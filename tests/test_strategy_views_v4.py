"""The paper v4 chart views in paperbot/strategy_views.py: a registry (strategy_view_defs/v4_views.py) maps the 44
DeepSeek ids (lib_c.DEFS) and REEL_H1 to their modules, imported on first use; a module not written yet or broken is
skipped, never an error; ``views()`` stays the 36 (NAMES); ``render`` passes the symbol on and BTC's bars to F14."""

import importlib.util
import os
import sys
import types

import numpy as np
import pandas as pd
import pytest

import paperbot.strategy_views as sv
from paperbot.config import DS200_IDS, REEL_NAME
from paperbot.strategy_view_defs import NAMES
from paperbot.strategy_view_defs import v4_views as V4

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def fresh(monkeypatch):
    """strategy_views with empty caches (restored afterwards)."""
    monkeypatch.setattr(sv, "_VIEWS", None)
    monkeypatch.setattr(sv, "_V4_REGISTRY", None)
    monkeypatch.setattr(sv, "_V4", {})
    monkeypatch.setattr(sv, "_V4_BROKEN", {})
    return sv


def bars(n=300, seed=3, freq="1h"):
    r = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(r.normal(0, 0.004, n)))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"ts": pd.date_range("2026-01-01", periods=n, freq=freq, tz="UTC"), "open": o,
                         "high": np.maximum(o, c) * 1.002, "low": np.minimum(o, c) * 0.998, "close": c,
                         "volume": r.uniform(1, 10, n)})


def test_registry_is_lib_c_defs_plus_the_reel():
    path = os.path.join(REPO, "research", "deepseek200", "lib_c.py")
    from paperbot.entry_marks import _contained
    before = list(sys.path)
    with _contained():                                   # lib_c changes sys.path and the warnings at import
        spec = importlib.util.spec_from_file_location("_test_v4_views_lib_c", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    assert sys.path == before
    ids = tuple(d[0] for d in mod.DEFS)
    assert len(ids) == 44 and V4.lib_c_ids() == ids == DS200_IDS == V4.DS_IDS
    assert list(V4.V4_VIEWS) == list(ids) + [REEL_NAME]
    assert V4.V4_VIEWS["F9_FVG"] == "DS_F9_FVG" and V4.V4_VIEWS["REEL_H1"] == "REEL_H1"
    assert not set(V4.V4_VIEWS) & set(NAMES)


def test_lib_c_ids_is_read_without_running_the_file(tmp_path):
    p = tmp_path / "lib_c.py"
    p.write_text("import sys\nsys.exit('never run')\n_A = ('15m',)\nDEFS = [\n  ('F1_X', 'F1', _A), ('F2_Y', 'F2', _A),\n]\n")
    assert V4.lib_c_ids(str(p)) == ("F1_X", "F2_Y")
    assert V4.lib_c_ids(str(tmp_path / "none.py")) is None
    p.write_text("DEFS = [(name, 'F1', ())]\n")
    assert V4.lib_c_ids(str(p)) is None                 # not a literal id: fall back to config


def test_views_stays_the_36_and_loads_the_registry(fresh):
    vs = sv.views()
    assert set(vs) == set(NAMES) and len(vs) == 36
    assert sv._V4_REGISTRY == V4.V4_VIEWS               # loaded with the 36; the modules wait for their first use
    assert sv._V4 == {}
    allv = sv.all_views()
    assert set(vs) <= set(allv) and set(allv) - set(vs) <= set(V4.V4_VIEWS)
    assert set(allv) - set(vs) == set(V4.V4_VIEWS) - set(sv.v4_missing())


def test_a_module_not_written_yet_is_skipped(fresh, monkeypatch):
    monkeypatch.setattr(sv, "_V4_REGISTRY", {"ZZ_NOT_YET": "DS_ZZ_NOT_YET"})
    monkeypatch.setattr(sv, "_VIEWS", {})
    assert sv.v4_view("ZZ_NOT_YET") is None and not sv.has_view("ZZ_NOT_YET")
    assert sv.v4_missing() == {"ZZ_NOT_YET": "DS_ZZ_NOT_YET.py not written yet"}
    assert sv.v4_views() == {} and sv.all_views() == {}
    with pytest.raises(KeyError):
        sv.render("ZZ_NOT_YET", bars(), "1h")


def test_a_broken_module_is_skipped_until_its_file_changes(fresh, monkeypatch, tmp_path):
    (tmp_path / "DS_ZZ_HALF.py").write_text("def view_DS_ZZ_HALF(df, tf):\n    return (\n")
    monkeypatch.setattr(sv, "DEFS_DIR", str(tmp_path))
    monkeypatch.setattr(sv, "_V4_REGISTRY", {"ZZ_HALF": "DS_ZZ_HALF"})
    calls = []
    good = types.SimpleNamespace(view_DS_ZZ_HALF=lambda df, tf: {"long": [("항상", np.ones(len(df), bool))]})

    def fake_import(name):
        calls.append(name)
        if len(calls) == 1:
            raise SyntaxError("'(' was never closed")
        return good
    monkeypatch.setattr(sv.importlib, "import_module", fake_import)
    assert sv.v4_view("ZZ_HALF") is None
    assert sv.v4_missing()["ZZ_HALF"].startswith("SyntaxError")
    assert sv.v4_view("ZZ_HALF") is None and len(calls) == 1      # not imported again while the file is the same
    st = os.stat(tmp_path / "DS_ZZ_HALF.py")
    os.utime(tmp_path / "DS_ZZ_HALF.py", ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))     # the other team saved it
    assert sv.v4_view("ZZ_HALF") is good.view_DS_ZZ_HALF and len(calls) == 2
    assert sv.v4_missing() == {} and sv.v4_view("ZZ_HALF") is good.view_DS_ZZ_HALF and len(calls) == 2


def test_registry_import_failure_is_not_fatal_and_not_cached(fresh, monkeypatch):
    real = sv.importlib.import_module
    monkeypatch.setitem(sys.modules, "paperbot.strategy_view_defs.v4_views", None)   # import fails
    assert sv.v4_registry() == {} and sv._V4_REGISTRY is None
    assert sv.v4_view("F9_FVG") is None
    monkeypatch.delitem(sys.modules, "paperbot.strategy_view_defs.v4_views")
    real("paperbot.strategy_view_defs.v4_views")
    assert sv.v4_registry() == V4.V4_VIEWS


def test_render_passes_the_symbol_and_gives_btc_only_to_a_view_that_takes_it(fresh, monkeypatch):
    seen = {}

    def plain(df, tf):
        seen["plain"] = dict(df.attrs)
        return {"long": [("x", np.ones(len(df), bool))], "short": []}

    def smt(df, tf, btc=None):
        seen["smt"] = (dict(df.attrs), btc)
        return {"long": [], "short": [("y", np.zeros(len(df), bool))]}
    monkeypatch.setattr(sv, "_VIEWS", {"P": plain})
    monkeypatch.setattr(sv, "_V4", {"S": smt})
    df, btc = bars(), bars(seed=4)
    df.attrs.update(symbol="ETHUSDT", btc=btc)
    sv.render("P", df, "1h")
    assert seen["plain"] == {"symbol": "ETHUSDT", "tf": "1h"}          # no frame left in attrs
    r = sv.render("S", df, "1h")
    attrs, got = seen["smt"]
    assert attrs == {"symbol": "ETHUSDT", "tf": "1h"} and got is btc and r["conditions"]["short"][0]["on"] is False
    sv.render("S", bars(), "4h", symbol="SOLUSDT", btc=btc)
    assert seen["smt"][0] == {"symbol": "SOLUSDT", "tf": "4h"} and seen["smt"][1] is btc
    sv.render("S", bars(), "4h")
    assert seen["smt"] == ({"tf": "4h"}, None)
    assert df.attrs["btc"] is btc                                        # the caller's frame is not changed


def test_the_written_v4_views_render_and_f14_reads_btc(fresh):
    sv.views()
    v4 = sv.v4_views()
    if not v4:
        pytest.skip("no v4 view module written yet")
    df = bars(700)
    for name in v4:
        r = sv.render(name, df, "1h", tail=100, symbol="ETHUSDT", btc=bars(700, seed=4))
        assert r["strategy"] == name and (r["conditions"]["long"] or r["conditions"]["short"]), name
        for o in r["overlays"]:
            assert all(np.isfinite(p["value"]) for p in o["data"] if "value" in p), name
    if "F14_SMT" in v4:
        with_btc = sv.render("F14_SMT", df, "1h", tail=100, symbol="ETHUSDT", btc=bars(700, seed=4))
        without = sv.render("F14_SMT", df, "1h", tail=100, symbol="ETHUSDT")
        n = lambda r: sum(len(s["data"]) for p in r["panes"] for s in p["series"])      # noqa: E731
        assert n(with_btc) > 0 == n(without)
        assert n(sv.render("F14_SMT", df, "1h", tail=100, symbol="BTCUSDT", btc=bars(700, seed=4))) == 0


def test_v4_lines_break_at_gaps_and_the_36_keep_their_shape():
    t = np.arange(10) * 3600
    vals = [np.nan, 1, 1, np.nan, np.nan, 2, 2, 2, np.nan, np.nan]
    assert sv._points(t, vals, 10) == [{"time": int(x), "value": float(v)} for x, v in zip(t, vals) if v == v]
    got = sv._points(t, vals, 10, breaks=True)
    assert got == [{"time": 3600, "value": 1.0}, {"time": 7200, "value": 1.0}, {"time": 10800},
                   {"time": 18000, "value": 2.0}, {"time": 21600, "value": 2.0}, {"time": 25200, "value": 2.0}]
    assert sv._points(t, [np.nan] * 10, 10, breaks=True) == []
    assert sv._is_step([5.0] * 12 + [6.0] * 12) and not sv._is_step(np.linspace(1, 2, 30))
    o = {"name": "x", "values": vals}
    assert set(sv._line(t, o, 10, v4=False)) == {"name", "data"}
    assert sv._line(t, o, 10, v4=True)["breaks"] is True
    j = sv._line(t, {**o, "join": True}, 10, v4=True)
    assert j["breaks"] is False and all("value" in p for p in j["data"])


def test_v4_render_marks_breaks_and_the_36_do_not(fresh):
    sv.views()
    v4 = sv.v4_views()
    if "F13_FVG_PD" not in v4:
        pytest.skip("F13_FVG_PD view not loaded")
    r = sv.render("F13_FVG_PD", bars(700), "1h", tail=300)
    assert all("breaks" in o and "step" in o for o in r["overlays"])
    first36 = next(iter(sv.views()))
    r36 = sv.render(first36, bars(700), "1h", tail=50)
    assert all(set(o) == {"name", "data"} for o in r36["overlays"])
