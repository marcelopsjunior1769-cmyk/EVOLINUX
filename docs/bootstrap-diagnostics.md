# Diagnóstico inicial sem baixar o projeto

Este primeiro passo pode ser executado diretamente no terminal do Ubuntu
24.04.4, mesmo enquanto o download dos fontes estiver indisponível. Não exige
instalação, bibliotecas adicionais, `sudo` nem módulos experimentais. Ele lê
somente os metadados que o driver de áudio já publicou em `/proc/asound`;
não abre ALSA CTL ou PCM, não altera serviços e não executa comandos USB de
controle.

Com a EVO 16 conectada, copie este bloco inteiro para o terminal:

```bash
for evo_card in /proc/asound/card[0-9]*; do
    [ "$(cat "$evo_card/usbid" 2>/dev/null)" = "2708:000a" ] || continue
    printf '%s\n' "${evo_card##*/}"
    sed -n '/^USB Mixer:/p;/^[[:space:]]*Unit:/p;/^[[:space:]]*Info:/p' "$evo_card/usbmixer"
done
```

Compartilhe a saída textual para a análise dos controles expostos pelo seu
kernel. O filtro omite as linhas `Card:` e `Control:`, incluindo nomes de
controles, identificação de placa e números de série presentes nessas linhas.
Não substitua esse filtro por uma cópia do arquivo `usbmixer` inteiro.

## O que os campos permitem verificar

| Campo | Informação |
| --- | --- |
| `cardN` | Número atual da placa no ALSA; pode mudar após reconectar. |
| `USB Mixer:` | Identidade USB, interface de controle (`ctrlif`) e tratamento de erros (`ctlerr`) publicado pelo driver. |
| `Unit:` | Entidade USB à qual o controle pertence. |
| `Info:` | Identificador, seletor (`control`), máscara de canais (`cmask`), contagem efetiva (`channels`) e tipo USB. |

Precisamos desses campos para descobrir se o kernel expõe a Feature Unit 11
e as Mixer Units 60 e 61, e quais limites de canais realmente aplica. Os
seletores de FU11 para ganho e inversão de polaridade são, respectivamente,
`control=11` (`0x0b`) e `control=13` (`0x0d`). Os descritores da EVO 16 declaram
24 canais em FU11, mas a contagem efetiva publicada por versões do driver pode
ser menor. A máscara sozinha não confirma que todos esses canais estão
disponíveis como valores ALSA.

O ganho padrão de FU11 não deve ser confundido com o controle privado da
Extension Unit 58 usado por projetos de referência. A presença de FU11 não
comprova que seu ganho ajuste os oito pré-amplificadores físicos da interface.
Esse efeito precisa ser identificado e validado antes de qualquer ajuste.
As matrizes 60 e 61 também podem ter limitações no que o driver expõe; esta
coleta não lê valores nem verifica a aplicação de uma mixagem.

Uma saída vazia pode significar que a EVO não está conectada ou não apareceu
nesse caminho, que os arquivos não estão acessíveis ao usuário, ou que o
driver publica metadados diferentes. Isso não demonstra defeito no hardware.
Se houver uma mensagem de erro de leitura, compartilhe também essa mensagem;
não aumente permissões nem execute o comando como root para contorná-la.

Após tornar os fontes disponíveis, continue com o
[primeiro teste do controlador](first-test.md). A inspeção ALSA CTL opcional
tem limites diferentes desta coleta de metadados; consulte também os
[riscos USB e ALSA](usb-risks.md) antes de executá-la.

## Verificação deste procedimento

O bloco foi verificado com uma árvore temporária de metadados simulados,
substituindo somente o caminho `/proc/asound` pelo da simulação. A placa com
USB ID diferente foi ignorada. As linhas `USB Mixer:`, `Unit:` e `Info:` da
placa correspondente foram preservadas; nomes de placa, nomes de controles
e números de série colocados em outras linhas não apareceram na saída.
Nenhum dispositivo de áudio foi acessado durante essa verificação. A coleta
no Ubuntu com a EVO física ainda está pendente.
