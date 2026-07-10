# NexusReach security audit — 2026-07-10

## Executive summary

This source-available review covered the FastAPI backend, React/Vite frontend,
Chrome extension, Docker/Railway/Vercel configuration, Alembic migrations, and
declared dependencies. It included manual authorization, OAuth, upload, SSRF,
secret-handling, deployment, and dependency-audit review.

No critical issue, SQL injection, confirmed cross-user IDOR, hard-coded live
credential, or browser-to-Supabase RLS bypass was found in the reviewed code.
Application queries generally scope user-owned records with `user_id`; JWT
verification explicitly allowlists algorithms and validates audience; RLS is
deny-by-default for browser roles.

Eight findings require remediation. Priority work is OAuth callback binding,
request-body limits, parser upgrades, and centralizing SSRF-safe outbound
fetching.

This report reflects repository code only. It cannot prove the absence of
problems in deployed secrets, cloud IAM, Supabase configuration, Railway/Vercel
edge controls, DNS, or third-party systems.

## Method and scope

- Reviewed backend routes/services/models for authentication, ownership checks,
  raw SQL, input constraints, file parsing, and external calls.
- Reviewed frontend rendering, sanitization, OAuth callbacks, HTTP headers, and
  extension message/token handling.
- Reviewed migrations, RLS posture, production container, and deployment files.
- Ran `npm audit --omit=dev --package-lock-only` and
  `pip-audit -r backend/requirements.txt` on 2026-07-10.

Not performed: authenticated production penetration testing, cloud/IAM review,
secret rotation, or active exploitation.

## Findings

| ID | Severity | Confidence | Finding |
|---|---|---:|---|
| NR-01 | High | Confirmed | OAuth response is not tied to its initiating session and does not use PKCE. |
| NR-02 | High | Confirmed | Request bodies are unbounded before parsing, including the public waitlist. |
| NR-03 | High | Confirmed | Vulnerable `python-multipart==0.0.12` parses uploads. |
| NR-04 | High | Confirmed | Vulnerable `pypdf==4.3.1` parses untrusted resumes without resource isolation. |
| NR-05 | Medium | Confirmed code defect | Generic crawler fallbacks bypass SSRF validation; DNS rebinding remains possible. |
| NR-06 | Medium | Confirmed | Cost/abuse limits fail open when Redis is unavailable. |
| NR-07 | Medium | Confirmed dependency state | Frontend lockfile contains direct dependencies with unresolved advisories. |
| NR-08 | Low | Confirmed | Container runs as root and builds are not fully reproducible. |

### NR-01 — OAuth callback CSRF / inbox account-linking mix-up

**Evidence.** The Gmail and Outlook authorization-URL routes do not require the
current user and call the provider URL builders without state:
[email.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/routers/email.py:146)
and [email.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/routers/email.py:181).
The frontend appends a fixed `gmail` or `outlook` state, then accepts that
same static label on callback:
[SettingsPage.tsx](/Users/mayowaadesanya/Documents/Projects/NexusReach/frontend/src/pages/SettingsPage.tsx:172).
Neither provider flow includes a PKCE challenge/verifier.

**Impact.** A provider authorization code is not cryptographically bound to the
NexusReach account/browser session that initiated connection. An attacker can
obtain a code for a mailbox they control and induce a logged-in victim to
complete the callback, linking the attacker's inbox to the victim's NexusReach
account. That undermines the connected-mailbox boundary and can cause drafts or
sends to use the wrong mailbox.

**Remediation.** Make initiation authenticated and server-side. Generate a
one-time, high-entropy state record containing user id, provider, exact redirect
URI, expiry, and a PKCE verifier; persist only a state hash where practical.
Send state and an S256 challenge to the provider. In the callback, atomically
validate and consume the record before exchanging the code with its verifier.
Do not have the browser submit an arbitrary code/redirect URI to a generic
connect endpoint. Add tests for missing, mismatched, expired, replayed, and
cross-provider state.

### NR-02 — Body-size checks occur after the dangerous work

**Evidence.** The app registers CORS/gzip but no request-body limiting middleware:
[main.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/main.py:74).
The public waitlist receives a Pydantic JSON body:
[waitlist.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/routers/waitlist.py:32).
The JSON resume endpoint decodes and checks size only after FastAPI parsed the
full base64 string:
[profile.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/routers/profile.py:341).

**Impact.** An unauthenticated attacker can send a huge JSON body to
`POST /api/waitlist`. The worker receives/parses it before Pydantic field
limits or the route limiter run. Concurrent large bodies can exhaust memory,
CPU, bandwidth, and worker capacity. The same applies to authenticated JSON
upload paths; endpoint-level file caps do not protect pre-parse buffering.

**Remediation.**

1. Enforce route-appropriate request-body caps at Railway/the reverse proxy.
2. Add early ASGI middleware that rejects excessive `Content-Length`, and
   counts chunked request bytes while streaming.
3. Keep ordinary JSON small (for example 1 MiB); allow larger caps only on
   upload routes. Remove base64 JSON upload when multipart is reliable.
4. Apply an especially small edge body cap and bot/rate protection to waitlist.
5. Test declared-length and chunked over-limit requests and verify 413 happens
   before parser allocation.

### NR-03 — Known-vulnerable multipart parser

**Evidence.** The backend directly pins `python-multipart==0.0.12`:
[requirements.txt](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/requirements.txt:8).
It is used by resume and LinkedIn graph uploads; the resume upload route is
[profile.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/routers/profile.py:319).

**Scanner result.** pip-audit reported CVE-2024-53981,
CVE-2026-40347, CVE-2026-42561, CVE-2026-53538, and CVE-2026-53539, covering
malformed multipart/header and urlencoded parser DoS/differential issues.
Reported fixes reach `python-multipart 0.0.31`.

**Impact.** Crafted requests consume parser work before
`read_upload_capped()` runs. A low-barrier authenticated user can exhaust
event-loop/worker capacity despite later application-level file rejection.

**Remediation.** Upgrade to a currently patched release (at least 0.0.31 per
the audit), test against the supported FastAPI/Starlette version, enforce edge
body/header/field-count limits, and add malformed multipart regression tests.

### NR-04 — Known-vulnerable PDF parsing with no resource isolation

**Evidence.** The backend pins `pypdf==4.3.1`:
[requirements.txt](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/requirements.txt:15).
Resume parsing uses `PdfReader` in default non-strict mode and walks all page
text:
[resume_parser.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/services/resume_parser.py:34).

**Scanner result.** pip-audit reported pypdf resource-exhaustion issues,
including CVE-2025-55197, CVE-2025-62707, CVE-2025-62708,
CVE-2025-66019, and CVE-2026-22690. Its reported fixed releases are in the
6.x series, up to 6.6.2.

**Impact.** A PDF under the 10 MiB source cap can still cause large
decompression, CPU use, or looping. Moving parsing to a thread avoids blocking
the event loop but does not cap CPU/RAM or the count of simultaneous parses.

**Remediation.** Upgrade to a patched pypdf 6.x version, use
`PdfReader(..., strict=True)` where compatible, cap page count/extracted
text/decompressed stream output, and parse in an isolated worker with memory,
CPU, and wall-time limits. Return a generic 422 on parser failures and add
malicious-PDF fixtures to CI.

### NR-05 — SSRF control is bypassed by generic fallbacks and has DNS TOCTOU

**Evidence.** `fetch_direct_page()` uses `safe_get`, but generic
`fetch_page()` then hands the original URL to Crawl4AI and Firecrawl without
requiring it to be safe:
[public_page_client.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/clients/public_page_client.py:123).
Crawl4AI opens its own browser/network request:
[crawl4ai_client.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/clients/crawl4ai_client.py:30).
Additionally, `safe_get()` resolves the hostname, then HTTPX resolves/connects
again rather than using a vetted address:
[url_safety.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/utils/url_safety.py:65)
and [url_safety.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/utils/url_safety.py:155).

**Impact.** A URL rejected by direct retrieval can still reach a fallback
crawler. A hostile DNS name can pass an initial public-IP check then rebind to
an internal address before connection. Exploitability depends on reachability
of user-influenced URLs and egress policy, but the intended metadata/internal
network protection is incomplete.

**Remediation.** Centralize all outbound retrieval behind one fail-closed SSRF
policy and require it for direct HTTP, Crawl4AI, and Firecrawl. Resolve once and
connect to a vetted public IP while preserving the intended host/SNI, or enforce
the same control in an egress proxy. Revalidate redirects, block private,
loopback, link-local, multicast, reserved IPv4/IPv6 and metadata ranges, and
add DNS-rebinding coverage. Prefer domain allowlists for provider-specific
fetches.

### NR-06 — Rate limits fail open during Redis outages

**Evidence.** SlowAPI falls back to process-local in-memory limits on Redis
failure: [rate_limit.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/middleware/rate_limit.py:42).
The discovery daily budget catches Redis errors and allows the request:
[discovery_rate_limit.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/utils/discovery_rate_limit.py:65).

**Impact.** Shared limits disappear when the system is degraded. Abusive users
can repeatedly invoke costly external searches; per-process fallback is
inconsistent across workers. Public waitlist protection is also weak in a
multi-instance outage.

**Remediation.** For costly/external-provider actions, fail closed or use a
conservative local circuit breaker when Redis is unavailable. Keep inexpensive
reads available. Add independent edge/WAF rate limits, expose limiter health,
alert on Redis failures, and test intended outage behavior.

### NR-07 — Unresolved frontend dependency advisories

**Evidence.** The lockfile resolves `dompurify 3.3.3`,
`posthog-js 1.376.0`, and `react-router(-dom) 7.13.1`:
[package-lock.json](/Users/mayowaadesanya/Documents/Projects/NexusReach/frontend/package-lock.json:5513),
[package-lock.json](/Users/mayowaadesanya/Documents/Projects/NexusReach/frontend/package-lock.json:8237),
and [package-lock.json](/Users/mayowaadesanya/Documents/Projects/NexusReach/frontend/package-lock.json:8528).
`npm audit --omit=dev` reported 26 vulnerable production dependency entries
(7 high, 18 moderate, 1 low).

**Impact.** React Router advisories largely target server/RSC capabilities that
this Vite static SPA does not appear to use, so they are not considered a
confirmed RCE path here. DOMPurify is security-sensitive because it protects
job descriptions before `dangerouslySetInnerHTML`; its advisory state should
not be accepted without review.

**Remediation.** Upgrade direct dependencies to current patched releases,
regenerate the lockfile, and re-run the audit until clean or every residual
finding has a documented non-reachability decision. Retain sanitizer tests for
malicious URLs, SVG/MathML, custom elements, template content, and blank-target
links. Add automated dependency update/audit gates.

### NR-08 — Root container and non-reproducible builds

**Evidence.** The production Dockerfile has no `USER` instruction, starts
from mutable `python:3.12-slim`, and upgrades pip during each build:
[Dockerfile](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/Dockerfile:1).
Several backend dependencies are ranged rather than hash-locked.

**Impact.** This is defense-in-depth rather than an independent compromise. A
future application/library exploit receives unnecessary root privileges. Mutable
base images and ranged dependencies make supply-chain changes hard to reproduce.

**Remediation.** Pin the base image by digest, use a hash-locked dependency
file/wheel build, scan in CI, create an unprivileged application user, and run
Uvicorn as that user. Use a multi-stage build to keep compilers out of runtime
where feasible.

## Prioritized solution plan

### Phase 0 — containment (0–2 days)

1. Temporarily disable Gmail/Outlook connection in production, or restrict it
   to staff, until NR-01 is fixed.
2. Add Railway/edge request-body limits now; protect public waitlist first.
3. Upgrade `python-multipart` and `pypdf`, then run targeted upload/parser
   tests before deployment.
4. Disable generic Crawl4AI/Firecrawl fallback for any user-influenced URL
   until the shared SSRF gate is complete.

### Phase 1 — correct security controls (week 1)

1. Implement server-side OAuth transaction storage, state, PKCE, atomic
   consumption, and callback regression tests for both providers.
2. Add per-route body-size middleware plus proxy limits; eliminate base64
   resume JSON if possible.
3. Centralize outbound fetches and add redirect, IPv6/private-IP, metadata, and
   DNS-rebinding test cases.
4. Fail closed or apply a conservative breaker for costly paths during Redis
   outage; add edge rate limits.

### Phase 2 — runtime and supply-chain hardening (week 2)

1. Upgrade FastAPI/Starlette as a tested compatible set; resolve Python audit
   findings and produce a hash-locked environment.
2. Upgrade frontend direct dependencies and resolve/document every remaining
   production audit result.
3. Pin the container base digest and run the application as non-root.
4. Add CI jobs for dependency audits, secret scanning, SAST, RLS migration
   checks, and security regression tests.

### Phase 3 — production validation (week 3)

1. Test OAuth with attacker/victim sessions; ensure replay, wrong-provider,
   wrong-user, and intercepted-code flows fail.
2. Load-test oversized JSON, multipart, and malicious PDFs at the Railway edge.
3. Test SSRF protections against loopback, RFC1918, IPv6 link-local, metadata,
   redirects, and rebinding DNS.
4. Independently verify production CORS, Supabase RLS, Railway network egress,
   secrets, WAF/body limits, and alerting.

## Positive controls observed

- JWT verification explicitly allows ES256/HS256 and validates the
  `authenticated` audience.
- Reviewed user-owned reads/writes generally include `user_id` scoping; no
  confirmed cross-account object access was found.
- RLS migrations set browser roles to deny-all, including waitlist data.
- OAuth refresh tokens are encrypted at rest with versioned Fernet keys and
  production startup validates encryption configuration.
- Job description HTML is sanitized before rendering; Vercel config includes
  CSP, HSTS, frame denial, nosniff, referrer, and permissions headers.
- Upload helpers and LinkedIn ZIP parsing include useful post-parse size caps.
- Direct HTTP fetches check scheme, private addresses, and redirects; NR-05
  identifies the fallback/TOCTOU gaps that remain.

## Post-remediation acceptance criteria

- [ ] OAuth state is random, one-time, expiring, provider/user bound, and PKCE
  S256 is enforced.
- [ ] Oversized requests get 413 before JSON/multipart parsing and do not
  materially increase worker RSS.
- [ ] `pip-audit` and `npm audit --omit=dev` have no unreviewed production
  findings.
- [ ] Every outbound retrieval path uses a fail-closed SSRF policy.
- [ ] Redis outage keeps conservative limits for costly actions.
- [ ] Production container runs unprivileged from a digest-pinned base image.
- [ ] Production/cloud controls are verified independently, not inferred from
  repository configuration.
