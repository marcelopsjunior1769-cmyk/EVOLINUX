# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 EVOLINUX contributors
"""Live EVO 16 USB metadata; no saved inventories or simulated devices.

The serial is used only in memory by the compatibility API. It is deliberately
excluded from reprs and the broker's health response and request log.
"""

from dataclasses import dataclass, field
from pathlib import Path
import struct


SYSFS_USB_ROOT = Path("/sys/bus/usb/devices")
VENDOR_ID = 0x2708
PRODUCT_ID = 0x000A
MAX_CONFIG_LENGTH = 65535
MAX_DESCRIPTOR_BLOB = 18 + 255 * MAX_CONFIG_LENGTH
MAX_SYSFS_TEXT = 4096


class DescriptorError(ValueError):
    """Malformed or inconsistent real USB metadata, without its contents."""


class UnsupportedDevice(ValueError):
    """No unambiguous active UAC2 AudioControl interface is available."""


def _text(path: Path, *, optional: bool = False) -> str:
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_SYSFS_TEXT + 1)
    except FileNotFoundError:
        if optional:
            return ""
        raise
    if len(data) > MAX_SYSFS_TEXT:
        raise DescriptorError("sysfs attribute is too long")
    try:
        return data.decode("utf-8").removesuffix("\n")
    except UnicodeError:
        raise DescriptorError("sysfs attribute is not UTF-8") from None


def _number(path: Path, base: int, minimum: int, maximum: int) -> int:
    try:
        value = int(_text(path).strip(), base)
    except ValueError:
        raise DescriptorError("sysfs numeric attribute is invalid") from None
    if not minimum <= value <= maximum:
        raise DescriptorError("sysfs numeric attribute is out of range")
    return value


def active_configuration(blob: bytes, configuration_value: int) -> tuple[bytes, bytes]:
    """Return the real device descriptor and selected full config descriptor.

    Sysfs's descriptors file contains the device descriptor followed by every
    configuration, including inactive ones. Parse wTotalLength boundaries and
    bConfigurationValue; never assume the first configuration is active.
    """
    if len(blob) < 18 or blob[0:2] != b"\x12\x01":
        raise DescriptorError("device descriptor is missing or malformed")
    if len(blob) > MAX_DESCRIPTOR_BLOB:
        raise DescriptorError("USB descriptor collection exceeds its bound")
    device_descriptor = blob[:18]
    offset = 18
    active = None
    seen = set()
    for _ in range(device_descriptor[17]):
        if len(blob) - offset < 9 or blob[offset:offset + 2] != b"\x09\x02":
            raise DescriptorError("configuration descriptor is malformed")
        total = struct.unpack_from("<H", blob, offset + 2)[0]
        if not 9 <= total <= MAX_CONFIG_LENGTH or total > len(blob) - offset:
            raise DescriptorError("configuration length is invalid")
        config = blob[offset:offset + total]
        value = config[5]
        if value == 0 or value in seen:
            raise DescriptorError("configuration value is invalid or duplicated")
        seen.add(value)
        # Walk every descriptor, even for inactive configurations, to reject
        # malformed length fields without returning a fabricated config.
        inner = 0
        while inner < total:
            if total - inner < 2:
                raise DescriptorError("truncated descriptor header")
            length = config[inner]
            if length < 2 or length > total - inner:
                raise DescriptorError("descriptor length is invalid")
            inner += length
        if value == configuration_value:
            active = config
        offset += total
    if offset != len(blob):
        raise DescriptorError("trailing bytes after USB configurations")
    if active is None:
        raise DescriptorError("active configuration is not in USB descriptors")
    return device_descriptor, active


def uac2_interfaces(config: bytes) -> tuple[tuple[int, int, int], ...]:
    """Find (interface number, alternate setting, iInterface) with UAC2 headers."""
    if len(config) < 9 or config[:2] != b"\x09\x02":
        raise DescriptorError("configuration descriptor is malformed")
    if len(config) > MAX_CONFIG_LENGTH or struct.unpack_from("<H", config, 2)[0] != len(config):
        raise DescriptorError("configuration length is invalid")
    result = []
    current = None
    offset = 0
    while offset < len(config):
        if len(config) - offset < 2:
            raise DescriptorError("truncated descriptor header")
        length = config[offset]
        if length < 2 or length > len(config) - offset:
            raise DescriptorError("descriptor length is invalid")
        descriptor = config[offset:offset + length]
        if descriptor[1] == 4:
            if length != 9:
                raise DescriptorError("standard interface descriptor is malformed")
            current = (tuple(descriptor[2:4]) + (descriptor[8],)
                       if descriptor[5:8] == b"\x01\x01\x20" else None)
        elif descriptor[1] == 0x24 and current is not None:
            if length < 3:
                raise DescriptorError("class-specific descriptor is truncated")
            if descriptor[2] == 1:
                if length < 9 or descriptor[3:5] != b"\x00\x02":
                    raise DescriptorError("UAC2 AudioControl header is malformed")
                if current in result:
                    raise DescriptorError("duplicate AudioControl header")
                result.append(current)
        offset += length
    return tuple(result)


@dataclass(frozen=True, slots=True)
class DeviceSnapshot:
    path: Path
    vendor_id: int
    product_id: int
    bcd_device: int
    bus_number: int
    device_number: int
    configuration_value: int
    interface_number: int
    interface_string_index: int
    serial: str = field(repr=False)
    manufacturer: str = field(repr=False)
    display_name: str = field(repr=False)
    configuration: bytes = field(repr=False)

    def same_connection(self, current: "DeviceSnapshot") -> bool:
        """Reject index reuse after reconnect, config switch, or identity change."""
        return (self.path, self.vendor_id, self.product_id, self.bcd_device, self.bus_number,
                self.device_number, self.configuration_value,
                self.interface_number, self.serial, self.configuration) == (
                    current.path, current.vendor_id, current.product_id, current.bcd_device,
                    current.bus_number, current.device_number,
                    current.configuration_value, current.interface_number,
                    current.serial, current.configuration)

    def properties(self) -> bytes:
        """The confirmed 0x410-byte TUSBAUDIO ABI, sourced from this real device."""
        result = bytearray(0x410)
        struct.pack_into("<III", result, 0, self.vendor_id, self.product_id,
                         self.bcd_device)
        for offset, text in ((0x0C, self.serial), (0x10C, self.manufacturer),
                             (0x20C, self.display_name)):
            result[offset:offset + 256] = utf16_field(text)
        # Only the observed UAC2 capability is mapped. Private Windows-driver
        # flags cannot be inferred from Linux metadata; reserved bytes stay zero.
        struct.pack_into("<II", result, 0x30C, 0x0200, self.interface_number)
        return bytes(result)

    def instance_identity(self) -> bytes:
        """Windows-shaped compatibility identity, not a Windows registry path."""
        suffix = self.serial or "LINUX_SYSFS_" + self.path.name
        identity = f"USB\\VID_{self.vendor_id:04X}&PID_{self.product_id:04X}\\{suffix}"
        return identity.encode("utf-16le") + b"\x00\x00"


def utf16_field(text: str) -> bytes:
    """128 WCHAR units, including terminator, without splitting surrogate pairs."""
    encoded = text.split("\x00", 1)[0].encode("utf-16le")[:254]
    if encoded and 0xD800 <= int.from_bytes(encoded[-2:], "little") <= 0xDBFF:
        encoded = encoded[:-2]
    return (encoded + b"\x00\x00").ljust(256, b"\x00")


def read_device(path: Path) -> DeviceSnapshot:
    """Read and cross-check current metadata and active interface from sysfs."""
    vendor = _number(path / "idVendor", 16, 0, 65535)
    product = _number(path / "idProduct", 16, 0, 65535)
    if (vendor, product) != (VENDOR_ID, PRODUCT_ID):
        raise UnsupportedDevice("USB device does not match the EVO 16")
    revision = _number(path / "bcdDevice", 16, 0, 65535)
    bus = _number(path / "busnum", 10, 1, 0xFFFFFFFF)
    address = _number(path / "devnum", 10, 1, 127)
    configuration_value = _number(path / "bConfigurationValue", 10, 1, 255)
    with (path / "descriptors").open("rb") as stream:
        blob = stream.read(MAX_DESCRIPTOR_BLOB + 1)
    device_descriptor, configuration = active_configuration(blob, configuration_value)
    if struct.unpack_from("<HHH", device_descriptor, 8) != (vendor, product, revision):
        raise DescriptorError("USB IDs or revision disagree with sysfs attributes")
    matches = []
    for number, alternate, string_index in uac2_interfaces(configuration):
        interface = path.parent / f"{path.name}:{configuration_value}.{number}"
        try:
            actual_number = _number(interface / "bInterfaceNumber", 16, 0, 255)
            actual_alt = _number(interface / "bAlternateSetting", 10, 0, 255)
            classification = tuple(_number(interface / attr, 16, 0, 255) for attr in (
                "bInterfaceClass", "bInterfaceSubClass", "bInterfaceProtocol"))
        except FileNotFoundError:
            continue
        if (actual_number, actual_alt, classification) == (number, alternate, (1, 1, 32)):
            matches.append((number, string_index,
                            _text(interface / "interface", optional=True)))
    if len(matches) != 1:
        raise UnsupportedDevice("active UAC2 AudioControl interface is ambiguous or absent")
    number, string_index, interface_name = matches[0]
    serial = _text(path / "serial", optional=True)
    manufacturer = _text(path / "manufacturer", optional=True)
    display = interface_name or _text(path / "product", optional=True)
    # Do not return a mixed snapshot when enumeration races with reconnection.
    if (bus, address, configuration_value) != (
            _number(path / "busnum", 10, 1, 0xFFFFFFFF),
            _number(path / "devnum", 10, 1, 127),
            _number(path / "bConfigurationValue", 10, 1, 255)):
        raise DescriptorError("USB metadata changed during observation")
    return DeviceSnapshot(path, vendor, product, revision, bus, address,
                          configuration_value, number, string_index, serial,
                          manufacturer, display, configuration)


def enumerate_devices(root: Path = SYSFS_USB_ROOT) -> tuple[DeviceSnapshot, ...]:
    """Inventory actual matching devices; an empty tuple means none were found."""
    result = []
    for path in sorted(root.iterdir(), key=lambda entry: entry.name):
        if ":" in path.name:
            continue
        try:
            vendor = _text(path / "idVendor", optional=True).strip().lower()
            if vendor != "2708":
                continue
            product = _text(path / "idProduct").strip().lower()
        except FileNotFoundError:
            continue  # Unplugged before the target was identified.
        if product == "000a":
            result.append(read_device(path))
    return tuple(result)
