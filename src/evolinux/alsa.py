# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 EVOLINUX contributors
"""Native ALSA CTL access for the EVO 16, without opening a PCM device.

Only controls identified by the kernel's usbmixer metadata are read. Writes
require explicit authorization and are limited to the known FU11 controls.
ALSA integer values are normalized control values, not USB values or decibels.
"""

from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
import errno
import os
from pathlib import Path
import re


USB_ID = "2708:000a"
MAX_ELEMENTS = 4096
MAX_VALUES = 128
MAX_METADATA_BYTES = 2 * 1024 * 1024
SND_CTL_READONLY = 4
TYPE_NAMES = {1: "boolean", 2: "integer", 3: "enumerated", 4: "bytes",
              5: "iec958", 6: "integer64"}


@dataclass(frozen=True)
class Element:
    """Full ALSA identity; numid alone is insufficient during hotplug."""

    numid: int
    name: str
    index: int = 0
    interface: int = 2
    device: int = 0
    subdevice: int = 0


@dataclass(frozen=True)
class MixerMapping:
    name: str
    index: int
    unit: int
    selector: int
    channel_mask: int
    channels: int
    usb_type: str

    def channel_numbers(self):
        numbers = [i + 1 for i in range(24)
                   if self.channel_mask & (1 << i)]
        # Current snd-usb-audio limits feature values to the first 16 channels.
        # Preserve the original mask and expose only the reported effective set.
        if self.unit == 11 and len(numbers) != self.channels:
            numbers = [number for number in numbers if number <= 16]
        return numbers


def parse_usbmixer(data):
    """Parse only kernel Unit/Control/Info records, never card identification."""
    unit = None
    control = None
    correct_interface = False
    mappings = {}
    for line in data.splitlines():
        match = re.fullmatch(
            r"USB Mixer: usb_id=0x([0-9a-fA-F]{8}), ctrlif=(\d+), ctlerr=(\d+)\s*", line)
        if match:
            if int(match[1], 16) != 0x2708000a:
                raise ValueError("kernel mixer USB identity is inconsistent")
            if int(match[3]) != 0:
                raise ValueError("kernel mixer suppresses control errors")
            correct_interface = int(match[2]) == 0
            unit, control = None, None
            continue
        match = re.fullmatch(r"\s*Unit: (\d+)\s*", line)
        if match:
            unit, control = int(match[1]), None
            continue
        match = re.fullmatch(r'\s*Control: name="(.*)", index=(\d+)\s*', line)
        if match:
            control = (match[1], int(match[2]))
            continue
        match = re.fullmatch(
            r'\s*Info: id=(\d+), control=(\d+), cmask=0x([0-9a-fA-F]+), '
            r'channels=(\d+), type="([A-Z0-9_]+)"\s*', line)
        if match and correct_interface and unit in (11, 60, 61) and control is not None:
            if int(match[1]) != unit:
                raise ValueError("kernel mixer unit identity is inconsistent")
            mapping = MixerMapping(*control, unit, int(match[2]),
                                   int(match[3], 16), int(match[4]), match[5])
            if control in mappings:
                raise ValueError("kernel mixer control mapping is ambiguous")
            if not 1 <= mapping.channels <= MAX_VALUES:
                raise ValueError("kernel mixer channel count is invalid")
            mappings[control] = mapping
            control = None
    return mappings


def _checked(result, operation):
    if result < 0:
        code = -result
        raise OSError(code, os.strerror(code), operation)
    return result


def _bind_library(library):
    """Declare all ctypes signatures before any call into libasound."""
    pointer = ctypes.c_void_p
    integer = ctypes.c_int
    unsigned = ctypes.c_uint
    definitions = {
        "snd_ctl_open": (integer, [ctypes.POINTER(pointer), ctypes.c_char_p, integer]),
        "snd_ctl_close": (integer, [pointer]),
        "snd_ctl_elem_list": (integer, [pointer, pointer]),
        "snd_ctl_elem_list_get_count": (unsigned, [pointer]),
        "snd_ctl_elem_list_get_used": (unsigned, [pointer]),
        "snd_ctl_elem_list_alloc_space": (integer, [pointer, unsigned]),
        "snd_ctl_elem_list_free_space": (None, [pointer]),
        "snd_ctl_elem_list_get_id": (None, [pointer, unsigned, pointer]),
        "snd_ctl_elem_info": (integer, [pointer, pointer]),
        "snd_ctl_elem_info_set_id": (None, [pointer, pointer]),
        "snd_ctl_elem_info_get_id": (None, [pointer, pointer]),
        "snd_ctl_elem_info_get_type": (integer, [pointer]),
        "snd_ctl_elem_info_get_count": (unsigned, [pointer]),
        "snd_ctl_elem_info_is_readable": (integer, [pointer]),
        "snd_ctl_elem_info_is_writable": (integer, [pointer]),
        "snd_ctl_elem_info_is_inactive": (integer, [pointer]),
        "snd_ctl_elem_info_is_locked": (integer, [pointer]),
        "snd_ctl_elem_info_is_owner": (integer, [pointer]),
        "snd_ctl_elem_lock": (integer, [pointer, pointer]),
        "snd_ctl_elem_unlock": (integer, [pointer, pointer]),
        "snd_ctl_elem_read": (integer, [pointer, pointer]),
        "snd_ctl_elem_write": (integer, [pointer, pointer]),
        "snd_ctl_elem_value_set_id": (None, [pointer, pointer]),
        "snd_ctl_elem_value_get_id": (None, [pointer, pointer]),
    }
    for kind in ("list", "id", "info", "value"):
        definitions[f"snd_ctl_elem_{kind}_malloc"] = (
            integer, [ctypes.POINTER(pointer)])
        definitions[f"snd_ctl_elem_{kind}_free"] = (None, [pointer])
    for field in ("numid", "index", "device", "subdevice"):
        definitions[f"snd_ctl_elem_id_get_{field}"] = (unsigned, [pointer])
        definitions[f"snd_ctl_elem_id_set_{field}"] = (None, [pointer, unsigned])
    definitions["snd_ctl_elem_id_get_interface"] = (integer, [pointer])
    definitions["snd_ctl_elem_id_set_interface"] = (None, [pointer, integer])
    definitions["snd_ctl_elem_id_get_name"] = (ctypes.c_char_p, [pointer])
    definitions["snd_ctl_elem_id_set_name"] = (None, [pointer, ctypes.c_char_p])
    for kind, native in (("integer", ctypes.c_long),
                         ("integer64", ctypes.c_longlong)):
        for field in ("min", "max", "step"):
            definitions[f"snd_ctl_elem_info_get_{field}" +
                        ("64" if kind == "integer64" else "")] = (native, [pointer])
        definitions[f"snd_ctl_elem_value_get_{kind}"] = (native, [pointer, unsigned])
        definitions[f"snd_ctl_elem_value_set_{kind}"] = (None, [pointer, unsigned, native])
    definitions["snd_ctl_elem_value_get_boolean"] = (ctypes.c_long, [pointer, unsigned])
    definitions["snd_ctl_elem_value_set_boolean"] = (None, [pointer, unsigned, ctypes.c_long])
    for name, (result, arguments) in definitions.items():
        function = getattr(library, name)
        function.restype, function.argtypes = result, arguments
    return library


class NativeCtl:
    """A short-lived ALSA CTL session, read-only unless explicitly requested."""

    def __init__(self, card_number, *, library=None, readonly=True):
        if type(card_number) is not int or not 0 <= card_number <= 4095:
            raise ValueError("invalid ALSA card number")
        self.library = _bind_library(
            library if library is not None else
            ctypes.CDLL("libasound.so.2", use_errno=True))
        self.card_number, self.readonly = card_number, readonly
        self.handle = ctypes.c_void_p()

    def __enter__(self):
        if self.handle.value:
            raise OSError(errno.EBUSY, "ALSA session is already open")
        result = self.library.snd_ctl_open(
            ctypes.byref(self.handle), f"hw:{self.card_number}".encode("ascii"),
            SND_CTL_READONLY if self.readonly else 0)
        if result < 0:
            if self.handle.value:
                self.library.snd_ctl_close(self.handle)
                self.handle = ctypes.c_void_p()
            _checked(result, "snd_ctl_open")
        if not self.handle.value:
            raise OSError(errno.EIO, "ALSA returned an empty control handle")
        return self

    def __exit__(self, kind, value, traceback):
        if self.handle.value:
            handle, self.handle = self.handle, ctypes.c_void_p()
            result = self.library.snd_ctl_close(handle)
            if kind is None:
                _checked(result, "snd_ctl_close")

    @contextmanager
    def _allocated(self, kind):
        pointer = ctypes.c_void_p()
        prefix = f"snd_ctl_elem_{kind}"
        try:
            _checked(getattr(self.library, prefix + "_malloc")(
                ctypes.byref(pointer)), prefix + "_malloc")
            if not pointer.value:
                raise OSError(errno.ENOMEM, "ALSA returned an empty allocation")
            yield pointer
        finally:
            if pointer.value:
                getattr(self.library, prefix + "_free")(pointer)

    def _require_open(self):
        if not self.handle.value:
            raise OSError(errno.EBADF, "ALSA session is not open")

    def _get_id(self, pointer):
        lib = self.library
        raw_name = lib.snd_ctl_elem_id_get_name(pointer)
        if raw_name is None:
            raise OSError(errno.EIO, "ALSA returned an empty control identity")
        return Element(lib.snd_ctl_elem_id_get_numid(pointer),
                       raw_name.decode("utf-8", errors="strict"),
                       lib.snd_ctl_elem_id_get_index(pointer),
                       lib.snd_ctl_elem_id_get_interface(pointer),
                       lib.snd_ctl_elem_id_get_device(pointer),
                       lib.snd_ctl_elem_id_get_subdevice(pointer))

    def _set_id(self, pointer, element):
        for field in ("numid", "index", "interface", "device", "subdevice"):
            getattr(self.library, f"snd_ctl_elem_id_set_{field}")(
                pointer, 0 if field == "numid" else getattr(element, field))
        self.library.snd_ctl_elem_id_set_name(pointer, element.name.encode("utf-8"))

    def list_elements(self):
        self._require_open()
        with self._allocated("list") as listing, self._allocated("id") as identity:
            _checked(self.library.snd_ctl_elem_list(self.handle, listing),
                     "snd_ctl_elem_list")
            count = self.library.snd_ctl_elem_list_get_count(listing)
            if not 0 <= count <= MAX_ELEMENTS:
                raise OSError(errno.EOVERFLOW, "too many ALSA control elements")
            if count == 0:
                return []
            try:
                _checked(self.library.snd_ctl_elem_list_alloc_space(listing, count),
                         "snd_ctl_elem_list_alloc_space")
                _checked(self.library.snd_ctl_elem_list(self.handle, listing),
                         "snd_ctl_elem_list")
                current = self.library.snd_ctl_elem_list_get_count(listing)
                used = self.library.snd_ctl_elem_list_get_used(listing)
                if current != count or used != count:
                    raise OSError(errno.EAGAIN, "ALSA control list changed during enumeration")
                elements = []
                for position in range(used):
                    self.library.snd_ctl_elem_list_get_id(listing, position, identity)
                    elements.append(self._get_id(identity))
                return elements
            finally:
                self.library.snd_ctl_elem_list_free_space(listing)

    def info(self, element):
        self._require_open()
        with self._allocated("id") as identity, self._allocated("info") as info:
            self._set_id(identity, element)
            self.library.snd_ctl_elem_info_set_id(info, identity)
            _checked(self.library.snd_ctl_elem_info(self.handle, info), "snd_ctl_elem_info")
            self.library.snd_ctl_elem_info_get_id(info, identity)
            if self._get_id(identity) != element:
                raise OSError(errno.EAGAIN, "ALSA control identity changed")
            count = self.library.snd_ctl_elem_info_get_count(info)
            if not 1 <= count <= MAX_VALUES:
                raise OSError(errno.EOVERFLOW, "invalid ALSA value count")
            value_type = TYPE_NAMES.get(self.library.snd_ctl_elem_info_get_type(info), "unknown")
            if value_type == "integer64" and count > 64:
                raise OSError(errno.EOVERFLOW, "invalid ALSA integer64 value count")
            minimum = maximum = step = None
            if value_type == "boolean":
                minimum, maximum, step = 0, 1, 1
            elif value_type in ("integer", "integer64"):
                suffix = "64" if value_type == "integer64" else ""
                minimum, maximum, step = (
                    getattr(self.library, f"snd_ctl_elem_info_get_{field}{suffix}")(info)
                    for field in ("min", "max", "step"))
            return {"count": count, "value_type": value_type,
                    "minimum": minimum, "maximum": maximum, "step": step,
                    "readable": bool(self.library.snd_ctl_elem_info_is_readable(info)),
                    "writable": bool(self.library.snd_ctl_elem_info_is_writable(info)),
                    "active": not bool(self.library.snd_ctl_elem_info_is_inactive(info)),
                    "locked": bool(self.library.snd_ctl_elem_info_is_locked(info)),
                    "owner": bool(self.library.snd_ctl_elem_info_is_owner(info))}

    def _validate_info(self, info):
        if type(info.get("count")) is not int or not 1 <= info["count"] <= MAX_VALUES:
            raise OSError(errno.EOVERFLOW, "invalid ALSA value count")
        if info.get("value_type") not in ("boolean", "integer", "integer64"):
            raise OSError(errno.ENOTSUP, "unsupported ALSA value type")
        if info["value_type"] == "integer64" and info["count"] > 64:
            raise OSError(errno.EOVERFLOW, "invalid ALSA integer64 value count")

    @contextmanager
    def lock(self, element):
        """Own one control while updating; other ALSA writers must wait."""
        self._require_open()
        if self.readonly:
            raise PermissionError(errno.EPERM, "ALSA session is read-only")
        with self._allocated("id") as identity:
            self._set_id(identity, element)
            _checked(self.library.snd_ctl_elem_lock(self.handle, identity), "snd_ctl_elem_lock")
            try:
                yield
            except BaseException:
                # Keep the original read/write errno when hotplug also breaks unlock.
                self.library.snd_ctl_elem_unlock(self.handle, identity)
                raise
            else:
                # Closing the CTL handle also releases locks if hotplug prevents unlock.
                _checked(self.library.snd_ctl_elem_unlock(self.handle, identity), "snd_ctl_elem_unlock")

    def read(self, element, info):
        self._require_open()
        self._validate_info(info)
        if not info["readable"]:
            raise OSError(errno.EACCES, "ALSA control is not readable")
        with self._allocated("id") as identity, self._allocated("value") as value:
            self._set_id(identity, element)
            self.library.snd_ctl_elem_value_set_id(value, identity)
            _checked(self.library.snd_ctl_elem_read(self.handle, value), "snd_ctl_elem_read")
            self.library.snd_ctl_elem_value_get_id(value, identity)
            if self._get_id(identity) != element:
                raise OSError(errno.EAGAIN, "ALSA control identity changed")
            getter = getattr(self.library, "snd_ctl_elem_value_get_" + info["value_type"])
            return [getter(value, index) for index in range(info["count"])]

    def write(self, element, info, values):
        """Write the whole value array; callers must authorize and validate it."""
        self._require_open()
        self._validate_info(info)
        if self.readonly or not info["writable"]:
            raise PermissionError(errno.EPERM, "ALSA session is read-only")
        if len(values) != info["count"]:
            raise ValueError("value count changed")
        if not _valid_values(info, values):
            raise ValueError("value is outside the ALSA range or step")
        if self.info(element) != info:
            raise OSError(errno.EAGAIN, "ALSA control metadata changed")
        with self._allocated("id") as identity, self._allocated("value") as value:
            self._set_id(identity, element)
            self.library.snd_ctl_elem_value_set_id(value, identity)
            setter = getattr(self.library, "snd_ctl_elem_value_set_" + info["value_type"])
            for index, item in enumerate(values):
                setter(value, index, item)
            return _checked(self.library.snd_ctl_elem_write(self.handle, value),
                            "snd_ctl_elem_write")


def _consistent(mapping, info):
    if info["count"] != mapping.channels or len(mapping.channel_numbers()) != mapping.channels:
        return False
    if mapping.unit == 11:
        return (mapping.channel_mask != 0 and mapping.channel_mask <= 0xffffff
                and mapping.selector in (11, 13)
                and ((mapping.selector == 11 and mapping.usb_type == "S16"
                      and info["value_type"] == "integer")
                     or (mapping.selector == 13 and mapping.usb_type == "BOOLEAN"
                         and info["value_type"] == "boolean")))
    outputs = {60: 6, 61: 4}.get(mapping.unit)
    return (outputs is not None and 1 <= mapping.selector <= 34
            and 0 < mapping.channel_mask < (1 << outputs)
            and mapping.usb_type == "S16" and info["value_type"] == "integer")


def _valid_range(info):
    low, high, step = (info[key] for key in ("minimum", "maximum", "step"))
    if any(type(item) is not int for item in (low, high, step)):
        return False
    # ALSA integer step=0 means variable step; all integer positions are allowed.
    return low < high and 0 <= step <= high - low


def _valid_values(info, values):
    return (isinstance(values, list) and len(values) == info["count"]
            and _valid_range(info)
            and all(type(value) is int and info["minimum"] <= value <= info["maximum"]
                    and (value - info["minimum"]) % max(1, info["step"]) == 0
                    for value in values))


def _adjustable(mapping, info, values):
    if not (mapping.unit == 11 and _consistent(mapping, info)
            and info["readable"] and info["writable"]
            and info.get("active", False)
            and (not info.get("locked", True) or info.get("owner", False))
            and _valid_values(info, values)):
        return False
    if mapping.selector == 13:
        return (info["minimum"], info["maximum"], info["step"]) == (0, 1, 1)
    return 0 <= info["minimum"] < info["maximum"] <= 65535


def _error(operation, exception, *, card_number=None, numid=None):
    code = getattr(exception, "errno", None)
    result = {"operation": operation, "errno": code,
              "message": os.strerror(code) if code else (
                  "kernel metadata encoding is invalid" if isinstance(exception, UnicodeError)
                  else str(exception))}
    if card_number is not None:
        result["card_number"] = card_number
    if numid is not None:
        result["numid"] = numid
    return result


class NativeAlsaBackend:
    """Discover EVO 16 cards and inspect standard controls without PCM access."""

    def __init__(self, asound_root=Path("/proc/asound"), *, library=None, ctl_factory=None):
        self.asound_root = Path(asound_root)
        self.library = library
        self.ctl_factory = ctl_factory or NativeCtl

    def _ctl(self, card_number, *, readonly=True):
        return self.ctl_factory(card_number, library=self.library, readonly=readonly)

    def _usb_id(self, card_number):
        return (self.asound_root / f"card{card_number}" / "usbid").read_text(
            encoding="ascii").strip().lower()

    def _mappings(self, card_number):
        with (self.asound_root / f"card{card_number}" / "usbmixer").open("rb") as stream:
            data = stream.read(MAX_METADATA_BYTES + 1)
        if len(data) > MAX_METADATA_BYTES:
            raise OSError(errno.EOVERFLOW, "kernel mixer metadata is too large")
        mappings = parse_usbmixer(data.decode("utf-8", errors="strict"))
        if not mappings:
            raise ValueError("no supported kernel mixer mappings were found")
        return mappings

    def snapshot(self, *, card_number=None, numid=None):
        """Read all mapped controls, or limit native I/O to one card/control."""
        if card_number is not None and (type(card_number) is not int or not 0 <= card_number <= 4095):
            raise ValueError("invalid ALSA card number")
        if numid is not None and (card_number is None or type(numid) is not int or not 1 <= numid <= 0xffffffff):
            raise ValueError("a control numid requires a valid card number")
        result = {"status": "unavailable", "cards": [], "errors": []}
        try:
            directories = sorted(self.asound_root.iterdir(), key=lambda item: item.name)
        except OSError as exception:
            result["errors"].append(_error("discovery", exception))
            return result
        candidates = []
        for directory in directories:
            match = re.fullmatch(r"card(\d+)", directory.name)
            if not match:
                continue
            number = int(match[1])
            if card_number is not None and number != card_number:
                continue
            try:
                if self._usb_id(number) == USB_ID:
                    candidates.append(number)
            except FileNotFoundError:
                # Non-USB ALSA cards normally have no usbid file.
                continue
            except (OSError, UnicodeError) as exception:
                result["errors"].append(_error("usb_identity", exception, card_number=number))
        if not candidates:
            result["status"] = "unavailable" if result["errors"] else "absent"
            return result
        if self.ctl_factory is NativeCtl:
            try:
                self.library = _bind_library(
                    self.library if self.library is not None else
                    ctypes.CDLL("libasound.so.2", use_errno=True))
            except (OSError, AttributeError) as exception:
                result["cards"] = [{"card_number": number, "controls": []}
                                   for number in sorted(candidates)]
                result["errors"].append(_error("native_library", exception))
                return result
        for number in sorted(candidates):
            card = {"card_number": number, "controls": []}
            result["cards"].append(card)
            try:
                mappings = self._mappings(number)
                with self._ctl(number) as ctl:
                    if self._usb_id(number) != USB_ID or self._mappings(number) != mappings:
                        raise OSError(errno.EAGAIN, "EVO identity or mapping changed")
                    elements = ctl.list_elements()
                    expected = set(mappings)
                    if numid is not None:
                        elements = [element for element in elements if element.numid == numid]
                        if len(elements) != 1:
                            raise OSError(errno.ENOENT, "requested ALSA control is absent or ambiguous")
                        selected = elements[0]
                        if ((selected.name, selected.index) not in mappings
                                or selected.interface != 2 or selected.device or selected.subdevice):
                            raise OSError(errno.EOPNOTSUPP, "requested control has no supported EVO mapping")
                        expected = {(selected.name, selected.index)}
                    matched = set()
                    for element in elements:
                        key = (element.name, element.index)
                        if (key not in mappings or element.interface != 2
                                or element.device != 0 or element.subdevice != 0):
                            continue
                        if key in matched:
                            raise OSError(errno.EAGAIN, "ALSA control identity is ambiguous")
                        matched.add(key)
                        mapping = mappings[key]
                        control = {"id": element.numid, "numid": element.numid,
                                   "name": element.name, "index": element.index,
                                   "unit": mapping.unit, "selector": mapping.selector,
                                   "channel_mask": mapping.channel_mask,
                                   "channel_numbers": mapping.channel_numbers(),
                                   "count": None, "value_type": None, "values": None,
                                   "minimum": None, "maximum": None, "step": None,
                                   "readable": False, "writable": False,
                                   "active": False, "locked": False,
                                   "owner": False, "adjustable": False}
                        card["controls"].append(control)
                        try:
                            info = ctl.info(element)
                            control.update(info)
                            if not _consistent(mapping, info):
                                raise OSError(errno.EINVAL, "ALSA and kernel mixer metadata disagree")
                            values = ctl.read(element, info)
                            control["values"] = values
                            control["adjustable"] = _adjustable(mapping, info, values)
                        except (OSError, ValueError, UnicodeError) as exception:
                            result["errors"].append(_error("control_read", exception,
                                                           card_number=number, numid=element.numid))
                    if matched != expected:
                        raise OSError(errno.ENOENT, "mapped ALSA controls were not found")
                    if self._usb_id(number) != USB_ID or self._mappings(number) != mappings:
                        for control in card["controls"]:
                            control["adjustable"] = False
                        raise OSError(errno.EAGAIN, "EVO identity or mapping changed")
            except (OSError, ValueError, UnicodeError, AttributeError) as exception:
                result["errors"].append(_error("card_read", exception, card_number=number))
        result["status"] = "partial" if result["errors"] else "found"
        return result

    def set_value(self, card_number, numid, channel_index, value, *, authorized=False):
        """Change one FU11 array position only with explicit caller authorization."""
        if authorized is not True:
            raise PermissionError(errno.EPERM, "explicit authorization is required for ALSA writes")
        if any(type(item) is not int for item in (card_number, numid, channel_index, value)):
            raise ValueError("write arguments must be integers")
        if not (0 <= card_number <= 4095 and 1 <= numid <= 0xffffffff and channel_index >= 0):
            raise ValueError("invalid ALSA write address")
        if self._usb_id(card_number) != USB_ID:
            raise PermissionError(errno.ENODEV, "card is not an EVO 16")
        mappings = self._mappings(card_number)
        with self._ctl(card_number, readonly=False) as ctl:
            elements = [element for element in ctl.list_elements() if element.numid == numid]
            if len(elements) != 1:
                raise OSError(errno.EAGAIN, "ALSA control identity is missing or ambiguous")
            element = elements[0]
            mapping = mappings.get((element.name, element.index))
            if mapping is None or element.interface != 2 or element.device or element.subdevice:
                raise PermissionError(errno.EPERM, "control has no verified EVO mapping")
            if sum(item.name == element.name and item.index == element.index
                   and item.interface == element.interface and item.device == element.device
                   and item.subdevice == element.subdevice for item in ctl.list_elements()) != 1:
                raise OSError(errno.EAGAIN, "ALSA control identity is ambiguous")
            # Reject the unit/selector before even taking an ALSA control lock.
            if mapping.unit != 11 or mapping.selector not in (11, 13):
                raise PermissionError(errno.EPERM, "control is not a verified adjustable FU11 control")
            with ctl.lock(element):
                info = ctl.info(element)
                values = ctl.read(element, info)
                if not _adjustable(mapping, info, values):
                    raise PermissionError(errno.EPERM, "control is not a verified adjustable FU11 control")
                if channel_index >= info["count"]:
                    raise ValueError("channel index is outside the ALSA control")
                updated = values.copy()
                updated[channel_index] = value
                if not _valid_values(info, updated):
                    raise ValueError("value is outside the ALSA range or step")
                # Recheck immediately before write on the same locked CTL handle.
                if (self._usb_id(card_number) != USB_ID or self._mappings(card_number) != mappings
                        or ctl.info(element) != info
                        or [item for item in ctl.list_elements() if item.numid == numid] != [element]):
                    raise OSError(errno.EAGAIN, "EVO identity or control metadata changed")
                current = ctl.read(element, info)
                if not _valid_values(info, current):
                    raise OSError(errno.EAGAIN, "ALSA values changed to an invalid range")
                changed = current[channel_index] != value
                if changed:
                    current[channel_index] = value
                    ctl.write(element, info, current)
                    confirmed = ctl.read(element, info)
                    if confirmed != current:
                        raise OSError(errno.EIO, "ALSA readback did not confirm the requested values")
                    current = confirmed
                return {"changed": changed, "card_number": card_number,
                        "numid": numid, "values": current}
