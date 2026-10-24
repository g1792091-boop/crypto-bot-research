"""PLAN.md: the 384 settings (48 families x 8 exits) on every period, the coin-flip twins, BH, the verdicts, the select picks,
the direction shares, and for the highlight settings the 2026 months and the goal path (+500 % in 30 days).

    python3 -I f2build.py                  (once: SCR/rows_<coin>.pkl)
    python3 -I f2study.py                  -> results.json, settings.csv, families_direction.csv, months2026.csv, goal.csv"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from f2common import *
from f2common import _take_nb
import hashlib

SELECT_MIN_N = 300
BEST26_MIN_N = 100
BOOT_PATHS = 20000
GOAL = 6.0
TWIN_PERIODS = ("confirm", "y2026", "last19")


def load():
    parts = [pd.read_pickle(os.path.join(SCR, f"rows_{c}.pkl")) for c in COINS]
    R = pd.concat(parts, ignore_index=True)
    R = R.iloc[np.lexsort((R.side.to_numpy(), R.coin.to_numpy(), R.t.to_numpy()))].reset_index(drop=True)
    return R


class Book:
    def __init__(self, R):
        self.t = R.t.to_numpy(np.int64)
        self.coin = R.coin.to_numpy()
        self.side = R.side.to_numpy()
        self.free = (R.block == "").to_numpy()
        self.fam = {f: R[f].to_numpy(bool) for f in FAMS}
        self.fwd = {h: R[f"fwd{h}"].to_numpy(float) for h in (60, 240, 1440)}
        self.x = {}
        for xn in XN:
            self.x[xn] = {q: R[f"{xn}_{q}"].to_numpy() for q in ("own_r", "own_k", "own_why", "own_mae", "opp_r", "opp_k")}
        self.month = np.asarray(pd.to_datetime(self.t + KST, unit="ms").strftime("%Y-%m"))


def trades(B, fam, xi, a, z):
    lev, sl = EXITS[xi]
    X = B.x[XN[xi]]
    m = B.fam[fam] & B.free & (B.t >= a) & (B.t < z)
    ext = B.t + (X["own_k"].astype(np.int64) + 1) * MIN
    idx = _take_nb(B.t, ext, m)
    roe0 = lev * X["own_r"][idx]
    return m, idx, roe0, roe0 + refund(lev)


def period_stats(B, fam, xi, pn, twin_on=True, splits=False):
    a, z = PERIODS[pn]
    lev, sl = EXITS[xi]
    X = B.x[XN[xi]]
    m, idx, roe0, roe = trades(B, fam, xi, a, z)
    st = acct_stats(B.t[idx], roe, roe0, X["own_k"][idx], X["own_why"][idx], X["own_mae"][idx].astype(float))
    st["candidates"] = int(m.sum())
    st["per_weekday"] = rnd(len(idx) / max(weekdays(a, z), 1), 2)
    st["per_day"] = rnd(len(idx) / ((z - a) / DAY), 2)
    if twin_on and len(idx) and pn in TWIN_PERIODS:
        st["twin"] = twin(B.t, m, X["own_r"], X["own_k"], X["opp_r"], X["opp_k"], lev, float(roe0.mean()))
    if splits and len(idx):
        cs, ss = B.coin[idx], B.side[idx]
        st["by_coin"] = {COINS[c][:-4]: {"n": int((cs == c).sum()), "win": rnd((roe[cs == c] > 0).mean(), 3),
                                         "roe_pct": rnd(roe[cs == c].mean() * 100, 2), "sum_roe_pct": rnd(roe[cs == c].sum() * 100, 1)}
                         for c in range(6) if (cs == c).any()}
        st["by_side"] = {nm: {"n": int((ss == sv).sum()), "win": rnd((roe[ss == sv] > 0).mean(), 3),
                              "roe_pct": rnd(roe[ss == sv].mean() * 100, 2), "sum_roe_pct": rnd(roe[ss == sv].sum() * 100, 1)}
                         for nm, sv in (("long", 1), ("short", -1)) if (ss == sv).any()}
    return st


# ====================================================================== goal path
@numba.njit(cache=True)
def boot(roe, n_trades, n_paths, margin, goal, seed):
    np.random.seed(seed)
    reach = 0
    f50 = 0
    f10 = 0
    for p in range(n_paths):
        eq = 1.0
        h50 = False
        h10 = False
        for i in range(n_trades):
            r = roe[np.random.randint(0, len(roe))]
            x = margin * r
            if x < -1.0:
                x = -1.0
            eq *= 1.0 + x
            if eq >= goal:
                reach += 1
                break
            if eq <= 0.5 and not h50:
                h50 = True
                f50 += 1
            if eq <= 0.1 and not h10:
                h10 = True
                f10 += 1
                break
    return reach / n_paths, f50 / n_paths, f10 / n_paths


@numba.njit(cache=True)
def windows(t, roe, starts, span, margin, goal):
    """Every trade start in starts: the 30-day path from 1 at the margin: reached the goal, hit 0.5 / 0.1 before it."""
    n = len(t)
    reach = 0
    f50 = 0
    f10 = 0
    for s in starts:
        eq = 1.0
        h50 = False
        h10 = False
        i = s
        while i < n and t[i] < t[s] + span:
            x = margin * roe[i]
            if x < -1.0:
                x = -1.0
            eq *= 1.0 + x
            if eq >= goal:
                reach += 1
                break
            if eq <= 0.5 and not h50:
                h50 = True
                f50 += 1
            if eq <= 0.1 and not h10:
                h10 = True
                f10 += 1
                break
            i += 1
    k = len(starts)
    return reach / k, f50 / k, f10 / k


def goal_path(B, fam, xi):
    lev, sl = EXITS[xi]
    out = {"lev": lev}
    for pn in ("confirm", "y2026", "last19"):
        a, z = PERIODS[pn]
        _, idx, roe0, roe = trades(B, fam, xi, a, z)
        if len(idx) < 5:
            out[pn] = None
            continue
        n30 = int(round(len(idx) / ((z - a) / DAY) * 30))
        ms_ = np.round(np.arange(0.01, 1.0001, 0.01), 2)
        G = np.array([n30 * np.mean(np.log(np.maximum(1 + m * roe, 1e-12))) for m in ms_])
        best = int(np.argmax(G))
        need = np.flatnonzero(G >= np.log(GOAL))
        d = {"trades_per_30d": n30, "best_margin": float(ms_[best]), "best_median_mult_30d": rnd(np.exp(G[best]), 4),
             "min_margin_for_x6": float(ms_[need[0]]) if len(need) else None,
             "exposure_for_x6": rnd(lev * ms_[need[0]], 2) if len(need) else None,
             "median_mult_30d_m40": rnd(np.exp(G[39]), 4), "median_mult_30d_m10": rnd(np.exp(G[9]), 4)}
        for mg in MARGINS:
            p = boot(roe.astype(np.float64), max(n30, 1), BOOT_PATHS, mg, GOAL, SEED)
            d[f"boot_m{int(mg * 100)}"] = {"p_x6": rnd(p[0], 4), "p_half_first": rnd(p[1], 4), "p_tenth_first": rnd(p[2], 4)}
        out[pn] = d
    # (c) actual 30-day windows starting at every confirm trade (one pass from 2021-01 to the data end)
    _, idx, roe0, roe = trades(B, fam, xi, PERIODS["select"][0], END2)
    tt = B.t[idx]
    a, z = PERIODS["confirm"]
    starts = np.flatnonzero((tt >= a) & (tt < z) & (tt + 30 * DAY <= END2)).astype(np.int64)
    if len(starts):
        for mg in MARGINS:
            w = windows(tt, roe.astype(np.float64), starts, 30 * DAY, mg, GOAL)
            out[f"windows_confirm_m{int(mg * 100)}"] = {"windows": int(len(starts)), "share_x6": rnd(w[0], 4),
                                                        "share_half_first": rnd(w[1], 4), "share_tenth_first": rnd(w[2], 4)}
    return out


def months2026(B, fam, xi):
    a, z = PERIODS["y2026"][0], PERIODS["oct"][1]
    _, idx, roe0, roe = trades(B, fam, xi, a, z)
    mon = B.month[idx]
    rows = []
    for q in pd.period_range("2026-01", "2026-10", freq="M").strftime("%Y-%m"):
        r = roe[mon == q]
        row = {"month": q, "n": int(len(r)), "win": rnd((r > 0).mean(), 3) if len(r) else None,
               "roe_pct": rnd(r.mean() * 100, 2) if len(r) else None}
        for mg in MARGINS:
            row[f"mult{int(mg * 100)}"] = rnd(np.prod(1 + np.maximum(mg * r, -1.0)), 3)
        rows.append(row)
    return rows


def direction(B):
    out = []
    for f, spec in FAMS.items():
        for pn in ("select", "confirm", "y2026", "oct", "last19", "ext"):
            a, z = PERIODS[pn]
            m = B.fam[f] & B.free & (B.t >= a) & (B.t < z)
            row = {"family": f, **spec, "period": pn, "signals": int(m.sum())}
            for h in (60, 240, 1440):
                v = B.fwd[h][m]
                v = v[np.isfinite(v)]
                row[f"way_{h}m"] = rnd((v > 0).mean(), 4) if len(v) else None
                row[f"mean_{h}m_pct"] = rnd(v.mean() * 100, 4) if len(v) else None
            out.append(row)
    return out


def flat(s, fam, xi):
    lev, sl = EXITS[xi]
    row = {"setting": f"{fam}|{XN[xi]}", "family": fam, **FAMS[fam], "lev": int(lev), "stop_pct": int(round(sl * 100))}
    for pn, st in s.items():
        for k in ("n", "per_weekday", "win", "breakeven_win", "avg_win_pct", "avg_loss_pct", "roe_pct", "roe_pct_no_payback",
                  "mult40", "maxdd40", "mult10", "maxdd10", "win_mae_below_m12", "win_mae_median_pct", "hold_min_median"):
            row[f"{pn}_{k}"] = st.get(k)
        if "twin" in st and st["twin"]:
            row[f"{pn}_twin_pct"] = st["twin"]["pct_below"]
            if pn == "confirm":
                row["confirm_twin_p_norm"] = st["twin"]["p_norm"]
                row["confirm_twin_p_emp"] = st["twin"]["p_emp"]
    return row


def main():
    want = open(os.path.join(F2_DIR, "PLAN.md.sha256")).read().split()[0]
    sha = hashlib.sha256(open(os.path.join(F2_DIR, "PLAN.md"), "rb").read()).hexdigest()
    assert sha == want, "PLAN.md changed after it was frozen"
    binfo = json.load(open(os.path.join(SCR, "build_info.json")))
    assert binfo["plan_sha256"] == sha
    t0 = time.time()
    R = load()
    B = Book(R)
    del R
    print("rows", len(B.t), f"{time.time() - t0:.0f}s", flush=True)
    full, rows = {}, []
    for fi, fam in enumerate(FAMS):
        for xi in range(len(EXITS)):
            s = {pn: period_stats(B, fam, xi, pn) for pn in PERIODS}
            full[(fam, xi)] = s
            rows.append(flat(s, fam, xi))
        c = rows[-1]
        print(f"[{fi + 1}/48] {fam} {time.time() - t0:.0f}s | last exit {XN[-1]}: sel {c['select_roe_pct']} conf {c['confirm_roe_pct']} "
              f"tw {c.get('confirm_twin_pct')}", flush=True)
    S = pd.DataFrame(rows)
    p = S["confirm_twin_p_norm"].fillna(1.0).to_numpy()
    S["confirm_twin_p_bh"] = bh_adjust(p)
    S["c1_select_pos"] = S.select_roe_pct > 0
    S["c2_confirm_pos"] = S.confirm_roe_pct > 0
    S["c3_twin975"] = S.confirm_twin_pct >= 0.975
    S["c4_bh"] = S.confirm_twin_p_bh <= BH_Q
    S["works"] = S.c1_select_pos & S.c2_confirm_pos & S.c3_twin975 & S.c4_bh
    S.to_csv(os.path.join(F2_DIR, "settings.csv"), index=False)
    key = {r["setting"]: (r["family"], XN.index(r["setting"].split("|")[1])) for r in rows}
    # picks
    picks = {}
    for dz in ("F", "G", "V", "O"):
        D = S[(S.design == dz)]
        sel = D[D.select_n >= SELECT_MIN_N]
        if len(sel):
            picks[f"select_pick_{dz}"] = sel.loc[sel.select_roe_pct.idxmax(), "setting"]
        b26 = D[D.y2026_n >= BEST26_MIN_N]
        if len(b26):
            picks[f"best2026_{dz}_hindsight"] = b26.loc[b26.y2026_roe_pct.idxmax(), "setting"]
        b19 = D[D.last19_n >= 20]
        if len(b19):
            picks[f"best19d_{dz}_hindsight"] = b19.loc[b19.last19_mult40.idxmax(), "setting"]
    for s_ in S[S.works].setting:
        picks[f"confirmed:{s_}"] = s_
    hi = {}
    mon_rows, goal_rows = [], []
    for label, s_ in picks.items():
        fam, xi = key[s_]
        d = {"label": label, "setting": s_, **FAMS[fam], "lev": EXITS[xi][0], "stop": EXITS[xi][1],
             "periods": {pn: period_stats(B, fam, xi, pn, twin_on=True, splits=True) for pn in PERIODS},
             "verdict": S.loc[S.setting == s_, ["c1_select_pos", "c2_confirm_pos", "c3_twin975", "c4_bh", "works", "confirm_twin_p_bh"]].iloc[0].to_dict(),
             "months2026": months2026(B, fam, xi), "goal": goal_path(B, fam, xi)}
        hi[label] = d
        for r in d["months2026"]:
            mon_rows.append({"label": label, "setting": s_, **r})
        for pn in ("confirm", "y2026", "last19"):
            g = d["goal"].get(pn)
            if g:
                goal_rows.append({"label": label, "setting": s_, "period": pn, **{k: v for k, v in g.items() if not k.startswith("boot")},
                                  **{f"{b}_{k}": v for b in ("boot_m40", "boot_m10") for k, v in g[b].items()}})
        print("HI", label, s_, {pn: (d["periods"][pn].get("n"), d["periods"][pn].get("roe_pct"), d["periods"][pn].get("mult40"))
                                for pn in PERIODS}, flush=True)
    pd.DataFrame(mon_rows).to_csv(os.path.join(F2_DIR, "months2026.csv"), index=False)
    pd.DataFrame(goal_rows).to_csv(os.path.join(F2_DIR, "goal.csv"), index=False)
    dirs = direction(B)
    pd.DataFrame(dirs).to_csv(os.path.join(F2_DIR, "families_direction.csv"), index=False)
    # summaries
    summ = {"settings": int(len(S)), "c1": int(S.c1_select_pos.sum()), "c1_c2": int((S.c1_select_pos & S.c2_confirm_pos).sum()),
            "c1_c2_c3": int((S.c1_select_pos & S.c2_confirm_pos & S.c3_twin975).sum()), "works": int(S.works.sum()),
            "confirm_positive": int(S.c2_confirm_pos.sum()), "twin975": int(S.c3_twin975.sum()), "bh": int(S.c4_bh.sum()),
            "by_design": {dz: {"settings": int((S.design == dz).sum()), "select_pos": int(((S.design == dz) & S.c1_select_pos).sum()),
                               "confirm_pos": int(((S.design == dz) & S.c2_confirm_pos).sum()),
                               "both_pos": int(((S.design == dz) & S.c1_select_pos & S.c2_confirm_pos).sum()),
                               "y2026_pos": int(((S.design == dz) & (S.y2026_roe_pct > 0)).sum()),
                               "last19_grow40": int(((S.design == dz) & (S.last19_mult40 > 1)).sum()),
                               "ext_grow40": int(((S.design == dz) & (S.ext_mult40 > 1)).sum()),
                               "works": int(((S.design == dz) & S.works).sum())} for dz in ("F", "G", "V", "O")}}
    res = {"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "plan_sha256": sha, "build": binfo,
           "checks": json.load(open(os.path.join(F2_DIR, "checks.json"))),
           "periods_utc": {k: [str(pd.Timestamp(a, unit="ms")), str(pd.Timestamp(z, unit="ms"))] for k, (a, z) in PERIODS.items()},
           "exits": XN, "cost_round_trip": COST, "payback_roe": {int(l): refund(l) for l in LEVS}, "summary": summ,
           "picks": picks, "highlights": hi}
    json.dump(res, open(os.path.join(F2_DIR, "results.json"), "w"), ensure_ascii=False, indent=1, default=float)
    print(json.dumps(summ, indent=1), flush=True)
    print(f"done {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
