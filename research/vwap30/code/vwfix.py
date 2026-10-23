"""참고 read (no selection, every variant shown): VWAP fail 30m under the paper rules (stop 2 ATR, the rule bot's ladder,
margin 30 % x 30x, 96-bar cap), with one change at a time, on three stretches: the rule bot's run with the live bot's entry
blocks (2026-10-05 19:30 UTC .. the data end), 2020-03 .. 2024-12 and 2025-01 .. 2026-09 (weekdays and the NYSE-open pause;
the macro calendar only covers Oct-Dec 2026). One position, market round trip 0.14 %, real funding.

Changes from the loss review (loss10.json): exit when a closed 30m bar is back across the day's VWAP, exit when BTC is 0.5 %
against since the entry (both only before the first lock), skip when the 1h / 4h trend votes are against, skip a small
rejection wick, skip a close near VWAP, cap the leverage so the 2 ATR stop is at most -50 % ROE, stops 1.5 / 3 ATR.
Take-profit forms: the rule bot's ladder (now), the live bot's ladder, two wider ladders, fixed take-profits at net ROE
+20 / +30 / +50 %, 1 and 2 ATR targets, and no target.

    python3 -I vwfix.py   -> research/vwap30/fix.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
import vwpaper19 as P
from vwpaper19 import *
from vwbuild import features, lock_house, lock_owners
from vwacct import _take

W = 96 * 30
LEVP = 30.0


def lock_w20(r):     # first lock 15 % at 20 % reached, then +5 % per 5 % (gap 5)
    return np.where(r >= 0.20, 0.15 + 0.05 * np.floor((r - 0.20) / 0.05 + 1e-9), np.nan)


def lock_w30(r):     # first lock 20 % at 30 % reached, then +10 % per 10 % (gap 10)
    return np.where(r >= 0.30, 0.20 + 0.10 * np.floor((r - 0.30) / 0.10 + 1e-9), np.nan)


TP = {"T0 지금 계단(12→10, 5%씩)": ("ladder", lock_house), "T1 실거래봇 계단(11→10, 15→12, 20→17)": ("ladder", lock_owners),
      "T2 넓은 계단(20→15, 5%씩)": ("ladder", lock_w20), "T3 더 넓은 계단(30→20, 10%씩)": ("ladder", lock_w30),
      "T4 고정 익절 ROE +20%": ("roe", 0.20), "T5 고정 익절 ROE +30%": ("roe", 0.30), "T6 고정 익절 ROE +50%": ("roe", 0.50),
      "T7 익절 1ATR": ("atr", 1.0), "T8 익절 2ATR": ("atr", 2.0), "T9 익절 없음(손절·96봉만)": ("none", None)}
FIX = ["F0 그대로", "F1 VWAP 다시 넘으면 정리", "F2 BTC 0.5% 반대면 정리", "F3 1시간 추세 반대면 안 들어감",
       "F4 4시간 추세 반대면 안 들어감", "F5 반등 꼬리 20% 미만 안 들어감", "F6 VWAP에 너무 가까우면(0.3ATR 미만) 안 들어감",
       "F7 손절이 ROE −50% 넘으면 배율 낮춤", "F8 손절 1.5ATR", "F9 손절 3ATR", "F10 횡보(ADX 20 미만) 안 들어감",
       "F11 횡보(ADX 25 미만) 안 들어감", "F12 주말도 들어감", "F13 주말만"]


def coin_rows(coin, lib):
    g = grid(coin)
    df = bars(coin, "30m")
    sg = signals(coin, "30m", df)
    F = features(coin, "30m", df, sg, g)
    i = sg.i.to_numpy()
    atr = lib.fg.atr(df, 14).to_numpy(float)[i]
    t = sg.bar_close.to_numpy(np.int64)
    s = sg.side.to_numpy(int)
    e = (t - T0) // MIN
    ok = (e >= 1) & (e < g["n"] - 2) & np.isfinite(atr) & (atr > 0)
    p0 = g["o"][np.clip(e, 0, g["n"] - 1)]
    ok &= np.isfinite(p0) & (p0 > 0)
    # the day's VWAP on the 30m bars and the first closed bar back across it (minutes from the entry)
    ts = df.ts.to_numpy(np.int64)
    day = ts // DAY
    tp = (df.high + df.low + df.close).to_numpy(float) / 3
    v = df.volume.to_numpy(float)
    with np.errstate(all="ignore"):
        vw = pd.Series(tp * v).groupby(day).cumsum().to_numpy() / pd.Series(v).groupby(day).cumsum().to_numpy()
    cl = df.close.to_numpy(float)
    wrong_long, wrong_short = cl < vw, cl > vw
    k_rec = np.full(len(i), W + 1, np.int64)
    for q in range(len(i)):
        a = i[q] + 1
        b = min(len(cl), i[q] + 97)
        w = wrong_long[a:b] if s[q] > 0 else wrong_short[a:b]
        if w.any():
            k_rec[q] = (int(np.argmax(w)) + 1) * 30            # the bar a+j closes 30 (j+1) minutes after the entry
    # BTC 0.5 % against since the entry (minutes from the entry, exit at the next minute's open)
    bt = grid("BTCUSDT")
    k_btc = np.full(len(i), W + 1, np.int64)
    for q in np.flatnonzero(ok):
        m = slice(e[q], min(bt["n"], e[q] + W))
        x = s[q] * (bt["c"][m] / bt["o"][e[q]] - 1)
        hit = np.flatnonzero(x <= -0.005)
        if len(hit):
            k_btc[q] = int(hit[0]) + 1
    R = pd.DataFrame({"t": t, "coin": COINS.index(coin), "side": s, "atrf": atr / p0, "e": e, "k_rec": k_rec, "k_btc": k_btc,
                      "j1h": F.j1h_raw3.to_numpy(), "j4h": F.j4h_raw3.to_numpy(), "wick": F.wick_frac.to_numpy(),
                      "cva": F.close_vwap_atr.to_numpy(), "adx": F.adx.to_numpy()})
    return R[ok].reset_index(drop=True)


def outcomes(coin, R):
    """(ret, minutes to exit) per row for every (take-profit form) with F0 and for every fix with T0."""
    g = grid(coin)
    cumf = np.cumsum(g["fund"])
    out = {}
    n = len(R)
    for key in [("T", k) for k in TP] + [("F", k) for k in FIX[1:]]:
        out[key] = (np.zeros(n), np.zeros(n, np.int64))
    for a in range(0, n, 400):
        b = min(n, a + 400)
        e = R.e.to_numpy()[a:b]
        s = R.side.to_numpy()[a:b][:, None]
        af = R.atrf.to_numpy()[a:b][:, None]
        idx = np.minimum(e[:, None] + np.arange(W)[None, :], g["n"] - 1)
        p0 = g["o"][e][:, None]
        H, L, O, C = g["h"][idx] / p0 - 1, g["l"][idx] / p0 - 1, g["o"][idx] / p0 - 1, g["c"][idx] / p0 - 1
        FC = s * (cumf[idx] - cumf[e - 1][:, None])
        UP = np.where(s > 0, H, -L)
        DN = np.where(s > 0, L, -H)
        OP, CL = s * O, s * C
        hmax = np.minimum(W, g["n"] - e)
        col = np.arange(W)[None, :]
        valid = col < hmax[:, None]
        UP = np.where(valid, UP, -np.inf)
        DN = np.where(valid, DN, np.inf)
        RMUp = np.concatenate([np.zeros((len(e), 1)), np.maximum.accumulate(UP, axis=1)[:, :-1]], axis=1)
        rows = np.arange(len(e))
        tn = hmax - 1

        def finish(level, tgt, early):
            hit = DN <= level
            th = np.where(hit.any(1), hit.argmax(1), W + 1)
            if tgt is not None:
                ht = UP >= tgt
                tt = np.where(ht.any(1), ht.argmax(1), W + 1)
            else:
                tt = np.full(len(e), W + 1)
            t = np.minimum(np.minimum(th, tt), tn)
            stop_first = th <= np.minimum(tt, tn)                 # in one minute the stop is taken first
            tgt_hit = ~stop_first & (tt <= tn)
            tgt_val = tgt[:, 0] if tgt is not None else np.zeros(len(e))
            thc = np.minimum(th, W - 1)
            v = np.where(stop_first, np.minimum(level[rows, thc], OP[rows, thc]),
                         np.where(tgt_hit, tgt_val, CL[rows, np.minimum(tn, W - 1)]))
            if early is not None:
                ke, lock_off = early
                use = (ke < t) & lock_off[rows, np.minimum(ke, W - 1)]
                t = np.where(use, ke, t)
                v = np.where(use, OP[rows, np.minimum(ke, W - 1)], v)
            tc = np.minimum(t, W - 1)
            return v - COST_RT - FC[rows, tc], tc

        def ladder_level(lockf, k_stop):
            lk = lockf(LEVP * (RMUp - COST_RT))
            return np.maximum(np.where(np.isnan(lk), -np.inf, lk / LEVP + COST_RT), -k_stop * af), np.isnan(lk)

        for name, (kind, x) in TP.items():
            if kind == "ladder":
                lvl, _ = ladder_level(x, 2.0)
                r, tc = finish(lvl, None, None)
            else:
                lvl = np.broadcast_to(-2.0 * af, UP.shape)
                tgt = {"roe": np.full((len(e), 1), x / LEVP + COST_RT) if kind == "roe" else None,
                       "atr": x * af if kind == "atr" else None, "none": None}[kind]
                r, tc = finish(lvl, tgt, None)
            out[("T", name)][0][a:b], out[("T", name)][1][a:b] = r, tc
        lvl0, off0 = ladder_level(lock_house, 2.0)
        for name in FIX[1:]:
            if name.startswith("F1 "):
                r, tc = finish(lvl0, None, (R.k_rec.to_numpy()[a:b], off0))
            elif name.startswith("F2 "):
                r, tc = finish(lvl0, None, (R.k_btc.to_numpy()[a:b], off0))
            elif name.startswith("F8 "):
                r, tc = finish(ladder_level(lock_house, 1.5)[0], None, None)
            elif name.startswith("F9 "):
                r, tc = finish(ladder_level(lock_house, 3.0)[0], None, None)
            else:
                r, tc = out[("T", "T0 지금 계단(12→10, 5%씩)")][0][a:b], out[("T", "T0 지금 계단(12→10, 5%씩)")][1][a:b]
            out[("F", name)][0][a:b], out[("F", name)][1][a:b] = r, tc
    return out


def account(R, ret, tx, mask, expo):
    o = np.lexsort((R.coin.to_numpy(), R.t.to_numpy()))
    t = R.t.to_numpy()[o]
    ext = t + (tx[o] + 1) * MIN
    idx = _take(t, ext, mask[o])
    r = ret[o][idx]
    x = expo[o][idx] * r
    lg = np.log1p(np.maximum(x, -1 + 1e-12))
    eq = np.exp(np.cumsum(lg))
    dd = float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min()) if len(eq) else 0.0
    roe = LEVP * r
    w, l = roe[roe > 0], roe[roe <= 0]
    return {"n": int(len(r)), "win": round(float((r > 0).mean()), 4) if len(r) else None,
            "avg_win_roe": round(float(w.mean() * 100), 1) if len(w) else None,
            "avg_loss_roe": round(float(l.mean() * 100), 1) if len(l) else None,
            "payoff": round(float(w.mean() / -l.mean()), 3) if len(w) and len(l) else None,
            "avg_net_pct": round(float(r.mean() * 100), 4) if len(r) else None,
            "mult": round(float(eq[-1]), 4) if len(eq) else 1.0, "maxdd": round(dd, 4)}


def check(R, O):
    """T0 / T7 / T8 / T9 / F8 / F9 against round 3's exits 10 / 11 / 12 / 20 / 5 / 15 (same paths; ATR differs on ~0.3 %)."""
    import vwbuild3 as B
    Z = np.load(os.path.join(B.OUT3, "F6_VWAP_FAIL_at_30m.npz"))
    z = pd.DataFrame({"t": Z["t"], "coin": Z["coin"].astype(int), "q": np.arange(len(Z["t"]))})
    j = pd.DataFrame({"t": R.t, "coin": R.coin, "r": np.arange(len(R))}).merge(z, on=["t", "coin"])
    for key, jj in ((("T", "T0 지금 계단(12→10, 5%씩)"), 10), (("T", "T7 익절 1ATR"), 11), (("T", "T8 익절 2ATR"), 12),
                    (("T", "T9 익절 없음(손절·96봉만)"), 20), (("F", "F8 손절 1.5ATR"), 5), (("F", "F9 손절 3ATR"), 15)):
        a = O[key][0][j.r.to_numpy()]
        b = Z["ret"][j.q.to_numpy(), jj]
        print("check", key[1], "rows", len(j), "differ", float((np.abs(a - b) > 1e-5).mean()), flush=True)


def main():
    lib = sweepsig.lib()
    parts, outs = [], []
    for coin in COINS:
        R = coin_rows(coin, lib)
        o = outcomes(coin, R)
        parts.append(R)
        outs.append(o)
        print("built", coin, len(R), flush=True)
    R = pd.concat(parts, ignore_index=True)
    O = {k: (np.concatenate([o[k][0] for o in outs]), np.concatenate([o[k][1] for o in outs])) for k in outs[0]}
    check(R, O)
    kst = pd.to_datetime(R.t.to_numpy() + KST, unit="ms")
    wd = np.asarray(kst.dayofweek < 5)
    usop = np.array([bool(us_open_pause(int(x), 30, 30)) for x in R.t])
    macro = np.array([bool(EV.near(int(x), 30 * MIN, 30 * MIN)) for x in R.t])
    base = wd & ~usop & ~macro
    per = {"17일(10/05~10/23, 실거래봇 진입 금지)": (START, DATA_END - MIN), "2020-03~2024-12(평일)": SEL,
           "2025-01~2026-09(평일)": (ms("2025-01-01"), ms("2026-10-01"))}
    expo9 = np.full(len(R), 0.3 * LEVP)
    lev_cap = np.minimum(LEVP, 0.5 / (2.0 * R.atrf.to_numpy() + COST_RT))
    res = {}
    for key, (ret, tx) in O.items():
        name = key[1]
        mask = base.copy()
        expo = expo9
        if name.startswith("F3 "):
            mask &= ~(R.j1h.to_numpy() < 0)
        elif name.startswith("F4 "):
            mask &= ~(R.j4h.to_numpy() < 0)
        elif name.startswith("F5 "):
            mask &= ~(R.wick.to_numpy() < 0.2)
        elif name.startswith("F6 "):
            mask &= ~(R.cva.to_numpy() < 0.3)
        elif name.startswith("F7 "):
            expo = 0.3 * lev_cap
        elif name.startswith("F10"):
            mask &= ~(R.adx.to_numpy() < 20)
        elif name.startswith("F11"):
            mask &= ~(R.adx.to_numpy() < 25)
        elif name.startswith("F12"):
            mask = ~usop & ~macro
        elif name.startswith("F13"):
            mask = ~wd
        row = {}
        for pn, (a, z) in per.items():
            m = mask & (R.t.to_numpy() >= a) & (R.t.to_numpy() < z)
            row[pn] = account(R, ret, tx, m, expo)
        res[f"{key[0]}|{name}"] = row
        print(name, " | ".join(f"{pn[:6]} n{v['n']} win{v['win']} net{v['avg_net_pct']} x{v['mult']} dd{v['maxdd']}" for pn, v in row.items()),
              flush=True)
    # the changes that helped most on the 17 days, put together (chosen by looking at the 17 days: the 5-year columns show
    # whether that carries)
    j4, cva, adx = R.j4h.to_numpy(), R.cva.to_numpy(), R.adx.to_numpy()
    combos = [("C1 4시간 추세 + VWAP 거리 + 배율 제한", ("T", "T0 지금 계단(12→10, 5%씩)"), base & ~(j4 < 0) & ~(cva < 0.3), 0.3 * lev_cap),
              ("C2 C1 + 더 넓은 계단(30→20)", ("T", "T3 더 넓은 계단(30→20, 10%씩)"), base & ~(j4 < 0) & ~(cva < 0.3), 0.3 * lev_cap),
              ("C3 C1 + 횡보(ADX 25 미만) 빼기", ("T", "T0 지금 계단(12→10, 5%씩)"), base & ~(j4 < 0) & ~(cva < 0.3) & ~(adx < 25),
               0.3 * lev_cap)]
    for name, key, mask, expo in combos:
        ret, tx = O[key]
        row = {}
        for pn, (a, z) in per.items():
            m = mask & (R.t.to_numpy() >= a) & (R.t.to_numpy() < z)
            row[pn] = account(R, ret, tx, m, expo)
        res[f"C|{name}"] = row
        print(name, " | ".join(f"{pn[:6]} n{v['n']} win{v['win']} net{v['avg_net_pct']} x{v['mult']} dd{v['maxdd']}" for pn, v in row.items()),
              flush=True)
    json.dump(res, open(os.path.join(RES_DIR, "fix.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
