"""Pre-2021 signal caches (2020-01 .. 2021-08 Binance USDT-M futures bars in data/pre2021), read-only reuse of
research/entry_study/final_signals.py (load_bars, signal_arrays: locked sweep_lib, DOGE = doge_join) for the core 36
and research/deepseek200/lib_c.py (entries, BTC context) for the DeepSeek 44. Nothing is written into the repo.

    python3 -I -B repl_sig.py <out_dir> [procs]
writes <out_dir>/core/sig_<tf>_<COIN>.npz and <out_dir>/ds/sig_<tf>_<COIN>.npz (ts, o, h, l, c, atr, s__<name> int8)
"""
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
import numpy as np  # noqa


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


FS = _load('final_signals_ro', os.path.join(REPO, 'research', 'entry_study', 'final_signals.py'))
C = _load('lib_c_ro', os.path.join(REPO, 'research', 'deepseek200', 'lib_c.py'))
from paperbot import sweepsig  # noqa

COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
CORE_TFS = ("5m", "15m", "30m", "1h", "4h")
DS_TFS = ("15m", "30m", "1h", "4h")
PRE = os.path.join(REPO, 'data', 'pre2021')


def job(args):
    kind, tf, coin, out = args
    t0 = time.time()
    L = sweepsig.lib()
    df = FS.load_bars(L, tf, coin, PRE)
    if kind == "core":
        arrs = FS.signal_arrays(L, df, tf, coin)
        arrs.pop("v", None)
    else:
        ctx = None if coin == "BTCUSD" else {"BTCUSD": FS.load_bars(L, tf, "BTCUSD", PRE)}
        sig = C.entries(df, tf, ctx, coin)
        fg = C.env()["fg"]
        arrs = dict(ts=FS.RB._ns(df["ts"]), o=df["open"].to_numpy(float), h=df["high"].to_numpy(float),
                    l=df["low"].to_numpy(float), c=df["close"].to_numpy(float), atr=fg.atr(df, 14).to_numpy(float))
        for name, (lg, sh) in sig.items():
            arrs["s__" + name] = np.where(lg, 1, np.where(sh, -1, 0)).astype(np.int8)
    np.savez_compressed(os.path.join(out, kind, f"sig_{tf}_{coin}.npz"), **arrs)
    return kind, tf, coin, len(df), str(df["ts"].iloc[0]), str(df["ts"].iloc[-1]), round(time.time() - t0, 1)


def main(out, procs=3):
    for k in ("core", "ds"):
        os.makedirs(os.path.join(out, k), exist_ok=True)
    sweepsig.verify()
    jobs = [("core", tf, c, out) for tf in CORE_TFS for c in COINS] + [("ds", tf, c, out) for tf in DS_TFS for c in COINS]
    jobs = [j for j in jobs if not os.path.exists(os.path.join(out, j[0], f"sig_{j[1]}_{j[2]}.npz"))]
    with Pool(procs) as p:
        for r in p.imap_unordered(job, jobs):
            print(*r, flush=True)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 3)
