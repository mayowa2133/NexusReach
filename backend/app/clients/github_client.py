"""GitHub API client for finding engineers and their work."""

import logging

import httpx

from app.config import settings

GITHUB_BASE_URL = "https://api.github.com"


logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        h["Authorization"] = f"Bearer {settings.github_token}"
    return h


async def search_org_members(org_name: str, limit: int = 10) -> list[dict]:
    """Find public members of a GitHub organization.

    Args:
        org_name: GitHub organization slug (e.g. "vercel").
        limit: Max members to return.

    Returns:
        List of member dicts with login, profile URL, etc.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{GITHUB_BASE_URL}/orgs/{org_name}/members",
            params={"per_page": min(limit, 30)},
            headers=_headers(),
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        members = resp.json()

    results = []
    # Fetch profile details for each member (up to limit)
    async with httpx.AsyncClient(timeout=15) as client:
        for member in members[:limit]:
            user_resp = await client.get(
                f"{GITHUB_BASE_URL}/users/{member['login']}",
                headers=_headers(),
            )
            if user_resp.status_code != 200:
                continue
            user = user_resp.json()
            results.append({
                "full_name": user.get("name") or user.get("login", ""),
                "login": user.get("login", ""),
                "github_url": user.get("html_url", ""),
                "bio": user.get("bio", ""),
                "company": user.get("company", ""),
                "location": user.get("location", ""),
                "public_repos": user.get("public_repos", 0),
                "followers": user.get("followers", 0),
                "source": "github",
            })

    return results


async def get_user_repos(username: str, limit: int = 5) -> list[dict]:
    """Get a user's top repositories by stars.

    Args:
        username: GitHub username.
        limit: Max repos to return.

    Returns:
        List of repo dicts with name, description, language, stars, url.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{GITHUB_BASE_URL}/users/{username}/repos",
            params={"sort": "updated", "per_page": min(limit, 10), "type": "owner"},
            headers=_headers(),
        )
        if resp.status_code != 200:
            return []
        repos = resp.json()

    return [
        {
            "name": repo.get("name", ""),
            "description": repo.get("description", ""),
            "language": repo.get("language", ""),
            "stars": repo.get("stargazers_count", 0),
            "url": repo.get("html_url", ""),
            "updated_at": repo.get("updated_at", ""),
        }
        for repo in repos[:limit]
    ]


async def get_user_profile(username: str) -> dict | None:
    """Get full GitHub profile for a user."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{GITHUB_BASE_URL}/users/{username}",
            headers=_headers(),
        )
        if resp.status_code != 200:
            return None
        user = resp.json()

    repos = await get_user_repos(username)
    languages = list({r["language"] for r in repos if r.get("language")})

    return {
        "full_name": user.get("name") or user.get("login", ""),
        "login": user.get("login", ""),
        "github_url": user.get("html_url", ""),
        "bio": user.get("bio", ""),
        "company": user.get("company", ""),
        "location": user.get("location", ""),
        "public_repos": user.get("public_repos", 0),
        "followers": user.get("followers", 0),
        "languages": languages,
        "top_repos": repos,
        "source": "github",
    }


async def search_team_contributors(
    org_name: str,
    keywords: list[str],
    limit: int = 8,
) -> list[dict]:
    """Find contributors to the org repos that match the job's team keywords.

    Far more precise than org-wide members: contributors to the payments
    repos ARE the payments team. Falls back to [] on any API limitation so
    callers can use org members instead.
    """
    kw = [k.lower() for k in keywords[:3] if k]
    terms = " ".join(kw)
    if not terms:
        return []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{GITHUB_BASE_URL}/search/repositories",
                params={
                    "q": f"org:{org_name} {terms} in:name,description,readme",
                    "per_page": "8",
                    "sort": "updated",
                },
                headers=_headers(),
            )
            if resp.status_code in (403, 404, 422):
                return []
            resp.raise_for_status()
            repos = resp.json().get("items") or []

            # Prefer repos whose NAME matches the team keywords (an Android job
            # should mine stripe-terminal-android before -react-native/-ios),
            # then by recency. Limit to the top few to keep API calls bounded.
            def _repo_score(repo: dict) -> tuple:
                name = (repo.get("name") or "").lower()
                name_hits = sum(1 for k in kw if k in name)
                return (name_hits, repo.get("pushed_at") or repo.get("updated_at") or "")
            repos = sorted(repos, key=_repo_score, reverse=True)[:3]

            # Rank by RECENT commit authorship, not all-time contributions:
            # all-time counts are dominated by long-departed heavy committers,
            # while recent commits identify the current team.
            seen: set[str] = set()
            repo_names: dict[str, str] = {}
            recent_counts: dict[str, int] = {}
            logins: list[str] = []
            for repo in repos:
                commits_resp = await client.get(
                    f"{GITHUB_BASE_URL}/repos/{org_name}/{repo['name']}/commits",
                    params={"per_page": "40"},
                    headers=_headers(),
                )
                if commits_resp.status_code != 200:
                    continue
                for commit in commits_resp.json():
                    author = commit.get("author")
                    login = author.get("login") if isinstance(author, dict) else None
                    if not login or (isinstance(author, dict) and author.get("type") != "User"):
                        continue
                    recent_counts[login] = recent_counts.get(login, 0) + 1
                    if login.lower() not in seen:
                        seen.add(login.lower())
                        logins.append(login)
                        repo_names[login] = repo["name"]
            contrib_counts = recent_counts
            logins.sort(key=lambda lg: recent_counts.get(lg, 0), reverse=True)
            logins = logins[:limit]

            results: list[dict] = []
            for login in logins[:limit]:
                profile_resp = await client.get(
                    f"{GITHUB_BASE_URL}/users/{login}", headers=_headers()
                )
                if profile_resp.status_code != 200:
                    continue
                profile = profile_resp.json()
                results.append(
                    {
                        "login": login,
                        "name": profile.get("name"),
                        "full_name": profile.get("name") or login,
                        "company": profile.get("company"),
                        "github_url": profile.get("html_url", ""),
                        "location": profile.get("location"),
                        "bio": profile.get("bio"),
                        "team_repo": repo_names.get(login),
                        "_github_contributions": contrib_counts.get(login, 0),
                    }
                )
            return results
    except Exception:
        logger.warning("team contributor search failed for org=%s", org_name, exc_info=True)
        return []


async def get_org(slug: str) -> dict | None:
    """Return the GitHub org for *slug*, or None if it does not exist.

    Used to validate a guessed org slug before trusting it as the company's
    engineering org.
    """
    if not slug:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{GITHUB_BASE_URL}/orgs/{slug}", headers=_headers())
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        logger.debug("get_org failed for slug=%s", slug, exc_info=True)
    return None
