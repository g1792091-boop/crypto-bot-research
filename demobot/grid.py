"""The settings grid of the demo lab bot: the same grid as the 5-year study (research/st_custom/PREREG.md,
'Strategies and grid'; copied from research/st_custom/common.py so the demo bot does not import the study's
scratch-folder paths). Pure: numpy only."""
from __future__ import annotations

import math

import numpy as np

COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD", "XRPUSD")
TFS = ("15m", "30m")
TF_MIN = {"15m": 15, "30m": 30}
LEVS = (20, 30, 40, 50)
STRATS = ("S2_ST_ROC", "N02_ST_KST", "N04_ST_KLINGER")
SHORT = {"S2_ST_ROC": "S2", "N02_ST_KST": "N02", "N04_ST_KLINGER": "N04"}
LONG = {v: k for k, v in SHORT.items()}
SCOPES = ("ALL",) + COINS
WINDOWS = ("live", "26w", "4w")

ST_ATR = (5, 7, 8, 10, 12, 14, 20)
ST_MULT = (1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0)
ROC_LEN = (5, 9, 14, 21, 28, 37, 50)
KST_SCALE = (0.5, 0.75, 1.0, 1.5, 2.0)
KST_SIG = (5, 9, 13)
KVO_SCALE = (0.5, 0.75, 1.0, 1.5)
KVO_SIG = (7, 13, 21)


def round_len(x: float) -> int:
    """param_defs rule: round half up, min 2."""
    return max(2, int(math.floor(float(x) + 0.5)))


KST_ROC_BASE = (10, 15, 20, 30)
KVO_BASE = (34, 55)
KST_ROCS = tuple(tuple(round_len(v * s) for v in KST_ROC_BASE) for s in KST_SCALE)
KVO_LENS = tuple(tuple(round_len(v * s) for v in KVO_BASE) for s in KVO_SCALE)

DIMS = {
    "S2_ST_ROC": [("st_atr_len", ST_ATR), ("st_mult", ST_MULT), ("roc_len", ROC_LEN)],
    "N02_ST_KST": [("st_atr_len", ST_ATR), ("st_mult", ST_MULT), ("kst_scale", KST_SCALE), ("kst_signal_len", KST_SIG)],
    "N04_ST_KLINGER": [("st_atr_len", ST_ATR), ("st_mult", ST_MULT), ("kvo_scale", KVO_SCALE),
                       ("kvo_signal_len", KVO_SIG)],
}
SHAPE = {k: tuple(len(v) for _n, v in d) for k, d in DIMS.items()}
NCOMBO = {k: int(np.prod(s)) for k, s in SHAPE.items()}           # 343 / 735 / 588
DEFAULT_IDX = {"S2_ST_ROC": (3, 6, 1), "N02_ST_KST": (3, 6, 2, 1), "N04_ST_KLINGER": (3, 6, 2, 1)}
FRIEND_IDX = {"S2_ST_ROC": (2, 3, 5), "N04_ST_KLINGER": (2, 3, 2, 1)}   # S2 8/3/ROC 37; N04 8/3/Klinger default
# the study's pooled rank-1 plateau picks on SEARCH 2021-23, main exit (research/st_custom/out/picks.csv, frozen
# 2026-10-09T01:35:42Z before any out-of-sample number): "5년 1등 값"
PICK = {("S2_ST_ROC", "15m"): 336, ("S2_ST_ROC", "30m"): 307, ("N02_ST_KST", "15m"): 668,
        ("N02_ST_KST", "30m"): 689, ("N04_ST_KLINGER", "15m"): 539, ("N04_ST_KLINGER", "30m"): 527}

# exits: 0 = house (2 ATR stop + ladder), then fixed TP x stop, K-major (research/st_custom/common.TPSL_CFG)
TPSL_TP = (1.0, 1.5, 2.0, 3.0)
TPSL_K = (1.5, 2.0, 3.0)
TPSL_CFG = tuple((tp, k) for k in TPSL_K for tp in TPSL_TP)
EXITS = ("house",) + tuple(f"tp{tp:g}R_sl{k:g}atr" for tp, k in TPSL_CFG)
NEXIT = len(EXITS)


def exit_ko(e) -> str:
    i = EXITS.index(e) if isinstance(e, str) else int(e)
    if i == 0:
        return "사다리(규칙봇 방식)"
    tp, k = TPSL_CFG[i - 1]
    return f"익절 {tp:g}R · 손절 {k:g}ATR"


def exit_stop_k(e: int) -> float:
    """Stop distance in ATR of exit e (house: 2)."""
    return 2.0 if int(e) == 0 else TPSL_CFG[int(e) - 1][1]


def combo_index(strat: str, idx) -> int:
    return int(np.ravel_multi_index(tuple(idx), SHAPE[strat]))


def combo_tuple(strat: str, c: int) -> tuple:
    return tuple(int(x) for x in np.unravel_index(int(c), SHAPE[strat]))


def combo_values(strat: str, c: int) -> dict:
    t = combo_tuple(strat, c)
    return {n: vals[i] for (n, vals), i in zip(DIMS[strat], t)}


def combo_label(strat: str, c: int) -> str:
    v = combo_values(strat, c)
    if strat == "S2_ST_ROC":
        return f"ST {v['st_atr_len']}/{v['st_mult']:g} ROC {v['roc_len']}"
    if strat == "N02_ST_KST":
        return f"ST {v['st_atr_len']}/{v['st_mult']:g} KSTx{v['kst_scale']:g} sig {v['kst_signal_len']}"
    return f"ST {v['st_atr_len']}/{v['st_mult']:g} KVOx{v['kvo_scale']:g} sig {v['kvo_signal_len']}"


def overrides(strat: str, c: int) -> dict:
    """param_defs override dict of combo c."""
    t = combo_tuple(strat, c)
    ov = {"st_atr_len": ST_ATR[t[0]], "st_mult": ST_MULT[t[1]]}
    if strat == "S2_ST_ROC":
        ov["roc_len"] = ROC_LEN[t[2]]
    elif strat == "N02_ST_KST":
        ov["kst_roc_lens"] = list(KST_ROCS[t[2]])
        ov["kst_signal_len"] = KST_SIG[t[3]]
    else:
        ov["kvo_lens"] = list(KVO_LENS[t[2]])
        ov["kvo_signal_len"] = KVO_SIG[t[3]]
    return ov


def default_combo(strat: str) -> int:
    return combo_index(strat, DEFAULT_IDX[strat])


def friend_combo(strat: str):
    return combo_index(strat, FRIEND_IDX[strat]) if strat in FRIEND_IDX else None


def neighbours(strat: str, c: int, include_self: bool = True) -> np.ndarray:
    """Combos within +-1 step in every dimension (clipped at the grid edge); the combo itself counted once."""
    t = np.array(combo_tuple(strat, c))
    shp = SHAPE[strat]
    offs = np.array(np.meshgrid(*[[-1, 0, 1]] * len(shp), indexing="ij")).reshape(len(shp), -1).T
    pts = t[None, :] + offs
    ok = np.all((pts >= 0) & (pts < np.array(shp)[None, :]), axis=1)
    out = np.ravel_multi_index(tuple(pts[ok].T), shp)
    if not include_self:
        out = out[out != c]
    return np.unique(out)


_NB: dict = {}


def neighbour_matrix(strat: str) -> np.ndarray:
    """Dense 0/1 float32 (combo x combo) neighbourhood matrix incl. self (<= 735 x 735)."""
    if strat not in _NB:
        n = NCOMBO[strat]
        M = np.zeros((n, n), np.float32)
        for c in range(n):
            M[c, neighbours(strat, c)] = 1.0
        _NB[strat] = M
    return _NB[strat]


def plateau(n: np.ndarray, mean: np.ndarray, strat: str, min_n: int) -> np.ndarray:
    """Study selection score (research/st_custom/s3_select.plateau): unweighted mean of the combo means over the
    neighbourhood members with >= 1 trade; NaN when the combo itself has fewer than min_n trades."""
    M = neighbour_matrix(strat)
    has = (n >= 1).astype(np.float32)
    m0 = np.where(n >= 1, np.nan_to_num(mean), 0.0).astype(np.float32)
    num = M @ m0
    den = M @ has
    with np.errstate(invalid="ignore", divide="ignore"):
        sc = num / den
    return np.where(n >= min_n, sc, np.nan)


def top(score: np.ndarray, k: int = 1) -> list:
    """Best k by score (ties: lower index), as research/st_custom/s3_select.top."""
    ok = np.flatnonzero(np.isfinite(score))
    if not len(ok):
        return []
    order = ok[np.lexsort((ok, -score[ok]))]
    return [int(x) for x in order[:k]]


def binance_symbol(coin: str) -> str:
    return coin[:-3] + "USDT"


def coin_ko(coin: str) -> str:
    return coin[:-3]
