#!/usr/bin/env python3
"""Five-year every-signal outcomes of the 36 strategies at a fixed 30x (and optionally 10x), 2 ATR stop, paper
ladder, via the repo's research scan (profiles._scan), but with the GROSS taken directly from prices:
    gross_pre = side * (exit_raw / raw - 1)        raw = next-bar open (no slippage), exit_raw = level before slip
    net       = roe / lev
The chosen side and the opposite side at the same bar are both run.

python3 -I v3_5y.py <repo> <signals_dir> <out_csv_gz> [lev=30] [tfs=15m,30m,1h] [procs=4]
"""
import importlib.util
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vboot  # noqa
import numpy as np
import pandas as pd

G = {}


def load_levstop(repo):
    sys.path.insert(0, repo)
    spec = importlib.util.spec_from_file_location("levstop_v", os.path.join(repo, "research", "levstop", "levstop.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run_side(LS, b, idx, side, tf, lev, k=2.0):
    P = LS._profiles()
    RB = P.RB
    from paperbot import sweepsig
    L = sweepsig.lib()
    n = len(b["ts"])
    f_bar = RB.FUNDING_8H * L.tf_minutes(tf) / 480.0
    m = len(idx)
    raw = b["o"][idx + 1]
    a = b["atr"][idx]
    fs = LS.FixedSizer(int(lev), k)
    levv = np.full(m, float(lev))
    liq_frac = np.where(side > 0, fs.liq_frac[1], fs.liq_frac[-1])
    slip = RB.SETTINGS.slippage_frac
    fill = raw * (1 + side * slip)
    liq = fill * (1 - side * liq_frac)
    cap = side * (raw - liq) / a
    clipped = cap <= k
    kk = np.minimum(np.full(m, k), cap)
    out = {x: np.full(m, np.nan) for x in ("held", "roe", "reason", "exit_px")}
    todo = np.arange(m)
    for H in (64, 512, 4096):
        if not len(todo):
            break
        nxt = []
        step = max(32, 256_000 // H)
        for c0 in range(0, len(todo), step):
            sel = todo[c0:c0 + step]
            r = P._scan(b, idx[sel], side[sel], levv[sel], liq_frac[sel], H, n, f_bar, k_stop=kk[sel])
            keep = r["done"] | (H == 4096) | (idx[sel] + H >= n - 1)
            for x in ("held", "roe", "reason", "exit_px"):
                out[x][sel[keep]] = r[x][keep]
            nxt.append(sel[~keep])
        todo = np.concatenate(nxt) if nxt else np.zeros(0, int)
    reason = np.where(clipped & (out["reason"] == 0), 2.0, out["reason"])
    roe = np.where(reason == 2, -1.0, out["roe"])
    exit_raw = np.where(reason == 2, out["exit_px"], out["exit_px"] / (1 - side * slip))
    gross = side * (exit_raw / raw - 1)
    gross = np.where(reason == 2, -1.0 / lev, gross)       # liquidation: whole margin, count as price loss
    return dict(roe=roe, reason=reason, held=out["held"], gross=gross, f_bar=f_bar)


def job(args):
    strategy, tf = args
    LS, sig_dir, lev = G["LS"], G["sig_dir"], G["lev"]
    from paperbot import sweepsig
    RB = LS._profiles().RB
    L = sweepsig.lib()
    edges = [(LS._ns(a), LS._ns(b)) for _p, a, b in LS.PERIODS]
    out = []
    for c in LS.COINS:
        got = LS._bars(sig_dir, tf).get(c)
        if got is None or f"s__{strategy}" not in got[1].files:
            continue
        b, z = got
        sg = z[f"s__{strategy}"]
        n = len(b["ts"])
        lo = RB.window_bounds(L, b, tf, "is")[0]
        n_end = RB.window_bounds(L, b, tf, "cf")[1]
        idx = np.nonzero(sg[lo:max(lo, n_end - 1)])[0] + lo
        ok = np.isfinite(b["atr"][idx]) & (b["atr"][idx] > 0) & np.isfinite(b["o"][np.minimum(idx + 1, n - 1)])
        idx = idx[ok]
        ts = b["ts"][idx]
        per = np.zeros(len(idx), int)
        for k_, (a, e) in enumerate(edges, 1):
            per[(ts >= a) & (ts < e)] = k_
        idx, ts, per = idx[per > 0], ts[per > 0], per[per > 0]
        if not len(idx):
            continue
        side = sg[idx].astype(int)
        s1 = run_side(LS, b, idx, side, tf, lev)
        s2 = run_side(LS, b, idx, -side, tf, lev)
        stop_frac = 2.0 * b["atr"][idx] / b["o"][idx + 1]
        out.append(pd.DataFrame({
            "strategy": strategy, "tf": tf, "coin": c, "ts": ts, "period": per, "side": side, "stop_frac": stop_frac,
            "net_n": s1["roe"] / lev, "gross_n": s1["gross"], "reason": s1["reason"], "held": s1["held"],
            "net_n_flip": s2["roe"] / lev, "gross_n_flip": s2["gross"], "reason_flip": s2["reason"],
            "fund_n": s1["f_bar"] * s1["held"]}))
    return pd.concat(out) if out else pd.DataFrame()


def main():
    repo, sig_dir, out = sys.argv[1:4]
    lev = int(sys.argv[4]) if len(sys.argv) > 4 else 30
    tfs = (sys.argv[5] if len(sys.argv) > 5 else "15m,30m,1h").split(",")
    procs = int(sys.argv[6]) if len(sys.argv) > 6 else 4
    LS = load_levstop(repo)
    G.update(LS=LS, sig_dir=sig_dir, lev=lev)
    strategies = sorted({k[3:] for k in np.load(os.path.join(sig_dir, "sig_15m_BTCUSD.npz")).files if k.startswith("s__")})
    print("strategies", len(strategies))
    jobs = [(s, tf) for tf in tfs for s in strategies]
    t0 = time.time()
    import multiprocessing as mp
    with mp.get_context("fork").Pool(procs) as pool:
        parts = pool.map(job, jobs, chunksize=1)
    D = pd.concat([p for p in parts if len(p)], ignore_index=True)
    print("rows", len(D), "open-at-end", int((D["reason"] == 3).sum()), "s", round(time.time() - t0, 1))
    D.to_csv(out, index=False, compression="gzip")


if __name__ == "__main__":
    main()
