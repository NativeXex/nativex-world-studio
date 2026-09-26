"""Guarded deployment of the reviewed three-module seed-37 Black Box test only."""
import argparse
from datetime import datetime, timezone
import json
import uuid

from .world_probe import ROOT, SOURCE_SHA256, sha
from .world_probe_xbox import Console, LIVE, SIZE, require_aurora
from .world_geometry_probe_xbox import OUTPUT_SHA256 as PAD_SHA256, MAGENTA_SHA256

OUTPUT_SHA256 = '9cf174380c205a667222f34fba0d4826b08491f0d74196cb9d55e676c3772753'
FILE = 'blackbox-9cf174380c205a66.big'
LOCAL = ROOT/'data/world-tests/blackbox-generated-20260925'
REMOTE = r'Hdd:\Apps\NativeXWorldStudio\BlackBoxGenerated20260925'
KNOWN = {SOURCE_SHA256, MAGENTA_SHA256, PAD_SHA256, OUTPUT_SHA256}


def journal(event, **fields):
    LOCAL.mkdir(parents=True, exist_ok=True)
    path = LOCAL/'deployment-receipt.json'
    receipt = json.loads(path.read_text()) if path.exists() else dict(livePath=LIVE, events=[])
    item = dict(at=datetime.now(timezone.utc).isoformat(), event=event, **fields)
    receipt['events'].append(item)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(receipt, indent=2)+'\n')
    temp.replace(path)
    print(json.dumps(item), flush=True)


def inputs():
    original = (ROOT/'data/world-source/worldDIST_BlackBoxPark.big').read_bytes()
    generated = (ROOT/'data/park-exports'/FILE).read_bytes()
    if len(original) != SIZE or len(generated) != SIZE or sha(original) != SOURCE_SHA256 or sha(generated) != OUTPUT_SHA256:
        raise ValueError('Only the exact reviewed original and seed-37 archive are admitted')
    return original, generated


def known_live(console):
    data = console.read(LIVE)
    if len(data) != SIZE or sha(data) not in KNOWN:
        raise ValueError('Live archive is unknown; no replacement allowed')
    return data


def stage(console, original, generated):
    before = known_live(console)
    LOCAL.mkdir(parents=True, exist_ok=True)
    snapshot = LOCAL/f'console-before-stage-{sha(before)[:12]}.big'
    if snapshot.exists() and snapshot.read_bytes() != before:
        raise ValueError('Existing local snapshot differs')
    snapshot.write_bytes(before)
    parent = r'Hdd:\Apps'
    for name in ('NativeXWorldStudio', 'BlackBoxGenerated20260925'):
        entries = console.entries(parent)
        path = parent+'\\'+name
        if name.lower() in entries:
            if ' directory' not in entries[name.lower()]:
                raise ValueError('Staging path is not a directory')
        elif not console.command(f'mkdir name="{path}"').startswith('200-'):
            raise ValueError('Cannot create generated-test staging directory')
        parent = path
    for name, data in (('original.big', original), (FILE, generated)):
        console.upload_new(REMOTE+'\\'+name, data)
        journal('staged-and-byte-verified', name=name, sha256=sha(data), bytes=len(data))
    journal('ready-for-activation', currentLiveSha256=sha(before), localSnapshot=str(snapshot))


def activate(console, original, generated, restore=False):
    require_aurora(console.command('xbeinfo running'))
    if console.read(REMOTE+r'\original.big') != original:
        raise ValueError('Verified immutable console original is required')
    before = known_live(console)
    wanted = original if restore else generated
    phase = 'restore' if restore else 'seed-37-three-modules'
    if before == wanted:
        journal('already-active-and-byte-verified', phase=phase, sha256=sha(wanted), gameReloadVerified=False)
        return
    staged = REMOTE+'\\'+('restore-ready.big' if restore else FILE)
    if restore:
        console.upload_new(staged, wanted)
    if console.read(staged) != wanted:
        raise ValueError('Staged archive differs from the reviewed bytes')
    previous = REMOTE+'\\before-'+phase+'-'+uuid.uuid4().hex[:8]+'.big'
    require_aurora(console.command('xbeinfo running'))
    journal('activation-starting', phase=phase, beforeSha256=sha(before), rollbackPath=previous)
    console.rename(LIVE, previous)
    journal('previous-archive-preserved', rollbackPath=previous)
    try:
        console.rename(staged, LIVE)
    except Exception:
        if not console.exists(LIVE):
            console.rename(previous, LIVE)
            if console.read(LIVE) != before:
                raise RuntimeError('Rollback verification failed; immutable original remains available')
            journal('activation-rolled-back', restoredSha256=sha(before))
        raise
    if console.read(LIVE) != wanted:
        raise ValueError('Live verification failed; previous archive preserved at '+previous)
    journal('activated-and-byte-verified', phase=phase, sha256=sha(wanted), rollbackPath=previous,
            gameReloadVerified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('stage', 'activate', 'restore', 'status'))
    parser.add_argument('--host', default=None)
    args = parser.parse_args()
    console = Console(args.host)
    if args.action == 'status':
        print(console.command('xbeinfo running'), flush=True)
        print('Live archive SHA256:', sha(known_live(console)), flush=True)
    else:
        original, generated = inputs()
        if args.action == 'stage':
            stage(console, original, generated)
        else:
            activate(console, original, generated, restore=args.action == 'restore')
