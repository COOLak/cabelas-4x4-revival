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

    # Allocate new globals after the original script/library globals.
    dll_path, ini_path, error_text = 35, 36, 37
    opt1, opt2, result = 47, 48, 49
    title = "Cabela's 4x4 Community Patch 1.2.1"
    welcome = ('This patch fixes the depth-buffer boundary error in version 1.2. '
               'It modifies your installed executable and preserves its language. '
               'A supported 1.2 build is required. '
               'Close the game and its launcher before continuing.')
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
            opcode(0x125, dest_string(ini_path), source_string(10), string('patch-result.ini')),
            opcode(0x21, dest_number(opt1), integer(0)),
            opcode(0x21, dest_number(opt2), integer(0)),
            goto(1)),
        frame(
            call(6, 232, string(title), string(welcome)),
            opcode(0x21, dest_number(result), source_number(0)),
            branch(8, 6, source_number(result), integer(1)),
            goto(2)),
        frame(
            call(5, 215, string('Select the game folder'),
                 string('Choose the existing folder containing 4x4 Adventure.exe.'),
                 dest_string(3), integer(0)),
            opcode(0x21, dest_number(result), source_number(0)),
            branch(1, 5, source_number(result), integer(12)),
            branch(8, 6, source_number(result), integer(1)),
            goto(3)),
        frame(
            opcode(0xb2, source_string(dll_path)),
            opcode(0x21, dest_number(result), source_number(0)),
            branch(5, 1, source_number(result), integer(0)),
            goto(4)),
        frame(
            opcode(0xb4, b'\x80' + word(105), source_string(3), source_string(0), source_string(10)),
            opcode(0x21, dest_number(result), source_number(0)),
            opcode(0xb3, source_string(dll_path)),
            branch(6, 6, source_number(result), integer(0)),
            goto(7)),
        frame(
            branch(8, 5, source_number(4), integer(3)),
            opcode(0x2a, string('The native patch component could not be loaded. '
                                'Extract the whole installer folder before opening SETUP.EXE.'), integer(4)),
            goto(8)),
        frame(
            branch(8, 5, source_number(4), integer(3)),
            opcode(0x13, dest_string(error_text), string('The selected game could not be patched.')),
            opcode(0x26, source_string(ini_path), string('PatchResult'), string('error'), dest_string(error_text)),
            opcode(0x2a, source_string(error_text), integer(4)),
            goto(2)),
        frame(
            call(30, 749, string('Patch installed'),
                 string('Version 1.2.1 is installed and its executable hash has been verified. '
                        'Your game language and controls are preserved. '
                        'The original executable is saved in the game folder.'),
                 string('You can now start the game yourself.'), string(''), string(''),
                 dest_number(opt1), dest_number(opt2)),
            goto(8)),
        frame(opcode(0x2b)),
    ])

    # Append a real stdcall native DLL prototype: int PatchGame(STRING,STRING,STRING).
    proto = word(1) + word(3) + text('Cabela4x4PatchBridge') + text('PatchGame')
    proto += word(3) + (word(0) + word(4)) * 3
    header = bytearray(original[:hdr['code_offset']])
    struct.pack_into('<H', header, hdr['prototype_count_offset'], 106)
    struct.pack_into('<H', header, hdr['number_slots_offset'], 50)
    struct.pack_into('<H', header, hdr['string_slots_offset'], 38)
    slots_end = hdr['string_slots_offset'] + 2 + 35 * 2
    header[slots_end:slots_end] = word(65535) * 3
    out = header + proto + main + opaque + original[footer_start:]
    struct.pack_into('<I', out, 8, sum(out[12:]) & 0xffffffff)
    report = dict(
        original_sha256=ORIGINAL_HASH, output_sha256=hashlib.sha256(out).hexdigest(),
        original_main_events=9, authored_main_events=9, event_count=776,
        retained_event_ids=[9, 775], retained_library_sha256=LIBRARY_HASH,
        retained_library_bytes=len(opaque), added_dll_prototype=105,
        string_slots=38, number_slots=50, checksum=struct.unpack_from('<I', out, 8)[0],
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
