"""API tests for jobs endpoints — Phase 6."""

import uuid
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone

pytestmark = pytest.mark.asyncio


def _mock_job(user_id, **overrides):
    j = MagicMock()
    j.id = overrides.get("id", uuid.uuid4())
    j.user_id = user_id
    j.title = overrides.get("title", "Software Engineer")
    j.company_name = overrides.get("company_name", "TechCorp")
    j.company_logo = overrides.get("company_logo", None)
    j.location = overrides.get("location", "New York, NY")
    j.remote = overrides.get("remote", False)
    j.url = overrides.get("url", "https://example.com/job/1")
    j.description = overrides.get("description", "Build things")
    j.employment_type = overrides.get("employment_type", "full_time")
    j.salary_min = overrides.get("salary_min", 100000.0)
    j.salary_max = overrides.get("salary_max", 150000.0)
    j.salary_currency = overrides.get("salary_currency", "USD")
    j.source = overrides.get("source", "jsearch")
    j.ats = overrides.get("ats", None)
    j.posted_at = overrides.get("posted_at", "2024-01-15")
    j.match_score = overrides.get("match_score", 75.0)
    j.score_breakdown = overrides.get("score_breakdown", {"role_match": 30, "skills_match": 20})
    j.stage = overrides.get("stage", "discovered")
    j.tags = overrides.get("tags", None)
    j.department = overrides.get("department", None)
    j.experience_level = overrides.get("experience_level", None)
    j.notes = overrides.get("notes", None)
    j.starred = overrides.get("starred", False)
    j.applied_at = overrides.get("applied_at", None)
    j.offer_details = overrides.get("offer_details", None)
    j.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)
    j.updated_at = datetime(2024, 1, 15, tzinfo=timezone.utc)
    return j


async def test_search_jobs(client, mock_user_id):
    """POST /api/jobs/search returns scored job results."""
    job = _mock_job(mock_user_id)

    with patch("app.routers.jobs.search_jobs", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = [job]
        resp = await client.post(
            "/api/jobs/search",
            json={"query": "software engineer", "remote_only": False},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Software Engineer"
    assert data[0]["match_score"] == 75.0


async def test_search_ats(client, mock_user_id):
    """POST /api/jobs/search/ats returns ATS board results."""
    job = _mock_job(mock_user_id, source="greenhouse", ats="greenhouse")

    with patch("app.routers.jobs.search_ats_jobs", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = [job]
        resp = await client.post(
            "/api/jobs/search/ats",
            json={"company_slug": "stripe", "ats_type": "greenhouse"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["source"] == "greenhouse"


async def test_search_ats_with_job_url(client, mock_user_id):
    """POST /api/jobs/search/ats accepts a direct job posting URL."""
    job = _mock_job(mock_user_id, source="greenhouse", ats="greenhouse")

    with patch("app.routers.jobs.search_ats_jobs", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = [job]
        resp = await client.post(
            "/api/jobs/search/ats",
            json={"job_url": "https://job-boards.greenhouse.io/affirm/jobs/7550577003"},
        )

    assert resp.status_code == 200
    mock_search.assert_awaited_once()
    call_kwargs = mock_search.call_args.kwargs
    assert call_kwargs["job_url"] == "https://job-boards.greenhouse.io/affirm/jobs/7550577003"
    assert call_kwargs["company_slug"] is None
    assert call_kwargs["ats_type"] is None


async def test_search_ats_with_apple_job_url(client, mock_user_id):
    """POST /api/jobs/search/ats accepts Apple Jobs exact-job URLs."""
    job = _mock_job(mock_user_id, source="apple_jobs", ats="apple_jobs", company_name="Apple")

    with patch("app.routers.jobs.search_ats_jobs", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = [job]
        resp = await client.post(
            "/api/jobs/search/ats",
            json={
                "job_url": (
                    "https://jobs.apple.com/en-us/details/200652765/software-engineer-core-os-telemetry"
                    "?board_id=17682&jr_id=69bdc46c393a1008f7434e68"
                )
            },
        )

    assert resp.status_code == 200
    mock_search.assert_awaited_once()
    call_kwargs = mock_search.call_args.kwargs
    assert call_kwargs["job_url"].startswith("https://jobs.apple.com/en-us/details/200652765/")


async def test_search_ats_with_workday_job_url(client, mock_user_id):
    """POST /api/jobs/search/ats accepts Workday exact-job URLs."""
    job = _mock_job(mock_user_id, source="workday", ats="workday", company_name="NVIDIA")

    with patch("app.routers.jobs.search_ats_jobs", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = [job]
        resp = await client.post(
            "/api/jobs/search/ats",
            json={
                "job_url": (
                    "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-OR-Hillsboro/"
                    "Senior-Systems-Software-Engineer---New-College-Grad-2026_JR2015144-1"
                    "?jr_id=69bd8442b106024562826cc8"
                )
            },
        )

    assert resp.status_code == 200
    mock_search.assert_awaited_once()
    call_kwargs = mock_search.call_args.kwargs
    assert call_kwargs["job_url"].startswith("https://nvidia.wd5.myworkdayjobs.com/")


async def test_search_ats_accepts_dev_mode_without_token(unauthed_client, monkeypatch):
    """POST /api/jobs/search/ats works without Authorization in dev auth mode."""
    from app.database import get_db
    from app.main import app
    from app.config import settings

    fake_db = MagicMock()

    async def _override_db():
        yield fake_db

    monkeypatch.setattr(settings, "auth_mode", "dev")
    monkeypatch.setattr(settings, "dev_user_id", uuid.UUID("00000000-0000-0000-0000-000000000001"))
    monkeypatch.setattr(settings, "dev_user_email", "dev@nexusreach.local")
    app.dependency_overrides[get_db] = _override_db

    job = _mock_job(settings.dev_user_id, source="lever", ats="lever")

    try:
        with patch("app.routers.jobs.search_ats_jobs", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = [job]
            resp = await unauthed_client.post(
                "/api/jobs/search/ats",
                json={"job_url": "https://jobs.lever.co/pointclickcare/471f17d7-98b4-446c-9f62-796aa783a648"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    assert resp.json()[0]["ats"] == "lever"


async def test_list_jobs(client, mock_user_id):
    """GET /api/jobs returns saved jobs."""
    job1 = _mock_job(mock_user_id, match_score=80.0)
    job2 = _mock_job(mock_user_id, match_score=60.0, title="Frontend Dev")

    with patch("app.routers.jobs.get_jobs", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = ([job1, job2], 2)
        resp = await client.get("/api/jobs")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 2
    assert data["total"] == 2


async def test_list_jobs_with_stage_filter(client, mock_user_id):
    """GET /api/jobs?stage=applied filters by stage."""
    job = _mock_job(mock_user_id, stage="applied")

    with patch("app.routers.jobs.get_jobs", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = ([job], 1)
        resp = await client.get("/api/jobs", params={"stage": "applied"})

    assert resp.status_code == 200
    mock_get.assert_called_once()
    # Verify the stage parameter was passed
    call_args = mock_get.call_args
    assert call_args.kwargs.get("stage") == "applied" or call_args[1].get("stage") == "applied"


async def test_list_jobs_with_startup_filter(client, mock_user_id):
    """GET /api/jobs?startup=true filters startup-tagged jobs."""
    job = _mock_job(mock_user_id, tags=["startup", "startup_source:yc_jobs"])

    with patch("app.routers.jobs.get_jobs", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = ([job], 1)
        resp = await client.get("/api/jobs", params={"startup": "true"})

    assert resp.status_code == 200
    mock_get.assert_called_once()
    call_args = mock_get.call_args
    assert call_args.kwargs.get("startup") is True or call_args[1].get("startup") is True


async def test_get_single_job(client, mock_user_id):
    """GET /api/jobs/{id} returns a single job."""
    job = _mock_job(mock_user_id)

    with patch("app.routers.jobs.get_job", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = job
        resp = await client.get(f"/api/jobs/{uuid.uuid4()}")

    assert resp.status_code == 200
    assert resp.json()["title"] == "Software Engineer"


async def test_get_job_command_center(client, mock_user_id):
    """GET /api/jobs/{id}/command-center returns the job workflow summary."""
    job_id = uuid.uuid4()
    payload = {
        "job_id": str(job_id),
        "stage": "researching",
        "checklist": {
            "resume_uploaded": True,
            "match_scored": True,
            "resume_tailored": False,
            "resume_artifact_generated": False,
            "contacts_saved": True,
            "outreach_started": False,
            "applied": False,
            "interview_rounds_logged": False,
        },
        "stats": {
            "saved_contacts_count": 3,
            "verified_contacts_count": 2,
            "reachable_contacts_count": 3,
            "drafted_messages_count": 1,
            "outreach_count": 0,
            "active_outreach_count": 0,
            "responded_outreach_count": 0,
            "due_follow_ups_count": 0,
        },
        "next_action": {
            "key": "draft_first_outreach",
            "title": "Draft your first message",
            "detail": "You already have company contacts saved for this role, but no outreach has been logged yet.",
            "cta_label": "Open Messages",
            "cta_section": "activity",
        },
        "top_contacts": [
            {
                "id": str(uuid.uuid4()),
                "full_name": "Jane Recruiter",
                "title": "Senior Recruiter",
                "person_type": "recruiter",
                "work_email": "jane@example.com",
                "linkedin_url": "https://linkedin.com/in/jane",
                "email_verified": True,
                "current_company_verified": True,
            }
        ],
        "recent_messages": [],
        "recent_outreach": [],
    }

    with patch("app.routers.jobs.get_job_command_center", new_callable=AsyncMock) as mock_summary:
        mock_summary.return_value = payload
        resp = await client.get(f"/api/jobs/{job_id}/command-center")

    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == str(job_id)
    assert data["stats"]["saved_contacts_count"] == 3
    assert data["next_action"]["key"] == "draft_first_outreach"


async def test_generate_resume_artifact(client, mock_user_id):
    """POST /api/jobs/{id}/resume-artifact generates a saved resume artifact."""
    job_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    tailored_id = uuid.uuid4()
    artifact = MagicMock()
    artifact.id = artifact_id
    artifact.job_id = job_id
    artifact.tailored_resume_id = tailored_id
    artifact.format = "latex"
    artifact.filename = "resume-techcorp-2026-04-18.tex"
    artifact.content = "\\documentclass{article}\n"
    artifact.generated_at = datetime(2026, 4, 18, tzinfo=timezone.utc)
    artifact.created_at = datetime(2026, 4, 18, tzinfo=timezone.utc)
    artifact.updated_at = datetime(2026, 4, 18, tzinfo=timezone.utc)
    artifact.rewrite_decisions = {}

    from app.schemas.jobs import ResumeArtifactResponse

    async def _fake_build(_db, *, user_id, job_id, artifact):
        return ResumeArtifactResponse(
            id=str(artifact.id),
            job_id=job_id,
            tailored_resume_id=str(artifact.tailored_resume_id) if artifact.tailored_resume_id else None,
            format=artifact.format,
            filename=artifact.filename,
            content=artifact.content,
            generated_at=artifact.generated_at.isoformat(),
            created_at=artifact.created_at.isoformat(),
            updated_at=artifact.updated_at.isoformat(),
        )

    with patch("app.routers.jobs.generate_resume_artifact_for_job", new_callable=AsyncMock) as mock_generate, \
         patch("app.routers.jobs._build_artifact_response", side_effect=_fake_build):
        mock_generate.return_value = artifact
        resp = await client.post(f"/api/jobs/{job_id}/resume-artifact")

    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == str(job_id)
    assert data["format"] == "latex"
    assert data["filename"] == "resume-techcorp-2026-04-18.tex"
    assert mock_generate.await_args.kwargs["allow_auto_reuse"] is True


async def test_generate_resume_artifact_force_new_bypasses_auto_reuse(client, mock_user_id):
    """POST /api/jobs/{id}/resume-artifact?force_new=true bypasses auto reuse."""
    job_id = uuid.uuid4()
    artifact = MagicMock()
    artifact.id = uuid.uuid4()
    artifact.job_id = job_id
    artifact.tailored_resume_id = uuid.uuid4()
    artifact.format = "latex"
    artifact.filename = "resume-techcorp-2026-04-18.tex"
    artifact.content = "\\documentclass{article}\n"
    artifact.generated_at = datetime(2026, 4, 18, tzinfo=timezone.utc)
    artifact.created_at = datetime(2026, 4, 18, tzinfo=timezone.utc)
    artifact.updated_at = datetime(2026, 4, 18, tzinfo=timezone.utc)
    artifact.rewrite_decisions = {}

    from app.schemas.jobs import ResumeArtifactResponse

    async def _fake_build(_db, *, user_id, job_id, artifact):
        return ResumeArtifactResponse(
            id=str(artifact.id),
            job_id=job_id,
            tailored_resume_id=str(artifact.tailored_resume_id),
            format=artifact.format,
            filename=artifact.filename,
            content=artifact.content,
            generated_at=artifact.generated_at.isoformat(),
            created_at=artifact.created_at.isoformat(),
            updated_at=artifact.updated_at.isoformat(),
        )

    with patch("app.routers.jobs.generate_resume_artifact_for_job", new_callable=AsyncMock) as mock_generate, \
         patch("app.routers.jobs._build_artifact_response", side_effect=_fake_build):
        mock_generate.return_value = artifact
        resp = await client.post(f"/api/jobs/{job_id}/resume-artifact?force_new=true")

    assert resp.status_code == 200
    assert mock_generate.await_args.kwargs["allow_auto_reuse"] is False


async def test_get_resume_reuse_candidates(client, mock_user_id):
    """GET /api/jobs/{id}/resume-artifact/reuse-candidates returns saved matches."""
    job_id = uuid.uuid4()
    artifact = MagicMock()
    artifact.id = uuid.uuid4()
    artifact.filename = "resume-acme-2026-04-18.tex"
    artifact.generated_at = datetime(2026, 4, 18, tzinfo=timezone.utc)
    artifact.updated_at = datetime(2026, 4, 19, tzinfo=timezone.utc)
    source_job = MagicMock()
    source_job.id = uuid.uuid4()
    source_job.title = "Full-Stack Engineer"
    source_job.company_name = "Acme"
    candidate = {
        "artifact": artifact,
        "source_job": source_job,
        "score": 91.2,
        "threshold": 80.0,
        "job_family": "frontend_fullstack",
        "reason": "This saved resume scores 91.2% against the new posting.",
    }

    with patch(
        "app.routers.jobs.get_resume_reuse_candidates_for_job",
        new_callable=AsyncMock,
    ) as mock_candidates, patch(
        "app.routers.jobs.get_resume_auto_reuse_enabled",
        new_callable=AsyncMock,
    ) as mock_auto:
        mock_candidates.return_value = [candidate]
        mock_auto.return_value = False
        resp = await client.get(f"/api/jobs/{job_id}/resume-artifact/reuse-candidates")

    assert resp.status_code == 200
    data = resp.json()
    assert data["threshold"] == 80.0
    assert data["auto_reuse_enabled"] is False
    assert data["candidates"][0]["artifact_id"] == str(artifact.id)
    assert data["candidates"][0]["score"] == 91.2


async def test_reuse_resume_artifact(client, mock_user_id):
    """POST /api/jobs/{id}/resume-artifact/reuse/{artifact_id} reuses a saved artifact."""
    job_id = uuid.uuid4()
    source_artifact_id = uuid.uuid4()
    artifact = MagicMock()
    artifact.id = uuid.uuid4()
    artifact.job_id = job_id
    artifact.tailored_resume_id = None
    artifact.reused_from_artifact_id = source_artifact_id
    artifact.reuse_score = 88.0
    artifact.format = "latex"
    artifact.filename = "resume-intuit-2026-04-18.tex"
    artifact.content = "\\documentclass{article}\n"
    artifact.generated_at = datetime(2026, 4, 18, tzinfo=timezone.utc)
    artifact.created_at = datetime(2026, 4, 18, tzinfo=timezone.utc)
    artifact.updated_at = datetime(2026, 4, 18, tzinfo=timezone.utc)
    source_job = MagicMock()
    source_job.title = "Full-Stack Engineer"
    source_job.company_name = "Acme"

    from app.schemas.jobs import ResumeArtifactResponse

    async def _fake_build(_db, *, user_id, job_id, artifact):
        return ResumeArtifactResponse(
            id=str(artifact.id),
            job_id=str(job_id),
            tailored_resume_id=None,
            reused_from_artifact_id=str(source_artifact_id),
            reuse_score=artifact.reuse_score,
            format=artifact.format,
            filename=artifact.filename,
            content=artifact.content,
            generated_at=artifact.generated_at.isoformat(),
            created_at=artifact.created_at.isoformat(),
            updated_at=artifact.updated_at.isoformat(),
        )

    with patch(
        "app.routers.jobs.reuse_resume_artifact_for_job",
        new_callable=AsyncMock,
    ) as mock_reuse, patch(
        "app.routers.jobs._build_artifact_response",
        side_effect=_fake_build,
    ):
        mock_reuse.return_value = (artifact, source_job)
        resp = await client.post(
            f"/api/jobs/{job_id}/resume-artifact/reuse/{source_artifact_id}"
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["reused"] is True
    assert data["reused_from_artifact_id"] == str(source_artifact_id)
    assert data["source_company_name"] == "Acme"


async def test_get_resume_artifact(client, mock_user_id):
    """GET /api/jobs/{id}/resume-artifact returns the saved artifact."""
    job_id = uuid.uuid4()
    artifact = MagicMock()
    artifact.id = uuid.uuid4()
    artifact.job_id = job_id
    artifact.tailored_resume_id = uuid.uuid4()
    artifact.format = "latex"
    artifact.filename = "resume-techcorp-2026-04-18.tex"
    artifact.content = "\\documentclass{article}\n"
    artifact.generated_at = datetime(2026, 4, 18, tzinfo=timezone.utc)
    artifact.created_at = datetime(2026, 4, 18, tzinfo=timezone.utc)
    artifact.updated_at = datetime(2026, 4, 18, tzinfo=timezone.utc)
    artifact.rewrite_decisions = {}

    from app.schemas.jobs import ResumeArtifactResponse

    async def _fake_build(_db, *, user_id, job_id, artifact):
        return ResumeArtifactResponse(
            id=str(artifact.id),
            job_id=job_id,
            tailored_resume_id=str(artifact.tailored_resume_id) if artifact.tailored_resume_id else None,
            format=artifact.format,
            filename=artifact.filename,
            content=artifact.content,
            generated_at=artifact.generated_at.isoformat(),
            created_at=artifact.created_at.isoformat(),
            updated_at=artifact.updated_at.isoformat(),
        )

    with patch("app.routers.jobs.get_resume_artifact_for_job", new_callable=AsyncMock) as mock_get, \
         patch("app.routers.jobs._build_artifact_response", side_effect=_fake_build):
        mock_get.return_value = artifact
        resp = await client.get(f"/api/jobs/{job_id}/resume-artifact")

    assert resp.status_code == 200
    assert resp.json()["job_id"] == str(job_id)


async def test_download_resume_artifact_pdf(client, mock_user_id):
    """GET /api/jobs/{id}/resume-artifact/pdf returns a PDF download."""
    job_id = uuid.uuid4()
    artifact = MagicMock()
    artifact.filename = "resume-techcorp-2026-04-18.tex"
    artifact.content = "\\documentclass{article}\n"

    with patch("app.routers.jobs.get_resume_artifact_for_job", new_callable=AsyncMock) as mock_get:
        with patch("app.routers.jobs.render_resume_artifact_pdf") as mock_render:
            mock_get.return_value = artifact
            mock_render.return_value = b"%PDF-test"
            resp = await client.get(f"/api/jobs/{job_id}/resume-artifact/pdf")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    assert "resume-techcorp-2026-04-18.pdf" in resp.headers["content-disposition"]
    assert resp.content == b"%PDF-test"


async def test_preview_resume_artifact_redline_pdf(client, mock_user_id):
    """GET /api/jobs/{id}/resume-artifact/redline-pdf returns inline review PDF."""
    job_id = uuid.uuid4()
    artifact = MagicMock()
    artifact.id = uuid.uuid4()
    artifact.job_id = job_id
    artifact.tailored_resume_id = uuid.uuid4()
    artifact.format = "latex"
    artifact.filename = "resume-techcorp-2026-04-18.tex"
    artifact.content = "\\documentclass{article}\n"
    artifact.generated_at = datetime(2026, 4, 18, tzinfo=timezone.utc)
    artifact.created_at = datetime(2026, 4, 18, tzinfo=timezone.utc)
    artifact.updated_at = datetime(2026, 4, 18, tzinfo=timezone.utc)
    artifact.rewrite_decisions = {}

    from app.schemas.jobs import ResumeArtifactResponse, ResumeBulletRewritePreview

    async def _fake_build(_db, *, user_id, job_id, artifact):
        return ResumeArtifactResponse(
            id=str(artifact.id),
            job_id=str(job_id),
            tailored_resume_id=str(artifact.tailored_resume_id),
            format=artifact.format,
            filename=artifact.filename,
            content=artifact.content,
            generated_at=artifact.generated_at.isoformat(),
            created_at=artifact.created_at.isoformat(),
            updated_at=artifact.updated_at.isoformat(),
            rewrite_decisions={"rw-1": "accepted"},
            rewrite_previews=[
                ResumeBulletRewritePreview(
                    id="rw-1",
                    section="experience",
                    experience_index=0,
                    original="Built APIs.",
                    rewritten="Built RESTful APIs.",
                    decision="accepted",
                )
            ],
        )

    with patch(
        "app.routers.jobs.get_resume_artifact_for_job",
        new_callable=AsyncMock,
    ) as mock_get, patch(
        "app.routers.jobs._build_artifact_response",
        side_effect=_fake_build,
    ), patch("app.routers.jobs.render_resume_artifact_redline_pdf") as mock_render:
        mock_get.return_value = artifact
        mock_render.return_value = b"%PDF-redline"
        resp = await client.get(f"/api/jobs/{job_id}/resume-artifact/redline-pdf")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    assert "inline" in resp.headers["content-disposition"]
    assert "resume-techcorp-2026-04-18-redline.pdf" in resp.headers[
        "content-disposition"
    ]
    assert resp.content == b"%PDF-redline"
    mock_render.assert_called_once()


async def test_get_research_snapshot_returns_payload(client, mock_user_id):
    """GET /api/jobs/{id}/research-snapshot returns the persisted snapshot."""
    job_id = uuid.uuid4()
    snapshot_id = uuid.uuid4()
    fake_snapshot = MagicMock()
    fake_snapshot.id = snapshot_id
    fake_snapshot.job_id = job_id
    fake_snapshot.company_name = "Acme"
    fake_snapshot.target_count_per_bucket = 4
    fake_snapshot.recruiters = [{"id": str(uuid.uuid4()), "full_name": "R"}]
    fake_snapshot.hiring_managers = []
    fake_snapshot.peers = []
    fake_snapshot.your_connections = []
    fake_snapshot.recruiter_count = 1
    fake_snapshot.manager_count = 0
    fake_snapshot.peer_count = 0
    fake_snapshot.warm_path_count = 0
    fake_snapshot.verified_count = 0
    fake_snapshot.total_candidates = 1
    fake_snapshot.errors = None
    fake_snapshot.created_at = datetime(2026, 4, 18, tzinfo=timezone.utc)
    fake_snapshot.updated_at = datetime(2026, 4, 18, tzinfo=timezone.utc)

    with patch(
        "app.services.job_research_snapshot_service.get_job_research_snapshot",
        new_callable=AsyncMock,
    ) as mock_get:
        mock_get.return_value = fake_snapshot
        resp = await client.get(f"/api/jobs/{job_id}/research-snapshot")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(snapshot_id)
    assert data["total_candidates"] == 1
    assert data["recruiters"][0]["full_name"] == "R"


async def test_clear_research_snapshot(client, mock_user_id):
    """DELETE /api/jobs/{id}/research-snapshot reports deletion outcome."""
    job_id = uuid.uuid4()
    with patch(
        "app.services.job_research_snapshot_service.delete_job_research_snapshot",
        new_callable=AsyncMock,
    ) as mock_del:
        mock_del.return_value = True
        resp = await client.delete(f"/api/jobs/{job_id}/research-snapshot")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "deleted": True}


async def test_discover_jobs_startup_mode(client):
    """POST /api/jobs/discover forwards startup mode to the service."""
    with patch("app.routers.jobs.discover_jobs", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = 4
        resp = await client.post("/api/jobs/discover", json={"mode": "startup"})

    assert resp.status_code == 200
    assert resp.json() == {"new_jobs_found": 4}
    mock_discover.assert_awaited_once()
    call_kwargs = mock_discover.call_args.kwargs
    assert call_kwargs["mode"] == "startup"


async def test_get_job_not_found(client, mock_user_id):
    """GET /api/jobs/{id} returns 404 for missing job."""
    with patch("app.routers.jobs.get_job", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        resp = await client.get(f"/api/jobs/{uuid.uuid4()}")

    assert resp.status_code == 404


async def test_update_job_stage(client, mock_user_id):
    """PUT /api/jobs/{id}/stage updates kanban stage."""
    job = _mock_job(mock_user_id, stage="applied")

    with patch("app.routers.jobs.update_job_stage", new_callable=AsyncMock) as mock_update:
        mock_update.return_value = job
        resp = await client.put(
            f"/api/jobs/{uuid.uuid4()}/stage",
            json={"stage": "applied"},
        )

    assert resp.status_code == 200
    assert resp.json()["stage"] == "applied"


async def test_update_job_stage_not_found(client, mock_user_id):
    """PUT /api/jobs/{id}/stage returns 404 for wrong user/job."""
    with patch("app.routers.jobs.update_job_stage", new_callable=AsyncMock) as mock_update:
        mock_update.side_effect = ValueError("Job not found.")
        resp = await client.put(
            f"/api/jobs/{uuid.uuid4()}/stage",
            json={"stage": "applied"},
        )

    assert resp.status_code == 404
