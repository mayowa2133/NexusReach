# NexusReach Production Deployment Runbook

Last updated: 2026-05-24

This project is committed to this production stack for the mid-June launch:

- Frontend: Vercel, project root `frontend`
- API web service: Railway, project root `backend`, config `backend/railway.web.toml`
- Celery worker: Railway, project root `backend`, config `backend/railway.worker.toml`
- Celery beat: Railway, project root `backend`, config `backend/railway.beat.toml`
- Database and auth: Supabase hosted Postgres and Supabase Auth
- Redis: Railway Redis, shared by Celery broker/result backend and search cache
- Search metasearch: SearXNG on Railway or a private reachable host

The backend production image is built from `backend/Dockerfile`. It installs
`pdflatex` through TeX Live so resume PDF generation does not depend on an
implicit host package.

## Service Topology

```text
Vercel frontend
  -> Railway API web service
      -> Supabase Postgres/Auth
      -> Railway Redis
      -> Railway Celery worker
      -> Railway Celery beat
      -> SearXNG
      -> external providers: Apollo, Proxycurl, Hunter, Tavily, Serper, Brave, LLMs, Gmail, Microsoft Graph
```

Only one Celery beat instance should be active in production. Beat schedules job
refresh, stale contact re-verification, LinkedIn sync-session cleanup, job alert
digests, pending auto-send processing, and cadence digests.

## Platform Setup

### Vercel frontend

Create one Vercel project:

- Root Directory: `frontend`
- Framework Preset: Vite
- Install Command: `npm ci`
- Build Command: `npm run build`
- Output Directory: `dist`
- Production branch: `main`

Environment variables:

```env
VITE_API_URL=https://<railway-api-domain>
VITE_AUTH_MODE=supabase
VITE_DEV_AUTH_BYPASS_ENABLED=false
VITE_SUPABASE_URL=https://<supabase-project>.supabase.co
VITE_SUPABASE_ANON_KEY=<supabase-anon-key>
VITE_APP_ENVIRONMENT=production
VITE_APP_RELEASE=<git-sha-or-release>
VITE_SENTRY_DSN=<frontend-sentry-dsn>
VITE_SENTRY_TRACES_SAMPLE_RATE=0.05
VITE_SENTRY_REPLAYS_SESSION_SAMPLE_RATE=0
VITE_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE=1
VITE_POSTHOG_KEY=<posthog-project-key>
VITE_POSTHOG_HOST=https://us.i.posthog.com
VITE_ANALYTICS_ENABLED=true
```

The existing `frontend/vercel.json` keeps SPA rewrites pointed at
`index.html`.

### Railway backend services

Create three Railway services from the same repository and set each service root
to `backend`. Railway's config file path does not automatically follow the
service root, so set each service's config file path to the absolute repo path
shown below.

| Service | Config file | Start command |
| --- | --- | --- |
| `nexusreach-api` | `/backend/railway.web.toml` | `sh -c 'cd /app && python -m alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port $PORT'` |
| `nexusreach-worker` | `/backend/railway.worker.toml` | `celery -A app.tasks worker --loglevel=info` |
| `nexusreach-beat` | `/backend/railway.beat.toml` | `celery -A app.tasks beat --loglevel=info` |

The API start command runs `python -m alembic upgrade head` before Uvicorn, so a
failed migration prevents the new API container from becoming healthy. Worker
and beat do not run migrations. If the config path is not enabled in Railway,
keep the root directory as `backend`, use the shared `Dockerfile`, and set each
service's start command exactly as above.

The API service health check is:

```text
GET /api/health
```

It must return `200` with both `postgres` and `redis` set to `ok`.

### Redis

Provision one Railway Redis instance and attach its private connection string to
all three backend services:

```env
NEXUSREACH_REDIS_URL=redis://...
```

This URL is used by:

- Celery broker
- Celery result backend
- search-provider cache
- discovery rate limiting

### Supabase

Create a Supabase project and configure:

- Hosted Postgres connection string for `NEXUSREACH_DATABASE_URL`
- Auth URL for `NEXUSREACH_SUPABASE_URL`
- anon key for `NEXUSREACH_SUPABASE_KEY`
- JWT secret for `NEXUSREACH_SUPABASE_JWT_SECRET`
- Vercel production domain in Supabase Auth redirect URLs
- local development redirects only in non-production Supabase projects

Use the async SQLAlchemy URL form in Railway:

```env
NEXUSREACH_DATABASE_URL=postgresql+asyncpg://...
```

### SearXNG

SearXNG is the primary (free, unlimited) search provider. It is **not** bundled
in the app — it runs as its own service that the backend reaches over HTTP. The
repo ships a ready-to-deploy build under `deploy/searxng/` (a `Dockerfile` that
bakes in `deploy/searxng/settings.yml`, plus `railway.toml`). Local development
uses `docker-compose.yml` instead; production deploys the `deploy/searxng/` image.

> **Free, always-on alternative (no Railway Hobby plan needed):** host SearXNG on
> an Oracle Cloud "Always Free" VM instead — see
> [`deploy/searxng/ORACLE_FREE_VM.md`](deploy/searxng/ORACLE_FREE_VM.md). It uses
> the same `settings.yml`, fronted by Caddy for HTTPS + Basic Auth, and the
> backend connects via `https://<user>:<pass>@<domain>` (no code change). The
> Railway recipe below is the paid-plan path.

Deploy it as a private Railway service:

1. **New service → Deploy from repo.** Set the service root directory to
   `deploy/searxng` and its config file path to `/deploy/searxng/railway.toml`.
   Railway builds the Dockerfile (which contains the JSON-API-enabled settings),
   so no volume mount is needed.
2. **Set the secret.** Add a `SEARXNG_SECRET` service variable to a long random
   string (`python -c "import secrets; print(secrets.token_hex(32))"`). The image
   substitutes it into the `ultrasecretkey` placeholder at boot.
3. **Keep it private.** Do not assign a public domain; the backend reaches it on
   the Railway private network. The image listens on port `8080`.
4. **Wire the backend.** Set this on all three backend services (`api`, `worker`,
   `beat`) to the service's private URL **including the `:8080` port**:

```env
NEXUSREACH_SEARXNG_BASE_URL=http://nexusreach-searxng.railway.internal:8080
```

Verify after deploy (from a backend shell or any reachable host):

```bash
curl -s "$NEXUSREACH_SEARXNG_BASE_URL/search?q=site:linkedin.com/in+engineer&format=json" | head -c 200
```

It must return JSON with a `results` array. If it returns HTML or an error, the
`json` format is not enabled (check the mounted `settings.yml`) or the URL/port
is wrong.

**Limiter / 429s:** `settings.yml` enables the abuse limiter. If the backend
shares an egress IP and starts getting throttled (SearXNG returns `429` and the
router falls through to paid providers), set `limiter: false` in
`deploy/searxng/settings.yml` (safe for a private-only instance) or allowlist the
backend — see the note at the bottom of that file.

Keep Serper, Brave, Tavily, and Google CSE configured as fallbacks: the router
(`searxng → serper → brave → google_cse`) automatically uses them when SearXNG is
unreachable or returns nothing, so search degrades gracefully (to paid quota)
rather than breaking if SearXNG is down.

## Backend Secrets

Set these in all Railway backend services unless noted otherwise:

```env
NEXUSREACH_ENVIRONMENT=production
NEXUSREACH_DATABASE_URL=postgresql+asyncpg://...
NEXUSREACH_REDIS_URL=redis://...
NEXUSREACH_SUPABASE_URL=https://<supabase-project>.supabase.co
NEXUSREACH_SUPABASE_KEY=<supabase-anon-key>
NEXUSREACH_SUPABASE_SERVICE_ROLE_KEY=<supabase-service-role-key>
NEXUSREACH_SUPABASE_JWT_SECRET=<supabase-jwt-secret>
NEXUSREACH_AUTH_MODE=supabase
NEXUSREACH_DEV_AUTH_BYPASS_ENABLED=false
NEXUSREACH_APP_RELEASE=<git-sha-or-release>
NEXUSREACH_FRONTEND_URL=https://<vercel-production-domain>
NEXUSREACH_CORS_ORIGINS=["https://<vercel-production-domain>"]
NEXUSREACH_TOKEN_ENCRYPTION_PRIMARY_VERSION=v1
NEXUSREACH_TOKEN_ENCRYPTION_KEYS={"v1":"<fernet-key>"}
NEXUSREACH_SENTRY_DSN=<backend-sentry-dsn>
NEXUSREACH_SENTRY_TRACES_SAMPLE_RATE=0.05
NEXUSREACH_SENTRY_PROFILES_SAMPLE_RATE=0.0

NEXUSREACH_LLM_PROVIDER=anthropic
NEXUSREACH_ANTHROPIC_API_KEY=<key>
NEXUSREACH_OPENAI_API_KEY=<optional-key>
NEXUSREACH_GOOGLE_API_KEY=<optional-gemini-or-cse-key>
NEXUSREACH_GROQ_API_KEY=<optional-key>

NEXUSREACH_APOLLO_API_KEY=<key>
NEXUSREACH_APOLLO_MASTER_API_KEY=<optional-key>
NEXUSREACH_PROXYCURL_API_KEY=<key>
NEXUSREACH_HUNTER_API_KEY=<key>
NEXUSREACH_HUNTER_PATTERN_MONTHLY_BUDGET=25
NEXUSREACH_GITHUB_TOKEN=<key>
NEXUSREACH_JSEARCH_API_KEY=<key>
NEXUSREACH_ADZUNA_APP_ID=<key>
NEXUSREACH_ADZUNA_API_KEY=<key>
NEXUSREACH_DICE_API_KEY=<rotated-key>   # optional; old committed key must be rotated

NEXUSREACH_SEARXNG_BASE_URL=http://nexusreach-searxng.railway.internal:8080  # see SearXNG section
NEXUSREACH_SERPER_API_KEY=<optional-key>
NEXUSREACH_BRAVE_API_KEY=<optional-key>
NEXUSREACH_TAVILY_API_KEY=<key>
NEXUSREACH_SEARCH_CACHE_TTL_SECONDS=86400
NEXUSREACH_SEARCH_LINKEDIN_PROVIDER_ORDER=searxng,serper,brave,google_cse
NEXUSREACH_SEARCH_EXACT_LINKEDIN_PROVIDER_ORDER=searxng,brave,serper,google_cse
NEXUSREACH_SEARCH_HIRING_TEAM_PROVIDER_ORDER=searxng,serper,brave
NEXUSREACH_SEARCH_PUBLIC_PROVIDER_ORDER=searxng,serper,brave,tavily
NEXUSREACH_SEARCH_EMPLOYMENT_PROVIDER_ORDER=tavily,searxng,serper,brave

NEXUSREACH_GOOGLE_CLIENT_ID=<gmail-oauth-client-id>
NEXUSREACH_GOOGLE_CLIENT_SECRET=<gmail-oauth-client-secret>
NEXUSREACH_MICROSOFT_CLIENT_ID=<microsoft-oauth-client-id>
NEXUSREACH_MICROSOFT_CLIENT_SECRET=<microsoft-oauth-client-secret>

NEXUSREACH_FIRECRAWL_BASE_URL=
NEXUSREACH_FIRECRAWL_API_KEY=
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

Generate the token encryption key with:

```bash
cd backend
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep old key versions configured until every token encrypted with that version
has been rotated or disconnected.

The Supabase service role key is required for account deletion. Keep it only in
Railway backend services; never expose it to Vercel or the browser.

## OAuth Redirects

Configure provider callbacks to point at the production frontend/backend flow
used by the app:

- Google OAuth client: production Vercel domain and API callback origins
- Microsoft app registration: production Vercel domain and API callback origins
- Supabase Auth: production Vercel domain as the site URL and allowed redirect

After the OAuth token encryption migration lands, all existing Gmail and Outlook
connections must reconnect. Do not enable production email staging or auto-send
until reconnect has been tested.

## Release Order

Use this order for every production release:

1. Confirm CI is green on `main`. CI must include backend tests, frontend
   lint/test/build, and `e2e/playwright.real.config.ts` against Postgres,
   Redis, migrated schema, real backend, real frontend, and Supabase-compatible
   JWT auth.
2. Build the backend production image locally:

   ```bash
   scripts/production-smoke.sh
   ```

3. Back up Supabase Postgres.
4. Deploy the Railway API service with the new image. Its start command runs
   migrations before starting Uvicorn:

   ```bash
   sh -c 'cd /app && python -m alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port $PORT'
   ```

5. If the config-as-code path is disabled, set the same API start command in
   Railway's service settings. To run migrations manually for recovery:

   ```bash
   railway run --service nexusreach-api python -m alembic upgrade head
   ```

6. Verify API health:

   ```bash
   NEXUSREACH_API_URL=https://<railway-api-domain> \
     python backend/scripts/production_smoke.py
   ```

7. Deploy or restart the Celery worker service.
8. Deploy or restart the Celery beat service. Confirm only one beat instance is running.
9. Deploy Vercel frontend from `main`.
10. Run the full production smoke checklist below.

Do not let worker and beat run against a schema version that the API has not
migrated to.

## Production Smoke Checklist

Run this after every production deployment:

- `/api/health` returns `ok` for Postgres and Redis.
- Vercel frontend loads and calls the Railway API domain, not localhost.
- Supabase login works.
- Onboarding saves profile, goals, and resume, then can start job discovery.
- Resume tailoring can generate and download a PDF. This proves `pdflatex` is present.
- Job discovery returns at least one result from configured providers.
- Startup discovery returns results or fails soft for blocked providers.
- People search returns recruiters, hiring managers, or peers with company-confidence labels.
- Gmail reconnect works after token encryption rollout.
- Outlook reconnect works after token encryption rollout.
- Draft staging creates a provider draft.
- Optional auto-send can be enabled, schedules a delayed send, and can be cancelled before it sends.
- Privacy Policy and Terms pages load publicly from Vercel.
- Account export downloads JSON with OAuth tokens and stored API keys redacted.
- Account deletion works for a disposable production test account and removes the Supabase auth identity.
- Celery worker logs show task execution.
- Celery beat logs show scheduled task dispatch.
- Redis is receiving Celery and cache traffic without connection errors.
- LinkedIn graph manual upload works.
- LinkedIn local connector command can create a sync session and upload rows from an operator machine.

## LinkedIn Connector Runtime

The LinkedIn graph browser connector is intentionally not part of the Railway
backend image. It runs on the user's or operator's machine so the server never
stores LinkedIn cookies, session tokens, or credentials.

Operator setup:

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install playwright
python -m playwright install chrome
python scripts/linkedin_graph_connector.py --help
```

The production backend only receives normalized connection rows through the sync
session API.

## Alerts

Configure alerts before opening public access:

- Railway API: deploy failures, restart loops, `/api/health` failures, 5xx spikes.
- Railway worker: restart loops, task failure spikes, queue backlog growth.
- Railway beat: missing scheduled dispatches, multiple active beat instances.
- Redis: memory pressure, connection failures, eviction spikes.
- Supabase: connection saturation, storage growth, auth error spikes.
- Vercel: build failures, production deployment failures, elevated frontend errors.
- Sentry: new issue spikes, unhandled backend exceptions, frontend error spikes, release regressions.
- PostHog: pageview/event ingestion, onboarding completion drop-off, export/delete event volume.
- External providers: quota exhaustion for Hunter, Proxycurl, Apollo, Tavily, Serper, Brave, LLM provider.
- Uptime monitor: public frontend URL and API `/api/health`.

Until a first-party alerting integration is added to the codebase, use platform
alerts plus an external uptime monitor. Treat missing worker or beat alerts as a
launch blocker.

## Rollback

Frontend rollback:

- Promote the previous successful Vercel production deployment.
- Confirm `VITE_API_URL` still points to the intended API domain.

API rollback:

- Redeploy the previous Railway API deployment.
- Re-run `/api/health`.
- If the issue is schema-related, stop worker and beat before any DB rollback.

Worker rollback:

- Stop beat first if scheduled jobs are producing bad work.
- Redeploy the previous worker deployment.
- Inspect failed tasks before requeueing.

Beat rollback:

- Ensure only one beat process is running.
- Redeploy the previous beat deployment or stop beat entirely if scheduled
  sends/job refreshes need to pause.

Database rollback:

- Prefer forward fixes for already-applied migrations.
- If rollback is required, restore from the Supabase backup taken immediately
  before deploy.
- The OAuth plaintext-token migration intentionally clears tokens and is not
  meaningfully reversible. Recovery is user reconnect, not restoring plaintext
  secrets.

Provider rollback:

- Lower provider usage by changing provider-order environment variables and
  restarting API/worker.
- Disable risky scheduled effects by stopping beat.

## Go/No-Go For Mid-June Launch

Launch is blocked until all of these are true:

- Production services exist for web, worker, beat, Redis, SearXNG, Supabase, and Vercel.
- `scripts/production-smoke.sh` passes locally.
- Cloud smoke passes against the production Railway API.
- A production resume PDF can be generated.
- OAuth reconnect works for Gmail and Outlook.
- Sentry is receiving frontend/API/worker errors with release and environment tags.
- PostHog is receiving explicit pageview/product events without session recording.
- Privacy Policy, Terms, account export, and disposable-account deletion are verified.
- Alerts are configured for API, worker, beat, Redis, Supabase, Vercel, and external uptime.
- Rollback has been rehearsed once on staging or production preview.
