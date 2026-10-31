"""Cliente minimo do daemon, para cli.py e demo.py.

Eles falam direto com o HID. Com o daemon rodando (o normal, ele sobe com o
Windows), os dois brigariam pelo aparelho e, ao terminar, o script deixaria a
cabeca apagada. daemon_paused() silencia o daemon durante o script e, na saida,
faz ele reaplicar a cor atual.
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
        return False  # daemon desligado: tudo bem, o script tem o aparelho so pra ele


@contextlib.contextmanager
def daemon_paused(seconds=300):
    """Silencia o daemon durante o bloco. A pausa expira sozinha em 'seconds'
    (protege contra um script que morreu sem chamar resume)."""
    paused = _post("/pause", {"seconds": seconds})
    if paused:
        time.sleep(0.7)  # deixa terminar a escrita/meio-giro que estava em andamento
    try:
        yield paused
    finally:
        if paused:
            _post("/resume")
