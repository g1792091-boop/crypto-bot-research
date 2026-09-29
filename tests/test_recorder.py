import json
import shutil
import urllib.parse

import numpy as np
import pandas as pd
import pytest

from paperbot import sweepsig
from paperbot.archive import FIVE_MIN, RECORD_SYMBOLS, MarketArchive, sync
from paperbot.binance import BinanceREST
from paperbot.ledger import BookStore
from paperbot.live import LiveRunner
from paperbot.notify import ListNotifier
from paperbot.record import main as record_main
from paperbot.recorder import SLIP, Recorder, _ms, build_frames

L = sweepsig.lib()
START = "2026-08-01"
T0 = int(pd.Timestamp(START, tz="UTC").value // 1_000_000)
CELLS = [("N24_DMI", "5m"), ("N01_ST_EMA", "5m"), ("DOGE_L", "5m"),
         ("N03_ADX_GC", "1h"), ("V45_AMB", "1h")]


def synth(days=32, seed=3):
    return L.synth_ohlcv(days * 288, "5m", seed=seed, start=START)


def kline_rows(df):
    ms = _ms(df["ts"])
    return [[int(t), o, h, l, c, v, int(t) + FIVE_MIN - 1, v * c, 7, v / 2, v * c / 2, "0"]
            for t, o, h, l, c, v in zip(ms, df.open, df.high, df.low, df.close, df.volume)]


def fill(archive, df, symbol="BTCUSDT"):
    rows = kline_rows(df)
    archive.insert_klines(symbol, rows, exchange_now=rows[-1][6] + 1)


# ------------------------------------------------------------------ locked code
def test_locked_code_hashes_and_classes():
    v = sweepsig.verify()
    assert len(v["files"]) == 11 and v["source_commit"] == "a20ebe5"
    assert sweepsig.class_counts() == {"1": 0, "2": 164, "3": 58}
    assert len(sweepsig.cells("2")) == 164 and sweepsig.cells("1") == []
    assert ("V45_AMB", "1d") in sweepsig.cells("3")


def test_changed_locked_file_is_refused(tmp_path, monkeypatch):
    root = tmp_path / "sweep"
    shutil.copytree(sweepsig.ROOT, root)
    monkeypatch.setattr(sweepsig, "ROOT", str(root))
    monkeypatch.setattr(sweepsig, "CLASSIFICATION", str(root / "classify" / "classification.csv"))
    sweepsig.verify()
    with open(root / "harness" / "vendor" / "strategies.py", "a") as fh:
        fh.write("\n# edited\n")
    with pytest.raises(sweepsig.LockedCodeChanged):
        sweepsig.verify()


# ------------------------------------------------------------------ archive
class FakeBinance5m:
    def __init__(self, df, now_ms, funding=()):
        self.rows = kline_rows(df)
        self.now = now_ms
        self.funding = list(funding)
        self.calls = []

    def fetch(self, url, headers):
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        self.calls.append(u.path)
        if u.path == "/fapi/v1/time":
            return 200, json.dumps({"serverTime": self.now}).encode(), {}
        if u.path in ("/fapi/v1/klines", "/fapi/v1/markPriceKlines"):
            start, limit = int(q.get("startTime", 0)), int(q["limit"])
            rows = [r for r in self.rows if r[0] >= start and r[0] <= self.now][:limit]
            if u.path.endswith("markPriceKlines"):
                rows = [[r[0], r[1] * 1.001, r[2] * 1.001, r[3] * 1.001, r[4] * 1.001, "0", r[6]]
                        for r in rows]
            return 200, json.dumps(rows).encode(), {}
        if u.path == "/fapi/v1/fundingRate":
            start, limit = int(q.get("startTime", 0)), int(q["limit"])
            rows = [{"symbol": q["symbol"], "fundingTime": t, "fundingRate": str(r), "markPrice": "100"}
                    for t, r in self.funding if start <= t <= self.now][:limit]
            return 200, json.dumps(rows).encode(), {}
        return 404, b"{}", {}


def test_sync_backfills_pages_skips_forming_bar_and_keeps_revisions(tmp_path):
    df = synth(days=2)
    rows = kline_rows(df)
    now = rows[-1][0] + 60_000  # the last bar is still forming
    funding = [(T0 + k * 8 * 3_600_000, 0.0001 * (k + 1)) for k in range(6)]
    fake = FakeBinance5m(df, now, funding)
    rest = BinanceREST(fetch=fake.fetch, sleep=lambda s: None)
    arch = MarketArchive(str(tmp_path / "m.db"))
    s = sync(arch, rest, ["BTCUSDT"], since_ms=T0, pace=0, sleep=lambda s: None, page=100)
    k = s["symbols"]["BTCUSDT"]
    assert k["kline"]["added"] == len(rows) - 1 and k["kline"]["requests"] >= 6
    assert k["mark"]["added"] == len(rows) - 1 and k["funding"]["added"] == 6
    assert arch.last_time("kline5m", "BTCUSDT") == rows[-2][0]
    df5 = arch.load_5m("BTCUSDT")
    assert list(df5.columns) == ["ts", "open", "high", "low", "close", "volume"]
    assert str(df5["ts"].dtype) == "datetime64[ns, UTC]" and len(df5) == len(rows) - 1
    # Next sync: the forming bar has closed; one more bar arrives; nothing is duplicated.
    fake.now = rows[-1][6] + 1
    s2 = sync(arch, rest, ["BTCUSDT"], since_ms=T0, pace=0, sleep=lambda s: None, page=100)
    assert s2["symbols"]["BTCUSDT"]["kline"]["added"] == 1
    # The exchange later reports a different value for a stored bar: kept, and logged.
    fake.rows[-1][4] = fake.rows[-1][4] * 1.01
    sync(arch, rest, ["BTCUSDT"], since_ms=T0, pace=0, sleep=lambda s: None, page=100)
    rev = arch.conn.execute("SELECT tbl, time FROM revisions").fetchall()
    assert ("kline5m", rows[-1][0]) in rev
    stored_close = arch.conn.execute("SELECT close FROM kline5m WHERE open_time = ?",
                                     (rows[-1][0],)).fetchone()[0]
    assert stored_close == pytest.approx(float(df.close.iloc[-1]))


def test_live_runner_records_book_snapshots(tmp_path):
    from paperbot import Brackets, PaperEngine, Settings
    s = Settings()
    eng = PaperEngine(s, {x: Brackets.example() for x in s.symbols})
    books = BookStore(str(tmp_path / "p.db"), RECORD_SYMBOLS, clock_ms=lambda: 123)
    tickers = [{"symbol": sym, "bidPrice": "10", "bidQty": "1", "askPrice": "10.1", "askQty": "2",
                "time": 5} for sym in RECORD_SYMBOLS + ("ADAUSDT",)]
    lr = LiveRunner(None, eng, [], ListNotifier(), book_fn=lambda: tickers, book_store=books)
    from paperbot.models import Bar
    lr.process([(0, {"BTCUSDT": Bar("BTCUSDT", 0, 59_999, 1, 1, 1, 1)}, {})])
    got = {r[0] for r in books.conn.execute("SELECT symbol FROM book")}
    assert got == set(RECORD_SYMBOLS)  # XRP included, other symbols ignored
    lr.process([])  # no new bar, no snapshot
    assert books.conn.execute("SELECT COUNT(*) FROM book").fetchone()[0] == 7


# ------------------------------------------------------------------ frames and signals
def test_build_frames_drops_the_forming_bar():
    df = synth(days=2).iloc[:-1]  # ends 5 minutes before a full hour
    fr = build_frames(L, df, ["5m", "15m", "1h"])
    last_close = int(_ms(df["ts"])[-1]) + FIVE_MIN
    for tf, span in (("15m", 900_000), ("1h", 3_600_000)):
        ends = _ms(fr[tf]["ts"]) + span
        assert ends.max() <= last_close
    full = L.resample_ohlcv(df, "1h")
    assert len(full) == len(fr["1h"]) + 1  # sweep_lib keeps the forming hour; we drop it
    pd.testing.assert_frame_equal(fr["1h"], full.iloc[:-1].reset_index(drop=True), check_like=True)


def test_build_frames_drops_a_partial_first_bar():
    df = synth(days=2).iloc[9:].reset_index(drop=True)  # starts at 00:45
    fr = build_frames(L, df, ["1h"])
    assert fr["1h"]["ts"].iloc[0] == pd.Timestamp(START, tz="UTC") + pd.Timedelta(hours=1)
    full = L.resample_ohlcv(df, "1h")
    assert full["ts"].iloc[0] == pd.Timestamp(START, tz="UTC")  # sweep_lib keeps it; we drop it


def _direct(df, cells):
    """Signals straight from sweep_lib on the same bars read the way the backtest read them."""
    out = {}
    last_close = df.ts.iloc[-1] + pd.Timedelta(minutes=5)
    for tf in sorted({tf for _, tf in cells}):
        names = [n for n, t in cells if t == tf]
        c = df if tf == "5m" else L.resample_ohlcv(df, tf)
        c = c[c.ts + pd.Timedelta(minutes=L.tf_minutes(tf)) <= last_close].reset_index(drop=True)
        sig = L.compute_signals({"BTCUSDT": c}, tf, names)
        for n in names:
            a = sig[n]["BTCUSDT"]
            for i in np.flatnonzero(a):
                close = c.ts.iloc[i] + pd.Timedelta(minutes=L.tf_minutes(tf))
                if i >= L.warmup_bars(tf) and close < last_close:  # entry bar exists
                    out[f"{n}|{tf}|BTCUSDT|{c.ts.iloc[i].value // 1_000_000}"] = int(a[i])
    return out


def test_recorded_signals_equal_the_locked_code(tmp_path):
    df = synth()
    csv_path = tmp_path / "btc5m.csv"
    df.to_csv(csv_path, index=False)
    direct = _direct(L.read_ohlcv(str(csv_path)), CELLS)
    arch = MarketArchive(str(tmp_path / "m.db"))
    fill(arch, df)
    rep = Recorder(arch, cells=CELLS).run(["BTCUSDT"])
    got = {r[0]: r[1] for r in arch.conn.execute("SELECT signal_id, side FROM sweep_signals")}
    assert rep["status"] == "ok" and rep["mismatches"] == 0 and rep["n_errors"] == 0
    assert len(direct) > 20
    assert got == direct
    assert all(rep["warmup"]["BTCUSDT"][tf]["ready"] for tf in ("5m", "1h"))


def test_daily_runs_equal_one_shot_and_deferred_signals_get_recorded(tmp_path):
    df = synth(days=34)
    one = MarketArchive(str(tmp_path / "one.db"))
    fill(one, df)
    Recorder(one, cells=CELLS).run(["BTCUSDT"])
    inc = MarketArchive(str(tmp_path / "inc.db"))
    rec = Recorder(inc, cells=CELLS)
    for end in (31 * 288, 32 * 288 + 7, 33 * 288 + 100, len(df)):
        fill(inc, df.iloc[:end])
        rep = rec.run(["BTCUSDT"])
        assert rep["mismatches"] == 0
    q = "SELECT signal_id, side, entry_time, next_open, virtual_entry FROM sweep_signals ORDER BY 1"
    a, b = one.conn.execute(q).fetchall(), inc.conn.execute(q).fetchall()
    assert a == b and len(a) > 20
    for sid, side, entry, nxt, ve in a:
        assert ve == pytest.approx(nxt * (1 + side * SLIP))


def test_recompute_differences_raise_a_critical_alert(tmp_path):
    df = synth()
    arch = MarketArchive(str(tmp_path / "m.db"))
    fill(arch, df.iloc[:-300])
    note = ListNotifier()
    rec = Recorder(arch, cells=CELLS, notifier=note)
    rec.run(["BTCUSDT"])
    sid_flip, sid_drop = [r[0] for r in arch.conn.execute(
        "SELECT signal_id FROM sweep_signals ORDER BY bar_open LIMIT 2")]
    arch.conn.execute("UPDATE sweep_signals SET side = -side WHERE signal_id = ?", (sid_flip,))
    arch.conn.execute("DELETE FROM sweep_signals WHERE signal_id = ?", (sid_drop,))
    arch.conn.execute("INSERT INTO sweep_signals SELECT 'FAKE|5m|BTCUSDT|1', strategy, tf, symbol, side, "
                      "bar_open, bar_close, close, atr14, cls, entry_time, next_open, virtual_entry, "
                      "latency_ms, book_ts, book_bid, book_ask, est_fill, recorded_ts, run_id "
                      "FROM sweep_signals LIMIT 1")
    arch.conn.commit()
    fill(arch, df)
    rep = rec.run(["BTCUSDT"])
    kinds = {k: sid for k, sid in arch.conn.execute("SELECT kind, signal_id FROM sweep_mismatch")}
    assert kinds == {"side_changed": sid_flip, "appeared_late": sid_drop,
                     "disappeared": "FAKE|5m|BTCUSDT|1"}
    assert rep["mismatches"] == 3
    level, text = note.messages[-1]
    assert level == "CRITICAL" and "3 past signals changed" in text


def test_entry_after_a_gap_warmup_and_book_estimate(tmp_path, monkeypatch):
    df = synth()
    ms = _ms(df["ts"])
    k_warm, k_sig = 100, 9000  # 5m bar indexes: inside the warm-up / after it
    fire = {int(ms[k_warm]): 1, int(ms[k_sig]): -1}

    def test_strategy(d, frames=None):
        t = _ms(d["ts"])
        side = np.array([fire.get(int(x), 0) for x in t])
        return side > 0, side < 0

    monkeypatch.setitem(L.REGISTRY, "T_FIRE", test_strategy)
    gap = df.drop(index=[k_sig + 1, k_sig + 2]).reset_index(drop=True)  # exchange had no bars
    arch = MarketArchive(str(tmp_path / "m.db"))
    fill(arch, gap)
    ledger = str(tmp_path / "paper.db")
    bar_close = int(ms[k_sig]) + FIVE_MIN
    books = BookStore(ledger, RECORD_SYMBOLS, clock_ms=lambda: bar_close + 20_000)
    books.add([{"symbol": "BTCUSDT", "bidPrice": "99.5", "bidQty": "3", "askPrice": "99.6",
                "askQty": "1", "time": bar_close}])
    Recorder(arch, ledger_path=ledger, cells=[("T_FIRE", "5m")]).run(["BTCUSDT"])
    rows = arch.conn.execute("SELECT side, bar_close, entry_time, latency_ms, next_open, "
                             "virtual_entry, est_fill, book_bid FROM sweep_signals").fetchall()
    assert len(rows) == 1  # the warm-up signal is not recorded
    side, close_t, entry, latency, nxt, ve, est, bid = rows[0]
    assert side == -1 and close_t == bar_close
    assert entry == int(ms[k_sig + 3]) and latency == 2 * FIVE_MIN
    assert nxt == pytest.approx(float(df.open.iloc[k_sig + 3]))
    assert ve == pytest.approx(nxt * (1 - SLIP)) and est == bid == 99.5


def test_record_cli_compute_and_status(tmp_path, capsys, monkeypatch):
    df = synth()
    db = str(tmp_path / "market.db")
    arch = MarketArchive(db)
    fill(arch, df)
    arch.close()
    monkeypatch.setattr(sweepsig, "cells", lambda cls="2", path=None: CELLS if cls == "2" else [])
    monkeypatch.setattr("paperbot.record._notifier", lambda: ListNotifier())
    assert record_main(["compute", "--market", db, "--symbols", "BTCUSDT"]) == 0
    capsys.readouterr()
    record_main(["status", "--market", db, "--symbols", "BTCUSDT"])
    st = json.loads(capsys.readouterr().out)
    assert st["signals_total"] > 20 and st["runs"][0]["status"] == "ok"
    assert st["mismatches_total"] == 0
