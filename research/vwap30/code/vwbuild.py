"""Builds, for one timeframe, every F6_VWAP_FAIL signal's entry-time features and its outcome under every exit of the
grid, for the signal's side and for the other side (the coin-flip twin). PREREG.md "고정한 계산 방식" and step 5.

    python3 -I vwbuild.py 30m [--procs 4]

Writes OUT/<tf>/<coin>.npz (outcomes: ret, exit minute offset, for side and other side) and OUT/<tf>/features.pkl.
An outcome: entry = the 1m open at the signal bar's close; exit by the first of stop (a gap through it fills at that
minute's open), target (filled at the level), time (that minute's close); stop before target inside one minute;
net = price return - COST_RT - funding paid (the actual rates). The path is cut at HOLD_BARS bars (or the data end)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwcommon import *
import warnings
from multiprocessing import Pool
warnings.filterwarnings("ignore", category=RuntimeWarning)

STOPS = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0)                 # ATR (of the signal timeframe)
TARGETS = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0, None)
TIMES = (8, 16, 96)                                     # bars
BES = (None, 1.0)                                       # stop to entry after +1 ATR
TRAILS = ((0.5, 0.5), (1.0, 0.5), (1.0, 1.0), (2.0, 1.0))   # (activate after +a ATR, trail d ATR), stop 2 ATR, 96 bars


def exit_list():
    ex = []
    for s in STOPS:
        for t in TARGETS:
            for n in TIMES:
                for b in BES:
                    ex.append({"kind": "grid", "stop": s, "target": t, "time": n, "be": b})
    for a, d in TRAILS:
        ex.append({"kind": "trail", "stop": 2.0, "act": a, "dist": d, "time": 96})
    ex.append({"kind": "house", "stop": 2.0, "lev": 30, "time": 96})          # B1: the rule bot's 2 ATR + its ladder
    ex.append({"kind": "owners", "time": 96})                                 # B2: -50 % net ROE, the owners' ladder
    for i, e in enumerate(ex):
        e["id"] = i
    return ex


EXITS = exit_list()


def owners_lev(coin):
    return 40 if coin == "BTCUSDT" else 30


def lock_house(r):
    """The rule bot's ladder (config ladder_first_lock 0.10, step 0.05, trigger gap 0.02) on reached net ROE r."""
    return np.where(r >= 0.12, 0.10 + 0.05 * np.floor((r - 0.12) / 0.05 + 1e-9), np.nan)


def lock_owners(r):
    """The owners' ladder: 11 -> 10, 15 -> 12, 20 -> 17, then every 5 % reached - 3."""
    return np.where(r >= 0.20, 0.17 + 0.05 * np.floor((r - 0.20) / 0.05 + 1e-9),
                    np.where(r >= 0.15, 0.12, np.where(r >= 0.11, 0.10, np.nan)))


def first_true(cond):
    """Index of the first True per row, or the row length when none."""
    any_ = cond.any(axis=1)
    return np.where(any_, cond.argmax(axis=1), cond.shape[1])


def outcomes(P, s, atrf, coin, tfmin, hmax):
    """P: dict of path matrices (rows = signals, cols = minutes from the entry minute): H L C O F (returns vs the entry
    price, F the cumulative funding rate). s: sides (+1 / -1). atrf: ATR / entry price. hmax: usable minutes per row.
    Returns (ret [n, E] float32, t [n, E] int32)."""
    n, W = P["H"].shape
    s2 = s[:, None]
    UP = np.where(s2 > 0, P["H"], -P["L"])
    DN = np.where(s2 > 0, P["L"], -P["H"])
    CL, OP, FC = s2 * P["C"], s2 * P["O"], s2 * P["F"]
    col = np.arange(W)[None, :]
    valid = col < hmax[:, None]
    DN = np.where(valid, DN, np.inf)                     # beyond the data: never hits
    UP = np.where(valid, UP, -np.inf)
    RMU = np.maximum.accumulate(UP, axis=1)
    RMD = np.minimum.accumulate(DN, axis=1)
    RMUp = np.concatenate([np.zeros((n, 1)), RMU[:, :-1]], axis=1)
    rows = np.arange(n)
    ret = np.zeros((n, len(EXITS)), np.float32)
    tt = np.zeros((n, len(EXITS)), np.int32)
    cap = {k: np.minimum(k * tfmin, hmax) - 1 for k in TIMES}
    t_stop = {k: (RMD > -k * atrf[:, None]).sum(1) for k in STOPS}
    t_tgt = {k: (RMU < k * atrf[:, None]).sum(1) for k in TARGETS if k is not None}
    t_act = (RMU < 1.0 * atrf[:, None]).sum(1)
    t_be = first_true((DN <= 0) & (col > t_act[:, None]))

    for e in EXITS:
        j = e["id"]
        tn = cap[e["time"]]
        if e["kind"] == "grid":
            k = e["stop"]
            ts = t_stop[k].copy()
            lvl = np.full(n, -k) * atrf
            if e["be"] is not None:
                use = t_act < ts
                ts = np.where(use, np.minimum(t_be, ts), ts)
                lvl = np.where(use & (t_be <= t_stop[k]), 0.0, lvl)
            tg = t_tgt[e["target"]] if e["target"] is not None else np.full(n, W + 1)
            tgl = (e["target"] or 0.0) * atrf
            t = np.minimum(np.minimum(ts, tg), tn)
            is_stop = (ts <= tg) & (ts <= tn)
            is_tgt = ~is_stop & (tg <= tn)
            tc = np.minimum(t, W - 1)
            v = np.where(is_stop, np.minimum(lvl, OP[rows, tc]), np.where(is_tgt, tgl, CL[rows, tc]))
        else:
            if e["kind"] == "trail":
                stop = -e["stop"] * atrf
                act = RMUp >= e["act"] * atrf[:, None]
                level = np.where(act, RMUp - e["dist"] * atrf[:, None], -np.inf)
                level = np.maximum(level, stop[:, None])
            else:
                lev = e.get("lev") or owners_lev(coin)
                r = lev * (RMUp - COST_RT)
                if e["kind"] == "house":
                    lock = lock_house(r)
                    stop = -e["stop"] * atrf
                else:
                    lock = lock_owners(r)
                    stop = np.full(n, -(0.5 / lev - COST_RT))
                lp = np.where(np.isnan(lock), -np.inf, lock / lev + COST_RT)
                level = np.maximum(lp, stop[:, None])
            th = first_true(DN <= level)
            t = np.minimum(th, tn)
            hit = th <= tn
            tc = np.minimum(t, W - 1)
            v = np.where(hit, np.minimum(level[rows, tc], OP[rows, tc]), CL[rows, tc])
        tc = np.minimum(t, W - 1)
        ret[:, j] = v - COST_RT - FC[rows, tc]
        tt[:, j] = tc
    return ret, tt


def features(coin, tf, df, sg, g):
    """Entry-time features of the signals (all known at the signal bar's close)."""
    k = TF_MIN[tf]
    o, h, l, c, v = (df[x].to_numpy(float) for x in ("open", "high", "low", "close", "volume"))
    ts = df.ts.to_numpy(np.int64)
    day = ts // DAY
    tp = (h + l + c) / 3
    pv = pd.Series(tp * v).groupby(day).cumsum().to_numpy()
    cv = pd.Series(v).groupby(day).cumsum().to_numpy()
    with np.errstate(all="ignore"):
        vw = np.where(cv > 0, pv / cv, np.nan)
    atr, adx = atr_adx(df)
    i = sg.i.to_numpy()
    s = sg.side.to_numpy()
    bc = sg.bar_close.to_numpy(np.int64)
    rng = h[i] - l[i]
    wick = np.where(s < 0, h[i] - np.maximum(o[i], c[i]), np.minimum(o[i], c[i]) - l[i])
    # the break: the newest bar before i in the last 10 of the same day that closed through VWAP the trade's way
    depth = np.full(len(i), np.nan)
    since = np.full(len(i), np.nan)
    for q, (ii, ss) in enumerate(zip(i, s)):
        for j in range(ii - 1, max(ii - 11, 0), -1):
            if day[j] != day[ii]:
                break
            if (ss < 0 and c[j - 1] >= vw[j - 1] and c[j] < vw[j]) or (ss > 0 and c[j - 1] <= vw[j - 1] and c[j] > vw[j]):
                depth[q] = (c[j] - vw[j]) * ss / atr[j]
                since[q] = ii - j
                break
    vol20 = pd.Series(v).rolling(20).mean().shift(1).to_numpy()
    slope_from = np.maximum(i - 4, 0)
    same_day = day[slope_from] == day[i]
    slope = np.where(same_day, (vw[i] - vw[slope_from]) * s / atr[i], np.nan)
    atrp = atr / c
    win = int(30 * 1440 / k)
    q20 = pd.Series(atrp).rolling(win, min_periods=win // 2).quantile(0.2).to_numpy()
    q80 = pd.Series(atrp).rolling(win, min_periods=win // 2).quantile(0.8).to_numpy()
    # the day's range so far (UTC day)
    dhi = pd.Series(h).groupby(day).cummax().to_numpy()
    dlo = pd.Series(l).groupby(day).cummin().to_numpy()
    with np.errstate(all="ignore"):
        dpos = (c[i] - dlo[i]) / (dhi[i] - dlo[i])
    # the judges (research/newlive/judge: the trend bot's four judges on closed 1h / 4h bars)
    Z = np.load(os.path.join(JUDGE_DIR, f"{coin}.npz"))
    jf = {}
    for htf in ("1h", "4h"):
        tc_ = Z[f"{htf}_tclose"]
        jx = np.searchsorted(tc_, bc, side="right") - 1
        okj = (jx >= 0) & (bc - tc_[np.maximum(jx, 0)] < 2 * TF_MIN[htf] * MIN)
        for nm in ("V39", "S6", "OBV", "N12", "raw3"):
            a = Z[f"{htf}_{nm}"].astype(float)[np.maximum(jx, 0)]
            jf[f"j{htf}_{nm}"] = np.where(okj, a * s, np.nan)          # +1 = with the trade, -1 = against
    # 4h EMA50 and daily EMA20 on closed bars, from the 1m grid
    def htf_close(mins):
        n = g["n"] // mins * mins
        cc = g["c"][mins - 1:n:mins]
        tt_ = T0 + (np.arange(len(cc)) + 1) * mins * MIN                 # bar close times
        return tt_, cc
    t4, c4 = htf_close(240)
    e50 = ema(pd.Series(c4).ffill().to_numpy(), 50)
    x4 = np.searchsorted(t4, bc, side="right") - 1
    ema4 = np.sign(c4[x4] - e50[x4]) * s
    td, cd = htf_close(1440)
    e20 = ema(pd.Series(cd).ffill().to_numpy(), 20)
    xd = np.searchsorted(td, bc, side="right") - 1
    emad = np.sign(cd[xd] - e20[xd]) * s
    # the chase block (combo.chase_check) on hourly high / low from the 1m grid
    nh = g["n"] // 60
    hh = np.nanmax(g["h"][:nh * 60].reshape(nh, 60), axis=1)
    ll = np.nanmin(g["l"][:nh * 60].reshape(nh, 60), axis=1)
    r24h = pd.Series(hh).rolling(24, min_periods=20).max().shift(1).to_numpy()
    r24l = pd.Series(ll).rolling(24, min_periods=20).min().shift(1).to_numpy()
    r7h = pd.Series(hh).rolling(168, min_periods=150).max().shift(1).to_numpy()
    r7l = pd.Series(ll).rolling(168, min_periods=150).min().shift(1).to_numpy()
    kh = (bc - T0) // HOUR
    e_px = g["o"][(bc - T0) // MIN]
    with np.errstate(all="ignore"):
        p24 = (e_px - r24l[kh]) / (r24h[kh] - r24l[kh])
        p7 = (e_px - r7l[kh]) / (r7h[kh] - r7l[kh])
    chase = np.where(s > 0, (p24 >= 0.9) | (p7 >= 0.8), (p24 <= 0.1) | (p7 <= 0.2))
    # funding: the latest published rate at or before the bar close, paid by the side when side * rate > 0
    f = g["fund"]
    fidx = np.flatnonzero(f != 0)
    fi = np.searchsorted(fidx, (bc - T0) // MIN, side="right") - 1
    frate = np.where(fi >= 0, f[fidx[np.maximum(fi, 0)]], 0.0)
    kst = pd.to_datetime(bc + KST, unit="ms")
    out = pd.DataFrame({
        "coin": coin, "tf": tf, "side": s, "bar_close": bc, "entry_px": e_px, "atr": atr[i], "atrf": atr[i] / e_px,
        "kst_hour": kst.hour, "kst_dow": kst.dayofweek, "weekend": kst.dayofweek >= 5,
        "vwap_age_h": (bc - day[i] * DAY) / HOUR,
        "wick_frac": np.where(rng > 0, wick / rng, np.nan), "body_atr": np.abs(c[i] - o[i]) / atr[i],
        "close_vwap_atr": (c[i] - vw[i]) * s / atr[i], "brk_depth_atr": depth, "bars_since_brk": since,
        "relvol": v[i] / vol20[i], "vwap_slope_atr": slope, "adx": adx[i],
        "atrp": atrp[i], "atrp_q20": q20[i], "atrp_q80": q80[i], "day_pos": dpos,
        "ema4h50": ema4, "ema1d20": emad, "p24": p24, "p7": p7, "chase": chase, "fund_pay": s * frate > 0, **jf})
    return out


def job(args):
    coin, tf = args
    t0 = time.time()
    g = grid(coin)
    df = bars(coin, tf)
    sg = signals(coin, tf, df)
    sg = sg[(sg.bar_close.to_numpy(np.int64) - T0) // MIN < g["n"] - 1].reset_index(drop=True)   # an entry minute exists
    F = features(coin, tf, df, sg, g)
    k = TF_MIN[tf]
    W = HOLD_BARS * k
    e = ((F.bar_close.to_numpy(np.int64) - T0) // MIN).astype(np.int64)
    ep = F.entry_px.to_numpy()
    hmax = np.minimum(W, g["n"] - e).astype(np.int64)
    n = len(F)
    R = {"ret": np.zeros((n, len(EXITS)), np.float32), "t": np.zeros((n, len(EXITS)), np.int32),
         "ret_o": np.zeros((n, len(EXITS)), np.float32), "t_o": np.zeros((n, len(EXITS)), np.int32)}
    cumf = np.cumsum(g["fund"])
    CH = max(200, int(4_000_000 // W))
    for a in range(0, n, CH):
        b = min(n, a + CH)
        idx = e[a:b, None] + np.arange(W)[None, :]
        idx = np.minimum(idx, g["n"] - 1)
        base = ep[a:b, None]
        P = {"H": g["h"][idx] / base - 1, "L": g["l"][idx] / base - 1, "C": g["c"][idx] / base - 1,
             "O": g["o"][idx] / base - 1, "F": cumf[idx] - cumf[e[a:b] - 1][:, None]}
        s = F.side.to_numpy()[a:b]
        af = F.atrf.to_numpy()[a:b]
        hm = hmax[a:b]
        R["ret"][a:b], R["t"][a:b] = outcomes(P, s, af, coin, k, hm)
        R["ret_o"][a:b], R["t_o"][a:b] = outcomes(P, -s, af, coin, k, hm)
    os.makedirs(os.path.join(OUT, tf), exist_ok=True)
    np.savez(os.path.join(OUT, tf, f"{coin}.npz"), **R)
    F.to_pickle(os.path.join(OUT, tf, f"{coin}_features.pkl"))
    return coin, tf, n, round(time.time() - t0, 1)


if __name__ == "__main__":
    tfs = [a for a in sys.argv[1:] if a in TF_MIN]
    procs = int(sys.argv[sys.argv.index("--procs") + 1]) if "--procs" in sys.argv else 3
    jobs = [(c, tf) for tf in tfs for c in COINS]
    with Pool(procs) as pool:
        for r in pool.imap_unordered(job, jobs):
            print(*r, flush=True)
    json.dump([{k: v for k, v in e.items()} for e in EXITS], open(os.path.join(OUT, "exits.json"), "w"))
