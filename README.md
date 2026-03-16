# NexusReach

**A smart personal networking assistant for job seekers.**

NexusReach takes you from "I want to work at Company X" to a thoughtful, human-approved message ready to send. It solves the LinkedIn black hole problem — where connections are shallow, applications vanish, and networking feels like a guessing game.

Networking is still the #1 way people land jobs, yet most job seekers — especially new grads and career switchers — have no system for it. NexusReach makes networking systematic without making it fake. **The human is always in the loop.**

---

## Why NexusReach?

Most job seekers face the same frustrations:

- **Cold applications disappear** — submitting resumes into applicant tracking systems yields single-digit response rates
- **Networking feels aimless** — who do you reach out to? What do you say? How do you follow up?
- **Generic outreach gets ignored** — copy-paste templates are obvious and ineffective
- **No system for tracking** — conversations fall through the cracks without a personal CRM

NexusReach addresses all of these by combining people intelligence, AI-powered message drafting, and outreach tracking into one workflow. It finds the right people at target companies, drafts personalized messages grounded in real context (your background, their role, shared interests), and tracks every conversation so nothing slips.

---

## Features

### Profile & Resume Parsing
Upload your resume (PDF/DOCX) and it gets auto-parsed into structured data — skills, experience, education, projects. Add your bio, goals, tone preference, and target roles. This profile feeds every AI-generated message.

### Job & Company Intelligence
Search jobs from multiple aggregators (JSearch, Adzuna), score them against your profile, and track opportunities through a Kanban board (Discovered → Applied → Interviewing → Offer). Built-in deduplication collapses the same job posted across multiple boards.

### People Finder
Enter a company name and find the right humans to connect with — recruiters, hiring managers, and potential teammates. Pulls from Apollo.io (275M+ profiles), Proxycurl (LinkedIn enrichment), and GitHub (engineer activity). Categorizes contacts by type so you know who to prioritize.

### AI Message Drafting
Claude generates personalized outreach grounded in real context: your profile, the target person's background, their GitHub activity (for engineers), and the specific job. Supports LinkedIn connection notes, LinkedIn messages, professional emails, follow-ups, and thank-you messages. Every draft shows *why* the AI wrote what it wrote.

### Email Layer
Finds work emails through a waterfall (Apollo → Hunter → Proxycurl), verifies them, and stages drafts directly in your Gmail or Outlook inbox via OAuth. Falls back to LinkedIn message format if no email is found. **Nothing is ever sent automatically.**

### Outreach Tracker (Personal CRM)
Track every contact through their lifecycle: Draft → Sent → Connected → Responded → Met → Following Up. Get follow-up reminders, response rate analytics, and a full timeline of your networking activity. Every contact links back to the job that prompted the outreach.

### Insights Dashboard
See what's working: response rates by message type, which outreach angles get replies, network growth over time, and network gaps. Identifies warm paths — existing connections who work at target companies.

### Outreach Guardrails
Sensible defaults protect you from common mistakes: 7-day minimum gap between messages to the same person, follow-up suggestions, response rate warnings. Contact history is always shown before re-engaging someone. Guardrails are toggleable (with warnings), never hard blocks.

---

## Tech Stack

### Frontend
- **React 18** + **TypeScript** with **Vite**
- **Shadcn/ui** component library + **Tailwind CSS**
- **TanStack Query** for server state (caching, background refetching)
- **Zustand** for client state management
- **React Router** for navigation

### Backend
- **Python 3.12** + **FastAPI** (async)
- **SQLAlchemy** ORM + **Alembic** migrations
- **PostgreSQL** (Supabase hosted)
- **Celery** + **Redis** for background jobs
- **Pydantic** for request/response validation

### External Services
- **Supabase** — Authentication + PostgreSQL hosting
- **Apollo.io** — People search + work emails
- **Proxycurl** — LinkedIn profile enrichment
- **Hunter.io** — Email finding + verification
- **GitHub API** — Engineer profiles + repos
- **JSearch (RapidAPI)** + **Adzuna** — Job aggregation
- **Claude API (Anthropic)** — AI message drafting
- **Gmail API** + **Microsoft Graph API** — Email draft staging

### Infrastructure
- **Vercel** — Frontend hosting
- **Railway** — Backend + Redis + Celery workers
- **GitHub Actions** — CI/CD pipeline

---

## Project Structure

```
NexusReach/
├── frontend/                # React + Vite application
│   ├── src/
│   │   ├── components/      # UI components organized by module
│   │   ├── hooks/           # Custom React hooks
│   │   ├── lib/             # API client, utilities
│   │   ├── stores/          # Zustand state stores
│   │   ├── types/           # TypeScript type definitions
│   │   └── pages/           # Route page components
│   └── package.json
├── backend/                 # FastAPI application
│   ├── app/
│   │   ├── routers/         # API route handlers (thin)
│   │   ├── services/        # Business logic layer
│   │   ├── clients/         # External API wrappers
│   │   ├── models/          # SQLAlchemy models
│   │   ├── schemas/         # Pydantic schemas
│   │   ├── middleware/       # Error handling, rate limiting
│   │   ├── tasks/           # Celery background tasks
│   │   └── utils/           # Helpers (dedup, scoring, parsing)
│   ├── alembic/             # Database migrations
│   └── tests/               # pytest test suite
├── e2e/                     # Playwright end-to-end tests
├── .github/workflows/       # CI/CD pipeline
├── PRD.md                   # Product requirements document
├── architecture.md          # System design + data models
└── PLAN.md                  # Build roadmap + progress
```

---

## Getting Started

### Prerequisites

- **Node.js 20+** and **npm**
- **Python 3.12+**
- **PostgreSQL** (or a Supabase project)
- **Redis** (for Celery background jobs)

### Backend Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Copy .env.example to .env and fill in your API keys
cp .env.example .env

# Run database migrations
alembic upgrade head

# Start the API server
uvicorn app.main:app --reload   # Runs on port 8000
```

### Frontend Setup

```bash
cd frontend
npm install

# Copy .env.example to .env and configure
cp .env.example .env

# Start the dev server
npm run dev                     # Runs on port 5173
```

### Background Workers (optional, for async tasks)

```bash
cd backend
celery -A app.tasks worker --loglevel=info
celery -A app.tasks beat --loglevel=info
```

### Running Tests

```bash
# Backend tests
cd backend && pytest -v

# Frontend tests
cd frontend && npx vitest run

# E2E tests (requires frontend dev server)
cd e2e && npx playwright test
```

---

## Environment Variables

### Backend (`backend/.env`)

| Variable | Description |
|----------|-------------|
| `NEXUSREACH_DATABASE_URL` | PostgreSQL connection string (asyncpg) |
| `NEXUSREACH_REDIS_URL` | Redis connection string |
| `NEXUSREACH_SUPABASE_URL` | Supabase project URL |
| `NEXUSREACH_SUPABASE_KEY` | Supabase service role key |
| `NEXUSREACH_APOLLO_API_KEY` | Apollo.io API key |
| `NEXUSREACH_PROXYCURL_API_KEY` | Proxycurl API key |
| `NEXUSREACH_HUNTER_API_KEY` | Hunter.io API key |
| `NEXUSREACH_GITHUB_TOKEN` | GitHub personal access token |
| `NEXUSREACH_JSEARCH_API_KEY` | RapidAPI key for JSearch |
| `NEXUSREACH_ADZUNA_APP_ID` | Adzuna application ID |
| `NEXUSREACH_ADZUNA_API_KEY` | Adzuna API key |
| `NEXUSREACH_ANTHROPIC_API_KEY` | Anthropic (Claude) API key |
| `NEXUSREACH_GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `NEXUSREACH_GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `NEXUSREACH_MICROSOFT_CLIENT_ID` | Microsoft OAuth client ID |
| `NEXUSREACH_MICROSOFT_CLIENT_SECRET` | Microsoft OAuth client secret |

### Frontend (`frontend/.env`)

| Variable | Description |
|----------|-------------|
| `VITE_API_URL` | Backend API URL (e.g., `http://localhost:8000`) |
| `VITE_SUPABASE_URL` | Supabase project URL |
| `VITE_SUPABASE_ANON_KEY` | Supabase anonymous/public key |

---

## Architecture Highlights

- **Modular monolith** — All backend modules in one FastAPI app. Simpler to develop and deploy; can split into microservices later if needed.
- **Human always in the loop** — No message is ever sent automatically. The tool drafts; the user reviews, edits, and approves.
- **Email waterfall stops early** — Apollo → Hunter → Proxycurl. First verified email wins. Falls back to LinkedIn if nothing is found.
- **External API results cached** — Apollo/Proxycurl data stored in DB. Never re-fetches the same profile twice.
- **All data scoped to user_id** — Every database query includes user_id. No data leaks between accounts.
- **Rate limiting** — Tiered limits by endpoint type (expensive AI calls, standard writes, reads) keyed by authenticated user.
- **API cost tracking** — Per-user daily usage tracking with configurable limits to prevent runaway API costs.

---

## License

This project is for personal/educational use.
