"""Synthetic PE fixtures only: no game binaries, profiles, or assets."""

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import patcher


def fixture():
    data = bytearray((i * 17 + 3) % 256 for i in range(1025))
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", data, 0x84, 0x14C)
    struct.pack_into("<H", data, 0x86, 0)
    struct.pack_into("<H", data, 0x94, 224)
    struct.pack_into("<H", data, 0x98, 0x10B)
    struct.pack_into("<I", data, 0xD8, 0xABCDEF01)
    data[0x300] = data[0x308] = 0x7F
    original = bytes(data)
    data[0x300] = data[0x308] = 0x7D
    # Golden checksum independently calculated with pefile during development.
    # The tests themselves need only the standard library.
    struct.pack_into("<I", data, 0xD8, 8953)
    expected = bytes(data)
    manifest = {
        "schema_version": 1,
        "patch_version": "1.2.1",
        "target_file": "4x4 Adventure.exe",
        "source": {"sha256": patcher.digest(original), "size": len(original)},
        "patched": {"sha256": patcher.digest(expected), "size": len(expected)},
        "checksum": "pe",
        "changes": [
            {"offset": 0x300, "before": "7f", "after": "7d"},
            {"offset": 0x308, "before": "7f", "after": "7d"},
        ],
    }
    return original, expected, manifest


class PatcherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.game = self.base / "A game with spaces"
        self.game.mkdir()
        self.original, self.expected, self.manifest = fixture()
        self.target = self.game / "4x4 Adventure.exe"
        self.target.write_bytes(self.original)
        self.backup = self.game / "revival-backup-1.2.1" / self.target.name
        self.manifest_file = self.base / "fixture.json"
        self.manifest_file.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.guard = mock.patch.object(patcher, "running_game_pids", return_value=[])
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def operate(self, action):
        return patcher.operate(action, self.game, self.manifest)

    def snapshot(self):
        return {str(p.relative_to(self.game)): p.read_bytes()
                for p in self.game.rglob("*") if p.is_file()}

    def test_checksum_matches_independent_golden_and_ignores_existing_value(self):
        self.assertEqual(patcher.pe_checksum_offset(self.original), 0xD8)
        self.assertEqual(patcher.pe_checksum(self.original), 8957)
        self.assertEqual(patcher.pe_checksum(self.expected), 8953)
        changed = bytearray(self.original)
        struct.pack_into("<I", changed, 0xD8, 0)
        self.assertEqual(patcher.pe_checksum(changed), 8957)
        self.assertEqual(patcher.digest(self.expected),
                         "7dc953711815298b87ff6f5f26a0acc73ca120566bd7ebc1d865d33a71bc479d")

    def test_verify_is_read_only_in_both_states(self):
        before = self.snapshot()
        self.assertEqual(self.operate("verify")["state"], "original")
        self.assertEqual(self.snapshot(), before)
        self.operate("apply")
        before = self.snapshot()
        self.assertEqual(self.operate("verify")["state"], "patched")
        self.assertEqual(self.snapshot(), before)

    def test_complete_lifecycle_is_idempotent_and_keeps_original_backup(self):
        unrelated = self.game / "player.prf"
        unrelated.write_bytes(b"Synthetic profile: preserve byte for byte")
        self.assertEqual(self.operate("apply")["result"], "applied")
        self.assertEqual(self.target.read_bytes(), self.expected)
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.assertEqual(self.operate("apply")["result"], "already applied")
        self.assertEqual(self.operate("rollback")["result"], "rolled back")
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(self.operate("rollback")["result"], "already original")
        self.assertEqual(self.operate("apply")["result"], "applied")
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.assertEqual(unrelated.read_bytes(), b"Synthetic profile: preserve byte for byte")

    def test_unknown_source_is_refused_without_creating_backup(self):
        self.target.write_bytes(b"unsupported executable")
        before = self.snapshot()
        with self.assertRaises(patcher.PatchError):
            self.operate("apply")
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.backup.parent.exists())

    def test_different_existing_backup_is_never_overwritten(self):
        self.backup.parent.mkdir()
        self.backup.write_bytes(b"a different backup")
        before = self.snapshot()
        with self.assertRaises(patcher.PatchError):
            self.operate("apply")
        self.assertEqual(self.snapshot(), before)

    def test_modified_patched_executable_blocks_rollback(self):
        self.operate("apply")
        changed = bytearray(self.expected)
        changed[-1] ^= 0xFF
        self.target.write_bytes(changed)
        before = self.snapshot()
        with self.assertRaises(patcher.PatchError):
            self.operate("rollback")
        self.assertEqual(self.snapshot(), before)

    def test_modified_backup_blocks_rollback_and_repeated_apply(self):
        self.operate("apply")
        self.backup.write_bytes(b"modified backup")
        before = self.snapshot()
        for action in ("rollback", "apply"):
            with self.assertRaises(patcher.PatchError):
                self.operate(action)
        self.assertEqual(self.snapshot(), before)

    def test_missing_backup_blocks_rollback(self):
        self.operate("apply")
        self.backup.unlink()
        with self.assertRaises(patcher.PatchError):
            self.operate("rollback")
        self.assertEqual(self.target.read_bytes(), self.expected)

    def test_failed_atomic_apply_keeps_source_and_valid_backup(self):
        with mock.patch.object(patcher.os, "replace", side_effect=OSError("simulated replacement failure")):
            with self.assertRaises(OSError):
                self.operate("apply")
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.assertFalse(list(self.game.glob(".revival-stage-*")))
        self.assertEqual(self.operate("apply")["state"], "patched")

    def test_failed_atomic_rollback_keeps_patch_and_backup(self):
        self.operate("apply")
        with mock.patch.object(patcher.os, "replace", side_effect=OSError("simulated replacement failure")):
            with self.assertRaises(OSError):
                self.operate("rollback")
        self.assertEqual(self.target.read_bytes(), self.expected)
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.assertFalse(list(self.game.glob(".revival-stage-*")))

    def test_target_change_during_preparation_is_preserved(self):
        def external_change():
            self.target.write_bytes(b"external modification")
        calls = iter((False, True))
        with mock.patch.object(patcher, "assert_stopped",
                               side_effect=lambda: external_change() if next(calls) else None):
            with self.assertRaises(patcher.PatchError):
                self.operate("apply")
        self.assertEqual(self.target.read_bytes(), b"external modification")
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.assertFalse(list(self.game.glob(".revival-stage-*")))

    def test_game_running_blocks_writes_but_allows_read_only_verify(self):
        with mock.patch.object(patcher, "running_game_pids", return_value=[1234]):
            self.assertEqual(self.operate("verify")["state"], "original")
            with self.assertRaises(patcher.PatchError):
                self.operate("apply")
        self.assertFalse(self.backup.exists())
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_backup_change_during_preparation_blocks_replacement(self):
        def external_change():
            self.backup.write_bytes(b"external backup modification")
        calls = iter((False, True))
        with mock.patch.object(patcher, "assert_stopped",
                               side_effect=lambda: external_change() if next(calls) else None):
            with self.assertRaises(patcher.PatchError):
                self.operate("apply")
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(self.backup.read_bytes(), b"external backup modification")
        self.assertFalse(list(self.game.glob(".revival-stage-*")))

    def test_opcode_and_output_digest_guards(self):
        bad = copy.deepcopy(self.manifest)
        bad["changes"][0]["before"] = "7e"
        with self.assertRaises(patcher.PatchError):
            patcher.operate("apply", self.game, bad)
        bad = copy.deepcopy(self.manifest)
        bad["patched"]["sha256"] = "0" * 64
        with self.assertRaises(patcher.PatchError):
            patcher.operate("apply", self.game, bad)
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertFalse(self.backup.exists())

    def test_invalid_manifest_target_and_overlap_are_rejected(self):
        for target in ("../outside.exe", "..\\outside.exe", "C:outside.exe", "unsafe."):
            bad = copy.deepcopy(self.manifest)
            bad["target_file"] = target
            self.manifest_file.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(patcher.PatchError):
                patcher.load_manifest(self.manifest_file)
        bad = copy.deepcopy(self.manifest)
        bad["changes"][1] = dict(bad["changes"][0])
        self.manifest_file.write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaises(patcher.PatchError):
            patcher.load_manifest(self.manifest_file)

    def test_malformed_pe_is_rejected(self):
        for data in (b"MZ", b"X" * 1025):
            with self.assertRaises(patcher.PatchError):
                patcher.pe_checksum(data)
        changed = bytearray(self.original)
        struct.pack_into("<I", changed, 0x3C, len(changed) - 8)
        with self.assertRaises(patcher.PatchError):
            patcher.pe_checksum(changed)

    def test_escape_and_reparse_attributes_are_rejected(self):
        with self.assertRaises(patcher.PatchError):
            patcher.contained(self.game, self.base / "outside.exe")
        fake = SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400)
        with mock.patch.object(Path, "lstat", return_value=fake):
            with self.assertRaises(patcher.PatchError):
                patcher._check_component(self.target)

    def test_symlink_target_is_rejected_and_outside_file_preserved(self):
        outside = self.base / "outside.exe"
        outside.write_bytes(self.original)
        self.target.unlink()
        try:
            self.target.symlink_to(outside)
        except OSError as exc:
            self.skipTest("This host does not permit test symlinks: {}".format(exc))
        with self.assertRaises(patcher.PatchError):
            self.operate("apply")
        self.assertEqual(outside.read_bytes(), self.original)

    def test_symlink_backup_directory_is_rejected(self):
        outside = self.base / "outside-backups"
        outside.mkdir()
        try:
            self.backup.parent.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest("This host does not permit test symlinks: {}".format(exc))
        with self.assertRaises(patcher.PatchError):
            self.operate("apply")
        self.assertFalse(list(outside.iterdir()))
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_cli_custom_fixture_manifest_and_refusal_exit_code(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(patcher.main(["apply", "--game-dir", str(self.game),
                                          "--manifest", str(self.manifest_file)]), 0)
        self.assertEqual(json.loads(output.getvalue())["state"], "patched")
        self.target.write_bytes(b"modified")
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            self.assertEqual(patcher.main(["rollback", "--game-dir", str(self.game),
                                          "--manifest", str(self.manifest_file)]), 2)
        self.assertIn("Refused:", error.getvalue())


class WindowsProcessTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows-only passive process enumeration")
    def test_process_enumeration_smoke(self):
        self.assertTrue(all(isinstance(pid, int) and pid > 0
                            for pid in patcher.running_game_pids()))


if __name__ == "__main__":
    unittest.main()
