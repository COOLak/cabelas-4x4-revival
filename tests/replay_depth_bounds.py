#!/usr/bin/env python3
"""Verify the depth-buffer boundary fix by executing the game's x86 helper.

Requires a separately obtained, unmodified English v1.2 executable. This script
does not launch the game or edit that executable. It contains no game binaries.

Install requirements-replay.txt, then run:
    python replay_depth_bounds.py --exe /path/to/game.exe
Optional --output saves detailed JSON; --summary-output saves compact JSON.
"""

import argparse
import hashlib
import itertools
import json
import struct
from pathlib import Path

import pefile
from unicorn import (
    UC_ARCH_X86,
    UC_HOOK_CODE,
    UC_HOOK_MEM_INVALID,
    UC_HOOK_MEM_READ,
    UC_MODE_32,
    Uc,
    UcError,
    __version__ as unicorn_version,
)
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EFLAGS,
    UC_X86_REG_EIP,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
    UC_X86_REG_FPCW,
)

EXPECTED_SHA256 = "e9c5d3932dc87accd8a1d94a264de1badbe7edac73afaf1fa78181a30c624d1c"
ENTRY = 0x0040D2B0
RETURN = 0x04000000
RENDERER = 0x02000000
POINT = 0x03000000
STACK = 0x01000000
DEPTH = 0x1515A000
PATCHES = ((0x0040D2D5, 0x7F, 0x7D), (0x0040D2DA, 0x7F, 0x7D))
SAVED = {"EBX": 0x12223334, "ESI": 0x24445556, "EDI": 0x36667778, "EBP": 0x4888999A}
REGISTERS = {
    "EBX": UC_X86_REG_EBX,
    "ESI": UC_X86_REG_ESI,
    "EDI": UC_X86_REG_EDI,
    "EBP": UC_X86_REG_EBP,
}


def page_size(size):
    return (size + 4095) & ~4095


class Replay:
    def __init__(self, exe):
        self.exe = exe
        source = exe.read_bytes()
        if hashlib.sha256(source).hexdigest() != EXPECTED_SHA256:
            raise ValueError("Unsupported executable: this test requires unmodified English v1.2.")
        pe = pefile.PE(data=source)
        self.base = pe.OPTIONAL_HEADER.ImageBase
        self.image_size = page_size(pe.OPTIONAL_HEADER.SizeOfImage)
        self.image = pe.get_memory_mapped_image()
        for address, before, _ in PATCHES:
            if self.image[address - self.base] != before:
                raise ValueError("The original branch opcode does not match the expected executable.")

    def run(self, width, height, x, y, depth, sample, patched):
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        uc.mem_map(self.base, self.image_size)
        uc.mem_write(self.base, self.image)
        if patched:
            for address, _, after in PATCHES:
                uc.mem_write(address, bytes([after]))
        for address, size in (
            (STACK, 0x10000),
            (RENDERER, 0x20000),
            (POINT, 0x1000),
            (RETURN, 0x1000),
        ):
            uc.mem_map(address, size)

        pitch = width * 2
        allocation_size = pitch * height
        uc.mem_map(DEPTH, page_size(allocation_size))
        int_x, int_y = int(x), int(y)
        if 0 <= int_x < width and 0 <= int_y < height:
            uc.mem_write(DEPTH + int_y * pitch + int_x * 2, struct.pack("<H", sample))
        for offset, value in (
            (0x1C, width),
            (0x20, height),
            (0x6174, DEPTH),
            (0x617C, pitch),
        ):
            uc.mem_write(RENDERER + offset, struct.pack("<I", value))
        uc.mem_write(POINT, struct.pack("<fff", x, y, depth))
        initial_esp = STACK + 0x8000
        uc.mem_write(initial_esp, struct.pack("<II", RETURN, POINT))
        uc.reg_write(UC_X86_REG_ESP, initial_esp)
        uc.reg_write(UC_X86_REG_ECX, RENDERER)
        uc.reg_write(UC_X86_REG_EFLAGS, 0x202)
        uc.reg_write(UC_X86_REG_FPCW, 0x37F)
        for name, value in SAVED.items():
            uc.reg_write(REGISTERS[name], value)

        state = {
            "returned": False,
            "depth_reads": [],
            "bounds_fault": None,
            "emulator_error": None,
            "instructions": 0,
        }

        def on_code(machine, address, size, user_data):
            state["instructions"] += 1
            if address == RETURN:
                state["returned"] = True
                machine.emu_stop()

        def record_read(address, size, reason):
            state["depth_reads"].append(
                {"address": hex(address), "size": size, "offset": address - DEPTH}
            )
            if reason:
                state["bounds_fault"] = {
                    "address": hex(address),
                    "offset": address - DEPTH,
                    "allocation_size": allocation_size,
                    "reason": reason,
                }

        def on_read(machine, access, address, size, value, user_data):
            if machine.reg_read(UC_X86_REG_EIP) == 0x0040D2F4:
                outside = address < DEPTH or address + size > DEPTH + allocation_size
                record_read(address, size, "outside logical depth allocation" if outside else None)
                if outside:
                    machine.emu_stop()

        def on_invalid(machine, access, address, size, value, user_data):
            if machine.reg_read(UC_X86_REG_EIP) == 0x0040D2F4:
                record_read(address, size, "unmapped depth read")
            return False

        uc.hook_add(UC_HOOK_CODE, on_code)
        uc.hook_add(UC_HOOK_MEM_READ, on_read)
        uc.hook_add(UC_HOOK_MEM_INVALID, on_invalid)
        try:
            uc.emu_start(ENTRY, RETURN + 1, count=2000)
        except UcError as error:
            state["emulator_error"] = str(error)
        state.update(
            {
                "al": uc.reg_read(UC_X86_REG_EAX) & 0xFF,
                "esp_after": hex(uc.reg_read(UC_X86_REG_ESP)),
                "expected_esp_after": hex(initial_esp + 8),
                "callee_saved_preserved": {
                    name: uc.reg_read(REGISTERS[name]) == value for name, value in SAVED.items()
                },
                "eip_after": hex(uc.reg_read(UC_X86_REG_EIP)),
                "input": {
                    "width": width,
                    "height": height,
                    "x": x,
                    "y": y,
                    "depth": depth,
                    "sample": sample,
                    "int_x": int_x,
                    "int_y": int_y,
                },
                "patched": patched,
            }
        )
        return state


def verify(replay):
    cases = []
    for width, height in ((2880, 1800), (640, 480)):
        for x, y in itertools.product(
            (-1, 0, width - 1, width, width + 1),
            (-1, 0, height - 1, height, height + 1),
        ):
            cases.append((width, height, float(x), float(y), 12345.0, 23456))
        for x, y, depth, sample in (
            (7.75, 9.25, 100.9, 99),
            (7.75, 9.25, 100.9, 100),
            (7.75, 9.25, 100.9, 101),
            (-0.9, -0.9, 100.0, 100),
            (width - 0.1, height - 0.1, 100.0, 100),
        ):
            cases.append((width, height, x, y, depth, sample))
    cases.append((2880, 1800, 851.6438598632812, 1800.621826171875, 64657.0, 65535))

    pairs, checks = [], []

    def check(kind, passed, **details):
        checks.append({"kind": kind, "pass": bool(passed), **details})

    for case in cases:
        original = replay.run(*case, patched=False)
        patched = replay.run(*case, patched=True)
        width, height, x, y, depth, sample = case
        if 0 <= int(x) < width and 0 <= int(y) < height:
            expected = int(sample >= int(depth))
            check(
                "valid behavior unchanged",
                original["returned"]
                and patched["returned"]
                and original["al"] == patched["al"] == expected
                and original["depth_reads"] == patched["depth_reads"],
                input=patched["input"],
            )
        else:
            check(
                "patched rejects without depth read",
                patched["returned"]
                and patched["al"] == 0
                and not patched["depth_reads"]
                and patched["bounds_fault"] is None,
                input=patched["input"],
            )
        for version, result in (("original", original), ("patched", patched)):
            if result["returned"]:
                check(
                    "return stack and callee registers restored",
                    result["esp_after"] == result["expected_esp_after"]
                    and all(result["callee_saved_preserved"].values()),
                    version=version,
                    input=result["input"],
                )
        pairs.append({"original": original, "patched": patched})

    captured = pairs[-1]
    check(
        "captured fault target reproduced",
        captured["original"]["bounds_fault"] is not None
        and captured["original"]["bounds_fault"]["address"] == "0x15b3daa6",
    )
    check(
        "captured fault eliminated",
        captured["patched"]["returned"]
        and captured["patched"]["al"] == 0
        and not captured["patched"]["depth_reads"],
    )
    x_edge = next(
        pair
        for pair in pairs
        if pair["original"]["input"]["width"] == 2880
        and pair["original"]["input"]["int_x"] == 2880
        and pair["original"]["input"]["int_y"] == 0
    )
    check(
        "x equal width originally reads next row, patched rejects",
        x_edge["original"]["depth_reads"] and not x_edge["patched"]["depth_reads"],
    )
    source_unchanged = hashlib.sha256(replay.exe.read_bytes()).hexdigest() == EXPECTED_SHA256
    passed = all(item["pass"] for item in checks) and source_unchanged
    summary = {
        "status": "PASS" if passed else "FAIL",
        "source_build": "unmodified English v1.2",
        "source_sha256": EXPECTED_SHA256,
        "source_unchanged": source_unchanged,
        "unicorn_version": unicorn_version,
        "pefile_version": pefile.__version__,
        "method": "Full game x86 helper, including its actual x87 integer conversion helper, executed in an emulator.",
        "limits": "Logical depth allocation is modeled. No game, mission, graphics driver, or original Windows guard-page layout is exercised.",
        "function_entry": hex(ENTRY),
        "opcode_changes": [
            {"va": hex(address), "before": hex(before), "after": hex(after)}
            for address, before, after in PATCHES
        ],
        "case_pairs": len(pairs),
        "checks": len(checks),
        "failed_checks": [item for item in checks if not item["pass"]],
        "captured_case": captured,
    }
    return summary, {**summary, "results": pairs, "verification_checks": checks}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path, help="Unmodified English v1.2 game executable.")
    parser.add_argument("--output", type=Path, help="Optional detailed JSON report.")
    parser.add_argument("--summary-output", type=Path, help="Optional compact JSON report.")
    args = parser.parse_args()
    try:
        replay = Replay(args.exe)
        summary, detailed = verify(replay)
    except (OSError, ValueError, pefile.PEFormatError) as error:
        parser.exit(2, f"Replay failed: {error}\n")
    if args.output:
        write_json(args.output, detailed)
    if args.summary_output:
        write_json(args.summary_output, summary)
    print(json.dumps(summary, indent=2))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
