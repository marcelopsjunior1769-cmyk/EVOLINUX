# Perfil ALSA observado no Ubuntu do usuário

O usuário forneceu os metadados de `/proc/asound/card1/usbmixer` no Ubuntu
24.04.4 LTS, com kernel informado `7.0.0-38-generic`. O cabeçalho foi
`usb_id=0x2708000a, ctrlif=0, ctlerr=0`. O número `card1` é o da coleta e pode
mudar após reconectar. A coleta não leu valores nem executou ajustes.

| Entidade | Campo `control` | Tipo USB | Máscara | Valores por controle | Controles publicados |
| --- | --- | --- | --- | --- | --- |
| FU11, ganho padrão | 11 (`0x0b`) | S16 | `0xffffff` | 16 | 1 |
| FU11, inversão de polaridade | 13 (`0x0d`) | BOOLEAN | `0xffffff` | 16 | 1 |
| Mixer 60 | 1 a 24 | S16 | `0x3f` | 6 | 24 |
| Mixer 61 | 1 a 24 | S16 | `0x0f` | 4 | 24 |
| Seletor de clock 40 | 1 | U8 | `0x0` | 1 | 1 |
| Validade de clock 41, 44 e 45 | 2 | BOOLEAN | `0x0` | 1 por entidade | 3 |

As unidades 11/60/61 oferecem 50 controles candidatos ao backend atual, com
272 posições de valores: `16 + 16 + 24×6 + 24×4`. Os quatro controles de clock
estão fora do caminho de leitura/ajuste desse backend. Nos mixers, o campo
`control` identifica a entrada da matriz no mapeamento do driver; não é o
seletor de função de uma Feature Unit.

Os descritores USB anteriores anunciam FU11 com 24 canais e matrizes de
34×6/34×4. O inventário ALSA recebido publica somente 16 posições em cada
controle de FU11 e entradas 1–24 nos mixers. A máscara `0xffffff` de FU11 não
autoriza acessar mais posições que as 16 publicadas. As entradas 25–34 das
matrizes não aparecem nessa coleta; o controlador deve usar o inventário
disponível, sem criar controles ausentes. A causa dessa diferença não foi
validada neste equipamento.

Uma segunda coleta, `amixer -c 1 controls`, forneceu os identificadores ALSA:

| Numid | Interface ALSA | Nome | Índice |
| --- | --- | --- | --- |
| 1 | MIXER | `Input Gain Control` | 0 |
| 2 | MIXER | `Phase Inverter Control` | 0 |
| 3–50 | MIXER | `Analogue 5 Volume` | 0–47, respectivamente |
| 51 | CARD | `Audient Internal Clock Validity` | 0 |
| 52 | CARD | `Audient Optical1 Clock Validity` | 0 |
| 53 | CARD | `Audient Optical2 Clock Validity` | 0 |
| 54 | MIXER | `Audient Clock Selector Clock Source` | 0 |

O índice zero é o padrão, mesmo quando não aparece na saída do `amixer`.
Uma terceira coleta incluiu as linhas `Control:` de `usbmixer`, confirmando
o vínculo com as entidades e entradas:

| Numid | Índice ALSA | Unit | Campo `control` do driver |
| --- | --- | --- | --- |
| 1 | 0 | 11 | 11, ganho padrão |
| 2 | 0 | 11 | 13, inversão de polaridade |
| 3–26 | 0–23 | 60 | Entrada `numid − 2`, de 1 a 24 |
| 27–50 | 24–47 | 61 | Entrada `numid − 26`, de 1 a 24 |
| 51 | 0 | 41 | 2, validade do clock interno |
| 52 | 0 | 44 | 2, validade do clock óptico 1 |
| 53 | 0 | 45 | 2, validade do clock óptico 2 |
| 54 | 0 | 40 | 1, seleção de clock |

Para uma entrada `S` entre 1 e 24, o Mixer 60 usa índice `S − 1` e numid
`S + 2`; o Mixer 61 usa índice `S + 23` e numid `S + 26`. Esses vínculos foram
observados nesta coleta, não são numids universais para a EVO 16. Os 48
controles compartilham o nome `Analogue 5 Volume`; ele não identifica sozinho
uma entrada ou saída física. A correspondência com canais físicos segue
pendente.

## Primeira leitura de ganho recebida

O usuário executou `amixer -c 1 cget numid=1`. O ALSA retornou
`type=INTEGER`, `access=rw------`, 16 valores, mínimo 0, máximo 1 e passo 0.
Todas as 16 posições retornaram zero. A leitura foi do controle padrão FU11
identificado acima; ela não executou ajustes.

A faixa 0–1 oferece apenas dois valores inteiros e não valida uma escala
utilizável de ganho. A causa dessa faixa ainda é desconhecida: a saída não
demonstra falha de GET_RANGE, defeito de firmware ou escala em dB. O zero não
prova ganho físico zero nem mute. A capacidade de escrita indicada por
`rw------` também não valida o efeito de escrever.

O controlador permite observar esse controle, mas marca o ajuste como
bloqueado com `adjustment_block_reason="gain_range_not_validated"`; `plan-set`
e `set` recusam o ganho nessa faixa. Matrizes permanecem com escrita bloqueada.

## Primeira leitura de fase recebida

O usuário também executou `amixer -c 1 cget numid=2`, identificado como
`Phase Inverter Control` de FU11. O ALSA retornou `type=BOOLEAN`,
`access=rw------`, 16 valores e todas as posições `off`. Esse retorno registra
o estado informado pelo ALSA; não comprova polaridade física ou efeito de
um ajuste. Nenhum valor foi escrito. O controle de fase é tratado
separadamente da faixa 0–1 de ganho não validada.

A continuidade do áudio durante as leituras ainda não foi informada. Elas
têm os [limites do driver e do cache ALSA](usb-risks.md), e o controlador nativo
ainda não foi executado com a EVO física nesta sessão. Com ele instalado e a
placa ainda em `card1`, o [primeiro teste seletivo](terminal-controls.md) pode
observar `evolinux status --card 1 --control 1 --json`, registrando também a
continuidade da reprodução ou gravação já em uso. Valores/faixas de matrizes
e os efeitos físicos dos controles continuam pendentes. Não é necessário repetir
as coletas de metadados se a placa e sua configuração não mudaram.
