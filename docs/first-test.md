# Primeiro teste no Ubuntu 24.04.4

Estes passos verificam os pré-requisitos e permitem observar a leitura ALSA
durante o uso normal do áudio. O diagnóstico não confirma sozinho que o mixer
está completo nem que o áudio permanece contínuo: isso exige observação no seu
Ubuntu com a EVO 16 conectada.

## Verificação inicial sem abrir controles

Após seguir [o instalador por usuário](ubuntu-installer.md), execute:

```bash
"$HOME/.local/bin/evolinux" doctor --json
```

O modo padrão verifica Python 3.10 ou superior, o carregamento de
`libasound.so.2`, a distribuição e os metadados da EVO 16 publicados pelo kernel
em `/proc/asound`. Também consulta o estado de PipeWire e WirePlumber com
`systemctl --user is-active`, com timeout de dois segundos por serviço. Ele não
abre dispositivos ALSA CTL ou PCM, não envia pedidos USB e não inicia, para ou
reinicia serviços. A presença de Tkinter e de uma sessão gráfica é opcional para
o terminal; nenhum processo Tk é aberto pelo diagnóstico.

O resultado `software_prerequisites: "ready"` significa apenas que Python e
libasound estão disponíveis. `status: "warnings"` pode indicar serviços
inativos, outra distribuição ou metadados ausentes. A EVO pode ser utilizada
pelo ALSA mesmo se PipeWire não estiver ativo. `status: "failed"` indica um
pré-requisito obrigatório ausente. Erros de leitura preservam o número `errno`
quando ele existe; valores indisponíveis não são substituídos por zero.

O Ubuntu 24.04.4 identifica sua família em `/etc/os-release` como
`VERSION_ID="24.04"`. O diagnóstico aceita essa família e não bloqueia o uso
por uma versão diferente do kernel. Nomes de usuário, host, identificação de
placa, cabeçalhos e números de série não entram no relatório.

## Observar a leitura com áudio em funcionamento

Mantenha sua reprodução ou gravação habitual ativa e execute uma vez:

```bash
"$HOME/.local/bin/evolinux" status --json
```

Esse comando abre somente ALSA CTL em modo de leitura; não abre PCM, não toma a
interface USB do driver e não reinicia PipeWire. Confira se o áudio continua
normal durante a leitura. Observe tanto a reprodução quanto a gravação que
realmente utiliza. Se houver interrupção, anote o comportamento e o resultado
JSON antes de repetir o teste.

Uma inspeção equivalente pode ser anexada ao diagnóstico com:

```bash
"$HOME/.local/bin/evolinux" doctor --json --controls
```

`--controls` é opcional e altera o comportamento: abre a sessão ALSA CTL pelo
backend de leitura. A operação não chama o método de escrita do controlador.
Porém, o driver do kernel pode enviar comandos internos ao inicializar um
controle; em alguns caminhos ele aplica um valor mínimo se uma leitura USB
falha. Consulte [os riscos USB e ALSA](usb-risks.md) antes da validação física.

Em um checkout de desenvolvimento, os mesmos comandos ficam em
`.venv/bin/evolinux`. Para limitar uma leitura posterior, use `status --card N`
e opcionalmente `--control ID`, substituindo N e ID pelos números reais da
placa e do controle que deseja conferir. Essa seleção não lê os valores dos
demais controles.

O relatório inclui apenas controles identificados pelo kernel e seus valores
reais quando a leitura é bem-sucedida. `partial`, `unavailable` ou uma lista
vazia não demonstram funcionamento do mixer. O relatório do comando `doctor`
omite os nomes dos controles, mantendo números ALSA, unidades, seletores e
valores para análise sem exportar textos de identificação arbitrários.

## Informações úteis para continuar

O relatório também identifica a versão do kernel sem ler o nome do computador.
Guarde os resultados de `doctor --json` e, após observar o áudio, de
`status --json`, junto com uma descrição de eventuais interrupções. Execute os
comandos como seu usuário da sessão gráfica. Se ocorrer `EACCES`, investigue o
acesso existente à placa; não rode o aplicativo inteiro como root nem aplique
permissões globais aos dispositivos.

Esta primeira etapa não executa ajustes de ganho, fase, phantom, roteamento,
clock ou matrizes. Não carrega módulos experimentais nem utiliza DFU. Os
comandos de pesquisa USB continuam sujeitos a validação e autorização
específica conforme [a documentação de riscos](usb-risks.md).
