# NexusReach — Lessons Learned

Last updated: 2026-03-22

This is a curated list of the lessons that still matter for the current codebase. Older one-off historical notes were trimmed so this file stays useful to humans and AI tools.

## Architecture and data boundaries

### Keep company identity, role fit, and email trust separate
- A person can be a good same-company fallback without being a verified current employee.
- A person can be a verified current employee without the company domain being trusted for email guessing.
- **Lesson:** model these as separate fields and preserve the distinctions all the way to the UI.

### Same-company hierarchy is better than verified-only emptiness
- The earlier verified-only bucket strategy often returned nothing useful.
- Users still need someone to contact when the exact ideal person is not available.
- **Lesson:** rank same-company contacts as `direct`, `adjacent`, and `next_best` instead of dropping everything below perfect confidence.

### Public identity trust belongs on the company model
- `normalized_name`, `public_identity_slugs`, and `identity_hints` are now core system fields.
- **Lesson:** company identity is not just enrichment metadata. It drives search precision, The Org traversal, and verification safety.

## Search and provider routing

### Brave is valuable, but not as the default bulk engine
- Brave is still strong for exact LinkedIn x-ray lookups.
- Bulk discovery burns credits too quickly there.
- **Lesson:** reserve Brave for exact LinkedIn backfill and fallback, and move primary bulk search to Serper.

### Tavily is better for corroboration than LinkedIn x-ray
- Tavily shines when the goal is public-web evidence and summarized corroboration.
- It is not the best first provider for deterministic `site:linkedin.com/in` work.
- **Lesson:** use Tavily for employment corroboration and fallback public discovery, not the main LinkedIn path.

### Sequential fallback beats fan-out for cost control
- Calling every provider on every query hides failures but burns credits fast.
- **Lesson:** try providers in configured order, stop when enough useful results are present, and cache the result family.

### Query-family caching matters
- People search repeats the same queries constantly across retries and UI flows.
- **Lesson:** cache by provider + query family + normalized params, not just raw query string.

## Exact-job ingestion

### Two job-ingestion lanes are necessary
- Board-backed ATS feeds and exact-job URLs behave differently enough that they should not share the same assumptions.
- **Lesson:** support both board-backed search and exact-job ingestion as first-class lanes.

### Exact-job imports should canonicalize before dedupe
- Tracking params and location fragments create duplicate saved jobs.
- **Lesson:** canonical URL must be part of the normalization step, not a later cleanup.

### Metadata-only pages are still useful exact-job pages
- Some proprietary careers pages and Workday pages expose most useful job data in metadata and hydration blobs, not visible body text.
- **Lesson:** exact-job fetchers need to preserve raw HTML even when extracted visible text is sparse.

### Workday outages should fail honestly
- Workday can redirect to maintenance or outage pages that look superficially “successful” at the HTTP layer.
- **Lesson:** detect those redirects explicitly and return a clean failure instead of importing the wrong landing page.

## The Org and public verification

### The Org is reliable when parsed from embedded data
- The Org pages expose structured data that is far more stable than brittle visual parsing.
- **Lesson:** prefer embedded page data and explicit page-type parsing over raw markdown/text scraping.

### Do not trust the first The Org slug you see
- Short or ambiguous brands can accumulate bad or stale slugs.
- **Lesson:** validate org pages, cache preferred good slugs, and mark failed slugs in company hints.

### Team-page verification must be stricter than person-page verification
- A trusted team page does not verify arbitrary names.
- **Lesson:** require the candidate name and matching title or entry evidence on the team page before granting current-company verification.

### The Org/public trust should not reactivate unsafe email guesses
- Public identity success does not prove the company’s email domain.
- **Lesson:** keep public-company verification and email-domain trust on different rails.

## LinkedIn backfill and role recovery

### Humans resolve ambiguity better than the tool, so the tool must stay conservative
- A user can often find a correct LinkedIn profile manually that the tool should refuse to attach automatically.
- **Lesson:** exact-person LinkedIn backfill should bias toward precision over recall.

### Backfill should happen after a candidate is already worth keeping
- Running name-to-LinkedIn matching on every raw candidate is noisy and expensive.
- **Lesson:** backfill only for surviving verified or strongly trusted public candidates.

### Weak titles need a recovery pipeline
- Public results often collapse titles to the company name or a noisy snippet.
- **Lesson:** recover titles from snippets, The Org person pages, and trusted team pages before ranking or backfilling.

## Email behavior

### Best-guess emails need explicit basis metadata
- Once multiple guess modes exist, “best guess” alone is too vague.
- **Lesson:** store whether the guess came from a learned company pattern or a weaker generic/domain path.

### Safe best guesses are useful, but only with domain gating
- Users would rather have a labeled guess than nothing, but unsafe guesses create reputational risk.
- **Lesson:** allow best guesses only from approved domain signals and keep ambiguous brands blocked.

### Learned patterns compound value
- Spending effort to learn one company pattern improves many future lookups.
- **Lesson:** learned pattern reuse is more valuable than repeated per-person blind guessing.

## Testing and frontend UX

### Saved contacts must be visually separated from live search output
- Mixing old saved contacts with fresh people-search results caused real confusion during UI testing.
- **Lesson:** group saved contacts by company, filter them by company, and hide them during live people-search loading.

### Role-based queries are safer than text-only queries
- This codebase has many repeated labels and statuses.
- **Lesson:** prefer Testing Library role queries and exact labels to avoid brittle test failures.

### shadcn/ui in this repo is Base UI, not Radix
- Old habits around `asChild` and Radix-specific dialog props caused repeated mistakes.
- **Lesson:** always inspect the local component implementation before assuming prop APIs.

## Environment and local execution

### `backend/.env` loading depends on the current working directory
- Running helper scripts from the repo root can silently miss backend config because settings load `.env` relative to the cwd.
- **Lesson:** run environment-sensitive backend scripts from `backend/` unless you explicitly load the env another way.

### Async relationship access still bites in SQLAlchemy
- Lazy relationship access inside async services can still trigger `MissingGreenlet`.
- **Lesson:** eagerly load what the service will need rather than relying on implicit lazy loads.

### Full repo lint/test commands matter
- Running only part of the suite misses real failures.
- **Lesson:** use:
  - `cd backend && ruff check app tests conftest.py`
  - `cd backend && pytest`
  - `cd frontend && npx eslint .`
  - `cd frontend && npx tsc -b`
  - `cd frontend && npm run test`
  - `cd frontend && npm run build`
