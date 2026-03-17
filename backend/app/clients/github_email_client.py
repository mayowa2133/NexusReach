"""GitHub email extraction client — finds emails from profiles and commit history."""

import re
from collections import Counter

import httpx

from app.config import settings

GITHUB_BASE_URL = "https://api.github.com"
NOREPLY_PATTERN = re.compile(r"(noreply\.github\.com$|^noreply@github\.com$)", re.IGNORECASE)


def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        h["Authorization"] = f"Bearer {settings.github_token}"
    return h


def _extract_username(github_url: str) -> str | None:
    """Parse a GitHub URL to extract the username.

    Handles:
        https://github.com/johndoe
        https://github.com/johndoe/
        http://github.com/johndoe
        github.com/johndoe
    """
    if not github_url:
        return None
    # Strip protocol and www
    url = github_url.strip().rstrip("/")
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^www\.", "", url)
    if not url.startswith("github.com/"):
        return None
    parts = url.split("/")
    if len(parts) >= 2 and parts[1]:
        return parts[1]
    return None


def _is_noreply(email: str) -> bool:
    """Check if an email is a GitHub noreply address."""
    return bool(NOREPLY_PATTERN.search(email))


async def get_profile_email(github_url: str) -> str | None:
    """Get the public email from a GitHub user profile.

    Returns:
        Email string if the user has a public email set, None otherwise.
    """
    username = _extract_username(github_url)
    if not username:
        return None

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{GITHUB_BASE_URL}/users/{username}",
                headers=_headers(),
            )
            if resp.status_code != 200:
                return None
            user = resp.json()
    except (httpx.HTTPError, ValueError):
        return None

    email = user.get("email")
    if email and "@" in email and not _is_noreply(email):
        return email
    return None


async def get_commit_email(
    github_url: str,
    company_domain: str | None = None,
) -> str | None:
    """Extract email from recent public commit events.

    Looks at PushEvent payloads to find the commit author email.
    Filters out noreply addresses. If company_domain is provided,
    prefers emails matching that domain.

    Returns:
        Most likely real email, or None.
    """
    username = _extract_username(github_url)
    if not username:
        return None

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{GITHUB_BASE_URL}/users/{username}/events/public",
                params={"per_page": 30},
                headers=_headers(),
            )
            if resp.status_code != 200:
                return None
            events = resp.json()
    except (httpx.HTTPError, ValueError):
        return None

    # Collect emails from push event commits
    emails: list[str] = []
    for event in events:
        if event.get("type") != "PushEvent":
            continue
        commits = event.get("payload", {}).get("commits", [])
        for commit in commits:
            author = commit.get("author", {})
            email = author.get("email", "")
            if email and "@" in email and not _is_noreply(email):
                emails.append(email.lower().strip())

    if not emails:
        return None

    # If company domain provided, prefer matching emails
    if company_domain:
        domain_lower = company_domain.lower().strip()
        domain_emails = [e for e in emails if e.endswith(f"@{domain_lower}")]
        if domain_emails:
            # Return most frequent domain-matching email
            counter = Counter(domain_emails)
            return counter.most_common(1)[0][0]

    # Return most frequent email overall
    counter = Counter(emails)
    return counter.most_common(1)[0][0]
