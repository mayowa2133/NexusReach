# NexusReach — Competitive Roadmap

Last updated: 2026-04-21 (cadence engine + interview prep slice 2 shipped; CI fixes)
Reference comparison: `career-ops` (`santifer/career-ops`)

This file is the living roadmap for product improvements identified by comparing NexusReach against strong adjacent products. It is meant to survive agent handoffs and be updated as work progresses.

## How to use this file

- Update `Last updated` whenever you change statuses, priorities, scope, or notes.
- Keep status values to one of:
  - `not_started`
  - `planned`
  - `in_progress`
  - `blocked`
  - `shipped`
  - `deferred`
- When a workstream moves, update:
  - status
  - owner
  - progress notes
  - next checkpoint
- If implementation starts, link the main files, PR, or branch in `Implementation notes`.
- If scope changes, append a short dated note rather than rewriting history silently.

## Why this roadmap exists

The comparison with Career-Ops showed that NexusReach is already stronger in:
- people discovery and same-company targeting
- warm-path intelligence from imported LinkedIn graph data
- company verification and email-safety guardrails
- structured CRM, staged drafts, and app-backed workflow

The biggest product gaps are:
- lack of a tight single-job execution loop
- no first-class story bank / proof-point memory
- no interview-intelligence workspace
- no strong follow-up cadence engine
- resume tailoring stops at suggestions instead of a submission-ready artifact
- limited batch-triage workflow for deciding where to spend networking effort

This roadmap turns those findings into sequenced product work.

## Current priority order

1. Job command center
2. Story bank and proof-point memory
3. Next-action and follow-up cadence engine
4. Interview-prep workspace
5. Resume artifact generation
6. Batch triage for networking ROI

## Workstreams

### 1. Job Command Center

- Status: `shipped`
- Priority: `now`
- Owner: `active thread`
- Goal:
  - Turn each saved job into a single operating page that brings together match analysis, resume help, best people, warm paths, outreach recommendations, and next steps.
- Why this matters:
  - Career-Ops feels strong because one job turns into one tight workflow.
  - NexusReach already has the underlying pieces, but they are fragmented across Jobs, People, Messages, and Tracker.
- Scope:
  - add a clear per-job action panel
  - show match analysis, resume tailoring, best contacts, warm-path contacts, and draft recommendations together
  - add a persistent `next best action` summary for that job
  - expose whether the user has already contacted someone tied to that role
- Non-goals:
  - no application auto-submit
  - no weakening of company or email safety rules
- Dependencies:
  - existing job detail view
  - people-search by `job_id`
  - match analysis
  - tailored resume suggestions
  - outreach history linkage
- Success criteria:
  - a user can open one job and understand what to do next without navigating multiple pages
  - at least one recommended person and one recommended action are shown when enough data exists
  - job-level workflow state is visible and stable across sessions
- Implementation notes:
  - likely touches:
    - `frontend/src/pages/JobDetailPage.tsx`
    - `frontend/src/hooks/useJobs.ts`
    - `frontend/src/hooks/usePeople.ts`
    - `backend/app/routers/jobs.py`
    - `backend/app/services/job_service.py`
- Progress notes:
  - 2026-04-17: Roadmap item created from Career-Ops comparison.
  - 2026-04-17: First slice shipped. Added a backend `job command center` summary endpoint and rewrote the job detail surface to show:
    - next best action
    - workflow checklist
    - job-linked activity stats
    - top saved contacts at the company
    - recent job-linked messages and outreach
  - 2026-04-17: This first slice still relies on saved contacts and job-linked CRM state. It does not yet persist fresh live people-search results into a richer job workflow summary.
  - 2026-04-17: Second slice shipped. The command center now incorporates fresh live people-search results on the job page:
    - top contacts switch to latest recruiter / hiring manager / peer results when available
    - live candidate counts and warm-path counts appear in job activity
    - next-action logic now prefers fresh search output when deciding whether to draft outreach immediately
  - 2026-04-18: Third slice shipped. Decided to persist fresh people-search results as a first-class job research artifact instead of session-local UI state:
    - new `job_research_snapshots` table (one row per (user, job)) storing recruiter / hiring manager / peer arrays plus warm-path / verified counts
    - people-search router auto-upserts the snapshot whenever a job-aware search runs (best-effort, never blocks the search)
    - `JobCommandCenterResponse.research_snapshot` returns the latest snapshot so the command center hydrates across sessions/agents without re-running providers
    - `GET` and `DELETE /api/jobs/{id}/research-snapshot` for explicit fetch/clear
    - backend `next_action` logic now factors persisted live targets into the `draft_live_outreach` recommendation
    - frontend derives in-page `searchResults` from the snapshot when no in-session search has run, surfaces "Saved research snapshot • updated …" with a Clear button on the live-candidates card
  - 2026-04-18: Marked `shipped` — three slices delivered (command center summary, live people-search results in command center, persisted research snapshot per (user, job) with hydrate + clear). Remaining "thread snapshot context into drafting + Dashboard 'act now'" rolled into workstream #3 (Next-Action and Follow-Up Cadence Engine) since it is fundamentally a cadence/dashboard feature using snapshots as input.
- Next checkpoint:
  - none — workstream complete; follow-on work tracked under workstream #3

### 2. Story Bank and Proof-Point Memory

- Status: `shipped`
- Priority: `now`
- Owner: `active thread`
- Goal:
  - Add durable candidate memory for quantified wins, stories, themes, and role-specific framing that can improve drafts, follow-ups, and interview prep over time.
- Why this matters:
  - Career-Ops compounds value by keeping candidate narrative, proof points, and reusable stories as first-class inputs.
  - NexusReach currently has profile plus parsed resume, but not a reusable proof-point layer.
- Scope:
  - introduce a structured store for proof points and stories
  - support tags like:
    - leadership
    - technical depth
    - startup
    - migration
    - product impact
    - conflict / failure / recovery
  - allow drafts and future interview tooling to pull from this store
  - allow human editing rather than full auto-generation only
- Non-goals:
  - no fabricated stories
  - no hidden mutation of profile data without user review
- Dependencies:
  - profile/resume parsing
  - drafting context assembly
- Success criteria:
  - users can store and edit reusable stories and proof points
  - message generation can cite those stories when relevant
  - future interview prep can map questions to stored stories
- Implementation notes:
  - likely touches:
    - profile models and schemas
    - `backend/app/services/message_service.py`
    - profile or settings UI
- Progress notes:
  - 2026-04-17: Defined as a foundational layer for drafting and interview prep.
  - 2026-04-18: First slice (MVP) shipped. Decision: separate `stories` table (taggable, queryable, future interview-map ready) over profile JSONB extension.
    - new `stories` table + Alembic `032_add_stories` (id, user_id, title, summary, situation/action/result, impact_metric, role_focus, tags JSONB)
    - `StoryCreate` / `StoryUpdate` / `StoryResponse` Pydantic schemas
    - `story_service` with user-scoped CRUD + `find_relevant_stories` (tag overlap + role substring relevance)
    - `/api/stories` router (list / create / get / patch / delete)
    - `message_service.draft_message` now injects up to 3 relevant stories into the LLM user prompt under a `STORY BANK` section using job team/domain/seniority + recipient-strategy tags; story IDs stamped into `context_snapshot.story_ids` for traceability
    - frontend: `Story` / `StoryInput` types, `useStories` / `useCreateStory` / `useUpdateStory` / `useDeleteStory` hooks, PATCH added to api client
    - Profile page: new `Stories` step with full CRUD card (STAR fields, impact metric, role focus, tags, edit/delete)
    - tests: `test_stories_api.py` (8 cases — list/create/get/update/delete + 404 paths)
- Next checkpoint:
  - third slice: (no longer needed — interview-prep story mapping already shipped with workstream #4 first slice)
- Progress notes (continued):
  - 2026-04-20: Second slice shipped. Added pinned_story_ids to DraftRequest so any draft can be regenerated with a specific story selection. MessageResponse now exposes story_ids extracted from context_snapshot. MessagesPage shows a purple "Stories used" section listing story titles + impact metrics on any draft that used stories. Adds "Redraft with different story" button (or "Redraft with a story" when none used) that opens an inline story picker (checkbox, up to 3 stories, Redraft fires draft_message with pinned_story_ids bypassing auto-relevance). Third slice (interview-prep hook) already delivered as part of workstream #4 first slice — workstream #2 is now fully shipped.

### 3. Next-Action and Follow-Up Cadence Engine

- Status: `shipped`
- Priority: `now`
- Owner: `active thread`
- Goal:
  - Tell the user what deserves action now across jobs, people, and outreach, with follow-up timing and draft suggestions.
- Why this matters:
  - Career-Ops treats follow-up timing as part of the system, not as a manual memory burden.
  - NexusReach already stores enough CRM state to do this well.
- Scope:
  - add urgency logic for:
    - applied but untouched roles
    - drafted but unsent outreach
    - sent outreach with no response
    - active conversations that need a reply
    - interview thank-you timing
  - generate a recommended channel and target
  - optionally generate the draft inline
  - surface this on Dashboard and Outreach
- Non-goals:
  - no auto-send
  - no spammy repeated follow-ups
- Dependencies:
  - outreach logs
  - message history
  - job stage and interview data
- Success criteria:
  - dashboard can show a reliable queue of time-sensitive next actions
  - outreach and follow-up recommendations have clear reasons
  - users can distinguish `wait`, `follow up`, `reply now`, and `deprioritize`
- Implementation notes:
  - likely touches:
    - `backend/app/services/insights_service.py`
    - `backend/app/services/outreach_service.py`
    - `backend/app/services/message_service.py`
    - `frontend/src/pages/DashboardPage.tsx`
    - `frontend/src/pages/OutreachPage.tsx`
- Progress notes:
  - 2026-04-17: Identified as highest-leverage CRM improvement after the job command center.
  - 2026-04-18: First slice (MVP) shipped. Deterministic rule-based queue — no LLM scoring in v1, every recommendation is explainable.
    - new `cadence_service.compute_next_actions` with 6 rules ranked high→medium→low then oldest-first:
      - `reply_needed` (high): outreach `responded` + `response_received` + user hasn't advanced status
      - `thank_you_due` (high): Job `interviewing` with interview round in last 48h + no `thank_you` message for that job since the interview
      - `draft_unsent` (high): Message `draft`/`edited` older than 24h with no send recorded
      - `awaiting_reply` (medium): Outreach `sent` > 5 days with no `response_received` → suggest follow-up
      - `live_targets_unused` (medium): `job_research_snapshots.verified_count >= 1` for a job with no outreach yet — rolls in the Job Command Center leftover
      - `applied_untouched` (low): Job stage `applied` > 7 days with no outreach
    - `NextAction` dataclass carries kind, urgency, reason, suggested channel/goal, job/person/message refs, age_days, deep_link, meta
    - `/api/cadence/next-actions` GET endpoint with optional `limit`
    - frontend: `NextAction`/`NextActionList` types, `useNextActions` hook, new `ActNowCard` on Dashboard (urgency badge, kind label, age, suggested channel/goal, "Open" deep link)
    - backend tests: `test_cadence_service.py` covering each rule's fire + skip cases (16 unit tests)
    - verified live end-to-end: seeded applied-untouched job, `/api/cadence/next-actions` returned action, Dashboard Act Now rendered "LOW Applied, no outreach · 10 days ago · Suggest: email · referral" with deep link
- Progress notes (continued):
  - 2026-04-21: Second slice shipped. `OutreachCadencePanel` on Outreach page shows reply_needed / awaiting_reply / draft_unsent / thank_you_due / applied_untouched actions with urgency badges and "Draft follow-up" CTA per action.
  - 2026-04-21: Third slice shipped. Cadence thresholds now configurable per user via `UserSettings` DB columns (Alembic 036). `GET/PUT /settings/cadence` endpoints. `CadenceSettingsPanel` with per-field inline Save on Settings page. `useCadenceSettings` + `useUpdateCadenceSettings` hooks.
  - 2026-04-21: Fourth slice shipped. Weekly cadence digest email via Celery beat (Monday 09:00 UTC). `cadence_digest_service` computes next actions per user, renders urgency-grouped HTML + plain text, sends via connected Gmail or Outlook. `cadence_digest_enabled` toggle in Settings. Alembic 037 adds `cadence_digest_enabled` (default true) + `cadence_digest_last_sent_at`. 6-day guard prevents duplicate fires.
- Next checkpoint:
  - none — workstream complete

### 4. Interview-Prep Workspace

- Status: `in_progress`
- Priority: `now`
- Owner: `active thread`
- Goal:
  - Give users a company-and-role-specific interview prep space tied to the saved job and their own story bank.
- Why this matters:
  - Career-Ops has a dedicated interview-prep mode; NexusReach currently only tracks interview rounds.
  - This is a natural extension of the current job + people + public-web stack.
- Scope:
  - research interview process and likely rounds
  - generate role-specific prep themes
  - map likely question categories to stored stories
  - help track interview rounds, interviewer notes, and thank-you follow-up
- Non-goals:
  - no fabricated sourced claims
  - no pretending sparse company data is precise interview intel
- Dependencies:
  - story bank
  - job stage/interview rounds
  - public-web/company research
- Success criteria:
  - a user can prepare for an interview from within NexusReach without external notes
  - the tool can distinguish sourced interview intel from inferred prep guidance
  - interviewer and round data stay tied to the job record
- Implementation notes:
  - likely touches:
    - `frontend/src/pages/TrackerPage.tsx`
    - `frontend/src/pages/JobDetailPage.tsx`
    - `backend/app/routers/jobs.py`
    - new interview-prep service module
- Progress notes:
  - 2026-04-17: Sequenced after story bank because it depends on reusable candidate stories.
  - 2026-04-18: First slice (MVP) shipped. Decision: separate `interview_prep_briefs` table (one per (user, job)) persisted alongside `jobs.interview_rounds`; deterministic generator — no LLM call — every piece of guidance is flagged `inferred` and raw job-posting fields are returned under `sourced_signals` so the UI can distinguish sourced vs inferred.
    - new `interview_prep_briefs` table + Alembic `033_add_interview_prep_briefs` (id, user_id, job_id unique, company_overview, role_summary, likely_rounds JSONB, question_categories JSONB, prep_themes JSONB, story_map JSONB, sourced_signals JSONB, user_notes, generated_at)
    - `InterviewPrepBriefResponse` / `InterviewPrepGenerateRequest` / `InterviewPrepUpdate` Pydantic schemas
    - `interview_prep_service` with deterministic generator (`_make_rounds`, `_make_categories`, `_make_themes`, `_map_stories`) pulling from job title/description/tags + existing story bank for per-category story mapping
    - `/api/jobs/{job_id}/interview-prep` router (GET / POST generate-or-refresh / PATCH notes+story_map / DELETE)
    - frontend: `InterviewPrepBrief` + related types, `useInterviewPrep` / `useGenerateInterviewPrep` / `useUpdateInterviewPrep` / `useDeleteInterviewPrep` hooks
    - new `InterviewPrepPanel` component on `JobDetailPage` (gated to stages `applied | interviewing | offer`) — Generate / Refresh / Clear, role summary, likely rounds, per-category story map + examples, prep themes, editable user notes, every inferred item tagged with an Inferred/Sourced badge
    - tests: `test_interview_prep_api.py` (8 cases — get/create-generate/patch/delete + 404 paths)
- Progress notes (continued):
  - 2026-04-21: Second slice shipped. `InterviewRound` schema gains `completed_at` field. Cadence `_rule_thank_you_due` now prefers `completed_at` over `scheduled_at` when `completed: true` — ties thank-you nudge to actual round completion rather than scheduled time. `InterviewPrepPanel` now accepts `interviewRounds` prop from `JobDetailPage` and renders a "Logged rounds" section showing type label, interviewer name, date, Completed/Scheduled badge, round notes, and an amber thank-you callout when a completed round is within the 48h window.
- Next checkpoint:
  - third slice (optional / deferred): LLM pass to rewrite generic question examples into company-specific probes when a trusted company description exists

### 5. Resume Artifact Generation

- Status: `shipped`
- Priority: `next`
- Owner: `active thread`
- Goal:
  - Upgrade resume tailoring from advice-only to artifact generation while preserving truthful tailoring.
- Why this matters:
  - Career-Ops produces a submission-ready PDF; NexusReach currently stops at suggestions.
  - Users will still want a concrete artifact after deciding a job is worth pursuing.
- Scope:
  - create a saved tailored-resume variant per job
  - optionally support export to PDF and editable text/markdown
  - preserve current explanation layer:
    - skills to emphasize
    - keywords to add
    - bullet rewrites
    - overall strategy
- Non-goals:
  - no invented claims
  - no silent replacement of the user’s base resume
- Dependencies:
  - resume tailoring service
  - profile/resume source of truth
- Success criteria:
  - a user can export a truthful tailored resume variant for a job
  - changes are reviewable and reversible
  - generated artifacts stay linked to the job
- Implementation notes:
  - likely touches:
    - `backend/app/services/resume_tailor.py`
    - jobs schemas/routes
    - `frontend/src/pages/JobDetailPage.tsx`
- Progress notes:
  - 2026-04-17: Explicitly framed as artifact generation, not a generic “improve resume” task.
  - 2026-04-18: First slice shipped. Added a dedicated `resume_artifacts` model and migration, plus `GET/POST /api/jobs/{job_id}/resume-artifact`.
  - 2026-04-18: The job page now lets the user generate, preview, and download a saved markdown resume variant for a role. Artifact generation can reuse the latest tailoring suggestions or generate them on demand.
  - 2026-04-18: The Job Command Center checklist and next-action logic now recognize whether a resume artifact has been saved for the role.
  - 2026-04-18: PDF export shipped. Added on-demand PDF rendering from the saved markdown artifact through `reportlab`, exposed via `GET /api/jobs/{job_id}/resume-artifact/pdf`, with frontend download support from the job page.
  - 2026-04-18: Quality pass shipped for ATS-style one-page output. Replaced generic artifact assembly with a LaTeX resume generator modeled on the user's uploaded template, switched PDF generation to `pdflatex`, rehydrated richer structure from `profile.resume_raw`, preserved per-role locations/contact/certificates, and tightened dense layouts so the generated Intuit-targeted sample fits on a single page without dropping source content.
  - 2026-04-19: Stabilization pass shipped for frontend/fullstack targeting. Resume artifact planning now locks to a stronger one-page blueprint for frontend/fullstack roles instead of allowing planner drift:
    - top 3 experience entries now prefer a 3-bullet shape
    - top 3 projects now prefer a 3/2/2 shape
    - project ranking now favors software-product/fullstack evidence so `ClipForge` stays first and `SignalDraft` outranks sports-analytics work for roles like Intuit SWE1 Fullstack
    - the `Relevant` skills line now mirrors the approved recruiter/ATS surface for frontend/fullstack jobs (`React`, `JavaScript`, `TypeScript`, `HTML`, `CSS`, `Next.js`, `Node.js`, `RESTful APIs`, `Playwright`, `Cypress`, `responsive UI`, `component-based architecture`, `testing`, `debugging`, `telemetry`, `CI/CD`, `Git`, `cross-functional collaboration`)
    - regression tests added in `backend/tests/test_resume_artifact_service.py` to preserve the approved artifact shape across future edits
- Next checkpoint:
  - optional future enhancements only: parser round-trip validation against real ATS exports, DOCX export, in-app editing, alternate templates, or richer typography/layout controls

### 6. Batch Triage for Networking ROI

- Status: `planned`
- Priority: `later`
- Owner: `unassigned`
- Goal:
  - Help the user decide which jobs deserve networking effort by evaluating opportunity quality and reachable path quality in bulk.
- Why this matters:
  - Career-Ops is excellent at throughput.
  - NexusReach should borrow that throughput, but optimize for networking ROI rather than generic application volume.
- Scope:
  - batch process discovered/imported jobs
  - rank jobs by:
    - job fit
    - contactability
    - warm-path presence
    - company confidence
    - outreach opportunity quality
  - show a shortlist worth deeper effort
- Non-goals:
  - no spray-and-pray application engine
  - no reduction of people safety checks for speed
- Dependencies:
  - job scoring
  - people search
  - warm-path signals
  - dashboard summaries
- Success criteria:
  - user can quickly identify which jobs are worth active networking
  - ranking reasons are visible and explainable
  - the workflow reduces wasted effort on low-path roles
- Implementation notes:
  - likely touches:
    - jobs service
    - people service
    - dashboard/jobs UI
- Progress notes:
  - 2026-04-17: Positioned as later because it builds on the other workflow improvements.
- Next checkpoint:
  - define the networking-ROI scoring dimensions

## Supporting decisions to make

### Product decisions

- Status: `planned`
- Priority: `now`
- Questions:
  - Should story bank live in Profile, Settings, or a separate workspace?
  - Should the Job Command Center replace the current Job Detail page or extend it?
  - Should follow-up cadence rely only on explicit outreach history, or also on job stages like `applied` and `interviewing`?
  - Should tailored resumes be editable in-app, downloadable only, or both?
  - Should interview prep be job-centric, company-centric, or both?
- Next checkpoint:
  - resolve these before implementation work starts on the first two workstreams

## Suggested implementation sequence

### Now

1. Design the Job Command Center payload and UI structure.
2. Design the Story Bank data model and editing UX.
3. Define next-action and cadence rules so Dashboard can surface an actionable queue.

### Next

1. Build the Interview-Prep Workspace on top of the story bank and interview tracking.
2. Add tailored resume artifact generation.

### Later

1. Add batch triage for networking ROI.
2. Revisit whether any of the cadence engine should feed reminders or automations.

## Agent handoff notes

- Read this file together with:
  - `PLAN.md`
  - `HANDOFF.md`
  - `PRD.md`
  - `architecture.md`
- If an implementation changes roadmap priority or invalidates assumptions here, update this file in the same change.
- If a workstream is partially shipped, do not mark it `shipped`. Split remaining work into a follow-up dated note under that workstream.
