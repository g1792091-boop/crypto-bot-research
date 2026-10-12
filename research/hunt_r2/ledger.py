"""Program-wide ledger (PREREG_HUNT_R2.md section 8, 10.2, T2 13's rule): a dated snapshot with three prints, each
with a global Benjamini-Hochberg at q = 0.10, Holm at 0.05 and its m.

* **(A) tested:** every test-period hypothesis of the hunt program with a p on the snapshot date: the v1 pick; every
  tested wide pick; every round-1 read that prints a test-period p (the r = 1% line of each tested pick, H 13 / W 7;
  O4's R6 (e) momentum-control p per row, W 7.4a); track 2's tested picks (p = 1 when T0 fails, as its own family);
  round 2's p (7.1) and p_tune (7.2), and round 2's own read p-values once its reads exist (the r = 1% line of each
  row, 9.2, and O4's R6 (e) p per row, 9.2 / W 7.4a), as round 1's. Picks that are hashed but not yet tested are
  listed separately, not in m.
* **(A+):** (A) plus the full grid's 711 test-period hypotheses (p from its published confirm file when given and
  readable, else 1) and the 38 F4 watch picks at p = 1.
* **(L) live gate:** (A+) plus every confirm look whose pre-registration is hashed but not yet run, at its maximum
  number of hypotheses with p = 1 (so deciding early buys nothing); round 2's reads that print a p count here at their
  maximum until they exist. Every ``research/*/*.sha256`` of the checkout must be in the pinned registry
  (``ledger_registry.json``) or named by a ``--ledger-extra`` row ("prereg"); otherwise (L) is printed "incomplete"
  (no rejection, no live-gate pass) until the new study is registered with its maximum.

Inputs (8): each study's public test.json and reads files, read at their fixed paths; DeepSeek p-values from the
private files the owners copy to the server (``--ledger-private DIR``): each file's sha256 must equal the hash printed
in that study's public output, and only the p-value fields of its confirm rows are read (never a read's or R22's
per-system numbers). A missing or mismatched file gives p = 1 for its rows, listed "p not available". Round 2 opens
none of these files outside the server's test step and the ``ledger`` recompute; tests use temporary trees.

D11: DeepSeek rows show their id, study and labels in public; their p only in the private part.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hunt import hunt as H  # noqa: E402

BH_Q, HOLM_ALPHA = 0.10, 0.05
FG_FAMILY = 711                              # 8 / FG 4-6: the full grid's 711 test-period picks
FG_MIN_TEST = 100                            # research/fullgrid/run.MIN_TEST (a pick with fewer test trades: p = 1)
R1_V1_TEST = "research/hunt/out/v1/test.json"
R1_WIDE_TEST = "research/hunt/out/wide/test.json"
R1_WIDE_READS_O = "research/hunt/out/wide/reads_o.json"
R1_PIN = {"v1": "research/hunt/PREREG_HUNT.sha256", "wide": "research/hunt/PREREG_HUNT_WIDE.sha256"}
T2_PIN = "research/hiwr/PREREG_HIWR.sha256"
T2_PICKS = "research/hiwr/picks.json"
T2_TEST = "research/hiwr/out/test.json"
T2_MAX = 315                                 # T2 11: K = 1 per cell, up to 315 picks
R2_PIN = "research/hunt_r2/PREREG_HUNT_R2.sha256"
R2_PICKS = "research/hunt_r2/out/picks.json"
R2_TEST = "research/hunt_r2/out/test.json"
R2_READS_ROWS = "research/hunt_r2/out/reads_rows.json"
R2_READS_O = "research/hunt_r2/out/reads_weekend.json"
R2_READS_PRIVATE = {R2_READS_ROWS: "r2_rows_private.json", R2_READS_O: "r2_reads_o_private.json"}
REGISTRY = "research/hunt_r2/ledger_registry.json"
LEDGER_EXTRA = "research/hunt_r2/ledger_extra.json"
F4_WATCH = "research/fullgrid/diag/watch_sel.json"
PRIVATE_FILES = {R1_WIDE_TEST: "wide_test_private.json", T2_TEST: "test_private.json"}
MAX_HYP = {"hunt v1": 2, "hunt wide": 30 + 30 + 33, "hunt-r2 v1": 30 * 2 + 30 + 32, "track 2 (hiwr v1)": T2_MAX}
MAX_NOTE = {"hunt v1": "the v1 pick and its r = 1% line",
            "hunt wide": "30 picks, their 30 r = 1% lines and 33 O4 (e) rows (30 picks, the v1 pick, 2 baskets)",
            "hunt-r2 v1": "30 picks x (p, p_tune), their 30 r = 1% lines and 32 O4 (e) rows (30 picks, 2 baskets)",
            "track 2 (hiwr v1)": "K = 1 per cell, up to 315 picks (T2 11)"}
NOTES = ["Four studies share one 33-month period (2024-01 .. 2026-09): hunt v1 / wide, track 2, round 2 and the full "
         "grid's custom values.",
         "Round 1's rows keep their own p: its month bootstrap had 10,000 resamples (floor about 1e-4) and no t_32 guard.",
         "Track 2's rows enter p = max(p_boot, p_a, p_b) (100,000 seeds, floor about 1e-5); p = 1 when T0 fails.",
         "Round 2's rows enter p (7.1) and p_tune (7.2), each the larger of a 100,000-resample bootstrap p and the "
         "one-sided t_32 p.",
         "The ledger changes no verdict of any study (8); print (L) is the live gate of 10.2 for round-2 정식 picks.",
         "Beside track 2's own ledger (T2 13, research/hiwr): the same round-1 and track-2 confirm rows enter with the "
         "same ids and p (a parity test checks it). Intended differences: this ledger enters p = 1 for a row whose p is "
         "missing (listed 'p not available') where track 2's prints 'incomplete'; it adds round 1's and round 2's read "
         "p-values (r = 1% line, O4 (e)), the full grid's 711 and the 38 F4 picks (A+) and the hashed-not-run looks at "
         "their maximum (L)."]


def holm(pvals, alpha: float = HOLM_ALPHA) -> list:
    """Holm step-down at ``alpha`` (None counts as 1)."""
    p = [1.0 if (x is None or not np.isfinite(x)) else float(x) for x in pvals]
    m = len(p)
    out = [False] * m
    for r, i in enumerate(sorted(range(m), key=lambda i: p[i])):
        if p[i] <= alpha / (m - r):
            out[i] = True
        else:
            break
    return out


def bh(pvals, q: float = BH_Q) -> list:
    return H.bh(pvals, q)


def sha256_or_none(path: str):
    return H.sha256_file(path) if os.path.exists(path) else None


def _load(path: str):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def private_doc(public: dict, rel: str, priv_dir: str | None) -> tuple:
    """(doc, status) of the private file next to a public output: read only when its sha256 equals the public
    output's ``private_sha256``."""
    if not priv_dir:
        return None, "no private folder given"
    path = os.path.join(priv_dir, PRIVATE_FILES[rel])
    if not os.path.exists(path):
        return None, f"{PRIVATE_FILES[rel]} absent"
    want = (public or {}).get("private_sha256")
    got = H.sha256_file(path)
    if not want or got != want:
        return None, f"{PRIVATE_FILES[rel]} sha256 {got[:12]} differs from the public output's {str(want)[:12]}"
    return _load(path), "private file sha256 checked"


def _row(rid: str, study: str, kind: str, p, deepseek: bool, source: str, status: str | None = None,
         note: str | None = None) -> dict:
    ok = p is not None and np.isfinite(float(p))
    st = status or ("published" if ok else "p not available")
    if not ok and "not available" not in st and "p = 1" not in st:
        st += "; p not available: p = 1"
    r = {"id": rid, "study": study, "kind": kind, "p": float(p) if ok else 1.0, "deepseek": bool(deepseek),
         "source": source, "p_status": st}
    if note:
        r["note"] = note
    return r


# ------------------------------------------------------------------ round 1 (hunt v1, wide and its reads)
def round1_rows(root: str, priv_dir: str | None) -> tuple:
    """(tested rows, listed-only rows, inputs, looks, pending) of hunt v1 and wide."""
    rows, listed, inputs, looks, pending = [], [], [], [], []
    p1 = os.path.join(root, R1_V1_TEST)
    v1 = _load(p1)
    inputs.append({"file": R1_V1_TEST, "sha256": sha256_or_none(p1)})
    if v1 is not None:
        pid = (v1.get("pick") or {}).get("id", "hunt v1 pick")
        rows.append(_row(pid, "hunt v1", "confirm", ((v1.get("result") or {}).get("checks") or {}).get("p"), False,
                         R1_V1_TEST))
        r1 = (((v1.get("reads") or {}).get("r1") or {}).get("checks") or {}).get("p")
        rows.append(_row(f"{pid} r=1%", "hunt v1", "read (r = 1% line)", r1, False, R1_V1_TEST))
        looks.append({"study": "hunt v1", "look": "confirm", "status": "run"})
    pw = os.path.join(root, R1_WIDE_TEST)
    wide = _load(pw)
    inputs.append({"file": R1_WIDE_TEST, "sha256": sha256_or_none(pw)})
    if wide is not None:
        priv, pst = private_doc(wide, R1_WIDE_TEST, priv_dir)
        inputs.append({"file": f"(private) {PRIVATE_FILES[R1_WIDE_TEST]}", "status": pst})
        for p in wide.get("picks") or []:
            pid = p["id"]
            ds = p.get("kind") == "ds"
            chk = ((wide.get("results") or {}).get(pid) or {}).get("checks") or {}
            pv, st = chk.get("p"), None
            if pv is None and ds:
                pv = ((((priv or {}).get("results") or {}).get(pid) or {}).get("checks") or {}).get("p")
                st = "private file (sha256 checked)" if pv is not None else f"p not available ({pst})"
            rows.append(_row(pid, "hunt wide", "confirm", pv, ds, R1_WIDE_TEST, st))
            rd = ((wide.get("reads") or {}).get(pid) or {})
            r1 = ((rd.get("r1") or {}).get("checks") or {}).get("p")
            rows.append(_row(f"{pid} r=1%", "hunt wide", "read (r = 1% line)", r1, ds, R1_WIDE_TEST,
                             None if r1 is not None else "p not available (DeepSeek read: private, not read (8))"
                             if ds else None))
        for b in (wide.get("verdict") or {}).get("batches") or []:
            looks.append({"study": "hunt wide", "look": f"batch {b.get('batch')}", "status": "run"})
        for u in wide.get("untested") or []:
            uid = u["id"] if isinstance(u, dict) else str(u)
            listed.append({"id": uid, "study": "hunt wide", "status": "untested by the batch rule (never runs)"})
        po = os.path.join(root, R1_WIDE_READS_O)
        ro = _load(po)
        inputs.append({"file": R1_WIDE_READS_O, "sha256": sha256_or_none(po)})
        if ro is not None:
            for rid, r in ((ro.get("out") or {}).get("rows") or {}).items():
                e = ((((r.get("periods") or {}).get("test") or {}).get("O4") or {}).get("e") or {})
                ds = "note" in r and "DeepSeek" in str(r.get("note"))
                rows.append(_row(f"{rid} O4 (e)", "hunt wide", "read (O4, R6 (e))", e.get("p_boot"), ds,
                                 R1_WIDE_READS_O, None if e.get("p_boot") is not None else
                                 "p not available (DeepSeek read: private, not read (8))" if ds else None))
            for o in ("O1", "O2", "O3", "O4"):
                looks.append({"study": "hunt wide", "look": f"read {o}", "status": "run"})
        else:                                   # O4 (e) prints a p per row: a look not yet run, at its maximum
            n = len(wide.get("picks") or []) + 3
            pending.append({"study": "hunt wide reads O4", "hypotheses": n,
                            "why": "reads_o.json absent: one O4 (e) p per tested pick, the v1 pick and 2 baskets"})
    return rows, listed, inputs, looks, pending


# ------------------------------------------------------------------ track 2
def track2_rows(root: str, priv_dir: str | None, pub_root: str | None = None) -> tuple:
    rows, listed, inputs, looks, pending = [], [], [], [], []
    pt = os.path.join(pub_root or root, T2_TEST)
    doc = _load(pt)
    inputs.append({"file": T2_TEST, "sha256": sha256_or_none(pt)})
    hashed = os.path.exists(os.path.join(root, T2_PIN))
    if doc is not None:
        priv, pst = private_doc(doc, T2_TEST, priv_dir)
        inputs.append({"file": f"(private) {PRIVATE_FILES[T2_TEST]}", "status": pst})
        for pid, blk in (doc.get("results") or {}).items():
            chk = blk.get("checks") or {}
            ds = "p" not in blk                     # track 2's public file leaves a DeepSeek pick's p out (D11)
            pv, st = blk.get("p"), None
            if pv is None and ds:
                pv = (((priv or {}).get("results") or {}).get(pid) or {}).get("p")
                st = "private file (sha256 checked)" if pv is not None else f"p not available ({pst})"
            if chk.get("T0") is False:
                pv, st = 1.0, "T0 fails: p = 1 (T2 12)"
            rows.append(_row(pid, "track 2 (hiwr v1)", "confirm", pv, ds, T2_TEST, st))
        looks.append({"study": "track 2 (hiwr v1)", "look": "confirm", "status": "run"})
    elif hashed:
        pk = _load(os.path.join(pub_root or root, T2_PICKS)) or _load(os.path.join(root, T2_PICKS))
        n = len(pk) if isinstance(pk, list) else len((pk or {}).get("picks") or []) if pk else None
        for i in range(n or 0):
            listed.append({"id": f"track 2 pick {i + 1}", "study": "track 2 (hiwr v1)",
                           "status": "hashed, not yet tested"})
        pending.append({"study": "track 2 (hiwr v1)", "hypotheses": n if n else T2_MAX,
                        "why": "picks hashed, test not run" if n else "pre-registration hashed, select not run"})
        looks.append({"study": "track 2 (hiwr v1)", "look": "confirm", "status": "pending"})
    return rows, listed, inputs, looks, pending


# ------------------------------------------------------------------ round 2 (this study)
def round2_row_ids(test_full: dict | None) -> list:
    """9.1 ROWS of round 2 (as reads_r2.rows_of): every tested pick, the batch-1 basket when K >= 2, the passing basket
    when at least two pass."""
    picks = list((test_full or {}).get("picks") or [])
    ids = [f"pick:{p['id']}" for p in picks]
    if sum(1 for p in picks if int(p.get("batch", 1)) == 1) >= 2:
        ids.append("basket_batch1")
    if len(((test_full or {}).get("verdict") or {}).get("passing") or []) >= 2:
        ids.append("basket_passing")
    return ids


def _r2_read_private(root: str, rel: str, pub: dict, r2_private: str | None) -> tuple:
    if not r2_private:
        return None, "round 2's private folder not given"
    path = os.path.join(r2_private, R2_READS_PRIVATE[rel])
    if not os.path.exists(path):
        return None, f"{R2_READS_PRIVATE[rel]} absent"
    if H.sha256_file(path) != (pub or {}).get("private_sha256"):
        return None, f"{R2_READS_PRIVATE[rel]} sha256 differs from {os.path.basename(rel)}'s private_sha256"
    return _load(path), "private file sha256 checked"


def round2_rows(test_full: dict | None, root: str | None = None, r2_private: str | None = None) -> tuple:
    """Round 2's p (7.1) and p_tune (7.2) of every tested pick, from the test step's full blocks; and, once its reads
    exist, the r = 1% line p of every row (reads_rows.json) and O4's R6 (e) p per row (reads_weekend.json), DeepSeek
    rows from round 2's private reads files after their sha256 check. Returns (rows, inputs, pending): a read not yet
    written counts in (L) at its maximum."""
    rows, inputs, pending = [], [], []
    picks = (test_full or {}).get("picks") or []
    ds_of = {}
    for p in picks:
        blk = test_full["results"][p["id"]]
        ds = p.get("family") == "F3" or p.get("kind") == "ds"
        ds_of[f"pick:{p['id']}"] = ds
        rows.append(_row(p["id"], "hunt-r2 v1", "confirm (R2 PASS, 7.1)", blk["checks"].get("p"), ds, R2_TEST,
                         "this test step"))
        rows.append(_row(f"{p['id']} tune", "hunt-r2 v1", "confirm (TUNED BETTER, 7.2)", blk["tune"].get("p_tune"),
                         ds, R2_TEST, "this test step"))
    if not picks or root is None:
        return rows, inputs, pending
    rids = round2_row_ids(test_full)
    for rid in rids:
        if rid.startswith("basket"):
            ds_of[rid] = any(p.get("family") == "F3" or p.get("kind") == "ds" for p in picks)
    for rel, kind, path_of, why in (
            (R2_READS_ROWS, "read (r = 1% line, 9.2)", lambda r: ((r.get("r1_line") or {}).get("checks") or {}).get("p"),
             "one r = 1% line p per row (9.2)"),
            (R2_READS_O, "read (O4, R6 (e), 9.2)",
             lambda r: ((((r.get("periods") or {}).get("test") or {}).get("O4") or {}).get("e") or {}).get("p_boot"),
             "one O4 (e) p per row (9.2)")):
        full = os.path.join(root, rel)
        doc = _load(full)
        inputs.append({"file": rel, "sha256": sha256_or_none(full)})
        if doc is None:
            pending.append({"study": f"hunt-r2 v1 reads {os.path.basename(rel)}", "hypotheses": len(rids),
                            "why": f"{os.path.basename(rel)} absent: {why}, at its maximum"})
            continue
        out_rows = ((doc.get("out") or {}).get("rows") or {})
        priv, pst = (None, None)
        if any(ds_of.get(r) for r in rids):
            priv, pst = _r2_read_private(root, rel, doc, r2_private)
            inputs.append({"file": f"(private) {R2_READS_PRIVATE[rel]}", "status": pst})
        priv_rows = ((priv or {}).get("rows") or {}) if priv else {}
        for rid in rids:
            r = out_rows.get(rid) or {}
            pv, st = path_of(r), None
            if pv is None and ds_of.get(rid):
                pv = path_of(priv_rows.get(rid) or {})
                st = "private file (sha256 checked)" if pv is not None else f"p not available ({pst})"
            rows.append(_row(f"{rid} {'r=1%' if rel == R2_READS_ROWS else 'O4 (e)'}", "hunt-r2 v1", kind, pv,
                             bool(ds_of.get(rid)), rel, st))
    return rows, inputs, pending


# ------------------------------------------------------------------ the registry of hashed pre-registrations (L)
def registry(root: str) -> dict:
    return (_load(os.path.join(root, REGISTRY)) or {}).get("files") or {}


def unregistered(root: str, extra_preregs: set) -> list:
    """Every research/*/*.sha256 of the checkout that the pinned registry does not know (or whose first line, the
    design hash, differs from the registry's) and no --ledger-extra row names: print (L) is then incomplete."""
    import glob
    reg = registry(root)
    out = []
    for full in sorted(glob.glob(os.path.join(root, "research", "*", "*.sha256"))):
        rel = os.path.relpath(full, root)
        if rel in extra_preregs:
            continue
        first = None
        try:
            with open(full) as fh:
                for ln in fh:
                    if ln.strip():
                        first = ln.split()[0]
                        break
        except OSError:
            first = None
        known = reg.get(rel)
        if known is None:
            out.append({"file": rel, "why": "not in the registry"})
        elif known.get("first_line_sha256") and known["first_line_sha256"] != first:
            out.append({"file": rel, "why": "its first line (design hash) differs from the registry's"})
    return out


# ------------------------------------------------------------------ full grid and F4 (A+)
def fullgrid_rows(confirm_path: str | None, root: str) -> tuple:
    """The full grid's 711 test-period hypotheses: p from its confirm.json rows (test.p, p = 1 below 100 test trades)
    when the file is given and readable, else p = 1 each; plus the 38 F4 watch picks at p = 1."""
    rows, inputs = [], []
    doc = _load(confirm_path) if confirm_path else None
    got = (doc or {}).get("rows") if isinstance(doc, dict) else None
    if got:
        inputs.append({"file": confirm_path, "sha256": H.sha256_file(confirm_path), "rows": len(got)})
        for i, r in enumerate(got):
            t = r.get("test") or {}
            pv = t.get("p") if (t.get("n") or 0) >= FG_MIN_TEST else 1.0
            rid = f"fullgrid:{r.get('kind')}:{r.get('name')}:{r.get('tf')}:{r.get('rank', i)}"
            rows.append(_row(rid, "full grid", "confirm (custom values, 2024-2026)", pv, r.get("kind") == "ds",
                             "full grid confirm.json", None if pv is not None else "p not available"))
        if len(got) != FG_FAMILY:
            inputs[-1]["note"] = f"{len(got)} rows, not {FG_FAMILY}"
    else:
        inputs.append({"file": confirm_path or "(not given)", "status": "not readable: 711 rows at p = 1"})
        for i in range(FG_FAMILY):
            rows.append(_row(f"fullgrid:{i + 1}", "full grid", "confirm (custom values, 2024-2026)", None, False,
                             "full grid (results file not given)", "p not available: p = 1"))
    wl = _load(os.path.join(root, F4_WATCH))
    n4 = len(wl) if isinstance(wl, list) else 38
    for i in range(n4):
        rows.append(_row(f"F4 watch {i + 1}", "full grid F4 watch picks", "watch pick (seen on 2024-2026)", 1.0,
                         False, F4_WATCH, "p = 1 by rule (8)"))
    return rows, inputs


# ------------------------------------------------------------------ pending looks (L)
def pending_looks(root: str, have: set, r2_tested: bool) -> list:
    """Every confirm look whose pre-registration is hashed but not yet run, at its maximum number of hypotheses."""
    out = []
    if os.path.exists(os.path.join(root, R1_PIN["v1"])) and "hunt v1" not in have:
        out.append({"study": "hunt v1", "hypotheses": MAX_HYP["hunt v1"], "why": MAX_NOTE["hunt v1"]})
    if os.path.exists(os.path.join(root, R1_PIN["wide"])) and "hunt wide" not in have:
        out.append({"study": "hunt wide", "hypotheses": MAX_HYP["hunt wide"], "why": MAX_NOTE["hunt wide"]})
    if os.path.exists(os.path.join(root, R2_PIN)) and not r2_tested:
        pk = _load(os.path.join(root, R2_PICKS))
        n = len((pk or {}).get("picks") or []) if pk else None
        if pk is None or n:
            b1 = len(((pk or {}).get("batches") or [[]])[0]) if n else 0
            rows = (n or 0) + (1 if b1 >= 2 else 0) + (1 if (n or 0) >= 2 else 0)
            out.append({"study": "hunt-r2 v1", "hypotheses": 2 * n + 2 * rows if n else MAX_HYP["hunt-r2 v1"],
                        "why": "picks hashed, test not run: picks x (p, p_tune) and each row's r = 1% line and O4 (e) "
                               "(rows = picks and baskets)" if n else MAX_NOTE["hunt-r2 v1"]})
    return out


def extra_rows(path: str | None) -> tuple:
    """``--ledger-extra``: a JSON list of {id, study, p, deepseek, status ('tested' | 'pending'), hypotheses}."""
    if not path:
        return [], [], []
    doc = _load(path) or []
    rows, pending = [], []
    for r in doc:
        if r.get("status") == "pending":
            pending.append({"study": str(r.get("study", r.get("id"))), "hypotheses": int(r.get("hypotheses", 1)),
                            "why": "--ledger-extra", "prereg": r.get("prereg")})
        else:
            rows.append(_row(str(r["id"]), str(r.get("study", "extra")), str(r.get("kind", "confirm")), r.get("p"),
                             bool(r.get("deepseek", False)), path))
            if r.get("prereg"):
                rows[-1]["prereg"] = r["prereg"]
    return rows, pending, [{"file": path, "sha256": H.sha256_file(path) if os.path.exists(path) else None}]


# ------------------------------------------------------------------ the three prints
def one_print(rows: list, incomplete: list | None = None) -> dict:
    """BH and Holm over ``rows``; with ``incomplete`` (hashed pre-registrations the ledger cannot count) nothing is
    rejected and the print says so."""
    if incomplete:
        out = [dict(r, bh_q10=None, holm_005=None) for r in rows]
        return {"m": len(out), "status": "incomplete", "missing": incomplete, "bh_rejections": None,
                "holm_rejections": None, "rows": out}
    pv = [r["p"] for r in rows]
    b, h = bh(pv, BH_Q), holm(pv, HOLM_ALPHA)
    out = [dict(r, bh_q10=bool(x), holm_005=bool(y)) for r, x, y in zip(rows, b, h)]
    return {"m": len(out), "status": "complete", "bh_rejections": [r["id"] for r in out if r["bh_q10"]],
            "holm_rejections": [r["id"] for r in out if r["holm_005"]], "rows": out}


def snapshot(root: str = ROOT, priv_dir: str | None = None, r2_full: dict | None = None,
             fullgrid_confirm: str | None = None, extra: str | None = None, when: dt.datetime | None = None,
             public_root: str | None = None, r2_private: str | None = None) -> dict:
    """The dated ledger (full: every p). ``r2_full`` = round 2's full test document (None before its test).
    ``public_root`` = where the other studies' public outputs lie under their repository paths (default: the
    repository; on the round-2 server, the folder the server kit fetches the results branches into).
    ``r2_private`` = round 2's own private folder (its DeepSeek read p-values). ``extra`` defaults to the pinned
    research/hunt_r2/ledger_extra.json."""
    when = when or dt.datetime.now(dt.timezone.utc)
    if extra is None and os.path.exists(os.path.join(root, LEDGER_EXTRA)):
        extra = os.path.join(root, LEDGER_EXTRA)
    r1, listed, inputs, looks, pend1 = round1_rows(public_root or root, priv_dir)
    t2, l2, in2, lk2, pend2 = track2_rows(root, priv_dir, public_root)
    r2, in_r2, pend_r2 = round2_rows(r2_full, root, r2_private)
    ex, pend_x, in_x = extra_rows(extra)
    pre_x = {r.get("prereg") for r in ex + pend_x if r.get("prereg")}
    missing = unregistered(root, pre_x)
    have = {r["study"] for r in r1}
    A_rows = r1 + t2 + r2 + ex
    if r2_full is not None:
        looks.append({"study": "hunt-r2 v1", "look": "confirm (picks and their anchor-default comparators)",
                      "status": "run" if r2_full.get("picks") else "not run: selection failed"})
        for o in ("O1", "O1b", "O4"):
            looks.append({"study": "hunt-r2 v1", "look": f"read {o} on round-2 rows",
                          "status": "after the verdict" if r2_full.get("picks") else "not run"})
    looks += lk2
    fg, in_fg = fullgrid_rows(fullgrid_confirm, root)
    Aplus = A_rows + fg
    pend = pending_looks(root, have, r2_full is not None) + pend1 + pend2 + pend_r2 + pend_x
    L_rows = list(Aplus)
    for pnd in pend:
        for i in range(int(pnd["hypotheses"])):
            L_rows.append(_row(f"{pnd['study']} pending {i + 1}", pnd["study"], "hashed, not yet run (p = 1)", 1.0,
                               False, "pending look", "p = 1 by rule (8)"))
    prints = {"A": one_print(A_rows), "A+": one_print(Aplus), "L": one_print(L_rows, missing)}
    for k, txt in (("A", "tested: every test-period hypothesis of the hunt program with a p on this date"),
                   ("A+", "tested + the full grid's 711 and the 38 F4 watch picks (p = 1)"),
                   ("L", "live gate: A+ plus every hashed-but-not-run confirm look at its maximum, p = 1")):
        prints[k]["what"] = txt
    gate = {}
    if r2_full is not None:
        lrej = set(prints["L"]["bh_rejections"] or [])
        for pid in (r2_full.get("verdict") or {}).get("passing") or []:
            if missing:
                gate[pid] = {"passes_print_L": False, "label": "정식 (장부 미완성: 등록 안 된 사전 등록이 있음)"}
                continue
            gate[pid] = {"passes_print_L": pid in lrej,
                         "label": "정식" if pid in lrej else "정식 (장부 미통과)"}
    return {"what": "PREREG_HUNT_R2 8: program-wide ledger snapshot (global BH q = 0.10, Holm 0.05)",
            "date_utc": when.isoformat(), "q": BH_Q, "holm_alpha": HOLM_ALPHA, "prints": prints,
            "listed_not_counted": listed + l2, "pending_looks_in_L": pend, "looks": looks,
            "looks_count": sum(1 for x in looks if x["status"] in ("run", "after the verdict")),
            "round2_live_gate": gate, "inputs": inputs + in2 + in_r2 + in_fg + in_x, "notes": NOTES,
            "registry": {"file": REGISTRY, "sha256": sha256_or_none(os.path.join(root, REGISTRY)),
                         "unregistered": missing},
            "line": "four studies share one 33-month period"}


def public_of(full: dict) -> dict:
    """D11: DeepSeek rows without their p (labels and the BH / Holm flags stay)."""
    out = dict(full)
    out["prints"] = {}
    for k, pr in full["prints"].items():
        out["prints"][k] = dict(pr, rows=[{kk: vv for kk, vv in r.items() if not (r["deepseek"] and kk == "p")}
                                          for r in pr["rows"]])
    return out
