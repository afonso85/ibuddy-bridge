import time as real_time
import unittest
from unittest import mock

import ibuddy.worker as worker_module
from ibuddy.worker import (
    BuddyWorker, PAUSE_MAX_SECONDS, RECONNECT_INTERVAL,
)
from fakes import FakeDevice, FakeTime


class SchedulerTest(unittest.TestCase):
    """Chama os metodos do worker direto, com relogio falso (sem thread)."""

    def setUp(self):
        self.clock = FakeTime()
        patcher = mock.patch.object(worker_module, "time", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.dev = FakeDevice()
        self.w = BuddyWorker(buddy_factory=self.dev.factory)
        self.w._ensure_connected()
        self.dev.writes.clear()

    def run_for(self, seconds, step=1.0):
        end = self.clock.now + seconds
        while self.clock.now < end:
            self.clock.advance(step)
            self.w._run_scheduled()

    # --- modo espera ---

    def test_waiting_swivels_every_interval_then_gives_up(self):
        self.w._do_waiting_start()
        self.run_for(59)
        self.assertEqual(self.dev.swivels(), 0)        # a primeira "chamadinha" so vem aos 60s
        self.run_for(700)
        self.assertEqual(self.dev.swivels(), 10)       # 60s, 120s, ... 600s
        self.assertFalse(self.w.status()["waiting"])   # e desiste: nao gira para sempre

    def test_new_prompt_extends_the_deadline(self):
        self.w._do_waiting_start()
        self.run_for(500)
        self.w._do_waiting_start()                     # novo pedido de permissao
        self.run_for(300)                              # sem o aviso novo, teria expirado
        self.assertTrue(self.w.status()["waiting"])

    def test_flap_ends_waiting_and_is_deduplicated(self):
        self.w._do_waiting_start()
        self.w._do_flap(times=2, interval=0.1)
        self.assertFalse(self.w.status()["waiting"])
        wings = [x["wings"] for x in self.dev.writes if x.get("wings")]
        self.assertEqual(wings, ["up", "down", "up", "down"])
        n = len(self.dev.writes)
        self.w._do_flap(times=2, interval=0.1)         # menos de 5s depois: mesma resposta
        self.assertEqual(len(self.dev.writes), n)

    def test_flap_bumps_activity_counter(self):
        self.assertEqual(self.w.wait_activity(0, 0), 0)
        self.w._do_flap(times=1, interval=0.1)
        self.assertEqual(self.w.wait_activity(0, 0), 1)

    # --- pausa (cli.py / demo.py) ---

    def test_pause_silences_hardware_then_reapplies_when_it_expires(self):
        self.w._do_set_color("low")
        self.assertEqual(self.dev.writes[-1], dict(heart=False, green=True))
        self.w.pause(30)
        self.dev.writes.clear()
        self.w._do_set_color("high")                   # o estado muda, o hardware nao
        self.w._do_flap(times=2, interval=0.1)
        self.w._do_heart_pulse()
        self.w._do_swivel_once()
        self.assertEqual(self.dev.writes, [])
        self.clock.advance(31)
        self.w._run_scheduled()                        # pausa venceu sozinha
        self.assertEqual(self.dev.writes, [dict(heart=False, red=True, blue=True)])

    def test_resume_reapplies_immediately(self):
        self.w.pause(100)
        self.w._do_set_color("critical")
        self.assertEqual(self.dev.writes, [])
        self.w.resume()
        action, kwargs = self.w._queue.get_nowait()
        self.assertEqual(action, "reapply")
        self.w._dispatch(action, kwargs)
        self.assertEqual(self.dev.writes, [dict(heart=False, red=True)])
        self.assertFalse(self.w.status()["paused"])

    def test_pause_is_capped(self):
        self.w.pause(10 ** 9)
        self.assertLessEqual(self.w._paused_until - self.clock.now, PAUSE_MAX_SECONDS)

    # --- conexao ---

    def test_reconnect_reapplies_the_current_color(self):
        self.w._do_set_color("medium")
        self.dev.break_writes = True
        self.w._guarded("cor", self.w._do_set_color, "high")   # a escrita falha
        self.assertFalse(self.w.status()["connected"])
        self.dev.break_writes = False
        self.dev.writes.clear()
        self.run_for(2)
        self.assertTrue(self.w.status()["connected"])
        self.assertEqual(self.dev.writes[-1], dict(heart=False, red=True, blue=True))

    def test_reconnect_attempts_are_throttled(self):
        self.dev.connected = False
        self.w._connected = False
        before = self.dev.attempts
        self.run_for(95)
        attempts = self.dev.attempts - before
        self.assertTrue(3 <= attempts <= 5, attempts)   # ~1 a cada RECONNECT_INTERVAL
        self.assertEqual(RECONNECT_INTERVAL, 30.0)

    # --- observabilidade e robustez ---

    def test_status_reports_health_fields(self):
        st = self.w.status()
        for key in ("connected", "heart", "color", "waiting", "waiting_for_s",
                    "paused", "last_write_ok_s_ago", "uptime_s"):
            self.assertIn(key, st)
        self.assertIsNone(st["waiting_for_s"])
        self.w._do_waiting_start()
        self.clock.advance(42)
        self.assertEqual(self.w.status()["waiting_for_s"], 42)
        self.w.pause(10)
        self.assertTrue(self.w.status()["paused"])

    def test_bad_commands_are_logged_not_raised(self):
        with self.assertLogs("ibuddy.worker", level="WARNING"):
            self.w._dispatch("nao_existe", {})
            self.w._guarded("x", self.w._dispatch, "set_color", {"bogus": 1})


class ThreadedWorkerTest(unittest.TestCase):
    """Roda a thread de verdade, com tempos minusculos."""

    def test_swivel_fires_while_the_queue_is_busy_and_stops_after_expiry(self):
        """Regressao: a extensao do Chrome manda um comando a cada <=25s. O
        temporizador antigo ('fila ociosa por 60s') nunca disparava enquanto
        ela estivesse ativa, e girava para sempre quando ela estava parada."""
        dev = FakeDevice()
        with mock.patch.multiple(worker_module, WAITING_PULSE_INTERVAL=0.15,
                                 WAITING_MAX_SECONDS=0.7, WAITING_PULSE_TIME=0.005):
            w = BuddyWorker(buddy_factory=dev.factory)
            w.start()
            try:
                w.submit("waiting_start")
                end = real_time.monotonic() + 1.4
                while real_time.monotonic() < end:
                    w.submit("set_color", level="low")      # "extensao" sempre ativa
                    real_time.sleep(0.03)
                real_time.sleep(0.3)
                during = dev.swivels()
                self.assertGreaterEqual(during, 2)           # girou apesar da fila ocupada
                self.assertLessEqual(during, 6)              # e desistiu (nao e eterno)
                self.assertFalse(w.status()["waiting"])
                real_time.sleep(0.5)
                self.assertEqual(dev.swivels(), during)
            finally:
                w.shutdown()
                w.join(2)

    def test_worker_thread_survives_bad_commands(self):
        dev = FakeDevice()
        w = BuddyWorker(buddy_factory=dev.factory)
        w.start()
        try:
            with self.assertLogs("ibuddy.worker", level="WARNING"):
                w.submit("set_color", bogus=1)               # TypeError
                w.submit("nao_existe")
                w.submit("set_color", level="low")
                for _ in range(300):
                    if any(x.get("green") for x in dev.writes):
                        break
                    real_time.sleep(0.01)
            self.assertTrue(any(x.get("green") for x in dev.writes))
            self.assertTrue(w.is_alive())
        finally:
            w.shutdown()
            w.join(2)


if __name__ == "__main__":
    unittest.main()
