# Resume Quality Gate — Implementation Plan

Last updated: 2026-06-23

## Objective

Use the transparent scoring ideas in HackerRank's MIT-licensed
`interviewstreet/hiring-agent` project to improve every generated NexusReach
resume. The feature must grade the final artifact, preserve job-specific ATS
matching, expose the evidence behind every score, and never present a generic
screening simulation as the actual reason an employer would accept or reject a
candidate.

The HackerRank rubric is a useful early-career software rubric, not a universal
ATS. NexusReach will therefore implement a versioned, occupation-aware quality
gate rather than applying HackerRank's weights to every user.

## Product behavior

1. Generate the tailored resume from the user's existing, user-scoped profile
   and the selected job.
2. Score the rendered artifact on three independent axes:
   - `job_fit`: required job terms supported and surfaced in the resume body.
   - `evidence_quality`: occupation-aware proof of work, outcomes, projects,
     production experience, and technical or professional capabilities.
   - `parseability`: deterministic checks that the generated artifact contains
     recognizable contact, experience, education, skills, and linked evidence.
3. Produce a bounded overall score and a transparent category breakdown. Each
   category includes its score, maximum, evidence, and improvement guidance.
4. Run one bounded improvement cycle during generation. The initial evaluation
   supplies priority guidance to the artifact planner, which may only reorder or
   select supported content. It may not invent facts. The final artifact is then
   evaluated and persisted.
5. Re-evaluate whenever rewrite decisions regenerate the artifact. Reused
   artifacts are evaluated against the new target job rather than inheriting a
   stale score.
6. Display the final score, profile, rubric version, category evidence,
   strengths, improvements, and a clear "screening simulation" disclaimer in
   the resume review UI.

## Scoring profiles

### `early_career_technical_v1`

Used for technical occupations when the resume appears early-career. It retains
the public HackerRank category balance:

- Open-source contribution: 35
- Projects: 30
- Production experience: 25
- Technical skills: 10

The implementation is deliberately conservative: personal repositories do not
count as third-party open-source contributions, and unsupported GitHub claims
receive no credit.

### `experienced_technical_v1`

Used for technical occupations with substantial production history. Production
impact has the highest weight; open source remains useful but is not required.

### `general_professional_v1`

Used for non-technical and unknown occupations. It scores demonstrated outcomes,
role-relevant experience, professional capabilities, and supporting evidence.
It does not penalize candidates for lacking GitHub or open-source work.

Profile selection uses the job's canonical `occupation:*` tags first, then title
classification. Seniority and the amount of dated work history distinguish the
two technical profiles. Selection is deterministic and stored with the result.

## Truthfulness and fairness invariants

- Score only the final content plus facts already present in the user's parsed
  resume. A score must never cause new metrics, employers, tools, credentials,
  links, or project claims to be generated.
- Pending inferred claims are not treated as verified evidence. Explicitly
  rejected inferred claims cannot contribute.
- Do not score names, demographic data, school prestige, grades, or geography.
- Missing evidence lowers only the applicable evidence category; it does not
  become a claim that an employer will reject the candidate.
- Every persisted result identifies its profile, rubric version, evaluation
  mode, source attribution, and evaluation timestamp.
- Evaluation failure is fail-soft: artifact generation succeeds, stores an
  unavailable evaluation with a reason, and remains reviewable.

## Backend design

### Evaluation module

Add `backend/app/services/resume_artifact/quality.py` containing:

- immutable rubric/profile definitions;
- deterministic profile selection;
- final-LaTeX plain-text extraction;
- supported-evidence collection from parsed resume data;
- category scorers with bounded outputs;
- job-fit and parseability axes;
- normalized overall score computation;
- structured strengths and improvements;
- validation that all scores remain within their declared bounds;
- planner guidance derived only from supported source evidence.

The evaluator remains deterministic so generation does not gain a second
provider failure mode or non-repeatable score. Existing LLM tailoring continues
to propose wording, while the quality gate decides what supported evidence must
be preserved and how the final result grades.

### Generation integration

Update the artifact planner to accept quality guidance and prioritize:

- measurable impact;
- production scope;
- linked, non-tutorial projects;
- explicit third-party open-source contributions;
- concrete technical/professional capabilities required by the job.

Evaluate the final LaTeX in `generate_resume_artifact_for_job`. Store the result
on the artifact. Recompute after decision-based regeneration and cross-job reuse.

### Persistence

Add nullable `quality_evaluation JSONB` and `quality_score FLOAT` fields to
`resume_artifacts`. Nullable fields preserve existing rows and make rollout
backward compatible. Add Alembic revision `054`.

### API

Extend `ResumeArtifactResponse` with:

- `quality_score`
- `quality_evaluation`

The nested response has typed axes/categories and explicit metadata. Existing
clients remain compatible because the new fields are nullable/defaulted.

## Frontend design

Add a quality panel above rewrite review containing:

- overall quality score and readiness label;
- separate job-fit, evidence-quality, and parseability scores;
- selected occupation profile and rubric version;
- expandable category cards with evidence and improvements;
- strengths and prioritized next improvements;
- a statement that the score is an explainable screening simulation, not an
  employer decision or guaranteed outcome.

The panel renders even when no rewrite proposals exist, so reused and legacy
artifacts can still expose their evaluation state.

## Verification matrix

| Requirement | Direct proof |
| --- | --- |
| HackerRank-inspired early-career weights | Unit test asserts exact 35/30/25/10 maxima |
| Occupation-aware behavior | Unit tests cover early-career technical, experienced technical, and non-technical jobs |
| Bounded deterministic scores | Unit/property-style parametrized tests assert repeatability and all bounds |
| Truthfulness | Tests prove absent claims/links receive no credit and pending inferred claims cannot add evidence |
| Final artifact graded | Service test asserts persisted evaluation is derived after LaTeX rendering |
| Regeneration/reuse freshness | Service tests assert decisions and reuse recompute for the target job |
| API contract | Router tests assert complete nested evaluation response |
| UI transparency | Testing Library tests assert scores, evidence, improvements, profile, and disclaimer |
| Database rollout | Alembic head/upgrade validation and model/migration inspection |
| Code quality | Backend Ruff, backend tests, frontend ESLint, TypeScript, Vitest, and production build |
| Actual artifact parseability | Compile a representative artifact to PDF, extract its text, and verify expected sections/links |

## Completion criteria

The work is complete only when every row in the verification matrix has direct
passing evidence, the full relevant backend/frontend suites pass, the migration
chain has one head, a representative PDF renders and parses, and a final audit
finds no requirement represented only by intent or indirect coverage.

## Implementation and verification record

Completed 2026-06-23:

- [x] Versioned deterministic evaluator with all three occupation-aware profiles.
- [x] Exact early-career technical maxima: 35/30/25/10.
- [x] Source-evaluation guidance injected into artifact planning.
- [x] Final rendered LaTeX evaluated and persisted on generation/regeneration.
- [x] Cross-job reuse recomputes the target evaluation and automatic reuse uses
  both the 80% job-body threshold and 70% quality threshold.
- [x] Typed API response and transparent review UI.
- [x] Alembic revision `054_add_resume_quality_evaluation` is the single head;
  offline PostgreSQL upgrade and downgrade SQL both render successfully.
- [x] `ruff check app tests conftest.py`: passed.
- [x] Full backend suite: 1,426 passed.
- [x] Frontend ESLint and TypeScript project build: passed.
- [x] Full frontend suite: 22 files / 202 tests passed.
- [x] Vite production build: passed.
- [x] 500 seeded randomized sparse/malformed evaluations completed with valid
  bounded results.
- [x] Representative artifact compiled with `pdflatex` to a 117,241-byte,
  one-page Letter PDF; `pdftotext` recovered contact, education, experience,
  projects, skills, certificates, metrics, and links.
- [x] Poppler PNG inspection found no clipping, overlap, broken glyphs, broken
  links, or unreadable sections.

### Live-job validation — 1Password

Completed 2026-06-23 against the live Ashby posting
`b6b8c8ed-ff1c-4bc2-9dbe-5122207ea3a2` (Developer Intern, Service
Development — Fall 2026):

- [x] Retrieved and evaluated the actual posting requirements, not a synthetic
  job fixture.
- [x] Baseline score: 58.3; tailored score: 60.8; truthful ceiling from the
  currently verified resume evidence: 60.8.
- [x] Surfaced 7/18 supported requirements without adding unsupported claims.
- [x] Explicitly withheld Go, gRPC, logging, tracing, metrics, configuration,
  developer experience, platform engineering, shared libraries, SDKs, and
  inner-source because the source resume did not verify them.
- [x] Fixed false open-source credit, keyword-stuffing credit, short-token
  substring matching, and job-boilerplate priority defects discovered by the
  live run; each has regression coverage.
- [x] Resume/API feature verification: Ruff passed and 75 tests passed.
- [x] Targeted frontend verification: 9 tests passed and TypeScript build
  passed.
- [x] Generated a one-page, unencrypted Letter PDF (117,078 bytes), recovered
  all expected content with `pdftotext`, and visually inspected the rendered
  page for clipping, overlap, and glyph errors.
- [x] Current full backend suite: 1,441 passed. The transient Google CSE mock
  failure was resolved by the separately committed search-provider work before
  this feature was staged.
