"""User-selected local game folder. Never writes to the source installation."""
import hashlib
import json
import os
from pathlib import Path
import threading
import uuid
from .catalog import ROOT

LOCK = threading.Lock()
SETTINGS = ROOT/'data/settings.local.json'

def initialize():
    for folder in ['data/source', 'data/decoded', 'data/projects', 'data/exports',
                   'data/world-source', 'data/level-projects', 'data/park-projects',
                   'data/park-exports', 'data/level-exports', 'data/level-builds', 'web/worlds']:
        (ROOT/folder).mkdir(parents=True, exist_ok=True)

def content_folder(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Choose your extracted Skate 3 folder or its data/content folder.')
    folder = Path(value).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError('Game folder is not readable. Mount the drive and choose a folder, not an ISO/GOD file.')
    from .worlds import KNOWN
    names = {row[1].lower() for row in KNOWN.values()} | {'parkassets.big'}
    # Bounded search: only the selected folder and conventional game subfolders.
    choices = [folder]
    for name in ['data', 'content']:
        choices += [p for base in list(choices) for p in base.iterdir()
                    if p.is_dir() and p.name.lower() == name]
    for candidate in choices:
        if any(p.is_file() and p.name.lower() in names for p in candidate.iterdir()):
            return candidate
    raise ValueError('No supported archives found. Select the Skate 3 game folder containing data/content/*.big.')

def configure(value):
    folder = content_folder(value)
    initialize()
    with LOCK:
        temporary = SETTINGS.with_suffix('.tmp')
        temporary.write_text(json.dumps({'gameContent': str(folder)}, indent=2)+'\n')
        temporary.replace(SETTINGS)
    return describe()

def source_directory():
    if not SETTINGS.exists():
        return None
    value = json.loads(SETTINGS.read_text()).get('gameContent')
    return Path(value) if isinstance(value, str) else None

def local_archive(filename):
    folder = source_directory()
    if folder and folder.is_dir():
        for path in folder.iterdir():
            if path.is_file() and path.name.lower() == filename.lower():
                return path
    return None

def describe():
    from .worlds import KNOWN
    folder = source_directory()
    available = [key for key, row in KNOWN.items() if local_archive(row[1])]
    return {'gameContent': str(folder) if folder else None, 'mounted': bool(folder and folder.is_dir()),
            'worlds': available, 'parkAssets': bool(local_archive('parkassets.big')), 'sourceReadOnly': True}

def stage(filename, *, assets=False):
    """Copy one allowlisted archive; full local readback; refuse replacement."""
    from .worlds import KNOWN
    allowed = {'parkassets.big'} if assets else {row[1] for row in KNOWN.values()}
    if filename not in allowed:
        raise ValueError('Unsupported archive name')
    initialize()
    source = local_archive(filename)
    if source is None:
        raise ValueError('Archive not found on the selected drive. Reconnect it or choose another game folder.')
    target = ROOT/('data/source' if assets else 'data/world-source')/filename
    with LOCK:
        before = source.stat()
        temporary = target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            digest = hashlib.sha256()
            with source.open('rb') as inp, temporary.open('xb') as out:
                if inp.read(2) != b'EB':
                    raise ValueError('Expected an extracted Xbox EB archive; ISO/GOD containers are not supported.')
                inp.seek(0)
                while block := inp.read(1024*1024):
                    out.write(block); digest.update(block)
                out.flush(); os.fsync(out.fileno())
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError('Source archive changed during copy; retry from a stable installation.')
            with temporary.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').digest() != digest.digest():
                    raise ValueError('Local copy readback failed')
            if target.exists():
                with target.open('rb') as stream:
                    if hashlib.file_digest(stream, 'sha256').digest() != digest.digest():
                        raise ValueError('A different source archive is already cached; use a separate checkout for a different game build.')
            else:
                temporary.replace(target)
            return target
        finally:
            temporary.unlink(missing_ok=True)
