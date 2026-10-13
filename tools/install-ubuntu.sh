#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 EVOLINUX contributors
# Install a supplied local checkout without touching audio devices or services.
set -euo pipefail

usage() {
    cat <<'EOF'
Uso: bash tools/install-ubuntu.sh [--check] [--allow-unsupported]
                               [--prefix DIRETORIO]

  --check              Somente verificar requisitos; não criar arquivos.
  --allow-unsupported  Permitir outro Linux para teste de desenvolvimento.
  --prefix DIRETORIO   Usar DIRETORIO/bin e DIRETORIO/share em vez dos padrões.
  --help               Mostrar esta ajuda.

O alvo suportado é Ubuntu 24.04. O instalador não executa sudo/apt, não
controla a interface, não altera PipeWire e não instala módulos de kernel.
EOF
}

check_only=0
allow_unsupported=0
prefix_option=
while (( $# )); do
    case "$1" in
        --check) check_only=1; shift ;;
        --allow-unsupported) allow_unsupported=1; shift ;;
        --prefix)
            if (( $# < 2 )); then
                printf 'A opção --prefix exige um diretório absoluto.\n' >&2
                exit 2
            fi
            prefix_option=$2
            shift 2
            ;;
        --help|-h) usage; exit 0 ;;
        *) printf 'Opção desconhecida: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

source_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
missing=0
supported=0
if [[ -r /etc/os-release ]]; then
    # This is the operating system's own configuration, not project input.
    . /etc/os-release
    if [[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 24.04 ]]; then
        supported=1
    fi
    printf 'Sistema: %s\n' "${PRETTY_NAME:-Linux}"
fi
if (( ! supported )); then
    printf 'Aviso: este sistema não é o alvo Ubuntu 24.04.4.\n' >&2
fi

if ! command -v python3 >/dev/null 2>&1; then
    printf 'Falta o comando python3.\n' >&2
    missing=1
else
    if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) and sys.platform == "linux" else 1)'; then
        printf 'É necessário Python 3.10 ou superior no Linux.\n' >&2
        missing=1
    fi
    if ! python3 -c 'import venv, ensurepip' >/dev/null 2>&1; then
        printf 'Falta o suporte a ambientes virtuais (python3-venv).\n' >&2
        missing=1
    fi
    if ! python3 -c 'import ctypes; ctypes.CDLL("libasound.so.2")' >/dev/null 2>&1; then
        printf 'Falta libasound.so.2 (libasound2t64).\n' >&2
        missing=1
    fi
fi
if (( missing )); then
    printf '\nNo Ubuntu 24.04, instale os requisitos manualmente:\n' >&2
    printf '  sudo apt update\n' >&2
    printf '  sudo apt install python3 python3-venv libasound2t64\n' >&2
    exit 1
fi
printf 'Requisitos disponíveis. Nenhum dispositivo de áudio foi aberto.\n'
if (( check_only )); then
    exit 0
fi
if (( ! supported && ! allow_unsupported )); then
    printf 'Instalação recusada fora do Ubuntu 24.04; use --allow-unsupported somente para desenvolvimento.\n' >&2
    exit 1
fi

: "${HOME:?HOME precisa apontar para a pasta do usuário.}"
data_home=${XDG_DATA_HOME:-"$HOME/.local/share"}
bin_directory="$HOME/.local/bin"
if [[ -n $prefix_option ]]; then
    data_home="$prefix_option/share"
    bin_directory="$prefix_option/bin"
fi
releases="$data_home/evolinux/releases"
launcher="$bin_directory/evolinux"
for location in "$HOME" "$data_home" "$bin_directory" "$source_root"; do
    if [[ $location != /* || $location == *$'\n'* || $location == *$'\r'* || $location == *$'\t'* ]]; then
        printf 'Os caminhos de instalação e fontes precisam ser absolutos e não conter controles de linha.\n' >&2
        exit 1
    fi
done

# Run collision checks before creating a virtual environment, and again before
# activation to preserve a file created concurrently by another application.
check_collisions() {
    if [[ -e "$launcher" || -L "$launcher" ]]; then
        if [[ -L "$launcher" || ! -f "$launcher" ]] || ! grep -Fxq '# EVOLINUX managed user launcher v1' "$launcher"; then
            printf 'Preservado arquivo existente não gerenciado: %s\n' "$launcher" >&2
            return 1
        fi
    fi
}
check_collisions
if [[ ! -f "$source_root/pyproject.toml" || ! -f "$source_root/src/evolinux/cli.py" ]]; then
    printf 'A pasta não contém os fontes completos do EVOLINUX.\n' >&2
    exit 1
fi

mkdir -p -- "$releases"
release=$(mktemp -d "$releases/install-XXXXXXXX")
activated=0
cleanup() {
    # A failed installation removes only the new unique release, never the
    # existing launcher, existing releases, checkout or user diagnostic files.
    if (( ! activated )) && [[ -n ${release:-} ]]; then
        # The Python helper may have completed os.replace before failing or
        # receiving a signal. Its launcher already references this release;
        # deleting it would break the installed command. Both marker lines
        # are literal text, so spaces/quotes in paths cannot affect the check.
        if [[ -f "$launcher" && ! -L "$launcher" ]] &&
           grep -Fxq '# EVOLINUX managed user launcher v1' "$launcher" &&
           grep -Fxq "# EVOLINUX release: $release" "$launcher"; then
            return
        fi
        rm -rf -- "$release"
    fi
}
trap cleanup EXIT
build_source="$release/build-source"
python3 - "$source_root" "$build_source" <<'PY'
from pathlib import Path
import shutil
import sys

source, destination = map(Path, sys.argv[1:])
destination.mkdir()
for name in ("pyproject.toml", "README.md", "LICENSE"):
    shutil.copyfile(source / name, destination / name)
for directory in ("LICENSES", "third_party_licenses"):
    (destination / directory).mkdir()
    for path in (source / directory).glob("*.txt"):
        shutil.copyfile(path, destination / directory / path.name)
# Build from a private copy. pip/setuptools must not generate build metadata
# inside the user's checkout. No installer, extracted binary or USB research
# module is copied into the installed runtime.
package = source / "src" / "evolinux"
for path in package.rglob("*.py"):
    if "__pycache__" not in path.parts:
        target = destination / "src" / "evolinux" / path.relative_to(package)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
PY
python3 -m venv "$release/venv"
"$release/venv/bin/python" -m pip --disable-pip-version-check --no-cache-dir install "$build_source"
"$release/venv/bin/evolinux" --help >/dev/null
rm -rf -- "$build_source"
check_collisions
mkdir -p -- "$bin_directory"

python3 - "$release" "$launcher" <<'PY'
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile

release, launcher = map(Path, sys.argv[1:])
release_identifier = sys.argv[1]
executable = release / "venv" / "bin" / "evolinux"
content = (
    "#!/bin/sh\n# EVOLINUX managed user launcher v1\n"
    "# EVOLINUX release: " + release_identifier + "\nexec "
    + shlex.quote(str(executable)) + ' "$@"\n'
)


def prepared(path, text, mode):
    descriptor, filename = tempfile.mkstemp(prefix=".evolinux-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(filename, mode)
        return Path(filename)
    except BaseException:
        Path(filename).unlink(missing_ok=True)
        raise


temporary = []
try:
    launcher_temporary = prepared(launcher, content, 0o755)
    temporary.append(launcher_temporary)
    metadata = {
        "managed_by": "EVOLINUX install-ubuntu.sh v1",
        "launcher": str(launcher),
        "executable": str(executable),
    }
    (release / "installation.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    # The executable switch occurs only after build, installation, help and
    # all file preparation succeeded. Virtualenv paths never change.
    os.replace(launcher_temporary, launcher)
finally:
    for path in temporary:
        path.unlink(missing_ok=True)
PY
activated=1
printf '\nInstalação concluída: %s\n' "$release"
printf 'Comando: %s\n' "$launcher"
printf 'Verificação: "%s" --help\n' "$launcher"
printf 'Instalações anteriores foram preservadas. Nenhum controle de áudio foi executado.\n'
