# NexusReach Core Feature Audit

Date: 2026-07-12  
Scope: job discovery across occupations, people finding, and job-specific resume tailoring  
Repository baseline: `7f6b9b89`

## Executive summary

NexusReach has unusually broad foundations: 23 shared occupation categories, a large direct-ATS registry, non-technical Workday verticals, job-aware contact retrieval, evidence-ranked people results, inferred-claim review, and a deterministic resume quality gate. The architecture is strongest in job-aware software-engineering flows. The main product risk is that several later-stage components still encode software-specific assumptions even though the intake taxonomy is now cross-industry.

The audit found three immediate correctness risks:

1. Resume artifacts can render unsupported `skills_to_add` and `keywords_to_add` without the inferred-claim approval gate applied to bullet rewrites.
2. Company-level people searches default most roles to engineering context, and the final peer sort explicitly favors software titles over every non-technical title.
3. Occupation-targeted job searches store results without an occupation relevance gate. Generic titles can be tagged from the query hint even when the job is unrelated, and those rows remain in the user's global feed.

The highest-leverage next move is not adding more sources. It is building a shared, labeled cross-category evaluation system and then fixing the critical correctness paths. The product currently has a lot of retrieval capacity, but limited measurement of precision, recall, calibration, and downstream usefulness by occupation.

## Method and evidence

The audit traced the three features from API entry points through retrieval, normalization, classification, ranking, persistence, caching, rendering, and frontend presentation. It reviewed the current test suites and ran 206 focused tests covering occupation taxonomy/discovery, people ranking, resume tailoring, artifact generation, and quality evaluation. All 206 passed, with 16 existing warnings.

Executable probes confirmed that:

- `classify_title("Associate", nursing_description)` returns no occupation because description fallback is used only when the title is empty.
- an invalid stored occupation key silently produces the five software-engineering default queries;
- `_build_roles_context(["Registered Nurse"])` produces `department="engineering"` and no occupation keys;
- final peer ranking scores `Software Engineer` ahead of `Registered Nurse`, `Financial Analyst`, and `Marketing Manager` regardless of requested role;
- an empty one-entry resume is still required to produce at least five inferred-claim rewrites and three keyword rewrites;
- a rewrite adding one new word (`Led campaigns` to `Led brand campaigns`) is normalized as an ungated keyword rewrite;
- `CPA` and `SAP` supplied only through `skills_to_add`/`keywords_to_add` are rendered into a finance resume even though the source resume contains neither.

Passing tests show that the current behavior is internally consistent; they do not prove cross-category quality. In particular, the people eval suite contains only four hand-authored fixtures, does not evaluate peers, and begins with pre-labeled company confidence rather than testing retrieval and verification end to end.

This is a repository-grounded product-quality audit, not a live production relevance study. It did not spend provider quotas or scrape third-party services. Source recall and real-user precision therefore remain hypotheses until the evaluation and telemetry plan below is implemented. Code-path findings and executable probe results are direct evidence; expected production impact is labeled as impact or recommendation.

## What is already strong

### Job discovery

- The canonical 23-occupation taxonomy is shared with the frontend and several downstream services.
- Direct ATS aggregation, Workday verticals, The Muse category routing, Canadian coverage, startup provenance, source health history, canonical URLs, and stale/closed state provide a strong substrate.
- Engineering-only sources are intentionally gated away from known non-engineering searches, and occupation tags are periodically recomputed to self-heal classifier changes.
- Location, salary, experience, employment type, remote, startup, occupation, and recency filters are already available.

### People finding

- Job-aware searches use posting contacts, hiring-team capture, public search, company sites, The Org, GitHub evidence, employment verification, corroboration, warm paths, affinity, and outcome priors.
- Strong direct evidence can bypass fragile heuristics, while former-employee and ambiguous-company protections reduce confident false positives.
- Results expose confidence, match quality, reasons, warm paths, feedback, snapshots, debug traces, and source timing.

### Resume tailoring

- Bullet rewrites are tied back to source bullets, inferred claims are visible to users, and unaccepted inferred bullet claims are normally withheld from the PDF.
- The deterministic quality gate separates job fit, evidence quality, and parseability, excludes unsupported additions from scoring, and avoids prestige/demographic scoring.
- Resume reuse is opt-in by default, target-job quality is recomputed, LaTeX rendering escapes user text, and PDF compilation is sandboxed.

## Finding inventory

The audit records 34 concrete findings: 3 critical correctness risks, 14 high-priority quality/cross-category defects, and 17 medium-priority measurement, ranking, UX, and architecture improvements.

## Prioritized findings

### Critical

#### R1 — Unsupported skills and keywords are rendered without approval

`resume_artifact/latex.py::_render_resume_latex` merges `tailored.skills_to_add` and `tailored.keywords_to_add` directly into the skills section and focused skills. The bullet rewrite approval mechanism only filters `bullet_rewrites`. The tailoring prompt defines `skills_to_add` as skills the candidate “likely has but didn't list,” so these values are explicitly not guaranteed by source evidence.

Impact: a submission-ready PDF can claim a certification, license, tool, methodology, or domain capability that the candidate never confirmed. This is especially dangerous for regulated roles such as nursing, accounting, legal, healthcare, and public-sector work.

Fix:

- replace the three flat skill arrays with evidence-bearing suggestions: `{term, source_evidence_ids, change_type, requires_confirmation}`;
- render only source-supported or explicitly accepted terms;
- never infer licenses, degrees, clearances, certifications, languages, or legally scoped clinical capabilities;
- apply the same truthfulness ledger to bullets, summaries, headings, and skills;
- fail artifact generation closed if any rendered term has no source evidence or explicit acceptance.

Acceptance criteria: injecting `CPA`, `RN`, `Security Clearance`, `SAP`, or `Kubernetes` through any LLM field cannot make it into the artifact without source evidence or a recorded user acceptance.

#### P1 — Company-level non-technical people searches are assigned engineering context

`people/context.py::_build_roles_context` recognizes only a small product/data/marketing subset and otherwise defaults to `engineering`. It does not classify roles through the canonical occupation taxonomy. As a result, `Registered Nurse`, `Financial Analyst`, `Teacher`, `Attorney`, and most other category titles carry the wrong department and no occupation keys.

Impact: manager/peer seeds, function gating, The Org team selection, and ranking can all use the wrong professional context. Some correct candidates can be rejected as an occupation conflict while engineers are favored.

Fix:

- classify every role through `classify_title` and derive department, peer titles, manager titles, recruiter titles, and function group from the canonical occupation object;
- support multi-occupation role lists explicitly rather than guessing one department;
- use a neutral/unknown context when classification confidence is low; never default an explicit non-empty role to engineering;
- add company-level evals for all 23 categories.

Acceptance criteria: every canonical occupation's representative roles produce its canonical department and title seeds; unknown roles produce neutral context.

#### J1 — Occupation searches persist off-category results without a relevance gate

`jobs/search.py::search_jobs` infers occupation tags and then filters only location/remote constraints before storing. It does not require a fetched job to match the requested occupation. When title classification fails, `_occupation_hint` becomes the tag, allowing broad or query-ignoring sources to label unrelated generic titles as the requested category.

Impact: irrelevant jobs enter the global feed, distort counts and scores, consume storage and downstream processing, and may send the wrong job context into people and resume features. The daily re-tag task can remove the bad tag later but does not remove the irrelevant row.

Fix:

- produce an occupation relevance object with `keys`, `confidence`, `evidence`, and `source`;
- before persistence, require a high-confidence title match, a trusted source category, or a description-supported match for occupation-targeted discovery;
- quarantine low-confidence results for later enrichment instead of query-hint tagging them as facts;
- retain query hints as provenance, not canonical tags;
- track accepted, rejected, and unclassified counts per source and occupation.

Acceptance criteria: an engineering job returned during a marketing query is neither tagged marketing nor stored in that targeted run unless independent content evidence supports marketing.

### High

#### R2 — Rewrite normalization can downgrade inferred claims into ungated edits

`resume_tailor.py::_infer_change_type` labels rewrites with one or two new content words as `keyword`; only three or more new words become `inferred_claim`. This contradicts the prompt's strict rule that any new capability, scope, tool, or term must be gated. `_normalize_bullet_rewrites` also trusts an LLM-provided `requires_user_confirm=false` even when `change_type` is `inferred_claim`.

Fix: use deterministic phrase-level source entailment, force `requires_user_confirm=true` for every inferred claim, and treat uncertainty as gated. Validate that the original bullet exists at the declared section/index.

#### R3 — Global rewrite quotas incentivize hallucination and waste LLM calls

`_coverage_deficits` requires at least five inferred claims, at least three keyword rewrites, and two rewrites per top entry regardless of resume size or occupation. `tailor_resume` can retry three additional times to satisfy this quota. This contradicts the prompt's “do not manufacture inferred claims to hit a quota” rule.

Impact: sparse or already-strong resumes are pushed toward unnecessary claims; non-technical resumes receive a software-oriented rewrite volume; generation can require four tailoring calls plus a planning call.

Fix: replace output quotas with evidence-driven ceilings. A valid result may contain zero inferred claims. Set budgets by source bullet count, gap severity, occupation, and expected incremental benefit. Retry only on invalid schema or failed safety validation.

#### R4 — Artifact layout and labels remain technical and one-size-fits-all

The renderer always uses Education → Experience → Projects → “Technical Skills” → Certificates. It can show projects for every occupation, caps experience at four entries, and uses the same section strategy for a nurse, lawyer, marketer, teacher, accountant, and engineer. The plan has only `frontend_fullstack` and `general` families; its prompt and emphasis constants are heavily frontend-oriented.

Fix: introduce occupation-aware templates and section policies. Examples: licenses/clinical experience first for healthcare; credentials and deal/case experience for legal; campaigns/portfolio for marketing and creative roles; publications/teaching for education; certifications and controls for finance/security. Rename the section to “Skills” or an occupation-appropriate label outside technical profiles.

#### R5 — Resume reuse is effectively technical-only and its family gate is too coarse

`score_resume_content_against_job` relies on `extract_jd_must_surface`, whose vocabulary is technology/methodology oriented. Most non-technical jobs produce no terms and therefore no reuse candidate. At the same time, `_job_family` groups all non-frontend roles as `general`, which is too broad to be a safe semantic family boundary.

Fix: reuse only within canonical occupation/family plus seniority compatibility, score supported requirement coverage using the same domain-aware extractor as the quality gate, and require no critical target requirement regressions.

#### P2 — Final peer ordering is hardcoded for software titles

`people/ranking.py::_peer_person_title_alignment_rank` assigns the best rank to software/frontend/backend titles and the worst rank to nursing, finance, marketing, legal, education, and most other titles. `people/buckets.py::_finalize_bucketed` applies this after earlier contextual ranking and does not receive `JobContext`, so it can undo category-aware ordering.

Fix: pass context into finalization and calculate title alignment against canonical peer seeds for the requested occupations. Use neutral ordering when context is unknown.

#### P3 — Known-people cache can short-circuit live search before candidates pass quality gates

`_search_candidates` returns early when enough cached rows have token-matching titles. Current employment, company confidence, bucket validity, occupation conflict, and final usefulness are checked later. If cached rows are then rejected, the bucket can be empty without trying external providers.

Fix: validate cached rows with the same preflight gates before deciding the cache satisfies `min_results`; if fewer than the requested number survive `_prepare_candidates`, continue the waterfall from the failed bucket only.

#### P4 — Snapshots ignore requested result depth and negative feedback

`snapshot_serve_decision` only checks age and non-empty total. A fresh one-result prewarm snapshot can satisfy a later request for ten results. Negative contact feedback expires the known-person row but does not invalidate or filter existing per-job snapshots, so a rejected contact can reappear for up to 14 days.

Fix: include requested bucket counts, search depth, occupation/context version, taxonomy version, and feedback tombstones in snapshot validity. Delete or rewrite affected snapshots on negative feedback.

#### P5 — People quality evaluation is too small and too indirect

The current labeled suite has four fixtures: engineering, a fictional startup, nursing, and an ambiguous company. It asserts only top recruiter and hiring-manager ordering, does not score peers, and uses already-labeled confidence fields. There is no measured retrieval recall, current-employment precision, wrong-person rate, bucket precision, source contribution, or confidence calibration.

Fix: build a frozen, legally sourced evaluation corpus across all 23 occupations, company sizes, ambiguous names, geographies, remote roles, and early-career/senior levels. Evaluate retrieval and verification end to end with precision@k, recall@k, MRR/nDCG, bucket accuracy, current-company precision, diversity, latency, cost, and abstention quality.

#### J2 — Generic non-empty titles never use description evidence

`classify_title` consults the description only when the title is blank. Real titles such as `Associate`, `Coordinator`, `Specialist`, `Consultant`, `Analyst II`, and `Manager` therefore cannot be disambiguated by a clear description.

Fix: define generic-title detection, then classify title + responsibilities + trusted source taxonomy with separate weights. Do not scan the entire boilerplate description without section weighting.

#### J3 — Match scoring measures resume overlap more than job fit and is software-shaped

The 35-point skills axis divides matched resume skills by all resume skills rather than required job skills. A broad, accomplished resume can score lower than a sparse resume even when it covers more requirements. Skill synonyms and title synonyms are overwhelmingly technical. Education receives baseline points merely for existing, while category-specific credentials, authorization, language, portfolio, shift, travel, schedule, and licensure constraints are not modeled.

Fix: parse required vs preferred constraints from the job, map evidence from the resume, score coverage and critical gaps, and use occupation-specific axes. Keep one calibrated 0–100 display score only after validating it against user outcomes; otherwise show dimension scores and explicit hard constraints.

#### J4 — Invalid occupation keys silently launch software discovery

`discover_queries_for_occupations` treats both “no occupations selected” and “all supplied keys invalid” as the same state and falls back to software engineering.

Fix: distinguish `None/[]` from invalid non-empty input. Reject invalid API values, alert on stale stored taxonomy keys, and migrate removed keys explicitly.

#### J5 — Aggregator jobs bypass the people prewarm path

`_maybe_prewarm_people` is called by `_store_raw_jobs`, used for board payloads, but not by `search_jobs`, which stores JSearch, Adzuna, The Muse, Dice, Remotive, Jobicy, Simplify, and Job Bank results. Those jobs default to `people_prewarm_status="ready"`, contradicting the stated “every newly stored discovery job is warmed” behavior.

Fix: centralize persistence finalization so all newly inserted jobs pass through the same prewarm/auto-prospect policy exactly once.

#### J6 — Discovery “new job” counts include refreshed existing jobs

`search_jobs` correctly returns both new and existing matches, but `discover_jobs` sums `len(stored)` into `total_new`. API analytics and logs therefore report refreshed matches as newly discovered.

Fix: return a typed result with `new`, `refreshed`, `rejected`, and `duplicate` counts, or sum `_is_new_job` only.

#### J7 — On-demand non-technical discovery underuses the broad ATS registry

The direct ATS registry now contains employers and roles across marketing, finance, consumer, healthcare-adjacent, media, legal tech, and other functions, but on-demand curated ATS discovery still runs only for engineering-relevant occupations. Non-technical users depend on the hourly global crawl plus broad aggregators and Workday verticals.

Fix: fetch the registry independently of occupation, classify/filter results before user persistence, and use observed per-occupation yield to decide board/source routing. Do not label the registry “all tech companies” when its contents have outgrown that assumption.

### Medium

#### J8 — Source health is availability-only, not usefulness-aware

Source runs track raw/new/existing/duplicate/skipped/error counts, but not occupation relevance, metadata completeness, stale/closed rate, direct-apply success, or downstream save/apply rate. A source that returns 500 irrelevant jobs is considered healthy.

Improve with per-source/per-occupation precision, accepted yield, missing-field rates, age distribution, duplicate contribution, direct-link validity, cost, latency, and user outcome metrics.

#### J9 — Static source routing and fixed limits cannot adapt to category yield

The same per-source limit and a two-location fanout are applied broadly. Sources with high marketing yield and low nursing yield, or vice versa, do not learn different budgets. A user with more than two target locations is silently truncated.

Improve with budget allocation based on recent accepted yield, explicit location priorities, per-country sources, and exploration quotas for new sources.

#### J10 — Cross-source near-duplicate handling is limited

Identity prefers source + external ID and canonical URL, then an exact normalized company/title/location fingerprint. The same role syndicated across sources, title punctuation variants, company aliases, or multi-location variants can remain duplicated.

Improve with a cross-source cluster key using canonical employer identity, normalized role family/title, posting text similarity, location set, and publication window. Preserve source provenance on the winning record.

#### J11 — Hard constraints and negative preferences are missing from ranking

The feed filters salary floor, country, radius, remote, level, type, startup, occupation, and text, but ranking does not model visa/work authorization, schedule/shift, contract duration, travel, clearance, language, license, excluded employers, blocked keywords, or salary currency/period confidence.

Improve by separating hard eligibility filters from soft preferences and explaining each exclusion/match.

#### J12 — Occupation tags lack confidence and provenance

Tags are plain strings. Source category, title classifier, description classifier, and query hint are collapsed into the same `occupation:<key>` value. Downstream people and resume systems cannot tell strong classification from a fallback.

Improve with structured classification metadata and versioned classifier outputs while keeping tags as a query index.

#### P6 — Early-career company search is software-specific

When company-level context is early career, the extra peer search always uses `SWE Intern`, `Software Engineer`, `Production Engineer`, and `New Grad`.

Improve by generating internship/new-grad variants from occupation-specific peer seeds.

#### P7 — Feedback semantics are collapsed in the UI

The API supports `wrong_person`, `not_at_company`, and `helpful`, but the People page exposes only “Not the right person?” and sends `wrong_person`. The system loses the distinction between identity error, stale employment, wrong function, wrong seniority, duplicate, and low usefulness.

Improve with compact reason choices and use them to tune the corresponding retrieval, verification, or ranking component.

#### P8 — Result diversity is not explicitly optimized

Ranking can return several people with nearly identical titles, offices, sources, or org level. For networking, a useful set often includes one req owner, one functional leader, one close peer, one local contact, and one warm path rather than five near-duplicates.

Improve with constrained re-ranking for source, seniority, team, geography, and warm-path diversity after minimum trust thresholds are met.

#### P9 — Search metrics count results but do not measure correctness or action

Analytics records bucket counts and warm paths, but not which result was opened, verified, rejected, drafted to, emailed, replied to, or ultimately associated with an interview. “Found three people” is not equivalent to “found the right three people.”

Improve with privacy-conscious result impression/click/save/feedback/outreach/reply funnels keyed to rank, source family, occupation, and confidence tier.

#### P10 — Function groups are intentionally coarse but hide important adjacent-function errors

Engineering, product, data, and security share one technical group; sales, marketing, and customer success share GTM. This prevents obvious cross-group mistakes but still allows a Product Manager for a Security Engineer or a Marketer for an Account Executive.

Improve with hierarchical function distance: exact occupation, adjacent occupation, same group, cross-group. Use it as a rank and an abstention threshold rather than only a binary reject.

#### R6 — “Parseability” does not test the rendered PDF

The parseability axis detects LaTeX section markers, contact text, links, and metrics. It does not compile the final PDF, extract its text with an independent parser, check reading order, detect a second page, or compare extracted fields to the intended artifact.

Improve with render-time QA: compile, assert one page when required, extract with at least two parsers, compare section order and text retention, and flag glyph/layout loss.

#### R7 — The general-professional quality rubric is too generic for 20+ categories

All non-engineering roles share outcomes, role experience, capabilities, and supporting evidence. That misses clinical credentials, legal admissions, accounting controls, teaching evidence, portfolios, sales quota attainment, supply-chain scale, public-sector requirements, and other category-specific proof.

Improve with shared axes plus occupation-specific evidence modules and explicit “not applicable” handling so candidates are not penalized for irrelevant evidence types.

#### R8 — Job-term extraction is shallow and not requirement-structured

The evaluator uses up to 14 explicit hints/title/body tokens. It does not reliably distinguish mandatory qualifications, preferred qualifications, responsibilities, benefits boilerplate, or duplicated scraper text. Single-word term matching can overvalue generic nouns.

Improve with a structured requirement schema: normalized requirement, mandatory/preferred, evidence type, criticality, source span, and confidence. Score supported evidence against that schema.

#### R9 — Accepted inferred rewrites may drop source metrics

`_should_use_rewrite` requires metric preservation for keyword/reframe edits but exempts inferred claims. This conflicts with the prompt's instruction to preserve every concrete metric and can make an accepted rewrite weaker.

Improve by preserving all source metrics by default for every rewrite; allow removal only through an explicit user-visible decision.

#### R10 — Existing tailoring is regenerated instead of consistently reused

Artifact generation calls `_load_or_generate_tailoring(..., prefer_existing=False)`, so a user can review one tailoring result and then generate an artifact from a newly generated, potentially different result. This also adds cost and latency.

Improve by versioning tailoring against resume hash + job-description hash + prompt/rubric version. Reuse the reviewed version unless the user explicitly regenerates.

#### R11 — The quality score is not calibrated to hiring outcomes

Labels such as `strong` and `competitive` are fixed score bands. Tests establish determinism and bounds, not that an 85 corresponds to better recruiter outcomes than a 70 across occupations.

Improve by calling it an internal readiness score until calibrated, then validate monotonic relationships with user review acceptance, applications, screens, and interviews while controlling for occupation and experience level.

#### R12 — No end-to-end cross-category resume benchmark exists

Tests cover several non-technical term regressions, but there is no gold set of source resume + job + allowed claims + preferred sections + critical requirements + expected artifact checks across the taxonomy.

Improve with representative fixtures for every occupation and seniority level, including adversarial regulated-role cases and visual PDF snapshots.

## Cross-feature architectural improvements

1. **One versioned occupation inference service.** Return occupation, adjacent occupations, confidence, evidence spans, seniority, and function group. Use the same object in job filtering, people context, resume profiles, analytics, and UI explanations.
2. **One requirement/evidence model.** Parse a job into mandatory/preferred requirements and map each to resume evidence. Use it for job score, resume tailoring, quality evaluation, and explanations.
3. **One truthfulness ledger.** Every generated resume phrase should point to source evidence or explicit user acceptance. This should cover bullets, skills, summaries, and credentials.
4. **One evaluation harness.** Run frozen cross-category datasets through retrieval, ranking, and rendering. Store metrics by occupation, geography, company size, seniority, source, and model/prompt version.
5. **One feedback loop.** Distinguish retrieval errors, identity errors, stale-employment errors, function errors, and low-usefulness results. Feed the right signal back to the right subsystem.

## Detailed implementation plan

### Phase 0 — Correctness hotfixes (1–3 days)

1. Gate `skills_to_add` and `keywords_to_add`; do not render unsupported terms.
2. Force every inferred claim to require confirmation and replace the “three new words” heuristic.
3. Remove minimum inferred/keyword quotas and cap rewrites by available evidence.
4. Route company-level roles through the canonical occupation taxonomy.
5. Make final peer ranking context-aware and remove software-specific ordering.
6. Add an occupation relevance decision before targeted job persistence.
7. Make invalid non-empty occupation input fail closed.
8. Make snapshot validity respect requested result counts and invalidate negative-feedback contacts.
9. Centralize new-job finalization so aggregator jobs receive prewarm consistently.
10. Correct new/refreshed discovery counts.

Release gate: dedicated regression tests for every critical/high correctness item, including nursing, finance, marketing, legal, education, sales, and software examples.

### Phase 1 — Evaluation foundation (1–2 weeks)

1. Create a licensed/public or synthetic-but-reviewed dataset covering all 23 occupations.
2. For jobs, label relevance, occupation(s), seniority, location eligibility, metadata completeness, duplicates, and closure.
3. For people, label identity, current company, bucket, function distance, team relevance, geography, and useful/not useful.
4. For resumes, label source-supported claims, critical requirements, allowed rewrites, expected section order, and prohibited inferred credentials.
5. Add metrics dashboards and regression thresholds:
   - jobs: precision@50, recall proxy/source yield, unclassified rate, duplicate rate, metadata completeness, stale rate;
   - people: precision@k, recall@k, MRR/nDCG, current-company precision, bucket accuracy, abstention, diversity, p50/p95 latency and cost;
   - resumes: unsupported-claim rate (must be zero), supported requirement coverage, critical-gap recall, one-page/render pass rate, text-extraction fidelity, user rewrite acceptance.

Release gate: no category ships a ranking or prompt change without aggregate and per-category regression results.

### Phase 2 — Job discovery quality (2–4 weeks)

1. Implement structured occupation inference with generic-title description fallback.
2. Add pre-persistence relevance filtering/quarantine.
3. Replace static source budgets with per-category observed-yield budgets.
4. Run direct ATS discovery for all occupations and filter before persistence.
5. Build structured mandatory/preferred constraint extraction and category-aware match scoring.
6. Add cross-source clustering and employer identity normalization.
7. Add negative preferences and hard eligibility filters.
8. Surface “why this job,” classification confidence, missing critical constraints, and source freshness in the UI.

Success target: materially higher precision@50 in every occupation without reducing accepted unique-job yield; zero software fallback from invalid category keys.

### Phase 3 — People quality and usefulness (2–4 weeks)

1. Unify job-aware and company-level context construction.
2. Validate cache hits before short-circuiting and continue only failed buckets.
3. Replace binary function conflict with hierarchical function distance.
4. Make final ranking contextual and diversity-aware.
5. Version snapshots by context/taxonomy/search depth and apply feedback tombstones.
6. Expand retrieval for occupation-specific public evidence: professional directories, publications, associations, portfolios, speaker pages, faculty/provider/attorney directories, and licensed data where appropriate.
7. Add reason-specific feedback and connect ranking to downstream outreach/reply outcomes.
8. Calibrate confidence labels so `verified`, `strong_signal`, and `weak_signal` correspond to measured precision.

Success target: high current-company precision and bucket precision in every category, with an explicit abstention when trustworthy results are unavailable.

### Phase 4 — Resume tailoring by occupation (2–4 weeks)

1. Introduce the truthfulness ledger and evidence IDs.
2. Build a structured job-requirement extractor shared with match scoring.
3. Add occupation-specific section plans and quality modules.
4. Make rewrite generation evidence-first: select source evidence, choose an allowed transformation, then generate language.
5. Add deterministic entailment and metric-preservation validation after generation.
6. Render and verify the PDF before marking it ready: page count, text extraction, reading order, missing glyphs, and section integrity.
7. Version/cache tailoring by inputs and ensure the artifact uses the exact reviewed tailoring version.
8. Rebuild reuse on occupation/seniority compatibility and supported requirement coverage.

Success target: zero unsupported claims, 100% render/parse checks, and improved supported critical-requirement coverage over the source resume without evidence loss.

### Phase 5 — Continuous learning and product UX (ongoing)

1. Show users concise explanations and uncertainty rather than opaque scores.
2. Track job saves/applies, people feedback/outreach/replies, and resume accept/reject/download outcomes by category.
3. Run offline replay before online experiments.
4. Use guarded per-category experiments; never optimize raw result volume at the expense of trust.
5. Review thin categories quarterly and add sources only where measurement shows recall—not precision—is the limiting factor.

## Recommended delivery order

The safest order is R1 → R2/R3 → P1/P2 → J1/J2/J4 → snapshot/cache fixes → evaluation corpus → scoring/routing/template upgrades. This sequence first prevents incorrect claims and visibly wrong category results, then creates the measurement foundation needed for larger ranking changes.

## Definition of done

This improvement program is complete only when:

- all 23 occupations have representative end-to-end fixtures for jobs, people, and resumes;
- job results meet per-category relevance and metadata thresholds;
- people results meet measured identity/current-company/bucket thresholds or clearly abstain;
- every rendered resume phrase is source-supported or explicitly accepted;
- every artifact passes render, page-count, and independent text-extraction checks;
- source/ranking/prompt changes are versioned and evaluated before release;
- negative feedback immediately prevents the same bad job/contact/claim from resurfacing;
- product analytics measure downstream usefulness, not only result counts.
