"""Stop-loss choice for the paper run under the owners' final rules (PREREG_RULES.md).

    SWEEP_DATA=<sweep data> python3 research/paper_rules/rules_bt.py selftest
    SWEEP_DATA=<sweep data> python3 research/paper_rules/rules_bt.py signals <scratch_dir>
    SWEEP_DATA=<sweep data> python3 research/paper_rules/rules_bt.py run <scratch_dir>

One account = one strategy on one timeframe, $1,000, six coins, one position at a time.
Signals come from the locked backtest code (paperbot.sweepsig). Sizing is the paper engine's
``size_position`` (owners' tiers 40%x50/40, 30%x30, 20%x20; loss at stop <= 15% of equity).
Exits: initial stop k x ATR14 of the signal bar, then the stepped profit lock of
``paperbot.ladder``. No take-profit, no time exit, no drawdown halt, opposite signals ignored.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
import warnings
from multiprocessing import Pool

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
warnings.filterwarnings("ignore")

from paperbot import sweepsig  # noqa: E402
from paperbot.config import Settings  # noqa: E402
from paperbot.ladder import LadderSpec, roe_price  # noqa: E402
from paperbot.margin import Brackets  # noqa: E402
from paperbot.sizing import size_position  # noqa: E402
from paperbot.sigservice import doge_join  # noqa: E402

COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")  # entry priority order
TFS = ("5m", "15m", "30m", "1h", "4h", "1d")
SL_KS = (1.0, 1.5, 2.0)
WINDOWS = {"is": ("2021-08-01", "2024-07-01"), "cf": ("2024-07-01", "2026-09-30")}
RANDOM_SEEDS = (1, 2, 3)
INITIAL = 1000.0
BUST_BELOW = 10.0          # account stops when equity falls under this
MIN_NOTIONAL = 5.0
FUNDING_8H = 0.0001        # both sides pay, as in the backtest
SETTINGS = Settings(liq_buffer_atr_mult=1.0)  # stop must sit >= max(1 ATR, 0.2%) inside liquidation
LADDER = LadderSpec()
BRACKETS = Brackets.example()


def strategy_names(L) -> list[str]:
    names = [n for n in L.NAMES if n not in ("DOGE_L", "DOGE_S")]
    return names + ["DOGE"]


def _ns(ts) -> np.ndarray:
    return pd.to_datetime(ts, utc=True).dt.tz_localize(None).to_numpy().astype("datetime64[ns]").astype(np.int64)


def load_full(L, tf: str, coin: str) -> pd.DataFrame:
    df = L.read_ohlcv(L._resolve_path(tf, coin, "full", None))
    df = df[df["ts"] < pd.Timestamp(WINDOWS["cf"][1], tz="UTC")].reset_index(drop=True)
    df.attrs["tf"] = tf
    return df


# ---------------------------------------------------------------------------------------------
# signals (computed once per timeframe and coin on the whole series; the code is causal)
# ---------------------------------------------------------------------------------------------
def _signals_job(args):
    tf, coin, out_dir = args
    L = sweepsig.lib()
    import fg_indicators as fg
    df = load_full(L, tf, coin)
    t0 = time.time()
    raw = L.compute_signals({coin: df}, tf, list(L.NAMES), strict=True)
    sig = {n: raw[n][coin] for n in L.NAMES if n not in ("DOGE_L", "DOGE_S")}
    sig["DOGE"] = doge_join(raw["DOGE_L"][coin], raw["DOGE_S"][coin])  # DOGE_S is already -1 on shorts
    atr = fg.atr(df, 14).to_numpy(float)
    np.savez_compressed(os.path.join(out_dir, f"sig_{tf}_{coin}.npz"), ts=_ns(df["ts"]),
                        o=df["open"].to_numpy(float), h=df["high"].to_numpy(float), l=df["low"].to_numpy(float),
                        c=df["close"].to_numpy(float), atr=atr, **{f"s__{k}": v for k, v in sig.items()})
    return tf, coin, len(df), time.time() - t0


def build_signals(out_dir: str, procs: int = 4) -> None:
    os.makedirs(out_dir, exist_ok=True)
    jobs = [(tf, c, out_dir) for tf in TFS for c in COINS
            if not os.path.exists(os.path.join(out_dir, f"sig_{tf}_{c}.npz"))]
    with Pool(procs) as p:
        for tf, coin, n, sec in p.imap_unordered(_signals_job, jobs):
            print(f"signals {tf} {coin}: {n} bars, {sec:.0f}s", flush=True)


def load_tf(out_dir: str, tf: str) -> dict:
    out = {}
    for c in COINS:
        z = np.load(os.path.join(out_dir, f"sig_{tf}_{c}.npz"))
        out[c] = {k: z[k] for k in z.files}
    return out


# ---------------------------------------------------------------------------------------------
# one account
# ---------------------------------------------------------------------------------------------
def window_bounds(L, bars: dict, tf: str, window: str) -> tuple[int, int]:
    """Signal bars [lo, hi): time in the window, past the warm-up, and the entry bar (i+1) inside it.
    Returns (lo, n_end) where n_end = bars with time < window end; signals need i + 1 < n_end."""
    ts = bars["ts"]
    start = pd.Timestamp(WINDOWS[window][0]).value
    end = pd.Timestamp(WINDOWS[window][1]).value
    lo = max(int(np.searchsorted(ts, start, side="left")), L.warmup_bars(tf))
    n_end = int(np.searchsorted(ts, end, side="left"))
    return lo, n_end


def simulate(bars: dict, sigs: dict, bounds: dict, k: float, tf: str, L, keep_trades: bool = False) -> dict:
    """bars[coin]: dict ts,o,h,l,c,atr arrays; sigs[coin]: int8 array (+1/-1/0);
    bounds[coin]: (lo, n_end). Returns account statistics (and trades if asked)."""
    ts_l, pr_l, idx_l, side_l = [], [], [], []
    for p, c in enumerate(COINS):
        if c not in sigs:
            continue
        lo, n_end = bounds[c]
        hi = n_end - 1
        if hi <= lo:
            continue
        w = np.nonzero(sigs[c][lo:hi])[0] + lo
        ts_l.append(bars[c]["ts"][w]); pr_l.append(np.full(len(w), p)); idx_l.append(w)
        side_l.append(sigs[c][w].astype(int))
    if ts_l:
        ts_a, pr_a, idx_a, side_a = (np.concatenate(x) for x in (ts_l, pr_l, idx_l, side_l))
        order = np.lexsort((pr_a, ts_a))
        ts_a, pr_a, idx_a, side_a = ts_a[order], pr_a[order], idx_a[order], side_a[order]
    else:
        ts_a = pr_a = idx_a = side_a = np.zeros(0, int)

    rt = SETTINGS.round_trip_cost
    fee, slip = SETTINGS.taker_fee, SETTINGS.slippage_frac
    f_bar = FUNDING_8H * L.tf_minutes(tf) / 480.0
    equity, peak, max_dd = INITIAL, INITIAL, 0.0
    free_from = np.iinfo(np.int64).min
    n_signals, busy, rejected = len(ts_a), 0, 0
    bust_ts = None
    trades = []
    for s_ts, p, i, side in zip(ts_a, pr_a, idx_a, side_a):
        if bust_ts is not None:
            break
        if s_ts < free_from:
            busy += 1
            continue
        coin = COINS[p]
        b = bars[coin]
        n_end = bounds[coin][1]
        a = b["atr"][i]
        raw = b["o"][i + 1]
        if not (np.isfinite(a) and a > 0 and np.isfinite(raw)):
            rejected += 1
            continue
        fill = raw * (1 + side * slip)
        stop0 = raw - side * k * a
        dec = size_position(SETTINGS, equity, side, fill, stop0, "best", BRACKETS, atr=a,
                            min_notional=MIN_NOTIONAL)
        if not dec.ok:
            rejected += 1
            continue
        lev, qty, margin, liq = dec.leverage, dec.qty, dec.margin, dec.liq_price
        # forward scan in chunks
        j0 = i + 1
        best_carry = fill
        lock_carry = -np.inf if side == 1 else np.inf
        exit_j, exit_px, reason = None, None, None
        chunk = 256
        while j0 < n_end:
            j1 = min(n_end, j0 + chunk)
            o, h, lo_, cl = b["o"][j0:j1], b["h"][j0:j1], b["l"][j0:j1], b["c"][j0:j1]
            held = np.arange(j0, j1) - i            # bars held after bar j
            fund = f_bar * held
            if side == 1:
                best = np.maximum.accumulate(np.concatenate(([best_carry], h)))[1:]
                roe_best = lev * (best / fill - 1 - rt - fund)
            else:
                best = np.minimum.accumulate(np.concatenate(([best_carry], lo_)))[1:]
                roe_best = lev * (1 - best / fill - rt - fund)
            first = LADDER.first_lock + LADDER.trigger_gap
            nstep = np.floor((roe_best - first) / LADDER.step + 1e-9)
            lock_roe = np.where(roe_best >= first - 1e-12, LADDER.first_lock + LADDER.step * nstep, np.nan)
            lock_px = fill * (1 + side * (lock_roe / lev + rt + fund))
            if side == 1:
                lp = np.where(np.isnan(lock_px), -np.inf, lock_px)
                lock_cum = np.maximum.accumulate(np.concatenate(([lock_carry], lp)))
                stop_eff = np.maximum(stop0, lock_cum[:-1])       # lock from previous bars only
                hit = lo_ <= stop_eff
            else:
                lp = np.where(np.isnan(lock_px), np.inf, lock_px)
                lock_cum = np.minimum.accumulate(np.concatenate(([lock_carry], lp)))
                stop_eff = np.minimum(stop0, lock_cum[:-1])
                hit = h >= stop_eff
            if hit.any():
                q = int(np.argmax(hit))
                j = j0 + q
                st = stop_eff[q]
                gap = (o[q] <= st) if side == 1 else (o[q] >= st)
                if gap and ((o[q] <= liq) if side == 1 else (o[q] >= liq)):
                    exit_j, exit_px, reason = j, liq, "liquidation"
                else:
                    px = o[q] if gap else st
                    exit_j, exit_px = j, px * (1 - side * slip)
                    reason = "stop" if st == stop0 else "lock"
                break
            best_carry, lock_carry = best[-1], lock_cum[-1]
            j0 = j1
            chunk *= 2
        if exit_j is None:
            exit_j = n_end - 1
            exit_px = b["c"][exit_j] * (1 - side * slip)
            reason = "window_end"
        held_bars = exit_j - i
        if reason == "liquidation":
            pnl = -margin
        else:
            pnl = (qty * side * (exit_px - fill) - fee * qty * (fill + exit_px)
                   - qty * fill * f_bar * held_bars)
            pnl = max(pnl, -margin)
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, 1 - equity / peak)
        free_from = b["ts"][exit_j]
        trades.append((int(p), int(side), int(i), int(exit_j), int(lev), margin / (equity - pnl),
                       pnl / margin, reason, int(s_ts)))
        if equity < BUST_BELOW:
            bust_ts = int(b["ts"][exit_j])
    tr = pd.DataFrame(trades, columns=["coin", "side", "i", "exit_j", "lev", "margin_frac", "R", "reason",
                                       "signal_ts"])
    n = len(tr)
    out = dict(final=equity, multiple=equity / INITIAL, max_dd=max_dd, bust=bust_ts is not None,
               bust_ts=bust_ts, trades=n, signals=n_signals, busy=busy, rejected=rejected,
               win=float((tr["R"] > 0).mean()) if n else np.nan,
               mean_R=float(tr["R"].mean()) if n else np.nan,
               lock_exits=int((tr["reason"] == "lock").sum()) if n else 0,
               liquidations=int((tr["reason"] == "liquidation").sum()) if n else 0,
               **{f"lev{x}": int((tr["lev"] == x).sum()) if n else 0 for x in (50, 40, 30, 20)})
    if keep_trades:
        out["trade_table"] = tr
    return out


def random_signals(bars: dict, bounds: dict, p: float, seed: int, tf: str, L) -> dict:
    out = {}
    for ci, c in enumerate(COINS):
        n = len(bars[c]["ts"])
        rng = np.random.default_rng([seed, L.tf_minutes(tf), ci])
        fire = rng.random(n) < p
        side = np.where(rng.random(n) < 0.5, 1, -1)
        out[c] = (fire * side).astype(np.int8)
    return out


# ---------------------------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------------------------
def _tf_job(args):
    tf, sig_dir = args
    L = sweepsig.lib()
    data = load_tf(sig_dir, tf)
    names = [k[3:] for k in data[COINS[0]] if k.startswith("s__")]
    bars = {c: {k: data[c][k] for k in ("ts", "o", "h", "l", "c", "atr")} for c in COINS}
    rows = []
    bounds = {w: {c: window_bounds(L, bars[c], tf, w) for c in COINS} for w in WINDOWS}
    # random-bot firing rate: median over strategies of signals per coin-bar in the IS window
    rates = []
    for nm in names:
        tot = sum(int(np.count_nonzero(data[c]["s__" + nm][bounds["is"][c][0]:bounds["is"][c][1] - 1])) for c in COINS)
        bars_n = sum(max(0, bounds["is"][c][1] - 1 - bounds["is"][c][0]) for c in COINS)
        rates.append(tot / max(bars_n, 1))
    p_rand = float(np.median(rates))
    accounts = [(nm, {c: data[c]["s__" + nm] for c in COINS}) for nm in names]
    accounts += [(f"RANDOM_{s}", random_signals(bars, bounds["is"], p_rand, s, tf, L)) for s in RANDOM_SEEDS]
    for nm, sg in accounts:
        for w in WINDOWS:
            for k in SL_KS:
                r = simulate(bars, sg, bounds[w], k, tf, L)
                rows.append(dict(tf=tf, strategy=nm, window=w, k=k, **r))
    return tf, p_rand, rows


def run(scratch: str, procs: int = 4) -> None:
    sig_dir = os.path.join(scratch, "signals")
    build_signals(sig_dir, procs)
    rows, rates = [], {}
    with Pool(procs) as p:
        for tf, p_rand, r in p.imap_unordered(_tf_job, [(tf, sig_dir) for tf in TFS]):
            rows += r
            rates[tf] = p_rand
            print(f"accounts {tf}: {len(r)} rows, random rate {p_rand:.5f}", flush=True)
    res = pd.DataFrame(rows)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    res.to_csv(os.path.join(out, "accounts.csv"), index=False)
    summary = choose(res)
    summary["random_rate"] = rates
    with open(os.path.join(out, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=1, default=float)
    print(json.dumps(summary, indent=1, default=float))


def choose(res: pd.DataFrame) -> dict:
    """PREREG rule: median IS final equity over the 216 strategy accounts; if the best two are
    within $50, the pooled mean net return on margin per trade decides."""
    strat = res[~res["strategy"].str.startswith("RANDOM_")]
    out = {"by_k": {}}
    for k in SL_KS:
        d = {}
        for w in WINDOWS:
            g = strat[(strat["k"] == k) & (strat["window"] == w)]
            d[w] = dict(accounts=len(g), median_final=float(g["final"].median()),
                        mean_final=float(g["final"].mean()),
                        above_start=int((g["final"] > INITIAL).sum()), bust=int(g["bust"].sum()),
                        trades=int(g["trades"].sum()),
                        pooled_mean_R=float((g["mean_R"] * g["trades"]).sum() / max(g["trades"].sum(), 1)))
        out["by_k"][str(k)] = d
    med = sorted(((out["by_k"][str(k)]["is"]["median_final"], k) for k in SL_KS), reverse=True)
    if med[0][0] - med[1][0] < 50.0:
        cand = [k for m, k in med if med[0][0] - m < 50.0]
        chosen = max(cand, key=lambda k: out["by_k"][str(k)]["is"]["pooled_mean_R"])
        out["rule_used"] = "tie within $50 -> pooled mean R"
    else:
        chosen = med[0][1]
        out["rule_used"] = "median IS final equity"
    out["chosen_k"] = chosen
    return out


# ---------------------------------------------------------------------------------------------
# selftest (synthetic data only)
# ---------------------------------------------------------------------------------------------
def _flat_bars(n, px=100.0, atr=0.5):
    ts = (np.arange(n, dtype=np.int64) * 900 + 1_630_000_000) * 1_000_000_000
    o = np.full(n, px); h = o + 0.1; lo = o - 0.1; c = o.copy()
    return dict(ts=ts, o=o, h=h, l=lo, c=c, atr=np.full(n, atr))


def selftest() -> None:
    L = sweepsig.lib()
    tf = "15m"
    # 1. ladder: long at 100, price walks up to arm the 15% lock, then falls through it
    n = 400
    bars = {c: _flat_bars(n) for c in COINS}
    b = bars["BTCUSD"]
    sig = {c: np.zeros(n, np.int8) for c in COINS}
    sig["BTCUSD"][310] = 1
    for j in range(312, 320):
        b["h"][j] = 100.0 + 0.2 * (j - 311); b["o"][j] = b["c"][j] = b["h"][j] - 0.05; b["l"][j] = b["o"][j] - 0.1
    b["o"][320] = 101.6; b["h"][320] = 101.62; b["l"][320] = 99.0; b["c"][320] = 99.2
    bounds = {c: (300, n) for c in COINS}
    r = simulate(bars, sig, bounds, 1.0, tf, L, keep_trades=True)
    t = r["trade_table"].iloc[0]
    lev = int(t["lev"])
    fill = 100.0 * (1 + SETTINGS.slippage_frac)
    best = 100.0 + 0.2 * 8
    roe_best = lev * (best / fill - 1 - SETTINGS.round_trip_cost - FUNDING_8H * 15 / 480 * (319 - 310))
    want_lock = LADDER.lock_for(roe_best)
    assert t["reason"] == "lock" and t["exit_j"] == 320, t
    assert abs(t["R"] - want_lock) < 0.02, (t["R"], want_lock)
    # 2. stop: short signal, price rises through the 1 ATR stop
    sig = {c: np.zeros(n, np.int8) for c in COINS}
    bars = {c: _flat_bars(n) for c in COINS}
    sig["ETHUSD"][305] = -1
    bars["ETHUSD"]["h"][308] = 100.9
    r = simulate(bars, sig, bounds, 1.0, tf, L, keep_trades=True)
    t = r["trade_table"].iloc[0]
    assert t["reason"] == "stop" and t["exit_j"] == 308 and t["R"] < 0, t
    assert r["final"] >= INITIAL * (1 - SETTINGS.max_loss_frac) - 1e-6, r["final"]
    # 3. one position at a time, priority on ties, busy count
    sig = {c: np.zeros(n, np.int8) for c in COINS}
    bars = {c: _flat_bars(n) for c in COINS}
    for c in COINS:
        sig[c][305] = 1
    sig["SOLUSD"][306] = -1
    r = simulate(bars, sig, bounds, 1.0, tf, L, keep_trades=True)
    tt = r["trade_table"]
    assert len(tt) == 1 and COINS[tt.iloc[0]["coin"]] == "BTCUSD" and r["busy"] == 6, (tt, r)
    assert tt.iloc[0]["reason"] == "window_end"
    # 4. gap through liquidation loses the whole margin
    sig = {c: np.zeros(n, np.int8) for c in COINS}
    bars = {c: _flat_bars(n) for c in COINS}
    sig["BTCUSD"][305] = 1
    bars["BTCUSD"]["o"][310] = 90.0; bars["BTCUSD"]["l"][310] = 89.0
    r = simulate(bars, sig, bounds, 1.0, tf, L, keep_trades=True)
    t = r["trade_table"].iloc[0]
    assert t["reason"] == "liquidation" and abs(t["R"] + 1) < 1e-9, t
    # 5. no look-ahead: cutting the data after an exit does not change the trade
    rng = np.random.default_rng(0)
    bars = {}
    for c in COINS:
        d = L.synth_ohlcv(3000, tf, seed=int(rng.integers(1e6)))
        import fg_indicators as fg
        bars[c] = dict(ts=_ns(d["ts"]), o=d["open"].to_numpy(float), h=d["high"].to_numpy(float),
                       l=d["low"].to_numpy(float), c=d["close"].to_numpy(float), atr=fg.atr(d, 14).to_numpy(float))
    sig = random_signals(bars, None, 0.01, 7, tf, L)
    full_b = {c: (400, len(bars[c]["ts"])) for c in COINS}
    r1 = simulate(bars, sig, full_b, 1.5, tf, L, keep_trades=True)["trade_table"]
    assert len(r1) > 5
    cut_t = r1.iloc[len(r1) // 2]
    cut = {c: (400, int(np.searchsorted(bars[c]["ts"], bars[COINS[cut_t["coin"]]]["ts"][cut_t["exit_j"]], "right")) + 1)
           for c in COINS}
    r2 = simulate(bars, sig, cut, 1.5, tf, L, keep_trades=True)["trade_table"]
    a = r1.iloc[: len(r1) // 2 + 1].reset_index(drop=True)
    b2 = r2.iloc[: len(a)].reset_index(drop=True)
    assert np.allclose(a["R"], b2["R"]) and (a["exit_j"] == b2["exit_j"]).all()
    # 6. no overlapping positions on real-looking data
    starts = np.array([bars[COINS[c]]["ts"][i + 1] for c, i in zip(r1["coin"], r1["i"])])
    ends = np.array([bars[COINS[c]]["ts"][j] for c, j in zip(r1["coin"], r1["exit_j"])])
    assert (starts[1:] > ends[:-1]).all()
    print("selftest ok")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "selftest":
        selftest()
    elif cmd == "signals":
        build_signals(os.path.join(sys.argv[2], "signals"))
    elif cmd == "run":
        run(sys.argv[2])
