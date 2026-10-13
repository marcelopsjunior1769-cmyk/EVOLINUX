# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 EVOLINUX contributors
"""Protocol/unit tests only; these do not exercise a connected EVO 16."""

import struct
import unittest

from evolinux.protocol import (CUR, RANGE, ControlRead, SubRange,
                               decode_gain_db, decode_range, mixer_read)


class ControlReadTests(unittest.TestCase):
    def test_gain_setup_packet(self):
        control = ControlRead(11, 0x0B, 8, CUR, 2, interface_number=5)
        setup = control.usb_setup
        self.assertEqual(setup.bm_request_type, 0xA1)
        self.assertEqual(setup.value, 0x0B08)
        self.assertEqual(setup.index, 0x0B05)
        self.assertEqual(setup.pack(), b"\xa1\x01\x08\x0b\x05\x0b\x02\x00")

    def test_mixer_addresses_and_boundaries(self):
        for unit, outputs in ((60, 6), (61, 4)):
            for input_channel, output_channel in ((1, 1), (34, outputs)):
                with self.subTest(unit=unit, input=input_channel,
                                  output=output_channel):
                    control = mixer_read(unit, input_channel, output_channel)
                    self.assertEqual(control.usb_setup.value,
                                     input_channel << 8 | output_channel)
                    self.assertEqual(control.usb_setup.index, unit << 8)
                    self.assertEqual(control.length, 2)

    def test_mixer_rejects_wrong_unit_or_channel(self):
        for unit, input_channel, output_channel in (
                (50, 1, 1), (60, 0, 1), (60, 35, 1), (60, 1, 0),
                (60, 1, 7), (61, 1, 5)):
            with self.subTest(unit=unit, input=input_channel, output=output_channel):
                with self.assertRaises(ValueError):
                    mixer_read(unit, input_channel, output_channel)

    def test_whitelisted_clock_controls(self):
        self.assertEqual(ControlRead(40, 1, 0, CUR, 1).usb_setup.value, 0x100)
        for unit in (41, 44, 45):
            with self.subTest(unit=unit):
                ControlRead(unit, 1, 0, CUR, 4)
                ControlRead(unit, 1, 0, RANGE, 2)
                ControlRead(unit, 2, 0, CUR, 1)

    def test_whitelisted_gain_and_phase(self):
        for channel in (1, 24):
            for selector, length in ((0x0B, 2), (0x0D, 1)):
                with self.subTest(channel=channel, selector=selector):
                    ControlRead(11, selector, channel, CUR, length)
                    ControlRead(11, selector, channel, RANGE, 2)

    def test_exploratory_extension_read_bounds(self):
        for selector in (0, 1, 2):
            for channel in (0, 23):
                with self.subTest(selector=selector, channel=channel):
                    ControlRead(58, selector, channel, CUR, 4)
        for selector, channel in ((3, 0), (0, 24)):
            with self.subTest(selector=selector, channel=channel):
                with self.assertRaises(ValueError):
                    ControlRead(58, selector, channel, CUR, 4)

    def test_wrong_units_and_selectors_rejected(self):
        for unit, selector, channel, length in (
                (3, 1, 0, 4), (62, 1, 0, 4), (10, 2, 1, 2),
                (12, 2, 1, 2), (13, 2, 1, 2), (11, 2, 1, 2),
                (11, 0x0B, 0, 2), (11, 0x0B, 25, 2), (40, 2, 0, 1),
                (41, 1, 1, 4), (41, 3, 0, 4)):
            with self.subTest(unit=unit, selector=selector, channel=channel):
                with self.assertRaises(ValueError):
                    ControlRead(unit, selector, channel, CUR, length)

    def test_write_and_unrecognized_request_codes_rejected(self):
        # SET_CUR has bRequest=1 too, but the builder always emits direction IN.
        # These cannot encode a caller-supplied OUT direction or legacy GET_CUR.
        for request in (0, 3, 0x81, 0xFF, -1):
            with self.subTest(request=request):
                with self.assertRaises(ValueError):
                    ControlRead(11, 0x0B, 1, request, 2)

    def test_range_not_allowed_for_cur_only_controls(self):
        for unit, selector, channel in (
                (40, 1, 0), (41, 2, 0), (44, 2, 0), (45, 2, 0), (58, 0, 0)):
            with self.subTest(unit=unit, selector=selector):
                with self.assertRaises(ValueError):
                    ControlRead(unit, selector, channel, RANGE, 4)

    def test_cur_length_must_match_expected_width(self):
        for length in (0, 1, 3, 4096):
            with self.subTest(length=length):
                with self.assertRaises(ValueError):
                    ControlRead(11, 0x0B, 1, CUR, length)

    def test_range_header_probe_and_max_buffer(self):
        for length in (2, 8, 4096):
            with self.subTest(length=length):
                ControlRead(11, 0x0B, 1, RANGE, length)
        for length in (1, 4097):
            with self.subTest(length=length):
                with self.assertRaises(ValueError):
                    ControlRead(11, 0x0B, 1, RANGE, length)

    def test_interface_and_timeout_bounds(self):
        for interface, timeout in ((0, 1), (255, 10000)):
            with self.subTest(interface=interface, timeout=timeout):
                ControlRead(11, 0x0B, 1, CUR, 2, interface, timeout)
        for interface, timeout in ((-1, 1), (256, 1), (0, 0), (0, 10001)):
            with self.subTest(interface=interface, timeout=timeout):
                with self.assertRaises(ValueError):
                    ControlRead(11, 0x0B, 1, CUR, 2, interface, timeout)

    def test_types_are_not_coerced(self):
        valid = dict(unit_id=11, selector=0x0B, channel=1, request=CUR,
                     length=2, interface_number=0, timeout_ms=1000)
        for field in valid:
            for bad in (True, "1", 1.0):
                with self.subTest(field=field, bad=bad):
                    params = dict(valid, **{field: bad})
                    with self.assertRaises(ValueError):
                        ControlRead(**params)

    def test_abi_get_preserves_protocol_fields(self):
        control = ControlRead.from_tusbaudio_get(
            60, RANGE, 34, 6, 4096, 10000, interface_number=7)
        self.assertEqual(control, ControlRead(60, 34, 6, RANGE, 4096, 7, 10000))
        self.assertEqual(control.usb_setup.index, 0x3C07)


class DecoderTests(unittest.TestCase):
    def test_signed_gain_values(self):
        for raw, expected in ((0, 0.0), (-256, -1.0), (128, 0.5),
                              (32767, 127.99609375), (-32768, -128.0)):
            with self.subTest(raw=raw):
                self.assertEqual(decode_gain_db(struct.pack("<h", raw)), expected)

    def test_gain_requires_exact_length(self):
        for data in (b"", b"\x00", b"\x00\x00\x00"):
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    decode_gain_db(data)

    def test_signed_gain_range(self):
        data = struct.pack("<Hhhh", 1, -12 * 256, 60 * 256, 256)
        self.assertEqual(decode_range(data, 2, signed=True),
                         (SubRange(-3072, 15360, 256),))

    def test_range_one_and_four_byte_unsigned(self):
        for width, data, expected in (
                (1, b"\x01\x00\x00\x01\x01", SubRange(0, 1, 1)),
                (4, struct.pack("<HIII", 1, 44100, 192000, 1),
                 SubRange(44100, 192000, 1))):
            with self.subTest(width=width):
                self.assertEqual(decode_range(data, width), (expected,))

    def test_multiple_ranges(self):
        data = struct.pack("<HIIIIII", 2, 44100, 44100, 0, 48000, 48000, 0)
        self.assertEqual(decode_range(data, 4),
                         (SubRange(44100, 44100, 0), SubRange(48000, 48000, 0)))

    def test_zero_ranges_are_not_invented(self):
        self.assertEqual(decode_range(b"\x00\x00", 2), ())

    def test_range_truncated_extra_header_and_count(self):
        complete = struct.pack("<Hhhh", 1, -256, 256, 1)
        for data in (b"", b"\x01", complete[:2], complete[:-1],
                     complete + b"\x00", b"\xff\xff"):
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    decode_range(data, 2, signed=True)

    def test_range_bounded_count_and_buffer(self):
        complete = struct.pack("<HBBB", 1, 0, 1, 1)
        with self.assertRaises(ValueError):
            decode_range(complete, 1, max_count=0)
        with self.assertRaises(ValueError):
            decode_range(b"\x00\x00" + bytes(4095), 1)
        # Maximum complete one-byte response: 1364 subranges, 4094 bytes.
        maximal = struct.pack("<H", 1364) + b"\x00\x01\x01" * 1364
        self.assertEqual(len(decode_range(maximal, 1)), 1364)

    def test_invalid_range_width_and_interval(self):
        for width in (0, 3, 8, True):
            with self.subTest(width=width):
                with self.assertRaises(ValueError):
                    decode_range(b"\x00\x00", width)
        for data in (struct.pack("<Hhhh", 1, 2, 1, 1),
                     struct.pack("<Hhhh", 1, 0, 1, -1)):
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    decode_range(data, 2, signed=True)


if __name__ == "__main__":
    unittest.main()
