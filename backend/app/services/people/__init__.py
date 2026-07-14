"""People discovery service package.

Module layering (each module imports only from those below it):

    service          orchestrators (search_people_for_job, ...)
    persistence      company/person storage, captures, saved people
    candidates       search, dedupe, limits, recovery gates
    buckets          bucket assembly and finalization
    linkedin_backfill, theorg_recovery
    ranking          candidate/person ranks, scores, sort keys
    company_match    company-identity and employment verification
    classify, context
    titles, identity pure text primitives
"""

from app.services.people.persistence import (
    capture_linkedin_profile,
    get_or_create_company,
    get_saved_people,
    get_search_history,
    persist_linkedin_page_capture,
)
from app.services.people.service import (
    enrich_person_from_linkedin,
    search_people_at_company,
    search_people_for_job,
)

__all__ = [
    "capture_linkedin_profile",
    "enrich_person_from_linkedin",
    "get_or_create_company",
    "get_saved_people",
    "get_search_history",
    "persist_linkedin_page_capture",
    "search_people_at_company",
    "search_people_for_job",
]
