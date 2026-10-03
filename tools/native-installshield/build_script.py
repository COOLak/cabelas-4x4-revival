"""Assemble an original, small patch workflow for a private InstallShield 5 shell.

The original nine main event records are replaced; all other event records are
preserved as opaque bytes, retaining their IDs and native dialog resources.
This authoring tool needs a user's original installer, not an SDK or decompiler.
"""
from pathlib import Path
import argparse
import hashlib
import json
import struct
from inspect_tables import metadata

ORIGINAL_HASH = '971310d02e307562bcb3b8b2e9593959580d279d5e91c100cd2d1c758f5933e1'
LIBRARY_START = 4040
LIBRARY_HASH = 'cbbab0b389cb1e2de2ec1e7a849109c1f258c9de55817848efb19712cbcd00fa'

def word(n):
    return struct.pack('<H', n)

def text(s):
    b = s.encode('ascii')
    return word(len(b)) + b

def string(s):
    return b'\x61' + text(s)

def integer(n):
    return b'\x41' + struct.pack('<I', n & 0xffffffff)

def source_string(index):
    return b'\x62' + word(index)

def dest_string(index):
    return b'\x52' + word(index)

def source_number(index):
    return b'\x42' + word(index)

def dest_number(index):
    return b'\x32' + word(index)

def opcode(n, *args):
    return word(n) + b''.join(args)

def goto(event):
    return opcode(0x2c, b'\x70' + word(event))

def branch(event, comparison, left, right):
    return opcode(0x22, b'\x70' + word(event), bytes([0x90 | comparison]), left, right)

def call(proto, event, *args):
    return opcode(0xb5, b'\x80' + word(proto), b'\x70' + word(event), *args)

def frame(*actions):
    return word(0) + word(len(actions)) + b''.join(actions)

def build(original):
    if hashlib.sha256(original).hexdigest() != ORIGINAL_HASH:
        raise ValueError('Expected the untouched official 1.2 setup.ins')
    hdr = metadata(original)
    footer_start = len(original) - 1 - original[-1]
    opaque = original[LIBRARY_START:footer_start]
    if hashlib.sha256(opaque).hexdigest() != LIBRARY_HASH:
        raise ValueError('Original dialog event stream identity mismatch')
    assert hdr['event_count'] == 776 and len(hdr['string_slots']) == 35
    assert hdr['number_slots'] == 47 and len(hdr['prototypes']) == 105

    # New globals are appended after the untouched original/library slots.
    dll_path, folder_copy, error_text = 35, 36, 37
    opt1, opt2, worker_status, call_result = 47, 48, 49, 50
    title = "Cabela's 4x4 Community Patch 1.2.1"
    welcome = "This will install Cabela's 4x4 Community Patch 1.2.1."
    main = b''.join([
        frame(
            opcode(0x2, integer(12)),
            opcode(0x1, integer(29)),
            opcode(0x1, integer(16)),
            opcode(0x4, string(title), integer(24), integer(0x00ffffff)),
            opcode(0x4, string(title), integer(0), integer(0xff000100)),
            call(26, 676, string(title)),
            opcode(0x1, integer(12)),
            opcode(0x13, dest_string(3), string('C:\\Games')),
            opcode(0x125, dest_string(dll_path), source_string(0), string('Cabela4x4PatchBridge.dll')),
            opcode(0x21, dest_number(opt1), integer(0)),
            opcode(0x21, dest_number(opt2), integer(0)),
            # Reuse the original read-only HKCU Path1 lookup and scratch ABI.
            opcode(0x13, dest_string(34), string('')),
            opcode(0x110, integer(0x80000001)),
            opcode(0x152, string("Software\\Activision Value\\Cabela's Off-road Adventure"),
                   string('Path1'), dest_number(44), dest_string(34), dest_number(45)),
            branch(1, 1, source_number(0), integer(0)),
            opcode(0x2f, source_string(34)),
            branch(1, 5, source_number(0), integer(0)),
            opcode(0x0c, source_string(34)),
            branch(1, 1, source_number(0), integer(0)),
            opcode(0x13, dest_string(3), source_string(34)),
            goto(1)),
        frame(
            call(6, 232, string(title), string(welcome)),
            opcode(0x21, dest_number(call_result), source_number(0)),
            branch(8, 6, source_number(call_result), integer(1)),
            goto(2)),
        frame(
            call(5, 215, string('Choose Destination Location'),
                 string("Select the folder where Cabela's 4x4 is installed."),
                 dest_string(3), integer(0)),
            opcode(0x21, dest_number(call_result), source_number(0)),
            branch(1, 5, source_number(call_result), integer(12)),
            branch(8, 6, source_number(call_result), integer(1)),
            goto(3)),
        frame(
            # The engine grows this dynamic string for the long seed and never
            # shrinks it for the shorter path. The DLL writes at most239 bytes.
            # Pass only this private copy; TARGETDIR must survive error returns.
            opcode(0x13, dest_string(folder_copy), string(' ' * 300)),
            opcode(0x13, dest_string(folder_copy), source_string(3)),
            opcode(0x21, dest_number(worker_status), integer(-1)),
            # This original engine supports CallDLLFx, whose last two arguments
            # are writable variable indices, not source operand expressions.
            opcode(0x13b, source_string(dll_path), string('PatchInstaller'),
                   dest_number(worker_status), dest_string(folder_copy)),
            opcode(0x21, dest_number(call_result), source_number(0)),
            goto(4)),
        frame(
            branch(5, 1, source_number(call_result), integer(0)),
            branch(6, 6, source_number(call_result), integer(0)),
            branch(6, 6, source_number(worker_status), integer(0)),
            goto(7)),
        frame(
            branch(8, 5, source_number(4), integer(3)),
            opcode(0x6e, dest_string(error_text), source_number(call_result)),
            opcode(0x124, dest_string(error_text), string('\nLoader result: '), source_string(error_text)),
            opcode(0x124, dest_string(error_text), source_string(dll_path), source_string(error_text)),
            opcode(0x124, dest_string(error_text),
                   string('The native patch component could not be loaded.\nDLL: '), source_string(error_text)),
            opcode(0x2a, source_string(error_text), integer(0x10)),
            goto(8)),
        frame(
            branch(8, 5, source_number(4), integer(3)),
            opcode(0x2a, source_string(folder_copy), integer(0x10)),
            goto(2)),
        frame(
            call(30, 749, string('Setup Complete'),
                 string("Cabela's 4x4 has been updated to version 1.2.1."),
                 string(''), string(''), string(''),
                 dest_number(opt1), dest_number(opt2)),
            goto(8)),
        frame(opcode(0x2b)),
    ])

    # CallDLLFx uses the supported engine builtin and requires no new prototype.
    header = bytearray(original[:hdr['code_offset']])
    struct.pack_into('<H', header, hdr['number_slots_offset'], 51)
    struct.pack_into('<H', header, hdr['string_slots_offset'], 38)
    slots_end = hdr['string_slots_offset'] + 2 + 35 * 2
    header[slots_end:slots_end] = word(65535) * 3
    out = header + main + opaque + original[footer_start:]
    struct.pack_into('<I', out, 8, sum(out[12:]) & 0xffffffff)
    report = dict(
        original_sha256=ORIGINAL_HASH, output_sha256=hashlib.sha256(out).hexdigest(),
        original_main_events=9, authored_main_events=9, event_count=776,
        retained_event_ids=[9, 775], retained_library_sha256=LIBRARY_HASH,
        retained_library_bytes=len(opaque), prototype_count=105,
        native_call_opcode='0x13b', native_export='PatchInstaller',
        native_abi='LONG WINAPI (HWND, LONG*, LPSTR)',
        globals=dict(dll_path=35, folder_copy=36, error_text=37,
                     worker_status=49, call_result=50),
        string_slots=38, number_slots=51, checksum=struct.unpack_from('<I', out, 8)[0],
        selected_target_preserved=True, mutable_string_seed_bytes=300,
        game_executable_payload=False, game_registry_writes=False,
        game_launch=False, command_wrapper_required=False,
    )
    return bytes(out), report

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('original', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--report', required=True, type=Path)
    a = p.parse_args()
    data, report = build(a.original.read_bytes())
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_bytes(data)
    a.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))
