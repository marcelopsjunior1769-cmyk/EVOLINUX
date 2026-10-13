# Backend ALSA nativo do EVO 16

`evolinux.alsa.NativeAlsaBackend` usa `ctypes` e a biblioteca real
`libasound.so.2`. O caminho normal consulta a API **CTL** do ALSA com a sessão
aberta em `SND_CTL_READONLY`. Não abre PCM, não muda a configuração de áudio
do PipeWire e não faz detach, claim, reset, carga de módulos ou comunicação
USB direta. O dispositivo físico não estava conectado durante a implementação;
a leitura e os ajustes no Ubuntu 24.04.4 ainda precisam de validação local.

## Descoberta e valores

A descoberta exige `/proc/asound/cardN/usbid` igual a `2708:000a`. O arquivo
`usbmixer` desse card fornece a relação entre unidade USB, nome/índice ALSA,
selector, máscara e contagem de canais. O backend considera somente a interface
de controle 0 e as unidades 11, 60 e 61; não consulta valores dos demais
controles. Um mapeamento incompleto, ambíguo ou incompatível produz um erro
explícito. O modo `ctlerr=1`, que pode esconder falhas no driver, é recusado.

O snapshot retorna `status`, `cards` e `errors`:

| Status | Significado |
| --- | --- |
| `unavailable` | `/proc/asound` ou a biblioteca nativa não está disponível, ou a descoberta falhou. |
| `absent` | A descoberta foi concluída e nenhum card identificado como EVO 16 foi encontrado. |
| `found` | Os controles mapeados foram encontrados e suas leituras concluídas. |
| `partial` | O card foi identificado, mas alguma leitura ou validação falhou. |

Cada controle inclui `id`/`numid`, `name`, `index`, `unit`, `selector`,
`channel_mask`, `channel_numbers`, `count`, `value_type`, `values`,
`minimum`, `maximum`, `step`, `readable`, `writable`, `active`, `locked`,
`owner` e `adjustable`. Uma leitura que falha deixa `values` em `null`; não
apresenta zeros como se viessem do dispositivo. Os erros preservam `errno`.
Nomes e identificação do card presentes no cabeçalho de `usbmixer` não são
incluídos no resultado.

Os valores inteiros são as posições normalizadas do controle ALSA, não os
valores USB signed16 nem dB. Este backend não converte esses números em dB.
`step=0` no ALSA admite posições inteiras sem um passo fixo adicional.

O descritor FU11 declara 24 canais. Drivers com o limite de 16 canais podem
informar `cmask=0xffffff` e `channels=16`; drivers mais novos podem expor 24.
O backend exige a contagem ALSA correspondente e informa os canais efetivos
em `channel_numbers`, com números USB iniciando em 1. A posição da lista de
valores e `channel_index` da API iniciam em 0. Esses números não identificam,
por si, quais canais correspondem aos oito pré-amplificadores físicos.

## Ajustes explícitos

`set_value(card_number, numid, channel_index, value, authorized=False)` recusa
qualquer escrita por padrão, antes de abrir o card. A autorização precisa ser
literalmente `True`. O chamador deve obtê-la do usuário antes de executar um
ajuste manual; disponibilizar a função não autoriza testes de escrita.

Somente o ganho de entrada FU11/selector `0x0b` e a inversão de polaridade
FU11/selector `0x0d` podem ser ajustáveis. Nome/índice, interface, unidade,
tipo, máscara, quantidade de canais, acesso, faixa e passo precisam ser
compatíveis. Controles de matriz 60/61 ficam somente para leitura. Não há
escrita para phantom power, Smartgain, roteamento privado ou firmware.

A operação usa a identidade completa do controle, mantém um lock ALSA durante
a leitura/alteração e revalida identificação USB, mapeamento e metadados antes
da escrita. Os demais valores são preservados. Após escrever, uma leitura
ALSA precisa confirmar o array solicitado; ausência de confirmação produz
erro, sem relatar o ajuste como aplicado. Essa confirmação reflete o estado
ALSA, que pode usar o cache do driver, e não comprova uma nova medição física.
O lock impede escritas concorrentes de outros clientes CTL, mas não torna
operações externas ao ALSA atomicamente coordenadas.

O aplicativo não chama a API de escrita durante snapshots. Há uma limitação
do próprio `snd-usb-audio`: versões do kernel podem tentar inicializar um
controle com `SET_CUR` mínimo se uma leitura de inicialização `GET_CUR` falhar
no caminho INFO. Abrir CTL em modo de leitura não altera esse comportamento
interno do kernel. Isso exige cuidado com um dispositivo ou driver em falha;
não é um teste USB implementado pelo aplicativo.

## Validação sem hardware

```sh
cd EVOLINUX
PYTHONPATH=src python3 -m unittest discover -s tests -p test_alsa.py -v
```

Os testes usam arquivos de `/proc/asound` simulados e uma biblioteca nativa
simulada. Cobrem identificação, limite de valores, errno, liberação de memória,
hotplug/reutilização de identidade, recusa padrão, faixas e passos, preservação
dos outros canais, locks e leitura de confirmação. Não acessam um dispositivo
de som. O carregamento e os alocadores da `libasound.so.2` instalada podem ser
verificados separadamente sem abrir CTL ou PCM.
