"""Checked views of Xbox RenderWare arena sections; source bytes stay untouched."""
import struct
from .archive import u32

class Arena:
    def __init__(self, data):
        if data[:12] != b'\x89RW4xb2\0\r\n\x1a\n':
            raise ValueError('Expected Xbox RX2 arena')
        self.data = data
        count, table, base = u32(data, 32), u32(data, 48), u32(data, 68)
        if count > 4096 or table + count * 24 > len(data):
            raise ValueError('Invalid arena section table')
        self.sections = []
        for i in range(count):
            offset, _, size, align, _, kind = struct.unpack_from('>6I', data, table + i*24)
            offset += base if kind == 0x10031 else 0
            if offset + size > len(data): raise ValueError('Arena section exceeds file')
            self.sections.append(dict(index=i, type=kind, offset=offset, size=size, alignment=align))

    def section(self, index, kind=None):
        if not 0 <= index < len(self.sections): raise ValueError('Invalid arena reference')
        s = self.sections[index]
        if kind is not None and s['type'] != kind: raise ValueError('Arena reference type mismatch')
        return self.data[s['offset']:s['offset']+s['size']]

    def indices(self, kind):
        return [s['index'] for s in self.sections if s['type'] == kind]

    def one(self, kind):
        ids = self.indices(kind)
        if len(ids) != 1: raise ValueError(f'Expected one {kind:08x} section')
        return self.section(ids[0])

    def toc(self):
        records = []
        for i in self.indices(0xeb000b):
            s = self.section(i); count, start = struct.unpack_from('>2I', s)
            if start + count*24 > len(s): raise ValueError('TOC outside section')
            for j in range(count):
                name, _, guid, kind, handle = struct.unpack_from('>IIQII', s, start+j*24)
                records.append(dict(name=string(s,name), guid=f'{guid:016x}', type=kind, handle=handle))
        return records

def string(data, offset):
    if offset == 0: return ''
    if not 0 <= offset < len(data): raise ValueError('String offset outside section')
    end = data.find(b'\0', offset)
    if end < 0: raise ValueError('Unterminated arena string')
    return data[offset:end].decode('ascii', errors='replace')
