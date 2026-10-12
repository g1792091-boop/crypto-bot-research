"""Hunt round 2 command line and test stage (research/hunt_r2, PREREG_HUNT_R2.md sections 5-11). Synthetic bars,
hand-made tables and temporary trees only: no real price, no round-1 output, and never the repository's own pin state
(every step runs on a temporary repository tree with its own pin file; the pinlist test reads files, not the pin).

- 7.1 / 7.2: the controls (b-c) and (a-c), the t_32 / bootstrap p, the judge, the batch walk with BH per batch, PASS,
  TUNED BETTER and its three labels, the lineup, the one-look and selection-failed rules
- 8: the three ledger prints (A, A+, L) on a temporary tree, private files read only with a matching sha256, D11
- 11: pinlist by each file's own sha256 (never PREREG_HUNT_WIDE.sha256 or out/**), determinism in fresh processes,
  the step checks (select / pretest / test / reads), refusals without the picks or test.json line
- end to end on synthetic coins with monkeypatched periods: select -> picks hash -> pretest -> test (with reads) ->
  report; test data only after the picks line; D11 on every public output and the report
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import types

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hunt import hunt as H  # noqa: E402
from research.hunt import reads_a as RA  # noqa: E402
from research.hunt import reads_o as RO  # noqa: E402
from research.hunt_r2 import confirm_r2 as CF  # noqa: E402
from research.hunt_r2 import hunt_r2 as HR  # noqa: E402
from research.hunt_r2 import lattice as L  # noqa: E402
from research.hunt_r2 import ledger as LG  # noqa: E402
from research.hunt_r2 import pin_r2 as PN  # noqa: E402
from research.hunt_r2 import pretest_r2 as PT  # noqa: E402
from research.hunt_r2 import reads_r2 as RR  # noqa: E402
from research.hunt_r2 import report_r2 as RP  # noqa: E402
from research.hunt_r2 import select_r2 as SR  # noqa: E402

DAY = H.DAY_MS


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ------------------------------------------------------------------ 7.1 / 7.2 pure parts
def test_t_p_and_the_larger_p():
    from scipy.stats import t as student
    d = np.array([0.02, -0.01, 0.03, 0.01, 0.00, 0.02, -0.005, 0.015])
    want = student.sf(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))), len(d) - 1)
    assert CF.t_p(d) == pytest.approx(want)
    assert CF.t_p(np.full(5, 0.01)) == 0.0 and CF.t_p(np.zeros(5)) == 1.0 and CF.t_p([0.1]) == 1.0
    pp = CF.boot_and_t(d, 7, n_boot=2000)
    assert pp["p"] == max(pp["p_boot"], pp["p_t"]) and pp["p_boot"] == H.boot_p(d, 7, 2000)
    assert CF.boot_and_t(d, 7, n_boot=2000) == pp                      # deterministic in the seed
    lo, hi = CF.month_ci(d, 3, n_boot=5000)
    assert lo < d.mean() < hi and CF.month_ci(d, 3, n_boot=5000) == [lo, hi]
    assert CF.month_ci(-np.abs(d) - 0.01, 3, n_boot=2000)[1] < 0


def test_control_bc_flips_one_coin_per_close():
    sig = {"tf": "1h", "k": np.array([0, 1, 2, 0, 1]), "j": np.array([5, 5, 5, 9, 9]), "side": np.array([1, 1, -1, -1, 1])}
    close = np.array([100, 100, 100, 200, 200], np.int64)
    seen = set()
    for s in range(20):
        c = CF.control_bc(sig, close, H.rng_of("t", s))
        flip = c["side"] != sig["side"]
        assert flip[0] == flip[1] == flip[2] and flip[3] == flip[4]          # shared by every coin at a close
        assert np.array_equal(c["k"], sig["k"]) and np.array_equal(c["j"], sig["j"])
        seen.add((bool(flip[0]), bool(flip[3])))
    assert len(seen) == 4                                                  # independent coins per close
    a = CF.control_bc(sig, close, H.rng_of(*CF.seed_parts("R2:x", "bc", "test", 0.005, 3)))
    b = CF.control_bc(sig, close, H.rng_of(*CF.seed_parts("R2:x", "bc", "test", 0.005, 3)))
    assert np.array_equal(a["side"], b["side"])


def test_ac_weeks_on_the_test_period():
    mk = types.SimpleNamespace(start=H.day_ms("2024-01-01"), end=H.day_ms("2026-10-01"))
    w = CF.ac_weeks(mk)
    assert (mk.end - mk.start) // DAY == 1004 and len(w) == 136 and w[0] == 4 and w[-1] == 139
    assert CF.seed_parts("R2:F1:E1:1h:G1:abc", "a", "test", 0.005, 7) == ("hunt-r2", "R2:F1:E1:1h:G1:abc", "a",
                                                                         "test", 0.005, 7)


def _row(name, fam, tf="1h", gate="G1", no=1, batch=1, peak=None):
    lat = L.coarse(name)
    combo = peak or lat.combos[[i for i in range(len(lat)) if i != lat.default][0]]
    return {"family": fam, "name": name, "anchor": {"tf": tf, "gate": gate}, "default": L.default_combo(name),
            "peak": combo, "pick_no": no, "batch": batch, "rank": no, "id": L.system_id(fam, name, tf, gate, combo)}


def test_system_of_and_default_comparator():
    r = _row("E1", "F1")
    s = CF.system_of(r)
    assert s["id"] == r["id"] and s["kind"] == "hunt" and s["combo"] == r["peak"] and s["pick_no"] == 1
    d = CF.default_system_of(s)
    assert d["combo"] == L.default_combo("E1") and d["tf"] == "1h" and d["gate"] == "G1" and d["id"] != s["id"]
    with pytest.raises(RuntimeError, match="does not match its numbers"):
        CF.system_of(dict(r, id="R2:F1:E1:1h:G1:000000000000"))


def _block(sid, *, ok=True, p=0.001, p_tune=0.001, d2=0.01, ci=(0.001, 0.02), ranks=None, lnM=None):
    ranks = ranks or {}
    lnM = lnM or [0.02] * 12
    chk = {"P0": ok, "P1": ok, "P3": ok, "P4": ok, "p": p, "mean_d_a": 0.01, "mean_d_b": 0.01}
    for c in ("a", "b", "bc", "ac"):
        chk[f"rank_ok_{c}"] = ranks.get(c, True)
        chk[f"rank_p_{c}"] = 0.001 if ranks.get(c, True) else 0.5
    base = {"mean_lnM": float(np.mean(lnM)), "median_M": 1.02, "max_dd": 0.2, "bust": False, "lnM": lnM,
            "n_positions": 100}
    return {"id": sid, "base": base, "cost2": {"mean_lnM": 0.01, "median_M": 1.01, "lnM": lnM}, "checks": chk,
            "tune": {"p_tune": p_tune, "mean_d_tune_x2": d2, "ci90_mean_d_tune": list(ci), "mean_d_tune": 0.005},
            "default": {"id": "d", "base": base, "combo": {}}}


def _picks_doc(rows):
    nos = sorted({r["batch"] for r in rows})
    return {"picks": rows, "batches": [[r["pick_no"] for r in rows if r["batch"] == b] for b in nos]}


def test_batch_walk_bh_pass_tuned_better_and_labels():
    names = [("E1", "F1"), ("E2", "F1"), ("E3", "F1"), ("N20_EMA9_CHOP", "F2"), ("S2_ST_ROC", "F2"),
             ("TSMOM7", "F5"), ("TSMOM28", "F5"), ("TURTLE20", "F5"), ("N13_3OUTSIDE", "F2"), ("F3_BOS", "F3")]
    rows = [_row(n, f, no=i + 1, batch=1) for i, (n, f) in enumerate(names)]
    rows += [_row("N23_HA_ST", "F2", no=11, batch=2), _row("N16_BBRSI", "F2", no=12, batch=2)]
    pk = _picks_doc(rows)
    ids = [CF.system_of(r)["id"] for r in rows]
    spec = {ids[0]: dict(p=0.001), ids[1]: dict(p=0.002, ranks={"ac": False}), ids[2]: dict(p=0.003),
            ids[3]: dict(p=0.2), ids[4]: dict(p=0.004, d2=-0.01), ids[5]: dict(p=0.005, p_tune=0.9, ci=(-0.03, -0.01)),
            ids[6]: dict(p=0.006, ok=False), ids[7]: dict(p=0.004), ids[8]: dict(p=0.001), ids[9]: dict(p=0.002)}
    blocks = {i: _block(i, **spec.get(i, {})) for i in ids}
    full = CF.test_walk(None, pk, 1, block_fn=lambda s: blocks[s["id"]])
    v = full["verdict"]
    passing = set(v["passing"])
    assert ids[0] in passing and ids[1] not in passing                     # every seed-rank part is needed
    assert ids[3] not in passing                                           # p above the batch's BH line
    assert ids[6] not in passing                                           # P0-P4
    assert len(passing) >= 5 and v["batches"][0]["opens_next"] and v["batches_tested"] == [1, 2]
    assert v["r2_pass"] and full["lineup"]["picks"][ids[0]]["lineup"] == "정식"
    c4 = full["results"][ids[4]]["tune"]
    assert c4["bh_significant"] and not c4["TUNED_BETTER"]                 # mean d_tune at cost x2 must be > 0
    assert full["results"][ids[0]]["tune"]["label"]["ko"] == "커스텀이 기본값을 이김"
    assert full["results"][ids[5]]["tune"]["label"]["ko"] == "기본값보다 나쁨"
    assert full["results"][ids[3]]["tune"]["label"]["key"] in ("better", "not_shown")
    # fewer than 5 passes: batch 2 is never run and its members are 'untested'
    for i in ids[:6]:
        blocks[i] = _block(i, p=0.9)
    calls = []
    full2 = CF.test_walk(None, pk, 1, block_fn=lambda s: calls.append(s["id"]) or blocks[s["id"]])
    assert full2["verdict"]["batches_tested"] == [1] and set(full2["verdict"]["untested"]) == set(ids[10:])
    assert not set(calls) & set(ids[10:])
    sel_fail = CF.selection_failed_doc({"label": "round 2 fails at selection"})
    assert sel_fail["verdict"]["r2_pass"] is False and sel_fail["picks"] == []


def test_redaction_and_d11_of_test_json():
    r = _row("F3_BOS", "F3")
    s = CF.system_of(r)
    blk = _block(s["id"])
    blk["tune"].update({"bh_significant": True, "TUNED_BETTER": True, "label": CF.tune_label(True, [0.1, 0.2])})
    blk["checks"].update({"bh_significant": True, "PASS": True, "batch": 1})
    blk["default"]["combo"] = L.default_combo("F3_BOS")
    full = {"picks": [s], "untested": [], "verdict": {"passing": [s["id"]]}, "lineup": {}, "results": {s["id"]: blk}}
    pub = CF.redact_test(full)
    assert CF.d11_problems(pub, {s["id"]}) == []
    pb = pub["results"][s["id"]]
    assert pb["checks"]["PASS"] and "p" not in pb["checks"] and "mean_d_tune_x2" not in pb["tune"]
    assert pb["tune"]["label"]["ko"] == "커스텀이 기본값을 이김"
    assert CF.d11_problems(full, {s["id"]})                                # the full document is not public
    assert CF.d11_problems({"results": {s["id"]: {"x": 0.5}}}, {s["id"]}) == ["test.results.R2:F3:F3_BOS:1h:G1:"
                                                                              f"{L.combo_sha(r['peak'])}.x"]
    assert CF.d11_problems({"picks": [{"family": "F3", "combo": {"a": 0.5}}]}, set()) == []


# ------------------------------------------------------------------ 8: the ledger on a temporary tree
def _write(root, rel, obj):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        json.dump(obj, fh)
    return p


def test_ledger_three_prints_on_a_temporary_tree(tmp_path):
    root, priv = str(tmp_path / "repo"), str(tmp_path / "ledger_inputs")
    os.makedirs(priv)
    for rel in (LG.R1_PIN["v1"], LG.R1_PIN["wide"], LG.T2_PIN, LG.R2_PIN):
        _write(root, rel, {})
    _write(root, LG.R1_V1_TEST, {"pick": {"id": "v1:E1:1h"}, "result": {"checks": {"p": 0.003}},
                                 "reads": {"r1": {"checks": {"p": 0.02}}}})
    wide_priv = {"results": {"F3:DSX:1h:G1": {"checks": {"p": 0.0004}}}}
    pp = _write(priv, "wide_test_private.json", wide_priv)
    _write(root, LG.R1_WIDE_TEST, {
        "picks": [{"id": "F2:AAA:1h:G1", "kind": "core"}, {"id": "F3:DSX:1h:G1", "kind": "ds"}],
        "results": {"F2:AAA:1h:G1": {"checks": {"p": 0.0001}}, "F3:DSX:1h:G1": {"checks": {"PASS": False}}},
        "reads": {"F2:AAA:1h:G1": {"r1": {"checks": {"p": 0.5}}}, "F3:DSX:1h:G1": {"note": "D11"}},
        "verdict": {"batches": [{"batch": 1}]}, "untested": ["F2:BBB:4h:G1"], "private_sha256": H.sha256_file(pp)})
    _write(root, LG.R1_WIDE_READS_O, {"out": {"rows": {
        "pick:F2:AAA:1h:G1": {"periods": {"test": {"O4": {"e": {"p_boot": 0.04}}}}},
        "pick:F3:DSX:1h:G1": {"note": RO.DS_NOTE}}}})
    _write(root, LG.T2_TEST, {"results": {"S4|4h|1|L30": {"p": 0.01, "checks": {"T0": True}},
                                          "DS|1h|2|L30": {"checks": {"T0": True}},
                                          "S5|1h|3|L30": {"p": 0.0001, "checks": {"T0": False}}},
                              "private_sha256": "0" * 64})
    _write(priv, "test_private.json", {"results": {"DS|1h|2|L30": {"p": 0.0}}})      # sha differs: not read
    r2 = {"picks": [{"id": "R2:F1:E1:1h:G1:abc", "family": "F1"}, {"id": "R2:F3:F3_BOS:1h:G1:def", "family": "F3"}],
          "results": {"R2:F1:E1:1h:G1:abc": {"checks": {"p": 1e-5}, "tune": {"p_tune": 0.3}},
                      "R2:F3:F3_BOS:1h:G1:def": {"checks": {"p": 0.2}, "tune": {"p_tune": 0.6}}},
          "verdict": {"passing": ["R2:F1:E1:1h:G1:abc"]}}
    fg = _write(str(tmp_path), "confirm.json", {"rows": [{"kind": "core", "name": "X", "tf": "1h", "rank": i,
                                                          "test": {"p": 0.5, "n": 150 if i else 50}}
                                                         for i in range(711)]})
    snap = LG.snapshot(root, priv, r2, fg)
    A, Ap, Lp = (snap["prints"][k] for k in ("A", "A+", "L"))
    ids = {r["id"]: r for r in A["rows"]}
    assert A["m"] == 2 + 4 + 2 + 3 + 4                    # v1 (pick, 1%) + wide (2 picks, 2 r=1%) + O4 x2 + T2 + R2
    assert ids["F3:DSX:1h:G1"]["p"] == 0.0004 and ids["F3:DSX:1h:G1"]["deepseek"]
    assert ids["F3:DSX:1h:G1 r=1%"]["p"] == 1.0 and "private, not read" in ids["F3:DSX:1h:G1 r=1%"]["p_status"]
    assert ids["DS|1h|2|L30"]["p"] == 1.0 and ids["S5|1h|3|L30"]["p"] == 1.0          # sha mismatch; T0 fails
    assert ids["R2:F1:E1:1h:G1:abc tune"]["p"] == 0.3
    assert Ap["m"] == A["m"] + 711 + 38
    assert sum(1 for r in Ap["rows"] if r["study"] == "full grid" and r["p"] == 1.0) == 1   # n < 100 -> p = 1
    assert Lp["m"] == Ap["m"] and snap["pending_looks_in_L"] == []        # every hashed look has run here
    assert snap["listed_not_counted"][0]["id"] == "F2:BBB:4h:G1"
    assert "R2:F1:E1:1h:G1:abc" in snap["round2_live_gate"]
    pub = LG.public_of(snap)
    for k in ("A", "A+", "L"):
        for r in pub["prints"][k]["rows"]:
            assert ("p" in r) != r["deepseek"]
    # BH and Holm by hand on (A)
    p = np.array([r["p"] for r in A["rows"]])
    assert [r["bh_q10"] for r in A["rows"]] == H.bh(p, 0.10)
    order = np.argsort(p, kind="stable")
    holm = np.zeros(len(p), bool)
    for r_, i in enumerate(order):
        if p[i] <= 0.05 / (len(p) - r_):
            holm[i] = True
        else:
            break
    assert [r["holm_005"] for r in A["rows"]] == holm.tolist()
    # before round 2's test and track 2's test: pending looks count in (L) at their maximum, p = 1
    os.remove(os.path.join(root, LG.T2_TEST))
    _write(root, LG.R2_PICKS, {"picks": [{"id": "a"}, {"id": "b"}, {"id": "c"}]})
    snap2 = LG.snapshot(root, priv, None, None)
    pend = {x["study"]: x["hypotheses"] for x in snap2["pending_looks_in_L"]}
    assert pend == {"hunt-r2 v1": 6, "track 2 (hiwr v1)": LG.T2_MAX}
    assert snap2["prints"]["L"]["m"] == snap2["prints"]["A+"]["m"] + 6 + LG.T2_MAX
    assert snap2["prints"]["A+"]["m"] == snap2["prints"]["A"]["m"] + 711 + 38       # full grid without a file: p = 1


def test_holm_and_bh_parity_with_track_two():
    try:
        from research.hiwr import hiwr as T2
    except Exception as e:  # noqa: BLE001  track 2's code is another job's; parity only when it imports
        pytest.skip(f"track 2's ledger code does not import here: {type(e).__name__}")
    rng = np.random.default_rng(5)
    for _ in range(50):
        p = list(np.round(rng.uniform(0, 0.2, rng.integers(1, 40)) ** 2, 6))
        assert LG.holm(p) == T2.holm(p) and LG.bh(p) == list(T2.bh(p))


# ------------------------------------------------------------------ 11: the pin
def test_pinlist_own_hashes_and_step_checks_on_a_temporary_tree(tmp_path):
    root = str(tmp_path)
    files = {PN.DESIGN: b"design", PN.COUNTS: b"{}", PN.BENCH: b"{}", "research/hunt_r2/confirm_r2.py": b"c",
             "tests/test_hunt_r2_cli.py": b"t", "research/hunt/hunt.py": b"engine2",
             "research/hunt/reads_o.py": b"reads"}
    for rel, data in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    eng = ["research/hunt/hunt.py", "research/hunt/reads_o.py"]
    (tmp_path / PN.R1_PIN).write_text(f"{_sha(b'engine1')}  research/hunt/hunt.py\n{_sha(b'reads')}  "
                                      "research/hunt/reads_o.py\n" + f"{'f' * 64}  research/hunt/out/wide/x.json\n")
    lines = PN.pinlist(root, eng + [PN.R1_PIN, "research/hunt/out/wide/x.json"])
    paths = [ln.split("  ", 1)[1] for ln in lines]
    assert PN.R1_PIN not in paths and not any(p.startswith("research/hunt/out/") for p in paths)
    for ln in lines:
        h, p = ln.split("  ", 1)
        assert h == _sha(files[p])                                      # each file by its own sha256
    assert PN.pinlist_problems(root, eng) == ["changed since round 1's pin: research/hunt/hunt.py"]
    (tmp_path / "research/hunt/hunt.py").write_bytes(b"engine1")
    files["research/hunt/hunt.py"] = b"engine1"
    assert PN.pinlist_problems(root, eng) == []
    (tmp_path / PN.R2_PIN).write_text("\n".join(PN.pinlist(root, eng)) + "\n")
    assert PN.check_pin("select", root, eng)["files"] == len(files)
    for step in ("pretest", "test", "reads"):
        with pytest.raises(RuntimeError, match="picks.json is not pinned"):
            PN.check_pin(step, root, eng)
    os.makedirs(tmp_path / "research/hunt_r2/out")
    (tmp_path / PN.PICKS).write_text("{}")
    PN.append_line(PN.PICKS, root)
    PN.check_pin("pretest", root, eng)
    PN.check_pin("test", root, eng)
    with pytest.raises(RuntimeError, match="reads run only after the test step"):
        PN.check_pin("reads", root, eng)
    (tmp_path / PN.TEST).write_text("{}")
    PN.append_line(PN.TEST, root)
    PN.check_pin("reads", root, eng)
    with pytest.raises(RuntimeError, match="one look"):
        PN.check_pin("test", root, eng)
    (tmp_path / PN.PICKS).write_text('{"changed": 1}')
    with pytest.raises(RuntimeError, match="changed research/hunt_r2/out/picks.json"):
        PN.check_pin("reads", root, eng)
    assert PN.is_pinned(PN.TEST, root) and not PN.is_pinned(PN.PICKS, root)


def test_pinlist_is_deterministic_in_fresh_processes():
    env = dict(os.environ, PYTHONPATH=ROOT)
    cmd = [sys.executable, "-m", "research.hunt_r2.hunt_r2", "pinlist"]
    procs = [subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for _ in range(2)]
    outs = [p.communicate(timeout=600) for p in procs]
    a, b = outs[0][0], outs[1][0]
    assert a == b and a.strip()
    lines = a.strip().splitlines()
    paths = [ln.split("  ", 1)[1] for ln in lines]
    assert paths[0] == PN.DESIGN and len(paths) == len(set(paths))
    assert PN.R1_PIN not in paths and not any(p.startswith(("research/hunt/out/", "research/hunt_r2/out/"))
                                              for p in paths)
    for f in ("research/hunt/hunt.py", "research/hunt/entries_wide.py", "research/hunt/reads_a.py",
              "research/hunt/reads_o.py", "research/hunt_r2/confirm_r2.py", "research/hunt_r2/ledger.py",
              "research/hunt_r2/reads_r2.py", "tests/test_hunt_r2_cli.py", PN.COUNTS):
        assert f in paths, f
    for ln in lines[:12] + lines[-5:]:
        h, p = ln.split("  ", 1)
        assert h == H.sha256_file(os.path.join(ROOT, p))


# ------------------------------------------------------------------ end to end on synthetic coins
S0 = H.day_ms("2022-01-01")
SPAN_DAYS = 300
SYMS = ("BTCUSDT", "ETHUSDT", "AAAUSDT", "BBBUSDT")
PERIODS = {"extra": ("2022-07-01", "2022-07-21"), "select": ("2022-07-21", "2022-09-01"),
           "test": ("2022-09-01", "2022-10-27")}
NAMES = ("E1", "N20_EMA9_CHOP", "F3_BOS", "TSMOM7")
_E: dict = {}


def _cut_coin(c, end_ms):
    m = c.ts < end_ms
    return H.Coin(c.sym, c.ts[m], c.o[m], c.h[m], c.l[m], c.c[m], c.v[m], c.qv[m],
                  counts={"content_sha256": "synthetic", "funding_content_sha256": "synthetic"})


def _tree(repo):
    """A temporary repository: the design (first pin line), counts, bench, the reads modules round 2 runs."""
    files = {PN.DESIGN: b"synthetic design\n", PN.COUNTS: b"{}\n", PN.BENCH: b"{}\n"}
    for rel in (RR.MODULES["rows"]["rel"], RR.MODULES["reads_o"]["rel"], RR.MODULES["reads_a"]["rel"]):
        with open(os.path.join(ROOT, rel), "rb") as fh:
            files[rel] = fh.read()
    for rel, data in files.items():
        p = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)
    with open(os.path.join(repo, PN.R2_PIN), "w") as fh:
        fh.write("".join(f"{_sha(files[r])}  {r}\n" for r in files))


@pytest.fixture(scope="module")
def e2e(tmp_path_factory):
    if "done" in _E:
        return _E
    mp = pytest.MonkeyPatch()
    base = tmp_path_factory.mktemp("r2e2e")
    repo, priv, data = str(base / "repo"), str(base / "priv"), str(base / "data")
    os.makedirs(data)
    _tree(repo)
    coins = {s: H.synth_coin(s, S0, S0 + SPAN_DAYS * DAY, 70 + i, 10.0 * (i + 1)) for i, s in enumerate(SYMS)}
    fund = {s: H.synth_funding(S0, S0 + SPAN_DAYS * DAY, 80 + i) for i, s in enumerate(SYMS)}
    loads = []

    def fake_load(data_dir, syms, end_ms):
        picks_pinned = PN.PICKS in PN.listed_now(repo)
        loads.append((int(end_ms), picks_pinned))
        cut = {s: _cut_coin(coins[s], end_ms) for s in syms}
        fd = {s: (fund[s][0][fund[s][0] < end_ms], fund[s][1][fund[s][0] < end_ms]) for s in syms}
        H.install(cut, fd)
        return {s: dict(cut[s].counts) for s in syms}

    for k, v in PERIODS.items():
        mp.setitem(H.PERIODS, k, v)
    mp.setattr(H, "load_universe", lambda data_dir=None: list(SYMS))
    mp.setattr(H, "load_study_data", fake_load)
    mp.setattr(H, "data_identity_problems", lambda counts, fund_sha: [])
    mp.setattr(HR, "ROOT", repo)
    mp.setattr(PN, "engine_files", lambda: [])
    mp.setattr(L, "names", lambda: [(L.family_of(n), n) for n in NAMES])
    mp.setattr(SR, "N_REP", 2)
    orig_search, orig_box = SR.search, SR.box_check
    mp.setattr(SR, "search", lambda units, order, real, min_pos=6: orig_search(units, order, real, min_pos))
    mp.setattr(SR, "box_check", lambda S, S2, n, bust, exists, min_pos=6: orig_box(S, S2, n, bust, exists, min_pos))
    mp.setattr(SR, "step_down", lambda real_P, a, b, q=95.0: [
        {"rank": r, "taken": True, "label": "taken", "thr_a": 0.0, "thr_b": 0.0} for r in range(1, len(real_P) + 1)])
    for mod, k, v in ((CF, "N_SEEDS", 4), (CF, "N_BOOT", 400), (CF, "CTL_TASK_SEEDS", 3), (RR, "SELECT_SEEDS", 3),
                      (PT, "N_BLOCKS", 2), (PT, "BLOCK_MONTHS", 1), (PT, "BOARD_CTL_SEEDS", 2),
                      (PT, "BOARD_LEV_SEEDS", 2), (RO, "CTL_SEEDS", 3), (RO, "CTL_TASK_SEEDS", 3),
                      (RO, "E_SEEDS", {"test": 3, "select": 3}), (RO, "E_TASK_SEEDS", 3), (RA, "CAL_CTL_SEEDS", 2),
                      (RA, "ROLL_CTL_SEEDS", 2), (RA, "ROLL_CTL_SEEDS_SLOW", 2), (RA, "LEV_CTL_SEEDS", 2),
                      (RA, "MBB_N", 100)):
        mp.setattr(mod, k, v)
    args = ["--data", data, "--private", priv, "--procs", "2"]
    import time as _t
    t0 = _t.time()
    try:
        _E["rc"] = {"select": HR.main(["select", *args])}
        _E["rc"]["pretest"] = HR.main(["pretest", *args])
        _E["rc"]["test"] = HR.main(["test", *args, "--ledger-private", str(base / "none")])
        _E["rc"]["report"] = HR.main(["report", "--private", priv])
        _E["rc"]["test_again"] = HR.main(["test", *args])
        _E["seconds"] = _t.time() - t0
        print(f"[e2e] synthetic select + pretest + test + reads + report: {_E['seconds']:.0f}s")
        _E.update(repo=repo, priv=priv, loads=loads, done=True, mk_test=H.Market(list(SYMS), "test"))
        yield _E
    finally:
        mp.undo()
        _E.clear()


def _out(e, name):
    with open(os.path.join(e["repo"], "research/hunt_r2/out", name)) as fh:
        return json.load(fh)


def test_e2e_steps_run_and_refuse_a_second_look(e2e):
    assert e2e["rc"] == {"select": 0, "pretest": 0, "test": 0, "report": 0, "test_again": 2}
    pin = PN.listed_now(e2e["repo"])
    for rel in (PN.PICKS, PN.PRETEST, PN.TEST):
        assert PN.is_pinned(rel, e2e["repo"]), rel
    rows = open(os.path.join(e2e["repo"], PN.R2_PIN)).read().splitlines()
    order = [r.split("  ", 1)[1] for r in rows]
    assert order[0] == PN.DESIGN and order.index(PN.PICKS) < order.index(PN.PRETEST) < order.index(PN.TEST)
    assert set(pin) >= {PN.PICKS, PN.PRETEST, PN.TEST}


def test_e2e_test_data_only_after_the_picks_line(e2e):
    sel_end, test_end = (H.day_ms(PERIODS[k][1]) for k in ("select", "test"))
    loads = e2e["loads"]
    assert loads[0] == (sel_end, False)                                   # select: select bars only, no picks yet
    assert all(end == sel_end for end, _ in loads[:2])                    # select and pretest
    later = [x for x in loads if x[0] > sel_end]
    assert later and all(end == test_end and pinned for end, pinned in later)


def test_e2e_picks_and_test_json(e2e):
    pk = _out(e2e, "picks.json")
    assert [r["name"] for r in pk["names"]] == [n for _f, n in L.names()]
    assert pk["picks"], "the synthetic world must give at least one pick for this test"
    test = _out(e2e, "test.json")
    assert test["test_data_read"] and test["picks"]
    tested = {p["id"] for p in test["picks"]}
    assert tested == {p["id"] for p in pk["picks"] if p["batch"] == 1} | {
        p["id"] for p in pk["picks"] if p["batch"] > 1 and p["batch"] - 1 in [b["batch"] for b in
                                                                              test["verdict"]["batches"]
                                                                              if b["opens_next"]]}
    for p in test["picks"]:
        blk = test["results"][p["id"]]
        assert blk["default"]["combo"] == L.default_combo(p["name"])
        if CF.is_ds(p):
            assert "p" not in blk["checks"] and blk["note"] == CF.DS_NOTE
        else:
            c = blk["checks"]
            assert c["p"] == max(c["p_a"], c["p_b"]) and c["p_a"] == max(c["p_boot_a"], c["p_t_a"])
            assert c["n_a"] == c["n_b"] == c["n_bc"] == CF.N_SEEDS and c["n_ac"] == len(CF.ac_weeks(e2e["mk_test"]))
            assert blk["tune"]["p_tune"] == max(blk["tune"]["p_boot_tune"], blk["tune"]["p_t_tune"])
            assert blk["tune"]["label"]["key"] in CF.TUNE_LABELS
        assert c["PASS"] == (all(c[k] for k in ("P0", "P1", "P3", "P4")) and c["bh_significant"]
                             and all(c[f"rank_ok_{x}"] for x in ("a", "b", "bc", "ac")))
    lg = test["ledger"]
    assert set(lg["prints"]) == {"A", "A+", "L"} and lg["line"] == "four studies share one 33-month period"
    r2rows = [r for r in lg["prints"]["A"]["rows"] if r["study"] == "hunt-r2 v1"]
    assert len(r2rows) == 2 * len(test["picks"])


def test_e2e_d11_on_every_public_output_and_the_report(e2e):
    pk = _out(e2e, "picks.json")
    ds = {p["id"] for p in pk["picks"] if p["family"] == "F3"}
    ds |= {f"pick:{i}" for i in ds}
    names_ds = {r["name"] for r in pk["names"] if r["family"] == "F3"}
    for f in sorted(os.listdir(os.path.join(e2e["repo"], "research/hunt_r2/out"))):
        if not f.endswith(".json"):
            continue
        doc = _out(e2e, f)
        assert CF.d11_problems(doc, ds, f) == [], f
        assert SR.d11_problems(doc) == [], f
    with open(os.path.join(e2e["repo"], "research/hunt_r2/out", RP.REPORT)) as fh:
        rep = fh.read()
    for ln in rep.splitlines():
        if any(f"| {n} |" in ln for n in names_ds):
            assert "×" not in ln and "%" not in ln, ln
    assert "기본값 → 찾은 값" in rep and "봉 4가지 × 주말 포함/제외" in rep and "주말 제외 (O1)" in rep
    for n in NAMES:
        assert f"| {n} |" in rep


def test_e2e_pretest_reads(e2e):
    pre = _out(e2e, "pretest_reads.json")
    assert pre["label"] == "computed before test.json (6)"
    t4 = pre["four_timeframes"]["rows"]
    assert set(t4) == set(NAMES)
    for nm, t in t4.items():
        assert set(t["timeframes"]) == set(L.tfs_of(nm))
        for tf, by in t["timeframes"].items():
            x = by["default"]
            if t["family"] != "F3" and "removed" not in x:
                assert set(x) == {"base", "O1", "O1b"}
                assert x["O1"]["positions"] <= x["base"]["positions"] or x["O1"]["skipped"] > 0
    assert pre["null_summary"]["nulls"]["a"]["replicates"] == SR.N_REP if "a" in pre["null_summary"]["nulls"] else True
    assert pre["cscv"]["strict"]["splits"] == 2
    assert isinstance(pre["near_miss"], list) and "momentum_c_prime" in pre and "weekend_map" in pre
    board = pre["owner_board"]
    assert board and all(k.endswith(("|peak", "|default")) for k in board)


def test_e2e_reads_written_under_the_guard(e2e):
    out_dir = os.path.join(e2e["repo"], "research/hunt_r2/out")
    for f in ("reads_rows.json", "reads_weekend.json", "reads_goal.json"):
        d = _out(e2e, f)
        assert d["reads_line_predates_test_json"] is True and d["test_json_sha256"] == H.sha256_file(
            os.path.join(out_dir, "test.json"))
    rw = _out(e2e, "reads_weekend.json")["out"]
    assert rw["calendar"]["run"] is False and "not a round-2 read" in rw["calendar"]["reason"]
    rr = _out(e2e, "reads_rows.json")["out"]["rows"]
    test = _out(e2e, "test.json")
    assert set(rr) == {f"pick:{p['id']}" for p in test["picks"]}


def test_e2e_controls_do_not_depend_on_the_worker_count(e2e):
    test = _out(e2e, "test.json")
    p = next(p for p in test["picks"])
    mk = e2e["mk_test"]
    syms = list(SYMS)
    H.load_study_data("x", syms, H.day_ms(PERIODS["test"][1]))
    mk = H.Market(syms, "test")
    sig = CF.signals(mk, p)
    a = CF.run_controls(mk, p, sig, H.R_BASE, 1, 3)
    b = CF.run_controls(mk, p, sig, H.R_BASE, 2, 3)
    for c in CF.RANK_PARTS:
        assert np.array_equal(a[c], b[c])
    blk = test["results"][p["id"]]
    if not CF.is_ds(p):
        assert blk["controls"]["a_mean_lnM"][:3] == pytest.approx(a["a"].mean(axis=1).tolist())


def test_e2e_round_two_signals_equal_the_store_on_the_select_period(e2e):
    """The test step's signals (round 2's events on the installed series) equal the select step's store signals for
    the same combo, gate and period."""
    pk = _out(e2e, "picks.json")
    syms = list(SYMS)
    H.load_study_data("x", syms, H.day_ms(PERIODS["select"][1]))
    mk = H.Market(syms, "select")
    ctx = SR.Ctx(mk, os.path.join(e2e["priv"], "store"))
    CF.clear_caches()
    for r in pk["names"][:3]:
        lat = L.coarse(r["name"])
        units = SR.load_units(ctx.root, "coarse", r["name"], r["anchor"]["tf"], ctx.syms)
        for ci in {lat.default, len(lat) - 1}:
            sys_ = {"id": L.system_id(r["family"], r["name"], r["anchor"]["tf"], r["anchor"]["gate"], lat.combos[ci]),
                    "family": r["family"], "name": r["name"], "kind": L.KIND_OF[r["family"]], "tf": r["anchor"]["tf"],
                    "gate": r["anchor"]["gate"], "combo": lat.combos[ci]}
            a = CF.signals(mk, sys_)
            b = SR.store_sig(ctx, units, ci, r["anchor"]["gate"], r["anchor"]["tf"])
            assert SR.sig_hash(a) == SR.sig_hash(b), (r["name"], ci)


def test_selection_failed_test_reads_no_test_data(tmp_path, monkeypatch):
    repo, priv = str(tmp_path / "repo"), str(tmp_path / "priv")
    _tree(repo)
    os.makedirs(os.path.join(repo, "research/hunt_r2/out"))
    _write(repo, PN.PICKS, {"names": [], "picks": [], "batches": [], "label": "round 2 fails at selection"})
    PN.append_line(PN.PICKS, repo)
    monkeypatch.setattr(HR, "ROOT", repo)
    monkeypatch.setattr(PN, "engine_files", lambda: [])
    called = []
    monkeypatch.setattr(H, "load_study_data", lambda *a: called.append(a) or {})
    assert HR.main(["test", "--data", str(tmp_path), "--private", priv, "--ledger-private", str(tmp_path)]) == 0
    doc = _out({"repo": repo}, "test.json")
    assert called == [] and doc["test_data_read"] is False and doc["verdict"]["r2_pass"] is False
    assert not [r for r in doc["ledger"]["prints"]["A"]["rows"] if r["study"] == "hunt-r2 v1"]
    assert PN.is_pinned(PN.TEST, repo)
    assert HR.main(["reads", "--data", str(tmp_path), "--private", priv]) == 0


def test_cli_refuses_without_the_lines(tmp_path, monkeypatch):
    repo, priv = str(tmp_path / "repo"), str(tmp_path / "priv")
    _tree(repo)
    monkeypatch.setattr(HR, "ROOT", repo)
    monkeypatch.setattr(PN, "engine_files", lambda: [])
    called = []
    monkeypatch.setattr(H, "load_study_data", lambda *a: called.append(a) or {})
    common = ["--data", str(tmp_path), "--private", priv]
    for cmd in ("test", "pretest", "reads"):
        assert HR.main([cmd, *common]) == 2                       # no picks line
    assert called == []
    with open(os.path.join(repo, PN.R2_PIN)) as fh:
        txt = fh.read().splitlines()
    with open(os.path.join(repo, PN.R2_PIN), "w") as fh:          # design hash not first: every step refuses
        fh.write("\n".join(txt[1:] + txt[:1]) + "\n")
    assert HR.main(["select", *common]) == 2 and called == []
    with pytest.raises(SystemExit, match="outside the repository"):
        HR.main(["select", "--data", str(tmp_path), "--private", os.path.join(repo, "x")])
