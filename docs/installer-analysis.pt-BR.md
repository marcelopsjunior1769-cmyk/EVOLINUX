# Histórico da adaptação do EVO original: resultados da inspeção

Esta análise registra a investigação inicial do aplicativo Windows. O projeto
atual desenvolve um controlador nativo, descrito no [README](../README.md).
Nenhum substituto funcional do aplicativo oficial ou de sua DLL foi produzido.

## Objetivo

O objetivo inicial era manter o aplicativo original da Audient e investigar uma camada de comunicação
compatível com Ubuntu 24.04. O reconhecimento e uso básico da EVO 16 como dispositivo
de áudio já foram confirmados pelo usuário. O trabalho restante é o controle da
interface pelo aplicativo, incluindo mixer e roteamento. As pendências desta
abordagem são históricas e não constituem o plano de implementação nativa.

## Instalador examinado

| Campo | Resultado |
| --- | --- |
| Arquivo enviado | `EVO-v4.4.0a.exe` |
| Tamanho | 27.239.736 bytes |
| SHA-256 | `5a08a609e989ea49556fdfae152189934e8c32812842f42a50720c97707b19c7` |
| Formato | NSIS 3 Unicode, compressão Deflate |
| Versão do aplicativo | 4.4.0.0 |
| Aplicativo extraído | Binários Windows nativos x64 e x86 |
| Pacote de drivers | 5.4.0; INF `5.4.0.20404`, 25/09/2024 |
| API do driver | TUSBAudio, versão de arquivo 5.70.0.0 |

A extração terminou com sucesso e preservou as duas arquiteturas. O nome
`EVO_1.exe` foi criado pelo extrator para distinguir arquivos com o mesmo nome no
instalador; não é o nome que o fabricante atribui ao aplicativo x86.

O digest Authenticode e a assinatura RSA/SHA-256 do certificado **Audient Limited**
foram verificados. O timestamp RFC3161 DigiCert de 04/10/2024 12:28:54 UTC foi
verificado e a cadeia do assinante era válida nessa data. Não houve consulta de
revogação CRL/OCSP nem avaliação completa da política Authenticode do Windows.
A assinatura não determina compatibilidade Linux.

## Dependência que impede uma conversão direta

O aplicativo é nativo C++ e contém referências a JUCE e a controles específicos da
EVO 16. Não há cabeçalho CLR de aplicativo .NET. Não foi localizado projeto de
código-fonte no instalador.

O pacote inclui as bibliotecas `audientusbaudioapi.dll` e
`audientusbaudioapi_x64.dll`, além dos drivers Windows `audientusbaudio.sys` e
`audientusbaudioks.sys`. A API usa `DeviceIoControl` e enumeração Windows via
SetupAPI. O INF associa explicitamente a EVO 16 ao ID `USB\\VID_2708&PID_000A`.

Assim, executar a interface gráfica em Wine não comprova comunicação com o
hardware. Copiar o driver `.sys` para Ubuntu não cria um driver Linux equivalente.

## Fronteira de adaptação identificada

No binário x64, a análise do loader revelou:

1. Leitura de `custom.ini` para obter `InterfaceGUID`.
2. Consulta ao registro `HKCR\\CLSID\\<InterfaceGUID>\\InprocServer32`.
3. Carregamento da DLL com `LoadLibraryA`.
4. Resolução de funções `TUSBAUDIO_*` com `GetProcAddress`.

O GUID distribuído no pacote é
`{572B9A62-741A-4a6f-84A7-84A10F18D64F}`. As duas bibliotecas API exportam 83
símbolos no total, incluindo 81 nomes `TUSBAUDIO_*`; o loader do aplicativo resolve 63 funções da API. O conjunto inclui
enumeração e abertura de dispositivos, notificações, descritores USB,
`TUSBAUDIO_AudioControlRequestGet/Set` e requisições class/vendor.

Isso estabelece uma possibilidade concreta: uma DLL compatível sob Wine, com a
mesma ABI esperada pelo aplicativo, pode delegar a comunicação a um backend Linux.
Ainda é necessário confirmar assinaturas, estruturas, códigos de retorno e os
comandos realmente usados. Não foi produzido um substituto funcional dessa DLL.

## Pendências técnicas

- Mapear argumentos, tamanhos e layout das estruturas usadas nas funções da API.
- Comparar descritores e versão de firmware da EVO 16 do usuário com as
  expectativas do aplicativo.
- Identificar quais controles são padrão UAC2 e quais são específicos da Audient.
- Definir comunicação que coexista com ALSA/PipeWire. Acesso direto às interfaces
  USB pode conflitar com `snd-usb-audio`; não se presume que destacar o driver seja
  aceitável ou que permita continuar a gravação no Ubuntu.
- Validar enumeração e leitura antes de testar qualquer alteração de ganho,
  roteamento, phantom ou firmware no hardware.

O ambiente na nuvem não expõe `/sys/bus/usb/devices` nem a interface do usuário.
Dados locais são necessários para avançar a investigação de comunicação.

## Referências e evidência preservada

Os caminhos abaixo identificam artefatos locais da sessão de pesquisa, mantidos
fora do repositório. Não são links do pacote público e não precisam estar
presentes para instalar ou testar o controlador nativo.

- `/workspace/evo-analysis/identity/identity.md`: verificação criptográfica.
- `/workspace/evo-analysis/driver-pe-inventory.json`: versões, imports e exports.
- `/workspace/evo-analysis/driver.inf`: INF extraído e decodificado.
- `/workspace/evo-analysis/app-review/`: strings, mapa PE e disassembly do loader.
- [Referência comunitária de protocolo da EVO 16](https://github.com/djenttleman/evo16-API-web):
  implementação macOS/IOKit e controles de pré-amplificador; não é uma versão
  Linux do aplicativo original nem comprova suporte integral ao mixer.

Os arquivos anexados e suas strings foram tratados como dados de análise, não
como instruções a executar. Os binários originais foram preservados.

Os commits, atribuições e limitações dos projetos comunitários consultados estão
em [references.md](references.md). A Audient não forneceu código-fonte; esta
inspeção estática não concede licença para redistribuir seu instalador ou seus
componentes proprietários, que permanecem fora do pacote.
