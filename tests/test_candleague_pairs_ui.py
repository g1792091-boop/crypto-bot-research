"""candleague 같은 신호 짝 비교 / 발동 기록 / 매매법별 구조 기준 (js/screens/pairs.js, events.js, judge.js): the owners' new exit league.

The three screens are mounted for real under node on the suite's DOM stand-in (tests/test_candleague_rank_ui.py: text nodes only) with a
synthetic snapshot in the shape the server writes (``lineup``, ``pairs``, ``events``, ``accounts`` of the 49 picks, ``equity0`` 1000) and
GET /api/judge = candleague/data/native_ko.json, and the tests read what reached the page:
  * pairs: the one sentence ("빠른 손절은 같은 신호에서 대조보다 N번 낫고 M번 못했습니다 (평균 +x.x%p)"), a card per kind (짝 수,
    낫다/같다/못하다, 평균 차이, 돈으로 본 차이), the newest pairs in a table (메인 vs 대조: reason, ROE, 낫다/못하다/같다), the kind
    chips and the pager, the explanation of a pair;
  * events: one plain sentence per event, the type word, the chips and the count line, the empty state;
  * judge: the two top boxes (빠른 손절 / 스위칭), a card per strategy (27), the own conditions of the 16, the 11 without them, the counts;
  * absent keys, the old 190-account league, null ROE fields (always "—", never 0), the start wallet ($1,000, never $5,000).
Plus the static rules (text only, tokens only)."""

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

from candleague import rulex  # noqa: E402
import test_candleague_rank_ui as RANK  # noqa: E402  (its DOM stand-in)

STATIC = os.path.join(ROOT, "candleague", "static")
DATA = os.path.join(ROOT, "candleague", "data")
NEW_JS = ["pairs.js", "events.js", "judge.js"]
T0 = 1_791_000_000_000
HOUR = 3_600_000


def _json(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- the snapshot, as the server writes it
def _kind(role, suffix, label, short, **kw):
    return {"role": role, "suffix": suffix, "kind": "rule", "label_ko": label, "short_ko": short, "desc_ko": kw.get("desc", short + " 계좌"),
            "why_ko": kw.get("why", "이 청산이 나은가"), "tp": "ladderU", "weekend_off": False, "size": 1.0, "rule": kw.get("rule"), "accounts": 1}


LINEUP = [
    _kind("fq", "-fq", "메인 · 구조 확실히 무너지면 빠른 손절 (실전 후보)", "빠른 손절", rule="F11.a.d0.5", why="매매법마다 자기 구조로 확실히 무너졌을 때만 빨리 자르면 나은가"),
    _kind("nv", "-nv", "메인 · 매매법 자체 판단으로 청산", "매매법 판단", rule="F11.a"),
    _kind("sw", "-sw", "메인 · 반대 신호 나오면 스위칭", "스위칭", rule="F3.a"),
    _kind("tg", "-tg", "메인 · 구조 무너지면 손절 좁힘", "손절 좁힘", rule="F11.a"),
    _kind("ld", "-ld", "대조 · 계단 · 손절 최대 2 ATR (원래 메인)", "계단"),
    _kind("sb", "-sb", "연구 · 모든 매매법 공통 3봉 구조 청산", "구조 청산", rule="F1.w3.a"),
    _kind("cand", "-e", "지금 청산", "지금"),
]


def _accounts():
    covers = set(rulex.NATIVE_COVERS["core"]) | set(rulex.NATIVE_COVERS["ds"])
    rows = []
    for p in _json("candidates_owner.json")["candidates"]:
        roles = ["cand", "ld", "sw", "sb"] + (["fq", "nv", "tg"] if p["name"] in covers else [])
        for r in roles:
            suffix = next(k["suffix"] for k in LINEUP if k["role"] == r)
            rows.append({"id": p["id"] + suffix, "role": r, "pick": p["id"], "name": p["name"], "tf": p["tf"], "kind": p["kind"], "combo": {},
                         "exit": "ladderU|2", "of": p["id"] + "-e", "trades": 0, "wins": 0, "mean_ret": None, "wallet": 1000.0, "max_dd": 0.0,
                         "bust": False, "open": None, "source": {"rank": 1}})
    return rows


def _row(**kw):
    base = {"pick": "core-DOGE-15m-1", "name": "DOGE", "tf": "15m", "kind": "core", "symbol": "DOGEUSDT", "side": 1, "entry_time": T0, "role": "fq",
            "a_reason": "RULE", "a_roe": -0.17, "b_reason": "SL", "b_roe": -0.38, "diff_roe": 0.21}
    base.update(kw)
    base.setdefault("exit_time", base["entry_time"] + 2 * HOUR)
    return base


def _stats(n, b, w, e, mean, money, shown=None):
    """One role's numbers as summary.pairs_summary writes them (n = every pair, n_shown = the pairs whose ROE is shown)."""
    m = n if shown is None else shown
    if not m:
        return {"n": n, "n_shown": m, "better": None, "worse": None, "same": None, "mean_diff_roe": None, "sum_diff_pct_of_wallet": None, "pct_better": None}
    return {"n": n, "n_shown": m, "better": b, "worse": w, "same": e, "mean_diff_roe": mean, "sum_diff_pct_of_wallet": money, "pct_better": b / m}


def _pairs():
    recent = [
        _row(),                                                                                                                  # DOGE 15m long, -17% vs -38%
        _row(pick="core-N03_ADX_GC-1h-2", name="N03_ADX_GC", tf="1h", symbol="ETHUSDT", side=-1, entry_time=T0 - HOUR, a_roe=0.04, b_roe=0.09, diff_roe=-0.05,
             a_reason="RULE", b_reason="TP"),
        _row(role="nv", pick="ds-F5_BOX-4h-1", name="F5_BOX", tf="4h", kind="ds", symbol="SOLUSDT", entry_time=T0 - 2 * HOUR, a_roe=None, b_roe=-0.10, diff_roe=None),
        _row(role="tg", entry_time=T0 - 3 * HOUR, a_roe=-0.2002, b_roe=-0.2000, diff_roe=-0.0002, a_reason="SL", b_reason="SL"),
    ]
    return {"control": "-ld", "by_role": {
        "fq": _stats(6, 4, 2, 0, 0.032, 0.125), "nv": _stats(5, 2, 2, 1, -0.0123, -0.041),
        "sw": _stats(0, 0, 0, 0, None, None), "tg": _stats(3, 1, 1, 1, 0.0004, 0.0)}, "recent": recent}


def _event(**kw):
    base = {"time": T0, "account": "core-DOGE-15m-1-fq", "pick": "core-DOGE-15m-1", "role": "fq", "name": "DOGE", "tf": "15m", "kind": "core", "side": 1,
            "symbol": "DOGEUSDT", "event": "rule_exit", "roe": -0.17, "hold_h": 3.5, "control_roe": -0.38}
    base.update(kw)
    return base


def _events():
    return [_event(),
            _event(time=T0 - HOUR, account="core-N03_ADX_GC-1h-2-tg", pick="core-N03_ADX_GC-1h-2", role="tg", name="N03_ADX_GC", tf="1h", symbol="ETHUSDT", side=-1,
                   event="narrowed", roe=-0.12, control_roe=-0.30, hold_h=0.4),
            _event(time=T0 - 2 * HOUR, account="core-N02_ST_KST-30m-2-sw", pick="core-N02_ST_KST-30m-2", role="sw", name="N02_ST_KST", tf="30m", symbol="BTCUSDT",
                   side=-1, event="switch", roe=0.05, control_roe=None, hold_h=1.0),
            _event(time=T0 - 3 * HOUR, account="ds-F5_BOX-4h-1-nv", pick="ds-F5_BOX-4h-1", role="nv", name="F5_BOX", tf="4h", kind="ds", symbol="SOLUSDT", side=1,
                   roe=None, control_roe=0.02, hold_h=None)]


def _doc(**kw):
    d = {"generated_ms": T0, "done_ms": T0, "lag_s": 60, "start_ms": T0 - 3 * 86_400_000, "started_ms": T0 - 3 * 86_400_000, "equity0": 1000, "ds_money": True,
         "accounts": _accounts(), "lineup": LINEUP, "pairs": _pairs(), "events": _events()}
    d.update(kw)
    for k in [k for k, v in d.items() if v is ...]:
        del d[k]
    return d


def _old_doc():
    """The 190-account league: no lineup, no pairs, no events (the older snapshot's five roles per pick)."""
    accts = []
    for p in _json("candidates_owner.json")["candidates"][:6]:
        for role, suffix in (("cand", ""), ("quarter", "-q"), ("exitonly", "-x"), ("flip", "-flip")):
            accts.append({"id": p["id"] + suffix, "role": role, "name": p["name"], "tf": p["tf"], "kind": p["kind"], "of": None if role == "cand" else p["id"],
                          "trades": 0, "wins": 0, "mean_ret": None, "wallet": 5000.0, "max_dd": 0.0, "bust": False, "open": None, "source": {"rank": 1}})
    return {"generated_ms": T0, "done_ms": T0, "lag_s": 60, "start_ms": T0 - 3 * 86_400_000, "started_ms": T0 - 3 * 86_400_000, "accounts": accts}


# ---------------------------------------------------------------- running a screen under node
def _run(tmp_path, doc, body, judge="file", meta=True):
    """Run ``body`` (an async JS block that fills ``out``) on the DOM stand-in with the routes: /api/league, /api/meta (strategies_ko.json),
    /api/judge (judge: "file" = native_ko.json, "empty" = {}, anything else = no route: a 404). ``mount(name, query)`` returns the element."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    (tmp_path / "shim.mjs").write_text(RANK.SHIM)
    routes = {"/api/league": doc}
    if meta:
        routes["/api/meta"] = _json("strategies_ko.json")
    if judge == "file":
        routes["/api/judge"] = _json("native_ko.json")
    elif judge == "empty":
        routes["/api/judge"] = {}
    code = r"""
import {readFileSync} from "node:fs";
import {install, txt} from "./shim.mjs";
const cfg = JSON.parse(readFileSync(process.argv[2], "utf8"));
install(cfg);
globalThis.location.hash = "";
const S = cfg.static;
const LK = await import(`file://${S}/js/lk.js`);
const doc = cfg.routes["/api/league"];
if (doc) LK.setLeague(doc);
try { await LK.getMeta(); } catch (e) { /* no meta route */ }
const tick = () => new Promise((r) => setTimeout(r, 20));
const queries = [];
async function mount(name, query = {}) {
  const M = await import(`file://${S}/js/screens/${name}.js`);
  const el = document.createElement("div");
  el.dataset.screen = name;
  document.body.appendChild(el);
  const ctx = {params: {name, arg: null, query}, alive: () => true, signal: null,
    api: async (p) => { const r = await globalThis.fetch(p); if (!r.ok) { const e = new Error("HTTP " + r.status); e.status = r.status; throw e; } return r.json(); },
    meta: () => LK.getMeta(), onLeague: (fn) => { if (doc) fn(doc); }, onLive: () => () => {}, onPositions: () => () => {},
    every: () => {}, css: async () => null, wide() {}, setTitle() {}, setQuery: (q) => queries.push(q),
    href: (n, a) => `#/${n}${a ? "/" + a : ""}`};
  await M.mount(el, ctx);
  for (let i = 0; i < 8; i++) await tick();
  return el;
}
const btn = (el, text) => el.querySelectorAll("button").find((b) => txt(b) === text || txt(b).startsWith(text));
async function click(el, b) { if (!b) throw new Error("no button"); b.fire("click"); for (let i = 0; i < 3; i++) await tick(); }
const out = {};
""" + body + "\nout.queries = queries;\nconsole.log(JSON.stringify(out));\nprocess.exit(0);\n"
    (tmp_path / "run.mjs").write_text(code)
    (tmp_path / "cfg.json").write_text(json.dumps({"static": STATIC, "routes": routes}, ensure_ascii=False))
    r = subprocess.run([node, str(tmp_path / "run.mjs"), str(tmp_path / "cfg.json")], capture_output=True, text=True, timeout=120, cwd=str(tmp_path))
    assert r.returncode == 0, (r.stdout[-800:], r.stderr[-2500:])
    return json.loads(r.stdout.strip().splitlines()[-1])


SCREENS = "pairs events judge".split()
ALL = r"""
for (const n of ["pairs", "events", "judge"]) { const el = await mount(n); out[n] = txt(el); }
"""


def _clean(page):
    assert "NaN" not in page and "undefined" not in page and "[object" not in page and "null" not in page.replace("native_ko", ""), page[:300]


# ---------------------------------------------------------------- the pairs screen
def test_pairs_sentence_cards_table_and_the_explanation(tmp_path):
    o = _run(tmp_path, _doc(), r"""
const el = await mount("pairs");
out.page = txt(el);
out.sentence = txt(el.querySelector(".hero .dl-vline"));
out.cards = el.querySelectorAll(".cl-cp").map(txt);
out.rows = el.querySelectorAll("tbody tr").map(txt);
out.head = el.querySelectorAll("thead th").map(txt);
out.chips = el.querySelectorAll(".seg button").map(txt);
out.bars = el.querySelectorAll("span[role=\"img\"]").map((b) => b.getAttribute("aria-label"));
""")
    assert o["sentence"] == "빠른 손절은 같은 신호에서 대조보다 4번 낫고 2번 못했습니다 (평균 +3.2%p)"
    assert "짝 6개" in o["page"] and "짝이 30개가 안 되면 우연일 수 있습니다" in o["page"]
    fq, nv, sw, tg = o["cards"]                                                      # the lineup's order, only kinds that have a number
    assert fq.startswith("빠른 손절") and "메인" in fq and "실전 후보" in fq and "짝 6개 · 평균 +3.2%p 낫다" in fq
    assert "낫다 4번" in fq and "같다 0번" in fq and "못하다 2번" in fq and "돈으로 (계좌 대비)" in fq and "+12.5%" in fq
    assert nv.startswith("매매법 판단") and "평균 −1.2%p 못하다" in nv and "낫다 2번" in nv and "같다 1번" in nv and "−4.1%" in nv and "실전 후보" not in nv
    assert "아직 짝 없음" in sw and sw.startswith("스위칭")
    assert "평균 0.0%p 같다" in tg                                                   # 0.04 %p reads as the same, never "+0.0%p 낫다"
    assert o["bars"][0] == "낫다 4번, 같다 0번, 못하다 2번"
    # the table: newest first; 메인 reason + ROE next to 대조 reason + ROE, the difference with its word
    assert len(o["rows"]) == 4
    first, second, third, fourth = o["rows"]
    for t in ("15분", "도지 봇", "DOGE", "롱", "빠른 손절", "규칙 청산", "−17%", "손절", "−38%", "+21.0%p", "낫다"):
        assert t in first, (t, first)
    for t in ("1시간", "ADX·골든크로스", "ETH", "숏", "+4.0%", "익절", "+9.0%", "−5.0%p", "못하다"):
        assert t in second, (t, second)
    assert "—" in third and "−10%" in third and "낫다" not in third and "못하다" not in third and "+0.0" not in third      # null ROE: a dash, no word
    assert "0.0%p" in fourth and "같다" in fourth and "낫다" not in fourth and "못하다" not in fourth
    assert o["head"] == ["매매법", "끝난 때", "방향", "메인 청산", "대조 청산", "차이 (메인 − 대조)"]
    assert o["chips"][0] == "전체 4" and any(c.startswith("빠른 손절 2") for c in o["chips"]) and any(c.startswith("매매법 판단 1") for c in o["chips"])
    # the plain explanation: what a pair is and why only the same-signal pairs are fair
    for t in ("짝이 뭔가요?", "같은 신호로 들어간 거래 두 개", "같은 코인 · 같은 방향 · 같은 진입 시각", "왜 같은 신호끼리만 비교하나요?",
              "들어간 자리가 같으니", "차이 = 메인 ROE − 대조 ROE"):
        assert t in o["page"], t
    assert "$1,000" in o["page"] and "$5,000" not in o["page"]
    _clean(o["page"])


def test_pairs_filter_chips_and_paging(tmp_path):
    doc = _doc()
    doc["pairs"]["recent"] = [_row(entry_time=T0 - i * HOUR, role="fq" if i % 3 else "nv", diff_roe=0.01 * (i % 5 - 2)) for i in range(14)]
    o = _run(tmp_path, doc, r"""
const el = await mount("pairs");
out.first = el.querySelectorAll("tbody tr").length;
out.info = txt(el.querySelector(".pinfo"));
await click(el, btn(el, "다음"));
out.second = el.querySelectorAll("tbody tr").length;
out.info2 = txt(el.querySelector(".pinfo"));
await click(el, btn(el, "매매법 판단"));
out.nv = el.querySelectorAll("tbody tr").map(txt);
out.count = txt(el.querySelector(".card .note"));
out.pressed = el.querySelectorAll(".seg button").filter((b) => b.getAttribute("aria-selected") === "true").map(txt);
""")
    assert o["first"] == 12 and o["info"] == "1–12 / 14"
    assert o["second"] == 2 and o["info2"] == "13–14 / 14"
    assert len(o["nv"]) == 5 and all("매매법 판단" in r for r in o["nv"])          # i = 0, 3, 6, 9, 12
    assert o["queries"][-1] == {"kind": "nv"} and any(p.startswith("매매법 판단") for p in o["pressed"])


def test_pairs_null_roe_is_a_dash_never_zero(tmp_path):
    doc = _doc()
    doc["pairs"]["by_role"]["fq"] = _stats(2, 0, 0, 0, None, None)
    doc["pairs"]["recent"] = [_row(a_roe=None, b_roe=None, diff_roe=None, a_reason=None, b_reason=None)]
    o = _run(tmp_path, doc, r"""
const el = await mount("pairs");
out.page = txt(el);
out.row = el.querySelectorAll("tbody tr").map(txt)[0];
out.sentence = txt(el.querySelector(".hero .dl-vline"));
""")
    assert o["sentence"] == "빠른 손절은 같은 신호에서 대조보다 0번 낫고 0번 못했습니다 (평균 —)"
    assert o["row"].count("—") >= 5 and "%" not in o["row"] and "낫다" not in o["row"]
    assert not re.search(r"(?<![\d.])0(\.0)?%", o["page"].split("최근 짝")[-1].split("짝이 뭔가요")[0])
    _clean(o["page"])


def test_pairs_absent_keys_and_the_old_league(tmp_path):
    for doc, want in ((_doc(pairs=...), "같은 신호 짝 기록이 아직 없습니다"), (_doc(pairs={}), "아직 같은 신호 짝이 없습니다"),
                      (_doc(pairs={"control": "-ld", "by_role": {}, "recent": []}), "아직 같은 신호 짝이 없습니다"),
                      (_doc(pairs={"by_role": {"fq": _stats(0, 0, 0, 0, None, None)}}), "빠른 손절은 아직 대조와 짝을 이룬 거래가 없습니다"),
                      (_old_doc(), "지금 기록은 이전 리그(계좌 24개)라서 같은 신호 짝 비교는 아직 없습니다")):
        o = _run(tmp_path, doc, r"""
const el = await mount("pairs");
out.page = txt(el);
out.tables = el.querySelectorAll("table").length;
""")
        assert want in o["page"], (want, o["page"][:300])
        assert o["tables"] == 0 and "짝이 뭔가요?" in o["page"]                       # the plain explanation stays; no table without pairs
        _clean(o["page"])
    o = _run(tmp_path, None, r"""
const el = await mount("pairs");
out.page = txt(el);
""")
    assert "같은 신호 짝 비교" in o["page"]                                             # no snapshot yet: the head and the explanation, no error


def test_pairs_follow_the_servers_numbers_n_shown_and_exit_order(tmp_path):
    """summary.pairs_summary: ``n`` is every pair, ``n_shown`` those whose ROE is shown (DeepSeek money switch); the newest pair is the one
    whose main trade ended last (not entered last); a difference under 0.05 %p is 같다 on both sides."""
    doc = _doc()
    doc["pairs"]["by_role"]["fq"] = _stats(5, 1, 1, 0, 0.01, 0.02, shown=2)
    doc["pairs"]["by_role"]["nv"] = _stats(3, 0, 0, 0, None, None, shown=0)
    doc["pairs"]["recent"] = [_row(entry_time=T0, exit_time=T0 + HOUR, pick="core-DOGE-15m-1"),
                              _row(entry_time=T0 - 5 * HOUR, exit_time=T0 + 10 * HOUR, pick="core-N03_ADX_GC-1h-2", name="N03_ADX_GC", tf="1h", a_roe=0.001, b_roe=0.0, diff_roe=0.001),
                              _row(entry_time=T0 - 6 * HOUR, exit_time=T0 - HOUR, tf="30m", a_roe=0.0005, b_roe=0.0, diff_roe=0.0005),
                              _row(entry_time=T0 - 7 * HOUR, exit_time=T0 - 2 * HOUR, tf="4h", a_roe=-0.0005, b_roe=0.0, diff_roe=-0.0005)]
    o = _run(tmp_path, doc, r"""
const el = await mount("pairs");
out.sentence = txt(el.querySelector(".hero .dl-vline"));
out.hero = txt(el.querySelector(".hero"));
out.cards = el.querySelectorAll(".cl-cp").map(txt);
out.rows = el.querySelectorAll("tbody tr").map(txt);
""")
    assert o["sentence"] == "빠른 손절은 같은 신호에서 대조보다 1번 낫고 1번 못했습니다 (평균 +1.0%p)"
    assert "짝 2개 (전체 5개 중 ROE가 보이는 것)" in o["hero"] and "짝이 30개가 안 되면 우연일 수 있습니다" in o["hero"]
    assert "짝 2개" in o["cards"][0] and "전체 5개 중 ROE가 보이는 짝 기준" in o["cards"][0] and "+2.0%" in o["cards"][0]
    assert "짝 3개" in o["cards"][1] and "금액 숨김 설정이라 ROE 비교는 숨겼습니다" in o["cards"][1] and "낫다 0번" not in o["cards"][1]
    assert "1시간" in o["rows"][0] and "+0.1%p 낫다" in o["rows"][0]                    # ended last, entered earlier
    assert "15분" in o["rows"][1] and "30분" in o["rows"][2] and "4시간" in o["rows"][3]
    assert "+0.1%p" in o["rows"][0] and "낫다" in o["rows"][2] and "못하다" in o["rows"][3]      # exactly 0.05 %p: better / worse, as the server counts
    doc["pairs"]["by_role"]["fq"] = _stats(4, 0, 0, 0, None, None, shown=0)
    o = _run(tmp_path, doc, r"""
const el = await mount("pairs");
out.sentence = txt(el.querySelector(".hero .dl-vline"));
""")
    assert o["sentence"] == "빠른 손절은 같은 신호 짝이 4개 있지만, 금액 숨김 설정이라 낫고 못한 횟수는 숨겼습니다"


# ---------------------------------------------------------------- the events screen
def test_events_feed_sentences_counts_and_chips(tmp_path):
    o = _run(tmp_path, _doc(), r"""
const el = await mount("events");
out.page = txt(el);
out.hero = txt(el.querySelector(".hero"));
out.rows = el.querySelectorAll("div[data-event]").map(txt);
out.kinds = el.querySelectorAll("div[data-event]").map((r) => r.dataset.event);
out.links = el.querySelectorAll("div[data-event] a").map((a) => a.getAttribute("href"));
out.count = txt(el.querySelectorAll(".note").find((n) => txt(n).includes("보는 중")));
out.chips = el.querySelectorAll(".seg button").map(txt);
await click(el, btn(el, "손절 좁힘"));
out.tg = el.querySelectorAll("div[data-event]").map(txt);
out.tgCount = txt(el.querySelectorAll(".note").find((n) => txt(n).includes("보는 중")));
""")
    assert "규칙이 4번 발동했습니다 (빠른 청산 2 · 손절 좁힘 1 · 스위칭 1)" in o["hero"]
    assert "대조 결과를 아는 2번 중 대조보다 낫다 2번 · 못하다 0번 · 같다 0번" in o["hero"]
    r = o["rows"]
    assert o["kinds"] == ["rule_exit", "narrowed", "switch", "rule_exit"]            # newest first
    assert "빠른 청산" in r[0] and "15분 DOGE 롱 · 구조가 무너져 빠른 손절 · 손실 −17% · 대조는 −38%" in r[0]
    assert "보유 3시간 30분" in r[0] and "도지 봇" in r[0] and "대조보다 낫다" in r[0]
    assert "손절 좁힘" in r[1] and "1시간 ETH 숏 · 구조가 무너져 손절을 좁힘 · 손실 −12% · 대조는 −30%" in r[1] and "ADX·골든크로스" in r[1]
    assert "스위칭" in r[2] and "30분 BTC 숏 · 반대 신호가 나와 청산하고 반대로 갈아탐 · 수익 +5.0% · 대조는 —" in r[2] and "슈퍼트렌드·KST" in r[2]
    assert "대조보다" not in r[2]                                                    # no control number: no comparison word
    assert "4시간 SOL 롱 · 매매법이 구조가 무너졌다고 보고 청산 · 손익 — · 대조는 +2.0%" in r[3] and "보유" not in r[3] and "대조보다" not in r[3]
    assert o["links"][0] == "#/account/core-DOGE-15m-1-fq"
    assert "4번 보는 중 · 전체 4번 · 새 것부터" in o["count"]
    assert o["chips"][0] == "전체 4" and "빠른 손절 1" in o["chips"] and "매매법 판단 1" in o["chips"] and "스위칭 1" in o["chips"] and "손절 좁힘 1" in o["chips"]
    assert len(o["tg"]) == 1 and "손절 좁힘" in o["tg"][0]
    assert "1번 보는 중 (손절 좁힘) · 전체 4번 · 새 것부터" in o["tgCount"]
    assert "$1,000" in o["page"] and "$5,000" not in o["page"] and "읽는 법" in o["page"]
    _clean(o["page"])


def test_events_empty_absent_and_old_league(tmp_path):
    for doc, want in ((_doc(events=[]), "아직 발동한 적 없음 (구조가 확실히 무너진 거래가 아직 없습니다)"),
                      (_doc(events=...), "발동 기록이 아직 없습니다"), (_doc(events=[{"event": "nope"}, None, 3]), "아직 발동한 적 없음"),
                      (_old_doc(), "지금 기록은 이전 리그(계좌 24개)라서 메인 계좌의 발동 기록은 아직 없습니다")):
        o = _run(tmp_path, doc, r"""
const el = await mount("events");
out.page = txt(el);
out.rows = el.querySelectorAll("div[data-event]").length;
""")
        assert want in o["page"] and o["rows"] == 0, (want, o["page"][:300])
        _clean(o["page"])


def test_events_null_fields_and_many_rows(tmp_path):
    doc = _doc(events=[_event(roe=None, control_roe=None, hold_h=None, symbol=None, side=None, tf="15m") for _ in range(2)]
               + [_event(time=T0 - i * HOUR, roe=0.0, control_roe=0.0) for i in range(1, 17)]
               + [_event(time=T0 - 20 * HOUR, role="sw", account="core-DOGE-15m-1-sw", roe=-0.01, control_roe=-0.02)])
    o = _run(tmp_path, doc, r"""
const el = await mount("events");
out.n = el.querySelectorAll("div[data-event]").length;
out.rows = el.querySelectorAll("div[data-event]").map(txt);
out.info = txt(el.querySelector(".pinfo"));
out.page = txt(el);
await click(el, btn(el, "다음"));
out.last = el.querySelectorAll("div[data-event]").map(txt);
""")
    assert o["last"] and len(o["last"]) == 4 and "반대 신호가 나와 청산 · 손실 −1.0% · 대조는 −2.0%" in o["last"][-1]       # a rule exit of the switching account
    assert o["n"] == 15 and o["info"] == "1–15 / 19"                                 # 2 + 16 + 1
    nulls = [r for r in o["rows"] if "손익 —" in r]
    assert len(nulls) == 2 and all("15분 — — · " in r and "대조는 —" in r and "대조보다" not in r for r in nulls)
    zero = [r for r in o["rows"] if "본전 0.0%" in r]
    assert zero and all("대조는 0.0%" in r and "대조와 같다" in r for r in zero)
    _clean(o["page"])


# ---------------------------------------------------------------- the judge screen
def test_judge_top_boxes_and_cards(tmp_path):
    o = _run(tmp_path, _doc(), r"""
const el = await mount("judge");
out.page = txt(el);
out.cards = el.querySelectorAll(".cl-ecard").map(txt);
out.own = el.querySelectorAll(".cl-ecard[data-own=\"true\"]").length;
out.none = el.querySelectorAll(".cl-ecard[data-own=\"false\"]").length;
out.byName = Object.fromEntries(el.querySelectorAll(".cl-ecard").map((c) => [c.dataset.strategy, txt(c)]));
out.chips = el.querySelectorAll(".seg button").map(txt);
await click(el, btn(el, "기준 없음"));
out.noneShown = el.querySelectorAll(".cl-ecard").map((c) => c.dataset.strategy);
out.q = el.querySelectorAll(".seg button").filter((b) => b.getAttribute("aria-selected") === "true").map(txt);
""")
    p = o["page"]
    for t in ("빠른 손절은 언제 나가나?", "그 매매법 자체 구조 기준이 무너졌고", "그때 손실이 손절 거리의 절반을 넘었을 때", "둘 중 하나만으로는 나가지 않습니다",
              "봉이 마감할 때만", "스위칭은 언제 하나?", "그 매매법이 스스로 반대 방향 진입 신호를 낼 때", "같은 분에 반대 방향으로 진입"):
        assert t in p, t
    assert "자체 구조 코드가 없는 11개 매매법에는 이 계좌들이 없습니다" in p               # quick stop and narrowing: the strategy's own structure only
    assert "빠른 손절과 손절 좁힘은 그 매매법 자체 구조 기준만 씁니다" in p
    assert "모든 매매법 공통 3봉 구조 청산" in p and "실전 후보가 아닙니다" in p               # the research account is named as research
    assert len(o["cards"]) == 27 and o["own"] == 16 and o["none"] == 11
    doge = o["byName"]["DOGE"]
    assert "도지 봇" in doge and "자체 구조 기준 있음" in doge and "쓰는 봉: 15분 · 30분 · 1시간 · 4시간 (후보 4개)" in doge
    assert "무엇에 거나?" in doge and "롱 구조가 무너졌다" in doge and "숏 구조가 무너졌다" in doge
    assert "빠른 평균선(EMA)이 느린 평균선 아래로 내려가거나" in doge and "K선이 D선 위로 꺾인 봉이 마감하면" in doge
    assert "메인 규칙 발동: 1번 (빠른 청산 1번)" in doge
    n02 = o["byName"]["N02_ST_KST"]
    assert "슈퍼트렌드·KST" in n02 and "자체 구조 기준 없음" in n02 and "롱 구조가 무너졌다" not in n02 and "3봉" not in n02 and "스윙" not in n02
    assert "빠른 손절 · 손절 좁힘 · 매매법 판단 계좌가 이 매매법에는 없습니다" in n02 and "메인 규칙 발동: 1번 (스위칭 1번)" in n02
    assert "메인 규칙 발동: 아직 없음" in o["byName"]["OBV_S"]
    assert "쓰는 봉" in o["byName"]["F5_BOX"] and "15분 · 4시간" in o["byName"]["F5_BOX"] and "박스 바닥 아래로" in o["byName"]["F5_BOX"]
    assert o["chips"] == ["전체 27", "기준 있음 16", "기준 없음 11"]
    assert len(o["noneShown"]) == 11 and set(o["noneShown"]) == {"N02_ST_KST", "N12_ICHI_AO", "N07_ICHI_CMO", "N04_ST_KLINGER", "N23_HA_ST", "N21_ST_RSI_ADX",
                                                                  "F3_BOS", "F15_ORB", "F4_FAN", "F6_VWAP_FAIL", "F15_LON_BRK"}
    assert o["queries"][-1] == {"own": "none"}
    assert "$5,000" not in p
    _clean(p)


def test_judge_without_the_file_or_with_an_empty_one(tmp_path):
    body = r"""
const el = await mount("judge");
out.page = txt(el);
out.cards = el.querySelectorAll(".cl-ecard").length;
out.retry = !!btn(el, "다시 시도");
out.chips = el.querySelectorAll(".seg button").length;
"""
    o = _run(tmp_path, _doc(), body, judge="none")                                  # the route fails (404)
    assert "불러오지 못했습니다" in o["page"] and o["retry"] and o["cards"] == 27 and o["chips"] == 0
    assert "빠른 손절은 언제 나가나?" in o["page"] and "스위칭은 언제 하나?" in o["page"]  # the rules stay; no number of weak strategies is claimed
    assert "자체 구조 코드가 없는 매매법에는 이 계좌들이 없습니다" in o["page"]
    assert "설명 자료가 아직 없습니다" in o["page"]
    _clean(o["page"])
    o = _run(tmp_path, _doc(), body, judge="empty")                                 # {}
    assert "매매법별 설명 자료가 아직 없습니다" in o["page"] and o["cards"] == 27 and not o["retry"]
    _clean(o["page"])
    o = _run(tmp_path, None, body)                                                  # no snapshot yet: the file's own names
    assert o["cards"] == 27 and "자체 구조 기준 있음" in o["page"]
    _clean(o["page"])


def test_judge_old_league_and_missing_events(tmp_path):
    o = _run(tmp_path, _old_doc(), r"""
const el = await mount("judge");
out.page = txt(el);
out.cards = el.querySelectorAll(".cl-ecard").map(txt);
""")
    assert "지금 기록은 이전 리그(계좌 24개)라서 메인 계좌의 발동 횟수는 아직 없고" in o["page"]
    assert o["cards"] and all("메인 규칙 발동" not in c for c in o["cards"])
    assert "자체 구조 기준 있음" in o["page"]                                          # the explanations are the new league's rules, still shown
    o = _run(tmp_path, _doc(events=...), r"""
const el = await mount("judge");
out.cards = el.querySelectorAll(".cl-ecard").map(txt);
""")
    assert len(o["cards"]) == 27 and all("메인 규칙 발동" not in c for c in o["cards"])    # no events in the snapshot: the line is left out


# ---------------------------------------------------------------- all three: the wallet and the static rules
def test_start_wallet_is_the_snapshots_not_a_stray_5000(tmp_path):
    for doc in (_doc(), _doc(pairs=..., events=...)):
        o = _run(tmp_path, doc, ALL)
        for n in SCREENS:
            assert "$5,000" not in o[n] and "5,000" not in o[n] and "5000" not in o[n], n
        assert "$1,000" in o["pairs"] and "$1,000" in o["events"]
    o = _run(tmp_path, _doc(equity0=5000), ALL)                                     # another league: its own number
    assert "$5,000" in o["pairs"] and "$1,000" not in o["pairs"]


def test_new_files_are_text_only_tokens_only_and_parse():
    for f in NEW_JS:
        path = os.path.join(STATIC, "js", "screens", f)
        src = open(path, encoding="utf-8").read()
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "document.write", "new Function", "eval(", "localStorage"):
            assert bad not in src, (f, bad)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", src), f                       # colours only from the tokens (var(--x))
        for m in re.finditer(r"(?:fontSize|font)\s*:\s*\"([^\"]*)\"", src):
            assert "var(--t-" in m.group(1) or m.group(1).startswith(("800 var(--t-", "700 var(--t-")), (f, m.group(0))
        for m in re.finditer(r"(?:background|borderColor|color)\s*:\s*\"([^\"]*)\"", src):
            assert m.group(1).startswith("var(--"), (f, m.group(0))
        assert "export async function mount(el, ctx)" in src and "export const css" not in src, f
        node = shutil.which("node")
        if node:
            with open(path, encoding="utf-8") as fh:
                r = subprocess.run([node, "--input-type=module", "--check"], stdin=fh, capture_output=True, text=True)
            assert r.returncode == 0, (f, r.stderr[:400])
    # the shell registers them by these ids; the data file is the route's answer
    assert set(_json("native_ko.json")) == {"strategies"}
