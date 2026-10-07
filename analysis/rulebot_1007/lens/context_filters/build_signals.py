#!/usr/bin/env python3
"""Build one row per SUBMITTED signal (all three runs) with its chart context and its outcome in R.

    python3 -I build_signals.py <export_dir> <out_real_dir> <repo> <out_dir>

Outcome per signal ("signal alone", fresh $5,000 account, house exits):
  v3b, v4 : the pipeline's independent replay (replay_signals.csv, status TRADED) -> R, flip_R, cost, tier.
  v3a     : no live_bars, so: the account's real trade if it ENTERED the signal (trades_enriched R), else the nightly
            'skipped' shadow (d3_shadows kind=skipped, ROE only) converted to R with the repo's own sizing
            (tier_walk, fresh $5,000, the same call the engine makes): R = ROE * margin / (qty * |fill - stop|).
  v4 also gets the same trade/shadow outcome (R_ts) so the shadow->R conversion can be checked against the replay.
Nothing outside <out_dir> is written; the repository is only imported.
"""
from __future__ import annotations

import json
import os
import site
import sys

sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path:
    sys.path.append(us)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

EXPORT, OUTREAL, REPO, OUT = sys.argv[1:5]
sys.path.append(REPO)
os.makedirs(OUT, exist_ok=True)

RUNS = {"run-20261005T014624Z": "v3a", "run-20261005T183457Z": "v3b", "current": "v4"}
TAKER, SLIP = 0.0005, 0.0002
HOUR = 3_600_000

# strategy families (STRATEGY_CATALOG_KO.md: core 36 measured trend ratio; DeepSeek estimated from rule shape)
FAM = {}
for s in ["S1_EMA_RSI_CHOP", "S2_ST_ROC", "S4_BB_BBP", "S5_DONCHIAN_MFI", "N01_ST_EMA", "N02_ST_KST", "N03_ADX_GC",
          "N04_ST_KLINGER", "N05_PSAR_POC", "N06_MACD_ORB", "N07_ICHI_CMO", "N09_ALLIG_AROON", "N12_ICHI_AO",
          "N13_3OUTSIDE", "N15_KC_AO", "N18_VWMA_MACD", "N19_FIB_CHOP", "N23_HA_ST", "DOGE"]:
    FAM[s] = "trend"
for s in ["S3_CMO_SANDWICH", "S6_EMA_DMI_ADX", "N08_ICHI_WR", "N10_HA_PSAR", "N16_BBRSI", "N20_EMA9_CHOP",
          "N22_VORTEX_PSAR", "N24_DMI", "V39_ALL", "OBV_S"]:
    FAM[s] = "mixed"
for s in ["N11_BREAKAWAY", "N17_KC_RSI", "N25_DST_CCI", "V45_AMB", "OBV_B"]:
    FAM[s] = "revert"
for s in ["F1_RSI_DIV", "F1_MOM_DIV", "F1_PVT_DIV", "F2_DEMARK", "F5_BOX", "F5_BOX_RSI", "F5_BOX_HTF", "F11_TSOUP",
          "F11_RAID", "F11_PO3", "F13_RAID_PD", "F15_ASIA_SWEEP", "F17_Z", "F17_Z_HL", "F10_M2022", "F12_MSS",
          "F12_MSS_DISP"]:
    FAM[s] = "revert"
for s in ["F3_BOS", "F3_HHHL", "F4_FAN", "F6_VWAP_CROSS", "F6_VWAP_FAIL", "F7_RF_TRIPLE", "F7_RF_ONLY",
          "F15_ASIA_BRK", "F15_LON_BRK", "F15_OPEN0930", "F15_OPEN0000", "F15_ORB", "F3_BOS_ZONE", "F4_PULL",
          "F4_PULL_RSI", "F8_VWICK", "F9_FVG", "F9_OB", "F10_OTE", "F13_FVG_PD", "F16_FIB382", "F16_FIB500",
          "F16_FIB618", "F16_FIB764"]:
    FAM[s] = "trend"
for s in ["F9_IFVG", "F9_BREAKER", "F14_SMT"]:
    FAM[s] = "mixed"


def kind_of(aid: str, acc: pd.DataFrame) -> str:
    if aid in acc.index:
        return acc.at[aid, "kind"]
    s = aid.split("@")[0]
    if s.startswith("RANDOM"):
        return "random"
    if s.startswith("F") and s[1].isdigit():
        return "ds200"
    return "strategy"


def flat_ctx(path: str) -> pd.DataFrame:
    from paperbot.levrule import quality_score
    rows = []
    with open(path) as fh:
        for line in fh:
            d = json.loads(line)
            c = d.get("ctx") or {}
            sr = c.get("sr") if isinstance(c.get("sr"), dict) else {}
            r = {"sig_id": int(d["id"]), "ctx_close": d.get("close"), "has_ctx": int(bool(c.get("regime")))}
            for k in ("regime", "htf_regime", "er", "box_pos", "htf_box_pos", "ema20_dist_atr", "trend_age",
                      "range_pct", "adx", "di_plus", "di_minus"):
                r[k] = c.get(k)
            for k in ("room", "floor", "room_type", "floor_type", "level_before_lock", "support_before_stop",
                      "breakout", "lev"):
                r["sr_" + k] = sr.get(k)
            r["_strength"] = c.get("strength")
            rows.append(r)
    return pd.DataFrame(rows)


def main() -> int:
    from paperbot.config import DEFAULT_TIERS, v3_settings
    from paperbot.daily3 import make_signal
    from paperbot.engine import PaperEngine
    from paperbot.levrule import quality_score
    sys.path.insert(0, os.path.join(os.path.dirname(OUTREAL)))      # rb_analyze/ (analyze.py)
    import analyze as A                                               # noqa: E402  (imports only)

    brackets, _ = A.make_brackets(None)
    TE = pd.read_csv(os.path.join(OUTREAL, "trades_enriched.csv"), low_memory=False)
    RP = pd.read_csv(os.path.join(OUTREAL, "replay_signals.csv"), low_memory=False)
    specs = A.infer_specs(TE)
    S_walk = v3_settings(leverage_rule="tier_walk", tiers=DEFAULT_TIERS, max_margin_frac=0.40, taker_fee=TAKER)
    S_q = v3_settings(taker_fee=TAKER)
    allrows = []
    checks = []
    for run, tag in RUNS.items():
        rd = os.path.join(EXPORT, run)
        sig = pd.read_csv(os.path.join(rd, "signal_log.csv"))
        sig = sig[sig["status"] == "SUBMITTED"].copy()
        sig = sig.rename(columns={"id": "sig_id"})
        acc = pd.read_csv(os.path.join(rd, "accounts.csv")).set_index("account_id")
        sig["account_id"] = sig["strategy"] + "@" + sig["timeframe"]
        sig["kind"] = [kind_of(a, acc) for a in sig["account_id"]]
        cx = flat_ctx(os.path.join(rd, "signal_ctx.jsonl"))
        sig = sig.merge(cx, on="sig_id", how="left")
        # quality score / tier from the recorded strength (levrule, as quality_v1 reads it)
        qs = [quality_score(st, s, tf) if isinstance(st, dict) else {"score": None, "tier": None}
              for st, s, tf in zip(sig["_strength"], sig["strategy"], sig["timeframe"])]
        sig["q_score"] = [q.get("score") for q in qs]
        sig["q_tier"] = [q.get("tier") for q in qs]
        sig = sig.drop(columns=["_strength"])
        # account outcome
        o = pd.read_csv(os.path.join(rd, "outcomes.csv"))
        o = o[["account_id", "sig_ts", "symbol", "status", "reason"]].rename(
            columns={"status": "acct_status", "reason": "acct_reason"})
        sig["sig_ts"] = sig["bar_close"] - 1
        sig = sig.merge(o, on=["account_id", "sig_ts", "symbol"], how="left")
        # entered trade
        te = TE[TE["run"] == run][["account_id", "signal_ts", "symbol", "R", "cost_R", "leverage", "roe",
                                   "exit_reason", "hold_min", "mfe_R", "mae_R", "stop_frac"]]
        te = te.rename(columns={"signal_ts": "sig_ts", "R": "tr_R", "cost_R": "tr_cost_R", "leverage": "tr_lev",
                                "roe": "tr_roe", "exit_reason": "tr_exit", "hold_min": "tr_hold",
                                "mfe_R": "tr_mfe_R", "mae_R": "tr_mae_R", "stop_frac": "tr_stop_frac"})
        sig = sig.merge(te.drop_duplicates(["account_id", "sig_ts", "symbol"]), on=["account_id", "sig_ts", "symbol"],
                        how="left")
        # skipped shadows
        shp = os.path.join(rd, "d3_shadows.csv")
        sig["sh_roe"] = np.nan
        sig["sh_resolved"] = np.nan
        if os.path.exists(shp):
            sh = pd.read_csv(shp, low_memory=False)
            sh = sh[sh["kind"] == "skipped"].drop_duplicates("key")
            parts = sh["key"].str.split("|", expand=True)
            sh = pd.DataFrame({"account_id": parts[1], "symbol": parts[2], "bar_close": pd.to_numeric(parts[3]),
                               "sh_roe2": pd.to_numeric(sh["roe"], errors="coerce").to_numpy(),
                               "sh_res2": sh["resolved"].to_numpy(), "sh_exit": sh["exit_reason"].to_numpy()})
            sig = sig.merge(sh, on=["account_id", "symbol", "bar_close"], how="left")
            sig["sh_roe"] = sig["sh_roe2"]
            sig["sh_resolved"] = sig["sh_res2"]
            sig = sig.drop(columns=["sh_roe2", "sh_res2"])
        # sizing of the shadow (fresh $5,000, the run's rule) -> R
        settings = S_walk if tag == "v3a" else S_q
        eng = PaperEngine(settings, brackets, symbol_specs=specs, book="size")
        sz_lev, sz_R = [], []
        for r in sig.itertuples(index=False):
            lev = Rv = np.nan
            if r.sh_roe == r.sh_roe and r.symbol in brackets and r.atr == r.atr and r.atr > 0:
                d = {"bar_close": int(r.bar_close), "timeframe": r.timeframe, "strategy": r.strategy,
                     "symbol": r.symbol, "side": int(r.side), "atr": float(r.atr), "ref_price": float(r.ref_price),
                     "ref_time": None, "delay_ms": None}
                if tag != "v3a" and r.q_tier is not None:
                    d["data"] = {"lev_group": "best" if r.q_tier == "best" else "normal"}
                try:
                    s = make_signal(d)
                    raw = float(s.meta["ref_price"])
                    fill = raw * (1 + s.side * settings.slippage_frac)
                    from dataclasses import replace
                    s = replace(s, stop_price=raw - s.side * float(s.meta["stop_dist"]))
                    dec = eng.policy.size(settings.initial_equity, s, fill, brackets[r.symbol], specs.get(r.symbol, {}))
                    if dec.ok:
                        lev = dec.leverage
                        Rv = float(r.sh_roe) * dec.margin / (dec.qty * abs(fill - s.stop_price))
                except Exception as exc:  # noqa: BLE001
                    checks.append({"run": tag, "sig_id": r.sig_id, "err": str(exc)[:100]})
            sz_lev.append(lev)
            sz_R.append(Rv)
        sig["sh_lev"] = sz_lev
        sig["sh_R"] = sz_R
        # trade-or-shadow outcome
        ent = sig["acct_status"] == "ENTERED"
        sig["R_ts"] = np.where(ent, sig["tr_R"], np.where(sig["acct_status"] == "SKIPPED", sig["sh_R"], np.nan))
        sig["R_ts_src"] = np.where(ent & sig["tr_R"].notna(), "trade",
                                   np.where((sig["acct_status"] == "SKIPPED") & sig["sh_R"].notna(), "shadow", ""))
        # replay
        rp = RP[RP["run"] == run]
        if len(rp):
            rp = rp[["sig_id", "status", "R", "flip_R", "flip_status", "mark_R", "fees", "funding", "qty", "entry_price",
                     "stop_initial", "leverage", "tier", "exit_reason", "hold_min", "mfe_R", "mae_R", "stop_frac",
                     "exit_time", "entry_time"]].rename(
                columns={"status": "rp_status", "R": "rp_R", "flip_R": "rp_flip_R", "flip_status": "rp_flip_status",
                         "mark_R": "rp_mark_R", "leverage": "rp_lev", "tier": "rp_tier", "exit_reason": "rp_exit",
                         "hold_min": "rp_hold", "mfe_R": "rp_mfe_R", "mae_R": "rp_mae_R", "stop_frac": "rp_stop_frac"})
            risk = rp["qty"] * (rp["entry_price"] - rp["stop_initial"]).abs()
            rp["rp_cost_R"] = (rp["fees"] + rp["funding"]) / risk
            rp = rp.drop(columns=["fees", "funding", "qty", "entry_price", "stop_initial"])
            sig = sig.merge(rp, on="sig_id", how="left")
        sig.insert(0, "run", tag)
        allrows.append(sig)
    D = pd.concat(allrows, ignore_index=True)
    # main outcome
    D["R"] = np.where(D["run"] == "v3a", D["R_ts"], np.where(D["rp_status"] == "TRADED", D["rp_R"], np.nan))
    D["R_src"] = np.where(D["run"] == "v3a", D["R_ts_src"], np.where(D["rp_status"] == "TRADED", "replay", ""))
    D["flip_R"] = np.where((D["rp_status"] == "TRADED") & (D["rp_flip_status"] == "TRADED"), D["rp_flip_R"], np.nan)
    # derived context
    D["stop_pct"] = 200 * D["atr"] / D["ref_price"]                 # 2 ATR stop as % of price
    D["cost_R_est"] = 2 * (TAKER + SLIP) * 100 / D["stop_pct"]      # round-trip cost share of the stop (R)
    D["kst_hour"] = ((D["bar_close"] // HOUR + 9) % 24).astype(int)
    D["kst_dow"] = (((D["bar_close"] + 9 * HOUR) // (24 * HOUR)) + 4) % 7   # 0 = Monday
    D["family"] = D["strategy"].map(FAM).fillna(pd.Series(np.where(D["kind"] == "random", "random", "other"), index=D.index))
    D["is_dup_stream"] = 0
    # signals of the same kind-group at the same bar/coin/tf: same side (consensus) and opposite side (conflict)
    D["kg"] = np.where(D["kind"].isin(["strategy", "ds200"]), D["kind"], "other")
    g = D.groupby(["run", "kg", "timeframe", "symbol", "bar_close", "side"]).size().rename("n_same")
    D = D.merge(g.reset_index(), on=["run", "kg", "timeframe", "symbol", "bar_close", "side"], how="left")
    g2 = g.reset_index()
    g2["side"] = -g2["side"]
    D = D.merge(g2.rename(columns={"n_same": "n_opp"}), on=["run", "kg", "timeframe", "symbol", "bar_close", "side"],
                how="left")
    D["n_opp"] = D["n_opp"].fillna(0).astype(int)
    D.to_csv(os.path.join(OUT, "signals_master.csv.gz"), index=False)
    # checks
    C = []
    for tag in ["v3a", "v3b", "v4"]:
        x = D[D["run"] == tag]
        C.append({"run": tag, "signals": len(x), "with_ctx": int((x["has_ctx"] == 1).sum()),
                  "R_n": int(x["R"].notna().sum()), "R_trade": int((x["R_src"] == "trade").sum()),
                  "R_shadow": int((x["R_src"] == "shadow").sum()), "R_replay": int((x["R_src"] == "replay").sum()),
                  "flip_n": int(x["flip_R"].notna().sum()),
                  "acct_status": json.dumps(x["acct_status"].value_counts(dropna=False).to_dict())})
    # conversion check (v4): skipped shadow R vs replay R on the same signals
    v = D[(D["run"] == "v4") & D["sh_R"].notna() & (D["rp_status"] == "TRADED")]
    lev_match = (v["sh_lev"] == v["rp_lev"]).mean() if len(v) else np.nan
    d = (v["sh_R"] - v["rp_R"]).abs()
    C.append({"run": "check_v4_shadowR_vs_replayR", "signals": len(v), "R_n": float(lev_match),
              "acct_status": json.dumps({"lev_match_share": float(lev_match),
                                         "median_abs_diff_R": float(d.median()) if len(d) else None,
                                         "share_abs_diff_lt_0.05R": float((d < 0.05).mean()) if len(d) else None,
                                         "corr": float(np.corrcoef(v["sh_R"], v["rp_R"])[0, 1]) if len(v) > 2 else None,
                                         "mean_sh_R": float(v["sh_R"].mean()), "mean_rp_R": float(v["rp_R"].mean())})})
    # v3a: fresh-account sizing vs the real entered trades' leverage (scale-invariant except brackets)
    rows = []
    for tag in ["v3a"]:
        x = D[(D["run"] == tag) & (D["acct_status"] == "ENTERED")].copy()
        # size them as if a shadow (fresh) to compare leverage with the real trade
        settings = S_walk
        eng = PaperEngine(settings, brackets, symbol_specs=specs, book="size")
        from dataclasses import replace
        ok = 0
        nn = 0
        for r in x.itertuples(index=False):
            if r.tr_lev != r.tr_lev or r.symbol not in brackets:
                continue
            d = {"bar_close": int(r.bar_close), "timeframe": r.timeframe, "strategy": r.strategy, "symbol": r.symbol,
                 "side": int(r.side), "atr": float(r.atr), "ref_price": float(r.ref_price), "ref_time": None,
                 "delay_ms": None}
            s = make_signal(d)
            raw = float(s.meta["ref_price"])
            fill = raw * (1 + s.side * settings.slippage_frac)
            s = replace(s, stop_price=raw - s.side * float(s.meta["stop_dist"]))
            dec = eng.policy.size(settings.initial_equity, s, fill, brackets[r.symbol], specs.get(r.symbol, {}))
            nn += 1
            ok += int(dec.ok and dec.leverage == r.tr_lev)
        C.append({"run": "check_v3a_fresh_sizing_lev_eq_trade_lev", "signals": nn, "R_n": ok / max(nn, 1)})
    pd.DataFrame(C).to_csv(os.path.join(OUT, "build_checks.csv"), index=False)
    if checks:
        pd.DataFrame(checks).to_csv(os.path.join(OUT, "build_errors.csv"), index=False)
    print(pd.DataFrame(C).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
