"""Read native static placement records independently of editor layout plans."""
from dataclasses import replace
import copy
import math
import struct

from .arena import Arena, string
from .archive import u32
from .collision_tree import bounds
from .vendor.retail_collision_mesh import decode_clustered_mesh


def instances(data, component):
    arena = Arena(data)
    kind, field = (0xeb0001, 128) if component == 'render' else (0xeb000a, 132)
    result = []
    for sid in arena.indices(0xeb000d):
        s = arena.section(sid)
        count, start = u32(s, 4), u32(s, 12)
        if count > 10000 or start + count*160 > len(s):
            raise ValueError('Invalid native instance table')
        for index in range(count):
            at = start + index*160
            ref = u32(s, at+field)
            if not ref:
                continue
            arena.section(ref, kind)
            matrix = list(struct.unpack_from('>16f', s, at))
            # Initial section compiler admits translations only. Do not guess
            # rotations/scales for the native collision and grind bindings.
            if not all(math.isfinite(v) for v in matrix) or any(
                    abs(v - (1 if j % 5 == 0 else 0)) > 1e-6
                    for j, v in enumerate(matrix) if j not in (12, 13, 14)):
                raise ValueError('Native section reader requires translation-only instances')
            bb = [list(struct.unpack_from('>3f', s, at+offset)) for offset in (64, 80)]
            if not all(math.isfinite(v) for p in bb for v in p):
                raise ValueError('Non-finite native instance bounds')
            result.append(dict(matrix=matrix, bounds=bb, delta=matrix[12:15], section=sid,
                               index=index, modelSection=ref, guid=f'{struct.unpack_from(">Q", s, at+96)[0]:016x}',
                               name=string(s, u32(s, at+140))))
    if not result:
        raise ValueError('No native model instances')
    if len({i['guid'] for i in result}) != len(result):
        raise ValueError('Duplicate native instance identity')
    if {i['modelSection'] for i in result} != set(arena.indices(kind)):
        raise ValueError('Native model instance coverage is unresolved')
    return result


def translated(point, delta):
    return tuple(point[a]+delta[a] for a in range(3))


def render_instances(data, model):
    native = instances(data, 'render')
    result = copy.deepcopy(model)
    result['groups'] = []
    for item in native:
        for group in model['groups']:
            g = copy.deepcopy(group)
            g['positions'] = [v+item['delta'][i % 3] for i, v in enumerate(g['positions'])]
            g['nativeInstance'] = item['guid']
            points = [g['positions'][i:i+3] for i in range(0, len(g['positions']), 3)]
            if any(p[a] < item['bounds'][0][a]-.08 or p[a] > item['bounds'][1][a]+.08
                   for p in points for a in range(3)):
                raise ValueError('Placed render geometry exceeds native instance bounds')
            result['groups'].append(g)
    result['bounds'] = bounds([g['positions'][i:i+3] for g in result['groups']
                               for i in range(0, len(g['positions']), 3)])
    result['vertices'] *= len(native)
    result['triangles'] *= len(native)
    result['nativeInstances'] = native
    return result


def collision_instances(data):
    arena = Arena(data)
    output = []
    covered = set()
    for item in instances(data, 'collision'):
        model = arena.section(item['modelSection'], 0xeb000a)
        count, start = u32(model, 4), u32(model, 8)
        if count > 10000 or start+count*8 > len(model):
            raise ValueError('Invalid collision model bindings')
        for index in range(count):
            volume = arena.section(u32(model, start+index*8), 0x80001)
            if len(volume) != 96 or u32(volume, 64) != 6:
                raise ValueError('Unsupported collision volume binding')
            matrix = struct.unpack_from('>12f', volume)
            if any(abs(v-(1 if i in (0, 5, 10) else 0)) > 1e-6 for i, v in enumerate(matrix)) or any(volume[48:64]):
                raise ValueError('Nonidentity collision volume transform')
            sid = u32(volume, 68)
            covered.add(sid)
            mesh = decode_clustered_mesh(arena.section(sid, 0x80006))
            tris = tuple(replace(t, **{k: translated(getattr(t, k), item['delta']) for k in ('a', 'b', 'c')})
                         for t in mesh.triangles)
            bb = bounds([p for t in tris for p in (t.a, t.b, t.c)])
            if any(p[a] < item['bounds'][0][a]-.08 or p[a] > item['bounds'][1][a]+.08 for p in bb for a in range(3)):
                raise ValueError('Placed collision exceeds native instance bounds')
            output.append(replace(mesh, triangles=tris, bounds_min=tuple(bb[0]), bounds_max=tuple(bb[1])))
    if covered != set(arena.indices(0x80006)):
        raise ValueError('Unbound native collision mesh')
    return output
