"""규칙봇의 나머지 기록 내보내기 (읽기 전용) — 10/19 분석 보충용.

    sudo python3 ex_export.py            # → /root/extra_export_<UTC 날짜시각>.zip

/var/lib/paperbot 와 /var/lib 아래 다른 봇 폴더의 *.db 를 sqlite backup으로 복사해 넣습니다. 커스텀값 그림자(paramshadow),
매일 점검(daily3), 30일 판정(checkpoint), 에이전트 회의(agents3), 아이디어함(inbox), 토론방(debate), 그림자 리그(shadow_league),
GH Coin 기록, 테스트넷 실행기 기록 등. 이미 받은 paper3.db와, 시세만 담은 큰 파일(liq, market, bars, flow, ctx)은 뺍니다.
파일 하나가 400MB를 넘으면 빼고 목록에만 적습니다. 원본은 mode=ro 로만 엽니다. 키·토큰이 든 설정 파일(.env, .json)은 넣지 않습니다.
"""
import glob
import os
import sqlite3
import tempfile
import time
import zipfile

OUT = os.environ.get("EX_OUT", f"/root/extra_export_{time.strftime('%Y%m%d_%H%M', time.gmtime())}.zip")
ROOTS = ["/var/lib/paperbot"] + [d for d in glob.glob("/var/lib/*/") if any(k in d for k in ("ghcoin", "gh", "hunt", "demobot"))]
SKIP_NAMES = ("paper3.db", "liq.db", "market.db", "flow.db", "ctx.db")
SKIP_PREFIX = ("bars",)
CAP = 400 * 1024 * 1024
log = []


def backup_copy(src: str, dst: str) -> None:
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=60)
    d = sqlite3.connect(dst)
    s.backup(d)
    d.close()
    s.close()


seen = set()
with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for root in ROOTS:
        for p in sorted(glob.glob(os.path.join(root, "**", "*.db"), recursive=True)):
            rp = os.path.realpath(p)
            if rp in seen:
                continue
            seen.add(rp)
            name = os.path.basename(p)
            size = os.path.getsize(p)
            rel = os.path.relpath(p, "/var/lib")
            if name in SKIP_NAMES or name.startswith(SKIP_PREFIX) or "/archive/" in p:
                log.append(f"건너뜀(대상 아님) {rel}: {size:,}")
                continue
            if size > CAP:
                log.append(f"건너뜀(너무 큼) {rel}: {size:,}")
                continue
            try:
                dst = os.path.join(tmp, "x.db")
                backup_copy(p, dst)
                z.write(dst, f"db/{rel}")
                log.append(f"넣음 {rel}: {os.path.getsize(dst):,}")
                os.remove(dst)
            except Exception as e:  # noqa: BLE001
                log.append(f"실패 {rel}: {type(e).__name__}: {e}")
    z.writestr("manifest.txt", "\n".join([time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())] + ROOTS + log) + "\n")
print("\n".join(log))
print(f"\n완료: {OUT}  ({os.path.getsize(OUT) / 1e6:.1f} MB)")
