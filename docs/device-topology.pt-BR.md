# EVO 16 — interpretação do trecho USB enviado pelo usuário

Sistema informado: Ubuntu 24.04.4 LTS (Noble). Fonte dos dados: texto de `lsusb -v -d 2708:000a` enviado no chat; o cabeçalho do dispositivo está ausente. Nenhuma transferência USB foi executada nesta análise.

## Resultado que muda o próximo passo

O trecho expõe ganho e inversão de polaridade no Feature Unit 11 e duas matrizes de mixer, 60 e 61. Os avisos de “Junk at end of descriptor” e os campos `bmControls=0xff` / `iMixer=255` dessas matrizes são explicados pelo decodificador do `lsusb`, não demonstram firmware danificado. Isto identifica controles candidatos para o controlador nativo Linux; não prova correspondência física nem operação contínua com ALSA/PipeWire. A investigação histórica de DLL substituta/Wine também não produziu um aplicativo funcional.

Uma coleta posterior de `/proc/asound/card1/usbmixer`, no kernel informado
`7.0.0-38-generic`, publicou 16 posições ALSA por controle de ganho/fase FU11
e matrizes com entradas 1–24, mantendo 6/4 saídas. Isso corresponde a um
subconjunto dos 24 canais FU11 e das 34 entradas de matriz anunciados abaixo.
O [perfil ALSA observado](observed-alsa-profile.md) registra esses limites e
as informações que ainda faltam; nenhum valor ou ajuste foi obtido nessa coleta.

As linhas `Control:` fornecidas depois confirmaram o vínculo ALSA: ganho/fase
FU11 em numids 1/2; entradas 1–24 do Mixer 60 em numids 3–26, índices 0–23;
entradas 1–24 do Mixer 61 em numids 27–50, índices 24–47. Todos os controles de
matriz se chamam `Analogue 5 Volume`, sem comprovar canais físicos. Uma leitura
separada por `amixer` retornou o ganho FU11 INTEGER com 16 valores zero, faixa
0–1 e passo 0. Isso ainda não valida a escala ou o efeito de ganho; sua causa
permanece desconhecida e o controlador bloqueia ajustes nessa faixa.
Outra leitura por `amixer` retornou o controle de fase FU11 BOOLEAN com 16
posições `off`, sem ajuste ou validação de polaridade física. A continuidade
do áudio durante as leituras não foi informada.

## Matrizes 60 e 61: reconstrução dos campos

O layout UAC2 Mixer Unit (seção 4.7.2.6, tabela 4-11, citada pelo usbutils) é:

`bLength, bDescriptorType, bDescriptorSubtype, bUnitID, bNrInPins, baSourceID[p], bNrChannels, bmChannelConfig[4], iChannelNames, bmMixerControls[n], bmControls, iMixer`

Seu comprimento é `13 + p + n`; `n = ceil(total_de_canais_de_entrada × canais_de_saída / 8)`. Um pino de entrada pode transportar vários canais: não se deve substituir a soma de canais por `bNrInPins`. Aqui ambos os mixers têm um pino vindo da Extension Unit 50, que declara 34 canais.

| Campo | Unit 60 | Unit 61 |
| --- | --- | --- |
| Comprimento anunciado | 40 | 31 |
| Pinos / origem | 1 / Unit 50 | 1 / Unit 50 |
| Canais de entrada segundo origem | 34 | 34 |
| Canais de saída | 6 | 4 |
| Bits de matriz necessários | 204 | 136 |
| Bytes de matriz necessários | 26 | 17 |
| Comprimento esperado | `13+1+26=40` | `13+1+17=31` |
| Aviso do `lsusb` | 25 bytes restantes | 16 bytes restantes |
| Final real reconstruído | `bmControls=0`, `iMixer=0` | `bmControls=0`, `iMixer=0` |

A matriz começa no byte de offset 12 (offsets a partir de zero) em ambos os descritores. No Unit 60 ocupa offsets 12–37, seguido de `bmControls` em 38 e `iMixer` em 39. No Unit 61 ocupa offsets 12–28, seguido de `bmControls` em 29 e `iMixer` em 30. O texto contém `ff` para todos os bytes da matriz, incluindo bits excedentes ao número de pontos do Unit 60, e `00 00` nos dois últimos bytes. A disponibilidade anunciada não substitui uma leitura bem-sucedida dos controles nem valida a semântica de canais físicos.

O usbutils v017 configura `bmMixerControls` com tamanho derivado de `bNrInPins × bNrChannels`, ou seja, 6 ou 4 bits neste caso: apenas um byte. Depois lê outros dois bytes da matriz como `bmControls` e `iMixer`, exibindo `ff`, `ff` e deixando 25 ou 16 bytes. O v017 também tem uma falha de precedência em `entries = (entries / 8) + (entries & 0x7) ? 1 : 0`, que produz um byte para qualquer contagem não nula; o master consultado corrige os parênteses, mas mantém o cálculo baseado em pinos. Não foi informada a versão do usbutils instalada no computador; a saída é consistente com esse erro de layout.

O kernel Linux usa a soma dos canais nas fontes e calcula `(num_ins*num_outs+7)/8`; os acessores leem `iMixer` no último byte do descritor. Assim, esses avisos do utilitário não estabelecem um erro de parsing do driver de áudio do kernel.

## Confirmado pelo descritor versus ainda desconhecido

| Entidade | Confirmado pelo trecho | Ainda não confirmado |
| --- | --- | --- |
| Feature Unit 11 | Fonte 1; 24 canais; master sem controle. `0x03300000` significa ganho de entrada (selector `0x0b`, bits 21:20=`11`) e inversão de polaridade (`0x0d`, bits 25:24=`11`), ambos anunciados como leitura/escrita por canal. | Resposta real a GET_CUR / RANGE; escala e limites de ganho; quais canais correspondem aos oito pré-amplificadores físicos. |
| Extension Units 58 e 62 | Fonte 1, respectivamente 24 e 1 canais; extension code 0; `bmControls=0`. | Não há identificação de phantom power, Smartgain, nomes, medidores ou controles proprietários a partir disso. Não adivinhar selectors. |
| Extension Unit 50 | Fontes 2 e 1; saída declarada com 34 canais; alimenta os mixers 60 e 61. | Ordem exata dos 34 canais; razão da redução/composição a partir das fontes; protocolo de roteamento. |
| Extension Units 51 e 52 | Seis fontes cada; 51: `[11,1,12,13,55,54]`, saída com 28 canais; 52: `[11,2,12,13,55,54]`, saída com 24 canais. | A semântica das rotas e de seus comandos específicos. |
| Extension Units 55 e 54 | Fontes 12 e 13; 55: código 2 e 5 canais; 54: código 1 e 6 canais; controles anunciados zero. | Não equiparar esses códigos a uma função da interface sem evidência do executável/protocolo. |
| Feature Units 10, 12 e 13 | Nenhum controle anunciado nos canais mostrados. | Não usar o selector padrão de volume nessas entidades apenas porque existem Feature Units. |
| Clocks 40, 41, 44 e 45 | Selector 40 entre três clocks; frequência/validade nos sources 41,44,45. | Taxa ativa, source ativo, limites reais, validade externa. |
| AudioControl interface 0 | UAC2 (`bcdADC=2.00`); endpoint de interrupção IN `0x82`, máximo seis bytes. | Notificações proprietárias ou disponibilidade do endpoint enquanto o kernel mantém a interface. |
| AudioStreaming | Interfaces 1 e 2, 24 canais, PCM 24 bits em subslot de três bytes no alternate setting exibido. | Não significa 24 pré-amplificadores; não estabelece taxas ativas nem toda a configuração do dispositivo. |

O `iChannelNames=255 (error)` da Extension Unit 58 é distinto do `iMixer=255` dos mixers. O layout fixo da Extension Unit de 16 bytes está alinhado: o índice 255 ali é efetivamente anunciado, mas a leitura da string falhou. Sem captura bruta/retorno da requisição não se pode distinguir string inexistente, indisponibilidade ou erro na leitura. Isso não altera o tamanho das matrizes.

## Leituras padrão úteis para a camada de compatibilidade

Sem assumir sucesso do firmware: na interface AudioControl 0, uma leitura UAC2 CUR usa `bmRequestType=0xa1`, `bRequest=1`, `wIndex=(entity_id<<8)|0`. Para ganho do Unit 11: `wValue=(0x0b<<8)|canal`, tamanho dois bytes; para polaridade: `wValue=(0x0d<<8)|canal`, tamanho um byte. O pedido RANGE tem `bRequest=2` e pode confirmar limites de ganho.

Para matrizes, a implementação ALSA usa o canal de entrada (base 1) no byte alto de `wValue` e o de saída (base 1) no baixo; `wIndex` contém a entidade 60 ou 61. Valor atual é signed 16-bit (1/256 dB). Isso é diferente de inventar um selector de volume `0x02` para cada ponto da matriz. Números de canal precisam vir do descritor e do mapeamento identificado no aplicativo.

O dispositivo DFU na interface 3 é de atualização de firmware, não deve participar desta coleta ou da adaptação inicial. O próximo dado útil é uma coleta somente de leitura dos valores/ranges e do estado ALSA, preservando o áudio existente, para comparar com o que a DLL original espera.

## Fontes consultadas

- [usbutils v017, `desc-defs.c`](https://github.com/gregkh/usbutils/blob/v017/desc-defs.c): layouts UAC2 de Mixer/Extension Units e os nomes dos controles de Feature Unit.
- [usbutils v017, `desc-dump.c`](https://github.com/gregkh/usbutils/blob/v017/desc-dump.c): cálculo do comprimento de arrays e falha de precedência.
- [usbutils master, `desc-defs.c`](https://github.com/gregkh/usbutils/blob/master/desc-defs.c) e [`desc-dump.c`](https://github.com/gregkh/usbutils/blob/master/desc-dump.c): cálculo baseado em pinos persiste no snapshot consultado; arredondamento foi corrigido.
- [Linux, `include/uapi/linux/usb/audio.h`](https://github.com/torvalds/linux/blob/master/include/uapi/linux/usb/audio.h): acessores UAC2 para bitmap e `iMixer` (equivalente também inspecionado nos headers instalados).
- [Linux, `include/linux/usb/audio-v2.h`](https://github.com/torvalds/linux/blob/master/include/linux/usb/audio-v2.h): selectors `UAC2_FU_INPUT_GAIN=0x0b` e `UAC2_FU_PHASE_INVERTER=0x0d`.
- [Linux, `sound/usb/mixer.c`](https://github.com/torvalds/linux/blob/master/sound/usb/mixer.c): `mixer_bitmap_overflow`, `parse_audio_mixer_unit`, `build_mixer_unit_ctl`, `get_ctl_value_v2`.

O download direto da especificação USB-IF retornou HTTP 403 nesta máquina; a análise de layout acima foi corroborada pelos projetos públicos citados, sem afirmar inspeção direta desse PDF.
