#!/usr/bin/env python3
"""v3a (run-20261005T014624Z, tier-walk leverage, no live_bars) every-signal R for kind 'strategy'.

v3a has no replay; its every-signal sample = the entered trades (R known) + the nightly 'skipped' shadows
(daily3: the skipped signal alone on a fresh $5,000 account, Binance final klines, ROE only).
R = ROE / (leverage x stop_frac) holds exactly for every trade (checked on trades_enriched: max diff 1.7e-13).
The shadow row has no leverage, so the leverage / entry / stop the engine would choose for that signal on a fresh
account is recomputed with the repo's own PaperEngine (tier walk settings of v3a, inferred brackets) on one
synthetic bar at the signal's reference price. Validation: the same recomputation on the 'base' shadow rows (which
DO carry the fresh-account leverage and match real trades) -> leverage agreement and R agreement.

usage: python3 -I -B v3a_every_signal.py <export_dir> <out_real_dir> <repo> <out_dir>
"""
import os
import site
import sys

sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path:
    sys.path.append(us)
HERE = os.path.dirname(os.path.abspath(__file__))
EXP, OUTREAL, REPO, OUT = sys.argv[1:5]
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

import json  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import rb_lib as L  # noqa: E402  (a verbatim copy of rb_analyze/analyze.py)
from paperbot.daily3 import make_signal  # noqa: E402
from paperbot.engine import PaperEngine  # noqa: E402
from paperbot.models import Bar  # noqa: E402

RUN = "run-20261005T014624Z"
run = L.Run(EXP, RUN)
taker = L.implied_taker(run)
S = L.replay_settings("tier_walk", taker)
brackets, _ = L.make_brackets(None)
specs = L.infer_specs(run.trades)
MIN = 60_000


def fresh_entry(d):
    """leverage, entry, stop_initial the engine picks on a fresh account for signal row d (dict as signal_log)."""
    sig = make_signal(d)
    e = PaperEngine(S, brackets, symbol_specs=specs, book="lens")
    e.submit(sig)
    px = float(d["ref_price"])
    b = Bar(d["symbol"], int(d["bar_close"]), int(d["bar_close"]) + MIN - 1, px, px, px, px,
            mark_open=px, mark_high=px, mark_low=px, mark_close=px, volume=1.0)
    e.step({d["symbol"]: b}, {})
    p = e.position
    if p is None:
        return np.nan, np.nan, np.nan
    return float(p.leverage), float(p.entry_price), float(p.stop_initial)


sig = run.sig.copy()
sig["key"] = sig["strategy"] + "@" + sig["timeframe"] + "|" + sig["symbol"] + "|" + sig["bar_close"].astype(str)
sigd = {k: r for k, r in zip(sig["key"], sig.to_dict("records"))}

sh = L.parse_shadows(run)
sh["kind_acct"] = sh["aid"].map(L.infer_kind)
sh = sh[sh["kind_acct"] == "strategy"].copy()
sh["k2"] = sh["aid"] + "|" + sh["symbol"] + "|" + sh["bc"].astype("int64").astype(str)

rows = []
cache = {}


def lev_for(k2):
    if k2 not in cache:
        d = sigd.get(k2)
        cache[k2] = (np.nan, np.nan, np.nan) if d is None else fresh_entry(
            {kk: d[kk] for kk in ("bar_close", "timeframe", "strategy", "symbol", "side", "atr", "ref_price",
                                  "ref_time", "delay_ms")})
    return cache[k2]


# ---- validation on base rows (fresh-account leverage recorded in data)
base = sh[sh["kind"] == "base"].copy()
T = pd.read_csv(os.path.join(OUTREAL, "trades_enriched.csv"))
T = T[T["run"] == RUN]
T["k2"] = T["account_id"] + "|" + T["symbol"] + "|" + (T["signal_ts"] + 1).astype("int64").astype(str)
Tk = T.drop_duplicates("k2").set_index("k2")
val = []
for r in base.itertuples():
    dd = json.loads(r.data) if isinstance(r.data, str) else {}
    lev_s, ent, stp = lev_for(r.k2)
    sf = abs(ent - stp) / ent if ent == ent else np.nan
    t = Tk.loc[r.k2] if r.k2 in Tk.index else None
    val.append({"k2": r.k2, "tf": r.timeframe, "lev_base": dd.get("leverage"), "lev_syn": lev_s,
                "roe_base": r.roe, "actual_roe": dd.get("actual_roe"), "actual_lev": dd.get("actual_leverage"),
                "stop_frac_syn": sf, "R_conv": r.roe / (lev_s * sf) if lev_s == lev_s and sf == sf and r.roe == r.roe else np.nan,
                "R_actual": None if t is None else t["R"], "stop_frac_actual": None if t is None else t["stop_frac"]})
V = pd.DataFrame(val)
V.to_csv(os.path.join(OUT, "v3a_conversion_validation_rows.csv"), index=False)
same = V[(V["lev_base"] == V["actual_lev"]) & (np.abs(V["roe_base"] - V["actual_roe"]) < 1e-9) & V["R_actual"].notna()]
summ = {
    "base_rows": len(V),
    "lev_syn_eq_lev_base_share": float((V["lev_syn"] == V["lev_base"]).mean()),
    "rows_base_equals_actual_trade": len(same),
    "R_conv_minus_R_actual_median_abs": float(np.nanmedian(np.abs(same["R_conv"] - same["R_actual"]))),
    "R_conv_minus_R_actual_p95_abs": float(np.nanpercentile(np.abs(same["R_conv"] - same["R_actual"]), 95)),
    "R_conv_minus_R_actual_mean": float(np.nanmean(same["R_conv"] - same["R_actual"])),
    "stop_frac_rel_err_median": float(np.nanmedian(np.abs(same["stop_frac_syn"] / same["stop_frac_actual"] - 1))),
}
print("validation:", summ)
pd.DataFrame([summ]).to_csv(os.path.join(OUT, "v3a_conversion_validation.csv"), index=False)

# ---- skipped shadows -> R
sk = sh[sh["kind"] == "skipped"].copy()
for r in sk.itertuples():
    lev_s, ent, stp = lev_for(r.k2)
    sf = abs(ent - stp) / ent if ent == ent else np.nan
    rows.append({"run": RUN, "account_id": r.aid, "strategy": r.aid.split("@")[0], "timeframe": r.timeframe,
                 "symbol": r.symbol, "bar_close": int(r.bc), "side": r.side, "source": "skipped_shadow",
                 "resolved": r.resolved, "roe": r.roe, "exit_reason": r.exit_reason, "leverage": lev_s,
                 "stop_frac": sf, "R": r.roe / (lev_s * sf) if (r.roe == r.roe and lev_s == lev_s and sf == sf) else np.nan,
                 "roe_per_lev": r.roe / lev_s if r.roe == r.roe and lev_s == lev_s else np.nan,
                 "in_signal_log": r.k2 in sigd, "day": r.day})
SK = pd.DataFrame(rows)
# shadow window: signals whose bar closed inside the nightly job's covered span
lo, hi = SK["bar_close"].min(), SK["bar_close"].max()
E = T[T["kind"] == "strategy"].copy()
E = pd.DataFrame({"run": RUN, "account_id": E["account_id"], "strategy": E["strategy"], "timeframe": E["tf"],
                  "symbol": E["symbol"], "bar_close": (E["signal_ts"] + 1).astype("int64"), "side": E["side"],
                  "source": "entered", "resolved": 1, "roe": E["roe"], "exit_reason": E["exit_reason"],
                  "leverage": E["leverage"], "stop_frac": E["stop_frac"], "R": E["R"], "roe_per_lev": E["roe_per_lev"],
                  "mfe_R": E["mfe_R"], "mae_R": E["mae_R"], "cost_R": E["cost_R"], "in_signal_log": True, "day": E["entry_day"]})
E["in_shadow_window"] = (E["bar_close"] >= lo) & (E["bar_close"] <= hi)
SK["in_shadow_window"] = True
A = pd.concat([E, SK], ignore_index=True)
A.to_csv(os.path.join(OUT, "v3a_every_signal.csv"), index=False)
print("shadow window (KST):", L.fmt_ts(lo), "~", L.fmt_ts(hi))
print(A.groupby(["source", "timeframe"]).agg(n=("R", "size"), n_R=("R", lambda x: x.notna().sum()),
                                             mean_R=("R", "mean")).to_string())
print("skipped not in signal_log:", int((~SK["in_signal_log"]).sum()), "unresolved:", int((SK["resolved"] == 0).sum()),
      "resolved no trade:", int(((SK["resolved"] == 1) & SK["roe"].isna()).sum()))
print("lev mix skipped 15m/30m:", SK[SK.timeframe.isin(["15m", "30m"])]["leverage"].value_counts(dropna=False).to_dict())
