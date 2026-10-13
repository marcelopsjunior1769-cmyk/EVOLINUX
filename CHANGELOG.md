# Histórico de alterações

## 0.2.0 — uso pelo terminal em preparação

- Instalador por usuário para Ubuntu 24.04, com versões isoladas e preservação
  de lançadores existentes e instalações anteriores.
- `doctor` verifica Python, libasound, kernel, metadados ALSA e serviços de áudio.
  Controles só são abertos com a opção explícita `--controls`.
- `status --card N --control ID` limita leituras ao controle selecionado.
- Saída do terminal informa limites inteiros e disponibilidade de ajuste.
- Primeiro teste físico documentado; acesso USB privado e firmware continuam
  fora do fluxo normal. GUI adiada conforme prioridade do usuário.

## 0.1.0 — em preparação

- Estrutura Python instalável e CLI nativa para ALSA.
- Descoberta, leitura e validação de controles conhecidos da EVO 16.
- Coleta sysfs e transporte UAC2 experimental somente de leitura.
- Módulo compilado para o kernel Ubuntu 7.0.0-38-generic, sem carregamento.
- Testes independentes de hardware e workflow de CI.
- Documentação de instalação, protocolo, riscos e referências MIT.
- Preservação das análises do instalador e da tentativa via Wine.

Nenhuma release foi publicada. Funcionamento físico e convivência com PipeWire
continuam pendentes de validação.
