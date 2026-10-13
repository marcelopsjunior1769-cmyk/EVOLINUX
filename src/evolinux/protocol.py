# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 EVOLINUX contributors
"""Read-only USB Audio Control requests for the EVO 16 investigation.

This is the transport prerequisite for adapting the original Windows application.
It is not a mixer application, a Windows DLL, or proof of hardware compatibility.
The whitelist matches the companion kernel bridge and deliberately excludes USB
OUT requests, firmware interfaces, arbitrary extension units, and device reset.
"""

from dataclasses import dataclass
import struct


CUR = 0x01
RANGE = 0x02
USB_AUDIO_CONTROL_IN = 0xA1
MAX_DATA_LENGTH = 4096
MAX_TIMEOUT_MS = 10000


def _integer(name: str, value: int, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")


@dataclass(frozen=True, slots=True)
class UsbSetup:
    """A USB setup packet; integer fields use host order before packing."""

    bm_request_type: int
    request: int
    value: int
    index: int
    length: int

    def pack(self) -> bytes:
        # USB setup packets, unlike the ioctl structure, are always little-endian.
        return struct.pack("<BBHHH", self.bm_request_type, self.request,
                           self.value, self.index, self.length)


@dataclass(frozen=True, slots=True)
class ControlRead:
    """One whitelisted CUR/RANGE read, never an OUT/SET request.

    The clock and gain/polarity entities come from the supplied descriptors.
    EU58's selectors 0..2, with zero-based channels, are exploratory candidates
    from external protocol references; their behavior on this EVO 16 remains
    unvalidated. Inclusion in this read-only whitelist is not a support claim.
    Mixer points use input channel in the selector byte and output channel in
    the channel byte, both one-based.
    """

    unit_id: int
    selector: int
    channel: int
    request: int
    length: int
    interface_number: int = 0
    timeout_ms: int = 1000

    def __post_init__(self) -> None:
        _integer("unit_id", self.unit_id, 0, 255)
        _integer("selector", self.selector, 0, 255)
        _integer("channel", self.channel, 0, 255)
        _integer("request", self.request, CUR, RANGE)
        _integer("length", self.length, 1, MAX_DATA_LENGTH)
        _integer("interface_number", self.interface_number, 0, 255)
        _integer("timeout_ms", self.timeout_ms, 1, MAX_TIMEOUT_MS)

        minimum_cur = self._minimum_cur_length()
        if self.request == RANGE:
            if (self.unit_id in (40, 58)
                    or (self.unit_id in (41, 44, 45) and self.selector == 2)):
                raise ValueError("RANGE is not allowed for this control")
            # A RANGE probe may first request only wNumSubRanges (two bytes).
            if self.length < 2:
                raise ValueError("RANGE reads require at least two bytes")
        elif self.length != minimum_cur:
            raise ValueError(f"this CUR read requires exactly {minimum_cur} bytes")

    def _minimum_cur_length(self) -> int:
        if self.unit_id == 40 and self.selector == 1 and self.channel == 0:
            return 1
        if self.unit_id in (41, 44, 45) and self.channel == 0:
            if self.selector == 1:
                return 4
            if self.selector == 2:
                return 1
        if self.unit_id == 11 and 1 <= self.channel <= 24:
            if self.selector == 0x0B:
                return 2
            if self.selector == 0x0D:
                return 1
        if (self.unit_id == 58 and 0 <= self.selector <= 2
                and 0 <= self.channel <= 23):
            return 4
        output_channels = {60: 6, 61: 4}.get(self.unit_id)
        if (output_channels is not None and 1 <= self.selector <= 34
                and 1 <= self.channel <= output_channels):
            return 2
        raise ValueError("control is outside the EVO 16 read-only whitelist")

    @property
    def usb_setup(self) -> UsbSetup:
        return UsbSetup(USB_AUDIO_CONTROL_IN, self.request,
                        (self.selector << 8) | self.channel,
                        (self.unit_id << 8) | self.interface_number,
                        self.length)

    @classmethod
    def from_tusbaudio_get(cls, unit_id: int, b_request: int,
                          control_selector: int, channel: int,
                          byte_count: int, timeout_ms: int, *,
                          interface_number: int) -> "ControlRead":
        """Preserve the six protocol scalars in AudioControlRequestGet.

        That Windows ABI has nine arguments. Its device handle, buffer pointer,
        and actual-byte-count pointer belong to the future DLL adapter; they are
        not guessed or represented as userspace/kernel pointers here. The Audio
        Control interface must come from the real device descriptor.
        """
        return cls(unit_id=unit_id, selector=control_selector, channel=channel,
                   request=b_request, length=byte_count,
                   interface_number=interface_number, timeout_ms=timeout_ms)


def mixer_read(unit_id: int, input_channel: int, output_channel: int, *,
               request: int = CUR, length: int = 2,
               interface_number: int = 0, timeout_ms: int = 1000) -> ControlRead:
    """Address one matrix point: Unit 60 is 34x6, Unit 61 is 34x4."""
    if unit_id not in (60, 61):
        raise ValueError("mixer unit must be 60 or 61")
    return ControlRead(unit_id, input_channel, output_channel, request, length,
                       interface_number, timeout_ms)


@dataclass(frozen=True, slots=True)
class SubRange:
    minimum: int
    maximum: int
    resolution: int


def decode_range(data: bytes, width: int, *, signed: bool = False,
                 max_count: int = 1364) -> tuple[SubRange, ...]:
    """Decode a complete UAC2 RANGE response, rejecting missing/extra bytes.

    A two-byte header probe is not a complete response unless the count is zero.
    The maximum default count fits the smallest (one-byte) values in 4096 bytes.
    Decoding does not substitute a range when a control returns none.
    """
    _integer("width", width, 1, 4)
    if width not in (1, 2, 4):
        raise ValueError("width must be 1, 2, or 4 bytes")
    if not isinstance(signed, bool):
        raise ValueError("signed must be a boolean")
    _integer("max_count", max_count, 0, 65535)
    if len(data) < 2:
        raise ValueError("RANGE response is missing its two-byte count")
    if len(data) > MAX_DATA_LENGTH:
        raise ValueError("RANGE response exceeds the bridge buffer")
    count = int.from_bytes(data[:2], "little")
    if count > max_count:
        raise ValueError("RANGE response exceeds the allowed subrange count")
    expected = 2 + count * 3 * width
    if len(data) != expected:
        raise ValueError(f"RANGE response needs exactly {expected} bytes")
    subranges = []
    offset = 2
    for _ in range(count):
        values = []
        for _ in range(3):
            values.append(int.from_bytes(data[offset:offset + width], "little",
                                         signed=signed))
            offset += width
        minimum, maximum, resolution = values
        if minimum > maximum or resolution < 0:
            raise ValueError("RANGE response contains an invalid interval")
        subranges.append(SubRange(minimum, maximum, resolution))
    return tuple(subranges)


def decode_gain_db(data: bytes) -> float:
    """Decode the numeric signed 16-bit UAC gain value in units of 1/256 dB.

    This does not establish which physical input a channel controls, or interpret
    device-specific sentinel values as observed physical gain.
    """
    if len(data) != 2:
        raise ValueError("gain response must contain exactly two bytes")
    return int.from_bytes(data, "little", signed=True) / 256.0
