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
    terms = " ".join(k for k in keywords[:3] if k)
    if not terms:
        return []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{GITHUB_BASE_URL}/search/repositories",
                params={
                    "q": f"org:{org_name} {terms} in:name,description,readme",
                    "per_page": "3",
                    "sort": "updated",
                },
                headers=_headers(),
            )
            if resp.status_code in (403, 404, 422):
                return []
            resp.raise_for_status()
            repos = resp.json().get("items") or []

            logins: list[str] = []
            seen: set[str] = set()
            repo_names: dict[str, str] = {}
            for repo in repos:
                contrib_resp = await client.get(
                    f"{GITHUB_BASE_URL}/repos/{org_name}/{repo['name']}/contributors",
                    params={"per_page": "10"},
                    headers=_headers(),
                )
                if contrib_resp.status_code != 200:
                    continue
                for contributor in contrib_resp.json():
                    login = contributor.get("login")
                    if login and login.lower() not in seen and contributor.get("type") == "User":
                        seen.add(login.lower())
                        logins.append(login)
                        repo_names[login] = repo["name"]
                    if len(logins) >= limit:
                        break
                if len(logins) >= limit:
                    break

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
                        "full_name": profile.get("name") or login,
                        "github_url": profile.get("html_url", ""),
                        "location": profile.get("location"),
                        "bio": profile.get("bio"),
                        "team_repo": repo_names.get(login),
                    }
                )
            return results
    except Exception:
        logger.warning("team contributor search failed for org=%s", org_name, exc_info=True)
        return []
