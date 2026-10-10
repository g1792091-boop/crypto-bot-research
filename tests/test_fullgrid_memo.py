"""research/fullgrid/memo.py must not change a single signal: every one of the 36 parameter definitions, on a
sample of grid combinations, gives the same long/short arrays with the indicator memo as without it. Runs in a fresh
interpreter so the memo (which patches the vendor modules) starts uninstalled."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCRIPT = textwrap.dedent("""
    import importlib.util, os, sys, warnings
    import numpy as np, pandas as pd
    warnings.filterwarnings("ignore")
    ROOT = sys.argv[1]
    sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "research", "fullgrid"))
    import grid as G, memo as M
    D = os.path.join(ROOT, "research", "entry_study", "param_defs")
    rng = np.random.default_rng(3)
    n = 3000
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.006, n)))
    o = np.r_[100, c[:-1]]
    df = pd.DataFrame({"ts": pd.date_range("2022-01-01", periods=n, freq="15min", tz="UTC"), "open": o,
                       "high": np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.003, n))),
                       "low": np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.003, n))), "close": c,
                       "volume": rng.uniform(100, 1000, n)})
    mods, samples, plain = {}, {}, {}
    for name in sorted(f[:-3] for f in os.listdir(D) if f.endswith(".py")):
        spec = importlib.util.spec_from_file_location("pd_" + name, os.path.join(D, name + ".py"))
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        g = G.grid(name, m.PARAMS)
        r = np.random.default_rng(len(name))
        pick = [g[i] for i in sorted(r.choice(len(g), min(6, len(g)), replace=False))]
        pick += pick[:2]                                   # repeats: served from the memo the second time
        mods[name], samples[name] = m, pick
        plain[name] = [m.signals(df.copy(), "15m", **c) for c in pick]
    M.install(list(mods.values()))
    bad = []
    for name, m in mods.items():
        M.clear()
        for c, (lo0, sh0) in zip(samples[name], plain[name]):
            lo, sh = m.signals(df, "15m", **c)
            if not (np.array_equal(lo, lo0) and np.array_equal(sh, sh0)):
                bad.append((name, c))
    print("HITS", M.STATS["hit"], "BAD", bad)
    sys.exit(1 if bad or M.STATS["hit"] == 0 else 0)
""")


def test_memo_gives_identical_signals():
    r = subprocess.run([sys.executable, "-c", SCRIPT, ROOT], capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
