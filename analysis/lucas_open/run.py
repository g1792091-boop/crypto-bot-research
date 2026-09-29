"""Lucas Lalk's two open-source Astral strategies (Explore #1199 RSI mean reversion, #1233 EMA 5/50 trend),
re-implemented and run on 5 years of 15m data (2021-08-01 .. 2026-09-29, 7 coins, Astral spot aggregate).
Faithful rules (long only, as published) plus a mirrored short side; zero cost (as published) and realistic cost
(taker 0.05%/side + slippage 0.02%/market fill + funding 0.01%/8h). One position per coin at a time.
#1199: RSI(14) < 30 at bar close -> buy at that close; TP +1%, SL -4% (same-bar touch -> SL). Astral's version adds
       to the position on every oversold bar (accumulate=True); here one position at a time.
#1233: EMA5 crosses above EMA50 and close > EMA200 -> buy next open; exit next open after EMA5 crosses below EMA50."""
import os, sys, numpy as np, pandas as pd
D = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "sweep", "data", "full")
COINS = ["btcusd", "ethusd", "solusd", "xrpusd", "dogeusd", "ltcusd", "bchusd"]
FEE, SLIP, F8 = 0.0005, 0.0002, 0.0001
def rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up = np.clip(d, 0, None); dn = np.clip(-d, 0, None)
    au = pd.Series(up).ewm(alpha=1/n, adjust=False).mean(); ad = pd.Series(dn).ewm(alpha=1/n, adjust=False).mean()
    return (100 - 100 / (1 + au / ad)).to_numpy()
ema = lambda c, n: pd.Series(c).ewm(span=n, adjust=False).mean().to_numpy()

def run_rsi(df, side):
    o, h, l, c = (df[k].to_numpy() for k in ["open", "high", "low", "close"]); r = rsi(c); t = df.ts.tolist()
    out = []; i = 200; n = len(c)
    while i < n - 1:
        if (r[i] < 30) if side > 0 else (r[i] > 70):
            e = c[i]; tp = e * (1 + 0.01 * side); sl = e * (1 - 0.04 * side)
            for j in range(i + 1, n):
                hit_sl = l[j] <= sl if side > 0 else h[j] >= sl
                hit_tp = h[j] >= tp if side > 0 else l[j] <= tp
                if hit_sl: x = min(o[j], sl) if side > 0 else max(o[j], sl); tpx = False; break
                if hit_tp: x = max(o[j], tp) if side > 0 else min(o[j], tp); tpx = True; break
            else: break
            g = side * (x / e - 1); cost = 2 * FEE + SLIP * (1 if tpx else 2) + F8 * (j - i) * 15 / 480
            out.append((t[i], side, g, g - cost)); i = j
        i += 1
    return out

def run_ema(df, side):
    o, c = df.open.to_numpy(), df.close.to_numpy(); t = df.ts.tolist()
    e5, e50, e200 = ema(c, 5), ema(c, 50), ema(c, 200)
    up = (e5 > e50) & (np.roll(e5, 1) <= np.roll(e50, 1)); dnx = (e5 < e50) & (np.roll(e5, 1) >= np.roll(e50, 1))
    ent = up & (c > e200) if side > 0 else dnx & (c < e200); ex = dnx if side > 0 else up
    out = []; i = 200; n = len(c)
    while i < n - 2:
        if ent[i]:
            j = i + 1
            while j < n - 1 and not ex[j]: j += 1
            e, x = o[i + 1], o[min(j + 1, n - 1)]
            g = side * (x / e - 1); cost = 2 * (FEE + SLIP) + F8 * (j - i) * 15 / 480
            out.append((t[i], side, g, g - cost)); i = j
        i += 1
    return out

rows, trades = [], []
for coin in COINS:
    df = pd.read_csv(os.path.join(D, f"{coin}-15m.csv")); df["ts"] = pd.to_datetime(df.ts, utc=True)
    df = df[df.ts >= "2021-07-01"].reset_index(drop=True)
    for strat, fn in [("1199_RSI_MR", run_rsi), ("1233_EMA_5_50", run_ema)]:
        for side in (1, -1):
            for ts, s, g, nt in fn(df, side):
                if pd.Timestamp(ts) >= pd.Timestamp("2021-08-01", tz="UTC"):
                    trades.append(dict(strategy=strat, coin=coin, side=s, ts=ts, gross=g, net=nt))
T = pd.DataFrame(trades); T.to_csv(os.path.join(os.path.dirname(__file__), "trades.csv.gz"), index=False)
def st(g, col):
    x = g[col].to_numpy(); w = x > 0; c = np.cumsum(np.sort(x) * 0 + x); dd = (np.maximum.accumulate(np.r_[0, c])[1:] - c).max()
    return dict(trades=len(x), win_rate=w.mean(), avg_win=x[w].mean() * 100, avg_loss=x[~w].mean() * 100,
                payoff=abs(x[w].mean() / x[~w].mean()), pf=x[w].sum() / -x[~w].sum(), exp=x.mean() * 100,
                sum=x.sum() * 100, mdd=dd * 100, years_pos=int((g.groupby(g.ts.dt.year)[col].sum() > 0).sum()))
for (strat, scope), sel in [((s, sc), None) for s in T.strategy.unique() for sc in ["BTC long (as published)", "7 coins long", "7 coins short", "7 coins long+short"]]:
    g = T[T.strategy == strat]
    if scope.startswith("BTC"): g = g[(g.coin == "btcusd") & (g.side > 0)]
    elif scope == "7 coins long": g = g[g.side > 0]
    elif scope == "7 coins short": g = g[g.side < 0]
    g = g.sort_values("ts")
    for col, lab in [("gross", "no cost"), ("net", "real cost")]:
        rows.append(dict(strategy=strat, scope=scope, cost=lab, **st(g, col)))
R = pd.DataFrame(rows); R.to_csv(os.path.join(os.path.dirname(__file__), "summary.csv"), index=False)
pd.set_option("display.width", 250); print(R.round(3).to_string(index=False))
# the published 7-week windows, no cost, BTC long (sanity check vs Astral)
for strat, a, b in [("1199_RSI_MR", "2026-07-27", "2026-09-18"), ("1233_EMA_5_50", "2026-08-02", "2026-09-24")]:
    g = T[(T.strategy == strat) & (T.coin == "btcusd") & (T.side > 0) & (T.ts >= a) & (T.ts < b)]
    print(strat, "published window BTC long no-cost:", len(g), "trades, win", round((g.gross > 0).mean(), 3), "sum %", round(g.gross.sum() * 100, 2))
# yearly BTC long as published, real cost
for strat in T.strategy.unique():
    g = T[(T.strategy == strat) & (T.coin == "btcusd") & (T.side > 0)]
    print(strat, "BTC long by year (real cost, sum %):", g.groupby(g.ts.dt.year).net.sum().mul(100).round(1).to_dict())
