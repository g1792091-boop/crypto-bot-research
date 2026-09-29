"""Positive control #3 (gap_2): can the stage-1 pipeline say PASS when a real edge exists?

Extends critic/work/posctrl2.py:
  * timeframes: 5m (BTC/ETH/SOL, window ALL, max_hold 3000 as run.py:143),
                15m (5 symbols, window IS as stage 1, max_hold 1000),
                1h  (5 symbols, 15m resampled, window ALL, max_hold 1000 = CostCfg default)
  * exits: all 13 stage-1 exits (engine.default_exit_configs, unchanged)
           + TIME16 / TIME64 = FIXED sl_atr=tp_atr=1e4, CostCfg.max_hold=H
             (exit at close[e+H-1] ~= open[e+H] = forward.py fwdH endpoint)
  * two oracle types
      sign : at random bars, side = sign(o[i+1+k]/o[i+1]-1) with prob q else random
             (hit rate at k = (1+q)/2).  Price data untouched.
      drift: random bars, random side; a linear log-price ramp of +mu (in side direction)
             is ADDED to the real bars over the H bars after entry, then held (permanent).
             ATR recomputed on the modified bars.
  * the stage-1 rule (analyze.apply_rule) and costs (CostCfg defaults) are unchanged.
  * exit-independent forward drift fwd16/fwd64 over ALL oracle signals + a circular
    shift null (per symbol, B shifts) -> z and one-sided p.
Output: one CSV row per (tf, oracle, k, dial, seed, exit).
"""
import argparse, os, sys, time
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bt"))
import fg_indicators as fg
from engine import CostCfg, ExitCfg, default_exit_configs, run_backtest
from run import load_csv, window_bounds
from analyze import pooled, apply_rule

DATA = os.path.join(HERE, "..", "data")
SYMS = {"5m": ("BTCUSD", "ETHUSD", "SOLUSD"),
        "15m": ("BTCUSD", "ETHUSD", "SOLUSD", "LTCUSD", "BCHUSD"),
        "1h": ("BTCUSD", "ETHUSD", "SOLUSD", "LTCUSD", "BCHUSD")}
BARMIN = {"5m": 5, "15m": 15, "1h": 60}
WINDOW = {"5m": "ALL", "15m": "IS", "1h": "ALL"}
MAXHOLD = {"5m": 3000, "15m": 1000, "1h": 1000}
HZ = (16, 64)


def resample_1h(df15):
    g = df15.set_index("ts").resample("1h", label="left", closed="left")
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "volume": g["volume"].sum(), "nb": g["open"].count()})
    out = out[out["nb"] > 0].reset_index()
    out["open_time"] = out["ts"].astype("int64") // 10**6
    return out


def load_tf(tf):
    out = {}
    for s in SYMS[tf]:
        if tf == "1h":
            df = resample_1h(load_csv(os.path.join(DATA, f"{s.lower()}-15m-ohlcv.csv"), 15))
        else:
            df = load_csv(os.path.join(DATA, f"{s.lower()}-{tf}-ohlcv.csv"), BARMIN[tf])
        out[s] = df
    return out


def exits():
    base = default_exit_configs()
    t = [ExitCfg(name=f"TIME{h}", mode="FIXED", sl_atr=1e4, tp_atr=1e4) for h in HZ]
    return base + t


def family(name):
    if name.startswith("F_"):
        return "FIXED9"
    if name.startswith("T_"):
        return "TRAIL2"
    if name.startswith("L50"):
        return "LADDER2"
    return name


def fwd_arrays(o, n):
    """R[h][t] = o[t+1+h]/o[t+1]-1 (NaN where undefined)"""
    R = {}
    for h in HZ:
        r = np.full(n, np.nan)
        r[: n - 1 - h] = o[1 + h:] / o[1: n - h] - 1.0
        R[h] = r
    return R


def run_cell(tf, dfs, oracle, k, dial, seed, dens, B, cfgs):
    rng = np.random.default_rng([seed, int(k), int(round(dial * 1e4)), 1 if oracle == "sign" else 2, BARMIN[tf]])
    trades = []
    fw = {h: [] for h in HZ}
    null_sum = {h: np.zeros(B) for h in HZ}
    null_cnt = {h: np.zeros(B) for h in HZ}
    per_sym_fwd = {}
    for sym, df0 in dfs.items():
        n = len(df0)
        lo, hi = window_bounds(df0, WINDOW[tf]) if tf != "1h" else (0, n)
        lo_e = max(lo, 1000)
        hi_e = min(hi, n - max(HZ) - 3)
        nsig = int(dens * (hi_e - lo_e))
        idx = np.sort(rng.choice(np.arange(lo_e, hi_e), size=nsig, replace=False))
        if oracle == "sign":
            df = df0
            o = df["open"].to_numpy(float)
            fut = np.sign(o[idx + 1 + k] / o[idx + 1] - 1)
            rnd = rng.choice([-1, 1], size=nsig)
            side = np.where(rng.random(nsig) < dial, fut, rnd)
            side[side == 0] = 1
        else:  # planted additive drift ramp of mu over k bars, then held
            side = rng.choice([-1, 1], size=nsig).astype(float)
            mu = dial
            e = idx + 1
            # a_open[t] = sum_i s_i*mu*clip((t-e_i)/k,0,1); a_close[t] = same at t+1
            slope = np.zeros(n + 2)
            np.add.at(slope, e, side * mu / k)
            np.add.at(slope, np.minimum(e + k, n + 1), -side * mu / k)
            d = np.cumsum(slope)[: n + 1]          # per-bar increment applied between t and t+1
            a_open = np.concatenate([[0.0], np.cumsum(d)[:-1]])[:n]   # value at open of bar t
            a_close = a_open + d[:n]
            df = df0.copy()
            ea, ec = np.exp(a_open), np.exp(a_close)
            df["open"] = df0["open"].to_numpy(float) * ea
            df["close"] = df0["close"].to_numpy(float) * ec
            df["high"] = df0["high"].to_numpy(float) * np.maximum(ea, ec)
            df["low"] = df0["low"].to_numpy(float) * np.minimum(ea, ec)
            o = df["open"].to_numpy(float)
        R = fwd_arrays(o, n)
        per_sym_fwd[sym] = {}
        for h in HZ:
            v = side * R[h][idx]
            fw[h].append(v)
            per_sym_fwd[sym][h] = float(np.nanmean(v))
            # shift null
            L = hi_e - lo_e
            for b in range(B):
                u = rng.integers(max(200, 2 * h), L - max(200, 2 * h))
                j = lo_e + (idx - lo_e + u) % L
                w = side * R[h][j]
                null_sum[h][b] += np.nansum(w)
                null_cnt[h][b] += np.isfinite(w).sum()
        atr = fg.atr(df, 14).to_numpy(float)
        L_ = np.zeros(n, bool); S_ = np.zeros(n, bool)
        L_[idx[side > 0]] = True; S_[idx[side < 0]] = True
        for cfg in cfgs:
            mh = int(cfg.name[4:]) if cfg.name.startswith("TIME") else MAXHOLD[tf]
            cc = CostCfg(bar_minutes=BARMIN[tf], max_hold=mh)
            t = run_backtest(df, atr, L_, S_, cfg, cc, lo, hi).copy()
            t["symbol"] = sym; t["strategy"] = "oracle"; t["exit"] = cfg.name
            t["entry_ts"] = df["ts"].to_numpy()[t["entry_idx"].to_numpy()]
            trades.append(t)
    T = pd.concat(trades, ignore_index=True)
    P = apply_rule(pooled(T))
    stats = {}
    for h in HZ:
        allv = np.concatenate(fw[h]); obs = float(np.nanmean(allv))
        nullm = null_sum[h] / null_cnt[h]
        stats[f"fwd{h}_pct"] = obs * 100
        stats[f"fwd{h}_hit"] = float(np.nanmean(allv > 0))
        stats[f"fwd{h}_null_mean_pct"] = float(nullm.mean() * 100)
        stats[f"fwd{h}_null_sd_pct"] = float(nullm.std(ddof=1) * 100)
        stats[f"fwd{h}_z"] = float((obs - nullm.mean()) / nullm.std(ddof=1))
        stats[f"fwd{h}_p"] = float((1 + (nullm >= obs).sum()) / (B + 1))
        stats[f"fwd{h}_sym_pos"] = int(sum(per_sym_fwd[s][h] > 0 for s in per_sym_fwd))
    rows = []
    for _, r in P.iterrows():
        rows.append(dict(tf=tf, oracle=oracle, k=k, dial=dial, seed=seed, exit=r["exit"], family=family(r["exit"]),
                         trades=int(r["trades"]), exp_gross=r["exp_gross_pct"], exp_net=r["exp_net_pct"],
                         pf=r["pf"], wr=r["wr"], hold=r["avg_hold"], sym_pos=int(r["symbols_pos"]),
                         nsym=int(r["symbols"]), eqL50=r["eq_L50"], liqL50=r["liq_L50"], passed=bool(r["pass"]),
                         nsig=int(sum(len(x) for x in fw[HZ[0]])), **stats))
    return rows, T


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", required=True)
    ap.add_argument("--oracle", required=True, choices=["sign", "drift"])
    ap.add_argument("--ks", default="16,64")
    ap.add_argument("--dials", required=True)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--dens", type=float, default=0.03)
    ap.add_argument("--B", type=int, default=300)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    dfs = load_tf(a.tf)
    for s, d in dfs.items():
        print(a.tf, s, len(d), d["ts"].iloc[0], d["ts"].iloc[-1], flush=True)
    cfgs = exits()
    rows = []
    t0 = time.time()
    for k in [int(x) for x in a.ks.split(",")]:
        for dial in [float(x) for x in a.dials.split(",")]:
            for seed in range(a.seeds):
                r, _ = run_cell(a.tf, dfs, a.oracle, k, dial, seed, a.dens, a.B, cfgs)
                rows += r
                best = max(r, key=lambda x: x["pf"])
                print(f"{a.tf} {a.oracle} k={k} dial={dial} seed={seed} fwd{k}={r[0][f'fwd{k}_pct']:.3f}% z={r[0][f'fwd{k}_z']:.2f} "
                      f"pass={[x['exit'] for x in r if x['passed']]} best={best['exit']}:{best['pf']:.2f} ({time.time()-t0:.0f}s)", flush=True)
                pd.DataFrame(rows).to_csv(a.out, index=False)


if __name__ == "__main__":
    main()
