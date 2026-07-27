"""Contact-field sanity checks (functionality audit 2026-07-26, finding #5).

A live search returned 28 contacts of which ~18% were unusable: a LinkedIn feed
post parsed as a job title, the company name as a title, empty titles, and
LinkedIn's truncated "Christopher K." names. These fields feed the drafting
model, so they don't just look untidy — they make the outreach look automated.
"""

from app.services.people import contact_quality as cq


# --- prose that isn't a job title ------------------------------------------


def test_a_feed_post_is_not_a_title():
    """The real value observed in production discovery."""
    assert cq.clean_title("Wonderful post from Letícia about their move") is None


def test_first_person_text_is_not_a_title():
    assert cq.clean_title("I'm excited to share that we're hiring!") is None
    assert cq.clean_title("Check out our open roles") is None


def test_sentences_are_not_titles():
    assert cq.clean_title("We build payments infrastructure. Join us.") is None


def test_overlong_text_is_not_a_title():
    assert cq.clean_title("Engineering leader " * 12) is None


# --- values that carry no signal -------------------------------------------


def test_company_name_alone_is_not_a_title():
    assert cq.clean_title("Stripe", "Stripe") is None
    assert cq.clean_title("  stripe  ", "Stripe") is None


def test_placeholder_junk_is_dropped():
    for junk in ("N/A", "n/a", "none", "-", "LOCATION", "View profile"):
        assert cq.clean_title(junk) is None, junk


def test_empty_and_punctuation_only():
    assert cq.clean_title("") is None
    assert cq.clean_title("   ") is None
    assert cq.clean_title("---") is None
    assert cq.clean_title("2024") is None


# --- real titles must survive ----------------------------------------------


def test_genuine_titles_pass_through():
    for title in (
        "Engineering Manager, Security",
        "Software Engineer @ Stripe | Full-Stack",
        "University Recruiter",
        "Sr. IP Product Engineer, AI Processor",
        "Talent Acquisition @ Stripe",
        "APAC Head of Customer Engineering",
    ):
        assert cq.clean_title(title, "Stripe") == title.strip(), title


def test_a_title_containing_the_company_still_passes():
    """Only the company name *alone* is meaningless."""
    assert cq.clean_title("Recruiting @ Stripe", "Stripe") == "Recruiting @ Stripe"


# --- greeting names ---------------------------------------------------------


def test_truncated_surname_is_trimmed_for_greeting():
    """"Hi Christopher K." is a tell that the message was generated."""
    assert cq.greeting_name("Christopher K.") == "Christopher"
    assert cq.greeting_name("Johnson G") == "Johnson"


def test_normal_names_greet_on_the_first_name():
    assert cq.greeting_name("Amy Salazar") == "Amy"
    assert cq.greeting_name("Bryan Irace") == "Bryan"


def test_leading_initial_prefers_the_next_token():
    assert cq.greeting_name("J. Smith") == "Smith"


def test_single_name_and_empty():
    assert cq.greeting_name("Cher") == "Cher"
    assert cq.greeting_name("") is None
    assert cq.greeting_name(None) is None


# --- keeping the person, not discarding them -------------------------------


def test_a_contact_with_a_bad_title_is_still_a_contact():
    """Recall is expensive; only a missing identity is worth dropping."""
    assert cq.is_usable_contact({"full_name": "Ryan Peterman", "title": ""}) is True


def test_a_nameless_result_is_dropped():
    assert cq.is_usable_contact({"full_name": "", "title": "Engineer"}) is False


def test_a_prose_blob_as_a_name_is_dropped():
    assert cq.is_usable_contact(
        {"full_name": "Wonderful post from Letícia about their move"}
    ) is False
