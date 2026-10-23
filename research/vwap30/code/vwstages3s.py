"""PREREG3_AMEND1.md: baskets C and CV from the 32 short-hold exits. Same steps as vwstages3.py / vwconfirm3.py.

    python3 -I vwstages3s.py select     -> OUT3S/select3s.json, research/vwap30/finalists3s.json (+ sha256)
    python3 -I vwstages3s.py confirm    -> research/vwap30/results3s.json (checks the sha256 first)"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
import vwstages3 as S3
import vwbuild3s as B3S
from vwstages3 import *
from vwconfirm import pick

S3.EXITS3 = B3S.EXITS3S                      # Label.D, solo_scan read these module globals
S3.OUT3 = B3S.OUT3S
S3.exit3_name = B3S.exit3s_name
EX = B3S.EXITS3S
SEED_S = 20261026
PERIODS["c2025"] = (ms("2025-01-01"), ms("2026-01-01"))
PERIODS["c2026"] = (ms("2026-01-01"), ms("2026-10-01"))


def select():
    t0 = time.time()
    names = sorted(os.path.basename(f)[:-4] for f in glob.glob(os.path.join(B3S.OUT3S, "*.npz")))
    labels = {n: S3.Label(n) for n in names}
    scan, best = {}, {}
    for nm, lab in labels.items():
        b_, rows = S3.solo_scan(lab)
        if b_ is None:
            scan[nm] = {"best": None}
            continue
        j = b_[0]
        o = lab.one(j)
        x = metrics(o, wd_mask(o), 0, "select")
        p90, _ = twin_p90(o, wd_mask(o), "select", 200, SEED_S)
        scan[nm] = {"best": j, "exit_ko": B3S.exit3s_name(EX[j]), "twin_p90": round(p90, 3),
                    "pass": bool(x["avgR"] > 0 and x["growth"] > 0 and x["growth"] > p90),
                    **rnd({k: x[k] for k in ("n", "per_weekday", "win", "avgR", "payoff", "growth", "maxdd")})}
        best[nm] = j
    passed = [n for n, s in scan.items() if s.get("pass")]
    print("passed", len(passed), passed, flush=True)
    ones_all = {n: labels[n].one(best[n]) for n in best}
    cands = {n: ones_all[n] for n in passed}
    C, C_sel, C_steps = S3.greedy(cands, [], ones_all, max_total=10 ** 6)
    CV, CV_sel, CV_steps = S3.greedy({k: v for k, v in cands.items() if k != VWAP30}, [VWAP30], ones_all, max_total=10 ** 6)
    print("C", len(C), round(C_sel["growth"], 3), round(C_sel["per_weekday"], 2), flush=True)
    print("CV", len(CV), round(CV_sel["growth"], 3), round(CV_sel["per_weekday"], 2), flush=True)
    st3 = {}
    for tag, mem in (("C", C), ("CV", CV)):
        b = merge([ones_all[n] for n in mem])
        st3[tag] = {"select": rnd(metrics(b, wd_mask(b), 0, "select")),
                    "sizing": [rnd({"r": r, **{q: v for q, v in metrics(b, wd_mask(b), 0, "select", r=r).items() if q in (
                        "mult", "cagr", "mon_median", "mon_x6", "mon_worst", "mon_best", "maxdd", "ruin", "lev_med")}})
                               for r in SIZES]}
    fin = [{"name": f"묶음 {tag}", "members": [{"label": n, "exit": int(scan[n]["best"]), "exit_ko": scan[n]["exit_ko"]}
                                              for n in mem]} for tag, mem in (("C", C), ("CV", CV))]
    fp = os.path.join(RES_DIR, "finalists3s.json")
    json.dump({"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "finalists": fin}, open(fp, "w"),
              ensure_ascii=False, indent=1)
    open(fp + ".sha256", "w").write(hashlib.sha256(open(fp, "rb").read()).hexdigest() + "  finalists3s.json\n")
    out = {"scan": scan, "passed": passed, "C": {"members": C, "steps": C_steps}, "CV": {"members": CV, "steps": CV_steps},
           "step3": st3, "secs": round(time.time() - t0)}
    json.dump(out, open(os.path.join(B3S.OUT3S, "select3s.json"), "w"), ensure_ascii=False, indent=1, default=float)
    print("done", round(time.time() - t0), "s")


def confirm():
    fp = os.path.join(RES_DIR, "finalists3s.json")
    want = open(fp + ".sha256").read().split()[0]
    got = hashlib.sha256(open(fp, "rb").read()).hexdigest()
    assert want == got, "finalists3s.json changed after it was frozen"
    res = []
    for f in json.load(open(fp))["finalists"]:
        b = merge([S3.Label(mbr["label"]).one(mbr["exit"], i) for i, mbr in enumerate(f["members"])])
        m = wd_mask(b)
        row = {"name": f["name"], "members": f["members"]}
        for per in ("select", "confirm", "c2025", "c2026", "live"):
            row[per] = pick(metrics(b, m, 0, per))
            row[per + "_rb9"] = {q: round(v, 4) if isinstance(v, float) else v
                                 for q, v in metrics(b, m, 0, per, r="rb9").items() if q in ("mult", "maxdd", "mon_median", "mon_worst")}
        p90, tw = twin_p90(b, m, "confirm", 1000, SEED_S)
        g = row["confirm"]["growth"]
        row["twin"] = {"p10": round(float(np.percentile(tw, 10)), 3), "p50": round(float(np.median(tw)), 3),
                       "p90": round(p90, 3), "share_below": round(float((tw < g).mean()), 3)}
        row["verdict"] = "통함" if (row["confirm"]["avgR"] > 0 and g > p90) else "통하지 않음"
        row["meets_3_per_weekday_select"] = bool(row["select"]["per_weekday"] >= MIN_WD)
        row["sizing_confirm"] = [rnd({"r": r, **{q: v for q, v in metrics(b, m, 0, "confirm", r=r).items() if q in (
            "mult", "cagr", "mon_median", "mon_x6", "mon_worst", "mon_best", "maxdd", "ruin", "lev_med")}}) for r in SIZES]
        a, z = PERIODS["confirm"]
        idx, net, ext, D = trades(b, m & (b.entry >= a) & (b.entry < z), 0)
        mem = pd.DataFrame({"member": b.member[idx], "R": net / D, "win": net > 0})
        row["by_member_confirm"] = {k: {"n": int(len(g_)), "win": round(float(g_.win.mean()), 3),
                                        "avgR": round(float(g_.R.mean()), 4)} for k, g_ in mem.groupby("member")}
        res.append(row)
        print(f["name"], len(f["members"]), "| select wd", row["select"]["per_weekday"], "R", row["select"]["avgR"],
              "| confirm n", row["confirm"]["n"], "wd", row["confirm"]["per_weekday"], "win", row["confirm"]["win"],
              "R", row["confirm"]["avgR"], "g", g, "p90", round(p90, 2), "->", row["verdict"], flush=True)
    sel = json.load(open(os.path.join(B3S.OUT3S, "select3s.json")))
    out = {"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "finalists_sha256": got, "finalists": res,
           "select": {k: sel[k] for k in ("scan", "passed", "C", "CV", "step3")}}
    json.dump(out, open(os.path.join(RES_DIR, "results3s.json"), "w"), ensure_ascii=False, indent=1, default=float)
    print("written results3s.json")


if __name__ == "__main__":
    {"select": select, "confirm": confirm}[sys.argv[1]]()
