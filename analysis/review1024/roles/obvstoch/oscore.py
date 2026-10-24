"""Core of the OBV x Stoch RSI study (analysis/review1024/roles/obvstoch, PLAN.md sha256 in PLAN.sha256).

Per coin and entry timeframe (15m / 30m / 1h) it builds, for EVERY bar close:
  e (entry minute from T0), t (ms), day (UTC day number), blk (entry block code)
  sig_<O>      int8 +1 / -1 / 0: the timing signal O on that bar (6 timings of the plan)
  st_<htf>_<T> int8: the trend state T of the last CLOSED htf bar (9 trends; htf 1h / 4h above the entry tf)
  <X>_L_r, <X>_S_r float32 net price return, <X>_L_w, <X>_S_w int8 exit reason (0 stop, 1 lock, 3 open, -1 none)
               for X in w35 / w35s30 / w35s20 / a2 (a2 on the entry tf)
and caches it uncompressed in /dev/shm (the disk is full), never in the repository.

Everything is read from the shared data layer (../data, files under common.OUT); w35s30 is walked here with
frdeep.walk3 (net-ROE stop -30 %); the call is checked to reproduce the grid's w35 exactly. Run from this folder:
    python3 oscore.py build        (6 coins, 3 processes)
"""
import os
import sys

sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
import rolesdata as RD                      # noqa: E402
from common import *                        # noqa: E402,F401,F403

CACHE = "/dev/shm/obvstoch_review1024"
HERE = os.path.dirname(os.path.abspath(__file__))
ENTRY_TFS = ("15m", "30m", "1h")
HTF_OF = {"15m": ("1h", "4h"), "30m": ("1h", "4h"), "1h": ("4h",)}
MAPS = (("15m", "1h"), ("15m", "4h"), ("30m", "1h"), ("30m", "4h"), ("1h", "4h"))
TRENDS = ("OBV20", "OBV30", "OBV50", "OBVSL10", "ST", "EMA21_52", "ICHI", "J3", "J3A")
OBV_TRENDS = ("OBV20", "OBV30", "OBV50", "OBVSL10")
TIMINGS = ("SRSI_KD", "SRSI_X", "RSI", "WR", "CCI", "MFI")
SRSI = ("SRSI_KD", "SRSI_X")
LIB_TIMING = {"SRSI_KD": "O4_STOCHRSI_ZONE", "RSI": "O1_RSI14_REV30", "WR": "O6_WR14", "CCI": "O5_CCI20",
              "MFI": "O7_MFI14"}
EXITS = ("w35", "w35s30", "w35s20", "a2")
LEVX = {"w35": 35.0, "w35s30": 35.0, "w35s20": 35.0, "a2": 30.0}
STOPX = {"w35s30": -0.30}
WARM = 300

P = {"PRE": (ms("2020-03-01"), ms("2021-01-01")), "SEL": (ms("2021-01-01"), ms("2024-01-01")),
     "CONF": (ms("2024-01-01"), GRID_END), "YTD": (ms("2026-01-01"), GRID_END),
     "FWD": (ms("2026-10-05 15:00"), ms("2026-10-24 15:00")), "FIVE": (ms("2020-03-01"), GRID_END)}


def _sgn(x):
    x = np.asarray(x, float)
    with np.errstate(invalid="ignore"):
        return np.where(x > 0, 1, np.where(x < 0, -1, 0)).astype(np.int8)


def _cross_up(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return (a > b) & (np.r_[np.nan, a[:-1]] <= np.r_[np.nan, b[:-1]])


def trend_states(coin, htf, df):
    """{trend: int8 per htf bar} (warm-up bars < WARM set to 0) + checks against the shared state file."""
    pi = libs()["pi"]
    Z = np.load(os.path.join(OUT, "states", f"{coin}_{htf}.npz"))
    ts = df.ts.to_numpy(np.int64)
    assert len(ts) == len(Z["ts"]) and (ts == Z["ts"]).all(), (coin, htf)
    c = df.close.to_numpy(float)
    ob = np.asarray(pi.obv(c, df.volume.to_numpy(float)), float)
    S = {}
    for n_ in (20, 30, 50):
        S[f"OBV{n_}"] = _sgn(ob - np.asarray(pi.pine_sma(ob, n_), float))
    S["OBVSL10"] = _sgn(ob - np.r_[np.full(10, np.nan), ob[:-10]])
    S["EMA21_52"] = _sgn(np.asarray(pi.pine_ema(c, 21), float) - np.asarray(pi.pine_ema(c, 52), float))
    S["ST"] = Z["c_V39_ALL"].astype(np.int8)
    S["ICHI"] = Z["c_N12_ICHI_AO"].astype(np.int8)
    S["J3"] = Z["j_dir"].astype(np.int8)
    with np.errstate(invalid="ignore"):
        S["J3A"] = np.where(Z["j_adx"] >= 20.0, Z["j_dir"], 0).astype(np.int8)
    chk = {"OBV30_vs_c_OBV_S": float((S["OBV30"] == Z["c_OBV_S"]).mean()),
           "OBV20_vs_c_VO1": float((S["OBV20"] == Z["c_VO1_OBV_X_MA20"]).mean())}
    warm = Z["nb"] < WARM
    for k in S:
        S[k] = np.where(warm, 0, S[k]).astype(np.int8)
    return S, ts + TF_MIN[htf] * MIN, chk


def timings(coin, tf, df):
    """{timing: int8 +1/-1/0 per entry-tf bar}, e0, and the check of my Stoch RSI against the library bits."""
    pi = libs()["pi"]
    S = {}
    e0 = None
    for nm, lib_name in LIB_TIMING.items():
        lg, sh, e0_ = RD.signal_bits(lib_name, tf, coin)
        assert lg is not None and len(lg) == len(df), (coin, tf, nm)
        e0 = e0_ if e0 is None else e0
        assert e0 == e0_
        S[nm] = np.where(lg, 1, np.where(sh, -1, 0)).astype(np.int8)
    c = df.close.to_numpy(float)
    k, d = pi.stoch_rsi_kd(c, 14, 14, 3, 3)
    k, d = np.asarray(k, float), np.asarray(d, float)
    with np.errstate(invalid="ignore"):
        kd_l = np.nan_to_num((_cross_up(k, d) & (k < 20)).astype(float)) != 0
        kd_s = (np.nan_to_num((_cross_up(d, k) & (k > 80)).astype(float)) != 0) & ~kd_l
        x_l = np.nan_to_num(_cross_up(k, np.full(len(k), 20.0)).astype(float)) != 0
        x_s = (np.nan_to_num(_cross_up(np.full(len(k), 80.0), k).astype(float)) != 0) & ~x_l
    mine_kd = np.where(kd_l, 1, np.where(kd_s, -1, 0)).astype(np.int8)
    chk = {"SRSI_KD_mine_vs_O4": float((mine_kd == S["SRSI_KD"]).mean())}
    S["SRSI_X"] = np.where(x_l, 1, np.where(x_s, -1, 0)).astype(np.int8)
    assert e0 == (close_ms(df, tf)[0] - T0) // MIN, (coin, tf)
    for kk in S:
        S[kk][:WARM] = 0
    return S, e0, chk


def walk_s30(coin, G):
    """w35s30 over every valid 15m entry minute, both sides (frdeep.walk3, as build_grid but stop -30 %); the same call
    with stop -50 % reproduces the grid's w35 (checked on a slice)."""
    from frdeep import walk3
    g = grid(coin)
    n = g["n"]
    cumf = np.cumsum(g["fund"])
    valid = G["valid15"]
    e = (np.arange(len(valid), dtype=np.int64) + 1) * 15
    ev = e[valid]
    flag = np.zeros(1, bool)
    out = {}
    sl = ev[:: max(1, len(ev) // 3000)]
    a = walk3(g["o"], g["h"], g["l"], g["c"], cumf, sl, 1, 35.0, COST, FL, STEP, GAP, -0.50, 9.0, 0.01, 0, flag, False,
              g["c"], g["o"], 0.0, n)
    jj = sl // 15 - 1
    chk = float(np.mean(np.isclose(a[0].astype(np.float32), G["w35_L_r"][jj], atol=1e-7) & (a[1] == G["w35_L_k"][jj])))
    for lab, s in (("L", 1), ("S", -1)):
        a = walk3(g["o"], g["h"], g["l"], g["c"], cumf, ev, s, 35.0, COST, FL, STEP, GAP, STOPX["w35s30"], 9.0, 0.01, 0,
                  flag, False, g["c"], g["o"], 0.0, n)
        r = np.full(len(valid), np.nan, np.float32)
        k = np.full(len(valid), -1, np.int32)
        w = np.full(len(valid), -1, np.int8)
        r[valid], k[valid], w[valid] = a[0], a[1], a[2]
        out[lab] = (r, k, w)
    return out, chk


def build_coin(coin):
    t0 = time.time()
    G = RD._grid(coin)
    s30, chk_walk = walk_s30(coin, G)
    blk = np.load(os.path.join(OUT, "grid", "blk15.npy"))
    B = {tf: bars(coin, tf) for tf in ("15m", "30m", "1h", "4h")}
    HT = {}
    checks = {"walk_w35_repro": chk_walk}
    for htf in ("1h", "4h"):
        S, cl, chk = trend_states(coin, htf, B[htf])
        HT[htf] = (S, cl)
        checks.update({f"{htf}_{k}": v for k, v in chk.items()})
    out = {}
    for tf in ENTRY_TFS:
        df = B[tf]
        TS, e0, chk = timings(coin, tf, df)
        checks[f"{tf}_{list(chk)[0]}"] = list(chk.values())[0]
        nb = len(df)
        tfm = TF_MIN[tf]
        e = e0 + np.arange(nb, dtype=np.int64) * tfm
        t = T0 + e * MIN
        pre = f"{tf}_"
        out[pre + "e"] = e
        out[pre + "day"] = (t // DAY).astype(np.int32)
        j15 = e // 15 - 1
        ok15 = (j15 >= 0) & (j15 < len(G["valid15"]))
        jc = np.clip(j15, 0, len(G["valid15"]) - 1)
        out[pre + "blk"] = np.where(ok15, blk[np.clip(j15, 0, len(blk) - 1)], -1).astype(np.int8)
        for nm, arr in TS.items():
            out[pre + "sig_" + nm] = arr
        for htf in HTF_OF[tf]:
            S, cl = HT[htf]
            idx = last_closed(cl, t)
            for tr, arr in S.items():
                out[f"{pre}st_{htf}_{tr}"] = np.where(idx >= 0, arr[np.clip(idx, 0, len(arr) - 1)], 0).astype(np.int8)
        for x in EXITS:
            for lab in ("L", "S"):
                if x in ("w35", "w35s20"):
                    r, w = G[f"{x}_{lab}_r"][jc], G[f"{x}_{lab}_why"][jc]
                elif x == "w35s30":
                    r, w = s30[lab][0][jc], s30[lab][2][jc]
                else:
                    jt = e // tfm - 1
                    okt = (jt >= 0) & (jt < len(G[f"a2_{tf}_{lab}_r"]))
                    jt = np.clip(jt, 0, len(G[f"a2_{tf}_{lab}_r"]) - 1)
                    r = np.where(okt, G[f"a2_{tf}_{lab}_r"][jt], np.nan)
                    w = np.where(okt, G[f"a2_{tf}_{lab}_why"][jt], -1)
                    ok = okt
                if x != "a2":
                    ok = ok15
                out[f"{pre}{x}_{lab}_r"] = np.where(ok, r, np.nan).astype(np.float32)
                out[f"{pre}{x}_{lab}_w"] = np.where(ok, w, -1).astype(np.int8)
                if x == "w35s30":
                    out[f"{pre}{x}_{lab}_k"] = np.where(ok, s30[lab][1][jc], -1).astype(np.int32)
    os.makedirs(CACHE, exist_ok=True)
    tmp = os.path.join(CACHE, f"{coin}.tmp.npz")
    np.savez(tmp, **out)
    os.replace(tmp, os.path.join(CACHE, f"{coin}.npz"))
    drop(coin)
    RD._GR.pop(coin, None)
    log(coin, f"built {time.time() - t0:.0f}s", checks)
    return coin, checks


def load(coin):
    z = np.load(os.path.join(CACHE, f"{coin}.npz"))
    return {k: z[k] for k in z.files}


def load_all():
    return {c: load(c) for c in COINS}


# ---------------------------------------------------------------------- statistics
def cl_stats(x, day):
    """n, mean, cluster(UTC day)-robust SE and t of x."""
    n = len(x)
    if n < 2:
        return n, (float(x.mean()) if n else np.nan), np.nan, np.nan
    m = float(x.mean())
    u, inv = np.unique(day, return_inverse=True)
    s = np.bincount(inv, weights=x - m)
    G = len(u)
    se = np.sqrt((s * s).sum() * G / max(G - 1, 1)) / n
    return n, m, se, (m / se if se > 0 else np.nan)


def bh(p):
    """Benjamini-Hochberg q-values."""
    p = np.asarray(p, float)
    q = np.full(len(p), np.nan)
    ok = np.isfinite(p)
    pv = p[ok]
    o = np.argsort(pv)
    m = len(pv)
    qq = pv[o] * m / (np.arange(m) + 1)
    qq = np.minimum.accumulate(qq[::-1])[::-1]
    out = np.empty(m)
    out[o] = np.minimum(qq, 1.0)
    q[ok] = out
    return q


def rows(D, tf, htf, trend, timing, x, period, against=False, trend_only=False, timing_only=False, drop_open=True):
    """Concatenated rows of one cell over all coins: dict side, roe, roe_opp, day, t, coin, e, blk."""
    a, b = P[period] if isinstance(period, str) else period
    acc = {k: [] for k in ("side", "roe", "opp", "day", "e", "coin", "blk", "w")}
    lev = LEVX[x]
    for ci, coin in enumerate(COINS):
        Z = D[coin]
        pre = f"{tf}_"
        e = Z[pre + "e"]
        t = T0 + e * MIN
        mt = (t >= a) & (t < b)
        if trend_only:
            st = Z[f"{pre}st_{htf}_{trend}"]
            side = st
            m = mt & (st != 0)
        else:
            sig = Z[pre + "sig_" + timing]
            if timing_only:
                m = mt & (sig != 0)
            else:
                st = Z[f"{pre}st_{htf}_{trend}"]
                m = mt & (sig != 0) & ((st == -sig) if against else (st == sig))
            side = sig
        rL, rS = Z[f"{pre}{x}_L_r"], Z[f"{pre}{x}_S_r"]
        wL, wS = Z[f"{pre}{x}_L_w"], Z[f"{pre}{x}_S_w"]
        sd = side[m]
        r = np.where(sd > 0, rL[m], rS[m])
        ro = np.where(sd > 0, rS[m], rL[m])
        w = np.where(sd > 0, wL[m], wS[m])
        wo = np.where(sd > 0, wS[m], wL[m])
        keep = np.isfinite(r) & np.isfinite(ro)
        if drop_open:
            keep &= (w != 3) & (wo != 3)
        acc["side"].append(sd[keep])
        acc["roe"].append(lev * r[keep].astype(float))
        acc["opp"].append(lev * ro[keep].astype(float))
        acc["day"].append(Z[pre + "day"][m][keep])
        acc["e"].append(e[m][keep])
        acc["coin"].append(np.full(int(keep.sum()), ci, np.int8))
        acc["blk"].append(Z[pre + "blk"][m][keep])
        acc["w"].append(w[keep])
    return {k: np.concatenate(v) if v else np.array([]) for k, v in acc.items()}


def summarize(R):
    n, m, se, t = cl_stats(R["roe"], R["day"])
    d = R["roe"] - R["opp"]
    _, md, sed, td = cl_stats(d, R["day"])
    from scipy.stats import norm
    days = len(np.unique(R["day"])) if n else 0
    return {"n": n, "mean_roe": m, "se": se, "t_abs": t, "p_abs": float(norm.sf(t)) if np.isfinite(t) else np.nan,
            "mean_opp": float(R["opp"].mean()) if n else np.nan, "mean_d": md, "t_d": td,
            "p_d": float(norm.sf(td)) if np.isfinite(td) else np.nan,
            "win": float((R["roe"] > 0).mean()) if n else np.nan,
            "long_share": float((R["side"] > 0).mean()) if n else np.nan, "days_with": days}


def parse(cell):
    """'T@htf>O@tf|X' -> (tf, htf, T, O, X)."""
    left, X = cell.split("|")
    tr, tm = left.split(">")
    T, htf = tr.split("@")
    Ot, tf = tm.split("@")
    return tf, htf, T, Ot, X


def holm(p):
    p = np.asarray(p, float)
    o = np.argsort(p)
    m = len(p)
    adj = np.empty(m)
    run = 0.0
    for i, k in enumerate(o):
        run = max(run, min(1.0, (m - i) * p[k]))
        adj[k] = run
    return adj


def cells():
    out = []
    for tf, htf in MAPS:
        for T in TRENDS:
            for O in TIMINGS:
                for X in EXITS:
                    out.append((tf, htf, T, O, X))
    return out


def cell_id(tf, htf, T, O, X):
    return f"{T}@{htf}>{O}@{tf}|{X}"


if __name__ == "__main__":
    if sys.argv[1:2] == ["build"]:
        from multiprocessing import get_context
        coins = sys.argv[2:] or list(COINS)
        import json
        allchk = {}
        with get_context("fork").Pool(3) as pool:
            for c, chk in pool.imap_unordered(build_coin, coins):
                allchk[c] = chk
        json.dump(allchk, open(os.path.join(HERE, "build_checks.json"), "w"), indent=1)
        print(json.dumps(allchk, indent=1))
