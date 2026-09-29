"""Markdown tables from out/metrics.csv + out/calibration.csv -> out/tables.md (pasted into NOTES.md)."""
import json
import numpy as np
import pandas as pd

MALL = pd.read_csv("out/metrics.csv")
CALL = pd.read_csv("out/calibration.csv")
M = MALL[MALL.res == "5m"].copy()          # base: exits resolved on 5m sub-bars (5m TF: native)
CAL = CALL[CALL.res == "5m"].copy()
TAGS = {"5m": "5m", "15m": "15m_fine", "1h": "1h_fine", "4h": "4h_fine"}
TFS = [t for t in ["5m", "15m", "1h", "4h"] if t in set(M.tf)]
NAMED = ["S0", "S1", "S2", "S3", "S4"]
SDESC = {"S0": "S0 no edge", "S1": "S1 +0.05% uniform", "S2": "S2 +0.10% uniform", "S3": "S3 +0.05% concentrated", "S4": "S4 +0.10% concentrated"}
out = []
P = out.append


def get(tf, scen, pol, stop="1.5", tp="roe", order="adv"):
    r = M[(M.tf == tf) & (M.scen == scen) & (M.pol == pol) & (M.stop.astype(str) == stop) & (M.tp == tp) & (M.order == order)]
    assert len(r) == 1, (tf, scen, pol, stop, tp, order, len(r))
    return r.iloc[0]


def money(x):
    if x >= 1e6:
        return f"${x/1e6:.1f}M"
    if x >= 1e4:
        return f"${x/1e3:.0f}k"
    return f"${x:,.0f}"


def pct(x):
    return f"{100*x:.0f}%" if x >= 0.01 or x == 0 else f"{100*x:.1f}%"


# ------------------------------------------------------------------ setup
P("### Setup per TF (all measured by code)\n")
P("| TF | edge horizon h_e (bars) | E\\|r_he\\| per coin (min-max) | candidates/day | tiered S0 trades/month taken | mean hold (bars) tiered S0 | q at +0.05% / +0.10% (mean over coins) | direction hit-rate at +0.05% / +0.10% |")
P("|---|---|---|---|---|---|---|---|")
for tf in TFS:
    meta = json.load(open(f"out/{TAGS[tf]}_meta.json"))
    E = np.array(list(meta["Eabs"].values()))
    r = get(tf, "S0", "tiered")
    q1 = CAL[(CAL.tf == tf) & (CAL.scen == "S1")].q_mean.iloc[0]
    q2 = CAL[(CAL.tf == tf) & (CAL.scen == "S2")].q_mean.iloc[0]
    P(f"| {tf} | {meta['HE']} | {100*E.min():.2f}-{100*E.max():.2f}% | {meta['lam']:.2f} | {r.trades_pm:.0f} | {r.hold_bars:.1f} | "
      f"{q1:.3f} / {q2:.3f} | {100*(1+q1)/2:.1f}% / {100*(1+q2)/2:.1f}% |")

# ------------------------------------------------------------------ calibration
P("\n### Edge calibration check (target = planted mean drift side*r_he; realised = mean over all candidates, averaged over seeds)\n")
P("| TF | scenario | target avg | realised avg (all cand.) | realised top-10% | realised other 90% | taken trades, tiered base: drift top / rest | captured gross per trade at actual exit: tiered / flat20 / max50 / rec |")
P("|---|---|---|---|---|---|---|---|")
for tf in TFS:
    for sc in NAMED:
        c = CAL[(CAL.tf == tf) & (CAL.scen == sc)].iloc[0]
        r = get(tf, sc, "tiered")
        caps = " / ".join(f"{100*get(tf, sc, p).gross_pt:+.3f}%" for p in ["tiered", "flat20", "max50", "rec"])
        P(f"| {tf} | {sc} | {100*c.D:.3f}% | {100*c.drift_all:+.3f}% | {100*c.drift_top:+.3f}% | {100*c.drift_rest:+.3f}% | "
          f"{100*r.drift_t2:+.3f}% / {100*r.drift_rest:+.3f}% | {caps} |")

# ------------------------------------------------------------------ headline
for order, lab in [("adv", "ADVERSE-first (conservative, base)"), ("fav", "FAVOURABLE-first (optimistic)")]:
    P(f"\n### HEADLINE ({lab}): stop 1.5 ATR, TP +10% ROE, 64-bar time exit, from $1,000, 5,000 bootstrap paths\n")
    P("P(<$500) = end-of-12-month equity below $500 / ever below $500 at any trade exit within 12 months.\n")
    P("| TF | scenario | USER TIERED: 1m median | 12m median | P(<$500) end / ever | liq / month | RECOMMENDED: 1m median | 12m median | P(<$500) end / ever | liq / month |")
    P("|---|---|---|---|---|---|---|---|---|---|")
    for tf in TFS:
        for sc in NAMED:
            a = get(tf, sc, "tiered", order=order); b = get(tf, sc, "rec", order=order)
            P(f"| {tf} | {SDESC[sc]} | {money(a['1m_med'])} | {money(a['12m_med'])} | {pct(a['12m_P500'])} / {pct(a['12m_P500ever'])} | {a.liq_pm:.1f} | "
              f"{money(b['1m_med'])} | {money(b['12m_med'])} | {pct(b['12m_P500'])} / {pct(b['12m_P500ever'])} | {b.liq_pm:.2f} |")

# ------------------------------------------------------------------ references
P("\n### Reference sizing rules (adverse-first, stop 1.5 ATR, TP +10% ROE): 12m median / P(end<$500) / P(ever<$100) / liq per month\n")
P("| TF | scenario | tiered | flat 20x x 20% | always 50x x 40% | recommended |")
P("|---|---|---|---|---|---|")
for tf in TFS:
    for sc in NAMED:
        cells = []
        for p in ["tiered", "flat20", "max50", "rec"]:
            r = get(tf, sc, p)
            cells.append(f"{money(r['12m_med'])} / {pct(r['12m_P500'])} / {pct(r['12m_P100ever'])} / {r.liq_pm:.1f}")
        P(f"| {tf} | {sc} | " + " | ".join(cells) + " |")

# ------------------------------------------------------------------ full distribution for tiered and rec
P("\n### Distribution detail (adverse-first, stop 1.5 ATR, TP +10% ROE): median [p10 - p90] at 1m / 3m / 12m; P(<$100) end/ever at 12m\n")
P("| TF | scenario | policy | 1 month | 3 months | 12 months | P(<$100) 12m end / ever |")
P("|---|---|---|---|---|---|---|")
for tf in TFS:
    for sc in NAMED:
        for p in ["tiered", "rec"]:
            r = get(tf, sc, p)
            cells = [f"{money(r[f'{h}_med'])} [{money(r[f'{h}_p10'])} - {money(r[f'{h}_p90'])}]" for h in ["1m", "3m", "12m"]]
            P(f"| {tf} | {sc} | {p} | " + " | ".join(cells) + f" | {pct(r['12m_P100'])} / {pct(r['12m_P100ever'])} |")

# ------------------------------------------------------------------ exit variants
P("\n### Exit variants: 12m median / P(end<$500) / liq per month, tiered vs recommended (A = adverse-first, F = favourable-first)\n")
P("| TF | scenario | exit | tiered A | tiered F | rec A | rec F |")
P("|---|---|---|---|---|---|---|")
for tf in TFS:
    for sc in ["S0", "S2", "S4"]:
        for st, tp in [("1.5", "roe"), ("1.5", "2x"), ("1.0", "roe"), ("1.0", "2x")]:
            cells = []
            for p in ["tiered", "rec"]:
                for o in ["adv", "fav"]:
                    r = get(tf, sc, p, st, tp, o)
                    cells.append(f"{money(r['12m_med'])} / {pct(r['12m_P500'])} / {r.liq_pm:.1f}")
            tpl = "TP 10% ROE" if tp == "roe" else "TP max(10% ROE, 2x stop)"
            P(f"| {tf} | {sc} | {st} ATR, {tpl} | " + " | ".join(cells) + " |")

# ------------------------------------------------------------------ fees + trade mechanics
P("\n### Costs and trade mechanics (S0, adverse-first, stop 1.5 ATR, TP +10% ROE)\n")
P("| TF | policy | trades/month | mean notional (x equity) | cost per trade (% of equity) | fees paid in 12m, median path ($, from $1,000 start) | fees / (1000 - 12m median equity) | exits TP / stop / liq / time | liq rate normal / good / perfect | win rate |")
P("|---|---|---|---|---|---|---|---|---|---|")
for tf in TFS:
    for p in ["tiered", "flat20", "max50", "rec"]:
        r = get(tf, "S0", p)
        P(f"| {tf} | {p} | {r.trades_pm:.0f} | {r.mean_N:.2f} | {100*r.fee_eq_pt:.2f}% | {money(r['12m_fees_med'])} ({100*r['12m_fees_med']/1000:.0f}%) | "
          f"{(pct(r['12m_fees_med'] / (1000 - r['12m_med'])) if r['12m_med'] < 1000 else 'n/a (gain)')} | "
          f"{pct(r.tp_share)} / {pct(r.stop_share)} / {pct(r.liq_share)} / {pct(r.time_share)} | "
          f"{pct(r.liq_rate_t0)} / {pct(r.liq_rate_t1)} / {pct(r.liq_rate_t2)} | {pct(r.win)} |")

# ------------------------------------------------------------------ minimum edge
P("\n### Minimum average planted drift (at h_e) for: 12m median > $1,000 AND P(12m end < $500) < 20%\n")
P("Grid search over planted average drift; value = smallest grid point from which the criterion holds at every larger feasible "
  "grid point. '> X' = not met up to X, the largest feasible drift (q <= 1 on every coin; concentrated: top-decile q <= 1). "
  "Hit-rate = share of trades whose direction matches the sign of the h_e-bar move, (1+q)/2 averaged over coins. "
  "Stop 1.5 ATR, TP +10% ROE.  Also shown: the criterion with 'ever below $500' instead of 'end below $500'.\n")
ME = []
P("| TF | edge structure | order | tiered | flat 20x20% | max 50x40% | recommended | tiered (ever<$500 < 20%) | rec (ever<$500 < 20%) |")
P("|---|---|---|---|---|---|---|---|---|")
for tf in TFS:
    for conc, lab in [(False, "uniform (score useless)"), (True, "concentrated (top-10% = 3x)")]:
        for o in ["adv", "fav"]:
            cells = []
            for p, key in [("tiered", "12m_P500"), ("flat20", "12m_P500"), ("max50", "12m_P500"), ("rec", "12m_P500"),
                           ("tiered", "12m_P500ever"), ("rec", "12m_P500ever")]:
                sub = M[(M.tf == tf) & (M.pol == p) & (M.stop.astype(str) == "1.5") & (M.tp == "roe") & (M.order == o) &
                        (((M.conc == conc) & (M.scen.str[0] == ("C" if conc else "U"))) | (M.scen == "S0"))].sort_values("D")
                ok = (sub["12m_med"] > 1000) & (sub[key] < 0.20)
                okv = ok.values; Ds = sub.D.values
                idx = None
                for i in range(len(okv)):
                    if okv[i:].all():
                        idx = i; break
                if idx is None:
                    cells.append(f"> {100*Ds.max():.3f}%"); dmin = np.nan
                else:
                    dmin = Ds[idx]
                    sc = sub.scen.values[idx]
                    c = CAL[(CAL.tf == tf) & (CAL.scen == sc)].iloc[0]
                    hr = f"hit {100*(1+c.q_top)/2:.0f}%/{100*(1+c.q_rest)/2:.0f}%" if conc else f"hit {100*(1+c.q_mean)/2:.1f}%"
                    cap = sub.gross_pt.values[idx]
                    cells.append(f"{100*dmin:.3f}% ({hr}; captured {100*cap:+.3f}%)")
                ME.append(dict(tf=tf, conc=conc, order=o, pol=p, crit=key, min_D=dmin, max_tested=Ds.max()))
            P(f"| {tf} | {lab} | {o} | " + " | ".join(cells) + " |")
pd.DataFrame(ME).to_csv("out/min_edge.csv", index=False)

# ------------------------------------------------------------------ edge sweep curves (tiered vs rec)
P("\n### Edge sweep (adverse-first, stop 1.5 ATR, TP +10% ROE): 12m median / P(end<$500)\n")
for tf in TFS:
    for conc, pre in [(False, "U"), (True, "C")]:
        sub = M[(M.tf == tf) & (M.stop.astype(str) == "1.5") & (M.tp == "roe") & (M.order == "adv") &
                ((M.scen.str[0] == pre) | (M.scen == "S0"))]
        Ds = sorted(set(sub.D))
        P(f"\n{tf}, {'concentrated' if conc else 'uniform'}:\n")
        P("| planted drift | " + " | ".join(f"{100*d:.3f}%" for d in Ds) + " |")
        P("|---|" + "---|" * len(Ds))
        for p in ["tiered", "flat20", "max50", "rec"]:
            cells = []
            for d in Ds:
                r = sub[(sub.pol == p) & np.isclose(sub.D, d) & ((sub.scen == "S0") if d == 0 else True)].iloc[0]
                cells.append(f"{money(r['12m_med'])} / {pct(r['12m_P500'])}")
            P(f"| {p} | " + " | ".join(cells) + " |")

# ------------------------------------------------------------------ exit-resolution / ordering sensitivity
P("\n### Sensitivity to intrabar path assumptions (stop 1.5 ATR, TP +10% ROE): 12m median / P(end<$500) / liq per month\n")
P("'TF bars' = exits resolved on the chart-TF OHLC bars; '5m sub-bars' = resolved on the 5m bars inside them (base). "
  "A = adverse-first, F = favourable-first inside a bar.\n")
P("| TF | scenario | policy | TF bars A | TF bars F | 5m sub-bars A (BASE) | 5m sub-bars F |")
P("|---|---|---|---|---|---|---|")
for tf in [t for t in TFS if t != "5m"]:
    for sc in ["S0", "S2", "S4"]:
        for p in ["tiered", "flat20", "max50", "rec"]:
            cells = []
            for res in ["tf", "5m"]:
                for o in ["adv", "fav"]:
                    r = MALL[(MALL.tf == tf) & (MALL.res == res) & (MALL.scen == sc) & (MALL.pol == p) &
                             (MALL.stop.astype(str) == "1.5") & (MALL.tp == "roe") & (MALL.order == o)]
                    if len(r) == 0:
                        cells.append("n/a"); continue
                    r = r.iloc[0]
                    cells.append(f"{money(r['12m_med'])} / {pct(r['12m_P500'])} / {r.liq_pm:.1f}")
            P(f"| {tf} | {sc} | {p} | " + " | ".join(cells) + " |")

open("out/tables.md", "w").write("\n".join(out) + "\n")
print("\n".join(out))
