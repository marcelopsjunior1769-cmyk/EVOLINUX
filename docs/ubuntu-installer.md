# Instalação por usuário no Ubuntu 24.04.4

O instalador usa os fontes **já disponíveis localmente**. Ele não depende de um
clone novo nem da publicação pendente no GitHub. Execute-o na raiz do checkout
preservado ou do pacote de fontes extraído. O alvo é Ubuntu 24.04; o kernel
informado `7.0.0-38-generic` não requer um módulo adicional para este controlador.

## Verificar os requisitos

```bash
bash tools/install-ubuntu.sh --check
```

Essa opção apenas verifica Python 3.10 ou superior, `venv`/`ensurepip` e a
possibilidade de carregar `libasound.so.2`. Não instala pacotes, cria um ambiente
virtual nem abre uma placa ALSA. Um sistema diferente do Ubuntu 24.04 produz um
aviso, sem impedir a verificação dos requisitos. O resultado é 0 quando os
requisitos estão disponíveis e 1 quando falta algum requisito.

Se faltar um requisito, o instalador imprime os comandos para executá-los
**manualmente** no Ubuntu:

```bash
sudo apt update
sudo apt install python3 python3-venv libasound2t64
```

O instalador não chama `sudo`, `apt` ou `apt-get`. A instalação normal é pelo
terminal; não exige Tkinter nem uma sessão gráfica.

## Instalar a cópia local

```bash
bash tools/install-ubuntu.sh
"$HOME/.local/bin/evolinux" --help
```

Não execute o instalador com `sudo`: o destino pertence ao usuário da sessão.
Ele cria uma instalação isolada em:

```text
${XDG_DATA_HOME:-$HOME/.local/share}/evolinux/releases/install-XXXXXXXX/
```

Cada instalação recebe um caminho novo. O ambiente virtual permanece nesse
caminho para preservar os caminhos absolutos de seus executáveis. O comando
`$HOME/.local/bin/evolinux` é um lançador pequeno que aponta para a instalação
concluída. Use o caminho completo acima se `~/.local/bin` ainda não estiver no
`PATH` da sessão.

Os fontes necessários à construção do pacote são copiados para uma pasta
temporária dentro da nova instalação. O `pip` constrói e instala o pacote a
partir dessa cópia, evitando criar `build/` ou metadados de pacote no checkout.
A cópia é removida depois da instalação. São incluídos apenas o pacote Python,
seus metadados e licenças; o instalador Windows, binários proprietários e o módulo
de pesquisa não fazem parte do runtime instalado.

O `pip` pode baixar dependências de construção, incluindo `setuptools`, pelo
canal HTTPS configurado no ambiente Python. Uma falha de rede ou construção não
substitui o lançador da instalação anterior. O cache do pip fica desativado para
essa operação. Não há instalação editável: mudanças
posteriores no checkout só chegam ao runtime ao executar o instalador novamente.

Antes de ativar o novo lançador, o instalador executa apenas `evolinux --help`.
Ele não executa `status`, `set`, `doctor`, comandos USB, `modprobe`, `insmod` nem
operações no PipeWire. O funcionamento físico continua dependendo da validação
na EVO 16 conectada ao seu Ubuntu.

## Usar e diagnosticar pelo terminal

```bash
"$HOME/.local/bin/evolinux" doctor --json
"$HOME/.local/bin/evolinux" status --json
```

O diagnóstico ajuda a verificar o ambiente. O comando `status` lê os controles
ALSA e deve ser testado com o áudio em funcionamento. Uma leitura pelo ALSA não
é uma garantia de ausência de transferências USB do próprio driver: consulte
[os riscos e limites da validação](usb-risks.md). Ajustes exigem autorização
explícita do comando `set`; este instalador não os executa.

## Atualizar preservando a instalação anterior

Depois de revisar alterações nos fontes, execute novamente:

```bash
bash tools/install-ubuntu.sh
```

As instalações anteriores permanecem em `releases/`. Falhas de criação do
ambiente, instalação do pacote ou execução da ajuda removem apenas a nova
instalação incompleta. O lançador anterior é preservado. O novo lançador é
ativado por uma substituição atômica somente depois das verificações.

Se o processo falhar ou for interrompido depois dessa substituição, a limpeza
reconhece o identificador da instalação no lançador e preserva o executável
ativo. Nesse caso, a ausência da mensagem final não implica que a versão antiga
continua selecionada: confira o lançador e seu `installation.json`.

Se `~/.local/bin/evolinux` já existir e não contiver a identificação do instalador,
a operação é recusada. Links simbólicos nesse caminho também são preservados.
Não mova ou substitua um programa existente sem verificar sua origem.

Cada instalação guarda `installation.json`, com os caminhos do lançador e do
executável. Para usar temporariamente uma versão anterior, execute o
`venv/bin/evolinux` dessa versão diretamente. Não mova ambientes virtuais entre
pastas. Evite executar duas instalações simultaneamente.

## Remover somente o lançador gerenciado

Confira sua identificação antes de removê-lo:

```bash
grep -Fx '# EVOLINUX managed user launcher v1' "$HOME/.local/bin/evolinux"
```

Se a identificação estiver presente e o arquivo corresponder à instalação que
você deseja remover:

```bash
rm -- "$HOME/.local/bin/evolinux"
```

As instalações anteriores permanecem disponíveis. Liste os caminhos em
`releases/`, confira `installation.json` e remova apenas a instalação desejada
depois de preservar qualquer arquivo seu. O instalador não modifica regras
udev, grupos, permissões de dispositivos, serviços ou firmware; não é necessário
reverter esses itens para desinstalar.

## Verificação de desenvolvimento fora do Ubuntu

Em outro Linux, a instalação normal é recusada depois de conferir os requisitos.
A opção abaixo permite testar o empacotamento em diretórios de usuário
temporários; ela não comprova compatibilidade física com o Ubuntu ou com a EVO:

```bash
evolinux_test_prefix=$(mktemp -d)
bash tools/install-ubuntu.sh --allow-unsupported --prefix "$evolinux_test_prefix"
"$evolinux_test_prefix/bin/evolinux" --help
```

`--prefix DIRETORIO` instala em `DIRETORIO/bin` e
`DIRETORIO/share/evolinux/releases`, sem alterar `HOME`. O diretório deve ser
absoluto. Também é possível usá-lo no Ubuntu para escolher outro destino de
usuário. O destino padrão continua sendo o da sessão do usuário.

Os testes automatizados usam destinos descartáveis e comandos Python/pip simulados.
Eles verificam isolamento do checkout, recusa de colisões, preservação de versões
anteriores, falhas de instalação e caminhos com espaços e caracteres de shell.
Não usam hardware nem executam a instalação de pacotes do sistema.
