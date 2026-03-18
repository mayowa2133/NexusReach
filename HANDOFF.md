# NexusReach Handoff

## Completed in this pass
- Added exact ATS job-link ingestion for Greenhouse, Lever, and Ashby.
  - `POST /api/jobs/search/ats` now accepts `job_url` as well as `company_slug + ats_type`.
  - Greenhouse embed URLs are normalized via `for` + `token`.
  - Exact-link searches return the matched job first so the Jobs UI can auto-select it.
- Tightened job-aware people discovery.
  - Reworked `job_context.py` to use weighted title/lead/body scoring.
  - Added higher-signal domain tags such as `credit`, `risk`, `decisioning`, `marketplace`, `consumer`, and `merchant`.
  - Removed `staff` and `principal` from implicit manager bucketing.
  - Added `match_quality` and `match_reason` on people responses.
  - Added a Brave-powered public-web enrichment pass in addition to Apollo and LinkedIn X-ray.
- Reworked the email finder to be verified-first with best-effort fallback.
  - `/api/email/find/{person_id}` now supports `mode=best_effort|verified_only` and defaults to `best_effort`.
  - Response now includes `result_type`, `verified_email`, `best_guess_email`, `alternate_guesses`, and `failure_reasons`.
  - Low-confidence pattern suggestions are surfaced after verified paths fail instead of being silently dropped.
  - Added lightweight company-level email pattern learning on `companies.email_pattern` and `companies.email_pattern_confidence`.
- Fixed auth bootstrap.
  - JWT email is now used for first-login user creation.
  - Missing-email tokens fall back to `<user_id>@users.nexusreach.invalid`.
  - Existing blank-email users are backfilled on login.
- Updated the frontend.
  - Jobs page now uses one smart ATS input for board IDs or full ATS job URLs.
  - People page shows direct vs next-best match context and renders unverified email guesses with confidence and alternates.
  - Messages page distinguishes verified emails from best guesses in the toast flow.
- Added backend and frontend regression coverage for the new behavior.
- Updated `lessons.md`.

## Files changed in this pass
- `backend/alembic/versions/010_add_company_email_pattern_fields.py`
- `backend/app/clients/ats_client.py`
- `backend/app/clients/brave_search_client.py`
- `backend/app/clients/email_suggestion_client.py`
- `backend/app/dependencies.py`
- `backend/app/models/company.py`
- `backend/app/routers/email.py`
- `backend/app/routers/jobs.py`
- `backend/app/schemas/email.py`
- `backend/app/schemas/jobs.py`
- `backend/app/schemas/people.py`
- `backend/app/services/email_finder_service.py`
- `backend/app/services/job_service.py`
- `backend/app/services/people_service.py`
- `backend/app/utils/job_context.py`
- `backend/tests/test_ats_client.py`
- `backend/tests/test_dependencies.py`
- `backend/tests/test_email_finder_service.py`
- `backend/tests/test_job_context.py`
- `backend/tests/test_jobs_api.py`
- `backend/tests/test_people_api.py`
- `backend/tests/test_people_job_search.py`
- `backend/tests/test_people_utils.py`
- `frontend/src/hooks/useJobs.ts`
- `frontend/src/pages/JobsPage.tsx`
- `frontend/src/pages/MessagesPage.tsx`
- `frontend/src/pages/PeoplePage.tsx`
- `frontend/src/pages/__tests__/JobsPage.test.tsx`
- `frontend/src/pages/__tests__/MessagesPage.test.tsx`
- `frontend/src/pages/__tests__/PeoplePage.test.tsx`
- `frontend/src/types/index.ts`
- `lessons.md`

## Verification completed
- `cd backend && ruff check app tests conftest.py`
- `cd backend && pytest`
  - result: `458 passed`
- `cd frontend && npx tsc -b`
- `cd frontend && npx eslint .`
- `cd frontend && npm run test`
  - result: `90 passed`
- `cd frontend && npm run build`

## Remaining caveats
- I did not run `alembic upgrade head` against a live/shared database in this pass. The new migration file exists, but DB migration execution still needs to happen in the target environment.
- The repo still contains earlier uncommitted changes from the previous pass outside this exact feature set:
  - `backend/alembic/env.py`
  - `backend/alembic/versions/001_add_apollo_id_to_persons.py`
  - `backend/alembic/versions/008_seed_smtp_blocklist.py`
  - `backend/app/models/person.py`
  - plus the already-added migration/test files from that work
- Full backend pytest still emits existing warning noise about sync tests marked with `pytest.mark.asyncio`; I did not clean that up here because it is unrelated to the functional changes.

## Suggested next manual check
- Start the app, paste the original Affirm embed URL into Jobs, confirm the exact posting auto-selects, then click `Find People` and verify the new `direct` / `next best` and best-guess email UI in the live flow.
