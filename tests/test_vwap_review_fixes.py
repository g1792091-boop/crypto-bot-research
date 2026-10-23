"""Review fixes of 10-23 for the 'VWAP 개선판' site work: the site's second paper bot stays the old -35 % bot until the VWAP
bot's file is there (no variable set), and the VWAP executor's break-even win rate is on net ROE (dollars would move with
the account size)."""
from __future__ import annotations

import pytest

from paperbot.dash.more import liveinsight as I
from paperbot.dash.more import livebots as L


def test_second_paper_is_the_vwap_file_else_the_old_one_until_it_is_there(tmp_path, monkeypatch):
    vwap, old = tmp_path / "vwap.db", tmp_path / "live15-mexc.db"
    monkeypatch.setitem(L.ENV, "paper2", ("PAPERBOT_LIVE_PAPER2_DB", str(vwap)))
    monkeypatch.setattr(L, "LEGACY_PAPER2", str(old))
    assert L.paths({})["paper2"] == str(vwap)                 # neither file: the default (shown only once it exists)
    old.write_bytes(b"")
    assert L.paths({})["paper2"] == str(old)                  # before the VWAP bot: the page as it was
    vwap.write_bytes(b"")
    assert L.paths({})["paper2"] == str(vwap)                 # the VWAP bot's file wins
    named = str(tmp_path / "x.db")
    vwap.unlink()
    assert L.paths({"PAPERBOT_LIVE_PAPER2_DB": named})["paper2"] == named      # a variable always wins


def test_breakeven_is_on_net_roe_and_a_flat_trade_is_neither():
    # three wins of +10 % and one loss of -40 %: 40 / (10 + 40) = 80 %, whatever the dollars were
    assert I.breakeven_win([0.10, 0.10, 0.10, -0.40]) == pytest.approx(0.8)
    assert I.breakeven_win([0.10, 0.0, -0.40, None]) == pytest.approx(0.8)
    assert I.breakeven_win([0.10, 0.20]) is None and I.breakeven_win([]) is None
