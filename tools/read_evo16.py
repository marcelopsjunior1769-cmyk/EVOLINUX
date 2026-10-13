#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 EVOLINUX contributors
"""Probe the experimental EVO 16 read transport; never change device controls."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from evolinux.protocol import CUR, ControlRead, decode_gain_db
from evolinux.readonly import DEVICE_NODE, read_control

spec = importlib.util.spec_from_file_location(
    "evo16_sysfs_collector", PROJECT_ROOT / "tools" / "collect_evo16.py"
)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


def select_device(inventory, bus_number=None, device_number=None):
    devices = inventory["devices"]
    if bus_number is not None:
        devices = [d for d in devices if d["bus_number"] == bus_number
                   and d["device_number"] == device_number]
    if not devices:
        raise ValueError("Nenhuma EVO 16 corresponde à seleção neste Ubuntu.")
    if len(devices) != 1:
        raise ValueError("Há várias EVO 16. Selecione uma com --bus e --device.")
    device = devices[0]
    interfaces = [i for i in device["interfaces"]
                  if (i["class"], i["subclass"], i["protocol"]) == (1, 1, 32)]
    if len(interfaces) != 1 or interfaces[0]["interface_number"] is None:
        raise ValueError("A interface Audio Control UAC2 não foi identificada.")
    if not device["bus_number"] or not device["device_number"]:
        raise ValueError("O endereço USB não pôde ser lido.")
    return device, interfaces[0]["interface_number"]


def probe(device, interface_number, *, include_gain=False,
          include_extension=False, node=DEVICE_NODE):
    readings = []
    report = {"status": None, "device": device,
              "interface_number": interface_number, "readings": readings}

    def read(name, unit, selector, channel, length, decoder=None,
             exploratory=False):
        control = ControlRead(unit, selector, channel, CUR, length,
                              interface_number=interface_number)
        setup = control.usb_setup
        entry = {"name": name, "exploratory": exploratory,
                 "unit_id": unit, "selector": selector, "channel": channel,
                 "usb_setup_hex": setup.pack().hex(), "status": None}
        readings.append(entry)
        try:
            payload = read_control(device["bus_number"], device["device_number"],
                                   control, node=node)
            entry["actual_length"] = len(payload)
            entry["hex"] = payload.hex()
            if len(payload) != length:
                raise ValueError("Resposta CUR com comprimento inesperado.")
            value = decoder(payload) if decoder is not None else None
            if decoder is not None:
                entry["value"] = value
            entry["status"] = "read"
            return value
        except OSError as exc:
            entry["status"] = "error"
            entry["error"] = {"kind": "os_error", "errno": exc.errno,
                              "message": os.strerror(exc.errno) if exc.errno else "Erro de leitura"}
        except ValueError as exc:
            entry["status"] = "error"
            entry["error"] = {"kind": "invalid_response", "message": str(exc)}
        return None

    def clock_pin(payload):
        value = payload[0]
        if value not in (1, 2, 3):
            raise ValueError("Pino de clock fora do descritor fornecido (1–3).")
        return value

    def boolean(payload):
        if payload[0] not in (0, 1):
            raise ValueError("Resposta de estado não é 0 ou 1.")
        return bool(payload[0])

    pin = read("clock_selector", 40, 1, 0, 1, clock_pin)
    if pin is not None:
        source = {1: 41, 2: 44, 3: 45}[pin]
        report["selected_clock_unit"] = source
        read("clock_frequency_hz", source, 1, 0, 4,
             lambda payload: int.from_bytes(payload, "little"))
        read("clock_valid", source, 2, 0, 1, boolean)

    if include_gain:
        for channel in range(1, 9):
            read("input_gain_db", 11, 0x0B, channel, 2, decode_gain_db)
            read("phase_inverted", 11, 0x0D, channel, 1, boolean)
    if include_extension:
        # Reference-only EU58 mapping. Store raw bytes, not inferred gain/48V.
        for selector in (0, 1, 2):
            read("eu58_candidate", 58, selector, 0, 4, exploratory=True)

    passed = sum(entry["status"] == "read" for entry in readings)
    report["status"] = ("read" if passed == len(readings)
                        else "partial" if passed else "failed")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Teste de leituras da EVO 16 pela ponte experimental."
    )
    parser.add_argument("--output", default="evo16-readings.json")
    parser.add_argument("--bus", type=int, help="número do barramento USB")
    parser.add_argument("--device", type=int, help="número do dispositivo USB")
    parser.add_argument("--include-gain", action="store_true",
                        help="ler ganho e fase da unidade 11 nos canais 1–8")
    parser.add_argument("--include-extension", action="store_true",
                        help="ler candidatos privados EU58; resultado ainda experimental")
    args = parser.parse_args(argv)
    if (args.bus is None) != (args.device is None):
        parser.error("--bus e --device devem ser usados juntos")
    output = Path(args.output)
    try:
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print("O arquivo já existe. Escolha outro nome com --output.", file=sys.stderr)
        return 1
    except OSError:
        print("Não foi possível criar o relatório.", file=sys.stderr)
        return 1
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        inventory = collector.collect()
        try:
            device, interface = select_device(inventory, args.bus, args.device)
            report = probe(device, interface, include_gain=args.include_gain,
                           include_extension=args.include_extension)
        except ValueError as exc:
            report = {"status": "unavailable", "inventory": inventory,
                      "error": str(exc)}
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print("Relatório salvo em: {}".format(output))
    if report["status"] == "read":
        print("As leituras solicitadas foram recebidas. O mixer original ainda não foi validado.")
        return 0
    print("As leituras não foram concluídas; o JSON registra os erros.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
