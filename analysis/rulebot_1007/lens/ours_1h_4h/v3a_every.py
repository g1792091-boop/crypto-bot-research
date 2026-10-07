"""v3a (run-20261005T014624Z, no live_bars, no replay): every signal of our 36 = entered trades (exact R from
trades_enriched) + nightly 'skipped' shadows (ROE only) converted to R with the leverage the v3a tier walk gives
that signal on a fresh $5,000 account (paperbot.sizing.size_position, rb_analyze replay_settings('tier_walk') and
INFERRED_BRACKETS):  R = roe x fill / (lev x |fill - stop|), fill = ref x (1 + side x slip), stop = ref - side x 2 ATR.
The leverage reconstruction is validated on the entered trades (their recorded leverage).

    python3 -I v3a_every.py <export_dir> <out_real_dir> <rb_analyze_dir> <repo> <out_csv>
"""
import json
import site
import sys

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

E, O, AZD, REPO, OUT = sys.argv[1:6]
sys.path.insert(0, REPO)
sys.path.insert(0, AZD)
import analyze as AZ  # noqa: E402
from paperbot.sizing import size_position  # noqa: E402

RUN = "run-20261005T014624Z"
OURS = None


def main():
    S = AZ.replay_settings("tier_walk", 0.0005)
    BRK, _ = AZ.make_brackets(None)
    sl = pd.read_csv(f"{E}/{RUN}/signal_log.csv")
    acc = pd.read_csv(f"{E}/{RUN}/accounts.csv")
    ours = set(acc.loc[acc["kind"] == "strategy", "strategy"])
    sl = sl[sl["strategy"].isin(ours) & (sl["status"] == "SUBMITTED")].copy()

    def lev_of(sym, side, ref, atr):
        fill = ref * (1 + side * S.slippage_frac)
        stop = ref - side * 2.0 * atr
        d = size_position(S, 5000.0, side, fill, stop, "best", BRK[sym], atr=atr, min_notional=5.0)
        return (d.leverage if d.ok else 0), fill, abs(fill - stop)

    # --- validate on entered trades
    T = pd.read_csv(f"{O}/trades_enriched.csv", low_memory=False)
    T = T[(T["run"] == RUN) & (T["kind"] == "strategy")]
    m = T.merge(sl[["strategy", "timeframe", "symbol", "bar_close", "atr", "ref_price", "side"]]
                .assign(signal_ts=lambda x: x["bar_close"] - 1),
                left_on=["strategy", "tf", "symbol", "signal_ts"], right_on=["strategy", "timeframe", "symbol",
                                                                              "signal_ts"], how="left",
                suffixes=("", "_sig"))
    ok = m["atr"].notna()
    levs = [lev_of(r.symbol, int(r.side), r.ref_price, r.atr)[0] for r in m[ok].itertuples()]
    match = (np.array(levs) == m.loc[ok, "leverage"].to_numpy()).mean()
    print(f"v3a entered trades: {len(T)}, joined {ok.sum()}, tier-walk leverage reproduced: {match:.4f}")
    # R of the entered trades from the reconstruction vs exact (check the R formula)
    rr = []
    for r in m[ok].itertuples():
        lev, fill, dist = lev_of(r.symbol, int(r.side), r.ref_price, r.atr)
        rr.append(r.roe * fill / (lev * dist) if lev else np.nan)
    rr = np.array(rr)
    print("R approx vs exact: median abs diff", np.nanmedian(np.abs(rr - m.loc[ok, "R"].to_numpy())),
          "corr", np.corrcoef(np.nan_to_num(rr), m.loc[ok, "R"].to_numpy())[0, 1])

    # --- skipped shadows
    sh = pd.read_csv(f"{E}/{RUN}/d3_shadows.csv")
    sh = sh[sh["kind"] == "skipped"].drop_duplicates("key").copy()
    parts = sh["key"].str.split("|", expand=True)
    sh["aid"], sh["bc"] = parts[1], pd.to_numeric(parts[3])
    sh["strategy"] = sh["aid"].str.split("@").str[0]
    sh["tf"] = sh["aid"].str.split("@").str[-1]
    sh = sh[sh["strategy"].isin(ours)]
    sh = sh.merge(sl[["strategy", "timeframe", "symbol", "bar_close", "atr", "ref_price", "side", "id"]]
                  .rename(columns={"timeframe": "tf", "bar_close": "bc", "side": "side_sig"}),
                  on=["strategy", "tf", "symbol", "bc"], how="left")
    rows = []
    for r in sh.itertuples():
        if not (r.atr == r.atr) or not (r.roe == r.roe):
            rows.append(np.nan)
            continue
        lev, fill, dist = lev_of(r.symbol, int(r.side), r.ref_price, r.atr)
        rows.append(r.roe * fill / (lev * dist) if lev else np.nan)
    sh["R"] = rows
    sh["src"] = "skipped_shadow"
    print("skipped shadows (ours):", len(sh), "with R:", sh["R"].notna().sum(), "resolved=0:", (sh["resolved"] == 0).sum())
    ent = T[["strategy", "tf", "symbol", "signal_ts", "side", "R", "roe", "exit_reason"]].copy()
    ent["bc"] = ent["signal_ts"] + 1
    ent["src"] = "entered"
    out = pd.concat([ent[["strategy", "tf", "symbol", "bc", "side", "R", "roe", "exit_reason", "src"]],
                     sh[["strategy", "tf", "symbol", "bc", "side", "R", "roe", "exit_reason", "src"]]],
                    ignore_index=True)
    out = out.merge(sl[["strategy", "timeframe", "symbol", "bar_close", "id"]].rename(
        columns={"timeframe": "tf", "bar_close": "bc", "id": "sig_id"}), on=["strategy", "tf", "symbol", "bc"],
        how="left")
    out.insert(0, "run", RUN)
    out.to_csv(OUT, index=False)
    print(out.groupby(["tf", "src"]).agg(n=("R", "size"), nR=("R", "count"), meanR=("R", "mean")))


if __name__ == "__main__":
    main()
