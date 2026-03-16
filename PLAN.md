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

- [ ] Settings page UI
- [ ] Outreach guardrails toggles (7-day gap, follow-up suggestions, response warnings)
- [ ] Toggle-off modal with risk explanation
- [ ] Persistent "Guardrails: Modified" indicator
- [ ] API key management (user-provided keys for personal use)
- [ ] Email integration management (connect/disconnect)
- [ ] Profile editing from settings

**Deliverable:** User has full control over tool behaviour with sensible defaults.

---

## Phase 10: Polish + Production
**Goal:** Production-ready deployment.

- [ ] Error boundary components (frontend)
- [ ] Loading states and skeleton screens
- [ ] Mobile responsive design pass
- [ ] Rate limiting on backend endpoints
- [ ] API cost tracking and per-user daily limits
- [ ] Onboarding flow for new users
- [ ] Production environment setup (Vercel + Railway)
- [ ] CI/CD pipeline
- [ ] End-to-end testing for core flows

**Deliverable:** Production-ready NexusReach.

---

## Current Status

**Phase:** Phase 8 complete

**Completed:** Phase 1 (Skeleton + Auth), Phase 2 (Profile Setup + Resume Parsing), Phase 3 (People Finder), Phase 4 (Message Drafting), Phase 5 (Email Layer), Phase 6 (Job Intelligence), Phase 7 (Outreach Tracker CRM), Phase 8 (Insights Dashboard)

**Next step:** Phase 9 — Settings + Guardrails
