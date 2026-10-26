import struct, sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\deepseek_workplace')
from parse_log import crc32c, parse_batch
from sst_scan import scan_table

DBDIR = r'C:\Users\31138\AppData\Roaming\Minecraft Bedrock\Users\16885677904858126412\games\com.mojang\minecraftWorlds\481i79mrEfs=\db'

def rvar(data, pos, maxb=10):
    v=0; shift=0
    for _ in range(maxb):
        b=data[pos]; pos+=1
        v |= (b & 0x7F) << shift
        if not (b & 0x80): return v, pos
        shift += 7
    return v, pos

def parse_manifest(path):
    data = open(path,'rb').read()
    lognum = None; lastseq = 0; records = []
    # manifest uses log format: 32KB blocks, crc32c header, types 1=FULL 2=FIRST 3=MIDDLE 4=LAST
    BLOCK = 32768
    nblocks = (len(data) + BLOCK - 1) // BLOCK
    frag = b''
    for bi in range(nblocks):
        block = data[bi*BLOCK:(bi+1)*BLOCK]
        pos = 0
        while pos + 7 <= len(block):
            crc = struct.unpack_from('<I', block, pos)[0]
            ln = struct.unpack_from('<H', block, pos+4)[0]
            typ = block[pos+6]
            if ln == 0 and crc == 0:
                break
            if 7 + ln > len(block) - pos:
                break
            payload = block[pos+7:pos+7+ln]
            pos += 7 + ln
            c = crc32c(bytes([typ]) + payload)
            expect = (((c >> 15) | ((c & 0x7FFFFFFF) << 17)) + 0xa282ead8) & 0xFFFFFFFF
            if expect != crc:
                break
            if typ == 1:
                records.append(payload)
            elif typ == 2:
                frag = payload
            elif typ == 3:
                frag += payload
            elif typ == 4:
                frag += payload
                records.append(frag)
    for payload in records:
        pos = 0
        while pos < len(payload):
            tag, pos = rvar(payload, pos)
            if tag == 1:
                ln, pos = rvar(payload, pos); pos += ln
            elif tag == 2:
                lognum, pos = rvar(payload, pos)
            elif tag == 3:
                _, pos = rvar(payload, pos)
            elif tag == 4:
                lastseq, pos = rvar(payload, pos)
            elif tag == 5:
                _, pos = rvar(payload, pos); ln, pos = rvar(payload, pos); pos += ln
            elif tag == 6:
                _, pos = rvar(payload, pos); _, pos = rvar(payload, pos)
            elif tag == 7:
                _, pos = rvar(payload, pos); _, pos = rvar(payload, pos); _, pos = rvar(payload, pos)
                ln, pos = rvar(payload, pos); pos += ln
                ln, pos = rvar(payload, pos); pos += ln
            elif tag == 9:
                _, pos = rvar(payload, pos)
            else:
                break
    return lognum, lastseq

def read_log_seq(path, key):
    data = open(path,'rb').read()
    pos = 0; frag = b''; results = []; bad = 0
    while pos + 7 <= len(data):
        crc = struct.unpack_from('<I', data, pos)[0]
        ln = struct.unpack_from('<H', data, pos+4)[0]
        typ = data[pos+6]
        if ln == 0 and crc == 0:
            break
        pos += 7
        if pos + ln > len(data):
            break
        payload = data[pos:pos+ln]; pos += ln
        c = crc32c(bytes([typ]) + payload)
        expect = (((c >> 15) | ((c & 0x7FFFFFFF) << 17)) + 0xa282ead8) & 0xFFFFFFFF
        if expect != crc:
            bad += 1; break
        if typ == 1:
            seq = struct.unpack_from('<Q', payload, 0)[0]
            ops = parse_batch(payload)
            if ops:
                for op,k,v in ops:
                    if k == key: results.append((seq, op, v))
        elif typ == 2:
            frag = payload
        elif typ == 3:
            frag += payload
        elif typ == 4:
            frag += payload
            seq = struct.unpack_from('<Q', frag, 0)[0]
            ops = parse_batch(frag)
            if ops:
                for op,k,v in ops:
                    if k == key: results.append((seq, op, v))
    return results, bad

if __name__ == '__main__':
    cur = open(os.path.join(DBDIR,'CURRENT')).read().strip()
    man = os.path.join(DBDIR, cur)
    lognum, lastseq = parse_manifest(man)
    print('CURRENT=%s  日志号=%s  最后序列=%d' % (cur, lognum, lastseq))
    logpath = os.path.join(DBDIR, '%06d.log' % lognum)
    results, bad = read_log_seq(logpath, b'~local_player')
    print('当前日志 %06d.log 中 ~local_player: %d 条, CRC错误=%d' % (lognum, len(results), bad))
    best = None
    for seq, op, v in results:
        print('  log: seq=%d op=%d bytes=%d' % (seq, op, len(v)))
        if best is None or seq > best[0]:
            best = (seq, v)
    for f in sorted(os.listdir(DBDIR)):
        if f.endswith('.ldb'):
            r = scan_table(os.path.join(DBDIR, f), b'~local_player')
            if r and r[0]:
                seq, vt, v = r[0]
                print('  table %s: seq=%d type=%d bytes=%d' % (f, seq, vt, len(v)))
                if best is None or seq > best[0]:
                    best = (seq, v)
    if best:
        print('最新值: seq=%d bytes=%d -> 保存到 local_player_current.raw' % (best[0], len(best[1])))
        open(r'D:\deepseek_workplace\local_player_current.raw','wb').write(best[1])
    else:
        print('未找到 ~local_player')
