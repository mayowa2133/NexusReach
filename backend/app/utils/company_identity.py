"""Helpers for canonicalizing company identity, public slugs, and domain trust."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

LEGAL_SUFFIX_TOKENS = {
    "co",
    "company",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "ltd",
    "limited",
    "llc",
    "plc",
    "gmbh",
    "ag",
    "pte",
    "pty",
}
LEADING_STOP_TOKENS = {"the"}
SAFE_AMBIGUOUS_SLUG_SUFFIXES = {
    "hq",
    "app",
    "labs",
    "team",
    "dev",
    "jobs",
    "careers",
}
SAFE_PUBLIC_IDENTITY_VARIANT_TOKENS = LEGAL_SUFFIX_TOKENS | SAFE_AMBIGUOUS_SLUG_SUFFIXES | {
    "career",
    "careers",
    "jobs",
    "media",
    "magazine",
    "news",
    "digital",
    "press",
    "live",
    "studios",
    "studio",
}
TRUSTED_PUBLIC_SLUG_HOSTS = {
    "theorg.com",
    "www.theorg.com",
    "linkedin.com",
    "www.linkedin.com",
}
GENERIC_CAREERS_HOST_ROOTS = {
    "greenhouse",
    "lever",
    "ashbyhq",
    "workable",
    "myworkdayjobs",
}

# ---------------------------------------------------------------------------
# Parent ↔ subsidiary / brand mapping
#
# Maps a *normalized* parent name to a frozenset of normalized subsidiary
# names, and vice-versa.  ``company_family()`` returns the full family set
# for any member (including itself).
# ---------------------------------------------------------------------------

_COMPANY_FAMILIES: list[frozenset[str]] = [
    frozenset({"bytedance", "tiktok", "tiktok shop", "lark", "pico"}),
    frozenset({"alphabet", "google", "deepmind", "waymo", "youtube", "google cloud", "verily", "wing"}),
    frozenset({"meta", "facebook", "instagram", "whatsapp", "meta platforms", "oculus", "threads"}),
    frozenset({"microsoft", "linkedin", "github", "azure", "nuance"}),
    frozenset({"amazon", "aws", "amazon web services", "twitch", "whole foods", "ring", "audible"}),
    frozenset({"apple", "apple inc"}),
    frozenset({"salesforce", "slack", "tableau", "mulesoft"}),
    frozenset({"broadcom", "vmware", "symantec"}),
    frozenset({"oracle", "netsuite", "cerner"}),
    frozenset({"uber", "uber eats", "uber freight"}),
    frozenset({"snap", "snapchat"}),
    frozenset({"block", "square", "cash app", "afterpay", "tidal"}),
    frozenset({"paypal", "venmo", "braintree"}),
    frozenset({"intuit", "turbotax", "quickbooks", "credit karma", "mailchimp"}),
    frozenset({"cisco", "webex", "splunk"}),
    frozenset({"ibm", "red hat", "hashicorp"}),
    frozenset({"samsung", "samsung electronics", "samsung semiconductor"}),
    frozenset({"jpmorgan", "jp morgan", "jpmorgan chase", "chase"}),
]

# Build a lookup: normalized_name → frozenset of the full family.
_FAMILY_LOOKUP: dict[str, frozenset[str]] = {}
for _family in _COMPANY_FAMILIES:
    for _member in _family:
        _FAMILY_LOOKUP[_member] = _family


def company_family(name: str | None) -> frozenset[str]:
    """Return the full family of related company names (normalized).

    If the company isn't in any known family, returns a singleton set
    containing the normalized name itself.
    """
    normalized = normalize_company_name(name)
    return _FAMILY_LOOKUP.get(normalized, frozenset({normalized}))


@dataclass
class PublicIdentityHints:
    slugs: list[str] = field(default_factory=list)
    hints: dict = field(default_factory=dict)


def _tokens(value: str | None) -> list[str]:
    return re.findall(r"[a-z0-9]+", (value or "").lower())


def normalize_company_name(value: str | None) -> str:
    tokens = _tokens(value)
    filtered = [token for token in tokens if token not in LEGAL_SUFFIX_TOKENS]
    while filtered and filtered[0] in LEADING_STOP_TOKENS:
        filtered = filtered[1:]
    canonical = filtered or tokens
    return " ".join(canonical)


def canonical_company_display_name(value: str | None) -> str:
    stripped = " ".join((value or "").split()).strip()
    if not stripped:
        return ""
    if stripped.islower():
        return " ".join(token.capitalize() for token in stripped.split())
    return stripped


def slugify_company_name(value: str | None) -> str:
    return "-".join(normalize_company_name(value).split())


def is_ambiguous_company_name(value: str | None) -> bool:
    normalized = normalize_company_name(value)
    if not normalized:
        return False
    tokens = normalized.split()
    return len(tokens) == 1 and len(tokens[0]) <= 4


def _slug_tokens(value: str | None) -> list[str]:
    return [token for token in (value or "").strip().lower().split("-") if token]


def _slug_variant_matches(base_slug: str | None, candidate_slug: str | None) -> bool:
    base_tokens = _slug_tokens(base_slug)
    candidate_tokens = _slug_tokens(candidate_slug)
    if not base_tokens or not candidate_tokens:
        return False
    if candidate_tokens == base_tokens:
        return True

    base_compact = "".join(base_tokens)
    candidate_compact = "".join(candidate_tokens)
    if not base_compact or not candidate_compact:
        return False

    if len(base_tokens) == 1:
        if candidate_tokens[0] == base_tokens[0]:
            extra_tokens = candidate_tokens[1:]
            return bool(extra_tokens) and all(
                token in SAFE_PUBLIC_IDENTITY_VARIANT_TOKENS for token in extra_tokens
            )
        if candidate_compact.startswith(base_compact):
            suffix = candidate_compact[len(base_compact):]
            return bool(suffix) and suffix in SAFE_AMBIGUOUS_SLUG_SUFFIXES
        return False

    if candidate_tokens[:len(base_tokens)] == base_tokens:
        extra_tokens = candidate_tokens[len(base_tokens):]
        return bool(extra_tokens) and all(
            token in SAFE_PUBLIC_IDENTITY_VARIANT_TOKENS for token in extra_tokens
        )
    return False


def domain_root(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    host = urlparse(raw if "://" in raw else f"https://{raw}").netloc.lower()
    if not host:
        host = raw.split("/")[0]
    parts = [part for part in host.split(".") if part]
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in {"co", "com", "org", "net"}:
        return parts[-3]
    if len(parts) >= 2:
        return parts[-2]
    return parts[0] if parts else ""


def should_trust_company_enrichment(
    requested_name: str,
    *,
    resolved_name: str | None = None,
    domain: str | None = None,
) -> bool:
    requested_normalized = normalize_company_name(requested_name)
    if not requested_normalized:
        return False

    resolved_normalized = normalize_company_name(resolved_name or requested_name)
    if requested_normalized != resolved_normalized:
        return False

    if not domain:
        return False

    if is_ambiguous_company_name(requested_name):
        return False

    return normalize_company_name(domain_root(domain)) == requested_normalized


def _slug_from_path_segment(url: str | None, expected_prefixes: tuple[str, ...]) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    for prefix in expected_prefixes:
        if prefix in parts:
            index = parts.index(prefix)
            if len(parts) > index + 1:
                return parts[index + 1].strip().lower()
    return ""


def extract_public_identity_hints(url: str | None) -> dict:
    if not url:
        return {}
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    parts = [part for part in parsed.path.split("/") if part]

    if "theorg.com" in host and len(parts) >= 2 and parts[0] == "org":
        hints = {
            "host": host,
            "company_slug": parts[1].lower(),
            "page_type": "org",
        }
        if len(parts) >= 4 and parts[2] == "teams":
            hints["page_type"] = "team"
            hints["team_slug"] = parts[3].lower()
        elif "org-chart" in parts and len(parts) >= 4:
            hints["page_type"] = "org_chart_person"
            hints["person_slug"] = parts[3].lower()
        return hints

    if "linkedin.com" in host and len(parts) >= 2 and parts[0] == "company":
        return {
            "host": host,
            "company_slug": parts[1].lower(),
            "page_type": "linkedin_company",
        }

    return {"host": host} if host else {}


def is_compatible_public_identity_slug(company_name: str, candidate_slug: str | None) -> bool:
    slug = (candidate_slug or "").strip().lower()
    if not slug:
        return False

    expected_slug = slugify_company_name(company_name)
    expected = expected_slug.replace("-", "")
    candidate_compact = slug.replace("-", "")
    if not expected_slug or not expected:
        return False
    if candidate_compact == expected:
        return True

    return _slug_variant_matches(expected_slug, slug)


def _merge_slug(slugs: set[str], slug: str | None, *, company_name: str) -> None:
    clean = (slug or "").strip().lower()
    if not clean:
        return
    if is_compatible_public_identity_slug(company_name, clean):
        slugs.add(clean)


def effective_public_identity_slugs(
    company_name: str,
    public_identity_slugs: list[str] | None = None,
    *,
    identity_hints: dict | None = None,
) -> list[str]:
    hints = dict(identity_hints or {})
    official_aliases = {
        slugify_company_name(company_name),
        (hints.get("normalized_slug") or "").strip().lower(),
        (hints.get("ats_slug") or "").strip().lower(),
        (hints.get("linkedin_company_slug") or "").strip().lower(),
        (hints.get("domain_root") or "").strip().lower(),
    }
    careers_host = (hints.get("careers_host") or "").strip().lower()
    if careers_host:
        careers_root = domain_root(careers_host)
        if careers_root and careers_root not in GENERIC_CAREERS_HOST_ROOTS:
            official_aliases.add(careers_root)

    aliases = {alias for alias in official_aliases if alias}
    filtered: set[str] = set(aliases)
    for raw_slug in public_identity_slugs or []:
        slug = (raw_slug or "").strip().lower()
        if not slug:
            continue
        if slug in aliases or is_compatible_public_identity_slug(company_name, slug):
            filtered.add(slug)
            continue
        if any(_slug_variant_matches(alias, slug) for alias in aliases):
            filtered.add(slug)
    return sorted(filtered)


def build_public_identity_hints(
    company_name: str,
    *,
    existing_slugs: list[str] | None = None,
    existing_hints: dict | None = None,
    ats_slug: str | None = None,
    domain: str | None = None,
    careers_url: str | None = None,
    linkedin_company_url: str | None = None,
) -> PublicIdentityHints:
    slugs: set[str] = set((existing_slugs or []))
    hints = dict(existing_hints or {})

    base_slug = slugify_company_name(company_name)
    if base_slug:
        slugs.add(base_slug)
        hints.setdefault("normalized_slug", base_slug)
        if is_ambiguous_company_name(company_name):
            slugs.add(f"{base_slug}hq")

    if ats_slug:
        clean_ats_slug = ats_slug.strip().lower()
        if clean_ats_slug:
            slugs.add(clean_ats_slug)
            hints["ats_slug"] = clean_ats_slug

    domain_slug = domain_root(domain)
    if domain_slug:
        _merge_slug(slugs, domain_slug, company_name=company_name)
        hints["domain_root"] = domain_slug

    if careers_url:
        careers_host = urlparse(careers_url).netloc.lower()
        careers_slug = domain_root(careers_url)
        if careers_host:
            hints["careers_host"] = careers_host
        if careers_slug:
            _merge_slug(slugs, careers_slug, company_name=company_name)

    linkedin_slug = _slug_from_path_segment(linkedin_company_url, ("company",))
    if linkedin_slug:
        _merge_slug(slugs, linkedin_slug, company_name=company_name)
        hints["linkedin_company_slug"] = linkedin_slug

    return PublicIdentityHints(
        slugs=effective_public_identity_slugs(
            company_name,
            sorted(slugs),
            identity_hints=hints,
        ),
        hints=hints,
    )


def trusted_public_identity_slugs(
    company_name: str,
    public_identity_slugs: list[str] | None = None,
    *,
    ats_slug: str | None = None,
    domain: str | None = None,
    careers_url: str | None = None,
    linkedin_company_url: str | None = None,
) -> list[str]:
    return build_public_identity_hints(
        company_name,
        existing_slugs=public_identity_slugs,
        ats_slug=ats_slug,
        domain=domain,
        careers_url=careers_url,
        linkedin_company_url=linkedin_company_url,
    ).slugs


def matches_public_company_identity(
    public_url: str | None,
    company_name: str,
    trusted_slugs: list[str] | None = None,
) -> bool:
    hints = extract_public_identity_hints(public_url)
    host = hints.get("host", "")
    slug = hints.get("company_slug", "")
    if not host or host not in TRUSTED_PUBLIC_SLUG_HOSTS:
        return False
    if not slug:
        return False

    slug = slug.lower()
    trusted_raw = {item.lower() for item in trusted_slugs or [] if item}
    trusted = trusted_raw | set(
        effective_public_identity_slugs(
            company_name,
            list(trusted_raw),
        )
    )
    if trusted and slug in trusted:
        return True

    if trusted and any(_slug_variant_matches(trusted_slug, slug) for trusted_slug in trusted):
        return True

    if trusted:
        return False

    return is_compatible_public_identity_slug(company_name, slug)
