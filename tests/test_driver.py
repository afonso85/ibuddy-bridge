import types
import unittest
from unittest import mock

import ibuddy.driver as driver_module
from ibuddy.driver import (
    IBuddy, IBuddyNotFoundError, HIDError, build_command, pick_interface, SETUP, MESSAGE_PREFIX,
)


class FakeHid:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail
        self.closed = False

    def send_output_report(self, buf):
        if self.fail:
            raise HIDError("Error device disconnected before write")
        self.sent.append(list(buf))
        return True

    def close(self):
        self.closed = True


class BuildCommandTest(unittest.TestCase):
    """Bytes validated physically on the device (see docs/PROTOCOL.md)."""

    def test_neutral(self):
        self.assertEqual(build_command(), 0xFF)

    def test_validated_on_hardware(self):
        self.assertEqual(build_command(heart=True), 0x7F)
        self.assertEqual(build_command(red=True), 0xEF)
        self.assertEqual(build_command(wings="up"), 0xF7)
        self.assertEqual(build_command(wings="down"), 0xFB)
        self.assertEqual(build_command(swivel="right"), 0xFD)

    def test_head_colors_use_bits_4_5_6(self):
        self.assertEqual(build_command(green=True), 0xDF)
        self.assertEqual(build_command(blue=True), 0xBF)
        self.assertEqual(build_command(red=True, green=True, blue=True), 0x8F)
        self.assertEqual(build_command(swivel="left"), 0xFE)

    def test_effects_combine(self):
        # observed live: 0x0F = heart + white head (bits 7,6,5,4 cleared)
        self.assertEqual(build_command(heart=True, red=True, green=True, blue=True), 0x0F)


class WireFormatTest(unittest.TestCase):
    def test_every_command_is_setup_then_message(self):
        b = IBuddy()
        b._dev = FakeHid()
        b.set_state(heart=True)
        self.assertEqual(b._dev.sent, [[0] + SETUP, [0] + MESSAGE_PREFIX + [0x7F]])
        self.assertIsNotNone(b.last_write_ok)

    def test_write_failure_becomes_not_found(self):
        b = IBuddy()
        b._dev = FakeHid(fail=True)
        with self.assertRaises(IBuddyNotFoundError):
            b.set_state(red=True)
        self.assertIsNone(b.last_write_ok)

    def test_write_without_connection(self):
        with self.assertRaises(IBuddyNotFoundError):
            IBuddy().set_state(red=True)

    def test_close_survives_dead_handle_and_releases_it(self):
        b = IBuddy()
        dev = FakeHid(fail=True)
        b._dev = dev
        b.close()  # must not raise
        self.assertTrue(dev.closed)
        self.assertIsNone(b._dev)

    def test_close_sends_neutral(self):
        b = IBuddy()
        dev = FakeHid()
        b._dev = dev
        b.close()
        self.assertEqual(dev.sent[-1], [0] + MESSAGE_PREFIX + [0xFF])


MI_00 = types.SimpleNamespace(device_path=r"\\?\hid#vid_1130&pid_0001&mi_00#8&146095d7&0&0000#{guid}")
MI_01 = types.SimpleNamespace(device_path=r"\\?\HID#VID_1130&PID_0001&MI_01#8&1307999&0&0000#{guid}")


class InterfaceSelectionTest(unittest.TestCase):
    """Regression: after a reboot Windows returned the interfaces in the opposite
    order, the driver kept using position 1 (now MI_00, which ignores everything)
    and the figurine stayed dark while every write 'succeeded'."""

    def test_picks_mi_01_whatever_the_order(self):
        self.assertIs(pick_interface([MI_00, MI_01]), MI_01)
        self.assertIs(pick_interface([MI_01, MI_00]), MI_01)

    def test_missing_mi_01_is_an_error_not_a_silent_wrong_choice(self):
        with self.assertRaises(IBuddyNotFoundError):
            pick_interface([MI_00])

    def test_connect_opens_the_right_interface(self):
        for order in ([MI_00, MI_01], [MI_01, MI_00]):
            opened = []
            for d in (MI_00, MI_01):
                d.open = lambda d=d: opened.append(d)
            fake_hid = types.SimpleNamespace(
                HidDeviceFilter=lambda **kw: types.SimpleNamespace(get_devices=lambda: list(order)))
            with mock.patch.object(driver_module, "hid", fake_hid):
                b = IBuddy().connect()
            self.assertIs(b._dev, MI_01)
            self.assertEqual(opened, [MI_01])


if __name__ == "__main__":
    unittest.main()
