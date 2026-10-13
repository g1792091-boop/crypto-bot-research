"""The paper wallet every account of the league starts with: CANDLEAGUE_EQUITY (the owners' league: 1000), else the paper bot's 5000."""

from __future__ import annotations

import copy
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_candleague_rulex as TR  # noqa: E402
import test_candleague_user_ladder as TU  # noqa: E402
from candleague import exits as X  # noqa: E402
from candleague import rulex as RX  # noqa: E402
from candleague import runner as RN  # noqa: E402


def test_the_default_is_the_paper_bots_5000_and_the_environment_changes_it(monkeypatch):
    monkeypatch.delenv(X.EQUITY_ENV, raising=False)
    assert X.start_equity() == 5000.0 and X.settings_for("ladderU|2").initial_equity == 5000.0
    monkeypatch.setenv(X.EQUITY_ENV, "1000")
    assert X.start_equity() == 1000.0 and X.settings_for("ladderU|2").initial_equity == 1000.0 and X.settings_for("ladder|2").initial_equity == 1000.0
    monkeypatch.setenv(X.EQUITY_ENV, "  ")
    assert X.start_equity() == 5000.0                                              # empty = not set


@pytest.mark.parametrize("bad", ["abc", "0", "-5", "nan", "inf", "1,000"])
def test_a_bad_wallet_is_an_error_not_a_silent_default(monkeypatch, bad):
    monkeypatch.setenv(X.EQUITY_ENV, bad)
    with pytest.raises(ValueError):
        X.start_equity()


def test_engines_of_every_builder_start_with_the_wallet(monkeypatch):
    monkeypatch.setenv(X.EQUITY_ENV, "1000")
    for exit_ in ("ladderU|2", "ladder|2", "roe10|2", "tp3R|4"):
        assert X.make_engine(exit_, TR.BR, TR.SP).wallet == 1000.0
        assert RX.make_engine(TR.acct(None, exit_=exit_), TR.BR, TR.SP).wallet == 1000.0
    w = TR.acct(None, exit_="ladderU|2")
    w["weekend_off"] = True
    assert RX.make_engine(w, TR.BR, TR.SP).wallet == 1000.0
    assert RX.make_engine(TU._ruled("F1.w3.a", 0.5), TR.BR, TR.SP).wallet == 1000.0
    assert RX.make_engine(TR.acct("F2.n50.b", exit_="tp3R|2"), TR.BR, TR.SP).wallet == 1000.0


@pytest.mark.parametrize("side", [1, -1])
def test_a_thousand_dollar_account_takes_the_same_trade_at_a_fifth_of_the_size(monkeypatch, side):
    a = TR.acct(None, exit_="ladderU|2", role=RX.ROLE_BASE_LIVE)
    path, _top, _jx = TU._band_path(30, side, 0.20, 0.25)
    monkeypatch.delenv(X.EQUITY_ENV, raising=False)
    big = TR.run(a, path, side).trades[0]
    monkeypatch.setenv(X.EQUITY_ENV, "1000")
    small = TR.run(a, path, side).trades[0]
    assert (small.leverage, small.exit_reason, small.exit_time) == (big.leverage, big.exit_reason, big.exit_time)
    assert small.margin == pytest.approx(0.2 * big.margin, rel=0.01) and small.pnl == pytest.approx(0.2 * big.pnl, rel=0.02)
    assert small.pnl / 1000.0 == pytest.approx(big.pnl / 5000.0, rel=0.02)           # the same return on the account


def test_the_fingerprint_follows_the_wallet_and_is_unchanged_without_it(monkeypatch):
    accts = RX.owner_accounts(TU._cands(("S2_ST_ROC", "15m", "tp3R|4")), RX.normalize_owner(TU.LINEUP))
    monkeypatch.delenv(X.EQUITY_ENV, raising=False)
    default = RN.fingerprint(accts)
    monkeypatch.setenv(X.EQUITY_ENV, "5000")
    assert RN.fingerprint(copy.deepcopy(accts)) == default                          # 5000 is the default: the old league is not started over
    monkeypatch.setenv(X.EQUITY_ENV, "1000")
    assert RN.fingerprint(copy.deepcopy(accts)) != default


def test_every_module_that_prints_or_replays_the_start_wallet_reads_the_environment():
    code = ("import candleague.runner as R, candleague.summary as S, candleague.rulex as X, candleague.dash as D;"
            "print(R.EQUITY, S.EQUITY, X.INITIAL_EQUITY, D.RULE_EQUITY)")
    for env, want in ((None, "5000.0 5000.0 5000.0 5000.0"), ("1000", "1000.0 1000.0 1000.0 1000.0")):
        e = {k: v for k, v in os.environ.items() if k != X.EQUITY_ENV}
        if env:
            e[X.EQUITY_ENV] = env
        out = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {ROOT!r}); " + code], capture_output=True, text=True, env=e, cwd=ROOT)
        assert out.returncode == 0, out.stderr[-400:]
        assert out.stdout.strip() == want
