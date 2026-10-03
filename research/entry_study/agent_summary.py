"""Per-strategy summary of the entry study for the agent rooms (paperbot/agents/research_prior.json).

    python3 research/entry_study/agent_summary.py

Reads out/sr_trials.csv (A: support / resistance, 290 tests), out/bc_trials.csv (B: entry strength,
410 tests; C: parameter variants, 1,680) and the B feature labels (strength_defs), and writes what one
strategy's specialist should know: how many tests were already run on the same five years, which passed
(none as an edge), each parameter's shape, the variants positive in all three periods, and the two
cells RESULTS_ENTRY_BC.md asks the specialists to watch. Descriptive only: nothing here is a rule.
"""

from __future__ import annotations

import json
import math
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, "paperbot", "agents", "research_prior.json")
TFS = ("5m", "15m", "30m", "1h", "4h")
# RESULTS_ENTRY_BC.md, "눈여겨볼 곳(판정 아님)": defaults near 0 in all three periods
WATCH = {("V39_ALL", "4h"): "기본값의 거래당 평균이 세 기간 모두 0 근처(표준오차 0.5배 안). paper 성적을 조금 더 주의해서 봄. 판정 아님",
         ("N10_HA_PSAR", "4h"): "기본값의 거래당 평균이 세 기간 모두 0 근처(표준오차 0.5배 안). paper 성적을 조금 더 주의해서 봄. 판정 아님"}
SHAPE_KO = {"flat": "평평", "smooth": "완만", "spiky": "뾰족", "insufficient": "표본 부족"}
CONCLUSION = ("사전 등록한 네 연구(지지·저항 290건, 진입 수치 410건, 파라미터 변형 1,680건, 추세선 600건(매매법 칸 580건))를 같은 5년 자료로 "
              "이미 했고, 세 기간을 모두 통과한 효과는 없었다(지지·저항 후보 2건은 무작위 진입에서도 같은 효과: 시장 전체의 성질; "
              "추세선은 1기간 보정부터 통과 0건). "
              "파라미터는 뾰족한 곳이 없고, 세 기간 플러스 변형 수도 '파라미터가 상관없다'는 가정의 기대치와 같다. "
              "그래서 이 숫자들은 설명 자료이고, 같은 것을 다시 시험해도 새 정보가 아니다.")


def _f(x, nd=4):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, nd) if math.isfinite(x) else None


def _labels() -> dict:
    sys.path.insert(0, HERE)
    import importlib
    out = {}
    d = os.path.join(HERE, "strength_defs")
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".py") and not fn.startswith("_"):
            m = importlib.import_module(f"strength_defs.{fn[:-3]}")
            out[m.NAME] = {f["name"]: f.get("label_ko", f["name"]) for f in m.FEATURES}
    return out


def build() -> dict:
    a = pd.read_csv(os.path.join(HERE, "out", "sr_trials.csv"))
    bc = pd.read_csv(os.path.join(HERE, "out", "bc_trials.csv"))
    b, c = bc[bc["part"] == "B"], bc[bc["part"] == "C"]
    labels = _labels()
    # trendline study (PREREG_TRENDLINE.md, RESULTS_TRENDLINE.md): the strategy cells only; its random-entry
    # tests are a baseline of no strategy
    tp = os.path.join(HERE, "out", "trendline_trials.csv")
    t = pd.read_csv(tp) if os.path.exists(tp) else pd.DataFrame(columns=["strategy", "kind", "tf", "feature", "candidate"])
    t = t[t["kind"] == "cell"] if "kind" in t else t
    names = sorted(set(a["strategy"]) | set(b["strategy"]) | set(c["strategy"]))
    per = {}
    for s in names:
        sa, sb, sc = a[a["strategy"] == s], b[b["strategy"] == s], c[c["strategy"] == s]
        st = t[t["strategy"] == s]
        cand_a = [{"tf": r.tf, "feature": r.feature,
                   "note": "무작위 진입에서도 같은 효과(시장 전체의 성질)" if r.random_same_effect_p1 else ""}
                  for r in sa[sa["candidate"].astype(bool)].itertuples()]
        feats = []
        for r in sb.itertuples():
            rho = [_f(r.stat_p1), _f(r.stat_p2), _f(r.stat_p3)]
            feats.append({"tf": r.tf, "feature": r.feature, "label_ko": labels.get(s, {}).get(r.feature, r.feature),
                          "higher_is_stronger": bool(r.higher_is_stronger), "spearman_p1_p2_p3": rho,
                          "same_sign_all3": all(v is not None for v in rho) and len({v > 0 for v in rho}) == 1})
        params = []
        for (tf, p), g in sc.groupby(["tf", "param"], sort=False):
            pos = g[g["positive_all3"].astype(str) == "True"]
            params.append({"tf": tf, "param": p, "shape": g["shape"].iloc[0],
                           "shape_ko": SHAPE_KO.get(str(g["shape"].iloc[0]), str(g["shape"].iloc[0])),
                           "variants": int(len(g)),
                           "positive_all3": [{"mult": _f(r.mult, 2), "value": r.value} for r in pos.itertuples()]})
        per[s] = {
            "strategy": s,
            "support_resistance": {"tests": int(len(sa)), "passed_all3": cand_a,
                                   "features": ["level_before_lock", "support_before_stop"]},
            "entry_strength": {"tests": int(len(sb)), "passed_all3": int(sb["candidate"].astype(bool).sum()),
                               "features": feats},
            "parameters": {"variants": int(len(sc)), "adopted": 0, "params": params},
            "trendline": {"tests": int(len(st)),
                          "passed_all3": [{"tf": r.tf, "feature": r.feature} for r in st[st["candidate"].astype(str) == "True"].itertuples()],
                          "features": sorted(set(st["feature"].astype(str))) if len(st) else []},
            "watch": [{"tf": tf, "note": t} for (ws, tf), t in WATCH.items() if ws == s],
        }
    return {"source": "research/entry_study (PREREG_ENTRY.md; RESULTS_ENTRY.md, RESULTS_ENTRY_A.md, RESULTS_ENTRY_BC.md; "
                      "PREREG_TRENDLINE.md, RESULTS_TRENDLINE.md)",
            "data": "5-year outcomes, periods 2021-08..2024-06 / 2024-07..2026-09 / 2020-01..2021-07",
            "totals": {"support_resistance": int(len(a)), "entry_strength": int(len(b)), "parameters": int(len(c)),
                       "trendline": int(len(t[t["strategy"].isin(names)]))},
            "conclusion_ko": CONCLUSION, "strategies": per}


if __name__ == "__main__":
    doc = build()
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print(f"wrote {OUT}: {len(doc['strategies'])} strategies, totals {doc['totals']}, "
          f"{os.path.getsize(OUT) / 1024:.0f} KB")
