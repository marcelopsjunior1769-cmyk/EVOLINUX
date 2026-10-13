# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 EVOLINUX contributors
"""Native ioctl transport to the read-only EVO 16 kernel bridge.

No libusb detach/claim, firmware request, device reset, OUT request, or fake data
is implemented. The actual bridge/kernel errno is propagated to the caller.
"""

import fcntl
import os
import struct

from .protocol import ControlRead, MAX_DATA_LENGTH, _integer


DEVICE_NODE = "/dev/evo16-readonly"
# Fixed-width native-endian UAPI, without pointers. C offsets: 0,4,8,9,10,11,
# 12,14,16,20,24. This layout is identical for the supported 32/64-bit Linux ABI.
IOCTL_STRUCT = struct.Struct("@IIBBBBHHII4096s")
IOCTL_SIZE = 4120
if IOCTL_STRUCT.size != IOCTL_SIZE:
    raise RuntimeError("native platform does not match the EVO 16 bridge UAPI")
# Linux asm-generic _IOWR(0xe6, 1, struct evo16_read): direction=3, size=4120.
EVO16_IOCTL_READ = (3 << 30) | (IOCTL_SIZE << 16) | (0xE6 << 8) | 1


def build_ioctl_buffer(bus_number: int, device_number: int,
                       control: ControlRead) -> bytearray:
    """Build a fully zero-initialized input/output structure for one read."""
    _integer("bus_number", bus_number, 1, 0xFFFFFFFF)
    _integer("device_number", device_number, 1, 127)
    if not isinstance(control, ControlRead):
        raise TypeError("control must be a validated ControlRead")
    return bytearray(IOCTL_STRUCT.pack(
        bus_number, device_number, control.unit_id, control.selector,
        control.channel, control.request, control.length,
        control.interface_number, control.timeout_ms, 0,
        bytes(MAX_DATA_LENGTH)))


class NativeReadTransport:
    """Issue control reads through a node opened O_RDONLY for each operation."""

    def __init__(self, node: str = DEVICE_NODE) -> None:
        self.node = node

    def read(self, bus_number: int, device_number: int,
             control: ControlRead) -> bytes:
        buffer = build_ioctl_buffer(bus_number, device_number, control)
        fd = os.open(self.node, os.O_RDONLY | os.O_CLOEXEC)
        try:
            fcntl.ioctl(fd, EVO16_IOCTL_READ, buffer, True)
        finally:
            os.close(fd)
        fields = IOCTL_STRUCT.unpack(buffer)
        actual_length = fields[9]
        if actual_length > control.length or actual_length > MAX_DATA_LENGTH:
            raise ValueError("kernel returned more bytes than requested")
        return fields[10][:actual_length]


def read_control(bus_number: int, device_number: int, control: ControlRead, *,
                 node: str = DEVICE_NODE) -> bytes:
    """Convenience entry point; return only actual bytes, preserving kernel errno."""
    return NativeReadTransport(node).read(bus_number, device_number, control)
