// Guard-logic tests for the companion's auto-cadence sync (Workstream D).
//
// The extension has no bundler, so we load the real background.js service-worker
// script into a vm context with stubbed chrome.* + fetch and drive the exported
// decision functions. This pins the safety-critical behavior: auto-sync must
// never run when disconnected, disabled, within cooldown, or on a fresh/empty
// graph. Run with: node --test extension/tests/
//
// The scrape/upload run path (chrome.tabs + content-script messaging) is not
// exercised here — it's covered by the manual checklist in TESTING.md.

import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const EXT = path.join(HERE, "..");

function loadBackground({ store = {}, fetchImpl } = {}) {
  const backing = { ...store };
  const noop = () => {};
  const ctx = { console };
  ctx.globalThis = ctx;
  vm.createContext(ctx);

  ctx.importScripts = (p) =>
    vm.runInContext(fs.readFileSync(path.join(EXT, p), "utf8"), ctx);

  const asArray = (keys) =>
    Array.isArray(keys) ? keys : typeof keys === "string" ? [keys] : Object.keys(keys || {});

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
      onMessage: { addListener: noop },
      onInstalled: { addListener: noop },
      onStartup: { addListener: noop },
      getManifest: () => ({ version: "test" }),
    },
    notifications: { create: noop },
    tabs: {},
  };
  ctx.fetch =
    fetchImpl ||
    (async () => ({ ok: true, status: 200, json: async () => ({}) }));

  vm.runInContext(fs.readFileSync(path.join(EXT, "background.js"), "utf8"), ctx);
  return { ctx, backing };
}

function statusFetch(status) {
  return async (url, opts) => {
    if (url.includes("/linkedin-graph/status")) {
      return { ok: true, status: 200, json: async () => status };
    }
    // Any POST (sync-session) — a run should never reach here in guard tests.
    return { ok: true, status: 200, json: async () => ({ session_token: "s", max_batch_size: 250 }) };
  };
}

const CONNECTED = { apiUrl: "http://x", authToken: "nrc_test" };
const AGED = { connection_count: 100, days_since_sync: 10, refresh_recommended: true };

test("skips when not connected (no token)", async () => {
  const { ctx } = loadBackground({ store: {}, fetchImpl: statusFetch(AGED) });
  const r = await ctx.maybeAutoSync("alarm");
  assert.equal(r.ran, false);
  assert.equal(r.reason, "not_connected");
});

test("skips when reconnect is pending", async () => {
  const { ctx } = loadBackground({
    store: { ...CONNECTED, needsReconnect: true },
    fetchImpl: statusFetch(AGED),
  });
  const r = await ctx.maybeAutoSync("alarm");
  assert.equal(r.reason, "not_connected");
});

test("skips when auto-sync disabled", async () => {
  const { ctx } = loadBackground({
    store: { ...CONNECTED, autoSyncEnabled: false },
    fetchImpl: statusFetch(AGED),
  });
  const r = await ctx.maybeAutoSync("alarm");
  assert.equal(r.reason, "disabled");
});

test("skips within the 24h cooldown", async () => {
  const { ctx } = loadBackground({
    store: { ...CONNECTED, lastAutoSyncAt: Date.now() - 60_000 },
    fetchImpl: statusFetch(AGED),
  });
  const r = await ctx.maybeAutoSync("alarm");
  assert.equal(r.reason, "cooldown");
});

test("skips a never-synced (empty) graph", async () => {
  const { ctx } = loadBackground({
    store: { ...CONNECTED },
    fetchImpl: statusFetch({ connection_count: 0, days_since_sync: null }),
  });
  const r = await ctx.maybeAutoSync("alarm");
  assert.equal(r.reason, "fresh_or_empty");
});

test("skips a fresh graph under the staleness threshold", async () => {
  const { ctx } = loadBackground({
    store: { ...CONNECTED },
    fetchImpl: statusFetch({ connection_count: 100, days_since_sync: 3, refresh_recommended: false }),
  });
  const r = await ctx.maybeAutoSync("alarm");
  assert.equal(r.reason, "fresh_or_empty");
});

test("stale-graph nudge fires past 14 days when idle", async () => {
  const { ctx } = loadBackground({
    store: { ...CONNECTED },
    fetchImpl: statusFetch({ connection_count: 100, days_since_sync: 20 }),
  });
  const r = await ctx.shouldPromptStaleGraph();
  assert.equal(r.prompt, true);
  assert.equal(r.daysSinceSync, 20);
});

test("stale-graph nudge stays quiet under 14 days", async () => {
  const { ctx } = loadBackground({
    store: { ...CONNECTED },
    fetchImpl: statusFetch({ connection_count: 100, days_since_sync: 9 }),
  });
  const r = await ctx.shouldPromptStaleGraph();
  assert.equal(r.prompt, false);
});

test("stale-graph nudge stays quiet right after an auto-sync", async () => {
  const { ctx } = loadBackground({
    store: { ...CONNECTED, lastAutoSyncAt: Date.now() - 60_000 },
    fetchImpl: statusFetch({ connection_count: 100, days_since_sync: 20 }),
  });
  const r = await ctx.shouldPromptStaleGraph();
  assert.equal(r.prompt, false);
});
