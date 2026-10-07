#!/usr/bin/env python3
"""Assemble lens2_cost_model.json from the cost-model outputs (no API calls).

    python3 -P assemble.py <work_dir> <out_json>
"""
import os
import sys
import json
import numpy as np
import pandas as pd

W = None


def P(name):
    return os.path.join(W, name)


def main():
    global W
    W, out_json = sys.argv[1:3]
    sc = pd.read_csv(P("scenarios.csv"))
    pc = json.load(open(P("per_call_costs.json")))
    lv = pd.read_csv(P("live_vs_5y.csv"))
    tcl = pd.read_csv(P("trader_calls_live.csv"))
    per = pd.read_csv(P("calls_5y_per_strategy.csv"))
    rates = pd.read_csv(P("rates_strategy_tf.csv"))
    mt = pd.read_csv(P("move_threshold.csv")).set_index("timeframe")
    scr = json.load(open(P("outscreens/screens_measure.json")))
    z = np.load(P("calls_5y_daily.npz"))

    base = sc[(sc.lang == "ko") & (sc.screen_scale == 1.0) & (sc.thinking == "mid") & (sc.hold_model == "sonnet") & (sc.pe == 1.0)]

    def g(df, **kw):
        m = df
        for k, v in kw.items():
            m = m[m[k] == v]
        assert len(m) == 1, (kw, len(m))
        return m.iloc[0]

    # ---------------------------------------------------------------- live-based monthly (current quiet market)
    v4 = tcl[(tcl.run == "v4")]
    ce = pc["ko|heavy1.0|sonnet|mid|entry"]["usd"]
    chh = pc["ko|heavy1.0|sonnet|mid|hold"]["usd"]
    ceo = pc["ko|heavy1.0|opus|mid|entry"]["usd"]
    cho = pc["ko|heavy1.0|opus|mid|hold"]["usd"]
    mkt_tok = pc["ko|heavy1.0|sonnet|mid|entry"]["cached_in"] - json.load(open(P("outscreens/screens_measure.json")))["screens"]["S1_entry_S2_ST_ROC_15m|ko"]["instructions"]["tok_mid"]
    live_rows = []
    for setup in "ABC":
        d = v4[v4.setup == setup]
        for mode in ("switch", "ignore"):
            for pol in ("P1", "P2", "P3", "P4"):
                tot = d[f"live_{mode}_{pol}"]
                ent = d.entry_pd + (d.switch_pd if mode == "switch" else 0)
                hold = tot - ent
                e_med, h_med = float(ent.median()), float(hold.median())
                for n in (10, 20, 30):
                    for opus in (False, True):
                        day = n * (e_med * ce + h_med * chh)
                        calls = n * (e_med + h_med)
                        day += min(calls, 192) * mkt_tok * (2.5 - 0.2) / 1e6
                        if opus:
                            day += 5 * (e_med * ceo + h_med * cho)
                        r5 = g(base, n_traders=n, setup=setup, hold_policy=pol, signals_while_holding=mode, opus5=opus)
                        ratio = r5.p90_day_x30 / r5.mean_month
                        live_rows.append({"n_traders": n, "setup": setup, "hold_policy": pol, "signals_while_holding": mode,
                                          "opus5": opus, "trader_calls_day_median": round(e_med + h_med, 1),
                                          "entry_type_calls": round(e_med, 1), "hold_calls": round(h_med, 1),
                                          "live_mean_month": round(30 * day, 1),
                                          "live_p90_day_x30": round(30 * day * ratio, 1),
                                          "y5_mean_month": r5.mean_month, "y5_p90_day_x30": r5.p90_day_x30})
    live_sc = pd.DataFrame(live_rows)
    live_sc.to_csv(P("scenarios_live_basis.csv"), index=False)

    # ---------------------------------------------------------------- fit $500 (Opus 5 included, KO, mid thinking)
    fit = []
    for r in live_sc[live_sc.opus5].itertuples():
        r5 = g(base, n_traders=r.n_traders, setup=r.setup, hold_policy=r.hold_policy, signals_while_holding=r.signals_while_holding, opus5=True)
        fit.append({"n": r.n_traders, "setup": r.setup, "policy": r.hold_policy, "mode": r.signals_while_holding,
                    "y5_mean": r5.mean_month, "y5_p90day": r5.p90_day_x30, "live_mean": r.live_mean_month,
                    "live_p90day": r.live_p90_day_x30,
                    "fits_all": bool(max(r5.p90_day_x30, r.live_p90_day_x30) <= 500),
                    "fits_mean_only": bool(max(r5.mean_month, r.live_mean_month) <= 500)})
    fit = pd.DataFrame(fit)
    fit.to_csv(P("fit_500.csv"), index=False)

    # ---------------------------------------------------------------- levers for reference config
    ref = dict(n_traders=30, setup="B", hold_policy="P4", signals_while_holding="switch", opus5=True)
    r0 = g(base, **ref).mean_month
    lev = []

    def add(name, val, note=""):
        lev.append({"lever": name, "mean_month": round(float(val), 1), "saving": round(float(r0 - val), 1), "note": note})
    add("reference: 30 Sonnet + 5 Opus, setup B, P4 (30m + events), switch calls", r0)
    add("signals while holding ignored (no switch calls)", g(base, **{**ref, "signals_while_holding": "ignore"}).mean_month)
    add("holding checks only every 30 min (P2)", g(base, **{**ref, "hold_policy": "P2"}).mean_month)
    add("holding checks only on events (P3)", g(base, **{**ref, "hold_policy": "P3"}).mean_month)
    p2 = g(base, **{**ref, "hold_policy": "P2"}).mean_month
    p4 = r0
    add("P4 with move trigger 1.0R instead of 0.5R (approx.)", p2 + (p4 - p2) * float(mt.loc["15m", "per_hour_1.0"] / mt.loc["15m", "per_hour_0.5"]),
        "event part scaled by the live 1R/0.5R event ratio (15m)")
    add("drop the 5 Opus twins", g(base, **{**ref, "opus5": False}).mean_month)
    add("Haiku first for holding checks (20% escalated)", g(sc[(sc.lang == "ko") & (sc.screen_scale == 1.0) & (sc.thinking == "mid") & (sc.hold_model == "haiku") & (sc.pe == 1.0)], **ref).mean_month)
    add("English keys instead of Korean labels", g(sc[(sc.lang == "en") & (sc.screen_scale == 1.0) & (sc.thinking == "mid") & (sc.hold_model == "sonnet") & (sc.pe == 1.0)], **ref).mean_month)
    add("thinking low (entry ~300, hold ~100 tokens)", g(sc[(sc.lang == "ko") & (sc.screen_scale == 1.0) & (sc.thinking == "low") & (sc.hold_model == "sonnet") & (sc.pe == 1.0)], **ref).mean_month)
    add("thinking high (entry ~2000, hold ~800 tokens) [cost increase]", g(sc[(sc.lang == "ko") & (sc.screen_scale == 1.0) & (sc.thinking == "high") & (sc.hold_model == "sonnet") & (sc.pe == 1.0)], **ref).mean_month)
    add("screen 1.5x larger instructions/card/journal [cost increase]", g(sc[(sc.lang == "ko") & (sc.screen_scale == 1.5) & (sc.thinking == "mid") & (sc.hold_model == "sonnet") & (sc.pe == 1.0)], **ref).mean_month)
    add("setup A (15m/30m entries only)", g(base, **{**ref, "setup": "A"}).mean_month)
    add("20 traders instead of 30", g(base, **{**ref, "n_traders": 20}).mean_month)
    add("AI skips half the signals (pe 0.5)", g(sc[(sc.lang == "ko") & (sc.screen_scale == 1.0) & (sc.thinking == "mid") & (sc.hold_model == "sonnet") & (sc.pe == 0.5)], **ref).mean_month)
    levers = pd.DataFrame(lev)
    levers.to_csv(P("levers.csv"), index=False)

    # recommended cheap-but-sensible configs
    cfg_rows = []
    for n, setup, pol, mode, hm, think in [(30, "C", "P4", "ignore", "haiku", "mid"), (30, "C", "P2", "ignore", "sonnet", "mid"),
                                           (30, "C", "P3", "ignore", "sonnet", "mid"), (30, "A", "P2", "ignore", "sonnet", "mid"),
                                           (20, "C", "P4", "switch", "sonnet", "mid"), (10, "C", "P4", "switch", "sonnet", "mid"),
                                           (30, "C", "P4", "ignore", "sonnet", "high"), (30, "C", "P2", "ignore", "sonnet", "high"), (30, "C", "P4", "switch", "sonnet", "low")]:
        m = sc[(sc.lang == "ko") & (sc.screen_scale == 1.0) & (sc.thinking == think) & (sc.hold_model == hm) & (sc.pe == 1.0)]
        r = g(m, n_traders=n, setup=setup, hold_policy=pol, signals_while_holding=mode, opus5=True)
        cfg_rows.append({"n": n, "setup": setup, "policy": pol, "mode": mode, "hold_model": hm, "thinking": think,
                         "mean": r.mean_month, "p90day_x30": r.p90_day_x30, "max30d": r.max_30d_window,
                         "fits_500_p90": "yes" if r.p90_day_x30 <= 500 else "no"})
    cfgs = pd.DataFrame(cfg_rows)

    # ---------------------------------------------------------------- strategy notes: calls/day per strategy
    notes = []
    p5 = per[(per.pe == 1.0)]
    for s in sorted(per.strategy.unique()):
        for tf in ["15m", "30m", "1h", "4h"]:
            rr = rates[(rates.strategy == s) & (rates.timeframe == tf)]
            if rr.empty:
                continue
            rr = rr.iloc[0]
            nums = {"live_v3b_signals_per_day": None if pd.isna(rr.live_v3b_per_day) else round(rr.live_v3b_per_day, 2),
                    "live_v4_signals_per_day": None if pd.isna(rr.live_v4_per_day) else round(rr.live_v4_per_day, 2),
                    "live_v4_bundles_per_day": None if pd.isna(rr.live_v4_bundles_per_day) else round(rr.live_v4_bundles_per_day, 2),
                    "y5_signals_per_day": round(rr.y5_signals_per_day, 2), "y5_bundles_per_day": round(rr.y5_bundles_per_day, 2)}
            notes.append({"strategy": s, "timeframe": tf, "grade": "rate", "numbers": nums,
                          "note": "signals = SUBMITTED on 6 tradable coins; bundle = one call per bar-close moment (coins bundled); 5y = Binance rebuild 2021-08..2026-09"})
        for setup in ("A", "B"):
            x = p5[(p5.strategy == s) & (p5.setup == setup)]
            if x.empty:
                continue
            nums = {}
            for mode in ("switch", "ignore"):
                for pol in ("P1", "P2", "P3", "P4"):
                    y = x[(x["mode"] == mode) & (x.policy == pol)].iloc[0]
                    nums[f"y5_{mode}_{pol}_mean"] = round(y.total_mean, 1)
                    nums[f"y5_{mode}_{pol}_p90"] = round(y.total_p90, 1)
            y = x[(x["mode"] == "ignore") & (x.policy == "P2")].iloc[0]
            nums["y5_entry_calls"] = round(y.entry_calls_mean, 2)
            nums["y5_trades_per_day"] = round(y.trades_per_day, 2)
            nums["y5_occupancy"] = round(y.occupancy, 2)
            lvx = tcl[(tcl.strategy == s) & (tcl.setup == setup)]
            for run in ("v3b", "v4"):
                q = lvx[lvx.run == run]
                if len(q):
                    nums[f"live_{run}_switch_P4"] = round(float(q.live_switch_P4.iloc[0]), 1)
                    nums[f"live_{run}_ignore_P2"] = round(float(q.live_ignore_P2.iloc[0]), 1)
            tot = nums["y5_switch_P4_mean"]
            grade = "rare" if tot < 5 else ("light" if tot < 30 else ("typical" if tot < 50 else "heavy"))
            notes.append({"strategy": s, "timeframe": "setup " + setup + (" (15m+30m)" if setup == "A" else " (15m/30m/1h/4h)"),
                          "grade": grade, "numbers": nums,
                          "note": f"AI calls per trader-day, one position at a time, AI enters every signal (pe 1). {grade}: switch+P4 mean {tot}/day"})
    # DeepSeek: live only
    for s in sorted(tcl[tcl.kind == "ds200"].strategy.unique()):
        q = tcl[(tcl.strategy == s) & (tcl.setup == "A") & (tcl.run == "v4")]
        if q.empty:
            continue
        q = q.iloc[0]
        nums = {"live_v4_switch_P4": round(q.live_switch_P4, 1), "live_v4_ignore_P2": round(q.live_ignore_P2, 1),
                "live_v4_entry_calls": round(q.entry_pd, 2), "live_v4_switch_calls": round(q.switch_pd, 2),
                "live_days": round(q.days, 2)}
        for tf in ["15m", "30m", "1h", "4h"]:
            rr = rates[(rates.strategy == s) & (rates.timeframe == tf)]
            if len(rr):
                nums[f"live_v4_signals_per_day_{tf}"] = None if pd.isna(rr.iloc[0].live_v4_per_day) else round(rr.iloc[0].live_v4_per_day, 2)
                nums[f"y5_trades_per_day_{tf}"] = None if pd.isna(rr.iloc[0].y5_ds_trades_per_day_own_exits) else round(rr.iloc[0].y5_ds_trades_per_day_own_exits, 2)
        notes.append({"strategy": s, "timeframe": "setup A (15m+30m), DeepSeek", "grade": "live-only",
                      "numbers": nums, "note": "1.5 live days only; 5y = DeepSeek trades/day with its own exits (not a call rate)"})

    # ---------------------------------------------------------------- key numbers
    s1 = scr["screens"]["S1_entry_S2_ST_ROC_15m|ko"]
    s1e = scr["screens"]["S1_entry_S2_ST_ROC_15m|en"]
    s2 = scr["screens"]["S2_entry_bundle_F6_VWAP_CROSS|ko"]
    s3 = scr["screens"]["S3_hold_N24_DMI|ko"]
    s3e = scr["screens"]["S3_hold_N24_DMI|en"]
    lv5 = lv.set_index(["source", "kind", "setup"])

    def L(src, kind, setup, col):
        return round(float(lv5.loc[(src, kind, setup), col]), 2 if col == "occupancy" else 1)

    rates_sum = rates[rates.kind == "strategy"].groupby("timeframe")[["live_v3b_per_day", "live_v4_per_day", "y5_signals_per_day", "live_v4_bundles_per_day", "y5_bundles_per_day"]].sum().round(0)
    ds_sum = rates[rates.kind == "ds200"].groupby("timeframe")[["live_v4_per_day", "live_v4_bundles_per_day"]].sum().round(0)
    ref_live = live_sc[(live_sc.n_traders == 30) & (live_sc.setup == "B") & (live_sc.hold_policy == "P4") & (live_sc.signals_while_holding == "switch") & (live_sc.opus5)].iloc[0]
    fits_all = fit[fit.fits_all]
    fits_mean = fit[fit.fits_mean_only & ~fit.fits_all]

    fp_rows = []
    for (n, mode), d in fit.groupby(["n", "mode"]):
        row = {"traders": n, "while holding": mode}
        for pol in ["P1", "P2", "P3", "P4"]:
            a = d[(d.policy == pol) & d.fits_all].setup.tolist()
            m = d[(d.policy == pol) & d.fits_mean_only & ~d.fits_all].setup.tolist()
            row[pol] = (" ".join(a) if a else "-") + (f" (mean only: {' '.join(m)})" if m else "")
        fp_rows.append(row)
    fit_piv = pd.DataFrame(fp_rows)
    strat_tab = per[(per.pe == 1.0) & (per.setup == "A")].pivot_table(index="strategy", columns=["mode", "policy"], values="total_mean")
    strat_tab = pd.DataFrame({"strategy": strat_tab.index, "5y switch P4": strat_tab[("switch", "P4")].values,
                              "5y switch P2": strat_tab[("switch", "P2")].values, "5y ignore P2": strat_tab[("ignore", "P2")].values,
                              "5y ignore P3": strat_tab[("ignore", "P3")].values})
    lq = tcl[(tcl.setup == "A") & (tcl.run == "v4")].set_index("strategy")
    strat_tab["live v4 switch P4"] = strat_tab.strategy.map(lq.live_switch_P4)
    strat_tab["live v4 ignore P2"] = strat_tab.strategy.map(lq.live_ignore_P2)
    strat_tab = strat_tab.sort_values("5y switch P4", ascending=False)

    def fl(df):
        return "; ".join(f"{r.n}x{r.setup}/{r.policy}/{r.mode} (5y {r.y5_mean:.0f}/{r.y5_p90day:.0f}, live {r.live_mean:.0f}/{r.live_p90day:.0f})" for r in df.itertuples())

    findings = []

    def F(i, claim, ev, conf, imp):
        findings.append({"id": i, "claim": claim, "evidence": ev, "confidence": conf, "implication": imp})

    F("C1", "Signal rates are high and stable: the 36 strategies on the 6 tradable coins submit about 570 (15m), 290 (30m), 190 (1h) and 40 (4h) signals a day live, the same as the 5-year rebuild; DeepSeek 44 adds about 780 / 410 / 245 / 84.",
      f"rates_strategy_tf.csv: ours live v3b {rates_sum.live_v3b_per_day.to_dict()}, v4 {rates_sum.live_v4_per_day.to_dict()}, 5y {rates_sum.y5_signals_per_day.to_dict()}; bundled per bar-close moment v4 {rates_sum.live_v4_bundles_per_day.to_dict()} vs 5y {rates_sum.y5_bundles_per_day.to_dict()}; DeepSeek v4 {ds_sum.live_v4_per_day.to_dict()}",
      "high", "Raw signal counts are not the cost driver once a trader holds one position at a time; per-trader call counts are.")
    F("C2", "One position at a time caps entry calls at about 4-5 per trader-day (5y median), but a trader is in a position 43-54% of the time (5y) or 53-73% (live, quiet market), so most calls are holding checks and switch decisions.",
      f"live_vs_5y.csv: 5y median entry calls A {L('5y_sim','strategy','A','entry_pd')}, trades {L('5y_sim','strategy','A','trades_pd')}, occupancy A {L('5y_sim','strategy','A','occupancy')} / B {L('5y_sim','strategy','B','occupancy')}; live v4 ours occupancy A {L('live_v4','strategy','A','occupancy')} / B {L('live_v4','strategy','B','occupancy')}, ds200 A {L('live_v4','ds200','A','occupancy')}",
      "high", "Budget by holding-check policy first, not by signal counts.")
    F("C3", "Per-trader calls/day (median strategy, setup A, AI enters every signal): switch mode 24-39 (5y) / 28-60 (live, ours and DeepSeek) depending on the holding policy; ignore mode 20-38 (5y) / 19-58 (live). P4 (30-minute checks + events, the PLAN_ATTACH draft) is the most expensive: about 39 (5y) and 49-60 (live) calls per trader-day.",
      f"live_vs_5y.csv 5y A switch P1/P2/P3/P4 {L('5y_sim','strategy','A','switch_P1')}/{L('5y_sim','strategy','A','switch_P2')}/{L('5y_sim','strategy','A','switch_P3')}/{L('5y_sim','strategy','A','switch_P4')}, ignore {L('5y_sim','strategy','A','ignore_P1')}/{L('5y_sim','strategy','A','ignore_P2')}/{L('5y_sim','strategy','A','ignore_P3')}/{L('5y_sim','strategy','A','ignore_P4')}; live v4 ours switch {L('live_v4','strategy','A','switch_P1')}/{L('live_v4','strategy','A','switch_P2')}/{L('live_v4','strategy','A','switch_P3')}/{L('live_v4','strategy','A','switch_P4')}, ds200 switch P4 {L('live_v4','ds200','A','switch_P4')}",
      "medium", "Live (quiet market) runs ~15-50% above the 5-year emulation because positions last longer when ATR is small (the ROE ladder needs a larger move in ATR terms). Plan with the live numbers as the upper case.")
    F("C4", "A '>= 0.5R move' trigger is not rare: on 15m positions it fires about 1.8 times per hour held (1m bars), almost as often as a 15m bar-close check; 1.0R fires 0.46 per hour (-74%).",
      f"move_threshold.csv (live replay, {int(mt.loc['15m','n_trades'])} 15m trades): per hour 0.5R {mt.loc['15m','per_hour_0.5']:.2f}, 0.75R {mt.loc['15m','per_hour_0.75']:.2f}, 1.0R {mt.loc['15m','per_hour_1.0']:.2f}; 30m 0.5R {mt.loc['30m','per_hour_0.5']:.2f}, 1h {mt.loc['1h','per_hour_0.5']:.2f}, 4h {mt.loc['4h','per_hour_0.5']:.2f}",
      "high", "Use 1.0R (or 1 ATR of the held tf with a 15-minute cooldown) for event wakes, or route move wakes to Haiku.")
    F("C5", f"A realistic screen is about 13.5-14.5k characters: about 6.2-6.6k tokens with Korean labels (range 5.1-7.3k) and 5.1-5.4k with English keys (4.5-6.2k). The cacheable prefix (instructions + market bundle) is about 5.0k of 6.3k Korean tokens (~80%); the variable part (card + journal + wake) is about 1.1-1.4k.",
      f"outscreens/screens_measure.json: S1 KO total mid {s1['total']['tok_mid']} (low {s1['total']['tok_low']}, high {s1['total']['tok_high']}; instr {s1['instructions']['tok_mid']}, market {s1['market']['tok_mid']}, card {s1['card']['tok_mid']}, journal {s1['journal']['tok_mid']}, wake {s1['wake']['tok_mid']}); S1 EN {s1e['total']['tok_mid']}; S2 (5-signal bundle) KO {s2['total']['tok_mid']}; S3 hold KO {s3['total']['tok_mid']}, EN {s3e['total']['tok_mid']}; market bundle EN JSON {s1e['market_json']['tok_mid']} vs EN rows {s1e['market']['tok_mid']}",
      "medium", "Token counts are estimates (ASCII/3.2 + Hangul x0.95; no tokenizer offline). Measure with usage fields in the pilot. English keys save ~15% input but input is only ~30% of the bill.")
    F("C6", f"Output (thinking + answer) dominates the per-call price: a Sonnet entry decision costs about ${pc['ko|heavy1.0|sonnet|mid|entry']['usd']:.4f} at ~900 output tokens (low ${pc['ko|heavy1.0|sonnet|low|entry']['usd']:.4f}, high ${pc['ko|heavy1.0|sonnet|high|entry']['usd']:.4f}); a holding check ${pc['ko|heavy1.0|sonnet|mid|hold']['usd']:.4f} (low ${pc['ko|heavy1.0|sonnet|low|hold']['usd']:.4f}, high ${pc['ko|heavy1.0|sonnet|high|hold']['usd']:.4f}); Opus about 1.9x; Haiku hold ${pc['ko|heavy1.0|haiku|mid|hold']['usd']:.4f}.",
      "per_call_costs.json; cached input 5,058 tokens at $0.20/M, uncached ~1.1-1.4k at $2/M, output at $10/M (Sonnet).",
      "medium", "Thinking length is the largest unknown (3x range in the total). Fix effort per call type and cap max_tokens; measure output_tokens in the pilot before locking the budget.")
    F("C7", f"Reference plan (30 Sonnet traders, setup B, P4 holding checks, switch calls, + 5 Opus twins, Korean, mid thinking) costs about ${r0:.0f}/month on 5-year rates and ${ref_live.live_mean_month:.0f}/month on live (quiet-market) rates; busy days (p90) about +15%.",
      f"scenarios.csv / scenarios_live_basis.csv: 5y mean {r0:.0f}, p90-day x30 {g(base, **ref).p90_day_x30:.0f}, p90 30-day window {g(base, **ref).p90_30d_window:.0f}, max 30-day window {g(base, **ref).max_30d_window:.0f}; live mean {ref_live.live_mean_month:.0f}, live p90-day x30 {ref_live.live_p90_day_x30:.0f}",
      "medium", "The draft plan does not fit $500 reliably; it needs one or two cuts.")
    F("C8", "Market activity moves the bill only a little: with one position per trader, calls are bounded by clock time, so the 90th-percentile day is about 1.15x the mean day and the worst 30-day window in five years about 1.14x the mean month (30 traders).",
      "scenarios.csv: p90_day_x30 / mean_month 1.08-1.21 (median 1.16); max_30d_window / mean_month 1.06-1.21",
      "high", "Set the daily cap at ~1.25x the planned mean; budget risk is in thinking tokens and policy choice, not in volatile markets. A shock day can still exceed the cap for a few hours.")
    F("C9", "Combinations that fit $500 including 5 Opus twins under both 5-year and live rates at the p90 day (Korean screen, mid thinking): 10 traders: every setup x policy x mode; 20 traders: every combination in ignore mode, and in switch mode P2 or P3 (P1 only for B/C; P4 fits only on an average month); 30 traders: only ignore mode with P2 (30-minute checks) or P3 (event checks), any setup (P1-ignore and P2/P3-switch fit only on an average month; P4 never).",
      "fit_500.csv (KO screen, mid thinking, Sonnet holding checks; values = mean / p90-day x30)",
      "medium", "With 30 traders, 'ignore new signals while holding' plus either 30-minute checks or event-only checks is the main way to stay under $500; with switch calls, only 10-20 traders fit. If the analyst, coach and re-asks (~$55/month) come out of the same $500, plan the traders at <= ~$445.")
    F("C10", "What to cut first, by saving per dollar of lost information: (1) the 0.5R move trigger -> 1.0R or Haiku; (2) switch calls while holding (ignore new signals except opposite signals on the held coin); (3) the 30-minute schedule when events are on; (4) Opus twins to 3 or to entry calls only; then thinking caps, then trader count.",
      "levers.csv: " + "; ".join(f"{r.lever}: {r.mean_month:.0f} (saves {r.saving:.0f})" for r in levers.itertuples()),
      "medium", "Keep 30 traders and the 15m/30m(+1h) entries; cut the holding-check frequency, which the owners' own data says is noise (most move wakes are ordinary 1-ATR wiggles).")
    F("C11", "Letting the AI skip half the signals (pe 0.5) lowers the bill a little (fewer positions to check) rather than raising it.",
      "scenarios.csv (30 traders, Opus 5): pe 0.5 vs 1.0 mean month e.g. B/P4/switch " + f"{g(sc[(sc.lang=='ko')&(sc.screen_scale==1.0)&(sc.thinking=='mid')&(sc.hold_model=='sonnet')&(sc.pe==0.5)], **ref).mean_month:.0f} vs {r0:.0f}",
      "medium", "Skip rates within the pilot band (15-85%) do not threaten the budget.")

    limits = [
        "No tokenizer was available offline and no API was called: token counts are character-based estimates (low/mid/high) using the repo's own conservative rule as the high end. Korean text in particular may tokenize differently on Sonnet 5.5; measure usage.input_tokens / cache_read_input_tokens / output_tokens in the pilot.",
        "Thinking tokens are assumed (entry 300/800/2000, holding 100/300/800 for low/mid/high). They are the largest driver of the bill and are unknown until measured.",
        "Holding times use rule exits (5-year: a house-exit emulation on the trade's own bars at 30x / 20x; live: the validated replay). AI early exits would shorten holds (fewer checks) but add entries; not modelled.",
        "The 5-year emulation gives shorter holds than live (5y median 52-82 min vs live 15m median 92 min) because the ROE ladder triggers sooner when ATR is large; live (quiet market, 2.2 days, holds truncated at run end) is the upper case. Truth for the coming month is likely between.",
        "Live rates rest on 0.7 (v3b) and 1.5 (v4) days; per-strategy live numbers are noisy. DeepSeek traders have live rates only (no 5-year call simulation); they were treated as drawn from the same per-trader distribution (their live per-trader calls are similar to ours).",
        "Scenario trader sets are random draws of 10/20/30 from the 32 non-rare core strategies; the final AI-trader list is not chosen yet. A list of busy strategies (S2_ST_ROC, N04, N23, N22, N18, N17) costs up to ~2.4x the median trader.",
        "Market-bundle caching assumes one shared 15-minute version written about twice per window; the card sits after the market bundle (design 6-4 order), so it is never cached. A per-trader second breakpoint or a different order could change input cost by a few percent only.",
        "Prices are from the owners' design doc (AIBOT_DESIGN_KO_v2 14-3) and the claude-api reference cached 2026-09-25: Sonnet 5.5 $2/$10, cache read $0.20; Opus 5.5 $4/$20, cache read $0.20; Haiku 4.5 $1/$5, cache read assumed $0.10, minimum cacheable prefix 4,096 tokens on Haiku. Re-check before launch.",
        "Not included: market analyst (design ~$20/month), coach/night journal (~$15), re-asks and format failures (~$20), the separate server (~$40), pre-launch tests. Macro releases add only ~0.25 calls per trader-day (4 releases / 30 days).",
        "Funding-settlement wakes (design v2: 10 minutes before each 8h settlement while holding) are not in P1-P4; they would add about 3 x occupancy calls per trader-day (~1.5-2).",
    ]

    files = {k: os.path.join(W, v) for k, v in {
        "sim5y_script": "sim5y.py", "live_sim_script": "live_sim.py", "screens_script": "screens.py",
        "cost_model_script": "cost_model.py", "rates_script": "rates_table.py", "assemble_script": "assemble.py",
        "move_threshold_script": "move_threshold.py", "summarize5y_script": "summarize5y.py",
        "sim5y_outputs": "out5y", "per_strategy_5y": "calls_5y_per_strategy.csv", "daily_5y": "calls_5y_daily.npz",
        "live_calls": "outlive/live_calls.csv", "live_rates": "outlive/live_rates.csv", "live_move_calib": "outlive/live_move_calib.csv",
        "trader_calls_live": "trader_calls_live.csv", "live_vs_5y": "live_vs_5y.csv", "rates_strategy_tf": "rates_strategy_tf.csv",
        "trader_calls_per_strategy": "trader_calls_per_strategy.csv", "move_threshold": "move_threshold.csv",
        "screens_dir": "outscreens", "screens_measure": "outscreens/screens_measure.json",
        "instructions_ko": "screen_parts/instr_ko.txt", "instructions_en": "screen_parts/instr_en.txt",
        "per_call_costs": "per_call_costs.json", "scenarios_5y": "scenarios.csv", "scenarios_live": "scenarios_live_basis.csv",
        "fit_500": "fit_500.csv", "levers": "levers.csv"}.items()}

    # ---------------------------------------------------------------- report section
    def tbl(df, cols, fmt=None):
        h = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
        for r in df[cols].itertuples(index=False):
            h += "| " + " | ".join(str(round(x, 1)) if isinstance(x, float) else str(x) for x in r) + " |\n"
        return h

    main_tab = base[(base.opus5) & (base.hold_policy.isin(["P1", "P2", "P3", "P4"]))][
        ["n_traders", "setup", "hold_policy", "signals_while_holding", "calls_day_mean", "mean_month", "p90_day_x30"]].copy()
    lsx = live_sc[live_sc.opus5][["n_traders", "setup", "hold_policy", "signals_while_holding", "live_mean_month", "live_p90_day_x30"]]
    main_tab = main_tab.merge(lsx, on=["n_traders", "setup", "hold_policy", "signals_while_holding"])
    main_tab["calls_day_mean"] = main_tab.calls_day_mean.round(0)
    main_tab = main_tab[(main_tab.n_traders == 30) | ((main_tab.setup == "C") & (main_tab.hold_policy.isin(["P2", "P3", "P4"])))]
    main_tab = main_tab.sort_values(["n_traders", "setup", "hold_policy", "signals_while_holding"])
    main_tab.columns = ["traders", "setup", "hold", "while holding", "calls/day (5y)", "5y mean $", "5y p90-day $", "live mean $", "live p90-day $"]

    md = f"""## AI cost model for AI traders attached to the rule bot (no API calls)

**Bottom line.** The draft plan (30 Sonnet traders, 15m/30m/1h/4h entries, checks every 30 minutes plus event wakes, new signals while holding asked as switch decisions, plus 5 Opus twins) costs about **${r0:.0f}/month** on 5-year call rates and **${ref_live.live_mean_month:.0f}/month** on live (current quiet-market) rates, with Korean screens and mid thinking. A busy day (p90) runs about 15% higher. It does not reliably fit $500. Two cuts bring it under: ignore new signals while holding (except an opposite signal on the held coin), and raise the move trigger from 0.5R to 1.0R or send move wakes to Haiku. A safe 30-trader plan is setup C, new signals ignored while holding, and **either** 30-minute checks **or** event checks: about $270-360/month on average and $320-410 on a busy day, Opus twins included. That leaves room for the analyst, coach and re-asks (about $55, which the design budgets separately). Thinking length is the biggest unknown. If entry decisions think about 2,000 tokens instead of 800, even this plan goes over $500, so lock effort and max_tokens per call type and measure them in the pilot. **All prices must be re-checked in the Anthropic console before launch.**

### 1. How many decisions
- Signals (SUBMITTED, 6 tradable coins, per day). Our 36, live v4: {rates_sum.live_v4_per_day.to_dict()}. Five-year rebuild: {rates_sum.y5_signals_per_day.to_dict()}. DeepSeek 44, live v4: {ds_sum.live_v4_per_day.to_dict()}. Bundling the coins that close at the same moment into one call cuts these by about 30% (v4 ours {rates_sum.live_v4_bundles_per_day.to_dict()}).
- With **one position at a time**, a trader makes only about 4-5 entry calls a day (5y median), but it holds a position 43-54% of the day in the 5-year emulation and 53-73% live. While it holds, new signals are either **switch decisions** (still calls: about +5/day in the 5-year emulation, +9-13 live) or **ignored** (no call).
- Per-trader calls/day, median strategy, setup A (5y / live v4 ours):
  - switch mode: P1 bar close {L('5y_sim','strategy','A','switch_P1')} / {L('live_v4','strategy','A','switch_P1')}; P2 every 30m {L('5y_sim','strategy','A','switch_P2')} / {L('live_v4','strategy','A','switch_P2')}; P3 events {L('5y_sim','strategy','A','switch_P3')} / {L('live_v4','strategy','A','switch_P3')}; P4 30m + events {L('5y_sim','strategy','A','switch_P4')} / {L('live_v4','strategy','A','switch_P4')}
  - ignore mode: {L('5y_sim','strategy','A','ignore_P1')} / {L('live_v4','strategy','A','ignore_P1')}, {L('5y_sim','strategy','A','ignore_P2')} / {L('live_v4','strategy','A','ignore_P2')}, {L('5y_sim','strategy','A','ignore_P3')} / {L('live_v4','strategy','A','ignore_P3')}, {L('5y_sim','strategy','A','ignore_P4')} / {L('live_v4','strategy','A','ignore_P4')}
- The spread across strategies is wide: from about 6 (N03_ADX_GC) to 96 (N04_ST_KLINGER) calls per trader-day (5y, A, switch, P4). See strategy_notes.
- A move of 0.5R is an ordinary wiggle. On 15m positions it fires {mt.loc['15m','per_hour_0.5']:.2f} times per hour held; 1.0R fires {mt.loc['15m','per_hour_1.0']:.2f} times per hour.

### 2. Screen size (real export data; tokens are estimates)
| part | Korean labels (tokens, mid) | English keys (tokens, mid) | cached? |
|---|---|---|---|
| common instructions (6-3) | {s1['instructions']['tok_mid']} | {s1e['instructions']['tok_mid']} | yes, shared by all traders |
| market bundle: 6 coins x 15m/30m/1h/4h + daily + market data + analyst + releases | {s1['market']['tok_mid']} | {s1e['market']['tok_mid']} (JSON {s1e['market_json']['tok_mid']}) | yes, one 15-minute version shared |
| strategy card | {s1['card']['tok_mid']} | {s1e['card']['tok_mid']} | no (sits after the market bundle) |
| last 10 journal lines | {s1['journal']['tok_mid']} | {s1e['journal']['tok_mid']} | no |
| wake: 2-signal entry / 5-signal bundle / holding | {s1['wake']['tok_mid']} / {s2['wake']['tok_mid']} / {s3['wake']['tok_mid']} | {s1e['wake']['tok_mid']} / - / {s3e['wake']['tok_mid']} | no |
| **total** | **{s1['total']['tok_mid']}** (range {s1['total']['tok_low']}-{s1['total']['tok_high']}) | **{s1e['total']['tok_mid']}** ({s1e['total']['tok_low']}-{s1e['total']['tok_high']}) | ~80% cacheable |

The answer is about 80-100 tokens (entry) or 40 tokens (holding), plus thinking. Thinking is the unknown: we assumed 800 tokens for an entry decision and 300 for a holding check (mid).

### 3. Prices (re-check before launch)
Sonnet 5.5: $2 input / $10 output, cache read $0.20. Opus 5.5: $4 / $20, cache read $0.20. Haiku 4.5: $1 / $5 (cache read assumed $0.10; minimum cacheable prefix 4,096 tokens). Cache write costs 1.25x input (5-minute TTL). Per call (Korean, mid): Sonnet entry ${pc['ko|heavy1.0|sonnet|mid|entry']['usd']:.4f}, holding ${pc['ko|heavy1.0|sonnet|mid|hold']['usd']:.4f}; Opus entry ${pc['ko|heavy1.0|opus|mid|entry']['usd']:.4f}, holding ${pc['ko|heavy1.0|opus|mid|hold']['usd']:.4f}. About 70% of an entry call's price is output.

### 4. Monthly cost (with 5 Opus twins; Korean screen; mid thinking; Sonnet holding checks; AI enters every signal)
Setups: A = 15m/30m entries. B = 15m/30m/1h/4h entries. C = 15m/30m/1h, plus 4h only when the 2 ATR stop is within 3.2% (20x). Holding checks: P1 = every bar close of the held timeframe. P2 = every 30 minutes. P3 = events (0.5R move, other-timeframe same-coin signal, macro release). P4 = P2 + P3. "While holding": switch = new signals are asked as switch decisions; ignore = no call.

{tbl(main_tab, list(main_tab.columns))}
p90-day = the 90th-percentile day x 30 (busy-market stress). Over five years, the worst 30-day window was at most 1.21x the mean month.

### 5. What fits $500 (5 Opus twins included; Korean screen; mid thinking)
Each cell lists the setups whose p90 day x30 is at most $500 on both the 5-year and the live basis. "mean only" = fits on an average month, not on busy days.

{tbl(fit_piv, list(fit_piv.columns))}

### 6. What to cut first (reference: 30 traders, setup B, P4, switch, 5 Opus; ${r0:.0f}/month on 5-year rates)
{tbl(levers, ['lever', 'mean_month', 'saving'])}
Order of cuts:
1. Move wakes: raise the trigger to 1.0R, or send them to Haiku first.
2. Switch calls: wake a holding trader only for an opposite signal on the held coin (design v2 rule), not for every new signal.
3. Drop the fixed 30-minute check when event wakes are on, or keep the 30-minute check and drop the move trigger.
4. Opus twins: use 3 instead of 5, or ask Opus only on entry calls.
5. Cap thinking with effort settings (entry medium, holding low) and max_tokens.

Trader count and 15m/30m entries are the last things to cut. Thinking length can swing the total from about 0.7x to 1.8x of the mid case, so the pilot must measure output_tokens per call type before the budget is locked.

### 7. Calls per trader-day by strategy (setup A, AI enters every signal; 5-year mean and live v4)
{tbl(strat_tab.round(1), list(strat_tab.columns))}

### 8. Example configurations (5-year basis, 5 Opus twins included; mean / p90-day x30 / worst 30 days, $; not all fit)
{tbl(cfgs, ['n', 'setup', 'policy', 'mode', 'hold_model', 'thinking', 'mean', 'p90day_x30', 'max30d', 'fits_500_p90'])}
Not included in these totals: market analyst (~$20/month), coach and night journal (~$15), re-asks (~$20), the server (~$40, outside the AI budget).
"""
    out = {"findings": findings, "strategy_notes": notes, "files": files, "limits": limits, "report_section_md": md}
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("wrote", out_json, len(findings), len(notes))
    print(levers.to_string())
    print(fit[fit.fits_all].to_string())
    print(fit[fit.fits_mean_only & ~fit.fits_all].to_string())
    print(cfgs.to_string())
    print(ref_live)


if __name__ == "__main__":
    main()
