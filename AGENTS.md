# NexusReach — AI Agent Context

Last updated: 2026-03-22

This file is the current AI-facing project snapshot for NexusReach. It is intended for Codex, Claude, and other repo-aware assistants. `CLAUDE.md` intentionally mirrors the same project story so different tools inherit the same context.

## What this product is

NexusReach is a networking assistant for job seekers. It helps a user:
- import or discover relevant jobs
- find recruiters, hiring-side contacts, and peers at the target company
- recover LinkedIn/public profile evidence for those people
- find or guess work emails safely
- draft outreach messages and stage email drafts
- track networking activity in a lightweight CRM

The human is always in the loop. Nothing is ever sent automatically.

## Current product snapshot

### Jobs and company intake
- Job aggregation exists for JSearch, Adzuna, Dice, remote/public boards, and curated GitHub job lists.
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
- Exact-job import canonicalizes URLs, dedupes by `ats + external_id` first, then canonical URL, then fingerprint.

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
- Results are ranked as a same-company hierarchy:
  - `direct`
  - `adjacent`
  - `next_best`
- Result quality and company confidence are separate concepts:
  - `match_quality` = role/team closeness
  - `company_match_confidence` = verified vs strong/weak company signal

### Search-provider routing
- Brave is still used, but it is no longer the default bulk search engine.
- Current router behavior:
  - bulk LinkedIn people discovery: `Serper -> Brave -> Google CSE`
  - exact LinkedIn backfill: `Brave -> Serper -> Google CSE`
  - hiring-team search: `Serper -> Brave`
  - public-web people discovery: `Serper -> Brave -> Tavily`
  - employment corroboration: `Tavily -> Serper -> Brave`
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

### Message drafting
- Message drafting supports multiple providers through `llm_client.py`.
- Supported `NEXUSREACH_LLM_PROVIDER` values:
  - `anthropic`
  - `openai`
  - `gemini`
  - `groq`
- The drafting flow still follows the same product rule: generate only drafts, never send automatically.

### Frontend state and UX
- Saved contacts are grouped by company on the People page.
- Saved-contact company filters now exist on:
  - People
  - Messages
  - Outreach
- Saved contacts are hidden while a live people search is pending to avoid cross-company confusion.

## Tech stack

### Frontend
- React 18 + TypeScript
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
- Serper: primary bulk SERP provider
- Brave Search: exact LinkedIn backfill + fallback search
- Tavily: employment corroboration + fallback public discovery
- Google CSE: optional legacy fallback
- Proxycurl: LinkedIn enrichment
- Hunter: email finder + verifier
- GitHub API: engineer/public profile context
- Crawl4AI / Firecrawl: public-page retrieval fallback stack
- Gmail API / Microsoft Graph: draft staging

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
│   │   ├── models/
│   │   ├── routers/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── tasks/
│   │   └── utils/
│   ├── alembic/
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
```

## Environment variables

### Backend
```env
NEXUSREACH_DATABASE_URL=postgresql+asyncpg://...
NEXUSREACH_REDIS_URL=redis://...
NEXUSREACH_SUPABASE_URL=https://...
NEXUSREACH_SUPABASE_KEY=...
NEXUSREACH_SUPABASE_JWT_SECRET=...
NEXUSREACH_AUTH_MODE=supabase
NEXUSREACH_DEV_USER_ID=00000000-0000-0000-0000-000000000001
NEXUSREACH_DEV_USER_EMAIL=dev@nexusreach.local

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

NEXUSREACH_BRAVE_API_KEY=...
NEXUSREACH_SERPER_API_KEY=...
NEXUSREACH_TAVILY_API_KEY=...
NEXUSREACH_SEARCH_CACHE_TTL_SECONDS=86400
NEXUSREACH_SEARCH_LINKEDIN_PROVIDER_ORDER=serper,brave,google_cse
NEXUSREACH_SEARCH_EXACT_LINKEDIN_PROVIDER_ORDER=brave,serper,google_cse
NEXUSREACH_SEARCH_HIRING_TEAM_PROVIDER_ORDER=serper,brave
NEXUSREACH_SEARCH_PUBLIC_PROVIDER_ORDER=serper,brave,tavily
NEXUSREACH_SEARCH_EMPLOYMENT_PROVIDER_ORDER=tavily,serper,brave

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
```

### Frontend
```env
VITE_API_URL=http://localhost:8000
VITE_SUPABASE_URL=https://...
VITE_SUPABASE_ANON_KEY=...
```

## Critical implementation truths

1. `backend/.env` is loaded relative to the current working directory. Running scripts from the repo root can miss backend config.
2. Apollo free-tier company endpoints are useful; person search is still not something to depend on blindly.
3. Brave is intentionally preserved for exact LinkedIn backfill, not bulk search.
4. Serper is now the default bulk LinkedIn/public people provider.
5. Tavily is primarily for employment corroboration and fallback public-web discovery, not main LinkedIn x-ray.
6. Firecrawl is optional and should be treated as a last-resort page-fetch provider.
7. The Org slug resolution must validate real org pages. Do not assume the first slug candidate is correct.
8. `current_company_verified` is separate from `match_quality`. A person can be a `next_best` contact and still be a verified current employee.
9. Best-guess emails are acceptable only with safe domain evidence. Ambiguous brands like Zip should still withhold unsafe guesses.
10. Workday exact-job support is honest about upstream outages. Maintenance pages should fail cleanly, not import the wrong landing page.
11. Legacy `firecrawl_public_web` values still exist in stored data, but new verification writes should use `public_web`.
12. shadcn/ui in this repo uses `@base-ui/react`, not Radix. No `asChild`, no Radix-specific dialog props.
13. Run `ruff check app tests conftest.py`, not just `ruff check app`.
14. Testing Library queries on this codebase often need role-based selectors because duplicated text is common.
15. SQLAlchemy forward references like `Mapped["Person"]` still need `# noqa: F821` in model files.
16. The global error handler returns `{"error": {"code", "message"}}`, not FastAPI's default `{"detail": ...}`.
17. Vitest utilities should still be imported explicitly for portability.
18. Always inspect `frontend/src/components/ui/*.tsx` before assuming shadcn prop support from external examples.

## Pre-commit checklist

```bash
cd backend && ruff check app tests conftest.py
cd backend && pytest
cd frontend && npx eslint .
cd frontend && npx tsc -b
cd frontend && npm run test
cd frontend && npm run build
```
