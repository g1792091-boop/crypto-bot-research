#!/usr/bin/env python3
"""5-year backtest reference table, one row per (source, strategy, timeframe, variant), for side-by-side comparison
with the paper results (analyze.py --ref fiveyear_ref.csv).

    python3 -I fiveyear_ref.py [--repo /home/user/crypto-bot-research] [--out fiveyear_ref.csv]

Reads only (never writes into the repo):

1. research/strategy_profiles/out_binance/profiles.json  (machine-readable source of PROFILES.md, Binance-futures
   rebuild). The 36 locked strategies x 5m/15m/30m/1h/4h. EVERY signal run alone (no account, no position limit),
   2021-08-01 .. 2026-09-30, six coins, next-bar-open entry + 0.02% slippage, 2 x ATR14 stop, the stepped profit
   lock (ladder), taker 0.05% both sides, funding, sized at a fixed $1,000 equity with the "tier_walk" rule
   (40% x 50x -> 40% x 40x -> 30% x 30x -> 20% x 20x, first passing), EXAMPLE leverage brackets
   (meta.brackets = "example tiers (as in rules_bt)").  -> source = "profiles_binance", variant = "every_signal".
2. research/paper_rules/out_binance/accounts.csv  (the "5년 계좌" column of PROFILES.md): one $1,000 account per
   (strategy, tf), one position at a time, same rules; rows for k (stop ATR multiple) 1.0 / 1.5 / 2.0 and windows
   is (2021-08-01..2024-07-01) / cf (2024-07-01..2026-09-30). Only k = 2.0 (the house stop) is joined, as acct_* columns
   of the profiles rows. NOTE: its column "mean_R" is pnl / margin = mean net ROE per trade, NOT an R-multiple.
3. research/deepseek200/out/results.csv (source of truth for the DeepSeek-200 definitions; 44 entries x 2 exits x
   tf = 342 rows). -> source = "deepseek200", variant = exit name (X5_TRAIL2 or X2_SL15_TP3). These are the
   PREREG's OWN exits, NOT the house 2 ATR + ladder exits the live ds200 accounts use, and the per-trade numbers are
   UNLEVERED net returns on notional in percent (mean_pct), not ROE. windows: is = 2021-08-01..2024-07-01,
   cf = 2024-07-01..2026-09-30 ("oos"), pre = 2020-01-01..2021-08-01. Gates: stage1 / stage1_top / stage2 / stage3 /
   x20_ok / candidate / ... exactly as in results.csv.

Output columns (NaN where a source has no such number):
  source, strategy, timeframe, variant
  n_signals          profiles: signals of the 5 years; deepseek: trades is+cf (n12)
  per_day            profiles: signals per day (6 coins together); deepseek: (is_n + cf_n) / days of is+cf
  mean_roe           profiles: mean net ROE per signal at the tier-walk leverage mix (fraction, -0.046 = -4.6%)
  mean_roe_t         profiles: t of mean_roe
  mean_roe_is / mean_roe_cf   profiles: by window
  mean_lev           profiles: trade-weighted mean leverage of lev_mix (50/40/30/20)
  mean_ret_notional  net return per unit notional = mean_roe / mean_lev (profiles, approximate: ROE is per trade at
                     its own leverage) or mean12_pct / 100 (deepseek, exact unlevered mean of is+cf)
  roe_at_30x_equiv   mean_ret_notional x 30 (the live 'normal' first leverage; for comparison only)
  win_rate           fraction of trades with net > 0
  payoff             avg win / |avg loss| (deepseek: is+cf trade-weighted from is_rr/cf_rr is not exact: we give
                     is_rr and cf_rr separately and payoff = NaN) ; profiles: not available (NaN)
  pf_is, pf_cf       deepseek profit factor by window
  sized_share        profiles: share of signals that passed the sizing checks (the rest rejected: no trade)
  lev50/lev40/lev30/lev20_share   profiles: leverage mix of sized signals
  exit_stop/exit_lock/exit_liq/exit_open   profiles: exit reason shares
  median_hold_hours  profiles; deepseek: hold_mean (bars) is given in hold_bars_is
  mean_best_roe      profiles: mean best net ROE reached during the trade
  long_share, trend_share   profiles
  acct_k2_*          paper_rules one-account (k = 2.0) per window: trades, win, mean_roe (file column mean_R),
                     final ($ of $1,000), max_dd, bust
  ds_* columns       deepseek per-window n / win% / mean% / pf / rr / p / coins_pos, gates
  gate_pass          deepseek: candidate (final verdict); stage1 shown separately. profiles: no gate (NaN)
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import site
import sys

us = site.getusersitepackages()
if us not in sys.path:
    sys.path.append(us)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

TFS = ("5m", "15m", "30m", "1h", "4h")
DS_DAYS_12 = (pd.Timestamp("2026-09-30") - pd.Timestamp("2021-08-01")).days


def profiles_rows(repo: str) -> list[dict]:
    p = os.path.join(repo, "research", "strategy_profiles", "out_binance", "profiles.json")
    with open(p) as fh:
        js = json.load(fh)
    meta, prof = js["meta"], js["profiles"]
    acc_path = os.path.join(repo, "research", "paper_rules", "out_binance", "accounts.csv")
    acc = pd.read_csv(acc_path) if os.path.exists(acc_path) else pd.DataFrame()
    acc2 = acc[acc["k"] == 2.0] if len(acc) else acc
    rows = []
    for strat, per_tf in prof.items():
        for tf in TFS:
            r = per_tf.get(tf)
            row = {"source": "profiles_binance", "strategy": strat, "timeframe": tf, "variant": "every_signal"}
            if r is None:
                row["note"] = "absent in profiles.json"
                rows.append(row)
                continue
            lm = r.get("lev_mix") or {}
            tot = sum(float(v) for v in lm.values()) if lm else 0.0
            mean_lev = sum(float(k) * float(v) for k, v in lm.items()) / tot if tot else np.nan
            ex = r.get("exit_share") or {}
            byw = r.get("mean_roe_by_window") or {}
            mr = r.get("mean_roe")
            row.update({
                "n_signals": r.get("signals"), "per_day": r.get("signals_per_day"),
                "mean_roe": mr, "mean_roe_t": r.get("mean_roe_t"),
                "mean_roe_is": byw.get("is"), "mean_roe_cf": byw.get("cf"),
                "mean_lev": mean_lev,
                "mean_ret_notional": (mr / mean_lev) if (mr is not None and mean_lev and not math.isnan(mean_lev)) else np.nan,
                "win_rate": r.get("win_rate"), "payoff": np.nan,
                "sized_share": r.get("sized_share"),
                **{f"lev{k}_share": (float(lm.get(str(k), 0)) / tot if tot else np.nan) for k in (50, 40, 30, 20)},
                "exit_stop": ex.get("stop"), "exit_lock": ex.get("lock"), "exit_liq": ex.get("liquidation"),
                "exit_open": ex.get("open"),
                "median_hold_hours": r.get("median_hold_hours"), "mean_best_roe": r.get("mean_best_roe"),
                "long_share": r.get("long_share"), "trend_share": r.get("trend_share"),
                "style": (r.get("labels") or {}).get("style"),
            })
            if mr is None:
                row["note"] = f"no mean_roe (signals {r.get('signals')}, sized_share {r.get('sized_share')})"
            mrn = row["mean_ret_notional"]
            row["roe_at_30x_equiv"] = mrn * 30 if mrn == mrn else np.nan
            for w in ("is", "cf"):
                a = acc2[(acc2["strategy"] == strat) & (acc2["tf"] == tf) & (acc2["window"] == w)] if len(acc2) else []
                if len(a):
                    a = a.iloc[0]
                    row.update({f"acct_k2_{w}_trades": a["trades"], f"acct_k2_{w}_win": a["win"],
                                f"acct_k2_{w}_mean_roe": a["mean_R"], f"acct_k2_{w}_final": a["final"],
                                f"acct_k2_{w}_max_dd": a["max_dd"], f"acct_k2_{w}_bust": a["bust"]})
            row["ref_meta"] = f"equity_for_sizing={meta.get('equity_for_sizing')}; brackets={meta.get('brackets')}; " \
                              f"k_stop={meta.get('k_stop')}; leverage=tier_walk (40%x50x..20%x20x)"
            rows.append(row)
    return rows


def deepseek_rows(repo: str) -> list[dict]:
    p = os.path.join(repo, "research", "deepseek200", "out", "results.csv")
    t = pd.read_csv(p)
    rows = []
    for _, r in t.iterrows():
        n12 = float(r.get("n12", np.nan))
        row = {"source": "deepseek200", "strategy": r["entry"], "timeframe": r["tf"], "variant": r["exit"],
               "family": r["family"], "n_signals": n12, "per_day": n12 / DS_DAYS_12 if n12 == n12 else np.nan,
               "mean_ret_notional": r["mean12_pct"] / 100.0 if pd.notna(r["mean12_pct"]) else np.nan,
               "max_lev": r["max_lev"]}
        row["roe_at_30x_equiv"] = row["mean_ret_notional"] * 30 if pd.notna(row["mean_ret_notional"]) else np.nan
        nw = 0.0
        ww = 0.0
        for w in ("is", "cf"):
            n = r[f"{w}_n"]
            if pd.notna(n) and n > 0 and pd.notna(r[f"{w}_win_pct"]):
                nw += n
                ww += n * r[f"{w}_win_pct"] / 100
        row["win_rate"] = ww / nw if nw else np.nan
        row["payoff"] = np.nan
        for w in ("is", "cf", "pre"):
            for c in ("n", "win_pct", "mean_pct", "pf", "rr", "p", "coins_pos", "coins_n", "avg_win_pct",
                      "avg_loss_pct", "own_final_x", "gross_mean_pct", "cost_mean_pct", "long_mean_pct",
                      "short_mean_pct"):
                col = f"{w}_{c}"
                if col in r:
                    row[f"ds_{col}"] = r[col]
            row[f"hold_bars_{w}"] = r.get(f"{w}_hold_mean")
        row["pf_is"], row["pf_cf"] = r["is_pf"], r["cf_pf"]
        for g in ("stage1", "stage1_top", "stage2", "stage3", "x20_ok", "bh12", "candidate", "weak_candidate",
                  "candidate_20x", "stage3_bonf", "all3_positive", "p12", "boot_p12", "boot_p3"):
            row[f"ds_{g}"] = r[g]
        row["gate_pass"] = bool(r["candidate"])
        row["ref_meta"] = ("unlevered net % per trade on notional; PREREG exits (not the live house ladder); "
                           "windows is=2021-08-01..2024-07-01 cf=2024-07-01..2026-09-30 pre=2020-01-01..2021-08-01")
        rows.append(row)
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default="/home/user/crypto-bot-research")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "fiveyear_ref.csv"))
    a = ap.parse_args(argv)
    rows = profiles_rows(a.repo) + deepseek_rows(a.repo)
    df = pd.DataFrame(rows)
    first = ["source", "strategy", "timeframe", "variant", "n_signals", "per_day", "mean_roe", "mean_roe_t",
             "mean_roe_is", "mean_roe_cf", "mean_lev", "mean_ret_notional", "roe_at_30x_equiv", "win_rate", "payoff",
             "pf_is", "pf_cf", "gate_pass", "sized_share", "note"]
    cols = [c for c in first if c in df.columns] + [c for c in df.columns if c not in first]
    df = df[cols]
    df.to_csv(a.out, index=False, quoting=csv.QUOTE_MINIMAL)
    # coverage report
    prof = df[df.source == "profiles_binance"]
    have = prof[prof["mean_roe"].notna()]
    print(f"profiles_binance: {len(prof)} strategy x tf rows, {len(have)} with mean_roe; missing mean_roe:")
    for _, r in prof[prof["mean_roe"].isna()].iterrows():
        print(f"   {r.strategy} {r.timeframe}: {r.get('note')}")
    ds = df[df.source == "deepseek200"]
    print(f"deepseek200: {len(ds)} rows ({ds.strategy.nunique()} definitions x exits x tf); "
          f"stage1 passers in results.csv: "
          f"{[(r.timeframe, r.strategy, r.variant) for _, r in ds[ds['ds_stage1'] == True].iterrows()]}")  # noqa: E712
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
