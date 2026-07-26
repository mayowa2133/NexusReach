# Security Audit — 2026-07-25

Scope: full product on `main` — FastAPI backend (`backend/app`, 270 files), React
frontend, Chrome companion extension, Celery workers, Alembic migrations,
deployment config, and CI security gates. Reviewed by reading the code paths, not
by scanning alone; dependency audits (`pip-audit`, `npm audit`) were re-run
locally.

Prior audits: `SECURITY_AUDIT_2026-07-11.md`, `AUDIT_PASS2_2026-05-29.md`. The
hardening from those passes is intact and verified below. **Every high-severity
finding here is in the pre-launch waitlist / referral loop shipped 2026-07-23–24,
which post-dates the last audit.**

---

## Summary

| # | Severity | Finding | Status | Location |
|---|----------|---------|--------|----------|
| 1 | **High** | Waitlist join hands out a valid owner token for *any* email | **Fixed 2026-07-25** | `backend/app/routers/waitlist.py:72`, `backend/app/services/waitlist_service.py:50` |
| 2 | **High** | HTML injection into the verification email via `name` | **Fixed 2026-07-25** | `backend/app/tasks/referrals.py:24` |
| 3 | **High** | Double-opt-in is self-serviceable → unlimited fake referrals | **Fixed 2026-07-25** | `backend/app/routers/waitlist.py:121` + `backend/app/routers/referrals.py:38` |
| 4 | Medium | Rate limits key on the proxy IP, not the client | **Fixed 2026-07-25** | `backend/railway.web.toml:6`, `backend/app/middleware/rate_limit.py:24` |
| 5 | Medium | Extension accepts an unvalidated `apiUrl`; `sender` never checked | **Fixed 2026-07-25** | `extension/background.js:28,668,755` |
| 6 | Medium | Secret referral token rides in the URL and is not scrubbed from telemetry | **Fixed 2026-07-25** | `backend/app/services/referral_service.py:215`, `frontend/src/lib/observability.ts:8` |
| 7 | Medium | `react-router` HIGH advisory red-lights the CI security gate | **Fixed 2026-07-25** | `frontend/package.json:33` |
| 8 | Low | Admin waitlist export has no rate limit | **Fixed 2026-07-25** | `backend/app/routers/waitlist.py:130` |
| 9 | Low | Resubmission silently overwrites an existing signup's fields **and its stored resume** | **Fixed 2026-07-25** | `backend/app/services/waitlist_service.py:53`, `backend/app/routers/waitlist.py:81` |
| 10 | Low | No retention policy for `signup_ip` / resumes / goals | **Fixed 2026-07-25** | `backend/alembic/versions/061`, `062` |
| 11 | Info | Known-people cache is cross-tenant by design | **Addressed 2026-07-25** | `backend/app/routers/known_people.py:24` |

### Remediation — 2026-07-25

All three high-severity findings are fixed, plus #6 (its one-line telemetry gap
was pulled forward because the fix introduces a second URL-borne secret) and #9.

Together these establish one invariant on the public signup endpoint: **an
unauthenticated caller can neither read from nor write to a waitlist row it did
not create.** Everything else about the branch follows from that.

**The change.** `waitlist_signups` gains `verification_token_hash` (migration
`063`), a single-use `nrv_` secret that exists only inside the confirmation
email. `access_token` (`nrw_`) is demoted to dashboard *reads*. The join
response now returns `{ok, already_on_list, access_token, referral}` where the
last two are populated **only when the request created the row** — an address
already on the list gets a bare acknowledgement and its owner link by email.
`/api/referrals/verify` takes `?v=` and rejects the access token outright;
spending it consumes the token, credits the referrer once, and returns a fresh
dashboard key. Both email templates escape every interpolated value. The
dashboard reads its token from `?t=`, `?v=`, or `localStorage`, and strips
either secret from the URL after use.

**Verification.** Beyond unit coverage (regression tests added for each), the
original attacks were replayed against the real app on a migrated Postgres:

```
FINDING 1 — attacker submits the victim's email
  [PASS] no access_token returned          [PASS] victim's name not disclosed
  [PASS] no referral block returned        [PASS] referral code not disclosed
  [PASS] no secret token of any kind in the body
  [PASS] victim's original token still works (not locked out by a rotation)
FINDING 9 — the same request must not rewrite the row
  [PASS] name unchanged                    [PASS] note unchanged
  [PASS] linkedin_url unchanged            [PASS] goals unchanged
  [PASS] stored resume not replaced
FINDING 3 — referral fraud without mailbox access
  [PASS] old ?t= verify shape rejected     [PASS] referrer credited nothing
  [PASS] join-response token rejected as a verify token
REGRESSION — the real mailbox flow still works
  [PASS] emailed token verifies            [PASS] referrer credited exactly once
  [PASS] replayed link is dead (single-use, no double-count)
FINDING 2 — HTML injection through the submitted name
  [PASS] no live anchor injected           [PASS] payload rendered as inert text
```

Full suites green afterwards: 1803 backend tests, 219 frontend tests, ruff,
eslint, tsc. Migration applies and reverses cleanly from zero and
`scripts/verify_rls.py` still passes.

**Residual, by design:** `already_on_list` still tells a caller whether an
address is on the list. Closing that would mean dropping the inline referral
panel on join — the mechanic that drives sharing — since showing it at all
reveals the inverse. Worth a decision rather than a silent default: for this
product the leaked bit is "this person is job-hunting", which some users hide
from an employer.

**Breaking change to note at deploy:** confirmation emails already sent carry
the old `?t=` shape and will no longer verify. The plaintext of those tokens
cannot be recovered from their hashes, so there is nothing to backfill —
resubmitting the form with the same address issues a fresh link. Pre-launch
volume makes this the right trade; the alternative was continuing to accept the
credential that made finding #3 exploitable.

---

## 1. High — Waitlist join returns a valid owner token for any email

`POST /api/waitlist` is public and idempotent per email. When the email already
exists, `upsert_waitlist_signup` **mints a fresh access token and returns it**:

```python
# backend/app/services/waitlist_service.py:60-68
raw_token = mint_access_token()
existing.access_token_hash = hash_token(raw_token)
...
return existing, True, raw_token
```

and the router returns it along with the existing row's identity:

```python
# backend/app/routers/waitlist.py:121-127
return WaitlistSignupResponse(
    ok=True,
    already_on_list=already,   # ← email enumeration oracle
    access_token=access_token, # ← the victim's secret owner key
    name=entry.name,           # ← the victim's stored name
    **payload_out,             # ← referral_code, position, share_url, counts
)
```

**Attack.** POST any email address you want to test.
- `already_on_list: true` confirms that person is on the waitlist (enumeration).
- The response discloses their name, referral code, queue position and referral count.
- The returned `access_token` is a *working* owner credential: it opens
  `/api/referrals/status`, `/api/referrals/verify`, and `/r/<code>?t=<token>`.
- The previous owner's token is invalidated by the rotation, so the real owner
  is locked out of their own dashboard link.

**Fix.** Do not return `access_token`, `name`, or referral state on the
`already == True` branch. Return `{ok: true, already_on_list: true}` and nothing
else; email the existing owner their dashboard link instead. Stop rotating the
token on resubmission — mint once, and treat "resend my link" as a separate
email-delivered flow.

---

## 2. High — HTML injection into the verification email

`name` comes straight from the public form (`str`, `max_length=200`, only
`.strip()`ed — `backend/app/schemas/waitlist.py:8`) and is interpolated into the
email body unescaped:

```python
# backend/app/tasks/referrals.py:24-29
def _render_email(name: str, verify_url: str) -> str:
    greeting = f"Hi {name}," if name else "Hi,"
    return f"""...<p style="font-size:16px;line-height:1.5;">{greeting}</p>..."""
```

**Attack.** Submit `email` = the victim's address and

```
name = </p><a href="https://evil.example/login">Confirm your spot →</a><p>
```

The victim receives a Solomon-branded, DKIM-signed message from the product's
own verified Resend sender containing an attacker-chosen link. 200 characters is
ample for an anchor or a tracking pixel. Chained with finding #1, this works
against addresses already on the list too (the resubmission overwrites `name`,
then re-queues the email because the row is still unverified —
`routers/waitlist.py:90`). Effectively: an unauthenticated
phishing-from-your-own-domain primitive, 10 requests/minute.

**Fix.** `html.escape(name)` before interpolation (and escape anything else
user-supplied that ever enters an email template). Consider also restricting
`name` to a printable-character allowlist at the schema level, and sending a
`text` alternative.

---

## 3. High — Double-opt-in is self-serviceable; referral counts are unenforceable

The design intent (per `CLAUDE.md`) is *"a referral only counts once the invitee
verifies their email."* The join response defeats that: it returns both halves of
the verification credential — `referral_code` and `access_token` — to whoever
submitted the form.

```
POST /api/waitlist {"email":"anything@gmail.com","name":"x","referred_by_code":"ATTACKER"}
  → {"referral_code":"ABC…","access_token":"nrw_…"}
GET  /api/referrals/verify?code=ABC…&t=nrw_…
  → invitee flips to verified, referrer's verified_referral_count += 1
```

No mailbox access is ever required. `verify_signup`
(`backend/app/services/referral_service.py:157`) only checks that the code/token
pair resolves. Consequences: the reward ladder (product credits, honored manually
at launch) is farmable, and queue position — sorted on
`verified_referral_count` — is meaningless. The other anti-fraud controls do not
compensate: the disposable-domain list and the Gmail-normalizing `fraud_key` only
block obvious duplicates, and the per-IP cap is itself broken (finding #4).

**Fix.** Verification must require possession of the mailbox. Mint a **separate,
single-use verification token** that is only ever delivered by email and never
returned in an HTTP response; keep `access_token` for dashboard reads only and
have `/api/referrals/verify` reject it.

---

## 4. Medium — Rate limits key on the proxy IP, not the client

`uvicorn` is started with no `--proxy-headers` / `--forwarded-allow-ips`:

```toml
# backend/railway.web.toml:6
startCommand = "... exec uvicorn app.main:app --host 0.0.0.0 --port $PORT"
```

Uvicorn's `forwarded_allow_ips` defaults to `127.0.0.1`, so `X-Forwarded-For`
from Railway's edge is not trusted, and slowapi's key function reads the peer
address only:

```python
# backend/app/middleware/rate_limit.py:24
return get_remote_address(request)   # request.client.host — no XFF
```

Behind the Railway edge that peer is the proxy, so **every visitor shares one
rate-limit bucket**. Concretely:

- `POST /api/waitlist` `10/minute` becomes a global 10/minute for the whole site.
- `referral_signup_ip_daily_limit = 50` becomes a **global 50 signups/day** —
  after the 50th, `enforce_signup_ip_limit` 429s every subsequent visitor
  (`referral_service.py:108`). On a launch day that shuts the funnel.
- `signup_ip` stored on every row is the proxy's address, so it has no forensic
  value.
- The anti-fraud intent of the per-IP cap is void either way.

**Fixed 2026-07-25.** The obvious remedy is a trap and was rejected: uvicorn
0.30.6's `ProxyHeadersMiddleware` returns `x_forwarded_for_hosts[0]` in
always-trust mode — the **leftmost**, *client-written* entry. Setting
`--forwarded-allow-ips='*'` would therefore have converted a shared-bucket
availability bug into a total bypass, since `X-Forwarded-For: 9.9.9.9` arrives
as `9.9.9.9, <real client>` and uvicorn would report the forged value.

Resolution now happens in `backend/app/utils/client_ip.py`, which is explicit,
testable, and independent of uvicorn's version-specific behaviour.
`X-Forwarded-For` grows left-to-right (each proxy appends the address it
received *from*), so with `NEXUSREACH_TRUSTED_PROXY_HOPS = N` the real caller is
the Nth entry from the **right** and everything left of it is client input.
Railway's edge is one hop, wired in `railway.web.toml`. It fails safe — missing
header, chain shorter than the hop count, or a non-IP value falls back to the
socket peer (the old shared bucket) rather than trusting attacker input — and
the production config validator refuses to boot the API below 1, because this
failure is otherwise silent until the signup funnel closes.

`GET /api/ready` (already token-gated) now reports `client_ip`, `socket_peer`
and `trusted_proxy_hops`, so the setting can be **verified against the real
topology** instead of assumed:

```bash
curl -s -H "X-Readiness-Token: $NEXUSREACH_READINESS_TOKEN" https://<api-host>/api/ready
```

Verified end-to-end by driving the app through a simulated appending edge proxy:

```
IP RESOLUTION behind one appending edge proxy
  [PASS] resolves the real caller, not the socket peer
  [PASS] a different caller resolves differently
  [PASS] an injected X-Forwarded-For cannot choose the key
  [PASS] a long forged chain cannot either
RATE LIMIT BUDGETS are per caller
  [PASS] first caller is eventually limited        (10/min budget exhausts)
  [PASS] a second caller still has its own budget  (the reported bug)
  [PASS] cannot pin the blame on someone else's key either
```

That last check matters independently: spoofing a victim's IP must not let an
attacker burn *their* budget and lock them out.

---

## 5. Medium — Extension stores an unvalidated `apiUrl`; `sender` is never checked

`app-bridge.js` forwards **any** `window.postMessage` from the app page into the
privileged background worker with an unfiltered `type`/`payload`
(`extension/app-bridge.js:9`, `:32`). The background's router never inspects
`sender` (`extension/background.js:668` — the parameter is bound but unused
except for `sender?.origin` as a display value), and `setConfig` accepts whatever
origin it is handed:

```js
// extension/background.js:28-31
async function setConfig({ apiUrl, authToken, appUrl }) {
  if (apiUrl) update.apiUrl = apiUrl.replace(/\/+$/, "");   // no scheme/host check
```

which every companion call then trusts:

```js
// extension/background.js:77-84
const response = await fetch(`${apiUrl}${path}`, {
  headers: { Authorization: `Bearer ${authToken}`, ... }
});
```

**Attack.** Any script executing on the app origin (XSS, a compromised
third-party script, a malicious transitive dependency) posts
`NR_EXTENSION_CONNECT` with `apiUrl: "https://evil.example"`. From then on the
long-lived companion bearer token, the user's profile, captured LinkedIn
profiles and the entire first-degree graph are POSTed to the attacker — and the
poisoning is **persistent in `chrome.storage.local`**, surviving long after the
originating XSS is patched. `SET_TOKEN` is likewise reachable and lets a page
swap in an attacker's token so captures land in the attacker's account.

**Fixed 2026-07-25.** Three layers:

*The API origin is pinned.* `getConfig` always returns `NR_DEFAULTS.apiUrl`,
`setConfig` no longer has an `apiUrl` channel, and the worker purges any legacy
stored value on start — so an install poisoned by an older build heals on
update rather than keeping the attacker's endpoint indefinitely. The app stops
sending `apiUrl` at all. To retarget the companion you edit `config.js` (dev) or
rebuild with `NR_API_ORIGIN` (prod).

*Messages are authorized by origin **and** type.* `isAuthorizedMessage` allows
our own extension pages everything, and allows a content script only the types
its page legitimately needs (`ALLOWED_TYPES_BY_SCRIPT`). The matching origins are
**derived from the live manifest's `content_scripts` matches**, so they cannot
drift from where each script is actually injected — and because `build.mjs`
rewrites those matches for production, the rules narrow to the real app origin
automatically. Net effect: the web app can still run the connect handshake, but
can no longer reach `SET_TOKEN` (swap in the attacker's account), `LOGOUT`, or
the LinkedIn scrape/capture handlers. A job-board page gets `GET_PROFILE` only.

*The bridge forwards a matching allowlist.* `app-bridge.js` drops any page
`postMessage` outside the five `NR_EXTENSION_*` / `NR_LINKEDIN_*` types before
it reaches the worker. Defense in depth — the worker's check is authoritative.

Found while fixing this: the popup carried an **"API URL (advanced)" input** that
wrote `apiUrl` straight to `chrome.storage.local`. Pinning made it inert, but it
was independently a social-engineering vector — "paste this URL into your
Solomon popup to fix syncing" sends the companion token wherever the attacker
says. The field is removed; a dev build retargets via `config.js`.

Verified by `extension/tests/message-auth.test.mjs` (14 tests, loading the real
`background.js` and the real `manifest.json`): the connect payload cannot
redirect the API origin, a legacy stored `apiUrl` is purged, the app origin is
refused `SET_TOKEN` / `CAPTURE_PROFILE` / `SUBMIT_HIRING_TEAM`, a job board is
refused everything but `GET_PROFILE`, look-alike origins
(`myworkdayjobs.com.evil.example`, `http://` LinkedIn) fail the wildcard while a
genuine `*.myworkdayjobs.com` subdomain passes, and a production-shaped manifest
refuses localhost entirely.

**These tests were not running anywhere**, so they are now wired into CI as an
`extension-test` job, together with a packaging check that the built manifest
contains no localhost and scopes `app-bridge.js` to the app origin.

---

## 6. Medium — Secret referral token travels in URLs and escapes telemetry scrubbing

`build_dashboard_url` / `build_verify_url` put the secret in the query string
(`backend/app/services/referral_service.py:215-222`), and `useReferral.ts:63`
sends it as `?t=` on API calls. Secrets in URLs land in browser history, CDN and
server access logs, and `Referer` headers on any outbound navigation from
`/r/:code`.

The frontend already scrubs telemetry URLs, but the allowlist misses this
parameter name:

```ts
// frontend/src/lib/observability.ts:8
const SENSITIVE_QUERY_KEYS = new Set([
  'code', 'state', 'token', 'access_token', 'refresh_token', 'session_token',
]);   // ← no 't'
```

so a Sentry event raised on the referral dashboard ships the live owner token to
Sentry.

**Fix.** Add `'t'` to `SENSITIVE_QUERY_KEYS` now (one line). Longer term, have
`/r/:code` read `t` once, `history.replaceState` it out of the URL, and send it
to the API in an `Authorization` header instead of a query parameter.

---

## 7. Medium — `react-router` advisory is failing the CI security gate

`npm audit --omit=dev` in `frontend` reports 2 HIGH:

```
react-router  7.12.0 - 8.2.0
  React Router: RSC Mode CSRF Bypass Allows Action Execution Before 400 Response
  GHSA-qwww-vcr4-c8h2
```

The app is a Vite SPA with no RSC/server actions, so this is **not exploitable
here**. But `.github/workflows/security.yml` runs exactly this command, and
`npm audit` exits non-zero — so the security workflow is currently red and every
other gate in it (gitleaks, trivy, bandit, semgrep, RLS verification) stops
being a signal. Backend deps are clean: `pip-audit` on `requirements.lock`
reports no known vulnerabilities.

**Fixed 2026-07-25.** There was no patch to take: the advisory range ends at
`8.2.0`, the fix landed in **8.3.0**, and `7.18.1` is the last v7 — no backport
exists, so staying on v7 meant carrying the advisory permanently. Suppressing it
was the wrong call too, since the whole point of the gate is that everything
else in that workflow (gitleaks, trivy, bandit, semgrep, the RLS check) stops
being a signal while it's red.

So this became a real major upgrade. `react-router-dom` has **no v8** — it was
folded into `react-router` — so the change is a package swap plus an import
rewrite across 36 files (11 symbols, all core SPA APIs: `BrowserRouter`,
`Routes`, `Route`, `Link`, `Navigate`, `Outlet`, `MemoryRouter`, `useNavigate`,
`useParams`, `useLocation`, `useSearchParams`). `react-router@8.3.0` requires
React `>= 19.2.7`; the app declared `^19.2.4`, so React moved 19.2.4 → 19.2.8
within its existing range — a lockfile change, not a new constraint.

Worth recording that the advisory itself was **not exploitable here** — it is an
RSC-mode CSRF bypass and this is a Vite SPA with no RSC or server actions. The
upgrade was to restore the gate, not to close a live hole.

Verified beyond the type checker, because passing tests do not prove routing
still works at runtime:

- `npm audit --omit=dev` → **found 0 vulnerabilities**, exit 0 (the gate itself)
- 219 frontend tests, eslint, `tsc -b`, production build
- **the real-browser E2E suite** (`e2e/npm run test:real`) — boots the backend
  and frontend, migrates a database from zero, and drives Chromium through the
  authenticated onboarding flow: 1 passed
- manual smoke of the public routes that use the changed hooks: `/` renders and
  `/r/:code` resolves `useParams` + `useSearchParams` with a clean console

---

## 8. Low — Admin waitlist export has no rate limit

**Fixed 2026-07-25.** `GET /api/waitlist` 404s when unset and uses
`hmac.compare_digest`, but carried no `@limiter.limit`, so `X-Admin-Token` could
be guessed at full request rate against a payload containing the entire list —
emails, LinkedIn URLs, notes, resume metadata.

Now rate-limited to 5/min (keyed on the real client IP, per #4) and rejected
attempts are logged so repeated guessing is visible rather than silent. The
token requirement is enforced rather than advised: production fails config
validation if `NEXUSREACH_WAITLIST_ADMIN_TOKEN` is shorter than 32 characters,
since a short secret guarding the whole list is worse than leaving the export
disabled. Verified end-to-end — a wrong token returns 403 and trips 429 after
three attempts.

## 9. Low — Resubmission overwrites an existing signup's fields and resume

**Fixed 2026-07-25.** `waitlist_service.py:53-59` overwrote `name`,
`linkedin_url`, `current_title`, `target_role`, `note`, `source` and `goals` for
any caller who knew the email. Closer inspection during remediation found the
worse half: `routers/waitlist.py` also ran `attach_resume` on the existing-row
branch, and since the Storage object path is derived from the row id
(`{id}/resume.pdf`) and uploads send `x-upsert: true`, a stranger could
**replace the owner's stored resume file in place**.

An unauthenticated caller now cannot write to a row it did not create. A
resubmission for a known address re-issues a link and mails it — nothing else.
Validation still runs before the branch, so a malformed upload returns the same
error either way and cannot be used as an "is this email registered?" oracle.

**Product trade-off, accepted deliberately:** a member who signed up and later
wants to attach a resume or fix a typo can no longer do it by resubmitting. The
endpoint cannot tell them from someone who guessed their address, so the correct
home for that is a token-authenticated edit on the referral dashboard — not
built here, and worth scheduling if pre-launch profile enrichment matters.

## 10. Low — No retention policy for newly collected personal data

**Fixed 2026-07-25.** Waitlist members have no account, so `/api/account/delete`
could not reach them: an uploaded resume, an IP address and free-text notes had
no expiry and no way out. Both halves now exist.

*Retention* — `tasks/waitlist_retention.purge_waitlist_pii` runs daily and drops
each field once it has outlived its purpose: `signup_ip` after 30 days (the live
anti-fraud control is the 24h Redis window, so the column is forensic only) and
resumes after 180 days, removing the Storage object as well as the columns. The
object is deleted *before* the metadata is cleared — the reverse order would
leave a row claiming "no resume" while the file lingered unreferenced, with
nothing to retry it. A failed object delete leaves the row intact so the next
sweep retries.

*Erasure* — `DELETE /api/referrals/me` (owner token, same as `/status`) removes
the row and the stored file together, surfaced as a "Delete my data" control on
the referral dashboard. Referral attribution survives deliberately: invitee rows
keep their place via `ON DELETE SET NULL` and referrer tallies are untouched, so
erasing one member never silently demotes other people's queue positions.

Verified against a real database and through the browser: erasure refuses a
wrong token, removes the row plus the Storage object, and invalidates the token;
the sweep clears expired IPs and resumes while leaving recent signups alone.

## 11. Info — Known-people cache is cross-tenant by design

**Addressed 2026-07-25.** First, a correction to the original write-up: I said
the table "stores guessed and verified work emails". It does not. Migration 048
nulled every value, `known_people_service` refuses to cache one, and
`_sanitize_profile_data_for_cache` strips every email-shaped key from
`profile_data`. The column was dead weight, and migration `064` drops it so it
cannot be silently repopulated — there is now no email column at all.

What was genuinely open: rows were marked `expired` but **never deleted**, so
data about third parties who never used the product accumulated forever, and
there was no way to service a removal request. Both are fixed —
`maintain_known_people_cache` now calls `purge_expired_records` (delete after
`known_people_purge_days`, default 180, required to stay above the 90-day expiry
flag), and `scripts/erase_known_person.py` services an erasure request with a
`--dry-run` first. Deliberately a script rather than an endpoint: these requests
are rare and manual, and an endpoint would add an enumeration oracle for no gain.
The `/privacy` page now discloses the directory, what it holds, the legitimate-
interests basis, the retention window, and how to be removed.

**Still a business decision, not a code one:** whether legitimate interests is
the right basis for your jurisdictions and user base. The code now minimizes what
is held and makes erasure possible; confirming the basis (and whether an
Article 14 notification obligation applies) needs your judgement, not mine.

---

## Verified sound

These were examined specifically and found correctly implemented — recording so
the next pass doesn't re-litigate them:

- **SQL injection** — no raw SQL anywhere except two parameterized `text()` calls
  (`main.py:168` health probe, `dependencies.py:94` advisory lock). All queries
  are ORM-constructed; `ilike(f"%{x}%")` sites bind parameters correctly.
- **SSRF** — `utils/url_safety.py` resolves DNS, rejects
  private/loopback/link-local/reserved/multicast, **pins the vetted IP for the
  connection with SNI/Host preserved**, and re-validates every redirect hop.
  Unresolvable hosts fail closed. The logo proxy constrains input with a strict
  hostname regex and never fetches the user's host directly.
- **LaTeX RCE** — `-no-shell-escape` plus `openin_any=p` / `openout_any=p`,
  `-halt-on-error`, timeout, `start_new_session`, run inside the process sandbox
  (`resume_artifact/latex.py:739-766`). Escaping covers all TeX metacharacters;
  `_latex_url` strips backslashes and braces.
- **Untrusted file parsing** — `utils/sandboxed_process.py` uses a fresh
  interpreter, `RLIMIT_AS/CPU/FSIZE/NOFILE`, a scrubbed env, process-group kill
  on timeout, output-size caps, and socket denial. Waitlist resumes are magic-byte
  sniffed and parsed out-of-band in the worker, never inline on the public route.
- **Prompt injection** — all untrusted sources (job posting, recipient profile,
  reply, warm path, LinkedIn signal, stories, history) are wrapped in labelled
  untrusted blocks and scanned (`message_service.py:855`), and
  `assess_generated_message_safety` gates auto-send on an outbound URL allowlist,
  credential-request patterns, active markup, bidi/zero-width characters and
  header injection. `auto_prospect.py:503,663` honor `safe_for_automatic_send`.
- **OAuth** — PKCE, one-time server-side state bound to the user, `redirect_uri`
  allowlisted to known frontends with localhost excluded in production
  (`routers/email.py:46`). Refresh tokens Fernet-encrypted with versioned keys.
- **JWT** — explicit per-algorithm branches with an allowlist (ES256 via JWKS,
  HS256 via shared secret), audience checked; no `alg: none` or confusion path
  (`auth_tokens.py`).
- **Authorization** — every authenticated route depends on `get_current_user_id`
  /`get_companion_or_user_id`; spot-checked service queries filter on
  `user_id`. Companion tokens are prefixed, hashed at rest, single-active,
  revocable, cannot mint successors, and are accepted only on opted-in routes.
- **RLS** — enabled on every `public` table, including the new `waitlist_signups`
  and `companion_tokens`; `scripts/verify_rls.py` enforces it in CI.
- **XSS** — the only two `dangerouslySetInnerHTML` sinks both pass through
  DOMPurify with a tag/attribute allowlist and a `rel="noopener noreferrer"` hook.
- **Secrets** — no `.env` tracked in git; gitleaks scans full history in CI.
- **CI** — pip-audit, bandit, semgrep, gitleaks (full history), trivy image scan,
  CycloneDX SBOMs, RLS verification, non-root/no-compiler container assertions,
  SHA-pinned actions and base images. Strong posture — see finding #7 about
  keeping it green.

---

## Remaining work

Every finding in this audit is now closed. What remains are decisions rather
than defects:

1. **The `already_on_list` residual** (under #1) — the join response still
   reveals whether an address is on the list. Closing it means dropping the
   inline referral panel, since showing the panel reveals the inverse. A product
   call: the leaked bit is "this person is job-hunting".
2. **Lawful basis for the known-people directory** (under #11) — the code now
   minimizes and expires it and supports erasure; confirming the basis, and
   whether Article 14 notification applies, is a legal judgement.
3. **A token-authenticated "edit my details / attach a resume"** action on the
   referral dashboard, now that #9 blocks doing it by resubmitting the form —
   only worth building if pre-launch profile enrichment matters.

### Deploy notes from this round

- The API refuses to boot in production unless `NEXUSREACH_TRUSTED_PROXY_HOPS`
  is ≥1 (set in `railway.web.toml`) and `NEXUSREACH_WAITLIST_ADMIN_TOKEN`, if
  set, is ≥32 characters. Both are fail-fast on purpose.
- Verification emails already sent carry the old `?t=` shape and will no longer
  verify; resubmitting the form issues a fresh link.
- Retention now depends on Celery beat running. If beat is down nothing expires,
  so treat a stalled beat as a privacy issue, not just a freshness one.
- `react-router` 8 requires React ≥19.2.7 (moved 19.2.4 → 19.2.8 within the
  existing range).
