"""Hunt round 2 pin (PREREG_HUNT_R2.md section 2, 0.3, 11): the read-only inputs round 2 imports, each with the sha256
round 1 pinned for it, and round 2's own code pin.

``engine_files()`` = hunt.py, entries_wide.py, universe30.json, exchange30.json, data_manifest.json, regime5y.py,
fullgrid/memo.py, deepseek200/lib_c.py, the pin files fullgrid/PREREG.sha256, entry_study/DEFS_BC.sha256 and
third_party/sweep/PREREG.sha256, and every file ``hunt.signal_path_files("wide")`` returns (round 2's own modules
excluded: they are pinned by round 2's own lines). ``READ_INPUTS`` = the other round-1 files round 2 reads: the reads
modules reads_a.py / reads_o.py (section 9, "as round 1"), the synthetic window timing bench_window.json and the F4
watch list (labels, ledger count). ``round1_lines()`` reads round 1's pin lines for those files from
``research/hunt/PREREG_HUNT_WIDE.sha256`` (never hashing that file itself, which round 1 appends to, and never a line
under ``research/hunt/out/``); the last line of a path counts (an engine fix inherited under 0.3 appends a line there
and replaces the line in round 2's pin). ``engine_problems`` lists every difference; every step refuses on any.

``pinlist()`` prints the code pin's lines, each file by its own sha256 (11): this design, the code, the tests, the
server kit, counts.json, bench_r2.json and the read-only inputs. ``check_pin(step)`` refuses unless the design hash is
the first line, every listed file matches, every file of the pin list is listed, the inputs equal round 1's pinned
hashes, and the step's own lines are (not) there: select before picks.json; pretest and test after it; reads after
test.json.
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
READ_INPUTS = ("research/hunt/reads_a.py", "research/hunt/reads_o.py", "research/hunt/bench_window.json",
               "research/fullgrid/diag/watch_sel.json")
NEVER = (R1_PIN,)                          # 2: never hashed (round 1 appends to it)
# 0.3 blind code: round 2's pinned checkout holds no round-1 result (checked by existence only; never opened)
R1_RESULTS = tuple(f"research/hunt/out/{d}/{f}" for d in ("v1", "wide")
                   for f in ("select.json", "picks.json", "test.json", "reads_o.json", "reads_a.json")) + \
    ("research/hunt/results",)


def round1_results_in_tree(root: str = ROOT) -> list:
    """Round-1 result files present in the checkout (existence only; nothing is opened)."""
    return [p for p in R1_RESULTS if os.path.exists(os.path.join(root, p))]


def sha256_file(path: str) -> str:
    from research.hunt import hunt as H
    return H.sha256_file(path)


def engine_files() -> list:
    """Section 2's list plus the read inputs (each must equal round 1's pinned hash)."""
    from research.hunt import hunt as H
    sp = [p for p in H.signal_path_files("wide") if not p.startswith("research/hunt_r2/")]
    out = sorted(set(FIXED) | set(sp) | set(READ_INPUTS))
    bad = [p for p in out if p in NEVER or p.startswith(R1_OUT)]
    if bad:
        raise RuntimeError(f"round 2 never pins {bad} (section 2)")
    return out


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
    path = os.path.join(root, R1_PIN)
    if not os.path.exists(path):
        return out                                 # every input then reads "not pinned by round 1"
    for h, p in read_lines(path):
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
PRETEST = "research/hunt_r2/out/pretest_reads.json"
TEST = "research/hunt_r2/out/test.json"
STEPS = ("select", "pretest", "test", "reads", "report")
COUNTS = "research/hunt_r2/counts.json"
BENCH = "research/hunt_r2/bench_r2.json"
KIT = ("research/hunt_r2/bootstrap_r2.sh", "research/hunt_r2/wait_go_r2.sh", "research/hunt_r2/SERVER_R2_KO.md")


def own_files(root: str = ROOT) -> list:
    """Round 2's own files the code pin lists (11): the design, the code, its JSON inputs (counts.json, bench_r2.json,
    the full grid's select picks, the ledger registry and extra list), the tests and the server kit (each when it
    exists; counts.json and bench_r2.json are required by ``check_pin``)."""
    out = [DESIGN, COUNTS, BENCH]
    d = os.path.join(root, "research", "hunt_r2")
    if os.path.isdir(d):
        out += [f"research/hunt_r2/{f}" for f in sorted(os.listdir(d))
                if f.endswith(".json") and f"research/hunt_r2/{f}" not in (COUNTS, BENCH)]
        out += [f"research/hunt_r2/{f}" for f in sorted(os.listdir(d)) if f.endswith(".py")]
    t = os.path.join(root, "tests")
    out += [f"tests/{f}" for f in sorted(os.listdir(t)) if f.startswith("test_hunt_r2") and f.endswith(".py")] \
        if os.path.isdir(t) else []
    out += [k for k in KIT if os.path.exists(os.path.join(root, k))]
    return out


def pinlist(root: str = ROOT, files: list | None = None) -> list:
    """'<sha256>  <path>' lines of the code pin (11), each file by its own sha256: round 2's own files, then the
    read-only inputs (section 2; ``pinlist_problems`` says whether each equals round 1's pinned hash). Never
    PREREG_HUNT_WIDE.sha256, never a file under research/hunt/out/."""
    lines = []
    seen = set()
    for f in own_files(root) + sorted(engine_files() if files is None else files):
        if f in seen or f in NEVER or f.startswith(R1_OUT) or f.startswith("research/hunt_r2/out/"):
            continue
        seen.add(f)
        full = os.path.join(root, f)
        if os.path.exists(full):
            lines.append(f"{sha256_file(full)}  {f}")
    return lines


def pinlist_problems(root: str = ROOT, files: list | None = None) -> list:
    """The inputs whose own hash differs from round 1's pinned hash (or that round 1 never pinned), and any round-1
    result in the checkout (0.3)."""
    return engine_problems(files, None, root) + [f"round-1 output in the checkout (0.3: the pinned commit holds none): {p}"
                                                 for p in round1_results_in_tree(root)]


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
    if step not in STEPS:
        raise ValueError(f"step {step!r}")
    if step == "select" and PICKS in listed:
        bad.append(f"{PICKS} is already pinned: select ran; the picks do not change")
    if step == "select":
        bad += [f"round-1 output in the checkout (0.3: round 2's pinned commit holds none; fetch the ledger inputs at "
                f"the test step instead): {p}" for p in round1_results_in_tree(root)]
    if step in ("pretest", "test", "reads") and PICKS not in listed:
        bad.append(f"{PICKS} is not pinned: run select first")
    if step == "test" and TEST in listed:
        bad.append(f"{TEST} is already pinned: the confirm look happened (one look, 7)")
    if step == "reads" and TEST not in listed:
        bad.append(f"{TEST} is not pinned: reads run only after the test step (9.1)")
    if bad:
        raise RuntimeError(f"{R2_PIN} does not match: " + "; ".join(bad))
    return {"pin_file": R2_PIN, "pin_sha256": sha256_file(path), "files": len(rows),
            "lines": {p: h for h, p in rows if p in (PICKS, PRETEST, TEST) or p.startswith("research/hunt_r2/")
                      or p in READ_INPUTS}}


def listed_now(root: str = ROOT) -> dict:
    """{path: sha256} of round 2's pin file right now ({} without one)."""
    path = os.path.join(root, R2_PIN)
    if not os.path.exists(path):
        return {}
    return {p: h for h, p in read_lines(path)}


def is_pinned(rel: str, root: str = ROOT) -> bool:
    """The file exists and its current sha256 is the last line of that path in round 2's pin."""
    full = os.path.join(root, rel)
    return bool(os.path.exists(full) and listed_now(root).get(rel) == sha256_file(full))


def append_line(rel: str, root: str = ROOT) -> str:
    h = sha256_file(os.path.join(root, rel))
    with open(os.path.join(root, R2_PIN), "a") as fh:
        fh.write(f"{h}  {rel}\n")
    return h
