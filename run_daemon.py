"""Daemon do iBuddy Bridge: fica rodando em segundo plano, escutando
http://127.0.0.1:8765 e traduzindo pedidos em animacoes no hardware.

Uso: python run_daemon.py
Para parar: Ctrl+C, ou  curl -X POST http://127.0.0.1:8765/shutdown
(o dispositivo eh resetado ao estado neutro antes de sair)

Variaveis de ambiente: IBUDDY_DEBUG=1 (log detalhado, inclui texto das
notificacoes), IBUDDY_APP_AUMID (AUMID do app do Claude).
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
        print("Ja existe um daemon rodando. Encerrando esta instancia.")
        return 0

    worker = BuddyWorker()
    worker.start()

    try:
        from ibuddy.notifications import NotificationWatcher
        NotificationWatcher(worker).start()
        notif = "ok"
    except Exception as e:
        notif = f"indisponivel ({e})"
        log.warning("listener de notificacoes indisponivel: %s", e)

    try:
        server = make_server(worker)
    except OSError:
        # outra instancia ocupou a porta entre a checagem e agora
        print("Ja existe um daemon rodando. Encerrando esta instancia.")
        worker.shutdown()
        return 0

    log.info("daemon iniciado - notificacoes: %s", notif)
    print(f"iBuddy Bridge rodando em http://{HOST}:{PORT}")
    print(f"Listener de notificacoes do Windows: {notif}")
    print(f"Log: {LOG_FILE}")
    print("Ctrl+C para parar. (ou: curl -X POST http://127.0.0.1:8765/shutdown)")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("Encerrando, resetando o i-buddy...")
        server.server_close()
        worker.shutdown()
        worker.join(timeout=3)
        log.info("daemon encerrado")


if __name__ == "__main__":
    sys.exit(main() or 0)
