"""Low-level driver for the i-buddy (Tenx Technology, VID_1130 PID_0001).

The protocol was confirmed empirically on real hardware (details in
docs/PROTOCOL.md). Every command takes two HID output reports in a row: a fixed
SETUP message followed by the MESSAGE carrying the command byte. The command
byte is an active-low bitfield (0xFF = neutral, each bit cleared to 0 turns on
the matching feature).
"""
import time

try:
    import pywinusb.hid as hid
    from pywinusb.hid.helpers import HIDError
except ImportError:  # lets the rest of the project be imported (and tested) off Windows
    hid = None

    class HIDError(Exception):
        pass

VID = 0x1130
PID = 0x0001
INTERFACE_INDEX = 1  # MI_01 - the only interface that responds

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

FLAP_INTERVAL = 0.2  # seconds between up/down pulses when flapping the wings
SWIVEL_PULSE = 0.15  # duration of one swivel pulse


class IBuddyNotFoundError(Exception):
    """Device missing, disconnected, or holding an invalid handle."""


def _clear_bit(value, bit):
    return value & ~(1 << bit)


def build_command(heart=False, red=False, green=False, blue=False,
                  wings=None, swivel=None):
    """Build the command byte (a pure function, never touches the hardware).

    wings: None, 'up' or 'down'. swivel: None, 'left' or 'right'.
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
        self.last_write_ok = None  # time.monotonic() of the last successful write

    def connect(self):
        if hid is None:
            raise IBuddyNotFoundError(
                "pywinusb is not available (Windows only: pip install pywinusb)"
            )
        devices = hid.HidDeviceFilter(vendor_id=VID, product_id=PID).get_devices()
        if not devices or len(devices) <= INTERFACE_INDEX:
            raise IBuddyNotFoundError(
                "i-buddy not found (VID_1130 PID_0001). Check that it is plugged in."
            )
        self._dev = devices[INTERFACE_INDEX]
        self._dev.open()
        return self

    def abandon(self):
        """Drop the handle without trying to write anything (use after a failed write)."""
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
            pass  # already disconnected - nothing to reset, just release the handle
        self.abandon()

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _send_report(self, data8):
        if self._dev is None:
            raise IBuddyNotFoundError("i-buddy is not connected")
        try:
            self._dev.send_output_report([0] + data8)
        except HIDError as e:
            # the handle went invalid mid-use (e.g. the USB port entered
            # selective suspend) - Windows may still see the device in a fresh
            # enumeration, so treat it as "gone" and let the caller reconnect
            # from scratch
            raise IBuddyNotFoundError(f"i-buddy disconnected during write: {e}") from e
        self.last_write_ok = time.monotonic()

    def _send_command(self, command_byte):
        self._send_report(SETUP)
        self._send_report(MESSAGE_PREFIX + [command_byte])

    def reset(self):
        """Back to neutral: everything off, no motion."""
        self._send_command(NEUTRAL)

    def set_state(self, heart=False, red=False, green=False, blue=False,
                  wings=None, swivel=None):
        """Apply several effects in a single command (heart + color + wings + swivel)."""
        self._send_command(build_command(heart, red, green, blue, wings, swivel))

    def heart(self, on):
        self.set_state(heart=on)

    def head_color(self, red=False, green=False, blue=False):
        self.set_state(red=red, green=green, blue=blue)

    def flap(self, times=3, interval=FLAP_INTERVAL):
        """Flap the wings. It must alternate up/down - holding a fixed state moves nothing."""
        for _ in range(times):
            self.set_state(wings="up")
            time.sleep(interval)
            self.set_state(wings="down")
            time.sleep(interval)
        self.reset()

    def swivel(self, direction, pulses=1, pulse_time=SWIVEL_PULSE):
        """Turn the body. direction: 'left' or 'right'. Each pulse turns a little."""
        for _ in range(pulses):
            self.set_state(swivel="right" if direction == "right" else "left")
            time.sleep(pulse_time)
        self.reset()
