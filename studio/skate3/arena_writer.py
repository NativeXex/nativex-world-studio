"""Append replacement CPU sections without shifting any existing native offsets."""
import struct
from .arena import Arena
from .archive import u32


def align(value, alignment=16):
    return (value+alignment-1) & -alignment


def subrefs(arena):
    d = arena.data
    manifest = u32(d, 52)
    table = manifest+u32(d, manifest+8)
    offsets = [manifest+u32(d, table+i*4) for i in range(u32(d, manifest+4))]
    matches = [at for at in offsets if u32(d, at) == 0x10007]
    if len(matches) != 1:
        raise ValueError('Unknown arena subreference manifest')
    at = matches[0]
    count, used = u32(d, at+4), u32(d, at+24)
    if count != used or u32(d, at+8) or u32(d, at+12):
        raise ValueError('Unsupported arena relocation state')
    start = u32(d, at+20)
    return at, [struct.unpack_from('>II', d, start+i*8) for i in range(used)]


def append_sections(data, replacements, extra_refs=()):
    arena = Arena(data)
    base = u32(data, 68)
    if base+u32(data, 84) != len(data):
        raise ValueError('Unsupported arena CPU/GPU partition')
    output = bytearray(data[:base])
    table = u32(data, 48)
    for sid, payload in sorted(replacements.items()):
        section = arena.sections[sid]
        if section['type'] == 0x10031:
            raise ValueError('CPU writer cannot replace GPU storage')
        at = align(len(output), section['alignment'])
        output.extend(bytes(at-len(output)))
        output.extend(payload)
        struct.pack_into('>I', output, table+sid*24, at)
        struct.pack_into('>I', output, table+sid*24+8, len(payload))
    if extra_refs:
        at, refs = subrefs(arena)
        refs += list(extra_refs)
        start = align(len(output), 4)
        output.extend(bytes(start-len(output)))
        for sid, offset in refs:
            payload = replacements.get(sid, arena.section(sid))
            if not 0 <= offset < len(payload):
                raise ValueError('Subreference leaves its replacement section')
            output.extend(struct.pack('>II', sid, offset))
        dictionary = len(output)
        output.extend(bytes(len(refs)*24))
        struct.pack_into('>I', output, at+4, len(refs))
        struct.pack_into('>III', output, at+16, dictionary, start, len(refs))
    new_base = align(len(output), u32(data, 72))
    output.extend(bytes(new_base-len(output)))
    struct.pack_into('>I', output, 68, new_base)
    output.extend(data[base:])
    checked = Arena(bytes(output))
    for section in arena.sections:
        wanted = replacements.get(section['index'], arena.section(section['index']))
        if checked.section(section['index']) != wanted:
            raise ValueError('Arena relocation changed an unrelated section')
    return bytes(output)


def extend_toc(data, additions):
    """Keep all original name pointers; redirect only the entry/type-map arrays."""
    if not additions:
        return data
    count, start, names, type_count, types = struct.unpack_from('>5I', data)
    if start+count*24 > len(data) or types+type_count*8 > len(data):
        raise ValueError('Invalid source TOC')
    output = bytearray(data)
    new_start = align(len(output), 4)
    output.extend(bytes(new_start-len(output)))
    output.extend(data[start:start+count*24])
    for guid, kind, handle in additions:
        output.extend(struct.pack('>IIQII', 0, 0xfeffffff, guid, kind, handle))
    new_types = len(output)
    for kind, index in struct.iter_unpack('>II', data[types:types+type_count*8]):
        output.extend(struct.pack('>II', kind, count+len(additions) if index == count else index))
    struct.pack_into('>5I', output, 0, count+len(additions), new_start, names, type_count, new_types)
    return bytes(output)
