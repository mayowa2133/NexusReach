(function initNexusReachAppBridge() {
  const PAGE_SOURCE = "nexusreach-web";
  const EXTENSION_SOURCE = "nexusreach-companion";

  // Only these message types cross from the page into the privileged worker.
  // Anything running in the page can postMessage here — an XSS, a malicious
  // dependency, a third-party tag — so forwarding `data.type` unfiltered would
  // hand page script the worker's whole command surface, including SET_TOKEN.
  // The background worker enforces the same list against the sender's origin;
  // this is the cheap first gate. Keep in step with ALLOWED_TYPES_BY_SCRIPT
  // ("app-bridge.js") in background.js and CompanionMessageType in the app.
  const FORWARDABLE_TYPES = new Set([
    "NR_EXTENSION_PING",
    "NR_EXTENSION_CONNECT",
    "NR_LINKEDIN_ASSIST",
    "NR_LINKEDIN_GRAPH_REFRESH",
    "NR_CAPTURE_SELF_PROFILE",
  ]);

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;

    const data = event.data || {};
    if (data.source !== PAGE_SOURCE || !data.type || !data.requestId) {
      return;
    }
    if (!FORWARDABLE_TYPES.has(data.type)) {
      return;
    }

    const postFailure = (error) => {
      window.postMessage(
        {
          source: EXTENSION_SOURCE,
          type: "NR_EXTENSION_RESULT",
          requestId: data.requestId,
          ok: false,
          error,
        },
        window.location.origin,
      );
    };

    try {
      if (!chrome.runtime?.id) {
        postFailure("Companion extension context is unavailable. Reload NexusReach and try again.");
        return;
      }

      chrome.runtime.sendMessage(
        {
          type: data.type,
          payload: data.payload || {},
          requestId: data.requestId,
        },
        (response) => {
          const runtimeError = chrome.runtime.lastError?.message;
          const ok = !runtimeError && !response?.error;
          window.postMessage(
            {
              source: EXTENSION_SOURCE,
              type: "NR_EXTENSION_RESULT",
              requestId: data.requestId,
              ok,
              result: ok ? response : undefined,
              error: runtimeError || response?.error || "Companion request failed.",
            },
            window.location.origin,
          );
        },
      );
    } catch (error) {
      postFailure(
        error instanceof Error
          ? error.message
          : "Companion extension context is unavailable. Reload NexusReach and try again.",
      );
    }
  });
})();
