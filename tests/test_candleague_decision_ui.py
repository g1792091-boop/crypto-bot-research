"""candleague 판정 screen (js/screens/decision.js, css scr/kinds.css) and its menu / 찾기 entries.

The screen is mounted for real under node on the DOM stand-in of test_candleague_rank_ui (text nodes only, like the browser's) with
hand-made snapshots whose ``decision`` follows candleague.summary.decision_views, and the tests read what reached the page:
  (a) full data (day 15, a preview): the rule box first (seven rules), the one-sentence answer with the bar to day 28, the four deciding rows
      under "이것으로만 판정합니다 (4개)" and the reference rows under "참고용 (판정에 쓰지 않음)", the numbers (쌍, 차이, 구간, p) in short form;
  (b) the verdict words with their colours: 대기 / 표본 부족 (day 15), 통과 / 실패 (day 30), 탐색 (a reference row, no colour tone);
  (c) the card view; (d) ``decision`` absent: a friendly note and the rule box still there (new league, old league, no snapshot);
  (e) null numbers read "—", never 0, NaN or null; (f) the start wallet says $1,000 and never $5,000; (g) DeepSeek note both ways;
  (h) a block made by the real summary.decision_views from synthetic trades.
Plus the static rules (text only, tokens only), the menu entry right after 짝 비교, and 찾기."""

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
from candleague import summary as SM  # noqa: E402

STATIC = os.path.join(ROOT, "candleague", "static")
DAY = 86_400_000
T0 = (1_791_000_000_000 // DAY) * DAY
NOW = T0 + 15 * DAY
BAD = ("NaN", "undefined", "null", "Infinity")


# ---------------------------------------------------------------- hand-made snapshots
NAMES = {"-fq": ("빠른 손절", "메인 · 구조 확실히 무너지면 빠른 손절 (실전 후보)", "main"), "-nv": ("자체 판단", "메인 · 매매법 자체 판단으로 청산", "main"),
         "-sw": ("스위칭", "메인 · 반대 신호 나오면 스위칭", "main"), "-tg": ("손절 좁힘", "메인 · 구조 무너지면 손절 좁힘", "main"),
         "-ld": ("계단", "대조 · 계단 · 손절 최대 2 ATR", "control"), "-ldt": ("대조 추세 필터", "필터 · 대조에 BTC 4시간 추세 방향만", "research"),
         "-ldv": ("대조 변동성 필터", "필터 · 대조에 변동성 보통일 때만", "research"), "-fqt": ("빠른 손절 추세 필터", "필터 · 빠른 손절에 BTC 4시간 추세 방향만", "research")}
VKO = {"pass": "통과", "fail": "실패", "wait": "대기", "few": "표본 부족", "explore": "탐색"}


def _row(test, suffix, vs, verdict, primary, n, mean, lo, hi, p, ph, h1, h2, reason, **kw):
    short, label, group = NAMES[suffix]
    r = {"role": suffix[1:], "suffix": suffix, "label_ko": label, "short_ko": short, "group": group, "test": test, "primary": primary, "vs_suffix": vs,
         "vs_ko": NAMES.get(vs, (vs,))[0], "n": n, "n_days": 12, "mean_diff": mean, "ci_lo": lo, "ci_hi": hi, "p_one_sided": p, "p_holm": ph if primary else None,
         "half1": h1, "half2": h2, "same_sign_halves": bool(h1 and h2 and h1 > 0 and h2 > 0), "verdict": verdict, "verdict_ko": VKO[verdict], "reason_ko": reason}
    if test == "filter_kept_vs_dropped":
        r.update(n_kept=kw.get("n_kept", n), n_dropped=kw.get("n_dropped", n * 3), mean_kept=0.03, mean_dropped=0.01)
    return r


def _decision(phase="observe", days=15, verdicts=("wait", "wait", "few", "few"), summary=None, ds_in=False) -> dict:
    """Four primary rows (the quick stop vs the control, the quick stop and the control vs their coin twins, the -ldt gate) and five reference rows."""
    v = list(verdicts)
    wait = "미리보기입니다: 28일째에 한 번만 판정합니다 (지금 15일째, 평균 차이 +1.2%p)"
    rows = [
        _row("main_vs_control", "-fq", "-ld", v[0], True, 412, 0.0123, -0.0031, 0.0271, 0.0123, 0.031, 0.02, 0.0046, wait if v[0] == "wait" else "통과: 412쌍, 평균 차이 +1.2%p"),
        _row("vs_coin", "-fq", "-fqc", v[1], True, 380, 0.0218, 0.0102, 0.0331, 0.0001, 0.0004, 0.02, 0.023, wait if v[1] == "wait" else "실패: 앞 절반(+2.0%p)과 뒤 절반(−0.1%p) 중 플러스가 아닌 쪽이 있음"),
        _row("vs_coin", "-ld", "-ldc", v[2], True, 212, -0.0021, -0.0090, 0.0048, 0.7210, 1.0, -0.004, 0.0, "표본 부족(212/300)"),
        _row("filter_kept_vs_dropped", "-ldt", "-ld", v[3], True, 150, 0.0112, -0.0200, 0.0400, 0.2000, 0.6, 0.01, 0.0124, "표본 부족(150/300) · 근사 비교: 필터 계좌가 다른 때 포지션 중이어서 건너뛴 신호도 '걸러진 것'에 섞입니다",
             n_kept=150, n_dropped=400),
    ]
    ex = "탐색용: 판정에 쓰지 않습니다. 비교가 많아 우연히 좋아 보일 수 있어서, 이것만으로는 결정의 근거가 될 수 없습니다 (쌍 {n}개, 평균 차이 {m})"
    rows += [
        _row("main_vs_control", "-nv", "-ld", "explore", False, 350, 0.0310, 0.0101, 0.0502, 0.0010, None, 0.03, 0.031, ex.format(n=350, m="+3.1%p")),
        _row("main_vs_control", "-sw", "-ld", "explore", False, 90, -0.0150, -0.0400, 0.0100, 0.9000, None, -0.01, -0.02, ex.format(n=90, m="−1.5%p") + " · 표본도 적음(90/300)"),
        _row("main_vs_control", "-tg", "-ld", "explore", False, 0, None, None, None, None, None, None, None, ex.format(n=0, m="—")),
        _row("filter_kept_vs_dropped", "-ldv", "-ld", "explore", False, 300, 0.0020, -0.0100, 0.0140, 0.3300, None, 0.0, 0.004, ex.format(n=300, m="+0.2%p"), n_kept=300, n_dropped=500),
        _row("filter_kept_vs_dropped", "-fqt", "-fq", "explore", False, 40, 0.0400, 0.0100, 0.0700, 0.0100, None, 0.04, 0.04, ex.format(n=40, m="+4.0%p"), n_kept=40, n_dropped=90),
    ]
    counts = {k: sum(r["verdict"] == k for r in rows) for k in VKO}
    return {"phase": phase, "days": days, "checkpoints": {"observe_day": 14, "decide_day": 28}, "min_pairs": 300, "alpha": 0.05, "family_size": 4, "boot": 2000,
            "ci_level": 0.9, "min_days": 5, "observe_ms": T0 + 14 * DAY, "decide_ms": T0 + 28 * DAY, "n_tests": len(rows), "counts": counts, "ds_in_stats": ds_in,
            "summary_ko": summary or f"아직 판정 시점이 아닙니다 ({days}일째, 28일째에 판정)", "rules_ko": SM.decision_rules_ko(), "rows": rows}


def _doc(decision="full", equity0=1000, lineup=True, accounts=True) -> dict:
    d = {"generated_ms": NOW - 60_000, "done_ms": NOW, "start_ms": T0, "started_ms": T0, "judge": {}, "ds_money": False, "watch": {"checkpoints": [], "pools": {}},
         "accounts": [{"id": "core-X-1h-1-fq", "role": "fq", "kind": "core", "name": "X", "tf": "1h", "trades": 5, "wins": 3, "mean_ret": 0.01, "wallet": 1000.0,
                       "max_dd": 0.02, "bust": False, "open": None}] if accounts else None}
    if not accounts:
        del d["accounts"]
    if equity0 is not None:
        d["equity0"] = equity0
    if lineup:
        d["lineup"] = [{"role": s[1:], "suffix": s, "label_ko": v[1], "short_ko": v[0], "accounts": 38} for s, v in NAMES.items()]
    if decision == "full":
        d["decision"] = _decision()
    elif decision is not None:
        d["decision"] = decision
    return d


# ---------------------------------------------------------------- the node runner
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
const M = await import(`file://${S}/js/screens/decision.js`);
const el = document.createElement("div");
el.dataset.screen = "decision";
document.body.appendChild(el);
const ctx = {params: {name: "decision", arg: null, query: {}}, alive: () => true, signal: null,
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


def _run(tmp_path, doc, sels=None, local=None) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    (tmp_path / "shim.mjs").write_text(RANK.SHIM)
    (tmp_path / "run.mjs").write_text(RUNNER)
    cfg = {"static": STATIC, "routes": {}, "local": local or {}, "doc": doc, "sels": sels or {}}
    (tmp_path / "cfg.json").write_text(json.dumps(cfg, ensure_ascii=False))
    r = subprocess.run([node, str(tmp_path / "run.mjs"), str(tmp_path / "cfg.json")], capture_output=True, text=True, timeout=120, cwd=str(tmp_path))
    assert r.returncode == 0, (r.stdout[-600:], r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def _no_junk(text: str) -> None:
    for bad in BAD:
        assert bad not in text, bad


SELS = {"rules": "ol.kd-rules li", "hero": ".kd-hero", "big": ".kd-hero .dl-vbig", "prog": ".kd-hero .dl-progbar", "prim": "tr.kd-row[data-primary=\"1\"]",
        "ref": "tr.kd-row[data-primary=\"0\"]", "verdicts": ".kd-verdict", "plates": ".plate", "reasons": "tr.kd-reason", "card_prim": "section.kd-primary", "card_ref": "section.kd-ref"}


# ---------------------------------------------------------------- (a) full data
def test_full_data_rules_first_then_the_answer_then_the_four_rows(tmp_path):
    o = _run(tmp_path, _doc(), SELS)
    page = o["text"]
    assert o["css"] == "scr/kinds.css" and "kd" in o["cls"].split()
    # the rule box comes first and holds the seven rules with their bold heads
    rules = o["sel"]["rules"]
    assert len(rules) == 7
    for i, head in enumerate(("거래당 순수익 차이", "같은 날 거래는 묶어서 계산", "판정에 쓰는 것은 4개뿐", "우연 보정", "28일째 한 번만 판정", "앞 절반과 뒤 절반이 같은 방향", "하나도 통과 못 하면 '우위 없음'이 결론")):
        assert rules[i]["t"].startswith(head), (i, rules[i]["t"])
    assert "무엇으로 이기고 지는지 미리 정한 규칙" in page and page.index("무엇으로 이기고 지는지 미리 정한 규칙") < page.index("한 줄 결론")
    assert "새 구조는 실전에 쓰지 않습니다" in page and "숫자를 본 뒤에 기준을 바꾸지 않습니다" in page and "4개뿐" in rules[2]["t"]
    # the one-sentence answer and the bar to the decision day
    assert o["sel"]["big"][0]["t"] == "아직 판정 시점이 아닙니다 (15일째, 28일째에 판정)" and "warn" in o["sel"]["big"][0]["c"].split()
    assert "15일째 / 28일째에 판정" in o["sel"]["hero"][0]["t"] and o["sel"]["prog"][0]["a"]["aria-valuenow"] == "54"
    assert "중간 확인(14일째" in page and "지났습니다" in page and "판정은 28일째" in page
    assert "대기 2개" in o["sel"]["hero"][0]["t"] and "표본 부족 2개" in o["sel"]["hero"][0]["t"] and "통과 " not in o["sel"]["hero"][0]["t"].split("모의")[0].replace("통과 · 실패", "")
    # the four deciding rows first, the reference rows after them
    assert page.index("이것으로만 판정합니다 (4개)") < page.index("참고용 (판정에 쓰지 않음)")
    assert len(o["sel"]["prim"]) == 4 and len(o["sel"]["ref"]) == 5
    assert [r["d"]["suffix"] for r in o["sel"]["prim"]] == ["-fq", "-fq", "-ld", "-ldt"] and [r["d"]["test"] for r in o["sel"]["prim"]] == [
        "main_vs_control", "vs_coin", "vs_coin", "filter_kept_vs_dropped"]
    prim_end = page.index("참고용 (판정에 쓰지 않음)")
    assert all(page.index(w) < prim_end for w in ("빠른 손절", "412쌍")) and "자체 판단" in page[prim_end:]
    # the numbers in short readable form: 쌍, 차이 with ▲▼, 구간 (90%), p after the correction
    first = o["sel"]["prim"][0]["t"]
    assert "빠른 손절" in first and "실전 후보" in first and "메인 vs 대조" in first and "412쌍" in first and "대기" in first
    assert "▲ +1.2%p" in first and "−0.3 ~ +2.7%p" in first and first.endswith("0.031")
    second = o["sel"]["prim"][1]["t"]
    assert "동전 짝" in second and "▲ +2.2%p" in second and "0.001 미만" in second and "동전 던지기 짝 (-fqc)과 비교" in second
    third = o["sel"]["prim"][2]["t"]
    assert "212쌍" in third and "300쌍 필요" in third and "▼ −0.2%p" in third and "표본 부족" in third and third.endswith("1.000")
    fourth = o["sel"]["prim"][3]["t"]
    assert "남김 150건" in fourth and "버림 400건" in fourth and "적은 쪽 150건" in fourth and "필터" in fourth
    assert "구간 (90%)" in page and "p (보정 후)" in page and "p (보정 전)" in page
    # the reasons under each row, the halves, and the gate caveat
    reasons = [r["t"] for r in o["sel"]["reasons"]]
    assert len(reasons) == 9 and "앞 절반 +2.0%p · 뒤 절반 +0.5%p · 미리보기입니다: 28일째에 한 번만 판정합니다" in reasons[0]
    assert "표본 부족(212/300)" in reasons[2] and "근사 비교" in reasons[3] and "다른 때 포지션 중" in reasons[3]
    # the reference rows: the word 탐색, the raw p, a plain reason that they cannot decide
    ref = [r["t"] for r in o["sel"]["ref"]]
    assert all("탐색" in t for t in ref) and "0.001 미만" not in ref[0] and ref[0].endswith("0.001")
    assert any("자체 판단" in t and "▲ +3.1%p" in t for t in ref)
    assert page.count("탐색용: 판정에 쓰지 않습니다") == 5 and "이것만으로는 결정의 근거가 될 수 없습니다" in page and "표본도 적음(90/300)" in page
    assert "참고용이라 보정하지 않은 값" in json.dumps(o["sel"]["ref"], ensure_ascii=False) or "p (보정 전)" in page
    # the three kinds of comparison are named: the reference ones as their own cards, the rest as a short explanation
    for plate in ("메인 vs 대조 (참고용)", "필터 (참고용)"):
        assert plate in [p["t"] for p in o["sel"]["plates"]], plate
    assert "동전 짝 (참고용)" not in [p["t"] for p in o["sel"]["plates"]]            # both coin tests are deciding rows: no reference coin rows
    assert "세 가지 비교 방법 보기" in page and "같은 신호 시각에 롱/숏을 동전으로 정한 짝 계좌와 비교합니다" in page
    assert "낱말 뜻" in page and "홀름 보정" in page
    _no_junk(page)


def test_verdict_words_and_colours(tmp_path):
    def words(o):
        return [(v["t"], [c for c in v["c"].split() if c in ("good", "bad", "warn", "thin", "accent")]) for v in o["sel"]["verdicts"]]
    # day 15: 대기 (amber) and 표본 부족 (grey, dashed) on the deciding rows, 탐색 (no tone) on the others; the word is always there
    o = _run(tmp_path, _doc(), SELS)
    w = words(o)[:9]
    assert w == [("대기", ["warn"]), ("대기", ["warn"]), ("표본 부족", ["thin"]), ("표본 부족", ["thin"])] + [("탐색", [])] * 5
    # day 30: 통과 (green) and 실패 (red)
    d = _doc(decision=_decision("decide", 30, ("pass", "fail", "few", "fail"), "통과 1개: 메인 1개(빠른 손절)가 대조를 이겼습니다 (표본 부족 1개)"))
    o = _run(tmp_path, d, SELS)
    w = words(o)[:4]
    assert w == [("통과", ["good"]), ("실패", ["bad"]), ("표본 부족", ["thin"]), ("실패", ["bad"])]
    assert o["sel"]["big"][0]["t"].startswith("통과 1개: 메인 1개(빠른 손절)가 대조를 이겼습니다") and "ok" in o["sel"]["big"][0]["c"].split()
    assert re.search(r"판정일\(28일째, \d\d/\d\d\)이 지났습니다", o["text"]) and "이 표의 통과 · 실패가 최종 판정입니다" in o["text"]
    hero = o["sel"]["hero"][0]["t"]
    assert "통과 1개" in hero and "실패 2개" in hero and "표본 부족 1개" in hero and "대기" not in hero
    assert o["sel"]["prog"][0]["a"]["aria-valuenow"] == "100" and "30일째 / 28일째에 판정" in hero
    assert "앞 절반(+2.0%p)과 뒤 절반(−0.1%p) 중 플러스가 아닌 쪽이 있음" in o["text"]
    # nothing passes: the honest sentence, in the warning tone
    d = _doc(decision=_decision("decide", 40, ("fail", "fail", "few", "few"), "통과한 것 0개: 새 구조에서 우위를 찾지 못했습니다 (표본 부족 2개)"))
    o = _run(tmp_path, d, SELS)
    assert o["sel"]["big"][0]["t"] == "통과한 것 0개: 새 구조에서 우위를 찾지 못했습니다 (표본 부족 2개)" and "warn" in o["sel"]["big"][0]["c"].split()
    assert "새 구조는 실전에 쓰지 않습니다" in o["text"]
    # a few-only decision day
    d = _doc(decision=_decision("decide", 29, ("few", "few", "few", "few"), "판정 시점(28일째)이 지났지만 표본이 모자라 판정하지 못했습니다 (표본 부족 4개): 통과한 것은 없습니다"))
    o = _run(tmp_path, d, SELS)
    assert "표본이 모자라 판정하지 못했습니다" in o["sel"]["big"][0]["t"] and [w_[0] for w_ in words(o)[:4]] == ["표본 부족"] * 4
    _no_junk(o["text"])


def test_wait_phase_before_the_first_look(tmp_path):
    d = _decision("observe", 3, ("few", "few", "few", "few"))
    o = _run(tmp_path, _doc(decision=d), SELS)
    assert o["sel"]["big"][0]["t"] == "아직 판정 시점이 아닙니다 (3일째, 28일째에 판정)" and o["sel"]["prog"][0]["a"]["aria-valuenow"] == "11"
    assert "중간 확인은 14일째" in o["text"] and "그 전에는 아무것도 바꾸지 않습니다" in o["text"] and "중간 확인(14일째" not in o["text"]
    _no_junk(o["text"])


# ---------------------------------------------------------------- (c) the card view
def test_card_view_has_a_card_per_row_with_the_same_words(tmp_path):
    o = _run(tmp_path, _doc(), {"cards": ".kd-kcard", "rows": "tr.kd-row", "seg": ".seg button"}, local={"cl-decision-view": json.dumps("card")})
    cards = o["sel"]["cards"]
    assert len(cards) == 9 and not o["sel"]["rows"]
    assert [c["d"]["primary"] for c in cards] == ["1"] * 4 + ["0"] * 5 and [c["d"]["verdict"] for c in cards][:4] == ["wait", "wait", "few", "few"]
    assert "평균 차이 (거래 하나당)" in cards[0]["t"] and "▲ +1.2%p" in cards[0]["t"] and "412쌍" in cards[0]["t"] and "−0.3 ~ +2.7%p" in cards[0]["t"]
    assert "p (보정 후)" in cards[0]["t"] and "p (보정 전)" in cards[4]["t"] and "앞 +2.0%p · 뒤 +0.5%p" in cards[0]["t"]
    assert "탐색" in cards[4]["t"] and "탐색용: 판정에 쓰지 않습니다" in cards[4]["t"]
    assert [b["t"] for b in o["sel"]["seg"]] == ["표", "카드"]
    _no_junk(o["text"])


# ---------------------------------------------------------------- (d) absent decision
def test_decision_absent_old_league_and_no_snapshot(tmp_path):
    for d, need, notneed in ((_doc(decision=None), ("데이터 준비 중", "판정 기록은 아직 없습니다"), ("새 리그 전용", "이것으로만 판정합니다")),
                             (_doc(decision={"rows": "x"}), ("데이터 준비 중",), ("새 리그 전용",)),            # malformed = absent
                             (_doc(decision=None, lineup=False), ("새 리그 전용", "이전 리그"), ("데이터 준비 중",)),
                             (_doc(decision=None, accounts=False), ("준비 중", "후보 리그 기록이 아직 없습니다"), ("새 리그 전용",)),
                             (None, ("준비 중",), ("새 리그 전용", "이것으로만 판정합니다"))):
        o = _run(tmp_path, d, SELS)
        for t in need:
            assert t in o["text"], (t, o["text"][:300])
        for t in notneed:
            assert t not in o["text"], t
        # the rule box is there anyway: the rule is fixed before there is any number
        assert len(o["sel"]["rules"]) == 7 and "무엇으로 이기고 지는지 미리 정한 규칙" in o["text"] and not o["sel"]["verdicts"]
        _no_junk(o["text"])
    # an empty list of rows is a decision with nothing to compare: a note in both cards, no crash
    d = _decision()
    d["rows"] = []
    o = _run(tmp_path, _doc(decision=d), SELS)
    assert "판정에 쓰는 비교가 아직 없습니다" in o["text"] and "참고용 비교가 아직 없습니다" in o["text"] and "한 줄 결론" in o["text"]
    _no_junk(o["text"])


def test_default_rules_in_the_screen_are_the_servers_rules(tmp_path):
    o = _run(tmp_path, _doc(decision=None), SELS)
    assert o["rulesDefault"] == SM.decision_rules_ko()                       # the fallback text cannot drift from candleague/summary.py
    assert [r["t"] for r in o["sel"]["rules"]] == [t.replace(": ", ": ", 1) for t in SM.decision_rules_ko()]
    d = _decision()
    d["rules_ko"] = ["첫째: 하나", "둘째: 둘"]                                    # the snapshot's own rules win when it has them
    o = _run(tmp_path, _doc(decision=d), SELS)
    assert [r["t"] for r in o["sel"]["rules"]] == ["첫째: 하나", "둘째: 둘"]


# ---------------------------------------------------------------- (e) null numbers
def test_null_numbers_read_as_dashes(tmp_path):
    d = _decision()
    for r in d["rows"]:
        r.update(mean_diff=None, ci_lo=None, ci_hi=None, p_one_sided=None, p_holm=None, half1=None, half2=None, n=0, n_kept=0, n_dropped=0)
        r["reason_ko"] = "표본 부족(0/300)" if r["primary"] else "탐색용: 판정에 쓰지 않습니다"
    o = _run(tmp_path, _doc(decision=d), SELS)
    _no_junk(o["text"])
    first = o["sel"]["prim"][0]["t"]
    assert "0쌍" in first and "300쌍 필요" in first and first.count("—") == 3 and "▲" not in first and "▼" not in first and "＝" not in first
    assert all(t["t"].count("—") >= 3 for t in o["sel"]["ref"]) and "앞 절반" not in " ".join(r["t"] for r in o["sel"]["reasons"])
    # a snapshot with only part of the fields still renders
    o = _run(tmp_path, _doc(decision={"rows": [{"test": "vs_coin", "suffix": "-fq", "primary": True, "verdict": "few", "role": "fq"}]}), SELS)
    assert len(o["sel"]["prim"]) == 1 and "표본 부족" in o["sel"]["prim"][0]["t"] and "15일째" not in o["text"]
    _no_junk(o["text"])
    # an unknown verdict word is a dash, never "undefined"
    d = _decision()
    d["rows"][0]["verdict"] = "weird"
    o = _run(tmp_path, _doc(decision=d), SELS)
    assert o["sel"]["verdicts"][0]["t"] == "—"
    _no_junk(o["text"])


# ---------------------------------------------------------------- (f) the start wallet
def test_text_says_1000_never_5000(tmp_path):
    o = _run(tmp_path, _doc(equity0=1000), SELS)
    assert "$1,000" in o["text"] and "$5,000" not in o["text"] and "5,000" not in o["text"]
    for d in (_decision(), _decision("decide", 30, ("pass", "fail", "few", "fail"))):
        o = _run(tmp_path, _doc(decision=d, equity0=1000), SELS)
        assert "$1,000" in o["text"] and "5,000" not in o["text"]
    o = _run(tmp_path, _doc(equity0=None), SELS)                              # no equity0: no dollar figure is made up
    assert "$" not in o["text"] and "모의 계좌입니다 (가상 돈)" in o["text"]
    for d in (_doc(decision=None), None):
        assert "5,000" not in _run(tmp_path, d, SELS)["text"]


# ---------------------------------------------------------------- (g) DeepSeek
def test_deepseek_note_both_ways(tmp_path):
    o = _run(tmp_path, _doc(decision=_decision(ds_in=False)))
    assert "이 판정은 딥시크를 뺀 후보만으로 계산했습니다" in o["text"] and "딥시크 계좌도 들어 있습니다" not in o["text"]
    o = _run(tmp_path, _doc(decision=_decision(ds_in=True)))
    assert "이 판정에는 딥시크 계좌도 들어 있습니다" in o["text"] and "딥시크를 뺀" not in o["text"]


# ---------------------------------------------------------------- (h) the real server block
def test_a_block_made_by_summary_decision_views_renders(tmp_path):
    lu = [{"role": s[1:], "suffix": s, "label_ko": v[1], "short_ko": v[0]} for s, v in NAMES.items()]
    lu += [{"role": "fqc", "suffix": "-fqc", "label_ko": "대조 · 메인 빠른 손절의 동전 던지기 짝", "short_ko": "빠른 손절 동전"},
           {"role": "ldc", "suffix": "-ldc", "label_ko": "대조 · 계단 · 동전 던지기", "short_ko": "계단 동전"}]
    accts, book = [], {}
    pick = "core-X-1h-1"
    for k in lu:
        accts.append({"id": pick + k["suffix"], "pick": pick, "role": k["role"], "kind": "core"})
        book[pick + k["suffix"]] = []
    for d_ in range(30):
        for j in range(12):
            e = T0 + d_ * DAY + 3_600_000 + j * 60_000
            for k, roe in (("-ld", 0.0), ("-fq", 0.03), ("-fqc", -0.01), ("-ldc", 0.0), ("-nv", 0.01), ("-ldt", 0.0)):
                book[pick + k].append({"symbol": "BTCUSDT", "side": -1 if k.endswith("c") else 1, "entry_time": e, "exit_time": e + 3_600_000, "roe": roe + 0.001 * j, "pnl": 1.0})
    block = SM.decision_views(book, accts, lu, T0, T0 + 30 * DAY, False)
    assert block["phase"] == "decide" and block["counts"]["pass"] >= 1
    d = _doc(decision=json.loads(json.dumps(block, allow_nan=False)))
    o = _run(tmp_path, d, SELS)
    assert len(o["sel"]["prim"]) == 4 and len(o["sel"]["ref"]) == len(block["rows"]) - 4
    assert o["sel"]["big"][0]["t"] == block["summary_ko"] and o["sel"]["verdicts"][0]["t"] == "통과" and "ok" in o["sel"]["big"][0]["c"].split()
    for r in block["rows"][:4]:
        assert r["reason_ko"] in o["text"]
    assert [r["t"] for r in o["sel"]["rules"]] == SM.decision_rules_ko()
    _no_junk(o["text"])


# ---------------------------------------------------------------- 찾기, the menu, the static rules
def test_find_knows_the_screen(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    (tmp_path / "shim.mjs").write_text(RANK.SHIM)
    (tmp_path / "run.mjs").write_text(r"""
import {readFileSync} from "node:fs";
import {install} from "./shim.mjs";
const cfg = JSON.parse(readFileSync(process.argv[2], "utf8"));
install(cfg);
const S = cfg.static;
const LK = await import(`file://${S}/js/lk.js`);
const F = await import(`file://${S}/js/find.js`);
LK.setLeague(cfg.doc);
F.setFindScreens([["versus", "메인 vs 대조"], ["pairs", "짝 비교"], ["decision", "판정"], ["reasons", "청산 이유"]]
  .map(([id, ko]) => ({id, ko, group: "home", groupKo: "홈", title: ko})));
const q = (s) => F.search(s).filter((x) => x.kind === "screen").map((x) => x.id);
console.log(JSON.stringify({name: q("판정"), word: q("홀름"), rule: q("우위 없음"), eng: q("decision"), coin: q("동전"), none: q("zzzz")}));
process.exit(0);
""")
    (tmp_path / "cfg.json").write_text(json.dumps({"static": STATIC, "routes": {}, "local": {}, "doc": _doc()}, ensure_ascii=False))
    r = subprocess.run([node, str(tmp_path / "run.mjs"), str(tmp_path / "cfg.json")], capture_output=True, text=True, timeout=60, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr[-1500:]
    o = json.loads(r.stdout.strip().splitlines()[-1])
    assert o["name"][0] == "decision" and o["word"] == ["decision"] and o["rule"] == ["decision"] and o["eng"] == ["decision"] and "decision" in o["coin"] and o["none"] == []


def test_menu_screens_file_and_static_rules():
    app = open(os.path.join(STATIC, "js", "app.js"), encoding="utf-8").read()
    menu = re.findall(r'\{id: "(\w+)", ko: "([^"]+)", group: "(\w+)"', re.search(r"const MENU = \[(.*?)\];", app, re.S).group(1))
    ids = [m[0] for m in menu]
    i = ids.index("home")
    assert ids[i + 2] == "decision" and menu[i + 2][1] == "판정" and menu[i + 2][2] == "home"                  # right after 요약, in the 홈 group (the answer comes first)
    assert [m[2] for m in menu] == sorted([m[2] for m in menu], key=["trade", "home", "study", "method", "info"].index)       # groups stay together
    screens = re.search(r"const SCREENS = \{([^}]*)\}", app).group(1)
    titles = re.search(r"const MENU_TITLE = \{(.*?)\};\s*const SCREENS", app, re.S).group(1)
    assert 'decision: "decision"' in screens and re.search(r"\bdecision: \"", titles)
    assert os.path.exists(os.path.join(STATIC, "js", "screens", "decision.js"))
    from candleague import dash as D
    src = open(os.path.join(STATIC, "js", "screens", "decision.js"), encoding="utf-8").read()
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "document.write", "new Function", "eval(", "binance.com"):
        assert bad not in src, bad
    assert 'export const css = "scr/kinds.css"' in src
    assert "js/screens/decision.js" in D.STATIC_FILES and "scr/kinds.css" in D.STATIC_FILES
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsl\(", src)                                          # colours only from the tokens
    for m in re.finditer(r'fontSize: "([^"]+)"', src):
        assert m.group(1).startswith("var(--t-"), m.group(0)                                                 # font sizes only from the tokens
    find = open(os.path.join(STATIC, "js", "find.js"), encoding="utf-8").read()
    assert re.search(r"\bdecision: \"판정 ", find)
