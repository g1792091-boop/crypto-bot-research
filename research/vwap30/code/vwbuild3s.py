"""PREREG3_AMEND1.md: vwbuild3.py with the 32 short-hold exits (stop {1, 1.5, 2, 3} ATR x profit side {rule bot ladder,
1 ATR, 2 ATR, none + break-even after 1 ATR} x hold cap {8, 16} bars) into OUT3S.

    python3 -I vwbuild3s.py [--procs 3]"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
import vwbuild3 as B
from vwcommon import *
import glob
from multiprocessing import Pool

OUT3S = OUT + "_r3s"


def exits3s():
    ex = []
    for tcap in (8, 16):
        for s in (1.0, 1.5, 2.0, 3.0):
            ex += [{"kind": "house", "stop": s, "lev": 30},
                   {"kind": "grid", "stop": s, "target": 1.0, "be": None},
                   {"kind": "grid", "stop": s, "target": 2.0, "be": None},
                   {"kind": "grid", "stop": s, "target": None, "be": 1.0}]
            for e in ex[-4:]:
                e["time"] = tcap
    for i, e in enumerate(ex):
        e["id"] = i
    return ex


EXITS3S = exits3s()


def use_short():
    """Point vwbuild3 (and anything reading its globals) at the short set."""
    B.EXITS3 = EXITS3S
    B.OUT3 = OUT3S


def exit3s_name(e):
    return B.exit3_name(e) + f" · {e['time']}봉 한도"


if __name__ == "__main__":
    use_short()
    procs = int(sys.argv[sys.argv.index("--procs") + 1]) if "--procs" in sys.argv else 3
    files = sorted(glob.glob(os.path.join(B.SIG, "*.npz")), key=lambda f: -os.path.getsize(f))
    if "--only" in sys.argv:
        want = set(sys.argv[sys.argv.index("--only") + 1].split(","))
        files = [f for f in files if os.path.basename(f)[:-4] in want]
    os.makedirs(OUT3S, exist_ok=True)
    json.dump(EXITS3S, open(os.path.join(OUT3S, "exits3s.json"), "w"))
    t0 = time.time()
    with Pool(procs, maxtasksperchild=8) as pool:
        for i, r in enumerate(pool.imap_unordered(B.job, files)):
            print(i + 1, len(files), *r, round(time.time() - t0), flush=True)
