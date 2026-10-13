# Instalação no Ubuntu 24.04.4

O runtime normal é Python 3.10 ou superior e `libasound.so.2`. O Ubuntu 24.04.4
fornece Python 3.12 e o pacote `libasound2t64`. Wine e os drivers Windows da
Audient não são necessários para o controlador nativo.

## Pacote Python

Para uso pelo terminal, o caminho recomendado é o
[instalador por usuário](ubuntu-installer.md). Com os fontes nesta máquina:

```bash
sudo apt update
sudo apt install python3 python3-venv libasound2t64
bash tools/install-ubuntu.sh --check
bash tools/install-ubuntu.sh
"$HOME/.local/bin/evolinux" doctor --json
```

Isso não executa testes no dispositivo nem altera serviços ou permissões de
áudio. A instalação é feita a partir do checkout local; o código deste ambiente
ainda precisa ser transferido para o Ubuntu do usuário. O diagnóstico padrão
não abre controles. Use [o roteiro do primeiro teste](first-test.md) depois
de instalar. GUI/Tkinter não são necessários nesta versão.

Para desenvolvimento e instalação editável, siga a alternativa abaixo.

Execute os comandos na raiz do checkout existente. Para obter o código em uma
nova máquina, faça primeiro:

```bash
git clone --branch codex/evo16-native-controller https://github.com/marcelopsjunior1769-cmyk/EVOLINUX.git
cd EVOLINUX
```

Essa branch estará disponível depois do envio dos fontes ao GitHub, que ainda
está pendente de autorização da integração. Não recrie o checkout existente
para executar estes passos.
O pacote de fontes também pode ser extraído localmente antes da publicação.

```bash
sudo apt update
sudo apt install python3 python3-venv libasound2t64
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/evolinux --help
.venv/bin/evolinux status --json
```

Também pode instalar o pacote de fontes em um ambiente virtual com
`python -m pip install .`. A leitura dos controles requer que a sessão do usuário
tenha acesso à placa ALSA. Se houver erro de permissão, investigue as permissões
existentes; não rode o aplicativo inteiro como root nem aplique permissões
globais `0666` aos dispositivos.

O comando `status` não usa dispositivos PCM. Pode ser executado com PipeWire em
funcionamento. Essa arquitetura busca preservar o áudio; a continuidade precisa
ser confirmada durante uma sessão real de gravação/reprodução.

| Resultado | Significado | Código de saída |
| --- | --- | --- |
| `found` sem erros | Controles solicitados foram lidos | 0 |
| `absent` | Nenhuma EVO 16 correspondente foi encontrada | 2 |
| `partial` | Alguns controles ou metadados falharam | 1 |
| `unavailable` | ALSA não está disponível neste ambiente | 1 |

Uma lista vazia não demonstra que o mixer funciona. Se o driver não expuser os
controles necessários, isso permanece uma limitação a investigar.

`status --card N` consulta somente a placa ALSA escolhida. Acrescente
`--control ID` para ler apenas um numid dessa placa, usando os números reais
do resultado anterior. O backend não lê valores dos outros controles nessa
seleção; controles ausentes ou sem mapeamento conhecido retornam erro.

O diagnóstico `doctor` retorna 0 quando seus pré-requisitos e verificações
terminam sem avisos, 2 quando há avisos ou dados incompletos, e 1 quando falta
um pré-requisito obrigatório. Nenhum desses códigos comprova áudio contínuo.

## Ajustes padrão ALSA

O fluxo recomendado começa com a prévia `plan-set`, que não executa a escrita
e apresenta os limites e o valor ALSA atual. Se a operação estiver validada,
ela sugere um comando manual com autorização e `--expect-current`. Veja
[a conferência de controles pelo terminal](terminal-controls.md).

O comando `set` existe para uma operação manual e explícita, depois de conferir
os controles e sua faixa no resultado de `status`. Seus argumentos incluem o
numid ALSA, a posição 1–N no vetor de valores e um **inteiro ALSA**, não um ganho
em dB. O numid e a posição no vetor não são IDs de canal USB.

Consulte `evolinux set --help`. Sem `--authorize-alsa-write`, o comando recusa a
operação antes de abrir a placa. Mesmo com autorização, o backend só aceita os
controles FU11 conhecidos e consistentes, revalida a identidade e os limites e
preserva os demais valores. Matrizes, controles privados e firmware não são
editáveis por esse caminho. Não foram realizados ajustes no hardware nesta
etapa; a autorização não substitui a validação física.

## Coleta sysfs

```bash
.venv/bin/evolinux collect --output evo16-diagnostics.json
```

É uma coleta de arquivos do kernel, sem abrir o dispositivo USB. Ela não requer
sudo nem o módulo de pesquisa. O JSON é criado com permissão `0600` e não
sobrescreve um arquivo existente.

## Módulo de pesquisa: somente compilação

O módulo não é necessário para usar o backend ALSA. Seu uso físico depende de
autorização específica e validação do pedido de leitura.

Para compilar no kernel informado `7.0.0-38-generic`:

```bash
sudo apt install build-essential gcc-13 linux-headers-7.0.0-38-generic
make -C kernel KDIR=/lib/modules/7.0.0-38-generic/build CC=gcc-13 W=1
```

Se estiver usando outro kernel, use os headers correspondentes ao resultado
real de `uname -r`. Não utilize um `.ko` compilado para uma versão diferente.
Esses comandos compilam; não instalam ou carregam o módulo. A assinatura de
módulo exigida pelo sistema deve ser respeitada; não desative Secure Boot para
contornar um erro de carregamento.

Na nuvem, a compilação do alvo 7.0.0-38-generic foi concluída com headers oficiais
Ubuntu e GCC 13.3.0 correspondente. MODPOST e link passaram. Os metadados BTF de
depuração foram omitidos por ausência de `pahole`; nenhuma verificação de
assinatura ou checksum de pacote foi desativada. O módulo não foi carregado.
