# EVO 4.4.0 — notificações e bloqueios de carregamento

Continuação da inspeção estática. Nenhum código Windows foi executado. Binários e ImageBases são os identificados em [tusbaudio-abi.md](tusbaudio-abi.md).

Este documento preserva a investigação Windows/Wine; o [controlador nativo](../README.md) não implementa essas APIs ou notificações Windows. Os relatórios JSON e binários citados abaixo são artefatos locais preservados fora do repositório, não arquivos distribuídos no pacote público. Nenhuma DLL substituta funcional foi produzida.

## Existência de exportações versus execução de funções

O carregador `TUsbAudioApiDll` em `0x1402e77e0` resolve **63 nomes**. Para API v5, testa se cada ponteiro retornado por `GetProcAddress` é diferente de zero; se algum está ausente, descarrega e devolve erro. Portanto um adaptador terá de exportar os 63 nomes com ABI correta. O carregador não testa a execução de todos eles.

Ele executa `GetApiVersion()` e `CheckApiVersion(5,0)` antes da resolução principal. `CheckApiVersion` é booleano: retornar `TSTATUS_NOT_SUPPORTED` (inteiro não zero) nessa função seria um erro de contrato. No DLL original, `GetApiVersion` retorna 0x0005000d e `CheckApiVersion(5,minor)` retorna verdadeiro para minor <= 13.

As referências do aplicativo a cada slot global estão em `TUSBAUDIO-app-global-slot-references.json`. Esse mapa contém referências por endereço, não um call graph completo. A ausência de referências diretas é evidência forte para esta compilação, mas não uma promessa de que futuras versões manterão o mesmo comportamento.

**Sem referência efetiva encontrada no x64:** `RegisterDeviceNotification`, `ReadDeviceNotification`, `ClassVendorRequestIn/Out`, Get/SetVolume, Get/SetMute, GetDspProperty/SetDspProperty, GetDriverInfo, propriedades de canais e formatos de streaming, estatísticas. A aplicação usa `AudioControlRequestSet/Get` para suas operações UAC.

Os exports sem uso podem existir e devolver TSTATUS_NOT_SUPPORTED em um protótipo de escopo limitado, desde que assinaturas e saídas sejam respeitadas. Isso é diferente de omitir os exports: omiti-los impede o carregamento.

## Enumeração inicial e PnP

O construtor em `0x1402e60b0` executa esta sequência:

1. Carrega DLL e faz a verificação de versão.
2. Em `0x1402e6476`, chama a rotina de enumeração `0x1402edc10`.
3. Cria evento Windows chamado `devicePnpEvent` em `0x1402e6489`.
4. Em `0x1402e64b8`, chama `RegisterPnpNotification(event,event,NULL,0,0)`.
5. **Não testa o retorno** dessa chamada e inicia a thread JUCE.

A thread `UsbDevicesImpl::run`, `0x1402eb730`, espera o evento com `WaitForSingleObject(event,20ms)`. Chama novamente `0x1402edc10` somente quando o resultado é WAIT_OBJECT_0. O timeout de 20 ms é usado para verificar a condição de término; **não significa reenumeração a cada 20 ms**.

Conclusão limitada: devolver NOT_SUPPORTED em RegisterPnpNotification não bloqueia essa enumeração inicial, com o dispositivo conectado antes da abertura. Sem sinalizar o evento, conexão e remoção posteriores não atualizam a lista. Para hotplug funcional, o adaptador deverá notificar os eventos Windows a partir das mudanças USB reais.

`UnregisterPnpNotification()` é chamado sem argumentos no destrutor, em `0x1402e6e1f`, após parar a thread. O retorno não é usado. A implementação original desmonta a thread/registro e limpa os campos; a assinatura se comporta como `void(void)`.

## Assinaturas de notificação recuperadas

| Export | ABI externa observada | Evidência |
|---|---|---|
| `RegisterPnpNotification` | `(HANDLE arrivalEvent, HANDLE removalEvent, HWND window, uint32 message, uint32 arg5)`; TSTATUS de 32 bits. O arg5 é encaminhado pelo wrapper mas não consumido na implementação analisada | export x64 `0x1800021a0`; helper `0x180011600`; campos internos 0x1c0/0x1c8 são usados com SetEvent na chegada/remoção; 0x1d0/0x1d8 são usados com PostMessageW |
| `UnregisterPnpNotification` | zero argumentos; retorno ignorado, implementação aparentemente void | export x64 `0x180002420` → helper `0x1800129e0`; app `0x1402e6e13` |
| `RegisterDeviceNotification` | `(uint32 handle, uint32 notificationFlags, HANDLE event, uint32 arg4)`; TSTATUS de 32 bits. Arg4 encaminhado, não lido no helper observado | export x64 `0x180002170`; helper `0x180011520`; entrada IOCTL0x808820d8 de 12 bytes: flags DWORD + handle Windows de 8 bytes em offset4 |
| `ReadDeviceNotification` | `(uint32 handle, uint32 *type, void *payload, uint32 maxBytes, uint32 *actualBytes)`; TSTATUS de 32 bits | export x64 `0x180002140`; helper `0x180011310`; usa saída IOCTL0x808820dc de 12+maxBytes; devolve type do offset4, comprimento do offset8 e payload do offset12 |

Na implementação `ReadDeviceNotification`, type é obrigatório. Payload pode ser nulo para consultar apenas o tipo; actualBytes é opcional. Não inventar números de tipos ou mensagens. Como esses dois exports não têm referências efetivas no aplicativo analisado, seus layouts não bloqueiam o primeiro teste de enumeração.

O helper de PnP `0x1800106c0` confirma chegada 0x8000 → sinaliza arrivalEvent e PostMessage(...,wParam=1,lParam=0); remoção 0x8004 → sinaliza removalEvent e PostMessage(...,wParam=2,lParam=0). Os dois eventos são o mesmo objeto no app EVO.

## APIs efetivamente chamadas que não podem ser ignoradas indiscriminadamente

- `EnumerateDevices`, `GetDeviceCount`, `OpenDeviceByIndex`, `GetDeviceInstanceIdString`, `GetDeviceProperties`, `GetUsbConfigDescriptor`: seus erros fazem a aplicação pular a descoberta ou a construção do dispositivo. Um DLL que apenas exporte nomes e retorne NOT_SUPPORTED não faz a EVO aparecer.
- `AudioControlRequestGet/Set`, strings USB e consulta de sample rate/clock: suas falhas deixam controles sem estado válido ou sem execução. Descriptor estático sozinho não substitui os valores reais.
- `GetASIOInstanceInfo` é chamado por cinco rotinas, embora não possa corresponder a um driver ASIO Linux. Algumas saídas são copiadas mesmo após erro. Em `0x1402e8bf0`, a rotina não inicializa sua estrutura local, chama `GetASIOInstanceInfo(0,buffer)` e copia o DWORD de buffer+0x1c antes de testar o retorno. Um stub que apenas retorne NOT_SUPPORTED e deixe a saída intacta pode propagar dados não inicializados. O helper original `0x18000c310` confirma `(uint32 instanceIndex, void *info)` e uma saída de **0xc4=196 bytes** no IOCTL0x80882180, em `0x18000c3cc..0x18000c3ee`. Uma resposta de erro deve deixar o buffer determinístico sem indicar que existe ASIO funcional; o significado dos demais campos ainda requer investigação.
- Funções de firmware/DFU têm call sites efetivos. Devem continuar devolvendo um erro explícito em um primeiro protótipo; não simular sucesso nem iniciar download.

Esses fatos permitem definir um protótipo com limites claros, mas não comprovam que as rotinas superiores tolerarão todas as falhas opcionais sem uma sessão de teste sob Wine. Esta sessão não foi realizada e não é uma etapa necessária à instalação do controlador nativo.
