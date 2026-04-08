from app.services.linkedin_graph_browser_sync import (
    dedupe_scraped_connections,
    infer_company_name_from_headline,
    normalize_scraped_connection,
)


def test_infer_company_name_from_headline_handles_at_patterns():
    assert infer_company_name_from_headline("Senior Recruiter at Acme") == "Acme"
    assert infer_company_name_from_headline("Software Engineer @ Stripe | Payments") == "Stripe"


def test_infer_company_name_from_headline_is_conservative():
    assert infer_company_name_from_headline("Product manager, developer tooling") is None
    assert infer_company_name_from_headline(None) is None


def test_normalize_scraped_connection_inferrs_company_from_headline():
    row = normalize_scraped_connection(
        {
            "full_name": "Jane Doe",
            "linkedin_url": "linkedin.com/in/jane-doe?trk=profile",
            "headline": "Senior Recruiter at Acme",
        }
    )

    assert row == {
        "full_name": "Jane Doe",
        "linkedin_url": "https://www.linkedin.com/in/jane-doe",
        "headline": "Senior Recruiter at Acme",
        "current_company_name": "Acme",
        "company_linkedin_url": None,
    }


def test_dedupe_scraped_connections_merges_missing_fields_by_url():
    rows = dedupe_scraped_connections(
        [
            {
                "full_name": "Jane Doe",
                "linkedin_url": "https://www.linkedin.com/in/jane-doe",
                "headline": "Recruiter at Acme",
            },
            {
                "display_name": "Jane Doe",
                "linkedin_url": "linkedin.com/in/jane-doe/",
                "current_company_name": "Acme",
                "company_linkedin_url": "https://www.linkedin.com/company/acme",
            },
        ]
    )

    assert rows == [
        {
            "full_name": "Jane Doe",
            "linkedin_url": "https://www.linkedin.com/in/jane-doe",
            "headline": "Recruiter at Acme",
            "current_company_name": "Acme",
            "company_linkedin_url": "https://www.linkedin.com/company/acme",
        }
    ]
