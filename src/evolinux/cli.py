# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 EVOLINUX contributors
"""Native ALSA command line. Private USB probes are separate, opt-in tools."""

import argparse
import json
import shlex
import sys

from .alsa import NativeAlsaBackend
from . import diagnostics
from . import __version__


def parser():
    result = argparse.ArgumentParser(
        description="Controlador nativo experimental da Audient EVO 16 para ALSA."
    )
    result.add_argument("--version", action="version", version="EVOLINUX " + __version__)
    commands = result.add_subparsers(dest="command")
    status = commands.add_parser("status", help="ler os controles ALSA da EVO 16")
    status.add_argument("--json", action="store_true", help="resultado JSON")
    status.add_argument("--card", type=int, help="ler somente esta placa ALSA")
    status.add_argument("--control", type=int, help="ler somente este numid; exige --card")
    collect = commands.add_parser("collect", help="coletar descritores pelo sysfs")
    collect.add_argument("--output", default="evo16-diagnostics.json")
    doctor = commands.add_parser("doctor", help="verificar instalação e serviços de áudio")
    doctor.add_argument("--json", action="store_true", help="resultado JSON para diagnóstico")
    doctor.add_argument("--controls", action="store_true",
                        help="incluir uma leitura padrão dos controles ALSA")
    change = commands.add_parser("set", help="ajuste explícito de ganho/fase pelo ALSA")
    preview = commands.add_parser("plan-set", help="conferir um ajuste sem escrever no controle")
    for command in (change, preview):
        command.add_argument("--card", type=int, required=True)
        command.add_argument("--control", type=int, required=True, help="numid ALSA")
        command.add_argument("--channel", type=int, required=True, help="posição 1–N no controle ALSA")
        command.add_argument("--value", type=int, required=True, help="valor inteiro ALSA, não dB")
    preview.add_argument("--json", action="store_true", help="prévia estruturada")
    change.add_argument("--expect-current", type=int,
                        help="recusar se o valor ALSA atual diferir do valor conferido")
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
            if control.get("minimum") is not None:
                print("    Faixa inteira ALSA: {} a {}; passo: {}".format(
                    control["minimum"], control["maximum"], control["step"]))
            print("    {} · unidade {} · seletor {} · posições: {}".format(
                "Ajustável com autorização" if control.get("adjustable") else "Somente leitura",
                control.get("unit", "?"), control.get("selector", "?"), control.get("count", "?")))
    if report.get("errors"):
        print("Há erros de leitura. Use --json para os detalhes.")
    if report.get("cards"):
        print("Valores inteiros ALSA; não são dB. As posições do vetor não identificam os pré-amplificadores físicos.")


def main(argv=None):
    arguments = parser()
    args = arguments.parse_args(argv)
    if args.command is None:
        arguments.print_help()
        return 0
    if args.command == "collect":
        return diagnostics.main(["--output", args.output])
    if args.command == "doctor":
        from .health import check_environment
        report = check_environment(include_controls=args.controls)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            _print_health(report)
        return {"ready": 0, "warnings": 2}.get(report["status"], 1)
    if args.command in ("set", "plan-set"):
        # Refuse before discovery or opening an ALSA handle when authorization
        # is absent. No private USB or kernel-module write path exists here.
        if args.command == "set" and not args.authorize_alsa_write:
            arguments.error("ajustes exigem --authorize-alsa-write")
        if not 0 <= args.card <= 4095 or not 1 <= args.control <= 0xffffffff or args.channel < 1:
            arguments.error("placa, controle ou canal inválido")
        try:
            backend = NativeAlsaBackend()
            if args.command == "plan-set":
                result = backend.plan_value(args.card, args.control, args.channel - 1, args.value)
                result["apply_arguments"] = ["evolinux", "set", "--card", str(args.card),
                    "--control", str(args.control), "--channel", str(args.channel),
                    "--value", str(args.value), "--expect-current", str(result["current_value"]),
                    "--authorize-alsa-write"]
            else:
                options = {"authorized": True}
                if args.expect_current is not None:
                    options["expected_current"] = args.expect_current
                result = backend.set_value(args.card, args.control, args.channel - 1, args.value, **options)
        except (OSError, ValueError, PermissionError, RuntimeError) as exc:
            print("{} recusado: {}".format("Prévia" if args.command == "plan-set" else "Ajuste", exc), file=sys.stderr)
            return 1
        if args.command == "plan-set" and not args.json:
            _print_plan(result)
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.card is not None and not 0 <= args.card <= 4095:
        arguments.error("--card deve estar entre 0 e 4095")
    if args.control is not None and (args.card is None or not 1 <= args.control <= 0xffffffff):
        arguments.error("--control exige --card e um numid positivo")
    backend = NativeAlsaBackend()
    report = (backend.snapshot() if args.card is None else
              backend.snapshot(card_number=args.card, numid=args.control))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_status(report)
    if report["status"] == "found" and not report.get("errors"):
        return 0
    return 2 if report["status"] == "absent" else 1


def _print_health(report):
    print("Pré-requisitos: {}".format(
        "disponíveis" if report["software_prerequisites"] == "ready" else "incompletos"))
    print("Python: {}; libasound: {}".format(
        report.get("python", {}).get("version", "?"),
        "disponível" if report.get("libasound", {}).get("available") else "indisponível"))
    print("Kernel: {}".format(report.get("kernel") or "não identificado"))
    cards = report.get("alsa", {}).get("cards", [])
    print("Placas EVO 16 identificadas: {}".format(len(cards)))
    for service, info in report.get("services", {}).items():
        print("{}: {}".format(service, info["state"]))
    for warning in report.get("warnings", []):
        print("Aviso: {}".format(warning))
    for error in report.get("errors", []):
        print("Erro: {} (errno: {})".format(error.get("message", "falha de diagnóstico"), error.get("errno")))
    if report["status"] == "ready":
        print("O software está preparado para um teste local. A continuidade do áudio precisa ser observada.")
    print("Use doctor --json para o relatório completo.")


def _print_plan(result):
    print("Prévia concluída; o aplicativo não escreveu no controle.")
    print("Placa {} · controle {} · {} · posição {}".format(
        result["card_number"], result["numid"], result["name"], result["channel_position"]))
    print("Valor ALSA atual: {}; proposto: {}; faixa: {} a {}; passo: {}".format(
        result["current_value"], result["target_value"], result["minimum"], result["maximum"], result["step"]))
    print("Valores inteiros ALSA, não dB. A correspondência com o canal físico precisa estar confirmada.")
    if result["would_change"]:
        print("Após conferir o controle, o ajuste exige executar manualmente:")
        print(shlex.join(result["apply_arguments"]))
    else:
        print("O controle já informa o valor proposto; nenhum ajuste é necessário.")
