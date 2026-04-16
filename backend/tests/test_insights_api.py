"""API tests for insights dashboard endpoint — Phase 8."""

import pytest
from unittest.mock import patch, AsyncMock

pytestmark = pytest.mark.asyncio


MOCK_DASHBOARD = {
    "summary": {
        "total_contacts": 18,
        "total_messages_sent": 12,
        "total_jobs_tracked": 45,
        "overall_response_rate": 33.3,
        "upcoming_follow_ups": 5,
        "active_conversations": 7,
    },
    "response_by_channel": [
        {"label": "linkedin_message", "sent": 8, "responded": 3, "rate": 37.5},
        {"label": "email", "sent": 4, "responded": 1, "rate": 25.0},
    ],
    "response_by_role": [
        {"label": "recruiter", "sent": 5, "responded": 2, "rate": 40.0},
        {"label": "peer", "sent": 7, "responded": 2, "rate": 28.6},
    ],
    "response_by_company": [
        {"label": "TechCorp", "sent": 4, "responded": 2, "rate": 50.0},
        {"label": "Acme Inc", "sent": 3, "responded": 0, "rate": 0.0},
    ],
    "angle_effectiveness": [
        {"goal": "intro", "sent": 6, "responded": 2, "rate": 33.3},
        {"goal": "coffee_chat", "sent": 3, "responded": 2, "rate": 66.7},
    ],
    "network_growth": [
        {"date": "2024-03-04T00:00:00+00:00", "cumulative_contacts": 5},
        {"date": "2024-03-11T00:00:00+00:00", "cumulative_contacts": 12},
    ],
    "network_gaps": [
        {"category": "industry", "label": "Fintech", "count": 0},
        {"category": "role", "label": "Data Science", "count": 0},
    ],
    "warm_paths": [
        {
            "company_name": "TechCorp",
            "connected_persons": [
                {"name": "Jane Smith", "title": "Engineering Manager", "status": "connected"},
            ],
        }
    ],
    "company_openness": [
        {"company_name": "TechCorp", "total_outreach": 4, "responses": 2, "rate": 50.0},
    ],
    "job_pipeline": [
        {"stage": "discovered", "count": 20},
        {"stage": "applied", "count": 8},
        {"stage": "interviewing", "count": 3},
        {"stage": "offer", "count": 1},
    ],
    "api_usage_by_service": [
        {"service": "hunter", "calls": 14, "cost_cents": 0},
        {"service": "anthropic", "calls": 9, "cost_cents": 42},
    ],
    "graph_warm_paths": [
        {"company_name": "TechCorp", "connection_count": 6},
        {"company_name": "Acme Inc", "connection_count": 2},
    ],
}


# ===========================================================================
# GET /api/insights/dashboard
# ===========================================================================

async def test_dashboard_returns_full_data(client, mock_user_id):
    """GET /api/insights/dashboard returns the composite insights response."""
    with patch(
        "app.routers.insights.get_full_dashboard", new_callable=AsyncMock
    ) as m:
        m.return_value = MOCK_DASHBOARD
        resp = await client.get("/api/insights/dashboard")

    assert resp.status_code == 200
    data = resp.json()

    # Verify top-level keys
    assert "summary" in data
    assert "response_by_channel" in data
    assert "response_by_role" in data
    assert "response_by_company" in data
    assert "angle_effectiveness" in data
    assert "network_growth" in data
    assert "network_gaps" in data
    assert "warm_paths" in data
    assert "company_openness" in data
    assert "job_pipeline" in data
    assert "api_usage_by_service" in data
    assert "graph_warm_paths" in data


async def test_dashboard_summary_fields(client, mock_user_id):
    """Summary includes all KPI fields."""
    with patch(
        "app.routers.insights.get_full_dashboard", new_callable=AsyncMock
    ) as m:
        m.return_value = MOCK_DASHBOARD
        resp = await client.get("/api/insights/dashboard")

    summary = resp.json()["summary"]
    assert summary["total_contacts"] == 18
    assert summary["total_messages_sent"] == 12
    assert summary["total_jobs_tracked"] == 45
    assert summary["overall_response_rate"] == 33.3
    assert summary["upcoming_follow_ups"] == 5
    assert summary["active_conversations"] == 7


async def test_dashboard_response_by_channel(client, mock_user_id):
    """Response by channel has correct structure."""
    with patch(
        "app.routers.insights.get_full_dashboard", new_callable=AsyncMock
    ) as m:
        m.return_value = MOCK_DASHBOARD
        resp = await client.get("/api/insights/dashboard")

    by_channel = resp.json()["response_by_channel"]
    assert len(by_channel) == 2
    assert by_channel[0]["label"] == "linkedin_message"
    assert by_channel[0]["rate"] == 37.5


async def test_dashboard_network_growth(client, mock_user_id):
    """Network growth returns time series points."""
    with patch(
        "app.routers.insights.get_full_dashboard", new_callable=AsyncMock
    ) as m:
        m.return_value = MOCK_DASHBOARD
        resp = await client.get("/api/insights/dashboard")

    growth = resp.json()["network_growth"]
    assert len(growth) == 2
    assert growth[0]["cumulative_contacts"] == 5
    assert growth[1]["cumulative_contacts"] == 12


async def test_dashboard_warm_paths(client, mock_user_id):
    """Warm paths includes connected persons per company."""
    with patch(
        "app.routers.insights.get_full_dashboard", new_callable=AsyncMock
    ) as m:
        m.return_value = MOCK_DASHBOARD
        resp = await client.get("/api/insights/dashboard")

    paths = resp.json()["warm_paths"]
    assert len(paths) == 1
    assert paths[0]["company_name"] == "TechCorp"
    assert len(paths[0]["connected_persons"]) == 1
    assert paths[0]["connected_persons"][0]["name"] == "Jane Smith"


async def test_dashboard_network_gaps(client, mock_user_id):
    """Network gaps lists unreached targets."""
    with patch(
        "app.routers.insights.get_full_dashboard", new_callable=AsyncMock
    ) as m:
        m.return_value = MOCK_DASHBOARD
        resp = await client.get("/api/insights/dashboard")

    gaps = resp.json()["network_gaps"]
    assert len(gaps) == 2
    industry_gaps = [g for g in gaps if g["category"] == "industry"]
    role_gaps = [g for g in gaps if g["category"] == "role"]
    assert len(industry_gaps) == 1
    assert len(role_gaps) == 1


async def test_dashboard_angle_effectiveness(client, mock_user_id):
    """Angle effectiveness shows goal-based response rates."""
    with patch(
        "app.routers.insights.get_full_dashboard", new_callable=AsyncMock
    ) as m:
        m.return_value = MOCK_DASHBOARD
        resp = await client.get("/api/insights/dashboard")

    angles = resp.json()["angle_effectiveness"]
    assert len(angles) == 2
    coffee = next(a for a in angles if a["goal"] == "coffee_chat")
    assert coffee["rate"] == 66.7


async def test_dashboard_company_openness(client, mock_user_id):
    """Company openness returns ranked companies."""
    with patch(
        "app.routers.insights.get_full_dashboard", new_callable=AsyncMock
    ) as m:
        m.return_value = MOCK_DASHBOARD
        resp = await client.get("/api/insights/dashboard")

    openness = resp.json()["company_openness"]
    assert len(openness) == 1
    assert openness[0]["rate"] == 50.0


async def test_dashboard_job_pipeline(client, mock_user_id):
    """Job pipeline returns counts grouped by stage."""
    with patch(
        "app.routers.insights.get_full_dashboard", new_callable=AsyncMock
    ) as m:
        m.return_value = MOCK_DASHBOARD
        resp = await client.get("/api/insights/dashboard")

    pipeline = resp.json()["job_pipeline"]
    stages = {row["stage"]: row["count"] for row in pipeline}
    assert stages["discovered"] == 20
    assert stages["applied"] == 8
    assert stages["interviewing"] == 3
    assert stages["offer"] == 1


async def test_dashboard_api_usage_by_service(client, mock_user_id):
    """API usage breakdown groups by service over the rolling window."""
    with patch(
        "app.routers.insights.get_full_dashboard", new_callable=AsyncMock
    ) as m:
        m.return_value = MOCK_DASHBOARD
        resp = await client.get("/api/insights/dashboard")

    usage = resp.json()["api_usage_by_service"]
    services = {row["service"]: row for row in usage}
    assert services["hunter"]["calls"] == 14
    assert services["anthropic"]["cost_cents"] == 42


async def test_dashboard_graph_warm_paths(client, mock_user_id):
    """Graph warm paths surface companies from the imported LinkedIn graph."""
    with patch(
        "app.routers.insights.get_full_dashboard", new_callable=AsyncMock
    ) as m:
        m.return_value = MOCK_DASHBOARD
        resp = await client.get("/api/insights/dashboard")

    graph = resp.json()["graph_warm_paths"]
    assert len(graph) == 2
    assert graph[0]["company_name"] == "TechCorp"
    assert graph[0]["connection_count"] == 6


async def test_dashboard_empty_state(client, mock_user_id):
    """Dashboard returns zeros and empty lists for new users."""
    empty = {
        "summary": {
            "total_contacts": 0,
            "total_messages_sent": 0,
            "total_jobs_tracked": 0,
            "overall_response_rate": 0.0,
            "upcoming_follow_ups": 0,
            "active_conversations": 0,
        },
        "response_by_channel": [],
        "response_by_role": [],
        "response_by_company": [],
        "angle_effectiveness": [],
        "network_growth": [],
        "network_gaps": [],
        "warm_paths": [],
        "company_openness": [],
        "job_pipeline": [],
        "api_usage_by_service": [],
        "graph_warm_paths": [],
    }
    with patch(
        "app.routers.insights.get_full_dashboard", new_callable=AsyncMock
    ) as m:
        m.return_value = empty
        resp = await client.get("/api/insights/dashboard")

    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["total_contacts"] == 0
    assert data["network_growth"] == []


async def test_dashboard_requires_auth(unauthed_client):
    """GET /api/insights/dashboard returns 401 without auth."""
    resp = await unauthed_client.get("/api/insights/dashboard")
    assert resp.status_code in (401, 403)
