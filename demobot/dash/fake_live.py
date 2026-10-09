"""The round 4 part A files of the FAKE snapshot folder (demobot/CONTRACT.md 9.2-9.4 and 9.9), built from the fake
accounts of fake.py so the terminal, the positions, the signals, the data check and the timeline agree with the
accounts, the trades and the candles of the same folder:

    positions.json      every open position of every plain line (from the lines' open trades), by_coin (20x lines)
    calendar.json       per KST day since the live start: closed trades, wins, P&L, lines up / down, per kind, best / worst
    signals_now.json    votes of every setting per coin x tf x strategy (shaped by the candles), the entries taken
    dataq.json          the data check (bars per coin, tick times, errors)
    timeline.json       install, warm-up, live start, updates, passes and confirmation results
    export/<id>.csv.gz  every trade of every line of a few accounts (UTF-8 with BOM), export/index.json
    + acct/<id>.json "daily" and home.json "equity_total" / "pnl_total" (fake.build adds them to its own files)

Called by fake.build (never on its own); deterministic (its own seeded streams, gzip without a time stamp).
"""
from __future__ import annotations

import csv
import datetime
import gzip
import io
import math
import os
import re

import numpy as np

from .. import grid
from . import fake as F      # helpers and constants only; the clock (fake.NOW_MS) is always passed in as `now`

H1 = 3_600_000
H8 = 8 * H1
KST = datetime.timezone(datetime.timedelta(hours=9))
TP_RE = re.compile(r"^익절\s*([0-9.]+)R\s*·\s*손절")
EXPORT_IDS = ("fx-def-S2-15m", "fx-pk-S2-15m", "ad-r26-N04-15m", "fr-S2-15m", "cf-15m", "pv-p1-15m")
CSV_COLS = ("account", "name", "L", "coin", "side", "status", "reason", "signal_kst", "entry_kst", "entry", "stop",
            "exit_kst", "exit", "pnl", "roe", "R", "margin", "notional", "fee", "funding", "cost_bps", "through_bps",
            "trend", "vol", "setting_ko", "exit_ko", "key")


def _day(ms: int) -> str:
    return datetime.datetime.fromtimestamp(ms / 1000, KST).strftime("%Y-%m-%d")


def _kst(ms) -> str:
    return "" if ms is None else datetime.datetime.fromtimestamp(ms / 1000, KST).strftime("%Y-%m-%d %H:%M")


def _r(x, nd=2):
    return F._r(x, nd)


def _lines(accts):
    return [(a, L) for a in accts for L in grid.LEVS]


def _closed(a, L):
    """The line's closed trades in the order they closed (the simulation's heap order)."""
    tr = a.sims[L]["trades"]
    return [t for _x, _i, t in sorted((t["exit_ms"], i, t) for i, t in enumerate(tr) if t["status"] == "closed")]


# ---------------------------------------------------------------- acct "daily", home "equity_total" / "pnl_total"
def acct_daily(a) -> dict:
    days: dict = {}
    for L in grid.LEVS:
        for t in a.sims[L]["trades"]:
            if t["status"] == "closed":
                row = days.setdefault(_day(t["exit_ms"]), {str(x): 0.0 for x in grid.LEVS})
                row[str(L)] += t["pnl"]
    return {d: {k: _r(v) for k, v in row.items()} for d, row in sorted(days.items())}


def home_extra(accts, live_start: int, now: int) -> dict:
    """The sum of every plain line's wallet on an hourly grid (a ruined wallet restarts at $1,000, as in the engine),
    and the same minus lines x $1,000."""
    t0 = -(-live_start // H1) * H1
    grid_t = list(range(t0, now + 1, H1))
    if not grid_t or grid_t[-1] != now:
        grid_t.append(now)
    total = np.zeros(len(grid_t))
    lines = _lines(accts)
    for a, L in lines:
        W, k = F.SEED_USD, 0
        ev = _closed(a, L)
        for i, t in enumerate(grid_t):
            while k < len(ev) and ev[k]["exit_ms"] <= t:
                W += ev[k]["pnl"]
                if ev[k].get("ruin"):
                    W = F.SEED_USD
                k += 1
            total[i] += W
    base = len(lines) * F.SEED_USD
    eq = F._down([[int(t), _r(float(v))] for t, v in zip(grid_t, total)], 800)
    return {"equity_total": eq, "pnl_total": [[t, _r(v - base)] for t, v in eq]}


# ---------------------------------------------------------------- positions.json (9.2)
def positions(accts, mk, now: int) -> dict:
    rows = []
    for a in accts:
        s = a.spec
        for L in grid.LEVS:
            for t in a.sims[L]["trades"]:
                if t["status"] != "open":
                    continue
                last = float(mk.bars[t["coin"]]["c"][-1])
                m = TP_RE.match(t.get("exit_ko") or "")
                dist = abs(t["entry"] - t["stop"])
                rows.append({"id": s["id"], "name": s["name"], "kind": s["kind"], "L": L, "coin": t["coin"],
                             "side": t["side"], "tf": s["tf"], "entry_ms": t["entry_ms"], "entry": t["entry"],
                             "stop": t["stop"], "target": _r(t["entry"] + t["side"] * float(m.group(1)) * dist, 6) if m else None,
                             "margin": t["margin"], "notional": t["notional"], "unreal": t["pnl"], "roe": t["roe"],
                             "R": t["R"], "last": _r(last, 6), "stop_dist_pct": _r(abs(last - t["stop"]) / last * 100, 3),
                             "held_ms": int(now - t["entry_ms"]), "setting_ko": t["setting_ko"], "exit_ko": t["exit_ko"]})
    rows.sort(key=lambda p: (-p["entry_ms"], p["id"], p["L"]))
    by = []
    for coin in grid.COINS:
        mine = [p for p in rows if p["coin"] == coin]
        by.append({"coin": coin, "long": sum(1 for p in mine if p["L"] == 20 and p["side"] > 0),
                   "short": sum(1 for p in mine if p["L"] == 20 and p["side"] < 0),
                   "unreal": _r(sum(p["unreal"] for p in mine))})
    return {"generated_ms": now, "positions": rows, "by_coin": by}


# ---------------------------------------------------------------- calendar.json (9.3)
def calendar(accts, live_start: int, now: int) -> dict:
    lines = _lines(accts)
    per = {}                                  # day -> {(id, L): [pnl, n, wins]}
    for a, L in lines:
        for t in a.sims[L]["trades"]:
            if t["status"] == "closed":
                c = per.setdefault(_day(t["exit_ms"]), {}).setdefault((a.spec["id"], L), [0.0, 0, 0])
                c[0] += t["pnl"]
                c[1] += 1
                c[2] += t["pnl"] > 0
    kinds = [(k, ko) for k, ko in F.KIND_KO.items() if any(a.spec["kind"] == k for a in accts)]
    names = {a.spec["id"]: a.spec["name"] for a in accts}
    kind_of = {a.spec["id"]: a.spec["kind"] for a in accts}
    d0 = datetime.datetime.fromtimestamp(live_start / 1000, KST).date()
    d1 = datetime.datetime.fromtimestamp(now / 1000, KST).date()
    days = []
    d = d0
    while d <= d1:
        key = d.isoformat()
        cells = per.get(key, {})
        ranked = sorted(cells.items(), key=lambda kv: kv[1][0])
        ref = lambda kv: {"id": kv[0][0], "name": names[kv[0][0]], "L": kv[0][1], "pnl": _r(kv[1][0])}   # noqa: E731
        by_kind = []
        for k, ko in kinds:
            ks = [cells.get((a.spec["id"], L), [0.0])[0] / F.SEED_USD * 100 for a, L in lines if kind_of[a.spec["id"]] == k]
            by_kind.append({"kind": k, "kind_ko": ko, "mean_pnl_pct": _r(float(np.mean(ks)), 3)})
        days.append({"day": key, "trades": sum(c[1] for c in cells.values()), "wins": sum(c[2] for c in cells.values()),
                     "pnl_sum": _r(sum(c[0] for c in cells.values())),
                     "lines_up": sum(1 for c in cells.values() if c[0] > 0),
                     "lines_down": sum(1 for c in cells.values() if c[0] < 0), "by_kind": by_kind,
                     "best": ref(ranked[-1]) if ranked else {}, "worst": ref(ranked[0]) if ranked else {}})
        d += datetime.timedelta(days=1)
    return {"generated_ms": now, "days": days}


# ---------------------------------------------------------------- signals_now.json (9.4)
SIG_RATE = {"S2": 0.006, "N02": 0.008, "N04": 0.005}


def _tf_bars(mk, coin, tf):
    """(open ms, open, close, ATR ratio) of the coin's closed bars in a timeframe (30m: paired 15m bars)."""
    b, ts = mk.bars[coin], mk.ts
    if tf == "15m":
        return ts, b["o"], b["c"], mk.atr[coin]
    first = np.flatnonzero((ts[:-1] % (2 * F.M15) == 0) & (ts[1:] == ts[:-1] + F.M15))
    return ts[first], b["o"][first], b["c"][first + 1], mk.atr[coin][first + 1] * math.sqrt(2)


def signals_now(accts, mk, seed: int, now: int) -> dict:
    rng = np.random.default_rng(seed + 41)
    votes, bar_ms = [], {}
    for coin in grid.COINS:
        for tf in grid.TFS:
            ts, o, c, atr = _tf_bars(mk, coin, tf)
            ts, o, c, atr = ts[-96:], o[-96:], c[-96:], atr[-96:]
            bar_ms[tf] = int(ts[-1])
            z = np.clip((c - o) / np.maximum(atr * c, 1e-12), -3, 3)
            for strat in grid.STRATS:
                S = grid.NCOMBO[strat]
                base = SIG_RATE[grid.SHORT[strat]] * S
                lo = rng.poisson(np.minimum(base * np.exp(1.15 * z), 0.3 * S))
                sh = rng.poisson(np.minimum(base * np.exp(-1.15 * z), 0.3 * S))
                hist = [[int(t), int(min(S, a)), int(min(S, b))] for t, a, b in zip(ts, lo, sh)]
                votes.append({"coin": coin, "tf": tf, "strategy": strat, "settings": S, "long": hist[-1][1],
                              "short": hist[-1][2], "history": hist})
    groups = {}
    for a in accts:
        for t in a.sims[20]["trades"]:
            if t["entry_ms"] >= now - 24 * H1:
                g = groups.setdefault((t["signal_ms"], t["coin"], a.spec["tf"], t["side"]), [])
                g.append({"id": a.spec["id"], "name": a.spec["name"], "setting_ko": t["setting_ko"]})
    recent = [{"t_ms": int(k[0]), "coin": k[1], "tf": k[2], "side": k[3], "accounts": v}
              for k, v in sorted(groups.items(), key=lambda kv: (-kv[0][0], kv[0][1], kv[0][2], kv[0][3]))][:200]
    return {"generated_ms": now, "bar_ms": bar_ms, "votes": votes, "recent": recent}


# ---------------------------------------------------------------- dataq.json (9.9)
def dataq(status, mk, cm, seed: int, now: int) -> dict:
    rng = np.random.default_rng(seed + 42)
    hist0 = status.get("history_start_ms") or (now - 200 * 86_400_000)
    expected = int((now - hist0) // F.M15)
    missing = {"BCHUSD": 4}
    coins = []
    for coin in grid.COINS:
        miss = missing.get(coin, 0)
        coins.append({"coin": coin, "bars_expected": expected, "bars_have": expected - miss, "bars_missing": miss,
                      "last_bar_ms": int(mk.ts[-1]), "lag_s": _r(float(rng.uniform(19, 34)), 1),
                      "funding_last_ms": int(now // H8 * H8), "depth_rows": int(len(cm.ticks)),
                      "depth_last_ms": int(cm.ticks[-1]) + 31_000 if len(cm.ticks) else None})
    ticks = []
    for k in range(191, -1, -1):
        sec = float(rng.lognormal(math.log(38), 0.18))
        err = 0
        if k in (23, 117):
            sec, err = sec * 2.6, 1
        ticks.append([int(now - k * F.M15 + 20_000), _r(sec, 1), err])
    errors = [[int(now - 23 * F.M15 + 61_000), "바이낸스 응답 시간 초과 (premiumIndex): 다음 틱에 다시 받음"],
              [int(now - 117 * F.M15 + 58_000), "XRPUSD 15분봉 1개 늦게 도착: 다시 받음"],
              [int(now - 3 * 86_400_000 + 7 * H1), "응답에 <html> 조각이 섞여 와서 버림 (글자로만 보여야 함)"]]
    errors.sort(key=lambda e: -e[0])
    return {"generated_ms": now, "coins": coins, "ticks": ticks, "errors": errors[:50],
            "issues": list(status.get("data_issues") or []), "rank_ms": int(now - 40_000),
            "warm_issues": ["BCHUSD 15분봉 4개가 바이낸스에도 없음 (빈 봉으로 두고 계산에서 뺌)"]}


# ---------------------------------------------------------------- timeline.json (9.9)
def timeline(confirm, live_start: int, now: int) -> dict:
    D = 86_400_000
    ev = [{"t_ms": int(live_start - 2 * D + 5 * 60_000), "what": "start", "detail_ko": "설치 끝, 엔진 처음 시작 (과거 자료 채우기부터)"},
          {"t_ms": int(live_start - 2 * D + 6 * 60_000), "what": "plugins", "detail_ko": "비공개 매매법 2개 불러옴 (계좌 2개 추가)"},
          {"t_ms": int(live_start - 30 * 60_000), "what": "warm", "detail_ko": "과거 26주 채우기 끝: 7코인 15분봉, 9분 40초 걸림"},
          {"t_ms": int(live_start), "what": "live", "detail_ko": "실시간 시작: 계좌 50개, 배수 4줄씩 (200줄)"},
          {"t_ms": int(live_start + 2 * D + 3 * H1), "what": "update", "detail_ko": "업데이트: 반익반본 청산(1R 절반 · 본전 · 1.5R) 추가"},
          {"t_ms": int(live_start + 2 * D + 3 * H1 + 90_000), "what": "start", "detail_ko": "업데이트 뒤 엔진 다시 시작 (기록은 그대로)"},
          {"t_ms": int(live_start + F.COST_LOG_DAYS * D), "what": "update", "detail_ko": "업데이트: 실제 호가 비용 기록 시작"}]
    for c in confirm:
        who = f"{c['name']} {c['L']}배"
        ev.append({"t_ms": int(c["start_ms"]), "what": "pass", "detail_ko": f"우리 기준 통과: {who} → 확인 기간 시작"})
        if c["status"] == "confirmed" and c["decided_ms"]:
            ev.append({"t_ms": int(c["decided_ms"]), "what": "confirmed", "detail_ko": f"확인 기간 통과: {who} (실전 후보, 두 분이 정할 차례)"})
        elif c["status"] == "failed" and c["decided_ms"]:
            ev.append({"t_ms": int(c["decided_ms"]), "what": "failed", "detail_ko": f"확인 기간 실패: {who} ({c['why_ko']})"})
    ev = [e for e in ev if e["t_ms"] <= now]
    ev.sort(key=lambda e: (-e["t_ms"], e["what"]))
    return {"generated_ms": now, "events": ev}


# ---------------------------------------------------------------- export/<id>.csv.gz (9.9)
def export_csv(a) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_COLS)
    rows = [t for L in grid.LEVS for t in a.sims[L]["trades"]]
    rows.sort(key=lambda t: (t["entry_ms"], t["L"]))
    for t in rows:
        w.writerow([a.spec["id"], a.spec["name"], t["L"], t["coin"], t["side"], t["status"], t["reason"],
                    _kst(t["signal_ms"]), _kst(t["entry_ms"]), t["entry"], t["stop"], _kst(t["exit_ms"]),
                    "" if t["exit"] is None else t["exit"], t["pnl"], t["roe"], t["R"], t["margin"], t["notional"], t["fee"],
                    t["funding"], "" if t.get("cost_bps") is None else t["cost_bps"],
                    "" if t.get("through_bps") is None else t["through_bps"], t.get("trend") or "", t.get("vol") or "",
                    t["setting_ko"], t["exit_ko"], t["key"]])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _write_gz(path: str, raw: bytes) -> None:
    tmp = path + ".tmp"
    with open(tmp, "wb") as f, gzip.GzipFile(filename="", mode="wb", fileobj=f, mtime=0) as gz:
        gz.write(raw)
    os.replace(tmp, path)


def write(outdir: str, accts, mk, cm, status: dict, confirm, live_start: int, seed: int, now: int) -> dict:
    """Write the part A files; returns a few facts (tests). now: fake.build's clock (passed in: under
    ``python -m demobot.dash.fake`` that module runs as __main__, so its NOW_MS is not this import's)."""
    pos = positions(accts, mk, now)
    F._write_json(os.path.join(outdir, "positions.json"), pos)
    F._write_json(os.path.join(outdir, "calendar.json"), calendar(accts, live_start, now))
    sig = signals_now(accts, mk, seed, now)
    F._write_json(os.path.join(outdir, "signals_now.json"), sig)
    F._write_json(os.path.join(outdir, "dataq.json"), dataq(status, mk, cm, seed, now))
    F._write_json(os.path.join(outdir, "timeline.json"), timeline(confirm, live_start, now))
    ex = os.path.join(outdir, "export")
    os.makedirs(ex, exist_ok=True)
    files = []
    byid = {a.spec["id"]: a for a in accts}
    for aid in EXPORT_IDS:
        if aid in byid:
            _write_gz(os.path.join(ex, aid + ".csv.gz"), export_csv(byid[aid]))
            files.append(aid + ".csv.gz")
    F._write_json(os.path.join(ex, "index.json"), {"generated_ms": now, "files": files})
    return {"positions": len(pos["positions"]), "recent_signals": len(sig["recent"]), "exports": len(files)}
