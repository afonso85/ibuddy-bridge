// iBuddy Bridge - service worker.
// Reads the usage of your Claude account's 5-hour window using the browser's
// own already logged-in session and sends it to the i-buddy daemon. It runs in
// the service worker (not in the page) to avoid Chrome's Private Network Access
// block when talking to localhost.
//
// Reacting to usage bursts: instead of waiting for a fixed interval (chrome.alarms
// has a ~1 min floor, too slow for "burning through tokens"), we keep a long-poll
// connection open to the local daemon (/wait-activity) that only returns when a
// response finishes (or every ~25 s as a safety heartbeat). A pending fetch also
// keeps the service worker "alive" (it resets the MV3 idle timeout).
// The 1-minute alarm remains as a safety net in case the loop stops.

const DAEMON = "http://127.0.0.1:8765";
const POLL_MINUTES = 1;
const ACTIVITY_TIMEOUT = 25;

function levelFor(util) {
  if (util < 50) return "low";
  if (util < 75) return "medium";
  if (util < 85) return "high";
  return "critical";
}

async function postDaemon(path, body) {
  try {
    await fetch(DAEMON + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
  } catch (e) {
    // daemon is off - fine, ignore silently
  }
}

async function poll() {
  let usage;
  try {
    const orgs = await fetch("https://claude.ai/api/organizations", {
      credentials: "include",
    }).then((r) => r.json());
    if (!Array.isArray(orgs) || !orgs.length || !orgs[0].uuid) return; // not logged in
    const org = orgs[0].uuid;
    usage = await fetch(`https://claude.ai/api/organizations/${org}/usage`, {
      credentials: "include",
    }).then((r) => r.json());
  } catch (e) {
    return; // no session / offline - do nothing
  }

  const fh = usage && usage.five_hour;
  if (!fh || typeof fh.utilization !== "number") return;

  // head color according to the 5-hour window usage %
  await postDaemon("/token-level", { level: levelFor(fh.utilization) });

  // the heart pulses when the 5-hour window renews. We first tried comparing
  // resets_at (the ISO reset time), but that string jitters because of rounding
  // in the backend - and when the real reset time falls right on a minute
  // boundary the jitter crosses it and triggers a false positive on EVERY poll
  // (that is what happened: the heart hammering every 20-60 s). Usage, on the
  // other hand, only goes up within a window - a drop only happens when it
  // renews. A more direct signal, without the timestamp fragility.
  const { lastUtilization } = await chrome.storage.local.get("lastUtilization");
  if (typeof lastUtilization === "number" && fh.utilization < lastUtilization - 1) {
    await postDaemon("/session-renewed", {});
  }
  await chrome.storage.local.set({ lastUtilization: fh.utilization });
}

let activityLoopRunning = false;

async function activityLoop() {
  if (activityLoopRunning) return; // a loop is already running, don't duplicate
  activityLoopRunning = true;
  let since = 0;
  try {
    while (true) {
      try {
        const r = await fetch(
          `${DAEMON}/wait-activity?since=${since}&timeout=${ACTIVITY_TIMEOUT}`
        );
        const data = await r.json();
        since = typeof data.seq === "number" ? data.seq : since;
        await poll(); // real activity or safety heartbeat - re-read the usage
      } catch (e) {
        // daemon is off - wait a bit before trying again, so we don't spin in
        // a tight loop burning CPU for nothing
        await new Promise((res) => setTimeout(res, 5000));
      }
    }
  } finally {
    activityLoopRunning = false; // should never get here (while true)
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("poll", { periodInMinutes: POLL_MINUTES });
  poll();
  activityLoop();
});

chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create("poll", { periodInMinutes: POLL_MINUTES });
  poll();
  activityLoop();
});

chrome.alarms.onAlarm.addListener((a) => {
  if (a.name !== "poll") return;
  poll();
  // safety net: if the long-poll died for any reason, restart it
  if (!activityLoopRunning) activityLoop();
});
