// Authorization tests for the background worker's message router.
//
// The worker holds the long-lived companion token and can act as the user, so
// "a message arrived" is not authorization. These pin the two properties that
// matter: the API origin cannot be redirected by a caller, and a content script
// can only send the message types its own page legitimately needs.
//
// Loaded the same way as autosync.test.mjs — the real background.js in a vm with
// stubbed chrome.*, driven through the captured onMessage listener, using the
// REAL manifest.json so the origin rules are the ones that actually ship.
// Run with: node --test extension/tests/

import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const EXT = path.join(HERE, "..");

const MANIFEST = JSON.parse(
  fs.readFileSync(path.join(EXT, "manifest.json"), "utf8"),
);
const EXTENSION_ID = "abcdefghijklmnopqrstuvwxyzabcdef";
const APP_ORIGIN = "http://localhost:5173";

function loadBackground({ store = {}, fetchImpl, manifest = MANIFEST } = {}) {
  const backing = { ...store };
  const noop = () => {};
  const ctx = { console: { ...console, warn: noop } };
  ctx.globalThis = ctx;
  vm.createContext(ctx);

  ctx.importScripts = (p) =>
    vm.runInContext(fs.readFileSync(path.join(EXT, p), "utf8"), ctx);

  const asArray = (keys) =>
    Array.isArray(keys) ? keys : typeof keys === "string" ? [keys] : Object.keys(keys || {});

  let listener = null;
  ctx.chrome = {
    storage: {
      local: {
        get: async (keys) => {
          const out = {};
          for (const k of asArray(keys)) if (k in backing) out[k] = backing[k];
          return out;
        },
        set: async (obj) => Object.assign(backing, obj),
        remove: async (keys) => {
          for (const k of asArray(keys)) delete backing[k];
        },
      },
    },
    action: { setBadgeText: noop, setBadgeBackgroundColor: noop },
    alarms: { get: async () => undefined, create: noop, onAlarm: { addListener: noop } },
    runtime: {
      id: EXTENSION_ID,
      onMessage: { addListener: (fn) => { listener = fn; } },
      onInstalled: { addListener: noop },
      onStartup: { addListener: noop },
      getManifest: () => manifest,
    },
    notifications: { create: noop },
    tabs: {},
  };
  ctx.fetch = fetchImpl || (async () => ({ ok: true, status: 200, json: async () => ({}) }));

  vm.runInContext(fs.readFileSync(path.join(EXT, "background.js"), "utf8"), ctx);
  return { ctx, backing, send: (message, sender) => {
    const responses = [];
    listener(message, sender, (r) => responses.push(r));
    return responses;
  } };
}

const fromPage = (origin) => ({ id: EXTENSION_ID, origin, tab: { id: 1 } });
const fromPopup = () => ({ id: EXTENSION_ID });

/** Did the router refuse before doing any work? */
function refused(responses) {
  return responses.length === 1 && responses[0]?.error === "Message not permitted from this page.";
}

// --- The API origin is pinned ---------------------------------------------

test("stored apiUrl from an older build is purged on start", async () => {
  const { backing } = loadBackground({ store: { apiUrl: "https://evil.example" } });
  await new Promise((r) => setTimeout(r, 0));
  assert.equal("apiUrl" in backing, false);
});

test("getConfig always reports the build-time API origin", async () => {
  const { ctx } = loadBackground({ store: { apiUrl: "https://evil.example" } });
  const cfg = await ctx.getConfig();
  assert.equal(cfg.apiUrl, ctx.NR_DEFAULTS.apiUrl);
});

test("NR_EXTENSION_CONNECT cannot redirect the API origin", async () => {
  const { ctx, backing, send } = loadBackground();
  send(
    {
      type: "NR_EXTENSION_CONNECT",
      payload: { apiUrl: "https://evil.example", authToken: "nrc_stolen" },
    },
    fromPage(APP_ORIGIN),
  );
  await new Promise((r) => setTimeout(r, 0));

  assert.equal(backing.apiUrl, undefined, "no attacker origin persisted");
  const cfg = await ctx.getConfig();
  assert.equal(cfg.apiUrl, ctx.NR_DEFAULTS.apiUrl);
  // The token still lands — connecting is the legitimate purpose of this call.
  assert.equal(backing.authToken, "nrc_stolen");
});

test("setConfig has no apiUrl channel at all", async () => {
  const { ctx, backing } = loadBackground();
  await ctx.setConfig({ apiUrl: "https://evil.example", authToken: "nrc_x" });
  assert.equal(backing.apiUrl, undefined);
});

// --- Sender authorization --------------------------------------------------

test("the web app may run the connect handshake", () => {
  const { send } = loadBackground();
  assert.equal(refused(send({ type: "NR_EXTENSION_PING" }, fromPage(APP_ORIGIN))), false);
});

test("the web app cannot swap in its own token via SET_TOKEN", () => {
  const { backing, send } = loadBackground();
  const responses = send(
    { type: "SET_TOKEN", token: "nrc_attacker" },
    fromPage(APP_ORIGIN),
  );
  assert.ok(refused(responses));
  assert.equal(backing.authToken, undefined);
});

test("the web app cannot drive the LinkedIn capture handlers", () => {
  const { send } = loadBackground();
  for (const type of ["CAPTURE_PROFILE", "SUBMIT_HIRING_TEAM", "START_OPPORTUNISTIC_SYNC"]) {
    assert.ok(refused(send({ type, payload: {} }, fromPage(APP_ORIGIN))), type);
  }
});

test("a job board page is limited to profile autofill", () => {
  const { send } = loadBackground();
  const board = "https://boards.greenhouse.io";
  assert.equal(refused(send({ type: "GET_PROFILE" }, fromPage(board))), false);
  for (const type of ["SET_TOKEN", "NR_EXTENSION_CONNECT", "CAPTURE_PROFILE", "LOGOUT"]) {
    assert.ok(refused(send({ type, payload: {} }, fromPage(board))), type);
  }
});

test("LinkedIn may capture, but cannot connect or set a token", () => {
  const { send } = loadBackground();
  const li = "https://www.linkedin.com";
  assert.equal(refused(send({ type: "GET_STATUS" }, fromPage(li))), false);
  for (const type of ["SET_TOKEN", "NR_EXTENSION_CONNECT"]) {
    assert.ok(refused(send({ type, payload: {} }, fromPage(li))), type);
  }
});

test("an unrelated site is refused outright", () => {
  const { send } = loadBackground();
  for (const type of ["GET_PROFILE", "NR_EXTENSION_PING", "SET_TOKEN"]) {
    assert.ok(refused(send({ type, payload: {} }, fromPage("https://evil.example"))), type);
  }
});

test("a look-alike origin does not satisfy a wildcard match pattern", () => {
  const { send } = loadBackground();
  // manifest has https://*.myworkdayjobs.com/* — this must not match.
  for (const origin of [
    "https://myworkdayjobs.com.evil.example",
    "https://www.linkedin.com.evil.example",
    "http://www.linkedin.com",
  ]) {
    assert.ok(refused(send({ type: "GET_PROFILE" }, fromPage(origin))), origin);
  }
});

test("a real Workday subdomain does match the wildcard", () => {
  const { send } = loadBackground();
  const responses = send(
    { type: "GET_PROFILE" },
    fromPage("https://acme.wd5.myworkdayjobs.com"),
  );
  assert.equal(refused(responses), false);
});

test("the popup keeps full access", () => {
  const { send } = loadBackground();
  for (const type of ["SET_TOKEN", "LOGOUT", "GET_STATUS", "GET_AUTOSYNC"]) {
    assert.equal(refused(send({ type, token: "nrc_x", enabled: true }, fromPopup())), false, type);
  }
});

test("another extension is refused", () => {
  const { send } = loadBackground();
  const responses = send({ type: "GET_PROFILE" }, { id: "someotherextensionid", tab: { id: 2 } });
  assert.ok(refused(responses));
});

test("a malformed message is refused rather than thrown on", () => {
  const { send } = loadBackground();
  assert.ok(refused(send({}, fromPopup())));
  assert.ok(refused(send({ type: 42 }, fromPopup())));
});

test("a shipped build does not answer localhost", () => {
  // build.mjs rewrites app-bridge's matches to the production app origin and
  // drops every localhost entry. Rules are derived from the live manifest, so a
  // packaged extension must refuse the dev origins outright — otherwise a user
  // running anything on localhost:5173 could drive their companion.
  const prodManifest = {
    ...MANIFEST,
    content_scripts: MANIFEST.content_scripts.map((entry) =>
      (entry.js || []).includes("app-bridge.js")
        ? { ...entry, matches: ["https://app.solomon.test/*"] }
        : { ...entry, matches: entry.matches.filter((m) => !m.includes("localhost")) },
    ),
  };
  const { send } = loadBackground({ manifest: prodManifest });

  assert.ok(refused(send({ type: "NR_EXTENSION_PING" }, fromPage("http://localhost:5173"))));
  assert.ok(refused(send({ type: "NR_EXTENSION_PING" }, fromPage("http://127.0.0.1:5173"))));
  assert.equal(
    refused(send({ type: "NR_EXTENSION_PING" }, fromPage("https://app.solomon.test"))),
    false,
  );
});

// --- app-bridge.js forwards only the app's own types -----------------------

test("app-bridge refuses to forward non-app message types", async () => {
  const forwarded = [];
  const ctx = {
    console,
    chrome: { runtime: { id: EXTENSION_ID, sendMessage: (m) => forwarded.push(m) } },
  };
  const listeners = [];
  ctx.window = {
    addEventListener: (name, fn) => name === "message" && listeners.push(fn),
    postMessage: () => {},
    location: { origin: APP_ORIGIN },
  };
  ctx.globalThis = ctx;
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(EXT, "app-bridge.js"), "utf8"), ctx);

  const post = (type) =>
    listeners[0]({
      source: ctx.window,
      data: { source: "nexusreach-web", type, requestId: "r1", payload: {} },
    });

  post("SET_TOKEN");
  post("CAPTURE_PROFILE");
  post("LOGOUT");
  assert.deepEqual(forwarded, [], "privileged types must not cross the bridge");

  post("NR_EXTENSION_PING");
  assert.equal(forwarded.length, 1);
  assert.equal(forwarded[0].type, "NR_EXTENSION_PING");
});
