"""Apply the missing horizon-matched time exits (TIME16/TIME64) and the exit-independent
forward-drift shift-null gate to the REAL stage-1 strategies, same windows as stage 1:
  15m: CANDIDATES_15M (30 entries), 5 symbols, window IS
  5m : V45_EXACT_AMB, V45_ANY, V45_EXACT_AMB_G1, 3 symbols, window ALL
Engine, costs and rule unchanged.  TIMEH = FIXED sl_atr=tp_atr=1e4, max_hold=H.
"""
import os, sys, time
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bt"))
import fg_indicators as fg
import strategies as S
from engine import CostCfg, ExitCfg, run_backtest
from run import load_csv, window_bounds
from analyze import pooled, apply_rule

DATA = os.path.join(HERE, "..", "data")
OUT = os.path.join(HERE, "..", "out")
HZ = (16, 64)
B = 1000


def one(tf, sym, df, strategies, lo, hi, barmin, rng, fwd_acc, trades):
    o = df["open"].to_numpy(float); n = len(o)
    atr = fg.atr(df, 14).to_numpy(float)
    R = {}
    for h in HZ:
        r = np.full(n, np.nan); r[: n - 1 - h] = o[1 + h:] / o[1: n - h] - 1.0; R[h] = r
    lo_e = max(lo, 1000)
    for name, fn in strategies.items():
        l, s = fn(df)
        l = np.asarray(l, bool); s = np.asarray(s, bool) & ~l
        idx = np.where((l | s)[lo_e:hi])[0] + lo_e
        idx = idx[idx + 1 < n]
        side = np.where(l[idx], 1.0, -1.0)
        acc = fwd_acc.setdefault(name, {h: dict(sum=0.0, cnt=0, nsum=np.zeros(B), ncnt=np.zeros(B), sym={}) for h in HZ})
        for h in HZ:
            v = side * R[h][idx]
            acc[h]["sum"] += np.nansum(v); acc[h]["cnt"] += int(np.isfinite(v).sum())
            acc[h]["sym"][sym] = float(np.nanmean(v)) if len(v) else np.nan
            if len(idx):
                L = hi - lo_e
                us = rng.integers(max(200, 2 * h), L - max(200, 2 * h), size=B)
                for b in range(B):
                    j = lo_e + (idx - lo_e + us[b]) % L
                    w = side * R[h][j]
                    acc[h]["nsum"][b] += np.nansum(w); acc[h]["ncnt"][b] += np.isfinite(w).sum()
        for h in HZ:
            cfg = ExitCfg(name=f"TIME{h}", mode="FIXED", sl_atr=1e4, tp_atr=1e4)
            t = run_backtest(df, atr, l, s, cfg, CostCfg(bar_minutes=barmin, max_hold=h), lo, hi)
            if len(t):
                t = t.copy(); t["symbol"] = sym; t["strategy"] = name; t["exit"] = cfg.name
                t["entry_ts"] = df["ts"].to_numpy()[t["entry_idx"].to_numpy()]
                trades.append(t)


def main():
    rng = np.random.default_rng(2026)
    rows = []
    for tf in ("15m", "5m"):
        fwd_acc = {}; trades = []
        syms = ("BTCUSD", "ETHUSD", "SOLUSD", "LTCUSD", "BCHUSD") if tf == "15m" else ("BTCUSD", "ETHUSD", "SOLUSD")
        for sym in syms:
            t0 = time.time()
            if tf == "15m":
                df = load_csv(os.path.join(DATA, f"{sym.lower()}-15m-ohlcv.csv"), 15)
                lo, hi = window_bounds(df, "IS"); strategies = S.CANDIDATES_15M; barmin = 15
            else:
                df = load_csv(os.path.join(DATA, f"{sym.lower()}-5m-ohlcv.csv"), 5)
                df15 = load_csv(os.path.join(DATA, f"{sym.lower()}-15m-ohlcv.csv"), 15)
                lo, hi = 0, len(df); barmin = 5
                strategies = {"V45_EXACT_AMB": (lambda d, d15=df15: S.v45_exact_amb(d, d15)),
                              "V45_ANY": (lambda d, d15=df15: S.v45_any(d, d15)),
                              "V45_EXACT_AMB_G1": (lambda d, d15=df15: S.v45_exact_amb_g1(d, d15))}
            one(tf, sym, df, strategies, lo, hi, barmin, rng, fwd_acc, trades)
            print(tf, sym, f"{time.time()-t0:.0f}s", flush=True)
        T = pd.concat(trades, ignore_index=True)
        T.to_csv(os.path.join(OUT, f"real_time_trades_{tf}.csv"), index=False)
        P = apply_rule(pooled(T))
        for name, acc in fwd_acc.items():
            r = dict(tf=tf, strategy=name)
            for h in HZ:
                a = acc[h]
                if a["cnt"] == 0:
                    continue
                obs = a["sum"] / a["cnt"]; nm = a["nsum"] / a["ncnt"]
                r.update({f"sig": a["cnt"], f"fwd{h}_pct": obs * 100, f"null{h}_mean_pct": nm.mean() * 100,
                          f"null{h}_sd_pct": nm.std(ddof=1) * 100, f"z{h}": (obs - nm.mean()) / nm.std(ddof=1),
                          f"p{h}": (1 + (nm >= obs).sum()) / (B + 1),
                          f"sympos{h}": int(sum(v > 0 for v in a["sym"].values()))})
                pr = P[(P.strategy == name) & (P.exit == f"TIME{h}")]
                if len(pr):
                    pr = pr.iloc[0]
                    r.update({f"T{h}_trades": int(pr.trades), f"T{h}_pf": pr.pf, f"T{h}_net": pr.exp_net_pct,
                              f"T{h}_gross": pr.exp_gross_pct, f"T{h}_sympos": int(pr.symbols_pos), f"T{h}_pass": bool(pr["pass"])})
            rows.append(r)
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(OUT, "real_time_gate.csv"), index=False)
    pd.set_option("display.width", 300); pd.set_option("display.max_columns", 50)
    print(R.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
