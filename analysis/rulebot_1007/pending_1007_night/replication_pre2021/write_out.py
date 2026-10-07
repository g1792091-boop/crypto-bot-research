"""Collect every number for replication.json (all from files written by the scripts in this folder).
    python3 -I -B write_out.py <repl_dir> <scratchpad> <repo>
"""
import json
import os
import re
import sys
from math import erf, sqrt

sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np  # noqa
import pandas as pd  # noqa

RD, SP, REPO = sys.argv[1:4]
O = os.path.join(RD, "out")
Phi = lambda x: 0.5 * (1 + erf(x / sqrt(2)))  # noqa


def bh(p):
    p = np.asarray(p, float)
    m = len(p)
    o = np.argsort(p)
    q = np.minimum.accumulate((p[o] * m / np.arange(1, m + 1))[::-1])[::-1]
    r = np.empty(m)
    r[o] = np.minimum(q, 1)
    return r


def r4(x):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else (round(float(x), 4) if isinstance(x, (float, np.floating)) else x)


# ---------------- coverage
cov = {}
for f in ("MANIFEST.json", "MANIFEST_5m.json"):
    m = json.load(open(os.path.join(REPO, "data", "pre2021", f)))
    for k, v in m["files"].items():
        cov[k] = dict(symbol=v["symbol"], interval=v["interval"], first=v["first_ts"], last=v["last_ts"], rows=v["rows"],
                      missing=v["missing_bars_in_range"])
of = json.load(open(os.path.join(REPO, "data", "orderflow", "MANIFEST.json")))
fund = {s: dict(first=d["funding"]["first"], last=d["funding"]["last"], rows=d["funding"]["rows"]) for s, d in of["symbols"].items()}
btc = json.load(open(os.path.join(REPO, "data", "btc_pre2021", "MANIFEST.json")))
coverage = dict(
    pre2021=dict(path="data/pre2021", source="data.binance.vision futures/um monthly klines (last price, OHLCV)", files=cov,
                 note="7 symbols x 5m/15m/1h/4h, 2020-01 (SOL 2020-09-14, DOGE 2020-07-10, LTC 2020-01-09, XRP 2020-01-06) .. 2021-08-31, 0 missing bars; no 30m (built from 5m), no 1m, no mark-price klines; XRP is not in the 6-coin research universe"),
    btc_pre2021=dict(path="data/btc_pre2021", interval="1h", symbol="BTCUSDT", first=btc["first_ts"], last=btc["last_ts"], rows=btc["rows"],
                     note="duplicate of the BTC 1h series in data/pre2021 (used by research/btc_pre2021, maker long/short-ratio test)"),
    funding=dict(path="data/orderflow/*_funding.csv.gz", symbols=fund,
                 note="real 8h funding from 2020-01 (or listing) to 2026-08 for BTC ETH SOL LTC BCH DOGE XRP; premium index 1h same months; OI/long-short metrics 5m: BTC from 2020-09-01, others from 2021-12-01"),
    universe=dict(path="data/universe/klines_1d.csv.gz", note="1d klines of 864 USDT perps incl. delisted, 2020-01..2026-08 (daily only: no intraday signal test possible)"),
    bookdepth=dict(path="data/bookdepth", note="5m order-book depth bands, from 2023-01-01 only"),
    binance_5y=dict(path="scratchpad/binance/bars + signals", note="the 5y verified data: Binance USDT-M 5m/15m/30m/1h/4h/1d, 6 coins, 2021-01-01..2026-09-29; funding files from 2021-01 (scratchpad/binance/funding)"),
    spot_5y=dict(path="scratchpad/paper_rules/signals", note="original research data (Astral/Polygon multi-exchange USD spot), core-36 signal cache 2021-05-30..2026-09-29, 5m..1d, no volume column; same period as the 5y test, so a data-vendor check, not an independent period"),
    not_found=["mark-price klines (none in data/ or research/)", "1m history (only live_bars.csv in the paper exports, a few days)", "any futures bars before 2020-01 (archive 404 for 2019-09..12)", "DeepSeek signals on spot data (spot cache has no volume; not built)"],
)

# ---------------- regime
reg = {}
for lab, d, a, b in (("pre", os.path.join(RD, "sig_pre", "core"), "2020-01-01", "2021-08-01"),
                     ("y5", os.path.join(SP, "binance", "signals"), "2021-08-01", "2026-09-30")):
    rets, atrp = {}, {}
    for c in ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD"):
        z = np.load(os.path.join(d, f"sig_4h_{c}.npz"))
        ts, cl = z["ts"], z["c"]
        i0 = max(int(np.searchsorted(ts, pd.Timestamp(a).value)), 300)
        i1 = int(np.searchsorted(ts, pd.Timestamp(b).value)) - 1
        rets[c] = float(cl[i1] / cl[i0] - 1)
        z15 = np.load(os.path.join(d, f"sig_15m_{c}.npz"))
        t15 = z15["ts"]
        j0, j1 = int(np.searchsorted(t15, pd.Timestamp(a).value)), int(np.searchsorted(t15, pd.Timestamp(b).value))
        atrp[c] = float(np.nanmedian(z15["atr"][j0:j1] / z15["c"][j0:j1]))
    reg[lab] = dict(window=[a, b], buy_hold_return_from_first_signal_bar=rets, median_atr14_pct_15m=atrp)

# ---------------- cells
X = pd.read_csv(os.path.join(O, "pre_cells.csv"))
P = pd.read_csv(os.path.join(O, "primary.csv"))
B = pd.read_csv(os.path.join(O, "bh22.csv"))
Y = pd.read_csv(os.path.join(O, "y5_flip_cells.csv"))
SPOT = pd.read_csv(os.path.join(O, "spot_cells.csv"))
G = json.load(open(os.path.join(O, "global.json")))


def enrich(D):
    D = D.merge(Y[["strategy", "tf", "y5_g_flip", "y5_dir", "y5_dir_t"]], on=["strategy", "tf"], how="left")
    D = D.merge(SPOT, on=["strategy", "tf"], how="left")
    se5 = np.abs(D.y5_grossR / D.y5_gross_t)
    D["diff_z"] = (D.grossR - D.y5_grossR) / np.sqrt(D.gross_se ** 2 + se5 ** 2)
    sed, sed5 = np.abs(D.dir_content / D.dir_t), np.abs(D.y5_dir / D.y5_dir_t)
    D["dir_diff_z"] = (D.dir_content - D.y5_dir) / np.sqrt(sed ** 2 + sed5 ** 2)
    D["exp_t_dir"] = D.y5_dir / sed
    s5 = np.sign(D.y5_grossR)
    D["p_one_dir"] = [1 - Phi(s * t) if np.isfinite(t) else 1.0 for s, t in zip(s5, D.dir_t)]
    D["q_one_dir"] = bh(D.p_one_dir.to_numpy())
    D["dir_sign_agree"] = np.sign(D.dir_content) == s5

    def vd(r):
        if not np.isfinite(r.dir_t):
            return "no data"
        if r.dir_sign_agree and abs(r.dir_t) >= 1.5:
            return "replicates (BH)" if r.q_one_dir <= 0.05 else "replicates (nominal only)"
        if (not r.dir_sign_agree) and abs(r.dir_t) >= 1.5:
            return "contradicted"
        return "inconclusive (same sign)" if r.dir_sign_agree else "inconclusive (sign flipped)"
    D["verdict_dir"] = [vd(r) for r in D.itertuples()]
    return D


P = enrich(P)
B = enrich(B)
P.to_csv(os.path.join(O, "primary_final.csv"), index=False)
B.to_csv(os.path.join(O, "bh22_final.csv"), index=False)

# global extras: shrinkage slope pre ~ 5y over cells with n>=200 in both
s = X[(X.n >= 200) & (X.y5_n >= 200) & X.gross_t.notna() & X.y5_gross_t.notna()]
slope = float(np.polyfit(s.y5_grossR, s.grossR, 1)[0])
pertf = {tf: dict(cells=len(g), spearman_t=float(g.y5_gross_t.rank().corr(g.gross_t.rank())),
                  spearman_vs_pre_dir_t=float(g.y5_gross_t.rank().corr(g.dir_t.rank())), sign_agree=float(g.sign_agree.mean()))
         for tf, g in s.groupby("tf")}
G["slope_pre_on_5y_gross"] = slope
G["per_tf"] = pertf
G["all_spearman_5y_gross_t_vs_pre_dir_t"] = float(s.y5_gross_t.rank().corr(s.dir_t.rank()))
G["note"] = "cells share strategies across timeframes and DS definitions overlap, so the permutation p treats dependent cells as exchangeable and is optimistic"

# resolution
res = {}
for f in sorted(os.listdir(O)):
    if f.startswith("res5m_") and f.endswith(".log"):
        for line in open(os.path.join(O, f)):
            if line.startswith("SUMMARY"):
                m = re.match(r"SUMMARY (\S+) (\S+) n (\d+) \| gross tf-bars ([-+.\d]+) t ([-.\d]+) -> 5m ([-+.\d]+) t ([-.\d]+) \(diff ([-+.\d]+) t ([-.\d]+)\) \| net tf-bars ([-+.\d]+) t ([-.\d]+) -> 5m ([-+.\d]+) t ([-.\d]+) \(diff ([-+.\d]+) t ([-.\d]+)\)", line)
                k = ["period", "cell", "n", "gross_tfbars", "gross_tfbars_t", "gross_5m", "gross_5m_t", "gross_diff", "gross_diff_t",
                     "net_tfbars", "net_tfbars_t", "net_5m", "net_5m_t", "net_diff", "net_diff_t"]
                v = m.groups()
                res[f"{v[0]}:{v[1]}"] = {kk: (vv if i < 2 else (int(vv) if i == 2 else float(vv))) for i, (kk, vv) in enumerate(zip(k, v))}
fix = [line.strip() for line in open(os.path.join(O, "fix20.log"))]
par = dict(core_4h=[line.strip() for line in open(os.path.join(O, "parity_5y_core4h.log"))],
           ds_4h=[line.strip() for line in open(os.path.join(O, "parity_5y_ds4h.log"))])

cols = ["kind", "strategy", "tf", "n_all", "n", "per_day_sized", "sized_share", "long_share", "grossR", "gross_t", "netR", "net_t",
        "costR", "netR_realfund", "g_long", "g_short", "g_flip", "dir_content", "dir_t", "g_2020", "g_2021", "n_2020", "n_2021",
        "y5_n", "y5_grossR", "y5_gross_t", "y5_netR", "y5_g_is", "y5_g_cf", "y5_long_share", "y5_g_flip", "y5_dir", "y5_dir_t",
        "spot_n", "spot_gross", "spot_gross_t", "exp_t", "pow15", "diff_z", "sign_agree", "p_one", "q_one", "verdict",
        "exp_t_dir", "dir_diff_z", "dir_sign_agree", "q_one_dir", "verdict_dir"]
# exploratory appendix: other AI-list strategies at their listed entry timeframes (not in the pre-specified family)
APP = [("N07_ICHI_CMO", "30m"), ("N07_ICHI_CMO", "15m"), ("N13_3OUTSIDE", "1h"), ("F7_RF_TRIPLE", "30m"), ("F7_RF_TRIPLE", "1h"),
       ("DOGE", "15m"), ("DOGE", "30m"), ("DOGE", "1h"), ("F15_ASIA_BRK", "30m"), ("F15_ASIA_BRK", "1h"), ("N12_ICHI_AO", "15m"),
       ("N12_ICHI_AO", "30m"), ("S2_ST_ROC", "15m"), ("N01_ST_EMA", "15m"), ("N09_ALLIG_AROON", "15m"), ("N09_ALLIG_AROON", "1h"),
       ("N24_DMI", "1h"), ("N04_ST_KLINGER", "15m"), ("N23_HA_ST", "15m"), ("N23_HA_ST", "30m"), ("N23_HA_ST", "1h"),
       ("F9_FVG", "30m"), ("F4_FAN", "30m"), ("F6_VWAP_CROSS", "30m"), ("F6_VWAP_CROSS", "1h"), ("V39_ALL", "30m"),
       ("N18_VWMA_MACD", "30m"), ("N10_HA_PSAR", "15m"), ("N10_HA_PSAR", "1h"), ("N20_EMA9_CHOP", "15m"), ("N20_EMA9_CHOP", "30m")]
A = pd.DataFrame(APP, columns=["strategy", "tf"]).merge(X, on=["strategy", "tf"], how="left")
A["sign_agree"] = np.sign(A.grossR) == np.sign(A.y5_grossR)
A["dir_sign_agree"] = np.sign(A.dir_content) == np.sign(A.y5_grossR)
A.to_csv(os.path.join(O, "appendix_ai_list.csv"), index=False)


def recs(D):
    return [{c: r4(r[c]) if c in r else None for c in cols} for r in D.to_dict("records")]


meta = pd.read_csv(os.path.join(O, "pre_meta.csv")).to_dict("records")
out = dict(
    title="Replication of the 5-year (2021-08..2026-09) cell results on 2020-01..2021-07 Binance futures data",
    written="2026-10-07", prespec="repl/PRESPEC.json (written before any pre-2021 result was computed)",
    method=json.load(open(os.path.join(RD, "PRESPEC.json"))),
    parity=par, coverage=coverage, regime=reg, pre_meta=meta,
    primary_cells=recs(P), bh22_cells=recs(B), global_rank_agreement=G,
    appendix_other_ai_list_cells_exploratory=[{c: r4(r.get(c)) for c in ["strategy", "tf", "n", "grossR", "gross_t", "netR", "dir_content", "dir_t",
                                                                      "y5_grossR", "y5_gross_t", "sign_agree", "dir_sign_agree"]}
                                              for r in A.to_dict("records")],
    resolution_5m_exits=res, fixed20x_all_signals=fix,
    verdict_counts=dict(primary_gross=P.verdict.value_counts().to_dict(), primary_dir=P.verdict_dir.value_counts().to_dict(),
                        bh22_gross=B.verdict.value_counts().to_dict(), bh22_dir=B.verdict_dir.value_counts().to_dict()),
    files=dict(scripts=["repl_sig.py", "repl_sim.py", "repl_agg.py", "y5flip_agg.py", "repl_res5m.py", "fixlev.py", "parity_5y.py",
                        "parity_ds.py", "ds5y_sig.py", "write_out.py"],
               tables=["out/pre_cells.csv", "out/primary_final.csv", "out/bh22_final.csv", "out/y5_flip_cells.csv", "out/spot_cells.csv",
                       "out/global.json", "out/res5m_*.log", "out/fix20.log"]),
)
json.dump(out, open(os.path.join(RD, "replication.json"), "w"), indent=1, ensure_ascii=False)
pd.set_option("display.width", 300)
print(json.dumps(reg, indent=1))
print(json.dumps(G, indent=1)[:3000])
show = ["strategy", "tf", "n", "grossR", "gross_t", "netR", "dir_content", "dir_t", "y5_grossR", "y5_gross_t", "y5_dir", "exp_t", "pow15",
        "diff_z", "q_one", "verdict", "q_one_dir", "verdict_dir", "spot_gross", "spot_gross_t"]
print(P[show].round(4).to_string())
print(B[show].round(4).to_string())
print(out["verdict_counts"])
