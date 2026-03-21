# NexusReach Handoff

## Completed in this pass
- Added exact-job Workable ATS support.
  - `parse_ats_job_url()` now recognizes `apply.workable.com/<company>/j/<shortcode>` URLs
  - ATS search can import a pasted Workable posting through the public `api/v2/accounts/{company}/jobs/{shortcode}` endpoint
  - normalized jobs are stored as `ats="workable"` and use the returned canonical Workable shortcode URL
- Added a generic free-first public page fetch layer.
  - Strategy is now direct `httpx` fetch first, then Crawl4AI, then Firecrawl only if configured.
  - Public-web employment verification no longer bails out when Firecrawl env is missing.
  - New public-web verification writes use `current_company_verification_source="public_web"` while old `firecrawl_public_web` rows remain readable.
- Added Firecrawl-backed The Org graph traversal for people discovery.
  - Resolves a trusted The Org org slug from `Company.public_identity_slugs`
  - Traverses company org pages, relevant team pages, and selected manager person pages
  - Harvests recruiter, hiring-manager, and peer candidates with `source="theorg_traversal"`
- The Org candidates now carry richer public metadata in `profile_data`.
  - `public_url`, `public_host`, `public_identity_slug`, `public_page_type`
  - `theorg_origin_url`, `theorg_team_slug`, `theorg_team_name`
  - `theorg_relationship`, `theorg_parent_name`, `theorg_parent_title`
- People discovery now uses The Org as a second-stage expansion when buckets are underfilled or the company name is ambiguous.
  - Existing Apollo + Brave + hiring-team search stays in place
  - The Org candidates are merged into the existing `_prepare_candidates()` path before storage/ranking
- Current-company verification is stricter for public pages.
  - direct trusted-slug shortcut now only applies to The Org person pages
  - team-page verification now requires the trusted company slug plus the candidate’s name and title on the scraped team page
- Added backend config for bounded traversal and cache TTL in `backend/.env.example`.

## Files changed in this pass
- `backend/app/clients/firecrawl_client.py`
- `backend/app/clients/ats_client.py`
- `backend/app/clients/public_page_client.py`
- `backend/app/clients/theorg_client.py`
- `backend/app/clients/crawl4ai_client.py`
- `backend/app/config.py`
- `backend/app/services/job_service.py`
- `backend/app/services/employment_verification_service.py`
- `backend/app/services/people_service.py`
- `backend/app/services/theorg_discovery_service.py`
- `backend/app/utils/company_identity.py`
- `backend/tests/test_ats_client.py`
- `backend/tests/test_employment_verification_service.py`
- `backend/tests/test_job_service_ats.py`
- `backend/tests/test_theorg_client.py`
- `backend/tests/test_theorg_discovery_service.py`
- `backend/.env.example`
- `HANDOFF.md`
- `lessons.md`

## Verification completed
- `cd backend && ruff check app tests conftest.py`
- `cd backend && pytest`
  - result: `517 passed`
- Targeted The Org / verification checks:
  - `cd backend && pytest tests/test_public_page_client.py tests/test_theorg_client.py tests/test_theorg_discovery_service.py tests/test_employment_verification_service.py tests/test_people_utils.py -q`
  - result: `39 passed`

## Remaining caveats
- Firecrawl is now an optional fallback, but self-hosted or hosted Firecrawl can still help on harder public pages where direct fetch and Crawl4AI both underperform.
- Workable support currently covers the pasted job URL flow. Full Workable company-board crawling from `company_slug + ats_type` alone is still not implemented.
- This pass improves contact recall only. It does not change email-domain trust, email guessing safety, or the verified-only final bucket rule.
- The traversal is intentionally bounded:
  - up to 3 team pages
  - up to 3 manager person pages
  - up to 25 harvested candidates before normal prep/ranking

## Suggested next manual check
- Run the Zip Ashby posting again with Firecrawl configured and confirm the People buckets recover:
  - recruiters from the HR / Talent team
  - engineering managers from the Software Development and Engineering team
  - peers from engineering team members and manager direct reports
- Then run one non-ambiguous company and confirm:
  - The Org traversal does not overrun already-good results
  - email lookup still withholds guesses when `company.domain_trusted` is false
