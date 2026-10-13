# TUSBAUDIO_GetDeviceProperties: kernel output layout

Static analysis only. No Audient executable or driver was executed or modified.

This document preserves the historical Windows/Wine investigation. The
[native controller](../README.md) does not use TUSBAUDIO or this Windows IOCTL
layout. Binary paths and disassembly filenames below identify local research
artifacts; those artifacts are not included in the public source package.

## Input binary and dispatch evidence

- `/workspace/evo-analysis/drivers/x64-cab/fil643897f3e74848ed80f10efdd6a6625c`: PE x64 native, version `5.70.0.0`, OriginalFilename `tusbaudio.sys`.
- SHA-256: `3b9fb6760ff866f03187f5040a70e3916c74ff707d0a05930e89cca2ccdc3c3c`.
- `fil0841e75ce9f74c09a116e0039b50ed26` is byte-identical.
- Disassembly was saved as `/workspace/evo-analysis/app-review/TUSBAUDIO-sys-x64-disassembly.txt` outside this repository; addresses below use preferred image base `0x140000000`.
- Dispatcher `0x140024ef0` receives IOCTL code at `0x140024f3d` and dispatches via a byte-index table at RVA `0x28644` and DWORD target table at RVA `0x285e4`.
- IOCTL `0x808820c4`: normalized index `(code + 0x7f77dffc) & 0xffffffff = 0xc0`; byte table gives `14`; target table entry 14 gives RVA `0x25e81`.
- Handler `0x140025e81` requires output length **exactly** `0x410`; a mismatch yields `0xee000045`. It passes device context in RCX and output pointer in RDX to `0x140033720`. On success it reports `0x410` returned bytes.

## Confirmed output structure

| Output offset | Size | Directly observed content |
| --- | --- | --- |
| `0x000` | 4 | USB VID, loaded from a WORD at device `+0x3e8`, zero-extended and stored as DWORD |
| `0x004` | 4 | USB PID, from WORD at device `+0x3ea`, zero-extended DWORD |
| `0x008` | 4 | USB bcdDevice, from WORD at device `+0x3ec`, zero-extended DWORD |
| `0x00c` | `0x100` | UTF-16 serial string, maximum 127 nonzero UTF-16 units plus terminator; source pointer device `+0x428` |
| `0x10c` | `0x100` | UTF-16 manufacturer string, same bound; source pointer device `+0x3f8` |
| `0x20c` | `0x100` | UTF-16 device display string, same bound; source pointer device `+0x440`; NULL source falls back to literal `USB audio device` at `0x14005bf50` |
| `0x30c` | 4 | Device capability/state bitfield; exact conditions below |
| `0x310` | 4 | AudioControl USB interface number; defaults to `0xffffffff`; if device DWORD `+0x4bc == 1`, set to zero-extended BYTE at device `+0x4dc` |
| `0x314` | `0xfc` | Reserved/unused in this version, explicitly zeroed and never written again in this function |

The entire kernel structure is `0x410 = 12 + 3*256 + 4 + 4 + 252` bytes. It is **not** two 256-WCHAR strings followed by a meaningful final DWORD. The last DWORD at **`0x40c` is zero-filled reserved storage** in this driver implementation.

At `0x140033730..0x14003373b`, the function calls `0x14004f740(output, 0, 0x310)`. At `0x140033740..0x14003374f`, it calls `0x14004f740(output + 0x314, 0, 0xfc)`. At `0x140033754`, it sets DWORD `+0x310` to `0xffffffff`. The helper at `0x14004f740` implements memset (broadcast DL to bytes, write R8 bytes, return original RCX). All subsequent output writes end at `+0x310` inclusive, leaving `[0x314,0x410)` zero.

## String origin evidence

The USB device descriptor lives at device `+0x3e0`, with VID/PID/bcdDevice at `+8/+10/+12` and iManufacturer/iProduct/iSerial at `+14/+15/+16`.

- `0x14002965f` reads iManufacturer from device `+0x3ee`; `0x140029699` calls USB string helper `0x140008ca0`. On success, `0x14002983a..0x14002984b` copies into device string storage at `+0x3f8`. Failure message at RVA `0x522e0` is `Unable to retrieve Manufacturer string.`
- `0x140029754` reads iProduct from device `+0x3ef`; `0x14002977d` obtains the string. Success at `0x140029855..0x140029866` stores it at device `+0x410`. Failure text at RVA `0x52330`: `Unable to retrieve Product string.` The raw product string is not copied into this properties output by `0x140033720`.
- `0x14002986b` reads iSerial from device `+0x3f0`; `0x140029898` obtains it. Success at `0x14002994e..0x14002995f` stores into device `+0x428`. Failure text at RVA `0x52380`: `Unable to retrieve Serial string.`
- Properties output copies strings at `0x140033784..0x140033844`: serial to `+0xc`, manufacturer to `+0x10c`, display string to `+0x20c`. All three loops stop before 128 units and append a zero WORD.

The display string source `+0x440` is assigned by `0x140028cd0`: first use nonempty string at device `+0x4e8`; otherwise use nonempty raw product string at device `+0x410`; otherwise use `USB audio device`. It copies the result into device `+0x440` at `0x140028d4e..0x140028d58`. The primary `+0x4e8` string comes from the AudioControl interface's iInterface descriptor: `0x1400144fc` reads interface descriptor byte `+8`; `0x140014504..0x140014524` retrieves that USB string; `0x14001452e..0x140014537` stores it at parsing-object `+0x20`, which is device `0x4c8 + 0x20 = 0x4e8`. A later registry path writes this display name under `FriendlyDeviceNameString` (string at `0x14005cf90`; call site `0x14002444f`).

## Flags at output +0x30c

These are exact predicates from `0x140033848..0x140033985`. Names for unresolved driver-private source fields are deliberately omitted.

| Mask | Predicate |
| --- | --- |
| `0x0001` | BYTE device `+0x45d != 0` |
| `0x0002` | BYTE device `+0x45e != 0` |
| `0x0010` | BYTE device `+0x460 != 0` |
| `0x0040` | BYTE device `+0x462 != 0` |
| `0x0080` | bit 20 of DWORD at global context pointer `[0x140064060] + 0x140` is clear |
| `0x0020` | device `+0x4bc == 1` and QWORD device `+0xef8 != 0` |
| `0x0008` | device `+0x4bc == 1` and BYTE device `+0xa28 != 0` |
| `0x0004` | device `+0x4bc == 1`, BYTE device `+0x5f0 != 0`, and at least one of QWORD device `+0x610` / `+0x620` is nonzero |
| `0x0100` | device `+0x4bc == 1` and WORD device `+0x4e0 == 0x100` |
| `0x0200` | device `+0x4bc == 1` and WORD device `+0x4e0 == 0x200` |
| `0x1000` | device `+0x4bc == 1` and QWORD device `+0x1c88 != 0` |
| `0x2000` | preceding pointer exists, its `+0x58` UTF-16 string is non-NULL, and it equals device `+0x3b0` UTF-16 string (NULL at `+0x3b0` compares as empty) |

`+0x310` is confirmed as the AudioControl-interface number. The parsing object is embedded at device `+0x4c8` (caller `0x14002413d..0x14002414d`). Parser `0x1400141c0` searches standard interface descriptors (type byte `+1 == 4`) with audio class (byte `+5`, usually 1) and subclass AudioControl (byte `+6 == 1`) at `0x140014348..0x140014358`; it validates class-specific AC header at `0x1400143f2..0x140014425` and supported UAC version. It copies the selected standard interface's `bInterfaceNumber` byte `+2` to parsing-object `+0x14` at `0x1400144ec..0x1400144f0`. Thus device `+0x4c8 + 0x14 = +0x4dc` is precisely the chosen AC USB interface number. USB Audio Control request function `0x1400333e0` also replaces the low byte of `wIndex` with device `+0x4dc` at `0x1400334d4..0x1400334eb`.

Flags `0x0100` / `0x0200` are confirmed UAC1 / UAC2 indicators: parser stores selected AC header `bcdADC` (class-specific descriptor WORD `+3`) to parsing-object `+0x18` at `0x1400147a1..0x1400147a6` (UAC2) and `0x1400147cb..0x1400147d0` (UAC1); embedded device offset `0x4c8+0x18 = 0x4e0`. The properties routine tests `0x100` / `0x200` there. The precise symbolic API names of these flags were not available.
