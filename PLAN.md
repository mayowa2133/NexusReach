# NexusReach — Build Plan

## Build Philosophy

Ship a working core loop first, then layer features on top. At every phase, the user has something usable — not a half-built system that only works when everything is done.

---

## Phase 1: Project Skeleton + Auth
**Goal:** Working frontend + backend with authentication. User can sign up, log in, and see a dashboard shell.

- [ ] Initialize Vite + React + TypeScript frontend
- [ ] Install and configure Shadcn/ui + Tailwind CSS
- [ ] Set up React Router with page shells (Dashboard, Profile, Jobs, People, Messages, Outreach, Settings)
- [ ] Initialize FastAPI backend with project structure
- [ ] Set up SQLAlchemy + Alembic + PostgreSQL connection
- [ ] Implement Supabase Auth integration (signup, login, JWT validation)
- [ ] Create base database models (users, profiles, user_settings)
- [ ] Set up environment variable management (pydantic-settings)
- [ ] Create API client utility on frontend (TanStack Query + auth headers)
- [ ] Zustand store for auth state
- [ ] Protected route wrapper on frontend

**Deliverable:** User can sign up, log in, and see the empty dashboard.

---

## Phase 2: Profile Setup + Resume Parsing
**Goal:** User creates their profile — the foundation that feeds every AI-generated message.

- [ ] Build profile setup page (multi-step form)
- [ ] Resume upload component (PDF/DOCX)
- [ ] Backend resume parsing service (extract skills, experience, education, projects)
- [ ] Profile API endpoints (CRUD)
- [ ] Store parsed resume as structured JSONB
- [ ] Bio, goals, tone, target preferences form fields
- [ ] Portfolio links (GitHub, LinkedIn, personal site)
- [ ] Profile completion indicator on dashboard

**Deliverable:** User has a complete profile that the AI can reference.

---

## Phase 3: People Finder
**Goal:** User enters a company or job URL and gets relevant people to network with.

- [ ] Apollo.io API client (search by company + title + seniority)
- [ ] Proxycurl API client (enrich by LinkedIn URL)
- [ ] GitHub API client (find engineers by org, get repos/activity)
- [ ] Company website scraper (team pages, blog authors)
- [ ] People finder service (orchestrates all sources)
- [ ] Person database model + API endpoints
- [ ] Company database model + API endpoints
- [ ] People search UI — enter company name, see results categorized (recruiter / manager / peer)
- [ ] Manual LinkedIn URL input — paste URL, get enriched profile
- [ ] Person detail card (role, background, GitHub activity if available)

**Deliverable:** User can find relevant people at any company.

---

## Phase 4: Message Drafting
**Goal:** The core value — AI drafts personalized messages grounded in real context.

- [ ] Claude API client
- [ ] Message drafting service (assembles context, calls Claude, returns draft + reasoning)
- [ ] Prompt engineering — system prompt with user profile, person profile, job context, goal
- [ ] Message database model + API endpoints
- [ ] Message drafting UI — select person, choose goal, choose channel (LinkedIn/email), see draft
- [ ] Draft editing interface — user can modify before approving
- [ ] AI reasoning display — show why the AI wrote what it wrote
- [ ] Copy to clipboard functionality
- [ ] Re-engagement awareness — detect prior outreach history, adjust draft accordingly
- [ ] All message types: LinkedIn note, LinkedIn message, email, follow-up, thank-you

**Deliverable:** User can draft and copy personalized messages for any contact.

---

## Phase 5: Email Layer
**Goal:** Find work emails and stage drafts in the user's inbox.

- [ ] Hunter.io API client (email finder + verification)
- [ ] Email finding waterfall service (Apollo → Hunter → Proxycurl → fallback)
- [ ] Gmail OAuth integration (consent flow, token storage)
- [ ] Outlook OAuth integration (consent flow, token storage)
- [ ] Gmail draft staging (create draft via API)
- [ ] Outlook draft staging (create draft via Graph API)
- [ ] Email-specific message formatting (subject line, signature, professional tone)
- [ ] Settings page: connect/disconnect Gmail and Outlook
- [ ] Fallback UI — when no email found, show LinkedIn option instead

**Deliverable:** User can find work emails and stage personalized drafts in their inbox.

---

## Phase 6: Job Intelligence
**Goal:** Comprehensive job monitoring and tracking.

- [ ] JSearch (RapidAPI) client
- [ ] Adzuna API client
- [ ] ATS clients (Greenhouse, Lever, Ashby, Workday public APIs)
- [ ] Dice API client
- [ ] Remotive / Jobicy client
- [ ] GitHub SimplifyJobs markdown table parser (New Grad + Internships)
- [ ] newgrad-jobs.com web scraper
- [ ] Job deduplication service (fingerprint by company + title + location)
- [ ] Opportunity scoring service (compare JD against user profile)
- [ ] Celery periodic task for job sync (every 6 hours)
- [ ] Job search + filter UI
- [ ] Job detail view (description, match score, linked people, linked outreach)
- [ ] Kanban job tracker (Interested → Researching → Networking → Applied → Interviewing → Offer)
- [ ] Company research panel (size, funding, tech stack, open roles)

**Deliverable:** User has a comprehensive job board with intelligent scoring and tracking.

---

## Phase 7: Outreach Tracker (CRM)
**Goal:** Nothing falls through the cracks.

- [ ] Outreach log database model + API endpoints
- [ ] CRM UI — list view + timeline view of all contacts
- [ ] Status tracking per contact (Draft → Sent → Connected → Responded → Met → Following Up → Closed)
- [ ] Notes field per contact
- [ ] Reminder system — Celery task for follow-up notifications
- [ ] Link outreach records to jobs and companies
- [ ] Response rate tracking per contact
- [ ] Contact history view (always visible before re-engagement, non-toggleable)

**Deliverable:** User has a full personal CRM tracking every networking interaction.

---

## Phase 8: Insights Dashboard
**Goal:** Help users network smarter over time.

- [ ] Response rate analytics (by message type, role type, company)
- [ ] Message angle effectiveness (GitHub reference vs shared background vs direct inquiry)
- [ ] Network growth chart over time
- [ ] Network gap analysis (industries/roles not yet reached)
- [ ] Warm path finder (existing connections at target companies)
- [ ] Company openness ranking (based on response rates)
- [ ] Dashboard home page with key metrics summary

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

**Phase:** Not started — foundation documents complete (PRD, Architecture, CLAUDE.md, PLAN.md)

**Next step:** Begin Phase 1 — Project Skeleton + Auth
