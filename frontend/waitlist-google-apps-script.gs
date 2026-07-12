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
    var email = String(data.email || '').trim().toLowerCase();
    if (!name || !_validEmail(email)) {
      return _json({ ok: false, error: 'name and email are required' });
    }
    if (name.length > 120 || email.length > 254 ||
        String(data.linkedin_url || '').length > 500 ||
        String(data.current_title || '').length > 200 ||
        String(data.target_role || '').length > 200 ||
        String(data.note || '').length > 2000) {
      return _json({ ok: false, error: 'input is too long' });
    }

    // Apps Script does not expose a trustworthy client IP. Enforce global
    // minute/day ceilings under the script lock so anonymous abuse is bounded.
    if (!_consumeQuota()) {
      return _json({ ok: false, error: 'rate limit exceeded' });
    }

    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = ss.getSheetByName('Waitlist') || ss.getSheets()[0];

    // Add a header row the first time.
    if (sheet.getLastRow() === 0) {
      sheet.appendRow([
        'Timestamp', 'Name', 'Email', 'LinkedIn',
        'Current role', 'Looking for', 'Note', 'Source', 'Email hash',
      ]);
    } else if (!sheet.getRange(1, 9).getValue()) {
      sheet.getRange(1, 9).setValue('Email hash');
    }

    // Hash-index new submissions in a dedicated column. For rows created by an
    // older deployment, fall back to a server-side exact email search.
    var emailHash = _emailHash(email);
    var hashMatch = sheet.getRange('I:I').createTextFinder(emailHash)
      .matchCase(true).matchEntireCell(true).findNext();
    if (hashMatch) {
      return _json({ ok: true, already: true });
    }
    var existing = sheet.getRange('C:C').createTextFinder(email)
      .matchCase(false).matchEntireCell(true).findNext();
    if (existing) {
      return _json({ ok: true, already: true });
    }

    sheet.appendRow([
      new Date(),
      _sheetText(name),
      _sheetText(email),
      _sheetText(data.linkedin_url),
      _sheetText(data.current_title),
      _sheetText(data.target_role),
      _sheetText(data.note),
      _sheetText(data.source),
      emailHash,
    ]);

    return _json({ ok: true });
  } catch (err) {
    console.error('waitlist submission failed', err);
    return _json({ ok: false, error: 'submission failed' });
  } finally {
    lock.releaseLock();
  }
}

function _sheetText(value) {
  var text = String(value || '').replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '');
  // Neutralize spreadsheet formulas in every user-controlled cell.
  if (/^[\s]*[=+\-@]/.test(text)) text = "'" + text;
  return text;
}

function _validEmail(email) {
  return /^[^\s@]{1,64}@[^\s@]{1,189}\.[^\s@]{2,63}$/.test(email);
}

function _emailHash(email) {
  var digest = Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256,
    email,
    Utilities.Charset.UTF_8
  );
  return digest.map(function (b) {
    var value = (b + 256) % 256;
    return ('0' + value.toString(16)).slice(-2);
  }).join('');
}

function _consumeQuota() {
  var properties = PropertiesService.getScriptProperties();
  var now = new Date();
  var minuteKey = 'quota:minute:' + Utilities.formatDate(now, 'UTC', 'yyyyMMddHHmm');
  var dayKey = 'quota:day:' + Utilities.formatDate(now, 'UTC', 'yyyyMMdd');
  var minuteCount = Number(properties.getProperty(minuteKey) || '0');
  var dayCount = Number(properties.getProperty(dayKey) || '0');
  if (minuteCount >= 30 || dayCount >= 1000) return false;
  properties.setProperty(minuteKey, String(minuteCount + 1));
  properties.setProperty(dayKey, String(dayCount + 1));

  // Keep only current quota counters; email hashes are deliberately retained.
  var all = properties.getProperties();
  Object.keys(all).forEach(function (key) {
    if (key.indexOf('quota:') === 0 && key !== minuteKey && key !== dayKey) {
      properties.deleteProperty(key);
    }
  });
  return true;
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
