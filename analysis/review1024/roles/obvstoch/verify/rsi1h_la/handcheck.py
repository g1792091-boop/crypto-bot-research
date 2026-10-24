"""Hand check of sample trades of OBV20@4h>RSI@1h|a2 straight from the raw 1m rows (verifier, look-ahead lens).

For each trade: the raw minutes of the 1h signal bar (and the bar before), the 4h bar used for the trend (its close must
be <= the signal time) with OBV / SMA20 from my own 4h bars, the entry minute's raw open, the 2 x ATR stop price, the
minute-by-minute path to the exit (first lock, exit minute and fill) and the last-price vs mark-price extremes inside
the trade (a bad last-price print would show as a wick missing from the mark price). Also lists the DOGE gap minutes.
    python3 handcheck.py <live_bars.csv>
"""
import sys
import json
import numpy as np
import pandas as pd
import indep as IN

TRADES = [("BCHUSDT", "2020-06-10 07:00", -1), ("SOLUSDT", "2021-09-18 15:00", -1), ("BCHUSDT", "2026-03-22 02:00", 1),
          ("LTCUSDT", "2025-08-14 15:00", 1), ("LTCUSDT", "2022-03-14 04:00", 1), ("SOLUSDT", "2026-10-07 06:00", 1)]
MIN = 60_000


def main(live):
    lb = IN.load_live(live)
    end = int(min(lb[lb.symbol == c].ts.max() for c in IN.COINS)) + MIN
    S = pd.read_csv("study_rows.csv")
    S["t_ms"] = IN.T0 + S.e * MIN
    res = []
    cache = {}
    for coin, tstr, side in TRADES:
        if coin not in cache:
            m, nmiss, first = IN.raw_minutes(coin, lb, end)
            z = np.load(f"{IN.FG}/{coin}.npz")
            mk = pd.DataFrame({"ts": z["ts"], "mh": z["mh"], "ml": z["ml"]}).set_index("ts")
            b4 = IN.resample(m, "4h", 240, first)
            c4 = b4.c.to_numpy(float)
            ob = np.cumsum(np.sign(np.nan_to_num(np.r_[np.nan, np.diff(c4)])) * b4.v.to_numpy(float))
            b4["obv"], b4["sma20"] = ob, pd.Series(ob).rolling(20).mean().to_numpy()
            b1 = IN.resample(m, "1h", 60, first)
            b1["rsi"] = IN.rsi(b1.c.to_numpy(float))
            b1["atr"] = IN.atr(b1.h.to_numpy(float), b1.l.to_numpy(float), b1.c.to_numpy(float))
            cache[coin] = (m, mk, b4, b1)
        m, mk, b4, b1 = cache[coin]
        tc = IN.ms(tstr)                                            # signal bar close = entry minute
        i1 = int(np.flatnonzero(b1.close_ms.to_numpy() == tc)[0])
        bar = m.loc[tc - 60 * MIN: tc - MIN]                        # the 60 raw minutes of the signal bar
        prevbar = m.loc[tc - 120 * MIN: tc - 61 * MIN]
        j4 = int(np.flatnonzero(b4.close_ms.to_numpy() <= tc)[-1])
        r4, r4n = b4.iloc[j4], b4.iloc[j4 + 1] if j4 + 1 < len(b4) else None
        p0 = float(m.loc[tc, "o"])
        atr = float(b1.atr.iat[i1])
        stop = p0 * (1 - side * 2 * atr / p0)
        # walk minute by minute (same rule as indep.walk, written out to print the path)
        best, lk, k = -1e9, None, 0
        ts = m.index.to_numpy()
        o, h, l = m.o.to_numpy(), m.h.to_numpy(), m.l.to_numpy()
        cumf = np.cumsum(m.fund.to_numpy())
        e = int(np.flatnonzero(ts == tc)[0])
        f0 = cumf[e - 1]
        first_lock_t = None
        while True:
            i = e + k
            Fp = side * (cumf[i - 1] - f0)
            level = max(-2 * atr / p0, -1 / 30 + IN.COST + Fp)
            if lk is not None:
                level = max(level, lk / 30 + IN.COST + Fp)
            up = h[i] / p0 - 1 if side > 0 else 1 - l[i] / p0
            dn = l[i] / p0 - 1 if side > 0 else 1 - h[i] / p0
            op = side * (o[i] / p0 - 1)
            F = side * (cumf[i] - f0)
            if dn <= level:
                fill = min(level, op)
                roe = max(fill - IN.COST - F, -1 / 30) * 30
                break
            r_up = 30 * (up - IN.COST - F)
            if r_up > best:
                best = r_up
                lk2 = IN.lock_for(best)
                if lk2 is not None:
                    if lk is None:
                        first_lock_t = str(pd.Timestamp(ts[i], unit="ms"))
                    lk = lk2
            k += 1
        xi = e + k
        seg = m.iloc[e: xi + 1]
        mseg = mk.loc[ts[e]: ts[xi]]
        st_row = S[(S.coin == coin) & (S.t_ms == tc)]
        rec = {"trade": f"{coin} {tstr} UTC side {side:+d}",
               "signal_bar_raw": {"open": float(bar.o.iloc[0]), "high": float(bar.h.max()), "low": float(bar.l.min()),
                                  "close": float(bar.c.iloc[-1]), "minutes": len(bar),
                                  "last_minute": str(pd.Timestamp(bar.index[-1], unit="ms"))},
               "prev_bar_close_raw": float(prevbar.c.iloc[-1]),
               "rsi_prev_now": [round(float(b1.rsi.iat[i1 - 1]), 3), round(float(b1.rsi.iat[i1]), 3)],
               "trend_4h_bar_used": {"open": str(pd.Timestamp(r4.open_ms, unit="ms")), "close": str(pd.Timestamp(r4.close_ms, unit="ms")),
                                     "obv_minus_sma20": float(r4.obv - r4.sma20)},
               "next_4h_bar_not_used": None if r4n is None else {"close": str(pd.Timestamp(r4n.close_ms, unit="ms")),
                                                                 "obv_minus_sma20": float(r4n.obv - r4n.sma20)},
               "entry_minute": str(pd.Timestamp(tc, unit="ms")), "entry_open_raw": p0,
               "atr14_1h": atr, "stop_price": stop, "first_lock_at": first_lock_t, "final_lock_net_roe": lk,
               "best_net_roe": best, "exit_minute": str(pd.Timestamp(ts[xi], unit="ms")), "minutes_held": k,
               "exit_minute_raw": {"o": float(o[xi]), "h": float(h[xi]), "l": float(l[xi])},
               "hand_roe": roe, "study_roe": float(st_row.roe.iloc[0]) if len(st_row) else None,
               "last_hi_lo_in_trade": [float(seg.h.max()), float(seg.l.min())],
               "mark_hi_lo_in_trade": [float(mseg.mh.max()), float(mseg.ml.min())] if len(mseg) else None}
        res.append(rec)
        print(json.dumps(rec, indent=1, default=str), flush=True)
    # DOGE gap minutes
    m, nmiss, first = IN.raw_minutes("DOGEUSDT", lb, end)
    z = np.load(f"{IN.FG}/DOGEUSDT.npz")
    ts = z["ts"]
    gaps = np.flatnonzero(np.diff(ts) > MIN)
    G = pd.DataFrame({"from": pd.to_datetime(ts[gaps], unit="ms"), "to": pd.to_datetime(ts[gaps + 1], unit="ms"),
                      "missing_min": (ts[gaps + 1] - ts[gaps]) // MIN - 1})
    G = G.sort_values("missing_min", ascending=False)
    print("DOGE gaps (largest):\n", G.head(8).to_string())
    json.dump({"trades": res, "doge_gaps_top": G.head(8).astype(str).to_dict("records")},
              open("handcheck.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main(sys.argv[1])
