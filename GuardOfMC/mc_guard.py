# -*- coding: utf-8 -*-
# MC Guard - 单机版 MC 极限模式守护程序
# 功能: 实时检测死亡 -> 自动快照 -> 游戏关闭后自动复活(保留全部物品) 或 自动回滚到死前快照
# 每5分钟滚动快照(保留12份) + 死亡快照(保留5份)
import os, sys, time, shutil, struct, ctypes, winsound, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from nbt_tool import (parse_level_dat, find, set_entry, enc_level_dat, Reader, read_string,
                      read_payload, enc_string, enc_payload,
                      TAG_BYTE, TAG_INT, TAG_SHORT, TAG_FLOAT, TAG_LIST,
                      TAG_COMPOUND)
from parse_log import crc32c, parse_batch
from append_batch import scan_log_end, build_records, make_batch
from analyze2 import rvar, parse_manifest, read_log_seq

# ================= 配置 =================
# 世界路径优先读取同目录下的 world-path.txt(一行一个完整路径), 便于复制到其他电脑使用
def _load_world_path():
    cfg = os.path.join(HERE, 'world-path.txt')
    try:
        with open(cfg, 'r', encoding='utf-8') as f:
            p = f.read().strip()
            if p:
                return p
    except Exception:
        pass
    return ''
WORLD = _load_world_path()
SNAPDIR = os.path.join(HERE, 'snapshots')
DEATHDIR = os.path.join(HERE, 'death-snapshots')
QUARANTINE = os.path.join(HERE, 'quarantine')
LOGFILE = os.path.join(HERE, 'guard-log.txt')
LOCKFILE = os.path.join(HERE, 'guard.lock')
PENDING = os.path.join(HERE, 'pending-fix.bin')
SNAP_INTERVAL = 300
POLL = 3
KEEP = 12
KEEP_DEATH = 5
# 复活方式: True=仍在极限模式内复活(生存); False=解锁极限并改为创造
REVIVE_KEEP_HARDCORE = True
REVIVE_MODE = 0          # 0=生存(显式) 1=创造
SEQ_MARGIN = 100000
# ========================================

def log(msg):
    try:
        with open(LOGFILE, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + msg + '\n')
    except Exception:
        pass

def popup(title, text):
    try:
        winsound.MessageBeep()
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)
    except Exception as e:
        log('popup fail: %s' % e)

def game_running():
    try:
        r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq Minecraft*', '/FO', 'CSV'],
                           capture_output=True, timeout=10)
        out = (r.stdout or b'').decode('gbk', 'replace')
        return 'Minecraft' in out and 'INFO' not in out
    except Exception:
        return False

def get_flags():
    try:
        p = os.path.join(WORLD, 'level.dat')
        ver, ln, name, t, root = parse_level_dat(p)
        hc = find(root, 'IsHardcore')
        phd = find(root, 'PlayerHasDied')
        gt = find(root, 'GameType')
        return (hc[1] if hc else 0), (phd[1] if phd else 0), (gt[1] if gt else 0)
    except Exception:
        return None

def latest_log_info():
    cur = open(os.path.join(WORLD, 'db', 'CURRENT')).read().strip()
    lognum, lastseq = parse_manifest(os.path.join(WORLD, 'db', cur))
    return lognum, lastseq

def grab_from_log():
    try:
        lognum, lastseq = latest_log_info()
        logpath = os.path.join(WORLD, 'db', '%06d.log' % lognum)
        results, bad = read_log_seq(logpath, b'~local_player')
        if results:
            return results[-1][2]
    except Exception as e:
        log('grab_from_log error: %s' % e)
    return None

def grab_from_tables():
    from sst_scan import scan_table
    try:
        dbdir = os.path.join(WORLD, 'db')
        best = None
        for f in sorted(os.listdir(dbdir)):
            if f.endswith('.ldb'):
                r = scan_table(os.path.join(dbdir, f), b'~local_player')
                if r and r[0]:
                    seq, vt, v = r[0]
                    if best is None or seq > best[0]:
                        best = (seq, v)
        if best:
            return best[1]
    except Exception as e:
        log('grab_from_tables error: %s' % e)
    return None

def edit_player(raw):
    r = Reader(raw)
    t = r.u8(); name = read_string(r); root = read_payload(r, t, 0)
    mode = 0 if REVIVE_MODE == 5 else REVIVE_MODE
    set_entry(root, 'PlayerGameMode', TAG_INT, mode)
    set_entry(root, 'Dead', TAG_BYTE, 0)
    set_entry(root, 'DeathTime', TAG_SHORT, 0)
    # 清除残留的创造能力标志(修复"生存模式物品不消耗"问题)
    try:
        ab = find(root, 'abilities')
        if ab and ab[0] == TAG_COMPOUND:
            for k in ('instabuild', 'invulnerable', 'mayfly', 'flying'):
                kt, kv = find(ab[1], k)
                if kt == TAG_BYTE:
                    set_entry(ab[1], k, TAG_BYTE, 0)
    except Exception as e:
        log('abilities normalize failed: %s' % e)
    # 复活位置改为出生点(避免在死亡地点复活后再次遇险)
    try:
        sx = find(root, 'SpawnX')
        sy = find(root, 'SpawnY')
        sz = find(root, 'SpawnZ')
        if sx and sy and sz and sy[1] is not None and int(sy[1]) < 30000:
            set_entry(root, 'Pos', TAG_LIST, (TAG_FLOAT, [float(sx[1]) + 0.5, float(sy[1]) + 1.0, float(sz[1]) + 0.5]))
            fd = find(root, 'FallDistance')
            if fd and fd[0] == TAG_FLOAT:
                set_entry(root, 'FallDistance', TAG_FLOAT, 0.0)
            log('respawn position set to spawn point %s %s %s' % (sx[1], sy[1], sz[1]))
    except Exception as e:
        log('spawn teleport failed: %s' % e)
    att = find(root, 'Attributes')
    if att and att[0] == TAG_LIST:
        et, vals = att[1]
        for entry in vals:
            if isinstance(entry, list):
                nm = find(entry, 'Name')
                if nm and nm[1] == b'minecraft:health':
                    set_entry(entry, 'Current', TAG_FLOAT, 20.0)
                    set_entry(entry, 'Min', TAG_FLOAT, 0.0)
                    set_entry(entry, 'Max', TAG_FLOAT, 20.0)
    return bytes([t]) + enc_string(name) + enc_payload(t, root)

def patch_level_files():
    base = WORLD
    for fn in ['level.dat', 'level.dat_old']:
        p = os.path.join(base, fn)
        ver, ln, name, t, root = parse_level_dat(p)
        set_entry(root, 'PlayerHasDied', TAG_BYTE, 0)
        if not REVIVE_KEEP_HARDCORE:
            set_entry(root, 'IsHardcore', TAG_BYTE, 0)
            set_entry(root, 'GameType', TAG_INT, 1)
        open(p, 'wb').write(enc_level_dat(ver, name, t, root))

def snapshot_to(dest_dir, keep, tag):
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, time.strftime('%Y%m%d-%H%M%S'))
    os.makedirs(dest)
    state = {}
    try:
        for root, dirs, files in os.walk(WORLD):
            rel = os.path.relpath(root, WORLD)
            d = os.path.join(dest, rel)
            os.makedirs(d, exist_ok=True)
            for f in files:
                src = os.path.join(root, f)
                try:
                    st = os.stat(src)
                    shutil.copy2(src, os.path.join(d, f))
                    state[os.path.join(rel, f)] = (st.st_mtime_ns, st.st_size)
                except Exception as e:
                    log('copy fail %s: %s' % (src, e))
        for rnd in range(3):
            changed = []
            for root, dirs, files in os.walk(WORLD):
                rel = os.path.relpath(root, WORLD)
                for f in files:
                    key = os.path.join(rel, f)
                    try:
                        st = os.stat(os.path.join(root, f))
                        if key in state and (st.st_mtime_ns, st.st_size) != state[key]:
                            shutil.copy2(os.path.join(root, f), os.path.join(dest, rel, f))
                            state[key] = (st.st_mtime_ns, st.st_size)
                            changed.append(key)
                    except FileNotFoundError:
                        pass
            if not changed:
                break
        log('%s snapshot -> %s (%d files)' % (tag, dest, len(state)))
        if len(state) < 5:
            log('%s snapshot aborted: too few files (%d)' % (tag, len(state)))
            shutil.rmtree(dest, ignore_errors=True)
            return
        snaps = sorted(x for x in os.listdir(dest_dir) if x[0].isdigit())
        for old in snaps[:-keep]:
            shutil.rmtree(os.path.join(dest_dir, old), ignore_errors=True)
    except Exception as e:
        log('snapshot error: %s' % e)

def append_fix():
    lognum, lastseq = latest_log_info()
    logpath = os.path.join(WORLD, 'db', '%06d.log' % lognum)
    val = open(PENDING, 'rb').read()
    seq = lastseq + SEQ_MARGIN
    batch = make_batch(seq, [(b'~local_player', val)])
    data, last_end = scan_log_end(logpath)
    records, end = build_records(batch, last_end)
    blob = b''.join(records)
    with open(logpath, 'r+b') as f:
        f.seek(last_end)
        f.write(blob)
    log('append_fix OK: log=%06d.log seq=%d bytes=%d' % (lognum, seq, len(blob)))
    return True

def rollback_from_snapshot():
    snaps = sorted([x for x in os.listdir(SNAPDIR) if x[0].isdigit()], reverse=True)
    if not snaps:
        log('rollback: no snapshot available!')
        return False
    src = os.path.join(SNAPDIR, snaps[0])
    os.makedirs(QUARANTINE, exist_ok=True)
    qdir = os.path.join(QUARANTINE, 'broken-' + time.strftime('%Y%m%d-%H%M%S'))
    try:
        os.rename(WORLD, qdir)
    except Exception as e:
        log('quarantine move failed: %s' % e)
        return False
    try:
        shutil.copytree(src, WORLD)
        log('rollback OK: restored %s (broken world -> %s)' % (snaps[0], qdir))
        return True
    except Exception as e:
        log('rollback copy failed: %s' % e)
        try:
            os.rename(qdir, WORLD)
        except Exception:
            pass
        return False

def pid_alive(pid):
    try:
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    except Exception:
        return False

def handle_death(silent=False):
    if not silent:
        popup('MC 守护', '检测到死亡！\n\n已自动备份死亡现场。\n关闭游戏后我会自动复活你（物品全部保留）。')
    else:
        log('world already dead at startup, preparing revive quietly')
    snapshot_to(DEATHDIR, KEEP_DEATH, 'DEATH')
    val = None
    for i in range(6):
        try:
            val = grab_from_log()
        except Exception as e:
            log('grab error: %s' % e)
        if val:
            break
        time.sleep(3)
    if val:
        try:
            open(PENDING, 'wb').write(edit_player(val))
            log('player record grabbed and fixed (%d bytes)' % len(val))
            return True
        except Exception as e:
            log('edit_player failed: %s' % e)
            return False
    log('log grab failed, will try tables after game close')
    return False

def main():
    # 防止双开: 锁文件里存 PID, PID 还活着且锁新鲜才退出
    if os.path.exists(LOCKFILE):
        try:
            old = open(LOCKFILE).read().strip()
            fresh = time.time() - os.path.getmtime(LOCKFILE) < 120
            if old.isdigit() and fresh and pid_alive(int(old)):
                log('another instance seems running, exit')
                return
        except Exception:
            pass
    log('==== MC Guard started ====')
    if not WORLD:
        log('world-path.txt is empty - please configure the world path first')
        popup('MC 守护', '未配置世界路径！\n\n请用记事本打开：\n%s\\world-path.txt\n\n写入你的世界存档路径（查找方法见 使用说明.txt），保存后重新运行。' % HERE)
        return
    log('world path: %s' % WORLD)
    prev_died = None
    pending = None
    last_snap = time.time()
    last_lm = 0
    while True:
        try:
            open(LOCKFILE, 'w').write(str(os.getpid()))
            flags = get_flags()
            now = time.time()
            if flags is not None:
                hc, phd, gt = flags
                died = (hc == 1 and phd == 1)
                if prev_died is None:
                    log('initial: IsHardcore=%d PlayerHasDied=%d GameType=%d' % (hc, phd, gt))
                    if died:
                        pending = handle_death(silent=True)
                elif died and not prev_died:
                    log('!!! DEATH DETECTED !!!')
                    pending = handle_death()
                prev_died = died
                if pending is not None and not game_running():
                    time.sleep(2)
                    if not game_running():
                        ok = False
                        if os.path.exists(PENDING):
                            try:
                                ok = append_fix()
                                if ok:
                                    patch_level_files()
                                    popup('MC 守护', '复活完成！\n\n重新进入游戏即可继续（极限模式，物品全在）。')
                            except Exception as e:
                                log('append_fix failed: %s' % e)
                        if not ok:
                            # 尝试从表里抓
                            try:
                                val = grab_from_tables()
                                if val:
                                    open(PENDING, 'wb').write(edit_player(val))
                                    ok = append_fix()
                                    if ok:
                                        patch_level_files()
                                        popup('MC 守护', '复活完成！(已从数据库深层恢复)\n\n重新进入游戏即可。')
                            except Exception as e:
                                log('table fallback failed: %s' % e)
                        if not ok:
                            log('revive failed -> rollback to last snapshot')
                            if rollback_from_snapshot():
                                popup('MC 守护', '复活失败，已自动回滚！\n\n世界已恢复到死亡前最近一次快照（最多损失5分钟）。')
                            else:
                                popup('MC 守护', '复活失败且无快照可回滚！\n\n请打开 guard-log.txt 联系协助。')
                        pending = None
                        if os.path.exists(PENDING):
                            os.remove(PENDING)
            if pending is None and now - last_snap >= SNAP_INTERVAL:
                lm = None
                try:
                    lm = os.path.getmtime(os.path.join(WORLD, 'level.dat'))
                except OSError:
                    pass
                if lm is not None and lm != last_lm:
                    snapshot_to(SNAPDIR, KEEP, 'periodic')
                    last_lm = lm
                last_snap = now
        except Exception as e:
            log('loop error: %s' % e)
        time.sleep(POLL)

if __name__ == '__main__':
    main()
