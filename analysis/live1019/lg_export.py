"""후보 리그(커스텀값봇) 기록 내보내기 — 읽기 전용. 10/19 실거래 전 분석용.

    sudo python3 lg_export.py            # → /root/league_export_<UTC 날짜시각>.zip

넣는 것: /var/lib/candleague 의 league_exits*.db (지금 리그 + 옆으로 치운 old_* 리그)를 sqlite backup으로 복사한 사본,
snap/ 폴더의 JSON(대시보드가 읽는 요약), /etc/candleague 의 rules.json · candidates.json, 그리고 설정 파일에서 CANDLEAGUE_
로 시작하는 줄 중 비밀이 아닌 것(START, EQUITY, MIN_LEV, DB, RULES, CANDIDATES)만.
넣지 않는 것: 텔레그램 토큰 · 키 등 다른 설정 줄 전부, bars5m.db(시세는 다시 받을 수 있음).
원본은 mode=ro 로만 엽니다. 서버의 어떤 파일도 바꾸지 않습니다.
"""
import glob
import os
import sqlite3
import tempfile
import time
import zipfile

ROOT = os.environ.get("LG_ROOT", "/var/lib/candleague")
ETC = os.environ.get("LG_ETC", "/etc/candleague")
OUT = os.environ.get("LG_OUT", f"/root/league_export_{time.strftime('%Y%m%d_%H%M', time.gmtime())}.zip")
SAFE_ENV = ("CANDLEAGUE_START", "CANDLEAGUE_EXPECT_START", "CANDLEAGUE_EQUITY", "CANDLEAGUE_MIN_LEV", "CANDLEAGUE_DB",
            "CANDLEAGUE_RULES", "CANDLEAGUE_CANDIDATES", "CANDLEAGUE_DS_MONEY")
log = []


def backup_copy(src: str, dst: str) -> None:
    """A consistent copy of a WAL database without writing next to it: sqlite's backup API from a read-only connection."""
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=60)
    d = sqlite3.connect(dst)
    s.backup(d)
    d.close()
    s.close()


with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    dbs = sorted(p for p in glob.glob(os.path.join(ROOT, "*league_exits*.db")) if not p.endswith(("-wal", "-shm")))
    for p in dbs:
        name = os.path.basename(p)
        try:
            dst = os.path.join(tmp, name)
            backup_copy(p, dst)
            z.write(dst, f"db/{name}")
            log.append(f"db/{name}: {os.path.getsize(dst):,} bytes")
            os.remove(dst)
        except Exception as e:  # noqa: BLE001
            log.append(f"db/{name}: 실패 {type(e).__name__}: {e}")
    for p in sorted(glob.glob(os.path.join(ROOT, "*league_exits*_start.json"))):
        z.write(p, f"db/{os.path.basename(p)}")
    for p in sorted(glob.glob(os.path.join(ROOT, "snap", "*.json"))):
        z.write(p, f"snap/{os.path.basename(p)}")
        log.append(f"snap/{os.path.basename(p)}: {os.path.getsize(p):,} bytes")
    for n in ("rules.json", "candidates.json"):
        p = os.path.join(ETC, n)
        if os.path.exists(p):
            z.write(p, f"etc/{n}")
    env = os.path.join(ETC, "candleague.env")
    if os.path.exists(env):
        keep = [ln.rstrip("\n") for ln in open(env, encoding="utf-8") if ln.split("=", 1)[0].strip() in SAFE_ENV]
        z.writestr("etc/candleague_env_safe.txt", "\n".join(keep) + "\n")
    z.writestr("manifest.txt", "\n".join([time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), ROOT] + log) + "\n")
print(OUT)
print("\n".join(log))
