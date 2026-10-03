# Case 001: a depth sample beyond the bottom edge

| Case | Depth-buffer bounds |
|---|---|
| Fix ID | `001-depth-buffer-bounds` |
| Community release | `1.2.1` |
| Supported builds | Official 1.2 and a compatible 1.2 variant |
| Faulting instruction | VA `0x0040D2F4`, RVA and file offset `0xD2F4` |
| Correction | Two `JG` instructions become `JGE` |
| Verification | Static analysis and isolated x86 replay; gameplay pending |

## Failure and causal chain

The game crashed while testing whether a projected visual effect should be visible. The effect's screen-space point was just below the bottom edge. Its integer y coordinate became `1800` on a screen with height `1800`.

That screen has valid row indices `0` through `1799`. The game's bounds check rejected y values greater than `1800`, but allowed equality. It then read the depth sample for the nonexistent row `1800`.

The captured exception was `STATUS_GUARD_PAGE_VIOLATION`, code `0x80000001`, at a depth-read instruction. Windows uses that exception when an application accesses a guarded memory page. It is not the ordinary `0xC0000005` access-violation code. See Microsoft's [guard-page documentation](https://learn.microsoft.com/en-us/windows/win32/memory/creating-guard-pages).

## Captured values

Only the minimal numerical evidence is reproduced here. Proprietary executable files and raw process dumps are not distributed.

| Value | Captured or derived result |
|---|---|
| Screen globals | Width `2880`, height `1800` |
| Projected point | x `851.6438598632812`, y `1800.621826171875`, z `64657.0` |
| Converted pixel | x `851`, y `1800` |
| Depth base, EDX | `0x1515A000` |
| Linear element index, ECX | `5,184,851` |
| Fault target | `0x15B3DAA6` |
| Caller return address | `0x0040D9A3` |

The executed index calculation is:

```text
element_index = (pitch_bytes / 2) * y + x
5,184,851     = 2,880             * 1,800 + 851
pitch_bytes   = 5,760
```

For a 16-bit, 2880-by-1800 depth surface with that pitch:

```text
nominal_size          = 5,760 * 1,800 = 10,368,000 bytes
nominal_end_exclusive = 0x1515A000 + 10,368,000 = 0x15B3D400
sample_address        = 0x1515A000 + 2 * 5,184,851 = 0x15B3DAA6
distance_past_end     = 1,702 bytes
```

The calculated sample address exactly matches the exception's target address.

The renderer heap object was not retained in this minidump. Its width, height, and pitch fields could not be read directly. Width and height are corroborated by captured game globals and the constructor's unmodified assignment of resolution arguments. Pitch is derived from the captured register arithmetic. The allocation extent above is the nominal surface extent, rather than a separately captured allocation descriptor.

## Responsible code

The image base is `0x00400000`. Function `0x0040D2B0` implements renderer virtual method `0x54`. It converts a projected x/y/z point, checks the x and y bounds, reads a 16-bit depth value, and returns a Boolean visibility result.

The relevant original instructions are:

```asm
; Earlier instructions reject negative x and y.
0040D2D2  cmp eax, dword ptr [esi + 1Ch] ; x versus width
0040D2D5  jg  0040D308                   ; equality slips through
0040D2D7  cmp edi, dword ptr [esi + 20h] ; y versus height
0040D2DA  jg  0040D308                   ; equality slips through
...
0040D2F4  mov si, word ptr [edx + ecx*2]
```

The dimension fields hold pixel counts, not the maximum valid index. Their initialization stores the resolution width and height without subtracting one.

Caller `0x0040D800` projects the effect point and invokes this depth test at `0x0040D9A0`. If the test returns false, the caller takes its existing path that skips drawing the effect.

## Original defect, modern manifestation

The complete bounds-test routine, its surface setup, and its dimension initialization were compared against the preserved official 1.2 baseline. The faulty instructions are present in that original executable.

The same routines are byte-for-byte identical in the supported compatible 1.2 variant. The patcher identifies each complete executable separately and applies the same two code changes to the installed build, preserving its other content. The variant is identified by its binary hash and is not presented as an official release.

```text
Official 1.2 SHA-256
e9c5d3932dc87accd8a1d94a264de1badbe7edac73afaf1fa78181a30c624d1c
```

The captured ordinary effect point, exact edge coordinate, and matching fault-address arithmetic support attribution to the game's bounds error. A graphics provider that guards its memory can expose that mistake immediately. This evidence does not prove that every wrapper behaves the same way, or that the crash could never occur on an original-era operating system.

## Correction

| File offset | VA | Original | Replacement | Result |
|---|---|---|---|---|
| `0xD2D5` | `0x0040D2D5` | `7F` | `7D` | Reject x greater than or equal to width |
| `0xD2DA` | `0x0040D2DA` | `7F` | `7D` | Reject y greater than or equal to height |

These are short signed conditional branches: `JG` becomes `JGE`. The existing negative checks remain. Branch lengths and destinations remain unchanged.

The rejection path at `0x0040D308` restores the saved EDI, ESI, and EBX registers, returns `AL = 0`, and removes the single stack argument with `RET 4`. EBP is untouched. The floating-point z load occurs after the bounds checks, so rejecting equality does not leave an extra value on the FPU stack.

All previously valid interior coordinates follow the same path. Previously rejected coordinates remain rejected. The newly rejected right-edge case also prevents x equal to width from aliasing the first sample in the next row.

## Validation and limits

The actual x86 routine was replayed offline before and after the byte changes: **61 original/patched case pairs and 177 checks**. The replay includes the captured failure input, edge coordinates, nearby interior coordinates, and return behavior. See the [saved replay results](../verification/v1.2.1-replay.json) and [replay harness](../../tests/replay_depth_bounds.py).

The patched routine rejects the captured point before its depth read. Offline execution establishes the changed routine's behavior in the supplied test state. It does not exercise the complete game loop, the graphics driver, or a real mission. Live gameplay validation remains pending.

## Separate surface-lifetime concern

The original setup code obtains a depth-surface pointer through DirectDraw `Lock`, immediately calls `Unlock`, and retains the pointer for subsequent CPU reads. Microsoft's [DirectDraw Lock documentation](https://learn.microsoft.com/en-us/windows/win32/api/ddraw/nf-ddraw-idirectdrawsurface7-lock) says the surface pointer is invalid after the corresponding unlock.

This is a separate API-contract concern. It may matter for valid-coordinate accesses on some providers, but it is not necessary to explain the captured out-of-range row. The 1.2.1 fix leaves surface locking unchanged; further work belongs in a separate case with its own evidence.
