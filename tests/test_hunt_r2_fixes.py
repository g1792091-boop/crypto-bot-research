"""Hunt round 2: tests for the fixes after the 2026-10-12 review (PREREG_HUNT_R2.md 3.6, 3.7, 4.2-4.4, 5, 6, 8, 9.1, 11).

Synthetic bars and temporary trees only; the repository's own pin state is never read. Covers: the store's open files
under the default 1024 limit, resource errors never recorded as 3.7 removals, store units keyed to the code, the (b′)
flip table reused in the workers, the F4 watch list and the full grid's select picks as pinned label inputs, box checks
resumable, the ledger's round-2 read p-values, registry and parity with track 2's rows, the round-1-output refusal of
the pin, and the goal board kept row by row under the 12-hour wall.
"""

from __future__ import annotations

import json
import os
import subprocess
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
from research.hunt_r2 import ledger as LG  # noqa: E402
from research.hunt_r2 import pin_r2 as PN  # noqa: E402
from research.hunt_r2 import reads_r2 as RR  # noqa: E402
from research.hunt_r2 import select_r2 as SR  # noqa: E402
from research.hunt_r2 import store_r2 as ST  # noqa: E402
from test_hunt_r2_core import SYMS, _W, world  # noqa: E402,F401  (the synthetic world fixture)


# ------------------------------------------------------------------ 11: open files of the event store
def test_store_units_stay_under_the_default_open_file_limit(tmp_path):
    """3 names x 4 timeframes x 30 coins read back in one process with a soft limit of 1024 (Ubuntu's SSH / tmux
    default): the cache closes evicted units, so the open files stay bounded; raise_nofile lifts the soft limit."""
    script = f"""
import os, resource, sys
import numpy as np
sys.path.insert(0, {ROOT!r})
soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
resource.setrlimit(resource.RLIMIT_NOFILE, (1024, hard))
from research.hunt_r2 import select_r2 as SR, store_r2 as ST
root = {str(tmp_path)!r}
syms = [f"C{{i:02d}}USDT" for i in range(30)]
names = ["E1", "N20_EMA9_CHOP", "F3_BOS"]
tfs = ["15m", "30m", "1h", "4h"]
doc = {{"j": np.arange(40, dtype=np.int32), "side": np.ones(40, np.int8), "g1": np.ones(40, np.int8),
        "off": np.array([0, 20, 40]), "n_both": np.zeros(2, np.int32),
        "meta": {{"combo_sha": ["a", "b"], "raised": {{}}, "sym": "X"}}}}
for nm in names:
    for tf in tfs:
        for s in syms:
            ST.write_unit(ST.unit_dir(root, "coarse", nm, tf, s), doc)
peak = 0
for rep in range(2):
    for nm in names:
        for tf in tfs:
            us = SR.load_units(root, "coarse", nm, tf, syms)
            for u in us:
                j, side, g1 = u.events(1)
                assert len(j) == 20
            peak = max(peak, len(os.listdir("/proc/self/fd")))
SR.drop_units()
after = len(os.listdir("/proc/self/fd"))
new_soft, new_hard = SR.raise_nofile()
print(peak, after, new_soft, new_hard)
"""
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    peak, after, soft, hard = (int(x) for x in out.stdout.split())
    assert peak < 1024 and peak <= SR.UNITS_LRU * 30 * len(ST.MAPPED) + 64
    assert after < 64
    assert soft >= min(hard, SR.NOFILE_WANT) or hard == -1


# ------------------------------------------------------------------ 3.7: only the signal code's own errors remove a combo
def test_resource_errors_are_never_recorded_as_removals(world, monkeypatch, tmp_path):
    ctx = world
    name = "E1"
    lat = L.coarse(name)
    orig = E.SeriesEvents.events
    for exc in (MemoryError, OSError):
        def ev(self, combo, exc=exc):
            if L.canon(combo) == L.canon(lat.combos[1]):
                raise exc("synthetic")
            return orig(self, combo)
        monkeypatch.setattr(E.SeriesEvents, "events", ev)
        with pytest.raises(exc):
            ST.compute_unit(name, "1h", "ETHUSDT", lat.combos[:3], ctx.start, ctx.end)
        with pytest.raises(exc):
            ST.build(str(tmp_path), "coarse", name, "1h", "ETHUSDT", lat.combos, ctx.start, ctx.end)
        assert not os.path.exists(ST.unit_dir(str(tmp_path), "coarse", name, "1h", "ETHUSDT"))

    def ev2(self, combo):
        if L.canon(combo) == L.canon(lat.combos[1]):
            raise ValueError("a definition error")
        return orig(self, combo)
    monkeypatch.setattr(E.SeriesEvents, "events", ev2)
    doc = ST.compute_unit(name, "1h", "ETHUSDT", lat.combos[:3], ctx.start, ctx.end)
    assert list(doc["meta"]["raised"]) == ["1"] and doc["meta"]["raised"]["1"].startswith("ValueError")


def test_store_units_are_keyed_to_the_code(world, tmp_path, monkeypatch):
    ctx = world
    name, tf, sym = "TSMOM7", "4h", "ETHUSDT"
    lat = L.coarse(name)
    root = str(tmp_path)
    path = ST.build(root, "coarse", name, tf, sym, lat.combos, ctx.start, ctx.end)
    ser = H.series(sym, tf)
    with open(os.path.join(path, "meta.json")) as fh:
        meta = json.load(fh)
    assert meta["code"] == ST.code_fingerprint() and meta["version"] == ST.STORE_VERSION
    assert ST.unit_complete(path, lat.combos, ctx.start, ctx.end, ser)
    monkeypatch.setitem(ST._CODE, "fp", "0" * 64)                       # other code: the unit is not reused
    assert not ST.unit_complete(path, lat.combos, ctx.start, ctx.end, ser)
    calls = []
    real = ST.compute_unit
    monkeypatch.setattr(ST, "compute_unit", lambda *a: calls.append(a) or real(*a))
    ST.build(root, "coarse", name, tf, sym, lat.combos, ctx.start, ctx.end)
    assert len(calls) == 1
    files = ST.code_files()
    assert set(ST.CODE_FILES) <= set(files) and "research/hunt/hunt.py" in files
    assert "research/hunt/entries_wide.py" in files and "research/fullgrid/memo.py" in files


# ------------------------------------------------------------------ 4.3: the (b′) flip table is the parent's
def test_null_task_reuses_the_parents_flip_table(world, monkeypatch):
    ctx = world
    monkeypatch.setitem(SR._RUN, "ctx", ctx)
    monkeypatch.setitem(SR._RUN, "flip", {3: SR.FlipTable(3, ctx.start, ctx.end)})

    def no_build(*a, **k):
        raise AssertionError("the flip table was rebuilt in the worker")
    monkeypatch.setattr(SR, "FlipTable", no_build)
    out = SR._null_task(("b", 3, "TSMOM7", None, 0))
    assert out["name"] == "TSMOM7" and out["counts"]["events"] > 0


# ------------------------------------------------------------------ 5: the labels' pinned inputs
def test_watch_list_unreadable_stops_the_step(monkeypatch):
    monkeypatch.setattr(SR, "_RUN", {})
    monkeypatch.setattr(SR.ST.E.EW, "watch_picks", lambda: (_ for _ in ()).throw(ValueError("broken")))
    with pytest.raises(RuntimeError, match="F4 watch list"):
        SR._watch_picks()


def test_fullgrid_select_pick_label(tmp_path, monkeypatch):
    name = "N20_EMA9_CHOP"
    lat = L.coarse(name)
    i = next(k for k in range(len(lat)) if k != lat.default)
    combo = {k: (float(v) + 1e-13 if isinstance(v, float) else v) for k, v in lat.combos[i].items()}
    sel = {"picks": [{"kind": "core", "name": name, "tf": "1h", "row": 7, "exit_index": 0, "exit": "house",
                      "rank": 2, "combo": combo, "select_mean": 0.01, "plateau": 0.02},
                     {"kind": "core", "name": "OTHER", "tf": "1h", "row": 1, "exit_index": 0, "exit": "house",
                      "rank": 1, "combo": lat.combos[i], "select_mean": 0.01}]}
    path = tmp_path / "select.json"
    path.write_text(json.dumps(sel))
    ext = SR.fullgrid_extract(str(path))
    assert ext["n"] == 2 and ext["source"]["sha256"] == H.sha256_file(str(path))
    assert all("select_mean" not in p and "plateau" not in p for p in ext["picks"])        # numbers only (D11)
    monkeypatch.setattr(SR, "_RUN", {"fg": ext["picks"], "watch": []})
    assert SR.fullgrid_matches(name, lat.combos[i]) == [{"tf": "1h", "rank": 2, "exit": "house"}]
    assert SR.fullgrid_matches(name, lat.combos[lat.default]) == []
    u = {"exists": np.ones(len(lat), bool), "S": np.ones(len(lat)), "dup_groups": []}
    assert SR.FG_LABEL in SR.labels_of(name, u, i)
    assert SR.FG_LABEL not in SR.labels_of(name, u, lat.default)


def test_pinned_fullgrid_extract_is_the_full_grids_711():
    with open(os.path.join(ROOT, SR.FG_PICKS_REL)) as fh:
        d = json.load(fh)
    assert d["n"] == len(d["picks"]) == 711 and len(d["source"]["sha256"]) == 64
    ours = {n for _f, n in L.names()}
    assert {p["name"] for p in d["picks"]} <= ours | {"F2_DEMARK", "F6_VWAP_CROSS"}
    assert all(set(p) == {"kind", "name", "tf", "rank", "exit", "combo"} for p in d["picks"])
    assert SR.FG_PICKS_REL in PN.own_files(ROOT)


# ------------------------------------------------------------------ 4.4: box checks resume from their parts
def test_box_checks_resume_from_part_files(world, tmp_path, monkeypatch):
    ctx = world
    name = "TSMOM7"
    u = SR.name_unit(ctx, name, real=True)
    lat = L.coarse(name)
    peak = int(next(k for k in range(len(lat)) if k != lat.default and u["exists"][k]))
    ranked = [{"name": name, "family": lat.family, "P": 0.1, "P2": 0.1, "peak": peak}]
    steps = [{"rank": 1, "taken": True, "label": "taken"}]
    parts = str(tmp_path / "box")
    SR._RUN["ctx"] = ctx
    a = SR.box_stage(ctx, {name: u}, ranked, steps, 1, parts=parts)
    assert len(os.listdir(parts)) == 1
    monkeypatch.setattr(SR, "box_unit", lambda *x, **k: (_ for _ in ()).throw(AssertionError("recomputed")))
    b = SR.box_stage(ctx, {name: u}, ranked, steps, 1, parts=parts)
    assert a["picks"] == b["picks"] and a["boxes"][name]["plateau"] == b["boxes"][name]["plateau"]


# ------------------------------------------------------------------ 0.3: no round-1 output in the pinned checkout
def test_pin_refuses_round_one_output_in_the_checkout(tmp_path):
    root = str(tmp_path)
    for rel, data in {PN.DESIGN: b"d", PN.COUNTS: b"{}", PN.BENCH: b"{}"}.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    (tmp_path / PN.R2_PIN).write_text("\n".join(PN.pinlist(root, [])) + "\n")
    PN.check_pin("select", root, [])
    assert PN.round1_results_in_tree(root) == []
    for rel in ("research/hunt/out/wide/test.json", "research/hunt/results"):
        target = tmp_path / rel
        if rel.endswith(".json"):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}")
        else:
            target.mkdir(parents=True)
        assert rel in PN.round1_results_in_tree(root)
        with pytest.raises(RuntimeError, match="round-1 output in the checkout"):
            PN.check_pin("select", root, [])
        assert any(rel in x for x in PN.pinlist_problems(root, []))
    (tmp_path / "research/hunt/out/wide/parity.json").write_text("{}")      # round 1's pinned parity file is fine
    assert "research/hunt/out/wide/parity.json" not in PN.round1_results_in_tree(root)


# ------------------------------------------------------------------ 8: the ledger
def _w(root, rel, obj):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        json.dump(obj, fh)
    return p


def _registry(root, files):
    _w(root, LG.REGISTRY, {"files": {f: {"study": f, "ledger": "A", "first_line_sha256": None} for f in files}})


def test_ledger_counts_round_two_read_p_values_and_their_maximum_while_absent(tmp_path):
    root, r2priv = str(tmp_path / "repo"), str(tmp_path / "r2priv")
    os.makedirs(r2priv)
    _registry(root, [])
    full = {"picks": [{"id": "R2:F1:E1:1h:G1:a", "family": "F1", "batch": 1},
                      {"id": "R2:F3:F3_BOS:1h:G1:b", "family": "F3", "batch": 1}],
            "results": {"R2:F1:E1:1h:G1:a": {"checks": {"p": 0.01}, "tune": {"p_tune": 0.2}},
                        "R2:F3:F3_BOS:1h:G1:b": {"checks": {"p": 0.3}, "tune": {"p_tune": 0.4}}},
            "verdict": {"passing": []}}
    assert LG.round2_row_ids(full) == ["pick:R2:F1:E1:1h:G1:a", "pick:R2:F3:F3_BOS:1h:G1:b", "basket_batch1"]
    snap = LG.snapshot(root, None, full, None, None, r2_private=r2priv)
    pend = {x["study"]: x["hypotheses"] for x in snap["pending_looks_in_L"]}
    assert pend["hunt-r2 v1 reads reads_rows.json"] == 3 and pend["hunt-r2 v1 reads reads_weekend.json"] == 3
    assert snap["prints"]["L"]["m"] == snap["prints"]["A+"]["m"] + sum(pend.values())
    # the reads exist: every row's r = 1% line p and O4 (e) p enter (A); DeepSeek rows from the sha-checked private file
    priv_rows = {"rows": {"pick:R2:F3:F3_BOS:1h:G1:b": {"r1_line": {"checks": {"p": 0.07}}},
                          "basket_batch1": {"r1_line": {"checks": {"p": 0.08}}}}}
    pp = _w(r2priv, "r2_rows_private.json", priv_rows)
    _w(root, LG.R2_READS_ROWS, {"private_sha256": H.sha256_file(pp), "out": {"rows": {
        "pick:R2:F1:E1:1h:G1:a": {"r1_line": {"checks": {"p": 0.02}}},
        "pick:R2:F3:F3_BOS:1h:G1:b": {"note": "D11"}, "basket_batch1": {"note": "D11"}}}})
    _w(root, LG.R2_READS_O, {"private_sha256": "0" * 64, "out": {"rows": {
        "pick:R2:F1:E1:1h:G1:a": {"periods": {"test": {"O4": {"e": {"p_boot": 0.05}}}}}}}})
    snap = LG.snapshot(root, None, full, None, None, r2_private=r2priv)
    rows = {r["id"]: r for r in snap["prints"]["A"]["rows"]}
    assert rows["pick:R2:F1:E1:1h:G1:a r=1%"]["p"] == 0.02
    assert rows["pick:R2:F3:F3_BOS:1h:G1:b r=1%"]["p"] == 0.07 and rows["basket_batch1 r=1%"]["p"] == 0.08
    assert rows["pick:R2:F1:E1:1h:G1:a O4 (e)"]["p"] == 0.05
    assert rows["pick:R2:F3:F3_BOS:1h:G1:b O4 (e)"]["p"] == 1.0                  # private sha differs: p = 1
    assert not any(x["study"].startswith("hunt-r2 v1 reads") for x in snap["pending_looks_in_L"])
    pub = LG.public_of(snap)
    for r in pub["prints"]["A"]["rows"]:
        assert ("p" in r) != r["deepseek"]
    assert LG.MAX_HYP["hunt-r2 v1"] == 30 * 2 + 30 + 32


def test_ledger_print_l_is_incomplete_with_an_unregistered_preregistration(tmp_path):
    root = str(tmp_path)
    _registry(root, ["research/hunt_r2/PREREG_HUNT_R2.sha256"])
    _w(root, "research/hunt_r2/PREREG_HUNT_R2.sha256", {})
    full = {"picks": [{"id": "R2:F1:E1:1h:G1:a", "family": "F1", "batch": 1}],
            "results": {"R2:F1:E1:1h:G1:a": {"checks": {"p": 1e-9}, "tune": {"p_tune": 0.2}}},
            "verdict": {"passing": ["R2:F1:E1:1h:G1:a"]}}
    snap = LG.snapshot(root, None, full, None, None)
    assert snap["prints"]["L"]["status"] == "complete" and snap["registry"]["unregistered"] == []
    new = os.path.join(root, "research", "exitflex", "PREREG_EXITFLEX.sha256")
    os.makedirs(os.path.dirname(new))
    with open(new, "w") as fh:
        fh.write(f"{'a' * 64}  research/exitflex/PREREG_EXITFLEX.md\n")
    snap = LG.snapshot(root, None, full, None, None)
    L_ = snap["prints"]["L"]
    assert L_["status"] == "incomplete" and L_["bh_rejections"] is None
    assert snap["registry"]["unregistered"][0]["file"] == "research/exitflex/PREREG_EXITFLEX.sha256"
    assert snap["round2_live_gate"]["R2:F1:E1:1h:G1:a"]["passes_print_L"] is False
    assert snap["prints"]["A"]["status"] == "complete"                         # (A) and (A+) unaffected
    extra = _w(str(tmp_path), "extra.json", [{"id": "exitflex", "study": "exit study", "status": "pending",
                                              "hypotheses": 40, "prereg": "research/exitflex/PREREG_EXITFLEX.sha256"}])
    snap = LG.snapshot(root, None, full, None, extra)
    assert snap["prints"]["L"]["status"] == "complete"
    assert snap["prints"]["L"]["m"] == snap["prints"]["A+"]["m"] + sum(x["hypotheses"] for x in snap["pending_looks_in_L"])
    assert {"exit study": 40}.items() <= {x["study"]: x["hypotheses"] for x in snap["pending_looks_in_L"]}.items()


def test_pinned_registry_structure():
    """The registry file itself (the checkout's own hash files are compared by `hunt_r2 pinlist`, which lists any
    unregistered one as a problem before the pin; a test here would fail the server's self-check on a later study)."""
    reg = LG.registry(ROOT)
    assert reg and "research/hunt_r2/PREREG_HUNT_R2.sha256" in reg and "research/hiwr/PREREG_HIWR.sha256" in reg
    for f, e in reg.items():
        assert f.startswith("research/") and f.endswith(".sha256") and e["ledger"] in ("A", "A+", "none")
        assert e["first_line_sha256"] is None or len(e["first_line_sha256"]) == 64


def test_ledger_rows_agree_with_track_twos_on_the_same_round_one_files(tmp_path):
    try:
        from research.hiwr import hiwr as T2
    except Exception as e:  # noqa: BLE001  track 2's code is another job's
        pytest.skip(f"track 2's ledger code does not import here: {type(e).__name__}")
    pub, priv = str(tmp_path / "pub"), str(tmp_path / "priv")
    os.makedirs(priv)
    v1 = {"pick": {"id": "v1:E1:1h"}, "result": {"checks": {"p": 0.003}}}
    wpriv = {"results": {"F3:DSX:1h:G1": {"checks": {"p": 0.0004}}}}
    pp = _w(priv, "wide_test_private.json", wpriv)
    wide = {"picks": [{"id": "F2:AAA:1h:G1", "kind": "core"}, {"id": "F3:DSX:1h:G1", "kind": "ds"}],
            "results": {"F2:AAA:1h:G1": {"checks": {"p": 0.0001}}, "F3:DSX:1h:G1": {"checks": {"PASS": False}}},
            "private_sha256": H.sha256_file(pp)}
    _w(pub, LG.R1_V1_TEST, v1)
    _w(pub, LG.R1_WIDE_TEST, wide)
    ours = {r["id"]: (r["p"], r["deepseek"]) for r in LG.round1_rows(pub, priv)[0] if r["kind"] == "confirm"}
    theirs = {}
    for rel, doc, pv in ((LG.R1_V1_TEST, v1, None), (LG.R1_WIDE_TEST, wide, wpriv)):
        for r in T2._hunt_rows("hunt", rel, doc, pv):
            theirs[r["id"]] = (r["p"], r["deepseek"])
    assert ours == theirs
    assert any("parity test" in n for n in LG.NOTES)


# ------------------------------------------------------------------ 9.1: the goal board keeps its finished rows
def _goal_world(tmp_path, monkeypatch, rows_n=3):
    root, priv = str(tmp_path / "repo"), str(tmp_path / "priv")
    os.makedirs(os.path.join(root, RR.OUT_REL))
    os.makedirs(priv)
    picks = [{"id": f"R2:F1:E1:1h:G1:{i}", "family": "F1", "name": "E1", "batch": 1, "pick_no": i + 1}
             for i in range(rows_n)]
    full = {"picks": picks, "verdict": {"passing": []}, "results": {}}
    calls = []

    def fake_run(ctx):
        calls.append([r["row"] for r in ctx["rows"]])
        for r in ctx["rows"]:
            ctx["out"].setdefault("r1_goal_board", {})[r["row"]] = {"headline": {"share": 0}}
            ctx["out"].setdefault("leverage", {})[r["row"]] = {}
            ctx["out"].setdefault("continuous", {})[r["row"]] = {}
            ctx["out"].setdefault("r12_basics", {})[r["row"]] = {}
            ctx["out"].setdefault("rows", []).append({"row": r["row"]})
            ctx["out"].setdefault("r15_signal_rate", {"rows": {}})["rows"][r["row"]] = {}
        if len(ctx["rows"]) > 1:
            ctx["out"]["r13_basics"] = {"select": {"ids": [r["row"] for r in ctx["rows"]]}}
            ctx["out"]["r15_signal_rate"]["union"] = {"n": len(ctx["rows"])}
        ctx["out"]["seconds"] = 1.0
    monkeypatch.setattr(RR.RA, "run", fake_run)
    monkeypatch.setattr(RR, "make_ctx", lambda **kw: {"out": {}, "private": {}, "rows": None})
    rp = {"module": "research/hunt/reads_a.py", "sha256": "x", "listed_in_pin": True, "listed_before_test_json": True}
    kw = dict(args=None, pin=None, mks={}, syms=[], test_doc={}, full=full, private_dir=priv, root=root, rp=rp,
              ds_ids=set(), status={}, t_start=0.0)
    return root, priv, full, calls, kw


def test_goal_board_runs_row_by_row_and_keeps_finished_rows_at_the_wall(tmp_path, monkeypatch):
    import time as _t
    real_time = _t.time
    root, priv, full, calls, kw = _goal_world(tmp_path, monkeypatch)
    rows = [r["row"] for r in RR.rows_of(full)]
    assert rows[-1] == "basket_batch1" and len(rows) == 4
    out_path = os.path.join(root, RR.OUT_REL, "reads_goal.json")
    clock = {"n": 0}

    def fake_time():                       # the wall is reached after the second row
        clock["n"] += 1
        return 0.0 if len(calls) < 2 else 1e9
    monkeypatch.setattr(RR.time, "time", fake_time)
    st = RR.goal_module(deadline=100.0, **kw)
    assert st.startswith("partial: 2 of 4 rows")
    with open(out_path) as fh:
        doc = json.load(fh)
    assert doc["complete"] is False and doc["rows_done"] == rows[:2] and doc["rows_not_run"] == rows[2:]
    assert set(doc["out"]["r1_goal_board"]) == set(rows[:2]) and "status" in doc["out"]["r13_basics"]
    assert len(os.listdir(os.path.join(priv, "reads_parts", "reads_a"))) == 2
    # resume: finished rows are not rerun; the cross-row pass completes the file
    monkeypatch.setattr(RR.time, "time", real_time)
    calls.clear()
    st = RR.goal_module(deadline=real_time() + 3600, **kw)
    assert st == "written" and calls == [[rows[2]], [rows[3]], rows]
    with open(out_path) as fh:
        doc = json.load(fh)
    assert doc["complete"] is True and set(doc["out"]["r1_goal_board"]) == set(rows)
    assert doc["out"]["r13_basics"] == {"select": {"ids": rows}} and doc["out"]["r15_signal_rate"]["union"]["n"] == 4
