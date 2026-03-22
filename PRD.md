# NexusReach — Product Requirements Document

Last updated: 2026-03-22

This PRD reflects the current intended product behavior, including features that are already shipped and the operating rules they should continue to preserve.

## Vision

NexusReach helps a job seeker go from:
- a company they care about, or
- a specific job posting

to:
- the right humans to contact
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
- board-backed ATS search:
  - Greenhouse
  - Lever
  - Ashby
- exact-job URL ingestion:
  - Workable
  - Apple Jobs
  - Workday exact-job URLs
  - proprietary careers pages when parseable metadata exists

### Product requirements
- exact-job import must canonicalize tracked URLs and avoid duplicate jobs
- unsupported or broken pages should fail clearly instead of importing the wrong page
- imported jobs must be usable immediately in the `Find People` flow

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

### Product requirement
- buckets should prefer same-company contacts even when the exact ideal person is not available
- lower-confidence same-company fallbacks must be labeled, not silently mixed with direct matches

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
- Brave should remain available because it is strong for exact LinkedIn backfill
- bulk search should not depend exclusively on Brave credits
- search should support provider fallback and caching

## Module 5: Public-web verification

The product must separate:
- company verification
- role-fit ranking
- email trust

### Required behaviors
- current-company verification can rely on trusted public identity and LinkedIn/public evidence
- The Org person pages may verify current company when trusted slug matching succeeds
- team pages require stricter evidence than person pages
- public verification source should be surfaced as `public_web`

### Product requirement
- a contact may be useful as a `next_best` fallback even if current company is not fully verified
- a verified company match should not automatically imply a safe email domain

## Module 6: Email layer

### Desired outputs
Email lookup should return one of:
- `verified`
- `best_guess`
- `not_found`

### Product requirement
- verified emails should always outrank guesses
- best guesses are allowed only from approved domain signals
- ambiguous-company or unsafe-domain cases must still withhold guesses
- the UI should make it obvious when an email is usable but unverified

### User experience requirement
- if no safe email exists, the product should still leave the user with a LinkedIn/public-contact path when available

## Module 7: Message drafting

### Required message types
- LinkedIn connection note
- LinkedIn message
- professional email
- follow-up
- thank-you / post-conversation

### Product requirement
- drafts must incorporate:
  - user context
  - contact context
  - job/company context
  - prior outreach history
- provider choice should be abstracted so the product is not locked to one LLM vendor
- drafts may be staged into Gmail or Outlook, but never auto-sent

## Module 8: CRM and contact history

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

## Module 9: Insights and cost-awareness

The product should help the user network more intelligently over time.

### Required capabilities
- response-rate style analytics
- network-gap views
- warm-path visibility
- company/job linkage across outreach

### Internal system requirement
- external-provider usage should be routed and cached to reduce cost burn
- expensive search providers should be reserved for the narrowest, highest-value tasks

## Non-functional requirements

- **Latency:** people search should degrade gracefully rather than fail hard when one provider is unavailable
- **Accuracy:** same-company misclassification is a higher-severity error than underfilling a bucket
- **Privacy:** all persisted data must remain scoped to `user_id`
- **Resilience:** exact-job pages and public pages should fail honestly when upstream providers are down
- **Transparency:** the UI should expose enough metadata that a user can tell whether a contact is direct, adjacent, next-best, verified, or guessed

## Guardrails

### Must preserve
- no automatic sending
- visible prior outreach history
- explicit labels for weaker evidence
- warnings rather than silent unsafe behavior

### Toggle philosophy
Guardrails are defaults, not locks. But safety-sensitive behaviors such as ambiguous-domain email guessing must still be blocked even if the user wants more aggressive output.
