"""거래 다시보기 (paperbot/dash/more/replay.py): the replay answer on a small synthetic paper3.db (bars from live_bars,
the Binance fallback, the lock steps, the reel's lines and setup), the equity lines of the 순위표 rows, the empty
database, the cache (one candle fetch per trade), the login guard and the honesty marks (rebuilt / fit)."""
import json
import math
import os
import stat
import time
from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.config import v3_settings  # noqa: E402
from paperbot.dash.app import Data, create_app, hash_password  # noqa: E402
from paperbot.dash.more import replay as R  # noqa: E402
from paperbot.ladder import roe_price  # noqa: E402
from paperbot.models import TradeRecord  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

MIN = 60_000
M5 = 5 * MIN
M15 = 15 * MIN
T0 = 1_790_000_000_000 - (1_790_000_000_000 % (4 * 3_600_000))      # a 4h boundary (UTC)
RT = v3_settings().round_trip_cost


def _minutes(bars, tf_ms):
    """tf bars (o, h, l, c) -> 1m live_bars rows: the first minute opens at o, the last closes at c, the range inside."""
    rows = []
    k = tf_ms // MIN
    for i, (o, hi, lo, c) in enumerate(bars):
        t = T0 + i * tf_ms
        for m in range(k):
            a = o + (c - o) * m / k
            b = o + (c - o) * (m + 1) / k
            rows.append({"ts": t + m * MIN, "symbol": "BTCUSDT", "open": a, "high": hi if m == k // 2 else max(a, b),
                         "low": lo if m == k // 2 + 1 or k == 1 else min(a, b), "close": b, "volume": 1.0,
                         "mark_open": a, "mark_high": max(a, b), "mark_low": min(a, b), "mark_close": b,
                         "close_time": t + (m + 1) * MIN - 1, "processed_at": t + (m + 1) * MIN + 9000})
    return rows


def _rec(**kw):
    base = dict(strategy_id="A", symbol="BTCUSDT", timeframe="15m", side=1, signal_ts=0, entry_time=0, entry_price=100.0,
                exit_time=0, exit_price=100.0, exit_reason="SL", qty=1.0, leverage=30, tier="normal", margin=100.0,
                stop_price=99.0, tp_price=float("nan"), liq_price=97.0, fees=0.1, funding=0.0, pnl=-1.0, roe=-0.01,
                price_move=0.0, mae_price=100.0, mfe_price=100.0, equity_after=4999.0, score=0.0, context={})
    base.update(kw)
    return TradeRecord(**base)


# ---------------------------------------------------------------- the synthetic world
def _core_bars():
    """15m bars: 41 flat, then a rise of 0.2% a bar for 5 bars (best net ROE at 30x about +26%: lock +20%), then a
    fall of 0.3% a bar (the +20% lock is hit in bar 46)."""
    out, px = [], 100.0
    for i in range(70):
        if i < 41:
            o, c = px, px * (1.0005 if i % 2 else 0.9995)
        elif i < 46:
            o, c = px, px * 1.002
        else:
            o, c = px, px * 0.997
        out.append((o, max(o, c) * 1.0004, min(o, c) * 0.9996, c))
        px = c
    return out


def _reel_bars():
    """5m bars: a slow rise (the middle line above the 200 line), one close far below the lower band (bar 240), a green
    bar back inside the band (241, the signal), then a rise to the upper band (the target is hit)."""
    out = []
    for i in range(240):
        c = 100 + 0.02 * i + (0.03 if i % 2 else -0.03)
        o = out[-1][3] if out else c
        out.append((o, max(o, c) + 0.01, min(o, c) - 0.01, c))
    x = out[-1][3]
    out.append((x, x + 0.01, x - 1.3, x - 1.2))           # 240: breach
    out.append((x - 1.2, x - 0.6, x - 1.25, x - 0.7))     # 241: green, inside the band = the signal
    px = x - 0.7
    for i in range(30):                                   # 242...: the trade, up to the band
        o, c = px, px + 0.08
        out.append((o, c + 0.02, o - 0.02, c))
        px = c
    return out


@pytest.fixture
def world(tmp_path):
    db = str(tmp_path / "paper3.db")
    st = Store3(db)
    st.add_account("A@15m", "S5_DONCHIAN_MFI", "15m", "strategy", T0, "paper-v4", None, {"group": "core"})
    st.add_account("REEL_H1@5m", "REEL_H1", "5m", "reel", T0, "paper-v4", None, {"group": "reel", "exits": "reel"})
    st.add_account("RANDOM_1@5m", "RANDOM_1", "5m", "random", T0, "paper-v4", None, {"group": "flip", "exits": "reel"})
    st.add_account("B@15m", "S1_EMA_RSI_CHOP", "15m", "strategy", T0, "paper-v4", None, {"group": "core"})
    # core bars on BTC 15m (the reel's 5m bars on ETH below)
    core = _core_bars()
    st.live_bars(_minutes(core, M15))
    e = 41                                                # entry bar (signal bar 40)
    entry = core[e][0] * 1.0002
    lock, lev = 0.20, 30
    stop_final = roe_price(1, entry, lev, lock, RT)
    xbar = 46
    st.trade("A@15m", _rec(signal_ts=T0 + e * M15 - 1, entry_time=T0 + e * M15 + 10_000, entry_price=entry,
                           exit_time=T0 + xbar * M15 + 7 * MIN, exit_price=stop_final * (1 - 0.0002), exit_reason="LOCK",
                           stop_price=stop_final, stop_initial=entry * 0.99, lock_roe=lock, leverage=lev, pnl=18.0, roe=0.18,
                           mfe_price=max(b[1] for b in core[e:xbar + 1]), liq_price=entry * 0.97))
    # a plain stop-loss without a lock, on the same bars
    st.trade("B@15m", _rec(timeframe="15m", signal_ts=T0 + 10 * M15 - 1, entry_time=T0 + 11 * M15 + 10_000,
                           entry_price=core[11][0], exit_time=T0 + 14 * M15 + 3 * MIN, exit_price=core[11][0] * 0.999,
                           stop_price=core[11][0] * 0.999, stop_initial=core[11][0] * 0.999, side=1))
    reel = _reel_bars()
    rows = _minutes(reel, M5)
    for r in rows:
        r["symbol"] = "ETHUSDT"
    st.live_bars(rows)
    up, _mid, _dn = R.bollinger([b[3] for b in reel])
    re_e, re_x = 242, 250
    st.trade("REEL_H1@5m", _rec(strategy_id="REEL_H1", symbol="ETHUSDT", timeframe="5m", signal_ts=T0 + re_e * M5 - 1,
                                entry_time=T0 + re_e * M5 + 10_000, entry_price=reel[re_e][0] * 1.0002,
                                exit_time=T0 + re_x * M5 + 2 * MIN, exit_price=up[re_x - 1], exit_reason="TP",
                                stop_price=reel[240][2] - 0.05, stop_initial=reel[240][2] - 0.05, tp_price=up[re_x - 1],
                                pnl=30.0, roe=0.3))
    st.trade("RANDOM_1@5m", _rec(strategy_id="RANDOM_1", symbol="ETHUSDT", timeframe="5m", signal_ts=T0 + 250 * M5 - 1,
                                 entry_time=T0 + 250 * M5 + 10_000, entry_price=reel[250][0], exit_time=T0 + 255 * M5,
                                 exit_price=reel[255][0], exit_reason="TIME", stop_price=reel[250][0] * 0.99,
                                 stop_initial=reel[250][0] * 0.99, tp_price=reel[250][0] * 1.01))
    for k in range(48):                                   # equity every hour for two accounts
        st.equity("A@15m", T0 + k * 3_600_000, 5000.0 + 10 * k, 0.0)
        if k >= 10:
            st.equity("B@15m", T0 + k * 3_600_000, 5000.0 - 5 * k, 0.0)
    st.commit()
    st.conn.close()
    return db


def _client(db, candles=None):
    app = FastAPI()
    R.register(app, SimpleNamespace(data=Data(db), db=db, candles=candles))
    return TestClient(app)


def _ids(db):
    import sqlite3
    c = sqlite3.connect(db)
    out = {a: i for i, a in c.execute("SELECT id, account_id FROM trades")}
    c.close()
    return out


# ---------------------------------------------------------------- pure pieces
def test_minutes_become_timeframe_bars():
    rows = [(0, 1, 2, 0.5, 1.5), (60_000, 1.5, 3, 1, 2), (120_000, 2, 2.2, 1.9, 2.1), (900_000, 5, 6, 4, 5.5)]
    b = R.bars_from_minutes(rows, 900_000)
    assert b == [[0, 1.0, 3.0, 0.5, 2.1, 3], [900_000, 5.0, 6.0, 4.0, 5.5, 1]]


def test_bollinger_is_the_population_band_and_sma_waits_for_its_bars():
    xs = [float(i % 7) for i in range(40)]
    up, mid, dn = R.bollinger(xs)
    assert up[18] is None and up[19] is not None
    w = xs[20:40]
    m = sum(w) / 20
    sd = math.sqrt(sum((x - m) ** 2 for x in w) / 20)
    assert mid[39] == pytest.approx(m) and up[39] == pytest.approx(m + 2 * sd) and dn[39] == pytest.approx(m - 2 * sd)
    ma = R.sma(xs, 10)
    assert ma[8] is None and ma[9] == pytest.approx(sum(xs[:10]) / 10) and ma[39] == pytest.approx(sum(xs[30:]) / 10)


def test_lock_steps_end_exactly_at_the_recorded_lock_and_never_go_down():
    spec = v3_settings().ladder
    bars = [[0, 100, 100.1, 99.9, 100]] + [[i, 100 + 0.25 * i, 100.3 + 0.25 * i, 99.9 + 0.25 * i, 100.25 + 0.25 * i] for i in range(1, 12)]
    stop = roe_price(1, 100.0, 30, 0.25, RT)
    steps = R.lock_steps(1, 100.0, 30, bars, 0, 11, 0.25, stop, spec)
    levels = [s["level"] for s in steps]
    assert levels == sorted(levels) and levels[-1] == 0.25 and steps[-1]["price"] == pytest.approx(stop, rel=1e-6)
    assert levels[0] == pytest.approx(0.10) and all(s["rebuilt"] for s in steps)
    assert R.lock_steps(1, 100.0, 30, bars, 0, 11, None, stop, spec) == []
    # the bars never reached the recorded lock (1m vs bar data): the record still ends the steps
    flat = [[i, 100, 100.05, 99.95, 100] for i in range(5)]
    s2 = R.lock_steps(1, 100.0, 30, flat, 0, 4, 0.10, roe_price(1, 100.0, 30, 0.10, RT), spec)
    assert len(s2) == 1 and s2[0]["level"] == 0.10
    # a short locks below its entry
    short = [[i, 100 - 0.25 * i, 100.1 - 0.25 * i, 99.7 - 0.25 * i, 99.75 - 0.25 * i] for i in range(10)]
    s3 = R.lock_steps(-1, 100.0, 30, short, 0, 9, 0.15, roe_price(-1, 100.0, 30, 0.15, RT), spec)
    assert s3 and all(s["price"] < 100.0 for s in s3)


# ---------------------------------------------------------------- the route
def test_a_core_trade_replays_on_the_bars_the_bot_stepped_on(world):
    c = _client(world, candles=lambda *a: pytest.fail("live_bars cover it: no Binance fetch"))
    tid = _ids(world)["A@15m"]
    t0 = time.perf_counter()
    r = c.get(f"/api/v4/replay/{tid}")
    ms = (time.perf_counter() - t0) * 1000
    assert r.status_code == 200
    d = r.json()
    assert len(r.content) < 150_000 and ms < 300
    assert d["source"] == "live_bars" and d["fit"] is True and d["tf"] == "15m" and d["exits"] == "house"
    assert d["account"]["account_id"] == "A@15m" and d["account"]["group"] == "core"
    n = len(d["bars"])
    assert n > 40 and all(len(b) == 5 for b in d["bars"])
    assert [b[0] for b in d["bars"]] == sorted(b[0] for b in d["bars"])          # oldest first, seconds
    i = d["idx"]
    assert i["signal"] == i["entry"] - 1 and i["exit"] > i["entry"]
    assert d["bars"][i["entry"]][0] * 1000 <= d["trade"]["entry_time"] < d["bars"][i["entry"]][0] * 1000 + M15
    kinds = [e["kind"] for e in d["events"]]
    assert kinds[0] == "signal" and kinds[1] == "entry" and kinds[-1] == "exit" and "lock" in kinds
    steps = d["steps"]
    assert [s["level"] for s in steps] == sorted(s["level"] for s in steps)
    assert [s["level"] for s in steps] == pytest.approx([0.10, 0.15, 0.20]) and steps[-1]["level"] == pytest.approx(0.20) and steps[-1]["price"] == pytest.approx(d["levels"]["stop_final"], rel=1e-6)
    assert all(i["entry"] <= s["bar"] <= i["exit"] for s in steps) and all(s["rebuilt"] for s in steps)
    assert d["levels"]["lock_start"] > d["trade"]["entry_price"] and d["ladder"]["first"] == pytest.approx(0.10)
    assert d["lines"] == {} and d["reel_bars"] is None
    assert "NaN" not in r.text and "Infinity" not in r.text


def test_a_stop_loss_without_a_lock_has_no_steps(world):
    d = _client(world).get(f"/api/v4/replay/{_ids(world)['B@15m']}").json()
    assert d["steps"] == [] and [e["kind"] for e in d["events"]] == ["signal", "entry", "exit"]
    assert d["events"][-1]["reason"] == "SL"


def test_the_reel_replays_on_5m_with_its_band_target_200_line_and_setup(world):
    d = _client(world).get(f"/api/v4/replay/{_ids(world)['REEL_H1@5m']}").json()
    assert d["tf"] == "5m" and d["exits"] == "reel" and d["ladder"] is None and d["reel_bars"] == 96
    n = len(d["bars"])
    for k in ("bb_up", "bb_dn", "ma200", "target"):
        assert len(d["lines"][k]) == n
    assert all(v is not None for v in d["lines"]["ma200"])            # the warm-up bars before the window made it
    i = d["idx"]
    tgt = d["lines"]["target"]
    assert all(v is None for v in tgt[:i["entry"]]) and all(v is not None for v in tgt[i["entry"]:i["exit"] + 1])
    assert tgt[i["entry"] + 1] == pytest.approx(d["lines"]["bb_up"][i["entry"]], rel=1e-6)   # the previous bar's band
    ev = {e["kind"]: e for e in d["events"]}
    assert ev["breach"]["bar"] == i["signal"] - 1 and ev["signal"]["how"] == "reel" and ev["signal"]["ok"] is True
    assert ev["signal"]["filter"] is True and ev["breach"]["rebuilt"] is True
    assert d["levels"]["time_exit_ts"] == (d["trade"]["entry_time"] // M5) * M5 + 96 * M5
    assert d["steps"] == [] and ev["exit"]["reason"] == "TP"


def test_a_5m_coin_flip_uses_the_reel_exits_and_says_it_is_a_coin_flip(world):
    d = _client(world).get(f"/api/v4/replay/{_ids(world)['RANDOM_1@5m']}").json()
    assert d["tf"] == "5m" and d["exits"] == "reel"
    sig = [e for e in d["events"] if e["kind"] == "signal"]
    assert sig and sig[0]["how"] == "flip" and not any(e["kind"] == "breach" for e in d["events"])


def test_unknown_or_bad_ids(world):
    c = _client(world)
    assert c.get("/api/v4/replay/999999").status_code == 404
    assert c.get("/api/v4/replay/abc").status_code == 422


def test_binance_fallback_is_one_fetch_per_trade_and_flags_bars_that_do_not_match(tmp_path):
    db = str(tmp_path / "p.db")
    st = Store3(db)
    st.add_account("A@15m", "A", "15m", "strategy", T0, "v", None, {})
    now = int(time.time() * 1000)
    et = now - 10 * M15
    st.trade("A@15m", _rec(entry_time=et, exit_time=et + 3 * M15, signal_ts=et - 10_000, entry_price=100.0, exit_price=99.0))
    st.trade("A@15m", _rec(entry_time=now - 2000 * M15, exit_time=now - 1990 * M15, entry_price=100.0))   # too old
    st.commit()
    st.conn.close()
    calls = []

    def candles(sym, iv, limit):
        calls.append((sym, iv, limit))
        last = now - now % M15
        return [{"time": (last - k * M15) // 1000, "open": 100.0, "high": 100.5, "low": 98.8, "close": 99.5}
                for k in range(int(limit) - 1, -1, -1)]
    c = _client(db, candles=candles)
    a = c.get("/api/v4/replay/1").json()
    assert a["source"] == "binance" and a["bars"] and a["fit"] is True and len(calls) == 1
    assert calls[0][1] == "15m" and calls[0][2] <= R.CANDLE_LIMIT
    c.get("/api/v4/replay/1")
    assert len(calls) == 1                                  # cached
    old = c.get("/api/v4/replay/2").json()
    assert old["bars"] == [] and old["source"] is None and old["fit"] is None and len(calls) == 1   # beyond 1,500 bars

    def far(sym, iv, limit):                                 # bars from another price level: flagged, not trusted
        return [dict(b, open=b["open"] * 2, high=b["high"] * 2, low=b["low"] * 2, close=b["close"] * 2) for b in candles(sym, iv, limit)]
    assert _client(db, candles=far).get("/api/v4/replay/1").json()["fit"] is False

    def broken(*a):
        raise OSError("binance down")
    v = _client(db, candles=broken).get("/api/v4/replay/1").json()
    assert v["bars"] == [] and v["trade"]["id"] == 1 and v["events"] == []


def test_a_long_trade_is_shown_on_a_larger_timeframe(tmp_path):
    db = str(tmp_path / "p.db")
    st = Store3(db)
    st.add_account("A@15m", "A", "15m", "strategy", T0, "v", None, {})
    st.trade("A@15m", _rec(entry_time=T0 + 10_000, exit_time=T0 + 300 * M15, entry_price=100.0))
    st.commit()
    st.conn.close()
    d = _client(db).get("/api/v4/replay/1").json()
    assert d["tf"] == "30m" and d["tf_own"] == "15m" and d["stepped"] is True


def test_the_route_never_writes(world):
    for suffix in ("", "-wal", "-shm"):
        p = world + suffix
        if os.path.exists(p):
            os.chmod(p, stat.S_IRUSR)
    try:
        c = _client(world)
        assert c.get(f"/api/v4/replay/{_ids(world)['A@15m']}").status_code == 200
        assert c.get("/api/v4/replay/sparks?ids=A@15m").status_code == 200
    finally:
        for suffix in ("", "-wal", "-shm"):
            p = world + suffix
            if os.path.exists(p):
                os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)


# ---------------------------------------------------------------- sparks
def test_sparks_share_one_time_axis_and_only_the_asked_rows(world):
    c = _client(world)
    v = c.get("/api/v4/replay/sparks?ids=A@15m,B@15m,nobody").json()
    assert v["points"] == R.SPARK_POINTS and set(v["series"]) == {"A@15m", "B@15m", "nobody"}
    a, b = v["series"]["A@15m"], v["series"]["B@15m"]
    assert len(a) == len(b) == R.SPARK_POINTS and a[0] == 5000.0 and a[-1] == pytest.approx(5000.0 + 10 * 47)
    assert b[0] is None and b[-1] == pytest.approx(5000.0 - 5 * 47)        # nothing before its first row
    assert all(x is None for x in v["series"]["nobody"])
    many = ",".join(f"X{k}@15m" for k in range(60))
    assert len(c.get(f"/api/v4/replay/sparks?ids={many}").json()["series"]) == R.SPARK_MAX_IDS
    assert len(json.dumps(v)) < 20_000


def test_empty_database(tmp_path):
    db = str(tmp_path / "empty.db")
    Store3(db).conn.close()
    c = _client(db)
    assert c.get("/api/v4/replay/1").status_code == 404
    v = c.get("/api/v4/replay/sparks?ids=A@15m").json()
    assert v["series"] == {} or all(x is None for x in v["series"].get("A@15m", []))
    assert c.get("/api/v4/replay/sparks").json()["series"] == {}


def test_the_routes_sit_behind_the_login(world):
    app = create_app(world, hash_password("correct horse battery"), b"x" * 32,
                     candles=lambda *a: [])
    c = TestClient(app)
    assert c.get("/api/v4/replay/1").status_code == 401
    assert c.get("/api/v4/replay/sparks?ids=A@15m").status_code == 401
    assert c.post("/api/login", json={"password": "correct horse battery"}).status_code == 200
    assert c.get(f"/api/v4/replay/{_ids(world)['A@15m']}").json()["source"] == "live_bars"


# ---------------------------------------------------------------- the page's words (honesty captions)
def _static(*parts):
    root = os.path.join(os.path.dirname(__file__), "..", "paperbot", "dash", "static", "v4")
    with open(os.path.join(root, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_the_replay_page_says_what_it_is_and_what_was_rebuilt():
    js = _static("screens", "replay.js") + _static("screens", "replay-story.js")
    assert "/api/v4/replay/${id}" in js and "ui.assume(" in js
    assert "한 건으로 매매법이 좋다·나쁘다를 말할 수 없습니다" in js and "판정은 30일째" in js
    assert "봉으로 다시 맞춘 것" in js and "봉으로 다시 찾음" in js          # rebuilt lock times / reel setup
    assert "거래 가격과 맞지 않습니다" in js                                 # fit false
    assert "visibilitychange" in js                                        # the player stops when hidden
    for word in ("▶ 재생", "❚❚ 멈춤", "1x", "2x", "4x", "손절에 닿아 청산", "손절선을"):
        assert word in js
    pos = _static("screens", "positions.js") + _static("screens", "positions-kit.js")
    assert 'ctx.href("replay", String(t.id))' in pos and "다시보기" in pos


def test_motion_helpers_respect_reduced_motion_and_hidden_pages():
    m = _static("core", "motion.js")
    for fn in ("flash", "fadeIn", "drawIn", "ring", "floatChip", "beat"):
        body = m[m.index(f"export function {fn}("):]
        body = body[:body.index("\n}\n")]
        assert "still()" in body, fn                                        # reduced motion or a hidden page: nothing
    assert "document.hidden" in m and "prefers-reduced-motion" in m
    b = _static("screens", "board-motion.js")
    assert 'a.kind === "ds200"' in b and "/api/v4/replay/sparks" in b       # DeepSeek rows: no per-account lines
