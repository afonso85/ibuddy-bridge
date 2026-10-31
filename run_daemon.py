"""iBuddy Bridge daemon: keeps running in the background, listening on
http://127.0.0.1:8765 and turning requests into animations on the hardware.

Usage: python run_daemon.py
To stop: Ctrl+C, or  curl -X POST http://127.0.0.1:8765/shutdown
(the device is reset to the neutral state before exiting)

Environment variables: IBUDDY_DEBUG=1 (verbose log, includes the notification
text), IBUDDY_APP_AUMID (the Claude app's AUMID), IBUDDY_STALE_SECONDS (how long
without a usage reading before the head starts blinking; default 300).
"""
import logging
import os
import socket
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ibuddy.worker import BuddyWorker
from ibuddy.server import make_server, HOST, PORT

LOG_FILE = Path(__file__).resolve().parent / ".state" / "daemon.log"


def setup_logging():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("IBUDDY_DEBUG") else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[handler],
    )


def already_running():
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((HOST, PORT))
        return False
    except OSError:
        return True
    finally:
        probe.close()


def main():
    setup_logging()
    log = logging.getLogger("ibuddy.daemon")

    if already_running():
        print("A daemon is already running. Exiting this instance.")
        return 0

    worker = BuddyWorker()
    worker.start()

    try:
        from ibuddy.notifications import NotificationWatcher
        NotificationWatcher(worker).start()
        notif = "ok"
    except Exception as e:
        notif = f"unavailable ({e})"
        log.warning("notification listener unavailable: %s", e)

    try:
        server = make_server(worker)
    except OSError:
        # another instance took the port between the check and now
        print("A daemon is already running. Exiting this instance.")
        worker.shutdown()
        return 0

    log.info("daemon started - notifications: %s", notif)
    print(f"iBuddy Bridge running at http://{HOST}:{PORT}")
    print(f"Windows notification listener: {notif}")
    print(f"Log: {LOG_FILE}")
    print("Ctrl+C to stop. (or: curl -X POST http://127.0.0.1:8765/shutdown)")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("Shutting down, resetting the i-buddy...")
        server.server_close()
        worker.shutdown()
        worker.join(timeout=3)
        log.info("daemon stopped")


if __name__ == "__main__":
    sys.exit(main() or 0)
