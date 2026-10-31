# iBuddy Bridge — Chrome extension

**English** · [Português](README.pt-BR.md)

Reads the usage of your account's **5-hour window** (the same number as the app's
"Usage" tab) and tells the i-buddy daemon, so the head changes color with your
consumption and the heart pulses when the window renews.

## How it works

- It uses the session that is **already logged in** in your Chrome (like the usage
  trackers in the store): no token, no password, no vault.
- It makes two reads on `claude.ai`: `/api/organizations` and
  `/api/organizations/{id}/usage`. **That endpoint is undocumented and unofficial**
  — it can change or break without notice.
- The **only thing that leaves** the extension is the level
  (`low`/`medium`/`high`/`critical`), sent to the daemon at `127.0.0.1:8765`.
  Nothing goes to the internet.
- It runs in the extension's *service worker* (not in the page) so it can talk to
  `localhost` without Chrome's Private Network Access block.
- Instead of polling every X minutes, it keeps a connection open to the daemon
  (`/wait-activity`) that only returns when a response finishes (or every ~25 s as
  a safety heartbeat). The color therefore reacts soon after a burst of usage
  without hammering `claude.ai`. A 1-minute alarm remains as a safety net.

## Install (once)

1. Open `chrome://extensions` and turn on **Developer mode**.
2. Click **Load unpacked** and select this folder (`chrome-extension/`, inside the
   repository).
3. Stay logged in to `claude.ai` and keep the daemon running.

After editing `background.js`, reload the extension (↻ button on its card).

## Colors

| 5-hour window usage | Head |
|---|---|
| under 50 % | green |
| 50 to 74 % | blue |
| 75 to 84 % | purple |
| 85 % or more | red |

The heart pulses when usage **drops** from one reading to the next (within a window
usage only goes up, so a drop means the window renewed). Comparing the `resets_at`
timestamp doesn't work: the API returns it with millisecond noise, and when the
real reset time falls near a minute boundary the noise crosses it and triggers a
false positive on every reading.

## Limitation

It only updates while Chrome is open and logged in. If you close Chrome, the color
freezes at the last value read.

## Tests

```
node tests/extension/test_background.mjs
```
