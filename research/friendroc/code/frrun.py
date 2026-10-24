"""The friend's 15m EMA / RSI / ROC study, as pre-registered in research/friendroc/PREREG.md and PREREG_AMEND1.md.

    python3 -I frrun.py build [--procs 3]   signals + outcomes of every signal row -> OUT/rows.pkl (scratchpad)
    python3 -I frrun.py study               accounts, coin-flip twins, months, examples -> research/friendroc/results.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from vwacct import _take                                  # the one-position pass (signals in entry order)
import hashlib
from multiprocessing import Pool

ROWS = os.path.join(OUT, "rows.pkl")
PERS = {"last19": (ms("2026-10-04"), DATA_END), "oct2026": (ms("2026-10-01"), DATA_END),
        "select": (ms("2020-03-01"), ms("2025-01-01")), "confirm": (ms("2025-01-01"), ms("2026-10-01")),
        "fiveyear": (ms("2020-03-01"), ms("2026-10-01"))}
MARGIN = 0.40
DRAWS, SEED = 2000, 20261024
MAE_LINE = -0.20


def build_coin(coin):
    t0 = time.time()
    R = coin_signals(coin)
    O = coin_outcomes(coin, R)
    print("built", coin, len(R), {q: int(R[q].sum()) for q in SETS}, f"{time.time() - t0:.0f}s", flush=True)
    return pd.concat([R, O], axis=1)


def build(procs):
    assert check_lock()
    with Pool(procs) as pool:
        parts = pool.map(build_coin, COINS)
    A = pd.concat(parts, ignore_index=True)
    A = A.iloc[np.lexsort((A.coin.to_numpy(), A.t.to_numpy()))].reset_index(drop=True)
    A["block"] = [blocked(int(x)) for x in A.t.to_numpy()]
    A.to_pickle(ROWS)
    print("rows", len(A), "blocked", A.block.value_counts().to_dict(), flush=True)


# ====================================================================== the account pass and its numbers
class Book:
    def __init__(self, A):
        self.A = A
        self.t = A.t.to_numpy(np.int64)
        self.coin = A.coin.to_numpy()
        self.side = A.side.to_numpy()
        kst = pd.to_datetime(self.t + KST, unit="ms")
        self.month = np.asarray(kst.strftime("%Y-%m"))

    def leg(self, xn, cn, sn):
        p = f"{xn}_{cn}_{sn}"
        return {q: self.A[f"{p}_{q}"].to_numpy() for q in ("r", "k", "why", "mae", "mfe")}


def take(t, k, use):
    return _take(t, t + (k.astype(np.int64) + 1) * MIN, use)


def rnd(x, n=4):
    return None if x is None or not np.isfinite(x) else round(float(x), n)


def summary(B, use, own, opp, lev, a, z, twin=True, splits=True):
    m = use & (B.t >= a) & (B.t < z)
    idx = take(B.t, own["k"], m)
    r = own["r"][idx]
    roe = lev * r
    n = len(idx)
    out = {"candidates": int(m.sum()), "n": n}
    months = (z - a) / DAY / 30.44
    out["per_month"] = rnd(n / months, 1)
    if not n:
        return out
    win = roe > 0
    w, lo = roe[win], roe[~win]
    x = np.maximum(MARGIN * roe, -1.0)
    eq = np.cumprod(1 + x)
    dd = float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min())
    why = own["why"][idx]
    hold = own["k"][idx] + 1
    aw, al = (float(w.mean()) if len(w) else np.nan), (float(lo.mean()) if len(lo) else np.nan)
    out.update({
        "wins": int(win.sum()), "losses": int((~win).sum()), "win": rnd(win.mean()),
        "roe_pct": rnd(roe.mean() * 100, 3), "net_pct": rnd(r.mean() * 100, 4),
        "avg_win_roe_pct": rnd(aw * 100, 2), "avg_loss_roe_pct": rnd(al * 100, 2),
        "breakeven_win": rnd(-al / (aw - al)) if len(w) and len(lo) else None,
        "mult40": rnd(eq[-1], 4), "maxdd40": rnd(dd), "growth40": rnd(np.log1p(np.maximum(x, -1 + 1e-12)).sum(), 3),
        "winners_below_m20": rnd((own["mae"][idx][win] < MAE_LINE).mean()) if win.any() else None,
        "exits": {REASONS[j]: int((why == j).sum()) for j in range(4)},
        "hold_min_median": int(np.median(hold)), "hold_min_p90": int(np.percentile(hold, 90)),
    })
    if splits:
        cs = B.coin[idx]
        ss = B.side[idx]
        out["by_coin"] = {COINS[c][:-4]: {"n": int((cs == c).sum()), "win": rnd(win[cs == c].mean()),
                                          "roe_pct": rnd(roe[cs == c].mean() * 100, 2)} for c in range(6) if (cs == c).any()}
        out["by_side"] = {nm: {"n": int((ss == sv).sum()), "win": rnd(win[ss == sv].mean()),
                               "roe_pct": rnd(roe[ss == sv].mean() * 100, 2)} for nm, sv in (("long", 1), ("short", -1))
                          if (ss == sv).any()}
    if twin:
        out["twin"] = coin_flip(B, m, own, opp, lev, roe.mean(), out["growth40"])
    return out


def coin_flip(B, m, own, opp, lev, roe_mean, growth):
    """PREREG twin: every candidate of the period gets its side by a coin (p 1/2), same exits, one position; 2,000
    draws, seed 20261024. Returns where the strategy's per-trade net ROE (and growth at margin 40 %) sits."""
    rng = np.random.default_rng(SEED)
    j = np.flatnonzero(m)
    t = B.t[j]
    r1, r2, k1, k2 = own["r"][j], opp["r"][j], own["k"][j], opp["k"][j]
    every = np.ones(len(j), bool)
    tm, tg = np.empty(DRAWS), np.empty(DRAWS)
    for d in range(DRAWS):
        f = rng.random(len(j)) < 0.5
        r = np.where(f, r2, r1)
        k = np.where(f, k2, k1)
        idx = take(t, k, every)
        roe = lev * r[idx]
        tm[d] = roe.mean() if len(idx) else np.nan
        tg[d] = np.log1p(np.maximum(MARGIN * roe, -1 + 1e-12)).sum()
    return {"roe_pct_median": rnd(np.nanmedian(tm) * 100, 3), "roe_pct_p975": rnd(np.nanpercentile(tm, 97.5) * 100, 3),
            "pct_below": rnd((tm < roe_mean).mean()), "growth40_median": rnd(np.median(tg), 2),
            "growth40_pct_below": rnd((tg < growth).mean())}


def monthly(B, use, own, lev):
    """vwmonth2.py's form: one pass from 2020-03-01 UTC to the data end, each KST month of the entry from 1 at margin
    40 %; 2020-03 .. 2026-09 (79 months) and 2026-10 apart."""
    m = use & (B.t >= ms("2020-03-01"))
    idx = take(B.t, own["k"], m)
    x = np.maximum(MARGIN * lev * own["r"][idx], -1.0)
    mon = B.month[idx]
    rows = []
    for q in pd.period_range("2020-03", "2026-10", freq="M").strftime("%Y-%m"):
        xs = x[mon == q]
        rows.append({"month": q, "n": int(len(xs)), "mult": round(float(np.prod(1 + xs)), 4)})
    full = [r for r in rows if r["month"] < "2026-10"]
    mm = np.array([r["mult"] for r in full])
    return {"months": len(full), "x2_or_more": int((mm >= 2).sum()), "plus": int((mm > 1).sum()),
            "minus": int((mm < 1).sum()), "lost_half": int((mm < 0.5).sum()), "lost_90pct": int((mm < 0.1).sum()),
            "median": rnd(np.median(mm)), "worst": rnd(mm.min()), "worst_month": full[int(mm.argmin())]["month"],
            "best": rnd(mm.max()), "best_month": full[int(mm.argmax())]["month"],
            "oct_2026": rows[-1]["mult"], "oct_2026_n": rows[-1]["n"], "rows": rows}


def examples(B, use, own):
    """PREREG: the first three trades P took in the 19 days, with the indicator values."""
    a, z = PERS["last19"]
    idx = take(B.t, own["k"], use & (B.t >= a) & (B.t < z))[:3]
    out = []
    utc = lambda v: str(pd.Timestamp(int(v), unit="ms"))[:16]
    kst = lambda v: str(pd.Timestamp(int(v) + KST, unit="ms"))[:16]
    for i in idx:
        r = B.A.iloc[i]
        out.append({
            "signal_bar_utc": f"{utc(r.bar_open)} ~ {utc(r.t)[11:]}", "entry_utc": utc(r.t), "entry_kst": kst(r.t),
            "coin": COINS[int(r.coin)][:-4], "side": "long" if r.side > 0 else "short",
            "close": rnd(r.close, 6), "entry_px": rnd(r.entry_px, 6),
            "ema21": rnd(r.e21, 6), "ema21_prev": rnd(r.e21p, 6), "ema52": rnd(r.e52, 6), "ema52_prev": rnd(r.e52p, 6),
            "rsi26": rnd(r.rsi, 3), "roc9_prev": rnd(r.rocp, 4), "roc9": rnd(r.roc, 4),
            "h1_bar_utc": utc(r["1h_ts"]), "h1_roc9": rnd(r["1h_roc"], 4), "h1_roc9_prev": rnd(r["1h_rocp"], 4),
            "h1_rsi26": rnd(r["1h_rsi"], 3),
            "h4_bar_utc": utc(r["4h_ts"]), "h4_roc9": rnd(r["4h_roc"], 4), "h4_roc9_prev": rnd(r["4h_rocp"], 4),
            "h4_rsi26": rnd(r["4h_rsi"], 3),
            "exit": REASONS[int(own["why"][i])], "minutes": int(own["k"][i]) + 1, "net_roe_pct": rnd(30 * own["r"][i] * 100, 2)})
    return out


def parity_check(n=600):
    """The walk against the repository's vectorized stop / ladder pass (research/vwap30/code/vwfix2.py outcomes_tf,
    with the -50 % net stop in place of 2 ATR) on BTC's first n P signals, 96-bar cap, funding 0 (the vectorized pass
    leaves funding out of the levels; the walk puts it in, as paperbot/ladder.py net_roe does)."""
    from vwbuild import lock_house
    A = pd.read_pickle(ROWS)
    S = A[(A.coin == 0) & A.P].iloc[:n]
    g = grid("BTCUSDT")
    o, h, l, c = (np.ascontiguousarray(g[x], dtype=np.float64) for x in ("o", "h", "l", "c"))
    cumf = np.zeros(g["n"])
    cost, lev, W = COSTS["c042"], 30.0, 96 * 15
    same, dmax = 0, 0.0
    for side in (1, -1):
        es = S.e.to_numpy(np.int64)[(S.side == side).to_numpy()]
        r, k, _, _, _ = walk(o, h, l, c, cumf, es, side, lev, cost, 0.10, 0.05, 0.02, W, g["n"])
        idx = np.minimum(es[:, None] + np.arange(W)[None, :], g["n"] - 1)
        p0 = o[es][:, None]
        UP = (h[idx] / p0 - 1) if side > 0 else (1 - l[idx] / p0)
        DN = (l[idx] / p0 - 1) if side > 0 else (1 - h[idx] / p0)
        OP, CL = side * (o[idx] / p0 - 1), side * (c[idx] / p0 - 1)
        RMUp = np.concatenate([np.zeros((len(es), 1)), np.maximum.accumulate(UP, axis=1)[:, :-1]], axis=1)
        lk = lock_house(lev * (RMUp - cost))
        level = np.maximum(np.where(np.isnan(lk), -np.inf, lk / lev + cost), -0.5 / lev + cost)
        hit = DN <= level
        th = np.where(hit.any(1), hit.argmax(1), W + 1)
        rows = np.arange(len(es))
        tc = np.minimum(th, W - 1)
        v = np.where(th < W, np.minimum(level[rows, tc], OP[rows, tc]), CL[rows, W - 1])
        same += int((tc == k).sum())
        dmax = max(dmax, float(np.abs(v - cost - r).max()))
    return {"signals": int(len(S)), "same_exit_minute": same, "max_abs_diff_net": dmax}


def verdict(row, sel, conf):
    ok = [row[sel]["roe_pct"] > 0, row[conf]["roe_pct"] > 0, row[conf]["twin"]["pct_below"] >= 0.975]
    return {"select_roe_positive": ok[0], "confirm_roe_positive": ok[1], "confirm_twin_975": ok[2],
            "edge": all(ok)}


def study():
    shas = {}
    for f in ("PREREG.md", "PREREG_AMEND1.md"):
        want = open(os.path.join(RES_DIR, f + ".sha256")).read().split()[0]
        got = hashlib.sha256(open(os.path.join(RES_DIR, f), "rb").read()).hexdigest()
        assert want == got, f"{f} changed after it was frozen"
        shas[f] = got
    A = pd.read_pickle(ROWS)
    B = Book(A)
    free = (A.block == "").to_numpy()
    res = {"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "prereg_sha256": shas, "simulator_check": parity_check(),
           "data": NL.data_manifest(), "costs_round_trip": COSTS, "exits": EXITS,
           "periods_utc": {k: [str(pd.Timestamp(a, unit="ms")), str(pd.Timestamp(z, unit="ms"))] for k, (a, z) in PERS.items()},
           "signal_rows": {q: int(A[q].sum()) for q in SETS},
           "blocked_share_P": rnd(1 - free[A.P.to_numpy()].mean()),
           "blocked_by_reason_P": A[A.P].block.replace("", "free").value_counts().to_dict(),
           "variants": {}, "monthly": {}}
    for vn, (sset, xn, blk) in VARIANTS.items():
        lev = EXITS[xn][0]
        use = A[sset].to_numpy() & (free if blk else True)
        res["variants"][vn] = {}
        res["monthly"][vn] = {}
        for cn in COSTS:
            own, opp = B.leg(xn, cn, "own"), B.leg(xn, cn, "opp")
            row = {pn: summary(B, use, own, opp, lev, a, z) for pn, (a, z) in PERS.items()}
            res["variants"][vn][cn] = row
            mo = monthly(B, use, own, lev)
            if vn != "P":
                mo.pop("rows")
            res["monthly"][vn][cn] = mo
            s, c, f, l19, oc = row["select"], row["confirm"], row["fiveyear"], row["last19"], row["oct2026"]
            print(f"{vn:9s} {cn} | sel n{s['n']} w{s['win']} roe{s['roe_pct']} net{s['net_pct']} tw{s['twin']['pct_below']}"
                  f" | conf n{c['n']} w{c['win']} roe{c['roe_pct']} net{c['net_pct']} tw{c['twin']['pct_below']}"
                  f" | 5y {f['per_month']}/mo be{f['breakeven_win']} | 19d n{l19['n']} w{l19.get('win')} x{l19.get('mult40')}"
                  f" | oct n{oc['n']} x{oc.get('mult40')} | months +{mo['plus']} med{mo['median']}", flush=True)
            if vn == "P" and cn == "c042":
                res["examples"] = examples(B, use, own)
    # PREREG verdicts
    P = res["variants"]["P"]
    res["verdict_P"] = verdict(P["c042"], "select", "confirm")
    res["verdict_P"]["no_discount_both_halves_positive"] = bool(P["c060"]["select"]["roe_pct"] > 0
                                                                and P["c060"]["confirm"]["roe_pct"] > 0)
    best = max(VARIANTS, key=lambda v: res["variants"][v]["c042"]["select"]["roe_pct"])
    res["select_best"] = {"variant": best, **verdict(res["variants"][best]["c042"], "select", "confirm")}
    json.dump(res, open(os.path.join(RES_DIR, "results.json"), "w"), ensure_ascii=False, indent=1, default=float)
    print("verdict P", res["verdict_P"], "| select best", res["select_best"], flush=True)
    for e in res["examples"]:
        print("example", e, flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "build":
        build(int(sys.argv[sys.argv.index("--procs") + 1]) if "--procs" in sys.argv else 3)
    else:
        study()
