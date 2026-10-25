"""Executor sizing from the live account (owners 10-25 night: "b로해줘", "파산당하면 파산 당한다는 마인드야 그냥 항상
시드비중 40%로 해줘"): ``size_from: "equity"`` makes every new entry's margin ``margin_frac`` of the live equity at the
paper's leverage (capped by risk.max_leverage), never cut for a far stop; ``"paper"`` (the default) is unchanged."""
import dataclasses

import pytest

from fakefutures import FakeFutures
from paperbot.executor import ExecConfig
from test_executor import BTC, World, risk_cfg


def _equity_world(tmp_path, wallet=50.0, margin_frac=0.4, **risk_kw):
    w = World(tmp_path, fake=FakeFutures(wallet=wallet), **risk_kw)
    w.cfg = dataclasses.replace(w.cfg, size_from="equity", margin_frac=margin_frac)
    w.restart()
    return w


def test_equity_size_is_the_share_of_the_live_balance(tmp_path):
    w = _equity_world(tmp_path)                                   # $50 x 40 % = $20 margin, 20x at $100: 4 BTC
    w.paper(stop=95.0, qty=5.0, lev=20)                           # the paper's own quantity is not used
    w.loop()
    assert w.fake.pos[BTC] == pytest.approx(4.0)
    assert w.stops() == [(95.0, 4.0)]
    assert w.ex.trade["planned_qty"] == pytest.approx(4.0)
    w.store.close()


def test_equity_size_is_never_cut_for_a_far_stop(tmp_path):
    w = _equity_world(tmp_path)
    w.paper(stop=90.0, qty=5.0, lev=20)                           # 10 % away: the stop would cost 80 % of the balance
    w.loop()
    assert w.fake.pos[BTC] == pytest.approx(4.0)                  # still 40 % of the balance (owners: always 40 %)
    w.store.close()


def test_paper_size_still_cut_by_the_loss_share(tmp_path):
    """The default ("paper") keeps its loss-share cut: the same far stop gets a smaller size."""
    w = World(tmp_path, fake=FakeFutures(wallet=50.0))
    w.cfg = dataclasses.replace(w.cfg, qty_scale=0.8)             # 5 x 0.8 = 4 BTC before the cut
    w.restart()
    w.paper(stop=95.0, qty=5.0, lev=20)                           # 4 BTC would lose ~$21 = 42 % of $50 at the stop
    w.loop()
    assert 0 < w.fake.pos[BTC] < 4.0                              # cut to the paper rules' loss share
    w.store.close()


def test_equity_size_follows_the_balance_as_it_changes(tmp_path):
    w = _equity_world(tmp_path, wallet=100.0)                     # $100: 8 BTC
    w.paper(stop=95.0, qty=5.0, lev=20)
    w.loop()
    assert w.fake.pos[BTC] == pytest.approx(8.0)
    w.store.close()


def test_equity_size_at_the_capped_leverage_keeps_the_share(tmp_path):
    w = _equity_world(tmp_path)                                   # risk.max_leverage 20 (risk_cfg)
    w.paper(stop=97.0, qty=5.0, lev=30)                           # paper 30x -> traded at 20x: margin still $20
    w.loop()
    assert w.fake.lev[BTC] == 20 and w.fake.pos[BTC] == pytest.approx(4.0)
    w.store.close()


def test_equity_size_below_the_minimum_is_skipped(tmp_path):
    w = _equity_world(tmp_path, wallet=0.01)                      # $0.01 x 40 % x 20 / 100 = 0.0008 < 0.001
    w.paper(stop=95.0, qty=5.0, lev=20)
    w.loop()
    assert w.fake.pos[BTC] == 0
    assert any("최소 수량" in text for _, _, text in w.events("entry_check"))
    w.store.close()


def test_entry_qty_without_a_known_balance_is_zero(tmp_path):
    w = _equity_world(tmp_path)
    w.ex.risk.last_equity = None
    spec = {"qty_step": 0.001, "min_qty": 0.001, "tick": 0.1, "min_notional": 100.0}
    w.paper(stop=95.0)
    assert w.ex._entry_qty(w.src.intent, 100.0, spec) == 0.0
    w.store.close()


@pytest.mark.parametrize("extra,word", [
    ({"size_from": "equity"}, "margin_frac"),
    ({"size_from": "equity", "margin_frac": 1.5}, "margin_frac"),
    ({"size_from": "equity", "margin_frac": 0.4, "entry_source": "signal"}, "entry_source"),
    ({"margin_frac": 0.4}, "margin_frac은 size_from"),
    ({"size_from": "wallet"}, "size_from은"),
])
def test_config_refusals(tmp_path, extra, word):
    cfg = ExecConfig(account="A@15m", paper_db="p", db=str(tmp_path / "e.db"), qty_scale=1.0,
                     risk=risk_cfg(tmp_path), **extra)
    assert any(word in p for p in cfg.problems())


def test_config_equity_ok_and_described(tmp_path):
    from paperbot.executor import guard_lines
    cfg = ExecConfig(account="A@15m", paper_db="p", db=str(tmp_path / "e.db"), qty_scale=1.0,
                     risk=risk_cfg(tmp_path), size_from="equity", margin_frac=0.4)
    assert not [p for p in cfg.problems() if "size_from" in p or "margin_frac" in p]
    assert any("실거래 잔고의 40%" in line for line in guard_lines(cfg))
