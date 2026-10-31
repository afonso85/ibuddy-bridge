// Tests the REAL logic of chrome-extension/background.js without Chrome: it
// simulates chrome.storage/alarms/runtime and fetch, then runs
// poll()/activityLoop()/levelFor().
//
//   node tests/extension/test_background.mjs
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

// --- simulated environment ---------------------------------------------------
let storage = {};
globalThis.chrome = {
  storage: {
    local: {
      get: async (key) => ({ [key]: storage[key] }),
      set: async (obj) => Object.assign(storage, obj),
    },
  },
  alarms: { create() {}, onAlarm: { addListener() {} } },
  runtime: { onInstalled: { addListener() {} }, onStartup: { addListener() {} } },
};

let usageQueue = [];     // /usage responses, in order
let waitQueue = [];      // /wait-activity responses; empty = hangs forever
let daemonCalls = [];    // POSTs that reached the daemon
let waitUrls = [];

const json = (data) => ({ json: async () => data });

globalThis.fetch = async (url, opts = {}) => {
  if (url.endsWith("/api/organizations")) return json([{ uuid: "org-1" }]);
  if (url.includes("/usage")) return json({ five_hour: usageQueue.shift() });
  if (url.includes("/wait-activity")) {
    waitUrls.push(url);
    if (waitQueue.length === 0) return new Promise(() => {}); // long-poll "parked"
    return json({ seq: waitQueue.shift() });
  }
  daemonCalls.push({ path: new URL(url).pathname, body: opts.body ? JSON.parse(opts.body) : null });
  return json({ ok: true });
};

function reset() {
  storage = {}; usageQueue = []; waitQueue = []; daemonCalls = []; waitUrls = [];
}
const count = (p) => daemonCalls.filter((c) => c.path === p).length;

// --- load the real file ------------------------------------------------------
const src = fs.readFileSync(path.join(here, "..", "..", "chrome-extension", "background.js"), "utf8");
const tmp = path.join(os.tmpdir(), `ibuddy_background_${process.pid}.mjs`);
fs.writeFileSync(tmp, src + "\nexport { poll, activityLoop, levelFor };\n");
const { poll, activityLoop, levelFor } = await import(pathToFileURL(tmp).href);

// --- tests -------------------------------------------------------------------
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("color thresholds: 50 / 75 / 85", () => {
  const cases = [[0, "low"], [49, "low"], [50, "medium"], [74, "medium"],
                 [75, "high"], [84, "high"], [85, "critical"], [100, "critical"]];
  for (const [util, level] of cases) assert.equal(levelFor(util), level, `${util}%`);
});

test("the heart only pulses when usage DROPS (renewal), not on resets_at jitter", async () => {
  // the real scenario that caused the bug: resets_at jittering around a minute boundary
  const jitter = ["18:29:59.948896", "18:30:00.189734", "18:30:00.169048", "18:29:59.891234", "18:30:00.273798"];
  for (const t of jitter) usageQueue.push({ utilization: 21, resets_at: `2026-09-09T${t}+00:00` });
  usageQueue.push({ utilization: 3, resets_at: "2026-09-09T23:30:00.100000+00:00" }); // renewed
  usageQueue.push({ utilization: 4, resets_at: "2026-09-09T23:30:00.150000+00:00" });
  for (let i = 0; i < 7; i++) await poll();
  assert.equal(count("/session-renewed"), 1, "exactly one renewal");
  assert.equal(count("/token-level"), 7, "color sent on every reading");
  assert.equal(storage.lastUtilization, 4);
});

test("a 1-point drop is not a renewal; a bigger drop is", async () => {
  usageQueue.push({ utilization: 22 }, { utilization: 21 }, { utilization: 18 });
  for (let i = 0; i < 3; i++) await poll();
  assert.equal(count("/session-renewed"), 1); // only 21 -> 18
});

test("without a session or without data, nothing is sent to the daemon", async () => {
  usageQueue.push(undefined);
  await poll();
  assert.equal(daemonCalls.length, 0);
});

test("activityLoop re-reads the usage on every long-poll return and passes 'since'", async () => {
  waitQueue.push(1, 1, 2);
  for (let i = 0; i < 3; i++) usageQueue.push({ utilization: 30 });
  await Promise.race([activityLoop(), new Promise((r) => setTimeout(r, 300))]);
  assert.equal(count("/token-level"), 3);
  assert.deepEqual(waitUrls.map((u) => new URL(u).searchParams.get("since")), ["0", "1", "1", "2"]);
});

// --- run ---------------------------------------------------------------------
let failed = 0;
for (const [name, fn] of tests) {
  reset();
  try {
    await fn();
    console.log(`ok   - ${name}`);
  } catch (e) {
    failed++;
    console.log(`FAIL - ${name}\n       ${e.message}`);
  }
}
fs.rmSync(tmp, { force: true });
console.log(failed ? `\n${failed} test(s) failed` : `\n${tests.length} tests ok`);
process.exit(failed ? 1 : 0);
