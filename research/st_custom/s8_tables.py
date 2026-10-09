"""Markdown tables for RESULTS_KO.md from the out/*.csv files (printed; the report text is written by hand around
them). Writes out/tables_ko.md.

    python3 -B research/st_custom/s8_tables.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

O = C.OUT
SN = {"S2_ST_ROC": "S2", "N02_ST_KST": "N02", "N04_ST_KLINGER": "N04"}
PER_KO = {"SEARCH": "검색 2021-23", "TEST": "시험 2024-26", "EXTRA": "추가 2020"}
SET_KO = {"default": "기본값", "friend": "친구 값", "pick1": "고른 값 1", "pick2": "고른 값 2", "pick3": "고른 값 3",
          "coinpick": "코인별 고른 값"}


def f(x, d=3, sign=True):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "-"
    return f"{x:+.{d}f}" if sign else f"{x:.{d}f}"


def pct(x):
    return "-" if not np.isfinite(x) else f"{100 * x:.0f}%"


def ci(r):
    return f"[{f(r.ci_lo)}, {f(r.ci_hi)}]" if np.isfinite(r.ci_lo) else "-"


def md(rows, head):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    return "\n".join(out)


def t_picks(P):
    rows = []
    for strat in C.STRATS:
        for tf in C.TFS:
            g = P[(P.strategy == strat) & (P.tf == tf) & (P.variant == "main") & (P.scope == "pooled")]
            for r in g.itertuples():
                rows.append([SN[strat], tf, r.rank, r.label, f(r.score), f(r.search_meanR), f"{r.search_n:,}"])
    return md(rows, ["전략", "봉", "순위", "값", "점수(이웃 평균)", "검색 net R", "검색 거래 수"])


def t_coinpicks(P, PS):
    rows = []
    for strat in C.STRATS:
        for tf in C.TFS:
            g = PS[(PS.strategy == strat) & (PS.tf == tf) & (PS.variant == "main") & (PS.scope == "coin")]
            for r in g.itertuples():
                rows.append([SN[strat], tf, r.coin.replace("USD", ""), r.label, f(r.search_net_R), f(r.test_net_R),
                             f(r.default_test_net_R), f(r.extra_net_R), f(r.default_extra_net_R),
                             "통과" if r.PASS else "탈락"])
    return md(rows, ["전략", "봉", "코인", "값", "검색", "시험", "시험(기본값)", "추가", "추가(기본값)", "판정"])


def t_main(PR, variant="main", sets=("default", "friend", "pick1", "pick2", "pick3")):
    out = []
    for strat in C.STRATS:
        for tf in C.TFS:
            rows = []
            g = PR[(PR.strategy == strat) & (PR.tf == tf) & (PR.variant == variant) & (PR.scope == "ALL")]
            for s in sets:
                gs = g[g.set == s]
                if not len(gs):
                    continue
                for per in C.PERIOD_ORDER:
                    r = gs[gs.period == per].iloc[0]
                    rows.append([SET_KO[s] if per == "SEARCH" else "", r.label if per == "SEARCH" else "",
                                 PER_KO[per], f"{r.trades:,}", pct(r.win_rate), f(r.gross_R), f(r.cost_R, sign=False),
                                 f(r.net_R), ci(r), f(r.max_dd_R, 0, False)])
            out.append(f"**{SN[strat]} {tf}**\n\n" + md(rows, ["값", "설정", "기간", "거래", "승률", "gross R",
                                                              "cost R", "net R", "95% 구간", "최대 낙폭(R)"]))
    return "\n\n".join(out)


def t_percoin(PR, per="TEST"):
    rows = []
    for strat in C.STRATS:
        for tf in C.TFS:
            g = PR[(PR.strategy == strat) & (PR.tf == tf) & (PR.variant == "main") & (PR.period == per)]
            for s in ("default", "friend", "pick1"):
                gs = g[g.set == s].set_index("scope")
                if not len(gs):
                    continue
                rows.append([SN[strat], tf, SET_KO[s]] + [f(gs.loc[c, "net_R"]) for c in C.COINS] + [f(gs.loc["ALL", "net_R"])])
    return md(rows, ["전략", "봉", "값"] + [c.replace("USD", "") for c in C.COINS] + ["7개 합산"])


def t_crash(CR):
    rows = []
    for strat in C.STRATS:
        for tf in C.TFS:
            g = CR[(CR.strategy == strat) & (CR.tf == tf) & (CR.variant == "main") & (CR.scope == "ALL")]
            for s in ("default", "friend", "pick1"):
                gs = g[g.set == s]
                cells = []
                for w in C.CRASH:
                    x = gs[gs.window == w]
                    cells.append(f"{f(x.net_R.iloc[0])} ({int(x.trades.iloc[0]):,})" if len(x) else "-")
                if len(gs):
                    rows.append([SN[strat], tf, SET_KO[s]] + cells)
    return md(rows, ["전략", "봉", "값", "2020-03 COVID", "2022-05 LUNA", "2022-11 FTX"])


def t_variants(PS, PR):
    rows = []
    for strat in C.STRATS:
        for tf in C.TFS:
            for v in ["main", "maker", "stflip", "htf", "chop"] + [x for x in PS.variant.unique() if x.startswith("tpsl")]:
                g = PS[(PS.strategy == strat) & (PS.tf == tf) & (PS.variant == v) & (PS.scope == "pooled")]
                if not len(g):
                    continue
                r = g[g["rank"] == 1].iloc[0]
                npass = int(g.PASS.sum())
                ncoin = int(PS[(PS.strategy == strat) & (PS.tf == tf) & (PS.variant == v) & (PS.scope == "coin")].PASS.sum())
                rows.append([SN[strat], tf, v, r.label, f(r.search_net_R), f(r.test_net_R), f(r.default_test_net_R),
                             f(r.extra_net_R), f(r.default_extra_net_R), f"{npass}/3", f"{ncoin}/7"])
    return md(rows, ["전략", "봉", "변형", "고른 값 1", "검색", "시험", "시험(기본값)", "추가", "추가(기본값)",
                     "통과(전체 3개)", "통과(코인 7개)"])


def best_tpsl(P):
    """Per strategy x tf: the TPSL setting whose rank-1 pooled pick has the best SEARCH score (DEVIATIONS I6)."""
    g = P[(P.scope == "pooled") & (P["rank"] == 1) & P.variant.str.startswith("tpsl")]
    return {(s, tf): x.sort_values("score", ascending=False).variant.iloc[0] for (s, tf), x in g.groupby(["strategy", "tf"])}


def t_variants_compact(PS, P):
    bt = best_tpsl(P)
    rows = []
    for strat in C.STRATS:
        for tf in C.TFS:
            for v in ("main", "maker", "stflip", "htf", "chop", bt[(strat, tf)]):
                g = PS[(PS.strategy == strat) & (PS.tf == tf) & (PS.variant == v)]
                r = g[(g.scope == "pooled") & (g["rank"] == 1)].iloc[0]
                k = float(v.split("_")[2].replace("atr", "")) / 2 if v.startswith("tpsl") else 1.0
                vn = {"main": "기본 청산", "maker": "MAKER", "stflip": "STFLIP", "htf": "HTF", "chop": "CHOP"}.get(
                    v, "TPSL " + v[5:].replace("_", " ").replace("atr", " ATR"))
                rows.append([SN[strat], tf, vn, r.label, f(r.search_net_R), f(r.test_net_R),
                             f"[{f(r.test_ci_lo)}, {f(r.test_ci_hi)}]", f(r.default_test_net_R), f(r.extra_net_R),
                             f(r.default_extra_net_R), f(r.test_net_R * k) if k != 1 else "",
                             f"{int(g[g.scope == 'pooled'].PASS.sum())}/3, {int(g[g.scope == 'coin'].PASS.sum())}/7"])
    return md(rows, ["전략", "봉", "변형", "고른 값 1", "검색", "시험", "시험 95% 구간", "시험(기본값)", "추가",
                     "추가(기본값)", "시험 R2", "통과(전체/코인)"])


def t_luck(LK):
    rows = []
    for strat in C.STRATS:
        for tf in C.TFS:
            g = LK[(LK.strategy == strat) & (LK.tf == tf) & (LK.variant == "main") & (LK.scope == "pooled")]
            for r in g.itertuples():
                rows.append([SN[strat], tf, r.rank, r.label, f(r.search_net_R), f(r.random_mean),
                             f(r.random_best_of_grid_p95), "예" if r.beats_luck else "아니오"])
    return md(rows, ["전략", "봉", "순위", "값", "검색 net R", "무작위 평균", "무작위 최고값 95%", "운보다 나음"])


def t_reopt(RO):
    rows = []
    for strat in C.STRATS:
        for tf in C.TFS:
            for per in ("TEST", "EXTRA"):
                g = RO[(RO.strategy == strat) & (RO.tf == tf) & (RO.period == per)].set_index("method")
                d = g.loc["DEFAULT"]
                cells = [SN[strat], tf, PER_KO[per], f"{f(d.net_R)} ({int(d.trades):,})"]
                for m in ("ROLL5_26w", "ROLL5_4w", "WEEKLY_26w"):
                    r = g.loc[m]
                    cells.append(f"{f(r.net_R)} ({int(r.trades):,}); 차이 {f(r.diff_vs_default)} "
                                 f"[{f(r.diff_ci_lo)}, {f(r.diff_ci_hi)}]")
                rows.append(cells)
    return md(rows, ["전략", "봉", "기간", "기본값 (거래)", "5거래마다, 26주", "5거래마다, 4주", "매주, 26주"])


def t_accounts(AC, period="TEST", mode="house", minorder=True, sets=("default", "friend", "pick1", "coinpicks")):
    out = []
    for sizing in ("owner", "risk1"):
        rows = []
        for strat in C.STRATS:
            for tf in C.TFS:
                for s in sets:
                    g = AC[(AC.strategy == strat) & (AC.tf == tf) & (AC.set == s) & (AC.period == period) &
                           (AC["mode"] == mode) & (AC.minorder == minorder) & (AC.sizing == sizing)]
                    if not len(g):
                        continue
                    cells = [SN[strat], tf, SET_KO.get(s, s if s != "coinpicks" else "코인별 고른 값")]
                    for L in (20, 30, 40, 50):
                        r = g[g.lev == L].iloc[0]
                        cells.append(f"${r.final:,.0f} / -{100 * r.max_dd:.0f}% / {int(r.worst_streak)}연패 / "
                                     f"{('파산 ' + str(r.ruin_day)[2:]) if r.ruin else '생존'} ({int(r.trades):,})")
                    rows.append(cells)
        out.append(f"**{'증거금 = 배수% 규칙' if sizing == 'owner' else '손절 1% 규칙'}**\n\n" +
                   md(rows, ["전략", "봉", "값", "20배", "30배", "40배", "50배"]))
    return "\n\n".join(out)


def main():
    P = pd.read_csv(os.path.join(O, "picks.csv"))
    PR = pd.read_csv(os.path.join(O, "pick_results.csv"))
    PS = pd.read_csv(os.path.join(O, "pass_rule.csv"))
    CR = pd.read_csv(os.path.join(O, "crash_windows.csv"))
    LK = pd.read_csv(os.path.join(O, "luck.csv"))
    parts = {"picks": t_picks(P), "coinpicks": t_coinpicks(P, PS), "main": t_main(PR), "percoin_TEST": t_percoin(PR),
             "percoin_EXTRA": t_percoin(PR, "EXTRA"), "crash": t_crash(CR),
             "variants_compact": t_variants_compact(PS, P), "variants": t_variants(PS, PR), "luck": t_luck(LK)}
    if os.path.exists(os.path.join(O, "reopt.csv")):
        parts["reopt"] = t_reopt(pd.read_csv(os.path.join(O, "reopt.csv")))
    if os.path.exists(os.path.join(O, "accounts.csv")):
        AC = pd.read_csv(os.path.join(O, "accounts.csv"))
        for per in ("TEST", "EXTRA", "SEARCH"):
            parts[f"accounts_{per}"] = t_accounts(AC, per)
    txt = "\n\n".join(f"<!-- {k} -->\n{v}" for k, v in parts.items())
    open(os.path.join(O, "tables_ko.md"), "w").write(txt)
    print(txt)


if __name__ == "__main__":
    main()
