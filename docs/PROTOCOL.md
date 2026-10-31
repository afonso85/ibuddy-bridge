# i-buddy USB protocol

**English** · [Português](PROTOCOL.pt-BR.md)

Reverse-engineering notes **confirmed on real hardware** (Tenx Technology, USB
`VID_1130` / `PID_0001`, product string `Tenx USBOUTDEVICE DEMO`). The reference
implementation in this repository is [`ibuddy/driver.py`](../ibuddy/driver.py); the
pure function `build_command()` and the tests in
[`tests/test_driver.py`](../tests/test_driver.py) pin down the bytes below.

## The device

- HID class: Windows loads the stock HID driver by itself — **no driver install, and
  no need to swap in WinUSB/libusb (Zadig)**.
- It exposes **two HID interfaces** (`MI_00` and `MI_01`). **Only `MI_01` (index 1)
  responds.**
- 9-byte output report: report ID `0` + 8 data bytes.

## Every command is two reports, back to back

Sent with `HidD_SetOutputReport` (in Python, `pywinusb`:
`dev.send_output_report([0] + data)`), one right after the other:

| Order | Data (8 bytes) | Role |
|---|---|---|
| 1 | `22 09 00 02 01 00 00 00` | SETUP, constant |
| 2 | `55 53 42 43 00 40 02 <cmd>` | MESSAGE: `"USBC"` signature + command byte |

Without the signature (or without the SETUP first), the firmware **silently ignores
everything** — no error at all. That is why "sending `0xFF` everywhere" did nothing.

## The command byte

An **active-low** bitfield: `0xFF` is the neutral state (everything off, no motion);
clearing a bit turns the feature on.

| Bit | Feature | Notes |
|---|---|---|
| 7 | Heart | fixed red LED (on/off) |
| 6 | Head — blue | |
| 5 | Head — green | |
| 4 | Head — red | |
| 3 | Wings — "up" pulse | |
| 2 | Wings — "down" pulse | |
| 1 | Swivel — right | |
| 0 | Swivel — left | |

Values checked physically: `0x7F` heart · `0xEF` red head · `0xF7` wings up ·
`0xFB` wings down · `0xFD` swivel right · `0x0F` heart + white head.

## Physical behavior

- **Head**: each channel is simply on or off (no PWM), so there are 7 colors: red,
  green, blue, yellow (R+G), cyan (G+B), purple (R+B) and white. On the unit
  tested, "yellow" comes out greenish because the green LED is stronger.
- **Wings**: holding a fixed state **moves nothing**. To flap you have to alternate
  "up"/"down" every ~0.2 s (it behaves like a solenoid).
- **Swivel**: each pulse turns a small, incremental angle.
- Combinations work: a single byte can carry heart, color, wings and swivel at once.

## Gotchas

- **Dead HID handle while the device is still there.** In the middle of a session a
  write can fail with `HIDError: Error device disconnected before write` while
  Windows still enumerates the device (typical of USB selective suspend). The fix
  is to drop the handle and reopen it; there is no need to replug.
- **Wing mechanism on old units.** It can stop responding after a lot of use (the
  LEDs keep working). Replugging the cable usually restores it.
- **Several processes.** Two open handles work at the same time, but their commands
  get mixed — which is why the daemon is the device's sole owner
  (`ibuddy/worker.py`) and `cli.py`/`demo.py` pause it while they run.
- Only `PID_0001` was tested. The `py3buddy` reference project mentions other PIDs
  (`0002`, `0004`, `0005`) for variants of the product.

## Origin

The bytes were identified from two open projects that use libusb control transfers
(`bmRequestType 0x21`, `bRequest 0x09`, `wValue 2`, `wIndex 1`) and were then
**confirmed and adapted** to the standard Windows HID path:

- [armijnhemel/py3buddy](https://github.com/armijnhemel/py3buddy) (MIT)
- [ewall/pybuddy](https://github.com/ewall/pybuddy)
