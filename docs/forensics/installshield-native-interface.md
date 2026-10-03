# The original installer and its native interface

The original installer engine recognizes more script operations than this particular engine build enables. The first private integration used `UseDLL`, an operation whose dispatch entry is disabled. The VM returned `-1` before attempting to load the patch component. Its profile-writing operation was disabled too, explaining why the diagnostic INI file was absent.

The corrected integration uses the engine's enabled `CallDLLFx` interface. The original 16-bit setup entry point, original 32-bit engine and original SDK dialogs are retained. The owned native component launches the windowless patch worker, waits for the actual process to finish, and requires a fresh verified success receipt before returning success.

## Engine identity and evidence

This analysis inspected an existing isolated extraction of the original engine, without executing the game or changing the engine:

| Property | Observed value |
| --- | --- |
| Architecture | PE32, Intel x86 |
| File size | 594,944 bytes |
| SHA-256 | `82ca5fd2d52ddbef610dccb4641fab4e84f8e55d81f1d92ec34a41b54beb0664` |
| Preferred image base | `0x00400000` |
| Built-in dispatch table | `0x0047F0A0`; five bytes per entry |

Each dispatch entry contains a flags/argument-count byte followed by a function pointer. The low four flag bits specify the number of arguments. The dispatcher reads the pointer at `0x0047F0A1 + opcode * 5`. A zero pointer takes an existing path that sets the script's `LAST_RESULT` to `-1` and skips the operation.

| Script operation | Opcode | Arguments | Dispatch result |
| --- | --- | --- | --- |
| `UseDLL` | `0x00B2` | 1 | Disabled: null pointer |
| `UnUseDLL` | `0x00B3` | 1 | Disabled: null pointer |
| `WriteProfString` | `0x0025` | 4 | Disabled: null pointer |
| `GetProfString` | `0x0026` | 4 | Disabled: null pointer |
| `LaunchApp` | `0x0033` | 2 | Disabled: null pointer |
| `LaunchAppAndWait` | `0x00E3` | 3 | Disabled: null pointer |
| `CallDLLFx` | `0x013B` | 4 | Enabled: `0x00441C78` |

Native implementation bodies for some disabled operations remain in the executable. Their presence alone does not establish that the script VM can reach them. Testing an internal loader directly bypasses the dispatch decision.

The failed private wizard displayed the correct full component filename and `UseDLL` result `-1`. Independent 32-bit Windows loading tests accepted that exact DLL path and found its export. Direct tests of the engine's internal loader also succeeded. The null dispatch entries explain the otherwise contradictory observations: the attempted script calls never reached those working implementations. An independent reference scan found the dispatch-table references were reads and found no ordinary direct write enabling the disabled entries.

This is evidence about this exact engine image and interface. It does not establish that every InstallShield 5 distribution disables the same operations.

## Supported call contract

The [vendor's compatibility interface](https://docs.revenera.com/installshield30helplib/LangRef/LangrefCallDLLFx.htm) specifies:

```c
LONG APIENTRY PatchInstaller(HWND installerWindow,
                            LPLONG workerStatus,
                            LPSTR selectedFolder);
```

The script call has four arguments: the DLL's full filename, the exported function's name, a numeric variable, and a string variable. The last two are references to mutable script variables. They must not be encoded as literal values or general expression objects.

In this engine, the corresponding variable-reference argument tags are `0x32` for the numeric variable and `0x52` for the string variable. The parser preserves their variable indices; the native handler resolves those indices to `LPLONG` and `LPSTR`. It calls `LoadLibraryA` and `GetProcAddress`, invokes the export synchronously, stores its returned `LONG` in `LAST_RESULT`, and unloads the library after return.

The caller initializes the worker status to a nonzero failure value. It captures the function return immediately into a separate numeric variable, before formatting any message, and requires both return and worker status to equal zero. The bridge performs the actual process wait and receipt verification, so an older successful receipt cannot certify a failed or incomplete new operation.

The adapter treats the selected folder as a bounded Windows ANSI string, converts it for Unicode Windows APIs, and writes any diagnostic response within the script buffer's verified capacity. Unsupported paths or identities must fail before replacing the game executable.

## Authored workflow audit

The new main retains nine event records and calls the original SDK welcome, destination-selection and finish functions. Its registry read only supplies a suggested existing destination. A failed read, an empty value or a nonexistent directory keeps the fallback destination. The user's final directory selection is passed to the native component.

The supported native entries used by that workflow are:

| Operation | Opcode | Arguments | Native handler |
| --- | --- | --- | --- |
| `Enable` / `Disable` | `0x0001` / `0x0002` | 1 / 1 | `0x00466579` / `0x00466D5F` |
| `SetTitle` | `0x0004` | 3 | `0x00455A43` |
| `ExistsDir` | `0x000C` | 1 | `0x004622C5` |
| String assignment | `0x0013` | 2 | `0x0045D608` |
| Numeric assignment | `0x0021` | 2 | `0x004180CB` |
| Conditional branch | `0x0022` | 4 encoded operands | `0x004180F1` |
| `MessageBox` | `0x002A` | 2 | `0x00468C2D` |
| `exit` / event jump | `0x002B` / `0x002C` | 0 / 1 | `0x0044A0DE` / `0x00417B99` |
| `StrLength` | `0x002F` | 1 | `0x0045E15B` |
| `NumToStr` | `0x006E` | 2 | `0x0045D7F8` |
| Original SDK function call | `0x00B5` | Defined by its prototype | Special function-call handling |
| `RegDBSetDefaultRoot` | `0x0110` | 1 | `0x00447995` |
| String concatenation | `0x0124` | 3 | `0x0045D6E9` |
| Path concatenation | `0x0125` | 3 | `0x0045E682` |
| `RegDBGetKeyValueEx` | `0x0152` | 5 | `0x00447E77` |
| `CallDLLFx` | `0x013B` | 4 | `0x00441C78` |

`ExistsDir` returns zero for an existing directory and `-1` otherwise. `StrLength` writes the measured length to `LAST_RESULT`. Both contracts match the guarded destination-selection flow. The registry getter takes two input strings, followed by a numeric type variable, a string value variable and a numeric size variable. Its enabled handler writes the output variables only after a successful read and sets `LAST_RESULT` to zero on success.

Failure dialogs use `0x10`, which selects an error icon and the default OK button under the [Windows MessageBox contract](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-messageboxa). Silent mode skips those interactive error dialogs. A nonzero component result cannot reach the successful finish page.

## Validation limits

The worker's patch, identity, backup, rollback and process guards have separate isolated-copy validation. The dispatch audit verifies that the authored main calls enabled engine entries with compatible argument bindings and excludes the disabled operations listed above. Static checks also preserve the original opaque SDK event stream and its event identifiers.

The [saved authored-main audit](../verification/installshield-main-dispatch.json) passes **467 checks across 53 actions, nine events and 18 distinct opcodes**. It is bound to candidate script SHA-256 `abc02df7c019cae040782710e5272a6114b33e30041bd46832b61271db46c7cd` and the exact engine identity above. The checks cover dispatch availability, native argument counts, input versus reference bindings, slot bounds, branch targets, selected original SDK targets, error-dialog flags, the single CallDLLFx invocation, failure-status initialization, immediate separate return capture, 25 completion-gate combinations, script checksum and unchanged opaque SDK identity. These are static interface checks, not execution of the wizard.

This report does not certify a complete installation through the user's wizard. The earlier unprivileged silent check stopped before the patch script at legacy Error 432. The failed `UseDLL` run is user-observed evidence, while the corrected `CallDLLFx` workflow still requires end-to-end wizard confirmation. No game was launched for these checks, and no elevation or compatibility mechanism was bypassed.

The repository contains owned source, hashes and these findings. Original installer components, game executables, proprietary script/library bytes and personal installation paths are excluded.
