# NexusReach

NexusReach is a networking assistant for job seekers. It helps a user move from a job posting or target company to actual people, usable outreach drafts, and a lightweight networking CRM.

The product is designed around one rule: the human is always in the loop. NexusReach can discover, rank, enrich, verify, and draft, but it never sends outreach automatically.

## What it does today

### Job intake
- search broad job aggregators and curated sources
- import board-backed ATS jobs from Greenhouse, Lever, and Ashby
- import exact-job URLs from:
  - Workable
  - Apple Jobs
  - Workday
  - metadata-rich proprietary careers pages through the generic exact-job pipeline

### People discovery
- find recruiters, hiring managers, and peers for a company or saved job
- run job-aware title generation from the job description
- use a same-company ranking hierarchy:
  - `Direct`
  - `Adjacent`
  - `Next Best`
- enrich and verify people using LinkedIn/public-web evidence, not just one provider

### Public discovery stack
- Apollo for company/org enrichment where useful
- Serper as the primary bulk search provider
- Brave Search retained for exact LinkedIn backfill and fallback
- Tavily for employment corroboration and fallback public discovery
- The Org traversal for trusted org-chart discovery
- Redis-backed search query caching to reduce repeated provider spend

### Email and outreach
- find verified emails when possible
- return clearly labeled best-guess emails when the domain signal is safe enough
- stage drafts in Gmail or Outlook
- generate LinkedIn and email outreach drafts with multiple LLM providers

### CRM and UX
- track outreach statuses and notes
- filter saved contacts by company on People, Messages, and Outreach
- keep contacts linked back to the jobs and companies that produced them

## Current architecture highlights

- **Frontend:** React 18, TypeScript, Vite, React Router, TanStack Query, Zustand, Tailwind, shadcn/ui
- **Backend:** FastAPI, SQLAlchemy, Alembic, PostgreSQL, Redis, Celery, Pydantic v2
- **LLMs:** Anthropic, OpenAI, Gemini, or Groq through a shared provider abstraction
- **Search routing:** Serper, Brave, Tavily, optional Google CSE, Redis cache
- **Public page retrieval:** direct `httpx`, then Crawl4AI, then optional Firecrawl

## Supported job posting flows

### Board-backed ATS
- Greenhouse
- Lever
- Ashby

### Exact-job ingestion
- Workable
- Apple Jobs
- Workday exact-job URLs on `*.myworkdayjobs.com`
- generic exact-job hosts when canonical metadata is parseable

## People discovery model

NexusReach does not rely on one provider to find people. The current pipeline is:

1. normalize and enrich the target company
2. generate recruiter, manager, and peer title families from the job context
3. search via the provider router
4. expand with The Org when buckets underfill or the company is ambiguous
5. verify current company using LinkedIn/public-web evidence
6. backfill LinkedIn profiles for verified The Org/public candidates
7. rank results as `direct`, `adjacent`, or `next_best`

## Email behavior

Email results can come back as:
- `verified`
- `best_guess`
- `not_found`

Best guesses are only returned when the domain source is approved, such as:
- a trusted domain
- an official careers/site host
- a learned same-company email pattern

Ambiguous brands and unsafe domains are still blocked from guessing.

## Repository structure

```text
NexusReach/
├── frontend/
│   └── src/
│       ├── components/
│       ├── hooks/
│       ├── lib/
│       ├── pages/
│       ├── stores/
│       └── types/
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
├── AGENTS.md
└── CLAUDE.md
```

## Local setup

### Prerequisites
- Node.js 20+
- Python 3.12+
- PostgreSQL
- Redis

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Optional workers

```bash
cd backend
celery -A app.tasks worker --loglevel=info
celery -A app.tasks beat --loglevel=info
```

## Important environment variables

### Core app
- `NEXUSREACH_DATABASE_URL`
- `NEXUSREACH_REDIS_URL`
- `NEXUSREACH_SUPABASE_URL`
- `NEXUSREACH_SUPABASE_KEY`
- `NEXUSREACH_SUPABASE_JWT_SECRET`
- `NEXUSREACH_AUTH_MODE`

### Search and public discovery
- `NEXUSREACH_BRAVE_API_KEY`
- `NEXUSREACH_SERPER_API_KEY`
- `NEXUSREACH_TAVILY_API_KEY`
- `NEXUSREACH_GOOGLE_API_KEY`
- `NEXUSREACH_GOOGLE_CSE_ID`
- `NEXUSREACH_SEARCH_CACHE_TTL_SECONDS`
- `NEXUSREACH_SEARCH_LINKEDIN_PROVIDER_ORDER`
- `NEXUSREACH_SEARCH_EXACT_LINKEDIN_PROVIDER_ORDER`
- `NEXUSREACH_SEARCH_HIRING_TEAM_PROVIDER_ORDER`
- `NEXUSREACH_SEARCH_PUBLIC_PROVIDER_ORDER`
- `NEXUSREACH_SEARCH_EMPLOYMENT_PROVIDER_ORDER`

### Public page retrieval / The Org
- `NEXUSREACH_FIRECRAWL_BASE_URL`
- `NEXUSREACH_FIRECRAWL_API_KEY`
- `NEXUSREACH_THEORG_TRAVERSAL_ENABLED`
- `NEXUSREACH_THEORG_CACHE_TTL_HOURS`
- `NEXUSREACH_THEORG_MAX_TEAM_PAGES`
- `NEXUSREACH_THEORG_MAX_MANAGER_PAGES`
- `NEXUSREACH_THEORG_MAX_HARVESTED_PEOPLE`
- `NEXUSREACH_THEORG_TIMEOUT_SECONDS`

### Enrichment and drafting
- `NEXUSREACH_APOLLO_API_KEY`
- `NEXUSREACH_APOLLO_MASTER_API_KEY`
- `NEXUSREACH_PROXYCURL_API_KEY`
- `NEXUSREACH_HUNTER_API_KEY`
- `NEXUSREACH_GITHUB_TOKEN`
- `NEXUSREACH_ANTHROPIC_API_KEY`
- `NEXUSREACH_OPENAI_API_KEY`
- `NEXUSREACH_GROQ_API_KEY`
- `NEXUSREACH_LLM_PROVIDER`

## Local quality checks

```bash
cd backend && ruff check app tests conftest.py
cd backend && pytest
cd frontend && npx eslint .
cd frontend && npx tsc -b
cd frontend && npm run test
cd frontend && npm run build
```

## Important truths

1. Brave is still part of the product, but it is intentionally reserved for higher-value exact LinkedIn lookups and fallback use.
2. Firecrawl is optional. The default page-fetch path is direct `httpx` plus Crawl4AI.
3. Current-company verification and email-domain trust are different concerns.
4. Workday exact-job ingestion should fail honestly on maintenance/outage pages instead of importing the wrong landing page.
5. Saved contacts are user-scoped and company-filterable, but people-search output should always be interpreted against the live bucket result, not the global saved-contact list.
