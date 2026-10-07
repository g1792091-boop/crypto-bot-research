"""Verifier: which leverage the live sizing allows for a 2 ATR stop, and WHICH rule binds.

    python3 -I vlev.py <v_tf_all.pkl> <export_dir> <out_real_dir> <repo> <out_dir>

For each signal (5-year sim signals, every one incl. rejected; and live SUBMITTED signals of our 36):
  maxlev_house  = size_position(v3_settings(), 5000, ..., "best") -> the leverage the live rule gives (50/40/30/20/0)
  maxlev_liq    = same with max_loss_frac = 1e9 (only the liquidation-buffer rule and the bracket)
  maxlev_loss   = same with liq buffer 0 (only the 15%-of-equity max-loss rule, margin = leverage %)
Also the replay 4h statuses by coin and the account-level sizing rejections.
"""
import site
import sys

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

FY, E, O, REPO, OUTD = sys.argv[1:6]
sys.path.insert(0, REPO)
from paperbot.config import v3_settings  # noqa: E402
from paperbot.margin import BracketTier, Brackets  # noqa: E402
from paperbot.sizing import size_position  # noqa: E402

INFERRED_BRACKETS = {
    "BTCUSDT": [(1e12, 50, 0.004, 0.0)],
    "ETHUSDT": [(1e12, 50, 0.004, 0.0)],
    "SOLUSDT": [(50_000, 50, 0.005, 0.0), (1e12, 50, 0.0065, 75.0)],
    "DOGEUSDT": [(80_000, 50, 0.0065, 0.0), (1e12, 50, 0.01, 280.0)],
    "BCHUSDT": [(10_000, 50, 0.005, 0.0), (100_000, 50, 0.01, 50.0), (1e12, 40, 0.0125, 300.0)],
    "LTCUSDT": [(10_000, 50, 0.005, 0.0), (50_000, 50, 0.01, 50.0), (1e12, 40, 0.015, 300.0)],
}
BRK = {s: Brackets([BracketTier(*t) for t in tiers]) for s, tiers in INFERRED_BRACKETS.items()}
SET = {"house": v3_settings(), "liq_only": v3_settings(max_loss_frac=1e9),
       "loss_only": v3_settings(liq_buffer_atr_mult=0.0, liq_buffer_min_frac=0.0)}
CACHE = {}


def ml(mode, sym, side, af):
    key = (mode, sym, side, round(af, 6))
    v = CACHE.get(key)
    if v is None:
        raw = 100.0
        a = af * raw
        fill = raw * (1 + side * 0.0002)
        d = size_position(SET[mode], 5000.0, side, fill, raw - side * 2 * a, "best", BRK[sym], atr=a, min_notional=5.0)
        v = d.leverage if d.ok else 0
        CACHE[key] = v
    return v


def summ(df, src):
    rows = []
    for tf, g in df.groupby("tf"):
        for coin, gg in list(g.groupby("sym")) + [("ALL", g)]:
            d = dict(src=src, tf=tf, coin=coin, n=len(gg), median_stop_pct=200 * gg.atr_frac.median())
            for mode in SET:
                lv = gg[f"lev_{mode}"].to_numpy()
                for L in (50, 40, 30, 20):
                    d[f"{mode}_ge{L}"] = (lv >= L).mean()
            rows.append(d)
    return rows


def main():
    D = pd.read_pickle(FY)
    D = D[["tf", "coin", "side", "atr_frac", "close_ms"]].copy()
    D["tf"] = D.tf.astype(str)
    D["sym"] = D.coin.astype(str) + "T"
    for mode in SET:
        D[f"lev_{mode}"] = [ml(mode, s, int(sd), float(a)) for s, sd, a in zip(D.sym, D.side, D.atr_frac)]
    rows = summ(D, "5y")
    acc = pd.read_csv(f"{E}/current/accounts.csv")
    ours = set(acc.loc[acc.kind == "strategy", "strategy"])
    parts = []
    for run in ("run-20261005T014624Z", "run-20261005T183457Z", "current"):
        sl = pd.read_csv(f"{E}/{run}/signal_log.csv")
        sl = sl[sl.strategy.isin(ours) & (sl.status == "SUBMITTED") & sl.timeframe.isin(["15m", "30m", "1h", "4h"])]
        parts.append(pd.DataFrame({"run": run, "tf": sl.timeframe, "sym": sl.symbol, "side": sl.side,
                                   "atr_frac": sl.atr / sl.ref_price}))
    Lv = pd.concat(parts).dropna()
    for mode in SET:
        Lv[f"lev_{mode}"] = [ml(mode, s, int(sd), float(a)) for s, sd, a in zip(Lv.sym, Lv.side, Lv.atr_frac)]
    rows += summ(Lv, "live_all_runs")
    R = pd.DataFrame(rows)
    R.to_csv(f"{OUTD}/v_lev.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(R[R.coin == "ALL"].round(3).to_string())
    print(R[(R.tf == "4h")][["src", "coin", "n", "house_ge20", "liq_only_ge20", "loss_only_ge20", "median_stop_pct"]].round(3).to_string())
    # replay 4h status by coin; account rejections
    RP = pd.read_csv(f"{O}/replay_signals.csv", low_memory=False)
    RP = RP[(RP.kind == "strategy") & RP.timeframe.isin(["1h", "4h"])]
    print(pd.crosstab([RP.timeframe, RP.symbol], RP.status))
    print("4h TRADED leverage:", RP[(RP.timeframe == "4h") & (RP.status == "TRADED")].leverage.value_counts().to_dict(),
          " 1h TRADED leverage:", RP[(RP.timeframe == "1h") & (RP.status == "TRADED")].leverage.value_counts().to_dict())
    SR = pd.read_csv(f"{O}/sizing_rejections.csv")
    SR["strategy"] = SR.account_id.str.split("@").str[0]
    SR["tf"] = SR.account_id.str.split("@").str[1]
    SR = SR[SR.strategy.isin(ours)]
    print(SR.groupby(["run", "tf"]).size())
    print(SR[SR.tf.isin(["1h", "4h"])].groupby(["run", "tf", "symbol"]).size())


if __name__ == "__main__":
    main()
