"""Email finding waterfall service."""

import logging
import uuid

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
from app.services.smtp_domain_service import is_domain_blocked, record_smtp_result

logger = logging.getLogger(__name__)

LOW_CONFIDENCE_PERSIST_THRESHOLD = 60
LEARNED_PATTERN_THRESHOLD = 80


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
    confidence: int | None = None,
    suggestions: list[dict] | None = None,
    failure_reasons: list[str] | None = None,
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

    return {
        "email": email,
        "source": source,
        "verified": verified,
        "result_type": result_type,
        "verified_email": verified_email,
        "best_guess_email": best_guess_email,
        "confidence": confidence,
        "suggestions": suggestions,
        "alternate_guesses": suggestions,
        "failure_reasons": failure_reasons or [],
        "tried": tried,
    }


def _append_reason(failure_reasons: list[str], reason: str) -> None:
    if reason not in failure_reasons:
        failure_reasons.append(reason)


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

    if person.work_email:
        return _response(
            email=person.work_email,
            source=person.email_source or "existing",
            verified=person.email_verified,
            tried=["existing"],
            confidence=person.email_confidence,
        )

    first_name, last_name = _split_name(person.full_name or "")
    if not first_name or not last_name:
        _append_reason(failure_reasons, "missing_person_name")

    company_domain = None
    learned_pattern = None
    learned_confidence = None
    if person.company and person.company.domain:
        company_domain = person.company.domain
        learned_pattern = person.company.email_pattern
        learned_confidence = person.company.email_pattern_confidence
    else:
        _append_reason(failure_reasons, "missing_company_domain")

    fallback_suggestion: dict | None = None
    fallback_confidence: int | None = None

    if person.github_url:
        tried.append("github_profile")
        profile_email = await github_email_client.get_profile_email(person.github_url)
        if profile_email:
            person.work_email = profile_email
            person.email_source = "github_profile"
            person.email_verified = False
            await db.commit()
            return _response(
                email=profile_email,
                source="github_profile",
                verified=False,
                tried=tried,
                failure_reasons=failure_reasons,
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
            await db.commit()
            return _response(
                email=commit_email,
                source="github_commit",
                verified=False,
                tried=tried,
                failure_reasons=failure_reasons,
            )
        _append_reason(failure_reasons, "github_commit_no_email")

    if first_name and last_name and company_domain:
        tried.append("pattern_smtp")
        if await is_domain_blocked(db, company_domain):
            _append_reason(failure_reasons, "smtp_domain_blocked")
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
            elif domain_status == "timeout":
                await record_smtp_result(db, company_domain, "blocked")
                _append_reason(failure_reasons, "smtp_timeout")
            elif domain_status == "infrastructure_blocked":
                await record_smtp_result(db, company_domain, "infrastructure_blocked")
                _append_reason(failure_reasons, "smtp_infrastructure_blocked")
            elif domain_status == "all_rejected":
                _append_reason(failure_reasons, "smtp_all_rejected")
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
                    confidence=100,
                    failure_reasons=failure_reasons,
                )

        tried.append("pattern_suggestion")
        suggestion = email_suggestion_client.suggest_email(
            first_name,
            last_name,
            company_domain,
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
                confidence=100 if verified else None,
                failure_reasons=failure_reasons,
            )
        _append_reason(failure_reasons, "apollo_no_email")

    if company_domain and first_name and last_name:
        tried.append("hunter")
        if not settings.hunter_api_key:
            _append_reason(failure_reasons, "hunter_api_key_missing")
        else:
            hunter_result = await hunter_client.find_email(
                domain=company_domain,
                first_name=first_name,
                last_name=last_name,
            )
            if hunter_result and hunter_result.get("email"):
                verified = hunter_result.get("verified", False)
                person.work_email = hunter_result["email"]
                person.email_source = "hunter"
                person.email_verified = verified
                person.email_confidence = 100 if verified else person.email_confidence
                await _learn_company_pattern(
                    person,
                    email=hunter_result["email"],
                    confidence=100 if verified else 70,
                    first_name=first_name,
                    last_name=last_name,
                    company_domain=company_domain,
                    verified=verified,
                )
                await db.commit()
                return _response(
                    email=hunter_result["email"],
                    source="hunter",
                    verified=verified,
                    tried=tried,
                    failure_reasons=failure_reasons,
                )
            _append_reason(failure_reasons, "hunter_no_email")

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
                await db.commit()
                return _response(
                    email=email,
                    source="proxycurl",
                    verified=False,
                    tried=tried,
                    failure_reasons=failure_reasons,
                )
            _append_reason(failure_reasons, "proxycurl_no_email")

    if company_domain and first_name and last_name:
        tried.append("hunter_domain")
        if not settings.hunter_api_key:
            _append_reason(failure_reasons, "hunter_api_key_missing")
        else:
            domain_results = await hunter_client.domain_search(company_domain, limit=20)
            for result_entry in domain_results:
                r_first = (result_entry.get("first_name") or "").lower()
                r_last = (result_entry.get("last_name") or "").lower()
                if r_first == first_name.lower() and r_last == last_name.lower():
                    confidence = result_entry.get("confidence", 0)
                    verified = confidence > 80
                    person.work_email = result_entry["email"]
                    person.email_source = "hunter_domain"
                    person.email_verified = verified
                    person.email_confidence = confidence or None
                    await _learn_company_pattern(
                        person,
                        email=result_entry["email"],
                        confidence=confidence,
                        first_name=first_name,
                        last_name=last_name,
                        company_domain=company_domain,
                        verified=verified,
                    )
                    await db.commit()
                    return _response(
                        email=result_entry["email"],
                        source="hunter_domain",
                        verified=verified,
                        tried=tried,
                        confidence=confidence or None,
                        failure_reasons=failure_reasons,
                    )
            _append_reason(failure_reasons, "hunter_domain_no_email")

    tried.append("exhausted")
    if mode == "best_effort" and fallback_suggestion:
        if fallback_confidence and fallback_confidence >= LOW_CONFIDENCE_PERSIST_THRESHOLD:
            person.work_email = fallback_suggestion["email"]
            person.email_source = "pattern_suggestion"
            person.email_verified = False
            person.email_confidence = fallback_confidence
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
            confidence=fallback_confidence,
            suggestions=fallback_suggestion["suggestions"],
            failure_reasons=failure_reasons,
        )

    return _response(
        email=None,
        source="not_found",
        verified=False,
        tried=tried,
        failure_reasons=failure_reasons,
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
        person.email_verified = verification.get("status") == "valid"
        await db.commit()
        return verification

    return {"email": person.work_email, "status": "unknown", "result": "unable_to_verify"}
