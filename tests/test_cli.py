# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 EVOLINUX contributors
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from evolinux import cli


class CliTests(unittest.TestCase):
    def test_doctor_defaults_to_metadata_only(self):
        with patch("evolinux.health.check_environment") as check, contextlib.redirect_stdout(io.StringIO()):
            check.return_value = {"status": "ready", "software_prerequisites": "ready"}
            self.assertEqual(cli.main(["doctor", "--json"]), 0)
        check.assert_called_once_with(include_controls=False)

    def test_doctor_reads_controls_only_when_explicitly_requested(self):
        with patch("evolinux.health.check_environment") as check, contextlib.redirect_stdout(io.StringIO()):
            check.return_value = {"status": "warnings", "software_prerequisites": "ready"}
            self.assertEqual(cli.main(["doctor", "--json", "--controls"]), 2)
        check.assert_called_once_with(include_controls=True)

    def test_selected_control_is_passed_to_native_backend(self):
        with patch.object(cli, "NativeAlsaBackend") as backend, contextlib.redirect_stdout(io.StringIO()):
            backend.return_value.snapshot.return_value = {"status": "found", "cards": [], "errors": []}
            self.assertEqual(cli.main(["status", "--card", "3", "--control", "7", "--json"]), 0)
        backend.return_value.snapshot.assert_called_once_with(card_number=3, numid=7)

    def test_control_without_card_is_refused_before_discovery(self):
        with patch.object(cli, "NativeAlsaBackend") as backend, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli.main(["status", "--control", "7"])
        backend.assert_not_called()

    def test_help_does_not_open_audio_controls(self):
        with patch.object(cli, "NativeAlsaBackend") as backend, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main([]), 0)
        backend.assert_not_called()

    def test_unauthorized_set_is_refused_before_device_discovery(self):
        with patch.object(cli, "NativeAlsaBackend") as backend, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                cli.main(["set", "--card", "0", "--control", "1", "--channel", "1", "--value", "0"])
        self.assertEqual(raised.exception.code, 2)
        backend.assert_not_called()

    def test_explicit_request_preserves_value_and_converts_channel_position(self):
        with patch.object(cli, "NativeAlsaBackend") as backend, contextlib.redirect_stdout(io.StringIO()):
            backend.return_value.set_value.return_value = {"values": [12, 3]}
            result = cli.main(["set", "--card", "2", "--control", "7", "--channel", "2",
                               "--value", "3", "--authorize-alsa-write"])
        self.assertEqual(result, 0)
        backend.return_value.set_value.assert_called_once_with(2, 7, 1, 3, authorized=True)

    def test_kernel_failure_is_not_reported_as_a_successful_adjustment(self):
        with patch.object(cli, "NativeAlsaBackend") as backend, contextlib.redirect_stderr(io.StringIO()):
            backend.return_value.set_value.side_effect = OSError(16, "Device or resource busy")
            result = cli.main(["set", "--card", "2", "--control", "7", "--channel", "1",
                               "--value", "3", "--authorize-alsa-write"])
        self.assertEqual(result, 1)

    def test_absence_and_partial_reads_cannot_pass_as_hardware_readiness(self):
        for state, code in [("absent", 2), ("partial", 1), ("unavailable", 1)]:
            stream = io.StringIO()
            with self.subTest(state=state), patch.object(cli, "NativeAlsaBackend") as backend, contextlib.redirect_stdout(stream):
                backend.return_value.snapshot.return_value = {"status": state, "cards": [], "errors": []}
                self.assertEqual(cli.main(["status", "--json"]), code)
            self.assertEqual(json.loads(stream.getvalue())["status"], state)
