"""Pooled summary of side_skill.py (optionally with gross_sum.json to add the cost back).

    python research/fullgrid/diag/side_sum.py side_skill.json [gross_sum.json]
"""

import json
import sys

P = ("select", "test", "extra")


def main(src: str, cost_file: str | None) -> None:
    res = json.load(open(src))
    cost = json.load(open(cost_file)) if cost_file else {}
    for tf in ("15m", "30m", "1h", "4h"):
        rs = [r for r in res if r["tf"] == tf]
        if not rs:
            continue
        for en in ("ladder|2", "tp3R|4"):
            for p in (0, 1, 2):
                a = [r["acc"][f"{en}|{p}"] for r in rs]
                n = sum(x[0] for x in a)
                ch = sum(x[1] for x in a) / max(n, 1)
                op = sum(x[2] for x in a) / max(n, 1)
                longs, win = sum(x[3] for x in a), sum(x[4] for x in a)
                better = sum(1 for x in a if x[0] >= 20 and x[1] > x[2])
                cells = sum(1 for x in a if x[0] >= 20)
                c = cost.get(f"{tf}|{en}|{P[p]}", {}).get("cost")
                extra = (f" | +cost: chosen {(ch + c) * 100:+.3f}% opp {(op + c) * 100:+.3f}% "
                         f"both {((ch + op) / 2 + c) * 100:+.3f}%") if c is not None else ""
                print(f"{tf:4} {en:9} {P[p]:6} n={n:7d} long={longs / max(n, 1):.0%} chosen={ch * 100:+.3f}% "
                      f"opposite={op * 100:+.3f}% skill={(ch - op) / 2 * 100:+.3f}% "
                      f"chosen>opp trades {win / max(n, 1):.0%} cells {better}/{cells}{extra}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
