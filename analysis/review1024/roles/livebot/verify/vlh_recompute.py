"""Verifier (lens: look-ahead / time alignment / data errors) for the livebot claim 'costs and market direction matter
more than roles'. Recomputes from the trades files (no lb_core import): gross / cost / payback per trade on
2024-01-01 .. 2026-10-05 15:00 UTC, the October luck table, the coin changes over 10-06 .. 10-24 KST from the
rule bot's own 1m bars (live_bars.csv, independent of the research grid), and the 30-day goal bootstrap with an
independent implementation.
Run (from this folder, no -I): python3 vlh_recompute.py <trades_dir> <live_bars.csv>"""
import sys
import numpy as np
import pandas as pd

TD, LBF = sys.argv[1], sys.argv[2]
MIN, DAY = 60_000, 86_400_000
COST = 2 * (0.00042 + 0.0002)
PAYBACK = 2 * 0.9 * 0.00042
def ms(s): return int(pd.Timestamp(s, tz="UTC").value // 10**6)
CL = (ms("2024-01-01"), ms("2026-10-05 15:00"))
FWD = (ms("2026-10-05 15:00"), ms("2026-10-24 15:00"))
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"]


def load(v):
    T = pd.read_csv(f"{TD}/trades_{v}.csv.gz")
    T["lev"] = np.where(T.coin == 0, 40.0, 30.0)
    return T


print("== gross / cost / payback per trade (ROE points), conf+late and fwd")
for v in ("B0", "B3", "B6", "B9", "W3"):
    T = load(v)
    for nm, (a, b) in (("conf+late", CL), ("fwd", FWD)):
        P = T[(T.t >= a) & (T.t < b)]
        net = P.tb_roe.mean()
        cost = (P.lev * COST).mean()
        pb = (P.lev * PAYBACK).mean()
        # identity check: tb_roe == lev * tb_r
        idd = np.abs(P.tb_roe - P.lev * P.tb_r).max()
        print(f"{v} {nm:9s} n={len(P):5d} net={100*net:+.3f} gross={100*(net+cost):+.3f} cost={100*cost:.3f} "
              f"payback={100*pb:.3f} net+pb={100*(net+pb):+.3f} win={100*(P.tb_roe>0).mean():.1f} "
              f"btc_share={(P.coin==0).mean():.3f} max|roe-lev*r|={idd:.2e} open_at_end={(P.tb_why==3).sum()}")

print("\n== October luck table (fwd), as in fwd_trend_luck.csv")
for v in ("B0", "B3", "B6", "W3"):
    P = load(v)
    P = P[(P.t >= FWD[0]) & (P.t < FWD[1])]
    short = np.where(P.side < 0, P.tb_roe, P.tb_opp_roe)
    long_ = np.where(P.side > 0, P.tb_roe, P.tb_opp_roe)
    print(f"{v} n={len(P)} short_share={(P.side<0).mean():.3f} own={100*P.tb_roe.mean():+.2f} opp={100*P.tb_opp_roe.mean():+.2f} "
          f"always_short={100*short.mean():+.2f} always_long={100*long_.mean():+.2f} "
          f"own_long={100*P.tb_roe[P.side>0].mean():+.2f} ({(P.side>0).sum()}) own_short={100*P.tb_roe[P.side<0].mean():+.2f}"
          f" | trades with forced exit (why 2) own={((P.tb_why==2)).sum()} opp={((P.tb_opp_why==2)).sum()}")

print("\n== coin change 10-06 00:00 KST .. last bar, from live_bars.csv (independent of the grid)")
LB = pd.read_csv(LBF, usecols=["ts", "symbol", "open", "close"])
for c in COINS:
    X = LB[LB.symbol == c].sort_values("ts")
    a = X[X.ts >= FWD[0]].iloc[0]
    z = X[X.ts < FWD[1]].iloc[-1]
    print(c, "first minute", pd.to_datetime(a.ts, unit="ms"), "last", pd.to_datetime(z.ts, unit="ms"),
          "change %.1f%%" % (100 * (z.close / a.open - 1)))
print("live_bars first minute", pd.to_datetime(LB.ts.min(), unit="ms"), "(FWD starts", pd.to_datetime(FWD[0], unit="ms"), ")")


def boot(T, a, b, margin=0.4, horizon=30, n=20000, seed=11, payback=True):
    T = T.sort_values("t")
    roe = T.tb_roe.to_numpy() + (T.lev.to_numpy() * PAYBACK if payback else 0)
    roe = np.maximum(roe, -1.0)
    d = T.t.to_numpy() // DAY
    lo, hi = a // DAY, (b - 1) // DAY
    days = [roe[d == x] for x in range(lo, hi + 1)]
    rng = np.random.default_rng(seed)
    hit = l50 = l90 = 0
    fin = np.empty(n)
    for i in range(n):
        eq = 1.0
        reached = lost50 = lost90 = False
        for di in rng.integers(0, len(days), horizon):
            for x in days[di]:
                eq *= 1 + margin * x
                if not (reached or lost90):
                    if eq >= 6:
                        reached = True
                    else:
                        if eq <= 0.5:
                            lost50 = True
                        if eq <= 0.1:
                            lost90 = True
        hit += reached
        l50 += lost50
        l90 += lost90
        fin[i] = eq
    return hit / n, l50 / n, l90 / n, np.median(fin), len(days)


print("\n== goal bootstrap (independent implementation), margin 0.4")
for v in ("B0", "B3", "B6", "W3"):
    T = load(v)
    for nm, (a, b) in (("2024-26", CL), ("fwd", FWD)):
        P = T[(T.t >= a) & (T.t < b)]
        for pb in (False, True):
            r = boot(P, a, b, payback=pb, n=8000 if nm != "fwd" else 20000)
            print(f"{v} {nm} payback={pb}: P(x6)={100*r[0]:.1f}% P(-50 first)={100*r[1]:.1f}% P(-90 first)={100*r[2]:.1f}% median x{r[3]:.2f} days={r[4]}")
