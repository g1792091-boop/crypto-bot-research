"""거래 화면 채우기 (fill-trade): /api/v4/flowlive and /api/v4/flowlive/liq over fixture flow.db / liq.db (read-only,
missing files say so, never zero), the Korean ENTRY / EXIT alert lines (DeepSeek and coin flips without money), the
market / positions / chart / alerts wiring, and the pure helpers of market-live.js and positions-risk.js in node."""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot import flow as F  # noqa: E402
from paperbot.dash.app import create_app, hash_password  # noqa: E402
from paperbot.dash.more import flowlive  # noqa: E402
from paperbot.liqstream import SCHEMA as LIQ_SCHEMA  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_dash import SECRET, _store  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
PW = "correct horse battery"
H = 3_600_000


def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as f:
        return f.read()


def _flow_db(path, last):
    c = sqlite3.connect(path)
    c.executescript(F._schema())
    for k in range(24 * 12, -1, -1):            # 24 h of 5-minute rows for BTC; OI grows 10 % over the day
        ts = last - k * 300_000
        oi = 1e9 * (1 + 0.1 * (24 * 12 - k) / (24 * 12))
        c.execute("INSERT INTO oi5m VALUES (?,?,?,?,?)", ("BTCUSDT", ts, oi / 6e4, oi, ts))
        ls = 2.0 if k == 0 else 1.2
        c.execute("INSERT INTO ls_global5m VALUES (?,?,?,?,?,?)", ("BTCUSDT", ts, ls, ls / (1 + ls), 1 / (1 + ls), ts))
        c.execute("INSERT INTO ls_top_position5m VALUES (?,?,?,?,?,?)", ("BTCUSDT", ts, 1.1, 0.52, 0.48, ts))
        c.execute("INSERT INTO taker5m VALUES (?,?,?,?,?,?)", ("BTCUSDT", ts, 1.0, 300.0, 200.0, ts))
        c.execute("INSERT INTO premium5m VALUES (?,?,?,?,?,?,?)", ("BTCUSDT", ts, 0, 0, 0, 0.0002, ts))
    c.commit()
    c.close()


def _liq_db(path, now):
    c = sqlite3.connect(path)
    c.executescript(LIQ_SCHEMA)
    rows = [(now - 10 * 60_000, "BTCUSDT", "SELL", 1.0, 60000.0),       # long liquidated 60k, inside 1 h
            (now - 5 * H, "BTCUSDT", "BUY", 2.0, 60000.0),               # short 120k, inside 24 h only
            (now - 30 * H, "BTCUSDT", "SELL", 9.0, 60000.0),             # older than 24 h: not counted
            (now - 20 * 60_000, "ETHUSDT", "BUY", 3.0, 2000.0)]
    for ts, s, side, q, p in sorted(rows):           # the recorder appends in time order
        c.execute("INSERT INTO liq VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (ts, ts, s, side, "LIMIT", "IOC", q, p, p, "FILLED", q, q, ts))
    c.commit()
    c.close()


# ---------------------------------------------------------------- server: flow.db
def test_flow_live_reads_the_newest_rows_and_changes(tmp_path):
    now = int(time.time() * 1000)
    last = now // 300_000 * 300_000 - 40 * 60_000
    _flow_db(str(tmp_path / "flow.db"), last)
    d = flowlive.flow_live(str(tmp_path / "flow.db"), now)
    assert d["ready"] is True and d["as_of"] == last
    btc = next(x for x in d["coins"] if x["symbol"] == "BTCUSDT")
    assert btc["oi_usd"] == pytest.approx(1.1e9, rel=1e-6)
    assert btc["oi_chg_24h"] == pytest.approx(0.1, rel=1e-3) and 0 < btc["oi_chg_1h"] < 0.01
    assert btc["ls_global"] == 2.0 and btc["ls_global_24h"] == 1.2 and btc["ls_top"] == 1.1
    assert btc["taker_1h"] == 1.5 and btc["premium"] == 0.0002
    assert 24 <= len(btc["oi_series"]) <= 26 and len(btc["ls_series"]) == len(btc["oi_series"])
    assert btc["hints"] == ["long_crowd", "oi_jump", "taker_buy"]
    eth = next(x for x in d["coins"] if x["symbol"] == "ETHUSDT")
    assert "ts" not in eth and "oi_usd" not in eth                     # no rows: nothing made up
    assert set(d["hint_rules"]) == set(flowlive.HINT_RULES)


def test_flow_live_without_the_file_is_not_ready(tmp_path):
    d = flowlive.flow_live(str(tmp_path / "flow.db"), int(time.time() * 1000))
    assert d["ready"] is False and "flow.db" in d["why"]
    assert not (tmp_path / "flow.db").exists()                         # read-only: never created


def test_hints_follow_the_published_thresholds():
    assert flowlive.hints({"ls_global": 0.6, "oi_chg_1h": -0.04, "taker_1h": 0.8}) == ["short_crowd", "oi_drop", "taker_sell"]
    assert flowlive.hints({"ls_global": 1.0, "oi_chg_1h": 0.01, "oi_chg_24h": 0.02, "taker_1h": 1.0}) == []
    assert flowlive.hints({}) == []


# ---------------------------------------------------------------- server: liq.db
def test_liq_board_counts_1h_and_24h_by_side(tmp_path):
    now = int(time.time() * 1000)
    _liq_db(str(tmp_path / "liq.db"), now)
    d = flowlive.liq_board(str(tmp_path / "liq.db"), now)
    assert d["ready"] is True and d["stale"] is False and d["partial_24h"] is False
    btc = next(x for x in d["coins"] if x["symbol"] == "BTCUSDT")
    assert btc["h1"] == {"long_usd": 60000.0, "short_usd": 0.0, "long_n": 1, "short_n": 0}
    assert btc["h24"]["long_usd"] == 60000.0 and btc["h24"]["short_usd"] == 120000.0
    assert btc["biggest"]["usd"] == 120000.0 and btc["biggest"]["liquidated"] == "short"
    assert [r["symbol"] for r in d["latest"]][:2] == ["BTCUSDT", "ETHUSDT"] and len(d["latest"]) <= 5
    sol = next(x for x in d["coins"] if x["symbol"] == "SOLUSDT")
    assert sol["biggest"] is None and sol["h24"]["long_n"] == 0


def test_liq_board_stale_and_missing(tmp_path):
    now = int(time.time() * 1000)
    _liq_db(str(tmp_path / "liq.db"), now - 5 * H)                     # newest row 5 h old: the recorder stopped
    assert flowlive.liq_board(str(tmp_path / "liq.db"), now)["stale"] is True
    d = flowlive.liq_board(str(tmp_path / "none.db"), now)
    assert d["ready"] is False and "liq.db" in d["why"]


def test_endpoints_are_registered_behind_the_login(tmp_path):
    db = str(tmp_path / "paper3.db")
    _store(db).close()
    now = int(time.time() * 1000)
    c = TestClient(create_app(db, hash_password(PW), SECRET))
    assert c.get("/api/v4/flowlive", follow_redirects=False).status_code in (302, 307, 401)
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    assert c.get("/api/v4/flowlive").json()["ready"] is False                 # no flow.db yet
    assert c.get("/api/v4/flowlive/liq").json()["ready"] is False
    _flow_db(str(tmp_path / "flow.db"), now // 300_000 * 300_000)
    _liq_db(str(tmp_path / "liq.db"), now)
    c2 = TestClient(create_app(db, hash_password(PW), SECRET))               # a fresh app: no cached answer
    assert c2.post("/api/login", json={"password": PW}).status_code == 200
    assert c2.get("/api/v4/flowlive").json()["ready"] is True
    assert c2.get("/api/v4/flowlive/liq").json()["coins"][0]["symbol"] == "BTCUSDT"


def test_flowlive_opens_read_only_and_registers_once():
    src = open(os.path.join(ROOT, "paperbot", "dash", "more", "flowlive.py"), encoding="utf-8").read()
    assert "mode=ro" in src and "INSERT" not in src
    assert not re.search(r"^\s*(import|from)\s+(urllib|requests|httpx|websocket)", src, re.M)   # no Binance call
    init = open(os.path.join(ROOT, "paperbot", "dash", "more", "__init__.py"), encoding="utf-8").read()
    assert init.count('("flowlive",)') == 1


# ---------------------------------------------------------------- browser logic in node
def _node(script: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_alert_lines_in_korean_and_counted_only_for_deepseek_and_flips():
    core = "file://" + os.path.join(V4, "core")
    out = _node(f"""const A = await import('{core}/alerts.js');
const t = (x) => A.alertKo(x);
console.log(JSON.stringify({{
  e: t("[V4.4_TREND@4h] ENTRY LTCUSDT SHORT V4.4_TREND normal 30x margin 1334.54 @ 75.8571 SL 76.3275 TP ladder LIQ 77.9957"),
  x: t("[V4.4_TREND@4h] EXIT SOLUSDT LOCK pnl +321.54 ROE +20.6% equity 5520.21"),
  ds: t("[F13_FVG_PD@15m] ENTRY LTCUSDT SHORT F13_FVG_PD best 50x margin 1334.54 @ 75.8571 SL 76.3275 TP ladder LIQ 77.9957"),
  fx: t("[RANDOM_2@5m] EXIT SOLUSDT SL pnl -21.54 ROE -2.6% equity 4520.21"),
  reel: t("[REEL_BB@5m] ENTRY BTCUSDT LONG REEL_BB normal 20x margin 900.00 @ 62000 SL 61500 TP 62400 LIQ 59000"),
  other: t("something else"),
  parts: A.tradeAlert("[V4.4_TREND@4h] ENTRY LTCUSDT SHORT V4.4_TREND normal 30x margin 1334.54 @ 75.8571 SL 76.3275 TP ladder LIQ 77.9957"),
}}));""")
    assert "진입: LTC 숏 30배 (보통 자리)" in out["e"] and "증거금 1,335 USDT" in out["e"] and "손절 76.33" in out["e"] and "청산가 78.00" in out["e"]
    assert "청산: SOL 익절 잠금" in out["x"] and "+322 USDT" in out["x"] and "잔고 5,520 USDT" in out["x"]
    assert "50배 (좋은 자리)" in out["ds"] and "증거금" not in out["ds"] and "USDT" not in out["ds"]
    assert "손실" in out["fx"] and "USDT" not in out["fx"] and "%" not in out["fx"]
    assert "진입: BTC 롱 20배" in out["reel"] and "증거금 900 USDT" in out["reel"]
    assert out["other"] == "something else"
    assert out["parts"]["kind"] == "entry" and out["parts"]["side"] == -1 and [c["k"] for c in out["parts"]["chips"]] == ["증거금", "손절", "청산가"]


def test_market_live_and_risk_helpers():
    sc = "file://" + os.path.join(V4, "screens")
    out = _node(f"""const M = await import('{sc}/market-live.js'); const R = await import('{sc}/positions-risk.js');
const mark = {{BTCUSDT: 100}};
const list = [{{a: {{account_id: "a"}}, pos: {{symbol: "BTCUSDT", side: 1, liq: 95, stop: 99}}}},
              {{a: {{account_id: "b"}}, pos: {{symbol: "BTCUSDT", side: -1, liq: 101.5, stop: 100.5}}}},
              {{a: {{account_id: "c"}}, pos: {{symbol: "ETHUSDT", side: 1, liq: 1, stop: 2}}}}];
console.log(JSON.stringify({{
  rp: [M.rangePos(5, 0, 10), M.rangePos(12, 0, 10), M.rangePos(5, 10, 10)],
  ko: [M.usdKo(5.94e9), M.usdKo(4.4e7), M.usdKo(16800), M.usdKo(950), M.usdKo(null)],
  sp: [M.split(1, 3), M.split(0, 0)],
  gap: [R.gap(1, 100, 95), R.gap(-1, 100, 101.5), R.gap(1, 100, 101), R.gap(1, null, 95)],
  cl: [R.closeness(0, 0.1), R.closeness(0.05, 0.1), R.closeness(0.2, 0.1), R.closeness(null, 0.1)],
  rank: R.rankRisk(list, (s) => mark[s]).map((x) => x.a.account_id),
}}));""")
    assert out["rp"] == [0.5, 1, None]
    assert out["ko"] == ["59.4억", "4,400만", "1.7만", "950", "—"]
    assert out["sp"] == [{"long": 0.25, "short": 0.75}, None]
    assert out["gap"][0] == pytest.approx(0.05) and out["gap"][1] == pytest.approx(0.015) and out["gap"][2] < 0 and out["gap"][3] is None
    assert out["cl"] == [1, 0.5, 0, 0]
    assert out["rank"] == ["b", "a", "c"]                  # closest to liquidation first, unknown mark last


# ---------------------------------------------------------------- wiring
def test_screens_are_wired():
    mk = _read("screens", "market.js")
    assert 'from "./market-live.js"' in mk and "tempBoard(ctx)" in mk and "flowB.load" in mk and "liqB.load" in mk
    assert ': null);\n  }\n  async function loadMarket' not in mk          # the stray 'null' under the macro calendar
    live = _read("screens", "market-live.js")
    assert '"/api/v4/flowlive"' in live and '"/api/v4/flowlive/liq"' in live and "수집 전" in live and "motion.tickPrice(" in live
    pos = _read("screens", "positions.js")
    assert 'from "./positions-risk.js"' in pos and "(min-width: 1280px)" in pos and "open: wide || st.open.has(id)" in pos
    assert "ladder.set(" in pos
    risk = _read("screens", "positions-risk.js")
    assert "fmt.money" not in risk and "fmt.usdt" not in risk and ".pnl" not in risk     # distances only (D10/D11)
    al = _read("screens", "alerts.js")
    assert "tradeAlert(g.text)" in al and "paintDay()" in al and "limit=${st.limit}" in al
    cp = _read("screens", "chart-panels.js")
    assert 'const STACK = ["pos", "sig", "liq", "al"]' in cp and "(min-width: 1280px)" in cp
    assert "coinFlowCard(ctx, st.sym)" in _read("screens", "chart.js")


def test_new_css_uses_tokens_only():
    """New rules (거래 채우기 blocks) take font sizes only from the --t-* tokens and colours only from tokens."""
    for f in ("market.css", "positions.css", "alerts.css", "chart.css"):
        css = _read("screens", f)
        part = css[css.index("거래 채우기"):] if "거래 채우기" in css else ""
        assert part, f
        for m in re.finditer(r"font-size:\s*([^;}]+)", part):
            assert re.fullmatch(r"var\(--t-(xs|sm|md|lg|xl|2xl|led)\)", m.group(1).strip()), (f, m.group(0))
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", part), f
    for f in ("market-live.js", "positions-risk.js"):
        assert "fontSize" not in _read("screens", f) and "font-size" not in _read("screens", f)
