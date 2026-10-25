"""Shared pieces of the 10/25 hunt: trend-state columns and the direction filters built from them."""
import sys
import numpy as np

RD_DIR = "/home/user/crypto-bot-research/analysis/review1024/roles/data"
sys.path.insert(0, RD_DIR)
import rolesdata as RD          # noqa: E402
from common import COINS, TFS, TF_MIN  # noqa: E402

SRC = ["V39_ALL", "S6_EMA_DMI_ADX", "N12_ICHI_AO", "OBV_S", "VO1_OBV_X_MA20", "O2_RSI14_X50", "O8_ROC21",
       "O9_CMO14", "F7_RF_TRIPLE", "T1_EMA50_200", "T5_ST10_3", "N24_DMI"]
LATCH = ["V39_ALL", "OBV_S", "N24_DMI"]


def add_atr(S):
    atr = np.full(len(S), np.nan)
    for ci, coin in enumerate(COINS):
        G = RD._grid(coin)
        for tf in TFS:
            m = (S.coin.to_numpy() == ci) & (S.tf.to_numpy() == tf)
            if m.any():
                j = S.e.to_numpy()[m] // TF_MIN[tf] - 1
                atr[m] = G[f"atr14_{tf}"][j]
    S["atr"] = atr
    return S


def add_trend(S):
    for htf in ("1h", "4h", "1d"):
        S = RD.add_states(S, htf, SRC, kind="c")
        S = RD.add_states(S, htf, LATCH, kind="l")
        idx = RD.htf_index(S, htf)
        for k in ("dir", "raw3", "V39", "S6", "OBV", "N12"):
            col = np.zeros(len(S), np.int8)
            for ci, coin in enumerate(COINS):
                m = (S.coin.to_numpy() == ci) & (idx >= 0)
                if not m.any():
                    continue
                Zs = RD._states(coin, htf)
                v = np.nan_to_num(Zs[f"j_{k}"][idx[m]].astype(float))
                col[m] = np.where(Zs["nb"][idx[m]] >= 120, v, 0).astype(np.int8)
            S[f"j{htf}_{k}"] = col
    return S


def filters(S):
    side = S.side.to_numpy()

    def agree(col):
        return S[col].to_numpy() == side

    F = {"none": np.ones(len(S), bool)}
    for h in ("1h", "4h", "1d"):
        F[f"V39상태@{h}"] = agree(f"c{h}_V39_ALL")
        F[f"V39마지막신호@{h}"] = agree(f"l{h}_V39_ALL")
        F[f"추세봇판단@{h}"] = agree(f"j{h}_dir")
        v = sum(S[f"j{h}_{k}"].to_numpy().astype(int) for k in ("V39", "S6", "OBV", "N12"))
        F[f"4표모두@{h}"] = v * side == 4
        F[f"OBV+RSI+ROC@{h}"] = agree(f"c{h}_OBV_S") & agree(f"c{h}_O2_RSI14_X50") & agree(f"c{h}_O8_ROC21")
        F[f"OBV@{h}"] = agree(f"c{h}_OBV_S")
        F[f"OBV마지막신호@{h}"] = agree(f"l{h}_OBV_S")
        F[f"CMO@{h}"] = agree(f"c{h}_O9_CMO14")
        F[f"RF3@{h}"] = agree(f"c{h}_F7_RF_TRIPLE")
        F[f"EMA50/200@{h}"] = agree(f"c{h}_T1_EMA50_200")
        F[f"ST10_3@{h}"] = agree(f"c{h}_T5_ST10_3")
        F[f"DMI마지막신호@{h}"] = agree(f"l{h}_N24_DMI")
    F["V39상태@1h+4h"] = F["V39상태@1h"] & F["V39상태@4h"]
    F["V39+OBV@4h"] = F["V39상태@4h"] & F["OBV@4h"]
    F["V39+OBV@1h"] = F["V39상태@1h"] & F["OBV@1h"]
    return F
