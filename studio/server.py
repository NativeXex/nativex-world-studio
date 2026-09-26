"""Local-only stdlib application service. No npm runtime or internet required."""
import json, mimetypes, re, secrets, time, threading, argparse, math, os, errno, sys
from http.client import HTTPConnection, HTTPException
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, unquote, parse_qs
from .catalog import ROOT, load_catalog
from .skate3.xbox import Adapter
from . import levels, worlds, parks, walktests, level_builds, library
TOKEN=secrets.token_urlsafe(32)
library.initialize()
CATALOG=load_catalog()
ASSETS={a['id']:a for a in CATALOG['assets']}
XBOX=Adapter(CATALOG)
SAVE_LOCK=threading.Lock()

def validate_project(p):
    if not isinstance(p,dict) or p.get('schema')!=1 or p.get('gameBuild')!='skate3-xbox360-tu3': raise ValueError('Unsupported project schema/build')
    if not re.fullmatch(r'[a-zA-Z0-9-]{1,100}',p.get('id','')):raise ValueError('Invalid project identity')
    if not isinstance(p.get('name'),str) or len(p['name'])>200:raise ValueError('Invalid project name')
    def box(b):
        return isinstance(b,dict) and all(isinstance(b.get(k),list) and len(b[k])==3 and all(isinstance(v,(int,float)) and math.isfinite(v) and abs(v)<100000 for v in b[k]) for k in ['min','max']) and all(b['min'][i]<b['max'][i] for i in range(3))
    if not box(p.get('region')) or not isinstance(p.get('protected'),list) or len(p['protected'])>100 or not all(box(b) for b in p['protected']):raise ValueError('Invalid editing/protected region')
    if not isinstance(p.get('generationHistory'),list):raise ValueError('Missing generation history')
    objects=p.get('instances');ids=set()
    if not isinstance(objects,list) or len(objects)>100:raise ValueError('Project object limit: 100')
    for o in objects:
        if not isinstance(o,dict) or not isinstance(o.get('id'),str) or o['id'] in ids:raise ValueError('Invalid or duplicate object identity')
        ids.add(o['id']);a=ASSETS.get(o.get('assetId'))
        if not a or a['status']!='decoded':raise ValueError('Asset is unavailable or unsupported')
        if not isinstance(o.get('position'),list) or len(o['position'])!=3 or not all(isinstance(v,(int,float)) and math.isfinite(v) and abs(v)<100000 for v in o['position']):raise ValueError('Invalid position')
        yaw=o.get('yaw')
        if not isinstance(yaw,(int,float)) or not math.isfinite(yaw) or abs(yaw/15-round(yaw/15))>0.0001:raise ValueError('Yaw must use 15-degree increments')
        if o.get('scale')!=[1,1,1]:raise ValueError('Scaling unavailable')
        if o.get('origin') not in ['added','original','override']:raise ValueError('Invalid content origin')
    return p

def layout_for(p):
    validate_project(p);items=[]
    for o in p['instances']:
        a=ASSETS[o['assetId']]
        if not a['nativeLayout'] or o['origin']!='added':raise ValueError('Xbox export supports added static terrain instances; captured originals are inspection-only')
        items.append(dict(id=o['id'],assetId=o['assetId'],recipe=a['recipe'],arena=a['arena'],sourceSha256=a['sha256'],position=o['position'],heading=round(o['yaw']/15)%24))
    return dict(format='nativex-layout',version=1,projectId=p['id'],gameBuild=p['gameBuild'],coordinateSystem='Y-up metres; native pivots',instances=items)

class Handler(BaseHTTPRequestHandler):
    server_version='NativeXWorldStudio/0.1'
    def log_message(self,*args):pass
    def respond(self,code,data,mime='application/json'):
        body=json.dumps(data,allow_nan=False).encode() if mime=='application/json' and not isinstance(data,bytes) else data
        self.send_response(code);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
    def local_request(self):
        if self.headers.get('Host') not in [f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}']:raise ValueError('Invalid local host')
    def do_GET(self):
        try:
            self.local_request();path=unquote(urlparse(self.path).path)
            if path=='/api/bootstrap':return self.respond(200,{'token':TOKEN,'catalog':CATALOG,'capabilities':{'nativeWorldExport':False,'blackboxSectionExport':True,'curatedBlackboxExport':True,'collisionOverlay':False,'modelIntegration':False,'levelPlans':True}})
            if path.startswith('/api/level-builds/'):
                return self.respond(200,level_builds.status(path.rsplit('/',1)[-1]))
            if path.startswith('/api/level-exports/'):
                return self.respond(200,level_builds.artifact(path.rsplit('/',1)[-1]),'application/octet-stream')
            if path.startswith('/api/level-walk-plans/'):
                return self.respond(200,walktests.read_snapshot(path.rsplit('/',1)[-1]))
            if path.startswith('/api/walk-layout/'):
                section=parse_qs(urlparse(self.path).query).get('section',[None])[0]
                return self.respond(200,walktests.describe_layout(path.rsplit('/',1)[-1],section))
            if path.startswith('/api/walk-source/'):
                section=parse_qs(urlparse(self.path).query).get('section',[None])[0]
                return self.respond(200,walktests.describe(path.rsplit('/',1)[-1],section))
            if path=='/api/parks/catalog':return self.respond(200,parks.catalog())
            if path=='/api/parks':return self.respond(200,parks.inventory())
            if path.startswith('/api/parks/'):return self.respond(200,parks.read(path.rsplit('/',1)[-1]))
            if path.startswith('/api/park-exports/'):
                name=path.rsplit('/',1)[-1]
                return self.respond(200,parks.artifact(name),'application/json' if name.endswith('.json') else 'application/octet-stream')
            if path=='/api/library':return self.respond(200,library.describe())
            if path=='/api/worlds':return self.respond(200,dict(**worlds.inventory(),xboxConfigured=bool(XBOX.host)))
            if path=='/api/levels':
                return self.respond(200,[dict(file=p.name,**{k:json.loads(p.read_text()).get(k) for k in ('name','sourceId','sourceSha256')}) for p in sorted((ROOT/'data/level-projects').glob('*.nxlevel.json')) if not p.name.startswith('.')])
            if path.startswith('/api/levels/'):
                name=path.rsplit('/',1)[-1]
                if not re.fullmatch(r'[a-zA-Z0-9-]+\.nxlevel\.json',name):raise ValueError('Invalid level plan name')
                return self.respond(200,json.loads((ROOT/'data/level-projects'/name).read_text()))
            if path=='/api/projects':
                return self.respond(200,[{'file':p.name,'name':json.loads(p.read_text())['name']} for p in sorted((ROOT/'data/projects').glob('*.nxworld.json')) if not p.name.startswith('.')])
            if path.startswith('/api/projects/'):
                name=path.rsplit('/',1)[-1]
                if not re.fullmatch(r'[a-zA-Z0-9.-]+\.nxworld\.json',name):raise ValueError('Invalid project name')
                return self.respond(200,json.loads((ROOT/'data/projects'/name).read_text()))
            if path.startswith('/api/geometry/'):
                key=path.rsplit('/',1)[-1]
                if not re.fullmatch(r'[0-9a-f]{16}',key):raise ValueError('Invalid asset reference')
                return self.respond(200,(ROOT/'data/decoded'/f'{key}.json').read_bytes(),'application/json; charset=utf-8')
            file=(ROOT/'web'/('index.html' if path=='/' else path.lstrip('/'))).resolve()
            if not file.is_relative_to((ROOT/'web').resolve()) or not file.is_file():return self.respond(404,{'error':'Not found'})
            return self.respond(200,file.read_bytes(),mimetypes.guess_type(file)[0] or 'application/octet-stream')
        except (ValueError,FileNotFoundError) as e:self.respond(400,{'error':str(e)})
    def do_POST(self):
        try:
            self.local_request()
            if self.headers.get('X-NativeX-Token')!=TOKEN:raise ValueError('Local session token required')
            origin=self.headers.get('Origin')
            if origin and origin not in [f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}']:raise ValueError('Cross-origin request rejected')
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<8*1024*1024:raise ValueError('Invalid request size')
            body=json.loads(self.rfile.read(size));path=urlparse(self.path).path
            if path=='/api/library/configure':return self.respond(200,library.configure(body.get('path')))
            if path=='/api/levels/build':return self.respond(200,level_builds.build(body))
            if path=='/api/levels/install':return self.respond(200,level_builds.install(body.get('buildId'),body.get('plan'),XBOX.host))
            if path=='/api/levels/restore-original':return self.respond(200,level_builds.install(body.get('buildId'),None,XBOX.host,restore=True))
            if path=='/api/levels/restore-previous':return self.respond(200,level_builds.install(body.get('buildId'),None,XBOX.host,restore='previous'))
            if path=='/api/levels/walk':return self.respond(200,walktests.snapshot_plan(body))
            if path=='/api/walk-reports':return self.respond(200,walktests.save_observation(body))
            if path=='/api/parks/generate':return self.respond(200,parks.generator.generate(body.get('plan'),body.get('seed')))
            if path=='/api/parks/move':return self.respond(200,parks.generator.move(body.get('plan'),body.get('moduleId'),body.get('delta')))
            if path=='/api/parks/validate':return self.respond(200,parks.generator.validate_layout(body))
            if path=='/api/parks/save':return self.respond(200,parks.save(body))
            if path=='/api/parks/export':return self.respond(200,parks.export(body))
            if path=='/api/worlds/prepare':return self.respond(200,worlds.prepare(body.get('id'),XBOX.host))
            if path=='/api/levels/save':return self.respond(200,levels.save(body))
            if path=='/api/save':
                p=validate_project(body)
                with SAVE_LOCK:
                    folder=ROOT/'data/projects';history=folder/p['id'];history.mkdir(exist_ok=True)
                    latest=folder/f"{p['id']}.nxworld.json"
                    revision=(json.loads(latest.read_text()).get('revision',0) if latest.exists() else 0)+1
                    p=dict(p,revision=revision,savedAt=time.time());text=json.dumps(p,indent=2,allow_nan=False)
                    (history/f'{revision:05d}.nxworld.json').write_text(text)
                    tmp=folder/f"{p['id']}.tmp";tmp.write_text(text);tmp.replace(latest)
                return self.respond(200,{'project':p,'path':str(latest)})
            if path=='/api/export':
                layout=layout_for(body);file=ROOT/'data/exports'/f"{body['id']}.nxlayout.json";file.write_text(json.dumps(layout,indent=2));return self.respond(200,{'layout':layout,'path':str(file)})
            if path=='/api/xbox/status':return self.respond(200,XBOX.status())
            if path=='/api/xbox/capture':return self.respond(200,XBOX.capture())
            if path=='/api/xbox/apply':return self.respond(200,XBOX.apply(layout_for(body)))
            if path=='/api/xbox/cleanup':return self.respond(200,XBOX.cleanup(body['projectId']))
            return self.respond(404,{'error':'Unknown route'})
        except Exception as e:self.respond(400,{'error':str(e),**({'details':e.diagnostics} if hasattr(e,'diagnostics') else {})})

def existing_studio(port):
    """Recognize our running server without restarting its Xbox ownership session."""
    connection=HTTPConnection('127.0.0.1',port,timeout=2)
    try:
        connection.request('GET','/')
        response=connection.getresponse()
        return (response.status==200
                and response.getheader('Server','').startswith('NativeXWorldStudio/')
                and b'<title>NativeX World Studio</title>' in response.read(65536))
    except (OSError,HTTPException):
        return False
    finally:
        connection.close()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8378);parser.add_argument('--xbox',default=None);parser.add_argument('--open',action='store_true');parser.add_argument('--game-dir');args=parser.parse_args();XBOX.host=args.xbox
    if args.game_dir:
        try:library.configure(args.game_dir)
        except ValueError as error:parser.error(str(error))
    if not 1<=args.port<=65535:parser.error('--port must be between 1 and 65535')
    try:
        server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    except OSError as error:
        if error.errno!=errno.EADDRINUSE:raise
        if existing_studio(args.port):
            url=f'http://127.0.0.1:{args.port}'
            print(f'NativeX World Studio is already running: {url}\nReusing the existing session.',flush=True)
            if args.open:
                import webbrowser
                webbrowser.open(url)
            return 0
        print(f'Port {args.port} is used by another application. Launch Studio with --port <unused-port>.',file=sys.stderr)
        return 1
    print(f'NativeX World Studio: http://127.0.0.1:{args.port}\nXbox: {args.xbox or 'not configured (offline)'} | Ctrl+C stops server',flush=True)
    if args.open:
        import webbrowser
        threading.Timer(.5,lambda:webbrowser.open(f'http://127.0.0.1:{args.port}')).start()
    try:server.serve_forever()
    except KeyboardInterrupt:print('NativeX World Studio stopped.')
    finally:server.server_close()
if __name__=='__main__':raise SystemExit(main())
