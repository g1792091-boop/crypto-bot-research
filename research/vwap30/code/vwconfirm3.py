"""PREREG3.md step 4: the frozen baskets (finalists3.json, sha256 checked) once on the confirm period, live for
reference, coin-flip twin over every signal of the basket (1,000 draws, seed 20261025), verdict.

    python3 -I vwconfirm3.py  -> research/vwap30/results3.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwstages3 import *
from vwconfirm import KEYS, pick

PERIODS["c2025"] = (ms("2025-01-01"), ms("2026-01-01"))
PERIODS["c2026"] = (ms("2026-01-01"), ms("2026-10-01"))


def main():
    fp = os.path.join(RES_DIR, "finalists3.json")
    want = open(fp + ".sha256").read().split()[0]
    got = hashlib.sha256(open(fp, "rb").read()).hexdigest()
    assert want == got, "finalists3.json changed after it was frozen"
    fin = json.load(open(fp))["finalists"]
    res = []
    for f in fin:
        ones = []
        for i, mbr in enumerate(f["members"]):
            if mbr["label"] == VWAP4H:
                ones.append(vwap4h_one(i))
            else:
                ones.append(Label(mbr["label"]).one(mbr["exit"], i))
        b = merge(ones)
        m = wd_mask(b)
        row = {"name": f["name"], "members": f["members"]}
        for per in ("select", "confirm", "c2025", "c2026", "live"):
            row[per] = pick(metrics(b, m, 0, per))
            row[per + "_rb9"] = {q: round(v, 4) if isinstance(v, float) else v
                                 for q, v in metrics(b, m, 0, per, r="rb9").items() if q in ("mult", "maxdd", "mon_median", "mon_worst")}
        p90, tw = twin_p90(b, m, "confirm", 1000, SEED)
        g = row["confirm"]["growth"]
        row["twin"] = {"p10": round(float(np.percentile(tw, 10)), 3), "p50": round(float(np.median(tw)), 3),
                       "p90": round(p90, 3), "share_below": round(float((tw < g).mean()), 3)}
        row["verdict"] = "통함" if (row["confirm"]["avgR"] > 0 and g > p90) else "통하지 않음"
        row["sizing_confirm"] = [rnd({"r": r, **{q: v for q, v in metrics(b, m, 0, "confirm", r=r).items() if q in (
            "mult", "cagr", "mon_median", "mon_x6", "mon_worst", "mon_best", "maxdd", "ruin", "lev_med")}}) for r in SIZES]
        # which members made the trades (confirm)
        a, z = PERIODS["confirm"]
        idx, net, ext, D = trades(b, m & (b.entry >= a) & (b.entry < z), 0)
        mem = pd.DataFrame({"member": b.member[idx], "R": net / D, "win": net > 0})
        row["by_member_confirm"] = {k: {"n": int(len(g_)), "win": round(float(g_.win.mean()), 3),
                                        "avgR": round(float(g_.R.mean()), 4)} for k, g_ in mem.groupby("member")}
        res.append(row)
        print(f["name"], [x["label"] for x in f["members"]], "| confirm n", row["confirm"]["n"], "wd",
              row["confirm"]["per_weekday"], "win", row["confirm"]["win"], "R", row["confirm"]["avgR"], "g", g,
              "p90", round(p90, 2), "->", row["verdict"], flush=True)
    sel = json.load(open(os.path.join(OUT3, "select3.json")))
    out = {"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "finalists_sha256": got, "finalists": res,
           "select": {k: sel[k] for k in ("scan", "passed", "A", "V", "step3", "luck19", "n_configs")}}
    json.dump(out, open(os.path.join(RES_DIR, "results3.json"), "w"), ensure_ascii=False, indent=1, default=float)
    print("written results3.json")


if __name__ == "__main__":
    main()
