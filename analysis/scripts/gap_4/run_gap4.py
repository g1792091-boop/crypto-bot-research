"""gap_4 runner, 15m IS window only (2025-08-07 .. 2026-05-07; the OOS window stays sealed).
Parts:
  A forward drift (exit-independent, gross) for 12 new ports (+ variants) and 17 tested strategies
  B stage-1 13-exit grid, no gate           (12 new ports + variants; 17 tested = sanity reproduction)
  C stage-1 13-exit grid with hard-cap gate (keep signals with 0 < structural-stop distance <= gate)
  D native-lite engine (structural stop, cap, net-ROE lock, CONFIRM_2) x {gate none/0.6%/consistent}
    x {real cost 0.05%+0.02% slip, FINGRAD cost 0.02%+0.01% slip}
usage: python3 run_gap4.py SYMBOL[,SYMBOL]  -> out/parts_<SYMS>.pkl"""
import os, sys, time, pickle, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "bt"))
import fg_indicators as fg
from engine import CostCfg, default_exit_configs, run_backtest
from run import load_csv, window_bounds
from forward import forward_stats
from ports12 import PORTS12
from stops17 import TESTED17
from native import sim_native

D = os.path.join(HERE, "..", "data"); OUT = os.path.join(HERE, "out"); os.makedirs(OUT, exist_ok=True)
GATE = 0.006
COSTS = {"real": dict(fee=0.0005, slip=0.0002), "fg": dict(fee=0.0002, slip=0.0001)}


def strategies():
    s = {}
    for k, f in PORTS12.items():
        s[k] = (f, 0, "new")
    for k in ("N11_BREAKAWAY", "N13_3OUTSIDE", "N19_FIB_CHOP"):
        s[k + "~v1"] = (PORTS12[k], 1, "variant")
    s["N11_BREAKAWAY~stopbar5"] = (lambda df, variant=0: PORTS12["N11_BREAKAWAY"](df, 0, stop_variant=1), 0, "variant")
    for k, f in TESTED17.items():
        s[k] = (f, 0, "tested")
    return s


def main(syms):
    cfgs = default_exit_configs(); cost = CostCfg()
    STR = strategies()
    fw, trB, trC, trD, gstat = [], [], [], [], []
    for sym in syms:
        df = load_csv(os.path.join(D, f"{sym.lower()}-15m-ohlcv.csv"), 15)
        atr = fg.atr(df, 14).to_numpy(float); lo, hi = window_bounds(df, "IS")
        c = df["close"].to_numpy(float); ts = df["ts"].to_numpy()
        for name, (fn, var, grp) in STR.items():
            t0 = time.time()
            sig = fn(df, variant=var)
            L, S = sig["L"], sig["S"]
            # A forward
            r = forward_stats(df, L, S, lo, hi); r.update(symbol=sym, strategy=name, group=grp); fw.append(r)
            # structural-stop distance per signal (from signal close)
            with np.errstate(invalid="ignore"):
                dL = (c - sig["stopL"]) / c; dS = (sig["stopS"] - c) / c
            dist = np.where(L, dL, np.where(S, dS, np.nan))
            sl = slice(max(lo, 1000), hi)
            dd = dist[sl][(L | S)[sl]]
            gstat.append(dict(symbol=sym, strategy=name, group=grp, signals=int(len(dd)),
                              nan_stop=int(np.isnan(dd).sum()), wrong_side=int((dd <= 0).sum()),
                              le_046=int(((dd > 0) & (dd <= 0.0046)).sum()), le_054=int(((dd > 0) & (dd <= 0.0054)).sum()),
                              le_060=int(((dd > 0) & (dd <= GATE)).sum()), med_dist_pct=float(np.nanmedian(dd) * 100) if len(dd) else np.nan))
            gok = np.isfinite(dist) & (dist > 0) & (dist <= GATE)
            Lg, Sg = L & gok, S & gok
            rg = forward_stats(df, Lg, Sg, lo, hi); rg.update(symbol=sym, strategy=name + "|gate0.6", group=grp); fw.append(rg)
            for cfg in cfgs:
                for tag, (LL, SS), store in (("nogate", (L, S), trB), ("gate0.6", (Lg, Sg), trC)):
                    if tag == "nogate" and grp == "tested" and cfg.name not in ("F_sl2.0_tp3.0", "L50_sl20"):
                        continue  # sanity reproduction on 2 exits only
                    t = run_backtest(df, atr, LL, SS, cfg, cost, lo, hi)
                    if len(t):
                        t = t.copy(); t["symbol"] = sym; t["strategy"] = name; t["exit"] = cfg.name; t["group"] = grp
                        t["entry_ts"] = ts[t["entry_idx"].to_numpy()]; store.append(t)
            # D native-lite
            for cn, cc in COSTS.items():
                cons = 0.30 / 50.0 - 2 * cc["fee"] - 2 * cc["slip"]
                for gname, g in (("none", None), ("0.6", GATE), (f"cap{cons*100:.2f}", cons)):
                    t, blk = sim_native(df, sig, lo, hi, fee=cc["fee"], slip=cc["slip"], gate=g)
                    if len(t):
                        t = t.copy(); t["symbol"] = sym; t["strategy"] = name; t["group"] = grp
                        t["exit"] = f"NATIVE_{cn}_gate{gname}"; t["entry_ts"] = ts[t["entry_idx"].to_numpy()]; trD.append(t)
            print(f"{sym} {name:24s} sig={int((L|S)[max(lo,1000):hi].sum()):6d} gate0.6={int(gok[max(lo,1000):hi].sum()):5d} {time.time()-t0:.1f}s", flush=True)
    res = dict(fw=pd.DataFrame(fw), gstat=pd.DataFrame(gstat),
               B=pd.concat(trB) if trB else None, C=pd.concat(trC) if trC else None, D=pd.concat(trD) if trD else None)
    with open(os.path.join(OUT, f"parts_{'_'.join(syms)}.pkl"), "wb") as fh:
        pickle.dump(res, fh)


if __name__ == "__main__":
    main(sys.argv[1].split(","))
