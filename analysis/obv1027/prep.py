#!/usr/bin/env python3
"""OBV 추세형 study (PLAN.md): bars, the six signal sets and the filter columns, into one work folder.

    python3 -E -P prep.py --five FIVE5M/5m --new NEWV/5m --work WORK

FIVE5M: 5m klines with volume 2020-01 .. 2026-10-24 (fetch_bars five with volume); NEWV: the same for 2026-09 ..
2026-10-26 (the days after are appended, the overlap must agree). Writes WORK/a5_<SYM>.npz (ts, o, h, l, c, fund: the
arrays the trades walk on) and WORK/signals.pkl (one frame per cell: symbol, close_ms, side, atr, atrp, best, the
filter columns F1..F11 and the judges they read). Nothing private is read; research code, it trades nothing.
"""
from __future__ import annotations

import argparse
import os
import pickle
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "analysis", "v39_1h"))
import v39lib as L  # noqa: E402,F401  (puts the user site and the repository on sys.path)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import features as F  # noqa: E402
sys.path.insert(0, os.path.join(REPO, "research", "entry_study", "param_defs"))
sys.path.insert(0, os.path.join(REPO, "tradingview"))
import OBV_S as P  # noqa: E402
import pine_mirror as PM  # noqa: E402

SYMBOLS = L.SYMBOLS
M5, H1 = 300_000, 3_600_000
TF_MS = {"30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
HTF = {"30m": "1h", "1h": "4h", "4h": "1d"}
CELLS = {  # name: (tf, overrides)
    "RB30": ("30m", {}), "RB1h": ("1h", {}), "CV30": ("30m", dict(obv_ma_len=15, stc_level=55.0, stoch_k_smooth=2,
                                                                     ao_slow_len=102)),
    "CV1h": ("1h", dict(obv_ma_len=38, stc_level=72.0, stoch_k_smooth=6, ao_slow_len=51)),
    "RB4h": ("4h", {}), "CV4h": ("4h", dict(obv_ma_len=38, stc_level=60.0, stoch_k_smooth=2, ao_slow_len=43))}
PICK = (pd.Timestamp("2021-01-01", tz="UTC").value // 10**6, pd.Timestamp("2024-01-01", tz="UTC").value // 10**6)


def load(five: str, new: str, sym: str) -> dict:
    a, b = F.load5(five, sym), F.load5(new, sym)
    keys = ("ts", "o", "h", "l", "c", "v", "fund")
    # the overlap must agree (prices, volume); funding is checked as a sum over the overlap
    ov_a = (a["ts"] >= b["ts"][0]) & (a["ts"] <= a["ts"][-1])
    ov_b = b["ts"] <= a["ts"][-1]
    assert np.array_equal(a["ts"][ov_a], b["ts"][ov_b]), sym
    for k in ("o", "h", "l", "c", "v"):
        assert np.allclose(a[k][ov_a], b[k][ov_b], rtol=0, atol=1e-9), (sym, k)
    tail = b["ts"] > a["ts"][-1]
    return {k: np.r_[a[k], b[k][tail]] for k in keys}


def bars(z: dict, step: int) -> pd.DataFrame:
    df = F.agg(z["ts"], z["o"], z["h"], z["l"], z["c"], step, M5)
    b = z["ts"] // step
    vol = pd.Series(z["v"]).groupby(b).sum()
    df["volume"] = vol.reindex(df["open_ms"].to_numpy() // step).to_numpy(float)
    return df


def judges_of(df: pd.DataFrame) -> dict:
    m = np.c_[df["open_ms"].to_numpy(float), df[["open", "high", "low", "close", "volume"]].to_numpy(float)]
    return PM.judges(m)


def at_closed(close_ms: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Index of the last bar closed at or before each t (-1: none)."""
    return np.searchsorted(close_ms, t, side="right") - 1


def take(x: np.ndarray, k: np.ndarray, warm: int = 120) -> np.ndarray:
    out = np.zeros(len(k))
    ok = k >= warm
    out[ok] = x[k[ok]]
    return out


def best_flags(df: pd.DataFrame, tf: str):
    """levrule's best group for OBV_S at this timeframe (research/fullgrid/run.py best_flags, as the rule bot)."""
    from paperbot import levrule
    from paperbot.entry_marks import strength_module
    n = len(df)
    smod = strength_module("OBV_S")
    cell = levrule.edges().get(f"OBV_S|{tf}")
    arrays = smod.strength(df.copy(), tf)
    out = []
    for k in (0, 1):
        tot, cnt = np.zeros(n), np.zeros(n)
        for f in smod.FEATURES:
            e = cell.get(f["name"])
            if e is None:
                continue
            v = np.asarray(arrays[f["name"]][k], float)
            ok = np.isfinite(v)
            sv = np.where(ok, v if e["higher_is_stronger"] else -v, 0.0)
            q = 1 + np.searchsorted(np.asarray(e["edges"], float), sv, side="right")
            tot += np.where(ok, q, 0)
            cnt += ok
        with np.errstate(invalid="ignore", divide="ignore"):
            out.append((cnt > 0) & (tot / np.maximum(cnt, 1) >= 4))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--five", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--work", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.work, exist_ok=True)
    fg, pi = F.indicators()
    Z, B = {}, {}
    for s in SYMBOLS:
        Z[s] = load(a.five, a.new, s)
        np.savez(os.path.join(a.work, f"a5_{s}.npz"), ts=Z[s]["ts"], o=Z[s]["o"], h=Z[s]["h"], l=Z[s]["l"],
                 c=Z[s]["c"], fund=Z[s]["fund"])
        B[s] = {tf: bars(Z[s], ms) for tf, ms in TF_MS.items()}
        print(s, len(Z[s]["ts"]), pd.Timestamp(int(Z[s]["ts"][-1]), unit="ms"), flush=True)
    J = {s: {tf: judges_of(B[s][tf]) for tf in ("1h", "4h")} for s in SYMBOLS}
    D200 = {}
    for s in SYMBOLS:
        d = B[s]["1d"]
        e = np.asarray(pi.pine_ema(d["close"].to_numpy(float), 200), float)
        D200[s] = np.sign(d["close"].to_numpy(float) - e)
    out, meta = {}, {}
    for name, (tf, ov) in CELLS.items():
        rows = []
        for s in SYMBOLS:
            df = B[s][tf]
            lo, sh = P.signals(df, tf, **ov)
            atr = fg.atr(df, 14).to_numpy(float)
            close = df["close"].to_numpy(float)
            atrp = atr / close
            cms = df["close_ms"].to_numpy(np.int64)
            pk = (cms >= PICK[0]) & (cms < PICK[1]) & np.isfinite(atrp)
            q20, q80 = np.quantile(atrp[pk], [0.2, 0.8])
            meta[(name, s)] = {"atrp_q20": float(q20), "atrp_q80": float(q80)}
            bl, bs = best_flags(df, tf)
            for side, m, best in ((1, lo, bl), (-1, sh, bs)):
                idx = np.flatnonzero(np.asarray(m, bool))
                idx = idx[idx >= 300]
                rows.append(pd.DataFrame({"symbol": s, "bar": idx, "close_ms": cms[idx], "side": side, "atr": atr[idx],
                                          "atrp": atrp[idx], "best": best[idx], "close": close[idx],
                                          "vol_ok": (atrp[idx] >= q20) & (atrp[idx] <= q80)}))
        G = pd.concat(rows, ignore_index=True)
        t = G["close_ms"].to_numpy(np.int64)
        sd = G["side"].to_numpy(int)
        cols = {k: np.zeros(len(G)) for k in ("obv1h", "obv4h", "j3h", "st4h", "d200", "btc4h", "up_h", "dn_h")}
        for s in SYMBOLS:
            m = (G["symbol"] == s).to_numpy()
            tt = t[m]
            h1, h4, d1 = B[s]["1h"], B[s]["4h"], B[s]["1d"]
            k1 = at_closed(h1["close_ms"].to_numpy(np.int64), tt)
            k4 = at_closed(h4["close_ms"].to_numpy(np.int64), tt)
            kd = at_closed(d1["close_ms"].to_numpy(np.int64), tt)
            kb = at_closed(B["BTCUSDT"]["4h"]["close_ms"].to_numpy(np.int64), tt)
            cols["obv1h"][m] = take(J[s]["1h"]["OBV"], k1)
            cols["obv4h"][m] = take(J[s]["4h"]["OBV"], k4)
            cols["st4h"][m] = take(J[s]["4h"]["V39"], k4)
            cols["btc4h"][m] = take(J["BTCUSDT"]["4h"]["V39"], kb)
            cols["d200"][m] = take(D200[s], kd, warm=200)
            htf = HTF[tf]
            kh = k1 if htf == "1h" else (k4 if htf == "4h" else kd)
            if htf in ("1h", "4h"):
                cols["up_h"][m] = take(J[s][htf]["up"], kh)
                cols["dn_h"][m] = take(J[s][htf]["down"], kh)
        for k, v in cols.items():
            G[k] = v
        htf_obv = G["obv1h"] if tf == "30m" else G["obv4h"]
        j3 = np.where(sd > 0, G["up_h"] >= 3, G["dn_h"] >= 3)
        wd = pd.to_datetime(t, unit="ms", utc=True).weekday
        wknd = np.isin(wd, (5, 6))                     # KST Sat 09:00 .. Mon 09:00 = UTC Saturday and Sunday
        G["F0"] = True
        G["F1"] = G["obv4h"].to_numpy() * sd > 0
        G["F2"] = htf_obv.to_numpy() * sd > 0
        G["F3"] = j3
        G["F4"] = G["st4h"].to_numpy() * sd > 0
        G["F5"] = G["d200"].to_numpy() * sd > 0
        G["F6"] = G["btc4h"].to_numpy() * sd > 0
        G["F7"] = G["vol_ok"].to_numpy(bool)
        G["F8"] = ~wknd
        G["F9"] = sd < 0
        G["F10"] = G["F1"] & G["F5"]
        G["F11"] = G["F3"] & G["F8"]
        G["tf"] = tf
        prio = {s_: k for k, s_ in enumerate(("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"))}
        G["prio"] = G["symbol"].map(prio)
        out[name] = G.sort_values(["close_ms", "prio"]).reset_index(drop=True)
        print(name, tf, len(G), "signals", flush=True)
    with open(os.path.join(a.work, "signals.pkl"), "wb") as fh:
        pickle.dump({"cells": out, "meta": meta}, fh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
