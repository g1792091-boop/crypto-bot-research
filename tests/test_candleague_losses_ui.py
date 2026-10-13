"""candleague 손실 해부 screen (js/screens/losses.js, css scr/losses.css + scr/kinds.css) and its menu / 찾기 / 한눈 지도 entries.

The screen is mounted for real under node on the DOM stand-in of test_candleague_rank_ui (text nodes only) with snapshots whose ``losses`` is written by
the real candleague.lossview.loss_views from hand-made trades (or edited by hand); the tests read what reached the page:
  (a) full data: the rule box first, the server's sentence, the picker (default 핵심 2개 = 빠른 손절 + 원래 방식), one card per kind with the counts, the stacked
      bar of loss types with every type written, the explanations under a disclosure, five breakdown tables, the streak / cluster lines and the 10 biggest
      losses each with a 다시보기 link to #/replay?acct=..&at=..; (b) the other picker choices; (c) ``losses`` absent: 준비 중 / 새 리그 전용 / 준비 중;
  (d) null numbers read "—", never 0 / NaN / undefined / null; (e) 표본 적음; (f) the DeepSeek note both ways;
Plus the static rules (text only, tokens only, scoped CSS), the type words equal to the server's, and the registration snippets."""

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

import test_candleague_lossview as LT  # noqa: E402  (the hand-made trades of the server tests)
import test_candleague_rank_ui as RANK  # noqa: E402  (its DOM stand-in)
import test_candleague_riskview as RT  # noqa: E402
from candleague import lossview as LV  # noqa: E402

STATIC = os.path.join(ROOT, "candleague", "static")
NOW = RT.T0 + 15 * RT.DAY
BAD = ("NaN", "undefined", "null", "Infinity", "[object")


# ---------------------------------------------------------------- hand-made snapshots
def losses_block(ds=False, many=False):
    book, rows, _ = LT.world()
    if many:                                           # 12 more losses on p1-fq so the 10 biggest are a cut and the kind is not small
        extra = [LT.loss(entry_t=RT.T0 + (10 + i) * 5 * RT.H, roe=-0.05 * (i + 1), pnl=-5.0, sym=RT.COINS[i % 6]) for i in range(40)]
        book["p1-fq"] = sorted(book["p1-fq"] + extra, key=lambda t: t["exit_time"])
    rows.append(RT.row("p1-nv", "nv"))
    book["p1-nv"] = [LT.loss("slow", entry_t=RT.T0 + 8 * RT.H)]
    rows.append(RT.row("ds-fq", "fq", kind="ds"))
    book["ds-fq"] = [LT.loss(roe=-0.7, pnl=-700.0)]
    return json.loads(json.dumps(LV.loss_views(book, rows, RT.LU, ds), allow_nan=False))


def doc(losses="full", lineup=True, accounts=True, ds=False, many=False) -> dict:
    d = {"generated_ms": NOW - 60_000, "done_ms": NOW, "start_ms": RT.T0, "started_ms": RT.T0, "judge": {}, "ds_money": False, "equity0": 1000,
         "watch": {"checkpoints": [], "pools": {}},
         "accounts": [{"id": "core-X-1h-1-fq", "role": "fq", "kind": "core", "name": "X", "tf": "1h", "trades": 5, "wins": 3, "mean_ret": 0.01, "wallet": 1000.0,
                       "max_dd": 0.02, "bust": False, "open": None}]}
    if not accounts:
        del d["accounts"]
    if lineup:
        d["lineup"] = [{"role": k["role"], "suffix": k["suffix"], "label_ko": k["label_ko"], "short_ko": k["short_ko"], "accounts": 12} for k in RT.LU]
    if losses == "full":
        d["losses"] = losses_block(ds=ds, many=many)
    elif losses is not None:
        d["losses"] = losses
    return d


# ---------------------------------------------------------------- the node runner (this test's own copy)
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
const M = await import(`file://${S}/js/screens/losses.js`);
const el = document.createElement("div");
el.dataset.screen = "losses";
document.body.appendChild(el);
const ctx = {params: {name: "losses", arg: null, query: {}}, alive: () => true, signal: null,
  api: async (p) => (await globalThis.fetch(p)).json(), meta: () => LK.getMeta(),
  onLeague: (fn) => { if (doc) fn(doc); }, onLive: () => () => {}, onPositions: () => () => {},
  every: () => {}, css: async () => null, wide() {}, setTitle() {}, setQuery() {},
  href: (n, a) => `#/${n}${a ? "/" + a : ""}`};
await M.mount(el, ctx);
const wait = async () => { for (let i = 0; i < 4; i++) await new Promise((r) => setTimeout(r, 10)); };
await wait();
for (const c of cfg.clicks || []) { const b = el.querySelector(c); if (!b) throw new Error("no " + c); b.fire("click"); await wait(); }
const out = {text: txt(el), css: M.css, cls: el.className, sel: {}, types: M.TYPES_DEFAULT, min: M.MIN_LOSSES};
for (const [k, sel] of Object.entries(cfg.sels || {})) {
  out.sel[k] = el.querySelectorAll(sel).map((n) => ({t: txt(n), d: {...n.dataset}, c: n.className, a: Object.fromEntries(n.attrs)}));
}
out.cards = el.querySelectorAll("section.lv-card").map((c) => ({id: c.attrs.get("id"), t: txt(c),
  bar: (c.querySelector(".lv-bar") || {attrs: new Map()}).attrs.get("aria-label") || null,
  legend: c.querySelectorAll(".lv-leg .kd-rc").map((n) => ({type: n.dataset.type, t: txt(n)})),
  words: c.querySelectorAll("dl.kd-legend div").map((n) => ({type: n.dataset.typeword, t: txt(n)})),
  tables: c.querySelectorAll(".lv-bd").map((n) => ({bd: n.dataset.bd, rows: n.querySelectorAll("tr.kd-row").map(txt)})),
  facts: c.querySelectorAll("div[data-fact]").map((n) => ({k: n.dataset.fact, t: txt(n)})),
  streak: c.querySelectorAll("ul.lv-streak li").map(txt),
  worst: c.querySelectorAll("table.lv-worst tbody tr").map((r) => ({t: txt(r), type: r.dataset.type, href: (r.querySelector("a") || {attrs: new Map()}).attrs.get("href") || null})),
  pills: c.querySelectorAll(".pp").map(txt)}));
console.log(JSON.stringify(out));
process.exit(0);
"""


def run(tmp_path, d, sels=None, local=None, clicks=None) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    (tmp_path / "shim.mjs").write_text(RANK.SHIM)
    (tmp_path / "run.mjs").write_text(RUNNER)
    cfg = {"static": STATIC, "routes": {}, "local": local or {}, "doc": d, "sels": sels or {}, "clicks": clicks or []}
    (tmp_path / "cfg.json").write_text(json.dumps(cfg, ensure_ascii=False))
    r = subprocess.run([node, str(tmp_path / "run.mjs"), str(tmp_path / "cfg.json")], capture_output=True, text=True, timeout=120, cwd=str(tmp_path))
    assert r.returncode == 0, (r.stdout[-600:], r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def no_junk(text: str) -> None:
    for bad in BAD:
        assert bad not in text, bad


SELS = {"rules": "ol.kd-rules li", "big": ".kd-hero .dl-vbig", "line": ".kd-hero .dl-vline", "plates": ".plate", "limits": "ul.kd-list li", "seg": ".seg button",
        "pressed": '.seg button[aria-selected="true"]'}


def card(o, role):
    return next(c for c in o["cards"] if c["id"] == f"lv-{role}")


# ---------------------------------------------------------------- (a) full data
def test_full_data_rules_first_then_the_sentence_then_the_core_two(tmp_path):
    d = doc()
    L = d["losses"]
    o = run(tmp_path, d, SELS)
    page = o["text"]
    assert o["css"] == ["scr/kinds.css", "scr/losses.css"] and "kd" in o["cls"].split()
    assert len(o["sel"]["rules"]) == 4 and "이 화면은 무엇인가요" in page and page.index("이 화면은 무엇인가요") < page.index("한 줄 결론")
    assert o["sel"]["big"][0]["t"] == L["headline_ko"] and L["headline_ko"].startswith("빠른 손절")
    assert [x["t"] for x in o["sel"]["seg"]] == ["핵심 2개", "모든 종류 합계", "종류 전부"] and [x["t"] for x in o["sel"]["pressed"]] == ["핵심 2개"]
    assert [c["id"] for c in o["cards"]] == ["lv-fq", "lv-ld"]                                    # 빠른 손절 + 원래 방식 (the control)
    assert "아래에 보는 종류: 빠른 손절 · 계단" in o["sel"]["line"][0]["t"]
    no_junk(page)
    assert page.index("한 줄 결론") < page.index("진 거래의 유형") and "이 숫자의 한계" in page and "딥시크를 뺀 후보만으로" in page


def test_the_card_of_a_kind_counts_types_tables_streak_and_worst(tmp_path):
    d = doc()
    o = run(tmp_path, d)
    c = card(o, "fq")
    k = next(k for k in d["losses"]["kinds"] if k["role"] == "fq")
    facts = {f["k"]: f["t"] for f in c["facts"]}
    assert "7건" in facts["trades"] and "6건" in facts["losses"] and "85.7%" in facts["losses"] and "−100" in facts["worst"].replace("-", "−")
    assert facts["money"].startswith("진 거래의 손실 합계") and "360" in facts["money"]
    # the stacked bar: every type that happened is written in the label, and the legend lists ALL types (also the zero ones) in the rule order
    assert c["bar"].startswith("진 거래의 유형: ") and "강제청산 1건" in c["bar"] and "손절보다 크게 잃음 2건" in c["bar"] and "오래 끌다" not in c["bar"]
    assert [x["type"] for x in c["legend"]] == list(LV.TYPE_IDS)
    zero = next(x for x in c["legend"] if x["type"] == "slow")
    assert "0건" in zero["t"] and "평균 —" in zero["t"]
    # the plain explanation of each type is printed (under the disclosure), in the rule order, with its number
    assert [w["type"] for w in c["words"]] == list(LV.TYPE_IDS)
    for w, t in zip(c["words"], d["losses"]["types"]):
        assert t["ko"] in w["t"] and t["explain_ko"] in w["t"]
    assert c["words"][0]["t"].startswith("1. 강제청산")
    assert [t["bd"] for t in c["tables"]] == ["coin", "side", "lev", "hour", "week"]
    coin = c["tables"][0]["rows"]
    assert coin[0].startswith("ETH") and "4건" in coin[0] and "67%" in coin[0]
    assert any("30배" in r for r in c["tables"][2]["rows"]) and any(r.startswith("롱") for r in c["tables"][1]["rows"])
    assert any("평일" in r for r in c["tables"][4]["rows"]) or any("주말" in r for r in c["tables"][4]["rows"])
    assert "연속으로 진 최다: 2번" in c["streak"][0] and "진 신호 4개 중 여러 계좌가 한꺼번에 진 신호 1개" in c["streak"][1]
    assert any("계좌 3개가 함께 진 것" in s for s in c["streak"]) and any("50%" in s for s in c["streak"])
    assert len(c["worst"]) == len(k["worst"]) == 6
    first = c["worst"][0]
    w0 = k["worst"][0]
    assert first["href"] == f"#/replay?acct={w0['account']}&at={w0['at']}" and "다시보기" in first["t"] and first["type"] == w0["type_id"]
    assert all(w["href"] and w["href"].startswith("#/replay?acct=") and "&at=" in w["href"] for w in c["worst"])


def test_ten_biggest_and_a_big_sample_has_no_small_flag(tmp_path):
    d = doc(many=True)
    o = run(tmp_path, d)
    c = card(o, "fq")
    assert len(c["worst"]) == 10 and "표본 적음" not in " ".join(c["pills"]) and "진 거래 46건" in c["t"]
    assert "표본 적음" in " ".join(card(o, "ld")["pills"])                                         # the control has one loss only


def test_small_sample_reads_as_such(tmp_path):
    o = run(tmp_path, doc())
    for role in ("fq", "ld"):
        assert "표본 적음" in " ".join(card(o, role)["pills"])


# ---------------------------------------------------------------- (b) the picker
def test_picker_pooled_and_every_kind(tmp_path):
    o = run(tmp_path, doc(), SELS, clicks=['.seg button[data-id="all"]'])
    assert [c["id"] for c in o["cards"]] == ["lv-all"] and [x["t"] for x in o["sel"]["pressed"]] == ["모든 종류 합계"]
    assert "모두 합침" in " ".join(o["cards"][0]["pills"])
    o = run(tmp_path, doc(), SELS, clicks=['.seg button[data-id="each"]'])
    assert [c["id"] for c in o["cards"]] == ["lv-fq", "lv-nv", "lv-ld"] or sorted(c["id"] for c in o["cards"]) == ["lv-fq", "lv-ld", "lv-nv"]
    o = run(tmp_path, doc(), SELS, local={"cl-losses-pick": '"each"'})                              # the choice is remembered per viewer
    assert len(o["cards"]) == 3
    o = run(tmp_path, doc(), SELS, local={"cl-losses-pick": '"nonsense"'})                          # ... and a bad value falls back to the default
    assert [c["id"] for c in o["cards"]] == ["lv-fq", "lv-ld"]


def test_without_the_core_two_the_first_two_kinds_are_shown(tmp_path):
    L = losses_block()
    L["kinds"] = [k for k in L["kinds"] if k["role"] not in ("fq", "ld")]
    o = run(tmp_path, doc(losses=L))
    assert [c["id"] for c in o["cards"]] == ["lv-nv"]


# ---------------------------------------------------------------- (c) the block is not there
def test_losses_absent_says_preparing_and_the_rule_box_stays(tmp_path):
    o = run(tmp_path, doc(losses=None), SELS)
    assert "준비 중" in o["text"] and "손실 해부 기록은 아직 없습니다" in o["text"] and len(o["sel"]["rules"]) == 4 and o["cards"] == []
    no_junk(o["text"])
    o = run(tmp_path, doc(losses=None, lineup=False), SELS)
    assert "새 리그 전용" in o["text"] and o["cards"] == []
    o = run(tmp_path, doc(losses=None, accounts=False), SELS)
    assert "준비 중" in o["text"] and o["cards"] == []
    o = run(tmp_path, None, SELS)
    assert "준비 중" in o["text"]
    for junk in ({"kinds": "x"}, {"kinds": []}, [], "x", {"kinds": [None, 5]}):
        o = run(tmp_path, doc(losses=junk), SELS)
        assert o["cards"] == [] and "준비 중" in o["text"]
        no_junk(o["text"])


# ---------------------------------------------------------------- (d) nothing is made up
def test_null_numbers_read_as_a_dash_never_zero(tmp_path):
    L = losses_block()
    for k in L["kinds"]:
        for key in ("loss_share", "mean_loss_roe", "worst_loss_roe", "loss_money", "accounts", "trades"):
            k[key] = None
        k["streak"], k["cluster"] = {"max": None, "account": None}, {"signals": None, "multi": None, "biggest": None, "multi_share": None}
        for t in k["types"]:
            t["share"] = t["mean_roe"] = None
        for r in k["by_coin"] + k["by_side"] + k["by_lev"]:
            r["share"] = r["mean_roe"] = None
        for w in k["worst"]:
            w["roe"] = w["at"] = w["leverage"] = w["entry_time"] = None
    o = run(tmp_path, doc(losses=L))
    no_junk(o["text"])
    c = card(o, "fq")
    facts = {f["k"]: f["t"] for f in c["facts"]}
    assert facts["trades"].endswith("—") or "—" in facts["trades"]
    assert "—" in facts["mean"] and "—" in facts["worst"] and "—" in facts["money"] and "0건" not in facts["trades"]
    assert "연속으로 진 최다: —" in c["streak"][0] and "같은 신호에 함께 진 기록: —" in c["streak"][1]
    assert all(w["href"] is None for w in c["worst"])                                              # no entry time -> no replay link


def test_an_empty_kind_says_so(tmp_path):
    rows = [RT.row("a-fq", "fq"), RT.row("a-ld", "ld")]
    L = json.loads(json.dumps(LV.loss_views({}, rows, RT.LU, False), allow_nan=False))
    o = run(tmp_path, doc(losses=L))
    no_junk(o["text"])
    c = card(o, "fq")
    assert "아직 진 거래가 없습니다" in c["t"] and c["worst"] == [] and "표본 적음" in " ".join(c["pills"])
    assert "아직 진 거래가 없습니다" in o["text"]


# ---------------------------------------------------------------- (f) DeepSeek
def test_deepseek_note_both_ways_and_no_hidden_money(tmp_path):
    o = run(tmp_path, doc(ds=False))
    assert "이 숫자는 딥시크를 뺀 후보만으로 계산했습니다" in o["text"] and "딥시크 계좌도 들어 있습니다" not in o["text"] and "700" not in o["text"]
    o = run(tmp_path, doc(ds=True))
    assert "이 숫자에는 딥시크 계좌도 들어 있습니다" in o["text"] and "딥시크를 뺀 후보만으로" not in o["text"]


# ---------------------------------------------------------------- the static rules, the registration
def test_the_type_words_equal_the_servers():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    # TYPES_DEFAULT is the fallback of the screen: same ids, words and order as candleague/lossview.LOSS_TYPES
    src = open(os.path.join(STATIC, "js", "screens", "losses.js"), encoding="utf-8").read()
    got = re.findall(r'\{id: "(\w+)", ko: "([^"]+)", explain_ko: "([^"]+)"\}', src)
    assert got == [tuple(t) for t in LV.LOSS_TYPES] and f"MIN_LOSSES = {LV.MIN_LOSSES};" in src


def test_the_files_and_the_static_rules():
    src = open(os.path.join(STATIC, "js", "screens", "losses.js"), encoding="utf-8").read()
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "document.write", "new Function", "eval(", "binance.com"):
        assert bad not in src, bad
    assert 'export const css = ["scr/kinds.css", "scr/losses.css"]' in src
    from candleague import dash as D
    assert "js/screens/losses.js" in D._static_files() and "scr/losses.css" in D._static_files()
    css = open(os.path.join(STATIC, "scr", "losses.css"), encoding="utf-8").read()
    for text in (src, css):
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsl\(", text.replace("#/replay", "").replace("// #/losses", ""))
    for decl in re.findall(r"(?<![\w-])font(?:-size)?:[^;}]*", css):
        assert "var(--t-" in decl, decl
    assert not re.search(r"\$\s?5,?000|5000", src + css)
    for sel in re.findall(r"^([^\s{@/][^{]*)\{", css, re.M):
        for part in sel.split(","):
            assert part.strip().startswith(".scr.kd "), part


def test_registration_in_the_menu_titles_find_and_glance():
    app = open(os.path.join(STATIC, "js", "app.js"), encoding="utf-8").read()
    menu = re.findall(r'\{id: "(\w+)", ko: "([^"]+)", group: "(\w+)"', re.search(r"const MENU = \[(.*?)\];", app, re.S).group(1))
    assert ("losses", "손실 해부", "study") in menu and [m[0] for m in menu].index("losses") == [m[0] for m in menu].index("risk") + 1
    assert 'losses: "losses"' in re.search(r"const SCREENS = \{([^}]*)\}", app).group(0)
    titles = re.search(r"const MENU_TITLE = \{(.*?)\};\s*const SCREENS", app, re.S).group(1)
    assert re.search(r"\blosses: \"손실 해부 ", titles)
    find = open(os.path.join(STATIC, "js", "find.js"), encoding="utf-8").read()
    assert re.search(r"\blosses: \"손실 해부 ", find)
    glance = open(os.path.join(STATIC, "js", "screens", "glance.js"), encoding="utf-8").read()
    assert '["losses", "손실 해부", s(x.losses, "headline_ko")]' in glance
