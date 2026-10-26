import struct, sys, os
sys.path.insert(0, r'D:\deepseek_workplace')
from nbt_tool import Reader, read_string, read_payload, dump, fmt_val, TAG_COMPOUND, TAG_END

# ---- CRC32C (Castagnoli) ----
def make_crc_table():
    t=[]
    for i in range(256):
        c=i
        for _ in range(8):
            c = (c>>1) ^ (0x82F63B78 if (c&1) else 0)
        t.append(c & 0xFFFFFFFF)
    return t
CRC_T=make_crc_table()
def crc32c(data):
    c=0xFFFFFFFF
    for b in data:
        c = CRC_T[(c ^ b) & 0xFF] ^ (c >> 8)
    return (c ^ 0xFFFFFFFF) & 0xFFFFFFFF

def parse_batch(payload):
    pos=0
    if len(payload)<12: return None
    seq=struct.unpack_from('<Q', payload, pos)[0]; pos+=8
    cnt=struct.unpack_from('<I', payload, pos)[0]; pos+=4
    ops=[]
    for _ in range(cnt):
        op=payload[pos]; pos+=1
        # varint32 key length
        klen=0; shift=0
        while True:
            b=payload[pos]; pos+=1
            klen |= (b & 0x7F) << shift
            if not (b & 0x80): break
            shift+=7
        key=payload[pos:pos+klen]; pos+=klen
        val=b''
        if op==1:
            vlen=0; shift=0
            while True:
                b=payload[pos]; pos+=1
                vlen |= (b & 0x7F) << shift
                if not (b & 0x80): break
                shift+=7
            val=payload[pos:pos+vlen]; pos+=vlen
        ops.append((op,key,val))
    return ops

def read_log(path, key_filter=None):
    data=open(path,'rb').read()
    size=len(data)
    BLOCK=32768
    frag=b''
    in_frag=False
    results=[]
    pos=0
    bad=0
    while pos + 7 <= size:
        rem = BLOCK - (pos % BLOCK)
        # a fresh block starts here if pos%BLOCK==0
        # read record header
        avail = min(rem, size-pos)
        if avail < 7:
            break
        crc, ln, typ = struct.unpack_from('<I', data, pos), None, None
        crc = struct.unpack_from('<I', data, pos)[0]
        ln = struct.unpack_from('<H', data, pos+4)[0]
        typ = data[pos+6]
        pos += 7
        if ln==0 or pos + ln > size:
            break
        payload = data[pos:pos+ln]
        # verify crc
        expect = crc32c(bytes([typ]) + payload)
        expect = ((expect >> 15) | ((expect & 0x7FFFFFFF) << 17)) + 0xa282ead8 & 0xFFFFFFFF
        pos += ln
        if expect != crc:
            bad += 1
            break
        if typ==0:
            break
        if typ==1:
            ops=parse_batch(payload)
            if ops:
                for op,k,v in ops:
                    if key_filter is None or k==key_filter:
                        results.append((op,k,v))
        elif typ==2:
            frag=payload
        elif typ==3:
            frag+=payload
        elif typ==4:
            frag+=payload
            ops=parse_batch(frag)
            if ops:
                for op,k,v in ops:
                    if key_filter is None or k==key_filter:
                        results.append((op,k,v))
        else:
            break
    return results, bad

if __name__=='__main__':
    logpath = r'D:\deepseek_workplace\mc-world-backup-20261020-212834\db\000225.log'
    key = b'~local_player'
    results, bad = read_log(logpath, key)
    print('log records for ~local_player:', len(results), ' crc_errors:', bad)
    if results:
        op,k,v = results[-1]
        print('last write: op=%d key=%r value_bytes=%d' % (op,k,len(v)))
        open(r'D:\deepseek_workplace\local_player.raw','wb').write(v)
        r = Reader(v)
        t = r.u8()
        name = read_string(r)
        root = read_payload(r, t, 0)
        print('player NBT: name=%r type=%d consumed=%d' % (name, t, r.pos))
        if t==TAG_COMPOUND:
            for n,ct,cv in root:
                nn = n.decode('utf-8','replace') if isinstance(n,bytes) else n
                if ct==TAG_COMPOUND:
                    print('  %s (compound %d)' % (nn, len(cv)))
                else:
                    print('  %s (t=%d) = %s' % (nn, ct, fmt_val(ct,cv,100)))
    else:
        print('no ~local_player in this log')
