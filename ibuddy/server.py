"""API HTTP local (so 127.0.0.1) para a extensao do Chrome e scripts pedirem
animacoes ao i-buddy sem tocar no HID diretamente.

Seguranca: qualquer site aberto no navegador consegue disparar requisicoes para
127.0.0.1 (o CORS so impede de ler a resposta, nao de executar a acao). Por
isso o servidor recusa pedidos com 'Origin' que nao seja de uma extensao do
Chrome (navegadores sempre enviam Origin em POST entre origens e o JavaScript
da pagina nao consegue forja-lo) e valida o cabecalho 'Host' (anti DNS
rebinding). Programas locais (curl, python) nao enviam Origin e passam.
"""
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from .worker import LEVEL_COLORS, PAUSE_MAX_SECONDS

log = logging.getLogger("ibuddy.server")

HOST = "127.0.0.1"
PORT = 8765

MAX_WAIT_TIMEOUT = 30.0  # segundos - teto de seguranca para o long-poll
MAX_BODY_BYTES = 64 * 1024
EXTENSION_ORIGIN_PREFIX = "chrome-extension://"

ROUTES = {
    "/token-level",
    "/session-renewed",
    "/response-end",
    "/waiting-start",
    "/waiting-stop",
    "/swivel-once",
    "/pause",
    "/resume",
    "/reset",
    "/shutdown",
}


class _BadRequest(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _num(body, key, default, lo, hi, cast=float):
    """Le um numero do corpo com limites; valor invalido cai no padrao."""
    try:
        value = cast(body.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def make_handler(worker):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # silencioso - isto roda o tempo todo em segundo plano

        # --- respostas ---

        def _extension_origin(self):
            origin = self.headers.get("Origin")
            if origin and origin.startswith(EXTENSION_ORIGIN_PREFIX):
                return origin
            return None

        def _reply(self, code=200, payload=None):
            body = json.dumps(payload or {}).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            origin = self._extension_origin()
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(body)

        # --- protecao ---

        def _guard(self):
            """False (ja respondeu 403) se o pedido nao deve ser atendido."""
            allowed = {f"127.0.0.1:{self.server.server_address[1]}",
                       f"localhost:{self.server.server_address[1]}"}
            host = self.headers.get("Host")
            if host is not None and host.lower() not in allowed:
                self._reply(403, {"error": "host not allowed"})
                return False
            origin = self.headers.get("Origin")
            if origin is not None and not origin.startswith(EXTENSION_ORIGIN_PREFIX):
                self._reply(403, {"error": "origin not allowed"})
                return False
            return True

        def _read_json(self):
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                raise _BadRequest(400, "invalid Content-Length")
            if length > MAX_BODY_BYTES:
                raise _BadRequest(413, "body too large")
            if length <= 0:
                return {}
            try:
                data = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, ValueError):
                return {}
            return data if isinstance(data, dict) else {}

        # --- metodos ---

        def do_OPTIONS(self):
            if not self._guard():
                return
            origin = self._extension_origin()
            self.send_response(204)
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Max-Age", "600")
                self.send_header("Vary", "Origin")
            self.end_headers()

        def do_GET(self):
            if not self._guard():
                return
            parsed = urlparse(self.path)
            if parsed.path == "/status":
                self._reply(200, worker.status())
            elif parsed.path == "/wait-activity":
                qs = parse_qs(parsed.query)
                try:
                    since = int(qs.get("since", ["0"])[0])
                    timeout = min(float(qs.get("timeout", ["25"])[0]), MAX_WAIT_TIMEOUT)
                except ValueError:
                    since, timeout = 0, MAX_WAIT_TIMEOUT
                self._reply(200, {"seq": worker.wait_activity(since, timeout)})
            else:
                self._reply(404, {"error": "not found"})

        def do_POST(self):
            if not self._guard():
                return
            if self.path not in ROUTES:
                self._reply(404, {"error": "not found"})
                return
            try:
                body = self._read_json()
            except _BadRequest as e:
                self._reply(e.code, {"error": e.message})
                return
            if self.path != "/token-level":  # esse e barulhento (1/min), o resto vale logar
                log.info("POST %s %s", self.path, body)

            path = self.path
            if path == "/token-level":
                level = body.get("level")
                if level not in LEVEL_COLORS:
                    self._reply(400, {"error": f"level must be one of {sorted(LEVEL_COLORS)}"})
                    return
                worker.submit("set_color", level=level)
            elif path == "/session-renewed":
                worker.submit("heart_pulse", times=_num(body, "times", 3, 1, 10, int))
            elif path == "/response-end":
                worker.submit("flap", times=_num(body, "times", 5, 1, 20, int),
                              interval=_num(body, "interval", 0.2, 0.05, 1.0))
            elif path == "/waiting-start":
                worker.submit("waiting_start")
            elif path == "/waiting-stop":
                worker.submit("waiting_stop")
            elif path == "/swivel-once":
                worker.submit("swivel_once", pulse_time=_num(body, "pulse_time", 0.5, 0.05, 2.0))
            elif path == "/pause":
                worker.pause(_num(body, "seconds", 120, 1, PAUSE_MAX_SECONDS))
            elif path == "/resume":
                worker.resume()
            elif path == "/reset":
                worker.submit("reset")
            elif path == "/shutdown":
                self._reply(200, {"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return

            self._reply(200, {"ok": True})

    return Handler


def make_server(worker, host=HOST, port=PORT):
    return ThreadingHTTPServer((host, port), make_handler(worker))
