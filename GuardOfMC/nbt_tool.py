import struct, sys, io, os

TAG_END=0; TAG_BYTE=1; TAG_SHORT=2; TAG_INT=3; TAG_LONG=4
TAG_FLOAT=5; TAG_DOUBLE=6; TAG_BYTE_ARRAY=7; TAG_STRING=8
TAG_LIST=9; TAG_COMPOUND=10; TAG_INT_ARRAY=11; TAG_LONG_ARRAY=12

class Reader:
    def __init__(self, buf): self.buf=buf; self.pos=0
    def u8(self): v=self.buf[self.pos]; self.pos+=1; return v
    def i8(self): v=struct.unpack_from('<b',self.buf,self.pos)[0]; self.pos+=1; return v
    def u16(self): v=struct.unpack_from('<H',self.buf,self.pos)[0]; self.pos+=2; return v
    def i16(self): v=struct.unpack_from('<h',self.buf,self.pos)[0]; self.pos+=2; return v
    def i32(self): v=struct.unpack_from('<i',self.buf,self.pos)[0]; self.pos+=4; return v
    def u32(self): v=struct.unpack_from('<I',self.buf,self.pos)[0]; self.pos+=4; return v
    def i64(self): v=struct.unpack_from('<q',self.buf,self.pos)[0]; self.pos+=8; return v
    def f32(self): v=struct.unpack_from('<f',self.buf,self.pos)[0]; self.pos+=4; return v
    def f64(self): v=struct.unpack_from('<d',self.buf,self.pos)[0]; self.pos+=8; return v
    def raw(self,n): v=self.buf[self.pos:self.pos+n]; self.pos+=n; return v

def read_string(r):
    n=r.u16()
    return r.raw(n)

def read_payload(r, tag, depth):
    if tag==TAG_BYTE: return r.i8()
    if tag==TAG_SHORT: return r.i16()
    if tag==TAG_INT: return r.i32()
    if tag==TAG_LONG: return r.i64()
    if tag==TAG_FLOAT: return r.f32()
    if tag==TAG_DOUBLE: return r.f64()
    if tag==TAG_BYTE_ARRAY:
        n=r.i32()
        if n<0 or n>len(r.buf)-r.pos: raise ValueError('bad bytearray len %d'%n)
        return r.raw(n)
    if tag==TAG_STRING: return read_string(r)
    if tag==TAG_LIST:
        et=r.u8(); n=r.i32()
        vals=[]
        for _ in range(n):
            vals.append(read_payload(r, et, depth+1))
        return (et, vals)
    if tag==TAG_COMPOUND:
        d=[]
        while True:
            t=r.u8()
            if t==TAG_END: break
            name=read_string(r)
            d.append((name, t, read_payload(r, t, depth+1)))
        return d
    if tag==TAG_INT_ARRAY:
        n=r.i32()
        if n<0 or 4*n>len(r.buf)-r.pos: raise ValueError('bad intarray len')
        return r.raw(4*n)
    if tag==TAG_LONG_ARRAY:
        n=r.i32()
        if n<0 or 8*n>len(r.buf)-r.pos: raise ValueError('bad longarray len')
        return r.raw(8*n)
    raise ValueError('unknown tag %d'%tag)

def parse_named(r, depth=0):
    t=r.u8()
    if t==TAG_END: return None
    name=read_string(r)
    val=read_payload(r, t, depth+1)
    return (name, t, val)

def parse_level_dat(path):
    data=open(path,'rb').read()
    if len(data)<8: raise ValueError('file too small')
    ver, ln = struct.unpack_from('<ii', data, 0)
    r=Reader(data); r.pos=8
    t=r.u8()
    name=read_string(r)
    root=read_payload(r, t, 0)
    return ver, ln, name, t, root

def fmt_val(t, v, limit=120):
    if t==TAG_BYTE_ARRAY: return '<bytes len=%d>'%len(v)
    if t==TAG_INT_ARRAY: return '<intarray bytes=%d>'%len(v)
    if t==TAG_LONG_ARRAY: return '<longarray bytes=%d>'%len(v)
    if t==TAG_STRING:
        try:
            s=v.decode('utf-8')
        except Exception:
            s='<non-utf8 %d bytes>'%len(v)
        if len(s)>limit: s=s[:limit]+'...'
        return repr(s)
    if t==TAG_LIST:
        et, vals=v
        return '<list type=%d len=%d>'%(et,len(vals))
    if t==TAG_COMPOUND:
        return '<compound %d entries>'%len(v)
    return repr(v)

def dump(entries, indent=0, maxdepth=6):
    pad='  '*indent
    for name, t, v in entries:
        print('%s%s (t=%d) = %s'%(pad, name, t, fmt_val(t,v)))
        if t==TAG_COMPOUND and indent<maxdepth:
            dump(v, indent+1, maxdepth)

def enc_string(s):
    if isinstance(s, bytes):
        b=s
    else:
        b=s.encode('utf-8')
    return struct.pack('<H',len(b))+b

def enc_payload(t, v):
    if t==TAG_BYTE: return struct.pack('<b', v)
    if t==TAG_SHORT: return struct.pack('<h', v)
    if t==TAG_INT: return struct.pack('<i', v)
    if t==TAG_LONG: return struct.pack('<q', v)
    if t==TAG_FLOAT: return struct.pack('<f', v)
    if t==TAG_DOUBLE: return struct.pack('<d', v)
    if t==TAG_BYTE_ARRAY: return struct.pack('<i',len(v))+v
    if t==TAG_STRING: return enc_string(v)
    if t==TAG_LIST:
        et, vals=v
        out=bytes([et])+struct.pack('<i',len(vals))
        for x in vals: out+=enc_payload(et,x)
        return out
    if t==TAG_COMPOUND:
        out=b''
        for name,ct,cv in v:
            out+=bytes([ct])+enc_string(name)+enc_payload(ct,cv)
        out+=b'\x00'
        return out
    if t==TAG_INT_ARRAY:
        return struct.pack('<i',len(v)//4)+v
    if t==TAG_LONG_ARRAY:
        return struct.pack('<i',len(v)//8)+v
    raise ValueError('unknown tag %d'%t)

def enc_level_dat(ver, name, t, root):
    body=bytes([t])+enc_string(name)+enc_payload(t, root)
    return struct.pack('<ii', ver, len(body))+body

def _key_bytes(k):
    return k if isinstance(k, bytes) else k.encode('utf-8')

def find(entries, key):
    kb = _key_bytes(key)
    for name,t,v in entries:
        nb = name if isinstance(name, bytes) else name.encode('utf-8')
        if nb == kb: return t,v
    return None

def set_entry(entries, key, t, v):
    kb = _key_bytes(key)
    for i,(name,ct,cv) in enumerate(entries):
        nb = name if isinstance(name, bytes) else name.encode('utf-8')
        if nb == kb:
            entries[i]=(name,t,v)
            return
    entries.append((kb,t,v))

if __name__=='__main__':
    path=sys.argv[1]
    ver, ln, name, t, root = parse_level_dat(path)
    print('header: version=%d nbt_length=%d root_name=%r root_type=%d file_size=%d'%(ver,ln,name,t,os.path.getsize(path)))
    if t==TAG_COMPOUND:
        dump(root, 0, 6)
