"""Hand re-check of sample trades from the RAW 1m rows (fg1m npz with its own open timestamps; looked up by timestamp,
not by the grid's index arithmetic), for the claim's rows (15m / 30m entry-role signals, 1h judge V4OF4):

  * the signal bar = the minutes with open in [t - tf, t): all before the entry minute t; its close = the close of the
    minute t - 1 min; must equal the study's bar close
  * the 1h bar the filter reads: open + 60 min <= t (closed), and the next 1h bar's close > t; its four judges / V4OF4
  * the entry = the open of the minute that opens at t (first minute after the signal bar)
  * the w35 exit walked minute by minute from t on, written here from the rule text (35x, net ROE -50 % stop, ladder
    +12 -> +10 then +5 steps, lock armed from the next minute, stop checked before the new high of the same minute,
    fill at the level or at the open if it gapped through, cost 0.124 %, funding of the minutes held); must equal the
    grid's w35_r / w35_k

    python3 la_trades.py  -> la_trades.csv"""
import os
import sys

DATA = "/home/user/crypto-bot-research/analysis/review1024/roles/data"
sys.path.insert(0, DATA)
import rolesdata as RD          # noqa: E402
from common import *            # noqa: E402,F401

HERE = os.path.dirname(os.path.abspath(__file__))
FG = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/fg1m"
LEV, STOP = 35.0, -0.50


def lock_for(best):
    ft = 0.10 + 0.02
    if best < ft - 1e-12:
        return None
    return 0.10 + 0.05 * np.floor((best - ft) / 0.05 + 1e-9)


def walk(ts, o, h, l, c, f, t, s):
    p = int(np.searchsorted(ts, t))
    assert ts[p] == t, "entry minute missing"
    p0 = o[p]
    best, lock = -1e9, None
    F_prev = 0.0
    k = 0
    while True:
        q = p + k
        assert ts[q] == t + k * MIN, "gap in raw minutes"
        F = F_prev + s * f[q]
        level = STOP / LEV + COST + F_prev
        if lock is not None:
            level = max(level, lock / LEV + COST + F_prev)
        op = s * (o[q] / p0 - 1)
        fav = (h[q] / p0 - 1) if s > 0 else (1 - l[q] / p0)
        adv = (l[q] / p0 - 1) if s > 0 else (1 - h[q] / p0)
        if adv <= level:
            fill = min(level, op)
            return max(fill - COST - F, -1 / LEV), k
        roe_hi = LEV * (fav - COST - F)
        if roe_hi > best:
            best = roe_hi
            lock = lock_for(best)
        F_prev = F
        k += 1


def main():
    rng = np.random.default_rng(4242)
    N = RD.names()
    rows = []
    for coin in ("BTCUSDT", "SOLUSDT", "DOGEUSDT", "BCHUSDT"):
        z = np.load(f"{FG}/1m/{coin}.npz")
        ts = z["ts"]
        o, h, l, c, f = (z[k].astype(float) for k in ("o", "h", "l", "c", "fund"))
        f = np.nan_to_num(f)
        for tf in ("15m", "30m"):
            S = RD.signals(roles_=["range", "pullback", "breakout", "reversal", "timing", "other"], tfs=(tf,),
                           period=(ms("2021-01-01"), ms("2026-10-01")), coins=[coin])
            S = RD.add_outcomes(S, ["w35"])
            S = S[np.isfinite(S.w35_r) & (S.w35_why != 3)].reset_index(drop=True)
            Z = RD._states(coin, "1h")
            hc = Z["ts"] + HOUR
            idx = last_closed(hc, S.t.to_numpy(np.int64))
            v = sum(Z[f"j_{k}"].astype(int)[idx] for k in ("V39", "S6", "OBV", "N12"))
            v4 = np.where(np.abs(v) == 4, np.sign(v), 0)
            withm = np.flatnonzero(v4 == S.side.to_numpy())
            pick = np.r_[rng.choice(withm, 12, replace=False), rng.choice(len(S), 6, replace=False)]
            db = bars(coin, tf)
            bc = close_ms(db, tf)
            for j in pick:
                r = S.iloc[j]
                t, s = int(r.t), int(r.side)
                tfm = TF_MIN[tf] * MIN
                a, b = np.searchsorted(ts, t - tfm), np.searchsorted(ts, t)
                mins = ts[a:b]
                bar_ok = len(mins) == TF_MIN[tf] and mins[-1] == t - MIN and (mins < t).all()
                bi = int(np.searchsorted(bc, t))
                close_eq = bc[bi] == t and abs(db.close.iloc[bi] - c[b - 1]) < 1e-9
                i1 = idx[j]
                h_ok = (Z["ts"][i1] + HOUR <= t) and (i1 + 1 >= len(hc) or hc[i1 + 1] > t)
                try:
                    rr, kk = walk(ts, o, h, l, c, f, t, s)
                except (AssertionError, IndexError) as exc:
                    rr, kk = np.nan, -9
                    log("skip (raw gap or past the raw end)", coin, tf, t, repr(exc)[:60])
                rows.append({"coin": coin, "tf": tf, "name": r["name"], "side": s, "t_utc": str(pd.Timestamp(t, unit="ms")),
                             "with_v4of4": bool(v4[j] == s), "bar_minutes_before_entry": bar_ok, "bar_close_equal": close_eq,
                             "htf_bar_open_utc": str(pd.Timestamp(int(Z["ts"][i1]), unit="ms")), "htf_closed": h_ok,
                             "entry_open_raw": o[np.searchsorted(ts, t)], "r_grid": float(r.w35_r), "r_hand": rr,
                             "k_grid": int(r.w35_k), "k_hand": kk, "r_equal": abs(rr - float(r.w35_r)) < 2e-6,
                             "k_equal": kk == int(r.w35_k)})
        RD._GR.pop(coin, None)
        RD._SIG.pop(coin, None)
        drop(coin)
        log(coin, "done")
    D = pd.DataFrame(rows)
    D.to_csv(os.path.join(HERE, "la_trades.csv"), index=False)
    print(D[["bar_minutes_before_entry", "bar_close_equal", "htf_closed", "r_equal", "k_equal"]].mean())
    print(len(D), "trades;", D[~(D.r_equal & D.k_equal)].to_string())


if __name__ == "__main__":
    main()
