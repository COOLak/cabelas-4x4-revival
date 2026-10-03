# Changelog

Community release numbers describe this project's fixes. They do not replace the publisher's official release history.

## 1.2.1 — 2026-10-04

### Fixed

- Reject depth-buffer sample coordinates equal to the screen width or height. The official English 1.2 executable admitted these invalid border coordinates and could read beyond the buffer while checking whether a visual effect should be drawn.
- Preserve the game's existing false-return path for effects outside the screen. The fix changes two short conditional-branch opcodes, leaving interior coordinates and the executable's instruction layout unchanged.

### Added

- A hash-checked patcher with apply, verify, and rollback commands.
- A machine-readable fix manifest, forensic explanation, regression checks, and remaining-issue notes.
- An English project site in the repository README with original field-manual artwork.

### Validation

- Offline replay of the actual x86 routine: **61 original/patched case pairs and 177 checks**.
- The captured bottom-edge input is rejected before a depth read after the fix.
- Live gameplay and graphics-driver verification remain pending. No in-game validation was performed for this release.

### Scope

- Supports the exact official English 1.2 baseline identified in the fix manifest.
- Addresses the demonstrated depth-buffer bounds failure. Other renderer and compatibility issues remain open.
