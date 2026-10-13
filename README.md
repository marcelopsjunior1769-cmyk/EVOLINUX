# EVOLINUX — Audient EVO 16 no Ubuntu

Controlador nativo experimental para a **Audient EVO 16**, com prioridade para
ALSA e convivência com PipeWire. Alvo: **Ubuntu 24.04.4 LTS**. O dispositivo
identificado é `2708:000a`; o kernel informado para desenvolvimento é
`7.0.0-38-generic`.

**Estado: versão alfa, sem validação física completa.** Os testes automatizados
usam fixtures e simulam as chamadas ao hardware. Eles não comprovam funcionamento
do mixer na EVO conectada ao seu computador. O projeto não é um produto oficial
da Audient nem uma versão convertida do instalador Windows.

## Instalação e primeira leitura

Com os fontes disponíveis no seu Ubuntu 24.04.4, entre na pasta do projeto:

```bash
sudo apt update
sudo apt install python3 python3-venv libasound2t64
bash tools/install-ubuntu.sh --check
bash tools/install-ubuntu.sh
"$HOME/.local/bin/evolinux" doctor --json
```

O instalador cria uma versão isolada por usuário e preserva instalações
anteriores; não precisa de sudo, Wine, interface gráfica ou módulo de kernel.
O comando `doctor` verifica pré-requisitos, kernel, metadados da EVO e estado
de PipeWire/WirePlumber. Por padrão, não abre controles ALSA/PCM nem envia
comandos USB. Veja [o instalador](docs/ubuntu-installer.md) e
[o primeiro teste no Ubuntu](docs/first-test.md).

Para ler os controles, execute `"$HOME/.local/bin/evolinux" status --json`.
`status` usa somente a API de controles ALSA. Não abre dispositivos PCM, reinicia
PipeWire, reivindica interfaces USB ou carrega o módulo experimental. Sem a EVO,
o resultado registra ausência ou indisponibilidade, em vez de mostrar valores
de demonstração. Em um checkout, também pode usar:

```bash
PYTHONPATH=src python3 -m evolinux status --json
```

Leia as [instruções completas](docs/installation.md) e os
[riscos e limites de operação](docs/usb-risks.md) antes de ajustar controles.

Se os fontes ainda não chegaram ao seu Ubuntu, a
[coleta inicial pelo terminal](docs/bootstrap-diagnostics.md) permite informar
os controles que o kernel expõe sem instalar este projeto. Com o controlador
instalado, `plan-set` mostra uma prévia sem escrita pelo aplicativo e sugere
um ajuste manual condicionado ao valor ALSA conferido. Veja
[o fluxo de conferência](docs/terminal-controls.md).

## Componentes implementados

- Descoberta da EVO 16 por `/proc/asound` e metadados do mixer do kernel.
- Instalação por usuário com atualização que preserva versões anteriores.
- Diagnóstico de pré-requisitos e serviços sem abrir controles por padrão.
- Backend ALSA CTL para ler controles das unidades 11, 60 e 61 quando expostos
  pelo driver, sem converter valores brutos em dB inventados.
- Seleção de placa/numid na leitura para limitar o acesso ao controle escolhido.
- Prévia `plan-set`, sem escrita, e condição `--expect-current` para recusar
  um ajuste quando o valor ALSA mudou desde a conferência.
- Caminho de ajuste explícito de ganho/fase FU11, com autorização por operação,
  validação de identidade, tipo, faixa, passo e canal. **Ainda não testado no
  hardware; escritas não acontecem no fluxo padrão.**
- Coletor sysfs de descritores e drivers, sem número de série ou mudanças USB.
- Construção e interpretação de leituras UAC2 CUR/RANGE.
- Módulo de pesquisa restrito a leituras, opcional e não carregado
  automaticamente. Compilou para o kernel `7.0.0-38-generic`.
- Testes automatizados, empacotamento Python e workflow de CI sem acesso USB.

Veja a [matriz de funcionalidades](docs/features.md) para distinguir código
implementado de capacidades comprovadas no dispositivo.

## O que permanece pendente

Interface gráfica, medição, correspondência dos controles aos canais físicos,
ganho de pré-amplificador privado EU58, phantom 48 V, Smartgain, modo instrumento,
roteamento completo, notificações e validação de áudio contínuo com PipeWire.
Não há implementação de atualização de firmware.

## Diagnóstico sem enviar comandos USB

```bash
"$HOME/.local/bin/evolinux" collect --output evo16-diagnostics.json
```

O coletor lê arquivos que o kernel já expõe. O módulo e o utilitário
`tools/read_evo16.py` são pesquisas separadas; não os execute sem autorização
para o teste físico específico. Nenhum teste automatizado carrega módulos ou
usa a EVO real.

## Desenvolvimento e testes

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

Para desenvolvimento, crie `.venv` com `python3 -m venv .venv` e instale o
checkout com `.venv/bin/python -m pip install -e .`. Sem instalação, use
`PYTHONPATH=src python3 -m unittest discover -s tests -v`.
As instruções de contribuição e de publicação ficam em
[CONTRIBUTING.md](CONTRIBUTING.md).

O [relatório do trabalho](docs/progress-report.md) registra o material analisado,
as dificuldades e a preservação do histórico. Os resultados de compilação,
testes e empacotamento estão em [docs/validation.md](docs/validation.md).

## Organização

```text
src/evolinux/        backend ALSA, CLI, diagnóstico e protocolo UAC2
tools/              entradas de diagnóstico para usar no checkout
kernel/             módulo opcional de leituras experimentais
include/            contrato ioctl do módulo
tests/              verificações independentes de hardware
docs/               instalação, protocolo, riscos, estado e referências
research/           protótipo Wine preservado como histórico, fora do runtime
third_party_licenses/ avisos das referências consultadas
```

A análise anterior do instalador e da API Windows permanece documentada. O
instalador proprietário, DLLs, drivers e dumps do equipamento não integram a
distribuição do projeto.

## Referências e atribuições

- [soerenbnoergaard/evoctl](https://github.com/soerenbnoergaard/evoctl), MIT:
  referência da família EVO 4/8 e mensagens USB. Sua rotina de detach/reset não
  foi incorporada ao controlador nativo.
- [djenttleman/evo16-API-web](https://github.com/djenttleman/evo16-API-web), MIT:
  referência de comandos privados da EVO 16 em macOS. As divergências e os
  limites de validação estão registrados em [docs/references.md](docs/references.md).
- Linux/ALSA: especificações de controles UAC2, formato do mixer e APIs de kernel.

Os avisos originais estão em `third_party_licenses/`. O código Python usa
[GPL-3.0-only](LICENSE); o módulo Linux usa GPL-2.0-only. Consulte
[LICENSING.md](LICENSING.md) para o escopo e a exceção do header UAPI.
