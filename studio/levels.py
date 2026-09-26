"""Validated, versioned local level plans. No Xbox output path is implied."""
import json, math, re, time, threading
from .catalog import ROOT

LOCK=threading.Lock()

def source_for(key):
    if not isinstance(key,str) or not re.fullmatch(r'[a-z0-9-]+',key):raise ValueError('Invalid world reference')
    return json.loads((ROOT/'web/worlds'/key/'manifest.json').read_text())

def validate(p):
    if not isinstance(p,dict) or p.get('format')!='nativex-level-plan' or p.get('version')!=1:raise ValueError('Unsupported level plan')
    if not isinstance(p.get('id'),str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,100}',p['id']):raise ValueError('Invalid level plan identity')
    if not isinstance(p.get('name'),str) or len(p['name'])>200:raise ValueError('Invalid level name')
    source=source_for(p.get('sourceId'))
    if p.get('sourceSha256')!=source['sourceSha256'] or p.get('gameBuild')!=source['gameBuild']:raise ValueError('Level source hash/build mismatch')
    if not isinstance(p.get('generationHistory'),list) or len(p['generationHistory'])>1000:raise ValueError('Invalid generation history')
    objects=p.get('instances');seen=set();sections={s['id'] for s in source['sections']}
    if not isinstance(objects,list) or len(objects)>2048:raise ValueError('Level plan section limit: 2048')
    for o in objects:
        if not isinstance(o,dict) or not isinstance(o.get('id'),str) or o['id'] in seen:raise ValueError('Invalid or duplicate section identity')
        seen.add(o['id'])
        if o.get('sectionId') not in sections:raise ValueError('Unknown native world section')
        pos=o.get('position')
        if not isinstance(pos,list) or len(pos)!=3 or not all(type(v) in (int,float) and math.isfinite(v) and abs(v)<100000 for v in pos):raise ValueError('Invalid world transform')
        yaw=o.get('yaw')
        if type(yaw) not in (int,float) or not math.isfinite(yaw) or yaw%15:raise ValueError('World rotation must use 15-degree steps')
        if type(o.get('locked')) is not bool or type(o.get('visible')) is not bool or o.get('origin') not in ('original','copy'):raise ValueError('Invalid section state')
    return p

def save(p):
    validate(p)
    with LOCK:
        folder=ROOT/'data/level-projects';history=folder/p['id'];history.mkdir(parents=True,exist_ok=True)
        latest=folder/f'{p["id"]}.nxlevel.json'
        revision=(json.loads(latest.read_text()).get('revision',0) if latest.exists() else 0)+1
        p=dict(p,revision=revision,savedAt=time.time());body=json.dumps(p,indent=2,allow_nan=False)
        (history/f'{revision:05d}.nxlevel.json').write_text(body)
        tmp=folder/f'{p["id"]}.tmp';tmp.write_text(body);tmp.replace(latest)
        return dict(project=p,path=str(latest))
