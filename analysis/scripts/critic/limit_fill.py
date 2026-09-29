"""Option B premise check: does a maker-limit entry keep the V4.5 64-bar drift?

In-sample on the delivered 5m data (the same data the drift was found on), so
every number here is an OPTIMISTIC upper bound for option B.

Market baseline: entry o[i+1] (+2bp slip, taker 5bp), exit o[i+1+H] (taker 5bp, 2bp slip).
Limit variant: limit at c[i]*(1 - side*k) valid on bars i+1..i+W; fill if the bar
trades THROUGH the limit (long: low < L); fill px = min(open, L) (long).
Exit at the SAME calendar bar o[i+1+H], either as maker (2bp, no slip; optimistic:
assumes the exit limit also fills at that open) or taker (5bp+2bp slip).
Optional ATR stop (taker+slip), checked from the bar AFTER the fill bar (optimistic).
Null: identical procedure on random bars with the same long/short mix.
"""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bt"))
import strategies as S
import fg_indicators as fg
from run import load_csv

DATA = os.path.join(HERE, "..", "data")
H = 64
TAKER, MAKER, SLIP = 0.0005, 0.0002, 0.0002


def sim(o, h, l, c, atr, idx, side, k, W, stop_atr=None, exit_maker=True):
    n = len(o)
    out = []
    for i, s in zip(idx, side):
        ex = i + 1 + H
        if ex >= n:
            continue
        # market baseline
        e_m = o[i + 1] * (1 + s * SLIP)
        x_m = o[ex] * (1 - s * SLIP)
        g_m = s * (x_m / e_m - 1)
        raw_m = s * (o[ex] / o[i + 1] - 1)
        if W == 0:
            out.append((raw_m, g_m, g_m - 2 * TAKER, 1, np.nan, np.nan)); continue
        L = c[i] * (1 - s * k)
        fill_j, fpx = None, None
        for j in range(i + 1, min(i + 1 + W, ex)):
            if (s > 0 and l[j] < L) or (s < 0 and h[j] > L):
                fill_j = j
                fpx = min(o[j], L) if s > 0 else max(o[j], L)
                break
        if fill_j is None:
            out.append((raw_m, np.nan, np.nan, 0, np.nan, np.nan)); continue
        exit_px, exit_is_stop = o[ex], False
        if stop_atr is not None:
            sl = fpx * (1 - s * stop_atr * atr[i] / fpx)
            for j in range(fill_j + 1, ex):
                if (s > 0 and l[j] <= sl) or (s < 0 and h[j] >= sl):
                    exit_px = (min(o[j], sl) if s > 0 else max(o[j], sl)) * (1 - s * SLIP)
                    exit_is_stop = True
                    break
        if exit_is_stop or not exit_maker:
            xp = exit_px if exit_is_stop else exit_px * (1 - s * SLIP)
            fee = MAKER + TAKER
        else:
            xp = exit_px
            fee = 2 * MAKER
        g = s * (xp / fpx - 1)
        out.append((raw_m, g, g - fee, 1, fill_j - i, float(exit_is_stop)))
    return pd.DataFrame(out, columns=["raw_mkt", "gross", "net", "filled", "fill_lag", "stopped"])


def main():
    rng = np.random.default_rng(1)
    rows = []
    frames = {}
    for sym in ("BTCUSD", "ETHUSD", "SOLUSD"):
        d5 = load_csv(os.path.join(DATA, f"{sym.lower()}-5m-ohlcv.csv"), 5)
        d15 = load_csv(os.path.join(DATA, f"{sym.lower()}-15m-ohlcv.csv"), 15)
        L_, S_ = S.v45_exact_amb(d5, d15)
        L_ = np.asarray(L_, bool); S_ = np.asarray(S_, bool) & ~L_
        o, h, l, c = (d5[x].to_numpy(float) for x in ("open", "high", "low", "close"))
        atr = fg.atr(d5, 14).to_numpy(float)
        idx = np.where((L_ | S_)[1000:])[0] + 1000
        side = np.where(L_[idx], 1, -1)
        # null: random bars, same side mix, same count x5
        nidx = np.sort(rng.choice(np.arange(1000, len(o) - H - 2), size=5 * len(idx), replace=False))
        nside = rng.choice(side, size=len(nidx))
        frames[sym] = (o, h, l, c, atr, idx, side, nidx, nside)
    configs = [("market", 0, 0, None, True)]
    for k in (0.0, 0.0002, 0.0005, 0.0010):
        for W in (1, 3, 6):
            configs.append((f"lim_k{k*1e4:.0f}bp_W{W}", k, W, None, True))
    configs.append(("lim_k0bp_W3_takerexit", 0.0, 3, None, False))
    configs.append(("lim_k0bp_W3_sl2atr", 0.0, 3, 2.0, True))
    configs.append(("market_sl2atr_ref", None, None, 2.0, None))
    for name, k, W, st, xm in configs:
        for kind in ("V45_AMB", "NULL"):
            parts = []
            for sym, (o, h, l, c, atr, idx, side, nidx, nside) in frames.items():
                ii, ss = (idx, side) if kind == "V45_AMB" else (nidx, nside)
                if name == "market_sl2atr_ref":
                    # market entry at o[i+1] with 2ATR stop, time exit at 64 -> taker both
                    r = []
                    n = len(o)
                    for i, s in zip(ii, ss):
                        ex = i + 1 + H
                        if ex >= n: continue
                        e = o[i + 1] * (1 + s * SLIP); sl = e * (1 - s * 2.0 * atr[i] / e)
                        xp = o[ex] * (1 - s * SLIP); stp = 0.0
                        for j in range(i + 1, ex):
                            if (s > 0 and l[j] <= sl) or (s < 0 and h[j] >= sl):
                                xp = (min(o[j], sl) if s > 0 else max(o[j], sl)) * (1 - s * SLIP); stp = 1.0; break
                        g = s * (xp / e - 1)
                        r.append((s * (o[ex] / o[i + 1] - 1), g, g - 2 * TAKER, 1, 0, stp))
                    df = pd.DataFrame(r, columns=["raw_mkt", "gross", "net", "filled", "fill_lag", "stopped"])
                else:
                    df = sim(o, h, l, c, atr, ii, ss, k, W, st, xm)
                df["sym"] = sym
                parts.append(df)
            d = pd.concat(parts)
            f = d[d.filled == 1]
            uf = d[d.filled == 0]
            rows.append(dict(config=name, set=kind, signals=len(d), fill_rate=len(f) / len(d),
                             raw_mkt_all=d.raw_mkt.mean() * 100,
                             raw_mkt_filled=f.raw_mkt.mean() * 100, raw_mkt_unfilled=(uf.raw_mkt.mean() * 100 if len(uf) else np.nan),
                             gross_filled=f.gross.mean() * 100, net_per_trade=f.net.mean() * 100,
                             net_per_signal=f.net.sum() / len(d) * 100,
                             pf=(f.net[f.net > 0].sum() / -f.net[f.net <= 0].sum()),
                             stopped=f.stopped.mean() if "stopped" in f else np.nan,
                             sym_net=";".join(f"{s}:{g.net.mean()*100:+.3f}" for s, g in f.groupby("sym"))))
    res = pd.DataFrame(rows)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    print(res.round(4).to_string(index=False))
    res.to_csv(os.path.join(HERE, "limit_fill.csv"), index=False)


if __name__ == "__main__":
    main()
