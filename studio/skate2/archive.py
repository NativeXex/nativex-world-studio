"""Read-only BIG4/BIGF directory reader measured against the local Skate 2 files.

The file size is little endian; counts, directory span and member ranges are
big endian. This is separate from Skate 3's EB archive implementation.
"""
import mmap
from pathlib import Path, PurePosixPath
import struct


class ClassicBigArchive:
    def __init__(self, path):
        self.path = Path(path)
        with self.path.open('rb') as f:
            self.data = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            self.entries = self._directory()
        except Exception:
            self.close()
            raise

    def _directory(self):
        d = self.data
        if len(d) < 16 or d[:4] not in (b'BIG4', b'BIGF'):
            raise ValueError('Expected Skate 2 BIG4/BIGF archive')
        self.magic = d[:4].decode('ascii')
        declared = struct.unpack_from('<I', d, 4)[0]
        count, end = struct.unpack_from('>2I', d, 8)
        if declared != len(d) or not 0 < count <= 100000 or not 16 <= end <= len(d):
            raise ValueError('Invalid classic BIG header or file size')
        result, at = {}, 16
        for _ in range(count):
            if at+8 >= end:
                raise ValueError('Truncated classic BIG directory')
            offset, size = struct.unpack_from('>2I', d, at)
            at += 8
            tail = d.find(b'\0', at, end)
            if tail < 0:
                raise ValueError('Unterminated classic BIG name')
            name = d[at:tail].decode('ascii').replace('\\', '/').lower()
            at = tail+1
            if not name or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or ':' in name:
                raise ValueError('Unsafe classic BIG member path')
            # Retail worldmisc ends with a zero-length wildcard directory marker.
            if name in result or (size and offset < end) or offset+size > len(d):
                raise ValueError('Invalid or duplicate classic BIG member range')
            result[name] = dict(path=name, offset=offset, size=size)
        ranges = sorted((e['offset'], e['offset']+e['size']) for e in result.values() if e['size'])
        if any(a[1] > b[0] for a, b in zip(ranges, ranges[1:])):
            raise ValueError('Overlapping classic BIG members')
        return result

    def read(self, name):
        e = self.entries[name]
        return self.data[e['offset']:e['offset']+e['size']]

    def close(self):
        self.data.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
