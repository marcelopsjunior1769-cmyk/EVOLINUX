# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 EVOLINUX contributors
import errno
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("read_evo16", ROOT / "tools/read_evo16.py")
probe_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe_tool)


def device():
    return {"bus_number": 1, "device_number": 4, "interfaces": [
        {"class": 1, "subclass": 1, "protocol": 32, "interface_number": 0,
         "driver": "snd-usb-audio"}]}


class ProbeTests(unittest.TestCase):
    def test_uses_selected_optical_clock_and_preserves_read_addresses(self):
        calls = []

        def read(bus, address, control, **kwargs):
            calls.append((bus, address, control.usb_setup.pack()))
            if control.unit_id == 40:
                return b"\x02"
            if control.selector == 1:
                return (96000).to_bytes(4, "little")
            return b"\x01"

        with patch.object(probe_tool, "read_control", read):
            report = probe_tool.probe(device(), 0)
        self.assertEqual(report["status"], "read")
        self.assertEqual(report["selected_clock_unit"], 44)
        self.assertEqual(report["readings"][1]["value"], 96000)
        self.assertTrue(report["readings"][2]["value"])
        self.assertEqual([item[2] for item in calls], [
            bytes.fromhex("a101000100280100"),
            bytes.fromhex("a1010001002c0400"),
            bytes.fromhex("a1010002002c0100"),
        ])

    def test_invalid_clock_pin_does_not_guess_a_frequency(self):
        with patch.object(probe_tool, "read_control", return_value=b"\x00") as read:
            report = probe_tool.probe(device(), 0)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(read.call_count, 1)
        self.assertNotIn("selected_clock_unit", report)
        self.assertNotIn("value", report["readings"][0])

    def test_kernel_failure_is_retained_and_never_shown_as_zero_gain(self):
        def read(bus, address, control, **kwargs):
            if control.unit_id == 40:
                return b"\x01"
            if control.unit_id == 41:
                return (48000).to_bytes(4, "little") if control.selector == 1 else b"\x01"
            raise OSError(errno.EBUSY, "Device or resource busy")

        with patch.object(probe_tool, "read_control", read):
            report = probe_tool.probe(device(), 0, include_gain=True)
        self.assertEqual(report["status"], "partial")
        gain = report["readings"][3]
        self.assertEqual(gain["error"]["errno"], errno.EBUSY)
        self.assertNotIn("value", gain)
        self.assertNotIn("hex", gain)

    def test_short_cur_response_cannot_pass(self):
        with patch.object(probe_tool, "read_control", return_value=b""):
            report = probe_tool.probe(device(), 0)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["readings"][0]["actual_length"], 0)
        self.assertEqual(report["readings"][0]["error"]["kind"], "invalid_response")

    def test_multiple_interfaces_or_devices_require_unambiguous_selection(self):
        evo = device()
        with self.assertRaises(ValueError):
            probe_tool.select_device({"devices": [evo, device()]})
        evo["interfaces"].append(dict(evo["interfaces"][0], interface_number=3))
        with self.assertRaises(ValueError):
            probe_tool.select_device({"devices": [evo]})


if __name__ == "__main__":
    unittest.main()
