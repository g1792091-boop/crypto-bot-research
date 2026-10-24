"""Friend-rule reads under measured trading costs (analysis only; nothing in research/friendroc is changed or rewritten).

The friendroc studies charge one round-trip cost inside the 1m walk (frcore / frdeep.walk3: taker 0.042 % + slippage 0.02 % a
side = 0.124 %; the net-ROE stop and the ladder are measured net of it) and add the TetherMax payback afterwards as a flat net-ROE
shift per trade (frmanual2.REFUND = lev x 2 x taker x 0.9). This script reruns the same walk and the same read code with each cost
scenario's round trip inside the walk and its own payback shift:

    A  assumed, payback 90 %      taker 4.20 bp + slip 2.00 bp a side, payback 0.9 x taker   (the studies' baseline)
    B  assumed, no payback        4.20 + 2.00
    C  WOO X Pro measured, paid   4.21 + 4.37, payback 0.9 x 4.21
    D  WOO X Pro measured         4.21 + 4.37
    E  Bybit measured             4.41 + 1.39

Rules: (1) the friend bot's chosen rule (frfinal2: original 15m signal, 1h OR 4h ROC9, 35x, net ROE -50 % stop, ladder 12 -> 10
then 5 % steps); (2) frlast19's "실거래로 정한 규칙 (1시간 RSI + ROC)" with its chosen exit (frfinal: screen -20 % stop, ladder);
(3a) K01 = "기준 B" of PREREG6 (frmore: 15m signal + 4h ADX >= 20 + quiet bar, 30x, net -75 % stop, ladder 20 / 10);
(3b) PREREG11's "B + 네 조건" (frladder35: the four bigger-trend conditions, one being 4h ADX >= 20, screen -20 % stop, ladder).
A screen stop stays at the same price distance under every cost (stop = -20 % - lev x round trip, as FEE_ROE does).
Reads: frbracket.detail (n, win, break-even win, net ROE per trade, margin-40 % multiple and max drawdown, the 90-day goal read),
run with its period table / leverage / payback swapped in. Scenario A is checked against results22 / 23 / 21 / 20 / 15 / 9 first;
the script stops (exit 1) on any mismatch. Also: the chosen rule's break-even all-in cost a side per period, two ways (the walk
run at that cost, no payback; and the levels held at the configured 0.124 % with the cost charged on top), and the chosen rule with the live executor's fixed levels (stop 1.3046 % and the ladder from its own fill with the
configured 0.124 % round trip; the measured costs charged on top).

    python3 -I -B analysis/review1024/costs/frcost.py      -> analysis/review1024/costs/frcost.json, frcost_table.csv"""
import os, sys
from contextlib import contextmanager
_COSTS_DIR = os.path.dirname(os.path.abspath(__file__))
_FR = os.path.abspath(os.path.join(_COSTS_DIR, "..", "..", "..", "research", "friendroc", "code"))
sys.path.insert(0, _FR)
from frcore import *                                       # np, pd, json, ms, KST, DAY, COINS, blocked, ...
from frrun import rnd
from frloss import PER, FL, COST as COST0, LEV as LEV30
from frfamily import signals, outcomes as fam_outcomes
from frmanual2 import LEV as LEV35, REFUND as REFUND35, TAKER
from frhtrend import raw15
from frhtrend2 import add_rsi
from frpay import mask, REFUND as REFUND30
from frtrend4 import trend_columns, conditions
import frladder35 as L35
import frbracket as FB

RESDIR = os.path.abspath(os.path.join(_FR, ".."))
SCEN = {                                                   # commission, slippage (a side), payback share of the commission
    "A": (0.00042, 0.00020, 0.9), "B": (0.00042, 0.00020, 0.0), "C": (0.000421, 0.000437, 0.9),
    "D": (0.000421, 0.000437, 0.0), "E": (0.000441, 0.000139, 0.0)}
SCEN_KO = {"A": "가정 + 페이백", "B": "가정, 페이백 없음", "C": "WOO 실측 + 페이백", "D": "WOO 실측", "E": "바이비트 실측"}
WIN = {"last19": PER["last19"], "oct2026": PER["oct2026"], "ytd2026": (ms("2026-01-01") - KST, ms("2026-10-23") - KST),
       "confirm": PER["confirm"], "select": PER["select"]}
WIN_KO = {"last19": "19일", "oct2026": "10월", "ytd2026": "2026 1/1~10/22", "confirm": "2025-01~2026-09", "select": "2020-03~2024-12"}
CFG_RT = 2 * (0.00042 + 0.0002)                            # the live executor's configured round trip (docs/friend-bot-ko.md 7)
BE_GRID = np.round(np.arange(-10.0, 14.01, 0.5), 2)        # all-in cost a side, bp


def rt(sc):
    f, s, _ = SCEN[sc]
    return 2 * (f + s)


def refund(sc, lev):
    f, _, p = SCEN[sc]
    return lev * 2 * f * p


def eff_bp(sc):
    f, s, p = SCEN[sc]
    return (f * (1 - p) + s) * 1e4


@contextmanager
def patched(mod, **kw):
    old = {k: getattr(mod, k) for k in kw}
    for k, v in kw.items():
        setattr(mod, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(mod, k, v)


def out35(R, roe_stop, cost):
    """frladder35.outcomes (35x, ladder FL / 5 % / 2 %) with the walk's round trip set to cost."""
    with patched(L35, COST=cost):
        return L35.outcomes(R, roe_stop, FL)


def read(R, O, use, lev, rf, margin=0.40):
    """frbracket.detail over WIN with this leverage, payback shift and margin."""
    with patched(FB, PER=WIN, LEV=lev, REFUND=rf, MARGIN=margin):
        return FB.detail(R, O, use)


# ====================================================================== the rules
def frames():
    A = signals("15m")
    P = A[A.block == ""].reset_index(drop=True)            # frfinal2 / frmore / frladder35 rows
    P4 = trend_columns(P)
    t4 = np.logical_and.reduce(list(conditions(P4).values()))
    k01 = mask(P, "F4+V")
    B = add_rsi(pd.concat([raw15(c) for c in COINS], ignore_index=True))
    B = B.iloc[np.lexsort((B.coin.to_numpy(), B.t.to_numpy()))].reset_index(drop=True)
    with np.errstate(invalid="ignore"):
        B = B[(B.roc_1h.to_numpy() > 0) & (B.rsi_1h.to_numpy() > 0)].reset_index(drop=True)
    B["block"] = [blocked(int(x)) for x in B.t.to_numpy()]
    R2 = B[B.block == ""].reset_index(drop=True)           # frfinal rows
    print("rows: P", len(P), "rule2", len(R2), "K01", int(k01.sum()), "four", int(t4.sum()), flush=True)
    return {"chosen": (P, np.ones(len(P), bool)), "rule2": (R2, np.ones(len(R2), bool)),
            "k01": (P[k01].reset_index(drop=True), None), "four": (P4[t4].reset_index(drop=True), None)}


RULES = {   # name: (label, leverage, how to walk it at a round trip c)
    "chosen": ("① 친구 봇 규칙 (1h|4h ROC, 35배, 순 −50, 계단 10/5)", LEV35, lambda R, c: out35(R, -0.50, c)),
    "rule2": ("② 실거래로 정한 규칙 (1시간 RSI + ROC, 35배, 화면 −20, 계단)", LEV35, lambda R, c: out35(R, -0.20 - LEV35 * c, c)),
    "k01": ("③a K01 기준 B (4h ADX ≥ 20 + 조용한 봉, 30배, 순 −75, 계단 20/10)", LEV30,
            lambda R, c: fam_outcomes(R, -0.75, 0.20, 0.10, cost=c)["own"]),
    "four": ("③b PREREG11 B 네 조건 (35배, 화면 −20, 계단 10/5)", LEV35, lambda R, c: out35(R, -0.20 - LEV35 * c, c)),
}


# ====================================================================== scenario A against the stored results
def check_A(res):
    J = lambda f: json.load(open(os.path.join(RESDIR, f)))
    bad = []

    def cmp(tag, got, want, keys, strict=True):
        """strict: the stored file was written by the same read code (same rounding) -> equal; else within its rounding."""
        for k in keys:
            if want.get(k) is None:
                continue
            g, w = got.get(k), want[k]
            tol = 0.0 if strict or k == "n" else (0.0051 if k == "roe_pct" else 1.01e-3)
            if g is None or abs(g - w) > tol + 1e-9:
                bad.append(f"{tag} {k}: got {g}, stored {w}")

    K = ("n", "win", "breakeven_win", "roe_pct", "mult40", "maxdd40")
    r22, r20, r15, r9 = J("results22.json"), J("results20.json"), J("results15.json"), J("results9.json")
    for p in ("oct2026", "last19", "select", "confirm"):
        cmp(f"results22 {p}", res["chosen"]["A"][p], r22[p], K)
        cmp(f"results20 {p}", res["rule2"]["A"][p], r20[p], K)
        cmp(f"results15 {p}", res["four"]["A"][p], r15["runs"]["B + 네 조건 · 계단 (순ROE) · 손절 −20"][p], K)
        b = r9["runs"]["B"][p]
        cmp(f"results9 {p}", res["k01"]["A"][p], {"n": b["n"], "win": b["win"], "roe_pct": b["roe_pct"], "mult40": b["m40"]["mult"],
                                                 "maxdd40": b["m40"]["maxdd"]}, K)
    for k in ("to_10pct_or_less", "x4", "x10"):
        cmp("results22 goal90", res["chosen"]["A"]["goal90"], r22["goal90"], (k,))
        cmp("results20 goal90", res["rule2"]["A"]["goal90"], J("results20.json")["goal90"], (k,))
        cmp("results15 goal90", res["four"]["A"]["goal90"], r15["runs"]["B + 네 조건 · 계단 (순ROE) · 손절 −20"]["goal90"], (k,))
    y = J("results23.json")["② 수정한 말 (1시간 또는 4시간, ROC만) = 지금 봇"]
    got = res["chosen"]["A"]["ytd2026"]
    cmp("results23 ② with payback", got, y["with_payback"], ("n", "win", "roe_pct", "mult40", "maxdd40"), strict=False)
    rows = J("results21.json")["rows"]
    for entry, ex, rule in (("처음 친구 신호 (1시간 또는 4시간 ROC)", "계단 · 손절 순 −50", "chosen"),
                            ("실거래로 정한 규칙 (1시간 RSI + ROC)", "계단 · 손절 −20", "rule2")):
        r = next(x for x in rows if x["entry"] == entry and x["cond"] == "조건 없음" and x["exit"] == ex)["19일"]
        g = res[rule]["A"]["last19"]
        cmp(f"results21 {rule}", g, r, ("n", "win", "roe_pct", "mult40", "maxdd40"), strict=False)
    return bad


# ====================================================================== main
def main():
    assert abs(rt("A") - COST0) < 1e-15 and abs(refund("A", LEV35) - REFUND35) < 1e-15 and abs(refund("A", LEV30) - REFUND30["p90"]) < 1e-15
    assert TAKER == SCEN["A"][0]
    F = frames()
    res, keep = {}, {}
    # scenario A first, checked against the stored results
    for rn, (lab, lev, walk) in RULES.items():
        R, use = F[rn]
        use = np.ones(len(R), bool) if use is None else use
        O = walk(R, rt("A"))
        res[rn] = {"label": lab, "A": read(R, O, use, lev, refund("A", lev))}
        keep[rn] = (R, use, lev, walk)
    bad = check_A(res)
    if bad:
        print("SCENARIO A DOES NOT MATCH THE STORED RESULTS:", *bad, sep="\n  ", flush=True)
        json.dump({"mismatch": bad}, open(os.path.join(_COSTS_DIR, "frcost_mismatch.json"), "w"), ensure_ascii=False, indent=1)
        sys.exit(1)
    print("scenario A reproduces results22 / 23 / 21 / 20 / 15 / 9", flush=True)
    for rn, (R, use, lev, walk) in keep.items():
        for sc in "BCDE":
            O = walk(R, rt(sc))
            res[rn][sc] = read(R, O, use, lev, refund(sc, lev))
        if rn == "k01":                                     # where K01 was read before: margin 10 %
            res[rn]["margin10"] = {}
            for sc in "ACD":
                O = walk(R, rt(sc))
                d = read(R, O, use, lev, refund(sc, lev), margin=0.10)
                res[rn]["margin10"][sc] = {p: {"mult": d[p]["mult40"], "maxdd": d[p]["maxdd40"]} for p in WIN}
        print("done", rn, flush=True)
    # the chosen rule with the executor's fixed levels: walk at the configured round trip + entry slippage, then the real costs
    R, use, lev, walk = keep["chosen"]
    res["chosen_executor"] = {}
    for sc in SCEN:
        f, s, _ = SCEN[sc]
        c_lv = CFG_RT + s
        O = walk(R, c_lv)
        O = dict(O, r=np.maximum(O["r"] + c_lv - rt(sc), -1.0 / lev))
        res["chosen_executor"][sc] = read(R, O, use, lev, refund(sc, lev))
    # break-even all-in cost a side for the chosen rule (walk at 2 x cost, no payback)
    curve = {p: [] for p in WIN}
    t = R.t.to_numpy(np.int64)
    for bp in BE_GRID:
        O = walk(R, 2 * bp * 1e-4)
        for p, (a, z) in WIN.items():
            idx = FB.take(t, O["k"], use & (t >= a) & (t < z))
            curve[p].append(float((lev * O["r"][idx]).mean() * 100))
    be = {}
    for p, v in curve.items():
        v = np.array(v)
        sgn = np.flatnonzero(np.diff(np.sign(v)) != 0)
        cross = [float(BE_GRID[i] + (BE_GRID[i + 1] - BE_GRID[i]) * v[i] / (v[i] - v[i + 1])) for i in sgn]
        be[p] = {"breakeven_bp_side": rnd(cross[0], 2) if len(cross) == 1 else (None if not cross else [rnd(x, 2) for x in cross]),
                 "below_grid": bool((v < 0).all()), "above_grid": bool((v > 0).all())}
    res["breakeven"] = {"grid_bp": BE_GRID.tolist(), "roe_pct": {p: [rnd(x, 3) for x in v] for p, v in curve.items()}, "cross": be}
    # the same with the bot's levels held where the executor puts them (stop and ladder at the configured 0.124 %, here from the
    # entry minute's open) and an all-in cost x a side charged on top: mean net ROE = lev x (mean r + 0.124 % - 2x), one x per
    # period, no change in which trades are taken (the walk-at-cost curve above moves the levels and so the trades)
    OA = walk(R, CFG_RT)
    fixed = {}
    for p, (a, z) in WIN.items():
        idx = FB.take(t, OA["k"], use & (t >= a) & (t < z))
        fixed[p] = rnd(float((OA["r"][idx].mean() + CFG_RT) / 2 * 1e4), 2)
    res["breakeven"]["fixed_levels_bp_side"] = fixed
    res["scenarios"] = {sc: {"label": SCEN_KO[sc], "commission_bp": SCEN[sc][0] * 1e4, "slip_bp": SCEN[sc][1] * 1e4, "payback": SCEN[sc][2],
                             "round_trip_pct": rnd(rt(sc) * 100, 4), "allin_bp_side": rnd(eff_bp(sc), 3),
                             "payback_roe_pct_35x": rnd(refund(sc, LEV35) * 100, 3), "payback_roe_pct_30x": rnd(refund(sc, LEV30) * 100, 3)}
                        for sc in SCEN}
    res["windows_kst"] = {p: [str(pd.Timestamp(a + KST, unit="ms")), str(pd.Timestamp(z + KST, unit="ms"))] for p, (a, z) in WIN.items()}
    # the table
    rows = []
    for rn in RULES:
        for p in WIN:
            for sc in SCEN:
                d = res[rn][sc][p]
                rows.append({"rule": rn, "period": p, "scenario": sc, "n": d["n"], "win": d["win"], "breakeven_win": d["breakeven_win"],
                             "roe_pct": d["roe_pct"], "mult40": d["mult40"], "maxdd40": d["maxdd40"],
                             "to_10pct_90d": res[rn][sc]["goal90"]["to_10pct_or_less"], "x4_90d": res[rn][sc]["goal90"]["x4"]})
    for p in WIN:
        for sc in SCEN:
            d = res["chosen_executor"][sc][p]
            rows.append({"rule": "chosen_executor", "period": p, "scenario": sc, "n": d["n"], "win": d["win"],
                         "breakeven_win": d["breakeven_win"], "roe_pct": d["roe_pct"], "mult40": d["mult40"], "maxdd40": d["maxdd40"],
                         "to_10pct_90d": res["chosen_executor"][sc]["goal90"]["to_10pct_or_less"],
                         "x4_90d": res["chosen_executor"][sc]["goal90"]["x4"]})
    pd.DataFrame(rows).to_csv(os.path.join(_COSTS_DIR, "frcost_table.csv"), index=False)
    for rn in list(RULES) + ["chosen_executor"]:
        print("==", res[rn]["label"] if rn in RULES else "① 실행기 고정 자리", flush=True)
        for p in WIN:
            print(f"  {WIN_KO[p]:16s}", " | ".join(f"{sc} n{res[rn][sc][p]['n']} w{res[rn][sc][p]['win']} be{res[rn][sc][p]['breakeven_win']} "
                                                   f"roe{res[rn][sc][p]['roe_pct']} x{res[rn][sc][p]['mult40']} dd{res[rn][sc][p]['maxdd40']}"
                                                   for sc in SCEN), flush=True)
        print("  goal90 to10%:", {sc: res[rn][sc]["goal90"]["to_10pct_or_less"] for sc in SCEN}, flush=True)
    print("break-even bp a side (walk at that cost):", {p: v["breakeven_bp_side"] for p, v in be.items()}, flush=True)
    print("break-even bp a side (levels fixed at 0.124 %):", fixed, flush=True)
    for d in (res[rn][sc] for rn in list(RULES) + ["chosen_executor"] for sc in SCEN):
        d.pop("months", None)
    json.dump(res, open(os.path.join(_COSTS_DIR, "frcost.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
