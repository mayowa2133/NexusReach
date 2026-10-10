# October 2026 security remediation

Scope: the seven 2026-10-10 audit findings, assuming public production with open
signup. Changes and validation are local; production has not been deployed or
tested.

| Finding | Fix | Regression coverage |
| --- | --- | --- |
| SEC-01, high: HTML CPU exhaustion | Replace backtracking HTML extraction with bounded lxml parsing. Direct-page title/text extraction runs in a killable process: 5-second wall deadline, 2-second CPU limit, 256 MiB Linux address-space limit. JSON-LD traversal is iterative. | Malformed repeated tags, normal metadata, event-loop responsiveness, existing exact-job/public-page tests. |
| SEC-03, high: anonymous waitlist amplification | Reject files on public signup. Require mailbox proof and scoped owner authorization for uploads. Shared submission/file/byte/email budgets precede resource use. Owner notification tasks also require proof. | Real Redis admission races, weighted bytes, anonymous rejection, verified-owner boundary, provider-call suppression, waitlist/request-size tests. |
| SEC-02: JWKS amplification | Pin PyJWT 2.15.1, enable key-miss cooldown, add outage backoff and validate key identifiers. Both API entry points limit bearer requests before authentication and reject oversized/duplicate authorization headers. | Concurrent misses, legitimate key rotation, outage backoff, pre-auth rejection in both apps. |
| SEC-04: profile rescoring floods | Ignore unchanged scoring fields, budget actual changes, maintain one transactional outbox row per account, coalesce edits during processing and recover expired tickets. SQL-filter stale jobs in batches of 100. | Concurrent requests/claims, edits during work, broker failure/recovery, 135-job batching, ten identical PUTs. |
| SEC-05: PDF denial of service | Pin pypdf 6.19.0 in both hash locks. Shared expiring process leases bound API/worker children. Cancellation and deadlines kill/reap children before lease release. | Real child cancellation, capacity rejection, stale-lease recovery, existing parser/document tests, dependency audits. |
| SEC-06: referral alias credits | Canonicalize Gmail/googlemail domains, dots and plus tags before campaign HMACs. Other domains retain distinct characters. Reconcile old credits under the campaign lock; keep the earliest and correct duplicate totals. | Concurrent aliases earn one credit, legacy duplicate backfill, deleted legacy identity replay, existing delete/rejoin tests. |
| SEC-07: private feedback changes shared contacts | Feedback updates the caller's CRM row and snapshots only; it has no authority to expire shared known-person records. | Both negative feedback types against private captures and previously verified contacts; assert no shared eviction. |

The API lock also updates urllib3 to 2.8.0 to clear the current dependency audit.
Both hash-locked dependency audits report no known vulnerabilities at validation.

## Default admission allowances

All application API and worker replicas must share one protected application
Redis database. The renderer still requires its isolated broker. Redis errors
refuse admission with 503; exhausted allowances return 429. Email delivery returns
false without calling its provider. Attempts are charged before work and are not
refunded after failures.

| Environment suffix (`NEXUSREACH_…`) | Default |
| --- | --- |
| `WAITLIST_DAILY_SUBMISSION_LIMIT` | 1,000 per UTC day across IPs |
| `SYSTEM_EMAIL_DAILY_LIMIT` | 500 send attempts per UTC day, including retries |
| `SYSTEM_EMAIL_RECIPIENT_DAILY_LIMIT` | 3 per canonical recipient/day; configured notification owner shares the global allowance |
| `WAITLIST_RESUME_DAILY_LIMIT` | 50 files globally/day, additionally 2 per owner |
| `WAITLIST_RESUME_DAILY_BYTES` | 262,144,000 bytes globally/day |
| `PROFILE_RESCORE_HOURLY_LIMIT` | 500 changed scoring requests globally/hour |
| `PROFILE_RESCORE_ACCOUNT_HOURLY_LIMIT` | 10 per account/hour |
| `AUTH_GLOBAL_REQUESTS_PER_MINUTE` | 3,000 bearer requests globally/minute |
| `AUTH_SOURCE_REQUESTS_PER_MINUTE` | 120 per resolved IP/minute |
| `MAX_BEARER_HEADER_BYTES` | 8,192 bytes |
| `PARSER_GLOBAL_CONCURRENCY` | 1 child across API/worker replicas |
| `PARSER_ACCOUNT_CONCURRENCY` | 1 child per subject |

Zero closes the corresponding allowance. Admission bypasses are restricted to
test/e2e. Production must use `ENVIRONMENT=production`. Parser concurrency is
conservative; raise it alongside measured memory/CPU capacity. A busy parser can
cause page retrieval to fall through to existing bounded fallbacks. These limits
do not configure provider billing caps or protect against Redis resets. Keep
Redis private and durable.

## Rollout

1. Back up PostgreSQL. Drain old API/workers before backfill; raw-key and
   canonical-key referral writers must not coexist during rollout.
2. Rebuild from both updated hash locks. From `backend/`, apply the normal
   `python -m alembic upgrade head` command (revisions 076 and 077).
3. With the application's environment and encryption keyring, run
   `python scripts/verify_rls.py` and
   `python scripts/reconcile_referral_identities.py`. The latter reports only
   identity version and unresolved count, never addresses, tokens or keys.
4. If legacy identities are unresolved, deleted addresses cannot be reconstructed
   from their HMACs. New Gmail rewards remain paused for that campaign, preventing
   unseen-alias replay. Existing counters/tombstones remain; verification and
   owner access still work. Review the campaign before issuing rewards or
   intentionally starting a new campaign. Do not clear the unresolved count just
   to re-enable rewards.
5. Restart the new API, application workers and the single Celery beat instance.
   Beat checks the outbox every minute. Expired tickets recover after 15 minutes,
   exceeding the existing 240-second task hard deadline.
6. Smoke-test email-only signup, verification, owner access, profile changes and
   cancellation. Anonymous signup keeps its generic 202; file attachments return
   422.

Verified waitlist resumes use `POST /api/referrals/resume?code=…`, an owner Bearer
credential and JSON fields `resume_filename`, `resume_content_type`,
`resume_file_base64`. Files remain capped at 5 MiB and the route body at 7 MiB.
The landing form already submits email-only; this patch adds no upload UI.

Migration 077 cannot downgrade: reverting canonical state reopens replay.
Prefer a forward fix and preserve campaign records and encryption keys.

## Validation commands

Local result: **1,962 passed, none skipped**, with the opt-in PostgreSQL tests
enabled and real disposable Redis servers. Ruff, Bandit at high severity,
repository Semgrep rules, both dependency audits, migrations from an empty
database and `verify_rls.py` pass. Existing deprecation/test-marker warnings
remain. Linux container builds and the hosted CI run were not executed locally.

Run backend tests from the repository root to seal development credentials:

```sh
backend/.venv/bin/python -m pytest backend/tests -q
ruff check backend/app backend/tests backend/conftest.py
pip-audit --no-deps --disable-pip -r backend/requirements.lock
pip-audit --no-deps --disable-pip -r backend/requirements.renderer.lock
```

Opt-in database tests deliberately use only loopback port 55439, database
`nexusreach_security_audit`, role `audit`, synthetic password `audit-local-only`.
Create `anon`/`authenticated` roles and apply all migrations there, then set
`NEXUS_SECURITY_DB_TESTS=1`. Redis regressions start and stop their own loopback
server; they require `redis-server`. The Security CI job prepares these services
and runs regressions on Linux, where address-space limits are enforced. Local
macOS checks exercise deadlines, cancellation and admission.
