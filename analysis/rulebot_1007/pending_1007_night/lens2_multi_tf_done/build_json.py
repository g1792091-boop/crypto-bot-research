"""Assemble lens2_multi_tf.json from the summary CSVs (every number below is read from them, nothing typed in).

    python3 -I -B build_json.py <summ_dir> <feas_csv> <out_json>
"""
import json
import os
import sys

sys.path[:0] = ['/root/.local/lib/python3.11/site-packages']
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

summ, feas_csv, out_json = sys.argv[1:4]
HERE = os.path.dirname(os.path.abspath(__file__))
P = pd.read_csv(os.path.join(summ, "pooled.csv"))
PS = pd.read_csv(os.path.join(summ, "per_strategy.csv"))
PR = pd.read_csv(os.path.join(summ, "paired.csv"))
BL = pd.read_csv(os.path.join(summ, "blocking_long.csv"))
BM = pd.read_csv(os.path.join(summ, "blocked_matrix.csv"))
DQ = pd.read_csv(os.path.join(summ, "dd_quarter_summary.csv"))
RC = pd.read_csv(os.path.join(summ, "recent_cost.csv"))
LV = pd.read_csv(os.path.join(summ, "live_check_summary.csv"))
FE = pd.read_csv(feas_csv)
LR = pd.read_csv(os.path.join(summ, "live_rejected.csv")).dropna()
LRS = {r.kind: float(r.rejected_share) for r in LR[LR.timeframe == "4h"].itertuples()}
CALL_USD = 0.03          # docs/aibot/AIBOT_DESIGN_KO_v2.md line 1035: Sonnet call ~ $0.03 (cached ~ $0.015)
BUDGET = 500.0
DAYS60 = 60
GROUP_DQ = {"core36": "core", "ds44": "ds"}


def pr(g, cb):
    r = P[(P.group == g) & (P.combo == cb)]
    return r.iloc[0] if len(r) else None


def f3(x):
    return f"{x:+.3f}" if isinstance(x, (float, np.floating)) and np.isfinite(x) else "n/a"


def pct(x, d=0):
    return f"{100 * x:.{d}f}%"


def dq(g, cb, col):
    r = DQ[(DQ.grp == GROUP_DQ[g]) & (DQ.combo == cb)]
    return float(r[col].iloc[0]) if len(r) else np.nan


def paired(g, a, b):
    r = PR[(PR.group == g) & (PR.a == a) & (PR.b == b)]
    return r.iloc[0] if len(r) else None


def d_combined(g):
    """Setup D: the 15m/30m trader (A|FC) plus the 1h/4h trader (HI|FC), trades pooled."""
    sel = PS.family.eq("core") if g == "core36" else PS.family.ne("core")
    s = PS[sel & PS.combo.isin(["A|FC", "HI|FC"]) & (PS.period == "all")]
    return float(s.sumR.sum() / s.trades.sum()), float(s.groupby("combo").trades_per_day.mean().sum())


# ------------------------------------------------------------------ setup table
SETUPS = [("A: AI 15m+30m, first-come", "A|FC"), ("A: AI 15m+30m, switch to higher tf", "A|SWH"),
          ("A: AI 15m+30m, switch to any new", "A|SW"),
          ("B: one trader 4 tfs, first-come", "ALL|FC"), ("B: one trader 4 tfs, longer-tf-first on ties", "ALL|LTF"),
          ("B: 4 tfs incl. 4h not sizable at 20x (sensitivity)", "ALLINF|FC"),
          ("C: 4 tfs (4h only if 20x sizes), switch only to higher tf", "ALL|SWH"),
          ("C: 4 tfs, switch to any new signal", "ALL|SW"),
          ("D: second trader 1h+4h, first-come", "HI|FC"),
          ("rule account 15m alone", "T15|FC"), ("rule account 30m alone", "T30|FC"),
          ("rule account 1h alone", "T1h|FC"), ("rule account 4h alone", "T4h|FC")]


def setup_rows(g):
    rows = []
    for lab, cb in SETUPS:
        r = pr(g, cb)
        if r is None:
            continue
        sd = dq(g, cb, "sdR")
        n60 = r.trades_per_day_per_trader * DAYS60
        calls_lo = r.calls_entry_free_per_day + r.calls_hold_30m_per_day
        calls_hi = r.calls_entry_all_per_day + r.calls_hold_30m_per_day
        rows.append(dict(setup=lab, combo=cb, meanR=r.meanR, ci=(r.ci_lo, r.ci_hi), IS=r.meanR_IS, CF=r.meanR_CF,
                         gross=r.mean_gross, cost=r.mean_cost, tpd=r.trades_per_day_per_trader,
                         spd=r.signals_per_day_per_trader, blk=r.blocked_share, tie=r.tie_share, blkR=r.blocked_meanR,
                         takenR=r.taken_alone_meanR, sw=r.switches_per_day, hold=r.hold_h_mean, holdmed=r.median_hold_h_median,
                         dd2q=dq(g, cb, "dd_raw_median"), dd1q0=dq(g, cb, "dd1_demeaned_median"),
                         dd1q0_p90=dq(g, cb, "dd1_demeaned_p90"), dd1q0_gt25=dq(g, cb, "dd1_demeaned_gt25"),
                         winpos=dq(g, cb, "share_windows_pos"), sd=sd, mde60=2.8 * sd / np.sqrt(max(n60, 1)),
                         calls_lo=calls_lo, calls_hi=calls_hi, calls_bar=r.calls_entry_free_per_day + r.calls_hold_tfbar_per_day,
                         usd_month_lo=calls_lo * 30.4 * CALL_USD, usd_month_hi=calls_hi * 30.4 * CALL_USD,
                         pos=int(r.strategies_meanR_pos), pos2=int(r.strategies_pos_IS_and_CF), k=int(r.strategies)))
    return rows


SR = {g: setup_rows(g) for g in ("core36", "ds44")}
SRD = {g: {r["combo"]: r for r in SR[g]} for g in SR}


def md_table(g):
    h = ("| setup | combo | net R/trade [95% CI] | IS / CF | gross R | cost R | trades/day | signals/day | blocked | "
         "blocked signals' R | hold h (mean) | 91d DD @1% risk, zero-edge (median / p90 / >25%) | MDE 60d | AI calls/day (free-entry..all-signal + 30m holds) | $/month/trader |\n"
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    for r in SR[g]:
        h += (f"| {r['setup']} | {r['combo']} | {r['meanR']:+.3f} [{r['ci'][0]:+.3f}, {r['ci'][1]:+.3f}] | {r['IS']:+.3f} / {r['CF']:+.3f} | "
              f"{r['gross']:+.3f} | {r['cost']:.3f} | {r['tpd']:.2f} | {r['spd']:.1f} | {pct(r['blk'])} (+{pct(r['tie'])} ties) | "
              f"{r['blkR']:+.3f} | {r['hold']:.1f} | {pct(r['dd1q0'])} / {pct(r['dd1q0_p90'])} / {pct(r['dd1q0_gt25'])} | "
              f"{r['mde60']:.2f}R | {r['calls_lo']:.0f}..{r['calls_hi']:.0f} | ${r['usd_month_lo']:.0f}..${r['usd_month_hi']:.0f} |\n")
    return h


# ------------------------------------------------------------------ long-hold blocking
def blocking(g):
    b = BL[BL.family.eq("core")] if g == "core36" else BL[BL.family.ne("core")]
    out = {}
    for cb in ("ALL|FC", "ALL|SWH", "ALLINF|FC"):
        x = b[b.combo == cb].sum(numeric_only=True)
        out[cb] = dict(hi_trades=int(x.hi_trades), ge5=x.hi_trades_blk_ge5 / x.hi_trades, ge10=x.hi_trades_blk_ge10 / x.hi_trades,
                       ge20=x.hi_trades_blk_ge20 / x.hi_trades, by_hi=x.low_blocked_by_hi / x.low_blocked_total,
                       hi_time=x.hi_held_hours / x.all_held_hours, per_hi=x.low_blocked_by_hi / x.hi_trades)
    m = BM[BM.family.eq("core")] if g == "core36" else BM[BM.family.ne("core")]
    mm = m[m.combo == "ALL|FC"].groupby(["held_tf", "blocked_tf"])[["n", "sumR"]].sum()
    out["blk15_by_4h_R"] = float(mm.loc[(3, 0)].sumR / mm.loc[(3, 0)].n)
    out["blk15_by_15_R"] = float(mm.loc[(0, 0)].sumR / mm.loc[(0, 0)].n)
    return out


BK = {g: blocking(g) for g in ("core36", "ds44")}

# ------------------------------------------------------------------ leverage feasibility
fe_tf = FE.groupby(["tf", "period"])[[c for c in FE.columns if c.endswith("_pass")] + ["stop_pct_median"]].mean()
fe_c4 = FE[FE.tf == "4h"].set_index(["coin", "period"])["house_20x_pass"]
fe_c1 = FE[FE.tf == "1h"].set_index(["coin", "period"])[["house_20x_pass", "house_30x_pass"]]
fe_c15 = FE[FE.tf == "15m"].set_index(["coin", "period"])[["house_50x_pass", "risk2_50x_pass", "risk5_50x_pass", "stop_pct_median"]]


def fe(tf, per, col):
    return float(fe_tf.loc[(tf, per), col])


def lev_md():
    h = ("| tf | period | median 2 ATR stop % | house 20x | 30x | 40x | 50x | risk-per-stop 2%: 20x | 30x | 40x | 50x | 5%: 20x | 50x |\n"
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    for tf in ("15m", "30m", "1h", "4h"):
        for per in ("5y", "last30d"):
            h += (f"| {tf} | {per} | {fe(tf, per, 'stop_pct_median'):.2f} | " +
                  " | ".join(pct(fe(tf, per, f"house_{L}x_pass")) for L in (20, 30, 40, 50)) + " | " +
                  " | ".join(pct(fe(tf, per, f"risk2_{L}x_pass")) for L in (20, 30, 40, 50)) + " | " +
                  f"{pct(fe(tf, per, 'risk5_20x_pass'))} | {pct(fe(tf, per, 'risk5_50x_pass'))} |\n")
    h += "\n4h at 20x (house), per coin, 5y / last 30 days: " + "; ".join(
        f"{c[:-3]} {pct(fe_c4.loc[(c, '5y')])} / {pct(fe_c4.loc[(c, 'last30d')])}"
        for c in ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")) + ".\n"
    return h


# ------------------------------------------------------------------ recent cost + live
def rc(g, cb):
    r = RC[(RC.grp == GROUP_DQ[g]) & (RC.combo == cb)].iloc[0]
    return r


def lv(kind, sc):
    r = LV[(LV.kind == kind) & (LV.scope == sc)].iloc[0]
    return r


# ------------------------------------------------------------------ strategy notes
def strat_notes():
    notes = []
    a = PS[PS.period == "all"].set_index(["strategy", "combo"])
    per = PS.set_index(["strategy", "combo", "period"])
    blk = BL[BL.combo == "ALL|FC"].set_index("strategy")

    def v(s, cb, col, p=None):
        try:
            return float(per.loc[(s, cb, p), col]) if p else float(a.loc[(s, cb), col])
        except KeyError:
            return np.nan

    def grade(gIS, gCF, tpd):
        if not np.isfinite(tpd) or tpd < 1.0:
            return "D (under 1 AI-scope trade/day: too few decisions)"
        if gIS > 0 and gCF > 0:
            return "A (gross R > 0 in both halves, but far below the cost per trade)"
        if gIS > 0 or gCF > 0:
            return "B (gross R > 0 in one half only)"
        return "C (gross R <= 0 in both halves; AI must add direction skill and also beat cost)"

    names = sorted(PS.strategy.unique())
    for s in [n for n in names if n.startswith("C:")]:
        tpd = v(s, "A|FC", "trades_per_day")
        gIS, gCF = v(s, "A|FC", "mean_gross", "IS"), v(s, "A|FC", "mean_gross", "CF")
        cand = {cb: v(s, cb, "meanR") for cb in ("A|FC", "ALL|FC", "ALL|SWH")}
        cand = {k: x for k, x in cand.items() if np.isfinite(x) and v(s, k, "trades_per_day") >= 1.0}
        best = max(cand, key=cand.get) if cand else None
        sig4 = v(s, "T4h|FC", "signals")
        inf4 = v(s, "T4h|FC", "infeasible_in_scope")
        f4 = sig4 / (sig4 + inf4) if np.isfinite(sig4) and np.isfinite(inf4) and (sig4 + inf4) > 0 else np.nan
        numbers = {
            "A_FC": {"meanR": v(s, "A|FC", "meanR"), "IS": v(s, "A|FC", "meanR", "IS"), "CF": v(s, "A|FC", "meanR", "CF"),
                     "gross": v(s, "A|FC", "mean_gross"), "gross_IS": gIS, "gross_CF": gCF, "cost": v(s, "A|FC", "mean_cost"), "trades_per_day": tpd,
                     "blocked_share": v(s, "A|FC", "blocked_share"), "blocked_meanR": v(s, "A|FC", "blocked_meanR")},
            "ALL_FC_meanR": v(s, "ALL|FC", "meanR"), "ALL_SWH_meanR": v(s, "ALL|SWH", "meanR"),
            "ALL_SWH_IS_CF": [v(s, "ALL|SWH", "meanR", "IS"), v(s, "ALL|SWH", "meanR", "CF")],
            "ALL_SWH_trades_per_day": v(s, "ALL|SWH", "trades_per_day"), "ALL_SWH_cost": v(s, "ALL|SWH", "mean_cost"),
            "HI_FC": {"meanR": v(s, "HI|FC", "meanR"), "trades_per_day": v(s, "HI|FC", "trades_per_day"),
                      "gross": v(s, "HI|FC", "mean_gross")},
            "T4h": {"meanR": v(s, "T4h|FC", "meanR"), "trades": v(s, "T4h|FC", "trades"), "sizable_share_20x": f4},
            "lowtf_blocked_by_1h4h_share_ALL_FC": float(blk.loc[s, "low_blocked_by_hi"] / blk.loc[s, "low_blocked_total"])
            if s in blk.index and blk.loc[s, "low_blocked_total"] > 0 else np.nan,
        }
        numbers = json.loads(json.dumps(numbers, default=float).replace("NaN", "null"))
        if not np.isfinite(tpd):
            note = "No 5-year signals in the 15m/30m scope (N21 fires almost never); not testable here."
        else:
            note = (f"A (15m+30m first-come): {tpd:.2f} trades/day, net {v(s, 'A|FC', 'meanR'):+.3f}R (gross {v(s, 'A|FC', 'mean_gross'):+.3f}, "
                    f"cost {v(s, 'A|FC', 'mean_cost'):.3f}); C-proxy ALL|SWH {v(s, 'ALL|SWH', 'meanR'):+.3f}R; 1h+4h trader {v(s, 'HI|FC', 'meanR'):+.3f}R "
                    f"at {v(s, 'HI|FC', 'trades_per_day'):.2f}/day. Lowest-hurdle setup with >= 1 trade/day: {best}.")
        notes.append(dict(strategy=s[2:], timeframe="15m+30m (A) vs 15m-4h (B/C) vs 1h+4h (D)",
                          grade=grade(gIS, gCF, tpd) if np.isfinite(tpd) else "n/a (no signals)", numbers=numbers, note=note))
    for s in ("C:N21_ST_RSI_ADX",):
        if s not in names:
            notes.append(dict(strategy=s[2:], timeframe="15m/30m/1h/4h", grade="n/a (no signals)", numbers={"trades_A_FC": 0},
                              note="No 15m-4h signals in the 2021-08..2026-09 window (sim.py wrote no account); cannot be evaluated."))
    fam = P[P.group.str.startswith("ds_")]
    for gname in sorted(fam.group.unique(), key=lambda x: int(x[4:])):
        r = {cb: fam[(fam.group == gname) & (fam.combo == cb)].iloc[0] for cb in ("A|FC", "ALL|FC", "ALL|SWH", "HI|FC", "T4h|FC")
             if len(fam[(fam.group == gname) & (fam.combo == cb)])}
        defs = sorted(s[2:] for s in PS.strategy.unique() if s.startswith("D:") and s[2:].split("_")[0] == gname[3:])
        ra = r["A|FC"]
        g = grade(ra.meanR_IS + ra.mean_cost, ra.meanR_CF + ra.mean_cost, ra.trades_per_day_per_trader)  # gross approx per half
        numbers = {"definitions": defs,
                   "A_FC": {"meanR": ra.meanR, "IS": ra.meanR_IS, "CF": ra.meanR_CF, "gross": ra.mean_gross, "cost": ra.mean_cost,
                            "trades_per_day_per_trader": ra.trades_per_day_per_trader, "blocked_share": ra.blocked_share},
                   "ALL_FC_meanR": r["ALL|FC"].meanR, "ALL_SWH_meanR": r["ALL|SWH"].meanR,
                   "ALL_SWH_trades_per_day": r["ALL|SWH"].trades_per_day_per_trader,
                   "HI_FC": {"meanR": r["HI|FC"].meanR, "trades_per_day": r["HI|FC"].trades_per_day_per_trader},
                   "T4h_meanR": r["T4h|FC"].meanR if "T4h|FC" in r else None}
        numbers = json.loads(json.dumps(numbers, default=float).replace("NaN", "null"))
        notes.append(dict(strategy=f"DeepSeek {gname[3:]} ({len(defs)} defs pooled)", timeframe="15m+30m (A) vs 15m-4h (B/C) vs 1h+4h (D)",
                          grade=g.replace("gross R", "approx. gross R (net + mean cost per half)"), numbers=numbers,
                          note=(f"A {ra.meanR:+.3f}R at {ra.trades_per_day_per_trader:.2f}/day per def; ALL|SWH {r['ALL|SWH'].meanR:+.3f}R "
                                f"({r['ALL|SWH'].meanR - ra.meanR:+.3f} vs A); 1h+4h {r['HI|FC'].meanR:+.3f}R at "
                                f"{r['HI|FC'].trades_per_day_per_trader:.2f}/day.")))
    return notes


NOTES = strat_notes()

# ------------------------------------------------------------------ findings
c, d = SRD["core36"], SRD["ds44"]
pc = {k: paired("core36", *k) for k in [("ALL|SWH", "A|FC"), ("ALL|FC", "A|FC"), ("ALL|SW", "ALL|FC"), ("A|SW", "A|FC"),
                                         ("HI|FC", "A|FC"), ("ALL|SWH", "ALL|FC"), ("ALLINF|FC", "ALL|FC"), ("ALL|LTF", "ALL|FC"), ("A|SWH", "A|FC")]}
pd_ = {k: paired("ds44", *k) for k in pc}
Dc, Dc_tpd = d_combined("core36")
Dd, Dd_tpd = d_combined("ds44")
bk, bkd = BK["core36"], BK["ds44"]


def ci(p):
    return f"{p['diff']:+.3f}R [95% week-cluster CI {p.ci_lo:+.3f}, {p.ci_hi:+.3f}], better in {p.strategies_a_better}/{p.strategies} strategies"


F = []
hur_lo, hur_hi = c["HI|FC"]["cost"], rc("core36", "A|FC").cost_recent
blk_multi = [r["blk"] for g in ("core36", "ds44") for cb, r in SRD[g].items() if cb in ("A|FC", "ALL|FC", "ALL|SWH", "ALL|LTF", "A|SWH")]
blk_hi = [SRD[g]["HI|FC"]["blk"] for g in ("core36", "ds44")]
per_slot = (c["A|FC"]["spd"] / c["A|FC"]["tpd"], c["ALL|SWH"]["spd"] / c["ALL|SWH"]["tpd"])
hi_ratio = (c["HI|FC"]["usd_month_hi"] / c["A|FC"]["usd_month_hi"], c["HI|FC"]["usd_month_lo"] / c["A|FC"]["usd_month_lo"])
n_aff = (BUDGET / c["A|FC"]["usd_month_hi"], BUDGET / c["A|FC"]["usd_month_lo"])
F.append(dict(id="MT1", claim="Under rules, every setup and every priority rule loses per trade when pooled, for the 36 and for DeepSeek (in both halves); the per-trade loss is almost exactly the trading cost, because the signals' gross R (before fees, slippage, funding) is about zero in every setup.",
              evidence=(f"5-year (2021-08..2026-09, Binance futures bars, 6 coins), house exits, normal leverage chain. Core36 net R/trade: A {c['A|FC']['meanR']:+.3f}, B {c['ALL|FC']['meanR']:+.3f}, "
                        f"C-proxy (switch only to higher tf) {c['ALL|SWH']['meanR']:+.3f}, D = {Dc:+.3f} pooled (15m/30m trader {c['A|FC']['meanR']:+.3f} + 1h/4h trader {c['HI|FC']['meanR']:+.3f}); "
                        f"gross R {c['A|FC']['gross']:+.3f} / {c['ALL|FC']['gross']:+.3f} / {c['ALL|SWH']['gross']:+.3f} / {c['HI|FC']['gross']:+.3f}; cost R {c['A|FC']['cost']:.3f} / {c['ALL|FC']['cost']:.3f} / "
                        f"{c['ALL|SWH']['cost']:.3f} / {c['HI|FC']['cost']:.3f}. DeepSeek44 the same shape (A {d['A|FC']['meanR']:+.3f}, C-proxy {d['ALL|SWH']['meanR']:+.3f}, 1h/4h {d['HI|FC']['meanR']:+.3f}). "
                        f"Both halves (IS 2021-08..2024-06 / CF 2024-07..2026-09) negative in every setup. Strategies with mean R > 0 in A: core {c['A|FC']['pos']}/{c['A|FC']['k']} (the only positive one is N14_ICHI_RSI with {PS[(PS.strategy == 'C:N14_ICHI_RSI') & (PS.combo == 'A|FC') & (PS.period == 'all')].trades.iloc[0]} trades in 5 years), DeepSeek {d['A|FC']['pos']}/{d['A|FC']['k']}. "
                        "summ/pooled.csv, per_strategy.csv."),
              confidence="high", implication="The setup choice cannot make a rule account profitable; it only changes the hurdle the AI must clear (about = cost per trade) and how many decisions it gets. Any AI gain must come from selection/exit skill worth more than about " + f"{hur_lo:.2f}-{hur_hi:.2f}" + "R per trade (1h/4h 5-year cost to A cost in the last 91 days)."))
F.append(dict(id="MT2", claim="Cost hurdle per trade falls with the held timeframe: the C-proxy (one trader on 15m-4h, switching only to a higher timeframe) cuts the hurdle by ~0.03R/trade vs A, and a 1h/4h-only trader by ~0.06R, entirely through lower cost.",
              evidence=(f"Core36 paired vs A|FC: ALL|SWH {ci(pc[('ALL|SWH', 'A|FC')])}; ALL|FC {ci(pc[('ALL|FC', 'A|FC')])}; HI|FC {ci(pc[('HI|FC', 'A|FC')])}. "
                        f"DeepSeek44: ALL|SWH {ci(pd_[('ALL|SWH', 'A|FC')])}; HI|FC {ci(pd_[('HI|FC', 'A|FC')])}. "
                        f"Cost R by single-tf rule account (core): 15m {c['T15|FC']['cost']:.3f}, 30m {c['T30|FC']['cost']:.3f}, 1h {c['T1h|FC']['cost']:.3f}, 4h {c['T4h|FC']['cost']:.3f}. "
                        f"Last 91 days of the data (2026-07..09, quieter): A cost {rc('core36', 'A|FC').cost_recent:.3f}R, ALL|SWH {rc('core36', 'ALL|SWH').cost_recent:.3f}R, HI {rc('core36', 'HI|FC').cost_recent:.3f}R (net {rc('core36', 'A|FC').meanR_recent:+.3f} / {rc('core36', 'ALL|SWH').meanR_recent:+.3f} / {rc('core36', 'HI|FC').meanR_recent:+.3f}). paired.csv, recent_cost.csv."),
              confidence="high (differences are cost arithmetic; CIs exclude 0 and nearly every strategy agrees)",
              implication="Lowest cost hurdle per decision: 1h/4h trader (D's second trader) < C-proxy < B < A. At today's volatility the A hurdle is ~0.20R/trade."))
F.append(dict(id="MT3", claim="Decision counts: A and B/C give ~4-5 rule trades/day per trader out of ~25-29 signals/day; a 1h/4h-only trader gets ~1.2-1.5 trades/day out of ~4 signals/day, too few to confirm an AI effect within a 60-day check.",
              evidence=(f"Core36 per trader: A {c['A|FC']['tpd']:.2f} trades/day from {c['A|FC']['spd']:.1f} signals/day; ALL|SWH {c['ALL|SWH']['tpd']:.2f} from {c['ALL|SWH']['spd']:.1f}; HI {c['HI|FC']['tpd']:.2f} from {c['HI|FC']['spd']:.1f}. "
                        f"Smallest mean-R change detectable in 60 days (80% power, 5% two-sided, i.i.d. trades = optimistic): A {c['A|FC']['mde60']:.2f}R, ALL|SWH {c['ALL|SWH']['mde60']:.2f}R, HI {c['HI|FC']['mde60']:.2f}R "
                        f"(R sd {c['A|FC']['sd']:.2f} / {c['ALL|SWH']['sd']:.2f} / {c['HI|FC']['sd']:.2f}). Live v4 cross-check (1.5 days): core A {lv('strategy', 'A').trades_per_day_per_trader:.2f} trades/day/trader, HI {lv('strategy', 'HI').trades_per_day_per_trader:.2f}. pooled.csv, dd_quarter_summary.csv, live_check_summary.csv."),
              confidence="medium-high (MDE ignores time clustering, so real MDEs are larger)",
              implication="C-proxy gives the most decisions at the lowest per-trade hurdle with enough n; D's 1h/4h trader has the lowest hurdle but cannot be judged by 12/31 on its own."))
F.append(dict(id="MT4", claim=f"One position at a time blocks most signals: {pct(min(blk_multi))}-{pct(max(blk_multi))} in setups that include 15m/30m, {pct(min(blk_hi))}-{pct(max(blk_hi))} for a 1h/4h trader; and the blocked signals are no better than the taken ones, so blocking per se does not throw away measurable edge.",
              evidence=(f"Blocked by an open position (ties at the same moment listed separately), core: A {pct(c['A|FC']['blk'])} (+{pct(c['A|FC']['tie'])}), B {pct(c['ALL|FC']['blk'])} (+{pct(c['ALL|FC']['tie'])}), C-proxy {pct(c['ALL|SWH']['blk'])} (+{pct(c['ALL|SWH']['tie'])}), HI {pct(c['HI|FC']['blk'])}; "
                        f"blocked signals alone {c['A|FC']['blkR']:+.3f}R vs taken {c['A|FC']['takenR']:+.3f}R (A), {c['ALL|SWH']['blkR']:+.3f} vs {c['ALL|SWH']['takenR']:+.3f} (C-proxy). "
                        f"Live v4 (1.5 days, replayed signals): A blocked {pct(lv('strategy', 'A').blocked_share)} (core) / {pct(lv('ds200', 'A').blocked_share)} (DeepSeek). pooled.csv, live_check_summary.csv."),
              confidence="high for the shares; the 'no better' statement is about rules, an AI choosing among signals could differ",
              implication=f"The AI has about {per_slot[0]:.1f}-{per_slot[1]:.1f} signals per position slot to choose from (A, C-proxy); a skip-heavy AI loses little by passing. Ranking/skip skill is where an AI could add value."))
F.append(dict(id="MT5", claim="Long 1h/4h holds do block many 15m/30m signals, but the blocked low-tf signals during 4h holds are the worst ones (quiet-market 15m signals with high cost in R).",
              evidence=(f"Core ALL|FC: 1h/4h positions are {pct(bk['ALL|FC']['hi_time'])} of held time and cause {pct(bk['ALL|FC']['by_hi'])} of blocked 15m/30m signals; {pct(bk['ALL|FC']['ge5'])} of 1h/4h trades block >= 5 and {pct(bk['ALL|FC']['ge10'])} >= 10 15m/30m signals (mean {bk['ALL|FC']['per_hi']:.1f}). "
                        f"With switch-only-to-higher (C-proxy) 1h/4h hold {pct(bk['ALL|SWH']['hi_time'])} of the time, {pct(bk['ALL|SWH']['ge10'])} block >= 10. "
                        f"15m signals blocked while a 4h position is open: {bk['blk15_by_4h_R']:+.3f}R alone vs {bk['blk15_by_15_R']:+.3f}R when blocked by a 15m position. DeepSeek: by_hi {pct(bkd['ALL|FC']['by_hi'])}, >=10 {pct(bkd['ALL|FC']['ge10'])}. blocking_long.csv, blocked_matrix.csv."),
              confidence="high", implication="Letting 1h/4h signals occupy the trader is not costly in R terms; it is the reason C/B beat A (fewer expensive 15m trades)."))
F.append(dict(id="MT6", claim="Switching to any new signal (the 'human' switch) is the worst proxy: 3x the trades, more cost, lower R; switching only to a higher timeframe is the best of the four rules.",
              evidence=(f"Core: ALL|SW vs ALL|FC {ci(pc[('ALL|SW', 'ALL|FC')])}; A|SW vs A|FC {ci(pc[('A|SW', 'A|FC')])}; ALL|SWH vs ALL|FC {ci(pc[('ALL|SWH', 'ALL|FC')])}; longer-tf-first on ties vs first-come {ci(pc[('ALL|LTF', 'ALL|FC')])}. "
                        f"ALL|SW trades/day {c['ALL|SW']['tpd']:.1f}, {c['ALL|SW']['sw']:.1f} switches/day; the early close itself costs ~0 ({pr('core36', 'ALL|SW').switch_cost_R:+.3f}R vs holding), the loss is the extra round trips. DeepSeek same sign: ALL|SW vs ALL|FC {ci(pd_[('ALL|SW', 'ALL|FC')])}. paired.csv."),
              confidence="high", implication="If the AI may switch, the default should be 'hold unless a higher-timeframe signal arrives'; frequent switching raises the hurdle."))
F.append(dict(id="MT7", claim="Leverage: with the house 2 ATR stop and the 1 ATR liquidation buffer, 20-50x is executable on 15m (and mostly 30m), 20x only on part of 1h, and 4h almost only on BTC (ETH in quiet weeks). Risk-per-stop sizing (2-5%) does not change the 20x limit, because the liquidation buffer binds; it only removes the 15% loss cap that blocks 40-50x.",
              evidence=(f"Share of bars sizable, mean over 6 coins, 5y / last 30 days: 4h at 20x house {pct(fe('4h', '5y', 'house_20x_pass'))} / {pct(fe('4h', 'last30d', 'house_20x_pass'))}, 30x {pct(fe('4h', '5y', 'house_30x_pass'), 1)} / {pct(fe('4h', 'last30d', 'house_30x_pass'))}; "
                        f"1h 20x {pct(fe('1h', '5y', 'house_20x_pass'))} / {pct(fe('1h', 'last30d', 'house_20x_pass'))}, 30x {pct(fe('1h', '5y', 'house_30x_pass'))} / {pct(fe('1h', 'last30d', 'house_30x_pass'))}; "
                        f"15m 50x house {pct(fe('15m', '5y', 'house_50x_pass'))} / {pct(fe('15m', 'last30d', 'house_50x_pass'))} vs risk-per-stop 2% {pct(fe('15m', '5y', 'risk2_50x_pass'))} / {pct(fe('15m', 'last30d', 'risk2_50x_pass'))}. "
                        f"4h 20x by coin 5y / last30d: " + "; ".join(f"{cc[:-3]} {pct(fe_c4.loc[(cc, '5y')])}/{pct(fe_c4.loc[(cc, 'last30d')])}" for cc in ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")) +
                        f". Live v4: {pct(1 - LRS['strategy'])} of core and {pct(1 - LRS['ds200'])} of DeepSeek 4h signals sized (rest REJECTED_SIZING). feas.csv, live_check.py."),
              confidence="high (mechanical; brackets inferred from live trades)",
              implication=f"'4h only where 20x executes' means mostly BTC 4h; in the 5-year simulation it keeps 4h trades rare (core 4h rule account {c['T4h|FC']['tpd']:.2f} trades/day). Admitting sub-20x 4h trades (sensitivity ALLINF vs B) changes R by {pc[('ALLINF|FC', 'ALL|FC')]['diff']:+.3f} only."))
F.append(dict(id="MT8", claim="Drawdown at fixed risk: with ~4 trades/day, even a zero-net-edge trader at 1% risk per stop breaches the design's 25% drawdown gate in about a quarter of 91-day windows under A, less under the C-proxy, and almost never under a 1h/4h trader.",
              evidence=(f"Rule R series with each strategy's own mean removed (pure noise), 91-day windows, 1% risk per trade: median DD A {pct(c['A|FC']['dd1q0'])}, p90 {pct(c['A|FC']['dd1q0_p90'])}, windows > 25%: {pct(c['A|FC']['dd1q0_gt25'])}; "
                        f"C-proxy {pct(c['ALL|SWH']['dd1q0'])} / {pct(c['ALL|SWH']['dd1q0_p90'])} / {pct(c['ALL|SWH']['dd1q0_gt25'])}; HI {pct(c['HI|FC']['dd1q0'])} / {pct(c['HI|FC']['dd1q0_p90'])} / {pct(c['HI|FC']['dd1q0_gt25'])}. "
                        f"With the actual negative drift at 2% risk the median 91-day DD is {pct(c['A|FC']['dd2q'])} (A), {pct(c['ALL|SWH']['dd2q'])} (C-proxy), {pct(c['HI|FC']['dd2q'])} (HI); share of 91-day windows with positive sum R: A {pct(c['A|FC']['winpos'], 1)}, HI {pct(c['HI|FC']['winpos'], 1)}. dd_quarter_summary.csv."),
              confidence="medium-high (assumes trade-sequence noise like the rules'; an AI that trades less would see less)",
              implication="The DD gate is easier to pass with fewer, longer trades; at A's frequency the gate partly measures noise. Consider 0.5-1% risk per stop for 15m/30m traders."))
F.append(dict(id="MT9", claim="AI call volume is dominated by holding checks and by whether busy-time signals are shown to the AI; per-trader cost is similar for A, B and C, and a 1h/4h trader costs " + f"{pct(hi_ratio[0])}-{pct(hi_ratio[1])}" + " of an A trader.",
              evidence=(f"Per trader per day (core), entry calls between 'free-time signals only' and 'every signal incl. hold/switch consults', plus a check every 30 min while holding: A {c['A|FC']['calls_lo']:.0f}..{c['A|FC']['calls_hi']:.0f}, B/C {c['ALL|SWH']['calls_lo']:.0f}..{c['ALL|SWH']['calls_hi']:.0f}, 1h/4h trader {c['HI|FC']['calls_lo']:.0f}..{c['HI|FC']['calls_hi']:.0f}; "
                        f"at $0.03/call (design v2 estimate): ${c['A|FC']['usd_month_lo']:.0f}..${c['A|FC']['usd_month_hi']:.0f}, ${c['ALL|SWH']['usd_month_lo']:.0f}..${c['ALL|SWH']['usd_month_hi']:.0f}, ${c['HI|FC']['usd_month_lo']:.0f}..${c['HI|FC']['usd_month_hi']:.0f} per trader-month; "
                        f"30 traders A: ${30 * c['A|FC']['usd_month_lo']:.0f}..${30 * c['A|FC']['usd_month_hi']:.0f} vs the $500 budget. D needs two traders per strategy (A + 1h/4h): ${c['A|FC']['usd_month_lo'] + c['HI|FC']['usd_month_lo']:.0f}..${c['A|FC']['usd_month_hi'] + c['HI|FC']['usd_month_hi']:.0f} per strategy-month. "
                        f"Checks at each held-timeframe bar close instead of every 30m: A {c['A|FC']['calls_bar']:.0f}/day, C-proxy {c['ALL|SWH']['calls_bar']:.0f}/day, HI {c['HI|FC']['calls_bar']:.0f}/day (free-entry calls included). pooled.csv."),
              confidence="medium (call price is the design doc's estimate; an AI that skips more makes more entry calls and fewer hold calls)",
              implication=f"$500/month covers about {n_aff[0]:.0f}-{n_aff[1]:.0f} A traders with 30-min hold checks, not 30, unless hold checks are thinned (e.g. bar-close of the held tf on 1h/4h positions) or busy-time signals are filtered by code."))
F.append(dict(id="MT10", claim="Ranking for 'conditions for the AI' (not profitability): C (one trader, 15m/30m/1h + 4h where 20x sizes, default hold, switch only to a higher timeframe) > B (same scope, first-come) > A on hurdle at the same decision count. D = A's 15m/30m seat plus a 1h/4h seat that has the lowest hurdle but the fewest decisions, and it doubles the seats.",
              evidence=(f"Core: hurdle (cost/trade) C {c['ALL|SWH']['cost']:.3f}R, B {c['ALL|FC']['cost']:.3f}R, A {c['A|FC']['cost']:.3f}R, D {c['A|FC']['cost']:.3f}R (15m/30m seat) + {c['HI|FC']['cost']:.3f}R (1h/4h seat); trades/day {c['ALL|SWH']['tpd']:.2f} / {c['ALL|FC']['tpd']:.2f} / {c['A|FC']['tpd']:.2f} / {Dc_tpd:.2f} (two seats); "
                        f"net R/trade {c['ALL|SWH']['meanR']:+.3f} / {c['ALL|FC']['meanR']:+.3f} / {c['A|FC']['meanR']:+.3f} / {Dc:+.3f}; zero-edge 91-day DD > 25% at 1% risk {pct(c['ALL|SWH']['dd1q0_gt25'])} / {pct(c['ALL|FC']['dd1q0_gt25'])} / {pct(c['A|FC']['dd1q0_gt25'])} / {pct(c['A|FC']['dd1q0_gt25'])}+{pct(c['HI|FC']['dd1q0_gt25'])}. "
                        f"C vs A per strategy: better in {pc[('ALL|SWH', 'A|FC')].strategies_a_better}/{pc[('ALL|SWH', 'A|FC')].strategies} core and {pd_[('ALL|SWH', 'A|FC')].strategies_a_better}/{pd_[('ALL|SWH', 'A|FC')].strategies} DeepSeek. All four remain negative."),
              confidence="medium (rule proxies, not an AI; the ranking is about the starting hurdle and sample size)",
              implication="If one AI seat per strategy, give it 15m/30m/1h (+BTC-type 4h when 20x sizes) with a 'switch only upward' default; keep 4h rule accounts as controls. Do not expect the setup alone to change the sign."))

limits = [
    "Rule proxies only: the AI's choices (skip, early exit, switch) are replaced by fixed priority rules; an AI that skips more changes trades/day, blocking and call counts.",
    "Sizing uses the 'normal' chain (30x/30% then 20x/20%) for every signal; the live core run gives ~22% of signals 50x/40x ('best'), which changes ladder R slightly (the ROE ladder locks at smaller price moves at higher leverage).",
    "Stops and ladder checked on 15m bars for all timeframes (live engine uses 1m; the 5-year studies used each tf's own bars). 15m parity with research/strategy_profiles/profiles._scan is exact (3,000 of 3,000 sampled LTC 15m signals to 1e-6); 4h mean R on a 3,000-signal BTC sample is -0.0758R vs -0.0783R on own-tf bars (parity_check.py).",
    "A position frees the trader only after the 15m bar of its exit (conservative by up to 15 minutes); same-moment signals: one taken, the rest counted as 'ties'.",
    "Switching closes the held position at the next 15m open (taker fee + slippage); a new signal on the held coin and side is treated as 'hold'.",
    "Bars are Binance USD-M futures 2021-01..2026-09-29 (scratchpad/binance); 'current' volatility = last 30 days of that data (2026-08-30..09-29) plus the 1.5-day live v4 replay; brackets inferred from live trades, equity $5,000.",
    "MDE and confidence intervals: pooled CIs are week-cluster bootstraps over 2021-2026, but strategies inside a group are correlated (same coins, overlapping signals; several DeepSeek definitions duplicate each other), so group pooled CIs are optimistic; MDE assumes i.i.d. trades.",
    "AI cost uses the design doc's ~$0.03 per Sonnet call; actual cost depends on prompt size and caching.",
    "DeepSeek definitions are run under the house exits (as in paper v4), not their PREREG exits; 'main families' = all 17 families, pooled per family.",
    "N21_ST_RSI_ADX produced no 15m-4h signals in the 5-year window and cannot be evaluated; N14_ICHI_RSI has only a handful of trades in 5 years.",
    "Grades in strategy_notes: A = gross R in the A setup > 0 in both halves, B = in one half, C = in neither, D = under 1 trade/day in the A scope; for DeepSeek families gross per half is approximated by net + whole-window mean cost.",
]

files = {
    "folder": HERE,
    "scripts": [os.path.join(HERE, f) for f in ("ds_signals.py", "precompute.py", "parity_check.py", "sim.py", "summarize.py",
                                                "dd_quarter.py", "recent.py", "feas.py", "live_check.py", "build_json.py")],
    "tables": [os.path.join(HERE, "summ", f) for f in ("pooled.csv", "per_strategy.csv", "paired.csv", "blocking_long.csv",
                                                        "blocked_matrix.csv", "dd_quarter.csv", "dd_quarter_summary.csv",
                                                        "recent_cost.csv", "live_check.csv", "live_check_summary.csv", "live_rejected.csv")] +
              [os.path.join(HERE, "feas.csv")],
    "caches": [os.path.join(HERE, "ds_sig"), os.path.join(HERE, "outc"), os.path.join(HERE, "res")],
    "inputs": ["/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/binance/signals (sig_<tf>_<coin>.npz: 36 core signals, bars, ATR14)",
               "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/binance/bars (DeepSeek signals via research/deepseek200/lib_c.entries)",
               "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/rb_analyze/out_real/replay_signals.csv",
               "repo (read-only): paperbot/sizing.py, config.v3_settings, ladder.py, margin.py; research/strategy_profiles/profiles.py (_scan copied); research/paper_rules/rules_bt.py (one-position account logic, adapted)"],
}

# ------------------------------------------------------------------ report section
rep = "## Which timeframe setup for one AI trader per strategy (5-year rule proxies)\n\n"
rep += ("**Bottom line.** Under rules every setup loses: the signals' gross R before costs is about 0 in all of them, so the "
        "net loss per trade is the trading cost. The setup only changes how high that cost hurdle is and how many decisions "
        "the AI gets. Of the four setups, **C (one trader on 15m/30m/1h, plus 4h when 20x can be sized, holding by default and "
        f"switching only to a higher timeframe)** gives the AI the best conditions: hurdle {c['ALL|SWH']['cost']:.3f}R per trade "
        f"vs {c['A|FC']['cost']:.3f}R for A, {c['ALL|SWH']['tpd']:.1f} trades/day, and the smallest 60-day detectable effect "
        f"({c['ALL|SWH']['mde60']:.2f}R vs {c['A|FC']['mde60']:.2f}R). D's 1h/4h trader has the lowest hurdle ({c['HI|FC']['cost']:.3f}R) "
        f"but makes only {c['HI|FC']['tpd']:.1f} trades/day and needs a second seat. Nothing here says any setup will turn positive.\n\n")
rep += "### Setups, core 36 (pooled, 2021-08..2026-09)\n\n" + md_table("core36") + "\n"
rep += "### Setups, DeepSeek 44 definitions (house exits)\n\n" + md_table("ds44") + "\n"
rep += (f"Setup D pooled (15m/30m seat + 1h/4h seat): core {Dc:+.3f}R at {Dc_tpd:.2f} trades/day for two seats; DeepSeek {Dd:+.3f}R at {Dd_tpd:.2f}.\n\n"
        "Columns: blocked = signals that came while the trader held a position (ties = several signals at the same bar close, one taken); "
        "blocked signals' R = what they would have made alone; 91d DD = drawdown in 91-day windows of the rule R series with the strategy's "
        "own mean removed (the noise a zero-edge trader still sees), 1% risk per stop; MDE 60d = smallest mean-R change detectable in 60 days "
        "(80% power, i.i.d. trades); AI calls = entry decisions (free-time only .. every signal) + a holding check every 30 min; $ at ~$0.03/call.\n\n")
rep += "### Paired differences (same weeks resampled; core 36)\n\n| comparison | difference | strategies better |\n|---|---|---|\n"
for k, p in pc.items():
    rep += f"| {k[0]} minus {k[1]} | {p['diff']:+.3f}R [{p.ci_lo:+.3f}, {p.ci_hi:+.3f}] | {p.strategies_a_better}/{p.strategies} |\n"
rep += ("\n### Long 1h/4h holds and the 15m/30m signals they block (core, B = first-come over 4 tfs)\n\n"
        f"- 1h/4h positions take {pct(bk['ALL|FC']['hi_time'])} of the held time and cause {pct(bk['ALL|FC']['by_hi'])} of the blocked 15m/30m signals.\n"
        f"- {pct(bk['ALL|FC']['ge5'])} of 1h/4h trades block at least 5 lower-timeframe signals, {pct(bk['ALL|FC']['ge10'])} at least 10, {pct(bk['ALL|FC']['ge20'])} at least 20.\n"
        f"- Under switch-only-upward (C proxy) the 1h/4h share of held time rises to {pct(bk['ALL|SWH']['hi_time'])}, and {pct(bk['ALL|SWH']['ge10'])} of 1h/4h trades block 10 or more.\n"
        f"- The 15m signals blocked by a 4h position would have made {bk['blk15_by_4h_R']:+.3f}R alone, compared with {bk['blk15_by_15_R']:+.3f}R for 15m signals blocked by a 15m position. They come in quiet markets, where a 15m stop is tight and the cost per R is high.\n\n")
rep += "### Leverage that can actually be executed with the house 2 ATR stop (share of bars, mean of 6 coins)\n\n" + lev_md() + "\n"
rep += ("Risk-per-stop sizing at 2-5% leaves the 20x limit where it is, because the stop has to sit inside liquidation by 1 ATR. "
        "It only removes the 15% loss cap that blocks 40-50x on 15m/30m. In practice, \"4h only where 20x executes\" means BTC 4h, "
        "plus ETH 4h in quiet weeks.\n\n")
rep += (f"### Current market\n\nIn the last 91 days of the data the cost hurdle is higher: A {rc('core36', 'A|FC').cost_recent:.3f}R, C-proxy {rc('core36', 'ALL|SWH').cost_recent:.3f}R, "
        f"1h/4h {rc('core36', 'HI|FC').cost_recent:.3f}R. The live v4 replay (1.5 days) shows the same blocking: A blocked {pct(lv('strategy', 'A').blocked_share)} of core signals, "
        f"at {lv('strategy', 'A').trades_per_day_per_trader:.1f} trades/day per trader.\n\n")
rep += "### Limits\n\n" + "".join(f"- {x}\n" for x in limits)

out = dict(findings=F, strategy_notes=NOTES, files=files, limits=limits, report_section_md=rep)
with open(out_json, "w") as fh:
    json.dump(out, fh, indent=1, default=float, ensure_ascii=False)
print("wrote", out_json, len(F), "findings", len(NOTES), "notes")
print(rep[:6000])
