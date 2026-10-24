"""Cost / executability verifier for B_sel_with20 (the claim: CONF -2.77 % raw, -0.13 % with the TetherMax payback,
2,487 trades, 2.48 / day, 30-day P(x6) 1.7 % at margin 0.4 with payback, +9.25 / +6.75 ROE points needed).

Re-walks EVERY candidate signal of B (not only the taken trades) with frdeep.walk3 on the 1m grid, so that exits, the
one-position path and the coin-flip twin all change consistently, under:
  base        cost 0.124 % round trip (taker 0.042 % + slippage 0.02 %, each side) -- must equal the grid lookups
  nofund      base without funding (how much funding matters)
  cost2x      0.248 % round trip (taker + slippage doubled; payback stays 90 % of the real 0.042 % taker)
  slip3x      taker 0.042 % + slippage 0.06 % each side (0.204 % round trip)
  late1       entry at the open of the NEXT minute (one minute of executor latency), base cost
  late1_2x    both
  stopslip    base, every stop exit filled 0.05 % (price) worse than the stop level (post-processed)
Then one position over all coins (study rule, same priority), CONF trades, mean ROE (35x), with payback, win rate,
coin-flip twin (own one-position path), 30-day day-block bootstrap at margin 0.4 (and 0.2), and the ROE shift needed
for a x6 growth-optimal median.

    python3 ce_costs.py   -> ce_costs.csv, ce_costs.txt"""
import os
import sys

FY = "/home/user/crypto-bot-research/analysis/review1024/roles/fiveyear"
sys.path.insert(0, FY)
import fy_common                         # noqa: E402
fy_common.SHM = "/dev/shm/claude_verify_ce"
os.makedirs(fy_common.SHM, exist_ok=True)
import goalpath as GP                    # noqa: E402
from goal_gap import need                # noqa: E402
from cellsig import *                    # noqa: E402,F401
from frdeep import walk3                 # noqa: E402

OUTD = os.path.dirname(os.path.abspath(__file__))
PBR = 35.0 * PAYBACK
LINES = []


def say(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LINES.append(s)


def specs_B():
    sel = pd.read_csv(os.path.join(FY, "shortlist.csv"))
    return [(r["name"], r.etf, r.htf, r.source.split(":")[0], r.source.split(":")[1], "W")
            for _, r in sel[sel.cond == "W"].iterrows()]


SCEN = {  # name: (round-trip cost, entry delay minutes, use funding)
    "base": (COST, 0, True),
    "nofund": (COST, 0, False),
    "cost2x": (2 * COST, 0, True),
    "slip3x": (2 * (0.00042 + 0.0006), 0, True),
    "late1": (COST, 1, True),
    "late1_2x": (2 * COST, 1, True),
}


def rewalk(S):
    """Columns r_<scen>, k_<scen>, why_<scen> and the _opp twin, per row of S."""
    n = len(S)
    res = {}
    for sc in SCEN:
        for sfx in ("", "_opp"):
            res[f"r_{sc}{sfx}"] = np.full(n, np.nan)
            res[f"k_{sc}{sfx}"] = np.full(n, -1, np.int64)
            res[f"why_{sc}{sfx}"] = np.full(n, -1, np.int8)
    dummy = np.zeros(1, bool)
    for ci, coin in enumerate(COINS):
        m = np.flatnonzero(S.coin.to_numpy() == ci)
        if not len(m):
            continue
        g = grid(coin)
        o, h, l, c, nn = g["o"], g["h"], g["l"], g["c"], g["n"]
        cumf = np.cumsum(g["fund"])
        zf = np.zeros_like(cumf)
        e = S.e.to_numpy(np.int64)[m]
        side = S.side.to_numpy()[m]
        for sc, (cost, dly, fund) in SCEN.items():
            cf = cumf if fund else zf
            for sfx, sg in (("", 1), ("_opp", -1)):
                for sd in (1, -1):
                    q = np.flatnonzero(side * sg == sd)
                    if not len(q):
                        continue
                    es = np.ascontiguousarray(e[q] + dly, dtype=np.int64)
                    a = walk3(o, h, l, c, cf, es, sd, 35.0, cost, FL, STEP, GAP, -0.50, 9.0, 0.01, 0, dummy, False,
                              c, o, 0.0, nn)
                    res[f"r_{sc}{sfx}"][m[q]] = a[0]
                    res[f"k_{sc}{sfx}"][m[q]] = a[1] + dly       # exit minute measured from the signal minute e
                    res[f"why_{sc}{sfx}"][m[q]] = a[2]
        drop(coin)
        log("rewalked", coin, len(m))
    for k, v in res.items():
        S[k] = v
    return S


def read(S, sc, extra_stop=0.0, label=None):
    P = period_rows(S, "CONF").copy()
    P["w35_k"] = P[f"k_{sc}"]
    P["w35_opp_k"] = P[f"k_{sc}_opp"]
    r = P[f"r_{sc}"].to_numpy().copy()
    ro = P[f"r_{sc}_opp"].to_numpy().copy()
    if extra_stop:
        r[P[f"why_{sc}"].to_numpy() == 0] -= extra_stop
        ro[P[f"why_{sc}_opp"].to_numpy() == 0] -= extra_stop
    P["w35_roe"] = np.maximum(35.0 * r, -1.0)
    P["w35_opp_roe"] = np.maximum(35.0 * ro, -1.0)
    P["w35_why"] = P[f"why_{sc}"]
    took = RD.one_position(P, "w35", priority="prio")
    T = P[took]
    tko = RD.one_position(P, "w35", side_col="_opp", priority="prio")
    To = P[tko]
    a, b = PER_SPAN["CONF"]
    days = (b - a) / DAY
    roe = T.w35_roe.to_numpy()
    o = {"scenario": label or sc, "trades": len(T), "per_day": len(T) / days, "mean_roe": roe.mean(),
         "mean_roe_pb": roe.mean() + PBR, "win": (roe > 0).mean(), "stop_share": (T.w35_why == 0).mean(),
         "twin_mean_roe": To.w35_opp_roe.mean(), "twin_mean_roe_pb": To.w35_opp_roe.mean() + PBR,
         "open_at_end": int((T.w35_why == 3).sum())}
    for m_ in (0.2, 0.4):
        for pb in (False, True):
            Tb = T.assign(w35_roe=T.w35_roe + (PBR if pb else 0.0))
            gb = RD.goal_bootstrap(Tb, "w35", margin=m_, days=PER_SPAN["CONF"], n_boot=4000)
            tag = f"m{m_}{'_pb' if pb else ''}"
            o[f"px6_{tag}"] = gb["p_target"]
            o[f"pl50_{tag}"] = gb["p_lose50_first"]
            o[f"pl90_{tag}"] = gb["p_lose90_first"]
            o[f"med_{tag}"] = gb["median_final_x"]
    d0, m0 = need(roe, o["per_day"])
    d1, m1 = need(roe + PBR, o["per_day"])
    o.update({"need_shift": d0 * 100, "need_margin": m0, "need_shift_pb": d1 * 100, "need_margin_pb": m1})
    return o, T


def main():
    S = GP.bot_rows(specs_B())
    S = period_rows(S, "CONF").reset_index(drop=True)
    say("B candidate CONF signals", len(S))
    S = rewalk(S)
    # sanity: the base re-walk equals the grid lookups the study used
    d = np.nanmax(np.abs(S.r_base.to_numpy() * 35 - S.w35_roe.to_numpy()))
    dk = int((S.k_base.to_numpy() != S.w35_k.to_numpy()).sum())
    do = np.nanmax(np.abs(S.r_base_opp.to_numpy() * 35 - S.w35_opp_roe.to_numpy()))
    say(f"base re-walk vs grid: max |ROE diff| {d:.2e}, opp {do:.2e}, exit-minute mismatches {dk}")
    rows = []
    for sc in SCEN:
        o, T = read(S, sc)
        rows.append(o)
    o, T = read(S, "base", extra_stop=0.0005, label="stopslip_0.05pct")
    rows.append(o)
    o, T = read(S, "cost2x", extra_stop=0.0005, label="cost2x+stopslip")
    rows.append(o)
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(OUTD, "ce_costs.csv"), index=False, float_format="%.5g")
    pd.set_option("display.width", 250)
    say(R[["scenario", "trades", "per_day", "mean_roe", "mean_roe_pb", "win", "stop_share", "twin_mean_roe",
           "px6_m0.4_pb", "pl50_m0.4_pb", "pl90_m0.4_pb", "med_m0.4_pb", "px6_m0.4", "need_shift", "need_margin",
           "need_shift_pb", "need_margin_pb"]].round(4).to_string())
    # concurrency: how many CONF signals arrived while the bot was busy (overlap that one position throws away)
    P = period_rows(S, "CONF").copy()
    P["w35_k"] = P.k_base
    took = RD.one_position(P, "w35", priority="prio")
    say(f"CONF candidate signals {len(P)}, taken {int(took.sum())} ({took.mean():.1%}); "
        f"mean ROE all candidates {np.nanmean(np.maximum(P.r_base * 35, -1)):.4f}")
    # hold time and stop distance in price terms (what an executor must place)
    T = P[took]
    say(f"taken trades: median hold {np.median(T.k_base):.0f} min, mean {T.k_base.mean():.0f} min; "
        f"stop at gross {(-0.5 / 35 + COST) * 100:.3f} % price from entry (net -50 % ROE at 35x incl. 0.124 % cost)")
    open(os.path.join(OUTD, "ce_costs.txt"), "w").write("\n".join(LINES) + "\n")


if __name__ == "__main__":
    main()
