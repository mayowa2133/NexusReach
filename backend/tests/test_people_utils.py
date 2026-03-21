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
    _candidate_matches_company,
    _classify_employment_status,
    _classify_org_level,
    _classify_person,
    _choose_linkedin_backfill_match,
    _compute_match_metadata,
    _name_match_score,
    _prioritize_titles_for_search,
    _prepare_candidates,
    _recover_candidate_titles,
    _store_person,
    get_or_create_company,
)
from app.services.email_finder_service import _split_name
from app.utils.job_context import JobContext


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        value = self._value

        class _Scalars:
            def __init__(self, raw):
                self._raw = raw

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

    @pytest.mark.asyncio
    async def test_recover_candidate_titles_recovers_from_snippet(self):
        company = SimpleNamespace(
            public_identity_slugs=["whatnot"],
            identity_hints={},
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

    def test_name_match_score_accepts_same_name_and_last_initial(self):
        assert _name_match_score("Derek S.", "Derek Smith") == 90
        assert _name_match_score("Lauren Tyson", "Lauren Tyson") == 100
        assert _name_match_score("Lauren Tyson", "Laura Tyson") == 0

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

    @pytest.mark.asyncio
    async def test_backfill_linkedin_profiles_upgrades_weak_peer_title(self):
        with patch(
            "app.services.people_service.brave_search_client.search_exact_linkedin_profile",
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
            "app.services.people_service.brave_search_client.search_exact_linkedin_profile",
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
