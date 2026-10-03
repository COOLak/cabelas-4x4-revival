"""Read serialized InstallScript metadata tables, without reconstructing code."""
from pathlib import Path
import json
import struct
import sys


class Reader:
    def __init__(self, data, offset=0):
        self.data, self.offset = data, offset

    def read(self, size):
        result = self.data[self.offset:self.offset + size]
        if len(result) != size:
            raise ValueError("Truncated table")
        self.offset += size
        return result

    def u8(self):
        return self.read(1)[0]

    def u16(self):
        return struct.unpack('<H', self.read(2))[0]

    def text(self):
        return self.read(self.u16()).decode('ascii')


def metadata(data):
    r = Reader(data, 0xD)
    copyright_text = r.text()
    events_offset = r.offset
    event_count = r.u16()
    string_slots_offset = r.offset
    string_slots = [r.u16() for _ in range(r.u16())]
    external_strings = [dict(index=r.u16(), name=r.text()) for _ in range(r.u16())]
    number_slots_offset = r.offset
    number_slots = r.u16()
    external_numbers = [dict(index=r.u16(), name=r.text()) for _ in range(r.u16())]
    structures = []
    for _ in range(r.u16()):
        packing, name, count = r.u16(), r.text(), r.u16()
        fields = [dict(type=r.u16(), size=r.u16(), name=r.text()) for _ in range(count)]
        structures.append(dict(packing=packing, name=name, fields=fields))
    prototype_count_offset = r.offset
    prototypes = []
    for index in range(r.u16()):
        offset = r.offset
        kind, return_type = r.u8(), r.u8()
        if kind == 2:
            dll, name, event = r.text(), r.text(), r.u16()
        elif kind == 1:
            return_type = r.u16()
            dll, name, event = r.text(), r.text(), None
        else:
            raise ValueError(f'Unknown prototype kind {kind} at {offset:#x}')
        params = [dict(script_type=r.u16(), internal_type=r.u16()) for _ in range(r.u16())]
        prototypes.append(dict(index=index, offset=offset, kind=kind, return_type=return_type,
                               dll=dll, name=name, event=event, params=params))
    return dict(copyright=copyright_text, event_count_offset=events_offset,
                event_count=event_count, string_slots_offset=string_slots_offset,
                string_slots=string_slots, external_strings=external_strings,
                number_slots_offset=number_slots_offset,
                number_slots=number_slots, external_numbers=external_numbers,
                structures=structures, prototype_count_offset=prototype_count_offset,
                prototypes=prototypes, code_offset=r.offset)


if __name__ == '__main__':
    result = metadata(Path(sys.argv[1]).read_bytes())
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in ('prototypes', 'structures', 'string_slots')}))
    print(json.dumps([p for p in result['prototypes'] if p['name'] in
                      ('SdWelcome', 'SdAskDestPath', 'SdFinish', 'SdFinishReboot', 'SdShowInfoList')]))
