"""Experimental Black Box section translations/copies using native model instances.

Static model buffers and collision trees are shared by additional native placement
records. Grind cubics are independent world-space records. No editor sidecar is
needed by the game. Runtime validation remains a separate Xbox test.
"""
import hashlib
import json
from pathlib import Path
import struct
import tempfile

from .. import levels
from .archive import BigArchive, u32
from .arena import Arena
from .arena_writer import align, append_sections, extend_toc, subrefs
from .collision_tree import TriangleTree, bounds
from .geometry import decode
from .native_instances import instances, render_instances, collision_instances
from .refpack_writer import compress
from .vendor.retail_grind_splines import decode_grind_splines, translate_native_segment_payload
from .vendor.skate3_streams import read_atoc, read_sfil
from .world_probe import ROOT, SOURCE_SHA256, STREAM_PREFIX, load_assets, sha


def guid(*parts):
    return int.from_bytes(hashlib.sha256('|'.join(map(str, parts)).encode()).digest()[:8], 'big') | (1 << 63)


def source_path(manifest):
    if manifest['id'] == 'blackbox' and manifest['sourceSha256'] == SOURCE_SHA256:
        path = ROOT/'data/world-source/worldDIST_BlackBoxPark.big'
    elif manifest['id'].startswith('blackbox-export-'):
        name = manifest.get('walkTest', {}).get('archiveFile', '')
        import re
        if not re.fullmatch(r'blackbox-[0-9a-f]{16}\.big', name):
            raise ValueError('Section export requires a verified Black Box source archive')
        path = ROOT/'data/park-exports'/name
        report = json.loads(path.with_suffix('.report.json').read_text())
        if report['sourceSha256'] != SOURCE_SHA256 or report['outputSha256'] != manifest['sourceSha256']:
            raise ValueError('Source archive is not a verified Black Box module export')
    else:
        raise ValueError('Native section export currently supports Black Box and its verified obstacle exports')
    if sha(path.read_bytes()) != manifest['sourceSha256']:
        raise ValueError('Source archive changed')
    return path


def placements(plan, manifest):
    levels.validate(plan)
    if plan['gameBuild'] != 'skate3-xbox360-tu3':
        raise ValueError('Xbox section export requires Skate 3')
    if len(plan['instances']) > 32:
        raise ValueError('Experimental native export admits at most 32 section instances')
    result = {}
    for section in manifest['sections']:
        selected = [i for i in plan['instances'] if i['sectionId'] == section['id']]
        originals = [i for i in selected if i['origin'] == 'original']
        if len(originals) != 1 or not all(i['visible'] for i in selected):
            raise ValueError('Native section export requires every original section visible; hide/delete is not supported')
        selected = originals + [i for i in selected if i['origin'] == 'copy']
        rows = []
        for item in selected:
            if item['yaw'] % 360:
                raise ValueError('Native section rotations are not supported yet; translations and copies are supported')
            delta = [item['position'][a]-section['pivot'][a] for a in range(3)]
            bb = [[p[a]+delta[a] for a in range(3)] for p in section['bounds']]
            world = manifest['bounds']
            if any(p[a] < world[0][a]-.08 or p[a] > world[1][a]+.08 for p in bb for a in range(3)):
                raise ValueError('Section leaves the original Black Box world bounds')
            rows.append(dict(id=item['id'], delta=delta, bounds=bb))
        result[section['id']] = rows
    return result


def edit_resource(data, rows, component, *, copy_grinds=True):
    arena = Arena(data)
    native = instances(data, component)
    if len(native) != 1 or any(native[0]['delta']):
        raise ValueError('Source must contain one baked identity instance per section resource')
    if len(rows) == 1 and not any(rows[0]['delta']):
        return data
    sid = native[0]['section']
    s = arena.section(sid)
    start, strings = u32(s, 12), u32(s, 16)
    if u32(s, 4) != 1 or start != 32 or strings != 192:
        raise ValueError('Unsupported source placement/string table')
    _, refs = subrefs(arena)
    extra_refs, toc = [], []
    shift = (len(rows)-1)*160
    output = bytearray(s[:start])
    struct.pack_into('>I', output, 4, len(rows))
    struct.pack_into('>I', output, 16, strings+shift)
    for index, row in enumerate(rows):
        record = bytearray(s[start:start+160])
        struct.pack_into('>3f', record, 48, *row['delta'])
        for at in (64, 80):
            point = struct.unpack_from('>3f', s, start+at)
            struct.pack_into('>3f', record, at, *(point[a]+row['delta'][a] for a in range(3)))
        for at in (140, 144, 148, 152):
            pointer = u32(record, at)
            if pointer < strings or pointer >= len(s):
                raise ValueError('Unknown native instance string pointer')
            struct.pack_into('>I', record, at, pointer+shift)
        if index:
            identity = guid(row['id'], component, native[0]['guid'])
            struct.pack_into('>Q', record, 96, identity)
            toc.append((identity, 0xeb0069, 0x800000+len(refs)+len(extra_refs)))
            extra_refs.append((sid, start+index*160))
        output.extend(record)
    output.extend(s[strings:])
    replacements = {sid: bytes(output)}
    if component == 'collision' and copy_grinds:
        spline_sid, = arena.indices(0xeb0004)
        old = arena.section(spline_sid)
        nr, ns, rt, st = struct.unpack_from('>4I', old)
        if rt != 16 or st != 16+nr*32 or len(old) != st+ns*144:
            raise ValueError('Unsupported native spline layout')
        new_st = 16+nr*len(rows)*32
        spline = bytearray(struct.pack('>4I', nr*len(rows), ns*len(rows), 16, new_st))
        segments = bytearray()
        old_toc = arena.toc()
        for index, row in enumerate(rows):
            for rail in range(nr):
                at = rt+rail*32
                record = bytearray(old[at:at+32])
                if u32(record, 16):
                    raise ValueError('Attached grind instance needs a separate writer')
                for p in (20, 24):
                    struct.pack_into('>I', record, p, new_st+index*ns*144+(u32(record, p)-st))
                if index:
                    struct.pack_into('>Q', record, 0, guid(row['id'], 'rail', rail))
                    exported = [t for t in old_toc if t['type'] == 0xeb0064 and
                                refs[t['handle']-0x800000] == (spline_sid, at)]
                    if len(exported) != 1:
                        raise ValueError('Unresolved grind export binding')
                    toc.append((guid(row['id'], 'grind-export', rail), 0xeb0064,
                                0x800000+len(refs)+len(extra_refs)))
                    extra_refs.append((spline_sid, 16+(index*nr+rail)*32))
                spline.extend(record)
            for segment in range(ns):
                at = st+segment*144
                record = bytearray(old[at:at+144])
                record[:120] = bytes.fromhex(translate_native_segment_payload(record[:120].hex(), row['delta']))
                parent = u32(record, 120)
                if parent < 16 or (parent-16) % 32 or parent >= st or any(record[124:]):
                    raise ValueError('Unsupported native grind segment links')
                struct.pack_into('>I', record, 120, parent+index*nr*32)
                segments.extend(record)
        spline.extend(segments)
        replacements[spline_sid] = bytes(spline)
    if toc:
        toc_sid, = arena.indices(0xeb000b)
        replacements[toc_sid] = extend_toc(arena.section(toc_sid), toc)
    result = append_sections(data, replacements, extra_refs)
    if len(instances(result, component)) != len(rows):
        raise ValueError('Native instance count failed to reopen')
    if component == 'render':
        render_instances(result, decode(result))
    else:
        collision_instances(result)
        grind_copies = len(rows) if copy_grinds else 1
        if len(decode_grind_splines(result)) != grind_copies*len(decode_grind_splines(data)):
            raise ValueError('Native grind copy count failed to reopen')
        for tree in arena.indices(0x80006):
            TriangleTree(Arena(result).section(tree))
    return result


def replace_sfil(source, records, replacements):
    """Resize only changed records; retain every other record's exact bytes."""
    output = bytearray(source[:u32(source, 16)])
    alignment = u32(source, 16)
    cursor = alignment
    while cursor < len(source) and any(source[cursor:]):
        aid = struct.unpack_from('>Q', source, cursor)[0]
        stride = u32(source, cursor+16)
        if aid not in replacements:
            output.extend(source[cursor:cursor+stride])
        else:
            data = replacements[aid]
            cpu_size = u32(data, 68)
            chunks = [data[:cpu_size], data[cpu_size:]]
            encoded = []
            for chunk in chunks:
                packed = compress(chunk) if chunk else b''
                encoded.append((packed, 1) if len(packed) < len(chunk) else (chunk, 0))
            header = bytearray(source[cursor:cursor+208])
            total = 208+sum(len(v) for v, _ in encoded)
            struct.pack_into('>III', header, 8, total-128, 128, align(total, alignment))
            for at, chunk, (payload, method) in zip((128, 160), chunks, encoded):
                struct.pack_into('>III', header, at, len(chunk), len(payload), method)
            output.extend(header)
            for payload, _ in encoded:
                output.extend(payload)
            output.extend(bytes(align(total, alignment)-total))
        cursor += stride
    return bytes(output)


def rebuild_big(archive, replacements):
    """Same member directory/names; update explicit offsets, lengths and total size."""
    first = min(e['offset'] for e in archive.entries.values())
    output = bytearray(archive.data[:first])
    shift = archive.data[10]
    row_size = 20 if struct.unpack_from('>H', archive.data, 8)[0] & 1 else 16
    indices = {name: i for i, name in enumerate(archive.entries)}
    for name, entry in sorted(archive.entries.items(), key=lambda p: p[1]['offset']):
        if entry['packed']:
            raise ValueError('Section compiler requires stored BIG members')
        at = align(len(output), 1 << shift)
        output.extend(bytes(at-len(output)))
        payload = replacements.get(name, archive.read(name))
        struct.pack_into('>III', output, 48+indices[name]*row_size, at >> shift, 0, len(payload))
        output.extend(payload)
    struct.pack_into('>I', output, 28, len(output))
    return bytes(output)


def relocation_targets(plan, manifest, rows):
    """An explicit control relocates bytes without changing any native payload."""
    control = plan.get('diagnosticControl')
    if control is None:
        return set()
    if (not isinstance(control, dict) or set(control) != {'kind', 'sections'} or
            control['kind'] != 'relocate-identical-sections-v1'):
        raise ValueError('Unknown native export diagnostic control')
    selected = control['sections']
    if (not isinstance(selected, list) or not selected or
            any(not isinstance(s, str) for s in selected) or
            len(set(selected)) != len(selected) or
            not set(selected) <= {s['id'] for s in manifest['sections']}):
        raise ValueError('Invalid diagnostic section selection')
    if any(len(group) != 1 or any(group[0]['delta']) for group in rows.values()):
        raise ValueError('Storage diagnostic requires unchanged original placements')
    return set(selected)


def relocate_resource(data):
    arena = Arena(data)
    kinds = {0xeb000d, 0xeb000b, 0xeb0004}
    replacements = {s['index']: arena.section(s['index']) for s in arena.sections if s['type'] in kinds}
    if not arena.indices(0xeb000d):
        raise ValueError('Storage diagnostic requires a native placement section')
    result = append_sections(data, replacements)
    # Independent native section comparison, including GPU buffers, trees,
    # TOC exports, strings and spline links. Only their storage can differ.
    after = Arena(result)
    if subrefs(arena) != subrefs(after):
        raise ValueError('Storage diagnostic changed native subreferences')
    for section in arena.sections:
        if arena.section(section['index']) != after.section(section['index']):
            raise ValueError('Storage diagnostic changed a native section payload')
    return result


def build(plan, destination):
    manifest = levels.source_for(plan.get('sourceId'))
    rows = placements(plan, manifest)
    control = plan.get('diagnosticControl')
    copy_mode = control.get('kind') if isinstance(control, dict) else None
    render_only = copy_mode == 'copy-render-only-v1'
    no_grinds = copy_mode in ('copy-render-only-v1', 'copy-render-collision-only-v1')
    if no_grinds:
        if (set(control) != {'kind'} or sum(map(len, rows.values())) != len(rows)+1 or
                any(any(group[0]['delta']) for group in rows.values())):
            raise ValueError('Copy diagnostic requires unchanged originals and exactly one copy')
        relocated = set()
    else:
        relocated = relocation_targets(plan, manifest, rows)
    path = source_path(manifest)
    archive = BigArchive(path)
    replacements, members = {}, {}
    with tempfile.TemporaryDirectory(prefix='nativex-section-') as temp:
        folder = Path(temp)
        for name in archive.entries:
            target = folder/'source'/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
        root = folder/'source'/STREAM_PREFIX
        assets, occurrences = load_assets(root)
        for section in manifest['sections']:
            for component, ids in (('render', [m['id'] for m in section['models']]),
                                   ('collision', section['simulation'])):
                if len(ids) != 1:
                    raise ValueError('Expected one source model per Black Box section')
                aid = int(ids[0], 16)
                resource_rows = rows[section['id']][:1] if render_only and component == 'collision' else rows[section['id']]
                new = (relocate_resource(assets[aid].data) if section['id'] in relocated else
                       edit_resource(assets[aid].data, resource_rows, component, copy_grinds=not no_grinds))
                if new != assets[aid].data:
                    replacements[aid] = new
        for stream in ('pres', 'sim'):
            table_name = STREAM_PREFIX+f'dist_blackboxpark_{stream}.xst'
            records = read_atoc(folder/'source'/table_name)
            table = bytearray(archive.read(table_name))
            changed_streams = {}
            for i, record in enumerate(records):
                if record.asset_id in replacements:
                    data = replacements[record.asset_id]
                    struct.pack_into('>II', table, 24+i*64+12, len(data), u32(data, 68))
                    struct.pack_into('>I', table, 24+i*64+32, u32(data, 84))
            if table != archive.read(table_name):
                members[table_name] = bytes(table)
            for f in root.glob('c'+stream+'_*.xsf'):
                if f.name.startswith('.'):
                    continue
                owned = read_sfil(f, records, require_all_records=False)
                if not any(a.record.asset_id in replacements for a in owned):
                    continue
                rebuilt = replace_sfil(f.read_bytes(), records, replacements)
                members[STREAM_PREFIX+f.name] = rebuilt
                changed_streams[f.stem.lower()] = (len(rebuilt), len(owned))
            map_name = STREAM_PREFIX+f'dist_blackboxpark_{stream}.xsm'
            cmap = bytearray(archive.read(map_name))
            if cmap[:4] != b'CMAP' or len(cmap) != 32+u32(cmap, 16)*104:
                raise ValueError('Unsupported stream allocation map')
            stream_ids = {}
            for i in range(u32(cmap, 16)):
                at = 32+i*104
                name = cmap[at+28:at+92].split(b'\0')[0].decode().lower()
                if name in changed_streams:
                    length, count = changed_streams[name]
                    if u32(cmap, at+24) != count or u32(cmap, at+16) != 128:
                        raise ValueError('Source stream allocation count differs')
                    struct.pack_into('>I', cmap, at+20, length-128)
                stream_ids[name] = bytes(cmap[at:at+8])
            if cmap != archive.read(map_name):
                members[map_name] = bytes(cmap)
            spatial_name = STREAM_PREFIX+f'dist_blackboxpark_{stream}.xss'
            spatial = bytearray(archive.read(spatial_name))
            if spatial[:4] != b'CSPA' or len(spatial) != 24+u32(spatial, 16)*80:
                raise ValueError('Unsupported native cell spatial map')
            for section in manifest['sections']:
                if no_grinds:
                    continue  # Isolate render instance records from spatial-map changes.
                if len(rows[section['id']]) == 1 and not any(rows[section['id']][0]['delta']):
                    continue
                cell_id = stream_ids['c'+stream+'_'+section['id']+'_high']
                at, = [24+i*80 for i in range(u32(spatial, 16)) if spatial[24+i*80:32+i*80] == cell_id]
                # Expand both load and content bounds to include every placement;
                # preserve existing margins/dependencies and source cell identity.
                for box_offset in (16, 48):
                    for side in (0, 1):
                        offset = at+box_offset+side*16
                        old = struct.unpack_from('>3f', spatial, offset)
                        fn = min if side == 0 else max
                        expanded = [fn([old[a]]+[r['bounds'][side][a] for r in rows[section['id']]]) for a in range(3)]
                        struct.pack_into('>3f', spatial, offset, *expanded)
            if spatial != archive.read(spatial_name):
                members[spatial_name] = bytes(spatial)
        payload = rebuild_big(archive, members) if members else archive.data
        test = folder/'candidate.big'
        test.write_bytes(payload)
        reopened = BigArchive(test)
        if set(reopened.entries) != set(archive.entries):
            raise ValueError('Archive member coverage changed')
        for name in reopened.entries:
            raw = reopened.read(name)
            if raw != members.get(name, archive.read(name)):
                raise ValueError('Archive member differs after reopening')
            target = folder/'actual'/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        reread, count = load_assets(folder/'actual'/STREAM_PREFIX)
        if count != occurrences or set(reread) != set(assets):
            raise ValueError('Native resource coverage changed')
        for aid, asset in reread.items():
            if asset.data != replacements.get(aid, assets[aid].data):
                raise ValueError('Reopened native resource differs from compiled data')
        totals = dict(renderTriangles=0, collisionTriangles=0, grindRails=0, grindSegments=0)
        for section in manifest['sections']:
            n = len(rows[section['id']])
            totals['renderTriangles'] += n*sum(m['triangles'] for m in section['models'])
            if render_only:
                n = 1
            totals['collisionTriangles'] += n*sum(m['triangles'] for m in section['collision'])
            if no_grinds:
                n = 1
            totals['grindRails'] += n*sum(m['count'] for m in section['rails'])
            totals['grindSegments'] += n*sum(m['segments'] for m in section['rails'])
    digest = sha(payload)
    name = 'blackbox-sections-'+digest[:16]+'.big'
    report = dict(format='nativex-section-export', version=1, file=name, sourceSha256=manifest['sourceSha256'],
                  sourceId=manifest['id'], outputSha256=digest, archiveBytes=len(payload),
                  planSha256=sha(json.dumps(plan, sort_keys=True, separators=(',', ':')).encode()),
                  plan=plan, placements=rows, nativeInstanceCount=sum(map(len, rows.values())),
                  resourcesCompared=len(assets), changedResources=[f'{aid:016x}' for aid in sorted(replacements)],
                  changedMembers=sorted(members), expected=totals, nativeExportVerified=True,
                  xboxRuntimeVerified=False, originalBackupSha256=SOURCE_SHA256,
                  limitations=['Experimental native model instancing; requires an Xbox load and ride test.',
                               'Translations and copies only. Original sections must stay visible and inside the original world.',
                               'AI, triggers, dynamic objects, spawn records and baked lighting are preserved, not duplicated or regenerated.',
                               'Section seams and overlaps are not automatically repaired.'])
    if relocated:
        report['diagnosticControl'] = plan['diagnosticControl']
        report['allNativeSectionPayloadsByteIdentical'] = True
        report['limitations'] = ['Storage-only diagnostic: original placements, geometry, collision, grinds and spatial bounds are unchanged.',
                                 'Native arena and archive storage changed; Xbox loading remains unverified.']
    if render_only:
        report['diagnosticControl'] = control
        report['renderInstanceCount'] = sum(map(len, rows.values()))
        report['collisionInstanceCount'] = len(rows)
        report['limitations'] = ['Visual-copy diagnostic only: the duplicate has NO added collision or grind records.',
                                 'Original simulation resources and all spatial maps are byte-identical to the source.',
                                 'Xbox rendering/loading remains unverified; this is not a finished skateable export.']
    if copy_mode == 'copy-render-collision-only-v1':
        report['diagnosticControl'] = control
        report['renderInstanceCount'] = report['collisionInstanceCount'] = sum(map(len, rows.values()))
        report['limitations'] = ['Collision-copy diagnostic: the duplicate has render and collision placements but NO added grind records.',
                                 'All original grind payloads and spatial maps are byte-identical to the source.',
                                 'Xbox duplicate collision remains unverified; this is not a finished export.']
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for filename, content in ((name, payload), (report['planSha256']+'-'+digest[:16]+'.report.json', (json.dumps(report, indent=2)+'\n').encode())):
        target = destination/filename
        if target.exists() and target.read_bytes() != content:
            raise ValueError('Refusing to overwrite a different native export')
        target.write_bytes(content)
    return report
