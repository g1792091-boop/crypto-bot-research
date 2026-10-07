"""Highest leverage the live sizing allows for a 2 ATR stop (stop must sit >= max(1 ATR, 0.2%) inside the liquidation
price; paperbot.sizing.size_position with v3_settings() quality_v1, group "best" falling to "normal": 50x, 40x, 30x,
20x; $5,000 equity; brackets inferred from the live trades). Per timeframe x coin: share of signals whose 2 ATR stop
fits at >= 50x, >= 40x, >= 30x, >= 20x, and none. 5-year signals (fy_signals.pkl, 2021-08..2026-09 and the last
12 months alone) and the live SUBMITTED signals of our 36 (signal_log atr / ref_price, all three runs).

    python3 -I lev_feas.py <fy_signals.pkl> <export_dir> <rb_analyze_dir> <repo> <out_csv>
"""
import site
import sys

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

FY, E, AZD, REPO, OUT = sys.argv[1:6]
sys.path.insert(0, REPO)
sys.path.insert(0, AZD)
import analyze as AZ  # noqa: E402
from paperbot.config import v3_settings  # noqa: E402
from paperbot.sizing import size_position  # noqa: E402

S = v3_settings()
BRK, _ = AZ.make_brackets(None)
CACHE = {}


def maxlev(sym, side, atr_frac):
    key = (sym, side, float(f"{atr_frac:.3g}"))
    if key not in CACHE:
        raw = 100.0
        a = key[2] * raw
        fill = raw * (1 + side * S.slippage_frac)
        d = size_position(S, 5000.0, side, fill, raw - side * 2.0 * a, "best", BRK[sym], atr=a, min_notional=5.0)
        CACHE[key] = d.leverage if d.ok else 0
    return CACHE[key]


def summarize(df, src):
    rows = []
    for (tf, sym), g in df.groupby(["tf", "sym"]):
        lv = g["maxlev"].to_numpy()
        rows.append({"source": src, "tf": tf, "coin": sym, "n": len(g),
                     "median_stop_pct": float(np.median(2 * g["atr_frac"]) * 100),
                     "share_50x": (lv >= 50).mean(), "share_40x_plus": (lv >= 40).mean(),
                     "share_30x_plus": (lv >= 30).mean(), "share_20x_plus": (lv >= 20).mean(),
                     "share_none": (lv == 0).mean()})
    for tf, g in df.groupby("tf"):
        lv = g["maxlev"].to_numpy()
        rows.append({"source": src, "tf": tf, "coin": "ALL", "n": len(g),
                     "median_stop_pct": float(np.median(2 * g["atr_frac"]) * 100),
                     "share_50x": (lv >= 50).mean(), "share_40x_plus": (lv >= 40).mean(),
                     "share_30x_plus": (lv >= 30).mean(), "share_20x_plus": (lv >= 20).mean(),
                     "share_none": (lv == 0).mean()})
    return rows


def main():
    D = pd.read_pickle(FY)
    D = D[["tf", "coin", "side", "atr_frac", "close_ms"]].copy()
    D["tf"], D["sym"] = D["tf"].astype(str), D["coin"].astype(str) + "T"
    D["maxlev"] = [maxlev(s, int(sd), float(a)) for s, sd, a in zip(D["sym"], D["side"], D["atr_frac"])]
    rows = summarize(D, "5y_2021-08..2026-09")
    last = D[D["close_ms"] >= pd.Timestamp("2025-10-01").value // 1_000_000]
    rows += summarize(last, "5y_last12m")
    acc = pd.read_csv(f"{E}/current/accounts.csv")
    ours = set(acc.loc[acc["kind"] == "strategy", "strategy"])
    lv = []
    for run in ("run-20261005T014624Z", "run-20261005T183457Z", "current"):
        sl = pd.read_csv(f"{E}/{run}/signal_log.csv")
        sl = sl[sl["strategy"].isin(ours) & (sl["status"] == "SUBMITTED") & sl["timeframe"].isin(["15m", "30m", "1h", "4h"])]
        lv.append(pd.DataFrame({"tf": sl["timeframe"], "sym": sl["symbol"], "side": sl["side"],
                                "atr_frac": sl["atr"] / sl["ref_price"]}))
    L = pd.concat(lv, ignore_index=True).dropna()
    L["maxlev"] = [maxlev(s, int(sd), float(a)) for s, sd, a in zip(L["sym"], L["side"], L["atr_frac"])]
    rows += summarize(L, "live_v3a_v3b_v4")
    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False)
    pd.set_option("display.width", 200)
    print(out[out["coin"] == "ALL"].round(3).to_string())
    print(out[(out["tf"] == "4h") | (out["tf"] == "1h")].round(3).to_string())


if __name__ == "__main__":
    main()
