"""Hunt round 2 engine identity (PREREG_HUNT_R2.md section 2, 0.3, 11): the read-only inputs round 2 imports, each
with the sha256 round 1 pinned for it.

``engine_files()`` = hunt.py, entries_wide.py, universe30.json, exchange30.json, data_manifest.json, regime5y.py,
fullgrid/memo.py, deepseek200/lib_c.py, the pin files fullgrid/PREREG.sha256, entry_study/DEFS_BC.sha256 and
third_party/sweep/PREREG.sha256, and every file ``hunt.signal_path_files("wide")`` returns (round 2's own modules
excluded: they are pinned by round 2's own lines). ``round1_lines()`` reads round 1's pin lines for those files from
``research/hunt/PREREG_HUNT_WIDE.sha256`` (never hashing that file itself, which round 1 appends to, and never a line
under ``research/hunt/out/``); the last line of a path counts (an engine fix inherited under 0.3 appends a line there
and replaces the line in round 2's pin). ``engine_problems`` lists every difference; select and test refuse on any.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

R1_PIN = "research/hunt/PREREG_HUNT_WIDE.sha256"
R1_OUT = "research/hunt/out/"
R2_PIN = "research/hunt_r2/PREREG_HUNT_R2.sha256"
FIXED = ("research/hunt/hunt.py", "research/hunt/entries_wide.py", "research/hunt/universe30.json",
         "research/hunt/exchange30.json", "research/hunt/data_manifest.json", "paperbot/dash/tools/regime5y.py",
         "research/fullgrid/memo.py", "research/deepseek200/lib_c.py", "research/fullgrid/PREREG.sha256",
         "research/entry_study/DEFS_BC.sha256", "third_party/sweep/PREREG.sha256")


def sha256_file(path: str) -> str:
    from research.hunt import hunt as H
    return H.sha256_file(path)


def engine_files() -> list:
    from research.hunt import hunt as H
    sp = [p for p in H.signal_path_files("wide") if not p.startswith("research/hunt_r2/")]
    return sorted(set(FIXED) | set(sp))


def read_lines(path: str) -> list:
    rows = []
    with open(path) as fh:
        for line in fh:
            if not line.strip():
                continue
            parts = line.rstrip("\n").split("  ", 1)
            if len(parts) != 2 or len(parts[0]) != 64:
                raise ValueError(f"{path}: bad line {line!r}")
            rows.append((parts[0], parts[1].strip()))
    return rows


def round1_lines(root: str = ROOT) -> dict:
    """{path: sha256} of round 1's pin lines (last line per path), lines under research/hunt/out/ skipped unread."""
    out = {}
    for h, p in read_lines(os.path.join(root, R1_PIN)):
        if p.startswith(R1_OUT):
            continue
        out[p] = h
    return out


def engine_problems(files: list | None = None, r2_lines: dict | None = None, root: str = ROOT) -> list:
    """Every engine file must be pinned by round 1, unchanged since, and (when ``r2_lines`` is given, the code pin)
    listed in round 2's pin with round 1's hash."""
    files = engine_files() if files is None else files
    r1 = round1_lines(root)
    bad = []
    for f in files:
        want = r1.get(f)
        full = os.path.join(root, f)
        if want is None:
            bad.append(f"not pinned by round 1: {f}")
            continue
        if not os.path.exists(full):
            bad.append(f"missing: {f}")
        elif sha256_file(full) != want:
            bad.append(f"changed since round 1's pin: {f}")
        if r2_lines is not None and r2_lines.get(f) != want:
            bad.append(f"round 2's pin line differs from round 1's: {f}")
    return bad


def check_engine(files: list | None = None, r2_lines: dict | None = None, root: str = ROOT) -> None:
    bad = engine_problems(files, r2_lines, root)
    if bad:
        raise RuntimeError("the round-1 engine differs from its pin (PREREG_HUNT_R2 2): " + "; ".join(bad))
