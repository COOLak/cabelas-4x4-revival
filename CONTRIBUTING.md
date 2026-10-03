# Contributing

Thank you for helping preserve *Cabela's 4x4 Off-Road Adventure*. The most useful contribution is a small correction supported by evidence that another person can review.

## Report a problem

Include these details when you can:

1. Game executable version and SHA-256.
2. Windows version, graphics hardware, and graphics-wrapper name and version.
3. Mission, vehicle, resolution, and the shortest sequence that triggers the failure.
4. Exception code, faulting module, and fault offset from Windows Error Reporting.
5. Whether the same failure occurs with the official baseline and with the current community patch.

Separate what you observed from what you suspect. If you cannot reproduce the problem, say so. A single confirmed crash is still useful evidence.

Crash dumps can contain private process memory, paths, and account information. Do not attach raw dumps to a public issue. Start with a redacted exception summary, relevant register values, and the few memory or code details needed to explain the failure.

## Propose a fix

- Keep documentation, comments, issue descriptions, and pull requests in English.
- Target a specific failure and identify whether the game, wrapper, configuration, or another layer caused it.
- Record the exact supported baseline hash, expected original bytes, replacement bytes, and resulting executable hash.
- For multiple builds, identify each original and patched executable separately. Preserve each build's existing content and require its own verified rollback backup; include selection and cross-build backup regression checks.
- Explain control flow, register preservation, stack cleanup, and any changes to valid inputs when editing machine code.
- Add a meaningful regression check that fails before the fix and passes after it. Verify nearby valid cases as well as the failing boundary.
- Label static analysis, emulated execution, and real gameplay validation separately.
- Keep unrelated compatibility changes in separate fixes.

Use `fixes/001-depth-buffer-bounds/` and its [forensic report](docs/forensics/depth-buffer-bounds.md) as the structure for a new fix. Coordinate manifest-format changes with the patcher and tests.

## Keep the repository distributable

Submit patch descriptions and original project code. Do not commit proprietary game executables, game assets, raw crash dumps, third-party wrapper binaries, or files containing local account information. The repository's license applies to project contributions; it does not grant rights to redistribute the game.

Before opening a pull request, run the project's checks described in its test configuration and review the staged files for accidental binary or personal-data additions. Describe the resulting behavior and the evidence that supports it.
