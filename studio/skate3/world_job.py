"""Collect one known retail world read-only, then build its offline cache."""
import argparse, hashlib, struct, time
from pathlib import Path
from .xbox import XBDM, xbox_content_path
from .world import ROOT, import_world, progress, write_json
from ..worlds import KNOWN, collection_active

def collect(key,host):
    label,archive,kind=KNOWN[key]
    if kind=='overlay':raise ValueError('This overlay requires a base district import.')
    target=ROOT/'data/world-source'/archive
    if target.exists():return target
    from ..library import local_archive, stage
    if local_archive(archive):return stage(archive)
    if not host:raise ValueError('Choose your game folder first, or start Studio with --xbox <console IPv4>.')
    part=target.with_suffix('.big.part')
    if part.exists():
        if collection_active(part,ROOT):raise ValueError('This archive is already being collected.')
        part.rename(part.with_name(part.name+f'.interrupted-{int(time.time())}'))
    progress(key,'Connecting to Xbox to collect the original archive…')
    connection=XBDM(host)
    try:
        connection.sock.settimeout(30)
        connection.sock.sendall(f'getfile name="{xbox_content_path()}\\{archive}"\r\n'.encode('ascii'))
        response=connection.line()
        if not response.startswith(b'203-'):raise ValueError('Xbox could not read this archive: '+response.decode('ascii',errors='replace'))
        size=struct.unpack('<I',connection.exact(4))[0]
        if not 0<size<4*1024**3:raise ValueError('Unexpected archive length')
        started=time.time();receipt=dict(archive=archive,expectedBytes=size,startedAt=started,source='Xbox XBDM read-only file transfer')
        write_json(ROOT/'data/world-source'/key/'collection.json',receipt)
        received=0;digest=hashlib.sha256();last=0
        with part.open('wb') as out:
            while received<size:
                block=connection.exact(min(1024*1024,size-received));out.write(block);digest.update(block);received+=len(block)
                if time.time()-last>5:
                    progress(key,f'Copying from Xbox · {received/size:.0%}',received,size);last=time.time()
        part.replace(target)
        receipt.update(completedAt=time.time(),sha256=digest.hexdigest(),receivedBytes=received)
        write_json(ROOT/'data/world-source'/key/'collection.json',receipt)
        return target
    finally:connection.close()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('key',choices=KNOWN);parser.add_argument('--xbox',default=None);args=parser.parse_args()
    try:
        source=collect(args.key,args.xbox)
        import_world(source,args.key,KNOWN[args.key][0])
    except Exception as e:progress(args.key,str(e),state='failed');raise

if __name__=='__main__':main()
