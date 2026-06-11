"""Name, slug, keyword, and public-profile URL primitives for people discovery."""

import logging
import re
import unicodedata
from urllib.parse import urlparse



logger = logging.getLogger(__name__)


def _normalize_identity(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def _normalize_name_for_matching(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", ascii_only.lower()))


def _dedupe_text(values: list[str] | None) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        clean = " ".join((value or "").split()).strip()
        normalized = clean.lower()
        if not clean or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(clean)
    return ordered


def _contains_any_keyword(text: str | None, keywords: tuple[str, ...]) -> bool:
    normalized = _normalize_identity(text)
    return any(keyword in normalized for keyword in keywords)


def _identity_tokens(value: str | None) -> list[str]:
    return re.findall(r"[a-z0-9]+", (value or "").lower())


def _keyword_in_text(keyword: str, text: str) -> bool:
    if not text:
        return False
    if keyword == "backend":
        return "backend" in text or "back-end" in text or "server-side" in text
    if keyword == "decisioning":
        return "decisioning" in text or "decision engine" in text or "eligibility" in text
    return keyword.replace("_", " ") in text


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def _name_match_score(candidate_name: str | None, linkedin_name: str | None) -> int:
    candidate_tokens = _normalize_name_for_matching(candidate_name).split()
    linkedin_tokens = _normalize_name_for_matching(linkedin_name).split()
    if len(candidate_tokens) < 2 or len(linkedin_tokens) < 2:
        return 0

    candidate_first, candidate_last = candidate_tokens[0], candidate_tokens[-1]
    linkedin_first, linkedin_last = linkedin_tokens[0], linkedin_tokens[-1]

    if candidate_last == linkedin_last:
        if candidate_first != linkedin_first:
            return 0
        return 100 if candidate_tokens == linkedin_tokens else 96

    if (
        len(candidate_tokens) == 2
        and len(linkedin_tokens) == 2
        and candidate_first == linkedin_last
        and candidate_last == linkedin_first
    ):
        return 92

    if candidate_first != linkedin_first:
        return 0

    if len(candidate_last) == 1 and linkedin_last.startswith(candidate_last):
        return 90
    if len(linkedin_last) == 1 and candidate_last.startswith(linkedin_last):
        return 90
    return 0


def _linkedin_backfill_name_variants(full_name: str | None) -> list[str]:
    raw = (full_name or "").strip()
    if not raw:
        return []

    variants: list[str] = []
    normalized = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if normalized and normalized != raw:
        variants.append(normalized)

    comma_parts = [part.strip() for part in raw.split(",", 1)]
    if len(comma_parts) == 2 and all(comma_parts):
        variants.append(f"{comma_parts[1]} {comma_parts[0]}")

    raw_tokens = [token.strip() for token in re.split(r"\s+", raw) if token.strip()]
    cleaned_tokens = [re.sub(r"[^A-Za-z0-9'-]", "", token) for token in raw_tokens]
    cleaned_tokens = [token for token in cleaned_tokens if token]
    if len(cleaned_tokens) >= 3:
        without_middle_initials = [
            cleaned_tokens[0],
            *[token for token in cleaned_tokens[1:-1] if len(token) > 1],
            cleaned_tokens[-1],
        ]
        if len(without_middle_initials) >= 2:
            variants.append(" ".join(without_middle_initials))

    normalized_tokens = _normalize_name_for_matching(raw).split()
    if len(normalized_tokens) == 2:
        first, last = normalized_tokens
        variants.append(f"{last.title()} {first.title()}")

    ordered: list[str] = []
    seen: set[str] = set()
    canonical = _normalize_name_for_matching(raw)
    for variant in variants:
        clean_variant = " ".join(variant.split()).strip()
        if not clean_variant:
            continue
        normalized_variant = _normalize_name_for_matching(clean_variant)
        if not normalized_variant or normalized_variant == canonical or normalized_variant in seen:
            continue
        seen.add(normalized_variant)
        ordered.append(clean_variant)
    return ordered[:3]


def _public_profile_url(data: dict) -> str:
    profile_data = data.get("profile_data") or {}
    public_url = profile_data.get("public_url")
    return public_url if isinstance(public_url, str) else ""


def _public_profile_host(data: dict) -> str:
    public_url = _public_profile_url(data)
    if not public_url:
        return ""
    return urlparse(public_url).netloc.lower()


def _linkedin_profile_host(data: dict) -> str:
    linkedin_url = data.get("linkedin_url") or ""
    if not linkedin_url:
        return ""
    return urlparse(linkedin_url).netloc.lower()


def _is_linkedin_public_profile(data: dict) -> bool:
    hosts = {
        _public_profile_host(data),
        _linkedin_profile_host(data),
    }
    return any("linkedin.com" in host for host in hosts if host)
