import json
import urllib.parse

import pytest

from paperbot.archive import FIVE_MIN
from paperbot.binance import BinanceREST
from paperbot.flow import STATS, WINDOW_MS, FlowArchive, main as flow_main, status as flow_status, sync
from paperbot.liqstream import LiqRunner, LiqStore, parse
from paperbot.notify import ListNotifier

DAY = 86_400_000
NOW = 1_790_000_000_000 - (1_790_000_000_000 % FIVE_MIN) + 123_000  # mid-period on the exchange clock


class FakeExchange:
    """Serves 5m statistics for the last 30 days and premium klines for any time."""

    def __init__(self, now=NOW):
        self.now = now
        self.calls = []
        self.bump = 0.0  # added to values to simulate a revision

    def fetch(self, url, headers):
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        self.calls.append(u.path)
        if u.path == "/fapi/v1/time":
            return 200, json.dumps({"serverTime": self.now}).encode(), {}
        if u.path.startswith("/futures/data/"):
            start, end, limit = int(q["startTime"]), int(q["endTime"]), int(q["limit"])
            oldest = self.now - 30 * DAY
            t = max(start, oldest)
            t += (-t) % FIVE_MIN
            rows = []
            while t <= min(end, self.now) and len(rows) < limit:
                v = (t // FIVE_MIN) % 1000 + self.bump
                rows.append({"symbol": q["symbol"], "timestamp": t, "sumOpenInterest": str(v),
                             "sumOpenInterestValue": str(v * 10), "longShortRatio": str(1 + v / 1e4),
                             "longAccount": "0.6", "shortAccount": "0.4", "buySellRatio": str(1 + v / 1e5),
                             "buyVol": "5", "sellVol": "4"})
                t += FIVE_MIN
            return 200, json.dumps(rows).encode(), {}
        if u.path == "/fapi/v1/premiumIndexKlines":
            t, limit = int(q["startTime"]), int(q["limit"])
            t += (-t) % FIVE_MIN
            rows = []
            while t <= self.now and len(rows) < limit:
                rows.append([t, "0.0001", "0.0002", "0.0", "0.00015", "0", t + FIVE_MIN - 1, "0", 12, "0", "0", "0"])
                t += FIVE_MIN
            return 200, json.dumps(rows).encode(), {}
        return 404, b"{}", {}


def make(tmp_path, ex):
    fa = FlowArchive(str(tmp_path / "flow.db"), clock_ms=lambda: ex.now)
    rest = BinanceREST(fetch=ex.fetch, sleep=lambda s: None)
    return fa, rest


def test_first_sync_stores_29_days_of_closed_periods(tmp_path):
    ex = FakeExchange()
    fa, rest = make(tmp_path, ex)
    out = sync(fa, rest, ["BTCUSDT"], since_ms=NOW - 3 * DAY, sleep=lambda s: None)
    assert out["gaps"] == []
    for ds, (table, _cols) in STATS.items():
        first = fa.conn.execute(f"SELECT MIN(ts), MAX(ts), COUNT(*) FROM {table}").fetchone()
        assert first[0] >= NOW - WINDOW_MS
        assert first[1] + FIVE_MIN <= NOW  # the forming period is not stored
        assert first[2] == (first[1] - first[0]) // FIVE_MIN + 1  # no holes
        assert first[2] >= 29 * 288 - 1
    p = fa.conn.execute("SELECT MIN(ts), MAX(ts), COUNT(*) FROM premium5m").fetchone()
    assert p[0] == NOW - 3 * DAY + (-(NOW - 3 * DAY)) % FIVE_MIN and p[1] + FIVE_MIN <= NOW
    assert p[2] == (p[1] - p[0]) // FIVE_MIN + 1


def test_resync_is_idempotent_and_catches_up(tmp_path):
    ex = FakeExchange()
    fa, rest = make(tmp_path, ex)
    sync(fa, rest, ["ETHUSDT"], since_ms=NOW - DAY, sleep=lambda s: None)
    again = sync(fa, rest, ["ETHUSDT"], since_ms=NOW - DAY, sleep=lambda s: None)
    assert all(v["added"] == 0 and v["revised"] == 0 for v in again["symbols"]["ETHUSDT"].values())
    ex.now += 3600_000
    later = sync(fa, rest, ["ETHUSDT"], since_ms=NOW - DAY, sleep=lambda s: None)
    assert later["symbols"]["ETHUSDT"]["oi"]["added"] == 12
    assert later["symbols"]["ETHUSDT"]["premium"]["added"] == 12


def test_changed_value_goes_to_revisions_and_stored_row_is_kept(tmp_path):
    ex = FakeExchange()
    fa, rest = make(tmp_path, ex)
    sync(fa, rest, ["SOLUSDT"], since_ms=NOW - DAY, sleep=lambda s: None)
    last = fa.last_time("oi5m", "SOLUSDT")
    before = fa.conn.execute("SELECT sum_oi FROM oi5m WHERE ts = ?", (last,)).fetchone()[0]
    ex.bump = 0.5
    sync(fa, rest, ["SOLUSDT"], since_ms=NOW - DAY, sleep=lambda s: None)
    assert fa.conn.execute("SELECT sum_oi FROM oi5m WHERE ts = ?", (last,)).fetchone()[0] == before
    assert fa.conn.execute("SELECT COUNT(*) FROM revisions WHERE tbl = 'oi5m'").fetchone()[0] >= 1


def test_downtime_longer_than_window_is_logged_as_gap(tmp_path):
    ex = FakeExchange()
    fa, rest = make(tmp_path, ex)
    sync(fa, rest, ["BTCUSDT"], since_ms=NOW - DAY, sleep=lambda s: None)
    ex.now += 40 * DAY
    fa.clock_ms = lambda: ex.now
    out = sync(fa, rest, ["BTCUSDT"], since_ms=NOW - DAY, sleep=lambda s: None)
    assert {g["dataset"] for g in out["gaps"]} == set(STATS)
    g = fa.conn.execute("SELECT from_ts, to_ts FROM gaps WHERE dataset = 'oi'").fetchone()
    assert g[0] < g[1] == ex.now - WINDOW_MS
    st = flow_status(fa, ["BTCUSDT"], now_ms=ex.now)
    assert st["coverage_last_24h"]["BTCUSDT"]["oi5m"].startswith("287/") or \
        st["coverage_last_24h"]["BTCUSDT"]["oi5m"].startswith("288/")
    assert len(st["gaps"]) == len(STATS)


def test_status_command_runs_without_network(tmp_path, capsys):
    assert flow_main(["status", "--flow", str(tmp_path / "f.db")]) == 0
    assert "coverage_last_24h" in capsys.readouterr().out


# ------------------------------------------------------------------ liquidations
EVENT = {"e": "forceOrder", "E": 1790000000100,
         "o": {"s": "BTCUSDT", "S": "SELL", "o": "LIMIT", "f": "IOC", "q": "0.5", "p": "60000", "ap": "60010",
               "X": "FILLED", "l": "0.5", "z": "0.5", "T": 1790000000050}}


def test_parse_event_list_wrapper_and_junk():
    rows = parse(EVENT)
    assert rows == [(1790000000100, 1790000000050, "BTCUSDT", "SELL", "LIMIT", "IOC", 0.5, 60000.0, 60010.0,
                     "FILLED", 0.5, 0.5)]
    assert parse([EVENT, {"e": "other"}]) == rows
    assert parse({"stream": "x", "data": EVENT}) == rows
    assert parse("junk") == [] and parse({"e": "forceOrder"}) == []


class FakeWS:
    def __init__(self, items):
        self.items = list(items)
        self.closed = False

    def recv(self):
        if not self.items:
            raise TimeoutError("idle")
        x = self.items.pop(0)
        if isinstance(x, Exception):
            raise x
        return x

    def close(self):
        self.closed = True

    def shutdown(self):
        self.closed = True


def test_runner_stores_reconnects_and_tracks_uptime(tmp_path):
    t = {"now": 1000.0}
    store = LiqStore(str(tmp_path / "liq.db"), clock_ms=lambda: int(t["now"] * 1000))
    ev2 = dict(EVENT, o=dict(EVENT["o"], T=1790000000999, z="0.7", ap="59990"))
    conns = [FakeWS([json.dumps(EVENT), "not json", ConnectionError("reset")]),
             FakeWS([json.dumps(ev2), json.dumps(ev2)])]
    sleeps = []

    def connect():
        if not conns:
            raise OSError("no network")
        return conns.pop(0)

    def sleep(s):
        sleeps.append(s)
        t["now"] += 400  # long enough to trigger the reconnect alert

    notes = ListNotifier()
    runner = LiqRunner(store, connect=connect, notifier=notes, sleep=sleep, clock=lambda: t["now"])
    runner.run(max_connections=3)
    assert store.conn.execute("SELECT COUNT(*) FROM liq").fetchone()[0] == 2  # duplicate ignored
    events = [r[0] for r in store.conn.execute("SELECT event FROM conn_log ORDER BY rowid")]
    assert events.count("connected") == 2 and "bad_message" in events and events[-1] == "stopped"
    assert sleeps[:2] == [1.0, 1.0] or sleeps[0] == 1.0
    assert any("reconnected" in m[1] for m in notes.messages)


def test_uptime_share(tmp_path):
    store = LiqStore(str(tmp_path / "liq.db"))
    for ts, ev in ((0, "connected"), (40, "disconnected"), (60, "connected")):
        store.conn.execute("INSERT INTO conn_log VALUES (?,?,?)", (ts, ev, "{}"))
    assert store.uptime_share(0, 100) == pytest.approx(0.8)
    assert store.uptime_share(50, 100) == pytest.approx(0.8)
