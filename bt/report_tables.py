"""Build the markdown tables for the stage-1 report from results/*.csv."""
from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd

from run import OUT

KO = {
    "S2_ST_ROC": "S2 슈퍼트렌드·ROC", "S5_DONCHIAN_MFI": "S5 돈치안·MFI", "S6_EMA_DMI_ADX": "S6 EMA·DMI·ADX",
    "N01_ST_EMA": "N01 ST·EMA5/20", "N02_ST_KST": "N02 ST·KST", "N03_ADX_GC": "N03 ADX·EMA50/200",
    "N07_ICHI_CMO": "N07 일목·CMO", "N08_ICHI_WR": "N08 일목·Williams%R", "N09_ALLIG_AROON": "N09 앨리게이터·Aroon",
    "N10_HA_PSAR": "N10 하이킨아시·PSAR", "N12_ICHI_AO": "N12 일목·AO", "N14_ICHI_RSI": "N14 일목·RSI",
    "N17_KC_RSI": "N17 켈트너·RSI", "N18_VWMA_MACD": "N18 VWMA·MACD", "N21_ST_RSI_ADX": "N21 ST·RSI·ADX",
    "N22_VORTEX_PSAR": "N22 Vortex·PSAR", "N23_HA_ST": "N23 하이킨아시·ST", "N24_DMI": "N24 DMI",
    "N25_DST_CCI": "N25 더블ST·CCI", "V39_15M": "V3.9 15분 전체", "V39_15M_STC": "V3.9 15분+STC",
    "V39_S42": "V3.9 S42", "V39_S52": "V3.9 S52", "V39_SR": "V3.9 SR", "V39_D16": "V3.9 D16", "V39_AC1": "V3.9 AC1",
    "OBV_S": "OBV S", "OBV_B": "OBV B", "V45_EXACT_AMB": "V4.5 정확 AM+B", "V45_ANY": "V4.5 전체(A/B/C)",
}
EXIT_KO = {
    "L50_sl15": "원래 방식 50배 SL−15%+계단", "L50_sl20": "원래 방식 50배 SL−20%+계단",
    "T_sl1.5_tr1.5": "트레일 1.5ATR", "T_sl1.5_tr2.5": "트레일 2.5ATR",
}


def exit_label(e: str) -> str:
    if e in EXIT_KO:
        return EXIT_KO[e]
    if e.startswith("F_"):
        sl = e.split("_sl")[1].split("_")[0]
        tp = e.split("_tp")[1]
        return f"SL {sl}ATR / TP {tp}ATR"
    return e


def fmt(x, nd=2):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return "—"
    return f"{x:,.{nd}f}"


def md_table(df: pd.DataFrame, cols, headers, nds):
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for _, r in df.iterrows():
        cells = []
        for c, nd in zip(cols, nds):
            v = r[c]
            if isinstance(v, str):
                cells.append(v)
            elif nd is None:
                cells.append(str(int(v)) if not (isinstance(v, float) and np.isnan(v)) else "—")
            else:
                cells.append(fmt(float(v), nd))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="")
    ap.add_argument("--window", default="IS")
    args = ap.parse_args()
    tag = f"_{args.tag}" if args.tag else ""
    p = pd.read_csv(os.path.join(OUT, f"pooled_{args.window}_15m{tag}.csv"))
    p["전략"] = p["strategy"].map(KO).fillna(p["strategy"])
    p["청산"] = p["exit"].map(exit_label)

    print("### T1 전략별 최고 청산 조합 (PF 순)\n")
    best = p.sort_values("pf", ascending=False).groupby("strategy").head(1).sort_values("pf", ascending=False)
    print(md_table(best, ["전략", "청산", "trades", "wr", "pf", "exp_gross_pct", "exp_net_pct", "symbols_pos", "months_pos", "eq_L10", "mdd_L10"],
                   ["전략", "최고 청산", "거래", "승률", "PF", "비용 전 기대값%", "비용 후 기대값%", "양수 종목", "양수 월", "10배 최종자산", "10배 MDD"],
                   [None, None, None, 3, 2, 3, 3, None, None, 2, 2]))
    print("\n### T2 청산 방식별 평균 (28개 전략 평균)\n")
    ex = p.groupby("exit")[["trades", "wr", "pf", "exp_gross_pct", "exp_net_pct", "avg_hold"]].mean().reset_index()
    ex["청산"] = ex["exit"].map(exit_label)
    ex = ex.sort_values("pf", ascending=False)
    print(md_table(ex, ["청산", "trades", "wr", "pf", "exp_gross_pct", "exp_net_pct", "avg_hold"],
                   ["청산 방식", "평균 거래", "평균 승률", "평균 PF", "비용 전 기대값%", "비용 후 기대값%", "평균 보유(봉)"],
                   [None, 0, 3, 2, 3, 3, 1]))
    print("\n### T3 V3.9 / OBV / V4.5 후보 — 원래 청산 방식 vs 최고 청산\n")
    cand = p[p["strategy"].isin(["V39_15M", "V39_15M_STC", "OBV_S", "V45_EXACT_AMB", "V45_ANY"])]
    rows = []
    for s, g in cand.groupby("strategy"):
        for e in ["L50_sl15", "L50_sl20"]:
            r = g[g["exit"] == e]
            if len(r):
                rows.append(r.iloc[0])
        rows.append(g.sort_values("pf", ascending=False).iloc[0])
    cand2 = pd.DataFrame(rows)
    print(md_table(cand2, ["전략", "청산", "trades", "wr", "pf", "exp_net_pct", "avg_hold", "eq_L50", "mdd_L50", "liq_L50"],
                   ["전략", "청산", "거래", "승률", "PF", "비용 후 기대값%", "평균 보유(봉)", "50배 최종자산", "50배 MDD", "50배 강제청산 수"],
                   [None, None, None, 3, 2, 3, 1, 3, 2, None]))
    fpath = os.path.join(OUT, f"forward_{args.window}{tag}.csv")
    if os.path.exists(fpath):
        f = pd.read_csv(fpath)
        g = f.groupby("strategy")
        rows = []
        for s, x in g:
            w = x["signals"].to_numpy()
            if w.sum() == 0:
                continue
            rows.append(dict(strategy=s, signals=int(w.sum()),
                             **{f"fwd{h}": float(np.average(x[f"fwd{h}_mean_pct"], weights=w)) for h in (4, 16, 64)},
                             hit16=float(np.average(x["fwd16_hit"], weights=w))))
        fr = pd.DataFrame(rows).sort_values("fwd16", ascending=False)
        fr["전략"] = fr["strategy"].map(KO).fillna(fr["strategy"])
        print("\n### T4 청산과 무관한 신호 품질 — 신호 후 N봉 뒤 방향 수익률(비용 0)\n")
        print(md_table(fr, ["전략", "signals", "fwd4", "fwd16", "fwd64", "hit16"],
                       ["전략", "신호 수", "4봉(1h) 뒤 %", "16봉(4h) 뒤 %", "64봉(16h) 뒤 %", "16봉 뒤 양수 비율"],
                       [None, None, 3, 3, 3, 3]))


if __name__ == "__main__":
    main()
