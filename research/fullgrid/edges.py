"""Which picks sit at the end of a number's range, and what a second run would add there.

    python research/fullgrid/edges.py --results DIR [--out DIR]

A pick whose number is the grid's smallest or largest value may have its best value outside the range the first run
looked at (owners 2026-10-10: "커스텀값 경우의수를 더 늘리는게 좋지 않아?" -> widen only where the results point). For
each pick of select.json and each of its numbers at the first or last grid value, this says whether the range can go
further that way (not at a hard limit: a length of 2, a declared bound, an oscillator's end) and which values a second
run would add, with the same rounding and clipping as grid.py:

- length, mult, threshold_abs: default x (1/5, 1/4) below, x (4, 5) above
- threshold_neutral: neutral + f x (default - neutral), f 0.1 toward the neutral point, f 2.5 and 3 away from it;
  a level on or past the oscillator's end is left out (it is never crossed)

Output: OUT/edges.json and edges_KO.md (no money figures: numbers and counts only). It selects nothing.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)

import grid as G  # noqa: E402
import run as R  # noqa: E402

EXT_MULTS = (1 / 5, 1 / 4, 4.0, 5.0)
EXT_NEUTRAL_F = (0.1, 2.5, 3.0)


def _key(v):
    return tuple(v) if isinstance(v, list) else v


def extra_values(name: str, spec: dict) -> list:
    """The values a widened grid would add for one number (sorted, none already in the grid)."""
    d, kind = spec["default"], spec["kind"]
    lo, hi = spec.get("bounds") or G.BOUNDS.get((name, spec["name"]), (0.0, math.inf))
    now = {_key(v) for v in G.values(name, spec)}
    out = set()
    if kind == "length" and isinstance(d, (list, tuple)):
        out = {tuple(max(2, G._round_half_up(x * m)) for x in d) for m in EXT_MULTS}
    elif kind == "length":
        out = {min(max(2, G._round_half_up(d * m)), hi) if hi < math.inf else max(2, G._round_half_up(d * m))
               for m in EXT_MULTS}
    elif kind in ("mult", "threshold_abs"):
        for m in EXT_MULTS:
            v = round(float(d) * m, 12)
            if lo < v <= hi or (v == hi and hi < math.inf):
                out.add(v)
    elif kind == "threshold_neutral":
        n = float(spec["neutral"])
        for f in EXT_NEUTRAL_F:
            v = round(n + f * (float(d) - n), 12)
            if lo < v < hi and v != n:                  # an oscillator's end is a level price never crosses
                out.add(v)
    return sorted(v for v in out if v not in now)


def edges_of(pick: dict) -> list[dict]:
    """[{param, side, value, now [first, last], add [...]}] for each number of the pick at its range's end."""
    ps, vals, _combos = R.cell_grid(pick["kind"], pick["name"])
    out = []
    for p, vs in zip(ps, vals):
        if len(vs) < 2:
            continue
        v = _key(pick["combo"][p["name"]])
        side = "low" if v == vs[0] else "high" if v == vs[-1] else None
        if side is None:
            continue
        add = [x for x in extra_values(pick["name"], p) if (x < vs[0] if side == "low" else x > vs[-1])]
        out.append({"param": p["name"], "kind": p["kind"], "side": side, "value": v, "now": [vs[0], vs[-1]],
                    "add": add})
    return out


def plan(picks: list) -> dict:
    """Per cell: the numbers to widen (from any pick at an end that can go further) and the grid size it gives."""
    cells = {}
    for p in picks:
        key = f"{p['kind']}|{p['name']}|{p['tf']}"
        c = cells.setdefault(key, {"kind": p["kind"], "name": p["name"], "tf": p["tf"], "widen": {}, "picks": []})
        es = edges_of(p)
        c["picks"].append({"rank": p.get("rank"), "exit": p.get("exit"), "edges": es})
        for e in es:
            if e["add"]:
                w = c["widen"].setdefault(e["param"], set())
                w.update(map(_key, e["add"]))
    for c in cells.values():
        ps, vals, combos = R.cell_grid(c["kind"], c["name"])
        n_new = 1
        for p, vs in zip(ps, vals):
            n_new *= len(vs) + len(c["widen"].get(p["name"], ()))
        c["widen"] = {k: sorted(v) for k, v in c["widen"].items()}
        c["combos_now"], c["combos_widened_max"] = len(combos), n_new
        c["top_pick_at_edge"] = bool(c["picks"] and c["picks"][0]["edges"])
    return cells


def report_ko(cells: dict) -> str:
    to_widen = [c for c in cells.values() if c["widen"]]
    top = sum(c["top_pick_at_edge"] for c in cells.values())
    L = ["# 범위 끝에 붙은 커스텀값 (2차 계산에서 넓힐 곳)", "",
         f"후보가 있는 칸 {len(cells)}개 중 1등 값이 범위 끝에 붙은 칸 {top}개, 더 넓힐 수 있는 칸 {len(to_widen)}개.",
         "범위 끝에 붙었다는 건 더 바깥에 더 좋은 값이 있을 수 있다는 뜻입니다(확실하다는 뜻은 아님). 2차 계산은 이 칸들만",
         "그 숫자 쪽으로 넓혀 다시 봅니다. 돈 숫자는 없습니다.", ""]
    for c in sorted(to_widen, key=lambda c: (c["kind"], c["name"], c["tf"])):
        parts = [f"{k} +{', '.join(map(str, v))}" for k, v in c["widen"].items()]
        L.append(f"- {c['name']} {c['tf']}: " + "; ".join(parts)
                 + f" (조합 {c['combos_now']:,} → 최대 {c['combos_widened_max']:,})")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--results", required=True)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    out = a.out or a.results
    with open(os.path.join(a.results, "select.json")) as fh:
        picks = json.load(fh)["picks"]
    cells = plan(picks)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "edges.json"), "w") as fh:
        json.dump({"cells": cells, "ext_mults": EXT_MULTS, "ext_neutral_f": EXT_NEUTRAL_F}, fh, ensure_ascii=False,
                  indent=1, default=list)
    with open(os.path.join(out, "edges_KO.md"), "w") as fh:
        fh.write(report_ko(cells))
    print(f"[edges] {sum(bool(c['widen']) for c in cells.values())} of {len(cells)} cells to widen -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
