# Licenças e atribuições

| Componente | Licença | Texto |
| --- | --- | --- |
| Python em `src/`, `tools/`, `tests/`, pesquisa Python original, documentação e configuração do projeto | GPL-3.0-only | [LICENSE](LICENSE) |
| `kernel/evo16_readonly.c` e `kernel/Makefile` | GPL-2.0-only | [GPL versão 2](LICENSES/GPL-2.0-only.txt) |
| `include/evo16_bridge_uapi.h` | GPL-2.0 WITH Linux-syscall-note | [GPL versão 2](LICENSES/GPL-2.0-only.txt), [exceção](LICENSES/Linux-syscall-note.txt) |
| Avisos dos projetos consultados | MIT, respectivos autores | [evoctl](third_party_licenses/evoctl.txt), [evo16-API-web](third_party_licenses/evo16-API-web.txt) |

A licença declarada no pacote Python é GPL-3.0-only, escolhida pelo responsável
pelo projeto. A distribuição de fontes também inclui o módulo separado sob
GPL-2.0-only; essa declaração não muda a licença dos arquivos com identificador
SPDX próprio. O wheel não instala o módulo. A comunicação entre processos e o
contrato UAPI mantêm os componentes separados; não se incorpora código GPL-2.0
do kernel ao pacote Python.

Os projetos de referência e as revisões consultadas são registrados em
[docs/references.md](docs/references.md). Seus avisos originais são preservados;
referência a um protocolo não transfere autoria do trabalho original.

O instalador, aplicativo, DLLs, drivers, firmware e marcas da Audient não são
relicenciados nem redistribuídos aqui. Audient e EVO pertencem aos respectivos
titulares. O projeto EVOLINUX é independente e não oficial.
