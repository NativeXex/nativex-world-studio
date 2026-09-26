"""Restricted V37 mailbox adapter. No RPC, executable patches or game-file writes.
Engine mutations run through V37's existing FreeSkateUpdate handler. Runtime
serial receipts live only in this process and never become project identities.
"""
import socket, struct, re, time, uuid, hashlib, json, threading, os

def xbox_content_path():
    value=os.environ.get("NATIVEX_XBOX_CONTENT", r"Hdd:\skate 3\data\content")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*:\\[A-Za-z0-9 _./\\-]+", value):
        raise ValueError("Invalid NATIVEX_XBOX_CONTENT path")
    return value.rstrip("\\")

BASE=0x91d00000
STATUS=BASE+0x21000; COMMAND=BASE+0x22fac; DRAFT=BASE+0x23fa8; RECORDS=BASE+0x22fe0

class XBDM:
    def __init__(self,host):
        if not isinstance(host,str) or not re.fullmatch(r'(?:\d{1,3}\.){3}\d{1,3}',host): raise ValueError('Xbox is not configured. Start Studio with --xbox <console IPv4>.')
        self.sock=socket.create_connection((host,730),timeout=4); self.sock.settimeout(8); self.buf=bytearray()
        if not self.line().startswith(b'201-'): raise ConnectionError('Invalid XBDM banner')
    def close(self): self.sock.close()
    def exact(self,n):
        while len(self.buf)<n:
            b=self.sock.recv(max(4096,n-len(self.buf)))
            if not b: raise ConnectionError('XBDM disconnected')
            self.buf.extend(b)
        b=bytes(self.buf[:n]);del self.buf[:n];return b
    def line(self):
        while b'\r\n' not in self.buf:
            b=self.sock.recv(4096)
            if not b: raise ConnectionError('XBDM disconnected')
            self.buf.extend(b)
        at=self.buf.index(b'\r\n');b=bytes(self.buf[:at]);del self.buf[:at+2];return b
    def command(self,s):
        self.sock.sendall((s+'\r\n').encode('ascii'));h=self.line();lines=[h]
        if h.startswith(b'202-'):
            while True:
                x=self.line()
                if x==b'.':break
                lines.append(x)
        return b'\n'.join(lines).decode('ascii',errors='replace')
    def read(self,address,n):
        self.sock.sendall(f'getmemex addr=0x{address:08x} length=0x{n:x}\r\n'.encode())
        if not self.line().startswith(b'203-'):raise RuntimeError('XBDM read refused')
        out=bytearray()
        while len(out)<n:
            self.exact(2);out.extend(self.exact(min(1024,n-len(out))))
        return bytes(out)
    def word(self,address): return struct.unpack('>I',self.read(address,4))[0]
    def write_control(self,address,data):
        if not ((address==COMMAND and len(data)==4) or (address==DRAFT and len(data)==16)):
            raise ValueError('Write outside V37 command/draft allowlist')
        r=self.command(f'setmem addr=0x{address:08x} data={data.hex()}')
        if not r.startswith('200-'): raise RuntimeError('XBDM command staging failed: '+r)
        if self.read(address,len(data))!=data and address!=COMMAND: raise RuntimeError('Draft readback mismatch')

class Adapter:
    def __init__(self,catalog,host=None):
        self.host=host; self.assets={a['id']:a for a in catalog['assets']};self.lock=threading.Lock();self.receipts={};self.log=[];self.session=str(uuid.uuid4())
    def connect(self):
        x=XBDM(self.host)
        try:
            mods=x.command('modules')
            plugin=next((l for l in mods.splitlines() if 'name="Skate3TU3Plugin_v37.xex"' in l),None)
            game=next((l for l in mods.splitlines() if 'name="default.xex"' in l),None)
            def fields(line):return dict(re.findall(r'(\w+)=(0x[0-9a-fA-F]+)',line or ''))
            p,g=fields(plugin),fields(game)
            if int(p.get('base','0'),16)!=BASE or int(p.get('size','0'),16)!=0x29000 or int(p.get('timestamp','0'),16)!=0x6aa5a059:
                raise RuntimeError('Expected exact V37 module at 0x91D00000; console build differs')
            if int(g.get('base','0'),16)!=0x82000000 or int(g.get('timestamp','0'),16)!=0x4c65a164: raise RuntimeError('Expected Skate 3 TU3 executable')
            return x
        except: x.close();raise
    def snapshot(self,x):
        for _ in range(30):
            raw=x.read(STATUS,132);v=struct.unpack_from('>29I',raw)
            if v[0]!=0x53335632 or v[1]!=3:raise RuntimeError('V37 status signature mismatch')
            if not v[2]&1 and x.word(STATUS+8)==v[2]:break
        else:raise RuntimeError('Could not obtain consistent V37 status')
        park=struct.unpack('>8I',x.read(BASE+0x21c58,32))
        terrain=struct.unpack('>20I',x.read(BASE+0x226f8,80))
        if park[:2]!=(0x53335043,2) or terrain[:2]!=(0x53335431,3):raise RuntimeError('Native component signature mismatch')
        menu=x.word(BASE+0x21818+36)
        live=x.word(BASE+0x21c2c+12); noclip=x.word(BASE+0x2274c+8)
        return dict(epoch=v[8],ready=bool(v[3] and v[4] and v[13]==1),mode=v[13],result=v[5],updates=v[6],active=v[15],selectedSlot=v[22],selectedSerial=v[23],draftValid=v[25],category=park[2],model=park[3],menuOpen=bool(menu),liveEdit=bool(live),noclip=bool(noclip),draft=list(struct.unpack_from('>3fI',raw,116)),terrain=dict(zip(['magic','version','manager','registry','mesh','pending','borrowed','age','creates','moves','removes','result','publishes','publishedCount','publishFailures','phase','collisionRebuilds','collisionEligible','collisionBody','collisionFailures'],terrain)))
    def guard(self,x,epoch=None):
        s=self.snapshot(x)
        if not s['ready']:raise RuntimeError('V37 is not ready in Free Skate')
        if s['menuOpen'] or s['liveEdit'] or s['noclip']:raise RuntimeError('Close the NativeX menu and exit object editing/noclip before applying')
        if epoch is not None and s['epoch']!=epoch:raise RuntimeError('World changed; apply stopped and stale receipts invalidated')
        return s
    def send(self,x,action,argument=0,epoch=None):
        if action not in [2,3,5,6,7,9,14]:raise ValueError('Unsupported mailbox command')
        s=self.guard(x,epoch); epoch=s['epoch']
        if x.word(COMMAND):raise RuntimeError('V37 mailbox busy')
        x.write_control(COMMAND,struct.pack('>I',(epoch<<16)|(argument<<8)|action))
        deadline=time.monotonic()+7
        while time.monotonic()<deadline:
            time.sleep(.04)
            if not x.word(COMMAND):
                s=self.guard(x,epoch)
                if s['updates']!=0:return s
        raise RuntimeError('V37 command acknowledgment timed out; do not retry blindly')
    def records(self,x):
        # XBDM transport can exceed a frame. Records change on commands, unlike
        # the per-frame status sequence. Double-collect bytes under an epoch guard.
        for _ in range(8):
            epoch=x.word(STATUS+32)
            raw=x.read(RECORDS,101*40)
            verify=x.read(RECORDS,101*40)
            if raw==verify and x.word(STATUS+32)==epoch:break
        else:raise RuntimeError('Could not read stable object records')
        result=[]
        for slot in range(101):
            handle,rawptr,owner,model,serial,px,py,pz,heading=struct.unpack_from('>IIQII3fI',raw,slot*40)
            if handle:result.append(dict(slot=slot,model=model,serial=serial,position=[px,py,pz],heading=heading))
        return result
    def resident_assets(self,x):
        values=struct.unpack('>661I',x.read(BASE+0x21c58+32,661*4))
        return [a['id'] for a in self.assets.values() if a['nativeLayout'] and values[a['nativeIndex']]==2]
    def status(self):
        with self.lock:
            x=self.connect()
            try:return self.snapshot(x)|{'session':self.session,'ownedByStudio':sum(len(r['objects']) for r in self.receipts.values()),'ip':self.host,'residentTerrainAssets':self.resident_assets(x)}
            finally:x.close()
    def capture(self):
        with self.lock:
            x=self.connect()
            try:
                s=self.snapshot(x);records=self.records(x);byindex={a['nativeIndex']:a for a in self.assets.values()};instances=[];skipped=[]
                for r in records:
                    a=byindex.get(r['model']-16)
                    if not a or a['status']!='decoded':skipped.append(r['model']);continue
                    # Snapshot has stable project UUIDs, never handles, addresses or serial identities.
                    instances.append(dict(id=str(uuid.uuid4()),assetId=a['id'],label=a['label'],position=r['position'],yaw=r['heading']*15,scale=[1,1,1],locked=True,origin='original',sourceTransform={'position':r['position'],'yaw':r['heading']*15}))
                return dict(instances=instances,source=dict(kind='nativex-session-snapshot',captureId=str(uuid.uuid4()),gameBuild='skate3-xbox360-tu3',units='metres',up='Y',note='Plugin-tracked requested placements only; not the original streamed city. Dynamic physics may differ.'),skipped=skipped,status=s)
            finally:x.close()
    def select_model(self,x,a,epoch):
        s=self.guard(x,epoch)
        for _ in range(22):
            if s['category']==a['categoryIndex']:break
            direction=1 if (a['categoryIndex']-s['category'])%22<=11 else 0
            s=self.send(x,14,direction,epoch)
        members=sorted(b['nativeIndex'] for b in self.assets.values() if b['categoryIndex']==a['categoryIndex'])
        for _ in range(len(members)):
            if s['model']==a['nativeIndex']:return
            cur=members.index(s['model']);target=members.index(a['nativeIndex']);d=(target-cur)%len(members)
            s=self.send(x,5,1 if d<=len(members)/2 else 0,epoch)
        raise RuntimeError('Could not select native asset')
    def select_serial(self,x,serial,epoch):
        s=self.guard(x,epoch)
        for _ in range(102):
            if s['selectedSerial']==serial:return s
            if not any(r['serial']==serial for r in self.records(x)):raise RuntimeError('Owned instance is no longer present')
            s=self.send(x,6,1,epoch)
        raise RuntimeError('Could not select owned instance')
    def cleanup_internal(self,x,receipt):
        self.guard(x,receipt['epoch'])
        for obj in list(receipt['objects']):
            if any(r['serial']==obj['serial'] for r in self.records(x)):
                self.select_serial(x,obj['serial'],receipt['epoch']);self.send(x,3,epoch=receipt['epoch'])
                if any(r['serial']==obj['serial'] for r in self.records(x)):raise RuntimeError('Cleanup not acknowledged; receipt retained')
            receipt['objects'].remove(obj)
    def cleanup(self,project_id):
        with self.lock:
            receipt=self.receipts.get(project_id)
            if not receipt:return {'removed':0,'note':'No owned objects in this Studio session'}
            x=self.connect()
            try:
                count=len(receipt['objects']);s=self.guard(x)
                if s['epoch']!=receipt['epoch']:
                    del self.receipts[project_id];return {'removed':0,'note':'World changed; stale ownership forgotten without touching new-world objects'}
                self.cleanup_internal(x,receipt);del self.receipts[project_id];return {'removed':count,'status':self.snapshot(x)}
            finally:x.close()
    def apply(self,layout):
        with self.lock:
            x=self.connect();pid=layout['projectId'];digest=hashlib.sha256(json.dumps(layout,sort_keys=True).encode()).hexdigest()
            try:
                s=self.guard(x);old=self.receipts.get(pid)
                if old and old['epoch']!=s['epoch']:self.receipts.pop(pid);old=None
                if old:
                    present={r['serial'] for r in self.records(x)}
                    if old['digest']==digest and len(old['objects'])==len(layout['instances']) and all(o['serial'] in present for o in old['objects']):return {'unchanged':True,'count':len(old['objects']),'status':s}
                    raise RuntimeError('This project already owns a layout. Clean it up before applying revisions.')
                if len(layout['instances'])>12:raise ValueError('Initial adapter safety budget: at most 12 additions per layout')
                if s['active']+len(layout['instances'])>99:raise ValueError('Insufficient tracked-object capacity, including replacement staging')
                resident=set(self.resident_assets(x))
                missing=[self.assets[i['assetId']]['label'] for i in layout['instances'] if i['assetId'] not in resident]
                if missing:raise RuntimeError('Terrain asset not resident: '+', '.join(sorted(set(missing)))+'. Place one of each in the V37 spawner first, then close its menu. Cold loading requires the V37 menu to remain open.')
                epoch=s['epoch'];receipt={'epoch':epoch,'digest':digest,'objects':[]};self.receipts[pid]=receipt
                for item in layout['instances']:
                    a=self.assets[item['assetId']];self.select_model(x,a,epoch)
                    before={r['serial'] for r in self.records(x)}
                    s=self.send(x,2,epoch=epoch)
                    # A cold terrain recipe can need async registration. Refuse blind retries.
                    if s['result']!=1:raise RuntimeError(f"Spawn not completed (V37 result {s['result']}); load this asset once in NativeX and retry after cleanup")
                    serial=s['selectedSerial'];slot=s['selectedSlot']
                    if serial in before:raise RuntimeError('No new owned identity after spawn')
                    obj={'id':item['id'],'serial':serial};receipt['objects'].append(obj)
                    self.guard(x,epoch)
                    if x.word(BASE+0x22fdc)!=serial:raise RuntimeError('Selected draft identity changed')
                    payload=struct.pack('>3fI',*item['position'],item['heading'])
                    x.write_control(DRAFT,payload)
                    s=self.guard(x,epoch)
                    if s['selectedSerial']!=serial or not s['draftValid']:raise RuntimeError('Selection changed during draft staging')
                    s=self.send(x,9,epoch=epoch)
                    # Terrain replacement changes serial. Capture all newly owned serials even on failure.
                    after=self.records(x);new=[r for r in after if r['serial'] not in before]
                    receipt['objects'].remove(obj)
                    receipt['objects'].extend({'id':item['id'],'serial':r['serial']} for r in new)
                    target=next((r for r in new if r['slot']==slot),None)
                    if s['result']!=14 or len(new)!=1 or not target or target['heading']!=item['heading'] or any(abs(a-b)>.001 for a,b in zip(target['position'],item['position'])):raise RuntimeError('Native placement did not match layout; clean up retained Studio objects')
                final=self.snapshot(x)
                report={'count':len(receipt['objects']),'status':final,'collisionEvidence':'Native terrain registration counters only; actual skateability requires gameplay observation.'}
                self.log.append(report);return report
            except Exception:
                # Preserve receipt on failure for explicit, scoped cleanup. No remove-all command.
                raise
            finally:x.close()
