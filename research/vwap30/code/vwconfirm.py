"""Step 7 of PREREG.md: the frozen finalists (finalists.json, sha256 checked) run once on the confirm period
(2025-01-01 .. 2026-09-30) and the live period (2026-10-01 .. 10-20), with the coin-flip twin (1,000 random-side
draws, seed 20261023) and the verdict. Then reads that choose nothing (marked 참고): cost, every timeframe at the
rule bot's exits, splits. Writes research/vwap30/results.json.

    python3 -I vwconfirm.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwstages import *

SEED, DRAWS = 20261023, 1000
PERIODS["c2025"] = (ms("2025-01-01"), ms("2026-01-01"))
PERIODS["c2026"] = (ms("2026-01-01"), ms("2026-10-01"))
PERIODS["all"] = (SEL[0], CONF[1])
KEYS = ("n", "per_weekday", "per_day", "win", "avgR", "avg_winR", "avg_lossR", "payoff", "pf", "avg_win_pct",
        "avg_loss_pct", "growth", "mult", "cagr", "maxdd", "mon_median", "mon_x6", "mon_worst", "mon_best", "mon_pos",
        "months", "ruin", "lev_med")


def pick(x):
    return rnd({k: x[k] for k in KEYS if k in x})


def mask_of(book, bundle):
    m = np.ones(len(book.entry), bool)
    Fs = filters(book.F)
    for nm in bundle:
        m &= Fs[nm]
    return m


def twin(book, m, j, per):
    rng = np.random.default_rng(SEED)
    g = np.empty(DRAWS)
    for k in range(DRAWS):
        flip = rng.random(len(book.entry)) < 0.5
        g[k] = metrics(book, m, j, per, flip=flip, full=False)["growth"]
    return g


def cost_read(book, m, j, per):
    """참고: mean R with the round-trip cost added back (0 %) and at a maker-like 0.04 % round trip."""
    a, b = PERIODS[per]
    idx, net, ext, D = trades(book, m & (book.entry >= a) & (book.entry < b), j)
    return {"avgR_now": round(float((net / D).mean()), 4),
            "avgR_no_cost": round(float(((net + COST_RT) / D).mean()), 4),
            "avgR_rt_0.04%": round(float(((net + COST_RT - 0.0004) / D).mean()), 4),
            "win_no_cost": round(float((net + COST_RT > 0).mean()), 4), "n": int(len(idx))}


def splits(book, m, j, per):
    F = book.F
    out = {}
    for c in COINS:
        out[c[:-4]] = pick(metrics(book, m & (F.coin.to_numpy() == c), j, per))
    out["롱"] = pick(metrics(book, m & (F.side.to_numpy() > 0), j, per))
    out["숏"] = pick(metrics(book, m & (F.side.to_numpy() < 0), j, per))
    out["평일"] = pick(metrics(book, m & ~F.weekend.to_numpy(bool), j, per))
    out["주말"] = pick(metrics(book, m & F.weekend.to_numpy(bool), j, per))
    return out


def main():
    fp = os.path.join(RES_DIR, "finalists.json")
    want = open(fp + ".sha256").read().split()[0]
    got = hashlib.sha256(open(fp, "rb").read()).hexdigest()
    assert want == got, "finalists.json changed after it was frozen"
    fin = json.load(open(fp))["finalists"]
    books = {tf: Book(tf) for tf in TF_MIN}
    res = []
    for f in fin:
        b = books[f["tf"]]
        m = mask_of(b, f["bundle"])
        j = f["exit"]
        row = dict(f)
        for per in ("select", "confirm", "c2025", "c2026", "live"):
            row[per] = pick(metrics(b, m, j, per))
        tw = twin(b, m, j, "confirm")
        p90 = float(np.percentile(tw, 90))
        g = row["confirm"]["growth"]
        row["twin"] = {"p10": round(float(np.percentile(tw, 10)), 3), "p50": round(float(np.median(tw)), 3),
                       "p90": round(p90, 3), "share_below": round(float((tw < g).mean()), 3)}
        row["verdict"] = "통함" if (row["confirm"]["avgR"] > 0 and g > p90) else "통하지 않음"
        row["sizing_confirm"] = [rnd({"r": r, **{k: v for k, v in metrics(b, m, j, "confirm", r=r).items() if k in (
            "mult", "cagr", "mon_median", "mon_x6", "mon_worst", "mon_best", "maxdd", "ruin", "lev_med")}})
            for r in list(R_GRID) + ["owners"]]
        row["sizing_live"] = [rnd({"r": r, **{k: v for k, v in metrics(b, m, j, "live", r=r).items() if k in (
            "mult", "maxdd", "ruin")}}) for r in list(R_GRID) + ["owners"]]
        row["splits_confirm"] = splits(b, m, j, "confirm")
        row["cost_select"] = cost_read(b, m, j, "select")
        row["cost_confirm"] = cost_read(b, m, j, "confirm")
        res.append(row)
        print(f["name"], f["tf"], f["exit_ko"], "| confirm n", row["confirm"]["n"], "win", row["confirm"]["win"],
              "R", row["confirm"]["avgR"], "g", g, "twin p90", round(p90, 2), "->", row["verdict"], flush=True)
    # 참고 reads (choose nothing)
    extra = {"tf_house": {}, "tf_b3": {}, "weekday_house_30m": {}}
    for tf, b in books.items():
        allm = np.ones(len(b.entry), bool)
        extra["tf_house"][tf] = {per: pick(metrics(b, allm, EX_B1, per)) for per in ("select", "confirm", "live")}
        extra["tf_b3"][tf] = {per: pick(metrics(b, allm, EX_B3, per)) for per in ("select", "confirm", "live")}
        extra.setdefault("cost_b3", {})[tf] = {per: cost_read(b, allm, EX_B3, per) for per in ("select", "confirm")}
        extra.setdefault("cost_house", {})[tf] = {per: cost_read(b, allm, EX_B1, per) for per in ("select", "confirm")}
    b = books["30m"]
    wd = ~b.F.weekend.to_numpy(bool)
    for nm, j in (("B1", EX_B1), ("B2", EX_B2)):
        extra["weekday_house_30m"][nm] = {per: pick(metrics(b, wd, j, per)) for per in ("select", "confirm", "live")}
    # the 4h exit grid on confirm (참고: how the select ranking held up, all 258)
    b4 = books["4h"]
    m4 = np.ones(len(b4.entry), bool)
    rank = []
    for e in EXITS:
        s_ = metrics(b4, m4, e["id"], "select", full=False)["growth"]
        c_ = metrics(b4, m4, e["id"], "confirm")
        rank.append({"exit": e["id"], "exit_ko": exit_name(e["id"]), "g_select": round(s_, 3),
                     "g_confirm": round(c_["growth"], 3), "avgR_confirm": round(c_["avgR"], 4), "win_confirm": round(c_["win"], 4)})
    extra["exit_grid_4h_select_vs_confirm"] = rank
    # 참고: how much of the step-5 4h pick rests on its biggest trades, and the same exit on the other timeframes
    j4 = next(f["exit"] for f in fin if f["tf"] == "4h") if any(f["tf"] == "4h" for f in fin) else None
    if j4 is not None:
        rb = {}
        for per in ("select", "confirm"):
            a, z = PERIODS[per]
            idx, net, ext, D = trades(b4, m4 & (b4.entry >= a) & (b4.entry < z), j4)
            R = net / D
            o = np.argsort(-R)
            Fp = b4.F.iloc[idx]
            rb[per] = {"n": int(len(R)), "sumR": round(float(R.sum()), 1),
                       "top_share": {k: round(float(R[o[:k]].sum() / R.sum()), 3) for k in (1, 3, 5)},
                       "avgR_without_top5": round(float(R[o[5:]].mean()), 4),
                       "avgR_cost_x2": round(float(((net - COST_RT) / D).mean()), 4),
                       "top5": [{"coin": Fp.coin.iloc[t][:-4], "side": int(Fp.side.iloc[t]),
                                 "date": str(pd.to_datetime(Fp.bar_close.iloc[t], unit="ms"))[:10], "R": round(float(R[t]), 1)}
                                for t in o[:5]]}
        rb["same_exit_other_tf"] = {tf: {per: pick(metrics(books[tf], np.ones(len(books[tf].entry), bool), j4, per))
                                         for per in ("select", "confirm", "live")} for tf in ("15m", "30m", "1h")}
        extra["robust_4h_pick"] = rb
    sel = json.load(open(os.path.join(OUT, "select.json")))
    out = {"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "finalists_sha256": got,
           "n_configs_select": sel["n_configs"], "finalists": res, "extra": extra,
           "select": {k: sel[k] for k in ("step1", "step2", "keep", "step6")},
           "select_filters": {tf: {"base": v["base"], "filters": v["filters"], "passed": v["passed"], "bundle": v["bundle"],
                                   "exit_top3": v["exit_top3"], "exit_grid": v["exit_grid"]} for tf, v in sel["step345"].items()}}
    json.dump(out, open(os.path.join(RES_DIR, "results.json"), "w"), ensure_ascii=False, indent=1, default=float)
    print("written results.json")


if __name__ == "__main__":
    main()
