"""Offline world inventory. Merely browsing never contacts the console."""
import json, subprocess, sys, threading, time, os
from .catalog import ROOT

# Retail archive names verified in this console's content directory. A listing
# is not evidence that its render data is supported by our importer.
KNOWN = {
    'university': ('University District', 'worldDIST_University.big', 'district'),
    'blackbox': ('Black Box Park', 'worldDIST_BlackBoxPark.big', 'park'),
    'downtown': ('Downtown District', 'worldDIST_DownTown.big', 'district'),
    'industrial': ('Industrial District', 'worldDIST_Industrial.big', 'district'),
    'skate-school': ('Skate School', 'worldDIST_SkateSchool.big', 'park'),
    'mega-park': ('Mega Park', 'worldDIST_MegaPark.big', 'overlay'),
    'downtown-park': ('Downtown Skate Park', 'worldDIST_DownTownSkatePark.big', 'park'),
    'industrial-park': ('Industrial Skate Park', 'worldDIST_IndustrialSkatePark.big', 'park'),
    'start-park': ('Start Park', 'worldDIST_StartPark.big', 'park'),
    'maloof': ('Maloof Money Cup', 'worldDIST_MaloofMoneyCup.big', 'park'),
}

JOB_LOCK=threading.Lock()
ACTIVE_JOB=None

def running(job):
    if job.get('state')!='running':return False
    pid=job.get('pid')
    if not isinstance(pid,int):return time.time()-job.get('updatedAt',0)<600
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False
    except PermissionError:return True

def collection_active(part,root=ROOT):
    key=next((k for k,v in KNOWN.items() if part.name==v[1]+'.part'),None)
    progress=root/'data/world-source'/str(key)/'import-progress.json'
    if progress.exists():
        job=json.loads(progress.read_text())
        if job.get('state')=='failed' or job.get('state')=='running' and not running(job):return False
    return time.time()-part.stat().st_mtime<120

def prepare(key,host):
    """Only user-triggered calls start a job; inventory stays strictly offline."""
    global ACTIVE_JOB
    if key not in KNOWN:raise ValueError('Unknown local world identity')
    if KNOWN[key][2]=='overlay':raise ValueError('Mega Park needs a composed University base; standalone import is unavailable.')
    with JOB_LOCK:
        if ACTIVE_JOB is not None and ACTIVE_JOB.poll() is None:raise ValueError('A world is already being prepared. Let it finish first.')
        for file in (ROOT/'data/world-source').glob('*/import-progress.json'):
            if not file.parent.name.startswith('.') and running(json.loads(file.read_text())):
                raise ValueError('A local world import is already running. Let it finish first.')
        for part in (ROOT/'data/world-source').glob('*.big.part'):
            if not part.name.startswith('.') and collection_active(part):
                raise ValueError('An Xbox archive collection is already running. Let it finish first.')
        own_part=(ROOT/'data/world-source'/KNOWN[key][1]).with_suffix('.big.part')
        if own_part.exists():own_part.rename(own_part.with_name(own_part.name+f'.interrupted-{int(time.time())}'))
        from .skate3.world import progress, write_json
        progress(key,'Starting local world preparation…')
        log=ROOT/'data/world-source'/key/'import.log'
        try:
            with log.open('ab') as output:
                command=[sys.executable,'-u','-m','studio.skate3.world_job',key]
                if host:command += ['--xbox',host]
                ACTIVE_JOB=subprocess.Popen(command,cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
            write_json(log.with_name('import-progress.json'),dict(state='running',message='Starting local world preparation…',current=0,total=0,updatedAt=time.time(),pid=ACTIVE_JOB.pid))
        except OSError as e:progress(key,str(e),state='failed');raise
        return dict(id=key,state='running')

def inventory(root=ROOT):
    known=dict(KNOWN)
    for p in (root/'web/worlds').glob('*/manifest.json'):
        if p.parent.name.startswith('.'):continue
        if p.parent.name not in known:
            m=json.loads(p.read_text());known[m['id']]=(m['name'],m['sourceArchive'],'world')
    result=[]
    for key,(name,archive,kind) in known.items():
        raw=root/'data/world-source'/archive
        part=raw.with_suffix('.big.part')
        file=root/'web/worlds'/key/'manifest.json'
        from .library import local_archive
        local=local_archive(archive) if root==ROOT else None
        item=dict(id=key,name=name,kind=kind,archive=archive,availableOnDrive=bool(local),archiveBytes=raw.stat().st_size if raw.exists() else 0,
                  collected=raw.exists(),canOpen=False,status='not-collected',summary={},issues=[],bounds=None)
        if raw.exists():item.update(status='collected',detail='Archive stored locally. It needs decoding before it can open.')
        else:item['detail']='Available on your selected drive. Import a local copy to begin.' if local else 'Connect your game folder to import this archive.'
        if part.exists():item.update(status='collecting',receivedBytes=part.stat().st_size,detail='Copying the original archive from Xbox. Opening is available after import completes.')
        collection=root/'data/world-source'/key/'collection.json'
        if collection.exists():
            receipt=json.loads(collection.read_text());item['expectedBytes']=receipt.get('expectedBytes');item['collectionStartedAt']=receipt.get('startedAt')
        if kind=='overlay':item['detail']='An overlay, not a standalone world. Mega Park also needs University base geometry.'
        if file.exists():
            try:
                m=json.loads(file.read_text());summary=m.get('summary',{});sections=m.get('sections',[])
                issues=m.get('unsupported',[])
                ready=bool(sections) and m.get('importStatus')=='ready-preview' and not summary.get('missingDiffuseTextures')
                item.update(status='ready' if ready else 'partial',canOpen=bool(sections),summary=summary,
                            sectionCount=len(sections),issues=issues,bounds=m.get('bounds'),sourceSha256=m['sourceSha256'],
                            detail='Local geometry and textures are ready to browse.' if ready else 'Partial import: some native data is not yet supported.',
                            manifest=f'/worlds/{key}/manifest.nxdata')
                if m.get('gameBuild','').startswith('skate2'):
                    item['detail']='Skate 2 source preview. Skate 3 runtime compatibility is untested.'
                # A manifest alone is not a usable offline world. Optional
                # collision is checked when requested; visible data must exist.
                urls=[model['url'] for section in sections for model in section['models']]
                urls += [t['url'] for t in m.get('textures',{}).values()]
                missing=[];web=(root/'web').resolve()
                for url in urls:
                    path=(web/url.lstrip('/')).resolve()
                    if not path.is_relative_to(web) or not path.is_file():missing.append(url)
                if missing:item.update(status='invalid',canOpen=False,detail=f'{len(missing)} cached render files are missing. Re-import the original local archive.')
            except (ValueError,KeyError):item.update(status='invalid',detail='The cached manifest is incomplete. Re-import the local archive.')
        progress=root/'data/world-source'/key/'import-progress.json'
        if progress.exists():
            job=json.loads(progress.read_text())
            if job.get('state') in ('running','failed'):
                item['job']=job
                if job['state']=='running' and running(job):item.update(status='collecting' if part.exists() else 'importing',detail=job.get('message','Decoding local archive…'))
                elif job['state']=='running' and not item['canOpen']:item.update(status='failed',detail='The previous import stopped. Its original archive is retained; retry to continue.')
                elif not item['canOpen']:item.update(status='failed',detail=job.get('message','Import failed. Original archive retained.'))
        result.append(item)
    return dict(worlds=result,offline=True,sourceDirectory=str(root/'data/world-source'))
