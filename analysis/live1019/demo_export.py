"""데모 랩봇 결과 + 커스텀값 그림자 상태 내보내기 (읽기 전용) — 10/19 분석 보충용.

    sudo python3 demo_export.py          # → /root/demo_export_<UTC 날짜시각>_1.zip (20MB쯤에서 _2, _3 ... 으로 나눔)

demo.db 전체(233MB)는 올리기에 너무 커서, 분석에 쓰는 작은 부분만 담습니다.
* /var/lib/demobot/snap/ 의 스냅샷 전부: 계좌 48개 결과·거래(acct/*.json), 순위표(rank_*.npz: 설정 x 청산 13개 x 기간), 판정 등
* demo.db 의 작은 표: meta, funding, decisions, passes, depth(호가), views — 시세(bars)·신호(sigs)·신호별 결과(cells)는 뺍니다
* 커스텀값 그림자(/var/lib/paperbot/paramshadow)의 상태 파일(last.json, last.txt, error.json)과 타이머 상태
원본은 mode=ro 로만 엽니다. 설정 파일(.env)은 넣지 않습니다.
"""
import glob
import os
import sqlite3
import subprocess
import tempfile
import time
import zipfile

STAMP = time.strftime("%Y%m%d_%H%M", time.gmtime())
OUT = os.environ.get("DEMO_OUT", f"/root/demo_export_{STAMP}")
DB = os.environ.get("DEMOBOT_DB", "/var/lib/demobot/demo.db")
SNAP = os.environ.get("DEMOBOT_SNAP", "/var/lib/demobot/snap")
SHADOW = "/var/lib/paperbot/paramshadow"
SKIP_TABLES = {"bars", "sigs", "cells", "outbox", "notified"}
PART = 24 * 1024 * 1024
log = [time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())]
items = []  # (zip 안 이름, 파일 경로)


def small_db(dst: str) -> None:
    s = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=60)
    d = sqlite3.connect(dst)
    for name, sql in s.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL"):
        n = s.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
        if name in SKIP_TABLES or name.startswith("sqlite_"):
            log.append(f"표 건너뜀 {name}: {n:,}행")
            continue
        d.execute(sql)
        cols = len(s.execute(f'SELECT * FROM "{name}" LIMIT 0').description)
        d.executemany(f'INSERT INTO "{name}" VALUES ({",".join("?" * cols)})', s.execute(f'SELECT * FROM "{name}"'))
        log.append(f"표 넣음 {name}: {n:,}행")
    for name in ("bars", "cells"):
        try:
            lo, hi = s.execute(f'SELECT min(ts), max(ts) FROM "{name}"').fetchone()
            log.append(f"{name} 기간(ms): {lo} ~ {hi}")
        except sqlite3.Error:
            pass
    d.commit()
    d.close()
    s.close()


with tempfile.TemporaryDirectory() as tmp:
    for p in sorted(glob.glob(os.path.join(SNAP, "**", "*"), recursive=True)):
        if not os.path.isfile(p) or not p.endswith((".json", ".npz", ".txt")):
            continue
        size = os.path.getsize(p)
        if size > PART:
            log.append(f"건너뜀(너무 큼) snap/{os.path.relpath(p, SNAP)}: {size:,}")
            continue
        items.append((f"snap/{os.path.relpath(p, SNAP)}", p))
    log.append(f"snap 파일 {len(items)}개")
    if os.path.exists(DB):
        try:
            dst = os.path.join(tmp, "demo_small.db")
            small_db(dst)
            items.append(("db/demo_small.db", dst))
        except Exception as e:  # noqa: BLE001
            log.append(f"demo.db 실패: {type(e).__name__}: {e}")
    else:
        log.append(f"demo.db 없음: {DB}")
    for f in ("last.json", "last.txt", "error.json"):
        p = os.path.join(SHADOW, f)
        if os.path.exists(p):
            items.append((f"paramshadow/{f}", p))
    log.append("paramshadow 폴더: " + (", ".join(sorted(os.listdir(SHADOW))) if os.path.isdir(SHADOW) else "없음"))
    for cmd in (["systemctl", "list-timers", "--all", "--no-pager", "paperbot-paramshadow.timer"],
                ["systemctl", "status", "--no-pager", "-n", "30", "paperbot-paramshadow.service"]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            log.append("$ " + " ".join(cmd) + "\n" + (r.stdout + r.stderr).strip())
        except Exception as e:  # noqa: BLE001
            log.append("$ " + " ".join(cmd) + f"\n실패: {e}")

    # 압축된 크기가 20MB를 넘으면 다음 파일부터 새 zip (_2, _3 ...) — 한 파일당 25MB 아래로 올릴 수 있게
    outs, z = [], None
    for arc, p in [("manifest.txt", None)] + items:
        if z is None or z.fp.tell() > 20 * 1024 * 1024:
            if z is not None:
                z.close()
            outs.append(f"{OUT}_{len(outs) + 1}.zip")
            z = zipfile.ZipFile(outs[-1], "w", zipfile.ZIP_DEFLATED, compresslevel=9)
        if p is None:
            z.writestr(arc, "\n".join(log) + "\n")
        else:
            z.write(p, arc)
    z.close()

print("\n".join(log))
for out in outs:
    mb = os.path.getsize(out) / 1e6
    print(f"\n완료: {out}  ({mb:.1f} MB)" + ("  ← 25MB 넘음: 알려주세요" if mb > 25 else ""))
