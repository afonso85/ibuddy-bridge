"""Test doubles: no Python test touches the hardware or the real clock (except the
worker regression test, which uses tiny times on purpose)."""
import logging

from ibuddy.driver import IBuddyNotFoundError

# keeps expected warnings out of the test output (assertLogs still sees them)
logging.getLogger("ibuddy").addHandler(logging.NullHandler())


class FakeTime:
    """A controllable clock: sleep() just advances the time."""

    def __init__(self, start=1000.0):
        self.now = start

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def advance(self, seconds):
        self.now += seconds


class FakeDevice:
    """State shared across "reconnections" (each connect creates a new FakeBuddy)."""

    def __init__(self):
        self.writes = []            # each set_state(**kw) becomes a dict
        self.connected = True       # False: connect() raises IBuddyNotFoundError
        self.break_writes = False   # True: set_state raises IBuddyNotFoundError
        self.attempts = 0           # connect() attempts, successful or not
        self.connects = 0

    def factory(self):
        return FakeBuddy(self)

    def swivels(self):
        return sum(1 for w in self.writes if w.get("swivel") == "right")


class FakeBuddy:
    last_write_ok = None

    def __init__(self, dev):
        self.dev = dev

    def connect(self):
        self.dev.attempts += 1
        if not self.dev.connected:
            raise IBuddyNotFoundError("absent")
        self.dev.connects += 1
        return self

    def set_state(self, **kw):
        if self.dev.break_writes:
            raise IBuddyNotFoundError("write failed")
        self.dev.writes.append(kw)

    def reset(self):
        self.dev.writes.append({"reset": True})

    def close(self):
        pass

    def abandon(self):
        pass


class FakeWorker:
    """Records what the HTTP server asked the worker to do."""

    def __init__(self):
        self.calls = []

    def submit(self, action, **kw):
        self.calls.append((action, kw))

    def pause(self, seconds):
        self.calls.append(("pause", seconds))

    def resume(self):
        self.calls.append(("resume",))

    def status(self):
        return {"connected": True}

    def wait_activity(self, since, timeout):
        return since
