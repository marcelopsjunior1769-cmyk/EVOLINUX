# Comunicação USB e UAC2 da EVO 16

## Identificação e evidência

VID `0x2708`, PID `0x000a`. O trecho de `lsusb` fornecido pelo usuário identifica
AudioControl UAC2 na interface 0 e duas interfaces AudioStreaming, com fluxos de
24 canais PCM/24 bits. A interface 3 anuncia DFU; ela não é usada pelo projeto.
A revisão USB `bcdDevice` não é necessariamente a versão de firmware.

| Entidade | Função observada no descritor |
| --- | --- |
| 40 | Seletor de clock, fontes 41/44/45 |
| 41, 44, 45 | Clock interno, óptico 1 e óptico 2 |
| 11 | Feature Unit: ganho de entrada `0x0b` e fase `0x0d` |
| 58, 62 | Extension Units privadas, sem selectors anunciados em `bmControls` |
| 50 | Cluster intermediário de 34 canais |
| 60 | Mixer de 34 entradas por 6 saídas |
| 61 | Mixer de 34 entradas por 4 saídas |
| 51/52/54/55 | Unidades intermediárias de encaminhamento/seleção |

Existência e geometria não comprovam o efeito físico de um controle ou a
semântica de um comando privado. Veja [a análise dos descritores](device-topology.pt-BR.md).

## Endereçamento padrão

Para leituras class/interface, o setup packet usa `bmRequestType=0xa1`. Em UAC2,
`bRequest=1` é CUR e `2` é RANGE. O campo `wIndex` combina entidade e interface:

```text
wIndex = (unit_id << 8) | audio_control_interface
wValue = (selector << 8) | channel
```

Em Feature Units, master é canal 0 e canais individuais começam em 1. Nas
matrizes padrão, o byte alto corresponde à entrada e o baixo à saída, ambos
começando em 1. A fórmula linear usada pelo evoctl para EVO 8 não foi aplicada
ao EVO 16 como protocolo confirmado.

Os campos de setup e os payloads UAC2 usam little-endian. Ganhos padrão de dois
bytes podem ser signed Q8.8; isso não autoriza converter diretamente valores
normalizados da API ALSA em dB. RANGE contém `wNumSubRanges` seguido dos trios
MIN/MAX/RES; o decoder recusa contagens, comprimentos e intervalos inconsistentes.

## Controle ALSA prioritário

[src/evolinux/alsa.py](../src/evolinux/alsa.py) lê `/proc/asound/card*/usbid` e o mapeamento `usbmixer`,
depois usa a API CTL de `libasound`. Só controles ligados às unidades conhecidas
são considerados. Tipo, quantidade de valores, máscaras, identidade e faixa são
validados; ausência e falhas são expostas como tais.

Esse caminho mantém o driver `snd-usb-audio` responsável pela interface. O
aplicativo não abre PCM nem solicita restart do PipeWire. A atividade interna
USB e a política de energia continuam sendo controladas pelo kernel.

## Referências privadas EU58

No projeto macOS consultado, os candidatos são CS0 phantom, CS1 ganho e CS2
mute, com quatro bytes e índice privado de canal baseado em zero. São diferentes
dos controles padrão FU11. Há divergência no mute ADAT: o código usa FU11 CS2
com quatro bytes, enquanto o resumo do README diz EU58 para todos os canais.
Esses candidatos não foram validados no firmware do usuário.

O módulo de pesquisa só permite leituras CUR/RANGE delimitadas. Ele não oferece
SET_CUR, escrita de firmware, reset, DFU, claim ou detach. A lista completa,
tamanhos e contrato ioctl estão em [kernel/README.md](../kernel/README.md).

## Avisos do decodificador lsusb

Os mixers têm bitmaps de 26 e 17 bytes. O decodificador consultado calcula apenas
um byte usando o número de pinos em vez do número agregado de canais; isso
desloca `bmControls` e `iMixer` e explica os bytes reportados como “Junk”. Os
comprimentos totais 40 e 31 são coerentes. A falha de string índice 255 em EU58
é separada e não foi descartada como esse erro de offsets.

## Procedência

As referências, commits, licenças e divergências estão em
[references.md](references.md). O controlador não assume que aceitação de uma
requisição USB ou eco de um registro comprove mudança física no equipamento.
