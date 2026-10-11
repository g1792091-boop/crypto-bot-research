"""research/regimegate/gate.py (PREREG_REGIMEGATE.md): the style map, the gates, the block bootstrap, the coin-flip
control, the verdict lines and the decision, on hand-made numbers only (no market data)."""

from __future__ import annotations

import importlib.util
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _load():
    name = "regimegate_gate"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "research", "regimegate", "gate.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


GT = _load()
WEEK = 7 * 86_400_000


def test_style_map_covers_the_80_strategies():
    core = sorted(f[:-3] for f in os.listdir(os.path.join(ROOT, "research", "entry_study", "param_defs"))
                  if f.endswith(".py") and not f.startswith("_"))
    st = GT.style()
    assert sorted(st["core"]) == core
    assert sorted(st["ds"]) == sorted(GT.R.ds_module().DEFS)
    for kind in ("core", "ds"):
        for name, e in st[kind].items():
            base = e["catalog"].rstrip("*").strip()
            base = base.rsplit(" ", 1)[0] if base.rsplit(" ", 1)[-1].replace(".", "").isdigit() else base
            assert st["rules"][base] == e["class"] in GT.CLASSES, name
    count = {k: {c: sum(e["class"] == c for e in st[k].values()) for c in GT.CLASSES} for k in ("core", "ds")}
    assert count == {"core": {"trend": 19, "reversion": 5, "other": 12}, "ds": {"trend": 26, "reversion": 14, "other": 4}}
    assert GT.style_class("core", "OBV_S") == "other"            # the measured label wins over the name
    assert GT.style_class("ds", "F9_IFVG") == "trend" and GT.style_class("ds", "F12_MSS") == "other"


def test_reads_are_the_live_exit_and_4atr_3r():
    assert [GT.K.EXITS[e][0] for e in GT.READ_IDX] == ["ladder|2", "tp3R|4"]
    assert GT.READ_IDX[0] == 0 and GT.K.EXITS[GT.READ_IDX[1]][1] == 4.0


def test_allowed_mask_and_swaps():
    tr, rv, ot = (GT.CLASSES.index(c) for c in GT.CLASSES)
    cls = np.array([tr, tr, tr, rv, rv, ot, ot, tr])
    reg = np.array([1, 2, 3, 1, 2, 1, 2, 4])          # 추세장 횡보장 급변장 추세장 횡보장 추세장 횡보장 보통
    vol = np.array([3, 1, 2, 3, 1, 3, 1, 3])          # 큼 작음 보통 큼 작음 큼 작음 큼
    assert GT.allowed_mask(GT.GATES["G1"], cls, reg, vol).tolist() == [1, 0, 0, 0, 1, 1, 0, 0]
    assert GT.allowed_mask(GT.GATES["G2"], cls, reg, vol).tolist() == [1, 0, 0, 0, 1, 1, 0, 1]
    assert GT.allowed_mask(GT.SWAPS["G1s"], cls, reg, vol).tolist() == [0, 1, 0, 1, 0, 1, 0, 0]
    assert GT.SWAPS["G2s"]["allow"] == {"trend": ("작음",), "reversion": ("큼",), "other": ("큼",)}


def test_boot_diff_p():
    rng = np.random.default_rng(1)
    n = 4000
    block = np.repeat(np.arange(200), n // 200)
    allowed = rng.random(n) < 0.4
    x = rng.normal(0, 0.02, n)
    assert GT.boot_diff_p(block, x + 0.01 * allowed, allowed, 500, 7) < 0.01
    assert GT.boot_diff_p(block, x - 0.01 * allowed, allowed, 500, 7) > 0.99
    assert GT.boot_diff_p(block, x, np.ones(n, bool), 500, 7) is None


def test_flip_control_blocks_the_same_count_per_cell():
    # x constant within a cell: a draw that blocks the gate's count in every cell gives exactly the gate's difference
    cell = np.repeat(np.arange(3), [50, 80, 20])
    x = np.repeat([1.0, 2.0, 5.0], [50, 80, 20])
    blocked = {"G1": np.r_[np.ones(10, bool), np.zeros(40, bool), np.ones(40, bool), np.zeros(40, bool),
                           np.zeros(20, bool)]}
    lines = np.array([[True, True, True], [False, True, False]])
    out = GT.flip_control(cell, x, blocked, lines, 50, 3)["G1"]
    assert out.shape == (50, 2)
    assert np.allclose(out[:, 0], 220 / 100 - 90 / 50) and np.allclose(out[:, 1], 0.0)
    # random values: the draws scatter around 0
    rng = np.random.default_rng(2)
    xr = rng.normal(0, 1, len(cell))
    o2 = GT.flip_control(cell, xr, blocked, lines, 400, 4)["G1"]
    assert abs(o2[:, 1].mean()) < 0.1 and o2[:, 1].std() > 0.05


def _synthetic(effect: float, seed: int = 5):
    cells = (("core", "S2_ST_ROC", "15m"), ("core", "N17_KC_RSI", "15m"), ("core", "S3_CMO_SANDWICH", "1h"),
             ("ds", "F5_BOX", "15m"), ("ds", "F3_BOS", "4h"))
    rng = np.random.default_rng(seed)
    n = 30_000
    cell = rng.integers(0, len(cells), n).astype(np.int16)
    close = np.sort(rng.integers(GT.HIST_FROM, GT.HIST_FROM + 150 * WEEK, n)).astype(np.int64)
    reg = rng.integers(0, 5, n).astype(np.int8)       # 0 = 모름 is left out
    vol = rng.integers(1, 4, n).astype(np.int8)
    cls = np.array([GT.CLASSES.index(GT.style_class(k, nm)) for k, nm, _tf in cells])[cell]
    allowed = GT.allowed_mask(GT.GATES["G1"], cls, reg, vol)
    x0 = rng.normal(-0.01, 0.03, n) + effect * allowed
    x1 = rng.normal(-0.002, 0.03, n)
    x1[::7] = np.nan                                  # not sized at this exit
    T = {"cell": cell, "coin": np.zeros(n, np.int8), "side": np.ones(n, np.int8), "close": close, "x0": x0, "x1": x1,
         "regime": reg, "vol": vol}
    return T, cells


def test_evaluate_passes_a_real_gate_and_hides_deepseek_money():
    T, cells = _synthetic(0.03)
    doc = GT.evaluate(T, "history", cells, money=False, n_flip=100)
    rd = doc["reads"]["ladder|2"]
    v = {(ln["gate"], ln["group"]): ln for ln in rd["lines"] if ln["role"] == "verdict"}
    assert rd["unknown_state"] > 0 and rd["used"] == rd["signals"] - rd["unknown_state"]
    assert v[("G1", "pooled")]["pass"] is True and v[("G1", "trend")]["pass"] is True
    assert v[("G2", "pooled")]["pass"] is False
    assert "mean_allowed" not in v[("G1", "pooled")]                  # DeepSeek trades are in the line
    core = [ln for ln in rd["lines"] if ln["universe"] == "core" and ln["gate"] == "G1" and ln["group"] == "pooled"]
    assert core and core[0]["mean_allowed"] is not None and core[0]["pass"] is None
    assert v[("G1s", "pooled")]["pass"] is None and v[("G1s", "pooled")]["control_p"] is None
    assert all("mean" not in d for k, d in rd["states"].items() if not k.startswith("core|"))
    assert all("diff" not in d for k, d in rd["years"].items() if "|all|" in k)
    # the second read has no effect: nothing passes
    rd1 = doc["reads"]["tp3R|4"]
    assert not any(ln["pass"] for ln in rd1["lines"] if ln["role"] == "verdict" and ln["gate"] in GT.GATES)
    money = GT.evaluate(T, "history", cells, money=True, n_flip=20)
    vm = [ln for ln in money["reads"]["ladder|2"]["lines"] if ln["role"] == "verdict" and ln["gate"] == "G1"]
    assert vm[0]["diff"] > 0


def test_forward_uses_days_and_core_only():
    T, cells = _synthetic(0.0)
    keep = np.array([k == "core" for k, _n, _tf in cells])[T["cell"]]
    T = {k: v[keep] for k, v in T.items()}
    T["close"] = np.sort(np.random.default_rng(3).integers(GT.FWD_FROM, GT.FWD_FROM + 25 * 86_400_000,
                                                           len(T["cell"]))).astype(np.int64)
    doc = GT.evaluate(T, "forward", cells, money=False, n_flip=20)
    lines = doc["reads"]["ladder|2"]["lines"]
    assert {ln["universe"] for ln in lines} == {"core"}
    assert all("mean_allowed" in ln for ln in lines)                  # core only: money shown
    assert not any(ln["pass"] for ln in lines if ln["role"] == "verdict" and ln["gate"] in GT.GATES)


def test_decide():
    def doc(passes):
        return {"reads": {"ladder|2": {"lines": [
            {"gate": g, "group": grp, "role": "verdict", "pass": passes.get((g, grp), False)}
            for g in ("G1", "G2", "G1s") for grp in GT.GROUPS]}}}
    h = doc({("G1", "trend"): True, ("G1", "pooled"): True, ("G1s", "pooled"): True})
    f = doc({("G1", "trend"): True, ("G2", "other"): True})
    d = GT.decide(h, f)
    res = {(r["gate"], r["group"]): r["result"] for r in d["rows"]}
    assert res[("G1", "trend")] == "candidate" and res[("G1", "pooled")] == "not_confirmed"
    assert res[("G2", "other")] == "forward_only" and res[("G2", "pooled")] == "fail"
    assert ("G1s", "pooled") not in res and [c["group"] for c in d["candidates"]] == ["trend"]


def test_report_renders_without_money():
    T, cells = _synthetic(0.03)
    h = GT.evaluate(T, "history", cells, money=False, n_flip=10)
    text = GT.report_ko({"history": h})
    assert "장세 문지기 시험 결과" in text and "G1" in text


def test_label_codes_read_the_signal_bar():
    Y = GT.RG.Y
    M15 = GT.RG.M15
    t0 = GT.ms("2026-10-05")
    st = {"close": t0 + M15 * np.arange(1, 5), "code": np.array([Y.TREND, Y.RANGE, Y.SHOCK, Y.UNKNOWN], np.int8),
          "ts15": t0 + M15 * np.arange(4), "vol": np.array([2, 0, 1, 9], np.int8),
          "day": np.array([t0 // GT.DAY - 1]), "above": np.array([1.0])}
    reg, vol = GT.label_codes(t0 + M15 * np.array([1, 2, 3, 4]), st)
    assert [GT.REGIME[c] for c in reg] == ["추세장", "횡보장", "급변장", "모름"]
    assert [GT.VOL[c] for c in vol] == ["작음", "보통", "모름", "모름"]


def test_load_table_refuses_another_window(tmp_path):
    out = str(tmp_path)
    for tf in GT.R.TFS:
        for sym in GT.R.SYMBOLS:
            p = GT.part_path(out, "forward", tf, sym)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            T = {k: np.zeros(2, dt) for k, dt in GT.DTYPES.items()}
            np.savez(p, open_at_end=np.array([1, 0]), seconds=0.0, lo_ms=10, hi_ms=20, regime=np.ones(2, np.int8),
                     vol=np.ones(2, np.int8), **T)
    T = GT.load_table(out, "forward", 10, 20)
    assert len(T["x0"]) == 48 and T["open_at_end"] == [24, 0]
    try:
        GT.load_table(out, "forward", 10, 21)
    except SystemExit as exc:
        assert "another window" in str(exc)
    else:
        raise AssertionError("a part of another window was accepted")


def test_within_p_is_the_excess_over_the_coin_flip_average():
    # the observed value equals the gate's difference minus the mean of the coin-flip draws
    rng = np.random.default_rng(11)
    n = 6000
    cell = rng.integers(0, 4, n)
    block = np.sort(rng.integers(0, 120, n))
    allowed = rng.random(n) < np.array([0.2, 0.5, 0.7, 0.4])[cell]
    x = rng.normal(0, 0.02, n) + np.array([-0.01, 0.0, 0.01, 0.005])[cell] + 0.004 * allowed
    p, ex = GT.boot_within_p(block, cell, x, allowed, 400, 3)
    lines = np.ones((1, 4), bool)
    fl = GT.flip_control(cell, x, {"G": ~allowed}, lines, 4000, 5)["G"][:, 0]
    diff = x[allowed].mean() - x[~allowed].mean()
    assert abs(ex - (diff - fl.mean())) < 4 * fl.std() / np.sqrt(len(fl)) + 1e-12
    assert p < 0.05
    assert GT.boot_within_p(block, cell, x, np.ones(n, bool), 100, 3) == (None, None)


def test_within_p_refuses_a_mix_effect_with_clustered_luck():
    # no timing skill: the gate blocks half of the worse cell by a day-long state, and that cell's outcomes share a
    # common shock per day which happens to be one null standard deviation better on the gate's days. The plain
    # difference passes (the mix) and so does the coin-flip control (its draws are not clustered); condition 5 does not.
    rng = np.random.default_rng(12)
    days, per = 400, 200
    block = np.repeat(np.arange(days), per)
    cell = np.tile(np.r_[np.zeros(per // 2, int), np.ones(per // 2, int)], days)
    state = rng.random(days) < 0.5                                  # the gate's state, constant over a day
    luck = rng.normal(0, 0.008, days)
    sd_null = 0.008 * np.sqrt(1 / state.sum() + 1 / (~state).sum())
    luck[state] += sd_null - (luck[state].mean() - luck[~state].mean())
    x = rng.normal(0, 0.01, len(block)) + np.where(cell == 1, -0.006 + luck[block], 0.0)
    allowed = np.where(cell == 0, True, state[block])               # cell 0 always allowed, cell 1 by state
    p2 = GT.boot_diff_p(block, x, allowed, 1000, 1)
    fl = GT.flip_control(cell, x, {"G": ~allowed}, np.ones((1, 2), bool), 300, 2)["G"][:, 0]
    diff = x[allowed].mean() - x[~allowed].mean()
    cp = (1 + (fl >= diff).sum()) / (len(fl) + 1)
    p5, _ex = GT.boot_within_p(block, cell, x, allowed, 1000, 1)
    assert p2 < 0.05 and cp < 0.05                                  # conditions 2 and 4 alone would pass it
    assert p5 > 0.05                                                # condition 5 does not


def test_pin_must_list_exactly_the_pinned_files(tmp_path):
    pin = tmp_path / "pin.sha256"
    lines = [f"{GT.R._sha(os.path.join(GT.HERE, f))}  {f}" for f in GT.PINNED]
    pin.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert GT.pin_problems(str(pin)) == []
    pin.write_text("\n".join(lines[:3]) + "\n", encoding="utf-8")   # the three own files only: refused
    assert any("exactly" in b for b in GT.pin_problems(str(pin)))
    pin.write_text("\n".join(lines[:-1] + ["0" * 64 + "  " + GT.PINNED[-1]]) + "\n", encoding="utf-8")
    assert any(GT.PINNED[-1] in b for b in GT.pin_problems(str(pin)))
    assert GT.pin_problems(str(tmp_path / "none")) and "missing" in GT.pin_problems(str(tmp_path / "none"))[0]
