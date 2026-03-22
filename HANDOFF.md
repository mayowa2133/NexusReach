# NexusReach Handoff

Last updated: 2026-03-22

## Current state

NexusReach is past the original MVP. The app now supports:
- board-backed ATS search plus exact-job URL ingestion
- job-aware people discovery
- bounded The Org traversal and slug repair
- LinkedIn backfill for verified public candidates
- same-company contact hierarchy (`direct`, `adjacent`, `next_best`)
- safe best-guess emails from approved domain signals
- multi-provider search routing with Redis caching
- multi-provider LLM drafting
- saved-contact company filtering across People, Messages, and Outreach

## Major capabilities that are live

### Job import
- Board-backed ATS:
  - Greenhouse
  - Lever
  - Ashby
- Exact-job ingestion:
  - Workable
  - Apple Jobs
  - Workday exact-job URLs
  - generic exact-job hosts when structured metadata is available

### People discovery
- Search stack:
  - Serper for primary bulk discovery
  - Brave for exact LinkedIn backfill and fallback
  - Tavily for employment corroboration and fallback public discovery
  - Google CSE as optional legacy fallback
- The Org traversal:
  - resolves trusted org slugs from `public_identity_slugs`
  - validates and repairs stale slugs
  - traverses org/team/person pages with bounded budgets
- LinkedIn backfill:
  - second-pass exact-name/company x-ray for verified The Org/public-web candidates
  - strict name/company/role matching before attaching a profile

### Verification and ranking
- `current_company_verified` is tracked separately from role fit.
- Public verification source now writes `public_web`.
- Stored legacy `firecrawl_public_web` values remain readable.
- Final buckets are ranked as:
  - `direct`
  - `adjacent`
  - `next_best`
- Lower-confidence same-company fallbacks are explicitly labeled instead of being dropped.

### Email behavior
- Email lookup can return:
  - `verified`
  - `best_guess`
  - `not_found`
- Best guesses are allowed only from safe signals:
  - trusted domain
  - official careers/site host
  - learned company pattern
- Ambiguous-company protections still block unsafe domains.

## Latest infrastructure direction

### Search routing
- Brave is preserved, but not used as the default bulk provider anymore.
- Current default routing:
  - bulk people: `Serper -> Brave -> Google CSE`
  - exact LinkedIn backfill: `Brave -> Serper -> Google CSE`
  - hiring-team search: `Serper -> Brave`
  - public people: `Serper -> Brave -> Tavily`
  - employment corroboration: `Tavily -> Serper -> Brave`
- Redis caches raw search results by query family.

### Public-page retrieval
- Free-first retrieval order:
  - direct `httpx`
  - Crawl4AI
  - Firecrawl optional fallback

## Important files to understand first

### Backend
- `backend/app/clients/ats_client.py`
- `backend/app/clients/search_router_client.py`
- `backend/app/clients/serper_search_client.py`
- `backend/app/clients/tavily_search_client.py`
- `backend/app/clients/theorg_client.py`
- `backend/app/services/job_service.py`
- `backend/app/services/people_service.py`
- `backend/app/services/employment_verification_service.py`
- `backend/app/services/email_finder_service.py`
- `backend/app/utils/company_identity.py`
- `backend/app/utils/job_context.py`

### Frontend
- `frontend/src/pages/JobsPage.tsx`
- `frontend/src/pages/PeoplePage.tsx`
- `frontend/src/pages/MessagesPage.tsx`
- `frontend/src/pages/OutreachPage.tsx`
- `frontend/src/types/index.ts`

## Current known limitations

1. Manager precision is still weaker than recruiter and peer precision at large companies.
2. Some company identities still need manual tuning when a short brand overlaps with another company or common first name.
3. Workday support is first-class for exact-job URLs, but live upstream maintenance/outage pages still block import and should fail honestly.
4. LinkedIn backfill intentionally favors precision over recall, so a human may still find a valid LinkedIn that the tool refuses to attach.
5. Search cache smoke scripts can print async Redis shutdown warnings at interpreter exit. The request path still works.

## Good regression fixtures

- Zip Ashby roles: ambiguous-company and The Org slug/verification regression
- Whatnot Ashby new-grad roles: recruiter-first early-career discovery
- Apple exact-job URLs: first-class proprietary exact-job ingestion
- Fortune Workday role: Fortune Media vs Fortune Brands identity split
- Uber proprietary jobs: generic exact-job ingestion + same-company ranking
- xAI Greenhouse role: hierarchy fallback and safe best-guess email behavior

## Last meaningful verification snapshot

- Backend:
  - `cd backend && ruff check app tests conftest.py`
  - `cd backend && pytest`
- Frontend:
  - `cd frontend && npx eslint .`
  - `cd frontend && npx tsc -b`
  - `cd frontend && npm run test`
  - `cd frontend && npm run build`

The most recent code pass before this doc sync also included live smoke checks for:
- Serper bulk people discovery
- Brave exact LinkedIn backfill
- Tavily employment corroboration
- Redis search-cache hits

## Suggested next product-level improvements

1. Improve hiring-manager precision for large engineering orgs.
2. Expand exact-job host coverage beyond the current Apple/Workday/Workable set.
3. Tighten duplicate suppression across buckets so the same person is less likely to appear as both manager and peer fallback.
4. Add clearer provider/cost observability in the UI or admin tooling.
