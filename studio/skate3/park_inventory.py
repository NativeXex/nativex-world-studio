"""Read-only connected-surface inventory of all original Black Box render data.

Connectivity is evidence for inspection, not proof of object/physics ownership.
Only the separately measured modules are permitted to move/export.
"""
from functools import lru_cache
import json
from . import park_generator as park
from .collision_tree import bounds
from .geometry import decode


@lru_cache(maxsize=1)
def inventory():
    s = park.source()
    manifest = json.loads((park.ROOT/'web/worlds/blackbox/manifest.json').read_text())
    parents, refs, points, touched = [], [], [], {}
    verified = {(f'{park.RENDER:016x}', g['section'], t): m['id']
                for m in s['modules'] for g in m['render'] for t in g['triangles']}

    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    lookup = {}
    for section in manifest['sections']:
        for entry in section['models']:
            aid = entry['id']
            model = decode(s['assets'][int(aid, 16)].data)
            lookup[aid] = {}
            for g in model['groups']:
                verts = [g['positions'][i:i+3] for i in range(0, len(g['positions']), 3)]
                row = lookup[aid][str(g['sourceSection'])] = []
                for t in range(len(g['indices'])//3):
                    ref = (aid, g['sourceSection'], t)
                    if ref in verified:
                        row.append('module:'+verified[ref])
                        continue
                    i = len(parents)
                    parents.append(i); refs.append(ref)
                    tri = [verts[v] for v in g['indices'][t*3:t*3+3]]
                    points.append(tri); row.append(i)
                    for p in tri:
                        key = tuple(round(v*1000) for v in p)
                        if key in touched:
                            parents[find(i)] = find(touched[key])
                        else:
                            touched[key] = i
    components = {}
    for i in range(len(parents)):
        components.setdefault(find(i), []).append(i)
    regions = []
    for n, ids in enumerate(sorted(components.values(), key=lambda ids: refs[ids[0]]), 1):
        identity = f'surface-{n:03d}'
        bb = bounds([p for i in ids for p in points[i]])
        planar_floor = sum(all(abs(p[1]) < .003 for p in points[i]) for i in ids)
        regions.append(dict(id=identity, name=f'Connected surface {n}', bounds=bb,
                            triangles=len(ids), floorTriangles=planar_floor, editable=False,
                            reason=('This region includes floor or structure. Its complete collision, grind and seam ownership must be mapped before moving it.'
                                    if planar_floor else 'Collision and grind ownership are not yet verified for this connected render region.'),
                            assets=sorted({refs[i][0] for i in ids})))
        for i in ids:
            aid, sid, tri = refs[i]
            lookup[aid][str(sid)][tri] = identity
    total = sum(len(row) for groups in lookup.values() for row in groups.values())
    if total != manifest['summary']['triangles'] or total != len(refs)+len(verified):
        raise ValueError('Surface inventory does not cover the original render triangles exactly once')
    return dict(format='nativex-surface-inventory', version=1, sourceSha256=park.SOURCE_SHA256,
                lookup=lookup, regions=regions,
                summary=dict(renderTriangles=total, verifiedMovableTriangles=len(verified),
                             connectedRegions=len(regions), verifiedModules=len(s['modules'])),
                warning='Connected surfaces are inspection regions, not independently movable objects.')
