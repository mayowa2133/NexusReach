const DEFAULT_API_URL = "http://localhost:8000";
const LINKEDIN_CONNECTIONS_URL =
  "https://www.linkedin.com/mynetwork/invite-connect/connections/";
const LINKEDIN_FOLLOWING_PEOPLE_URL =
  "https://www.linkedin.com/mynetwork/network-manager/people-follow/following/";

async function getConfig() {
  const data = await chrome.storage.local.get(["apiUrl", "authToken", "profile"]);
  return {
    apiUrl: data.apiUrl || DEFAULT_API_URL,
    authToken: data.authToken || null,
    profile: data.profile || null,
  };
}

async function setConfig({ apiUrl, authToken }) {
  const update = {};
  if (apiUrl) update.apiUrl = apiUrl.replace(/\/+$/, "");
  if (authToken) update.authToken = authToken;
  await chrome.storage.local.set(update);
}

async function setToken(token) {
  await chrome.storage.local.set({ authToken: token });
}

async function clearAuth() {
  await chrome.storage.local.remove(["authToken", "profile"]);
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
    await clearAuth();
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

async function createAndWaitForTab(url) {
  const tab = await chrome.tabs.create({ url, active: true });
  if (!tab.id) {
    throw new Error("Failed to open LinkedIn tab.");
  }
  await waitForTabComplete(tab.id);
  return tab.id;
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

async function scrapeFollowTab(url, entityType) {
  try {
    const tabId = await createAndWaitForTab(url);
    const result = await sendMessageToTab(tabId, {
      type: "RUN_GRAPH_REFRESH_FOLLOWS",
      payload: { entityType },
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

async function runGraphRefresh(payload) {
  if (!payload.sessionToken) {
    throw new Error("LinkedIn graph refresh session token is missing.");
  }

  await setConfig({
    apiUrl: payload.apiUrl,
    authToken: payload.authToken,
  });

  const connectionTabId = await createAndWaitForTab(LINKEDIN_CONNECTIONS_URL);
  const connectionResult = await sendMessageToTab(connectionTabId, {
    type: "RUN_GRAPH_REFRESH_CONNECTIONS",
  });
  if (connectionResult?.status === "blocked" || connectionResult?.status === "error") {
    throw new Error(connectionResult?.message || "Could not scrape LinkedIn connections.");
  }

  const peopleFollowResult = await scrapeFollowTab(LINKEDIN_FOLLOWING_PEOPLE_URL, "person");
  const ownProfileUrl = await resolveOwnLinkedInProfileUrl(connectionTabId);
  const companyFollowUrl = profileInterestsUrl(ownProfileUrl);
  const companyFollowResult = companyFollowUrl
    ? await scrapeFollowTab(companyFollowUrl, "company")
    : {
        follows: [],
        warnings: ["Could not resolve your LinkedIn profile URL for company follow capture."],
      };

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

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
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
    clearAuth().then(() => sendResponse({ ok: true }));
    return true;
  }

  if (message.type === "GET_STATUS") {
    getConfig().then(({ authToken, profile }) => {
      sendResponse({
        available: true,
        connected: Boolean(authToken),
        hasProfile: Boolean(profile),
        name: profile?.full_name || null,
        version: chrome.runtime.getManifest().version,
      });
    });
    return true;
  }

  if (message.type === "NR_EXTENSION_PING") {
    getConfig().then(({ authToken, profile }) => {
      sendResponse({
        available: true,
        connected: Boolean(authToken),
        hasProfile: Boolean(profile),
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

  return false;
});

chrome.runtime.onInstalled.addListener(() => {
  fetchProfile();
});
