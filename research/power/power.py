"""Statistical power of the 30-day checkpoint (owners approved 2026-10-04): if an account had a TRUE edge of
+X net ROE per trade over a coin flip, how likely would it pass the day-30 / day-60 / day-90 checkpoint
(v3: addendum Q1-Q3, 2,000 coin-flip bots per account, Benjamini-Hochberg at FDR 10% over the accounts tested)?

Paper v4 (2026-10-05, version 2 of out/power.json): the verdict schemes are compared side by side (``SCHEMES``):
"split" = the owners' choice D5 (b), the core family (108 judged accounts of the 36) at alpha 0.07 with 10,000 bots
(the DeepSeek family 132 at 0.025, the reel alone at 0.005); "one" = option (a), one BH family over all 241 judged
accounts at 0.10 with 10,000 bots; "v3" = the v3 rule (108 at 0.10, 2,000 bots) for reference. The reel (5m) gets its
own pool: random long entries with the reel's own exits (paperbot/reel_engine.py ``simulate_exit`` on 5m bars, the
PREREG's low-first order) at the reel's H1 signal rate (config.V4_FLIP5M), 'normal' leverage; judged alone at 0.005.

    python3 research/power/power.py run [--out research/power/out/power.json] [--reps 4000] [--null 20000]
    python3 research/power/power.py selftest

Read-only research: nothing here trades or touches a database. The result JSON (``out/power.json``, committed)
is what ``paperbot/agents/power.py`` shows to the 30-day checkpoint meeting and the Saturday learning meeting.

How (every number is code; the choices are fixed here, before looking at any live result)
1. Coin-flip trades under the paper rules, from the SAME machinery as the 5-year card and the coin-flip bots:
   ``research/paper_rules/rules_bt.py`` (``random_signals`` + ``simulate``: next-bar entry with slippage, stop
   2 x ATR14 (V3_STOP_ATR), the owners' sizing tiers under the run's leverage rule (``LEVERAGE_RULE``, since
   2026-10-04 quality_v1: a coin flip is 'best' with config.V3_P_BEST[tf]), the stepped profit lock, one position at a time, coin
   priority, liquidation, bust) on the Binance USD-M futures bars in the repository (``data/pre2021``:
   2020-01 .. 2021-08, six coins; 30m is resampled from 15m). Each timeframe's signal rate per coin-bar is the
   MEDIAN strategy's rate of the 5-year cards (``signals_per_day`` / (6 coins x bars a day), cards.json), as the
   checkpoint matches every bot's rate to its account's own. Consecutive 30-day windows x ``SEEDS`` seeds give a
   pool of coin-flip trades: each trade's net ROE on margin (R) and its margin as a share of the wallet before
   it (mf), and the accepted-trade rate per day while the account is alive (busy signals and sizing rejects
   left out by the engine rules themselves).
2. Monte Carlo of whole accounts in equity terms: per 30-day period N ~ Poisson(rate x 30) trades drawn with
   replacement from the pool (R, mf pairs), wallet x (1 + mf (R + X)) per trade, R + X never below -1 (a
   liquidation loses at most the margin), bust below the v3 line (10 / 5,000 of the start) and nothing after.
   X = 0 is the null: ``--null`` accounts give the 30 / 60 / 90-day end-equity distributions.
3. The checkpoint, as paperbot/checkpoint.py ``plan`` / ``decide`` judge it: the 1st verdict at the first
   checkpoint with >= 30 trades on the equity since the start (pass = equity > start, not bust, Q1 after FDR);
   a 1st pass is checked again on the next 30 days (>= 30 trades in them, P&L > 0, Q1 again on that window);
   a fail stays a fail. Q1: p = (bots >= account + 1) / (2,000 + 1); the number of the 2,000 bots at or above
   the account is drawn exactly as Binomial(2,000, S(v)), S = the null's share at or above v. FDR: the account
   with the edge is tested with ``family - 1`` accounts WITHOUT an edge (their p-values uniform), BH at 10%
   (checkpoint.ALPHA). ``family`` = 108 (36 strategies x 15m / 30m / 1h: 4h is observation only, addendum Q3;
   config.V3_Q1_MAIN_FAMILY) and 144 (every strategy account, 36 x 4: a stricter count).
4. 4h is computed for completeness but the checkpoint never judges it (observation only).
5. Timeframes: the run's (config.V3_TRADE_TFS: 15m, 30m, 1h, 4h). 5m was removed from the experiment on
   2026-10-04 with the restart (docs/paper-v3-rules-change-1.md); until then this script also ran 5m and used the
   families 144 (36 x 5m..1h) and 180.

Assumptions that make this an estimate, not a promise (also in the JSON ``assumptions``): trades are drawn
independently (no streaks beyond chance, no regime changes); the edge is the same on every trade; the coin
flips' trade shape comes from 2020-01 .. 2021-08 bars; the other accounts are all without an edge (more real
edges elsewhere would make BH slightly easier); one rate per timeframe (the median strategy).

Runtime (the full grid: 4 timeframes x 6 edges, ``reps`` 4,000, ``null`` 20,000; seconds in the development
container): the JSON keeps the measured times (``runtime_s``). ``tests/test_power.py`` runs a tiny grid on
synthetic bars in about a second. 4h: the 2020-21 bars give too few coin-flip trades (most 4h signals fail the
sizing rule, as in the live run) for a Monte Carlo (``too_few``); 4h is observation only anyway.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import gzip
import json
import math
import os
import sys
import time
from typing import Optional

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research", "paper_rules"))

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "power.json")
DATA = os.path.join(ROOT, "data", "pre2021")
CARDS = os.path.join(ROOT, "research", "strategy_profiles", "out_binance", "cards.json")
from paperbot.config import (V3_OBSERVE_TFS, V3_Q1_MAIN_FAMILY, V3_STRATEGIES,  # noqa: E402
                             V3_TRADE_TFS, V4_FLIP5M, V4_GROUP_JUDGED, V4_JUDGED_ACCOUNTS)
TFS = V3_TRADE_TFS                                  # 15m, 30m, 1h, 4h: the core group's (house exits)
REEL_TF = "5m"                                      # the reel's pool (its own exits), judged alone
EDGES = (0.0, 0.005, 0.01, 0.02, 0.05, 0.10)      # + net ROE per trade (0.01 = +1% of the margin)
FAMILIES = (V3_Q1_MAIN_FAMILY, V3_STRATEGIES * len(V3_TRADE_TFS))   # (108, 144): the judged ones, every strategy acct
# Paper v4 verdict schemes (owners' D5): family = accounts in the target's BH family, alpha, bots per account.
# "split" is the chosen one (checkpoint.FAMILY_ALPHA); "one" the single family over every judged account.
SCHEMES = {
    "split": {"family": V4_GROUP_JUDGED["core"], "alpha": 0.07, "n_bots": 10_000,
              "what": "owners' D5 (b): core family 108 at FDR 7%, 10,000 bots"},
    "one": {"family": V4_JUDGED_ACCOUNTS, "alpha": 0.10, "n_bots": 10_000,
            "what": "D5 (a): one family over all 241 judged accounts at FDR 10%, 10,000 bots"},
    "v3": {"family": V3_Q1_MAIN_FAMILY, "alpha": 0.10, "n_bots": 2_000,
           "what": "the v3 rule: 108 at FDR 10%, 2,000 bots (reference)"},
}
REEL_SCHEMES = {
    "split": {"family": V4_GROUP_JUDGED["reel"], "alpha": 0.005, "n_bots": 10_000,
              "what": "owners' D5 (b): the reel alone at FDR 0.5%, 10,000 bots"},
    "one": {"family": V4_JUDGED_ACCOUNTS, "alpha": 0.10, "n_bots": 10_000,
            "what": "D5 (a): one family over all 241 judged accounts at FDR 10%, 10,000 bots"},
}
CHOSEN = "split"
NO_5M = ("5m removed for the 36 on 2026-10-04 (docs/paper-v3-rules-change-1.md): 5-year data -2.3% equity per trade, "
         "34 of 36 cells significantly negative; paper v4's only 5m account is the reel (own exits, judged alone)")
SEEDS = (1, 2, 3)
SEED = 20261004
PERIOD_DAYS = 30
CHECKPOINTS = (30, 60, 90)
WARMUP_BARS = 300                                   # ATR14 settles (as checkpoint.ATR_PREFIX_BARS)
MIN_POOL = 100                                      # fewer coin-flip trades in the pool: no Monte Carlo
TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}
# Leverage of the coin flips: the restarted run's rule (config.V3_LEVERAGE_RULE, owners 2026-10-04): each coin-flip
# signal is 'best' with probability config.V3_P_BEST[tf] (50x / 50%, 40x / 40%, then 30x / 30%, 20x / 20%), else
# 'normal' (30x / 30%, 20x / 20%), as the live coin-flip accounts and the checkpoint's bots. "tier_walk" = rules_bt's own
# sizing (every signal 40% x 50x first, then 40x, 30x, 20x), the rule of power.json before 2026-10-04.
LEVERAGE_RULE = "quality_v1"


def _cp():
    from paperbot import checkpoint as CP
    return CP


def v3_numbers() -> dict:
    from paperbot.config import V3_INITIAL, V3_STOP_ATR, v3_settings
    CP = _cp()
    s = v3_settings()
    return {"initial": float(V3_INITIAL), "bust_below": float(s.bust_below), "stop_atr": float(V3_STOP_ATR),
            "n_bots": int(CP.N_BOTS), "alpha": float(CP.ALPHA), "min_trades": int(CP.MIN_TRADES)}


# ---------------------------------------------------------------- 1. the coin-flip trade pool
class _TfLib:
    """What rules_bt needs from the locked library (``tf_minutes``) when it is not loaded."""

    @staticmethod
    def tf_minutes(tf: str) -> int:
        return TF_MIN[tf]


def lib():
    try:
        from paperbot import sweepsig
        return sweepsig.lib()
    except Exception:  # noqa: BLE001  (only tf_minutes is used here)
        return _TfLib()


def _atr14(h: np.ndarray, lo: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Wilder ATR14 (fg_indicators.atr: RMA of the true range)."""
    pc = np.concatenate([[np.nan], c[:-1]])
    tr = np.nanmax(np.vstack([h - lo, np.abs(h - pc), np.abs(lo - pc)]), axis=0)
    out = np.full(len(tr), np.nan)
    if len(tr) < 14:
        return out
    a = float(np.mean(tr[:14]))
    out[13] = a
    for i in range(14, len(tr)):
        a += (tr[i] - a) / 14.0
        out[i] = a
    return out


def _read_csv(path: str) -> dict:
    import pandas as pd
    df = pd.read_csv(path)
    ts = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None).to_numpy().astype("datetime64[ns]").astype(np.int64)
    return {"ts": ts, "o": df["open"].to_numpy(float), "h": df["high"].to_numpy(float),
            "l": df["low"].to_numpy(float), "c": df["close"].to_numpy(float)}


def _resample_pairs(b: dict, k: int = 2) -> dict:
    """15m -> 30m: bars grouped by their 30-minute open time (incomplete groups dropped)."""
    span = 30 * 60 * 10 ** 9
    key = b["ts"] // span
    out = {k_: [] for k_ in ("ts", "o", "h", "l", "c")}
    uniq, start, counts = np.unique(key, return_index=True, return_counts=True)
    for u, s0, n in zip(uniq, start, counts):
        if n != k:
            continue
        sl = slice(s0, s0 + n)
        out["ts"].append(u * span)
        out["o"].append(b["o"][s0])
        out["h"].append(b["h"][sl].max())
        out["l"].append(b["l"][sl].min())
        out["c"].append(b["c"][s0 + n - 1])
    return {k_: np.asarray(v, dtype=np.int64 if k_ == "ts" else float) for k_, v in out.items()}


def load_bars(tf: str, data_dir: str = DATA) -> dict:
    """{rules_bt coin: {ts (ns), o, h, l, c, atr}} from data/pre2021 (Binance USD-M futures)."""
    import rules_bt as RB
    out = {}
    for coin in RB.COINS:
        src = "15m" if tf == "30m" else tf
        path = os.path.join(data_dir, f"{coin.lower()}-{src}.csv.gz")
        if not os.path.exists(path):
            continue
        b = _read_csv(path)
        if tf == "30m":
            b = _resample_pairs(b)
        b["atr"] = _atr14(b["h"], b["l"], b["c"])
        out[coin] = b
    return out


def card_rates(cards_path: str = CARDS) -> dict:
    """{tf: (median signals a day of the 36 strategies, rate per coin-bar)} from the 5-year cards."""
    with open(cards_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    out = {}
    for tf in TFS:
        v = sorted(r["signals_per_day"] for c in doc["cards"] for r in c["rows"]
                   if r["tf"] == tf and r.get("signals_per_day") is not None)
        if not v:
            continue
        med = float(np.median(v))
        out[tf] = (med, med / (6 * 1440 / TF_MIN[tf]))
    return out


@contextlib.contextmanager
def leverage_rule(rule: str, tf: str, seed: int):
    """rules_bt.simulate sizing under ``rule``: "tier_walk" leaves it alone; "quality_v1" swaps rules_bt's
    ``size_position`` (only while the block runs; rules_bt.py itself is unchanged) for the run's quality_v1 tiers
    with each signal's group drawn 'best' with probability config.V3_P_BEST[tf] from its own seeded stream."""
    import rules_bt as RB
    if rule == "tier_walk":
        yield
        return
    if rule != "quality_v1":
        raise ValueError(f"unknown leverage rule {rule!r}")
    from dataclasses import replace
    from paperbot.config import V3_BEST_FALLS_TO_NORMAL, V3_P_BEST, V3_QUALITY_TIERS
    from paperbot.levrule import GROUP_SALT
    s = replace(RB.SETTINGS, leverage_rule="quality_v1", tiers=V3_QUALITY_TIERS, max_margin_frac=0.50,
                best_falls_to_normal=V3_BEST_FALLS_TO_NORMAL)
    real = RB.size_position
    rng = np.random.default_rng([GROUP_SALT, int(seed), TF_MIN[tf]])
    p = float(V3_P_BEST.get(tf, 0.0))

    def sized(_settings, equity, side, entry, stop, _requested, brackets, **kw):
        return real(s, equity, side, entry, stop, "best" if rng.random() < p else "normal", brackets, **kw)

    RB.size_position = sized
    try:
        yield
    finally:
        RB.size_position = real


def build_pool(bars: dict, tf: str, rate: float, seeds=SEEDS, window_days: int = PERIOD_DAYS, L=None,
               stop_atr: Optional[float] = None, max_windows: Optional[int] = None, rule: str = LEVERAGE_RULE) -> dict:
    """Coin-flip trades of rules_bt in consecutive ``window_days`` windows (each a fresh account) x ``seeds``,
    sized with the leverage ``rule`` (``leverage_rule``). Returns R (net ROE on margin), mf (margin / wallet
    before), the trades and alive days, and per window the bust flag and trade count."""
    import rules_bt as RB
    L = L or lib()
    k = float(stop_atr if stop_atr is not None else v3_numbers()["stop_atr"])
    coins = [c for c in RB.COINS if c in bars]
    t_lo = max(int(bars[c]["ts"][min(WARMUP_BARS, len(bars[c]["ts"]) - 1)]) for c in coins)
    t_hi = min(int(bars[c]["ts"][-1]) for c in coins)
    span = window_days * 86_400 * 10 ** 9
    edges = list(range(t_lo, t_hi - span + 1, span))
    if max_windows is not None:
        edges = edges[:max_windows]
    R, MF, wins = [], [], []
    alive_days = 0.0
    for seed in seeds:
        sig = RB.random_signals(bars, None, rate, int(seed), tf, L)
        for w0 in edges:
            w1 = w0 + span
            bounds = {c: (max(int(np.searchsorted(bars[c]["ts"], w0)), WARMUP_BARS),
                          int(np.searchsorted(bars[c]["ts"], w1))) for c in coins}
            with leverage_rule(rule, tf, int(seed) * 100_003 + len(wins)):
                r = RB.simulate(bars, {c: sig[c] for c in coins}, bounds, k, tf, L, keep_trades=True)
            tt = r["trade_table"]
            if len(tt):
                R.append(tt["R"].to_numpy(float))
                MF.append(tt["margin_frac"].to_numpy(float))
            end = r["bust_ts"] if r["bust"] and r["bust_ts"] is not None else w1
            alive_days += max(0.0, (float(end) - w0) / 86_400e9)
            wins.append({"bust": bool(r["bust"]), "trades": int(r["trades"])})
    R_a = np.concatenate(R) if R else np.zeros(0)
    MF_a = np.concatenate(MF) if MF else np.zeros(0)
    ok = np.isfinite(R_a) & np.isfinite(MF_a) & (MF_a > 0)
    return {"R": R_a[ok], "mf": MF_a[ok], "trades": int(ok.sum()), "alive_days": alive_days,
            "rate_per_day": float(ok.sum() / alive_days) if alive_days else 0.0, "windows": wins}


def build_reel_pool(bars: dict, rate: float, seeds=SEEDS, window_days: int = PERIOD_DAYS,
                    max_windows: Optional[int] = None) -> dict:
    """Coin-flip trades with the reel's own exits (paper v4, the reel's control; owners' D2 (ii), D4) on 5m bars:
    each coin and bar fires long with ``rate`` while the account is flat (coin priority, one position), the stop = the
    lowest low of the last 12 bars (signal bar included) - 0.05 x ATR14, the first target the signal bar's upper band
    (then each bar's previous band), skip when stop >= fill or fill >= the first target, the 96-bar time exit
    (``reel_engine.simulate_exit``, the PREREG's low-first order); entry at the next bar's open + slippage, 'normal'
    leverage (30x / 30%, then 20x / 20%; config.V3_P_BEST["5m"] = 0), the exchange brackets of rules_bt; costs: taker
    on entry, stop and time exits, maker on the target; funding left out (holds of at most 8 hours). Coins are aligned
    on their common bar times (a bar missing for one coin is dropped for all). Same shape as ``build_pool``."""
    import pandas as pd
    import rules_bt as RB
    from paperbot.config import v3_settings
    from paperbot.reel_engine import MAX_HOLD_5M, STOP_BUF_ATR, simulate_exit, upper_bands
    from paperbot.sizing import size_position
    s = v3_settings()
    coins = [c for c in RB.COINS if c in bars]
    common = bars[coins[0]]["ts"]
    for c in coins[1:]:
        common = np.intersect1d(common, bars[c]["ts"])
    cols = {}
    for c in coins:
        b = bars[c]
        ix = np.searchsorted(b["ts"], common)
        o, h, lo, cl, a = (np.asarray(b[k], float)[ix] for k in ("o", "h", "l", "c", "atr"))
        cols[c] = {"open": o, "high": h, "low": lo, "close": cl, "atr": a, "upper": upper_bands(cl),
                   "low12": pd.Series(lo).rolling(12, min_periods=12).min().to_numpy()}
    n = len(common)
    span = window_days * 288
    t_lo = WARMUP_BARS
    edges = list(range(t_lo, n - span, span))
    if max_windows is not None:
        edges = edges[:max_windows]
    R, MF, wins = [], [], []
    alive_days = 0.0
    taker, maker, slip = s.taker_fee, s.maker_fee, s.slippage_frac
    for seed in seeds:
        rng = np.random.default_rng([SEED, int(seed), 5])
        for w0 in edges:
            w1 = w0 + span
            wallet, trades, bust_at = float(s.initial_equity), 0, None
            j = w0
            while j < w1 - 1:
                fire = rng.random(len(coins)) < rate
                done = False
                for ci in np.nonzero(fire)[0]:
                    x = cols[coins[ci]]
                    a, e = x["atr"][j], j + 1
                    if not (np.isfinite(a) and a > 0 and np.isfinite(x["low12"][j]) and np.isfinite(x["upper"][j])):
                        continue
                    fill = x["open"][e] * (1 + slip)
                    stop = x["low12"][j] - STOP_BUF_ATR * a
                    if stop >= fill or fill >= x["upper"][j]:
                        continue
                    d = size_position(s, wallet, 1, fill, stop, "normal", RB.BRACKETS, atr=a)
                    if not d.ok:
                        continue
                    last = min(e + MAX_HOLD_5M, w1)
                    xi, px, why = simulate_exit({k: x[k][:last] for k in ("open", "high", "low", "close", "upper")},
                                                e, fill, stop)
                    if xi is None:
                        continue
                    out = px * (1 - slip) if why in ("SL", "TIME", "EOD") else px
                    fee = d.qty * fill * taker + d.qty * out * (maker if why == "TP" else taker)
                    pnl = max(d.qty * (out - fill) - fee, -d.margin)
                    R.append(pnl / d.margin)
                    MF.append(d.margin / wallet)
                    wallet += pnl
                    trades += 1
                    j = xi + 1
                    done = True
                    break
                if not done:
                    j += 1
                if wallet < s.bust_below:
                    bust_at = j
                    break
            end = bust_at if bust_at is not None else w1
            alive_days += max(0.0, (end - w0) / 288.0)
            wins.append({"bust": bust_at is not None, "trades": trades})
    R_a, MF_a = np.asarray(R, float), np.asarray(MF, float)
    ok = np.isfinite(R_a) & np.isfinite(MF_a) & (MF_a > 0)
    return {"R": R_a[ok], "mf": MF_a[ok], "trades": int(ok.sum()), "alive_days": alive_days,
            "rate_per_day": float(ok.sum() / alive_days) if alive_days else 0.0, "windows": wins}


# ---------------------------------------------------------------- 2. Monte Carlo accounts
def simulate_accounts(R: np.ndarray, mf: np.ndarray, rate_per_day: float, n: int, edge: float, rng,
                      bust_frac: float, periods: int = len(CHECKPOINTS), period_days: int = PERIOD_DAYS,
                      chunk: int = 2000) -> dict:
    """``n`` accounts of ``periods`` x ``period_days``: per period N ~ Poisson(rate x days) trades drawn from
    the pool, wallet x (1 + mf (R + edge)), bust below ``bust_frac`` of the start (nothing after). Returns per
    period end (1..periods): equity (start = 1), trades so far, bust so far."""
    lam = rate_per_day * period_days
    eq = np.ones((n, periods))
    trades = np.zeros((n, periods), dtype=np.int64)
    bust = np.zeros((n, periods), dtype=bool)
    lb = math.log(bust_frac)
    P = len(R)
    lr_pool = None
    for a in range(0, n, chunk):
        m = min(chunk, n - a)
        cnt = rng.poisson(lam, size=(m, periods))
        cum_n = np.cumsum(cnt, axis=1)
        tot = int(cum_n[:, -1].max()) if m else 0
        if tot == 0 or P == 0:
            trades[a:a + m] = cum_n
            continue
        if lr_pool is None:
            lr_pool = np.log1p(np.maximum(mf * np.maximum(R + edge, -1.0), -1.0 + 1e-12))
        idx = rng.integers(0, P, size=(m, tot))
        lr = lr_pool[idx]
        valid = np.arange(tot)[None, :] < cum_n[:, -1:]
        lr = np.where(valid, lr, 0.0)
        cum = np.cumsum(lr, axis=1)
        dead = (cum < lb) & valid
        first_dead = np.where(dead.any(axis=1), dead.argmax(axis=1), tot + 1)
        for p in range(periods):
            k = cum_n[:, p]                                    # trades drawn by the end of period p
            upto = np.minimum(k, first_dead + 1)               # the bust trade is the last one
            at = np.clip(upto - 1, 0, tot - 1)
            v = np.where(upto > 0, cum[np.arange(m), at], 0.0)
            eq[a:a + m, p] = np.exp(v)
            trades[a:a + m, p] = upto
            bust[a:a + m, p] = first_dead < k
    return {"equity": eq, "trades": trades, "bust": bust}


# ---------------------------------------------------------------- 3. the checkpoint
def survival_fn(null_values: np.ndarray):
    """S(v) = share of the null at or above v (as checkpoint.luck_p counts bots >= account - 1e-9)."""
    srt = np.sort(np.asarray(null_values, float))
    N = len(srt)

    def S(v: np.ndarray) -> np.ndarray:
        return (N - np.searchsorted(srt, np.asarray(v, float) - 1e-9, side="left")) / N
    return S


def luck_p(v: np.ndarray, S, n_bots: int, rng) -> np.ndarray:
    """p = (bots >= v + 1) / (n_bots + 1), the count drawn as Binomial(n_bots, S(v))."""
    k = rng.binomial(n_bots, np.clip(S(v), 0.0, 1.0))
    return (k + 1.0) / (n_bots + 1.0)


def bh_target(p_target: np.ndarray, family: int, n_bots: int, alpha: float, rng) -> np.ndarray:
    """Benjamini-Hochberg over the target and ``family - 1`` accounts without an edge (p uniform, drawn as the
    checkpoint would: Binomial(n_bots, U)): is the target rejected? (checkpoint.bh's step-up rule, row-wise.)"""
    r = len(p_target)
    if family <= 1:
        return p_target <= alpha
    u = rng.random((r, family - 1))
    others = (rng.binomial(n_bots, u) + 1.0) / (n_bots + 1.0)
    return bh_rows(np.concatenate([p_target[:, None], others], axis=1), alpha)[:, 0]


def bh_rows(allp: np.ndarray, alpha: float) -> np.ndarray:
    """Benjamini-Hochberg step-up on every row of ``allp`` (rows x m): which p-values are rejected (the k smallest,
    k = max{i: p_(i) <= i alpha / m}), as checkpoint.bh does for one family."""
    allp = np.asarray(allp, float)
    r, m = allp.shape
    srt = np.sort(allp, axis=1)
    ok = srt <= np.arange(1, m + 1)[None, :] * alpha / m
    kmax = np.where(ok.any(axis=1), m - 1 - np.argmax(ok[:, ::-1], axis=1), -1)
    cut = np.where(kmax >= 0, srt[np.arange(r), np.maximum(kmax, 0)], -1.0)
    return allp <= cut[:, None]


def checkpoint_pass(acc: dict, nulls: dict, family: int, rng, n_bots: int, alpha: float,
                    min_trades: int) -> dict:
    """Pass probabilities of ``acc`` (simulate_accounts) at day 30 / 60 / 90, the checkpoint's schedule:
    1st verdict at the first checkpoint with >= ``min_trades`` trades (since the start), a fail stays a fail, a
    1st pass is checked on the next 30 days (2nd: >= min_trades trades in them, P&L > 0, Q1 on that window)."""
    eq, tr, bu = acc["equity"], acc["trades"], acc["bust"]
    n = len(eq)
    S = {d: survival_fn(nulls[d]) for d in nulls}
    state = np.zeros(n, dtype=np.int8)        # 0 hold, 1 pass1 (2nd pending), 2 pass2, -1 fail
    first_at = np.full(n, -1)
    pass1_by, pass2_by, judged = {}, {}, {}
    for p, day in enumerate(CHECKPOINTS):
        # 2nd check of the accounts that passed the 1st at the previous checkpoint
        sec = state == 1
        if sec.any() and p > 0:
            e0 = eq[sec, p - 1]
            value = eq[sec, p] / e0                                  # the window's P&L scaled to the start
            n2 = tr[sec, p] - tr[sec, p - 1]
            pv = luck_p(value, S[PERIOD_DAYS], n_bots, rng)
            rej = bh_target(pv, family, n_bots, alpha, rng)
            ok = (n2 >= min_trades) & (value > 1.0) & rej
            idx = np.nonzero(sec)[0]
            state[idx[ok]] = 2
            state[idx[~ok]] = -1
        # 1st verdict of the accounts still held
        hold = (state == 0) & (tr[:, p] >= min_trades)
        if hold.any():
            v = eq[hold, p]
            pv = luck_p(v, S[day], n_bots, rng)
            rej = bh_target(pv, family, n_bots, alpha, rng)
            ok = (v > 1.0) & ~bu[hold, p] & rej
            idx = np.nonzero(hold)[0]
            state[idx[ok]] = 1
            first_at[idx[ok]] = day
            state[idx[~ok]] = -1
        judged[day] = float(np.mean(state != 0))
        pass1_by[day] = float(np.mean(first_at >= 0))
        pass2_by[day] = float(np.mean(state == 2))
    return {"p_pass1_d30": float(np.mean(first_at == 30)), **{f"p_pass1_by_d{d}": pass1_by[d] for d in CHECKPOINTS},
            **{f"p_pass2_by_d{d}": pass2_by[d] for d in CHECKPOINTS[1:]},
            **{f"p_judged_by_d{d}": judged[d] for d in CHECKPOINTS}}


# ---------------------------------------------------------------- the whole grid
def power_grid(pools: dict, edges=EDGES, families=FAMILIES, reps: int = 4000, n_null: int = 20000,
               seed: int = SEED, numbers: Optional[dict] = None, schemes: Optional[dict] = None) -> dict:
    """{tf: {"pool": ..., "rows": [per edge: pass probabilities per family]}} from ``pools`` (build_pool).
    ``schemes`` ({name: {family, alpha, n_bots}}, paper v4): rows carry ``scheme_<name>`` instead of
    ``family_<n>`` (``families`` is then not used)."""
    nb = numbers or v3_numbers()
    bust_frac = nb["bust_below"] / nb["initial"]
    out = {}
    for ti, (tf, pool) in enumerate(pools.items()):
        rng = np.random.default_rng([seed, ti])
        R, mf, rate = pool["R"], pool["mf"], pool["rate_per_day"]
        if pool["trades"] < MIN_POOL:
            out[tf] = {"pool": {"trades_in_pool": int(pool["trades"]), "trades_per_30d": round(rate * PERIOD_DAYS, 2),
                                "too_few": True, "min_pool": MIN_POOL}, "rows": [],
                       "observation_only": tf in V3_OBSERVE_TFS}
            continue
        null = simulate_accounts(R, mf, rate, n_null, 0.0, rng, bust_frac)
        nulls = {d: null["equity"][:, p] for p, d in enumerate(CHECKPOINTS)}
        wins = pool.get("windows") or []
        info = {"trades_in_pool": int(pool["trades"]), "alive_days": round(pool["alive_days"], 1),
                "trades_per_30d": round(rate * PERIOD_DAYS, 1),
                "coin_flip_mean_roe": round(float(R.mean()), 5) if len(R) else None,
                "coin_flip_win_rate": round(float((R > 0).mean()), 4) if len(R) else None,
                "mean_margin_share": round(float(mf.mean()), 4) if len(mf) else None,
                "null_bust_30d": round(float(null["bust"][:, 0].mean()), 4),
                "null_median_equity_30d": round(float(np.median(nulls[30])), 4),
                "rules_bt_windows": len(wins),
                "rules_bt_bust_30d": round(sum(w["bust"] for w in wins) / len(wins), 4) if wins else None}
        rows = []
        for xi, x in enumerate(edges):
            acc = simulate_accounts(R, mf, rate, reps, float(x), rng, bust_frac)
            row = {"edge_roe": x, "mean_roe": round(float(R.mean() + x), 5) if len(R) else None,
                   "median_equity_30d": round(float(np.median(acc["equity"][:, 0])), 4)}
            if schemes:
                for si, (name, sc) in enumerate(schemes.items()):
                    res = checkpoint_pass(acc, nulls, int(sc["family"]),
                                          np.random.default_rng([seed, ti, xi, int(sc["family"]), si]),
                                          int(sc["n_bots"]), float(sc["alpha"]), nb["min_trades"])
                    row[f"scheme_{name}"] = {k: round(v, 4) for k, v in res.items()}
            else:
                for fam in families:
                    res = checkpoint_pass(acc, nulls, fam, np.random.default_rng([seed, ti, xi, fam]),
                                          nb["n_bots"], nb["alpha"], nb["min_trades"])
                    row[f"family_{fam}"] = {k: round(v, 4) for k, v in res.items()}
            rows.append(row)
        out[tf] = {"pool": info, "rows": rows, "observation_only": tf in V3_OBSERVE_TFS}
    return out


def summary_ko(results: dict, family: int = FAMILIES[0], numbers: Optional[dict] = None,
               key: Optional[str] = None) -> list[str]:
    """'진짜 엣지가 거래당 +X%라면 30일에 합격할 확률 ...' lines and what limits them (code-written). ``key``: the row
    key to read (default ``family_<family>``; paper v4: ``scheme_split``)."""
    from paperbot.checkpoint import TF_KO
    nb = numbers or v3_numbers()
    key = key or f"family_{family}"
    judged = {tf: v for tf, v in results.items() if v.get("rows") and not v.get("observation_only")
              and key in v["rows"][0]}
    lines = []
    edges = [r["edge_roe"] for r in next(iter(judged.values()))["rows"]] if judged else []
    for xi, x in enumerate(edges):
        if x <= 0:
            continue
        parts = []
        for tf, v in judged.items():
            f = v["rows"][xi][key]
            txt = f"{TF_KO.get(tf, tf)} {f['p_pass1_d30'] * 100:.0f}%"
            if f["p_judged_by_d30"] < 0.5:
                txt += f"(30일엔 대부분 거래 30건 미만, 60일까지 {f['p_pass1_by_d60'] * 100:.0f}%)"
            parts.append(txt)
        lines.append(f"진짜 엣지가 거래당 +{x * 100:g}%(증거금 대비 순 ROE)라면 30일에 1차 합격할 확률: " + ", ".join(parts))
    if judged:
        cf = ", ".join(f"{TF_KO.get(tf, tf)} {v['pool']['coin_flip_mean_roe'] * 100:+.1f}%" for tf, v in judged.items())
        lines.append(f"동전 봇의 거래당 평균 순 ROE: {cf}. 엣지가 이만큼을 넘어야 계좌가 시작 금액 위로 갈 수 있음(1차 조건)")
    thr, pmin = nb["alpha"] / family, 1.0 / (nb["n_bots"] + 1)
    if pmin <= thr < 2 * pmin:
        lines.append(f"판정 계좌 {family}개에서 혼자 FDR을 통과하려면 p ≤ {thr:.5f}: 동전 봇 {nb['n_bots']:,}개를 모두 "
                     f"이겨야 함(p = 1/{nb['n_bots'] + 1:,})")
    return lines


def scheme_lines(results: dict, schemes: dict = SCHEMES, reel: Optional[dict] = None) -> list[str]:
    """The D5 comparison in one line per edge that matters (code-written): the 36's chance of a 1st pass at day 30
    under each scheme, and the reel's under its own."""
    from paperbot.checkpoint import TF_KO
    out = []
    judged = {tf: v for tf, v in results.items() if v.get("rows") and not v.get("observation_only")
              and tf != REEL_TF}
    for x in (0.05, 0.10):
        parts = []
        for name in ("split", "one"):
            vals = []
            for tf, v in judged.items():
                r = next((r for r in v["rows"] if r["edge_roe"] == x), None)
                if r and f"scheme_{name}" in r:
                    vals.append(f"{TF_KO.get(tf, tf)} {r[f'scheme_{name}']['p_pass1_d30'] * 100:.0f}%")
            if vals:
                sc = schemes[name]
                parts.append(f"{'나눔(b)' if name == 'split' else '한 묶음(a)'} {sc['family']}개·FDR {sc['alpha'] * 100:g}%: "
                             + ", ".join(vals))
        if parts:
            out.append(f"엣지 +{x * 100:g}%일 때 매매법 36의 30일 1차 합격 확률 — " + " / ".join(parts))
    rv = results.get(REEL_TF)
    if rv and rv.get("rows"):
        for x in (0.05, 0.10):
            r = next((r for r in rv["rows"] if r["edge_roe"] == x), None)
            if r and "scheme_split" in r:
                out.append(f"엣지 +{x * 100:g}%일 때 5분 단타(릴스)의 30일 1차 합격 확률: 혼자 FDR 0.5% "
                           f"{r['scheme_split']['p_pass1_d30'] * 100:.0f}%"
                           + (f", 한 묶음(a) {r['scheme_one']['p_pass1_d30'] * 100:.0f}%" if "scheme_one" in r else ""))
    for name, sc in schemes.items():
        if name == "v3":
            continue
        thr = sc["alpha"] / sc["family"]
        k = int(math.floor(thr * (sc["n_bots"] + 1) - 1 + 1e-9))
        out.append(f"{'나눔(b)' if name == 'split' else '한 묶음(a)'}: 판정 계좌 {sc['family']}개에서 혼자 FDR을 통과하려면 "
                   f"p ≤ {thr:.5f}: 동전 봇 {sc['n_bots']:,}개 중 앞선 봇이 {max(k, 0)}개 이하")
    return out


def run(out_path: str = OUT, reps: int = 4000, n_null: int = 20000, seed: int = SEED, data_dir: str = DATA,
        tfs=TFS, edges=EDGES, reel: bool = True) -> dict:
    t0 = time.time()
    L = lib()
    rates = card_rates()
    pools, pool_s = {}, {}
    for tf in tfs:
        t1 = time.time()
        bars = load_bars(tf, data_dir)
        pools[tf] = build_pool(bars, tf, rates[tf][1], L=L)
        pool_s[tf] = round(time.time() - t1, 1)
        print(f"pool {tf}: {pools[tf]['trades']} trades, {pools[tf]['rate_per_day'] * 30:.0f}/30d, {pool_s[tf]}s",
              flush=True)
    t2 = time.time()
    res = power_grid(pools, edges=edges, reps=reps, n_null=n_null, seed=seed, schemes=SCHEMES)
    mc_s = round(time.time() - t2, 1)
    for tf in res:
        res[tf]["pool"]["signals_per_day_median"] = round(rates[tf][0], 3)
        res[tf]["pool"]["rate_per_coin_bar"] = round(rates[tf][1], 6)
    if reel:
        t1 = time.time()
        rp = build_reel_pool(load_bars(REEL_TF, data_dir), float(V4_FLIP5M["rate"]))
        pool_s[REEL_TF] = round(time.time() - t1, 1)
        print(f"pool {REEL_TF} (reel exits): {rp['trades']} trades, {rp['rate_per_day'] * 30:.0f}/30d, "
              f"{pool_s[REEL_TF]}s", flush=True)
        t3 = time.time()
        rr = power_grid({REEL_TF: rp}, edges=edges, reps=reps, n_null=n_null, seed=seed + 5, schemes=REEL_SCHEMES)
        mc_s = round(mc_s + time.time() - t3, 1)
        rr[REEL_TF]["pool"]["rate_per_coin_bar"] = round(float(V4_FLIP5M["rate"]), 6)
        rr[REEL_TF]["pool"]["rate_label"] = V4_FLIP5M.get("label")
        rr[REEL_TF]["exits"] = "reel"
        res[REEL_TF] = rr[REEL_TF]
    nb = v3_numbers()
    doc = {"version": 2, "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"),
           "script": "research/power/power.py run", "seed": seed, "reps": reps, "null_accounts": n_null,
           "edges_roe": list(edges), "schemes": SCHEMES, "reel_schemes": REEL_SCHEMES, "chosen": CHOSEN,
           "checkpoints": list(CHECKPOINTS),
           "rules": nb, "leverage": leverage_doc(), "data": "data/pre2021 (Binance USD-M futures 2020-01..2021-08, 6 coins; 30m from 15m)",
           "rates_from": "research/strategy_profiles/out_binance/cards.json (median strategy signals_per_day); "
                         "5m: config.V4_FLIP5M (the reel's H1 signal rate)",
           "timeframes": list(tfs) + ([REEL_TF] if reel else []), "no_5m": NO_5M,
           "addendum_trades_30d_median": {k: v for k, v in {"5m": 144, "15m": 104, "30m": 56, "1h": 27, "4h": 1}.items()
                                          if k in tfs},
           "results": res,
           "summary_ko": summary_ko({k: v for k, v in res.items() if k != REEL_TF},
                                    numbers={**nb, "alpha": SCHEMES[CHOSEN]["alpha"],
                                             "n_bots": SCHEMES[CHOSEN]["n_bots"]},
                                    family=SCHEMES[CHOSEN]["family"], key=f"scheme_{CHOSEN}") + scheme_lines(res),
           "assumptions": ["trades drawn independently from the coin-flip pool (no streaks or regime changes)",
                           "5m: the reel's control pool (random long entries, the reel's own exits on 5m bars, "
                           "low-first inside a bar, no funding); the reel is judged alone",
                           "the same edge on every trade: net ROE + X (a liquidation still loses at most the margin)",
                           "coin-flip trade shape from 2020-01..2021-08 bars, the median strategy's signal rate",
                           "the other accounts in the FDR family have no edge (p uniform)",
                           "4h is computed but never judged (observation only, addendum Q3)"],
           "runtime_s": {"pool": pool_s, "monte_carlo": mc_s, "total": round(time.time() - t0, 1)}}
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1)
    return doc


def leverage_doc() -> dict:
    from paperbot.config import V3_BEST_FALLS_TO_NORMAL, V3_P_BEST, V3_QUALITY_TIERS
    return {"rule": LEVERAGE_RULE, "p_best": dict(V3_P_BEST), "best_falls_to_normal": V3_BEST_FALLS_TO_NORMAL,
            "tiers": [[t.name, t.margin_frac, list(t.leverages)] for t in V3_QUALITY_TIERS],
            "note": "coin flips drawn 'best' with p_best[tf] (owners 2026-10-04, docs/paper-v3-rules-change-1.md)"}


# ---------------------------------------------------------------- selftest (synthetic bars)
def synth_bars(n: int = 4000, tf: str = "1h", seed: int = 0) -> dict:
    """Six coins of random-walk bars (ns timestamps) for the tests: no repository data needed."""
    import rules_bt as RB
    rng = np.random.default_rng(seed)
    step = TF_MIN[tf] * 60 * 10 ** 9
    ts = 1_577_836_800 * 10 ** 9 + np.arange(n, dtype=np.int64) * step
    out = {}
    for ci, coin in enumerate(RB.COINS):
        r = rng.normal(0, 0.004 * math.sqrt(TF_MIN[tf] / 15), n)
        c = 100.0 * np.exp(np.cumsum(r))
        o = np.concatenate([[100.0], c[:-1]])
        wig = np.abs(rng.normal(0, 0.002, n)) * c
        h = np.maximum(o, c) + wig
        lo = np.minimum(o, c) - wig
        out[coin] = {"ts": ts, "o": o, "h": h, "l": lo, "c": c, "atr": _atr14(h, lo, c)}
    return out


def selftest() -> None:
    bars = synth_bars()
    pool = build_pool(bars, "1h", 0.013, seeds=(1,), max_windows=3)
    assert pool["trades"] > 30 and 0 < pool["mf"].max() <= 1.0 and pool["R"].min() >= -1.0 - 1e-9
    res = power_grid({"1h": pool}, edges=(0.0, 0.5), families=(10,), reps=300, n_null=2000)
    rows = res["1h"]["rows"]
    assert rows[0]["family_10"]["p_pass1_d30"] <= 0.05 and rows[1]["family_10"]["p_pass1_d30"] > 0.5, rows
    print("selftest ok")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="power.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", default=OUT)
    r.add_argument("--reps", type=int, default=4000)
    r.add_argument("--null", type=int, default=20000)
    r.add_argument("--seed", type=int, default=SEED)
    r.add_argument("--no-reel", action="store_true", help="leave out the reel's 5m pool")
    sub.add_parser("selftest")
    a = ap.parse_args(argv)
    if a.cmd == "selftest":
        selftest()
        return 0
    doc = run(a.out, a.reps, a.null, a.seed, reel=not a.no_reel)
    print(json.dumps({"summary_ko": doc["summary_ko"], "runtime_s": doc["runtime_s"]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
