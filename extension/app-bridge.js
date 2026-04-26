(function initNexusReachAppBridge() {
  const PAGE_SOURCE = "nexusreach-web";
  const EXTENSION_SOURCE = "nexusreach-companion";

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;

    const data = event.data || {};
    if (data.source !== PAGE_SOURCE || !data.type || !data.requestId) {
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
