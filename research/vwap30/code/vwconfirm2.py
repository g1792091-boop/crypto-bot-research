"""PREREG2.md step 4: the frozen finalists2.json (sha256 checked) once on the confirm period, live for reference,
coin-flip twin (1,000 draws, seed 20261024), verdict; then reads that choose nothing (참고): what each fix does on the
rule bot's own exits, the best setting with a win rate of 60 % or more, the 19-day stretches.

    python3 -I vwconfirm2.py   -> research/vwap30/results2.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwstages2 import *
from vwconfirm import KEYS, pick
from vwbuild2 import EARLY
from vwacct2 import _EX2

SEED, DRAWS = 20261024, 1000
PERIODS["c2025"] = (ms("2025-01-01"), ms("2026-01-01"))
PERIODS["c2026"] = (ms("2026-01-01"), ms("2026-10-01"))
PERIODS["rb19"] = (ms("2026-10-05T19:30"), DATA_END)            # the rule bot's run (first entry 10-06 04:30 KST)


def setup(books, wdm, c):
    b = books[c["book"]]
    m = wdm[c["book"]].copy()
    Fc = filters2(b)
    for nm in c["bundle"]:
        if nm not in NEW_FILTERS:
            m &= Fc[nm]
    return b, m, (take_rule(c["rule"]) if c["rule"] else None)


def stretches(b, m, j, tk, expo="rb9"):
    """19-day stretches (start each KST day) over select+confirm at the rule bot's 9x: share positive, median."""
    a, z = SEL[0], CONF[1]
    idx, net, ext, D = (tk or trades)(b, m & (b.entry >= a) & (b.entry < z), j)
    x = stake(b, idx, D, expo) * net
    lg = np.log1p(np.maximum(x, -1 + 1e-12))
    kd = (b.entry[idx] + KST) // DAY
    d0, d1 = (a + KST) // DAY, (z + KST) // DAY
    per = np.zeros(d1 - d0 + 1)
    np.add.at(per, kd - d0, lg)
    cs = np.r_[0, np.cumsum(per)]
    w = np.expm1(cs[19:] - cs[:-19])
    return {"share_pos": round(float((w > 0).mean()), 4), "median": round(float(np.median(w)), 4),
            "p90": round(float(np.quantile(w, 0.9)), 4)}


def main():
    fp = os.path.join(RES_DIR, "finalists2.json")
    want = open(fp + ".sha256").read().split()[0]
    got = hashlib.sha256(open(fp, "rb").read()).hexdigest()
    assert want == got, "finalists2.json changed after it was frozen"
    fin = json.load(open(fp))["finalists"]
    books = {b: Book2(b) for b in BOOKS}
    books["pool"] = pool([books["15m"], books["30m"], books["1h"]])
    wdm = {k: ~b.F.weekend.to_numpy(bool) for k, b in books.items()}
    res = []
    for c in fin:
        b, m, tk = setup(books, wdm, c)
        j = c["exit"]
        row = dict(c)
        for per in ("select", "confirm", "c2025", "c2026", "live", "rb19"):
            row[per] = pick(metrics(b, m, j, per, take=tk))
            row[per + "_rb9"] = {q: round(v, 4) if isinstance(v, float) else v for q, v in
                                 metrics(b, m, j, per, r="rb9", take=tk).items() if q in ("mult", "maxdd", "mon_median", "mon_worst")}
        rng = np.random.default_rng(SEED)
        tw = np.empty(DRAWS)
        for k in range(DRAWS):
            tw[k] = metrics(b, m, j, "confirm", flip=rng.random(len(b.entry)) < 0.5, full=False, take=tk)["growth"]
        g = row["confirm"]["growth"]
        p90 = float(np.percentile(tw, 90))
        row["twin"] = {"p10": round(float(np.percentile(tw, 10)), 3), "p50": round(float(np.median(tw)), 3),
                       "p90": round(p90, 3), "share_below": round(float((tw < g).mean()), 3)}
        row["verdict"] = "통함" if (row["confirm"]["avgR"] > 0 and g > p90) else "통하지 않음"
        row["sizing_confirm"] = [rnd({"r": r, **{q: v for q, v in metrics(b, m, j, "confirm", r=r, take=tk).items() if q in (
            "mult", "cagr", "mon_median", "mon_x6", "mon_worst", "mon_best", "maxdd", "ruin", "lev_med")}}) for r in SIZES]
        row["stretch19_rb9"] = stretches(b, m, j, tk)
        res.append(row)
        print(c["name"], c["book"], c["exit_ko"], "| confirm n", row["confirm"]["n"], "wd", row["confirm"]["per_weekday"],
              "win", row["confirm"]["win"], "R", row["confirm"]["avgR"], "g", g, "p90", round(p90, 2), "->", row["verdict"],
              flush=True)
    # 참고 1: each fix on the rule bot's own exits (30m, weekday entries)
    b30, m30 = books["30m"], wdm["30m"]
    fixes = []
    for prof in ("house", None, 1.0):
        for ev in EARLY:
            j = ex2_id(2.0, prof, ev)
            row = {"exit": j, "exit_ko": exit2_name(_EX2[j])}
            for per in ("select", "confirm", "live"):
                x = metrics(b30, m30, j, per)
                row[per] = rnd({q: x[q] for q in ("n", "per_weekday", "win", "avgR", "avg_win_pct", "avg_loss_pct",
                                                  "payoff", "growth")})
            fixes.append(row)
    # 참고 2: highest select growth among settings with win >= 60 % and >= 3 per weekday, per book
    hiwin = {}
    for k, b in books.items():
        best = None
        for e in EXITS2:
            x = metrics(b, wdm[k], e["id"], "select")
            if x["win"] >= 0.6 and x["per_weekday"] >= MIN_WD and (best is None or x["growth"] > best[1]["growth"]):
                best = (e["id"], x)
        if best:
            j = best[0]
            hiwin[k] = {"exit": j, "exit_ko": exit2_name(_EX2[j]),
                        **{per: pick(metrics(b, wdm[k], j, per)) for per in ("select", "confirm", "live")}}
    sel = json.load(open(os.path.join(OUT2, "select2.json")))
    s1 = {k: {kk: v[kk] for kk in ("n_ok", "best", "best_full")} for k, v in sel["step1"].items()}
    out = {"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "finalists_sha256": got,
           "n_configs_select": sel["n_configs"], "finalists": res, "step1": s1, "top_book": sel["top_book"],
           "step2": sel["step2"], "step3": sel["step3"], "fixes_30m": fixes, "hiwin": hiwin}
    json.dump(out, open(os.path.join(RES_DIR, "results2.json"), "w"), ensure_ascii=False, indent=1, default=float)
    print("written results2.json")


if __name__ == "__main__":
    main()
