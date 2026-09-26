"""Traceable local collision tests. A walk test never asserts game compatibility."""
import hashlib
import json
import math
import re
import time
import uuid

from .catalog import ROOT
from .levels import source_for, validate as validate_level, LOCK as LEVEL_LOCK
from .skate3.arena import Arena
from .skate3.collision_tree import TriangleTree
from .skate3.vendor.retail_collision_mesh import decode_rx2_clustered_meshes
from .skate3.world import file_sha, identity_instances, import_world, write_json
from .skate3.native_instances import collision_instances


def digest(data):
    return hashlib.sha256(data).hexdigest()


def describe(key, section=None, *, section_ids=None):
    """Compare browser collision against fresh native decoding, never editor transforms."""
    manifest = source_for(key)
    sections = manifest['sections']
    if section_ids is not None:
        sections = [s for s in sections if s['id'] in section_ids]
    if section is not None:
        sections = [s for s in sections if s['id'] == section]
        if not sections:
            raise ValueError('Unknown collision test section')
    if sum(c['triangles'] for s in sections for c in s['collision']) > 250000:
        raise ValueError('Choose a section for this large world; local walk tests admit 250,000 triangles at once')
    records = {r['id']: r for r in manifest['resources']}
    inputs, triangles, trees = [], 0, 0
    for s in sections:
        for entry in s['collision']:
            aid = entry['id']
            if not re.fullmatch(r'[0-9a-f]{16}', aid):
                raise ValueError('Invalid collision resource identity')
            raw = (ROOT/'data/world-source'/key/'rx2'/f'{aid}.rx2').read_bytes()
            if digest(raw) != records[aid]['sha256']:
                raise ValueError('Native collision source hash changed; reimport the archive')
            arena = Arena(raw)
            if manifest.get('walkTest', {}).get('compiler') == 'sections-v1':
                decoded = collision_instances(raw) if arena.indices(0x80006) else []
            else:
                if arena.indices(0x80006):identity_instances(raw, 'collision')
                decoded = decode_rx2_clustered_meshes(raw)
            positions = [v for mesh in decoded for t in mesh.triangles for p in (t.a, t.b, t.c) for v in p]
            surfaces = [t.surface for mesh in decoded for t in mesh.triangles]
            path = ROOT/'web/worlds'/key/'collision'/f'{aid}.nxdata'
            payload = path.read_bytes()
            cache = json.loads(payload)
            if cache['positions'] != positions or cache['surfaces'] != surfaces or len(surfaces) != entry['triangles']:
                raise ValueError('Collision preview differs from the decoded native source; reimport before testing')
            for sid in arena.indices(0x80006):
                TriangleTree(arena.section(sid))
                trees += 1
            inputs.append(dict(id=aid, section=s['id'], url=f'/worlds/{key}/collision/{aid}.nxdata',
                               sha256=digest(payload), nativeSha256=digest(raw), triangles=len(surfaces)))
            triangles += len(surfaces)
    if not triangles:
        raise ValueError('No decoded collision surfaces are available')
    reopened = manifest.get('walkTest', {}).get('kind') == 'reopened-skate3-export'
    if reopened:
        filename = manifest['walkTest']['archiveFile']
        section_export = manifest['walkTest'].get('compiler') == 'sections-v1'
        pattern = r'blackbox-sections-[0-9a-f]{16}\.big' if section_export else r'blackbox-[0-9a-f]{16}\.big'
        if not re.fullmatch(pattern, filename):
            raise ValueError('Invalid test archive identity')
        if file_sha(ROOT/'data'/('level-exports' if section_export else 'park-exports')/filename) != manifest['sourceSha256']:
            raise ValueError('Exported archive changed since it was reopened')
    return dict(format='nativex-collision-test-source', version=1, world=key,
                name=manifest['name'], gameBuild=manifest['gameBuild'],
                archiveSha256=manifest['sourceSha256'], manifest=manifest, inputs=inputs,
                sectionIds=[s['id'] for s in sections], subset=section is not None,
                collisionTriangles=triangles, nativeTreesChecked=trees,
                kind='reopened-skate3-export' if reopened else 'decoded-source',
                unsupportedCollision=[u for u in manifest['unsupported'] if u['component']=='collision'],
                xboxRuntimeVerified=False, skate3ConversionVerified=False,
                limitations=['Local capsule approximation; not Skate 3 player or board physics.',
                             'Surface IDs are reported, but game material behaviour and grind physics are not simulated.',
                             'A walked route does not prove coverage of the entire world.'])


def snapshot_plan(plan):
    """Freeze the current editor state without replacing any saved project."""
    validate_level(plan)
    if not any(o['visible'] for o in plan['instances']):
        raise ValueError('Show at least one section before starting a walk test')
    payload = json.dumps(plan, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    identity = digest(payload)
    folder = ROOT/'data/level-walk-tests'
    with LEVEL_LOCK:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder/(identity+'.nxlevel.json')
        if path.exists():
            if path.read_bytes() != payload:
                raise ValueError('Existing walk snapshot does not match its identity')
        else:
            temporary = path.with_suffix('.tmp')
            temporary.write_bytes(payload)
            temporary.replace(path)
    return dict(layout=identity, kind='edited-layout-preview',
                url='/walk.html?world='+plan['sourceId']+'&layout='+identity)


def read_snapshot(identity):
    if not isinstance(identity, str) or not re.fullmatch(r'[0-9a-f]{64}', identity):
        raise ValueError('Invalid walk layout identity')
    payload = (ROOT/'data/level-walk-tests'/(identity+'.nxlevel.json')).read_bytes()
    if digest(payload) != identity:
        raise ValueError('Walk layout snapshot changed; prepare a new test')
    return validate_level(json.loads(payload))


def describe_layout(identity, section=None):
    plan = read_snapshot(identity)
    instances = [o for o in plan['instances'] if o['visible'] and (section is None or o['sectionId']==section)]
    if not instances:
        raise ValueError('No visible instances in this walk test area')
    manifest = source_for(plan['sourceId'])
    lookup = {s['id']: s for s in manifest['sections']}
    triangle_count = sum(c['triangles'] for o in instances for c in lookup[o['sectionId']]['collision'])
    if triangle_count > 250000:
        raise ValueError('Choose a section for this large layout; walk tests admit 250,000 triangles including copies')
    result = describe(plan['sourceId'], section, section_ids={o['sectionId'] for o in instances})
    result.update(kind='edited-layout-preview', name=plan['name'], layoutSha256=identity,
                  layoutPlan=plan, instances=instances, nativeExportVerified=False,
                  collisionTriangles=triangle_count,
                  sourceCollisionTriangles=result['collisionTriangles'],
                  renderTriangles=sum(m['triangles'] for o in instances for m in lookup[o['sectionId']]['models']))
    result['limitations'].insert(0, 'Editor transforms and copies applied locally. This layout has not been exported to a native Xbox archive.')
    return result


def reopen_export(report, path):
    """Reimport the completed .big; build no test data from the proposed plan."""
    if file_sha(path) != report['outputSha256']:
        raise ValueError('Export does not match its validation report')
    section_export = report.get('format') == 'nativex-section-export'
    key = ('blackbox-sections-' if section_export else 'blackbox-export-')+report['outputSha256'][:16]
    manifest = import_world(path, key, 'Black Box · exported collision test', native_placements=section_export)
    if manifest['sourceSha256'] != report['outputSha256'] or manifest['preservation']['archiveReconstruction'] != 'byte-identical':
        raise ValueError('Export reimport failed archive identity checks')
    if any(u['component'] in ('collision', 'geometry') for u in manifest['unsupported']):
        raise ValueError('Export reimport has unsupported geometry or collision')
    manifest['walkTest'] = dict(kind='reopened-skate3-export', archiveFile=report['file'],
                                resourcesCompared=report['resourcesCompared'], xboxRuntimeVerified=False)
    if section_export:
        manifest['walkTest'].update(compiler='sections-v1', planSha256=report['planSha256'])
        for field, summary_field in (('renderTriangles', 'triangles'), ('collisionTriangles', 'collisionTriangles'),
                                     ('grindRails', 'grindRails'), ('grindSegments', 'grindSegments')):
            if manifest['summary'][summary_field] != report['expected'][field]:
                raise ValueError('Reopened section export differs from the saved layout: '+field)
        actual_instances = sum(len(m['nativeInstances']) for s in manifest['sections'] for m in s['models'])
        if actual_instances != report['nativeInstanceCount']:
            raise ValueError('Native section copy count differs after import')
        manifest['walkTest']['nativeInstanceCount'] = actual_instances
    for name in ('manifest.json', 'manifest.nxdata'):
        write_json(ROOT/'web/worlds'/key/name, manifest)
    checked = describe(key)
    evidence = {k: v for k, v in checked.items() if k != 'manifest'}
    write_json(ROOT/'data/collision-tests'/key/'reopen.json', evidence)
    return dict(world=key, url='/walk.html?world='+key, archiveSha256=manifest['sourceSha256'],
                collisionTriangles=checked['collisionTriangles'], nativeTreesChecked=checked['nativeTreesChecked'])


def save_observation(body):
    # Results are observations, never a compatibility approval or export gate.
    layout = body.get('layout')
    source = describe_layout(layout, body.get('section')) if layout else describe(body.get('world'), body.get('section'))
    if body.get('world') != source['world']:
        raise ValueError('Walk report belongs to a different world')
    if body.get('archiveSha256') != source['archiveSha256']:
        raise ValueError('Walk report belongs to a different archive')
    metrics = body.get('metrics', {})
    if not isinstance(metrics, dict) or set(metrics) != {'distance', 'seconds', 'falls', 'resets', 'contacts', 'visitedTriangles'}:
        raise ValueError('Invalid walk metrics')
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 or v > 1e9 for v in metrics.values()):
        raise ValueError('Invalid walk metric value')
    notes = body.get('notes', [])
    if not isinstance(notes, list) or len(notes) > 200:
        raise ValueError('Walk note limit exceeded')
    for note in notes:
        if not isinstance(note, dict) or not isinstance(note.get('text'), str) or len(note['text']) > 1000:
            raise ValueError('Invalid walk note')
        pos = note.get('position')
        if not isinstance(pos, list) or len(pos) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e6 for v in pos):
            raise ValueError('Invalid walk note position')
    report = dict(format='nativex-walk-observation', version=1, createdAt=time.time(),
                  source={k: v for k, v in source.items() if k != 'manifest'}, metrics=metrics, notes=notes,
                  outcome='local-observations-only', xboxRuntimeVerified=False,
                  controller=dict(shape='capsule', radius=.3, height=1.75, maxSlopeDegrees=48,
                                  gravity=18, maxSubstepDistance=.06, maxSubstepSeconds=1/120,
                                  collisionSidedness='two-sided diagnostic', automaticStepClimb=False))
    path = ROOT/'data/collision-tests'/source['world']/(str(uuid.uuid4())+'.walk.json')
    write_json(path, report)
    return dict(path=str(path), report=report)
