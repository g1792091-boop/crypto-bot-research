"""믹스 30분 봇, the last 20 days (owners 10-25 night: "친구봇 계단도 V3.9처럼 했을때 친구봇의 20일 실제 거래로 먼저 비교해줘"):
the bot's OWN code (paperbot/mixchop.py through research/mixchop5y/replay.py: the real evaluate at every colour change,
a mixchop.Bot in paper mode with the live rules of deploy/mixchop.live.json) over 2026-10-05 00:00 .. 10-25 00:00 UTC on
Binance USDT-M 30m / 1h klines, once with its own ladder and once with each V3.9-style ladder in its place.

    python3 -I research/mixchop20d/ladder20.py download   # data.binance.vision zips (sha256 checked) -> --data
    python3 -I research/mixchop20d/ladder20.py run        # -> research/mixchop20d/ladder20.json
    python3 -I research/mixchop20d/ladder20.py all

Why a replay: the live bot (WOO X Pro 2) started 2026-10-25 14:06 UTC, so it has no 20 days of its own trades; this is
what its code would have done on those 20 days of real prices, entry for entry (same coins, signals, stop, size).

Ladders compared (nothing else changes; the stop only moves at a 30m close, as the bot does it):
- now: the bot's ladder (mixchop.ladder_stop): at +roe_act % ROE (SOL/BCH 150, ETH/XRP 200, DOGE/ZEC 100) the stop goes to
  +10 % ROE, then one more lock every (roe_act - 10) %.
- v39_15: V3.9's ladder (deploy/executor.live-toobit.json): net ROE (after the 0.042 % taker fee on both sides, at the
  coin's own leverage) 15 -> lock 13, 20 -> 17, 25 -> 22, 30 -> 27, then every +5 % the lock 3 % under it.
- v39_20: the same from 20 -> 17 (owners' option B); v39_25: from 25 -> 22 (option C).
Each ladder twice: as the bot moves its stop (at 30m closes only, from the closed 30m bars), and "_1m": the stop checked
and moved on every 1m bar (as V3.9's executor follows the live price; a new entry still only at a 30m close).
Also "same entries": the current ladder's own entries, each followed with every ladder on the 1m bars (the trades
themselves fixed, so only the take-profit differs).
Data: monthly zips 2026-07 .. 2026-09 and daily zips 2026-10-01 .. 2026-10-24 (the bot reads 1,500 bars: warm-up), 1m
daily zips 2026-10-05 .. 2026-10-24,
https://data.binance.vision/data/futures/um/{monthly,daily}/klines/<SYMBOL>/<tf>/, each checked against its .CHECKSUM.
Raw data never goes into git (default --data: the session scratchpad).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research", "mixchop5y"))

from paperbot import mixchop as M  # noqa: E402
import replay as R  # noqa: E402  (research/mixchop5y/replay.py)

SCRATCH = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad"
DATA = os.environ.get("MIXCHOP20D_DATA") or os.path.join(SCRATCH, "mixchop20d_data")
OUT = os.path.join(HERE, "ladder20.json")
BASE = "https://data.binance.vision/data/futures/um"
MONTHS = ("2026-07", "2026-08", "2026-09")
DAY0, DAY1 = dt.date(2026, 10, 1), dt.date(2026, 10, 24)
T0 = int(pd.Timestamp("2026-10-05", tz="UTC").value // 1_000_000)
T1 = int(pd.Timestamp("2026-10-25", tz="UTC").value // 1_000_000)
FEE = R.TAKER                                                   # WOO X Pro taker, a side
M1_FROM = "2026-10-05"
MIN1 = 60_000
ORIG_LADDER = M.ladder_stop                                     # the bot's own ladder


def days():
    d = DAY0
    while d <= DAY1:
        yield d.isoformat()
        d += dt.timedelta(days=1)


def files():
    cfg = M.load_config(R.CONFIG)
    for s in cfg.symbols:
        for tf in R.TFS:
            for mo in MONTHS:
                yield s, tf, "monthly", mo
            for d in days():
                yield s, tf, "daily", d
        for d in days():
            if d >= M1_FROM:
                yield s, "1m", "daily", d


def path_of(data, sym, tf, kind, when):
    return os.path.join(data, "raw", kind, sym, tf, f"{sym}-{tf}-{when}.zip")


def fetch(data, sym, tf, kind, when) -> str:
    p = path_of(data, sym, tf, kind, when)
    if os.path.exists(p):
        return "kept"
    url = f"{BASE}/{kind}/klines/{sym}/{tf}/{sym}-{tf}-{when}.zip"
    want = R._get(url + ".CHECKSUM").decode().split()[0].strip().lower()
    body = R._get(url)
    got = hashlib.sha256(body).hexdigest()
    if got != want:
        raise RuntimeError(f"{url}: sha256 {got} != {want}")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".part", "wb") as fh:
        fh.write(body)
    os.replace(p + ".part", p)
    return "new"


def cmd_download(args) -> int:
    jobs = list(files())
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda j: fetch(args.data, *j), jobs))
    print(f"{len(res)} files: {res.count('new')} new, {res.count('kept')} kept")
    return 0


def read(data, sym, tf) -> np.ndarray:
    """[open_ms, open, high, low, close] rows, oldest first, one per open time (as replay.read_klines)."""
    rows = []
    parts = (("daily", tuple(d for d in days() if d >= M1_FROM)),) if tf == "1m" else \
        (("monthly", MONTHS), ("daily", tuple(days())))
    for kind, whens in parts:
        for w in whens:
            with zipfile.ZipFile(path_of(data, sym, tf, kind, w)) as z:
                names = [n for n in z.namelist() if n.endswith(".csv") and "/" not in n and ".." not in n]
                if len(names) != 1:
                    raise RuntimeError(f"{sym} {tf} {w}: {z.namelist()}")
                text = z.read(names[0]).decode("ascii", "replace")
            for line in text.splitlines():
                f = line.split(",")
                if len(f) < 5 or not f[0].strip().isdigit():
                    continue
                t = int(f[0])
                if t > 10 ** 14:
                    t //= 1000
                rows.append((t, float(f[1]), float(f[2]), float(f[3]), float(f[4])))
    a = np.array(rows, dtype=float)
    a = a[np.argsort(a[:, 0], kind="stable")]
    return a[np.r_[a[1:, 0] != a[:-1, 0], True]]


# ====================================================================== the ladders
def v39_ladder(first: float, lock: float, nxt: float = 0.0, nxt_gap: float = 0.0, step: float = 0.05, fee: float = FEE):
    """V3.9's two-part ladder on net ROE at the coin's leverage, in mixchop.ladder_stop's form (new stop, step):
    best net ROE >= first -> lock; >= nxt -> nxt - nxt_gap, + step for every step past nxt."""

    def ladder_stop(side, entry, best, stop, roe_act, lev, lock_roe=M.LOCK_ROE):
        roe = (side * (best - entry) / entry - 2 * fee) * lev
        if roe < first - 1e-12:
            return stop, 0
        if nxt > 0 and roe >= nxt - 1e-12:
            k = int(math.floor((roe - nxt) / step + 1e-9))
            lk, n = nxt - nxt_gap + step * k, k + 2
        else:
            lk, n = lock, 1
        new = entry + side * entry * (lk / lev + 2 * fee)
        if (side > 0 and new > stop) or (side < 0 and new < stop):
            return new, n
        return stop, -1

    return ladder_stop


LADDERS = {
    "now": ("지금 계단 (ROE +100~200% → +10%, 코인별)", None),
    "v39_15": ("V3.9 계단 15→13·20→17·25→22·30→27… (A)", v39_ladder(0.15, 0.13, 0.20, 0.03)),
    "v39_20": ("20→17·25→22·30→27… (B)", v39_ladder(0.20, 0.17, 0.25, 0.03)),
    "v39_25": ("25→22·30→27… (C)", v39_ladder(0.25, 0.22, 0.30, 0.03)),
}


# ====================================================================== the stop on every 1m bar
class MinuteBot(R.ReplayBot):
    """The replay bot with its paper exit and ladder run on every 1m bar since the last one used (mixchop.Bot.paper_bars
    with 1m bars in place of the 30m ones); entries are unchanged (30m closes)."""
    m1: dict = {}

    def paper_bars(self, close_ms: int) -> None:
        p = self.pos
        a = self.m1[p.symbol]
        lo = int(np.searchsorted(a[:, 0], p.last_bar_ms))
        hi = int(np.searchsorted(a[:, 0], close_ms - MIN1, side="right"))
        for o, op, h, low, _c in a[lo:hi]:
            hit = low <= p.stop if p.side > 0 else h >= p.stop
            if hit:
                px = min(op, p.stop) if p.side > 0 else max(op, p.stop)
                self.finish(p, px, "ladder" if p.step > 0 else "stop")
                return
            p.best = max(p.best, h) if p.side > 0 else min(p.best, low)
            p.last_bar_ms = int(o) + MIN1
            new, step = M.ladder_stop(p.side, p.entry, p.best, p.stop, p.roe_act, p.leverage)
            if step > 0 and new != p.stop:
                self.log("ladder", symbol=p.symbol, old=p.stop, new=new, step=step, best=p.best)
                p.stop, p.step = new, step
        self.save()


def follow(a1: np.ndarray, side: int, entry: float, dist: float, lev: float, roe_act: float, start_ms: int, ladder) -> dict:
    """One entry followed on 1m bars with ``ladder`` (MinuteBot's rule): exit price and R (fees both sides), or the
    mark at the last bar when still open."""
    stop, best, step = entry - side * dist, entry, 0
    lo = int(np.searchsorted(a1[:, 0], start_ms))
    px, done, t = float(a1[-1, 4]), False, int(a1[-1, 0]) + MIN1
    for o, op, h, low, _c in a1[lo:]:
        if (low <= stop) if side > 0 else (h >= stop):
            px, done, t = (min(op, stop) if side > 0 else max(op, stop)), True, int(o) + MIN1
            break
        best = max(best, h) if side > 0 else min(best, low)
        new, s = ladder(side, entry, best, stop, roe_act, lev)
        if s > 0 and new != stop:
            stop, step = new, s
    r = (side * (px - entry) - entry * FEE - px * FEE) / dist
    return {"r": round(r, 3), "exit": px, "closed": done, "step": step, "exit_ms": t,
            "net_roe": round((side * (px - entry) / entry - 2 * FEE) * lev, 4)}


def same_entries(trades_now: list, rows: list, m1: dict) -> dict:
    """The current ladder's entries, each followed with every ladder on 1m bars."""
    out = {}
    for name, (label, fn) in LADDERS.items():
        res = []
        for t in trades_now:
            en = next(r for r in rows if r["kind"] == "entry" and r["symbol"] == t["symbol"] and r["opened_ms"] == t["opened_ms"])
            f = follow(m1[t["symbol"]], int(en["side"]), float(en["entry"]), float(en["stop_dist"]), float(en["leverage"]),
                       float(en["roe_act"]), int(en["last_bar_ms"]), fn or ORIG_LADDER)
            res.append({"symbol": t["symbol"], "side": t["side"], "opened": t["opened"], **f})
        rs = [x["r"] for x in res]
        out[name] = {"label": label, "trades": len(rs), "wins": sum(1 for r in rs if r > 0), "r_sum": round(sum(rs), 2),
                     "usd_at_50": round(sum(rs) * 50 * 0.0025, 3), "list": res}
    return out


# ====================================================================== numbers
def trade_rows(rows, risk_pct, bars30):
    """Closed trades with the bot's own R, the price ROE at its leverage, and the best ROE it saw."""
    out = []
    for t in R.trades(rows, risk_pct):
        en = next(r for r in rows if r["kind"] == "entry" and r["symbol"] == t["symbol"] and r["opened_ms"] == t["opened_ms"])
        ex = next(r for r in rows if r["kind"] == "exit" and r["symbol"] == t["symbol"] and r["opened_ms"] == t["opened_ms"])
        lev, entry, side = float(en["leverage"]), float(en["entry"]), int(en["side"])
        a = bars30[t["symbol"]]
        seg = a[(a[:, 0] + M.MIN30 > t["opened_ms"] - R.JUDGE_MS) & (a[:, 0] < t["exit_ms"])]
        best = (seg[:, 2].max() if side > 0 else seg[:, 3].min()) if len(seg) else entry
        out.append({**t, "lev": lev, "entry": entry, "exit": float(ex["price"]),
                    "net_roe": round((side * (float(ex["price"]) - entry) / entry - 2 * FEE) * lev, 4),
                    "best_net_roe": round((side * (best - entry) / entry - 2 * FEE) * lev, 4),
                    "stop_roe": round(-float(en["stop_dist"]) / entry * lev, 4),
                    "opened": time.strftime("%m-%d %H:%M", time.gmtime(t["opened_ms"] / 1000)),
                    "closed": time.strftime("%m-%d %H:%M", time.gmtime(t["exit_ms"] / 1000))})
    return out


def summarize(res, rows, ts, bars30) -> dict:
    rs = [t["r"] for t in ts]
    w = [r for r in rs if r > 0]
    lo = [r for r in rs if r <= 0]
    per_day: dict = {}
    for r in rows:
        if r["kind"] == "entry":
            d = time.strftime("%Y-%m-%d", time.gmtime(r["opened_ms"] / 1000))
            per_day[d] = per_day.get(d, 0) + 1
    n_days = (T1 - T0) // 86_400_000
    counts = [per_day.get(time.strftime("%Y-%m-%d", time.gmtime((T0 + i * 86_400_000) / 1000)), 0) for i in range(n_days)]
    open_pos = None
    eq = res["end_eq"]
    for r in rows:
        if r["kind"] == "entry":
            open_pos = r
        elif r["kind"] == "exit" and open_pos and r["opened_ms"] == open_pos["opened_ms"]:
            open_pos = None
    mark = None
    if open_pos:                                                # an open position at the end: marked at the last close
        last = float(bars30[open_pos["symbol"]][-1, 4])
        upnl = open_pos["side"] * (last - open_pos["entry"]) * open_pos["qty"] - open_pos["qty"] * last * FEE
        mark = {"symbol": open_pos["symbol"], "side": open_pos["side"], "entry": open_pos["entry"], "last": last,
                "stop": open_pos["stop"], "upnl": round(upnl, 4)}
    peak, mdd, cur = 50.0, 0.0, 50.0
    for t in ts:
        cur += t["pnl"]
        peak = max(peak, cur)
        mdd = max(mdd, 1 - cur / peak)
    return {"trades": len(rs), "wins": len(w), "losses": len(lo), "win_rate": round(len(w) / len(rs), 3) if rs else None,
            "stop_exits": sum(1 for t in ts if t["why"] == "stop"), "ladder_exits": sum(1 for t in ts if t["step"] > 0),
            "r_sum": round(float(sum(rs)), 2), "avg_win_r": round(float(np.mean(w)), 2) if w else None,
            "avg_loss_r": round(float(np.mean(lo)), 2) if lo else None, "best_r": round(max(rs), 2) if rs else None,
            "end_equity": round(eq, 3), "pnl_usd": round(eq - 50.0, 3), "max_dd_equity": round(mdd, 4),
            "open_at_end": mark, "entries_per_day": round(sum(counts) / n_days, 2),
            "days_by_entries": {str(k): counts.count(k) for k in sorted(set(counts))},
            "skips": R.skip_counts(rows), "trades_list": ts}


def cmd_run(args) -> int:
    cfg = M.load_config(R.CONFIG)
    risk = cfg.risk_pct
    R.T0, R.T1 = T0, T1                                         # the replay's period globals: the 20 days
    bars30, bars1h, info, decided, checks = {}, {}, {}, {}, {}
    for co in cfg.coins:
        bars30[co.symbol] = read(args.data, co.symbol, "30m")
        bars1h[co.symbol] = read(args.data, co.symbol, "1h")
        info[co.symbol] = {"30m": R.gaps(bars30[co.symbol], M.MIN30), "1h": R.gaps(bars1h[co.symbol], M.H1),
                           "last_30m_open": time.strftime("%m-%d %H:%M", time.gmtime(bars30[co.symbol][-1, 0] / 1000))}
        decided[co.symbol], checks[co.symbol] = R.decisions(co, bars30[co.symbol], bars1h[co.symbol], sample=400)
        print(co.symbol, info[co.symbol], checks[co.symbol], flush=True)

    def spec_live(sym):
        return {"qty_step": 0.0, "min_qty": 0.0, "tick": 0.0, "min_notional": R.MIN_ORDER_USDT}

    MinuteBot.m1 = {co.symbol: read(args.data, co.symbol, "1m") for co in cfg.coins}
    for co in cfg.coins:
        info[co.symbol]["1m"] = R.gaps(MinuteBot.m1[co.symbol], MIN1)
    keep, keep_bot = M.ladder_stop, R.ReplayBot
    variants, same = {}, {}
    try:
        for upd, bot in (("", keep_bot), ("_1m", MinuteBot)):
            R.ReplayBot = bot
            for name, (label, fn) in LADDERS.items():
                M.ladder_stop = fn or keep
                res = R.run_bot(list(cfg.coins), decided, bars30, fee=FEE, blocks=True, spec_fn=spec_live)
                ts = trade_rows(res["rows"], risk, bars30)
                variants[name + upd] = {"label": label + (" · 1분마다 손절 갱신" if upd else " · 30분봉 마감에 갱신 (봇 방식)"),
                                        **summarize(res, res["rows"], ts, bars30)}
                v = variants[name + upd]
                print(f"{name + upd}: {v['trades']} trades {v['wins']}W {v['losses']}L  R {v['r_sum']:+.2f}  "
                      f"${v['end_equity']:.3f}", flush=True)
                if name == "now" and not upd:
                    M.ladder_stop = keep
                    same = same_entries(ts, res["rows"], MinuteBot.m1)
    finally:
        M.ladder_stop, R.ReplayBot = keep, keep_bot
    out = {"what": "믹스 30분 봇 20일 재생 (봇 자기 코드, 실거래 규칙) · 계단만 바꿔 비교 (research/mixchop20d/ladder20.py)",
           "made_utc": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()),
           "period": {"from": "2026-10-05 00:00 UTC", "to": "2026-10-25 00:00 UTC", "days": (T1 - T0) // 86_400_000},
           "rules": {"start_equity": 50.0, "risk_pct": risk, "fee_side": FEE, "one_position": True,
                     "blocks": "주말(KST)·나스닥 개장 ±30분·미국 지표 ±30분", "min_order_usd": R.MIN_ORDER_USDT,
                     "coins": [{"symbol": c.symbol, "sl_atr": c.sl_atr, "roe_act": c.roe_act, "leverage": c.leverage} for c in cfg.coins]},
           "data": info, "checks": checks,
           "code": {"mixchop_sha256": R.file_sha(os.path.join(ROOT, "paperbot", "mixchop.py")),
                    "config_sha256": R.file_sha(R.CONFIG)},
           "variants": variants, "same_entries_1m": same,
           "not_modelled": ["실거래는 봉 마감 몇 초 뒤 시장가 체결 (재생은 신호 봉 종가)", "WOO X Pro 가격 기준 손절 (재생은 바이낸스 30분봉)",
                            "펀딩비", "코인별 주문 단위 ($5 최소 주문만 반영)"]}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=float)
        fh.write("\n")
    print("wrote", args.out)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ladder20.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("download", "run", "all"))
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args(argv)
    if a.cmd in ("download", "all"):
        cmd_download(a)
    if a.cmd in ("run", "all"):
        return cmd_run(a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
