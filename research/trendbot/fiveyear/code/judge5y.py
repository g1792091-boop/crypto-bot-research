"""The trend judge (paperbot/trendjudge.py vote_arrays / raw_votes, the same indicator functions) and the entry-bar
values (spot: EMA20, ATR14, RSI14, range) on the FULL series of each coin's 1h / 4h and 30m / 1h bars, plus a check
against the live form (judge_frame / spot_frame on the last KEEP = 300 closed bars, as Klines.frame hands them) on a
fixed random sample of bars. Output: out/judge/<COIN>.npz, out/judge_agreement.json
Run: python3 -I judge5y.py [--sample 400]"""
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fycommon import *
import time, warnings
from multiprocessing import Pool
from paperbot import trendjudge as TJ

SAMPLE = int(sys.argv[sys.argv.index("--sample") + 1]) if "--sample" in sys.argv else 400
S0, S1 = ms("2021-01-01"), ms("2026-10-21")


def job(coin):
    fg, pi = TJ.lib()
    rules3 = TJ.TrendRules()
    rules4 = TJ.TrendRules(vote_min=4)
    m = load_grid(coin, with_oct=True)
    out, chk = {}, {}
    rng = np.random.default_rng(abs(hash(coin)) % 2**32 if False else COINS.index(coin) + 7)
    for tf in ("30m", "1h", "4h"):
        b = agg(m, TF_MS[tf])
        df = df_of(b)
        df["ts"] = df["ts"].dt.tz_localize(None)
        close_t = b["ts"] + TF_MS[tf]
        out[f"{tf}_tclose"] = close_t
        if tf in ("1h", "4h"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                arr = TJ.vote_arrays(df, fg, pi)
            for k in TJ.JUDGES:
                out[f"{tf}_{k}"] = arr[k].astype(np.int8)
            out[f"{tf}_raw3"] = TJ.raw_votes(arr, 3)
            out[f"{tf}_raw4"] = TJ.raw_votes(arr, 4)
            for k in ("adx", "ema20", "atr", "close"):
                out[f"{tf}_{k}"] = arr[k]
        if tf in ("30m", "1h"):
            close = df["close"]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                out[f"{tf}_s_ema20"] = TJ._f(fg.ema(close, 20))
                out[f"{tf}_s_atr"] = TJ._f(fg.atr(df, 14))
                out[f"{tf}_s_rsi"] = TJ._f(fg.rsi(close, 14))
            out[f"{tf}_s_range"] = b["h"] - b["l"]
            out[f"{tf}_s_close"] = b["c"]
        # live form on a sample: the last 300 closed bars at the bar's close
        idx = np.flatnonzero((close_t >= S0) & (close_t < S1))
        pick = np.sort(rng.choice(idx, size=min(SAMPLE, len(idx)), replace=False))
        n_ok = {"judge_dir3": 0, "judge_raw3": 0, "judge_votes": 0, "judge_raw4": 0, "adx_rel_1e-6": 0,
                "spot_ema_rel_1e-6": 0, "spot_atr_rel_1e-6": 0, "spot_rsi_abs_1e-6": 0, "n": 0}
        worst = {"adx": 0.0, "ema": 0.0, "atr": 0.0, "rsi": 0.0}
        for k in pick:
            win = df.iloc[max(0, k - TJ.KEEP + 1): k + 1].reset_index(drop=True)
            n_ok["n"] += 1
            if tf in ("1h", "4h"):
                j3 = TJ.judge_frame(win, coin, tf, rules3, fg, pi)
                j4 = TJ.judge_frame(win, coin, tf, rules4, fg, pi)
                hold = rules3.hold(tf)
                r3 = out[f"{tf}_raw3"]
                d3 = int(r3[k]) if (r3[k] != 0 and all(r3[k - h] == r3[k] for h in range(hold))) else 0
                n_ok["judge_raw3"] += int(j3.raw == int(r3[k]))
                n_ok["judge_dir3"] += int(j3.dir == d3)
                n_ok["judge_raw4"] += int(j4.raw == int(out[f"{tf}_raw4"][k]))
                n_ok["judge_votes"] += int(all(j3.votes[v] == int(out[f"{tf}_{v}"][k]) for v in TJ.JUDGES))
                rel = abs(j3.adx - out[f"{tf}_adx"][k]) / max(1e-12, abs(j3.adx))
                worst["adx"] = max(worst["adx"], rel)
                n_ok["adx_rel_1e-6"] += int(rel < 1e-6)
            if tf in ("30m", "1h"):
                s = TJ.spot_frame(win, tf, fg)
                e = abs(s.ema20 - out[f"{tf}_s_ema20"][k]) / abs(s.ema20)
                a = abs(s.atr - out[f"{tf}_s_atr"][k]) / abs(s.atr)
                r = abs(s.rsi - out[f"{tf}_s_rsi"][k])
                worst["ema"], worst["atr"], worst["rsi"] = max(worst["ema"], e), max(worst["atr"], a), max(worst["rsi"], r)
                n_ok["spot_ema_rel_1e-6"] += int(e < 1e-6)
                n_ok["spot_atr_rel_1e-6"] += int(a < 1e-6)
                n_ok["spot_rsi_abs_1e-6"] += int(r < 1e-6)
        chk[tf] = {"counts": n_ok, "worst": worst}
    np.savez(f"{OUT}/judge/{coin}.npz", **out)
    return coin, chk


if __name__ == "__main__":
    os.makedirs(f"{OUT}/judge", exist_ok=True)
    t0 = time.time()
    res = {}
    with Pool(2) as pool:
        for coin, chk in pool.imap_unordered(job, COINS):
            res[coin] = chk
            print(coin, json.dumps(chk), f"{time.time() - t0:.0f}s", flush=True)
    json.dump(res, open(f"{OUT}/judge_agreement.json", "w"), indent=1)
