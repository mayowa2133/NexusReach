# Audit Fix — Items Requiring User Intervention

These fixes could not be completed autonomously because they require credentials, secrets, or actions outside the codebase. Each time you're at the laptop, handle these.

## Summary

- **Only ONE item needs you: C4** (Dice API key — set env var + rotate the exposed key).
- Everything else (all CRITICAL except C4's secret, all HIGH, all MEDIUM, all LOW) is fully fixed in code and verified by tests.
- **New deploy step:** migration `045_add_job_canonical_url` was added (H7). It runs automatically via `alembic upgrade head` in the normal deploy — no manual action beyond deploying.
- **Verification not run locally:** `cd e2e && npm run test:real` (real-browser E2E) needs a live Postgres + booted backend/frontend + a Supabase-compatible JWT, which aren't available in this environment. Run it once at the laptop before shipping. All other gates pass: 1111 backend tests, 172 frontend tests, ruff, tsc, eslint, production build.

(Items appended as they are encountered during implementation.)

---

## C4 — Dice API key (PARTIAL: code done, secrets need you)

**Code change (done):** `backend/app/clients/remote_jobs_client.py` now reads the Dice key from
`settings.dice_api_key` (env var `NEXUSREACH_DICE_API_KEY`) instead of the hardcoded literal.
When the env var is unset, Dice search fails soft to `[]` (no crash). `dice_api_key` was added to
`backend/app/config.py`.

**What you must do:**
1. **Rotate the exposed key.** The old key `1YAt0R9wBg4WfsF9VB2778F5CHLAPMVW3WAZcKd8` is in git
   history and must be treated as compromised. Obtain a fresh Dice API key.
2. **Set the env var in every environment that runs the backend:**
   - Local: add `NEXUSREACH_DICE_API_KEY=<new key>` to `backend/.env`
   - Railway: add `NEXUSREACH_DICE_API_KEY` to the web + worker + beat services
3. Until set, the Dice source simply returns no jobs (other sources unaffected).

**Why skipped autonomously:** requires a real secret + key rotation, which I cannot perform.

---
