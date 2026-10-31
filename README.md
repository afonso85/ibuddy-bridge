# iBuddy Bridge

**English** · [Português](README.pt-BR.md)

Turn the **i-buddy** — the USB figurine that shipped for MSN Messenger in 2007 —
into a physical notification panel for the **Claude desktop app** on Windows. The
head shows how much of your 5-hour usage window you've spent, the heart pulses
when the window renews, the wings flap when a response finishes, and the body
swivels when Claude is waiting for you.

> **Unofficial project, not affiliated with or endorsed by Anthropic.** "Claude"
> is a trademark of Anthropic. The head color and the heart rely on an
> **internal, undocumented** `claude.ai` endpoint that can change at any time.
> It was built around a ~15-year-old unit, so the wing mechanism may act up now
> and then (see *Known limitations*).

Just own an i-buddy and want to drive it from Python on Windows? You don't need
any of the Claude parts: see [Use the driver on its own](#use-the-driver-on-its-own)
and the [protocol notes](docs/PROTOCOL.md). **No driver installation (Zadig, WinUSB)
is required** — the stock Windows HID driver is enough.

## What each signal means

| Signal | Meaning | Data source |
|---|---|---|
| **Head** | 5-hour window usage: green < 50 %, blue 50–74 %, purple 75–84 %, red ≥ 85 % | Chrome extension |
| **Heart** | The 5-hour window renewed | Chrome extension |
| **Wings** | Claude finished a response (any conversation or tab in the app) | Windows notifications |
| **Swivel** | Claude asked for permission or is waiting for you; repeats every 60 s for up to 10 min | Windows notifications |

## How it works

```
 Claude app ──notification──▶ Windows ──▶ ┐
                                          ├──▶  daemon (run_daemon.py) ──HID──▶ i-buddy
 claude.ai ◀──session── Chrome extension ─┘          127.0.0.1:8765
```

- **`ibuddy/driver.py`** — the device's HID protocol ([notes](docs/PROTOCOL.md)).
- **`ibuddy/worker.py`** — sole owner of the device: command queue, persistent
  state (color/heart) kept underneath the animations, the swivel scheduler,
  automatic reconnection.
- **`ibuddy/server.py`** — local HTTP API, bound to `127.0.0.1` only.
- **`ibuddy/notifications.py`** + **`rules.py`** — reads the Windows notification
  center and classifies each Claude notification.
- **`chrome-extension/`** — reads your usage from the already-logged-in Chrome
  session ([details](chrome-extension/README.md)).

## Requirements

- Windows (tested on 11) and Python (tested on 3.13).
- The Claude desktop app (Microsoft Store package) for wings and swivel.
- Chrome, logged in to `claude.ai`, for head and heart.
- The original i-buddy, `VID_1130 / PID_0001`.

## Install

```
pip install -r requirements.txt
python run_daemon.py
```

1. **Autostart** (starts the daemon hidden at every logon):
   `powershell -ExecutionPolicy Bypass -File scripts\install-autostart.ps1`
   — remove it with `-Remove`.
2. **Extension** (head and heart): `chrome://extensions` → Developer mode →
   *Load unpacked* → the `chrome-extension/` folder.
3. **Notifications**: Windows may ask whether the program can read your
   notifications (Settings › Privacy & security › Notifications). Without it only
   the wings and swivel are disabled.

## Try it by hand

```
python demo.py            # full choreography (or double-click Demo.bat)
python cli.py head red    # red green blue cyan yellow purple white off
python cli.py heart on 3
python cli.py flap 5
python cli.py swivel right 3
python cli.py reset
```

While the daemon is running, `demo.py` and `cli.py` pause it for the duration of
the command; when they finish it re-applies the current head color.

## Use the driver on its own

```python
import time
from ibuddy import IBuddy

with IBuddy() as buddy:
    buddy.set_state(heart=True, blue=True)   # heart + blue head
    time.sleep(2)
    buddy.flap(times=5)                      # flap the wings
```

Leaving the `with` block resets the device. If the daemon is running, stop it
first (`POST /shutdown`) or use `cli.py`, which pauses it for you.

## Local API

`127.0.0.1:8765` only. Requests coming from web pages (an `Origin` header) or with
a `Host` other than `localhost`/`127.0.0.1` are refused with 403; only Chrome
extensions and local programs (curl, Python) get through.

| Route | Effect |
|---|---|
| `GET /status` | health: connection, color, waiting, pause, age of the last successful write to the device |
| `GET /wait-activity?since=N&timeout=S` | long-poll: returns when a response finishes |
| `POST /token-level` `{"level": "low\|medium\|high\|critical\|off"}` | head color |
| `POST /session-renewed` `{"times": 3}` | pulse the heart |
| `POST /response-end` `{"times": 5, "interval": 0.2}` | flap the wings |
| `POST /waiting-start` · `/waiting-stop` | start/stop waiting mode (swivel) |
| `POST /swivel-once` `{"pulse_time": 0.5}` | a single swivel |
| `POST /pause` `{"seconds": 120}` · `/resume` | silence the daemon (it re-applies the color when it resumes) |
| `POST /reset` · `/shutdown` | turn everything off · stop the daemon |

## Configuration

- `IBUDDY_DEBUG=1` — verbose log, **includes notification text**. By default the
  log keeps only the classification, never the text.
- `IBUDDY_APP_AUMID` — if your Claude app has a different identifier
  (default: `Claude_pzs8sxrjxfjjc!Claude`).
- Timing constants (swivel, expiry, reconnection) at the top of
  `ibuddy/worker.py`; the keywords that mean "waiting for you" in
  `ibuddy/rules.py` (the defaults match English and Portuguese notifications).

The log lives in `.state/daemon.log` (rotating, 1 MB × 3) and is **not versioned**.

## Known limitations

- **Head and heart only update while Chrome is open and logged in.** Close it and
  the color freezes at the last value.
- **Wings depend on Windows showing the "response ready" notification.** If it
  doesn't appear (for example with the app in focus, or in Do Not Disturb), the
  figurine won't flap.
- **The swivel can't tell when you've answered**, so it gives up on its own after 10 min.
- **Claude Code hooks and the statusline don't run in the desktop app's *Code* tab**
  (tested: they were never called). That's why this project uses Windows
  notifications and the extension.
- The `claude.ai` usage endpoint is unofficial.
- The wing mechanism of old units can stop responding; replugging the cable
  usually fixes it. The LEDs are unaffected.
- Notification matching is keyword-based, and tuned to English and Portuguese.

## Troubleshooting

- `curl http://127.0.0.1:8765/status` — `last_write_ok_s_ago` is how long ago the
  device last accepted a write; `connected: false` means the daemon is trying to
  reconnect (every 30 s).
- `.state/daemon.log` — reconnections, warnings and errors.
- Wings/swivel do nothing: check the notification permission and run with
  `IBUDDY_DEBUG=1`.

## Tests

```
python -m unittest discover -s tests -v
node tests/extension/test_background.mjs
```

They never touch the device: they use a fake device and a controllable clock.

## Credits

The protocol was worked out from
[py3buddy](https://github.com/armijnhemel/py3buddy) (Armijn Hemel, MIT) and
[pybuddy](https://github.com/ewall/pybuddy) (ewall), and confirmed on hardware.

## License

[MIT](LICENSE).
