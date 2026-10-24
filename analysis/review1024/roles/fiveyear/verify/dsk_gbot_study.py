"""Direction-skill verifier, part 3c: bot G through the STUDY's own functions (cellsig.cell_rows, goalpath.bot_rows,
goalpath.read) with the exact cell order, to locate any difference with dsk_gbot.py (our own path).

    python3 dsk_gbot_study.py"""
import os
import sys

FYD = "/home/user/crypto-bot-research/analysis/review1024/roles/fiveyear"
sys.path.insert(0, FYD)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import goalpath as GP                       # noqa: E402
from dsk_gbot_prio import exact_cells       # noqa: E402
import dsk_gbot as GB                       # noqa: E402
import numpy as np                          # noqa: E402
import pandas as pd                         # noqa: E402


def main():
    G = exact_cells()
    specs = [(r["name"], r.etf, r.htf, r.kind, r.source, "W") for _, r in G.iterrows()]
    S = GP.bot_rows(specs)
    lines = []
    for per in ("CONF", "FWD"):
        o, T = GP.read(S, per)
        lines.append(f"study functions now: {per} signals {o['signals']} trades {o['trades']} mean {o['mean_roe']:.5f}"
                     f" flip {o['opp_mean_roe']:.5f}")
        T.to_csv(os.path.join(GB.HERE, f"dsk_gbot_study_{per}.csv"), index=False)
    # our rows vs the study's rows (same signals?)
    mine = pd.read_csv(os.path.join(GB.HERE, "dsk_gbot_trades.csv"))
    for per in ("CONF", "FWD"):
        st = pd.read_csv(os.path.join(GB.HERE, f"dsk_gbot_study_{per}.csv"))
        mn = mine[mine.period == per]
        ks = set(zip(st.coin, st.e, st.side, st["name"], st.tf))
        km = set(zip(mn.coin, mn.e, mn.side, mn["name"], mn.tf))
        lines.append(f"{per}: taken trades study {len(ks)} mine {len(km)} common {len(ks & km)}")
        first = sorted(ks ^ km, key=lambda x: x[1])[:3]
        lines.append(f"  first differing trades: {first}")
    txt = "\n".join(lines)
    print(txt)
    open(os.path.join(GB.HERE, "dsk_gbot_study.txt"), "w").write(txt + "\n")


if __name__ == "__main__":
    main()
