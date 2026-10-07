"""Stability of the clustering measure across the two 5-year halves (IS 2021-08..2024-06, CF 2024-07..2026-09).

    python3 -I -B overlap_half.py <sig23.npz> <out_csv>

kappa_1h = (share - chance) / (1 - chance), share = fraction of A's card-scope entries with a same coin-side B entry
within +-4 15m bars (1 hour), chance = B shifted by +-7 days; max over the two directions. Also same-15m kappa.
"""
import os
import sys

sys.path[:0] = ['/root/.local/lib/python3.11/site-packages', os.path.dirname(os.path.abspath(__file__))]
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import common5 as C  # noqa: E402
from overlap import codes, share, chance  # noqa: E402

SPLIT = pd.Timestamp("2024-07-01").value


def main(path, out):
    d = C.load(path)
    ts = d["ts15"]
    half = ts[d["e"]] >= SPLIT
    rows = []
    for h, hm in (("IS", ~half), ("CF", half)):
        cd = {s: codes(d, C.scope_mask(d, {s: C.CARD[s]}) & hm) for s in C.ALL}
        for i, a in enumerate(C.ALL):
            for b in C.ALL[i + 1:]:
                r = dict(half=h, A=min(a, b), B=max(a, b))
                for lab, w in (("1h", 4), ("same15", 0)):
                    ks = []
                    for x, y in ((a, b), (b, a)):
                        o, c = share(cd[x], cd[y], w), chance(cd[x], cd[y], w)
                        ks.append((o - c) / (1 - c))
                    r[f"k_{lab}"] = max(ks)
                rows.append(r)
    df = pd.DataFrame(rows).pivot_table(index=["A", "B"], columns="half", values=["k_1h", "k_same15"])
    df.columns = [f"{a}_{b}" for a, b in df.columns]
    df.reset_index().to_csv(out, index=False, float_format="%.4f")
    print(df.corr().round(3))


if __name__ == "__main__":
    main(*sys.argv[1:3])
