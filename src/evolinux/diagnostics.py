#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 EVOLINUX contributors
"""Collect EVO 16 USB metadata from Linux sysfs without opening the USB device."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys


VENDOR_ID = "2708"
PRODUCT_ID = "000a"
DEFAULT_SYSFS_ROOT = Path("/sys/bus/usb/devices")
DEFAULT_ASOUND_ROOT = Path("/proc/asound")


def _error(errors, path, root, exc, kind=None):
    if kind is None:
        if isinstance(exc, PermissionError):
            kind = "permission_denied"
        elif isinstance(exc, FileNotFoundError):
            kind = "missing"
        else:
            kind = "read_error"
    try:
        relative = str(path.relative_to(root))
    except ValueError:
        relative = path.name
    errors.append({"path": relative, "kind": kind})


def _read_text(path, root, errors, missing_ok=False):
    try:
        return path.read_text(encoding="ascii").strip()
    except FileNotFoundError as exc:
        if not missing_ok:
            _error(errors, path, root, exc)
    except (OSError, UnicodeError) as exc:
        _error(errors, path, root, exc)
    return None


def _read_number(path, root, errors, base=10):
    raw = _read_text(path, root, errors)
    if raw is None or raw == "":
        return None
    try:
        return int(raw, base)
    except ValueError as exc:
        _error(errors, path, root, exc, "invalid_value")
        return None


def _driver_name(path, root, errors):
    try:
        return Path(os.readlink(path / "driver")).name
    except FileNotFoundError:
        return None  # An unbound interface has no driver symlink.
    except OSError as exc:
        _error(errors, path / "driver", root, exc)
        return None


def _device_revision(raw):
    """Format valid USB BCD values without assuming they equal a firmware version."""
    if raw is None or len(raw) != 4 or not raw.isdecimal():
        return None
    return "{}.{}".format(int(raw[:2]), raw[2:])


def _collect_device(path, entries, root, errors):
    device_errors = []
    revision = _read_text(path / "bcdDevice", root, device_errors)
    device = {
        "sysfs_name": path.name,
        "vendor_id": VENDOR_ID,
        "product_id": PRODUCT_ID,
        "bcd_device_hex": revision,
        "bcd_device_revision": _device_revision(revision),
        "bus_number": _read_number(path / "busnum", root, device_errors),
        "device_number": _read_number(path / "devnum", root, device_errors),
        "speed_mbps": _read_text(path / "speed", root, device_errors),
        "configuration_value": _read_number(
            path / "bConfigurationValue", root, device_errors
        ),
        "device_driver": _driver_name(path, root, device_errors),
        "descriptors": None,
        "interfaces": [],
    }
    try:
        descriptors = (path / "descriptors").read_bytes()
        device["descriptors"] = {
            "byte_length": len(descriptors),
            "sha256": hashlib.sha256(descriptors).hexdigest(),
            "hex": descriptors.hex(),
        }
    except OSError as exc:
        _error(device_errors, path / "descriptors", root, exc)

    for interface in entries:
        if not interface.name.startswith(path.name + ":"):
            continue
        interface_data = {
            "sysfs_name": interface.name,
            "driver": _driver_name(interface, root, device_errors),
        }
        for filename, output_name, base in (
            ("bInterfaceNumber", "interface_number", 16),
            ("bAlternateSetting", "alternate_setting", 10),
            ("bInterfaceClass", "class", 16),
            ("bInterfaceSubClass", "subclass", 16),
            ("bInterfaceProtocol", "protocol", 16),
            ("bNumEndpoints", "endpoint_count", 16),
        ):
            interface_data[output_name] = _read_number(
                interface / filename, root, device_errors, base=base
            )
        device["interfaces"].append(interface_data)

    device["read_errors"] = device_errors
    errors.extend(device_errors)
    return device


def _collect_alsa(root):
    """Keep card numbers and mixer control names, excluding free-form card headers."""
    root = Path(root)
    errors = []
    result = {"status": "available", "cards": [], "read_errors": errors}
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name)
    except (FileNotFoundError, NotADirectoryError):
        result["status"] = "unavailable"
        return result
    except OSError as exc:
        _error(errors, root, root, exc)
        result["status"] = (
            "permission_denied" if isinstance(exc, PermissionError) else "read_error"
        )
        return result
    for path in entries:
        match = re.fullmatch(r"card([0-9]+)", path.name)
        if not match:
            continue
        usb_id = _read_text(path / "usbid", root, errors, missing_ok=True)
        if usb_id is None or usb_id.lower() != VENDOR_ID + ":" + PRODUCT_ID:
            continue
        card = {"card_number": int(match[1]), "usb_id": usb_id.lower(), "controls": []}
        try:
            mixer = (path / "usbmixer").read_text(encoding="utf-8")
        except FileNotFoundError:
            mixer = ""
        except (OSError, UnicodeError) as exc:
            _error(errors, path / "usbmixer", root, exc)
            mixer = ""
        # The Card: header can contain identifiers. Do not include it or the raw dump.
        for line in mixer.splitlines():
            control = re.fullmatch(r'\s*Control: name="(.*)", index=([0-9]+)\s*', line)
            if control:
                card["controls"].append(
                    {"name": control[1], "index": int(control[2])}
                )
        result["cards"].append(card)
    if errors:
        result["status"] = (
            "permission_denied"
            if any(error["kind"] == "permission_denied" for error in errors)
            else "read_error"
        )
    return result


def collect(sysfs_root=DEFAULT_SYSFS_ROOT, asound_root=DEFAULT_ASOUND_ROOT):
    """Return a report; sysfs_root can be supplied for offline fixture validation."""
    root = Path(sysfs_root)
    errors = []
    report = {
        "schema_version": 1,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "system": {
            "os": platform.system(),
            "kernel_release": platform.release(),
            "architecture": platform.machine(),
        },
        "target": {"vendor_id": VENDOR_ID, "product_id": PRODUCT_ID},
        "status": None,
        "devices": [],
        "read_errors": errors,
        "alsa": _collect_alsa(asound_root),
    }
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name)
    except (FileNotFoundError, NotADirectoryError):
        report["status"] = "sysfs_unavailable"
        return report
    except OSError as exc:
        _error(errors, root, root, exc)
        report["status"] = (
            "permission_denied" if isinstance(exc, PermissionError) else "read_error"
        )
        return report

    for path in entries:
        if ":" in path.name:  # USB interface nodes do not have device IDs.
            continue
        vendor = _read_text(path / "idVendor", root, errors, missing_ok=True)
        if vendor is None or vendor.lower() != VENDOR_ID:
            continue
        product = _read_text(path / "idProduct", root, errors)
        if product is None or product.lower() != PRODUCT_ID:
            continue
        report["devices"].append(_collect_device(path, entries, root, errors))

    if report["devices"]:
        report["status"] = "found"
    elif any(error["kind"] == "permission_denied" for error in errors):
        report["status"] = "permission_denied"
    elif errors:
        report["status"] = "read_error"
    else:
        report["status"] = "absent"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Coleta dados USB da EVO 16, sem alterar a interface."
    )
    parser.add_argument(
        "--output", default="evo16-diagnostics.json", help="arquivo JSON de saída"
    )
    args = parser.parse_args(argv)
    report = collect()
    output = Path(args.output)
    try:
        # O_EXCL refuses existing paths, including symlinks; use private permissions.
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except FileExistsError:
        print(
            "O arquivo já existe. Escolha outro nome com --output.", file=sys.stderr
        )
        return 1
    except OSError:
        print(
            "Não foi possível gravar o relatório. Verifique o caminho e as permissões.",
            file=sys.stderr,
        )
        return 1

    print("Relatório salvo em: {}".format(output))
    if report["status"] == "found":
        print("EVO 16 encontrada: {} dispositivo(s).".format(len(report["devices"])))
        if report["read_errors"]:
            print("Alguns dados não puderam ser lidos; consulte read_errors no JSON.")
            return 1
        return 0
    if report["status"] == "absent":
        print("Nenhuma EVO 16 com ID USB 2708:000a foi encontrada.")
        return 2
    if report["status"] == "sysfs_unavailable":
        print("O sysfs USB não está disponível. Execute no seu Ubuntu.")
    elif report["status"] == "permission_denied":
        print("Sem permissão para ler alguns dados USB; consulte o JSON.")
    else:
        print("Não foi possível concluir a leitura dos dados USB; consulte o JSON.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
