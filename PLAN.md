# NexusReach — Current Plan and Roadmap

Last updated: 2026-03-22

This file is no longer a speculative greenfield checklist. It now tracks what is already shipped and what still matters next.

## Product status

NexusReach already has a working end-to-end loop:
1. import or discover a job
2. find recruiters, hiring-side contacts, and peers
3. recover LinkedIn/public evidence
4. find or guess an email safely
5. draft outreach
6. track the relationship in CRM views

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

## Completed job-ingestion milestones

- [x] Greenhouse board support
- [x] Lever board support
- [x] Ashby board support
- [x] Workable exact-job support
- [x] custom exact-job ingestion framework
- [x] Apple Jobs support
- [x] Workday exact-job support
- [x] generic exact-job fallback for metadata-rich proprietary career pages

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

## Current priorities

### P1
- [ ] Improve hiring-manager precision for large engineering orgs
- [ ] Increase peer recall for broad roles without drifting into noisy adjacent titles
- [ ] Reduce cross-bucket duplicates when one same-company fallback qualifies for multiple buckets

### P2
- [ ] Add more first-class exact-job host adapters beyond Apple and Workday
- [ ] Improve company-identity disambiguation for overloaded short brands
- [ ] Add provider usage telemetry and easier cost/credit visibility

### P3
- [ ] Add optional self-hosted search fallback behind the router if vendor-cost pressure remains
- [ ] Expand company-research surfaces using the existing public-web stack
- [ ] Revisit background sync/reminder automation once retrieval precision stabilizes

## Near-term regression suite to keep healthy

- [ ] Zip ambiguous-company people search
- [ ] Whatnot early-career recruiter discovery
- [ ] Apple exact-job import + people search
- [ ] Fortune Media vs Fortune Brands identity split
- [ ] Uber generic exact-job import + hierarchy output
- [ ] xAI hierarchy + safe best-guess email behavior

## Guiding principles

1. Keep humans in the loop. Draft and stage; never auto-send.
2. Prefer explicit same-company hierarchy over empty buckets.
3. Keep public identity trust separate from email-domain trust.
4. Reserve expensive providers for the narrowest, highest-value tasks.
5. Optimize for truthful output over aggressive guessing.
