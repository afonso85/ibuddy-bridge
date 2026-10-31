import unittest

from ibuddy.driver import (
    IBuddy, IBuddyNotFoundError, HIDError, build_command, SETUP, MESSAGE_PREFIX,
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
    """Bytes validados fisicamente no aparelho (ver docs/PROTOCOL.md)."""

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
        # observado ao vivo: 0x0F = coracao + cabeca branca (bits 7,6,5,4 zerados)
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
        b.close()  # nao pode levantar
        self.assertTrue(dev.closed)
        self.assertIsNone(b._dev)

    def test_close_sends_neutral(self):
        b = IBuddy()
        dev = FakeHid()
        b._dev = dev
        b.close()
        self.assertEqual(dev.sent[-1], [0] + MESSAGE_PREFIX + [0xFF])


if __name__ == "__main__":
    unittest.main()
