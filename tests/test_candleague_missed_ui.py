"""candleague 놓친 신호 screen (js/screens/missed.js, scr/missed.css) and its menu / 찾기 / 한눈 지도 entries.

Mounted for real under node on the DOM stand-in of test_candleague_rank_ui with hand-made snapshots whose account rows carry ``counts``
{offered, entered, skipped, rejected, closed}:
  (a) the core two by default, 전체 on the picker: per kind signals / entered / skipped / rejected with their shares; the reasons are explained but never split
      (이유별 건수는 기록하지 않습니다); (b) the picks that rarely enter (>= 20 offered, lowest share first, 10 rows); (c) 표본 적음; (d) missing numbers read "—";
  (e) an older snapshot: 새 리그 전용 / 준비 중; (f) the static rules and the registration."""

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

import test_candleague_rank_ui as RANK  # noqa: E402  (its DOM stand-in, read only)

STATIC = os.path.join(ROOT, "candleague", "static")
BAD = ("NaN", "undefined", "null", "Infinity", "[object")
NAMES = {"fq": "빠른 손절", "ld": "원래 방식", "fq50": "빠른 손절 50배"}


def acct(pick, role, offered, entered, skipped, rejected, name="strat", tf="1h"):
    return {"id": pick + "-" + role, "role": role, "kind": "core", "pick": pick, "name": name, "tf": tf, "wallet": 1000.0, "max_dd": 0.1, "trades": entered, "wins": 1,
            "open": None, "counts": {"offered": offered, "entered": entered, "skipped": skipped, "rejected": rejected, "closed": entered}}


def doc(accounts=None, lineup=True, roles=("fq", "ld", "fq50")):
    d = {"generated_ms": 1, "done_ms": 1, "start_ms": 1, "judge": {}, "ds_money": False, "equity0": 1000, "watch": {"checkpoints": [], "pools": {}},
         "accounts": accounts if accounts is not None else default_accounts()}
    if lineup:
        d["lineup"] = [{"role": r, "suffix": "-" + r, "label_ko": "연구 · " + NAMES[r], "short_ko": NAMES[r], "accounts": 12} for r in roles]
    return d


def default_accounts():
    rows = [acct("p1", "fq", 100, 40, 50, 10), acct("p2", "fq", 100, 20, 60, 20), acct("p1", "ld", 80, 40, 30, 10), acct("p1", "fq50", 50, 25, 20, 5)]
    return rows


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
const M = await import(`file://${S}/js/screens/missed.js`);
const el = document.createElement("div");
el.dataset.screen = "missed";
document.body.appendChild(el);
const ctx = {params: {name: "missed", arg: null, query: {}}, alive: () => true, signal: null,
  api: async (p) => (await globalThis.fetch(p)).json(), meta: () => LK.getMeta(),
  onLeague: (fn) => { if (doc) fn(doc); }, onLive: () => () => {}, onPositions: () => () => {},
  every: () => {}, css: async () => null, wide() {}, setTitle() {}, setQuery() {},
  href: (n, a) => `#/${n}${a ? "/" + a : ""}`};
await M.mount(el, ctx);
for (let i = 0; i < 4; i++) await new Promise((r) => setTimeout(r, 10));
const out = {text: txt(el), css: M.css, headline: M.headline(doc), kinds: [], picks: []};

const wait = async () => { for (let i = 0; i < 4; i++) await new Promise((r) => setTimeout(r, 10)); };
for (const c of cfg.clicks || []) { const b = el.querySelector(c); if (!b) throw new Error("no " + c); b.fire("click"); await wait(); }
out.text = txt(el);
for (const tr of el.querySelectorAll('table[data-tbl="kinds"] tbody tr')) out.kinds.push({role: tr.dataset.role, offered: txt(tr.querySelector('td[data-c="offered"]')), cells: tr.querySelectorAll("td").map(txt)});
for (const tr of el.querySelectorAll('table[data-tbl="picks"] tbody tr')) out.picks.push({pick: tr.dataset.pick, offered: txt(tr.querySelectorAll("td")[1]), rate: txt(tr.querySelector('td[data-c="rate"]'))});
console.log(JSON.stringify(out));
process.exit(0);
"""


def run(tmp_path, d, clicks=None, local=None):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    (tmp_path / "shim.mjs").write_text(RANK.SHIM)
    (tmp_path / "run.mjs").write_text(RUNNER)
    (tmp_path / "cfg.json").write_text(json.dumps({"static": STATIC, "routes": {}, "local": local or {}, "doc": d, "clicks": clicks or []}, ensure_ascii=False))
    r = subprocess.run([node, str(tmp_path / "run.mjs"), str(tmp_path / "cfg.json")], capture_output=True, text=True, timeout=120, cwd=str(tmp_path))
    assert r.returncode == 0, (r.stdout[-600:], r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def no_junk(text):
    for bad in BAD:
        assert bad not in text, bad


def kinds(o):
    return {r["role"]: r for r in o["kinds"]}


# ---------------------------------------------------------------- (a) per kind
def test_core_two_by_default_with_counts_and_shares(tmp_path):
    o = run(tmp_path, doc())
    no_junk(o["text"])
    assert o["css"] == ["scr/kinds.css", "scr/missed.css"]
    k = kinds(o)
    assert set(k) == {"fq", "ld"}                                       # 핵심 2개
    assert k["fq"]["offered"] == "200" and k["fq"]["cells"][2].startswith("60") and "30.0%" in k["fq"]["cells"][2]       # 40 + 20 entered of 200
    assert "55.0%" in k["fq"]["cells"][3] and "15.0%" in k["fq"]["cells"][4]                                                # 110 skipped, 30 rejected
    assert "계좌 2개" in k["fq"]["cells"][0] and "표본 적음" not in k["fq"]["cells"][0]
    assert k["ld"]["offered"] == "80" and "50.0%" in k["ld"]["cells"][2]
    for need in ("이유별 건수는 기록하지 않습니다", "20배는 쓰지 않습니다", "15% 한도", "강제청산 거리 검사"):
        assert need in o["text"]
    assert o["headline"].startswith("빠른 손절 · 원래 방식에 들어온 신호 280개 중 진입")


def test_the_picker_shows_all_kinds_and_remembers(tmp_path):
    o = run(tmp_path, doc(), clicks=['.seg button[data-id="all"]'])
    assert set(kinds(o)) == {"fq", "ld", "fq50"}
    o = run(tmp_path, doc(), local={"cl-missed-pick": '"all"'})
    assert set(kinds(o)) == {"fq", "ld", "fq50"}
    o = run(tmp_path, doc(roles=("fq50",), accounts=[acct("p1", "fq50", 50, 25, 20, 5)]))   # neither core kind: the first two kinds
    assert set(kinds(o)) == {"fq50"}


# ---------------------------------------------------------------- (b) the rare picks
def test_rare_picks_lowest_share_first_needs_20_offered_and_top_10(tmp_path):
    rows = [acct(f"q{i:02d}", "fq", 100, 10 + i, 80 - i, 10) for i in range(14)]          # shares 10% .. 23%
    rows += [acct("few", "fq", 19, 0, 19, 0, name="few")]                                  # under 20 offered: left out
    rows += [acct("p1", "ld", 100, 90, 5, 5)]                                              # ld adds to a pick only when it is the same pick
    o = run(tmp_path, doc(accounts=rows))
    ps = o["picks"]
    assert len(ps) == 10 and [p["pick"] for p in ps] == [f"q{i:02d}" for i in range(10)] and all(p["pick"] != "few" for p in ps)
    assert ps[0]["rate"] == "10.0%" and ps[9]["rate"] == "19.0%"
    # the same pick across the shown kinds is summed
    o = run(tmp_path, doc(accounts=[acct("a", "fq", 20, 2, 18, 0), acct("a", "ld", 20, 8, 12, 0)]))
    assert o["picks"][0]["pick"] == "a" and o["picks"][0]["rate"] == "25.0%" and o["picks"][0]["offered"] == "40"
    o = run(tmp_path, doc(accounts=[acct("a", "fq", 19, 2, 17, 0)]))
    assert o["picks"] == [] and "신호가 20개 이상 들어온 매매법이 아직 없습니다" in o["text"]


# ---------------------------------------------------------------- (c) small samples
def test_small_samples_say_so(tmp_path):
    o = run(tmp_path, doc(accounts=[acct("p1", "fq", 29, 10, 10, 9), acct("p1", "ld", 30, 10, 10, 10)]))
    k = kinds(o)
    assert "표본 적음" in k["fq"]["cells"][0] and "표본 적음" not in k["ld"]["cells"][0]


# ---------------------------------------------------------------- (d) missing numbers
def test_missing_numbers_read_dash_and_zero_offered_has_no_share(tmp_path):
    a = acct("p1", "fq", 0, 0, 0, 0)
    o = run(tmp_path, doc(accounts=[a, acct("p2", "ld", 40, 10, 20, 10)]))
    no_junk(o["text"])
    assert kinds(o)["fq"]["offered"] == "0" and "—" in kinds(o)["fq"]["cells"][2] and "0.0%" not in kinds(o)["fq"]["cells"][2]
    broken = acct("p1", "fq", 40, 10, 20, 10)
    broken["counts"]["rejected"] = None                                                     # one number missing: the account is left out, not counted as 0
    o = run(tmp_path, doc(accounts=[broken, acct("p2", "ld", 40, 10, 20, 10)]))
    no_junk(o["text"])
    assert set(kinds(o)) == {"ld"}


# ---------------------------------------------------------------- (e) older snapshots
def test_older_snapshots(tmp_path):
    o = run(tmp_path, doc(lineup=False))
    assert "새 리그 전용" in o["text"] and not o["kinds"]
    no_counts = [{k: v for k, v in a.items() if k != "counts"} for a in default_accounts()]
    o = run(tmp_path, doc(accounts=no_counts))
    assert "준비 중" in o["text"] and not o["kinds"] and o["headline"] is None
    o = run(tmp_path, None)
    assert "준비 중" in o["text"] and o["headline"] is None


# ---------------------------------------------------------------- (f) static rules and registration
def test_static_rules_and_registration():
    src = open(os.path.join(STATIC, "js", "screens", "missed.js"), encoding="utf-8").read()
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "document.write", "new Function", "eval(", "binance.com"):
        assert bad not in src, bad
    assert 'export const css = ["scr/kinds.css", "scr/missed.css"]' in src
    from candleague import dash as D
    assert "js/screens/missed.js" in D._static_files() and "scr/missed.css" in D._static_files()
    css = open(os.path.join(STATIC, "scr", "missed.css"), encoding="utf-8").read()
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsl\(", css)
    for decl in re.findall(r"(?<![\w-])font(?:-size)?:[^;}]*", css):
        assert "var(--t-" in decl, decl
    for sel in re.findall(r"^([^\s{@/][^{]*)\{", css, re.M):
        for part in sel.split(","):
            assert part.strip().startswith(".scr.kd "), part
    app = open(os.path.join(STATIC, "js", "app.js"), encoding="utf-8").read()
    assert '{id: "missed", ko: "놓친 신호", group: "study"}' in app and 'missed: "missed"' in app
    assert "missed:" in open(os.path.join(STATIC, "js", "find.js"), encoding="utf-8").read()
    glance = open(os.path.join(STATIC, "js", "screens", "glance.js"), encoding="utf-8").read()
    assert '"leverage", "레버리지 비교"' in glance and '"missed", "놓친 신호"' in glance and "ORDER = [" in glance and '"leverage"' not in glance.split("const ORDER")[1].split("];")[0]
