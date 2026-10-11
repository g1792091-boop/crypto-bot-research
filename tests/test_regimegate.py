"""research/regimegate/gate.py (PREREG_REGIMEGATE.md): the style map, the gates, the block bootstrap, the coin-flip
control, the verdict lines and the decision, on hand-made numbers only (no market data). Then the nightly look
(paperbot/regimegate.py) on synthetic bars: its labels equal research/fullgrid/regimes.py, a night split in pieces gives
the same signals and trades as one night, the window's edges, paper3.db untouched, the units and the installer."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

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


def test_style_map_has_each_of_the_80_ids_once():
    st = GT.style()
    core, ds = set(st["core"]), set(st["ds"])
    assert not core & ds and len(core) == 36 and len(ds) == 44
    assert len(GT.all_cells()) == 315
    assert sorted({(k, n) for k, n, _tf in GT.all_cells()}) == sorted([("core", n) for n in core] + [("ds", n) for n in ds])


def test_flip_control_is_seeded():
    rng = np.random.default_rng(8)
    n = 3000
    cell = np.sort(rng.integers(0, 6, n))
    x = rng.normal(0, 0.02, n)
    blocked = {"G1": rng.random(n) < 0.6, "G2": rng.random(n) < 0.3}
    lines = np.array([np.ones(6, bool), np.arange(6) < 3])
    a = GT.flip_control(cell, x, blocked, lines, 200, GT.R._seed("regimegate|flip", "forward", "ladder|2"))
    b = GT.flip_control(cell, x, blocked, lines, 200, GT.R._seed("regimegate|flip", "forward", "ladder|2"))
    c = GT.flip_control(cell, x, blocked, lines, 200, GT.R._seed("regimegate|flip", "history", "ladder|2"))
    for g in blocked:
        assert np.array_equal(a[g], b[g]) and not np.array_equal(a[g], c[g])


# ====================================================================== the nightly look (paperbot/regimegate.py)
MIN = 60_000
DAY = 86_400_000


def _rgj():
    from paperbot import regimegate as RGJ
    return RGJ


def _synth1m(days: int, seed: int, p0: float, start: int) -> dict:
    """1m bars with drifting and calm / wild stretches (three days each), so every market state appears."""
    n = days * 1440
    rng = np.random.default_rng(seed)
    blk = 3 * 1440
    nb = n // blk + 1
    vol = np.repeat(rng.choice([0.0004, 0.0009, 0.0025], nb), blk)[:n]
    drift = np.repeat(rng.choice([-0.0001, 0.0, 0.0001], nb), blk)[:n]
    c = p0 * np.exp(np.cumsum(drift + vol * rng.standard_normal(n)))
    o = np.r_[p0, c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 1, n)) * vol * 0.5)
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 1, n)) * vol * 0.5)
    v = rng.lognormal(5, 0.5, n)
    ts = start + MIN * np.arange(n, dtype=np.int64)
    return {"ts": ts, "fund": np.zeros(n), "o": o, "h": h, "l": lo, "c": c, "v": v, "mo": o, "mh": h, "ml": lo,
            "mc": c}


def _to5m(z: dict) -> tuple:
    n5 = len(z["ts"]) // 5

    def g(x, f):
        return f(x[:n5 * 5].reshape(n5, 5), axis=1)
    return (z["ts"][::5][:n5], z["o"][::5][:n5], g(z["h"], np.max), g(z["l"], np.min), z["c"][4::5][:n5],
            g(z["v"], np.sum))


def test_labels_equal_regimes_py_on_a_synthetic_series(tmp_path, monkeypatch):
    """coin_states_from_frames on the live frames (from 5m bars) == research/fullgrid/regimes.py coin_states on the
    full grid's frames (from the same series' 1m bars), and the label lookup reads them the same way."""
    from paperbot import paramshadow as PS
    from paperbot import sweepsig
    RGJ = _rgj()
    monkeypatch.setattr(GT.R, "FRAME_DIR", [None])
    z = _synth1m(200, 1, 100.0, GT.ms("2026-03-20"))
    os.makedirs(tmp_path / "1m")
    np.savez(tmp_path / "1m" / "BTCUSDT.npz", **z)
    lib = sweepsig.lib()
    cols = _to5m(z)
    seen = set()
    for tf in ("15m", "1h", "4h"):
        want = GT.RG.coin_states(str(tmp_path), "BTCUSDT", tf)
        frames = {t: PS.chart_frame(lib, cols, t) for t in (tf, "15m", "4h")}
        got = RGJ.coin_states_from_frames(frames, tf)
        for k in want:
            assert np.array_equal(want[k], got[k], equal_nan=True), (tf, k)
        closes = want["close"][-2000:]
        assert [list(a) for a in GT.label_codes(closes, want)] == [list(a) for a in GT.label_codes(closes, got)]
        seen |= set(np.unique(want["code"]).tolist())
    assert {GT.RG.Y.TREND, GT.RG.Y.RANGE, GT.RG.Y.NORMAL, GT.RG.Y.UNKNOWN} <= seen


def test_labels_never_look_ahead():
    """A label at a bar is the same whether the frames end there or two weeks later (the night it is computed on
    never changes it)."""
    from paperbot import paramshadow as PS
    from paperbot import sweepsig
    RGJ = _rgj()
    lib = sweepsig.lib()
    z = _synth1m(200, 2, 50.0, GT.ms("2026-03-20"))
    cols = _to5m(z)
    cut = int(np.searchsorted(cols[0], cols[0][-1] - 14 * DAY))
    short = tuple(a[:cut] for a in cols)
    for tf in ("15m", "4h"):
        full = RGJ.coin_states_from_frames({t: PS.chart_frame(lib, cols, t) for t in (tf, "15m", "4h")}, tf)
        part = RGJ.coin_states_from_frames({t: PS.chart_frame(lib, short, t) for t in (tf, "15m", "4h")}, tf)
        n = len(part["close"])
        assert np.array_equal(full["close"][:n], part["close"]) and np.array_equal(full["code"][:n], part["code"])
        m = len(part["ts15"])
        assert np.array_equal(full["vol"][:m], part["vol"])


D0 = 1_791_158_400_000                        # 2026-10-05 00:00 UTC
STRATS = ["S2_ST_ROC", "N17_KC_RSI", "S3_CMO_SANDWICH"]   # trend, reversion, other (style map)
TFS = ("15m", "1h")
SYMS = ("BTCUSDT", "ETHUSDT")
HIST_DAYS = 200                               # > regime5y's 180 days, so the labels are known in the window
WIN = (GT.FWD_FROM, D0 + 4 * DAY)             # the registered start; a short end for the test


def _synth5(seed: int, p0: float, days: int = HIST_DAYS + 7):
    z = _synth1m(days, seed, p0, D0 - HIST_DAYS * DAY)
    return tuple(np.asarray(a) for a in _to5m(z))


@pytest.fixture(scope="module")
def fdata():
    return {s: _synth5(i + 3, p) for i, (s, p) in enumerate(zip(SYMS, (60000.0, 2500.0)))}


def _steps_from(data):
    """1m steps made from the 5m bars (each 5m bar split into five minutes; funding every 8 h)."""
    from paperbot.models import Bar

    def fetch(rest, symbols, start, end):
        out = []
        cols = {s: tuple(a[(data[s][0] >= start) & (data[s][0] < end)] for a in data[s]) for s in symbols}
        n = len(cols[symbols[0]][0])
        for j in range(n):
            for q in range(5):
                t0 = int(cols[symbols[0]][0][j]) + q * MIN
                bars = {}
                for s in symbols:
                    _ts, o, h, lo, c, _v = cols[s]
                    oo = o[j] + (c[j] - o[j]) * q / 5
                    cc = o[j] + (c[j] - o[j]) * (q + 1) / 5
                    hh = max(oo, cc) + (h[j] - max(o[j], c[j])) * (1.0 if q == 2 else 0.3)
                    ll = min(oo, cc) - (min(o[j], c[j]) - lo[j]) * (1.0 if q == 3 else 0.3)
                    bars[s] = Bar(s, t0, t0 + MIN - 1, oo, hh, ll, cc, oo, hh, ll, cc)
                fund = {s: 0.0001 for s in symbols} if t0 % (8 * 3_600_000) == 0 else {}
                out.append((t0, bars, fund))
        return out
    return fetch


def _brackets():
    from paperbot.margin import BracketTier, Brackets
    return {s: Brackets([BracketTier(300_000, 75, 0.005, 0.0), BracketTier(800_000, 50, 0.01, 1500.0),
                         BracketTier(3_000_000, 20, 0.025, 13500.0)]) for s in SYMS}


def _paper_db(path) -> str:
    from paperbot import sweepsig
    from paperbot.sigservice import strategy_names
    from paperbot.store3 import Store3
    st = Store3(str(path))
    for n in strategy_names(sweepsig.lib()):
        for tf in ("15m", "30m", "1h", "4h"):
            st.add_account(f"{n}@{tf}", n, tf, "strategy", WIN[0] + 30_000, "paper-v4")
    st.put_state("run", WIN[0], {"taker_fee": 0.0005})
    st.commit()
    st.close()
    return str(path)


def _frun(out, data, now, max_days=30, db=None):
    from paperbot import paramshadow as PS
    return _rgj().run(db, str(out), PS.FrameSource(data), None, _brackets(), {s: {} for s in SYMS}, now,
                      max_days=max_days, strategies=STRATS, tfs=TFS, symbols=SYMS, fetch_steps=_steps_from(data),
                      log=lambda s: None, win=WIN, live_root="", n_flip=20, brackets_doc=b"test")


def _signals(out):
    conn = sqlite3.connect(os.path.join(str(out), "regimegate.db"))
    rows = conn.execute("SELECT id, strategy, tf, symbol, side, bar_close, class, regime, vol, status, entry_time, "
                        "exit_time, exit_reason, leverage, tier, round(pnl, 6) FROM signals ORDER BY id").fetchall()
    conn.close()
    return rows


def test_forward_look_in_pieces_equals_one_night(tmp_path, fdata):
    now = D0 + 6 * DAY + 3_600_000                    # yesterday = 10-10; the test window's last day is 10-09
    one = _frun(tmp_path / "one", fdata, now)
    assert one["status"] == "done" and one["through_day"] == "2026-10-09" and one["days"] == 5
    out = tmp_path / "parts"
    s1 = _frun(out, fdata, now, max_days=2)
    assert s1["status"] == "filling" and s1["days_remaining"] == 3 and "채우는 중" in s1["line_ko"]
    _frun(out, fdata, now, max_days=2)
    s3 = _frun(out, fdata, now, max_days=2)
    assert s3["status"] == "done" and s3["days_remaining"] == 0
    rows = _signals(tmp_path / "one")
    assert rows == _signals(out)
    assert json.dumps(one["evaluation"], sort_keys=True) == json.dumps(s3["evaluation"], sort_keys=True)
    again = _frun(out, fdata, now, max_days=2)        # nothing left: no change
    assert _signals(out) == rows and again["days"] == 5
    # the window: bars closing in [10-05 18:35, 10-09 00:00) only; the day 10-09 only finishes open trades
    assert rows and min(r[5] for r in rows) >= WIN[0] and max(r[5] for r in rows) < WIN[1]
    st = {r[9] for r in rows}
    assert st <= {"closed", "open", "not_sized"} and "closed" in st
    assert {r[6] for r in rows} == {GT.style_class("core", n) for n in STRATS}
    closed = [r for r in rows if r[9] == "closed"]
    assert all(r[10] >= r[5] and r[11] >= r[10] and r[15] is not None for r in closed)   # fills at the next open
    known = [r for r in rows if r[7] > 0 and r[8] > 0]
    assert known and len({r[7] for r in known}) >= 2      # the labels are filled in (history before the window)
    ev = one["evaluation"]
    assert one["counts"]["closed"] == ev["signals"] and ev["used"] == ev["signals"] - ev["unknown_state"]
    assert ev["open_at_end"] == one["counts"]["open"]
    v = {(ln["gate"], ln["group"]) for ln in ev["lines"] if ln["role"] == "verdict"}
    assert {("G1", "pooled"), ("G2", "trend"), ("G1s", "pooled")} <= v
    assert one["read"] == "ladder|2" and one["look"] is True and one["verdict"] is False
    assert all("mean_allowed" in ln for ln in ev["lines"])               # the 36 only: money shown
    assert "판정 아님" in one["line_ko"] and "G1 들임" in one["line_ko"]
    text = _rgj().show_text(json.loads((tmp_path / "one" / "last.json").read_text(encoding="utf-8")))
    assert text.count("\n") == 8 and "G2 되돌림형" in text


def test_forward_look_x_is_the_trade_over_5000(tmp_path, fdata):
    now = D0 + 3 * DAY + 3_600_000
    s = _frun(tmp_path, fdata, now)
    assert s["status"] == "ok" and s["through_day"] == "2026-10-07"
    T, counts = _rgj().signal_table(sqlite3.connect(str(tmp_path / "regimegate.db")), GT, 5000.0)
    rows = [r for r in _signals(tmp_path) if r[9] == "closed"]
    assert len(T["x0"]) == len(rows) == counts["closed"] and np.isnan(T["x1"]).all()
    assert sorted(np.round(T["x0"] * 5000.0, 6).tolist()) == sorted(r[15] for r in rows)
    cells = GT.all_cells()
    assert {cells[c][1] for c in T["cell"]} <= set(STRATS) and {cells[c][0] for c in T["cell"]} == {"core"}


def test_forward_look_starts_over_on_another_window_and_keeps_paper3(tmp_path, fdata):
    now = D0 + 3 * DAY + 3_600_000
    db = _paper_db(tmp_path / "paper3.db")
    before = hashlib.sha256(Path(db).read_bytes()).hexdigest()
    s = _frun(tmp_path / "out", fdata, now, db=db)
    assert hashlib.sha256(Path(db).read_bytes()).hexdigest() == before
    assert s["parity"]["real"] == 0 and s["parity"]["share"] is None
    assert s["run_start_ms"] == WIN[0] + 30_000 and not any("다름" in n for n in s["notes"])
    conn = sqlite3.connect(str(tmp_path / "out" / "regimegate.db"))
    conn.execute("UPDATE meta SET data = json_set(data, '$.fingerprint', 'old') WHERE k = 'run'")
    conn.commit()
    conn.close()
    again = _frun(tmp_path / "out", fdata, now, db=db)                  # other code: rebuilt from the window start
    assert again["days"] == s["days"] and _signals(tmp_path / "out")


def test_forward_look_waits_before_the_window(tmp_path, fdata):
    s = _frun(tmp_path, fdata, D0 + 3_600_000)
    assert s["status"] == "waiting" and s["through_day"] is None and s["counts"]["signals"] == 0
    assert "아직" in s["line_ko"]
    assert _rgj().read_summary(str(tmp_path)) == s["line_ko"]


def test_forward_look_window_is_the_registered_one():
    RGJ = _rgj()
    assert RGJ.window() == (GT.ms("2026-10-05 18:35"), GT.ms("2026-10-30"))
    br, specs = RGJ.exchange_tables()
    assert sorted(br) == sorted(specs) == sorted(GT.R.SYMBOLS)
    assert all(v["qty_step"] > 0 and v["min_notional"] > 0 for v in specs.values())
    assert "PREREG_REGIMEGATE" in RGJ.error_ko("PREREG_REGIMEGATE.sha256 missing: pin the files before running")
    assert "가격 자료" in RGJ.error_ko("5m klines of BTCUSDT unavailable")
    assert "정의 파일" in RGJ.error_ko("DEFS_BC.sha256 sha256 1 != pinned 2")


def test_forward_look_is_not_a_trading_file():
    from paperbot import runinfo
    for group in (runinfo.TRADING_FILES, runinfo.DS_FILES, runinfo.REEL_FILES, runinfo.EXTRA_FILES,
                  runinfo.SHARED_SIGNAL_FILES, runinfo.EXTRA_GATE_FILES):
        assert "paperbot/regimegate.py" not in group
    src = Path(ROOT, "paperbot", "regimegate.py").read_text(encoding="utf-8")
    assert "PS.connect_ro(paper_db)" in src                             # paper3.db: mode=ro, query_only
    for bad in ("submit_order", "place_order", "executor", "notify.send", "Store3("):
        assert bad not in src
    for rel in runinfo.TRADING_FILES:                                   # nothing on the trading path imports it
        if rel.endswith(".py"):
            assert "regimegate" not in Path(ROOT, rel).read_text(encoding="utf-8"), rel


def test_units_and_installer():
    d = Path(ROOT, "deploy", "regimegate")
    svc = (d / "paperbot-regimegate.service").read_text(encoding="utf-8")
    tim = (d / "paperbot-regimegate.timer").read_text(encoding="utf-8")
    inst = (d / "install_regimegate.sh").read_text(encoding="utf-8")
    assert "-m paperbot.regimegate run" in svc and "--out /var/lib/paperbot/regimegate" in svc
    assert "User=paperbot" in svc and "OnFailure=paperbot-failed@%n.service" in svc and "MemoryMax=" in svc
    ro = svc.split("ReadOnlyPaths=", 1)[1].split("\n", 1)[0].split()
    assert "ReadWritePaths=/var/lib/paperbot\n" in svc                 # as paramshadow: paper3.db's WAL is readable
    for p in ("-/var/lib/paperbot/paper3.db", "-/var/lib/paperbot/paramshadow", "/opt/paperbot-regimegate",
              "-/opt/crypto-bot-research"):
        assert p in ro, p
    assert "EnvironmentFile" not in svc and "-/etc/paperbot" in svc            # no key: public bars only
    assert "WorkingDirectory=/opt/paperbot-regimegate/app" in svc and "PYTHONPATH=/opt/paperbot-regimegate/app" in svc
    assert "OnCalendar=*-*-* 01:40:00 UTC" in tim                           # after paramshadow (01:00 UTC)
    for line in inst.splitlines():                                      # the rule bot's installer is only named
        if "install.sh" in line and "install_regimegate.sh" not in line:
            assert line.strip().startswith(("#", "echo")), line
    assert "paperbot.regimegate selfcheck" in inst and "enable --now paperbot-regimegate.timer" in inst
    tokens = set(inst.split("CODE_PATHS=", 1)[1].split("\n\n", 1)[0].replace('"', " ").replace("\\", " ").split())
    for rel in GT.PINNED + ("PREREG_REGIMEGATE.sha256",):            # every pinned file reaches the copy
        parts = os.path.normpath(os.path.join("research", "regimegate", rel)).split(os.sep)
        assert any("/".join(parts[:k]) in tokens for k in range(1, len(parts) + 1)), rel
