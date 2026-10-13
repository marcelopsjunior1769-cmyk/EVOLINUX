# EVO 4.4.0 — observações estáticas de ABI

Inspeção apenas de arquivos: os executáveis Windows e os drivers não foram executados. Endereços abaixo pertencem aos binários deste instalador e não constituem uma API documentada pela Audient. Análise realizada para avaliar um adaptador que mantenha a interface Windows original sob Wine.

Estas observações preservam a pesquisa histórica; o [controlador nativo atual](../README.md) não depende de TUSBAUDIO ou Wine. Os caminhos `payload/`, `drivers/` e os relatórios de disassembly/JSON citados abaixo pertencem aos artefatos locais de análise, fora deste repositório. Eles não fazem parte do pacote público. Nenhuma DLL substituta funcional foi desenvolvida nesta etapa.

## Arquitetura observada

- `payload/EVO/EVO.exe`: PE32+ x86-64, versão 4.4.0, 9.295.360 bytes. SHA-256 `6c77c84438b894b78221582eb4dda1ee9e612442a7fb04568fa6beb458493faa`.
- `payload/EVO/EVO_1.exe`: PE32 x86, versão 4.4.0, 8.288.256 bytes. SHA-256 `d49e1189062c61e2bf672b5b9edd0688a8c705f684c5a059933eea7309c0ce15`.
- Ambos têm CLR Directory zerado e RTTI de classes C++ JUCE (`juce::Component`, `Evo16MonitorControls`, `UacLib::UacXUAudientRoutingMatrix`, `UacXUAudientInputControl` etc.). Não são assemblies .NET.
- `WebView2Loader.dll` e classes JUCE WebView2 existem; strings próximas vinculam esse navegador a `ProductRegistrationComponent` e `https://arc.audient.com/`. Não há evidência de que o mixer seja uma interface HTML extraível.
- Dependências estáticas do aplicativo: KERNEL32, USER32, GDI32, SHELL32, ole32, OLEAUT32, COMDLG32, ADVAPI32, WININET, WS2_32, SHLWAPI, WINMM, IMM32, OPENGL32. Não há importação estática de libusb/WinUSB/HID. `DeviceIoControl` e funções `LoadLibrary`/`GetProcAddress` estão presentes; sua presença isolada não identifica o transporte do mixer.

## Fronteira de adaptação comprovada

O construtor `UsbDevicesImpl`, começando em `0x1402e60b0`, procura `custom.ini` e extrai a linha `InterfaceGUID = `. Se não a encontra próximo ao aplicativo, consulta `HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\ProgramFilesDir` e procura debaixo da pasta Audient. Mensagens do binário: `Failed to find custom.ini file:` e `Failed to load dll.`

`0x1402e75f0` abre `HKEY_CLASSES_ROOT\\CLSID\\<InterfaceGUID>\\InprocServer32`, lê o valor padrão usando `RegQueryValueExA` e passa o caminho obtido ao carregador `0x1402e77e0`. Esse carregador chama `LoadLibraryA` e resolve os nomes `TUSBAUDIO_*` por `GetProcAddress`, mantendo os ponteiros em um objeto global em `0x14087c950`.

As 63 funções resolvidas e seus slots estão listados em `TUSBAUDIO-resolved-api-slots.json` e `TUSBAUDIO-api-names.txt`. O carregador exige que esses símbolos estejam presentes para a API v5. `TUSBAUDIO_GetApiVersion()` retorna `0x0005000d` no DLL extraído (v5.13); `TUSBAUDIO_CheckApiVersion(5,0)` é chamado e retorna um booleano, não um TSTATUS.

Isso identifica uma fronteira concreta para desenvolver uma DLL substituta compatível, carregada pelo registro do prefixo Wine, que encaminhe operações ao Linux. Isso não prova que a aplicação abre corretamente sob Wine nem que todos os seus controles possam ser suportados sem trabalho adicional.

## DLLs de referência usadas nesta análise

- API x64, `drivers/x64-cab/filf2ab6ca29b78431e8c4970ce17142823`, ImageBase `0x180000000`.
- API x86, `drivers/x64-cab/fild3b52249e2bd4f9cbba3ec1fdfe130e8`, ImageBase `0x10000000`.
- Metadados internos: `TUSBAudio API DLL`, arquivo original `tusbaudioapi.dll`, driver 5.70.0.0. Cada uma exporta 81 nomes TUSBAUDIO; o aplicativo resolve 63.
- Arquivos de evidência: exports JSON de ambas as arquiteturas, `EVO-TUSBAUDIO-resolution-disassembly.txt`, `TUSBAUDIO-call-excerpts.txt`, disassembly das DLLs x64/x86.

## ABI de operações essenciais

O `handle` é um inteiro de 32 bits mesmo no aplicativo x64: as aberturas recebem ponteiro para DWORD, e os consumidores carregam o handle em ECX. A identidade de handles no Linux deverá preservar essa semântica.

| Operação | Argumentos e retorno observados | Evidência |
|---|---|---|
| `EnumerateDevices` | zero argumentos; TSTATUS de 32 bits, 0 significa sucesso | app `0x1402edc53`; export x64 `0x1800019b0` troca RCX pelo singleton, sem preservar qualquer argumento |
| `GetDeviceCount` | zero argumentos; número de dispositivos de 32 bits, não TSTATUS | app `0x1402edc84`, `0x1402edd00`, `0x1402edff0`; export `0x180001ca0` |
| `OpenDeviceByIndex` | `(uint32 index, uint32 *handle)`; TSTATUS | app `0x1402edd1a` → chamada `0x1402edd34`; export `0x1800020d0`; implementação `0x180010b40` escreve 4 bytes no ponteiro de saída |
| `CloseDevice` | `(uint32 handle)`; TSTATUS | app `0x1402ede1d`; export `0x180001940` |
| `GetDeviceProperties` | `(uint32 handle, void *properties)`; TSTATUS; saída de **0x410 bytes** | app `0x1402e5f21`, output objeto+0x2c; export `0x180001cd0`; implementação `0x18000d9f0` usa IOCTL `0x808820c4` e comprimento de saída 0x410 |
| `GetUsbConfigDescriptor` | `(uint32 handle, void *buffer, uint32 maxBytes, uint32 *actualBytes)`; TSTATUS | app `0x1402e5f9e` usa buffer 0x400; export `0x180001fb0`; implementação `0x18000ecb0` escreve 4 bytes em actualBytes |
| `GetUsbStringDescriptorString` | `(uint32 handle, uint8 descriptorIndex, uint32 languageId, void *buffer, uint32 maxBytes)`; TSTATUS | app `0x1402ea005` com maxBytes=0x400; export `0x180001fe0`; interpretação Unicode observada no consumidor; sem typedef oficial |
| `AudioControlRequestSet` / `Get` | **9 argumentos**: `(uint32 handle, uint8 unitId, uint8 bRequest, uint8 controlSelector, uint8 channel, void *buffer, uint32 bytes, uint32 *actualBytes, uint32 timeoutMs)`; TSTATUS | app chamada `0x1402ebae1`; exports `0x1800017d0`/`0x180001760`; wrappers x86 retornam com `ret 0x24`, confirmando 9 argumentos stdcall |
| `ClassVendorRequestOut` / `In` | **10 argumentos**, larguras `(u32,u32,u8,u8,u16,u16,u16,ptr,ptr,u32)`; TSTATUS. Nome semântico de arg2/arg3 requer confirmação | exports `0x1800018c0`/`0x180001850`; implementações `0x18000a1e0`/`0x18000a070`; não encontrei call site efetivo desses slots no app x64 |
| `RegisterPnpNotification` | cinco argumentos, larguras `(ptr,ptr,ptr,u32,u32)`; eventos de chegada/remoção, HWND, mensagem e último argumento não consumido no helper; app fornece o mesmo evento nas duas primeiras posições e zero nas demais | app `0x1402e649b` → `0x1402e64b8`; export `0x1800021a0`; detalhes em [tusbaudio-notifications.md](tusbaudio-notifications.md) |

No x86, funções TUSBAUDIO têm convenção stdcall, apesar de os nomes exportados não incluírem decoração `@N`. No x64, usar a ABI Windows x64. Uma compilação Linux normal com a ABI SysV não pode substituir essas funções diretamente.

## Transformação USB Audio Control confirmada

O app monta um pacote USB no seu objeto de requisição e escolhe `AudioControlRequestGet` quando o bit 7 de `bmRequestType` indica entrada, `Set` quando indica saída. Na chamada em `0x1402ebae1`, o unitId vem do byte alto de wIndex, bRequest do byte 1, controlSelector do byte alto de wValue, channel do byte baixo de wValue. O timeout é **10.000 ms**.

A implementação comum do DLL em `0x180009ce0` confirma:

- `wValue = (controlSelector << 8) | channel`;
- `wIndex = unitId << 8` na requisição encaminhada;
- fluxo `Get` usa o IOCTL `0x80882086`, `Set` usa `0x80882081`;
- `actualBytes`, quando não nulo, aponta para 4 bytes;
- o índice da interface de Audio Control não é um argumento explícito dessa API. O transporte Linux deverá determiná-lo do descriptor real, sem presumir que seja sempre 0.

Isso é consistente com controles USB Audio Class, inclusive extension units Audient. Ainda não valida os valores de controle concretos da EVO 16 nem a coexistência com o driver ALSA.

## Layout de GetDeviceProperties confirmado no driver SYS

O tamanho 0x410 é confirmado pelo código do DLL e pelo handler no driver SYS. A análise do SYS está documentada em [tusbaudio-properties.md](tusbaudio-properties.md), incluindo hash e endereços. O layout é:

| Offset relativo à saída | Uso observado |
|---|---|
| 0x000 | VID em DWORD, zero-extended do WORD USB; app lê WORD no getter `0x1402ea3b0` |
| 0x004 | PID em DWORD, zero-extended do WORD USB; app lê WORD no getter `0x1402e9bf0` |
| 0x008 | bcdDevice em DWORD, zero-extended do WORD USB; app lê WORD no getter `0x1402e91d0` |
| 0x00c | número de série USB em UTF-16, 128 unidades incluindo terminador; getter app `0x1402e9d90` |
| 0x10c | fabricante USB em UTF-16, 128 unidades incluindo terminador |
| 0x20c | nome exibido do dispositivo em UTF-16, 128 unidades; prioridade: iInterface AudioControl não vazio, depois iProduct USB, depois `USB audio device`; getter app `0x1402e9c80` |
| 0x30c | DWORD de flags; bits 0x100/0x200 confirmados como UAC1/UAC2; demais predicados exatos descritos em [tusbaudio-properties.md](tusbaudio-properties.md), sem inventar nomes |
| 0x310 | DWORD com bInterfaceNumber da interface USB AudioControl, zero-extended do BYTE; default 0xffffffff quando indisponível, confirmado pelo parser de descritores do SYS |
| 0x314..0x40f | 252 bytes reservados, explicitamente zerados pelo driver |

Os últimos 4 bytes em 0x40c são parte da área reservada zerada, não um campo semântico desconhecido. Não foi encontrada leitura direta dessa posição no código Uac do aplicativo. A disposição de três strings de 128 WCHAR foi confirmada pelo SYS; a inferência inicial de duas strings de 256 WCHAR estava incorreta e foi substituída por essa evidência.

## Retornos recuperados sem adivinhar

`TUSBAUDIO-return-status-codes.json` contém códigos extraídos dos jump tables de `StatusCodeStringA` em `0x1800057b0`. Valores úteis confirmados:

- `0x00000000`: TSTATUS_SUCCESS.
- `0xee000003`: TSTATUS_TIMEOUT.
- `0xee000023`: TSTATUS_NO_DEVICES.
- `0xee000030`: TSTATUS_NOT_SUPPORTED (também fallback do app quando um ponteiro API está ausente).
- `0xee000033`: TSTATUS_NOT_OPENED.
- `0xee000041`: TSTATUS_INVALID_PARAMETER.
- `0xee000047`: TSTATUS_INVALID_INDEX.
- `0xee000048`: TSTATUS_INVALID_HANDLE.
- `0xee000060`: TSTATUS_VERSION_MISMATCH.
- `0xee000070`: TSTATUS_ENUM_REQUIRED.
- `0xee000074`: TSTATUS_BUFFER_TOO_SMALL.

Uma DLL de teste poderia devolver erros suportados para funções opcionais, mas não deve devolver sucesso sem executar a operação nem simular uma EVO conectada.

## Próximo requisito antes de um adaptador funcional

A DLL API fornece uma fronteira suficiente para uma investigação concreta e um protótipo limitado. Notificações e bloqueios do carregador estão detalhados em [tusbaudio-notifications.md](tusbaudio-notifications.md). Ainda faltam interpretação dos flags necessária ao app, comportamento de relógio/sample rate e teste de UI sob Wine. No Ubuntu do usuário, também é necessário provar acesso às leituras USB e aos extension units mantendo ALSA/PipeWire disponíveis. Não há teste de hardware nesta nuvem. Firmware e DFU não devem fazer parte do primeiro protótipo. Estas são lacunas da abordagem Windows histórica, não funcionalidades prometidas para o controlador nativo.
