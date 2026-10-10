"""Pooled summary of gross_cost.py: per timeframe, exit and period, mean per trade at costs x0 and x1, the cost per
trade, cells positive, and the cost multiple that would break even.

    python research/fullgrid/diag/gross_sum.py gross_4h_1h.json gross_sum.json
"""

import json
import sys

P = ("select", "test", "extra")


def main(src: str, dst: str) -> None:
    res = json.load(open(src))
    out = {}
    for tf in sorted({r["tf"] for r in res}, key=["15m", "30m", "1h", "4h"].index):
        rs = [r for r in res if r["tf"] == tf]
        for ex in ("ladder|2", "tp3R|4"):
            for p in P:
                n0 = sum(r[f"{ex}|x0"][p][0] for r in rs)
                s0 = sum(r[f"{ex}|x0"][p][1] for r in rs)
                n1 = sum(r[f"{ex}|x1"][p][0] for r in rs)
                s1 = sum(r[f"{ex}|x1"][p][1] for r in rs)
                m0, m1 = s0 / max(n0, 1), s1 / max(n1, 1)
                pos0 = sum(1 for r in rs if r[f"{ex}|x0"][p][0] >= 20 and r[f"{ex}|x0"][p][1] > 0)
                pos1 = sum(1 for r in rs if r[f"{ex}|x1"][p][0] >= 20 and r[f"{ex}|x1"][p][1] > 0)
                cells = sum(1 for r in rs if r[f"{ex}|x0"][p][0] >= 20)
                be = m0 / (m0 - m1) if m0 > 0 and m0 != m1 else None
                out[f"{tf}|{ex}|{p}"] = dict(n0=n0, n1=n1, m0=m0, m1=m1, cost=m0 - m1, pos0=pos0, pos1=pos1,
                                             cells=cells, breakeven_mult=be)
                print(f"{tf:4} {ex:9} {p:6} n0={n0:7d} n1={n1:7d} gross={m0 * 100:+.3f}% net={m1 * 100:+.3f}% "
                      f"cost/trade={(m0 - m1) * 100:.3f}% pos gross {pos0}/{cells} net {pos1}/{cells}"
                      + (f" breakeven cost x{be:.2f}" if be else ""))
    json.dump(out, open(dst, "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
