"""Email finding waterfall service — tries multiple sources to find work emails."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import apollo_client, hunter_client, proxycurl_client
from app.models.person import Person


def _split_name(full_name: str) -> tuple[str, str]:
    """Split a full name into first and last name."""
    parts = (full_name or "").strip().split()
    if len(parts) == 0:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


async def find_email_for_person(
    db: AsyncSession,
    user_id: uuid.UUID,
    person_id: uuid.UUID,
) -> dict:
    """Try to find a work email for a person using the waterfall:
    1. Check if we already have one
    2. Apollo Enrichment (1 credit — best when we have apollo_id)
    3. Hunter.io (email finder by domain + name)
    4. Proxycurl (LinkedIn profile enrichment)
    5. Hunter domain search (fallback — search entire domain)
    6. Exhausted — no email found

    Returns:
        {"email": str | None, "source": str, "verified": bool, "tried": list[str]}
    """
    result = await db.execute(
        select(Person).where(Person.id == person_id, Person.user_id == user_id)
    )
    person = result.scalar_one_or_none()
    if not person:
        raise ValueError("Person not found.")

    tried: list[str] = []

    # 1. Already have an email
    if person.work_email:
        return {
            "email": person.work_email,
            "source": person.email_source or "existing",
            "verified": person.email_verified,
            "tried": ["existing"],
        }

    first_name, last_name = _split_name(person.full_name or "")

    # Get company domain for Hunter lookup
    company_domain = None
    if person.company and person.company.domain:
        company_domain = person.company.domain

    # 2. Apollo Enrichment (1 credit) — best when we have an apollo_id
    if person.apollo_id or person.linkedin_url:
        tried.append("apollo_enrichment")
        enrichment = await apollo_client.enrich_person(
            apollo_id=person.apollo_id,
            linkedin_url=person.linkedin_url,
            full_name=person.full_name,
            domain=company_domain,
        )
        if enrichment and enrichment.get("work_email"):
            person.work_email = enrichment["work_email"]
            person.email_source = "apollo"
            person.email_verified = enrichment.get("email_verified", False)
            if enrichment.get("apollo_id") and not person.apollo_id:
                person.apollo_id = enrichment["apollo_id"]
            await db.commit()
            return {
                "email": enrichment["work_email"],
                "source": "apollo",
                "verified": enrichment.get("email_verified", False),
                "tried": tried,
            }

    # 3. Hunter.io — best for email finding by name + domain
    if company_domain and first_name and last_name:
        tried.append("hunter")
        hunter_result = await hunter_client.find_email(
            domain=company_domain,
            first_name=first_name,
            last_name=last_name,
        )
        if hunter_result and hunter_result.get("email"):
            person.work_email = hunter_result["email"]
            person.email_source = "hunter"
            person.email_verified = hunter_result.get("verified", False)
            await db.commit()
            return {
                "email": hunter_result["email"],
                "source": "hunter",
                "verified": hunter_result.get("verified", False),
                "tried": tried,
            }

    # 4. Proxycurl — LinkedIn enrichment may reveal email
    if person.linkedin_url:
        tried.append("proxycurl")
        profile = await proxycurl_client.enrich_profile(person.linkedin_url)
        if profile and profile.get("personal_emails"):
            email = profile["personal_emails"][0]
            person.work_email = email
            person.email_source = "proxycurl"
            person.email_verified = False
            person.profile_data = profile
            await db.commit()
            return {
                "email": email,
                "source": "proxycurl",
                "verified": False,
                "tried": tried,
            }

    # 5. Hunter domain search fallback — search entire domain
    if company_domain:
        tried.append("hunter_domain")
        domain_results = await hunter_client.domain_search(company_domain, limit=20)
        for result_entry in domain_results:
            r_first = (result_entry.get("first_name") or "").lower()
            r_last = (result_entry.get("last_name") or "").lower()
            if r_first == first_name.lower() and r_last == last_name.lower():
                person.work_email = result_entry["email"]
                person.email_source = "hunter_domain"
                person.email_verified = result_entry.get("confidence", 0) > 80
                await db.commit()
                return {
                    "email": result_entry["email"],
                    "source": "hunter_domain",
                    "verified": result_entry.get("confidence", 0) > 80,
                    "tried": tried,
                }

    # 6. No email found
    tried.append("exhausted")
    return {
        "email": None,
        "source": "not_found",
        "verified": False,
        "tried": tried,
    }


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
