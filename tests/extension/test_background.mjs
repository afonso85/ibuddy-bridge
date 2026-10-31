// Testa a logica REAL de chrome-extension/background.js sem Chrome: simula
// chrome.storage/alarms/runtime e fetch, e roda poll()/activityLoop()/levelFor().
//
//   node tests/extension/test_background.mjs
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

// --- ambiente simulado -------------------------------------------------------
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

let usageQueue = [];     // respostas de /usage, na ordem
let waitQueue = [];      // respostas de /wait-activity; vazio = fica pendurado
let daemonCalls = [];    // POSTs que chegaram ao daemon
let waitUrls = [];

const json = (data) => ({ json: async () => data });

globalThis.fetch = async (url, opts = {}) => {
  if (url.endsWith("/api/organizations")) return json([{ uuid: "org-1" }]);
  if (url.includes("/usage")) return json({ five_hour: usageQueue.shift() });
  if (url.includes("/wait-activity")) {
    waitUrls.push(url);
    if (waitQueue.length === 0) return new Promise(() => {}); // long-poll "parado"
    return json({ seq: waitQueue.shift() });
  }
  daemonCalls.push({ path: new URL(url).pathname, body: opts.body ? JSON.parse(opts.body) : null });
  return json({ ok: true });
};

function reset() {
  storage = {}; usageQueue = []; waitQueue = []; daemonCalls = []; waitUrls = [];
}
const count = (p) => daemonCalls.filter((c) => c.path === p).length;

// --- carrega o arquivo real --------------------------------------------------
const src = fs.readFileSync(path.join(here, "..", "..", "chrome-extension", "background.js"), "utf8");
const tmp = path.join(os.tmpdir(), `ibuddy_background_${process.pid}.mjs`);
fs.writeFileSync(tmp, src + "\nexport { poll, activityLoop, levelFor };\n");
const { poll, activityLoop, levelFor } = await import(pathToFileURL(tmp).href);

// --- testes ------------------------------------------------------------------
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("limiares de cor: 50 / 75 / 85", () => {
  const cases = [[0, "low"], [49, "low"], [50, "medium"], [74, "medium"],
                 [75, "high"], [84, "high"], [85, "critical"], [100, "critical"]];
  for (const [util, level] of cases) assert.equal(levelFor(util), level, `${util}%`);
});

test("coracao so pulsa quando o uso CAI (renovacao), nao com jitter do resets_at", async () => {
  // cenario real que causou o bug: resets_at oscilando em volta de uma virada de minuto
  const jitter = ["18:29:59.948896", "18:30:00.189734", "18:30:00.169048", "18:29:59.891234", "18:30:00.273798"];
  for (const t of jitter) usageQueue.push({ utilization: 21, resets_at: `2026-09-09T${t}+00:00` });
  usageQueue.push({ utilization: 3, resets_at: "2026-09-09T23:30:00.100000+00:00" }); // renovou
  usageQueue.push({ utilization: 4, resets_at: "2026-09-09T23:30:00.150000+00:00" });
  for (let i = 0; i < 7; i++) await poll();
  assert.equal(count("/session-renewed"), 1, "exatamente uma renovacao");
  assert.equal(count("/token-level"), 7, "cor enviada a cada leitura");
  assert.equal(storage.lastUtilization, 4);
});

test("queda de 1 ponto nao conta como renovacao; queda maior conta", async () => {
  usageQueue.push({ utilization: 22 }, { utilization: 21 }, { utilization: 18 });
  for (let i = 0; i < 3; i++) await poll();
  assert.equal(count("/session-renewed"), 1); // so 21 -> 18
});

test("sem sessao ou sem dados, nao envia nada ao daemon", async () => {
  usageQueue.push(undefined);
  await poll();
  assert.equal(daemonCalls.length, 0);
});

test("activityLoop relê o uso a cada retorno do long-poll e repassa 'since'", async () => {
  waitQueue.push(1, 1, 2);
  for (let i = 0; i < 3; i++) usageQueue.push({ utilization: 30 });
  await Promise.race([activityLoop(), new Promise((r) => setTimeout(r, 300))]);
  assert.equal(count("/token-level"), 3);
  assert.deepEqual(waitUrls.map((u) => new URL(u).searchParams.get("since")), ["0", "1", "1", "2"]);
});

// --- execucao ----------------------------------------------------------------
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
console.log(failed ? `\n${failed} teste(s) falharam` : `\n${tests.length} testes ok`);
process.exit(failed ? 1 : 0);
