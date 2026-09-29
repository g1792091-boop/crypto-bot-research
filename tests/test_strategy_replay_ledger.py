import csv
import json
import sqlite3

import pytest

from paperbot import Bar, Brackets, PaperEngine, Settings, Signal
from paperbot.ledger import Ledger
from paperbot.replay import main as replay_main
from paperbot.strategy import StrategyRunner

MIN = 60_000


class EveryThird:
    strategy_id = "every3"
    timeframe = "1m"
    warmup_bars = 3

    def on_bar(self, symbol, history):
        b = history[-1]
        if len(history) % 3:
            return []
        return [Signal(b.close_time, symbol, "1m", self.strategy_id, +1, b.close * 0.99)]


class BadStamp(EveryThird):
    strategy_id = "bad"

    def on_bar(self, symbol, history):
        b = history[-1]
        return [Signal(b.open_time, symbol, "1m", self.strategy_id, +1, b.close * 0.99)]


def bars(n, sym="BTCUSDT"):
    return [Bar(sym, i * MIN, i * MIN + MIN - 1, 100, 100.2, 99.8, 100) for i in range(n)]


def test_runner_respects_warmup():
    r = StrategyRunner([EveryThird()])
    out = [r.on_closed_bar("1m", b) for b in bars(6)]
    assert [len(x) for x in out] == [0, 0, 1, 0, 0, 1]


def test_runner_rejects_wrong_signal_timestamp():
    r = StrategyRunner([BadStamp()])
    with pytest.raises(ValueError):
        for b in bars(3):
            r.on_closed_bar("1m", b)


def test_runner_rejects_out_of_order_bars():
    r = StrategyRunner([EveryThird()])
    b = bars(2)
    r.on_closed_bar("1m", b[1])
    with pytest.raises(ValueError):
        r.on_closed_bar("1m", b[0])


def test_ledger_persists_trades_and_outcomes(tmp_path):
    s = Settings()
    db = tmp_path / "ledger.db"
    led = Ledger(str(db), "run1", s.version)
    e = PaperEngine(s, {x: Brackets.example() for x in s.symbols},
                    on_trade=led.trade, on_outcome=led.outcome, on_equity=led.equity)
    e.submit(Signal(MIN - 1, "BTCUSDT", "1m", "t", +1, 99.0))
    e.step({"BTCUSDT": Bar("BTCUSDT", MIN, 2 * MIN - 1, 100, 100.1, 99.9, 100)})
    e.step({"BTCUSDT": Bar("BTCUSDT", 2 * MIN, 3 * MIN - 1, 100, 100.1, 98.5, 99)})
    led.close()
    con = sqlite3.connect(db)
    assert con.execute("select count(*) from trades").fetchone()[0] == 1
    assert con.execute("select status from signals").fetchone()[0] == "ENTERED"
    trade = json.loads(con.execute("select data from trades").fetchone()[0])
    assert trade["exit_reason"] == "SL"


def test_replay_cli_end_to_end(tmp_path, capsys):
    bdir = tmp_path / "bars"
    bdir.mkdir()
    with open(bdir / "BTCUSDT.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["open_time", "close_time", "open", "high", "low", "close"])
        w.writerow([0, MIN - 1, 100, 100, 100, 100])
        w.writerow([MIN, 2 * MIN - 1, 100, 100.1, 99.9, 100])
        w.writerow([2 * MIN, 3 * MIN - 1, 100, 100.8, 99.9, 100.6])
    sfile = tmp_path / "signals.csv"
    with open(sfile, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ts", "symbol", "timeframe", "strategy_id", "side", "stop_price", "tier"])
        w.writerow([MIN - 1, "BTCUSDT", "1m", "demo", 1, 99.0, "base"])
    out = tmp_path / "summary.json"
    replay_main(["--bars", str(bdir), "--signals", str(sfile), "--out", str(out)])
    books = {b["book"]: b for b in json.loads(out.read_text())}
    assert set(books) == {"owner", "recommended"}
    for b in books.values():
        assert b["brackets_source"].startswith("EXAMPLE")
        assert b["signals"] == 1
    # Same signal, different exits: the owner book's ROE-10% target (0.5% at
    # 20x) is hit on this path; the recommended book's 2R target is not yet.
    assert books["owner"]["trades"] == 1 and books["owner"]["final_equity"] > 1000
    assert books["recommended"]["trades"] == 0
