import re, json, hashlib, time
from pathlib import Path
from .skate3.archive import BigArchive
from .skate3.geometry import decode
ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = []

def empty_catalog():
    return dict(version=1, game='Skate 3 Xbox 360 TU3', assets=[], categories=[],
                coordinates='native metres; Y up; yaw degrees',
                setupRequired=True, message='Import your own parkassets.big to populate the object library.')

def load_catalog():
    path=ROOT/'data/catalog.json'
    return json.loads(path.read_text()) if path.exists() else empty_catalog()

def build_catalog(progress=None):
    from .library import initialize
    initialize()
    archive = BigArchive(ROOT/'data/source/parkassets.big')
    header=(ROOT/'research/v37_park_catalog.h').read_text()
    categories=re.findall(r'"([^"]+)"',header.split('kParkCategories')[1].split(';')[0])
    rows=re.findall(r'\{0x([0-9a-f]+)ui64,(\d+),"([^"]+)",0x([0-9a-f]+)ui64,(\d+)\}',header)
    paths={Path(p).stem:p for p in archive.entries if '/model/' in p and p.endswith('.rx2')}
    result=[]
    for index,(arena,category,label,recipe,terrain) in enumerate(rows):
        asset=dict(id='s3:'+recipe,arena='0x'+arena,recipe='0x'+recipe,label=label,category=categories[int(category)],categoryIndex=int(category),nativeIndex=index,terrain=bool(int(terrain)),status='missing',reason='Model not present in collected archive',nativeLayout=bool(int(terrain)),scaleSupported=False,dependencies=[],collision='not decoded',material='clay preview')
        path=paths.get('0x'+arena)
        if path:
            asset['sourcePath']=path
            try:
                raw=archive.read(path); asset['sha256']=hashlib.sha256(raw).hexdigest()
                # Keep original unmodified resource, including all unknown sections.
                (ROOT/'data/source'/f'{arena}.rx2').write_bytes(raw)
                geo=decode(raw)
                (ROOT/'data/decoded'/f'{recipe}.json').write_text(json.dumps(geo,separators=(',',':')))
                asset.update(status='decoded',reason='',bounds=geo['bounds'],dimensions=[round(geo['bounds'][1][i]-geo['bounds'][0][i],4) for i in range(3)],vertices=geo['vertices'],triangles=geo['triangles'],sections=geo['sections'])
            except (ValueError,IndexError,KeyError,OverflowError, __import__('struct').error) as e:
                asset.update(status='unsupported',reason=str(e),nativeLayout=False)
        else: asset['nativeLayout']=False
        asset['dependencies']=[dict(kind='recipe',id=asset['recipe'],status='V37 catalogue mapping'),dict(kind='arena',id=asset['arena'],status='collected' if path else 'missing'),dict(kind='textures',status='links unresolved; clay preview'),dict(kind='collision',status='native resource retained; host decoding unavailable')]
        result.append(asset)
        if progress and index%20==0: progress(index,len(rows))
    summary=dict(version=1,game='Skate 3 Xbox 360 TU3',archiveSha256=hashlib.sha256(archive.data).hexdigest(),assets=result,categories=categories,coordinates='native metres; Y up; yaw degrees',generatedAt=time.time())
    (ROOT/'data/catalog.json').write_text(json.dumps(summary,indent=2))
    return summary

if __name__=='__main__':
    from collections import Counter
    c=build_catalog(); print(Counter(a['status'] for a in c['assets'])); print(Counter(a['reason'] for a in c['assets'] if a['status']!='decoded'))
