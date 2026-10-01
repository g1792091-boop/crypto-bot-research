"""결과·다운로드 — 사무실이 만든 모든 결과를 파일로 모으고, 화면에서 받거나 폴더를 연다.

저장 위치: {STATE_DIR}/office/files/  (데스크톱 앱이면 실행 파일 옆 state 폴더 안)
  pipeline.csv            매매법 파이프라인 (개발 → 백테스트 → 데모 → 실거래 승인 대기)
  backtests/*.json        백테스트 카드 (전략 JSON · 70/30 · 시나리오)
  research.csv            퀀트 연구소 연구 기록
  forecasts.csv           24시간 방향 예측 장부와 채점
  ml.csv                  머신러닝·딥러닝 실험 결과
  teams/{팀}/{날짜}.md    팀별 분석 노트 (자료 + 팀원 해설)
  boards/*.csv            코인별 상황표
  reports/*.md            일일·시간별 보고서
  trades.csv · strategies/*.json   시그널 추적(가상 체결) 거래와 전략
  meetings.md             최근 회의록
"""
from __future__ import annotations

import csv
import io
import os
import platform
import subprocess
import time
import zipfile
from datetime import datetime
from pathlib import Path

from . import engine as E
from . import roster

CATS = [("pipeline.csv", "매매법 파이프라인"), ("backtests", "백테스트 결과"), ("research.csv", "퀀트 연구 기록"), ("forecasts.csv", "방향 예측 장부"),
        ("ml.csv", "머신러닝 결과"), ("teams", "팀별 분석 노트"), ("boards", "코인별 상황표"), ("reports", "보고서"), ("trades.csv", "가상 체결 거래"),
        ("strategies", "전략 파일"), ("meetings.md", "회의록"), ("live_log.csv", "실거래 기록")]


def root() -> Path:
    d = E._dir() / "files"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _csv(path: Path, rows: list[list]) -> None:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8-sig")         # 엑셀에서 한글이 깨지지 않게 BOM


def refresh() -> None:
    """메모리에 있는 기록을 파일로 다시 쓴다 (목록을 열 때마다)."""
    r = root()
    _csv(r / "research.csv", [["time", "name", "market", "tf", "pass", "oos_ret", "grade", "author"]] + [
        [datetime.fromtimestamp(x["t"]).strftime("%Y-%m-%d %H:%M"), x["name"], x["market"], x["tf"], x["pass"], x.get("oos"), x.get("grade"),
         roster.BY_ID.get(x.get("author") or "", {}).get("name", x.get("author"))] for x in E.ST.get("research", [])])
    _csv(r / "forecasts.csv", [["made", "due", "asset", "dir", "prob", "p0", "by", "result", "ret_pct", "paper_pct"]] + [
        [datetime.fromtimestamp(f["t"]).strftime("%Y-%m-%d %H:%M"), datetime.fromtimestamp(f["due"]).strftime("%Y-%m-%d %H:%M"), f["asset"], f["dir"], f["prob"],
         f["p0"], roster.BY_ID.get(f["by"], {}).get("name", f["by"]), f.get("result"), f.get("ret"), f.get("paper")] for f in E.ST.get("forecasts", [])])
    _csv(r / "ml.csv", [["time", "market", "tf", "model", "accuracy", "baseline", "auc", "edge"]] + [
        [datetime.fromtimestamp(e["t"]).strftime("%Y-%m-%d %H:%M"), e["market"], e["tf"], e["model"], e["acc"], e["base"], e["auc"], e["edge"]]
        for e in E.LOG if e["kind"] == "ml"])
    lines = []
    for e in E.LOG[-400:]:
        if e["kind"] in ("agent", "user", "divider", "system") and not e.get("chat"):
            who = "나" if e["kind"] == "user" else roster.BY_ID.get(e.get("agent") or "", {}).get("name", "")
            team = roster.TEAM_BY.get(e["ch"], {}).get("name", e["ch"])
            lines.append(f"**{datetime.fromtimestamp(e['t']):%m-%d %H:%M} #{team} {who}** {e.get('text') or ''}")
    (r / "meetings.md").write_text("# 최근 회의록\n\n" + "\n\n".join(lines), encoding="utf-8")
    try:
        from .. import live as livex
        _csv(r / "live_log.csv", [["time", "text"]] + [[datetime.fromtimestamp(x["t"]).strftime("%Y-%m-%d %H:%M:%S"), x["text"]] for x in livex.LOG])
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import teamjobs
        teamjobs._export_pipeline()
    except Exception:  # noqa: BLE001
        pass


def listing() -> dict:
    refresh()
    r = root()
    files = []
    for p in sorted(r.rglob("*")):
        if p.is_file():
            rel = p.relative_to(r).as_posix()
            top = rel.split("/")[0]
            cat = next((name for key, name in CATS if key == top), "기타")
            files.append({"path": rel, "category": cat, "size": p.stat().st_size, "mtime": p.stat().st_mtime})
    files.sort(key=lambda f: -f["mtime"])
    return {"root": str(r.resolve()), "files": files, "categories": [name for _, name in CATS],
            "can_open": os.environ.get("APP_MODE") != "server" and not os.environ.get("APP_PASSWORD")}


def safe_path(rel: str) -> Path:
    r = root().resolve()
    p = (r / rel).resolve()
    if r not in p.parents and p != r:
        raise ValueError("폴더 밖 파일은 받을 수 없습니다")
    if not p.is_file():
        raise ValueError("파일이 없습니다")
    return p


def zip_all() -> Path:
    refresh()
    r = root()
    out = E._dir() / f"GHQuant_결과_{datetime.now():%Y%m%d_%H%M}.zip"
    for old in E._dir().glob("GHQuant_결과_*.zip"):
        if time.time() - old.stat().st_mtime > 600:
            old.unlink(missing_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in r.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(r).as_posix())
    return out


def open_folder() -> str:
    """이 컴퓨터의 파일 탐색기로 결과 폴더를 연다 (데스크톱 앱에서만)."""
    if os.environ.get("APP_PASSWORD"):
        raise ValueError("서버 모드에서는 폴더를 열 수 없습니다. '전체 ZIP 받기' 를 쓰세요.")
    path = str(root().resolve())
    sysname = platform.system()
    if sysname == "Windows":
        os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
    elif sysname == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
    return path
