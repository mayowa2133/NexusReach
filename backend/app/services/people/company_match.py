"""Company-identity and employment-status verification for people discovery."""

import logging
import re
from urllib.parse import urlparse


from app.utils.company_identity import (
    is_ambiguous_company_name,
    matches_public_company_identity,
    normalize_company_name,
)
from app.utils.job_context import (
    JobContext,
)

from app.services.people.context import _candidate_geo_signal_match, _location_match_rank
from app.services.people.identity import _identity_tokens, _is_linkedin_public_profile, _public_profile_host, _public_profile_url, _slugify
from app.services.people.titles import _role_like_title
logger = logging.getLogger(__name__)


CURRENT_TRUSTED_SOURCES = {
    "apollo",
    "proxycurl",
    "brave_hiring_team",
    "serper_hiring_team",
    # SearXNG is the default primary search provider; its hiring-team results
    # must be trusted on par with the paid fallbacks (audit C1).
    "searxng_hiring_team",
    # The company's own website leadership page and LinkedIn's hiring-team
    # panel name people the company itself publishes -> authoritative current.
    "company_site",
    "linkedin_hiring_team",
}


CURRENT_TRUSTED_PUBLIC_HOSTS = {
    "theorg.com",
    "www.theorg.com",
}


PUBLIC_WEB_SOURCES = {
    "brave_public_web",
    "serper_public_web",
    "tavily_public_web",
    "searxng_public_web",
}


FORMER_COMPANY_PATTERNS = (
    r"\bformer\b",
    r"\bformerly\b",
    r"\bpreviously\b",
    r"\bex[-\s]",
    r"\bpast\b",
)


AMBIGUOUS_COMPANY_NEGATIVE_SUFFIXES = {"co", "company", "limited", "ltd", "corp", "corporation"}


COMPANY_NEGATIVE_TERMS = {
    "zip": {"ziprecruiter"},
}


PUBLIC_DIRECTORY_TERMS = {
    "email & phone",
    "phone number",
    "staff directory",
    "company profile",
    "contact info",
    "contact information",
    "directory",
}


def _mentions_company(text: str, company_name: str) -> bool:
    company_tokens = normalize_company_name(company_name).split()
    text_tokens = _identity_tokens(text)
    if not company_tokens or not text_tokens:
        return False

    negative_terms = COMPANY_NEGATIVE_TERMS.get(company_tokens[0], set())
    if any(term in "".join(text_tokens) for term in negative_terms):
        return False

    company_length = len(company_tokens)
    for index in range(len(text_tokens) - company_length + 1):
        window = text_tokens[index:index + company_length]
        if window != company_tokens:
            continue
        if (
            is_ambiguous_company_name(company_name)
            and company_length == 1
            and index + company_length < len(text_tokens)
            and text_tokens[index + company_length] in AMBIGUOUS_COMPANY_NEGATIVE_SUFFIXES
        ):
            continue
        return True
    return False


def _linkedin_company_match(candidate: dict, company_name: str) -> bool:
    profile_data = candidate.get("profile_data") or {}
    result_title = profile_data.get("linkedin_result_title")
    texts = [candidate.get("snippet", ""), candidate.get("title", ""), result_title]
    return any(_mentions_company(str(text), company_name) for text in texts if text)


def _public_url_matches_company(public_url: str, company_name: str) -> bool:
    if not public_url:
        return False
    return _slugify(company_name) in urlparse(public_url).path.lower()


def _trusted_public_match(data: dict, company_name: str, public_identity_slugs: list[str] | None = None) -> bool:
    public_url = _public_profile_url(data)
    return matches_public_company_identity(public_url, company_name, public_identity_slugs)


def _trusted_public_peer_match(
    data: dict,
    *,
    company_name: str,
    public_identity_slugs: list[str] | None = None,
    context: JobContext | None = None,
) -> bool:
    if _trusted_public_match(data, company_name, public_identity_slugs):
        return True
    if not _is_linkedin_public_profile(data):
        return False

    title = data.get("title", "") or ""
    snippet = data.get("snippet", "") or ""
    linkedin_result_title = ((data.get("profile_data") or {}).get("linkedin_result_title", "") or "")
    location = data.get("location", "") or ((data.get("profile_data") or {}).get("location", "") or "")
    haystack = " ".join(part for part in [title, snippet, linkedin_result_title, location] if part)
    if not _mentions_company(haystack, company_name):
        return False
    employment_status = _classify_employment_status(data, company_name, public_identity_slugs)
    if employment_status == "former":
        return False
    if not (_role_like_title(title) or _role_like_title(snippet)):
        return False
    if context and context.job_locations:
        return _location_match_rank(data, context=context) == 0 or _candidate_geo_signal_match(data, context=context)
    return True


def _candidate_matches_company(
    data: dict,
    company_name: str,
    public_identity_slugs: list[str] | None = None,
) -> bool:
    source = data.get("source", "")
    if source in CURRENT_TRUSTED_SOURCES:
        return True

    title = data.get("title", "") or ""
    snippet = data.get("snippet", "") or ""
    # The LinkedIn result parser strips "@ Company" from the title for clean
    # display, but the original search result title still holds the company
    # reference.  Check it so that "Emerging Talent Recruiter @ Meta" still
    # matches even though the cleaned title is "Emerging Talent Recruiter".
    linkedin_result_title = (
        (data.get("profile_data") or {}).get("linkedin_result_title", "")
    )
    public_url = _public_profile_url(data)
    host = _public_profile_host(data)
    company_mentioned = (
        _mentions_company(title, company_name)
        or _mentions_company(snippet, company_name)
        or _mentions_company(linkedin_result_title, company_name)
        or _trusted_public_match(data, company_name, public_identity_slugs)
        or (
            not is_ambiguous_company_name(company_name)
            and _public_url_matches_company(public_url, company_name)
        )
    )

    if host in CURRENT_TRUSTED_PUBLIC_HOSTS and not _trusted_public_match(
        data,
        company_name,
        public_identity_slugs,
    ):
        return False

    if title and not _role_like_title(title) and not _mentions_company(title, company_name):
        return False

    combined_text = " ".join(part for part in [title, snippet] if part).lower()
    if data.get("source") in PUBLIC_WEB_SOURCES and any(term in combined_text for term in PUBLIC_DIRECTORY_TERMS):
        return False

    return company_mentioned


def _classify_employment_status(
    data: dict,
    company_name: str,
    public_identity_slugs: list[str] | None = None,
) -> str:
    source = data.get("source", "")
    title = data.get("title", "") or ""
    snippet = data.get("snippet", "") or ""
    host = _public_profile_host(data)
    haystack = " ".join(part for part in [title, snippet] if part).lower()

    if _mentions_company(haystack, company_name) and any(
        re.search(pattern, haystack) for pattern in FORMER_COMPANY_PATTERNS
    ):
        return "former"

    if source in CURRENT_TRUSTED_SOURCES:
        return "current"

    if host in CURRENT_TRUSTED_PUBLIC_HOSTS and _trusted_public_match(
        data,
        company_name,
        public_identity_slugs,
    ):
        return "current"

    current_company_patterns = (
        rf"\bcurrently\b.*\b{re.escape(company_name.lower())}\b",
        rf"\bcurrent\b.*\b{re.escape(company_name.lower())}\b",
        rf"\bworks?\s+at\b.*\b{re.escape(company_name.lower())}\b",
        rf"\bworking\s+at\b.*\b{re.escape(company_name.lower())}\b",
    )
    if any(re.search(pattern, haystack) for pattern in current_company_patterns):
        return "current"

    if _is_linkedin_public_profile(data):
        strong_public_profile_patterns = (
            rf"\babout\b.*\bi\s+(?:lead|manage|work|support)\b.*\b{re.escape(company_name.lower())}\b",
            r"\babout\b.*\bresponsible for hiring\b.*\b(?:canada|toronto|greater toronto area|gta)\b",
            rf"\bexperience\b.*\b{re.escape(company_name.lower())}\b",
        )
        if any(re.search(pattern, haystack) for pattern in strong_public_profile_patterns):
            return "current"

    if _mentions_company(title, company_name):
        return "current"

    # The LinkedIn parser strips "@ Company" from the display title, but the
    # original search result title retains it.  Use it for employment signal.
    linkedin_result_title = (
        (data.get("profile_data") or {}).get("linkedin_result_title", "")
    )
    if linkedin_result_title and _mentions_company(linkedin_result_title, company_name):
        return "current"

    if _mentions_company(snippet, company_name):
        return "ambiguous"

    return "ambiguous"
