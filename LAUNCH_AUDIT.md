# NexusReach Launch Audit

Last updated: 2026-05-24

Assumption: "mid June" means a production launch target of 2026-06-15.

## Verdict

NexusReach is close to a credible private/beta launch, but it is not ready for a public launch until the P0 launch gates below are closed. The product loop exists: onboard, discover jobs, find people, verify contact quality, draft outreach, stage/send email, and track follow-up. The remaining risk is less about missing core features and more about production rollout, external-provider reliability, safety regressions, and first-session clarity.

## Fixed In This Pass

1. Onboarding no longer behaves like a stub.
   - Profile basics now persist through `PUT /api/profile`.
   - Goals and target roles/locations/industries now persist through `PUT /api/profile`.
   - Resume upload now uses the existing `POST /api/profile/resume` parser.
   - Completion now drives the user to a first outcome: discover matching jobs, find people, or review profile.
   - Regression coverage added in `frontend/src/components/onboarding/__tests__/OnboardingDialog.test.tsx`.

2. OAuth refresh-token storage is launch-safe.
   - Gmail and Outlook refresh tokens are encrypted with versioned app keys.
   - Existing plaintext tokens are cleared by migration and require reconnect.
   - Production config now fails fast without encryption keys.

3. Auto-send positioning is consistent.
   - Docs now describe draft-first behavior with explicit, delayed, cancellable auto-send.
   - Stale "no auto-send" roadmap/handoff lines were updated.

4. SearXNG production config docs are corrected.
   - `backend/.env.example` now includes `NEXUSREACH_SEARXNG_BASE_URL`.
   - Provider order examples now match the app defaults.

5. Observability and compliance foundation is implemented.
   - Frontend and backend Sentry initialization are wired with release/environment tags.
   - Frontend product analytics are wired through PostHog with autocapture and session recording disabled by default.
   - Public Privacy Policy and Terms pages exist.
   - Settings exposes account export and account deletion.
   - Backend export redacts OAuth refresh tokens and stored API keys.
   - Backend deletion removes Supabase auth identity before deleting app-owned user data.

6. First-win product loop is now explicit.
   - Dashboard has a guided `Job -> Contact -> Draft -> Staged Draft` path.
   - Contact cards show proof for why the contact matched, why the company is trusted, why the email is safe, and whether a warm path exists.
   - Product analytics now tracks signup, onboarding completion, first job, first people result, first saved contact, first draft, first staged draft, and first reply milestones.
   - Dashboard summary now includes launch outcome metrics: contacts found, verified emails, warm paths, drafts created, staged drafts, replies, and interviews.

## P0 Launch Gates

These must be done before public launch.

### 1. Production deployment path

Current evidence: production deployment is now committed to Vercel + Railway +
Supabase + Redis in `DEPLOYMENT_RUNBOOK.md`. The backend has a production
Dockerfile, Railway service configs for web/worker/beat, and production smoke
scripts. The remaining launch gate is an actual cloud rehearsal with production
secrets.

Fix plan:
- Create the Vercel project rooted at `frontend`.
- Create Railway services for API, worker, beat, Redis, and SearXNG.
- Configure Supabase production auth/database and provider OAuth redirects.
- Run migrations once, then deploy/restart worker and beat.
- Run `scripts/production-smoke.sh` locally and
  `backend/scripts/production_smoke.py` against the Railway API.
- Rehearse rollback on staging or production preview.

Owner priority: highest. Target date: 2026-05-29.

### 2. OAuth encryption rollout and reconnect

Current evidence: app-layer encryption is implemented, but launch needs operational rollout.

Fix plan:
- Generate a real Fernet key and configure `NEXUSREACH_TOKEN_ENCRYPTION_KEYS`.
- Run Alembic migration `041_clear_plaintext_oauth_tokens.py` in production before enabling email sends.
- QA Gmail reconnect, Outlook reconnect, draft staging, manual send, scheduled send, and disconnect.
- Add admin/support copy explaining why existing users must reconnect.

Owner priority: highest. Target date: 2026-05-30.

### 3. Observability, legal, and account controls

Current evidence: code-level observability and compliance controls are now in
place. Production still needs real Sentry/PostHog projects, alert rules, and a
disposable-account deletion rehearsal against Supabase.

Fix plan:
- Configure `NEXUSREACH_SENTRY_DSN` for API, worker, and beat.
- Configure `VITE_SENTRY_DSN` and `VITE_POSTHOG_KEY` for the Vercel frontend.
- Confirm Sentry receives frontend, API, and worker errors with environment and release tags.
- Confirm PostHog receives explicit pageview/product events without autocapture or session recording.
- Verify `/privacy` and `/terms` are publicly reachable.
- Verify account export redacts OAuth refresh tokens and API keys.
- Delete a disposable production account and confirm Supabase auth plus app-owned data are removed.

Owner priority: highest. Target date: 2026-05-31.

### 4. Auto-send safety regression coverage

Current evidence: `backend/app/tasks/auto_prospect.py` implements scheduled sending and cancellation checks, but current test search shows no focused backend coverage for `process_pending_sends`.

Fix plan:
- Add backend tests for:
  - scheduled send only when `auto_send_enabled=true`
  - disabling auto-send clears pending schedules
  - missing provider cancels and notifies
  - per-cycle send limit is enforced
  - failed send clears `scheduled_send_at`
- Add frontend tests for the auto-send settings panel and the Messages cancel path.
- Add copy that confirms the delay and cancellation behavior before enabling auto-send.

Owner priority: highest. Target date: 2026-06-01.

### 5. Live smoke suite for the actual user promise

Current evidence: unit/integration tests are strong. A real browser onboarding
happy path now exists in `e2e/tests-real/onboarding-happy-path.spec.ts` and CI
runs it against fresh Postgres, Redis, Alembic migrations, the real backend,
the real frontend, and Supabase-compatible JWT auth. `PLAN.md` and `HANDOFF.md`
still list broader live regression fixtures that need recurring validation.

Fix plan:
- Expand the manual or Playwright-backed launch smoke checklist covering:
  - signup/login
  - onboarding profile/goals/resume
  - default job discovery
  - startup job discovery
  - exact-job import for Apple, Workday, and one generic careers page
  - job-aware people search
  - LinkedIn graph upload/sync-session
  - email find/verify
  - draft generation
  - Gmail and Outlook draft staging
  - scheduled send cancellation
  - privacy/terms public routes
  - account export
  - disposable-account deletion
  - dashboard Act Now
- Run the known fixtures from `HANDOFF.md`: Zip, Whatnot, Apple, Fortune, Uber, xAI, direct LinkedIn graph match, LinkedIn bridge match.
- Record pass/fail results before launch.

Owner priority: highest. Target date: 2026-06-03.

### 6. External-provider reliability decisions

Current evidence: Wellfound is explicitly best-effort and may return 403. LinkedIn browser sync has known DOM/security-challenge uncertainty.

Fix plan:
- Decide whether Wellfound remains visible in v1 copy. Either harden it, mark it as best-effort in UI, or remove it from the launch source list.
- Add UI/provider telemetry for zero-result source failures so users are not left guessing.
- Harden LinkedIn connector selectors against at least two current LinkedIn UI variants.
- Add recovery copy for LinkedIn challenge/login states.

Owner priority: high. Target date: 2026-06-05.

### 7. Production secrets, limits, and abuse controls

Current evidence: config validation catches several production mistakes, but launch still needs real values, quota decisions, and abuse controls.

Fix plan:
- Set real production values for Supabase, Redis, database, frontend URL, CORS origins, OAuth clients, search providers, LLM provider, and encryption keys.
- Set real production values for Supabase service-role key, Sentry, and PostHog.
- Confirm rate limits for discovery, email finding, LLM drafting, and scheduled sends.
- Set provider budgets and failure alerts for Hunter, Proxycurl, Serper, Brave, Tavily, LLM, and Gmail/Graph.
- Decide whether self-hosted SearXNG is enough for beta traffic or needs a managed host/container policy.

Owner priority: high. Target date: 2026-06-06.

## P1 Product Polish For An "Irresistible" First Use

These should be completed before a broader launch, but a small private beta can start if P0 is closed.

1. Make first-session success undeniable.
   - After onboarding, show the discovered job count and next action.
   - If discovery returns zero, fall back to exact-job import and startup discovery prompts.
   - Add a "use a pasted job URL" path directly from onboarding completion.

2. Make the job command center the primary workflow.
   - Route new users into one saved/discovered job with next action highlighted.
   - Reduce cross-page friction between Job Detail, People, Messages, and Outreach.
   - Make "find people for this job" and "draft outreach" the obvious next clicks.

3. Make warm paths feel magical but safe.
   - Thread LinkedIn graph warm-path context into drafting.
   - Keep safety gates intact: warm paths must not bless unsafe company or email matches.
   - Add explanation copy showing why a warm path is useful.

4. Improve provider transparency.
   - Show when a source failed soft vs found no results.
   - Surface enough provider/debug metadata for support without overwhelming users.
   - Add cost/credit visibility for expensive services.

5. Finish launch copy and positioning.
   - Product promise should be: job seekers get from job to right people to safe outreach draft in one workflow.
   - Do not lead with "AI"; lead with "find the right people and draft the right outreach faster."

Target date for P1 polish: 2026-06-10.

## P2 Post-Launch Backlog

These are valuable but should not block the June 15 launch if P0/P1 are done.

- More exact-job adapters beyond Apple/Workday/Workable.
- Scheduled LinkedIn graph refresh.
- Broader company research surfaces.
- Startup-first vs venture-backed taxonomy.
- More dashboard insights from imported LinkedIn graph data.
- Better manager precision at large companies.

## Launch Week Plan

### 2026-05-24 to 2026-05-31
- Land onboarding persistence and first outcome. Done.
- Land OAuth encryption rollout. Done in code; operational rollout remains.
- Add deployment blueprint/runbook. Done; cloud rehearsal remains.
- Add auto-send safety tests.
- Fix stale docs/config inconsistencies. Done for known auto-send and SearXNG examples.

### 2026-06-01 to 2026-06-07
- Run live smoke fixtures end to end.
- Complete provider reliability decisions.
- Harden LinkedIn connector recovery states.
- Complete production secrets and rate-limit setup.
- QA Gmail/Outlook reconnect and email lifecycle.

### 2026-06-08 to 2026-06-12
- Polish first-session outcomes.
- Tighten job command center entry points.
- Add warm-path drafting context if time allows.
- Finalize launch/support copy.

### 2026-06-13 to 2026-06-15
- Freeze non-critical changes.
- Run full backend and frontend test suites.
- Run full launch smoke suite against production.
- Verify monitoring, health checks, worker/beat jobs, and rollback plan.
- Verify privacy/terms, data export, and disposable-account deletion.
- Launch private beta first; expand only after 48 hours of clean telemetry.

## Go/No-Go Checklist

Go only when all are true:
- Production deploy path is documented and rehearsed.
- `/api/health` is green for Postgres and Redis.
- Alembic migrations run cleanly.
- Celery worker and beat are running.
- OAuth reconnect works for Gmail and Outlook.
- No plaintext refresh tokens remain usable.
- Auto-send can be enabled, delayed, cancelled, and disabled safely.
- Onboarding creates a persisted profile and routes to a first outcome.
- Live job discovery and people discovery pass the launch fixtures.
- Provider failures degrade with honest UI feedback.
- Sentry and PostHog are configured and receiving production telemetry.
- Privacy/terms pages are public, account export works, and disposable-account deletion has been rehearsed.
- Frontend tests, frontend build, backend ruff, backend tests, and real E2E pass.
