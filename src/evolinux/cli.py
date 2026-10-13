# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 EVOLINUX contributors
"""Native ALSA command line. Private USB probes are separate, opt-in tools."""

import argparse
import json
import sys

from .alsa import NativeAlsaBackend
from . import diagnostics


def parser():
    result = argparse.ArgumentParser(
        description="Controlador nativo experimental da Audient EVO 16 para ALSA."
    )
    result.add_argument("--version", action="version", version="EVOLINUX 0.1.0")
    commands = result.add_subparsers(dest="command")
    status = commands.add_parser("status", help="ler os controles ALSA da EVO 16")
    status.add_argument("--json", action="store_true", help="resultado JSON")
    collect = commands.add_parser("collect", help="coletar descritores pelo sysfs")
    collect.add_argument("--output", default="evo16-diagnostics.json")
    change = commands.add_parser("set", help="ajuste explícito de ganho/fase pelo ALSA")
    change.add_argument("--card", type=int, required=True)
    change.add_argument("--control", type=int, required=True, help="numid ALSA")
    change.add_argument("--channel", type=int, required=True, help="posição 1–N no controle ALSA")
    change.add_argument("--value", type=int, required=True, help="valor inteiro ALSA, não dB")
    change.add_argument("--authorize-alsa-write", action="store_true",
                        help="autorizar este ajuste padrão após conferir o controle e a faixa")
    return result


def _print_status(report):
    labels = {"unavailable": "ALSA indisponível neste ambiente.",
              "absent": "Nenhuma EVO 16 foi encontrada no ALSA.",
              "found": "EVO 16 encontrada no ALSA.",
              "partial": "A leitura ALSA ficou incompleta."}
    print(labels.get(report["status"], "Não foi possível concluir a leitura ALSA."))
    for card in report.get("cards", []):
        print("Placa {}:".format(card["card_number"]))
        for control in card.get("controls", []):
            values = control.get("values")
            text = "indisponível" if values is None else ", ".join(str(x) for x in values)
            print("  {} · {} · valores: {}".format(
                control["numid"], control["name"], text))
    if report.get("errors"):
        print("Há erros de leitura. Use --json para os detalhes.")


def main(argv=None):
    arguments = parser()
    args = arguments.parse_args(argv)
    if args.command is None:
        arguments.print_help()
        return 0
    if args.command == "collect":
        return diagnostics.main(["--output", args.output])
    if args.command == "set":
        # Refuse before discovery or opening an ALSA handle when authorization
        # is absent. No private USB or kernel-module write path exists here.
        if not args.authorize_alsa_write:
            arguments.error("ajustes exigem --authorize-alsa-write")
        if args.card < 0 or args.control < 1 or args.channel < 1:
            arguments.error("placa, controle ou canal inválido")
        try:
            result = NativeAlsaBackend().set_value(
                args.card, args.control, args.channel - 1, args.value,
                authorized=True)
        except (OSError, ValueError, PermissionError, RuntimeError) as exc:
            print("Ajuste recusado: {}".format(exc), file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    report = NativeAlsaBackend().snapshot()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_status(report)
    if report["status"] == "found" and not report.get("errors"):
        return 0
    return 2 if report["status"] == "absent" else 1
