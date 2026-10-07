"""5-year every-signal rerun of the 36 locked strategies with per-signal output (timestamps kept).

    python3 -I -B fy36_rerun.py <signals_dir> <out_dir> [procs]

Reuses research/strategy_profiles/profiles.py (_scan, the paper v3 ladder exit) READ-ONLY (import only, -B so no
pycache is written into the repo). Two leverage modes per signal:
  tw   = the old tier walk (rules_bt.SETTINGS, $1,000 sizing equity): reproduces profiles.json mean_roe (parity check)
  v4n  = paper v4 "normal" group (config.v3_settings(): quality_v1, 30x/30% then 20x/20%), $5,000 equity
Per signal: strategy, coin, signal ts, side, lev, roe, R (= roe / (lev * stop_frac)), net ret per notional,
gross ret per notional (before fees, slippage, funding), stop_frac, exit reason, held bars, window (is/cf).
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from multiprocessing import Pool

sys.path.append('/root/.local/lib/python3.11/site-packages')
REPO = '/home/user/crypto-bot-research'
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'research', 'paper_rules'))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

spec = importlib.util.spec_from_file_location('profiles_ro', os.path.join(REPO, 'research', 'strategy_profiles', 'profiles.py'))
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
RB = P.RB
from paperbot import sweepsig  # noqa: E402
from paperbot.sizing import size_position  # noqa: E402
from paperbot.config import v3_settings  # noqa: E402

TFS = ("5m", "15m", "30m", "1h", "4h")
K = 2.0
V4S = v3_settings()


def sizer_v4n(equity=5000.0):
    cache = {}

    def lev_liq(side, atr_frac):
        key = (side, float(f"{atr_frac:.4g}"))
        if key not in cache:
            raw = 100.0
            a = key[1] * raw
            fill = raw * (1 + side * V4S.slippage_frac)
            d = size_position(V4S, equity, side, fill, raw - side * K * a, "normal", RB.BRACKETS,
                              atr=a, min_notional=RB.MIN_NOTIONAL)
            cache[key] = (d.leverage, side * (fill - d.liq_price) / fill) if d.ok else (0, np.nan)
        return cache[key]
    return lev_liq


def run_mode(b, idx, side, lev, liq_frac, n, f_bar):
    res = {k: np.full(len(idx), np.nan) for k in ("held", "roe", "reason", "exit_px")}
    todo = np.nonzero(lev > 0)[0]
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
    sz_tw = P._sizer()
    sz_v4 = sizer_v4n()
    cf0 = pd.Timestamp(RB.WINDOWS["cf"][0]).value
    slip = RB.SETTINGS.slippage_frac
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
        out = dict(strategy=name, coin=coin, tf=tf, ts=b["ts"][idx], side=side.astype(np.int8),
                   win=np.where(b["ts"][idx] < cf0, 0, 1).astype(np.int8), stop_frac=stop_frac.astype(np.float32))
        for mode, sz in (("tw", sz_tw), ("v4n", sz_v4)):
            ll = np.array([sz(int(s), float(x)) for s, x in zip(side, atr / raw)]).reshape(-1, 2)
            lev, liq_frac = ll[:, 0], ll[:, 1]
            r = run_mode(b, idx, side, lev, liq_frac, n, f_bar)
            roe = r["roe"]
            done = np.isfinite(r["reason"]) & (r["reason"] < 3)
            with np.errstate(invalid="ignore", divide="ignore"):
                ret = np.where(lev > 0, roe / np.where(lev > 0, lev, 1), np.nan)
                R = ret / stop_frac
                exit_raw = r["exit_px"] / (1 - side * slip)
                gross = side * (exit_raw / raw - 1)
            out[f"{mode}_lev"] = lev.astype(np.int16)
            out[f"{mode}_done"] = done
            out[f"{mode}_roe"] = roe.astype(np.float32)
            out[f"{mode}_ret"] = ret.astype(np.float32)
            out[f"{mode}_R"] = R.astype(np.float32)
            out[f"{mode}_gross"] = np.where(r["reason"] == 2, np.nan, gross).astype(np.float32)
            out[f"{mode}_reason"] = r["reason"].astype(np.float32)
            out[f"{mode}_held"] = r["held"].astype(np.float32)
        frames.append(pd.DataFrame(out))
    days = (n_end - lo_all) * L.tf_minutes(tf) / 1440.0
    return tf, coin, (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), days


def main(sig_dir, out_dir, procs=4):
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    meta = []
    for tf in TFS:
        with Pool(procs) as pool:
            got = pool.map(job, [(tf, c, sig_dir) for c in RB.COINS])
        df = pd.concat([g[2] for g in got], ignore_index=True)
        for c in ("strategy", "coin", "tf"):
            df[c] = df[c].astype("category")
        df.to_pickle(os.path.join(out_dir, f"fy36_{tf}.pkl.gz"))
        meta.append(dict(tf=tf, days=got[0][3], rows=len(df)))
        print(tf, len(df), f"{time.time() - t0:.0f}s", flush=True)
    pd.DataFrame(meta).to_csv(os.path.join(out_dir, "fy36_meta.csv"), index=False)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 4)
