"""친구봇 두 번째 매매법 시험 (owners 10-26): "30분봉 진입 슈퍼트렌드 14/3, 14/6 같은 상승 추세이고 스톡RSI 14/11/4/5를
사용하고 골든 크로스를 하는데 RSI26이 50 위에 있고 그리고 1시간봉 RSI26도 50 위에 있으면 롱 진입. 1시간봉은 슈퍼트렌드 사용
안 함. 숏은 반대 조건".

The new rule, read on each closed 30m bar (TradingView's built-in indicators, Pine v5):
  long  = supertrend(ATR 14, factor 3) up AND supertrend(ATR 14, factor 6) up
          AND Stoch RSI %K crosses above %D on this bar (RSI length 14, stochastic length 11, %K SMA 4, %D SMA 5)
          AND RSI(26) of the 30m closes > 50 AND RSI(26) of the last CLOSED 1h bar > 50
  short = the mirror (both supertrends down, %K crosses below %D, both RSI(26) < 50)
  ("14/11/4/5" read as RSI 14 / stochastic 11 / K 4 / D 5; the other order TradingView's legend shows, K 14 / D 11 /
  RSI 4 / stochastic 5, is the variant ``alt``.)

The bot is the friend bot's OWN code (paperbot/mixchop.py Bot in paper mode, PaperBroker), configured as it runs live
(deploy/mixchop.live.json: six coins in its order, one position, margin = 40 % of equity at the coin's leverage, the net
ROE ladder 12 -> 10 then +5 a step on closed 1m bars, the weekend / Nasdaq-open / US-release entry blocks, $10,000 at
most a position, WOO X Pro's taker 0.042 % a side, $5 minimum order); only its evaluate() is replaced by precomputed
answers:
  A    the friend's rule alone (replay.decisions: the real mixchop.evaluate at every colour change)
  B    the new rule alone
  C    both, the friend's answer first on a coin when both fire on the same bar (then the config's coin order)
The new rule's stop (the friend did not give one): ``atr`` = ATR(14, 30m) x the coin's sl_atr (as the friend's rule);
``st`` = the supertrend(14, 3) line at the signal bar. Either way the liquidation guard of evaluate() (stop inside the
coin's leverage less 0.5 % maintenance margin) drops a signal whose stop is too far.
Windows: every calendar month (UTC) 2021-10 .. 2026-09 from a fresh $50 with the 70 % floor off (each month on its
own), the position of a month followed to its exit; and the recent 20 days 2026-10-05 .. 10-25 (research/mixchop20d
data) from $50. A coin-flip control (B's bars with a seeded random side) tells whether B's direction carries anything.
Data: research/mixchop5y/replay.py download (30m, 1h) + the 1m monthly zips (dl1m in the scratchpad: replay.fetch_one,
sha256-checked). Raw data never goes into git.
    python3 -I research/mixchop_st/study.py [--data DIR] [--data20 DIR] [--jobs 4]  ->  research/mixchop_st/summary.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import sys
import tempfile
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (ROOT, os.path.join(ROOT, "research", "mixchop5y"), os.path.join(ROOT, "research", "mixchop20d"),
          os.path.expanduser("~/.local/lib/python3.11/site-packages")):
    if p not in sys.path:
        sys.path.insert(0, p) if p.startswith(ROOT) else sys.path.append(p)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import replay as R  # noqa: E402
from paperbot import mixchop as M  # noqa: E402

OUT = os.path.join(HERE, "summary.json")
MAIN = dict(rsi=14, stoch=11, k=4, d=5)
ALT = dict(rsi=4, stoch=5, k=14, d=11)


def SPEC(symbol: str) -> dict:
    """WOO X Pro's $5 minimum order (the contract steps are not modelled)."""
    return {"qty_step": 0.0, "min_qty": 0.0, "tick": 0.0, "min_notional": R.MIN_ORDER_USDT}


# ====================================================================== TradingView's indicators
def sma(x, n: int) -> np.ndarray:
    """Pine ta.sma: NaN while the window holds a NaN."""
    return pd.Series(np.asarray(x, float)).rolling(n, min_periods=n).mean().to_numpy()


def stoch_rsi(close, rsi_len: int, stoch_len: int, k_len: int, d_len: int) -> tuple[np.ndarray, np.ndarray]:
    """TradingView 'Stoch RSI': k = sma(stoch(rsi, rsi, rsi, stoch_len), k_len), d = sma(k, d_len)."""
    r = M.rsi(close, rsi_len)
    s = pd.Series(r)
    lo = s.rolling(stoch_len, min_periods=stoch_len).min().to_numpy()
    hi = s.rolling(stoch_len, min_periods=stoch_len).max().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        st = np.where(hi > lo, 100.0 * (r - lo) / (hi - lo), np.nan)     # Pine: x / 0 is na
    k = sma(st, k_len)
    return k, sma(k, d_len)


def supertrend(high, low, close, atr_len: int, factor: float) -> tuple[np.ndarray, np.ndarray]:
    """Pine v5 ta.supertrend(factor, atr_len) as TradingView's built-in 'Supertrend' draws it: (line, up) with
    up = True where TradingView's direction is -1 (the green line under the price)."""
    h, l, c = (np.asarray(a, float) for a in (high, low, close))
    atr = M.atr(h, l, c, atr_len)
    hl2 = (h + l) / 2.0
    n = len(c)
    line, up = np.full(n, np.nan), np.zeros(n, dtype=bool)
    lb_prev = ub_prev = math.nan
    st_prev = math.nan
    for i in range(n):
        a = atr[i]
        lb, ub = hl2[i] - factor * a, hl2[i] + factor * a
        pl = 0.0 if math.isnan(lb_prev) else lb_prev               # nz(lowerBand[1])
        pu = 0.0 if math.isnan(ub_prev) else ub_prev
        c1 = c[i - 1] if i > 0 else math.nan
        lb = lb if (lb > pl or c1 < pl) else pl                    # comparisons with na are false
        ub = ub if (ub < pu or c1 > pu) else pu
        if i == 0 or math.isnan(atr[i - 1]):
            d = 1
        elif st_prev == pu:
            d = -1 if c[i] > ub else 1
        else:
            d = 1 if c[i] < lb else -1
        st = lb if d == -1 else ub
        line[i], up[i] = st, d == -1
        lb_prev, ub_prev, st_prev = lb, ub, st
    return line, up


def new_signals(co: "M.Coin", a30: np.ndarray, a1h: np.ndarray, p: dict, lo_ms: int, hi_ms: int) -> dict:
    """{close_ms: decision} for every 30m close in (lo_ms, hi_ms] where the new rule fires (the dicts mixchop.Bot.enter
    reads: side, close, close_ms, stop_dist (ATR x sl_atr), stop_st (to the supertrend 14/3 line), stop_pct, the RSIs)."""
    o = a30[:, 0].astype(np.int64)                                   # rows: open_ms, open, high, low, close
    h, l, c = a30[:, 2], a30[:, 3], a30[:, 4]
    ce = o + M.MIN30
    ln3, up3 = supertrend(h, l, c, 14, 3.0)
    _ln6, up6 = supertrend(h, l, c, 14, 6.0)
    k, d = stoch_rsi(c, p["rsi"], p["stoch"], p["k"], p["d"])
    kp, dp = np.r_[np.nan, k[:-1]], np.r_[np.nan, d[:-1]]
    with np.errstate(invalid="ignore"):
        gold, dead = (k > d) & (kp <= dp), (k < d) & (kp >= dp)
    r30 = M.rsi(c, 26)
    hc = a1h[:, 0].astype(np.int64) + M.H1
    r1h = M.rsi(a1h[:, 4], 26)
    j = np.searchsorted(hc, ce, side="right") - 1                    # the last 1h bar closed by each 30m close
    ok_h = (j >= 0) & (hc[np.maximum(j, 0)] == ce // M.H1 * M.H1)
    rh = np.where(ok_h, r1h[np.maximum(j, 0)], np.nan)
    atr = M.atr(h, l, c, 14)
    with np.errstate(invalid="ignore"):
        lng = up3 & up6 & gold & (r30 > 50) & (rh > 50)
        sht = (~up3) & (~up6) & dead & (r30 < 50) & (rh < 50)
    out = {}
    for i in np.flatnonzero((lng | sht) & (ce > lo_ms) & (ce <= hi_ms)):
        side = 1 if lng[i] else -1
        px = float(c[i])
        out[int(ce[i])] = {"symbol": co.symbol, "close_ms": int(ce[i]), "side": side, "why": "", "rule": "new",
                           "close": px, "atr": float(atr[i]), "dist_atr": float(atr[i]) * co.sl_atr,
                           "dist_st": abs(px - float(ln3[i])), "k": round(float(k[i]), 2), "d": round(float(d[i]), 2),
                           "avg_rsi_30m": round(float(r30[i]), 2), "avg_rsi_1h": round(float(rh[i]), 2)}
    return out


def with_stop(ev: dict, co: "M.Coin", how: str) -> dict:
    """The decision with its stop distance (``how`` = atr | st) and evaluate()'s liquidation guard."""
    e = dict(ev)
    dist = e["dist_atr"] if how == "atr" else e["dist_st"]
    px = e["close"]
    e["stop_dist"], e["stop_pct"] = dist, round(dist / px * 100, 3)
    e["liq_ok"] = bool(0 < dist < px * (1.0 / co.leverage - M.MMR_PCT / 100.0))
    if not e["liq_ok"]:
        e["why"] = f"손절 폭 {dist / px * 100:.2f}%가 {co.leverage}배 청산가보다 멂"
        e["side_wanted"], e["side"] = e["side"], 0
    return e


def check_window(co, a30, a1h, p, sigs, lo_ms, hi_ms, n=300, seed=3) -> dict:
    """The whole-series answers vs the same rule on the 1,499 closed bars the bot reads (the live code will do that)."""
    rng = np.random.default_rng(seed)
    ce_all = a30[:, 0].astype(np.int64) + M.MIN30
    cand = np.flatnonzero((ce_all > lo_ms) & (ce_all <= hi_ms) & (np.arange(len(a30)) >= R.HIST))
    pick = sorted(set(rng.choice(cand, size=min(n, len(cand)), replace=False).tolist())
                  | {int(np.searchsorted(ce_all, t)) for t in list(sigs)[:: max(1, len(sigs) // n)]})
    bad = 0
    for i in pick:
        b30 = a30[i - R.HIST + 1:i + 1]
        jh = int(np.searchsorted(a1h[:, 0] + M.H1, ce_all[i], side="right"))
        b1h = a1h[max(0, jh - R.HIST):jh]
        got = new_signals(co, b30, b1h, p, int(ce_all[i]) - 1, int(ce_all[i]))
        want = int(ce_all[i]) in sigs
        if bool(got) != want or (got and sigs[int(ce_all[i])]["side"] != got[int(ce_all[i])]["side"]):
            bad += 1
    return {"checked": len(pick), "disagree": bad}


# ====================================================================== data
def read_1m(data: str, sym: str, mos: list) -> np.ndarray:
    cache = os.path.join(data, "npy", f"{sym}-1m-{mos[0]}-{mos[-1]}.npy")
    if os.path.exists(cache):
        return np.load(cache)
    rows = []
    for mo in mos:
        with zipfile.ZipFile(R.zip_path(data, sym, "1m", mo)) as z:
            names = [n for n in z.namelist() if n.endswith(".csv") and "/" not in n and ".." not in n]
            if len(names) != 1:
                raise RuntimeError(f"{sym} 1m {mo}: {z.namelist()}")
            text = z.read(names[0]).decode("ascii", "replace")
        for line in text.splitlines():
            f = line.split(",", 5)
            if len(f) < 5 or not f[0].strip().isdigit():
                continue
            t = int(f[0])
            if t > 10 ** 14:
                t //= 1000
            rows.append((t, float(f[1]), float(f[2]), float(f[3]), float(f[4])))
    a = np.array(rows, dtype=float)
    a = a[np.argsort(a[:, 0], kind="stable")]
    a = a[np.r_[a[1:, 0] != a[:-1, 0], True]]
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    np.save(cache, a)
    return a


# ====================================================================== the bot over one window
G: dict = {}            # the forked workers' data: coins, bars30, m1, decisions {variant: {sym: {ce: ev}}}


def run_window(variant: str, t0: int, t1: int, start_eq: float = 50.0) -> dict:
    coins = [M.Coin(**vars(c)) for c in G["coins"]]
    raw = json.load(open(R.CONFIG, encoding="utf-8"))
    cfg = M.Config(mode="paper", state=os.path.join(tempfile.gettempdir(), "mixchop-st-none", "state.json"), log="",
                   coins=coins, risk_pct=float(raw["risk_pct"]), equity_floor_frac=0.0, start_equity=start_eq,
                   kill_file="", own_stop_file="", max_notional_usd=float(raw["max_notional_usd"]), taker_fee=R.TAKER,
                   telegram=False, no_weekend=bool(raw["no_weekend"]), us_open_pre_min=int(raw["us_open_pre_min"]),
                   us_open_pause_min=int(raw["us_open_pause_min"]), macro_blackout_min=int(raw["macro_blackout_min"]),
                   margin_frac=float(raw["margin_frac"]),
                   ladder=G.get("ladder_of", {}).get(variant) or {k: float(v) for k, v in raw["ladder"].items()},
                   ladder_every_s=float(raw["ladder_every_s"]))
    dec = G["decided"][G.get("dec_of", {}).get(variant, variant)]     # grid.py: many ladders on one set of answers
    bars30, m1 = G["bars30"], G["m1"]
    clock = R.Clock()
    o30 = {s: a[:, 0].astype(np.int64) for s, a in bars30.items()}
    o1 = {s: a[:, 0].astype(np.int64) for s, a in m1.items()}

    def fetch(symbol: str, tf: str, n: int) -> list:
        a, o = (m1[symbol], o1[symbol]) if tf == "1m" else (bars30[symbol], o30[symbol])
        j = int(np.searchsorted(o, clock.t, side="right"))
        return a[max(0, j - n):j].tolist()

    def evaluate(co, b30, b1h, ce):
        return dict(dec[co.symbol].get(ce) or {"symbol": co.symbol, "close_ms": ce, "side": 0, "why": "색 변화 없음"})

    broker = M.PaperBroker(start_eq, R.TAKER, SPEC)
    keep = M.evaluate
    M.evaluate = evaluate
    try:
        bot = R.ReplayBot(cfg, broker, fetch, clock, sleep=lambda s: None)
        clock.t = t0
        bot.start()
        ce = t0 + M.MIN30
        while ce <= t1:
            clock.t = ce + R.JUDGE_MS
            bot.on_close(ce)
            ce += M.MIN30
        n = 0
        while bot.pos is not None and n < 14 * 48:         # the month's last position, followed to its exit
            clock.t = ce + R.JUDGE_MS
            bot.manage(ce)
            ce += M.MIN30
            n += 1
    finally:
        M.evaluate = keep
    rows = bot.rows
    ens = {(r["symbol"], r["opened_ms"]): r for r in rows if r["kind"] == "entry"}
    trades = []
    for r in rows:
        if r["kind"] != "exit":
            continue
        en = ens[(r["symbol"], r["opened_ms"])]
        eb = float(en["equity_before"])
        w = en.get("why") or {}
        trades.append({"symbol": r["symbol"], "side": int(r["side"]), "t": int(r["opened_ms"]), "exit_t": int(r["ts"]),
                       "rule": w.get("rule", "friend"), "pnl": float(r["pnl"]), "ret": float(r["pnl"]) / eb,
                       "why": r["why"], "step": int(r.get("step") or 0), "stop_pct": w.get("stop_pct")})
    skips = {}
    for r in rows:
        if r["kind"] == "skip":
            key = "보유 중" if r["why"] == "보유 중" else ("같은 봉" if r["why"].startswith("같은 봉") else
                                                        "최소 주문" if r["why"].startswith("최소") else "진입 금지 시간")
            skips[key] = skips.get(key, 0) + 1
    return {"variant": variant, "t0": t0, "end_eq": broker.equity(), "open": bot.pos is not None, "trades": trades,
            "skips": skips}


def _job(a):
    return run_window(*a)


# ====================================================================== numbers
def summarize(res: list, start_eq: float = 50.0) -> dict:
    xs = np.array([r["end_eq"] / start_eq for r in res])
    ts = [t for r in res for t in r["trades"]]
    by_rule = {}
    for rule in ("friend", "new"):
        tt = [t for t in ts if t["rule"] == rule]
        if tt:
            rr = np.array([t["ret"] for t in tt])
            by_rule[rule] = {"n": len(tt), "win": round(float(np.mean(rr > 0)), 3), "avg_ret": round(float(rr.mean()), 4),
                             "stops": sum(1 for t in tt if t["why"] == "stop"),
                             "ladder": sum(1 for t in tt if t["why"] == "ladder")}
    skips = {}
    for r in res:
        for k, v in r["skips"].items():
            skips[k] = skips.get(k, 0) + v
    years = {}
    for r in res:
        y = time.strftime("%Y", time.gmtime(r["t0"] / 1000))
        years.setdefault(y, []).append(r["end_eq"] / start_eq)
    return {"months": len(xs), "median_x": round(float(np.median(xs)), 3), "mean_x": round(float(xs.mean()), 3),
            "geo_x": round(float(np.exp(np.mean(np.log(np.maximum(xs, 1e-9))))), 3),
            "up_months": int((xs > 1).sum()), "x2_months": int((xs >= 2).sum()), "x6_months": int((xs >= 6).sum()),
            "half_or_worse": int((xs <= 0.5).sum()), "worst_x": round(float(xs.min()), 3), "best_x": round(float(xs.max()), 3),
            "trades": len(ts), "trades_per_month": round(len(ts) / max(1, len(xs)), 1),
            "win": round(float(np.mean([t["ret"] > 0 for t in ts])), 3) if ts else None, "by_rule": by_rule, "skips": skips,
            "by_year_median": {y: round(float(np.median(v)), 3) for y, v in sorted(years.items())},
            "by_month": [[time.strftime("%Y-%m", time.gmtime(r["t0"] / 1000)), round(r["end_eq"] / start_eq, 3),
                          len(r["trades"])] for r in res]}


def month_bounds() -> list:
    out, (y, m) = [], (2021, 10)
    while (y, m) <= (2026, 9):
        a = int(pd.Timestamp(f"{y:04d}-{m:02d}-01", tz="UTC").value // 1_000_000)
        y2, m2 = (y + 1, 1) if m == 12 else (y, m + 1)
        b = int(pd.Timestamp(f"{y2:04d}-{m2:02d}-01", tz="UTC").value // 1_000_000)
        out.append((a, b))
        y, m = y2, m2
    return out


def build_variants(coins, friend: dict, new_main: dict, new_alt: dict, seeds=(1, 2, 3)) -> tuple[dict, dict]:
    """{variant: {sym: {ce: ev}}} and the counts of the new rule's signals (fired, dropped by the liquidation guard)."""
    V, counts = {"A": {c.symbol: friend[c.symbol] for c in coins}}, {}
    for tag, src in (("", new_main), ("alt_", new_alt)):
        for how in ("atr", "st"):
            if tag and how == "st":
                continue
            b = {c.symbol: {t: with_stop(e, c, how) for t, e in src[c.symbol].items()} for c in coins}
            counts[f"{tag}{how}"] = {c.symbol: {"fired": len(b[c.symbol]),
                                                "liq_dropped": sum(1 for e in b[c.symbol].values() if not e["liq_ok"]),
                                                "long": sum(1 for e in b[c.symbol].values() if e["side"] > 0),
                                                "short": sum(1 for e in b[c.symbol].values() if e["side"] < 0)}
                                     for c in coins}
            V[f"B_{tag}{how}"] = b
            V[f"C_{tag}{how}"] = {c.symbol: {**b[c.symbol], **{t: e for t, e in friend[c.symbol].items() if e["side"]}}
                                  for c in coins}
            if not tag and how == "atr":
                for s in seeds:
                    rng = np.random.default_rng(s)
                    V[f"B_flip{s}"] = {c.symbol: {t: (dict(e, side=int(rng.choice([-1, 1]))) if e["side"] else e)
                                                  for t, e in sorted(b[c.symbol].items())} for c in coins}
    return V, counts


def friend_decisions(coins, a30, a1h, cache: str) -> tuple[dict, dict]:
    if os.path.exists(cache):
        with open(cache, "rb") as f:
            return pickle.load(f)
    with ProcessPoolExecutor(4) as ex:
        res = list(ex.map(_friend_one, [(c, a30[c.symbol], a1h[c.symbol], R.T0, R.T1) for c in coins]))
    out = ({c.symbol: r[0] for c, r in zip(coins, res)}, {c.symbol: r[1] for c, r in zip(coins, res)})
    with open(cache, "wb") as f:
        pickle.dump(out, f)
    return out


def _friend_one(a):
    co, a30, a1h, t0, t1 = a
    R.T0, R.T1 = t0, t1
    d, chk = R.decisions(co, a30, a1h, sample=300)
    for e in d.values():
        e["rule"] = "friend"
    return d, chk


def run_variants(V: dict, windows: list, jobs: int) -> dict:
    G["decided"] = V
    work = [(v, a, b) for v in V for a, b in windows]
    with ProcessPoolExecutor(jobs) as ex:
        res = list(ex.map(_job, work, chunksize=4))
    out = {}
    for r in res:
        out.setdefault(r["variant"], []).append(r)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=R.DATA)
    ap.add_argument("--data20", default=os.path.join(R.SCRATCH, "mixchop20d_data"))
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--skip5y", action="store_true")
    a = ap.parse_args(argv)
    cfg = M.load_config(R.CONFIG)
    coins = list(cfg.coins)
    summary = {"rule": "ST(14,3)+ST(14,6) same side + StochRSI K/D cross + RSI26 30m and closed 1h on the side of 50",
               "stoch_main": MAIN, "stoch_alt": ALT, "config": os.path.relpath(R.CONFIG, ROOT)}
    t_start = time.time()
    if not a.skip5y:
        a30 = {c.symbol: R.read_klines(a.data, c.symbol, "30m") for c in coins}
        a1h = {c.symbol: R.read_klines(a.data, c.symbol, "1h") for c in coins}
        mos = [m for m in R.months() if "2021-10" <= m <= "2026-09"]
        G["m1"] = {c.symbol: read_1m(a.data, c.symbol, mos) for c in coins}
        G["bars30"], G["coins"] = a30, coins
        print(f"data {time.time() - t_start:.0f}s", flush=True)
        friend, fchk = friend_decisions(coins, a30, a1h, os.path.join(a.data, "npy", "friend_decisions_v2.pkl"))
        print(f"friend decisions {time.time() - t_start:.0f}s", fchk, flush=True)
        lo, hi = R.T0 - 2 * 86_400_000, R.T1 + 30 * 86_400_000
        nm = {c.symbol: new_signals(c, a30[c.symbol], a1h[c.symbol], MAIN, lo, hi) for c in coins}
        na = {c.symbol: new_signals(c, a30[c.symbol], a1h[c.symbol], ALT, lo, hi) for c in coins}
        chk = {c.symbol: check_window(c, a30[c.symbol], a1h[c.symbol], MAIN, nm[c.symbol], lo, R.T1) for c in coins}
        print("new rule window check", chk, flush=True)
        V, counts = build_variants(coins, friend, nm, na)
        res = run_variants(V, month_bounds(), a.jobs)
        summary["five_years"] = {"window": "2021-10 .. 2026-09, each month from $50, floor off",
                                 "friend_check": fchk, "new_window_check": chk, "new_signal_counts": counts,
                                 "variants": {v: summarize(r) for v, r in res.items()}}
        print(f"5y done {time.time() - t_start:.0f}s", flush=True)
    # the recent 20 days
    import ladder20 as L
    G["coins"] = coins
    G["bars30"] = {c.symbol: L.read(a.data20, c.symbol, "30m") for c in coins}
    b1h = {c.symbol: L.read(a.data20, c.symbol, "1h") for c in coins}
    G["m1"] = {c.symbol: L.read(a.data20, c.symbol, "1m") for c in coins}
    R.T0, R.T1 = L.T0, L.T1
    friend20 = {}
    for c in coins:
        d, _ = R.decisions(c, G["bars30"][c.symbol], b1h[c.symbol], sample=10)
        for e in d.values():
            e["rule"] = "friend"
        friend20[c.symbol] = d
    nm20 = {c.symbol: new_signals(c, G["bars30"][c.symbol], b1h[c.symbol], MAIN, L.T0 - 86_400_000, L.T1) for c in coins}
    na20 = {c.symbol: new_signals(c, G["bars30"][c.symbol], b1h[c.symbol], ALT, L.T0 - 86_400_000, L.T1) for c in coins}
    V20, counts20 = build_variants(coins, friend20, nm20, na20)
    res20 = run_variants(V20, [(L.T0, L.T1)], a.jobs)
    summary["recent_20d"] = {"window": "2026-10-05 .. 10-25 from $50", "new_signal_counts": counts20,
                             "variants": {v: {**summarize(r), "list": r[0]["trades"]} for v, r in res20.items()}}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    for part in ("five_years", "recent_20d"):
        if part not in summary:
            continue
        print(f"\n== {part}")
        for v, s in summary[part]["variants"].items():
            print(f"{v:12s} med x{s['median_x']:<6} mean x{s['mean_x']:<7} geo x{s['geo_x']:<6} up {s['up_months']:>2}/{s['months']} "
                  f"x2 {s['x2_months']:>2} x6 {s['x6_months']:>2} <=x0.5 {s['half_or_worse']:>2} worst x{s['worst_x']:<6} "
                  f"trades {s['trades']:>4} win {s['win']} {json.dumps(s['by_rule'], ensure_ascii=False)}", flush=True)
    print(f"total {time.time() - t_start:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
