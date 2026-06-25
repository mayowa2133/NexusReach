# NexusReach — AI Agent Context

Last updated: 2026-06-23

This file is the current AI-facing project snapshot for NexusReach. It is intended for Codex, Claude, and other repo-aware assistants. `CLAUDE.md` intentionally mirrors the same project story so different tools inherit the same context.

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
- Job discovery is occupation-aware. The curated ATS boards are all tech employers and Dice/Simplify/newgrad lean tech, so when a discover run resolves to occupations that are *all* industry-bound non-tech (healthcare, education/training, legal/compliance, public-sector/government, arts/entertainment), `discover_jobs` routes only to the broad all-industry aggregators (JSearch / Adzuna / Remotive) and skips the tech-only sources. Cross-industry occupations (sales, marketing, finance, ...) keep the full source set because those seekers may target tech companies (`job_service.INDUSTRY_BOUND_NONTECH_OCCUPATIONS` / `_suppress_tech_sources`).
- **The Muse** (`themuse_client`) is the cross-industry, **free + keyless** breadth source that gives *every* occupation real curated depth independent of the paid aggregators. This matters because JSearch/Adzuna are the only other industry-agnostic sources and are single points of failure (JSearch is monthly-quota-capped — currently HTTP 429 — and Adzuna needs keys), while everything else (Dice/Simplify/Jobicy/newgrad/Remotive) is tech-only; without The Muse a non-SWE category collapses to ~0 when those two are down. The public API filters by a fixed `category` taxonomy that maps onto our occupations (`MUSE_CATEGORY_BY_OCCUPATION`, every category name live-verified — a wrong name silently returns nothing). Occupation-routed discovery passes the category directly and gates results to titles sharing a *distinctive* taxonomy token (TF-IDF auto-derived over occupation alias/seed vocab in `_build_distinctive_vocab`, so generic words like "manager"/"director" can't make every title match); the free-text saved-search path maps query→category and token-filters back to the query. It's in `DEFAULT_SEARCH_SOURCES` (so every saved-search refresh gets it) and both `discover_jobs` source lists; `publication_date` gives a precise `posted_ts`; fails soft to `[]` on quota/error. Optional `NEXUSREACH_THEMUSE_API_KEY` only raises the rate limit.
- **Early-career volume (new-grad + internships) is a first-class goal — coverage = more chances.** The dedicated tech early-career source is the SimplifyJobs GitHub lists (`remote_jobs_client.fetch_simplify_early_career_jobs`): it pulls *both* `SimplifyJobs/New-Grad-Positions` **and** `SimplifyJobs/Summer2026-Internships` (+ `vanshb03/Summer2026-Internships`), each level-stamped from the source list (`level_label` New Grad / Internship → `new_grad` / `intern`), ↳-repeat-company-aware, 🔥/⭐-marker-stripped, deduped — ~590 roles (224 new-grad + 366 internships), up from the old 50-cap new-grad-only (internships were ~0). The big SimplifyJobs repos are HTML tables now, so `_parse_simplify_html_jobs` (not the markdown path) carries the level. `simplify` is in `DEFAULT_SEARCH_SOURCES`, so it refreshes every cycle. For **non-tech** early-career, The Muse `boost_early_career` adds dedicated `Entry Level` + `Internship` level pulls on top of the all-levels pull (additive budget so senior roles never crowd them out) across every occupation — wired on for the `themuse` source. The Muse's own `level` is stamped as `level_label` so experience classification is authoritative, not title-guessed. Net: a SWE discover now yields ~600+ early-career roles vs ~50 before.
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
- **Cross-source corroboration** is an accuracy signal in all three buckets: when ≥2 independent strategies surface the same person, `candidates._dedupe_candidates` unions the distinct `source` values onto `_corroborated_by` (instead of silently dropping the duplicate), and `ranking._corroboration_rank` sorts corroborated candidates ahead of equally-titled singletons. It sits just below the strong direct-evidence tiers (hiring-team capture, GitHub-team, published-leader) and helps tech and non-tech equally.
- **Recruiter discovery** additionally mines the company's own recruiting/talent-team page (`company_site.discover_company_site_recruiters` — TA-specific paths + SERP, recruiter-tuned LLM extraction, regex-filtered to recruiting titles, own-domain → strong-signal). It runs for every role type (recruiters are universal) via the shared `people/service._gather_company_site_recruiters` helper in both flows, and is the best free recruiter source when the companion's hiring-team capture isn't available.
- People discovery additionally mines the posting itself (named contact emails rank first; reporting-line titles seed the HM search), searches LinkedIn feed posts for the recruiter who announced the exact req, annotates shared school/past-employer affinity from the user resume, applies bounded reply-rate priors from the user own outreach history, and accepts contact feedback that evicts bad known-people cache rows.
- For engineering roles at companies with public repos, the GitHub-team strategy (`app/services/people/github_team.py`) resolves the recent contributors to the org repos matching the job team keywords into LinkedIn titles: lead/manager-titled, company-evidenced contributors become hiring-manager candidates, the rest become high-confidence peers on GitHub evidence alone. GitHub-team membership is the strongest signal in the hiring-manager and peer rankings. Org slug is derived from the company name and validated via the GitHub API (cached). Recency-ranked (recent commits, not all-time) so departed heavy committers do not surface; former-employee and wrong-person LinkedIn matches are filtered.
- The companion can capture LinkedIn's "Meet the hiring team" panel from a job page the user is viewing (`POST /api/people/hiring-team-capture`, `app/services/people/hiring_team_capture.py`): the named req owners are stored as `verified` contacts in the recruiter/hiring-manager buckets and cached for the company. A hiring-team-captured contact is the single top signal in the recruiter and hiring-manager rankings — above the GitHub-team lead — because LinkedIn itself attached them to the exact posting. Covers every role type, including non-engineering and private-repo companies the GitHub strategy cannot.
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
  - **Visibility gate:** `get_jobs` hides a job whose `people_prewarm_status == "pending"` *unless* it is older than `PEOPLE_PREWARM_REVEAL_TIMEOUT` (3 min) — so a new job surfaces the moment its people are warmed, or after the timeout if the warm stalls. Existing/old jobs and non-discovery inserts default to `ready` and are never hidden. The `GET /api/jobs` response includes `warming_count` (jobs still pending and within the timeout); the frontend feed polls every 4s while it's > 0 and shows a "finding the best people…" banner so warmed jobs appear automatically.
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
  - direct `httpx`
  - Crawl4AI
  - Firecrawl only if configured
- Firecrawl is optional fallback infrastructure, not a hard dependency.
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
- Frontend Sentry and PostHog initialize only when configured. PostHog autocapture
  and session recording are disabled by default.

## Tech stack

### Frontend
- React 19 + TypeScript
- Vite
- React Router
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
- Crawl4AI / Firecrawl: public-page retrieval fallback stack
- Gmail API / Microsoft Graph: draft staging

### Production deployment target
- Vercel serves the frontend from the `frontend` project root.
- Railway runs three backend services from `backend`:
  - FastAPI web service using `backend/railway.web.toml`
  - Celery worker using `backend/railway.worker.toml`
  - Celery beat using `backend/railway.beat.toml`
- Supabase provides hosted Postgres and auth.
- Railway Redis is shared by Celery, search cache, and rate-limit storage.
- SearXNG runs on Railway or another private reachable host.
- `backend/Dockerfile` is the production backend runtime and installs TeX Live for `pdflatex` resume PDF generation.
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

# Real browser E2E
cd e2e && npm install
cd e2e && npx playwright install chromium
cd e2e && npm run test:real

# LinkedIn graph local connector
cd backend && python scripts/linkedin_graph_connector.py --help

# Curated Workday board health check (drift detection + repaired configs)
cd backend && python scripts/verify_workday_boards.py
```

## Environment variables

### Backend
```env
NEXUSREACH_DATABASE_URL=postgresql+asyncpg://...
NEXUSREACH_REDIS_URL=redis://...
NEXUSREACH_SUPABASE_URL=https://...
NEXUSREACH_SUPABASE_KEY=...
NEXUSREACH_SUPABASE_SERVICE_ROLE_KEY=...
NEXUSREACH_SUPABASE_JWT_SECRET=...
NEXUSREACH_AUTH_MODE=supabase
NEXUSREACH_DEV_AUTH_BYPASS_ENABLED=false
NEXUSREACH_DEV_USER_ID=00000000-0000-0000-0000-000000000001
NEXUSREACH_DEV_USER_EMAIL=dev@nexusreach.local
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
```

## Critical implementation truths

1. `backend/.env` is loaded relative to the current working directory. Running scripts from the repo root can miss backend config.
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
