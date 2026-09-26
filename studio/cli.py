"""Local API client for people, scripts and coding assistants. No cloud service."""
import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8378)
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ['status','worlds','projects','library']:sub.add_parser(name)
    connect=sub.add_parser('connect-folder');connect.add_argument('path')
    prepare=sub.add_parser('import-world');prepare.add_argument('world')
    save=sub.add_parser('save-plan');save.add_argument('file',type=Path)
    build=sub.add_parser('build');build.add_argument('file',type=Path)
    result=sub.add_parser('build-status');result.add_argument('id')
    args=parser.parse_args()
    if not 1<=args.port<=65535:parser.error('Invalid local port')
    base=f'http://127.0.0.1:{args.port}'
    def request(path,body=None):
        headers={}
        if body is not None:
            headers={'Content-Type':'application/json','X-NativeX-Token':request('/api/bootstrap')['token']}
        req=Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        with urlopen(req,timeout=120) as response:return json.load(response)
    try:
        if args.command=='status':
            bootstrap=request('/api/bootstrap')
            value={'capabilities':bootstrap['capabilities'],'library':request('/api/library')}
        elif args.command in ['worlds','projects','library']:
            value=request('/api/'+('levels' if args.command=='projects' else args.command))
        elif args.command=='connect-folder':value=request('/api/library/configure',{'path':args.path})
        elif args.command=='import-world':value=request('/api/worlds/prepare',{'id':args.world})
        elif args.command=='build-status':
            import re
            if not re.fullmatch('[0-9a-f]{64}',args.id):parser.error('Invalid build identity')
            value=request('/api/level-builds/'+args.id)
        else:value=request('/api/levels/'+('save' if args.command=='save-plan' else 'build'),json.loads(args.file.read_text()))
        print(json.dumps(value,indent=2))
    except HTTPError as error:parser.exit(1,error.read().decode()+'\n')
    except (URLError,OSError,ValueError) as error:parser.exit(1,str(error)+'\nStart Studio first: python3 -m studio.server\n')

if __name__=='__main__':main()
