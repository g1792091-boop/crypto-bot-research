"""후보 리그 "설치 뒤 진입만" (owners 10/11: "설치 뒤(10월 11일 이후)에 들어간 것만 보기"): one per-device view switch
(candleague/static/js/after.js) that keeps, in the lists of open positions and closed trades on 포지션 · 터미널 · 체결 기록
· 순위표 · 계좌, only what was ENTERED at or after the install time (the snapshot's ``started_ms``), recomputes the counts
and sums next to those lists (labelled 설치 뒤만), and leaves the ranking, the wallets, 잔고 수익률, the checkpoint numbers
and the coin-flip comparisons alone (the full record from 10/01). A view filter only.

The pure filter runs under node; the 포지션, 터미널 and 순위표 screens are mounted under node on the DOM stand-ins of
tests/test_candleague_pos_ui.py, test_candleague_term_ui.py and test_candleague_rank_ui.py (their harnesses are reused,
not copied). The API side: /api/positions carries started_ms and every position's ``since``, /api/fills every row's
``entry_time`` (what the page filters on; no new server field)."""

from __future__ import annotations

import copy
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, TESTS)

import test_candleague_pos_ui as POS  # noqa: E402  (its DOM stand-in and _run)
import test_candleague_rank_ui as RANK  # noqa: E402
import test_candleague_term_ui as TERM  # noqa: E402

STATIC = os.path.join(ROOT, "candleague", "static")
AFTER = "file://" + os.path.join(STATIC, "js", "after.js")
# 2026-10-01 09:00 KST (the replay's start) and 2026-10-11 21:03 KST (the install)
START_MS = 1_790_812_800_000
INSTALL_MS = 1_791_676_800_000 + 12 * 3_600_000 + 3 * 60_000


def test_filter_helpers(tmp_path):
    """Off (or no install time): the very same objects come back. On: positions entered at or after the install stay
    (the boundary counts as after; a missing time never does), the counts are recomputed over them, the left-out ones
    are listed; the shared answer is never modified; fills by entry time; a trade book keeps its equity line whole;
    a league account's open position as the lists show it. The switch is stored per device and tells its listeners
    once; a blocked storage never throws, reads as 'off' until pressed, and then keeps the choice for this page only
    (the switch works and says it is not kept)."""
    o = POS._run(tmp_path, f"""
const A = await import("{AFTER}");
const CUT = {INSTALL_MS};
LKm.setLeague({{started_ms: CUT, start_ms: {START_MS}, accounts: []}});
const mk = (id, since, side, coin, role, kind, hidden = false) => ({{id, since, side, coin, role, kind, hidden}});
const d = {{started_ms: CUT, generated_ms: 1, done_ms: 2, positions: [mk("a", CUT - 1, 1, "BTCUSD", "cand", "core"),
  mk("b", CUT, -1, "BTCUSD", "flip", "ds", true), mk("c", null, 1, "ETHUSD", "cand", "core"), mk("d", CUT + 5e6, 1, "ETHUSD", "base", "core")],
  counts: {{open: 4}}}};
out.offSame = A.afterPositions(d) === d && A.afterOn(d) === false;
const heard = [];
const un = A.onAfterChange((v) => heard.push(v));
A.setAfter(true); A.setAfter(true);
out.heard = heard.slice(); out.stored = localStorage.getItem("cl-after");
const v = A.afterPositions(d);
out.ids = v.positions.map((p) => p.id); out.counts = v.counts; out.before = v.after.before.map((p) => p.id); out.afterMs = v.after.ms;
out.notMutated = d.positions.length === 4 && d.counts.open === 4 && v !== d;
out.keepStatus = A.afterPositions({{status: "준비 중", positions: []}}).status;
const fills = [{{entry_time: CUT - 1, account: "x"}}, {{entry_time: CUT, account: "y"}}, {{entry_time: null, account: "z"}}, {{account: "w"}}];
out.fills = A.afterFills(fills).map((f) => f.account);
const eq = [[1, 5000], [2, 5100]];
const bk = A.afterBook({{equity: eq, trades: [{{entry_time: CUT + 1}}, {{entry_time: CUT - 1}}]}});
out.book = {{n: bk.trades.length, all: bk.all_trades, eqSame: bk.equity === eq}};
const acc = (since) => ({{id: "q", open: {{symbol: "BTCUSDT", side: 1, since}}}});
out.open = [!!A.openAfter(acc(CUT)), !!A.openAfter(acc(CUT - 60e3)), A.openBefore(acc(CUT - 60e3)), A.openBefore({{id: "n", open: null}})];
out.suffix = A.afterSuffix(d); out.tag = A.afterTag(d).textContent;
// the install time unknown everywhere: the switch is "off" whatever was stored, nothing is filtered
LKm.setLeague({{start_ms: {START_MS}, accounts: []}});
const d2 = {{...d, started_ms: null}};
out.noInstall = [A.installMs(d2), A.afterOn(d2), A.afterPositions(d2) === d2, A.afterFills(fills) === fills];
LKm.setLeague({{started_ms: CUT, start_ms: {START_MS}, accounts: []}});
A.setAfter(false);
out.heard2 = heard.slice(); out.stored2 = localStorage.getItem("cl-after");
un();
out.offFills = A.afterFills(fills) === fills;
// a private window / blocked storage: reads and writes throw; the switch is simply off and nothing breaks
const keep = globalThis.localStorage;
globalThis.localStorage = {{getItem() {{ throw new Error("blocked"); }}, setItem() {{ throw new Error("blocked"); }}}};
let threw = false;
try {{
  out.blocked0 = [A.afterWanted(), A.afterVolatile()];
  const hb = [];
  const un2 = A.onAfterChange((v) => hb.push(v));
  A.setAfter(true);
  out.blocked = [A.afterWanted(), A.afterOn(d), A.afterPositions(d) === d, A.afterVolatile()];
  const bar = A.afterBar();
  out.blockedBar = {{pressed: bar.querySelector("button.kp-after-tog").getAttribute("aria-pressed"), note: bar.querySelector("span.kp-after-note").textContent,
    title: bar.querySelector("button.kp-after-tog").getAttribute("title")}};
  A.setAfter(false);
  out.blocked2 = [A.afterWanted(), A.afterVolatile()];
  out.blockedHeard = hb;
  un2();
}} catch (e) {{ threw = String(e); }}
out.threw = threw;
globalThis.localStorage = keep;
""")
    assert o["offSame"]
    assert o["heard"] == [True] and o["stored"] == "true"
    assert o["ids"] == ["b", "d"] and o["before"] == ["a", "c"] and o["afterMs"] == INSTALL_MS
    c = o["counts"]
    assert c["open"] == 2 and c["long"] == 1 and c["short"] == 1 and c["hidden"] == 1
    assert c["by_coin"] == {"BTCUSD": {"long": 0, "short": 1}, "ETHUSD": {"long": 1, "short": 0}}
    assert c["by_role"] == {"flip": 1, "base": 1} and c["by_kind"] == {"ds": 1, "core": 1}
    assert o["notMutated"] and o["keepStatus"] == "준비 중"
    assert o["fills"] == ["y"]
    assert o["book"] == {"n": 1, "all": 2, "eqSame": True}
    assert o["open"] == [True, False, True, False]
    assert o["suffix"] == " · 설치 뒤만" and o["tag"] == "설치 뒤만"
    assert o["noInstall"] == [None, False, True, True]
    assert o["heard2"] == [True, False] and o["stored2"] == "false" and o["offFills"]
    assert not o["threw"] and o["blocked0"] == [False, False]
    assert o["blocked"] == [True, True, False, True]                 # pressed: on for this page, and it filters
    assert o["blockedBar"]["pressed"] == "true" and "새로 고치면 처음대로" in o["blockedBar"]["note"]
    assert "저장이 막혀" in o["blockedBar"]["title"]
    assert o["blocked2"] == [False, False] and o["blockedHeard"] == [True, False]


def test_switch_bar_label_note_and_hidden_without_install_time(tmp_path):
    """The switch reads "설치 뒤 진입만 (10/11 21:03 이후)" in Korea time with aria-pressed, its note says the ranking,
    wallets and checkpoints are the full record from 10/01 (the 터미널 adds its 수익 차트); without an install time
    the bar is hidden; a later snapshot that brings the time shows it (syncAfter). The note says, in visible words
    (not only a tooltip), that only the view changes."""
    o = POS._run(tmp_path, f"""
const A = await import("{AFTER}");
LKm.setLeague({{start_ms: {START_MS}, accounts: []}});
const bar0 = A.afterBar();
out.hidden0 = bar0.hidden;
LKm.setLeague({{started_ms: {INSTALL_MS}, start_ms: {START_MS}, accounts: []}});
document.body.append(bar0);
A.syncAfter();
out.hidden1 = bar0.hidden;
out.off = {{t: bar0.textContent, pressed: bar0.querySelector("button.kp-after-tog").getAttribute("aria-pressed")}};
bar0.querySelector("button.kp-after-tog").click();
out.on = {{pressed: bar0.querySelector("button.kp-after-tog").getAttribute("aria-pressed"), stored: localStorage.getItem("cl-after"),
  cls: bar0.className}};
const tm = A.afterBar({{also: ["수익 차트"]}});
out.term = tm.querySelector("span.kp-after-note").textContent;
""")
    assert o["hidden0"] and not o["hidden1"]
    assert o["off"]["t"] == "설치 뒤 진입만 (10/11 21:03 이후)보기만 바뀝니다 · 순위·잔고·점검은 10/01부터 전체 기록" and o["off"]["pressed"] == "false"
    assert o["on"]["pressed"] == "true" and o["on"]["stored"] == "true" and "on" in o["on"]["cls"].split()
    assert o["term"] == "보기만 바뀝니다 · 순위·잔고·수익 차트·점검은 10/01부터 전체 기록"


# the 포지션 fixture (tests/test_candleague_pos_ui.py) with the install 2.2 hours ago: P1 (BTC long, entered 3 h ago) is
# from before it; P2 (ETH 1/4 short, 1 h), the two DeepSeek ones (2 h, 10 min) are after it. One fill entered after.
POS_AFTER = r"""
const CUT = NOW - 2.2 * 3600e3;
fills.fills.unshift({symbol: "ETHUSDT", side: -1, entry_time: NOW - 3600e3, entry_price: 2560, exit_time: NOW - 1800e3, exit_price: 2540,
  exit_reason: "TP", leverage: 40, pnl: 20, roe: 0.32, account: "core-OBV_S-1h-3-q"});
LKm.setLeague({ds_money: false, started_ms: CUT, start_ms: NOW - 10 * 86400e3, accounts: [{id: "core-DOGE-1h-1", role: "cand", kind: "core", name: "DOGE", tf: "1h"},
  {id: "core-OBV_S-1h-3-q", role: "quarter", kind: "core", name: "OBV_S", tf: "1h", of: "core-OBV_S-1h-3"},
  {id: "ds-F5_BOX-15m-1", role: "cand", kind: "ds", name: "F5_BOX", tf: "15m"}]});
localStorage.setItem("cl-ps-grp", JSON.stringify("all"));
const grab = async (el) => {
  const r = {cards: el.querySelectorAll("article.ps-card").map((c) => c.getAttribute("aria-label")),
    sum: el.querySelector("section.ps-sum").textContent, coins: el.querySelector("div.ps-coins").textContent,
    bar: el.querySelector("div.kp-after").textContent, pressed: el.querySelector("button.kp-after-tog").getAttribute("aria-pressed"),
    tab: el.querySelector("div.ps-tabs").querySelectorAll("button")[0].textContent,
    ladder: el.querySelector("section.ps-risk").textContent, rungs: el.querySelectorAll("a.ps-risk-row").length};
  const tabs = el.querySelector("div.ps-tabs").querySelectorAll("button");
  tabs[1].click(); await tick(30);
  r.orders = el.querySelectorAll("div.ps-orow").length;
  tabs[2].click(); await tick(80);
  const per = el.querySelectorAll("div.ps-filters")[0].querySelectorAll("button").find((b) => b.textContent === "최근 300건");
  per.click(); await tick(20);
  r.trows = el.querySelectorAll("div.ps-trow").map((x) => x.getAttribute("title"));
  r.tsum = el.querySelector("p.ps-sumline").textContent;
  tabs[0].click(); await tick(20);
  return r;
};
"""


def test_positions_screen_on_and_off(tmp_path):
    """포지션 with the switch on: the cards, the 위험 사다리, the 손절·잠금 주문 and the 체결 기록 tab keep only what was
    entered after the install; the summary (열린 n개, 미실현 합계) and the coin chips are over those and say 설치 뒤만;
    the BTC long entered before the install is nowhere. Off: everything, no label. All before the install: the empty
    state says so and offers to turn the switch off."""
    o = POS._run(tmp_path, POS.FIXTURE + POS_AFTER + r"""
localStorage.setItem("cl-after", "true");
let el = await mountOn(doc({started_ms: CUT}), live(101000, 2550));
out.on = await grab(el);
el.remove();
localStorage.setItem("cl-after", "false");
el = await mountOn(doc({started_ms: CUT}), live(101000, 2550));
out.off = await grab(el);
el.remove();
localStorage.setItem("cl-after", "true");
API["/api/positions"] = doc({started_ms: NOW});
await K.kickPositions(); await tick(60);
el = await mountOn(doc({started_ms: NOW}), live(101000, 2550));
out.empty = el.querySelector("div.ps-empty").textContent;
el.querySelector("div.ps-empty").querySelector("button").click();
out.stored = localStorage.getItem("cl-after");
""")
    on, off = o["on"], o["off"]
    assert on["pressed"] == "true" and on["bar"].startswith("설치 뒤 진입만 (") and "순위·잔고·점검은" in on["bar"]
    assert len(on["cards"]) == 3 and not any(c.startswith("BTC 롱") for c in on["cards"])     # P1 (BTC long) is out
    assert len(off["cards"]) == 4 and any(c.startswith("BTC 롱") for c in off["cards"])
    assert "설치 뒤만" in on["sum"] and "열린 3개 · 전체 · 설치 뒤만" in on["sum"]
    assert "+100.00" not in on["sum"] and "−50.00" in on["sum"]              # the BTC long's +100.00 is out of the total
    assert "열린 4개 · 전체" in off["sum"] and "설치 뒤만" not in off["sum"] and "+50.00" in off["sum"]
    assert "설치 뒤만" in on["coins"] and "설치 뒤만" not in off["coins"]
    assert on["tab"] == "포지션 3설치 뒤만" and off["tab"] == "포지션 4"          # the tab's count says so too
    assert "BTC0↑ 1↓" in on["coins"] and "BTC1↑ 1↓" in off["coins"]
    assert on["rungs"] == 1 and off["rungs"] == 2 and "설치 뒤만" in on["ladder"]
    assert on["orders"] == 1 and off["orders"] == 2
    assert len(on["trows"]) == 1 and on["trows"][0].startswith("core-OBV_S-1h-3-q")
    assert on["tsum"].startswith("1건 · 합계 +20.00 USDT") and "설치 뒤만" in on["tsum"]
    assert len(off["trows"]) == 4 and "설치 뒤만" not in off["tsum"]
    assert "설치 뒤에 들어간 열린 포지션이 아직 없습니다" in o["empty"] and "4개는 모두 설치 전" in o["empty"]
    assert o["stored"] == "false"


def test_terminal_filters_every_part(tmp_path):
    """터미널 with the switch on: the band counts over the positions entered after the install (열린 3, its lead
    labelled 설치 뒤만), the table, the side list, the chips and the feed leave the BTC long and every trade entered
    before the install out; the chart has no mark of a pre-install trade; the selected account whose position is from
    before says why it is not shown instead of "없음". Off: as before."""
    o = TERM._run(tmp_path, TERM.FIXTURE + r"""
const CUT = NOW - 2.2 * 3600e3;
fills.fills.unshift({symbol: "ETHUSDT", side: -1, entry_time: NOW - 3600e3, entry_price: 2560, exit_time: NOW - 1800e3, exit_price: 2540,
  exit_reason: "TP", leverage: 40, pnl: 20, roe: 0.32, account: "core-OBV_S-1h-3-q"});
LKm.setLeague({...LKm.league(), started_ms: CUT});
localStorage.setItem("cl-tm-grp", JSON.stringify("all"));
const inTable = (el, sel) => { const t = el.querySelector("section.tm-table"); const x = t ? t.querySelector(sel) : null; return x ? x.textContent : null; };
const grab = (el) => ({band: q1(el, "div.tm-band"), bar: q1(el, "div.kp-after"), rows: el.querySelectorAll("tr.click").map((r) => r.textContent),
  feed: el.querySelectorAll("button.tm-fr").map((b) => b.getAttribute("title")), head: inTable(el, "div.tm-ph"),
  sel: q1(el, "div.tm-selb"), chips: el.querySelectorAll("button.tm-chip").length, marks: CH.cs.marks.length,
  foot: inTable(el, "div.tm-pf")});
localStorage.setItem("cl-after", "true");
let el = await mountOn(doc({started_ms: CUT}), live(101000, 2550), {});
out.on = grab(el);
el.remove();
el = await mountOn(doc({started_ms: CUT}), live(101000, 2550), {acct: "core-DOGE-1h-1", coin: "BTCUSD"});
out.onAcct = grab(el);
el.remove();
localStorage.setItem("cl-after", "false");
el = await mountOn(doc({started_ms: CUT}), live(101000, 2550), {acct: "core-DOGE-1h-1", coin: "BTCUSD"});
out.off = grab(el);
""")
    on, acct, off = o["on"], o["onAcct"], o["off"]
    assert on["band"].startswith("후보 리그 지금설치 뒤만") and "열린 3" in on["band"] and "190계좌" not in on["band"]
    assert "190계좌 열린 4" in off["band"] and "설치 뒤" not in off["band"]
    assert on["bar"].startswith("설치 뒤 진입만 (") and "수익 차트" in on["bar"]
    assert len(on["rows"]) == 1 and "BTC" not in on["rows"][0]                 # the ETH 1/4 short only
    assert "열린 3" in on["head"] and "설치 뒤만" in on["head"] and on["foot"].startswith("설치 뒤만 · ")
    assert "설치 뒤" not in off["head"]
    assert not any(t.startswith("core-DOGE-1h-1") for t in on["feed"])          # its pre-install trade and position
    assert any(t.startswith("core-OBV_S-1h-3-q") for t in on["feed"])
    assert any(t.startswith("core-DOGE-1h-1") for t in off["feed"])
    assert "설치 전 진입이라 숨김" in acct["sel"] and "지금 열린 포지션 없음" not in acct["sel"]
    assert acct["chips"] == 0 and acct["marks"] == 0                            # no BTC chip, no mark of the old trade
    assert off["chips"] >= 1 and off["marks"] >= 1 and "설치 전" not in off["sel"]


def test_rank_ranking_untouched_pills_and_counts_filtered(tmp_path):
    """순위표 with the switch on: every rank, 잔고 수익률 and comparison is exactly what it is off (the official record);
    only the open-position pills of positions entered before the install go, and 포지션 중 / the cards' 포지션 count the
    rest, labelled 설치 뒤."""
    now = int(__import__("time").time() * 1000)
    lg = RANK._league(now)
    lg["started_ms"] = now - 30 * 60_000                            # every open position (entered 1 h ago) is from before
    lg2 = copy.deepcopy(lg)
    for a in lg2["accounts"]:                                       # ... except the 후보 DOGE's, entered 10 minutes ago
        if a["id"] == "core-DOGE-15m-1" and a["open"]:
            a["open"]["since"] = now - 10 * 60_000
    steps = [{"name": "flip", "click": '.rk-gcard[data-group="flip"]'}, {"name": "all", "click": ".k4-allbtn"}]
    off = RANK._run(tmp_path, RANK._routes(lg2, now), steps=steps, local={"cl-after": "false"})
    on = RANK._run(tmp_path, RANK._routes(lg2, now), steps=steps, local={"cl-after": "true"})
    strip = lambda v: [(r["id"], r["rk"], r["ret"], (r["meta"] or "").replace(r["pill"] or "\0", "").replace("설치 전 진입 · 숨김", ""))  # noqa: E731
                       for r in v["rows"]]
    views = lambda x: [x["first"], x["steps"]["flip"], x["steps"]["all"]]  # noqa: E731
    for a, b in zip(views(on), views(off)):                         # ranks, %, 거래 · 승패 · 잔고 · 낙폭: the same
        assert strip(a) == strip(b)
    assert on["csv"] == off["csv"]
    pills = lambda v: sorted({r["id"] for r in v["rows"] if r["pill"]})  # noqa: E731
    assert pills(on["first"]) == pills(off["first"]) == ["core-DOGE-15m-1"]     # entered after the install: kept
    assert "core-DOGE-15m-1-flip" in pills(off["steps"]["flip"]) and pills(on["steps"]["flip"]) == []
    assert pills(on["steps"]["all"]) == ["core-DOGE-15m-1"] and len(pills(off["steps"]["all"])) > 1
    assert "설치 뒤만" in on["first"]["tiles"] and "설치 뒤" not in off["first"]["tiles"]
    assert "포지션중1" in on["first"]["tiles"].replace(" ", "") and "포지션중1" in off["first"]["tiles"].replace(" ", "")
    assert "포지션중0" in on["steps"]["flip"]["tiles"].replace(" ", "") and "포지션중0" not in off["steps"]["flip"]["tiles"].replace(" ", "")
    # the cards' "(설치 뒤만)" (a no-break space, which the harness's txt() folds to a plain one)
    assert any("(설치 뒤만)" in c for c in on["first"]["cards"]) and not any("설치" in c for c in off["first"]["cards"])
    # a pill the switch hides is never a silent gap: the row says "설치 전 진입 · 숨김" where the pill was
    flip_on = {r["id"]: r for r in on["steps"]["flip"]["rows"]}
    assert "설치 전 진입 · 숨김" in flip_on["core-DOGE-15m-1-flip"]["meta"] and flip_on["core-DOGE-15m-1-flip"]["pill"] is None
    assert not any("설치 전" in (r["meta"] or "") for r in off["steps"]["flip"]["rows"])
    assert "설치 뒤 진입만" in on["first"]["page"] and "순위·잔고·점검은" in on["first"]["page"]


def test_api_carries_the_times_the_page_filters_on(tmp_path):
    """No new server field: /api/positions has started_ms and each position's since (the entry time), /api/fills each
    row's entry_time, /api/league started_ms (dash.py, read only)."""
    from fastapi.testclient import TestClient

    from candleague import dash as D
    from candleague.live import Live
    snap = tmp_path / "snap"
    snap.mkdir()
    acct = {"id": "core-DOGE-1h-1", "role": "cand", "kind": "core", "name": "DOGE", "tf": "1h", "exit": "tp3R|4", "exit_ko": "x",
            "size": 1.0, "trades": 1, "wins": 1, "wallet": 5100.0, "mean_ret": 0.02, "max_dd": 0.0, "bust": False, "of": None,
            "open": {"symbol": "BTCUSDT", "side": 1, "entry": 100000.0, "stop": 98000.0, "tp": 106000.0, "since": INSTALL_MS + 900_000, "lev": 30}}
    league = {"generated_ms": INSTALL_MS + 3_600_000, "done_ms": INSTALL_MS + 3_500_000, "start_ms": START_MS, "started_ms": INSTALL_MS,
              "accounts": [acct], "ds_money": True, "judge": {}, "watch": {}}
    trade = {"symbol": "BTCUSDT", "side": -1, "entry_time": INSTALL_MS - 7_200_000, "entry_price": 1.0, "exit_time": INSTALL_MS + 60_000,
             "exit_price": 1.0, "exit_reason": "TP", "leverage": 30, "pnl": 1.0, "roe": 0.1}
    (snap / "league.json").write_text(json.dumps(league))
    (snap / "trades.json").write_text(json.dumps({"core-DOGE-1h-1": {"equity": [[START_MS, 5000.0]], "trades": [trade]}}))
    c = TestClient(D.create_app(str(snap), "", b"x" * 32, live=Live(mode="fake"), open_=True), base_url="http://league.test")
    p = c.get("/api/positions").json()
    assert p["started_ms"] == INSTALL_MS and p["positions"][0]["since"] == INSTALL_MS + 900_000
    assert c.get("/api/fills").json()["fills"][0]["entry_time"] == INSTALL_MS - 7_200_000
    assert c.get("/api/league").json()["started_ms"] == INSTALL_MS
    assert c.get("/static/js/after.js").status_code == 200


def test_static_rules():
    """Text only through dom.js (no HTML strings) in after.js; the screens that filter import it; the switch lives in the
    설정 panel too; the stylesheet rules (tokens, var(--t-*) sizes) hold for the new kit.css and terminal.css parts."""
    src = open(os.path.join(STATIC, "js", "after.js")).read()
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write", src)
    for f in ("positions.js", "positions-orders.js", "positions-risk.js", "fills.js", "terminal.js", "terminal-top.js", "terminal-table.js",
              "terminal-side.js", "terminal-feed.js", "rank.js", "rank-cards.js", "rank-rows.js", "rank-table.js", "account.js", "home.js",
              "entries.js"):
        assert '"../after.js"' in open(os.path.join(STATIC, "js", "screens", f)).read(), f
    assert '"./after.js"' in open(os.path.join(STATIC, "js", "app.js")).read()
    assert '"./after.js"' in open(os.path.join(STATIC, "js", "settings.js")).read()
    for f in ("kit.css", os.path.join("scr", "terminal.css")):
        css = open(os.path.join(STATIC, f)).read()
        part = css[css.index("설치 뒤 진입만"):]
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", part), f
        for m in re.finditer(r"font(?:-size)?:\s*([^;]+);", part):
            assert "var(--t-" in m.group(1), (f, m.group(0))


# ------------------------------------------------------------------------------------------------ review fixes (10/11)
def test_terminal_filters_again_when_the_install_time_comes_late(tmp_path):
    """A cold load of 터미널 with the switch on, whose /api/fills answered before the snapshot and the positions brought
    the install time: the first rows are unfiltered (nothing to cut with yet), and the moment the install time is known
    the feed, the table's 체결 tab and the band's 오늘 후보 거래 drop the pre-install trades (the raw answer is kept and
    filtered again; the feed no longer keeps rows it was handed before)."""
    o = TERM._run(tmp_path, TERM.FIXTURE + r"""
const CUT = NOW - 2.2 * 3600e3;
fills.fills.unshift({symbol: "ETHUSDT", side: -1, entry_time: NOW - 3600e3, entry_price: 2560, exit_time: NOW - 1800e3, exit_price: 2540,
  exit_reason: "TP", leverage: 40, pnl: 20, roe: 0.32, account: "core-OBV_S-1h-3-q"});
LKm.setLeague({...LKm.league(), started_ms: null});                  // the snapshot has not brought the time yet
localStorage.setItem("cl-tm-grp", JSON.stringify("all"));
localStorage.setItem("cl-tm-tab", JSON.stringify("fills"));
localStorage.setItem("cl-after", "true");
const feedIds = (el) => el.querySelectorAll("button.tm-fr").map((b) => b.getAttribute("title").split(" · ")[0]);
const tableRows = (el) => el.querySelector("section.tm-table").querySelectorAll("tr.click").map((r) => r.textContent);
const el = await mountOn(doc({started_ms: null}), live(101000, 2550), {});
out.early = {feed: feedIds(el), rows: tableRows(el).length, bar: el.querySelector("div.kp-after").hidden};
// the positions answer now carries the install time (same snapshot: no reload of the fills)
API["/api/positions"] = doc({started_ms: CUT});
await K.kickPositions(); await tick(80);
out.late = {feed: feedIds(el), rows: tableRows(el), bar: el.querySelector("div.kp-after").hidden,
  band: el.querySelector("div.tm-band").textContent, sub: el.querySelector("section.tm-fills") ? el.querySelector("section.tm-fills").textContent : ""};
""")
    e, l = o["early"], o["late"]
    assert e["bar"] is True and "core-DOGE-1h-1" in e["feed"] and e["rows"] >= 2     # no install time: nothing to filter with
    assert l["bar"] is False
    assert "core-DOGE-1h-1" not in l["feed"] and "core-OBV_S-1h-3-q" in l["feed"]   # the 9e6 / 8e6-old trades are gone
    assert len(l["rows"]) == 1 and "ETH" in l["rows"][0]                            # 체결 tab: the one entered after
    assert "설치 뒤만" in l["band"]


def test_lists_the_switch_emptied_say_why_and_offer_to_turn_it_off(tmp_path):
    """With every entry from before the install (install time = now), no list just says "없음": 터미널's 포지션 · 체결 ·
    손절 주문 tabs, 우리 봇 체결 and 이 코인 포지션, the 체결 기록 screen (목록 and 표) and 포지션's 손절·잠금 주문 and
    위험 사다리 say how many were hidden and why; the "모두 보기 (설치 뒤 진입만 끄기)" button turns the switch off."""
    t = TERM._run(tmp_path, TERM.FIXTURE + r"""
LKm.setLeague({...LKm.league(), started_ms: NOW});
localStorage.setItem("cl-tm-grp", JSON.stringify("all"));
localStorage.setItem("cl-after", "true");
const el = await mountOn(doc({started_ms: NOW}), live(101000, 2550), {coin: "BTCUSD"});
const tbl = el.querySelector("section.tm-table");
const tab = (name) => tbl.querySelectorAll("button").find((b) => b.textContent.startsWith(name));
const box = () => { const x = tbl.querySelector("div.kp-after-empty"); return x ? x.textContent : null; };
out.pos = box();
tab("체결").click(); await tick(20); out.fills = box();
tab("손절").click(); await tick(20); out.stops = box();
const feed = el.querySelector("section.tm-fills").querySelector("div.kp-after-empty");
out.feed = feed ? feed.textContent : null;
const mine = el.querySelector("section.tm-mine").querySelector("div.kp-after-empty");
out.mine = mine ? mine.textContent : null;
tbl.querySelector("div.kp-after-empty").querySelector("button").click();
out.stored = localStorage.getItem("cl-after");
""")
    for k in ("pos", "stops"):
        assert t[k] and "설치 뒤에 들어간" in t[k] and "4개는 모두 설치 전" in t[k] and "모두 보기 (설치 뒤 진입만 끄기)" in t[k], (k, t[k])
    assert t["fills"] and "닫힌 거래 3건은 설치 전" in t["fills"] and "모두 보기" in t["fills"]
    assert t["feed"] and "설치 뒤에 들어간 체결이 아직 없습니다" in t["feed"] and "모두 보기" in t["feed"]
    assert t["mine"] and "BTC 열린 포지션 2개는 설치 전" in t["mine"]
    assert t["stored"] == "false"
    p = POS._run(tmp_path, POS.FIXTURE + r"""
LKm.setLeague({ds_money: false, started_ms: NOW, start_ms: NOW - 10 * 86400e3, accounts: []});
localStorage.setItem("cl-ps-grp", JSON.stringify("all"));
localStorage.setItem("cl-after", "true");
const el = await mountOn(doc({started_ms: NOW}), live(101000, 2550));
out.ladder = el.querySelector("section.ps-risk").textContent;
el.querySelector("div.ps-tabs").querySelectorAll("button")[1].click(); await tick(30);
const ord = el.querySelectorAll("div.kp-after-empty").map((x) => x.textContent);
out.orders = ord.find((x) => x.includes("주문")) || null;
el.remove();
API["/api/fills"] = fills;
const f = document.createElement("div"); document.body.append(f);
await FL.mount(f, {...ctxOf(), params: {name: "fills", arg: null, query: {}}});
await tick(80);
const g = f.querySelector("div.kp-after-empty");
out.list = g ? g.textContent : null;
out.listRows = f.querySelectorAll("div.ps-trow").length;
f.querySelector("div.scr-head").querySelectorAll("button").find((b) => b.textContent === "표").click(); await tick(80);
const g2 = f.querySelectorAll("div.kp-after-empty").map((x) => x.textContent);
out.table = g2[g2.length - 1] || null;
""")
    assert "설치 전 진입 4개는 숨김" in p["ladder"]
    assert p["orders"] and "열린 포지션 4개는 설치 전" in p["orders"] and "모두 보기" in p["orders"]
    assert p["list"] and "최근 거래 3건은 설치 전" in p["list"] and p["listRows"] == 0 and "모두 보기" in p["list"]
    assert p["table"] and "최근 거래 3건은 설치 전" in p["table"]


def test_a_hidden_pill_says_it_was_entered_before_the_install(tmp_path):
    """A position the switch hides never leaves a silent gap: the account screen's head shows "설치 전 진입 · 숨김" where
    its pill was (a 후보 account too), and a 묶음 of hidden DeepSeek accounts whose positions all predate the install
    says so instead of "지금 열린 포지션 없음"."""
    url = lambda f: "file://" + os.path.join(STATIC, "js", f)  # noqa: E731
    o = POS._run(tmp_path, POS.FIXTURE + f"""
const AC = await import("{url('screens/account.js')}");
const W = await import("{url('screens/rank-rows.js')}");
const CUT = NOW - 30 * 60e3;
const open = {{symbol: "LTCUSDT", side: -1, entry: 80, stop: 82, tp: 74, since: NOW - 3600e3, lev: 20}};
const acct = (id, role, o2 = {{}}) => ({{id, role, kind: "core", name: "DOGE", tf: "1h", exit: "tp3R|4", exit_ko: "고정 익절 3R", size: 1,
  trades: 5, wins: 3, wallet: 5200, mean_ret: 0.01, max_dd: 0.02, bust: false, of: role === "cand" ? null : "core-DOGE-1h-1", open: null, ...o2}});
const lg = {{ds_money: true, started_ms: CUT, start_ms: NOW - 10 * 86400e3, generated_ms: NOW - 60e3, done_ms: NOW - 120e3, judge: {{}}, watch: {{}},
  accounts: [acct("core-DOGE-1h-1", "cand", {{open}}), acct("core-DOGE-1h-1-q", "quarter"), acct("core-DOGE-1h-1-x", "exitonly"),
    acct("core-DOGE-1h-1-flip", "flip"), acct("base-core-DOGE-1h", "base", {{of: null}})]}};
LKm.setLeague(lg);
API["/api/trades/"] = {{equity: null, trades: []}};
const mountAcct = async () => {{
  const el = document.createElement("div"); document.body.append(el);
  await AC.mount(el, {{...ctxOf(), params: {{name: "account", arg: "core-DOGE-1h-1", query: {{}}}}, onLeague: (fn) => fn(lg)}});
  await tick(60);
  const hd = el.querySelector("div.cl-acthead");
  return {{head: hd ? hd.textContent : null, pill: !!(hd && hd.querySelector("span.kp-pill"))}};
}};
localStorage.setItem("cl-after", "true");
out.on = await mountAcct();
localStorage.setItem("cl-after", "false");
out.off = await mountAcct();
// the 상위 · 하위 of a 묶음 whose accounts are all hidden (DeepSeek money hidden) and whose positions predate the install
localStorage.setItem("cl-after", "true");
const tb = W.topBottom();
const hid = [{{...acct("ds-X-1h-1", "cand", {{open, kind: "ds"}})}}, {{...acct("ds-Y-1h-1", "cand", {{kind: "ds"}})}}];
tb.set({{label: "딥시크", rk: {{shown: [], waiting: [], hid}}, row: () => null, hidRow: () => document.createElement("div")}});
out.tb = tb.el.textContent;
""")
    assert o["on"]["head"] and "설치 전 진입 · 숨김" in o["on"]["head"] and not o["on"]["pill"]
    assert o["off"]["pill"] and "설치 전" not in o["off"]["head"]
    assert "모두 설치 전 진입" in o["tb"] and "지금 열린 포지션 없음" not in o["tb"]


def test_the_pressed_switch_keeps_its_place_on_the_screen(tmp_path):
    """Pressing the switch remounts the screen from the top; the new switch is scrolled back to where the pressed one
    was on the screen (so neither a finger nor an eye loses it), again as the screen fills in, and no more once the
    viewer scrolls themselves. "모두 보기" inside a list keeps the page's scroll position instead."""
    o = POS._run(tmp_path, f"""
const A = await import("{AFTER}");
LKm.setLeague({{started_ms: {INSTALL_MS}, start_ms: {START_MS}, accounts: []}});
const calls = [], ls = {{}};
globalThis.window = {{scrollY: 0, scrollBy(x, y) {{ calls.push(y); this.scrollY += y; }},
  addEventListener(t, f) {{ ls[t] = f; }}, removeEventListener(t) {{ delete ls[t]; }}}};
const bar1 = A.afterBar(); document.body.append(bar1);
const b1 = bar1.querySelector("button.kp-after-tog");
b1.getBoundingClientRect = () => ({{top: 300}});
let top2 = 483;                                                    // the new screen: the switch lower (taller band)
const un = A.onAfterChange(() => {{
  bar1.remove();
  const bar2 = A.afterBar(); document.body.append(bar2);
  bar2.querySelector("button.kp-after-tog").getBoundingClientRect = () => ({{top: top2 - window.scrollY}});
}});
b1.click();
await tick(100);
out.first = calls.slice();
top2 = 523;                                                         // the screen filled in more: it moved again
await tick(400);
out.second = calls.slice();
if (ls.wheel) ls.wheel();                                           // the viewer scrolls: no more pinning
top2 = 900;
await tick(2700);
out.after = calls.slice();
un();
""")
    assert o["first"] == [183]
    assert o["second"] == [183, 40]
    assert o["after"] == o["second"]


def test_home_follows_the_switch(tmp_path):
    """요약 shows the switch; with it on, 최근 체결 lists only trades entered after the install (its head says 설치 뒤만;
    all of them older: it says how many it hid), and 후보 열린 포지션 counts only positions entered after the install."""
    url = lambda f: "file://" + os.path.join(STATIC, "js", f)  # noqa: E731
    o = POS._run(tmp_path, POS.FIXTURE + f"""
const HM = await import("{url('screens/home.js')}");
const CUT = NOW - 2.2 * 3600e3;
const open = (since) => ({{symbol: "BTCUSDT", side: 1, entry: 100000, stop: 98000, tp: 106000, since, lev: 30}});
const acct = (id, o2) => ({{id, role: "cand", kind: "core", name: id, tf: "1h", exit: "x", exit_ko: "x", size: 1, trades: 3, wins: 1,
  wallet: 5100, mean_ret: 0.01, max_dd: 0.01, bust: false, of: null, open: null, ...o2}});
const lg = (cut) => ({{ds_money: true, started_ms: cut, start_ms: NOW - 10 * 86400e3, generated_ms: NOW - 60e3, done_ms: NOW - 120e3, judge: {{}},
  watch: {{checkpoints: []}}, accounts: [acct("core-A-1h-1", {{open: open(NOW - 3600e3)}}), acct("core-B-1h-1", {{open: open(NOW - 5 * 3600e3)}})]}});
fills.fills.unshift({{symbol: "ETHUSDT", side: -1, entry_time: NOW - 3600e3, entry_price: 2560, exit_time: NOW - 1800e3, exit_price: 2540,
  exit_reason: "TP", leverage: 40, pnl: 20, roe: 0.32, account: "core-A-1h-1"}});
API["/api/fills"] = fills;
const mountHome = async (cut) => {{
  const d = lg(cut);
  LKm.setLeague(d);
  const el = document.createElement("div"); document.body.append(el);
  await HM.mount(el, {{...ctxOf(), params: {{name: "home", arg: null, query: {{}}}}, onLeague: (fn) => fn(d)}});
  await tick(60);
  const card = el.querySelectorAll("section.card").find((c) => c.textContent.includes("최근 체결"));
  return {{bar: el.querySelector("div.kp-after") ? el.querySelector("div.kp-after").textContent : null, card: card ? card.textContent : null,
    rows: card ? card.querySelectorAll("div.s2a-ev").length : -1, led: el.querySelector("section.ledbar") ? el.querySelector("section.ledbar").textContent : ""}};
}};
localStorage.setItem("cl-after", "true");
out.on = await mountHome(CUT);
out.all = await mountHome(NOW);
localStorage.setItem("cl-after", "false");
out.off = await mountHome(CUT);
""")
    on, off, allold = o["on"], o["off"], o["all"]
    assert on["bar"] and on["bar"].startswith("설치 뒤 진입만 (") and "보기만 바뀝니다" in on["bar"]
    assert on["rows"] == 1 and "설치 뒤만" in on["card"] and off["rows"] == 4 and "설치 뒤만" not in off["card"]
    assert "후보 열린 포지션 (설치 뒤만)1" in on["led"] and "후보 열린 포지션2" in off["led"]
    assert "최근 거래 4번은 설치 전" in allold["card"] and "모두 보기" in allold["card"]
