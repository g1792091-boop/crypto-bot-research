#!/usr/bin/env python3
"""Monthly AI cost scenarios for AI traders attached to the rule bot (no API calls).

    python3 -P cost_model.py <work_dir>

Reads <work_dir>/calls_5y_daily.npz + calls_5y_per_strategy.csv (summarize5y.py) and
<work_dir>/outscreens/screens_measure.json (screens.py). Writes scenarios.csv, per_call_costs.json.

PRICES ($ per million tokens; from docs/aibot/AIBOT_DESIGN_KO_v2.md 14-3 and the claude-api reference cached
2026-09-25; RE-CHECK IN THE CONSOLE BEFORE LAUNCH):
  Sonnet 5.5: input 2, output 10, cache read 0.20 (0.1x), cache write 5m 2.50 (1.25x), 1h 4.00 (2x)
  Opus 5.5:   input 4, output 20, cache read 0.20 (0.05x), cache write 5m 5.00, 1h 8.00
  Haiku 4.5:  input 1, output 5, cache read 0.10 (0.1x, assumed), write 5m 1.25; minimum cacheable prefix 4,096 tokens
Thinking tokens are billed as output. Screen order (6-4): [instructions][market bundle][card][journal][wake]:
  instructions: cache read on every call (shared by all traders; 1h TTL, re-written ~24x/day, negligible)
  market bundle: shared by all traders within one 15-minute version; each version is written once or twice
                 (WRITES_PER_VERSION) at 1.25x and read at 0.1x by every other call in the window
  card + journal + wake: uncached (card sits after the market bundle, so it cannot be cached across versions)
"""
import os
import sys
import json
import itertools
import numpy as np
import pandas as pd

PRICES = {
    "sonnet": {"in": 2.0, "out": 10.0, "cr": 0.20, "cw": 2.50},
    "opus": {"in": 4.0, "out": 20.0, "cr": 0.20, "cw": 5.00},
    "haiku": {"in": 1.0, "out": 5.0, "cr": 0.10, "cw": 1.25},
}
RARE = {"N14_ICHI_RSI", "N15_KC_AO", "S1_EMA_RSI_CHOP", "N21_ST_RSI_ADX"}  # PLAN_ATTACH 1-5: excluded (too rare)
VERSIONS_PER_DAY = 96
WRITES_PER_VERSION = 2
# output tokens: structured answer (measured, screens_measure.json) + thinking (assumed; adaptive thinking,
# effort medium for entry-type, low for holding checks). Haiku: no thinking (design 6-6), answer only.
THINK = {"low": {"entry": 300, "hold": 100}, "mid": {"entry": 800, "hold": 300}, "high": {"entry": 2000, "hold": 800}}
ANS = {"entry": 100, "hold": 45}
SUBSETS = 200


def tokens(work, lang="ko", level="tok_mid", heavy=1.0):
    m = json.load(open(os.path.join(work, "outscreens", "screens_measure.json")))["screens"]
    e1 = m[f"S1_entry_S2_ST_ROC_15m|{lang}"]
    e2 = m[[k for k in m if k.startswith("S2_entry") and k.endswith(lang)][0]]
    h = m[f"S3_hold_N24_DMI|{lang}"]
    t = {
        "instr": heavy * e1["instructions"][level],
        "market": e1["market"][level],
        "card": heavy * (e1["card"][level] + e2["card"][level] + h["card"][level]) / 3,
        "journal": heavy * e1["journal"][level],
        "wake_entry": (e1["wake"][level] + e2["wake"][level]) / 2,
        "wake_hold": h["wake"][level],
    }
    return t


def per_call(model, kind, t, think):
    p = PRICES[model]
    cached = t["instr"] + t["market"]
    unc = t["card"] + t["journal"] + (t["wake_entry"] if kind == "entry" else t["wake_hold"])
    if model == "haiku":
        out = ANS[kind]
        # the 4,096-token minimum: instructions + market (~4.5-5.7k) can cache only at a breakpoint after the market
        cr = p["cr"] if cached >= 4096 else p["in"]
    else:
        out = ANS[kind] + THINK[think][kind]
        cr = p["cr"]
    return (cached * cr + unc * p["in"] + out * p["out"]) / 1e6, {"cached_in": cached, "uncached_in": unc, "out": out}


def market_write_extra(total_calls_day, t, model="sonnet"):
    p = PRICES[model]
    writes = np.minimum(total_calls_day, VERSIONS_PER_DAY * WRITES_PER_VERSION)
    return writes * t["market"] * (p["cw"] - p["cr"]) / 1e6


def stats_month(daily_cost):
    roll = np.convolve(daily_cost, np.ones(30), "valid")
    return {"mean_month": 30 * daily_cost.mean(), "median_day_x30": 30 * np.median(daily_cost),
            "p90_day_x30": 30 * np.percentile(daily_cost, 90), "p90_30d_window": np.percentile(roll, 90),
            "max_30d_window": roll.max(), "last365_mean_month": 30 * daily_cost[-365:].mean()}


def main():
    work = sys.argv[1]
    z = np.load(os.path.join(work, "calls_5y_daily.npz"))
    per = pd.read_csv(os.path.join(work, "calls_5y_per_strategy.csv"))
    pool = sorted(s for s in per.strategy.unique() if s not in RARE)
    rng = np.random.default_rng(7)
    out_rows = []
    costs = {}
    for lang in ("ko", "en"):
        for heavy in (1.0, 1.5):
            t = tokens(work, lang, heavy=heavy)
            for model in ("sonnet", "opus", "haiku"):
                for think in THINK:
                    for kind in ("entry", "hold"):
                        c, parts = per_call(model, kind, t, think)
                        costs[f"{lang}|heavy{heavy}|{model}|{think}|{kind}"] = {"usd": c, **parts}
    with open(os.path.join(work, "per_call_costs.json"), "w") as fh:
        json.dump(costs, fh, indent=1)

    subsets = {n: [sorted(rng.choice(pool, n, replace=False)) for _ in range(SUBSETS)] for n in (10, 20, 30)}
    for n in (10, 20, 30):
        busiest = None
        for setup, pol, mode, pe in itertools.product("ABC", ["P1", "P2", "P3", "P4"], ["switch", "ignore"], [1.0, 0.5]):
            arr = {s: z[f"{s}|{setup}|{pe}|{mode}|{pol}"] for s in pool}
            means = {s: a.sum(0).mean() for s, a in arr.items()}
            top = sorted(pool, key=lambda s: -means[s])[:n]
            pre = {}
            for i, sub in enumerate(subsets[n] + [top]):
                E = sum(arr[s][0] for s in sub)
                H = sum(arr[s][1] for s in sub)
                mids = sorted(sub, key=lambda s: means[s])[len(sub) // 2 - 2: len(sub) // 2 + 3]
                E5 = sum(arr[s][0] for s in mids)
                H5 = sum(arr[s][1] for s in mids)
                pre[i] = (E, H, E5, H5)
            for lang, heavy, think, hold_model in [("ko", 1.0, "mid", "sonnet"), ("ko", 1.0, "low", "sonnet"),
                                                   ("ko", 1.0, "high", "sonnet"), ("en", 1.0, "mid", "sonnet"),
                                                   ("ko", 1.5, "mid", "sonnet"), ("ko", 1.0, "mid", "haiku")]:
                if (lang, heavy, think, hold_model) != ("ko", 1.0, "mid", "sonnet") and not (pol == "P4" or pol == "P2" or pol == "P3"):
                    continue
                t = tokens(work, lang, heavy=heavy)
                ce = per_call("sonnet", "entry", t, think)[0]
                if hold_model == "haiku":
                    # Haiku first, 20 % escalated to Sonnet (design 6-7 small model; escalation share assumed)
                    ch = per_call("haiku", "hold", t, think)[0] + 0.2 * per_call("sonnet", "hold", t, think)[0]
                else:
                    ch = per_call("sonnet", "hold", t, think)[0]
                ceo = per_call("opus", "entry", t, think)[0]
                cho = per_call("opus", "hold", t, think)[0]

                def daily_cost(i, with_opus):
                    E, H, E5, H5 = pre[i]
                    c = E * ce + H * ch + market_write_extra(E + H, t)
                    if with_opus:
                        # 5 Opus twins of 5 traders (median-rate members of the set), same wake moments
                        c = c + E5 * ceo + H5 * cho
                    return c, E + H

                for opus in (False, True):
                    sts = []
                    calls = []
                    for i in range(len(subsets[n])):
                        c, k = daily_cost(i, opus)
                        sts.append(stats_month(c))
                        calls.append((k.mean(), np.median(k), np.percentile(k, 90)))
                    med = {k: float(np.median([s[k] for s in sts])) for k in sts[0]}
                    cb, kb = daily_cost(len(subsets[n]), opus)
                    bz = stats_month(cb)
                    row = {"n_traders": n, "setup": setup, "hold_policy": pol, "signals_while_holding": mode, "pe": pe,
                           "lang": lang, "screen_scale": heavy, "thinking": think, "hold_model": hold_model,
                           "opus5": opus,
                           "calls_day_mean": float(np.median([c[0] for c in calls])),
                           "calls_day_median": float(np.median([c[1] for c in calls])),
                           "calls_day_p90": float(np.median([c[2] for c in calls])),
                           **{k: round(v, 1) for k, v in med.items()},
                           "busiest_set_mean_month": round(bz["mean_month"], 1),
                           "busiest_set_p90_day_x30": round(bz["p90_day_x30"], 1),
                           "busiest_set_calls_day_mean": float(kb.mean())}
                    out_rows.append(row)
        print("done n", n, flush=True)
    df = pd.DataFrame(out_rows)
    df.to_csv(os.path.join(work, "scenarios.csv"), index=False)
    print(len(df))


if __name__ == "__main__":
    main()
