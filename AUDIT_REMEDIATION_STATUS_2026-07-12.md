# NexusReach Audit Remediation Ledger

Updated: 2026-07-12

This is the completion ledger for `FEATURE_AUDIT_2026-07-12.md`. “Done” means
the finding's acceptance behavior is implemented and covered by a focused
regression. “Partial” means material risk was reduced but at least one stated
acceptance requirement remains. The audit program is not complete while any
row is Partial or Todo.

| Finding | Status | Current evidence / remaining work |
|---|---|---|
| R1 unsupported resume terms | Done | A persisted truthfulness ledger covers source evidence, generated terms, rewrites, explicit acceptance, and regulated claims; generation and reuse fail closed before rendering or persistence. |
| P1 nontechnical people context | Done | Canonical taxonomy drives company-level context; all 23 occupations and unknown-neutral behavior are evaluated. |
| J1 targeted relevance gate | Done | Versioned evidence-bearing relevance runs before persistence; query hints cannot pass the gate. |
| R2 inferred rewrite downgrade | Done | New capabilities are deterministically gated and inferred claims always require confirmation. |
| R3 hallucination quotas | Done | Minimum inferred/keyword quotas were removed; zero inferred claims is valid. |
| R4 occupation resume layouts | Done | Canonical occupation policies control section order, labels, project/portfolio inclusion, and experience allocation, including regulated healthcare and legal layouts. |
| R5 resume reuse families | Done | Reuse requires canonical occupation compatibility, bounded seniority distance, and no missing mandatory credential, license, or clearance. |
| P2 software-only peer ordering | Done | Final peer ordering receives context and uses canonical title/function distance. |
| P3 cache early return | Done | Cache candidates receive company, employment, bucket, and occupation-conflict preflight; a post-gate underfill resumes only the affected bucket's live waterfall. |
| P4 snapshot depth/feedback | Done | Snapshot depth is versioned and negative feedback immediately rewrites all durable snapshots/counts. |
| P5 people evaluation depth | Done | A frozen synthetic-reviewed corpus covers all 23 occupations and reports precision@2, recall@2, MRR, nDCG@3, bucket/current-company accuracy, wrong-person and abstention rates, diversity, confidence calibration, latency, and cost with release gates. Live vendor retrieval remains an operational evaluation, not a deterministic CI dependency. |
| J2 generic title evidence | Done | Generic titles use a bounded description lead; specific unmatched titles do not inherit boilerplate. |
| J3 match scoring | Partial | Match scoring now consumes the shared typed requirement model and explicit hard-eligibility decision. Outcome calibration still requires production labels over time. |
| J4 invalid occupation fallback | Done | Invalid non-empty keys fail closed and never launch software discovery. |
| J5 aggregator prewarm | Done | Centralized new-job finalization applies prewarm/auto-prospect exactly once. |
| J6 new/refreshed counts | Done | Discovery totals count only transiently marked inserts. |
| J7 nontechnical ATS routing | Done | Direct ATS registry runs for every targeted occupation and filters each posting by independent evidence before storage. |
| J8 usefulness-aware health | Done | Source runs record accepted relevance, metadata yield, stale/closed rates, direct-link validity, cost, latency, and per-source visible/save/apply/interview outcomes; bounded budgets consume the quality signals. |
| J9 adaptive source routing | Done | Recent usefulness drives per-source budgets with exploration floors, explicit locations are ordered in the profile UI, and country/location priority adjusts source budgets without starving exploration. |
| J10 cross-source duplicates | Done | The cluster-v2 key uses employer identity families, normalized title and location sets, a 14-day publication window, and description minhash while retaining merged source provenance. |
| J11 hard/negative preferences | Done | Hard eligibility covers authorization, sponsorship, schedule, travel, language, license, clearance, employer/keyword exclusions, salary currency/period/provenance confidence, and minimum contract duration; unknown evidence remains explicitly unknown. |
| J12 classification provenance | Done | Versioned keys, source, confidence, evidence, and query provenance are persisted in metadata. |
| P6 software early-career search | Done | Early-career company search derives variants from occupation peer titles. |
| P7 feedback semantics | Done | UI/API distinguish identity, employment, function, seniority, duplicate, usefulness, and helpful signals; negatives evict snapshots. |
| P8 result diversity | Done | Greedy diversity re-ranking operates only within equal trust/match tiers. |
| P9 outcome metrics | Done | Privacy-safe pseudonymous job/person/message/artifact keys join impression, action, feedback, draft, send, reply, stage, resume, application, and interview outcomes without emitting raw database identifiers or person data. |
| P10 coarse function groups | Done | Ranking distinguishes exact, adjacent, same-group, cross-group, and unknown; cross-group remains the abstention gate. |
| R6 rendered PDF parseability | Done | Every generated/reused artifact is compiled, constrained to one page, extracted by pypdf and Poppler, and checked for text/order/metric/glyph retention before persistence. |
| R7 occupation quality rubrics | Done | All canonical occupations map to weighted evidence profiles; irrelevant evidence modules are explicitly not applicable rather than scored as failures. |
| R8 structured requirements | Done | Shared mandatory/preferred/responsibility requirements carry evidence type, criticality, source span, confidence, value, and schema version. |
| R9 inferred rewrite metric loss | Done | Every rewrite type must preserve all source metric tokens. |
| R10 reviewed tailoring reuse | Done | Tailoring is versioned by deterministic resume/job/prompt/rubric input hash and generation reuses only the exact reviewed version unless explicitly regenerated. |
| R11 score calibration | Partial | Product labels say Internal quality/readiness and avoid employer-outcome claims. A fail-closed cohort report now measures review/application/interview monotonicity by occupation and experience level, but real cohorts must accrue before any score can be called empirically calibrated. |
| R12 resume benchmark | Done | A 69-case matrix renders every one of the 23 occupations at entry, mid, and senior levels through the production LaTeX/PDF path, asserts one page, two-parser agreement, section policy, and bounded raster dimensions/ink density, alongside regulated-claim adversarial tests. |

## Verification checkpoint

Latest continuation checks:

- backend Ruff: clean
- full backend regression: 1,707 passed
- full frontend regression: 214 passed
- frontend production build and ESLint: passed
- Alembic migration graph: one head (`059_version_tailored_resumes`)
- Docker: compose SearXNG healthy over HTTP; the non-root renderer image contains TeX and Poppler and imports the production PDF verifier
