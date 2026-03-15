"""GitHub API client for finding engineers and their work."""

import httpx

from app.config import settings

GITHUB_BASE_URL = "https://api.github.com"


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
