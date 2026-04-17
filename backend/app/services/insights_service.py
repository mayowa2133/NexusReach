"""Insights dashboard service — analytics from existing data (Phase 8)."""

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import Integer, cast, select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_usage import ApiUsage
from app.models.linkedin_graph import LinkedInGraphConnection
from app.models.outreach import OutreachLog
from app.models.person import Person
from app.models.company import Company
from app.models.message import Message
from app.models.job import Job
from app.models.profile import Profile
from app.services.linkedin_graph_service import graph_freshness_metadata

# Window used by the API-usage breakdown on the dashboard.
API_USAGE_WINDOW_DAYS = 30
# Cap on the imported-graph warm-path companies surfaced on the dashboard.
GRAPH_WARM_PATHS_LIMIT = 10


# ---------------------------------------------------------------------------
# Summary KPIs
# ---------------------------------------------------------------------------

async def get_dashboard_summary(
    db: AsyncSession, user_id: uuid.UUID
) -> dict:
    """Top-level KPIs for metric cards."""
    # Total distinct contacts
    total_contacts_r = await db.execute(
        select(sa_func.count(sa_func.distinct(OutreachLog.person_id))).where(
            OutreachLog.user_id == user_id
        )
    )
    total_contacts = total_contacts_r.scalar() or 0

    # Total messages drafted (non-draft status)
    total_messages_r = await db.execute(
        select(sa_func.count()).where(
            Message.user_id == user_id,
            Message.status != "draft",
        )
    )
    total_messages_sent = total_messages_r.scalar() or 0

    # Total jobs tracked
    total_jobs_r = await db.execute(
        select(sa_func.count()).where(Job.user_id == user_id)
    )
    total_jobs_tracked = total_jobs_r.scalar() or 0

    # Overall response rate
    total_outreach_r = await db.execute(
        select(sa_func.count()).where(
            OutreachLog.user_id == user_id,
            OutreachLog.status != "draft",
        )
    )
    total_outreach = total_outreach_r.scalar() or 0

    responded_r = await db.execute(
        select(sa_func.count()).where(
            OutreachLog.user_id == user_id,
            OutreachLog.status.in_(["responded", "met", "closed"]),
        )
    )
    responded = responded_r.scalar() or 0
    response_rate = round((responded / total_outreach * 100), 1) if total_outreach > 0 else 0.0

    # Upcoming follow-ups
    now = datetime.now(timezone.utc)
    follow_ups_r = await db.execute(
        select(sa_func.count()).where(
            OutreachLog.user_id == user_id,
            OutreachLog.next_follow_up_at.is_not(None),
            OutreachLog.next_follow_up_at >= now,
            OutreachLog.status.notin_(["closed"]),
        )
    )
    upcoming_follow_ups = follow_ups_r.scalar() or 0

    # Active conversations
    active_r = await db.execute(
        select(sa_func.count()).where(
            OutreachLog.user_id == user_id,
            OutreachLog.status.in_(["sent", "connected", "following_up"]),
        )
    )
    active_conversations = active_r.scalar() or 0

    return {
        "total_contacts": total_contacts,
        "total_messages_sent": total_messages_sent,
        "total_jobs_tracked": total_jobs_tracked,
        "overall_response_rate": response_rate,
        "upcoming_follow_ups": upcoming_follow_ups,
        "active_conversations": active_conversations,
    }


# ---------------------------------------------------------------------------
# Response rate breakdowns
# ---------------------------------------------------------------------------

async def get_response_rate_by_channel(
    db: AsyncSession, user_id: uuid.UUID
) -> list[dict]:
    """Response rate grouped by outreach channel."""
    result = await db.execute(
        select(
            OutreachLog.channel,
            sa_func.count().label("sent"),
            sa_func.sum(
                cast(OutreachLog.response_received, Integer)
            ).label("responded"),
        )
        .where(OutreachLog.user_id == user_id, OutreachLog.status != "draft")
        .group_by(OutreachLog.channel)
    )
    rows = result.all()
    return [
        {
            "label": row[0] or "unknown",
            "sent": row[1],
            "responded": int(row[2] or 0),
            "rate": round((int(row[2] or 0) / row[1] * 100), 1) if row[1] > 0 else 0.0,
        }
        for row in rows
    ]


async def get_response_rate_by_role(
    db: AsyncSession, user_id: uuid.UUID
) -> list[dict]:
    """Response rate grouped by person type (recruiter, hiring_manager, peer)."""
    result = await db.execute(
        select(
            Person.person_type,
            sa_func.count().label("sent"),
            sa_func.sum(
                cast(OutreachLog.response_received, Integer)
            ).label("responded"),
        )
        .join(Person, OutreachLog.person_id == Person.id)
        .where(OutreachLog.user_id == user_id, OutreachLog.status != "draft")
        .group_by(Person.person_type)
    )
    rows = result.all()
    return [
        {
            "label": row[0] or "unknown",
            "sent": row[1],
            "responded": int(row[2] or 0),
            "rate": round((int(row[2] or 0) / row[1] * 100), 1) if row[1] > 0 else 0.0,
        }
        for row in rows
    ]


async def get_response_rate_by_company(
    db: AsyncSession, user_id: uuid.UUID
) -> list[dict]:
    """Response rate grouped by company name."""
    result = await db.execute(
        select(
            Company.name,
            sa_func.count().label("sent"),
            sa_func.sum(
                cast(OutreachLog.response_received, Integer)
            ).label("responded"),
        )
        .join(Person, OutreachLog.person_id == Person.id)
        .join(Company, Person.company_id == Company.id)
        .where(OutreachLog.user_id == user_id, OutreachLog.status != "draft")
        .group_by(Company.name)
    )
    rows = result.all()
    return [
        {
            "label": row[0],
            "sent": row[1],
            "responded": int(row[2] or 0),
            "rate": round((int(row[2] or 0) / row[1] * 100), 1) if row[1] > 0 else 0.0,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Message angle effectiveness
# ---------------------------------------------------------------------------

async def get_angle_effectiveness(
    db: AsyncSession, user_id: uuid.UUID
) -> list[dict]:
    """Response rate by message goal (intro, coffee_chat, referral, etc.)."""
    result = await db.execute(
        select(
            Message.goal,
            sa_func.count().label("sent"),
            sa_func.sum(
                cast(OutreachLog.response_received, Integer)
            ).label("responded"),
        )
        .join(OutreachLog, OutreachLog.message_id == Message.id)
        .where(OutreachLog.user_id == user_id, OutreachLog.status != "draft")
        .group_by(Message.goal)
    )
    rows = result.all()
    return [
        {
            "goal": row[0] or "unknown",
            "sent": row[1],
            "responded": int(row[2] or 0),
            "rate": round((int(row[2] or 0) / row[1] * 100), 1) if row[1] > 0 else 0.0,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Network growth (time series)
# ---------------------------------------------------------------------------

async def get_network_growth(
    db: AsyncSession, user_id: uuid.UUID
) -> list[dict]:
    """Cumulative distinct contacts over time, grouped by week."""
    result = await db.execute(
        select(
            sa_func.date_trunc("week", OutreachLog.created_at).label("week"),
            sa_func.count(sa_func.distinct(OutreachLog.person_id)).label("new_contacts"),
        )
        .where(OutreachLog.user_id == user_id)
        .group_by("week")
        .order_by("week")
    )
    rows = result.all()

    # Compute cumulative sum
    cumulative = 0
    points = []
    for row in rows:
        cumulative += row[1]
        points.append({
            "date": row[0].isoformat() if row[0] else "",
            "cumulative_contacts": cumulative,
        })
    return points


# ---------------------------------------------------------------------------
# Network gaps
# ---------------------------------------------------------------------------

async def get_network_gaps(
    db: AsyncSession, user_id: uuid.UUID
) -> list[dict]:
    """Industries and roles not yet reached vs profile targets."""
    # Get user profile targets
    profile_r = await db.execute(
        select(Profile).where(Profile.user_id == user_id)
    )
    profile = profile_r.scalar_one_or_none()

    gaps: list[dict] = []

    if not profile:
        return gaps

    # --- Industry gaps ---
    target_industries = profile.target_industries or []
    if target_industries:
        contacted_r = await db.execute(
            select(sa_func.distinct(Company.industry))
            .join(Person, Person.company_id == Company.id)
            .join(OutreachLog, OutreachLog.person_id == Person.id)
            .where(OutreachLog.user_id == user_id, Company.industry.is_not(None))
        )
        contacted_industries = {r[0].lower() for r in contacted_r.all() if r[0]}

        for ind in target_industries:
            if ind.lower() not in contacted_industries:
                gaps.append({"category": "industry", "label": ind, "count": 0})

    # --- Role gaps ---
    target_roles = profile.target_roles or []
    if target_roles:
        contacted_roles_r = await db.execute(
            select(sa_func.distinct(Person.department))
            .join(OutreachLog, OutreachLog.person_id == Person.id)
            .where(OutreachLog.user_id == user_id, Person.department.is_not(None))
        )
        contacted_roles = {r[0].lower() for r in contacted_roles_r.all() if r[0]}

        for role in target_roles:
            if role.lower() not in contacted_roles:
                gaps.append({"category": "role", "label": role, "count": 0})

    return gaps


# ---------------------------------------------------------------------------
# Warm paths
# ---------------------------------------------------------------------------

async def get_warm_paths(
    db: AsyncSession, user_id: uuid.UUID
) -> list[dict]:
    """Companies where user already has positive connections."""
    result = await db.execute(
        select(
            Company.name,
            Person.full_name,
            Person.title,
            OutreachLog.status,
        )
        .join(Person, OutreachLog.person_id == Person.id)
        .join(Company, Person.company_id == Company.id)
        .where(
            OutreachLog.user_id == user_id,
            OutreachLog.status.in_(["connected", "responded", "met"]),
        )
        .order_by(Company.name)
    )
    rows = result.all()

    by_company: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_company[row[0]].append({
            "name": row[1] or "Unknown",
            "title": row[2],
            "status": row[3],
        })

    return [
        {"company_name": name, "connected_persons": persons}
        for name, persons in by_company.items()
    ]


# ---------------------------------------------------------------------------
# Company openness ranking
# ---------------------------------------------------------------------------

async def get_company_openness(
    db: AsyncSession, user_id: uuid.UUID
) -> list[dict]:
    """Companies ranked by response rate (min 2 outreach attempts)."""
    result = await db.execute(
        select(
            Company.name,
            sa_func.count().label("total"),
            sa_func.sum(
                cast(OutreachLog.response_received, Integer)
            ).label("responses"),
        )
        .join(Person, OutreachLog.person_id == Person.id)
        .join(Company, Person.company_id == Company.id)
        .where(OutreachLog.user_id == user_id, OutreachLog.status != "draft")
        .group_by(Company.name)
        .having(sa_func.count() >= 2)
    )
    rows = result.all()

    companies = []
    for row in rows:
        total = row[1]
        responses = int(row[2] or 0)
        companies.append({
            "company_name": row[0],
            "total_outreach": total,
            "responses": responses,
            "rate": round((responses / total * 100), 1) if total > 0 else 0.0,
        })

    # Sort by rate descending
    companies.sort(key=lambda c: c["rate"], reverse=True)
    return companies


# ---------------------------------------------------------------------------
# Job pipeline — counts per Job.stage
# ---------------------------------------------------------------------------

async def get_job_pipeline(
    db: AsyncSession, user_id: uuid.UUID
) -> list[dict]:
    """Counts of tracked jobs grouped by Kanban stage.

    Stage values follow `Job.stage`: discovered | interested | researching |
    networking | applied | interviewing | offer | accepted | rejected |
    withdrawn.
    """
    result = await db.execute(
        select(
            Job.stage,
            sa_func.count().label("count"),
        )
        .where(Job.user_id == user_id)
        .group_by(Job.stage)
    )
    return [
        {"stage": row[0] or "discovered", "count": int(row[1])}
        for row in result.all()
    ]


# ---------------------------------------------------------------------------
# API usage by service — last N days
# ---------------------------------------------------------------------------

async def get_api_usage_by_service(
    db: AsyncSession, user_id: uuid.UUID
) -> list[dict]:
    """Per-service call counts and cost over the last `API_USAGE_WINDOW_DAYS`.

    Sources: `ApiUsage` rows. Today this captures email-finder calls
    (`hunter`) and message-drafting LLM calls. Search-provider calls are
    not currently recorded in `ApiUsage` and will simply not appear until
    they are.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=API_USAGE_WINDOW_DAYS)
    result = await db.execute(
        select(
            ApiUsage.service,
            sa_func.count().label("calls"),
            sa_func.coalesce(sa_func.sum(ApiUsage.cost_cents), 0).label("cost_cents"),
        )
        .where(
            ApiUsage.user_id == user_id,
            ApiUsage.created_at >= cutoff,
        )
        .group_by(ApiUsage.service)
        .order_by(sa_func.count().desc())
    )
    return [
        {
            "service": row[0] or "unknown",
            "calls": int(row[1]),
            "cost_cents": int(row[2] or 0),
        }
        for row in result.all()
    ]


# ---------------------------------------------------------------------------
# LinkedIn-graph warm paths — top companies in the imported graph
# ---------------------------------------------------------------------------

async def get_graph_warm_paths(
    db: AsyncSession, user_id: uuid.UUID
) -> list[dict]:
    """Top companies in the user's imported LinkedIn graph by connection count.

    This is intentionally separate from `get_warm_paths`, which is
    outreach-derived. Per project rules, imported LinkedIn graph data must
    not be conflated with CRM `Person` rows or with outreach warm paths.
    """
    company_expr = sa_func.coalesce(
        LinkedInGraphConnection.normalized_company_name,
        LinkedInGraphConnection.current_company_name,
    )
    result = await db.execute(
        select(
            company_expr.label("company"),
            sa_func.count().label("connections"),
            sa_func.max(LinkedInGraphConnection.last_synced_at).label("last_synced_at"),
        )
        .where(
            LinkedInGraphConnection.user_id == user_id,
            company_expr.is_not(None),
        )
        .group_by(company_expr)
        .order_by(sa_func.count().desc())
        .limit(GRAPH_WARM_PATHS_LIMIT)
    )
    companies = []
    for row in result.all():
        freshness = graph_freshness_metadata(row[2])
        companies.append({
            "company_name": row[0],
            "connection_count": int(row[1]),
            "freshness": freshness["freshness"],
            "days_since_sync": freshness["days_since_sync"],
            "refresh_recommended": freshness["refresh_recommended"],
        })
    return companies


def _merge_warm_path_companies(
    outreach_paths: list[dict],
    graph_paths: list[dict],
) -> list[dict]:
    merged: dict[str, dict] = {}

    for item in outreach_paths:
        merged[item["company_name"]] = {
            "company_name": item["company_name"],
            "connected_persons": item["connected_persons"],
            "outreach_connection_count": len(item["connected_persons"]),
            "graph_connection_count": 0,
            "graph_freshness": None,
            "graph_days_since_sync": None,
            "graph_refresh_recommended": False,
        }

    for item in graph_paths:
        target = merged.setdefault(
            item["company_name"],
            {
                "company_name": item["company_name"],
                "connected_persons": [],
                "outreach_connection_count": 0,
                "graph_connection_count": 0,
                "graph_freshness": None,
                "graph_days_since_sync": None,
                "graph_refresh_recommended": False,
            },
        )
        target["graph_connection_count"] = int(item["connection_count"])
        target["graph_freshness"] = item.get("freshness")
        target["graph_days_since_sync"] = item.get("days_since_sync")
        target["graph_refresh_recommended"] = bool(item.get("refresh_recommended"))

    return sorted(
        merged.values(),
        key=lambda item: (
            -(item["outreach_connection_count"] > 0),
            -(item["graph_connection_count"] > 0),
            -(item["outreach_connection_count"] + item["graph_connection_count"]),
            item["company_name"].lower(),
        ),
    )


# ---------------------------------------------------------------------------
# Composite dashboard
# ---------------------------------------------------------------------------

async def get_full_dashboard(
    db: AsyncSession, user_id: uuid.UUID
) -> dict:
    """Fetch all dashboard data.

    Runs sequentially because async SQLAlchemy sessions do not support
    concurrent operations from asyncio.gather on a single connection.
    """
    summary = await get_dashboard_summary(db, user_id)
    by_channel = await get_response_rate_by_channel(db, user_id)
    by_role = await get_response_rate_by_role(db, user_id)
    by_company = await get_response_rate_by_company(db, user_id)
    angles = await get_angle_effectiveness(db, user_id)
    growth = await get_network_growth(db, user_id)
    gaps = await get_network_gaps(db, user_id)
    warm = await get_warm_paths(db, user_id)
    openness = await get_company_openness(db, user_id)
    pipeline = await get_job_pipeline(db, user_id)
    api_usage = await get_api_usage_by_service(db, user_id)
    graph_warm = await get_graph_warm_paths(db, user_id)
    warm_path_companies = _merge_warm_path_companies(warm, graph_warm)

    return {
        "summary": summary,
        "response_by_channel": by_channel,
        "response_by_role": by_role,
        "response_by_company": by_company,
        "angle_effectiveness": angles,
        "network_growth": growth,
        "network_gaps": gaps,
        "warm_paths": warm,
        "warm_path_companies": warm_path_companies,
        "company_openness": openness,
        "job_pipeline": pipeline,
        "api_usage_by_service": api_usage,
        "graph_warm_paths": graph_warm,
    }
