# Functionality Audit — 2026-07-26

Question asked: *are we doing everything we can to give users the best product?*
So this measures the product against its own promise rather than looking for
defects in isolation.

**The promise** (PRD + landing page): for every job you target — the recruiter,
the hiring manager, and a peer, with evidence, a warm path, a safe email, and a
draft. You approve every send.

**Method.** Read the pipeline, then *ran* it: 580 real jobs in the dev database
measured directly, the occupation classifier replayed over all 575 real titles,
and a live people search + email lookup against a real company using the
configured providers. Findings below are measurements, not inferences, except
where explicitly flagged.

**Caveat that matters:** the measurements come from the local dev environment.
Its `.env` points `DATABASE_URL` at the **production Supabase pooler**, so the
provider credentials in it are very likely the production ones — but confirm in
Railway before acting on #1.

---

## Summary

| # | Severity | Finding | Status |
|---|----------|---------|--------|
| 1 | **Critical** | Two of three LinkedIn discovery providers are dead — and fail silently | **Detection fixed 2026-07-26; credentials need you** |
| 2 | **High** | ~31% of jobs can never appear under any occupation chip | **Fixed 2026-07-26 (31% → 16%)** |
| 3 | **High** | Occupation targeting depends entirely on a daily beat, with no fallback | **Fixed 2026-07-26 (beat heartbeat)** |
| 4 | Medium | Feed skews 85% mid/senior, against the stated early-career audience | **Root cause fixed 2026-07-26** |
| 5 | Medium | ~18% of surfaced contacts are unusable (post text as job title, empty names) | **Fixed 2026-07-26** |
| 6 | Medium | 25% of the feed is in countries the product doesn't target | **Fixed 2026-07-26 (20% → 12%)** |
| 7 | Medium | 90% of jobs come from one source; the non-tech breadth source is absent | **Not a defect — sources verified healthy** |
| 8 | Low | ~73s cold latency from job → contact → email | **Improved twice — 61s → 51s; still open** |
| 9 | Low | 15 jobs sat in `people_prewarm_status='pending'` for 7 days | **Fixed 2026-07-26** |

### Remediation — 2026-07-26

**#1 (detection).** The credentials themselves are yours to reissue — see below
— but the *silence* is fixed. Both clients only special-cased 403/429, so a 400
fell through `raise_for_status()` into a bare `except httpx.HTTPError: return []`
with no log at all. They now log the status and body snippet at WARNING (the
body is where "Not enough credits" and "API Key not found" actually live) and
record an error outcome. `clients/search_provider_health.py` keeps hourly
counters; `tasks/jobs.monitor_search_provider_health` (6-hourly) escalates a
*sustained* pattern to one aggregated ERROR per provider, mirroring the existing
`_monitor_source_health`. It distinguishes `errors` (credential/quota) from
`no_results` (answers 200, never returns anything) because those need different
fixes, and only judges providers that are actually configured.

Verified live — the same two calls that used to return `[]` in silence:

```
WARNING serper rejected a query: HTTP 400 — {"message":"Not enough credits","statusCode":400}
WARNING google_cse rejected a query: HTTP 400 — {"error":{"code":400,"message":"API Key not found. …
```

**#2.** 31% → **16%** unclassifiable on the same 575-job feed; **84 jobs
recovered** into the chips. Two changes: mainstream engineer titles that carry
no "software" token (`product engineer`, `growth engineer`, `integration
engineer`, `cloud engineer`, `customer engineer`, `test`/`verification
engineer`, `solutions engineer`) plus the partner/BD, people and financial-crime
titles that were missing; and `classify_title` now consults the description lead
for *any* unmatched title rather than only "generic" ones.

The second change needed correcting mid-flight. Accepting any alias hit in the
lead recovered more (8%) but tagged `Engineering Manager, Payments` as
**human_resources** and `Tax Technology Lead` as **machine_learning_ai** — one
incidental mention in boilerplate. The original author's caution was right. The
fallback now scores occupations by distinct alias hits and takes the single best
only when it clears two hits *and* strictly beats the runner-up. Fewer jobs
recovered, no scattershot tags (per-job: 457×1 tag, 24×2, 0×3+), and a wrong tag
— which puts a job in front of the wrong person — is avoided.

One trap worth recording: aliases feed the Muse relevance gate's TF-IDF
vocabulary. Adding a `technical operations engineer` alias silently broke
`business_analyst` matching, caught by
`test_relevance_gate_drops_off_category_noise`. Never introduce an `operations`
token into another occupation's aliases.

**#3.** `tasks/jobs.beat_heartbeat` stamps Redis every 5 minutes and
`GET /api/ready` now reports `celery_beat: {status, age_seconds}` — reported,
never gating readiness. Beat had quietly become load-bearing for three
user-visible guarantees: occupation retagging (targeting), waitlist retention
(privacy, from the security audit), and now provider alerting.

Verified: 1868 backend tests, ruff clean, 22 new regression tests.

### ⚠️ Still needs you (#1)

Nothing above restores recall. Until these are fixed, LinkedIn discovery runs on
Brave alone:

- **Google CSE** — HTTP 400 *"API Key not found"*. The key is revoked or
  mistyped, not merely over quota. Reissue it.
- **Serper** — HTTP 400 *"Not enough credits"*. Top up.

These came from the local `.env`, which points `DATABASE_URL` at the production
Supabase pooler — so they are very likely the production values. Confirm in
Railway. After fixing, the 6-hourly monitor will confirm recovery, and the first
sustained failure after that will page instead of hiding.

### Remediation — mediums, 2026-07-26

**#5 — contact quality.** `services/people/contact_quality.py`, applied in
`_prepare_candidates`. A feed post parsed as a job title, the company name as a
title, and placeholder junk are stripped to `None`; `greeting_name` trims
LinkedIn's truncated "Christopher K." so a draft doesn't open with an obvious
tell. Posture is **clean, don't discard** — a discovered contact cost real
provider calls, and a person with a bad title is still worth reaching, so only
a candidate with no usable identity at all is dropped.

Caught while testing: the first prose detector ate `Sr. IP Product Engineer, AI
Processor`, because "Sr." looks like a sentence end. It now strips title
abbreviations before testing. That would have silently discarded valid titles —
a worse bug than the one being fixed.

**#6 — country coverage.** 20% → **12%** country-less; 47 jobs newly
filterable. Two causes: `COUNTRY_ALIASES` was missing real countries appearing
in the feed (Luxembourg, Uruguay, Philippines), and bare city names resolved to
nothing. Added `UNAMBIGUOUS_CITY_COUNTRY`, consulted only after every other rule
declines and only for cities with no US/Canada homonym — "Bengaluru" alone was
41 of the 116. Ambiguous names are still left to the geocoder, which already
places London/Dublin/Toronto correctly. The remaining 69 ("N/A", "Remote",
"Worldwide", "Dublin OR London") are genuinely unresolvable and correctly left
alone.

**#4 — early-career skew: root cause found and fixed.** The source is not the
problem. `fetch_simplify_early_career_jobs` returns **660 jobs** live (339
internships, 321 new grad) against 18 in the feed. The loss was the occupation
relevance gate: on a `software_engineering` discover it **discarded 353 of 660**,
and 237 of those purely as `unclassified` — the classifier couldn't place the
title, so the job was thrown away rather than merely untagged.

`unclassified` and `off_category` are now treated as the different verdicts they
are. off_category still rejects; unclassified is kept with **no** occupation tag,
and the query hint is stripped so the hint-fallback can't stamp the searched
occupation on it. Measured after: **307 → 544 kept (+237)**, only genuine
off_category still rejected, and **0** jobs mis-tagged with the searched
occupation.

This is the same root cause as #2 — an unclassified job was being penalised
twice, hidden from the chips *and* deleted at ingest.

**#7 — not a defect.** Both suspect sources are healthy when called directly:
The Muse returns 40/40/10 for marketing/finance/HR, SimplifyJobs returns 660.
The dev feed's 90%-Greenhouse shape reflects which discovery runs happened in
that database, not a broken adapter. No code change; the #4 gate fix also lifts
non-tech breadth, since unclassified non-tech roles were being discarded the
same way. Worth re-measuring against production before treating it as real.

Verified: 1893 backend tests, ruff clean, 30 new regression tests.

### Remediation — lows, 2026-07-26

**#9 — stuck pre-warms: fixed.** `prewarm_job_people_batch` always flips a job
to `ready` (even on failure or zero results), and `_maybe_prewarm_people`
already un-sticks jobs whose enqueue raised — so a job left `pending` means the
task reached the broker and then never completed (worker crash, lost message,
mid-deploy restart). Nothing retried those; the audit found 15 pending for
nearly seven days, visible in the feed but with no people behind them and no
path to ever getting any.

`auto_prospect.recover_stuck_prewarms` (hourly) re-queues jobs pending beyond 30
minutes — comfortably past the 3-minute reveal timeout, so it never races a warm
that is simply still running — in bounded batches. Anything pending beyond 24
hours is retired to `ready` instead: at that point the task plainly never ran,
and retrying forever is worse than accepting there are no people for that job.

**#8 — cold latency: improved, not resolved. Being precise about this.**

Two independent, network-bound enrichment steps (`_gather_nontech_leaders`,
`_gather_company_site_recruiters`) ran sequentially in *both* the People-page
and job-aware flows — the second being the path a user hits from a job. They now
run concurrently.

Measured in isolation on a cold cache: 8.7s + 4.2s serial, so concurrency saves
roughly the shorter leg, **~4s per cold search**.

I nearly reported a much better number. A full search after the change came back
at 11.9s against the 40.1s baseline, which looks like a 70% win — but that run
was served largely from the 24h Redis search cache warmed by earlier identical
queries. A genuinely cold search against an untouched company still takes
**55.4s**. The parallelisation is structurally right and worth keeping, but it
is a few seconds off a total dominated by provider round trips and employment
verification, not a fix for the finding.

Actually resolving #8 needs the streaming approach the finding proposed —
returning each bucket as it resolves instead of awaiting all three, and starting
the email lookup speculatively for the top contact. That is a real API and UI
change and is left open deliberately rather than half-done.

Note the baseline was also measured while two of three search providers were
failing; each dead provider costs a round trip before falling through. Re-measure
after the credentials are fixed.

Verified: 1893 backend tests, ruff clean.

### #8 follow-up — profiled, then the actual bottleneck fixed

The finding proposed streaming "per bucket as they resolve rather than awaiting
all three". Profiling the cold job-aware path showed that premise is wrong: the
three bucket searches are **already concurrent** and finish together at 17.3s of
a 61.0s total. The other 72% is a chain of sequential enrichment stages behind
them. Streaming buckets would have targeted the 28% that was never the problem.

```
initial_bucket_searches (already concurrent)  17.3s   28%
theorg_expansion                              10.0s   16%
linkedin_backfill_top                          8.4s   14%
employment_verification                        7.2s   12%
actively_hiring_people_search                  6.6s   11%
hiring_managers_geo_public                     3.5s    6%
ambiguous_company_broad_employees              3.5s    6%
(+6 smaller)                                  ~4.5s    7%
```

**What was fixed.** Two of those tail stages are unconditional *discovery*, not
recovery — their inputs (company name, domain, geo terms, team keywords) are all
resolved before the gather, and neither depends on whether a bucket underfilled.
They are now folded into the initial gather:

```
cold, same job, same conditions:   61.0s -> 50.9s   (-10.1s)
initial_bucket_searches            17.3s -> 17.2s   (absorbed both extra searches)
contacts returned                      9 -> 9       (no recall lost)
```

**What was deliberately left sequential.** The remaining tail is
`theorg_expansion` (10.0s) and `hiring_managers_geo_public` (7.5s) — *conditional
recovery* passes that only run when the previous one left a bucket short.
Running those concurrently would spend paid provider quota on work that is
usually unnecessary; the latency is bought deliberately. `linkedin_backfill_top`
(7.2s) and `employment_verification` (6.1s) both operate on the final candidate
set and may be coupled (verification can read a backfilled title), so
parallelising them needs a correctness check that has not been done.

**#8 stays open.** 51s is better than 61s and it is honest work, but it is not
fast. Getting to a genuinely quick result needs the perceived-latency fix —
emitting usable contacts after the ~17s search phase and refining them as
enrichment lands — which is an API and UI change, not a scheduling one.

---

## 1. Critical — two of three LinkedIn providers are dead, silently

Tested directly against each provider's API:

```
google_cse   HTTP 400  — "API Key not found. Please pass a valid API key."
serper       HTTP 400  — {"message":"Not enough credits"}
brave        200       — 5 results
```

The router order for LinkedIn x-ray is `google_cse → serper → brave`. Both
Google-backed providers return nothing, so **every LinkedIn discovery query in
the product is being served by Brave alone** — the source `CLAUDE.md` truth #4
explicitly calls the weakest for LinkedIn:

> *"Google-backed sources have by far the best `site:linkedin.com/in` recall;
> Brave's independent index is weak for LinkedIn."*

The product is running its single most important discovery path on its declared
worst option, and has been for at least as long as those credentials have been
broken.

**It fails silently.** The only trace is `INFO search provider empty`. No alert,
no degraded-mode banner, no user-visible signal. A user sees fewer and
weaker-evidenced contacts and has no way to know the system is impaired. In the
live search below, only 4 of 28 contacts (14%) could be company-verified — a
plausible direct consequence, since verification leans on the same providers.

**Fix.** Two immediate: reissue the Google CSE key (the 400 says *not found*, so
it is revoked or mistyped, not merely over quota) and top up Serper. Then make
this class of failure loud: a provider that returns zero results for **every**
query in a run is not "empty", it is broken. Track per-provider hit rate and
alert when a configured provider's rate hits zero over a window. The fallback
chain is doing exactly its job — masking the outage — which is why it needs
telemetry on top.

---

## 2. High — ~31% of jobs can never surface under any occupation chip

The occupation chips are the product's primary targeting primitive. The feed
filter is `Job.tags.contains(['occupation:<key>'])`, so a job with no occupation
tag is invisible to **every** chip. There is no "everything else" bucket.

Replaying `occupation_tags_for_job` (title *and* description) over all 575 real
titles:

```
classified:    397  (69%)
unclassified:  178  (31%)   <- invisible to every chip, permanently
```

The misses are not exotic. They cluster on exactly the roles this product
targets:

| keyword in unclassifiable title | count | share of misses |
|---|---|---|
| engineer | 50 | 28% |
| manager | 39 | 22% |
| product | 25 | 14% |
| specialist | 17 | 10% |
| associate | 16 | 9% |

Real examples it cannot classify: `Staff Product Engineer`, `Customer Engineer`,
`Senior Cloud Engineer - Product Metrics`, `Design Verification Engineer Intern`,
`Sr. IP Product Engineer, AI Processor`, `Operations Intern`.

"Product Engineer" is a mainstream software title. So is "Cloud Engineer". A
new-grad SWE — the PRD's first-listed target user — filtering by Software
Engineering silently loses a chunk of the roles they want.

**Fix.** Two parts, and the second matters more. (a) Broaden `classify_title`
aliases to cover `product engineer`, `cloud engineer`, `customer engineer`,
`test/verification engineer`, and bare `… Manager` / `… Specialist` patterns.
(b) Stop letting an unclassified job vanish: either fall back to a default
occupation from the job's source/board, or make untagged jobs match any chip
rather than none. A miss should degrade ranking, never remove inventory.

---

## 3. High — occupation targeting rests entirely on a daily beat

In the environment measured, **93.8% of stored jobs (544/580) carry no
occupation tag at all**, and the chips return this:

| chip | jobs shown | jobs that actually exist |
|---|---|---|
| software_engineering | 21 | 84 |
| sales | 1 | 81 |
| product_management | 3 | 37 |
| project_management | 0 | 34 |
| marketing | 1 | 31 |
| accounting_finance | 0 | 25 |
| customer_service_support | 0 | 24 |
| legal_compliance | 0 | 22 |
| human_resources | 0 | 8 |

The right-hand column is what a simulated `retag_occupation_tags` run produces
over the same rows. So the inventory is there; it is simply not reachable.

**In fairness:** ingest *does* tag (`_infer_occupation_tags_for_job` runs inside
`store_jobs`), and the daily `retag-occupation-tags` beat heals older rows. Dev
runs no beat, so this exact 93.8% is a dev artifact and production will look far
better. **The finding is the fragility, not the number**: the primary targeting
primitive is only ever as fresh as the last beat run, newly-ingested jobs from
before a classifier change stay mis-tagged until it runs, and there is no
in-request fallback.

Worth connecting to the security audit: data retention now also depends on beat.
**Beat is now a single point of failure for two user-visible guarantees** —
targeting and privacy. It deserves a liveness alert of its own.

---

## 4. Medium — the feed skews away from the stated audience

```
senior    288   (50%)
mid       204   (35%)
new_grad   80   (14%)
intern      8   (1%)
```

85% mid/senior. The PRD's target users are, in order: *"new grad software
engineers, interns looking for return offers, early-career professionals"*.
`CLAUDE.md` states early-career volume is "a first-class goal — coverage = more
chances", and describes dedicated machinery for it (SimplifyJobs lists, The Muse
`boost_early_career`). That machinery is not showing up in the output: 8
internships total.

**Fix.** Verify the early-career sources are actually running and landing
(`simplify` is in `DEFAULT_SEARCH_SOURCES`, but only 18 jobs came from it here).
Consider weighting early-career in default ranking for users whose profile says
new grad or intern, rather than relying on ingest volume alone.

---

## 5. Medium — a fifth of surfaced contacts are unusable

From the live Stripe search (28 contacts saved), real rows:

| name | title as stored |
|---|---|
| Brian Delahunty | `Wonderful post from Letícia about their…` |
| Eric Geniesse | `Stripe` |
| Ingrid Sousa | `Stripe` |
| Ryan Peterman | *(empty)* |
| Christopher K. | Solutions Architect - Marketplace & Plat… |
| Johnson G. | Recruiting Manager |
| Gordon D. | Engineering Manager |

Three distinct defects:

1. **A LinkedIn post snippet parsed as a job title.** The SERP parser accepted
   feed content as a profile. That contact is noise and visibly wrong.
2. **Company name as title** (`Stripe`), and empty titles — no signal for the
   user, and nothing for the draft to work from.
3. **Initials-only names** (`Christopher K.`, `Johnson G.`) — LinkedIn truncates
   these for out-of-network profiles. Fine as data, but they flow into outreach
   drafts, where "Hi Christopher K." reads as obviously automated. This directly
   undercuts the product's core value: a message that doesn't look mass-sent.

That is ~18% of surfaced contacts either unusable or embarrassing in a draft.

**Fix.** Reject candidates whose title is empty, equals the company name, or
fails a sanity check (contains sentence punctuation, exceeds a length bound).
Separately, normalise truncated names for greetings — use the first name alone
rather than `First L.`

---

## 6. Medium — a quarter of the feed is in untargeted countries

```
United States  179      Ireland    51
(none)         116      Singapore  36
Canada          71      UK         28
                        Mexico     27
                        Australia   6
```

The product targets Canadians and Americans. 148 jobs (25%) are in countries it
doesn't serve, and another 116 (20%) have no country at all — which the
client-side country filter cannot touch, so a user filtering to Canada silently
loses those too.

**Fix.** Filter at ingest against the user's target regions, and backfill country
on the 20% missing it (most have a parseable `location`).

---

## 7. Medium — 90% of the feed comes from one source

```
greenhouse       523  (90.2%)
simplify_github   18  (3.1%)
jsearch           18  (3.1%)
jobicy             8
remotive           5
newgrad_jobs       2
themuse            1
```

Zero from Lever, Ashby, or Workday, despite `CLAUDE.md` describing a verified
~1,117-board registry across Greenhouse/Lever/Ashby plus curated Workday
verticals. **The Muse contributes one job** — and The Muse is documented as *the*
keyless breadth source that makes every non-tech occupation viable:

> *"without The Muse a non-SWE category collapses to ~0 when those two are down."*

JSearch is described as currently quota-capped and Adzuna is key-gated and unset
(confirmed: `NEXUSREACH_ADZUNA_*` empty). So the two paid all-industry
aggregators are down/absent and the free replacement is contributing ~0.2% —
non-tech coverage rests on nothing.

This may partly be a dev-database artifact of a partial crawl. Verify against
production before concluding; but if the shape holds, one adapter regression
takes out 90% of the product.

---

## 8. Low — ~73 seconds from job to contactable person, cold

Measured: people search **40.1s**, email lookup **32.7s**.

Pre-warm and the stale-while-revalidate snapshot exist precisely to hide this,
and do for warmed jobs. But any cold path — a new company, a stale snapshot, the
People page — is a 40s wait, and email is a further 33s on top.

**Fix.** Stream results per bucket as they resolve rather than awaiting all
three, and start email lookup speculatively for the top contact during the
people search.

---

## 9. Low — jobs stuck in `pending` for a week

15 jobs sat at `people_prewarm_status='pending'`, all ~6 days 22 hours old. The
visibility gate reveals them after 3 minutes so they aren't hidden, but their
pre-warm never completed and nothing retried it. Those jobs quietly have no
people behind them.

**Fix.** Re-queue pre-warm for jobs `pending` beyond the reveal timeout, or mark
them `failed` so the UI can offer a retry instead of showing nothing.

---

## What is genuinely good

Worth stating plainly, because the findings above are all deficits:

- **The people pipeline works, and the output is real.** A live Stripe search
  returned 28 contacts, 23 with LinkedIn URLs, including correctly identified
  recruiters (`Recruiting @ Stripe`, `Talent Acquisition @ Stripe`) and
  engineering managers. This is the hard part of the product and it delivers.
- **Email guessing is honest.** `mikaylahougan@stripe.com`, source
  `pattern_suggestion_learned`, confidence 85, status **`best_guess`** — labelled
  as a guess rather than asserted. That matches PRD principle 2 ("truthful over
  aggressive") and is the right call.
- **Verification is separated from ranking**, as the PRD requires — a contact can
  be `next_best` and still verified, and the UI shows the distinction.
- **Graceful LLM degradation.** `_resolve_provider` falls back to any configured
  provider rather than failing, so drafting survives a missing key.
- **Feed freshness is good** — 96% of jobs posted within 30 days, and 99% carry a
  working apply link.

---

## Recommended order

1. **#1 — reissue the Google CSE key and top up Serper today.** Everything
   downstream (recall, verification rate, contact quality) is degraded until
   this is fixed, and it is invisible. Then add per-provider zero-rate alerting
   so the next occurrence is loud.
2. **#2 — make unclassified jobs visible.** The fallback change is small and
   recovers ~31% of inventory immediately; the alias expansion can follow.
3. **#3 — add a beat liveness alert.** It now silently gates both targeting and
   data retention.
4. **#5 — add contact sanity checks.** Cheap, and directly protects the quality
   of every draft the product sends.
5. **#4, #6, #7 — coverage and relevance.** Verify against production first;
   the dev database may understate.
6. **#8, #9 — latency and stuck pre-warms.**
