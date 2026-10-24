"""Shared parts of the friend's second design (analysis/review1024/friend2/PLAN.md): data (frcore's 1m grid + the rule bot's
live_bars.csv extension), indicators (OBV / SMA30, RSI26, MOM10, ROC9, TradingView Klinger 34/55/13, EMA21/52, supertrend
10/3), the 48 signal families, the stop / ladder walk with MAE, and the account helpers.

Run every script with python3 -I (the export is untrusted data: read as CSV only)."""
import os, sys
_F2 = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_F2, "..", "..", ".."))
FR = os.path.join(_REPO, "research", "friendroc", "code")
for _p in (FR, _F2):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from frcore import *                                      # grid, bars, COINS, T0, MIN, HOUR, DAY, KST, DATA_END, NL, ms, blocked, lock_for
import vwcommon                                           # (its grid cache is extended below)
from frdeep import walk3
from frrun import take, rnd
from frp30 import weekdays
import math

F2_DIR = _F2                                              # (frcore's star import rebinds HERE / REPO)
REPO = _REPO
SCR = os.path.join(NL.FY.SCR, "friend2")                 # heavy outputs (session scratchpad, never in the repository)
os.makedirs(SCR, exist_ok=True)
LIVE_CSV = os.path.join(SCR, "export", "current__live_bars.csv")
END2 = ms("2026-10-24 14:00")                             # the extension's end (exclusive, a whole hour)
OVERLAP_TOL, OVERLAP_SHARE = 0.0005, 0.99

TFS = ("15m", "30m", "1h")
HTF = {"15m": "1h", "30m": "1h", "1h": "4h"}             # placement A
ALL_TF = ("15m", "30m", "1h", "4h")
WARM = 200
KR_N = 3

TAKER, SLIP = 0.00042, 0.0002
COST = 2 * (TAKER + SLIP)                                 # 0.124 % round trip
FL, STEP, GAP = 0.10, 0.05, 0.02                          # the ladder: net ROE 12 % locks 10 %, then 5 % steps
LEVS = (35.0, 20.0)
STOPS = (-0.15, -0.20, -0.30, -0.50)
EXITS = [(lev, sl) for lev in LEVS for sl in STOPS]
def xname(lev, sl):
    return f"{int(lev)}x{int(round(sl * 100))}"
XN = [xname(*x) for x in EXITS]
def refund(lev):
    return lev * 2 * TAKER * 0.9                          # the TetherMax payback per trade, as ROE

MARGINS = (0.40, 0.10)
DRAWS, SEED = 2000, 20261024
BH_Q = 0.025

PERIODS = {
    "select": (ms("2021-01-01"), ms("2024-01-01")),
    "confirm": (ms("2024-01-01"), ms("2026-10-01")),
    "y2026": (ms("2026-01-01"), ms("2026-10-23")),
    "oct": (ms("2026-10-01"), ms("2026-10-23")),
    "last19": (ms("2026-10-04"), ms("2026-10-23")),
    "ext": (ms("2026-10-04"), END2),
    "ext_only": (ms("2026-10-23"), END2),
}


# ====================================================================== families
def families():
    """name -> dict(design, tf, trend, place, trig). 48 families (PLAN 3)."""
    F = {}
    for tf in TFS:
        for pl in ("A", "B"):
            for tr in ("K", "R", "KR"):
                F[f"F-{tf}-{pl}-{tr}"] = dict(design="F", tf=tf, trend="T", place=pl, trig=tr)
        F[f"G-{tf}"] = dict(design="G", tf=tf, trend="-", place="B", trig="G")
        for vt in ("V", "VO"):
            for pl in ("A", "B"):
                for tr in ("K", "R"):
                    F[f"{vt}-{tf}-{pl}-{tr}"] = dict(design="V", tf=tf, trend=vt, place=pl, trig=tr)
        F[f"O-{tf}"] = dict(design="O", tf=tf, trend="RMR", place="B", trig="O")
    return F
FAMS = families()
assert len(FAMS) == 48


# ====================================================================== data: the extension
_EXT_INFO = {}


def extend_grid(coin, live=None):
    """frcore's grid of the coin extended to END2 with the export's 1m bars (o h l c v; funding 0), after the overlap
    check (PLAN 0). Returns the check numbers; with use=False the grid is left as it is."""
    if coin in _EXT_INFO:
        return _EXT_INFO[coin]
    g = grid(coin)
    if live is None:
        live = pd.read_csv(LIVE_CSV, usecols=["ts", "symbol", "open", "high", "low", "close", "volume"])
    d = live[live.symbol == coin].sort_values("ts")
    ts = d.ts.to_numpy(np.int64)
    assert (ts % MIN == 0).all() and (np.diff(ts) > 0).all()
    n0 = g["n"]
    assert T0 + n0 * MIN == DATA_END
    j = (ts - T0) // MIN
    ov = (j >= 0) & (j < n0)
    gc = g["c"][j[ov]]
    rel = np.abs(d.close.to_numpy(float)[ov] / gc - 1)
    share = float((rel <= OVERLAP_TOL).mean())
    n1 = (END2 - T0) // MIN
    new = (j >= n0) & (j < n1)
    full = int(new.sum()) == n1 - n0 and (np.diff(j[new]) == 1).all()
    info = {"overlap_minutes": int(ov.sum()), "overlap_share_within_005pct": round(share, 6),
            "overlap_max_rel_diff": float(rel.max()) if len(rel) else None,
            "overlap_vol_ratio_median": float(np.median(d.volume.to_numpy(float)[ov] / np.maximum(g["v"][j[ov]], 1e-12))),
            "ext_minutes": int(new.sum()), "ext_complete": bool(full),
            "use": bool(share >= OVERLAP_SHARE and full)}
    if info["use"]:
        add = {"o": d.open, "h": d.high, "l": d.low, "c": d.close, "v": d.volume}
        out = {}
        for k in ("o", "h", "l", "c", "v"):
            out[k] = np.r_[g[k], add[k].to_numpy(float)[new]]
        out["fund"] = np.r_[g["fund"], np.zeros(n1 - n0)]
        vwcommon._GRID[coin] = out | {"first": g["first"], "n": int(n1)}
    _EXT_INFO[coin] = info
    return info


def data_end():
    return T0 + grid(COINS[0])["n"] * MIN


# ====================================================================== indicators
@numba.njit(cache=True)
def pine_ema_nb(x, n):
    """Pine ta.ema: alpha 2/(n+1), seeded with the SMA of the first n consecutive finite values; a NaN later keeps the
    previous value (pine_indicators._recursive_ma)."""
    m = len(x)
    out = np.full(m, np.nan)
    alpha = 2.0 / (n + 1.0)
    cnt = 0
    s = -1
    for i in range(m):
        if np.isfinite(x[i]):
            cnt += 1
        else:
            cnt = 0
        if cnt >= n:
            s = i
            break
    if s < 0:
        return out
    acc = 0.0
    for i in range(s - n + 1, s + 1):
        acc += x[i]
    out[s] = acc / n
    for i in range(s + 1, m):
        v = x[i]
        if np.isfinite(v):
            out[i] = alpha * v + (1.0 - alpha) * out[i - 1]
        else:
            out[i] = out[i - 1]
    return out


def klinger_tv(h, l, c, v, fast=34, slow=55, sig=13):
    """TradingView's built-in Klinger Oscillator: sv = change(hlc3) >= 0 ? volume : -volume; kvo = ema(sv, 34) -
    ema(sv, 55); signal = ema(kvo, 13)."""
    hlc3 = (np.asarray(h, float) + np.asarray(l, float) + np.asarray(c, float)) / 3.0
    ch = np.r_[np.nan, np.diff(hlc3)]
    with np.errstate(invalid="ignore"):
        sv = np.where(ch >= 0, np.asarray(v, float), -np.asarray(v, float))
    kvo = pine_ema_nb(sv, fast) - pine_ema_nb(sv, slow)
    return kvo, pine_ema_nb(kvo, sig)


def klinger_ref(h, l, c, v, fast=34, slow=55, sig=13):
    """The same formula written as a plain loop (unit check)."""
    n = len(c)
    sv = [0.0] * n
    for i in range(n):
        x = (h[i] + l[i] + c[i]) / 3.0
        if i == 0:
            sv[i] = -float(v[i])                          # change(hlc3) is na on the first bar: na >= 0 is false
        else:
            px = (h[i - 1] + l[i - 1] + c[i - 1]) / 3.0
            sv[i] = float(v[i]) if x - px >= 0 else -float(v[i])

    def ema(xs, ln):
        out = [math.nan] * n
        a = 2.0 / (ln + 1)
        run = 0
        for i in range(n):
            run = run + 1 if math.isfinite(xs[i]) else 0
            if run == ln:
                out[i] = sum(xs[i - ln + 1:i + 1]) / ln
                for k in range(i + 1, n):
                    out[k] = a * xs[k] + (1 - a) * out[k - 1] if math.isfinite(xs[k]) else out[k - 1]
                return out
        return out
    e1, e2 = ema(sv, fast), ema(sv, slow)
    kvo = [x - y for x, y in zip(e1, e2)]
    return np.array(kvo), np.array(ema(kvo, sig))


def prev(x, k=1):
    out = np.full(len(x), np.nan)
    out[k:] = x[:-k]
    return out


def tf_frame(coin, tf):
    """Indicator states of the coin's tf bars: dict of arrays (ts open, close time, states +1/-1/0, cross events)."""
    L = sweepsig.lib()
    fg, pi = L.fg, L.pi
    df = bars(coin, tf)
    h, l, c, v = (df[k].to_numpy(float) for k in ("high", "low", "close", "volume"))
    cs = pd.Series(c)
    o = np.asarray(pi.obv(c, v), float)
    om = np.asarray(pi.pine_sma(o, 30), float)
    rsi = fg.rsi(cs, 26).to_numpy(float)
    mom = c - prev(c, 10)
    roc = fg.roc(cs, 9).to_numpy(float)
    kvo, ksg = klinger_tv(h, l, c, v)
    e21, e52 = fg.ema(cs, 21).to_numpy(float), fg.ema(cs, 52).to_numpy(float)
    _line, d3 = pi.exchange_supertrend(h, l, c, 10, 3.0)
    d3 = np.asarray(d3, np.int8)
    sg = lambda up, dn: np.where(up, 1, np.where(dn, -1, 0)).astype(np.int8)
    with np.errstate(invalid="ignore"):
        obv = sg(o > om, o < om)
        rs = sg(rsi > 50, rsi < 50)
        mo = sg(mom > 0, mom < 0)
        T = sg((obv == 1) & (rs == 1) & (mo == 1), (obv == -1) & (rs == -1) & (mo == -1))
        V = d3.copy()
        VO = np.where(d3 == obv, d3, 0).astype(np.int8)
        RMR = sg((roc > 0) & (mom > 0) & (rsi > 50), (roc < 0) & (mom < 0) & (rsi < 50))
        kp, sp, rp = prev(kvo), prev(ksg), prev(roc)
        K = sg((kp <= sp) & (kvo > ksg), (kp >= sp) & (kvo < ksg))
        R = sg((rp <= 0) & (roc > 0), (rp >= 0) & (roc < 0))
        st = sg((e21 > e52) & (rsi > 50), (e21 < e52) & (rsi < 50))
        stp = np.r_[0, st[:-1]]
        G = np.where((st != 0) & (st != stp), st, 0).astype(np.int8)
        omp, op_ = prev(om), prev(o)
        OX = sg((op_ <= omp) & (o > om), (op_ >= omp) & (o < om))
    # KR: K and R the same way within the last KR_N bars, the later of the two on this bar
    def recent(x, s):
        y = (x == s).astype(np.int8)
        out = y.copy()
        for k in range(1, KR_N):
            out[k:] |= y[:-k]
        return out.astype(bool)
    KR = np.zeros(len(c), np.int8)
    for s in (1, -1):
        hit = ((K == s) & recent(R, s)) | ((R == s) & recent(K, s))
        KR[hit] = s
    warm = np.arange(len(c)) >= WARM
    ok = warm & np.isfinite(kvo) & np.isfinite(ksg) & np.isfinite(om) & np.isfinite(rsi) & np.isfinite(e52)
    for a in (T, V, VO, RMR, K, R, KR, G, OX):
        a[~ok] = 0
    k = vwcommon.TF_MIN[tf]
    return {"ts": df.ts.to_numpy(np.int64), "tclose": df.ts.to_numpy(np.int64) + k * MIN, "T": T, "V": V, "VO": VO,
            "RMR": RMR, "K": K, "R": R, "KR": KR, "G": G, "OX": OX, "n": len(c)}


def family_sides(fam, E, H):
    """+1 / -1 / 0 per entry-tf bar of the family; E = the entry tf frame, H = its placement-A tf frame (aligned)."""
    trig = {"K": E["K"], "R": E["R"], "KR": E["KR"], "G": E["G"], "O": E["OX"]}[fam["trig"]]
    if fam["design"] == "G":
        return trig.copy()
    if fam["design"] == "O":
        return np.where(trig == E["RMR"], trig, 0).astype(np.int8)
    tr = (H if fam["place"] == "A" else E)[fam["trend"]]
    return np.where(trig == tr, trig, 0).astype(np.int8)


def align(H, tclose):
    """The higher frame's states at the last higher bar closed at or before each time in tclose (0 if none / warm-up)."""
    j = np.searchsorted(H["tclose"], tclose, side="right") - 1
    ok = j >= 0
    jj = np.maximum(j, 0)
    return {k: np.where(ok, H[k][jj], 0).astype(np.int8) for k in ("T", "V", "VO", "RMR")}


# ====================================================================== the walk (frdeep.walk3 without the fixes, + MAE)
@numba.njit(cache=True)
def walk4(o, h, l, c, cumf, es, s, lev, cost, first_lock, step, gap, roe_stop, n):
    """frdeep.walk3 with no time / break-even / cancel / BTC exit: the net ROE stop roe_stop and the ladder (armed by the
    best net ROE up to the previous minute), filled at the level or at the minute's open when it gapped past; data end =
    open, marked at the last close. Returns net price return (floored at -1/lev), exit minute offset, reason
    (0 stop, 1 lock, 3 open) and MAE as screen ROE (lev x the worst side-adjusted low / high move before the exit
    minute, the exit minute at its fill)."""
    m = len(es)
    ret = np.zeros(m)
    kk = np.zeros(m, np.int64)
    why = np.zeros(m, np.int8)
    mae = np.zeros(m)
    for q in range(m):
        e = es[q]
        p0 = o[e]
        f0 = cumf[e - 1]
        best = -1e9
        lk = np.nan
        worst = 0.0
        k = 0
        while True:
            i = e + k
            if i >= n:
                i = n - 1
                F = s * (cumf[i] - f0)
                ret[q] = s * (c[i] / p0 - 1.0) - cost - F
                kk[q] = i - e
                why[q] = 3
                break
            Fp = s * (cumf[i - 1] - f0)
            F = s * (cumf[i] - f0)
            locked = not np.isnan(lk)
            op = s * (o[i] / p0 - 1.0)
            level = roe_stop / lev + cost + Fp
            rs = 0
            if locked:
                lv = lk / lev + cost + Fp
                if lv > level:
                    level = lv
                    rs = 1
            if s > 0:
                up = h[i] / p0 - 1.0
                dn = l[i] / p0 - 1.0
            else:
                up = 1.0 - l[i] / p0
                dn = 1.0 - h[i] / p0
            if dn <= level:
                fill = level if level < op else op
                ret[q] = fill - cost - F
                kk[q] = k
                why[q] = rs
                if lev * fill < worst:
                    worst = lev * fill
                break
            if lev * dn < worst:
                worst = lev * dn
            r_up = lev * (up - cost - F)
            if r_up > best:
                best = r_up
                lk = lock_for(best, first_lock, step, gap)
            k += 1
        if ret[q] < -1.0 / lev:
            ret[q] = -1.0 / lev
        mae[q] = worst
    return ret, kk, why, mae


# ====================================================================== account helpers
def acct_stats(t, roe, roe0, k, why, mae, margins=MARGINS):
    """Numbers of the trades taken (in entry order): roe with payback, roe0 without."""
    n = len(roe)
    if not n:
        return {"n": 0}
    w, lo = roe[roe > 0], roe[roe <= 0]
    out = {"n": int(n), "win": rnd((roe > 0).mean(), 4),
           "avg_win_pct": rnd(w.mean() * 100, 2) if len(w) else None,
           "avg_loss_pct": rnd(lo.mean() * 100, 2) if len(lo) else None,
           "breakeven_win": rnd(-lo.mean() / (w.mean() - lo.mean()), 4) if len(w) and len(lo) else None,
           "roe_pct": rnd(roe.mean() * 100, 3), "roe_pct_no_payback": rnd(roe0.mean() * 100, 3),
           "stop_share": rnd((why == 0).mean(), 4), "lock_share": rnd((why == 1).mean(), 4), "open_at_end": int((why == 3).sum()),
           "hold_min_median": int(np.median(k + 1)),
           "mae_median_pct": rnd(np.median(mae) * 100, 2),
           "win_mae_below_m12": rnd((mae[roe > 0] < -0.12).mean(), 4) if len(w) else None,
           "win_mae_median_pct": rnd(np.median(mae[roe > 0]) * 100, 2) if len(w) else None}
    for mg in margins:
        x = np.maximum(mg * roe, -1.0)
        eq = np.cumprod(1 + x)
        dd = float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min())
        out[f"mult{int(mg * 100)}"] = rnd(eq[-1], 4)
        out[f"maxdd{int(mg * 100)}"] = rnd(dd, 4)
    return out


@numba.njit(cache=True)
def _take_nb(entry, exit_t, use):
    n = len(entry)
    out = np.empty(n, np.int64)
    k = 0
    free = -1
    for i in range(n):
        if not use[i] or entry[i] < free:
            continue
        out[k] = i
        k += 1
        free = exit_t[i]
    return out[:k]


@numba.njit(cache=True)
def _twin_one(t, r1, r2, k1, k2, f, lev):
    n = len(t)
    free = -1
    s = 0.0
    cnt = 0
    for i in range(n):
        if t[i] < free:
            continue
        if f[i]:
            r, k = r2[i], k2[i]
        else:
            r, k = r1[i], k1[i]
        s += lev * r
        cnt += 1
        free = t[i] + (k + 1) * 60000
    return s / cnt if cnt else np.nan


def twin(t, m, own_r, own_k, opp_r, opp_k, lev, obs_mean0):
    """frrun.coin_flip's coin-flip twin (same rng use: one rng.random per candidate per draw, seed 20261024, 2,000
    draws) on the period's candidates m; obs_mean0 = the strategy's per-trade net ROE without payback. Returns where
    the strategy sits (share of draws below), the draws' mean / sd / 97.5 % point and the normal one-sided p."""
    rng = np.random.default_rng(SEED)
    j = np.flatnonzero(m)
    if not len(j):
        return None
    tt = t[j]
    r1, r2 = own_r[j].astype(np.float64), opp_r[j].astype(np.float64)
    k1, k2 = own_k[j].astype(np.int64), opp_k[j].astype(np.int64)
    tm = np.empty(DRAWS)
    for d in range(DRAWS):
        f = rng.random(len(j)) < 0.5
        tm[d] = _twin_one(tt, r1, r2, k1, k2, f, lev)
    mu, sd = float(np.nanmean(tm)), float(np.nanstd(tm, ddof=1))
    z = (obs_mean0 - mu) / sd if sd > 0 else 0.0
    p = 0.5 * math.erfc(z / math.sqrt(2))
    return {"pct_below": rnd(float((tm < obs_mean0).mean()), 4), "mean_pct": rnd(mu * 100, 3), "sd_pct": rnd(sd * 100, 3),
            "p975_pct": rnd(float(np.nanpercentile(tm, 97.5)) * 100, 3), "z": rnd(z, 3), "p_norm": p,
            "p_emp": (1 + int((tm >= obs_mean0).sum())) / (DRAWS + 1)}


def bh_adjust(p):
    p = np.asarray(p, float)
    m = len(p)
    o = np.argsort(p)
    adj = np.empty(m)
    run = 1.0
    for rank in range(m, 0, -1):
        i = o[rank - 1]
        run = min(run, p[i] * m / rank)
        adj[i] = run
    return adj
