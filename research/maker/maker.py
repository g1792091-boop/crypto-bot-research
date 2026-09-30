"""Limit-order (maker) entries (research/maker/PREREG_MAKER.md).

    python3 research/maker/maker.py selftest
    SWEEP_DATA=<rebuilt sweep data> python3 research/maker/maker.py run <scratch_dir>

A signal on bar i places a limit order at close_i - side * offset * ATR_i, valid for bars i+1..i+2.
It fills only if price trades THROUGH the limit (long: low < limit), at the limit price, maker fee.
Stop: stop-market (taker fee + 0.02% slippage; a bar opening beyond the stop fills at the open).
Target: limit, fills only if price trades through it, maker fee. Time exit after 48 bars at the
close, taker fee + slippage. In the fill bar only the stop is checked (worst case). Funding
0.01% per 8 hours on both sides. One position (or pending order) at a time per config and coin.
"""

from __future__ import annotations

import os
import sys
import time
import warnings

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
for sub in ("research/search", "research/orderflow"):
    sys.path.insert(0, os.path.join(ROOT, sub))
warnings.filterwarnings("ignore")

import search as SR  # noqa: E402
import orderflow as OF  # noqa: E402

TFS = ("15m", "1h")
MAKER, TAKER, SLIP, FUND_8H = 0.0002, 0.0005, 0.0002, 0.0001
VALID_BARS, MAX_HOLD = 2, 48
OFFSETS = (0.0, 0.25)
EXITS = [("X1_SL1_TP2", 1.0, 2.0), ("X2_SL15_TP3", 1.5, 3.0), ("X4_SL2_TP1", 2.0, 1.0), ("X6_SL1_TP1", 1.0, 1.0)]
SEARCH_ENTRIES = ("E1_CONNORS", "E2_MTF_PULLBACK", "E7_BB_RANGE", "E10_RSI_DIP", "E12_BIG_FADE")
FLOW_ENTRIES = ("H1_FUNDING_FADE", "H3A_RETAIL_FADE", "H5_PREMIUM_FADE")
REV_ENTRIES = ("RV1_REVERSAL_1BAR", "RV4_REVERSAL_4BAR")
ENTRIES = SEARCH_ENTRIES + FLOW_ENTRIES + REV_ENTRIES
BARS_30D = {"15m": 2880, "1h": 720}


def reversal_signals(c: np.ndarray, tf: str) -> dict[str, np.ndarray]:
    out = {}
    for name, k in (("RV1_REVERSAL_1BAR", 1), ("RV4_REVERSAL_4BAR", 4)):
        r = pd.Series(c).pct_change(k)
        z = OF.rolling_z(r, BARS_30D[tf]).to_numpy()
        out[name] = np.where(z <= -2, 1, np.where(z >= 2, -1, 0)).astype(np.int8)
    return out


def simulate(o, h, lo, c, atr, sig, bar_hours, offset, sl, tp, start, end) -> list[tuple]:
    """Returns rows (signal_idx, fill_idx, exit_idx, side, net, mae, sl_dist, reason)."""
    rows = []
    n = len(c)
    i = start
    while i < end:
        s = int(sig[i])
        if s == 0 or not np.isfinite(atr[i]) or atr[i] <= 0:
            i += 1
            continue
        a = atr[i]
        lim = c[i] - s * offset * a
        fill = None
        for j in range(i + 1, min(i + 1 + VALID_BARS, n)):
            if (s > 0 and lo[j] < lim) or (s < 0 and h[j] > lim):
                fill = j
                break
        if fill is None:
            i = min(i + VALID_BARS, n - 1) + 1  # the order expired unfilled
            continue
        stop, targ = lim - s * sl * a, lim + s * tp * a
        exit_px, cost_exit, reason, k = None, TAKER + SLIP, "TIME", fill
        worst = lim
        last = min(fill + MAX_HOLD, n - 1)
        for k in range(fill, last + 1):
            worst = min(worst, lo[k]) if s > 0 else max(worst, h[k])
            hit_sl = lo[k] <= stop if s > 0 else h[k] >= stop
            if hit_sl:
                gap = (o[k] < stop) if s > 0 else (o[k] > stop)
                exit_px = o[k] if (gap and k > fill) else stop
                exit_px *= (1 - s * SLIP)
                cost_exit, reason = TAKER, "SL"
                break
            if k > fill and ((s > 0 and h[k] > targ) or (s < 0 and lo[k] < targ)):
                exit_px, cost_exit, reason = targ, MAKER, "TP"
                break
        if exit_px is None:
            k = last
            exit_px = c[k] * (1 - s * SLIP)
            cost_exit = TAKER
        held_h = (k - fill + 1) * bar_hours
        net = s * (exit_px / lim - 1) - MAKER - cost_exit - FUND_8H * held_h / 8
        mae = (worst / lim - 1) * s
        rows.append((i, fill, k, s, net, mae, sl * a / lim, reason))
        i = k + 1
    return rows


def signals_for(L, fg, pi, df, tf, locked, feats_coin) -> dict[str, np.ndarray]:
    se = SR.entries(L, fg, pi, df, tf, locked)
    out = {k: se[k] for k in SEARCH_ENTRIES}
    if feats_coin is not None:
        d1 = L.resample_ohlcv(df, "1h")
        close_1h = pd.Series(d1["close"].to_numpy(float), index=pd.to_datetime(d1["ts"], utc=True) + pd.Timedelta("1h"))
        fl = OF.to_chart(L, df, tf, OF.hourly_conditions(feats_coin, close_1h))
        out.update({k: fl[k] for k in FLOW_ENTRIES})
    out.update(reversal_signals(df["close"].to_numpy(float), tf))
    return out


def run_split(L, fg, pi, tf, split, feats) -> pd.DataFrame:
    panel = L.load_panel(tf, split)
    for df in panel.values():
        df.attrs["tf"] = tf
    locked = L.compute_signals(panel, tf, ["V39_ALL", "V45_AMB", "DOGE_L", "DOGE_S"], strict=True)
    bar_hours = L.tf_minutes(tf) / 60
    parts = []
    for coin, df in panel.items():
        lo_, hi_ = L.signal_window(df, tf, split, MAX_HOLD + VALID_BARS)
        if hi_ <= lo_:
            continue
        lo_ = max(lo_, L.warmup_bars(tf))
        o, h, l_, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        atr = fg.atr(df, 14).to_numpy(float)
        ts = pd.to_datetime(df["ts"], utc=True).to_numpy()
        sig = signals_for(L, fg, pi, df, tf, {k: locked[k][coin] for k in locked}, feats.get(coin))
        for ename, arr in sig.items():
            for off in OFFSETS:
                for xname, sl, tp in EXITS:
                    rows = simulate(o, h, l_, c, atr, arr, bar_hours, off, sl, tp, lo_, hi_)
                    if not rows:
                        continue
                    t = pd.DataFrame(rows, columns=["signal_idx", "entry_idx", "exit_idx", "side", "net", "mae",
                                                    "sl_dist", "reason"])
                    t = t.assign(symbol=coin, entry=ename, exit=f"{xname}@{off:g}", tf=tf, split=split,
                                 entry_ts=ts[t["entry_idx"].to_numpy()], exit_ts=ts[t["exit_idx"].to_numpy()])
                    parts.append(t)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def fill_rates(L, fg, pi, feats) -> pd.DataFrame:
    """Share of signals whose limit order filled (selection window, descriptive)."""
    rows = []
    for tf in TFS:
        panel = L.load_panel(tf, "is")
        for df in panel.values():
            df.attrs["tf"] = tf
        locked = L.compute_signals(panel, tf, ["V39_ALL", "V45_AMB", "DOGE_L", "DOGE_S"], strict=True)
        for coin, df in panel.items():
            lo_, hi_ = L.signal_window(df, tf, "is", MAX_HOLD + VALID_BARS)
            lo_ = max(lo_, L.warmup_bars(tf))
            o, h, l_, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
            atr = fg.atr(df, 14).to_numpy(float)
            sig = signals_for(L, fg, pi, df, tf, {k: locked[k][coin] for k in locked}, feats.get(coin))
            for ename, arr in sig.items():
                idx = np.flatnonzero(arr[lo_:hi_]) + lo_
                for off in OFFSETS:
                    s = arr[idx].astype(float)
                    lim = c[idx] - s * off * atr[idx]
                    filled = np.zeros(len(idx), bool)
                    for d in range(1, VALID_BARS + 1):
                        j = np.minimum(idx + d, len(c) - 1)
                        filled |= np.where(s > 0, l_[j] < lim, h[j] > lim)
                    rows.append({"tf": tf, "entry": ename, "offset": off, "coin": coin, "signals": len(idx),
                                 "filled": int(filled.sum())})
    return pd.DataFrame(rows)


def run(scratch: str) -> None:
    L = SR.lib()
    import fg_indicators as fg
    import pine_indicators as pi
    os.makedirs(scratch, exist_ok=True)
    feats = {coin: OF.hourly_features(sym) for coin, sym in OF.COIN_SYM.items()}
    parts = []
    for tf in TFS:
        for split in (*SR.SPLITS_IS, *SR.SPLITS_CONF):
            t0 = time.time()
            t = run_split(L, fg, pi, tf, split, feats)
            parts.append(t)
            print(f"{tf} {split}: {len(t)} trades, {time.time() - t0:.0f}s", flush=True)
    all_t = pd.concat(parts, ignore_index=True)
    all_t.to_pickle(os.path.join(scratch, "maker_trades.pkl"))
    res = SR.evaluate(all_t)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    res.to_csv(os.path.join(out, "results.csv"), index=False)
    fr = fill_rates(L, fg, pi, feats)
    fr.to_csv(os.path.join(out, "fill_rates.csv"), index=False)
    pd.set_option("display.width", 260)
    cols = ["tf", "entry", "exit", "is_n", "is_win_pct", "is_rr", "is_pf", "is_mean_pct", "is_p", "is_coins_pos",
            "is_half1_mean_pct", "is_half2_mean_pct", "cf_n", "cf_pf", "cf_mean_pct", "cf_coins_pos", "max_lev",
            "is_own_final_x", "cf_own_final_x", "bh_pass", "candidate"]
    print(res.sort_values("is_p")[cols].head(30).round(4).to_string())
    print("configs:", len(res), "candidates:", int(res["candidate"].sum()), "bh_pass:", int(res["bh_pass"].sum()))


def selftest() -> None:
    # Long signal, price dips through the limit, then rises through the target.
    c = np.array([100.0, 100, 99.8, 100.5, 101.5, 102, 102, 102, 102, 102])
    o = np.r_[100, c[:-1]]
    h = c + 0.1
    lo = c - 0.3
    atr = np.full(len(c), 1.0)
    sig = np.zeros(len(c), np.int8)
    sig[1] = 1
    rows = simulate(o, h, lo, c, atr, sig, 1.0, 0.0, 1.0, 1.0, 1, 5)
    assert len(rows) == 1 and rows[0][7] == "TP", rows
    assert abs(rows[0][4] - (0.01 - 2 * MAKER - FUND_8H * 3 / 8)) < 1e-9, rows
    # Not filled if the low only touches the limit.
    lo2 = lo.copy()
    lo2[2:4] = 100.0
    assert simulate(o, h, lo2, c, atr, sig, 1.0, 0.0, 1.0, 1.0, 1, 5) == []
    # Stop in the fill bar is taken (worst case).
    lo3 = lo.copy()
    lo3[2] = 98.5
    r3 = simulate(o, h, lo3, c, atr, sig, 1.0, 0.0, 1.0, 1.0, 1, 5)
    assert r3[0][7] == "SL" and r3[0][2] == 2
    # Short mirror.
    sig2 = -sig
    c2 = 200 - c
    rows2 = simulate(200 - o, 200 - lo, 200 - h, c2, atr, sig2, 1.0, 0.0, 1.0, 1.0, 1, 5)
    assert rows2[0][7] == "TP" and rows2[0][3] == -1
    # No lookahead in the reversal signals.
    x = np.cumprod(1 + np.random.default_rng(0).normal(0, 0.01, 5000)) * 100
    a, b = reversal_signals(x, "1h"), reversal_signals(x[:4000], "1h")
    for k in a:
        assert np.array_equal(a[k][:4000], b[k])
    print("selftest ok")


if __name__ == "__main__":
    if sys.argv[1] == "selftest":
        selftest()
    else:
        run(sys.argv[2])
