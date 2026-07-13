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
| P3 cache early return | Partial | Cache candidates receive company/employment/bucket preflight. Prove and enforce bucket-only waterfall continuation after every post-gate underfill. |
| P4 snapshot depth/feedback | Done | Snapshot depth is versioned and negative feedback immediately rewrites all durable snapshots/counts. |
| P5 people evaluation depth | Partial | A 23-occupation synthetic regression exists. Add licensed end-to-end retrieval/verification labels and precision/recall/MRR/calibration/cost metrics. |
| J2 generic title evidence | Done | Generic titles use a bounded description lead; specific unmatched titles do not inherit boilerplate. |
| J3 match scoring | Partial | Match scoring now consumes the shared typed requirement model and explicit hard-eligibility decision. Outcome calibration still requires production labels over time. |
| J4 invalid occupation fallback | Done | Invalid non-empty keys fail closed and never launch software discovery. |
| J5 aggregator prewarm | Done | Centralized new-job finalization applies prewarm/auto-prospect exactly once. |
| J6 new/refreshed counts | Done | Discovery totals count only transiently marked inserts. |
| J7 nontechnical ATS routing | Done | Direct ATS registry runs for every targeted occupation and filters each posting by independent evidence before storage. |
| J8 usefulness-aware health | Partial | Relevance rejection and metadata yield are recorded and drive bounded budgets. Add stale/closed/direct-link/cost/latency/downstream outcome reporting. |
| J9 adaptive source routing | Partial | Recent usefulness drives per-source budgets with exploration floors; all explicit locations are searched. Add user-visible location priority and country-aware budget policies. |
| J10 cross-source duplicates | Partial | Legal suffix, punctuation, seniority, and remote variants cluster; all source provenance is retained. Add description similarity, employer identity families, location sets, and publication windows. |
| J11 hard/negative preferences | Partial | Persisted authorization, sponsorship, schedule, travel, language, license, clearance, employer and keyword constraints now filter confirmed failures before persistence and explain unknowns. Salary currency/period confidence and contract-duration preferences remain. |
| J12 classification provenance | Done | Versioned keys, source, confidence, evidence, and query provenance are persisted in metadata. |
| P6 software early-career search | Done | Early-career company search derives variants from occupation peer titles. |
| P7 feedback semantics | Done | UI/API distinguish identity, employment, function, seniority, duplicate, usefulness, and helpful signals; negatives evict snapshots. |
| P8 result diversity | Done | Greedy diversity re-ranking operates only within equal trust/match tiers. |
| P9 outcome metrics | Partial | Privacy-safe impression and action telemetry now carries rank, source, bucket, trust, match quality, warm-path and corroboration signals; server feedback includes reason/source/type/confidence. Cross-surface send/reply/interview attribution remains. |
| P10 coarse function groups | Done | Ranking distinguishes exact, adjacent, same-group, cross-group, and unknown; cross-group remains the abstention gate. |
| R6 rendered PDF parseability | Done | Every generated/reused artifact is compiled, constrained to one page, extracted by pypdf and Poppler, and checked for text/order/metric/glyph retention before persistence. |
| R7 occupation quality rubrics | Done | All canonical occupations map to weighted evidence profiles; irrelevant evidence modules are explicitly not applicable rather than scored as failures. |
| R8 structured requirements | Done | Shared mandatory/preferred/responsibility requirements carry evidence type, criticality, source span, confidence, value, and schema version. |
| R9 inferred rewrite metric loss | Done | Every rewrite type must preserve all source metric tokens. |
| R10 reviewed tailoring reuse | Done | Tailoring is versioned by deterministic resume/job/prompt/rubric input hash and generation reuses only the exact reviewed version unless explicitly regenerated. |
| R11 score calibration | Partial | Product labels now say Internal quality/readiness and avoid employer-outcome claims. Outcome monotonicity still requires production labels over time. |
| R12 resume benchmark | Partial | All 23 occupations have source/job/resume fixtures; regulated-claim adversarial tests and real one-/two-page PDF regressions are included. Broader seniority × occupation rendered snapshots remain. |

## Verification checkpoint

Latest continuation checks:

- backend Ruff: clean
- full backend regression: 1,627 passed
- full frontend regression: 214 passed
- frontend production build and ESLint: passed
- Alembic migration graph: one head (`059_version_tailored_resumes`)
- Docker: compose SearXNG healthy over HTTP; renderer image builds with TeX, Poppler, and the PDF verifier
