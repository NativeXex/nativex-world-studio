"""Build → native reimport → observed walk → guarded Xbox install/restore."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading
import uuid

from .catalog import ROOT
from .skate3 import section_export
from .skate3.world_probe import SOURCE_SHA256, sha
from .skate3.world_probe_xbox import Console, LIVE, require_aurora
from .skate3.park_generation_xbox import KNOWN
from .skate3.world import write_json
from . import walktests

EXPORTS = ROOT/'data/level-exports'
BUILDS = ROOT/'data/level-builds'
LOCK = threading.Lock()
REMOTE = r'Hdd:\Apps\NativeXWorldStudio\SectionTests'


def identity(plan):
    return sha(json.dumps(plan, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


def folder(build_id):
    if not isinstance(build_id, str) or not re.fullmatch(r'[0-9a-f]{64}', build_id):
        raise ValueError('Invalid map build identity')
    return BUILDS/build_id


def read(build_id):
    result = json.loads((folder(build_id)/'build.json').read_text())
    report = result['report']
    if report['planSha256'] != build_id or identity(report['plan']) != build_id:
        raise ValueError('Map build plan identity changed')
    if (report.get('format') != 'nativex-section-export' or report.get('version') != 1 or
            not re.fullmatch(r'blackbox-sections-[0-9a-f]{16}\.big', report.get('file', '')) or
            report.get('originalBackupSha256') != SOURCE_SHA256):
        raise ValueError('Invalid native section build report')
    if sha((EXPORTS/report['file']).read_bytes()) != report['outputSha256']:
        raise ValueError('Built map changed; rebuild before installation')
    return result


def observations(result):
    matches = []
    for path in (ROOT/'data/collision-tests'/result['walkTest']['world']).glob('*.walk.json'):
        if path.name.startswith('.'):
            continue
        r = json.loads(path.read_text())
        s, m = r.get('source', {}), r.get('metrics', {})
        if (s.get('kind') == 'reopened-skate3-export' and not s.get('subset') and
                s.get('archiveSha256') == result['report']['outputSha256'] and
                not s.get('unsupportedCollision') and m.get('distance', 0) > .5 and
                m.get('seconds', 0) > 0 and m.get('contacts', 0) > 0 and m.get('visitedTriangles', 0) > 0):
            matches.append(str(path))
    return matches


def has_unverified_copy(plan):
    return any(item.get('origin')=='copy' for item in plan.get('instances', []))

def status(build_id):
    result = read(build_id)
    walked = observations(result)
    receipt = folder(build_id)/'deployment.json'
    runtime_path = folder(build_id)/'runtime.json'
    runtime = json.loads(runtime_path.read_text()) if runtime_path.exists() else None
    failed = bool(runtime and runtime.get('result') == 'failed')
    unsupported_copy=has_unverified_copy(result['report']['plan'])
    return dict(**result, buildId=build_id, walkReports=walked, readyToInstall=bool(walked) and not failed and not unsupported_copy,
                deployment=json.loads(receipt.read_text()) if receipt.exists() else None,
                runtime=runtime, blockedByRuntimeFailure=bool(failed),
                unsupportedCopy=unsupported_copy,
                nextStep='Section duplication has unresolved native collision. Installation is disabled; local preview is not Xbox validation.' if unsupported_copy else
                         'Xbox gameplay failed. Restore the previous map; this build cannot be installed again.' if failed else
                         'Quit Skate 3 to Aurora, then install the test map.' if walked else
                         'Open the exported walk, walk a route, and save its report.')


def build(plan):
    plan = json.loads(json.dumps(plan, allow_nan=False))
    build_id = identity(plan)
    with LOCK:
        if (folder(build_id)/'build.json').exists():
            return status(build_id)
        report = section_export.build(plan, EXPORTS)
        walk = walktests.reopen_export(report, EXPORTS/report['file'])
        result = dict(report=report, walkTest=walk, path=str(EXPORTS/report['file']),
                      download='/api/level-exports/'+report['file'])
        write_json(folder(build_id)/'build.json', result)
    return status(build_id)


def artifact(name):
    if not re.fullmatch(r'blackbox-sections-[0-9a-f]{16}\.big', name):
        raise ValueError('Invalid native section archive name')
    return (EXPORTS/name).read_bytes()


def journal(build_id, event, **fields):
    path = folder(build_id)/'deployment.json'
    receipt = json.loads(path.read_text()) if path.exists() else dict(livePath=LIVE, events=[])
    receipt['events'].append(dict(at=datetime.now(timezone.utc).isoformat(), event=event, **fields))
    write_json(path, receipt)


def known_hashes():
    result = set(KNOWN)
    for path in BUILDS.glob('*/deployment.json'):
        for event in json.loads(path.read_text()).get('events', []):
            if event['event'] == 'activated-and-byte-verified':
                result.add(event['sha256'])
    return result


def ensure_directories(console):
    parent = r'Hdd:\Apps'
    for name in ('NativeXWorldStudio', 'SectionTests'):
        entries = console.entries(parent)
        path = parent+'\\'+name
        if name.lower() in entries:
            if ' directory' not in entries[name.lower()]:
                raise ValueError('Backup path is not a directory')
        elif not console.command(f'mkdir name="{path}"').startswith('200-'):
            raise RuntimeError('Cannot create the native map backup directory')
        parent = path


def install(build_id, plan, host, *, restore=False, console=None):
    if not restore and has_unverified_copy(read(build_id)['report']['plan']):
        raise ValueError('Section duplication collision is unresolved. Installation is disabled for copied sections.')
    with LOCK:
        result = read(build_id)
        if restore not in (False, True, 'previous'):
            raise ValueError('Unknown map recovery mode')
        if not restore:
            runtime_path = folder(build_id)/'runtime.json'
            if runtime_path.exists() and json.loads(runtime_path.read_text()).get('result') == 'failed':
                raise ValueError('This build failed its Xbox gameplay test; rebuild after the native exporter is corrected')
            if identity(plan) != build_id:
                raise ValueError('Layout changed after building; build and walk the current layout first')
            if not observations(result):
                raise ValueError('Walk the reopened native export and save its report before installation')
        # Recheck decoded native collision and the actual archive, not just a UI flag.
        source = walktests.describe(result['walkTest']['world'])
        if source['archiveSha256'] != result['report']['outputSha256'] or source['kind'] != 'reopened-skate3-export':
            raise ValueError('Reopened map evidence changed')
        original = (ROOT/'data/world-source/worldDIST_BlackBoxPark.big').read_bytes()
        if sha(original) != SOURCE_SHA256:
            raise ValueError('Immutable original backup changed')
        wanted = original if restore else (EXPORTS/result['report']['file']).read_bytes()
        if restore == 'previous':
            receipt = json.loads((folder(build_id)/'deployment.json').read_text())
            backup = next((e for e in receipt['events'] if e['event'] == 'backup-verified' and
                           e['beforeSha256'] != result['report']['outputSha256']), None)
            if not backup or backup['beforeSha256'] not in known_hashes():
                raise ValueError('No recognized previous-map backup is available')
            previous_hash = backup['beforeSha256']
            wanted = (folder(build_id)/('before-'+previous_hash+'.big')).read_bytes()
            if sha(wanted) != previous_hash:
                raise ValueError('Previous-map backup changed')
        console = console or Console(host, max_file_size=32*1024*1024)
        try:
            require_aurora(console.command('xbeinfo running'))
        except (TimeoutError, ConnectionError, OSError) as error:
            raise RuntimeError(f'Xbox at {host} is unavailable. Check its connection and IP, then return to Aurora and retry.') from error
        before = console.read(LIVE)
        if sha(before) not in known_hashes() | {result['report']['outputSha256']}:
            raise ValueError('The Xbox map has an unknown hash; no replacement performed')
        transaction = uuid.uuid4().hex[:12]
        previous = REMOTE+'\\before-'+transaction+'.big'
        staged = REMOTE+'\\ready-'+transaction+'.big'
        snapshot = folder(build_id)/('before-'+sha(before)+'.big')
        if snapshot.exists() and snapshot.read_bytes() != before:
            raise ValueError('Local rollback snapshot differs')
        snapshot.write_bytes(before)
        ensure_directories(console)
        console.upload_new(REMOTE+r'\original.big', original)
        if console.read(REMOTE+r'\original.big') != original:
            raise ValueError('Console original backup did not verify')
        if before == wanted:
            journal(build_id, 'activated-and-byte-verified', sha256=sha(wanted), bytes=len(wanted),
                    alreadyActive=True, originalBackup=REMOTE+r'\original.big', restore=restore,
                    xboxRuntimeVerified=False)
            return status(build_id)
        journal(build_id, 'backup-verified', beforeSha256=sha(before), localSnapshot=str(snapshot),
                originalBackup=REMOTE+r'\original.big', originalSha256=SOURCE_SHA256)
        console.upload_new(staged, wanted)
        if console.read(staged) != wanted:
            raise ValueError('Transferred map failed complete byte readback')
        journal(build_id, 'staged-and-byte-verified', staged=staged, sha256=sha(wanted), bytes=len(wanted))
        # Catch both a title launch and an external file replacement during transfer.
        require_aurora(console.command('xbeinfo running'))
        if console.read(LIVE) != before:
            raise ValueError('Live map changed during transfer; no replacement performed')
        journal(build_id, 'activation-starting', rollbackPath=previous, staged=staged,
                beforeSha256=sha(before), wantedSha256=sha(wanted), restore=restore)
        try:
            console.rename(LIVE, previous)
            if console.read(previous) != before:
                raise RuntimeError('Preserved previous map did not verify')
            console.rename(staged, LIVE)
            if console.read(LIVE) != wanted:
                raise RuntimeError('Installed map failed complete byte readback')
        except Exception as error:
            journal(build_id, 'activation-error', message=str(error), rollbackPath=previous)
            # Only recover a demonstrably known state; a network failure leaves
            # both the journal and immutable original available for recovery.
            try:
                require_aurora(console.command('xbeinfo running'))
                if console.exists(previous) and console.read(previous) == before:
                    if console.exists(LIVE):
                        failed = REMOTE+'\\failed-'+transaction+'.big'
                        console.rename(LIVE, failed)
                    console.rename(previous, LIVE)
                    if console.read(LIVE) != before:
                        raise RuntimeError('Rollback readback failed')
                    journal(build_id, 'rolled-back-and-byte-verified', sha256=sha(before))
            except Exception as recovery:
                journal(build_id, 'recovery-required', message=str(recovery), rollbackPath=previous)
            raise
        journal(build_id, 'activated-and-byte-verified', sha256=sha(wanted), bytes=len(wanted),
                rollbackPath=previous, originalBackup=REMOTE+r'\original.big', restore=restore,
                xboxRuntimeVerified=False)
    return status(build_id)
