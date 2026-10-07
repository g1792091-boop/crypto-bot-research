"""House-exit every-signal simulation on a signal cache, v4n mode only (copied from lens/fiveyear/fy36_rerun.py and
fyds_rerun.py, which were row-parity-verified by verify3/v3sim.py): next-bar open + slippage, 2 x ATR14 stop, paper v3
ladder via research/strategy_profiles/profiles._scan (read-only import), v4 'normal' sizing ($5,000), taker fee,
slippage, funding 0.01%/8h. Optionally also the same signal with the side flipped (coin-flip benchmark at the same
moment).

    python3 -I -B repl_sim.py <sig_dir> <kind core|ds> <start> <end> <out_pkl_prefix> [flip 0|1] [procs]
"""
import importlib.util
import os
import sys
import time
from multiprocessing import Pool

sys.path.append('/root/.local/lib/python3.11/site-packages')
REPO = '/home/user/crypto-bot-research'
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'research', 'paper_rules'))
import numpy as np  # noqa
import pandas as pd  # noqa

spec = importlib.util.spec_from_file_location('profiles_ro', os.path.join(REPO, 'research', 'strategy_profiles', 'profiles.py'))
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
RB = P.RB
from paperbot import sweepsig  # noqa
from paperbot.sizing import size_position  # noqa
from paperbot.config import v3_settings  # noqa

K = 2.0
V4S = v3_settings()
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
TFS = {"core": ("5m", "15m", "30m", "1h", "4h"), "ds": ("15m", "30m", "1h", "4h")}


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


def run_mode(b, idx, side, lev, liq_frac, n, f_bar, hs=(64, 512, 4096)):
    res = {k: np.full(len(idx), np.nan) for k in ("held", "roe", "reason", "exit_px")}
    todo = np.nonzero(lev > 0)[0]
    for H in hs:
        if not len(todo):
            break
        nxt = []
        step = max(32, 256_000 // H)
        for c0 in range(0, len(todo), step):
            sel = todo[c0:c0 + step]
            r = P._scan(b, idx[sel], side[sel], lev[sel], liq_frac[sel], H, n, f_bar)
            keep = r["done"] | (H == hs[-1]) | (idx[sel] + H >= n - 1)
            for k in res:
                res[k][sel[keep]] = r[k][keep]
            nxt.append(sel[~keep])
        todo = np.concatenate(nxt) if nxt else np.zeros(0, int)
    return res


def one(b, idx, side, n, f_bar, sz, slip):
    ll = np.array([sz(int(s), float(x)) for s, x in zip(side, b["atr"][idx] / b["o"][idx + 1])]).reshape(-1, 2)
    lev, liq_frac = ll[:, 0], ll[:, 1]
    r = run_mode(b, idx, side, lev, liq_frac, n, f_bar)
    raw = b["o"][idx + 1]
    stop_frac = (raw * slip + K * b["atr"][idx]) / (raw * (1 + side * slip))
    with np.errstate(invalid="ignore", divide="ignore"):
        ret = np.where(lev > 0, r["roe"] / np.where(lev > 0, lev, 1), np.nan)
        R = ret / stop_frac
        gross = side * (r["exit_px"] / (1 - side * slip) / raw - 1)
    done = np.isfinite(r["reason"]) & (r["reason"] < 3)
    return dict(lev=lev.astype(np.int16), done=done, R=R.astype(np.float32),
                gross=np.where(r["reason"] == 2, np.nan, gross).astype(np.float32),
                reason=r["reason"].astype(np.float32), held=r["held"].astype(np.float32)), stop_frac


def job(args):
    sig_dir, kind, tf, coin, start, end, flip = args
    L = sweepsig.lib()
    z = np.load(os.path.join(sig_dir, f"sig_{tf}_{coin}.npz"))
    b = {k: z[k] for k in ("ts", "o", "h", "l", "c", "atr")}
    n = len(b["ts"])
    f_bar = RB.FUNDING_8H * L.tf_minutes(tf) / 480.0
    lo = max(int(np.searchsorted(b["ts"], pd.Timestamp(start).value)), L.warmup_bars(tf))
    n_end = int(np.searchsorted(b["ts"], pd.Timestamp(end).value))
    slip = RB.SETTINGS.slippage_frac
    sz = sizer_v4n()
    frames = []
    only = set(filter(None, os.environ.get("REPL_NAMES", "").split(",")))
    for key in (k for k in z.files if k.startswith("s__") and (not only or k[3:] in only)):
        sg = z[key]
        idx = np.nonzero(sg[lo:n_end - 1])[0] + lo
        a = b["atr"][idx]
        ok = np.isfinite(a) & (a > 0) & np.isfinite(b["o"][np.minimum(idx + 1, n - 1)])
        idx = idx[ok]
        if not len(idx):
            continue
        side = sg[idx].astype(int)
        res, stop_frac = one(b, idx, side, n, f_bar, sz, slip)
        d = dict(strategy=key[3:], coin=coin, tf=tf, ts=b["ts"][idx], side=side.astype(np.int8),
                 stop_frac=stop_frac.astype(np.float32), **{f"v4n_{k}": v for k, v in res.items()})
        if flip:
            rf, _ = one(b, idx, -side, n, f_bar, sz, slip)
            d.update({f"fl_{k}": v for k, v in rf.items() if k in ("lev", "done", "R", "gross")})
        frames.append(pd.DataFrame(d))
    days = (n_end - 1 - lo) * L.tf_minutes(tf) / 1440.0
    return tf, coin, (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), days


def main(sig_dir, kind, start, end, out, flip=0, procs=3):
    t0 = time.time()
    meta = []
    tfs = [t for t in os.environ.get("REPL_TFS", "").split(",") if t] or TFS[kind]
    for tf in tfs:
        with Pool(procs) as pool:
            got = pool.map(job, [(sig_dir, kind, tf, c, start, end, int(flip)) for c in COINS])
        df = pd.concat([g[2] for g in got], ignore_index=True)
        for c in ("strategy", "coin", "tf"):
            df[c] = df[c].astype("category")
        df.to_pickle(f"{out}_{tf}.pkl.gz")
        for g in got:
            meta.append(dict(kind=kind, tf=tf, coin=g[1], days=g[3], rows=len(g[2])))
        print(kind, tf, len(df), f"{time.time() - t0:.0f}s", flush=True)
    pd.DataFrame(meta).to_csv(f"{out}_meta.csv", index=False)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], a[2], a[3], a[4], int(a[5]) if len(a) > 5 else 0, int(a[6]) if len(a) > 6 else 3)
