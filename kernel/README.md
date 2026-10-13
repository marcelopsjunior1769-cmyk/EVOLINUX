# Transporte EVO 16 experimental, somente leitura

Este módulo é uma camada de pesquisa para o Ubuntu 24.04.4 LTS. Ainda precisa
ser validado na EVO 16 física; compilar não demonstra que a interface aceita as
requisições nem que o aplicativo Windows funciona. O kernel real pode ser
diferente entre instalações 24.04.4: consulte `uname -r`.

O módulo cria `/dev/evo16-readonly` com modo `0600`. Ele localiza exclusivamente
o dispositivo USB `2708:000a` pelo barramento e endereço informados, confirma a
interface AudioControl UAC2 ativa e envia transferências **IN** ao endpoint zero.
Não se registra como driver USB, não reivindica nem desconecta interfaces e não
envia comandos de reset, configuração, alternate setting, clock ou firmware. O áudio
permanece sob responsabilidade do `snd-usb-audio` existente. Não há código de
instalação automática ou carregamento do módulo.

## Requisições permitidas

| Unidade | Seletor e canal | Requisição |
| --- | --- | --- |
| 40, seletor de clock | seletor 1, canal 0 | CUR, 1 byte |
| 41/44/45, fontes de clock | seletor 1, canal 0 | CUR, 4 bytes; RANGE |
| 41/44/45, validade de clock | seletor 2, canal 0 | CUR, 1 byte |
| 11, ganho de entrada | seletor `0x0b`, canais 1–24 | CUR, 2 bytes; RANGE |
| 11, inversão de fase | seletor `0x0d`, canais 1–24 | CUR, 1 byte; RANGE |
| 58, extensão privada | seletores 0–2, canais 0–23 | CUR, 4 bytes |
| 60, mixer | entrada/seletor 1–34, saída/canal 1–6 | CUR, 2 bytes; RANGE |
| 61, mixer | entrada/seletor 1–34, saída/canal 1–4 | CUR, 2 bytes; RANGE |

RANGE aceita 2–4096 bytes, inclusive a consulta inicial de 2 bytes para contar
subintervalos. O timeout deve ser de 1–10.000 ms. O mapeamento privado da
unidade 58 vem de uma referência externa; seus seletores ainda não foram
confirmados no firmware do usuário. Um controle não implementado ou um stall
USB retorna erro, sem substituir a resposta por dados simulados. A permissão de
uma leitura não confirma a existência do controle, inclusive RANGE para fase.

## Compilação, sem carregar o módulo

Os headers devem corresponder exatamente ao kernel de destino. Com os headers
já disponíveis, execute na raiz do projeto:

```bash
uname -r
make -C kernel KDIR="/lib/modules/$(uname -r)/build"
```

Para uma checagem de compilação em outra máquina, `KDIR` pode apontar para seus
headers; o `.ko` resultante será específico daquele kernel e não deve ser usado
no Ubuntu do usuário. Não há comandos de `insmod`, `modprobe` ou instalação
neste procedimento. Secure Boot pode exigir assinatura confiável do módulo;
sua desativação não faz parte deste projeto.

Na nuvem, o módulo compilou com GCC 14 e `W=1` contra headers Debian
`6.12.107+deb13-amd64`, incluindo resolução dos símbolos por MODPOST. Os headers
extraídos foram acessados pelo Makefile de origem com a opção suportada `-f`.
O pacote tinha um `vmlinux` de referência, mas `pahole` não estava disponível;
usou-se `CONFIG_DEBUG_INFO_BTF_MODULES=` para omitir somente os metadados de
depuração BTF. O módulo não foi carregado.

A compilação também foi concluída contra headers oficiais Ubuntu
`7.0.0-38-generic` (`7.0.0-38.38~24.04.4`), com GCC 13.3 e `W=1`, incluindo
MODPOST e link do módulo. A ausência de `pahole` foi tratada da mesma forma,
omitindo os metadados BTF. Assinaturas dos repositórios e checksums dos pacotes
foram preservados. Este resultado valida a compilação para o alvo informado;
aceitação dos pedidos e continuidade do áudio ainda exigem teste físico
autorizado. Nenhuma compilação foi seguida por carregamento do módulo.

## Contrato e limitações

[O header UAPI](../include/evo16_bridge_uapi.h) define um struct de 4.120 bytes,
sem ponteiros, e `_IOWR(0xe6, 1, ...)`. Campos inteiros usam a ordem de bytes
nativa; o payload USB é devolvido intacto, acompanhado de `actual_length`.
Requisições desconhecidas retornam `ENOTTY`; controles fora da lista retornam
`EOPNOTSUPP`; erros de USB são propagados, incluindo timeout e stall.

As referências de dispositivo/interface e o lock do dispositivo protegem o
acesso à configuração durante desconexão e reconfiguração. Uma referência
temporária de runtime PM evita autosuspend durante a operação; a política de
autosuspend não é desativada. A retomada e eventual recuperação normal do
dispositivo continuam sendo responsabilidade do usbcore. O mutex deste módulo serializa seus próprios
clientes, sem substituir os locks do ALSA ou oferecer um snapshot atômico de
todos os controles. Desconexão física ainda pode interromper qualquer leitura.

O endpoint interrupt `0x82` continua sendo usado pelo ALSA; o módulo não o
consome. Também não oferece controles de escrita, phantom power, Smartgain,
monitoramento por notificações ou atualização de firmware. A interface original
sob Wine e uma DLL compatível com TUSBAUDIO são componentes separados.

Referências de API utilizadas:

- [Linux v6.8: USB device iteration e referências](https://github.com/torvalds/linux/blob/v6.8/drivers/usb/core/usb.c)
- [Linux v6.8: runtime PM e locks USB](https://github.com/torvalds/linux/blob/v6.8/drivers/usb/core/driver.c)
- [Linux v6.8: usb_control_msg](https://github.com/torvalds/linux/blob/v6.8/drivers/usb/core/message.c)
- [Linux v6.8: parser e notificações do mixer ALSA](https://github.com/torvalds/linux/blob/v6.8/sound/usb/mixer.c)
