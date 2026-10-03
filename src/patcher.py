"""Hash-guarded, reversible binary patcher; Python 3.9+, standard library only."""

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys
import tempfile
from typing import Any, Dict, List, Optional

DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "fixes" / "001-depth-buffer-bounds" / "manifest.json"
)
REPARSE_POINT = 0x400


class PatchError(Exception):
    """An expected refusal that leaves the executable untouched."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pe_checksum_offset(data: bytes) -> int:
    """Locate CheckSum in a structurally bounded PE32/PE32+ optional header."""
    if len(data) < 64 or data[:2] != b"MZ":
        raise PatchError("The executable has no valid DOS header.")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if pe < 64 or pe + 24 > len(data) or data[pe:pe + 4] != b"PE\0\0":
        raise PatchError("The executable has no valid PE header.")
    optional_size = struct.unpack_from("<H", data, pe + 20)[0]
    optional = pe + 24
    if optional_size < 68 or optional + optional_size > len(data):
        raise PatchError("The PE optional header is truncated.")
    if struct.unpack_from("<H", data, optional)[0] not in (0x10B, 0x20B):
        raise PatchError("Unsupported PE optional-header format.")
    return optional + 64


def pe_checksum(data: bytes) -> int:
    """Compute the IMAGEHLP checksum, excluding its existing four-byte value."""
    offset = pe_checksum_offset(data)
    total = 0
    for i in range(0, len(data), 2):
        if offset <= i < offset + 4:
            continue
        word = data[i] | ((data[i + 1] << 8) if i + 1 < len(data) else 0)
        total += word
        total = (total & 0xFFFF) + (total >> 16)
    total = (total & 0xFFFF) + (total >> 16)
    return ((total & 0xFFFF) + len(data)) & 0xFFFFFFFF


def load_manifest(path: Path) -> Dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int or manifest["schema_version"] not in (1, 2):
            raise ValueError("unsupported schema")
        version = manifest["patch_version"]
        target = manifest["target_file"]
        if not isinstance(version, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){2}", version):
            raise ValueError("invalid patch version")
        if (
            not isinstance(target, str) or not target or target in (".", "..")
            or any(c in target for c in ("/", "\\", ":", "\0"))
            or target.endswith((".", " "))
        ):
            raise ValueError("target must be a plain filename")
        builds = supported_builds(manifest)
        if not isinstance(builds, list) or not builds:
            raise ValueError("empty supported-build list")
        build_ids, hashes = set(), set()
        for build in builds:
            if not isinstance(build, dict):
                raise ValueError("invalid supported build")
            if manifest["schema_version"] == 2:
                if not isinstance(build["id"], str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", build["id"]):
                    raise ValueError("invalid build ID")
                if build["id"] in build_ids:
                    raise ValueError("duplicate build ID")
                build_ids.add(build["id"])
                if not isinstance(build["name"], str) or not build["name"].strip():
                    raise ValueError("invalid build name")
                if not isinstance(build["language"], str) or not re.fullmatch(r"[a-z]{2,3}(?:-[A-Z]{2})?", build["language"]):
                    raise ValueError("invalid build language")
            for identity in (build["source"], build["patched"]):
                if not re.fullmatch(r"[0-9a-f]{64}", identity["sha256"]):
                    raise ValueError("invalid SHA-256")
                if type(identity["size"]) is not int or identity["size"] < 64:
                    raise ValueError("invalid executable size")
                if identity["sha256"] in hashes:
                    raise ValueError("ambiguous executable identity")
                hashes.add(identity["sha256"])
            if build["source"]["size"] != build["patched"]["size"]:
                raise ValueError("this patcher only supports fixed-size changes")
        if manifest.get("checksum") != "pe":
            raise ValueError("unsupported checksum policy")
        changes = manifest["changes"]
        if not isinstance(changes, list) or not changes:
            raise ValueError("empty changes")
        used = set()
        for change in changes:
            at = change["offset"]
            if type(at) is not int or at < 0:
                raise ValueError("invalid change offset")
            before = bytes.fromhex(change["before"])
            after = bytes.fromhex(change["after"])
            if not before or len(before) != len(after):
                raise ValueError("changes must be nonempty and fixed-size")
            positions = set(range(at, at + len(before)))
            if any(at + len(before) > build["source"]["size"] for build in builds) or used & positions:
                raise ValueError("overlapping or out-of-file changes")
            used |= positions
        return manifest
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PatchError("Cannot read a valid patch manifest: {}".format(exc)) from exc


def supported_builds(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Schema 1 remains usable for existing single-build custom manifests."""
    return manifest["builds"] if manifest.get("schema_version") == 2 else [manifest]


def select_build(data: bytes, manifest: Dict[str, Any],
                 identity: Optional[str] = None) -> Dict[str, Any]:
    """Recognize an original or patched build without guessing from its language."""
    identity = digest(data) if identity is None else identity
    matches = [build for build in supported_builds(manifest)
               if any(identity == state["sha256"] and len(data) == state["size"]
                      for state in (build["source"], build["patched"]))]
    if not matches:
        raise PatchError("Unsupported or modified executable. No executable was changed.")
    if len(matches) != 1:
        raise PatchError("Ambiguous executable identity; no executable was changed.")
    return matches[0]


def make_patched(data: bytes, manifest: Dict[str, Any]) -> bytes:
    identity = digest(data)
    build = select_build(data, manifest, identity)
    if len(data) != build["source"]["size"] or identity != build["source"]["sha256"]:
        raise PatchError("Unsupported executable. The source size or SHA-256 does not match.")
    checksum_offset = pe_checksum_offset(data)
    output = bytearray(data)
    for change in manifest["changes"]:
        at = change["offset"]
        old, new = bytes.fromhex(change["before"]), bytes.fromhex(change["after"])
        if at < checksum_offset + 4 and at + len(old) > checksum_offset:
            raise PatchError("A code change overlaps the PE checksum field.")
        if data[at:at + len(old)] != old:
            raise PatchError("Original instruction mismatch at 0x{:x}.".format(at))
        output[at:at + len(old)] = new
    struct.pack_into("<I", output, checksum_offset, pe_checksum(bytes(output)))
    result = bytes(output)
    if digest(result) != build["patched"]["sha256"]:
        raise PatchError("The reconstructed patch does not match its expected SHA-256.")
    return result


def _check_component(path: Path, must_exist: bool = True) -> Optional[os.stat_result]:
    try:
        info = path.lstat()
    except FileNotFoundError:
        if must_exist:
            raise PatchError("Required path does not exist: {}".format(path))
        return None
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & REPARSE_POINT:
        raise PatchError("Symbolic links and reparse points are not supported: {}".format(path))
    return info


def _check_ancestors(path: Path) -> None:
    for component in reversed((path,) + tuple(path.parents)):
        _check_component(component)


def game_root(path: Path) -> Path:
    root = Path(os.path.abspath(os.fspath(path.expanduser())))
    _check_ancestors(root)
    if not root.is_dir():
        raise PatchError("The game directory is not a directory.")
    return root


def contained(root: Path, path: Path, must_exist: bool = False) -> Path:
    absolute = Path(os.path.abspath(os.fspath(path)))
    try:
        relative = absolute.relative_to(root)
    except ValueError as exc:
        raise PatchError("A patch path escaped the game directory.") from exc
    if not relative.parts:
        raise PatchError("A file operation cannot target the game directory itself.")
    current = root
    for part in relative.parts:
        current = current / part
        _check_component(current, must_exist=must_exist)
    return absolute


def read_file(root: Path, path: Path) -> bytes:
    contained(root, path, must_exist=True)
    if not path.is_file():
        raise PatchError("Expected a regular file: {}".format(path))
    return path.read_bytes()


def running_game_pids() -> List[int]:
    """Passively enumerate processes; never activate, stop, or launch an app."""
    if os.name != "nt":
        return []
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        function = getattr(kernel, name)
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        function.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise PatchError("Cannot check whether the game is running.")
    entry = ProcessEntry()
    entry.dwSize = ctypes.sizeof(entry)
    found = []
    try:
        more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.szExeFile.casefold() == "4x4 adventure.exe":
                found.append(entry.th32ProcessID)
            more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise PatchError("Process enumeration failed; no executable was changed.")
    finally:
        kernel.CloseHandle(snapshot)
    return found


def assert_stopped() -> None:
    if running_game_pids():
        raise PatchError("Close all 4x4 Adventure game instances before applying or rolling back.")


def _atomic_write(root: Path, target: Path, data: bytes, expected_current: bytes,
                  backup: Path, expected_backup: bytes) -> None:
    """Stage and flush first; a failed replace cannot partially overwrite target."""
    contained(root, target, must_exist=True)
    descriptor, name = tempfile.mkstemp(prefix=".revival-stage-", suffix=".tmp", dir=str(root))
    stage = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(stage, stat.S_IMODE(target.stat().st_mode))
        contained(root, stage, must_exist=True)
        if stage.read_bytes() != data:
            raise PatchError("The staged file failed verification.")
        assert_stopped()
        if read_file(root, target) != expected_current:
            raise PatchError("The executable changed during preparation; replacement refused.")
        if read_file(root, backup) != expected_backup:
            raise PatchError("The rollback backup changed during preparation; replacement refused.")
        os.replace(stage, target)
        if read_file(root, target) != data:
            raise PatchError("Replacement verification failed. Preserve the rollback backup.")
    finally:
        if stage.exists():
            contained(root, stage, must_exist=True)
            stage.unlink()


def _preserve_backup(root: Path, backup: Path, source: bytes) -> None:
    contained(root, backup)
    if _check_component(backup, must_exist=False) is not None:
        if read_file(root, backup) != source:
            raise PatchError("The existing rollback backup differs; it will not be replaced.")
        return
    contained(root, backup.parent)
    backup.parent.mkdir(exist_ok=True)
    contained(root, backup.parent, must_exist=True)
    created = False
    try:
        with backup.open("xb") as stream:
            created = True
            stream.write(source)
            stream.flush()
            os.fsync(stream.fileno())
        if read_file(root, backup) != source:
            raise PatchError("Rollback backup verification failed.")
    except BaseException:
        if created:
            contained(root, backup, must_exist=True)
            backup.unlink()
        raise


def operate(action: str, directory: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
    if action not in ("apply", "verify", "rollback"):
        raise PatchError("Unsupported action.")
    root = game_root(directory)
    target = contained(root, root / manifest["target_file"], must_exist=True)
    backup = contained(root, root / ("revival-backup-" + manifest["patch_version"]) / manifest["target_file"])
    current = read_file(root, target)
    identity = digest(current)
    build = select_build(current, manifest, identity)
    source, patched = build["source"], build["patched"]
    if identity == source["sha256"] and len(current) == source["size"]:
        state = "original"
    elif identity == patched["sha256"] and len(current) == patched["size"]:
        state = "patched"
    else:
        raise PatchError("Unsupported or modified executable. No executable was changed.")
    result = {"action": action, "state": state, "patch_version": manifest["patch_version"],
              "executable": str(target), "sha256": identity, "backup": str(backup)}
    if manifest.get("schema_version") == 2:
        result.update(build=build["id"], build_name=build["name"], language=build["language"])
    if action == "verify":
        return result
    assert_stopped()
    if action == "apply":
        if state == "patched":
            saved = read_file(root, backup)
            if digest(saved) != source["sha256"] or len(saved) != source["size"]:
                raise PatchError("The patched file has no valid rollback backup.")
            result["result"] = "already applied"
            return result
        replacement = make_patched(current, manifest)
        _preserve_backup(root, backup, current)
        _atomic_write(root, target, replacement, current, backup, current)
        result.update(state="patched", sha256=digest(replacement), result="applied")
    else:
        if state == "original":
            result["result"] = "already original"
            return result
        replacement = read_file(root, backup)
        if digest(replacement) != source["sha256"] or len(replacement) != source["size"]:
            raise PatchError("The rollback backup is missing or modified; rollback refused.")
        _atomic_write(root, target, replacement, current, backup, replacement)
        result.update(state="original", sha256=digest(replacement), result="rolled back")
    return result


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Apply, verify, or roll back the unofficial Cabela's 4x4 1.2.1 fix.")
    parser.add_argument("action", choices=("apply", "verify", "rollback"))
    parser.add_argument("--game-dir", required=True, type=Path, help="Existing supported game directory; its current language is preserved.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="Patch manifest; the bundled manifest automatically recognizes supported builds.")
    args = parser.parse_args(argv)
    try:
        result = operate(args.action, args.game_dir, load_manifest(args.manifest))
    except (PatchError, OSError) as exc:
        print("Refused: {}".format(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
