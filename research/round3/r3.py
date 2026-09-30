"""Round 3: information not tested before, at horizons that fit 20-50x (research/round3/PREREG_ROUND3.md).

    python3 research/round3/r3.py selftest
    SWEEP_DATA=<rebuilt sweep data> python3 research/round3/r3.py run <scratch_dir>

S1  hour-of-day effect learned on the selection window, tested on the confirmation window only
S2  funding-time drift (fixed rule)
LL  BTC -> alt lead-lag and alt idiosyncratic fade on 5-minute bars (fixed rules)
OB  order-book depth imbalance on 5-minute bars (fixed rules; only if data/bookdepth exists)
All trades: market entry at the next bar's open and market exit (taker 0.05% + slippage 0.02% per
side), protective stop 1.5% (inside the 20x isolated liquidation distance), funding 0.01%/8h.
"""

from __future__ import annotations

import glob
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd
from scipy import stats

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
for sub in ("research/search", "research/orderflow"):
    sys.path.insert(0, os.path.join(ROOT, sub))
warnings.filterwarnings("ignore")

import search as SR  # noqa: E402
import orderflow as OF  # noqa: E402

SIDE = 0.0005 + 0.0002
STOP = 0.015
FUND_8H = 0.0001
IS_END = pd.Timestamp("2024-07-01", tz="UTC")
HALF = pd.Timestamp("2023-01-01", tz="UTC")
Z5 = 8640  # 30 days of 5m bars
ALTS = ["ETHUSD", "SOLUSD", "LTCUSD", "BCHUSD", "DOGEUSD", "XRPUSD"]


# ------------------------------------------------------------------ simulator
def sim_time(o, h, lo, c, sig, hold, bar_hours, start, end) -> list[tuple]:
    """Enter at the next open, exit at the close `hold` bars later, 1.5% protective stop
    (stop first; a bar opening beyond the stop fills at the open). One position at a time."""
    rows, i, n = [], start, len(c)
    while i < end:
        s = int(sig[i])
        if s == 0 or i + hold >= n:
            i += 1
            continue
        e = o[i + 1]
        stop = e * (1 - s * STOP)
        exit_px, k, reason, worst = None, i + hold, "TIME", e
        for k in range(i + 1, i + hold + 1):
            worst = min(worst, lo[k]) if s > 0 else max(worst, h[k])
            if (s > 0 and lo[k] <= stop) or (s < 0 and h[k] >= stop):
                gap = (o[k] < stop) if s > 0 else (o[k] > stop)
                exit_px, reason = (o[k] if gap and k > i + 1 else stop), "SL"
                break
        if exit_px is None:
            k = i + hold
            exit_px = c[k]
        net = s * (exit_px / e - 1) - 2 * SIDE - FUND_8H * (k - i) * bar_hours / 8
        rows.append((i, i + 1, k, s, net, s * (worst / e - 1), STOP, reason))
        i = k + 1
    return rows


def frame(rows, df, coin, entry, exit_name, tf) -> pd.DataFrame:
    t = pd.DataFrame(rows, columns=["signal_idx", "entry_idx", "exit_idx", "side", "net", "mae", "sl_dist", "reason"])
    ts = pd.to_datetime(df["ts"], utc=True).to_numpy()
    return t.assign(symbol=coin, entry=entry, exit=exit_name, tf=tf, entry_ts=ts[t["entry_idx"].to_numpy()],
                    exit_ts=ts[t["exit_idx"].to_numpy()])


def rz(x: np.ndarray, n: int) -> np.ndarray:
    return OF.rolling_z(pd.Series(x), n).to_numpy()


# ------------------------------------------------------------------ signals
def ll_signals(panel5: dict) -> dict[str, dict[str, np.ndarray]]:
    """LL1: BTC 5m return z >= 3 and the alt moved less than half of beta x BTC -> follow BTC.
    LL2: alt 5m return z >= 3 while |BTC z| < 1 -> fade the alt."""
    btc = panel5["BTCUSD"].set_index(pd.to_datetime(panel5["BTCUSD"]["ts"], utc=True))["close"].astype(float)
    out = {"LL1_FOLLOW_BTC": {}, "LL2_FADE_IDIO": {}}
    for coin in ALTS:
        df = panel5[coin]
        t = pd.to_datetime(df["ts"], utc=True)
        a = df["close"].astype(float).to_numpy()
        b = btc.reindex(t).to_numpy()
        ra, rb = np.r_[np.nan, a[1:] / a[:-1] - 1], np.r_[np.nan, b[1:] / b[:-1] - 1]
        za, zb = rz(ra, Z5), rz(rb, Z5)
        cov = pd.Series(ra).rolling(Z5, min_periods=Z5 // 2).cov(pd.Series(rb)).shift(1)
        var = pd.Series(rb).rolling(Z5, min_periods=Z5 // 2).var().shift(1)
        beta = (cov / var).to_numpy()
        lag = np.abs(ra) < 0.5 * np.abs(beta * rb)
        same = np.sign(ra) == np.sign(rb)
        f = np.where((np.abs(zb) >= 3) & (lag | ~same), np.sign(rb), 0)
        g = np.where((np.abs(za) >= 3) & (np.abs(zb) < 1), -np.sign(ra), 0)
        out["LL1_FOLLOW_BTC"][coin] = np.nan_to_num(f).astype(np.int8)
        out["LL2_FADE_IDIO"][coin] = np.nan_to_num(g).astype(np.int8)
    return out


def ob_features(coin: str) -> pd.DataFrame | None:
    sym = OF.COIN_SYM[coin]
    files = sorted(glob.glob(os.path.join(ROOT, "data", "bookdepth", f"{sym}_depth_5m*.csv.gz")))
    if not files:
        return None
    d = pd.concat([pd.read_csv(f) for f in files], ignore_index=True).drop_duplicates("ts", keep="last")
    d["t"] = pd.to_datetime(d["snap_ts"], unit="ms", utc=True)
    d = d.sort_values("t").set_index("t")
    out = pd.DataFrame(index=d.index)
    for band in (1, 5):
        b, a = d.get(f"bid_{band}"), d.get(f"ask_{band}")
        if b is None or a is None:
            continue
        imb = (b - a) / (b + a)
        out[f"z{band}"] = OF.rolling_z(imb, 2016)  # 7 days of 5m snapshots
    return out


def ob_signals(panel5: dict) -> dict[str, dict[str, np.ndarray]]:
    out = {"OB1_IMB_1PCT": {}, "OB5_IMB_5PCT": {}}
    for coin, df in panel5.items():
        f = ob_features(coin)
        if f is None:
            continue
        close_t = pd.to_datetime(df["ts"], utc=True) + pd.Timedelta("5min")
        j = np.searchsorted(f.index.values, close_t.values, side="right") - 1
        ok = (j >= 0)
        age = close_t.values - f.index.values[np.clip(j, 0, len(f) - 1)]
        ok &= age <= np.timedelta64(10, "m")
        for name, col in (("OB1_IMB_1PCT", "z1"), ("OB5_IMB_5PCT", "z5")):
            if col not in f:
                continue
            z = np.where(ok, f[col].to_numpy()[np.clip(j, 0, len(f) - 1)], np.nan)
            out[name][coin] = np.where(z >= 2, 1, np.where(z <= -2, -1, 0)).astype(np.int8)
    return out


def funding_times(coin: str) -> pd.DataFrame:
    f = pd.read_csv(os.path.join(ROOT, "data", "orderflow", f"{OF.COIN_SYM[coin]}_funding.csv.gz"))
    t = pd.to_datetime(f["calc_time"], unit="ms", utc=True).dt.floor("h")
    return pd.DataFrame({"t": t, "rate": pd.to_numeric(f["last_funding_rate"], errors="coerce")}).drop_duplicates("t")


def s2_signals(df1h: pd.DataFrame, coin: str) -> np.ndarray:
    """At the close of the bar ending one hour before a settlement: if the previous settlement
    was > +0.03% -> short over the last hour before settlement; < -0.01% -> long. At the close of
    the settlement hour's first bar... (second leg) is handled as the opposite trade one bar later."""
    ft = funding_times(coin).sort_values("t")
    open_t = pd.to_datetime(df1h["ts"], utc=True)
    sig = np.zeros(len(df1h), np.int8)
    prev_rate = ft.set_index("t")["rate"].shift(1)  # the last settlement known before this one
    pos = {t: i for i, t in enumerate(open_t)}
    for t, r in prev_rate.dropna().items():
        pre = pos.get(t - pd.Timedelta("1h"))  # bar [T-1h, T): enter at its open -> signal on bar before
        if pre is None or pre < 1:
            continue
        if r > 0.0003:
            sig[pre - 1] = -1
        elif r < -0.0001:
            sig[pre - 1] = 1
    return sig


def s2_after(sig: np.ndarray) -> np.ndarray:
    """Second leg: the opposite trade over the hour after settlement."""
    out = np.zeros_like(sig)
    idx = np.flatnonzero(sig)
    ok = idx + 1 < len(sig)
    out[idx[ok] + 1] = -sig[idx[ok]]
    return out


# ------------------------------------------------------------------ run
def run(scratch: str) -> None:
    L = SR.lib()
    os.makedirs(scratch, exist_ok=True)
    parts = []
    s1_rows = []
    for split in ("is", "oos", "final"):
        p5 = L.load_panel("5m", split)
        p1 = L.load_panel("1h", split)
        sigs = {**ll_signals(p5), **ob_signals(p5)}
        for fam, per in sigs.items():
            for coin, arr in per.items():
                df = p5[coin]
                lo_, hi_ = L.signal_window(df, "5m", split, 12)
                o, h, l_, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
                for hold in (3, 6):
                    rows = sim_time(o, h, l_, c, arr, hold, 5 / 60, max(lo_, Z5), hi_)
                    if rows:
                        parts.append(frame(rows, df, coin, fam, f"TIME{hold}x5m", "5m").assign(split=split))
        for coin, df in p1.items():
            lo_, hi_ = L.signal_window(df, "1h", split, 2)
            o, h, l_, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
            pre = s2_signals(df, coin)
            for name, arr in (("S2_FUNDING_PRE", pre), ("S2_FUNDING_POST", s2_after(pre))):
                rows = sim_time(o, h, l_, c, arr, 1, 1.0, lo_, hi_)
                if rows:
                    parts.append(frame(rows, df, coin, name, "TIME1x1h", "1h").assign(split=split))
            t = pd.to_datetime(df["ts"], utc=True)
            r = c / o - 1  # the hour's own open-to-close return
            s1_rows.append(pd.DataFrame({"coin": coin, "split": split, "ts": t, "hour": t.dt.hour, "ret": r,
                                         "idx": np.arange(len(df))}).iloc[lo_:hi_])
    all_t = pd.concat(parts, ignore_index=True)
    all_t.to_pickle(os.path.join(scratch, "r3_trades.pkl"))
    res = SR.evaluate(all_t)
    # Order-book data starts later than 2021, so its halves split the available selection window
    # at its own midpoint (PREREG_ROUND3.md).
    for i, row in res[res["entry"].str.startswith("OB")].iterrows():
        g = all_t[(all_t["entry"] == row["entry"]) & (all_t["exit"] == row["exit"]) & (all_t["split"] == "is")]
        if len(g) < 2:
            continue
        ts = pd.to_datetime(g["entry_ts"], utc=True)
        mid = ts.min() + (ts.max() - ts.min()) / 2
        h1, h2 = g.loc[(ts < mid).to_numpy(), "net"].mean(), g.loc[(ts >= mid).to_numpy(), "net"].mean()
        res.loc[i, ["is_half1_mean_pct", "is_half2_mean_pct"]] = [100 * h1, 100 * h2]
        ok = bool(row["bh_pass"] and row["is_n"] >= 100 and row["is_coins_pos"] >= 4
                  and row["is_coins_pos"] > row["is_coins_n"] / 2 and h1 > 0 and h2 > 0)
        res.loc[i, "is_ok"] = ok
        res.loc[i, "candidate"] = ok and bool(row["cf_ok"])
    # 20x viability on top of the usual candidate rule
    res["x20_ok"] = (res["is_own_final_x"] > 1) & (res["cf_own_final_x"] > 1)
    res["candidate_20x"] = res["candidate"] & res["x20_ok"]
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    res.to_csv(os.path.join(out, "results.csv"), index=False)
    # S1: learn hour cells on the selection window, trade them on the confirmation window
    s1 = pd.concat(s1_rows, ignore_index=True).dropna(subset=["ret"])
    learn = s1[s1["split"] == "is"].groupby(["coin", "hour"])["ret"].agg(["mean", "std", "size"])
    learn["t"] = learn["mean"] / (learn["std"] / np.sqrt(learn["size"]))
    cells = learn[learn["t"].abs() >= 2.5]
    test = s1[s1["split"] != "is"].merge(cells[["mean"]].reset_index(), on=["coin", "hour"])
    test["side"] = np.sign(test["mean"])
    test["net"] = test["side"] * test["ret"] - 2 * SIDE
    s1_out = {"cells_selected": int(len(cells)), "cells": cells.round(6).reset_index().to_dict("records"),
              "cf_trades": int(len(test))}
    if len(test):
        day = pd.to_datetime(test["ts"], utc=True).dt.floor("D").to_numpy()
        m, p = SR.mean_test(test["net"].to_numpy(), day)
        s1_out.update({"cf_mean_pct": 100 * m, "cf_p": p, "cf_win_pct": 100 * float((test["net"] > 0).mean()),
                       "cf_coins_pos": int((test.groupby("coin")["net"].mean() > 0).sum()),
                       "cf_coins": int(test["coin"].nunique()),
                       "cf_gross_pct": 100 * float((test["side"] * test["ret"]).mean())})
        tt = test.assign(entry_ts=pd.to_datetime(test["ts"], utc=True),
                         exit_ts=pd.to_datetime(test["ts"], utc=True) + pd.Timedelta("1h"),
                         mae=np.where(test["side"] * test["ret"] < -STOP, -STOP, np.minimum(0, test["side"] * test["ret"])),
                         symbol=test["coin"])
        s1_out.update({f"cf_{k}": v for k, v in SR.owners_book(tt).items()})
    s1_out["candidate_20x"] = bool(s1_out.get("cf_p", 1) < 0.05 and s1_out.get("cf_mean_pct", -1) > 0
                                   and s1_out.get("cf_coins_pos", 0) >= 4 and s1_out.get("cf_own_final_x", 0) > 1)
    with open(os.path.join(out, "s1_hour_of_day.json"), "w") as fh:
        json.dump(s1_out, fh, indent=1, default=str)
    pd.set_option("display.width", 260)
    cols = ["tf", "entry", "exit", "is_n", "is_win_pct", "is_mean_pct", "is_p", "is_coins_pos", "is_half1_mean_pct",
            "is_half2_mean_pct", "cf_n", "cf_pf", "cf_mean_pct", "cf_coins_pos", "is_own_final_x", "cf_own_final_x",
            "bh_pass", "candidate", "candidate_20x"]
    print(res.sort_values("is_p")[cols].round(4).to_string())
    print(json.dumps({k: v for k, v in s1_out.items() if k != "cells"}, indent=1, default=str))


def selftest() -> None:
    # long entry; the price falls through the 1.5% stop on the second bar
    o = np.array([100, 100, 99.9, 98.0, 99.0, 99.0])
    c = np.array([100, 99.9, 98.2, 98.5, 99.0, 99.0])
    h = np.maximum(o, c) + 0.1
    lo = np.minimum(o, c) - 0.1
    sig = np.zeros(6, np.int8)
    sig[0] = 1
    r = sim_time(o, h, lo, c, sig, 3, 1 / 12, 0, 3)
    assert r[0][7] == "SL" and r[0][2] == 2, r
    assert abs(r[0][4] - (-0.015 - 2 * SIDE - FUND_8H * 2 / 12 / 8)) < 1e-9, r
    # time exit
    sig2 = np.zeros(6, np.int8)
    sig2[3] = -1
    r2 = sim_time(o, h, lo, c, sig2, 2, 1 / 12, 3, 4)
    assert r2[0][7] == "TIME" and r2[0][2] == 5
    # second funding leg is the opposite trade one bar later
    s = np.zeros(10, np.int8)
    s[4] = -1
    assert s2_after(s)[5] == 1 and s2_after(s).sum() == 1
    print("selftest ok")


if __name__ == "__main__":
    selftest() if sys.argv[1] == "selftest" else run(sys.argv[2])
