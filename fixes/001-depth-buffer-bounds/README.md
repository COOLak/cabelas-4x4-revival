# 001: Depth-buffer bounds

Community version: **1.2.1**. Base version: official **1.2**, released
July 12, 2001. This fix is unofficial.

A projected visual-effect point can land exactly on the screen's width or
height after conversion to integer coordinates. The game checks `x > width`
and `y > height`, then samples the 16-bit depth buffer. Coordinates equal to
the dimensions pass those checks even though the valid ranges end at
`width - 1` and `height - 1`.

The fix changes both comparisons to reject equality. It retains the original
off-screen return path, branch destinations, instruction lengths and calling
convention. Interior coordinates keep the original behavior. The PE checksum
is recomputed after applying the two instruction changes.

## Patch map

| File offset | Virtual address | Original | Patched | Effect |
| --- | --- | --- | --- | --- |
| `0xD2D5` | `0x40D2D5` | `7F` | `7D` | `JG` -> `JGE` for x |
| `0xD2DA` | `0x40D2DA` | `7F` | `7D` | `JG` -> `JGE` for y |

The faulting lookup is at `0x40D2F4`: `mov si, word ptr [edx + ecx*2]`.
The shared rejection target is `0x40D308`, which returns false and restores
the function's saved registers.

## Supported executables

Filename: `4x4 Adventure.exe`. The patcher automatically selects the exact
supported build by its size and SHA-256 in either original or patched state.
Its English interface preserves the installed build's existing content.

### Official 1.2

Size: **749568 bytes**.

Original official 1.2 SHA-256:

```text
e9c5d3932dc87accd8a1d94a264de1badbe7edac73afaf1fa78181a30c624d1c
```

Patched community 1.2.1 SHA-256:

```text
9bdb9bfaa4d91f12bc81c0db1a05765c03538fb81f0a523c978733902ba2d3c6
```

### Compatible 1.2 variant

Size: **757760 bytes**. Its bounds-test code matches the official baseline;
the same code edits and PE checksum update preserve its other content.
Build ID: `compatible-1-2-variant`. Language metadata: unspecified (`und`).
This compatibility identity is not an official release designation.

Original SHA-256:

```text
ab517697d459912a924f8502b1be5b38d69c3bd4e8a3011689c5eca16077f765
```

Patched SHA-256:

```text
a54624101f8b04ed5539703ea558705483fc06974c1ca00eaf0964726d408faf
```

Executable identities not listed in the manifest fail the identity check.
The repository distributes English patch instructions and tooling, without
game assets or original/patched game executables.

## Apply, verify, and roll back

Run from the repository root with Python 3.9 or later. Close the game before
applying or rolling back. No additional Python packages are required.

```powershell
python src/patcher.py verify --game-dir "C:\Games\Cabelas 4x4"
python src/patcher.py apply --game-dir "C:\Games\Cabelas 4x4"
python src/patcher.py rollback --game-dir "C:\Games\Cabelas 4x4"
```

Replace the example directory with your installation. Verification is
read-only. Apply preserves the original executable at
`revival-backup-1.2.1/4x4 Adventure.exe` inside that installation and replaces
the executable using a verified temporary file. Rollback restores that exact
backup. Repeat apply/rollback operations preserve the backup; modified game
executables or backups are refused. A backup from the other supported build
cannot be used for apply or rollback.

The patcher does not launch the game or change profiles, controls, graphics
configuration, resources, textures, launcher files, or system settings.
Symbolic links and Windows reparse points are refused for patch targets.

## Evidence and limits

The failure was traced to a projected point at `(851.6439, 1800.6218)` on a
2880 by 1800 viewport. After integer conversion, row 1800 was accepted and a
depth read landed 1702 bytes beyond the nominal buffer. The offending helper
and its dimension initialization are identical to the official 1.2 binary.

An isolated x86 replay of the actual helper validated the corrected bounds
and preserved register/stack behavior. The public test suite separately
exercises the patcher's checksum, identity checks, backup lifecycle and
failure handling using synthetic PE files. No game or driver is executed in
CI. In-game verification of this fix has not been performed.

This fix addresses the demonstrated depth-buffer bounds defect. It does not
claim to resolve every crash or the separate lifetime assumptions around
cached DirectDraw surface pointers.

See [manifest.json](manifest.json) for machine-readable offsets and identities.

## Manifest format

The bundled schema-version-2 manifest lists each supported build's ID,
human-readable description, language metadata, and original/patched identities in
`builds`. Byte changes and the PE-checksum policy are shared. Build IDs and
all executable hashes must be unique, and every change must fit every build.
Selection requires both the size and hash; it does not infer a build from
filenames, language labels, or version strings.

Schema-version-1 custom manifests with a single top-level `source` and
`patched` pair remain supported through `--manifest PATH`.
