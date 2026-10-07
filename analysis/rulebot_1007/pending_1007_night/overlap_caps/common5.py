"""Shared definitions for the ovl5 study (entry-level overlap + exposure caps of the AI traders)."""
import numpy as np

WAVE1 = ["N10_HA_PSAR", "F16_FIB382", "F9_FVG", "N18_VWMA_MACD", "S4_BB_BBP", "N25_DST_CCI", "F6_VWAP_CROSS",
         "N23_HA_ST", "F4_FAN", "V39_ALL"]
WAVE2 = ["F16_FIB500", "F7_RF_TRIPLE", "S2_ST_ROC", "N02_ST_KST", "N07_ICHI_CMO", "DOGE", "N13_3OUTSIDE"]
RESERVE = ["N01_ST_EMA", "N04_ST_KLINGER", "N09_ALLIG_AROON", "F9_IFVG", "F12_MSS", "N22_VORTEX_PSAR"]
ALL = WAVE1 + WAVE2 + RESERVE
WAVE = {**{s: "W1" for s in WAVE1}, **{s: "W2" for s in WAVE2}, **{s: "R" for s in RESERVE}}
TF_NAMES = ("15m", "30m", "1h", "4h")
TF_BARS15 = np.array([1, 2, 4, 16])          # tf bar length in 15m bars
COINS = ("BTC", "ETH", "SOL", "DOGE", "LTC", "BCH")

# CARD scope = the pre-registered entry timeframes per trader. Source: select_portfolio.json "timeframes" where it
# names them (judge's synthesis: scope fixed by the 5-year gross sign; examples S4 without 15m, F16_FIB382 15m+1h,
# N25 without 30m); for the strategies the portfolio proposal did not staff, the same rule applied mechanically:
# keep 15m/30m/1h cells whose 5-year every-signal gross R >= 0 (sel_tp/fy_side.json). "4h" = 4h signals only when
# sizable at 20x (outc 'feasible'), only where the portfolio card names 4h.
CARD = {
    "N10_HA_PSAR": (0, 1, 2), "F16_FIB382": (0, 2), "F9_FVG": (0, 1), "N18_VWMA_MACD": (0, 1), "S4_BB_BBP": (1, 2),
    "N25_DST_CCI": (0, 2), "F6_VWAP_CROSS": (0, 1, 2, 3), "N23_HA_ST": (0, 1, 2, 3), "F4_FAN": (0, 1, 2),
    "V39_ALL": (0, 1), "F16_FIB500": (0, 1), "F7_RF_TRIPLE": (1, 2), "S2_ST_ROC": (0, 2), "N02_ST_KST": (0, 2),
    "N07_ICHI_CMO": (0, 1), "DOGE": (0, 1, 2), "N13_3OUTSIDE": (0, 2), "N01_ST_EMA": (0, 1),
    "N04_ST_KLINGER": (0, 1, 2), "N09_ALLIG_AROON": (0, 1, 2), "F9_IFVG": (0, 1, 2), "F12_MSS": (2,),
    "N22_VORTEX_PSAR": (0, 1, 2),
}
# U scope = owners' current plan / test-power setup B: 15m/30m/1h for everyone + 4h where 20x sizes.
U = {s: (0, 1, 2, 3) for s in ALL}

# Clusters proposed before this study (synthesis 'Cluster notes' + select_portfolio exposure_caps)
CLUSTERS_PROPOSED = {
    "ST_HA": ["N10_HA_PSAR", "N23_HA_ST", "S2_ST_ROC", "N01_ST_EMA", "N02_ST_KST", "N04_ST_KLINGER", "DOGE"],
    "PULLBACK": ["F16_FIB382", "F16_FIB500", "F9_FVG", "F9_IFVG"],
    "DS_TREND": ["F7_RF_TRIPLE", "F4_FAN", "F6_VWAP_CROSS"],
}


def scope_mask(d, scope):
    """Boolean mask over the flat table d for the given scope dict (4h rows only if feasible)."""
    names = list(d["names"])
    m = np.zeros(len(d["s"]), bool)
    for s, tfs in scope.items():
        si = names.index(s)
        ms = d["s"] == si
        for t in tfs:
            mt = ms & (d["tf"] == t)
            if t == 3:
                mt &= d["feas"]
            m |= mt
    return m


def load(path):
    z = np.load(path)
    return {k: z[k] for k in z.files}
