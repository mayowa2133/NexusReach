# NexusReach — Claude Context

## What is this project?

NexusReach is a smart personal networking assistant for job seekers. It helps users find relevant people at target companies, draft personalized outreach messages, and track their networking efforts. The human is always in the loop — nothing is ever sent automatically.

See `PRD.md` for full product requirements and `architecture.md` for system design.

---

## Tech Stack

### Frontend
- **React 18** + **TypeScript**
- **Vite** for build tooling
- **React Router** for routing
- **Shadcn/ui** for component library
- **Zustand** for client state management
- **TanStack Query** for server state (API caching, refetching)
- **Tailwind CSS** for styling

### Backend
- **Python 3.12+** + **FastAPI**
- **SQLAlchemy** ORM with **Alembic** migrations
- **PostgreSQL** (Supabase hosted)
- **Celery** + **Redis** for background jobs
- **Pydantic** for request/response validation

### External Services
- **Supabase** — Auth + PostgreSQL hosting
- **Apollo.io** — Company enrichment (free tier); people search + email enrichment (paid tier)
- **Brave Search API** — LinkedIn X-ray people discovery (free-tier fallback for Apollo)
- **Proxycurl** — LinkedIn profile enrichment
- **Hunter.io** — Email finding + verification
- **GitHub API** — Engineer profiles + repos
- **JSearch (RapidAPI)** — Job aggregation
- **Adzuna** — Job aggregation
- **Claude API (Anthropic)** — Message drafting
- **Gmail API** — Email draft staging
- **Microsoft Graph API** — Outlook draft staging

### Hosting
- **Vercel** — Frontend
- **Railway** — Backend + Redis + Celery workers

---

## Project Structure

```
NexusReach/
├── frontend/               # React + Vite app
│   ├── src/
│   │   ├── components/     # UI components by module
│   │   ├── hooks/          # Custom hooks
│   │   ├── lib/            # API client, utils
│   │   ├── stores/         # Zustand stores
│   │   ├── types/          # TypeScript types
│   │   └── pages/          # Route pages
│   └── package.json
│
├── backend/                # FastAPI application
│   ├── app/
│   │   ├── routers/        # API route handlers
│   │   ├── services/       # Business logic
│   │   ├── clients/        # External API wrappers
│   │   ├── models/         # SQLAlchemy models
│   │   ├── schemas/        # Pydantic schemas
│   │   ├── tasks/          # Celery tasks
│   │   └── utils/          # Helpers (dedup, scoring, parsing)
│   ├── alembic/            # DB migrations
│   ├── tests/
│   └── requirements.txt
│
├── PRD.md                  # Product requirements
├── architecture.md         # System design + data models
├── PLAN.md                 # Build roadmap + progress
└── CLAUDE.md               # This file
```

---

## Coding Conventions

### Python (Backend)
- Use `async` endpoints in FastAPI
- Type hints on all function signatures
- Pydantic models for all API request/response bodies
- Services contain business logic, routers are thin
- External API calls isolated in `clients/` — never called directly from routers
- Environment variables via `pydantic-settings` (never hardcoded)
- Tests use `pytest` + `httpx.AsyncClient`

### TypeScript (Frontend)
- Functional components only
- Custom hooks for shared logic
- TanStack Query for all API calls (no raw fetch in components)
- Zustand stores for client-only state
- Types co-located or in `types/` directory
- Shadcn/ui components imported from `@/components/ui`

### General
- No `any` types in TypeScript
- No bare `except` in Python — always catch specific exceptions
- Environment variables prefixed: `NEXUSREACH_` for backend, `VITE_` for frontend
- All database queries scoped to `user_id` — never leak data across users

---

## Key Commands

```bash
# Frontend
cd frontend && npm install        # Install dependencies
cd frontend && npm run dev        # Dev server (port 5173)
cd frontend && npm run build      # Production build
cd frontend && npm run lint       # Lint check

# Backend
cd backend && pip install -r requirements.txt  # Install dependencies
cd backend && uvicorn app.main:app --reload    # Dev server (port 8000)
cd backend && alembic upgrade head             # Run migrations
cd backend && alembic revision --autogenerate -m "description"  # New migration
cd backend && pytest                           # Run tests
cd backend && celery -A app.tasks worker --loglevel=info  # Start Celery worker
cd backend && celery -A app.tasks beat --loglevel=info     # Start Celery beat
```

---

## Environment Variables

### Backend (.env)
```
NEXUSREACH_DATABASE_URL=postgresql+asyncpg://...
NEXUSREACH_REDIS_URL=redis://...
NEXUSREACH_SUPABASE_URL=https://...
NEXUSREACH_SUPABASE_KEY=...
NEXUSREACH_APOLLO_API_KEY=...
NEXUSREACH_APOLLO_MASTER_API_KEY=...
NEXUSREACH_PROXYCURL_API_KEY=...
NEXUSREACH_HUNTER_API_KEY=...
NEXUSREACH_GITHUB_TOKEN=...
NEXUSREACH_JSEARCH_API_KEY=...
NEXUSREACH_ADZUNA_APP_ID=...
NEXUSREACH_ADZUNA_API_KEY=...
NEXUSREACH_ANTHROPIC_API_KEY=...
NEXUSREACH_OPENAI_API_KEY=...
NEXUSREACH_GOOGLE_API_KEY=...
NEXUSREACH_GOOGLE_CSE_ID=...
NEXUSREACH_GROQ_API_KEY=...
NEXUSREACH_BRAVE_API_KEY=...
NEXUSREACH_LLM_PROVIDER=anthropic          # anthropic | openai | gemini | groq
NEXUSREACH_GOOGLE_CLIENT_ID=...
NEXUSREACH_GOOGLE_CLIENT_SECRET=...
NEXUSREACH_MICROSOFT_CLIENT_ID=...
NEXUSREACH_MICROSOFT_CLIENT_SECRET=...
```

### Frontend (.env)
```
VITE_API_URL=http://localhost:8000
VITE_SUPABASE_URL=https://...
VITE_SUPABASE_ANON_KEY=...
```

---

## Important Design Decisions

1. **Modular monolith, not microservices** — All backend modules in one FastAPI app. Simpler to develop and deploy. Can split later if needed.

2. **Human always in the loop** — No message is ever sent automatically. The tool drafts; the user approves.

3. **Email waterfall stops early** — Apollo Enrichment → Hunter → Proxycurl → Hunter Domain. First verified email wins. Falls back to LinkedIn if nothing found.

4. **Cache external API results** — Apollo/Proxycurl data stored in DB. Never re-fetch the same profile twice.

5. **Guardrails are defaults, not locks** — 7-day message gap is toggleable with a warning. Contact history is always shown (non-toggleable).

6. **All data scoped to user_id** — Every query includes user_id. No data leaks between accounts.

---

## CI/CD Pre-commit Checklist

Before every commit, the `.githooks/pre-commit` hook runs automatically. You can also run manually:

```bash
# Backend lint (must pass with zero errors)
cd backend && ruff check app/ tests/ conftest.py

# Frontend lint + type check + tests + build (all must pass)
cd frontend && npx eslint .
cd frontend && npx tsc -b
cd frontend && npm run test
cd frontend && npm run build
```

---

## Critical Gotchas

1. **shadcn/ui uses `@base-ui/react`, NOT Radix** — No `asChild` prop (use `render={<Component />}`), no `onInteractOutside`/`onEscapeKeyDown` on DialogContent.
2. **Always check `src/components/ui/*.tsx`** for actual prop types before using any shadcn component prop.
3. **Run `ruff check` on the full backend** including `conftest.py` — it's outside `tests/`.
4. **SQLAlchemy forward references** (`Mapped["Person"]`) need `# noqa: F821` — ruff flags them as undefined names.
5. **Global error handler** returns `{"error": {"code", "message"}}` not `{"detail": "..."}` — all tests must use the new format.
6. **Recharts Tooltip `formatter`** — Don't annotate the value type; let TS infer `ValueType | undefined`.
7. **Testing-library queries** — Use `getByRole('heading', ...)` or exact regex `/^save$/i` to avoid multiple-match failures.
8. **Vitest globals** — Always import `beforeEach`, `afterEach` etc. explicitly from `vitest` for CI compatibility.
9. **Apollo free tier = company endpoints only** — People search (`api_search`, `mixed_people/search`) returns 403 on the free plan. Company endpoints (`organizations/search`, `organizations/enrich`) work. People discovery falls back to **Brave Search API** (LinkedIn X-ray search) when Apollo returns empty. If you upgrade Apollo, people search starts working automatically — no code changes needed.
10. **Brave Search API setup** — Sign up at https://api-dashboard.search.brave.com/ and get an API key. Set `NEXUSREACH_BRAVE_API_KEY` in `.env`. $5/month free credits (~1,000 searches). Google CSE client still exists as backup but Google is deprecating the Custom Search API (blocked for new projects as of Feb 2026).
