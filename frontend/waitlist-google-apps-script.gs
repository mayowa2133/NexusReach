/**
 * NexusReach pre-launch waitlist → Google Sheet.
 *
 * This is a standalone signup sink that needs NO Supabase, NO Railway, NO
 * database — just a Google Sheet. The landing-page waitlist form POSTs here and
 * each submission appends a row.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * ONE-TIME SETUP
 * ─────────────────────────────────────────────────────────────────────────────
 * 1. Create a Google Sheet (e.g. "NexusReach Waitlist"). Leave the first tab
 *    as-is (this script writes to whatever the first/"Waitlist" tab is and adds
 *    a header row automatically on the first signup).
 * 2. In the Sheet: Extensions → Apps Script. Delete any boilerplate, paste this
 *    entire file, and click Save (💾).
 * 3. Deploy → New deployment → gear icon → "Web app".
 *      - Description:      NexusReach waitlist
 *      - Execute as:       Me (your Google account)
 *      - Who has access:   Anyone            ← required; the form is anonymous
 *    Click Deploy, then Authorize access and allow the permissions.
 * 4. Copy the "Web app URL" (ends in `/exec`).
 * 5. In Vercel (frontend project) → Settings → Environment Variables, add:
 *      VITE_WAITLIST_ENDPOINT = <that /exec URL>
 *    Redeploy the frontend. Signups now land in the Sheet.
 *
 * To change the script later, edit + Save, then Deploy → Manage deployments →
 * edit the existing deployment → Version: "New version" → Deploy (keeps the
 * same URL so you don't have to touch Vercel again).
 *
 * The endpoint URL is not a secret (the form is public), so it's fine in a
 * VITE_ env var.
 */

function doPost(e) {
  var lock = LockService.getScriptLock();
  try {
    lock.waitLock(10000); // serialize appends so concurrent signups can't clash
  } catch (lockErr) {
    return _json({ ok: false, error: 'busy' });
  }

  try {
    var data = {};
    if (e && e.postData && e.postData.contents) {
      data = JSON.parse(e.postData.contents);
    }

    var name = String(data.name || '').trim();
    var email = String(data.email || '').trim();
    if (!name || !email) {
      return _json({ ok: false, error: 'name and email are required' });
    }

    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = ss.getSheetByName('Waitlist') || ss.getSheets()[0];

    // Add a header row the first time.
    if (sheet.getLastRow() === 0) {
      sheet.appendRow([
        'Timestamp', 'Name', 'Email', 'LinkedIn',
        'Current role', 'Looking for', 'Note', 'Source',
      ]);
    }

    // De-dupe by email (column 3) so a repeat submit doesn't add a second row.
    var emailKey = email.toLowerCase();
    var lastRow = sheet.getLastRow();
    if (lastRow > 1) {
      var existing = sheet.getRange(2, 3, lastRow - 1, 1).getValues();
      for (var i = 0; i < existing.length; i++) {
        if (String(existing[i][0]).trim().toLowerCase() === emailKey) {
          return _json({ ok: true, already: true });
        }
      }
    }

    sheet.appendRow([
      new Date(),
      name,
      email,
      String(data.linkedin_url || ''),
      String(data.current_title || ''),
      String(data.target_role || ''),
      String(data.note || ''),
      String(data.source || ''),
    ]);

    return _json({ ok: true });
  } catch (err) {
    return _json({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

// A GET on the URL just confirms the endpoint is live (handy to sanity-check
// the deployment in a browser).
function doGet() {
  return _json({ ok: true, service: 'nexusreach-waitlist' });
}

function _json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
