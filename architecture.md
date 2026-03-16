# NexusReach — Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (React)                       │
│              Vercel — nexusreach.vercel.app               │
└──────────────────────┬──────────────────────────────────┘
                       │ REST API (HTTPS)
┌──────────────────────▼──────────────────────────────────┐
│                  Backend (FastAPI)                        │
│                  Railway — api.nexusreach.com             │
│                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐  │
│  │ Profile   │ │ Jobs     │ │ People   │ │ Outreach  │  │
│  │ Router    │ │ Router   │ │ Router   │ │ Router    │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────┘  │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │              Service Layer                        │   │
│  │  ProfileService | JobService | PeopleService     │   │
│  │  MessageService | OutreachService | InsightService│   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │           External API Clients                    │   │
│  │  Apollo | Proxycurl | Hunter | GitHub | JSearch   │   │
│  │  Adzuna | Claude | Gmail | Outlook               │   │
│  └──────────────────────────────────────────────────┘   │
└──────────┬──────────────────────┬───────────────────────┘
           │                      │
    ┌──────▼──────┐        ┌──────▼──────┐
    │ PostgreSQL  │        │ Redis       │
    │ (Supabase)  │        │ (Railway)   │
    └─────────────┘        └──────┬──────┘
                                  │
                           ┌──────▼──────┐
                           │ Celery      │
                           │ Workers     │
                           └─────────────┘
```

## Architecture Style

**Modular monolith** — not microservices. All modules live in a single FastAPI application, organized as separate routers and services. This is the right choice because:
- Single developer / small team
- Shared database
- No need for independent scaling at this stage
- Far simpler to develop, deploy, and debug
- Can be split into microservices later if scale demands it

---

## Frontend Architecture

```
frontend/
├── src/
│   ├── app/                    # Next.js app router (or Vite + React Router)
│   ├── components/
│   │   ├── ui/                 # Shadcn/ui components
│   │   ├── profile/            # Profile setup components
│   │   ├── jobs/               # Job board, tracker, search
│   │   ├── people/             # People finder, cards, detail views
│   │   ├── messages/           # Message drafting, preview, editing
│   │   ├── outreach/           # CRM tracker, timeline, reminders
│   │   └── dashboard/          # Insights charts and metrics
│   ├── hooks/                  # Custom React hooks
│   ├── lib/                    # API client, utilities
│   ├── stores/                 # State management (Zustand)
│   └── types/                  # TypeScript type definitions
├── public/
├── package.json
└── tsconfig.json
```

**Key decisions:**
- **Shadcn/ui** for component library (not a dependency — copies components into project)
- **Zustand** for state management (lightweight, no boilerplate)
- **TanStack Query** for server state (caching, background refetching)
- **React Router** or **Next.js App Router** (TBD based on SSR needs)

---

## Backend Architecture

```
backend/
├── app/
│   ├── main.py                 # FastAPI app entry point
│   ├── config.py               # Settings, env vars, API keys
│   ├── dependencies.py         # Shared dependencies (DB session, auth)
│   │
│   ├── routers/                # API route handlers
│   │   ├── profile.py
│   │   ├── jobs.py
│   │   ├── people.py
│   │   ├── messages.py
│   │   ├── outreach.py
│   │   ├── insights.py
│   │   └── auth.py
│   │
│   ├── services/               # Business logic
│   │   ├── profile_service.py
│   │   ├── job_service.py
│   │   ├── people_service.py
│   │   ├── message_service.py
│   │   ├── outreach_service.py
│   │   ├── insight_service.py
│   │   └── resume_parser.py
│   │
│   ├── clients/                # External API wrappers
│   │   ├── apollo_client.py
│   │   ├── proxycurl_client.py
│   │   ├── hunter_client.py
│   │   ├── github_client.py
│   │   ├── jsearch_client.py
│   │   ├── adzuna_client.py
│   │   ├── ats_client.py       # Greenhouse, Lever, Ashby, Workday
│   │   ├── claude_client.py
│   │   ├── gmail_client.py
│   │   └── outlook_client.py
│   │
│   ├── models/                 # SQLAlchemy ORM models
│   │   ├── user.py
│   │   ├── profile.py
│   │   ├── job.py
│   │   ├── company.py
│   │   ├── person.py
│   │   ├── message.py
│   │   └── outreach.py
│   │
│   ├── schemas/                # Pydantic request/response schemas
│   │   ├── profile.py
│   │   ├── job.py
│   │   ├── people.py
│   │   ├── message.py
│   │   └── outreach.py
│   │
│   ├── tasks/                  # Celery background tasks
│   │   ├── job_sync.py         # Periodic job fetching from all sources
│   │   ├── company_research.py # Background company enrichment
│   │   └── reminders.py        # Follow-up reminder notifications
│   │
│   └── utils/
│       ├── dedup.py            # Job deduplication logic
│       ├── job_context.py      # Job context extraction (department, team, seniority)
│       ├── markdown_parser.py  # Parse SimplifyJobs GitHub tables
│       └── scoring.py          # Opportunity scoring algorithm
│
├── alembic/                    # Database migrations
├── tests/
├── requirements.txt
└── Dockerfile
```

---

## Database Schema

### users
```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### profiles
```sql
CREATE TABLE profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    full_name VARCHAR(255),
    bio TEXT,
    goals TEXT[],                        -- ['job', 'mentor', 'network']
    tone VARCHAR(50) DEFAULT 'conversational', -- formal | conversational | humble
    target_industries TEXT[],
    target_company_sizes TEXT[],
    target_roles TEXT[],
    target_locations TEXT[],
    linkedin_url VARCHAR(500),
    github_url VARCHAR(500),
    portfolio_url VARCHAR(500),
    resume_raw TEXT,                     -- Original resume text
    resume_parsed JSONB,                -- Structured: {skills, experience, education, projects}
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### companies
```sql
CREATE TABLE companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    domain VARCHAR(255),
    size VARCHAR(50),
    industry VARCHAR(255),
    funding_stage VARCHAR(100),
    tech_stack TEXT[],
    description TEXT,
    careers_url VARCHAR(500),
    enriched_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### jobs
```sql
CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    company_id UUID REFERENCES companies(id),
    title VARCHAR(500) NOT NULL,
    description TEXT,
    location VARCHAR(255),
    remote BOOLEAN DEFAULT FALSE,
    url VARCHAR(1000),
    source VARCHAR(100),                -- jsearch | adzuna | greenhouse | simplify_newgrad | etc
    source_id VARCHAR(500),             -- External ID for dedup
    fingerprint VARCHAR(255),           -- company+title+location hash for dedup
    opportunity_score FLOAT,            -- 0-1 match against user profile
    status VARCHAR(50) DEFAULT 'interested', -- interested | researching | networking | applied | interviewing | offer
    posted_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### persons
```sql
CREATE TABLE persons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    company_id UUID REFERENCES companies(id),
    full_name VARCHAR(255),
    title VARCHAR(255),
    department VARCHAR(255),
    seniority VARCHAR(100),
    linkedin_url VARCHAR(500),
    github_url VARCHAR(500),
    work_email VARCHAR(255),
    email_source VARCHAR(50),           -- apollo | hunter | proxycurl
    email_verified BOOLEAN DEFAULT FALSE,
    person_type VARCHAR(50),            -- recruiter | hiring_manager | peer
    profile_data JSONB,                 -- Full enriched profile from Proxycurl/Apollo
    github_data JSONB,                  -- Repos, languages, recent activity
    source VARCHAR(50),                 -- apollo | proxycurl | github | manual
    apollo_id VARCHAR(100),              -- Apollo person ID for on-demand enrichment
    created_at TIMESTAMP DEFAULT NOW()
);
```

### messages
```sql
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    person_id UUID REFERENCES persons(id),
    job_id UUID REFERENCES jobs(id),
    channel VARCHAR(50) NOT NULL,       -- linkedin_note | linkedin_message | email
    message_type VARCHAR(50) NOT NULL,  -- initial | follow_up | thank_you
    subject VARCHAR(500),               -- For emails only
    body TEXT NOT NULL,
    ai_reasoning TEXT,                  -- Why the AI wrote what it wrote
    status VARCHAR(50) DEFAULT 'draft', -- draft | approved | sent
    approved_at TIMESTAMP,
    sent_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### outreach_logs
```sql
CREATE TABLE outreach_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    person_id UUID REFERENCES persons(id) NOT NULL,
    job_id UUID REFERENCES jobs(id),
    message_id UUID REFERENCES messages(id),
    status VARCHAR(50) DEFAULT 'draft', -- draft | sent | connected | responded | met | following_up | closed
    notes TEXT,
    last_contacted_at TIMESTAMP,
    next_follow_up_at TIMESTAMP,
    response_received BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### user_settings
```sql
CREATE TABLE user_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    min_message_gap_days INTEGER DEFAULT 7,
    min_message_gap_enabled BOOLEAN DEFAULT TRUE,
    follow_up_suggestion_enabled BOOLEAN DEFAULT TRUE,
    response_rate_warnings_enabled BOOLEAN DEFAULT TRUE,
    guardrails_acknowledged BOOLEAN DEFAULT FALSE, -- True after first toggle-off modal
    gmail_connected BOOLEAN DEFAULT FALSE,
    outlook_connected BOOLEAN DEFAULT FALSE,
    gmail_refresh_token TEXT,           -- Encrypted
    outlook_refresh_token TEXT,         -- Encrypted
    api_keys JSONB,                     -- Encrypted: {apollo, proxycurl, hunter, etc}
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

---

## External API Integration Map

### People Finding Flow
```
User targets a company/job
        │
        ├── Generic search (company name only)
        │         │
        │         ▼
        │   Apollo.io API ──→ Find people by company + title + seniority
        │
        └── Job-aware search (from saved job)
                  │
                  ▼
          extract_job_context(title, description)
                  │  → department, team_keywords, seniority
                  ▼
          Apollo.io API ──→ 3 targeted searches (department-filtered)
                  │         Recruiters: dept recruiter titles
                  │         Managers: team manager titles + seniority
                  │         Peers: team peer titles
                  │
                  ▼
          Fallback: If < 2 results, re-search without department filter
        │
        ▼
Proxycurl API ──→ Enrich selected profiles (full LinkedIn data)
        │
        ▼
GitHub API ──→ For engineers: find repos, languages, activity
        │
        ▼
Person records stored in DB
```

### Email Finding Waterfall
```
User clicks "Get Email" on a person card
        │
        ▼
Apollo Enrichment (/v1/people/match, 1 credit) ──→ Has email? ──→ Yes ──→ Done
        │                                              No
        ▼
Hunter.io (name + domain) ──→ Has email? ──→ Yes ──→ Done
        │                          No
        ▼
Proxycurl (LinkedIn enrichment) ──→ Has email? ──→ Yes ──→ Done
        │                               No
        ▼
Hunter.io (domain search fallback) ──→ Has email? ──→ Yes ──→ Done
        │                                   No
        ▼
Fallback to LinkedIn message only
```

Note: People discovery uses `/api/v1/mixed_people/api_search` (free, no credits, no emails).
Email enrichment is on-demand only — triggered by user clicking "Get Email".

### Job Sync Flow
```
Celery periodic task (every 6 hours)
        │
        ├──→ JSearch API ──→ Parse, fingerprint, dedup, store
        ├──→ Adzuna API ──→ Parse, fingerprint, dedup, store
        ├──→ ATS APIs (per watched company) ──→ Parse, store
        ├──→ GitHub SimplifyJobs repos ──→ Parse markdown tables, store
        ├──→ newgrad-jobs.com ──→ Scrape, parse, store
        ├──→ Dice API ──→ Parse, fingerprint, dedup, store
        └──→ Remotive/Jobicy ──→ Parse, fingerprint, dedup, store
                │
                ▼
        Score each new job against user profile
                │
                ▼
        Notify user of high-match opportunities
```

### Message Drafting Flow
```
User selects a person + goal
        │
        ▼
Gather context:
  - User profile (from DB)
  - Person profile (from DB)
  - Job description (from DB)
  - GitHub data (if engineer)
  - Prior outreach history (from DB)
        │
        ▼
Claude API ──→ Generate draft + reasoning
        │
        ▼
User reviews, edits, approves
        │
        ├──→ LinkedIn: Copy to clipboard
        └──→ Email: Stage as Gmail/Outlook draft OR copy
```

---

## Background Jobs (Celery)

| Task | Schedule | Purpose |
|------|----------|---------|
| `sync_jobs` | Every 6 hours | Pull new jobs from all sources |
| `enrich_companies` | On demand | Fetch company data when user targets a new company |
| `check_follow_ups` | Daily | Generate follow-up reminders for stale outreach |
| `score_new_jobs` | After each sync | Score new jobs against user profiles |

---

## Authentication Flow

```
User signs up/logs in via Supabase Auth
        │
        ▼
Frontend receives JWT + refresh token
        │
        ▼
Every API request includes: Authorization: Bearer <jwt>
        │
        ▼
FastAPI dependency validates JWT with Supabase
        │
        ▼
User ID extracted, scoped to their data only
```

### OAuth Flows (Gmail / Outlook)

```
User clicks "Connect Gmail"
        │
        ▼
Redirect to Google OAuth consent screen
        │
        ▼
User approves Gmail draft access
        │
        ▼
Backend receives auth code, exchanges for refresh token
        │
        ▼
Refresh token encrypted and stored in user_settings
        │
        ▼
When staging email draft: use refresh token to get access token, create draft via Gmail API
```

---

## API Cost Management

External APIs charge per call. Strategy:

- **Cache aggressively** — Apollo/Proxycurl results stored in DB, not re-fetched
- **Waterfall stops early** — Email finding stops at first verified result
- **User-triggered only** — People finding runs when user explicitly searches, not automatically
- **Job sync is batched** — One bulk call per source per sync cycle, not per job
- **Rate limiting** — Backend enforces per-user daily limits to prevent accidental cost spikes

---

## Error Handling Strategy

| Scenario | Behaviour |
|----------|-----------|
| Apollo API down | Show cached results if available, skip to Proxycurl for enrichment |
| No people found for company | Show message: "No profiles found. Try manual LinkedIn URL input." |
| Email waterfall finds nothing | Silently switch to LinkedIn message mode |
| Claude API fails | Show error, let user retry. Never auto-retry silently |
| Job source unavailable | Skip that source in sync, log warning, show other sources normally |
| Resume parsing fails | Show error, offer manual entry form as fallback |
