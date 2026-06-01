# NexusReach — Vibe-Coded Launch Checklist Review

Date: 2026-06-01

Source: an external "Pre-launch & Security Checklists for Vibe-Coded
Applications" document, mapped against NexusReach's *actual* architecture and
prior audits (`LAUNCH_AUDIT.md`, `AUDIT_2026-05-29.md`,
`AUDIT_PASS2_2026-05-29.md`, `LAUNCH_CONFIG_CHECKLIST.md`, `DEPLOYMENT_RUNBOOK.md`).

## Verdict

The source checklist is written for a typical un-audited prototype. NexusReach
is well past that: two deep audit passes (54 findings fixed), a deploy runbook,
token encryption, signature-verified JWT auth, production-only restrictive CORS,
Redis-backed per-user rate limiting, SSRF protection, JSON-only Celery, and a
non-leaking global error handler are all already in place. Of the entire
document, **five items are genuinely actionable**, and one of them — Supabase
Data API exposure — is a real risk that none of the prior audits caught because
it lives in Supabase project config, not in code.

Legend: 🔴 critical · 🟠 high · 🟡 medium · ✅ done in this pass · ⏳ needs your action

---

## Findings

### 1. 🔴 Supabase Data API exposure — VERIFY against the live project
Status: ⏳ **you must verify** · ✅ defense-in-depth migration shipped (`047`)

Supabase exposes the `public` schema over its auto-generated PostgREST Data API
to anyone holding the **anon key**, and the anon key ships publicly in the
Vercel frontend bundle (`VITE_SUPABASE_ANON_KEY`). Our app never uses that API
— the backend talks to Postgres directly via `NEXUSREACH_DATABASE_URL` and
scopes every query by `user_id` — but our tables are created by **Alembic**,
and externally-migrated tables do **not** get RLS auto-enabled (only tables
made in the Supabase dashboard do). So `users`, OAuth/token, `people`,
`messages`, and `linkedin_graph_*` may be directly readable/writable at
`https://<project>.supabase.co/rest/v1/<table>` with a key that is public.

> The source document's "RLS is your data layer's master key" framing is *wrong*
> for us (we don't use PostgREST for data), but the underlying risk is real and
> arguably more dangerous, because it's easy to assume "we don't use the Supabase
> API, so RLS doesn't matter" — when the API is exposed regardless.

**30-second check** (run against the real project):
```bash
curl 'https://<project>.supabase.co/rest/v1/users?select=*&limit=1' \
  -H "apikey: <anon-key>"
```
A permission error = good. Returned rows = still exposed.

**Fix (either):**
- **Primary / complete:** Supabase Dashboard → Project Settings → Data API →
  **disable it** (we don't use it), or remove `public` from "Exposed schemas".
- **Defense-in-depth (shipped here):** migration
  `backend/alembic/versions/047_enable_rls_defense_in_depth.py` enables (not
  forces) RLS on every app table with no policies = deny-all over the API.
  The backend's direct connection (Supabase `postgres` role, BYPASSRLS + owner)
  is unaffected. Applies automatically on the next `alembic upgrade head`.
  **Safe only while the backend connects as a BYPASSRLS/owner role** — see the
  migration docstring.

Do both: disable the Data API *and* keep RLS on.

### 2. 🟠 Frontend security headers
Status: ✅ **done** — `frontend/vercel.json`

The SPA previously shipped with no security headers. Added: `X-Frame-Options:
DENY` + `Content-Security-Policy: frame-ancestors 'none'` (clickjacking),
`X-Content-Type-Options: nosniff`, `Referrer-Policy`,
`Strict-Transport-Security` (HSTS, no `preload` — add `; preload` only if you
intend to submit to the HSTS preload list), and a minimal `Permissions-Policy`.

**Deliberately not done:** a full resource-restricting CSP
(`default-src`/`script-src`/`connect-src`). That needs the complete inventory of
runtime origins (Supabase, PostHog, Sentry, the Railway API domain, Google/MS
OAuth) plus testing — a wrong value white-screens production. Recommended as a
follow-up once the prod domains are fixed.

### 3. 🟠 Rotate the committed Dice key
Status: ⏳ **your action** (already noted in `LAUNCH_CONFIG_CHECKLIST.md`)

A real Dice key exists in git history (commit `59f8a701`). History rewriting
won't help — anyone who cloned has it. **Rotate it** in the Dice dashboard;
the current tracked value is blank and `config.py` treats blank as "Dice
disabled," so rotation has no downtime cost.

### 4. 🟡 Cookie consent for analytics (if EU/UK users)
Status: ⏳ **decision needed**

No consent banner exists. PostHog is initialized privacy-consciously
(`autocapture: false`, `disable_session_recording: true` in
`frontend/src/lib/observability.ts`) but still sets analytics cookies by
default. Supabase auth cookies are essential (no consent required); PostHog
analytics is **not** essential and needs consent in the EU/UK. Low-urgency for a
US-first private beta; required for a public EU-facing launch. Options: add a
consent gate, or set PostHog `persistence: 'memory'` until consent.

### 5. 🟡 Verifies & prevention
- **PII in logs:** ✅ checked — the only token-related log lines are scraping
  debug messages (Meta LSD token); no user emails/tokens/passwords are
  interpolated into log statements.
- **AI data-handling disclosure:** ⏳ confirm during the pending legal review
  that the privacy policy states drafting sends user/contact data to the LLM
  provider (Anthropic/etc.).
- **Secret scanning / push protection:** ⏳ enable GitHub secret scanning +
  push protection (and/or a `gitleaks`/`trufflehog` pre-commit hook). This is
  what prevents the *next* Dice-key incident.

---

## What this review changed (code)
- `frontend/vercel.json` — added security `headers` block (finding #2).
- `backend/alembic/versions/047_enable_rls_defense_in_depth.py` — new RLS
  defense-in-depth migration (finding #1).

## Already handled — don't re-chase from the source doc
SSRF (pass-2 P4), insecure deserialization / pickle (N/A; Celery JSON), SQL
injection (ORM + parameterized; LIKE-escape fixed pass-2 P14), endpoint auth
(verified JWT + per-resource ownership, pass-2 P9), CORS `*` (restrictive in
prod), stack-trace leakage (safe global handler), rate limiting / unbounded LLM
consumption (slowapi per-user + daily token cap), `.env` committed (gitignored),
prod source maps (off by default in Vite), observability (Sentry + PostHog +
JSON logs), privacy/terms/export/deletion (built; legal review pending),
backups/rollback/staged deploy (runbook + Go/No-Go).

## What the source document got wrong / N/A for our stack
- **RLS as the app's data layer** — false; reframed as finding #1.
- **pickle RCE** — N/A (no pickle; Celery `task_serializer="json"`).
- **Stripe / "click to cancel" / billing** — N/A (no payment code; free beta).
- **C/C++ memory corruption (GGUF parsers, integer overflow)** — N/A (no native code).
- **Most SEO / sitemap / Core Web Vitals** — low value (logged-in app; root
  redirects to login; only `/privacy` + `/terms` are public).
- **Transactional-email SPF/DKIM/DMARC** — mostly N/A (outreach sends via the
  *user's own* Gmail/Outlook; password resets via Supabase). Confirm cadence /
  job-alert digests aren't sent via an unauthenticated system mailer.
- **Dual-LLM / guardrail-model patterns** — overkill for draft-first outreach
  with mandatory human review. Indirect prompt injection (scraped job/profile
  text in drafting prompts) is low-impact for the same reason; worth awareness,
  not a blocker.
