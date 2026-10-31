"""Listener de notificacoes do Windows: observa a central de notificacoes e
reage a notificacoes novas do app Claude (qualquer aba, chat ou Code).

Usa polling em vez do evento notification_changed porque o evento WinRT exige
identidade de pacote (app empacotado), o que um processo Python solto nao tem.

Privacidade: o texto das notificacoes (titulos de conversa, comandos) NAO vai
para o log; so a classificacao. Para depurar as regras: IBUDDY_DEBUG=1.
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

# AUMID do app desktop do Claude (pacote da Microsoft Store). Pode ser
# sobrescrito se o seu for diferente: IBUDDY_APP_AUMID=...
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
                # o resto do daemon segue funcionando (cor e coracao)
                log.warning("sem permissao para ler notificacoes do Windows "
                            "(Configuracoes > Privacidade > Notificacoes): "
                            "asas e giro desativados")
                return

        last_error = None
        while True:
            try:
                await self._poll(listener)
                last_error = None
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                if msg != last_error:  # nao enche o log se o erro se repetir a cada 2s
                    log.warning("falha ao ler notificacoes: %s", msg)
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
                log.exception("erro tratando uma notificacao")
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
        log.info("notificacao -> %s", kind)
        log.debug("texto da notificacao: %r", text)
        if kind == "waiting":
            self._worker.submit("waiting_start")
        elif kind == "done":
            self._worker.submit("flap")
