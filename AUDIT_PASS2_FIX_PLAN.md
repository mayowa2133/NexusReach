# NexusReach Pass-2 Fix Plan — 2026-05-30

> **STATUS: EXECUTED — all 19 findings fixed and proven.** Backend 1155 tests pass,
> frontend 172 pass, ruff/tsc/eslint clean, build clean, migrations apply from zero.
> New migration: `046_add_job_posted_date`. New module: `app/utils/url_safety.py`.
> Proof tests: `backend/tests/test_audit_pass2_critical.py`, `_ssrf.py`, `_medium_low.py`.
> No user intervention required.

Remediation plan for the 19 findings in `AUDIT_PASS2_2026-05-29.md`. Each fix lists approach, files, and the proof that verifies it. Several findings share a root cause and are fixed together.

**Proof strategy:** the crash/SSRF/race items get *live reproductions* (same harness that proved the bug — re-run must now pass). Pure-logic items get targeted unit tests. Full suite (`pytest`, `ruff`, `tsc`, `eslint`, `vitest`, `build`) re-run after each batch.

Order: 🔴 CRITICAL → 🟠 HIGH → 🟡 MEDIUM → 🟢 LOW.

---

## Batch A — CRITICAL

### P1. Outreach list/detail/timeline crash (MissingGreenlet)
- **Approach:** Eager-load every relationship `_to_response` touches (`person`, `person.company`, `job`) in all three loaders (`get_outreach_logs`, `get_outreach_log`, `get_outreach_timeline`). For the create/update paths, re-fetch the log via the eager-loading getter before serializing (those code paths also access unloaded relationships).
- **Files:** `services/outreach_service.py`, `routers/outreach.py`, `services/draft_staging_service.py` (`_ensure_outreach_log` returns log used by callers — check it isn't serialized lazily).
- **Proof:** re-run the live Postgres repro that crashed → must list + serialize without error, with correct `company_name`/`job_title`.

### P3. ♻️ Date-sort `::date` cast crashes whole jobs list
- **Approach:** Replace the erroring `cast(substring(...), Date)` with Postgres `to_date(substring(...), 'YYYY-MM-DD')`, which is lenient (normalizes `2026-02-30` instead of raising). Verify `to_date` never raises on digit-shaped input; if it can, wrap in a validity guard. Fall back to `created_at` via coalesce as before.
- **Files:** `services/job_service.py` (`list_jobs` ORDER BY).
- **Proof:** re-run the live Postgres repro with `posted_at='2026-02-30'`/`'2026-13-01'` → query returns rows, no error; valid ISO dates still sort correctly.

### P2 + P5 + P10 + P11. Auto-send race / commit window / session poisoning / consent lag (one rewrite)
- **Approach:** Rewrite `_process_pending_sends`:
  1. Fresh `async_session()` **per user** (fixes P10 session poisoning).
  2. Re-read `auto_send_enabled` + resolve provider **per message**, right before sending (fixes P11 consent lag + disconnect-mid-cycle).
  3. **Atomic claim** before the network send: `UPDATE messages SET status='sending', scheduled_send_at=NULL WHERE id=:id AND status='staged'` and proceed only if `rowcount==1`, committing the claim first (fixes P2 double-send — a redelivered task can't re-claim; fixes P5 — a message stuck `sending` after a failed final commit is never re-selected by the `status='staged'` scheduler).
  4. On send failure: set status back to `staged` (no `scheduled_send_at`) after `rollback`, so it's visible but not auto-retried.
- **Files:** `tasks/auto_prospect.py`, `services/draft_staging_service.py` (add `claim_message_for_send` helper).
- **Proof:** live Postgres test — two concurrent claims on the same staged message: exactly one returns `claimed=True`; the other `False`. Plus a test that a `sending`-stuck message is not re-selected.

---

## Batch B — HIGH

### P4. SSRF via exact-job import
- **Approach:** New `utils/url_safety.py` with `is_safe_public_url(url)` — requires http/https, resolves host, rejects private/loopback/link-local/reserved/multicast/unspecified IPs (and unresolvable hosts). Apply:
  1. `_parse_generic_exact_url` rejects unsafe hosts → returns `None` (blocks the user entry point).
  2. `_fetch_direct_exact_page` / `_probe_workday_job_redirect` / `public_page_client.fetch_direct_page`: validate before fetch, disable auto-redirect-to-internal by following redirects manually with per-hop host validation (prevents redirect-bypass SSRF).
- **Files:** new `utils/url_safety.py`, `clients/ats_client.py`, `clients/public_page_client.py`.
- **Proof:** re-run the live localhost-SSRF repro → `parse_ats_job_url` now returns `None` for the internal URL, and the safe-fetch refuses it. A public host still parses/fetches.

---

## Batch C — MEDIUM

### P6. Cadence digest HTML injection
- **Approach:** `html.escape` every interpolated dynamic field in `cadence_digest_service._render_html` (mirror the L11 job-alert fix).
- **Proof:** unit test — a malicious `person_name` is escaped in the rendered HTML.

### P7. ♻️ `work_mode` wiped on refresh
- **Approach:** Fold `work_mode` into the same `if value is not None` guard as the other location fields in `_refresh_existing_job`.
- **Proof:** unit test — refresh omitting `work_mode` preserves the existing value.

### P8. Senior-IC hiring-manager backfill is dead code
- **Approach:** Tag the synthetic clone (`_synthetic_fallback=True`) and exempt synthetic clones from id-based dedup in `_dedupe_bucket_assignments`, so a verified senior IC survives in `hiring_managers` when that bucket is sparse (original stays in `peers`).
- **Proof:** unit test — a verified Staff Engineer peer appears in `hiring_managers` after `_finalize_bucketed` when the HM bucket was empty.

### P9. Outreach stores unvalidated `job_id`/`message_id`
- **Approach:** In `create_outreach_log`/`update_outreach_log`, verify `Job.user_id == user_id` and `Message.user_id == user_id` for any provided IDs; raise `ValueError` otherwise.
- **Proof:** unit test (live DB) — creating outreach with another user's `job_id` raises.

---

## Batch D — LOW

- **P12. ♻️ `_detached_person_copy` aliasing:** deep-copy mutable `profile_data`/`github_data` on the clone. Proof: `clone.profile_data is not person.profile_data` and nested mutation doesn't affect original.
- **P13. Known-people cache hygiene:** lookup freshness filter → `last_discovered_at`/`last_verified_at`; strip `search_*` keys before global write. Proof: unit test the strip + the filter column.
- **P14. ♻️ Legacy `ilike("%host%")` widening:** escape `%`/`_`/`\` in `host` with an `ESCAPE` clause. Proof: unit test the escaped pattern.
- **P15. OAuth redirect_uri/state:** validate `redirect_uri` against allowed origins; generate a random `state`. Proof: unit test rejecting a foreign redirect_uri.
- **P16. Export omits refresh runs:** add `JobRefreshRun` to `EXPORT_MODELS`. Proof: unit test export includes `job_refresh_runs`.
- **P17. Google feed-level category bleed:** track `in_entry` via start/end events; only seed entry fields inside an `<entry>`. Proof: unit test feed-level `<category>` doesn't leak into the first job.
- **P18. Token-cache/in-flight after disconnect:** actionable part folded into P11 (per-message connection re-check); document the bearer-token + per-process residual.
- **P19. Misleading H9 comment:** correct the comment. Trivial.

---

## Items requiring USER intervention
- None expected (all code-side). The `045` migration from pass-1 already covers schema; no new migration needed (the fixes are query/logic-level). If P16/P8 need columns, will add a migration and document.
