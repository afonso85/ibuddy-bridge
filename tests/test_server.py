import http.client
import json
import threading
import unittest

from ibuddy.server import make_server
from fakes import FakeWorker

EXT = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
WEB = "https://site-qualquer.example"


class ServerBase(unittest.TestCase):
    def setUp(self):
        self.worker = FakeWorker()
        self.server = make_server(self.worker, port=0)   # porta livre qualquer
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.server.shutdown()
        self.server.server_close()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            payload = json.dumps(body) if body is not None else None
            conn.request(method, path, body=payload, headers=headers or {})
            resp = conn.getresponse()
            raw = resp.read()
            return resp.status, dict(resp.getheaders()), (json.loads(raw) if raw else None)
        finally:
            conn.close()


class OriginAndHostProtectionTest(ServerBase):
    """Qualquer site aberto no navegador consegue mandar requisicoes para
    127.0.0.1; o servidor tem que recusar as que nao vem de uma extensao."""

    def test_plain_local_clients_are_allowed(self):
        status, _, body = self.request("GET", "/status")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"connected": True})

    def test_web_origin_cannot_trigger_actions(self):
        for ctype in ("application/json", "text/plain"):   # text/plain nao tem preflight
            status, headers, _ = self.request(
                "POST", "/response-end", {"times": 1},
                {"Origin": WEB, "Content-Type": ctype})
            self.assertEqual(status, 403)
            self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(self.worker.calls, [])

    def test_web_origin_cannot_shut_the_daemon_down(self):
        status, _, _ = self.request("POST", "/shutdown", {}, {"Origin": WEB})
        self.assertEqual(status, 403)
        self.assertTrue(self.thread.is_alive())

    def test_preflight_from_web_origin_is_refused(self):
        status, headers, _ = self.request("OPTIONS", "/shutdown", None, {
            "Origin": WEB,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Private-Network": "true",
        })
        self.assertEqual(status, 403)
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertNotIn("Access-Control-Allow-Private-Network", headers)

    def test_opaque_origin_is_refused(self):
        status, _, _ = self.request("POST", "/reset", {}, {"Origin": "null"})
        self.assertEqual(status, 403)

    def test_dns_rebinding_host_is_refused(self):
        status, _, _ = self.request("GET", "/status", None, {"Host": "atacante.example:8765"})
        self.assertEqual(status, 403)
        status, _, _ = self.request("POST", "/reset", {}, {"Host": "atacante.example"})
        self.assertEqual(status, 403)
        self.assertEqual(self.worker.calls, [])

    def test_localhost_name_is_accepted(self):
        status, _, _ = self.request("GET", "/status", None, {"Host": f"localhost:{self.port}"})
        self.assertEqual(status, 200)

    def test_extension_origin_works_and_is_echoed(self):
        status, headers, _ = self.request(
            "POST", "/token-level", {"level": "low"}, {"Origin": EXT})
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), EXT)
        self.assertEqual(self.worker.calls, [("set_color", {"level": "low"})])

    def test_extension_preflight_is_accepted(self):
        status, headers, _ = self.request("OPTIONS", "/token-level", None, {"Origin": EXT})
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), EXT)


class RoutesTest(ServerBase):
    def test_unknown_route(self):
        self.assertEqual(self.request("POST", "/nada", {})[0], 404)
        self.assertEqual(self.request("GET", "/nada")[0], 404)

    def test_invalid_level_is_rejected(self):
        status, _, _ = self.request("POST", "/token-level", {"level": "roxo-choque"})
        self.assertEqual(status, 400)
        status, _, _ = self.request("POST", "/token-level", {})
        self.assertEqual(status, 400)
        self.assertEqual(self.worker.calls, [])

    def test_numbers_are_clamped_and_garbage_falls_back_to_default(self):
        self.request("POST", "/response-end", {"times": 10 ** 9, "interval": 0.0001})
        self.request("POST", "/response-end", {"times": "abc", "interval": None})
        self.assertEqual(self.worker.calls, [
            ("flap", {"times": 20, "interval": 0.05}),
            ("flap", {"times": 5, "interval": 0.2}),
        ])

    def test_pause_and_resume(self):
        self.request("POST", "/pause", {"seconds": 45})
        self.request("POST", "/pause", {"seconds": 10 ** 9})
        self.request("POST", "/resume")
        self.assertEqual(self.worker.calls, [("pause", 45.0), ("pause", 600.0), ("resume",)])

    def test_wait_activity_returns_the_counter(self):
        status, _, body = self.request("GET", "/wait-activity?since=3&timeout=1")
        self.assertEqual((status, body), (200, {"seq": 3}))

    def test_oversized_body_is_refused_without_reading_it(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.putrequest("POST", "/reset")
            conn.putheader("Content-Length", str(10 * 1024 * 1024))
            conn.endheaders()                      # o corpo nunca e enviado
            self.assertEqual(conn.getresponse().status, 413)
        finally:
            conn.close()
        self.assertEqual(self.worker.calls, [])

    def test_invalid_json_is_treated_as_empty(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("POST", "/waiting-start", body=b"{nao e json")
            self.assertEqual(conn.getresponse().status, 200)
        finally:
            conn.close()
        self.assertEqual(self.worker.calls, [("waiting_start", {})])


class ShutdownTest(unittest.TestCase):
    def test_shutdown_stops_serve_forever(self):
        server = make_server(FakeWorker(), port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
            conn.request("POST", "/shutdown", body=b"{}")
            self.assertEqual(conn.getresponse().status, 200)
            conn.close()
            thread.join(3)
            self.assertFalse(thread.is_alive())
        finally:
            server.server_close()


if __name__ == "__main__":
    unittest.main()
