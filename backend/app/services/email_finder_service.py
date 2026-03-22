"""Email finding waterfall service."""

from datetime import datetime, timezone
import logging
import uuid
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients import (
    apollo_client,
    email_pattern_client,
    email_suggestion_client,
    github_email_client,
    gravatar_client,
    hunter_client,
    proxycurl_client,
)
from app.config import settings
from app.models.person import Person
from app.services import api_usage_service
from app.services.smtp_domain_service import is_domain_blocked, record_smtp_result
from app.utils.company_identity import is_ambiguous_company_name, slugify_company_name

logger = logging.getLogger(__name__)

LOW_CONFIDENCE_PERSIST_THRESHOLD = 60
LEARNED_PATTERN_THRESHOLD = 80
HUNTER_EXPLICIT_PATTERN_CONFIDENCE = 85
HUNTER_INFERRED_PATTERN_CONFIDENCE = 75
HUNTER_PATTERN_USAGE_PREFIX = "domain_search.pattern_learning:"
HUNTER_PATTERN_CREDITS = 1.0
HUNTER_VERIFY_CREDITS = 0.5
DOMAIN_DEPENDENT_EMAIL_SOURCES = {
    "pattern_smtp",
    "pattern_smtp_gravatar",
    "pattern_suggestion",
    "pattern_suggestion_learned",
}
KNOWN_BOARD_HOST_FRAGMENTS = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "workable.com",
    "myworkdayjobs.com",
)


def _split_name(full_name: str) -> tuple[str, str]:
    parts = (full_name or "").strip().split()
    if len(parts) == 0:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _response(
    *,
    email: str | None,
    source: str,
    verified: bool,
    tried: list[str],
    guess_basis: str | None = None,
    confidence: int | None = None,
    suggestions: list[dict] | None = None,
    failure_reasons: list[str] | None = None,
    email_verification_status: str | None = None,
    email_verification_method: str | None = None,
    email_verification_label: str | None = None,
    email_verification_evidence: str | None = None,
    email_verified_at: datetime | None = None,
) -> dict:
    result_type = "not_found"
    verified_email = None
    best_guess_email = None
    if email:
        if verified:
            result_type = "verified"
            verified_email = email
        else:
            result_type = "best_guess"
            best_guess_email = email
            guess_basis = guess_basis or _guess_basis_from_source(source)

    return {
        "email": email,
        "source": source,
        "verified": verified,
        "result_type": result_type,
        "usable_for_outreach": bool(email),
        "guess_basis": guess_basis,
        "verified_email": verified_email,
        "best_guess_email": best_guess_email,
        "confidence": confidence,
        "email_verification_status": email_verification_status,
        "email_verification_method": email_verification_method,
        "email_verification_label": email_verification_label,
        "email_verification_evidence": email_verification_evidence,
        "email_verified_at": email_verified_at.isoformat() if email_verified_at else None,
        "suggestions": suggestions,
        "alternate_guesses": suggestions,
        "failure_reasons": failure_reasons or [],
        "tried": tried,
    }


def _append_reason(failure_reasons: list[str], reason: str) -> None:
    if reason not in failure_reasons:
        failure_reasons.append(reason)


def _guess_basis_from_source(source: str | None) -> str | None:
    if source == "pattern_suggestion_learned":
        return "learned_company_pattern"
    if source == "pattern_suggestion":
        return "generic_pattern"
    return None


def _normalized_host(url_or_host: str | None) -> str:
    raw = (url_or_host or "").strip().lower()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = parsed.netloc.lower() or raw.split("/")[0].lower()
    return host[4:] if host.startswith("www.") else host


def _is_board_host(host: str | None) -> bool:
    normalized = _normalized_host(host)
    return any(fragment in normalized for fragment in KNOWN_BOARD_HOST_FRAGMENTS)


def _official_company_domain(person: Person) -> str | None:
    company = getattr(person, "company", None)
    if not company:
        return None

    candidates = [
        getattr(company, "careers_url", None),
    ]
    hints = getattr(company, "identity_hints", None) or {}
    company_slug = slugify_company_name(getattr(company, "name", None))
    official_slug_match = False
    if isinstance(hints, dict):
        candidates.append(hints.get("careers_host"))
        official_slug_match = any(
            (hints.get(key) or "").strip().lower() == company_slug
            for key in ("ats_slug", "linkedin_company_slug", "normalized_slug")
        )

    if is_ambiguous_company_name(getattr(company, "name", None)) and not official_slug_match:
        return None

    for candidate in candidates:
        host = _normalized_host(candidate)
        if not host or _is_board_host(host):
            continue
        return host
    return None


def _verification_label(
    status: str | None,
    method: str | None,
    *,
    guess_basis: str | None = None,
) -> str | None:
    if status == "verified" and method == "smtp_pattern":
        return "SMTP-verified"
    if status == "verified" and method == "hunter_verifier":
        return "Hunter-verified"
    if status == "verified" and method == "provider_verified":
        return "Provider-verified"
    if status == "best_guess" and guess_basis == "learned_company_pattern":
        return "Best guess from learned company pattern"
    if status == "best_guess":
        return "Best guess from generic pattern fallback"
    if status == "unverified" and method == "provider_verified":
        return "Provider email (unverified)"
    if status == "unverified" and method == "hunter_verifier":
        return "Hunter verification inconclusive"
    if status == "unverified":
        return "Unverified email"
    if status == "unknown":
        return "Verification unknown"
    return None


def _email_verification_payload(
    *,
    status: str | None,
    method: str | None,
    guess_basis: str | None = None,
    evidence: str | None = None,
    verified_at: datetime | None = None,
) -> dict:
    return {
        "email_verification_status": status,
        "email_verification_method": method,
        "email_verification_label": _verification_label(status, method, guess_basis=guess_basis),
        "email_verification_evidence": evidence,
        "email_verified_at": verified_at,
    }


def _set_person_email_verification(
    person: Person,
    *,
    status: str | None,
    method: str | None,
    guess_basis: str | None = None,
    evidence: str | None = None,
    verified_at: datetime | None = None,
) -> None:
    payload = _email_verification_payload(
        status=status,
        method=method,
        guess_basis=guess_basis,
        evidence=evidence,
        verified_at=verified_at,
    )
    person.email_verification_status = payload["email_verification_status"]
    person.email_verification_method = payload["email_verification_method"]
    person.email_verification_label = payload["email_verification_label"]
    person.email_verification_evidence = payload["email_verification_evidence"]
    person.email_verified_at = payload["email_verified_at"]


def _infer_saved_email_verification(person: Person) -> dict:
    if not person.work_email:
        return _email_verification_payload(status=None, method=None)

    source = getattr(person, "email_source", None)
    guess_basis = _guess_basis_from_source(source)
    inferred_verified_at = getattr(person, "email_verified_at", None) or (
        getattr(person, "created_at", None) if getattr(person, "email_verified", False) else None
    )

    if source in {"pattern_smtp", "pattern_smtp_gravatar"} and getattr(person, "email_verified", False):
        return _email_verification_payload(
            status="verified",
            method="smtp_pattern",
            evidence="Backfilled from existing SMTP pattern verification.",
            verified_at=inferred_verified_at,
        )
    if source == "apollo":
        return _email_verification_payload(
            status="verified" if getattr(person, "email_verified", False) else "unverified",
            method="provider_verified",
            evidence=(
                "Backfilled from existing provider-verified email."
                if getattr(person, "email_verified", False)
                else "Backfilled from existing provider email without verification."
            ),
            verified_at=inferred_verified_at if getattr(person, "email_verified", False) else None,
        )
    if source in {"pattern_suggestion", "pattern_suggestion_learned"}:
        return _email_verification_payload(
            status="best_guess",
            method="none",
            guess_basis=guess_basis,
            evidence=(
                "Backfilled from existing learned company-pattern best guess."
                if guess_basis == "learned_company_pattern"
                else "Backfilled from existing generic-pattern best guess."
            ),
        )
    if getattr(person, "email_verified", False):
        return _email_verification_payload(
            status="verified",
            method="none",
            evidence="Backfilled from existing verified email.",
            verified_at=inferred_verified_at,
        )
    return _email_verification_payload(
        status="unknown",
        method="none",
        evidence="Backfilled from existing saved email with unknown verification provenance.",
    )


def _backfill_person_email_verification(person: Person) -> bool:
    if not person.work_email:
        return False
    existing = (
        getattr(person, "email_verification_status", None),
        getattr(person, "email_verification_method", None),
        getattr(person, "email_verification_label", None),
        getattr(person, "email_verification_evidence", None),
        getattr(person, "email_verified_at", None),
    )
    if any(value is not None for value in existing):
        return False
    payload = _infer_saved_email_verification(person)
    _set_person_email_verification(
        person,
        status=payload["email_verification_status"],
        method=payload["email_verification_method"],
        evidence=payload["email_verification_evidence"],
        verified_at=payload["email_verified_at"],
        guess_basis=(
            "learned_company_pattern"
            if payload["email_verification_label"] == "Best guess from learned company pattern"
            else "generic_pattern"
            if payload["email_verification_label"] == "Best guess from generic pattern fallback"
            else None
        ),
    )
    return True


def _company_domain_is_trusted(person: Person) -> bool:
    return bool(
        person.company
        and getattr(person.company, "domain", None)
        and getattr(person.company, "domain_trusted", False)
    )


def _saved_email_depends_on_company_domain(person: Person) -> bool:
    return (person.email_source or "") in DOMAIN_DEPENDENT_EMAIL_SOURCES


async def _clear_untrusted_domain_email(db: AsyncSession, person: Person) -> None:
    person.work_email = None
    person.email_source = None
    person.email_verified = False
    person.email_confidence = None
    _set_person_email_verification(
        person,
        status=None,
        method=None,
        evidence=None,
        verified_at=None,
    )
    await db.commit()


def _hunter_pattern_endpoint(company_domain: str) -> str:
    return f"{HUNTER_PATTERN_USAGE_PREFIX}{company_domain.lower().strip()}"


def _hunter_verify_endpoint(email: str) -> str:
    return f"email_verifier.manual_verify:{email.lower().strip()}"


async def _record_hunter_usage(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    endpoint: str,
    operation: str,
    target: str,
    billable: bool,
    result: str,
    credits_used: float,
    extra_details: dict | None = None,
) -> None:
    details = {
        "operation": operation,
        "target": target,
        "billable": billable,
        "result": result,
    }
    if extra_details:
        details.update(extra_details)

    await api_usage_service.record_usage(
        db,
        user_id,
        service="hunter",
        endpoint=endpoint,
        credits_used=credits_used,
        details=details,
    )


def _extract_hunter_pattern(
    domain_result: dict | None,
    *,
    company_domain: str,
) -> tuple[str | None, int | None]:
    if not domain_result:
        return None, None

    explicit_pattern = domain_result.get("pattern")
    if explicit_pattern:
        return explicit_pattern, HUNTER_EXPLICIT_PATTERN_CONFIDENCE

    emails = sorted(
        domain_result.get("emails", []),
        key=lambda entry: int(entry.get("confidence") or 0),
        reverse=True,
    )
    for entry in emails:
        first_name = entry.get("first_name") or ""
        last_name = entry.get("last_name") or ""
        email = entry.get("email") or ""
        inferred = email_suggestion_client.infer_pattern(
            email,
            first_name,
            last_name,
            company_domain,
        )
        if inferred:
            return inferred, max(HUNTER_INFERRED_PATTERN_CONFIDENCE, int(entry.get("confidence") or 0))

    return None, None


async def _learn_company_pattern(
    person: Person,
    *,
    email: str,
    confidence: int,
    first_name: str,
    last_name: str,
    company_domain: str | None,
    verified: bool,
) -> None:
    if not person.company or not company_domain:
        return
    if not verified and confidence < LEARNED_PATTERN_THRESHOLD:
        return

    pattern = email_suggestion_client.infer_pattern(email, first_name, last_name, company_domain)
    if not pattern:
        return

    if not person.company.email_pattern_confidence or confidence >= person.company.email_pattern_confidence:
        person.company.email_pattern = pattern
        person.company.email_pattern_confidence = confidence


async def find_email_for_person(
    db: AsyncSession,
    user_id: uuid.UUID,
    person_id: uuid.UUID,
    mode: str = "best_effort",
) -> dict:
    """Try to find a work email for a person using the waterfall."""
    mode = mode if mode in {"best_effort", "verified_only"} else "best_effort"

    result = await db.execute(
        select(Person)
        .options(selectinload(Person.company))
        .where(Person.id == person_id, Person.user_id == user_id)
    )
    person = result.scalar_one_or_none()
    if not person:
        raise ValueError("Person not found.")

    tried: list[str] = []
    failure_reasons: list[str] = []

    if person.work_email and _saved_email_depends_on_company_domain(person) and not _company_domain_is_trusted(person):
        await _clear_untrusted_domain_email(db, person)

    if person.work_email:
        if _backfill_person_email_verification(person):
            await db.commit()
        return _response(
            email=person.work_email,
            source=person.email_source or "existing",
            verified=person.email_verified,
            tried=["existing"],
            confidence=person.email_confidence,
            email_verification_status=getattr(person, "email_verification_status", None),
            email_verification_method=getattr(person, "email_verification_method", None),
            email_verification_label=getattr(person, "email_verification_label", None),
            email_verification_evidence=getattr(person, "email_verification_evidence", None),
            email_verified_at=getattr(person, "email_verified_at", None),
        )

    first_name, last_name = _split_name(person.full_name or "")
    if not first_name or not last_name:
        _append_reason(failure_reasons, "missing_person_name")

    company_domain = None
    suggestion_domain = None
    learned_pattern = None
    learned_confidence = None
    if _company_domain_is_trusted(person):
        company_domain = person.company.domain
        suggestion_domain = company_domain
        learned_pattern = person.company.email_pattern
        learned_confidence = person.company.email_pattern_confidence
    elif person.company and getattr(person.company, "domain_trusted", False) is False:
        _append_reason(failure_reasons, "company_domain_untrusted")
        if not getattr(person.company, "domain", None):
            _append_reason(failure_reasons, "missing_company_domain")
        suggestion_domain = _official_company_domain(person)
        learned_pattern = person.company.email_pattern
        learned_confidence = person.company.email_pattern_confidence
    else:
        _append_reason(failure_reasons, "missing_company_domain")
        suggestion_domain = _official_company_domain(person)

    fallback_suggestion: dict | None = None
    fallback_confidence: int | None = None
    if person.github_url:
        tried.append("github_profile")
        profile_email = await github_email_client.get_profile_email(person.github_url)
        if profile_email:
            person.work_email = profile_email
            person.email_source = "github_profile"
            person.email_verified = False
            _set_person_email_verification(
                person,
                status="unknown",
                method="none",
                evidence="Email discovered from GitHub profile.",
            )
            await db.commit()
            return _response(
                email=profile_email,
                source="github_profile",
                verified=False,
                tried=tried,
                failure_reasons=failure_reasons,
                email_verification_status=getattr(person, "email_verification_status", None),
                email_verification_method=getattr(person, "email_verification_method", None),
                email_verification_label=getattr(person, "email_verification_label", None),
                email_verification_evidence=getattr(person, "email_verification_evidence", None),
                email_verified_at=getattr(person, "email_verified_at", None),
            )
        _append_reason(failure_reasons, "github_profile_no_email")

        tried.append("github_commit")
        commit_email = await github_email_client.get_commit_email(
            person.github_url,
            company_domain=company_domain,
        )
        if commit_email:
            person.work_email = commit_email
            person.email_source = "github_commit"
            person.email_verified = False
            _set_person_email_verification(
                person,
                status="unknown",
                method="none",
                evidence="Email discovered from GitHub commit metadata.",
            )
            await db.commit()
            return _response(
                email=commit_email,
                source="github_commit",
                verified=False,
                tried=tried,
                failure_reasons=failure_reasons,
                email_verification_status=getattr(person, "email_verification_status", None),
                email_verification_method=getattr(person, "email_verification_method", None),
                email_verification_label=getattr(person, "email_verification_label", None),
                email_verification_evidence=getattr(person, "email_verification_evidence", None),
                email_verified_at=getattr(person, "email_verified_at", None),
            )
        _append_reason(failure_reasons, "github_commit_no_email")

    if first_name and last_name and company_domain:
        tried.append("pattern_smtp")
        learning_candidate = False
        if await is_domain_blocked(db, company_domain):
            _append_reason(failure_reasons, "smtp_domain_blocked")
            learning_candidate = True
        else:
            pattern_result = await email_pattern_client.find_email_by_pattern(
                first_name,
                last_name,
                company_domain,
            )
            domain_status = pattern_result.get("domain_status", "timeout")
            if domain_status == "success":
                await record_smtp_result(db, company_domain, "success")
            elif domain_status == "catch_all":
                await record_smtp_result(db, company_domain, "catch_all")
                _append_reason(failure_reasons, "smtp_catch_all")
                learning_candidate = True
            elif domain_status == "timeout":
                await record_smtp_result(db, company_domain, "blocked")
                _append_reason(failure_reasons, "smtp_timeout")
                learning_candidate = True
            elif domain_status == "infrastructure_blocked":
                await record_smtp_result(db, company_domain, "infrastructure_blocked")
                _append_reason(failure_reasons, "smtp_infrastructure_blocked")
                learning_candidate = True
            elif domain_status == "all_rejected":
                _append_reason(failure_reasons, "smtp_all_rejected")
                learning_candidate = True
            elif domain_status == "no_mx":
                _append_reason(failure_reasons, "smtp_no_mx")

            if pattern_result.get("email"):
                found_email = pattern_result["email"]
                source = "pattern_smtp"
                has_gravatar = await gravatar_client.check_gravatar(found_email)
                if has_gravatar:
                    source = "pattern_smtp_gravatar"

                person.work_email = found_email
                person.email_source = source
                person.email_verified = True
                person.email_confidence = 100
                _set_person_email_verification(
                    person,
                    status="verified",
                    method="smtp_pattern",
                    evidence="SMTP RCPT accepted the generated company-pattern email.",
                    verified_at=datetime.now(timezone.utc),
                )
                await _learn_company_pattern(
                    person,
                    email=found_email,
                    confidence=100,
                    first_name=first_name,
                    last_name=last_name,
                    company_domain=company_domain,
                    verified=True,
                )
                await db.commit()
                return _response(
                    email=found_email,
                    source=source,
                    verified=True,
                    tried=tried,
                    guess_basis=_guess_basis_from_source(source),
                    confidence=100,
                    failure_reasons=failure_reasons,
                    email_verification_status=getattr(person, "email_verification_status", None),
                    email_verification_method=getattr(person, "email_verification_method", None),
                    email_verification_label=getattr(person, "email_verification_label", None),
                    email_verification_evidence=getattr(person, "email_verification_evidence", None),
                    email_verified_at=getattr(person, "email_verified_at", None),
                )

        if learning_candidate and not learned_pattern:
            tried.append("hunter_pattern_learning")
            if not settings.hunter_api_key:
                tried.append("hunter_pattern_learning_skipped")
                _append_reason(failure_reasons, "hunter_api_key_missing")
            else:
                monthly_usage = await api_usage_service.get_monthly_usage_count(
                    db,
                    user_id,
                    service="hunter",
                    endpoint_prefix=HUNTER_PATTERN_USAGE_PREFIX,
                )
                if monthly_usage >= settings.hunter_pattern_monthly_budget:
                    tried.append("hunter_pattern_learning_skipped")
                    _append_reason(failure_reasons, "hunter_pattern_budget_exhausted")
                else:
                    hunter_learning_endpoint = _hunter_pattern_endpoint(company_domain)
                    if await api_usage_service.has_monthly_usage(
                        db,
                        user_id,
                        service="hunter",
                        endpoint=hunter_learning_endpoint,
                    ):
                        tried.append("hunter_pattern_learning_skipped")
                        _append_reason(failure_reasons, "hunter_pattern_already_tried")
                    else:
                        domain_result = await hunter_client.domain_search(company_domain, limit=10)
                        billable = bool(domain_result.get("emails"))
                        credits_used = HUNTER_PATTERN_CREDITS if billable else 0.0
                        outcome = "pattern_learned" if domain_result.get("pattern") else "no_result"
                        await _record_hunter_usage(
                            db,
                            user_id,
                            endpoint=hunter_learning_endpoint,
                            operation="domain_search",
                            target=company_domain,
                            billable=billable,
                            result=outcome,
                            credits_used=credits_used,
                            extra_details={
                                "accept_all": domain_result.get("accept_all"),
                                "email_count": len(domain_result.get("emails", [])),
                            },
                        )
                        learned_pattern, learned_confidence = _extract_hunter_pattern(
                            domain_result,
                            company_domain=company_domain,
                        )
                        if learned_pattern and person.company:
                            person.company.email_pattern = learned_pattern
                            person.company.email_pattern_confidence = learned_confidence
                            tried.append("hunter_pattern_learned")
                        else:
                            tried.append("hunter_pattern_learning_skipped")
                            _append_reason(failure_reasons, "hunter_pattern_no_pattern_found")

    suggestion_domain = suggestion_domain or company_domain
    if first_name and last_name and suggestion_domain:
        tried.append("pattern_suggestion")
        suggestion = email_suggestion_client.suggest_email(
            first_name,
            last_name,
            suggestion_domain,
            preferred_format=learned_pattern,
            preferred_confidence=learned_confidence,
        )
        if suggestion:
            confidence = suggestion["confidence"]
            has_gravatar = await gravatar_client.check_gravatar(suggestion["email"])
            if has_gravatar:
                confidence = min(confidence + 15, 95)

            suggestion_list = [
                {"email": item["email"], "confidence": item["confidence"]}
                for item in suggestion.get("suggestions", [])
            ]
            fallback_suggestion = {
                "email": suggestion["email"],
                "confidence": confidence,
                "suggestions": suggestion_list,
                "guess_basis": "learned_company_pattern" if learned_pattern else "generic_pattern",
            }
            fallback_confidence = confidence
            if confidence < LOW_CONFIDENCE_PERSIST_THRESHOLD:
                _append_reason(failure_reasons, "pattern_suggestion_low_confidence")

    if person.apollo_id or person.linkedin_url:
        tried.append("apollo_enrichment")
        enrichment = await apollo_client.enrich_person(
            apollo_id=person.apollo_id,
            linkedin_url=person.linkedin_url,
            full_name=person.full_name,
            domain=company_domain,
        )
        if enrichment and enrichment.get("work_email"):
            verified = enrichment.get("email_verified", False)
            person.work_email = enrichment["work_email"]
            person.email_source = "apollo"
            person.email_verified = verified
            person.email_confidence = 100 if verified else person.email_confidence
            _set_person_email_verification(
                person,
                status="verified" if verified else "unverified",
                method="provider_verified",
                evidence=(
                    "Provider returned a verified work email."
                    if verified
                    else "Provider returned a work email without verification."
                ),
                verified_at=datetime.now(timezone.utc) if verified else None,
            )
            if enrichment.get("apollo_id") and not person.apollo_id:
                person.apollo_id = enrichment["apollo_id"]
            await _learn_company_pattern(
                person,
                email=enrichment["work_email"],
                confidence=100 if verified else 70,
                first_name=first_name,
                last_name=last_name,
                company_domain=company_domain,
                verified=verified,
            )
            await db.commit()
            return _response(
                email=enrichment["work_email"],
                source="apollo",
                verified=verified,
                tried=tried,
                guess_basis=_guess_basis_from_source("apollo"),
                confidence=100 if verified else None,
                failure_reasons=failure_reasons,
                email_verification_status=getattr(person, "email_verification_status", None),
                email_verification_method=getattr(person, "email_verification_method", None),
                email_verification_label=getattr(person, "email_verification_label", None),
                email_verification_evidence=getattr(person, "email_verification_evidence", None),
                email_verified_at=getattr(person, "email_verified_at", None),
            )
        _append_reason(failure_reasons, "apollo_no_email")

    if person.linkedin_url:
        tried.append("proxycurl")
        if not settings.proxycurl_api_key:
            _append_reason(failure_reasons, "proxycurl_api_key_missing")
        else:
            profile = await proxycurl_client.enrich_profile(person.linkedin_url)
            if profile and profile.get("personal_emails"):
                email = profile["personal_emails"][0]
                person.work_email = email
                person.email_source = "proxycurl"
                person.email_verified = False
                person.profile_data = profile
                _set_person_email_verification(
                    person,
                    status="unknown",
                    method="none",
                    evidence="Email discovered from Proxycurl profile enrichment.",
                )
                await db.commit()
                return _response(
                    email=email,
                    source="proxycurl",
                    verified=False,
                    tried=tried,
                    failure_reasons=failure_reasons,
                    email_verification_status=getattr(person, "email_verification_status", None),
                    email_verification_method=getattr(person, "email_verification_method", None),
                    email_verification_label=getattr(person, "email_verification_label", None),
                    email_verification_evidence=getattr(person, "email_verification_evidence", None),
                    email_verified_at=getattr(person, "email_verified_at", None),
                )
            _append_reason(failure_reasons, "proxycurl_no_email")

    tried.append("exhausted")
    if mode == "best_effort" and fallback_suggestion:
        fallback_evidence = (
            "Best guess derived from a learned company email pattern."
            if fallback_suggestion["guess_basis"] == "learned_company_pattern"
            else (
                "Best guess derived from the official company site domain fallback."
                if suggestion_domain and suggestion_domain != company_domain
                else "Best guess derived from the generic email pattern fallback."
            )
        )
        if (
            fallback_confidence
            and fallback_confidence >= LOW_CONFIDENCE_PERSIST_THRESHOLD
            and suggestion_domain == company_domain
        ):
            person.work_email = fallback_suggestion["email"]
            person.email_source = (
                "pattern_suggestion_learned"
                if fallback_suggestion["guess_basis"] == "learned_company_pattern"
                else "pattern_suggestion"
            )
            person.email_verified = False
            person.email_confidence = fallback_confidence
            _set_person_email_verification(
                person,
                status="best_guess",
                method="none",
                guess_basis=fallback_suggestion["guess_basis"],
                evidence=fallback_evidence,
            )
            await _learn_company_pattern(
                person,
                email=fallback_suggestion["email"],
                confidence=fallback_confidence,
                first_name=first_name,
                last_name=last_name,
                company_domain=company_domain,
                verified=False,
            )
            await db.commit()
        return _response(
            email=fallback_suggestion["email"],
            source="pattern_suggestion",
            verified=False,
            tried=tried,
            guess_basis=fallback_suggestion["guess_basis"],
            confidence=fallback_confidence,
            suggestions=fallback_suggestion["suggestions"],
            failure_reasons=failure_reasons,
            email_verification_status=(
                person.email_verification_status
                if person.work_email == fallback_suggestion["email"]
                else "best_guess"
            ),
            email_verification_method=(
                person.email_verification_method
                if person.work_email == fallback_suggestion["email"]
                else "none"
            ),
            email_verification_label=_verification_label(
                person.email_verification_status if person.work_email == fallback_suggestion["email"] else "best_guess",
                person.email_verification_method if person.work_email == fallback_suggestion["email"] else "none",
                guess_basis=fallback_suggestion["guess_basis"],
            ),
            email_verification_evidence=(
                person.email_verification_evidence
                if person.work_email == fallback_suggestion["email"]
                else fallback_evidence
            ),
            email_verified_at=getattr(person, "email_verified_at", None),
        )

    return _response(
        email=None,
        source="not_found",
        verified=False,
        tried=tried,
        failure_reasons=failure_reasons,
        email_verification_status=None,
        email_verification_method=None,
        email_verification_label=None,
        email_verification_evidence=None,
        email_verified_at=None,
    )


async def verify_person_email(
    db: AsyncSession,
    user_id: uuid.UUID,
    person_id: uuid.UUID,
) -> dict:
    """Verify an existing email address via Hunter.io."""
    result = await db.execute(
        select(Person).where(Person.id == person_id, Person.user_id == user_id)
    )
    person = result.scalar_one_or_none()
    if not person:
        raise ValueError("Person not found.")
    if not person.work_email:
        raise ValueError("No email to verify.")

    verification = await hunter_client.verify_email(person.work_email)
    if verification:
        result = verification.get("result", "unknown")
        billable = result != "unknown"
        await _record_hunter_usage(
            db,
            user_id,
            endpoint=_hunter_verify_endpoint(person.work_email),
            operation="email_verifier",
            target=person.work_email,
            billable=billable,
            result=result,
            credits_used=HUNTER_VERIFY_CREDITS if billable else 0.0,
            extra_details={"status": verification.get("status", "unknown")},
        )
        status = verification.get("status", "unknown")
        is_valid = status == "valid"
        person.email_verified = is_valid
        _set_person_email_verification(
            person,
            status="verified" if is_valid else ("unknown" if status == "unknown" else "unverified"),
            method="hunter_verifier",
            evidence=f"Hunter Email Verifier returned status={status} result={result}.",
            verified_at=datetime.now(timezone.utc) if is_valid else None,
        )
        await db.commit()
        return {
            **verification,
            "email_verification_status": person.email_verification_status,
            "email_verification_method": person.email_verification_method,
            "email_verification_label": person.email_verification_label,
            "email_verification_evidence": person.email_verification_evidence,
        }

    _set_person_email_verification(
        person,
        status="unknown",
        method="hunter_verifier",
        evidence="Hunter Email Verifier could not return a result.",
        verified_at=None,
    )
    await db.commit()
    return {
        "email": person.work_email,
        "status": "unknown",
        "result": "unable_to_verify",
        "email_verification_status": person.email_verification_status,
        "email_verification_method": person.email_verification_method,
        "email_verification_label": person.email_verification_label,
        "email_verification_evidence": person.email_verification_evidence,
    }
