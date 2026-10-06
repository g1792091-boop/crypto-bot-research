"""분석 › 장세 스위치 (regime5y): the committed 5-year JSON's shape and honesty, the server module (the file as
committed; the paper trades by regime with a filling bar first, unknown when the bars do not reach), the routes, and
the page's static rules (the 36 only, the caveat words, the money caption, the coin-flip 참고 note, tokens only)."""
import json
import math
import os
import re
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from anasyn_world import build  # noqa: E402
from paperbot.dash import more as MORE  # noqa: E402
from paperbot.dash.more import regime5y as RG  # noqa: E402
from paperbot.dash.tools import regime5y as G  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENS = os.path.join(ROOT, "paperbot", "dash", "static", "v4", "screens")


def _read(name):
    with open(os.path.join(SCREENS, name), encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def doc():
    assert os.path.getsize(RG.DATA) < 2_000_000
    with open(RG.DATA, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- the committed 5-year file
def test_file_shape_and_counts(doc):
    assert doc["label"] == "설명용, 판정 아님" and doc["prereg"] == "docs/regime5y.md"
    cells, hd = doc["cells"], doc["head"]
    assert len(cells) == hd["cells"] == 144
    assert {c["tf"] for c in cells} == {"15m", "30m", "1h", "4h"}
    assert len({(c["s"], c["tf"]) for c in cells}) == 144
    st = [c["test"]["status"] for c in cells]
    assert st.count("tested") == hd["tested"] and st.count("small") == hd["small"] and st.count("norule") == hd["norule"]
    assert hd["survivors"] == sum(1 for c in cells if c["test"].get("survivor"))
    assert hd["survivors"] <= hd["bh_pass"] <= hd["tested"]
    assert hd["with_rule"] == sum(1 for c in cells if c.get("switch"))
    for c in cells:
        t = c["test"]
        if t.get("survivor"):
            assert t["bh"] and all(t["per"][k]["diff"] > 0 for k in ("a", "b"))
        if c["rule"]:
            assert 0 < len(c["rule"]) < 4 and set(c["rule"]) <= {"trend", "range", "shock", "normal"}
            assert set(c["switch"]) == {"a", "b"}
        else:
            assert "switch" not in c and t["status"] == "norule"
        # the rule was picked on the pick period: every chosen regime beat the pick mean with >= 30 trades there
        for k in c["rule"] or []:
            n, _w, m, _p = c["regimes"]["pick"][k]
            assert n >= G.MIN_PICK and m >= c["pick_mean"] - 1e-4          # both rounded to 4 places in the file


def test_file_has_no_nan_and_q_values_are_bh(doc):
    s = json.dumps(doc)
    assert "NaN" not in s and "Infinity" not in s
    tested = [c["test"] for c in doc["cells"] if c["test"]["status"] == "tested"]
    q = G.bh([t["p"] for t in tested])                   # from the rounded p: equal up to the rounding x m / rank
    assert all(abs(a - t["q"]) < 1e-3 for a, t in zip(q, tested))
    assert all(t["q"] >= t["p"] - 1e-9 for t in tested)


def test_periods_and_regimes_are_the_preregistered_ones(doc):
    assert [(p["key"], p["from"], p["to"]) for p in doc["periods"]] == [(k, a, b) for k, a, b in G.PERIODS]
    d = doc["defs"]
    assert (d["adx_trend"], d["adx_range"], d["slope_min"], d["vol_q"], d["vol_days"]) == (25.0, 20.0, 0.5, 0.8, 365)
    with open(os.path.join(ROOT, "docs", "regime5y.md"), encoding="utf-8") as f:
        pre = f.read()
    for words in ("ADX ≥ 25", "ADX < 20", "80번째 백분위수", "2021-07-01 ~ 2022-12-31", "q = 0.05", "30건 이상"):
        assert words in pre
    for tf, coins in doc["live_vol_q"].items():
        assert set(coins) == set(G.COINS) and all(v and 0 < v < 0.2 for v in coins.values())


# ---------------------------------------------------------------- the server module
def test_load_doc_missing_file(tmp_path):
    d = RG.load_doc(str(tmp_path / "none.json"))
    assert d["unavailable"] and d["note"]


def test_signal_open_and_coin_names():
    step = RG.TF_MS["15m"]
    t0 = 1_790_000_000_000 // step * step
    assert RG.signal_open({"signal_ts": t0 + step - 1, "entry_time": t0 + step}, "15m") == t0
    assert RG.signal_open({"entry_time": t0 + step}, "15m") == t0
    assert RG.signal_open({}, "15m") is None and RG.signal_open({"signal_ts": 1}, "5m") is None
    assert RG.coin_of("dogeusdt") == "DOGEUSD" and RG.coin_of("BTCUSD") == "BTCUSD"


def _bars(n=600, seed=1, step_s=900, end_s=1_790_000_000):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    end = end_s // step_s * step_s
    return [{"time": end - (n - 1 - i) * step_s, "open": float(c[i - 1] if i else c[0]), "high": float(c[i] * 1.002),
             "low": float(c[i] * 0.998), "close": float(c[i])} for i in range(n)]


def test_bar_codes_settle_and_fixed_threshold():
    rows = _bars()
    codes = RG.bar_codes(rows, 0.5)                     # a line no bar reaches: never 급변장
    v = list(codes.values())
    assert all(k == G.UNKNOWN for k in v[:RG.SETTLE_BARS])
    assert G.SHOCK not in v and set(v[RG.SETTLE_BARS:]) <= {G.TREND, G.RANGE, G.NORMAL}
    low = RG.bar_codes(rows, 0.0)                       # every bar at or above the line: 급변장 after the warm-up
    assert set(list(low.values())[RG.SETTLE_BARS:]) == {G.SHOCK}
    none = RG.bar_codes(rows, None)                     # no threshold for the coin: 모름, never a guess
    assert set(none.values()) == {G.UNKNOWN}
    assert RG.bar_codes([], 0.01) == {}
    # the live label is the study's formula: same as label_codes on the same bars
    h = np.array([r["high"] for r in rows]); lo = np.array([r["low"] for r in rows]); c = np.array([r["close"] for r in rows])
    want = G.label_codes(*G.indicators(h, lo, c), 0.004)
    got = RG.bar_codes(rows, 0.004)
    assert list(got.values())[RG.SETTLE_BARS:] == want[RG.SETTLE_BARS:].tolist()


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    db = str(tmp_path_factory.mktemp("regime") / "paper3.db")
    info = build(db, days=30)
    return {"db": db, **info}


def _candles_for(world_end_ms):
    def candles(symbol, interval, limit):
        step = RG.TF_MS[interval] // 1000
        return _bars(limit, seed=hash((symbol, interval)) & 0xffff, step_s=step, end_s=world_end_ms // 1000 + step)
    return candles


def test_live_view_rows_and_waiting(world, doc):
    calls = []

    def candles(symbol, interval, limit):
        calls.append((symbol, interval))
        return _candles_for(world["now"])(symbol, interval, limit)
    d = RG.live_view(world["db"], candles, doc, world["now"])
    assert d["trades"] >= RG.LIVE_MIN and not d.get("waiting")
    rows = {r["key"]: r for r in d["rows"]}
    assert set(rows) == {"trend", "range", "shock", "normal", "unknown"}
    assert sum(r["group"][0] for r in d["rows"]) == d["trades"]
    assert sum(r["coin_flips"][0] for r in d["rows"]) == d["flip_trades"]
    known = sum(r["group"][0] for k, r in rows.items() if k != "unknown")
    assert known > 0                                     # the fetched bars reach the recent trades
    for r in d["rows"]:
        n, w, m, p = r["group"]
        if n:
            assert 0 <= w <= 1 and m is not None and p is not None
    assert calls and len(calls) == len(set(calls))       # one fetch per coin and timeframe
    # bars that fail to arrive: those trades are 모름, never a 500
    def broken(symbol, interval, limit):
        raise OSError("down")
    b = RG.live_view(world["db"], broken, doc, world["now"])
    assert b["fetch_failed"] and {r["key"]: r for r in b["rows"]}["unknown"]["group"][0] == b["trades"]


def test_live_view_waits_before_enough_trades(tmp_path, doc):
    db = str(tmp_path / "paper3.db")
    build(db, days=1, hours_into_last=1)
    called = []
    d = RG.live_view(db, lambda *a: called.append(a) or [], doc, 0)
    assert d["trades"] < RG.LIVE_MIN
    assert d["waiting"] and "rows" not in d and not called           # nothing is fetched before the bar is full
    assert RG.live_view(str(tmp_path / "none.db"), None, doc, 0)["error"]


def test_routes_answer(world):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    assert "regime5y" in MORE.MODULES
    app = fastapi.FastAPI()
    RG._count.update(at=0.0, val=None)
    done = MORE.register_all(app, data=None, rooms=None, db=world["db"], daily_db=None, agents_db=None,
                             checkpoint_db=None, candles=_candles_for(world["now"]), frames=None)
    assert done["regime5y"]["routes"] == ["/api/v4/regime5y", "/api/v4/regime5y/live"]
    c = TestClient(app)
    d = c.get("/api/v4/regime5y").json()
    assert d["head"]["cells"] == 144 and d["label"] == "설명용, 판정 아님"
    live = None
    for _ in range(40):
        live = c.get("/api/v4/regime5y/live").json()
        if not live.get("pending"):
            break
    assert live["need"] == RG.LIVE_MIN and ("rows" in live or live.get("waiting"))


# ---------------------------------------------------------------- the page (static rules)
def test_tab_is_registered_core_only():
    a = _read("analysis.js")
    m = re.search(r'\{id: "regime", label: "장세 스위치", path: "/api/v4/regime5y", render: RG\.regime, groups: "core"', a)
    assert m and 'import * as RG from "./analysis-regime.js";' in a


def test_page_words_and_safety():
    js = _read("analysis-regime.js")
    for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "DOMParser", "eval(", "toLocaleString", "Intl.NumberFormat"):
        assert bad not in js
    for words in ("설명용, 판정 아님", "잠긴 매매법 36개의 규칙은 이 결과로 바뀌지 않습니다", "과최적화", "ui.refNote(env.verdictTs)",
                  "ui.assume(", "차이 없음", "남음", "progressBar("):
        assert words in js
    css = _read("analysis-regime.css")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and not re.search(r"font-size:\s*\d", css)
    assert all("var(--t-" in line for line in css.splitlines() if "font-size" in line)
    for m in re.finditer(r"font:\s*([^;]+);", css):
        assert "var(--t-" in m.group(1) or m.group(1).strip() == "inherit"
