# NexusReach deep security audit — 2026-07-11

## Executive summary

This is a repository-grounded security review of NexusReach and the remediation
implemented on 2026-07-11. It covers the FastAPI backend,
React/Vite frontend, Chrome extension, Celery jobs, PostgreSQL/Supabase RLS,
Redis controls, OAuth integrations, untrusted document parsing, outbound web
retrieval, AI drafting and delayed auto-send, Docker images, deployment files,
dependency trees, and Git history.

The review found **no critical vulnerability**, confirmed SQL injection,
confirmed cross-user IDOR, current tracked plaintext secret, or browser-role RLS
bypass. Current Python, frontend, and E2E production dependency audits are
clean. OAuth state/PKCE, body limits, production rate-limit failure behavior,
frontend dependency upgrades, container non-root execution, and default-off
rendered crawling from the prior audit are implemented and materially improve
the posture.

The implementation and verification passes addressed all twelve findings.
NR-12 was resolved by ownership validation rather than destructive rewriting:
the exact historical Dice value is a shared client identifier published in at
least four independent public Dice integrations, not a NexusReach-issued
credential. The current tree no longer embeds it, local secret files are mode
`0600`, and three exact historical false-positive fingerprints are baselined so
Gitleaks now scans all 258 commits without suppressing future findings.

Security review cannot prove that every vulnerability has been found. This
report records the reachable issues found through source review, automated
scanning, and isolated runtime testing, plus the limits of that evidence.

## Scope and methodology

### Reviewed surfaces

- FastAPI authentication, user scoping, schemas, rate limiting, OAuth, health,
  company-logo proxy, external job search, email verification, uploads, and
  error behavior.
- PostgreSQL models/migrations and runtime RLS state.
- Redis-backed OAuth transactions, caches, budgets, and limiter behavior.
- Public-page, ATS, SMTP, crawler, redirect, and DNS handling for SSRF.
- PDF, DOCX, CSV/ZIP, and LaTeX parsing/rendering paths.
- AI prompt assembly, externally sourced context, draft staging, and delayed
  auto-send.
- React rendering/sanitization, analytics/error telemetry, OAuth callback flow,
  and Chrome extension content scripts/permissions.
- Dockerfiles, built backend image, GitHub Actions, deployment artifacts,
  dependency locks, ignored environment files, and complete Git history.

### Tests and scanners

- `pip-audit -r backend/requirements.txt`: no known vulnerabilities.
- `npm audit --omit=dev` in `frontend` and `e2e`: no known vulnerabilities.
- Gitleaks 8.28.0: full 256-commit history and current working tree.
- Bandit 1.8.6: all backend application Python.
- Semgrep 1.169.0: Python, JavaScript, TypeScript, and OWASP rule sets.
- Trivy 0.72.0: repository filesystem/configuration/secrets and the built
  `nexusreach-security-audit:local` image.
- Dockerized API with isolated PostgreSQL and Redis: migrations, health,
  request-limit behavior, and database RLS inspection.
- Schemathesis 4.22.4: property-based OpenAPI exercise across 120 operations.
- Manual trust-boundary, data-flow, and exploitability review to triage scanner
  results and find logic defects scanners do not model.

### Runtime validation results

- The API migrated and started successfully in the isolated Docker stack.
- Every base table in the runtime `public` schema had PostgreSQL RLS enabled;
  the query found zero base tables without RLS.
- A 1.2 MiB chunked JSON request was rejected with HTTP 413, confirming that the
  body limiter does not rely only on `Content-Length`.
- Concurrent first-user requests reproduced a uniqueness failure in
  `get_or_create_user` (NR-10).
- Schemathesis "missing authorization accepted" results were false positives
  caused by the deliberately enabled isolated dev-auth mode, not evidence that
  production Supabase authentication is bypassed.
- Bandit/Semgrep high-severity hash warnings were non-security fingerprints or
  Gravatar protocol hashing. No confirmed command injection or backend code
  execution emerged from those results.

## Remediation status

| ID | Status | Implemented control |
|---|---|---|
| NR-09 | Remediated | The extension now uses DOM APIs and `textContent`; LinkedIn hosts require an exact or suffix-boundary match, with injection/lookalike tests. |
| NR-10 | Remediated | Pre-auth limiting is IP-only and cannot decode JWTs or fetch JWKS; authenticated expensive actions use atomic per-user Redis budgets. |
| NR-11 | Remediated | Untrusted parsers run in killable, resource-limited subprocesses; archive/CSV bounds were added; production TeX runs on an isolated renderer queue/container. |
| NR-12 | Resolved / reclassified | The current tree uses configuration and local `.env` files are `0600`. Cross-repository verification found the exact historical Dice value in four independent public integrations, establishing it as a shared vendor client identifier rather than NexusReach-owned credential material. Exact Gitleaks fingerprints baseline only those historical false positives; full-history scanning remains enabled. |
| NR-13 | Remediated | DNS errors fail closed; outbound HTTP pins the vetted public IP while preserving Host/SNI and revalidates every redirect. Rendered crawling requires an attested egress policy. |
| NR-14 | Remediated | Daily atomic action budgets, tighter per-minute limits, bounded logo-cache cardinality, cheap liveness, and protected readiness checks were added. |
| NR-15 | Remediated | External text is explicitly marked untrusted; unsafe drafts are quarantined and revalidated before delayed sending. |
| NR-16 | Remediated | OAuth artifacts are synchronously removed before telemetry initialization; browser and backend telemetry scrub sensitive query/body fields. |
| NR-17 | Remediated | The API image is multi-stage, non-root, hash-locked, and excludes compilers/TeX; TeX is confined to the renderer image. |
| NR-18 | Remediated | PostgreSQL advisory locking serializes first-login bootstrap creation. |
| NR-19 | Remediated | The active Apps Script validates and bounds input, neutralizes formulas, deduplicates by hash, rate-limits submissions, and hides internal errors. |
| NR-20 | Remediated | Security CI, exact OAuth redirects, production API-doc controls, schema bounds, dependency audits, RLS verification, and image scanning gates were added. |

The detailed sections below preserve the original evidence and remediation
recommendations for traceability; the table above records the post-fix state.

### Post-remediation verification — 2026-07-12

The remediation was revalidated from a clean Docker runtime after the initial
implementation commit. The verification found and fixed four integration gaps:
the RLS script's direct invocation could not import the application package,
Redis-backed limiting made liveness/readiness fail with HTTP 500 during a Redis
outage, Compose omitted the required SearXNG secret, and E2E processes could
inherit real telemetry credentials from a developer `.env`. The stale real-E2E
brand assertion and a Gitleaks false positive in the launch checklist were also
corrected.

- Backend: **1,556 tests passed**; Ruff passed.
- Frontend: **214 tests passed**; ESLint and the production TypeScript/Vite
  build passed.
- Real browser E2E: the authenticated onboarding/profile persistence flow
  passed against fresh Dockerized PostgreSQL and Redis, with telemetry disabled
  by environment even when local credentials exist.
- Dependency gates: `pip-audit` on the hash-locked Python graph and production
  `npm audit` for both frontend and E2E reported zero known vulnerabilities.
- Static analysis: Bandit High-only and the repository Semgrep rules completed
  with zero findings.
- Secrets: Gitleaks found no leak in the current tracked tree or the complete
  258-commit history after applying three exact fingerprint baselines. The two
  historical Dice matches were independently verified as the same publicly
  shared vendor client identifier, and the checklist match was an empty
  assignment followed by a comment; neither baseline contains a secret value.
- Images: both the API and credential-free renderer built successfully from the
  lock file, run as the non-root `nexusreach` user, and reported **zero fixable
  High/Critical findings** in Trivy 0.72.0. The API runtime contains neither a
  compiler nor TeX; the renderer contains TeX and rejects production startup if
  application/provider credentials are injected.
- Render boundary: a real Celery task crossed Redis into the isolated render
  worker and returned a valid, bounded PDF.
- Database/runtime: all migrations applied; every application table had RLS;
  48 concurrent first-login requests all returned 200 and produced exactly one
  user, profile, and settings row; a 1.2 MiB chunked request returned 413.
- Operations: production API discovery paths returned 404 and unauthenticated
  API access returned 401. With PostgreSQL and Redis stopped, liveness remained
  200 in approximately 5 ms, hidden readiness remained 404, and authorized
  readiness returned 503 before recovering to 200 when dependencies returned.
- SearXNG: the pinned image starts healthy with a required runtime secret,
  non-root UID/GID, read-only root filesystem, all capabilities dropped, and
  `no-new-privileges`.

The GitHub runs for the initial remediation commit failed on the now-corrected
checklist false positive and stale E2E product name. A follow-up run is required
to establish green remote CI for these corrections.

## Original findings overview

| ID | Severity | Confidence | Finding |
|---|---|---:|---|
| NR-09 | High | Confirmed | LinkedIn extension constructs privileged UI with untrusted `innerHTML`; URL validation also accepts lookalike LinkedIn hosts. |
| NR-10 | High | Confirmed | Rate-limit keying can synchronously fetch JWKS on the event loop before authentication. |
| NR-11 | High | Confirmed design gap | Untrusted PDF/DOCX/CSV/ZIP and LaTeX processing lacks killable CPU/RAM/time isolation. |
| NR-12 | High | Confirmed exposure; validity unknown | A credential-like Dice API key remains in Git history; local secret files are broadly readable and duplicated. |
| NR-13 | Medium | Confirmed code defect | SSRF checks fail open on DNS error and remain vulnerable to resolve/connect DNS rebinding. |
| NR-14 | Medium | Confirmed | Several routes permit external-call, dependency, cache-cardinality, or paid-API amplification. |
| NR-15 | Medium | Confirmed design gap | Untrusted public/job/profile/reply text enters AI prompts that may feed opt-in delayed auto-send. |
| NR-16 | Medium | Confirmed | OAuth `code` and `state` can be sent to PostHog/Sentry before the callback URL is cleared. |
| NR-17 | Medium | Confirmed scanner/runtime state | Production image retains compilers and full TeX and has a large vulnerable OS package surface. |
| NR-18 | Low | Dynamically reproduced | Concurrent first login can return 500 because bootstrap creation is not an upsert. |
| NR-19 | Low (conditional) | Confirmed dormant code | Legacy public Apps Script permits spreadsheet formula injection and unbounded linear-time submissions if deployed. |
| NR-20 | Low | Confirmed hardening gaps | Security gates, production API discovery controls, exact OAuth callback matching, and fine-grained input bounds are incomplete. |

## Detailed findings

### NR-09 — Stored DOM injection in the LinkedIn companion

**Evidence.** The content script builds a fixed, maximum-z-index panel and
assigns a template string to `root.innerHTML`. The template interpolates
`personName`, `companyName`, `jobTitle`, warm-path reason, LinkedIn-signal
reason, and status without HTML escaping:
[linkedin-content.js](/Users/mayowaadesanya/Documents/Projects/NexusReach/extension/linkedin-content.js:75).
These values originate in jobs, CRM/public-profile records, search results, or
API responses and are not all trusted author input. The same script's URL
normalizer accepts any hostname containing `linkedin.com`, so
`linkedin.com.attacker.example` and `evil-linkedin.com` pass:
[linkedin-content.js](/Users/mayowaadesanya/Documents/Projects/NexusReach/extension/linkedin-content.js:10).

**Impact.** A malicious external job/person field can inject arbitrary markup
into a NexusReach-branded overlay on an authenticated LinkedIn page. Even where
LinkedIn CSP blocks inline script, injected links, forms, visual deception, and
credential/phishing UI remain possible. The permissive hostname check can
misclassify attacker-controlled URLs as LinkedIn evidence and compounds the
integrity risk.

**Remediation.** Replace the HTML template with DOM construction using
`createElement`, `textContent`, and fixed attributes/styles. If a small HTML
fragment is unavoidable, sanitize it with a strict allowlist and disallow URLs.
Accept only `linkedin.com`, `www.linkedin.com`, or a deliberately enumerated
LinkedIn subdomain set using exact/suffix-boundary comparison. Add regression
tests containing `<img onerror>`, `<a href=javascript:>`, closing tags, entity
encodings, and both lookalike host forms; assert that payloads render as text and
no attacker element exists.

### NR-10 — Synchronous JWKS retrieval in the rate-limit key function

**Evidence.** SlowAPI's synchronous key callback decodes and signature-verifies
the bearer token directly:
[rate_limit.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/middleware/rate_limit.py:20).
For asymmetric Supabase tokens, verification can retrieve JWKS over the network.
The authentication dependency correctly moves this work to a thread, but the
limiter callback does not:
[dependencies.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/dependencies.py:57).
The key callback runs before authenticated route work and falls back to IP only
after verification fails.

**Impact.** Requests carrying fabricated ES256 tokens and rotating unknown
`kid` values can cause synchronous JWKS lookups and block the async worker's
event loop. Limited public endpoints make this reachable without a valid
account; limited authenticated endpoints invoke it before their authentication
dependency rejects the token. Repeated requests can turn a remote identity
provider delay into application-wide availability loss.

**Remediation.** Never decode or remotely verify a token in the synchronous
limiter callback. Use IP for pre-auth/public limiting. After normal async
authentication, attach the verified user ID to request state and enforce a
second per-user budget in an async dependency/service. Cache JWKS with bounded
refresh, reject unknown algorithms before key lookup, add a short circuit for
unknown `kid`, and test that random bearer tokens cause no outbound network
request and do not stall a concurrent health request.

### NR-11 — Document and rendering work is not resource-isolated

**Evidence.** The current patched `pypdf` is used in strict mode and applies page
and extracted-character caps, but those checks occur after `PdfReader` has
parsed the file:
[resume_parser.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/services/resume_parser.py:36).
DOCX input is a ZIP container and is opened by `python-docx` without inspecting
member count, total expanded size, compression ratio, or XML size first:
[resume_parser.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/services/resume_parser.py:57).
LinkedIn CSV parsing materializes all rows at once after decoding the entire
payload:
[parsing.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/services/linkedin_graph/parsing.py:310).
LaTeX compilation is concurrency-limited and uses `-no-shell-escape`, but the
subprocess has no wall timeout and runs on the API host:
[latex.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/services/resume_artifact/latex.py:483).
Moving parsers or subprocess waits to threads prevents event-loop blocking but
does not stop runaway native/library work or reclaim its memory.

**Impact.** A small compressed DOCX/PDF/ZIP can expand or consume disproportionate
CPU and RAM. A malformed parser input or hanging TeX run can occupy workers
indefinitely. Concurrent authenticated submissions can degrade or terminate the
API process. Dependency upgrades reduce known-CVE exposure but do not create a
resource boundary.

**Remediation.** Run all untrusted document extraction and TeX compilation in a
dedicated worker/container with per-task memory, CPU, process, filesystem, and
wall-time limits; kill the worker on timeout. Before DOCX extraction, inspect
the ZIP central directory and reject excessive entries, per-entry size, total
uncompressed size, compression ratio, encrypted members, nested archives, and
unexpected paths. Stream CSV rows and enforce row/column/cell limits without
`list(...)`. Keep PDF source/page/text caps, add a task timeout and maximum
concurrent parsing budget, and fuzz all parsers with decompression bombs and
malformed fixtures.

### NR-12 — Credential material in history and weak local secret hygiene

**Evidence.** Full-history Gitleaks scanning found a hard-coded `x-api-key` in
two historical revisions of `backend/app/clients/remote_jobs_client.py`. It is
absent from the current tree, but remains retrievable from every clone with the
history. The working-tree scan also found actual secret-shaped values in ignored
`backend/.env` and `frontend/.env`, plus copies under stale `.claude/worktrees`.
The primary `.env` files are mode `0644`, allowing other local users to read
them. Secret values are intentionally omitted from this report.

**Impact.** If the historical key has not been revoked, repository readers can
use the associated provider account/quota. Broadly readable and duplicated
local environment files increase exposure to local accounts, backups, support
bundles, indexing, or accidental future commits.

**Remediation.** Treat the historical key as compromised: identify its owner,
revoke/rotate it, and review provider usage. If the repository has ever left a
strictly trusted boundary, rewrite/purge the secret from all refs and coordinate
clone/cache invalidation; rotation is mandatory even after a history rewrite.
Set secret files to `0600`, delete stale worktree copies, store production
secrets in the platform secret manager, and install pre-commit plus CI Gitleaks
history scanning. Maintain an owner/rotation inventory for every API and OAuth
secret.

### NR-13 — SSRF protection remains vulnerable to DNS rebinding

**Evidence.** `is_safe_public_url` explicitly allows a hostname when DNS
resolution fails:
[url_safety.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/utils/url_safety.py:38).
`safe_get` resolves to validate, then passes the hostname to HTTPX, which
resolves again before connecting:
[url_safety.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/utils/url_safety.py:137).
`_probe_workday_job_redirect` performs the same validate-then-raw-GET sequence:
[exact.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/clients/ats/exact.py:98).
Rendered crawler fallback is now disabled by default and prevalidated when
enabled, but Crawl4AI/Firecrawl still perform their own resolution.

**Impact.** A controlled hostname can resolve publicly during validation and to
a private, loopback, link-local, or metadata address during connection. A
transient lookup failure is also treated as safe. Reachability depends on the
specific ingestion route and deployment egress rules, but the application-level
guard does not enforce the security property it advertises.

**Remediation.** Fail closed on DNS errors. Resolve once and connect to a vetted
address while preserving the intended Host header and TLS SNI, or route all
outbound retrieval through an egress proxy that enforces DNS/IP policy at
connect time. Revalidate every redirect; block private, loopback, link-local,
reserved, multicast, IPv4-mapped IPv6, and cloud metadata destinations. Use
provider/domain allowlists for known ATS and API paths. Keep rendered retrieval
off until its execution network has equivalent egress enforcement. Add a
controlled DNS-rebinding integration test rather than only mocking the checker.

### NR-14 — Incomplete resource and paid-provider governance

**Evidence.** The public health endpoint performs a PostgreSQL query and Redis
ping for every request without a limiter:
[main.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/main.py:120).
The public logo endpoint accepts arbitrary unique domains without a limiter:
[companies.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/routers/companies.py:16).
Each cache miss causes an outbound favicon fetch and creates a per-domain Redis
entry:
[company_logo_service.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/services/company_logo_service.py:77).
Authenticated ATS search can invoke external ingestion without a route limit:
[jobs.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/routers/jobs.py:270).
Hunter email verification likewise lacks the limiter present on adjacent email
lookup routes:
[email.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/routers/email.py:84).
OAuth authorization-URL requests create ten-minute Redis transaction keys but
have no route budget.

**Impact.** Attackers can amplify requests into database/Redis load, outbound
traffic, cache-cardinality growth, or paid-provider calls. Valid low-cost
accounts can consume shared API quota and reduce availability for other users.

**Remediation.** Split `/health` into a cheap liveness check and an internal or
edge-protected readiness/dependency check. Rate-limit the logo proxy at the
edge and application, allow only known/stored company domains where possible,
bound cache cardinality, and coalesce concurrent misses. Add per-user,
per-provider, daily, and concurrency budgets to ATS search, email verification,
OAuth transaction creation, LLM calls, and other external-cost paths. Enforce
field/list/cardinality limits in schemas in addition to the global 1 MiB body
cap. Alert on budget rejection and provider spend anomalies.

### NR-15 — Indirect prompt injection can reach delayed auto-send

**Evidence.** Job descriptions, company descriptions, fresh LinkedIn/about
snippets, previous message bodies, and a recipient's reply snippet are inserted
directly into the drafting prompt:
[message_service.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/services/message_service.py:228),
[message_service.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/services/message_service.py:348), and
[message_service.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/services/message_service.py:409).
The system prompt has writing rules but does not label these sections as
untrusted data or instruct the model to ignore instructions embedded in them:
[message_service.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/services/message_service.py:37).
Users may opt into staging and delayed auto-send, after which background tasks
draft, schedule, and later transmit the model output:
[auto_prospect.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/tasks/auto_prospect.py:377).

**Impact.** A malicious job listing, public profile, or reply can contain prompt
instructions intended to alter the outgoing email, solicit secrets, insert
links, or damage the user's reputation. Exploitation is probabilistic and
auto-send is opt-in with a delay/cancel path, but the final message can leave the
system without a human review.

**Remediation.** Explicitly define all retrieved/job/profile/reply content as
untrusted data in the system prompt and delimit it in typed, structured fields.
Extract only necessary facts before generation; never place raw instructions
from external content into policy sections. Validate generated subject/body for
unexpected URLs, requests for credentials, hidden/encoded text, new recipients,
unsupported claims, and policy violations. Quarantine flagged drafts from
auto-send and require user review. Add adversarial prompt-injection evaluation
fixtures across every external context source and make passing them a release
gate.

### NR-16 — OAuth authorization artifacts leak into telemetry

**Evidence.** Route analytics includes `location.search`, and page-view capture
sends the full `window.location.href` to PostHog:
[RouteAnalytics.tsx](/Users/mayowaadesanya/Documents/Projects/NexusReach/frontend/src/components/RouteAnalytics.tsx:5) and
[observability.ts](/Users/mayowaadesanya/Documents/Projects/NexusReach/frontend/src/lib/observability.ts:118).
The Settings callback reads OAuth `code` and `state`, performs the backend
exchange, and only then clears the query string:
[SettingsPage.tsx](/Users/mayowaadesanya/Documents/Projects/NexusReach/frontend/src/pages/SettingsPage.tsx:170).
Sentry browser tracing is enabled without a URL-scrubbing callback:
[observability.ts](/Users/mayowaadesanya/Documents/Projects/NexusReach/frontend/src/lib/observability.ts:21).

**Impact.** Short-lived authorization codes and one-time state values can cross
into analytics/error-processing systems, browser history, or retained event
data. PKCE, server-side user binding, and one-time state consumption materially
limit code abuse, but sensitive OAuth artifacts should not leave the callback
boundary.

**Remediation.** On callback page initialization, capture required values in
memory and synchronously call `history.replaceState` to remove query/hash before
analytics initializes or any exchange request. Page analytics should record a
route template/path only, never raw query/hash. Add central PostHog property
sanitization and Sentry `beforeSend`/`beforeSendTransaction` URL scrubbing for
`code`, `state`, tokens, emails, and connector session values. Delete affected
historical telemetry where supported and add a browser test asserting no
observability call contains callback parameters.

### NR-17 — Production image has excessive vulnerable OS surface

**Evidence.** The built backend image is approximately 2.58 GB. The Dockerfile
is digest-pinned and runs as `nexusreach`, but its single stage retains
`build-essential`, compilers, `curl`, and a full TeX installation:
[Dockerfile](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/Dockerfile:1).
Trivy reported 1,663 OS-package findings: 10 Critical, 103 High, 410 Medium,
1,108 Low, and 32 Unknown. Python and Node packages in the image had zero known
findings. Many OS findings have no Debian fix and not all flagged libraries are
reachable from normal application paths, so these counts are exposure signals,
not 1,663 demonstrated exploits.

**Impact.** Any application compromise lands in a runtime containing compilers,
download tooling, and a much larger library set than the web API needs. The
attack surface increases exploit chaining and post-exploitation capability and
makes vulnerability triage noisy.

**Remediation.** Use a multi-stage wheel build and omit `build-essential` and
`curl` from runtime. Prefer moving TeX into the isolated rendering worker from
NR-11; if it must remain, use the smallest tested TeX subset and rebuild on a
regular cadence. Produce an SBOM, run Trivy/Grype on every image, define a
time-bounded exception format for unfixed/unreachable CVEs, and block releases
on fixable Critical/High findings. Keep the digest pin and non-root user.

### NR-18 — First-login bootstrap race returns 500

**Evidence.** `get_or_create_user` selects the user and, when absent, inserts
User, Profile, and UserSettings before commit without conflict handling:
[dependencies.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/dependencies.py:80).
Concurrent isolated API requests for the same first-time identity both observed
no row; one commit then failed with `UniqueViolationError`. This was reproduced
during Schemathesis testing.

**Impact.** Normal browser concurrency or deliberate parallel requests can
cause a first-time user's requests to return 500 and poison that request's
transaction. This is primarily availability/reliability, with limited security
impact.

**Remediation.** Use PostgreSQL `INSERT ... ON CONFLICT DO NOTHING` for User,
Profile, and UserSettings, then select the canonical user. Alternatively catch
the integrity error, roll back, and retry safely, but an atomic upsert is
preferable. Emit signup analytics only for the request that actually inserted
the user. Add a database-backed concurrency regression test.

### NR-19 — Legacy waitlist Apps Script is unsafe if still deployed

**Evidence.** The legacy Google Apps Script accepts public form data and writes
untrusted values with `appendRow` without neutralizing formula prefixes:
[waitlist-google-apps-script.gs](/Users/mayowaadesanya/Documents/Projects/NexusReach/frontend/waitlist-google-apps-script.gs:34).
It performs linear spreadsheet scanning for email deduplication and has no
application rate limit. The current frontend posts to the FastAPI waitlist
route, so this file appears dormant; deployment state was not available.

**Impact.** If the script remains publicly deployed, values beginning with
`=`, `+`, `-`, or `@` can become spreadsheet formulas when staff open/export
the sheet. Public spam can also make each request increasingly expensive.

**Remediation.** Remove and undeploy the script if unused. Otherwise prefix
formula-leading cells with an apostrophe, validate tight lengths and formats,
use indexed storage/deduplication, enforce quotas/bot protection, restrict the
deployment where feasible, and add malicious spreadsheet-formula tests.

### NR-20 — Security assurance and production hardening gaps

**Evidence.** GitHub Actions runs lint, tests, builds, and E2E, but no dependency
audit, secret-history scan, SAST, image scan, SBOM, or migration/RLS assertion:
[ci.yml](/Users/mayowaadesanya/Documents/Projects/NexusReach/.github/workflows/ci.yml:1).
FastAPI OpenAPI/docs remain enabled by default in production. OAuth redirect
validation accepts any path/query on an allowed origin rather than an exact
registered callback:
[email.py](/Users/mayowaadesanya/Documents/Projects/NexusReach/backend/app/routers/email.py:44).
Several schemas rely on the coarse global body cap rather than explicit
per-field and list cardinality limits. The obsolete SearXNG Dockerfile remains
unpinned and does not declare a non-root user or healthcheck:
[Dockerfile](/Users/mayowaadesanya/Documents/Projects/NexusReach/deploy/searxng/Dockerfile:1).

**Impact.** Regressions can merge without automated detection, API discovery
reduces attacker reconnaissance cost, broad callback matching increases future
OAuth redirect mistakes, and stale deployment artifacts can be accidentally
revived with unsafe defaults. These are defense-in-depth gaps rather than a
currently demonstrated compromise.

**Remediation.** Add blocking CI jobs for locked production dependency audits,
Gitleaks full-history/diff scans, Semgrep/Bandit, Trivy filesystem/image scans,
SBOM generation, and a migrated-database RLS assertion. Disable or authenticate
OpenAPI/docs in production. Match exact OAuth callback URIs from configuration.
Add explicit string, collection, row, URL, and nested-object bounds to all
externally reachable schemas. Remove the SearXNG artifact if obsolete; otherwise
pin it by digest, verify its runtime user, add a healthcheck, and scan it.

## Status of the 2026-07-10 findings

| Prior ID | Status | Current assessment |
|---|---|---|
| NR-01 OAuth state/PKCE | Remediated | Authenticated server-side transactions bind user/provider/redirect URI, use PKCE, expire, and are consumed once. Exact callback matching and telemetry scrubbing are now implemented. |
| NR-02 body limits | Remediated | ASGI limit handles declared and chunked bodies; Docker validation returned 413 for an oversized chunked request. Edge limits are still recommended. |
| NR-03 multipart CVEs | Remediated | Current `python-multipart` audit is clean and untrusted parsing is resource-isolated. |
| NR-04 pypdf CVEs | Remediated | Current dependency is clean; strict parsing/caps and a killable parser subprocess bound pre-cap work. |
| NR-05 SSRF | Remediated | DNS fails closed and validated public IPs are pinned through connect and redirect handling; rendered fetch requires attested egress policy. |
| NR-06 fail-open limits | Remediated | Production requires Redis for protected application limits; pre-auth keying is network-free and per-user action budgets are atomic. Operational probes deliberately bypass Redis so they report outages correctly. |
| NR-07 frontend advisories | Remediated | Current frontend production audit is clean. |
| NR-08 container root/build | Remediated | Digest-pinned multi-stage API and renderer images run non-root; compilers/TeX are absent from the API, and both images pass the High/Critical gate. |

## Original prioritized remediation plan

This plan is retained for traceability. Every applicable implementation item
below is complete and verified; NR-12's original rotation/rewrite action was
superseded by evidence that the value is a vendor-published shared identifier,
not a NexusReach-owned credential.

### Phase 0 — immediate containment (0–48 hours)

1. **NR-12:** Revoke/rotate the historical Dice-like API key, inspect provider
   usage, restrict local `.env` files to `0600`, and remove stale copies.
2. **NR-09:** Disable or feature-flag the LinkedIn overlay for externally sourced
   context until all interpolated values use text nodes. Fix hostname validation
   in the same patch.
3. **NR-10:** Change pre-auth limiter keying to IP-only so no request-path JWT
   verification can perform synchronous network I/O.
4. **NR-15:** Disable delayed auto-send for newly generated drafts or require
   explicit review until prompt-injection controls and output validation ship.
5. **NR-19:** Confirm whether the Apps Script is deployed; undeploy it if unused.

### Phase 1 — close direct application risks (days 2–7)

1. **Extension safety:** replace `innerHTML`; implement exact LinkedIn host
   validation; add DOM-injection and lookalike-host tests.
2. **Limiter architecture:** separate IP pre-auth and verified-user post-auth
   budgets; add no-network and event-loop-liveness tests.
3. **SSRF:** fail closed, remove raw validate-then-fetch calls, enforce
   connect-time IP policy/egress proxy, and add redirect plus rebinding tests.
4. **Resource budgets:** protect health/logo, rate-limit ATS/Hunter/OAuth state
   creation, add provider daily budgets/concurrency caps, and bound cache keys.
5. **OAuth privacy:** synchronously clear callback parameters, sanitize PostHog
   and Sentry, purge retained callback URLs where possible, and add browser tests.
6. **Bootstrap race:** implement transaction-safe upserts and a concurrent
   first-login integration test.

### Phase 2 — isolate high-risk processing (week 2)

1. Create a dedicated parser/renderer worker image with no cloud credentials,
   no database superuser credentials, read-only root filesystem, ephemeral
   scratch space, outbound network disabled, and strict CPU/RAM/PID/time limits.
2. Add DOCX/ZIP central-directory guards, streaming CSV limits, PDF task limits,
   LaTeX wall timeout/kill behavior, and global per-user/concurrent work budgets.
3. Build a malicious-file corpus and fuzzing harness; verify worker termination
   and cleanup after timeout/OOM/parser crash.
4. Add structured untrusted-context handling, output policy checks, adversarial
   AI evaluations, and a mandatory-review quarantine for suspicious drafts.

### Phase 3 — supply chain and continuous assurance (weeks 2–3)

1. Split build/runtime images and move TeX out of the web image; remove compiler
   and download tooling; rebuild and re-scan until fixable Critical/High OS
   findings are zero or formally excepted with owner/expiry/reachability.
2. Add CI security gates: pip/npm audits, Gitleaks, Semgrep/Bandit, Trivy,
   generated SBOM, image signature/provenance, RLS checks, and security tests.
3. Hash-lock Python artifacts/wheels, pin every deployment image by digest, and
   automate update PRs and monthly base-image refreshes.
4. Disable/guard production docs, exact-match OAuth callbacks, remove stale
   SearXNG deployment code, and add explicit schema/cardinality bounds.
5. Schedule quarterly authenticated staging penetration tests and annual cloud
   IAM, Supabase, DNS, observability-retention, and third-party OAuth reviews.

## Remediation acceptance criteria

- No extension path assigns externally influenced strings to `innerHTML`; the
  malicious DOM corpus renders only text, and lookalike LinkedIn hosts fail.
- Random bearer tokens never trigger JWKS/network access from the limiter and
  do not delay unrelated concurrent requests.
- Every URL-fetching implementation enforces connect-time public-IP policy;
  DNS-error, redirect-to-private, IPv6, metadata, and rebinding tests pass.
- Parser/render tasks are executed outside the API process and are forcibly
  terminated within configured CPU/RAM/wall limits; ZIP bombs and oversized
  CSV/PDF/TeX fixtures fail safely.
- Every external-cost route has documented per-minute, daily, and concurrency
  budgets with deterministic Redis-outage behavior.
- No PostHog/Sentry event contains OAuth code/state, access/refresh tokens,
  connector session tokens, or raw URL query/hash values.
- Prompt-injection evaluation fixtures cannot cause automatic transmission of
  unexpected links, credential requests, unsupported claims, or altered
  recipients; suspicious outputs require review.
- Historical scanner matches are ownership-validated and narrowly baselined by
  fingerprint, local secret files are `0600`, Gitleaks passes on all refs/diffs,
  and no secret copies remain in stale worktrees.
- Trivy reports no unexcepted fixable Critical/High runtime findings; runtime
  contains no compiler/download tool unless explicitly justified.
- Concurrent first-login test returns successful, consistent user/profile/
  settings state with exactly one signup event.
- CI blocks regressions in dependencies, secrets, SAST rules, RLS, body caps,
  OAuth binding/privacy, extension DOM safety, and container policy.

## Positive controls observed

- JWT algorithms and audience are constrained; normal verification is moved off
  the event loop in the authentication dependency.
- User-owned database queries are generally scoped by `user_id`; no confirmed
  IDOR or SQL injection was found in reviewed routes.
- All runtime public tables have RLS enabled.
- OAuth uses authenticated, expiring, provider/user-bound state plus PKCE and
  one-time consumption.
- Request-size middleware rejects both declared and chunked oversized bodies.
- Production limiter initialization fails closed when Redis is unavailable.
- Current Python/frontend/E2E production dependencies have no known audit
  findings.
- Job-description HTML is sanitized in the React app; dangerous rendering found
  in this audit is isolated to the extension panel.
- LaTeX runs with `-no-shell-escape`, input escaping, constrained TeX file access,
  and a concurrency semaphore.
- The production API image is digest-pinned and runs as a non-root user.
- Rendered crawlers are disabled by default.

## Limitations

This audit did not perform destructive testing against production, inspect live
Railway/Vercel/Supabase IAM and network policy, validate third-party dashboards
or secret-rotation status, examine organization-wide Git forks/caches, audit
browser-extension store packaging/signing, or conduct a third-party model
red-team against every supported LLM. Findings that depend on deployment state
are explicitly marked conditional. A clean scanner result means no matching
known signature was found; it is not proof of safety.
