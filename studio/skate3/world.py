"""Import original level streams, preserving every source file and dependency.

This produces an editor bundle, not Xbox replacement resources. No game writes.
"""
import argparse, hashlib, json, re, struct, time, os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from collections import Counter
from .archive import BigArchive, u32
from .arena import Arena, string
from .geometry import decode as geometry
from .world_materials import enrich
from .world_textures import decode as texture
from .vendor.skate3_streams import read_atoc, read_sfil
from .vendor.retail_collision_mesh import decode_rx2_clustered_meshes
from .vendor.retail_grind_splines import decode_grind_splines
from .native_instances import instances as native_instances, render_instances, collision_instances

ROOT = Path(__file__).resolve().parents[2]
def sha(data): return hashlib.sha256(data).hexdigest()
def write_json(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(data,allow_nan=False,separators=(',',':'))+'\n');temporary.replace(path)

def file_sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def progress(key,message,current=0,total=0,state='running'):
    write_json(ROOT/'data/world-source'/key/'import-progress.json',dict(state=state,message=message,current=current,total=total,updatedAt=time.time(),pid=os.getpid()))
    print(message,flush=True)

def decode_texture_file(job):
    """A bounded process pool decodes images; original RX2 files stay on disk."""
    key,aid,digest=job;raw=ROOT/'data/world-source'/key/'rx2'/f'{aid}.rx2'
    target=ROOT/'web/worlds'/key/'textures'/f'{aid}.png'
    cache=target.with_suffix('.meta.json')
    try:
        if cache.exists() and target.exists():
            meta=json.loads(cache.read_text())
            if meta.get('sha256')==digest:return meta,None
        meta,png=texture(raw.read_bytes());meta.update(streamAsset=aid,sha256=digest,url=f'/worlds/{key}/textures/{aid}.png')
        target.write_bytes(png);write_json(cache,meta)
        return meta,None
    except ValueError as e:return None,dict(resource=aid,component='texture',reason=str(e))

def identity_instances(data, component='render'):
    """Current importer only admits baked sections with identity world transforms."""
    a=Arena(data);result=[]
    for i in a.indices(0xeb000d):
        s=a.section(i);count,start=u32(s,4),u32(s,12)
        if count>10000 or start+160*count>len(s): raise ValueError('World instance layout not yet supported')
        for n in range(count):
            at=start+n*160
            ref=u32(s,at+(128 if component=='render' else 132))
            expected=0xeb0001 if component=='render' else 0xeb000a
            # Metadata-only instances share this table. They do not place the
            # render/collision model and must not cause duplicate geometry.
            if ref==0:continue
            if ref>=len(a.sections) or a.sections[ref]['type']!=expected:
                raise ValueError('Unresolved native instance model reference')
            matrix=list(struct.unpack_from('>16f',s,at))
            if any(abs(v-(1 if j%5==0 else 0))>1e-5 for j,v in enumerate(matrix)):
                raise ValueError('Nonidentity source world instance transform requires decoding')
            result.append(dict(matrix=matrix,name=string(s,u32(s,at+140)),section=i,index=n,modelSection=ref,
                               guid=f'{struct.unpack_from(">Q",s,at+96)[0]:016x}'))
    if component=='collision':
        refs=[r['modelSection'] for r in result]
        if not refs or len(refs)!=len(set(refs)) or set(refs)!=set(a.indices(0xeb000a)):
            raise ValueError('Collision model instance coverage is unresolved')
        return result
    if len(result)!=1:raise ValueError('Expected one original baked instance')
    return result[0]

def import_world(source, key, label, *, archive_reader=None, member_prefix=None,
                 game_build='skate3-xbox360-tu3', material_enricher=enrich, native_placements=False):
    if not re.fullmatch(r'[a-z0-9-]+',key):raise ValueError('Invalid world key')
    progress(key,'Reading original archive…')
    archive=BigArchive(source,mapped=True) if archive_reader is None else archive_reader(source)
    source_hash=sha(archive.data)
    preserved=ROOT/'data/world-source'/key/'files'
    bundle=ROOT/'web/worlds'/key
    bundle.mkdir(parents=True,exist_ok=True)
    files=[]
    for index,(name,entry) in enumerate(archive.entries.items()):
        if member_prefix is not None and not name.startswith(member_prefix):continue
        if index%100==0:progress(key,f'Preserving original archive members · {index} / {len(archive.entries)}',index,len(archive.entries))
        path=preserved/name
        if not path.resolve().is_relative_to(preserved.resolve()): raise ValueError('Unsafe archive path')
        path.parent.mkdir(parents=True,exist_ok=True)
        data=archive.read(name);path.write_bytes(data)
        files.append(dict(path=name,sha256=sha(data),bytes=len(data),offset=entry['offset'],packed=entry.get('packed',0)))
    if not files:raise ValueError('No source members matched the requested world')
    # Reconstruct from all extracted files and original header/padding. Byte
    # identity is a container preservation test, not an edited world export.
    preservation=dict(sha256=source_hash,xboxReloadTested=False)
    if member_prefix is None:
        roundtrip=ROOT/'data/world-source'/key/'unchanged-rebuilt.big'
        rebuilt_path=roundtrip.with_suffix('.big.tmp')
        progress(key,'Reconstructing the unchanged archive from preserved members…')
        with rebuilt_path.open('wb') as rebuilt:
            last=0
            for entry in sorted(files,key=lambda e:e['offset']):
                if entry['packed']:raise ValueError('Unchanged rebuild currently requires stored archive entries')
                if entry['offset']<last:raise ValueError('Overlapping archive entries require a different reconstruction policy')
                rebuilt.write(archive.data[last:entry['offset']]);payload=(preserved/entry['path']).read_bytes();rebuilt.write(payload)
                last=entry['offset']+len(payload)
            rebuilt.write(archive.data[last:])
        if file_sha(rebuilt_path)!=source_hash:raise ValueError('Unchanged archive reconstruction mismatch')
        rebuilt_path.replace(roundtrip)
        preservation['archiveReconstruction']='byte-identical'
    else:
        for entry in files:
            if (preserved/entry['path']).read_bytes()!=archive.read(entry['path']):
                raise ValueError('Selected member preservation mismatch')
        preservation.update(archiveReconstruction='not-attempted-subset',
                            selectedMembers='byte-identical',memberPrefix=member_prefix,
                            selectedMemberCount=len(files),archiveMemberCount=len(archive.entries))
    archive.data.close()
    streams=sorted(p for p in preserved.rglob('*.xst') if not p.name.startswith('.'))
    manifest=dict(format='nativex-level-source',version=1,id=key,name=label,
                  gameBuild=game_build,units='metres',up='Y',
                  sourceArchive=Path(source).name,sourceSha256=source_hash,sourceFiles=files,
                  preservation=preservation,
                  sections=[],textures={},resources=[],warnings=[],unsupported=[])
    all_assets={};occurrences={};expected=0
    for table in streams:
        stream=table.stem.rsplit('_',1)[1];records=read_atoc(table);expected+=len(records);seen=set()
        progress(key,f'Reconstructing {stream} resources from original streams…')
        for path in sorted(table.parent.glob('c'+stream+'_*.xsf')):
            for asset in read_sfil(path,records,require_all_records=False):
                aid=f'{asset.record.asset_id:016x}';seen.add(aid)
                previous=all_assets.get(aid)
                digest=sha(asset.data)
                if previous and previous['sha256']!=digest:raise ValueError('Conflicting stream asset copies')
                if not previous:
                    raw_path=ROOT/'data/world-source'/key/'rx2'/f'{aid}.rx2'
                    raw_path.parent.mkdir(exist_ok=True);raw_path.write_bytes(asset.data)
                    all_assets[aid]=dict(type=asset.record.asset_type,sha256=digest,bytes=len(asset.data))
                occurrences.setdefault(aid,[]).append(path.name)
        missing={f'{r.asset_id:016x}' for r in records}-seen
        if missing:raise ValueError('Missing stream records: '+', '.join(sorted(missing)))
    cells={}
    def cell_for(asset_id):
        names=occurrences[asset_id]
        matches=[re.fullmatch(r'c(?:pres|sim)_(-?\d+)_(-?\d+)_high\.xsf',n) for n in names]
        keys={f'{m[1]}_{m[2]}' for m in matches if m}
        if len(keys)==1:cell=next(iter(keys))
        elif not keys and any(n in ('cpres_global.xsf','csim_global.xsf') for n in names):cell='global'
        else:raise ValueError('Asset does not have one supported source cell')
        return cells.setdefault(cell,dict(id=cell,label='World section '+cell,models=[],simulation=[],rails=[],collision=[],
                                         sourceStreams=[],bounds=None))
    texture_jobs=[]
    for index,(aid,record) in enumerate(all_assets.items()):
        if index%50==0:progress(key,f'Decoding native resources · {index} / {len(all_assets)}',index,len(all_assets))
        raw_path=ROOT/'data/world-source'/key/'rx2'/f'{aid}.rx2'
        data=raw_path.read_bytes();arena=Arena(data)
        resource=dict(id=aid,type=record['type'],sha256=record['sha256'],bytes=record['bytes'],
                      streams=occurrences[aid],sections=[dict(type=f'{s["type"]:08x}',bytes=s['size']) for s in arena.sections])
        manifest['resources'].append(resource)
        if record['type']==0x1000:
            texture_jobs.append((key,aid,record['sha256']))
        elif arena.indices(0xeb0001):
            try:
                native=native_instances(data, 'render') if native_placements else [identity_instances(data)]
                decoded=material_enricher(data,geometry(data))
                if native_placements:decoded=render_instances(data,decoded)
                cell=cell_for(aid)
                write_json(bundle/'models'/f'{aid}.nxdata',decoded)
                cell['models'].append(dict(id=aid,url=f'/worlds/{key}/models/{aid}.nxdata',bounds=decoded['bounds'],
                                          vertices=decoded['vertices'],triangles=decoded['triangles'],meshes=len(decoded['groups']),
                                          sourceInstance=native[0],nativeInstances=native,sourceSha256=record['sha256'],
                                          diffuseTextures=sorted({c['guid'] for g in decoded['groups'] for c in g['material']['channels'] if c['role']=='diffuse'})))
                cell['sourceStreams']+=occurrences[aid]
            except ValueError as e:manifest['unsupported'].append(dict(resource=aid,component='geometry',reason=str(e)))
        elif arena.indices(0x80006) or arena.indices(0xeb0004):
            try:
                cell=cell_for(aid)
                if arena.indices(0x80006) and not native_placements:identity_instances(data,'collision')
                collision=collision_instances(data) if native_placements and arena.indices(0x80006) else decode_rx2_clustered_meshes(data)
                rails=decode_grind_splines(data)
                positions=[];surfaces=[]
                for mesh in collision:
                    for tri in mesh.triangles:
                        positions.extend([v for p in (tri.a,tri.b,tri.c) for v in p]);surfaces.append(tri.surface)
                rail_lines=[]
                for rail in rails:
                    points=[]
                    for payload in rail['native_segment_payloads']:
                        v=struct.unpack('>30f',bytes.fromhex(payload))
                        for j in range(9):
                            t=j/8;points.extend(v[12+i]+v[8+i]*t+v[4+i]*t*t+v[i]*t*t*t for i in range(3))
                    rail_lines.append(dict(id=rail['spline_id'],points=points,segments=rail['segment_count']))
                write_json(bundle/'collision'/f'{aid}.nxdata',dict(positions=positions,surfaces=surfaces,rails=rail_lines))
                # Exact cubic payloads and all source bytes stay in the research
                # cache, independent of the tessellated viewport lines.
                write_json(ROOT/'data/world-source'/key/'rails'/f'{aid}.json',rails)
                cell['simulation'].append(aid)
                bounds=([[min(m.bounds_min[i] for m in collision) for i in range(3)],[max(m.bounds_max[i] for m in collision) for i in range(3)]]
                        if collision else [[min(v for r in rail_lines for v in r['points'][i::3]) for i in range(3)],
                                           [max(v for r in rail_lines for v in r['points'][i::3]) for i in range(3)]])
                cell['collision'].append(dict(id=aid,url=f'/worlds/{key}/collision/{aid}.nxdata',triangles=len(surfaces),
                                              meshes=len(collision),surfaceIds=sorted(set(surfaces)),bounds=bounds))
                cell['rails'].append(dict(resource=aid,count=len(rails),segments=sum(r['segment_count'] for r in rails)))
                cell['sourceStreams']+=occurrences[aid]
            except ValueError as e:manifest['unsupported'].append(dict(resource=aid,component='collision',reason=str(e)))
    (bundle/'textures').mkdir(exist_ok=True)
    progress(key,f'Decoding {len(texture_jobs)} texture resources locally…',0,len(texture_jobs))
    with ProcessPoolExecutor(max_workers=3) as workers:
        for index,(meta,error) in enumerate(workers.map(decode_texture_file,texture_jobs)):
            if error:manifest['unsupported'].append(error)
            else:
                old=manifest['textures'].get(meta['id'])
                if old is None or meta['width']*meta['height']>old['width']*old['height']:manifest['textures'][meta['id']]=meta
            if index%25==0:progress(key,f'Decoding textures · {index+1} / {len(texture_jobs)}',index+1,len(texture_jobs))
    for cell in cells.values():
        if not cell['models']:continue
        cell['bounds']=[[min(m['bounds'][0][i] for m in cell['models']) for i in range(3)],
                        [max(m['bounds'][1][i] for m in cell['models']) for i in range(3)]]
        cell['sourceStreams']=sorted(set(cell['sourceStreams']))
        cell['pivot']=[(cell['bounds'][0][0]+cell['bounds'][1][0])/2,0,(cell['bounds'][0][2]+cell['bounds'][1][2])/2]
        cell['editUnit']='baked world section; render/collision/grinds move together in preview'
        manifest['sections'].append(cell)
    models=[m for c in manifest['sections'] for m in c['models']]
    manifest['importStatus']='ready-preview' if models and not any(x['component']=='geometry' for x in manifest['unsupported']) else 'unsupported-or-partial'
    missing=sorted({t for m in models for t in m['diffuseTextures']}-set(manifest['textures']))
    if missing:manifest['importStatus']='unsupported-or-partial'
    manifest['summary']=dict(streamRecords=expected,uniqueResources=len(all_assets),worldSections=len(manifest['sections']),models=len(models),
                             meshes=sum(m['meshes'] for m in models),vertices=sum(m['vertices'] for m in models),
                             triangles=sum(m['triangles'] for m in models),textures=len(manifest['textures']),
                             missingDiffuseTextures=missing,collisionTriangles=sum(c['triangles'] for s in manifest['sections'] for c in s['collision']),
                             collisionMeshes=sum(c['meshes'] for s in manifest['sections'] for c in s['collision']),
                             grindRails=sum(r['count'] for s in manifest['sections'] for r in s['rails']),
                             grindSegments=sum(r['segments'] for s in manifest['sections'] for r in s['rails']))
    manifest['warnings']=['Editor lighting approximates the game; shader layering and reflections are not reproduced.',
                          'Baked world sections are the current edit unit. Section seams are not automatically repaired.',
                          'Grinds may cross section boundaries. Their source stream ownership is preserved; cross-section continuity is not rebuilt.',
                          'AI routes, triggers, streaming bounds and spawn data are preserved but not regenerated.',
                          'Native Xbox world export is unavailable until those structures have a validated writer and game reload test.']
    if models:manifest['bounds']=[[min(m['bounds'][0][i] for m in models) for i in range(3)],[max(m['bounds'][1][i] for m in models) for i in range(3)]]
    write_json(bundle/'manifest.json',manifest)
    write_json(bundle/'manifest.nxdata',manifest)
    progress(key,'Local world import complete.',state='complete')
    print(json.dumps(manifest['summary'],indent=2))
    return manifest

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('archive');parser.add_argument('--key',required=True);parser.add_argument('--name',required=True)
    args=parser.parse_args()
    try:import_world(args.archive,args.key,args.name)
    except Exception as e:
        if re.fullmatch(r'[a-z0-9-]+',args.key):progress(args.key,str(e),state='failed')
        raise
