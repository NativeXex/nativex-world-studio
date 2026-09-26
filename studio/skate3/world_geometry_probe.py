"""Hash-pinned Black Box manual-pad translation; not a general level exporter.

Move the isolated 8.396 x 3.059 m, 0.75 m high manual pad four metres along +Z.
Preserve native topology, materials, UVs, identities, links and archive offsets.
"""
import argparse
import json
from pathlib import Path
import struct
import tempfile

from .archive import BigArchive, u32
from .arena import Arena
from .collision_tree import TriangleTree, bounds
from .geometry import decode as decode_geometry
from .refpack_writer import compress
from .vendor.retail_grind_splines import decode_grind_splines, translate_native_segment_payload
from .world_probe import ROOT, SOURCE_SHA256, STREAM_PREFIX, load_assets, sha

RENDER = 0x551e1167ead2e4fc
SIMULATION = 0x6a808dc6f03d6adb
DELTA = (0., 0., 4.)
SELECTION = ((22.4, -.01, 63.15), (30.9, .8, 66.35))
RAILS = {'0xCA834E1A83F2A265', '0xDFA5EEA27D782AAA'}


def selected(point):
    return all(SELECTION[0][a] <= point[a] <= SELECTION[1][a] for a in range(3))


def moved(point):
    return tuple(point[a]+DELTA[a] for a in range(3))


def contained(bb, points, tolerance=.003):
    return all(bb[0][a]-tolerance <= p[a] <= bb[1][a]+tolerance for p in points for a in range(3))


def native_box(data, at):
    return [list(struct.unpack_from('>3f', data, at)), list(struct.unpack_from('>3f', data, at+16))]


def subreference(arena, value):
    data = arena.data
    manifest = u32(data, 52)
    if u32(data, manifest) != 0x10004:
        raise ValueError('Unknown arena section manifest')
    table = manifest+u32(data, manifest+8)
    sections = [manifest+u32(data, table+i*4) for i in range(u32(data, manifest+4))]
    subs = [p for p in sections if u32(data, p) == 0x10007]
    if value >> 16 != 0x80 or len(subs) != 1:
        raise ValueError('Unsupported island reference')
    sub = subs[0]
    index = value & 0xffff
    if index >= u32(data, sub+24):
        raise ValueError('Island subreference outside arena')
    section, offset = struct.unpack_from('>II', data, u32(data, sub+20)+index*8)
    if section >= len(arena.sections) or offset+32 > arena.sections[section]['size']:
        raise ValueError('Island bound reference is invalid')
    return arena.sections[section]['offset']+offset


def translate_render(data):
    before = decode_geometry(data)
    arena = Arena(data)
    output = bytearray(data)
    addresses = set()
    report = []
    triangles = 0
    for group in before['groups']:
        sid = group['sourceSection']
        mesh = arena.section(sid, 0xeb0023)
        positions = [tuple(group['positions'][i:i+3]) for i in range(0, len(group['positions']), 3)]
        selected_vertices = {i for i, p in enumerate(positions) if selected(p)}
        if not selected_vertices:
            continue
        if sid not in (301, 308):
            raise ValueError('Selection unexpectedly touches another render mesh')
        count = 0
        for j in range(0, len(group['indices']), 3):
            hits = [i in selected_vertices for i in group['indices'][j:j+3]]
            if any(hits) and not all(hits):
                raise ValueError('Render selection cuts through a triangle')
            count += int(all(hits))
        declaration = arena.section(u32(mesh, 40), 0x200e9)
        elems, streams = struct.unpack_from('>HH', declaration, 8)
        if streams != 1:
            raise ValueError('Multiple vertex streams are not admitted')
        stride = declaration[16+elems*16]
        position = None
        for i in range(elems):
            stream, offset, kind, _, usage, usage_index, _, _ = struct.unpack_from('>HHIBBBBI', declaration, 16+i*16)
            if usage == 0 and usage_index == 0:
                position = (stream, offset, kind)
        if position is None or position[0] != 0 or position[2] != 0x2a23b9:
            raise ValueError('First render move requires native float3 positions')
        vb = arena.section(u32(mesh, 52), 0x200ea)
        raw_section = arena.sections[u32(vb, 24) >> 2]
        if raw_section['type'] != 0x10031:
            raise ValueError('Vertex storage is not a GPU buffer')
        for i in selected_vertices:
            at = raw_section['offset']+i*stride+position[1]
            if at in addresses:
                raise ValueError('Render groups alias a moved vertex buffer')
            addresses.add(at)
            if struct.unpack_from('>3f', data, at) != positions[i]:
                raise ValueError('Vertex source mapping disagrees with decoder')
            struct.pack_into('>3f', output, at, *moved(positions[i]))
        all_after = [moved(p) if i in selected_vertices else p for i, p in enumerate(positions)]
        if not contained(native_box(mesh, 0), all_after) or not contained(before['declaredBounds'], all_after):
            raise ValueError('Move leaves preserved mesh/model visibility bounds')
        # Bounds are arena subreferences, not local mesh offsets. Verify every
        # draw island still fits its preserved native visibility box.
        box_at = subreference(arena, u32(mesh, 64))
        draws = u32(mesh, 68)
        for island in range(u32(mesh, 56)):
            _, _, _, length = struct.unpack_from('>IiII', mesh, draws+island*16)
            # This hash-pinned target has one island covering its complete mesh.
            if u32(mesh, 56) != 1 or length != len(group['indices']):
                raise ValueError('Unexpected target draw-island layout')
            if not contained(native_box(data, box_at+island*32), all_after):
                raise ValueError('Move leaves preserved draw-island bounds')
        report.append(dict(section=sid, vertices=len(selected_vertices), triangles=count))
        triangles += count
    if triangles != 10 or {r['section'] for r in report} != {301, 308}:
        raise ValueError('Manual-pad render selection differs from measured source')
    result = bytes(output)
    after = decode_geometry(result)
    for old, new in zip(before['groups'], after['groups']):
        if old['indices'] != new['indices']:
            raise ValueError('Render topology changed')
        for i in range(0, len(old['positions']), 3):
            p = tuple(old['positions'][i:i+3])
            expected = moved(p) if selected(p) else p
            if any(abs(new['positions'][i+a]-expected[a]) > 1e-5 for a in range(3)):
                raise ValueError('Render move escaped its selection')
    allowed = {at+i for at in addresses for i in range(12)}
    if any(i not in allowed for i, (a, b) in enumerate(zip(data, result)) if a != b):
        raise ValueError('Non-position render data changed')
    return result, dict(triangles=triangles, vertices=len(addresses), groups=report,
                        uvNormalsMaterialsIndicesUnchanged=True, visibilityBoundsPreservedAndChecked=True)


def translate_rails(data):
    output = bytearray(data)
    before = decode_grind_splines(data)
    moved_rails = []
    for rail in before:
        payloads = rail['native_segment_payloads']
        points = []
        for payload in payloads:
            v = struct.unpack('>30f', bytes.fromhex(payload))
            points.extend([v[12:15], tuple(sum(v[j+a] for j in (0, 4, 8, 12)) for a in range(3))])
        hits = [selected(p) for p in points]
        if any(hits) != (rail['spline_id'] in RAILS) or (any(hits) and not all(hits)):
            raise ValueError('Grind selection crosses or misses an attachment')
        if not any(hits):
            continue
        start = rail['section_offset']
        row = start+16+rail['rail_index']*32
        first = u32(data, row+20)
        for i, payload in enumerate(payloads):
            at = start+first+i*144
            if data[at:at+120].hex() != payload:
                raise ValueError('Grind source mapping disagrees with decoder')
            output[at:at+120] = bytes.fromhex(translate_native_segment_payload(payload, DELTA))
        moved_rails.append(dict(id=rail['spline_id'], segments=len(payloads)))
    if {r['id'] for r in moved_rails} != RAILS or sum(r['segments'] for r in moved_rails) != 4:
        raise ValueError('Incomplete manual-pad grind loop')
    after = decode_grind_splines(bytes(output))
    for old, new in zip(before, after):
        expected = dict(old)
        if old['spline_id'] in RAILS:
            expected['native_segment_payloads'] = [translate_native_segment_payload(p, DELTA) for p in old['native_segment_payloads']]
        if expected != new:
            raise ValueError('Grind data differs from exact intended translation')
    return bytes(output), moved_rails


def floor_hit(x, z, tri):
    a, b, c = tri.a, tri.b, tri.c
    den = (b[2]-c[2])*(a[0]-c[0])+(c[0]-b[0])*(a[2]-c[2])
    if abs(den) < 1e-8:
        return False
    u = ((b[2]-c[2])*(x-c[0])+(c[0]-b[0])*(z-c[2]))/den
    v = ((c[2]-a[2])*(x-c[0])+(a[0]-c[0])*(z-c[2]))/den
    return min(u, v, 1-u-v) >= -1e-6


def translate_simulation(data):
    arena = Arena(data)
    ids = arena.indices(0x80006)
    if len(ids) != 1:
        raise ValueError('Expected one collision mesh')
    tree = TriangleTree(arena.section(ids[0]))
    chosen = []
    for i, tri in enumerate(tree.mesh.triangles):
        hits = [selected(p) for p in (tri.a, tri.b, tri.c)]
        if any(hits) and not all(hits):
            raise ValueError('Collision selection cuts through a triangle')
        if all(hits):
            chosen.append(i)
    if len(chosen) != 10:
        raise ValueError('Manual-pad collision selection differs from measured source')
    before_bounds = bounds([p for i in chosen for p in (tree.mesh.triangles[i].a, tree.mesh.triangles[i].b, tree.mesh.triangles[i].c)])
    after_bounds = [list(moved(p)) for p in before_bounds]
    # Reject any stationary triangle whose AABB overlaps the moved pad above
    # floor height. This intentionally conservative check is not a general
    # swept-volume or playability validator.
    for i, tri in enumerate(tree.mesh.triangles):
        if i in chosen:
            continue
        bb = bounds([tri.a, tri.b, tri.c])
        if bb[1][1] > .003 and all(bb[1][a] > after_bounds[0][a]+.003 and bb[0][a] < after_bounds[1][a]-.003 for a in range(3)):
            raise ValueError(f'Destination overlaps stationary collision triangle {i}')
    floor = [t for t in tree.mesh.triangles if all(abs(p[1]) < .003 for p in (t.a, t.b, t.c))]
    support = []
    for bb in (before_bounds, after_bounds):
        points = [(bb[0][0]+.01+(bb[1][0]-bb[0][0]-.02)*i/20,
                   bb[0][2]+.01+(bb[1][2]-bb[0][2]-.02)*j/10) for i in range(21) for j in range(11)]
        hits = sum(any(floor_hit(x, z, t) for t in floor) for x, z in points)
        if hits != len(points):
            raise ValueError('Original or destination footprint lacks sampled floor support')
        support.append(hits)
    collision, report = tree.translate(chosen, DELTA)
    output = bytearray(data)
    section = arena.sections[ids[0]]
    output[section['offset']:section['offset']+section['size']] = collision
    result, rails = translate_rails(bytes(output))
    # Only clustered collision and spline sections may change in this arena.
    checked = Arena(result)
    for s in arena.sections:
        if s['type'] not in (0x80006, 0xeb0004) and arena.section(s['index']) != checked.section(s['index']):
            raise ValueError('Unrelated simulation section changed')
    report.update(beforeBounds=before_bounds, afterBounds=after_bounds, grindRails=rails,
                  sampledFloorSupport=support, stationaryCollisionAabbClearance=True,
                  surfaceIdsEdgesTopologyAndGrindLinksPreserved=True)
    return result, report


def replace_stream_asset(stream, asset, data):
    """Recompress within the existing SFIL record allocation, or refuse."""
    if len(data) != len(asset.data):
        raise ValueError('Experiment cannot resize an arena')
    output = bytearray(stream)
    off = asset.source_offset
    values = list(struct.unpack_from('>11I', stream, off+128))
    cpu_size, cpu_stored, cpu_compression = values[:3]
    gpu_size, gpu_stored, gpu_compression = values[8:11]
    stride = u32(stream, off+16)
    if u32(stream, off+12) != 128 or cpu_size+gpu_size != len(data):
        raise ValueError('Unsupported SFIL allocation')
    choices = []
    for chain in (128, 512, 2048):
        encoded = []
        cursor = off+208
        raw_at = 0
        for size, stored, method in ((cpu_size, cpu_stored, cpu_compression), (gpu_size, gpu_stored, gpu_compression)):
            chunk = data[raw_at:raw_at+size]
            if chunk == asset.data[raw_at:raw_at+size]:
                encoded.append((stream[cursor:cursor+stored], method))
            else:
                encoded.append((compress(chunk, chain_limit=chain), 1))
            raw_at += size
            cursor += stored
        total = 208+sum(len(c) for c, _ in encoded)
        choices.append((total, encoded))
        if total <= stride:
            break
    total, encoded = min(choices, key=lambda x: x[0])
    if total > stride:
        raise ValueError(f'Recompressed resource exceeds original allocation by {total-stride} bytes')
    cpu, gpu = encoded
    struct.pack_into('>I', output, off+8, 80+len(cpu[0])+len(gpu[0]))
    struct.pack_into('>3I', output, off+128, cpu_size, len(cpu[0]), cpu[1])
    struct.pack_into('>3I', output, off+160, gpu_size, len(gpu[0]), gpu[1])
    output[off+208:off+stride] = cpu[0]+gpu[0]+bytes(stride-total)
    if len(output) != len(stream) or output[:off] != stream[:off] or output[off+stride:] != stream[off+stride:]:
        raise ValueError('Recompression escaped original stream allocation')
    return bytes(output), dict(recordOffset=off, recordStride=stride, oldCpuStored=cpu_stored,
                               newCpuStored=len(cpu[0]), oldGpuStored=gpu_stored, newGpuStored=len(gpu[0]),
                               remainingPadding=stride-total)


def build(output, source=None):
    source = Path(source) if source else ROOT/'data/world-source/worldDIST_BlackBoxPark.big'
    original = BigArchive(source)
    if sha(original.data) != SOURCE_SHA256:
        raise ValueError('Manual-pad experiment requires the verified original Black Box archive')
    edited = bytearray(original.data)
    with tempfile.TemporaryDirectory(prefix='nativex-geometry-') as temporary:
        tmp = Path(temporary)
        for name, entry in original.entries.items():
            if entry['packed']:
                raise ValueError('Probe requires stored archive members')
            path = tmp/'source'/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(original.read(name))
        assets, occurrences = load_assets(tmp/'source'/STREAM_PREFIX)
        render, render_report = translate_render(assets[RENDER].data)
        simulation, simulation_report = translate_simulation(assets[SIMULATION].data)
        replacements = {RENDER: render, SIMULATION: simulation}
        storage = []
        ranges = []
        for aid, payload in replacements.items():
            asset = assets[aid]
            name = STREAM_PREFIX+asset.source_path.name
            if name not in (STREAM_PREFIX+'cpres_50_50_high.xsf', STREAM_PREFIX+'csim_50_50_high.xsf'):
                raise ValueError('Unexpected native target stream')
            stream, stats = replace_stream_asset(original.read(name), asset, payload)
            entry = original.entries[name]
            edited[entry['offset']:entry['offset']+entry['size']] = stream
            storage.append(dict(member=name, resource=f'{aid:016x}', **stats))
            start = entry['offset']+stats['recordOffset']
            ranges.append([start, start+stats['recordStride']])
        if any(not any(start <= i < end for start, end in ranges) for i, (a, b) in enumerate(zip(original.data, edited)) if a != b):
            raise ValueError('Output changed outside the two admitted SFIL records')
        test = tmp/'edited.big'
        test.write_bytes(edited)
        actual = BigArchive(test)
        if actual.entries != original.entries:
            raise ValueError('Archive directory or file positions changed')
        members = []
        for name in actual.entries:
            data = actual.read(name)
            if data != original.read(name):
                members.append(name)
            path = tmp/'actual'/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        reread, count = load_assets(tmp/'actual'/STREAM_PREFIX)
        if count != occurrences or set(reread) != set(assets) or len(assets) != 110:
            raise ValueError('Native resource coverage changed')
        changed = {aid for aid in assets if assets[aid].data != reread[aid].data}
        if changed != set(replacements):
            raise ValueError('Unexpected decoded resource changes')
        for aid, payload in replacements.items():
            if reread[aid].data != payload:
                raise ValueError('Reopened archive differs from intended edit')
        decode_geometry(reread[RENDER].data)
        TriangleTree(Arena(reread[SIMULATION].data).one(0x80006))
        decode_grind_splines(reread[SIMULATION].data)
    report = dict(format='nativex-world-geometry-probe', version=1, sourceSha256=SOURCE_SHA256,
                  outputSha256=sha(edited), archiveBytes=len(edited), outputFile='manual-pad-move.big',
                  target='Black Box low rectangular manual pad', translation=list(DELTA),
                  sourceSelection=SELECTION, render=render_report, simulation=simulation_report,
                  storage=storage, allowedArchiveRanges=ranges, changedMembers=members,
                  changedResources=[f'{aid:016x}' for aid in sorted(changed)], resourcesCompared=len(assets),
                  untouchedResourcesByteIdentical=True, allTexturesByteIdentical=True,
                  archiveDirectoryAndSizesUnchanged=True, worldCellBoundsPreserved=True,
                  aiTriggersDmosNavAndSpawnDataUnchanged=True, xboxReloadVerified=False,
                  generalLevelExportSupported=False)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    target = output/'manual-pad-move.big'
    if target.exists() and target.read_bytes() != edited:
        raise ValueError('Refusing to overwrite a different geometry experiment')
    target.write_bytes(edited)
    (output/'build-report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output), indent=2))
