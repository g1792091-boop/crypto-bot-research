"""Verifier: live every-signal outcomes of our 36 strategies (own assembly).

    python3 -I live_es.py <export_dir> <out_real_dir> <repo> <their es_signals.csv> <their tf_summary_live.csv> <out_dir>

v3a: entered trades (trades_enriched R) + nightly skipped shadows (d3_shadows kind=skipped, resolved=1). Shadow R from
ROE needs the shadow's leverage, not stored: rebuilt with paperbot.sizing.size_position under the v3a tier walk
(DEFAULT_TIERS, max margin 0.40), requested tier = the signal's own outcomes.csv sig_tier (not an assumed "best"),
validated on the v3a ENTERED outcomes against the recorded leverage (outcomes detail.leverage).
v3b / v4: replay_signals TRADED (R exact); UNRESOLVED kept separately with mark_R.
Cluster = run x bar_close floored to 4 h; CI = cluster bootstrap (ratio of sums), 4,000 draws, seed fixed.
"""
import json
import site
import sys

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

E, O, REPO, THEIR_ES, THEIR_TF, OUTD = sys.argv[1:7]
sys.path.insert(0, REPO)
from paperbot.config import DEFAULT_TIERS, v3_settings  # noqa: E402
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
V3A, V3B, V4 = "run-20261005T014624Z", "run-20261005T183457Z", "current"
RK = {V3A: "v3a", V3B: "v3b", V4: "v4"}
H4 = 14_400_000
TFS = ("15m", "30m", "1h", "4h")
RNG = np.random.default_rng(777)


def boot(x, c, B=4000):
    x = np.asarray(x, float)
    s = pd.DataFrame({"x": x, "c": c}).groupby("c")["x"].agg(["sum", "size"])
    G = len(s)
    if len(x) < 3 or G < 3:
        return np.nan, np.nan, G
    i = RNG.integers(0, G, size=(B, G))
    m = s["sum"].to_numpy()[i].sum(1) / s["size"].to_numpy()[i].sum(1)
    return np.percentile(m, 2.5), np.percentile(m, 97.5), G


def main():
    S_tw = v3_settings(leverage_rule="tier_walk", tiers=DEFAULT_TIERS, max_margin_frac=0.40, taker_fee=0.0005)
    acc = pd.read_csv(f"{E}/{V3A}/accounts.csv")
    ours = set(acc.loc[acc["kind"] == "strategy", "strategy"])
    oc = pd.read_csv(f"{E}/{V3A}/outcomes.csv")
    oc = oc[oc["sig_strategy_id"].isin(ours) & oc["sig_timeframe"].isin(TFS)].copy()

    def lev_of(sym, side, ref, atr, tier):
        fill = ref * (1 + side * S_tw.slippage_frac)
        stop = ref - side * 2.0 * atr
        d = size_position(S_tw, 5000.0, side, fill, stop, tier, BRK[sym], atr=atr, min_notional=5.0)
        return (d.leverage if d.ok else 0), fill, abs(fill - stop)

    # validation on ENTERED outcomes (fresh-account assumption: equity differs from 5,000 in reality)
    en = oc[oc["status"] == "ENTERED"].copy()
    en["lev_rec"] = en["detail"].map(lambda s: json.loads(s).get("leverage") if isinstance(s, str) else np.nan)
    en["lev_new"] = [lev_of(r.symbol, int(r.sig_side), r.ref_price, r.sig_atr, r.sig_tier)[0] for r in en.itertuples()]
    en["lev_best"] = [lev_of(r.symbol, int(r.sig_side), r.ref_price, r.sig_atr, "best")[0] for r in en.itertuples()]
    print("v3a ENTERED (ours, 15m-4h):", len(en), "leverage reproduced with own sig_tier:",
          round((en.lev_new == en.lev_rec).mean(), 4), " with 'best':", round((en.lev_best == en.lev_rec).mean(), 4))
    print(" tiers requested:", en.sig_tier.value_counts().to_dict(), " by tf match:",
          en.assign(m=en.lev_new == en.lev_rec).groupby("sig_timeframe").m.mean().round(3).to_dict())

    # entered trades (exact R)
    T = pd.read_csv(f"{O}/trades_enriched.csv", low_memory=False)
    T = T[(T.run == V3A) & (T.kind == "strategy") & T.tf.isin(TFS)]
    ent = pd.DataFrame({"run": V3A, "strategy": T.strategy, "tf": T.tf, "symbol": T.symbol, "bc": T.signal_ts + 1,
                        "side": T.side, "R": T.R, "src": "entered", "status": "TRADED"})
    # skipped shadows
    sh = pd.read_csv(f"{E}/{V3A}/d3_shadows.csv")
    sh = sh[sh.kind == "skipped"].copy()
    k = sh.key.str.split("|", expand=True)
    sh["aid"], sh["bc"] = k[1], k[3].astype(np.int64)
    sh["strategy"] = sh.aid.str.split("@").str[0]
    sh["tf"] = sh.aid.str.split("@").str[1]
    sh = sh[sh.strategy.isin(ours) & sh.tf.isin(TFS)]
    o2 = oc[oc.status == "SKIPPED"][["account_id", "symbol", "sig_ts", "sig_side", "sig_atr", "ref_price", "sig_tier"]]
    o2 = o2.assign(bc=o2.sig_ts + 1).drop_duplicates(["account_id", "symbol", "bc"])
    sh = sh.merge(o2, left_on=["aid", "symbol", "bc"], right_on=["account_id", "symbol", "bc"], how="left")
    print("v3a skipped shadows (ours 15m-4h):", len(sh), "joined to outcomes:", sh.sig_atr.notna().sum(),
          "side agrees:", (sh.side == sh.sig_side).mean())
    R = []
    for r in sh.itertuples():
        if not (r.roe == r.roe) or not (r.sig_atr == r.sig_atr):
            R.append(np.nan)
            continue
        lev, fill, dist = lev_of(r.symbol, int(r.side), r.ref_price, r.sig_atr, r.sig_tier)
        R.append(r.roe * fill / (lev * dist) if lev else np.nan)
    sh["R"] = R
    sh["src"] = "shadow"
    sh["status"] = np.where(sh.resolved == 1, "TRADED", "UNRESOLVED")
    a = pd.concat([ent, sh[["strategy", "tf", "symbol", "bc", "side", "R", "src", "status"]].assign(run=V3A)])
    # replay v3b + v4
    RP = pd.read_csv(f"{O}/replay_signals.csv", low_memory=False)
    RP = RP[(RP.kind == "strategy") & RP.timeframe.isin(TFS)]
    rp = pd.DataFrame({"run": RP.run, "strategy": RP.strategy, "tf": RP.timeframe, "symbol": RP.symbol,
                       "bc": RP.bar_close, "side": RP.side, "R": RP.R, "mark_R": RP.mark_R, "src": "replay",
                       "status": RP.status})
    ES = pd.concat([a, rp], ignore_index=True)
    ES["rk"] = ES.run.map(RK)
    ES["cl"] = ES.run + "|" + (ES.bc // H4).astype(np.int64).astype(str)
    ES.to_csv(f"{OUTD}/v_live_es.csv", index=False)
    ok = ES[(ES.status == "TRADED") & ES.R.notna()]
    rows = []
    for tf in TFS:
        for rk in ("v3a", "v3b", "v4", "all"):
            g = ok[ok.tf == tf] if rk == "all" else ok[(ok.tf == tf) & (ok.rk == rk)]
            lo, hi, G = boot(g.R, g.cl)
            un = ES[(ES.tf == tf) & (ES.status == "UNRESOLVED") & ((ES.rk == rk) | (rk == "all"))]
            rows.append(dict(tf=tf, run=rk, n=len(g), mean_R=g.R.mean(), lo=lo, hi=hi, clusters=G,
                             n_unresolved=len(un), unres_share=len(un) / max(len(un) + len(g), 1)))
    TS = pd.DataFrame(rows)
    TS.to_csv(f"{OUTD}/v_live_tf.csv", index=False)
    pd.set_option("display.width", 200)
    print(TS.round(4).to_string())
    th = pd.read_csv(THEIR_TF)
    print(th[["tf", "run", "n", "mean_R", "ci95_lo", "ci95_hi", "clusters"]].round(4).to_string())
    # row-level comparison with their es_signals
    their = pd.read_csv(THEIR_ES)
    key = ["run", "strategy", "tf", "symbol", "bc"]
    their = their.rename(columns={"timeframe": "tf"})
    m = ok.merge(their[key + ["R"]], on=key, how="outer", suffixes=("", "_their"), indicator=True)
    print(m["_merge"].value_counts().to_dict())
    both = m[m["_merge"] == "both"]
    print("R abs diff (both): max", (both.R - both.R_their).abs().max(), "share >1e-6",
          ((both.R - both.R_their).abs() > 1e-6).mean())
    print(m[m["_merge"] != "both"].groupby(["run", "tf", "_merge"]).size())


if __name__ == "__main__":
    main()
