/**
 * NexusReach Companion — Popup Script
 *
 * Handles manual connect/disconnect, profile display, and ATS autofill toggle.
 */

const loginView = document.getElementById("login-view");
const connectedView = document.getElementById("connected-view");
const connectBtn = document.getElementById("connect-btn");
const refreshBtn = document.getElementById("refresh-btn");
const disconnectBtn = document.getElementById("disconnect-btn");
const apiUrlInput = document.getElementById("api-url");
const authTokenInput = document.getElementById("auth-token");
const autofillToggle = document.getElementById("autofill-toggle");

// ---------------------------------------------------------------------------
// View toggling
// ---------------------------------------------------------------------------

function showLogin() {
  loginView.classList.remove("hidden");
  connectedView.classList.add("hidden");
}

function showConnected(profile) {
  loginView.classList.add("hidden");
  connectedView.classList.remove("hidden");

  if (profile) {
    renderProfile(profile);
  }
}

function renderProfile(p) {
  document.getElementById("profile-name").textContent = p.full_name || "No name set";
  document.getElementById("profile-name-status").textContent =
    p.full_name ? `Signed in as ${p.full_name}` : "Profile loaded";

  // Email from experience or just show roles
  const roles = (p.target_roles || []).slice(0, 3).join(", ");
  document.getElementById("profile-email").textContent = roles || "No target roles set";

  // Links
  const links = [];
  if (p.linkedin_url) links.push("LinkedIn ✓");
  if (p.github_url) links.push("GitHub ✓");
  if (p.portfolio_url) links.push("Portfolio ✓");
  document.getElementById("profile-links").textContent = links.join(" · ") || "";

  // Skills
  const skillsEl = document.getElementById("profile-skills");
  skillsEl.innerHTML = "";
  const skills = (p.skills || []).slice(0, 12);
  skills.forEach((s) => {
    const tag = document.createElement("span");
    tag.className = "skill-tag";
    tag.textContent = s;
    skillsEl.appendChild(tag);
  });
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

async function init() {
  // Load saved API URL
  const data = await chrome.storage.local.get(["apiUrl", "autofillEnabled"]);
  if (data.apiUrl) apiUrlInput.value = data.apiUrl;
  autofillToggle.checked = data.autofillEnabled !== false; // default on

  // Check connection status
  chrome.runtime.sendMessage({ type: "GET_STATUS" }, (resp) => {
    if (resp && resp.connected && resp.hasProfile) {
      chrome.runtime.sendMessage({ type: "GET_PROFILE" }, (r) => {
        showConnected(r.profile);
      });
    } else if (resp && resp.connected) {
      // Have token but no profile — try refresh
      chrome.runtime.sendMessage({ type: "REFRESH_PROFILE" }, (r) => {
        if (r.profile) {
          showConnected(r.profile);
        } else {
          showLogin();
        }
      });
    } else {
      showLogin();
    }
  });
}

// ---------------------------------------------------------------------------
// Event handlers
// ---------------------------------------------------------------------------

connectBtn.addEventListener("click", async () => {
  const apiUrl = apiUrlInput.value.trim().replace(/\/+$/, "");
  const token = authTokenInput.value.trim();

  if (!token) {
    authTokenInput.style.borderColor = "#ef4444";
    return;
  }

  connectBtn.textContent = "Connecting...";
  connectBtn.disabled = true;

  await chrome.storage.local.set({ apiUrl });

  chrome.runtime.sendMessage({ type: "SET_TOKEN", token }, (resp) => {
    connectBtn.textContent = "Connect";
    connectBtn.disabled = false;

    if (resp && resp.ok && resp.profile) {
      showConnected(resp.profile);
    } else {
      authTokenInput.style.borderColor = "#ef4444";
      alert("Failed to connect. Check your API URL and token.");
    }
  });
});

refreshBtn.addEventListener("click", () => {
  refreshBtn.textContent = "Refreshing...";
  refreshBtn.disabled = true;

  chrome.runtime.sendMessage({ type: "REFRESH_PROFILE" }, (resp) => {
    refreshBtn.textContent = "Refresh Profile";
    refreshBtn.disabled = false;

    if (resp && resp.profile) {
      renderProfile(resp.profile);
    }
  });
});

disconnectBtn.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "LOGOUT" }, () => {
    showLogin();
    authTokenInput.value = "";
  });
});

autofillToggle.addEventListener("change", () => {
  chrome.storage.local.set({ autofillEnabled: autofillToggle.checked });
});

// Go
init();
