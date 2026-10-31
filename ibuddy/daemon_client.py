"""Minimal client for the daemon, used by cli.py and demo.py.

Those scripts talk to the HID directly. With the daemon running (the normal
case: it starts with Windows) the two would fight over the device and, when the
script ended, it would leave the head dark. daemon_paused() silences the daemon
while the script runs and, on exit, makes it re-apply the current color.
"""
import contextlib
import json
import time
import urllib.error
import urllib.request

from .server import HOST, PORT

BASE = f"http://{HOST}:{PORT}"


def _post(path, payload=None, timeout=0.5):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=timeout).read()
        return True
    except (urllib.error.URLError, OSError):
        return False  # daemon is off: fine, the script has the device to itself


@contextlib.contextmanager
def daemon_paused(seconds=300):
    """Silence the daemon during the block. The pause expires on its own after
    'seconds' (protects against a script that died without calling resume)."""
    paused = _post("/pause", {"seconds": seconds})
    if paused:
        time.sleep(0.7)  # let the write / half swivel that was in flight finish
    try:
        yield paused
    finally:
        if paused:
            _post("/resume")
