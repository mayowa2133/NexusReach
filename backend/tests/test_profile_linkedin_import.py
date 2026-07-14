"""Own-profile LinkedIn import merge logic (Workstream F)."""

from app.models.profile import Profile
from app.services.profile_linkedin_import import merge_linkedin_profile

PAYLOAD = {
    "linkedin_url": "https://www.linkedin.com/in/jane-doe/",
    "full_name": "Jane Doe",
    "headline": "Staff Engineer at Acme",
    "positions": [
        {"title": "Staff Engineer", "company": "Acme"},
        {"title": "SWE", "company": "Globex"},
    ],
    "education": [{"school": "State University", "degree": "BSc"}],
    "skills": ["Python", "Go"],
}


def test_fills_blank_profile_fields():
    profile = Profile()
    changed = merge_linkedin_profile(profile, PAYLOAD)

    assert profile.full_name == "Jane Doe"
    assert profile.bio == "Staff Engineer at Acme"
    assert profile.linkedin_url == "https://www.linkedin.com/in/jane-doe"
    assert changed["filled_name"] and changed["filled_bio"] and changed["filled_linkedin_url"]


def test_does_not_clobber_existing_fields():
    profile = Profile(full_name="Existing Name", bio="My bio", linkedin_url="https://x")
    merge_linkedin_profile(profile, PAYLOAD)

    assert profile.full_name == "Existing Name"
    assert profile.bio == "My bio"
    assert profile.linkedin_url == "https://x"


def test_populates_resume_parsed_for_affinity():
    profile = Profile()
    changed = merge_linkedin_profile(profile, PAYLOAD)

    parsed = profile.resume_parsed
    companies = {e["company"] for e in parsed["experience"]}
    schools = {e["school"] for e in parsed["education"]}
    assert companies == {"Acme", "Globex"}
    assert schools == {"State University"}
    assert set(parsed["skills"]) == {"Python", "Go"}
    assert changed["positions_added"] == 2
    assert changed["education_added"] == 1
    assert changed["skills_added"] == 2
    assert parsed["linkedin_import"]["source"] == "companion"


def test_merges_without_duplicating_or_losing_resume_data():
    profile = Profile(
        resume_parsed={
            "skills": ["Python"],
            "experience": [{"title": "Senior SWE", "company": "Acme"}],
            "education": [{"school": "State University"}],
        }
    )
    changed = merge_linkedin_profile(profile, PAYLOAD)

    parsed = profile.resume_parsed
    # Existing Acme/State University preserved; only new distinct rows appended.
    companies = [e["company"] for e in parsed["experience"]]
    assert companies.count("Acme") == 1
    assert "Globex" in companies
    assert len(parsed["education"]) == 1  # State University not duplicated
    assert set(parsed["skills"]) == {"Python", "Go"}
    assert changed["positions_added"] == 1
    assert changed["education_added"] == 0
    assert changed["skills_added"] == 1


def test_skips_url_when_invalid():
    profile = Profile()
    merge_linkedin_profile(profile, {"full_name": "No URL", "linkedin_url": "not-a-url"})
    assert profile.linkedin_url is None
