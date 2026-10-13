# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 EVOLINUX contributors
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from evolinux import cli


class CliTests(unittest.TestCase):
    def test_preview_builds_manual_apply_arguments_without_calling_set(self):
        stream = io.StringIO()
        with patch.object(cli, "NativeAlsaBackend") as backend, contextlib.redirect_stdout(stream):
            backend.return_value.plan_value.return_value = {
                "current_value": 12, "target_value": 30, "write_performed": False}
            self.assertEqual(cli.main(["plan-set", "--card", "3", "--control", "7",
                                       "--channel", "2", "--value", "30", "--json"]), 0)
        backend.return_value.plan_value.assert_called_once_with(3, 7, 1, 30)
        backend.return_value.set_value.assert_not_called()
        report = json.loads(stream.getvalue())
        self.assertFalse(report["write_performed"])
        self.assertEqual(report["apply_arguments"], ["evolinux", "set", "--card", "3",
            "--control", "7", "--channel", "2", "--value", "30", "--expect-current", "12",
            "--authorize-alsa-write"])

    def test_confirmed_value_is_forwarded_only_for_explicit_write(self):
        with patch.object(cli, "NativeAlsaBackend") as backend, contextlib.redirect_stdout(io.StringIO()):
            backend.return_value.set_value.return_value = {"changed": True}
            self.assertEqual(cli.main(["set", "--card", "3", "--control", "7", "--channel", "2",
                "--value", "30", "--expect-current", "12", "--authorize-alsa-write"]), 0)
        backend.return_value.set_value.assert_called_once_with(3, 7, 1, 30,
                                                              authorized=True, expected_current=12)

    def test_unchanged_preview_does_not_print_an_apply_command(self):
        stream = io.StringIO()
        with patch.object(cli, "NativeAlsaBackend") as backend, contextlib.redirect_stdout(stream):
            backend.return_value.plan_value.return_value = {
                "card_number": 3, "numid": 7, "name": "Input Gain", "channel_position": 1,
                "current_value": 12, "target_value": 12, "minimum": 0, "maximum": 100,
                "step": 1, "would_change": False, "write_performed": False}
            self.assertEqual(cli.main(["plan-set", "--card", "3", "--control", "7",
                                       "--channel", "1", "--value", "12"]), 0)
        self.assertIn("nenhum ajuste é necessário", stream.getvalue())
        self.assertNotIn("--authorize-alsa-write", stream.getvalue())
        backend.return_value.set_value.assert_not_called()

    def test_failed_preview_does_not_suggest_or_execute_a_write(self):
        stream = io.StringIO()
        with patch.object(cli, "NativeAlsaBackend") as backend, contextlib.redirect_stdout(stream), contextlib.redirect_stderr(io.StringIO()):
            backend.return_value.plan_value.side_effect = OSError(5, "read failed")
            self.assertEqual(cli.main(["plan-set", "--card", "3", "--control", "7",
                "--channel", "1", "--value", "30", "--json"]), 1)
        backend.return_value.set_value.assert_not_called()
        self.assertEqual(stream.getvalue(), "")

    def test_invalid_preview_address_is_refused_before_backend_discovery(self):
        with patch.object(cli, "NativeAlsaBackend") as backend, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli.main(["plan-set", "--card", "-1", "--control", "7", "--channel", "1", "--value", "30"])
        backend.assert_not_called()

    def test_doctor_defaults_to_metadata_only(self):
        with patch("evolinux.health.check_environment") as check, contextlib.redirect_stdout(io.StringIO()):
            check.return_value = {"status": "ready", "software_prerequisites": "ready"}
            self.assertEqual(cli.main(["doctor", "--json"]), 0)
        check.assert_called_once_with(include_controls=False)

    def test_binary_gain_read_reports_why_adjustment_is_blocked(self):
        stream = io.StringIO()
        with patch.object(cli, "NativeAlsaBackend") as backend, contextlib.redirect_stdout(stream):
            backend.return_value.snapshot.return_value = {
                "status": "found", "errors": [], "cards": [{"card_number": 1,
                "controls": [{"numid": 1, "name": "Input Gain Control", "unit": 11,
                              "selector": 11, "count": 16, "values": [0] * 16,
                              "minimum": 0, "maximum": 1, "step": 0,
                              "adjustable": False,
                              "adjustment_block_reason": "gain_range_not_validated"}]}]}
            self.assertEqual(cli.main(["status", "--card", "1", "--control", "1"]), 0)
        self.assertIn("Somente leitura", stream.getvalue())
        self.assertIn("Ajuste bloqueado", stream.getvalue())
        self.assertNotIn("Ajustável com autorização", stream.getvalue())
        backend.return_value.set_value.assert_not_called()

    def test_doctor_reads_controls_only_when_explicitly_requested(self):
        with patch("evolinux.health.check_environment") as check, contextlib.redirect_stdout(io.StringIO()):
            check.return_value = {"status": "warnings", "software_prerequisites": "ready"}
            self.assertEqual(cli.main(["doctor", "--json", "--controls"]), 2)
        check.assert_called_once_with(include_controls=True)

    def test_doctor_displays_actual_metadata_counts_without_reading_controls(self):
        stream = io.StringIO()
        with patch("evolinux.health.check_environment") as check, contextlib.redirect_stdout(stream):
            check.return_value = {"status": "ready", "software_prerequisites": "ready",
                "alsa": {"cards": [{"card_number": 1, "metadata_summary": {
                    "mapped_control_count": 50, "reported_value_count": 272,
                    "features": [{"unit": 11, "selector": 11,
                                  "channel_numbers": list(range(1, 17))}],
                    "matrices": [{"unit": 60, "rows": [{}] * 24,
                                  "reported_value_count": 144},
                                 {"unit": 61, "rows": [{}] * 24,
                                  "reported_value_count": 96}]}}]}}
            self.assertEqual(cli.main(["doctor"]), 0)
        check.assert_called_once_with(include_controls=False)
        output = stream.getvalue()
        self.assertIn("Placa 1: 50 controles mapeados, 272 posições ALSA", output)
        self.assertIn("seletor 11: 16 posições ALSA", output)
        self.assertIn("Unidade 60: 24 controles de entrada, 144 posições ALSA", output)
        self.assertIn("Unidade 61: 24 controles de entrada, 96 posições ALSA", output)

    def test_doctor_does_not_show_invented_counts_for_missing_metadata(self):
        stream = io.StringIO()
        with patch("evolinux.health.check_environment") as check, contextlib.redirect_stdout(stream):
            check.return_value = {"status": "warnings", "software_prerequisites": "ready",
                                 "alsa": {"cards": [{"card_number": 1}]}}
            self.assertEqual(cli.main(["doctor"]), 2)
        check.assert_called_once_with(include_controls=False)
        self.assertIn("Placa 1: metadados incompletos", stream.getvalue())
        self.assertNotIn("posições ALSA", stream.getvalue())

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
