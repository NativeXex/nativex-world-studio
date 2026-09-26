"""Local persistence and export facade for curated native park modules."""
import json
import re
import threading
import time
from .catalog import ROOT
from .skate3 import park_generator as generator
from .skate3.park_inventory import inventory as surface_inventory

LOCK = threading.Lock()
PROJECTS = ROOT/'data/park-projects'
EXPORTS = ROOT/'data/park-exports'


def catalog():
    return dict(**generator.catalog(), original=generator.new_plan(), inspection=surface_inventory())


def inventory():
    return [dict(file=p.name, **{key: json.loads(p.read_text()).get(key) for key in ('name', 'seed', 'revision')})
            for p in sorted(PROJECTS.glob('*.nxpark.json')) if not p.name.startswith('.')]


def read(name):
    if not re.fullmatch(r'[a-zA-Z0-9-]+\.nxpark\.json', name):
        raise ValueError('Invalid park project filename')
    return generator.validate_plan(json.loads((PROJECTS/name).read_text()))


def save(plan):
    validation = generator.validate_layout(plan)
    with LOCK:
        folder = PROJECTS/plan['id']
        folder.mkdir(parents=True, exist_ok=True)
        latest = PROJECTS/f"{plan['id']}.nxpark.json"
        revision = (json.loads(latest.read_text()).get('revision', 0) if latest.exists() else 0)+1
        result = dict(plan, revision=revision, savedAt=time.time())
        body = json.dumps(result, indent=2, allow_nan=False)+'\n'
        (folder/f'{revision:05d}.nxpark.json').write_text(body)
        temporary = latest.with_suffix('.tmp')
        temporary.write_text(body)
        temporary.replace(latest)
    return dict(plan=result, validation=validation, path=str(latest))


def export(plan):
    with LOCK:
        report = generator.build(plan, EXPORTS)
        from .walktests import reopen_export
        walk_test = reopen_export(report, EXPORTS/report['file'])
    return dict(report=report, walkTest=walk_test, path=str(EXPORTS/report['file']),
                download='/api/park-exports/'+report['file'],
                reportUrl='/api/park-exports/'+report['file'].replace('.big', '.report.json'))


def artifact(name):
    if not re.fullmatch(r'blackbox-[0-9a-f]{16}\.(big|report\.json)', name):
        raise ValueError('Invalid native park export filename')
    return (EXPORTS/name).read_bytes()
