# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 EVOLINUX contributors
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from evolinux import diagnostics as collector

DESCRIPTORS = bytes.fromhex('12010002ef02014008270a00010101020301090209000101008032')


def device(root, name, product='000a', revision='0101'):
    location = root / name
    location.mkdir()
    for key, value in {
        'idVendor': '2708', 'idProduct': product, 'bcdDevice': revision,
        'busnum': '1', 'devnum': '2', 'speed': '480', 'bConfigurationValue': '1',
        'serial': 'SECRET-SERIAL-MUST-NOT-APPEAR',
    }.items():
        (location / key).write_text(value + '\n')
    (location / 'descriptors').write_bytes(DESCRIPTORS)
    interface = root / (name + ':1.0')
    interface.mkdir()
    for key, value in {
        'bInterfaceNumber': '0a', 'bAlternateSetting': '10', 'bInterfaceClass': '01',
        'bInterfaceSubClass': '01', 'bInterfaceProtocol': '20', 'bNumEndpoints': '02',
    }.items():
        (interface / key).write_text(value + '\n')
    (interface / 'driver').symlink_to('../../drivers/snd-usb-audio')
    return location


def snapshot(root):
    return {str(p.relative_to(root)): ('link', os.readlink(p)) if p.is_symlink() else ('bytes', p.read_bytes())
            for p in root.rglob('*') if p.is_symlink() or p.is_file()}


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.usb = self.base / 'usb'
        self.usb.mkdir()
        self.alsa = self.base / 'asound'
        self.alsa.mkdir()

    def collect(self):
        return collector.collect(self.usb, self.alsa)

    def test_two_evos_descriptors_driver_versions_and_privacy(self):
        device(self.usb, '1-2')
        device(self.usb, '2-4', revision='0204')
        device(self.usb, '3-1', product='0004')
        card = self.alsa / 'card2'
        card.mkdir()
        (card / 'usbid').write_text('2708:000a\n')
        (card / 'usbmixer').write_text('USB Mixer: usb_id=0x2708000a\nCard: SECRET-HOST-SERIAL\n  Unit: 2\n    Control: name="Capture Volume", index=0\n')
        other_card = self.alsa / 'card1'
        other_card.mkdir()
        (other_card / 'usbid').write_text('2708:0004\n')
        before = snapshot(self.base)
        result = self.collect()
        self.assertEqual(result['status'], 'found')
        self.assertEqual(result['read_errors'], [])
        self.assertEqual([d['sysfs_name'] for d in result['devices']], ['1-2', '2-4'])
        evo, second = result['devices']
        self.assertEqual(evo['bcd_device_revision'], '1.01')
        self.assertEqual(second['bcd_device_revision'], '2.04')
        self.assertEqual(bytes.fromhex(evo['descriptors']['hex']), DESCRIPTORS)
        self.assertEqual(evo['descriptors']['sha256'], hashlib.sha256(DESCRIPTORS).hexdigest())
        self.assertEqual(evo['descriptors']['byte_length'], len(DESCRIPTORS))
        self.assertEqual(evo['interfaces'][0]['driver'], 'snd-usb-audio')
        self.assertEqual(evo['interfaces'][0]['interface_number'], 10)
        self.assertEqual(evo['interfaces'][0]['alternate_setting'], 10)
        self.assertEqual(evo['interfaces'][0]['protocol'], 32)
        self.assertEqual(result['alsa']['cards'], [{'card_number': 2, 'usb_id': '2708:000a', 'controls': [{'name': 'Capture Volume', 'index': 0}]}])
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertEqual(snapshot(self.base), before)

    def test_absent_and_unavailable_are_distinct(self):
        device(self.usb, '1-2', product='0004')
        self.assertEqual(self.collect()['status'], 'absent')
        self.assertEqual(collector.collect(self.base / 'missing', self.alsa)['status'], 'sysfs_unavailable')

    def test_permission_error_retains_found_device_and_marks_partial_report(self):
        location = device(self.usb, '1-2')
        original = Path.read_bytes
        def denied(path):
            if path == location / 'descriptors':
                raise PermissionError(13, 'Permission denied')
            return original(path)
        with patch.object(Path, 'read_bytes', denied):
            result = self.collect()
        self.assertEqual(result['status'], 'found')
        self.assertIsNone(result['devices'][0]['descriptors'])
        self.assertIn({'path': '1-2/descriptors', 'kind': 'permission_denied'}, result['read_errors'])

    def test_discovery_permission_error_is_not_reported_as_absence(self):
        location = device(self.usb, '1-2')
        original = Path.read_text
        def denied(path, *args, **kwargs):
            if path == location / 'idVendor':
                raise PermissionError(13, 'Permission denied')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', denied):
            result = self.collect()
        self.assertEqual(result['status'], 'permission_denied')
        self.assertEqual(result['devices'], [])

    def test_disappearing_attribute_marks_read_error(self):
        location = device(self.usb, '1-2')
        (location / 'descriptors').unlink()
        result = self.collect()
        self.assertEqual(result['status'], 'found')
        self.assertIn({'path': '1-2/descriptors', 'kind': 'missing'}, result['read_errors'])

    def test_output_is_private_and_never_overwritten(self):
        output = self.base / 'report.json'
        report = self.collect()
        with patch.object(collector, 'collect', return_value=report), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(collector.main(['--output', str(output)]), 2)
            content = output.read_bytes()
            self.assertEqual(collector.main(['--output', str(output)]), 1)
        self.assertEqual(output.read_bytes(), content)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(content)['status'], 'absent')

    def test_output_symlink_is_refused(self):
        target = self.base / 'target'
        target.write_text('do not overwrite')
        output = self.base / 'report.json'
        output.symlink_to(target)
        with patch.object(collector, 'collect', return_value=self.collect()), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(collector.main(['--output', str(output)]), 1)
        self.assertEqual(target.read_text(), 'do not overwrite')


if __name__ == '__main__':
    unittest.main(verbosity=2)
