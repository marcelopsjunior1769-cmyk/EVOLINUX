# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 EVOLINUX contributors
"""ALSA metadata and native ABI tests; no sound device is opened by these tests."""

import ctypes
from contextlib import contextmanager
import errno
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from evolinux.alsa import Element, NativeAlsaBackend, NativeCtl, parse_usbmixer


HEADER = "USB Mixer: usb_id=0x2708000a, ctrlif=0, ctlerr=0\nCard: private card identification\n"


def record(name, unit, selector, mask, channels, usb_type, index=0):
    return (f'  Unit: {unit}\n    Control: name="{name}", index={index}\n'
            f'    Info: id={unit}, control={selector}, cmask=0x{mask:x}, '
            f'channels={channels}, type="{usb_type}"\n')


def information(count, value_type="integer", minimum=0, maximum=100, step=1,
                **changes):
    result = {"count": count, "value_type": value_type, "minimum": minimum,
              "maximum": maximum, "step": step, "readable": True,
              "writable": True, "active": True, "locked": False}
    result["owner"] = False
    result.update(changes)
    return result


class FakeCtl:
    def __init__(self, state, card_number, *, library=None, readonly=True):
        self.state, self.card_number, self.readonly = state, card_number, readonly
        state["sessions"].append(self)

    def __enter__(self):
        if self.state.get("open_error"):
            raise self.state["open_error"]
        self.state["open"] += 1
        return self

    def __exit__(self, *exception):
        self.state["open"] -= 1

    def list_elements(self):
        callback = self.state.get("list_callback")
        if callback:
            callback()
        return list(self.state["elements"])

    def info(self, element):
        callback = self.state.get("info_callback")
        if callback:
            callback()
        return dict(self.state["infos"][element.numid])

    def read(self, element, info):
        if element.numid in self.state.get("read_errors", {}):
            raise self.state["read_errors"][element.numid]
        self.state["reads"].append(element.numid)
        callback = self.state.get("read_callback")
        if callback:
            callback(element)
        return list(self.state["values"][element.numid])

    def write(self, element, info, values):
        if self.readonly:
            raise AssertionError("test attempted to write a read-only session")
        self.state["writes"].append((element.numid, list(values)))
        if not self.state.get("ignore_write"):
            self.state["values"][element.numid] = list(values)
        return 0

    @contextmanager
    def lock(self, element):
        self.state["locks"] = self.state.get("locks", 0) + 1
        if self.state["infos"][element.numid]["locked"]:
            raise PermissionError(errno.EBUSY, "control is already locked")
        self.state["locked"] = True
        try:
            yield
        finally:
            self.state["locked"] = False


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.card = self.root / "card3"
        self.card.mkdir()
        (self.card / "usbid").write_text("2708:000a\n")
        self.metadata = HEADER + record("Input Gain Control", 11, 11, 0xffffff, 16, "S16")
        self.metadata += record("Phase Inverter Control", 11, 13, 0xffffff, 16, "BOOLEAN")
        self.metadata += record("Mixer Gain", 60, 1, 0x3f, 6, "S16")
        (self.card / "usbmixer").write_text(self.metadata)
        self.state = {"sessions": [], "open": 0, "writes": [], "reads": [],
                      "elements": [Element(7, "Input Gain Control"),
                                   Element(8, "Phase Inverter Control"),
                                   Element(9, "Mixer Gain"),
                                   Element(10, "Unrelated Control")],
                      "infos": {7: information(16),
                                8: information(16, "boolean", 0, 1),
                                9: information(6)},
                      "values": {7: list(range(10, 26)),
                                 8: [0, 1] * 8, 9: [0] * 6}}
        self.backend = NativeAlsaBackend(self.root, ctl_factory=self.factory)

    def factory(self, number, **kwargs):
        return FakeCtl(self.state, number, **kwargs)

    def test_snapshot_matches_only_supported_card_and_controls(self):
        other = self.root / "card5"
        other.mkdir()
        (other / "usbid").write_text("2708:000b\n")
        result = self.backend.snapshot()
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["errors"], [])
        self.assertEqual([card["card_number"] for card in result["cards"]], [3])
        controls = result["cards"][0]["controls"]
        self.assertEqual([control["id"] for control in controls], [7, 8, 9])
        self.assertEqual(controls[0]["values"], list(range(10, 26)))
        self.assertEqual(controls[0]["channel_numbers"], list(range(1, 17)))
        self.assertEqual([control["adjustable"] for control in controls], [True, True, False])
        self.assertTrue(all(session.readonly for session in self.state["sessions"]))
        self.assertEqual(self.state["reads"], [7, 8, 9])
        self.assertEqual(self.state["writes"], [])
        self.assertEqual(self.state["open"], 0)
        self.assertNotIn("private card identification", str(result))

    def test_new_driver_can_expose_all_24_channels(self):
        (self.card / "usbmixer").write_text(self.metadata.replace("channels=16", "channels=24"))
        for numid in (7, 8):
            self.state["infos"][numid]["count"] = 24
            self.state["values"][numid] += [0] * 8
        result = self.backend.snapshot()
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["cards"][0]["controls"][0]["channel_numbers"], list(range(1, 25)))

    def test_absent_and_unavailable_are_distinct(self):
        (self.card / "usbid").write_text("1234:5678\n")
        self.assertEqual(self.backend.snapshot(), {"status": "absent", "cards": [], "errors": []})
        unavailable = NativeAlsaBackend(self.root / "missing").snapshot()
        self.assertEqual(unavailable["status"], "unavailable")
        self.assertEqual(unavailable["errors"][0]["errno"], errno.ENOENT)

    def test_selected_control_does_not_read_other_controls_or_cards(self):
        other = self.root / "card5"
        other.mkdir()
        (other / "usbid").write_text("2708:000a\n")
        self.state["read_errors"] = {8: OSError(errno.EIO, "unrelated read failed")}
        result = self.backend.snapshot(card_number=3, numid=7)
        self.assertEqual(result["status"], "found")
        self.assertEqual(self.state["reads"], [7])
        self.assertEqual([session.card_number for session in self.state["sessions"]], [3])
        self.assertEqual([item["numid"] for item in result["cards"][0]["controls"]], [7])
        self.assertEqual(self.state["writes"], [])

    def test_missing_or_unsupported_selected_control_cannot_pass_as_found(self):
        for numid, code in ((99, errno.ENOENT), (10, errno.EOPNOTSUPP)):
            with self.subTest(numid=numid):
                result = self.backend.snapshot(card_number=3, numid=numid)
                self.assertEqual(result["status"], "partial")
                self.assertEqual(result["errors"][0]["errno"], code)
                self.assertEqual(result["cards"][0]["controls"], [])
        self.assertEqual(self.state["reads"], [])

    def test_invalid_snapshot_selection_fails_before_opening_any_card(self):
        for selection in ({"numid": 7}, {"card_number": -1}, {"card_number": True},
                          {"card_number": 3, "numid": 0}, {"card_number": 3, "numid": True}):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                self.backend.snapshot(**selection)
        self.assertEqual(self.state["sessions"], [])

    def test_plan_reads_one_selected_control_without_locks_or_writes(self):
        with patch.object(self.backend, "set_value", side_effect=AssertionError("must not set")):
            result = self.backend.plan_value(3, 7, 2, 40)
        self.assertEqual(result, {
            "card_number": 3, "numid": 7, "name": "Input Gain Control",
            "unit": 11, "selector": 11, "count": 16, "value_type": "integer",
            "minimum": 0, "maximum": 100, "step": 1,
            "channel_index": 2, "channel_position": 3, "usb_channel": 3,
            "current_value": 12, "target_value": 40, "would_change": True,
            "write_performed": False})
        self.assertEqual(self.state["reads"], [7])
        self.assertTrue(all(session.readonly for session in self.state["sessions"]))
        self.assertEqual(self.state["writes"], [])
        self.assertEqual(self.state.get("locks", 0), 0)
        self.assertEqual(self.state["values"][7], list(range(10, 26)))
        self.assertEqual(self.state["open"], 0)

    def test_plan_noop_still_reports_a_read_only_preview(self):
        result = self.backend.plan_value(3, 7, 0, 10)
        self.assertFalse(result["would_change"])
        self.assertFalse(result["write_performed"])
        self.assertEqual(self.state["reads"], [7])
        self.assertEqual(self.state["writes"], [])
        self.assertEqual(self.state.get("locks", 0), 0)

    def test_plan_phase_accepts_only_raw_zero_and_one(self):
        for value in (0, 1):
            with self.subTest(value=value):
                result = self.backend.plan_value(3, 8, 0, value)
                self.assertEqual(result["value_type"], "boolean")
                self.assertEqual(result["target_value"], value)
                self.assertEqual(result["current_value"], 0)
        with self.assertRaises(ValueError):
            self.backend.plan_value(3, 8, 0, 2)
        self.assertEqual(self.state["writes"], [])
        self.assertEqual(self.state.get("locks", 0), 0)

    def test_plan_invalid_arguments_fail_before_any_discovery(self):
        cases = ((True, 7, 0, 10), (-1, 7, 0, 10), (4096, 7, 0, 10),
                 (3, False, 0, 10), (3, 0, 0, 10), (3, 2**32, 0, 10),
                 (3, 7, False, 10), (3, 7, -1, 10), (3, 7, 128, 10),
                 (3, 7, 0, True), (3, 7, 0, -1), (3, 7, 0, 65536),
                 (3, 7, 0, "10"), (3, 7, 0, 10.0))
        with patch.object(self.backend, "snapshot", side_effect=AssertionError("must not discover")):
            for case in cases:
                with self.subTest(case=case), self.assertRaises(ValueError):
                    self.backend.plan_value(*case)
        self.assertEqual(self.state["sessions"], [])

    def test_plan_rejects_matrix_controls(self):
        with self.assertRaises(PermissionError) as raised:
            self.backend.plan_value(3, 9, 0, 20)
        self.assertEqual(raised.exception.errno, errno.EPERM)
        self.assertEqual(self.state["reads"], [9])
        self.assertEqual(self.state["writes"], [])
        self.assertEqual(self.state.get("locks", 0), 0)

    def test_plan_refuses_failed_read_and_preserves_errno(self):
        self.state["read_errors"] = {7: OSError(errno.ETIMEDOUT, "control timed out")}
        with self.assertRaises(OSError) as raised:
            self.backend.plan_value(3, 7, 0, 20)
        self.assertEqual(raised.exception.errno, errno.ETIMEDOUT)
        self.assertEqual(self.state["writes"], [])
        self.assertEqual(self.state.get("locks", 0), 0)
        self.assertEqual(self.state["open"], 0)

    def test_plan_absent_unavailable_or_incomplete_status_refuses(self):
        cases = (({"status": "absent", "cards": [], "errors": []}, errno.ENODEV),
                 ({"status": "unavailable", "cards": [], "errors": [
                     {"errno": errno.ENOENT, "message": "no ALSA tree"}]}, errno.ENOENT),
                 ({"status": "partial", "cards": [], "errors": []}, errno.EIO),
                 ({"status": "found", "cards": [], "errors": [
                     {"errno": errno.EBUSY, "message": "busy"}]}, errno.EBUSY),
                 ({"status": "unavailable", "cards": [], "errors": [
                     {"errno": None, "message": "missing libasound"}]}, errno.EIO))
        for snapshot, code in cases:
            with self.subTest(snapshot=snapshot):
                with patch.object(self.backend, "snapshot", return_value=snapshot):
                    with self.assertRaises(OSError) as raised:
                        self.backend.plan_value(3, 7, 0, 20)
                self.assertEqual(raised.exception.errno, code)
        self.assertEqual(self.state["sessions"], [])

    def test_plan_requires_exactly_the_requested_card_and_control(self):
        snapshot = self.backend.snapshot(card_number=3, numid=7)
        variants = ([], snapshot["cards"] * 2,
                    [{"card_number": 4, "controls": snapshot["cards"][0]["controls"]}],
                    [{"card_number": 3, "controls": []}],
                    [{"card_number": 3, "controls": snapshot["cards"][0]["controls"] * 2}],
                    [{"card_number": 3, "controls": [{"numid": 8}]}])
        for cards in variants:
            with self.subTest(cards=cards), patch.object(self.backend, "snapshot", return_value={
                    "status": "found", "cards": cards, "errors": []}):
                with self.assertRaises(OSError) as raised:
                    self.backend.plan_value(3, 7, 0, 20)
                self.assertEqual(raised.exception.errno, errno.EIO)
        self.assertEqual(self.state["writes"], [])

    def test_plan_bounds_and_step_follow_the_selected_control(self):
        with self.assertRaises(ValueError):
            self.backend.plan_value(3, 7, 16, 20)
        with self.assertRaises(ValueError):
            self.backend.plan_value(3, 7, 0, 101)
        self.state["infos"][7]["step"] = 2
        self.state["values"][7] = [10] * 16
        with self.assertRaises(ValueError):
            self.backend.plan_value(3, 7, 0, 11)
        self.state["infos"][7]["step"] = 0
        self.assertEqual(self.backend.plan_value(3, 7, 0, 11)["target_value"], 11)
        self.assertEqual(self.state["writes"], [])

    def test_plan_refuses_invalid_or_incomplete_control_data(self):
        snapshot = self.backend.snapshot(card_number=3, numid=7)
        control = snapshot["cards"][0]["controls"][0]
        variants = ({"values": None}, {"values": [True] * 16}, {"count": None},
                    {"channel_numbers": list(range(2, 18))}, {"step": "1"},
                    {"value_type": "integer64"}, {"readable": False})
        for variant in variants:
            with self.subTest(variant=variant):
                changed = dict(control, **variant)
                with patch.object(self.backend, "snapshot", return_value={"status": "found",
                        "errors": [], "cards": [{"card_number": 3, "controls": [changed]}]}):
                    with self.assertRaises(OSError):
                        self.backend.plan_value(3, 7, 0, 20)
        del control["values"]
        with patch.object(self.backend, "snapshot", return_value=snapshot):
            with self.assertRaises(OSError) as raised:
                self.backend.plan_value(3, 7, 0, 20)
        self.assertEqual(raised.exception.errno, errno.EIO)
        self.assertEqual(self.state["writes"], [])

    def test_missing_native_library_is_unavailable_even_with_known_card(self):
        with patch("evolinux.alsa.ctypes.CDLL", side_effect=OSError("missing libasound")):
            result = NativeAlsaBackend(self.root).snapshot()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["cards"], [{"card_number": 3, "controls": []}])
        self.assertEqual(result["errors"][0]["operation"], "native_library")

    def test_read_errno_is_preserved_without_values_or_adjustability(self):
        self.state["read_errors"] = {7: OSError(errno.EACCES, "denied")}
        result = self.backend.snapshot()
        control = result["cards"][0]["controls"][0]
        self.assertEqual(result["status"], "partial")
        self.assertIsNone(control["values"])
        self.assertFalse(control["adjustable"])
        self.assertEqual(result["errors"][0]["errno"], errno.EACCES)
        self.assertEqual(self.state["open"], 0)

    def test_card_open_failure_does_not_look_like_empty_success(self):
        self.state["open_error"] = OSError(errno.ENODEV, "unplugged")
        result = self.backend.snapshot()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["errors"][0]["errno"], errno.ENODEV)

    def test_inconsistent_count_does_not_read_control(self):
        self.state["infos"][7]["count"] = 15
        result = self.backend.snapshot()
        self.assertEqual(result["status"], "partial")
        self.assertNotIn(7, self.state["reads"])
        self.assertFalse(result["cards"][0]["controls"][0]["adjustable"])

    def test_locked_inactive_invalid_range_and_unknown_types_refuse_write(self):
        variants = ({"locked": True}, {"active": False}, {"maximum": 0},
                    {"step": -1}, {"step": 101}, {"value_type": "integer64"},
                    {"count": 129}, {"readable": False}, {"writable": False})
        for variant in variants:
            with self.subTest(variant=variant):
                self.state["infos"][7] = information(16)
                self.state["infos"][7].update(variant)
                with self.assertRaises(PermissionError):
                    self.backend.set_value(3, 7, 0, 20, authorized=True)
        self.assertEqual(self.state["writes"], [])

    def test_default_write_refusal_happens_before_discovery_or_open(self):
        with patch.object(self.backend, "_usb_id", side_effect=AssertionError("must not discover")):
            for authorization in (False, 1, "yes", None):
                with self.subTest(authorization=authorization):
                    with self.assertRaises(PermissionError):
                        self.backend.set_value(3, 7, 0, 20, authorized=authorization)
        self.assertEqual(self.state["sessions"], [])

    def test_authorized_write_preserves_fresh_values_and_supports_phase(self):
        reads = []
        def update(element):
            reads.append(element.numid)
            if len(reads) == 2:
                self.state["values"][7][1] = 70
        self.state["read_callback"] = update
        result = self.backend.set_value(3, 7, 0, 30, authorized=True)
        self.assertTrue(result["changed"])
        self.assertEqual(self.state["writes"][0][1][:3], [30, 70, 12])
        self.state.pop("read_callback")
        self.backend.set_value(3, 8, 0, 1, authorized=True)
        self.assertEqual(self.state["writes"][1][1], [1, 1] + [0, 1] * 7)
        self.assertEqual(self.state["open"], 0)
        self.assertFalse(self.state["locked"])

    def test_expected_current_type_is_checked_before_discovery(self):
        with patch.object(self.backend, "_usb_id", side_effect=AssertionError("must not discover")):
            for expected in (True, False, "10", 10.0, [], {}):
                with self.subTest(expected=expected), self.assertRaises(ValueError):
                    self.backend.set_value(3, 7, 0, 20, authorized=True,
                                           expected_current=expected)
        self.assertEqual(self.state["sessions"], [])

    def test_expected_current_does_not_grant_write_authorization(self):
        with patch.object(self.backend, "_usb_id", side_effect=AssertionError("must not discover")):
            with self.assertRaises(PermissionError) as raised:
                self.backend.set_value(3, 7, 0, 20, expected_current=10)
        self.assertEqual(raised.exception.errno, errno.EPERM)
        self.assertEqual(self.state["sessions"], [])

    def test_stale_expected_current_refuses_even_when_target_is_noop(self):
        for target in (10, 30):
            with self.subTest(target=target), self.assertRaises(OSError) as raised:
                self.backend.set_value(3, 7, 0, target, authorized=True, expected_current=9)
            self.assertEqual(raised.exception.errno, errno.EAGAIN)
            self.assertEqual(self.state["writes"], [])
            self.assertEqual(self.state["values"][7][0], 10)
            self.assertEqual(self.state["open"], 0)
            self.assertFalse(self.state["locked"])

    def test_expected_current_is_checked_against_final_read(self):
        reads = []
        def update(element):
            reads.append(element.numid)
            if len(reads) == 2:
                self.state["values"][7][0] = 30
        self.state["read_callback"] = update
        with self.assertRaises(OSError) as raised:
            self.backend.set_value(3, 7, 0, 40, authorized=True, expected_current=10)
        self.assertEqual(raised.exception.errno, errno.EAGAIN)
        self.assertEqual(self.state["reads"], [7, 7])
        self.assertEqual(self.state["writes"], [])
        self.assertEqual(self.state["values"][7][0], 30)
        self.assertEqual(self.state["open"], 0)
        self.assertFalse(self.state["locked"])

    def test_matching_current_guard_preserves_other_fresh_channels(self):
        reads = []
        def update(element):
            reads.append(element.numid)
            if len(reads) == 2:
                self.state["values"][7][1] = 70
        self.state["read_callback"] = update
        result = self.backend.set_value(3, 7, 0, 30, authorized=True, expected_current=10)
        self.assertTrue(result["changed"])
        self.assertEqual(self.state["writes"], [(7, [30, 70] + list(range(12, 26)))])
        self.assertEqual(result["values"], [30, 70] + list(range(12, 26)))
        self.assertEqual(self.state["open"], 0)
        self.assertFalse(self.state["locked"])

    def test_matching_current_guard_noop_does_not_write(self):
        result = self.backend.set_value(3, 7, 0, 10, authorized=True, expected_current=10)
        self.assertFalse(result["changed"])
        self.assertEqual(self.state["reads"], [7, 7])
        self.assertEqual(self.state["writes"], [])
        self.assertEqual(self.state["open"], 0)
        self.assertFalse(self.state["locked"])

    def test_guarded_phase_update_keeps_boolean_values(self):
        result = self.backend.set_value(3, 8, 0, 1, authorized=True, expected_current=0)
        self.assertTrue(result["changed"])
        self.assertEqual(result["values"], [1, 1] + [0, 1] * 7)
        with self.assertRaises(OSError) as raised:
            self.backend.set_value(3, 8, 0, 0, authorized=True, expected_current=0)
        self.assertEqual(raised.exception.errno, errno.EAGAIN)
        self.assertEqual(len(self.state["writes"]), 1)

    def test_readback_failure_is_not_reported_as_applied(self):
        self.state["ignore_write"] = True
        with self.assertRaises(OSError) as raised:
            self.backend.set_value(3, 7, 0, 30, authorized=True)
        self.assertEqual(raised.exception.errno, errno.EIO)
        self.assertEqual(self.state["open"], 0)
        self.assertFalse(self.state["locked"])

    def test_noop_is_evaluated_against_final_read(self):
        reads = []
        def update(element):
            reads.append(element.numid)
            if len(reads) == 2:
                self.state["values"][7][0] = 30
        self.state["read_callback"] = update
        result = self.backend.set_value(3, 7, 0, 10, authorized=True)
        self.assertTrue(result["changed"])
        self.assertEqual(result["values"][0], 10)

    def test_driver_error_suppression_is_rejected(self):
        (self.card / "usbmixer").write_text(self.metadata.replace("ctlerr=0", "ctlerr=1"))
        result = self.backend.snapshot()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.state["sessions"], [])
        self.assertIn("suppresses", result["errors"][0]["message"])

    def test_matrix_other_card_bad_channel_and_bounds_are_rejected(self):
        cases = ((3, 9, 0, 20, PermissionError), (3, 10, 0, 20, PermissionError),
                 (3, 7, 16, 20, ValueError), (3, 7, 0, 101, ValueError),
                 (3, 7, 0, -1, ValueError), (True, 7, 0, 20, ValueError),
                 (3, 7, 0, True, ValueError))
        for card, numid, channel, value, exception in cases:
            with self.subTest(case=(card, numid, channel, value)):
                with self.assertRaises(exception):
                    self.backend.set_value(card, numid, channel, value, authorized=True)
        (self.card / "usbid").write_text("1234:5678\n")
        with self.assertRaises(PermissionError):
            self.backend.set_value(3, 7, 0, 20, authorized=True)
        self.assertEqual(self.state["writes"], [])

    def test_step_alignment_is_checked_and_zero_step_allows_integers(self):
        self.state["infos"][7]["step"] = 2
        self.state["values"][7] = [10] * 16
        with self.assertRaises(ValueError):
            self.backend.set_value(3, 7, 0, 11, authorized=True)
        self.state["infos"][7]["step"] = 0
        self.backend.set_value(3, 7, 0, 11, authorized=True)
        self.assertEqual(self.state["writes"][0][1][0], 11)

    def test_identity_metadata_and_numid_races_refuse_write(self):
        for race in ("usb", "mapping", "info", "identity"):
            with self.subTest(race=race):
                self.setUp()
                counter = []
                def change(element):
                    counter.append(element)
                    if len(counter) != 1:
                        return
                    if race == "usb":
                        (self.card / "usbid").write_text("2708:000b\n")
                    elif race == "mapping":
                        (self.card / "usbmixer").write_text(self.metadata.replace("control=11", "control=12"))
                    elif race == "info":
                        self.state["infos"][7]["maximum"] = 99
                    else:
                        self.state["elements"][0] = Element(7, "Other Control")
                self.state["read_callback"] = change
                with self.assertRaises(OSError) as raised:
                    self.backend.set_value(3, 7, 0, 20, authorized=True)
                self.assertEqual(raised.exception.errno, errno.EAGAIN)
                self.assertEqual(self.state["writes"], [])
                self.assertEqual(self.state["open"], 0)

    def test_duplicate_control_mapping_and_wrong_usb_header_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_usbmixer(self.metadata + record("Input Gain Control", 11, 11, 0xffffff, 16, "S16"))
        with self.assertRaises(ValueError):
            parse_usbmixer(self.metadata.replace("0x2708000a", "0x12345678"))
        self.assertEqual(parse_usbmixer(self.metadata.replace("ctrlif=0", "ctrlif=1")), {})


class FakeFunction:
    def __init__(self, library, name):
        self.library, self.name = library, name

    def __call__(self, *arguments):
        return self.library.call(self.name, *arguments)


class FakeLibrary:
    """Opaque fake native pointers, with failures injected at C call boundaries."""
    def __init__(self):
        self.functions, self.buffers, self.calls = {}, {}, []
        self.serial = 100
        self.element = Element(5, "Input Gain Control")
        self.information = information(2, "integer64", -2**50, 2**50, 0)
        self.values = [-2**40, 2**40]
        self.failures = {}
        self.count = 1
        self.changed_identity = False
        self.io_numids = []

    def __getattr__(self, name):
        if not name.startswith("snd_ctl_"):
            raise AttributeError(name)
        if name not in self.functions:
            self.functions[name] = FakeFunction(self, name)
        return self.functions[name]

    def call(self, name, *args):
        self.calls.append(name)
        if name in ("snd_ctl_elem_info", "snd_ctl_elem_read", "snd_ctl_elem_write",
                    "snd_ctl_elem_lock", "snd_ctl_elem_unlock"):
            self.io_numids.append(self.buffers[args[1].value]["identity"]["numid"])
        if name in self.failures:
            return -self.failures[name]
        if name == "snd_ctl_open" or name.endswith("_malloc"):
            self.serial += 1
            ctypes.cast(args[0], ctypes.POINTER(ctypes.c_void_p))[0] = self.serial
            self.buffers[self.serial] = {}
            return 0
        buffer = self.buffers.get(args[0].value, {}) if args else {}
        if name == "snd_ctl_close" or name.endswith("_free"):
            self.buffers.pop(args[0].value)
            return 0
        if name == "snd_ctl_elem_list_get_count" or name == "snd_ctl_elem_list_get_used":
            return self.count
        if name == "snd_ctl_elem_list_get_id":
            self.buffers[args[2].value]["identity"] = self.element.__dict__.copy()
            return None
        if name.startswith("snd_ctl_elem_id_set_"):
            field = name.removeprefix("snd_ctl_elem_id_set_")
            buffer.setdefault("identity", {})[field] = args[1].decode() if field == "name" else args[1]
            return None
        if name.startswith("snd_ctl_elem_id_get_"):
            field = name.removeprefix("snd_ctl_elem_id_get_")
            value = buffer["identity"][field]
            return value.encode() if field == "name" else value
        if name in ("snd_ctl_elem_info_set_id", "snd_ctl_elem_value_set_id"):
            buffer["identity"] = self.buffers[args[1].value]["identity"].copy()
            return None
        if name in ("snd_ctl_elem_info_get_id", "snd_ctl_elem_value_get_id"):
            identity = buffer["identity"].copy()
            identity["numid"] = self.element.numid
            if self.changed_identity:
                identity["name"] = "A replacement control"
            self.buffers[args[1].value]["identity"] = identity
            return None
        if name.startswith("snd_ctl_elem_info_get_"):
            field = name.removeprefix("snd_ctl_elem_info_get_")
            if field == "type":
                return {"boolean": 1, "integer": 2, "integer64": 6}[self.information["value_type"]]
            field = {"min": "minimum", "max": "maximum"}.get(field.removesuffix("64"), field.removesuffix("64"))
            return self.information[field]
        if name.startswith("snd_ctl_elem_info_is_"):
            field = name.removeprefix("snd_ctl_elem_info_is_")
            return int(not self.information["active"] if field == "inactive" else self.information[field])
        if name.startswith("snd_ctl_elem_value_get_"):
            return self.values[args[1]]
        if name.startswith("snd_ctl_elem_value_set_"):
            buffer.setdefault("values", {})[args[1]] = args[2]
            return None
        return 0


class NativeCtlTests(unittest.TestCase):
    def test_opaque_list_info_and_integer64_values(self):
        library = FakeLibrary()
        with NativeCtl(3, library=library) as ctl:
            self.assertEqual(ctl.list_elements(), [library.element])
            info = ctl.info(library.element)
            self.assertEqual(info["minimum"], -2**50)
            self.assertEqual(ctl.read(library.element, info), [-2**40, 2**40])
        self.assertEqual(library.buffers, {})
        self.assertEqual(library.snd_ctl_elem_value_get_integer64.restype, ctypes.c_longlong)
        self.assertEqual(library.snd_ctl_elem_value_set_boolean.argtypes[-1], ctypes.c_long)
        self.assertEqual(library.snd_ctl_elem_value_get_boolean.restype, ctypes.c_long)
        self.assertIn("snd_ctl_elem_list_free_space", library.calls)

    def test_native_errors_preserve_errno_and_free_every_pointer(self):
        for name in ("snd_ctl_elem_list_alloc_space", "snd_ctl_elem_info_malloc",
                     "snd_ctl_elem_info", "snd_ctl_elem_read"):
            with self.subTest(name=name):
                library = FakeLibrary()
                library.failures[name] = errno.EACCES
                with self.assertRaises(OSError) as raised:
                    with NativeCtl(3, library=library) as ctl:
                        ctl.list_elements()
                        info = ctl.info(library.element)
                        ctl.read(library.element, info)
                self.assertEqual(raised.exception.errno, errno.EACCES)
                self.assertEqual(library.buffers, {})
                self.assertEqual(library.calls.count("snd_ctl_close"), 1)

    def test_limits_are_checked_before_native_values_are_accessed(self):
        library = FakeLibrary()
        library.count = 4097
        with NativeCtl(3, library=library) as ctl:
            with self.assertRaises(OSError) as raised:
                ctl.list_elements()
            self.assertEqual(raised.exception.errno, errno.EOVERFLOW)
            library.information["count"] = 129
            with self.assertRaises(OSError) as raised:
                ctl.info(library.element)
            self.assertEqual(raised.exception.errno, errno.EOVERFLOW)
        self.assertNotIn("snd_ctl_elem_list_alloc_space", library.calls)
        self.assertNotIn("snd_ctl_elem_read", library.calls)
        self.assertEqual(library.buffers, {})

    def test_replaced_native_identity_is_rejected(self):
        library = FakeLibrary()
        library.changed_identity = True
        with NativeCtl(3, library=library) as ctl:
            with self.assertRaises(OSError) as raised:
                ctl.info(library.element)
        self.assertEqual(raised.exception.errno, errno.EAGAIN)
        self.assertEqual(library.buffers, {})

    def test_native_read_failure_cannot_return_zero_initialized_fake_values(self):
        library = FakeLibrary()
        with NativeCtl(3, library=library) as ctl:
            info = ctl.info(library.element)
            library.failures["snd_ctl_elem_read"] = errno.EPIPE
            with self.assertRaises(OSError) as raised:
                ctl.read(library.element, info)
        self.assertEqual(raised.exception.errno, errno.EPIPE)
        self.assertNotIn("snd_ctl_elem_value_get_integer64", library.calls)
        self.assertEqual(library.buffers, {})

    def test_integer64_capacity_is_64_even_when_global_limit_is_128(self):
        library = FakeLibrary()
        library.information["count"] = 65
        with NativeCtl(3, library=library) as ctl:
            with self.assertRaises(OSError) as raised:
                ctl.info(library.element)
            self.assertEqual(raised.exception.errno, errno.EOVERFLOW)
            with self.assertRaises(OSError) as raised:
                ctl.read(library.element, library.information)
            self.assertEqual(raised.exception.errno, errno.EOVERFLOW)
        self.assertNotIn("snd_ctl_elem_read", library.calls)

    def test_closed_and_double_entered_sessions_fail_before_native_assertions(self):
        library = FakeLibrary()
        ctl = NativeCtl(3, library=library)
        with self.assertRaises(OSError) as raised:
            ctl.list_elements()
        self.assertEqual(raised.exception.errno, errno.EBADF)
        with ctl:
            with self.assertRaises(OSError) as raised:
                ctl.__enter__()
            self.assertEqual(raised.exception.errno, errno.EBUSY)
        with self.assertRaises(OSError):
            ctl.info(library.element)
        self.assertEqual(library.calls.count("snd_ctl_open"), 1)
        self.assertEqual(library.buffers, {})

    def test_control_lock_releases_and_preserves_primary_errno(self):
        library = FakeLibrary()
        library.failures["snd_ctl_elem_unlock"] = errno.ENODEV
        with NativeCtl(3, library=library, readonly=False) as ctl:
            with self.assertRaises(OSError) as raised:
                with ctl.lock(library.element):
                    raise OSError(errno.ETIMEDOUT, "write timed out")
        self.assertEqual(raised.exception.errno, errno.ETIMEDOUT)
        self.assertIn("snd_ctl_elem_unlock", library.calls)
        self.assertEqual(library.buffers, {})

    def test_native_io_uses_full_identity_instead_of_reusable_numid(self):
        library = FakeLibrary()
        with NativeCtl(3, library=library, readonly=False) as ctl:
            with ctl.lock(library.element):
                info = ctl.info(library.element)
                values = ctl.read(library.element, info)
                self.assertEqual(ctl.write(library.element, info, values), 0)
        self.assertEqual(library.io_numids, [0] * len(library.io_numids))
        self.assertEqual(library.buffers, {})


if __name__ == "__main__":
    unittest.main()
