"""PREREG3.md steps 1-3 on the select period (weekday entries), the frozen finalists3.json (+ sha256), and the 참고 read
"how big is the 19-day #1 by chance" (all 189 labels at the rule bot's form: 2 ATR stop + its ladder, 9x, all days).

    python3 -I vwstages3.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwacct import *
from vwbuild3 import OUT3, EXITS3, exit3_name
from vwstages import rnd, R_GRID, RES_DIR
import glob, hashlib

MIN_WD = 3.0
MIN_N = 100
SEED = 20261025
SIZES = list(R_GRID) + ["rb9", "owners"]
EX_HOUSE2 = next(e["id"] for e in EXITS3 if e["kind"] == "house" and e["stop"] == 2.0)
VWAP30 = "F6_VWAP_FAIL_at_30m"
VWAP4H = "F6_VWAP_FAIL_at_4h#1차"


class One:
    """A one-column book: rows in entry order, one exit per row already chosen (ret, t, ret_o, t_o, D per row)."""

    def __init__(self, entry, coin, ret, t, ret_o, t_o, D, prio=None, member=None):
        o = np.lexsort((coin, np.zeros(len(entry)) if prio is None else prio, entry))
        self.entry = entry[o].astype(np.int64)
        self.coin = coin[o]
        self.ret = ret[o][:, None]
        self.t = t[o].astype(np.int64)[:, None]
        self.ret_o = ret_o[o][:, None]
        self.t_o = t_o[o].astype(np.int64)[:, None]
        self.D = D[o]
        self.member = None if member is None else member[o]
        kst = pd.to_datetime(self.entry + KST, unit="ms")
        self.wd = np.asarray(kst.dayofweek < 5)
        self.lev_owner = np.where(self.coin == 0, 40.0, 30.0)

    def risk_dist(self, j):
        return self.D


class Label:
    """One strategy label: all its signals under the 24 exits."""

    def __init__(self, name):
        self.name = name
        Z = np.load(os.path.join(OUT3, f"{name}.npz"))
        self.entry = Z["t"].astype(np.int64)
        self.coin = Z["coin"].astype(np.int64)
        self.ret, self.tx, self.ret_o, self.tx_o = Z["ret"], Z["tx"], Z["ret_o"], Z["tx_o"]
        self.atrf = Z["atrf"].astype(float)

    def D(self, j):
        e = EXITS3[j]
        if e["kind"] == "owners":
            return 0.5 / np.where(self.coin == 0, 40.0, 30.0)
        return e["stop"] * self.atrf + COST_RT

    def one(self, j, prio=0):
        n = len(self.entry)
        return One(self.entry, self.coin, self.ret[:, j], self.tx[:, j], self.ret_o[:, j], self.tx_o[:, j], self.D(j),
                   np.full(n, prio), np.full(n, self.name, object))


def vwap4h_one(prio=0):
    b = Book("4h")
    j = 83                                   # round 1's step-5 pick (finalists.json)
    n = len(b.entry)
    return One(b.entry, b.F["rank"].to_numpy(), b.ret[:, j], b.t[:, j], b.ret_o[:, j], b.t_o[:, j], b.risk_dist(j),
               np.full(n, prio), np.full(n, VWAP4H, object))


def merge(ones):
    cat = lambda k: np.concatenate([getattr(o, k) for o in ones])
    prio = np.concatenate([np.full(len(o.entry), i) for i, o in enumerate(ones)])
    return One(cat("entry"), cat("coin"), cat("ret")[:, 0], cat("t")[:, 0], cat("ret_o")[:, 0], cat("t_o")[:, 0],
               cat("D"), prio, cat("member"))


def wd_mask(b):
    return b.wd.copy()


def solo_scan(lab):
    """Best exit by select growth (weekday, one position, r = 2 %), n >= 100."""
    best = None
    rows = []
    for e in EXITS3:
        b = lab.one(e["id"])
        x = metrics(b, wd_mask(b), 0, "select", full=False)
        rows.append((e["id"], x["growth"], x["n"], x["per_weekday"]))
        if x["n"] >= MIN_N and (best is None or x["growth"] > best[1]):
            best = (e["id"], x["growth"])
    return best, rows


def twin_p90(b, m, per, draws, seed):
    rng = np.random.default_rng(seed)
    g = np.array([metrics(b, m, 0, per, flip=rng.random(len(b.entry)) < 0.5, full=False)["growth"] for _ in range(draws)])
    return float(np.percentile(g, 90)), g


def basket_metrics(ones, per="select", full=False):
    b = merge(ones)
    return metrics(b, wd_mask(b), 0, per, full=full)


def greedy(cands, start, pool_all):
    """cands: {name: One}; start: [names]. Adds the member that raises select growth most (<= 12); then, if under 3 a
    weekday, the one that lowers it least, first from cands, then from pool_all."""
    chosen = list(start)
    cur = basket_metrics([cands.get(n) or pool_all[n] for n in chosen]) if chosen else {"growth": 0.0, "per_weekday": 0.0}
    steps = []
    while len(chosen) < 12:
        best = None
        for nm, o in cands.items():
            if nm in chosen:
                continue
            x = basket_metrics([cands.get(n) or pool_all[n] for n in chosen] + [o])
            if best is None or x["growth"] > best[1]["growth"]:
                best = (nm, x)
        if best is None or best[1]["growth"] <= cur["growth"]:
            break
        chosen.append(best[0])
        cur = best[1]
        steps.append({"add": best[0], "growth": round(cur["growth"], 3), "per_weekday": round(cur["per_weekday"], 3), "why": "성장"})
    for pool, tag in ((cands, "3번 채우기(통과)"), (pool_all, "3번 채우기(전체)")):
        while cur["per_weekday"] < MIN_WD and len(chosen) < 24:
            best = None
            for nm, o in pool.items():
                if nm in chosen:
                    continue
                x = basket_metrics([cands.get(n) or pool_all[n] for n in chosen] + [o])
                if best is None or x["growth"] > best[1]["growth"]:
                    best = (nm, x)
            if best is None:
                break
            chosen.append(best[0])
            cur = best[1]
            steps.append({"add": best[0], "growth": round(cur["growth"], 3), "per_weekday": round(cur["per_weekday"], 3), "why": tag})
    return chosen, cur, steps


def luck19(labels):
    """참고: each label alone at the rule bot's form (2 ATR + its ladder, 9x, all days, one position): every 19-day
    stretch (start each KST day) over 2020-03 .. the data end; the #1 label's return and its next 19 days."""
    a, z = SEL[0], DATA_END
    d0, d1 = (a + KST) // DAY, (z + KST) // DAY
    nd = d1 - d0 + 1
    curves = {}
    for nm, lab in labels.items():
        b = lab.one(EX_HOUSE2)
        m = (b.entry >= a) & (b.entry < z)
        idx, net, ext, D = trades(b, m, 0)
        if len(idx) < 50:
            continue
        lg = np.log1p(np.maximum(9.0 * net, -1 + 1e-12))
        per = np.zeros(nd)
        np.add.at(per, (b.entry[idx] + KST) // DAY - d0, lg)
        curves[nm] = np.r_[0, np.cumsum(per)]
    names = list(curves)
    C = np.array([curves[n] for n in names])                      # labels x (nd + 1)
    W = 19
    starts = np.arange(0, nd - W + 1)
    r = np.expm1(C[:, starts + W] - C[:, starts])                 # labels x starts
    top = r.max(0)
    who = r.argmax(0)
    nxt = np.full(len(starts), np.nan)
    ok = starts + 2 * W <= nd
    nxt[ok] = np.expm1(C[who[ok], starts[ok] + 2 * W] - C[who[ok], starts[ok] + W])
    med = np.median(r, axis=0)
    k_live = (ms("2026-10-05T15:00") + KST) // DAY - d0          # the rule bot's run: 10-06 KST .. the data end
    rl = np.zeros(len(names))                                     # each label started fresh at the rule bot's start
    for q, nm in enumerate(names):
        b = labels[nm].one(EX_HOUSE2)
        idx, net, ext, D = trades(b, (b.entry >= ms("2026-10-05T19:30")) & (b.entry < z), 0)
        rl[q] = np.prod(1 + np.maximum(9.0 * net, -1.0)) - 1
    order = np.argsort(-rl)
    live = [(names[i], round(float(rl[i]), 3)) for i in order[:5]]
    live_vwap_rank = int(np.where(order == names.index(VWAP30))[0][0]) + 1 if VWAP30 in names else None
    # how often the #1 of a stretch as long as the rule bot's run reaches that run's #1
    L = nd - k_live
    rL = np.expm1(C[:, starts[:nd - L + 1] + L] - C[:, starts[:nd - L + 1]])
    topL = rL.max(0)
    return {"labels": len(names), "stretches": int(len(starts)),
            "top_q": {str(q): round(float(np.quantile(top, q)), 3) for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
            "share_top_ge_0686": round(float((top >= 0.686).mean()), 3),
            "median_label_median": round(float(np.median(med)), 3),
            "top_next19_median": round(float(np.nanmedian(nxt)), 3),
            "top_next19_pos": round(float(np.nanmean(nxt[ok] > 0)), 3),
            "live_days": int(L), "live_1006_end_top5": live, "live_vwap_rank": live_vwap_rank,
            "share_topL_ge_live_top": round(float((topL[:-1] >= rl.max()).mean()), 3),
            "topL_median": round(float(np.median(topL)), 3)}


def main():
    t0 = time.time()
    names = sorted(os.path.basename(f)[:-4] for f in glob.glob(os.path.join(OUT3, "*.npz")))
    labels = {n: Label(n) for n in names}
    # step 1: per label
    scan, best = {}, {}
    n_cfg = 0
    for nm, lab in labels.items():
        b_, rows = solo_scan(lab)
        n_cfg += len(EXITS3)
        if b_ is None:
            scan[nm] = {"best": None}
            continue
        j = b_[0]
        o = lab.one(j)
        x = metrics(o, wd_mask(o), 0, "select")
        p90, _ = twin_p90(o, wd_mask(o), "select", 200, SEED)
        ok = bool(x["avgR"] > 0 and x["growth"] > 0 and x["growth"] > p90)
        scan[nm] = {"best": j, "exit_ko": exit3_name(EXITS3[j]), "pass": ok, "twin_p90": round(p90, 3),
                    **rnd({k: x[k] for k in ("n", "per_weekday", "win", "avgR", "payoff", "growth", "maxdd")})}
        best[nm] = j
    v4 = vwap4h_one()
    x = metrics(v4, wd_mask(v4), 0, "select")
    p90, _ = twin_p90(v4, wd_mask(v4), "select", 200, SEED)
    scan[VWAP4H] = {"best": 83, "exit_ko": "손절 0.75ATR · 익절 없음 · 96봉 · 본전(+1ATR 뒤) (1차)", "twin_p90": round(p90, 3),
                    "pass": bool(x["avgR"] > 0 and x["growth"] > 0 and x["growth"] > p90),
                    **rnd({k: x[k] for k in ("n", "per_weekday", "win", "avgR", "payoff", "growth", "maxdd")})}
    passed = [n for n, s in scan.items() if s.get("pass")]
    print("step1 passed", len(passed), passed, flush=True)
    ones_all = {n: labels[n].one(best[n]) for n in best}
    ones_all[VWAP4H] = v4
    cands = {n: ones_all[n] for n in passed}
    # step 2: baskets
    A, A_sel, A_steps = greedy(cands, [], ones_all)
    V, V_sel, V_steps = greedy({k: v for k, v in cands.items() if k != VWAP30}, [VWAP30], ones_all)
    n_cfg += 2 * len(ones_all) * 12
    print("basket A", A, round(A_sel["growth"], 3), round(A_sel["per_weekday"], 2), flush=True)
    print("basket V", V, round(V_sel["growth"], 3), round(V_sel["per_weekday"], 2), flush=True)
    # step 3: sizing (select)
    st3 = {}
    for tag, mem in (("A", A), ("V", V)):
        if not mem:
            continue
        b = merge([ones_all[n] for n in mem])
        st3[tag] = {"select": rnd(metrics(b, wd_mask(b), 0, "select")),
                    "sizing": [rnd({"r": r, **{q: v for q, v in metrics(b, wd_mask(b), 0, "select", r=r).items() if q in (
                        "mult", "cagr", "mon_median", "mon_x6", "mon_worst", "mon_best", "maxdd", "ruin", "lev_med")}})
                               for r in SIZES]}
    fin = [{"name": f"묶음 {tag}", "members": [{"label": n, "exit": int(scan[n]["best"]), "exit_ko": scan[n]["exit_ko"]}
                                              for n in mem]} for tag, mem in (("A", A), ("V", V)) if mem]
    fp = os.path.join(RES_DIR, "finalists3.json")
    json.dump({"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "finalists": fin}, open(fp, "w"),
              ensure_ascii=False, indent=1)
    open(fp + ".sha256", "w").write(hashlib.sha256(open(fp, "rb").read()).hexdigest() + "  finalists3.json\n")
    luck = luck19(labels)
    print("luck19", luck, flush=True)
    out = {"scan": scan, "passed": passed, "A": {"members": A, "steps": A_steps}, "V": {"members": V, "steps": V_steps},
           "step3": st3, "luck19": luck, "n_configs": n_cfg, "secs": round(time.time() - t0)}
    json.dump(out, open(os.path.join(OUT3, "select3.json"), "w"), ensure_ascii=False, indent=1, default=float)
    print("done", round(time.time() - t0), "s")


if __name__ == "__main__":
    main()
