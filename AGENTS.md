# NexusReach — AI Agent Context

Last updated: 2026-09-06

This file is the current AI-facing project snapshot for NexusReach. It is intended for Codex, Claude, and other repo-aware assistants. `CLAUDE.md` intentionally mirrors the same project story so different tools inherit the same context.

## Branch layout

- **`main`** — canonical branch; the shipped product. Includes the keyless Jina Reader page-fetch fallback (`backend/app/clients/jina_reader_client.py`, wired into `public_page_client.fetch_page`, LinkedIn-guarded, on by default). Its real-world value is being measured — see the `REVIEW 2026-08-06` note in `public_page_client._log_retrieval_outcome`.
- **`demo-mode`** (`origin/demo-mode`) — **in-progress, NOT merged.** A fail-closed synthetic "demo mode" for local browser-product testing: it only starts against loopback e2e/demo databases, forces dev auth, and refuses every external provider/telemetry credential. Lives entirely on this branch — `main` does NOT contain it. Files: `backend/app/middleware/demo_mode.py`, `demo_mode` + `_validate_demo_config` in `backend/app/config.py`, `backend/scripts/demo_reset.py`, `scripts/demo_*.sh`, `e2e/playwright.demo.config.ts` + `e2e/tests-demo/`, `frontend/src/lib/demoMode.ts` (+ test), plus edits to `main.py`, `routers/profile.py`, `jobs/command_center.py`, `AppLayout.tsx`, `main.tsx`, `README.md`, and the `.env` examples. It was branched off `main` after Jina landed, so it depends on `main`'s `jina_reader_enabled` config — keep it rebased on `main`. To work on demo mode: `git checkout demo-mode`.
- **`security/remediation-2026-09`** — **merged into `main`** (PR #40, September 2026). Kept named here because the audit remediation is easier to find by branch than by trawling `main`'s history: commit `3b59e4ac` plus migrations `068`–`074` carry renderer isolation, paid-work reservations, durable deletion receipts, client-capture provenance, the send-attempt ledger, referral credential/campaign tables, JWT claim validation, and least-privilege grants on internal tables. Everything marked "September 2026" in this file is on `main` now; the follow-up commits on the branch also fixed three places where the hardening outran its own test scaffolding (an unpinned issuer in a JWT unit test, a missing `iss` claim in the E2E token, and first-time bootstrap having no Supabase admin API to consult in the harness).

## What this product is

NexusReach is a networking assistant for job seekers. It helps a user:
- import or discover relevant jobs
- find recruiters, hiring-side contacts, and peers at the target company
- recover LinkedIn/public profile evidence for those people
- surface warm paths from the user's imported first-degree LinkedIn graph
- find or guess work emails safely
- draft outreach messages, stage email drafts, and optionally auto-send staged email drafts after a user-configured delay
- track networking activity in a lightweight CRM

NexusReach defaults to draft-first workflows. Users can optionally enable delayed auto-send for staged email drafts and cancel scheduled sends before they go out.

## Current product snapshot

### Jobs and company intake
- Job aggregation exists for JSearch, Adzuna, Dice, remote/public boards, curated GitHub job lists, `newgrad-jobs.com`, and Job Bank Canada (national board, Canada-only, fail-soft scrape).
- `newgrad-jobs.com` ingestion is now two-stage:
  - list-page discovery for title/company/date/URL
  - detail-page enrichment for location, employment type, work mode, salary, level label, and description
- Board-backed ATS support exists for:
  - Greenhouse
  - Lever
  - Ashby
- **The curated ATS registry auto-grows.** Beyond the hand-curated `constants.ATS_DISCOVER_BOARDS` / `LEVER_DISCOVER_SLUGS`, `scripts/discover_ats_boards.py` is the "do what JobRight does" engine: it takes a big multi-industry seed of company *names* (a curated list + every company on the SimplifyJobs lists + the all-industry The Muse companies API + the free `yc-oss` YC company list — ~7.2k names), slugifies each, probes Greenhouse/Lever/Ashby, and **verifies every hit against the board's real company name** (Greenhouse `name` / Ashby `organizationName`; Lever has none so it requires an exact slug match) so a slug collision can't add the wrong company, and rejects staffing/gig aggregators via a job-count ceiling (>500 openings) + a generic-slug denylist (so a board named `pulse` with 2.5k NHS staffing roles can't pollute the feed). Output is committed to `app/data/discovered_ats_boards.json` and loaded by `jobs/discovered_boards.load_discovered_boards()` (deduped against the hand-curated lists, fail-soft, `lru_cache`d). The crawl (`fetch_curated_ats_source_payloads`) fans these in through the same ATS adapters and **stamps the verified company name** on the jobs (the board APIs sometimes return only the slug). Now: **+985 verified employers / ~24k jobs** from a ~7.2k-company seed, taking the Greenhouse/Lever/Ashby registry to ~1,117 — free, with direct employer apply links, spanning healthtech/fintech/climate/consumer (not just SWE). The seed includes a curated **marketing-heavy consumer / media / martech / DTC** block (HelloFresh, Klaviyo, The New York Times, Vox Media, Sprout Social, Reformation, Impossible Foods, …), plus broad non-tech-recruiting verticals — legal tech (Relativity, DISCO, Everlaw), adtech (The Trade Desk, DoubleVerify), HR tech (Justworks, Culture Amp), insurtech, proptech, gaming, education/nonprofit (Khan Academy, Code.org) — that lift the general-professional and thin categories because those brands post the most marketing / brand / comms roles and seasonal marketing internships — the non-tech-recruiting employers the original SWE-leaning seed missed. Re-run the script to refresh; dead boards fail soft. This is the highest-leverage lever for both volume and non-tech coverage. Do **not** scrape LinkedIn/Indeed to chase more (anti-bot + the legal risk that killed Proxycurl) — aggregate ATS boards directly.
- Exact-job URL ingestion exists for:
  - Workable
  - Apple Jobs
  - Workday exact-job URLs on `*.myworkdayjobs.com`
  - generic exact-job hosts when metadata is parseable
- Proprietary careers pages can import through the exact-job pipeline when the page exposes enough metadata. In practice this is how some Microsoft and Uber roles are handled.
- Startup-first discovery now exists as a separate manual flow:
  - direct startup boards:
    - Y Combinator Jobs
    - VentureLoop
    - Wellfound (best-effort; may fail soft when blocked)
  - startup ecosystems that resolve to ATS/exact-job imports:
    - Conviction Jobs / Mixture of Experts
    - a16z Speedrun companies
- Startup provenance is source-based only in v1 and stored in reserved job tags:
  - `startup`
  - `startup_source:<source_key>`
- Job import now canonicalizes URLs and dedupes by `source + external_id` first, then canonical URL, then fingerprint.
- Job discovery is occupation-aware, and routing is keyed on whether the search is **engineering-relevant**, not just "industry-bound non-tech". The engineering-only job boards — Dice, Jobicy, **Remotive** (which *ignores the query* and returns its own tech feed), Simplify, and the newgrad-jobs tech scraper / curated ATS crawl — only ever carry tech roles, so they run only when the resolved occupations include an engineering-relevant one (`constants.ENGINEERING_RELEVANT_OCCUPATIONS`: software_engineering, data_engineer, ml_ai, cybersecurity, engineering_development, data_analyst, product_management) **or** no occupation is specified (the default SWE-leaning feed). A purely non-engineering search (marketing, sales, finance, HR, …) uses the broad all-industry aggregators (`constants.ALL_INDUSTRY_DISCOVER_SOURCES` = JSearch / Adzuna / The Muse) **plus** the curated non-tech vertical boards — it never pulls the engineering boards, because they don't carry those roles and (worse) injected engineering jobs that the discover-hint fallback then mis-tagged with the search occupation (a "Senior Quality Engineer" surfacing under Marketing). See `constants._engineering_relevant`; the older `_suppress_tech_sources` / `INDUSTRY_BOUND_NONTECH_OCCUPATIONS` still exist but routing now goes through `_engineering_relevant`. Non-engineering roles at tech employers still reach the feed via the hourly global ATS board crawl, tagged by title classification. **Occupation tagging is by the job's own title/description (`occupation_tags_for_job` → `classify_title`), with the discover-hint only as a last-resort `fallback_keys`.** `classify_title`'s aliases must stay broad enough to recognize a category's real titles without the literal category word (e.g. marketing covers Brand Manager / Social Media / Content Strategist / SEO / Communications / PR / Media Buyer / Campaign Manager) and specific enough to avoid generic collisions (the arts aliases use "art director"/"film producer"/"video editor", never bare "director"/"producer"/"editor", which matched *every* "… Director" title). The daily `tasks/jobs.retag_occupation_tags` beat re-runs `storage.recompute_occupation_tags` over stored jobs to self-heal tags after any classifier/routing change (drops stale fallback tags, adds newly-recognized ones; non-occupation tags preserved).
- **The Muse** (`themuse_client`) is the cross-industry, **free + keyless** breadth source that gives *every* occupation real curated depth independent of the paid aggregators. This matters because JSearch/Adzuna are the only other industry-agnostic sources and are single points of failure (JSearch is monthly-quota-capped — currently HTTP 429 — and Adzuna needs keys), while everything else (Dice/Simplify/Jobicy/newgrad/Remotive) is tech-only; without The Muse a non-SWE category collapses to ~0 when those two are down. The public API filters by a fixed `category` taxonomy that maps onto our occupations (`MUSE_CATEGORY_BY_OCCUPATION`, every category name live-verified — a wrong name silently returns nothing). Occupation-routed discovery passes the category directly and gates results to titles sharing a *distinctive* taxonomy token (TF-IDF auto-derived over occupation alias/seed vocab in `_build_distinctive_vocab`, so generic words like "manager"/"director" can't make every title match); the free-text saved-search path maps query→category and token-filters back to the query. It's in `DEFAULT_SEARCH_SOURCES` (so every saved-search refresh gets it) and both `discover_jobs` source lists; `publication_date` gives a precise `posted_ts`; fails soft to `[]` on quota/error. Optional `NEXUSREACH_THEMUSE_API_KEY` only raises the rate limit.
- **Early-career volume (new-grad + internships) is a first-class goal — coverage = more chances.** The dedicated tech early-career source is the SimplifyJobs GitHub lists (`remote_jobs_client.fetch_simplify_early_career_jobs`): it pulls *both* `SimplifyJobs/New-Grad-Positions` **and** `SimplifyJobs/Summer2026-Internships` (+ `vanshb03/Summer2026-Internships`), each level-stamped from the source list (`level_label` New Grad / Internship → `new_grad` / `intern`), ↳-repeat-company-aware, 🔥/⭐-marker-stripped, deduped — ~590 roles (224 new-grad + 366 internships), up from the old 50-cap new-grad-only (internships were ~0). The big SimplifyJobs repos are HTML tables now, so `_parse_simplify_html_jobs` (not the markdown path) carries the level. `simplify` is in `DEFAULT_SEARCH_SOURCES`, so it refreshes every cycle. For **non-tech** early-career, The Muse `boost_early_career` adds dedicated `Entry Level` + `Internship` level pulls on top of the all-levels pull (additive budget so senior roles never crowd them out) across every occupation — wired on for the `themuse` source. The Muse's own `level` is stamped as `level_label` so experience classification is authoritative, not title-guessed. Net: a SWE discover now yields ~600+ early-career roles vs ~50 before. Non-tech early-career has no GitHub-list equivalent (those are all tech), so The Muse *is* the non-tech early-career substrate — and it's deep (Healthcare ~3.6k internships, Education/Business-Ops ~3k entry-level, Marketing ~440). The boost harvests it with a dedicated `_EARLY_CAREER_BUDGET` (200/call, split across the Entry-Level + Internship × category specs, paging up to `_MAX_PAGES_HARD_CAP`=12), yielding ~50–100 *clean* early-career roles per non-tech occupation per call (up from ~41). The distinctive-token relevance gate is kept on the early-career specs too — without it The Muse floods every category's entry level with mis-tagged retail roles ("Tire Center Associate"), so category+level alone is NOT a safe relevance signal. The genuine free-source ceiling for non-tech early-career is The Muse; Adzuna (free tier, key-gated, currently unset) is the broad all-industry source that would close the remaining gap to the tech GitHub-list depth.
- Curated **non-tech vertical boards** are the employer-list analog of the tech ATS boards: `workday_client.WORKDAY_NONTECH_COMPANIES` is a live-verified registry of large Workday employers tagged by vertical (`healthcare` health systems, `education` universities, `finance` banks/insurers, `retail` retailers). `job_service.OCCUPATION_VERTICALS` / `verticals_for_occupations` route an occupation to the verticals that actually hire it. Because these large employers staff a full back office, the general-professional functions (finance/HR/marketing/business-analysis/project-management/management) route to **all four** verticals via `ALL_NONTECH_VERTICALS` (a hospital posts accountants the same way a bank posts payroll staff); legal → finance+healthcare+education, sales/support → finance+retail, supply chain → retail+healthcare; pure-tech engineering occupations pull none and rely on the tech ATS boards + The Muse. Relevance is handled downstream by occupation tagging + the feed's occupation filter, exactly as for tech ATS boards. The per-company fetch limit is 40 (raised from 20, near tech parity). `discover_jobs` calls `_discover_nontech_vertical_boards` additively — it fires whenever the resolved occupations have a vertical home, *independent* of the tech-suppression decision (a finance seeker isn't suppressed but still gets banks; a nurse is suppressed and still gets hospitals). The hourly refresh (`tasks/jobs._discover_all_boards`) folds every non-tech employer into the `workday:curated` payload, so saved-search matching keeps non-tech jobs fresh the same way it does Stripe/OpenAI for engineers. Every Workday config (`wd` tier + `site`) is verified against the live jobs API — a wrong value silently returns nothing, so do not add unverified employers.
- **Government** is its own vertical served by USAJobs, not Workday (agencies don't post on the curated tenants). `public_sector_government` → `{government}` → `_discover_government_jobs` → `usajobs_client` on on-demand discover, and the weekly refresh fanout (`tasks/jobs._discover_all_boards`) folds USAJobs gov-query results into the `usajobs` payload too, so a saved government search stays fresh the way a nurse's does. The USAJobs client is gated on `NEXUSREACH_USAJOBS_API_KEY` + `NEXUSREACH_USAJOBS_USER_AGENT` and **fails soft** to `[]` when unset, so government discovery still works via the broad aggregators and simply gains the official federal board when the key is present.
- **Canada is a first-class region, not a US afterthought** (the product targets Canadians + Americans). Two additions close the historical US-skew: (1) the curated ATS boards now include verified Canadian-HQ employers (Lightspeed, Cohere, Neo Financial, Hopper, 1Password, Wealthsimple, Jobber, Waabi, Hootsuite, … — see the "Canadian-HQ employers" blocks in `constants.ATS_DISCOVER_BOARDS` / `LEVER_DISCOVER_SLUGS`, each verified live via `scripts/verify_canadian_ats_boards.py`); and (2) **Job Bank Canada** (`app/clients/jobbank_client.py`) — Canada's national board, all occupations incl. non-tech, scraped from the public jobsearch page (no JSON API exists; the open-data CSV is monthly + URL-less). It's **best-effort, fails soft to `[]`** like the newgrad/Wellfound scrapers, and is **auto-added in `search.search_jobs` whenever the location resolves to Canada** (`_adzuna_country_for_location(...) == "ca"`) — so it covers discover, saved-search refresh, and ad-hoc paths without per-call wiring, and never wastes calls on US locations. Job Bank card titles are the NOC-standardized title (the employer-specific title lives on the unscraped detail page).
- **Legal and arts/entertainment** are deliberately left to the broad aggregators: law firms and studios/agencies are fragmented across bespoke sites with no free curated substrate, so there is no curated registry for them (their occupation taxonomy `default_search_queries` seed the aggregators instead). Don't fake-cover them with unverified Workday/ATS guesses.
- **Workday config drift is handled, not silent.** Tenants migrate `wd` tiers/sites and a drifted config returns nothing. `workday_client.verify_workday_config` probes a config and auto-repairs across known tiers; `verify_all_workday` runs the whole registry. `scripts/verify_workday_boards.py` is the manual refresh tool (prints paste-ready repaired lines, non-zero exit on dead entries), and `tasks/jobs.verify_curated_boards` is a weekly Celery health-check that WARNING-logs drifted/dead configs so they're visible. Tenants whose anonymous bulk API is disabled (return `total=0`/HTTP 422 — e.g. Qualcomm, Dell, IBM) are unharvestable through this client and were removed rather than left as silent dead weight.

### People discovery
- People discovery is no longer Apollo-only.
- Current discovery stack is:
  1. Apollo company/org enrichment where available
  2. search-provider router for web/LinkedIn discovery
  3. hiring-team search
  4. bounded The Org traversal when buckets underfill or the company is ambiguous
  5. LinkedIn backfill for verified The Org/public-web candidates
- The People page and job-aware people flow return three buckets:
  - recruiters
  - hiring managers
  - peers
- An occupation gate (`app/services/people/occupation_gate.py`) rejects candidates whose function clearly differs from the job's (e.g. an Engineering Manager surfaced by x-ray for a sales req) from the hiring-manager and peer buckets — coarse function groups (technical / gtm / corporate / creative / domain) so adjacent functions still pass; pre-validated contacts (posting/hiring-team/github-team) bypass all heuristic gates. For known non-engineering occupations, manager/peer/recruiter title seeds come from the occupation taxonomy (not engineering scaffolding) and engineering-flavored team keywords are dropped, so a sales role searches for sales people.
- Two non-technical leadership sources fill the gap where GitHub does not apply: the company's own website leadership/team page (`app/services/people/company_site.py` — probe common paths, LLM-extract named leaders+titles, cached/fail-soft; the non-tech analog of GitHub-team and the highest-recall source for the long tail The Org misses) executives quoted by exact title in news/PR (`tavily_search_client.search_executive_quotes`), and leaders found via speaker/podcast/byline mentions and X/Twitter bios (`app/services/people/public_footprint.py`). The company-site parser also probes domain people-directories (/attorneys, /faculty, /providers, ...) and uses SERP-assisted page discovery; it works on server-rendered sites and fails soft on JS-rendered SPAs (where the SERP-based news/footprint miners cover instead). Both are company-verified (own domain / press), run for non-engineering roles, route into the hiring-manager bucket through the occupation gate, and rank just below team-confirmed contacts. All three (site/news/footprint) are gathered by the shared `people/service._gather_nontech_leaders` helper, which runs in **both** the job-aware (`search_people_for_job`) and People-page company (`search_people_at_company`) flows, so non-tech recall is identical whether the user starts from a job or browses a company.
- **Cross-source corroboration** is an accuracy signal in all three buckets: when ≥2 independent strategies surface the same person, `candidates._dedupe_candidates` unions the distinct `source` values onto `_corroborated_by` (instead of silently dropping the duplicate), and `ranking._corroboration_rank` sorts corroborated candidates ahead of equally-titled singletons. It sits just below the strong direct-evidence tiers (GitHub-team, published-leader) and helps tech and non-tech equally. (Client capture is no longer one of those tiers — see the hiring-team-capture bullet below.)
- **Recruiter discovery** additionally mines the company's own recruiting/talent-team page (`company_site.discover_company_site_recruiters` — TA-specific paths + SERP, recruiter-tuned LLM extraction, regex-filtered to recruiting titles, own-domain → strong-signal). It runs for every role type (recruiters are universal) via the shared `people/service._gather_company_site_recruiters` helper in both flows, and is the best free recruiter source when the companion's hiring-team capture isn't available.
- People discovery additionally mines the posting itself (named contact emails rank first; reporting-line titles seed the HM search), searches LinkedIn feed posts for the recruiter who announced the exact req, annotates shared school/past-employer affinity from the user resume, applies bounded reply-rate priors from the user own outreach history, and accepts contact feedback that evicts bad known-people cache rows.
- For engineering roles at companies with public repos, the GitHub-team strategy (`app/services/people/github_team.py`) resolves the recent contributors to the org repos matching the job team keywords into LinkedIn titles: lead/manager-titled, company-evidenced contributors become hiring-manager candidates, the rest become high-confidence peers on GitHub evidence alone. GitHub-team membership is the strongest signal in the hiring-manager and peer rankings. Org slug is derived from the company name and validated via the GitHub API (cached). Recency-ranked (recent commits, not all-time) so departed heavy committers do not surface; former-employee and wrong-person LinkedIn matches are filtered.
- The companion can capture LinkedIn's "Meet the hiring team" panel from a job page the user is viewing (`POST /api/people/hiring-team-capture`, `app/services/people/hiring_team_capture.py`). **Since the September 2026 audit a capture is an unverified client assertion, not evidence** (migration `068`): the source label is `client_capture` (was `linkedin_hiring_team`), each stored `Person` carries `provenance="client_capture"` with `current_company_verified=False`, verification status `unverified`, no evidence and `_employment_status="ambiguous"`; a supplied `job_id` must belong to the caller or the request 404s; and the capture is **never** written to the global known-people cache (`linkedin_hiring_team` / `client_capture` are in `GLOBAL_CACHE_BLOCKED_SOURCES`, and `is_cache_eligible` additionally rejects any candidate carrying the capture marker). Rows the old path had already published were flipped to `verification_status='quarantined'` and are excluded from every cache read/count. The capture is still the broadest-coverage recruiter/HM source — every role type, including non-engineering and private-repo companies the GitHub strategy cannot reach — but it is now **private to the capturing user and ranks as an unverified lead**. Authenticating a request does not establish the provenance of browser-submitted content: do not restore the `verified` treatment, the top-of-bucket ranking, or the shared-cache write.
- Hiring-manager ranking is startup-aware: when the job carries the reserved `startup` tag, verification tier and founder/C-level status outrank manager-title-seed alignment (at small companies the verified founder is the hiring manager); non-startup searches keep title fit on top.
- Results are ranked as a same-company hierarchy:
  - `direct`
  - `adjacent`
  - `next_best`
- Result quality and company confidence are separate concepts:
  - `match_quality` = role/team closeness
  - `company_match_confidence` = verified vs strong/weak company signal
- People discovery is **pre-warmed and cache-served** so "Find People" feels instant:
  - On job discovery, `jobs/storage._maybe_prewarm_people` marks every newly stored job `people_prewarm_status="pending"` and queues a per-job `auto_prospect.prewarm_job_people` Celery task (highest `match_score` first, capped at `PREWARM_MAX_JOBS_PER_BATCH=300`; the tail stays visible without a warm). Each task runs `search_people_for_job(target_count_per_bucket=1)` — the top recruiter + hiring manager + next-best peer — which **persists** those `Person` CRM rows (so they show on the People page and the snapshot contacts are actionable) and saves the `job_research_snapshot`, then flips the job to `ready`. It **always** flips to `ready` even on failure / zero results, so a job is never permanently hidden. On by default (`people_prewarm_enabled` setting, opt-out in the Auto-Prospect panel); never finds emails / drafts / sends.
  - **Visibility gate:** `get_jobs` hides a job whose `people_prewarm_status == "pending"` *unless* it is older than `PEOPLE_PREWARM_REVEAL_TIMEOUT` (3 min) — so a new job surfaces the moment its people are warmed, or after the timeout if the warm stalls. Existing/old jobs and non-discovery inserts default to `ready` and are never hidden. The `GET /api/jobs` response includes `warming_count` (jobs still pending and within the timeout); while it's > 0 the frontend polls the count-only `GET /api/jobs/warming-count` every 4s (backed by the partial index from migration 056) and refetches the feed only when the count drops, showing a "finding the best people…" banner so warmed jobs appear automatically — the full feed payload is never re-downloaded just to poll.
  - `POST /api/people/search` with a `job_id` is **stale-while-revalidate**: a usable `job_research_snapshot` is returned instantly (`served_from_snapshot: true`); if it's older than 24h (≤14 days) a background `auto_prospect.refresh_job_research_snapshot` task is queued (debounced 2 min); empty / older-than-14-day / missing snapshots run live, and a snapshot-lookup error fails soft to a live search. `force_refresh: true` bypasses the cache.

### LinkedIn graph and warm paths
- LinkedIn graph data is user-scoped and stored separately from saved CRM `Person` rows.
- The new graph subsystem persists:
  - `linkedin_graph_connections`
  - `linkedin_graph_sync_runs`
- Settings now supports two graph inputs:
  - manual LinkedIn connections CSV/ZIP import
  - short-lived sync session for a local browser connector
- The local connector can:
  - attach to an already logged-in Chrome session via CDP
  - open a dedicated persistent browser profile and wait for the user to log into LinkedIn once
  - scrape first-degree LinkedIn connection cards locally with Playwright
  - upload only normalized connection rows back to the API
- The server does not store LinkedIn cookies, OAuth tokens, or credentials.
- People search now returns:
  - `your_connections`
  - per-person `warm_path_type`
  - per-person `warm_path_reason`
  - per-person `warm_path_connection`
- Warm-path boosts are bounded:
  - they only reorder already-safe candidates
  - they do not override ambiguous-company protections
  - they do not bypass `current_company_verified` / `company_match_confidence`
  - they do not change email trust rules
- Dashboard `warm_paths` unifies imported LinkedIn graph paths with outreach-derived paths (`insights_service`). Imported graph data also powers people-search ranking and explanation.

### Search-provider routing
- **Self-hosted SearXNG is NOT viable on a cloud/datacenter IP** and is no longer used in production. Its scraping engines (Google/Bing/DuckDuckGo/Brave-web/Startpage) get CAPTCHA'd or rate-limited from a datacenter IP and return **0 results** (verified on Railway 2026-06-23 — every engine `Suspended: CAPTCHA/too many requests`). Same for any cloud host (Oracle/Fly/Render) and for residential-proxy salvage (more expensive + fragile than paying a SERP API). The authenticated **APIs are primary** — they call vendor endpoints (not scraping), so a datacenter IP is fine. SearXNG stays a supported provider for local dev on a residential IP (opt in via the order env vars).
- **For LinkedIn x-ray, Google-backed sources have by far the best `site:linkedin.com/in` recall**; independent indexes (Brave, Mojeek, Marginalia, …) are weak for LinkedIn, so lead with Google.
- Current router order (env-overridable via `NEXUSREACH_SEARCH_*_PROVIDER_ORDER`):
  - bulk LinkedIn people discovery: `Google CSE -> Serper -> Brave`
  - exact LinkedIn backfill: `Google CSE -> Serper -> Brave`
  - hiring-team search: `Serper -> Brave`
  - public-web people discovery: `Brave -> Serper -> Tavily`
  - employment corroboration: `Tavily -> Brave -> Serper`
- Free-tier economics: Google CSE 100/day free (best LinkedIn recall, but whole-web mode **sunsets 2027-01-01** — a `linkedin.com`-restricted CSE survives and stays free); Serper 2,500 one-time then ~$0.30–1/1k (real Google SERPs); Brave ~free monthly credit (general web). There is **no truly free + unlimited + datacenter-safe Google-quality LinkedIn source** — the strategy is stacked free tiers + routing + caching, graduating to a low-cost SERP API at volume.
- Raw provider results are cached in Redis for 24 hours by normalized query family (kept at 24h, not longer — partly for Google's ToS on caching SERP payloads).
- Provider/debug metadata is stored in `profile_data` or result metadata:
  - `search_provider`
  - `search_query_family`
  - `search_fallback_depth`
  - `search_cache_hit`

### Public-page retrieval and The Org
- Public-page retrieval is free-first:
  - direct `httpx` — SSRF-checked on every redirect hop, byte-capped (`MAX_PAGE_BYTES` 5 MiB) and capacity-leased
  - Jina Reader (keyless, LinkedIn-guarded)
  - Firecrawl only if configured
- Firecrawl is optional fallback infrastructure, not a hard dependency.
- **Crawl4AI was removed in September 2026**, along with its NLTK dependency chain: the client, the `public_page_client` fallback rung, and the requirement are all gone. Do not re-add it.
- Outbound page fetches are **leased** (`url_safety._fetch_capacity`): a Redis-scripted allowance of 2 concurrent fetches per account and 10 across all API workers, keyed on the `paid_context` subject. Missing subject context is a 503, not an unbounded fetch.
- The Org parsing has an HTML fallback: when the legacy `next_data` payload is empty (current TheOrg pages), `parse_org_page` recovers the leadership roster from the JSON-LD `Organization.employee[]` array, and `resolve_reporting_managers` reads the inline `LightPosition` graph (role + `parentPositionId`) to surface a role's direct manager and same-function managers. This is the primary hiring-manager source for non-engineering roles (where public-web x-ray returns only engineers); The Org traversal now always runs for known non-engineering occupations.
- The Org traversal is implemented and bounded:
  - org page resolution from trusted `public_identity_slugs`
  - company/team/person page parsing
  - recruiter, manager, and peer harvesting
  - cache + slug repair in `Company.identity_hints["theorg"]`
- The Org person/team URLs can verify current company, but that trust does not automatically trust an email domain.

### Email behavior
- Email lookup uses a waterfall and stops early on the first strong result.
- Best-guess emails are allowed again, but only from approved domain signals:
  - trusted company domain
  - official careers/site host
  - learned same-company pattern
- Ambiguous-company protections still block unsafe guesses.
- Public identity trust and email-domain trust are intentionally separate.
- Staged drafts and sent mail are reconciled against the provider on a 30-minute beat: drafts sent from the Gmail/Outlook UI flip to `sent`, and thread replies flip `sent` to `responded` (with notification + `outreach_reply_received` analytics event) for up to 45 days after send.
- Reply reconciliation captures `replied_at` and a plain-text `last_reply_snippet` on the outreach log; drafting automatically switches to respond-to-their-reply mode when a contact has replied, and the reply snippet is exposed through the outreach API.
- Gmail and Outlook refresh tokens are encrypted at rest with versioned app keys.
- Legacy plaintext OAuth tokens are cleared by migration and require reconnect.
- **Every claimed send has a durable attempt row** (`send_attempts`, migration `069`, September 2026). `send_staged_message` locks the message `FOR UPDATE`, claims it with a compare-and-set on `(status, schedule_version, scheduled_send_at)`, writes a `sending` attempt with a payload digest, commits, and only then calls the provider; a partial unique index permits one unresolved attempt per message. Failure is split by what is actually known — a definitive rejection (`ValueError`, or a 4xx that is not 408) becomes `send_failed` and is retryable, anything else becomes **`delivery_unknown`** and is never silently re-sent, because a timeout may still have delivered. `expire_unresolved_sends` ages a stuck `sending` attempt to `delivery_unknown` after 10 minutes, and re-sending an already-`sent` message returns the earlier attempt instead of raising.
- **`schedule_version` is the cancellation primitive.** Editing a message, or cancelling its schedule (`draft_staging_service.cancel_message_schedule`, behind `POST /api/email/cancel-send/{message_id}`), bumps it — so a scheduler task still holding the old generation loses its claim rather than sending stale content. A message in `sending` / `delivery_unknown` / `sent` rejects staging, editing and re-scheduling with a 409.

### Message drafting
- Message drafting supports multiple providers through `llm_client.py`.
- Supported `NEXUSREACH_LLM_PROVIDER` values:
  - `anthropic`
  - `openai`
  - `gemini`
  - `groq`
- The drafting flow is draft-first by default, with optional delayed auto-send for staged email drafts when the user explicitly enables it.
- The weekly cadence digest can pre-draft due follow-ups (`cadence_auto_draft_enabled`, opt-in, capped at 3 LLM drafts per digest); drafts are attached to next actions and never sent automatically.
- Warm-path context (type, reason, connection) is threaded into drafting and shown on draft cards.

### Resume quality gate
- Every newly generated or regenerated resume artifact is evaluated after LaTeX rendering by a deterministic, explainable quality gate (`app/services/resume_artifact/quality.py`).
- The gate keeps three independent axes separate:
  - job-fit term coverage
  - occupation-aware evidence quality
  - artifact parseability
- The early-career technical profile adapts HackerRank Hiring Agent's MIT-licensed public category balance (open source 35, projects 30, production 25, technical skills 10). Experienced technical and general professional profiles use different weights; non-technical candidates are never penalized for lacking GitHub/open-source work.
- Scores use only user-scoped parsed resume evidence and final artifact content. Unconfirmed `inferred_claim` additions are stripped before scoring, and school prestige, grades, demographics, and geography do not affect results.
- The source evaluation feeds bounded, supported-evidence guidance into artifact planning. Final results persist on `resume_artifacts.quality_evaluation` / `quality_score` with rubric version, profile, evidence, improvements, attribution, and a screening-simulation disclaimer.
- Cross-job resume reuse now requires both the existing 80% body ATS threshold and a 70% quality threshold before it is offered for automatic reuse. Explicit reuse is re-evaluated against the target job and never inherits a stale source-job score.
- The Job Detail review shows the overall score, independent axes, category evidence, improvements, attribution, excluded inferred-claim count, and the explicit statement that the simulation is not an employer decision or rejection reason.

### Frontend state and UX
- Saved contacts are grouped by company on the People page.
- **Jobs auto-populate — there is no manual "Discover" button.** Opening the Jobs page fires `POST /api/jobs/ensure-fresh`, a debounced, non-blocking nudge: an empty feed gets a full background cold-start discovery (`tasks/jobs.discover_for_user`, default + startup folded in), a warm-but-stale feed (>20 min) gets a light `refresh_single_user_feeds`, a fresh feed does nothing. Debounced in Redis (`search_cache_client.acquire_debounce`, 10 min, fail-closed) so rapid refreshes never re-trigger or hammer the paid APIs. Enrollment is profile-driven: setting target occupations/roles/locations seeds saved searches (`profile._seed_saved_searches`) and fires the first `discover_for_user`, so the existing background beats keep the feed fresh — the LinkedIn model (jobs are ingested into our own index in the background and the page reads it instantly). Startup jobs are folded into the same feed (reachable via the `Startup` filter). The occupation chips on the Jobs page **both filter and drive discovery**: selecting a category fires `POST /api/jobs/discover-occupations` (debounced per occupation-set), which enqueues `tasks/jobs.discover_occupations_for_user` → `discover_jobs(occupations=[...])` so the system actually *fetches* that category (early-career boost included via the `themuse` source) instead of just filtering the SWE-heavy feed to nothing. This is what makes the product work for a non-SWE seeker whose profile only lists "Software Engineer" — pick the Marketing chip and marketing roles get discovered. The frontend time-boxes a jobs-query poll while a chip discovery (or cold-start) runs so freshly-found roles surface on their own. The legacy **saved-search management UI** (the list with on/off toggles, delete, "Refresh Now", and the refresh-health log) has been removed from the Jobs and Dashboard pages: `SearchPreference` is now an *internal, auto-managed ingestion substrate* (seeded from the profile by `_seed_saved_searches`, consumed by the background refresh/board-crawl tasks and the `ensure-fresh` staleness check), never surfaced to the user. Do not re-add a user-facing saved-search surface — occupations are the targeting primitive now.
- Jobs now has:
  - a server-backed `Startup` filter
  - a client-side country filter derived from `location`
  - startup badges and startup-source labels on cards and detail views
- Dashboard latest jobs and top opportunities now show startup badges/source labels when startup tags are present.
- Saved-contact company filters now exist on:
  - People
  - Messages
  - Outreach
- Saved contacts are hidden while a live people search is pending to avoid cross-company confusion.
- People search can show:
  - a `Your Connections at {company}` section above the live buckets
  - warm-path badges and explanations on cold contacts
- Contact cards now show proof for why the person matched, why the company is trusted, why the email is safe, and whether a warm path exists.
- Dashboard now has a guided first-win path from job to contact to draft to staged inbox draft.
- Dashboard outcome metrics now include contacts found, verified emails, warm paths, drafts created, staged drafts, replies, and interviews.
- Settings includes a LinkedIn Graph card with:
  - sync status
  - last sync time
  - `Sync Now`
  - `Upload Export`
  - `Clear Graph Data`
  - generated local connector commands for CDP or dedicated-profile browser sync
- Settings includes Account Data controls for JSON export and permanent account deletion.
- Public `/privacy` and `/terms` routes exist for launch compliance.
- **Pre-launch waitlist + native referral loop.** The landing page is in pre-launch marketing mode: a top banner + every primary CTA ("Join the waitlist" in nav/hero/closer/footer) open `WaitlistModal` (`frontend/src/components/WaitlistModal.tsx`, `.lp-wl-*` / `.lp-ref-*` classes in `landing.css`), collecting name + email (required) + LinkedIn / current title / target role / note (optional) and POSTing to the **public, unauthenticated** `POST /api/waitlist` (rate-limited 10/min/IP, idempotent per lowercased email). **A resubmission for an address already on the list is read-only**: it does not touch the stored name / LinkedIn / title / role / note / goals, and does not attach or replace the stored resume (the Storage path is derived from the row id and uploads are `x-upsert`, so attaching would overwrite the owner's file). Anyone can submit anyone's email here and there is no other proof of ownership, so as of September 2026 a resubmission does **nothing at all** — no field merge, no resume attach, and (unlike the 2026-07-25 behavior) not even a re-issued link, because mailing one on demand is itself a nuisance-mail primitive. Recovering access is a separate, heavily throttled endpoint (`POST /api/referrals/recover`). **Do not re-add a merge of the submitted fields, and do not re-add link delivery to this endpoint.** Trade-off to know: a member cannot add a resume or fix a typo by resubmitting; that needs a token-authenticated edit on the referral dashboard, which does not exist yet. **On success the modal shows one generic "check your inbox" confirmation** — identical for a new signup and an address already on the list, since the endpoint cannot tell the owner from someone guessing their email. The referral panel (`ReferralPanel.tsx`) is now reached only from the dashboard at `/r/:code`, after the emailed credential is exchanged; it shows queue position, a personal share link (Copy + LinkedIn/X/WhatsApp/Email), an email-verify nudge, and the reward ladder — this is a **referral loop built on the waitlist** (product decision 2026-07-23; Robinhood/Harry's pattern, rewards are Solomon's own product value, **referrer-only** for v1). Mechanics extend the RLS-enabled `waitlist_signups` table (migration `061`, no new table): `referral_code` (PUBLIC, shareable, in `?ref=`), `referred_by_id` (self-FK), `email_verified`/`verified_at`, `verified_referral_count` (denormalized — the queue-position sort key), `access_token_hash` / `verification_token_hash` (the original SECRET key hashes — **legacy since September 2026**, see the credential tables below), `signup_ip`. Logic splits into `services/referral_service.py` (code/token mint, fraud, position/tier/status — `referral_status_payload` is the single composer) + `services/waitlist_service.upsert_waitlist_signup` (attribution). Endpoints (**reshaped September 2026**): `POST /api/waitlist` returns `202` and a bare `{ok: true}` — no `already_on_list`, no `access_token`, no `referral`, nothing that distinguishes a new signup from an existing one, because the endpoint is unauthenticated and any of those was an account takeover plus an enumeration oracle. `routers/referrals.py` carries `GET /api/referrals/status` (public `code` in the query + owner token in an **`Authorization: Bearer` header**, never a query parameter), `POST /api/referrals/exchange` (was `GET /verify`: the single-use emailed credential now travels in a **request body**, so it stays out of URLs, logs and `Referer`), `POST /api/referrals/recover` (mails a fresh exchange credential, always answers `202 {ok: true}` whether or not the address exists), and `DELETE /api/referrals/me` (owner bearer + `Idempotency-Key`, returns a deletion receipt). All are **no-account** — waitlist users have none — and `main.py` stamps `Cache-Control: no-store` + `Referrer-Policy: no-referrer` on every `/api/referrals` and `/api/deletions` response. **A referral only counts once the invitee verifies their email** (double-opt-in via Resend — `clients/resend_client.py` + `tasks/referrals.send_verification_email`, fail-soft: logs the verify link when `NEXUSREACH_RESEND_API_KEY`/`RESEND_FROM_EMAIL` are unset). The two tokens are **deliberately separate**: `v` exists only inside the email, so confirming an address proves mailbox control. When one token did both jobs and was returned at signup, anyone could self-verify invented invitees and farm the reward ladder — **never return the verification token over HTTP.** `verify_signup` consumes the exchange credential, flips the invitee, credits the referrer in one transaction, and hands back a fresh `nrw_` dashboard key; a replayed link 404s rather than double-counting. **Credits are now rows, not counters** (migration `071`): a `referral_credits` row keyed `UNIQUE(campaign_id, fingerprint)` — the fingerprint being an HMAC of the invitee's email under a per-campaign key sealed with the app's Fernet keys — makes "one identity, one credit per campaign" a database invariant rather than a code path, so deleting and re-verifying an address cannot farm the ladder. Credentials themselves moved out of the signup row into `referral_credentials` (`kind` `owner` | `exchange`, hashed, **expiring**: 7 days for an owner key, 30 minutes for an exchange credential; issuing a new owner key prunes all but the two most recent). The old query-parameter tokens keep working for 7 days after the campaign row is created (`legacy_until` / `legacy_allowed`) so links already in inboxes do not break — that window is meant to lapse, not to be extended. When that credit lands, `tasks/referrals.send_referral_credited_email` tells the referrer they moved up (position + new count) — the nudge that drives the *next* share. Since September 2026 it is **not** dispatched inline from the request: the credit row carries `notification_status`, and the `deliver-referral-credit-notifications` beat (every 60s) claims and sends the pending ones, so a broker hiccup during confirmation cannot lose the nudge and a replay cannot re-send it. It fires only for the confirmation that actually inserted a credit row, so a replay can't re-notify, it skips an unverified referrer (unsolicited mail only goes to a confirmed address), and it links to the **tokenless** `/r/{code}` via `build_dashboard_home_url` — minting a link token would call `issue_access_token`, which *rotates* the stored hash and would sign the referrer out of a dashboard they may have open. Both email templates escape every interpolated value (`html.escape`) — `name` is untrusted public input and these send from our own verified domain. Anti-fraud: disposable-domain blocklist (`app/data/disposable_email_domains.txt` → 422), self-referral guard (`fraud_key` Gmail dot/plus normalization), per-IP daily cap (`referral_signup_ip_daily_limit`, reuses `discovery_rate_limit._enforce_daily_limit`), plus the verified-gating above. **Position is referral-count-ranked** (`verified_referral_count DESC, created_at ASC`) — NOT a literal "+100" (that's display copy on rung 1). Returning users hit the account-less dashboard at **`/r/:code`** (`ReferralDashboardPage.tsx`, wrapped in `.lp` so the `.lp`-scoped classes apply). Emailed links now put the secret in the **URL fragment** (`/r/{code}#t=…`, `/r/{code}#v=…` — `build_dashboard_url` / `build_verify_url`), which browsers never send to the server or to a `Referer`; the page reads the fragment, `replaceState`s it away immediately, and falls back to the legacy `?t=`/`?v=` query parameters only for links already in flight. The owner key is held in **`sessionStorage`** (was `localStorage`), so it dies with the tab rather than persisting on a shared machine. `SENSITIVE_QUERY_KEYS` in `lib/observability.ts` still scrubs `t`/`v` from telemetry, and Vercel serves `/r/*` with `Cache-Control: no-store` + `Referrer-Policy: no-referrer`. Frontend: `hooks/useReferral.ts` (raw fetch — public, deliberately bypasses the auth'd `api` client and its sign-out-on-401), `types/referral.ts`, `?ref=` captured in `LandingPage` into `localStorage.nr_ref`, the owner's `{code, token}` stashed as `sessionStorage.nr_wl` (`storeReferralOwner` / `readReferralOwnerToken`). **Referrals REQUIRE the backend sink.** The Google Apps Script / Google Sheet path (`VITE_WAITLIST_ENDPOINT`, `frontend/waitlist-google-apps-script.gs`) has an unreadable `no-cors` response so it cannot hydrate the panel — it is now only an **offline fallback** when the backend is unreachable (signup still captured, no referral features). To keep the Sheet populated in normal operation, the backend **mirrors each signup server-side** to the same Apps Script `/exec` URL (`clients/sheets_mirror_client.py`, `NEXUSREACH_WAITLIST_SHEET_MIRROR_URL`; best-effort FastAPI `BackgroundTasks`, never blocks the signup). Product-credit rewards (rungs 5/10) are **honored manually at launch** via the admin export `GET /api/waitlist` (`X-Admin-Token` = `NEXUSREACH_WAITLIST_ADMIN_TOKEN`, 404 when unset) — now includes `referral_code` / `referred_by_id` / `email_verified` / `verified_referral_count` / `earned_tier`. Config: `NEXUSREACH_RESEND_API_KEY` / `RESEND_FROM_EMAIL` / `REFERRAL_PUBLIC_BASE_URL` (link/email base, falls back to `frontend_url`) / `REFERRAL_LAUNCH_TARGET` / `REFERRAL_TIER_THRESHOLDS` / `REFERRAL_SIGNUP_IP_DAILY_LIMIT`. **Target role is a taxonomy key, not free text (2026-07-27):** the signup form asks "What kind of role are you targeting?" as a **required** `<select>` of the 23 occupations from the public `GET /api/occupations`, storing the validated key in `target_occupation` (migration `065`; `clean_target_occupation` drops anything not in the taxonomy, exactly as `clean_goals` does). This is the field that can seed saved searches at launch (`profile._seed_saved_searches` takes occupation keys) and group the list into invite cohorts — "SWE"/"Software Engineer"/"swe" are three unusable strings for one segment. It is fetched with `usePublicOccupations` (raw fetch: the `api` client resolves a Supabase token and **signs out** when there isn't one, which is wrong for an anonymous visitor) **lazily on modal open**, so the landing page still makes no network call until someone shows intent. If the taxonomy can't be fetched the field **falls back to the old free-text input** writing `target_role` — a backend blip must never leave a required empty dropdown blocking signups. `current_title` stays optional free text: new grads and career changers are a first-class audience and often have no current role. NB: the DB column is `current_title`, **not** `current_role` (reserved SQL keyword); the LinkedIn input is `type="text"` (not `url`) so scheme-less `linkedin.com/in/...` paste isn't rejected. To flip back to open signup, restore the `/signup` links on the CTAs. **Goals + optional resume (2026-07-24):** the form also collects multi-select **goal chips** (`app/utils/waitlist_goals.py` — keys validated server-side by `clean_goals`, unknown keys dropped; the free-text detail reuses the existing `note` column, and `GOAL_OPTIONS` in `WaitlistModal.tsx` must stay in sync) plus an **optional resume upload**. The resume rides as base64 in the JSON body (mirroring `/api/profile/resume-json`, adopted because multipart was flaky in browsers), is validated by `app/utils/resume_upload.py` (type allowlist + **magic-byte sniff**, promoted out of `routers/profile.py`), stored in a **private Supabase Storage bucket** via `clients/supabase_storage_client.py` (raw httpx + service-role key — the `supabase` SDK is still never imported), and parsed **asynchronously in the Celery worker** (`tasks/waitlist_resume.py`) because the sandboxed parser can use 512 MiB and must never run inline on the public endpoint. Columns land on `waitlist_signups` (migration `062`), with `resume_text`/`resume_parsed` **deferred** so hot reads skip them. Split posture: **invalid input** (bad base64/type/magic bytes/oversize) returns 400/413/422 so the visitor can fix it, while a **Storage outage is fail-soft** — the signup still returns 202 with `resume_parse_status='failed'`. `/api/waitlist` gets its own larger body limit in `middleware/request_size.py`. Requires a manually-created private `waitlist-resumes` bucket.
- - **The waitlist funnel is instrumented end to end** (`trackFunnelEvent` from `lib/observability`): `waitlist_landing_viewed` (+`referred`) → `waitlist_modal_opened` (+`source`) → `waitlist_submitted` → `waitlist_joined` (+`sink` backend|sheet_fallback, `already_on_list`, `saw_referral_panel`) or `waitlist_submit_failed` (+`reason` category) → `waitlist_verified` → `waitlist_dashboard_viewed` → `waitlist_link_copied` / `waitlist_shared` (+`channel`). **`waitlist_verified` is the one to watch**: double-opt-in gates every referral count, so silent loss there looks exactly like nobody sharing. **Payloads are shape-only by rule** — counts, booleans, the fixed goal-key vocabulary, and error *categories*; never the email, name, note, LinkedIn URL, resume filename, referral code, or any token (the server's error `detail` can quote user input, so it is deliberately not forwarded). `components/__tests__/WaitlistAnalytics.test.tsx` asserts this, because such a leak would ship silently — a new property on an existing event breaks nothing.
- **Analytics consent is geo-conditional, and gates `posthog.init` itself** (`lib/consent.ts` + `components/ConsentBanner.tsx`). PostHog writes a device identifier and calls a US host the instant it initialises, so suppressing *events* after that point would not be consent — `startProductAnalytics()` is therefore deferred and only runs when `analyticsAllowed()`. Region comes from the browser's IANA timezone (`Europe/*` + the Atlantic EU/EEA outliers, minus `Europe/Moscow|Istanbul|Minsk` etc.): no geo-IP service, no network call, and nothing recorded about a visitor in order to decide whether we may record anything. It **fails closed** — an unreadable timezone counts as consent-required. Solomon targets the US and Canada, so those visitors never see a banner and analytics is unchanged for them; only EU/UK/EEA visitors are asked. A decline is a stored answer, not a dismissal, so it does not re-prompt. Every send path gates on `productAnalyticsStarted`, **not** `isProductAnalyticsEnabled` (config-on) — don't revert those checks. Sentry is deliberately *not* gated: it is error monitoring for service reliability, runs with `sendDefaultPii: false` and masked replay.
Frontend Sentry and PostHog initialize only when configured. PostHog autocapture
  and session recording are disabled by default.

### Security posture (September 2026 audit remediation)

This subsection landed on `main` in September 2026 via `security/remediation-2026-09` (commit `3b59e4ac`, PR #40).

- **The renderer is a credential-free blast-radius boundary.** LaTeX/PDF work runs in its own Celery app
  (`app/renderer_app.py` + `app/renderer_runtime.py`) on its own Redis broker, from an image that contains only those two
  modules and `celery[redis]` + `pypdf` — no database URL, no provider keys, no application package. The old in-process
  `app/tasks/render.py` and its `render` queue routes are gone. The renderer app refuses to boot without
  `NEXUSREACH_RENDERER_REDIS_URL`, and in production `_validate_production_isolation` checks its own containment at
  startup: non-root, no application secret in the environment, a read-only root mount, cgroup memory/PID ceilings,
  and an explicit `NEXUSREACH_RENDERER_EGRESS_ENFORCED=true` attestation that its egress is broker-only. Config
  validation on `service_role=renderer` separately rejects any provider/auth credential being handed to it. Production API config validation requires `render_remote_enabled`, `renderer_isolation_enforced`, and a
  renderer broker **different** from the general one — `renderer_isolation_enforced` is an attestation you flip only
  after verifying the live controls, not a default.
- **Every externally billed call takes an atomic reservation first** (`services/paid_work.py`, migration `073`).
  `reserve()` locks the global then the account day-bucket (that lock order is the only one used), checks calls, tokens
  and concurrency against `global_*` and per-account ceilings, and **commits the reservation before any provider I/O**;
  the call then moves `dispatched -> settled` with real usage, or `delivery_unknown` on an exception. A stable
  `operation_id` (from `services/paid_context.operation_id`, scoped to the Celery task id) makes a redelivered task reuse
  its reservation instead of paying twice, and the `recover-paid-work-reservations` beat releases what a crashed worker
  abandoned. The subject comes from a `contextvar` set by `get_current_user_id` for requests and by each background task;
  outside tests, LLM generation with no subject is a 503 rather than an unattributed spend.
- **Deletion is durable, idempotent, and provable without an account** (`services/deletion_service.py`, migration `070`).
  `POST /api/account/delete` and `DELETE /api/referrals/me` return `202` with a receipt instead of doing best-effort work
  inline: they write an `auth_tombstone` for the subject, a `deletion_request` (deduped by `Idempotency-Key`) and per-target
  `deletion_actions`, then delete the application data in the same transaction. External erasure (Supabase identity,
  Storage objects) is retried by the `retry-deletions` beat, so a failed step keeps its pointer rather than orphaning a
  file. `GET /api/deletions/{id}` reports progress to the bearer of the receipt — the only way a deleted user can check,
  since they no longer have a session. The tombstone is the revocation barrier: `dependencies.get_or_create_user` refuses
  a tombstoned subject, so a JWT signed before deletion cannot re-bootstrap the row, and tombstones outlive the longest
  possible access token (`supabase_access_token_max_lifetime_seconds` + a day, minimum 30 days).
- **Supabase JWTs are validated on all identity-bearing claims**, not just the signature: `exp`, `sub`, `aud` and `iss`
  are required and the issuer must match `{supabase_url}/auth/v1` (both ES256 and HS256 paths). First-time bootstrap of an
  unknown subject additionally verifies the user upstream via the admin API before creating the row.
- **SSRF protection now covers volume as well as destination.** `utils/url_safety` keeps the per-hop private/loopback/
  link-local/metadata rejection and adds a 5 MiB response cap plus Redis-leased fetch capacity (2 per account, 10 global).
- **Rate limiting is atomic.** `discovery_rate_limit._enforce_daily_limit` is a single Redis Lua script (check-and-add in
  one round trip; the old pipeline pair let concurrent callers both pass) and now fails **closed** everywhere except
  `test`/`e2e` — previously only `production` failed closed.
- **Supply chain.** `requirements.lock` regenerated; the renderer has its own `requirements.renderer.lock`, audited and
  SBOM'd separately in `security.yml`, which now also runs daily on a schedule and on `workflow_dispatch`. Both workflows
  declare `permissions: contents: read` and cancel superseded runs. Frontend pins `posthog-js` forward and overrides
  `fflate`. The Vercel CSP `connect-src` is an explicit host allowlist instead of `https:` + `wss:`.

## Tech stack

### Frontend
- React 19 + TypeScript
- Vite
- React Router 8 — imported from `react-router`; the separate `react-router-dom`
  package has no v8 and was dropped (upgraded 2026-07-25 for GHSA-qwww-vcr4-c8h2,
  whose fix landed only in 8.3.0 — there is no 7.x backport). Requires React >= 19.2.7.
- TanStack Query
- Zustand
- Tailwind CSS
- shadcn/ui built on `@base-ui/react`

### Backend
- Python 3.12+
- FastAPI
- SQLAlchemy + Alembic
- PostgreSQL
- Redis
- Celery
- Pydantic v2

### External services in the live architecture
- Supabase: auth + hosted Postgres
- Apollo: company/org enrichment, optional person enrichment
- SearXNG: primary free search provider (self-hosted, unlimited)
- Serper: fallback bulk SERP provider (paid)
- Brave Search: fallback search (paid)
- Tavily: employment corroboration + fallback public discovery
- Google CSE: optional legacy fallback (100 free/day)
- Hunter: email finder + verifier
- GitHub API: engineer/public profile context
- Job Bank Canada (`jobbank.gc.ca`): Canada's national job board — public-page scrape, no key, fail-soft (no JSON API exists)
- The Muse (`themuse.com/api/public/jobs`): cross-industry job board — free, no key required, all occupation categories, fail-soft. The keyless breadth source for every non-tech category.
- Firecrawl: optional public-page retrieval fallback (Crawl4AI removed September 2026)
- Gmail API / Microsoft Graph: draft staging

### Production deployment target
- Vercel serves the frontend from the `frontend` project root.
- Railway runs four backend services from `backend`:
  - FastAPI web service using `backend/railway.web.toml`
  - Celery worker using `backend/railway.worker.toml`
  - Celery beat using `backend/railway.beat.toml`
  - Renderer worker using `backend/railway.renderer.toml`
- Supabase provides hosted Postgres and auth.
- Railway Redis is shared by Celery, search cache, and rate-limit storage. **The renderer has its own Redis instance and credentials** (`NEXUSREACH_RENDERER_REDIS_URL`); production config validation rejects a renderer broker equal to the general one.
- SearXNG runs on Railway or another private reachable host.
- `backend/Dockerfile` is the API/worker/beat runtime and **no longer contains a TeX toolchain**. `pdflatex` lives only in `backend/Dockerfile.renderer`, which installs TeX Live, ships just `app/renderer_app.py` + `app/renderer_runtime.py` (not the application package), and installs the two-line `requirements.renderer.lock` — no database driver, no HTTP client, no application credentials. The web service runs migrations through Railway's `preDeployCommand` rather than inside its start command.
- `DEPLOYMENT_RUNBOOK.md` is the source of truth for deploy order, secrets, smoke checks, alerts, and rollback.

### Local helper tooling
- Playwright is used by the LinkedIn graph browser connector (`backend/scripts/linkedin_graph_connector.py`).

## Project structure

```text
NexusReach/
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── lib/
│   │   ├── pages/
│   │   ├── stores/
│   │   └── types/
├── backend/
│   ├── app/
│   │   ├── clients/
│   │   │   └── ats/
│   │   ├── models/
│   │   ├── routers/
│   │   ├── schemas/
│   │   ├── services/
│   │   │   ├── linkedin_graph/
│   │   │   ├── people/
│   │   │   └── resume_artifact/
│   │   ├── tasks/
│   │   └── utils/
│   ├── alembic/
│   ├── scripts/
│   └── tests/
├── PRD.md
├── architecture.md
├── PLAN.md
├── HANDOFF.md
├── lessons.md
├── README.md
├── AGENTS.md
└── CLAUDE.md
```

## Coding conventions

### Python
- Use `async` service and router code where appropriate.
- Keep routers thin and services responsible for business logic.
- Put external integrations in `backend/app/clients`.
- Use typed signatures everywhere.
- Avoid bare `except`.
- Keep environment reads in `backend/app/config.py`.

### TypeScript
- Functional components only.
- TanStack Query for server-state access.
- Zustand for client-only state.
- No `any`.
- Shared types belong in `frontend/src/types`.

### Data boundaries
- All user data must remain scoped by `user_id`.
- Never treat cross-company public results as safe fallback contacts.
- Company verification, role ranking, and email trust are separate axes.
- Imported LinkedIn graph rows must remain separate from saved CRM contacts.
- **Every `public` table must have RLS enabled.** Supabase auto-exposes the `public` schema through PostgREST to the `anon`/`authenticated` roles (the public anon key ships in the frontend), so an RLS-disabled table is readable/writable directly via the Supabase REST API, bypassing the FastAPI `user_id` scoping. Migration `055_enable_row_level_security` enables RLS (deny-all, no policies) on all tables; the backend is unaffected because it connects as the `postgres` owner, which bypasses RLS (we `ENABLE`, never `FORCE`). **Any new table added in a later migration must `ALTER TABLE … ENABLE ROW LEVEL SECURITY` in the same migration** — new tables are not covered automatically.
- **Internal security tables additionally revoke the browser roles' grants.** RLS with no policies already denies reads, but migration `074_internal_table_grants` also `REVOKE`s every privilege from `anon`/`authenticated` on `send_attempts`, `auth_tombstones`, `deletion_requests`, `deletion_actions`, `referral_campaigns`, `referral_credentials`, `referral_credits`, `paid_budget_buckets` and `paid_reservations` — defense in depth against a future policy being added by mistake. `scripts/verify_rls.py` now asserts both properties and exits non-zero on either failure; add a new server-only table to its `_SERVER_ONLY_TABLES` list and to the migration together.

## Key commands

```bash
# Frontend
cd frontend && npm install
cd frontend && npm run dev
cd frontend && npx eslint .
cd frontend && npx tsc -b
cd frontend && npm run test
cd frontend && npm run build

# Backend
cd backend && pip install -r requirements.txt
cd backend && uvicorn app.main:app --reload
cd backend && alembic upgrade head
cd backend && ruff check app tests conftest.py
cd backend && pytest
cd backend && celery -A app.tasks worker --loglevel=info
cd backend && celery -A app.tasks beat --loglevel=info

# Isolated renderer worker (its own Celery app, its own broker)
cd backend && celery -A app.renderer_app:renderer_app worker --loglevel=info --concurrency=1 -Q render

# RLS + internal-table grant check (needs a live DB connection)
cd backend && python scripts/verify_rls.py

# Real browser E2E
cd e2e && npm install
cd e2e && npx playwright install chromium
cd e2e && npm run test:real

# LinkedIn graph local connector
cd backend && python scripts/linkedin_graph_connector.py --help

# Curated Workday board health check (drift detection + repaired configs)
cd backend && python scripts/verify_workday_boards.py
```

## Local dev auth bypass (preview authed pages without a Supabase login)

So Claude Code / Codex (and humans) can see authenticated pages directly in a
preview, both sides ship a **dev auth bypass** (no Supabase, no real login). The
code already exists (`auth_mode=dev` + bypass guards); this is how to run it.

- **Frontend:** `cd frontend && npm run dev:bypass` (= `vite --mode devauth`).
  Loads the committed, non-secret `frontend/.env.devauth`
  (`VITE_AUTH_MODE=dev` + `VITE_DEV_AUTH_BYPASS_ENABLED=true`), which overrides
  `.env` in `devauth` mode **only** — plain `npm run dev` is untouched. The store
  builds a dev session and skips the login screen; the bootstrap is best-effort,
  so the authed shell still renders if the backend is down (data pages just show
  empty/loading states).
- **Backend:** run it with `NEXUSREACH_AUTH_MODE=dev` +
  `NEXUSREACH_DEV_AUTH_BYPASS_ENABLED=true` (every request resolves to
  `dev_user_id` `00000000-…-0001`, created lazily on first `/api/auth/me`).
  The Supabase **pooler resets direct asyncpg from a local box** (truth #3 family),
  so point the dev backend at a **local Postgres** (e.g.
  `NEXUSREACH_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/nexusreach`)
  and `alembic upgrade head` — never the prod pooler. Do **not** flip the
  committed prod `.env`'s `DATABASE_URL`; override per-run.
- **Preview launch configs** (`.claude/launch.json`): `frontend-bypass` (vite
  devauth) + `backend-dev` (uvicorn with the dev env inlined, local DB). Start
  both, then the authed app renders at `localhost:5173`.
- **Caveat:** the dev user is empty unless seeded; taxonomy-driven UI (e.g. the
  occupation chips, `/api/occupations`) renders regardless. `GET /api/jobs` with
  **no `limit`** serializes the whole feed and can 500 on a large local dataset —
  the real frontend always paginates, so this only bites raw unbounded calls.

## Environment variables

### Backend
```env
NEXUSREACH_DATABASE_URL=postgresql+asyncpg://...
NEXUSREACH_REDIS_URL=redis://...
# Renderer isolation (September 2026). The renderer must have its own broker
# and credentials; production API config validation rejects a renderer URL
# equal to REDIS_URL, and refuses to boot unless both flags below are true.
# RENDERER_ISOLATION_ENFORCED is an attestation that the live container's
# egress, filesystem, scratch, CPU, memory and PID limits were verified.
NEXUSREACH_RENDERER_REDIS_URL=
NEXUSREACH_RENDER_REMOTE_ENABLED=false
NEXUSREACH_RENDERER_ISOLATION_ENFORCED=false
NEXUSREACH_RENDER_TASK_TIMEOUT_SECONDS=30
# Set on the RENDERER service only: attests its egress is broker-only.
# The renderer refuses to start in production without it.
NEXUSREACH_RENDERER_EGRESS_ENFORCED=false
NEXUSREACH_SERVICE_ROLE=api
# Tombstones must outlive any JWT signed before deletion.
NEXUSREACH_SUPABASE_ACCESS_TOKEN_MAX_LIFETIME_SECONDS=3600
# API-only secret deriving deletion status receipts (>= 32 chars in prod,
# rejected on worker/renderer roles). Generate: openssl rand -hex 32
NEXUSREACH_DELETION_RECEIPT_HMAC_KEY=
# Paid-work reservation ceilings (UTC-day buckets), checked atomically
# before any billed provider call. Account limits reuse the existing
# DAILY_* names; the GLOBAL_* pair caps the whole deployment.
NEXUSREACH_GLOBAL_DAILY_API_CALL_LIMIT=500
NEXUSREACH_GLOBAL_DAILY_LLM_TOKEN_LIMIT=1000000
NEXUSREACH_ACCOUNT_PAID_CONCURRENCY=2
NEXUSREACH_GLOBAL_PAID_CONCURRENCY=6
NEXUSREACH_PAID_RESERVATION_TTL_SECONDS=300
# Referral campaign identity (credit uniqueness scope) + recovery throttle.
NEXUSREACH_REFERRAL_CAMPAIGN_ID=prelaunch-2026
NEXUSREACH_REFERRAL_RECOVERY_HOURLY_LIMIT=100
NEXUSREACH_SUPABASE_URL=https://...
NEXUSREACH_SUPABASE_KEY=...
NEXUSREACH_SUPABASE_SERVICE_ROLE_KEY=...
NEXUSREACH_SUPABASE_JWT_SECRET=...
NEXUSREACH_AUTH_MODE=supabase
NEXUSREACH_DEV_AUTH_BYPASS_ENABLED=false
NEXUSREACH_DEV_USER_ID=00000000-0000-0000-0000-000000000001
NEXUSREACH_DEV_USER_EMAIL=dev@nexusreach.local
# Proxies we control in front of the API. Every per-IP control resolves the
# caller via `utils/client_ip` (Nth-from-right X-Forwarded-For entry). 0 = direct
# (local dev); 1 = one edge proxy (Railway). Production API refuses to boot at 0
# because the socket peer would be the proxy and all callers would share one
# rate-limit bucket. Never combine with uvicorn --forwarded-allow-ips='*'.
NEXUSREACH_TRUSTED_PROXY_HOPS=0
# Shared secret for the waitlist admin export (GET /api/waitlist, X-Admin-Token
# header). Unset => export endpoint returns 404. Public POST /api/waitlist is
# unauthenticated regardless.
NEXUSREACH_WAITLIST_ADMIN_TOKEN=
# Data retention. Waitlist members have no account, so /api/account/delete
# cannot reach them: the daily `purge-waitlist-pii` beat expires these fields
# and DELETE /api/referrals/me lets a member erase everything themselves.
NEXUSREACH_WAITLIST_SIGNUP_IP_RETENTION_DAYS=30
NEXUSREACH_WAITLIST_RESUME_RETENTION_DAYS=180
# Global known-people cache: rows describe third parties who never used the
# product, so anything not re-discovered/re-verified in this window is deleted
# by `maintain-known-people-cache` (re-created on next discovery if relevant).
NEXUSREACH_KNOWN_PEOPLE_PURGE_DAYS=180
# Referral waitlist. Resend sends the double-opt-in verification email (the only
# transactional-email path — all other email is user-OAuth mailbox sending).
# Both unset => the verify link is logged, not sent (fail-soft). PUBLIC_BASE_URL
# is the origin used to build referral/verify links (falls back to frontend_url).
NEXUSREACH_RESEND_API_KEY=
NEXUSREACH_RESEND_FROM_EMAIL=
NEXUSREACH_REFERRAL_PUBLIC_BASE_URL=
NEXUSREACH_REFERRAL_LAUNCH_TARGET=3000
NEXUSREACH_REFERRAL_TIER_THRESHOLDS=1,3,5,10
NEXUSREACH_REFERRAL_SIGNUP_IP_DAILY_LIMIT=50
# Optional: mirror each signup to a Google Apps Script /exec URL so the
# pre-launch Google Sheet stays populated (the backend is the primary sink now).
# Unset => no mirror. Best-effort background task, never blocks a signup.
NEXUSREACH_WAITLIST_SHEET_MIRROR_URL=
# Optional waitlist resume upload. Files go to a PRIVATE Supabase Storage bucket
# (create it manually) and are parsed by the Celery worker, never inline. Missing
# bucket/service-role key => signup still succeeds, resume marked `failed`.
NEXUSREACH_SUPABASE_STORAGE_BUCKET=waitlist-resumes
NEXUSREACH_MAX_WAITLIST_RESUME_BYTES=5242880
NEXUSREACH_MAX_WAITLIST_REQUEST_BYTES=7340032
NEXUSREACH_APP_RELEASE=...
NEXUSREACH_SENTRY_DSN=...
NEXUSREACH_SENTRY_TRACES_SAMPLE_RATE=0.05
NEXUSREACH_SENTRY_PROFILES_SAMPLE_RATE=0.0
NEXUSREACH_TOKEN_ENCRYPTION_PRIMARY_VERSION=v1
NEXUSREACH_TOKEN_ENCRYPTION_KEYS={"v1":"..."}

NEXUSREACH_APOLLO_API_KEY=...
NEXUSREACH_APOLLO_MASTER_API_KEY=...
NEXUSREACH_HUNTER_API_KEY=...
NEXUSREACH_HUNTER_PATTERN_MONTHLY_BUDGET=25
NEXUSREACH_GITHUB_TOKEN=...
NEXUSREACH_JSEARCH_API_KEY=...
NEXUSREACH_ADZUNA_APP_ID=...
NEXUSREACH_ADZUNA_API_KEY=...
# USAJobs federal government board (optional, fail-soft). Free key from
# developer.usajobs.gov; the user-agent must be the email registered with it.
NEXUSREACH_USAJOBS_API_KEY=...
NEXUSREACH_USAJOBS_USER_AGENT=...

NEXUSREACH_ANTHROPIC_API_KEY=...
NEXUSREACH_OPENAI_API_KEY=...
NEXUSREACH_GOOGLE_API_KEY=...
NEXUSREACH_GOOGLE_CSE_ID=...
# Optional: a Google CSE restricted to linkedin.com, used only for LinkedIn
# x-ray. Survives the 2027 whole-web CSE sunset; falls back to GOOGLE_CSE_ID.
NEXUSREACH_GOOGLE_LINKEDIN_CSE_ID=
NEXUSREACH_GROQ_API_KEY=...
NEXUSREACH_LLM_PROVIDER=anthropic

NEXUSREACH_SEARXNG_BASE_URL=http://localhost:8888
NEXUSREACH_BRAVE_API_KEY=...
NEXUSREACH_SERPER_API_KEY=...
NEXUSREACH_TAVILY_API_KEY=...
# Optional datacenter-safe fallbacks (off until set, then add to the order vars):
# You.com = SERP API (LinkedIn x-ray), Exa = neural `people` search.
NEXUSREACH_YOUCOM_API_KEY=
NEXUSREACH_EXA_API_KEY=
NEXUSREACH_SEARCH_CACHE_TTL_SECONDS=86400
NEXUSREACH_SEARCH_LINKEDIN_PROVIDER_ORDER=google_cse,serper,brave
NEXUSREACH_SEARCH_EXACT_LINKEDIN_PROVIDER_ORDER=google_cse,serper,brave
NEXUSREACH_SEARCH_HIRING_TEAM_PROVIDER_ORDER=serper,brave
NEXUSREACH_SEARCH_PUBLIC_PROVIDER_ORDER=brave,serper,tavily
NEXUSREACH_SEARCH_EMPLOYMENT_PROVIDER_ORDER=tavily,brave,serper

NEXUSREACH_FIRECRAWL_BASE_URL=
NEXUSREACH_FIRECRAWL_API_KEY=
NEXUSREACH_THEORG_TRAVERSAL_ENABLED=true
NEXUSREACH_THEORG_CACHE_TTL_HOURS=24
NEXUSREACH_THEORG_MAX_TEAM_PAGES=3
NEXUSREACH_THEORG_MAX_MANAGER_PAGES=3
NEXUSREACH_THEORG_MAX_HARVESTED_PEOPLE=25
NEXUSREACH_THEORG_TIMEOUT_SECONDS=20

NEXUSREACH_GOOGLE_CLIENT_ID=...
NEXUSREACH_GOOGLE_CLIENT_SECRET=...
NEXUSREACH_MICROSOFT_CLIENT_ID=...
NEXUSREACH_MICROSOFT_CLIENT_SECRET=...

NEXUSREACH_EMPLOYMENT_VERIFY_TOP_N=10
NEXUSREACH_EMPLOYMENT_VERIFY_TIMEOUT_SECONDS=20
NEXUSREACH_EMPLOYMENT_VERIFY_ENABLED=true

NEXUSREACH_LINKEDIN_GRAPH_SYNC_SESSION_TTL_SECONDS=900
NEXUSREACH_LINKEDIN_GRAPH_MAX_IMPORT_BATCH_SIZE=250
```

### Frontend
```env
VITE_API_URL=http://localhost:8000
VITE_AUTH_MODE=supabase
VITE_DEV_AUTH_BYPASS_ENABLED=false
VITE_SUPABASE_URL=https://...
VITE_SUPABASE_ANON_KEY=...
VITE_APP_ENVIRONMENT=development
VITE_APP_RELEASE=...
VITE_SENTRY_DSN=...
VITE_SENTRY_TRACES_SAMPLE_RATE=0.05
VITE_SENTRY_REPLAYS_SESSION_SAMPLE_RATE=0
VITE_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE=1
VITE_POSTHOG_KEY=...
VITE_POSTHOG_HOST=https://us.i.posthog.com
VITE_ANALYTICS_ENABLED=true
# Pre-launch waitlist sink. Set to a Google Apps Script /exec URL to send
# signups straight to a Google Sheet (no backend/Supabase/Railway needed —
# see frontend/waitlist-google-apps-script.gs). Unset => the modal falls back
# to the app's own POST /api/waitlist.
VITE_WAITLIST_ENDPOINT=
```

## Critical implementation truths

1. `backend/.env` is loaded relative to the current working directory. Running scripts from the repo root can miss backend config. **That cuts both ways, and it is how you reproduce CI locally**: CI has no `.env`, so a test that reads an ambient setting instead of pinning it passes from `backend/` and fails on a runner (`test_valid_supabase_jwt_is_accepted` built its `iss` claim from `settings.supabase_url` and did exactly this). Run `python -m pytest backend/tests` **from the repo root** to get CI's configuration — every setting at its default — and pin what a test depends on with `monkeypatch.setattr(settings, ...)`.
2. Apollo free-tier company endpoints are useful; person search is still not something to depend on blindly.
3. SearXNG is no longer a production search provider — self-hosted SearXNG on a cloud/datacenter IP returns 0 results (engines block the IP; verified 2026-06-23). Authenticated APIs are primary; SearXNG is local-dev-only (residential IP). See the Search-provider routing section.
4. For LinkedIn x-ray the order is Google CSE → Serper → Brave (Google-backed sources have the best `site:linkedin.com/in` recall; Brave's independent index is weak for LinkedIn). Brave leads only the general-web chains.
5. Tavily is primarily for employment corroboration and fallback public-web discovery, not main LinkedIn x-ray.
6. Firecrawl is optional and should be treated as a last-resort page-fetch provider.
7. The Org slug resolution must validate real org pages. Do not assume the first slug candidate is correct.
8. `current_company_verified` is separate from `match_quality`. A person can be a `next_best` contact and still be a verified current employee.
9. Best-guess emails are acceptable only with safe domain evidence. Ambiguous brands like Zip should still withhold unsafe guesses.
10. Workday exact-job support is honest about upstream outages. Maintenance pages should fail cleanly, not import the wrong landing page.
11. `firecrawl_public_web` is fully legacy: no code path writes it anymore. Firecrawl is now only an optional page-fetch fallback and never labels its own results. The value survives only in the frontend `Person.current_company_verification_source` union for backwards-compatible reads of old rows.
12. shadcn/ui in this repo uses `@base-ui/react`, not Radix. No `asChild`, no Radix-specific dialog props.
13. Run `ruff check app tests conftest.py`, not just `ruff check app`.
14. Testing Library queries on this codebase often need role-based selectors because duplicated text is common.
15. SQLAlchemy forward references like `Mapped["Person"]` still need `# noqa: F821` in model files.
16. The global error handler returns `{"error": {"code", "message"}}`, not FastAPI's default `{"detail": ...}`.
17. Vitest utilities should still be imported explicitly for portability.
18. Always inspect `frontend/src/components/ui/*.tsx` before assuming shadcn prop support from external examples.
19. Imported LinkedIn graph data must remain separate from `Person` CRM rows and from dashboard outreach-derived `warm_paths`.
20. `Sync Now` on Settings is not LinkedIn OAuth. It creates a short-lived sync session for the local browser connector.
21. The server must never store LinkedIn cookies, session tokens, or credentials. Only normalized connection rows are uploaded.
22. Warm-path ranking boosts cannot bless unsafe candidates. They operate only within already-safe same-company results.
23. The local browser connector requires Playwright locally and can either attach to Chrome over CDP or use a dedicated persistent browser profile.
24. `newgrad_jobs` now behaves like a first-class non-ATS source: enrich detail pages inline, derive `remote` from the detail-page work-mode signal, and dedupe by `source + external_id` / canonical URL instead of ATS-only assumptions.
25. Startup state is tag-based, not schema-based. Reserved tags are `startup` and `startup_source:<source_key>`.
26. `POST /api/jobs/discover` supports `mode: "default" | "startup"`. Startup-mode saved searches participate in the hourly feed refresh via `run_startup_refresh_for_query`.
27. Startup ecosystem imports must preserve the underlying `source` / `ats` from the resolved posting while merging startup provenance into `job.tags` on dedupe.
28. Wellfound is intentionally best-effort right now. Live fetches can return `403` anti-bot pages and should fail soft to `[]` rather than breaking startup discover.
29. `auth_mode=dev` is fail-closed unless `NEXUSREACH_DEV_AUTH_BYPASS_ENABLED=true`; the frontend has the same explicit `VITE_DEV_AUTH_BYPASS_ENABLED=true` guard.
30. Real E2E uses `VITE_AUTH_MODE=e2e` with a Supabase-compatible JWT, boots backend/frontend on isolated ports, drops and recreates `nexusreach_e2e`, and runs Alembic from zero before the browser test.
31. `people_service.py`, `ats_client.py`, `resume_artifact_service.py`, `linkedin_graph_service.py`, and `job_service.py` are compatibility shims. The implementations live in `app/services/people/`, `app/clients/ats/`, `app/services/resume_artifact/`, `app/services/linkedin_graph/`, and `app/services/jobs/` as layered packages (each module imports only from layers below it). New code should import from the packages, not the shims. The `jobs` package is `constants → normalize → storage → search/curated_boards/command_center → startup → discovery`; cross-module references are **module-qualified** (e.g. `storage._find_existing_job`, not a bare import) so a test patching `app.services.jobs.<defining_module>.<fn>` reaches every caller. Patch tests at the defining module, not the `job_service` shim. (`command_center` imports `search as _search_mod` because `get_jobs` has a `search` parameter.)
32. Frontend types live in domain files under `frontend/src/types/` (`jobs.ts`, `people.ts`, `messages.ts`, ...); `types/index.ts` is a barrel re-export, so `@/types` imports keep working. Beware DOM-global name shadowing when adding types (e.g. `MessageChannel`, `Notification`): a missing cross-file type import resolves silently to the DOM type instead of erroring.
33. **Proxycurl is gone; LinkedIn enrichment is now free + self-hosted.** LinkedIn sued Proxycurl and it shut down permanently on 2025-07-04 (host `nubela.co/proxycurl` is dead). The client, config key (`proxycurl_api_key`), and call sites were removed — do not re-add them. Profile enrichment is now `app/clients/public_profile_client.py`: it reads the public **SERP snippet** (`"Name - Title - Company | LinkedIn"`) through the existing SearXNG layer, matched to the exact profile URL — $0, unlimited, no LinkedIn scraping, no stored credentials, fail-soft to `None`. The SERP-title parse is the shared `utils.linkedin.parse_linkedin_serp_title` (the single source of truth also used by the Brave/Google/SearXNG result parsers — don't re-fork it). It powers `enrich_person_from_linkedin` / `POST /api/people/enrich` (source label `public_web`) and recovers name/title/current-company/headline, **not** full experience/education history. It also backstops people discovery: `linkedin_backfill._enrich_existing_url_title` calls it to upgrade a weak/missing title on a *discovered* candidate that already has a LinkedIn URL — matched against that exact URL, so no wrong-person ambiguity (the name+company `search_exact_linkedin_profile` FIND path still handles candidates with no URL). For richer structured data a free-tier/paid API can slot in additively (People Data Labs free tier = 100 lookups/mo; Crustdata; Coresignal) — do **not** add server-side LinkedIn scrapers (the legal/operational risk that killed Proxycurl). The legacy `"proxycurl"` source string is intentionally **retained** in the trust/ranking/cache-eligibility lists (`people/company_match.CURRENT_TRUSTED_SOURCES`, `people/ranking.SOURCE_PRIORITY`, `known_people_service.GLOBAL_CACHE_ELIGIBLE_SOURCES`) only for backwards-compatible reads of old DB rows — same pattern as `firecrawl_public_web` (truth #11). Note: Tavily was acquired by Nebius (Feb 2026) — roadmap/pricing risk on the employment-corroboration provider; Exa is the independent alternative.
34. **People pre-warm is per-job and intentionally persists the top 3 contacts.** Every newly discovered job is queued for `auto_prospect.prewarm_job_people`, which runs `search_people_for_job(target_count_per_bucket=1)` and **persists** the resulting recruiter/HM/peer as `Person` CRM rows — this is deliberate (product decision 2026-06-22: the user wants people found for every job, surfaced on the People page and actionable from the job snapshot). The job is held out of `get_jobs` (`people_prewarm_status="pending"`) until the warm finishes or `PEOPLE_PREWARM_REVEAL_TIMEOUT` (3 min) elapses, whichever is first; the warm always flips the job to `ready` (even on failure/zero) so nothing is permanently hidden. Note this **supersedes** the older company-level `prewarm_company_people` / `search_people_at_company(persist=False)` design, which has been removed — pre-warm now does cross into CRM rows by design. The response/snapshot serialization shared by the `/people/search` handler, `prewarm_job_people`, and `refresh_job_research_snapshot` lives in `app/services/people/serialize.py` (single source of truth — import/patch it there, not the router). Snapshot freshness windows (`SNAPSHOT_FRESH_TTL` 24h, `SNAPSHOT_MAX_SERVE_AGE` 14d) and the serve/refresh/miss decision live in `job_research_snapshot_service.snapshot_serve_decision`. The pre-warm and refresh tasks live in `app/tasks/auto_prospect.py` and are event-triggered via `.delay` (no beat schedule).
35. **Posting time has two precisions, and ordering uses the real posting time — never ingest time.** `jobs/normalize._parse_posting_time(posted_at)` returns `(posted_ts, posted_date)`: `posted_ts` (precise `DateTime`) is set **only** when the source gives genuine sub-day precision — an ISO datetime, an epoch, or a fine relative phrase ("30 minutes ago", "just now") — so "15 minutes ago" in the UI is never fabricated; coarse sources (ISO date, "today", "3 days ago") set `posted_date` (day) with `posted_ts` left NULL. The date sort orders by `coalesce(posted_ts, posted_date, created_at)` so a freshly-discovered-but-old posting (real `posted_date` 2 weeks ago) sinks instead of riding our recent `created_at` to the top — the old `coalesce(posted_date, created_at)` was the "2-week-old jobs on top" bug. Both columns are pre-parsed at ingest (`storage._build_job` + the refresh path), so the query never casts the free-form `posted_at` string at runtime and invalid dates still resolve to NULL (audit pass-2 P3 invariant preserved). The frontend mirrors the precision: `dateUtils.formatJobPostedAt` shows granular relative time from `posted_ts`, falls back to day-level (`formatRelativeDay`) for `posted_date`, and never invents a time for a date-only value. Relative phrases re-resolve against `now` on every refresh, so a still-"3 days ago" posting stays correctly aged.
36. **Every job category has a curated, keyless substrate now — non-tech no longer depends solely on the paid aggregators.** The historical "great at SWE, thin everywhere else" gap was structural: SWE rests on ~160 free curated tech employers (Greenhouse/Ashby/Lever/Workday-tech/proprietary), while every non-tech occupation collapsed to JSearch+Adzuna — two paid single points of failure (JSearch monthly-quota-capped, Adzuna key-gated) with no free fallback (Dice/Simplify/Jobicy/newgrad/Remotive are tech-only; Remotive even ignores the query). The fix is three keyless, free additions: (a) **The Muse** (`themuse_client`, all-industry, category↔occupation map, distinctive-token relevance gate) in `DEFAULT_SEARCH_SOURCES` + both discover source lists; (b) broadened `OCCUPATION_VERTICALS` so the general-professional functions pull all four curated Workday verticals (banks/hospitals/universities/retailers staff a full back office); (c) non-tech per-company limit raised 20→40. Do **not** re-add a Muse category name without live-verifying it (a wrong name silently returns 0), and do **not** assume non-tech recall comes from the aggregators — it comes from The Muse + the curated verticals.
37. **The jobs feed hot path is deliberately thin — keep it that way.** `GET /api/jobs` loads rows with `defer(Job.description)` and serves a 500-char `description` preview + `description_truncated` flag (`get_description_previews`); the full text comes from `GET /api/jobs/{id}` (the JobsPage detail panel fetches it via `useJob` when truncated). Never read `job.description` on rows loaded with `defer_description=True` — it lazy-loads on the async session and raises `MissingGreenlet`. Responses are GZip-compressed and rendered with ORJSON (`main.py`). The dice/newgrad apply-URL repair is a debounced background task (`search.queue_apply_url_repair` → `tasks/jobs.repair_job_apply_urls`), never an inline network call on the read path. Dedup in `store_jobs` is set-based: `storage._prefetch_existing_jobs` bulk-loads all candidates into a `_DedupIndex` (same probe order as the per-row `_find_existing_job`, which consults the index when given) — tests that mock the DB session must patch `storage._prefetch_existing_jobs` alongside `storage._find_existing_job`. The Celery worker runs `--concurrency=2 -Q celery,prewarm`; people pre-warm and snapshot refresh are routed to the `prewarm` queue so sends/refreshes never sit behind the pre-warm backlog (scale by adding a worker service consuming only `-Q prewarm`). Pre-warm is queued as **company-grouped batches** (`storage._maybe_prewarm_people` → `auto_prospect.prewarm_job_people_batch`, ≤`PREWARM_COMPANY_BATCH_MAX` jobs/task with a wall-clock budget that reveals the unfinished tail); the legacy per-job `prewarm_job_people` task is kept only for in-flight messages during deploys. The board crawls (`fetch_curated_ats_source_payloads`, `crawl_and_store_discovered_boards`, `discover_workday_companies`) share **one keep-alive httpx client per run** — `search_greenhouse/lever/ashby`, `search_lever_html`, and `search_workday` accept a keyword-only `client=`; omitted, they own a short-lived client (old behavior), so never revert them to per-call `async with httpx.AsyncClient(...)`. The JobsPage list renders a growing window (`INITIAL_VISIBLE_JOBS`, IntersectionObserver + Show-more) instead of all 200 cards at once.
38. **Client IPs come from `utils/client_ip.client_ip(request)`, never `request.client.host`.** The API is only reachable through an edge proxy, so the socket peer *is* the proxy: keying on it puts every visitor in one bucket and turns `referral_signup_ip_daily_limit` from per-IP anti-fraud into a site-wide ceiling that locks out real signups. Resolution is hop-count based — `NEXUSREACH_TRUSTED_PROXY_HOPS` = the number of proxies we control, and the real caller is that many entries from the **right** of `X-Forwarded-For` (each proxy appends the address it received from, so everything further left is client-written). Production API fails config validation below 1. **Do not "fix" this with uvicorn `--forwarded-allow-ips='*'`** — uvicorn's always-trust path returns `x_forwarded_for_hosts[0]`, the *leftmost*, client-supplied entry, which would let anyone choose their own rate-limit key with a single header (verified against uvicorn 0.30.6's `ProxyHeadersMiddleware`). Resolution fails safe: a missing header, a chain shorter than the hop count, or a non-IP value falls back to the peer (shared bucket) rather than trusting attacker input. Verify a deployment with the token-gated `GET /api/ready`, which reports `client_ip` / `socket_peer` / `trusted_proxy_hops`.
39. **The companion background worker authorizes every message by sender origin AND type, and its API origin is pinned at build time.** It holds the long-lived `nrc_` companion token and can act as the user, so "a message arrived" is not authorization. `isAuthorizedMessage` in `extension/background.js` allows our own extension pages (popup) everything, and allows a content script only the types its page needs — the allowlist is `ALLOWED_TYPES_BY_SCRIPT`, and the matching **origins are derived from the live manifest's `content_scripts` matches** so they cannot drift from where each script is actually injected (build.mjs rewrites those matches for prod, and the rules follow automatically). Consequence: the web app can run the connect handshake (`NR_EXTENSION_*`) but can NOT reach `SET_TOKEN`, `LOGOUT`, or the LinkedIn capture handlers; a job board gets `GET_PROFILE` only. `app-bridge.js` enforces the same app-side list before forwarding a page `postMessage` — keep the two in step. Separately, `apiUrl` is **never** read from a message: `getConfig` always returns `NR_DEFAULTS.apiUrl`, `setConfig` has no apiUrl channel, and any legacy stored value is purged on worker start. A caller-supplied origin was a token-exfiltration primitive that persisted in `chrome.storage.local` long after the injecting script was gone. To point the companion elsewhere, edit `config.js` (dev) or rebuild with `NR_API_ORIGIN` (prod). Covered by `extension/tests/message-auth.test.mjs`, which runs in CI (`extension-test` job) along with a check that the packaged manifest contains no localhost.
40. **Third-party and account-less PII expires on a clock, and both have an erasure path.** Two places hold data for people the normal `/api/account/delete` flow cannot reach. (a) **Waitlist members have no account**: `tasks/waitlist_retention.purge_waitlist_pii` (daily beat) nulls `signup_ip` after `waitlist_signup_ip_retention_days` (the live anti-fraud control is the 24h Redis window, so the column is forensic only) and deletes the Storage object + resume columns after `waitlist_resume_retention_days`; `DELETE /api/referrals/me` (owner token, same as `/status`) erases the row **and** the stored file together. `purge_expired_resumes` deletes the object BEFORE clearing the metadata — reverse that and a failure leaves a row claiming "no resume" while the file lingers unreferenced. (b) **The global known-people cache describes third parties**: `maintain_known_people_cache` now calls `purge_expired_records` (delete after `known_people_purge_days`, must stay > the 90-day expiry flag) instead of only flagging rows, and `scripts/erase_known_person.py` services a removal request — deliberately a script, not an endpoint, since these are rare, manual, and an endpoint would add an enumeration oracle. The cache stores **no email column at all** (migration 048 nulled it, 064 dropped it, `_sanitize_profile_data_for_cache` strips every email-shaped key from `profile_data`); a discovered email belongs on the finding user's own `Person` row. `GET /api/waitlist` is rate-limited (5/min) and production rejects an admin token shorter than `MIN_ADMIN_TOKEN_LENGTH`.
41. **A search provider that is broken looks exactly like one with no results — so it is now counted, not just logged.** The 2026-07-26 functionality audit found Google CSE returning HTTP 400 "API Key not found" and Serper returning HTTP 400 "Not enough credits", for an unknown period, with **zero** signal: both clients only special-cased 403/429, so a 400 fell through to `raise_for_status()` and was swallowed by a bare `except httpx.HTTPError: return []`, and the router logged `search provider empty` at INFO — identical to a quiet query. Every LinkedIn x-ray in the product was silently being served by Brave, the provider truth #4 calls the weakest for LinkedIn. Now: both clients log the status + body snippet at WARNING (the body is where "Not enough credits" lives) and record an `error` outcome; the router records `hit`/`empty`; `clients/search_provider_health.py` keeps hourly Redis counters and `tasks/jobs.monitor_search_provider_health` (6-hourly beat) escalates a *sustained* pattern to ONE aggregated ERROR per provider, mirroring `_monitor_source_health`. Two distinct verdicts because they need different fixes: `errors` (credential/quota) vs `no_results` (answers 200, never returns anything). Only *configured* providers are judged. All of it is fail-soft — health accounting must never break a search. **Celery beat now gates three user-visible guarantees** (occupation retagging, waitlist retention, provider alerting), so `tasks/jobs.beat_heartbeat` stamps Redis every 5 min and `GET /api/ready` reports `celery_beat: {status, age_seconds}` — reported, never gating readiness.
42. **An unclassified job is invisible to every occupation chip, not merely ranked lower.** The feed filter is an exact tag match (`Job.tags.contains(['occupation:<key>'])`), so a job the classifier can't place drops out of the product's primary targeting primitive entirely. Measured on a real 575-job feed (2026-07-26): 31% unclassifiable, and the misses clustered on mainstream target roles — 50 contained "engineer", 39 "manager", 25 "product". Fixed to 16% by (a) adding the engineer titles that carry no "software" token (`product engineer`, `growth engineer`, `integration engineer`, `cloud engineer`, `customer engineer`, `test`/`verification engineer`, `solutions engineer`, …) plus partner/BD, people and financial-crime titles, and (b) letting `classify_title` consult the description lead for **any** unmatched title, not only "generic" ones. (b) needs care: accepting any alias hit tagged "Engineering Manager, Payments" as HR and "Tax Technology Lead" as ML, so the fallback scores occupations by distinct alias hits and takes the single best only when it clears `_DESC_FALLBACK_MIN_HITS` (2) AND strictly beats the runner-up — a wrong tag is worse than no tag, because it puts the job in front of the wrong person. **Aliases are not free**: they feed the Muse relevance gate's TF-IDF vocabulary, so adding an "…operations engineer" alias silently broke `business_analyst` matching (caught by `test_relevance_gate_drops_off_category_noise`). Never introduce an `operations` token into another occupation's aliases — see the `revops` comment in `sales`.
43. **Discovery degrades targeting; it must not delete inventory — and discovered contact fields are scrubbed before anything reads them.** Two fixes from the 2026-07-26 functionality audit. (a) `search._occupation_relevance` used to reject an `unclassified` result outright, same as `off_category`. They are different verdicts: *off_category* means we identified the role and it is something else (drop it), *unclassified* means we could not tell. Rejecting the second threw away real inventory — a `software_engineering` discover discarded **237 of 660** curated SimplifyJobs early-career roles purely because their titles didn't classify, in a product whose first-named audience is new grads and interns. Unclassified results are now **kept with no occupation tag**, and `search.py` pops `_occupation_hint` for them so `_infer_occupation_tags_for_job`'s hint fallback cannot stamp the *searched* occupation onto a job we couldn't classify (that is how engineering roles reached Marketing). The exact-match feed filter still won't surface them under the wrong chip — the protection is preserved, the deletion is not. (b) `services/people/contact_quality.py` scrubs discovered contact fields in `_prepare_candidates`: a LinkedIn feed post parsed as a job title, the company name as a title, and placeholder junk all become `None`, and `greeting_name` trims LinkedIn's truncated "Christopher K." so drafts don't open with an obvious tell. Posture is **clean, don't discard** — recall costs real provider calls, so only a candidate with no usable identity is dropped. NB the prose detector strips title abbreviations (`Sr.`, `Ph.D.`) before testing for sentences, or it eats valid titles like "Sr. IP Product Engineer".
44. **A capture from the user's browser is a claim, not evidence — and it never leaves the user who made it.** The September 2026 audit found `POST /api/people/hiring-team-capture` promoting client-submitted contacts to `verified`, ranking them above every server-verified signal, *and* writing them into the global `known_persons` cache other users read. Authentication proves who is calling, not where the content came from, so one user's page-scrape (or a poisoned page) became everyone's "verified" fact. Now the source is `client_capture`, rows carry `provenance` with verification explicitly cleared, `job_id` ownership is enforced, the shared-cache write is deleted, and migration `068` quarantined every row the old path published (`verification_status='quarantined'`, excluded from all cache reads). The general rule this encodes: **client-supplied assertions may be stored privately for the submitter, never promoted into shared state or trusted ranking tiers.**
45. **An email send that "failed" is not the same as an email that was not sent, and the distinction is now durable.** Before, an exception during dispatch put the message back to `staged` — meaning a provider timeout after the mail was accepted would send it again. `send_attempts` (migration `069`) records each dispatch with a payload digest before the network call; only a definitive rejection (`ValueError`, or a 4xx that is not 408) is retryable (`send_failed`), and everything else lands in **`delivery_unknown`**, which the scheduler never re-sends. `expire_unresolved_sends` promotes a stuck `sending` row after 10 minutes so nothing hangs forever. Cancellation/edit safety rides on `Message.schedule_version`: the scheduler claims a message by `(status, schedule_version, scheduled_send_at)`, so a cancel or edit that bumps the version invalidates an in-flight claim. **Never resolve a `delivery_unknown` by re-sending**; ask the provider.
46. **The renderer holds no credentials, and the API refuses to run unless that is true.** `pdflatex` is the largest untrusted-input attack surface in the product, so it runs in a separate Celery app with a separate broker from an image containing only `app/renderer_app.py`, `app/renderer_runtime.py`, `celery[redis]` and `pypdf`. There is no database URL, no provider key, and no application package to import. Production config validation demands `render_remote_enabled` + `renderer_isolation_enforced` + a renderer Redis URL that differs from `redis_url`. `renderer_isolation_enforced` is an **attestation**, not a feature flag: flip it only after verifying the deployed container's egress, filesystem, scratch, CPU, memory and PID limits. In production the renderer also self-checks at startup (non-root, no application secrets present, read-only root mount, cgroup memory/PID limits, `NEXUSREACH_RENDERER_EGRESS_ENFORCED=true`). Do not "simplify" this by importing `app.tasks` in the renderer or by pointing both workers at one broker.
47. **Paid work is reserved before it is performed, per account and per deployment.** `services/paid_work.reserve()` takes the global then account day-bucket lock (only that order), checks calls/tokens/concurrency, and **commits the reservation before provider I/O** — so a crash cannot lose the spend and a retry cannot double it. The `operation_id` is derived in `services/paid_context` from the Celery task id (or a prompt fingerprint), which is what makes a redelivered task reuse its reservation. Outside `test`/`e2e`, a paid call with no subject in context is a **503** — if you add a background entry point that spends money, `set_subject(user_id)` at the top of it, or your feature will fail closed. The `recover-paid-work-reservations` beat releases reservations abandoned by crashed workers.
48. **Deletion returns a receipt, not a promise.** `POST /api/account/delete` and `DELETE /api/referrals/me` are `202`: they write a tombstone, a deduped `deletion_request` (keyed by `Idempotency-Key`) and per-target `deletion_actions`, delete app data transactionally, and let the `retry-deletions` beat finish external erasure (Supabase identity, Storage objects). `GET /api/deletions/{id}` authenticates with the **receipt bearer** because a deleted user has no session left. The `auth_tombstones` row is the revocation barrier — `get_or_create_user` rejects a tombstoned subject, so a JWT minted before deletion cannot recreate the account — and it is retained past the longest possible token lifetime. Requires `NEXUSREACH_DELETION_RECEIPT_HMAC_KEY` (>= 32 chars) on the API role; the same key is *forbidden* on worker/renderer roles.
49. **The waitlist endpoint answers identically for everyone, and referral secrets never touch a URL or a counter.** `POST /api/waitlist` returns a bare `202 {ok: true}` — no `already_on_list`, no token, no queue position — because it is unauthenticated and any of those distinguishes a real member from a guess. Owner tokens travel in an `Authorization: Bearer` header, the single-use exchange credential travels in the `POST /api/referrals/exchange` body, and emailed links carry secrets in the **fragment** (`#t=` / `#v=`), which never reaches the server or a `Referer`; the owner key lives in `sessionStorage`. Credentials are rows in `referral_credentials` with real expiry (owner 7 days, exchange 30 minutes, with all but the two most recent owner keys pruned on issue) rather than a hash on the signup row, and a referral credit is a `UNIQUE(campaign_id, fingerprint)` row in `referral_credits` — the fingerprint an HMAC of the email under a sealed per-campaign key — so "one identity, one credit" is a database invariant that surviving deletion-and-resignup cannot farm. Recovery is its own endpoint with per-recipient cooldown (10 min), per-recipient daily cap (3) and a global hourly ceiling, and it always answers `202 {ok: true}`. The pre-existing query-token path stays valid for 7 days after campaign bootstrap (`legacy_until`) purely so links already in inboxes work; let it lapse.

## Pre-commit checklist

```bash
cd backend && ruff check app tests conftest.py
cd backend && pytest
cd frontend && npx eslint .
cd frontend && npx tsc -b
cd frontend && npm run test
cd frontend && npm run build
cd e2e && npm run test:real
```
