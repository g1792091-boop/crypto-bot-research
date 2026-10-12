"""Hunt round 2 command line (PREREG_HUNT_R2.md section 11).

    python -m research.hunt_r2.hunt_r2 counts                       (writes research/hunt_r2/counts.json; no data)
    python -m research.hunt_r2.hunt_r2 pinlist                      (the code pin's lines: own files + engine files)
    python -m research.hunt_r2.hunt_r2 select --data <coins30 dir> [--private DIR] [--procs N]

``select`` refuses unless round 2's pin matches (design hash first, code, tests, counts.json, bench_r2.json, the engine
files with round 1's hashes) and picks.json is not pinned yet. It reads no 5m bar that opens at or after 2024-01-01
(hunt.load_coin cuts every column at that time before anything uses it; the content hash is taken over the whole file,
H 2), writes research/hunt_r2/out/picks.json (public; DeepSeek rows numbers, ranks and labels only) and the private
file (outside the repository, its sha256 in picks.json), and appends picks.json's sha256 to the pin before any test
bar is read. Long parts resume under the pin's hash. ``bench``, ``selfcheck``, ``pretest``, ``test`` and ``reads`` are
added before the code pin.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hunt import hunt as H  # noqa: E402
from research.hunt_r2 import lattice as L  # noqa: E402
from research.hunt_r2 import pin_r2 as PN  # noqa: E402
from research.hunt_r2 import select_r2 as SR  # noqa: E402

OUT_REL = "research/hunt_r2/out"


def private_dir(args) -> str:
    base = args.private or os.path.join(args.data or os.environ.get("HUNT_DATA", "."), "hunt_r2_private")
    path = os.path.abspath(base)
    if os.path.commonpath([path, ROOT]) == ROOT:
        raise SystemExit("--private must be outside the repository (D11)")
    return path


def cmd_counts(args) -> int:
    print(L.write_counts())
    return 0


def cmd_pinlist(args) -> int:
    print("\n".join(PN.pinlist()))
    return 0


def cmd_select(args) -> int:
    pin = PN.check_pin("select")
    EW = SR.ST.E.EW
    EW.fullgrid_pins()
    data = args.data or os.environ.get("HUNT_DATA")
    if not data:
        raise SystemExit("--data <coins30 folder> (or $HUNT_DATA) is needed")
    priv = private_dir(args)
    H.disk_check(os.path.join(ROOT, OUT_REL), priv)
    syms = H.load_universe(data)
    counts = H.load_study_data(data, syms, H.day_ms(H.PERIODS["select"][1]))
    bad = H.data_identity_problems(counts, {s: c.get("funding_content_sha256") for s, c in counts.items()})
    if bad:
        raise SystemExit("stopped: the data differ from research/hunt/data_manifest.json (H 2): " + "; ".join(bad))
    mk = H.Market(syms, "select")
    H.prepare_series(syms, H.TF_ORDER)
    tag = pin["pin_sha256"][:16]
    root = os.path.join(priv, "store")
    parts = os.path.join(priv, "parts", f"select_{tag}")
    t0 = time.time()
    res = SR.select_run(mk, root, parts, args.procs)
    order = [n for _f, n in L.names()]
    public, private = SR.picks_doc(order, res["real_units"], res["real"], res["hurdle"], res["box"], res["nulls"])
    psha = SR.write_json(os.path.join(priv, "picks_private.json"), private)
    public.update({"study": "hunt-r2 v1", "pin": pin, "git_commit": H.git_commit(), "private_sha256": psha,
                   "data_counts": counts, "seconds": round(time.time() - t0, 1), "written_utc": H.ms_str(int(
                       time.time() * 1000))})
    SR.write_json(os.path.join(ROOT, PN.PICKS), public)
    h = PN.append_line(PN.PICKS)
    print(f"round 2 select done in {time.time() - t0:.0f}s; picks.json sha256 {h} appended to {PN.R2_PIN}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m research.hunt_r2.hunt_r2")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("counts")
    sub.add_parser("pinlist")
    s = sub.add_parser("select")
    s.add_argument("--data", default=None)
    s.add_argument("--private", default=None)
    s.add_argument("--procs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args(argv)
    return {"counts": cmd_counts, "pinlist": cmd_pinlist, "select": cmd_select}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
