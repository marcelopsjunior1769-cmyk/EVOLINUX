# Contribuição e publicação

Use o checkout existente. Preserve os binários anexados e as notas anteriores;
os arquivos proprietários e os relatórios de hardware ficam fora do Git.

## Verificações antes de uma contribuição

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/evolinux --help
```

Os testes usam fixtures temporárias e mocks de ioctl/ALSA. Acrescente testes que
detectem erros de identidade, canal, limite, tamanho e estado; não crie um modo
demo que transforme ausência de hardware em uma leitura bem-sucedida.

Documente o modelo, fonte e nível de evidência de cada comando. Testes privados
no equipamento exigem autorização específica. Não acrescente detach, reset,
claim, DFU ou mudanças de clock ao caminho padrão para contornar um erro.

O workflow `.github/workflows/tests.yml` testa software em Ubuntu 24.04 com
Python 3.10/3.12. Ele não comprova hardware nem continuidade do PipeWire.

## Preparação de distribuição

```bash
.venv/bin/python -m pip install build
.venv/bin/python -m build
```

Confira o conteúdo de `dist/`: o sdist inclui fontes Python, módulo, contrato
ioctl, documentação e testes. O wheel instala o runtime Python; o módulo
experimental não é instalado ou carregado pelo pip. Não distribua `.ko` de
outro kernel, instaladores Windows, dumps reais ou credenciais junto do pacote.

## Publicação no GitHub

Esta preparação não envia commits ou arquivos ao GitHub. Antes do envio:

1. Revise `git status` e as licenças/atribuições.
2. Inclua os arquivos de fonte e confirme que os artefatos ignorados ficaram fora.
3. Faça o commit e envie à branch desejada usando sua autenticação existente.
4. Aguarde o workflow e publique uma release somente com os limites da versão
   alfa e da validação física explicitados.

Os binários do fabricante foram usados para análise local. Referências à API
Windows e o protótipo `research/wine_broker.py` foram preservados como histórico;
não fazem parte do runtime nativo atual.
