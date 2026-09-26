"""Skate 2 material binding via explicit arena subreferences.

Unlike the tested Skate 3 material tables, Skate 2 Name-channel GUIDs repeat
across different materials. Resolve each mesh handle to the actual native row;
never infer material identity from array order or the repeated Name GUID.
"""
import struct
from ..skate3.archive import u32
from ..skate3.arena import Arena, string
from ..skate3.world_materials import enrich as enrich_attributes


def bindings(arena):
    d = arena.data
    manifest = u32(d, 52)
    if u32(d, manifest) != 0x10004:
        raise ValueError('Unsupported Skate 2 arena manifest')
    count, relative = struct.unpack_from('>2I', d, manifest+4)
    table = manifest+relative
    if count > 100 or table+count*4 > len(d):
        raise ValueError('Invalid Skate 2 arena manifest table')
    sections = [manifest+u32(d, table+i*4) for i in range(count)]
    subs = [p for p in sections if p+28 <= len(d) and u32(d, p) == 0x10007]
    if len(subs) != 1:
        raise ValueError('Expected one Skate 2 subreference table')
    pointer, length = struct.unpack_from('>2I', d, subs[0]+20)
    if pointer+length*8 > len(d):
        raise ValueError('Skate 2 subreference table exceeds arena')
    rows = {}
    for sid in arena.indices(0xeb0005):
        s = arena.section(sid)
        total, channels, start = struct.unpack_from('>3I', s)
        if total > 10000 or start+total*12 > len(s):
            raise ValueError('Invalid Skate 2 material table')
        for i in range(total):
            row = start+i*12
            n, flags, at = struct.unpack_from('>3I', s, row)
            if n > channels or at+n*32 > len(s):
                raise ValueError('Invalid Skate 2 material channels')
            entries = []
            for j in range(n):
                name, cf, image, _, _, guid, text, stream = struct.unpack_from('>IHHIIQII', s, at+j*32)
                entries.append(dict(role=string(s, name), flags=cf, imageChannel=image,
                                    guid=f'{guid:016x}', text=string(s, text), stream=stream))
            identity = next((c for c in entries if c['role'] == 'Name'), None)
            if identity is None:
                raise ValueError('Skate 2 material has no Name channel')
            rows[(sid, row)] = dict(name=identity['text'], flags=flags, channels=entries,
                                    sourceSection=sid, sourceOffset=row)
    result = {}
    for item in arena.toc():
        if item['type'] != 0xeb0066:
            continue
        handle = item['handle']; index = handle & 0xffff
        if handle >> 16 != 0x80 or index >= length:
            raise ValueError('Unsupported Skate 2 material subreference')
        key = struct.unpack_from('>2I', d, pointer+index*8)
        if key not in rows or handle in result:
            raise ValueError('Skate 2 material reference does not resolve to one material row')
        result[handle] = dict(rows[key], guid=item['guid'])
    used = {u32(arena.section(i), 36) for i in arena.indices(0xeb0023)}
    if not used.issubset(result):
        raise ValueError('Not every Skate 2 mesh has a resolved material')
    return result


def enrich(data, decoded):
    result = enrich_attributes(data, decoded, bindings=bindings(Arena(data)))
    result['materials'] = 'Skate 2 native subreference bindings and diffuse UVs; approximate editor lighting'
    return result
