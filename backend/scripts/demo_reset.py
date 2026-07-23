"""Reset and seed the synthetic local product-capture environment.

This script deliberately relies on Settings' demo-mode validation. Importing
``app.config`` fails before a database connection is opened unless the target
database/Redis hosts are loopback, the database name contains ``e2e`` or
``demo``, dev auth is enabled, and external credentials are empty.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import UTC, date, datetime

from app.config import settings
from app.database import async_session
from app.models.company import Company
from app.models.job import Job
from app.models.message import Message
from app.models.outreach import OutreachLog
from app.models.person import Person
from app.models.profile import Profile
from app.models.search_preference import SearchPreference
from app.models.settings import UserSettings
from app.models.user import User
from app.services.account_service import delete_user_data


DEMO_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def demo_uuid(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"https://demo.nexusreach.invalid/{name}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=("onboarding", "returning"),
        default="returning",
        help="Starting state to seed (default: returning).",
    )
    return parser.parse_args()


async def reset_demo(scenario: str) -> dict[str, int | str]:
    if not settings.demo_mode:
        raise SystemExit("Refusing to reset unless NEXUSREACH_DEMO_MODE=true.")
    if settings.dev_user_id != DEMO_USER_ID:
        raise SystemExit("Demo mode requires the deterministic development user ID.")

    async with async_session() as db:
        await delete_user_data(db, DEMO_USER_ID)
        db.add(User(id=DEMO_USER_ID, email=settings.dev_user_email))
        db.add(
            Profile(
                id=demo_uuid("profile"),
                user_id=DEMO_USER_ID,
                full_name=None if scenario == "onboarding" else "Jordan Demo",
                bio=None if scenario == "onboarding" else "Early-career product engineer building accessible web products.",
                goals=None if scenario == "onboarding" else ["job"],
                target_roles=None if scenario == "onboarding" else ["Product Engineer", "Frontend Engineer"],
                target_occupations=None if scenario == "onboarding" else ["software_engineering", "product_management"],
                target_locations=None if scenario == "onboarding" else ["Toronto", "Remote"],
                target_industries=None if scenario == "onboarding" else ["Developer tools", "Climate tech"],
                job_preferences={},
            )
        )
        db.add(
            UserSettings(
                id=demo_uuid("settings"),
                user_id=DEMO_USER_ID,
                onboarding_completed=scenario == "returning",
                guardrails_acknowledged=scenario == "returning",
                auto_prospect_enabled=False,
                auto_draft_on_apply=False,
                auto_stage_on_apply=False,
                auto_send_enabled=False,
                people_prewarm_enabled=False,
                cadence_digest_enabled=False,
                cadence_auto_draft_enabled=False,
                gmail_connected=False,
                outlook_connected=False,
                linkedin_graph_connected=False,
            )
        )
        # Persist the FK roots before adding fixture rows. The fixture uses
        # explicit scalar IDs rather than ORM relationships so its ordering is
        # deterministic even if SQLAlchemy cannot infer an object dependency.
        await db.flush()

        if scenario == "returning":
            counts = seed_returning_fixture(db)
        else:
            counts = {"companies": 0, "jobs": 0, "people": 0, "messages": 0, "outreach": 0}
        await db.commit()
        return {"scenario": scenario, "users": 1, **counts}


def seed_returning_fixture(db) -> dict[str, int]:
    now = datetime(2026, 7, 14, 14, 0, tzinfo=UTC)
    companies = [
        Company(id=demo_uuid("company/northstar"), user_id=DEMO_USER_ID, name="Northstar Labs", normalized_name="northstar labs", domain="northstar.example.test", domain_trusted=False, industry="Developer tools", size="51-200", funding_stage="Series B", description="Synthetic developer-tools company used only for the NexusReach demo."),
        Company(id=demo_uuid("company/greenline"), user_id=DEMO_USER_ID, name="Greenline Energy", normalized_name="greenline energy", domain="greenline.example.test", domain_trusted=False, industry="Climate technology", size="201-500", funding_stage="Series C", description="Synthetic climate-software company used only for the NexusReach demo."),
        Company(id=demo_uuid("company/maple"), user_id=DEMO_USER_ID, name="Maple Systems", normalized_name="maple systems", domain="maple.example.test", domain_trusted=False, industry="Financial technology", size="501-1000", funding_stage="Private", description="Synthetic Canadian fintech used only for the NexusReach demo."),
    ]
    db.add_all(companies)

    job_specs = [
        ("product-engineer", "Product Engineer", companies[0], "Toronto, Canada", False, "hybrid", "interested", 91.0, "software_engineering"),
        ("frontend-engineer", "Frontend Engineer", companies[1], "Remote — Canada", True, "remote", "researching", 87.0, "software_engineering"),
        ("associate-pm", "Associate Product Manager", companies[0], "Toronto, Canada", False, "hybrid", "networking", 82.0, "product_management"),
        ("new-grad-software", "New Grad Software Engineer", companies[2], "Vancouver, Canada", False, "onsite", "discovered", 79.0, "software_engineering"),
        ("implementation", "Implementation Specialist", companies[2], "Remote — Canada", True, "remote", "applied", 74.0, "customer_service_support"),
    ]
    jobs: list[Job] = []
    for index, (slug, title, company, location, remote, work_mode, stage, score, occupation) in enumerate(job_specs):
        jobs.append(
            Job(
                id=demo_uuid(f"job/{slug}"),
                user_id=DEMO_USER_ID,
                external_id=f"demo-{slug}",
                title=title,
                company_name=company.name,
                company_id=company.id,
                location=location,
                country_codes=["CA"],
                countries=["Canada"],
                remote=remote,
                work_mode=work_mode,
                url=None,
                apply_url=None,
                description=f"Synthetic {title} role for deterministic browser testing. Collaborate with a kind, cross-functional team and ship measurable product improvements.",
                employment_type="full_time",
                experience_level="new_grad" if "New Grad" in title or "Associate" in title else "mid",
                experience_level_confidence=1.0,
                salary_min=70_000 + index * 3_000,
                salary_max=95_000 + index * 4_000,
                salary_currency="CAD",
                salary_period="year",
                source="demo_fixture",
                posted_at=f"2026-07-{14 - index:02d}",
                posted_date=date(2026, 7, 14 - index),
                source_status="active",
                last_seen_at=now,
                people_prewarm_status="ready",
                match_score=score,
                score_breakdown={"demo_fixture": score},
                scored_at=now,
                fingerprint=f"demo:{slug}",
                stage=stage,
                tags=[f"occupation:{occupation}", "demo_fixture"],
                metadata_provenance={"fixture": "gideon-local-pilot-v1"},
                department="Engineering" if occupation == "software_engineering" else "Product",
                starred=index in {0, 2},
                created_at=now,
                updated_at=now,
            )
        )
    db.add_all(jobs)

    person_specs = [
        ("avery", "Avery Chen", "Senior Technical Recruiter", "recruiter", companies[0], 96),
        ("morgan", "Morgan Lee", "Director of Engineering", "hiring_manager", companies[0], 94),
        ("riley", "Riley Patel", "Product Engineer", "peer", companies[0], 90),
        ("casey", "Casey Williams", "Talent Partner", "recruiter", companies[1], 91),
        ("jamie", "Jamie Nguyen", "Frontend Engineering Manager", "hiring_manager", companies[1], 93),
        ("taylor", "Taylor Robinson", "Software Engineer", "peer", companies[2], 86),
    ]
    people: list[Person] = []
    for slug, name, title, person_type, company, relevance in person_specs:
        people.append(
            Person(
                id=demo_uuid(f"person/{slug}"),
                user_id=DEMO_USER_ID,
                company_id=company.id,
                full_name=name,
                title=title,
                department="Talent" if person_type == "recruiter" else "Engineering",
                seniority="manager" if "Manager" in title or "Director" in title else "individual_contributor",
                linkedin_url=None,
                work_email=f"{slug}@example.test",
                email_source="demo_fixture",
                email_verified=False,
                email_confidence=0,
                email_verification_status="synthetic",
                person_type=person_type,
                profile_data={"fixture": "gideon-local-pilot-v1", "match_quality": "direct"},
                source="demo_fixture",
                relevance_score=relevance,
                current_company_verified=True,
                current_company_verification_status="fixture_verified",
                current_company_verification_source="demo_fixture",
                current_company_verification_confidence=100,
                current_company_verification_evidence="Synthetic fixture; not a real person.",
                current_company_verified_at=now,
                created_at=now,
            )
        )
    db.add_all(people)

    messages = [
        Message(id=demo_uuid("message/avery"), user_id=DEMO_USER_ID, person_id=people[0].id, channel="email", goal="informational", subject="Learning about Northstar Labs", body="Hi Avery — this is a synthetic, unsent demo draft.", reasoning="Seeded fixture; no model was called.", ai_model="demo_fixture", token_usage={}, context_snapshot={"fixture": True}, status="draft", created_at=now, updated_at=now),
        Message(id=demo_uuid("message/morgan"), user_id=DEMO_USER_ID, person_id=people[1].id, channel="linkedin_note", goal="coffee_chat", subject=None, body="Hi Morgan — this is a synthetic, unsent demo note.", reasoning="Seeded fixture; no model was called.", ai_model="demo_fixture", token_usage={}, context_snapshot={"fixture": True}, status="edited", created_at=now, updated_at=now),
    ]
    db.add_all(messages)
    db.add_all(
        [
            OutreachLog(id=demo_uuid("outreach/avery"), user_id=DEMO_USER_ID, person_id=people[0].id, job_id=jobs[0].id, message_id=messages[0].id, status="draft", channel="email", notes="Synthetic draft only — never send.", response_received=False, created_at=now, updated_at=now),
            OutreachLog(id=demo_uuid("outreach/morgan"), user_id=DEMO_USER_ID, person_id=people[1].id, job_id=jobs[0].id, message_id=messages[1].id, status="draft", channel="linkedin_note", notes="Synthetic demo record.", response_received=False, created_at=now, updated_at=now),
        ]
    )
    db.add(
        SearchPreference(
            id=demo_uuid("search/product-engineer"),
            user_id=DEMO_USER_ID,
            query="Product Engineer",
            location="Canada",
            remote_only=False,
            enabled=False,
            mode="default",
            new_jobs_found=0,
            created_at=now,
            updated_at=now,
        )
    )
    return {"companies": len(companies), "jobs": len(jobs), "people": len(people), "messages": len(messages), "outreach": 2}


async def main() -> None:
    result = await reset_demo(parse_args().scenario)
    summary = ", ".join(f"{key}={value}" for key, value in result.items())
    print(f"NexusReach demo reset complete: {summary}")


if __name__ == "__main__":
    asyncio.run(main())
