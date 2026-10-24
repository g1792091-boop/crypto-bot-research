"""Shared parts of the friend's 15m EMA / RSI / ROC study (research/friendroc/PREREG.md + PREREG_AMEND1.md): the signals
of P and of the signal variants (V-SLOPE, V-H2, V-ORIG) on 15m bars with the last closed 1h / 4h bars, the entry blocks, and the stop /
ladder walk over the 1m path of every signal (both sides, every exit setting, both costs).

Data: research/newlive's 1m grid (nlcommon.load_grid, to 2026-10-23 00:00 UTC) through research/vwap30/code/vwcommon.py
(bars on the UTC grid). Indicators: the repo's indicator library (paperbot.sweepsig.lib().fg = fg_indicators).
Ladder: paperbot/ladder.py LadderSpec.lock_for semantics (checked against it below), net ROE as ladder.net_roe.
Run with python3 -I (the data files are downloaded data: read as arrays only)."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
VW = os.path.join(REPO, "research", "vwap30", "code")
for _p in (REPO, VW):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from vwcommon import *                                   # grid, bars, COINS, T0, MIN, HOUR, DAY, KST, DATA_END, NL, ms
import numba
from paperbot import sweepsig
from paperbot.ladder import LadderSpec
from paperbot.combo import kst_weekend, us_open_pause
from paperbot import events as EV

OUT = os.path.join(NL.FY.SCR, "friendroc_out")          # heavy outputs (never in the repository)
os.makedirs(OUT, exist_ok=True)
RES_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))   # (vwcommon * rebinds HERE)

SETS = ("P", "SLOPE", "H2", "ORIG")                      # signal definitions (PREREG_AMEND1)
COSTS = {"c042": 2 * (0.00042 + 0.0002), "c060": 2 * (0.0006 + 0.0002)}   # round trip: taker + slippage, each side
EXITS = {                                                # lev, first_lock, step, trigger_gap, cap (minutes; 0 = none)
    "L30": (30.0, 0.10, 0.05, 0.02, 0),
    "L20": (20.0, 0.10, 0.05, 0.02, 0),
    "L10": (30.0, 0.10, 0.05, 0.00, 0),
    "H96": (30.0, 0.10, 0.05, 0.02, 96 * 15),
}
VARIANTS = {                                             # name: (signal set, exit, entry blocks)
    "P": ("P", "L30", True),
    "V-SLOPE": ("SLOPE", "L30", True),
    "V-H2": ("H2", "L30", True),
    "V-ORIG": ("ORIG", "L30", True),
    "V-NOBLOCK": ("P", "L30", False),
    "V-20x": ("P", "L20", True),
    "V-L10": ("P", "L10", True),
    "V-HOLD": ("P", "H96", True),
}
WARM15, WARMH = 200, 60                                  # PREREG: 200 15m bars, 60 bars of each higher timeframe
REASONS = ("stop", "lock", "time", "open")


# ====================================================================== indicators and signals
def _ind(close):
    fg = sweepsig.lib().fg
    c = pd.Series(close)
    return {"e21": fg.ema(c, 21).to_numpy(float), "e52": fg.ema(c, 52).to_numpy(float),
            "rsi": fg.rsi(c, 26).to_numpy(float), "roc": fg.roc(c, 9).to_numpy(float)}


def prev(x):
    return np.r_[np.nan, x[:-1]]


def coin_signals(coin):
    """Every 15m bar of the coin where at least one signal set fires: DataFrame t (bar close = entry minute, ms), coin,
    side, flags P / SLOPE / H2 / ORIG, and the indicator values (for the examples)."""
    df = bars(coin, "15m")
    c = df.close.to_numpy(float)
    I = _ind(c)
    bc = df.ts.to_numpy(np.int64) + 15 * MIN
    with np.errstate(invalid="ignore"):
        e21, e52, rsi, roc = I["e21"], I["e52"], I["rsi"], I["roc"]
        e21p, e52p, rocp = prev(e21), prev(e52), prev(roc)
        ema_up_s = (e21 > e52) & (e21 > e21p) & (e52 > e52p)
        ema_dn_s = (e21 < e52) & (e21 < e21p) & (e52 < e52p)
        ema_up_1, ema_dn_1 = e21 > e52, e21 < e52
        rsi_up, rsi_dn = rsi > 50, rsi < 50
        x_up = (rocp <= 0) & (roc > 0)
        x_dn = (rocp >= 0) & (roc < 0)
    warm = np.arange(len(c)) >= WARM15
    H = {}
    for tf, k in (("1h", 60), ("4h", 240)):
        dh = bars(coin, tf)
        Ih = _ind(dh.close.to_numpy(float))
        hc = dh.ts.to_numpy(np.int64) + k * MIN                   # the higher bar's close time
        j = np.searchsorted(hc, bc, side="right") - 1                # the last one closed at (or before) the 15m close
        ok = j >= WARMH
        jj = np.maximum(j, 1)
        r, rp, rs = Ih["roc"][jj], Ih["roc"][jj - 1], Ih["rsi"][jj]
        r, rp, rs = (np.where(ok, v, np.nan) for v in (r, rp, rs))
        H[tf] = {"ok": ok, "roc": r, "rocp": rp, "rsi": rs, "ts": np.where(ok, dh.ts.to_numpy(np.int64)[jj], -1)}
    with np.errstate(invalid="ignore"):
        hp_up = (H["1h"]["roc"] > 0) | (H["4h"]["roc"] > 0)
        hp_dn = (H["1h"]["roc"] < 0) | (H["4h"]["roc"] < 0)
        h2_up = (H["1h"]["roc"] > H["1h"]["rocp"]) | (H["4h"]["roc"] > H["4h"]["rocp"])
        h2_dn = (H["1h"]["roc"] < H["1h"]["rocp"]) | (H["4h"]["roc"] < H["4h"]["rocp"])
        ho_up = ((H["1h"]["rsi"] > 50) & (H["1h"]["roc"] > 0)) | ((H["4h"]["rsi"] > 50) & (H["4h"]["roc"] > 0))
        ho_dn = ((H["1h"]["rsi"] < 50) & (H["1h"]["roc"] < 0)) | ((H["4h"]["rsi"] < 50) & (H["4h"]["roc"] < 0))
    base_up = warm & rsi_up & x_up
    base_dn = warm & rsi_dn & x_dn
    # PREREG_AMEND1: P = EMA21 > EMA52 only; the slope form is V-SLOPE; V-H2 / V-ORIG change only the higher bars
    L = {"P": base_up & ema_up_1 & hp_up, "SLOPE": base_up & ema_up_s & hp_up,
         "H2": base_up & ema_up_1 & h2_up, "ORIG": base_up & ema_up_1 & ho_up}
    S = {"P": base_dn & ema_dn_1 & hp_dn, "SLOPE": base_dn & ema_dn_s & hp_dn,
         "H2": base_dn & ema_dn_1 & h2_dn, "ORIG": base_dn & ema_dn_1 & ho_dn}
    anyl = np.logical_or.reduce([L[q] for q in SETS])
    anys = np.logical_or.reduce([S[q] for q in SETS])
    assert not (anyl & anys).any()                               # a bar is long or short, never both (ROC cross)
    g = grid(coin)
    e = (bc - T0) // MIN
    i = np.flatnonzero((anyl | anys) & (e < g["n"]))              # an entry minute exists
    side = np.where(anyl[i], 1, -1)
    R = pd.DataFrame({"t": bc[i], "coin": COINS.index(coin), "side": side, "e": e[i]})
    for q in SETS:
        R[q] = np.where(side > 0, L[q][i], S[q][i])
    R["bar_open"] = df.ts.to_numpy(np.int64)[i]
    R["close"] = c[i]
    for nm, v in (("e21", e21), ("e21p", e21p), ("e52", e52), ("e52p", e52p), ("rsi", rsi), ("roc", roc), ("rocp", rocp)):
        R[nm] = v[i]
    for tf in ("1h", "4h"):
        for nm in ("ts", "roc", "rocp", "rsi"):
            R[f"{tf}_{nm}"] = H[tf][nm][i]
    R["entry_px"] = g["o"][R.e.to_numpy()]
    return R


def blocked(t):
    """'' or why an entry at minute t (ms) is blocked (the owners' bots: KST weekend, US macro +-30 min, NYSE open
    -30 / +30 min)."""
    if kst_weekend(int(t)):
        return "weekend"
    if EV.near(int(t), 30 * MIN, 30 * MIN):
        return "macro"
    if us_open_pause(int(t), 30, 30):
        return "us_open"
    return ""


# ====================================================================== the ladder and the walk over 1m bars
@numba.njit
def lock_for(best, first_lock, step, gap):
    """paperbot/ladder.py LadderSpec.lock_for: the highest lock armed by best net ROE, NaN below the first trigger."""
    ft = first_lock + gap
    if not best >= ft - 1e-12:
        return np.nan
    n = np.floor((best - ft) / step + 1e-9)
    return first_lock + step * n


def check_lock():
    """lock_for == LadderSpec.lock_for on a dense grid, for both ladders of the study."""
    for fl, st, gp in {(v[1], v[2], v[3]) for v in EXITS.values()}:
        spec = LadderSpec(first_lock=fl, step=st, trigger_gap=gp)
        for b in np.r_[np.linspace(-0.6, 1.5, 4201), [0.10, 0.12, 0.15, 0.17, 0.20, 0.22]]:
            a, w = lock_for(float(b), fl, st, gp), spec.lock_for(float(b))
            assert (w is None and np.isnan(a)) or (w is not None and abs(a - w) < 1e-12), (fl, st, gp, b, a, w)
    return True


@numba.njit
def walk(o, h, l, c, cumf, es, s, lev, cost, first_lock, step, gap, cap, n):
    """One trade per entry minute es[q], side s: the net ROE -50 % stop and the ladder (armed by the best net ROE up to
    the previous minute), filled at the level or at the minute's open when it gapped past; cap minutes (0 = none);
    the data end marks an open trade at the last close. Net = side x price change - round trip - funding paid
    (ladder.net_roe / lev). Returns net price return (floored at -1/lev: the margin), exit minute offset, reason
    (0 stop, 1 lock, 2 time, 3 open), lowest net ROE before the exit (the exit minute at its fill), best net ROE."""
    m = len(es)
    ret = np.zeros(m)
    kk = np.zeros(m, np.int64)
    why = np.zeros(m, np.int8)
    mae = np.zeros(m)
    mfe = np.zeros(m)
    for q in range(m):
        e = es[q]
        p0 = o[e]
        f0 = cumf[e - 1]
        best = -1e9
        lk = np.nan
        worst = 1e9
        k = 0
        done = False
        while not done:
            i = e + k
            if i >= n:                                           # data end: open, marked at the last close
                i = n - 1
                F = s * (cumf[i] - f0)
                ret[q] = s * (c[i] / p0 - 1.0) - cost - F
                kk[q] = i - e
                why[q] = 3
                done = True
                break
            Fp = s * (cumf[i - 1] - f0)
            level = -0.5 / lev + cost + Fp
            locked = not np.isnan(lk)
            if locked:
                lv = lk / lev + cost + Fp
                if lv > level:
                    level = lv
            if s > 0:
                up = h[i] / p0 - 1.0
                dn = l[i] / p0 - 1.0
            else:
                up = 1.0 - l[i] / p0
                dn = 1.0 - h[i] / p0
            op = s * (o[i] / p0 - 1.0)
            F = s * (cumf[i] - f0)
            if dn <= level:
                fill = level if level < op else op
                ret[q] = fill - cost - F
                kk[q] = k
                why[q] = 1 if locked else 0
                done = True
                break
            r_dn = lev * (dn - cost - Fp)
            if r_dn < worst:
                worst = r_dn
            if cap > 0 and k == cap - 1:
                ret[q] = s * (c[i] / p0 - 1.0) - cost - F
                kk[q] = k
                why[q] = 2
                done = True
                break
            r_up = lev * (up - cost - F)
            if r_up > best:
                best = r_up
                lk = lock_for(best, first_lock, step, gap)
            k += 1
        if ret[q] < -1.0 / lev:
            ret[q] = -1.0 / lev
        r_ex = lev * ret[q]
        mae[q] = r_ex if r_ex < worst else worst
        mfe[q] = best
    return ret, kk, why, mae, mfe


def coin_outcomes(coin, R):
    """Columns <exit>_<cost>_<own|opp>_{r,k,why,mae} for the coin's signal rows (both sides: the coin-flip twin)."""
    g = grid(coin)
    cumf = np.cumsum(g["fund"])
    o, h, l, c = (np.ascontiguousarray(g[x], dtype=np.float64) for x in ("o", "h", "l", "c"))
    es = R.e.to_numpy(np.int64)
    out = {}
    for xn, (lev, fl, st, gp, cap) in EXITS.items():
        for cn, cost in COSTS.items():
            for sn, sg in (("own", 1), ("opp", -1)):
                pre = f"{xn}_{cn}_{sn}"
                r = np.zeros(len(es)); k = np.zeros(len(es), np.int64); w = np.zeros(len(es), np.int8)
                ma = np.zeros(len(es)); mf = np.zeros(len(es))
                for side in (1, -1):
                    m = (R.side.to_numpy() * sg) == side
                    if m.any():
                        a = walk(o, h, l, c, cumf, es[m], side, lev, cost, fl, st, gp, cap, g["n"])
                        r[m], k[m], w[m], ma[m], mf[m] = a
                out[f"{pre}_r"], out[f"{pre}_k"], out[f"{pre}_why"], out[f"{pre}_mae"] = r, k, w, ma
                out[f"{pre}_mfe"] = mf.astype(np.float32)
    return pd.DataFrame(out, index=R.index)
