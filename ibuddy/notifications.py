"""Windows notification listener: watches the notification center and reacts to
new notifications from the Claude app (any tab, chat or Code).

It polls instead of using the WinRT notification_changed event, because that
event requires package identity (a packaged app), which a plain Python process
does not have.

Privacy: the notification text (conversation titles, commands) does NOT go to the
log; only the classification does. To debug the rules: IBUDDY_DEBUG=1.
"""
import asyncio
import logging
import os
import threading

from winrt.windows.ui.notifications.management import (
    UserNotificationListener,
    UserNotificationListenerAccessStatus,
)
from winrt.windows.ui.notifications import NotificationKinds, KnownNotificationBindings

from .rules import classify

log = logging.getLogger("ibuddy.notifications")

# AUMID of the Claude desktop app (Microsoft Store package). It can be
# overridden if yours differs: IBUDDY_APP_AUMID=...
CLAUDE_AUMID = os.environ.get("IBUDDY_APP_AUMID", "Claude_pzs8sxrjxfjjc!Claude")
POLL_INTERVAL = 2.0


class NotificationWatcher(threading.Thread):
    def __init__(self, worker):
        super().__init__(daemon=True)
        self._worker = worker
        self._seen_ids = set()
        self._first_poll = True

    def run(self):
        asyncio.run(self._loop())

    async def _loop(self):
        listener = UserNotificationListener.current
        status = listener.get_access_status()
        if status != UserNotificationListenerAccessStatus.ALLOWED:
            status = await listener.request_access_async()
            if status != UserNotificationListenerAccessStatus.ALLOWED:
                # the rest of the daemon keeps working (color and heart)
                log.warning("no permission to read Windows notifications "
                            "(Settings > Privacy & security > Notifications): "
                            "wings and swivel disabled")
                return

        last_error = None
        while True:
            try:
                await self._poll(listener)
                last_error = None
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                if msg != last_error:  # don't flood the log if the error repeats every 2s
                    log.warning("failed to read notifications: %s", msg)
                    last_error = msg
            await asyncio.sleep(POLL_INTERVAL)

    async def _poll(self, listener):
        notifs = await listener.get_notifications_async(NotificationKinds.TOAST)
        current_ids = set()
        for n in notifs:
            try:
                if n.app_info.app_user_model_id != CLAUDE_AUMID:
                    continue
                current_ids.add(n.id)
                if self._first_poll or n.id in self._seen_ids:
                    continue
                self._on_claude_notification(n)
            except Exception:
                log.exception("error handling a notification")
        self._seen_ids = current_ids
        self._first_poll = False

    def _texts_of(self, n):
        try:
            binding = n.notification.visual.get_binding(
                KnownNotificationBindings.toast_generic)
            return " ".join(t.text for t in binding.get_text_elements()).lower()
        except Exception:
            return ""

    def _on_claude_notification(self, n):
        text = self._texts_of(n)
        kind = classify(text)
        log.info("notification -> %s", kind)
        log.debug("notification text: %r", text)
        if kind == "waiting":
            self._worker.submit("waiting_start")
        elif kind == "done":
            self._worker.submit("flap")
