"""Hunt round 2: the full engine-fidelity checks (PREREG_HUNT_R2.md 11), synthetic bars only.

The in-repo tests of test_hunt_r2_core.py check a sample (defaults at 15m and 4h on one coin, five coarse and two box
combos per name, four names through the engine). These two tests cover everything, take minutes, and run only with
``HUNT_R2_FIDELITY=1`` (before the code pin, and whenever entries_r2.py, store_r2.py or a signal-path file changes):

1. every default system (85 names x every timeframe x G1 and NONE) on the synthetic world: the store's signals equal
   ``hunt.system_signals`` and ``run_signals`` equals ``run_system``'s full detail;
2. every coarse combo of every F2 / F3 name: the memo and cache kept across combos equal a fresh one per combo (F2 at
   15m and 4h, F3 at every timeframe of the name), also on BTCUSDT without context.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, TESTS):
    if p not in sys.path:
        sys.path.insert(0, p)

from research.hunt import hunt as H  # noqa: E402
from research.hunt_r2 import entries_r2 as E  # noqa: E402
from research.hunt_r2 import lattice as L  # noqa: E402
from research.hunt_r2 import select_r2 as SR  # noqa: E402
from research.hunt_r2 import store_r2 as ST  # noqa: E402
from test_hunt_r2_core import SYMS, _W, _bars, _spec, world  # noqa: E402,F401

pytestmark = pytest.mark.skipif(os.environ.get("HUNT_R2_FIDELITY") != "1",
                                reason="the full fidelity run (minutes): HUNT_R2_FIDELITY=1")


def test_every_default_system_through_the_store_equals_a_direct_hunt_run(world, tmp_path):
    ctx = world
    root = str(tmp_path)
    bad, n = [], 0
    for fam, name in L.names():
        lat = L.coarse(name)
        for tf in L.tfs_of(name):
            for s in SYMS:
                ST.build(root, "coarse", name, tf, s, lat.combos[lat.default:lat.default + 1], ctx.start, ctx.end)
            units = SR.load_units(root, "coarse", name, tf, ctx.syms)
            for gate in L.GATES:
                H._EVENTS.clear()
                H._SIGS.clear()
                spec = _spec(fam, name, tf, gate)
                direct = H.system_signals(ctx.mk, spec)
                sig = SR.store_sig(ctx, units, 0, gate, tf)
                if not all(np.array_equal(sig[x], direct[x]) for x in ("k", "j", "side")):
                    bad.append((name, tf, gate, "signals"))
                    continue
                a = H.run_system(ctx.mk, spec, H.R_BASE, "base", detail=True, days=False)
                b = H.run_signals(ctx.mk, [(sig, 0)], H.R_BASE, "base", detail=True, days=False)
                a.pop("signal_counts")
                if json.dumps(a, sort_keys=True, default=str) != json.dumps(b, sort_keys=True, default=str):
                    bad.append((name, tf, gate, "engine"))
                n += 1
    SR.drop_units()
    assert not bad and n == 670, (bad[:10], n)


def test_every_coarse_combo_kept_memo_equals_fresh():
    bad, n = [], 0
    series = {tf: (_bars(40, 7, tf), _bars(40, 8, tf)) for tf in L.TFS}
    for fam, name in L.names():
        if fam not in ("F2", "F3"):
            continue
        lat = L.coarse(name)
        tfs = ("15m", "4h") if fam == "F2" else L.tfs_of(name)
        for tf in tfs:
            b, btc = series[tf]
            for sym, ctx in (("ETHUSDT", btc), ("BTCUSDT", None)):
                kept = E.SeriesEvents(name, b, sym, ctx, fresh=False)
                for c in lat.combos:
                    x = kept.events(c)
                    y = E.SeriesEvents(name, b, sym, ctx, fresh=True).events(c)
                    n += 1
                    if not (np.array_equal(x[0], y[0]) and np.array_equal(x[1], y[1])):
                        bad.append((name, tf, sym, L.combo_sha(c)))
    assert not bad and n > 0, bad[:10]
