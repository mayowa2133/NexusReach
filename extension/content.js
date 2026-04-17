/**
 * NexusReach Autofill — Content Script
 *
 * Detects job application forms on ATS pages and fills them
 * with the user's NexusReach profile data.
 *
 * Supported ATS:
 *   - Greenhouse (boards.greenhouse.io)
 *   - Lever (jobs.lever.co)
 *   - Ashby (jobs.ashbyhq.com)
 *   - Workable (apply.workable.com)
 *   - Workday (*.myworkdayjobs.com)
 *   - Generic application forms
 */

// ---------------------------------------------------------------------------
// Field detection — maps form fields to profile data keys
// ---------------------------------------------------------------------------

/**
 * Each rule: { profileKey, patterns (for name/id/label match), type }
 * profileKey maps to the flat autofill profile structure returned
 * by GET /api/profile/autofill.
 */
const FIELD_RULES = [
  {
    key: "full_name",
    patterns: [/full.?name/i, /^name$/i, /your.?name/i, /candidate.?name/i],
    type: "text",
  },
  {
    key: "first_name",
    patterns: [/first.?name/i, /given.?name/i, /fname/i],
    type: "text",
  },
  {
    key: "last_name",
    patterns: [/last.?name/i, /family.?name/i, /surname/i, /lname/i],
    type: "text",
  },
  {
    key: "email",
    patterns: [/e?.?mail/i],
    type: "email",
  },
  {
    key: "phone",
    patterns: [/phone/i, /mobile/i, /cell/i, /tel(?:ephone)?/i],
    type: "tel",
  },
  {
    key: "linkedin_url",
    patterns: [/linkedin/i, /linked.?in/i],
    type: "url",
  },
  {
    key: "github_url",
    patterns: [/github/i, /git.?hub/i],
    type: "url",
  },
  {
    key: "portfolio_url",
    patterns: [/portfolio/i, /website/i, /personal.?(?:site|url|page)/i, /^url$/i, /^link$/i],
    type: "url",
  },
  {
    key: "location",
    patterns: [/^location$/i, /city/i, /address/i, /current.?location/i],
    type: "text",
  },
  {
    key: "current_company",
    patterns: [/current.?(?:company|employer|org)/i],
    type: "text",
  },
  {
    key: "current_title",
    patterns: [/current.?(?:title|role|position)/i, /job.?title/i],
    type: "text",
  },
  {
    key: "years_experience",
    patterns: [/years?.?(?:of)?.?exp/i, /experience.?years/i],
    type: "text",
  },
  {
    key: "education",
    patterns: [/education/i, /school/i, /university/i, /college/i, /degree/i],
    type: "text",
  },
  {
    key: "salary_expectation",
    patterns: [/salary/i, /compensation/i, /pay.?expect/i],
    type: "text",
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getFieldSignature(el) {
  /** Combine all identifiable attributes into one searchable string. */
  const parts = [
    el.name || "",
    el.id || "",
    el.placeholder || "",
    el.getAttribute("aria-label") || "",
    el.getAttribute("data-qa") || "",
    el.getAttribute("autocomplete") || "",
  ];

  // Also check the associated <label>
  const label = findLabel(el);
  if (label) parts.push(label);

  return parts.join(" ");
}

function findLabel(el) {
  // Explicit label via for=
  if (el.id) {
    const label = document.querySelector(`label[for="${el.id}"]`);
    if (label) return label.textContent.trim();
  }
  // Enclosing label
  const parent = el.closest("label");
  if (parent) return parent.textContent.trim();
  // Adjacent label (sibling or parent child)
  const container = el.closest(".field, .form-group, .form-field, [class*='field'], [class*='input']");
  if (container) {
    const label = container.querySelector("label, .label, [class*='label']");
    if (label) return label.textContent.trim();
  }
  return "";
}

function matchRule(signature, rules) {
  for (const rule of rules) {
    for (const pattern of rule.patterns) {
      if (pattern.test(signature)) {
        return rule;
      }
    }
  }
  return null;
}

function setInputValue(el, value) {
  /** Set value with proper events so React/Angular/Vue pick it up. */
  if (!value) return false;

  const nativeInputValueSetter =
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set ||
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;

  if (nativeInputValueSetter) {
    nativeInputValueSetter.call(el, value);
  } else {
    el.value = value;
  }

  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  el.dispatchEvent(new Event("blur", { bubbles: true }));
  return true;
}

// ---------------------------------------------------------------------------
// Form detection + filling
// ---------------------------------------------------------------------------

function detectAndFill(profile) {
  if (!profile) return { filled: 0, total: 0, fields: [] };

  const inputs = document.querySelectorAll(
    'input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="checkbox"]):not([type="radio"]):not([type="file"]), textarea'
  );

  let filled = 0;
  const total = inputs.length;
  const fields = [];

  for (const input of inputs) {
    // Skip already-filled fields
    if (input.value && input.value.trim().length > 0) {
      continue;
    }
    // Skip disabled/readonly
    if (input.disabled || input.readOnly) continue;

    const sig = getFieldSignature(input);
    const rule = matchRule(sig, FIELD_RULES);

    if (rule && profile[rule.key]) {
      const success = setInputValue(input, String(profile[rule.key]));
      if (success) {
        filled++;
        fields.push(rule.key);
        // Visual feedback
        input.style.outline = "2px solid #6366f1";
        input.style.outlineOffset = "-1px";
        setTimeout(() => {
          input.style.outline = "";
          input.style.outlineOffset = "";
        }, 3000);
      }
    }
  }

  return { filled, total, fields };
}

// ---------------------------------------------------------------------------
// Floating action button
// ---------------------------------------------------------------------------

function createFAB() {
  // Don't duplicate
  if (document.getElementById("nexusreach-fab")) return;

  const fab = document.createElement("div");
  fab.id = "nexusreach-fab";
  fab.innerHTML = `
    <button id="nexusreach-fill-btn" title="NexusReach Autofill">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 20h9"/>
        <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>
      </svg>
      <span>Fill</span>
    </button>
    <div id="nexusreach-toast" class="nexusreach-toast hidden"></div>
  `;
  document.body.appendChild(fab);

  document.getElementById("nexusreach-fill-btn").addEventListener("click", () => {
    chrome.runtime.sendMessage({ type: "GET_PROFILE" }, (resp) => {
      if (!resp || !resp.profile) {
        showToast("Not connected. Open the NexusReach extension to connect.", "error");
        return;
      }
      const result = detectAndFill(resp.profile);
      if (result.filled > 0) {
        showToast(`Filled ${result.filled} field${result.filled > 1 ? "s" : ""}: ${result.fields.join(", ")}`, "success");
      } else {
        showToast("No empty fields matched. Some may already be filled.", "info");
      }
    });
  });
}

function showToast(message, type) {
  const toast = document.getElementById("nexusreach-toast");
  if (!toast) return;
  toast.textContent = message;
  toast.className = `nexusreach-toast ${type}`;
  toast.classList.remove("hidden");
  setTimeout(() => toast.classList.add("hidden"), 4000);
}

// ---------------------------------------------------------------------------
// Auto-fill on page load (if enabled)
// ---------------------------------------------------------------------------

async function maybeAutoFill() {
  const data = await chrome.storage.local.get(["autofillEnabled"]);
  if (data.autofillEnabled === false) return;

  chrome.runtime.sendMessage({ type: "GET_PROFILE" }, (resp) => {
    if (resp && resp.profile) {
      // Wait a bit for React/dynamic forms to render
      setTimeout(() => {
        const result = detectAndFill(resp.profile);
        if (result.filled > 0) {
          showToast(`Auto-filled ${result.filled} field${result.filled > 1 ? "s" : ""}`, "success");
        }
      }, 1500);
    }
  });
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

function init() {
  createFAB();
  maybeAutoFill();

  // Also watch for dynamically loaded forms (SPAs)
  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (mutation.addedNodes.length > 0) {
        const hasForm = Array.from(mutation.addedNodes).some(
          (node) => node.nodeType === 1 && (node.tagName === "FORM" || node.querySelector?.("form, input"))
        );
        if (hasForm) {
          // Re-create FAB if it was removed (SPA navigation)
          createFAB();
          break;
        }
      }
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
}

// Run when DOM is ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
