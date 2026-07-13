# Solomon Companion — manual test checklist

The extension has no automated harness (chrome.* APIs need a real browser).
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

- [ ] Settings → Refresh in Companion → connections tab opens, scrolls,
      follows tabs process, and Settings shows imported counts.
- [ ] Run it a 7th time in one day → clean "Daily LinkedIn sync limit"
      error (6/day cap), not a crash.

## Hiring-team capture

- [ ] On a LinkedIn job with "Meet the hiring team": capture stores the
      named contacts; they appear on the People page as verified.
- [ ] On a job without the panel: clean "no members" result, no error toast.

## ATS autofill

- [ ] Greenhouse or Lever application form autofills from the profile with
      the toggle on; does nothing with the toggle off.

## Prod-build specifics (dist/prod only)

- [ ] manifest.json has no localhost entries; app-bridge matches the prod
      app origin; API origin present in host_permissions.
- [ ] config.js contains the prod origins.
- [ ] Connect from the production app works end-to-end (CORS: requires
      NEXUSREACH_COMPANION_EXTENSION_ORIGINS to include the extension ID).
