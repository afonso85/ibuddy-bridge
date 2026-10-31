"""Background worker: sole owner of the HID connection, processes a command queue.

It exists so that two simultaneous triggers (e.g. the Chrome extension and a
"response finished" notification) never write to the HID at the same time and
collide. It keeps a "persistent" state (head color / heart) that stays on until
it is changed, and layers transient animations (wing flap, pulse, swivel) on top
of it without losing the persistent state underneath.

Besides the queue, the loop has its own scheduler (waiting swivel, reconnection,
end of pause, stale-reading blink). Its clock does NOT depend on queue traffic:
the Chrome extension sends a command every <=25 s, and a timer based on "queue
idle for N seconds" never fired while it was active.
"""
import logging
import os
import queue
import threading
import time

from .driver import IBuddy, IBuddyNotFoundError

log = logging.getLogger("ibuddy.worker")

LEVEL_COLORS = {
    "low": dict(green=True),
    "medium": dict(blue=True),
    "high": dict(red=True, blue=True),
    "critical": dict(red=True),
    "off": dict(),
}


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


WAITING_PULSE_INTERVAL = 60.0   # seconds between swivels while "waiting for you"
WAITING_MAX_SECONDS = 600.0     # give up after this: there is no way to know you already answered
WAITING_PULSE_TIME = 0.5        # duration of each half swivel
PAUSE_MAX_SECONDS = 600.0       # cap for a pause (demo/cli); it expires on its own
FLAP_DEDUP_SECONDS = 5.0        # two notifications close together = one response
RECONNECT_INTERVAL = 30.0       # active reconnection attempts while disconnected

# No color reading for this long = the value on the head is stale (Chrome closed,
# logged out, extension stopped...): the head keeps its last color but blinks.
STALE_AFTER_SECONDS = _env_float("IBUDDY_STALE_SECONDS", 300.0)
STALE_BLINK_ON = 1.0            # seconds lit in each blink cycle
STALE_BLINK_OFF = 0.5           # seconds dark in each blink cycle


class BuddyWorker(threading.Thread):
    def __init__(self, buddy_factory=IBuddy):
        super().__init__(daemon=True)
        self._buddy_factory = buddy_factory
        self._queue = queue.Queue()
        self._buddy = None
        self._connected = False
        self._ever_connected = False
        self._lock = threading.Lock()
        self._created_at = time.monotonic()

        # persistent state (what stays "on" between animations)
        self._heart = False
        self._color = dict(LEVEL_COLORS["off"])

        # color freshness: blinks when no reading arrives for a long time
        self._color_seen = False        # at least one reading since the daemon started
        self._last_color_at = 0.0
        self._stale = False
        self._blink_off = False         # True during the dark phase of the blink
        self._next_blink = 0.0

        # waiting mode ("Claude is waiting for you")
        self._waiting = False
        self._waiting_since = 0.0
        self._next_pulse = 0.0

        # pause (demo/cli drive the HID directly; the daemon stays quiet)
        self._paused_until = 0.0
        self._pause_reapply = False

        self._next_reconnect = 0.0
        self._last_flap = -FLAP_DEDUP_SECONDS

        # "a response happened" counter for the extension's long-poll (lets it
        # react at once to usage bursts without depending on the 1-minute
        # minimum interval of chrome.alarms)
        self._activity_seq = 0
        self._activity_cond = threading.Condition()

    # --- public API, called by the HTTP server (thread-safe) ---

    def submit(self, action, **kwargs):
        self._queue.put((action, kwargs))

    def shutdown(self):
        self._queue.put(("_shutdown", {}))

    def pause(self, seconds):
        """Silence the daemon (no HID writes) for up to 'seconds'. Synchronous:
        it takes effect as soon as it returns; running animations abort on their
        next step."""
        seconds = max(0.0, min(float(seconds), PAUSE_MAX_SECONDS))
        with self._lock:
            self._paused_until = time.monotonic() + seconds
            self._pause_reapply = True

    def resume(self):
        with self._lock:
            self._paused_until = 0.0
        self.submit("reapply")  # also wakes the loop

    def wait_activity(self, since, timeout):
        """Block until the activity counter exceeds 'since' or the timeout
        expires. Used by the Chrome extension's long-poll."""
        with self._activity_cond:
            self._activity_cond.wait_for(
                lambda: self._activity_seq > since, timeout=timeout)
            return self._activity_seq

    def status(self):
        now = time.monotonic()
        last_ok = getattr(self._buddy, "last_write_ok", None)
        with self._lock:
            return {
                "connected": self._connected,
                "heart": self._heart,
                "color": dict(self._color),
                "stale": self._stale,
                "color_age_s": round(now - self._last_color_at) if self._color_seen else None,
                "waiting": self._waiting,
                "waiting_for_s": round(now - self._waiting_since) if self._waiting else None,
                "paused": now < self._paused_until,
                "last_write_ok_s_ago": round(now - last_ok, 1) if last_ok else None,
                "uptime_s": round(now - self._created_at),
            }

    # --- main loop ---

    def run(self):
        self._guarded("initial connection", self._ensure_connected)
        while True:
            try:
                action, kwargs = self._queue.get(timeout=self._seconds_to_next_deadline())
            except queue.Empty:
                action, kwargs = None, {}

            if action == "_shutdown":
                self._safe_reset()
                break
            if action is not None:
                self._guarded(action, self._dispatch, action, kwargs)
            self._guarded("scheduler", self._run_scheduled)

    def _guarded(self, label, fn, *args):
        """Nothing may escape from here: if the worker thread dies, the whole
        daemon hangs (the HTTP server stays up but nobody processes commands)."""
        try:
            fn(*args)
        except IBuddyNotFoundError:
            self._connected = False
            log.warning("i-buddy disconnected during '%s'", label)
        except Exception:
            log.exception("error in '%s'", label)

    def _dispatch(self, action, kwargs):
        handler = getattr(self, "_do_" + action, None)
        if handler is None:
            log.warning("unknown action: %r", action)
            return
        handler(**kwargs)

    # --- scheduler ---

    def _blink_applies(self):
        """The blink only makes sense if some head color has been shown."""
        return self._color_seen and bool(self._color)

    def _seconds_to_next_deadline(self):
        now = time.monotonic()
        with self._lock:
            deadlines = []
            if self._waiting:
                deadlines.append(self._next_pulse)
            if self._pause_reapply:
                deadlines.append(self._paused_until)
            if not self._connected:
                deadlines.append(self._next_reconnect)
            if self._blink_applies():
                deadlines.append(self._next_blink if self._stale
                                 else self._last_color_at + STALE_AFTER_SECONDS)
        return max(0.0, min(deadlines) - now) if deadlines else None

    def _run_scheduled(self):
        now = time.monotonic()
        reapply = pulse = expired = reconnect = went_stale = blink = False
        with self._lock:
            if self._pause_reapply and now >= self._paused_until:
                self._pause_reapply = False
                reapply = True
            if self._waiting and now >= self._next_pulse:
                if now - self._waiting_since > WAITING_MAX_SECONDS:
                    self._waiting = False
                    expired = True
                else:
                    self._next_pulse = now + WAITING_PULSE_INTERVAL
                    pulse = True
            if not self._connected and now >= self._next_reconnect:
                self._next_reconnect = now + RECONNECT_INTERVAL
                reconnect = True
            if self._blink_applies():
                if not self._stale and now - self._last_color_at >= STALE_AFTER_SECONDS:
                    self._stale = True
                    self._blink_off = False   # starts lit; the first toggle comes later
                    self._next_blink = now + STALE_BLINK_ON
                    went_stale = True
                elif self._stale and now >= self._next_blink:
                    self._blink_off = not self._blink_off
                    self._next_blink = now + (STALE_BLINK_OFF if self._blink_off
                                              else STALE_BLINK_ON)
                    blink = True

        if expired:
            log.info("waiting mode expired after %.0fs without a new notice", WAITING_MAX_SECONDS)
        if went_stale:
            log.warning("no usage reading for %.0fs (Chrome closed or logged out?): "
                        "the head keeps its last color but now blinks", STALE_AFTER_SECONDS)
        if reconnect:
            self._ensure_connected()
        if reapply:
            self._apply_base()
        if pulse and not self._paused():
            self._waiting_pulse()
        if blink and self._connected:   # no reconnection churn at every toggle
            self._apply_base()

    def _paused(self):
        return time.monotonic() < self._paused_until

    # --- connection and hardware writes ---

    def _ensure_connected(self):
        if self._connected:
            return
        if self._buddy is not None:
            self._buddy.abandon()  # drop the old handle (it may be invalid)
            self._buddy = None
        try:
            buddy = self._buddy_factory()
            buddy.connect()
        except IBuddyNotFoundError:
            return
        self._buddy = buddy
        self._connected = True
        reconnected = self._ever_connected
        self._ever_connected = True
        log.info("i-buddy %s", "reconnected" if reconnected else "connected")
        if reconnected and not self._paused():
            self._write_state()  # re-apply the color/heart the device lost

    def _write_state(self, **extra):
        """Write the persistent state (+ transient effects in 'extra').
        Returns False if there is no device."""
        self._ensure_connected()
        if not self._connected:
            return False
        with self._lock:
            heart = self._heart
            # dark phase of the stale blink: heart and animations still show
            color = {} if (self._stale and self._blink_off) else dict(self._color)
        effects = {**color, **extra}
        heart = effects.pop("heart", heart)
        self._buddy.set_state(heart=heart, **effects)
        return True

    def _apply_base(self):
        """Re-send the current persistent state (heart + color) to the hardware."""
        if not self._paused():
            self._write_state()

    def _safe_reset(self):
        if self._connected and self._buddy is not None:
            try:
                self._buddy.reset()
                self._buddy.close()
            except Exception:
                pass

    def _waiting_pulse(self):
        with self._lock:
            elapsed = time.monotonic() - self._waiting_since
        log.info("waiting swivel (waiting for %.0fs)", elapsed)
        if not self._write_state(swivel="right"):
            return
        time.sleep(WAITING_PULSE_TIME)
        self._write_state(swivel="left")
        time.sleep(WAITING_PULSE_TIME)
        self._write_state()

    # --- actions (dispatched by _dispatch from the queue) ---

    def _do_set_color(self, level="off"):
        now = time.monotonic()
        with self._lock:
            self._color = dict(LEVEL_COLORS.get(level, LEVEL_COLORS["off"]))
            self._color_seen = True
            self._last_color_at = now
            was_stale = self._stale
            self._stale = False
            self._blink_off = False
        if was_stale:
            log.info("fresh usage reading received: the head is solid again")
        self._apply_base()

    def _do_heart_pulse(self, times=3):
        for _ in range(times):
            if self._paused() or not self._write_state(heart=True):
                return
            time.sleep(0.3)
            if not self._write_state(heart=False):
                return
            time.sleep(0.3)
        with self._lock:
            self._heart = False
        self._apply_base()

    def _do_flap(self, times=5, interval=0.2):
        # dedup: two notifications close together = one response
        now = time.monotonic()
        if now - self._last_flap < FLAP_DEDUP_SECONDS:
            return
        self._last_flap = now
        self._bump_activity()
        with self._lock:
            self._waiting = False  # the response finished, it is no longer waiting
        for _ in range(times):
            if self._paused() or not self._write_state(wings="up"):
                return
            time.sleep(interval)
            if not self._write_state(wings="down"):
                return
            time.sleep(interval)
        self._apply_base()

    def _do_waiting_start(self):
        now = time.monotonic()
        with self._lock:
            if not self._waiting:
                self._waiting = True
                self._next_pulse = now + WAITING_PULSE_INTERVAL
            self._waiting_since = now  # a new notice extends the deadline

    def _do_waiting_stop(self):
        with self._lock:
            self._waiting = False
        self._apply_base()

    def _do_reset(self):
        with self._lock:
            self._heart = False
            self._color = dict(LEVEL_COLORS["off"])
            self._color_seen = False
            self._stale = False
            self._blink_off = False
            self._waiting = False
        self._ensure_connected()
        if self._connected:
            self._buddy.reset()

    def _do_swivel_once(self, pulse_time=WAITING_PULSE_TIME):
        """A one-off swivel on demand (demo/test); leaves the persistent state alone."""
        if self._paused() or not self._write_state(swivel="right"):
            return
        time.sleep(pulse_time)
        self._write_state(swivel="left")
        time.sleep(pulse_time)
        self._apply_base()

    def _do_reapply(self):
        with self._lock:
            self._pause_reapply = False
        self._apply_base()

    def _bump_activity(self):
        with self._activity_cond:
            self._activity_seq += 1
            self._activity_cond.notify_all()
