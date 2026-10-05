"""신호 레이더 (fill-radar): /api/v4/radar and /api/v4/radar/strategy/<name> (dash/more/radar.py) and the page pieces.

- the radar gives the 36 with a view, each side's {on, of, names} exactly as /api/strategy/<name> shows them;
- one bar fetch per (timeframe, coin) per closed bar, shared by all 36; no fetch while the bar is still the newest;
- ``fired`` only from a real signal_log row on that bar; bad timeframe / coin -> 400, a non-36 name -> 404;
- the matrix fills at most MAX_NEW_CELLS new cells per call and says how many are pending;
- the JS sort / state logic (node) and the honest wording; wiring greps; tokens-only CSS.
"""
import json
import os
import re
import shutil
import subprocess
import time

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.dash.app import create_app, hash_password  # noqa: E402
from paperbot.dash.more import radar as R  # noqa: E402
from test_dash import SECRET, _store  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "paperbot", "dash", "static", "v4")
SCR = os.path.join(V4, "screens")
PW = "radar radar radar"


def _read(*p):
    with open(os.path.join(*p), encoding="utf-8") as fh:
        return fh.read()


def _frames_now(calls):
    """Closed 1h-style bars ending on the last closed bar of each timeframe (so a cell stays fresh)."""
    import pandas as pd
    from paperbot import sweepsig
    base = sweepsig.lib().synth_ohlcv(1600, "1h", seed=5, start="2026-01-01")[["ts", "open", "high", "low", "close", "volume"]]
    step = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400}

    def frames(sym, tf, n):
        calls.append((sym, tf, n))
        df = base.tail(min(n, len(base))).reset_index(drop=True).copy()
        end = int(time.time()) // step[tf] * step[tf] - step[tf]
        df["ts"] = pd.to_datetime([(end - (len(df) - 1 - k) * step[tf]) * 1000 for k in range(len(df))], unit="ms", utc=True)
        return df
    return frames


@pytest.fixture()
def client(tmp_path):
    db = str(tmp_path / "p.db")
    _store(db)
    calls = []
    c = TestClient(create_app(db, hash_password(PW), SECRET, frames=_frames_now(calls)))
    assert c.get("/api/v4/radar").status_code == 401                 # behind the login like every /api route
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    return c, calls, db


def test_radar_shape_matches_strategy_view_and_fetches_once(client):
    c, calls, _db = client
    r = c.get("/api/v4/radar", params={"tf": "1h", "symbol": "ETHUSDT"})
    assert r.status_code == 200
    d = r.json()
    assert d["ready"] and d["tf"] == "1h" and d["symbol"] == "ETHUSDT" and d["n"] == len(d["rows"]) == 36
    assert d["next_close"] - d["bar_close"] == 3_600_000
    assert {(s, tf) for s, tf, _n in calls} == {("ETHUSDT", "1h")}      # one fetch shared by all 36
    row = next(x for x in d["rows"] if x["strategy"] == "S2_ST_ROC")
    assert row["ko"] and set(row) >= {"long", "short", "fired", "left"}
    for side in ("long", "short"):
        s = row[side]
        assert s["of"] == len(s["names"]) and s["on"] == sum(1 for x in s["names"] if x["on"])
    v = c.get("/api/strategy/S2_ST_ROC", params={"tf": "1h", "symbol": "ETHUSDT"}).json()
    assert [x["name"] for x in v["conditions"]["long"]] == [x["name"] for x in row["long"]["names"]]
    assert [x["on"] for x in v["conditions"]["short"]] == [x["on"] for x in row["short"]["names"]]
    assert v["bar_close"] == d["bar_close"]
    keys = [R.closeness(x) for x in d["rows"]]
    assert keys == sorted(keys)                                        # closest to firing first
    n = len(calls)
    assert c.get("/api/v4/radar", params={"tf": "1h", "symbol": "ETHUSDT"}).json()["rows"] == d["rows"]
    assert len(calls) == n                                             # the bar is still the newest: no fetch


def test_radar_rejects_and_matrix(client):
    c, calls, _db = client
    assert c.get("/api/v4/radar", params={"tf": "5m"}).status_code == 400
    assert c.get("/api/v4/radar", params={"symbol": "XRPUSDT"}).status_code == 400
    assert c.get("/api/v4/radar/strategy/F9_FVG").status_code == 404   # DeepSeek: not on the radar
    m = c.get("/api/v4/radar/strategy/S2_ST_ROC").json()
    assert m["tfs"] == ["15m", "30m", "1h", "4h"] and len(m["coins"]) == 6 and len(m["cells"]) == 24
    ready = [x for x in m["cells"] if x["ready"]]
    assert len(ready) == R.MAX_NEW_CELLS and m["pending"] == 24 - R.MAX_NEW_CELLS
    assert all(set(x["long"]) == {"on", "of"} for x in ready)
    for _ in range(10):
        m = c.get("/api/v4/radar/strategy/S2_ST_ROC").json()
        if not m["pending"]:
            break
    assert not m["pending"] and all(x["ready"] for x in m["cells"])
    assert len({(s, tf) for s, tf, _n in calls}) == 24                # one fetch per cell


def test_fired_only_from_signal_log(client, monkeypatch):
    c, _calls, db = client
    d = c.get("/api/v4/radar", params={"tf": "4h", "symbol": "SOLUSDT"}).json()
    assert all(x["fired"] is None for x in d["rows"])
    from paperbot.store3 import Store3
    st = Store3(db)
    st.log_signals([{"bar_close": d["bar_close"], "timeframe": "4h", "strategy": "N24_DMI", "symbol": "SOLUSDT", "side": -1,
                     "atr": 1.0, "ref_price": 1.0, "ref_time": d["bar_close"] + 4000, "delay_ms": 4000, "status": "SUBMITTED"}])
    st.commit()
    st.close()
    monkeypatch.setattr(R, "FIRED_S", 0.0)                            # the signal landed after the bar was computed
    d2 = c.get("/api/v4/radar", params={"tf": "4h", "symbol": "SOLUSDT"}).json()
    hit = next(x for x in d2["rows"] if x["strategy"] == "N24_DMI")
    assert hit["fired"] == {"long": False, "short": True} and d2["rows"][0]["strategy"] == "N24_DMI"
    assert sum(1 for x in d2["rows"] if x["fired"]) == 1
    rd = R.Radar(lambda *a: None, db)
    assert rd.fired_on("4h", "SOLUSDT", d["bar_close"] - 14_400_000, d["bar_close"]) == {"N24_DMI": [-1]}
    assert rd.fired_on("4h", "BTCUSDT", d["bar_close"] - 14_400_000, d["bar_close"]) == {}


def test_pure_helpers():
    row = {"long": {"on": 2, "of": 3}, "short": {"on": 0, "of": 3}}
    assert R.left_of(row) == 1 and R.left_of({"long": {"of": 0}, "short": {"of": 0}}) is None
    assert R.closeness({**row, "fired": {"long": True}}) < R.closeness(row)


def _node(body):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    js = os.path.abspath(os.path.join(SCR, "strategies-radar.js"))
    sig = os.path.abspath(os.path.join(SCR, "signals.js"))
    script = f"const R = await import('{js}'); const S = await import('{sig}');\n" + body
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_js_state_sort_and_heatmap():
    out = _node("""
const rows = [
  {strategy: "A", long: {on: 0, of: 3}, short: {on: 1, of: 3}},
  {strategy: "B", long: {on: 2, of: 3}, short: {on: 0, of: 3}},
  {strategy: "C", long: {on: 3, of: 3}, short: {on: 0, of: 3}},
  {strategy: "D", long: {on: 0, of: 3}, short: {on: 0, of: 3}, fired: {long: false, short: true}},
];
const sorted = rows.slice().sort(R.byClose).map((r) => r.strategy);
const st = rows.map((r) => R.stateOf(r));
const top = R.topCells([{symbol: "BTCUSDT", tf: "1h", rows}, {symbol: "ETHUSDT", tf: "1h", rows: rows.slice(0, 2)}], 3);
const now = Date.UTC(2026, 9, 6, 0, 0);
const sig = [{bar_close: now - 1000, timeframe: "15m", symbol: "BTCUSDT", side: 1, status: "SUBMITTED"},
  {bar_close: now - 2000, timeframe: "15m", symbol: "BTCUSDT", side: -1, status: "LATE"},
  {bar_close: now - 90000000, timeframe: "1h", symbol: "ETHUSDT", side: 1, status: "SUBMITTED"}];
const m = S.heatMap(sig, now);
console.log(JSON.stringify({sorted, st, top: top.map((r) => r.strategy + "@" + r.symbol), onOf: R.onOf(rows[1]),
  cell: m.cells["BTCUSDT|15m"], n: m.n, eth: m.cells["ETHUSDT|1h"] || null, tfs: m.tfs, coins: m.coins.length, capped: m.capped}));
""")
    assert out["sorted"] == ["D", "C", "B", "A"]                       # logged signal, all on, one left, two left
    assert [s["key"] for s in out["st"]] == ["far", "one", "all", "fired"]
    assert out["st"][3]["ko"] == "신호!" and out["st"][2]["ko"] == "조건 모두 켜짐" and out["st"][1]["ko"] == "한 칸 남음"
    assert out["st"][3]["side"] == "short" and out["st"][1]["side"] == "long"
    assert out["top"] == ["D@BTCUSDT", "C@BTCUSDT", "B@BTCUSDT"]
    assert out["onOf"] == "롱 2/3 · 숏 0/3"
    assert out["cell"] == {"n": 2, "long": 1, "short": 1, "late": 1} and out["n"] == 2 and out["eth"] is None   # 24 h only
    assert out["tfs"] == ["15m", "30m", "1h", "4h"] and out["coins"] == 6 and out["capped"] is False


def test_wiring_and_honest_words():
    js = _read(SCR, "strategies-radar.js")
    assert "/api/v4/radar?tf=" in js and "/api/v4/radar/strategy/" in js
    assert "예측이 아닙니다" in js and "실제로 신호를 기록했을 때만" in js        # not a forecast; 신호! only from the log
    assert "준비 전" in js
    assert re.search(r'import \{radarCard\} from "\./strategies-radar\.js"', _read(SCR, "strategies-list.js"))
    assert "radarCard(ctx)" in _read(SCR, "strategies-list.js")
    det = _read(SCR, "strategies-detail.js")
    assert "radarMatrix(ctx, name, {pick: (tf, sym) => setChart(tf, sym)" in det and 'kind === "strategy"' in det
    sig = _read(SCR, "signals.js")
    assert "waitRoom(ctx)" in sig and "/api/signals?limit=1000" in sig
    assert '"radar"' in _read(HERE, "..", "paperbot", "dash", "more", "__init__.py")
    assert "frames=frames)" in _read(HERE, "..", "paperbot", "dash", "app.py")
    ro = _read(HERE, "..", "paperbot", "dash", "more", "radar.py")
    assert "mode=ro" in ro and "INSERT" not in ro.upper().replace("INSERTED", "")


def test_new_css_tokens_only():
    css = _read(SCR, "strategies-radar.css")
    sig = _read(SCR, "signals.css")
    new = css + sig[sig.index("fill-radar"):]
    for m in re.finditer(r"font-size:\s*([^;]+);", new):
        assert re.fullmatch(r"var\(--t-(xs|sm|md|lg|xl|2xl|led)\)", m.group(1).strip()), m.group(0)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", new)              # colours from tokens only
    js = _read(SCR, "strategies-radar.js")
    assert "fontSize" not in js and "font-size" not in js
