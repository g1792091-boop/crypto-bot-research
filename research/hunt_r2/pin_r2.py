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


# ------------------------------------------------------------------ round 2's own pin (11)
DESIGN = "research/hunt_r2/PREREG_HUNT_R2.md"
PICKS = "research/hunt_r2/out/picks.json"
COUNTS = "research/hunt_r2/counts.json"
BENCH = "research/hunt_r2/bench_r2.json"
KIT = ("research/hunt_r2/bootstrap_r2.sh", "research/hunt_r2/wait_go_r2.sh", "research/hunt_r2/SERVER_R2_KO.md")


def own_files(root: str = ROOT) -> list:
    """Round 2's own files the code pin lists (11): the design, the code, the tests, the server kit, counts.json and
    bench_r2.json (each when it exists; counts.json and bench_r2.json are required by ``check_pin``)."""
    out = [DESIGN, COUNTS, BENCH]
    d = os.path.join(root, "research", "hunt_r2")
    out += [f"research/hunt_r2/{f}" for f in sorted(os.listdir(d)) if f.endswith(".py")]
    t = os.path.join(root, "tests")
    out += [f"tests/{f}" for f in sorted(os.listdir(t)) if f.startswith("test_hunt_r2") and f.endswith(".py")]
    out += [k for k in KIT if os.path.exists(os.path.join(root, k))]
    return out


def pinlist(root: str = ROOT, files: list | None = None) -> list:
    """'<sha256>  <path>' lines of the code pin: round 2's own files by their current hash, the engine files by the
    hash round 1 pinned for them (section 2)."""
    r1 = round1_lines(root)
    lines = []
    for f in own_files(root):
        full = os.path.join(root, f)
        if os.path.exists(full):
            lines.append(f"{sha256_file(full)}  {f}")
    for f in (engine_files() if files is None else files):
        lines.append(f"{r1.get(f, '?' * 64)}  {f}")
    return lines


def check_pin(step: str, root: str = ROOT, files: list | None = None) -> dict:
    """Refuse unless round 2's pin holds the design hash first, every listed file matches, every file of ``pinlist``
    is listed, the engine lines equal round 1's, and (select) picks.json is not pinned yet / (test) it is."""
    path = os.path.join(root, R2_PIN)
    if not os.path.exists(path):
        raise RuntimeError(f"{R2_PIN} does not exist")
    rows = read_lines(path)
    bad = []
    if not rows or rows[0][1] != DESIGN:
        bad.append("the first line is not the design hash of PREREG_HUNT_R2.md")
    listed = {}
    for h, p in rows:
        listed[p] = h
        full = os.path.join(root, p)
        if not os.path.exists(full):
            bad.append(f"missing {p}")
        elif sha256_file(full) != h:
            bad.append(f"changed {p}")
    for f in own_files(root):
        if f not in listed and os.path.exists(os.path.join(root, f)) and not f.startswith("research/hunt_r2/out/"):
            bad.append(f"not pinned {f}")
    for f in (COUNTS, BENCH):
        if f not in listed:
            bad.append(f"not pinned {f} (11: written and pinned before any data is read)")
    eng = engine_files() if files is None else files
    eng_lines = {f: listed.get(f) for f in eng}
    bad += engine_problems(eng, eng_lines, root)
    if step == "select" and PICKS in listed:
        bad.append(f"{PICKS} is already pinned: select ran; the picks do not change")
    if step == "test" and PICKS not in listed:
        bad.append(f"{PICKS} is not pinned: run select first")
    if bad:
        raise RuntimeError(f"{R2_PIN} does not match: " + "; ".join(bad))
    return {"pin_file": R2_PIN, "pin_sha256": sha256_file(path), "files": len(rows)}


def append_line(rel: str, root: str = ROOT) -> str:
    h = sha256_file(os.path.join(root, rel))
    with open(os.path.join(root, R2_PIN), "a") as fh:
        fh.write(f"{h}  {rel}\n")
    return h
