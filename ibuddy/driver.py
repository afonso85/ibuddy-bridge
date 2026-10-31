"""Driver de baixo nivel para o i-buddy (Tenx Technology, VID_1130 PID_0001).

Protocolo confirmado empiricamente no hardware real (detalhes em
docs/PROTOCOL.md). Cada comando exige duas transferencias HID output report em
sequencia: uma mensagem SETUP fixa seguida da MESSAGE contendo o byte de
comando. O byte de comando e um bitfield ativo em zero (0xFF = neutro, cada bit
em 0 ativa o recurso correspondente).
"""
import time

try:
    import pywinusb.hid as hid
    from pywinusb.hid.helpers import HIDError
except ImportError:  # permite importar (e testar) o resto do projeto fora do Windows
    hid = None

    class HIDError(Exception):
        pass

VID = 0x1130
PID = 0x0001
INTERFACE_INDEX = 1  # MI_01 - a unica interface que responde

SETUP = [0x22, 0x09, 0x00, 0x02, 0x01, 0x00, 0x00, 0x00]
MESSAGE_PREFIX = [0x55, 0x53, 0x42, 0x43, 0x00, 0x40, 0x02]

NEUTRAL = 0xFF

BIT_HEART = 7
BIT_RED = 4
BIT_GREEN = 5
BIT_BLUE = 6
BIT_WINGS_UP = 3
BIT_WINGS_DOWN = 2
BIT_SWIVEL_RIGHT = 1
BIT_SWIVEL_LEFT = 0

FLAP_INTERVAL = 0.2  # segundos entre pulsos up/down para bater as asas
SWIVEL_PULSE = 0.15  # duracao de um pulso de giro


class IBuddyNotFoundError(Exception):
    """Dispositivo ausente, desconectado ou com a alca invalida."""


def _clear_bit(value, bit):
    return value & ~(1 << bit)


def build_command(heart=False, red=False, green=False, blue=False,
                  wings=None, swivel=None):
    """Monta o byte de comando (funcao pura, sem tocar no hardware).

    wings: None, 'up' ou 'down'. swivel: None, 'left' ou 'right'.
    """
    cmd = NEUTRAL
    if heart:
        cmd = _clear_bit(cmd, BIT_HEART)
    if red:
        cmd = _clear_bit(cmd, BIT_RED)
    if green:
        cmd = _clear_bit(cmd, BIT_GREEN)
    if blue:
        cmd = _clear_bit(cmd, BIT_BLUE)
    if wings == "up":
        cmd = _clear_bit(cmd, BIT_WINGS_UP)
    elif wings == "down":
        cmd = _clear_bit(cmd, BIT_WINGS_DOWN)
    if swivel == "right":
        cmd = _clear_bit(cmd, BIT_SWIVEL_RIGHT)
    elif swivel == "left":
        cmd = _clear_bit(cmd, BIT_SWIVEL_LEFT)
    return cmd


class IBuddy:
    def __init__(self):
        self._dev = None
        self.last_write_ok = None  # time.monotonic() da ultima escrita bem-sucedida

    def connect(self):
        if hid is None:
            raise IBuddyNotFoundError(
                "biblioteca pywinusb indisponivel (so funciona no Windows: pip install pywinusb)"
            )
        devices = hid.HidDeviceFilter(vendor_id=VID, product_id=PID).get_devices()
        if not devices or len(devices) <= INTERFACE_INDEX:
            raise IBuddyNotFoundError(
                "i-buddy nao encontrado (VID_1130 PID_0001). Verifique se esta conectado."
            )
        self._dev = devices[INTERFACE_INDEX]
        self._dev.open()
        return self

    def abandon(self):
        """Descarta a alca sem tentar escrever nada (uso apos falha de escrita)."""
        dev, self._dev = self._dev, None
        if dev is not None:
            try:
                dev.close()
            except Exception:
                pass

    def close(self):
        if self._dev is None:
            return
        try:
            self._send_command(NEUTRAL)
        except IBuddyNotFoundError:
            pass  # ja desconectado - nada a resetar, so libera o handle
        self.abandon()

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _send_report(self, data8):
        if self._dev is None:
            raise IBuddyNotFoundError("i-buddy nao esta conectado")
        try:
            self._dev.send_output_report([0] + data8)
        except HIDError as e:
            # handle ficou invalido em pleno uso (ex: porta USB entrou em
            # suspensao seletiva) - o Windows ainda pode enxergar o
            # dispositivo numa nova enumeracao, entao trata como "sumiu"
            # para quem chama reconectar do zero
            raise IBuddyNotFoundError(f"i-buddy desconectado durante escrita: {e}") from e
        self.last_write_ok = time.monotonic()

    def _send_command(self, command_byte):
        self._send_report(SETUP)
        self._send_report(MESSAGE_PREFIX + [command_byte])

    def reset(self):
        """Volta ao estado neutro: tudo apagado, sem movimento."""
        self._send_command(NEUTRAL)

    def set_state(self, heart=False, red=False, green=False, blue=False,
                  wings=None, swivel=None):
        """Aplica varios efeitos num unico comando (heart + cor + asas + giro)."""
        self._send_command(build_command(heart, red, green, blue, wings, swivel))

    def heart(self, on):
        self.set_state(heart=on)

    def head_color(self, red=False, green=False, blue=False):
        self.set_state(red=red, green=green, blue=blue)

    def flap(self, times=3, interval=FLAP_INTERVAL):
        """Bate as asas. Precisa alternar up/down - segurar um estado fixo nao move nada."""
        for _ in range(times):
            self.set_state(wings="up")
            time.sleep(interval)
            self.set_state(wings="down")
            time.sleep(interval)
        self.reset()

    def swivel(self, direction, pulses=1, pulse_time=SWIVEL_PULSE):
        """Gira o corpo. direction: 'left' ou 'right'. Cada pulso move um pouco."""
        for _ in range(pulses):
            self.set_state(swivel="right" if direction == "right" else "left")
            time.sleep(pulse_time)
        self.reset()
