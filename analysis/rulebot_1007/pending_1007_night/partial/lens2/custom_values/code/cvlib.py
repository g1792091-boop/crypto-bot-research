"""Custom-value walk-forward study: signals (locked param_defs / lib_c copies), context filters, exit simulation.

Read-only reuse of the repo: research/entry_study/param_defs (hash-checked against DEFS_BC.sha256),
research/deepseek200/lib_c.py (imported, for helpers and for the default-parity check), paperbot.sweepsig
(locked indicator code). Pre-registration: ../PREREG.md (hash in ../PREREG.sha256).
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import sys

REPO = "/home/user/crypto-bot-research"
for p in (REPO, "/root/.local/lib/python3.11/site-packages", os.path.join(REPO, "research", "deepseek200")):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SCR = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad"
SIG_DIR = os.path.join(SCR, "binance", "signals")
HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.dirname(HERE)
PREREG = os.path.join(WORK, "PREREG.md")
PREREG_SHA = os.path.join(WORK, "PREREG.sha256")
PARAM_DIR = os.path.join(REPO, "research", "entry_study", "param_defs")
DEFS_MANIFEST = os.path.join(REPO, "research", "entry_study", "DEFS_BC.sha256")
DEFS_MANIFEST_PIN = "185dbcf858e93f694d0775e12925c1904373d0db002a4df7bf3cfcefa3d56044"

COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
TFS = ("15m", "30m", "1h")
TF_MIN = {"15m": 15, "30m": 30, "1h": 60}
HTF_RULE = {"15m": "1h", "30m": "2h", "1h": "4h"}
START = np.datetime64("2021-02-01T00:00:00", "ns").astype(np.int64)

# house costs (paperbot/config.py Settings, research/paper_rules/rules_bt.py)
TAKER = 0.0005
SLIP = 0.0002
RT = 2 * (TAKER + SLIP)
FUNDING_8H = 0.0001
LEV_HOUSE = 20.0
LAD_FIRST, LAD_STEP, LAD_GAP = 0.10, 0.05, 0.02

STOPS = (1.5, 2.0, 2.5)
EXITS = ("house", "rladder", "tp15be")
FILTERS = ("none", "htf", "adx", "box", "session")

STRATS = {  # name: (source, family, [P1..P4 overrides])
    "S2_ST_ROC": ("pd", "trend", [{"st_mult": 0.75}, {"st_mult": 1.25}, {"roc_len": 0.75}, {"roc_len": 1.25}]),
    "N23_HA_ST": ("pd", "trend", [{"st_atr_len": 0.75}, {"st_atr_len": 1.25}, {"st_mult": 0.75}, {"st_mult": 1.25}]),
    "N24_DMI": ("pd", "trend", [{"di_len": 0.75}, {"di_len": 1.25}, {"adx_len": 0.75}, {"adx_len": 1.25}]),
    "N10_HA_PSAR": ("pd", "trend", [{"sar_af_start": 0.75}, {"sar_af_start": 1.25}, {"sar_af_max": 0.75}, {"sar_af_max": 1.25}]),
    "S4_BB_BBP": ("pd", "trend", [{"bb_len": 0.75}, {"bb_len": 1.25}, {"sq_pct": 0.75}, {"sq_pct": 1.25}]),
    "N06_MACD_ORB": ("pd", "trend", [{"macd_fast": 0.75, "macd_slow": 0.75}, {"macd_fast": 1.25, "macd_slow": 1.25},
                                      {"ext_cap": 0.75}, {"ext_cap": 1.25}]),
    "OBV_B": ("pd", "trend", [{"break_len": 0.75}, {"break_len": 1.25}, {"ao_slow": 0.75}, {"ao_slow": 1.25}]),
    "F6_VWAP_CROSS": ("ds", "trend", [{"anchor": "week"}, {"volconf": True}, {"buffer": 0.10}, {"buffer": 0.25}]),
    "F9_FVG": ("ds", "trend", [{"min_atr": 0.375}, {"min_atr": 0.625}, {"exp": 38}, {"exp": 62}]),
    "N17_KC_RSI": ("pd", "mr", [{"kc_mult": 0.75}, {"kc_mult": 1.25}, {"rsi_level": 0.75}, {"rsi_level": 1.25}]),
    "N16_BBRSI": ("pd", "mr", [{"bb_len": 0.75}, {"bb_len": 1.25}, {"rsi_len": 0.75}, {"rsi_len": 1.25}]),
    "F5_BOX": ("ds", "mr", [{"box_len": 36}, {"box_len": 60}, {"adx_thr": 15.0}, {"adx_thr": 25.0}]),
}


def sha256(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def check_prereg() -> str:
    want = open(PREREG_SHA).read().split()[0]
    got = sha256(PREREG)
    if want != got:
        raise SystemExit(f"PREREG.md changed: {got} != {want}")
    return got


# ------------------------------------------------------------------ locked param defs (hash-checked)
_MODS: dict = {}


def load_param_def(name: str):
    if name in _MODS:
        return _MODS[name]
    if sha256(DEFS_MANIFEST) != DEFS_MANIFEST_PIN:
        raise SystemExit("DEFS_BC.sha256 does not match its pinned hash")
    exp = None
    for line in open(DEFS_MANIFEST):
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == f"param_defs/{name}.py":
            exp = parts[0].lower()
    path = os.path.join(PARAM_DIR, f"{name}.py")
    data = open(path, "rb").read()
    if hashlib.sha256(data).hexdigest() != exp:
        raise SystemExit(f"param_defs/{name}.py hash mismatch")
    spec = importlib.util.spec_from_file_location(f"_cv_pd_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    exec(compile(data, path, "exec"), mod.__dict__)
    _MODS[name] = mod
    return mod


def pd_overrides(mod, mults: dict) -> dict:
    spec = {p["name"]: p for p in mod.PARAMS}
    return {k: mod.variant_value(spec[k], m) for k, m in mults.items()}


# ------------------------------------------------------------------ bars
def load_npz(tf: str, coin: str):
    z = np.load(os.path.join(SIG_DIR, f"sig_{tf}_{coin}.npz"))
    b = {k: z[k] for k in ("ts", "o", "h", "l", "c", "v", "atr")}
    return b, z


def frame(b: dict, tf: str) -> pd.DataFrame:
    df = pd.DataFrame({"ts": pd.to_datetime(b["ts"], utc=True), "open": b["o"], "high": b["h"], "low": b["l"],
                       "close": b["c"], "volume": b["v"]})
    df.attrs["tf"] = tf
    return df


# ------------------------------------------------------------------ DeepSeek copies (parameterised)
def _lc():
    import lib_c
    return lib_c


def ds_signals(name: str, df: pd.DataFrame, tf: str, **ov):
    """Parameterised copies of lib_c.entries for F6_VWAP_CROSS, F5_BOX, F9_FVG. Defaults == lib_c."""
    L = _lc()
    E = L.env()
    fg = E["fg"]
    o, h, l, c, v = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    ts = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None).to_numpy().astype("datetime64[ns]")
    n = len(c)
    atr = fg.atr(df, 14).to_numpy(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        if name == "F6_VWAP_CROSS":
            anchor, volconf, buf = ov.get("anchor", "day"), ov.get("volconf", False), float(ov.get("buffer", 0.0))
            day = ts.astype("datetime64[D]").astype(np.int64)
            key = day if anchor == "day" else (day + 3) // 7          # Monday-based week number
            tp = (h + l + c) / 3
            g = pd.DataFrame({"d": key, "pv": tp * v, "v": v}).groupby("d")
            cpv, cv = g["pv"].cumsum().to_numpy(), g["v"].cumsum().to_numpy()
            vw = np.where(cv > 0, cpv / cv, np.nan)
            same = np.r_[False, key[1:] == key[:-1]]
            pc, pv = L._prev(c), L._prev(vw)
            up_lvl = vw if buf == 0 else vw + buf * atr     # buf 0: exactly lib_c (no NaN ATR in warm-up)
            dn_lvl = vw if buf == 0 else vw - buf * atr
            lg = same & (pc <= pv) & (c > up_lvl)
            sh = same & (pc >= pv) & (c < dn_lvl)
            if volconf:
                vs = pd.Series(v).rolling(20).mean().to_numpy()
                lg, sh = lg & (v > vs), sh & (v > vs)
        elif name == "F5_BOX":
            bl, thr = int(ov.get("box_len", 48)), float(ov.get("adx_thr", 20.0))
            hi = pd.Series(h).rolling(bl).max().shift(1).to_numpy()
            lo = pd.Series(l).rolling(bl).min().shift(1).to_numpy()
            width = hi - lo
            adx = fg.dmi_adx(df, 14, 14)[2].to_numpy(float)
            valid = (adx < thr) & (width >= 3 * atr)
            pos = (c - lo) / width
            lg = valid & (pos >= 0) & (pos <= 0.15) & (c > o)
            sh = valid & (pos >= 0.85) & (pos <= 1) & (c < o)
        elif name == "F9_FVG":
            mn, expn = float(ov.get("min_atr", 0.5)), int(ov.get("exp", 50))
            zones = []
            up = (l[2:] > h[:-2]) & ((l[2:] - h[:-2]) >= mn * atr[2:])
            dn = (h[2:] < l[:-2]) & ((l[:-2] - h[2:]) >= mn * atr[2:])
            for b_ in (np.flatnonzero(up) + 2):
                zones.append((int(b_), float(h[b_ - 2]), float(l[b_]), 1, float("nan")))
            for b_ in (np.flatnonzero(dn) + 2):
                zones.append((int(b_), float(h[b_]), float(l[b_ - 2]), -1, float("nan")))

            def conf_mid(s, lo_, hi_, d):
                m = (lo_ + hi_) / 2
                return bool(c[s] >= m) if d > 0 else bool(c[s] <= m)
            old = L.EXP
            L.EXP = expn
            try:
                lg, sh = L.resolve_zones(n, h, l, zones, conf_mid)
            finally:
                L.EXP = old
        else:
            raise ValueError(name)
    lg, sh = np.asarray(lg, bool), np.asarray(sh, bool)
    both = lg & sh
    return lg & ~both, sh & ~both


def strategy_signal(name: str, k: int, df: pd.DataFrame, tf: str) -> np.ndarray:
    """int8 side array (+1/-1/0) of param set k (0 = default)."""
    src, _fam, var = STRATS[name]
    ov = {} if k == 0 else var[k - 1]
    if src == "pd":
        mod = load_param_def(name)
        lg, sh = mod.signals(df, tf, **pd_overrides(mod, ov))
    else:
        lg, sh = ds_signals(name, df, tf, **ov)
    lg, sh = np.asarray(lg, bool), np.asarray(sh, bool)
    return np.where(lg, 1, np.where(sh, -1, 0)).astype(np.int8)


# ------------------------------------------------------------------ filters
def filter_flags(df: pd.DataFrame, b: dict, tf: str, family: str):
    """{filter: (long_ok, short_ok)} boolean arrays per bar (causal, at the bar close)."""
    from paperbot import sweepsig
    sweepsig.lib()
    import fg_indicators as fg
    import pine_indicators as pi
    n = len(b["c"])
    c = b["c"]
    ts = b["ts"].astype("datetime64[ns]")
    tfm = TF_MIN[tf]
    # HTF close vs EMA50 from resampled own bars; an HTF bin is usable once its end <= this bar's close
    s = pd.DataFrame({"c": c}, index=pd.DatetimeIndex(ts))
    rule = HTF_RULE[tf]
    hc = s["c"].resample(rule, label="left", closed="left").last().dropna()
    hema = pi.pine_ema(hc.to_numpy(float), 50)
    hend = (hc.index + pd.Timedelta(rule)).to_numpy().astype("datetime64[ns]").astype(np.int64)
    bar_close = ts.astype(np.int64) + tfm * 60 * 10**9
    j = np.searchsorted(hend, bar_close, side="right") - 1
    okj = j >= 0
    jj = np.maximum(j, 0)
    hcl, hem = np.where(okj, hc.to_numpy(float)[jj], np.nan), np.where(okj, hema[jj], np.nan)
    with np.errstate(invalid="ignore"):
        htf_l, htf_s = hcl > hem, hcl < hem
        adx = fg.dmi_adx(df, 14, 14)[2].to_numpy(float)
        if family == "trend":
            a_ok = adx >= 20
        else:
            a_ok = adx < 25
        hi = pd.Series(b["h"]).rolling(48).max().shift(1).to_numpy()
        lo = pd.Series(b["l"]).rolling(48).min().shift(1).to_numpy()
        pos = (c - lo) / (hi - lo)
        if family == "trend":
            box_l, box_s = pos >= 0.5, pos <= 0.5
        else:
            box_l, box_s = pos <= 0.3, pos >= 0.7
    hour = (ts.astype("datetime64[h]").astype(np.int64) % 24)
    sess = (hour >= 7) & (hour <= 20)
    return {"htf": (htf_l, htf_s), "adx": (a_ok, a_ok), "box": (box_l, box_s), "session": (sess, sess)}


# ------------------------------------------------------------------ exits
def scan(b, idx, side, k, mode, H, n, f_bar):
    """Vectorised path of H bars after the signal (exitstyle.scan geometry). Returns done, held, exit_raw,
    exit_px, fill, stop0, raw."""
    m = len(idx)
    off = np.arange(1, H + 1)
    J = idx[:, None] + off[None, :]
    valid = J < n
    Jc = np.minimum(J, n - 1)
    o, h, lo, c = b["o"][Jc], b["h"][Jc], b["l"][Jc], b["c"][Jc]
    raw = b["o"][idx + 1]
    a = b["atr"][idx]
    d = k * a
    fill = raw * (1 + side * SLIP)
    stop0 = raw - side * d
    s = side[:, None]
    fav = np.where(s == 1, h, -lo)
    best = np.maximum.accumulate(np.concatenate([(side * fill)[:, None], fav], axis=1), axis=1)[:, 1:]
    tp = None
    if mode == "house":
        fund = f_bar * off[None, :]
        best_px = s * best
        roe_best = LEV_HOUSE * (s * (best_px / fill[:, None] - 1) - RT - fund)
        first = LAD_FIRST + LAD_GAP
        nstep = np.floor((roe_best - first) / LAD_STEP + 1e-9)
        lock_roe = np.where(roe_best >= first - 1e-12, LAD_FIRST + LAD_STEP * nstep, np.nan)
        lock_px = fill[:, None] * (1 + s * (lock_roe / LEV_HOUSE + RT + fund))
        lp = np.where(np.isnan(lock_px), -np.inf, s * lock_px)
    else:
        mfe = (best - (side * raw)[:, None]) / d[:, None]
        if mode == "rladder":
            lock_r = np.where(mfe >= 1.0 - 1e-12, 0.5 + 0.5 * np.floor((mfe - 1.0) / 0.5 + 1e-9), np.nan)
            lp = np.where(np.isnan(lock_r), -np.inf, (side * raw)[:, None] + lock_r * d[:, None])
        elif mode == "tp15be":
            lp = np.where(mfe >= 1.0 - 1e-12, (side * fill)[:, None], -np.inf)
            tp = raw + side * 1.5 * d
        else:
            raise ValueError(mode)
    lock_cum = np.maximum.accumulate(np.concatenate([np.full((m, 1), -np.inf), lp], axis=1), axis=1)[:, :-1]
    stop_eff = np.maximum((side * stop0)[:, None], lock_cum)
    adverse = np.where(s == 1, lo, -h)
    hit_s = (adverse <= stop_eff) & valid
    if tp is None:
        hit_t = np.zeros_like(hit_s)
    else:
        hit_t = (fav >= (side * tp)[:, None]) & valid & ~hit_s
    hit = hit_s | hit_t
    done = hit.any(axis=1)
    q = np.where(done, hit.argmax(axis=1), np.minimum(H, np.maximum(valid.sum(axis=1), 1)) - 1)
    r = np.arange(m)
    is_tp = done & hit_t[r, q]
    st = side * stop_eff[r, q]
    oq = o[r, q]
    gap = (side * oq) <= (side * st)
    tpv = tp if tp is not None else np.full(m, np.nan)
    exit_raw = np.where(done, np.where(is_tp, tpv, np.where(gap, oq, st)), c[r, q])
    return done, q + 1, exit_raw, raw, fill, stop0


def outcomes(b, idx, side, tf, k, mode):
    """Per-signal (done, held, R_net, R_gross, net_pct) with the 64 -> 512 -> 4096 bar passes."""
    n = len(b["ts"])
    f_bar = FUNDING_8H * TF_MIN[tf] / 480.0
    m = len(idx)
    held = np.zeros(m, np.int64)
    exr = np.full(m, np.nan)
    done = np.zeros(m, bool)
    todo = np.arange(m)
    for H in (64, 512, 4096):
        if not len(todo):
            break
        nxt = []
        step = max(16, 1_500_000 // H)
        for c0 in range(0, len(todo), step):
            sel = todo[c0:c0 + step]
            dn, hd, er, _raw, _fill, _st = scan(b, idx[sel], side[sel], k, mode, H, n, f_bar)
            fin = dn
            held[sel[fin]] = hd[fin]
            exr[sel[fin]] = er[fin]
            done[sel[fin]] = True
            rest = sel[~fin & (idx[sel] + H < n - 1)] if H < 4096 else sel[:0]
            nxt.append(rest)
        todo = np.concatenate(nxt) if nxt else np.zeros(0, int)
    raw = b["o"][idx + 1]
    fill = raw * (1 + side * SLIP)
    stop0 = raw - side * k * b["atr"][idx]
    exit_px = exr * (1 - side * SLIP)
    rd = np.abs(fill - stop0)
    pnl = side * (exit_px - fill) - TAKER * (fill + exit_px) - f_bar * held * fill
    r_net = pnl / rd
    r_gross = side * (exr - raw) / rd
    net_pct = pnl / fill
    return done, held, r_net, r_gross, net_pct
