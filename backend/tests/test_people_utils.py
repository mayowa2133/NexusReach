"""Tests for People Finder utility functions — Phase 3.

Tests pure functions: _classify_person from people_service,
_split_name from email_finder_service.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.people_service import (
    _backfill_linkedin_profiles,
    _broaden_peer_titles_for_retry,
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
    _prioritize_titles_for_search,
    _prepare_candidates,
    _recover_candidate_titles,
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
                        "_weak_title": False,
                        "_employment_status": "current",
                        "profile_data": {
                            "public_url": "https://theorg.com/org/applovin/org-chart/ting-xu",
                            "public_identity_slug": "applovin",
                            "theorg_team_name": "People and Talent",
                            "theorg_team_slug": "people-and-talent",
                        },
                    }
                ],
                company_name="AppLovin",
                public_identity_slugs=["applovin"],
                bucket="recruiters",
            )

        _, kwargs = mock_exact.await_args
        assert kwargs["name_variants"] == ["Xu Ting"]
        assert "Global Talent Acquisition Partner" in kwargs["title_hints"]
        assert "talent acquisition" in kwargs["team_keywords"]

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
