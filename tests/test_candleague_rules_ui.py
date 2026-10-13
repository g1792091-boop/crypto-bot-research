"""candleague 익절·손절·배수 / 왜 이 성적인가 / 운 vs 실력 / 5년 속도 / 연패 / 묶음 레이스 / 용어 사전 (owners 2026-10-12): the page.

The kits (js/rulekit.js, js/whykit.js) run under node, and the screens they feed (익절·손절·배수, 커스텀값, 계좌 자세히,
점검 진행, 5계좌 비교, 흐름, 요약, 읽는 법) are mounted on the DOM stand-in of test_candleague_rank_ui (text nodes only)
with routes made by the server's own functions (dash.rules_doc, summary.account_insight, summary.race), and the tests
read what reached the page: the exits in plain words, the leverage steps and checks, the five accounts, the coins
today, the leverages used, the luck ranges, the paces, the losing runs, the race and the glossary deep link; DeepSeek
money hidden under the snapshot's switch. Plus the static rules (text only, tokens only, the menu, the stylesheet)."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from candleague import dash as D  # noqa: E402
from candleague import exits as X  # noqa: E402
from candleague import summary as SM  # noqa: E402
import test_candleague_rank_ui as RANK  # noqa: E402  (its DOM stand-in and synthetic league)

STATIC = os.path.join(ROOT, "candleague", "static")
NEW_JS = ["rulekit.js", "whykit.js", "screens/rules.js"]
DAY = 86_400_000
EX = D.load_exchange()


def _run(tmp_path, cfg: dict, body: str) -> dict:
    """Run ``body`` (an async JS block that fills ``out``) after the DOM stand-in with ``cfg`` (routes, local); the
    kits are imported as RK, WK, LK; ``mount(name, query, arg)`` mounts a screen and returns its element."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    (tmp_path / "shim.mjs").write_text(RANK.SHIM)
    code = r"""
import {readFileSync} from "node:fs";
import {install, txt} from "./shim.mjs";
const cfg = JSON.parse(readFileSync(process.argv[2], "utf8"));
install(cfg);
globalThis.location.hash = "";
document.getElementById = (id) => document.documentElement.querySelector(`[id="${id}"]`);
const S = cfg.static;
const LK = await import(`file://${S}/js/lk.js`);
const RK = await import(`file://${S}/js/rulekit.js`);
const WK = await import(`file://${S}/js/whykit.js`);
const doc = cfg.routes["/api/league"];
if (doc) LK.setLeague(doc);
try { await LK.getMeta(); } catch (e) { /* no meta route */ }
const tick = () => new Promise((r) => setTimeout(r, 20));
async function mount(name, query = {}, arg = null) {
  const M = await import(`file://${S}/js/screens/${name}.js`);
  const el = document.createElement("div");
  el.dataset.screen = name;
  document.body.appendChild(el);
  const ctx = {params: {name, arg, query}, alive: () => true, signal: null,
    api: async (p) => { const r = await globalThis.fetch(p); if (!r.ok) { const e = new Error("HTTP " + r.status); e.status = r.status; throw e; } return r.json(); },
    meta: () => LK.getMeta(), onLeague: (fn) => { if (doc) fn(doc); }, onLive: () => () => {}, onPositions: () => () => {},
    every: () => {}, css: async () => null, wide() {}, setTitle() {}, setQuery() {},
    href: (n, a) => `#/${n}${a ? "/" + a : ""}`};
  await M.mount(el, ctx);
  for (let i = 0; i < 6; i++) await tick();
  return el;
}
const out = {};
""" + body + "\nconsole.log(JSON.stringify(out));\nprocess.exit(0);\n"
    (tmp_path / "run.mjs").write_text(code)
    (tmp_path / "cfg.json").write_text(json.dumps({"static": STATIC, "routes": cfg.get("routes", {}), "local": cfg.get("local", {})},
                                                  ensure_ascii=False))
    r = subprocess.run([node, str(tmp_path / "run.mjs"), str(tmp_path / "cfg.json")], capture_output=True, text=True,
                       timeout=120, cwd=str(tmp_path))
    assert r.returncode == 0, (r.stdout[-800:], r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- a league with the rule numbers and the insight
ATR = {tf: {c: {"price": p, "atr": p * f * m, "pct": f * m}
            for c, p, f in (("BTCUSD", 60000.0, 0.0013), ("ETHUSD", 2500.0, 0.0018), ("SOLUSD", 140.0, 0.003),
                            ("DOGEUSD", 0.2, 0.0028), ("LTCUSD", 70.0, 0.0033), ("BCHUSD", 300.0, 0.0033))}
       for tf, m in (("15m", 1.0), ("30m", 1.9), ("1h", 3.4), ("4h", 30.0))}


def _trades(n, wins_at=(), lev=30, side=1, t0=None):
    """n closed trades (newest first, as trades.json), the ones at ``wins_at`` (oldest = 0) won."""
    t0 = t0 or 1_791_000_000_000
    rows = []
    for i in range(n):
        won = i in wins_at
        pnl = 270.0 if won else -95.0
        margin = 1500.0
        x = 100.0 * (1 + side * (pnl + 30.0) / margin / lev)
        rows.append({"symbol": "BTCUSDT", "side": side, "entry_time": t0 + i * 3_600_000, "exit_time": t0 + i * 3_600_000 + 1_800_000,
                     "entry_price": 100.0, "exit_price": x, "exit_reason": "TP" if won else "SL", "leverage": lev,
                     "pnl": pnl, "roe": pnl / margin, "stop_initial": 99.0, "tp_price": 103.0, "mae_price": 99.5, "mfe_price": 101.0})
    return rows[::-1]


def _world(now, ds_money=True):
    lg = RANK._league(now, ds_money=ds_money)
    for a in lg["accounts"]:
        a["exit_ko"] = X.exit_ko(a["exit"])
        a["source"] = {**(a.get("source") or {}), "test_n": 251, "select_n": 200}
        if a["role"] == "base":
            a["exit"], a["exit_ko"] = "ladder|2", X.exit_ko("ladder|2")
    lg["accounts"][0]["exit"], lg["accounts"][0]["exit_ko"] = "tp3R|4", X.exit_ko("tp3R|4")
    for a in lg["accounts"]:
        if a.get("of") == "core-DOGE-15m-1":
            a["exit"], a["exit_ko"] = "tp3R|4", X.exit_ko("tp3R|4")
    lg["start_ms"] = now - 10 * DAY
    full = {a["id"]: _trades(a["trades"] or 0, wins_at=tuple(range(0, a["trades"] or 0, 3))) for a in lg["accounts"]}
    cps = lg["watch"]["checkpoints"]
    lg["watch"] = {**SM.watch_summary(lg["accounts"], {k: v[::-1] for k, v in full.items()}, now, ds_money), "checkpoints": cps}
    book = {}
    for a in lg["accounts"]:
        tr = full[a["id"]]
        if a["kind"] == "ds" and not ds_money:
            tr = [{**t, "win": t["pnl"] > 0, "pnl": None, "roe": None, **{k: None for k in D.DS_TRADE_PRICES}} for t in tr]
        book[a["id"]] = {"equity": None if (a["kind"] == "ds" and not ds_money) else [[lg["start_ms"], 5000.0], [now - DAY, a["wallet"] or 5000.0]],
                         "trades": tr}
    rules = D.rules_doc(lg, book, EX, ATR)
    rules.update(atr=ATR, atr_ms=now - 60_000, atr_source="fake", atr_loading=False, server_ms=now)
    ins = {"generated_ms": lg["generated_ms"], "last_n": 200, "ds_money": ds_money,
           "accounts": {a["id"]: SM.account_insight(book[a["id"]]["trades"], a["trades"], D.ds_hidden(a, lg))
                        for a in lg["accounts"]}}
    race = {**SM.race(lg["accounts"], {k: v for k, v in book.items() if v["equity"]}, lg["start_ms"], lg["done_ms"]),
            "generated_ms": lg["generated_ms"], "ds_money": ds_money}
    meta = json.load(open(os.path.join(ROOT, "candleague", "data", "strategies_ko.json")))
    for k, v in RANK.META["strategies"].items():                 # the synthetic league's names the real file lacks
        meta["strategies"].setdefault(k, {**v, "kind": "ds" if k.startswith("F") else "core", "family": "", "params": [],
                                          "long": "", "short": ""})
    routes = {**RANK._routes(lg, now), "/api/meta": meta, "/api/rules": rules, "/api/insight": ins, "/api/race": race,
              "/api/checkpoints": {"due": [], "results": {}}}
    for a in lg["accounts"]:
        routes[f"/api/trades/{a['id']}"] = book[a["id"]]
    return lg, routes


# ---------------------------------------------------------------- the pure helpers
def _binom_range(n, p, tail=0.05):
    cdf = lambda k: sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))  # noqa: E731
    lo = 0
    while lo < n and cdf(lo) <= tail:
        lo += 1
    hi = n
    while hi > 0 and 1 - cdf(hi - 1) <= tail:
        hi -= 1
    return [lo, hi]


def test_luck_pace_and_streak_helpers(tmp_path):
    now = int(time.time() * 1000)
    lg, routes = _world(now)
    o = _run(tmp_path, {"routes": routes}, r"""
out.ranges = [[20, 0.5], [33, 0.5], [23, 0.05], [1, 0.5], [0, 0.5]].map(([n, p]) => WK.binomRange(n, p));
out.cdf = WK.binomCdf(3, 10, 0.5);
out.rows = [WK.luckRow(17, 20, 0.5).tone, WK.luckRow(10, 20, 0.5).tone, WK.luckRow(2, 20, 0.5).tone];
const ix = LK.index(doc);
const c = ix.byId["core-DOGE-15m-1"];
out.pace = WK.pace5y(c, doc);
out.paceNull = WK.pace5y({...c, source: {}}, doc);
out.paceTxt = txt(WK.paceLine5y(c, doc));
out.luck = WK.luckRows(doc);
out.luckTxt = txt(WK.luckBody(doc));
out.short = txt(WK.luckShort(doc));
const ins = cfg.routes["/api/insight"].accounts;
out.streak = txt(WK.streakLine(ins["ds-F10_OTE-1h-1"]));
out.streakNone = txt(WK.streakLine(null));
out.whyShort = txt(WK.whyShort(ins["core-DOGE-15m-1"]));
out.fall = WK.waterfall(ins["core-DOGE-15m-1"]).map((x) => [x.key, Math.round(x.from * 100) / 100, Math.round(x.to * 100) / 100]);
""")
    assert o["ranges"][:3] == [_binom_range(20, 0.5), _binom_range(33, 0.5), _binom_range(23, 0.05)]
    assert o["ranges"][0] == [6, 14] and o["ranges"][3] == [0, 1] and o["ranges"][4] == [0, 0]
    assert o["cdf"] == pytest.approx(176 / 1024)
    assert o["rows"] == ["above", "inside", "below"]
    p = o["pace"]
    assert p["rate"] == pytest.approx(251 / 1004) and p["days"] == pytest.approx(10 - 2 / 1440, abs=1e-6)
    assert p["expect"] == pytest.approx(251 / 1004 * p["days"]) and p["actual"] == 12
    assert p["day30"] == pytest.approx(lg["start_ms"] + 30 / (251 / 1004) * DAY)
    assert [round(x["n"], 3) for x in p["at"]] == [round(251 / 1004 * (c["ms"] - lg["start_ms"]) / DAY, 3) for c in lg["watch"]["checkpoints"]]
    assert o["paceNull"] is None
    assert "하루 약 0.25번 → 지금쯤 많아야 약" in o["paceTxt"] and "(실제 12번)" in o["paceTxt"] and "30번은 빨라도" in o["paceTxt"]
    assert "한 번에 포지션 하나" in o["paceTxt"] and "꽤 느림" not in o["paceTxt"]
    # the league: DOGE beats its flip, N03 does not, F10 beats its flip; base comparisons likewise from mean_ret
    assert o["luck"]["flip"]["k"] == 2 and o["luck"]["flip"]["n"] == 4 and o["luck"]["flip"]["tone"] == "inside"
    assert "동전보다 나은 후보" in o["luckTxt"] and "운만으로" in o["luckTxt"] and "경고등 켜진 후보" in o["luckTxt"]
    assert o["short"].startswith("동전보다 나은 후보 2 / 4 · 운만으로도 ")
    assert "최장 연패" in o["streak"] and "이 승률" in o["streak"] and "보통 최장" in o["streak"]
    assert o["streakNone"] == "아직 닫힌 거래가 없습니다"
    assert o["whyShort"].startswith("손절 8 · 익절 4 · 수수료·펀딩 −$") and "최장 연패 2" in o["whyShort"]
    assert [x[0] for x in o["fall"]] == ["gross", "cost", "net"] and o["fall"][1][2] == o["fall"][2][2]


def test_rule_words(tmp_path):
    now = int(time.time() * 1000)
    lg, routes = _world(now)
    o = _run(tmp_path, {"routes": routes}, r"""
const R = cfg.routes["/api/rules"];
const tp = (k, v, f) => ({kind: k, val: v, first_lock: f});
out.short = [RK.tpShort(tp("R", 3)), RK.tpShort(tp("roe", 0.5)), RK.tpShort(tp("ladder", null, 0.1)), RK.tpShort(tp("ladder_R", 2, 0.1))];
out.words = [RK.tpWords(tp("R", 3)), RK.tpWords(tp("roe", 0.5)), RK.tpWords(tp("ladder", null, 0.1))];
out.stop = [txt(document.createElement("p")), ...[[4, "15m", tp("R", 3)], [2, "1h", tp("ladder", null, 0.1)]].map(([k, tf, t]) => {
  const p = document.createElement("p"); p.append(...RK.stopWords(k, tf, t).filter((x) => x != null)); return txt(p); })];
const p = R.picks["core-DOGE-15m-1"];
const be = document.createElement("p"); be.append(...RK.beWords(p).flat().filter((x) => x != null));
out.be = txt(be);
const lv = document.createElement("p"); lv.append(...RK.levWords(p)); out.lev = txt(lv);
const lvd = document.createElement("p"); lvd.append(...RK.levWords(R.picks["ds-F10_OTE-1h-1"])); out.levDs = txt(lvd);
out.pair = [RK.levPair({best: 40, normal: 30}, true), RK.levPair({normal: 0}, false), RK.levPair(null, true)];
out.used = [RK.usedChips({"30": 3, "20": 9}).querySelectorAll(".rl-lev").map(txt), txt(RK.usedChips({})), txt(RK.usedChips(null))];
out.box = txt(RK.ruleBox(LK.index(doc).byId["core-DOGE-15m-1"], R));
out.boxBare = txt(RK.ruleBox(LK.index(doc).byId["core-DOGE-15m-1"], null));
out.rule = txt(RK.levRuleBody(R));
const body = RK.pickRuleBody(p, R);
out.pick = txt(body);
out.tiles = body.querySelectorAll(".rl-coin").map(txt);
out.rows = body.querySelectorAll(".rl-frow").map((r) => [r.getAttribute("href"), txt(r)]);
out.roles = txt(RK.rolesTable());
out.terms = body.querySelectorAll(".rl-term").map((a) => a.getAttribute("href"));
""")
    assert o["short"] == ["고정 익절 3R", "고정 익절 증거금 대비 +50%", "계단 잠금 10%부터", "계단 잠금 + 익절 2R"]
    assert "손절 거리의 3배" in o["words"][0] and "예: 손절이 1% 아래면 익절은 3% 위" in o["words"][0]
    assert "20배면 약 2.6%" in o["words"][1] and "30배면 약 1.8%" in o["words"][1]
    assert "+12%가 되면 손절선을 +10% 자리로" in o["words"][2] and "5%씩" in o["words"][2]
    assert "15분봉 최근 14개" in o["stop"][1] and "× 4만큼" in o["stop"][1] and "움직이지 않습니다" in o["stop"][1]
    assert "1시간봉" in o["stop"][2] and "계단 잠금으로 손절선이 올라갑니다" in o["stop"][2]
    assert o["be"].startswith("25% (비용 전)") and "4번 중 1번만 이겨도 본전" in o["be"]
    assert "수수료·슬리피지(손절로 끝나면 0.14%, 지정가 익절로 끝나면 0.09%)" in o["be"]
    assert "좋은 자리" in o["lev"] and "50배 → 40배 → 30배 → 20배" in o["lev"] and "약 22%" in o["lev"]
    assert "딥시크 매매법은 진입 강도 점수가 없어서" in o["levDs"] and "30배 → 20배" in o["levDs"]
    assert o["pair"] == ["40배 / 30배", "못 들어감", "—"]
    assert o["used"] == [["30배 3번", "20배 9번"], "아직 없음", "숨김"]
    assert "고정 익절 3R = 손절 거리의 3배 가면 지정가로" in o["box"] and "4 ATR = 15분봉 평균 움직임의 4배" in o["box"]
    assert "25% (비용 전)" in o["box"] and "좋은 자리 50→40→30→20배" in o["box"] and "계단 잠금 10%부터 · 손절 2 ATR" in o["box"]
    assert "움직이지 않음" in o["box"]
    assert "익절·손절·배수 자세히" in o["boxBare"] and "고정 익절 3R · 손절 4 ATR" in o["boxBare"]
    r = o["rule"]
    for needle in ("거래소 한도 안이고 두 가지 안전 검사를 모두 통과한 첫 배수", "들어가지 않고 건너뜁니다", "50배", "0.48% · 1/4은 2.3%", "BTC 1.6%",
                   "진입 때 청산까지 (후보 · 1/4 크기)", "LTC·BCH 거래소 한도로 불가", "50배 LTC · BCH (거래소가 40배까지)",
                   "1/4 계좌는 주문이 작아 이 한도에 걸리지 않습니다", "거래소 한도",
                   "청산 검사", "손실 검사", "잔고의 15% 이하", "손절이 넓을수록 배수가 내려갑니다", "40배(한도 0.82%)",
                   "잔고 $5,000에서 30배면 증거금 $1,500, 포지션 $45,000", "지금까지 실제로 쓴 배수"):
        assert needle in r, needle
    assert "지금 이 숫자면" in o["pick"] and "‘좋은 자리 / 보통 자리’" in o["pick"]
    assert len(o["tiles"]) == 6 and o["tiles"][0].startswith("BTCATR 0.13%") and "배수좋은 / 보통후보40배 / 30배" in o["tiles"][0]
    assert "1/450배 / 30배" in o["tiles"][0] and "본전 (비용 포함)" in o["tiles"][0]
    assert [h for h, _ in o["rows"]] == ["#/account/core-DOGE-15m-1", "#/account/core-DOGE-15m-1-q", "#/account/core-DOGE-15m-1-x",
                                         "#/account/base-core-DOGE-15m", "#/account/core-DOGE-15m-1-flip"]
    assert "계단 잠금 10%부터 · 손절 2 ATR" in o["rows"][3][1] and "증거금 1/4" in o["rows"][1][1] and "방향은 동전" in o["rows"][4][1]
    assert "30배 12번" in o["rows"][0][1] and "거래 12번" in o["rows"][0][1] and "쓴 배수" in o["rows"][0][1]
    for needle in ("후보", "1/4 크기", "청산만 바꾼 기본값", "기본값", "동전 던지기", "증거금만 1/4 (50배 12.5%", "동전 던지기 (좋은 자리 여부도",
                   "좋아진 게 숫자 덕인가 익절·손절 덕인가", "방향을 맞힌 건가 운인가"):
        assert needle in o["roles"], needle
    assert "#/howto?q=ATR" in o["terms"] and "#/howto?q=%EC%A2%8B%EC%9D%80%20%EC%9E%90%EB%A6%AC" in o["terms"]
    # the 4 ATR pick against the 기본값's 2 ATR: the base is narrower, so its leverage tends to be higher
    assert "손절이 2 ATR로 이 후보(4 ATR)보다 좁아서" in o["pick"]


def test_rules_screen(tmp_path):
    """The 익절·손절·배수 screen: the short answers from the data, the leverage rule, the five accounts, the picks'
    list (one per pick, the chosen one pressed) and the chosen pick's card; ?pick= chooses, a click changes it."""
    now = int(time.time() * 1000)
    lg, routes = _world(now)
    o = _run(tmp_path, {"routes": routes}, r"""
const el = await mount("rules", {pick: "ds-F10_OTE-1h-1"});
out.answers = txt(el.querySelector(".rl-qa"));
out.rows = el.querySelectorAll(".rl-row").map((b) => [txt(b), b.getAttribute("aria-pressed")]);
out.card = txt(el.querySelector(".rl-pickcard"));
out.page = txt(el);
el.querySelectorAll(".rl-row")[0].fire("click");
await tick();
out.card2 = txt(el.querySelector(".rl-pickcard"));
out.pressed2 = el.querySelectorAll(".rl-row").filter((b) => b.getAttribute("aria-pressed") === "true").map(txt);
""")
    a = o["answers"]
    assert "후보 5개 모두 5년 탐색(84가지 청산 중)에서 각자 고른 고정 익절과 ATR 손절" in a
    assert "익절: 3R 5개" in a and "손절: 2 ATR 4개 · 4 ATR 1개" in a and "계단 잠금을 쓰는 후보는 없습니다" in a
    assert "규칙봇과 같은 규칙" in a and "1 ATR 이상 여유" in a and "잔고의 15% 이하" in a and "딥시크는 늘 보통 자리" in a
    assert "50배 → 40배 → 30배 → 20배, 보통 자리는 30배 → 20배" in a and "거래소가 그 주문 크기에 허용하는 배수" in a
    assert "후보 크기에서는 50배 LTC · BCH (거래소가 40배까지)" in a
    assert "후보 계좌가 지금까지 쓴 배수" in a and "30배 48번" in a
    assert re.search(r"\d\d/\d\d \d\d:\d\d KST \(설치한 때\)부터", a) and "$5,000으로 시작" in a and "D+10" in a
    assert len(o["rows"]) == 5
    pressed = [t for t, p in o["rows"] if p == "true"]
    assert len(pressed) == 1 and "ICT OTE" in pressed[0] and "3R (손절 거리의 3배)" in pressed[0] and "30→20배" in pressed[0]
    assert "4 ATR" in [t for t, _ in o["rows"] if "도지 봇" in t][0] and "50→40→30→20배" in [t for t, _ in o["rows"] if "도지 봇" in t][0]
    assert "ICT OTE · 1시간" in o["card"] and "늘 보통 자리" in o["card"] and "지금 이 숫자면" in o["card"] and "매매법 코드 F10_OTE" in o["card"]
    assert "배수(레버리지) 규칙" in o["page"] and "계좌 5개는 무엇이 다른가" in o["page"] and "후보마다 익절 · 손절" in o["page"]
    assert "도지 봇 · 15분" in o["card2"] and "좋은 자리 가능" in o["card2"] and len(o["pressed2"]) == 1 and "도지 봇" in o["pressed2"][0]


def test_hidden_deepseek_money_on_the_new_pieces(tmp_path):
    """The snapshot's DeepSeek money switch off: no leverage used, no P&L, no costs, no wallet of a DeepSeek account on
    the rules screen, the why card, the 5계좌 short line or the race; counts and labels stay."""
    now = int(time.time() * 1000)
    lg, routes = _world(now, ds_money=False)
    o = _run(tmp_path, {"routes": routes}, r"""
const el = await mount("rules", {pick: "ds-F10_OTE-1h-1"});
out.card = txt(el.querySelector(".rl-pickcard"));
const ins = cfg.routes["/api/insight"].accounts;
const a = LK.index(doc).byId["ds-F10_OTE-1h-1"];
out.why = txt(WK.whyCard(a, ins[a.id], {}));
out.short = txt(WK.whyShort(ins[a.id]));
const W = await import(`file://${S}/js/screens/weekly.js`);
out.race = txt(W.racePool("ds", cfg.routes["/api/race"], doc));
""")
    assert "숨김" in o["card"] and "30배 31" not in o["card"]
    assert "나간 이유" in o["why"] and "개수만" in o["why"] and "$" not in o["why"] and "손절 20번" in o["why"] and "익절 11번" in o["why"]
    assert "최장 연패" in o["why"]
    assert "$" not in o["short"] and "수수료" not in o["short"] and "손절 20" in o["short"]
    assert "딥시크 금액 숨김 설정이라 잔고 흐름이 없습니다" in o["race"]
    for leak in RANK.LEAKS:
        if leak != "20배":
            assert leak not in o["card"] + o["why"] + o["short"], leak


def test_why_card_with_money(tmp_path):
    now = int(time.time() * 1000)
    lg, routes = _world(now)
    o = _run(tmp_path, {"routes": routes}, r"""
const ins = cfg.routes["/api/insight"].accounts;
const ix = LK.index(doc);
const a = ix.byId["core-DOGE-15m-1"];
const R = cfg.routes["/api/rules"];
const card = WK.whyCard(a, ins[a.id], {flip: ix.byId["core-DOGE-15m-1-flip"], rule: R.picks[a.id], pick: a, href: (t) => `#/terminal?at=${t.entry_time}`});
out.text = txt(card);
out.links = card.querySelectorAll("a").map((x) => x.getAttribute("href"));
out.big = card.querySelectorAll(".wy-brow").length;
out.empty = txt(WK.whyCard(ix.byId["core-OBV-4h-1"], ins["core-OBV-4h-1"], {}));
const capped = {...ins[a.id], capped: true, total: 260};
out.capped = txt(WK.whyCard(a, capped, {}));
""")
    t = o["text"]
    for needle in ("왜 +24.0%인가", "$5,000.00 → $6,200.00 (+24.0%)", "같은 후보의 동전 계좌", "−18.0%", "차이 +42.0%p",
                   "닫힌 거래의 손익이 어디로 갔나", "수수료·펀딩 전", "실제 손익", "나간 이유별", "손절 8번", "익절 4번",
                   "이긴 비율 33%", "본전에 필요한 비율 26%", "규칙대로라면 25% (비용 전)", "실제로 쓴 배수", "30배 12번",
                   "가장 큰 손실 3번이 전체 손실의 38%", "연패 맥락", "최장 연패 2번"):
        assert needle in t, needle
    assert o["big"] == 3 and "#/rules?pick=core-DOGE-15m-1" in o["links"] and any(x.startswith("#/terminal?at=") for x in o["links"])
    assert "아직 닫힌 거래가 없습니다" in o["empty"]
    assert "최근 12번 기준 (전체 260번 중)" in o["capped"]


def test_screens_carry_the_new_parts(tmp_path):
    """커스텀값 (the rule box, the 5-year pace), 계좌 자세히 (왜 이 성적인가, the rule card), 점검 진행 (운 vs 실력,
    후보마다 속도 · 연패), 5계좌 비교 (the short line, the role words), 흐름 (묶음 레이스), 요약 (the luck line), 매매법
    (the rules link), 읽는 법 (the glossary, ?q= marks the term)."""
    now = int(time.time() * 1000)
    lg, routes = _world(now)
    o = _run(tmp_path, {"routes": routes}, r"""
out.custom = txt(await mount("custom", {s: "DOGE"}));
const acc = await mount("account", {}, "core-DOGE-15m-1");
out.account = txt(acc);
out.accountWhy = !!acc.querySelector(".wy") && !!acc.querySelector(".rl-pickcard");
const chk = await mount("check");
out.check = txt(chk);
out.paceRows = chk.querySelectorAll(".pc-tbl tbody tr").map(txt);
out.compare = txt(await mount("compare"));
const wk = await mount("weekly");
out.weekly = txt(wk);
out.raceSvg = wk.querySelectorAll(".rc-pool svg").length;
out.home = txt(await mount("home"));
const st = await mount("strategies");
out.stratLinks = st.querySelectorAll("a").map((x) => x.getAttribute("href")).filter((x) => x && x.startsWith("#/rules"));
const H = await import(`file://${S}/js/screens/howto.js`);
out.gl = [H.glossaryOf("atr") && H.glossaryOf("atr")[0], H.glossaryOf("레버리지") && H.glossaryOf("레버리지")[0], H.glossaryOf("nope")];
const how = await mount("howto", {q: "R"});
out.howOn = how.querySelector(".gl-list").children.filter((d) => d.classList.contains("on")).map((d) => d.getAttribute("id"));
out.how = txt(how);
""")
    c = o["custom"]
    assert "익절 · 손절 · 배수" in c and "고정 익절 3R = 손절 거리의 3배 가면 지정가로" in c and "5년 시험 속도(많아야) vs 지금" in c
    assert "익절·손절·배수 자세히 (지금 코인별 배수)" in c
    assert o["accountWhy"] and "왜 +24.0%인가" in o["account"] and "익절 · 손절 · 배수" in o["account"] and "지금 이 숫자면" in o["account"]
    ch = o["check"]
    assert "운 vs 실력" in ch and "동전보다 나은 후보" in ch and "후보마다 속도 · 연패" in ch and "5년 속도면 지금쯤" in ch
    assert len(o["paceRows"]) == 5 and any("도지 봇" in r and "12번" in r for r in o["paceRows"])
    assert "손절 8 · 익절 4" in o["compare"] and "진입: 커스텀값" in o["compare"] and "방향: 동전 던지기" in o["compare"]
    assert "묶음 레이스" in o["weekly"] and "동전 계좌 가운데 50%" in o["weekly"] and o["raceSvg"] >= 1
    assert "운만으로" not in o["weekly"] and "1시간마다 · " in o["weekly"] and "개 점" in o["weekly"] and "칸 (" not in o["weekly"]
    assert "동전보다 나은 후보 2 / 4" in o["home"]
    assert "#/rules?s=DOGE" in o["stratLinks"]
    assert o["gl"] == ["ATR", "배수", None]
    assert o["howOn"] == ["gl-R"] and "용어 사전" in o["how"] and "본전 승률" in o["how"] and "익절·손절·배수" in o["how"]


def test_static_rules_for_the_new_files():
    """Text only in the new modules; the shared stylesheet is served, loaded by the page, uses only the tokens and the
    type scale; the menu has the new screen in the 매매법 group and 흐름 for the old 주간 흐름."""
    for f in NEW_JS + ["screens/weekly.js", "screens/check.js", "screens/howto.js"]:
        src = open(os.path.join(STATIC, "js", f)).read()
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "document.write", "new Function", "eval("):
            assert bad not in src, (f, bad)
    assert "insight.css" in D.STATIC_FILES and "js/rulekit.js" in D.STATIC_FILES and "js/screens/rules.js" in D.STATIC_FILES
    assert '<link rel="stylesheet" href="/static/insight.css">' in open(os.path.join(STATIC, "index.html")).read()
    css = open(os.path.join(STATIC, "insight.css")).read()
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", css)
    for m in re.finditer(r"font(?:-size)?:\s*([^;]+);", css):
        assert "var(--t-" in m.group(1), m.group(0)
    app = open(os.path.join(STATIC, "js", "app.js")).read()
    assert '{id: "rules", ko: "익절·손절·배수", group: "method"}' in app and '{id: "weekly", ko: "흐름", group: "study"}' in app
    assert 'rules: "rules"' in app
    node = shutil.which("node")
    if node:
        for f in NEW_JS:
            with open(os.path.join(STATIC, "js", f)) as fh:
                r = subprocess.run([node, "--input-type=module", "--check"], stdin=fh, capture_output=True, text=True)
            assert r.returncode == 0, (f, r.stderr[:400])


# ---------------------------------------------------------------- review fixes (2026-10-12, second pass)
def test_rule_card_words_follow_the_pick(tmp_path):
    """The 기본값 note follows the stop widths (the leverage comes from the stop alone); a lock exit's box says the stop
    moves; equal leverages read as one word; the ROE tile says which leverage its take-profit distance assumes; the
    chips carry 번 and an empty account keeps the chips' place."""
    now = int(time.time() * 1000)
    lg, routes = _world(now)
    o = _run(tmp_path, {"routes": routes}, r"""
const R = cfg.routes["/api/rules"];
const base = {id: "base-x", exit: "ladder|2", exit_ko: "계단 잠금 10%부터 · 손절 2 ATR"};
const pk = (k) => ({id: "x", exit: `tp3R|${k}`, stop_atr: k, tf: "1h", tp: {kind: "R", val: 3}, roles: {base}});
out.notes = [4, 2, 1.5].map((k) => RK.baseNote(pk(k), R));
out.noBase = RK.baseNote({...pk(4), roles: {}}, R);
out.pairs = [RK.levPair({best: 0, normal: 0}, true), RK.levPair({best: 30, normal: 30}, true), RK.levPair({best: 40, normal: 0}, true)];
const lock = {id: "core-DOGE-15m-1", tf: "15m", tp: {kind: "ladder", val: null, first_lock: 0.1}, stop_atr: 2, best_ok: true, breakeven: null, roles: {}};
out.lockBox = txt(RK.ruleBox({id: "core-DOGE-15m-1", exit_ko: "x"}, {...R, picks: {"core-DOGE-15m-1": lock}}));
const roe = {...R.picks["ds-F10_OTE-1h-1"], tp: {kind: "roe", val: 0.5}};
out.roeTiles = RK.pickRuleBody(roe, R).querySelectorAll(".rl-coin").map(txt);
const ln = R.picks["ds-F10_OTE-1h-1"].now.BTCUSD.lev.cand.normal;
out.ln = ln;
out.emptyCls = RK.usedChips({}).getAttribute("class");
out.hidCls = RK.usedChips(null).getAttribute("class");
""")
    assert "손절이 2 ATR로 이 후보(4 ATR)보다 좁아서, 같은 자리라면 배수가 더 높게" in o["notes"][0]
    assert "손절이 이 후보와 같은 2 ATR이라 같은 자리라면 배수도 같습니다" in o["notes"][1] and "더 높게" not in o["notes"][1]
    assert "손절이 2 ATR로 이 후보(1.5 ATR)보다 넓어서, 같은 자리라면 배수가 같거나 더 낮게" in o["notes"][2]
    assert o["noBase"] is None
    assert o["pairs"] == ["둘 다 못 들어감", "둘 다 30배", "40배 / 못 들어감"]
    assert "수익이 나면 계단 잠금으로 올라감" in o["lockBox"] and "움직이지 않음" not in o["lockBox"] and "미리 셀 수 없음" in o["lockBox"]
    assert o["ln"] in (20, 30) and f"익절 거리 ({o['ln']}배면)" in o["roeTiles"][0]
    assert all("익절 거리 (" in t and "배면)" in t for t in o["roeTiles"] if "후보못 들어감" not in t)
    assert "rl-used" in o["emptyCls"] and "rl-used" in o["hidCls"]


def test_rules_list_header_divider_fold_and_pick_choice(tmp_path):
    """The list has its column names (a PC), a divider per kind, the order of steps in full and 배수에 따라 for an ROE
    take-profit; a ?pick= of another account means its pick, a pick the filters leave out falls back to the first row,
    a junk id too; on a phone the rows past LIST_FOLD fold behind "나머지 N개 보기" (the chosen one stays)."""
    now = int(time.time() * 1000)
    lg, routes = _world(now)
    o = _run(tmp_path, {"routes": routes}, r"""
const M = await import(`file://${S}/js/screens/rules.js`);
const R = cfg.routes["/api/rules"];
const el = await mount("rules", {pick: "base-core-DOGE-15m"});
out.hd = txt(el.querySelector(".rl-listhd"));
out.div = el.querySelectorAll(".rl-divider").map(txt);
out.pressedBase = el.querySelectorAll(".rl-row").filter((b) => b.getAttribute("aria-pressed") === "true").map(txt);
out.cardBase = txt(el.querySelector(".rl-pickcard"));
const el2 = await mount("rules", {kind: "core", pick: "ds-F10_OTE-1h-1"});
out.pressedKind = el2.querySelectorAll(".rl-row").filter((b) => b.getAttribute("aria-pressed") === "true").map(txt);
out.cardKind = txt(el2.querySelector(".rl-pickcard"));
out.rowsKind = el2.querySelectorAll(".rl-row").length;
const ix = LK.index(doc);
const rows = ix.cands;
out.choose = [M.choosePick("core-DOGE-15m-1-q", ix, rows), M.choosePick("base-core-DOGE-15m", ix, rows), M.choosePick("nope", ix, rows),
  M.choosePick("ds-F10_OTE-1h-1", ix, rows.filter((c) => c.kind === "core")), M.choosePick(null, ix, [])];
out.first = rows[0].id;
out.firstCore = rows.filter((c) => c.kind === "core")[0].id;
// twelve rows: four fold behind the button on a phone, the chosen one (the last) stays
const many = Array.from({length: 12}, (_, i) => ({...rows[0], id: `fake-${i}`}));
const L = M.pickList(many, R, "fake-11", () => {}, {});
out.extra = L.querySelectorAll(".rl-row.rl-extra").length;
out.more = txt(L.querySelector(".rl-more"));
out.lastOn = L.querySelectorAll(".rl-row").at(-1).getAttribute("class");
out.openCls = M.pickList(many, R, "fake-0", () => {}, {more: true}).getAttribute("class");
const roe = {...R, picks: {x: {tp: {kind: "roe", val: 0.5}, stop_atr: 4, breakeven: null, best_ok: false, roles: {}}}};
out.roeRow = txt(M.pickRow({id: "x", tf: "1h", name: "OBV_S", kind: "core"}, roe, false, () => {}));
""")
    assert o["hd"] == "매매법 · 봉익절손절본전 승률 (비용 전)배수 순서후보 계좌가 쓴 배수"
    assert len(o["div"]) == 2 and o["div"][0].startswith("기존 36") and "좋은 자리면 50배부터" in o["div"][0]
    assert "딥시크" in o["div"][1] and "늘 보통 자리 (30배부터)" in o["div"][1]
    assert len(o["pressedBase"]) == 1 and "도지 봇" in o["pressedBase"][0] and "도지 봇 · 15분" in o["cardBase"]
    assert "이 후보의 규칙을 찾지 못했습니다" not in o["cardBase"]
    assert len(o["pressedKind"]) == 1 and "ICT OTE" not in o["pressedKind"][0] and "ICT OTE" not in o["cardKind"] and o["rowsKind"] == 3
    assert o["choose"] == ["core-DOGE-15m-1", "core-DOGE-15m-1", o["first"], o["firstCore"], None]
    assert o["extra"] == 4 and o["more"] == "나머지 4개 보기" and "rl-extra" in o["lastOn"] and "on" in o["lastOn"].split()
    assert "open" in o["openCls"].split()
    assert "배수에 따라" in o["roeRow"] and "증거금 대비 +50%" in o["roeRow"] and "배수따라" not in o["roeRow"]


def test_account_page_of_a_base_account_leads_with_its_own_exit(tmp_path):
    now = int(time.time() * 1000)
    lg, routes = _world(now)
    o = _run(tmp_path, {"routes": routes}, r"""
const el = await mount("account", {}, "base-core-DOGE-15m");
const card = el.querySelector(".rl-pickcard");
out.card = txt(card);
out.own = card.querySelector(".rl-own") ? txt(card.querySelector(".rl-own")) : null;
const c2 = (await mount("account", {}, "core-DOGE-15m-1")).querySelector(".rl-pickcard");
out.candOwn = !!c2.querySelector(".rl-own");
out.candCard = txt(c2);
""")
    own = o["own"]
    assert own and own.startswith("기본값 이 계좌의 익절·손절: 계단 잠금 10%부터 · 손절 2 ATR")
    assert "+12%가 되면 손절선을 +10% 자리로" in own and "2 ATR" in own and "계단 잠금으로 손절선이 올라갑니다" in own
    assert "아래는 이 후보(후보 계좌)의 익절·손절입니다" in own
    assert o["card"].index("이 계좌의 익절·손절") < o["card"].index("고정 익절 3R")
    assert "이 후보의 익절·손절과 계좌 5개 공통 배수 규칙" in o["card"] and "이 후보의 계좌 5개 공통 규칙" not in o["card"]
    assert o["candOwn"] is False and "이 후보의 익절·손절과 계좌 5개 공통 배수 규칙" in o["candCard"]


def test_why_card_notes_follow_the_exit(tmp_path):
    """연패 맥락 speaks of the account's own exit; a money break-even far above the rule's says why; three or fewer
    losses carry no share; without a pick the leverage link goes to the rules screen."""
    now = int(time.time() * 1000)
    lg, routes = _world(now)
    o = _run(tmp_path, {"routes": routes}, r"""
out.notes = ["tp3R|4", "tp2R|2", "roe50|4", "ladder|2", null].map((e) => WK.streakNote(e));
const ins = cfg.routes["/api/insight"].accounts;
const ix = LK.index(doc);
const a = ix.byId["core-DOGE-15m-1"];
const R = cfg.routes["/api/rules"];
const skew = {...ins[a.id], breakeven: 0.52};
out.skew = txt(WK.whyCard(a, skew, {rule: R.picks[a.id], pick: a}));
out.plain = txt(WK.whyCard(a, ins[a.id], {rule: R.picks[a.id], pick: a}));
const b = ix.byId["base-core-DOGE-15m"];
out.base = txt(WK.whyCard(b, ins[b.id], {}));
const few = {...ins[a.id], losses: 2, big: ins[a.id].big.slice(0, 2), big_share: 1};
out.few = txt(WK.whyCard(a, few, {pick: a}));
out.links = WK.whyCard(b, ins[b.id], {}).querySelectorAll("a").map((x) => x.getAttribute("href"));
""")
    n3, n2, nroe, nlock, nnone = o["notes"]
    assert "3R은 4번 중 1번만 이겨도 본전" in n3 and "(보통 30~35%)" in n3
    assert "2R은 3번 중 1번만 이겨도 본전" in n2 and "30~35%" not in n2
    assert "증거금 대비 익절" in nroe and "3R" not in nroe
    assert "계단 잠금은 작게 자주 이기는 방식" in nlock and "3R" not in nlock
    assert "3R" not in nnone and "보통 범위 안의 연패로 매매법을 판단하지 않습니다" in nnone
    assert "규칙보다 높은 이유" in o["skew"] and "돈으로는 3배가 안 됩니다" in o["skew"]
    assert "규칙보다 높은 이유" not in o["plain"]
    assert "3R" not in o["base"].split("연패 맥락")[1] and "계단 잠금은 작게 자주" in o["base"]
    assert "손실 2번 (큰 순서)" in o["few"] and "전체 손실의" not in o["few"]
    assert "#/rules" in o["links"] and not any(x.startswith("#/rules?pick=base-") for x in o["links"])


def test_pace_is_an_upper_bound(tmp_path):
    """The 5-year pace counted every signal; a league account holds one position: the numbers read 많아야 / 빨라도, no
    '꽤 느림' warning, a past 30-trade date says so, and a phone gets one stacked row per pick."""
    now = int(time.time() * 1000)
    lg, routes = _world(now)
    o = _run(tmp_path, {"routes": routes}, r"""
const ix = LK.index(doc);
const c = {...ix.byId["core-DOGE-15m-1"], trades: 4};
const old = {...doc, start_ms: doc.done_ms - 200 * 86400000};
const p = WK.pace5y(c, old);
out.past = p.past30;
out.ratio = p.ratio;
out.line = txt(WK.paceLine5y(c, old));
out.fresh = WK.pace5y(c, doc).past30;
const C = await import(`file://${S}/js/screens/check.js`);
const t = C.paceTable(old, cfg.routes["/api/insight"]);
out.heads = t.querySelectorAll("th").map(txt);
out.cells = t.querySelectorAll(".pc-tbl tbody tr").map(txt);
out.phone = t.querySelectorAll(".pc-ph .pc-prow").map(txt);
out.notes = t.querySelectorAll("p.note").map(txt);
""")
    assert o["past"] is True and o["ratio"] < 0.5 and o["fresh"] is False
    assert "꽤 느림" not in o["line"] and "30번은 빨라도" in o["line"] and "(지남)" in o["line"] and "많아야" in o["line"]
    assert "5년 속도면 지금쯤 (많아야)" in o["heads"] and "30번 되는 날 (빨라도)" in o["heads"]
    assert any(h.startswith("5년 속도면 ") and h.endswith("까지 (많아야)") for h in o["heads"])
    assert any("지남" in r and "실제 " in r for r in o["cells"])
    assert len(o["phone"]) == 5 and all("5년 속도면 많아야" in r and "최장 연패" in r for r in o["phone"])
    assert o["notes"][0].startswith("5년 시험은 여섯 코인의 신호를 모두 셌고") and "한 번에 포지션 하나만" in o["notes"][0]


def test_glossary_luck_line_and_position_rule_line(tmp_path):
    """The glossary's fees (a limit take-profit is 0.02%), the lock's ROE, the new check terms the rules card links to;
    요약's luck line says the range once; the position card's rule is one short line with the link (the full sentence
    stays its tooltip)."""
    now = int(time.time() * 1000)
    lg, routes = _world(now)
    o = _run(tmp_path, {"routes": routes}, r"""
const H = await import(`file://${S}/js/screens/howto.js`);
out.gl = ["포지션 크기", "계단 잠금", "청산 검사", "손실 검사", "손절 거리 한도", "거래소 한도", "좋은 자리"].map((q) => { const g = H.glossaryOf(q); return g ? g[2] : null; });
const R = cfg.routes["/api/rules"];
out.terms = RK.levRuleBody(R).querySelectorAll(".rl-term").map((a) => decodeURIComponent(a.getAttribute("href")));
out.luck = txt(WK.luckShort(doc));
const C = await import(`file://${S}/js/screens/positions-card.js`);
const box = C.whyBox({lev: 30, margin_pct: 0.3, liq_dist_entry: 0.03, pick: "core-DOGE-15m-1",
  why: {group_ko: null, lev_ko: "x", sub_ko: "y", rule_ko: "규칙: 긴 문장", rule_short_ko: "좋은 자리 50→40→30→20배 · 보통 30→20배 · 거래소 한도와 안전 검사를 통과한 첫 배수"}});
out.rule = txt(box.querySelector(".ps-rule"));
out.title = box.getAttribute("title");
""")
    pos, lock, liq, loss, lim, ex, best = o["gl"]
    assert "지정가 익절로 나올 때 0.02%" in pos and "손절로 나올 때 0.05%" in pos
    assert "증거금 대비 순수익(수수료 뺀 ROE)이 +12%" in lock
    assert liq and "1 ATR 이상" in liq and loss and "15% 이하" in loss and lim and "0.48%" in lim and ex and "LTC · BCH" in ex
    assert "40배 → 30배 → 20배" in best
    for t in ("#/howto?q=거래소 한도", "#/howto?q=청산 검사", "#/howto?q=손실 검사", "#/howto?q=손절 거리 한도"):
        assert t in o["terms"], t
    assert o["luck"].count("운만으로") == 1 and "(그 범위 안)" in o["luck"]
    assert o["rule"] == "좋은 자리 50→40→30→20배 · 보통 30→20배 · 거래소 한도와 안전 검사를 통과한 첫 배수 · 배수 규칙 자세히"
    assert o["title"] == "규칙: 긴 문장"


def test_coin_tiles_can_wrap():
    """A tile value ("둘 다 못 들어감") wraps or drops under its label instead of pushing a phone sideways."""
    css = open(os.path.join(STATIC, "insight.css")).read()
    rule = re.search(r"\.rl-cdl dd \{([^}]*)\}", css).group(1)
    assert "white-space: normal" in rule and "min-width: 0" in rule and "nowrap" not in rule
    assert "flex-wrap: wrap" in re.search(r"\.rl-cdl > div \{([^}]*)\}", css).group(1)
    assert re.search(r"\.rl-list:not\(\.open\) \.rl-row\.rl-extra:not\(\.on\)", css)
    assert re.search(r"@media \(max-width: 759px\) \{[^@]*\.tbl-wrap\.pc-pc \{ display: none; \}", css)
