# NexusReach — Product Requirements Document

Last updated: 2026-04-04

This PRD reflects the current intended product behavior, including features that are already shipped and the rules they should continue to preserve.

## Vision

NexusReach helps a job seeker go from:
- a company they care about, or
- a specific job posting

to:
- the right humans to contact
- a usable warm path when one exists
- a safe way to reach them
- a high-quality draft message
- a clear history of prior outreach

The product should make networking systematic without making it robotic. The user remains the decision-maker at every step.

## Target users

- new grad software engineers
- interns looking for return offers or full-time roles
- early-career professionals trying to network more intentionally
- career switchers with weak first-degree networks
- experienced candidates who want a structured outreach workflow instead of ad hoc spreadsheets

## Product principles

1. Human in the loop: nothing is auto-sent.
2. Truthful over aggressive: it is better to label a contact as `next_best` than pretend certainty.
3. Same-company contact hierarchy beats empty output.
4. Verification and role fit are different concerns.
5. Email-domain trust and public-company identity trust are different concerns.
6. Imported relationship graph data must stay separate from CRM contact state and outreach analytics.

## Module 1: Profile and user context

The profile remains the grounding layer for all message generation and job scoring.

### Required capabilities
- resume upload and parsing
- bio and goals
- tone preference
- target roles, industries, locations, and company sizes
- portfolio links such as LinkedIn, GitHub, and personal website

### Product requirement
- every AI-generated draft must be grounded in explicit user data and visible target data
- the app should never fabricate personal details not present in the profile or discovered context

## Module 2: Job and company intake

Users should be able to start either from discovery or from an exact job posting URL.

### Supported job inputs
- aggregated job discovery from APIs and curated feeds
- `newgrad-jobs.com` discovery with detail-page enrichment for accurate metadata
- startup-first discovery from startup-specific sources
- board-backed ATS search:
  - Greenhouse
  - Lever
  - Ashby
- exact-job URL ingestion:
  - Workable
  - Apple Jobs
  - Workday exact-job URLs
  - proprietary careers pages when parseable metadata exists

### Startup-first discovery scope
- direct startup boards:
  - Y Combinator Jobs
  - VentureLoop
  - Wellfound (best-effort; may return zero when blocked)
- startup ecosystems that resolve into ATS/exact-job imports:
  - Conviction Jobs / Mixture of Experts
  - a16z Speedrun
- startup provenance should be stored in reserved job tags:
  - `startup`
  - `startup_source:<source_key>`

### Product requirements
- exact-job import must canonicalize tracked URLs and avoid duplicate jobs
- non-ATS sources such as `newgrad-jobs.com` should dedupe by `source + external_id`, then canonical URL, then fingerprint
- unsupported or broken pages should fail clearly instead of importing the wrong page
- imported jobs must be usable immediately in the `Find People` flow
- startup provenance must merge into an existing ATS/exact-job row on dedupe instead of creating a duplicate job

## Module 3: Company identity

Company identity is now a core system concern, not just enrichment metadata.

### Required behaviors
- normalize company names for matching and dedupe
- track trusted public identity slugs for public-web/The Org verification
- keep email-domain trust separate from public-identity trust
- protect against ambiguous brands such as short names that overlap with unrelated companies or people

### Product requirement
- same-company fallback contacts must still be blocked if there is conflicting employer evidence

## Module 4: People finder

This is the core differentiator of the product.

### Buckets
For any company or saved job, the system should surface:
- recruiters / talent
- hiring-side contacts
- peers

### Ranking hierarchy
Each bucket should be ranked in this order:
1. `direct`
2. `adjacent`
3. `next_best`

### Product requirements
- buckets should prefer same-company contacts even when the exact ideal person is not available
- lower-confidence same-company fallbacks must be labeled, not silently mixed with direct matches
- ranking may use warm-path metadata only after company-safety checks have already passed

### Job-aware search
When the user launches people search from a saved job:
- extract department, team keywords, seniority, and role-family titles
- search recruiters, managers, and peers differently
- use broader role-family fallbacks when exact context underfills

### Data sources and retrieval model
People discovery can use:
- Apollo company/org enrichment
- web search providers for LinkedIn x-ray and public discovery
- The Org traversal
- hiring-team search
- LinkedIn backfill for verified public candidates
- Proxycurl and GitHub enrichment where relevant

### Search provider requirements
- SearXNG should remain the default bulk provider because it is self-hosted and cheap to scale
- Brave should remain available because it is still strong for exact LinkedIn backfill
- bulk search should not depend exclusively on paid provider credits
- search should support provider fallback and caching

## Module 5: LinkedIn graph warm paths

The product should support a user-controlled warm-path layer without turning LinkedIn into a server-side auth dependency.

### Required behaviors
- import first-degree LinkedIn connection data in a user-scoped graph store separate from CRM contacts
- support manual LinkedIn export upload as a fallback
- support a local browser-sync flow that reads LinkedIn from the user's device and uploads only normalized rows
- surface `your_connections` at the target company in the People flow
- annotate contacts with direct-connection or same-company-bridge explanations when appropriate

### Safety requirements
- imported graph data must not bypass ambiguous-company protections
- imported graph data must not alter email trust rules
- imported graph data must not overwrite saved CRM `Person` rows
- the server must not store LinkedIn cookies, passwords, or session tokens

### v1 scope requirement
- LinkedIn graph data affects people-search ranking and explanation only
- dashboard outreach `warm_paths` remains based on real outreach history in v1
- message drafting does not yet depend on the graph in v1

## Module 6: Public-web verification

The product must separate:
- company verification
- role-fit ranking
- email trust

### Required behaviors
- current-company verification can rely on trusted public identity and LinkedIn/public evidence
- The Org person pages may verify current company when trusted slug matching succeeds
- team pages require stricter evidence than person pages
- public verification source should be surfaced as `public_web`

### Product requirements
- a contact may be useful as a `next_best` fallback even if current company is not fully verified
- a verified company match should not automatically imply a safe email domain

## Module 7: Email layer

### Desired outputs
Email lookup should return one of:
- `verified`
- `best_guess`
- `not_found`

### Product requirements
- verified emails should always outrank guesses
- best guesses are allowed only from approved domain signals
- ambiguous-company or unsafe-domain cases must still withhold guesses
- the UI should make it obvious when an email is usable but unverified

### User experience requirement
- if no safe email exists, the product should still leave the user with a LinkedIn/public-contact path when available

## Module 8: Message drafting

### Required message types
- LinkedIn connection note
- LinkedIn message
- professional email
- follow-up
- thank-you / post-conversation

### Product requirements
- drafts must incorporate:
  - user context
  - contact context
  - job/company context
  - prior outreach history
- provider choice should be abstracted so the product is not locked to one LLM vendor
- drafts may be staged into Gmail or Outlook, but never auto-sent

## Module 9: CRM and contact history

The CRM should ensure the user always knows:
- who they found
- why that person is relevant
- whether they already reached out
- what happened next

### Required behaviors
- contact history always visible before re-engagement
- status tracking for each relationship
- linkage between jobs, companies, people, messages, and outreach logs
- saved contacts should be filterable by company
- saved jobs should be filterable by country and startup status
- imported LinkedIn graph rows must stay outside the saved-contact CRM model

## Module 10: Insights and cost-awareness

The product should help the user network more intelligently over time.

### Required capabilities
- response-rate style analytics
- network-gap views
- warm-path visibility in people search
- company/job linkage across outreach

### Internal system requirements
- external-provider usage should be routed and cached to reduce cost burn
- expensive providers should be reserved for the narrowest, highest-value tasks
- outreach-derived insights and imported LinkedIn graph insights must remain conceptually separate until intentionally unified

## Non-functional requirements

- **Latency:** people search should degrade gracefully rather than fail hard when one provider is unavailable
- **Accuracy:** same-company misclassification is a higher-severity error than underfilling a bucket
- **Privacy:** all persisted data must remain scoped to `user_id`
- **Resilience:** exact-job pages and public pages should fail honestly when upstream providers are down
- **Transparency:** the UI should expose enough metadata that a user can tell whether a contact is direct, adjacent, next-best, verified, guessed, or supported by a warm path

## Guardrails

### Must preserve
- no automatic sending
- visible prior outreach history
- explicit labels for weaker evidence
- warnings rather than silent unsafe behavior
- no server-side storage of LinkedIn auth material

### Toggle philosophy
Guardrails are defaults, not locks. But safety-sensitive behaviors such as ambiguous-domain email guessing or unsafe same-company promotion must still be blocked even if the user wants more aggressive output.
