"""5-year every-signal outcomes of the 36 locked strategies at FIXED leverage 10/20/30/40/50 (house exit: 2 ATR stop +
ROE ladder of paper v3/v4, whose price levels depend on the leverage), per sizing rule's liquidation price.

    python3 -I -B s2_rerun.py <workdir> <signals_dir> <out_dir> [procs]

Reuses research/strategy_profiles/profiles.py _scan READ-ONLY (import with -B: no pycache in the repo), the same call
pattern as lens/fiveyear/fy36_rerun.py (its tw / v4n modes reproduce profiles.json; here the leverage is fixed).
Modes: M = margin rule (margin L% of equity, notional L^2/100 x $5,000) liquidation price; K = risk rule (notional =
2% of $5,000 / loss per notional) liquidation price. Exit prices do not depend on the mode except through a gap
beyond the liquidation price. Per signal also the executability flags of each rule at L (common.check).
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from multiprocessing import Pool

sys.dont_write_bytecode = True
WD = sys.argv[1]
sys.path.insert(0, WD)
sys.path.append('/root/.local/lib/python3.11/site-packages')
REPO = '/home/user/crypto-bot-research'
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'research', 'paper_rules'))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import common as C  # noqa: E402

spec = importlib.util.spec_from_file_location('profiles_ro', os.path.join(REPO, 'research', 'strategy_profiles', 'profiles.py'))
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
RB = P.RB
from paperbot import sweepsig  # noqa: E402

TFS = ("15m", "30m", "1h", "4h")
K = 2.0
LEVS = (10, 20, 30, 40, 50)


def run_mode(b, idx, side, lev, liq_frac, n, f_bar):
    res = {k: np.full(len(idx), np.nan) for k in ("held", "roe", "reason", "exit_px")}
    todo = np.arange(len(idx))
    for H in (64, 512, 4096):
        if not len(todo):
            break
        nxt = []
        step = max(32, 256_000 // H)
        for c0 in range(0, len(todo), step):
            sel = todo[c0:c0 + step]
            r = P._scan(b, idx[sel], side[sel], lev[sel], liq_frac[sel], H, n, f_bar)
            last = H == 4096
            keep = r["done"] | last | (idx[sel] + H >= n - 1)
            for k in ("held", "roe", "reason", "exit_px"):
                res[k][sel[keep]] = r[k][keep]
            nxt.append(sel[~keep])
        todo = np.concatenate(nxt) if nxt else np.zeros(0, int)
    return res


def job(args):
    tf, coin, sig_dir = args
    L = sweepsig.lib()
    z = np.load(os.path.join(sig_dir, f"sig_{tf}_{coin}.npz"))
    b = {k: z[k] for k in ("ts", "o", "h", "l", "c", "atr")}
    n = len(b["ts"])
    f_bar = RB.FUNDING_8H * L.tf_minutes(tf) / 480.0
    wins = {w: RB.window_bounds(L, b, tf, w) for w in RB.WINDOWS}
    lo_all, n_end = wins["is"][0], wins["cf"][1]
    cf0 = pd.Timestamp(RB.WINDOWS["cf"][0]).value
    slip = RB.SETTINGS.slippage_frac
    ck = C.coin_key(coin)
    frames = []
    for key in (k for k in z.files if k.startswith("s__")):
        name = key[3:]
        sg = z[key]
        idx = np.nonzero(sg[lo_all:n_end - 1])[0] + lo_all
        a = b["atr"][idx]
        ok = np.isfinite(a) & (a > 0) & np.isfinite(b["o"][np.minimum(idx + 1, n - 1)])
        idx = idx[ok]
        if not len(idx):
            continue
        side = sg[idx].astype(int)
        raw = b["o"][idx + 1]
        atr = b["atr"][idx]
        fill = raw * (1 + side * slip)
        stop_frac = (raw * slip + K * atr) / fill
        afrac = atr / fill
        out = dict(strategy=name, coin=coin, tf=tf, ts=b["ts"][idx], side=side.astype(np.int8),
                   win=np.where(b["ts"][idx] < cf0, 0, 1).astype(np.int8), stop_frac=stop_frac.astype(np.float32))
        for Lv in LEVS:
            mM = C.margin_rule(ck, side, stop_frac, afrac, Lv)
            mK = C.risk_rule(ck, side, stop_frac, afrac, Lv, 0.02)
            out[f"okM{Lv}"] = mM["ok"]
            out[f"okK{Lv}"] = mK["ok"]
            for mode, m in (("M", mM), ("K", mK)):
                if mode == "K" or True:
                    lev = np.full(len(idx), float(Lv))
                    liq = np.clip(m["liq"], 1e-6, None)
                    r = run_mode(b, idx, side, lev, liq, n, f_bar)
                    roe = r["roe"]
                    with np.errstate(invalid="ignore", divide="ignore"):
                        ret = roe / Lv
                        R = ret / stop_frac
                        exit_raw = np.where(r["reason"] == 2, r["exit_px"], r["exit_px"] / (1 - side * slip))
                        gross = side * (exit_raw / raw - 1)
                    out[f"R_{mode}{Lv}"] = R.astype(np.float32)
                    out[f"gR_{mode}{Lv}"] = (gross / stop_frac).astype(np.float32)
                    out[f"rs_{mode}{Lv}"] = r["reason"].astype(np.float32)
                    out[f"h_{mode}{Lv}"] = r["held"].astype(np.float32)
        frames.append(pd.DataFrame(out))
    days = (n_end - lo_all) * L.tf_minutes(tf) / 1440.0
    return tf, coin, (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), days


def main(sig_dir, out_dir, procs=4):
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    for tf in TFS:
        with Pool(procs) as pool:
            got = pool.map(job, [(tf, c, sig_dir) for c in RB.COINS])
        df = pd.concat([g[2] for g in got], ignore_index=True)
        for c in ("strategy", "coin", "tf"):
            df[c] = df[c].astype("category")
        df.to_pickle(os.path.join(out_dir, f"lev_{tf}.pkl"))
        print(tf, len(df), f"{time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main(sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 4)
