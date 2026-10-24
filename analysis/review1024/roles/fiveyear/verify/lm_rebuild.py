"""Luck / multiple-testing verifier, step 1: rebuild the study's cell table (cells.pkl) into a RAM scratch of our own
(/dev/shm/claude_verify_lm), by running the study's build_acc.main and fy_analyze.cell_table with SHM redirected.
Nothing in the study folder is written (fy_analyze.main is NOT called: it would overwrite the study's CSVs).

    python3 lm_rebuild.py      (run from this folder, no -I)"""
import os
import sys

FY = "/home/user/crypto-bot-research/analysis/review1024/roles/fiveyear"
MY = "/dev/shm/claude_verify_lm"
sys.path.insert(0, FY)
os.makedirs(MY, exist_ok=True)

import fy_common                         # noqa: E402
fy_common.SHM = MY
import build_acc                         # noqa: E402
build_acc.SHM = MY
import fy_analyze                        # noqa: E402
fy_analyze.SHM = MY


def main():
    if not os.path.exists(os.path.join(MY, "meta.json")):
        build_acc.main()
    meta, A, AM, B, B0, BARS = fy_analyze.load()
    D = fy_analyze.cell_table(meta, A, AM, B, BARS)
    side_n = D.groupby(["pair", "src"]).apply(lambda z: (z.SEL_nW + z.SEL_nA + z.CONF_nW + z.CONF_nA).sum())
    dead = set(side_n[side_n == 0].index)
    D = D[[(p, s) not in dead for p, s in zip(D.pair, D.src)]].reset_index(drop=True)
    D.to_pickle(os.path.join(MY, "cells.pkl"))
    print("cells", len(D), "dead", len(dead))


if __name__ == "__main__":
    main()
