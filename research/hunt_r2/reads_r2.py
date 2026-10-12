"""Hunt round 2 reads after the verdict (PREREG_HUNT_R2.md section 9): reported, never a pass.

ROWS (9.1): every tested pick (pass or fail); the batch-1 all-K basket (one wallet, H 8 caps shared, same-close order
by 30-day quote volume then pick number, labelled "not a candidate") when K >= 2; the passing basket when at least two
pass. Three read modules run in this order, each only when its file is in round 2's pin with its current sha256:

* ``rows`` (this file, ``research/hunt_r2/out/reads_rows.json``), on every row (picks and baskets): new 24 only (9.2,
  "carried by the old six" for passing picks); extra 2020 at r = 0.5% and 1%; the r = 1% line (P0-P4 and the four
  seed-rank parts, controls rerun at 1%, a basket's controls drawn member by member with each member's own seed parts)
  with its cost x2 line; select-period controls seeds 1-200 ((a-c): every select-period shift); the correlation of
  monthly ln M with the anchor default's (a basket: with the basket of its members' anchor defaults); a basket's plain
  test run (base and cost x2 at r = 0.5%); R14 and R19 status (not computed; DEVIATIONS.md).
* ``reads_o`` (round 1's pinned ``research/hunt/reads_o.py``, ``reads_weekend.json``): 9.3 weekend O1 / O1b beside
  the tested machine, select and test, controls (a) and (b) seeds 1-200 through the weekend-skip machine, the R1
  headline shares at the size fixed on select; O4 (f) and R6 (e) and the "momentum only" label (9.2). O2 never runs
  here (not a round-2 read, 8 counts O1, O1b and O4 only), and round 1's select map is not run (it is round 1's walk).
* ``reads_a`` (round 1's pinned ``research/hunt/reads_a.py``, ``reads_goal.json``): 9.5 R1 goal board, 9.4 R24 at
  20 / 30 / 40x, continuous accounts, R12 / R13 basics, R15. Run one row at a time (picks in pick order, then the
  baskets), each row's result kept in the private parts folder and ``reads_goal.json`` rewritten after every row, so
  the 12-hour wall keeps the finished rows; one last pass without windows gives the cross-row parts (R13 overlaps, the
  R15 union).

Round 1's modules receive round 2's own context (reads interface api 1): ``signals``, ``control_signals`` and ``run``
take round 2's signal dicts only (``run`` refuses a spec dict), and ``hunt_module`` is a proxy of hunt.py whose
``cached_events`` returns round 2's events for a round-2 system (``confirm_r2.events_of``), so no round-2 system ever
reaches round 1's spec-based path (11). Control draws use round 2's seed parts ("hunt-r2", system id, control, period,
r, seed), the same draws the test step used.

Read guard (9.1, H 14 / W 7.1): a module runs only after test.json is in the pin; the code refuses to write
(ReadGuardError) when any file of research/hunt_r2/out or picks.json changed while it ran; a float under a DeepSeek row
of its public output refuses the write (D11); the reads stop at 12 hours wall (the server kit passes what is left of
it over restarts): a module or goal-board row that would start later is listed "not run: 12-hour wall reached".
``reads_status.json`` is rewritten after every module and goal-board row.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
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
    "9.1 / 9.2 baskets: one wallet over the members' signals (each with its pick number as the source, H 8's same-close "
    "order); controls per member with the member's own seed parts, combined per seed; checks as 7.1 with the row id "
    "in the bootstrap seed parts; the correlation is with the basket of the members' anchor defaults.",
    "9.1 wall: the reads stop at 12 hours of their own running time summed over restarts; reads_a runs row by row and "
    "keeps every finished row; R13's cross-row overlaps and R15's union come from one last pass without windows.",
    "9.2 'carried by the old six': a passing pick whose new-24 test mean ln M is <= 0 (W 7.0).",
    "9.3: each weekend variant's pick-minus-control d_m (controls (a) and (b), seeds 1-200 through the same "
    "weekend-skip machine) carries a month 90% CI (100,000 resamples, seed parts ('hunt-r2', 'weekend', period, "
    "control, 'ci')), added to reads_o's summary.",
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
    """reads_o on round 2: O2 is not a round-2 read (its calendar status says so), round 1's select map is not run,
    and each control's pick-minus-control d_m gets its month 90% CI (9.3)."""
    cal, smap, summ = RO.calendar_status, RO.select_weekend_map, RO._summary

    def no_o2(study, periods=None):
        return {"file": RO.CALENDAR_REL, "run": False, "pinned": False, "problems": [],
                "reason": "O2 is not a round-2 read (PREREG_HUNT_R2 8, 9.3: O1, O1b and O4 only)"}

    def with_ci(o, ctl_lnm, base_taken, skipped, ctl_bits, cell, period):
        s = summ(o, ctl_lnm, base_taken, skipped, ctl_bits, cell, period)
        lnm = np.asarray(o["lnM"], float)
        for cn, mat in ctl_lnm.items():
            mat = np.asarray(mat, float)
            if cn in s.get("controls", {}) and mat.size and mat.shape[1] == len(lnm):
                d = lnm - mat.mean(axis=0)
                s["controls"][cn]["ci90_mean_d"] = CF.month_ci(d, H.seed_int(CF.SEED_TAG, "weekend", period, cn,
                                                                             "ci"))
        return s
    RO.calendar_status = no_o2
    RO.select_weekend_map = lambda ctx, live, off: ({"not_run": "round 1's select map; round 2's select-period "
                                                                "weekend tables are in pretest_reads.json (6)"}, {})
    RO._summary = with_ci
    try:
        yield
    finally:
        RO.calendar_status, RO.select_weekend_map, RO._summary = cal, smap, summ


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


_B: dict = {"mk": {}, "row": {}}         # basket controls: set in the parent before a pmap (fork inherits it)


def _parts(mk, members: list, srcs: list) -> list:
    return [(CF.signals(mk, m), int(src)) for m, src in zip(members, srcs)]


def _basket_ctl_task(task) -> tuple:
    mkey, rid, ctl, draws, r = task
    mk = _B["mk"][mkey]
    members, sigs, srcs = _B["row"][(mkey, rid)]
    rows, cnt = [], {}
    for s_ in draws:
        parts = []
        for m, sig, src in zip(members, sigs, srcs):
            csig, c = CF.control_sig(mk, sig, m["id"], ctl, r, s_)
            for k, v in c.items():
                cnt[k] = cnt.get(k, 0) + int(v)
            parts.append((csig, src))
        rows.append(H.run_signals(mk, parts, r)["lnM"])
    return rows, cnt


def basket_controls(mk, row: dict, r: float, procs: int, n_seeds: int) -> dict:
    """7.1's four controls on a basket row: each member's control draw with its own seed parts, one wallet per seed."""
    members, srcs = row["members"], [int(x) for x in row["src"]]
    sigs = [CF.signals(mk, m) for m in members]
    _B["mk"][mk.key] = mk
    _B["row"][(mk.key, row["row"])] = (members, sigs, srcs)
    weeks = CF.ac_weeks(mk)
    tasks = []
    for ctl in CF.RANK_PARTS:
        draws = weeks if ctl == "ac" else list(range(1, n_seeds + 1))
        for i in range(0, len(draws), CF.CTL_TASK_SEEDS):
            tasks.append((mk.key, row["row"], ctl, tuple(draws[i:i + CF.CTL_TASK_SEEDS]), float(r)))
    res = H.pmap(_basket_ctl_task, tasks, procs, label=f"controls {row['row']} {mk.period} r={r:g}")
    out = {c: [] for c in CF.RANK_PARTS}
    cnt = {}
    for t, (rows, c) in zip(tasks, res):
        out[t[2]].extend(rows)
        if t[2] == "ac":
            for k, v in c.items():
                cnt[k] = cnt.get(k, 0) + v
    n_m = len(mk.months)
    out = {c: (np.asarray(v, float) if v else np.zeros((0, n_m))) for c, v in out.items()}
    out.update({"ac_weeks": weeks, "ac_counts": cnt, "gated": int(sum(len(x["k"]) for x in sigs))})
    return out


def basket_block_at(mk, row: dict, r: float, procs: int, n_seeds: int) -> dict:
    """A 7.1-style block of a basket row on one market at r (one wallet, H 8 caps shared)."""
    parts = _parts(mk, row["members"], row["src"])
    base = H.run_signals(mk, parts, r, "base", detail=True, days=False)
    cost2 = H.run_signals(mk, parts, r, "x2", detail=False)
    ctl = basket_controls(mk, row, r, procs, n_seeds)
    chk = CF.judge(base, cost2, ctl, row["row"], mk.period, r)
    return {"base": _sum(base) | {"lnM": base["lnM"]}, "cost2": _sum(cost2), "checks": chk,
            "controls": {"seeds": n_seeds, "ac_shifts": len(ctl["ac_weeks"]), "ac_counts": ctl["ac_counts"]}}


def _basket_row(row: dict, mks: dict, procs: int) -> dict:
    members, srcs = row["members"], row["src"]
    out = {"row": row["row"], "kind": row["kind"], "label": row["label"], "members": [m["id"] for m in members]}
    out["new24"] = {per: _sum(H.run_signals(mks[f"new_{per}"], _parts(mks[f"new_{per}"], members, srcs), H.R_BASE,
                                            detail=True, days=False)) for per in ("select", "test")}
    out["extra2020"] = {f"{r:g}": _sum(H.run_signals(mks["extra"], _parts(mks["extra"], members, srcs), r,
                                                     detail=True, days=False)) for r in (H.R_BASE, H.R_ONE)}
    tparts = _parts(mks["test"], members, srcs)
    tb = H.run_signals(mks["test"], tparts, H.R_BASE, "base", detail=True, days=False)
    out["test_plain"] = {"base": _sum(tb), "cost2": _sum(H.run_signals(mks["test"], tparts, H.R_BASE, "x2",
                                                                       detail=False))}
    out["r1_line"] = basket_block_at(mks["test"], row, H.R_ONE, procs, CF.N_SEEDS)
    out["select_controls"] = basket_block_at(mks["select"], row, H.R_BASE, procs, SELECT_SEEDS)
    dmem = [CF.default_system_of(m) for m in members]
    dsel = H.run_signals(mks["select"], _parts(mks["select"], dmem, srcs), H.R_BASE, detail=False)
    dtest = H.run_signals(mks["test"], _parts(mks["test"], dmem, srcs), H.R_BASE, detail=False)
    out["corr_with_anchor_default"] = {"test": _corr(tb["lnM"], dtest["lnM"]),
                                       "select": _corr(out["select_controls"]["base"]["lnM"], dsel["lnM"]),
                                       "default_ids": [d["id"] for d in dmem]}
    out["labels"] = [row["label"]]
    out["R14_R19"] = {"status": "a basket: R14 and R19 are for passing picks only"}
    return out


def rows_reads(ctx: dict, mks: dict, full: dict) -> None:
    """9.2 per row (tested picks and baskets): new 24, extra 2020, the r = 1% line, select-period controls,
    correlation with the anchor default; R14 / R19 status. Fills ctx['out'] / ctx['private'] (D11 split)."""
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
    for row in rows_of(full):
        if row["kind"] == "pick":
            continue
        b = _basket_row(row, mks, procs)
        if row["is_ds"]:
            priv_rows[row["row"]] = b
            r_ = RO.redact(b)
            r_["note"] = DS_NOTE
            out_rows[row["row"]] = r_
        else:
            out_rows[row["row"]] = b
    ctx["out"].update({"what": "PREREG_HUNT_R2 9.2 reads on the rows (tested picks and baskets): reported, never a "
                               "pass", "choices": CHOICES, "rows": RO.plain(out_rows), "R14_R19": R14_R19})
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


GOAL_ROW_SECTIONS = ("r1_goal_board", "leverage", "continuous", "r12_basics")


def _row_key(rid: str) -> str:
    return hashlib.sha256(rid.encode()).hexdigest()[:16]


def _guarded(root: str, name: str, fn) -> None:
    before = guard_snapshot(root)
    fn()
    after = guard_snapshot(root)
    if after != before:
        changed = sorted(set(before) ^ set(after) | {k for k in before if after.get(k) != before[k]})
        raise H.ReadGuardError(f"{name} changed files of the study ({changed}): reads never write")


def _no_windows(ctx, live):
    """reads_a's window plan with no window: its last pass computes only the continuous runs, R12, R13 and R15."""
    return {(ri, p, kind): [] for ri in range(len(ctx["rows"])) for p in RA.READ_PERIODS
            for kind in ("calendar", "rolling")}


def merge_goal(row_parts: list, cross: dict | None) -> tuple:
    """(public out, private) of reads_a from its per-row results and the cross-row pass (None: not run)."""
    pub = dict(row_parts[0]["out"]) if row_parts else {}
    prv = dict(row_parts[0]["private"]) if row_parts else {}
    for sec in GOAL_ROW_SECTIONS:
        pub[sec] = {k: v for p in row_parts for k, v in ((p["out"].get(sec) or {}).items())}
        prv[sec] = {k: v for p in row_parts for k, v in ((p["private"].get(sec) or {}).items())}
    pub["rows"] = [m for p in row_parts for m in (p["out"].get("rows") or [])]
    r15 = {k: v for p in row_parts for k, v in (((p["out"].get("r15_signal_rate") or {}).get("rows") or {}).items())}
    r15p = {k: v for p in row_parts for k, v in (((p["private"].get("r15_signal_rate") or {}).get("rows") or {}).items())}
    if cross is not None:
        pub["r13_basics"] = cross["out"].get("r13_basics")
        prv["r13_basics"] = cross["private"].get("r13_basics")
        pub["r15_signal_rate"] = {"rows": r15, "union": (cross["out"].get("r15_signal_rate") or {}).get("union")}
        prv["r15_signal_rate"] = {"rows": r15p, "union_all_rows":
                                  (cross["private"].get("r15_signal_rate") or {}).get("union_all_rows")}
    else:
        pub["r13_basics"] = prv["r13_basics"] = {"status": "cross-row pass not run (12-hour wall or rows left)"}
        pub["r15_signal_rate"] = {"rows": r15, "union": None}
        prv["r15_signal_rate"] = {"rows": r15p, "union_all_rows": None}
    pub["seconds"] = round(sum(float(p["out"].get("seconds") or 0) for p in row_parts)
                           + (float(cross["out"].get("seconds") or 0) if cross else 0.0), 1)
    return pub, prv


def write_status(root: str, status: dict, t_start: float, extra: dict | None = None) -> None:
    SR.write_json(os.path.join(root, OUT_REL, "reads_status.json"),
                  {"what": "PREREG_HUNT_R2 9.1: which reads ran; unfinished ones are listed (12-hour wall)",
                   "status": status, "wall_hours_used_this_run": round((time.time() - t_start) / 3600, 2),
                   **(extra or {}), "written_utc": H.ms_str(int(time.time() * 1000))})


def _module_doc(rp: dict, root: str, pin, out: dict, priv_sha: str, seconds: float, extra: dict | None = None) -> dict:
    return {"study": "hunt-r2 v1", "module": rp["module"], "module_sha256": rp["sha256"], "reads_pin": rp,
            "reads_line_predates_test_json": rp["listed_before_test_json"],
            "label": "reported, never a pass (9.1)" if rp["listed_before_test_json"] else
            "post hoc: the module's pin line came after test.json (9.1, DEVIATIONS.md)",
            "test_json_sha256": H.sha256_file(os.path.join(root, PN.TEST)) if os.path.exists(
                os.path.join(root, PN.TEST)) else None,
            "pin": pin, "git_commit": H.git_commit(), "written_utc": H.ms_str(int(time.time() * 1000)),
            "out": RO.plain(out), "private_sha256": priv_sha, "seconds": round(seconds, 1), **(extra or {})}


def goal_module(*, args, pin, mks, syms, test_doc, full, private_dir, root, rp, deadline, ds_ids, status,
                t_start) -> str:
    """reads_a row by row (9.1 wall keeps the finished rows), then the cross-row pass."""
    rows = rows_of(full)
    pdir = os.path.join(private_dir, "reads_parts", "reads_a")
    out_path = os.path.join(root, OUT_REL, MODULES["reads_a"]["out"])
    priv_path = os.path.join(private_dir, "r2_reads_a_private.json")
    done, t0 = [], time.time()

    def ctx_for(rws):
        c = make_ctx(args=args, pin=pin, mks=mks, syms=syms, test_doc=test_doc, full=full, reads_pin=rp,
                     private_path=priv_path, root=root)
        c["rows"] = rws
        return c

    def publish(cross, complete):
        pub, prv = merge_goal(done, cross)
        bad = H.d11_problems(pub, ds_ids) + CF.d11_problems(pub, ds_ids, "reads")
        if bad:
            raise H.ReadGuardError(f"reads_a: DeepSeek figures in the public output (D11): {bad[:10]}")
        priv_sha = SR.write_json(priv_path, RO.plain(prv))
        left = [r["row"] for r in rows if r["row"] not in {p["row"] for p in done}]
        SR.write_json(out_path, _module_doc(rp, root, pin, pub, priv_sha, time.time() - t0, {
            "complete": complete, "rows_done": [p["row"] for p in done], "rows_not_run": left,
            "cross_row_pass": cross is not None}))

    for row in rows:
        part = os.path.join(pdir, f"{_row_key(row['row'])}.json")
        if os.path.exists(part):
            d = CF.load_json(part)
            if d.get("row") == row["row"]:
                done.append(d)
                continue
        if time.time() >= deadline:
            break
        ctx = ctx_for([row])
        _guarded(root, f"reads_a {row['row']}", lambda: RA.run(ctx))
        bad = H.d11_problems(ctx["out"], ds_ids) + CF.d11_problems(ctx["out"], ds_ids, "reads")
        if bad:
            raise H.ReadGuardError(f"reads_a {row['row']}: DeepSeek figures in the public output (D11): {bad[:10]}")
        H.disk_check(part)
        SR.write_json(part, {"row": row["row"], "out": RO.plain(ctx["out"]), "private": RO.plain(ctx["private"])})
        done.append(CF.load_json(part))
        publish(None, False)
        status["reads_a"] = f"running: {len(done)} of {len(rows)} rows written"
        write_status(root, status, t_start)
        print(f"[reads r2] reads_a: row {row['row']} written ({len(done)}/{len(rows)})", flush=True)
    if len(done) < len(rows):
        publish(None, False)
        return f"partial: {len(done)} of {len(rows)} rows (12-hour wall reached, 9.1)"
    cross = None
    if time.time() < deadline:
        ctx = ctx_for(rows)
        orig = RA._plan_windows
        RA._plan_windows = _no_windows
        try:
            _guarded(root, "reads_a cross-row pass", lambda: RA.run(ctx))
        finally:
            RA._plan_windows = orig
        cross = {"out": RO.plain(ctx["out"]), "private": RO.plain(ctx["private"])}
    publish(cross, cross is not None)
    return "written" if cross is not None else "written without the cross-row pass (12-hour wall reached, 9.1)"


def run_reads(*, args, pin, mks: dict, syms: list, test_doc: dict, full: dict, private_dir: str,
              root: str = ROOT, names=ORDER, t_start: float | None = None, wall_s: float | None = None) -> dict:
    """Each module in order, under the read guard; returns {name: status}. Outputs are written here only.
    ``wall_s``: seconds left of the 12-hour wall (9.1; default the whole wall)."""
    t_start = time.time() if t_start is None else t_start
    wall_s = WALL_S if wall_s is None else float(wall_s)
    deadline = t_start + wall_s
    status = {}
    ds_ids = {p["id"] for p in full["picks"] if CF.is_ds(p)} | {r["row"] for r in rows_of(full) if r["is_ds"]}
    for name in names:
        out_path = os.path.join(root, OUT_REL, MODULES[name]["out"])
        if os.path.exists(out_path) and (name != "reads_a" or (CF.load_json(out_path) or {}).get("complete")):
            status[name] = "exists"
            continue
        if time.time() >= deadline:
            status[name] = "not run: 12-hour wall reached (9.1)"
            write_status(root, status, t_start)
            continue
        rp = module_pin(name, test_doc.get("reads_pinned_at_test"), root)
        if not rp["listed_in_pin"]:
            status[name] = f"not pinned: {rp['module']} is not in {PN.R2_PIN} with its current sha256"
            write_status(root, status, t_start)
            continue
        t0 = time.time()
        if name == "reads_a":
            status[name] = goal_module(args=args, pin=pin, mks=mks, syms=syms, test_doc=test_doc, full=full,
                                       private_dir=private_dir, root=root, rp=rp, deadline=deadline, ds_ids=ds_ids,
                                       status=status, t_start=t_start)
            write_status(root, status, t_start)
            print(f"[reads r2] reads_a: {status[name]} in {time.time() - t0:.0f}s", flush=True)
            continue
        priv_path = os.path.join(private_dir, f"r2_{name}_private.json")
        ctx = make_ctx(args=args, pin=pin, mks=mks, syms=syms, test_doc=test_doc, full=full, reads_pin=rp,
                       private_path=priv_path, root=root)
        if name == "rows":
            _guarded(root, name, lambda: rows_reads(ctx, mks, full))
        else:
            def _o():
                with round2_reads_o():
                    RO.run(ctx)
            _guarded(root, name, _o)
        bad = H.d11_problems(ctx["out"], ds_ids) + CF.d11_problems(ctx["out"], ds_ids, "reads")
        if bad:
            raise H.ReadGuardError(f"{name}: DeepSeek figures in the public output (D11): {bad[:10]}")
        priv_sha = SR.write_json(priv_path, RO.plain(ctx["private"]))
        SR.write_json(out_path, _module_doc(rp, root, pin, ctx["out"], priv_sha, time.time() - t0))
        status[name] = "written"
        write_status(root, status, t_start)
        print(f"[reads r2] {name}: written {os.path.relpath(out_path, root)} in {time.time() - t0:.0f}s", flush=True)
    write_status(root, status, t_start, {"finished": True})
    return status
