"""실거래 봇 4개의 기록 내보내기 (읽기 전용) — 10/28 실거래 결과 분석용.

    cd /root/crypto-bot-research && nice -n 19 python3 -I analysis/live1028/live_export.py   # → /root/live_export_<UTC>.zip

넣는 것 (있는 것만, 없으면 목록에 '없음'):
- 실행기 기록: exec/executor-{toobit,deepcoin,wooxpro,wooxpro2,mexc,bybit}-live.db
- 친구봇(믹스 30분 봇) 실거래·모의: exec/mixchop-state.json, exec/mixchop-log.jsonl, mixchop-paper/state.json, mixchop-paper/log.jsonl
- 실행기가 따라가는 페이퍼: combo/vwap.db, combo/range.db, combo/friend.db, combo/live-ac.db, combo/live15-mexc.db
- 실거래 감시 기록: livecheck.db, liveimprove.db
- 투비트가 따라가는 규칙봇 V3.9 1시간 계좌: paper3.db에서 그 계좌의 거래·신호 줄만 CSV로 (paper3.db 통째로는 넣지 않음)
DB는 sqlite backup으로 복사합니다(원본은 mode=ro로만 엶). 설정 파일(/etc/paperbot), 키·토큰이 든 .env는 넣지 않습니다.
파일 하나가 300MB를 넘으면 빼고 목록에만 적습니다.
"""
import csv
import io
import os
import sqlite3
import tempfile
import time
import zipfile

ROOT = os.environ.get("PB_ROOT", "/var/lib/paperbot")
OUT = os.environ.get("PB_OUT", f"/root/live_export_{time.strftime('%Y%m%d_%H%M', time.gmtime())}.zip")
DBS = [f"exec/executor-{x}-live.db" for x in ("toobit", "deepcoin", "wooxpro", "wooxpro2", "mexc", "bybit")] + \
      ["combo/vwap.db", "combo/range.db", "combo/friend.db", "combo/live-ac.db", "combo/live15-mexc.db",
       "livecheck.db", "liveimprove.db"]
FILES = ["exec/mixchop-state.json", "exec/mixchop-log.jsonl", "mixchop-paper/state.json", "mixchop-paper/log.jsonl"]
V39 = ("V39_ALL@1h", "V39_ALL", "1h")
CAP = 300 * 1024 * 1024
log = []


def ro(p):
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=60)


def backup_copy(src, dst):
    s = ro(src)
    d = sqlite3.connect(dst)
    s.backup(d)
    d.close()
    s.close()


def put_csv(z, name, cur):
    head = [c[0] for c in cur.description]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(head)
    n = 0
    for r in cur:
        w.writerow(r)
        n += 1
    z.writestr(name, buf.getvalue())
    log.append(f"{name}: {n}줄")


with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for rel in DBS:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            log.append(f"{rel}: 없음")
            continue
        if os.path.getsize(p) > CAP:
            log.append(f"{rel}: {os.path.getsize(p) / 1e6:.0f}MB라 뺌")
            continue
        dst = os.path.join(tmp, "x.db")
        backup_copy(p, dst)
        z.write(dst, "db/" + rel)
        os.remove(dst)
        log.append(f"{rel}: {os.path.getsize(p) / 1e6:.1f}MB")
    for rel in FILES:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            log.append(f"{rel}: 없음")
            continue
        if os.path.getsize(p) > CAP:
            log.append(f"{rel}: {os.path.getsize(p) / 1e6:.0f}MB라 뺌")
            continue
        z.write(p, "files/" + rel)
        log.append(f"{rel}: {os.path.getsize(p) / 1e6:.2f}MB")
    p3 = os.path.join(ROOT, "paper3.db")
    if os.path.exists(p3):
        c = ro(p3)
        tabs = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "trades" in tabs:
            put_csv(z, "paper3/v39_trades.csv", c.execute("SELECT * FROM trades WHERE account_id = ?", (V39[0],)))
        if "signal_log" in tabs:
            put_csv(z, "paper3/v39_signals.csv",
                    c.execute("SELECT * FROM signal_log WHERE strategy = ? AND timeframe = ?", (V39[1], V39[2])))
        if "runs" in tabs:
            put_csv(z, "paper3/runs.csv", c.execute("SELECT * FROM runs"))
        c.close()
    else:
        log.append("paper3.db: 없음")
    z.writestr("manifest.txt", "\n".join([time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), ROOT] + log) + "\n")

print("\n".join(log))
print(f"\n완료: {OUT}  ({os.path.getsize(OUT) / 1e6:.1f} MB)")
