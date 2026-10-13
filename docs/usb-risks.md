# Riscos e limites dos controles USB

Esta versão é experimental. Nenhum comando USB foi executado na EVO física
durante o desenvolvimento na nuvem. Não execute testes privados no equipamento
sem autorização para a requisição específica e sem validação prévia.

| Caminho/ação | Possível impacto | Tratamento atual |
| --- | --- | --- |
| Coleta de arquivos sysfs | Dados incompletos ou dispositivo removido durante leitura | Somente leitura; erros explícitos; sem serial |
| Leitura de controles ALSA CTL | Comportamento interno do driver, energia e inicialização | API de leitura; não abre PCM; requer teste com áudio contínuo |
| Ganho/fase padrão ALSA | Nível inesperado, clipping, mudança de polaridade ou canal incorreto | Escrita desativada por padrão; autorização por operação e validação de metadados/range/canal |
| Matriz/roteamento | Realimentação, envio a saída errada, perda de monitoração ou som elevado | Escritas não implementadas |
| Phantom 48 V | Alteração elétrica em entradas e equipamentos conectados | Escritas não implementadas; pedidos privados não validados |
| Detach, claim ou reset USB | Interrupção do áudio e remoção da placa ALSA | Não usados pelo controlador |
| Mudança de clock/configuração/alternate setting | Interrupção, dessíncronização e alteração de formato | Não implementada |
| Comando privado IN | Timeout, stall, semântica desconhecida ou efeito inesperado de firmware | Somente pesquisa autorizada, whitelist, limite e resposta real |
| Kernel module experimental | Falha no kernel, bloqueio, desconexão ou incompatibilidade | Opcional, nó 0600, sem carregamento automático; build não comprova segurança física |
| DFU e firmware | Perda de funcionamento ou firmware incompatível | Fora do escopo; nenhum endpoint/comando de atualização |

## Leitura não é garantia absoluta de ausência de alterações

O snapshot abre a API ALSA CTL em modo READONLY e não chama sua função de escrita.
Ainda assim, o kernel é responsável pelo protocolo USB. Algumas versões do
`snd-usb-audio` podem inicializar um controle ou usar SET_CUR de fallback durante
a obtenção de limites quando uma leitura falha. Não se promete que toda chamada
ALSA produza exclusivamente pacotes IN no fio USB.

O módulo próprio restringe o pedido que ele envia a IN/class/interface, mas
usbcore continua responsável por runtime PM e recuperação normal do dispositivo.
Nenhuma dessas verificações prova continuidade do áudio sem teste físico.

## Condições para uma alteração padrão

`plan-set` usa uma leitura seletiva para validar uma proposta, sem abrir sessão
gravável ou chamar a escrita do aplicativo. Ele compartilha os limites da
leitura ALSA descritos acima. O comando sugerido precisa ser executado
manualmente após a correspondência física estar validada.

`--expect-current` recusa o ajuste se o valor ALSA do alvo não for mais o que
foi conferido. Essa condição não é uma comparação atômica no hardware e não
torna a identificação de uma prévia válida após reconexão ou renumeração.
Refaça a prévia quando a placa ou sua configuração mudar.

Antes de qualquer ajuste, confira placa, nome do controle, numid, canais,
valores atuais e faixa. O backend revalida isso no mesmo handle CTL, recusa tipos
ou mapeamentos inconsistentes e conserva as outras posições do vetor. Uma flag
de autorização é intenção do operador; não é prova de correspondência física.

Não use inteiro ALSA como se fosse dB, não replique payload privado de outro
modelo e não deduza suporte apenas de uma resposta USB sem erro. Alterações na
matriz, nos pré-amplificadores privados e em 48 V continuam bloqueadas.

## Validação física futura

Uma sessão autorizada deve registrar revisão do dispositivo, kernel, controles
ALSA, configuração de áudio e resposta da leitura escolhida, mantendo gravação
ou reprodução em andamento. Comece com uma leitura definida e limitada. Se
houver stall, timeout, erro ALSA ou interrupção do áudio, registre a falha e
interrompa a sequência; não substitua o estado por zeros nem repita comandos
sem um diagnóstico novo.

CI e testes locais de software não devem acessar USB real, executar `insmod`,
parar PipeWire ou alterar permissões de dispositivos. Preserve verificação TLS,
assinaturas de pacotes e a política de assinatura de módulos do sistema.
