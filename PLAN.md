# NexusReach — Current Plan and Roadmap

Last updated: 2026-04-04

This file tracks what is already shipped, what is actively being hardened, and what still matters next.

## Product status

NexusReach already has a working end-to-end loop:
1. import or discover a job
2. find recruiters, hiring-side contacts, and peers
3. recover LinkedIn/public evidence
4. surface warm paths from imported first-degree LinkedIn connections
5. find or guess an email safely
6. draft outreach
7. track the relationship in CRM views

## Completed foundations

- [x] Frontend app shell with auth, routing, and protected pages
- [x] FastAPI backend with SQLAlchemy, Alembic, PostgreSQL, Redis, and Celery
- [x] Profile setup and resume parsing
- [x] Job board, tracker, and scoring
- [x] Outreach CRM and insights dashboard
- [x] Gmail and Outlook draft staging
- [x] Multi-provider LLM drafting

## Completed people-intelligence milestones

### Early people discovery
- [x] Apollo company/org enrichment
- [x] Proxycurl enrichment
- [x] GitHub engineer enrichment
- [x] manual LinkedIn enrichment flow

### Apollo-free and fallback evolution
- [x] Apollo free-tier company support
- [x] Google CSE fallback
- [x] Brave LinkedIn/public search fallback
- [x] SearXNG primary search-provider integration

### Job-aware discovery
- [x] `job_id`-driven people search
- [x] context extraction from job title + description
- [x] recruiter / manager / peer targeted search titles

### The Org and identity upgrades
- [x] bounded The Org traversal
- [x] trusted public-identity slug support
- [x] The Org slug validation and repair
- [x] stricter team-page verification
- [x] LinkedIn backfill for verified public candidates

### Contact quality and fallback improvements
- [x] early-career recruiter-first tuning
- [x] direct / adjacent / next-best hierarchy
- [x] same-company fallback ranking
- [x] `company_match_confidence` and `fallback_reason`
- [x] safe best-guess emails from approved domain signals
- [x] usefulness_score (0-100) combining team, title, level, rank, company, and source signals

### LinkedIn graph warm-path v1
- [x] separate `linkedin_graph_connections` and `linkedin_graph_sync_runs`
- [x] LinkedIn graph status + sync-session API
- [x] manual LinkedIn CSV/ZIP import fallback
- [x] People page `your_connections` section
- [x] per-person warm-path metadata in people search responses
- [x] bounded warm-path ranking boost that does not override safety gates
- [x] local browser connector that can scrape first-degree LinkedIn connections from a logged-in browser

## Completed job-ingestion milestones

- [x] Greenhouse board support
- [x] Lever board support
- [x] Ashby board support
- [x] Workable exact-job support
- [x] custom exact-job ingestion framework
- [x] Apple Jobs support
- [x] Workday exact-job support
- [x] generic exact-job fallback for metadata-rich proprietary career pages
- [x] high-accuracy `newgrad-jobs.com` detail-page enrichment
- [x] source-aware non-ATS dedupe using `source + external_id` and canonical URL
- [x] startup-first discover mode with startup-source tagging

## Completed infrastructure upgrades

- [x] free-first public-page retrieval (`httpx -> Crawl4AI -> Firecrawl`)
- [x] search-provider router
- [x] Serper integration
- [x] Tavily integration
- [x] Redis-backed search result caching
- [x] provider-order configuration by query family

## Completed UX/supporting improvements

- [x] saved contacts grouped by company on People
- [x] saved-contact company filter on People
- [x] saved-contact company filter on Messages
- [x] saved-contact company filter on Outreach
- [x] hide saved contacts during live people-search loading
- [x] LinkedIn Graph settings card
- [x] local connector command surface in Settings
- [x] Jobs country filter derived from `location`
- [x] Jobs startup filter and separate `Discover Startup Jobs` action
- [x] startup badges/source badges on Jobs, Job Detail, and Dashboard

## Current priorities

### P1
- [ ] Decide on the production-grade Wellfound path: stronger browser retrieval, sanctioned feed, or removal from the v1 source list
- [ ] Decide whether startup sources should remain manual-only or join saved-search/hourly refresh behavior
- [ ] Harden LinkedIn browser sync against more LinkedIn DOM variants and security-challenge flows
- [ ] Add warm-intro-aware drafting suggestions without changing the no-auto-send rule
- [ ] Add provider usage telemetry and easier cost/credit visibility

### P2
- [ ] Add separate “startup-first” vs “venture-backed” taxonomy before onboarding broader VC portfolio boards
- [ ] Add more first-class exact-job host adapters beyond Apple and Workday
- [ ] Improve company-identity disambiguation for overloaded short brands
- [ ] Add optional scheduled LinkedIn graph refresh on top of the current on-demand sync model

### P3
- [ ] Expand company-research surfaces using the existing public-web stack
- [ ] Revisit reminder/automation workflows once retrieval precision stabilizes
- [ ] Decide whether LinkedIn graph should inform dashboard insights beyond people-search ranking

## Near-term regression suite to keep healthy

- [ ] Zip ambiguous-company people search
- [ ] Whatnot early-career recruiter discovery
- [x] `newgrad-jobs.com` detail-page enrichment + hidden DOM stripping
- [x] startup source parser fixtures for YC, VentureLoop, Conviction, and Speedrun
- [x] startup tag merge into existing ATS jobs
- [x] startup filter / badge rendering on Jobs and Dashboard
- [ ] Apple exact-job import + people search
- [ ] Fortune Media vs Fortune Brands identity split
- [ ] Uber generic exact-job import + hierarchy output
- [ ] xAI hierarchy + safe best-guess email behavior
- [ ] LinkedIn graph direct-connection match ordering
- [ ] LinkedIn graph same-company bridge ordering without unsafe-company promotion

## Guiding principles

1. Keep humans in the loop. Draft and stage; never auto-send.
2. Prefer explicit same-company hierarchy over empty buckets.
3. Keep public identity trust separate from email-domain trust.
4. Keep imported LinkedIn graph data separate from CRM contacts and outreach-derived insights.
5. Reserve expensive providers for the narrowest, highest-value tasks.
6. Optimize for truthful output over aggressive guessing.
