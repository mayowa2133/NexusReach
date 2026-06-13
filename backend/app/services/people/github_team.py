"""GitHub-team strategy: contributors to a company's repos -> LinkedIn titles.

For an engineering role at a company with public repos, the contributor graph
of the repos that match the job's team keywords *is* the team. Resolving each
top contributor's LinkedIn title turns that graph into named, classified
contacts: the lead/manager-titled contributor becomes a hiring-manager
candidate, the rest become high-confidence peers (they verifiably do the exact
work). This reaches the team's manager that generic LinkedIn x-ray cannot,
because it starts from "who actually ships this code" rather than from a title
guess.

Everything here is bounded (top N contributors), Redis-cached, and fails soft
to an empty list - it can never slow a search past the SERP timeout or break
one outright.
"""

from __future__ import annotations

import logging
import re

from app.clients import brave_search_client, github_client, search_cache_client
from app.services.people.company_match import _classify_employment_status
from app.utils.company_identity import normalize_company_name

logger = logging.getLogger(__name__)

ORG_CACHE_PREFIX = "people:github_org:v1:"
ORG_CACHE_TTL_SECONDS = 30 * 86400
MAX_CONTRIBUTORS_RESOLVED = 6

# Logins that are bots/automation, never people.
_BOT_LOGIN_RE = re.compile(r"(\[bot\]|-bot$|^dependabot|^github-actions)", re.IGNORECASE)


def _looks_like_real_name(name: str | None, login: str) -> bool:
    """True when the GitHub profile name is a usable human name, not a login.

    LinkedIn resolution needs a real "First Last"; a bare login like
    ``danwaters-stripe`` cannot be split reliably, so those are skipped.
    """
    if not name:
        return False
    cleaned = name.strip()
    if cleaned.lower() == login.lower():
        return False
    return " " in cleaned and len(cleaned) >= 5


async def resolve_github_org(company_name: str, identity_hints: dict | None) -> str | None:
    """Resolve (and cache) the company's GitHub org slug, validated to exist.

    Order: cached identity hint -> Redis cache -> guess from the normalized
    company name and confirm via the GitHub API. Returns None when no real org
    is found, so callers simply skip the strategy.
    """
    if identity_hints and isinstance(identity_hints.get("github"), str):
        return identity_hints["github"]

    normalized = normalize_company_name(company_name) or ""
    slug_guess = re.sub(r"[^a-z0-9]", "", normalized.lower())
    if not slug_guess:
        return None

    cache_key = ORG_CACHE_PREFIX + slug_guess
    try:
        cached = await search_cache_client.get_json(cache_key)
    except Exception:
        cached = None
    if cached is not None:
        return cached or None  # cached may be "" meaning "validated absent"

    org = await github_client.get_org(slug_guess)
    resolved = slug_guess if org else ""
    try:
        await search_cache_client.set_json(cache_key, resolved, ttl_seconds=ORG_CACHE_TTL_SECONDS)
    except Exception:
        logger.debug("github org cache write failed", exc_info=True)
    return resolved or None


async def resolve_team_contacts(
    org: str,
    team_keywords: list[str],
    company_name: str,
    *,
    limit: int = MAX_CONTRIBUTORS_RESOLVED,
) -> list[dict]:
    """Return classified, LinkedIn-resolved contacts from the team's repos.

    Each returned candidate carries ``_github_team_member=True``, the
    contribution count, the matched repo, and a ``_github_bucket_hint`` of
    "hiring_manager" or "peer" from its resolved title. Candidates whose name
    cannot be resolved or whose LinkedIn evidence does not tie them to the
    company are dropped.
    """
    if not org or not team_keywords:
        return []
    try:
        contributors = await github_client.search_team_contributors(org, team_keywords, limit=limit)
    except Exception:
        logger.warning("team contributor fetch failed for org=%s", org, exc_info=True)
        return []

    # local import avoids a module-level cycle (classify imports nothing heavy,
    # but service imports this module, so keep the dependency one-directional)
    from app.services.people.classify import _classify_person_with_confidence

    contacts: list[dict] = []
    for contributor in contributors:
        login = contributor.get("login", "")
        if _BOT_LOGIN_RE.search(login):
            continue
        name = contributor.get("name")
        if not _looks_like_real_name(name, login):
            continue
        contributions = contributor.get("_github_contributions", 0)
        team_repo = contributor.get("team_repo")

        title, snippet, linkedin_url = await _resolve_linkedin(name, company_name, team_keywords)

        # The GitHub-org contribution is itself the company gate: writing commits
        # to <org>/<repo> means this person is on that team. LinkedIn is used
        # only to recover a TITLE for bucketing. So we never drop a contributor
        # for a weak LinkedIn snippet - we just decide how much to trust it:
        #   - former-employee marker  -> drop (they have left)
        #   - company clearly evidenced -> trust the title (HM promotion allowed)
        #   - otherwise (weak / wrong-person snippet) -> keep as a peer with a
        #     generic title and no LinkedIn URL, on GitHub evidence alone.
        candidate_for_status = {"title": title, "snippet": snippet, "source": "github_team"}
        if (title or snippet) and _classify_employment_status(
            candidate_for_status, company_name, None
        ) == "former":
            continue

        company_trusted = bool(title or snippet) and _company_evidenced(title, snippet, company_name)
        if company_trusted:
            bucket, _confident = _classify_person_with_confidence(title, snippet=snippet)
            bucket_hint = "hiring_manager" if bucket == "hiring_manager" else "peer"
            display_title = title or "Software Engineer"
            display_snippet = snippet or f"Contributor to {company_name}'s {team_repo or 'team'} repository."
            display_url = linkedin_url
        else:
            # Untrusted LinkedIn match (or none): keep on GitHub evidence as a
            # peer, but do not attach a possibly-wrong profile or promote to HM.
            bucket_hint = "peer"
            display_title = "Software Engineer"
            display_snippet = f"Recent contributor to {company_name}'s {team_repo or 'team'} repository."
            display_url = None

        contacts.append(
            {
                "full_name": name,
                "title": display_title,
                "source": "github_team",
                "snippet": display_snippet,
                "linkedin_url": display_url,
                "github_url": contributor.get("github_url", ""),
                "location": contributor.get("location"),
                "_github_team_member": True,
                "_github_contributions": contributions,
                "_team_repo": team_repo,
                "_github_bucket_hint": bucket_hint,
                "profile_data": {
                    "company_match_confidence": "strong_signal",
                    "github_team": True,
                    "github_team_repo": team_repo,
                    "github_contributions": contributions,
                },
            }
        )
    return contacts


async def _resolve_linkedin(
    name: str, company_name: str, team_keywords: list[str]
) -> tuple[str, str, str | None]:
    """Best-effort LinkedIn title/snippet/url for a named contributor."""
    try:
        results = await brave_search_client.search_exact_linkedin_profile(
            name, company_name, team_keywords=team_keywords[:2], limit=2
        )
    except Exception:
        logger.debug("linkedin resolution failed for %s", name, exc_info=True)
        return "", "", None
    if not results:
        return "", "", None
    top = results[0]
    return (top.get("title") or "").strip(), (top.get("snippet") or "").strip(), top.get("linkedin_url")


_FORMER_MARKER_RE = re.compile(
    r"\b(previously|formerly|ex[- ]|former|cofounder of|co-founder of|founder of)\b",
    re.IGNORECASE,
)


def _company_evidenced(title: str, snippet: str, company_name: str) -> bool:
    """Require LinkedIn evidence of *current* employment at the company.

    A contributor to a public repo could be an external open-source
    contributor or a same-named different person whose post merely mentions
    the company. So the company token must appear either in the headline
    (``title``) or as an explicit current-employment phrase ("at Stripe",
    "Experience: Stripe"), and any former-employment marker vetoes the match.
    When no LinkedIn evidence resolved at all, the GitHub-org contribution
    stands on its own and the contact is kept.
    """
    title_l = (title or "").lower()
    snippet_l = (snippet or "").lower()
    if not title_l and not snippet_l:
        return True
    normalized = (normalize_company_name(company_name) or company_name).lower()
    token = normalized.split()[0] if normalized else company_name.lower()
    if _FORMER_MARKER_RE.search(snippet_l):
        return False
    if token in title_l:
        return True
    for phrase in (f"at {token}", f"experience: {token}", f"{token} ·", f"@ {token}", f"{token},"):
        if phrase in snippet_l:
            return True
    return False
