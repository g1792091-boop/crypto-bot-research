"""candleague 레버리지 비교 screen (js/screens/leverage.js, scr/leverage.css) and its menu / 찾기 / 한눈 지도 entries.

Mounted for real under node on the DOM stand-in of test_candleague_rank_ui (text nodes only) with hand-made snapshots:
  (a) both families present: three columns each, every number, the plain difference sentences with their signs, the disclosure on why 40/50x change the size;
  (b) one family missing: 준비 중 in its columns, no sentence; (c) small samples: 표본 적음; (d) missing numbers read "—", never 0;
  (e) an older snapshot (no lineup / none of the kinds): 새 리그 전용 / 준비 중; (f) the static rules and the registration."""

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
NAMES = {"fq": "빠른 손절", "fq40": "빠른 손절 40배", "fq50": "빠른 손절 50배", "ld": "원래 방식", "ld40": "원래 방식 40배", "ld50": "원래 방식 50배"}


def kind(role, trades=60, mean=0.02, ret=0.10, liq=0, win=0.5, accounts=12):
    return {"role": role, "suffix": "-" + role, "label_ko": NAMES[role], "short_ko": NAMES[role], "accounts": accounts, "trades": trades, "win_rate": win,
            "mean_roe": mean, "wallet_return_pct": ret, "reasons": {"SL": 5, "LOCK": 1, "RULE": 0, "TP": 2, "LIQ": liq}}


def doc(roles=("fq", "fq40", "fq50", "ld", "ld40", "ld50"), over=None, lineup=True, worst=None, dd=0.10, lev=None):
    over = over or {}
    d = {"generated_ms": 1, "done_ms": 1, "start_ms": 1, "judge": {}, "ds_money": False, "equity0": 1000, "watch": {"checkpoints": [], "pools": {}},
         "accounts": [{"id": f"p1-{r}", "role": r, "kind": "core", "pick": "p1", "max_dd": dd, "wallet": 1100.0, "trades": 3, "wins": 2, "open": None} for r in roles],
         "kinds": [], "losses": {"kinds": []}, "risk": {"kinds": []}}
    base = {"fq": (0.02, 0.10, 0), "fq40": (0.03, 0.14, 1), "fq50": (0.04, 0.20, 3), "ld": (0.01, 0.05, 0), "ld40": (0.00, 0.02, 2), "ld50": (-0.01, -0.05, 4)}
    wl = {"fq": -0.30, "fq40": -0.40, "fq50": -0.55, "ld": -0.30, "ld40": -0.30, "ld50": -0.20}
    for r in roles:
        m, rt, lq = base[r]
        k = kind(r, mean=m, ret=rt, liq=lq)
        k.update(over.get(r, {}))
        d["kinds"].append(k)
        d["losses"]["kinds"].append({"role": r, "pooled": False, "worst_loss_roe": (worst or {}).get(r, wl[r])})
        d["risk"]["kinds"].append({"role": r, "pooled": False, "now": {"open": 2, "lev_mean": (lev or {}).get(r)}})
    if lineup:
        d["lineup"] = [{"role": r, "suffix": "-" + r, "label_ko": "연구 · " + NAMES[r], "short_ko": NAMES[r], "accounts": 12} for r in roles]
    return d


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
const M = await import(`file://${S}/js/screens/leverage.js`);
const el = document.createElement("div");
el.dataset.screen = "leverage";
document.body.appendChild(el);
const ctx = {params: {name: "leverage", arg: null, query: {}}, alive: () => true, signal: null,
  api: async (p) => (await globalThis.fetch(p)).json(), meta: () => LK.getMeta(),
  onLeague: (fn) => { if (doc) fn(doc); }, onLive: () => () => {}, onPositions: () => () => {},
  every: () => {}, css: async () => null, wide() {}, setTitle() {}, setQuery() {},
  href: (n, a) => `#/${n}${a ? "/" + a : ""}`};
await M.mount(el, ctx);
for (let i = 0; i < 4; i++) await new Promise((r) => setTimeout(r, 10));
const out = {text: txt(el), css: M.css, headline: M.headline(doc), fams: {}, diffs: {}};
for (const c of el.querySelectorAll("section.lg-fam")) {
  out.fams[c.attrs.get("id")] = {cols: c.querySelectorAll(".lg-col").map((n) => ({role: n.dataset.role, state: n.dataset.state, t: txt(n),
    facts: Object.fromEntries(n.querySelectorAll("div[data-fact]").map((f) => [f.dataset.fact, txt(f)]))}))};
}
for (const p of el.querySelectorAll("p.lg-diff")) out.diffs[p.dataset.diff] = txt(p);
console.log(JSON.stringify(out));
process.exit(0);
"""


def run(tmp_path, d):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    (tmp_path / "shim.mjs").write_text(RANK.SHIM)
    (tmp_path / "run.mjs").write_text(RUNNER)
    (tmp_path / "cfg.json").write_text(json.dumps({"static": STATIC, "routes": {}, "local": {}, "doc": d}, ensure_ascii=False))
    r = subprocess.run([node, str(tmp_path / "run.mjs"), str(tmp_path / "cfg.json")], capture_output=True, text=True, timeout=120, cwd=str(tmp_path))
    assert r.returncode == 0, (r.stdout[-600:], r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def no_junk(text):
    for bad in BAD:
        assert bad not in text, bad


def col(o, fam, role):
    return next(c for c in o["fams"][f"lg-{fam}"]["cols"] if c["role"] == role)


# ---------------------------------------------------------------- (a) both families
def test_both_families_side_by_side_with_numbers_and_signed_sentences(tmp_path):
    o = run(tmp_path, doc(lev={"fq50": 50, "fq": 31.5}))
    no_junk(o["text"])
    assert o["css"] == ["scr/kinds.css", "scr/leverage.css"]
    assert list(o["fams"]) == ["lg-fq", "lg-ld"]
    assert [c["role"] for c in o["fams"]["lg-fq"]["cols"]] == ["fq", "fq40", "fq50"] and [c["role"] for c in o["fams"]["lg-ld"]["cols"]] == ["ld", "ld40", "ld50"]
    c = col(o, "fq", "fq50")
    assert c["facts"]["accounts"].endswith("12개") and c["facts"]["trades"].endswith("60건") and c["facts"]["win"].endswith("50.0%")
    assert c["facts"]["mean"].endswith("+4.0%") and c["facts"]["ret"].endswith("+20.0%") and c["facts"]["worst"].endswith("−55.0%")
    assert c["facts"]["dd"].endswith("10.0%") and c["facts"]["liq"].endswith("3번") and c["facts"]["lev"].endswith("50.0배")
    assert col(o, "fq", "fq")["facts"]["lev"].endswith("31.5배") and col(o, "fq", "fq40")["facts"]["lev"].endswith("—")
    # the plain sentences: only differences, signs written
    assert o["diffs"]["fq50"].startswith("50배 계좌는 같은 신호에서 거래당 평균 +2.0%p 더 벌었고, 가장 큰 손실은 −25.0%p 더 깊었습니다.")
    assert "총 수익률은 +10.0%p 높았습니다, 강제청산은 3번 더 많았습니다." in o["diffs"]["fq50"]
    assert o["diffs"]["fq40"].startswith("40배 계좌는 같은 신호에서 거래당 평균 +1.0%p 더 벌었고, 가장 큰 손실은 −10.0%p 더 깊었습니다.")
    # a worse mean and a shallower worst loss read the other way round
    assert o["diffs"]["ld50"].startswith("50배 계좌는 같은 신호에서 거래당 평균 −2.0%p 덜 벌었고, 가장 큰 손실은 +10.0%p 덜 깊었습니다.")
    assert "강제청산은 4번 더 많았습니다" in o["diffs"]["ld50"] and "총 수익률은 −10.0%p 낮았습니다" in o["diffs"]["ld50"]
    for t in o["diffs"].values():                                      # never a verdict
        assert not re.search(r"(낫|좋|나쁘|추천|권합|이득|우위)", t), t
    for need in ("30배: 증거금 30% × 30배 = 지갑의 약 9배", "50배: 증거금 50% × 50배 = 지갑의 약 25배", "우위의 증거가 아닙니다", "위험이 얼마나 커지는지 비교"):
        assert need in o["text"]
    assert o["headline"] and o["headline"].startswith("빠른 손절 계열: 50배 계좌는")


def test_equal_numbers_read_as_no_difference(tmp_path):
    o = run(tmp_path, doc(over={"fq50": {"mean_roe": 0.02, "wallet_return_pct": 0.10, "reasons": {"LIQ": 0}}}, worst={"fq50": -0.30}))
    assert "거래당 평균은 차이가 없었고, 가장 큰 손실은 차이가 없었습니다." in o["diffs"]["fq50"]
    assert "총 수익률은 차이가 없었습니다" in o["diffs"]["fq50"] and "강제청산 횟수는 같았습니다" in o["diffs"]["fq50"]


# ---------------------------------------------------------------- (b) one family missing
def test_one_family_missing_reads_in_preparation(tmp_path):
    o = run(tmp_path, doc(roles=("fq", "fq40", "fq50", "ld")))
    no_junk(o["text"])
    assert col(o, "ld", "ld40")["state"] == "prep" and col(o, "ld", "ld50")["state"] == "prep" and "준비 중" in col(o, "ld", "ld50")["t"]
    assert col(o, "ld", "ld")["state"] == "ok"
    assert "fq50" in o["diffs"] and "ld40" not in o["diffs"] and "ld50" not in o["diffs"]
    assert "비교할 숫자가 아직 모자랍니다" in o["fams"]["lg-ld"]["cols"][0]["t"] + o["text"]


# ---------------------------------------------------------------- (c) small samples
def test_small_samples_say_so_and_the_sentence_hedges(tmp_path):
    o = run(tmp_path, doc(over={"fq50": {"trades": 12}}))
    assert "표본 적음" in col(o, "fq", "fq50")["t"] and "표본 적음" not in col(o, "fq", "fq40")["t"]
    assert o["diffs"]["fq50"].endswith("거래가 적어 우연일 수 있습니다 (표본 적음).") and "표본 적음" not in o["diffs"]["fq40"]
    o = run(tmp_path, doc(over={"fq": {"trades": 29}}))
    assert "표본 적음" in col(o, "fq", "fq")["t"]
    o = run(tmp_path, doc(over={"fq": {"trades": 30}}))
    assert "표본 적음" not in col(o, "fq", "fq")["t"]


# ---------------------------------------------------------------- (d) missing numbers
def test_missing_numbers_read_dash_never_zero(tmp_path):
    d = doc(over={"fq50": {"mean_roe": None, "win_rate": None, "wallet_return_pct": None}}, worst={"fq50": None}, dd=None)
    d["risk"] = {}                                                      # no leverage numbers at all
    o = run(tmp_path, d)
    no_junk(o["text"])
    c = col(o, "fq", "fq50")
    for k in ("win", "mean", "ret", "worst", "dd", "lev"):
        assert c["facts"][k].endswith("—"), (k, c["facts"][k])
    assert "fq50" not in o["diffs"]                                     # no sentence without the means
    # the worst loss alone missing: the sentence says there is nothing to compare for it
    d = doc(worst={"fq50": None})
    o = run(tmp_path, d)
    assert "가장 큰 손실은 비교할 숫자가 없습니다" in o["diffs"]["fq50"]


# ---------------------------------------------------------------- (e) older snapshots
def test_older_snapshots(tmp_path):
    o = run(tmp_path, doc(lineup=False))
    assert "새 리그 전용" in o["text"] and not o["fams"]
    d = doc(roles=("fq", "ld"))
    o = run(tmp_path, d)
    assert "준비 중" in o["text"] and "40배 · 50배 계좌가 아직 기록에 없습니다" in o["text"] and not o["fams"] and o["headline"] is None
    o = run(tmp_path, None)
    assert "준비 중" in o["text"] and o["headline"] is None
    d = doc(); del d["losses"]; del d["risk"]                           # the other blocks absent: the rest still shows
    o = run(tmp_path, d)
    no_junk(o["text"])
    assert col(o, "fq", "fq50")["facts"]["worst"].endswith("—") and col(o, "fq", "fq50")["facts"]["trades"].endswith("60건")


# ---------------------------------------------------------------- (f) static rules and registration
def test_static_rules_and_registration():
    src = open(os.path.join(STATIC, "js", "screens", "leverage.js"), encoding="utf-8").read()
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "document.write", "new Function", "eval(", "binance.com"):
        assert bad not in src, bad
    assert 'export const css = ["scr/kinds.css", "scr/leverage.css"]' in src
    from candleague import dash as D
    assert "js/screens/leverage.js" in D._static_files() and "scr/leverage.css" in D._static_files()
    css = open(os.path.join(STATIC, "scr", "leverage.css"), encoding="utf-8").read()
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsl\(", css)
    for decl in re.findall(r"(?<![\w-])font(?:-size)?:[^;}]*", css):
        assert "var(--t-" in decl, decl
    for sel in re.findall(r"^([^\s{@/][^{]*)\{", css, re.M):
        for part in sel.split(","):
            assert part.strip().startswith(".scr.kd "), part
    app = open(os.path.join(STATIC, "js", "app.js"), encoding="utf-8").read()
    assert '{id: "leverage", ko: "레버리지 비교", group: "study"}' in app and 'leverage: "leverage"' in app and "\n  leverage: \"레버리지 비교 (" in app
    assert app.index('id: "losses"') < app.index('id: "leverage"') < app.index('id: "missed"') < app.index('id: "weekly"')
    assert "leverage:" in open(os.path.join(STATIC, "js", "find.js"), encoding="utf-8").read()
