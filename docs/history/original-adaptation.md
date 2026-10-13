# Histórico: investigação do aplicativo original EVO

Este documento preserva a descrição da etapa inicial. O objetivo atual é o [controlador nativo EVOLINUX](../../README.md); a implementação Windows/Wine descrita abaixo não foi concluída e não integra o pacote instalado.

Investigação da adaptação do **aplicativo original Audient EVO 16** ao Ubuntu 24.04.

O instalador `EVO-v4.4.0a.exe` foi extraído e analisado estaticamente. O aplicativo
original comunica-se com uma API de driver carregada por DLL. Essa fronteira permite
investigar uma implementação compatível para Wine com comunicação USB no Linux.

**Ainda não há uma versão modificada funcional nem suporte ao mixer validado.**
O código-fonte da Audient não foi fornecido, e a EVO 16 não está conectada ao ambiente
na nuvem. Nenhum aplicativo ou driver Windows foi executado nesta análise.

- [Resultados da análise](../installer-analysis.pt-BR.md)
- [Coleta de informações da interface no Ubuntu](../collect-diagnostics.md)

Os binários enviados pelo usuário e os componentes extraídos ficam fora deste
repositório. Na sessão original foram preservados em `/workspace/attachments`
e `/workspace/evo-analysis`; esses caminhos são registros do ambiente de
pesquisa e não arquivos disponíveis no checkout público. Os binários não são
incluídos em Git nem no pacote de fontes preparado para publicação.
