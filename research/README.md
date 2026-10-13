# Histórico preservado

`wine_broker.py` é uma cópia integral do servidor binário iniciado para estudar
a adaptação do aplicativo Windows. O objetivo passou a ser um controlador
nativo. Esta cópia foi mantida para preservar o trabalho, sem incluí-la no
pacote Python instalado ou apresentá-la como componente concluído.

O arquivo mantém seus imports relativos originais e não é um utilitário de
execução isolada. Não há DLL substituta funcional nem suporte validado ao
aplicativo oficial sob Wine. A API Windows/TUSBAUDIO e as análises de DLL/SYS
continuam documentadas nas notas de [ABI](../docs/tusbaudio-abi.md),
[propriedades](../docs/tusbaudio-properties.md) e
[notificações](../docs/tusbaudio-notifications.md). Os componentes de descoberta
sysfs e o protocolo que permanecem úteis estão em [src/evolinux](../src/evolinux/).

O [histórico do objetivo inicial](../docs/history/original-adaptation.md) e a
[inspeção do instalador](../docs/installer-analysis.pt-BR.md) preservam os
resultados anteriores. Binários proprietários, disassemblies, relatórios locais
e backups do ambiente de pesquisa não são redistribuídos no pacote público.
