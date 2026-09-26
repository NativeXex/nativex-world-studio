"""Retail material bindings: Name GUID -> TOC handle -> optimized mesh.

Table order is NOT mesh order. Field layouts documented by AASkate and the
SK8-Engine retail material audit; see research/WORLD_IMPORT.md.
"""
import struct, math
from .arena import Arena, string
from .archive import u32

def materials(arena):
    by_guid = {}
    for section in arena.indices(0xeb0005):
        s = arena.section(section)
        count, channels, start, _, _ = struct.unpack_from('>5I', s)
        if count > 10000 or start+count*12 > len(s): raise ValueError('Invalid material table')
        for i in range(count):
            n, flags, at = struct.unpack_from('>3I', s, start+i*12)
            if n > channels or at+n*32 > len(s): raise ValueError('Invalid material channels')
            entries = []
            for j in range(n):
                name, cf, image, _, _, guid, text, stream = struct.unpack_from('>IHHIIQII', s, at+j*32)
                entries.append(dict(role=string(s,name), flags=cf, imageChannel=image,
                                    guid=f'{guid:016x}', text=string(s,text), stream=stream))
            identity = next((c for c in entries if c['role']=='Name'), None)
            if identity is None: raise ValueError('Material has no Name GUID')
            by_guid[identity['guid']] = dict(guid=identity['guid'], name=identity['text'],
                                             flags=flags, channels=entries)
    result = {}
    for item in arena.toc():
        if item['type'] == 0xeb0066:
            if item['guid'] not in by_guid: raise ValueError('Unresolved material GUID')
            result[item['handle']] = by_guid[item['guid']]
    return result

def enrich(data, decoded, *, bindings=None):
    a = Arena(data); bindings = materials(a) if bindings is None else bindings
    for g in decoded['groups']:
        mesh = a.section(g['sourceSection'], 0xeb0023)
        handle = u32(mesh,36)
        if handle not in bindings: raise ValueError('Unresolved mesh material handle')
        g['material'] = bindings[handle]
        desc = a.section(u32(mesh,40),0x200e9)
        vb = a.section(u32(mesh,52),0x200ea)
        raw = a.section(u32(vb,24)>>2,0x10031)
        elems = struct.unpack_from('>H',desc,8)[0]; stride = desc[16+elems*16]
        count = len(g['positions'])//3
        attrs = [struct.unpack_from('>HHIBBBBI',desc,16+i*16) for i in range(elems)]
        tex = sorted((x for x in attrs if x[4]==5),key=lambda x:x[5])
        if tex:
            offset, typ = tex[0][1:3]
            fmt = {0x2c235f:'>2e',0x1a2360:'>4e',0x2c23a5:'>2f',0x2c2159:'>2h',0x2c2059:'>2H'}.get(typ)
            if fmt is None: raise ValueError(f'Unsupported diffuse UV declaration {typ:08x}')
            uv = [struct.unpack_from(fmt,raw,i*stride+offset)[:2] for i in range(count)]
            if typ in (0x2c2159,0x2c2059):
                divisor=32767 if typ==0x2c2159 else 65535
                uv=[tuple(max(-1,v/divisor) for v in pair) for pair in uv]
            if not all(math.isfinite(v) for pair in uv for v in pair): raise ValueError('Invalid UV')
            g['uv'] = [v for pair in uv for v in pair]
        if len(tex)>1 and tex[1][2]==0x1a215a:
            offset = tex[1][1]
            values = [struct.unpack_from('>4h',raw,i*stride+offset) for i in range(count)]
            g['lightmapUv'] = [abs(v/32767) for row in values for v in row[:2]]
            if any(x[4]==6 and x[2]&63==16 for x in attrs):
                normals=[]
                for sx,sy,nx,ny in values:
                    x=max(-1,nx/32767);y=max(-1,ny/32767)
                    z=math.sqrt(max(0,1-x*x-y*y)) * (-1 if sy<0 else 1)
                    normals.extend([x,y,z])
                g['normals']=normals
    decoded['materials']='Retail diffuse textures and UVs; approximate editor lighting'
    return decoded
