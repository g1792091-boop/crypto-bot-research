"""Hand check of single L1 trades (30m Stoch RSI KD entry, 1h OBV30 trend, w35) straight from the raw 1m rows
(live_bars.csv of the rule bot for the last 19 days, the fg1m npz for older trades), printed step by step, compared
with the study's own row (oscore.rows on the study's cache).

    python3 handcheck.py
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import oscore as O  # noqa: E402

O.CACHE = "/dev/shm/claude_verify_la"
S = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad"
LB = f"{S}/review1024_roles/verify_la_x/live_bars.csv"
T0, MIN = O.T0, O.MIN
LEV, COST = 35.0, 2 * (0.00042 + 0.0002)

lb = pd.read_csv(LB, usecols=["ts", "symbol", "open", "high", "low", "close", "volume"])


import indep as IN  # noqa: E402  (only its zip reader of the October daily files)


def raw_minutes(coin, a, b):
    """Raw 1m rows [a, b) ms: the rule bot's live_bars where it has them, else the October daily zips, else fg1m."""
    d = lb[(lb.symbol == coin) & (lb.ts >= a) & (lb.ts < b)]
    d = d.rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "volume": "v"})[["ts", "o", "h", "l", "c", "v"]]
    src = {"live_bars"} if len(d) else set()
    parts = [d]
    if a < O.ms("2026-10-23"):
        dd = IN.read_daily(coin)
        dd = dd[(dd.ts >= a) & (dd.ts < b) & ~dd.ts.isin(d.ts)]
        if len(dd):
            parts.append(dd); src.add("daily_zip")
    if a < O.ms("2026-10-01"):
        z = np.load(f"{S}/fg1m/1m/{coin}.npz")
        ts = z["ts"]
        m = (ts >= a) & (ts < b)
        f = pd.DataFrame({"ts": ts[m], **{k: z[k][m] for k in ("o", "h", "l", "c", "v")}})
        f = f[~f.ts.isin(pd.concat(parts).ts)]
        if len(f):
            parts.append(f); src.add("fg1m")
    X = pd.concat(parts).sort_values("ts").reset_index(drop=True)
    return X, "+".join(sorted(src))


def obv_state_by_hand(coin, t):
    """OBV vs its 30-bar SMA on the last 1h bar with close <= t, from 1h bars built here from raw minutes (only the
    last 31 bars are needed: a constant offset of OBV cancels)."""
    h_end = t // 3_600_000 * 3_600_000                     # the last 1h bar closing at or before t closes here
    d, src = raw_minutes(coin, h_end - 40 * 3_600_000, h_end)
    d["hb"] = d.ts // 3_600_000
    H = d.groupby("hb").agg(c=("c", "last"), v=("v", "sum"), cnt=("c", "size"))
    H = H.iloc[-31:]
    ob = np.cumsum(np.r_[0.0, np.sign(np.diff(H.c.to_numpy())) * H.v.to_numpy()[1:]])
    st = np.sign(ob[-1] - ob[-30:].mean())
    last_close = pd.Timestamp((H.index[-1] + 1) * 3_600_000, unit="ms")
    return int(st), str(last_close), int(H.cnt.iloc[-1]), src


def walk_by_hand(coin, e, side):
    t = T0 + e * MIN
    d, src = raw_minutes(coin, t, t + 20 * 86_400_000)
    assert int(d.ts.iloc[0]) == t, "entry minute missing"
    p0 = float(d.o.iloc[0])
    stop_px = p0 * (1 + side * (-0.50 / LEV + COST))
    best, lock, log = -1e9, None, []
    for row in d.itertuples():
        lvl = -0.50 / LEV + COST
        why = "stop"
        if lock is not None and lock / LEV + COST > lvl:
            lvl, why = lock / LEV + COST, f"lock {lock:.2f}"
        adv = (row.l / p0 - 1) if side > 0 else (1 - row.h / p0)
        fav = (row.h / p0 - 1) if side > 0 else (1 - row.l / p0)
        if adv <= lvl:
            op = side * (row.o / p0 - 1)
            fill = min(lvl, op)
            r = fill - COST
            return {"src": src, "entry_time": str(pd.Timestamp(t, unit="ms")), "p0": p0, "stop_px": round(stop_px, 6),
                    "exit_time": str(pd.Timestamp(row.ts, unit="ms")), "exit_px": round(p0 * (1 + side * fill), 6),
                    "minutes": int((row.ts - t) // MIN), "why": why, "roe": round(max(LEV * r, -1.0), 5), "locks": log}
        rb = LEV * (fav - COST)
        if rb > best:
            best = rb
            if best >= 0.12 - 1e-12:
                nl = 0.10 + 0.05 * np.floor((best - 0.12) / 0.05 + 1e-9)
                if lock is None or nl > lock:
                    log.append((str(pd.Timestamp(row.ts, unit="ms")), round(nl, 2)))
                lock = nl
    return {"open": True}


D = {c: O.load(c) for c in O.COINS}
out = []
for per, pick in (("FWD", (0, 1, 2, -1, "stop", "lock")), ((O.ms("2022-06-01"), O.ms("2022-07-01")), (0, 5, "stop")),
                  ((O.ms("2025-03-01"), O.ms("2025-04-01")), (0, "stop"))):
    R = O.rows(D, "30m", "1h", "OBV30", "SRSI_KD", "w35", per)
    order = np.argsort(R["e"], kind="stable")
    idx = []
    for p in pick:
        if p == "stop":
            idx.append(order[np.flatnonzero(R["w"][order] == 0)[0]])
        elif p == "lock":
            idx.append(order[np.flatnonzero(R["w"][order] == 1)[3]])
        else:
            idx.append(order[p])
    for i in idx:
        coin = O.COINS[int(R["coin"][i])]
        e, side = int(R["e"][i]), int(R["side"][i])
        t = T0 + e * MIN
        Z = D[coin]
        nb = int(np.flatnonzero(Z["30m_e"] == e)[0])
        st_hand, last_close, cnt, src_h = obv_state_by_hand(coin, t)
        w = walk_by_hand(coin, e, side)
        rec = {"coin": coin, "signal_close_utc": str(pd.Timestamp(t, unit="ms")), "side": side,
               "study_sig": int(Z["30m_sig_SRSI_KD"][nb]), "study_trend_1h_OBV30": int(Z["30m_st_1h_OBV30"][nb]),
               "hand_trend_1h_OBV30": st_hand, "htf_bar_used_closes_utc": last_close, "htf_minutes_in_bar": cnt,
               "study_roe": round(float(R["roe"][i]), 5), "study_why": int(R["w"][i])}
        rec.update({f"hand_{k}": v for k, v in w.items()})
        out.append(rec)
        print(rec)
T = pd.DataFrame(out)
T.to_csv(os.path.join(HERE, "handcheck.csv"), index=False)
print("roe equal:", np.allclose(T.study_roe, T.hand_roe, atol=1e-4), "trend equal:",
      bool((T.study_trend_1h_OBV30 == T.hand_trend_1h_OBV30).all()),
      "htf bar closes <= signal:", bool((pd.to_datetime(T.htf_bar_used_closes_utc) <= pd.to_datetime(T.signal_close_utc)).all()))
