"""Shared helpers of the forward role study (analysis/review1024/roles/forward). Import from scripts in this folder,
run without -I. Everything is read-only over the cached feature tables of fw_build.py."""
import os
import sys

sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
import rolesdata as RD  # noqa: E402
from common import *     # noqa: E402,F401

HERE = os.path.dirname(os.path.abspath(__file__))
FOUT = os.path.join(SCR, "forward")
SOURCES = RD.roles()["roles"]["trend_incl_dual"]
FWD_A, FWD_B = RD.PERIODS["fwd"]
DATA_END = ms("2026-10-24 14:12")               # last minute of the extended grid
SPLIT = ms("2026-10-15 03:00")                  # = 10-15 12:00 KST, the middle of the 19 forward days
PERIOD = {"all": (FWD_A, DATA_END), "H1": (FWD_A, SPLIT), "H2": (SPLIT, DATA_END)}
DAYS = {k: (b - a) / DAY for k, (a, b) in PERIOD.items()}
MAPS = (("15m", "1h"), ("15m", "4h"), ("30m", "1h"), ("30m", "4h"), ("1h", "4h"), ("1h", "1d"), ("4h", "1d"))
AUTO = {"15m": "1h", "30m": "1h", "1h": "4h", "4h": "1d"}
JUDGES = ("Jdir", "Jraw3", "Jlive", "J4of4", "J2net")
JUDGE_KO = {"Jdir": "추세판단 봇 판단(3/4, 유지)", "Jraw3": "3/4 그 봉만", "Jlive": "판단 + ADX 20↑ + 끝물 아님",
            "J4of4": "4/4 모두 같음", "J2net": "4표 합 ±2 이상", "JB": "추세판단 봇 전체 검사(10-22 설계)"}
ROLE_KO = {"pullback": "눌림", "range": "횡보 자리", "breakout": "돌파", "reversal": "반전", "timing": "타이밍",
           "other": "기타", "trend": "추세형(진입에 씀)"}
LEV = {"w35": 35.0, "w30": 30.0, "w35s20": 35.0, "a2": 30.0}


def load(which="sig"):
    D = pd.read_pickle(os.path.join(FOUT, f"{which}.pkl.gz"))
    D["half"] = np.where(D.t.to_numpy() < SPLIT, "H1", "H2")
    D["day"] = (D.t.to_numpy(np.int64) // DAY).astype(np.int32)
    return D


def state(D, src, htf):
    """+1 / -1 / 0 trend state of the last closed htf bar for source src: a judge variant (JUDGES) or c_<x> / l_<x>."""
    if src.startswith("J"):
        g = lambda k: np.nan_to_num(D[f"J{htf}_{k}"].to_numpy(np.float64))      # noqa: E731
        d = g("dir")
        if src == "Jdir":
            s = d
        elif src == "Jraw3":
            s = g("raw3")
        elif src == "Jlive":
            adx, adxp = g("adx"), g("adx_prev")
            s = np.where((adx >= 20) & ~((adx > 40) & (adx < adxp)), d, 0)
        else:
            v = g("V39") + g("S6") + g("OBV") + g("N12")
            if src == "J4of4":
                s = np.where(np.abs(v) == 4, np.sign(v), 0)
            else:
                s = np.where(np.abs(v) >= 2, np.sign(v), 0)
        return s.astype(np.int8)
    kind, name = src.split("_", 1)
    return D[f"{kind}{htf}_{name}"].to_numpy(np.int8)


def roe(D, v="w35", opp=False):
    """Net ROE per row (leverage x r, floored at -100 %), NaN where the trade is still open at the data end."""
    s = "_opp" if opp else ""
    x = LEV[v] * D[f"{v}{s}_r"].to_numpy(np.float64)
    x = np.maximum(x, -1.0)
    return np.where(D[f"{v}{s}_why"].to_numpy() == 3, np.nan, x)


def day_boot_ci(x, day, n_boot=2000, seed=7):
    """95 % CI of the mean of x by resampling UTC days (clusters) with replacement."""
    ok = np.isfinite(x)
    x, day = x[ok], day[ok]
    if len(x) < 2:
        return (np.nan, np.nan)
    u, inv = np.unique(day, return_inverse=True)
    s = np.bincount(inv, weights=x, minlength=len(u))
    c = np.bincount(inv, minlength=len(u)).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(u), (n_boot, len(u)))
    m = s[idx].sum(1) / np.maximum(c[idx].sum(1), 1)
    return (float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5)))


def bh(p):
    """Benjamini-Hochberg q-values."""
    p = np.asarray(p, float)
    n = len(p)
    o = np.argsort(p)
    q = np.empty(n)
    q[o] = np.minimum.accumulate((p[o] * n / np.arange(1, n + 1))[::-1])[::-1]
    return np.minimum(q, 1)


def pct(x, d=2):
    return "–" if x is None or not np.isfinite(x) else f"{100 * x:+.{d}f}%"


def md_table(df, cols=None):
    cols = cols or list(df.columns)
    out = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(out)
