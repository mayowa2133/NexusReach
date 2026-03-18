"""Email suggestion client — generate best-guess emails with confidence scores.

For domains that block SMTP verification (Proofpoint, Mimecast, etc.), this
client generates the most likely email address based on known company patterns.
Returns an unverified suggestion with a confidence score (0-100) so the user
can decide whether to trust it or spend paid API credits on verification.
"""

import logging
import unicodedata

logger = logging.getLogger(__name__)

VALID_FORMATS = {
    "first.last",
    "firstlast",
    "flast",
    "first",
    "firstl",
    "first_last",
    "last.first",
}


def _normalize(name: str) -> str:
    """Normalize a name: lowercase, strip accents, remove non-alpha chars."""
    normalized = unicodedata.normalize("NFD", name)
    stripped = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    return "".join(c for c in stripped if c.isalpha()).lower()


# --------------------------------------------------------------------------- #
# Known email patterns for major companies that block SMTP verification.
#
# Format templates:
#   "first.last"  -> john.doe@domain.com
#   "firstlast"   -> johndoe@domain.com
#   "flast"       -> jdoe@domain.com
#   "first"       -> john@domain.com
#   "firstl"      -> johnd@domain.com
#   "first_last"  -> john_doe@domain.com
#   "last.first"  -> doe.john@domain.com
#
# Base confidence reflects how consistent the company's pattern is across
# public data (GitHub commits, conference talks, job postings, Hunter stats).
# --------------------------------------------------------------------------- #
KNOWN_COMPANY_PATTERNS: dict[str, tuple[str, int]] = {
    # Big Tech — hardened infrastructure or confirmed SEG
    "amazon.com":       ("first.last",  90),
    "google.com":       ("first",       85),
    "meta.com":         ("firstlast",   80),
    "microsoft.com":    ("first.last",  85),
    "apple.com":        ("first_last",  75),
    "nvidia.com":       ("first.last",  85),
    "salesforce.com":   ("first.last",  85),
    "oracle.com":       ("first.last",  80),
    "ibm.com":          ("first.last",  75),
    "intel.com":        ("first.last",  80),
    "cisco.com":        ("first.last",  80),
    "intuit.com":       ("first.last",  85),
    "adobe.com":        ("first.last",  80),
    "qualcomm.com":     ("first.last",  80),
    "sap.com":          ("first.last",  75),
    "cloudflare.com":   ("first.last",  80),
    # Canadian banks
    "rbc.com":          ("first.last",  75),
    "td.com":           ("first.last",  70),
    "scotiabank.com":   ("first.last",  70),
    "bmo.com":          ("first.last",  70),
    "cibc.com":         ("first.last",  70),
    # Additional major tech companies
    "linkedin.com":     ("first.last",  80),
    "github.com":       ("first.last",  75),
    "netflix.com":      ("first.last",  80),
    "uber.com":         ("first.last",  80),
    "airbnb.com":       ("first.last",  75),
    "stripe.com":       ("first.last",  80),
    "shopify.com":      ("first.last",  80),
    "databricks.com":   ("first.last",  80),
    "snowflake.com":    ("first.last",  80),
    "palantir.com":     ("first.last",  80),
    "servicenow.com":   ("first.last",  80),
    "workday.com":      ("first.last",  80),
    "vmware.com":       ("first.last",  80),
    "dell.com":         ("first_last",  75),
    "hp.com":           ("first.last",  75),
    "paypal.com":       ("first.last",  80),
    "square.com":       ("first.last",  75),
    "block.xyz":        ("first.last",  70),
    "twitter.com":      ("first.last",  75),
    "x.com":            ("first.last",  70),
    "snap.com":         ("first.last",  80),
    "pinterest.com":    ("first.last",  80),
    "lyft.com":         ("first.last",  80),
    "doordash.com":     ("first.last",  80),
    "instacart.com":    ("first.last",  80),
    "coinbase.com":     ("first.last",  80),
    "robinhood.com":    ("first.last",  80),
    "plaid.com":        ("first.last",  80),
    "figma.com":        ("first.last",  80),
    "notion.so":        ("first.last",  75),
    "openai.com":       ("first.last",  80),
    "anthropic.com":    ("first.last",  80),
}

# Default pattern for unknown domains — most common corporate format
DEFAULT_PATTERN = "first.last"
DEFAULT_CONFIDENCE = 40


def _apply_format(fmt: str, first: str, last: str, domain: str) -> str | None:
    """Apply a format template to generate an email address.

    Args:
        fmt: Format template key (e.g. "first.last", "flast", "firstlast").
        first: Normalized first name.
        last: Normalized last name.
        domain: Company domain.

    Returns:
        Generated email address, or None if inputs are insufficient.
    """
    if not first or not domain:
        return None

    formats: dict[str, str] = {
        "first.last":  f"{first}.{last}@{domain}" if last else None,
        "firstlast":   f"{first}{last}@{domain}" if last else None,
        "flast":       f"{first[0]}{last}@{domain}" if last else None,
        "first":       f"{first}@{domain}",
        "firstl":      f"{first}{last[0]}@{domain}" if last else None,
        "first_last":  f"{first}_{last}@{domain}" if last else None,
        "last.first":  f"{last}.{first}@{domain}" if last else None,
    }

    return formats.get(fmt)


def infer_pattern(email: str, first_name: str, last_name: str, domain: str) -> str | None:
    """Infer the email format used by a known address."""
    first = _normalize(first_name)
    last = _normalize(last_name)
    domain = (domain or "").lower().strip()
    if not first or not last or not domain or not email:
        return None

    local_part = email.lower().strip()
    if local_part.endswith(f"@{domain}"):
        local_part = local_part[: -(len(domain) + 1)]

    for fmt in VALID_FORMATS:
        candidate = _apply_format(fmt, first, last, domain)
        if candidate and candidate.split("@", 1)[0] == local_part:
            return fmt
    return None


def _generate_ranked_suggestions(
    first: str,
    last: str,
    domain: str,
    known_fmt: str | None,
    base_confidence: int,
) -> list[dict]:
    """Generate ranked email suggestions for a person at a domain.

    The primary suggestion uses the known pattern (if available) or the
    default first.last format. Secondary suggestions use other common
    patterns with decreasing confidence.

    Returns:
        List of {"email": str, "confidence": int} dicts, highest first.
    """
    suggestions: list[dict] = []

    # Primary suggestion — known or default pattern
    primary_fmt = known_fmt or DEFAULT_PATTERN
    primary_email = _apply_format(primary_fmt, first, last, domain)
    if primary_email:
        suggestions.append({
            "email": primary_email,
            "confidence": base_confidence,
        })

    # Secondary suggestions — other common patterns (lower confidence)
    alternates = ["first.last", "flast", "firstlast", "first", "first_last"]
    for alt_fmt in alternates:
        if alt_fmt == primary_fmt:
            continue
        alt_email = _apply_format(alt_fmt, first, last, domain)
        if alt_email:
            # Each alternate is 20 points less confident than the primary,
            # with a floor of 15
            alt_confidence = max(base_confidence - 20, 15)
            suggestions.append({
                "email": alt_email,
                "confidence": alt_confidence,
            })

    return suggestions


def suggest_email(
    first_name: str,
    last_name: str,
    domain: str,
    preferred_format: str | None = None,
    preferred_confidence: int | None = None,
) -> dict | None:
    """Generate a best-guess email with confidence score for a blocked domain.

    Uses known company patterns (for major companies) or defaults to the
    most common corporate format (first.last@domain). This is a synchronous,
    zero-cost operation — no API calls or network I/O.

    Args:
        first_name: Person's first name.
        last_name: Person's last name.
        domain: Company domain (e.g. "amazon.com").

    Returns:
        Dict with keys:
            - email: str — best-guess email address
            - confidence: int — 0-100 confidence score
            - source: "pattern_suggestion"
            - verified: False
            - suggestions: list[dict] — ranked alternatives
            - known_company: bool — whether domain was in our pattern database
        Or None if insufficient input.
    """
    first = _normalize(first_name)
    last = _normalize(last_name)
    domain = (domain or "").lower().strip()

    if not first or not last or not domain:
        return None

    # Look up known pattern
    pattern_entry = KNOWN_COMPANY_PATTERNS.get(domain)
    if preferred_format in VALID_FORMATS:
        known_fmt = preferred_format
        base_confidence = preferred_confidence or 75
        known_company = True
    elif pattern_entry:
        known_fmt, base_confidence = pattern_entry
        known_company = True
    else:
        known_fmt = DEFAULT_PATTERN
        base_confidence = DEFAULT_CONFIDENCE
        known_company = False

    # Generate primary email
    primary_email = _apply_format(known_fmt, first, last, domain)
    if not primary_email:
        return None

    # Generate ranked alternatives
    suggestions = _generate_ranked_suggestions(
        first, last, domain, known_fmt, base_confidence
    )

    logger.debug(
        "Email suggestion for %s %s @ %s: %s (confidence=%d, known=%s)",
        first_name, last_name, domain, primary_email, base_confidence, known_company,
    )

    return {
        "email": primary_email,
        "confidence": base_confidence,
        "source": "pattern_suggestion",
        "verified": False,
        "suggestions": suggestions,
        "known_company": known_company,
    }
