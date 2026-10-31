"""Worker de fundo: dona unica da conexao HID, processa comandos de uma fila.

Existe para evitar que dois disparos simultaneos (ex: extensao do Chrome +
notificacao de fim de resposta) escrevam no HID ao mesmo tempo e colidam.
Mantem um estado "persistente" (cor da cabeca / coracao) que fica ligado ate
ser trocado, e camadas isso com animacoes transitorias (bater de asas, pulso,
giro) sem perder o estado persistente por baixo.

Alem da fila, o loop tem um agendador proprio (giro de espera, reconexao,
fim de pausa). O relogio dele NAO depende do trafego da fila: a extensao do
Chrome manda um comando a cada <=25s, e um temporizador baseado em "fila
ociosa" nunca disparava enquanto ela estivesse ativa.
"""
import logging
import queue
import threading
import time

from .driver import IBuddy, IBuddyNotFoundError

log = logging.getLogger("ibuddy.worker")

LEVEL_COLORS = {
    "low": dict(green=True),
    "medium": dict(blue=True),
    "high": dict(red=True, blue=True),
    "critical": dict(red=True),
    "off": dict(),
}

WAITING_PULSE_INTERVAL = 60.0   # segundos entre giros enquanto "esperando voce"
WAITING_MAX_SECONDS = 600.0     # desiste depois disso: nao ha como saber que voce ja respondeu
WAITING_PULSE_TIME = 0.5        # duracao de cada meio giro
PAUSE_MAX_SECONDS = 600.0       # teto da pausa (demo/cli); expira sozinha
FLAP_DEDUP_SECONDS = 5.0        # duas notificacoes quase juntas = uma resposta
RECONNECT_INTERVAL = 30.0       # tentativa ativa de reconexao quando desconectado


class BuddyWorker(threading.Thread):
    def __init__(self, buddy_factory=IBuddy):
        super().__init__(daemon=True)
        self._buddy_factory = buddy_factory
        self._queue = queue.Queue()
        self._buddy = None
        self._connected = False
        self._ever_connected = False
        self._lock = threading.Lock()
        self._created_at = time.monotonic()

        # estado persistente (o que fica "ligado" entre animacoes)
        self._heart = False
        self._color = dict(LEVEL_COLORS["off"])

        # modo espera ("Claude esta esperando voce")
        self._waiting = False
        self._waiting_since = 0.0
        self._next_pulse = 0.0

        # pausa (demo/cli mexem direto no HID; o daemon fica quieto)
        self._paused_until = 0.0
        self._pause_reapply = False

        self._next_reconnect = 0.0
        self._last_flap = -FLAP_DEDUP_SECONDS

        # contador de "aconteceu uma resposta" para o long-poll da extensao
        # (permite reagir na hora a picos de consumo, sem depender do
        # intervalo minimo de 1min do chrome.alarms)
        self._activity_seq = 0
        self._activity_cond = threading.Condition()

    # --- API publica, chamada pelo servidor HTTP (thread-safe) ---

    def submit(self, action, **kwargs):
        self._queue.put((action, kwargs))

    def shutdown(self):
        self._queue.put(("_shutdown", {}))

    def pause(self, seconds):
        """Silencia o daemon (nao escreve no HID) por ate 'seconds'. Sincrono:
        vale assim que retorna; animacoes em andamento abortam no proximo passo."""
        seconds = max(0.0, min(float(seconds), PAUSE_MAX_SECONDS))
        with self._lock:
            self._paused_until = time.monotonic() + seconds
            self._pause_reapply = True

    def resume(self):
        with self._lock:
            self._paused_until = 0.0
        self.submit("reapply")  # tambem acorda o loop

    def wait_activity(self, since, timeout):
        """Bloqueia ate o contador de atividade passar de 'since' ou o
        timeout estourar. Usado pelo long-poll da extensao do Chrome."""
        with self._activity_cond:
            self._activity_cond.wait_for(
                lambda: self._activity_seq > since, timeout=timeout)
            return self._activity_seq

    def status(self):
        now = time.monotonic()
        last_ok = getattr(self._buddy, "last_write_ok", None)
        with self._lock:
            return {
                "connected": self._connected,
                "heart": self._heart,
                "color": dict(self._color),
                "waiting": self._waiting,
                "waiting_for_s": round(now - self._waiting_since) if self._waiting else None,
                "paused": now < self._paused_until,
                "last_write_ok_s_ago": round(now - last_ok, 1) if last_ok else None,
                "uptime_s": round(now - self._created_at),
            }

    # --- loop principal ---

    def run(self):
        self._guarded("conexao inicial", self._ensure_connected)
        while True:
            try:
                action, kwargs = self._queue.get(timeout=self._seconds_to_next_deadline())
            except queue.Empty:
                action, kwargs = None, {}

            if action == "_shutdown":
                self._safe_reset()
                break
            if action is not None:
                self._guarded(action, self._dispatch, action, kwargs)
            self._guarded("agendamento", self._run_scheduled)

    def _guarded(self, label, fn, *args):
        """Nada pode escapar daqui: se a thread do worker morrer, o daemon
        inteiro trava (o servidor HTTP continua de pe, mas ninguem mais
        processa comando algum)."""
        try:
            fn(*args)
        except IBuddyNotFoundError:
            self._connected = False
            log.warning("i-buddy desconectado durante '%s'", label)
        except Exception:
            log.exception("erro em '%s'", label)

    def _dispatch(self, action, kwargs):
        handler = getattr(self, "_do_" + action, None)
        if handler is None:
            log.warning("acao desconhecida: %r", action)
            return
        handler(**kwargs)

    # --- agendador ---

    def _seconds_to_next_deadline(self):
        now = time.monotonic()
        with self._lock:
            deadlines = []
            if self._waiting:
                deadlines.append(self._next_pulse)
            if self._pause_reapply:
                deadlines.append(self._paused_until)
            if not self._connected:
                deadlines.append(self._next_reconnect)
        return max(0.0, min(deadlines) - now) if deadlines else None

    def _run_scheduled(self):
        now = time.monotonic()
        reapply = pulse = expired = reconnect = False
        with self._lock:
            if self._pause_reapply and now >= self._paused_until:
                self._pause_reapply = False
                reapply = True
            if self._waiting and now >= self._next_pulse:
                if now - self._waiting_since > WAITING_MAX_SECONDS:
                    self._waiting = False
                    expired = True
                else:
                    self._next_pulse = now + WAITING_PULSE_INTERVAL
                    pulse = True
            if not self._connected and now >= self._next_reconnect:
                self._next_reconnect = now + RECONNECT_INTERVAL
                reconnect = True

        if expired:
            log.info("modo espera expirou apos %.0fs sem novo aviso", WAITING_MAX_SECONDS)
        if reconnect:
            self._ensure_connected()
        if reapply:
            self._apply_base()
        if pulse and not self._paused():
            self._waiting_pulse()

    def _paused(self):
        return time.monotonic() < self._paused_until

    # --- conexao e escrita no hardware ---

    def _ensure_connected(self):
        if self._connected:
            return
        if self._buddy is not None:
            self._buddy.abandon()  # descarta a alca antiga (pode estar invalida)
            self._buddy = None
        try:
            buddy = self._buddy_factory()
            buddy.connect()
        except IBuddyNotFoundError:
            return
        self._buddy = buddy
        self._connected = True
        reconnected = self._ever_connected
        self._ever_connected = True
        log.info("i-buddy %s", "reconectado" if reconnected else "conectado")
        if reconnected and not self._paused():
            self._write_state()  # reaplica cor/coracao que o aparelho perdeu

    def _write_state(self, **extra):
        """Escreve o estado persistente (+ efeitos transitorios em 'extra').
        Devolve False se nao ha dispositivo."""
        self._ensure_connected()
        if not self._connected:
            return False
        with self._lock:
            heart, color = self._heart, dict(self._color)
        effects = {**color, **extra}
        heart = effects.pop("heart", heart)
        self._buddy.set_state(heart=heart, **effects)
        return True

    def _apply_base(self):
        """Reenvia o estado persistente atual (heart + cor) ao hardware."""
        if not self._paused():
            self._write_state()

    def _safe_reset(self):
        if self._connected and self._buddy is not None:
            try:
                self._buddy.reset()
                self._buddy.close()
            except Exception:
                pass

    def _waiting_pulse(self):
        with self._lock:
            elapsed = time.monotonic() - self._waiting_since
        log.info("giro de espera (esperando ha %.0fs)", elapsed)
        if not self._write_state(swivel="right"):
            return
        time.sleep(WAITING_PULSE_TIME)
        self._write_state(swivel="left")
        time.sleep(WAITING_PULSE_TIME)
        self._write_state()

    # --- acoes (despachadas por _dispatch a partir da fila) ---

    def _do_set_color(self, level="off"):
        with self._lock:
            self._color = dict(LEVEL_COLORS.get(level, LEVEL_COLORS["off"]))
        self._apply_base()

    def _do_heart_pulse(self, times=3):
        for _ in range(times):
            if self._paused() or not self._write_state(heart=True):
                return
            time.sleep(0.3)
            if not self._write_state(heart=False):
                return
            time.sleep(0.3)
        with self._lock:
            self._heart = False
        self._apply_base()

    def _do_flap(self, times=5, interval=0.2):
        # anti-duplicacao: duas notificacoes quase juntas = uma resposta
        now = time.monotonic()
        if now - self._last_flap < FLAP_DEDUP_SECONDS:
            return
        self._last_flap = now
        self._bump_activity()
        with self._lock:
            self._waiting = False  # resposta terminou, nao esta mais esperando
        for _ in range(times):
            if self._paused() or not self._write_state(wings="up"):
                return
            time.sleep(interval)
            if not self._write_state(wings="down"):
                return
            time.sleep(interval)
        self._apply_base()

    def _do_waiting_start(self):
        now = time.monotonic()
        with self._lock:
            if not self._waiting:
                self._waiting = True
                self._next_pulse = now + WAITING_PULSE_INTERVAL
            self._waiting_since = now  # novo aviso estende o prazo

    def _do_waiting_stop(self):
        with self._lock:
            self._waiting = False
        self._apply_base()

    def _do_reset(self):
        with self._lock:
            self._heart = False
            self._color = dict(LEVEL_COLORS["off"])
            self._waiting = False
        self._ensure_connected()
        if self._connected:
            self._buddy.reset()

    def _do_swivel_once(self, pulse_time=WAITING_PULSE_TIME):
        """Giro avulso sob demanda (demo/teste); nao mexe no estado persistente."""
        if self._paused() or not self._write_state(swivel="right"):
            return
        time.sleep(pulse_time)
        self._write_state(swivel="left")
        time.sleep(pulse_time)
        self._apply_base()

    def _do_reapply(self):
        with self._lock:
            self._pause_reapply = False
        self._apply_base()

    def _bump_activity(self):
        with self._activity_cond:
            self._activity_seq += 1
            self._activity_cond.notify_all()
