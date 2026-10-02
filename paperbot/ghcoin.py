"""GH Coin call recorder: reader (docs/ghcoin-recorder.md).

The recorder (ghcoin/recorder.mjs, service paperbot-ghcoin) runs GH Coin's own combo engine unchanged and writes
calls.jsonl, board.json and state.json. This module only reads them: totals per coin, gross and net R, and the
coin-flip comparison. Each call has a mirror (the other side, same entry and distances), so a coin flip at the
same times would have made the call or its mirror with equal odds: the p-value is the share of random side
choices (one per finished call) whose net R sum is at least GH Coin's own.

    python -m paperbot.ghcoin report [--dir /var/lib/paperbot/ghcoin] [--since 2026-10-03]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from typing import Optional

import numpy as np

DEFAULT_DIR = "/var/lib/paperbot/ghcoin"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
RESULT_KO = {"win": "익절1", "loss": "손절", "expire": "24시간 만료", "flip": "반대 신호"}
STATE_KO = {"long": "롱 타점", "short": "숏 타점", "longWait": "롱 대기", "shortWait": "숏 대기", "wait": "관망"}
STALE_MS = 15 * 60_000


def read_events(path: str) -> list[dict]:
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue            # a torn last line while the recorder writes
    except OSError:
        return []
    return out


def pairs(events: list[dict], since_ms: Optional[int] = None) -> tuple[list[dict], int]:
    """Finished (call, mirror) pairs opened at or after ``since_ms``; also the number of calls still open."""
    opened, closed = {}, {}
    for e in events:
        if e.get("ev") == "open":
            opened[e["id"]] = e
        elif e.get("ev") == "close":
            closed[e["id"]] = e
    out, still_open = [], 0
    for cid, c in opened.items():
        if c.get("mirror") or (since_ms is not None and c["t"] < since_ms):
            continue
        a, m = closed.get(cid), closed.get(cid + "-m")
        if a is None or m is None:
            still_open += 1
            continue
        out.append({"id": cid, "sym": c["sym"], "side": c["side"], "t": c["t"], "end": a.get("end"),
                    "result": a["result"], "r": a["r"], "net_r": a["net_r"], "m_net_r": m["net_r"],
                    "cost_r": c.get("cost_r")})
    return out, still_open


def coin_flip_p(net: np.ndarray, mirror: np.ndarray, n: int = 20_000, seed: int = 7) -> Optional[float]:
    """Share of random side choices whose net R sum >= the actual one (one-sided, +1 smoothing)."""
    if len(net) == 0:
        return None
    rng = np.random.default_rng(seed)
    actual = float(net.sum())
    picks = rng.integers(0, 2, size=(n, len(net)), dtype=np.int8)
    sums = np.where(picks == 1, net, mirror).sum(axis=1)
    return float((1 + np.count_nonzero(sums >= actual - 1e-12)) / (n + 1))


def summarize(rows: list[dict]) -> dict:
    if not rows:
        return {"calls": 0}
    net = np.array([r["net_r"] for r in rows], dtype=float)
    mir = np.array([r["m_net_r"] for r in rows], dtype=float)
    gross = np.array([r["r"] for r in rows], dtype=float)
    res = {}
    for r in rows:
        res[r["result"]] = res.get(r["result"], 0) + 1
    return {"calls": len(rows), "results": res,
            "win_rate": round(sum(1 for x in net if x > 0) / len(rows), 4),
            "gross_r": round(float(gross.sum()), 3), "net_r": round(float(net.sum()), 3),
            "net_r_per_call": round(float(net.mean()), 4),
            "coin_flip_net_r": round(float(((net + mir) / 2).sum()), 3),
            "p_coin_flip": coin_flip_p(net, mir)}


def report(directory: str = DEFAULT_DIR, since_ms: Optional[int] = None, now_ms: Optional[int] = None) -> dict:
    rows, still_open = pairs(read_events(os.path.join(directory, "calls.jsonl")), since_ms)
    board = None
    try:
        with open(os.path.join(directory, "board.json"), encoding="utf-8") as fh:
            board = json.load(fh)
    except (OSError, ValueError):
        pass
    now_ms = now_ms if now_ms is not None else int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    alive = bool(board) and now_ms - int(board.get("ts") or 0) <= STALE_MS
    return {"total": summarize(rows), "open": still_open, "since": since_ms,
            "by_coin": {s: summarize([r for r in rows if r["sym"] == s]) for s in SYMBOLS},
            "board": board, "alive": alive, "commit": (board or {}).get("commit")}


def text(rep: dict) -> str:
    t = rep["total"]
    lines = [f"GH Coin 타점 기록기 ({'작동 중' if rep['alive'] else '멈춤 또는 아직 시작 전'}, GH Coin 커밋 {rep.get('commit') or '?'})"]
    if not t.get("calls"):
        lines.append(f"끝난 타점이 아직 없습니다 (열린 타점 {rep['open']}개).")
        return "\n".join(lines)
    res = ", ".join(f"{RESULT_KO.get(k, k)} {v}" for k, v in sorted(t["results"].items()))
    lines.append(f"끝난 타점 {t['calls']}개 ({res}), 열린 타점 {rep['open']}개")
    lines.append(f"수익 낸 비율 {t['win_rate'] * 100:.1f}% · 합계 {t['gross_r']:+.2f}R (수수료 전) · "
                 f"{t['net_r']:+.2f}R (수수료·미끄러짐 뒤, 타점당 {t['net_r_per_call']:+.3f}R)")
    p = t["p_coin_flip"]
    lines.append(f"같은 시각 동전 던지기 평균 {t['coin_flip_net_r']:+.2f}R · 동전보다 나을 확률 검사 p={p:.4f} "
                 f"({'우연보다 낫다고 볼 근거 있음' if p is not None and p < 0.05 else '우연과 구별 안 됨'})")
    for s, v in rep["by_coin"].items():
        if v.get("calls"):
            lines.append(f"  {s}: {v['calls']}개, {v['net_r']:+.2f}R (동전 {v['coin_flip_net_r']:+.2f}R)")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.ghcoin")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", help="totals and the coin-flip comparison")
    r.add_argument("--dir", default=DEFAULT_DIR)
    r.add_argument("--since", default=None, help="UTC date (YYYY-MM-DD): only calls opened from then")
    r.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    since = None
    if a.since:
        since = int(dt.datetime.strptime(a.since, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    rep = report(a.dir, since)
    print(json.dumps(rep, ensure_ascii=False, indent=1) if a.json else text(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
