# Known issues and validation limits

## Gameplay validation

Version 1.2.1 has been checked through static analysis and isolated execution of the actual x86 depth-test routine. The game and graphics driver were not launched for verification. A complete mission run on a real installation remains useful follow-up validation.

The patch addresses a specific out-of-bounds read. It does not establish that every mission, vehicle, renderer, or wrapper configuration is stable.

## Other executable builds

The manifest identifies the exact official 1.2 executable and one compatible 1.2 variant, including their original and patched states. These binary identities define this release's support matrix. A matching version label with a different SHA-256 is a different baseline and requires its own review.

## Cached depth-surface pointer

Static analysis also found depth-surface setup that retrieves a pointer through DirectDraw `Lock`, calls `Unlock`, and retains the pointer for later reads. Microsoft's [Lock contract](https://learn.microsoft.com/en-us/windows/win32/api/ddraw/nf-ddraw-idirectdrawsurface7-lock) states that the pointer is invalid after the corresponding unlock.

This is a separate compatibility concern. Version 1.2.1 corrects the demonstrated coordinate boundary; it does not redesign surface locking. A valid-coordinate failure involving this cached pointer needs its own evidence and fix.

## Separate failed-lock crash

A separate, earlier crash record points to a null write in another renderer function after a surface-lock operation. It is a different fault address and failure path from the depth-buffer boundary incident. It is not included in the two-byte 1.2.1 correction.

The earlier failure needs further attribution of the lock result, surface state, and graphics-provider behavior before selecting a repair. Do not merge its diagnosis into the confirmed bottom-edge failure.

## Original operating systems and wrappers

The faulty boundary checks are present in the original official 1.2 executable. The captured failure occurred with a modern graphics provider and a high-resolution screen. That establishes an original game defect exposed in that environment; it does not establish the crash frequency on Windows XP, historical graphics drivers, or every modern wrapper.

Memory layout and protection can determine whether an invalid read immediately raises an exception, silently samples unrelated data, or appears harmless. A lower resolution or a different wrapper may change how the defect appears without correcting its bounds.

## Native installer component loading

A private original-InstallShield wizard reported a native support-component
load failure. The exact support DLL loads and exposes its entry point in an
independent 32-bit process, and static checks confirm the script framing,
load-result comparison and sufficient path buffers. This excludes those
specific explanations but does not identify the wizard failure. The authored
script collects its actual runtime paths and loader return code; full wizard
completion and a causal repair remain pending. The public Python patcher
provides the separately verified apply, verify and rollback route.
