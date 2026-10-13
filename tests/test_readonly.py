# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 EVOLINUX contributors
"""Native ioctl packing and mocked transport tests, without EVO hardware."""

import errno
import os
import struct
import sys
import unittest
from unittest.mock import patch

from evolinux.protocol import CUR, RANGE, ControlRead
from evolinux.readonly import (DEVICE_NODE, EVO16_IOCTL_READ, IOCTL_SIZE,
                               IOCTL_STRUCT, NativeReadTransport,
                               build_ioctl_buffer, read_control)


class IoctlPackingTests(unittest.TestCase):
    def test_known_native_layout(self):
        control = ControlRead(60, 34, 6, RANGE, 4096, 7, 10000)
        buffer = build_ioctl_buffer(0x10203040, 127, control)
        endian = "<" if sys.byteorder == "little" else ">"
        expected_header = struct.pack(endian + "IIBBBBHHII", 0x10203040, 127,
                                      60, 34, 6, 2, 4096, 7, 10000, 0)
        self.assertEqual(IOCTL_SIZE, 4120)
        self.assertEqual(IOCTL_STRUCT.size, IOCTL_SIZE)
        self.assertEqual(EVO16_IOCTL_READ, 0xD018E601)
        self.assertEqual(len(buffer), 4120)
        self.assertEqual(buffer[:24], expected_header)
        self.assertEqual(buffer[24:], bytes(4096))

    def test_address_bounds_and_types(self):
        control = ControlRead(11, 0x0B, 1, CUR, 2)
        for bus, device in ((1, 1), (0xFFFFFFFF, 127)):
            with self.subTest(bus=bus, device=device):
                build_ioctl_buffer(bus, device, control)
        for bus, device in ((0, 1), (-1, 1), (0x100000000, 1), (1, 0),
                            (1, 128), (True, 1), (1, "1")):
            with self.subTest(bus=bus, device=device):
                with self.assertRaises(ValueError):
                    build_ioctl_buffer(bus, device, control)

    def test_requires_validated_control(self):
        with self.assertRaises(TypeError):
            build_ioctl_buffer(1, 1, object())


class NativeTransportTests(unittest.TestCase):
    def setUp(self):
        self.control = ControlRead(11, 0x0B, 1, CUR, 2)

    def _reply(self, actual_length, data):
        def callback(fd, operation, buffer, mutate):
            self.assertEqual(fd, 41)
            self.assertEqual(operation, EVO16_IOCTL_READ)
            self.assertTrue(mutate)
            fields = list(IOCTL_STRUCT.unpack(buffer))
            self.assertEqual(fields[9], 0)
            self.assertEqual(fields[10], bytes(4096))
            fields[9] = actual_length
            fields[10] = data.ljust(4096, b"\x00")
            buffer[:] = IOCTL_STRUCT.pack(*fields)
            return 0
        return callback

    def test_reads_actual_bytes_and_opens_read_only(self):
        with patch("evolinux.readonly.os.open", return_value=41) as opened, \
                patch("evolinux.readonly.os.close") as closed, \
                patch("evolinux.readonly.fcntl.ioctl",
                      side_effect=self._reply(2, b"\x00\xff")):
            self.assertEqual(read_control(1, 2, self.control), b"\x00\xff")
        opened.assert_called_once_with(DEVICE_NODE, os.O_RDONLY | os.O_CLOEXEC)
        closed.assert_called_once_with(41)

    def test_short_reply_returns_no_padding(self):
        with patch("evolinux.readonly.os.open", return_value=41), \
                patch("evolinux.readonly.os.close"), \
                patch("evolinux.readonly.fcntl.ioctl",
                      side_effect=self._reply(1, b"\x12")):
            self.assertEqual(read_control(1, 2, self.control), b"\x12")

    def test_empty_reply_is_not_invented(self):
        with patch("evolinux.readonly.os.open", return_value=41), \
                patch("evolinux.readonly.os.close"), \
                patch("evolinux.readonly.fcntl.ioctl",
                      side_effect=self._reply(0, b"")):
            self.assertEqual(read_control(1, 2, self.control), b"")

    def test_kernel_errno_preserved_and_fd_closed(self):
        for code in (errno.ENODEV, errno.EPIPE, errno.ETIMEDOUT, errno.EPERM):
            with self.subTest(errno=code):
                original = OSError(code, os.strerror(code))
                with patch("evolinux.readonly.os.open", return_value=41), \
                        patch("evolinux.readonly.os.close") as closed, \
                        patch("evolinux.readonly.fcntl.ioctl", side_effect=original):
                    with self.assertRaises(OSError) as raised:
                        read_control(1, 2, self.control)
                self.assertIs(raised.exception, original)
                self.assertEqual(raised.exception.errno, code)
                closed.assert_called_once_with(41)

    def test_open_errno_preserved_and_does_not_close_unopened_fd(self):
        original = OSError(errno.EACCES, "permission denied")
        with patch("evolinux.readonly.os.open", side_effect=original), \
                patch("evolinux.readonly.os.close") as closed, \
                patch("evolinux.readonly.fcntl.ioctl") as ioctl:
            with self.assertRaises(OSError) as raised:
                read_control(1, 2, self.control)
        self.assertIs(raised.exception, original)
        closed.assert_not_called()
        ioctl.assert_not_called()

    def test_return_length_larger_than_request_rejected(self):
        with patch("evolinux.readonly.os.open", return_value=41), \
                patch("evolinux.readonly.os.close") as closed, \
                patch("evolinux.readonly.fcntl.ioctl",
                      side_effect=self._reply(3, b"\x01\x02\x03")):
            with self.assertRaisesRegex(ValueError, "more bytes"):
                read_control(1, 2, self.control)
        closed.assert_called_once_with(41)

    def test_custom_node(self):
        with patch("evolinux.readonly.os.open", return_value=41) as opened, \
                patch("evolinux.readonly.os.close"), \
                patch("evolinux.readonly.fcntl.ioctl",
                      side_effect=self._reply(2, b"\x00\x00")):
            NativeReadTransport("/tmp/test-node").read(1, 2, self.control)
        opened.assert_called_once_with("/tmp/test-node", os.O_RDONLY | os.O_CLOEXEC)


if __name__ == "__main__":
    unittest.main()
