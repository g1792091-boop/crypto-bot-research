"""The trend judge arrays of the four current judges (V39 / S6 / OBV / N12 at 1h and 4h, trendjudge.vote_arrays) and the
entry-bar values (EMA20, ATR14, RSI14, range at 30m and 1h) on the full series up to the extended data end: the
five-year study's own judge5y.job (unchanged), given this study's 1m grid (nlcommon.load_grid: fg1m + the October daily
klines) and writing to scratchpad newlive/judge/<COIN>.npz; --sample N repeats its live-form check (the last 300 bars
through trendjudge.judge_frame / spot_frame) on N random bars per timeframe and coin (judge/judge_agreement.json).
Run: python3 -I judge_all.py [--sample 20]"""
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nlcommon import *
import nlcommon
import time
from multiprocessing import Pool

if "--sample" not in sys.argv:
    sys.argv += ["--sample", "20"]
import judge5y                                    # parses --sample at import

judge5y.OUT = NL                                  # job() writes f"{OUT}/judge/{coin}.npz" = JUDGE/<coin>.npz
judge5y.S1 = DATA_END                             # the live-form sample: bar closes 2021-01-01 .. the data end
judge5y.load_grid = lambda coin, with_oct=True: nlcommon.load_grid(coin)

if __name__ == "__main__":
    os.makedirs(JUDGE, exist_ok=True)
    t0 = time.time()
    res = {}
    with Pool(3) as pool:
        for coin, chk in pool.imap_unordered(judge5y.job, COINS):
            res[coin] = chk
            print(coin, json.dumps(chk), f"{time.time() - t0:.0f}s", flush=True)
    json.dump({"data": data_manifest(), "data_end": DATA_END, "sample": judge5y.SAMPLE, "check": res},
              open(f"{JUDGE}/judge_agreement.json", "w"), indent=1)
