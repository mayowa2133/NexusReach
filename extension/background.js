// Runtime defaults (dev localhost vs production origins) come from config.js,
// which build.mjs rewrites in the production package.
importScripts("config.js");

const DEFAULT_API_URL = NR_DEFAULTS.apiUrl;
const LINKEDIN_CONNECTIONS_URL =
  "https://www.linkedin.com/mynetwork/invite-connect/connections/";
const LINKEDIN_FOLLOWING_PEOPLE_URL =
  "https://www.linkedin.com/mynetwork/network-manager/people-follow/following/";

async function getConfig() {
  const data = await chrome.storage.local.get([
    "apiUrl",
    "authToken",
    "profile",
    "appUrl",
    "needsReconnect",
  ]);
  return {
    apiUrl: data.apiUrl || DEFAULT_API_URL,
    authToken: data.authToken || null,
    profile: data.profile || null,
    appUrl: data.appUrl || null,
    needsReconnect: Boolean(data.needsReconnect),
  };
}

async function setConfig({ apiUrl, authToken, appUrl }) {
  const update = {};
  if (apiUrl) update.apiUrl = apiUrl.replace(/\/+$/, "");
  if (appUrl) update.appUrl = appUrl.replace(/\/+$/, "");
  if (authToken) {
    // A fresh token (long-lived companion token minted by the app) clears any
    // pending reconnect state.
    update.authToken = authToken;
    update.needsReconnect = false;
  }
  await chrome.storage.local.set(update);
  if (authToken) {
    clearReconnectBadge();
  }
}

async function setToken(token) {
  await chrome.storage.local.set({ authToken: token, needsReconnect: false });
  clearReconnectBadge();
}

function clearReconnectBadge() {
  try {
    chrome.action.setBadgeText({ text: "" });
  } catch {
    // Cosmetic only.
  }
}

async function clearAuth() {
  await chrome.storage.local.remove(["authToken", "profile", "needsReconnect"]);
}

async function markNeedsReconnect() {
  await chrome.storage.local.set({ needsReconnect: true });
  try {
    chrome.action.setBadgeText({ text: "!" });
    chrome.action.setBadgeBackgroundColor({ color: "#ef4444" });
  } catch {
    // Badge APIs are cosmetic — never fail the request over them.
  }
}

async function apiRequest(path, options = {}) {
  const { apiUrl, authToken } = await getConfig();
  if (!authToken) {
    throw new Error("NexusReach Companion is not connected.");
  }

  const response = await fetch(`${apiUrl}${path}`, {
    ...options,
    headers: {
      ...(options.headers || {}),
      Authorization: `Bearer ${authToken}`,
      "Content-Type": "application/json",
    },
  });

  if (response.status === 401 || response.status === 403) {
    // Keep the token so the user can see what happened; flag reconnect
    // instead of silently wiping state (the token may have been revoked or
    // expired server-side).
    await markNeedsReconnect();
    throw new Error("Companion authentication expired. Reconnect it from NexusReach Settings.");
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error?.message || body?.detail || `HTTP ${response.status}`);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

async function fetchProfile() {
  const { authToken } = await getConfig();
  if (!authToken) {
    return null;
  }

  try {
    const profile = await apiRequest("/api/profile/autofill", { method: "GET" });
    await chrome.storage.local.set({ profile });
    return profile;
  } catch (error) {
    console.warn("[NexusReach Companion] Failed to fetch profile:", error);
    return null;
  }
}

function chunk(items, size) {
  const chunks = [];
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size));
  }
  return chunks;
}

async function createAndWaitForTab(url, { active = true } = {}) {
  const tab = await chrome.tabs.create({ url, active });
  if (!tab.id) {
    throw new Error("Failed to open LinkedIn tab.");
  }
  await waitForTabComplete(tab.id);
  return tab.id;
}

async function closeTabQuietly(tabId) {
  if (!tabId) return;
  try {
    await chrome.tabs.remove(tabId);
  } catch {
    // Tab already gone — nothing to clean up.
  }
}

function waitForTabComplete(tabId, timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(onUpdated);
      // LinkedIn frequently keeps SPA tabs in a long loading state; content-script
      // retries are a better source of truth than the tab status alone.
      resolve();
    }, timeoutMs);

    function onUpdated(updatedTabId, info) {
      if (updatedTabId !== tabId || info.status !== "complete") {
        return;
      }
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(onUpdated);
      resolve();
    }

    chrome.tabs.get(tabId, (tab) => {
      if (chrome.runtime.lastError) {
        clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(onUpdated);
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      if (tab?.status === "complete") {
        clearTimeout(timer);
        resolve();
        return;
      }
      chrome.tabs.onUpdated.addListener(onUpdated);
    });
  });
}

async function sendMessageToTab(tabId, message, attempts = 20) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      const response = await chrome.tabs.sendMessage(tabId, message);
      if (response) {
        return response;
      }
    } catch (error) {
      if (attempt === attempts - 1) {
        throw error;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error("The LinkedIn companion content script did not respond.");
}

async function saveLinkedInPageCapture(personId, capture) {
  if (!personId || !capture) return false;
  await apiRequest(`/api/people/${personId}/linkedin-page-capture`, {
    method: "POST",
    body: JSON.stringify(capture),
  });
  return true;
}

async function captureHiringTeam(tabId, context) {
  // Ask the content script on the active job tab to read the "Meet the hiring
  // team" panel, then ingest the captured contacts server-side.
  const scraped = await chrome.tabs.sendMessage(tabId, { type: "CAPTURE_HIRING_TEAM" });
  if (!scraped || scraped.status === "error") {
    throw new Error(scraped?.message || "Could not read the hiring team panel.");
  }
  const members = (scraped.members || []).filter((m) => m && m.name && m.profile_url);
  if (!members.length) {
    return { stored: 0, recruiters: 0, hiring_managers: 0, reason: scraped.reason || "no_members" };
  }
  return apiRequest("/api/people/hiring-team-capture", {
    method: "POST",
    body: JSON.stringify({
      company_name: context?.companyName || scraped.company_label || "",
      job_id: context?.jobId || null,
      job_title: context?.jobTitle || scraped.job_title || null,
      members,
    }),
  });
}

async function markMessageCopied(messageId) {
  if (!messageId) return false;
  await apiRequest(`/api/messages/${messageId}/copy`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  return true;
}

async function runLinkedInAssist(payload) {
  if (!payload.linkedinUrl) {
    throw new Error("This contact does not have a LinkedIn URL.");
  }

  const tabId = await createAndWaitForTab(payload.linkedinUrl);
  const result = await sendMessageToTab(tabId, {
    type: "RUN_LINKEDIN_ASSIST",
    payload,
  });

  if (result?.capture) {
    try {
      result.capture_saved = await saveLinkedInPageCapture(payload.personId, result.capture);
    } catch (error) {
      console.warn("[NexusReach Companion] Failed to save LinkedIn capture:", error);
    }
  }

  if (result?.status === "completed" && payload.messageId && payload.action !== "open_profile") {
    try {
      result.draft_marked_copied = await markMessageCopied(payload.messageId);
    } catch (error) {
      console.warn("[NexusReach Companion] Failed to mark message as copied:", error);
    }
  }

  return result;
}

async function uploadConnectionBatches(sessionToken, items, maxBatchSize, hasFollowBatches) {
  if (!items.length) return;
  const batches = chunk(items, maxBatchSize);
  for (let index = 0; index < batches.length; index += 1) {
    const isFinalBatch = !hasFollowBatches && index === batches.length - 1;
    await apiRequest("/api/linkedin-graph/import-batch", {
      method: "POST",
      body: JSON.stringify({
        session_token: sessionToken,
        connections: batches[index],
        is_final_batch: isFinalBatch,
      }),
    });
  }
}

async function uploadFollowBatches(sessionToken, items, maxBatchSize) {
  if (!items.length) return;
  const batches = chunk(items, maxBatchSize);
  for (let index = 0; index < batches.length; index += 1) {
    await apiRequest("/api/linkedin-graph/import-follow-batch", {
      method: "POST",
      body: JSON.stringify({
        session_token: sessionToken,
        follows: batches[index],
        is_final_batch: index === batches.length - 1,
      }),
    });
  }
}

async function finishEmptyGraphSync(sessionToken) {
  await apiRequest("/api/linkedin-graph/import-batch", {
    method: "POST",
    body: JSON.stringify({
      session_token: sessionToken,
      connections: [],
      is_final_batch: true,
    }),
  });
}

async function scrapeFollowTab(url, entityType, { active = true, background = false, deadline = 0 } = {}) {
  let tabId = null;
  try {
    tabId = await createAndWaitForTab(url, { active });
    const result = await sendMessageToTab(tabId, {
      type: "RUN_GRAPH_REFRESH_FOLLOWS",
      payload: { entityType, background, deadline },
    });
    const statusWarning =
      result?.status === "blocked" || result?.status === "error"
        ? [result?.message || `Could not scrape LinkedIn ${entityType} follows.`]
        : [];
    return {
      follows: Array.isArray(result?.follows) ? result.follows : [],
      warnings: [
        ...statusWarning,
        ...(Array.isArray(result?.warnings) ? result.warnings : []),
      ],
    };
  } catch (error) {
    return {
      follows: [],
      warnings: [
        error instanceof Error
          ? error.message
          : `Could not scrape LinkedIn ${entityType} follows.`,
      ],
    };
  } finally {
    // Background runs open their own hidden tabs and must not leave them behind;
    // foreground runs leave the tab so the user can see what happened.
    if (background) await closeTabQuietly(tabId);
  }
}

async function resolveOwnLinkedInProfileUrl(tabId) {
  try {
    const result = await sendMessageToTab(tabId, {
      type: "RESOLVE_LINKEDIN_SELF_PROFILE",
    });
    return result?.profileUrl || null;
  } catch (error) {
    console.warn("[NexusReach Companion] Failed to resolve LinkedIn profile URL:", error);
    return null;
  }
}

function profileInterestsUrl(profileUrl) {
  if (!profileUrl) return null;
  try {
    const parsed = new URL(profileUrl);
    parsed.search = "";
    parsed.hash = "";
    return `${parsed.toString().replace(/\/+$/, "")}/details/interests/?detailScreenTabIndex=1`;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Auto-cadence sync (Workstream D)
//
// A jittered weekly alarm keeps the user's graph fresh with zero effort. All
// runs are heavily guarded: at most one per 24h, only when the graph already
// exists and has aged past AUTO_SYNC_STALE_DAYS, always in hidden tabs with a
// wall-clock budget, and aborting on any LinkedIn interstitial. Opt-out via
// the popup's Auto-sync toggle (default on).
// ---------------------------------------------------------------------------

const AUTO_SYNC_ALARM = "nr-auto-sync";
const AUTO_SYNC_BASE_INTERVAL_MS = 7 * 24 * 60 * 60 * 1000; // weekly
const AUTO_SYNC_JITTER_MS = 24 * 60 * 60 * 1000; // + up to a day
const AUTO_SYNC_COOLDOWN_MS = 24 * 60 * 60 * 1000; // never more than 1/24h
const AUTO_SYNC_STALE_DAYS = 7; // don't auto-run a fresher graph
const STALE_PROMPT_DAYS = 14; // opportunistic in-page nudge threshold
const STATUS_CACHE_MS = 6 * 60 * 60 * 1000; // bound status API calls
const GRAPH_BACKGROUND_BUDGET_MS = 4 * 60 * 1000; // finish before throttling

async function getSyncState() {
  const data = await chrome.storage.local.get([
    "autoSyncEnabled",
    "lastAutoSyncAt",
    "lastStalePromptAt",
    "cachedGraphStatus",
    "cachedGraphStatusAt",
  ]);
  return {
    // Opt-out: undefined (never set) counts as enabled.
    autoSyncEnabled: data.autoSyncEnabled !== false,
    lastAutoSyncAt: Number(data.lastAutoSyncAt) || 0,
    lastStalePromptAt: Number(data.lastStalePromptAt) || 0,
    cachedGraphStatus: data.cachedGraphStatus || null,
    cachedGraphStatusAt: Number(data.cachedGraphStatusAt) || 0,
  };
}

async function fetchGraphStatusCached(force = false) {
  const { cachedGraphStatus, cachedGraphStatusAt } = await getSyncState();
  if (!force && cachedGraphStatus && Date.now() - cachedGraphStatusAt < STATUS_CACHE_MS) {
    return cachedGraphStatus;
  }
  const status = await apiRequest("/api/linkedin-graph/status", { method: "GET" });
  await chrome.storage.local.set({
    cachedGraphStatus: status,
    cachedGraphStatusAt: Date.now(),
  });
  return status;
}

function setStaleBadge() {
  try {
    chrome.action.setBadgeText({ text: "↻" });
    chrome.action.setBadgeBackgroundColor({ color: "#d97706" });
  } catch {
    // Cosmetic only.
  }
}

function notify(title, message) {
  try {
    chrome.notifications?.create({
      type: "basic",
      iconUrl: "icons/icon128.png",
      title,
      message,
    });
  } catch {
    // Notifications are best-effort feedback for a background run.
  }
}

async function runOneShotGraphSync({ background }) {
  // Shared body for both the background alarm and the opportunistic prompt:
  // mint a fresh sync session (respects the server's 6/day cap) and run a
  // refresh. Records the run timestamp so the 24h cooldown holds across both.
  const session = await apiRequest("/api/linkedin-graph/sync-session", { method: "POST" });
  const result = await runGraphRefresh({
    sessionToken: session.session_token,
    maxBatchSize: session.max_batch_size,
    background,
    budgetMs: background ? GRAPH_BACKGROUND_BUDGET_MS : 0,
  });
  await chrome.storage.local.set({ lastAutoSyncAt: Date.now() });
  // A completed sync refreshes the cached status on the next read.
  await chrome.storage.local.remove(["cachedGraphStatus", "cachedGraphStatusAt"]);
  return result;
}

async function maybeAutoSync(trigger) {
  const { authToken, needsReconnect } = await getConfig();
  if (!authToken || needsReconnect) return { ran: false, reason: "not_connected" };

  const { autoSyncEnabled, lastAutoSyncAt } = await getSyncState();
  if (!autoSyncEnabled) return { ran: false, reason: "disabled" };
  if (Date.now() - lastAutoSyncAt < AUTO_SYNC_COOLDOWN_MS) {
    return { ran: false, reason: "cooldown" };
  }

  let status;
  try {
    status = await fetchGraphStatusCached(true);
  } catch (error) {
    console.warn("[NexusReach Companion] Auto-sync status check failed:", error);
    return { ran: false, reason: "status_error" };
  }

  // Only auto-run an existing graph that has aged. A never-synced graph stays
  // user-initiated (onboarding / Settings), never surprise-scraped.
  const connectionCount = Number(status?.connection_count) || 0;
  const daysSince = status?.days_since_sync;
  const aged =
    Boolean(status?.refresh_recommended)
    || (typeof daysSince === "number" && daysSince >= AUTO_SYNC_STALE_DAYS);
  if (connectionCount === 0 || !aged) {
    return { ran: false, reason: "fresh_or_empty" };
  }

  try {
    const result = await runOneShotGraphSync({ background: true });
    if (result.status === "completed") {
      clearReconnectBadge();
      notify(
        "Network refreshed",
        `Imported ${result.imported_connections} connections from LinkedIn.`,
      );
    } else {
      setStaleBadge();
    }
    return { ran: true, result };
  } catch (error) {
    console.warn(`[NexusReach Companion] Auto-sync (${trigger}) failed:`, error);
    setStaleBadge();
    return { ran: false, reason: "run_error" };
  }
}

async function shouldPromptStaleGraph() {
  const { authToken, needsReconnect } = await getConfig();
  if (!authToken || needsReconnect) return { prompt: false };

  const { autoSyncEnabled, lastAutoSyncAt, lastStalePromptAt } = await getSyncState();
  // The prompt only matters when auto-sync can't keep up on its own.
  if (!autoSyncEnabled) return { prompt: false };
  if (Date.now() - lastAutoSyncAt < AUTO_SYNC_COOLDOWN_MS) return { prompt: false };
  if (Date.now() - lastStalePromptAt < AUTO_SYNC_COOLDOWN_MS) return { prompt: false };

  let status;
  try {
    status = await fetchGraphStatusCached(false);
  } catch {
    return { prompt: false };
  }
  const connectionCount = Number(status?.connection_count) || 0;
  const daysSince = status?.days_since_sync;
  if (connectionCount === 0 || typeof daysSince !== "number" || daysSince < STALE_PROMPT_DAYS) {
    return { prompt: false };
  }
  await chrome.storage.local.set({ lastStalePromptAt: Date.now() });
  return { prompt: true, daysSinceSync: daysSince };
}

function scheduleNextAutoSync() {
  const when = Date.now() + AUTO_SYNC_BASE_INTERVAL_MS + Math.random() * AUTO_SYNC_JITTER_MS;
  chrome.alarms.create(AUTO_SYNC_ALARM, { when });
}

async function ensureAutoSyncAlarm() {
  // MV3 service workers are ephemeral but alarms persist; only (re)arm when the
  // alarm is missing so we don't reset the jittered schedule on every wake.
  const existing = await chrome.alarms.get(AUTO_SYNC_ALARM);
  if (!existing) scheduleNextAutoSync();
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== AUTO_SYNC_ALARM) return;
  maybeAutoSync("alarm").finally(() => scheduleNextAutoSync());
});

async function runGraphRefresh(payload) {
  if (!payload.sessionToken) {
    throw new Error("LinkedIn graph refresh session token is missing.");
  }

  // Background (auto-sync) runs use hidden tabs, slower scroll pacing, and a
  // wall-clock budget so they finish before Chrome's intensive throttling and
  // never steal focus. Foreground (user-initiated) runs keep the fast, visible
  // behavior.
  const background = Boolean(payload.background);
  const active = !background;
  const deadline = background && payload.budgetMs
    ? Date.now() + Number(payload.budgetMs)
    : 0;
  const scrapeOpts = { background, deadline };

  // Only overwrite stored auth when the caller actually passed a token — the
  // background path relies on the already-stored companion token.
  if (payload.apiUrl || payload.authToken) {
    await setConfig({
      apiUrl: payload.apiUrl,
      authToken: payload.authToken,
    });
  }

  const connectionTabId = await createAndWaitForTab(LINKEDIN_CONNECTIONS_URL, { active });
  let connectionResult;
  try {
    connectionResult = await sendMessageToTab(connectionTabId, {
      type: "RUN_GRAPH_REFRESH_CONNECTIONS",
      payload: scrapeOpts,
    });
    if (connectionResult?.status === "blocked" || connectionResult?.status === "error") {
      throw new Error(connectionResult?.message || "Could not scrape LinkedIn connections.");
    }

    const peopleFollowResult = await scrapeFollowTab(LINKEDIN_FOLLOWING_PEOPLE_URL, "person", { active, ...scrapeOpts });
    const ownProfileUrl = await resolveOwnLinkedInProfileUrl(connectionTabId);
    const companyFollowUrl = profileInterestsUrl(ownProfileUrl);
    const companyFollowResult = companyFollowUrl
      ? await scrapeFollowTab(companyFollowUrl, "company", { active, ...scrapeOpts })
      : {
          follows: [],
          warnings: ["Could not resolve your LinkedIn profile URL for company follow capture."],
        };
    return await finalizeGraphRefresh(payload, connectionResult, peopleFollowResult, companyFollowResult);
  } finally {
    if (background) await closeTabQuietly(connectionTabId);
  }
}

async function finalizeGraphRefresh(payload, connectionResult, peopleFollowResult, companyFollowResult) {
  const connections = Array.isArray(connectionResult?.connections)
    ? connectionResult.connections
    : [];
  const follows = [...peopleFollowResult.follows, ...companyFollowResult.follows];
  const followWarnings = [...peopleFollowResult.warnings, ...companyFollowResult.warnings];
  const maxBatchSize = Number(payload.maxBatchSize) || 250;

  if (connections.length === 0 && follows.length === 0) {
    await finishEmptyGraphSync(payload.sessionToken);
    return {
      status: "blocked",
      message: "LinkedIn refresh did not find any visible connections or follow signals to import.",
      imported_connections: 0,
      imported_follows: 0,
      follow_warnings: followWarnings,
    };
  }

  await uploadConnectionBatches(
    payload.sessionToken,
    connections,
    maxBatchSize,
    follows.length > 0,
  );
  if (follows.length > 0) {
    await uploadFollowBatches(payload.sessionToken, follows, maxBatchSize);
  } else if (connections.length === 0) {
    await finishEmptyGraphSync(payload.sessionToken);
  }

  return {
    status: "completed",
    message: `Imported ${connections.length} connections and ${follows.length} follow signals from LinkedIn.`,
    imported_connections: connections.length,
    imported_follows: follows.length,
    follow_warnings: followWarnings,
  };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "GET_PROFILE") {
    getConfig().then(({ profile }) => {
      if (profile) {
        sendResponse({ profile });
      } else {
        fetchProfile().then((nextProfile) => sendResponse({ profile: nextProfile }));
      }
    });
    return true;
  }

  if (message.type === "CAPTURE_HIRING_TEAM") {
    captureHiringTeam(message.tabId, message.context || {})
      .then((result) => sendResponse({ ok: true, ...result }))
      .catch((error) => sendResponse({ ok: false, error: error instanceof Error ? error.message : String(error) }));
    return true;
  }

  if (message.type === "SUBMIT_HIRING_TEAM") {
    const p = message.payload || {};
    apiRequest("/api/people/hiring-team-capture", {
      method: "POST",
      body: JSON.stringify({
        company_name: p.company_name || "",
        job_id: p.job_id || null,
        job_title: p.job_title || null,
        members: p.members || [],
      }),
    })
      .then((result) => sendResponse({ ok: true, ...result }))
      .catch((error) => sendResponse({ ok: false, error: error instanceof Error ? error.message : String(error) }));
    return true;
  }

  if (message.type === "REFRESH_PROFILE") {
    fetchProfile().then((profile) => sendResponse({ profile }));
    return true;
  }

  if (message.type === "SET_TOKEN") {
    setToken(message.token).then(() => {
      fetchProfile().then((profile) => sendResponse({ ok: true, profile }));
    });
    return true;
  }

  if (message.type === "LOGOUT") {
    clearAuth().then(() => {
      clearReconnectBadge();
      sendResponse({ ok: true });
    });
    return true;
  }

  if (message.type === "GET_STATUS") {
    Promise.all([getConfig(), getSyncState()]).then(
      ([{ authToken, profile, needsReconnect, appUrl }, { autoSyncEnabled }]) => {
        sendResponse({
          available: true,
          connected: Boolean(authToken),
          hasProfile: Boolean(profile),
          needsReconnect,
          appUrl,
          autoSyncEnabled,
          name: profile?.full_name || null,
          version: chrome.runtime.getManifest().version,
        });
      },
    );
    return true;
  }

  if (message.type === "NR_EXTENSION_PING") {
    getConfig().then(({ authToken, profile, needsReconnect }) => {
      sendResponse({
        available: true,
        connected: Boolean(authToken),
        hasProfile: Boolean(profile),
        needsReconnect,
        name: profile?.full_name || null,
        version: chrome.runtime.getManifest().version,
      });
    });
    return true;
  }

  if (message.type === "NR_EXTENSION_CONNECT") {
    setConfig({
      apiUrl: message.payload?.apiUrl,
      authToken: message.payload?.authToken,
      // Remember which NexusReach origin connected us so the popup can link
      // back to the app (works for both localhost dev and production).
      appUrl: sender?.origin || null,
    }).then(async () => {
      const profile = await fetchProfile();
      sendResponse({
        available: true,
        connected: Boolean(message.payload?.authToken),
        hasProfile: Boolean(profile),
        name: profile?.full_name || null,
        version: chrome.runtime.getManifest().version,
      });
    });
    return true;
  }

  if (message.type === "NR_LINKEDIN_ASSIST") {
    runLinkedInAssist(message.payload || {})
      .then((result) => sendResponse(result))
      .catch((error) =>
        sendResponse({
          error: error instanceof Error ? error.message : "LinkedIn assist failed.",
        }),
      );
    return true;
  }

  if (message.type === "NR_LINKEDIN_GRAPH_REFRESH") {
    runGraphRefresh(message.payload || {})
      .then((result) => sendResponse(result))
      .catch((error) =>
        sendResponse({
          error: error instanceof Error ? error.message : "LinkedIn graph refresh failed.",
        }),
      );
    return true;
  }

  // Auto-cadence sync (Workstream D)
  if (message.type === "GET_AUTOSYNC") {
    getSyncState().then(({ autoSyncEnabled, lastAutoSyncAt }) => {
      sendResponse({ enabled: autoSyncEnabled, lastAutoSyncAt });
    });
    return true;
  }

  if (message.type === "SET_AUTOSYNC") {
    chrome.storage.local
      .set({ autoSyncEnabled: Boolean(message.enabled) })
      .then(() => sendResponse({ ok: true, enabled: Boolean(message.enabled) }));
    return true;
  }

  if (message.type === "SHOULD_PROMPT_STALE_GRAPH") {
    shouldPromptStaleGraph()
      .then((result) => sendResponse(result))
      .catch(() => sendResponse({ prompt: false }));
    return true;
  }

  if (message.type === "CAPTURE_PROFILE") {
    // Ambient "Save to NexusReach" (Workstream E): the content script read the
    // visible profile top card; persist it as a CRM contact.
    apiRequest("/api/people/capture-linkedin-profile", {
      method: "POST",
      body: JSON.stringify(message.payload || {}),
    })
      .then((person) => sendResponse({ ok: true, person }))
      .catch((error) =>
        sendResponse({ ok: false, error: error instanceof Error ? error.message : String(error) }),
      );
    return true;
  }

  if (message.type === "START_OPPORTUNISTIC_SYNC") {
    // User clicked "Refresh now" on the in-page nudge — run in the foreground
    // in their current session (fast, visible, human-present).
    runOneShotGraphSync({ background: false })
      .then((result) => {
        clearReconnectBadge();
        sendResponse({ ok: true, ...result });
      })
      .catch((error) =>
        sendResponse({
          ok: false,
          error: error instanceof Error ? error.message : "LinkedIn graph refresh failed.",
        }),
      );
    return true;
  }

  return false;
});

chrome.runtime.onInstalled.addListener(() => {
  fetchProfile();
  ensureAutoSyncAlarm();
});

chrome.runtime.onStartup?.addListener(() => {
  ensureAutoSyncAlarm();
});

// Ensure the alarm exists whenever the service worker wakes (MV3 workers are
// ephemeral; onInstalled/onStartup don't cover every revival).
ensureAutoSyncAlarm();
