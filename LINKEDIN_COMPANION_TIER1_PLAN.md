# LinkedIn Companion — Tier 1 Implementation Plan

Date: 2026-07-13
Status: in progress on branch `linkedin-companion-tier1` — Workstreams A–E
implemented (A: migration landed as `060_add_companion_tokens`; B: build
via `extension/build.mjs`, submission package in `extension/STORE_LISTING.md`;
C: Settings blessed-path card, onboarding `network` step, dashboard nudge —
the install CTA reads `VITE_COMPANION_INSTALL_URL`, unset until the store
listing is live; D: jittered weekly `chrome.alarms` background sync + in-page
staleness nudge, guarded by cooldown/staleness/interstitial checks, opt-out
popup toggle, `node --test` guard-logic coverage; E: `POST /api/people/
capture-linkedin-profile` companion-authed upsert + in-page "Save to
NexusReach" chip on `/in/` profiles + People-page "Captured from LinkedIn"
chip). F not started.
D deviation: the auto-sync opt-out toggle lives in the extension popup (its
state is extension-local), not the Settings card — the card links to it. This
avoids new app↔extension bridge plumbing that can't be verified without loading
the real extension.
Two deliberate B deviations: (1) the `alarms` permission is deferred to the
release that ships Workstream D — requesting an unused permission is a CWS
review rejection risk; (2) naming resolved to **Solomon Companion**, not
"NexusReach Companion" — Solomon is the user-facing brand on every launch
surface (landing, login, terms, privacy); NexusReach is the internal name.

Goal: make the Companion extension the single, near-zero-effort path for getting a user's
LinkedIn network and profile into NexusReach. No new integration channel is being built —
the extension already implements full graph sync (`extension/background.js`,
`NR_LINKEDIN_GRAPH_REFRESH`). Tier 1 is packaging, durability, and ambient automation.

Research context: no official LinkedIn API covers this for US/Canada users (OIDC = name/
email/photo only; the DMA Member Data Portability API is EEA+CH-only). Session-based API
vendors (Unipile) are rejected for graph import: server-held LinkedIn sessions violate our
"no LinkedIn credentials server-side" promise, cost ~$5/user/mo, and carry Proxycurl-class
vendor legal risk. Read-only extension capture of pages the user is already viewing is the
industry-standard, lowest-ban-risk pattern (Teal/Careerflow/Simplify).

---

## Current state (verified in code)

- `extension/` is an MV3 Chrome extension ("NexusReach Companion" v0.1.0) with:
  - Full graph refresh: opens connections + follows pages, DOM-scrapes up to
    `MAX_GRAPH_ITEMS = 2500` with auto-scroll, uploads via
    `POST /api/linkedin-graph/import-batch` / `import-follow-batch` (session-token-authed,
    900s TTL sessions from `POST /api/linkedin-graph/sync-session`).
  - Hiring-team capture, LinkedIn assist (open profile + page capture for known persons),
    ATS autofill, app bridge (`app-bridge.js` postMessage relay, localhost origins only).
- **Auth gap:** `connectCompanion()` (`frontend/src/lib/companion.ts:137`) passes the
  Supabase access JWT into extension storage. It expires in ~1h; `apiRequest` clears auth
  on 401 → "reconnect from Settings". The Companion is effectively disconnected within an
  hour of every connect. This blocks all background behavior.
- Settings LinkedIn Graph card (`frontend/src/pages/SettingsPage.tsx`) shows the extension
  buttons *and* raw `python scripts/linkedin_graph_connector.py ...` terminal commands to
  every user.
- Onboarding (`frontend/src/components/onboarding/OnboardingDialog.tsx`) steps:
  welcome → profile → goals → resume → completed. No network/Companion step.
- Manifest is dev-only: localhost API/app origins, not published to the Chrome Web Store.
- Naming drift: frontend toasts say "Solomon Companion"; manifest says "NexusReach
  Companion". Pick one before the store listing.

---

## Workstream A — Durable companion token (prerequisite for everything)

Replace the stored Supabase JWT with a long-lived, revocable, backend-minted token.

### Backend
1. Migration `060_add_companion_tokens`: table `companion_tokens`
   (`id` uuid PK, `user_id` FK users, `token_hash` text unique, `created_at`,
   `last_used_at` nullable, `expires_at`, `revoked_at` nullable).
   **Must `ALTER TABLE companion_tokens ENABLE ROW LEVEL SECURITY` in the same migration**
   (CLAUDE.md data-boundary rule).
2. Token format: `nrc_` + 32 random bytes base64url. Store SHA-256 hash only; return the
   plaintext once. Default expiry 180 days. Connecting again revokes prior active tokens
   (one active token per user — simplest revocation story).
3. New router `backend/app/routers/companion.py`:
   - `POST /api/companion/token` (Supabase-authed via `get_current_user_id`) → mints token,
     revokes previous ones, returns `{ token, expires_at }`.
   - `DELETE /api/companion/token` → revoke all (Settings "Disconnect Companion").
   - `GET /api/companion/status` → `{ connected, created_at, last_used_at, expires_at }`.
4. New dependency in `app/dependencies.py`: `get_companion_or_user_id` — if the bearer
   starts with `nrc_`, hash-lookup (reject revoked/expired, update `last_used_at` at most
   once per hour to avoid write amplification); otherwise delegate to the existing
   Supabase path. Apply it **only** to the endpoints the extension calls:
   - `POST /api/linkedin-graph/sync-session`, `GET /api/linkedin-graph/status`
   - `POST /api/people/hiring-team-capture`
   - `POST /api/people/{id}/linkedin-page-capture`
   - `GET /api/profile/autofill`
   - `POST /api/messages/{id}/copy`
   - new endpoints from Workstreams E/F
   (`import-batch`/`import-follow-batch` stay sync-session-token-authed as today.)
   All other routes keep `get_current_user_id` — companion tokens must not become a
   general-purpose credential.
5. Rate-limit `POST /api/linkedin-graph/sync-session` per user (e.g. 6/day) using the
   existing Redis rate-limit storage, so a buggy auto-sync can't hammer LinkedIn or us.

### Frontend
6. `connectCompanion()` calls `POST /api/companion/token` and passes the `nrc_` token (not
   the Supabase JWT) via `NR_EXTENSION_CONNECT`. Settings "Disconnect" calls the DELETE.
   Companion status card reads `GET /api/companion/status` (server truth) alongside the
   local ping.

### Extension
7. Store `companionToken` (drop `authToken` naming); on 401/403, do **not** silently wipe —
   set a `needsReconnect` flag, badge the toolbar icon, and surface "Reconnect from
   NexusReach Settings" in the popup.
8. Popup connect flow: replace the paste-a-token field with a "Connect via NexusReach"
   button that opens the app's Settings page (the app-bridge `NR_EXTENSION_CONNECT` does
   the rest). Keep a collapsed "advanced" manual field for dev.
9. Verify `app/utils/origins.py` allows the `chrome-extension://<prod-id>` origin for the
   prod API CORS config once the store ID is known.

Tests: pytest for mint/revoke/expiry/hash-only-at-rest, dependency accept/reject paths,
RLS enabled check (`scripts/verify_rls.py` pattern); vitest for the new connect flow.

Estimate: ~2 days.

---

## Workstream B — Production packaging + Chrome Web Store publish

Start this early: CWS review with `linkedin.com` host permissions can take 1–3 weeks.

1. **Build variants.** Add `extension/build.mjs` (or two manifests) producing:
   - `dev`: current localhost origins.
   - `prod`: app-bridge content script matched to the production Vercel app origin; API
     host permission for the Railway API origin; `DEFAULT_API_URL` → prod API (emitted into
     a generated `config.js`). Keep the popup's advanced API-URL override for dev.
2. Manifest hygiene: bump to `1.0.0`; add `alarms` permission (Workstream D); keep `tabs`
   (needed for `chrome.tabs.create`/`sendMessage` in graph refresh) with a written
   justification for review; finalize the single-purpose description ("assists your own
   job search: saves pages you view, refreshes your own network graph, autofills
   applications").
3. Naming: settled as **Solomon Companion** (the user-facing brand); the manifest
   and popup were renamed to match the frontend's existing strings.
4. Store listing package: icons already exist; add screenshots (Settings connect, graph
   sync result, hiring-team capture, ATS autofill), promo tile, privacy-policy URL
   (`/privacy` — **update it to describe extension data flows**: what is read from
   LinkedIn pages the user views, what is uploaded, no cookies/credentials collected).
   Complete the CWS data-use disclosures (collects personally identifiable info —
   names/titles/companies of connections; no browsing history sale; no credentials).
5. Submit for review behind "unlisted" first if we want a soft launch; flip to public at
   waitlist→launch.
6. Post-publish: pin the store URL in a shared constant (`frontend/src/lib/constants` or
   similar) for Workstream C CTAs.

Estimate: ~1.5 days of work + review lead time (submit at the end of week 1).

---

## Workstream C — Make the extension the blessed path (Settings + onboarding)

1. **Settings LinkedIn Graph card reorder** (`SettingsPage.tsx`):
   - Companion not detected → primary CTA "Install the Companion" (CWS link) + one-line
     value copy; secondary: "Upload LinkedIn export" (existing CSV/ZIP flow).
   - Detected but not connected → "Connect Companion" primary.
   - Connected → "Sync Now (Companion)" primary + last-sync freshness + auto-sync toggle
     (Workstream D).
   - Move the CLI connector commands (`buildLinkedInCdpCommand` / profile variant) behind a
     collapsed "Developer options" disclosure. Do not delete — it's the non-Chrome power
     path.
   - CSV fallback gets a deep-link button to
     `https://www.linkedin.com/mypreferences/d/download-my-data` with copy: "choose
     **Connections** only — the file is ready in ~10 minutes", plus the existing drag-drop.
2. **Onboarding `network` step** (new, between `resume` and `completed` in
   `OnboardingDialog.tsx`):
   - Detect Chrome/Edge desktop (feature-detect via `pingCompanion()` + UA heuristic for
     the install CTA); other browsers see the CSV path instead.
   - States: install → connect (one click, uses Workstream A flow) → "Import your network"
     (starts a sync session + `refreshLinkedInGraphInCompanion`, shows progress, non-
     blocking — user can hit Continue while it runs) → done.
   - Skippable; completion state feeds the existing dashboard first-win path.
3. **Dashboard nudge:** when `GET /api/linkedin-graph/status` shows an empty graph, show a
   "Connect your network — unlock warm paths" card linking to the onboarding step/Settings.

Tests: vitest for the card states (role-based queries — duplicated text is common in this
codebase) and the new onboarding step; update `SettingsPage.test.tsx`.

Estimate: ~1.5 days.

---

## Workstream D — Auto-cadence sync (zero-effort freshness)

Design constraint: hidden tabs get timer throttling (≥1s clamp immediately, intensive
throttling after ~5 min hidden), and ban-risk favors human-looking activity. Two
complementary mechanisms, both opt-out via one toggle ("Keep my network fresh
automatically", default ON after the first successful sync):

1. **Weekly alarm** (`chrome.alarms`, period 7d + random 0–24h jitter):
   - Check `GET /api/linkedin-graph/status` with the companion token; skip unless the graph
     is older than the threshold (7 days).
   - Run the existing `runGraphRefresh` flow with `chrome.tabs.create({ active: false })`
     so it never steals focus. Adapt `autoScroll` for hidden-tab mode: 1s step delays
     (matches the throttle clamp), hard wall-clock budget of ~4 minutes (finish before
     intensive throttling), accept partial capture with warnings — the import path already
     tolerates partial batches.
   - On completion: toolbar badge + optional `chrome.notifications` "Imported N
     connections".
   - On failure/blocked: badge "stale" state; next natural popup open shows a one-click
     "Refresh now" (foreground, current behavior).
2. **Opportunistic staleness prompt:** when the user naturally visits `linkedin.com` and
   the graph is >14 days old and an alarm run hasn't succeeded, `linkedin-content.js`
   shows the existing panel affordance: "Your NexusReach network graph is 3 weeks old —
   refresh now?" One click runs the refresh in that session (foreground, fast, human-
   present). This is the safest posture and covers users whose Chrome is rarely open when
   the alarm fires.
3. Server side: nothing new beyond Workstream A (sync-session creation with the companion
   token + the 6/day rate limit). The 15-min sync-session TTL
   (`NEXUSREACH_LINKEDIN_GRAPH_SYNC_SESSION_TTL_SECONDS=900`) comfortably covers a run.
4. Ban-risk guardrails: never more than one auto-run per 24h regardless of triggers; keep
   the 2,500-item cap; keep scroll pacing ≥ current values; abort immediately on any
   LinkedIn interstitial/captcha DOM signal (fail-soft, badge, wait for a human session).
   (Tier 2's delta-sync — stop at first already-known connection — will shrink auto-runs
   to one page; note it in code comments as the planned evolution.)

Tests: unit-test the staleness/threshold/budget logic by extracting it into a pure module
(`extension/lib/` if we introduce a build step anyway); manual checklist for alarm and
hidden-tab runs.

Estimate: ~1.5 days.

---

## Workstream E — Ambient capture ("Save to NexusReach" on any profile)

1. **Extension** (`linkedin-content.js`):
   - On `/in/*` pages (SPA URL-change watcher — verify/extend the existing navigation
     handling), render a compact "Save to NexusReach" button using the existing panel
     renderer. Read-only: name, headline, current title/company from the top card (+ first
     visible Experience entry when present), location, canonical profile URL. Nothing is
     fetched or expanded beyond what's on screen (same posture as hiring-team capture).
   - POST to the new endpoint below with the capture; show saved/duplicate state inline.
2. **Backend:** `POST /api/people/capture-linkedin-profile` (companion-token-authed via
   `get_companion_or_user_id`):
   - Upsert `Person` by `(user_id, linkedin_url)`; create/link `Company` by name.
   - Source string `companion_capture`; company verification maps to the existing
     page-capture vocabulary (the user personally viewed the live profile — treat like
     `linkedin_page_capture` evidence, not like a SERP guess). **Do not** touch email
     trust — email lookup stays in its own waterfall.
   - Respect data boundaries: this creates CRM rows (user-initiated save), never
     `linkedin_graph_connections` rows.
3. **Frontend:** People page shows a "Captured from LinkedIn" source chip (extend the
   `Person` source/verification unions in `frontend/src/types/people.ts` — remember the
   barrel/DOM-shadowing gotcha).
4. Stretch (explicitly optional, else it's Tier 2): "Save all visible" on
   `/search/results/people/` pages via a batch variant of the endpoint.

Tests: pytest for upsert/dedupe/verification mapping; vitest for the chip; manual
checklist for the in-page button across a few profile layouts.

Estimate: ~2 days.

---

## Workstream F — Own-profile import (onboarding without retyping)

1. **Extension:** new content handler `CAPTURE_SELF_PROFILE`:
   - Resolve own profile URL (existing `resolveSelfProfile`), navigate there, scrape top
     card + Experience + Education + Skills sections. Each section fails soft
     independently (LinkedIn DOM drift is a fact of life); return
     `{ headline, positions[], education[], skills[], linkedin_url, warnings[] }`.
2. **Backend:** `POST /api/profile/import-linkedin` (companion-or-user-authed):
   - Non-destructive merge into the user profile: fill blank fields, append unknown
     skills, store positions/education as structured history alongside the parsed-resume
     evidence. Never overwrite user-entered values silently.
   - Feed the affinity substrate: schools + past employers from this import join the
     resume-derived affinity used by people ranking (shared-school / past-employer
     warm-path annotations).
3. **Frontend:**
   - Onboarding `network` step (Workstream C) gains "Import my LinkedIn profile" after
     connect: runs the capture, shows an editable summary (prefills `ProfileStep`-shaped
     fields), saves on confirm.
   - Settings profile section gets the same button for existing users.
4. Data boundary: own-profile data → profile tables only. Not a `Person` row, not graph
   rows.

Tests: pytest for merge semantics (blank-fill, no-overwrite, affinity rows); vitest for
the review UI; manual capture checklist.

Estimate: ~2 days.

---

## Sequencing

| Phase | Items | Notes |
|---|---|---|
| 0 (days 1–2) | Workstream A | Blocks everything; ship behind no flag (strict superset of current auth) |
| 1 (days 3–5) | B + C in parallel | Submit CWS review at end of phase — longest external lead time |
| 2 (days 6–9) | D, then E, then F | D depends on A only; E/F depend on A + the B build step |

Total ≈ 8–10 dev-days + CWS review wait. Everything lands incrementally; no big-bang.

Pre-commit checklist per repo standard (`ruff check app tests conftest.py`, `pytest`,
`eslint`, `tsc -b`, `npm run test`, `npm run build`, e2e). Extension has no automated
harness today — keep a manual test checklist in `extension/TESTING.md` (new); optional
follow-up: Playwright `launchPersistentContext` + `--load-extension` smoke in `e2e/`.

## Risks & mitigations

- **CWS review friction** (linkedin.com host permission): single-purpose narrative +
  privacy policy accuracy are the two things reviewers reject on. Prepared in B. Submit
  early; unlisted first if needed.
- **LinkedIn DOM drift:** all scrapers fail soft per section and report warnings; selectors
  stay centralized in `linkedin-content.js`.
- **Ban risk:** all new capture is read-only on pages the user chose to view; auto-sync is
  capped (1/24h, jittered weekly, wall-clock budget, interstitial abort). Delta-sync in
  Tier 2 reduces this further.
- **Token theft from extension storage:** `nrc_` tokens are scoped to companion endpoints
  only, revocable, expiring, hashed at rest, one-active-per-user. Strictly better than
  today's stored Supabase JWT.
- **Non-Chrome users:** unchanged CSV path, now with a deep link; CLI stays for power
  users. Safari/Firefox ports are out of scope.

## Out of scope (deliberately)

Tier 2: incremental delta sync, connection-accepted detection, search-results bulk
capture, humanized scroll pacing overhaul. Tier 3: Sign In with LinkedIn, DMA portability
API (EEA), Unipile-class LinkedIn messaging, driving the official data export from the
extension.
