"""Narrow RX2 reader: static, single-bone, optimized Xbox triangle meshes.
Reference: Skate-Modding-Team/AASkate-Blender-Addon struct documentation.
Independent implementation; validates declarations, references and model bounds.
"""
import struct, math, hashlib
from .archive import u32
LABELS = {0x10031:'GPU buffer',0x200e9:'Vertex declaration',0x200ea:'Vertex buffer',0x200eb:'Index buffer',0x20081:'Mesh helper',0xeb0001:'Render model',0xeb0023:'Optimized mesh',0xeb0005:'Material definitions',0xeb0004:'Spline data',0x80006:'Clustered collision',0xeb000a:'Collision model'}

def decode(data):
    if data[:12] != b'\x89RW4xb2\0\r\n\x1a\n': raise ValueError('Unsupported arena platform')
    n, table, base = u32(data,32), u32(data,48), u32(data,68)
    if n > 4096 or table+n*24 > len(data): raise ValueError('Invalid section table')
    sections=[]
    for i in range(n):
        offset, _, size, align, ti, typ = struct.unpack_from('>6I',data,table+i*24)
        at = offset + (base if typ==0x10031 else 0)
        if at+size > len(data): raise ValueError('Section outside arena')
        sections.append(dict(index=i,type=f'0x{typ:x}',label=LABELS.get(typ,'Uninterpreted'),offset=at,size=size))
    def section(i, typ):
        if i >= n or sections[i]['type'] != f'0x{typ:x}': raise ValueError('Unexpected section reference')
        s=sections[i]; return data[s['offset']:s['offset']+s['size']]
    modelids=[s['index'] for s in sections if s['type']=='0xeb0001']
    if len(modelids)!=1: raise ValueError('Expected one render model')
    model=section(modelids[0],0xeb0001)
    bones, meshes, deform, islands=struct.unpack_from('>4H',model,48)
    if deform != 1: raise ValueError('Animated/multiple-bone geometry unsupported')
    matrix_at=u32(model,32); matrix=struct.unpack_from('>16f',model,matrix_at)
    if any(abs(x - (1 if i%5==0 else 0))>0.0001 for i,x in enumerate(matrix)):
        raise ValueError('Nonidentity bind transform unsupported')
    modelbounds=[list(struct.unpack_from('>3f',model,0)),list(struct.unpack_from('>3f',model,16))]
    mesh_at=u32(model,36); groups=[]
    for m in range(meshes):
        meshindex=u32(model,mesh_at+m*8); mesh=section(meshindex,0xeb0023)
        desc=section(u32(mesh,40),0x200e9); vb=section(u32(mesh,52),0x200ea); ib=section(u32(mesh,48),0x200eb)
        elems,streams=struct.unpack_from('>HH',desc,8)
        if streams!=1 or elems>16 or len(desc)<16+elems*16+1: raise ValueError('Unsupported vertex streams')
        stride=desc[16+elems*16]
        pos=None
        for i in range(elems):
            stream,offset,typ,method,usage,usageindex,indexed,cls=struct.unpack_from('>HHIBBBBI',desc,16+i*16)
            if usage==0 and usageindex==0: pos=(stream,offset,typ)
        if not pos or pos[0]!=0 or pos[2] not in [0x1a2360,0x2a23b9]: raise ValueError('Unsupported position declaration')
        fmt='>4e' if pos[2]==0x1a2360 else '>3f'
        if not stride or pos[1]+struct.calcsize(fmt)>stride: raise ValueError('Invalid vertex stride')
        rawv=section(u32(vb,24)>>2,0x10031); rawi=section(u32(ib,24),0x10031)
        size=u32(vb,32); count=u32(ib,32)
        if size>len(rawv) or size%stride or count*2>len(rawi): raise ValueError('Buffer size mismatch')
        vertices=[struct.unpack_from(fmt,rawv,i+pos[1])[:3] for i in range(0,size,stride)]
        indices=list(struct.unpack_from('>'+str(count)+'H',rawi))
        if not vertices or not all(math.isfinite(c) and abs(c)<1e6 for v in vertices for c in v): raise ValueError('Invalid vertex coordinate')
        draw_at=u32(mesh,68); island_count=u32(mesh,56); tris=[]
        if not 0<island_count<10000: raise ValueError('Invalid island count')
        for i in range(island_count):
            prim,bias,start,length=struct.unpack_from('>IiII',mesh,draw_at+i*16)
            if prim!=4 or length%3 or start+length>len(indices): raise ValueError('Unsupported primitive layout')
            run=[j+bias for j in indices[start:start+length]]
            if min(run,default=0)<0 or max(run,default=0)>=len(vertices): raise ValueError('Index outside vertex buffer')
            tris.extend(run)
        # Xbox half positions differ slightly from float bounds. Refuse substantial mismatch.
        for v in vertices:
            if any(v[a]<modelbounds[0][a]-0.08 or v[a]>modelbounds[1][a]+0.08 for a in range(3)):
                raise ValueError('Decoded positions exceed declared model bounds')
        groups.append(dict(positions=[c for v in vertices for c in v],indices=tris,sourceSection=meshindex))
    if not groups: raise ValueError('No supported meshes')
    allv=[g['positions'][i:i+3] for g in groups for i in range(0,len(g['positions']),3)]
    bounds=[[min(v[a] for v in allv) for a in range(3)],[max(v[a] for v in allv) for a in range(3)]]
    return dict(groups=groups,bounds=bounds,declaredBounds=modelbounds,sections=sections,sha256=hashlib.sha256(data).hexdigest(),vertices=len(allv),triangles=sum(len(g['indices'])//3 for g in groups),materials='clay preview; native textures not decoded',collision='preserved, not decoded',units='game units (metres); Y up; native local pivot')
