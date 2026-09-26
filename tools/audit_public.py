"""Reject generated/game/private content from the Git-tracked publication tree."""
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
FORBIDDEN_SUFFIXES={'.big','.rx2','.xst','.xsf','.xex','.iso','.god','.stfs','.bin',
                    '.dump','.dmp','.pdb','.obj','.dll','.exe','.lib','.zip','.7z',
                    '.png','.jpg','.jpeg','.dds','.glb','.gltf','.obj','.fbx','.wav','.mp3'}
ALLOWED_SUFFIXES={'.py','.js','.json','.md','.txt','.html','.css','.h','.yml','.yaml','.command'}
ALLOWED_NAMES={'.gitignore','.gitattributes','LICENSE'}
PATTERNS=[
    (re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})'), 'credential-shaped value'),
    (re.compile(rb'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----'), 'private key'),
    (re.compile(rb'(?:/Users[/][^/\s]+/|/Volumes[/]XBOX360[/]|172[.]20[.]10[.]\d+)'), 'private development path/address'),
]

def main():
    paths=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    paths=[p for p in paths if p]
    if not paths:raise SystemExit('No tracked files; stage the source-only tree before auditing.')
    errors=[];total=0
    for name in paths:
        path=Path(name)
        if (name.startswith(('data/','web/worlds/','node_modules/','build/','dist/')) or
            any(part.startswith('._') or part=='__pycache__' for part in path.parts) or
            path.suffix.lower() in FORBIDDEN_SUFFIXES or
            path.suffix.lower() not in ALLOWED_SUFFIXES and path.name not in ALLOWED_NAMES):
            errors.append(f'{name}: unapproved publication file type/location');continue
        file=ROOT/path
        if file.is_symlink():errors.append(f'{name}: symlinks are not publication inputs');continue
        body=file.read_bytes();total+=len(body)
        try:body.decode('utf-8')
        except UnicodeError:errors.append(f'{name}: non-text content')
        if b'\0' in body:errors.append(f'{name}: binary content')
        if len(body)>2_500_000:errors.append(f'{name}: unexpectedly large source file')
        for pattern,label in PATTERNS:
            if pattern.search(body):errors.append(f'{name}: {label}')
    for required in ['LICENSE','README.md','THIRD_PARTY_NOTICES.md',
                     'web/vendor/THREE-LICENSE.txt','studio/skate3/vendor/LICENSE-SK8-ENGINE.txt',
                     'studio/skate3/vendor/PROVENANCE.json']:
        if required not in paths:errors.append('Missing required notice: '+required)
    if errors:raise SystemExit('\n'.join(errors))
    print(f'PASS: {len(paths)} tracked text files, {total:,} bytes; game/cache/binary/private-content checks and license notices present.')

if __name__=='__main__':main()
