# NexusReach — AI Agent Context

Last updated: 2026-06-11

This file is the current AI-facing project snapshot for NexusReach. It is intended for Codex, Claude, and other repo-aware assistants. `CLAUDE.md` intentionally mirrors the same project story so different tools inherit the same context.

## What this product is

NexusReach is a networking assistant for job seekers. It helps a user:
- import or discover relevant jobs
- find recruiters, hiring-side contacts, and peers at the target company
- recover LinkedIn/public profile evidence for those people
- surface warm paths from the user's imported first-degree LinkedIn graph
- find or guess work emails safely
- draft outreach messages, stage email drafts, and optionally auto-send staged email drafts after a user-configured delay
- track networking activity in a lightweight CRM

NexusReach defaults to draft-first workflows. Users can optionally enable delayed auto-send for staged email drafts and cancel scheduled sends before they go out.

## Current product snapshot

### Jobs and company intake
- Job aggregation exists for JSearch, Adzuna, Dice, remote/public boards, curated GitHub job lists, and `newgrad-jobs.com`.
- `newgrad-jobs.com` ingestion is now two-stage:
  - list-page discovery for title/company/date/URL
  - detail-page enrichment for location, employment type, work mode, salary, level label, and description
- Board-backed ATS support exists for:
  - Greenhouse
  - Lever
  - Ashby
- Exact-job URL ingestion exists for:
  - Workable
  - Apple Jobs
  - Workday exact-job URLs on `*.myworkdayjobs.com`
  - generic exact-job hosts when metadata is parseable
- Proprietary careers pages can import through the exact-job pipeline when the page exposes enough metadata. In practice this is how some Microsoft and Uber roles are handled.
- Startup-first discovery now exists as a separate manual flow:
  - direct startup boards:
    - Y Combinator Jobs
    - VentureLoop
    - Wellfound (best-effort; may fail soft when blocked)
  - startup ecosystems that resolve to ATS/exact-job imports:
    - Conviction Jobs / Mixture of Experts
    - a16z Speedrun companies
- Startup provenance is source-based only in v1 and stored in reserved job tags:
  - `startup`
  - `startup_source:<source_key>`
- Job import now canonicalizes URLs and dedupes by `source + external_id` first, then canonical URL, then fingerprint.
- Job discovery is occupation-aware. The curated ATS boards are all tech employers and Dice/Simplify/newgrad lean tech, so when a discover run resolves to occupations that are *all* industry-bound non-tech (healthcare, education/training, legal/compliance, public-sector/government, arts/entertainment), `discover_jobs` routes only to the broad all-industry aggregators (JSearch / Adzuna / Remotive) and skips the tech-only sources. Cross-industry occupations (sales, marketing, finance, ...) keep the full source set because those seekers may target tech companies (`job_service.INDUSTRY_BOUND_NONTECH_OCCUPATIONS` / `_suppress_tech_sources`).
- Curated **non-tech vertical boards** are the employer-list analog of the tech ATS boards: `workday_client.WORKDAY_NONTECH_COMPANIES` is a live-verified registry of large Workday employers tagged by vertical (`healthcare` health systems, `education` universities, `finance` banks/insurers, `retail` retailers). `job_service.OCCUPATION_VERTICALS` / `verticals_for_occupations` route an occupation to the verticals that actually hire it (nursing → health systems, finance → banks, sales/support → finance+retail, supply chain → retail; engineering and unmapped occupations pull none). `discover_jobs` calls `_discover_nontech_vertical_boards` additively — it fires whenever the resolved occupations have a vertical home, *independent* of the tech-suppression decision (a finance seeker isn't suppressed but still gets banks; a nurse is suppressed and still gets hospitals). The hourly refresh (`tasks/jobs._discover_all_boards`) folds every non-tech employer into the `workday:curated` payload, so saved-search matching keeps non-tech jobs fresh the same way it does Stripe/OpenAI for engineers. Every Workday config (`wd` tier + `site`) is verified against the live jobs API — a wrong value silently returns nothing, so do not add unverified employers.

### People discovery
- People discovery is no longer Apollo-only.
- Current discovery stack is:
  1. Apollo company/org enrichment where available
  2. search-provider router for web/LinkedIn discovery
  3. hiring-team search
  4. bounded The Org traversal when buckets underfill or the company is ambiguous
  5. LinkedIn backfill for verified The Org/public-web candidates
- The People page and job-aware people flow return three buckets:
  - recruiters
  - hiring managers
  - peers
- An occupation gate (`app/services/people/occupation_gate.py`) rejects candidates whose function clearly differs from the job's (e.g. an Engineering Manager surfaced by x-ray for a sales req) from the hiring-manager and peer buckets — coarse function groups (technical / gtm / corporate / creative / domain) so adjacent functions still pass; pre-validated contacts (posting/hiring-team/github-team) bypass all heuristic gates. For known non-engineering occupations, manager/peer/recruiter title seeds come from the occupation taxonomy (not engineering scaffolding) and engineering-flavored team keywords are dropped, so a sales role searches for sales people.
- Two non-technical leadership sources fill the gap where GitHub does not apply: the company's own website leadership/team page (`app/services/people/company_site.py` — probe common paths, LLM-extract named leaders+titles, cached/fail-soft; the non-tech analog of GitHub-team and the highest-recall source for the long tail The Org misses) executives quoted by exact title in news/PR (`tavily_search_client.search_executive_quotes`), and leaders found via speaker/podcast/byline mentions and X/Twitter bios (`app/services/people/public_footprint.py`). The company-site parser also probes domain people-directories (/attorneys, /faculty, /providers, ...) and uses SERP-assisted page discovery; it works on server-rendered sites and fails soft on JS-rendered SPAs (where the SERP-based news/footprint miners cover instead). Both are company-verified (own domain / press), run for non-engineering roles, route into the hiring-manager bucket through the occupation gate, and rank just below team-confirmed contacts.
- People discovery additionally mines the posting itself (named contact emails rank first; reporting-line titles seed the HM search), searches LinkedIn feed posts for the recruiter who announced the exact req, annotates shared school/past-employer affinity from the user resume, applies bounded reply-rate priors from the user own outreach history, and accepts contact feedback that evicts bad known-people cache rows.
- For engineering roles at companies with public repos, the GitHub-team strategy (`app/services/people/github_team.py`) resolves the recent contributors to the org repos matching the job team keywords into LinkedIn titles: lead/manager-titled, company-evidenced contributors become hiring-manager candidates, the rest become high-confidence peers on GitHub evidence alone. GitHub-team membership is the strongest signal in the hiring-manager and peer rankings. Org slug is derived from the company name and validated via the GitHub API (cached). Recency-ranked (recent commits, not all-time) so departed heavy committers do not surface; former-employee and wrong-person LinkedIn matches are filtered.
- The companion can capture LinkedIn's "Meet the hiring team" panel from a job page the user is viewing (`POST /api/people/hiring-team-capture`, `app/services/people/hiring_team_capture.py`): the named req owners are stored as `verified` contacts in the recruiter/hiring-manager buckets and cached for the company. A hiring-team-captured contact is the single top signal in the recruiter and hiring-manager rankings — above the GitHub-team lead — because LinkedIn itself attached them to the exact posting. Covers every role type, including non-engineering and private-repo companies the GitHub strategy cannot.
- Hiring-manager ranking is startup-aware: when the job carries the reserved `startup` tag, verification tier and founder/C-level status outrank manager-title-seed alignment (at small companies the verified founder is the hiring manager); non-startup searches keep title fit on top.
- Results are ranked as a same-company hierarchy:
  - `direct`
  - `adjacent`
  - `next_best`
- Result quality and company confidence are separate concepts:
  - `match_quality` = role/team closeness
  - `company_match_confidence` = verified vs strong/weak company signal

### LinkedIn graph and warm paths
- LinkedIn graph data is user-scoped and stored separately from saved CRM `Person` rows.
- The new graph subsystem persists:
  - `linkedin_graph_connections`
  - `linkedin_graph_sync_runs`
- Settings now supports two graph inputs:
  - manual LinkedIn connections CSV/ZIP import
  - short-lived sync session for a local browser connector
- The local connector can:
  - attach to an already logged-in Chrome session via CDP
  - open a dedicated persistent browser profile and wait for the user to log into LinkedIn once
  - scrape first-degree LinkedIn connection cards locally with Playwright
  - upload only normalized connection rows back to the API
- The server does not store LinkedIn cookies, OAuth tokens, or credentials.
- People search now returns:
  - `your_connections`
  - per-person `warm_path_type`
  - per-person `warm_path_reason`
  - per-person `warm_path_connection`
- Warm-path boosts are bounded:
  - they only reorder already-safe candidates
  - they do not override ambiguous-company protections
  - they do not bypass `current_company_verified` / `company_match_confidence`
  - they do not change email trust rules
- Dashboard `warm_paths` unifies imported LinkedIn graph paths with outreach-derived paths (`insights_service`). Imported graph data also powers people-search ranking and explanation.

### Search-provider routing
- SearXNG is the default primary search provider (free, self-hosted, unlimited).
- Brave and Serper are retained as paid fallbacks if re-funded.
- Current router behavior:
  - bulk LinkedIn people discovery: `SearXNG -> Serper -> Brave -> Google CSE`
  - exact LinkedIn backfill: `SearXNG -> Brave -> Serper -> Google CSE`
  - hiring-team search: `SearXNG -> Serper -> Brave`
  - public-web people discovery: `SearXNG -> Serper -> Brave -> Tavily`
  - employment corroboration: `Tavily -> SearXNG -> Serper -> Brave`
- Raw provider results are cached in Redis for 24 hours by normalized query family.
- Provider/debug metadata is stored in `profile_data` or result metadata:
  - `search_provider`
  - `search_query_family`
  - `search_fallback_depth`
  - `search_cache_hit`

### Public-page retrieval and The Org
- Public-page retrieval is free-first:
  - direct `httpx`
  - Crawl4AI
  - Firecrawl only if configured
- Firecrawl is optional fallback infrastructure, not a hard dependency.
- The Org parsing has an HTML fallback: when the legacy `next_data` payload is empty (current TheOrg pages), `parse_org_page` recovers the leadership roster from the JSON-LD `Organization.employee[]` array, and `resolve_reporting_managers` reads the inline `LightPosition` graph (role + `parentPositionId`) to surface a role's direct manager and same-function managers. This is the primary hiring-manager source for non-engineering roles (where public-web x-ray returns only engineers); The Org traversal now always runs for known non-engineering occupations.
- The Org traversal is implemented and bounded:
  - org page resolution from trusted `public_identity_slugs`
  - company/team/person page parsing
  - recruiter, manager, and peer harvesting
  - cache + slug repair in `Company.identity_hints["theorg"]`
- The Org person/team URLs can verify current company, but that trust does not automatically trust an email domain.

### Email behavior
- Email lookup uses a waterfall and stops early on the first strong result.
- Best-guess emails are allowed again, but only from approved domain signals:
  - trusted company domain
  - official careers/site host
  - learned same-company pattern
- Ambiguous-company protections still block unsafe guesses.
- Public identity trust and email-domain trust are intentionally separate.
- Staged drafts and sent mail are reconciled against the provider on a 30-minute beat: drafts sent from the Gmail/Outlook UI flip to `sent`, and thread replies flip `sent` to `responded` (with notification + `outreach_reply_received` analytics event) for up to 45 days after send.
- Reply reconciliation captures `replied_at` and a plain-text `last_reply_snippet` on the outreach log; drafting automatically switches to respond-to-their-reply mode when a contact has replied, and the reply snippet is exposed through the outreach API.
- Gmail and Outlook refresh tokens are encrypted at rest with versioned app keys.
- Legacy plaintext OAuth tokens are cleared by migration and require reconnect.

### Message drafting
- Message drafting supports multiple providers through `llm_client.py`.
- Supported `NEXUSREACH_LLM_PROVIDER` values:
  - `anthropic`
  - `openai`
  - `gemini`
  - `groq`
- The drafting flow is draft-first by default, with optional delayed auto-send for staged email drafts when the user explicitly enables it.
- The weekly cadence digest can pre-draft due follow-ups (`cadence_auto_draft_enabled`, opt-in, capped at 3 LLM drafts per digest); drafts are attached to next actions and never sent automatically.
- Warm-path context (type, reason, connection) is threaded into drafting and shown on draft cards.

### Frontend state and UX
- Saved contacts are grouped by company on the People page.
- Jobs now has separate `Discover Jobs` and `Discover Startup Jobs` actions.
- Jobs now has:
  - a server-backed `Startup` filter
  - a client-side country filter derived from `location`
  - startup badges and startup-source labels on cards and detail views
- Dashboard latest jobs and top opportunities now show startup badges/source labels when startup tags are present.
- Saved-contact company filters now exist on:
  - People
  - Messages
  - Outreach
- Saved contacts are hidden while a live people search is pending to avoid cross-company confusion.
- People search can show:
  - a `Your Connections at {company}` section above the live buckets
  - warm-path badges and explanations on cold contacts
- Contact cards now show proof for why the person matched, why the company is trusted, why the email is safe, and whether a warm path exists.
- Dashboard now has a guided first-win path from job to contact to draft to staged inbox draft.
- Dashboard outcome metrics now include contacts found, verified emails, warm paths, drafts created, staged drafts, replies, and interviews.
- Settings includes a LinkedIn Graph card with:
  - sync status
  - last sync time
  - `Sync Now`
  - `Upload Export`
  - `Clear Graph Data`
  - generated local connector commands for CDP or dedicated-profile browser sync
- Settings includes Account Data controls for JSON export and permanent account deletion.
- Public `/privacy` and `/terms` routes exist for launch compliance.
- Frontend Sentry and PostHog initialize only when configured. PostHog autocapture
  and session recording are disabled by default.

## Tech stack

### Frontend
- React 19 + TypeScript
- Vite
- React Router
- TanStack Query
- Zustand
- Tailwind CSS
- shadcn/ui built on `@base-ui/react`

### Backend
- Python 3.12+
- FastAPI
- SQLAlchemy + Alembic
- PostgreSQL
- Redis
- Celery
- Pydantic v2

### External services in the live architecture
- Supabase: auth + hosted Postgres
- Apollo: company/org enrichment, optional person enrichment
- SearXNG: primary free search provider (self-hosted, unlimited)
- Serper: fallback bulk SERP provider (paid)
- Brave Search: fallback search (paid)
- Tavily: employment corroboration + fallback public discovery
- Google CSE: optional legacy fallback (100 free/day)
- Proxycurl: LinkedIn enrichment
- Hunter: email finder + verifier
- GitHub API: engineer/public profile context
- Crawl4AI / Firecrawl: public-page retrieval fallback stack
- Gmail API / Microsoft Graph: draft staging

### Production deployment target
- Vercel serves the frontend from the `frontend` project root.
- Railway runs three backend services from `backend`:
  - FastAPI web service using `backend/railway.web.toml`
  - Celery worker using `backend/railway.worker.toml`
  - Celery beat using `backend/railway.beat.toml`
- Supabase provides hosted Postgres and auth.
- Railway Redis is shared by Celery, search cache, and rate-limit storage.
- SearXNG runs on Railway or another private reachable host.
- `backend/Dockerfile` is the production backend runtime and installs TeX Live for `pdflatex` resume PDF generation.
- `DEPLOYMENT_RUNBOOK.md` is the source of truth for deploy order, secrets, smoke checks, alerts, and rollback.

### Local helper tooling
- Playwright is used by the LinkedIn graph browser connector (`backend/scripts/linkedin_graph_connector.py`).

## Project structure

```text
NexusReach/
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── lib/
│   │   ├── pages/
│   │   ├── stores/
│   │   └── types/
├── backend/
│   ├── app/
│   │   ├── clients/
│   │   │   └── ats/
│   │   ├── models/
│   │   ├── routers/
│   │   ├── schemas/
│   │   ├── services/
│   │   │   ├── linkedin_graph/
│   │   │   ├── people/
│   │   │   └── resume_artifact/
│   │   ├── tasks/
│   │   └── utils/
│   ├── alembic/
│   ├── scripts/
│   └── tests/
├── PRD.md
├── architecture.md
├── PLAN.md
├── HANDOFF.md
├── lessons.md
├── README.md
├── AGENTS.md
└── CLAUDE.md
```

## Coding conventions

### Python
- Use `async` service and router code where appropriate.
- Keep routers thin and services responsible for business logic.
- Put external integrations in `backend/app/clients`.
- Use typed signatures everywhere.
- Avoid bare `except`.
- Keep environment reads in `backend/app/config.py`.

### TypeScript
- Functional components only.
- TanStack Query for server-state access.
- Zustand for client-only state.
- No `any`.
- Shared types belong in `frontend/src/types`.

### Data boundaries
- All user data must remain scoped by `user_id`.
- Never treat cross-company public results as safe fallback contacts.
- Company verification, role ranking, and email trust are separate axes.
- Imported LinkedIn graph rows must remain separate from saved CRM contacts.

## Key commands

```bash
# Frontend
cd frontend && npm install
cd frontend && npm run dev
cd frontend && npx eslint .
cd frontend && npx tsc -b
cd frontend && npm run test
cd frontend && npm run build

# Backend
cd backend && pip install -r requirements.txt
cd backend && uvicorn app.main:app --reload
cd backend && alembic upgrade head
cd backend && ruff check app tests conftest.py
cd backend && pytest
cd backend && celery -A app.tasks worker --loglevel=info
cd backend && celery -A app.tasks beat --loglevel=info

# Real browser E2E
cd e2e && npm install
cd e2e && npx playwright install chromium
cd e2e && npm run test:real

# LinkedIn graph local connector
cd backend && python scripts/linkedin_graph_connector.py --help
```

## Environment variables

### Backend
```env
NEXUSREACH_DATABASE_URL=postgresql+asyncpg://...
NEXUSREACH_REDIS_URL=redis://...
NEXUSREACH_SUPABASE_URL=https://...
NEXUSREACH_SUPABASE_KEY=...
NEXUSREACH_SUPABASE_SERVICE_ROLE_KEY=...
NEXUSREACH_SUPABASE_JWT_SECRET=...
NEXUSREACH_AUTH_MODE=supabase
NEXUSREACH_DEV_AUTH_BYPASS_ENABLED=false
NEXUSREACH_DEV_USER_ID=00000000-0000-0000-0000-000000000001
NEXUSREACH_DEV_USER_EMAIL=dev@nexusreach.local
NEXUSREACH_APP_RELEASE=...
NEXUSREACH_SENTRY_DSN=...
NEXUSREACH_SENTRY_TRACES_SAMPLE_RATE=0.05
NEXUSREACH_SENTRY_PROFILES_SAMPLE_RATE=0.0
NEXUSREACH_TOKEN_ENCRYPTION_PRIMARY_VERSION=v1
NEXUSREACH_TOKEN_ENCRYPTION_KEYS={"v1":"..."}

NEXUSREACH_APOLLO_API_KEY=...
NEXUSREACH_APOLLO_MASTER_API_KEY=...
NEXUSREACH_PROXYCURL_API_KEY=...
NEXUSREACH_HUNTER_API_KEY=...
NEXUSREACH_HUNTER_PATTERN_MONTHLY_BUDGET=25
NEXUSREACH_GITHUB_TOKEN=...
NEXUSREACH_JSEARCH_API_KEY=...
NEXUSREACH_ADZUNA_APP_ID=...
NEXUSREACH_ADZUNA_API_KEY=...

NEXUSREACH_ANTHROPIC_API_KEY=...
NEXUSREACH_OPENAI_API_KEY=...
NEXUSREACH_GOOGLE_API_KEY=...
NEXUSREACH_GOOGLE_CSE_ID=...
NEXUSREACH_GROQ_API_KEY=...
NEXUSREACH_LLM_PROVIDER=anthropic

NEXUSREACH_SEARXNG_BASE_URL=http://localhost:8888
NEXUSREACH_BRAVE_API_KEY=...
NEXUSREACH_SERPER_API_KEY=...
NEXUSREACH_TAVILY_API_KEY=...
NEXUSREACH_SEARCH_CACHE_TTL_SECONDS=86400
NEXUSREACH_SEARCH_LINKEDIN_PROVIDER_ORDER=searxng,serper,brave,google_cse
NEXUSREACH_SEARCH_EXACT_LINKEDIN_PROVIDER_ORDER=searxng,brave,serper,google_cse
NEXUSREACH_SEARCH_HIRING_TEAM_PROVIDER_ORDER=searxng,serper,brave
NEXUSREACH_SEARCH_PUBLIC_PROVIDER_ORDER=searxng,serper,brave,tavily
NEXUSREACH_SEARCH_EMPLOYMENT_PROVIDER_ORDER=tavily,searxng,serper,brave

NEXUSREACH_FIRECRAWL_BASE_URL=
NEXUSREACH_FIRECRAWL_API_KEY=
NEXUSREACH_THEORG_TRAVERSAL_ENABLED=true
NEXUSREACH_THEORG_CACHE_TTL_HOURS=24
NEXUSREACH_THEORG_MAX_TEAM_PAGES=3
NEXUSREACH_THEORG_MAX_MANAGER_PAGES=3
NEXUSREACH_THEORG_MAX_HARVESTED_PEOPLE=25
NEXUSREACH_THEORG_TIMEOUT_SECONDS=20

NEXUSREACH_GOOGLE_CLIENT_ID=...
NEXUSREACH_GOOGLE_CLIENT_SECRET=...
NEXUSREACH_MICROSOFT_CLIENT_ID=...
NEXUSREACH_MICROSOFT_CLIENT_SECRET=...

NEXUSREACH_EMPLOYMENT_VERIFY_TOP_N=10
NEXUSREACH_EMPLOYMENT_VERIFY_TIMEOUT_SECONDS=20
NEXUSREACH_EMPLOYMENT_VERIFY_ENABLED=true

NEXUSREACH_LINKEDIN_GRAPH_SYNC_SESSION_TTL_SECONDS=900
NEXUSREACH_LINKEDIN_GRAPH_MAX_IMPORT_BATCH_SIZE=250
```

### Frontend
```env
VITE_API_URL=http://localhost:8000
VITE_AUTH_MODE=supabase
VITE_DEV_AUTH_BYPASS_ENABLED=false
VITE_SUPABASE_URL=https://...
VITE_SUPABASE_ANON_KEY=...
VITE_APP_ENVIRONMENT=development
VITE_APP_RELEASE=...
VITE_SENTRY_DSN=...
VITE_SENTRY_TRACES_SAMPLE_RATE=0.05
VITE_SENTRY_REPLAYS_SESSION_SAMPLE_RATE=0
VITE_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE=1
VITE_POSTHOG_KEY=...
VITE_POSTHOG_HOST=https://us.i.posthog.com
VITE_ANALYTICS_ENABLED=true
```

## Critical implementation truths

1. `backend/.env` is loaded relative to the current working directory. Running scripts from the repo root can miss backend config.
2. Apollo free-tier company endpoints are useful; person search is still not something to depend on blindly.
3. SearXNG is the default primary search provider (free, self-hosted). It queries a local SearXNG instance via JSON API.
4. Brave and Serper are retained as paid fallbacks but are no longer the default primary providers.
5. Tavily is primarily for employment corroboration and fallback public-web discovery, not main LinkedIn x-ray.
6. Firecrawl is optional and should be treated as a last-resort page-fetch provider.
7. The Org slug resolution must validate real org pages. Do not assume the first slug candidate is correct.
8. `current_company_verified` is separate from `match_quality`. A person can be a `next_best` contact and still be a verified current employee.
9. Best-guess emails are acceptable only with safe domain evidence. Ambiguous brands like Zip should still withhold unsafe guesses.
10. Workday exact-job support is honest about upstream outages. Maintenance pages should fail cleanly, not import the wrong landing page.
11. `firecrawl_public_web` is fully legacy: no code path writes it anymore. Firecrawl is now only an optional page-fetch fallback and never labels its own results. The value survives only in the frontend `Person.current_company_verification_source` union for backwards-compatible reads of old rows.
12. shadcn/ui in this repo uses `@base-ui/react`, not Radix. No `asChild`, no Radix-specific dialog props.
13. Run `ruff check app tests conftest.py`, not just `ruff check app`.
14. Testing Library queries on this codebase often need role-based selectors because duplicated text is common.
15. SQLAlchemy forward references like `Mapped["Person"]` still need `# noqa: F821` in model files.
16. The global error handler returns `{"error": {"code", "message"}}`, not FastAPI's default `{"detail": ...}`.
17. Vitest utilities should still be imported explicitly for portability.
18. Always inspect `frontend/src/components/ui/*.tsx` before assuming shadcn prop support from external examples.
19. Imported LinkedIn graph data must remain separate from `Person` CRM rows and from dashboard outreach-derived `warm_paths`.
20. `Sync Now` on Settings is not LinkedIn OAuth. It creates a short-lived sync session for the local browser connector.
21. The server must never store LinkedIn cookies, session tokens, or credentials. Only normalized connection rows are uploaded.
22. Warm-path ranking boosts cannot bless unsafe candidates. They operate only within already-safe same-company results.
23. The local browser connector requires Playwright locally and can either attach to Chrome over CDP or use a dedicated persistent browser profile.
24. `newgrad_jobs` now behaves like a first-class non-ATS source: enrich detail pages inline, derive `remote` from the detail-page work-mode signal, and dedupe by `source + external_id` / canonical URL instead of ATS-only assumptions.
25. Startup state is tag-based, not schema-based. Reserved tags are `startup` and `startup_source:<source_key>`.
26. `POST /api/jobs/discover` supports `mode: "default" | "startup"`. Startup-mode saved searches participate in the hourly feed refresh via `run_startup_refresh_for_query`.
27. Startup ecosystem imports must preserve the underlying `source` / `ats` from the resolved posting while merging startup provenance into `job.tags` on dedupe.
28. Wellfound is intentionally best-effort right now. Live fetches can return `403` anti-bot pages and should fail soft to `[]` rather than breaking startup discover.
29. `auth_mode=dev` is fail-closed unless `NEXUSREACH_DEV_AUTH_BYPASS_ENABLED=true`; the frontend has the same explicit `VITE_DEV_AUTH_BYPASS_ENABLED=true` guard.
30. Real E2E uses `VITE_AUTH_MODE=e2e` with a Supabase-compatible JWT, boots backend/frontend on isolated ports, drops and recreates `nexusreach_e2e`, and runs Alembic from zero before the browser test.
31. `people_service.py`, `ats_client.py`, `resume_artifact_service.py`, and `linkedin_graph_service.py` are compatibility shims. The implementations live in `app/services/people/`, `app/clients/ats/`, `app/services/resume_artifact/`, and `app/services/linkedin_graph/` as layered packages (each module imports only from layers below it). New code should import from the packages, not the shims.
32. Frontend types live in domain files under `frontend/src/types/` (`jobs.ts`, `people.ts`, `messages.ts`, ...); `types/index.ts` is a barrel re-export, so `@/types` imports keep working. Beware DOM-global name shadowing when adding types (e.g. `MessageChannel`, `Notification`): a missing cross-file type import resolves silently to the DOM type instead of erroring.

## Pre-commit checklist

```bash
cd backend && ruff check app tests conftest.py
cd backend && pytest
cd frontend && npx eslint .
cd frontend && npx tsc -b
cd frontend && npm run test
cd frontend && npm run build
cd e2e && npm run test:real
```
