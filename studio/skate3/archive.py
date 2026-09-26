"""Read-only EA BIG/RefPack reader. Unknown codecs fail closed."""
import struct, mmap
from pathlib import Path

def u32(data, offset):
    return struct.unpack_from('>I', data, offset)[0]

def refpack(data, limit=64 * 1024 * 1024):
    if len(data) < 5 or data[:2] != b'\x10\xfb':
        raise ValueError('Unsupported RefPack header')
    expected = int.from_bytes(data[2:5], 'big')
    if expected > limit: raise ValueError('RefPack size limit')
    p, out = 5, bytearray()
    while p < len(data):
        a = data[p]; p += 1; length = distance = 0
        if a < 0x80:
            q = data[p]; p += 1; literal = a & 3
            length = ((a >> 2) & 7) + 3; distance = ((a & 0x60) << 3) + q + 1
        elif a < 0xc0:
            q, z = data[p:p+2]; p += 2; literal = q >> 6
            length = (a & 0x3f) + 4; distance = ((q & 0x3f) << 8) + z + 1
        elif a < 0xe0:
            q, z, w = data[p:p+3]; p += 3; literal = a & 3
            length = ((a & 0x0c) << 6) + w + 5; distance = ((a & 0x10) << 12) + (q << 8) + z + 1
        elif a < 0xfc: literal = ((a & 0x1f) << 2) + 4
        else: literal = a & 3
        if p + literal > len(data) or len(out) + literal + length > expected:
            raise ValueError('Invalid RefPack length')
        out.extend(data[p:p+literal]); p += literal
        if length and not 0 < distance <= len(out): raise ValueError('Invalid RefPack reference')
        for _ in range(length): out.append(out[-distance])
        if a >= 0xfc: break
    if len(out) != expected or p != len(data): raise ValueError('Incomplete RefPack stream')
    return bytes(out)

class BigArchive:
    def __init__(self, path, mapped=False):
        if mapped:
            with Path(path).open('rb') as f:self.data=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)
        else:self.data = Path(path).read_bytes()
        d = self.data
        if d[:2] != b'EB': raise ValueError('Expected Xbox EB archive')
        count, flags, shift = u32(d, 4), struct.unpack_from('>H', d, 8)[0], d[10]
        names = u32(d, 12); nlen, flen, folders = struct.unpack_from('>BBH', d, 20)
        if not 0 < count < 100000 or not nlen > 2 or not flen: raise ValueError('Invalid archive header')
        folder_at = (names + count * nlen + 15) & ~15
        self.entries = {}
        for i in range(count):
            offset, packed, unpacked = struct.unpack_from('>III', d, 48 + i * (20 if flags & 1 else 16))
            name_at = names + i * nlen; folder = struct.unpack_from('>H', d, name_at)[0]
            if folder >= folders: raise ValueError('Invalid folder index')
            name = d[name_at+2:name_at+nlen].split(b'\0')[0].decode('ascii')
            prefix = d[folder_at+folder*flen:folder_at+(folder+1)*flen].split(b'\0')[0].decode('ascii')
            path = (prefix + '/' + name).replace('\\', '/').lower().strip('/')
            offset <<= shift
            if offset + (packed or unpacked) > len(d): raise ValueError('Archive range outside file')
            self.entries[path] = dict(path=path, offset=offset, packed=packed, size=unpacked)
    def read(self, path):
        e = self.entries[path]; raw = self.data[e['offset']:e['offset']+(e['packed'] or e['size'])]
        if not e['packed']: return raw
        if raw[:8] != b'chunkref' or u32(raw, 8) != 2: raise ValueError('Unsupported archive compression')
        count, align, p, out = u32(raw, 20), u32(raw, 24), 40, bytearray()
        if count > 1024 or align not in [1, 4, 16, 32, 128]: raise ValueError('Unsupported chunk layout')
        for i in range(count):
            size, kind = struct.unpack_from('>II', raw, p); p += 8
            if p + size > len(raw): raise ValueError('Truncated chunk')
            if kind != 2: raise ValueError(f'Unsupported chunk codec {kind}')
            out.extend(refpack(raw[p:p+size])); p += size
            if i + 1 < count: p = (p + align - 1) & ~(align - 1)
        if len(out) != e['size'] or len(out) != u32(raw, 12): raise ValueError('Archive output size mismatch')
        return bytes(out)
