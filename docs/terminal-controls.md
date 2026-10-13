# Conferir e planejar um ajuste pelo terminal

Comece pelo [diagnóstico sem baixar o projeto](bootstrap-diagnostics.md) se os
fontes ainda não estiverem no Ubuntu. Com o controlador instalado, use
`evolinux doctor --json` e siga o [primeiro teste](first-test.md) para observar
a leitura durante o uso normal do áudio.

## Identificar o controle

`evolinux status` mostra placa, numid, nome, valores, faixa inteira ALSA e
disponibilidade de ajuste. `status --card N --control ID --json` limita a leitura
ao controle escolhido. N e ID devem vir do resultado real; não são números
USB nem devem ser copiados de outro equipamento.

O argumento `--channel` representa a posição 1–N do vetor desse controle ALSA.
Essa posição não identifica automaticamente um dos oito pré-amplificadores
físicos. Valores de ganho são inteiros normalizados do ALSA, não dB. O ganho
padrão FU11 também não equivale comprovadamente ao controle privado EU58.

## Prévia sem escrita pelo aplicativo

Substitua os nomes em maiúsculas pelos números reais conferidos:

```text
evolinux plan-set --card PLACA --control NUMID --channel POSICAO --value VALOR
```

O comando lê apenas o controle selecionado e mostra valor atual, proposto,
faixa e passo. Ele não abre uma sessão gravável, não toma um lock de escrita
nem chama `set_value`. A prévia recusa controles sem correspondência conhecida,
leituras incompletas, posição inválida e valores fora da faixa/passo. Somente
ganho padrão FU11 e inversão de polaridade FU11 são candidatos a ajuste.
Matrizes, clock, phantom, Smartgain e extensões privadas permanecem fora desse
caminho.

Use `--json` para obter `current_value`, `target_value`, `would_change`,
`write_performed: false` e os argumentos do comando manual. `usb_channel` é
informado pelos metadados do kernel, sem comprovar o canal físico. Se o valor
já for o proposto, o terminal não sugere ajuste.

Assim como `status`, a prévia usa ALSA CTL em modo de leitura. Isso não garante
que o próprio driver jamais envie comandos internos de inicialização; consulte
[os limites da leitura ALSA](usb-risks.md). A aplicação não executa uma escrita
durante a prévia.

## Aplicar somente depois da conferência física

Quando houver uma mudança válida, a prévia mostra um comando que inclui
`--authorize-alsa-write` e `--expect-current VALOR_ATUAL`. Ele precisa ser
executado manualmente pelo operador; a prévia não o executa nem agenda.

Antes de usar esse comando, a correspondência entre o controle e o canal físico
precisa estar validada. Se a placa foi reconectada, os numids foram renumerados
ou sua configuração mudou, refaça a identificação e a prévia. O projeto ainda
precisa dessa validação no firmware do usuário.

`--expect-current` compara o valor ALSA informado na última leitura do canal
escolhido, dentro do lock CTL existente e antes de escrever. Uma divergência
retorna `EAGAIN`, sem escrever. O operador deve conferir o estado novamente.
Os outros canais são preservados; a escrita só ocorre se o alvo mudar e uma
leitura posterior precisa confirmar o vetor solicitado.

Essa condição não é uma operação atômica no hardware. A leitura pode refletir
o cache ALSA, e o lock não coordena alterações no painel físico ou fora do ALSA.
Ela não comprova continuidade do áudio nem substitui validação física. A API
antiga e o comando `set` sem `--expect-current` continuam disponíveis, sempre
com autorização explícita; o fluxo recomendado passa pela prévia.
