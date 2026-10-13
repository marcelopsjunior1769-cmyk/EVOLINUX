# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 EVOLINUX contributors
"""Bounded first-use checks without opening an ALSA or USB device by default.

The report describes software prerequisites, not verified audio continuity.
Only ``include_controls=True`` opens ALSA CTL through the read-only backend.
No check changes a service, a control value, USB ownership or firmware.
"""

import ctypes
import errno
import importlib.util
import os
import platform
from pathlib import Path
import re
import shlex
import subprocess
import sys

from .alsa import MAX_METADATA_BYTES, NativeAlsaBackend, USB_ID, parse_usbmixer


MAX_CARDS = 4096
MAX_OS_RELEASE_BYTES = 16384
SERVICE_TIMEOUT_SECONDS = 2


def _error(operation, exception, *, card_number=None):
    code = getattr(exception, "errno", None)
    kind = "timeout" if isinstance(exception, subprocess.TimeoutExpired) else "error"
    result = {"operation": operation, "errno": code, "kind": kind,
              "message": os.strerror(code) if code else {
                  "python_version": "Não foi possível verificar a versão do Python",
                  "native_library": "Não foi possível carregar libasound.so.2",
                  "distribution": "Não foi possível ler os dados da distribuição",
                  "usb_identity": "Os dados de identificação USB são inválidos",
                  "mixer_metadata": "Não foi possível interpretar os controles conhecidos do mixer",
                  "discovery": "Não foi possível ler os dados da placa ALSA",
                  "control_read": "Não foi possível concluir a leitura dos controles ALSA",
                  "gui": "Não foi possível verificar os recursos gráficos opcionais",
              }.get(operation, "Não foi possível verificar o estado do serviço")}
    if card_number is not None:
        result["card_number"] = card_number
    return result


def _read_bounded(path, limit, encoding):
    with Path(path).open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise OSError(errno.EOVERFLOW, "metadata exceeds its size limit")
    return data.decode(encoding, errors="strict")


def _distribution(path):
    data = _read_bounded(path, MAX_OS_RELEASE_BYTES, "utf-8")
    result = {"id": None, "version_id": None, "target": False}
    for line in data.splitlines():
        key, separator, value = line.partition("=")
        if separator and key in ("ID", "VERSION_ID"):
            pieces = shlex.split(value, comments=True, posix=True)
            if len(pieces) != 1 or not re.fullmatch(r"[a-zA-Z0-9._-]{1,64}", pieces[0]):
                raise ValueError("invalid distribution value")
            result[{"ID": "id", "VERSION_ID": "version_id"}[key]] = pieces[0]
    result["target"] = result["id"] == "ubuntu" and result["version_id"] == "24.04"
    return result


def _card_metadata(asound_root, errors):
    result = {"status": "unavailable", "cards": []}
    try:
        entries = []
        for entry in Path(asound_root).iterdir():
            if len(entries) >= MAX_CARDS:
                raise OSError(errno.EOVERFLOW, "too many ALSA directory entries")
            entries.append(entry)
    except OSError as exception:
        errors.append(_error("discovery", exception))
        return result
    for directory in sorted(entries, key=lambda item: item.name):
        match = re.fullmatch(r"card(\d{1,4})", directory.name)
        if not match or int(match[1]) >= MAX_CARDS:
            continue
        number = int(match[1])
        try:
            identity = _read_bounded(directory / "usbid", 64, "ascii").strip().lower()
        except FileNotFoundError:
            # Non-USB ALSA cards have no usbid file.
            continue
        except (OSError, UnicodeError) as exception:
            errors.append(_error("usb_identity", exception, card_number=number))
            continue
        if identity != USB_ID:
            continue
        card = {"card_number": number, "usb_id": USB_ID,
                "metadata_status": "unavailable", "mappings": []}
        result["cards"].append(card)
        try:
            data = _read_bounded(directory / "usbmixer", MAX_METADATA_BYTES, "utf-8")
            mappings = {key: item for key, item in parse_usbmixer(data).items()
                        if _supported_mapping(item)}
            if not mappings:
                raise ValueError("no supported mixer records")
            if len(mappings) > 4096:
                raise OSError(errno.EOVERFLOW, "too many supported mixer records")
            # Names and identifying card headers are deliberately not exported.
            card["mappings"] = [{"unit": mapping.unit,
                                 "selector": mapping.selector,
                                 "channel_mask": mapping.channel_mask,
                                 "channels": mapping.channels,
                                 "usb_type": mapping.usb_type}
                                for mapping in mappings.values()]
            card["metadata_status"] = "found"
        except (OSError, ValueError, UnicodeError) as exception:
            errors.append(_error("mixer_metadata", exception, card_number=number))
    result["status"] = ("partial" if errors else "found") if result["cards"] else (
        "unavailable" if errors else "absent")
    return result


def _supported_mapping(mapping):
    if mapping.unit == 11:
        return (0 < mapping.channel_mask <= 0xffffff
                and len(mapping.channel_numbers()) == mapping.channels
                and ((mapping.selector == 11 and mapping.usb_type == "S16")
                     or (mapping.selector == 13 and mapping.usb_type == "BOOLEAN")))
    outputs = {60: 6, 61: 4}.get(mapping.unit)
    return (outputs is not None and 1 <= mapping.selector <= 34
            and 0 < mapping.channel_mask < (1 << outputs)
            and mapping.channel_mask.bit_count() == mapping.channels
            and mapping.usb_type == "S16")


def _service_state(service, runner):
    result = {"state": "unavailable", "returncode": None}
    try:
        completed = runner(
            ["systemctl", "--user", "--no-pager", "is-active", service + ".service"],
            capture_output=True, text=True, timeout=SERVICE_TIMEOUT_SECONDS, check=False)
        state = completed.stdout.strip()
        result["returncode"] = completed.returncode
        if state in ("active", "inactive", "failed", "activating", "deactivating", "unknown"):
            result["state"] = state
        # stderr may contain usernames, socket paths or host names. Never export it.
    except (OSError, subprocess.TimeoutExpired) as exception:
        result["error"] = _error(service, exception)
    return result


def _private_snapshot(snapshot):
    """Retain diagnostic values and errno, excluding arbitrary identifying text."""
    result = {"status": snapshot.get("status", "unavailable"), "cards": [], "errors": []}
    control_keys = ("id", "numid", "index", "unit", "selector", "channel_mask",
                    "channel_numbers", "count", "value_type", "values", "minimum",
                    "maximum", "step", "readable", "writable", "active", "locked",
                    "owner", "adjustable")
    for card in snapshot.get("cards", [])[:MAX_CARDS]:
        result["cards"].append({
            "card_number": card["card_number"],
            "controls": [{key: control[key] for key in control_keys if key in control}
                         for control in card.get("controls", [])[:4096]]})
    for item in snapshot.get("errors", [])[:4096]:
        code = item.get("errno")
        clean = {"errno": code, "message": os.strerror(code) if code else
                 "A leitura ALSA informou um erro de controle ou metadados"}
        for key in ("card_number", "numid"):
            if key in item:
                clean[key] = item[key]
        if item.get("operation") in ("discovery", "usb_identity", "native_library",
                                     "control_read", "card_read"):
            clean["operation"] = item["operation"]
        result["errors"].append(clean)
    return result


def check_environment(include_controls=False, *, asound_root=Path("/proc/asound"),
                      os_release_path=Path("/etc/os-release"), python_version=None,
                      library_loader=None, service_runner=None, backend_factory=None,
                      environment=None, module_finder=None, kernel_release=None):
    """Return a JSON-compatible first-use report with no identifying card text.

    Dependencies and paths can be injected to test every branch without hardware
    or a user's service manager. Library loading performs no ALSA control calls.
    Services are inspected with a two-second timeout each; none are restarted.
    """
    if type(include_controls) is not bool:
        raise ValueError("include_controls must be a boolean")
    errors = []
    warnings = []
    version = tuple((sys.version_info if python_version is None else python_version)[:3])
    if len(version) != 3 or any(type(item) is not int or item < 0 for item in version):
        raise ValueError("python_version must contain three nonnegative integers")
    python_ok = version >= (3, 10, 0)
    report = {"status": "warnings", "software_prerequisites": "missing",
              "physical_audio_validated": False,
              "python": {"version": ".".join(str(item) for item in version),
                         "supported": python_ok},
              "kernel": platform.release() if kernel_release is None else kernel_release,
              "libasound": {"available": False},
              "ubuntu": {"id": None, "version_id": None, "target": False},
              "alsa": None, "services": {}, "gui": {}, "warnings": warnings,
              "errors": errors}
    if (not isinstance(report["kernel"], str)
            or not re.fullmatch(r"[A-Za-z0-9_.+\-]{1,128}", report["kernel"])):
        report["kernel"] = None
        warnings.append("Não foi possível confirmar a versão do kernel")
    if not python_ok:
        errors.append({"operation": "python_version", "errno": None, "kind": "error",
                       "message": "É necessário Python 3.10 ou superior"})
    try:
        (library_loader or ctypes.CDLL)("libasound.so.2", use_errno=True)
        report["libasound"]["available"] = True
    except (OSError, AttributeError) as exception:
        errors.append(_error("native_library", exception))
    try:
        report["ubuntu"] = _distribution(os_release_path)
        if not report["ubuntu"]["target"]:
            warnings.append("A distribuição difere do Ubuntu 24.04 de destino")
    except (OSError, ValueError, UnicodeError) as exception:
        errors.append(_error("distribution", exception))
        warnings.append("Não foi possível confirmar a versão do Ubuntu")
    metadata_errors = []
    report["alsa"] = _card_metadata(asound_root, metadata_errors)
    errors.extend(metadata_errors)
    if report["alsa"]["status"] != "found":
        warnings.append("Os dados da EVO 16 estão ausentes ou incompletos")
    runner = service_runner or subprocess.run
    for service in ("pipewire", "wireplumber"):
        report["services"][service] = _service_state(service, runner)
        if report["services"][service]["state"] != "active":
            warnings.append(service + " não foi confirmado como ativo; o ALSA ainda pode ser usado")
    env = os.environ if environment is None else environment
    try:
        tkinter_available = (module_finder or importlib.util.find_spec)("tkinter") is not None
    except (ImportError, ValueError, AttributeError) as exception:
        errors.append(_error("gui", exception))
        tkinter_available = False
    report["gui"] = {"tkinter_available": tkinter_available,
                     "display_available": bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")),
                     "required_for_cli": False}
    if include_controls:
        try:
            factory = backend_factory or NativeAlsaBackend
            report["controls"] = _private_snapshot(factory(asound_root=asound_root).snapshot())
            if report["controls"]["status"] != "found" or report["controls"]["errors"]:
                warnings.append("A leitura dos controles ALSA está incompleta")
        except (OSError, ValueError, UnicodeError, AttributeError) as exception:
            errors.append(_error("control_read", exception))
            report["controls"] = {"status": "unavailable", "cards": [], "errors": []}
            warnings.append("Não foi possível concluir a leitura dos controles ALSA")
    prerequisites = python_ok and report["libasound"]["available"]
    report["software_prerequisites"] = "ready" if prerequisites else "missing"
    report["status"] = "failed" if not prerequisites else (
        "warnings" if warnings or errors else "ready")
    return report
