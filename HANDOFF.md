# NexusReach Handoff

Last updated: 2026-04-04

## Current state

NexusReach is well past the original MVP. The app now supports:
- board-backed ATS search plus exact-job URL ingestion
- high-accuracy `newgrad-jobs.com` detail-page enrichment
- startup-first job discovery plus startup tagging/filtering
- job-aware people discovery
- bounded The Org traversal and slug repair
- LinkedIn backfill for verified public candidates
- same-company contact hierarchy (`direct`, `adjacent`, `next_best`)
- imported LinkedIn graph warm paths in people search
- safe best-guess emails from approved domain signals
- multi-provider search routing with Redis caching
- multi-provider LLM drafting
- saved-contact company filtering across People, Messages, and Outreach

## Latest active branch work

- Current workspace branch: `codex/startup-jobs-feed`
- Latest pushed commit on this branch: `69dccf2`
- This branch adds:
  - `Discover Startup Jobs` on the Jobs page
  - startup filtering through `GET /api/jobs?startup=true`
  - startup badges/source badges on Jobs, Job Detail, and Dashboard
  - startup discovery sources:
    - Y Combinator Jobs
    - VentureLoop
    - Conviction Jobs / Mixture of Experts
    - a16z Speedrun
    - Wellfound as a best-effort client
- Current startup-source caveat:
  - Wellfound still returns live anti-bot `403` pages in this environment, so the client intentionally fails soft to `[]` instead of breaking startup discovery.

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
- `newgrad-jobs.com`:
  - list-page discovery plus detail-page enrichment
  - source-aware experience-level inference for new-grad rows
  - non-ATS dedupe using `source + external_id`, then canonical URL
- Startup-first discovery:
  - direct boards:
    - Y Combinator Jobs
    - VentureLoop
    - Wellfound (best-effort)
  - ecosystem crawls that resolve into ATS/exact-job imports:
    - Conviction Jobs / Mixture of Experts
    - a16z Speedrun
  - startup provenance stored in reserved tags:
    - `startup`
    - `startup_source:<source_key>`

### People discovery
- Search stack:
  - SearXNG as the primary provider for bulk LinkedIn/public discovery
  - Serper and Brave as paid fallbacks
  - Tavily for employment corroboration and fallback public discovery
  - Google CSE as optional legacy fallback
- The Org traversal:
  - resolves trusted org slugs from `public_identity_slugs`
  - validates and repairs stale slugs
  - traverses org/team/person pages with bounded budgets
- LinkedIn backfill:
  - second-pass exact-name/company x-ray for verified The Org/public-web candidates
  - strict name/company/role matching before attaching a profile

### LinkedIn graph warm-path v1
- separate graph storage and sync-run tracking
- settings-driven graph status and sync-session flow
- manual CSV/ZIP import fallback
- local Playwright connector for logged-in browser scraping
- people-search `your_connections` output
- per-person warm-path metadata:
  - `direct_connection`
  - `same_company_bridge`
- bounded warm-path ranking that does not override safety rules

### Jobs UI and dashboard
- Jobs page now supports:
  - `Discover Jobs`
  - `Discover Startup Jobs`
  - country filtering derived from `location`
  - server-backed startup filtering
- Job cards, job detail, dashboard latest jobs, and top opportunities render startup badges when startup tags are present.

### Verification and ranking
- `current_company_verified` is tracked separately from role fit.
- Public verification source writes `public_web`.
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
- SearXNG is the default primary provider.
- Current routing:
  - bulk people: `SearXNG -> Serper -> Brave -> Google CSE`
  - exact LinkedIn backfill: `SearXNG -> Brave -> Serper -> Google CSE`
  - hiring-team search: `SearXNG -> Serper -> Brave`
  - public people: `SearXNG -> Serper -> Brave -> Tavily`
  - employment corroboration: `Tavily -> SearXNG -> Serper -> Brave`
- Redis caches raw search results by query family.

### Public-page retrieval
- Free-first retrieval order:
  - direct `httpx`
  - Crawl4AI
  - Firecrawl optional fallback

### LinkedIn graph sync model
- `Sync Now` creates a short-lived sync session, not LinkedIn OAuth.
- The local connector can:
  - attach to an existing logged-in Chrome session via CDP
  - open a dedicated persistent browser profile and wait for login
- The server stores only normalized connection rows, not browser auth material.

## Important files to understand first

### Backend
- `backend/app/clients/search_router_client.py`
- `backend/app/clients/searxng_search_client.py`
- `backend/app/clients/serper_search_client.py`
- `backend/app/clients/brave_search_client.py`
- `backend/app/clients/tavily_search_client.py`
- `backend/app/clients/theorg_client.py`
- `backend/app/clients/newgrad_jobs_client.py`
- `backend/app/clients/yc_jobs_client.py`
- `backend/app/clients/ventureloop_jobs_client.py`
- `backend/app/clients/conviction_jobs_client.py`
- `backend/app/clients/speedrun_jobs_client.py`
- `backend/app/clients/wellfound_jobs_client.py`
- `backend/app/services/job_service.py`
- `backend/app/services/people_service.py`
- `backend/app/services/linkedin_graph_service.py`
- `backend/app/services/linkedin_graph_browser_sync.py`
- `backend/app/services/employment_verification_service.py`
- `backend/app/services/email_finder_service.py`
- `backend/app/utils/startup_jobs.py`
- `backend/app/utils/company_identity.py`
- `backend/app/utils/job_context.py`
- `backend/scripts/linkedin_graph_connector.py`

### Frontend
- `frontend/src/pages/JobsPage.tsx`
- `frontend/src/pages/JobDetailPage.tsx`
- `frontend/src/pages/DashboardPage.tsx`
- `frontend/src/pages/PeoplePage.tsx`
- `frontend/src/pages/MessagesPage.tsx`
- `frontend/src/pages/OutreachPage.tsx`
- `frontend/src/pages/SettingsPage.tsx`
- `frontend/src/hooks/useJobs.ts`
- `frontend/src/hooks/useLinkedInGraph.ts`
- `frontend/src/lib/jobStartup.ts`
- `frontend/src/types/index.ts`

## Current known limitations

1. Manager precision is still weaker than recruiter and peer precision at large companies.
2. Some company identities still need manual tuning when a short brand overlaps with another company or common first name.
3. Workday support is first-class for exact-job URLs, but live upstream maintenance/outage pages still block import and should fail honestly.
4. LinkedIn backfill intentionally favors precision over recall, so a human may still find a valid LinkedIn that the tool refuses to attach.
5. LinkedIn browser sync has unit coverage but has not yet been validated against every live LinkedIn UI variant; selectors may need follow-up hardening.
6. The dashboard `warm_paths` card still reflects outreach-derived relationships, not imported LinkedIn graph data.
7. Wellfound startup scraping is currently best-effort only; live anti-bot responses can yield zero Wellfound jobs while the other startup sources still work.
8. Startup tagging is source-based only in v1. Generic-source jobs are not inferred to be startup jobs.
9. Startup discovery is still a dedicated manual flow and does not yet participate in hourly saved-search refresh.

## Good regression fixtures

- Zip Ashby roles: ambiguous-company and The Org slug/verification regression
- Whatnot Ashby new-grad roles: recruiter-first early-career discovery
- `newgrad-jobs.com` software/remote/UX fixtures: detail-page enrichment and hidden DOM stripping
- Apple exact-job URLs: first-class proprietary exact-job ingestion
- Fortune Workday role: Fortune Media vs Fortune Brands identity split
- Uber proprietary jobs: generic exact-job ingestion + same-company ranking
- xAI Greenhouse role: hierarchy fallback and safe best-guess email behavior
- LinkedIn graph direct match: imported first-degree connection should outrank equally safe cold results
- LinkedIn graph bridge match: same-company bridge should explain warm path without promoting unsafe candidates
- startup parser fixtures:
  - YC jobs payload
  - VentureLoop results table
  - Conviction `unsortedData`
  - Speedrun companies API
- startup tag merge regression: an ATS job discovered through a startup ecosystem source must reuse the existing row and merge startup tags instead of inserting a duplicate

## Last meaningful verification snapshot

- Backend:
  - `cd backend && ruff check app tests conftest.py`
  - `cd backend && pytest`
- Frontend:
  - `cd frontend && npx eslint .`
  - `cd frontend && npx tsc -b`
  - `cd frontend && npm run test`
  - `cd frontend && npm run build`

The most recent targeted passes also covered:
- LinkedIn graph API/service tests
- LinkedIn graph browser-sync helper tests
- Settings-page LinkedIn graph UI tests
- startup jobs:
  - `cd backend && pytest -q tests/test_startup_jobs_clients.py tests/test_startup_job_discovery.py tests/test_jobs_api.py tests/test_newgrad_job_ingestion.py tests/test_job_service_ats.py`
  - `cd frontend && npx vitest run src/lib/jobStartup.test.ts src/pages/__tests__/JobsPage.test.tsx src/pages/__tests__/DashboardPage.test.tsx`
  - live sanity checks:
    - YC returned real jobs
    - VentureLoop returned real jobs
    - Conviction returned real startup companies/links
    - a16z Speedrun returned real startup companies
    - Wellfound returned live `403` and failed soft to zero jobs

## Suggested next product-level improvements

1. Decide on the production-grade Wellfound path: stronger browser retrieval, sanctioned feed, or removal from the v1 source list.
2. Decide whether startup sources should remain manual-only or join saved-search/hourly refresh behavior.
3. Add a separate “venture-backed” taxonomy before bringing in broader VC portfolio boards like Sequoia, Accel, and General Catalyst.
4. Harden the LinkedIn browser sync flow against more live DOM and challenge variations.
5. Thread warm-path context into drafting suggestions without changing the no-auto-send rule.
