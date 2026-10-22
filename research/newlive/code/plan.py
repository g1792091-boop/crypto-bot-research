"""The pre-registered selection (research/newlive/PREREG.md + PREREG_AMEND_1.md, classify.json), run once:
1. solo runs of every candidate (classify primary 돌파 / 자리 / 눌림 on 30m and 1h, default numbers, plus the league's
   30m / 1h picks of those strategies), J4, paper costs, signal bar closes 2021-01-01 .. the data end, measures per
   period (select / confirm / live by entry time), the select-period coin-flip twin (200 draws, default_rng(20261022));
2. PASS = select entries >= 40, select mean before-cost ROE > 0, select growth >= the twin's 90th percentile;
3. baskets B1 / B0 / B3 and C0 (the 10 live members as configured), one continuous run each, measures per period,
   coin-flip band (1,000 draws, default_rng(20261022)) on each period; verdicts on confirm;
4. J4L for the chosen basket (B1, else B0); the judges' direction accuracy; Bybit / WOO taker sensitivity of B0, C0.
Output: research/newlive/results.json, research/newlive/solo_table.csv, scratchpad newlive/runs/plan/*.
Run: python3 -I plan.py [--solo-draws 200] [--basket-draws 1000] [--procs 3]"""
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nlcommon import *
import time
from multiprocessing import Pool
import run_members as R

SEED = 20261022
SEL = (ms("2021-01-01"), ms("2025-01-01"))
CONF = (ms("2025-01-01"), ms("2026-10-01"))
LIVE = (ms("2026-10-01"), DATA_END)
PERIODS = {"select": SEL, "confirm": CONF, "live": LIVE}
START = ms("2021-01-01")
CLASSES = ("돌파", "자리", "눌림")
OUTD = f"{RUNS}/plan"
NL_REPO = f"{REPO}/research/newlive"
REASONS = ["LOCK", "SL", "JUDGE", "REV", "TIME", "LIQ", "END"]


def arg(name, default):
    return type(default)(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def candidate_list():
    from paperbot import combo as C
    cl = json.load(open(f"{NL_REPO}/classify.json"))
    names = sorted(n for n, v in cl.items() if v["primary"] in CLASSES)
    brk = {n for n, v in cl.items() if v["primary"] == "돌파"}
    out = []
    for tf in ("30m", "1h"):
        for n in names:
            out.append({"label": label_of(n, tf), "name": n, "tf": tf, "pick": None, "cls": cl[n]["primary"],
                        "breakout": n in brk})
    picks = C.load_picks(C.CANDIDATES_FILE)
    for pid, c in sorted(picks.items()):
        if c["tf"] in ("30m", "1h") and c["name"] in names:
            out.append({"label": label_of(c["name"], c["tf"], pid), "name": c["name"], "tf": c["tf"], "pick": pid,
                        "cls": cl[c["name"]]["primary"], "breakout": c["name"] in brk})
    return out


def flips(n, draws, seed=SEED):
    return np.random.default_rng(seed).random((draws, n)) < 0.5


def weekdays(a, b):
    return int(np.busday_count(pd.Timestamp(a, unit="ms").date(), pd.Timestamp(b, unit="ms").date()))


def measures(T, a, b, flip=None):
    m = ((T.entry_t >= a) & (T.entry_t < b)).to_numpy() if len(T) else np.zeros(0, bool)
    t = T[m] if len(T) else T
    n = int(m.sum())
    wd = weekdays(a, b)
    out = {"entries": n, "weekdays": wd, "per_weekday": round(n / wd, 4) if wd else None}
    if not n:
        out.update(growth_log=0.0, usd=1000.0)
        return out
    roe = t.roe.to_numpy()
    g = np.clip(1 + 0.4 * roe, 1e-12, None)
    lg = float(np.log(g).sum())
    path = np.cumprod(g)
    peak = np.maximum.accumulate(np.concatenate([[1.0], path]))[1:]
    w, l_ = roe[roe > 0], roe[roe < 0]
    out.update({"win_pct": round(100 * float((roe > 0).mean()), 2), "roe_mean": float(roe.mean()),
                "pre_mean": float(t.pre.mean()),
                "payoff": float(w.mean() / abs(l_.mean())) if len(w) and len(l_) else None,
                "growth_log": lg, "usd": float(1000 * np.exp(lg)), "worst_dd": float((1 - path / peak).max()),
                "exits": {r: int((t.reason == r).sum()) for r in REASONS if (t.reason == r).any()},
                "long_short": [int((t.side > 0).sum()), int((t.side < 0).sum())],
                "cost_mean": float((t.slip_cost + t.fee + t.fund).mean())})
    if flip is not None:
        r = np.where(flip[:, m], t.opp_roe.to_numpy()[None, :], roe[None, :])
        tl = np.log(np.clip(1 + 0.4 * r, 1e-12, None)).sum(axis=1)
        out["twin"] = {"draws": int(flip.shape[0]), "log_p5_50_90_95": [float(np.percentile(tl, q)) for q in (5, 50, 90, 95)],
                       "usd_p5_50_95": [float(1000 * np.exp(np.percentile(tl, q))) for q in (5, 50, 95)],
                       "rank_pct": float(100 * (tl < lg).mean())}
    return out


def all_periods(T, draws=0, twin_periods=("select",)):
    fl = flips(len(T), draws) if (draws and len(T)) else None
    return {p: measures(T, a, b, fl if p in twin_periods else None) for p, (a, b) in PERIODS.items()}


# ---------------------------------------------------------------- solo
SOLO_DRAWS = 200


def solo(c):
    t0 = time.time()
    T, cand, info = R.run([{"label": c["label"], "breakout": c["breakout"]}], START, DATA_END, "paper", name=c["label"])
    t1 = time.time()
    res = all_periods(T, SOLO_DRAWS, ("select",))
    s = res["select"]
    p90 = s.get("twin", {}).get("log_p5_50_90_95", [None] * 4)[2]
    ok = bool(s["entries"] >= 40 and s.get("pre_mean", -1) > 0 and p90 is not None and s["growth_log"] >= p90)
    os.makedirs(f"{OUTD}/solo", exist_ok=True)
    T.to_csv(f"{OUTD}/solo/{c['label'].replace('@', '_at_').replace('#', '__')}.csv.gz", index=False)
    return {**c, "periods": res, "pass": ok, "n_signals": info["n_signals"], "funnel": info["funnel"]["total"],
            "run_s": round(t1 - t0, 2), "twin_s": round(time.time() - t1, 2)}


# ---------------------------------------------------------------- baskets
def one_per_cell(rows):
    seen, out = set(), []
    for r in rows:
        k = (r["name"], r["tf"])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def basket(name, members, draws, judge="J4", cost="paper"):
    t0 = time.time()
    T, cand, info = R.run(members, START, DATA_END, cost, name=name, judge=judge)
    res = all_periods(T, draws, ("select", "confirm", "live"))
    os.makedirs(f"{OUTD}/baskets", exist_ok=True)
    T.to_csv(f"{OUTD}/baskets/{name}_trades.csv.gz", index=False)
    by_member = {lab: {p: measures(T[T.label == lab], a, b) for p, (a, b) in PERIODS.items()}
                 for lab in sorted(T.label.unique())} if len(T) else {}
    return {"name": name, "judge": judge, "cost": cost, "members": info["members"], "periods": res,
            "funnel": info["funnel"]["total"], "by_member": by_member, "run_s": round(time.time() - t0, 1)}


def verdicts(b, c0):
    cf = b["periods"]["confirm"]
    tw = cf.get("twin", {}).get("log_p5_50_90_95")
    return {"벌었다": cf["growth_log"] > 0, "지금보다_낫다": cf["growth_log"] > c0["periods"]["confirm"]["growth_log"]
            if b["name"] != "C0" else None, "운보다_낫다": (cf["growth_log"] > tw[3]) if tw else None}


# ---------------------------------------------------------------- judges' direction accuracy
def direction_accuracy():
    out = {}
    a0, a1 = ms("2021-01-01"), DATA_END
    for rule in ("J4", "J4L"):
        for tf in ("1h", "4h"):
            hold = {"1h": 2, "4h": 1}[tf]
            hit_raw = n_raw = hit_dir = n_dir = 0
            for c in COINS:
                M = R.markets()[c]
                J = M.J
                raw = J[f"{tf}_raw3"] if rule == "J4" else J[f"{tf}_rawL"]
                cl, tc = J[f"{tf}_close"], J[f"{tf}_tclose"]
                held = raw.copy()
                for h in range(1, hold):
                    held = np.where(np.r_[np.zeros(h, np.int8), raw[:-h]] == raw, held, 0)
                k = np.flatnonzero((tc >= a0) & (tc + 4 * TF_MS[tf] <= a1))
                k = k[k + 4 < len(cl)]
                mv = np.sign(cl[k + 4] - cl[k])
                for arr, name in ((raw, "raw"), (held, "held")):
                    d = arr[k]
                    sel = d != 0
                    if name == "raw":
                        n_raw += int(sel.sum()); hit_raw += int((mv[sel] == d[sel]).sum())
                    else:
                        n_dir += int(sel.sum()); hit_dir += int((mv[sel] == d[sel]).sum())
            out[f"{rule}_{tf}"] = {"bars_with_direction_raw": n_raw, "accuracy_raw_pct": round(100 * hit_raw / max(1, n_raw), 2),
                                   "bars_with_direction_held": n_dir,
                                   "accuracy_held_pct": round(100 * hit_dir / max(1, n_dir), 2)}
    return out


def main():
    global SOLO_DRAWS
    SOLO_DRAWS = arg("--solo-draws", 200)
    bdraws = arg("--basket-draws", 1000)
    procs = arg("--procs", 3)
    t_all = time.time()
    cands = candidate_list()
    print(f"{len(cands)} candidates", flush=True)
    R.markets()                                       # loaded once, shared by the forked workers
    t0 = time.time()
    rows = []
    cache = f"{OUTD}/solo_rows.json"
    if "--reuse-solo" in sys.argv and os.path.isfile(cache):
        rows = json.load(open(cache))
        assert sorted(r["label"] for r in rows) == sorted(c["label"] for c in cands)
    else:
        with Pool(procs) as pool:
            for r in pool.imap_unordered(solo, cands):
                rows.append(r)
                print(f"solo {len(rows)}/{len(cands)} {r['label']} run {r['run_s']}s twin {r['twin_s']}s", flush=True)
        os.makedirs(OUTD, exist_ok=True)
        json.dump(rows, open(cache, "w"), default=str)
    t_solo = time.time() - t0
    order = {c["label"]: i for i, c in enumerate(cands)}
    rows.sort(key=lambda r: order[r["label"]])
    rank = sorted(rows, key=lambda r: (-r["periods"]["select"]["growth_log"], order[r["label"]]))
    passing = [r for r in rank if r["pass"]]
    B1 = one_per_cell(passing)[:12]
    B0 = one_per_cell(rank)[:10]
    B3, acc = [], 0.0
    for r in one_per_cell(rank):
        B3.append(r)
        acc += r["periods"]["select"]["per_weekday"] or 0
        if acc >= 4.0:
            break
    mem = lambda rs: [{"label": r["label"], "breakout": r["breakout"]} for r in rs]
    baskets = {}
    t1 = time.time()
    baskets["C0"] = basket("C0", R.current_members(), bdraws)
    if B1:
        baskets["B1"] = basket("B1", mem(B1), bdraws)
    baskets["B0"] = basket("B0", mem(B0), bdraws)
    baskets["B3"] = basket("B3", mem(B3), bdraws)
    chosen = "B1" if B1 else "B0"
    baskets[f"{chosen}_J4L"] = basket(f"{chosen}_J4L", mem(B1 if B1 else B0), bdraws, judge="J4L")
    for nm, mm in (("B0", mem(B0)), ("C0", R.current_members())):
        for cost in ("bybit", "woo"):
            baskets[f"{nm}_{cost}"] = basket(f"{nm}_{cost}", mm, 0, cost=cost)
    for k in ("C0", "B1", "B0", "B3", f"{chosen}_J4L"):
        if k in baskets:
            baskets[k]["verdicts_confirm"] = verdicts(baskets[k], baskets["C0"])
    t_b = time.time() - t1
    j4 = baskets[chosen]["periods"]
    j4l = baskets[f"{chosen}_J4L"]["periods"]
    judge_cmp = {"basket": chosen, "select_growth_J4": j4["select"]["growth_log"],
                 "select_growth_J4L": j4l["select"]["growth_log"],
                 "proposal": "J4L" if j4l["select"]["growth_log"] > j4["select"]["growth_log"] else "J4",
                 "confirm_J4": j4["confirm"], "confirm_J4L": j4l["confirm"], "live_J4": j4["live"], "live_J4L": j4l["live"]}
    da = direction_accuracy()
    val = {}
    for f in ("validate.json", "validate_custom.json"):
        if os.path.isfile(f"{NL}/{f}"):
            val[f] = json.load(open(f"{NL}/{f}"))
    out = {"prereg_sha256": {"PREREG.md": sha256(f"{NL_REPO}/PREREG.md"),
                             "PREREG_AMEND_1.md": sha256(f"{NL_REPO}/PREREG_AMEND_1.md"),
                             "classify.json": sha256(f"{NL_REPO}/classify.json"),
                             "candidates_owner.json": sha256(f"{REPO}/candleague/data/candidates_owner.json")},
           "data": data_manifest(), "periods_utc": {k: [str(pd.Timestamp(a, unit="ms")), str(pd.Timestamp(b, unit="ms"))]
                                                    for k, (a, b) in PERIODS.items()},
           "seed": SEED, "solo_draws": SOLO_DRAWS, "basket_draws": bdraws, "validation": val,
           "candidates": len(cands), "solo": rows, "ranking_by_select_growth": [r["label"] for r in rank],
           "passing": [r["label"] for r in passing],
           "B1": [r["label"] for r in B1], "B0": [r["label"] for r in B0], "B3": [r["label"] for r in B3],
           "B3_sum_select_per_weekday": acc, "chosen_for_J4L": chosen, "baskets": baskets, "judge_sets": judge_cmp,
           "direction_accuracy": da,
           "timing_s": {"solo_all": round(t_solo, 1), "solo_mean_run": float(np.mean([r["run_s"] for r in rows])),
                        "solo_mean_twin": float(np.mean([r["twin_s"] for r in rows])), "baskets": round(t_b, 1),
                        "total": round(time.time() - t_all, 1)}}
    json.dump(out, open(f"{NL_REPO}/results.json", "w"), indent=1, default=str, ensure_ascii=False)
    tab = []
    for r in rank:
        row = {"rank": len(tab) + 1, "label": r["label"], "name": r["name"], "tf": r["tf"], "pick": r["pick"] or "",
               "class": r["cls"], "breakout": r["breakout"], "pass": r["pass"]}
        for p in PERIODS:
            m = r["periods"][p]
            row.update({f"{p}_entries": m["entries"], f"{p}_per_wd": m["per_weekday"], f"{p}_win": m.get("win_pct"),
                        f"{p}_roe": m.get("roe_mean"), f"{p}_pre": m.get("pre_mean"), f"{p}_payoff": m.get("payoff"),
                        f"{p}_growth": m["growth_log"], f"{p}_usd": m["usd"], f"{p}_dd": m.get("worst_dd"),
                        f"{p}_exits": " ".join(f"{k}{v}" for k, v in m.get("exits", {}).items())})
            if p == "select":
                tw = m.get("twin", {})
                row.update(select_twin_p90=(tw.get("log_p5_50_90_95") or [None] * 4)[2], select_twin_rank=tw.get("rank_pct"))
        tab.append(row)
    pd.DataFrame(tab).to_csv(f"{NL_REPO}/solo_table.csv", index=False, float_format="%.6g")
    print(json.dumps({"passing": out["passing"], "B1": out["B1"], "B0": out["B0"], "B3": out["B3"],
                      "timing": out["timing_s"]}, indent=1, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
