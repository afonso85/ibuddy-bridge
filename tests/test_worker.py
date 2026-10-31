import time as real_time
import unittest
from unittest import mock

import ibuddy.worker as worker_module
from ibuddy.worker import (
    BuddyWorker, PAUSE_MAX_SECONDS, RECONNECT_INTERVAL, STALE_BLINK_ON,
)
from fakes import FakeDevice, FakeTime

STALE = 300.0   # the value patched into the worker for these tests
HEAD = ("red", "green", "blue")


def head_on(write):
    return any(write.get(c) for c in HEAD)


class SchedulerTest(unittest.TestCase):
    """Calls the worker's methods directly, with a fake clock (no thread)."""

    def setUp(self):
        self.clock = FakeTime()
        for patcher in (mock.patch.object(worker_module, "time", self.clock),
                        mock.patch.object(worker_module, "STALE_AFTER_SECONDS", STALE)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.dev = FakeDevice()
        self.w = BuddyWorker(buddy_factory=self.dev.factory)
        self.w._ensure_connected()
        self.dev.writes.clear()

    def run_for(self, seconds, step=1.0):
        end = self.clock.now + seconds
        while self.clock.now < end:
            self.clock.advance(step)
            self.w._run_scheduled()

    # --- waiting mode ---

    def test_waiting_swivels_every_interval_then_gives_up(self):
        self.w._do_waiting_start()
        self.run_for(59)
        self.assertEqual(self.dev.swivels(), 0)        # the first nudge only comes at 60s
        self.run_for(700)
        self.assertEqual(self.dev.swivels(), 10)       # 60s, 120s, ... 600s
        self.assertFalse(self.w.status()["waiting"])   # and it gives up: no endless swivel

    def test_new_prompt_extends_the_deadline(self):
        self.w._do_waiting_start()
        self.run_for(500)
        self.w._do_waiting_start()                     # a new permission prompt
        self.run_for(300)                              # without it, it would have expired
        self.assertTrue(self.w.status()["waiting"])

    def test_flap_ends_waiting_and_is_deduplicated(self):
        self.w._do_waiting_start()
        self.w._do_flap(times=2, interval=0.1)
        self.assertFalse(self.w.status()["waiting"])
        wings = [x["wings"] for x in self.dev.writes if x.get("wings")]
        self.assertEqual(wings, ["up", "down", "up", "down"])
        n = len(self.dev.writes)
        self.w._do_flap(times=2, interval=0.1)         # less than 5s later: same response
        self.assertEqual(len(self.dev.writes), n)

    def test_flap_bumps_activity_counter(self):
        self.assertEqual(self.w.wait_activity(0, 0), 0)
        self.w._do_flap(times=1, interval=0.1)
        self.assertEqual(self.w.wait_activity(0, 0), 1)

    # --- pause (cli.py / demo.py) ---

    def test_pause_silences_hardware_then_reapplies_when_it_expires(self):
        self.w._do_set_color("low")
        self.assertEqual(self.dev.writes[-1], dict(heart=False, green=True))
        self.w.pause(30)
        self.dev.writes.clear()
        self.w._do_set_color("high")                   # the state changes, the hardware does not
        self.w._do_flap(times=2, interval=0.1)
        self.w._do_heart_pulse()
        self.w._do_swivel_once()
        self.assertEqual(self.dev.writes, [])
        self.clock.advance(31)
        self.w._run_scheduled()                        # the pause expired on its own
        self.assertEqual(self.dev.writes, [dict(heart=False, red=True, blue=True)])

    def test_resume_reapplies_immediately(self):
        self.w.pause(100)
        self.w._do_set_color("critical")
        self.assertEqual(self.dev.writes, [])
        self.w.resume()
        action, kwargs = self.w._queue.get_nowait()
        self.assertEqual(action, "reapply")
        self.w._dispatch(action, kwargs)
        self.assertEqual(self.dev.writes, [dict(heart=False, red=True)])
        self.assertFalse(self.w.status()["paused"])

    def test_pause_is_capped(self):
        self.w.pause(10 ** 9)
        self.assertLessEqual(self.w._paused_until - self.clock.now, PAUSE_MAX_SECONDS)

    # --- connection ---

    def test_reconnect_reapplies_the_current_color(self):
        self.w._do_set_color("medium")
        self.dev.break_writes = True
        self.w._guarded("color", self.w._do_set_color, "high")   # the write fails
        self.assertFalse(self.w.status()["connected"])
        self.dev.break_writes = False
        self.dev.writes.clear()
        self.run_for(2)
        self.assertTrue(self.w.status()["connected"])
        self.assertEqual(self.dev.writes[-1], dict(heart=False, red=True, blue=True))

    def test_reconnect_attempts_are_throttled(self):
        self.dev.connected = False
        self.w._connected = False
        before = self.dev.attempts
        self.run_for(95)
        attempts = self.dev.attempts - before
        self.assertTrue(3 <= attempts <= 5, attempts)   # ~1 per RECONNECT_INTERVAL
        self.assertEqual(RECONNECT_INTERVAL, 30.0)

    # --- stale reading: the head keeps its color but blinks ---

    def test_stale_head_keeps_its_color_but_blinks(self):
        self.w._do_set_color("low")
        self.dev.writes.clear()
        self.run_for(STALE - 5)
        self.assertEqual(self.dev.writes, [])            # still fresh: solid, no writes
        self.assertFalse(self.w.status()["stale"])
        self.run_for(10, step=0.25)                      # crosses the threshold
        self.assertTrue(self.w.status()["stale"])
        self.dev.writes.clear()
        self.run_for(10, step=0.25)
        lit = [x for x in self.dev.writes if head_on(x)]
        dark = [x for x in self.dev.writes if not head_on(x)]
        self.assertGreaterEqual(len(lit), 3)
        self.assertGreaterEqual(len(dark), 3)
        self.assertTrue(all(x.get("green") for x in lit))   # always its own last color

    def test_fresh_reading_makes_the_head_solid_again(self):
        self.w._do_set_color("high")
        self.run_for(STALE + 5, step=0.5)
        self.assertTrue(self.w.status()["stale"])
        self.w._do_set_color("high")
        self.assertFalse(self.w.status()["stale"])
        self.assertEqual(self.dev.writes[-1], dict(heart=False, red=True, blue=True))
        self.dev.writes.clear()
        self.run_for(60, step=0.5)
        self.assertEqual(self.dev.writes, [])            # no more toggling

    def test_no_blink_without_a_reading_or_with_the_head_off(self):
        self.run_for(STALE + 60)                         # never got a reading
        self.assertEqual(self.dev.writes, [])
        self.assertFalse(self.w.status()["stale"])
        self.w._do_set_color("off")                      # a reading, but nothing lit to blink
        self.dev.writes.clear()
        self.run_for(STALE + 60)
        self.assertEqual(self.dev.writes, [])
        self.assertFalse(self.w.status()["stale"])

    def test_blink_is_silent_while_paused(self):
        self.w._do_set_color("low")
        self.run_for(STALE + 2, step=0.5)
        self.assertTrue(self.w.status()["stale"])
        self.w.pause(30)
        self.dev.writes.clear()
        self.run_for(10, step=0.25)
        self.assertEqual(self.dev.writes, [])

    def test_animations_respect_the_dark_phase_of_the_blink(self):
        self.w._do_set_color("low")
        self.w._stale = True
        self.w._blink_off = True
        self.dev.writes.clear()
        self.w._do_flap(times=1, interval=0.1)
        self.assertEqual(self.dev.writes[0], dict(heart=False, wings="up"))   # head dark, wings still move

    def test_deadlines_follow_the_freshness_of_the_color(self):
        self.assertIsNone(self.w._seconds_to_next_deadline())
        self.w._do_set_color("low")
        self.assertAlmostEqual(self.w._seconds_to_next_deadline(), STALE, delta=1)
        self.run_for(STALE + 1, step=0.5)
        self.assertLessEqual(self.w._seconds_to_next_deadline(), STALE_BLINK_ON)

    def test_reset_clears_the_stale_state(self):
        self.w._do_set_color("low")
        self.run_for(STALE + 2, step=0.5)
        self.w._do_reset()
        st = self.w.status()
        self.assertFalse(st["stale"])
        self.assertIsNone(st["color_age_s"])

    # --- observability and robustness ---

    def test_status_reports_health_fields(self):
        st = self.w.status()
        for key in ("connected", "heart", "color", "stale", "color_age_s", "waiting",
                    "waiting_for_s", "paused", "last_write_ok_s_ago", "uptime_s"):
            self.assertIn(key, st)
        self.assertIsNone(st["waiting_for_s"])
        self.assertIsNone(st["color_age_s"])
        self.w._do_set_color("low")
        self.w._do_waiting_start()
        self.clock.advance(42)
        st = self.w.status()
        self.assertEqual(st["waiting_for_s"], 42)
        self.assertEqual(st["color_age_s"], 42)
        self.w.pause(10)
        self.assertTrue(self.w.status()["paused"])

    def test_bad_commands_are_logged_not_raised(self):
        with self.assertLogs("ibuddy.worker", level="WARNING"):
            self.w._dispatch("does_not_exist", {})
            self.w._guarded("x", self.w._dispatch, "set_color", {"bogus": 1})


class ThreadedWorkerTest(unittest.TestCase):
    """Runs the real thread, with tiny times."""

    def test_swivel_fires_while_the_queue_is_busy_and_stops_after_expiry(self):
        """Regression: the Chrome extension sends a command every <=25s. The old
        timer ('queue idle for 60s') never fired while it was active, and swivelled
        forever when it was stopped."""
        dev = FakeDevice()
        with mock.patch.multiple(worker_module, WAITING_PULSE_INTERVAL=0.15,
                                 WAITING_MAX_SECONDS=0.7, WAITING_PULSE_TIME=0.005):
            w = BuddyWorker(buddy_factory=dev.factory)
            w.start()
            try:
                w.submit("waiting_start")
                end = real_time.monotonic() + 1.4
                while real_time.monotonic() < end:
                    w.submit("set_color", level="low")      # an "extension" that is always active
                    real_time.sleep(0.03)
                real_time.sleep(0.3)
                during = dev.swivels()
                self.assertGreaterEqual(during, 2)           # it swivelled despite the busy queue
                self.assertLessEqual(during, 6)              # and gave up (not endless)
                self.assertFalse(w.status()["waiting"])
                real_time.sleep(0.5)
                self.assertEqual(dev.swivels(), during)
            finally:
                w.shutdown()
                w.join(2)

    def test_head_blinks_in_a_real_thread_when_readings_stop(self):
        dev = FakeDevice()
        with mock.patch.multiple(worker_module, STALE_AFTER_SECONDS=0.3,
                                 STALE_BLINK_ON=0.05, STALE_BLINK_OFF=0.05):
            w = BuddyWorker(buddy_factory=dev.factory)
            w.start()
            try:
                w.submit("set_color", level="low")
                real_time.sleep(0.9)                         # no more readings: stale after 0.3s
                self.assertTrue(w.status()["stale"])
                dark = sum(1 for x in dev.writes if not head_on(x))
                self.assertGreaterEqual(dark, 3)             # it really toggles
                w.submit("set_color", level="low")           # a fresh reading arrives
                real_time.sleep(0.2)
                self.assertFalse(w.status()["stale"])
            finally:
                w.shutdown()
                w.join(2)

    def test_worker_thread_survives_bad_commands(self):
        dev = FakeDevice()
        w = BuddyWorker(buddy_factory=dev.factory)
        w.start()
        try:
            with self.assertLogs("ibuddy.worker", level="WARNING"):
                w.submit("set_color", bogus=1)               # TypeError
                w.submit("does_not_exist")
                w.submit("set_color", level="low")
                for _ in range(300):
                    if any(x.get("green") for x in dev.writes):
                        break
                    real_time.sleep(0.01)
            self.assertTrue(any(x.get("green") for x in dev.writes))
            self.assertTrue(w.is_alive())
        finally:
            w.shutdown()
            w.join(2)


if __name__ == "__main__":
    unittest.main()
