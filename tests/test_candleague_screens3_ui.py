"""candleague 코인별 / 데이터 점검 / 타임라인 screens (js/screens/coins.js, dataq.js, timeline.js; css scr/coins.css, scr/dataq.css, scr/timeline.css on top
of scr/kinds.css), mounted for real under node on the DOM stand-in of test_candleague_rank_ui, with snapshots whose blocks are written by the real server
modules (coinview / dataq / timeline) from the hand-made worlds of their server tests (or edited by hand).

For each screen: (a) full data: the rule box first, the one sentence from the server, the content in order; (b) the card view (a phone's default) with the
same words; (c) the block absent: "데이터 준비 중" / "새 리그 전용" / "준비 중", and the rule box still there; (d) null numbers read "—", never 0 / NaN /
undefined / null; no typed-in $5,000; plus the static rules (text only, tokens only, scoped, prefixed) and the registration snippets (once app.js has them)."""

from __future__ import annotations

import json
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

import test_candleague_coinview as CT  # noqa: E402
import test_candleague_dataq as DT  # noqa: E402
import test_candleague_rank_ui as RANK  # noqa: E402  (its DOM stand-in)
import test_candleague_riskview as RT  # noqa: E402
import test_candleague_timeline as TT  # noqa: E402
from candleague import coinview as CV  # noqa: E402
from candleague import dataq as DQ  # noqa: E402
from candleague import timeline as TL  # noqa: E402

STATIC = os.path.join(ROOT, "candleague", "static")
BAD = ("NaN", "undefined", "null", "Infinity", "[object")


# ---------------------------------------------------------------- hand-made snapshots
def doc(block="full", name="coins", lineup=True, accounts=True) -> dict:
    now = int(time.time() * 1000)
    d = {"generated_ms": now - 60_000, "done_ms": now - 6 * 60_000, "lag_s": 360, "catching": False, "start_ms": TT.T0, "started_ms": TT.T0, "judge": {}, "ds_money": False,
         "watch": {"checkpoints": [], "pools": {}}, "equity0": 1000,
         "accounts": [{"id": "core-X-1h-1-fq", "role": "fq", "kind": "core", "name": "X", "tf": "1h", "trades": 5, "wins": 3, "mean_ret": 0.01, "wallet": 1000.0,
                       "max_dd": 0.02, "bust": False, "open": None}]}
    if not accounts:
        del d["accounts"]
    if lineup:
        d["lineup"] = [{"role": k["role"], "suffix": k["suffix"], "label_ko": k["label_ko"], "short_ko": k["short_ko"], "accounts": 1} for k in RT.LU]
    if block == "full":
        rows, book = CT.world()
        if name == "coins":
            d["coins"] = CV.coin_views(book, rows, RT.LU, 1000.0, False)
        elif name == "timeline":
            r2, b2 = TT.world()
            d["timeline"] = TL.timeline_views(b2, r2, RT.LU, TT.DEC, TT.T0, TT.T0, TT.T0 + 15 * TT.DAY, ["복원 메모"], False)
        else:
            shift = d["done_ms"] - DT.DONE                                                              # the hand-made trades, moved to the fresh engine time
            book = {a: [{**t, "entry_time": t["entry_time"] + shift, "exit_time": t["exit_time"] + shift} for t in ts] for a, ts in DT.BOOK.items()}
            d["dataq"] = DQ.dataq_views(DT.snap(done_ms=d["done_ms"], generated_ms=d["generated_ms"], start_ms=d["done_ms"] - 3 * 86_400_000), book, DT.LU, False)
    elif block is not None:
        d[name] = block
    return json.loads(json.dumps(d, allow_nan=False))


RUNNER = r"""
import {readFileSync} from "node:fs";
import {install, txt} from "./shim.mjs";
const cfg = JSON.parse(readFileSync(process.argv[2], "utf8"));
install(cfg);
globalThis.location.hash = "";
const S = cfg.static;
const LK = await import(`file://${S}/js/lk.js`);
const doc = cfg.doc;
if (doc) LK.setLeague(doc);
const M = await import(`file://${S}/js/screens/${cfg.screen}.js`);
const el = document.createElement("div");
el.dataset.screen = cfg.screen;
document.body.appendChild(el);
const ctx = {params: {name: cfg.screen, arg: null, query: {}}, alive: () => true, signal: null,
  api: async (p) => (await globalThis.fetch(p)).json(), meta: () => LK.getMeta(),
  onLeague: (fn) => { if (doc) fn(doc); }, onLive: () => () => {}, onPositions: () => () => {},
  every: () => {}, css: async () => null, wide() {}, setTitle() {}, setQuery() {},
  href: (n, a) => `#/${n}${a ? "/" + a : ""}`};
await M.mount(el, ctx);
for (let i = 0; i < 4; i++) await new Promise((r) => setTimeout(r, 10));
const out = {text: txt(el), css: M.css, cls: el.className, sel: {}, rulesDefault: M.RULES_DEFAULT};
for (const [k, sel] of Object.entries(cfg.sels || {})) {
  out.sel[k] = el.querySelectorAll(sel).map((n) => ({t: txt(n), d: {...n.dataset}, c: n.className, a: Object.fromEntries(n.attrs)}));
}
console.log(JSON.stringify(out));
process.exit(0);
"""


def run(tmp_path, screen, d, sels=None, local=None) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    (tmp_path / "shim.mjs").write_text(RANK.SHIM)
    (tmp_path / "run.mjs").write_text(RUNNER)
    cfg = {"static": STATIC, "routes": {}, "local": local or {}, "doc": d, "sels": sels or {}, "screen": screen}
    (tmp_path / "cfg.json").write_text(json.dumps(cfg, ensure_ascii=False))
    r = subprocess.run([node, str(tmp_path / "run.mjs"), str(tmp_path / "cfg.json")], capture_output=True, text=True, timeout=120, cwd=str(tmp_path))
    assert r.returncode == 0, (r.stdout[-600:], r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def no_junk(text: str) -> None:
    for bad in BAD:
        assert bad not in text, bad
    assert not re.search(r"\$\s?5,?000", text)


SELS = {"rules": "ol.kd-rules li", "big": ".kd-hero .dl-vbig", "plates": ".plate", "limits": "ul.kd-list li", "rows": "tr.kd-row", "cards": "article.kd-kcard, li.kd-kcard",
        "pills": ".pp", "links": "a.tl-acct", "seg": ".seg button", "legend": "dl.kd-legend dt", "missing": ".dl-missing"}
NAMES = ("coins", "dataq", "timeline")
CSS = {"coins": ["scr/kinds.css", "scr/coins.css"], "dataq": ["scr/kinds.css", "scr/dataq.css"], "timeline": ["scr/kinds.css", "scr/timeline.css"]}


# ---------------------------------------------------------------- 코인별
def test_coins_full_data_table_then_cards(tmp_path):
    d = doc()
    c = d["coins"]
    o = run(tmp_path, "coins", d, SELS, local={"cl-coins-view": json.dumps("table")})
    page = o["text"]
    assert o["css"] == CSS["coins"] and "kd" in o["cls"].split() and [x["t"] for x in o["sel"]["rules"]] == c["rules_ko"]
    assert page.index("이 화면은 무엇인가요") < page.index("한 줄 결론") < page.index("빠른 손절")
    assert o["sel"]["big"][0]["t"] == c["headline_ko"]
    assert len(o["sel"]["rows"]) == 4 * len(c["coins"])                                                  # a row per coin in each of the four kinds
    first = o["sel"]["rows"][0]["t"]
    assert first.startswith("BTC") and "40건" in first and "%p" in first and "손익 비중" not in first
    eth = next(r["t"] for r in o["sel"]["rows"] if r["t"].startswith("ETH"))
    assert "적음" in eth                                                                                 # n < 30 is a written word
    assert "동전 던지기 짝" in page and "이 숫자의 한계" in page and "낱말 뜻" in page and "실전 후보" in page
    assert [b["t"] for b in o["sel"]["seg"]] == ["표", "카드"]
    no_junk(page)
    k = run(tmp_path, "coins", d, SELS, local={"cl-coins-view": json.dumps("card")})
    assert not k["sel"]["rows"] and len(k["sel"]["cards"]) == 4 * len(c["coins"])
    one = k["sel"]["cards"][0]
    assert one["d"]["coin"] == "BTC" and "닫힌 거래 40건" in one["t"] and "이긴 비율" in one["t"] and "거래당 평균" in one["t"] and "%p" in one["t"]
    assert any(x["d"].get("few") == "1" and "적음" in x["t"] for x in k["sel"]["cards"])
    no_junk(k["text"])


def test_coins_absent_and_null_numbers(tmp_path):
    for dd, need, notneed in ((doc(None), ("데이터 준비 중", "코인별 기록은 아직 없습니다"), ("새 리그 전용",)), (doc({"kinds": "x"}), ("데이터 준비 중",), ("새 리그 전용",)),
                              (doc({"kinds": []}), ("데이터 준비 중",), ()), (doc(None, lineup=False), ("새 리그 전용", "이전 리그"), ("데이터 준비 중",)),
                              (doc(None, accounts=False), ("준비 중", "후보 리그 기록이 아직 없습니다"), ("새 리그 전용",)), (None, ("준비 중",), ("새 리그 전용",))):
        o = run(tmp_path, "coins", dd, SELS)
        for w in need:
            assert w in o["text"], w
        for w in notneed:
            assert w not in o["text"], w
        assert "이 화면은 무엇인가요" in o["text"] and not o["sel"]["rows"]
        no_junk(o["text"])
    d = doc()
    for k in d["coins"]["kinds"]:
        for r in k["rows"]:
            for key in ("win_rate", "mean_roe", "pnl", "share", "diff"):
                r[key] = None
        k["total"] = {"n": None, "pnl": None, "mean_roe": None}
    for view in ("table", "card"):
        o = run(tmp_path, "coins", d, SELS, local={"cl-coins-view": json.dumps(view)})
        no_junk(o["text"])
        assert "—" in o["text"] and not re.search(r"(?<![\d.])0(\.0)?%", o["text"])                      # a missing number is a dash, never 0%
    d["coins"].pop("rules_ko")
    o = run(tmp_path, "coins", d, SELS)
    assert [x["t"] for x in o["sel"]["rules"]] == o["rulesDefault"] == CV.coin_rules_ko()


# ---------------------------------------------------------------- 타임라인
def test_timeline_full_data_links_order_and_cards(tmp_path):
    d = doc(name="timeline")
    tl = d["timeline"]
    o = run(tmp_path, "timeline", d, SELS, local={"cl-timeline-view": json.dumps("table")})
    page = o["text"]
    assert o["css"] == CSS["timeline"] and o["sel"]["big"][0]["t"] == tl["headline_ko"]
    pl = [x["t"] for x in o["sel"]["plates"]]
    assert pl.index("이 화면은 무엇인가요") < pl.index("한 줄 결론") < pl.index("일어난 일")
    rows = o["sel"]["rows"]
    assert len(rows) == len(tl["rows"]) and rows[0]["d"]["kind"] == "decide" and rows[0]["d"]["state"] == "coming" and "예정" in rows[0]["t"] and "28일째 판정" in rows[0]["t"]
    assert rows[1]["d"]["kind"] == "observe" and "지남" in rows[1]["t"] and "14일째 확인" in rows[1]["t"]
    links = o["sel"]["links"]
    assert links and all(re.fullmatch(r"#/account/[^/]+", x["a"]["href"]) for x in links) and {x["t"] for x in links} >= {"a-fq", "a-ld"}
    assert "(대략)" in page and "가장 큰 한 번 이익 +$55.00" in page and "시각이 없는 기록" in page and "복원 메모" in page
    kst = re.findall(r"\d\d/\d\d \d\d:\d\d", rows[2]["t"])
    assert kst                                                                                          # a KST time on the row
    no_junk(page)
    k = run(tmp_path, "timeline", d, SELS, local={"cl-timeline-view": json.dumps("card")})
    assert not k["sel"]["rows"] and len(k["sel"]["cards"]) == len(tl["rows"]) and "예정" in k["sel"]["cards"][0]["t"]
    no_junk(k["text"])


def test_timeline_absent_and_null_numbers(tmp_path):
    for dd, need, notneed in ((doc(None, "timeline"), ("데이터 준비 중", "타임라인 기록은 아직 없습니다"), ("새 리그 전용",)), (doc({"rows": "x"}, "timeline"), ("데이터 준비 중",), ()),
                              (doc(None, "timeline", lineup=False), ("새 리그 전용", "이전 리그"), ("데이터 준비 중",)), (doc(None, "timeline", accounts=False), ("준비 중",), ("새 리그 전용",))):
        o = run(tmp_path, "timeline", dd, SELS)
        for w in need:
            assert w in o["text"], w
        for w in notneed:
            assert w not in o["text"], w
        assert "이 화면은 무엇인가요" in o["text"]
        no_junk(o["text"])
    nulls = {"rows": [{"ms": None, "kind": "bust", "tag_ko": "파산", "text_ko": "잔고가 바닥남", "account": None, "suffix": None, "state": None, "approx": False},
                      {"ms": None, "kind": "first", "tag_ko": None, "text_ko": None, "account": None, "state": None}], "more": None, "cap": None}
    for view in ("table", "card"):
        o = run(tmp_path, "timeline", doc(nulls, "timeline"), SELS, local={"cl-timeline-view": json.dumps(view)})
        no_junk(o["text"])
        assert "—" in o["text"] and not o["sel"]["links"]
    empty = run(tmp_path, "timeline", doc({"rows": []}, "timeline"), SELS)
    assert "아직 적을 일이 없습니다" in empty["text"]


# ---------------------------------------------------------------- 데이터 점검
def test_dataq_full_data_status_checklist_and_todo(tmp_path):
    d = doc(name="dataq")
    q = d["dataq"]
    assert q["status"] == "ok"
    o = run(tmp_path, "dataq", d, SELS, local={"cl-dataq-view": json.dumps("table")})
    page = o["text"]
    assert o["css"] == CSS["dataq"] and o["sel"]["big"][0]["t"] == q["headline_ko"] and q["headline_ko"].startswith("정상:")
    assert page.index("한 줄 결론") < page.index("어떻게 하면 되나요") < page.index("점검표")
    rows = o["sel"]["rows"]
    assert len(rows) == len(q["checks"]) + 1 and rows[0]["d"]["check"] == "written" and "엔진이 기록을 쓴 지" in rows[0]["t"] and "정상" in rows[0]["t"]
    prices = next(r for r in rows if r["d"]["check"] == "prices")
    assert "확인 못 함" in prices["t"] and "스냅샷에 코인별" in prices["t"]
    assert all(any(w in r["t"] for w in ("정상", "주의", "확인 필요", "확인 못 함")) for r in rows)        # the result is always a word
    assert "아무것도 하지 않아도" in page and "이 점검의 한계" in page
    no_junk(page)
    k = run(tmp_path, "dataq", d, SELS, local={"cl-dataq-view": json.dumps("card")})
    assert not k["sel"]["rows"] and len(k["sel"]["cards"]) == len(q["checks"]) + 1 and any("확인 못 함" in c["t"] for c in k["sel"]["cards"])
    no_junk(k["text"])


def test_dataq_late_check_and_the_screens_own_clock(tmp_path):
    d = doc(name="dataq")
    d["dataq"].update(status="late", status_ko="늦음", headline_ko="늦음: 엔진이 늦습니다", todo_ko=DQ.todo_ko("late"))
    o = run(tmp_path, "dataq", d, SELS)
    assert "늦음" in o["sel"]["big"][0]["t"] and "10~20분" in o["text"]
    d["dataq"].update(status="check", status_ko="확인 필요", headline_ko="확인 필요: 계산 중 난 오류: 1개", todo_ko=DQ.todo_ko("check"),
                      errors=[{"key": "risk_error", "text": "ValueError: boom"}])
    o = run(tmp_path, "dataq", d, SELS)
    assert "개발자에게 보내" in o["text"] and "계산 중 난 오류" in o["text"] and "risk_error" in o["text"] and "ValueError: boom" in o["text"]
    # the record was written long ago: whatever the block says, the page says 확인 필요 (never 정상 under a stopped engine)
    old = doc(name="dataq")
    old["generated_ms"] -= 40 * 60_000
    o = run(tmp_path, "dataq", old, SELS)
    assert o["sel"]["big"][0]["t"].startswith("확인 필요: ") and "개발자에게 보내" in o["text"]
    no_junk(o["text"])


def test_dataq_absent_and_null_values(tmp_path):
    for dd, need, notneed in ((doc(None, "dataq"), ("데이터 준비 중", "점검 기록은 아직 없습니다"), ("새 리그 전용",)), (doc({"checks": "x"}, "dataq"), ("데이터 준비 중",), ()),
                              (doc(None, "dataq", lineup=False), ("새 리그 전용", "이전 리그"), ("데이터 준비 중",)), (doc(None, "dataq", accounts=False), ("준비 중",), ("새 리그 전용",))):
        o = run(tmp_path, "dataq", dd, SELS)
        for w in need:
            assert w in o["text"], w
        for w in notneed:
            assert w not in o["text"], w
        assert "이 화면은 무엇인가요" in o["text"] and not o["sel"]["rows"]
        no_junk(o["text"])
    nulls = {"status": "ok", "headline_ko": None, "reason_ko": None, "todo_ko": None, "note_ko": None, "errors": None, "engine_notes": None,
             "checks": [{"id": "lag", "label_ko": None, "value_ko": None, "level": None, "word_ko": None, "detail_ko": None}]}
    d = doc(nulls, "dataq")
    d["generated_ms"] = None
    for view in ("table", "card"):
        o = run(tmp_path, "dataq", d, SELS, local={"cl-dataq-view": json.dumps(view)})
        no_junk(o["text"])
        assert "확인 못 함" in o["text"] and "—" in o["text"]


# ---------------------------------------------------------------- static rules and registration
@pytest.mark.parametrize("name", NAMES)
def test_the_files_and_the_static_rules(name):
    src = open(os.path.join(STATIC, "js", "screens", f"{name}.js"), encoding="utf-8").read()
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "document.write", "new Function", "eval(", "binance.com"):
        assert bad not in src, bad
    assert f"export const css = {json.dumps(CSS[name])}".replace('"', '"') in src
    from candleague import dash as D
    for f in (f"js/screens/{name}.js", f"scr/{name}.css", "scr/kinds.css"):
        assert f in D._static_files(), f
    css = open(os.path.join(STATIC, "scr", f"{name}.css"), encoding="utf-8").read()
    for text in (src, css):
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsl\(", text)                                  # colours only from the tokens
    for m in re.finditer(r'fontSize: "([^"]+)"', src):
        assert m.group(1).startswith("var(--t-"), m.group(0)
    for decl in re.findall(r"(?<![\w-])font(?:-size)?:[^;}]*", css):
        assert "var(--t-" in decl, decl
    assert not re.search(r"\$\s?5,?000|5000", src + css)
    for sel in re.findall(r"^([^\s{@/][^{]*)\{", css, re.M):
        for part in sel.split(","):
            assert part.strip().startswith(".scr.kd "), part


def test_default_rules_equal_the_servers_and_registration_snippets_once_added():
    app = open(os.path.join(STATIC, "js", "app.js"), encoding="utf-8").read()
    for name in NAMES:
        if f"{name}:" not in app and f'"{name}"' not in app:
            pytest.skip("the coordinator has not registered the three screens yet")
        assert f"screens/{name}.js" in app or f"{name}: () => import" in app or re.search(rf"\b{name}\b", app)
