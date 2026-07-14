# Solomon Companion — manual test checklist

Auto-sync guard logic (Workstream D) has automated coverage: `node --test`
from the `extension/` directory loads the real background.js in a stubbed
environment and pins the "never over-scrape" decisions
(`tests/autosync.test.mjs`). Run it before every submission. Everything below
needs a real browser (chrome.* + live LinkedIn DOM).

Run this checklist before every store submission and after any change to
background.js / popup.js / app-bridge.js / linkedin-content.js.

Setup: load the build under test via `chrome://extensions` → Load unpacked
(`extension/` for dev, `extension/dist/prod` for a release candidate) in a
Chrome profile logged into LinkedIn.

## Connect / auth lifecycle

- [ ] Fresh install → popup shows "Not connected" + "Open NexusReach Settings"
      button opens the app (dev: localhost:5173; prod build: the app origin).
- [ ] App Settings → Connect Companion → popup flips to Connected and shows
      the profile card (name, roles, skills).
- [ ] `GET /api/companion/status` (or the Settings card) shows connected with
      a recent `created_at`.
- [ ] Reconnect: click Connect Companion again → still works (old token
      revoked, new one active; no duplicate-connected weirdness).
- [ ] Revocation: Settings → Disconnect Companion → next extension API call
      fails; toolbar icon shows the red "!" badge; popup shows the
      "Reconnect needed" banner; Open Settings → Connect clears the badge.
- [ ] Durability: leave the browser for >1 hour after connect → popup still
      Connected and profile refresh works (the old Supabase-JWT expiry bug).

## LinkedIn graph refresh

- [ ] Settings → Sync Now → connections tab opens, scrolls, follows tabs
      process, and Settings shows imported counts.
- [ ] Run it a 7th time in one day → clean "Daily LinkedIn sync limit"
      error (6/day cap), not a crash.

## Auto-cadence sync (Workstream D)

- [ ] Popup shows "Keep my network fresh automatically" toggle, default ON;
      toggling it persists (reopen popup → same state).
- [ ] Force an alarm run for testing: in the service-worker console,
      `chrome.storage.local.remove('lastAutoSyncAt')` then
      `chrome.alarms.create('nr-auto-sync',{when:Date.now()+1000})`. With an
      aged graph (>7 days) it runs in a BACKGROUND tab (never steals focus),
      cleans the tab up afterward, fires a "Network refreshed" notification,
      and Settings shows updated counts.
- [ ] With the toggle OFF, the same forced alarm does nothing.
- [ ] With a fresh graph (<7 days) or an empty graph, the forced alarm does
      nothing (no tab opens).
- [ ] Only one auto-run per 24h: immediately forcing a second alarm (without
      clearing lastAutoSyncAt) does nothing.
- [ ] Opportunistic nudge: set `days_since_sync` high (or wait), clear
      `lastAutoSyncAt`/`lastStalePromptAt`, visit any normal LinkedIn page →
      after ~4s a "Your network graph is N weeks old" panel appears with
      "Refresh now" (runs a foreground sync) and "Not now" (dismisses). It
      does NOT appear on the connections/following pages.

## Hiring-team capture

- [ ] On a LinkedIn job with "Meet the hiring team": capture stores the
      named contacts; they appear on the People page as verified.
- [ ] On a job without the panel: clean "no members" result, no error toast.

## Save to NexusReach (Workstream E)

- [ ] Visit any LinkedIn profile (`/in/...`) while connected → a bottom-right
      "Save to NexusReach" chip appears after a moment. Click Save → chip shows
      "Saved <name> ✓" and the contact appears on the People page with a
      "Captured from LinkedIn" chip; if a current employer was visible, the
      company shows as verified.
- [ ] Navigate to another profile (SPA nav, no reload) → the chip re-appears
      for the new person; navigate off `/in/` → the chip disappears.
- [ ] Save the same profile twice → no duplicate contact (upsert by URL).
- [ ] While NOT connected, the chip does not appear.

## Own-profile import (Workstream F)

- [ ] Onboarding "Connect your network" step (or trigger via the app) →
      "Import my LinkedIn profile" opens your own profile in a background tab,
      reads Experience/Education/Skills, and shows a review summary (name,
      headline, N positions/schools/skills) before saving.
- [ ] "Save to my profile" fills blank profile fields, adds skills, and
      populates experience/education (visible on the Profile page); it does
      NOT overwrite fields you already set.
- [ ] Sections it can't read fail soft with a warning, not an error.

## ATS autofill

- [ ] Greenhouse or Lever application form autofills from the profile with
      the toggle on; does nothing with the toggle off.

## Prod-build specifics (dist/prod only)

- [ ] manifest.json has no localhost entries; app-bridge matches the prod
      app origin; API origin present in host_permissions.
- [ ] config.js contains the prod origins.
- [ ] Connect from the production app works end-to-end (CORS: requires
      NEXUSREACH_COMPANION_EXTENSION_ORIGINS to include the extension ID).
