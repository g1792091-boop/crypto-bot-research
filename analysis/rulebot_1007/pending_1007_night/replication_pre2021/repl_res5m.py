"""Exit-resolution sensitivity: the same signals, same entry (next signal-tf bar open = first 5m bar of it), same
2 x ATR14 (signal-tf) stop, same sizing, but the stop / ROE ladder is stepped on 5m bars instead of the signal-tf bars
(funding per 5m bar). Compared row by row with the signal-tf result.

    python3 -I -B repl_res5m.py <mode y5|pre> <kind core|ds> <tf> <strategies,comma> <rows_dir> <binance_bars_dir> <out_csv>
rows_dir: y5 -> lens/fiveyear/out (fy36_/fyds_<tf>.pkl.gz); pre -> repl/out (pre_core_/pre_ds_<tf>.pkl.gz)
"""
import os
import sys

sys.path.append('/root/.local/lib/python3.11/site-packages')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa
import pandas as pd  # noqa
import repl_sim as S  # noqa
import repl_sig as G  # noqa

mode, kind, tf, strats, rows_dir, bars_dir, out = sys.argv[1:8]
strats = strats.split(",")
L = S.sweepsig.lib()
fg = G.C.env()["fg"]
RB = S.RB
SLIP = RB.SETTINGS.slippage_frac
TFM = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}[tf]
HS = {"15m": (192, 1536, 12288), "30m": (384, 3072, 24576), "1h": (768, 6144, 49152), "4h": (384, 3072, 24576, 98304)}[tf]
F5 = RB.FUNDING_8H * 5 / 480.0
WK = 7 * 86400 * 10 ** 9


def bars(coin, t):
    if mode == "pre":
        return G.FS.load_bars(L, t, coin, G.PRE)
    df = L.read_ohlcv(os.path.join(bars_dir, f"{coin.lower()}-{t}.csv.gz"))
    df = df[df["ts"] < pd.Timestamp("2026-09-30", tz="UTC")].reset_index(drop=True)
    df.attrs["tf"] = t
    return df


pre = {"y5": {"core": "fy36", "ds": "fyds"}, "pre": {"core": "pre_core", "ds": "pre_ds"}}[mode][kind]
T = pd.read_pickle(os.path.join(rows_dir, f"{pre}_{tf}.pkl.gz"))
T = T[T.strategy.isin(strats) & (T.v4n_lev > 0) & T.v4n_done]
if mode == "y5":
    T = T[(T.ts >= pd.Timestamp("2021-08-01").value) & (T.ts < pd.Timestamp("2026-09-30").value)]
T = T[["strategy", "coin", "ts", "side", "stop_frac", "v4n_lev", "v4n_R", "v4n_gross", "v4n_reason"]].copy()
T["strategy"] = T.strategy.astype(str)
T["coin"] = T.coin.astype(str)
sz = S.sizer_v4n()
parts = []
for coin, g in T.groupby("coin"):
    d = bars(coin, tf)
    ts = G.FS.RB._ns(d["ts"])
    o = d["open"].to_numpy(float)
    atr = fg.atr(d, 14).to_numpy(float)
    d5 = bars(coin, "5m")
    ts5 = G.FS.RB._ns(d5["ts"])
    b5 = {"ts": ts5, "o": d5["open"].to_numpy(float), "h": d5["high"].to_numpy(float), "l": d5["low"].to_numpy(float),
          "c": d5["close"].to_numpy(float), "atr": np.full(len(ts5), np.nan)}
    i = np.searchsorted(ts, g.ts.to_numpy())
    okA = (i + 1 < len(ts)) & (ts[np.minimum(i, len(ts) - 1)] == g.ts.to_numpy())
    te = ts[np.minimum(i + 1, len(ts) - 1)]
    j = np.searchsorted(ts5, te)
    okB = okA & (j < len(ts5)) & (j >= 1) & (ts5[np.minimum(j, len(ts5) - 1)] == te)
    g = g[okB].copy()
    i, j = i[okB], j[okB]
    side = g.side.to_numpy(int)
    raw = o[i + 1]
    sf = (raw * SLIP + 2.0 * atr[i]) / (raw * (1 + side * SLIP))
    g["sf_chk"] = np.abs(sf / g.stop_frac.to_numpy(float) - 1)
    g["open_chk"] = np.abs(b5["o"][j] / raw - 1)
    idx5 = j - 1
    b5["atr"][idx5] = atr[i]
    ll = np.array([sz(int(s), float(x)) for s, x in zip(side, atr[i] / raw)]).reshape(-1, 2)
    lev, liq = ll[:, 0], ll[:, 1]
    r = S.run_mode(b5, idx5, side, lev, liq, len(ts5), F5, HS)
    with np.errstate(invalid="ignore", divide="ignore"):
        ret = np.where(lev > 0, r["roe"] / np.where(lev > 0, lev, 1), np.nan)
        gross = side * (r["exit_px"] / (1 - side * SLIP) / raw - 1)
    g["lev5"] = lev
    g["done5"] = np.isfinite(r["reason"]) & (r["reason"] < 3)
    g["R5"] = ret / sf
    g["G5"] = np.where(r["reason"] == 2, np.nan, gross) / sf
    g["reason5"] = r["reason"]
    g["Gtf"] = g.v4n_gross.to_numpy(float) / g.stop_frac.to_numpy(float)
    parts.append(g)
    print(mode, kind, tf, coin, len(g), "sf_chk max", float(g.sf_chk.max()), "open_chk max", float(g.open_chk.max()), flush=True)
D = pd.concat(parts, ignore_index=True)
D.to_csv(out, index=False)


def ct(x, cl):
    x = np.asarray(x, float)
    ok = np.isfinite(x)
    x, cl = x[ok], np.asarray(cl)[ok]
    mu = x.mean()
    s = pd.Series(x - mu).groupby(cl).sum().to_numpy()
    se = np.sqrt((s ** 2).sum() * len(s) / max(len(s) - 1, 1)) / len(x)
    return mu, mu / se, len(x)


for st, g in D.groupby("strategy"):
    g = g[g.done5 & (g.lev5 > 0)]
    cl = g.ts.to_numpy() // WK
    a = ct(g.Gtf, cl); b = ct(g.G5, cl); c = ct(g.v4n_R, cl); e = ct(g.R5, cl)
    dg = ct(g.G5 - g.Gtf, cl); dn = ct(g.R5 - g.v4n_R, cl)
    print(f"SUMMARY {mode} {st}@{tf} n {a[2]} | gross tf-bars {a[0]:+.4f} t {a[1]:.2f} -> 5m {b[0]:+.4f} t {b[1]:.2f} "
          f"(diff {dg[0]:+.4f} t {dg[1]:.2f}) | net tf-bars {c[0]:+.4f} t {c[1]:.2f} -> 5m {e[0]:+.4f} t {e[1]:.2f} "
          f"(diff {dn[0]:+.4f} t {dn[1]:.2f}) | lock share tf {(g.v4n_reason == 1).mean():.3f} 5m {(g.reason5 == 1).mean():.3f} "
          f"| win tf {(g.v4n_R > 0).mean():.3f} 5m {(g.R5 > 0).mean():.3f}", flush=True)
