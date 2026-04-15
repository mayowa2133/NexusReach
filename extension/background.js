/**
 * NexusReach Autofill — Background Service Worker
 *
 * Manages auth token storage and proxies API requests from
 * content scripts to the NexusReach backend.
 */

const DEFAULT_API_URL = "http://localhost:8000";

// ---------------------------------------------------------------------------
// Storage helpers
// ---------------------------------------------------------------------------

async function getConfig() {
  const data = await chrome.storage.local.get(["apiUrl", "authToken", "profile"]);
  return {
    apiUrl: data.apiUrl || DEFAULT_API_URL,
    authToken: data.authToken || null,
    profile: data.profile || null,
  };
}

async function setToken(token) {
  await chrome.storage.local.set({ authToken: token });
}

async function clearAuth() {
  await chrome.storage.local.remove(["authToken", "profile"]);
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function fetchProfile() {
  const { apiUrl, authToken } = await getConfig();
  if (!authToken) return null;

  try {
    const resp = await fetch(`${apiUrl}/api/profile/autofill`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });

    if (resp.status === 401 || resp.status === 403) {
      await clearAuth();
      return null;
    }
    if (!resp.ok) return null;

    const profile = await resp.json();
    await chrome.storage.local.set({ profile });
    return profile;
  } catch (err) {
    console.error("[NexusReach] Failed to fetch profile:", err);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Message handler — content scripts and popup talk to us here
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "GET_PROFILE") {
    // Return cached profile, or fetch fresh
    getConfig().then(({ profile }) => {
      if (profile) {
        sendResponse({ profile });
      } else {
        fetchProfile().then((p) => sendResponse({ profile: p }));
      }
    });
    return true; // async response
  }

  if (msg.type === "REFRESH_PROFILE") {
    fetchProfile().then((p) => sendResponse({ profile: p }));
    return true;
  }

  if (msg.type === "SET_TOKEN") {
    setToken(msg.token).then(() => {
      fetchProfile().then((p) => sendResponse({ ok: true, profile: p }));
    });
    return true;
  }

  if (msg.type === "LOGOUT") {
    clearAuth().then(() => sendResponse({ ok: true }));
    return true;
  }

  if (msg.type === "GET_STATUS") {
    getConfig().then(({ authToken, profile }) => {
      sendResponse({
        connected: !!authToken,
        hasProfile: !!profile,
        name: profile?.full_name || null,
      });
    });
    return true;
  }
});

// Refresh profile on install/update
chrome.runtime.onInstalled.addListener(() => {
  fetchProfile();
});
