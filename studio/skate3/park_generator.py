"""Bounded Black Box obstacle layouts using immutable native triangle ownership.

Only the three measured modules below are admitted. Translation preserves resource
counts, surface attributes and spline links. This is not a world/section compiler.
"""
from functools import lru_cache
import json
import math
from pathlib import Path
import random
import re
import struct
import tempfile

from .archive import BigArchive, u32
from .arena import Arena
from .collision_tree import TriangleTree, bounds
from .geometry import decode
from .surface_coverage import coverage
from .vendor.retail_grind_splines import decode_grind_splines, translate_native_segment_payload
from .world_geometry_probe import RENDER, SIMULATION, contained, floor_hit, native_box, replace_stream_asset, subreference
from .world_probe import ROOT, SOURCE_SHA256, STREAM_PREFIX, load_assets, sha

DEFINITIONS = (
    dict(id='manual-pad', name='Manual pad', selection=((22.4, -.01, 63.15), (30.9, .8, 66.35)),
         sections={301: 8, 308: 2}, triangles=10,
         rails={'0xCA834E1A83F2A265': 3, '0xDFA5EEA27D782AAA': 1}),
    dict(id='wedge', name='Wedge and ledge', selection=((31.1, -.01, 47.98), (37.98, 1.86, 50.65)),
         sections={35: 14, 42: 2, 77: 6}, triangles=22,
         rails={'0x09E9542A17D6BC04': 4, '0xA39BD8CC4D8F40BC': 4}),
    dict(id='rear-platform', name='Rear platform and rail', selection=((14.26, -.01, 72.45), (35.16, 2.28, 78.90)),
         sections={63: 18, 301: 24, 308: 8, 350: 8}, triangles=58,
         rails={'0x549F2ACEFF463F8A': 1, '0xD0123BB6D28775C2': 3}),
)
WORK_AREA = ((10., -.01, 40.), (54., 5., 79.))


def inside(p, bb):
    return all(bb[0][a] <= p[a] <= bb[1][a] for a in range(3))


def shifted(bb, delta):
    return [[p[a]+delta[a] for a in range(3)] for p in bb]


def overlaps(a, b, gap=0.):
    return all(a[1][k]+gap > b[0][k]+.003 and a[0][k]-gap < b[1][k]-.003 for k in (0, 2))


@lru_cache(maxsize=1)
def source():
    archive = BigArchive(ROOT/'data/world-source/worldDIST_BlackBoxPark.big')
    if sha(archive.data) != SOURCE_SHA256:
        raise ValueError('Generator requires the verified original Black Box archive')
    # Read the actual archive, not a potentially stale extracted preview cache.
    with tempfile.TemporaryDirectory(prefix='nativex-catalog-') as temp:
        folder = Path(temp)
        for name, entry in archive.entries.items():
            if entry['packed']:
                raise ValueError('Unexpected compressed archive member')
            target = folder/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
        assets, occurrences = load_assets(folder/STREAM_PREFIX)
    if len(assets) != 110:
        raise ValueError('Unexpected native resource coverage')
    model = decode(assets[RENDER].data)
    sim = Arena(assets[SIMULATION].data)
    tree = TriangleTree(sim.one(0x80006))
    rails = decode_grind_splines(sim.data)
    modules = []
    for definition in DEFINITIONS:
        chosen_groups, all_points = [], []
        for group in model['groups']:
            points = [group['positions'][i:i+3] for i in range(0, len(group['positions']), 3)]
            tris = [group['indices'][i:i+3] for i in range(0, len(group['indices']), 3)]
            chosen = [i for i, tri in enumerate(tris) if all(inside(points[v], definition['selection']) for v in tri)]
            if not chosen:
                continue
            vertices = sorted({v for i in chosen for v in tris[i]})
            if any(set(vertices).intersection(tri) for i, tri in enumerate(tris) if i not in chosen):
                raise ValueError('Module render vertices are shared with stationary triangles')
            chosen_groups.append(dict(section=group['sourceSection'], vertices=vertices, triangles=chosen))
            all_points.extend(points[v] for v in vertices)
        if {g['section']: len(g['triangles']) for g in chosen_groups} != definition['sections']:
            raise ValueError('Measured render module changed')
        units = [i for i, t in enumerate(tree.mesh.triangles)
                 if all(inside(p, definition['selection']) for p in (t.a, t.b, t.c))]
        if len(units) != definition['triangles']:
            raise ValueError('Measured collision module changed')
        vertices = {v for i in units for v in tree.units[i]['vertices']}
        if any(vertices.intersection(unit['vertices']) for i, unit in enumerate(tree.units) if i not in units):
            raise ValueError('Module collision shares stationary vertices')
        offsets = []
        for v in vertices:
            at, mode, _ = tree.vertex_storage[v]
            if mode != 1:
                raise ValueError('Only measured 16-bit collision vertices are admitted')
            offsets.append(struct.unpack_from('>3H', tree.data, at))
            all_points.append(tree.vertices[v])
        selected_rails = {}
        for rail in rails:
            points = []
            for payload in rail['native_segment_payloads']:
                v = struct.unpack('>30f', bytes.fromhex(payload))
                points.extend([v[12:15], tuple(sum(v[j+a] for j in (0, 4, 8, 12)) for a in range(3))])
            hits = [inside(p, definition['selection']) for p in points]
            if all(hits) and hits:
                selected_rails[rail['spline_id']] = len(rail['native_segment_payloads'])
                all_points.extend(points)
            elif any(hits):
                raise ValueError('Module cuts a grind attachment')
        if selected_rails != definition['rails']:
            raise ValueError('Measured module grind attachments changed')
        modules.append(dict(id=definition['id'], name=definition['name'], bounds=bounds(all_points),
                            render=chosen_groups, collisionUnits=units, rails=selected_rails,
                            deltaLimits=[[-min(v[a] for v in offsets)*tree.granularity,
                                          (65535-max(v[a] for v in offsets))*tree.granularity] for a in range(3)]))
    all_units = {i for m in modules for i in m['collisionUnits']}
    if len(all_units) != sum(len(m['collisionUnits']) for m in modules):
        raise ValueError('Collision modules overlap')
    ownership = [(g['section'], v) for m in modules for g in m['render'] for v in g['vertices']]
    if len(ownership) != len(set(ownership)):
        raise ValueError('Render modules overlap')
    fixed = [bounds((t.a, t.b, t.c)) for i, t in enumerate(tree.mesh.triangles)
             if i not in all_units and max(p[1] for p in (t.a, t.b, t.c)) > .003]
    floor = [t for i, t in enumerate(tree.mesh.triangles)
             if i not in all_units and all(abs(p[1]) < .003 for p in (t.a, t.b, t.c))]
    render_floor = []
    for g in model['groups']:
        points = [g['positions'][i:i+3] for i in range(0, len(g['positions']), 3)]
        for i in range(0, len(g['indices']), 3):
            tri = [points[v] for v in g['indices'][i:i+3]]
            if all(abs(p[1]) < .003 for p in tri):
                a, b, c = tri
                if (b[2]-a[2])*(c[0]-a[0])-(b[0]-a[0])*(c[2]-a[2]) > 1e-8:
                    render_floor.append(tri)
    manifest = json.loads((ROOT/'web/worlds/blackbox/manifest.json').read_text())
    return dict(archive=archive, assets=assets, occurrences=occurrences, model=model, tree=tree,
                modules=modules, fixed=fixed, floor=floor, renderFloor=render_floor, worldBounds=manifest['bounds'])


def catalog():
    s = source()
    return dict(sourceId='blackbox', sourceSha256=SOURCE_SHA256, version=1,
                renderAsset=f'{RENDER:016x}', simulationAsset=f'{SIMULATION:016x}',
                worldBounds=s['worldBounds'], workArea=WORK_AREA, modules=s['modules'],
                collisionClusterRebasing=True, collisionClusterSplitting=False,
                floorMap=dict(height=0., renderTriangles=len(s['renderFloor']), collisionTriangles=len(s['floor']),
                              repairExportSupported=False, method='Planar triangle coverage plus native floor samples'),
                limitations=['Three curated modules; translation only.',
                             'Moves needing new visible floor or collision are blocked; native floor filling is not implemented.',
                             'Original baked lighting is preserved; old obstacle shadows can remain.',
                             'The reviewed seed 37 arrangement passed a user-reported Xbox test. Each different layout needs its own ride test.'])


def validate_plan(plan):
    if not isinstance(plan, dict) or plan.get('format') != 'nativex-park-layout' or plan.get('version') != 1:
        raise ValueError('Unsupported park layout')
    if plan.get('sourceSha256') != SOURCE_SHA256 or plan.get('sourceId') != 'blackbox':
        raise ValueError('Park source does not match the immutable original')
    if not isinstance(plan.get('id'), str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,100}', plan['id']):
        raise ValueError('Invalid layout identity')
    if not isinstance(plan.get('name'), str) or not 1 <= len(plan['name']) <= 200:
        raise ValueError('Invalid layout name')
    if not isinstance(plan.get('seed'), str) or len(plan['seed']) > 100:
        raise ValueError('Invalid generator seed')
    entries = plan.get('modules')
    expected = {m['id'] for m in source()['modules']}
    if not isinstance(entries, list) or len(entries) != len(expected) or any(not isinstance(m, dict) for m in entries):
        raise ValueError('All three original modules are required')
    if {m.get('id') for m in entries} != expected:
        raise ValueError('Unknown or duplicate module')
    for m in entries:
        delta = m.get('delta')
        if not isinstance(delta, list) or len(delta) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 100 for v in delta):
            raise ValueError('Invalid module translation')
        if delta[1] != 0 or any(abs(v*2-round(v*2)) > 1e-7 for v in delta):
            raise ValueError('Modules stay on the floor and use 0.5 m translation steps')
        if type(m.get('locked')) is not bool:
            raise ValueError('Invalid module lock')
        if set(m) != {'id', 'delta', 'locked'}:
            raise ValueError('Rotation, duplication and scaling are not supported by this writer')
    return plan


def new_plan(seed='37'):
    return dict(format='nativex-park-layout', version=1, sourceId='blackbox', sourceSha256=SOURCE_SHA256,
                id='blackbox-generated', name='Black Box rearrangement', seed=str(seed),
                modules=[dict(id=m['id'], delta=[0., 0., 0.], locked=False) for m in source()['modules']])


class FloorGapError(ValueError):
    def __init__(self, message, diagnostics):
        super().__init__(message)
        self.diagnostics = diagnostics


def floor_report(module, delta, s=None):
    s = source() if s is None else s
    collision = [(t.a, t.b, t.c) for t in s['floor']]
    regions = {}
    for label, bb in (('old', module['bounds']), ('new', shifted(module['bounds'], delta))):
        regions[label] = dict(render=coverage(bb, s['renderFloor']), collision=coverage(bb, collision))
    needs_repair = any(not layer['covered'] for region in regions.values() for layer in region.values())
    return dict(regions=regions, needsRepair=needs_repair,
                action='native-floor-repair-required' if needs_repair else 'retain-existing-floor',
                repairExportSupported=False)


def check_placement(module, delta):
    s = source()
    bb = shifted(module['bounds'], delta)
    if not contained(WORK_AREA, bb) or not contained(s['worldBounds'], bb) or not contained(s['model']['declaredBounds'], bb):
        raise ValueError('Module leaves its original world/cell or the editing area')
    # The untouched source contains intentional adjoining/sloped geometry whose
    # AABBs overlap. Keep it when locked; use conservative rejection for new sites.
    if any(delta) and any(b[0][1] < bb[1][1]-.003 and b[1][1] > bb[0][1]+.003 and overlaps(bb, b) for b in s['fixed']):
        raise ValueError('Module overlaps fixed collision')
    report = floor_report(module, delta, s)
    if report['needsRepair']:
        regions = [label for label, region in report['regions'].items() if any(not layer['covered'] for layer in region.values())]
        raise FloorGapError('Visible floor or collision has a gap at the '+', '.join(regions)+
                            ' footprint; native floor repair is required before this move can be exported', report)
    # Same support density as the console-tested pad, over both old and new footprints.
    for region in (module['bounds'], bb):
        for i in range(21):
            for j in range(11):
                x = region[0][0]+.01+(region[1][0]-region[0][0]-.02)*i/20
                z = region[0][2]+.01+(region[1][2]-region[0][2]-.02)*j/10
                if not any(floor_hit(x, z, t) for t in s['floor']):
                    raise ValueError('Module lacks sampled floor support at its old or new position')
    return bb


def validate_layout(plan, gap=1.):
    validate_plan(plan)
    modules = {m['id']: m for m in source()['modules']}
    occupied, reports = [], []
    for item in plan['modules']:
        module = modules[item['id']]
        try:
            bb = check_placement(module, item['delta'])
            if any(overlaps(bb, other, gap) for other in occupied):
                raise ValueError('Modules need at least one metre between their bounding boxes')
        except ValueError as e:
            if isinstance(e, FloorGapError):
                raise FloorGapError(f"{module['name']}: {e}", e.diagnostics) from e
            raise ValueError(f"{module['name']}: {e}") from e
        occupied.append(bb)
        reports.append(dict(id=item['id'], afterBounds=bb, floorSamples=462, floor=floor_report(module, item['delta']),
                            renderTriangles=sum(len(g['triangles']) for g in module['render']),
                            collisionTriangles=len(module['collisionUnits']), grindSegments=sum(module['rails'].values())))
    translations = collision_translations(plan)
    rebased = source()['tree'].encode_translations(translations, rebase=True)[2] if translations else []
    return dict(valid=True, collisionClustersRebased=rebased, modules=reports, staysInsideOriginalWorld=True, fixedCollisionClear=True,
                visibleAndCollisionFloorCovered=True, floorRepairsAdded=0,
                warning='Floor coverage and structural geometry checks do not prove skate flow, baked lighting or Xbox runtime behaviour.')


def move(plan, module_id, delta):
    """One transactional move; callers only commit the returned validated plan."""
    validate_plan(plan)
    if not isinstance(module_id, str):
        raise ValueError('Select a movable module')
    result = json.loads(json.dumps(plan))
    item = next((m for m in result['modules'] if m['id'] == module_id), None)
    if item is None:
        raise ValueError('This surface has no verified movable render/collision/grind group')
    if item['locked']:
        raise ValueError('Unlock the selected group before moving it')
    item['delta'] = delta
    return dict(plan=result, validation=validate_layout(result))


def generate(plan, seed):
    validate_plan(plan)
    if not isinstance(seed, str) or len(seed) > 100:
        raise ValueError('Seed must be at most 100 characters')
    result = json.loads(json.dumps(plan))
    result['seed'] = seed
    rng = random.Random(seed)
    definitions = {m['id']: m for m in source()['modules']}
    unlocked = [m for m in result['modules'] if not m['locked']]
    if not unlocked:
        raise ValueError('Unlock at least one module')
    # Place the large platform first so smaller pieces can adapt around it.
    unlocked.sort(key=lambda m: (definitions[m['id']]['bounds'][1][0]-definitions[m['id']]['bounds'][0][0]), reverse=True)
    for restart in range(8):
        occupied = []
        for item in result['modules']:
            if item['locked']:
                bb = check_placement(definitions[item['id']], item['delta'])
                if any(overlaps(bb, b, 1.) for b in occupied):
                    raise ValueError('Locked modules overlap')
                occupied.append(bb)
        placed = True
        for item in unlocked:
            module = definitions[item['id']]
            ranges = []
            for a in (0, 2):
                low = max(WORK_AREA[0][a]-module['bounds'][0][a], module['deltaLimits'][a][0])
                high = min(WORK_AREA[1][a]-module['bounds'][1][a], module['deltaLimits'][a][1])
                ranges.append((math.ceil(low*2), math.floor(high*2)))
            for attempt in range(350):
                delta = [rng.randint(*ranges[0])*.5, 0., rng.randint(*ranges[1])*.5]
                if sum(abs(v) for v in delta) < 1:
                    continue
                bb = shifted(module['bounds'], delta)
                if any(overlaps(bb, b, 1.) for b in occupied):
                    continue
                try:
                    check_placement(module, delta)
                except ValueError:
                    continue
                item['delta'] = delta
                occupied.append(bb)
                break
            else:
                placed = False
                break
        if placed:
            return dict(plan=result, validation=validate_layout(result))
    raise ValueError('No complete layout found for this seed and locks; the current layout has been kept')


def render_layout(plan):
    s = source()
    data = s['assets'][RENDER].data
    arena, output = Arena(data), bytearray(data)
    deltas = {m['id']: m['delta'] for m in plan['modules']}
    owners = {(g['section'], v): deltas[m['id']] for m in s['modules'] for g in m['render'] for v in g['vertices']}
    allowed, changed_boxes = set(), []

    def expand_box(at, points):
        old = native_box(data, at)
        bb = bounds(points)
        new = [[min(old[0][a], bb[0][a]) for a in range(3)], [max(old[1][a], bb[1][a]) for a in range(3)]]
        if not contained(s['model']['declaredBounds'], new, .08):
            raise ValueError('Draw bounds leave the preserved model/cell')
        for side, offset in ((0, 0), (1, 16)):
            struct.pack_into('>3f', output, at+offset, *new[side])
            allowed.update(range(at+offset, at+offset+12))
        if new != old:
            changed_boxes.append(dict(offset=at, before=old, after=new))

    moved_addresses = set()
    for g in s['model']['groups']:
        sid = g['sourceSection']
        relevant = {v: d for (section, v), d in owners.items() if section == sid and any(d)}
        if not relevant:
            continue
        mesh = arena.section(sid)
        declaration = arena.section(u32(mesh, 40), 0x200e9)
        count, streams = struct.unpack_from('>HH', declaration, 8)
        attrs = [struct.unpack_from('>HHIBBBBI', declaration, 16+i*16) for i in range(count)]
        positions = [a for a in attrs if a[4:6] == (0, 0)]
        if streams != 1 or len(positions) != 1 or positions[0][0] != 0 or positions[0][2] != 0x2a23b9:
            raise ValueError('Only measured native float3 positions can be written')
        stride = declaration[16+count*16]
        vb = arena.section(u32(mesh, 52), 0x200ea)
        raw = arena.sections[u32(vb, 24) >> 2]
        if raw['type'] != 0x10031:
            raise ValueError('Invalid vertex buffer ownership')
        points = [g['positions'][i:i+3] for i in range(0, len(g['positions']), 3)]
        for v, delta in relevant.items():
            at = raw['offset']+v*stride+positions[0][1]
            if at in moved_addresses or list(struct.unpack_from('>3f', data, at)) != points[v]:
                raise ValueError('Aliased or invalid render source mapping')
            moved_addresses.add(at)
            points[v] = [points[v][a]+delta[a] for a in range(3)]
            struct.pack_into('>3f', output, at, *points[v])
            allowed.update(range(at, at+12))
        expand_box(arena.sections[sid]['offset'], points)
        box_at, cursor = subreference(arena, u32(mesh, 64)), 0
        for island in range(u32(mesh, 56)):
            _, _, _, length = struct.unpack_from('>IiII', mesh, u32(mesh, 68)+island*16)
            expand_box(box_at+island*32, [points[v] for v in g['indices'][cursor:cursor+length]])
            cursor += length
        if cursor != len(g['indices']):
            raise ValueError('Island coverage disagrees with render decoder')
    result = bytes(output)
    if any(i not in allowed for i, (a, b) in enumerate(zip(data, result)) if a != b):
        raise ValueError('Render edit changed bytes outside positions and visibility bounds')
    after = decode(result)
    for old, new in zip(s['model']['groups'], after['groups']):
        if old['indices'] != new['indices']:
            raise ValueError('Render topology changed')
        for i in range(0, len(old['positions']), 3):
            delta = owners.get((old['sourceSection'], i//3), [0, 0, 0])
            if any(abs(new['positions'][i+a]-old['positions'][i+a]-delta[a]) > 1e-5 for a in range(3)):
                raise ValueError('Render edit escaped module ownership')
    return result, dict(vertices=len(moved_addresses), visibilityBoxesExpanded=changed_boxes,
                        materialsUvsNormalsIndicesUnchanged=True, modelAndCellBoundsUnchanged=True)


def collision_translations(plan):
    definitions = {m['id']: m for m in source()['modules']}
    return {i: item['delta'] for item in plan['modules'] if any(item['delta'])
            for i in definitions[item['id']]['collisionUnits']}


def simulation_layout(plan):
    s = source()
    data = s['assets'][SIMULATION].data
    arena = Arena(data)
    sid = arena.indices(0x80006)[0]
    collision, reports = arena.section(sid), []
    definitions = {m['id']: m for m in s['modules']}
    output = bytearray(data)
    rail_deltas = {rid: item['delta'] for item in plan['modules'] if any(item['delta'])
                   for rid in definitions[item['id']]['rails']}
    translations = collision_translations(plan)
    if translations:
        collision, report = s['tree'].translate_many(translations, rebase=True)
        reports.append(dict(ids=[m['id'] for m in plan['modules'] if any(m['delta'])], **report))
    section = arena.sections[sid]
    output[section['offset']:section['offset']+section['size']] = collision
    before_rails = decode_grind_splines(data)
    for rail in before_rails:
        delta = rail_deltas.get(rail['spline_id'])
        if delta is None:
            continue
        start = rail['section_offset']
        first = u32(data, start+16+rail['rail_index']*32+20)
        for i, payload in enumerate(rail['native_segment_payloads']):
            at = start+first+i*144
            if data[at:at+120].hex() != payload:
                raise ValueError('Invalid grind source mapping')
            output[at:at+120] = bytes.fromhex(translate_native_segment_payload(payload, delta))
    result = bytes(output)
    for old, new in zip(before_rails, decode_grind_splines(result)):
        expected = dict(old)
        if old['spline_id'] in rail_deltas:
            expected['native_segment_payloads'] = [translate_native_segment_payload(p, rail_deltas[old['spline_id']]) for p in old['native_segment_payloads']]
        if expected != new:
            raise ValueError('Grind edit differs from the intended translation')
    checked = Arena(result)
    for sec in arena.sections:
        if sec['type'] not in (0x80006, 0xeb0004) and arena.section(sec['index']) != checked.section(sec['index']):
            raise ValueError('Unrelated simulation section changed')
    return result, dict(modules=reports, grindRails=len(rail_deltas), surfaceIdsEdgesAndLinksPreserved=True)


def build(plan, output):
    validation = validate_layout(plan)
    s = source()
    render, render_report = render_layout(plan)
    simulation, simulation_report = simulation_layout(plan)
    replacements = {aid: data for aid, data in ((RENDER, render), (SIMULATION, simulation)) if data != s['assets'][aid].data}
    if not replacements:
        raise ValueError('This arrangement has no native changes to export')
    original = s['archive']
    edited = bytearray(original.data)
    streams, stats, ranges = {}, [], []
    for aid, payload in replacements.items():
        asset = s['assets'][aid]
        name = STREAM_PREFIX+asset.source_path.name
        stream, report = replace_stream_asset(streams.get(name, original.read(name)), asset, payload)
        streams[name] = stream
        stats.append(dict(resource=f'{aid:016x}', member=name, **report))
        start = original.entries[name]['offset']+report['recordOffset']
        ranges.append((start, start+report['recordStride']))
    for name, payload in streams.items():
        e = original.entries[name]
        edited[e['offset']:e['offset']+e['size']] = payload
    if any(not any(low <= i < high for low, high in ranges) for i, (a, b) in enumerate(zip(original.data, edited)) if a != b):
        raise ValueError('Native archive edit escaped the admitted SFIL records')
    with tempfile.TemporaryDirectory(prefix='nativex-reopen-') as temp:
        folder = Path(temp)
        (folder/'test.big').write_bytes(edited)
        archive = BigArchive(folder/'test.big')
        if archive.entries != original.entries:
            raise ValueError('Native archive directory changed')
        for name in archive.entries:
            path = folder/'reopen'/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(name))
        reread, occurrences = load_assets(folder/'reopen'/STREAM_PREFIX)
        if occurrences != s['occurrences'] or set(reread) != set(s['assets']):
            raise ValueError('Native resource coverage changed')
        for aid, asset in reread.items():
            if asset.data != replacements.get(aid, s['assets'][aid].data):
                raise ValueError('Reopened native archive differs from the intended layout')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    digest = sha(edited)
    target = output/f'blackbox-{digest[:16]}.big'
    if target.exists() and target.read_bytes() != edited:
        raise ValueError('Refusing to overwrite an unrelated export')
    target.write_bytes(edited)
    report = dict(format='nativex-park-export-report', version=1, sourceSha256=SOURCE_SHA256,
                  outputSha256=digest, archiveBytes=len(edited), file=target.name, plan=plan,
                  validation=validation, render=render_report, simulation=simulation_report,
                  storage=stats, resourcesCompared=len(s['assets']), changedResources=[f'{i:016x}' for i in replacements],
                  allTexturesByteIdentical=True, archiveDirectoryAndSizesUnchanged=True,
                  aiTriggersAndSpawnsUnchanged=True, xboxReloadVerified=False,
                  limitations=catalog()['limitations'])
    (output/f'{target.stem}.report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report
