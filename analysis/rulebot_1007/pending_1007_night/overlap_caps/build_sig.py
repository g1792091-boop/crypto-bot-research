"""Extract the every-signal 5-year outcome rows of the 23 staffed + reserve strategies from the verified
lens2/multi_tf precompute (outc/out_<tf>_<coin>.npz: every signal of every strategy, run ALONE under the house exits,
2021-08-01..2026-09-30, Binance USD-M bars, entry at the 15m open after the signal bar's close, stop/ladder checked
on 15m bars).

    python3 -I -B build_sig.py <outc_dir> <core_sig_dir> <out_npz>

Output: one flat table (all strategies) with columns
  s (strategy index), tf (0=15m 1=30m 2=1h 3=4h), coin (0..5 BTC ETH SOL DOGE LTC BCH), side (+1/-1),
  i (signal bar index on the tf grid), e (entry 15m bar index, same grid for all coins), x (15m bar of exit),
  R (net R per initial stop), gross (gross R), feas (sizable at 30x/20x under the live normal chain),
  sf (initial stop distance as a fraction of the fill), and ts15 (15m bar open times, ns).
"""
import os
import sys

sys.path[:0] = ['/root/.local/lib/python3.11/site-packages']
import numpy as np  # noqa: E402

STRATS = ["N10_HA_PSAR", "F16_FIB382", "F9_FVG", "N18_VWMA_MACD", "S4_BB_BBP", "N25_DST_CCI", "F6_VWAP_CROSS",
          "N23_HA_ST", "F4_FAN", "V39_ALL",
          "F16_FIB500", "F7_RF_TRIPLE", "S2_ST_ROC", "N02_ST_KST", "N07_ICHI_CMO", "DOGE", "N13_3OUTSIDE",
          "N01_ST_EMA", "N04_ST_KLINGER", "N09_ALLIG_AROON", "F9_IFVG", "F12_MSS", "N22_VORTEX_PSAR"]
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
TFS = ("15m", "30m", "1h", "4h")


def key_of(name, files):
    for pre in ("C:", "D:"):
        if "m__" + pre + name in files:
            return "m__" + pre + name
    raise KeyError(name)


def main(outc, core, out):
    cols = {k: [] for k in ("s", "tf", "coin", "side", "i", "e", "x", "R", "gross", "feas", "sf")}
    for ti, tf in enumerate(TFS):
        for ci, c in enumerate(COINS):
            z = np.load(os.path.join(outc, f"out_{tf}_{c}.npz"))
            files = set(z.files)
            base = {k: z[k] for k in ("i", "side", "e", "x", "R", "gross", "feasible", "fill", "risk")}
            for si, s in enumerate(STRATS):
                p = z[key_of(s, files)]
                n = len(p)
                cols["s"].append(np.full(n, si, np.int8)); cols["tf"].append(np.full(n, ti, np.int8))
                cols["coin"].append(np.full(n, ci, np.int8)); cols["side"].append(base["side"][p].astype(np.int8))
                cols["i"].append(base["i"][p].astype(np.int32)); cols["e"].append(base["e"][p].astype(np.int32))
                cols["x"].append(base["x"][p].astype(np.int32)); cols["R"].append(base["R"][p].astype(np.float32))
                cols["gross"].append(base["gross"][p].astype(np.float32))
                cols["feas"].append(base["feasible"][p].astype(bool))
                cols["sf"].append((base["risk"][p] / base["fill"][p]).astype(np.float32))
    arr = {k: np.concatenate(v) for k, v in cols.items()}
    ok = np.isfinite(arr["R"])
    print("rows", len(ok), "non-finite R dropped", int((~ok).sum()))
    arr = {k: v[ok] for k, v in arr.items()}
    ts15 = np.load(os.path.join(core, "sig_15m_BTCUSD.npz"))["ts"]
    np.savez_compressed(out, ts15=ts15, names=np.array(STRATS), **arr)
    for si, s in enumerate(STRATS):
        m = arr["s"] == si
        print(s, [int((arr["tf"][m] == t).sum()) for t in range(4)])


if __name__ == "__main__":
    main(*sys.argv[1:4])
