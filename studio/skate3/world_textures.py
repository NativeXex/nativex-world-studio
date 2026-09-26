"""Xbox tiled base mip -> PNG. No imaging dependency; unsupported formats fail.

Fetch-constant fields follow Xenos/AASkate documentation. Tiled address math
and packed-tail offsets follow SK8-Engine's MIT retail_texture_decode.py.
Only 2D BC1/BC3, RGB565 and RGBA8 are supported here.
"""
import struct, zlib, binascii
from .arena import Arena

def tiled_offset(x,y,pitch,log):
    pitch=(pitch+31)&~31
    macro=((x>>5)+(y>>5)*(pitch>>5))<<(log+7)
    micro=((x&7)+((y&14)<<2))<<log
    offset=macro+((micro&~15)<<1)+(micro&15)+((y&1)<<4)
    return ((offset&~511)<<3)+((y&16)<<7)+((offset&448)<<2)+(((((y&8)>>2)+(x>>3))&3)<<6)+(offset&63)

def rgb565(v):
    return ((v>>11)*255//31,((v>>5)&63)*255//63,(v&31)*255//31)

def bc_block(block,alpha=False):
    alpha_values=[255]*16
    if alpha:
        a,b=block[:2];table=[a,b]
        table += ([(a*(7-i)+b*i)//7 for i in range(1,7)] if a>b else [(a*(5-i)+b*i)//5 for i in range(1,5)]+[0,255])
        bits=int.from_bytes(block[2:8],'little');alpha_values=[table[(bits>>(3*i))&7] for i in range(16)]
        block=block[8:]
    a,b,bits=struct.unpack('<HHI',block);ca,cb=rgb565(a),rgb565(b)
    table=[(*ca,255),(*cb,255)]
    if a>b or alpha:
        table += [(*( (ca[j]*2+cb[j])//3 for j in range(3)),255),(*( (ca[j]+cb[j]*2)//3 for j in range(3)),255)]
    else: table += [(*( (ca[j]+cb[j])//2 for j in range(3)),255),(0,0,0,0)]
    pixels=[]
    for i in range(16):
        pixel=table[(bits>>(2*i))&3]
        pixels.append((*pixel[:3],alpha_values[i] if alpha else pixel[3]))
    return pixels

def png(width,height,rgba):
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',binascii.crc32(kind+data)&0xffffffff)
    rows=b''.join(b'\0'+rgba[y*width*4:(y+1)*width*4] for y in range(height))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>2I5B',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(rows,6))+chunk(b'IEND',b'')

def decode(data):
    a=Arena(data);s=a.one(0x200e8);raw=a.one(0x10031)
    w=struct.unpack_from('>6I',s,28)
    kind=w[1]&63;endian=(w[1]>>6)&3;dimension=(w[5]>>9)&3
    width=(w[2]&8191)+1;height=((w[2]>>13)&8191)+1
    tiled=bool(w[0]>>31);pitch=((w[0]>>22)&511)*32
    if dimension!=1: raise ValueError('Cubemap/volume preview unsupported')
    if width*height>4096*4096: raise ValueError('Texture size limit')
    if kind not in (18,20,4,6): raise ValueError(f'Unsupported texture format {kind}')
    block=4 if kind in (18,20) else 1;size={18:8,20:16,4:2,6:4}[kind]
    log=size.bit_length()-1
    cols=(width+block-1)//block;rows=(height+block-1)//block
    packed_x=packed_y=0
    if (w[5]>>11)&1 and min((width-1).bit_length(),(height-1).bit_length())<=4:
        if width>height:packed_y=16//block
        else:packed_x=16//block
    rgba=bytearray(width*height*4)
    for y in range(rows):
        for x in range(cols):
            at=tiled_offset(x+packed_x,y+packed_y,max(cols,pitch//block),log) if tiled else (y*cols+x)*size
            if at+size>len(raw): raise ValueError('Tiled texture address outside GPU resource')
            value=raw[at:at+size]
            if kind==4:
                pixels=[(*rgb565(int.from_bytes(value,'big')),255)]
            else:
                if endian==1:value=b''.join(value[i:i+2][::-1] for i in range(0,size,2))
                elif endian==2:value=b''.join(value[i:i+4][::-1] for i in range(0,size,4))
                elif endian==3:value=b''.join(value[i+2:i+4]+value[i:i+2] for i in range(0,size,4))
                pixels=bc_block(value,kind==20) if block==4 else [(value[2],value[1],value[0],value[3])]
            for j,pixel in enumerate(pixels):
                px=x*block+j%block;py=y*block+j//block
                if px<width and py<height:
                    dst=(py*width+px)*4;rgba[dst:dst+4]=bytes(pixel)
    toc=[r for r in a.toc() if r['name'].lower().endswith('.texture')]
    if len(toc)!=1:raise ValueError('Texture has no unique GUID')
    return dict(id=toc[0]['guid'],width=width,height=height,format=kind,endian=endian,pitch=pitch),png(width,height,rgba)
