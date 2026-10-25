"""Trades of one sweep-2 config (cell, trend judge, side mode, exit) over 2020-03 .. 2026-10-24, and one-position merges
with the sweep's month / forward scores, the 30-day goal odds from every start day, and the coin-flip twin."""
import os, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/hunt1025")
import hb_build as HB                                    # noqa: E402
import hb_5y as H                                        # noqa: E402
from hb_common import RD, COINS                          # noqa: E402
from common import ms, TF_MIN, MIN                       # noqa: E402

EX = []
for lad in ("house", "tight"):
    for s in (("atr", 1.0), ("atr", 1.5), ("atr", 2.0), ("atr", 3.0), ("roe", 0.35), ("roe", 0.50), ("roe", 0.75)):
        EX.append((s, ("none", 0.0), lad))
for s in (("atr", 2.0), ("roe", 0.75)):
    for tp in (("roe", 0.30), ("roe", 0.50), ("roe", 1.00), ("atr", 2.0), ("atr", 3.0)):
        EX.append((s, tp, "none"))
XN = [HB.exit_name(x) for x in EX]
FWD_A = ms("2026-10-05 15:00"); MID = ms("2026-10-15 03:00"); Z = ms("2026-10-24 14:12")
MODE = {"양방향": "B", "숏만": "S", "롱만": "L"}
_S = {}


def sigs(cell):
    if cell not in _S:
        name, tf = cell.split("@")
        S = RD.signals(names=[name], tfs=[tf], period=(ms("2020-03-01"), Z))
        S["atr"] = np.nan
        for ci, coin in enumerate(COINS):
            G = RD._grid(coin); m = S.coin.to_numpy() == ci
            S.loc[m, "atr"] = G[f"atr14_{tf}"][S.e.to_numpy()[m] // TF_MIN[tf] - 1]
        _S[cell] = S
    return _S[cell]


def judge(S, filt, side):
    """+1 where the trend judge agrees with side (side may be the flipped one)."""
    if filt == "none":
        return np.ones(len(S), bool)
    kind, rest = filt.split("|", 1)
    if kind in ("jdir", "j4"):
        htf = rest
    else:
        src, htf = rest.split("|")
    out = np.zeros(len(S), bool); t = S.t.to_numpy(np.int64)
    for ci, coin in enumerate(COINS):
        m = np.flatnonzero(S.coin.to_numpy() == ci)
        if not len(m):
            continue
        Zs = RD._states(coin, htf); close = Zs["ts"] + TF_MIN[htf] * MIN
        idx = np.searchsorted(close, t[m], side="right") - 1; ok = idx >= 0; ii = np.clip(idx, 0, None)
        if kind == "jdir":
            st = np.nan_to_num(Zs["j_dir"][ii].astype(float)); wm = ok & (Zs["nb"][ii] >= 120)
        elif kind == "j4":
            v = sum(np.nan_to_num(Zs[f"j_{q}"][ii].astype(float)) for q in ("V39", "S6", "OBV", "N12"))
            st = np.where(np.abs(v) == 4, np.sign(v), 0); wm = ok & (Zs["nb"][ii] >= 120)
        else:
            st = Zs[f"{kind}_{src}"][ii].astype(float); wm = ok & (Zs["nb"][ii] >= 300)
        out[m] = wm & (st == side[m])
    return out


def trades(cell, filt, mode, x, flip_seed=None):
    S = sigs(cell)
    side = S.side.to_numpy().astype(np.int8)
    if flip_seed is not None:
        side = np.where(np.random.default_rng(flip_seed).random(len(S)) < 0.5, -side, side).astype(np.int8)
    m = judge(S, filt, side) & np.isfinite(S.atr.to_numpy()) & (S.atr.to_numpy() > 0)
    md = MODE.get(mode, mode)
    if md == "S":
        m &= side < 0
    elif md == "L":
        m &= side > 0
    S = S[m].reset_index(drop=True); side = side[m]
    M = H.minutes(); ci = S.coin.to_numpy(int)
    start = M["off"][ci] + S.e.to_numpy(np.int64); send = M["off"][ci + 1]
    (sk, sv), (tk, tv), lad = EX[x]; lg, ll, ls = HB.LADS[lad]
    W, K, _ = HB.walk_all(M["o"], M["h"], M["l"], M["c"], start, send, side, HB.LEVC[ci], S.atr.to_numpy() / M["o"][start],
                          np.array([0 if sk == "atr" else 1], np.int8), np.array([sv]),
                          np.array([{"none": 0, "roe": 1, "atr": 2}[tk]], np.int8), np.array([tv]), np.array([lg]),
                          np.array([ll]), np.array([max(ls, 1e-9)]), HB.COST, HB.MARGIN, HB.MAXK)
    tfo = {"15m": 0, "30m": 1, "1h": 2, "4h": 3}[cell.split("@")[1]]
    return pd.DataFrame({"t": S.t.to_numpy(np.int64), "w": np.nan_to_num(W[:, 0].astype(float)), "k": K[:, 0], "side": side,
                         "coin": ci, "tfo": tfo, "member": f"{cell}/{filt}/{mode}/{x}"})


def months(M):
    """KST calendar months before 2026-10: (goal months: x5 before -50 %, positive months, active months) per period."""
    d = pd.to_datetime(M.t + 9 * 3600 * 1000, unit="ms"); key = d.dt.year * 100 + d.dt.month
    out = {"2020~25": [0, 0, 0], "2026": [0, 0, 0]}
    for k, g in M[(M.t < FWD_A)].groupby(key[M.t < FWD_A]):
        if k >= 202610:
            continue
        eq = np.cumprod(1 + g.w.to_numpy()); hit = False
        for v in eq:
            if v >= 5:
                hit = True; break
            if v <= 0.5:
                break
        p = "2026" if k >= 202601 else "2020~25"
        out[p][0] += hit; out[p][1] += eq[-1] >= 1; out[p][2] += 1
    return out


def forward(M):
    f = M[(M.t >= FWD_A) & (M.t < Z)]
    return {"x": float(np.prod(1 + f.w)), "h1": float(np.prod(1 + f.w[f.t < MID])), "h2": float(np.prod(1 + f.w[f.t >= MID])),
            "n": len(f), "win": float((f.w > 0).mean()) if len(f) else 0.0}


def roll(M, a, b, floor=0.5, goal=5.0):
    t = M.t.to_numpy(); w = M.w.to_numpy(); res = []
    for s in range(a, b, 86_400_000):
        i = np.searchsorted(t, s); eq = 1.0; r = 0
        while i < len(t) and t[i] < s + 30 * 86_400_000:
            eq *= 1 + w[i]; i += 1
            if eq >= goal:
                r = 1; break
            if eq <= floor:
                r = -1; break
        res.append(r)
    R = np.array(res)
    return float((R == 1).mean()), float((R == -1).mean())
