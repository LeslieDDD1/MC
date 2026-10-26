import struct, sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\deepseek_workplace')
from parse_log import crc32c
from nbt_tool import Reader, read_string, read_payload, fmt_val, TAG_COMPOUND

def varint(data, pos, maxbytes=10):
    v=0; shift=0; n=0
    while True:
        b=data[pos]; pos+=1; n+=1
        v |= (b & 0x7F) << shift
        if not (b & 0x80): break
        shift += 7
        if n >= maxbytes: break
    return v, pos

def snappy_decompress(src):
    pos=0
    ulen, pos = varint(src, pos)
    out=bytearray()
    while pos < len(src):
        tag=src[pos]; pos+=1
        t=tag&3
        if t==0:
            ln=tag>>2
            if ln<60:
                ln+=1
            else:
                n=ln-59
                ln=0
                for i in range(n):
                    ln |= src[pos+i] << (8*i)
                pos+=n
                ln+=1
            out += src[pos:pos+ln]; pos+=ln
        else:
            if t==1:
                ln=4+((tag>>2)&7)
                off=((tag>>5)<<8)|src[pos]; pos+=1
            elif t==2:
                ln=1+(tag>>2)
                off=src[pos]|(src[pos+1]<<8); pos+=2
            else:
                ln=1+(tag>>2)
                off=src[pos]|(src[pos+1]<<8)|(src[pos+2]<<16)|(src[pos+3]<<24); pos+=4
            start=len(out)-off
            for i in range(ln):
                out.append(out[start+i])
    return bytes(out[:ulen])

MAGIC = b'\x57\xfb\x80\x8b\x24\x75\x47\xdb'

def read_block_handle(data, pos):
    off, pos = varint(data, pos)
    size, pos = varint(data, pos)
    return off, size, pos

def get_block(data, off, size):
    raw = data[off:off+size]
    try:
        import zlib
        out = zlib.decompress(raw, -15)
        return out, 'deflate'
    except Exception:
        return raw, 'raw'

def parse_block_entries(block):
    nrestart = struct.unpack_from('<I', block, len(block)-4)[0]
    restarts_off = len(block)-4-4*nrestart
    entries=[]
    pos=0
    key=b''
    while pos < restarts_off:
        shared, pos = varint(block, pos)
        nonshared, pos = varint(block, pos)
        vlen, pos = varint(block, pos)
        key = key[:shared] + block[pos:pos+nonshared]; pos+=nonshared
        val = block[pos:pos+vlen]; pos+=vlen
        entries.append((key,val))
    return entries

def scan_table(path, target):
    data=open(path,'rb').read()
    if len(data)<48 or data[-8:]!=MAGIC:
        return None
    pos = len(data)-48
    mi_off, mi_size, pos = read_block_handle(data, pos)
    idx_off, idx_size, pos = read_block_handle(data, pos)
    idx_block, idx_type = get_block(data, idx_off, idx_size)
    idx_entries = parse_block_entries(idx_block)
    best=None
    short_keys=[]
    blkcount=0
    for k,v in idx_entries:
        off,size = read_block_handle(v,0)[0:2]
        blk, btype = get_block(data, off, size)
        blkcount+=1
        for ikey, ival in parse_block_entries(blk):
            if len(ikey)<8: continue
            ukey = ikey[:-8]
            seq = struct.unpack_from('<Q', ikey, len(ikey)-8)[0] >> 8
            if ukey==target:
                if best is None or seq>best[0]:
                    best=(seq, ikey[-1], ival)
            elif len(ukey)<60 and len(ukey)>0 and ukey[:1].isalpha():
                short_keys.append(ukey)
    if best is None:
        print('  table %s: no target, %d index entries, %d blocks' % (path.split(chr(92))[-1], len(idx_entries), blkcount))
    return best, short_keys

if __name__=='__main__':
    dbdir = r'D:\deepseek_workplace\mc-world-backup-20261020-212834\db'
    target = b'~local_player'
    best=None
    allshort=set()
    for f in sorted(os.listdir(dbdir)):
        if f.endswith('.ldb'):
            r = scan_table(os.path.join(dbdir,f), target)
            if r and r[0]:
                if best is None or r[0][0]>best[0]:
                    best=r[0]
                    print('table %s: ~local_player seq=%d type=%d val_bytes=%d' % (f, r[0][0], r[0][1], len(r[0][2])))
            if r:
                for k in r[1]: allshort.add(k)
    print('---- short non-chunk keys found ----')
    for k in sorted(allshort)[:60]:
        print('  ', k.decode('utf-8','replace'))
    if best:
        seq, vt, val = best
        print('==== ~local_player current value (%d bytes) ====' % len(val))
        open(r'D:\deepseek_workplace\local_player.raw','wb').write(val)
        print('head hex:', val[:32].hex())
        r=Reader(val)
        t=r.u8(); name=read_string(r); root=read_payload(r,t,0)
        print('name=%r type=%d consumed=%d' % (name,t,r.pos))
        if t==TAG_COMPOUND:
            for n,ct,cv in root:
                nn=n.decode('utf-8','replace') if isinstance(n,bytes) else n
                if ct==TAG_COMPOUND:
                    print('  %s (compound %d)' % (nn,len(cv)))
                else:
                    print('  %s (t=%d) = %s' % (nn,ct,fmt_val(ct,cv,90)))
    else:
        print('NOT FOUND in .ldb tables')
