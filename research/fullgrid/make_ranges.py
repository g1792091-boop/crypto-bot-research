"""Write research/fullgrid/RANGES_KO.md: every strategy's numbers, their defaults and the values the full grid tries
(grid.py), with the number of combinations per timeframe. Run from the repository root."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import grid as G  # noqa: E402
from paperbot import paramshadow as PS, sweepsig  # noqa: E402
from paperbot.agents.roster3 import STRATEGY_KO  # noqa: E402
from paperbot.dash.more.params import PARAM_KO  # noqa: E402
from paperbot.sigservice import strategy_names, window_5m  # noqa: E402

KIND_KO = {"length": "길이(봉)", "mult": "배수", "threshold_abs": "기준값", "threshold_neutral": "기준선(중립 쪽으로·반대쪽으로)"}


def fmt(v):
    if isinstance(v, list):
        return "·".join(str(x) for x in v)
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


def main():
    lib = sweepsig.lib()
    man = PS.defs_manifest()
    live = {tf: (window_5m(lib, tf) // (lib.tf_minutes(tf) // 5)) // 3 for tf in ("15m", "30m", "1h", "4h")}
    out = ["# 5년 전체 조합: 매매법별 숫자 범위 (grid.py가 만든 표)", "",
           "각 숫자를 9단계로 바꾸고(기본값 포함, 반올림·한계 때문에 겹치면 줄어듦) 모든 조합을 시험합니다. "
           "**굵게** = 지금 규칙봇이 쓰는 기본값. 길이는 기본값의 ⅓배~3배, 배수·기준값도 ⅓배~3배(뜻이 바뀌는 한계에서 자름), "
           "기준선(RSI 30처럼 중립값이 있는 것)은 중립에서의 거리를 ¼배~2배로.", "",
           f"실시간 창 한계(길이가 이보다 길면 지금 봇의 자료 창으로는 계산이 덜 됨, '실시간 창 초과'로 표시): "
           + ", ".join(f"{tf} {n}봉" for tf, n in live.items()), ""]
    total = 0
    for n in strategy_names(lib):
        m = PS.param_module(n, man)
        g = G.grid(n, m.PARAMS)
        total += len(g)
        out.append(f"## {STRATEGY_KO.get(n, n)} (`{n}`) — 봉마다 {len(g):,}가지")
        out.append("")
        out.append("| 숫자 | 종류 | 시험하는 값 |")
        out.append("|---|---|---|")
        for p in m.PARAMS:
            vals = G.values(n, p)
            d = p["default"]
            cells = []
            for v in vals:
                s = fmt(v)
                same = (v == list(d)) if isinstance(d, (list, tuple)) else (float(v) == float(d))
                cells.append(f"**{s}**" if same else s)
            name = PARAM_KO.get(p["name"], p["name"])
            out.append(f"| {name} (`{p['name']}`) | {KIND_KO.get(p['kind'], p['kind'])} | {', '.join(cells)} |")
        out.append("")
    out.insert(6, f"**합계: 봉마다 {total:,}가지, 4개 봉 {total * 4:,}가지.**")
    out.insert(7, "")
    path = os.path.join(HERE, "RANGES_KO.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    print(path, total, total * 4)


if __name__ == "__main__":
    main()
