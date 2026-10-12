"""Hunt round 2 reads after the verdict (PREREG_HUNT_R2.md section 9): reported, never a pass.

ROWS (9.1): every tested pick (pass or fail); the batch-1 all-K basket (one wallet, H 8 caps shared, same-close order
by 30-day quote volume then pick number, labelled "not a candidate") when K >= 2; the passing basket when at least two
pass. Three read modules run in this order, each only when its file is in round 2's pin with its current sha256:

* ``rows`` (this file, ``research/hunt_r2/out/reads_rows.json``): new 24 only (9.2, "carried by the old six"); extra
  2020 at r = 0.5% and 1%; the r = 1% line (P0-P4 and the four seed-rank parts, controls rerun at 1%) with its cost x2
  line; select-period controls seeds 1-200 ((a-c): every select-period shift); the correlation of monthly ln M with
  the anchor default's (R12 / R13 basics come from reads_a); R14 and R19 status.
* ``reads_o`` (round 1's pinned ``research/hunt/reads_o.py``, ``reads_weekend.json``): 9.3 weekend O1 / O1b beside
  the tested machine, select and test, controls (a) and (b) seeds 1-200 through the weekend-skip machine, the R1
  headline shares at the size fixed on select; O4 (f) and R6 (e) and the "momentum only" label (9.2). O2 never runs
  here (not a round-2 read, 8 counts O1, O1b and O4 only), and round 1's select map is not run (it is round 1's walk).
* ``reads_a`` (round 1's pinned ``research/hunt/reads_a.py``, ``reads_goal.json``): 9.5 R1 goal board, 9.4 R24 at
  20 / 30 / 40x, continuous accounts, R12 / R13 basics, R15.

Round 1's modules receive round 2's own context (reads interface api 1): ``signals``, ``control_signals`` and ``run``
take round 2's signal dicts only (``run`` refuses a spec dict), and ``hunt_module`` is a proxy of hunt.py whose
``cached_events`` returns round 2's events for a round-2 system (``confirm_r2.events_of``), so no round-2 system ever
reaches round 1's spec-based path (11). Control draws use round 2's seed parts ("hunt-r2", system id, control, period,
r, seed), the same draws the test step used.

Read guard (9.1, H 14 / W 7.1): a module runs only after test.json is in the pin; the code refuses to write
(ReadGuardError) when any file of research/hunt_r2/out or picks.json changed while it ran; a float under a DeepSeek row
of its public output refuses the write (D11); the reads stop at 12 hours wall: a module that would start later is
listed "not run: 12-hour wall reached".
"""

from __future__ import annotations

import contextlib
import copy
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hunt import hunt as H  # noqa: E402
from research.hunt import reads_a as RA  # noqa: E402
from research.hunt import reads_o as RO  # noqa: E402
from research.hunt_r2 import confirm_r2 as CF  # noqa: E402
from research.hunt_r2 import pin_r2 as PN  # noqa: E402
from research.hunt_r2 import select_r2 as SR  # noqa: E402

OUT_REL = "research/hunt_r2/out"
MODULES = {"rows": {"rel": "research/hunt_r2/reads_r2.py", "out": "reads_rows.json"},
           "reads_o": {"rel": RO.MODULE_REL, "out": "reads_weekend.json"},
           "reads_a": {"rel": "research/hunt/reads_a.py", "out": "reads_goal.json"}}
ORDER = ("rows", "reads_o", "reads_a")
WALL_S = 12 * 3600                      # 9.1: the reads stop at 12 hours wall
SELECT_SEEDS = 200                      # 9.2: select-period controls, seeds 1-200
STUDY = "hunt-r2"
DS_NOTE = "DeepSeek row: figures in the private file (D11)"
R14_R19 = {"R14": "forward band: not computed by round 2's code (it needs the paper bot's forward record; round 1's "
                  "code has no R14 module either); listed for passing picks only",
           "R19": "1m + mark fidelity: not computed by round 2's code (it needs a 1m download of the traded coins; "
                  "round 1's fidelity command takes round-1 specs only); listed for passing picks only"}
CHOICES = [
    "9: round 1's pinned reads modules (reads_a.py, reads_o.py) run unchanged on round 2's context: its signals, "
    "control draws (round 2's seed parts) and engine runs take round 2's signal dicts only; the hunt_module proxy "
    "answers cached_events with round 2's events for a round-2 system; the goal-board bootstrap seeds use reads_a's "
    "own tag rule (a study other than 'wide': tag 'hunt') with round 2's row ids.",
    "9.3 / 8: O2 (macro blackout) and round 1's O1 select-only map are not run (not round-2 reads; the select-period "
    "four-timeframe weekend table is section 6's); reads_o's calendar status is replaced by 'not a round-2 read'.",
    "9.2 r = 1% line: base and cost x2 at 1%, controls (a), (b), (b-c) seeds 1-1,000 and every (a-c) shift at 1%, "
    "checks as 7.1 (P0, P1, P3, P4, the four seed-rank parts, p = max(p_a, p_b)); no BH (a read).",
    "9.2 select-period controls: seeds 1-200 of (a), (b) and (b-c), every (a-c) shift of the select period, r = 0.5%.",
    "9.2 'carried by the old six': a passing pick whose new-24 test mean ln M is <= 0 (W 7.0).",
]


# ------------------------------------------------------------------ rows (9.1)
def rows_of(test_full: dict) -> list:
    tested = list(test_full.get("picks") or [])
    passing = set((test_full.get("verdict") or {}).get("passing") or [])
    rows = [{"row": f"pick:{p['id']}", "kind": "pick", "label": "pick", "members": [p],
             "src": [int(p.get("pick_no", 1))], "is_ds": CF.is_ds(p), "candidate": True} for p in tested]
    b1 = [p for p in tested if int(p.get("batch", 1)) == 1]
    if len(b1) >= 2:
        rows.append({"row": "basket_batch1", "kind": "basket_batch1", "label": "not a candidate", "members": b1,
                     "src": [int(p["pick_no"]) for p in b1], "is_ds": any(CF.is_ds(p) for p in b1),
                     "candidate": False})
    ps = [p for p in tested if p["id"] in passing]
    if len(ps) >= 2:
        rows.append({"row": "basket_passing", "kind": "basket_passing", "label": "passing basket", "members": ps,
                     "src": [int(p["pick_no"]) for p in ps], "is_ds": any(CF.is_ds(p) for p in ps),
                     "candidate": False})
    return rows


# ------------------------------------------------------------------ round 1's modules on round 2's context
class Live:
    """hunt.py as round 1's reads modules see it, except ``cached_events`` (round 2's events of a round-2 system)
    and ``wide_systems`` (round 1's list is not round 2's)."""

    def __getattr__(self, k):
        return getattr(H, k)

    @staticmethod
    def cached_events(spec: dict, sym: str) -> tuple:
        if not str(spec.get("id", "")).startswith("R2:"):
            raise ValueError("round 2's reads run round-2 systems only")
        return CF.events_of(spec, sym)

    @staticmethod
    def wide_systems() -> list:
        return []


def read_markets(syms: list) -> dict:
    new = [s for s in syms if s not in H.OLD_SIX]
    mks = {"test": H.Market(syms, "test"), "select": H.Market(syms, "select"), "extra": H.Market(syms, "extra"),
           "new_test": H.Market(new, "test"), "new_select": H.Market(new, "select")}
    for m in mks.values():
        H._G["mk"][m.key] = m
    return mks


def window_seconds(root: str = ROOT) -> tuple:
    """W 7.1's 0.03 s rule input: research/hunt/bench_window.json when round 2's pin lists it with its sha256."""
    rel = H.BENCH_WINDOW_REL
    if PN.is_pinned(rel, root):
        d = SR_load(os.path.join(root, rel))
        if d.get("window_run_30d_s") is not None:
            return float(d["window_run_30d_s"]), f"{rel} (synthetic bars, pinned)"
    return None, f"no pinned {rel}: rolling control seeds 1-100"


def SR_load(path: str) -> dict:
    try:
        return CF.load_json(path) or {}
    except (OSError, ValueError):
        return {}


def make_ctx(*, args, pin, mks: dict, syms: list, test_doc: dict, full: dict, reads_pin: dict,
             private_path: str, root: str = ROOT) -> dict:
    """Reads interface api 1 for round 1's modules, on round 2's rows and signals."""
    tested = list(full["picks"])
    passing = list(full["verdict"]["passing"])
    lineup = (full.get("lineup") or {}).get("picks", {})
    picks = [{**{k: p.get(k) for k in ("id", "family", "name", "strategy", "kind", "tf", "gate", "combo",
                                         "pick_no", "batch", "rank")},
              "label": "pick", "is_ds": CF.is_ds(p), "passed": p["id"] in passing,
              "lineup": (lineup.get(p["id"]) or {}).get("lineup"),
              "coins_traded": (full["results"][p["id"]].get("coins_traded") or [])} for p in tested]
    periods = {k: [H.day_ms(a), H.day_ms(b)] for k, (a, b) in H.PERIODS.items()}

    def market(start_ms, end_ms, syms_=None):
        return H.market_for(list(syms_ or syms), int(start_ms), int(end_ms), mks)

    def signals(spec, mk):
        return CF.signals(mk, spec)

    def control_signals(spec, ctl, period, r, seed):
        mk = mks[period]
        sig = CF.signals(mk, spec)
        rng = H.rng_of(*CF.seed_parts(spec["id"], ctl, mk.period, r, seed))
        c = H.control_a(mk, sig, rng) if ctl == "a" else H.control_b(sig, rng)
        c = {k: c[k] for k in ("tf", "k", "j", "side")}
        c["syms"] = list(mk.syms)
        return c

    def run(what, start_ms, end_ms, **kw):
        if isinstance(what, dict) or any(isinstance(x, dict) for x in what):
            raise ValueError("round 2 never passes a spec dict to round 1's engine path (11)")
        return H.run_engine(what, start_ms, end_ms, mks=mks, universe=syms, **kw)

    sec, sec_src = window_seconds(root)
    machine = {"defaults": {n: float(v) for n, v in zip(H.PR_NAMES, H.params())}, "index": dict(H.PR_INDEX)}
    return {"api": 1, "study": STUDY, "pin": pin, "reads_pin": reads_pin, "periods": periods, "syms": list(syms),
            "old_six": [s for s in H.OLD_SIX if s in syms], "new": [s for s in syms if s not in H.OLD_SIX],
            "picks": picks, "untested": [p["id"] for p in full.get("untested") or []], "rows": rows_of(full),
            "machine": machine, "run": run, "market": market, "signals": signals,
            "control_signals": control_signals,
            "seeds": {"pass": CF.N_SEEDS, "read_default": SELECT_SEEDS, "rolling": 100,
                      "seed_parts": lambda study, spec, ctl, period, r, s: CF.seed_parts(spec["id"], ctl, period, r,
                                                                                       s)},
            "window_seconds": sec, "window_seconds_source": sec_src, "judge_usd_per_call": None,
            "test_doc": copy.deepcopy(test_doc), "test_private": copy.deepcopy(full),
            "verdict": copy.deepcopy(test_doc["verdict"]), "out": {}, "private": {}, "private_path": private_path,
            "is_ds": lambda x: bool(x.get("is_ds")) if "members" in x else CF.is_ds(x),
            "headline_cell": dict(H.HEADLINE_CELL), "size_fixed_on_select": H.size_fixed_on_select,
            "size_rule": H.SIZE_RULE, "live_gate": dict(H.LIVE_GATE), "evaluate_live_gate": H.evaluate_live_gate,
            "procs": int(getattr(args, "procs", 1) or 1), "pmap": H.pmap,
            "helpers": {"summarize": H.summarize, "boot_p": H.boot_p, "seed_int": H.seed_int, "rng_of": H.rng_of,
                        "bh": H.bh, "month_starts": H.month_starts, "clopper_pearson": H.clopper_pearson,
                        "ms_str": H.ms_str, "day_ms": H.day_ms},
            "log": lambda msg: print(f"[reads r2] {msg}", flush=True), "hunt_module": Live()}


@contextlib.contextmanager
def round2_reads_o():
    """reads_o on round 2: O2 is not a round-2 read (its calendar status says so) and round 1's select map is not
    run."""
    cal, smap = RO.calendar_status, RO.select_weekend_map

    def no_o2(study, periods=None):
        return {"file": RO.CALENDAR_REL, "run": False, "pinned": False, "problems": [],
                "reason": "O2 is not a round-2 read (PREREG_HUNT_R2 8, 9.3: O1, O1b and O4 only)"}
    RO.calendar_status = no_o2
    RO.select_weekend_map = lambda ctx, live, off: ({"not_run": "round 1's select map; round 2's select-period "
                                                                "weekend tables are in pretest_reads.json (6)"}, {})
    try:
        yield
    finally:
        RO.calendar_status, RO.select_weekend_map = cal, smap


# ------------------------------------------------------------------ the rows module (9.2)
def _sum(o: dict) -> dict:
    keep = ("mean_lnM", "median_M", "max_dd", "bust", "n_positions", "win_share", "end_multiple",
            "share_months_with_position")
    return {k: o.get(k) for k in keep}


def _corr(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 3 or len(a) != len(b) or a.std() == 0 or b.std() == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def block_at(mk, sys_: dict, r: float, procs: int, n_seeds: int) -> dict:
    """A 7.1-style block (base, cost x2, the four controls, the checks) of one system on one market at r."""
    sig = CF.signals(mk, sys_)
    base = H.run_signals(mk, [(sig, 0)], r, "base", detail=True, days=False)
    cost2 = H.run_signals(mk, [(sig, 0)], r, "x2", detail=False)
    ctl = CF.run_controls(mk, sys_, sig, r, procs, n_seeds)
    chk = CF.judge(base, cost2, ctl, sys_["id"], mk.period, r)
    return {"base": _sum(base) | {"lnM": base["lnM"]}, "cost2": _sum(cost2), "checks": chk,
            "controls": {"seeds": n_seeds, "ac_shifts": len(ctl["ac_weeks"]), "ac_counts": ctl["ac_counts"]}}


def rows_reads(ctx: dict, mks: dict, full: dict) -> None:
    """9.2 per tested pick: new 24, extra 2020, the r = 1% line, select-period controls, correlation with the anchor
    default; R14 / R19 status. Fills ctx['out'] / ctx['private'] (D11 split)."""
    procs = int(ctx.get("procs") or 1)
    passing = set(full["verdict"]["passing"])
    out_rows, priv_rows = {}, {}
    for p in full["picks"]:
        rid = f"pick:{p['id']}"
        blk = full["results"][p["id"]]
        d = CF.default_system_of(p)
        row = {"row": rid, "id": p["id"], "kind": "pick", "batch": p.get("batch"), "pick_no": p.get("pick_no")}
        row["new24"] = {per: _sum(H.run_signals(mks[f"new_{per}"], [(CF.signals(mks[f"new_{per}"], p), 0)],
                                                H.R_BASE, detail=True, days=False)) for per in ("select", "test")}
        row["extra2020"] = {f"{r:g}": _sum(H.run_signals(mks["extra"], [(CF.signals(mks["extra"], p), 0)], r,
                                                         detail=True, days=False)) for r in (H.R_BASE, H.R_ONE)}
        row["r1_line"] = block_at(mks["test"], p, H.R_ONE, procs, CF.N_SEEDS)
        row["select_controls"] = block_at(mks["select"], p, H.R_BASE, procs, SELECT_SEEDS)
        dsel = H.run_signals(mks["select"], [(CF.signals(mks["select"], d), 0)], H.R_BASE, detail=False)
        row["corr_with_anchor_default"] = {
            "test": _corr(blk["base"]["lnM"], blk["default"]["base"]["lnM"]),
            "select": _corr(row["select_controls"]["base"]["lnM"], dsel["lnM"]), "default_id": d["id"]}
        row["labels"] = []
        if p["id"] in passing and row["new24"]["test"]["mean_lnM"] <= 0:
            row["labels"].append("carried by the old six")
        row["R14_R19"] = dict(R14_R19) if p["id"] in passing else {"status": "not a passing pick: R14 and R19 are "
                                                                             "for passing picks only"}
        if CF.is_ds(p):
            priv_rows[rid] = row
            r_ = RO.redact(row)
            r_["note"] = DS_NOTE
            out_rows[rid] = r_
        else:
            out_rows[rid] = row
    ctx["out"].update({"what": "PREREG_HUNT_R2 9.2 reads on the tested picks: reported, never a pass",
                       "choices": CHOICES, "rows": RO.plain(out_rows), "R14_R19": R14_R19})
    ctx["private"].update({"rows": RO.plain(priv_rows)})


# ------------------------------------------------------------------ the hook (9.1)
def guard_snapshot(root: str = ROOT) -> dict:
    snap = {}
    d = os.path.join(root, OUT_REL)
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            p = os.path.join(d, f)
            if os.path.isfile(p):
                snap[p] = H.sha256_file(p)
    pk = os.path.join(root, PN.PICKS)
    if os.path.exists(pk):
        snap[pk] = H.sha256_file(pk)
    return snap


def module_pin(name: str, at_test: dict | None, root: str = ROOT) -> dict:
    rel = MODULES[name]["rel"]
    full = os.path.join(root, rel)
    sha = H.sha256_file(full) if os.path.exists(full) else None
    now = PN.listed_now(root)
    return {"module": rel, "sha256": sha, "listed_in_pin": bool(sha and now.get(rel) == sha),
            "listed_before_test_json": bool(sha and (at_test or {}).get(rel) == sha)}


def run_reads(*, args, pin, mks: dict, syms: list, test_doc: dict, full: dict, private_dir: str,
              root: str = ROOT, names=ORDER, t_start: float | None = None, wall_s: float | None = None) -> dict:
    """Each module in order, under the read guard; returns {name: status}. Outputs are written here only."""
    t_start = time.time() if t_start is None else t_start
    wall_s = WALL_S if wall_s is None else wall_s
    status = {}
    ds_ids = {p["id"] for p in full["picks"] if CF.is_ds(p)} | {r["row"] for r in rows_of(full) if r["is_ds"]}
    for name in names:
        out_path = os.path.join(root, OUT_REL, MODULES[name]["out"])
        if os.path.exists(out_path):
            status[name] = "exists"
            continue
        if time.time() - t_start > wall_s:
            status[name] = "not run: 12-hour wall reached (9.1)"
            continue
        rp = module_pin(name, test_doc.get("reads_pinned_at_test"), root)
        if not rp["listed_in_pin"]:
            status[name] = f"not pinned: {rp['module']} is not in {PN.R2_PIN} with its current sha256"
            continue
        priv_path = os.path.join(private_dir, f"r2_{name}_private.json")
        ctx = make_ctx(args=args, pin=pin, mks=mks, syms=syms, test_doc=test_doc, full=full, reads_pin=rp,
                       private_path=priv_path, root=root)
        before = guard_snapshot(root)
        t0 = time.time()
        if name == "rows":
            rows_reads(ctx, mks, full)
        elif name == "reads_o":
            with round2_reads_o():
                RO.run(ctx)
        else:
            RA.run(ctx)
        after = guard_snapshot(root)
        if after != before:
            changed = sorted(set(before) ^ set(after) | {k for k in before if after.get(k) != before[k]})
            raise H.ReadGuardError(f"{name} changed files of the study ({changed}): reads never write")
        bad = H.d11_problems(ctx["out"], ds_ids) + CF.d11_problems(ctx["out"], ds_ids, "reads")
        if bad:
            raise H.ReadGuardError(f"{name}: DeepSeek figures in the public output (D11): {bad[:10]}")
        priv_sha = SR.write_json(priv_path, RO.plain(ctx["private"]))
        doc = {"study": "hunt-r2 v1", "module": rp["module"], "module_sha256": rp["sha256"], "reads_pin": rp,
               "reads_line_predates_test_json": rp["listed_before_test_json"],
               "label": "reported, never a pass (9.1)" if rp["listed_before_test_json"] else
               "post hoc: the module's pin line came after test.json (9.1, DEVIATIONS.md)",
               "test_json_sha256": H.sha256_file(os.path.join(root, PN.TEST)) if os.path.exists(
                   os.path.join(root, PN.TEST)) else None,
               "pin": pin, "git_commit": H.git_commit(), "written_utc": H.ms_str(int(time.time() * 1000)),
               "out": RO.plain(ctx["out"]), "private_sha256": priv_sha, "seconds": round(time.time() - t0, 1)}
        SR.write_json(out_path, doc)
        status[name] = "written"
        print(f"[reads r2] {name}: written {os.path.relpath(out_path, root)} in {time.time() - t0:.0f}s", flush=True)
    return status
