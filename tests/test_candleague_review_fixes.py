"""후보 리그 dashboard: the fixes after the v4 review (2026-10-11), each pinned by what reaches the page.

  * 포지션 on a wide window: the cards follow '수익 큰 순' from the first prices (they were ordered before any price and
    stayed in entry order until the next 30 s answer).
  * 묶인 증거금 대비 % and 수익 중 / 손실 중 leave a coin without a price out of both sides and say how many.
  * Prices over a minute old (Binance not answering; the server keeps the last good values) hide every live P&L, ROE
    and pill ROE, like a stopped engine record does, and say why.
  * A lock line measured from the entry (while the engine replays from 10/01) reads "잠금 중", never "닿음" (터미널 too).
  * The engine dot (LK.health) uses the same 12 / 15 minute rule as the banner, by the server's clock: a record 20 minutes
    old is never "정상" under a banner that says the engine stopped.
  * The day pill counts like the rule bot's (10/01 = D+0).
  * 순위표: the "딥시크 금액 숨김" footnote only when the snapshot hides DeepSeek money.
  * 터미널: the chart keeps a far take-profit off its price scale (named at the edge instead); the bottom table changes
    numbers in place on the 5 s tick (a focused row is never thrown away); the top bar names the 묶음 it counts; a screen
    left while it loads hands back its cleanup.
  * dash.py: a file added under static/ after the server started is served after one rescan (no 404 until a restart).
The node harnesses are the screens' own test files' (DOM stand-ins, fake server answers)."""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
HERE = os.path.dirname(os.path.abspath(__file__))


def _mod(name):
    spec = importlib.util.spec_from_file_location(f"_cl_{name}", os.path.join(HERE, f"{name}.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


PU = _mod("test_candleague_pos_ui")
TU = _mod("test_candleague_term_ui")
RU = _mod("test_candleague_rank_ui")
DAY = 86_400_000


# ------------------------------------------------------------------------------------------------ 포지션
def test_positions_wide_cards_follow_the_first_prices(tmp_path):
    """Wide window (all cards open), sort 수익 큰 순: the positions answer comes before any price (cards in entry order:
    ETH newer than BTC); the first prices (BTC +100, ETH −50) re-order them at once, BTC first."""
    o = PU._run(tmp_path, PU.FIXTURE + r"""
globalThis.WIDE = true;
localStorage.setItem("cl-ps-grp", JSON.stringify("all"));
localStorage.setItem("cl-ps-sort", JSON.stringify("pnl"));
API["/api/positions"] = doc(); API["/api/klines"] = bars; API["/api/fills"] = fills; API["/api/meta"] = {};
const el = document.createElement("div");
document.body.append(el);
await P.mount(el, ctxOf({}));
await tick(80);
const order = () => el.querySelectorAll("article.ps-card").filter((c) => !c.classList.contains("ps-hidden")).map((c) => c.getAttribute("aria-label").split(" ")[0]);
out.before = order();
API["/api/live"] = live(101000, 2550);
await L.liveRefresh(); await tick(60);
out.after = order();
API["/api/live"] = live(101000, 2300);                        // later ticks: the order stays until the next snapshot
await L.liveRefresh(); await tick(60);
out.still = order();
""")
    assert o["before"] == ["ETH", "BTC"]
    assert o["after"] == ["BTC", "ETH"]
    assert o["still"] == ["BTC", "ETH"]


def test_positions_sum_leaves_unpriced_coins_out_of_both_sides(tmp_path):
    """ETH has no price: the % is BTC's +100 over BTC's own margin (+30.00 %, not +25.26 % over both margins); the line
    says one position has no price; the 묶인 증거금 total still has both."""
    o = PU._run(tmp_path, PU.FIXTURE + r"""
localStorage.setItem("cl-ps-grp", JSON.stringify("all"));
const lv = live(101000, 2550);
lv.coins = lv.coins.filter((c) => c.coin !== "ETHUSD");
const el = await mountOn(doc(), lv);
out.sum = el.querySelector("section.ps-sum").textContent;
out.k = (({coins, ...x}) => x)(K.sums([P1, P2], (c) => (c === "BTCUSD" ? 101000 : null)));
""")
    assert "묶인 증거금 대비 +30.00% (시세 있는 1개)" in o["sum"]
    assert "시세 없음 1" in o["sum"] and "묶인 증거금 395.83 USDT" in o["sum"] and "수익 중 1 · 손실 중 0" in o["sum"]
    k = o["k"]
    assert k["priced"] == 1 and k["unpriced"] == 1 and abs(k["margin"] - 395.83) < 1e-9 and abs(k["pricedMargin"] - 333.33) < 1e-9
    assert abs(k["roe"] - 100 / 333.33) < 1e-9


def test_old_prices_hide_live_numbers_everywhere(tmp_path):
    """The feed answers stale (Binance down) with prices 95 s old: no live P&L on the card, the sum or the ladder, and the
    screen says the prices are old; 20 s old (a hiccup) still counts as live. The kit rule itself: pricesLive / liveOk /
    waitKo."""
    o = PU._run(tmp_path, PU.FIXTURE + r"""
localStorage.setItem("cl-ps-grp", JSON.stringify("all"));
const old = (age) => ({...live(101000, 2550), stale: true, generated_ms: Date.now() - age * 1000});
const el = await mountOn(doc(), old(95));
const card = el.querySelectorAll("article.ps-card").find((c) => c.textContent.includes("BTCUSDT · 격리 30배"));
out.led = card.querySelector("b.led-num").textContent;
out.note = card.querySelector("small.ps-lednote").textContent;
out.sum = el.querySelector("section.ps-sum").textContent;
out.ladder = el.querySelector("section.ps-risk").textContent;
out.kit = [K.pricesLive(), K.liveOk(doc()), K.waitKo(doc())];
API["/api/live"] = old(20);
await L.liveRefresh(); await tick(60);
out.led2 = card.querySelector("b.led-num").textContent;
out.kit2 = [K.pricesLive(), K.liveOk(doc()), K.waitKo(doc())];
const pill = K.posPill({id: "x", kind: "core", open: {symbol: "BTCUSDT", side: 1, entry: 100000, lev: 30}}, {allowed: true});
out.pill = pill.textContent;
const hid = K.posPill({id: "ds-x", kind: "ds", open: {symbol: "BTCUSDT", side: 1, entry: 123456.7, lev: 50}}, {allowed: true, hidden: true});
out.hid = hid.textContent;
""")
    assert o["led"] == "—" and o["note"].startswith("시세가") and "전 값" in o["note"]
    assert "실시간 손익 감춤" in o["sum"] and "+100.00" not in o["sum"]
    assert "진입 때 거리" in o["ladder"]
    assert o["kit"][0] is False and o["kit"][1] is False and o["kit"][2].startswith("시세가")
    assert o["led2"] == "+100.00" and o["kit2"] == [True, True, ""]
    assert o["pill"] == "BTC 롱 30배+30.0%"                            # 20 s old prices: the pill's live ROE stays
    assert o["hid"] == "BTC 롱" and "50" not in o["hid"]               # posPill's own hidden rule: coin and side only


# ------------------------------------------------------------------------------------------------ kit: health, day pill
def test_engine_dot_follows_the_banner_rule_and_the_server_clock(tmp_path):
    o = PU._run(tmp_path, r"""
const now = Date.UTC(2026, 9, 10, 0, 0);                      // 10/10 09:00 KST
const d = (minAgo) => ({accounts: [], generated_ms: now - minAgo * 60e3, done_ms: now - minAgo * 60e3 - 60e3,
  start_ms: Date.UTC(2026, 8, 30, 15, 0), started_ms: now - 2 * 86400e3});
out.h = [5, 13, 20, 34].map((m) => LKm.health(d(m), now));
out.day = [LKm.dPlus(d(1), now), LKm.calDay(d(1), now), LKm.dPlus(d(1), Date.UTC(2026, 8, 30, 15, 30))];
""")
    lv = [x["lv"] for x in o["h"]]
    assert lv == ["ok", "warn", "bad", "bad"]
    assert "정상" in o["h"][0]["ko"] and "정상" not in o["h"][2]["ko"] and "멈춤" in o["h"][2]["ko"]
    assert o["day"] == [9, 10, 0]                                 # 10/10 = D+9 (10일째), 10/01 = D+0


# ------------------------------------------------------------------------------------------------ 순위표
def test_rank_footnote_and_old_prices(tmp_path):
    """The 'DeepSeek money hidden' footnote shows only when the snapshot hides it; prices over a minute old: no pill ROE
    and the live dot says why."""
    now = int(time.time() * 1000)
    shown = RU._run(tmp_path, RU._routes(RU._league(now, ds_money=True), now))
    assert "금액 숨김 설정" not in shown["first"]["page"]
    hid = RU._run(tmp_path, RU._routes(RU._league(now, ds_money=False), now))
    assert "딥시크는 금액 숨김 설정이라" in hid["first"]["page"]
    routes = RU._routes(RU._league(now), now)
    routes["/api/live"] = {**routes["/api/live"], "stale": True, "generated_ms": now - 95_000}
    o = RU._run(tmp_path, routes)
    assert RU._row(o["first"], "core-DOGE-15m-1")["pill"] == "BTC 롱 30배"
    assert "ROE 감춤" in o["first"]["live"] and "지난 값" in o["first"]["live"]


# ------------------------------------------------------------------------------------------------ 터미널
def test_terminal_chart_scale_table_in_place_and_scope_labels(tmp_path):
    o = TU._run(tmp_path, TU.FIXTURE + r"""
// capture the candle series' options (the autoscale provider)
const mk = window.LightweightCharts.createChart;
window.LightweightCharts.createChart = (...a) => {
  const c = mk(...a); const add = c.addCandlestickSeries;
  c.addCandlestickSeries = (opts) => { CH.copts = opts; return add(opts); };
  return c;
};
const el = await mountOn(doc(), live(101000, 2550), {});
const auto = CH.copts.autoscaleInfoProvider;
// bars 99,000-101,000 on screen: the stop (98,000) stays in the scale, the take-profit (106,000) is left off it
out.scale = auto(() => ({priceRange: {minValue: 99000, maxValue: 101000}})).priceRange;
const CHART = await import("file://__CLJS__/screens/terminal-chart.js");
out.band = [CHART.inBand({v: 106000}, {lo: 99000, hi: 101000}), CHART.inBand({v: 98000}, {lo: 99000, hi: 101000}),
  CHART.inBand({v: 150000, keep: true}, {lo: 99000, hi: 101000})];
// the next repaint (a 5 s tick) names the take-profit left off the scale at the chart's edge
await L.liveRefresh(); await tick(60);
out.edge = el.querySelectorAll("span.tm-cedge").map((x) => (x.hidden ? "" : x.textContent)).filter(Boolean);
// bars that reach near the take-profit: it is back inside the scale, and the edge label goes at the next repaint
out.near = auto(() => ({priceRange: {minValue: 97000, maxValue: 103500}})).priceRange;
await L.liveRefresh(); await tick(60);
out.edge2 = el.querySelectorAll("span.tm-cedge").map((x) => (x.hidden ? "" : x.textContent)).filter(Boolean);
// the table: the row element is the same after a 5 s tick, only its numbers change
const row = el.querySelector("tr.click");
const before = row.textContent;
API["/api/live"] = live(102000, 2550);
await L.liveRefresh(); await tick(60);
const row2 = el.querySelector("tr.click");
out.same = row === row2 && row.isConnected;
out.rowChanged = before !== row2.textContent && row2.textContent.includes("+200.00");
out.top = q1(el, "div.tm-row");
out.band2 = q1(el, "div.tm-band");
""".replace("__CLJS__", TU.JS))
    assert abs(o["scale"]["minValue"] - 98000) < 1e-9 and abs(o["scale"]["maxValue"] - 101000) < 1e-9
    assert abs(o["near"]["maxValue"] - 106000) < 1e-9                  # a near take-profit stays in the scale
    assert o["band"] == [False, True, True]
    assert any(e.startswith("익절 106,000.0 ↑") and "차트 밖" in e for e in o["edge"]), o["edge"]
    assert not any(e.startswith("익절") for e in o["edge2"]), o["edge2"]
    assert o["same"] and o["rowChanged"]
    assert "우리 포지션 · 후보" in o["top"] and "190계좌 열린 4" in o["band2"]


def test_terminal_lock_line_while_replaying_and_cleanup_when_left(tmp_path):
    o = TU._run(tmp_path, TU.FIXTURE + r"""
localStorage.setItem("cl-tm-grp", JSON.stringify("all"));
localStorage.setItem("cl-tm-tab", JSON.stringify("stops"));
const el = await mountOn(doc({catching_up: true}), live(101000, 2550), {});
out.stops = el.querySelectorAll("tr.click").map((r) => r.textContent);
// a screen left while it loads: the shell gets its cleanup back (the chart and its listeners go)
let alive = true;
API["/api/fills"] = () => { alive = false; return fills; };
const el2 = document.createElement("div");
document.body.append(el2);
const ret = await TM.mount(el2, {...ctxOf({}), alive: () => alive});
out.cleanup = typeof ret;
""")
    lock = [r for r in o["stops"] if "잠금" in r and "ETH" in r]
    assert lock and all("잠금 중" in r and "닿음" not in r and "−2" not in r for r in lock), o["stops"]
    assert o["cleanup"] == "function"


# ------------------------------------------------------------------------------------------------ the shell
def test_shell_drops_late_subscriptions_and_runs_late_cleanup():
    """app.js: a subscription made after the screen closed is dropped at once, and a cleanup returned after it closed
    runs at once (the old screen's object was already cleaned)."""
    app = open(os.path.join(ROOT, "candleague", "static", "js", "app.js"), encoding="utf-8").read()
    assert re.search(r"const until = \(unsub\) => \{ if \(ctl\.signal\.aborted\) unsub\(\);", app)
    assert "if (ctl.signal.aborted) { try { if (typeof cleanup === \"function\") cleanup();" in app
    assert "onLeague(fn) {\n      if (ctl.signal.aborted) return;" in app


def test_static_files_added_after_start_are_served(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from candleague import dash as D
    from candleague.live import Live
    st = tmp_path / "static"
    (st / "js").mkdir(parents=True)
    (st / "index.html").write_text("<!doctype html>")
    (st / "js" / "a.js").write_text("export const a = 1;")
    monkeypatch.setattr(D, "STATIC", str(st))
    monkeypatch.setattr(D, "_static_seen", {"files": D._static_files(), "at": time.monotonic()})
    snap = tmp_path / "snap"
    snap.mkdir()
    c = TestClient(D.create_app(str(snap), "", b"x" * 32, live=Live(mode="fake"), open_=True), base_url="http://league.test")
    assert c.get("/static/js/a.js").status_code == 200
    (st / "js" / "b.js").write_text("export const b = 2;")
    assert c.get("/static/js/b.js").status_code == 404              # inside the rescan pause: not looked for yet
    monkeypatch.setattr(D, "STATIC_RESCAN_S", 0.0)
    assert c.get("/static/js/b.js").status_code == 200              # one rescan finds it
    assert c.get("/static/js/../index.html").status_code == 404 and c.get("/static/nope.js").status_code == 404
