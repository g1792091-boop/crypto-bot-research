"""참고 read, continued from vwfix.py (no selection, every variant shown): more changes to VWAP fail under the paper rules
(stop 2 ATR, the rule bot's ladder, margin 30 % x 30x, 96-bar cap, one position, weekdays, NYSE-open and macro pauses), on
the rule bot's run (to the data end), 2020-03 .. 2024-12 and 2025-01 .. 2026-09:

  D1 enter one bar later, only when that bar did not close back across the day's VWAP (at the next minute's open)
  D2 move the stop to the entry price after +1 ATR
  D3 skip when BTC's last 30m bar went 0.3 % or more against the side
  D4 skip when BTC's 4h vote (3 of 4 judges) is against the side
  D5 skip when ATR % is above its 30-day 80th percentile
and more entries for the four-filter set of vwfix.py (4h trend, VWAP distance, ADX >= 25, leverage cap):
  E1 the four filters on VWAP 15m + 30m + 1h signals together
  E2 4h trend + leverage cap only, 30m
  E3 4h trend + leverage cap only, 15m + 30m + 1h
  E4 4h trend + leverage cap + D1, 15m + 30m + 1h

    python3 -I vwfix2.py   -> research/vwap30/fix2.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwfix import *
from vwfix import _take

TFS = {"15m": 15, "30m": 30, "1h": 60}


def rows_tf(coin, tf, lib):
    """Signals of one timeframe with the entry-time values the variants read."""
    k = TFS[tf]
    Wt = 96 * k
    g = grid(coin)
    df = bars(coin, tf)
    sg = signals(coin, tf, df)
    F = features(coin, tf, df, sg, g)
    i = sg.i.to_numpy()
    atr = lib.fg.atr(df, 14).to_numpy(float)[i]
    t = sg.bar_close.to_numpy(np.int64)
    s = sg.side.to_numpy(int)
    e = (t - T0) // MIN
    ok = (e >= k + 1) & (e < g["n"] - 2 - k) & np.isfinite(atr) & (atr > 0)
    p0 = g["o"][np.clip(e, 0, g["n"] - 1)]
    ok &= np.isfinite(p0) & (p0 > 0)
    ts = df.ts.to_numpy(np.int64)
    day = ts // DAY
    tp = (df.high + df.low + df.close).to_numpy(float) / 3
    v = df.volume.to_numpy(float)
    with np.errstate(all="ignore"):
        vw = pd.Series(tp * v).groupby(day).cumsum().to_numpy() / pd.Series(v).groupby(day).cumsum().to_numpy()
    cl = df.close.to_numpy(float)
    nxt = np.minimum(i + 1, len(cl) - 1)
    first_back = np.where(s > 0, cl[nxt] < vw[nxt], cl[nxt] > vw[nxt]) & (nxt > i)      # D1: the next bar closed back
    bt = grid("BTCUSDT")
    btc_bar = s * (bt["c"][np.maximum(e - 1, 0)] / bt["o"][np.maximum(e - k, 0)] - 1)
    Z = np.load(os.path.join(JUDGE_DIR, "BTCUSDT.npz"))
    tc = Z["4h_tclose"]
    x = np.searchsorted(tc, t, side="right") - 1
    okj = (x >= 0) & (t - tc[np.maximum(x, 0)] < 2 * 240 * MIN)
    btc4 = np.where(okj, Z["4h_raw3"].astype(float)[np.maximum(x, 0)] * s, np.nan)
    R = pd.DataFrame({"t": t, "coin": COINS.index(coin), "tf": tf, "side": s, "atrf": atr / p0, "e": e,
                      "j4h": F.j4h_raw3.to_numpy(), "cva": F.close_vwap_atr.to_numpy(), "adx": F.adx.to_numpy(),
                      "back1": first_back, "btc_bar": btc_bar, "btc4": btc4,
                      "atrp": F.atrp.to_numpy(), "atrp_q80": F.atrp_q80.to_numpy()})
    return R[ok].reset_index(drop=True)


def outcomes_tf(coin, R, k):
    """(ret, minutes from the signal time to the exit) for: base (2 ATR + ladder), D2 (+1 ATR -> stop at entry), D1 (one
    bar later; rows where the next bar closed back are not traded)."""
    Wt = 96 * k
    g = grid(coin)
    cumf = np.cumsum(g["fund"])
    n = len(R)
    out = {q: (np.zeros(n), np.zeros(n, np.int64)) for q in ("base", "D2", "D1")}
    for name, shift in (("base", 0), ("D2", 0), ("D1", k)):
        for a in range(0, n, 400):
            b = min(n, a + 400)
            e = R.e.to_numpy()[a:b] + shift
            s = R.side.to_numpy()[a:b][:, None]
            p0 = g["o"][e][:, None]
            af = (R.atrf.to_numpy()[a:b] * g["o"][e - shift] / g["o"][e])[:, None]     # the same ATR in price terms
            idx = np.minimum(e[:, None] + np.arange(Wt)[None, :], g["n"] - 1)
            H, L, O, C = g["h"][idx] / p0 - 1, g["l"][idx] / p0 - 1, g["o"][idx] / p0 - 1, g["c"][idx] / p0 - 1
            FC = s * (cumf[idx] - cumf[e - 1][:, None])
            UP = np.where(s > 0, H, -L)
            DN = np.where(s > 0, L, -H)
            OP, CL = s * O, s * C
            hmax = np.minimum(Wt, g["n"] - e)
            col = np.arange(Wt)[None, :]
            valid = col < hmax[:, None]
            UP = np.where(valid, UP, -np.inf)
            DN = np.where(valid, DN, np.inf)
            RMUp = np.concatenate([np.zeros((len(e), 1)), np.maximum.accumulate(UP, axis=1)[:, :-1]], axis=1)
            lk = lock_house(LEVP * (RMUp - COST_RT))
            level = np.maximum(np.where(np.isnan(lk), -np.inf, lk / LEVP + COST_RT), -2.0 * af)
            if name == "D2":
                level = np.maximum(level, np.where(RMUp >= 1.0 * af, 0.0, -np.inf))
            hit = DN <= level
            th = np.where(hit.any(1), hit.argmax(1), Wt + 1)
            tn = hmax - 1
            t = np.minimum(th, tn)
            rows = np.arange(len(e))
            thc = np.minimum(th, Wt - 1)
            v = np.where(th <= tn, np.minimum(level[rows, thc], OP[rows, thc]), CL[rows, np.minimum(tn, Wt - 1)])
            tc = np.minimum(t, Wt - 1)
            out[name][0][a:b] = v - COST_RT - FC[rows, tc]
            out[name][1][a:b] = tc + shift
    return out


def account2(t, coin, ret, tx, mask, expo):
    o = np.lexsort((coin, t))
    tt = t[o]
    ext = tt + (tx[o] + 1) * MIN
    idx = _take(tt, ext, mask[o])
    r = ret[o][idx]
    x = expo[o][idx] * r
    lg = np.log1p(np.maximum(x, -1 + 1e-12))
    eq = np.exp(np.cumsum(lg))
    dd = float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min()) if len(eq) else 0.0
    roe = LEVP * r
    w, l = roe[roe > 0], roe[roe <= 0]
    return {"n": int(len(r)), "wins": int((r > 0).sum()), "losses": int((r <= 0).sum()),
            "win": round(float((r > 0).mean()), 4) if len(r) else None,
            "avg_win_roe": round(float(w.mean() * 100), 1) if len(w) else None,
            "avg_loss_roe": round(float(l.mean() * 100), 1) if len(l) else None,
            "avg_net_pct": round(float(r.mean() * 100), 4) if len(r) else None,
            "mult": round(float(eq[-1]), 4) if len(eq) else 1.0, "maxdd": round(dd, 4)}


def main():
    lib = sweepsig.lib()
    parts = []
    for coin in COINS:
        for tf, k in TFS.items():
            R = rows_tf(coin, tf, lib)
            O = outcomes_tf(coin, R, k)
            for q, (r, x) in O.items():
                R[f"r_{q}"], R[f"x_{q}"] = r, x
            parts.append(R)
            print("built", coin, tf, len(R), flush=True)
    R = pd.concat(parts, ignore_index=True)
    t, coin = R.t.to_numpy(), R.coin.to_numpy()
    kst = pd.to_datetime(t + KST, unit="ms")
    wd = np.asarray(kst.dayofweek < 5)
    usop = np.array([bool(us_open_pause(int(x), 30, 30)) for x in t])
    macro = np.array([bool(EV.near(int(x), 30 * MIN, 30 * MIN)) for x in t])
    base = wd & ~usop & ~macro
    tf30 = (R.tf == "30m").to_numpy()
    j4, cva, adx = R.j4h.to_numpy(), R.cva.to_numpy(), R.adx.to_numpy()
    four = ~(j4 < 0) & ~(cva < 0.3) & ~(adx < 25)
    trend = ~(j4 < 0)
    lev_cap = 0.3 * np.minimum(LEVP, 0.5 / (2.0 * R.atrf.to_numpy() + COST_RT))
    e9 = np.full(len(R), 0.3 * LEVP)
    d1ok = ~R.back1.to_numpy()
    V = [("그대로(30분)", "base", base & tf30, e9),
         ("D1 한 봉 늦게(다음 봉이 VWAP 다시 넘으면 안 들어감)", "D1", base & tf30 & d1ok, e9),
         ("D2 +1ATR 가면 손절을 진입가로", "D2", base & tf30, e9),
         ("D3 BTC 직전 봉 0.3% 반대면 안 들어감", "base", base & tf30 & ~(R.btc_bar.to_numpy() <= -0.003), e9),
         ("D4 BTC 4시간 추세 반대면 안 들어감", "base", base & tf30 & ~(R.btc4.to_numpy() < 0), e9),
         ("D5 변동성 30일 상위 20%면 안 들어감", "base", base & tf30 & ~(R.atrp.to_numpy() > R.atrp_q80.to_numpy()), e9),
         ("C3 필터 4개(30분, 지난번 23승 2패)", "base", base & tf30 & four, lev_cap),
         ("E1 필터 4개, 15분+30분+1시간", "base", base & four, lev_cap),
         ("E2 4시간 추세 + 배율 제한, 30분", "base", base & tf30 & trend, lev_cap),
         ("E3 4시간 추세 + 배율 제한, 15분+30분+1시간", "base", base & trend, lev_cap),
         ("E4 E3 + 한 봉 늦게", "D1", base & trend & d1ok, lev_cap)]
    per = {"17일": (START, DATA_END - MIN), "2020-03~2024-12": SEL, "2025-01~2026-09": (ms("2025-01-01"), ms("2026-10-01"))}
    wdays = {pn: max(1, int(np.sum(pd.date_range(pd.Timestamp(a + KST, unit="ms").normalize(),
                                                  pd.Timestamp(z - 1 + KST, unit="ms").normalize()).dayofweek < 5)))
             for pn, (a, z) in per.items()}
    res = {}
    for name, q, mask, expo in V:
        row = {}
        for pn, (a, z) in per.items():
            m = mask & (t >= a) & (t < z)
            x = account2(t, coin, R[f"r_{q}"].to_numpy(), R[f"x_{q}"].to_numpy(), m, expo)
            x["per_weekday"] = round(x["n"] / wdays[pn], 2)
            row[pn] = x
        res[name] = row
        print(name, " | ".join(f"{pn[:4]} n{v['n']}({v['per_weekday']}/일) {v['wins']}승{v['losses']}패 net{v['avg_net_pct']} x{v['mult']} dd{v['maxdd']}"
                               for pn, v in row.items()), flush=True)
    # E2 with the two BTC / volatility skips added, and every year and month of the base and E2 (weekdays, 9x / capped)
    btc4ok = ~(R.btc4.to_numpy() < 0)
    volok = ~(R.atrp.to_numpy() > R.atrp_q80.to_numpy())
    V2 = [("E5 E2 + BTC 4시간 추세 반대면 안 들어감", "base", base & tf30 & trend & btc4ok, lev_cap),
          ("E6 E2 + 변동성 상위 20% 빼기", "base", base & tf30 & trend & volok, lev_cap),
          ("E7 E2 + 둘 다", "base", base & tf30 & trend & btc4ok & volok, lev_cap),
          ("E8 E2 + 둘 다 + 본전 이동", "D2", base & tf30 & trend & btc4ok & volok, lev_cap)]
    for name, q, mask, expo in V2:
        row = {}
        for pn, (a, z) in per.items():
            m = mask & (t >= a) & (t < z)
            x = account2(t, coin, R[f"r_{q}"].to_numpy(), R[f"x_{q}"].to_numpy(), m, expo)
            x["per_weekday"] = round(x["n"] / wdays[pn], 2)
            row[pn] = x
        res[name] = row
        print(name, " | ".join(f"{pn[:4]} n{v['n']}({v['per_weekday']}/일) {v['wins']}승{v['losses']}패 net{v['avg_net_pct']} x{v['mult']} dd{v['maxdd']}"
                               for pn, v in row.items()), flush=True)
    years = {}
    for name, q, mask, expo in (V[0], V[8]):
        ys = {}
        for y in range(2020, 2027):
            a, z = ms(f"{y}-01-01") if y > 2020 else SEL[0], ms(f"{y + 1}-01-01") if y < 2026 else DATA_END - MIN
            m = mask & (t >= a) & (t < z)
            x = account2(t, coin, R[f"r_{q}"].to_numpy(), R[f"x_{q}"].to_numpy(), m, expo)
            ys[str(y)] = {k: x[k] for k in ("n", "win", "avg_net_pct", "mult", "maxdd")}
        # months: the one-position pass over the whole span, then each KST month's compounded result
        m = mask & (t >= SEL[0])
        o = np.lexsort((coin, t))
        tt = t[o]
        ext = tt + (R[f"x_{q}"].to_numpy()[o] + 1) * MIN
        idx = _take(tt, ext, m[o])
        r = R[f"r_{q}"].to_numpy()[o][idx] * expo[o][idx]
        mon = pd.to_datetime(tt[idx] + KST, unit="ms").to_period("M")
        mm = pd.Series(np.log1p(np.maximum(r, -1 + 1e-12))).groupby(np.asarray(mon.astype(str))).sum()
        mret = np.expm1(mm)
        years[name] = {"years": ys, "months": int(len(mret)), "months_positive": int((mret > 0).sum()),
                       "months_x2": int((mret >= 1).sum()), "best_month": round(float(mret.max()), 3),
                       "worst_month": round(float(mret.min()), 3), "last_months": {k: round(float(v), 3) for k, v in mret.tail(8).items()}}
        print(name, json.dumps(years[name], ensure_ascii=False), flush=True)
    res["_years_months"] = years
    json.dump(res, open(os.path.join(RES_DIR, "fix2.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
