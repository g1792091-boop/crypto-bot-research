"""터미널 v2 (owners 10/06: "HelloQuant 터미널처럼 읽기 쉽게"): side, top and bottom areas reworked.

- /api/v4/movers (dash/more/movers.py): 급등 · 급락 · 음펀비 over every Binance USD-M perpetual from ONE all-symbol
  /fapi/v1/ticker/24hr and ONE /fapi/v1/premiumIndex fetch, cached 60 s (the bot shares the IP weight), frozen /
  delivery / dust symbols left out, a failed fetch keeps the last good answer marked stale, nothing before the first
  good answer (ready: false), behind the login, registered in MODULES;
- the page: the top strip shows the movers labelled 시장 전체 (우리 봇 아님); the left column stacks 실시간 큰 체결,
  시장 강제청산 and 우리 봇 체결 with a ratio bar under each (no switch between them); the right column has 이 코인
  포지션 (주문 버튼 없음), the 기존 36 수익 차트 (realized, 참고), 오늘 수익 and the 수익 캘린더 with each day's P&L;
  the bottom table has the ALL filter, the long / short share with %, the open count and the unrealized total;
- honesty: DeepSeek / coin-flip money is never shown here (counts only), market-wide lists say so, no whale-transfer
  numbers (that needs a paid on-chain source), every font size a --t-* token and every colour a token.
"""
import json
import os
import re
import time

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.dash import more  # noqa: E402
from paperbot.dash.app import create_app, hash_password  # noqa: E402
from paperbot.dash.more import movers as MV  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
PW = "correct horse battery"
NOW_S = 1_791_300_000.0
NOW = int(NOW_S * 1000)


def _src(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as f:
        return f.read()


def _code(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)(^|[^:\"'`])//.*$", r"\1", src)


def _tickers(now=NOW):
    t = lambda s, pct, q=5e7, close=now, last="1.5": {"symbol": s, "priceChangePercent": str(pct), "lastPrice": last,  # noqa: E731
                                                       "quoteVolume": str(q), "closeTime": close}
    return [t("BTCUSDT", 1.2, last="65000"), t("PUMPUSDT", 104.64), t("UPUSDT", 30.1), t("SHROOMUSDT", -31.33),
            t("DOWNUSDT", -12.0), t("DEADUSDT", 900.0, close=now - 3 * 3_600_000),     # frozen (delisted): left out
            t("DUSTUSDT", 500.0, q=20.0),                                               # one stray trade: left out
            t("BTCUSDT_261225", 80.0),                                                  # delivery: not in premiumIndex
            t("NOPERPUSDT", 70.0)]                                                      # not a perpetual


def _premium(now=NOW):
    p = lambda s, r: {"symbol": s, "lastFundingRate": str(r), "nextFundingTime": now + 3_600_000}  # noqa: E731
    return [p("BTCUSDT", 0.0001), p("PUMPUSDT", 0.0005), p("UPUSDT", -0.0003), p("SHROOMUSDT", -0.0041),
            p("DOWNUSDT", 0.0), p("DEADUSDT", -0.03), p("DUSTUSDT", -0.02), p("BTCUSDT_261225", -0.01),
            p("AGENCYUSDT", -0.02)]                                                     # no live 24 h row: left out


class FakeFetch:
    def __init__(self):
        self.urls, self.fail, self.now = [], False, NOW

    def __call__(self, url):
        self.urls.append(url)
        if self.fail:
            raise OSError("blocked")
        return _tickers(self.now) if "ticker/24hr" in url else _premium(self.now)


@pytest.fixture
def fake(monkeypatch):
    f = FakeFetch()
    monkeypatch.setattr(MV, "FETCH", f)
    return f


# ---------------------------------------------------------------- movers
def test_build_picks_real_perpetual_movers_only():
    out = MV.build(_tickers(), _premium(), NOW)
    assert out["ready"] and out["n"] == 5
    assert [r["s"] for r in out["up"]] == ["PUMPUSDT", "UPUSDT", "BTCUSDT"]
    assert [r["s"] for r in out["down"]] == ["SHROOMUSDT", "DOWNUSDT"]
    assert out["up"][0]["pct"] == 104.64 and out["down"][0]["pct"] == -31.33
    assert [r["s"] for r in out["neg"]] == ["SHROOMUSDT", "UPUSDT"]           # negative only, live perpetuals only
    assert out["neg"][0]["rate"] == -0.0041 and out["neg"][0]["next"] == NOW + 3_600_000
    every = {r["s"] for k in ("up", "down", "neg") for r in out[k]}
    assert not every & {"DEADUSDT", "DUSTUSDT", "BTCUSDT_261225", "NOPERPUSDT", "AGENCYUSDT"}


def test_build_with_nothing_is_not_ready():
    assert MV.build([], [], NOW)["ready"] is False
    assert MV.build(None, {"code": -1}, NOW)["ready"] is False


def test_one_fetch_of_each_list_per_minute_and_stale_on_failure(fake):
    clock = [NOW_S]
    m = MV.Movers(clock=lambda: clock[0])
    a = m.get()
    assert a["ready"] and "stale" not in a
    assert fake.urls == [MV.TICKER_URL, MV.PREMIUM_URL]                       # all-symbol forms, no ?symbol=
    assert "symbol=" not in "".join(fake.urls)
    clock[0] += 59
    assert m.get() == a and len(fake.urls) == 2                               # cached: no new request inside 60 s
    clock[0] += 2
    fake.fail = True
    b = m.get()                                                               # failed refresh: the last good, marked old
    assert b["stale"] is True and b["up"] == a["up"] and m.fetches == 2
    clock[0] += 10
    assert m.get()["stale"] is True and m.fetches == 2                        # a failure is not retried every request
    clock[0] += 60
    fake.fail = False
    assert "stale" not in m.get() and m.fetches == 3


def test_failure_before_any_answer_says_not_ready(fake):
    fake.fail = True
    assert MV.Movers(clock=lambda: NOW_S).get() == {"ready": False}


def test_default_fetch_is_the_apps_get_json(monkeypatch):
    import paperbot.dash.app as A
    seen = []
    monkeypatch.setattr(A, "_get_json", lambda url, timeout=8.0: seen.append((url, timeout)) or [])
    monkeypatch.setattr(MV, "FETCH", None)
    assert MV._fetch(MV.TICKER_URL) == [] and seen == [(MV.TICKER_URL, 8.0)]
    src = open(os.path.join(ROOT, "paperbot", "dash", "more", "movers.py"), encoding="utf-8").read()
    assert "urlopen" not in src and "TTL_S = 60.0" in src


def test_route_behind_login_and_registered(tmp_path, fake):
    assert "movers" in more.MODULES
    fake.now = int(time.time() * 1000)                                        # the route uses the real clock
    c = TestClient(create_app(str(tmp_path / "paper3.db"), hash_password(PW), b"x" * 32))
    assert c.get("/api/v4/movers").status_code == 401
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    d = c.get("/api/v4/movers").json()
    assert d["ready"] and d["up"][0]["s"] == "PUMPUSDT" and d["neg"][0]["s"] == "SHROOMUSDT"
    c.get("/api/v4/movers")
    assert len(fake.urls) == 2                                                # the second page shares the cached answer
    json.dumps(d)


# ---------------------------------------------------------------- the page
JS = ["terminal.js", "terminal-kit.js", "terminal-top.js", "terminal-feed.js", "terminal-live.js", "terminal-side.js",
      "terminal-table.js"]


def test_top_strip_wires_the_movers_labelled_market_wide():
    top = _src("screens", "terminal-top.js")
    assert '"/api/v4/movers"' in top and "ctx.every(60000" in top
    for w in ("급등", "급락", "음펀비", "시장 전체 (우리 봇 아님)", "24시간 거래대금", "펀딩"):
        assert w in top, w
    assert "수집 전" in top                                                    # no answer yet: no made-up mover
    assert "stale" in top


def test_left_column_stacks_three_lists_with_ratio_bars_and_no_switch():
    js, feed, live = _src("screens", "terminal.js"), _src("screens", "terminal-feed.js"), _src("screens", "terminal-live.js")
    left = js[js.index('"term-col term-left"'):].split("\n")[0]
    assert left.index("big.el") < left.index("liq.el") < left.index("fills.el")
    assert "duoSwitch(left" not in js
    assert "ratioBar(" in feed and "ratioBar(" in live
    assert '"LONG"' in feed and '"SHORT"' in feed and "/api/liq" in feed
    assert "시장 전체 (우리 봇 아님)" in live and "시장 전체 (우리 봇 아님)" in feed
    assert "export const age" in _src("screens", "terminal-kit.js")         # ages '6s' / '4m'
    css = _src("screens", "terminal.css")
    assert ".term-fr.big.whale" in css and ".term-fr.big.buy" in css and ".term-fr.big.sell" in css


def test_right_column_profit_card_calendar_and_no_order_buttons():
    side = _src("screens", "terminal-side.js")
    for w in ("이 코인 포지션", "수익 차트", "오늘 수익", "수익 캘린더", "기존 36", "판정이 아닙니다", "수집 전", "기록 없음"):
        assert w in side, w
    assert 'ui.assume("open")' in side and "ui.assume()" in side and 'ui.pill("", "ref")' in side
    assert "CAL_API" in side and ".pnl" in side                               # the calendar answer's realized P&L
    code = _code(side)
    assert ".g.ds200" not in code and ".g.flip" not in code and 'g["ds200"]' not in code


def test_bottom_table_header_has_all_filter_share_bar_count_and_total():
    t = _src("screens", "terminal-table.js")
    assert '"ALL"' in t and "ratioBar(" in t and "열린" in t and "미실현 합계" in t
    assert 'MONEY_G = new Set(["core", "m5", "extra"])' in t                 # DeepSeek / coin flips: counts only


def test_no_deepseek_or_coin_flip_money_and_no_fake_whale_transfers():
    side, table = _code(_src("screens", "terminal-side.js")), _code(_src("screens", "terminal-table.js"))
    assert "MONEY_G" in side and "MONEY_G" in table
    feed = _src("screens", "terminal-feed.js")
    assert 'FOLD = new Set(["ds", "coin"])' in feed
    fold = feed[feed.index("const what = "):feed.index("function render()")]
    assert "pnl" not in fold.replace("m.one", "")
    for f in JS:
        src = _src("screens", f)
        assert "Whale Transfer" not in src and "고래 이동" not in src, f       # needs a paid on-chain source: not faked
        assert "Math.random" not in src, f
        assert "innerHTML" not in src and "toLocaleString" not in src, f


def test_tokens_only():
    css = _src("screens", "terminal.css")
    for m in re.finditer(r"font(?:-size)?\s*:\s*([^;]+);", css):
        v = m.group(1)
        if "var(--f-" in v and "var(--t-" not in v and "px" not in v:
            continue                                                          # a family only (font: inherit etc.)
        assert "var(--t-" in v or "inherit" in v, v
    for f in JS + ["terminal.css"]:
        src = _code(_src("screens", f))
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", src), f
        assert not re.search(r"\b(rgba?|hsla?)\(\s*\d", src), f
