# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 EVOLINUX contributors
"""Regressions for EVO16 metadata supplied from Ubuntu 24.04.4.

The original USB fixture contains numeric USB Mixer/Unit/Info records. Later
fixtures preserve observed ALSA identities, their complete USB associations,
the reported gain range/values, and phase values. Matrix ranges/values and
unreported runtime flags remain synthetic, as do the explicit synthetic-
identity tests for the original numeric fixture.
Every CTL session is fake; none of these tests validates hardware effects.
"""

import errno
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from evolinux.alsa import Element, NativeAlsaBackend, parse_usbmixer
from evolinux.health import check_environment


FIXTURE = Path(__file__).parent / "fixtures" / "evo16-ubuntu-24.04-usbmixer-inventory.txt"
AMIXER_FIXTURE = Path(__file__).parent / "fixtures" / "evo16-ubuntu-24.04-amixer-controls.txt"
CONTROLS_FIXTURE = Path(__file__).parent / "fixtures" / "evo16-ubuntu-24.04-usbmixer-controls.txt"
GAIN_FIXTURE = Path(__file__).parent / "fixtures" / "evo16-ubuntu-24.04-input-gain.txt"
PHASE_FIXTURE = Path(__file__).parent / "fixtures" / "evo16-ubuntu-24.04-phase-inverter.txt"
INFO = re.compile(
    r'\s*Info: id=(\d+), control=(\d+), cmask=0x([0-9a-f]+), '
    r'channels=(\d+), type="([A-Z0-9_]+)"')
AMIXER_IDENTITY = re.compile(
    r"numid=(\d+),iface=(MIXER|CARD),name='([^']+)'(?:,index=(\d+))?")


def synthetic_control_identities(metadata):
    """Add clearly fake identities only for exercising the live mapping path."""
    lines, elements, infos, values, addresses = [], [], {}, {}, {}
    for line in metadata.splitlines():
        match = INFO.fullmatch(line)
        if match:
            unit, selector, mask, channels, usb_type = match.groups()
            unit, selector, channels = int(unit), int(selector), int(channels)
            name = f"SYNTHETIC ONLY Unit {unit} Selector {selector}"
            # The observed metadata contains no names, indices, or numids.
            numid = 1001 + len(elements)
            lines.append(f'    Control: name="{name}", index=0')
            elements.append(Element(numid, name))
            addresses[(unit, selector)] = numid
            if unit in (11, 60, 61):
                boolean = usb_type == "BOOLEAN"
                infos[numid] = {
                    "count": channels,
                    "value_type": "boolean" if boolean else "integer",
                    "minimum": 0,
                    "maximum": 1 if boolean else 100,
                    "step": 1,
                    "readable": True,
                    "writable": True,
                    "active": True,
                    "locked": False,
                    "owner": False,
                }
                values[numid] = ([0, 1] * 8 if boolean else
                                 list(range(10, 10 + channels)))
        lines.append(line)
    return "\n".join(lines) + "\n", elements, infos, values, addresses


def observed_amixer_elements():
    """Read observed identities without inferring from numid/name alone."""
    result = []
    for line in AMIXER_FIXTURE.read_text(encoding="ascii").splitlines():
        match = AMIXER_IDENTITY.fullmatch(line)
        if match is None:
            raise ValueError("invalid observed amixer identity fixture")
        numid, interface, name, index = match.groups()
        result.append(Element(int(numid), name, int(index or 0),
                              interface={"CARD": 0, "MIXER": 2}[interface]))
    return result


def observed_input_gain():
    """Read the supplied cget facts; status flags not in that output are fake."""
    identity, descriptor, values_line = GAIN_FIXTURE.read_text(encoding="ascii").splitlines()
    if identity != "numid=1,iface=MIXER,name='Input Gain Control'":
        raise ValueError("unexpected gain fixture identity")
    descriptor = re.fullmatch(
        r"\s*; type=INTEGER,access=rw------,values=(\d+),min=(\d+),max=(\d+),step=(\d+)",
        descriptor)
    values = re.fullmatch(r"\s*: values=(\d+(?:,\d+)*)", values_line)
    if descriptor is None or values is None:
        raise ValueError("invalid observed gain fixture")
    count, minimum, maximum, step = map(int, descriptor.groups())
    info = {"count": count, "value_type": "integer", "minimum": minimum,
            "maximum": maximum, "step": step, "readable": True, "writable": True,
            # These flags exercise the backend; cget did not report their state.
            "active": True, "locked": False, "owner": False}
    return info, list(map(int, values[1].split(",")))


def observed_phase_inverter():
    """Normalize supplied off/on values using the native BOOLEAN policy."""
    identity, descriptor, values_line = PHASE_FIXTURE.read_text(encoding="ascii").splitlines()
    if identity != "numid=2,iface=MIXER,name='Phase Inverter Control'":
        raise ValueError("unexpected phase fixture identity")
    descriptor = re.fullmatch(
        r"\s*; type=BOOLEAN,access=rw------,values=(\d+)", descriptor)
    values = re.fullmatch(r"\s*: values=((?:off|on)(?:,(?:off|on))*)", values_line)
    if descriptor is None or values is None:
        raise ValueError("invalid observed phase fixture")
    info = {"count": int(descriptor[1]), "value_type": "boolean",
            # NativeCtl derives these BOOLEAN limits; cget did not report them.
            "minimum": 0, "maximum": 1, "step": 1,
            "readable": True, "writable": True,
            # These flags exercise the backend; cget did not report their state.
            "active": True, "locked": False, "owner": False}
    return info, [{"off": 0, "on": 1}[value] for value in values[1].split(",")]


class ReadOnlyProfileCtl:
    """Fail immediately on writable access, locks, or unsupported controls."""

    def __init__(self, state, card_number, *, library=None, readonly=True):
        if readonly is not True:
            raise AssertionError("profile regression requested a writable CTL")
        self.state = state
        state["sessions"].append((card_number, readonly))

    def __enter__(self):
        self.state["open"] += 1
        return self

    def __exit__(self, *exception):
        self.state["open"] -= 1

    def list_elements(self):
        return list(self.state["elements"])

    def info(self, element):
        if element.numid not in self.state["infos"]:
            raise AssertionError("unmapped control was queried")
        self.state["queries"].append(element.numid)
        return dict(self.state["infos"][element.numid])

    def read(self, element, info):
        self.state["reads"].append(element.numid)
        return list(self.state["values"][element.numid])

    def write(self, *arguments):
        raise AssertionError("profile regression attempted a control write")

    def lock(self, *arguments):
        raise AssertionError("profile regression attempted a control lock")


class RealMixerProfileTests(unittest.TestCase):
    def setUp(self):
        self.metadata = FIXTURE.read_text(encoding="ascii")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.card = self.root / "card1"
        self.card.mkdir()
        (self.card / "usbid").write_text("2708:000a\n", encoding="ascii")
        (metadata, elements, infos, values,
         self.addresses) = synthetic_control_identities(self.metadata)
        (self.card / "usbmixer").write_text(metadata, encoding="ascii")
        self.state = {"elements": elements, "infos": infos, "values": values,
                      "sessions": [], "reads": [], "queries": [], "open": 0}
        self.backend = NativeAlsaBackend(self.root, ctl_factory=self.factory)

    def factory(self, card_number, **kwargs):
        return ReadOnlyProfileCtl(self.state, card_number, **kwargs)

    def test_fixture_preserves_numeric_records_without_inventing_identities(self):
        self.assertEqual(self.metadata.splitlines()[0],
                         "USB Mixer: usb_id=0x2708000a, ctrlif=0, ctlerr=0")
        records = [INFO.fullmatch(line).groups()
                   for line in self.metadata.splitlines() if INFO.fullmatch(line)]
        self.assertEqual(len(records), 54)
        self.assertEqual(records[:6], [
            ("11", "13", "ffffff", "16", "BOOLEAN"),
            ("11", "11", "ffffff", "16", "S16"),
            ("40", "1", "0", "1", "U8"),
            ("41", "2", "0", "1", "BOOLEAN"),
            ("44", "2", "0", "1", "BOOLEAN"),
            ("45", "2", "0", "1", "BOOLEAN"),
        ])
        for unit, mask, count in (("60", "3f", "6"), ("61", "f", "4")):
            with self.subTest(unit=unit):
                self.assertEqual([record for record in records if record[0] == unit],
                                 [(unit, str(selector), mask, count, "S16")
                                  for selector in range(24, 0, -1)])
        self.assertNotIn("Control:", self.metadata)
        self.assertNotIn("numid", self.metadata)
        self.assertNotIn("Card:", self.metadata)
        self.assertNotIn("@", self.metadata)
        # Numeric observations cannot authorize a guessed ALSA identity.
        self.assertEqual(parse_usbmixer(self.metadata), {})

    def test_identity_free_fixture_is_refused_before_any_ctl_session(self):
        (self.card / "usbmixer").write_text(self.metadata, encoding="ascii")
        result = self.backend.snapshot(card_number=1)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["cards"], [{"card_number": 1, "controls": []}])
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(self.state["sessions"], [])
        self.assertEqual(self.state["reads"], [])

    def test_named_mapping_respects_reported_16_positions_and_24_matrix_rows(self):
        mappings = list(parse_usbmixer(
            (self.card / "usbmixer").read_text(encoding="ascii")).values())
        self.assertEqual(len(mappings), 50)
        features = [mapping for mapping in mappings if mapping.unit == 11]
        self.assertEqual(len(features), 2)
        self.assertEqual({mapping.selector for mapping in features}, {11, 13})
        for mapping in features:
            self.assertEqual(mapping.channel_mask, 0xffffff)
            self.assertEqual(mapping.channels, 16)
            self.assertEqual(mapping.channel_numbers(), list(range(1, 17)))
        for unit, outputs in ((60, 6), (61, 4)):
            rows = [mapping for mapping in mappings if mapping.unit == unit]
            with self.subTest(unit=unit):
                self.assertEqual([mapping.selector for mapping in rows],
                                 list(range(24, 0, -1)))
                self.assertTrue(all(mapping.channels == outputs for mapping in rows))
                self.assertTrue(all(mapping.channel_numbers() == list(range(1, outputs + 1))
                                    for mapping in rows))
        self.assertEqual(sum(mapping.channels for mapping in mappings), 272)

    def test_fake_snapshot_reads_50_controls_272_values_and_excludes_clocks(self):
        result = self.backend.snapshot(card_number=1)
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["errors"], [])
        self.assertEqual([card["card_number"] for card in result["cards"]], [1])
        controls = result["cards"][0]["controls"]
        self.assertEqual(len(controls), 50)
        self.assertEqual(sum(len(control["values"]) for control in controls), 272)
        self.assertEqual(len(self.state["reads"]), 50)
        self.assertEqual(set(self.state["reads"]), set(self.state["infos"]))
        self.assertEqual(self.state["sessions"], [(1, True)])
        self.assertEqual(self.state["open"], 0)
        self.assertEqual(sum(control["adjustable"] for control in controls), 2)
        for unit in (60, 61):
            self.assertEqual({control["selector"] for control in controls
                              if control["unit"] == unit}, set(range(1, 25)))

    def test_selected_feature_reads_only_one_synthetic_control(self):
        for selector in (11, 13):
            with self.subTest(selector=selector):
                self.state["reads"].clear()
                self.state["queries"].clear()
                self.state["sessions"].clear()
                numid = self.addresses[(11, selector)]
                result = self.backend.snapshot(card_number=1, numid=numid)
                self.assertEqual(result["status"], "found")
                controls = result["cards"][0]["controls"]
                self.assertEqual(len(controls), 1)
                self.assertEqual(controls[0]["numid"], numid)
                self.assertEqual(controls[0]["channel_numbers"], list(range(1, 17)))
                self.assertEqual(self.state["queries"], [numid])
                self.assertEqual(self.state["reads"], [numid])
                self.assertEqual(self.state["sessions"], [(1, True)])
                self.assertEqual(self.state["open"], 0)

    def test_doctor_reports_observed_matrix_dimensions_without_opening_ctl(self):
        release = self.root / "os-release"
        release.write_text('ID=ubuntu\nVERSION_ID="24.04"\n', encoding="ascii")
        backend = Mock(side_effect=AssertionError("doctor must not open CTL"))
        library = Mock(return_value=object())
        runner = Mock(return_value=SimpleNamespace(
            stdout="active\n", stderr="", returncode=0))
        report = check_environment(
            asound_root=self.root, os_release_path=release,
            python_version=(3, 12, 3), kernel_release="7.0.0-38-generic",
            library_loader=library, service_runner=runner,
            backend_factory=backend, environment={},
            module_finder=Mock(return_value=None))
        self.assertEqual(report["status"], "ready")
        self.assertFalse(report["physical_audio_validated"])
        summary = report["alsa"]["cards"][0]["metadata_summary"]
        self.assertEqual(summary["mapped_control_count"], 50)
        self.assertEqual(summary["reported_value_count"], 272)
        self.assertEqual(summary["features"], [
            {"unit": 11, "selector": selector,
             "channel_numbers": list(range(1, 17))}
            for selector in (11, 13)])
        self.assertEqual(summary["matrices"], [
            {"unit": unit,
             "rows": [{"input_selector": selector,
                       "output_channels": list(range(1, outputs + 1))}
                      for selector in range(1, 25)],
             "reported_value_count": 24 * outputs}
            for unit, outputs in ((60, 6), (61, 4))])
        backend.assert_not_called()
        library.assert_called_once_with("libasound.so.2", use_errno=True)
        self.assertNotIn("controls", report)
        self.assertNotIn("SYNTHETIC ONLY", str(report))
        self.assertEqual(self.state["sessions"], [])
        self.assertEqual(self.state["reads"], [])

    def test_preview_uses_16_reported_positions_and_never_invents_position_17(self):
        numid = self.addresses[(11, 11)]
        result = self.backend.plan_value(1, numid, 15, 40)
        self.assertEqual(result["count"], 16)
        self.assertEqual(result["channel_position"], 16)
        self.assertEqual(result["usb_channel"], 16)
        self.assertEqual(result["current_value"], 25)
        self.assertFalse(result["write_performed"])
        with self.assertRaises(ValueError):
            self.backend.plan_value(1, numid, 16, 40)
        self.assertEqual(self.state["reads"], [numid, numid])
        self.assertEqual(self.state["sessions"], [(1, True), (1, True)])
        self.assertEqual(self.state["open"], 0)
        self.assertEqual(self.state["values"][numid], list(range(10, 26)))


class ObservedAlsaIdentityTests(unittest.TestCase):
    """Observed identities/mappings/gain/phase with fake matrix values."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.card = self.root / "card1"
        self.card.mkdir()
        (self.card / "usbid").write_text("2708:000a\n", encoding="ascii")
        self.metadata = CONTROLS_FIXTURE.read_text(encoding="ascii")
        (self.card / "usbmixer").write_text(self.metadata, encoding="ascii")
        common = {"minimum": 0, "step": 1, "readable": True,
                  "writable": True, "active": True, "locked": False,
                  "owner": False}
        self.state = {
            "elements": observed_amixer_elements(),
            "infos": {}, "values": {},
            "sessions": [], "reads": [], "queries": [], "open": 0,
        }
        mappings = parse_usbmixer(self.metadata)
        for element in self.state["elements"]:
            mapping = mappings.get((element.name, element.index))
            if mapping is None or element.interface != 2:
                continue
            if element.numid == 1:
                self.state["infos"][1], self.state["values"][1] = observed_input_gain()
            elif element.numid == 2:
                self.state["infos"][2], self.state["values"][2] = observed_phase_inverter()
            else:
                # Matrix ranges/values have not been supplied; fakes
                # verify identity mapping without claiming physical validation.
                boolean = mapping.usb_type == "BOOLEAN"
                self.state["infos"][element.numid] = dict(
                    common, count=mapping.channels,
                    value_type="boolean" if boolean else "integer",
                    maximum=1 if boolean else 100)
                self.state["values"][element.numid] = [0] * mapping.channels
        self.backend = NativeAlsaBackend(self.root, ctl_factory=self.factory)

    def factory(self, card_number, **kwargs):
        return ReadOnlyProfileCtl(self.state, card_number, **kwargs)

    def test_observed_identity_fixture_keeps_indices_and_card_interfaces(self):
        elements = self.state["elements"]
        self.assertEqual(len(elements), 54)
        self.assertEqual(elements[:2], [Element(1, "Input Gain Control"),
                                       Element(2, "Phase Inverter Control")])
        self.assertEqual(elements[2:50], [
            Element(index + 3, "Analogue 5 Volume", index=index)
            for index in range(48)])
        self.assertEqual(elements[50:], [
            Element(51, "Audient Internal Clock Validity", interface=0),
            Element(52, "Audient Optical1 Clock Validity", interface=0),
            Element(53, "Audient Optical2 Clock Validity", interface=0),
            Element(54, "Audient Clock Selector Clock Source"),
        ])
        self.assertEqual(len({(element.name, element.index, element.interface,
                               element.device, element.subdevice)
                              for element in elements}), 54)

    def test_same_name_requires_exact_index_and_never_queries_clocks(self):
        result = self.backend.snapshot(card_number=1)
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["errors"], [])
        controls = result["cards"][0]["controls"]
        self.assertEqual([control["numid"] for control in controls], list(range(1, 51)))
        self.assertEqual([control["index"] for control in controls],
                         [0, 0] + list(range(48)))
        self.assertEqual(self.state["queries"], list(range(1, 51)))
        self.assertEqual(self.state["reads"], list(range(1, 51)))
        self.assertEqual(sum(len(control["values"]) for control in controls), 272)
        self.assertEqual(self.state["sessions"], [(1, True)])
        self.assertEqual(self.state["open"], 0)

    def test_selected_matrix_reads_only_the_matching_index(self):
        # Adjacent observed indices straddle the unit60/unit61 boundary.
        for numid, index, unit, selector, count in (
                (26, 23, 60, 24, 6), (27, 24, 61, 1, 4)):
            with self.subTest(numid=numid):
                self.state["queries"].clear()
                self.state["reads"].clear()
                self.state["sessions"].clear()
                result = self.backend.snapshot(card_number=1, numid=numid)
                self.assertEqual(result["status"], "found")
                controls = result["cards"][0]["controls"]
                self.assertEqual(len(controls), 1)
                self.assertEqual(controls[0]["name"], "Analogue 5 Volume")
                self.assertEqual((controls[0]["numid"], controls[0]["index"],
                                  controls[0]["unit"], controls[0]["selector"],
                                  controls[0]["count"]),
                                 (numid, index, unit, selector, count))
                self.assertFalse(controls[0]["adjustable"])
                self.assertEqual(self.state["queries"], [numid])
                self.assertEqual(self.state["reads"], [numid])
                self.assertEqual(self.state["sessions"], [(1, True)])

    def test_unmapped_same_names_and_clock_numids_refuse_before_value_queries(self):
        # Retain one observed record, testing partial exposure rather than
        # inventing associations for any of its 47 identically named neighbors.
        record = re.search(
            r'  Unit: 60\n    Control: name="Analogue 5 Volume", index=23\n    Info:.*\n',
            self.metadata).group(0)
        (self.card / "usbmixer").write_text(
            self.metadata.splitlines()[0] + "\n" + record, encoding="ascii")
        for numid in (3, 25, 27, 50, 51, 52, 53, 54):
            with self.subTest(numid=numid):
                result = self.backend.snapshot(card_number=1, numid=numid)
                self.assertEqual(result["status"], "partial")
                self.assertEqual(result["cards"][0]["controls"], [])
                self.assertEqual(len(result["errors"]), 1)
                self.assertEqual(result["errors"][0]["errno"], errno.EOPNOTSUPP)
                self.assertEqual(self.state["queries"], [])
                self.assertEqual(self.state["reads"], [])
                self.assertEqual(self.state["open"], 0)

    def test_observed_fu_numids_read_individually_with_reported_associations(self):
        for numid in (1, 2):
            with self.subTest(numid=numid):
                self.state["queries"].clear()
                self.state["reads"].clear()
                result = self.backend.snapshot(card_number=1, numid=numid)
                self.assertEqual(result["status"], "found")
                controls = result["cards"][0]["controls"]
                self.assertEqual(len(controls), 1)
                self.assertEqual(controls[0]["numid"], numid)
                self.assertEqual(controls[0]["channel_numbers"], list(range(1, 17)))
                self.assertEqual(self.state["queries"], [numid])
                self.assertEqual(self.state["reads"], [numid])
                self.assertEqual(self.state["open"], 0)

    def test_complete_observed_mapping_joins_all_50_numids_without_guessing(self):
        mappings = parse_usbmixer(self.metadata)
        self.assertEqual(len(mappings), 50)
        elements = self.state["elements"]
        expected = [(1, 11, 11, 0), (2, 11, 13, 0)]
        expected += [(selector + 2, 60, selector, selector - 1)
                     for selector in range(1, 25)]
        expected += [(selector + 26, 61, selector, selector + 23)
                     for selector in range(1, 25)]
        self.assertEqual([
            (element.numid, mappings[(element.name, element.index)].unit,
             mappings[(element.name, element.index)].selector, element.index)
            for element in elements if (element.name, element.index) in mappings],
            expected)
        # The older numeric capture is preserved byte for byte after removing
        # newly supplied Control lines; no original record was replaced.
        self.assertEqual("\n".join(line for line in self.metadata.splitlines()
                                   if not line.lstrip().startswith("Control:")) + "\n",
                         FIXTURE.read_text(encoding="ascii"))

    def test_observed_binary_gain_range_remains_readable_but_not_adjustable(self):
        info, values = observed_input_gain()
        self.assertEqual((info["count"], info["minimum"], info["maximum"], info["step"]),
                         (16, 0, 1, 0))
        self.assertEqual(values, [0] * 16)
        result = self.backend.snapshot(card_number=1, numid=1)
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["errors"], [])
        control = result["cards"][0]["controls"][0]
        self.assertEqual(control["values"], [0] * 16)
        self.assertTrue(control["readable"])
        self.assertTrue(control["writable"])
        self.assertFalse(control["adjustable"])
        self.assertEqual(control["adjustment_block_reason"], "gain_range_not_validated")
        self.assertEqual(self.state["reads"], [1])
        self.assertEqual(self.state["sessions"], [(1, True)])
        self.assertEqual(self.state["open"], 0)

    def test_observed_binary_gain_preview_refuses_without_lock_or_write(self):
        with self.assertRaises(PermissionError) as raised:
            self.backend.plan_value(1, 1, 0, 1)
        self.assertEqual(raised.exception.errno, errno.EPERM)
        self.assertEqual(self.state["queries"], [1])
        self.assertEqual(self.state["reads"], [1])
        self.assertEqual(self.state["sessions"], [(1, True)])
        self.assertEqual(self.state["open"], 0)
        self.assertEqual(self.state["values"][1], [0] * 16)

    def test_observed_phase_off_values_normalize_to_16_zeros_in_isolated_read(self):
        info, values = observed_phase_inverter()
        self.assertEqual(info["value_type"], "boolean")
        self.assertEqual(info["count"], 16)
        self.assertEqual(values, [0] * 16)
        # These limits are NativeCtl BOOLEAN normalization, not cget fields.
        self.assertEqual((info["minimum"], info["maximum"], info["step"]), (0, 1, 1))
        self.assertNotIn("min=", PHASE_FIXTURE.read_text(encoding="ascii"))
        result = self.backend.snapshot(card_number=1, numid=2)
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["errors"], [])
        controls = result["cards"][0]["controls"]
        self.assertEqual(len(controls), 1)
        control = controls[0]
        self.assertEqual((control["numid"], control["unit"], control["selector"]),
                         (2, 11, 13))
        self.assertEqual(control["value_type"], "boolean")
        self.assertEqual(control["count"], 16)
        self.assertEqual(control["values"], [0] * 16)
        self.assertEqual(self.state["queries"], [2])
        self.assertEqual(self.state["reads"], [2])
        self.assertEqual(self.state["sessions"], [(1, True)])
        self.assertEqual(self.state["open"], 0)
        self.assertEqual(self.state["values"][2], [0] * 16)


if __name__ == "__main__":
    unittest.main()
