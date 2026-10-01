import pytest

from paperbot import risk as R

DAY = 86_400_000
T0 = 20_000 * DAY + 3_600_000          # 01:00 UTC on some day


def cfg(**kw):
    base = dict(daily_max_loss_usd=100.0, max_drawdown_pct=0.2, max_consecutive_losses=3, max_leverage=10,
                max_notional_usd=1_000.0, allowed_symbols=("BTCUSDT", "ETHUSDT"), kill_file="/nonexistent/STOP")
    base.update(kw)
    return R.RiskConfig(**base)


def test_config_must_be_filled_by_the_owners():
    empty = R.RiskConfig()
    probs = empty.problems()
    assert len(probs) == len(R.REQUIRED)
    assert any("하루 최대 손실" in p for p in probs) and any("멈춤 낙폭" in p for p in probs)
    assert cfg().problems() == []
    bad = cfg(max_drawdown_pct=20, max_leverage=0, max_consecutive_losses=0, daily_max_loss_usd=-1)
    assert len(bad.problems()) == 4
    with pytest.raises(ValueError):
        R.RiskConfig.from_dict({"daily_loss": 5})
    assert R.RiskConfig.from_dict({"allowed_symbols": ["btcusdt"]}).allowed_symbols == ("BTCUSDT",)


def test_entry_allow_reduce_block():
    st = R.RiskState()
    d = R.check_entry(cfg(), st, "BTCUSDT", qty=5, price=100, leverage=10, qty_step=0.001)
    assert d.action == R.ALLOW and d.qty == 5 and d.leverage == 10 and d.ok
    d = R.check_entry(cfg(), st, "BTCUSDT", qty=5, price=100, leverage=50, qty_step=0.001)
    assert d.action == R.REDUCE and d.leverage == 10 and "50배" in d.text()
    d = R.check_entry(cfg(), st, "BTCUSDT", qty=15, price=100, leverage=10, qty_step=0.001)
    assert d.action == R.REDUCE and d.qty == pytest.approx(10.0) and "줄입니다" in d.text()
    d = R.check_entry(cfg(max_notional_usd=50), st, "BTCUSDT", qty=1, price=100, leverage=10, qty_step=1, min_qty=1)
    assert d.action == R.BLOCK and "최소 수량" in d.text()
    d = R.check_entry(cfg(), st, "BTCUSDT", qty=0.5, price=100, leverage=10, qty_step=0.001, min_notional=100)
    assert d.action == R.BLOCK and "최소" in d.text()
    d = R.check_entry(cfg(), st, "DOGEUSDT", qty=5, price=0.1, leverage=10, qty_step=1)
    assert d.action == R.BLOCK and "허용 코인" in d.text() and not d.ok
    R.halt(st, T0, "테스트")
    assert R.check_entry(cfg(), st, "BTCUSDT", 5, 100, 10, 0.001).action == R.BLOCK


def test_loop_checks_daily_loss_drawdown_streak_kill():
    st = R.RiskState()
    R.observe_equity(st, T0, 1_000.0)
    assert R.check_loop(cfg(), st, 1_000.0).action == R.ALLOW
    R.observe_equity(st, T0 + 60_000, 901.0)
    assert R.check_loop(cfg(), st, 901.0).action == R.ALLOW
    R.observe_equity(st, T0 + 120_000, 900.0)
    d = R.check_loop(cfg(), st, 900.0)
    assert d.action == R.FLATTEN_HALT and "하루 한도" in d.text()
    # drawdown from the peak, across days
    st = R.RiskState()
    R.observe_equity(st, T0, 1_000.0)
    R.observe_equity(st, T0 + DAY, 850.0)
    R.observe_equity(st, T0 + 2 * DAY, 800.0)
    d = R.check_loop(cfg(daily_max_loss_usd=10_000), st, 800.0)
    assert d.action == R.FLATTEN_HALT and "낙폭 20.0%" in d.text()
    # loss streak
    st = R.RiskState()
    R.observe_equity(st, T0, 1_000.0)
    for pnl in (-1, -1, 5, -1, -1):
        R.record_trade(st, pnl)
    assert st.consecutive_losses == 2 and R.check_loop(cfg(), st, 1_000.0).action == R.ALLOW
    R.record_trade(st, -1)
    assert "연속 손실 3번" in R.check_loop(cfg(), st, 1_000.0).text()
    # kill switch
    st = R.RiskState()
    R.observe_equity(st, T0, 1_000.0)
    kill = R.kill_switch_on(cfg(kill_file="/k"), exists=lambda p: p == "/k")
    assert kill and "/k" in kill
    assert R.check_loop(cfg(), st, 1_000.0, kill).action == R.FLATTEN_HALT
    assert R.kill_switch_on(cfg(), exists=lambda p: False) is None


def test_halt_persists_until_a_person_clears_it():
    st = R.RiskState()
    R.observe_equity(st, T0, 1_000.0)
    R.observe_equity(st, T0 + 1, 890.0)
    d = R.check_loop(cfg(), st, 890.0)
    assert R.halt(st, T0 + 1, d.text()) and not R.halt(st, T0 + 2, "다른 이유")
    st2 = R.RiskState.from_dict(st.to_dict())               # what a restart sees
    assert st2.halted and "하루 한도" in st2.halt_reason
    R.observe_equity(st2, T0 + 10, 1_000.0)                 # even with the money back: still halted
    d = R.check_loop(cfg(), st2, 1_000.0)
    assert d.action == R.FLATTEN_HALT and "사람이 풀어야" in d.text()
    # cleared the same day at a loss: the daily limit is still hit -> halts again
    R.observe_equity(st2, T0 + 20, 890.0)
    assert "하루 한도" in R.clear_halt(st2) and not st2.halted
    assert R.check_loop(cfg(), st2, 890.0).action == R.FLATTEN_HALT
    # next UTC day the day starts from the current equity
    R.observe_equity(st2, T0 + DAY, 890.0)
    assert st2.day_start_equity == 890.0 and R.check_loop(cfg(), st2, 890.0).action == R.ALLOW


def test_clear_resets_peak_and_streak():
    st = R.RiskState()
    R.observe_equity(st, T0, 1_000.0)
    for _ in range(3):
        R.record_trade(st, -10)
    R.observe_equity(st, T0 + DAY, 700.0)
    R.halt(st, T0, "x")
    R.clear_halt(st)
    assert st.peak_equity == 700.0 and st.consecutive_losses == 0
    assert R.check_loop(cfg(), st, 700.0).action == R.ALLOW
    assert R.utc_day(T0) == R.utc_day(T0 + 3_600_000) != R.utc_day(T0 + DAY)
