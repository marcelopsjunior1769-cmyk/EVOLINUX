# Validação de software e distribuição

Verificações realizadas em 12 de outubro de 2026 no ambiente Linux da nuvem,
com Python 3.12.14. A data usa America/Sao_Paulo (UTC−3). Este ambiente não
possui a EVO física nem `/proc/asound`.

## Testes automatizados

### Atualização 0.2.0 para uso pelo terminal

O conjunto completo executou **148 testes, todos aprovados**, sem casos
ignorados. Inclui 26 testes de diagnóstico, 13 do instalador, 29 do backend
ALSA e 9 da CLI, além dos testes anteriores de descritores/protocolo/transporte.
Os testes da nova seleção demonstram que os outros controles não são lidos.
Os do instalador cobrem falhas antes e após a ativação do lançador, colisões,
argumentos com caracteres de shell e preservação das versões existentes.

A instalação completa e atualização foram exercitadas no ambiente Debian da
nuvem com `--allow-unsupported` e prefixo de teste próprio. O lançador e a versão
instalada foram verificados sem abrir uma placa; o diagnóstico real retornou
pré-requisitos disponíveis e avisos esperados de distribuição, serviços e
ausência de hardware. A execução no Ubuntu físico continua pendente.

### Base 0.1.0 preservada

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Resultado: **102 testes executados, 102 aprovados, nenhum ignorado**.

| Arquivo | Testes | Cobertura principal |
| --- | ---: | --- |
| `test_alsa.py` | 26 | Biblioteca nativa simulada, controles, limites, errno, identidade, locks e recusa de escritas |
| `test_cli.py` | 5 | Entrada de comandos, autorização, argumentos e tratamento de falhas |
| `test_devices.py` | 26 | Descritores, configuração ativa, sysfs, mudanças de identidade e privacidade |
| `test_diagnostics.py` | 7 | Descoberta, erros, coleta sem serial e criação privada do relatório |
| `test_probe.py` | 5 | Leituras simuladas, clock, respostas curtas e erros sem valores inventados |
| `test_protocol.py` | 23 | Whitelist, setup USB, limites, endereçamento de mixer e CUR/RANGE |
| `test_readonly.py` | 10 | Layout ioctl, transporte simulado, comprimentos e preservação de errno |

Os testes de comandos e transportes substituem as operações de hardware por
mocks. Nenhum teste acessa USB real, carrega módulo ou escreve em uma placa ALSA.

## Instalação e entrada de comandos

O ambiente virtual foi criado com `python3 -m venv .venv` e o pacote foi
instalado com `pip install -e .`. `evolinux --help` terminou com código 0.
O snapshot real `evolinux status --json` retornou `unavailable`, código 1,
`errno=ENOENT` na descoberta por ausência de `/proc/asound`. Esse resultado
é uma limitação confirmada do ambiente, não evidência de uma EVO operante.

O build Python terminou com sucesso e produziu wheel e sdist. O wheel contém
somente o runtime Python e os avisos de licença; o sdist inclui também testes,
documentação, ferramentas, fontes do módulo e header UAPI.
Instaladores, bibliotecas/driver do fabricante,
relatórios reais, cache, arquivos Git e módulos compilados são excluídos.
O binding e os alocadores da `libasound.so.2` instalada foram verificados
separadamente, sem abrir uma sessão CTL ou PCM.

## Compilação do módulo opcional

| Alvo | Toolchain | Resultado |
| --- | --- | --- |
| Debian `6.12.107+deb13-amd64` | GCC 14, `W=1` | Compilação, MODPOST e link concluídos |
| Ubuntu `7.0.0-38-generic` | GCC 13.3.0, `W=1` | Compilação, MODPOST e link concluídos |

Headers Ubuntu de versão `7.0.0-38.38~24.04.4`, obtidos via índice assinado:

- `linux-headers-7.0.0-38-generic`: SHA-256
  `44e6fa84a94dc7f8efbb85d48822a0030bd1e0e20f3696924f4d86834239931f`.
- `linux-hwe-7.0-headers-7.0.0-38`: SHA-256
  `8806dc00159307a485e7608ed52cc2482b0cdb6211550f55354586afef5e7e5e`.

`CONFIG_DEBUG_INFO_BTF_MODULES=` omitiu somente os metadados BTF de depuração,
por ausência de `pahole`. A divergência de versão dessa ferramenta continua
visível como aviso; não houve erro de compilação. TLS, assinatura do índice e
checksums dos pacotes foram preservados. Nenhum módulo foi instalado/carregado.

## O que esses resultados ainda não validam

- Leitura e ajuste dos controles na EVO com o firmware do usuário.
- Correspondência dos valores ALSA com pré-amplificadores/canais físicos.
- Comunicação privada EU58 e endereçamento efetivo das matrizes.
- Áudio sem interrupção, xruns ou mudanças de estado com ALSA/PipeWire em uso.
- Carregamento/assinatura do módulo com Secure Boot.

O workflow GitHub Actions está configurado para Ubuntu 24.04, Python 3.10/3.12,
testes sem hardware e build do pacote. Não foi executado no GitHub nesta etapa;
Python 3.10 também não foi executado localmente. A preparação não publica o
repositório nem cria release. Consulte [usb-risks.md](usb-risks.md) antes de
planejar qualquer validação física autorizada.
