"""Email pattern guesser + SMTP verification client.

Generates candidate emails from name + domain using common corporate
patterns, then verifies them via SMTP RCPT TO checks. Zero API cost.
"""

import asyncio
import logging
import unicodedata
import uuid

import aiodns

logger = logging.getLogger(__name__)

# Total timeout for the entire find_email_by_pattern operation
TOTAL_TIMEOUT_SECONDS = 30

# Timeout per individual SMTP connection
SMTP_TIMEOUT_SECONDS = 10

# Known Secure Email Gateway (SEG) MX record suffixes.
# Domains whose MX resolves to one of these are protected by a gateway that
# intercepts SMTP probes — RCPT TO results are meaningless. Skip SMTP entirely.
SEG_MX_PATTERNS: dict[str, str] = {
    "pphosted.com": "proofpoint",
    "ppe-hosted.com": "proofpoint",
    "mimecast.com": "mimecast",
    "barracudanetworks.com": "barracuda",
    "hydra.sophos.com": "sophos",
}


def _normalize(name: str) -> str:
    """Normalize a name: lowercase, strip accents, remove non-alpha chars."""
    # Decompose unicode and strip combining marks (accents)
    normalized = unicodedata.normalize("NFD", name)
    stripped = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    # Keep only alphabetic characters
    return "".join(c for c in stripped if c.isalpha()).lower()


def generate_candidates(first_name: str, last_name: str, domain: str) -> list[str]:
    """Generate candidate email addresses from name + domain.

    Returns candidates in priority order (most common corporate patterns first).
    """
    first = _normalize(first_name)
    last = _normalize(last_name)

    if not first or not last or not domain:
        return []

    domain = domain.lower().strip()

    return [
        f"{first}.{last}@{domain}",
        f"{first[0]}{last}@{domain}" if first else "",
        f"{first}{last[0]}@{domain}" if last else "",
        f"{first}@{domain}",
        f"{last}@{domain}",
        f"{first}_{last}@{domain}",
        f"{first}-{last}@{domain}",
        f"{last}{first[0]}@{domain}" if first else "",
    ]


async def _resolve_mx(domain: str) -> str | None:
    """Resolve the highest-priority MX record for a domain.

    Returns:
        MX hostname or None if resolution fails.
    """
    try:
        resolver = aiodns.DNSResolver()
        records = await resolver.query(domain, "MX")
        if not records:
            return None
        # Sort by priority (lowest = highest priority)
        records.sort(key=lambda r: r.priority)
        return str(records[0].host)
    except (aiodns.error.DNSError, Exception):
        return None


async def _smtp_command(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, command: str) -> str:
    """Send an SMTP command and read the response."""
    writer.write(f"{command}\r\n".encode())
    await writer.drain()
    response = await asyncio.wait_for(reader.readline(), timeout=SMTP_TIMEOUT_SECONDS)
    return response.decode("utf-8", errors="replace").strip()


async def _check_smtp(email: str, mx_host: str) -> bool | None:
    """Verify an email address via SMTP RCPT TO check.

    Returns:
        True if mailbox exists (250 response),
        False if rejected (5xx response),
        None if inconclusive (timeout, error, 4xx greylisting).
    """
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(mx_host, 25),
            timeout=SMTP_TIMEOUT_SECONDS,
        )

        try:
            # Read greeting
            greeting = await asyncio.wait_for(reader.readline(), timeout=SMTP_TIMEOUT_SECONDS)
            greeting_text = greeting.decode("utf-8", errors="replace").strip()
            if not greeting_text.startswith("220"):
                return None

            # HELO
            resp = await _smtp_command(reader, writer, "HELO nexusreach.local")
            if not resp.startswith("250"):
                return None

            # MAIL FROM
            resp = await _smtp_command(reader, writer, "MAIL FROM:<>")
            if not resp.startswith("250"):
                return None

            # RCPT TO — this is the actual check
            resp = await _smtp_command(reader, writer, f"RCPT TO:<{email}>")

            # Always quit cleanly
            try:
                await _smtp_command(reader, writer, "QUIT")
            except (asyncio.TimeoutError, OSError):
                pass

            if resp.startswith("250"):
                return True
            elif resp.startswith("5"):
                return False
            else:
                # 4xx = greylisting or temporary issue → inconclusive
                return None

        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (OSError, ConnectionError):
                pass

    except (asyncio.TimeoutError, OSError, ConnectionError):
        return None


async def _is_catch_all(domain: str, mx_host: str) -> bool:
    """Detect if a domain is catch-all (accepts any address).

    Probes with a random nonsense address. If the server accepts it,
    the domain accepts everything and SMTP verification is unreliable.
    """
    random_local = f"nexusreach-probe-{uuid.uuid4().hex[:12]}"
    probe_email = f"{random_local}@{domain}"
    result = await _check_smtp(probe_email, mx_host)
    return result is True


async def _find_email_inner(
    first_name: str,
    last_name: str,
    domain: str,
) -> dict:
    """Inner implementation without timeout wrapper.

    Always returns a dict with at least {"email": None, "domain_status": str}.
    """
    # Resolve MX
    mx_host = await _resolve_mx(domain)
    if not mx_host:
        logger.debug("No MX record found for %s", domain)
        return {"email": None, "domain_status": "no_mx"}

    # Check if MX host belongs to a known Secure Email Gateway (SEG).
    # These providers intercept all inbound mail — SMTP RCPT TO checks are
    # meaningless because the gateway always absorbs the probe.
    mx_lower = mx_host.lower()
    for pattern, provider in SEG_MX_PATTERNS.items():
        if mx_lower.endswith(pattern):
            logger.debug("Domain %s uses %s SEG (MX: %s), skipping SMTP", domain, provider, mx_host)
            return {"email": None, "domain_status": "infrastructure_blocked", "infrastructure": provider}

    # Check for catch-all domain
    if await _is_catch_all(domain, mx_host):
        logger.debug("Domain %s is catch-all, skipping SMTP verification", domain)
        return {"email": None, "domain_status": "catch_all"}

    # Generate and test candidates
    candidates = generate_candidates(first_name, last_name, domain)

    for candidate in candidates:
        if not candidate:
            continue

        result = await _check_smtp(candidate, mx_host)
        if result is True:
            return {
                "email": candidate,
                "source": "pattern_smtp",
                "verified": True,
                "domain_status": "success",
            }
        # If False (rejected), try next candidate
        # If None (inconclusive), also try next candidate

    return {"email": None, "domain_status": "all_rejected"}


async def find_email_by_pattern(
    first_name: str,
    last_name: str,
    domain: str,
) -> dict:
    """Find an email by generating pattern candidates and verifying via SMTP.

    Resolves MX records, checks for catch-all domains, then tests each
    candidate email sequentially. Stops at first verified match.

    Args:
        first_name: Person's first name.
        last_name: Person's last name.
        domain: Company domain (e.g. "stripe.com").

    Returns:
        Always a dict with at least {"email": str | None, "domain_status": str}.
        On success also includes "source" and "verified".

        domain_status values:
          "success"      — verified email found
          "catch_all"    — domain accepts all addresses (unreliable)
          "no_mx"        — no MX record found
          "all_rejected" — all candidates were SMTP-rejected
          "timeout"      — entire operation timed out
    """
    if not first_name or not last_name or not domain:
        return {"email": None, "domain_status": "no_mx"}

    try:
        return await asyncio.wait_for(
            _find_email_inner(first_name, last_name, domain),
            timeout=TOTAL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.debug("Pattern email search timed out for %s at %s", first_name, domain)
        return {"email": None, "domain_status": "timeout"}
    except Exception:
        logger.exception("Pattern email search failed for %s at %s", first_name, domain)
        return {"email": None, "domain_status": "timeout"}
