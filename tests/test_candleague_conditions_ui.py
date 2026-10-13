"""candleague 조건별 성적 screen (js/screens/conditions.js, css scr/conditions.css): the exploratory look at where a structure works.

The screen is mounted for real under node on the DOM stand-in of test_candleague_rank_ui (text nodes only, like the browser's) with snapshots
whose ``conditions`` block is made by the real summary.conditions_views from synthetic trades (and with hand-made blocks), and the tests read
what reached the page:
  (a) full data: the one-sentence headline (the server's), the exploratory caveat, the folded reading rules, the 실전 후보 / 대조 switch,
      one card per dimension in order with its buckets as rows, the columns (mean, coin twin's mean, ▲ / ▼ difference with its number, n),
      the clear-of-zero words, "적음" for a few bucket and no mean in it, the unknown buckets muted;
  (b) the switch to the control, (c) the phone's card view, (d) ``conditions`` absent / malformed / old league / no snapshot: "데이터 준비 중"
      and the rule box, (e) a pair missing, (f) no "undefined / NaN / null" with null numbers, (g) DeepSeek note both ways, (h) start wallet;
  plus the static rules (text only, tokens only, own css file served) and, once the coordinator registers the screen in app.js / find.js,
  the menu entry right after 판정 and 찾기."""

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

import test_candleague_conditions as TC  # noqa: E402  (its synthetic trades and the lineup)
import test_candleague_decision_ui as DUI  # noqa: E402  (its snapshot fixture)
import test_candleague_rank_ui as RANK  # noqa: E402  (its DOM stand-in)
from candleague import summary as SM  # noqa: E402

STATIC = os.path.join(ROOT, "candleague", "static")
T0, DAY = TC.T0, TC.DAY
BAD = ("NaN", "undefined", "null", "Infinity")


# ---------------------------------------------------------------- snapshots with a conditions block
def stamped_book(gap=0.04, picks=(("core-A-1h-1", "1h", "core"), ("core-B-15m-1", "15m", "core"), ("core-C-4h-1", "4h", "core"))):
    """-fq beats its twin by ``gap`` on the same signals, the control does not; stamps g1 / g2 spread over True / False / None."""
    book = TC.paired_book(n_days=14, per_day=8, gap=gap, twin_noise=1.0, picks=picks)
    for aid, rows in book.items():
        book[aid] = [r[:5] + ([True, False, None][i % 3], [True, False, True, None][i % 4]) for i, r in enumerate(rows)]
    return TC.accounts(picks), book


def block(**kw) -> dict:
    accts, book = stamped_book(**kw)
    return json.loads(json.dumps(SM.conditions_views(book, accts, TC.LU, T0, T0 + 14 * DAY, False), allow_nan=False))


def doc_with(conditions="full", **kw) -> dict:
    d = DUI._doc(decision=None, **kw)
    if conditions == "full":
        d["conditions"] = block()
    elif conditions is not None:
        d["conditions"] = conditions
    return d


# ---------------------------------------------------------------- the node runner
RUNNER = r"""
import {readFileSync} from "node:fs";
import {install, txt} from "./shim.mjs";
const cfg = JSON.parse(readFileSync(process.argv[2], "utf8"));
const store = install(cfg);
globalThis.location.hash = "";
if (cfg.width) globalThis.innerWidth = cfg.width;
const S = cfg.static;
const LK = await import(`file://${S}/js/lk.js`);
const doc = cfg.doc;
if (doc) LK.setLeague(doc);
const M = await import(`file://${S}/js/screens/conditions.js`);
const el = document.createElement("div");
el.dataset.screen = "conditions";
document.body.appendChild(el);
const ctx = {params: {name: "conditions", arg: null, query: {}}, alive: () => true, signal: null,
  api: async (p) => (await globalThis.fetch(p)).json(), meta: () => LK.getMeta(),
  onLeague: (fn) => { if (doc) fn(doc); }, onLive: () => () => {}, onPositions: () => () => {},
  every: () => {}, css: async () => null, wide() {}, setTitle() {}, setQuery() {},
  href: (n, a) => `#/${n}${a ? "/" + a : ""}`};
const tick = async () => { for (let i = 0; i < 4; i++) await new Promise((r) => setTimeout(r, 10)); };
await M.mount(el, ctx);
await tick();
for (const sel of cfg.clicks || []) {
  const b = el.querySelectorAll(sel)[0];
  if (!b) throw new Error("nothing to click: " + sel);
  b.fire("click");
  await tick();
}
const out = {text: txt(el), css: M.css, cls: el.className, sel: {}, rules: M.RULES, store: Object.fromEntries(store)};
for (const [k, sel] of Object.entries(cfg.sels || {})) {
  out.sel[k] = el.querySelectorAll(sel).map((n) => ({t: txt(n), d: {...n.dataset}, c: n.className, a: Object.fromEntries(n.attrs)}));
}
console.log(JSON.stringify(out));
process.exit(0);
"""


def _run(tmp_path, doc, sels=None, local=None, clicks=None, width=None) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    (tmp_path / "shim.mjs").write_text(RANK.SHIM)
    (tmp_path / "run.mjs").write_text(RUNNER)
    cfg = {"static": STATIC, "routes": {}, "local": local or {}, "doc": doc, "sels": sels or {}, "clicks": clicks or [], "width": width}
    (tmp_path / "cfg.json").write_text(json.dumps(cfg, ensure_ascii=False))
    r = subprocess.run([node, str(tmp_path / "run.mjs"), str(tmp_path / "cfg.json")], capture_output=True, text=True, timeout=120, cwd=str(tmp_path))
    assert r.returncode == 0, (r.stdout[-600:], r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def _no_junk(text: str) -> None:
    for bad in BAD:
        assert bad not in text, bad


SELS = {"hero": ".cn-hero", "head": ".cn-head", "note": ".cn-note", "rules": "ol.cn-rules li", "plates": ".plate", "dims": "section.cn-dim",
        "rows": "tr.cn-row", "cards": "article.cn-card", "good": "tr.cn-row[data-flag=\"good\"]", "bad": "tr.cn-row[data-flag=\"bad\"]",
        "unk": "tr.cn-row[data-unknown=\"1\"]", "few": ".cn-few", "seg": ".seg button", "flags": ".cn-flag", "bars": ".cn-bar", "line": ".cn-pairline",
        "th": "th", "pills": ".pp", "after": "section.cn-dim[id=\"cn-hold\"]"}


# ---------------------------------------------------------------- (a) full data
def test_full_data_headline_caveat_cards_in_order_and_the_columns(tmp_path):
    d = doc_with()
    C = d["conditions"]
    o = _run(tmp_path, d, SELS)
    page = o["text"]
    assert o["css"] == ["scr/kinds.css", "scr/conditions.css"] and "cn" in o["cls"].split() and "kd" in o["cls"].split()
    assert "조건별 성적" in page and "탐색용" in page
    # the one sentence is the server's, with the caveat under it
    assert o["sel"]["head"][0]["t"] == C["headline_ko"] and o["sel"]["note"][0]["t"] == C["note_ko"]
    assert "칸이 많아서 우연히 좋아 보이는 칸이 저절로 생기고" in o["sel"]["note"][0]["t"] and "판정" in o["sel"]["note"][0]["t"]
    assert page.index(C["headline_ko"]) < page.index("요일")                                       # the headline first, the cards after it
    # the reading rules (folded, but in the page): exploratory, what is compared, many cells, what it is for
    rules = [r["t"] for r in o["sel"]["rules"]]
    assert len(rules) == 4 and rules[0].startswith("탐색용:") and "통과 · 실패를 매기지 않고" in rules[0] and rules[1].startswith("무엇을 비교하나:")
    assert "차이 = 실제 평균 − 동전 평균" in rules[1] and rules[2].startswith("칸이 많으면:") and "30건 미만" in rules[2] and rules[3].startswith("어디에 쓰나:")
    assert "읽는 법 보기" in page
    # the switch: 실전 후보 (selected) and 대조, and 표 / 카드
    seg = o["sel"]["seg"]
    assert [b["t"] for b in seg] == ["실전 후보", "대조", "표", "카드"] and seg[0]["a"]["aria-selected"] == "true" and seg[1]["a"]["aria-selected"] == "false"
    assert "실전 후보(-fq) 거래" in o["sel"]["line"][0]["t"] and "동전(-fqc) 거래" in o["sel"]["line"][0]["t"] and "모든 후보를 합친 수입니다" in o["sel"]["line"][0]["t"]
    # one card per dimension, in the server's order, each named by its plate
    assert [p["t"] for p in o["sel"]["plates"] if p["t"] in ("요일", "시간대", "방향", "코인", "봉", "BTC 추세", "변동성", "보유시간")] == [
        "요일", "시간대", "방향", "코인", "봉", "BTC 추세", "변동성", "보유시간"]
    assert len(o["sel"]["dims"]) == len(C["dims"]) == 8
    rows = o["sel"]["rows"]
    assert len(rows) == sum(len(x["buckets"]) for x in C["dims"]) and not o["sel"]["cards"]
    assert [(r["d"]["dim"], r["d"]["bucket"]) for r in rows] == [(x["id"], b["id"]) for x in C["dims"] for b in x["buckets"]]
    heads = [t["t"] for t in o["sel"]["th"]]
    assert heads.count("실전 후보 평균") == 8 and heads.count("동전 평균") == 8 and heads.count("차이") == 8 and heads.count("거래 수") == 8
    # a row, read against the block: the name, both means, the difference with ▲ and its number, the range, the counts n · n
    wk = next(r for r in rows if r["d"]["dim"] == "weekday" and r["d"]["bucket"] == "weekday")
    b = next(b for b in C["dims"][0]["buckets"] if b["id"] == "weekday")
    df = b["diffs"]["-fq"]
    assert df["diff"] == pytest.approx(0.04, abs=1e-6)
    assert "평일" in wk["t"] and "월~금 (UTC)" in wk["t"] and "▲ +4.0%p" in wk["t"] and f"{b['kinds']['-fq']['n']:,} · {b['kinds']['-fqc']['n']:,}" in wk["t"]
    assert "범위 +4.0 ~ +4.0%p" in wk["t"] and "구간이 0 위" in wk["t"] and wk["d"]["flag"] == "good" and wk["d"]["few"] == "0"
    assert re.search(r"[+−]\d+\.\d+%", wk["t"]) and "승률" in wk["t"]                                  # a mean in percent, the win rate small
    # the sign is always a mark and a number: every difference starts with ▲ ▼ or ＝, never colour alone
    assert len(o["sel"]["good"]) > 0 and all("구간이 0 위" in r["t"] for r in o["sel"]["good"]) and not o["sel"]["bad"]
    assert len(o["sel"]["flags"]) == len(o["sel"]["good"]) and len(o["sel"]["bars"]) >= len(o["sel"]["good"])
    # the unknown buckets are muted rows with their words; the hold-time card says it is known only after the entry
    assert len(o["sel"]["unk"]) == 2 and all(r["d"]["bucket"] == "unknown" and "모름" in r["t"] and r["d"]["flag"] == "" for r in o["sel"]["unk"])
    assert "끝난 뒤에 아는 값" in o["sel"]["after"][0]["t"] and "조건으로 쓸 수 없고 참고만 합니다" in o["sel"]["after"][0]["t"]
    # the session card carries the Korean time of the UTC hours
    assert "UTC 00~08 · 한국 09~17시" in page and "UTC 16~24 · 한국 01~09시" in page
    # the closing: the wallet, the shared signals, DeepSeek out, no real orders
    assert "$1,000" in page and "$5,000" not in page and "딥시크를 뺀 후보만으로 계산했습니다" in page and "실제 주문은 넣지 않습니다" in page
    _no_junk(page)


def test_a_bucket_with_few_trades_says_so_and_has_no_mean(tmp_path):
    C = block()
    b0 = C["dims"][0]["buckets"][1]                                                                 # the weekend bucket: make it few for both kinds
    for k in b0["kinds"].values():
        k.update(few=True, mean=None, win_rate=None, n=12, wins=5)
    for dd in b0["diffs"].values():
        dd.update(few=True, diff=None, lo=None, hi=None, flag=None, n=12, n_twin=12)
    o = _run(tmp_path, doc_with(C), SELS)
    row = next(r for r in o["sel"]["rows"] if r["d"]["bucket"] == "weekend")
    assert row["d"]["few"] == "1" and row["d"]["flag"] == "" and row["t"].count("적음") == 2 and "비교 불가" in row["t"] and "▲" not in row["t"] and "▼" not in row["t"]
    assert "%" not in row["t"].replace("%p", "")                                                  # no mean in percent, no win rate
    assert "12 · 12" in row["t"]
    assert len(o["sel"]["few"]) >= 3
    _no_junk(o["text"])
    # the hint on a few cell says how many trades it takes
    assert any("30건 이상 필요" in (f["a"].get("title") or "") for f in o["sel"]["few"])


def test_a_worse_than_coin_bucket_is_red_with_a_down_arrow_and_its_words(tmp_path):
    C = block(gap=-0.05)
    o = _run(tmp_path, doc_with(C), SELS)
    assert o["sel"]["bad"] and not o["sel"]["good"]
    r = o["sel"]["bad"][0]
    assert "▼ −5.0%p" in r["t"] and "구간이 0 아래" in r["t"] and "bad" in " ".join(f["c"] for f in o["sel"]["flags"]).split()
    assert "neg" in " ".join(b["c"] for b in o["sel"]["bars"]).split()
    _no_junk(o["text"])


# ---------------------------------------------------------------- (b) the control, (c) cards
def test_switching_to_the_control_shows_its_numbers(tmp_path):
    C = block()
    o = _run(tmp_path, doc_with(C), SELS, clicks=[".seg button[data-id=\"-ld\"]"])
    heads = [t["t"] for t in o["sel"]["th"]]
    assert heads.count("대조 평균") == 8 and heads.count("실전 후보 평균") == 0 and heads.count("동전 평균") == 8
    assert "대조(-ld) 거래" in o["sel"]["line"][0]["t"] and "동전(-ldc) 거래" in o["sel"]["line"][0]["t"] and "원래 방식인 고정 손절 계단" in o["sel"]["line"][0]["t"]
    # the control has no effect over its twin in this world: no clear-of-zero rows, differences are ＝ 0
    assert not o["sel"]["good"] and not o["sel"]["bad"] and "＝" in o["text"] and "▲" not in o["text"] and "▼" not in o["text"]
    seg = o["sel"]["seg"]
    assert seg[0]["a"]["aria-selected"] == "false" and seg[1]["a"]["aria-selected"] == "true"
    assert json.loads(o["store"]["cl-conditions-pair"]) == "-ld"                                       # remembered for the next visit
    o = _run(tmp_path, doc_with(C), SELS, local={"cl-conditions-pair": json.dumps("-ld")})
    assert [t["t"] for t in o["sel"]["th"]].count("대조 평균") == 8
    # a saved choice the snapshot does not have falls back to the first pair
    o = _run(tmp_path, doc_with(C), SELS, local={"cl-conditions-pair": json.dumps("-zz")})
    assert [t["t"] for t in o["sel"]["th"]].count("실전 후보 평균") == 8
    _no_junk(o["text"])


def test_phone_card_view_has_a_compact_card_per_bucket(tmp_path):
    C = block()
    n = sum(len(x["buckets"]) for x in C["dims"])
    for kw in ({"width": 390}, {"local": {"cl-conditions-view": json.dumps("card")}}):
        o = _run(tmp_path, doc_with(C), SELS, **kw)                                                  # a phone opens on the cards; the saved choice does too
        cards = o["sel"]["cards"]
        assert len(cards) == n and not o["sel"]["rows"]
        wk = next(c for c in cards if c["d"]["dim"] == "weekday" and c["d"]["bucket"] == "weekday")
        assert "평일" in wk["t"] and "▲ +4.0%p" in wk["t"] and "구간이 0 위" in wk["t"] and "실전 후보 평균" in wk["t"] and "동전 평균" in wk["t"] and "거래 수" in wk["t"]
        assert "범위 +4.0 ~ +4.0%p" in wk["t"] and wk["d"]["flag"] == "good"
        assert [b["t"] for b in o["sel"]["seg"]] == ["실전 후보", "대조", "표", "카드"]
        assert o["sel"]["seg"][3]["a"]["aria-selected"] == "true"
        _no_junk(o["text"])
    # a wide window opens on the table, and the 카드 button switches (and is remembered)
    o = _run(tmp_path, doc_with(C), SELS, width=1280, clicks=[".seg button[data-id=\"card\"]"])
    assert len(o["sel"]["cards"]) == n and json.loads(o["store"]["cl-conditions-view"]) == "card"
    o = _run(tmp_path, doc_with(C), SELS, width=1280)
    assert len(o["sel"]["rows"]) == n and not o["sel"]["cards"]
    # a few bucket in the card view
    C["dims"][0]["buckets"][0]["kinds"]["-fq"].update(few=True, mean=None, win_rate=None)
    C["dims"][0]["buckets"][0]["diffs"]["-fq"].update(few=True, diff=None, lo=None, hi=None, flag=None)
    o = _run(tmp_path, doc_with(C), SELS, width=390)
    first = o["sel"]["cards"][0]
    assert "비교 불가" in first["t"] and "적음" in first["t"] and "▲" not in first["t"] and first["d"]["few"] == "1"
    _no_junk(o["text"])


# ---------------------------------------------------------------- (d) absent / malformed / old league / no snapshot
def test_conditions_absent_old_league_and_no_snapshot(tmp_path):
    cases = ((doc_with(None), ("데이터 준비 중", "조건별 기록은 아직 없습니다"), ("새 리그 전용",)),
             (doc_with({"dims": "x"}), ("데이터 준비 중",), ("새 리그 전용",)),                          # malformed = absent
             (doc_with(None, lineup=False), ("새 리그 전용", "이전 리그"), ("데이터 준비 중",)),
             (doc_with(None, accounts=False), ("준비 중", "후보 리그 기록이 아직 없습니다"), ("새 리그 전용",)),
             (None, ("준비 중",), ("새 리그 전용",)))
    for d, need, notneed in cases:
        o = _run(tmp_path, d, SELS)
        for t in need:
            assert t in o["text"], (t, o["text"][:300])
        for t in notneed:
            assert t not in o["text"], t
        # the rule box is there anyway, with the exploratory words; no cards
        assert "이 화면은 탐색용입니다" in o["text"] and len(o["sel"]["rules"]) == 4 and not o["sel"]["dims"] and not o["sel"]["rows"]
        _no_junk(o["text"])


def test_a_block_without_dimensions_or_pairs_is_a_note_not_a_crash(tmp_path):
    C = block()
    empty = {**C, "dims": [], "pairs": [], "n_cells": 0, "headline_ko": "아직 닫힌 거래가 없어서 비교할 것이 없습니다"}
    o = _run(tmp_path, doc_with(empty), SELS)
    assert "아직 닫힌 거래가 없어서 비교할 것이 없습니다" in o["text"] and "비교할 계좌 종류가 아직 없습니다" in o["text"] and not o["sel"]["rows"]
    no_pair = {**C, "pairs": []}
    o = _run(tmp_path, doc_with(no_pair), SELS)
    assert "비교할 계좌 종류가 아직 없습니다" in o["text"] and not o["sel"]["rows"]
    _no_junk(o["text"])


def test_a_pair_the_snapshot_lacks_is_not_offered(tmp_path):
    C = block()
    C["pairs"] = [p for p in C["pairs"] if p["real"] == "-ld"]
    o = _run(tmp_path, doc_with(C), SELS)
    assert [b["t"] for b in o["sel"]["seg"]] == ["대조", "표", "카드"] and [t["t"] for t in o["sel"]["th"]].count("대조 평균") == 8
    _no_junk(o["text"])


# ---------------------------------------------------------------- (f) null numbers, unknown shapes
def test_null_numbers_read_as_dashes_and_nothing_is_undefined(tmp_path):
    C = block()
    for dim in C["dims"]:
        for b in dim["buckets"]:
            for k in b["kinds"].values():
                k.update(mean=None, win_rate=None, n=None)
            for dd in b["diffs"].values():
                dd.update(diff=None, lo=None, hi=None, n=None, n_twin=None)
    o = _run(tmp_path, doc_with(C), SELS)
    _no_junk(o["text"])
    assert "▲" not in o["text"] and "▼" not in o["text"] and "＝" not in o["text"]
    # pieces missing altogether still render
    thin = {"dims": [{"id": "weekday", "ko": "요일", "buckets": [{"id": "weekday", "ko": "평일"}]}], "pairs": [{"real": "-fq", "twin": "-fqc"}]}
    o = _run(tmp_path, doc_with(thin), SELS)
    assert len(o["sel"]["rows"]) == 1 and "평일" in o["sel"]["rows"][0]["t"] and "—" in o["sel"]["rows"][0]["t"] and "탐색용" in o["text"]
    _no_junk(o["text"])
    # only unknown buckets (trades from before the stamps): a note that the record is not there yet
    old = block()
    for dim in old["dims"]:
        if dim["id"] in ("g1", "g2"):
            dim["buckets"] = [b for b in dim["buckets"] if b["unknown"]]
    o = _run(tmp_path, doc_with(old), SELS)
    assert o["text"].count("이 기록은 아직 없습니다") == 2 and "모름" in o["text"]
    _no_junk(o["text"])


# ---------------------------------------------------------------- (g) DeepSeek, (h) the wallet
def test_deepseek_note_both_ways_and_the_wallet(tmp_path):
    C = block()
    o = _run(tmp_path, doc_with(C))
    assert "딥시크를 뺀 후보만으로 계산했습니다" in o["text"] and "딥시크 계좌도 들어 있습니다" not in o["text"]
    C2 = {**C, "ds_in_stats": True}
    o = _run(tmp_path, doc_with(C2))
    assert "딥시크 계좌도 들어 있습니다" in o["text"] and "딥시크를 뺀" not in o["text"]
    o = _run(tmp_path, doc_with(C, equity0=None))
    assert "$" not in o["text"] and "모의 계좌입니다 (가상 돈)" in o["text"]
    assert "5,000" not in _run(tmp_path, doc_with(C, equity0=1000))["text"]


# ---------------------------------------------------------------- the real server block with the real stamps
def test_a_block_made_by_the_real_summary_from_a_stamped_league_renders(tmp_path):
    C = block()
    assert C["n_cells"] > 20 and C["n_good"] > 0 and C["expected_lucky"] == round(0.05 * C["n_cells"])
    o = _run(tmp_path, doc_with(C), SELS)
    assert len(o["sel"]["good"]) == sum(1 for dim in C["dims"] for b in dim["buckets"] if b["diffs"]["-fq"]["flag"] == "good")
    assert o["sel"]["head"][0]["t"] == C["headline_ko"] and f"{C['n_cells']}칸 중" in o["sel"]["head"][0]["t"]
    _no_junk(o["text"])


# ---------------------------------------------------------------- the static rules, the menu and 찾기 (once registered)
def test_the_file_the_css_and_the_static_rules():
    src = open(os.path.join(STATIC, "js", "screens", "conditions.js"), encoding="utf-8").read()
    css = open(os.path.join(STATIC, "scr", "conditions.css"), encoding="utf-8").read()
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "document.write", "new Function", "eval(", "binance.com"):
        assert bad not in src, bad
    assert 'export const css = ["scr/kinds.css", "scr/conditions.css"]' in src
    from candleague import dash as D
    assert "js/screens/conditions.js" in D.STATIC_FILES and "scr/conditions.css" in D.STATIC_FILES and "scr/kinds.css" in D.STATIC_FILES
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsl\(", src) and not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsl\(", css)       # colours only from the tokens
    for m in re.finditer(r"font(?:-size)?:[^;}]*", css):
        for size in re.findall(r"\d+(?:\.\d+)?px", m.group(0)):
            raise AssertionError(f"a fixed font size in the css: {m.group(0)}")                                                  # font sizes only var(--t-*)
    assert all(sel.strip().startswith(".scr.cn") for sel in re.findall(r"^([^@/\s{][^{]*)\{", css, re.M) for sel in sel.split(",")), "every rule is scoped to .scr.cn"
    # no horizontal page scroll on a phone: the table scrolls inside its own box, the cards are one column
    assert "tbl-wrap" in src and "@media (max-width: 459px)" in css and "minmax(0, 1fr)" in css
    # the JS does not run on text it did not make: every string goes through h()
    assert "textContent =" not in src.replace("el.textContent", "")


def test_menu_entry_and_find_words_once_registered():
    app = open(os.path.join(STATIC, "js", "app.js"), encoding="utf-8").read()
    find = open(os.path.join(STATIC, "js", "find.js"), encoding="utf-8").read()
    if 'id: "conditions"' not in app:
        pytest.skip("the screen is not registered in app.js yet (the coordinator adds the MENU / MENU_TITLE / SCREENS entries)")
    menu = re.findall(r'\{id: "(\w+)", ko: "([^"]+)", group: "(\w+)"', re.search(r"const MENU = \[(.*?)\];", app, re.S).group(1))
    ids = [m[0] for m in menu]
    i = ids.index("decision")
    assert ids[i + 1] == "conditions" and menu[i + 1][1] == "조건별" and menu[i + 1][2] == "home"
    assert 'conditions: "conditions"' in re.search(r"const SCREENS = \{([^}]*)\}", app).group(1)
    assert re.search(r"\bconditions: \"조건별 성적", re.search(r"const MENU_TITLE = \{(.*?)\};\s*const SCREENS", app, re.S).group(1))
    assert re.search(r"\bconditions: \"조건별 성적 ", find)
