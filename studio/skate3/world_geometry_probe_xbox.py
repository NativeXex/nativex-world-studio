"""Stage, activate or restore the single validated Black Box manual-pad test."""
import argparse
from datetime import datetime, timezone
import json
import uuid

from .world_probe import ROOT, SOURCE_SHA256, sha
from .world_probe_xbox import Console, LIVE, SIZE, require_aurora

LOCAL = ROOT/'data/world-tests/blackbox-geometry-20260925'
REMOTE = r'Hdd:\Apps\NativeXWorldStudio\BlackBoxGeometry20260925'
OUTPUT_SHA256 = 'a88a9ca5e08ab8d5e11d0c235fbd98f8c4ad64aa2bf9b1d189f2645401832a1f'
MAGENTA_SHA256 = '9867030e55c570fd83dfbf3c4e9cf30151abb925e4c1e9b723bb2a9f8aec2890'
KNOWN_LIVE = {SOURCE_SHA256, MAGENTA_SHA256, OUTPUT_SHA256}


def journal(event, **details):
    path = LOCAL/'deployment-receipt.json'
    record = json.loads(path.read_text()) if path.exists() else {'livePath': LIVE, 'events': []}
    item = dict(at=datetime.now(timezone.utc).isoformat(), event=event, **details)
    record['events'].append(item)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(record, indent=2)+'\n')
    tmp.replace(path)
    print(json.dumps(item), flush=True)


def files():
    original = (ROOT/'data/world-source/worldDIST_BlackBoxPark.big').read_bytes()
    edited = (LOCAL/'manual-pad-move.big').read_bytes()
    if len(original) != SIZE or len(edited) != SIZE or sha(original) != SOURCE_SHA256 or sha(edited) != OUTPUT_SHA256:
        raise ValueError('Deployment only admits the reviewed source and exact geometry test')
    return {'original.big': original, 'manual-pad-move.big': edited}


def known_live(console):
    data = console.read(LIVE)
    if len(data) != SIZE or sha(data) not in KNOWN_LIVE:
        raise ValueError('Live park archive is unknown; no replacement allowed')
    return data


def ensure_directory(console):
    parent = r'Hdd:\Apps'
    for name in ('NativeXWorldStudio', 'BlackBoxGeometry20260925'):
        entries = console.entries(parent)
        path = parent+'\\'+name
        if name.lower() in entries:
            if ' directory' not in entries[name.lower()]:
                raise ValueError('Staging path is not a directory')
        elif not console.command(f'mkdir name="{path}"').startswith('200-'):
            raise ValueError('Cannot create isolated geometry-test staging directory')
        parent = path


def stage(console, inputs):
    before = known_live(console)
    snapshot = LOCAL/f'console-before-stage-{sha(before)[:12]}.big'
    if snapshot.exists() and snapshot.read_bytes() != before:
        raise ValueError('Existing console snapshot differs')
    snapshot.write_bytes(before)
    ensure_directory(console)
    for name, data in inputs.items():
        console.upload_new(REMOTE+'\\'+name, data)
        journal('staged-and-byte-verified', name=name, sha256=sha(data), bytes=len(data))
    journal('ready-for-activation', currentLiveSha256=sha(before), localSnapshot=str(snapshot))


def activate(console, inputs, restore=False):
    require_aurora(console.command('xbeinfo running'))
    if console.read(REMOTE+r'\original.big') != inputs['original.big']:
        raise ValueError('Verified immutable console original backup is required')
    before = known_live(console)
    phase = 'restore' if restore else 'manual-pad-move'
    wanted = inputs['original.big'] if restore else inputs['manual-pad-move.big']
    if before == wanted:
        journal('already-active-and-byte-verified', phase=phase, sha256=sha(wanted), gameReloadVerified=False)
        return
    staged = REMOTE+('\\restore-ready.big' if restore else '\\manual-pad-move.big')
    if restore:
        console.upload_new(staged, wanted)
    if console.read(staged) != wanted:
        raise ValueError('Staged archive differs from approved test bytes')
    previous = REMOTE+'\\before-'+phase+'-'+uuid.uuid4().hex[:8]+'.big'
    require_aurora(console.command('xbeinfo running'))
    journal('activation-starting', phase=phase, beforeSha256=sha(before), rollbackPath=previous)
    console.rename(LIVE, previous)
    journal('previous-archive-preserved', phase=phase, rollbackPath=previous)
    try:
        console.rename(staged, LIVE)
    except Exception:
        if not console.exists(LIVE):
            console.rename(previous, LIVE)
            if console.read(LIVE) != before:
                raise RuntimeError('Rollback verification failed; preserved original backup remains available')
            journal('activation-rolled-back', phase=phase, restoredSha256=sha(before))
        raise
    if console.read(LIVE) != wanted:
        raise ValueError('Live readback differs; preserved previous archive: '+previous)
    journal('activated-and-byte-verified', phase=phase, sha256=sha(wanted), rollbackPath=previous,
            gameReloadVerified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('stage', 'activate', 'restore', 'status'))
    parser.add_argument('--host', default=None)
    args = parser.parse_args()
    try:
        console = Console(args.host)
        if args.action == 'status':
            print(console.command('xbeinfo running'), flush=True)
            print('Live archive SHA256:', sha(known_live(console)), flush=True)
        else:
            inputs = files()
            if args.action == 'stage':
                stage(console, inputs)
            else:
                activate(console, inputs, restore=args.action == 'restore')
    except Exception as error:
        journal('error', action=args.action, message=str(error))
        raise
