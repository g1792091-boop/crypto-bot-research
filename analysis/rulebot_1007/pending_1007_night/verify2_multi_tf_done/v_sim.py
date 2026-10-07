"""Verifier's own one-position account simulation on the 8-strategy x 3-year subset.
python3 -I -B v_sim.py <verify_dir> <sig_dir>
"""
import os, sys
sys.path[:0] = ['/root/.local/lib/python3.11/site-packages']
import numpy as np, pandas as pd

V, SIG = sys.argv[1:3]
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
FEE, SLIP, FB = 0.0005, 0.0002, 0.0001 * 15 / 480
d = pd.read_csv(os.path.join(V, "outc.csv"))
z = [np.load(os.path.join(SIG, f"sig_15m_{c}.npz")) for c in COINS]
ts15 = z[0]["ts"]; O = [q["o"] for q in z]
assert all(np.array_equal(ts15, q["ts"]) for q in z)
DAYS = (pd.Timestamp("2026-09-29") - pd.Timestamp("2023-10-01")).days
SCOPES = {"A": (0, 1), "ALL": (0, 1, 2, 3), "HI": (2, 3), "T15": (0,), "T30": (1,), "T1h": (2,), "T4h": (3,)}
rng = np.random.default_rng(7)


def account(t, rule, tie="coin_short"):
    if tie == "coin_short":
        t = t.sort_values(["e", "coin", "tf"], kind="mergesort")
    elif tie == "long_first":
        t = t.sort_values(["e", "ntf", "coin"], kind="mergesort")
    elif tie == "wide_first":
        t = t.assign(na=-t["atr_frac"]).sort_values(["e", "na"], kind="mergesort")
    else:  # random
        t = t.assign(rk=rng.random(len(t))).sort_values(["e", "rk"], kind="mergesort")
    cols = [t[c].to_numpy() for c in ("e", "tf", "coin", "side", "R", "gross", "x", "lev", "atr_frac")]
    E, TF, CO, SD, R, G, X, LV, AF = cols
    trades, blocked = [], []   # trades: (e, xe, R, gross, tf, switched, aloneR); blocked: (e, tf, R, tie, held_tf)
    hold = None
    nsw = 0
    for j in range(len(E)):
        e = E[j]
        if hold is not None and e > X[hold[0]]:
            i = hold[0]; trades.append((hold[1], X[i], R[i], G[i], TF[i], 0, R[i])); hold = None
        if hold is None:
            hold = (j, e); continue
        i = hold[0]
        istie = e == hold[1]
        same = CO[j] == CO[i] and SD[j] == SD[i]
        do = (not istie) and (not same) and ((rule == "SW") or (rule == "SWH" and TF[j] > TF[i]))
        if do:
            # close held at the open of bar e: taker + slippage, funding to e
            side = SD[i]; raw0 = O[CO[i]][hold[1]]; fill = raw0 * (1 + side * SLIP)
            risk = AF[i] * raw0 * 2 + raw0 * SLIP  # |fill - stop0| = 2 ATR + slip*raw
            raw = O[CO[i]][e]; px = raw * (1 - side * SLIP)
            lev = LV[i] if LV[i] > 0 else 20
            roe = max(lev * (side * (px / fill - 1) - FEE * (1 + px / fill) - FB * (e - hold[1])), -1.0)
            trades.append((hold[1], e - 1, roe * fill / (lev * risk), side * (raw - raw0) / (AF[i] * raw0 * 2 + raw0 * SLIP), TF[i], 1, R[i]))
            nsw += 1
            hold = (j, e); continue
        blocked.append((e, TF[j], R[j], istie, TF[i]))
    if hold is not None:
        i = hold[0]; trades.append((hold[1], X[i], R[i], G[i], TF[i], 0, R[i]))
    tr = pd.DataFrame(trades, columns=["e", "xe", "R", "gross", "tf", "sw", "aloneR"])
    bl = pd.DataFrame(blocked, columns=["e", "tf", "R", "tie", "held_tf"])
    return tr, bl, nsw


def mdd(R, risk):
    eq = np.concatenate([[1.0], np.cumprod(np.maximum(1 + risk * R, 1e-9))])
    return float(np.max(1 - eq / np.maximum.accumulate(eq)))


W = 91 * 96

def main():
  rows, trall, blall = [], [], []
  for nm, g0 in d.groupby("strat"):
      g0 = g0.assign(ntf=-g0.tf)
      for sc, tfs in SCOPES.items():
          gs = g0[g0.tf.isin(tfs)]
          g = gs[gs.lev > 0]
          if len(g) < 5:
              print('skip', nm, sc, len(g)); continue
          combos = [("FC", "coin_short")] if sc.startswith("T") else [("FC", "coin_short"), ("FC", "long_first"), ("FC", "random"), ("SW", "coin_short"), ("SWH", "long_first"), ("SWH", "coin_short")]
          for rule, tie in combos:
              tr, bl, nsw = account(g, rule, tie)
              key = f"{sc}|{rule}|{tie}"
              nb = (~bl.tie).sum() if len(bl) else 0
              nt = bl.tie.sum() if len(bl) else 0
              tr = tr.sort_values("xe")
              w = (tr.e.to_numpy() - tr.e.min()) // W
              mu = tr.R.mean()
              dd1 = [mdd(tr.R.to_numpy()[w == k] - mu, 0.01) for k in np.unique(w) if (w == k).sum() >= 5]
              dd1r = [mdd(tr.R.to_numpy()[w == k], 0.01) for k in np.unique(w) if (w == k).sum() >= 5]
              rows.append(dict(strat=nm, combo=key, sig=len(g), infeas=int((gs.lev == 0).sum()), trades=len(tr),
                               tpd=len(tr) / DAYS, spd=len(g) / DAYS, R=tr.R.mean(), gross=tr.gross.mean(),
                               cost=(tr.gross - tr.R).mean(), blocked=nb / len(g), ties=nt / len(g),
                               blR=bl.R[~bl.tie].mean() if nb else np.nan, takenR=tr.aloneR.mean(),
                               swpd=nsw / DAYS, hold_h=((tr.xe - tr.e + 1) * 0.25).mean(),
                               dd1_med=np.median(dd1), dd1_gt25=np.mean(np.array(dd1) > 0.25),
                               dd1raw_med=np.median(dd1r), dd1raw_gt25=np.mean(np.array(dd1r) > 0.25), nwin=len(dd1)))
              trall.append(tr.assign(strat=nm, combo=key)[["strat", "combo", "e", "xe", "R", "gross", "tf", "sw", "aloneR"]])
              blall.append(bl.assign(strat=nm, combo=key))
  res = pd.DataFrame(rows)
  res.to_csv(os.path.join(V, "v_sim_rows.csv"), index=False)
  pd.concat(trall).to_csv(os.path.join(V, "v_trades.csv.gz"), index=False)
  pd.concat(blall).to_csv(os.path.join(V, "v_blocked.csv.gz"), index=False)
  print("done", len(res))

if __name__ == "__main__":
  main()
