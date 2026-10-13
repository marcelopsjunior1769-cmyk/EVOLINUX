# Referências para controlador nativo EVO 16 no Ubuntu

Revisão estática em 2026-10-12 para o controlador nativo destinado ao Ubuntu 24.04.4, com ALSA/PipeWire contínuo. Os projetos foram clonados por HTTPS e seus arquivos foram inspecionados sem executar seus binários, scripts, testes ou transferências USB. A revisão das referências foi somente de leitura; o desenvolvimento e os testes simulados do EVOLINUX são descritos separadamente. App Windows/Wine e alteração de firmware estão fora do escopo nativo.

## Conclusão prática

Nenhum dos dois projetos é um controlador EVO 16 Linux pronto para este requisito. `evoctl` é nativo Linux, porém filtra EVO 4/8 e desanexa o driver para tomar a interface AudioControl. `evo16-API-web` identifica EVO 16 e contém uma referência útil de controles privados, porém seu transporte é macOS/IOKit. Suas alegações de validação não validam o firmware do dispositivo do usuário nem a coexistência com ALSA/PipeWire no Ubuntu.

Podemos aproveitar documentação e formatos de mensagens como referências com procedência. Não é justificável transplantar os caminhos de detach/claim/reset, a geometria EVO 8, o binding DFU documentado ou os controles experimentais para o controlador nativo.

## Snapshots e licenças

| Projeto | Commit inspecionado | Licença e escopo efetivo |
| --- | --- | --- |
| [soerenbnoergaard/evoctl](https://github.com/soerenbnoergaard/evoctl) | `31cf69905368d4a6f3523e5f9d5e7c00de496b94`, main, 2021-07-23 | [MIT, copyright 2020 soerenbnoergaard](https://github.com/soerenbnoergaard/evoctl/blob/31cf69905368d4a6f3523e5f9d5e7c00de496b94/LICENSE). C++/FLTK/libusb; detecção de `2708:0007` EVO 8 e fallback `2708:0006` EVO 4. Não inclui `2708:000a`. |
| [djenttleman/evo16-API-web](https://github.com/djenttleman/evo16-API-web) | `5b9ebe7cf0057a349407ac24848eec502e30266c`, main, 2026-05-31 | [MIT, copyright 2026 djenttleman](https://github.com/djenttleman/evo16-API-web/blob/5b9ebe7cf0057a349407ac24848eec502e30266c/LICENSE). FastAPI + helper C IOKit; serviço fixa `2708:000a` EVO 16. |

Ambas as licenças permitem reutilização, incluindo redistribuição e modificação, preservando o aviso de copyright e a licença nas cópias/porções substanciais. Isso não substitui as licenças das dependências.

As atribuições e os textos integrais das licenças consultadas acompanham o projeto em [evoctl.txt](../third_party_licenses/evoctl.txt) e [evo16-API-web.txt](../third_party_licenses/evo16-API-web.txt). Os repositórios completos e seus binários não são distribuídos neste pacote; os commits acima permitem reproduzir a consulta. As informações foram usadas como referências de protocolo, sem incorporar os transportes libusb ou IOKit ao backend ALSA.

Essas licenças MIT pertencem aos projetos consultados. O código Python desenvolvido para o EVOLINUX usa GPL-3.0; o módulo de kernel mantém GPL-2.0-only e o header UAPI mantém sua exceção de syscall. A distribuição e os escopos estão descritos em [LICENSING.md](../LICENSING.md).

O remoto web também contém `BACKUP-BEFORE-FORMATTING` em [`3dea20380b12d019a86cf78133b7da6fab3f9822`](https://github.com/djenttleman/evo16-API-web/commit/3dea20380b12d019a86cf78133b7da6fab3f9822), de 2026-09-14. Comparação Git confirma que `README.md`, `LICENSE`, `backend/service.py` e `mac-evo16/mac-evo16.c` são idênticos a main; as diferenças são documentação VST3 e remoção de um arquivo pyc. O relatório usa main como referência reprodutível.

## evoctl: protocolo útil, transporte incompatível

- [Detecção e posse do dispositivo](https://github.com/soerenbnoergaard/evoctl/blob/31cf69905368d4a6f3523e5f9d5e7c00de496b94/src/main.cxx#L9): abre primeiro EVO 8 e depois EVO 4; habilita `libusb_set_auto_detach_kernel_driver(..., 1)`, chama `libusb_claim_interface(..., 0)` e executa `libusb_reset_device()` ao fechar. O [README](https://github.com/soerenbnoergaard/evoctl/blob/31cf69905368d4a6f3523e5f9d5e7c00de496b94/README.md#L15) exige parar JACK e relata que detach/re-attach interrompe seu funcionamento. Isso não atende ao áudio contínuo.
- O [protótipo Python](https://github.com/soerenbnoergaard/evoctl/blob/31cf69905368d4a6f3523e5f9d5e7c00de496b94/tool/evolib.py#L24) também faz detach e claim da interface 0, reset e `set_configuration()`; seu fechamento reanexa o driver. Não é um transporte alternativo sem interrupção.
- A [implementação C++](https://github.com/soerenbnoergaard/evoctl/blob/31cf69905368d4a6f3523e5f9d5e7c00de496b94/src/main.cxx#L57) envia apenas SET_CUR do mixer: `bmRequestType=0x21`, `bRequest=0x01`, `wIndex=0x3c00`, payload signed little-endian Q8.8 de dois bytes. Seu índice de crosspoint é `wValue=0x0100 + 4*entrada + saída`, com entrada 0–9 e saída 0–3. Não realiza GET/readback e não verifica o retorno de `libusb_control_transfer()`.
- A [geometria](https://github.com/soerenbnoergaard/evoctl/blob/31cf69905368d4a6f3523e5f9d5e7c00de496b94/src/settings.h#L6) permanece fixa em 10 entradas × 4 saídas: quatro microfones, quatro DAW e dois loopback. O fallback EVO 4 não muda essa geometria. Ao abrir a GUI, [main chama evo_update()](https://github.com/soerenbnoergaard/evoctl/blob/31cf69905368d4a6f3523e5f9d5e7c00de496b94/src/main.cxx#L172) e escreve a matriz inicial, em vez de recuperar o estado existente: [40 células começam em mute, exceto DAW1→OUT1 até DAW4→OUT4 a 0 dB](https://github.com/soerenbnoergaard/evoctl/blob/31cf69905368d4a6f3523e5f9d5e7c00de496b94/src/transfer_matrix_table.cxx#L172). Toda edição reenvia as 40 células de forma síncrona, com timeout USB 0 (sem limite).
- O [ODS de mensagens capturadas](https://github.com/soerenbnoergaard/evoctl/blob/31cf69905368d4a6f3523e5f9d5e7c00de496b94/doc/usb_control_messages.ods) e o [protótipo Python](https://github.com/soerenbnoergaard/evoctl/blob/31cf69905368d4a6f3523e5f9d5e7c00de496b94/tool/evolib.py#L81) documentam EU58 `0x3a00`: phantom CH1 no índice privado 0 (`wValue=0x0000`) e ganho CH1 com CS1 (`wValue=0x0100`), payloads de quatro bytes. Isso é evidência para a família/modelo capturado, não confirmação do EVO 16.
- O [descritor EVO 8 arquivado](https://github.com/soerenbnoergaard/evoctl/blob/31cf69905368d4a6f3523e5f9d5e7c00de496b94/doc/lsusb_vvv_audient_evo_8.txt) identifica PID 0007 e bcdDevice 1.34. Ele distingue canais padrão de Feature Unit, que usam CH1=1 e master=0, dos índices privados EU58 base 0. A geometria, selectors e fórmula de crosspoint EVO 8 não devem ser extrapolados para o descritor EVO 16. O projeto é de 2021; não há validação Ubuntu 24.04.4/PipeWire no material analisado.

## evo16-API-web: o que o código atual efetivamente envia

Fontes principais: [constantes e serviço](https://github.com/djenttleman/evo16-API-web/blob/5b9ebe7cf0057a349407ac24848eec502e30266c/backend/service.py#L16), [helper IOKit](https://github.com/djenttleman/evo16-API-web/blob/5b9ebe7cf0057a349407ac24848eec502e30266c/mac-evo16/mac-evo16.c#L326) e [README de protocolo](https://github.com/djenttleman/evo16-API-web/blob/5b9ebe7cf0057a349407ac24848eec502e30266c/README.md#L64).

O helper implementa GET_CUR com `bmRequestType=0xa1`, SET_CUR com `0x21` e `bRequest=0x01` em ambos. São pedidos de classe destinados à interface; `wIndex=(entity_id<<8)|interface_number`. Assim, EU58 é a entidade decimal 58 (`0x3a`) e `0x3a00` é sua combinação com interface 0, não um ID de entidade de 16 bits.

Na API, canais são CH1–CH24; no protocolo privado do serviço, `CN=channel-1`, portanto 0–23. Os dados abaixo são os quatro bytes de SET_CUR; GET_CUR solicita quatro bytes e lê o campo correspondente.

| Controle no serviço atual | Entidade / wIndex | CS / wValue | Payload / interpretação |
| --- | --- | --- | --- |
| Ganho CH1–24 | EU58 / `0x3a00` | 1 / `0x0100 + CN` | `[0,dB,0,0]`; código restringe 0–50 dB e lê byte 1 |
| Phantom CH1–24 | EU58 / `0x3a00` | 0 / `CN` | `[on,0,0,0]`; booleano no byte 0 |
| Mute analógico CH1–8 | EU58 / `0x3a00` | 2 / `0x0200 + CN` | `[muted,0,0,0]`; booleano no byte 0 |
| Mute ADAT CH9–24 | FU11 / `0x0b00` | 2 / `0x0200 + CN` | Mesmo payload de quatro bytes; caminho diferente do analógico |

O cabeçalho de `service.py` relata validação em hardware em 2026-05-31 com EVO 16 + SP8 em ADAT1/2, macOS a 48 kHz, EVO 16 clock Internal e SP8 Digital/AUTO. Isso é um relato dos autores em um setup específico; não foi reproduzido aqui e não identifica versão de firmware.

Há uma divergência material: o [README](https://github.com/djenttleman/evo16-API-web/blob/5b9ebe7cf0057a349407ac24848eec502e30266c/README.md#L78) diz que mute dos 24 canais usa EU58 e descreve FU11 CS2 como stereo link; o [serviço](https://github.com/djenttleman/evo16-API-web/blob/5b9ebe7cf0057a349407ac24848eec502e30266c/backend/service.py#L42) usa FU11 CS2 para mute ADAT e afirma que substituir por EU58 quebrou o encaminhamento. Registrar ambos é necessário; não tratar o README como tabela normativa.

## Transporte e limites que impedem reaproveitamento direto

- O [helper](https://github.com/djenttleman/evo16-API-web/blob/5b9ebe7cf0057a349407ac24848eec502e30266c/mac-evo16/mac-evo16.c#L44) usa headers/frameworks exclusivos de macOS e `USBDeviceOpen()`. Não há libusb detach/claim no caminho IOKit. O comando opcional de interrupção, entretanto, [abre interface 0 com USBInterfaceOpen()](https://github.com/djenttleman/evo16-API-web/blob/5b9ebe7cf0057a349407ac24848eec502e30266c/mac-evo16/mac-evo16.c#L130). Isso não constitui evidência de coexistência no Linux; não traduzir esse trecho para claim de AudioControl.
- [dev/DESIGN.md](https://github.com/djenttleman/evo16-API-web/blob/5b9ebe7cf0057a349407ac24848eec502e30266c/dev/DESIGN.md#L7) é documentação de controlador EVO 4 e propõe um módulo que se prende à interface DFU 3 para obter o handle USB. O módulo `kmod` não está presente neste checkout. A proposta viola o requisito de não tomar interfaces e não é prova de transporte EVO 16 seguro para ALSA.
- O helper oferece pedidos arbitrários IN/OUT via JSON `ctrl` e escrita `set_min`, além dos comandos do serviço. Esses caminhos não possuem a whitelist do protótipo readonly e não fazem parte de um controle nativo validado.
- O [Makefile](https://github.com/djenttleman/evo16-API-web/blob/5b9ebe7cf0057a349407ac24848eec502e30266c/mac-evo16/Makefile#L15) possui instalação setuid root, apesar do README anunciar “no root”. O [script de startup](https://github.com/djenttleman/evo16-API-web/blob/5b9ebe7cf0057a349407ac24848eec502e30266c/backend/evo16-web.sh) usa caminhos locais de macOS. Nenhum desses passos foi instalado ou executado.
- O [smoke test](https://github.com/djenttleman/evo16-API-web/blob/5b9ebe7cf0057a349407ac24848eec502e30266c/backend/test_protocol_smoke.py#L33) compara constantes, fórmulas e seleção de entidade; não abre o dispositivo nem verifica efeito físico. Seu texto “ALL PROTOCOL CONSTANTS VERIFIED” não equivale a teste USB.
- [get_all_status()](https://github.com/djenttleman/evo16-API-web/blob/5b9ebe7cf0057a349407ac24848eec502e30266c/backend/service.py#L241) substitui erros de leitura por ganho 0/mute false/phantom false, e inventa mute false para todas as saídas. A [API](https://github.com/djenttleman/evo16-API-web/blob/5b9ebe7cf0057a349407ac24848eec502e30266c/backend/main.py#L92) também retorna modo demo e respostas mock quando desconectada. Estes valores não devem virar estado “confirmado” em um controlador de hardware.
- Ganho negativo, trim completo FU11, Smartgain, medição, clock/roteamento completo e controle real de saídas não estão estabelecidos pela implementação atual. A falha relatada ao escrever ganho negativo no caminho tentado não prova que todo acesso USB ao ganho negativo seja impossível.

## EU58: evidência, hipótese e confronto com o descritor local

| Informação | Evidência disponível | Conclusão permitida |
| --- | --- | --- |
| EU58 existe no EVO 16 e declara 24 canais | Trecho de descritores fornecido pelo usuário, analisado em [device-topology.pt-BR.md](device-topology.pt-BR.md) | Existência/topologia confirmada pelo trecho; `bmControls=0` não documenta seus selectors privados |
| CS0 phantom, CS1 gain, CS2 mute analógico, CN base 0, quatro bytes | Código web e relato de testes EVO 16 + SP8; ecos EVO 4/8 nos outros documentos | Referência externa específica, ainda não validada no EVO 16/firmware do usuário |
| FU11 CS2 mute ADAT de quatro bytes | Serviço web; contradiz o resumo README | Comportamento relatado que exige confirmação; não substituir pelo significado padrão do descriptor |
| FU11 ganho e polaridade padrão | Descritor local anuncia selectors `0x0b` e `0x0d`, respectivamente, canais padrão 1–24 | São controles distintos dos pedidos privados acima; não confundir CS2, CN0 ou payload 4B com esse ganho padrão |
| EU58 CS5 = instrumento/impedância | [Pesquisa dos autores](https://github.com/djenttleman/evo16-API-web/blob/5b9ebe7cf0057a349407ac24848eec502e30266c/dev/instrument-mode-research.md#L20): pedidos de oito bytes aceitos, sem mudança física | Não implementado de forma funcional; eco/readback não prova comutação de hardware |
| Modo instrumento usa `bmRequestType=0x40` | [Pesquisa](https://github.com/djenttleman/evo16-API-web/blob/5b9ebe7cf0057a349407ac24848eec502e30266c/dev/instrument-mode-research.md#L89) atribui essa conclusão a inferência a partir de strings e ausência de mudanças nos registros examinados | Hipótese, sem setup packet ou captura confirmatória publicado nesse relatório |

A pesquisa de instrumento tentou inclusive `wIndex=0x3a03`, direcionado à interface DFU. Isso foi apenas lido como histórico; não foi repetido e não deve entrar no plano nativo. O serviço mantém endpoints experimentais CS5 apesar de o documento final dizer que não produzem efeito físico.

O protótipo [EVOLINUX protocol.py](../src/evolinux/protocol.py) já classifica EU58 CS0–2 como referência exploratória e não validada, e distingue mixer e canais Feature Unit de base 1. Esta revisão sustenta manter essa classificação; não fornece motivo para habilitar OUT/SET privado ou afirmar suporte hardware. O caminho de ajuste padrão ALSA tem limites distintos, descritos em [alsa-backend.md](alsa-backend.md).

## Resultado e lacuna restante

A leitura dos dois snapshots e a comparação de suas mensagens estão concluídas. Consulta opcional à API de issues do evoctl retornou HTTP 403; nenhum achado depende de issues. O que falta para declarar suporte é evidência do EVO 16 do usuário: identificação/firmware completo, estado ALSA real, respostas permitidas de leitura e correspondência entre campos e canais físicos. Nenhuma dessas lacunas é resolvida por compilar os projetos, acrescentar `000a` ao filtro EVO 8 ou confiar em resposta USB bem-sucedida.

As referências servem como mapa rastreável e não autorizam executar comandos experimentais. O transporte de pesquisa permanece readonly: sem detach, claim, reset, mudança de configuração, DFU ou firmware. Não foi feita uma validação funcional de hardware na nuvem. Consulte [os riscos e condições de validação](usb-risks.md) antes de planejar qualquer operação física.
