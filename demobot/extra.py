"""Round-4 snapshot files for the terminal and the judgment screens (CONTRACT section 9): positions, the P&L
calendar and total P&L curve, the signal votes, the analysis splits and the live-vs-5-year table. Everything comes
from the tick's results and the engine state; nothing here changes an account."""
from __future__ import annotations

import os
import re
import time
from typing import Optional

import numpy as np

from . import accounts as A
from . import grid as G

M15 = 15 * 60 * 1000
H1 = 3600 * 1000
DAY_MS = 86400 * 1000
KST = 9 * 3600 * 1000
CURVE_MAX = 800
RECENT_MAX = 200
VOTE_BARS = 96
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PERIODS = ["2020", "2021-23", "2024-26", "2020-03", "2022-05", "2022-11"]
REASON_KO = {"stop": "손절", "lock": "잠금 익절", "liq": "강제청산", "tp": "익절", "be": "본전", "time": "시간"}
_TP_RE = re.compile(r"^tp([0-9.]+)R_sl")


def kst_day(t_ms: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime((int(t_ms) + KST) / 1000))


def _target(t: dict) -> Optional[float]:
    ex = t.get("exit_i")
    if ex is None or ex == 0:
        return None
    name = G.EXITS[ex]
    m = _TP_RE.match(name)
    tp = float(m.group(1)) if m else (1.5 if ex == G.HALFBE else None)
    if tp is None:
        return None
    return t["entry"] + t["side"] * tp * abs(t["entry"] - t["stop"])


# ------------------------------------------------------------------ 9.2 positions
def positions(eng, res: dict, now_ms: int) -> dict:
    out = []
    by = {c: dict(coin=c, long=0, short=0, unreal=0.0) for c in G.COINS}
    for a in A.current_accounts():
        r = res.get(a.id)
        if r is None:
            continue
        for L, sim in r["lines"].items():
            for t in sim["trades"]:
                if t["status"] != "open":
                    continue
                b = eng.b15.get(t["coin"])
                last = float(b["c"][-1]) if b is not None and len(b["c"]) else None
                unreal = float(t.get("unreal", t["pnl"]))
                out.append(dict(id=a.id, name=a.name, kind=a.kind, L=int(L), coin=t["coin"], side=t["side"], tf=a.tf,
                                entry_ms=t["entry_ms"], entry=t["entry"], stop=t["stop"], target=_target(t),
                                margin=t["margin"], notional=t.get("notional"), unreal=unreal, roe=t["roe"], R=t["R"],
                                last=last, stop_dist_pct=(t["side"] * (last - t["stop"]) / last * 100 if last else None),
                                held_ms=now_ms - t["entry_ms"], setting_ko=t["setting_ko"], exit_ko=t["exit_ko"]))
                c = by[t["coin"]]
                c["unreal"] += unreal
                if int(L) == 20:
                    c["long" if t["side"] > 0 else "short"] += 1
    out.sort(key=lambda p: -p["entry_ms"])
    return dict(generated_ms=now_ms, positions=out, by_coin=list(by.values()))


# ------------------------------------------------------------------ 9.3 calendar, daily per line, total curve
def calendar(res: dict, now_ms: int) -> tuple:
    """(calendar.json, {account id: daily}, equity_total, pnl_total)."""
    days: dict = {}
    daily_acct: dict = {}
    kinds = {}
    for a in A.current_accounts():
        r = res.get(a.id)
        if r is None:
            continue
        kinds.setdefault(a.kind, []).append(a.id)
        dacc: dict = {}
        for L, sim in r["lines"].items():
            per: dict = {}
            for t in sim["trades"]:
                if t["status"] != "closed" or not t["exit_ms"]:
                    continue
                d = kst_day(t["exit_ms"] - 1)
                per[d] = per.get(d, 0.0) + t["pnl"]
                if int(L) == 20:
                    e = days.setdefault(d, dict(trades=0, wins=0, line_pnl={}))
                    e["trades"] += 1
                    e["wins"] += t["pnl"] > 0
            for d, v in per.items():
                dacc.setdefault(d, {})[str(L)] = v
                days.setdefault(d, dict(trades=0, wins=0, line_pnl={}))["line_pnl"][(a.id, int(L))] = v
        daily_acct[a.id] = dacc
    names = {a.id: a.name for a in A.current_accounts()}
    from .report import KIND_KO
    out = []
    for d in sorted(days):
        e = days[d]
        lp = e["line_pnl"]
        by_kind = []
        for k, ids in kinds.items():
            vals = [lp.get((i, L), 0.0) / A.SEED * 100 for i in ids for L in G.LEVS]
            by_kind.append(dict(kind=k, kind_ko=KIND_KO.get(k, k), mean_pnl_pct=float(np.mean(vals)) if vals else None))
        best = max(lp.items(), key=lambda kv: kv[1]) if lp else None
        worst = min(lp.items(), key=lambda kv: kv[1]) if lp else None
        pub = (lambda kv: dict(id=kv[0][0], name=names.get(kv[0][0], kv[0][0]), L=kv[0][1], pnl=kv[1])
               if kv else None)
        out.append(dict(day=d, trades=e["trades"], wins=e["wins"], pnl_sum=float(sum(lp.values())),
                        lines_up=sum(1 for v in lp.values() if v > 0), lines_down=sum(1 for v in lp.values() if v < 0),
                        by_kind=by_kind, best=pub(best), worst=pub(worst)))
    eq, pnl = total_curve(res, now_ms)
    return dict(generated_ms=now_ms, days=out), daily_acct, eq, pnl


def total_curve(res: dict, now_ms: int) -> tuple:
    """Sum of every plain line's wallet curve on an hourly grid (steps: last value at or before each hour)."""
    curves = [np.asarray(sim["curve"], float) for r in res.values() for sim in r["lines"].values() if sim["curve"]]
    if not curves:
        return [], []
    t0 = min(int(c[0, 0]) for c in curves)
    grid = np.arange((t0 // H1) * H1, now_ms + H1, H1, dtype=np.int64)
    grid[-1] = min(grid[-1], now_ms)
    tot = np.zeros(len(grid))
    for c in curves:
        i = np.searchsorted(c[:, 0], grid, side="right") - 1
        tot += np.where(i >= 0, c[np.clip(i, 0, None), 1], A.SEED)
    n = len(curves)
    pts = list(zip(grid.tolist(), tot.tolist()))
    if len(pts) > CURVE_MAX:
        step = len(pts) / (CURVE_MAX - 1)
        idx = sorted({int(k * step) for k in range(CURVE_MAX - 1)} | {len(pts) - 1})
        pts = [pts[k] for k in idx]
    return [[int(t), float(v)] for t, v in pts], [[int(t), float(v - n * A.SEED)] for t, v in pts]


# ------------------------------------------------------------------ 9.4 signal votes
def signals_now(eng, res: dict, now_ms: int) -> dict:
    votes = []
    bar_ms = {}
    for tf in G.TFS:
        step = G.TF_MIN[tf] * 60000
        last_close = eng.last_bar(tf)
        if last_close is None:
            continue
        bar_ms[tf] = int(last_close)
        grid = last_close - step * np.arange(VOTE_BARS - 1, -1, -1, dtype=np.int64)
        for coin in G.COINS:
            for strat in G.STRATS:
                buf = eng.sigs.get((coin, tf, strat))
                if buf is None:
                    continue
                ts, _cb, sd = buf.arrays()
                m = ts >= grid[0]
                ts_m, sd_m = ts[m], sd[m]
                idx = np.searchsorted(grid, ts_m)
                ok = (idx < len(grid)) & (grid[np.clip(idx, 0, len(grid) - 1)] == ts_m)
                lo = np.bincount(idx[ok & (sd_m > 0)], minlength=len(grid))
                sh = np.bincount(idx[ok & (sd_m < 0)], minlength=len(grid))
                votes.append(dict(coin=coin, tf=tf, strategy=strat, settings=int(G.NCOMBO[strat]), long=int(lo[-1]),
                                  short=int(sh[-1]),
                                  history=[[int(t), int(x), int(y)] for t, x, y in zip(grid, lo, sh)]))
    recent: dict = {}
    for a in A.current_accounts():
        r = res.get(a.id)
        if r is None or a.kind == "flip":
            continue
        sim = r["lines"].get(20)
        if sim is None:
            continue
        for t in sim["trades"]:
            if t["entry_ms"] < now_ms - DAY_MS:
                continue
            k = (t["coin"], a.tf, t["signal_ms"], t["side"])
            recent.setdefault(k, []).append(dict(id=a.id, name=a.name, setting_ko=t["setting_ko"]))
    rec = [dict(t_ms=int(k[2]), coin=k[0], tf=k[1], side=int(k[3]), accounts=v[:20]) for k, v in recent.items()]
    rec.sort(key=lambda x: -x["t_ms"])
    return dict(generated_ms=now_ms, bar_ms=bar_ms, votes=votes, recent=rec[:RECENT_MAX])


# ------------------------------------------------------------------ 9.5 analysis
def _stats(tt: list) -> dict:
    n = len(tt)
    return dict(n=n, mean_R=(float(np.mean([t["R"] for t in tt])) if n else None), pnl=float(sum(t["pnl"] for t in tt)),
                win_rate=(sum(1 for t in tt if t["pnl"] > 0) / n if n else None))


def _split(tt: list, tf_of=None) -> dict:
    hours = [[] for _ in range(24)]
    wdays = [[] for _ in range(7)]
    hw = [[[] for _ in range(24)] for _ in range(7)]
    for t in tt:
        g = time.gmtime((t["entry_ms"] + KST) / 1000)
        hours[g.tm_hour].append(t)
        wdays[g.tm_wday].append(t)
        hw[g.tm_wday][g.tm_hour].append(t)
    by_tf = {}
    if tf_of is not None:
        for tf in G.TFS:
            by_tf[tf] = _stats([t for t in tt if tf_of(t) == tf])
    return dict(n=len(tt),
                by_coin={c: _stats([t for t in tt if t["coin"] == c]) for c in G.COINS},
                by_side={"long": _stats([t for t in tt if t["side"] > 0]),
                         "short": _stats([t for t in tt if t["side"] < 0])},
                by_hour=[_stats(x) for x in hours], by_weekday=[_stats(x) for x in wdays], by_tf=by_tf,
                by_exit={ko: _stats([t for t in tt if t["reason"] == k]) for k, ko in REASON_KO.items()},
                hw_n=[[len(c) for c in row] for row in hw],
                hw_R=[[(float(np.mean([t["R"] for t in c])) if c else None) for c in row] for row in hw])


def analysis(res: dict, now_ms: int) -> dict:
    from .report import KIND_KO
    accts, pools = [], {}
    for a in A.current_accounts():
        r = res.get(a.id)
        if r is None or 20 not in r["lines"]:
            continue
        tt = [dict(t, _tf=a.tf) for t in r["lines"][20]["trades"] if t["status"] == "closed"]
        accts.append(dict(id=a.id, name=a.name, kind=a.kind, tf=a.tf, **_split(tt)))
        pools.setdefault(a.kind, []).extend(tt)
    kinds = [dict(kind=k, kind_ko=KIND_KO.get(k, k), **_split(tt, tf_of=lambda t: t["_tf"])) for k, tt in pools.items()]
    return dict(generated_ms=now_ms, accounts=accts, kinds=kinds)


# ------------------------------------------------------------------ 9.6 live vs the 5-year study
_PAST: dict = {}


def _past(strat: str, tf: str):
    key = (strat, tf)
    if key not in _PAST:
        p = os.path.join(DATA_DIR, f"past5y_{G.SHORT[strat]}_{tf}.npz")
        try:
            _PAST[key] = np.load(p)["stats"]
        except OSError:
            _PAST[key] = None
    return _PAST[key]


def vs5y(res: dict, now_ms: int) -> dict:
    rows = []
    for a in A.current_accounts():
        if a.kind != "fixed" or a.id not in res:
            continue
        tt = [t for t in res[a.id]["lines"][20]["trades"] if t["status"] == "closed"]
        live = _stats(tt)
        live.pop("pnl", None)
        st = _past(a.strat, a.tf)
        past = {}
        for pi, p in enumerate(PERIODS):
            if st is None:
                past[p] = dict(n=0, mean_R=None, win_rate=None)
                continue
            n, wr, mr = (float(x) for x in st[pi, 0, 0, a.combo])
            ok = np.isfinite(n) and n > 0
            past[p] = dict(n=int(n) if ok else 0, mean_R=(mr if ok and np.isfinite(mr) else None),
                           win_rate=(wr if ok and np.isfinite(wr) else None))
        ref = past["2024-26"]["mean_R"]
        gap = (live["mean_R"] - ref) if (live["mean_R"] is not None and ref is not None) else None
        if gap is None:
            note = "거래가 아직 없음" if not live["n"] else "5년 시험 자료 없음"
        elif live["n"] < 30:
            note = f"거래 {live['n']}건: 아직 비교하기 이름"
        elif abs(gap) < 0.1:
            note = "5년 시험과 비슷"
        else:
            note = "5년 시험보다 좋음" if gap > 0 else "5년 시험보다 나쁨"
        rows.append(dict(id=a.id, name=a.name, strategy=a.strat, tf=a.tf, combo=a.combo, exit=0,
                         setting_ko=G.combo_label(a.strat, a.combo), exit_ko=G.exit_ko(0), live=live, past=past,
                         gap_R=gap, note_ko=note))
    return dict(generated_ms=now_ms, rows=rows)


# ------------------------------------------------------------------ 9.9 timeline, data quality, export
EVENTS_MAX = 500
TICK_HIST_MAX = 192
ERR_MAX = 50


def add_event(conn, t_ms: int, what: str, detail_ko: str) -> None:
    from . import store as ST
    ev = ST.get_meta(conn, "events", []) or []
    ev.append(dict(t_ms=int(t_ms), what=what, detail_ko=str(detail_ko)[:300]))
    ST.set_meta(conn, "events", ev[-EVENTS_MAX:])


def code_version() -> str:
    """A short hash of the demo lab's Python files (changes when the code is updated)."""
    import hashlib
    h = hashlib.sha256()
    d = os.path.dirname(os.path.abspath(__file__))
    for root, _dirs, files in sorted(os.walk(d)):
        if "__pycache__" in root:
            continue
        for f in sorted(files):
            if f.endswith((".py", ".js", ".css", ".html")):
                with open(os.path.join(root, f), "rb") as fh:
                    h.update(f.encode() + b"\0" + fh.read())
    return h.hexdigest()[:12]


def record_tick(conn, now_ms: int, seconds: float, errors: list) -> None:
    from . import store as ST
    hist = ST.get_meta(conn, "tick_hist", []) or []
    hist.append([int(now_ms), float(seconds or 0.0), len(errors or [])])
    ST.set_meta(conn, "tick_hist", hist[-TICK_HIST_MAX:])
    if errors:
        log = ST.get_meta(conn, "err_log", []) or []
        log.append([int(now_ms), "; ".join(errors)[:400]])
        ST.set_meta(conn, "err_log", log[-ERR_MAX:])


def timeline(conn, now_ms: int) -> dict:
    from . import store as ST
    ev = list(ST.get_meta(conn, "events", []) or [])
    wd = ST.get_meta(conn, "warm_done_ms")
    if wd:
        ev.append(dict(t_ms=int(wd), what="warm", detail_ko="첫 채우기 끝 (지난 26주 시세와 모든 설정의 결과)"))
    ls = ST.get_meta(conn, "live_start_ms")
    if ls:
        ev.append(dict(t_ms=int(ls), what="live", detail_ko="실시간 데모 시작: 이때부터의 거래만 계좌에 들어감"))
    ev.sort(key=lambda e: -e["t_ms"])
    return dict(generated_ms=now_ms, events=ev)


def dataq(eng, now_ms: int, snap: str) -> dict:
    from . import store as ST
    live0 = eng.live_start or now_ms
    coins = []
    for c in G.COINS:
        b = eng.b15.get(c)
        ts = np.asarray(b["ts"], np.int64) if b is not None else np.zeros(0, np.int64)
        lv = ts[ts >= live0 - M15]
        last = int(ts[-1]) if len(ts) else None
        exp = int(((last or live0) - live0) // M15 + 1) if last and last >= live0 else 0
        have = int((lv >= live0).sum())
        fts, _fr = eng.funding.get(c, (np.zeros(0), np.zeros(0)))
        dn, dlast = eng.conn.execute("SELECT COUNT(*), MAX(ts) FROM depth WHERE coin = ? AND ts >= ?",
                                     (c, int(live0))).fetchone()
        coins.append(dict(coin=c, bars_expected=exp, bars_have=have, bars_missing=max(0, exp - have),
                          last_bar_ms=last, lag_s=((now_ms - (last + M15)) / 1000 if last else None),
                          funding_last_ms=(int(fts[-1]) if len(fts) else None), depth_rows=int(dn or 0),
                          depth_last_ms=dlast))
    rank_ms = None
    try:
        import json
        with open(os.path.join(snap, "rank_meta.json"), encoding="utf-8") as fh:
            rank_ms = json.load(fh).get("generated_ms")
    except (OSError, ValueError):
        pass
    return dict(generated_ms=now_ms, coins=coins, ticks=ST.get_meta(eng.conn, "tick_hist", []) or [],
                errors=list(reversed(ST.get_meta(eng.conn, "err_log", []) or [])), issues=list(eng.issues),
                rank_ms=rank_ms, warm_issues=ST.get_meta(eng.conn, "warm_issues", []) or [])


EXPORT_COLS = ["account", "name", "L", "coin", "side", "signal_kst", "entry_kst", "entry", "stop", "exit_kst", "exit",
               "status", "reason", "R", "pnl", "roe", "margin", "notional", "fee", "funding", "setting", "exit_rule"]


def _kst(ms) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime((int(ms) + KST) / 1000)) if ms else ""


def write_exports(res: dict, snap: str, now_ms: int) -> None:
    """snap/export/<id>.csv.gz: every trade of every line of the account (UTF-8 with BOM for Excel)."""
    import csv
    import gzip
    import io
    d = os.path.join(snap, "export")
    os.makedirs(d, exist_ok=True)
    for a in A.current_accounts():
        r = res.get(a.id)
        if r is None:
            continue
        buf = io.StringIO()
        buf.write("﻿")
        w = csv.writer(buf)
        w.writerow(EXPORT_COLS)
        rows = sorted((t for sim in r["lines"].values() for t in sim["trades"]), key=lambda t: (t["entry_ms"], t["L"]))
        for t in rows:
            w.writerow([a.id, a.name, t["L"], t["coin"], "롱" if t["side"] > 0 else "숏", _kst(t["signal_ms"]),
                        _kst(t["entry_ms"]), f"{t['entry']:.8g}", f"{t['stop']:.8g}", _kst(t["exit_ms"]),
                        ("" if t["exit"] is None else f"{t['exit']:.8g}"), t["status"], t["reason"],
                        f"{t['R']:.4f}", f"{t['pnl']:.2f}", f"{t['roe']:.4f}", f"{t['margin']:.2f}",
                        f"{(t.get('notional') or 0):.2f}", f"{(t.get('fee') or 0):.2f}", f"{(t.get('funding') or 0):.2f}",
                        t["setting_ko"], t["exit_ko"]])
        tmp = os.path.join(d, f".{a.id}.csv.gz.tmp")
        with gzip.open(tmp, "wb", compresslevel=6) as fh:
            fh.write(buf.getvalue().encode("utf-8"))
        os.replace(tmp, os.path.join(d, f"{a.id}.csv.gz"))
    from . import store as ST
    ST.write_json(os.path.join(d, "index.json"), dict(generated_ms=now_ms,
                                                      files=sorted(f for f in os.listdir(d) if f.endswith(".csv.gz"))))
