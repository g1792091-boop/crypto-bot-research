"""Checks of the new tooling against the five-year study (its code re-run by fyref.py; its committed results.json):
(a) signals: the 10 current members' signals of signals_all.py vs fy_ref/out/signals5y.csv (bar closes 2020 .. 10-21);
(c) engine: run_members.run(current members) in the five-year data form (--compat: signal bar closes 2021-01-01 ..
    2026-10-01, data to 10-21 with October mark = last price) vs fy_ref's engine5y C0_current trades (trade by trade)
    and vs research/trendbot/fiveyear/results.json D.C0_current (analyze.describe, 1,000 draws) and funnel_C0.
Output: scratchpad newlive/validate.json.   Run: python3 -I validate.py"""
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nlcommon import *
import time
import run_members as R
from fyref import rnd, compare

OUTF = f"{NL}/validate.json"


def check_signals():
    ref = pd.read_csv(f"{FYREF}/out/signals5y.csv")
    ref["label"] = ref.member + "@" + ref.tf
    parts = []
    for m in R.current_members():
        z = np.load(sig_path(m["label"]))
        parts.append(pd.DataFrame({"bar_close": z["t"], "label": m["label"], "symbol": np.array(COINS)[z["coin"]],
                                   "side": z["side"].astype(int)}))
    mine = pd.concat(parts)
    mine = mine[mine.bar_close < T_FY_END]
    k = ["bar_close", "label", "symbol", "side"]
    mm = ref[k].merge(mine[k], on=k, how="outer", indicator=True)
    by = mm.groupby(["label", "_merge"], observed=True).size().unstack(fill_value=0)
    return {"window": "all bar closes < 2026-10-21", "fiveyear_n": int(len(ref)), "newlive_n": int(len(mine)),
            "both": int((mm._merge == "both").sum()), "only_fiveyear": int((mm._merge == "left_only").sum()),
            "only_newlive": int((mm._merge == "right_only").sum()),
            "by_member": {lab: {str(c): int(v) for c, v in r.items()} for lab, r in by.iterrows()}}


def check_engine():
    t0 = time.time()
    T, cand, info = R.run(R.current_members(), ms("2021-01-01"), ms("2026-10-01"), "paper", name="C0_newlive",
                          data_end=T_FY_END, oct_mark="last")
    dt = time.time() - t0
    R.save("C0_newlive", T, cand, info)
    ref = pd.read_csv(f"{FYREF}/out/runs/C0_current_trades.csv.gz")
    cols = ["entry_t", "label", "coin", "side", "exit_t", "reason", "roe", "pre", "fee", "fund", "opp_roe", "opp_reason"]
    a, b = T[cols].reset_index(drop=True), ref[cols].reset_index(drop=True)
    same_rows = len(a) == len(b) and all(
        (np.allclose(a[c], b[c], rtol=0, atol=1e-12, equal_nan=True) if a[c].dtype.kind == "f" else (a[c] == b[c]).all())
        for c in cols)
    import analyze as A
    A.RUNS = RUNS
    res = json.load(open(f"{REPO}/research/trendbot/fiveyear/results.json"))
    d, _ = A.describe("C0_newlive", detail="full")
    cmp_d = compare(rnd(d), {**res["D"]["C0_current"], "name": "C0_newlive"})
    cmp_f = compare(rnd(A.funnel("C0_newlive")), res["funnel_C0"])
    years = {y: {"entries": d["years"][y]["entries"], "roe_mean": round(d["years"][y]["roe_mean"], 6),
                 "results_json_entries": res["D"]["C0_current"]["years"][y]["entries"],
                 "results_json_roe_mean": res["D"]["C0_current"]["years"][y]["roe_mean"]} for y in d["years"]}
    return {"run_s": round(dt, 1), "trades": int(len(T)), "fiveyear_rerun_trades": int(len(ref)),
            "trade_by_trade_equal": bool(same_rows),
            "vs_results_json_D_C0_current": {"leaves_same": cmp_d["same"], "diff": cmp_d["diff"][:20],
                                             "only_newlive": cmp_d["only_a"][:10], "only_results": cmp_d["only_b"][:10]},
            "vs_results_json_funnel_C0": {"leaves_same": cmp_f["same"], "diff": cmp_f["diff"][:20]},
            "years": years, "all": {"entries": d["all"]["entries"], "roe_mean": d["all"]["roe_mean"],
                                    "rank_vs_twin_pct": d["all"]["rank_vs_twin_pct"]}}


if __name__ == "__main__":
    out = json.load(open(OUTF)) if os.path.isfile(OUTF) else {}
    what = sys.argv[1:] or ["signals", "engine"]
    if "signals" in what:
        out["signals_current_members"] = check_signals()
        print(json.dumps({k: v for k, v in out["signals_current_members"].items() if k != "by_member"}), flush=True)
    if "engine" in what:
        out["engine_C0"] = check_engine()
        print(json.dumps(out["engine_C0"], indent=1, default=str), flush=True)
    json.dump(out, open(OUTF, "w"), indent=1, default=str)
