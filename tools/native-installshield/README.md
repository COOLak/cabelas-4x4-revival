# Original InstallShield workflow support

These original project sources let a privately rebuilt InstallShield 5 wizard
patch its chosen destination's existing executable instead of carrying a fixed
game executable. The supported identities and two byte edits
are the same as the Python patcher.

`PatchBridge.c` exports the native x86 `LONG WINAPI PatchInstaller(HWND,
LONG *, LPSTR)` interface expected by InstallShield's built-in `CallDLLFx`.
The string argument receives a copy of the selected game directory; a failure
returns a short English explanation through that copy. The bridge locates the
worker beside its own DLL, creates a fresh temporary receipt directory, starts
the windowless .NET Framework 4 worker, and waits for its real exit code and
verified receipt before reporting success to the wizard. The separate
`PatchGame` export remains available to the direct-interface regression suite.

`PatchBackend.cs` handles strict build detection, backup, patch, verification,
idempotence and rollback. It refuses unknown binaries, unsafe file paths,
tampered backups and a running game or launcher. The backup directory is
`cabela4x4-patch-1.2.1-backups/<original SHA-256>/` in the game folder.

Build the managed worker with the installed .NET Framework 4 C# compiler:

```powershell
./build.ps1
```

Build the native bridge using an existing Open Watcom installation:

```powershell
./build-bridge.ps1 -WatcomDirectory "C:\Tools\Watcom"
```

Only `Cabela4x4PatchBridge.dll` and `Cabela4x4PatchBackend.exe` are patch support
payloads. Compiler outputs, test copies and original installer files stay out
of this repository and its source releases.

`build_script.py` authors nine new main event records in a user's original
official 1.2 `setup.ins`. It keeps all original dialog event IDs and opaque
library bytes, appends its working variables, and recalculates the
InstallScript byte-sum checksum. `inspect_tables.py` reads metadata tables;
neither tool reconstructs the original script source. Run it with Python 3.9+:

```powershell
python build_script.py ORIGINAL_SETUP_INS OUTPUT_SETUP_INS --report SCRIPT_REPORT.json
```

At each launch the workflow reads `Path1` from
`HKCU\Software\Activision Value\Cabela's Off-road Adventure` to prefill the
destination dialog. A missing, empty or nonexistent registered directory uses
`C:\Games` as a fallback; the user can choose a different existing game folder.
No game registry values are written.

The workflow shows the original welcome and destination dialogs, patches that
selected destination through the bridge, and reaches the original finish dialog
only after verified success. Cancellation exits; errors give a diagnostic and
allow another selection. No game-launch operation is authored. Set the private
installer's `SETUP.INI` to `EnableLangDlg=N`; its original `setup.lid` declares
English only. Remove the original CAB's game payloads from any private rebuild.
The private package uses the original 16-bit launcher and already-installed
Microsoft support. It contains no command-file preparation step.

The native interface and worker passed [165 isolated-copy checks](../../docs/verification/v1.2.1-native-backend.json),
including a real x86 stdcall host, both supported executable builds and synchronous exit-code
propagation. Static checks confirmed the authored script framing, checksum,
allocated variables, dialog bindings and unchanged original dialog library.

The corrected adapter passed [131 interface checks](../../docs/verification/v1.2.1-native-interface.json):
107 direct x86 adapter checks and 24 checks through the genuine original
`CallDLLFx` native handler. The handler patched isolated copies of both supported
builds to their exact expected hashes, refused an unknown executable, and
returned failure for a missing DLL. All caller-buffer guards remained intact.
These tests invoked the handler directly without running the wizard entry point.

The earlier private wizard failed because this original engine's dispatch table
has no handler for `UseDLL`. Its dispatcher returned `-1` before trying to load
the DLL. The same restriction disabled the script's INI diagnostics. The
workflow now uses the engine's enabled `CallDLLFx` handler and performs receipt
I/O in the native bridge. See the [interface investigation](../../docs/forensics/installshield-native-interface.md).

An actual user-run wizard applied the patch successfully: the installed hash,
intact original backup and fresh receipt were independently checked. See the
[installation verification](../../docs/verification/v1.2.1-user-install.json).
The subsequent text-only revision uses short welcome, destination and completion
messages. An unprivileged silent automation still stops before the script with
legacy Error 432; the installed Microsoft launcher normally requests elevation.

Original InstallShield executables, scripts, resources and SDK files are not
distributed here. Obtain and retain your own official installer. This directory
contains only the project's patch support and authoring sources.
