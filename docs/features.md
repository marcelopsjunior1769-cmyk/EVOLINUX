# Funcionalidades e estado de validação

O alvo é Ubuntu 24.04.4 e EVO 16 `2708:000a`. A identificação do áudio no Ubuntu
foi relatada pelo usuário. O controlador desenvolvido ainda não foi executado
com a interface física nesta sessão.

| Componente/capacidade | Código atual | Validação realizada | Pendência |
| --- | --- | --- | --- |
| Descoberta de placas EVO 16 no ALSA | Implementado | Fixtures e erros de descoberta | Inventário real no Ubuntu |
| Instalador por usuário para terminal | Implementado, sem apt/sudo automático | Instalação isolada e falhas simuladas | Execução no Ubuntu físico |
| Diagnóstico `doctor` | Implementado; padrão apenas metadados | Pré-requisitos, serviços e privacidade simulados | Relatório do Ubuntu do usuário |
| Leitura ALSA das unidades 11/60/61 | Implementado para controles mapeados | Testes de binding e transporte simulado | Controles efetivamente expostos pelo driver |
| Leitura restrita a placa/controle | Implementado com `status --card --control` | Recusa de seleções inválidas e ausência de leituras em outros controles | Numids do firmware do usuário |
| Ganho/fase FU11 pelo ALSA | Caminho de ajuste explícito com limites | Testes simulados; padrão sem escrita | Correspondência física e teste autorizado |
| Prévia e condição do valor atual | `plan-set` e `set --expect-current` implementados | Leitura seletiva, faixa/canal, valores desatualizados e ausência de escrita simulados | Validar canais/estado no hardware; cache ALSA não é medição física |
| Matrizes 60/61 | Leitura quando expostas; escrita bloqueada | Topologia analisada, testes de metadados | Mapear entradas/saídas e validar valores |
| Coletor sysfs | Implementado | Fixtures, privacidade e preservação de arquivos | Relatório completo do hardware |
| CUR/RANGE UAC2 | Builder e decoder implementados | Endereços, limites, dados malformados e erros | Leituras físicas autorizadas |
| Módulo de leituras privadas | Opcional e restrito | Compilação Debian 6.12 e Ubuntu 7.0.0-38; não carregado | Validação de acesso e coexistência |
| EU58 ganho/48 V/mute | Referências e candidatos de leitura | Análise dos projetos; sem hardware | Confirmar firmware, índices e payloads; nenhuma escrita |
| Interface gráfica | Não implementada | Não executada | Projeto e integração com backend |
| Medidores/notificações | Não implementados | Endpoint identificado | Integração sem disputar endpoint 0x82 do ALSA |
| Smartgain, instrumento e roteamento privado | Não implementados | Hipóteses e limites documentados | Captura e validação autorizadas |
| Atualização de firmware/DFU | Fora do escopo | Nenhum comando executado | Não há plano de implementação nesta etapa |
| Áudio contínuo com PipeWire | Arquitetura evita PCM/detach/reset | Revisão do código | Gravação/reprodução real durante uso |

Os valores ALSA inteiros não são automaticamente dB nem valores USB Q8.8. O
ganho padrão FU11 não foi identificado como equivalente ao ganho físico de
pré-amplificador privado EU58. O kernel pode expor somente um subconjunto dos
24 canais anunciados; o aplicativo não inventa os restantes.

O histórico da tentativa de adaptação da interface Windows está preservado nas
notas [TUSBAUDIO](tusbaudio-abi.md) e em [research/](../research/README.md);
ele não integra o runtime nativo. Os [riscos e limites dos comandos](usb-risks.md)
e as [atribuições das referências](references.md) acompanham estas funcionalidades.
