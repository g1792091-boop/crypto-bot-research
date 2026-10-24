"""PREREG5.md: the friend's rules on 15m and 30m signal bars (higher bars 1h | 4h), 30x, net ROE stops -50 / -75 / -90 %,
ladders L10 / L20 / L30 / L50, filters none / F4 / V / F4+V (96 settings), one position, the entry blocks, margin 40 %, with the
TetherMax payback added per trade outside the bot (90 %: +2.27 % net ROE per trade; 50 %: +1.26 %). The setting with the largest
monthly account growth at margin 40 % on 2020-03 .. 2024-12 (600 trades or more, payback 90 %) is read once on 2025-01 .. 2026-09.

    python3 -I frrun.py build     (once)
    python3 -I frpay.py           -> research/friendroc/results7.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frrun import ROWS, MARGIN, take, rnd, coin_flip
from frloss import table, PER, LEV
from frfamily import signals, outcomes, filt, STOPS, LADDERS, MIN_SELECT_N
from frdeep import per_stats
from frp30 import weekdays
import hashlib
from types import SimpleNamespace

TAKER = 0.00042
PAYBACK = {"p90": 0.90, "p50": 0.50}
REFUND = {k: LEV * 2 * TAKER * v for k, v in PAYBACK.items()}   # net ROE back per trade
FILTERS = ("none", "F4", "V", "F4+V")
TFS2 = ("15m", "30m")
assert MARGIN == 0.40


def mask(R, f):
    if f == "F4+V":
        return filt(R, "F4") & filt(R, "V")
    return filt(R, f)


def months_of(R, O, use, rf, lo, hi):
    t = R.t.to_numpy(np.int64)
    idx = take(t, O["k"], use & (t >= ms(lo + "-01")))
    mon = np.asarray(pd.to_datetime(t[idx] + KST, unit="ms").strftime("%Y-%m"))
    x = np.maximum(MARGIN * (LEV * O["r"][idx] + rf), -1.0)
    v = np.array([np.prod(1 + x[mon == q]) for q in pd.period_range(lo, hi, freq="M").strftime("%Y-%m")])
    return {"n": int(len(v)), "median": rnd(np.median(v), 3), "up": int((v > 1).sum()), "x2": int((v >= 2).sum()),
            "x4": int((v >= 4).sum()), "half_or_less": int((v <= 0.5).sum()), "worst": rnd(v.min(), 3), "best": rnd(v.max(), 3),
            "all_months_chained": rnd(float(np.prod(v)), 4)}


def detail(R, O, Oopp, use, rf):
    t = R.t.to_numpy(np.int64)
    out = table(t, O["k"], O["r"] + rf / LEV, O["why"], use)          # the payback as a shift of every trade's net return
    for pn, (a, z) in PER.items():
        idx = take(t, O["k"], use & (t >= a) & (t < z))
        out[pn]["per_weekday"] = rnd(len(idx) / weekdays(a, z), 2)
        out[pn]["hold_min_median"] = int(np.median(O["k"][idx] + 1)) if len(idx) else None
        if pn in ("confirm", "oct2026") and Oopp is not None:
            m = use & (t >= a) & (t < z)
            roe = LEV * O["r"][idx]
            growth = np.log1p(np.maximum(MARGIN * roe, -1 + 1e-12)).sum()
            out[pn]["twin"] = coin_flip(SimpleNamespace(t=t), m, O, Oopp, LEV, roe.mean(), growth)   # per-trade place: payback-free
    out["months_all"] = months_of(R, O, use, rf, "2020-03", "2026-09")
    out["months_2025"] = months_of(R, O, use, rf, "2025-01", "2026-09")
    return out


def main():
    want = open(os.path.join(RES_DIR, "PREREG5.md.sha256")).read().split()[0]
    sha = hashlib.sha256(open(os.path.join(RES_DIR, "PREREG5.md"), "rb").read()).hexdigest()
    assert sha == want, "PREREG5.md changed after it was frozen"
    res = {"prereg5_sha256": sha, "refund_net_roe_pct": {k: rnd(v * 100, 3) for k, v in REFUND.items()}}
    bnd = np.array([PER[pn] for pn in PER], np.int64)
    keys = list(PER)
    SIG, OUTS, rows = {}, {}, []
    for tf in TFS2:
        R = signals(tf)
        R = R[R.block == ""].reset_index(drop=True)
        SIG[tf] = R
        t = R.t.to_numpy(np.int64)
        for st in STOPS:
            for ln, (fl, step) in LADDERS.items():
                O = outcomes(R, st, fl, step)["own"]
                OUTS[(tf, st, ln)] = O
                ext = t + (O["k"].astype(np.int64) + 1) * MIN
                for f in FILTERS:
                    use = mask(R, f)
                    row = {"tf": tf, "stop": st, "ladder": ln, "filter": f}
                    for pk, rf in REFUND.items():
                        S = per_stats(t, ext, LEV * O["r"] + rf, use, bnd)
                        d = {}
                        for j, pn in enumerate(keys):
                            n, w, sm, gr = S[j]
                            months = (PER[pn][1] - PER[pn][0]) / DAY / 30.44
                            d[pn] = {"n": int(n), "win": rnd(w / n, 4) if n else None, "roe_pct": rnd(sm / n * 100, 3) if n else None,
                                     "mult40": rnd(np.exp(gr), 4), "growth_per_month": rnd(gr / months, 5)}
                        row[pk] = d
                    rows.append(row)
        print("tf", tf, "signals", len(R), flush=True)
    # the P check: 15m -50 % L10 none without payback = results.json P
    A = pd.read_pickle(ROWS)
    A = A[A.P & (A.block == "")].reset_index(drop=True)
    O = OUTS[("15m", -0.50, "L10")]
    assert np.array_equal(O["k"], A["L30_c042_own_k"].to_numpy()) and np.allclose(O["r"], A["L30_c042_own_r"].to_numpy(), atol=1e-15)
    ok = [r for r in rows if r["p90"]["select"]["n"] >= MIN_SELECT_N]
    ok.sort(key=lambda r: -r["p90"]["select"]["growth_per_month"])
    pick = ok[0]
    per_trade_best = max(ok, key=lambda r: r["p90"]["select"]["roe_pct"])
    res["settings"], res["eligible"] = len(rows), len(ok)
    res["both_halves_positive_p90"] = [r for r in rows if (r["p90"]["select"]["roe_pct"] or -1) > 0 and (r["p90"]["confirm"]["roe_pct"] or -1) > 0]
    res["both_halves_growing_p90"] = [r for r in rows if r["p90"]["select"]["mult40"] > 1 and r["p90"]["confirm"]["mult40"] > 1]
    res["top10_growth"] = ok[:10]
    res["per_trade_best"] = per_trade_best
    res["best_per_tf"] = {tf: max((r for r in ok if r["tf"] == tf), key=lambda r: r["p90"]["select"]["growth_per_month"]) for tf in TFS2}
    res["all"] = rows

    def show(tag, r):
        print(tag, r["tf"], r["stop"], r["ladder"], r["filter"],
              {pn: (r["p90"][pn]["n"], r["p90"][pn]["win"], r["p90"][pn]["roe_pct"], r["p90"][pn]["mult40"]) for pn in keys},
              "| p50 roe", {pn: r["p50"][pn]["roe_pct"] for pn in ("select", "confirm")}, flush=True)

    print("eligible", len(ok), "both halves positive p90", len(res["both_halves_positive_p90"]), "both growing", len(res["both_halves_growing_p90"]), flush=True)
    for r in ok[:10]:
        show(" top", r)
    show("PER-TRADE BEST", per_trade_best)
    for tf, r in res["best_per_tf"].items():
        show(f"best {tf}", r)
    for r in res["both_halves_positive_p90"]:
        show(" both+", r)
    # the pick
    tf, st, ln, f = pick["tf"], pick["stop"], pick["ladder"], pick["filter"]
    R = SIG[tf]
    fl, step = LADDERS[ln]
    O2 = outcomes(R, st, fl, step, sides=("own", "opp"))
    use = mask(R, f)
    det = {pk: detail(R, O2["own"], O2["opp"] if pk == "p90" else None, use, rf) for pk, rf in REFUND.items()}
    d = det["p90"]
    det["verdict"] = {"select_roe_positive": bool(d["select"]["roe_pct"] > 0), "confirm_roe_positive": bool(d["confirm"]["roe_pct"] > 0),
                      "confirm_account_grows": bool(d["confirm"]["mult40"] > 1), "confirm_twin_975": bool(d["confirm"]["twin"]["pct_below"] >= 0.975)}
    det["verdict"]["edge"] = all(det["verdict"].values())
    det["setting"] = {"tf": tf, "stop": st, "ladder": ln, "first_lock": fl, "step": step, "filter": f}
    res["pick"] = det
    print("PICK", det["setting"], flush=True)
    for pn in PER:
        v = d[pn]
        print(f"  {pn:8s} n{v['n']} w{v.get('win')} aw{v.get('avg_win_pct')} al{v.get('avg_loss_pct')} roe{v.get('roe_pct')} x{v.get('mult40')} "
              f"dd{v.get('maxdd40')} {v['per_weekday']}/d hold{v['hold_min_median']} twin {(v.get('twin') or {}).get('pct_below')}", flush=True)
    print("  months all", d["months_all"], "\n  months 2025", d["months_2025"], "\n  verdict", det["verdict"], flush=True)
    print("  p50", {pn: (det["p50"][pn].get("roe_pct"), det["p50"][pn].get("mult40")) for pn in PER}, det["p50"]["months_2025"], flush=True)
    # P (15m friend exits, no filter) with the payback, for reference
    RP = SIG["15m"]
    res["P_payback"] = {pk: detail(RP, OUTS[("15m", -0.50, "L10")], None, np.ones(len(RP), bool), rf) for pk, rf in REFUND.items()}
    pp = res["P_payback"]["p90"]
    print("P p90", {pn: (pp[pn]["n"], pp[pn].get("roe_pct"), pp[pn].get("mult40")) for pn in PER}, pp["months_2025"], flush=True)
    json.dump(res, open(os.path.join(RES_DIR, "results7.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
