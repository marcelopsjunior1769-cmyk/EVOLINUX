# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 EVOLINUX contributors
"""First-use checks use fixtures and fake services, never real audio devices."""

import errno
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from evolinux import health


HEADER = "USB Mixer: usb_id=0x2708000a, ctrlif=0, ctlerr=0\nCard: private serial HOSTNAME\n"
RECORD = ('  Unit: 11\n    Control: name="Input Gain private serial", index=0\n'
          '    Info: id=11, control=11, cmask=0xffffff, channels=16, type="S16"\n')


class HealthTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.asound = self.root / "asound"
        self.asound.mkdir()
        self.release = self.root / "os-release"
        self.release.write_text('ID=ubuntu\nVERSION_ID="24.04"\nPRETTY_NAME="private serial"\n')
        self.card = self.asound / "card3"
        self.card.mkdir()
        (self.card / "usbid").write_text("2708:000a\n")
        (self.card / "usbmixer").write_text(HEADER + RECORD)
        self.library = Mock(return_value=object())
        self.runner = Mock(return_value=SimpleNamespace(
            stdout="active\n", stderr="private user HOSTNAME", returncode=0))
        self.backend = Mock(side_effect=AssertionError("default must not open CTL"))

    def report(self, **changes):
        kwargs = dict(asound_root=self.asound, os_release_path=self.release,
                      python_version=(3, 12, 3), library_loader=self.library,
                      service_runner=self.runner, backend_factory=self.backend,
                      environment={"DISPLAY": "private user@HOSTNAME:1"},
                      module_finder=Mock(return_value=object()))
        kwargs.update(changes)
        return health.check_environment(**kwargs)

    def test_default_ready_reads_only_supported_metadata_without_ctl_or_usb(self):
        report = self.report()
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["software_prerequisites"], "ready")
        self.assertFalse(report["physical_audio_validated"])
        self.assertEqual(report["alsa"]["cards"][0]["mappings"], [
            {"unit": 11, "selector": 11, "channel_mask": 0xffffff,
             "channels": 16, "usb_type": "S16"}])
        self.library.assert_called_once_with("libasound.so.2", use_errno=True)
        self.backend.assert_not_called()
        self.assertNotIn("controls", report)
        encoded = json.dumps(report)
        self.assertNotIn("private", encoded)
        self.assertNotIn("HOSTNAME", encoded)

    def test_service_checks_are_fixed_read_only_and_bounded(self):
        self.report()
        self.assertEqual(self.runner.call_count, 2)
        commands = [call.args[0] for call in self.runner.call_args_list]
        self.assertEqual(commands, [
            ["systemctl", "--user", "--no-pager", "is-active", "pipewire.service"],
            ["systemctl", "--user", "--no-pager", "is-active", "wireplumber.service"]])
        for call in self.runner.call_args_list:
            self.assertEqual(call.kwargs, {"capture_output": True, "text": True,
                                          "timeout": 2, "check": False})

    def test_kernel_report_is_informational_and_does_not_read_host_identity(self):
        with patch("evolinux.health.platform.node", side_effect=AssertionError("no host identity")):
            report = self.report(kernel_release="7.0.0-38-generic")
        self.assertEqual(report["kernel"], "7.0.0-38-generic")
        self.assertEqual(report["status"], "ready")
        invalid = self.report(kernel_release="7.0\nprivate HOSTNAME")
        self.assertIsNone(invalid["kernel"])
        self.assertNotIn("HOSTNAME", json.dumps(invalid))

    def test_inactive_service_is_warning_and_does_not_make_alsa_unusable(self):
        self.runner.return_value = SimpleNamespace(stdout="inactive\n", stderr="", returncode=3)
        report = self.report()
        self.assertEqual(report["status"], "warnings")
        self.assertEqual(report["software_prerequisites"], "ready")
        self.assertEqual(report["alsa"]["status"], "found")
        self.assertEqual(report["services"]["pipewire"]["state"], "inactive")

    def test_service_timeout_is_not_exported_with_command_output(self):
        self.runner.side_effect = subprocess.TimeoutExpired(
            "private user HOSTNAME", 2, output="private serial")
        report = self.report()
        self.assertEqual(report["services"]["wireplumber"]["error"]["kind"], "timeout")
        self.assertEqual(report["software_prerequisites"], "ready")
        self.assertNotIn("private", json.dumps(report))

    def test_missing_service_manager_preserves_errno(self):
        self.runner.side_effect = FileNotFoundError(errno.ENOENT, "private socket")
        report = self.report()
        self.assertEqual(report["services"]["pipewire"]["error"]["errno"], errno.ENOENT)
        self.assertNotIn("private socket", json.dumps(report))

    def test_service_error_stdout_and_stderr_are_not_exported(self):
        self.runner.return_value = SimpleNamespace(
            stdout="private HOSTNAME", stderr="private user socket", returncode=1)
        report = self.report()
        self.assertEqual(report["services"]["pipewire"]["state"], "unavailable")
        self.assertNotIn("private", json.dumps(report))

    def test_python_too_old_and_missing_library_fail_software_prerequisites(self):
        self.library.side_effect = OSError(errno.ENOENT, "private library path")
        report = self.report(python_version=(3, 9, 20))
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["software_prerequisites"], "missing")
        self.assertFalse(report["python"]["supported"])
        self.assertEqual(report["errors"][1]["errno"], errno.ENOENT)
        self.assertNotIn("private", json.dumps(report))
        self.backend.assert_not_called()

    def test_missing_library_without_errno_is_not_fabricated(self):
        self.library.side_effect = OSError("private host dependency could not load")
        report = self.report()
        self.assertEqual(report["errors"][0]["operation"], "native_library")
        self.assertIsNone(report["errors"][0]["errno"])
        self.assertNotIn("private host", json.dumps(report))

    def test_other_distribution_is_informational_not_strict_failure(self):
        self.release.write_text('ID=debian\nVERSION_ID="13"\n')
        report = self.report()
        self.assertEqual(report["status"], "warnings")
        self.assertEqual(report["software_prerequisites"], "ready")
        self.assertEqual(report["ubuntu"], {"id": "debian", "version_id": "13", "target": False})

    def test_os_release_ignores_identifying_text_and_rejects_malformed_target(self):
        self.release.write_text('ID="ubuntu private HOSTNAME"\nVERSION_ID="24.04"\n')
        report = self.report()
        self.assertEqual(report["ubuntu"]["id"], None)
        self.assertNotIn("HOSTNAME", json.dumps(report))
        self.assertEqual(report["software_prerequisites"], "ready")

    def test_os_release_is_bounded(self):
        self.release.write_bytes(b"x" * (health.MAX_OS_RELEASE_BYTES + 1))
        report = self.report()
        self.assertEqual(report["errors"][0]["errno"], errno.EOVERFLOW)

    def test_other_usb_cards_and_nonusb_cards_do_not_appear(self):
        (self.card / "usbid").write_text("1234:5678\n")
        (self.asound / "card4").mkdir()
        report = self.report()
        self.assertEqual(report["alsa"], {"status": "absent", "cards": []})
        self.assertEqual(report["software_prerequisites"], "ready")

    def test_missing_asound_root_preserves_errno_and_does_not_fake_card(self):
        report = self.report(asound_root=self.root / "missing")
        self.assertEqual(report["alsa"], {"status": "unavailable", "cards": []})
        self.assertEqual(report["errors"][0]["errno"], errno.ENOENT)

    def test_identity_bytes_are_bounded_and_utf8_is_not_accepted_as_ascii(self):
        (self.card / "usbid").write_bytes(b"x" * 65)
        self.assertEqual(self.report()["errors"][0]["errno"], errno.EOVERFLOW)
        (self.card / "usbid").write_bytes(b"\xff\xfe")
        report = self.report()
        self.assertIsNone(report["errors"][0]["errno"])
        self.assertEqual(report["alsa"]["cards"], [])

    def test_failed_mixer_metadata_preserves_detected_card_but_no_mappings(self):
        (self.card / "usbmixer").unlink()
        report = self.report()
        self.assertEqual(report["alsa"]["status"], "partial")
        card = report["alsa"]["cards"][0]
        self.assertEqual(card["card_number"], 3)
        self.assertEqual(card["mappings"], [])
        self.assertEqual(card["metadata_status"], "unavailable")
        self.assertEqual(report["errors"][0]["errno"], errno.ENOENT)

    def test_private_or_inconsistent_control_metadata_is_not_supported(self):
        for record in (RECORD.replace("control=11", "control=2"),
                       RECORD.replace("cmask=0xffffff", "cmask=0x1")):
            with self.subTest(record=record):
                (self.card / "usbmixer").write_text(HEADER + record)
                report = self.report()
                self.assertEqual(report["alsa"]["status"], "partial")
                self.assertEqual(report["alsa"]["cards"][0]["mappings"], [])

    def test_kernel_suppressing_errors_is_refused(self):
        (self.card / "usbmixer").write_text((HEADER + RECORD).replace("ctlerr=0", "ctlerr=1"))
        report = self.report()
        self.assertEqual(report["alsa"]["status"], "partial")
        self.assertEqual(report["alsa"]["cards"][0]["mappings"], [])

    def test_known_matrices_are_metadata_only_and_private_extension_is_excluded(self):
        matrix = ('  Unit: {unit}\n    Control: name="private matrix {unit}", index=0\n'
                  '    Info: id={unit}, control=34, cmask=0x{mask:x}, '
                  'channels={channels}, type="S16"\n')
        private = ('  Unit: 58\n    Control: name="private extension", index=0\n'
                   '    Info: id=58, control=1, cmask=0x1, channels=1, type="S16"\n')
        data = HEADER + matrix.format(unit=60, mask=0x3f, channels=6)
        data += matrix.format(unit=61, mask=0xf, channels=4) + private
        (self.card / "usbmixer").write_text(data)
        report = self.report()
        mappings = report["alsa"]["cards"][0]["mappings"]
        self.assertEqual([mapping["unit"] for mapping in mappings], [60, 61])
        self.assertEqual([mapping["channels"] for mapping in mappings], [6, 4])
        self.backend.assert_not_called()
        self.assertNotIn("private", json.dumps(report))

    def test_matrix_mapping_outside_reported_outputs_is_rejected(self):
        data = ('  Unit: 61\n    Control: name="matrix", index=0\n'
                '    Info: id=61, control=35, cmask=0x1f, channels=5, type="S16"\n')
        (self.card / "usbmixer").write_text(HEADER + data)
        report = self.report()
        self.assertEqual(report["alsa"]["status"], "partial")
        self.assertEqual(report["alsa"]["cards"][0]["mappings"], [])

    def test_mixer_metadata_is_bounded(self):
        (self.card / "usbmixer").write_bytes(b"x" * (health.MAX_METADATA_BYTES + 1))
        report = self.report()
        self.assertEqual(report["errors"][0]["errno"], errno.EOVERFLOW)

    def test_permission_error_is_preserved_without_path_disclosure(self):
        original = health._read_bounded

        def reader(path, *args):
            if Path(path).name == "usbmixer":
                raise PermissionError(errno.EACCES, "private card serial", str(path))
            return original(path, *args)

        with patch("evolinux.health._read_bounded", side_effect=reader):
            report = self.report()
        self.assertEqual(report["errors"][0]["errno"], errno.EACCES)
        self.assertNotIn(str(self.root), json.dumps(report))
        self.assertNotIn("private", json.dumps(report))

    def test_optional_gui_does_not_open_tk_or_block_cli(self):
        finder = Mock(return_value=None)
        report = self.report(environment={}, module_finder=finder)
        finder.assert_called_once_with("tkinter")
        self.assertEqual(report["gui"], {"tkinter_available": False,
                                        "display_available": False, "required_for_cli": False})
        self.assertEqual(report["status"], "ready")

    def test_optional_control_snapshot_is_explicit_and_redacts_identifying_text(self):
        snapshot = {"status": "partial", "cards": [{"card_number": 3, "name": "private serial",
            "controls": [{"numid": 7, "name": "private serial", "unit": 11,
                          "selector": 11, "values": None, "minimum": None}]}],
            "errors": [{"operation": "control_read", "errno": errno.EACCES,
                        "message": "private HOSTNAME", "card_number": 3, "numid": 7}]}
        backend = Mock()
        backend.snapshot.return_value = snapshot
        factory = Mock(return_value=backend)
        report = self.report(include_controls=True, backend_factory=factory)
        factory.assert_called_once_with(asound_root=self.asound)
        backend.snapshot.assert_called_once_with()
        self.assertEqual(report["controls"]["cards"][0]["controls"][0]["values"], None)
        self.assertEqual(report["controls"]["errors"][0]["errno"], errno.EACCES)
        self.assertNotIn("private", json.dumps(report))
        backend.set_value.assert_not_called()

    def test_optional_control_snapshot_failure_does_not_invent_values(self):
        factory = Mock(side_effect=OSError(errno.ENODEV, "private card"))
        report = self.report(include_controls=True, backend_factory=factory)
        self.assertEqual(report["controls"], {"status": "unavailable", "cards": [], "errors": []})
        self.assertEqual(report["errors"][0]["errno"], errno.ENODEV)
        self.assertEqual(report["software_prerequisites"], "ready")

    def test_invalid_parameters_are_rejected_before_any_service_or_library_call(self):
        with self.assertRaises(ValueError):
            self.report(include_controls="yes")
        with self.assertRaises(ValueError):
            self.report(python_version=(3, "12", 0))
        self.runner.assert_not_called()
        self.library.assert_not_called()


if __name__ == "__main__":
    unittest.main()
