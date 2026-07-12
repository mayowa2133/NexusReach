# NexusReach — Launch Configuration Checklist

Tickable companion to `DEPLOYMENT_RUNBOOK.md` (the source of truth for deploy order,
smoke checks, alerts, and rollback). Work top to bottom. `[ ]` = todo, `[x]` = done.

**Deploy model:** Railway + Vercel deploy via their **native GitHub integrations**
(auto-deploy on push to `main`). There is **no** GitHub Actions deploy workflow, so
you do **not** need `RAILWAY_TOKEN`/`VERCEL_TOKEN` GitHub secrets. `ci.yml` only runs
tests. DB migrations (incl. `045_add_job_canonical_url`, `046_add_job_posted_date`)
run **automatically** via the API service's `alembic upgrade head` pre-deploy command.

---

## Phase 1 — Create accounts
- [ ] Supabase project (Postgres + Auth)
- [ ] Railway account (will host API, worker, beat, Redis, SearXNG)
- [ ] Vercel account (frontend)
- [ ] Sentry — 2 projects: backend (Python/FastAPI) + frontend (React)
- [ ] PostHog project (US cloud)
- [ ] Google Cloud project → OAuth 2.0 client (Gmail integration)
- [ ] Microsoft Entra (Azure AD) → app registration (Outlook integration)
- [ ] Domain (optional for beta — `*.vercel.app` / `*.up.railway.app` work to start)

## Phase 2 — Generate secrets
- [ ] Token encryption key (REQUIRED — backend fails fast in prod without it):
  ```bash
  cd backend && python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```
  → use for `NEXUSREACH_TOKEN_ENCRYPTION_KEYS={"v1":"<key>"}`
- [ ] SearXNG `secret_key` (a long random string; see `deploy/searxng/settings.yml`)
- [ ] **Rotate the old Dice key** (it's in git history) if you intend to use Dice → `NEXUSREACH_DICE_API_KEY`

## Phase 3 — Provision infrastructure
- [ ] **Supabase:** copy Postgres URL (use `postgresql+asyncpg://…` form), project URL, anon key, **service-role key** (Railway-only), JWT secret
- [ ] **Railway → Redis** instance; attach its private URL to all 3 backend services
- [ ] **Railway → 3 services** (root `backend`, shared `Dockerfile`):
  - [ ] `nexusreach-api` — config `/backend/railway.web.toml` (runs `alembic upgrade head` pre-deploy)
  - [ ] `nexusreach-worker` — config `/backend/railway.worker.toml`
  - [ ] `nexusreach-beat` — config `/backend/railway.beat.toml` — **exactly one instance**
- [ ] **Railway → SearXNG** private service, mount `deploy/searxng/settings.yml`
  - [ ] (Alternative) skip SearXNG: set `NEXUSREACH_SEARXNG_BASE_URL=""` AND provide a `SERPER` or `BRAVE` key
- [ ] **Vercel:** import repo, Root `frontend`, Vite preset, build `npm run build`, output `dist`, prod branch `main`

## Phase 4 — Backend env vars (Railway, set on all 3 services)
See the fill-in block at the bottom. Tiers:
- [ ] **REQUIRED** core (env, auth, DB, Redis, Supabase, frontend URL/CORS, Fernet key, Anthropic, release)
- [ ] **Email** OAuth (Google + Microsoft client id/secret) — needed for Gmail/Outlook connect
- [ ] **Recommended** discovery quality (SearXNG, Hunter, Proxycurl, Apollo, Tavily, JSearch, Adzuna, GitHub token)
- [ ] **Observability** (`NEXUSREACH_SENTRY_DSN`)
- [ ] **Optional** (OpenAI/Gemini/Groq, Serper/Brave/Google CSE, Firecrawl, Dice)
- [ ] Provider-order + The Org + employment-verify vars (safe defaults — copy from runbook §Backend Secrets)

## Phase 5 — Frontend env vars (Vercel)
- [ ] `VITE_API_URL`, `VITE_AUTH_MODE=supabase`, `VITE_DEV_AUTH_BYPASS_ENABLED=false`
- [ ] `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`
- [ ] `VITE_APP_ENVIRONMENT=production`, `VITE_APP_RELEASE=<git-sha>`
- [ ] `VITE_SENTRY_DSN`, `VITE_POSTHOG_KEY`, `VITE_POSTHOG_HOST=https://us.i.posthog.com`, `VITE_ANALYTICS_ENABLED=true`

## Phase 6 — OAuth & Supabase redirects
- [ ] Supabase Auth: Site URL = Vercel domain; add it to allowed redirect URLs
- [ ] Google OAuth client: add prod Vercel domain + API callback origins
- [ ] Microsoft app: add the same redirect URIs
- [ ] Note: after token-encryption migration, **all Gmail/Outlook users must reconnect**; don't enable email staging/auto-send until reconnect is QA'd

## Phase 6.5 — Rebrand → Solomon
The product is branded **Solomon** to users; the codebase/infra stays **NexusReach**
internally on purpose (env prefix `NEXUSREACH_`, DB name, Celery/Redis names, `/docs`
title — none of it is user-visible, so it is deliberately **not** renamed).

- [x] **Done in code** — all user-facing UI strings say "Solomon" (nav/header, landing,
  login, onboarding, Settings, Waitlist, Terms/Privacy, page `<title>`, favicon +
  compass logo mark in `frontend/src/components/BrandLogo.tsx`).
- [x] **Done in code** — user-facing *backend* strings say "Solomon": job-alert +
  cadence-digest email subjects/footers, resume-quality attribution shown in Job
  Detail, the LLM drafting persona, and the data-export download filename.
- [ ] **OAuth consent-screen app name (MANUAL — the one user-visible item not in code):**
  users see this on the Gmail/Outlook connect screen ("… wants to access your account").
  - [ ] Google Cloud → OAuth consent screen → **App name** = `Solomon` (+ logo, support/dev contact email on the Solomon domain)
  - [ ] Microsoft Entra → app registration → **Display name** / branding = `Solomon`
- [ ] Confirm transactional email **From** name reads as Solomon to recipients — note:
  alerts/digests send through the *user's own* Gmail/Outlook, so the sender is the user,
  not a branded address (no action needed unless a dedicated sending domain is added later).

## Phase 7 — Deploy (in order — runbook §Release Order)
- [ ] CI green on `main` ✅
- [ ] Back up Supabase Postgres
- [ ] Deploy **API** → pre-deploy migrates through `046`; verify `GET /api/health` → `postgres: ok, redis: ok`
- [ ] Local image check: `scripts/production-smoke.sh`
- [ ] Cloud smoke: `NEXUSREACH_API_URL=https://<api> python backend/scripts/production_smoke.py`
- [ ] Deploy/restart **worker**, then **beat** (one instance)
- [ ] Deploy **Vercel** frontend

## Phase 8 — Production smoke (must pass — runbook §Smoke Checklist)
- [ ] `/api/health` ok · Supabase login · onboarding saves profile/goals/resume
- [ ] Resume **PDF** generates (proves `pdflatex` in the image)
- [ ] Job discovery returns results · startup discovery returns/fails-soft
- [ ] People search returns recruiters/managers/peers with company-confidence labels
- [ ] **Gmail reconnect** · **Outlook reconnect** · draft staging creates a provider draft
- [ ] Auto-send: enable → schedules delayed send → cancel before it fires
- [ ] `/privacy` + `/terms` public · account export (tokens/keys redacted) · disposable-account deletion removes Supabase identity
- [ ] Worker logs show task execution · beat logs show dispatch · Redis healthy
- [ ] LinkedIn graph manual upload · local-connector sync session

## Phase 9 — Alerts (launch blocker — runbook §Alerts)
- [ ] Railway API (5xx, health, restart loops) · worker (failures/backlog) · beat (missing/duplicate dispatch)
- [ ] Redis · Supabase · Vercel · Sentry · PostHog
- [ ] Provider quota alerts (Hunter, Proxycurl, Apollo, Tavily, Serper, Brave, LLM)
- [ ] External uptime monitor on public URL + `/api/health`

## Go / No-Go (runbook §Go/No-Go)
- [ ] All services exist · local + cloud smoke pass · prod resume PDF works
- [ ] Gmail/Outlook reconnect works · Sentry receiving FE/API/worker errors · PostHog receiving events
- [ ] Privacy/Terms/export/deletion verified · alerts configured · **rollback rehearsed once**

---

## Not required (decisions, not blockers)
- **Billing/Stripe** — no payment code exists; only needed if charging at launch (free/beta = skip).
- **Marketing landing page** — only `/privacy` + `/terms` exist; root redirects to login. Fine for private beta.
- **Legal review** — have counsel review Terms/Privacy (LinkedIn data + email sections); update `privacy@/legal@` contact addresses to real ones.

---

## Fill-in env template

### Backend (Railway — all 3 services). Replace every `<…>`.
```env
# --- REQUIRED core ---
NEXUSREACH_ENVIRONMENT=production
NEXUSREACH_AUTH_MODE=supabase
NEXUSREACH_DEV_AUTH_BYPASS_ENABLED=false
NEXUSREACH_DATABASE_URL=postgresql+asyncpg://<supabase-postgres>
NEXUSREACH_REDIS_URL=redis://<railway-redis>
NEXUSREACH_SUPABASE_URL=https://<project>.supabase.co
NEXUSREACH_SUPABASE_KEY=<anon-key>
NEXUSREACH_SUPABASE_SERVICE_ROLE_KEY=<service-role-key>   # Railway only — never to Vercel
NEXUSREACH_SUPABASE_JWT_SECRET=<jwt-secret>
NEXUSREACH_FRONTEND_URL=https://<vercel-domain>
NEXUSREACH_CORS_ORIGINS=["https://<vercel-domain>"]
NEXUSREACH_TOKEN_ENCRYPTION_PRIMARY_VERSION=v1
NEXUSREACH_TOKEN_ENCRYPTION_KEYS={"v1":"<fernet-key>"}
NEXUSREACH_LLM_PROVIDER=anthropic
NEXUSREACH_ANTHROPIC_API_KEY=<key>
NEXUSREACH_APP_RELEASE=<git-sha>

# --- Email (Gmail/Outlook connect) ---
NEXUSREACH_GOOGLE_CLIENT_ID=<gmail-oauth-client-id>
NEXUSREACH_GOOGLE_CLIENT_SECRET=<gmail-oauth-client-secret>
NEXUSREACH_MICROSOFT_CLIENT_ID=<ms-oauth-client-id>
NEXUSREACH_MICROSOFT_CLIENT_SECRET=<ms-oauth-client-secret>

# --- Recommended discovery quality ---
NEXUSREACH_SEARXNG_BASE_URL=https://<searxng-service>
NEXUSREACH_HUNTER_API_KEY=<key>
NEXUSREACH_PROXYCURL_API_KEY=<key>
NEXUSREACH_APOLLO_API_KEY=<key>
NEXUSREACH_APOLLO_MASTER_API_KEY=<optional>
NEXUSREACH_TAVILY_API_KEY=<key>
NEXUSREACH_JSEARCH_API_KEY=<key>
NEXUSREACH_ADZUNA_APP_ID=<key>
NEXUSREACH_ADZUNA_API_KEY=<key>
NEXUSREACH_GITHUB_TOKEN=<key>
NEXUSREACH_HUNTER_PATTERN_MONTHLY_BUDGET=25

# --- Observability ---
NEXUSREACH_SENTRY_DSN=<backend-dsn>
NEXUSREACH_SENTRY_TRACES_SAMPLE_RATE=0.05
NEXUSREACH_SENTRY_PROFILES_SAMPLE_RATE=0.0

# --- Optional ---
NEXUSREACH_OPENAI_API_KEY=
NEXUSREACH_GOOGLE_API_KEY=
NEXUSREACH_GOOGLE_CSE_ID=
NEXUSREACH_GROQ_API_KEY=
NEXUSREACH_SERPER_API_KEY=
NEXUSREACH_BRAVE_API_KEY=
NEXUSREACH_FIRECRAWL_BASE_URL=
NEXUSREACH_FIRECRAWL_API_KEY=
# Rotate the old historically committed key before enabling Dice; blank disables it.
NEXUSREACH_DICE_API_KEY=

# --- Defaults (safe; copy as-is) ---
NEXUSREACH_SEARCH_CACHE_TTL_SECONDS=86400
NEXUSREACH_SEARCH_LINKEDIN_PROVIDER_ORDER=google_cse,serper,brave,youcom,exa
NEXUSREACH_SEARCH_EXACT_LINKEDIN_PROVIDER_ORDER=google_cse,serper,brave,youcom
NEXUSREACH_SEARCH_HIRING_TEAM_PROVIDER_ORDER=serper,brave
NEXUSREACH_SEARCH_PUBLIC_PROVIDER_ORDER=brave,serper,tavily
NEXUSREACH_SEARCH_EMPLOYMENT_PROVIDER_ORDER=tavily,brave,serper
NEXUSREACH_THEORG_TRAVERSAL_ENABLED=true
NEXUSREACH_THEORG_CACHE_TTL_HOURS=24
NEXUSREACH_THEORG_MAX_TEAM_PAGES=3
NEXUSREACH_THEORG_MAX_MANAGER_PAGES=3
NEXUSREACH_THEORG_MAX_HARVESTED_PEOPLE=25
NEXUSREACH_THEORG_TIMEOUT_SECONDS=20
NEXUSREACH_EMPLOYMENT_VERIFY_ENABLED=true
NEXUSREACH_EMPLOYMENT_VERIFY_TOP_N=10
NEXUSREACH_EMPLOYMENT_VERIFY_TIMEOUT_SECONDS=20
NEXUSREACH_LINKEDIN_GRAPH_SYNC_SESSION_TTL_SECONDS=900
NEXUSREACH_LINKEDIN_GRAPH_MAX_IMPORT_BATCH_SIZE=250
```

### Frontend (Vercel). Replace every `<…>`.
```env
VITE_API_URL=https://<railway-api-domain>
VITE_AUTH_MODE=supabase
VITE_DEV_AUTH_BYPASS_ENABLED=false
VITE_SUPABASE_URL=https://<project>.supabase.co
VITE_SUPABASE_ANON_KEY=<anon-key>
VITE_APP_ENVIRONMENT=production
VITE_APP_RELEASE=<git-sha>
VITE_SENTRY_DSN=<frontend-dsn>
VITE_SENTRY_TRACES_SAMPLE_RATE=0.05
VITE_SENTRY_REPLAYS_SESSION_SAMPLE_RATE=0
VITE_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE=1
VITE_POSTHOG_KEY=<posthog-key>
VITE_POSTHOG_HOST=https://us.i.posthog.com
VITE_ANALYTICS_ENABLED=true
```
