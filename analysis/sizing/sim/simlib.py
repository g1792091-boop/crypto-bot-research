"""Single-account sizing simulator with planted edges on real IS bar paths.

Units: all returns are fractions (0.0014 = 0.14 %).  Equity-fraction sizing, so per-trade equity
returns compound multiplicatively and do not depend on the equity level.

Reads ONLY sweep/data/is/<sym>-<tf>.csv (bars < 2024-07-01).  Never touches oos/ or final/.
"""
from __future__ import annotations

import os
import numpy as np
import pandas as pd

SCR = "/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad"
IS_DIR = os.path.join(SCR, "sweep", "data", "is")
COINS = ["btcusd", "ethusd", "solusd", "xrpusd", "dogeusd", "ltcusd", "bchusd"]
TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}

# signal window (same as sweep PREREG IS window)
WIN_START = pd.Timestamp("2021-08-01", tz="UTC")
WIN_END = pd.Timestamp("2024-07-01", tz="UTC")

# ---- per-TF design: horizon H (bars) and attempted signal rate (signals / day, whole 7-coin universe)
DESIGN = {
    "5m": dict(H=16, lam=8.0),        # 80 min hold, 8 signals/day
    "15m": dict(H=16, lam=4.5),       # 4 h hold, 4.5 signals/day
    "1h": dict(H=16, lam=1.5),        # 16 h hold, 1.5 signals/day
    "4h": dict(H=4, lam=3.0 / 7),     # 16 h hold, 3 signals/week
    "1d": dict(H=4, lam=1.5 / 7),     # 4 day hold, 1.5 signals/week
}

# ---- Binance USDT-M cost / margin model
FEE_T = 0.0005     # taker per side
FEE_M = 0.0002     # maker per side
SLIP = 0.0002      # per market fill
FUND_8H = 0.0001   # funding per 8 h on notional, charged as a cost
MMR = 0.005        # maintenance margin rate
C_IN = FEE_T + SLIP            # market entry
C_OUT_MKT = FEE_T + SLIP       # stop / time / gap exits
C_OUT_TP = FEE_M               # TP = resting limit order, maker, no slippage

EDGES = [0.0, 0.00025, 0.0005, 0.00075, 0.0010, 0.0015, 0.0020, 0.0030, 0.0040, 0.0060, 0.0080, 0.0100, 0.0125, 0.0150, 0.0200, 0.0250, 0.0300]


def load_tf(tf: str):
    out = {}
    for c in COINS:
        p = os.path.join(IS_DIR, f"{c}-{tf}.csv")
        assert "/data/is/" in p
        df = pd.read_csv(p)
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df[df["ts"] < WIN_END].reset_index(drop=True)
        out[c] = df
    return out


def rma(x: np.ndarray, n: int) -> np.ndarray:
    """Wilder RMA seeded with the SMA of the first n values (like ta/pine)."""
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    a = 1.0 / n
    s = np.nanmean(x[:n])
    out[n - 1] = s
    for i in range(n, len(x)):
        s = s + a * (x[i] - s)
        out[i] = s
    return out


def atr_pct(df: pd.DataFrame, n: int = 14) -> np.ndarray:
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    tr[0] = h[0] - l[0]
    return rma(tr, n) / c


class Panel:
    """Per-TF panel: per-coin arrays + global signal grid with admissible (coin, t)."""

    def __init__(self, tf: str, wick: str = "raw", edge_h: int = 0, subbar: bool = False):
        self.tf = tf
        self.tfm = TF_MIN[tf]
        self.H = DESIGN[tf]["H"]
        self.lam = DESIGN[tf]["lam"]
        dfs = load_tf(tf)
        H = self.H
        # sub-bar mode: resolve every trade on the 5m bars inside its TF bars (removes the intrabar-order assumption
        # except inside single 5m bars).  m = number of 5m bars per TF bar.
        self.subbar = subbar and tf != "5m"
        self.m = self.tfm // 5 if self.subbar else 1
        self.path_tfm = 5 if self.subbar else self.tfm
        d5 = load_tf("5m") if self.subbar else None
        step = np.int64(self.tfm * 60 * 10**9)
        self.coin = {}
        grids = []
        for ci, c in enumerate(COINS):
            df = dfs[c]
            ts = df["ts"].values.astype("datetime64[ns]").astype(np.int64)
            o, h, l, cl = (df[k].values.astype(np.float64) for k in ("open", "high", "low", "close"))
            if wick == "robust":
                # sensitivity: remove single-bar isolated spikes (a crude mark-price proxy):
                # a bar's high cannot exceed max(own body, previous high, next high); same for the low.
                body_hi, body_lo = np.maximum(o, cl), np.minimum(o, cl)
                hp, hn = np.r_[h[0], h[:-1]], np.r_[h[1:], h[-1]]
                lp, ln = np.r_[l[0], l[:-1]], np.r_[l[1:], l[-1]]
                h = np.minimum(h, np.maximum(body_hi, np.maximum(hp, hn)))
                l = np.maximum(l, np.minimum(body_lo, np.minimum(lp, ln)))
            a = atr_pct(df)
            # liquidation price proxy (Binance liquidates on the mark price, which is smoother than one venue's wicks):
            # 'mark' mode removes the part of a wick that sticks out beyond max/min(own body, previous bar, next bar)
            # by more than 0.5 ATR.  Used ONLY for the liquidation check; stops/TPs still trigger on raw high/low.
            hm, lm = h.copy(), l.copy()
            if wick == "mark":
                aa = np.nan_to_num(a, nan=np.nanmedian(a)) * cl
                ref_h = np.maximum(np.maximum(o, cl), np.maximum(np.r_[h[0], h[:-1]], np.r_[h[1:], h[-1]]))
                ref_l = np.minimum(np.minimum(o, cl), np.minimum(np.r_[l[0], l[:-1]], np.r_[l[1:], l[-1]]))
                hm = np.where(h - ref_h > 0.5 * aa, ref_h, h)
                lm = np.where(ref_l - l > 0.5 * aa, ref_l, l)
            n = len(df)
            t = np.arange(n)
            ok = (t + H < n)
            tH = np.minimum(t + H, n - 1)
            ok &= (ts[tH] - ts == H * step)                  # no gap inside the path
            ok &= ts >= WIN_START.value
            ok &= t >= 50                                      # ATR warm-up (RMA14)
            ok &= np.isfinite(a) & (a > 0)
            # forward H-bar return from the entry (open t+1) to the time exit (close t+H)
            t1 = np.minimum(t + 1, n - 1)
            # the planted edge's horizon: H by default; edge_h < H = a front-loaded edge (sensitivity)
            he = edge_h if edge_h else H
            tE = np.minimum(t + he, n - 1)
            rH = np.where(ok, cl[tE] / o[t1] - 1.0, np.nan)
            sub = {}
            if self.subbar:
                f5 = d5[c]
                ts5 = f5["ts"].values.astype("datetime64[ns]").astype(np.int64)
                L5 = H * self.m
                s1 = np.searchsorted(ts5, ts[t1])                   # first 5m bar of TF bar t+1
                s1c = np.minimum(s1, len(ts5) - 1)
                e1 = np.minimum(s1 + L5 - 1, len(ts5) - 1)
                ok &= (s1 + L5 - 1 < len(ts5)) & (ts5[s1c] == ts[t1]) & (ts5[e1] - ts5[s1c] == (L5 - 1) * 300 * 10**9)
                sub = dict(ts5=ts5, s1=s1, o5=f5["open"].values.astype(float), h5=f5["high"].values.astype(float),
                           l5=f5["low"].values.astype(float), c5=f5["close"].values.astype(float))
                rH = np.where(ok, rH, np.nan)
            self.coin[c] = dict(ts=ts, o=o, h=h, l=l, c=cl, hm=hm, lm=lm, atr=a, ok=ok, rH=rH, n=n, **sub)
            grids.append(ts[ok])
        g = np.unique(np.concatenate(grids))
        self.grid = g
        idx = np.full((len(g), len(COINS)), -1, dtype=np.int64)
        for ci, c in enumerate(COINS):
            d = self.coin[c]
            pos = np.where(d["ok"])[0]
            gi = np.searchsorted(g, d["ts"][pos])
            idx[gi, ci] = pos
        self.idx = idx
        self.nadm = (idx >= 0).sum(1)
        self.bars_per_day = 1440 / self.tfm
        self.day0 = WIN_START.value
        self.ndays = int((WIN_END.value - WIN_START.value) // (86400 * 10**9))
        # per-coin E|r_H| over admissible bars (for edge calibration)
        self.Eabs = {c: float(np.nanmean(np.abs(self.coin[c]["rH"][self.coin[c]["ok"]]))) for c in COINS}
        allr = np.concatenate([self.coin[c]["rH"][self.coin[c]["ok"]] for c in COINS])
        self.Eabs_pooled = float(np.mean(np.abs(allr)))
        self.atr_med = {c: float(np.nanmedian(self.coin[c]["atr"][self.coin[c]["ok"]])) for c in COINS}

    # ------------------------------------------------------------------ candidates
    def draw_candidates(self, rng: np.random.Generator):
        p = self.lam / self.bars_per_day
        fire = rng.random(len(self.grid)) < p
        gi = np.where(fire)[0]
        k = self.nadm[gi]
        pick = (rng.random(len(gi)) * k).astype(np.int64)
        ci = np.empty(len(gi), dtype=np.int64)
        ti = np.empty(len(gi), dtype=np.int64)
        adm = self.idx[gi] >= 0
        # choose the pick-th admissible coin
        csum = np.cumsum(adm, axis=1) - 1
        sel = (csum == pick[:, None]) & adm
        ci[:] = np.argmax(sel, axis=1)
        ti[:] = self.idx[gi, ci]
        return gi, ci, ti

    def paths(self, ci, ti):
        """Return arrays (n, H) of O,H,L,C for bars t+1..t+H, entry price, atr at t, rH, exit bar ts."""
        if self.subbar:
            return self._paths_sub(ci, ti)
        H = self.H
        n = len(ci)
        O = np.empty((n, H)); Hh = np.empty((n, H)); Lw = np.empty((n, H)); C = np.empty((n, H))
        Hm = np.empty((n, H)); Lm = np.empty((n, H))
        atr = np.empty(n); rH = np.empty(n); ts_bar = np.empty((n, H), dtype=np.int64)
        for k, c in enumerate(COINS):
            m = ci == k
            if not m.any():
                continue
            d = self.coin[c]
            t = ti[m]
            j = t[:, None] + np.arange(1, H + 1)[None, :]
            O[m] = d["o"][j]; Hh[m] = d["h"][j]; Lw[m] = d["l"][j]; C[m] = d["c"][j]
            Hm[m] = d["hm"][j]; Lm[m] = d["lm"][j]
            ts_bar[m] = d["ts"][j]
            atr[m] = d["atr"][t]
            rH[m] = d["rH"][t]
        E = O[:, 0].copy()
        return dict(O=O, H=Hh, L=Lw, C=C, Hm=Hm, Lm=Lm, E=E, atr=atr, rH=rH, ts_bar=ts_bar)

    def _paths_sub(self, ci, ti):
        """Same as paths() but on the 5m bars inside TF bars t+1..t+H.  ts_bar = open time of the TF bar that
        contains each 5m bar (so the one-position-at-a-time rule still works on the TF signal grid)."""
        L5 = self.H * self.m
        n = len(ci)
        step = np.int64(self.tfm * 60 * 10**9)
        O = np.empty((n, L5)); Hh = np.empty((n, L5)); Lw = np.empty((n, L5)); C = np.empty((n, L5))
        atr = np.empty(n); rH = np.empty(n); ts_bar = np.empty((n, L5), dtype=np.int64)
        for k, c in enumerate(COINS):
            m = ci == k
            if not m.any():
                continue
            d = self.coin[c]
            t = ti[m]
            j = d["s1"][t][:, None] + np.arange(L5)[None, :]
            O[m] = d["o5"][j]; Hh[m] = d["h5"][j]; Lw[m] = d["l5"][j]; C[m] = d["c5"][j]
            ts_bar[m] = (d["ts5"][j] // step) * step
            atr[m] = d["atr"][t]
            rH[m] = d["rH"][t]
        E = O[:, 0].copy()
        return dict(O=O, H=Hh, L=Lw, C=C, E=E, atr=atr, rH=rH, ts_bar=ts_bar)


# ---------------------------------------------------------------------- policies
def policy_params(name: str, atr: np.ndarray):
    """Return M (margin, equity fraction), L (leverage) arrays, stop distance sd, tp distance td.
    name format: '<P>|<stop>|<tp>' where stop in {A,B,C}, tp in {10,30,100,none} (ROE %)."""
    P, stop, tp = name.split("|")
    n = len(atr)
    one = np.ones(n)
    if P == "P0":
        M, L = 1.0 * one, 1.0 * one
    elif P == "P1":
        M, L = 0.25 * one, 5.0 * one
    elif P == "P2":
        M, L = 0.25 * one, 10.0 * one
    elif P == "P3":
        M, L = 0.20 * one, 20.0 * one
    elif P == "P4":
        M, L = 0.40 * one, 50.0 * one
    elif P == "P5":
        # user-adaptive inside the user's bounds:
        #   leverage: keep liquidation >= 3 ATR away if possible -> L = floor(1/(3 ATR + MMR)), clipped [20, 50]
        #   margin:   volatility target, a 1-ATR adverse move costs 6 % of equity -> M = 0.06/(L*ATR), clipped [20 %, 40 %]
        L = np.clip(np.floor(1.0 / (3 * atr + MMR)), 20, 50)
        M = np.clip(0.06 / (L * atr), 0.20, 0.40)
    elif P in ("P6", "P6h"):
        # recommended: risk r of equity to a 1.5 ATR stop (incl. round-trip cost), notional cap 3x,
        # leverage = the lowest that keeps liquidation >= 2x the stop distance, capped at 10x
        r = 0.01 if P == "P6" else 0.005
        N = r / (1.5 * atr + C_IN + C_OUT_MKT)
        N = np.minimum(N, 3.0)
        Lmax = np.clip(np.floor(1.0 / (3 * atr + MMR)), 1, 10)
        # isolated margin needed: choose L = Lmax (smallest margin tie-up with liq >= 2 stops);
        L = Lmax
        M = N / L
        M = np.minimum(M, 1.0)
    else:
        raise ValueError(P)
    N = M * L
    dl = 1.0 / L - MMR
    if stop == "A":
        sd = np.full(n, np.inf)
    elif stop == "B":
        sd = 1.5 * atr
    elif stop == "C":
        sd = 0.5 * dl
    else:
        raise ValueError(stop)
    if tp == "none":
        td = np.full(n, np.inf)
    else:
        td = float(tp) / 100.0 / L
    return M, L, N, dl, sd, td


def outcomes(pp: dict, side: np.ndarray, M, L, N, dl, sd, td, tfm: int, adverse_first_all: bool = False):
    """Vectorised exit resolution for n trades.
    Returns k (exit bar offset 1..H), code (1 TP, 2 STOP, 3 LIQ, 4 TIME), g (gross side-adjusted price move;
    for LIQ = -dl), r (equity return), ynet (net return per unit notional)."""
    O, Hh, Lw, C, E = pp["O"], pp["H"], pp["L"], pp["C"], pp["E"]
    s = side[:, None].astype(np.float64)
    En = E[:, None]
    om = s * (O / En - 1.0)
    cm = s * (C / En - 1.0)
    up = Hh / En - 1.0
    dn = 1.0 - Lw / En
    fm = np.where(s > 0, up, dn)
    am = np.where(s > 0, dn, up)
    if "Hm" in pp:
        am_liq = np.where(s > 0, 1.0 - pp["Lm"] / En, pp["Hm"] / En - 1.0)
    else:
        am_liq = am
    if adverse_first_all == "fav":
        advfirst = np.zeros_like(om, dtype=bool)
    elif adverse_first_all:
        advfirst = np.ones_like(om, dtype=bool)
    else:
        bull = C >= O
        advfirst = np.where(s > 0, bull, ~bull)
    dl_ = dl[:, None]; sd_ = sd[:, None]; td_ = np.asarray(td, dtype=np.float64).reshape(-1, 1)
    stop_first = sd_ < dl_
    gap_liq = (-om >= dl_)
    gap_stop = (~gap_liq) & stop_first & (-om >= sd_)
    gap_tp = (~gap_liq) & (~gap_stop) & (om >= td_)
    hit_stop = stop_first & (am >= sd_)
    hit_liq = (~hit_stop) & (am_liq >= dl_)
    hit_adv = hit_stop | hit_liq
    hit_tp = fm >= td_
    code = np.zeros(om.shape, dtype=np.int8)
    g = np.zeros(om.shape)
    # intrabar resolution
    adv_wins = hit_adv & (advfirst | ~hit_tp)
    tp_wins = hit_tp & ~adv_wins
    code = np.where(tp_wins, 1, code)
    g = np.where(tp_wins, td_, g)
    code = np.where(adv_wins & hit_stop, 2, code)
    g = np.where(adv_wins & hit_stop, -sd_, g)
    code = np.where(adv_wins & hit_liq, 3, code)
    # gaps at the open override
    code = np.where(gap_tp, 1, code); g = np.where(gap_tp, om, g)
    code = np.where(gap_stop, 2, code); g = np.where(gap_stop, om, g)
    code = np.where(gap_liq, 3, code)
    any_ev = code > 0
    first = np.where(any_ev.any(1), np.argmax(any_ev, axis=1), -1)
    n, H = om.shape
    rows = np.arange(n)
    k = np.where(first >= 0, first + 1, H)
    cc = np.where(first >= 0, code[rows, np.maximum(first, 0)], 4).astype(np.int8)
    gg = np.where(first >= 0, g[rows, np.maximum(first, 0)], cm[:, -1])
    gg = np.where(cc == 3, -dl, gg)
    fund = FUND_8H * k * tfm / 480.0
    c_out = np.where(cc == 1, C_OUT_TP, C_OUT_MKT)
    ynet = gg - C_IN - c_out - fund
    r = np.where(cc == 3, -M - N * (C_IN + fund), N * ynet)
    ynet = np.where(cc == 3, -1.0 / L - C_IN - fund, ynet)   # per-notional loss at liquidation incl. forfeited MM
    return k.astype(np.int64), cc, gg, r, ynet


def chase(cand_ts: np.ndarray, exit_ts: np.ndarray):
    """Lockstep pointer chase for B chains.  cand_ts (n,), exit_ts (B, n) exit-bar ts of each candidate.
    Returns taken bool (B, n): one position at a time, next candidate allowed if cand_ts >= exit bar ts."""
    B, n = exit_ts.shape
    nxt = np.empty((B, n + 1), dtype=np.int64)
    for b in range(B):
        nxt[b, :n] = np.searchsorted(cand_ts, exit_ts[b], side="left")
    nxt[:, n] = n
    taken = np.zeros((B, n + 1), dtype=bool)
    cur = np.zeros(B, dtype=np.int64)
    rows = np.arange(B)
    while True:
        alive = cur < n
        if not alive.any():
            break
        taken[rows[alive], cur[alive]] = True
        cur = np.where(alive, nxt[rows, cur], n)
    return taken[:, :n]
