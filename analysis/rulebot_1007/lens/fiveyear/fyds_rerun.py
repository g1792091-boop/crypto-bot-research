"""5-year DeepSeek-200 entries (research/deepseek200/lib_c.py, read-only import) run through the LIVE house exits:
next-bar open + slippage, 2 x ATR14 stop, paper v3 ladder (profiles._scan), paper v4 'normal' leverage (30x/30% then
20x/20%, $5,000), real costs (taker 0.05% x2, slippage 0.02% x2, funding 0.01%/8h). Per-signal output with timestamps.

    python3 -I -B fyds_rerun.py <bars_dir> <out_dir> [procs]

Live ds200 accounts use these house exits (not the PREREG X5_TRAIL2 / X2_SL15_TP3 exits of results.csv).
Long wins when a bar fires both sides (paperbot/dssig.py). ATR14 = lib.fg.atr(df, 14) as dssig.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
import warnings
from multiprocessing import Pool

sys.path.append('/root/.local/lib/python3.11/site-packages')
REPO = '/home/user/crypto-bot-research'
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'research', 'paper_rules'))
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


P = _load('profiles_ro', os.path.join(REPO, 'research', 'strategy_profiles', 'profiles.py'))
C = _load('lib_c_ro', os.path.join(REPO, 'research', 'deepseek200', 'lib_c.py'))
RB = P.RB
from paperbot.sizing import size_position  # noqa: E402
from paperbot.config import v3_settings  # noqa: E402

K = 2.0
V4S = v3_settings()
START, END, CF0 = "2021-08-01", "2026-09-30", "2024-07-01"


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


def read(bars_dir, coin, tf):
    E = C.env()
    L = E["L"]
    df = L.read_ohlcv(os.path.join(bars_dir, f"{coin.lower()}-{tf}.csv.gz"))
    df = df[df["ts"] < pd.Timestamp(END, tz="UTC")].reset_index(drop=True)
    df.attrs["tf"] = tf
    return df


def job(args):
    bars_dir, tf, coin = args
    E = C.env()
    L, fg = E["L"], E["fg"]
    df = read(bars_dir, coin, tf)
    ctx = None if coin == "BTCUSD" else {"BTCUSD": read(bars_dir, "BTCUSD", tf)}
    sig = C.entries(df, tf, ctx, coin)
    atr = fg.atr(df, 14).to_numpy(float)
    ts = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None).to_numpy().astype("datetime64[ns]").astype(np.int64)
    b = {"ts": ts, "o": df["open"].to_numpy(float), "h": df["high"].to_numpy(float), "l": df["low"].to_numpy(float),
         "c": df["close"].to_numpy(float), "atr": atr}
    n = len(ts)
    lo = max(int(np.searchsorted(ts, pd.Timestamp(START).value)), L.warmup_bars(tf))
    hi = int(np.searchsorted(ts, pd.Timestamp(END).value)) - 1
    f_bar = RB.FUNDING_8H * C.TF_MIN[tf] / 480.0
    slip = RB.SETTINGS.slippage_frac
    sz = sizer_v4n()
    cf0 = pd.Timestamp(CF0).value
    frames = []
    for name, (lg, sh) in sig.items():
        s = np.where(lg, 1, np.where(sh, -1, 0))
        idx = np.nonzero(s[lo:hi])[0] + lo
        a = atr[idx]
        ok = np.isfinite(a) & (a > 0) & np.isfinite(b["o"][np.minimum(idx + 1, n - 1)])
        idx = idx[ok]
        if not len(idx):
            continue
        side = s[idx].astype(int)
        raw = b["o"][idx + 1]
        a = atr[idx]
        fill = raw * (1 + side * slip)
        stop_frac = (raw * slip + K * a) / fill
        ll = np.array([sz(int(x), float(y)) for x, y in zip(side, a / raw)]).reshape(-1, 2)
        lev, liq_frac = ll[:, 0], ll[:, 1]
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
                keep = r["done"] | (H == 4096) | (idx[sel] + H >= n - 1)
                for k in res:
                    res[k][sel[keep]] = r[k][keep]
                nxt.append(sel[~keep])
            todo = np.concatenate(nxt) if nxt else np.zeros(0, int)
        with np.errstate(invalid="ignore", divide="ignore"):
            ret = np.where(lev > 0, res["roe"] / np.where(lev > 0, lev, 1), np.nan)
            gross = side * (res["exit_px"] / (1 - side * slip) / raw - 1)
        frames.append(pd.DataFrame(dict(
            strategy=name, coin=coin, tf=tf, ts=ts[idx], side=side.astype(np.int8),
            win=np.where(ts[idx] < cf0, 0, 1).astype(np.int8), stop_frac=stop_frac.astype(np.float32),
            v4n_lev=lev.astype(np.int16), v4n_done=np.isfinite(res["reason"]) & (res["reason"] < 3),
            v4n_roe=res["roe"].astype(np.float32), v4n_ret=ret.astype(np.float32),
            v4n_R=(ret / stop_frac).astype(np.float32),
            v4n_gross=np.where(res["reason"] == 2, np.nan, gross).astype(np.float32),
            v4n_reason=res["reason"].astype(np.float32), v4n_held=res["held"].astype(np.float32))))
    days = (hi - lo) * C.TF_MIN[tf] / 1440.0
    return tf, coin, (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), days


def main(bars_dir, out_dir, procs=4):
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    meta = []
    for tf in C.TFS:
        with Pool(procs) as pool:
            got = pool.map(job, [(bars_dir, tf, c) for c in C.COINS])
        df = pd.concat([g[2] for g in got], ignore_index=True)
        for c in ("strategy", "coin", "tf"):
            df[c] = df[c].astype("category")
        df.to_pickle(os.path.join(out_dir, f"fyds_{tf}.pkl.gz"))
        meta.append(dict(tf=tf, days=float(np.median([g[3] for g in got])), rows=len(df)))
        print(tf, len(df), f"{time.time() - t0:.0f}s", flush=True)
    pd.DataFrame(meta).to_csv(os.path.join(out_dir, "fyds_meta.csv"), index=False)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 4)
