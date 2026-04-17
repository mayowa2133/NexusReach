"""Tests for People Finder utility functions — Phase 3.

Tests pure functions: _classify_person from people_service,
_split_name from email_finder_service.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.people_service import (
    _append_bucket,
    _backfill_top_candidates,
    _backfill_linkedin_profiles,
    _broaden_peer_titles_for_retry,
    _candidate_geo_signal_match,
    _candidate_bucket_assignment_rank,
    _candidate_matches_company,
    _merge_company_public_identity_slugs,
    _saved_theorg_slug_candidates,
    _classify_employment_status,
    _classify_org_level,
    _classify_person,
    _choose_linkedin_backfill_match,
    _expand_peer_candidates,
    _compute_match_metadata,
    _finalize_bucketed,
    _linkedin_backfill_name_variants,
    _name_match_score,
    _initial_manager_titles,
    _manager_geo_recovery_titles,
    _manager_context_search_titles,
    _prioritize_titles_for_search,
    _prepare_candidates,
    _recover_candidate_titles,
    _recover_title_from_snippet,
    _score_contextual_candidates_fast,
    _sanitize_search_keywords,
    _should_run_manager_geo_recovery,
    _store_person,
    get_or_create_company,
)
from app.services.email_finder_service import _split_name
from app.utils.company_identity import effective_public_identity_slugs, matches_public_company_identity
from app.utils.job_context import JobContext


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        value = self._value

        class _Scalars:
            def __init__(self, raw):
                self._raw = raw

            def all(self):
                if isinstance(self._raw, list):
                    return self._raw
                if self._raw is None:
                    return []
                return [self._raw]

            def first(self):
                if isinstance(self._raw, list):
                    return self._raw[0] if self._raw else None
                return self._raw

        return _Scalars(value)


class TestClassifyPerson:
    def test_recruiter(self):
        assert _classify_person("Technical Recruiter") == "recruiter"
        assert _classify_person("Talent Acquisition Specialist") == "recruiter"
        assert _classify_person("Hiring Coordinator") == "recruiter"
        assert _classify_person("People Operations Manager") != "recruiter"

    def test_hiring_manager(self):
        assert _classify_person("Engineering Manager") == "hiring_manager"
        assert _classify_person("Team Lead") == "hiring_manager"
        assert _classify_person("Director of Engineering") == "hiring_manager"
        assert _classify_person("VP Engineering") == "hiring_manager"

    def test_peer(self):
        assert _classify_person("Software Engineer") == "peer"
        assert _classify_person("Frontend Developer") == "peer"
        assert _classify_person("Data Analyst") == "peer"
        assert _classify_person("Staff Software Engineer") == "peer"
        assert _classify_person("Principal Engineer") == "peer"

    def test_empty_title(self):
        assert _classify_person("") == "peer"
        assert _classify_person(None) == "peer"


class TestSplitName:
    def test_two_parts(self):
        first, last = _split_name("John Doe")
        assert first == "John"
        assert last == "Doe"

    def test_three_parts(self):
        first, last = _split_name("John Michael Doe")
        assert first == "John"
        assert last == "Michael Doe"

    def test_single_name(self):
        first, last = _split_name("Madonna")
        assert first == "Madonna"
        assert last == ""

    def test_empty_string(self):
        first, last = _split_name("")
        assert first == ""
        assert last == ""

    def test_none(self):
        first, last = _split_name(None)
        assert first == ""
        assert last == ""


class TestEmploymentAndRanking:
    @pytest.mark.asyncio
    async def test_get_or_create_company_reuses_normalized_company_name(self):
        existing = SimpleNamespace(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            name="Zip",
            normalized_name="zip",
            domain=None,
            domain_trusted=False,
            public_identity_slugs=[],
            identity_hints={},
            email_pattern=None,
            email_pattern_confidence=None,
        )
        db = MagicMock()
        db.execute = AsyncMock(return_value=_ScalarResult(existing))

        with patch(
            "app.services.people_service.apollo_client.search_company",
            new_callable=AsyncMock,
            return_value={"name": "Zip Co", "domain": "zip.co"},
        ):
            company = await get_or_create_company(db, existing.user_id, "zip")

        assert company is existing
        assert company.name == "Zip"
        assert company.domain is None
        assert company.domain_trusted is False
        assert "zip" in company.public_identity_slugs
        assert "ziphq" in company.public_identity_slugs

    def test_classify_employment_status_former(self):
        status = _classify_employment_status(
            {
                "title": "Former Engineering Manager",
                "snippet": "Former engineering manager at Two Sigma",
                "source": "brave_search",
            },
            "Two Sigma",
        )

        assert status == "former"

    def test_candidate_matches_company_rejects_other_org_chart(self):
        assert _candidate_matches_company(
            {
                "title": "Technical Recruiter",
                "snippet": "Worked in engineering talent acquisition at Two Sigma.",
                "source": "brave_public_web",
                "profile_data": {
                    "public_url": "https://theorg.com/org/jane-street-capital/org-chart/someone"
                },
            },
            "Two Sigma",
        ) is False

    def test_candidate_matches_company_rejects_ziprecruiter_for_zip(self):
        assert _candidate_matches_company(
            {
                "title": "Technical Recruiter",
                "snippet": "Technical recruiter at ZipRecruiter focused on engineering hiring.",
                "source": "brave_search",
            },
            "Zip",
        ) is False

    def test_candidate_matches_company_accepts_theorg_slug_for_ambiguous_company(self):
        assert _candidate_matches_company(
            {
                "title": "Andre Nguyen - Sr Technical Recruiter",
                "snippet": "Currently serving as a Sr Technical Recruiter at Zip.",
                "source": "brave_public_web",
                "profile_data": {
                    "public_url": "https://theorg.com/org/ziphq/org-chart/andre-nguyen",
                    "public_identity_slug": "ziphq",
                },
            },
            "Zip",
            ["zip", "ziphq"],
        ) is True

    def test_effective_public_identity_slugs_rejects_fortune_brands_pollution(self):
        slugs = effective_public_identity_slugs(
            "Fortune",
            ["fortune", "fortune-magazine", "fortune-brands-home-security"],
            identity_hints={
                "normalized_slug": "fortune",
                "ats_slug": "fortune",
                "linkedin_company_slug": "fortune",
                "careers_host": "fortune.wd108.myworkdayjobs.com",
            },
        )

        assert "fortune" in slugs
        assert "fortune-magazine" in slugs
        assert "fortune-brands-home-security" not in slugs
        assert "myworkdayjobs" not in slugs

    def test_matches_public_company_identity_accepts_fortune_magazine_from_official_alias(self):
        assert matches_public_company_identity(
            "https://theorg.com/org/fortune-magazine/org-chart/diane-brady",
            "Fortune Media",
            ["fortune", "fortune-media"],
        ) is True

    def test_matches_public_company_identity_rejects_fortune_brands_from_official_alias(self):
        assert matches_public_company_identity(
            "https://theorg.com/org/fortune-brands-home-security/org-chart/ashley-molyneux",
            "Fortune Media",
            ["fortune", "fortune-media"],
        ) is False

    def test_merge_company_public_identity_slugs_does_not_promote_candidate_slug_to_preferred(self):
        company = SimpleNamespace(
            public_identity_slugs=["fortune", "fortune-media"],
            identity_hints={},
        )

        _merge_company_public_identity_slugs(
            company,
            "Fortune Media",
            ["fortune-magazine"],
            preferred_slug="fortune-magazine",
            preferred_status="candidate",
        )

        assert company.identity_hints.get("theorg", {}).get("slug_status", {}) == {}
        assert "preferred_org_slug" not in company.identity_hints["theorg"]

    def test_merge_company_public_identity_slugs_ignores_incompatible_candidate_slug_status(self):
        company = SimpleNamespace(
            public_identity_slugs=["fortune", "fortune-media"],
            identity_hints={},
        )

        _merge_company_public_identity_slugs(
            company,
            "Fortune Media",
            ["infosys"],
            preferred_slug="infosys",
            preferred_status="candidate",
        )

        assert "infosys" not in company.public_identity_slugs
        assert company.identity_hints.get("theorg", {}).get("slug_status", {}) == {}

    @pytest.mark.asyncio
    async def test_saved_theorg_slug_candidates_filters_incompatible_saved_public_urls(self):
        company = SimpleNamespace(
            id=uuid.uuid4(),
            name="Fortune Media",
            public_identity_slugs=["fortune", "fortune-media", "fortune-magazine"],
            identity_hints={"ats_slug": "fortune", "normalized_slug": "fortune-media"},
        )
        people = [
            SimpleNamespace(
                profile_data={
                    "public_url": "https://theorg.com/org/fortune-magazine/org-chart/diane-brady",
                    "public_identity_slug": "fortune-magazine",
                }
            ),
            SimpleNamespace(
                profile_data={
                    "public_url": "https://theorg.com/org/fortune-brands-home-security/org-chart/ashley-molyneux",
                    "public_identity_slug": "fortune-brands-home-security",
                }
            ),
        ]
        db = MagicMock()
        db.execute = AsyncMock(return_value=_ScalarResult(people))

        candidates = await _saved_theorg_slug_candidates(
            db,
            user_id=uuid.uuid4(),
            company=company,
        )

        assert candidates == ["fortune-magazine"]

    def test_candidate_matches_company_rejects_directory_style_public_result(self):
        assert _candidate_matches_company(
            {
                "title": "Courtney Cronin's Email & Phone",
                "snippet": "Staff directory and contact information for Zip.",
                "source": "brave_public_web",
                "profile_data": {
                    "public_url": "https://www.contactout.com/courtney-cronin",
                },
            },
            "Zip",
            ["zip", "ziphq"],
        ) is False

    def test_classify_employment_status_marks_theorg_slug_match_current(self):
        status = _classify_employment_status(
            {
                "title": "Sophia Feng - Software Engineer",
                "snippet": "Software Engineer, Payments at Zip.",
                "source": "brave_public_web",
                "profile_data": {
                    "public_url": "https://theorg.com/org/ziphq/org-chart/sophia-feng",
                    "public_identity_slug": "ziphq",
                },
            },
            "Zip",
            ["zip", "ziphq"],
        )

        assert status == "current"

    def test_classify_employment_status_marks_public_linkedin_about_lead_signal_current(self):
        status = _classify_employment_status(
            {
                "title": "Talent Acquisition Lead, Canada",
                "snippet": (
                    "Reiss Simmons Intuit Canada About I lead the Talent Acquisition team at "
                    "Intuit responsible for hiring in Canada & the US."
                ),
                "source": "tavily_public_web",
                "linkedin_url": "https://ca.linkedin.com/in/reisssimmons",
                "profile_data": {
                    "public_url": "https://ca.linkedin.com/in/reisssimmons",
                    "linkedin_result_title": "Reiss Simmons - Intuit | LinkedIn",
                    "public_snippet": (
                        "Reiss Simmons Intuit Canada About I lead the Talent Acquisition team at "
                        "Intuit responsible for hiring in Canada & the US."
                    ),
                },
            },
            "Intuit",
        )

        assert status == "current"

    def test_recover_title_from_snippet_promotes_linkedin_about_recruiter_lead(self):
        recovered = _recover_title_from_snippet(
            {
                "full_name": "Reiss Simmons",
                "title": "Intuit",
                "snippet": (
                    "Reiss Simmons Intuit Canada About I lead the Talent Acquisition team at "
                    "Intuit responsible for hiring in Canada & the US."
                ),
                "linkedin_url": "https://ca.linkedin.com/in/reisssimmons",
                "profile_data": {
                    "public_url": "https://ca.linkedin.com/in/reisssimmons",
                    "linkedin_result_title": "Reiss Simmons - Intuit | LinkedIn",
                    "public_snippet": (
                        "Reiss Simmons Intuit Canada About I lead the Talent Acquisition team at "
                        "Intuit responsible for hiring in Canada & the US."
                    ),
                },
            },
            company_name="Intuit",
        )

        assert recovered == ("Talent Acquisition Lead, Canada", 74)

    def test_classify_org_level(self):
        assert _classify_org_level("Software Engineer") == "ic"
        assert _classify_org_level("Engineering Manager") == "manager"
        assert _classify_org_level("Managing Director") == "director_plus"

    def test_prioritize_titles_for_search_prefers_early_career_recruiters(self):
        context = JobContext(
            department="engineering",
            team_keywords=[],
            domain_keywords=[],
            seniority="junior",
            early_career=True,
        )
        titles = [
            "Engineering Recruiter",
            "Technical Recruiter",
            "Campus Recruiter",
            "University Recruiter",
            "Talent Acquisition",
        ]

        prioritized = _prioritize_titles_for_search(
            titles,
            bucket="recruiters",
            context=context,
        )

        assert prioritized[:3] == [
            "Campus Recruiter",
            "University Recruiter",
            "Engineering Recruiter",
        ]

    def test_broaden_peer_titles_for_ml_roles_adds_general_engineering_variants(self):
        context = JobContext(
            department="information_technology",
            team_keywords=["ml", "security"],
            domain_keywords=[],
            seniority="mid",
            early_career=False,
            peer_titles=[
                "Machine Learning Engineer",
                "Machine Learning Developer",
                "Machine Learning Software Engineer",
                "Ml Engineer",
                "Ml Software Engineer",
            ],
        )

        titles = _broaden_peer_titles_for_retry(context)

        assert titles[:4] == [
            "Machine Learning Engineer",
            "Software Engineer",
            "Applied Scientist",
            "Research Engineer",
        ]
        assert "Security Engineer" not in titles

    def test_broaden_peer_titles_for_junior_backend_roles_prefers_entry_level_variants(self):
        context = JobContext(
            department="engineering",
            team_keywords=["backend", "platform"],
            domain_keywords=[],
            seniority="junior",
            early_career=True,
            peer_titles=["Backend Engineer", "Software Engineer"],
        )

        titles = _broaden_peer_titles_for_retry(context)

        assert titles[:4] == [
            "Junior Backend Engineer",
            "Associate Backend Engineer",
            "Entry Level Backend Engineer",
            "Backend Engineer I",
        ]
        assert "Platform Engineer" in titles
        assert "Infrastructure Engineer" in titles

    @pytest.mark.asyncio
    async def test_expand_peer_candidates_retries_with_broader_titles_and_no_team_keywords(self):
        context = JobContext(
            department="data_science",
            team_keywords=["ml", "security"],
            domain_keywords=[],
            seniority="mid",
            early_career=False,
            peer_titles=["Machine Learning Engineer"],
            apollo_departments=["engineering_technical", "data"],
        )

        with patch(
            "app.services.people_service._search_candidates",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_search.return_value = [
                {
                    "full_name": "Peer Pat",
                    "title": "Software Engineer",
                    "source": "brave_search",
                }
            ]
            candidates = await _expand_peer_candidates(
                "Microsoft",
                [],
                context=context,
                public_identity_terms=["microsoft"],
                limit=10,
                min_results=2,
            )

        _, kwargs = mock_search.await_args
        assert kwargs["team_keywords"] is None
        assert kwargs["titles"][:3] == [
            "Machine Learning Engineer",
            "Software Engineer",
            "Applied Scientist",
        ]
        assert candidates[0]["full_name"] == "Peer Pat"

    def test_prioritize_titles_for_search_prefers_generic_engineering_managers_for_early_career(self):
        context = JobContext(
            department="engineering",
            team_keywords=[],
            domain_keywords=[],
            seniority="junior",
            early_career=True,
        )
        titles = [
            "Software Engineering Lead",
            "Software Engineering Manager",
            "Software Engineer Team Lead",
            "Engineering Manager",
        ]

        prioritized = _prioritize_titles_for_search(
            titles,
            bucket="hiring_managers",
            context=context,
        )

        assert prioritized[:2] == [
            "Engineering Manager",
            "Software Engineering Manager",
        ]

    def test_prepare_candidates_prefers_current_manager_before_director_fallback(self):
        context = JobContext(
            department="engineering",
            team_keywords=["backend"],
            domain_keywords=[],
            seniority="mid",
        )
        candidates = [
            {
                "full_name": "Director Dana",
                "title": "Director of Engineering",
                "snippet": "Currently at Two Sigma",
                "source": "brave_search",
            },
            {
                "full_name": "Manager Morgan",
                "title": "Engineering Manager",
                "snippet": "Currently at Two Sigma",
                "source": "brave_search",
            },
            {
                "full_name": "Ambiguous Avery",
                "title": "Engineering Manager",
                "snippet": "Worked on backend systems at Two Sigma",
                "source": "brave_search",
            },
        ]

        results = _prepare_candidates(
            candidates,
            company_name="Two Sigma",
            bucket="hiring_managers",
            context=context,
            limit=3,
        )

        assert [candidate["full_name"] for candidate in results] == [
            "Manager Morgan",
            "Ambiguous Avery",
            "Director Dana",
        ]

    def test_finalize_bucketed_dedupes_people_across_buckets_by_best_fit(self):
        shared_id = uuid.uuid4()
        hiring_manager_copy = SimpleNamespace(
            id=shared_id,
            full_name="Priya Principal",
            title="Principal Engineer",
            linkedin_url=None,
            current_company_verified=True,
            match_quality="next_best",
            fallback_reason="Senior IC fallback at the target company.",
            employment_status="current",
            org_level="ic",
            person_type="hiring_manager",
        )
        peer_copy = SimpleNamespace(
            id=shared_id,
            full_name="Priya Principal",
            title="Principal Engineer",
            linkedin_url="https://linkedin.com/in/priya-principal",
            current_company_verified=True,
            match_quality="direct",
            fallback_reason=None,
            employment_status="current",
            org_level="ic",
            person_type="peer",
        )

        finalized = _finalize_bucketed(
            {
                "recruiters": [],
                "hiring_managers": [hiring_manager_copy],
                "peers": [peer_copy],
            },
            target_count_per_bucket=3,
        )

        assert finalized["hiring_managers"] == []
        assert [person.full_name for person in finalized["peers"]] == ["Priya Principal"]

    def test_finalize_bucketed_prefers_linkedin_when_match_quality_is_tied(self):
        people = [
            SimpleNamespace(
                id=uuid.uuid4(),
                full_name="Alex Org",
                title="Software Engineer",
                linkedin_url=None,
                current_company_verified=True,
                match_quality="adjacent",
                fallback_reason=None,
                employment_status="current",
                org_level="ic",
                person_type="peer",
            ),
            SimpleNamespace(
                id=uuid.uuid4(),
                full_name="Alex LinkedIn",
                title="Software Engineer",
                linkedin_url="https://linkedin.com/in/alexlinkedin",
                current_company_verified=True,
                match_quality="adjacent",
                fallback_reason=None,
                employment_status="current",
                org_level="ic",
                person_type="peer",
            ),
        ]

        finalized = _finalize_bucketed(
            {
                "recruiters": [],
                "hiring_managers": [],
                "peers": people,
            },
            target_count_per_bucket=3,
        )

        assert [person.full_name for person in finalized["peers"][:2]] == [
            "Alex LinkedIn",
            "Alex Org",
        ]

    def test_finalize_bucketed_prefers_local_software_peer_over_remote_ml_peer(self):
        people = [
            SimpleNamespace(
                id=uuid.uuid4(),
                full_name="Remote ML",
                title="Senior Machine Learning Engineer",
                linkedin_url=None,
                current_company_verified=True,
                match_quality="direct",
                fallback_reason=None,
                employment_status="current",
                org_level="ic",
                person_type="peer",
                usefulness_score=61,
                warm_path_type=None,
                profile_data={"location": "Mountain View, California"},
            ),
            SimpleNamespace(
                id=uuid.uuid4(),
                full_name="Toronto Fullstack",
                title="Full Stack Developer @ Intuit",
                linkedin_url="https://ca.linkedin.com/in/toronto-fullstack",
                current_company_verified=None,
                match_quality="adjacent",
                fallback_reason=None,
                employment_status="current",
                org_level="ic",
                person_type="peer",
                usefulness_score=64,
                warm_path_type=None,
                profile_data={"location": "Toronto, Ontario, Canada"},
            ),
        ]

        finalized = _finalize_bucketed(
            {
                "recruiters": [],
                "hiring_managers": [],
                "peers": people,
            },
            target_count_per_bucket=3,
        )

        assert [person.full_name for person in finalized["peers"][:2]] == [
            "Toronto Fullstack",
            "Remote ML",
        ]

    def test_finalize_bucketed_prefers_recruiter_lead_scope_over_local_ic_recruiter(self):
        people = [
            SimpleNamespace(
                id=uuid.uuid4(),
                full_name="Greeshma Lal",
                title="Talent Acquisition",
                linkedin_url="https://ca.linkedin.com/in/greeshma-lal-879551139",
                current_company_verified=True,
                match_quality="adjacent",
                fallback_reason=None,
                employment_status="current",
                org_level="ic",
                person_type="recruiter",
                usefulness_score=69,
                warm_path_type=None,
                profile_data={"location": "Toronto, Ontario, Canada"},
            ),
            SimpleNamespace(
                id=uuid.uuid4(),
                full_name="Reiss Simmons",
                title="Talent Acquisition Lead, Canada",
                linkedin_url="https://ca.linkedin.com/in/reisssimmons",
                current_company_verified=None,
                match_quality="adjacent",
                fallback_reason=None,
                employment_status="current",
                org_level="manager",
                person_type="recruiter",
                usefulness_score=68,
                warm_path_type=None,
                profile_data={
                    "location": "Canada",
                    "public_snippet": "I lead the Talent Acquisition team at Intuit responsible for hiring in Canada & the US.",
                },
            ),
        ]

        finalized = _finalize_bucketed(
            {
                "recruiters": people,
                "hiring_managers": [],
                "peers": [],
            },
            target_count_per_bucket=3,
        )

        assert [person.full_name for person in finalized["recruiters"][:2]] == [
            "Reiss Simmons",
            "Greeshma Lal",
        ]

    def test_finalize_bucketed_prefers_explicit_engineering_manager_over_generic_engineering_leader(self):
        people = [
            SimpleNamespace(
                id=uuid.uuid4(),
                full_name="Rex Su",
                title="Engineering Leader | Intuit",
                linkedin_url="https://ca.linkedin.com/in/rexsu",
                current_company_verified=True,
                match_quality="direct",
                fallback_reason=None,
                employment_status="current",
                org_level="manager",
                person_type="hiring_manager",
                usefulness_score=67,
                warm_path_type=None,
                profile_data={"location": "Toronto, Ontario, Canada"},
            ),
            SimpleNamespace(
                id=uuid.uuid4(),
                full_name="Hugo Godoy",
                title="Software Engineering Manager",
                linkedin_url="https://ca.linkedin.com/in/godoyhugopereira",
                current_company_verified=True,
                match_quality="direct",
                fallback_reason=None,
                employment_status="current",
                org_level="manager",
                person_type="hiring_manager",
                usefulness_score=67,
                warm_path_type=None,
                profile_data={"location": "Toronto, Ontario, Canada"},
            ),
        ]

        finalized = _finalize_bucketed(
            {
                "recruiters": [],
                "hiring_managers": people,
                "peers": [],
            },
            target_count_per_bucket=3,
        )

        assert [person.full_name for person in finalized["hiring_managers"][:2]] == [
            "Hugo Godoy",
            "Rex Su",
        ]

    def test_prepare_candidates_excludes_generic_manager_without_engineering_context(self):
        context = JobContext(
            department="engineering",
            team_keywords=["fullstack"],
            domain_keywords=["qa"],
            seniority="junior",
            early_career=False,
        )
        results = _prepare_candidates(
            [
                {
                    "full_name": "John Smith",
                    "title": "Manager",
                    "snippet": "John Smith Intuit Toronto, Ontario, Canada",
                    "source": "tavily_public_web",
                    "linkedin_url": "https://ca.linkedin.com/in/john-smith-b58a26234",
                    "profile_data": {
                        "public_url": "https://ca.linkedin.com/in/john-smith-b58a26234",
                        "public_snippet": "John Smith Intuit Toronto, Ontario, Canada",
                        "location": "Toronto, Ontario, Canada",
                    },
                },
                {
                    "full_name": "Hugo Godoy",
                    "title": "Software Engineering Manager",
                    "snippet": "Software Engineering Manager at Intuit in Toronto.",
                    "source": "tavily_public_web",
                    "linkedin_url": "https://ca.linkedin.com/in/godoyhugopereira",
                    "profile_data": {
                        "public_url": "https://ca.linkedin.com/in/godoyhugopereira",
                        "public_snippet": "Software Engineering Manager at Intuit in Toronto.",
                        "location": "Toronto, Ontario, Canada",
                    },
                },
            ],
            company_name="Intuit",
            public_identity_slugs=["intuit"],
            bucket="hiring_managers",
            context=context,
            limit=5,
        )

        assert [candidate["full_name"] for candidate in results] == ["Hugo Godoy"]

    def test_append_bucket_does_not_drop_multiple_unsaved_people_with_none_ids(self):
        bucketed = {"recruiters": [], "hiring_managers": [], "peers": []}
        seen = {"recruiters": set(), "hiring_managers": set(), "peers": set()}
        context = JobContext(
            department="engineering",
            team_keywords=["fullstack"],
            domain_keywords=[],
            seniority="junior",
            early_career=False,
        )

        first = SimpleNamespace(
            id=None,
            full_name="Jacky Zhang",
            title="iOS/Full stack software developer",
            linkedin_url="https://ca.linkedin.com/in/jackydocode/es",
            profile_data={"public_url": "https://ca.linkedin.com/in/jackydocode/es"},
            person_type="peer",
        )
        second = SimpleNamespace(
            id=None,
            full_name="Navneet Kahlon",
            title="Full Stack Developer @ Intuit",
            linkedin_url="https://ca.linkedin.com/in/navneetskahlon",
            profile_data={"public_url": "https://ca.linkedin.com/in/navneetskahlon"},
            person_type="peer",
        )

        _append_bucket(
            bucketed,
            seen,
            first,
            {"full_name": "Jacky Zhang", "title": first.title, "linkedin_url": first.linkedin_url},
            explicit_type="peer",
            context=context,
            company_name="Intuit",
            public_identity_slugs=["intuit"],
        )
        _append_bucket(
            bucketed,
            seen,
            second,
            {"full_name": "Navneet Kahlon", "title": second.title, "linkedin_url": second.linkedin_url},
            explicit_type="peer",
            context=context,
            company_name="Intuit",
            public_identity_slugs=["intuit"],
        )

        assert [person.full_name for person in bucketed["peers"]] == [
            "Jacky Zhang",
            "Navneet Kahlon",
        ]

    def test_prepare_candidates_allows_senior_ic_fallback_for_hiring_managers(self):
        context = JobContext(
            department="engineering",
            team_keywords=["ml"],
            domain_keywords=[],
            seniority="staff",
        )
        results = _prepare_candidates(
            [
                {
                    "full_name": "Priya Principal",
                    "title": "Principal Engineer",
                    "snippet": "Currently at xAI working on model training.",
                    "source": "brave_search",
                }
            ],
            company_name="xAI",
            bucket="hiring_managers",
            context=context,
            limit=5,
        )

        assert results[0]["full_name"] == "Priya Principal"
        assert results[0]["_senior_ic_fallback"] is True

    def test_prepare_candidates_rejects_recruiter_with_company_only_title(self):
        context = JobContext(
            department="engineering",
            team_keywords=[],
            domain_keywords=[],
            seniority="junior",
            early_career=True,
        )
        candidates = [
            {
                "full_name": "Anthony Bihl",
                "title": "Trexquant Investment LP",
                "snippet": "Technical recruiter focused on engineering hiring at Trexquant Investment.",
                "source": "brave_search",
            },
            {
                "full_name": "Kanchan Kaur",
                "title": "Senior Manager - Talent Acquisition and Human Resources",
                "snippet": "Talent acquisition leader at Trexquant Investment.",
                "source": "brave_search",
            },
        ]

        results = _prepare_candidates(
            candidates,
            company_name="Trexquant Investment",
            bucket="recruiters",
            context=context,
            limit=5,
        )

        assert [candidate["full_name"] for candidate in results] == ["Kanchan Kaur"]

    def test_prepare_candidates_rejects_generic_people_leaders_from_recruiter_bucket(self):
        context = JobContext(
            department="engineering",
            team_keywords=[],
            domain_keywords=[],
            seniority="junior",
            early_career=True,
        )
        candidates = [
            {
                "full_name": "People Pat",
                "title": "VP, People Operations",
                "snippet": "People operations leader at Whatnot.",
                "source": "brave_public_web",
                "profile_data": {
                    "public_url": "https://theorg.com/org/whatnot/org-chart/pat",
                    "public_identity_slug": "whatnot",
                },
            }
        ]

        results = _prepare_candidates(
            candidates,
            company_name="Whatnot",
            bucket="recruiters",
            context=context,
            limit=5,
        )

        assert results == []

    def test_prepare_candidates_allows_public_linkedin_peers_with_current_company_and_local_geo(self):
        context = JobContext(
            department="engineering",
            team_keywords=["fullstack"],
            domain_keywords=[],
            seniority="junior",
            early_career=True,
            job_locations=["Toronto, Ontario, Canada"],
            job_geo_terms=["Toronto", "Greater Toronto Area", "Ontario", "Canada"],
        )
        results = _prepare_candidates(
            [
                {
                    "full_name": "Delna Bijo",
                    "title": "Software Engineer @ Intuit",
                    "snippet": "Software Engineer at Intuit in Toronto, Ontario, Canada. Currently building product experiences.",
                    "source": "tavily_public_web",
                    "linkedin_url": "https://ca.linkedin.com/in/delna-bijo",
                    "location": "Toronto, Ontario, Canada",
                    "profile_data": {
                        "public_url": "https://ca.linkedin.com/in/delna-bijo",
                        "linkedin_result_title": "Delna Bijo - Software Engineer @ Intuit",
                        "location": "Toronto, Ontario, Canada",
                    },
                }
            ],
            company_name="Intuit",
            public_identity_slugs=["intuit"],
            bucket="peers",
            context=context,
            limit=5,
        )

        assert [candidate["full_name"] for candidate in results] == ["Delna Bijo"]

    def test_prepare_candidates_prefers_local_software_peers_over_generic_nonlocal_engineers(self):
        context = JobContext(
            department="engineering",
            team_keywords=["fullstack"],
            domain_keywords=[],
            seniority="junior",
            early_career=True,
            job_locations=["Toronto, Ontario, Canada"],
            job_geo_terms=["Toronto", "Greater Toronto Area", "Ontario", "Canada"],
        )
        results = _prepare_candidates(
            [
                {
                    "full_name": "Mehdi Mohammadi",
                    "title": "Senior Machine Learning Engineer",
                    "snippet": "Current engineer at Intuit working on machine learning.",
                    "source": "brave_public_web",
                    "profile_data": {
                        "public_url": "https://theorg.com/org/intuit/org-chart/mehdi-mohammadi",
                        "public_identity_slug": "intuit",
                    },
                },
                {
                    "full_name": "Peter Smith",
                    "title": "Software Developer",
                    "snippet": "Software Developer at Intuit in Toronto, Ontario, Canada.",
                    "source": "tavily_public_web",
                    "linkedin_url": "https://ca.linkedin.com/in/peter-smith-8a402581",
                    "location": "Toronto, Ontario, Canada",
                    "profile_data": {
                        "public_url": "https://ca.linkedin.com/in/peter-smith-8a402581",
                        "linkedin_result_title": "Peter Smith - Software Developer at Intuit",
                        "location": "Toronto, Ontario, Canada",
                    },
                },
            ],
            company_name="Intuit",
            public_identity_slugs=["intuit"],
            bucket="peers",
            context=context,
            limit=5,
        )

        assert [candidate["full_name"] for candidate in results[:2]] == [
            "Peter Smith",
            "Mehdi Mohammadi",
        ]

    def test_compute_match_metadata_marks_weak_peer_title_next_best(self):
        match_quality, match_reason = _compute_match_metadata(
            {
                "title": "Whatnot",
                "snippet": "Software Engineer at Whatnot.",
                "_weak_title": True,
            },
            "peer",
            JobContext(
                department="engineering",
                team_keywords=[],
                domain_keywords=[],
                seniority="junior",
                early_career=True,
            ),
        )

        assert match_quality == "next_best"
        assert "title specificity is weak" in (match_reason or "").lower()

    def test_compute_match_metadata_marks_adjacent_manager(self):
        match_quality, match_reason = _compute_match_metadata(
            {
                "title": "Infrastructure Manager",
                "snippet": "Manager at xAI working on infrastructure systems.",
            },
            "hiring_manager",
            JobContext(
                department="engineering",
                team_keywords=["ml"],
                domain_keywords=[],
                seniority="staff",
            ),
        )

        assert match_quality == "adjacent"
        assert "adjacent engineering manager" in (match_reason or "").lower()

    @pytest.mark.asyncio
    async def test_recover_candidate_titles_recovers_from_snippet(self):
        company = SimpleNamespace(
            public_identity_slugs=["whatnot"],
            identity_hints={},
            name="Whatnot",
        )
        recovered = await _recover_candidate_titles(
            [
                {
                    "full_name": "Brandon Lee",
                    "title": "Whatnot",
                    "snippet": "Brandon Lee is a Software Engineer at Whatnot.",
                    "source": "brave_search",
                    "profile_data": {},
                }
            ],
            company=company,
            company_name="Whatnot",
        )

        assert recovered[0]["title"] == "Software Engineer"
        assert recovered[0]["profile_data"]["title_recovery_source"] == "snippet"
        assert recovered[0]["_weak_title"] is False

    @pytest.mark.asyncio
    async def test_recover_candidate_titles_recovers_from_theorg_and_updates_slug(self):
        company = SimpleNamespace(
            public_identity_slugs=["whatnot-inc"],
            identity_hints={},
            name="Whatnot",
        )
        page = {
            "url": "https://theorg.com/org/whatnot/org-chart/blake-morgan",
            "next_data": {
                "props": {
                    "pageProps": {
                        "initialPosition": {
                            "slug": "blake-morgan",
                            "fullName": "Blake Morgan",
                            "currentRole": "Engineering Manager",
                            "companyV2": {"name": "Whatnot", "slug": "whatnot"},
                            "teams": [{"slug": "engineering", "name": "Engineering"}],
                            "reports": [],
                        }
                    }
                }
            },
            "public_identity_hints": {"company_slug": "whatnot", "page_type": "org_chart_person"},
        }

        with patch("app.services.people_service.theorg_client.fetch_page", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = page
            recovered = await _recover_candidate_titles(
                [
                    {
                        "full_name": "Blake Morgan",
                        "title": "Whatnot",
                        "snippet": "Whatnot engineering leader.",
                        "source": "brave_public_web",
                        "profile_data": {
                            "public_url": "https://theorg.com/org/whatnot/org-chart/blake-morgan",
                            "public_identity_slug": "whatnot",
                            "public_page_type": "org_chart_person",
                        },
                    }
                ],
                company=company,
                company_name="Whatnot",
            )

        assert recovered[0]["title"] == "Engineering Manager"
        assert recovered[0]["profile_data"]["title_recovery_source"] == "theorg"
        assert recovered[0]["profile_data"]["public_identity_slug_resolution"] == "whatnot"
        assert company.identity_hints["theorg"]["preferred_org_slug"] == "whatnot"
        assert "whatnot" in company.public_identity_slugs

    @pytest.mark.asyncio
    async def test_recover_candidate_titles_rejects_incompatible_theorg_slug(self):
        company = SimpleNamespace(
            public_identity_slugs=["fortune", "fortune-media"],
            identity_hints={"ats_slug": "fortune", "normalized_slug": "fortune-media"},
            name="Fortune Media",
        )

        with patch("app.services.people_service.theorg_client.fetch_page", new_callable=AsyncMock) as mock_fetch:
            recovered = await _recover_candidate_titles(
                [
                    {
                        "full_name": "Wrong Person",
                        "title": "Fortune Media",
                        "snippet": "Engineering leader.",
                        "source": "brave_public_web",
                        "profile_data": {
                            "public_url": "https://theorg.com/org/infosys/org-chart/wrong-person",
                            "public_identity_slug": "infosys",
                            "public_page_type": "org_chart_person",
                        },
                    }
                ],
                company=company,
                company_name="Fortune Media",
            )

        mock_fetch.assert_not_awaited()
        assert recovered[0]["title"] == "Fortune Media"
        assert "infosys" not in getattr(company, "public_identity_slugs", [])

    def test_name_match_score_accepts_same_name_and_last_initial(self):
        assert _name_match_score("Derek S.", "Derek Smith") == 90
        assert _name_match_score("Lauren Tyson", "Lauren Tyson") == 100
        assert _name_match_score("Lauren Tyson", "Laura Tyson") == 0

    def test_name_match_score_accepts_reversed_two_token_name(self):
        assert _name_match_score("Ting Xu", "Xu Ting") == 92

    def test_linkedin_backfill_name_variants_generates_controlled_variants(self):
        assert _linkedin_backfill_name_variants("Alex H. Li") == ["Alex Li"]
        assert _linkedin_backfill_name_variants("Xu, Ting") == ["Ting Xu"]
        assert _linkedin_backfill_name_variants("Ting Xu") == ["Xu Ting"]

    def test_choose_linkedin_backfill_match_rejects_wrong_company(self):
        chosen, confidence, status = _choose_linkedin_backfill_match(
            {
                "full_name": "Lauren Tyson",
                "title": "Research Recruiter",
                "snippet": "Verified recruiter at Apple.",
                "source": "theorg_traversal",
                "profile_data": {
                    "public_url": "https://theorg.com/org/apple/org-chart/lauren-tyson",
                    "public_identity_slug": "apple",
                },
            },
            [
                {
                    "full_name": "Lauren Tyson",
                    "title": "Research Recruiter",
                    "snippet": "Research Recruiter at Meta.",
                    "source": "brave_search",
                    "linkedin_url": "https://www.linkedin.com/in/laurentyson",
                    "profile_data": {"linkedin_result_title": "Lauren Tyson - Research Recruiter at Meta"},
                }
            ],
            company_name="Apple",
            bucket="recruiters",
        )

        assert chosen is None
        assert confidence is None
        assert status == "no_match"

    def test_choose_linkedin_backfill_match_rejects_wrong_role_for_bucket(self):
        chosen, confidence, status = _choose_linkedin_backfill_match(
            {
                "full_name": "Lauren Tyson",
                "title": "Research Recruiter",
                "snippet": "Verified recruiter at Apple.",
                "source": "theorg_traversal",
                "profile_data": {
                    "public_url": "https://theorg.com/org/apple/org-chart/lauren-tyson",
                    "public_identity_slug": "apple",
                },
            },
            [
                {
                    "full_name": "Lauren Tyson",
                    "title": "Software Engineer",
                    "snippet": "Software Engineer at Apple.",
                    "source": "brave_search",
                    "linkedin_url": "https://www.linkedin.com/in/laurentyson",
                    "profile_data": {"linkedin_result_title": "Lauren Tyson - Software Engineer at Apple"},
                }
            ],
            company_name="Apple",
            bucket="recruiters",
        )

        assert chosen is None
        assert confidence is None
        assert status == "no_match"

    def test_choose_linkedin_backfill_match_prefers_closest_title_when_names_tie(self):
        chosen, confidence, status = _choose_linkedin_backfill_match(
            {
                "full_name": "Jordan Ferber",
                "title": "Engineering Manager",
                "snippet": "Engineering manager at AppLovin.",
                "source": "theorg_traversal",
                "profile_data": {
                    "public_url": "https://theorg.com/org/applovin/org-chart/jordan-ferber",
                    "public_identity_slug": "applovin",
                },
            },
            [
                {
                    "full_name": "Jordan Ferber",
                    "title": "Engineering Manager",
                    "snippet": "Engineering Manager at AppLovin.",
                    "source": "serper_search",
                    "linkedin_url": "https://www.linkedin.com/in/jordan-ferber",
                    "profile_data": {"linkedin_result_title": "Jordan Ferber - Engineering Manager at AppLovin"},
                },
                {
                    "full_name": "Jordan Ferber",
                    "title": "Senior Director, Sales",
                    "snippet": "Senior Director, Sales at AppLovin.",
                    "source": "serper_search",
                    "linkedin_url": "https://www.linkedin.com/in/jordan-ferber-sales",
                    "profile_data": {"linkedin_result_title": "Jordan Ferber - Senior Director, Sales at AppLovin"},
                },
            ],
            company_name="AppLovin",
            bucket="hiring_managers",
        )

        assert chosen is not None
        assert chosen["linkedin_url"] == "https://www.linkedin.com/in/jordan-ferber"
        assert confidence == 100
        assert status == "matched"

    @pytest.mark.asyncio
    async def test_backfill_linkedin_profiles_upgrades_weak_peer_title(self):
        with patch(
            "app.services.people_service.search_router_client.search_exact_linkedin_profile",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_search.return_value = [
                {
                    "full_name": "Brandon Lee",
                    "title": "Software Engineer",
                    "snippet": "Software Engineer at Whatnot.",
                    "source": "brave_search",
                    "linkedin_url": "https://www.linkedin.com/in/brandonlee",
                    "profile_data": {"linkedin_result_title": "Brandon Lee - Software Engineer at Whatnot"},
                }
            ]
            results = await _backfill_linkedin_profiles(
                [
                    {
                        "full_name": "Brandon Lee",
                        "title": "Whatnot",
                        "snippet": "Current teammate at Whatnot.",
                        "source": "theorg_traversal",
                        "_weak_title": True,
                        "_employment_status": "current",
                        "profile_data": {
                            "public_url": "https://theorg.com/org/whatnot/org-chart/brandon-lee",
                            "public_identity_slug": "whatnot",
                        },
                    }
                ],
                company_name="Whatnot",
                public_identity_slugs=["whatnot"],
                bucket="peers",
            )

        assert results[0]["linkedin_url"] == "https://www.linkedin.com/in/brandonlee"
        assert results[0]["title"] == "Software Engineer"
        assert results[0]["_weak_title"] is False
        assert results[0]["profile_data"]["linkedin_backfill_status"] == "matched"
        assert results[0]["profile_data"]["title_recovery_source"] == "linkedin_backfill"

    @pytest.mark.asyncio
    async def test_backfill_linkedin_profiles_marks_ambiguous_matches(self):
        with patch(
            "app.services.people_service.search_router_client.search_exact_linkedin_profile",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_search.return_value = [
                {
                    "full_name": "Alex Kim",
                    "title": "Software Engineer",
                    "snippet": "Software Engineer at Apple.",
                    "source": "brave_search",
                    "linkedin_url": "https://www.linkedin.com/in/alexkim1",
                    "profile_data": {"linkedin_result_title": "Alex Kim - Software Engineer at Apple"},
                },
                {
                    "full_name": "Alex Kim",
                    "title": "Software Engineer",
                    "snippet": "Software Engineer at Apple.",
                    "source": "brave_search",
                    "linkedin_url": "https://www.linkedin.com/in/alexkim2",
                    "profile_data": {"linkedin_result_title": "Alex Kim - Software Engineer at Apple"},
                },
            ]
            results = await _backfill_linkedin_profiles(
                [
                    {
                        "full_name": "Alex Kim",
                        "title": "Software Engineer",
                        "snippet": "Current teammate at Apple.",
                        "source": "theorg_traversal",
                        "_weak_title": False,
                        "_employment_status": "current",
                        "profile_data": {
                            "public_url": "https://theorg.com/org/apple/org-chart/alex-kim",
                            "public_identity_slug": "apple",
                        },
                    }
                ],
                company_name="Apple",
                public_identity_slugs=["apple"],
                bucket="peers",
            )

        assert results[0].get("linkedin_url") in {None, ""}
        assert results[0]["profile_data"]["linkedin_backfill_status"] == "ambiguous"

    @pytest.mark.asyncio
    async def test_backfill_linkedin_profiles_retries_recruiters_with_broad_title_query(self):
        with (
            patch(
                "app.services.people_service.search_router_client.search_exact_linkedin_profile",
                new_callable=AsyncMock,
            ) as mock_exact,
            patch(
                "app.services.people_service.search_router_client.search_people",
                new_callable=AsyncMock,
            ) as mock_people,
        ):
            mock_exact.return_value = []
            mock_people.return_value = [
                {
                    "full_name": "Meaghan Joynt",
                    "title": "Talent Acquisition @AppLovin",
                    "snippet": "Talent Acquisition @AppLovin.",
                    "source": "serper_search",
                    "linkedin_url": "https://www.linkedin.com/in/meaghanjoynt",
                    "profile_data": {
                        "linkedin_result_title": "Meaghan Joynt - Talent Acquisition @AppLovin",
                    },
                }
            ]
            results = await _backfill_linkedin_profiles(
                [
                    {
                        "full_name": "Meaghan Joynt",
                        "title": "Talent Acquisition Partner",
                        "snippet": "Current recruiter at AppLovin.",
                        "source": "theorg_traversal",
                        "_weak_title": False,
                        "_employment_status": "current",
                        "profile_data": {
                            "public_url": "https://theorg.com/org/applovin/org-chart/meaghan-joynt",
                            "public_identity_slug": "applovin",
                        },
                    }
                ],
                company_name="AppLovin",
                public_identity_slugs=["applovin"],
                bucket="recruiters",
            )

        assert results[0]["linkedin_url"] == "https://www.linkedin.com/in/meaghanjoynt"
        assert results[0]["profile_data"]["linkedin_backfill_status"] == "matched"
        assert results[0]["profile_data"]["linkedin_backfill_strategy"] == "broad_company_title_query"
        mock_people.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_backfill_linkedin_profiles_passes_exact_query_hints(self):
        with (
            patch(
                "app.services.people_service.search_router_client.search_exact_linkedin_profile",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_exact,
            patch(
                "app.services.people_service.search_router_client.search_people",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            await _backfill_linkedin_profiles(
                [
                    {
                        "full_name": "Ting Xu",
                        "title": "Global Talent Acquisition Partner",
                        "snippet": "Current recruiter at AppLovin.",
                        "source": "theorg_traversal",
                        "location": "Toronto, Ontario, Canada",
                        "_weak_title": False,
                        "_employment_status": "current",
                        "profile_data": {
                            "public_url": "https://theorg.com/org/applovin/org-chart/ting-xu",
                            "public_identity_slug": "applovin",
                            "theorg_team_name": "People and Talent",
                            "theorg_team_slug": "people-and-talent",
                            "location": "Toronto, Ontario, Canada",
                        },
                    }
                ],
                company_name="AppLovin",
                public_identity_slugs=["applovin"],
                bucket="recruiters",
                context=JobContext(
                    department="engineering",
                    team_keywords=[],
                    domain_keywords=[],
                    product_team_names=[],
                    seniority="junior",
                    early_career=False,
                    manager_titles=[],
                    peer_titles=[],
                    recruiter_titles=[],
                    apollo_departments=[],
                    job_locations=["Toronto, Ontario, Canada"],
                    job_geo_terms=["Toronto", "Ontario", "Canada"],
                ),
                geo_terms=["Toronto", "Ontario", "Canada"],
                search_profile="interactive",
            )

        _, kwargs = mock_exact.await_args
        assert kwargs["name_variants"] == ["Xu Ting"]
        assert "Global Talent Acquisition Partner" in kwargs["title_hints"]
        assert "talent acquisition" in kwargs["team_keywords"]
        assert kwargs["geo_terms"] == ["Toronto", "Ontario", "Canada"]
        assert kwargs["search_profile"] == "interactive"

    @pytest.mark.asyncio
    async def test_backfill_linkedin_profiles_prioritizes_geo_matched_public_candidates(self):
        observed_names: list[str] = []

        async def _mock_exact(full_name, company_name, **kwargs):
            observed_names.append(full_name)
            return []

        with (
            patch(
                "app.services.people_service.search_router_client.search_exact_linkedin_profile",
                new_callable=AsyncMock,
                side_effect=_mock_exact,
            ),
            patch(
                "app.services.people_service.search_router_client.search_people",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            await _backfill_linkedin_profiles(
                [
                    {
                        "full_name": "Generic Recruiter",
                        "title": "Recruiter",
                        "snippet": "Recruiter at Intuit.",
                        "source": "theorg_traversal",
                        "location": "New York, New York, United States",
                        "_employment_status": "current",
                        "profile_data": {
                            "public_url": "https://theorg.com/org/intuit/org-chart/generic-recruiter",
                            "public_identity_slug": "intuit",
                            "location": "New York, New York, United States",
                        },
                    },
                    {
                        "full_name": "Reiss Simmons",
                        "title": "Senior Talent Acquisition Manager",
                        "snippet": "Senior Talent Acquisition Manager at Intuit in Toronto.",
                        "source": "brave_public_web",
                        "location": "Toronto, Ontario, Canada",
                        "_employment_status": "current",
                        "profile_data": {
                            "public_url": "https://theorg.com/org/intuit/org-chart/reiss-simmons",
                            "public_identity_slug": "intuit",
                            "location": "Toronto, Ontario, Canada",
                        },
                    },
                ],
                company_name="Intuit",
                public_identity_slugs=["intuit"],
                bucket="recruiters",
                context=JobContext(
                    department="engineering",
                    team_keywords=[],
                    domain_keywords=[],
                    product_team_names=[],
                    seniority="junior",
                    early_career=False,
                    manager_titles=[],
                    peer_titles=[],
                    recruiter_titles=[],
                    apollo_departments=[],
                    job_locations=["Toronto, Ontario, Canada"],
                    job_geo_terms=["Toronto", "Ontario", "Canada"],
                ),
                geo_terms=["Toronto", "Ontario", "Canada"],
                search_profile="interactive",
            )

        assert observed_names[0] == "Reiss Simmons"

    @pytest.mark.asyncio
    async def test_backfill_top_candidates_only_backfills_provisional_top_slice(self):
        with patch(
            "app.services.people_service._backfill_linkedin_profiles",
            new_callable=AsyncMock,
        ) as mock_backfill:
            mock_backfill.return_value = [
                {"full_name": "Top 1", "linkedin_url": "https://linkedin.com/in/top1"},
                {"full_name": "Top 2", "linkedin_url": "https://linkedin.com/in/top2"},
            ]
            results = await _backfill_top_candidates(
                [
                    {"full_name": "Top 1"},
                    {"full_name": "Top 2"},
                    {"full_name": "Keep 3"},
                    {"full_name": "Keep 4"},
                ],
                top_n=2,
                company_name="Intuit",
                public_identity_slugs=["intuit"],
                bucket="recruiters",
            )

        assert [item["full_name"] for item in results] == ["Top 1", "Top 2", "Keep 3", "Keep 4"]
        assert len(mock_backfill.await_args.args[0]) == 2

    def test_score_contextual_candidates_fast_orders_by_heuristics(self):
        job = SimpleNamespace(title="Software Developer 1", company_name="Intuit")
        context = JobContext(
            department="engineering",
            team_keywords=["fullstack"],
            domain_keywords=["payments"],
            product_team_names=[],
            seniority="junior",
            early_career=False,
            manager_titles=[],
            peer_titles=[],
            recruiter_titles=[],
            apollo_departments=[],
            job_locations=["Toronto, Ontario, Canada"],
            job_geo_terms=["Toronto", "Ontario", "Canada"],
        )
        ranked = _score_contextual_candidates_fast(
            [
                {
                    "full_name": "Generic Manager",
                    "title": "Engineering Manager",
                    "snippet": "Engineering Manager at Intuit.",
                    "location": "Mountain View, California, United States",
                },
                {
                    "full_name": "Toronto Fullstack Manager",
                    "title": "Fullstack Engineering Manager",
                    "snippet": "Payments engineering leader at Intuit.",
                    "location": "Toronto, Ontario, Canada",
                },
            ],
            job=job,
            context=context,
            min_relevance_score=1,
            bucket="hiring_managers",
        )

        assert ranked[0]["full_name"] == "Toronto Fullstack Manager"
        assert ranked[0]["relevance_score"] >= ranked[1]["relevance_score"]

    def test_candidate_geo_signal_match_uses_title_and_snippet_when_location_missing(self):
        context = JobContext(
            department="engineering",
            team_keywords=["fullstack"],
            domain_keywords=[],
            product_team_names=[],
            seniority="junior",
            early_career=False,
            manager_titles=[],
            peer_titles=[],
            recruiter_titles=[],
            apollo_departments=[],
            job_locations=["Toronto, Ontario, Canada"],
            job_geo_terms=["Toronto", "Greater Toronto Area", "Ontario", "Canada"],
        )

        assert _candidate_geo_signal_match(
            {
                "title": "Software Engineering Manager",
                "snippet": "Current Software Engineering Manager at Intuit in Toronto.",
                "profile_data": {},
            },
            context=context,
        ) is True

    def test_initial_manager_titles_prioritize_engineering_leadership_variants(self):
        context = JobContext(
            department="engineering",
            team_keywords=["fullstack"],
            domain_keywords=["payments"],
            product_team_names=[],
            seniority="junior",
            early_career=False,
            manager_titles=["Engineering Manager"],
            peer_titles=[],
            recruiter_titles=[],
            apollo_departments=[],
            job_locations=["Toronto, Ontario, Canada"],
            job_geo_terms=["Toronto", "Ontario", "Canada"],
        )

        titles = _initial_manager_titles(context)

        assert "Engineering Manager" in titles[:2]
        assert "Software Engineering Manager" in titles
        assert "Team Lead" in titles
        assert "Technical Lead" in titles
        assert "Senior Engineering Manager" in titles
        assert "Director of Engineering" in titles

    def test_manager_context_search_titles_drops_non_manageric_job_title_derivatives(self):
        context = JobContext(
            department="engineering",
            team_keywords=["fullstack", "qa"],
            domain_keywords=[],
            product_team_names=[],
            seniority="junior",
            early_career=False,
            manager_titles=[
                "Engineering Manager",
                "Senior Software Developer 1 (Center of Money)",
                "Software Developer 1 (Center of Money) Team Lead",
                "Director of Engineering",
            ],
            peer_titles=[],
            recruiter_titles=[],
            apollo_departments=[],
            job_locations=["Toronto, Ontario, Canada"],
            job_geo_terms=["Toronto", "Ontario", "Canada"],
        )

        assert _manager_context_search_titles(context) == [
            "Engineering Manager",
            "Director of Engineering",
        ]

    def test_manager_geo_recovery_titles_adds_broader_leadership_variants_without_dropping_core_manager_titles(self):
        context = JobContext(
            department="engineering",
            team_keywords=["fullstack"],
            domain_keywords=["payments"],
            product_team_names=[],
            seniority="junior",
            early_career=False,
            manager_titles=["Engineering Manager"],
            peer_titles=[],
            recruiter_titles=[],
            apollo_departments=[],
            job_locations=["Toronto, Ontario, Canada"],
            job_geo_terms=["Toronto", "Ontario", "Canada"],
        )

        titles = _manager_geo_recovery_titles(context)

        assert "Engineering Manager" in titles[:2]
        assert "Software Engineering Manager" in titles
        assert "Software Development Manager" in titles
        assert "VP Engineering" in titles

    def test_sanitize_search_keywords_drops_company_name_noise(self):
        assert _sanitize_search_keywords(
            ["Intuit", "fullstack", "payments", "Intuit"],
            company_name="Intuit",
        ) == ["fullstack", "payments"]

    def test_should_run_manager_geo_recovery_when_bucket_underfilled(self):
        context = JobContext(
            department="engineering",
            team_keywords=["fullstack"],
            domain_keywords=[],
            product_team_names=[],
            seniority="junior",
            early_career=False,
            manager_titles=[],
            peer_titles=[],
            recruiter_titles=[],
            apollo_departments=[],
            job_locations=["Toronto, Ontario, Canada"],
            job_geo_terms=["Toronto", "Greater Toronto Area", "Ontario", "Canada"],
        )

        assert _should_run_manager_geo_recovery(
            [
                {
                    "title": "Engineering Manager",
                    "snippet": "Engineering Manager at Intuit in Toronto.",
                    "profile_data": {},
                }
            ],
            context=context,
            target_count_per_bucket=3,
        ) is True

    def test_should_skip_manager_geo_recovery_when_bucket_is_full_and_local(self):
        context = JobContext(
            department="engineering",
            team_keywords=["fullstack"],
            domain_keywords=[],
            product_team_names=[],
            seniority="junior",
            early_career=False,
            manager_titles=[],
            peer_titles=[],
            recruiter_titles=[],
            apollo_departments=[],
            job_locations=["Toronto, Ontario, Canada"],
            job_geo_terms=["Toronto", "Greater Toronto Area", "Ontario", "Canada"],
        )

        assert _should_run_manager_geo_recovery(
            [
                {
                    "title": "Engineering Manager",
                    "snippet": "Engineering Manager at Intuit in Toronto.",
                    "profile_data": {},
                },
                {
                    "title": "Software Engineering Manager",
                    "snippet": "Software Engineering Manager at Intuit in Greater Toronto Area.",
                    "profile_data": {},
                },
                {
                    "title": "Group Engineering Manager",
                    "snippet": "Group Engineering Manager at Intuit in Toronto.",
                    "profile_data": {},
                },
            ],
            context=context,
            target_count_per_bucket=3,
        ) is False

    def test_candidate_bucket_assignment_rank_prefers_explicit_manager_titles_over_generic_leaders(self):
        context = JobContext(
            department="engineering",
            team_keywords=[],
            domain_keywords=[],
            product_team_names=[],
            seniority="junior",
            early_career=False,
            manager_titles=[],
            peer_titles=[],
            recruiter_titles=[],
            apollo_departments=[],
            job_locations=["Toronto, Ontario, Canada"],
            job_geo_terms=["Toronto", "Greater Toronto Area", "Ontario", "Canada"],
        )

        explicit_manager = {
            "full_name": "David Van Noten",
            "title": "Senior Engineering Manager - Intuit",
            "snippet": "Greater Toronto Area, Canada",
            "source": "tavily_public_web",
            "linkedin_url": "https://ca.linkedin.com/in/davidvn",
            "location": "Greater Toronto Area, Canada",
            "profile_data": {},
        }
        generic_leader = {
            "full_name": "Rex Su",
            "title": "Engineering Leader | Intuit",
            "snippet": "Toronto, Ontario, Canada",
            "source": "tavily_public_web",
            "linkedin_url": "https://ca.linkedin.com/in/rexsu",
            "location": "Toronto, Ontario, Canada",
            "profile_data": {},
        }

        assert _candidate_bucket_assignment_rank(
            "hiring_managers",
            explicit_manager,
            context=context,
            company_name="Intuit",
            public_identity_slugs=["intuit"],
        ) < _candidate_bucket_assignment_rank(
            "hiring_managers",
            generic_leader,
            context=context,
            company_name="Intuit",
            public_identity_slugs=["intuit"],
        )

    @pytest.mark.asyncio
    async def test_store_person_merges_linkedin_into_existing_public_profile(self):
        existing = SimpleNamespace(
            apollo_id=None,
            title="Whatnot",
            full_name="Brandon Lee",
            company_id=None,
            company=None,
            profile_data={"public_url": "https://theorg.com/org/whatnot/org-chart/brandon-lee"},
            linkedin_url=None,
        )
        company = SimpleNamespace(id=uuid.uuid4(), name="Whatnot")
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_ScalarResult(existing)])

        person = await _store_person(
            db,
            uuid.uuid4(),
            company,
            {
                "full_name": "Brandon Lee",
                "title": "Software Engineer",
                "linkedin_url": "https://www.linkedin.com/in/brandonlee",
                "profile_data": {
                    "public_url": "https://theorg.com/org/whatnot/org-chart/brandon-lee",
                    "linkedin_backfill_status": "matched",
                },
            },
            "peer",
        )

        assert person is existing
        assert existing.linkedin_url == "https://www.linkedin.com/in/brandonlee"
        assert existing.title == "Software Engineer"
        assert existing.profile_data["linkedin_backfill_status"] == "matched"
