"""Accounts and goal paths of the candidate bots (one position at a time over all coins, the owners' live exits w35:
35x, net-ROE -50 % stop, ladder; costs 0.124 % round trip; TetherMax payback shown separately).

Bots (their membership was fixed from SELECT numbers or from the friend's words, before their account results were read):
  A_sel_portfolio   every family cell with SELECT t > 2, mean > 0 (>= 60 trades, >= 12 months; select_cells.py), union
  B_sel_with20      the 20 with-cells of the shortlist (SELECT top by t), union
  C_friend_30m      friend's words: StochRSI (O4) 30m entry, 1h OBV state with (30분봉 진입 = 1시간봉 추세)
  C_friend_1h       StochRSI 1h entry, 4h OBV state with
  C_friend_15m      StochRSI 15m entry, 1h OBV state with
  D_trendbot18      the live trend bot's 18 members (deploy/combo.trend.json, 10-22 design): passes the bot's check
                    (with or hold, ADX, tired, far, rsi, breakout rule) on its mapping, entry blocks off (blk == 0)
  E_timing_v4of4    the 7 timing oscillators on 15m and 30m, with the 1h judge when all four judges agree
                    (principle-defined; NOTE the role table's CONFIRM medians were seen before this bot was written)
  F_role_top3       the 3 role-level units with the highest SELECT t (role_pool.py), union
For each bot and period: trades, trades/day, mean ROE per trade, win rate, coin-flip twin (same entries, opposite
side, its own one-position path), final multiple and max drawdown at margin 0.40 (the live bots' margin), and on
CONFIRM trades the 30-day day-block bootstrap (P(x6), P(-50 % first), P(-90 % first)) at margins 0.1 / 0.2 / 0.4 / 0.6,
plus the growth-optimal margin and the 30-day median multiple it gives.

    python3 goalpath.py   ->  goalpath.csv, goal_boot.csv"""
import sys
from cellsig import *
from fy_analyze import bh, pval, ENTRY_ROLES

MARGINS = (0.1, 0.2, 0.4, 0.6)


def bot_rows(specs):
    parts = []
    for i, sp in enumerate(specs):
        S = cell_rows(*sp)
        if len(S):
            S["prio"] = i
            parts.append(S)
    if not parts:
        return pd.DataFrame()
    S = pd.concat(parts, ignore_index=True)
    # the same signal reached through two cells counts once (best priority)
    S = S.sort_values(["prio"]).drop_duplicates(["coin", "e", "side", "name", "tf"]).sort_values(["e", "prio"])
    return S.reset_index(drop=True)


def acct(T, side_col="", margin=0.4):
    a = RD.account(T, "w35", margin=margin, side_col=side_col)
    return a


def read(S, per, blk0=False):
    P = period_rows(S, per)
    if blk0:
        P = P[P.blk == 0]
    if not len(P):
        return {}
    took = RD.one_position(P, "w35", priority="prio")
    T = P[took]
    tko = RD.one_position(P, "w35", side_col="_opp", priority="prio")
    To = P[tko]
    a, b = PER_SPAN[per]
    days = (b - a) / DAY
    roe = T.w35_roe.to_numpy()
    out = {"signals": len(P), "trades": len(T), "per_day": len(T) / days, "mean_roe": roe.mean() if len(T) else np.nan,
           "mean_roe_pb": (roe + 35 * PAYBACK).mean() if len(T) else np.nan, "win": (roe > 0).mean() if len(T) else np.nan,
           "mean_roe_all_signals": P.w35_roe.mean(), "opp_mean_roe": To.w35_opp_roe.mean() if len(To) else np.nan,
           "long_share": (T.side > 0).mean() if len(T) else np.nan, "a2_mean": T.a2_roe.mean(),
           "s20_mean": T.w35s20_roe.mean(), "w30_mean": T.w30_roe.mean()}
    for m in (0.4,):
        ac = acct(T, margin=m)
        out[f"final_x_m{m}"] = ac["final_x"]
        out[f"max_dd_m{m}"] = ac["max_dd"]
        out[f"opp_final_x_m{m}"] = acct(To, side_col="_opp", margin=m)["final_x"] if len(To) else np.nan
        Tp = T.assign(w35_roe=T.w35_roe + 35 * PAYBACK)
        out[f"final_x_pb_m{m}"] = acct(Tp, margin=m)["final_x"]
    return out, T


def growth_opt(roe, per_day):
    """Growth-optimal margin (share of equity per trade) for these per-trade ROEs and the 30-day median multiple."""
    best = (0.0, 0.0)
    for m in np.linspace(0.01, 1.0, 100):
        g = np.mean(np.log(np.maximum(1 + m * np.maximum(roe, -1.0), 1e-12)))
        if g > best[1]:
            best = (m, g)
    m, g = best
    return m, float(np.exp(30 * per_day * g))


def main(which=None):
    sel = pd.read_csv(os.path.join(HERE, "shortlist.csv"))
    fam = pd.read_pickle(os.path.join(SHM, "cells.pkl"))
    bots = {}
    # A: SELECT-only portfolio (t > 2, mean > 0, n >= 60, months >= 12; latch neutral excluded)
    specs = []
    for cn in ("W", "A", "N"):
        q = fam[(fam[f"SEL_n{cn}"] >= 60) & (fam[f"SEL_M{cn}"] >= 12) & (fam[f"SEL_t{cn}"] > 2) & (fam[f"SEL_m{cn}"] > 0)]
        if cn == "N":
            q = q[q.kind != "l"]
        for _, r in q.sort_values(f"SEL_t{cn}", ascending=False).iterrows():
            specs.append((r["name"], r.etf, r.htf, r.kind, r.source, cn, float(r[f"SEL_t{cn}"])))
    specs = [s[:6] for s in sorted(specs, key=lambda x: -x[6])]
    bots["A_sel_portfolio"] = specs
    bots["B_sel_with20"] = [(r["name"], r.etf, r.htf, r.source.split(":")[0], r.source.split(":")[1], "W")
                            for _, r in sel[sel.cond == "W"].iterrows()]
    bots["C_friend_30m"] = [("O4_STOCHRSI_ZONE", "30m", "1h", "c", "OBV_S", "W")]
    bots["C_friend_1h"] = [("O4_STOCHRSI_ZONE", "1h", "4h", "c", "OBV_S", "W")]
    bots["C_friend_15m"] = [("O4_STOCHRSI_ZONE", "15m", "1h", "c", "OBV_S", "W")]
    import json
    cfg = json.load(open(os.path.join(REPO, "deploy", "combo.trend.json")))
    hmap = {"30m": "1h", "1h": "4h", "4h": "1d"}
    bots["D_trendbot18"] = [(m["strategy"], m["tf"], hmap[m["tf"]], "j", "TB22", "P") for m in cfg["members"]]
    N = RD.names()
    tim = N.name[N.role == "timing"].tolist()
    bots["E_timing_v4of4"] = [(nm, tf, "1h", "j", "V4OF4", "W") for tf in ("15m", "30m") for nm in tim]
    rp = pd.read_csv(os.path.join(HERE, "role_pool_picked.csv")).sort_values("SEL_t_pb", ascending=False).head(3)
    specs = []
    for _, r in rp.iterrows():
        for nm in N.name[N.role == r.role]:
            specs.append((nm, r.etf, r.htf, r.kind, r.source, r.cond))
    bots["F_role_top3"] = specs
    # G: direction-skill portfolio, SELECT only: with-cells whose side beats the coin-flip twin on SELECT (BH over the
    #    with family on the month-clustered paired t) AND whose SELECT mean + payback > 0
    Wf = fam[(fam.SEL_nW >= 60) & (fam.SEL_MW >= 12)].copy()
    Wf["bh"] = bh(pval(Wf.SEL_tFlip.to_numpy(), Wf.SEL_MW.to_numpy()))
    g = Wf[Wf.bh & (Wf.SEL_mW + 35 * PAYBACK > 0)].sort_values("SEL_tFlip", ascending=False)
    bots["G_flip_portfolio"] = [(r["name"], r.etf, r.htf, r.kind, r.source, "W") for _, r in g.iterrows()]
    # H: the friend's mapping with the live judge (held 3-of-4), entries picked on SELECT: SELECT mean + payback > 0
    #    and SELECT t (with payback) > 2, entry roles only
    h = fam[(fam.kind == "j") & (fam.source == "DIR") & fam.role.isin(ENTRY_ROLES) & (fam.SEL_nW >= 60)
            & (fam.SEL_MW >= 12) & [(a, b) in FRIEND_PAIRS for a, b in zip(fam.etf, fam.htf)]]
    h = h[(h.SEL_mW + 35 * PAYBACK > 0) & (h.SEL_tWpb > 2)].sort_values("SEL_tWpb", ascending=False)
    bots["H_friendmap_dir_sel"] = [(r["name"], r.etf, r.htf, "j", "DIR", "W") for _, r in h.iterrows()]
    # exploratory single cell seen while reading the direction-skill list (CONFIRM seen: not a confirmation)
    bots["X_S4_BB_BBP@1h|j:DIR@4h"] = [("S4_BB_BBP", "1h", "4h", "j", "DIR", "W")]
    # exploratory single cells: with-cells of the shortlist that were positive on CONFIRM (picked using CONFIRM!)
    for _, r in sel[(sel.cond == "W") & (sel.CONF_m > 0)].iterrows():
        bots[f"X_{r['name']}@{r.etf}|{r.source}@{r.htf}"] = [(r["name"], r.etf, r.htf, r.source.split(":")[0],
                                                                r.source.split(":")[1], "W")]
    rows, boots = [], []
    for bname, specs in bots.items():
        if which and not bname.startswith(which):
            continue
        S = bot_rows(specs)
        log(bname, "cells", len(specs), "rows", len(S))
        if not len(S):
            continue
        for per in ("SEL", "CONF", "LATE", "FWD"):
            for blk0 in ((True, False) if bname == "D_trendbot18" else (False,)):
                r = read(S, per, blk0=blk0)
                if not r:
                    continue
                o, T = r
                o.update({"bot": bname, "cells": len(specs), "period": per, "blk0": blk0})
                if per in ("CONF", "FWD") and len(T) >= 10:
                    m_opt, x_opt = growth_opt(T.w35_roe.to_numpy(), o["per_day"])
                    o["growth_opt_margin"], o["median_30d_x_at_opt"] = m_opt, x_opt
                    m_opt, x_opt = growth_opt(T.w35_roe.to_numpy() + 35 * PAYBACK, o["per_day"])
                    o["growth_opt_margin_pb"], o["median_30d_x_at_opt_pb"] = m_opt, x_opt
                    for m in MARGINS:
                        for pb in (False, True):
                            Tb = T.assign(w35_roe=T.w35_roe + (35 * PAYBACK if pb else 0.0))
                            g = RD.goal_bootstrap(Tb, "w35", margin=m, days=PER_SPAN[per], n_boot=4000)
                            boots.append({"bot": bname, "period": per, "blk0": blk0, "margin": m, "payback": pb,
                                          "exposure_x": 35 * m, **g})
                rows.append(o)
        print(pd.DataFrame([x for x in rows if x["bot"] == bname])[["period", "blk0", "trades", "per_day", "mean_roe",
                                                                       "mean_roe_pb", "opp_mean_roe", "win",
                                                                       "final_x_m0.4", "opp_final_x_m0.4",
                                                                       "max_dd_m0.4"]].round(4).to_string())
    G = pd.DataFrame(rows)
    Bt = pd.DataFrame(boots)
    sfx = f"_{which}" if which else ""
    G.to_csv(os.path.join(HERE, f"goalpath{sfx}.csv"), index=False, float_format="%.5g")
    Bt.to_csv(os.path.join(HERE, f"goal_boot{sfx}.csv"), index=False, float_format="%.5g")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
