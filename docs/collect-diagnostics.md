# Diagnóstico da EVO 16 no Ubuntu 24.04

Este diagnóstico identifica a EVO 16 pelo ID USB `2708:000a` usado no driver do instalador fornecido. Ele lê os dados que o kernel já expõe no sysfs. Não abre o dispositivo USB, envia comandos, desconecta drivers ou muda controles da interface.

Com a EVO 16 conectada ao **seu computador Ubuntu**, abra um terminal na pasta do projeto e execute:

```bash
python3 tools/collect_evo16.py --output evo16-diagnostics.json
```

Não precisa de `sudo` nem de pacotes extras. O arquivo `evo16-diagnostics.json` permite analisar a identificação e a topologia expostas pelo kernel local; não é necessário para rodar os testes automatizados. Uma máquina na nuvem não acessa a interface conectada ao seu computador. Também é possível usar `evolinux collect --output evo16-diagnostics.json` depois da [instalação do pacote](installation.md).

O arquivo inclui a versão do kernel, a arquitetura, a revisão USB `bcdDevice`, os descritores USB em hexadecimal e os nomes dos drivers das interfaces. Se disponíveis, também inclui os números das placas ALSA da EVO 16 e os nomes dos controles de mixer que o kernel expõe. Não coleta número de série, nome do computador, nome de usuário nem variáveis de ambiente. A revisão `bcdDevice` não é necessariamente a versão do firmware.

O programa não sobrescreve um relatório existente. Para coletar novamente, escolha outro nome:

```bash
python3 tools/collect_evo16.py --output evo16-diagnostics-2.json
```

O código de saída é `0` quando a EVO foi encontrada sem erros na leitura USB, `2` quando não foi encontrada e `1` quando houve erro. `status` e `read_errors` no JSON diferenciam ausência, sysfs indisponível e falta de permissão. A coleta ALSA é opcional e tem seus próprios campos `status` e `read_errors`; falhas nessa parte não impedem a coleta USB. Se houver várias EVO 16, todas aparecem em `devices`.

Se o dispositivo funcionar no áudio mas não aparecer neste diagnóstico, o ID USB pode ser diferente. Esse resultado deve ser investigado; não é necessário instalar drivers ou executar o programa como administrador para usar o áudio.
