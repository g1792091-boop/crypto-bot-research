"""Owners 10-25 night, 20 days only (no 5-year): the owners' plan (40% margin, BTC 40x / others 30x, fixed +15% TP)
at Toobit costs from $50; entries near the range ends; how many entries; all 61 signals alone; weekends."""
import json
import os
import sys

import pandas as pd

H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, H)
sys.path.insert(0, os.path.dirname(os.path.dirname(H)))
import extras as E  # noqa: E402
import sim  # noqa: E402
import v39lib as L  # noqa: E402
import variants as VR  # noqa: E402

EXPORT, OUT = sys.argv[1], sys.argv[2]
W = L.Window(EXPORT)
P = {v.name: v for v in VR.PLAN}
plans = [("페이퍼 규칙 그대로", VR.BASE), ("계획 + 지금 계단", P["p_ladder"]), ("계획 + 고정 익절 15% (손절 2ATR)", P["p_roe15_s2"]),
         ("계획 + 고정 익절 15% (손절 2.5ATR)", P["p_roe15_s2.5"]), ("계획 + 고정 익절 15% (손절 1.5ATR)", P["p_roe15_s1.5"]),
         ("계획 + 고정 익절 10% (손절 2ATR)", P["p_roe10_s2"])]
res = {"accounts": [], "per_trade": {}}
kst = lambda ms: pd.Timestamp(int(ms) + 9 * 3_600_000, unit="ms")  # noqa: E731
for label, v in plans:
    for cost, eq0 in (("paper", 5000.0), ("toobit_slip3", 50.0)):
        Sset = E.plan_settings(W, cost)
        specs = W.specs if cost == "paper" else E.plan_specs("A")
        k = L.kernel_account(W, v, equity0=eq0, settings=Sset, specs=specs)
        ent = k[k["status"] == "ENTERED"].copy()
        eq = ent["equity_after"].to_numpy(float)
        ent["ret"] = ent["pnl"] / ent["equity_before"]
        ent["t"] = [int(W.A[s]["ts"][int(i)]) for s, i in zip(ent["symbol"], ent["i"])] if "i" in ent else 0
        row = {"plan": label, "variant": v.name, "cost": cost, "start": eq0, "trades": int(len(ent)),
               "wins": int((ent["pnl"] > 0).sum()), "losses": int((ent["pnl"] <= 0).sum()),
               "open": int((ent["reason"] == "OPEN").sum()), "final": float(eq[-1]) if len(eq) else eq0,
               "dd_pct": 100 * L.max_drawdown(eq, eq0) if len(eq) else 0.0,
               "worst_pct": 100 * float(ent["ret"].min()), "liq": int((ent["reason"] == "LIQ").sum()),
               "reasons": ent["reason"].value_counts().to_dict()}
        res["accounts"].append(row)
        if cost == "toobit_slip3":
            res["per_trade"][v.name] = ent
        print(json.dumps(row, ensure_ascii=False, default=float))

# all 61 signals, each alone on a fresh $50 under the plan with the +15% TP (Toobit costs): "if every signal were taken"
Sset = E.plan_settings(W, "toobit_slip3")
S, br = L.kernel_vectors(W, Sset)
specs = E.plan_specs("A")
alone = []
taken = {(t.symbol, int(t.signal_ts) + 1) for t in W.trades.itertuples(index=False)}
for d in W.sigs:
    A = W.A[d["symbol"]]
    e = W.entry_index(d["symbol"], d["bar_close"])
    r = sim.run_one(S, br[d["symbol"]], A, e, d["ref_price"], d["side"], d["atr"], d["best"], 50.0, specs[d["symbol"]],
                    P["p_roe15_s2"], d["symbol"])
    t = kst(d["bar_close"])
    alone.append({"kst": t.strftime("%m-%d %H:%M"), "dow": t.dayofweek, "symbol": d["symbol"][:-4],
                  "side": "롱" if d["side"] > 0 else "숏", "taken": (d["symbol"], d["bar_close"]) in taken,
                  "reason": r["reason"], "ret_pct": 100 * r["ret"], "roe_pct": 100 * r["roe"], "hold_min": None})
A61 = pd.DataFrame(alone)
A61.to_csv(f"{OUT}/all61_alone_plan_roe15.csv", index=False)
ok = A61[A61["reason"] != "REJECTED"]
res["all61"] = {"signals": len(A61), "wins": int((ok["ret_pct"] > 0).sum()), "losses": int((ok["ret_pct"] <= 0).sum()),
                "open": int((ok["reason"] == "OPEN").sum()), "rejected": int((A61["reason"] == "REJECTED").sum()),
                "per_day": len(A61) / ((W.end_ms - W.start_ms) / 86_400_000),
                "not_taken": {"n": int((~ok["taken"]).sum()), "wins": int(((~ok["taken"]) & (ok["ret_pct"] > 0)).sum()),
                              "losses": int(((~ok["taken"]) & (ok["ret_pct"] <= 0)).sum())}}
# weekend (KST Sat-Sun) vs weekday: the 61 signals alone, and the 27 paper trades
for name, g in (("weekend", ok[ok["dow"] >= 5]), ("weekday", ok[ok["dow"] < 5])):
    res[f"all61_{name}"] = {"n": len(g), "wins": int((g["ret_pct"] > 0).sum()), "losses": int((g["ret_pct"] <= 0).sum()),
                            "mean_ret_pct": float(g["ret_pct"].mean())}
T = pd.read_csv(f"{H}/out/window/trades.csv")
T["dow"] = [kst(pd.Timestamp(f"2026-{s}").value // 10**6 - 9 * 3_600_000).dayofweek for s in T["entry_kst"]]
for name, g in (("weekend", T[T["dow"] >= 5]), ("weekday", T[T["dow"] < 5])):
    res[f"paper27_{name}"] = {"n": len(g), "wins": int((g["pnl"] > 0).sum()), "losses": int((g["pnl"] <= 0).sum()),
                              "pnl": float(g["pnl"].sum()), "mean_ret_pct": float(g["ret_pct"].mean())}
days = pd.date_range("2026-10-06", "2026-10-25")
res["calendar"] = {"days": len(days), "weekend_days": int((days.dayofweek >= 5).sum())}
# where the entry sat in the range (ctx_box_pos 0 = the low, 1 = the high) and how deep it went against first
T["near_bad_end"] = ((T["side"] == "숏") & (T["ctx_box_pos"] <= 0.3)) | ((T["side"] == "롱") & (T["ctx_box_pos"] >= 0.7))
res["box"] = {"short_pos": T.loc[T["side"] == "숏", "ctx_box_pos"].round(2).tolist(),
              "long_pos": T.loc[T["side"] == "롱", "ctx_box_pos"].round(2).tolist()}
for name, g in (("near_bad_end", T[T["near_bad_end"]]), ("other", T[~T["near_bad_end"]])):
    res[f"box_{name}"] = {"n": len(g), "wins": int((g["pnl"] > 0).sum()), "losses": int((g["pnl"] <= 0).sum()),
                          "mean_ret_pct": float(g["ret_pct"].mean()), "median_mae_net_pct": float(g["mae_roe_net_pct"].median()),
                          "deep_mae_20": int((g["mae_roe_net_pct"] < -20).sum())}
json.dump(res, open(f"{OUT}/q20.json", "w"), ensure_ascii=False, indent=1, default=lambda o: o.to_dict() if hasattr(o, "to_dict") else float(o))
for k in ("all61", "all61_weekend", "all61_weekday", "paper27_weekend", "paper27_weekday", "calendar", "box", "box_near_bad_end", "box_other"):
    print(k, json.dumps(res[k], ensure_ascii=False, default=float))
