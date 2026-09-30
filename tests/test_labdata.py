"""The lab cache builder (paperbot/agents/labdata.py): research builders pointed at the server
folder, and the digest check against the research caches. Nothing touches the network."""

import json
import os
import re
import sys

import numpy as np
import pytest

from paperbot.agents import labdata as LD


def test_reference_lists_every_lab_file():
    ref = LD.reference()
    for src in LD.SOURCES:
        assert set(ref[src]) == {f"{tf}_{c}" for tf in LD.TFS for c in LD.COINS}
        for row in ref[src].values():
            assert re.fullmatch(r"[0-9a-f]{64}", row["digest"]) and row["bars"] > 0
    # five and a half years of 5m bars in periods 1-2, about a year and a half in period 3
    assert ref["main"]["5m_BTCUSD"]["bars"] > 550_000 and 100_000 < ref["pre2021"]["5m_BTCUSD"]["bars"] < 250_000


def test_digest_is_the_research_digest():
    sys.path.insert(0, LD.ENTRY_STUDY)
    import final_signals as FS
    arrs = {"ts": np.arange(5, dtype=np.int64), "c": np.linspace(1, 2, 5), "s__X": np.array([0, 1, 0, -1, 0], np.int8)}
    assert LD.content_digest(arrs) == FS.content_digest(arrs)


def _write(d, tf, coin, seed):
    os.makedirs(d, exist_ok=True)
    rng = np.random.default_rng(seed)
    arrs = {"ts": np.arange(50, dtype=np.int64) * 300_000_000_000, "c": rng.normal(100, 1, 50),
            "s__AAA": rng.integers(-1, 2, 50).astype(np.int8)}
    np.savez_compressed(os.path.join(d, f"sig_{tf}_{coin}.npz"), **arrs)
    return {"digest": LD.content_digest(arrs), "bars": 50}


def _fake_lab(out):
    p = LD.paths(out)
    ref = {"main": {}, "pre2021": {}}
    for k, src in enumerate(LD.SOURCES):
        for i, tf in enumerate(LD.TFS):
            for j, c in enumerate(LD.COINS):
                ref[src][f"{tf}_{c}"] = _write(p[src], tf, c, 100 * k + 10 * i + j)
    return ref


def test_check_finds_identical_missing_and_changed_files(tmp_path, capsys):
    out = str(tmp_path / "lab")
    ref = _fake_lab(out)
    res = LD.check(out, ref)
    assert res["all_identical"] and len(res["files"]) == 60
    assert LD._report(res) == 0 and "60/60 files identical" in capsys.readouterr().out
    with open(os.path.join(out, LD.MANIFEST)) as fh:
        assert json.load(fh)["all_identical"] is True

    os.remove(os.path.join(out, "pre2021", "sig_1h_SOLUSD.npz"))
    _write(out, "4h", "DOGEUSD", 999)                       # rebuilt from other data
    res = LD.check(out, ref)
    assert res["missing"] == ["pre2021 1h_SOLUSD"] and res["differ"] == ["main 4h_DOGEUSD"]
    assert not res["all_identical"] and LD._report(res) == 1
    assert res["files"]["main/4h_DOGEUSD"]["status"] == "differs"
    # only the sources asked for
    assert LD.check(out, ref, sources=("main",))["missing"] == []


def test_the_builder_is_pointed_at_the_lab_folder_not_the_repository(tmp_path, monkeypatch):
    for k in ("BINANCE_DIR", "BINANCE_SIGNALS", "BINANCE_REPORTS"):
        monkeypatch.setenv(k, "unset")                         # restored after the test
    out = str(tmp_path / "lab")
    B = LD.load_builder(out, procs=1)
    p = LD.paths(out)
    assert (B.BASE, B.SIGNALS, B.OUT) == (p["work"], p["main"], p["reports"])
    assert B.RAW.startswith(p["work"]) and B.BARS.startswith(p["work"]) and B.MANIFEST.startswith(p["work"])
    assert B.PROCS == 1 and B.TFS[:5] == ("5m", "15m", "30m", "1h", "4h")
    assert B.COINS == LD.COINS
    FS = LD.load_final_signals(out)
    assert FS.OUT == p["reports"] and FS.PRE2021 == LD.PRE2021_BARS and os.path.isdir(LD.PRE2021_BARS)


class _FakeBuilder:
    def __init__(self, calls, failed=()):
        self.calls, self.failed = calls, list(failed)

    def download(self, refresh_404=False):
        self.calls.append(("download", refresh_404))
        return {"failed": self.failed}

    def assemble(self, force=False):
        self.calls.append(("assemble", force))

    def signals(self, force=False):
        self.calls.append(("signals", force))


def test_build_runs_the_research_steps_in_order_then_checks(tmp_path, monkeypatch):
    out = str(tmp_path / "lab")
    ref = _fake_lab(out)
    calls = []

    class FS:
        @staticmethod
        def build(d, procs, data_dir):
            calls.append(("pre2021", d, procs, data_dir))

    monkeypatch.setattr(LD, "load_builder", lambda o, procs: _FakeBuilder(calls))
    monkeypatch.setattr(LD, "load_final_signals", lambda o: FS)
    monkeypatch.setattr(LD, "reference", lambda path=LD.REFERENCE: ref)
    res = LD.build(out, procs=3, refresh_404=True)
    assert [c[0] for c in calls] == ["download", "assemble", "signals", "pre2021"]
    assert calls[0] == ("download", True) and calls[3][1:] == (os.path.join(os.path.abspath(out), "pre2021"), 3, LD.PRE2021_BARS)
    assert res["all_identical"] and set(res["steps"]) == {"download_s", "assemble_s", "signals_s", "pre2021_s"}

    calls.clear()
    assert LD.build(out, only="pre2021")["all_identical"] and [c[0] for c in calls] == ["pre2021"]
    calls.clear()
    res = LD.build(out, only="main")
    assert [c[0] for c in calls] == ["download", "assemble", "signals"] and len(res["files"]) == 30

    monkeypatch.setattr(LD, "load_builder", lambda o, procs: _FakeBuilder(calls, failed=[{"rel": "x"}]))
    with pytest.raises(SystemExit, match="download failed"):
        LD.build(out, only="main")


def test_cli(tmp_path, monkeypatch, capsys):
    out = str(tmp_path / "lab")
    ref = _fake_lab(out)
    monkeypatch.setattr(LD, "reference", lambda path=LD.REFERENCE: ref)
    assert LD.main(["check", "--out", out]) == 0
    with pytest.raises(SystemExit):
        LD.main(["build", "--out", out, "--only", "nope"])


def test_the_lab_reports_whether_its_data_matches_the_research(tmp_path):
    from paperbot.agents import labtests as LT
    out = str(tmp_path / "lab")
    ref = _fake_lab(out)
    d = LT.LabData(out)
    assert d.matches_research() is None                     # never checked
    LD.check(out, ref)
    assert d.matches_research() is True
    _write(out, "5m", "BTCUSD", 12345)
    LD.check(out, ref)
    assert d.matches_research() is False
    assert LT.LabData(None).matches_research() is None
