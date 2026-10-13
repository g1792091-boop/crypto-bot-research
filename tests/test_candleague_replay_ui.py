"""candleague 거래 다시보기 (js/screens/replay.js, route #/replay?acct=&at=) and the account page's '왜 이 수익률인가' card (js/screens/account-why.js).

Both are mounted / called for real under node on the DOM stand-in of test_candleague_rank_ui (text nodes only, like the browser's), each with its
own runner copy (no other module's globals are touched). Replay: a fake trade + klines, the entry / exit / caption words, the controls, the
markers and lines the chart is given (a fake chart library records them), a failed load shows the retry box, a hidden price reads 숨김 and is
not drawn. Account card: the by-reason table, the break-even win rate and the three biggest losses on a small hand-made trade list, 표본 적음
under 30 trades, hidden money = counts only, a missing number is "—"."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_candleague_rank_ui as RANK  # noqa: E402  (its DOM stand-in)

STATIC = os.path.join(ROOT, "candleague", "static")
BAD = ("NaN", "undefined", "null", "Infinity", "[object")
H = 3_600_000
T0 = 1_760_000_000_000 - (1_760_000_000_000 % H)
ACCT = "core-X-1h-1"

REPLAY_RUNNER = r"""
import {readFileSync} from "node:fs";
import {install, txt} from "./shim.mjs";
const cfg = JSON.parse(readFileSync(process.argv[2], "utf8"));
install(cfg);
globalThis.location.hash = "";
// a fake chart library: it records what the screen gives it
const rec = {setData: 0, hiddenBars: 0, markers: [], lines: new Map(), created: 0};
if (cfg.chart) {
  const series = {
    setData(d) { rec.setData++; rec.hiddenBars = d.filter((x) => x.color).length; },
    applyOptions() {}, setMarkers(m) { rec.markers = m.map((x) => x.text); },
    createPriceLine(o) { const l = {title: o.title, price: o.price}; rec.lines.set(l, 1); return l; },
    removePriceLine(l) { rec.lines.delete(l); },
  };
  globalThis.window = globalThis;
  globalThis.LightweightCharts = {createChart() { rec.created++; return {addCandlestickSeries: () => series, timeScale: () => ({fitContent() {}, setVisibleRange() {}}), resize() {}, remove() {}, applyOptions() {}}; }};
}
const S = cfg.static;
const LK = await import(`file://${S}/js/lk.js`);
LK.setLeague(cfg.doc);
const M = await import(`file://${S}/js/screens/replay.js`);
const el = document.createElement("div");
el.dataset.screen = "replay";
document.body.appendChild(el);
const ctx = {params: {name: "replay", arg: null, query: cfg.query}, alive: () => true, signal: null,
  api: async (p) => { const r = await globalThis.fetch(p); if (!r.ok) { const e = new Error("http " + r.status); e.status = r.status; throw e; } return r.json(); },
  meta: () => LK.getMeta(), onLeague: (fn) => fn(cfg.doc), onLive: () => () => {}, onPositions: () => () => {}, every: () => {},
  css: async () => null, wide() {}, setTitle() {}, setQuery() {}, href: (n, a, q) => `#/${n}${a ? "/" + a : ""}${q ? "?" + new URLSearchParams(q) : ""}`};
const settle = async () => { for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 10)); };
const cleanup = await M.mount(el, ctx);
await settle();
const caps = [];
const cap = () => txt(el.querySelector(".rp-cap-text"));
const snap = () => ({cap: cap(), step: txt(el.querySelector(".rp-cap-top")), markers: [...rec.markers], lines: [...rec.lines.keys()].map((l) => l.title), hidden: rec.hiddenBars,
  play: txt(el.querySelector(".rp-play")), why: txt(el.querySelector(".rp-cap .cl-ewhy"))});
const out = {text: txt(el), css: M.css, start: snap(), steps: [], created: rec.created};
for (const step of cfg.steps || []) {
  const n = step.n || 1;
  for (let i = 0; i < n; i++) el.querySelector(step.sel).fire("click");
  if (step.wait) await new Promise((r) => setTimeout(r, step.wait));
  out.steps.push({sel: step.sel, ...snap()});
}
const q = (sel) => el.querySelectorAll(sel).map((n) => ({t: txt(n), d: {...n.dataset}, c: n.className, a: Object.fromEntries(n.attrs)}));
out.buttons = q("button").map((b) => b.t);
out.speed = q(".rp-speed button").map((b) => b.t);
out.links = q("a").map((b) => b.a.href);
out.errbox = q(".errbox");
out.after = txt(el);
if (typeof cleanup === "function") cleanup();
console.log(JSON.stringify(out));
process.exit(0);
"""

WHY_RUNNER = r"""
import {readFileSync} from "node:fs";
import {install, txt} from "./shim.mjs";
const cfg = JSON.parse(readFileSync(process.argv[2], "utf8"));
install(cfg);
const S = cfg.static;
const LK = await import(`file://${S}/js/lk.js`);
LK.setLeague({equity0: 1000, accounts: []});
const W = await import(`file://${S}/js/screens/account-why.js`);
const stats = W.whyStats(cfg.trades, cfg.o || {});
const card = W.whyCard(cfg.acct, cfg.book === undefined ? {trades: cfg.trades} : cfg.book, cfg.o || {});
const links = card.querySelectorAll("a").map((n) => n.attrs.get("href"));
console.log(JSON.stringify({stats, text: txt(card), links, chips: card.querySelectorAll(".rp-wy-chip").map(txt), rows: card.querySelectorAll(".rp-wy-brow").map(txt)}));
process.exit(0);
"""


def node(tmp_path, runner, cfg):
    exe = shutil.which("node")
    if not exe:
        pytest.skip("node is not installed")
    (tmp_path / "shim.mjs").write_text(RANK.SHIM)
    (tmp_path / "run.mjs").write_text(runner)
    cfg = {"static": STATIC, "routes": {}, "local": {}, **cfg}
    (tmp_path / "cfg.json").write_text(json.dumps(cfg, ensure_ascii=False))
    r = subprocess.run([exe, str(tmp_path / "run.mjs"), str(tmp_path / "cfg.json")], capture_output=True, text=True, timeout=120, cwd=str(tmp_path))
    assert r.returncode == 0, (r.stdout[-600:], r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def no_junk(text):
    for bad in BAD:
        assert bad not in text, bad


# ---------------------------------------------------------------- hand-made data
def doc():
    return {"generated_ms": T0, "done_ms": T0, "start_ms": T0, "started_ms": T0, "judge": {}, "ds_money": False, "equity0": 1000, "watch": {},
            "accounts": [{"id": ACCT, "role": "cand", "kind": "core", "name": "X", "tf": "1h", "trades": 1, "wins": 0, "mean_ret": -0.01,
                          "wallet": 950.0, "max_dd": 0.05, "bust": False, "open": None}]}


def trade(**kw):
    t = {"symbol": "BTCUSDT", "side": 1, "entry_time": T0, "entry_price": 100.0, "exit_time": T0 + 6 * H, "exit_price": 98.0, "exit_reason": "SL",
         "leverage": 30, "pnl": -50.0, "roe": -0.6, "stop_initial": 98.0, "tp_price": None, "mae_price": 98.0, "mfe_price": 103.0}
    t.update(kw)
    return t


def klines():
    """Hourly bars from 25 h before the entry: the entry bar is index 25 (its time T0); bar 28 (3 after the entry) has the high 103, the exit bar
    (entry + 5 h: the trade closes T0 + 6 h) the low 98."""
    ts = [T0 + (i - 25) * H for i in range(25 + 6 + 9)]
    o, hh, ll, c = [], [], [], []
    for i, _ in enumerate(ts):
        j = i - 25
        base = 100.0
        hi, lo = base + 0.5, base - 0.5
        if j == 3:
            hi = 103.0
        if j == 5:
            lo = 98.0
        o.append(base); hh.append(hi); ll.append(lo); c.append(base + (0.2 if j >= 0 else 0.0))
    return {"bars": {"t": ts, "o": o, "h": hh, "l": ll, "c": c}}


def routes(t=None, kl=True):
    r = {"/api/trades/" + ACCT: {"trades": [t or trade()]}}
    if kl:
        r["/api/klines"] = klines()
    return r


def replay(tmp_path, t=None, steps=None, chart=True, kl=True, query=None, r=None):
    return node(tmp_path, REPLAY_RUNNER, {"doc": doc(), "routes": routes(t, kl) if r is None else r, "chart": chart, "steps": steps or [],
                                          "query": query or {"acct": ACCT, "at": str(T0)}})


# ---------------------------------------------------------------- 거래 다시보기
def test_replay_mounts_with_entry_exit_caption_controls_and_chart(tmp_path):
    o = replay(tmp_path, steps=[{"sel": "button.rp-next"}, {"sel": "button.rp-next", "n": 2}, {"sel": "button.rp-last"}, {"sel": "button.rp-next"}, {"sel": "button.rp-play"}, {"sel": "button.rp-play"}])
    no_junk(o["text"])
    assert o["css"] == ["scr/replay.css"] and o["created"] == 1
    # the first moment is the entry bar: the entry words, the first stop with its R distance, the shared "why opened" line, and the chart's entry marker + lines
    s = o["start"]
    assert s["cap"].startswith("진입: BTC 롱 100.00 · 30배") and "처음 손절 98.00" in s["cap"] and "1R" in s["cap"]
    assert s["why"] and s["why"].startswith("왜 들어갔나")
    assert s["markers"] == ["진입 롱"] and sorted(s["lines"]) == ["진입가", "처음 손절 = 청산"]          # the exit sits on the first stop: one line, no 0 and no lock line
    assert s["hidden"] == 13 and "봉 21 / 34" in s["step"] and s["play"] == "▶ 재생"                 # the 13 bars after the shown one are drawn clear
    # one bar on: a plain "N봉 뒤" line with the bar's close against the entry
    one = o["steps"][0]
    assert one["cap"].startswith("진입 1봉 뒤 · 이 봉 마감 기준 +0.20% (+0.1R)") and one["markers"] == ["진입 롱"]
    # three bars after the entry: the best moment, in words, with the percent and R
    best = o["steps"][1]
    assert "3봉 뒤 가장 유리했을 때 +3.00% (+1.5R)" in best["cap"] and "가장 유리" in best["markers"]
    # the exit bar: the exit words, the reason, the exit price and the worst moment; the shared "why closed" line; the exit marker
    last = o["steps"][2]
    assert "청산: 손절 · 98.00 · −2.00% (−1.0R) · 증거금 대비 −60.0%" in last["cap"] and "5봉 뒤 가장 불리했을 때 −2.00% (−1.0R)" in last["cap"]
    assert last["why"].startswith("왜 청산했나") and "처음 손절선" in last["why"] and "청산 손절" in last["markers"]
    assert last["play"] == "▶ 처음부터"
    # past the exit: the trade is over
    assert "청산 1봉 뒤: 이 거래는 이미 끝났습니다" in o["steps"][3]["cap"]
    # ▶ 재생 starts (the button reads ❚❚ 멈춤) and the next click pauses it
    assert o["steps"][4]["play"] == "❚❚ 멈춤" and o["steps"][5]["play"] == "▶ 재생"       # from past the exit, ▶ 재생 starts again at the entry
    assert o["buttons"] == ["⏮ 진입", "◀", "▶ 재생", "▶", "⏭ 청산", "1x", "2x", "4x"]
    assert o["speed"] == ["1x", "2x", "4x"]
    # the page says it is one trade's story, names the lock line as not drawn, and carries the record
    t = o["text"]
    assert "판정이 아닙니다" in t and "거래 한 건의 이야기입니다" in t and "계단 잠금선은 그리지 않습니다" in t
    assert "거래 기록" in t and "처음 손절" in t and "−60.0%" in t and "−50.00" in t.replace("$", "")
    assert f"#/account/{ACCT}" in o["links"]


def test_replay_plays_by_itself_and_stops_at_the_exit_bar(tmp_path):
    o = replay(tmp_path, steps=[{"sel": 'button[data-id="4"]'}, {"sel": "button.rp-play", "wait": 3600}])
    p = o["steps"][1]
    assert "청산: 손절" in p["cap"] and p["play"] == "▶ 처음부터" and "청산 손절" in p["markers"]          # 4x: dwell + 5 bars in about 3.5 s, then it stops on the exit bar


def test_replay_without_the_chart_library_still_tells_the_story(tmp_path):
    o = replay(tmp_path, chart=False, steps=[{"sel": "button.rp-last"}])
    assert "차트 파일을 불러오지 못했습니다" in o["text"] and o["created"] == 0
    assert o["start"]["cap"].startswith("진입: BTC 롱") and "청산: 손절" in o["steps"][0]["cap"]


def test_replay_failed_load_shows_the_retry_box(tmp_path):
    o = replay(tmp_path, r={})                                           # /api/trades answers 404: ctx.api throws
    assert len(o["errbox"]) == 1 and "불러오지 못했습니다" in o["errbox"][0]["t"] and "다시 시도" in o["buttons"]
    o = replay(tmp_path, r={"/api/trades/" + ACCT: {"trades": [trade()]}})   # the candles fail
    assert len(o["errbox"]) == 1 and "다시 시도" in o["buttons"]


def test_replay_unknown_trade_account_or_missing_query_say_so(tmp_path):
    assert "찾지 못했습니다" in replay(tmp_path, query={"acct": ACCT, "at": "12345"})["text"]
    assert "그런 계좌가 없습니다" in replay(tmp_path, query={"acct": "nope", "at": str(T0)})["text"]
    t = replay(tmp_path, query={"x": "1"})["text"]
    assert "어느 거래인지 알 수 없습니다" in t


def test_replay_hidden_prices_read_hidden_and_are_never_drawn_as_zero(tmp_path):
    hid = trade(entry_price=None, exit_price=None, pnl=None, roe=None, stop_initial=None, mae_price=None, mfe_price=None)
    o = replay(tmp_path, t=hid, steps=[{"sel": "button.rp-last"}])
    no_junk(o["text"])
    assert "진입: BTC 롱 (가격 숨김)" in o["start"]["cap"] and o["start"]["lines"] == [] and o["steps"][0]["lines"] == []
    assert "청산: 손절 · 가격 숨김" in o["steps"][0]["cap"] and "숨김" in o["text"]
    assert "가장 유리했을 때" not in o["steps"][0]["cap"]


def test_replay_a_take_profit_and_the_exit_line_when_they_are_apart(tmp_path):
    t = trade(exit_price=101.5, exit_reason="LOCK", pnl=20.0, roe=0.3, tp_price=110.0, mfe_price=103.0, mae_price=99.5)
    o = replay(tmp_path, t=t, steps=[{"sel": "button.rp-last"}])
    assert sorted(o["start"]["lines"]) == ["익절", "진입가", "처음 손절"]
    assert sorted(o["steps"][0]["lines"]) == ["익절", "진입가", "처음 손절", "청산가"] and "청산: 계단 잠금" in o["steps"][0]["cap"]


def test_replay_static_rules():
    js = os.path.join(STATIC, "js")
    app = open(os.path.join(js, "app.js"), encoding="utf-8").read()
    assert 'replay: "replay"' in app and 'also: ["replay"]' in app
    for f in ("screens/replay.js", "screens/account-why.js", "why.js"):
        src = open(os.path.join(js, f), encoding="utf-8").read()
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "eval(", "binance.com"):
            assert bad not in src, (f, bad)
    css = open(os.path.join(STATIC, "scr", "replay.css"), encoding="utf-8").read()
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsl\(", css)
    # entries / fills / account link to the replay and entries uses the shared why module
    ent = open(os.path.join(js, "screens", "entries.js"), encoding="utf-8").read()
    assert 'from "../why.js"' in ent and "replayHref" in ent and "function whyIn" not in ent
    assert "replayHref" in open(os.path.join(js, "screens", "fills.js"), encoding="utf-8").read()
    assert "replayHref" in open(os.path.join(js, "screens", "positions-orders.js"), encoding="utf-8").read()
    acc = open(os.path.join(js, "screens", "account.js"), encoding="utf-8").read()
    assert "replayHref" in acc and "account-why.js" in acc


# ---------------------------------------------------------------- 계좌 › 왜 이 수익률인가
def tr(i, pnl, reason, roe=None):
    return {"symbol": "ETHUSDT", "side": 1 if i % 2 else -1, "entry_time": T0 + i * H, "entry_price": 100.0, "exit_time": T0 + i * H + H, "exit_price": 99.0,
            "exit_reason": reason, "leverage": 30, "pnl": pnl, "roe": roe if roe is not None else pnl / 100.0}


LIST = [tr(1, -50, "SL"), tr(2, -30, "SL"), tr(3, 40, "LOCK"), tr(4, 20, "LOCK"), tr(5, 60, "TP"), tr(6, -10, "RULE"), tr(7, -100, "LIQ"), tr(8, -20, "SL")]
ACC = {"id": ACCT, "kind": "core", "trades": 8, "wallet": 790.0}


def why(tmp_path, trades, **kw):
    cfg = {"trades": trades, "acct": kw.pop("acct", ACC), "o": {"start": 1000, **kw.pop("o", {})}, **kw}
    return node(tmp_path, WHY_RUNNER, cfg)


def test_account_why_by_reason_breakeven_and_three_biggest_losses(tmp_path):
    o = why(tmp_path, LIST)
    s = o["stats"]
    no_junk(o["text"])
    # by exit reason, in the plain order 손절 · 계단 잠금 · 규칙 청산 · 익절 · 강제청산, with count / money / mean ROE
    assert [(r["reason"], r["n"], r["pnl"]) for r in s["byReason"]] == [("SL", 3, -100), ("LOCK", 2, 60), ("RULE", 1, -10), ("TP", 1, 60), ("LIQ", 1, -100)]
    assert o["chips"] == ["손절 3번 −$100.00 · 평균 증거금 대비 −33.3%", "계단 잠금 2번 +$60.00 · 평균 증거금 대비 +30.0%", "규칙 청산 1번 −$10.00 · 평균 증거금 대비 −10.0%",
                          "익절 1번 +$60.00 · 평균 증거금 대비 +60.0%", "강제청산 1번 −$100.00 · 평균 증거금 대비 −100.0%"]
    assert abs(s["byReason"][0]["roe"] - (-0.5 - 0.3 - 0.2) / 3) < 1e-9
    # win rate vs the rate the average win (40) and average loss (42) need to break even
    assert s["wins"] == 3 and s["losses"] == 5 and abs(s["winRate"] - 3 / 8) < 1e-9 and abs(s["avgWin"] - 40) < 1e-9 and abs(s["avgLoss"] - 42) < 1e-9
    assert abs(s["breakeven"] - 42 / 82) < 1e-9
    assert "이긴 비율 38%" in o["text"] and "본전에 필요한 비율 51%" in o["text"] and "51% 넘게 이겨야 본전" in o["text"]
    # the three biggest losses (−100, −50, −30) = 180 of the 210 lost, each with its replay link
    assert [t["pnl"] for t in s["big"]] == [-100, -50, -30] and abs(s["bigShare"] - 180 / 210) < 1e-9
    assert "전체 손실의 86%" in o["text"] and len(o["rows"]) == 3
    assert o["links"] == [f"#/replay?acct={ACCT}&at={T0 + i * H}" for i in (7, 1, 2)]
    # where the return stands: start 1,000 -> wallet 790 (−21.0%)
    assert "$1,000" in o["text"] and "$790" in o["text"] and "−21.0%" in o["text"]
    # honesty: small sample, and the net-only note (no fee waterfall)
    assert "표본 적음" in o["text"] and "순손익만 남깁니다" in o["text"] and "수수료 폭포는 그리지 않습니다" in o["text"]


def test_account_why_sample_floor_is_thirty(tmp_path):
    many = [tr(i, 10 if i % 3 else -20, "TP" if i % 3 else "SL") for i in range(1, 31)]
    o = why(tmp_path, many, acct={**ACC, "trades": 30})
    assert "표본 적음" not in o["text"] and o["stats"]["small"] is False
    o = why(tmp_path, many[:29], acct={**ACC, "trades": 29})
    assert "표본 적음" in o["text"] and o["stats"]["small"] is True


def test_account_why_hidden_money_shows_counts_only(tmp_path):
    o = why(tmp_path, [{**t, "pnl": None, "roe": None} for t in LIST], acct={**ACC, "kind": "ds", "wallet": None}, o={"hidden": True})
    no_junk(o["text"])
    assert [c for c in o["chips"]] == ["손절 3번", "계단 잠금 2번", "규칙 청산 1번", "익절 1번", "강제청산 1번"]
    assert "개수만 보여 드립니다" in o["text"] and "숨김" in o["text"]
    for word in ("합계", "본전에 필요한", "다시보기", "가장 큰 손실", "$790"):
        assert word not in o["text"], word
    # the server sent the numbers but hidden is set (the owners' D11): still counts only
    o = why(tmp_path, LIST, o={"hidden": True})
    assert "합계" not in o["text"] and "본전에 필요한" not in o["text"] and "−$100.00" not in o["text"]


def test_account_why_missing_numbers_read_dash_and_empty_and_failed_say_so(tmp_path):
    o = why(tmp_path, LIST, acct={**ACC, "wallet": None})
    no_junk(o["text"])
    assert "→ —" in o["text"]
    assert "아직 닫힌 거래가 없습니다" in why(tmp_path, [], acct={**ACC, "trades": 0})["text"]
    assert "불러오지 못했습니다" in why(tmp_path, LIST, book=None)["text"]
    # only wins: no break-even rate, said in words (never 0)
    o = why(tmp_path, [tr(1, 10, "TP"), tr(2, 5, "TP")])
    assert "본전에 필요한 비율 —" in o["text"] and "아직 진 거래가 없어" in o["text"] and not o["rows"]
    # the server keeps the newest 200: the card says so
    o = why(tmp_path, LIST, acct={**ACC, "trades": 250})
    assert "최근 8번까지만" in o["text"] and "전체 250번 중" in o["text"]
