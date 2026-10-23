"""참고 read (no selection, every variant shown): 'VWAP 개선판' (PREREG_FWD1.md candidate A) with one or more of the rule
bot's top strategies of the owners' 10/23 ranking photo added, in ONE account with one position (A first when two
signals come at the same minute, then the photo's order, then BTC ETH SOL DOGE LTC BCH), all under A's exits and size:
2 ATR stop + the rule bot's ladder, 96 bars, margin 30 % x min(30, 0.5 / (2 ATR % + 0.14 %)), weekdays, no entry 30 min
around a US macro release or the NYSE open. An added strategy either as it is ("그대로") or with A's two entry gates
too ("A 조건"): the trend bot's 4h vote not against the side, ATR % not above its 30-day 80 % point (its own timeframe).
Signals of the added strategies: the rule bot's code on 5m-built frames (research/newlive/code/signals_all.py's core
path) to the data end. Periods: the rule bot's run (2026-10-05 19:30 UTC .. the data end), 2020-03 .. 2024-12,
2025-01 .. 2026-09.

    python3 -I vwadd.py   -> research/vwap30/add.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwfix2 import *
from vwacct import _take
from vwlive19 import START
from multiprocessing import Pool

PHOTO = [("V39_ALL", "1h", "V3.9 1시간"), ("N05_PSAR_POC", "30m", "PSAR·POC 캔들 30분"),
         ("S3_CMO_SANDWICH", "30m", "CMO·샌드위치 캔들 30분"), ("OBV_S", "30m", "OBV 추세형 30분"),
         ("N13_3OUTSIDE", "30m", "쓰리 아웃사이드 30분"), ("S3_CMO_SANDWICH", "1h", "CMO·샌드위치 캔들 1시간"),
         ("OBV_B", "4h", "OBV 돌파형 4시간"), ("OBV_S", "4h", "OBV 추세형 4시간"), ("S6_EMA_DMI_ADX", "4h", "EMA·DMI·ADX 4시간")]
TFK = {"30m": 30, "1h": 60, "4h": 240}
PERS = {"17일": (START, DATA_END - MIN), "2020-03~2024-12": SEL, "2025-01~2026-09": (ms("2025-01-01"), ms("2026-10-01"))}


def sig_job(coin):
    """The photo's strategies on one coin: {(name, tf): array [t, side, atr]} (sweep_lib.compute_signals)."""
    import warnings
    from paperbot import sweepsig
    from paperbot.recorder import build_frames
    lib = sweepsig.lib()
    m = NL.load_grid(coin)
    f = NL.agg(m, NL.FIVE)
    del m
    out = {}
    for tf in sorted({tf for _, tf, _ in PHOTO}):
        names = sorted({n for n, t, _ in PHOTO if t == tf})
        df = build_frames(lib, NL.df_of(f), [tf])[tf]
        close_t = (df["ts"].astype("int64") // 1_000_000).to_numpy() + TFK[tf] * MIN
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            atr = lib.fg.atr(df, 14).to_numpy(float)
            sigs = lib.compute_signals({coin: df}, tf, names, strict=False)
        for n in names:
            a = np.asarray(sigs[n].get(coin), np.int8)
            k = np.flatnonzero(a)
            out[(n, tf)] = np.c_[close_t[k].astype(float), a[k].astype(float), atr[k]]
    return coin, out


def rows_of(coin, tf, arr):
    """rows_tf's columns for another strategy's signals (t, coin, side, atrf, e, j4h, atrp, atrp_q80)."""
    k = TFK[tf]
    g = grid(coin)
    t = arr[:, 0].astype(np.int64)
    s = arr[:, 1].astype(int)
    atr = arr[:, 2]
    e = (t - T0) // MIN
    ok = (e >= k + 1) & (e < g["n"] - 2 - k) & np.isfinite(atr) & (atr > 0)
    p0 = g["o"][np.clip(e, 0, g["n"] - 1)]
    ok &= np.isfinite(p0) & (p0 > 0)
    Z = np.load(os.path.join(JUDGE_DIR, f"{coin}.npz"))
    tc = Z["4h_tclose"]
    x = np.searchsorted(tc, t, side="right") - 1
    okj = (x >= 0) & (t - tc[np.maximum(x, 0)] < 2 * 240 * MIN)
    j4h = np.where(okj, Z["4h_raw3"].astype(float)[np.maximum(x, 0)] * s, np.nan)
    df = bars(coin, tf)
    a_, _ = atr_adx(df)
    c = df.close.to_numpy(float)
    atrp = a_ / c
    win = int(30 * 1440 / k)
    q80 = pd.Series(atrp).rolling(win, min_periods=win // 2).quantile(0.8).to_numpy()
    bc = df.ts.to_numpy(np.int64) + k * MIN
    i = np.searchsorted(bc, t)
    hit = (i < len(bc)) & (bc[np.minimum(i, len(bc) - 1)] == t)
    ok &= hit
    i = np.minimum(i, len(bc) - 1)
    R = pd.DataFrame({"t": t, "coin": COINS.index(coin), "tf": tf, "side": s, "atrf": atr / p0, "e": e, "j4h": j4h,
                      "atrp": np.where(hit, atrp[i], np.nan), "atrp_q80": np.where(hit, q80[i], np.nan)})
    return R[ok].reset_index(drop=True)


def outcomes_k(coin, R, k):
    """outcomes_tf's base exit, 4h in slices (its 96 x 240-minute window is wide)."""
    r, x = np.zeros(len(R)), np.zeros(len(R), np.int64)
    step = 100 if k >= 240 else len(R) or 1
    for a in range(0, len(R), step):
        S = R.iloc[a:a + step].reset_index(drop=True)
        if not len(S):
            continue
        O = outcomes_tf(coin, S, k)
        r[a:a + len(S)], x[a:a + len(S)] = O["base"]
    return r, x


def time_ok(t):
    kst = pd.to_datetime(t + KST, unit="ms")
    wd = np.asarray(kst.dayofweek < 5)
    usop = np.array([bool(us_open_pause(int(v), 30, 30)) for v in t], bool)
    macro = np.array([bool(EV.near(int(v), 30 * MIN, 30 * MIN)) for v in t], bool)
    return wd & ~usop & ~macro


def gates(R):
    return ~(R.j4h.to_numpy() < 0) & ~(R.atrp.to_numpy() > R.atrp_q80.to_numpy())


def account(parts, a, z, margin=0.3):
    """One position over the members' rows (t, coin, prio, r, x, lev, member) inside [a, z)."""
    P = pd.concat(parts, ignore_index=True)
    P = P[(P.t >= a) & (P.t < z)]
    t, coin, prio = P.t.to_numpy(), P.coin.to_numpy(), P.prio.to_numpy()
    o = np.lexsort((coin, prio, t))
    ext = t[o] + (P.x.to_numpy()[o] + 1) * MIN
    idx = o[_take(t[o], ext, np.ones(len(o), bool))]
    r = P.r.to_numpy()[idx]
    x = margin * P.lev.to_numpy()[idx] * r
    eq = np.cumprod(1 + np.maximum(x, -1))
    dd = float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min()) if len(eq) else 0.0
    mem = P.member.to_numpy()[idx]
    months = (z - a) / DAY / 30.44
    return {"n": int(len(r)), "wins": int((r > 0).sum()), "losses": int((r <= 0).sum()),
            "win": round(float((r > 0).mean()), 4) if len(r) else None,
            "per_month": round(len(r) / months, 1), "avg_net_pct": round(float(r.mean() * 100), 4) if len(r) else None,
            "mult": round(float(eq[-1]), 4) if len(eq) else 1.0, "maxdd": round(dd, 4),
            "month_pace": round(float(eq[-1] ** (30.44 / ((z - a) / DAY))), 3) if len(eq) else 1.0,
            "by_member": {m: {"n": int((mem == m).sum()), "wins": int(((mem == m) & (r > 0)).sum())} for m in sorted(set(mem))}}


def main():
    lib = sweepsig.lib()
    parts = []
    for coin in COINS:                                     # A, as vwfix4 / vwloss6
        R = rows_tf(coin, "30m", lib)
        R["r"], R["x"] = outcomes_tf(coin, R, 30)["base"]
        parts.append(R)
    A = pd.concat(parts, ignore_index=True)
    A = A[time_ok(A.t.to_numpy()) & gates(A)].assign(prio=0, member="VWAP 개선판")
    A["lev"] = np.minimum(LEVP, 0.5 / (2.0 * A.atrf.to_numpy() + COST_RT))
    print("A rows", len(A), flush=True)
    with Pool(2) as pool:
        sig = dict(pool.map(sig_job, COINS))
    X = {}
    for q, (name, tf, ko) in enumerate(PHOTO, start=1):
        rs = []
        for coin in COINS:
            R = rows_of(coin, tf, sig[coin][(name, tf)])
            R["r"], R["x"] = outcomes_k(coin, R, TFK[tf])
            rs.append(R)
        R = pd.concat(rs, ignore_index=True)
        R = R[time_ok(R.t.to_numpy())].assign(prio=q, member=ko)
        R["lev"] = np.minimum(LEVP, 0.5 / (2.0 * R.atrf.to_numpy() + COST_RT))
        R["gated"] = gates(R)
        X[ko] = R
        print("built", ko, len(R), "last", pd.Timestamp(int(R.t.max()), unit="ms"), flush=True)
    res = {"data_end": DATA_END, "variants": {}}

    def run(label, members):
        row = {pn: account(members, a, z) for pn, (a, z) in PERS.items()}
        row["17일 증거금40%"] = account(members, *PERS["17일"], margin=0.4)
        res["variants"][label] = row
        s, f = row["17일"], row["2025-01~2026-09"]
        print(f"{label} | 17일 {s['n']}번 {s['wins']}승{s['losses']}패 x{s['mult']} dd{s['maxdd']} 월{s['per_month']}번 "
              f"월속도x{s['month_pace']} | 25-26 net{f['avg_net_pct']} | 20-24 net{row['2020-03~2024-12']['avg_net_pct']}",
              flush=True)

    run("A 혼자", [A])
    for ko, R in X.items():
        run(f"{ko} 혼자(그대로)", [R.assign(prio=1)])
    for ko, R in X.items():
        run(f"A + {ko} 그대로", [A, R])
        run(f"A + {ko} A 조건", [A, R[R.gated]])
    top3 = list(X)[:3]
    run("A + 상위 3개 그대로", [A] + [X[k] for k in top3])
    run("A + 상위 3개 A 조건", [A] + [X[k][X[k].gated] for k in top3])
    run("A + 9개 전부 그대로", [A] + list(X.values()))
    run("A + 9개 전부 A 조건", [A] + [R[R.gated] for R in X.values()])
    json.dump(res, open(os.path.join(RES_DIR, "add.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
