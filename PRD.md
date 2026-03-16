# NexusReach — Product Requirements Document

## Vision

A smart personal networking assistant that takes you from "I want to work at Company X" to a thoughtful, human-approved message ready to send. Solves the LinkedIn black hole problem — where connections are shallow, applications vanish, and networking feels like a guessing game.

NexusReach makes networking systematic without making it fake. The human is always in the loop.

---

## Target Users

- New grad software engineers looking for their first role
- Interns seeking full-time conversion or new opportunities
- Early-career professionals growing their network intentionally
- Career switchers who don't have an existing industry network

---

## Module 1: Your Profile (The Foundation)

Everything the AI generates is grounded in the user's real background. Set up once, referenced everywhere.

### Features

- **Resume upload & parsing** — PDF/DOCX upload, auto-extracted into structured data (skills, experience, education, projects)
- **Bio** — Short free-text "who I am" written in the user's own words
- **Goals** — Multi-select: Find a Job, Find a Mentor, Grow Network (can select all three)
- **Target preferences** — Industries, company sizes, roles, locations
- **Tone preference** — Formal, Conversational, Humble/Curious
- **Portfolio links** — GitHub, personal site, LinkedIn URL

### Data Model

The parsed resume + bio + goals + tone form the "user context" that feeds into every AI-generated message.

---

## Module 2: Job & Company Intelligence

Finds and tracks opportunities so the user always knows where to focus networking energy.

### Job Sourcing

| Source | Type | What it covers |
|--------|------|----------------|
| JSearch (RapidAPI) | Aggregator API | LinkedIn, Indeed, Glassdoor, ZipRecruiter |
| Adzuna API | Aggregator API | Millions of broad market jobs |
| Greenhouse / Lever / Ashby / Workday | ATS APIs | Direct company feeds, freshest data |
| Dice API | Job board API | Tech-focused roles |
| Remotive / Jobicy | Public APIs | Remote-specific roles |
| SimplifyJobs New-Grad-Positions | GitHub API | Curated new grad roles (markdown table parsing) |
| SimplifyJobs Summer2026-Internships | GitHub API | Curated internship roles (markdown table parsing) |
| newgrad-jobs.com | Web scraper | New grad specific listings |

### Features

- **Job monitoring** — User sets target companies or roles, system surfaces new postings automatically
- **Company research engine** — For any company: size, funding stage, tech stack, recent news, open roles, inferred team structure
- **Opportunity scoring** — Ranks jobs against user profile (not just title match — reads full JD and compares to actual experience)
- **Deduplication** — Same job on multiple boards gets fingerprinted by company + title + location and collapsed
- **Job tracker** — Kanban board: Interested → Researching → Networking → Applied → Interviewing → Offer. Every outreach links back to a job/company

---

## Module 3: People Finder

For any company or job posting, finds the right humans to connect with.

### Data Sources

| Source | What it gets you |
|--------|-----------------|
| Apollo.io API | Primary source. 275M+ profiles. Search by company, title, department, seniority. Returns work email where available |
| Proxycurl API | LinkedIn profile enrichment by URL or search. Current role, past experience, education |
| GitHub API | Engineers at a company by org membership or email domain. Repos, languages, recent commits |
| Company website scraper | Team pages, blog authors, speaker bios |
| Manual input | User pastes a LinkedIn URL, tool enriches via Proxycurl |

### People Surfacing Logic

For each target job/company, surface three types of people:

| Person | Why they matter |
|--------|----------------|
| Recruiter / Talent Acquisition | Direct line into the hiring process |
| Hiring Manager / Team Lead | Understands the role deeply, can champion you |
| Peer / Potential Teammate | Most likely to respond, most authentic conversation |

User always chooses who to reach out to. The tool never contacts anyone automatically.

### Job-Aware Search

When a user clicks "Find People" from a saved job, the system runs a **targeted search** instead of a generic one:

1. **Context extraction** — The job title and description are analyzed to extract department (engineering, product, design, etc.), team keywords (backend, ML, mobile, etc.), and seniority level.
2. **Targeted Apollo searches** — Three searches are run using the extracted context:
   - **Recruiters**: Titles like "Engineering Recruiter" filtered to the job's department
   - **Managers**: Titles like "Backend Engineering Manager" filtered to the job's department + seniority
   - **Peers**: Titles like "Backend Engineer" filtered to the job's department
3. **Department filtering** — Apollo's `person_departments` filter ensures results come from the same part of the company as the target role.
4. **Graceful fallback** — If a department-filtered search yields fewer than 2 results, the system re-runs without the department filter to ensure the user always gets useful contacts.

This means searching for people at Stripe after saving a "Backend Engineer" role returns backend engineering managers, engineering recruiters, and backend engineers — not generic HR or marketing contacts.

---

## Module 4: Message Drafting Engine

Drafts personalized, thoughtful outreach grounded in real context.

### AI Inputs

- User's full profile and goals
- Target person's role, background, tenure, experience (from Apollo/Proxycurl)
- Specific job description or team context
- For engineers: their actual GitHub work (repos, languages, recent commits)
- User's selected goal for this specific message (job inquiry, informational interview, mentorship, general connection)

### Message Types

| Type | Format |
|------|--------|
| LinkedIn connection note | 300 character limit respected |
| LinkedIn message | ~150 words, slightly warmer tone |
| Professional email | 150-200 words, includes subject line, signature |
| Follow-up message | Context-aware, acknowledges previous contact |
| Thank you / post-conversation | References what was discussed |

### Re-engagement Drafting

When contacting someone a second time, the AI knows and writes accordingly:
- Acknowledges previous outreach naturally
- Provides new context (new role opened, new project completed, etc.)
- Never pretends to be a first contact

### Transparency

Every draft shows the user why the AI wrote what it wrote — which part of their profile it referenced, which part of the target's background it highlighted.

---

## Module 5: Email Layer

### Email Finding Waterfall

Tries each source in order, stops when it finds a verified work email:

1. **Apollo.io** — checked first, has work emails for ~60% of profiles
2. **Hunter.io** — fills the gap, strong on company domain pattern verification
3. **Proxycurl** — final check
4. **Fallback** — if no verified email found, silently switches to LinkedIn message mode

### Email Sending

| Mode | How it works |
|------|-------------|
| Connected Gmail/Outlook | OAuth connection, email staged as a draft in user's actual inbox. User opens, reviews, hits send |
| Draft only | Full email generated with copy button, user pastes manually |

Never auto-sends. Human always reviews and approves.

### Email vs LinkedIn Format Differences

| Aspect | LinkedIn | Email |
|--------|----------|-------|
| Length | 300 chars (connection) / ~150 words (message) | 150-200 words |
| Subject line | N/A | Generated, specific not generic |
| Tone | Slightly warmer, casual | Professional but human |
| CTA | "Would love to connect" | "Would you have 15 minutes for a call?" |
| Signature | None | Name, title, LinkedIn URL, portfolio |

---

## Module 6: Outreach Tracker (Personal CRM)

### Features

- **Status tracking per contact** — Draft → Sent → Connected → Responded → Met → Following Up
- **Reminder system** — "You connected with Sarah 2 weeks ago and haven't followed up"
- **Response rate analytics** — Which message types, roles, companies get responses
- **Notes field** — What you talked about, what you promised to send them
- **Timeline view** — Full networking activity history
- **Contact history always visible** — Before any re-engagement, user sees full history of prior contact (this is non-toggleable)

### Links

Every contact links back to the job/company that prompted the outreach, creating a full picture of networking efforts per opportunity.

---

## Module 7: Insights Dashboard

### Metrics

- Response rates by message type, role type, company
- Which message angles get responses (GitHub reference vs shared background vs direct job inquiry)
- Network growth over time
- Network gaps — industries or roles the user hasn't reached into yet
- Warm path finder — do existing connections work at a target company
- Which companies have the most open doors based on response rates

---

## Outreach Guardrails

Sensible defaults with user control. Never hard blocks — just informed decision-making.

| Setting | Default | Toggleable | Warning When Off |
|---------|---------|-----------|-----------------|
| Minimum gap between messages to same person (7 days) | ON | Yes | "Sending too frequently may appear unprofessional and increase spam risk" |
| Follow-up suggestion after 1 week | ON | Yes | None (just a suggestion) |
| Contact history shown before re-engaging | ON | No (always on) | N/A |
| Response rate warnings | ON | Yes | None (informational) |

### Toggle Experience

When user turns off the 7-day minimum:
1. One-time modal explaining the risk
2. User confirms they understand
3. Setting saves
4. Subtle persistent indicator on dashboard: "Guardrails: Modified"
5. Can flip back on anytime

---

## Authentication & Accounts

- Supabase Auth (email + password, Google OAuth, GitHub OAuth)
- Each user has fully isolated data
- API keys stored encrypted per user

---

## Non-Functional Requirements

- **Privacy** — No user data shared between accounts. Outreach data never leaves the user's account
- **Performance** — Job search results within 3 seconds. People finder within 5 seconds. Message draft within 10 seconds
- **Reliability** — Graceful degradation when external APIs fail (show cached data, skip unavailable sources)
- **Mobile** — Responsive web design, usable on mobile browsers
