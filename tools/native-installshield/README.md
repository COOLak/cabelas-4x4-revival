# Original InstallShield workflow support

These original project sources let a privately rebuilt InstallShield 5 wizard
patch its chosen destination's existing executable instead of carrying a fixed
game executable. The supported identities and two byte edits
are the same as the Python patcher.

`PatchBridge.c` exports a native x86 `int __stdcall PatchGame(const char *,
const char *, const char *)`. The original engine calls it synchronously. The
bridge starts the windowless .NET Framework 4 worker, waits for termination and
checks its result receipt before reporting success to the wizard.

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
library bytes, appends its native import and variables, and recalculates the
InstallScript byte-sum checksum. `inspect_tables.py` reads metadata tables;
neither tool reconstructs the original script source. Run it with Python 3.9+:

```powershell
python build_script.py ORIGINAL_SETUP_INS OUTPUT_SETUP_INS --report SCRIPT_REPORT.json
```

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

**Complete wizard execution remains unverified.** A private-desktop silent test
without administrator rights stopped before the script with legacy Error 432.
The installed Microsoft launcher normally requests elevation. The testing did
not approve that prompt, replace the system uninstaller, alter compatibility
settings or execute the game. The existing Python patcher remains the fully
tested public installation route.

Original InstallShield executables, scripts, resources and SDK files are not
distributed here. Obtain and retain your own official installer. This directory
contains only the project's patch support and authoring sources.
