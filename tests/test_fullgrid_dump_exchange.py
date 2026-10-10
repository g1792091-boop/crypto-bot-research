"""research/fullgrid/dump_exchange.py with a fake exchange: the six coins' table, and the research-only extra coins as
best effort (a coin it cannot get never changes or stops the six coins' output)."""

from __future__ import annotations

import importlib.util
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("dump_exchange", os.path.join(ROOT, "research", "fullgrid",
                                                                             "dump_exchange.py"))
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)

SIX = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")


def _tiers():
    return [{"bracket": 1, "initialLeverage": 125, "notionalCap": 300000, "notionalFloor": 0, "maintMarginRatio": 0.004,
             "cum": 0.0, "notionalCoef": 1.0},
            {"bracket": 2, "initialLeverage": 100, "notionalCap": 800000, "notionalFloor": 300000,
             "maintMarginRatio": 0.005, "cum": 300.0, "notionalCoef": 1.0}]


class FakeRest:
    api_key = api_secret = "x"

    def __init__(self, listed, broken=()):
        self.listed, self.broken = listed, set(broken)

    def leverage_brackets(self):
        return [{"symbol": s, "brackets": _tiers()} for s in self.listed]

    def exchange_info(self, symbols):
        bad = set(symbols) - set(self.listed) | (set(symbols) & self.broken)
        if bad:
            raise RuntimeError(f"symbols not listed: {sorted(bad)}")
        return {s: {"qty_step": 0.001, "min_notional": 5.0, "tick_size": 0.1} for s in symbols}


def _run(monkeypatch, capsys, rest):
    import paperbot.live
    monkeypatch.setattr(paperbot.live, "_rest", lambda: rest)
    rc = D.main()
    out, err = capsys.readouterr()
    return rc, (json.loads(out) if out.strip() else None), err


def test_six_coins_and_all_extras(monkeypatch, capsys):
    rc, doc, err = _run(monkeypatch, capsys, FakeRest(SIX + D.EXTRA + ("FOOUSDT",)))
    assert rc == 0 and err == ""
    assert list(doc) == ["fetched_utc", "brackets", "specs", "extra"]
    assert [p["symbol"] for p in doc["brackets"]] == list(SIX)
    assert doc["brackets"][0]["brackets"][1] == {k: _tiers()[1][k] for k in D.KEEP}      # notionalCoef dropped
    assert list(doc["extra"]["brackets"]) == list(D.EXTRA)
    assert doc["extra"]["brackets"]["XRPUSDT"][1] == [2, 100, 800000, 300000, 0.005, 300.0]
    assert doc["extra"]["specs"]["DOTUSDT"] == {"qty_step": 0.001, "min_notional": 5.0}


def test_missing_extras_leave_the_six_coins_unchanged(monkeypatch, capsys):
    rc, full, _ = _run(monkeypatch, capsys, FakeRest(SIX + D.EXTRA))
    rc2, part, err = _run(monkeypatch, capsys, FakeRest(SIX + D.EXTRA[2:], broken=("LINKUSDT",)))
    assert rc == rc2 == 0
    assert {k: part[k] for k in ("brackets", "specs")} == {k: full[k] for k in ("brackets", "specs")}
    assert list(part["extra"]["brackets"]) == ["ADAUSDT", "AVAXUSDT", "DOTUSDT"]
    assert "XRPUSDT" in err and "LINKUSDT" in err
    rc3, none, _ = _run(monkeypatch, capsys, FakeRest(SIX))
    assert rc3 == 0 and list(none) == ["fetched_utc", "brackets", "specs"]


def test_extra_failure_never_stops_the_output(monkeypatch, capsys):
    monkeypatch.setattr(D, "extra_part", lambda rest, payload: 1 / 0)
    rc, doc, err = _run(monkeypatch, capsys, FakeRest(SIX + D.EXTRA))
    assert rc == 0 and list(doc) == ["fetched_utc", "brackets", "specs"] and "ZeroDivisionError" in err


def test_a_missing_core_coin_still_stops(monkeypatch, capsys):
    r = FakeRest(SIX[:5] + D.EXTRA)                         # no BCH brackets, order-size rules for all
    r.exchange_info = lambda symbols: {s: {"qty_step": 0.001, "min_notional": 5.0} for s in symbols}
    rc, doc, err = _run(monkeypatch, capsys, r)
    assert rc == 2 and doc is None and "BCHUSDT" in err


def test_dump_needs_a_key(monkeypatch, capsys):
    r = FakeRest(SIX)
    r.api_key = None
    rc, doc, err = _run(monkeypatch, capsys, r)
    assert rc == 2 and doc is None
