# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 EVOLINUX contributors
"""USB metadata tests backed only by temporary files, never USB transfers."""

from dataclasses import replace
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from evolinux import devices


SERIAL = "PRIVATE-DEVICE-SERIAL"


def interface(number=0, alternate=0, string_index=5, classification=(1, 1, 32)):
    return bytes((9, 4, number, alternate, 0, *classification, string_index))


def uac_header(version=0x0200):
    return struct.pack("<BBBHBHB", 9, 0x24, 1, version, 8, 9, 0)


def configuration(value=1, descriptors=None):
    if descriptors is None:
        descriptors = interface() + uac_header()
    return struct.pack("<BBHBBBBB", 9, 2, 9 + len(descriptors), 1,
                       value, 0, 0xC0, 50) + descriptors


def descriptor_blob(*configs, vendor=0x2708, product=0x000A, revision=0x0101):
    descriptor = struct.pack("<BBHBBBBHHHBBBB", 18, 1, 0x0200, 0xEF, 2, 1,
                             64, vendor, product, revision, 1, 2, 3, len(configs))
    return descriptor + b"".join(configs)


def sysfs_device(root, name="1-2", configs=None, active=1, interface_number=0,
                 alternate=0, serial=SERIAL):
    if configs is None:
        configs = (configuration(),)
    location = root / name
    location.mkdir()
    attributes = {
        "idVendor": "2708", "idProduct": "000a", "bcdDevice": "0101",
        "busnum": "1", "devnum": "2", "bConfigurationValue": str(active),
        "manufacturer": "Audient", "product": "EVO 16 fallback name",
    }
    if serial is not None:
        attributes["serial"] = serial
    for key, value in attributes.items():
        (location / key).write_text(value + "\n", encoding="utf-8")
    (location / "descriptors").write_bytes(descriptor_blob(*configs))
    sysfs_interface(root, name, active, interface_number, alternate)
    return location


def sysfs_interface(root, name, active, number, alternate=0):
    location = root / f"{name}:{active}.{number}"
    location.mkdir()
    for key, value in {
        "bInterfaceNumber": f"{number:02x}",
        "bAlternateSetting": str(alternate),
        "bInterfaceClass": "01", "bInterfaceSubClass": "01",
        "bInterfaceProtocol": "20", "interface": "Audient EVO16",
    }.items():
        (location / key).write_text(value + "\n", encoding="utf-8")
    return location


class DescriptorTests(unittest.TestCase):
    def test_active_configuration_is_selected_by_value_not_position(self):
        inactive = configuration(1)
        active = configuration(7, interface(3, 0, 9) + uac_header())
        blob = descriptor_blob(inactive, active)
        device_descriptor, selected = devices.active_configuration(blob, 7)
        self.assertEqual(device_descriptor, blob[:18])
        self.assertEqual(selected, active)
        self.assertEqual(devices.uac2_interfaces(selected), ((3, 0, 9),))

    def test_malformed_device_configuration_and_length_are_rejected(self):
        valid = descriptor_blob(configuration())
        cases = {
            "missing_device": b"",
            "wrong_device_length": b"\x11" + valid[1:],
            "wrong_device_type": valid[:1] + b"\x02" + valid[2:],
            "missing_config": valid[:18],
            "wrong_config_type": valid[:19] + b"\x03" + valid[20:],
            "small_total": valid[:20] + struct.pack("<H", 8) + valid[22:],
            "truncated_total": valid[:20] + struct.pack("<H", 65535) + valid[22:],
            "trailing_bytes": valid + b"\x00",
        }
        for name, blob in cases.items():
            with self.subTest(case=name), self.assertRaises(devices.DescriptorError):
                devices.active_configuration(blob, 1)

    def test_invalid_descriptor_lengths_are_checked_in_inactive_configs(self):
        for body in (b"\x00\x04", b"\x01\x04", b"\x09\x04", b"\x02"):
            with self.subTest(body=body), self.assertRaises(devices.DescriptorError):
                devices.active_configuration(
                    descriptor_blob(configuration(1, body), configuration(2)), 2)

    def test_duplicate_zero_and_unavailable_configurations_are_rejected(self):
        for blob, selected in (
            (descriptor_blob(configuration(1), configuration(1)), 1),
            (descriptor_blob(configuration(0)), 0),
            (descriptor_blob(configuration(1)), 2),
        ):
            with self.subTest(selected=selected), self.assertRaises(devices.DescriptorError):
                devices.active_configuration(blob, selected)

    def test_collection_size_bound_is_enforced(self):
        blob = descriptor_blob(configuration())
        with patch.object(devices, "MAX_DESCRIPTOR_BLOB", len(blob) - 1):
            with self.assertRaises(devices.DescriptorError):
                devices.active_configuration(blob, 1)

    def test_only_uac2_audio_control_interfaces_with_headers_are_reported(self):
        descriptors = (
            interface(0, classification=(1, 1, 0)) + uac_header() +
            interface(1, classification=(1, 2, 32)) + uac_header() +
            interface(2) +
            interface(3, 1, 6) + uac_header() +
            interface(4, 0, 7) + uac_header()
        )
        self.assertEqual(devices.uac2_interfaces(configuration(descriptors=descriptors)),
                         ((3, 1, 6), (4, 0, 7)))

    def test_interface_parser_rejects_unvalidated_configuration_lengths(self):
        valid = configuration()
        cases = {
            "empty": b"",
            "truncated_header": valid[:8],
            "wrong_header_length": b"\x08" + valid[1:],
            "wrong_header_type": valid[:1] + b"\x03" + valid[2:],
            "truncated_total": valid[:-1],
            "trailing_bytes": valid + b"\x00",
            "zero_length": configuration(descriptors=b"\x00\x04"),
            "one_length": configuration(descriptors=b"\x01\x04"),
            "excessive_length": configuration(descriptors=b"\xff\x04"),
            "truncated_descriptor_header": configuration(descriptors=b"\x02"),
        }
        for name, config in cases.items():
            with self.subTest(case=name), self.assertRaises(devices.DescriptorError):
                devices.uac2_interfaces(config)

    def test_invalid_interface_and_audio_headers_are_rejected(self):
        for descriptors in (
            bytes((8, 4, 0, 0, 0, 1, 1, 32)),
            interface() + bytes((2, 0x24)),
            interface() + bytes((3, 0x24, 1)),
            interface() + uac_header(0x0100),
            interface() + uac_header() + uac_header(),
        ):
            with self.subTest(descriptors=descriptors):
                _, config = devices.active_configuration(
                    descriptor_blob(configuration(descriptors=descriptors)), 1)
                with self.assertRaises(devices.DescriptorError):
                    devices.uac2_interfaces(config)


class SysfsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_read_device_cross_checks_current_identity_and_active_interface(self):
        selected = configuration(2, interface(10, 3, 12) + uac_header())
        location = sysfs_device(self.root, configs=(configuration(1), selected),
                                active=2, interface_number=10, alternate=3)
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        device = devices.read_device(location)
        self.assertEqual((device.vendor_id, device.product_id, device.bcd_device),
                         (0x2708, 0x000A, 0x0101))
        self.assertEqual((device.bus_number, device.device_number), (1, 2))
        self.assertEqual((device.configuration_value, device.interface_number,
                          device.interface_string_index), (2, 10, 12))
        self.assertEqual(device.configuration, selected)
        self.assertEqual(device.display_name, "Audient EVO16")
        self.assertNotIn(SERIAL, repr(device))
        self.assertNotIn("Audient", repr(device))
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_optional_strings_and_display_fallback(self):
        location = sysfs_device(self.root, serial=None)
        (location / "manufacturer").unlink()
        (self.root / "1-2:1.0" / "interface").unlink()
        device = devices.read_device(location)
        self.assertEqual(device.serial, "")
        self.assertEqual(device.manufacturer, "")
        self.assertEqual(device.display_name, "EVO 16 fallback name")

    def test_unrelated_product_is_not_accepted(self):
        location = sysfs_device(self.root)
        (location / "idProduct").write_text("0007\n")
        with self.assertRaises(devices.UnsupportedDevice):
            devices.read_device(location)

    def test_ids_and_revision_must_agree_with_binary_device_descriptor(self):
        location = sysfs_device(self.root)
        for attributes in ({"vendor": 0x1234}, {"product": 0x0007}, {"revision": 0x0102}):
            with self.subTest(attributes=attributes):
                (location / "descriptors").write_bytes(descriptor_blob(configuration(), **attributes))
                with self.assertRaises(devices.DescriptorError):
                    devices.read_device(location)

    def test_inactive_alternate_setting_is_not_used(self):
        location = sysfs_device(self.root)
        (self.root / "1-2:1.0" / "bAlternateSetting").write_text("1\n")
        with self.assertRaises(devices.UnsupportedDevice):
            devices.read_device(location)

    def test_missing_audio_interface_is_not_fabricated(self):
        location = sysfs_device(self.root)
        (self.root / "1-2:1.0" / "bInterfaceNumber").unlink()
        with self.assertRaises(devices.UnsupportedDevice):
            devices.read_device(location)

    def test_multiple_active_audio_control_interfaces_are_ambiguous(self):
        config = configuration(descriptors=interface(0) + uac_header() +
                               interface(1) + uac_header())
        location = sysfs_device(self.root, configs=(config,))
        sysfs_interface(self.root, "1-2", 1, 1)
        with self.assertRaises(devices.UnsupportedDevice):
            devices.read_device(location)

    def test_changed_address_during_observation_rejects_mixed_snapshot(self):
        location = sysfs_device(self.root)
        original = devices._number
        addresses = iter((2, 3))

        def changed(path, base, minimum, maximum):
            if path == location / "devnum":
                return next(addresses)
            return original(path, base, minimum, maximum)

        with patch.object(devices, "_number", changed):
            with self.assertRaisesRegex(devices.DescriptorError, "changed"):
                devices.read_device(location)

    def test_invalid_numeric_attributes_do_not_leak_contents(self):
        location = sysfs_device(self.root)
        for text in (SERIAL, "0", "128"):
            with self.subTest(text=text):
                (location / "devnum").write_text(text + "\n")
                with self.assertRaises(devices.DescriptorError) as caught:
                    devices.read_device(location)
                self.assertNotIn(SERIAL, str(caught.exception))

    def test_invalid_utf8_and_oversized_text_are_bounded(self):
        location = sysfs_device(self.root)
        for value in (b"\xff", b"x" * (devices.MAX_SYSFS_TEXT + 1)):
            with self.subTest(length=len(value)):
                (location / "serial").write_bytes(value)
                with self.assertRaises(devices.DescriptorError):
                    devices.read_device(location)

    def test_optional_missing_file_does_not_mask_permission_failure(self):
        location = sysfs_device(self.root)
        original = Path.open

        def denied(path, *args, **kwargs):
            if path == location / "serial":
                raise PermissionError(13, "Permission denied")
            return original(path, *args, **kwargs)

        with patch.object(Path, "open", denied):
            with self.assertRaises(PermissionError):
                devices.read_device(location)

    def test_enumeration_sorts_matches_skips_interfaces_and_unrelated_devices(self):
        sysfs_device(self.root, "2-1")
        sysfs_device(self.root, "1-2")
        other = self.root / "3-1"
        other.mkdir()
        (other / "idVendor").write_text("1234\n")
        (self.root / "vanished").mkdir()
        self.assertEqual([item.path.name for item in devices.enumerate_devices(self.root)],
                         ["1-2", "2-1"])

    def test_missing_inventory_root_is_not_reported_as_no_device(self):
        with self.assertRaises(FileNotFoundError):
            devices.enumerate_devices(self.root / "missing")

    def test_inventory_permission_failure_is_not_reported_as_no_device(self):
        location = sysfs_device(self.root)
        original = Path.open

        def denied(path, *args, **kwargs):
            if path == location / "idVendor":
                raise PermissionError(13, "Permission denied")
            return original(path, *args, **kwargs)

        with patch.object(Path, "open", denied):
            with self.assertRaises(PermissionError):
                devices.enumerate_devices(self.root)


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.device = devices.DeviceSnapshot(Path("/sys/bus/usb/devices/1-2"),
            0x2708, 0x000A, 0x0101, 1, 2, 1, 0, 5, SERIAL, "Audient",
            "Audient EVO16", configuration())

    def test_connection_identity_rejects_address_configuration_and_serial_reuse(self):
        self.assertTrue(self.device.same_connection(replace(self.device)))
        changes = {
            "path": Path("/sys/bus/usb/devices/1-3"), "vendor_id": 0x1234,
            "product_id": 7, "bcd_device": 0x0102, "bus_number": 2, "device_number": 3,
            "configuration_value": 2, "interface_number": 1,
            "serial": "another-device", "configuration": configuration(2),
        }
        for key, value in changes.items():
            with self.subTest(key=key):
                self.assertFalse(self.device.same_connection(replace(self.device, **{key: value})))

    def test_windows_identity_uses_real_serial_or_explicit_sysfs_fallback(self):
        identity = self.device.instance_identity().decode("utf-16le")
        self.assertEqual(identity, "USB\\VID_2708&PID_000A\\" + SERIAL + "\x00")
        fallback = replace(self.device, serial="").instance_identity().decode("utf-16le")
        self.assertEqual(fallback, "USB\\VID_2708&PID_000A\\LINUX_SYSFS_1-2\x00")

    def test_compatibility_property_layout_preserves_unknown_bytes_as_zero(self):
        value = self.device.properties()
        self.assertEqual(len(value), 0x410)
        self.assertEqual(struct.unpack_from("<III", value), (0x2708, 0x000A, 0x0101))
        for offset, text in ((0x0C, SERIAL), (0x10C, "Audient"), (0x20C, "Audient EVO16")):
            self.assertEqual(value[offset:offset + 256].decode("utf-16le").split("\x00", 1)[0], text)
        self.assertEqual(struct.unpack_from("<II", value, 0x30C), (0x0200, 0))
        self.assertEqual(value[0x314:], bytes(0x410 - 0x314))

    def test_utf16_field_truncates_at_terminator_without_splitting_surrogates(self):
        for text, expected in (
            ("abc\x00hidden", "abc"),
            ("a" * 126 + "\U0001f3b5", "a" * 126),
            ("a" * 125 + "\U0001f3b5", "a" * 125 + "\U0001f3b5"),
            ("a" * 200, "a" * 127),
        ):
            with self.subTest(text_length=len(text)):
                result = devices.utf16_field(text)
                self.assertEqual(len(result), 256)
                self.assertEqual(result.decode("utf-16le").split("\x00", 1)[0], expected)
                self.assertEqual(result[-2:], b"\x00\x00")


if __name__ == "__main__":
    unittest.main()
