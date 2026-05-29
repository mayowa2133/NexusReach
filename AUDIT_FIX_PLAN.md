# NexusReach Audit Fix Plan — 2026-05-29

Companion to `AUDIT_2026-05-29.md`. Each fix lists: approach, files, how it's proven, and whether it needs user intervention.

**Proof strategy:** every code fix is backed by either (a) an existing test that still passes, (b) a new targeted unit test, or (c) a direct code-path demonstration. Full suite (`pytest`, `ruff`, `tsc`, `eslint`, `vitest`) is re-run after each batch.

**Order:** CRITICAL → HIGH → MEDIUM → LOW, grouped so related edits land together.

---

## Batch 1 — CRITICAL

### C1. SearXNG trust + priority labels
- **Approach:** Add `searxng_search`, `searxng_hiring_team`, `searxng_public_web` to `CURRENT_TRUSTED_SOURCES` and give them appropriate ranks in `SOURCE_PRIORITY` (mirror brave/serper ranks since SearXNG is primary).
- **Proof:** new unit test asserting searxng labels are trusted and out-rank fallback (5); full suite.
- **Intervention:** none.

### C2. Peer bucket typo
- **Approach:** `bucket != "peer"` → `bucket != "peers"`.
- **Proof:** new unit test for the title-recovery guard with `bucket="peers"`; full suite.
- **Intervention:** none.

### C3. search_jobs returns refreshed jobs too
- **Approach:** Have `_refresh_existing_job` return the job and append refreshed rows to the returned list (preserving "new vs existing" counts for refresh-run telemetry, but returning the full matched set from `search_jobs`).
- **Proof:** new test: search where all results already exist returns the existing rows, not `[]`.
- **Intervention:** none.

### C4. Dice API key → env config
- **Approach:** Add `dice_api_key` to `config.py` (`NEXUSREACH_DICE_API_KEY`). Client reads from settings; empty → Dice fails soft to `[]`. Remove hardcoded literal.
- **Proof:** unit test that client returns `[]` when key unset; ruff.
- **Intervention:** ⏭️ **USER** must (1) set `NEXUSREACH_DICE_API_KEY` in Railway + local `.env`, (2) rotate the exposed key since it is in git history.

### C5. Adzuna currency map
- **Approach:** Replace ternary with a country→currency dict covering Adzuna's supported countries; default to a sensible per-country value, fallback USD only for truly unknown.
- **Proof:** unit test mapping ca→CAD, au→AUD, de→EUR, in→INR, gb→GBP, us→USD.
- **Intervention:** none.

---

## Batch 2 — HIGH

### H1. Remove hardcoded Canada/Toronto bias
- **Approach:** Thread job/company location context into recruiter-recovery query builders and location-rank helpers. Where no location context exists, drop the geo qualifier entirely rather than defaulting to Canada. Replace Toronto-only location match with a generic match against the job's locations/country.
- **Proof:** unit tests: query builder with US job contains no "Canada"; location rank uses provided locations.
- **Intervention:** none (pure logic).

### H2. Parallelize job-aware initial bucket searches
- **Approach:** Wrap the 3 initial bucket searches in `asyncio.gather` (mirror `search_people_at_company`).
- **Proof:** full suite (existing people tests exercise this path); confirm gather usage.
- **Intervention:** none.

### H3. Parallelize job-aware title recovery
- **Approach:** `asyncio.gather` the 3 `_recover_candidate_titles` calls.
- **Proof:** full suite.
- **Intervention:** none.

### H4. Redis singleton in discovery rate limiter
- **Approach:** Reuse a module-level client/pool like `search_cache_client` does, instead of `from_url` per call.
- **Proof:** unit test asserting the same client object is reused across calls.
- **Intervention:** none.

### H5. Apollo enrich_person uses master key
- **Approach:** Use `_get_api_key()` in `enrich_person`.
- **Proof:** unit test: master-only key config makes enrich use it.
- **Intervention:** none.

### H6. Reliable job date sorting
- **Approach:** Prefer a real timestamp for ordering. Sort by `coalesce(posted_at_parsed, created_at)` — add a normalized `posted_at` parse at ingest into an existing/new sortable field, OR order by `created_at` as the stable tiebreak and only use `posted_at` when ISO-parseable. Lowest-risk: order by `created_at desc` (already populated, monotonic) as primary recency signal, keeping `posted_at` for display.
- **Proof:** test verifying ordering is by real recency, not lexicographic string.
- **Intervention:** none (decision documented inline).

### H7. URL dedup without full in-memory scan
- **Approach:** Query existing job by canonical URL with a WHERE clause instead of loading all rows and comparing in Python. Store/compare canonical URL at the DB level (use existing `url` plus canonicalization, query candidates narrowly).
- **Proof:** test confirming dedup still matches; confirm no `.all()` full scan in hot path.
- **Intervention:** none.

### H8. Pass query to startup direct fetchers
- **Approach:** Forward `query` to `search_yc_jobs`/`search_wellfound_jobs`/`search_ventureloop_jobs`.
- **Proof:** test asserting fetchers receive the query.
- **Intervention:** none.

### H9. Don't drop valid remote jobs under location filter
- **Approach:** When a job is `remote=True`, pass the location filter (remote jobs are location-eligible) regardless of HQ string, unless the user explicitly restricts to a region the remote role excludes.
- **Proof:** test: remote job w/ "San Francisco, CA" passes a "Canada" filter.
- **Intervention:** none.

### H10. Stream Google Careers feed
- **Approach:** True `iterparse` over the streamed response, clearing elements, instead of joining all chunks.
- **Proof:** parsing test on a sample feed still yields jobs; confirm no full-buffer join.
- **Intervention:** none.

### H11. Outlook token caching + locking
- **Approach:** Mirror Gmail's in-memory cache + per-user lock + expiry buffer. Capture `expires_in` from refresh response.
- **Proof:** test: second call within TTL does not re-hit token endpoint.
- **Intervention:** none.

### H12. Robust Celery async invocation
- **Approach:** Add a small `run_async` helper that uses a fresh loop when none is running and `asyncio.run` otherwise; use across tasks. (Default prefork pool works today; this hardens against pool changes.)
- **Proof:** unit test of the helper; full suite.
- **Intervention:** none.

---

## Batch 3 — MEDIUM (selected high-value; rest as time allows)

- **M1** guard location/geocode overwrite with `_apply_if_present`-style None check. Test.
- **M2** Lever: title-case/display the slug for `company_name`. Test.
- **M3** JSearch: compose location from city/state/country. Test.
- **M5** remove duplicate Plaid board entry (keep correct ATS). Code.
- **M6** `merge_startup_tags` preserve non-startup tags. Test.
- **M7** semaphore-bound employment verification. Test/inspect.
- **M8** `_balanced_candidate_mix` advance past collisions correctly. Test.
- **M9** drop location from recruiter-lead role haystack. Test.
- **M10** replace `copy.copy(person)` with a plain dict/explicit shallow build. Inspect.
- **M11** use `settings.theorg_timeout_seconds`. Code.
- **M12** log at warning instead of silent pass. Code.
- **M13** memoize LLM provider clients. Inspect.
- **M14** escape HTML in Gmail/Outlook body before `<br>` conversion. Test.
- **M16** raise Workday per-company limit / paginate. Code.
- **M17** normalize location in search-preference dedup. Test.
- **M18** route-level code-split for Dashboard charts. Build size check.

## Batch 4 — LOW (quick wins)

L1, L2, L3, L5, L9, L10, L11, L12, L13, L15 — small, local, each verified by inspection or a tiny test. L4/L6/L7 (external-site scraping fragility) are best-effort by design; will document rather than over-engineer.

---

## Items requiring USER intervention (will be skipped + documented)
- **C4** — set `NEXUSREACH_DICE_API_KEY` env var in Railway + local `.env`, and rotate the exposed key (it is in git history).
- Any additional discovered during implementation will be appended to `AUDIT_FIX_NOTES.md`.
