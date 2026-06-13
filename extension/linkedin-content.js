(function initNexusReachLinkedInCompanion() {
  const PANEL_ID = "nexusreach-companion-panel";
  const MAX_GRAPH_ITEMS = 2500;
  const TEST_MODE = Boolean(window.__NEXUSREACH_LINKEDIN_COMPANION_TEST_HOOKS__);

  function wait(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, TEST_MODE ? 0 : ms));
  }

  function normalizeLinkedInUrl(url) {
    if (!url) return null;
    try {
      const parsed = new URL(url, window.location.origin);
      if (!parsed.hostname.includes("linkedin.com")) return null;
      parsed.search = "";
      parsed.hash = "";
      return parsed.toString().replace(/\/+$/, "");
    } catch {
      return null;
    }
  }

  function textOf(node) {
    return (node?.textContent || "").replace(/\s+/g, " ").trim();
  }

  function labelOf(node) {
    return (
      node?.getAttribute?.("aria-label")
      || node?.getAttribute?.("title")
      || textOf(node)
      || ""
    ).replace(/\s+/g, " ").trim();
  }

  function linesOf(node) {
    return (node?.innerText || node?.textContent || "")
      .split(/\n+/)
      .map((line) => line.replace(/\s+/g, " ").trim())
      .filter(Boolean);
  }

  function isVisible(node) {
    if (!(node instanceof Element)) return false;
    const style = window.getComputedStyle(node);
    if (style.display === "none" || style.visibility === "hidden") return false;
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function panel() {
    let existing = document.getElementById(PANEL_ID);
    if (existing) return existing;

    existing = document.createElement("div");
    existing.id = PANEL_ID;
    existing.style.position = "fixed";
    existing.style.top = "16px";
    existing.style.right = "16px";
    existing.style.zIndex = "2147483647";
    existing.style.width = "320px";
    existing.style.maxWidth = "calc(100vw - 32px)";
    existing.style.padding = "14px";
    existing.style.borderRadius = "14px";
    existing.style.border = "1px solid rgba(2, 132, 199, 0.25)";
    existing.style.background = "rgba(255, 255, 255, 0.98)";
    existing.style.boxShadow = "0 18px 40px rgba(15, 23, 42, 0.15)";
    existing.style.fontFamily = "system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
    existing.style.color = "#0f172a";
    existing.style.fontSize = "12px";
    document.body.appendChild(existing);
    return existing;
  }

  function renderPanel(context, status) {
    const root = panel();
    const warmPath = context.warmPath?.reason
      ? `<div style="margin-top:6px;color:#475569;"><strong>Warm path:</strong> ${context.warmPath.reason}</div>`
      : "";
    const linkedinSignal = context.linkedinSignal?.reason
      ? `<div style="margin-top:6px;color:#475569;"><strong>LinkedIn signal:</strong> ${context.linkedinSignal.reason}</div>`
      : "";
    root.innerHTML = `
      <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;">
        <div>
          <div style="font-size:11px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:#0369a1;">NexusReach Companion</div>
          <div style="margin-top:4px;font-size:14px;font-weight:700;color:#0f172a;">${context.personName || "LinkedIn assist"}</div>
          ${context.companyName ? `<div style="margin-top:2px;color:#475569;">${context.companyName}</div>` : ""}
          ${context.jobTitle ? `<div style="margin-top:2px;color:#64748b;">${context.jobTitle}</div>` : ""}
        </div>
        <div style="padding:4px 8px;border-radius:999px;background:#e0f2fe;color:#075985;font-weight:600;">Manual send only</div>
      </div>
      ${warmPath}
      ${linkedinSignal}
      <div style="margin-top:10px;padding-top:10px;border-top:1px solid rgba(148, 163, 184, 0.25);color:#334155;">
        ${status}
      </div>
    `;
  }

  function detectBlockedState() {
    const href = window.location.href;
    if (href.includes("/checkpoint/") || href.includes("/challenge/")) {
      return "LinkedIn checkpoint detected. Complete the challenge manually and try again.";
    }
    const bodyText = textOf(document.body);
    if (/sign in/i.test(bodyText) && /join now/i.test(bodyText)) {
      return "LinkedIn is not logged in in this browser session.";
    }
    return null;
  }

  function queryFirst(selectors) {
    for (const selector of selectors) {
      const element = document.querySelector(selector);
      if (element && isVisible(element)) return element;
    }
    return null;
  }

  function queryTextButton(labels) {
    const wanted = labels.map((label) => label.toLowerCase());
    const nodes = Array.from(
      document.querySelectorAll(
        'button, a[role="button"], div[role="button"], span[role="button"], [role="tab"], [role="radio"], label',
      ),
    );

    for (const node of nodes) {
      if (!isVisible(node)) continue;
      const content = textOf(node).toLowerCase();
      const aria = (node.getAttribute("aria-label") || "").toLowerCase();
      if (wanted.some((label) => matchesControlLabel(content, label) || matchesControlLabel(aria, label))) {
        return node;
      }
    }
    return null;
  }

  function matchesControlLabel(value, label) {
    if (!value) return false;
    if (label === "connect") {
      return (
        /\bconnect\b/i.test(value)
        && !/\b(disconnect|connected|connections?)\b/i.test(value)
      );
    }
    if (value === label) return true;
    if (label.length <= 3) return value.split(/\s+/).includes(label);
    if (value.includes(label)) return true;
    return false;
  }

  function safeClick(node) {
    if (!node) return false;
    node.scrollIntoView({ behavior: "smooth", block: "center" });
    node.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
    node.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true }));
    node.click();
    return true;
  }

  async function fillEditable(text) {
    const textbox = await waitForElement(() =>
      queryFirst([
        'div[role="textbox"][contenteditable="true"]',
        'div[contenteditable="true"][aria-label*="message" i]',
        "textarea#custom-message",
        'textarea[name="message"]',
        "textarea",
      ]),
    );

    if (!textbox) {
      return false;
    }

    textbox.focus();
    if (textbox instanceof HTMLTextAreaElement || textbox instanceof HTMLInputElement) {
      const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(textbox), "value")?.set;
      if (setter) {
        setter.call(textbox, text);
      } else {
        textbox.value = text;
      }
      textbox.dispatchEvent(new Event("input", { bubbles: true }));
      textbox.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }

    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(textbox);
    selection?.removeAllRanges();
    selection?.addRange(range);

    const inserted = document.execCommand?.("insertText", false, text);
    if (!inserted) {
      textbox.textContent = text;
    }
    textbox.dispatchEvent(new InputEvent("beforeinput", { bubbles: true, data: text, inputType: "insertText" }));
    textbox.dispatchEvent(new InputEvent("input", { bubbles: true, data: text, inputType: "insertText" }));
    return true;
  }

  async function waitForElement(getter, timeoutMs = 9000, intervalMs = 250) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const node = getter();
      if (node) return node;
      await wait(intervalMs);
    }
    return null;
  }

  function captureProfile(targetUrl) {
    const heading = queryFirst(["h1"]);
    const headline = queryFirst([
      ".text-body-medium.break-words",
      ".pv-text-details__left-panel .text-body-medium",
      ".pv-top-card-profile-picture__container + div .text-body-medium",
    ]);
    const location = queryFirst([
      ".text-body-small.inline.t-black--light.break-words",
      ".pv-text-details__left-panel .text-body-small",
    ]);
    const about = Array.from(document.querySelectorAll("section"))
      .find((section) => /about/i.test(textOf(section)))
      ?.querySelector("span[aria-hidden='true'], .inline-show-more-text span");
    const experienceSection = Array.from(document.querySelectorAll("section"))
      .find((section) => /experience/i.test(textOf(section)));
    const experienceLines = linesOf(experienceSection);

    const experienceRole = experienceLines.find((line) => line.toLowerCase() !== "experience") || null;
    const experienceCompany = experienceLines.length > 1 ? experienceLines[1] : null;

    return {
      linkedin_url: normalizeLinkedInUrl(targetUrl || window.location.href),
      visible_name: textOf(heading) || null,
      headline: textOf(headline) || null,
      location: textOf(location) || null,
      current_role_title: experienceRole,
      current_company_label: experienceCompany,
      about_snippet: textOf(about).slice(0, 500) || null,
      recent_experience_snippet: experienceLines.slice(0, 3).join(" · ") || null,
      captured_at: new Date().toISOString(),
    };
  }

  async function runAssist(payload) {
    const blocked = detectBlockedState();
    renderPanel(payload, blocked || "Preparing LinkedIn assist…");
    if (blocked) {
      return { action: payload.action, status: "blocked", message: blocked };
    }

    await wait(800);
    const capture = captureProfile(payload.linkedinUrl);

    if (payload.action === "open_profile") {
      renderPanel(payload, "Profile opened. Review the page manually. NexusReach captured fresh visible profile context.");
      return {
        action: payload.action,
        status: "completed",
        message: "LinkedIn profile opened. Fresh visible context captured.",
        capture,
      };
    }

    if (!payload.draftText) {
      return { action: payload.action, status: "blocked", message: "No draft text was provided for LinkedIn assist." };
    }

    if (payload.action === "linkedin_message") {
      const messageButton = queryTextButton(["message"]);
      if (!safeClick(messageButton)) {
        renderPanel(payload, "Message composer not available for this profile.");
        return {
          action: payload.action,
          status: "blocked",
          message: "Message composer not available for this profile.",
          capture,
        };
      }
      await wait(1000);
      const inserted = await fillEditable(payload.draftText);
      if (!inserted) {
        renderPanel(payload, "Could not find the LinkedIn message editor.");
        return {
          action: payload.action,
          status: "blocked",
          message: "Could not find the LinkedIn message editor.",
          capture,
        };
      }
      renderPanel(payload, "Draft inserted into LinkedIn messages. Review and send manually.");
      return {
        action: payload.action,
        status: "completed",
        message: "Draft inserted into LinkedIn messages. Review and send manually.",
        capture,
      };
    }

    const connectButton = await findConnectButton();
    if (!connectButton) {
      renderPanel(payload, "Connect flow is not available. The person may already be connected or LinkedIn changed the page.");
      return {
        action: payload.action,
        status: "blocked",
        message: "Connect flow is not available. The person may already be connected or LinkedIn changed the page.",
        capture,
      };
    }

    safeClick(connectButton);
    await wait(800);
    const addNoteButton = queryTextButton(["add a note", "note"]);
    if (!addNoteButton) {
      renderPanel(payload, "Could not find the Add a note step in LinkedIn's connect flow.");
      return {
        action: payload.action,
        status: "blocked",
        message: "Could not find the Add a note step in LinkedIn's connect flow.",
        capture,
      };
    }

    safeClick(addNoteButton);
    await wait(800);
    const inserted = await fillEditable(payload.draftText);
    if (!inserted) {
      renderPanel(payload, "Could not find the LinkedIn note editor.");
      return {
        action: payload.action,
        status: "blocked",
        message: "Could not find the LinkedIn note editor.",
        capture,
      };
    }

    renderPanel(payload, "Draft inserted into the LinkedIn connection note. Review and send manually.");
    return {
      action: payload.action,
      status: "completed",
      message: "Draft inserted into the LinkedIn connection note. Review and send manually.",
      capture,
    };
  }

  async function findConnectButton() {
    const direct = queryTextButton(["connect"]);
    if (direct) return direct;

    const moreButton = queryTextButton(["more"]);
    if (!moreButton) return null;

    safeClick(moreButton);
    await wait(600);
    return queryTextButton(["connect"]);
  }

  async function autoScroll(maxPasses = 10, anchorSelector = 'a[href*="/in/"], a[href*="/company/"]') {
    let previousHeight = -1;
    let previousCount = -1;
    let stablePasses = 0;
    for (let pass = 0; pass < maxPasses; pass += 1) {
      clickVisibleShowMore();

      const nextHeight = scrollGraphContainers();
      await wait(800);

      const nextCount = document.querySelectorAll(anchorSelector).length;
      if (nextCount >= MAX_GRAPH_ITEMS) {
        break;
      }

      if (nextHeight === previousHeight && nextCount === previousCount) {
        stablePasses += 1;
      } else {
        stablePasses = 0;
      }
      if (stablePasses >= 3) {
        break;
      }

      previousHeight = nextHeight;
      previousCount = nextCount;
    }
    window.scrollTo(0, 0);
  }

  function clickVisibleShowMore() {
    const showMoreButtons = Array.from(
      document.querySelectorAll('button, a[role="button"], div[role="button"]'),
    ).filter((node) => {
      const label = labelOf(node).toLowerCase();
      return isVisible(node) && (label.includes("show more results") || label === "show more");
    });

    for (const button of showMoreButtons.slice(0, 2)) {
      safeClick(button);
    }
  }

  function scrollGraphContainers() {
    const containers = [
      document.scrollingElement,
      document.documentElement,
      document.body,
      ...Array.from(document.querySelectorAll("main, section, div")),
    ].filter((node, index, list) => {
      if (!node || !(node instanceof Element) || list.indexOf(node) !== index) return false;
      if (!isVisible(node) && node !== document.documentElement && node !== document.body) return false;
      return node.scrollHeight > node.clientHeight + 16;
    });

    let maxHeight = document.body.scrollHeight;
    for (const container of containers) {
      maxHeight = Math.max(maxHeight, container.scrollHeight);
      container.scrollTop = container.scrollHeight;
      container.dispatchEvent(new Event("scroll", { bubbles: true }));
    }
    window.scrollTo(0, maxHeight);
    window.dispatchEvent(new Event("scroll"));
    return maxHeight;
  }

  function inferCompanyFromHeadline(headline) {
    if (!headline) return null;
    const match = headline.match(/\bat\s+(.+)$/i);
    return match?.[1]?.trim() || null;
  }

  function uniqueBy(items, keyFn) {
    const seen = new Set();
    const result = [];
    for (const item of items) {
      const key = keyFn(item);
      if (!key || seen.has(key)) continue;
      seen.add(key);
      result.push(item);
    }
    return result;
  }

  function scrapeConnections() {
    const anchors = Array.from(document.querySelectorAll('a[href*="/in/"]'));
    const rawItems = anchors
      .map((anchor) => {
        const linkedinUrl = normalizeLinkedInUrl(anchor.href);
        const container = graphCardFor(anchor);
        const lines = linesOf(container);
        const fullName = cleanGraphName(labelOf(anchor) || lines[0], "person");
        const headline = lines.find((line) => line && line !== fullName && !/message|remove/i.test(line)) || null;
        return {
          full_name: fullName || null,
          linkedin_url: linkedinUrl,
          headline,
          current_company_name: inferCompanyFromHeadline(headline),
        };
      })
      .filter((item) => item.full_name && item.linkedin_url);

    return uniqueBy(rawItems, (item) => item.linkedin_url).slice(0, MAX_GRAPH_ITEMS);
  }

  async function switchFollowTab(label) {
    const tab = queryTextButton([label]);
    if (!tab) return false;
    safeClick(tab);
    await wait(1000);
    return true;
  }

  function scrapeFollows(entityType) {
    const selector = entityType === "company"
      ? 'a[href*="/company/"], a[href*="/showcase/"]'
      : 'a[href*="/in/"]';
    const anchors = Array.from(document.querySelectorAll(selector));
    const rawItems = anchors
      .map((anchor) => {
        const linkedinUrl = normalizeLinkedInUrl(anchor.href);
        const container = graphCardFor(anchor);
        const lines = linesOf(container);
        const displayName = cleanGraphName(labelOf(anchor) || lines[0], entityType);
        const headline = lines.find((line) => line && line !== displayName && !/following|unfollow/i.test(line)) || null;
        return {
          entity_type: entityType,
          display_name: displayName || null,
          linkedin_url: linkedinUrl,
          headline,
          current_company_name: entityType === "person" ? inferCompanyFromHeadline(headline) : displayName || null,
        };
      })
      .filter((item) => item.display_name && item.linkedin_url);

    return uniqueBy(rawItems, (item) => item.linkedin_url).slice(0, MAX_GRAPH_ITEMS);
  }

  function findVisibleOwnProfileAnchor() {
    const anchors = Array.from(document.querySelectorAll('a[href*="/in/"]'))
      .filter((anchor) => anchor instanceof HTMLAnchorElement && isVisible(anchor));

    const viewProfileLink = anchors.find((anchor) =>
      /view profile/i.test(labelOf(anchor)) || /view profile/i.test(textOf(anchor)),
    );
    if (viewProfileLink) return viewProfileLink;

    return anchors.find((anchor) => {
      let current = anchor.parentElement;
      for (let depth = 0; current && depth < 6; depth += 1) {
        const content = textOf(current);
        if (/settings\s*&\s*privacy/i.test(content) && /sign out/i.test(content)) {
          return true;
        }
        current = current.parentElement;
      }
      return false;
    }) || null;
  }

  async function resolveSelfProfile() {
    const existing = findVisibleOwnProfileAnchor();
    if (existing) {
      return {
        status: "completed",
        profileUrl: normalizeLinkedInUrl(existing.href),
      };
    }

    const meButton = queryTextButton(["me"]);
    if (!safeClick(meButton)) {
      return {
        status: "blocked",
        profileUrl: null,
        message: "Could not open the LinkedIn Me menu to resolve your profile URL.",
      };
    }

    await wait(700);
    const profileAnchor = await waitForElement(() => findVisibleOwnProfileAnchor(), 3000, 250);
    return {
      status: profileAnchor ? "completed" : "blocked",
      profileUrl: profileAnchor ? normalizeLinkedInUrl(profileAnchor.href) : null,
      message: profileAnchor
        ? "Resolved LinkedIn profile URL."
        : "Could not find a profile link in the LinkedIn Me menu.",
    };
  }

  function graphCardFor(anchor) {
    return anchor.closest(
      [
        "li",
        ".mn-connection-card",
        ".artdeco-card",
        ".artdeco-list__item",
        ".entity-result",
        ".reusable-search__result-container",
        "[data-view-name*='profile']",
        "[data-view-name*='follow']",
      ].join(", "),
    ) || anchor.parentElement;
  }

  function cleanGraphName(rawName, entityType) {
    const fallback = entityType === "company" ? "Company" : "Profile";
    const cleaned = (rawName || "")
      .replace(/^view\s+/i, "")
      .replace(/\s+(profile|company)\s*$/i, "")
      .replace(/^send a message to\s+/i, "")
      .replace(/^click to stop following\s+/i, "")
      .replace(/\s+\d[\d,.\s]*\s+followers?.*$/i, "")
      .replace(/\s+following,\s*click to unfollow.*$/i, "")
      .replace(/\s+profile.*$/i, "")
      .replace(/\s+/g, " ")
      .trim();
    if (!cleaned || /^linkedin$/i.test(cleaned)) return null;
    if (/^(home|my network|jobs|messaging|notifications|learning|for business)$/i.test(cleaned)) {
      return null;
    }
    return cleaned || fallback;
  }

  async function runConnectionScrape() {
    const blocked = detectBlockedState();
    if (blocked) {
      return { status: "blocked", message: blocked, connections: [] };
    }
    await waitForElement(() => document.querySelector('a[href*="/in/"]'), 15000, 500);
    await autoScroll(120, 'a[href*="/in/"]');
    const connections = scrapeConnections();
    return {
      status: "completed",
      message: `Collected ${connections.length} LinkedIn connections.`,
      connections,
    };
  }

  async function runFollowScrape(payload = {}) {
    const blocked = detectBlockedState();
    if (blocked) {
      return { status: "blocked", message: blocked, follows: [], warnings: [blocked] };
    }

    if (payload.entityType === "person" || payload.entityType === "company") {
      const selector = payload.entityType === "company"
        ? 'a[href*="/company/"], a[href*="/showcase/"]'
        : 'a[href*="/in/"]';
      if (payload.entityType === "company" && window.location.href.includes("/details/interests/")) {
        await switchFollowTab("companies");
      }
      await waitForElement(() => document.querySelector(selector), 15000, 500);
      await autoScroll(120, selector);
      const follows = scrapeFollows(payload.entityType);
      const warnings = follows.length
        ? []
        : [`LinkedIn ${payload.entityType} follows page loaded, but no visible follow rows were parsed.`];
      return {
        status: "completed",
        message: `Collected ${follows.length} ${payload.entityType} follow signals.`,
        follows,
        warnings,
      };
    }

    const warnings = [];
    const follows = [];

    if (await switchFollowTab("people")) {
      await autoScroll(80, 'a[href*="/in/"]');
      follows.push(...scrapeFollows("person"));
    } else if (window.location.href.includes("/people-follow/") || window.location.href.includes("/feed/following/")) {
      await autoScroll(80, 'a[href*="/in/"]');
      follows.push(...scrapeFollows("person"));
    } else {
      warnings.push("Could not open the LinkedIn People follow tab.");
    }

    if (await switchFollowTab("companies")) {
      await autoScroll(80, 'a[href*="/company/"]');
      follows.push(...scrapeFollows("company"));
    } else {
      warnings.push("Could not open the LinkedIn Companies follow tab.");
    }

    return {
      status: "completed",
      message: `Collected ${follows.length} follow signals.`,
      follows,
      warnings,
    };
  }

  function captureJobPoster() {
    // Read LinkedIn's structured "Posted by / Job poster" hirer card, which
    // appears on many job postings independently of the "Meet the hiring team"
    // section. Returns a single member object or null.
    const selectors = [
      ".job-details-jobs-unified-top-card__job-poster",
      ".hirer-card__container",
      ".jobs-poster__name",
      ".jobs-details-top-card__job-poster",
    ];
    let container = null;
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el) { container = el.closest("section, div") || el; break; }
    }
    if (!container) {
      // fall back: an element whose text says "Posted by", scoped to its card
      const labelled = Array.from(document.querySelectorAll("section, div, span"))
        .find((el) => /\bposted by\b/i.test(el.textContent || "") && el.querySelector('a[href*="/in/"]'));
      if (labelled) container = labelled;
    }
    if (!container) return null;

    const anchor = container.querySelector('a[href*="/in/"]');
    if (!anchor) return null;
    const url = normalizeLinkedInUrl(anchor.getAttribute("href"));
    if (!url) return null;
    const name = textOf(anchor).split("\n")[0].trim()
      || textOf(container.querySelector("span[aria-hidden='true'], strong"));
    if (!name || name.split(" ").length < 2) return null;
    const lines = linesOf(container).filter((l) => l && l !== name && !/\bposted by\b/i.test(l));
    const headline = lines.find((l) => l.length > 2) || null;
    return {
      name,
      profile_url: url,
      headline: headline ? headline.slice(0, 200) : null,
      role_label: "Job poster",
    };
  }

  function captureHiringTeam() {
    // Locate the "Meet the hiring team" card on a LinkedIn job posting and
    // extract the people LinkedIn itself attached to this req. Only visible
    // page content is read - nothing is fetched or expanded beyond the panel.
    const href = window.location.href;
    if (!/\/jobs\//.test(href)) {
      return { members: [], reason: "not_a_job_page" };
    }

    const section = Array.from(document.querySelectorAll("section, div"))
      .find((el) => /meet the hiring team|meet the team|hiring team/i.test((el.querySelector("h2, h3, header")?.textContent || "")));
    const scope = section || document;

    const seen = new Set();
    const members = [];

    // Capture the structured "Posted by" hirer first so its precise "Job
    // poster" label is not overwritten by the generic card scan below. Works
    // even when the posting has no "Meet the hiring team" card.
    const poster = captureJobPoster();
    if (poster) {
      seen.add(poster.profile_url);
      members.push(poster);
    }

    const cards = Array.from(scope.querySelectorAll('a[href*="/in/"]'));
    for (const anchor of cards) {
      const url = normalizeLinkedInUrl(anchor.getAttribute("href"));
      if (!url || seen.has(url)) continue;
      // climb to the card container to read the name/headline/role label
      const card = anchor.closest("li, div") || anchor;
      const name = textOf(anchor).split("\n")[0].trim()
        || textOf(card.querySelector("span[aria-hidden='true'], strong"));
      if (!name || name.split(" ").length < 2) continue;
      const lines = linesOf(card).filter((l) => l && l !== name);
      const roleLabel = lines.find((l) => /job poster|recruiter|talent|hiring manager|manager|recruit/i.test(l)) || null;
      const headline = lines.find((l) => l !== roleLabel) || null;
      seen.add(url);
      members.push({
        name,
        profile_url: url,
        headline: headline ? headline.slice(0, 200) : null,
        role_label: roleLabel,
      });
      if (members.length >= 6) break;
    }

    // job title + company from the posting header
    const jobTitle = textOf(queryFirst(["h1", ".job-details-jobs-unified-top-card__job-title"])) || null;
    const companyLabel = textOf(queryFirst([
      ".job-details-jobs-unified-top-card__company-name",
      ".jobs-unified-top-card__company-name",
      'a[href*="/company/"]',
    ])) || null;

    return { members, job_title: jobTitle, company_label: companyLabel };
  }

  function mountHiringTeamButton() {
    if (!/\/jobs\//.test(window.location.href)) return;
    const BTN_ID = "nexusreach-capture-hiring-team";
    if (document.getElementById(BTN_ID)) return;
    const btn = document.createElement("button");
    btn.id = BTN_ID;
    btn.textContent = "Capture hiring team → NexusReach";
    btn.style.cssText = [
      "position:fixed", "bottom:20px", "right:20px", "z-index:2147483647",
      "padding:10px 14px", "border-radius:999px", "border:none", "cursor:pointer",
      "background:#0369a1", "color:#fff", "font-family:system-ui,sans-serif",
      "font-size:13px", "font-weight:600", "box-shadow:0 8px 24px rgba(15,23,42,0.25)",
    ].join(";");
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      const original = btn.textContent;
      btn.textContent = "Capturing…";
      try {
        const scraped = captureHiringTeam();
        const members = (scraped.members || []).filter((m) => m && m.name && m.profile_url);
        if (!members.length) {
          btn.textContent = "No hiring team found on this page";
        } else {
          const res = await chrome.runtime.sendMessage({
            type: "SUBMIT_HIRING_TEAM",
            payload: {
              company_name: scraped.company_label || "",
              job_title: scraped.job_title || null,
              members,
            },
          });
          btn.textContent = res && res.ok
            ? `Saved ${res.stored ?? members.length} hiring contact(s)`
            : `Capture failed: ${(res && res.error) || "unknown"}`;
        }
      } catch (error) {
        btn.textContent = "Capture failed";
      } finally {
        setTimeout(() => { btn.textContent = original; btn.disabled = false; }, 4000);
      }
    });
    document.body.appendChild(btn);
  }

  if (TEST_MODE) {
    window.__NEXUSREACH_LINKEDIN_COMPANION__ = {
      captureProfile,
      captureHiringTeam,
      captureJobPoster,
      mountHiringTeamButton,
      cleanGraphName,
      matchesControlLabel,
      normalizeLinkedInUrl,
      runAssist,
      scrapeFollows,
    };
  }

  if (typeof chrome === "undefined" || !chrome.runtime?.onMessage) {
    return;
  }

  try {
    mountHiringTeamButton();
    // LinkedIn is a SPA; re-check on navigation so the button appears on job pages.
    let _lastHref = window.location.href;
    setInterval(() => {
      if (window.location.href !== _lastHref) {
        _lastHref = window.location.href;
        mountHiringTeamButton();
      }
    }, 1500);
  } catch (_e) { /* non-fatal */ }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.type === "RUN_LINKEDIN_ASSIST") {
      runAssist(message.payload || {})
        .then((result) => sendResponse(result))
        .catch((error) =>
          sendResponse({
            action: message.payload?.action || "unknown",
            status: "error",
            message: error instanceof Error ? error.message : "LinkedIn assist failed.",
          }),
        );
      return true;
    }

    if (message.type === "CAPTURE_HIRING_TEAM") {
      try {
        sendResponse({ status: "ok", ...captureHiringTeam() });
      } catch (error) {
        sendResponse({
          status: "error",
          members: [],
          message: error instanceof Error ? error.message : "Hiring-team capture failed.",
        });
      }
      return true;
    }

    if (message.type === "RUN_GRAPH_REFRESH_CONNECTIONS") {
      runConnectionScrape()
        .then((result) => sendResponse(result))
        .catch((error) =>
          sendResponse({
            status: "error",
            message: error instanceof Error ? error.message : "Connection scrape failed.",
            connections: [],
          }),
        );
      return true;
    }

    if (message.type === "RUN_GRAPH_REFRESH_FOLLOWS") {
      runFollowScrape(message.payload || {})
        .then((result) => sendResponse(result))
        .catch((error) =>
          sendResponse({
            status: "error",
            message: error instanceof Error ? error.message : "Follow scrape failed.",
            follows: [],
            warnings: ["Follow scrape failed."],
          }),
        );
      return true;
    }

    if (message.type === "RESOLVE_LINKEDIN_SELF_PROFILE") {
      resolveSelfProfile()
        .then((result) => sendResponse(result))
        .catch((error) =>
          sendResponse({
            status: "error",
            profileUrl: null,
            message: error instanceof Error ? error.message : "Could not resolve LinkedIn profile URL.",
          }),
        );
      return true;
    }

    return false;
  });
})();
