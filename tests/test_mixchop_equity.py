"""Owners 2026-11-03, the 레인지 봇's log: WOO X Pro answered an equity of $0.0014 (16:30 KST) and $0.0055 (18:00 KST)
between good readings of about $52, so two signals were skipped as "smaller than the minimum" (size 0). Since then an
entry's or an exit's live equity reading under EQ_ODD_FRAC of the last good one is read again (EQ_RETRIES, EQ_RETRY_S
apart); recovered: that one is used; still wrong: the entry is skipped and the message says the exchange answered it
(never a size from it), the exit has no P&L (never one from it); both logged with the exchange's own rows."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from paperbot import mixchop as M  # noqa: E402

T0 = 1_800_000_000_000


class Stub:
    """A live broker whose equity answers come from a list (the last one repeats)."""
    live = True

    def __init__(self, eqs):
        self.eqs, self.n, self.cancelled = list(eqs), 0, []

    def equity(self):
        v = self.eqs[min(self.n, len(self.eqs) - 1)]
        self.n += 1
        return v

    def balance_rows(self):
        return [{"currency": "USDT", "equity": "0.0055", "available_balance": "52.39"}]

    def spec(self, sym):
        return {"qty_step": 0.001, "min_qty": 0.001, "min_notional": 5.0}

    def cancel_stops(self, sym):
        self.cancelled.append(sym)


def _bot(tmp_path, eqs):
    d = json.loads((ROOT / "deploy" / "mixrange.live.json").read_text(encoding="utf-8"))
    d.update(state=str(tmp_path / "s.json"), log=str(tmp_path / "l.jsonl"), kill_file=str(tmp_path / "STOP"),
             own_stop_file=str(tmp_path / "OWN"), telegram=False)
    (tmp_path / "c.json").write_text(json.dumps(d), encoding="utf-8")
    cfg = M.load_config(str(tmp_path / "c.json"))
    msgs, sleeps = [], []
    b = Stub(eqs)
    bot = M.Bot(cfg, b, lambda s, tf, n: [], lambda: T0, notify=lambda lv, t: msgs.append(t), sleep=sleeps.append)
    return bot, b, msgs, sleeps, cfg


def _log(cfg):
    return [json.loads(x) for x in Path(cfg.log).read_text(encoding="utf-8").splitlines()]


def test_a_wrong_reading_read_again_and_the_good_one_used(tmp_path):
    bot, b, msgs, sleeps, cfg = _bot(tmp_path, [52.39, 0.0055, 52.4])
    assert bot.entry_equity() == 52.39 and bot._eq_good == 52.39 and sleeps == []
    assert bot.entry_equity() == 52.4 and bot._eq_odd is None and sleeps == [M.EQ_RETRY_S]
    odd = [r for r in _log(cfg) if r["kind"] == "equity_odd"]
    assert odd[0]["reads"] == [0.0055, 52.4] and odd[0]["recovered"] is True and odd[0]["what"] == "entry"
    assert odd[0]["rows"] == [{"currency": "USDT", "equity": "0.0055", "available_balance": "52.39"}]


def test_still_wrong_the_entry_is_skipped_and_said_so(tmp_path):
    bot, b, msgs, sleeps, cfg = _bot(tmp_path, [52.39, 0.0055])
    bot.entry_equity()
    co = cfg.coins[2]                                         # ZEC, 20x
    ev = {"symbol": co.symbol, "side": -1, "stop_dist": 25.0, "close": 1128.0, "stop_pct": 2.239, "rule": "o4h"}
    bot.enter(co, ev)
    assert bot.pos is None and sleeps == [M.EQ_RETRY_S] * M.EQ_RETRIES
    assert "거래소가 잔고를 $0.0055로 알려 줬어요(바로 전 $52.39). 2번 다시 읽어도 같아서 이번 신호는 건너뛰어요" in msgs[-1]
    assert "WOO X Pro 앱에서 선물 잔고를 확인해 주세요" in msgs[-1]
    odd = [r for r in _log(cfg) if r["kind"] == "equity_odd"][-1]
    assert odd["recovered"] is False and odd["reads"] == [0.0055] * (M.EQ_RETRIES + 1)


def test_a_wrong_reading_never_makes_an_exit_pnl(tmp_path):
    bot, b, msgs, sleeps, cfg = _bot(tmp_path, [52.39, 0.0055])
    bot.entry_equity()
    p = M.Position(symbol="BTCUSDT", side=1, qty=0.01, entry=77_000.0, stop_dist=500.0, stop=76_500.0, best=77_000.0,
                   step=0, opened_ms=T0, signal_close_ms=T0, signal_close=77_000.0, last_bar_ms=T0, leverage=40,
                   roe_act=100.0, equity_before=52.39)
    bot.pos = p
    bot.finish(p, None, "stop")
    ex = [r for r in _log(cfg) if r["kind"] == "exit"][-1]
    assert ex["pnl"] is None and ex["equity"] is None and "손익" not in msgs[-1] and b.cancelled == ["BTCUSDT"]


def test_a_real_loss_and_paper_are_read_once(tmp_path):
    bot, b, msgs, sleeps, cfg = _bot(tmp_path, [52.39, 40.0])     # -24 %: a loss, not a wrong reading
    bot.entry_equity()
    assert bot.entry_equity() == 40.0 and sleeps == [] and bot._eq_good == 40.0
    b.live = False
    b.eqs, b.n = [0.0055], 0
    assert bot.entry_equity() == 0.0055 and sleeps == []           # paper: its own numbers
