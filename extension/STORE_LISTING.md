# Solomon Companion — Chrome Web Store submission package

Everything needed to build, submit, and maintain the extension listing.
See `LINKEDIN_COMPANION_TIER1_PLAN.md` (Workstream B) for context.

## Before you build

Run the auto-sync guard tests: `cd extension && node --test`. All must pass
(`tests/autosync.test.mjs`).

## Build the production package

```bash
NR_APP_ORIGIN=https://<vercel-production-domain> \
NR_API_ORIGIN=https://<railway-api-domain> \
node extension/build.mjs
```

Output: `extension/dist/prod/` (unpacked, for a final local smoke test via
`chrome://extensions` → Load unpacked) and
`extension/dist/solomon-companion-v<version>.zip` (upload this to the store).
The committed source tree stays the dev build (localhost origins) and keeps
working unpacked for development.

Version bumps: edit `manifest.json` `version` — the zip name follows it. The
store rejects re-uploads of an existing version number.

## Listing copy

- **Name:** Solomon Companion
- **Summary (≤132 chars):** Solomon job-search companion: capture hiring
  teams from pages you view, sync your own LinkedIn network, autofill
  applications.
- **Category:** Productivity → Workflow & Planning
- **Description (long):**

  > Solomon Companion connects your browser to your Solomon account
  > (job-seeker networking assistant) so the manual parts of a job search
  > disappear:
  >
  > - **Hiring-team capture** — when a LinkedIn job posting shows "Meet the
  >   hiring team", one click saves those exact recruiters and hiring
  >   managers to your Solomon contacts.
  > - **Your network, imported** — refresh your own first-degree LinkedIn
  >   connections into Solomon so it can spot warm paths to the companies
  >   you're targeting. Runs only when you start it; only normalized
  >   name/title/company rows are uploaded.
  > - **Application autofill** — fills job applications on Greenhouse,
  >   Lever, Ashby, Workable, Workday, and Apple Jobs from your Solomon
  >   profile.
  >
  > The companion is read-only on LinkedIn: it never sends invites, likes,
  > or messages on your behalf, never automates activity, and never
  > collects your LinkedIn password or cookies. It only reads pages you
  > choose to view or syncs you explicitly start.

- **Single-purpose statement:** Assists the user's own job search by
  connecting their browser to their Solomon account: capturing job-page and
  profile contact information the user is viewing, importing the user's own
  LinkedIn connections with their consent, and autofilling job applications.

## Permission justifications (reviewer form)

| Permission | Justification |
|---|---|
| `storage` | Stores the user's Solomon companion token, API endpoint, and cached profile for autofill. |
| `activeTab` / `tabs` | Opens and reads the user-initiated tabs used for hiring-team capture and the user-started network sync; opens the Solomon app from the popup. |
| `alarms` | Schedules the optional weekly background refresh of the user's own imported network graph (opt-out, default on). |
| `notifications` | Tells the user when a background network refresh finished (e.g. "Imported N connections"), since it runs without a visible tab. |
| `https://www.linkedin.com/*` | Reads the "Meet the hiring team" panel on job postings the user is viewing and, when the user starts (or has opted into) a sync, the user's own connections list. Read-only; no automated actions (no invites, likes, messages); no credential or cookie access. |
| ATS hosts (`boards.greenhouse.io`, `jobs.lever.co`, `jobs.ashbyhq.com`, `apply.workable.com`, `*.myworkdayjobs.com`, `jobs.apple.com`, `*.careers-page.com`) | Autofills the user's own job applications from their Solomon profile. |
| API origin (`https://<railway-api-domain>/*`) | Syncs captured data with the user's own Solomon account. |

The optional weekly refresh is read-only and heavily rate-limited (at most one
run per 24h, only when the user's graph has aged past a week, always in a
background tab with a wall-clock budget, aborting on any LinkedIn
interstitial). It is opt-out from the extension popup.

## Data-use disclosures (Privacy tab)

- Collects: **personally identifiable information** (names, job titles,
  employers of the user's own connections and of contacts the user chooses to
  save), **authentication information** (the Solomon-issued companion token —
  never the user's LinkedIn credentials), **website content** (job-posting
  pages the user captures).
- Not collected: browsing history, location, financial info, health info,
  personal communications.
- Certify: data is not sold; not used for purposes unrelated to the single
  purpose; not used for creditworthiness/lending.
- **Privacy policy URL:** `https://<vercel-production-domain>/privacy`
  (the policy's "Browser Companion Extension" section covers the extension's
  data flows — keep it in sync with any capability change).

## Assets checklist

- [x] Icons 16/48/128 (`icons/`)
- [ ] Screenshots, 1280×800 (4 suggested): Settings connect card; hiring-team
  capture panel on a job posting; network sync result toast; ATS autofill in
  action
- [ ] Small promo tile 440×280 (optional but recommended)

## Submission steps

1. Build (above), smoke-test `dist/prod` unpacked in a clean Chrome profile
   against production (see `TESTING.md`).
2. Chrome Web Store Developer Dashboard → New item → upload the zip.
3. Fill listing copy, permission justifications, and data disclosures from
   this file.
4. **Visibility: Unlisted** for the pre-launch period; flip to Public at
   waitlist launch.
5. Reviewer notes (paste into the review notes field):

   > This extension is a companion to the user's own Solomon account (job
   > search assistant). On linkedin.com it is strictly read-only and
   > user-initiated: it captures the "Meet the hiring team" panel of a job
   > posting the user is viewing, and imports the user's own first-degree
   > connections when the user clicks sync in our app. It performs no
   > automated LinkedIn actions (no invites, likes, messages, or background
   > crawling) and never accesses LinkedIn credentials or cookies. A test
   > account for the Solomon app can be provided on request.

6. Expect 1–3 weeks review for linkedin.com host permissions.

## After publication

1. Note the extension ID from the dashboard.
2. Set on Railway (web service):
   `NEXUSREACH_COMPANION_EXTENSION_ORIGINS=["chrome-extension://<id>"]`
   (feeds CORS/OAuth origin allowlisting — `app/utils/origins.py`).
3. Set `VITE_COMPANION_INSTALL_URL=<store listing URL>` on the Vercel frontend
   build — the Settings and onboarding install CTAs hide themselves while it
   is unset.
4. Update `DEPLOYMENT_RUNBOOK.md` secrets/domains checklist with both values.
