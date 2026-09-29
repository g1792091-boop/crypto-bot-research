"""Tiered-leverage single-account simulator with planted edges on real IS bar paths.

Reads ONLY sweep/data/is/<sym>-<tf>.csv (bars < 2024-07-01).  Never touches oos/ or final/.
Units: fractions (0.0005 = 0.05 %).  All sizing is a fraction of current equity, so per-trade equity
returns compound multiplicatively and do not depend on the equity level.
"""
from __future__ import annotations

import os
import numpy as np
import pandas as pd
from scipy.signal import lfilter

SCR = "/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad"
IS_DIR = os.path.join(SCR, "sweep", "data", "is")
COINS = ["btcusd", "ethusd", "solusd", "xrpusd", "dogeusd", "ltcusd", "bchusd"]
TF_MIN = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
LAM = {"5m": 6.0, "15m": 4.0, "1h": 1.5, "4h": 3.0 / 7, "1d": 1.5 / 7}   # candidate signals / day, whole 7-coin universe
HMAX = 64                                                                  # time exit (bars)
WIN_START = pd.Timestamp("2021-08-01", tz="UTC")
WIN_END = pd.Timestamp("2024-07-01", tz="UTC")

# ---- Binance USDT-M cost / margin model (all on notional)
FEE = 0.0005        # taker, every fill
SLIP = 0.0002       # every market fill (entry, stop, time exit)
FUND_8H = 0.0001    # funding per 8 h, charged as a cost regardless of side
MMR = 0.005         # maintenance margin rate -> liquidation at 1/L - MMR adverse
C_IN = FEE + SLIP
C_OUT_MKT = FEE + SLIP
C_OUT_TP = FEE      # TP = order resting at the TP price: taker fee charged (conservative), no slippage

# ---- tiers by setup score s ~ U(0,1)
TIER_CUT = (0.70, 0.90)          # s >= 0.9 -> perfect (top 10 %), 0.7 <= s < 0.9 -> good (next 20 %), else normal
USER_L = np.array([20.0, 30.0, 50.0])
USER_M = np.array([0.20, 0.30, 0.40])
REC_L = 10.0
REC_RISK = np.array([0.01, 0.01, 0.02])
REC_NCAP = 10.0


def load_tf(tf: str):
    out = {}
    for c in COINS:
        p = os.path.join(IS_DIR, f"{c}-{tf}.csv")
        assert "/data/is/" in p and "/oos/" not in p and "/final/" not in p
        df = pd.read_csv(p)
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df[df["ts"] < WIN_END].reset_index(drop=True)
        out[c] = df
    return out


def rma(x: np.ndarray, n: int) -> np.ndarray:
    """Wilder RMA seeded with the SMA of the first n values."""
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    a = 1.0 / n
    s0 = float(np.mean(x[:n]))
    out[n - 1] = s0
    y, _ = lfilter([a], [1.0, -(1.0 - a)], x[n:], zi=[(1.0 - a) * s0])
    out[n:] = y
    return out


def atr_frac(h, l, c, n=14):
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    tr[0] = h[0] - l[0]
    return rma(tr, n) / c


class Panel:
    def __init__(self, tf: str, fine: bool = False):
        """fine=True: exits are resolved on the 5m sub-bars inside each TF bar (ATR, signal, edge horizon and
        time exit stay on the TF).  Candidates need a gap-free 5m path over the whole 64-TF-bar window."""
        self.tf, self.tfm, self.lam = tf, TF_MIN[tf], LAM[tf]
        self.fine = fine and tf != "5m"
        self.m = self.tfm // 5 if self.fine else 1
        H = HMAX
        dfs = load_tf(tf)
        d5 = load_tf("5m") if self.fine else None
        step = np.int64(self.tfm * 60 * 10**9)
        self.coin = {}
        grids = []
        for c in COINS:
            df = dfs[c]
            ts = df["ts"].values.astype("datetime64[ns]").astype(np.int64)
            o, h, l, cl = (df[k].values.astype(np.float64) for k in ("open", "high", "low", "close"))
            a = atr_frac(h, l, cl)
            n = len(df)
            t = np.arange(n)
            ok = t + H < n
            tH = np.minimum(t + H, n - 1)
            ok &= ts[tH] - ts == H * step          # no gap inside the 64-bar path
            ok &= ts >= WIN_START.value
            ok &= t >= 50
            ok &= np.isfinite(a) & (a > 0)
            rec = dict(ts=ts, o=o, h=h, l=l, c=cl, atr=a, ok=ok, n=n)
            if self.fine:
                f = d5[c]
                ts5 = f["ts"].values.astype("datetime64[ns]").astype(np.int64)
                n5 = len(ts5)
                W = H * self.m
                t1 = np.minimum(t + 1, n - 1)
                p5 = np.searchsorted(ts5, ts[t1])
                p5c = np.minimum(p5, n5 - 1)
                pe = np.minimum(p5 + W - 1, n5 - 1)
                ok &= (p5 < n5) & (ts5[p5c] == ts[t1]) & (p5 + W - 1 < n5) & (ts5[pe] - ts5[p5c] == (W - 1) * 300 * 10**9)
                rec.update(p5=p5c, o5=f["open"].values.astype(np.float64), h5=f["high"].values.astype(np.float64),
                           l5=f["low"].values.astype(np.float64), c5=f["close"].values.astype(np.float64))
                rec["ok"] = ok
            self.coin[c] = rec
            grids.append(ts[ok])
        g = np.unique(np.concatenate(grids))
        self.grid = g
        idx = np.full((len(g), len(COINS)), -1, dtype=np.int64)
        for ci, c in enumerate(COINS):
            d = self.coin[c]
            pos = np.where(d["ok"])[0]
            idx[np.searchsorted(g, d["ts"][pos]), ci] = pos
        self.idx = idx
        self.nadm = (idx >= 0).sum(1)
        self.bars_per_day = 1440 / self.tfm
        self.day0 = WIN_START.value
        self.ndays = int((WIN_END.value - WIN_START.value) // (86400 * 10**9))

    def fwd_abs(self, h: int):
        """per-coin E|r_h| (entry = open t+1, exit = close t+h) over admissible bars."""
        out = {}
        for c in COINS:
            d = self.coin[c]
            t = np.where(d["ok"])[0]
            r = d["c"][t + h] / d["o"][t + 1] - 1.0
            out[c] = float(np.mean(np.abs(r)))
        return out

    def draw_candidates(self, rng):
        p = self.lam / self.bars_per_day
        gi = np.where(rng.random(len(self.grid)) < p)[0]
        k = self.nadm[gi]
        pick = (rng.random(len(gi)) * k).astype(np.int64)
        adm = self.idx[gi] >= 0
        csum = np.cumsum(adm, axis=1) - 1
        ci = np.argmax((csum == pick[:, None]) & adm, axis=1).astype(np.int64)
        ti = self.idx[gi, ci]
        return gi, ci, ti

    def paths(self, ci, ti, he: int):
        if self.fine:
            return self.paths_fine(ci, ti, he)
        H = HMAX
        n = len(ci)
        O = np.empty((n, H)); Hh = np.empty((n, H)); Lw = np.empty((n, H)); C = np.empty((n, H))
        atr = np.empty(n); rhe = np.empty(n); tsb = np.empty((n, H), dtype=np.int64)
        for k, c in enumerate(COINS):
            m = ci == k
            if not m.any():
                continue
            d = self.coin[c]
            t = ti[m]
            j = t[:, None] + np.arange(1, H + 1)[None, :]
            O[m] = d["o"][j]; Hh[m] = d["h"][j]; Lw[m] = d["l"][j]; C[m] = d["c"][j]
            tsb[m] = d["ts"][j]
            atr[m] = d["atr"][t]
            rhe[m] = d["c"][t + he] / d["o"][t + 1] - 1.0
        return dict(O=O, H=Hh, L=Lw, C=C, E=O[:, 0].copy(), atr=atr, rhe=rhe, tsb=tsb)

    def paths_fine(self, ci, ti, he: int):
        """5m sub-bar paths: columns = 64*m five-minute bars starting at the open of TF bar t+1.
        tsb = open ts of the TF bar containing each sub-bar (for the one-position-at-a-time rule)."""
        m, W = self.m, HMAX * self.m
        n = len(ci)
        O = np.empty((n, W)); Hh = np.empty((n, W)); Lw = np.empty((n, W)); C = np.empty((n, W))
        atr = np.empty(n); rhe = np.empty(n); tsb = np.empty((n, W), dtype=np.int64)
        tfj = np.arange(W) // m + 1
        for k, c in enumerate(COINS):
            msk = ci == k
            if not msk.any():
                continue
            d = self.coin[c]
            t = ti[msk]
            j = d["p5"][t][:, None] + np.arange(W)[None, :]
            O[msk] = d["o5"][j]; Hh[msk] = d["h5"][j]; Lw[msk] = d["l5"][j]; C[msk] = d["c5"][j]
            tsb[msk] = d["ts"][t[:, None] + tfj[None, :]]
            atr[msk] = d["atr"][t]
            rhe[msk] = d["c"][t + he] / d["o"][t + 1] - 1.0
        return dict(O=O, H=Hh, L=Lw, C=C, E=O[:, 0].copy(), atr=atr, rhe=rhe, tsb=tsb)


def prep_moves(pp, sgn):
    """side-adjusted per-bar moves relative to entry, for side sgn (+1/-1)."""
    E = pp["E"][:, None]
    om = sgn * (pp["O"] / E - 1.0)
    cm = sgn * (pp["C"] / E - 1.0)
    up = pp["H"] / E - 1.0
    dn = 1.0 - pp["L"] / E
    fm, am = (up, dn) if sgn > 0 else (dn, up)
    return om, cm, fm, am


def exits(mv, L, sd, td, tfm, order="adv"):
    """Vectorised exit resolution.
    mv = prep_moves(...);  L leverage (scalar); sd stop distance (n,); td TP distance (n,).
    Returns k (1..64), code (1 TP, 2 STOP, 3 LIQ, 4 TIME), g (gross side-adjusted move; LIQ -> -dl),
    cost (per notional: fees + slippage + funding; LIQ -> entry + funding only),
    y (net per notional; LIQ -> -1/L - C_IN - funding, i.e. the whole margin is lost)."""
    om, cm, fm, am = mv
    n, H = om.shape
    dl = 1.0 / L - MMR
    sd_ = sd[:, None]; td_ = td[:, None]
    stop_first = sd_ < dl                      # stop beyond liquidation -> liquidation comes first
    gap_liq = -om >= dl
    gap_stop = (~gap_liq) & stop_first & (-om >= sd_)
    gap_tp = (~gap_liq) & (~gap_stop) & (om >= td_)
    hit_stop = stop_first & (am >= sd_)
    hit_liq = (~hit_stop) & (am >= dl)
    hit_adv = hit_stop | hit_liq
    hit_tp = fm >= td_
    if order == "adv":
        adv_wins = hit_adv
    else:                                        # favourable first
        adv_wins = hit_adv & ~hit_tp
    tp_wins = hit_tp & ~adv_wins
    code = np.zeros((n, H), dtype=np.int8)
    g = np.zeros((n, H))
    code[tp_wins] = 1
    g = np.where(tp_wins, td_, g)
    m = adv_wins & hit_stop
    code[m] = 2
    g = np.where(m, -sd_, g)
    code[adv_wins & hit_liq] = 3
    code[gap_tp] = 1; g = np.where(gap_tp, om, g)
    code[gap_stop] = 2; g = np.where(gap_stop, om, g)
    code[gap_liq] = 3
    ev = code > 0
    anyev = ev.any(1)
    first = np.where(anyev, np.argmax(ev, axis=1), H - 1)
    rows = np.arange(n)
    k = first + 1
    cc = np.where(anyev, code[rows, first], 4).astype(np.int8)
    gg = np.where(anyev, g[rows, first], cm[:, -1])
    gg = np.where(cc == 3, -dl, gg)
    fund = FUND_8H * k * tfm / 480.0
    c_out = np.where(cc == 1, C_OUT_TP, np.where(cc == 3, 0.0, C_OUT_MKT))
    cost = C_IN + c_out + fund
    y = np.where(cc == 3, -1.0 / L - C_IN - fund, gg - cost)
    return k.astype(np.int16), cc, gg.astype(np.float32), cost.astype(np.float32), y.astype(np.float32)


def chase_one(cand_ts: np.ndarray, exit_ts: np.ndarray) -> np.ndarray:
    """one position at a time: next candidate allowed if its signal ts >= exit-bar ts of the open trade.
    (exit at bar close; the next signal is formed at a later bar close, entry at the following open)"""
    n = len(cand_ts)
    nxt = np.searchsorted(cand_ts, exit_ts, side="left").tolist()
    out = []
    i = 0
    while i < n:
        out.append(i)
        i = nxt[i]
    return np.array(out, dtype=np.int64)
