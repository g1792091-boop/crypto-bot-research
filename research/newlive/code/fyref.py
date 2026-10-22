"""Re-run of the five-year study's own code (research/trendbot/fiveyear/code, unchanged) into scratchpad newlive/fy_ref,
because its outputs (signals5y.csv, judge/*.npz, runs/) are no longer in the scratchpad. Only fycommon's ROOT / OUT are
pointed at fy_ref before the five-year modules are imported; its October files (fy_ref/octdata) are links to the
checksum-verified daily klines of download.sh (10-01 .. 10-20, the five-year study's data end).

Run: python3 -I fyref.py signals [--procs 3]     -> fy_ref/out/signals5y.csv      (signals5y.main)
     python3 -I fyref.py judge [--sample 20]     -> fy_ref/out/judge/<COIN>.npz   (judge5y.job)
     python3 -I fyref.py runs                    -> fy_ref/out/runs/C0_current_*  (engine5y.run, runall.save)
     python3 -I fyref.py check                   -> C0 of the re-run vs research/trendbot/fiveyear/results.json"""
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nlcommon as NLC
from nlcommon import FYREF, DATA, COINS, REPO
import fycommon

fycommon.ROOT = FYREF
fycommon.OUT = f"{FYREF}/out"
os.makedirs(f"{FYREF}/out/judge", exist_ok=True)
os.makedirs(f"{FYREF}/out/runs", exist_ok=True)


def link_oct():
    n = 0
    for c in COINS:
        for d in range(1, 21):
            name = f"{c}-1m-2026-10-{d:02d}"
            src = f"{DATA}/klines/{name}/{name}.zip"
            assert os.path.isfile(f"{DATA}/klines/{name}/ok"), name
            dst = f"{FYREF}/octdata/{name}/{name}.zip"
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if not os.path.islink(dst):
                os.symlink(src, dst)
            n += 1
    return n


def main():
    step = sys.argv[1]
    print("octdata links", link_oct(), flush=True)
    if step == "signals":
        sys.argv = ["signals5y.py"] + sys.argv[2:]
        import signals5y
        signals5y.main()
    elif step == "judge":
        sys.argv = ["judge5y.py"] + sys.argv[2:]
        import time, json
        from multiprocessing import Pool
        import judge5y
        t0 = time.time()
        res = {}
        with Pool(3) as pool:
            for coin, chk in pool.imap_unordered(judge5y.job, COINS):
                res[coin] = chk
                print(coin, json.dumps(chk), f"{time.time() - t0:.0f}s", flush=True)
        json.dump(res, open(f"{fycommon.OUT}/judge_agreement.json", "w"), indent=1)
    elif step == "runs":
        import runall
        from engine5y import variant, run, load_signals, markets, candidates, BASE
        v = variant(name="C0_current")
        T, cand, info = run(v)
        runall.save(v, T, cand, info)
    elif step == "check":
        import json, math
        import analyze
        r, T = analyze.describe("C0_current", detail="full")
        ref = json.load(open(f"{REPO}/research/trendbot/fiveyear/results.json"))["D"]["C0_current"]
        out = compare(rnd(r), ref)
        f = rnd(analyze.funnel("C0_current"))
        out_f = compare(f, json.load(open(f"{REPO}/research/trendbot/fiveyear/results.json"))["funnel_C0"])
        print(json.dumps({"describe": out, "funnel": out_f}, indent=1))
        json.dump({"describe": out, "funnel": out_f}, open(f"{FYREF}/out/check_vs_results.json", "w"), indent=1)


def rnd(x):
    import math
    import numpy as np
    if isinstance(x, float):
        return float(f"{x:.6g}") if math.isfinite(x) else None
    if isinstance(x, dict):
        return {str(k): rnd(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [rnd(v) for v in x]
    if isinstance(x, np.floating):
        return rnd(float(x))
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def compare(a, b, path="", out=None):
    """Leaf-by-leaf comparison of two JSON-like trees: {"same": n, "diff": [(path, a, b)], "only_a", "only_b"}."""
    if out is None:
        out = {"same": 0, "diff": [], "only_a": [], "only_b": []}
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in b:
                out["only_a"].append(path + "/" + k)
            elif k not in a:
                out["only_b"].append(path + "/" + k)
            else:
                compare(a[k], b[k], path + "/" + k, out)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            compare(x, y, f"{path}[{i}]", out)
    else:
        if a == b or (isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) <= 1e-9 * max(1, abs(b))):
            out["same"] += 1
        else:
            out["diff"].append((path, a, b))
    return out


if __name__ == "__main__":
    main()
