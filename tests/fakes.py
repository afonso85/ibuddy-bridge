"""Dublês de teste: nenhum teste Python toca no hardware nem no relogio real
(exceto o teste de regressao do worker, que usa tempos minusculos de proposito)."""
from ibuddy.driver import IBuddyNotFoundError


class FakeTime:
    """Relogio controlavel: sleep() apenas avanca o tempo."""

    def __init__(self, start=1000.0):
        self.now = start

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def advance(self, seconds):
        self.now += seconds


class FakeDevice:
    """Estado compartilhado entre 'reconexoes' (cada connect cria um FakeBuddy novo)."""

    def __init__(self):
        self.writes = []            # cada set_state(**kw) vira um dict
        self.connected = True       # False: connect() levanta IBuddyNotFoundError
        self.break_writes = False   # True: set_state levanta IBuddyNotFoundError
        self.attempts = 0           # tentativas de connect(), com sucesso ou nao
        self.connects = 0

    def factory(self):
        return FakeBuddy(self)

    def swivels(self):
        return sum(1 for w in self.writes if w.get("swivel") == "right")


class FakeBuddy:
    last_write_ok = None

    def __init__(self, dev):
        self.dev = dev

    def connect(self):
        self.dev.attempts += 1
        if not self.dev.connected:
            raise IBuddyNotFoundError("ausente")
        self.dev.connects += 1
        return self

    def set_state(self, **kw):
        if self.dev.break_writes:
            raise IBuddyNotFoundError("falha de escrita")
        self.dev.writes.append(kw)

    def reset(self):
        self.dev.writes.append({"reset": True})

    def close(self):
        pass

    def abandon(self):
        pass


class FakeWorker:
    """Registra o que o servidor HTTP pediu ao worker."""

    def __init__(self):
        self.calls = []

    def submit(self, action, **kw):
        self.calls.append((action, kw))

    def pause(self, seconds):
        self.calls.append(("pause", seconds))

    def resume(self):
        self.calls.append(("resume",))

    def status(self):
        return {"connected": True}

    def wait_activity(self, since, timeout):
        return since
