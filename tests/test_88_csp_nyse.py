"""#88: the dashboard's Content-Security-Policy, the NYSE holidays (2026-2027) in the US market chip and the us_open
analysis window, and the A4 / A11 documents (the prepaid credit line, the TradingAgents limits page from the FAQ)."""
import json
import os
import re
import sys
from datetime import datetime, timezone

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot import sessions  # noqa: E402
from paperbot.dash import app as A  # noqa: E402
from paperbot.dash.app import create_app, hash_password  # noqa: E402

sys.path.insert(0, os.path.dirname(__file__))
from test_dash import SECRET, _node, _static  # noqa: E402
from test_dash_v4groups import PW, _world  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")


def _ms(y, mo, d, h, mi):
    return int(datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp() * 1000)


# ---------------------------------------------------------------- CSP
def test_every_answer_carries_a_strict_csp(tmp_path):
    db = str(tmp_path / "p.db")
    _world(db, trades=False).close()
    anon = TestClient(create_app(db, hash_password(PW), SECRET, candles=lambda s, i, n: []))
    pages = [anon.get("/login"), anon.get("/static/login.js"), anon.get("/api/board")]
    assert pages[1].status_code == 200 and "nextPath" in pages[1].text          # public: the login page needs it
    c = TestClient(create_app(db, hash_password(PW), SECRET, candles=lambda s, i, n: []))
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    pages += [c.get("/"), c.get("/api/board"), c.get("/static/v4/core/main.js")]
    for r in pages:
        csp = r.headers["Content-Security-Policy"]
        assert csp == A.CSP and r.headers["X-Frame-Options"] == "DENY"
    d = dict(x.strip().split(" ", 1) for x in A.CSP.split(";"))
    assert d["default-src"] == "'self'" and d["script-src"] == "'self'"           # no inline or outside script
    assert d["frame-ancestors"] == "'none'" and d["object-src"] == "'none'" and d["connect-src"] == "'self'"
    assert "data:" in d["img-src"] and "fonts.gstatic.com" in d["font-src"]       # the sound mask, Google Fonts
    assert "unsafe-eval" not in A.CSP and "*" not in A.CSP
    # the old dashboard (/v3) talks to Binance's WebSockets and TradingView from the browser: it keeps its old header
    old = c.get("/v3")
    assert old.status_code == 200 and old.headers["Content-Security-Policy"] == "frame-ancestors 'none'"
    assert old.headers["X-Frame-Options"] == "DENY"
    assert c.get("/v4").headers["Content-Security-Policy"] == A.CSP


def test_no_page_relies_on_an_inline_script_or_handler():
    pages = [os.path.join(ROOT, "paperbot", "dash", "static", f) for f in ("login.html", "index.html")]
    pages.append(os.path.join(V4, "index.html"))
    for p in pages:
        html = open(p, encoding="utf-8").read()
        assert re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html) is None, p          # every script has a src
        assert re.search(r"\son[a-z]+\s*=\s*[\"']", html) is None, p                 # no onclick= etc.
    for dirpath, _, files in os.walk(V4):
        for f in files:
            if f.endswith(".js"):
                src = open(os.path.join(dirpath, f), encoding="utf-8").read()
                assert "eval(" not in src and "new Function" not in src, f


# ---------------------------------------------------------------- NYSE holidays
def test_us_open_window_is_not_flagged_on_nyse_holidays():
    assert "us_open" not in sessions.time_features(_ms(2026, 11, 26, 14, 30))["windows"]    # Thanksgiving
    assert "us_open" in sessions.time_features(_ms(2026, 11, 25, 14, 30))["windows"]
    assert "us_open" in sessions.time_features(_ms(2026, 11, 27, 14, 30))["windows"]        # early close: opens
    assert "us_open" not in sessions.time_features(_ms(2027, 3, 26, 13, 30))["windows"]     # Good Friday 2027 (EDT)
    good_friday = sessions.time_features(_ms(2026, 4, 3, 12, 30))                         # 08:30 New York
    assert "macro" in good_friday["windows"] and "us_open" not in good_friday["windows"]  # data can still come out
    assert "2027-12-31" not in sessions.NYSE_HOLIDAYS and len(sessions.NYSE_HOLIDAYS) == 20


def test_dashboard_holiday_list_matches_the_analysis_list():
    src = open(os.path.join(V4, "core", "bars.js"), encoding="utf-8").read()
    block = src[src.index("export const NYSE_HOLIDAYS"):src.index("export const NYSE_EARLY")]
    assert set(re.findall(r'"(\d{4}-\d{2}-\d{2})"', block)) == set(sessions.NYSE_HOLIDAYS)
    early = src[src.index("export const NYSE_EARLY"):]
    early = early[:early.index("}")]
    assert set(re.findall(r'"(\d{4}-\d{2}-\d{2})"', early)) == set(sessions.NYSE_EARLY_CLOSE)


def test_us_market_chip_knows_holidays_and_early_closes():
    url = "file://" + os.path.join(V4, "core", "bars.js")
    cases = {"2026-11-26T15:00:00Z": None, "2026-11-25T22:00:00Z": None, "2026-11-27T17:30:00Z": None,
             "2026-10-06T21:30:00Z": None, "2026-10-09T21:30:00Z": None, "2026-10-06T15:00:00Z": None}
    js = (f"import({json.dumps(url)}).then((b) => {{ const r = {{}}; "
          + "".join(f"r[{json.dumps(k)}] = b.usMarket(Date.parse({json.dumps(k)}));" for k in cases)
          + " console.log(JSON.stringify(r)); });")
    out = json.loads(_node(js))
    assert out["2026-11-26T15:00:00Z"] == {"open": False, "holiday": "추수감사절",
                                           "text": "휴장 (추수감사절) · 다음 개장 11월 27일 밤 (한국)"}
    assert out["2026-11-25T22:00:00Z"]["text"] == "닫힘 · 다음 개장 11월 27일 밤 (한국)"
    assert out["2026-11-27T17:30:00Z"] == {"open": True, "holiday": None, "text": "열려 있음 · 마감까지 0시간 30분 (단축 마감)"}
    assert out["2026-10-06T21:30:00Z"]["text"] == "닫힘 · 다음 개장 오늘 밤 (한국)"      # an ordinary night: as before
    assert out["2026-10-09T21:30:00Z"]["text"] == "닫힘 · 다음 개장 월요일 밤 (한국)"
    assert out["2026-10-06T15:00:00Z"]["open"] is True


# ---------------------------------------------------------------- A4 / A11 documents
def test_prepaid_credit_line_is_in_both_documents():
    for f in ("debate-room.md", "server-setup-v4.md"):
        txt = open(os.path.join(ROOT, "docs", f), encoding="utf-8").read()
        assert "$30 선불 크레딧은 저절로 다시 채워지지 않습니다" in txt and "'API 잔액 부족'" in txt, f
    setup = open(os.path.join(ROOT, "docs", "server-setup-v4.md"), encoding="utf-8").read()
    assert "5-5. **24시간 토론방 켜기**" in setup                                    # the step number is unchanged


def test_tradingagents_limits_page_is_served_and_linked_from_the_faq(tmp_path):
    assert A.DOCS["tradingagents-limits"] == "tradingagents-limits.md"
    doc = open(os.path.join(ROOT, "docs", "tradingagents-limits.md"), encoding="utf-8").read()
    assert "2412.20138" in doc and "동전 던지기" in doc and len(doc.splitlines()) < 60
    assert "/api/doc/tradingagents-limits" in _static(os.path.join("v4", "screens", "faq-items.js"))
    db = str(tmp_path / "p.db")
    _world(db, trades=False).close()
    c = TestClient(create_app(db, hash_password(PW), SECRET, candles=lambda s, i, n: []))
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    r = c.get("/api/doc/tradingagents-limits")
    assert r.status_code == 200 and "TradingAgents" in r.text
