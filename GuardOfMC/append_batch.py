import struct, sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\deepseek_workplace')
from parse_log import crc32c

def varint32(n):
    out=b''
    while True:
        b=n & 0x7F
        n >>= 7
        if n: out += bytes([b|0x80])
        else: out += bytes([b]); break
    return out

def make_batch(seq, pairs):
    payload = struct.pack('<Q', seq) + struct.pack('<I', len(pairs))
    for k, v in pairs:
        payload += bytes([1]) + varint32(len(k)) + k + varint32(len(v)) + v
    return payload

def crc_masked(typ, data):
    c = crc32c(bytes([typ]) + data)
    return (((c >> 15) | ((c & 0x7FFFFFFF) << 17)) + 0xa282ead8) & 0xFFFFFFFF

def scan_log_end(path):
    data = open(path,'rb').read()
    BLOCK = 32768
    pos = 0
    last_end = 0
    while pos + 7 <= len(data):
        crc = struct.unpack_from('<I', data, pos)[0]
        ln = struct.unpack_from('<H', data, pos+4)[0]
        typ = data[pos+6]
        if ln == 0 and crc == 0:
            break
        pos += 7
        if pos + ln > len(data):
            pos -= 7
            break
        payload = data[pos:pos+ln]
        pos += ln
        if crc_masked(typ, payload) != crc:
            pos -= (7 + ln)
            break
        last_end = pos
    return data, last_end

def build_records(payload, ap):
    BLOCK = 32768
    records = []
    cur = ap
    off = 0
    n = len(payload)
    while off < n:
        space = BLOCK - (cur % BLOCK)
        if space < 7:
            raise ValueError('record would not fit: space=%d' % space)
        avail = space - 7
        chunk = payload[off:off+avail]
        if off == 0 and len(chunk) == n:
            typ = 1
        elif off == 0:
            typ = 2
        elif off + len(chunk) < n:
            typ = 3
        else:
            typ = 4
        header = struct.pack('<I', crc_masked(typ, chunk)) + struct.pack('<H', len(chunk)) + bytes([typ])
        records.append(header + chunk)
        cur += 7 + len(chunk)
        off += len(chunk)
    return records, cur

if __name__ == '__main__':
    dbdir = r'C:\Users\31138\AppData\Roaming\Minecraft Bedrock\Users\16885677904858126412\games\com.mojang\minecraftWorlds\481i79mrEfs=\db'
    log = os.path.join(dbdir, os.environ.get('MC_LOG', '000225.log'))
    val = open(r'D:\deepseek_workplace\player_new.raw','rb').read()
    key = b'~local_player'
    seq = int(sys.argv[1]) if len(sys.argv) > 1 else 2000000
    batch = make_batch(seq, [(key, val)])
    print('seq =', seq)
    print('batch payload bytes:', len(batch))
    data, last_end = scan_log_end(log)
    print('log size=%d last_record_end=%d' % (len(data), last_end))
    ap = last_end
    if ap % 32768 != 0:
        block_end = (ap // 32768 + 1) * 32768
        if block_end > len(data):
            tail = data[ap:len(data)]
        else:
            tail = data[ap:block_end]
        if tail.strip(b'\x00'):
            print('WARNING: non-zero tail after last record:', tail[:16].hex())
    records, end = build_records(batch, ap)
    print('records: %d, sizes=%s, end_offset=%d' % (len(records), [len(r) for r in records], end))
    blob = b''.join(records)
    with open(log, 'r+b') as f:
        f.seek(ap)
        f.write(blob)
    print('write OK, new size', os.path.getsize(log))
