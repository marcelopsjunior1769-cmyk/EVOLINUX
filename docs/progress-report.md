# Relatório da adaptação e organização

Estado registrado em 12 de outubro de 2026. Alvo informado: Ubuntu 24.04.4 LTS,
kernel `7.0.0-38-generic`, Audient EVO 16 `2708:000a`.

## Material analisado

- Instalador `EVO-v4.4.0a.exe`, 27.239.736 bytes, SHA-256
  `5a08a609e989ea49556fdfae152189934e8c32812842f42a50720c97707b19c7`.
  Contêiner NSIS, executáveis x86/x64, biblioteca TUSBAUDIO, INF do driver,
  imports, exports e dados de assinatura foram examinados estaticamente.
  O instalador não foi executado nem convertido para um executável Linux.
- Descritores USB enviados pelo usuário: interfaces UAC2/DFU, unidades de
  controles, clocks e matrizes. A análise está em
  [device-topology.pt-BR.md](device-topology.pt-BR.md).
- Projetos `soerenbnoergaard/evoctl` e `djenttleman/evo16-API-web`, em revisões
  registradas em [references.md](references.md). Seus protocolos são referências,
  com limitações e diferenças de modelo explicitadas.
- APIs de USB/runtime PM e mixer do Linux/ALSA. Foram consultadas para conferir
  endereçamento UAC2, manutenção do driver de áudio e acesso por ALSA CTL.

As notas Windows permanecem em [installer-analysis.pt-BR.md](installer-analysis.pt-BR.md),
[tusbaudio-abi.md](tusbaudio-abi.md), [tusbaudio-properties.md](tusbaudio-properties.md)
e [tusbaudio-notifications.md](tusbaudio-notifications.md).

## Componentes desenvolvidos

A evolução para 0.2.0 prioriza o terminal, conforme a escolha do usuário.
Foram acrescentados `health.py`/`doctor`, o instalador por usuário e seleção
de placa/numid em `status`. O diagnóstico padrão não abre CTL ou PCM; informa
pré-requisitos, kernel, metadados ALSA e serviços de áudio. O instalador não
abre dispositivos e preserva versões anteriores. O rascunho de GUI foi
preservado fora do runtime, em vez de entrar nesta entrega.

Em 0.3.0, `plan-set` valida uma proposta por leitura do controle selecionado,
sem executar o ajuste. `set --expect-current` permite recusar um valor ALSA
que mudou desde a conferência. O diagnóstico direto de `/proc/asound` foi
documentado para obter os metadados do Ubuntu mesmo sem baixar os fontes;
nenhum número de série ou nome de placa é solicitado por esse roteiro.

| Componente | Arquivos | Estado |
| --- | --- | --- |
| Backend nativo ALSA CTL | `src/evolinux/alsa.py` | Descoberta, snapshot e ajuste explícito de ganho/fase; testes com transporte simulado |
| CLI Python | `src/evolinux/cli.py`, `__main__.py` | `status`, `collect`, ajuste autorizado; erros e ausência não viram leituras simuladas |
| Diagnóstico de primeiro uso | `src/evolinux/health.py` | `doctor`, serviços e metadados sem CTL por padrão |
| Instalador por usuário | `tools/install-ubuntu.sh` | Instalação CLI isolada, atualização e falhas sem apagar versões anteriores |
| Diagnóstico de metadados | `diagnostics.py`, `devices.py`, `tools/collect_evo16.py` | Leitura sysfs, parsing de configuração ativa e proteção de identidade/privacidade |
| Protocolo de leituras UAC2 | `protocol.py`, `readonly.py`, `tools/read_evo16.py` | CUR/RANGE, parsing e contrato ioctl; pesquisa opcional |
| Transporte de kernel | `kernel/evo16_readonly.c`, `include/evo16_bridge_uapi.h` | Somente IN, whitelist e timeout; compilado, nunca carregado |
| Protótipo de compatibilidade Windows | `research/wine_broker.py` | Parcial, preservado fora do runtime nativo |
| Distribuição e desenvolvimento | `pyproject.toml`, `MANIFEST.in`, `tests/`, `.github/workflows/tests.yml` | Pacote Python, fontes de pesquisa e CI sem hardware |

## Dificuldades encontradas

O instalador contém binários proprietários, sem o código-fonte do EVO Mixer.
O aplicativo usa uma API Windows de driver; executar sua interface sob Wine
não fornece essa camada no Linux. A investigação de ABI ficou preservada, mas
não equivale a uma ponte funcional ou a uma versão oficial portada.

As interfaces UAC2 estão ocupadas por `snd-usb-audio`. Reivindicá-las ou
desconectar o driver para acessar controles privados pode interromper o áudio.
Por isso o caminho padrão usa ALSA CTL e não altera configuração USB, PCM ou
serviços PipeWire. Acesso privado continua separado e sujeito a autorização.

Os avisos de `lsusb` sobre matrizes foram confrontados com a topologia: o tamanho
correto do bitmap depende do total de canais de entrada, não apenas do número
de pinos. O aviso não é, por si só, prova de firmware inválido. Além disso,
descritores sozinhos não confirmam a semântica dos comandos privados.

As referências externas diferem entre EVO 4/8 e EVO 16, macOS e Linux, e incluem
operações incompatíveis com a prioridade de áudio contínuo. Não se transplantou
reset/detach nem comandos cuja semântica permaneça incerta.

O backend precisa lidar com controles brutos, truncamento de canais pelo kernel,
erros de leitura e numids reutilizados. Não atribui valores em dB ou nomes de
canais físicos sem evidência. O parser foi corrigido para rejeitar descritores
curtos ou de comprimento inválido e mudanças da revisão de dispositivo.

## Validação e limitações

Os testes automatizados não acessam hardware. O módulo foi compilado com `W=1`
contra Debian 6.12.107 e contra headers oficiais Ubuntu 7.0.0-38-generic com
GCC 13.3. A compilação confirma compatibilidade das APIs utilizadas; não confirma
a aceitação dos pedidos pela EVO. O ambiente na nuvem não possui a interface.
Os resultados consolidados ficam em [validation.md](validation.md).

Não foram executadas escritas ALSA no dispositivo, requisições USB experimentais,
operações DFU ou alterações de firmware. A continuidade do áudio com PipeWire
ainda precisa ser medida no computador do usuário em uma sessão autorizada.

## O que falta implementar

A [matriz de funcionalidades](features.md) detalha os próximos passos:
correspondência dos canais e escalas físicas, interface gráfica, medição e
notificações, controle privado de pré-amplificadores EU58, phantom, Smartgain,
instrumento e roteamento. Leituras/escritas privadas exigem evidência e validação
específica antes de integração. Atualização de firmware permanece fora do escopo.

## Preservação e publicação

Todo o checkout anterior à organização foi preservado em um backup local fora
do repositório. Os estudos Windows e o protótipo Python continuam neste projeto
como histórico; os binários proprietários e dados reais do equipamento não são
distribuídos. A licença Python é GPL-3.0-only, conforme escolha do responsável;
as demais licenças e atribuições estão em [../LICENSING.md](../LICENSING.md).

Preparar as fontes e os artefatos não publica commits nem releases no GitHub.
O procedimento de revisão e envio está em [../CONTRIBUTING.md](../CONTRIBUTING.md).
