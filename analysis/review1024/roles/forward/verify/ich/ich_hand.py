"""Hand re-check of sample trades from the rule bot's OWN 1m bars (export live_bars.csv, Binance USDT-M via the bot's
feed, 2026-10-05 18:45 .. 10-24 14:11 UTC), without the research grid: 4h bars, the 4h Ichimoku / CMO state of the
last CLOSED 4h bar, the 1h ATR14 of the signal bar, and the a2 walk; printed in KST with the numbers.

    python3 ich_hand.py <live_bars.csv> <ich_rewalk.csv> [n_per_cell]"""
import sys
import numpy as np
import pandas as pd

T0 = 1577836800000
MIN = 60000
KST = 9 * 3600000
LB = pd.read_csv(sys.argv[1], usecols=["ts", "symbol", "open", "high", "low", "close"]).drop_duplicates(["ts", "symbol"])
C = pd.read_csv(sys.argv[2])
NPC = int(sys.argv[3]) if len(sys.argv) > 3 else 4
C = C[~C.twin & (C.tf == "1h") & C.cell.str.contains("N07")]
C["t"] = T0 + C.e * MIN
C = C[C.t >= pd.Timestamp("2026-10-19 12:00", tz="UTC").value // 10**6]
rng = np.random.default_rng(11)
pick = pd.concat([g.iloc[rng.choice(len(g), min(NPC, len(g)), replace=False)] for _, g in C.groupby("cell")])


def kst(ms):
    return str(pd.Timestamp(int(ms) + KST, unit="ms"))[:16]


def agg(df, k):
    """bars of k minutes aligned to UTC multiples of k from T0 (whole bars only)."""
    b = (df.ts.to_numpy(np.int64) - T0) // (k * MIN)
    g = df.assign(b=b).groupby("b")
    out = pd.DataFrame({"o": g.open.first(), "h": g.high.max(), "l": g.low.min(), "c": g.close.last(), "n": g.size()})
    return out[out.n == k]


rows = []
for _, r in pick.iterrows():
    m = LB[LB.symbol == r.coin].sort_values("ts").reset_index(drop=True)
    t = int(r.t)
    # 4h state on the last closed 4h bar (close <= t)
    b4 = agg(m[m.ts < t], 240)
    h, l, c = b4.h.to_numpy(), b4.l.to_numpy(), b4.c.to_numpy()
    last = b4.index[-1]
    ten = (h[-9:].max() + l[-9:].min()) / 2
    kij = (h[-26:].max() + l[-26:].min()) / 2
    # spans visible at the last bar = raw values 26 bars earlier
    hh, ll = h[:-26], l[:-26]
    sa = ((hh[-9:].max() + ll[-9:].min()) / 2 + (hh[-26:].max() + ll[-26:].min()) / 2) / 2
    sb = (hh[-52:].max() + ll[-52:].min()) / 2
    d = np.diff(c[-15:])
    cmo = 100 * (d[d > 0].sum() - (-d[d < 0]).sum()) / np.abs(d).sum()
    st = 1 if (ten > kij and sa > sb and cmo > 0) else (-1 if (ten < kij and sa < sb and cmo < 0) else 0)
    # 1h ATR14 (Wilder) of the signal bar from the bot's own bars
    b1 = agg(m[m.ts < t], 60)
    hc, lc, cc = b1.h.to_numpy(), b1.l.to_numpy(), b1.c.to_numpy()
    tr = np.maximum(hc[1:] - lc[1:], np.maximum(np.abs(hc[1:] - cc[:-1]), np.abs(lc[1:] - cc[:-1])))
    a = tr[0]
    for x in tr[1:]:
        a += (x - a) / 14
    # walk from the entry minute (open of the minute starting at t)
    w = m[m.ts >= t].reset_index(drop=True)
    p0 = w.open.iloc[0]
    s = int(r.side)
    atrd = 2 * a / p0
    cost = 0.00124
    best, lk, k = -1e9, None, 0
    while True:
        if k >= len(w):
            res = ("open", None, None)
            break
        level = max(-1 / 30 + cost, -atrd) if lk is None else max(-1 / 30 + cost, -atrd, lk / 30 + cost)
        hi, lo, op = w.high.iloc[k], w.low.iloc[k], w.open.iloc[k]
        up, dn = (hi / p0 - 1, lo / p0 - 1) if s > 0 else (1 - lo / p0, 1 - hi / p0)
        o_ = s * (op / p0 - 1)
        if dn <= level:
            fill = min(level, o_)
            rr = max(fill - cost, -1 / 30)
            res = ("lock" if lk is not None else "stop", rr, k)
            break
        ru = 30 * (up - cost)
        if ru > best:
            best = ru
            if best >= 0.12 - 1e-12:
                lk = 0.10 + 0.05 * np.floor((best - 0.12) / 0.05 + 1e-9)
        k += 1
    rows.append({"cell": r.cell.split(":")[0], "coin": r.coin, "side": "L" if s > 0 else "S", "signal_close_kst": kst(t),
                 "htf4_bar_close_kst": kst(T0 + (last + 1) * 240 * MIN), "tenkan": round(ten, 6), "kijun": round(kij, 6),
                 "spanA": round(sa, 6), "spanB": round(sb, 6), "cmo": round(cmo, 2), "state": st,
                 "atr1h": round(a, 6), "atr_grid": round(r.atr_mine, 6), "entry": p0, "stop_px": round(p0 * (1 - s * atrd), 6),
                 "exit": res[0], "roe_hand": None if res[1] is None else round(30 * res[1], 4),
                 "roe_grid": round(max(30 * r.grid_r, -1), 4), "min_hand": res[2], "min_grid": int(r.grid_k)})
R = pd.DataFrame(rows)
pd.set_option("display.width", 250)
print(R.to_string(index=False))
R.to_csv("ich_hand.csv", index=False)
print("state +1/-1 agrees with side:", int((R.state * R.side.map({"L": 1, "S": -1}) == 1).sum()), "of", len(R),
      "| roe equal (1e-4):", int((np.abs(R.roe_hand - R.roe_grid) < 1e-4).sum()))
