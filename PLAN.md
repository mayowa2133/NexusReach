# NexusReach — Build Plan

## Build Philosophy

Ship a working core loop first, then layer features on top. At every phase, the user has something usable — not a half-built system that only works when everything is done.

---

## Phase 1: Project Skeleton + Auth
**Goal:** Working frontend + backend with authentication. User can sign up, log in, and see a dashboard shell.

- [x] Initialize Vite + React + TypeScript frontend
- [x] Install and configure Shadcn/ui + Tailwind CSS
- [x] Set up React Router with page shells (Dashboard, Profile, Jobs, People, Messages, Outreach, Settings)
- [x] Initialize FastAPI backend with project structure
- [x] Set up SQLAlchemy + Alembic + PostgreSQL connection
- [x] Implement Supabase Auth integration (signup, login, JWT validation)
- [x] Create base database models (users, profiles, user_settings)
- [x] Set up environment variable management (pydantic-settings)
- [x] Create API client utility on frontend (TanStack Query + auth headers)
- [x] Zustand store for auth state
- [x] Protected route wrapper on frontend

**Deliverable:** User can sign up, log in, and see the empty dashboard.

---

## Phase 2: Profile Setup + Resume Parsing
**Goal:** User creates their profile — the foundation that feeds every AI-generated message.

- [x] Build profile setup page (multi-step form)
- [x] Resume upload component (PDF/DOCX)
- [x] Backend resume parsing service (extract skills, experience, education, projects)
- [x] Profile API endpoints (CRUD)
- [x] Store parsed resume as structured JSONB
- [x] Bio, goals, tone, target preferences form fields
- [x] Portfolio links (GitHub, LinkedIn, personal site)
- [x] Profile completion indicator on dashboard

**Deliverable:** User has a complete profile that the AI can reference.

---

## Phase 3: People Finder
**Goal:** User enters a company or job URL and gets relevant people to network with.

- [x] Apollo.io API client (search by company + title + seniority)
- [x] Proxycurl API client (enrich by LinkedIn URL)
- [x] GitHub API client (find engineers by org, get repos/activity)
- [ ] Company website scraper (team pages, blog authors)
- [x] People finder service (orchestrates all sources)
- [x] Person database model + API endpoints
- [x] Company database model + API endpoints
- [x] People search UI — enter company name, see results categorized (recruiter / manager / peer)
- [x] Manual LinkedIn URL input — paste URL, get enriched profile
- [x] Person detail card (role, background, GitHub activity if available)

**Deliverable:** User can find relevant people at any company.

---

## Phase 4: Message Drafting
**Goal:** The core value — AI drafts personalized messages grounded in real context.

- [x] Claude API client
- [x] Message drafting service (assembles context, calls Claude, returns draft + reasoning)
- [x] Prompt engineering — system prompt with user profile, person profile, job context, goal
- [x] Message database model + API endpoints
- [x] Message drafting UI — select person, choose goal, choose channel (LinkedIn/email), see draft
- [x] Draft editing interface — user can modify before approving
- [x] AI reasoning display — show why the AI wrote what it wrote
- [x] Copy to clipboard functionality
- [x] Re-engagement awareness — detect prior outreach history, adjust draft accordingly
- [x] All message types: LinkedIn note, LinkedIn message, email, follow-up, thank-you

**Deliverable:** User can draft and copy personalized messages for any contact.

---

## Phase 5: Email Layer
**Goal:** Find work emails and stage drafts in the user's inbox.

- [x] Hunter.io API client (email finder + verification)
- [x] Email finding waterfall service (Apollo → Hunter → Proxycurl → fallback)
- [x] Gmail OAuth integration (consent flow, token storage)
- [x] Outlook OAuth integration (consent flow, token storage)
- [x] Gmail draft staging (create draft via API)
- [x] Outlook draft staging (create draft via Graph API)
- [x] Email-specific message formatting (subject line, signature, professional tone)
- [x] Settings page: connect/disconnect Gmail and Outlook
- [x] Fallback UI — when no email found, show LinkedIn option instead

**Deliverable:** User can find work emails and stage personalized drafts in their inbox.

---

## Phase 6: Job Intelligence
**Goal:** Comprehensive job monitoring and tracking.

- [x] JSearch (RapidAPI) client
- [x] Adzuna API client
- [x] ATS clients (Greenhouse, Lever, Ashby)
- [x] Dice API client
- [x] Remotive / Jobicy client
- [x] GitHub SimplifyJobs markdown table parser (New Grad + Internships)
- [ ] newgrad-jobs.com web scraper
- [x] Job deduplication service (fingerprint by company + title + location)
- [x] Opportunity scoring service (compare JD against user profile)
- [ ] Celery periodic task for job sync (every 6 hours)
- [x] Job search + filter UI
- [x] Job detail view (description, match score, linked people, linked outreach)
- [x] Kanban job tracker (Discovered → Interested → Researching → Networking → Applied → Interviewing → Offer)
- [ ] Company research panel (size, funding, tech stack, open roles)

**Deliverable:** User has a comprehensive job board with intelligent scoring and tracking.

---

## Phase 7: Outreach Tracker (CRM)
**Goal:** Nothing falls through the cracks.

- [x] Outreach log database model + API endpoints
- [x] CRM UI — list view + timeline view of all contacts
- [x] Status tracking per contact (Draft → Sent → Connected → Responded → Met → Following Up → Closed)
- [x] Notes field per contact
- [ ] Reminder system — Celery task for follow-up notifications
- [x] Link outreach records to jobs and companies
- [x] Response rate tracking per contact
- [x] Contact history view (always visible before re-engagement, non-toggleable)

**Deliverable:** User has a full personal CRM tracking every networking interaction.

---

## Phase 8: Insights Dashboard
**Goal:** Help users network smarter over time.

- [x] Response rate analytics (by message type, role type, company)
- [x] Message angle effectiveness (GitHub reference vs shared background vs direct inquiry)
- [x] Network growth chart over time
- [x] Network gap analysis (industries/roles not yet reached)
- [x] Warm path finder (existing connections at target companies)
- [x] Company openness ranking (based on response rates)
- [x] Dashboard home page with key metrics summary

**Deliverable:** User sees actionable insights about what's working.

---

## Phase 9: Settings + Guardrails
**Goal:** User control over all configurable behaviours.

- [x] Settings page UI
- [x] Outreach guardrails toggles (7-day gap, follow-up suggestions, response warnings)
- [x] Toggle-off modal with risk explanation
- [x] Persistent "Guardrails: Modified" indicator
- [x] Email integration management (connect/disconnect)
- [ ] API key management (user-provided keys for personal use)
- [ ] Profile editing from settings

**Deliverable:** User has full control over tool behaviour with sensible defaults.

---

## Phase 10: Polish + Production
**Goal:** Production-ready deployment.

- [x] Error boundary components (frontend)
- [x] Loading states and skeleton screens
- [x] Mobile responsive design pass
- [x] Rate limiting on backend endpoints
- [x] API cost tracking and per-user daily limits
- [x] Onboarding flow for new users
- [x] Production environment setup (Vercel + Railway)
- [x] CI/CD pipeline
- [x] End-to-end testing for core flows

**Deliverable:** Production-ready NexusReach.

---

## Phase 11: Job-Aware People Discovery
**Goal:** Connect job search and people finder — clicking "Find People" from a saved job automatically searches for people on the same team/department as that role.

- [x] Job context extraction utility (`backend/app/utils/job_context.py`) — pure function that derives department, team keywords, seniority, and targeted search titles from job title + description
- [x] Apollo client enhancement — add `departments` param to `search_people()` for department-filtered searches
- [x] Job-aware people service (`search_people_for_job()`) — loads job from DB, extracts context, runs 3 targeted Apollo searches (recruiters, managers, peers) with department filtering and fallback
- [x] Schema + router updates — `job_id` param on `PeopleSearchRequest`, `JobContextResponse` in response, router dispatches to job-aware search when `job_id` present
- [x] "Find People" button on job cards — navigates to people page with job context in URL params
- [x] Job-aware people page — auto-fills company, auto-triggers search, shows job context banner with department/team badges
- [x] Unit tests for job context extraction + API tests for job-aware search endpoint

**Deliverable:** User can click "Find People" on any saved job and get team-relevant recruiters, managers, and peers — not generic results.

---

## Phase 12: Apollo Free Discovery + On-Demand Enrichment
**Goal:** Switch from credit-consuming people search to Apollo's free discovery endpoint, and add on-demand email enrichment so the app works on Apollo's Free tier (100 emails/month) instead of requiring the $79/month Professional plan.

- [x] Add `apollo_master_api_key` config setting — free endpoint authenticates via header, not JSON body
- [x] Add `apollo_id` column to Person model + Alembic migration — stores Apollo's person ID for efficient enrichment
- [x] Refactor Apollo client — switch `search_people()` from `/v1/mixed_people/search` (credits) to `/api/v1/mixed_people/api_search` (free, no emails)
- [x] Add `enrich_person()` to Apollo client — calls `/v1/people/match` (1 credit) for on-demand email enrichment
- [x] Update `_store_person()` — handle `apollo_id`, dedup by `apollo_id` when no LinkedIn URL
- [x] Add Apollo enrichment step to email waterfall — now: Existing → Apollo Enrichment → Hunter → Proxycurl → Hunter Domain → Exhausted
- [x] Update schemas + types — `apollo_id` field on `PersonResponse` and frontend `Person` type
- [x] "Get Email" button on person cards — three states: email found, enrichment possible (button), no email available
- [x] Apollo client unit tests — verify free endpoint, header auth, no emails in search, enrichment flow
- [x] Updated existing test mocks with `apollo_id`

**Deliverable:** People discovery costs zero Apollo credits. Email enrichment happens on-demand (1 credit per "Get Email" click). App works on Apollo Free tier.

---

## Current Status

**Phase:** Phase 12 complete — Apollo Free Discovery + On-Demand Enrichment shipped!

**Completed:** Phase 1 (Skeleton + Auth), Phase 2 (Profile Setup + Resume Parsing), Phase 3 (People Finder), Phase 4 (Message Drafting), Phase 5 (Email Layer), Phase 6 (Job Intelligence), Phase 7 (Outreach Tracker CRM), Phase 8 (Insights Dashboard), Phase 9 (Settings + Guardrails), Phase 10 (Polish + Production), Phase 11 (Job-Aware People Discovery), Phase 12 (Apollo Free Discovery + On-Demand Enrichment)
