"""Self-checks of capsim.run.
  1. Uncapped joint run == each trader run alone (no interaction without caps).
  2. Capped run never violates the caps (coin-side, cluster per coin-side, book direction) at any 15m bar.
  3. A trader never holds two positions at once; entries only at e > previous exit.
  4. Independent brute-force re-implementation of setup B for one trader matches.
python3 -I -B verify.py <sig23.npz>
"""
import os
import sys

sys.path[:0] = ['/root/.local/lib/python3.11/site-packages', os.path.dirname(os.path.abspath(__file__))]
import numpy as np  # noqa: E402
import common5 as C  # noqa: E402
import capsim as S  # noqa: E402
import runcaps as RC  # noqa: E402


def main(path):
    tr = RC.T17
    t, ts15 = S.prep(path, tr, C.CARD)
    tk, bl, it = S.run(t, ts15, len(tr))
    TID = t.tid.to_numpy()
    ok1 = True
    for k, s in enumerate(tr):
        t1, _ = S.prep(path, [s], C.CARD)
        tk1, _, _ = S.run(t1, ts15, 1)
        a = t.loc[tk[TID[tk[:, 0]] == k, 0], ["e", "x", "coin", "side", "tf"]].to_numpy()
        b = t1.loc[tk1[:, 0], ["e", "x", "coin", "side", "tf"]].to_numpy()
        same = a.shape == b.shape and (a == b).all()
        ok1 &= same
        if not same:
            print("MISMATCH", s, a.shape, b.shape)
    print("1. uncapped joint == alone for all 17:", ok1)
    # brute force for one trader
    s = "N10_HA_PSAR"
    t1, _ = S.prep(path, [s], C.CARD)
    rows = t1.assign(k1=-t1.tf, k2=-t1.sf).sort_values(["e", "k1", "k2", "coin"]).to_numpy()
    cols = list(t1.columns) + ["k1", "k2"]
    ie, ix = cols.index("e"), cols.index("x")
    busy = -1
    taken = []
    for r in rows:
        if r[ie] > busy:
            taken.append((r[ie], r[ix]))
            busy = r[ix]
    tk1, _, _ = S.run(t1, ts15, 1)
    mine = list(zip(t1.e.to_numpy()[tk1[:, 0]], t1.x.to_numpy()[tk1[:, 0]]))
    print("4. brute-force setup B == run() for", s, ":", [tuple(map(int, x)) for x in taken] == [tuple(map(int, x)) for x in mine], len(taken))
    # caps
    cla = RC.cl_array(tr, "REC")
    for cs, bk in ((3, 8), (2, 6), (4, 10)):
        tk, bl, it = S.run(t, ts15, len(tr), cs_cap=cs, clusters=cla, book_cap=bk)
        r = tk[:, 0]
        e, x = t.e.to_numpy()[r], t.x.to_numpy()[r]
        co, sd, tid = t.coin.to_numpy()[r], t.side.to_numpy()[r], TID[r]
        nb = len(ts15)
        viol = 0
        for c in range(6):
            for sg in (1, -1):
                m = (co == c) & (sd == sg)
                dd = np.zeros(nb + 1, np.int32)
                np.add.at(dd, e[m], 1); np.add.at(dd, x[m] + 1, -1)
                viol += int((np.cumsum(dd) > cs).sum())
                for cl in set(cla[cla >= 0]):
                    mm = m & (cla[tid] == cl)
                    dd = np.zeros(nb + 1, np.int32)
                    np.add.at(dd, e[mm], 1); np.add.at(dd, x[mm] + 1, -1)
                    viol += int((np.cumsum(dd) > 1).sum())
        for sg in (1, -1):
            m = sd == sg
            dd = np.zeros(nb + 1, np.int32)
            np.add.at(dd, e[m], 1); np.add.at(dd, x[m] + 1, -1)
            viol += int((np.cumsum(dd) > bk).sum())
        # one position per trader
        ov = 0
        for k in range(len(tr)):
            m = tid == k
            ee, xx = e[m], x[m]
            o = np.argsort(ee)
            ov += int((ee[o][1:] <= xx[o][:-1]).sum())
        print(f"2/3. caps cs{cs}/REC/book{bk}: violations={viol}, own-overlap={ov}, intended=taken+blocked_flat:",
              int(it.sum()) == len(tk) + int((bl[:, 2] == 0).sum()))


if __name__ == "__main__":
    main(sys.argv[1])
