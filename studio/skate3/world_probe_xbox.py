"""Guarded deployment/restore for the one Black Box world experiment.

Stage only adds files under Apps. Activation requires Aurora to be running,
verified source bytes, a verified backup, and a known current archive hash.
No game launching, executable patches, DLC changes or runtime writes.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import struct
import uuid

from .world_probe import ROOT, SOURCE_SHA256
from .xbox import XBDM, xbox_content_path

LOCAL = ROOT / 'data/world-tests/blackbox-20260924'
REMOTE = r'Hdd:\Apps\NativeXWorldStudio\BlackBoxTest20260924'
LIVE = xbox_content_path() + r'\worldDIST_BlackBoxPark.big'
SIZE = 5339184


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require_aurora(reply):
    match = re.search(r'name="([^"]+)"', reply)
    if not reply.startswith('202-') or not match or match[1].split('\\')[-1].lower() != 'aurora.xex':
        raise RuntimeError('Quit Skate 3 to Aurora before replacing its world archive')


class Console:
    def __init__(self, host, max_file_size=SIZE):
        self.host = host
        self.max_file_size = max_file_size

    def command(self, command):
        x = XBDM(self.host)
        try:
            return x.command(command)
        finally:
            x.close()

    def entries(self, directory):
        reply = self.command(f'dirlist name="{directory}"')
        if not reply.startswith('202-'):
            raise RuntimeError('Cannot list console directory: ' + directory + ': ' + reply)
        return {m[1].lower(): line for line in reply.splitlines()
                if (m := re.search(r'name="([^"]+)"', line))}

    def exists(self, path):
        parent, name = path.rsplit('\\', 1)
        return name.lower() in self.entries(parent)

    def read(self, path):
        x = XBDM(self.host)
        x.sock.settimeout(30)
        try:
            x.sock.sendall(f'getfile name="{path}"\r\n'.encode('ascii'))
            reply = x.line()
            if not reply.startswith(b'203-'):
                raise RuntimeError('Read failed: ' + path + ': ' + repr(reply))
            size = struct.unpack('<I', x.exact(4))[0]
            if size > self.max_file_size:
                raise RuntimeError('Unexpected remote file size')
            return x.exact(size)
        finally:
            x.close()

    def ensure_directory(self):
        parent = r'Hdd:\Apps'
        for name in ['NativeXWorldStudio', 'BlackBoxTest20260924']:
            entries = self.entries(parent)
            path = parent + '\\' + name
            if name.lower() in entries:
                if ' directory' not in entries[name.lower()]:
                    raise RuntimeError('Remote path is not a directory')
            else:
                reply = self.command(f'mkdir name="{path}"')
                if not reply.startswith('200-'):
                    raise RuntimeError('mkdir failed: ' + reply)
            parent = path

    def upload_new(self, path, data):
        if self.exists(path):
            if self.read(path) != data:
                raise RuntimeError('Refusing to overwrite different staged file: ' + path)
            return
        x = XBDM(self.host)
        x.sock.settimeout(30)
        try:
            x.sock.sendall(f'sendfile name="{path}" length=0x{len(data):x}\r\n'.encode('ascii'))
            reply = x.line()
            if not reply.startswith(b'204-'):
                raise RuntimeError('Upload refused: ' + repr(reply))
            for at in range(0, len(data), 65536):
                x.sock.sendall(data[at:at+65536])
            reply = x.line()
            if not reply.startswith(b'200-'):
                raise RuntimeError('Upload incomplete: ' + repr(reply))
        finally:
            x.close()
        if self.read(path) != data:
            raise RuntimeError('Staged readback failed: ' + path)

    def rename(self, source, destination):
        if self.exists(destination):
            raise RuntimeError('Refusing to overwrite rename destination: ' + destination)
        reply = self.command(f'rename name="{source}" newname="{destination}"')
        if not reply.startswith('200-'):
            raise RuntimeError('Rename failed: ' + reply)


def journal(event, **details):
    path = LOCAL / 'deployment-receipt.json'
    receipt = json.loads(path.read_text()) if path.exists() else {'events': [], 'livePath': LIVE}
    receipt['events'].append(dict(at=datetime.datetime.now(datetime.timezone.utc).isoformat(), event=event, **details))
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(receipt, indent=2) + '\n')
    tmp.replace(path)
    print(json.dumps(receipt['events'][-1]), flush=True)


def local_files():
    report = json.loads((LOCAL/'build-report.json').read_text())
    if report['sourceSha256'] != SOURCE_SHA256 or report['archiveBytes'] != SIZE:
        raise RuntimeError('Invalid build report')
    result = {}
    for name, expected in [('xbox-original.big', SOURCE_SHA256), ('unchanged.big', SOURCE_SHA256),
                           ('magenta-floor.big', report['outputSha256'])]:
        data = (LOCAL/name).read_bytes()
        if len(data) != SIZE or sha(data) != expected:
            raise RuntimeError('Local input hash mismatch: ' + name)
        result[name] = data
    original, changed = result['xbox-original.big'], result['magenta-floor.big']
    start, end = report['allowedByteRange']
    if (start, end) != (1188664, 1350407) or original[:start] != changed[:start] or original[end:] != changed[end:]:
        raise RuntimeError('Changes extend outside the admitted texture payload')
    return result


def stage(console, files):
    if sha(console.read(LIVE)) != SOURCE_SHA256:
        raise RuntimeError('Live archive differs from the original; no staging performed')
    console.ensure_directory()
    for name, data in files.items():
        console.upload_new(REMOTE+'\\'+name, data)
        journal('staged-and-verified', name=name, sha256=sha(data), bytes=len(data))


def activate(console, files, phase):
    require_aurora(console.command('xbeinfo running'))
    original = files['xbox-original.big']
    if console.read(REMOTE+r'\xbox-original.big') != original:
        raise RuntimeError('Verified console backup is required')
    before = console.read(LIVE)
    allowed = {SOURCE_SHA256} if phase != 'restore' else {SOURCE_SHA256, sha(files['magenta-floor.big'])}
    if sha(before) not in allowed:
        raise RuntimeError('Live archive is not a recognised preimage; no replacement performed')
    name = {'unchanged': 'unchanged.big', 'magenta': 'magenta-floor.big', 'restore': 'restore-ready.big'}[phase]
    wanted = original if phase == 'restore' else files[name]
    staged = REMOTE+'\\'+name
    if phase == 'restore':
        console.upload_new(staged, wanted)
    if console.read(staged) != wanted:
        raise RuntimeError('Staged archive verification failed')
    previous = REMOTE + '\\before-' + phase + '-' + uuid.uuid4().hex[:8] + '.big'
    require_aurora(console.command('xbeinfo running'))
    journal('activation-starting', phase=phase, staged=staged, rollbackPath=previous, beforeSha256=sha(before))
    console.rename(LIVE, previous)
    journal('previous-archive-preserved', phase=phase, rollbackPath=previous)
    try:
        console.rename(staged, LIVE)
    except Exception:
        # Recover only if the target is demonstrably absent. An ambiguous network
        # result never permits overwriting a file whose state is unknown.
        if not console.exists(LIVE):
            console.rename(previous, LIVE)
            if console.read(LIVE) != before:
                raise RuntimeError('Rollback verification failed')
            journal('activation-rolled-back', phase=phase)
        raise
    if console.read(LIVE) != wanted:
        raise RuntimeError('Live archive verification failed; preserved backup remains at ' + previous)
    journal('activated-and-byte-verified', phase=phase, sha256=sha(wanted), rollbackPath=previous,
            gameReloadVerified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['stage', 'unchanged', 'magenta', 'restore'])
    parser.add_argument('--host', default=None)
    args = parser.parse_args()
    files = local_files()
    console = Console(args.host)
    try:
        if args.action == 'stage':
            stage(console, files)
        else:
            activate(console, files, args.action)
    except Exception as error:
        journal('error', action=args.action, message=str(error))
        raise
