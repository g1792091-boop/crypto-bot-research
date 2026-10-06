"""청산 이유 (ana-syn, 분석 › 청산 이유): per group, how the trades ended and how far price went against / for them before
the exit. Read-only on paper3.db; descriptive, not a verdict.

    GET /api/v4/exits?group=core|ds200|reel      (default core = the 36; dash/analysis.an_group checks it)

Each group is read on its own timeframes next to ITS coin flips (dash/analysis.own_tfs: the 36 and DeepSeek on 15m-4h
against the core coin flips, the reel on 5m against the three 5m coin flips), closed trades since the run start.

- ``reasons``  one row per exit reason that really occurs (trades.exit_reason): 손절 (SL), each step of the profit lock
               (LOCK, by the trade's ``lock_roe``: +10%, +15%, ... ; from step ``LOCK_ROWS`` on one row), 목표가 (TP), 시간
               청산 (TIME), 강제청산 (LIQ), and the rare ones (HALT, END, EOD, MANUAL; an unknown code is shown as it is):
               trades, share of the group's trades, win share (P&L > 0), mean net ROE (on margin, after costs). The
               same row for the coin flips. ``busts``: trades after which the account fell under the bust line
               (equity_after < Settings.bust_below).
- ``excursion`` 역행·순행 from the stored ``mae_price`` / ``mfe_price`` and ``stop_initial`` (agents/riskreward.norm_trade):
               for winners and for losers separately, the worst move against the entry as a share of the initial stop
               distance |entry - stop_initial| in buckets 0-25 / 25-50 / 50-75 / 75-100 / 100%+; the share of winners
               that came within 80% of their stop first (``near_stop``); the losers' best move in R (R = the initial
               stop distance) in buckets 0-0.25 / 0.25-0.5 / 0.5-1 / 1R+, its median and the share that reached 1R.
               A trade without stop_initial is counted in ``no_stop`` and left out.

DeepSeek (owners' D10 / D11, CONTRACT.md section 1): counts and shares only; no ROE and no R magnitude (``NO_MONEY``
keys are left out at the source for the group AND its coin-flip line; ``no_money: true``).
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
from typing import Any, Optional

TTL_S = 600
WAIT_S = 3.0
LABEL = "설명용, 판정 아님"
MIN_TRADES = 20               # a group's closed trades before the reasons table is shown (a filling bar before)
MIN_SIDE = 10                 # winners / losers with a known stop before an excursion chart is shown
LOCK_ROWS = 5                 # lock steps shown one by one; from this step on, one row ('+30% 이상')
NEAR_STOP = 0.8
MAE_EDGES = ((0.0, 0.25, "0~25%"), (0.25, 0.5, "25~50%"), (0.5, 0.75, "50~75%"), (0.75, 1.0, "75~100%"),
             (1.0, None, "100% 이상"))
MFE_EDGES = ((0.0, 0.25, "0~0.25R"), (0.25, 0.5, "0.25~0.5R"), (0.5, 1.0, "0.5~1R"), (1.0, None, "1R 이상"))
REASON_KO = {"SL": "손절", "TP": "목표가 익절", "TIME": "시간 청산", "LIQ": "강제청산", "HALT": "계좌 멈춤 정리",
             "END": "실험 끝 정리", "EOD": "자료 끝 정리", "MANUAL": "수동 청산"}
REEL_KO = {"TP": "목표가 익절 (볼린저 윗밴드)", "TIME": "시간 청산 (96봉)"}
ORDER = ("SL", "LOCK", "TP", "TIME", "LIQ", "HALT", "END", "EOD", "MANUAL")
NO_MONEY = ("mean_roe", "median_mfe_r")       # what a DeepSeek answer never carries (with dash/analysis.MONEY_KEYS)


def _r(x: Any, n: int = 4) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, n) if math.isfinite(v) else None


def lock_key(lock_roe: Any, first: float, step: float) -> tuple[str, int]:
    """('LOCK<k>', k) for a lock at ``lock_roe`` (k = 1 for the first lock); steps >= LOCK_ROWS share one key."""
    try:
        v = float(lock_roe)
    except (TypeError, ValueError):
        return "LOCK?", 99
    k = int(round((v - first) / step)) + 1 if step > 0 else 1
    k = max(1, k)
    return (f"LOCK{k}", k) if k < LOCK_ROWS else (f"LOCK{LOCK_ROWS}+", LOCK_ROWS)


def reason_label(key: str, first: float, step: float, reel: bool) -> str:
    if key.startswith("LOCK"):
        if key == "LOCK?":
            return "익절 잠금 (단계 기록 없음)"
        k = int(key[4:].rstrip("+"))
        roe = round((first + step * (k - 1)) * 100)
        return f"익절 잠금 {k}단계 (+{roe}%)" + (" 이상" if key.endswith("+") else "")
    if reel and key in REEL_KO:
        return REEL_KO[key]
    return REASON_KO.get(key, f"기타 ({key})")


def _sort_key(key: str) -> tuple:
    base = "LOCK" if key.startswith("LOCK") else key
    i = ORDER.index(base) if base in ORDER else len(ORDER)
    sub = 0
    if base == "LOCK":
        sub = 99 if key == "LOCK?" else int(key[4:].rstrip("+"))
    return (i, sub, key)


def read(c: sqlite3.Connection, kinds: tuple, tfs: tuple, since_ms: int, round_trip: float) -> list[dict]:
    """The closed trades of ``kinds`` on ``tfs`` (exit at or after ``since_ms``): win, roe, reason, lock_roe, the
    excursions (agents/riskreward.norm_trade's mae_stop; the best move in R from mfe_price), equity after."""
    from ...agents.riskreward import norm_trade
    q = ("SELECT t.exit_reason, t.pnl, t.roe, t.equity_after, t.data FROM trades t JOIN accounts a "
         f"ON a.account_id = t.account_id WHERE a.kind IN ({','.join('?' * len(kinds))}) "
         f"AND a.timeframe IN ({','.join('?' * len(tfs))}) AND t.exit_time >= ? ORDER BY t.exit_time, t.id")
    out = []
    for reason, pnl, roe, eqa, data in c.execute(q, (*kinds, *tfs, int(since_ms))):
        try:
            d = json.loads(data) or {}
        except (TypeError, ValueError):
            d = {}
        if not isinstance(d, dict) or pnl is None:
            continue
        nt = norm_trade({**d, "pnl": pnl, "roe": roe}, round_trip) or {}
        mfe_r = None
        try:
            side, entry, best, stop0 = int(d.get("side") or 0), float(d["entry_price"]), float(d["mfe_price"]), \
                float(d["stop_initial"])
            if side in (1, -1) and entry > 0 and best > 0 and abs(entry - stop0) > 0:
                mfe_r = max(0.0, side * (best - entry) / abs(entry - stop0))
        except (KeyError, TypeError, ValueError):
            mfe_r = None
        out.append({"reason": str(reason or d.get("exit_reason") or "?"), "lock_roe": d.get("lock_roe"),
                    "win": float(pnl) > 0, "roe": None if roe is None else float(roe),
                    "eq_after": None if eqa is None else float(eqa), "mae_stop": nt.get("mae_stop"), "mfe_r": mfe_r})
    return out


def reason_rows(trades: list, first: float, step: float) -> dict:
    """{key: {"trades", "share", "win_rate", "mean_roe"}} per exit reason (LOCK split by step)."""
    n = len(trades)
    per: dict = {}
    for t in trades:
        k = lock_key(t["lock_roe"], first, step)[0] if t["reason"] == "LOCK" else t["reason"]
        per.setdefault(k, []).append(t)
    out = {}
    for k, xs in per.items():
        roe = [x["roe"] for x in xs if x["roe"] is not None]
        out[k] = {"trades": len(xs), "share": _r(len(xs) / n, 4) if n else None,
                  "win_rate": _r(sum(1 for x in xs if x["win"]) / len(xs), 4),
                  "mean_roe": _r(sum(roe) / len(roe), 4) if roe else None}
    return out


def buckets(vals: list, edges: tuple) -> list:
    n = len(vals)
    out = []
    for lo, hi, label in edges:
        m = sum(1 for v in vals if v >= lo - 1e-12 and (hi is None or v < hi - 1e-12))
        out.append({"label": label, "n": m, "share": _r(m / n, 4) if n else None})
    return out


def excursion(trades: list) -> dict:
    """역행·순행 of one set of closed trades (see the module doc)."""
    win = [t["mae_stop"] for t in trades if t["win"] and t["mae_stop"] is not None]
    los = [t for t in trades if not t["win"] and t["mae_stop"] is not None]
    lmae = [t["mae_stop"] for t in los]
    lmfe = sorted(t["mfe_r"] for t in los if t["mfe_r"] is not None)
    near = sum(1 for v in win if v >= NEAR_STOP - 1e-12)
    deep = sum(1 for v in lmae if v >= 0.75 - 1e-12)
    one_r = sum(1 for v in lmfe if v >= 1.0 - 1e-12)
    med = None
    if lmfe:
        m = len(lmfe)
        med = lmfe[m // 2] if m % 2 else (lmfe[m // 2 - 1] + lmfe[m // 2]) / 2
    return {"winners": {"n": len(win), "mae": buckets(win, MAE_EDGES), "near_stop": _r(near / len(win), 4) if win else None,
                        "near_n": near, "small": len(win) < MIN_SIDE},
            "losers": {"n": len(lmae), "mae": buckets(lmae, MAE_EDGES), "deep": _r(deep / len(lmae), 4) if lmae else None,
                       "mfe_n": len(lmfe), "mfe": buckets(lmfe, MFE_EDGES),
                       "one_r": _r(one_r / len(lmfe), 4) if lmfe else None, "median_mfe_r": _r(med, 3),
                       "small": len(lmae) < MIN_SIDE},
            "no_stop": sum(1 for t in trades if t["mae_stop"] is None)}


def _strip(x: Any) -> Any:
    """``x`` without the NO_MONEY keys and dash/analysis.MONEY_KEYS (a DeepSeek answer)."""
    from ..analysis import no_money
    x = no_money(x)
    if isinstance(x, dict):
        return {k: _strip(v) for k, v in x.items() if k not in NO_MONEY}
    if isinstance(x, list):
        return [_strip(v) for v in x]
    return x


def exits_view(paper_db: str, now_ms: int, group: str = "core") -> dict:
    from ...agents import riskreward as RR
    from ...agents.triggers import run_start
    from ...config import v3_settings
    from ..analysis import AN_GROUP_KINDS, NO_MONEY_GROUPS, _close, own_tfs, ro_connect
    kinds, tfs = AN_GROUP_KINDS[group], own_tfs(group)
    reel = group == "reel"
    lad = RR.ladder()
    first, step = float(lad["first_lock"]), float(lad["step"])
    out: dict = {"group": group, "label": LABEL, "house_exits": not reel, "min_trades": MIN_TRADES, "min_side": MIN_SIDE,
                 "near_stop": NEAR_STOP, "lock": None if reel else {"first": first, "step": step,
                                                                    "first_trigger": lad["first_trigger"]}}
    c = ro_connect(paper_db)
    if c is None:
        out["error"] = "paper3.db 없음"
        return out
    try:
        start = int(run_start(c) or 0)
        rt = RR.round_trip_of(c)
        mine = read(c, kinds, tfs, start, rt)
        flips = read(c, ("random",), tfs, start, rt)
    except sqlite3.Error as exc:
        out["error"] = f"paper3.db를 읽지 못함: {type(exc).__name__}"
        return out
    finally:
        _close(c)
    bust_below = float(v3_settings().bust_below or 0.0)
    a, f = reason_rows(mine, first, step), reason_rows(flips, first, step)
    keys = sorted(set(a) | set(f), key=_sort_key)
    out.update({"since": start, "trades": len(mine), "flip_trades": len(flips),
                "reasons": [{"key": k, "ko": reason_label(k, first, step, reel), "group": a.get(k, {"trades": 0}),
                             "coin_flips": f.get(k, {"trades": 0})} for k in keys],
                "busts": sum(1 for t in mine if t["eq_after"] is not None and t["eq_after"] < bust_below),
                "flip_busts": sum(1 for t in flips if t["eq_after"] is not None and t["eq_after"] < bust_below),
                "excursion": {"group": excursion(mine), "coin_flips": excursion(flips)},
                "win_rate": _r(sum(1 for t in mine if t["win"]) / len(mine), 4) if mine else None,
                "flip_win_rate": _r(sum(1 for t in flips if t["win"]) / len(flips), 4) if flips else None})
    if len(mine) < MIN_TRADES:
        out["waiting"] = True
    if group in NO_MONEY_GROUPS:
        out = _strip(out)
        out["no_money"] = True
    return out


def register(app, ctx) -> dict:
    from ..analysis import Heavy, an_group
    heavy = getattr(app.state, "analysis", None)
    if not isinstance(heavy, Heavy):
        heavy = Heavy()

    @app.get("/api/v4/exits")
    def get_exits(group: Optional[str] = None):
        """청산 이유 + 역행·순행 for one group (?group=core|ds200|reel); background + cached ``TTL_S``."""
        g = an_group(group)
        return heavy.get(f"exits:{g}", TTL_S, lambda: exits_view(ctx.db, int(time.time() * 1000), g), wait_s=WAIT_S)

    return {"routes": ["/api/v4/exits"]}
