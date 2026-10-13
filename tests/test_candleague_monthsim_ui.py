"""candleague 한 달 시뮬 screen (js/screens/monthsim.js, css scr/monthsim.css) and the snippets that register it.

The screen is mounted for real under node on the DOM stand-in of test_candleague_rank_ui (text nodes only, like the browser's) with hand-made
snapshots whose ``monthsim`` follows candleague.monthsim.monthsim_views, and the tests read what reached the page:
  (a) full data: the rule box first (4 items), the one-sentence answer, the range bars of 실전 후보 and 대조 on ONE shared axis with the ticks at x1 and
      the x4 goal and the hatched coin bar under each (every number written, the dollars from equity0), the comparison with the coin, the small
      table (2배 · 4배 · 반토막 · 손실), the single-pick lines, the word list and the honest limits;
  (b) status "few": the "아직 자료가 모자랍니다 (N일, M건 · 7일 · 30건부터)" box, no bar and no range number for that kind;
  (c) the card view; (d) ``monthsim`` absent: 데이터 준비 중 / 새 리그 전용 / 준비 중 with the rule box still there; (e) null numbers read "—";
  (f) the dollars come from equity0 and never from a wallet written in the screen; (g) DeepSeek note both ways;
  (h) a block made by the real monthsim_views from synthetic trades; (i) the pure helpers (scale, words).
Plus the static rules (text only, tokens only) and the four registration snippets (MENU, MENU_TITLE, SCREENS, find.js SCREEN_WORDS) applied to a copy of
the static folder."""

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
from candleague import monthsim as MS  # noqa: E402

STATIC = os.path.join(ROOT, "candleague", "static")
DAY = 86_400_000
T0 = (1_791_000_000_000 // DAY) * DAY
NOW = T0 + 15 * DAY
BAD = ("NaN", "undefined", "null", "Infinity")
SNIPPETS = {
    "menu": '{id: "monthsim", ko: "한 달 시뮬", group: "home"},',
    "title": 'monthsim: "한 달 시뮬 (지금 성적이 한 달 이어진다면? 5% ~ 95% 범위 · 중앙값 · 4배 이상 몫, 동전 짝과 비교하는 운 계산기)",',
    "screen": 'monthsim: "monthsim",',
    "words": 'monthsim: "한 달 시뮬 운 계산기 시뮬레이션 중앙값 범위 4배 목표 동전 짝 운 실력 단일 후보 monthsim",',
}


# ---------------------------------------------------------------- hand-made snapshots
NAMES = {"-fq": ("빠른 손절", "메인 · 구조 확실히 무너지면 빠른 손절 (실전 후보)", "live", False), "-fqc": ("빠른 손절 동전", "대조 · 메인 빠른 손절의 동전 던지기 짝", "live", True),
         "-ld": ("계단", "대조 · 계단 · 손절 최대 2 ATR", "control", False), "-ldc": ("계단 동전", "대조 · 계단 · 동전 던지기", "control", True)}
P = {"-fq": (0.61, 0.87, 1.14, 1.49, 2.12), "-fqc": (0.83, 1.03, 1.23, 1.44, 1.79), "-ld": (0.36, 0.52, 0.67, 0.86, 1.27), "-ldc": (0.46, 0.64, 0.79, 0.97, 1.28)}
SH = {"-fq": (0.06, 0.0004, 0.01, 0.38), "-fqc": (0.01, 0.0, 0.0005, 0.20), "-ld": (0.0, 0.0, 0.21, 0.85), "-ldc": (0.0, 0.0, 0.09, 0.78)}


def _kind(sfx, status="ok", days=14, n=1596, **kw):
    short, label, pair, coin = NAMES[sfx]
    twin = {"-fq": "-fqc", "-fqc": "-fq", "-ld": "-ldc", "-ldc": "-ld"}[sfx]
    k = {"suffix": sfx, "role": sfx[1:], "label_ko": label, "short_ko": short, "pair": pair, "is_coin": coin, "twin": twin, "status": status, "days": days, "window_days": 14,
         "n_accounts": 38, "n_trades": n, "need": {"days": 7, "trades": 30}, "few_ko": None, "observed_multiple": 1.06, "linear_multiple": None, "percentiles": None,
         "p_x2": None, "p_x4": None, "p_below_half": None, "p_loss": None, "single_account": None, "edge_vs_coin": None}
    if status == "ok":
        p = P[sfx]
        x2, x4, half, loss = SH[sfx]
        k.update(percentiles=dict(zip(MS.PCT_KEYS, p)), p_x2=x2, p_x4=x4, p_below_half=half, p_loss=loss, linear_multiple=1.13,
                 single_account={"n": 38, "p05": p[0] + 0.24, "p50": p[2], "p95": p[2] + 0.24, "min": p[0], "max": p[4], "days": 14})
        if not coin:
            k["edge_vs_coin"] = {"status": "ok", "real_median": p[2], "coin_median": P[twin][2], "diff": round(p[2] - P[twin][2], 4), "lo": -0.84, "hi": 1.58, "ci_level": 0.9,
                                 "zero_in_interval": True, "coin_reaches_real_median": 0.61, "p_real_beats_coin": 0.4, "outer": 600, "inner": 300}
    elif status == "few":
        k["few_ko"] = MS.few_text(days, n)
    k.update(kw)
    return k


def _month(kinds=None, ds_in=False, equity0=1000.0, headline=None) -> dict:
    ks = kinds if kinds is not None else [_kind(s) for s in NAMES]
    live = next((k for k in ks if k["suffix"] == "-fq"), None)
    wallet = f" (${equity0:,.0f} → ${equity0 * 1.14:,.0f})" if equity0 else ""
    head = headline or (f"실전 후보 14일 · 1,596건: 한 달(30일) 이어진다고 해 본 중앙값은 1.14배{wallet}, 동전 짝은 1.23배입니다."
                        if live and live["status"] == "ok" else f"실전 후보는 {live['few_ko']}" if live else "아직 자료가 없습니다.")
    return {"horizon_days": 30, "boot": 2000, "goal_multiple": 4.0, "min_days": 7, "min_trades": 30, "ci_level": 0.9, "equity0": equity0, "start_ms": T0, "through_ms": T0 + 14 * DAY,
            "window_days": 14, "ds_in_stats": ds_in, "headline_ko": head, "note_ko": MS.notes_ko(), "kinds": ks}


def _doc(month="full", equity0=1000, lineup=True, accounts=True) -> dict:
    d = {"generated_ms": NOW - 60_000, "done_ms": NOW, "start_ms": T0, "started_ms": T0, "judge": {}, "ds_money": False, "watch": {"checkpoints": [], "pools": {}},
         "accounts": [{"id": "core-X-1h-1-fq", "role": "fq", "kind": "core", "name": "X", "tf": "1h", "trades": 5, "wins": 3, "mean_ret": 0.01, "wallet": 1000.0,
                       "max_dd": 0.02, "bust": False, "open": None}] if accounts else None}
    if not accounts:
        del d["accounts"]
    if equity0 is not None:
        d["equity0"] = equity0
    if lineup:
        d["lineup"] = [{"role": s[1:], "suffix": s, "label_ko": v[1], "short_ko": v[0], "accounts": 38} for s, v in NAMES.items()]
    if month == "full":
        d["monthsim"] = _month()
    elif month is not None:
        d["monthsim"] = month
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
const M = await import(`file://${S}/js/screens/monthsim.js`);
const el = document.createElement("div");
el.dataset.screen = "monthsim";
document.body.appendChild(el);
const ctx = {params: {name: "monthsim", arg: null, query: {}}, alive: () => true, signal: null,
  api: async (p) => (await globalThis.fetch(p)).json(), meta: () => LK.getMeta(),
  onLeague: (fn) => { if (doc) fn(doc); }, onLive: () => () => {}, onPositions: () => () => {},
  every: () => {}, css: async () => null, wide() {}, setTitle() {}, setQuery() {},
  href: (n, a) => `#/${n}${a ? "/" + a : ""}`};
await M.mount(el, ctx);
for (let i = 0; i < 4; i++) await new Promise((r) => setTimeout(r, 10));
const out = {text: txt(el), css: M.css, cls: el.className, sel: {}, notesDefault: M.NOTES_DEFAULT};
for (const [k, sel] of Object.entries(cfg.sels || {})) {
  out.sel[k] = el.querySelectorAll(sel).map((n) => ({t: txt(n), d: {...n.dataset}, c: n.className, a: Object.fromEntries(n.attrs),
    s: Object.fromEntries(Object.entries(n.style).filter(([, v]) => typeof v !== "function"))}));
}
console.log(JSON.stringify(out));
process.exit(0);
"""

HELPERS = r"""
import {readFileSync} from "node:fs";
import {install} from "./shim.mjs";
const cfg = JSON.parse(readFileSync(process.argv[2], "utf8"));
install(cfg);
const M = await import(`file://${cfg.static}/js/screens/monthsim.js`);
const k = (p05, p95, status = "ok") => ({status, p: status === "ok" ? {p05, p50: Math.sqrt(p05 * p95), p95} : null});
const sc = M.makeScale([k(0.61, 2.12), k(0.83, 1.79), k(0.36, 1.27)], 4);
const wide = M.makeScale([k(0.02, 90)], 4);
const none = M.makeScale([k(null, null, "few")], 4);
console.log(JSON.stringify({
  mult: [0.5, 1.234, 9.999, 12.34, 123.4, 1234.5, 0, null, "x", NaN].map((x) => M.mult(x)), msign: [0.1, -0.4, 0].map((x) => M.mult(x, true)),
  usd: [M.usd(1.14, 1000), M.usd(0.003, 1000), M.usd(4, 2500), M.usd(1.14, null), M.usd(null, 1000), M.usd(1.14, 0), M.usd(1234.5, 1000)],
  share: [0, 0.004, 0.01, 0.123, 0.5, 0.99, 0.995, 1, null, "x"].map((x) => M.share(x)),
  out: [0, 0.61, 0.995, null].map((x) => M.outOf100(x)),
  sc: {lo: sc.lo, hi: sc.hi, ticks: sc.ticks, p: [0.61, 1, 2.12, 4].map((m) => M.pos(sc, m)), off: [M.pos(sc, 0.0001), M.pos(sc, 1e9), M.pos(sc, null)]},
  wide: {lo: wide.lo, hi: wide.hi, ticks: wide.ticks.map((t) => [t.label, t.at])}, none: {lo: none.lo, hi: none.hi, ticks: none.ticks.map((t) => t.label)},
  norm: [M.normMonth(null), M.normMonth([]), M.normMonth({kinds: "x"}), M.normMonth({kinds: []}), M.normMonth({kinds: [{suffix: ""}, null, 3]})],
  gate: [M.gate(null).state, M.gate({}).state],
}));
process.exit(0);
"""


def _node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    return node


def _run(tmp_path, doc, sels=None, local=None, static=STATIC) -> dict:
    (tmp_path / "shim.mjs").write_text(RANK.SHIM)
    (tmp_path / "run.mjs").write_text(RUNNER)
    cfg = {"static": static, "routes": {}, "local": local or {}, "doc": doc, "sels": sels or {}}
    (tmp_path / "cfg.json").write_text(json.dumps(cfg, ensure_ascii=False))
    r = subprocess.run([_node(), str(tmp_path / "run.mjs"), str(tmp_path / "cfg.json")], capture_output=True, text=True, timeout=120, cwd=str(tmp_path))
    assert r.returncode == 0, (r.stdout[-600:], r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def _no_junk(text: str) -> None:
    for bad in BAD:
        assert bad not in text, bad


SELS = {"rules": "ol.ms-rules li", "hero": ".ms-hero", "big": ".ms-hero .dl-vbig", "bars": ".ms-bar", "krows": ".ms-krow", "one": ".ms-tick.one", "goal": ".ms-tick.goal",
        "range": ".ms-range", "med": ".ms-med", "axis": ".ms-axis", "at": ".ms-at", "edge": ".ms-edge", "rows": "tr.ms-row", "cards": ".ms-kcard", "single": ".ms-srow",
        "few": ".ms-few", "fewt": ".ms-fewt", "plates": ".plate", "legend": ".ms-legend li", "grp": ".ms-grp", "nums": ".ms-n", "limits": "ul.ms-limits li",
        "seg": ".seg button", "verdict": ".kd-verdict"}


def _pct(s, key):
    return float(s[key].rstrip("%"))


# ---------------------------------------------------------------- (a) full data
def test_full_data_rules_first_then_the_answer_then_the_bars(tmp_path):
    o = _run(tmp_path, _doc(), SELS)
    page = o["text"]
    assert o["css"] == ["scr/kinds.css", "scr/monthsim.css"] and "kd" in o["cls"].split() and "ms" in o["cls"].split()
    # the rule box is first and says what this is and is not
    rules = o["sel"]["rules"]
    assert [r["t"].split(":")[0] for r in rules] == ["이 화면은", "동전 짝도 같이", "이 화면이 아닌 것", "믿기 전에"]
    assert "2,000번" in rules[0]["t"] and "5% ~ 95%" in rules[0]["t"] and "예측도 약속도 아닙니다" in rules[2]["t"] and "7일" in rules[3]["t"] and "30건" in rules[3]["t"]
    order = ["이 화면은 무엇인가요", "한 줄 결론", "한 달(30일) 뒤 범위", "몫으로 보면", "단일 후보 하나는 이만큼 갈린다", "낱말 뜻", "솔직한 한계"]
    assert [page.index(w) for w in order] == sorted(page.index(w) for w in order)
    # one sentence: the server's, counts and the median only
    big = o["sel"]["big"][0]
    assert big["t"] == _month()["headline_ko"] and "warn" not in big["c"].split() and "ok" not in big["c"].split()
    assert "2,000번 중 4배 이상은 1% 미만, 1배 미만(손실)은 38%입니다" in o["sel"]["hero"][0]["t"] and "목표 4배 = $4,000" in o["sel"]["hero"][0]["t"]
    assert "앞으로를 약속하는 숫자가 아닙니다" in o["sel"]["hero"][0]["t"] and "14일치" in o["sel"]["hero"][0]["t"]
    # the bars: four, in the order fq, fqc, ld, ldc, in two groups, with every number written
    bars = o["sel"]["bars"]
    assert [b["d"]["suffix"] for b in bars] == ["-fq", "-fqc", "-ld", "-ldc"] and [g["d"]["pair"] for g in o["sel"]["grp"]] == ["live", "control"]
    assert [("ms-b-live" in b["c"], "ms-b-coin" in b["c"], "ms-b-control" in b["c"]) for b in bars] == [(True, False, False), (False, True, False), (False, False, True), (False, True, False)]
    rows = o["sel"]["krows"]
    assert len(rows) == 4 and [r["d"]["status"] for r in rows] == ["ok"] * 4
    first = rows[0]["t"]
    for w in ("빠른 손절", "14일 · 1,596건", "나쁜 쪽 5%", "0.61배", "$610", "중앙값 50%", "1.14배", "$1,140", "좋은 쪽 95%", "2.12배", "$2,120",
              "지금까지 실제로는 1.06배 (14일)", "지금 속도 그대로 30일 직선으로 늘리면 1.13배"):
        assert w in first, (w, first)
    assert "동전 짝" in rows[1]["t"] and "방향을 동전으로" in rows[1]["t"] and "0.83배" in rows[1]["t"] and "$1,230" in rows[1]["t"] and "1.79배" in rows[1]["t"]
    assert "계단" in rows[2]["t"] and "0.36배" in rows[2]["t"] and "1.27배" in rows[2]["t"] and "0.46배" in rows[3]["t"]
    assert all(b["a"]["role"] == "img" and "중앙값" in b["a"]["aria-label"] and "5%" in b["a"]["aria-label"] for b in bars)
    # ONE shared axis: the ticks at x1 and at the x4 goal are at the same place on every bar and on the axis rows
    one, goal = o["sel"]["one"], o["sel"]["goal"]
    assert len(one) == 4 and len(goal) == 4 and len({t["s"]["--at"] for t in one}) == 1 and len({t["s"]["--at"] for t in goal}) == 1
    at1, at4 = _pct(one[0]["s"], "--at"), _pct(goal[0]["s"], "--at")
    assert 0 < at1 < at4 < 100
    labels = {a["t"]: _pct(a["s"], "--at") for a in o["sel"]["at"][:4]}
    assert labels["1배"] == pytest.approx(at1, abs=0.01) and labels["4배 목표"] == pytest.approx(at4, abs=0.01) and len(o["sel"]["axis"]) == 2
    # each bar: the range from 5% to 95% with the median inside, the 1x tick inside the live bar (0.61 .. 2.12) and the goal beyond it
    for b, rng, med, p in zip(bars, o["sel"]["range"], o["sel"]["med"], P.values()):
        lo, w, m = _pct(rng["s"], "--l"), _pct(rng["s"], "--w"), _pct(med["s"], "--at")
        assert lo < m < lo + w < at4 and (lo < at1 < lo + w) == (p[0] < 1 < p[4]), (b["d"]["suffix"], lo, m, w)
        assert b["d"]["p05"] == str(p[0]) and b["d"]["p50"] == str(p[2]) and b["d"]["p95"] == str(p[4])
    r_live, r_ctl = o["sel"]["range"][0], o["sel"]["range"][2]
    assert _pct(r_live["s"], "--l") > _pct(o["sel"]["range"][2]["s"], "--l") and _pct(r_ctl["s"], "--l") < at1          # 0.61 starts right of 0.36
    # the legend: what every mark is, and that the coin bars are hatched (not only a colour)
    leg = " ".join(x["t"] for x in o["sel"]["legend"])
    assert "막대 = 5% ~ 95%" in leg and "표시 = 중앙값" in leg and "본전(1배)" in leg and "목표(4배)" in leg and "빗금 = 동전 짝" in leg
    # the comparison with the coin, in words
    edges = o["sel"]["edge"]
    assert len(edges) == 2
    assert all("구분 안 됨" in e["t"] and "동전 짝과 중앙값 차이" in e["t"] and "90% 구간 −0.84배 ~ +1.58배" in e["t"] and "구간에 0이 들어 있어" in e["t"] for e in edges)
    assert "−0.09배" in edges[0]["t"] and "동전 짝의 달 중 실전 후보의 중앙값(1.14배) 이상 나온 것은 100번 중 61번입니다" in edges[0]["t"]
    assert "대조의 중앙값(0.67배)" in edges[1]["t"]
    # the small table: 2배 · 4배 · 반토막 · 손실 as shares
    trs = o["sel"]["rows"]
    assert [r["d"]["suffix"] for r in trs] == ["-fq", "-fqc", "-ld", "-ldc"]
    for w in ("2배 이상", "4배 이상", "반토막 이하", "손실", "1배 미만"):
        assert w in page
    assert "실전 후보" in trs[0]["t"] and "14일" in trs[0]["t"] and "1.14배" in trs[0]["t"] and "6%" in trs[0]["t"] and "1% 미만" in trs[0]["t"] and "38%" in trs[0]["t"]
    assert "21%" in trs[2]["t"] and "85%" in trs[2]["t"] and "동전 짝" in trs[1]["t"] and "kd-coin" in trs[1]["c"]
    # the single-pick lines: the cross-section, written
    single = o["sel"]["single"]
    assert len(single) == 4 and "계좌 38개 중" in single[0]["t"] and "나쁜 쪽 5% 0.85배 · 가운데 1.14배 · 좋은 쪽 95% 1.38배" in single[0]["t"]
    assert "시뮬레이션이 아니라서 앞으로의 운은 들어 있지 않고" in page
    # the word list and the honest limits (the server's own)
    for w in ("배수 (1.2배)", "중앙값", "5% ~ 95% 범위", "동전 짝", "구간 (90%)", "단일 후보", "UTC 날짜 기준"):
        assert w in page
    assert [x["t"] for x in o["sel"]["limits"]] == MS.notes_ko() and "이 계산은 딥시크를 뺀 후보만으로 했습니다" in page
    _no_junk(page)


def test_edge_words_follow_the_interval(tmp_path):
    def with_edge(lo, hi, zero):
        ks = [_kind(s) for s in NAMES]
        ks[0]["edge_vs_coin"].update(lo=lo, hi=hi, zero_in_interval=zero, diff=0.4)
        return _doc(month=_month(ks))
    o = _run(tmp_path, with_edge(0.1, 0.9, False), SELS)
    e = o["sel"]["edge"][0]
    assert "동전보다 위" in e["t"] and "참고용" in e["t"] and e["d"]["edge"] == "동전보다 위" and "구간에 0이 들어 있어" not in e["t"]
    o = _run(tmp_path, with_edge(-0.9, -0.1, False), SELS)
    assert "동전보다 아래" in o["sel"]["edge"][0]["t"] and "동전보다 못합니다" in o["sel"]["edge"][0]["t"]
    o = _run(tmp_path, with_edge(-0.9, 0.9, True), SELS)
    assert "구분 안 됨" in o["sel"]["edge"][0]["t"] and "운일 수 있습니다" in o["sel"]["edge"][0]["t"]
    # an interval without ends cannot be called anything
    o = _run(tmp_path, with_edge(None, None, False), SELS)
    assert "구분 안 됨" in o["sel"]["edge"][0]["t"] and "90% 구간" not in o["sel"]["edge"][0]["t"]
    # an edge the server could not compute: a plain note, no number
    ks = [_kind(s) for s in NAMES]
    ks[0]["edge_vs_coin"] = {"status": "few"}
    o = _run(tmp_path, _doc(month=_month(ks)), SELS)
    assert "동전 짝과의 비교는 두 쪽 모두 자료가 쌓이면 나옵니다" in o["sel"]["edge"][0]["t"] if o["sel"]["edge"] else "동전 짝과의 비교는 두 쪽 모두 자료가 쌓이면 나옵니다" in o["text"]
    _no_junk(o["text"])


# ---------------------------------------------------------------- (b) too little data
def test_few_kinds_show_the_message_and_no_range(tmp_path):
    ks = [_kind("-fq", "few", days=5, n=21), _kind("-fqc", "few", days=5, n=21), _kind("-ld"), _kind("-ldc")]
    # whatever a "few" entry carries, no number of a range reaches the page
    ks[0].update(percentiles=dict(zip(MS.PCT_KEYS, (9.11, 9.22, 9.33, 9.44, 9.55))), p_x2=0.77, p_loss=0.66, single_account={"n": 3, "p05": 7.7, "p50": 7.8, "p95": 7.9})
    o = _run(tmp_path, _doc(month=_month(ks)), SELS)
    msg = "아직 자료가 모자랍니다 (5일, 21건 · 7일 · 30건부터)"
    assert [f["d"]["suffix"] for f in o["sel"]["few"]] == ["-fq", "-fqc"] and all(t["t"] == msg for t in o["sel"]["fewt"])
    assert [b["d"]["suffix"] for b in o["sel"]["bars"]] == ["-ld", "-ldc"]                  # the other group still has its bars
    page = o["text"]
    for junk in ("9.33", "9.11", "9.55", "77%", "66%", "7.8배", "$9,330"):
        assert junk not in page, junk
    big = o["sel"]["big"][0]
    assert big["t"] == f"실전 후보는 {msg}" and "warn" in big["c"].split()
    assert "2,000번 중 4배 이상은" not in o["sel"]["hero"][0]["t"]                              # no share is claimed for a kind without numbers
    assert "지금까지 실제로는 1.06배 (14일)" in o["sel"]["few"][0]["t"]                          # the observed fact is still there
    fq_edge = o["sel"]["edge"][0]
    assert "동전 짝과의 비교는 두 쪽 모두 자료가 쌓이면 나옵니다" in fq_edge["t"] and "구분 안 됨" not in fq_edge["t"]
    # the table: the message in place of the numbers, and the coin / single lines left out
    trs = o["sel"]["rows"]
    assert msg in trs[0]["t"] and "1.14배" not in trs[0]["t"] and trs[0]["d"]["status"] == "few" and "0.67배" in trs[2]["t"]
    assert [s["d"]["suffix"] for s in o["sel"]["single"]] == ["-ld", "-ldc"]
    _no_junk(page)
    # all four few: the page is the rule box, the sentence and the messages
    ks = [_kind(s, "few", days=3, n=8) for s in NAMES]
    o = _run(tmp_path, _doc(month=_month(ks)), SELS)
    assert not o["sel"]["bars"] and len(o["sel"]["few"]) == 4 and o["sel"]["big"][0]["t"].startswith("실전 후보는 아직 자료가 모자랍니다 (3일, 8건")
    assert "모든 계좌" in o["text"] and "자료가 쌓이면 나옵니다" in o["text"]
    _no_junk(o["text"])


def test_an_ok_kind_without_percentiles_is_few_and_a_missing_kind_says_so(tmp_path):
    ks = [_kind("-fq", percentiles=None), _kind("-fqc"), _kind("-ld", "none"), _kind("-ldc", "none")]
    o = _run(tmp_path, _doc(month=_month(ks, headline="x")), SELS)
    assert "아직 자료가 모자랍니다 (14일, 1,596건 · 7일 · 30건부터)" in o["sel"]["few"][0]["t"]            # built by the screen from the counts
    assert [r["d"]["status"] for r in o["sel"]["krows"]] == ["few", "ok", "none", "none"] and "이 종류의 계좌가 이 리그에 없습니다" in o["text"]
    _no_junk(o["text"])


# ---------------------------------------------------------------- (c) the card view
def test_card_view_has_a_card_per_kind_with_the_same_words(tmp_path):
    o = _run(tmp_path, _doc(), SELS, local={"cl-monthsim-view": json.dumps("card")})
    cards = o["sel"]["cards"]
    assert len(cards) == 4 and not o["sel"]["rows"] and [c["d"]["suffix"] for c in cards] == ["-fq", "-fqc", "-ld", "-ldc"]
    assert "중앙값" in cards[0]["t"] and "1.14배" in cards[0]["t"] and "$1,140" in cards[0]["t"] and "6%" in cards[0]["t"] and "38%" in cards[0]["t"]
    for w in ("2배 이상", "4배 이상 (목표)", "반토막 이하", "손실 (1배 미만)"):
        assert w in cards[0]["t"], w
    assert [b["t"] for b in o["sel"]["seg"]] == ["표", "카드"] and len(o["sel"]["bars"]) == 4              # the bars are there in both views
    o = _run(tmp_path, _doc(month=_month([_kind("-fq", "few", days=2, n=3)] + [_kind(s) for s in ("-fqc", "-ld", "-ldc")])), SELS, local={"cl-monthsim-view": json.dumps("card")})
    assert "아직 자료가 모자랍니다 (2일, 3건 · 7일 · 30건부터)" in o["sel"]["cards"][0]["t"] and "1.14배" not in o["sel"]["cards"][0]["t"]
    o = _run(tmp_path, _doc(), SELS, local={"cl-monthsim-view": json.dumps("table")})
    assert len(o["sel"]["rows"]) == 4 and not o["sel"]["cards"]


# ---------------------------------------------------------------- (d) absent block
def test_monthsim_absent_old_league_and_no_snapshot(tmp_path):
    for d, need, notneed in ((_doc(month=None), ("데이터 준비 중", "한 달 시뮬 기록은 아직 없습니다"), ("새 리그 전용", "한 줄 결론")),
                             (_doc(month={"kinds": "x"}), ("데이터 준비 중",), ("새 리그 전용",)),                  # malformed = absent
                             (_doc(month={"kinds": []}), ("데이터 준비 중",), ("새 리그 전용",)),
                             (_doc(month=None, lineup=False), ("새 리그 전용", "이전 리그"), ("데이터 준비 중",)),
                             (_doc(month=None, accounts=False), ("준비 중", "후보 리그 기록이 아직 없습니다"), ("새 리그 전용",)),
                             (None, ("준비 중",), ("새 리그 전용", "한 줄 결론"))):
        o = _run(tmp_path, d, SELS)
        for t in need:
            assert t in o["text"], (t, o["text"][:300])
        for t in notneed:
            assert t not in o["text"], t
        # the rule box is there anyway, and no bar
        assert len(o["sel"]["rules"]) == 4 and "이 화면은 무엇인가요" in o["text"] and not o["sel"]["bars"] and not o["sel"]["rows"]
        assert "약속이 아닙니다" in o["text"]
        _no_junk(o["text"])


# ---------------------------------------------------------------- (e) null numbers
def test_null_numbers_read_as_dashes_never_zero(tmp_path):
    ks = [_kind(s) for s in NAMES]
    for k in ks:
        k.update(p_x2=None, p_x4=None, p_below_half=None, p_loss=None, observed_multiple=None, linear_multiple=None, single_account=None)
        if k["edge_vs_coin"]:
            k["edge_vs_coin"].update(coin_reaches_real_median=None)
    m = _month(ks, equity0=None)
    m.update(window_days=0)
    o = _run(tmp_path, _doc(month=m, equity0=None), SELS)
    page = o["text"]
    _no_junk(page)
    assert "—" in o["sel"]["rows"][0]["t"] and o["sel"]["rows"][0]["t"].count("—") == 4 and "지금까지 실제로는" not in page
    assert not o["sel"]["single"] and "자료가 쌓이면 나옵니다" in page and "동전 짝의 달 중" not in page
    assert "$" not in page                                                              # no wallet at all: no dollar figure is made up
    # a snapshot with only part of the fields still renders
    mini = {"kinds": [{"suffix": "-fq", "status": "ok", "percentiles": {"p05": 0.9, "p50": 1.0, "p95": 1.2}}, {"suffix": "-fqc"}]}
    o = _run(tmp_path, _doc(month=mini, equity0=None), SELS)
    assert len(o["sel"]["bars"]) == 1 and "0.90배" in o["text"] and "1.20배" in o["text"]
    _no_junk(o["text"])


# ---------------------------------------------------------------- (f) the start wallet
def test_dollars_come_from_equity0_never_a_written_wallet(tmp_path):
    o = _run(tmp_path, _doc(equity0=1000), SELS)
    assert "$1,000" in o["text"] and "$5,000" not in o["text"] and "5,000" not in o["text"] and "$1,140" in o["text"]
    o = _run(tmp_path, _doc(month=_month(equity0=2500.0), equity0=2500), SELS)              # another start wallet: the dollars follow the snapshot
    page = o["text"]
    assert "$2,500" in page and "$2,850" in page and "$1,525" in page and "$10,000" in page and "$1,140" not in page and "$1,000" not in page.replace("$10,000", "")
    assert "5,000" not in page
    # no equity0 in the doc: the block's own start wallet is used; none at all: no dollars
    o = _run(tmp_path, _doc(equity0=None), SELS)
    assert "$1,140" in o["text"] and "모의 계좌입니다 (가상 돈)" in o["text"]
    m = _month(equity0=None)
    o = _run(tmp_path, _doc(month=m, equity0=None), SELS)
    assert "$" not in o["text"] and "5,000" not in o["text"]
    for d in (_doc(month=None), None):
        assert "5,000" not in _run(tmp_path, d, SELS)["text"]


# ---------------------------------------------------------------- (g) DeepSeek
def test_deepseek_note_both_ways(tmp_path):
    o = _run(tmp_path, _doc(month=_month(ds_in=False)))
    assert "이 계산은 딥시크를 뺀 후보만으로 했습니다" in o["text"] and "딥시크 계좌도 들어 있습니다" not in o["text"]
    o = _run(tmp_path, _doc(month=_month(ds_in=True)))
    assert "이 계산에는 딥시크 계좌도 들어 있습니다" in o["text"] and "딥시크를 뺀" not in o["text"]


# ---------------------------------------------------------------- (h) the real server block
def _real_block(days=14):
    import numpy as np
    rng = np.random.default_rng(11)
    lu = [{"role": s[1:], "suffix": s, "label_ko": v[1], "short_ko": v[0]} for s, v in NAMES.items()]
    accts, book = [], {}
    shock = rng.normal(0.004, 0.04, days)
    for s in NAMES:
        for p in range(6):
            aid = f"core-P{p}-1h-1{s}"
            accts.append({"id": aid, "pick": f"core-P{p}", "role": s[1:], "kind": "core"})
            w, tr = 1000.0, []
            for d_ in range(days):
                r = shock[d_] * (0.5 if s.endswith("c") else 1.0) + rng.normal(0, 0.01)
                for j in range(3):
                    tr.append({"exit_time": T0 + d_ * DAY + (2 + j) * 3_600_000, "pnl": w * r / 3})
                w *= 1 + r
            book[aid] = tr
    return MS.monthsim_views(book, accts, lu, T0, T0 + days * DAY + 3_600_000, False, 1000.0)


def test_a_block_made_by_monthsim_views_renders(tmp_path):
    block = json.loads(json.dumps(_real_block(), allow_nan=False))
    assert [k["status"] for k in block["kinds"]] == ["ok"] * 4
    o = _run(tmp_path, _doc(month=block), SELS)
    assert o["sel"]["big"][0]["t"] == block["headline_ko"] and len(o["sel"]["bars"]) == 4 and len(o["sel"]["rows"]) == 4 and len(o["sel"]["edge"]) == 2
    k = block["kinds"][0]
    assert f"{k['percentiles']['p50']:.2f}배" in o["sel"]["krows"][0]["t"] and f"{k['percentiles']['p05']:.2f}배" in o["sel"]["krows"][0]["t"]
    assert [x["t"] for x in o["sel"]["limits"]] == block["note_ko"] and f"계좌 {block['kinds'][0]['single_account']['n']}개 중" in o["sel"]["single"][0]["t"]
    e = k["edge_vs_coin"]
    assert f"동전 짝과 중앙값 차이 {'+' if e['diff'] > 0 else '−'}{abs(e['diff']):.2f}배" in o["sel"]["edge"][0]["t"] and ("구분 안 됨" if e["zero_in_interval"] else "동전보다") in o["sel"]["edge"][0]["t"]
    _no_junk(o["text"])
    # a young league: the same block with too few days is the message, not a number
    young = json.loads(json.dumps(_real_block(5), allow_nan=False))
    assert [k["status"] for k in young["kinds"]] == ["few"] * 4
    o = _run(tmp_path, _doc(month=young), SELS)
    assert not o["sel"]["bars"] and "아직 자료가 모자랍니다 (5일, 90건 · 7일 · 30건부터)" in o["text"]
    _no_junk(o["text"])


def test_default_notes_in_the_screen_are_the_servers_notes(tmp_path):
    o = _run(tmp_path, _doc(month=None), SELS)
    assert o["notesDefault"] == MS.notes_ko()                                           # the fallback text cannot drift from candleague/monthsim.py
    m = _month()
    m["note_ko"] = ["첫째 한계", "둘째 한계"]                                              # the snapshot's own notes win when it has them
    assert [x["t"] for x in _run(tmp_path, _doc(month=m), SELS)["sel"]["limits"]] == ["첫째 한계", "둘째 한계"]
    m["note_ko"] = []
    assert [x["t"] for x in _run(tmp_path, _doc(month=m), SELS)["sel"]["limits"]] == MS.notes_ko()


# ---------------------------------------------------------------- (i) the pure helpers
def test_helpers_scale_and_words(tmp_path):
    (tmp_path / "shim.mjs").write_text(RANK.SHIM)
    (tmp_path / "h.mjs").write_text(HELPERS)
    (tmp_path / "cfg.json").write_text(json.dumps({"static": STATIC, "routes": {}, "local": {}}))
    r = subprocess.run([_node(), str(tmp_path / "h.mjs"), str(tmp_path / "cfg.json")], capture_output=True, text=True, timeout=60, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr[-1500:]
    o = json.loads(r.stdout.strip().splitlines()[-1])
    assert o["mult"] == ["0.50배", "1.23배", "10.0배", "12.3배", "123배", "1,235배", "0.00배", "—", "—", "—"] and o["msign"] == ["+0.10배", "−0.40배", "0.00배"]
    assert o["usd"] == ["$1,140", "$3.00", "$10,000", None, None, None, "$1,234,500"]
    assert o["share"] == ["1% 미만", "1% 미만", "1%", "12%", "50%", "99%", "99% 넘음", "99% 넘음", "—", "—"]
    assert o["out"] == ["100번 중 1번도 안 됩니다", "100번 중 61번입니다", "100번 중 99번이 넘습니다", "—"]
    sc = o["sc"]
    assert 0.05 <= sc["lo"] <= 0.36 and sc["hi"] >= 4.6 and [t["label"] for t in sc["ticks"]][:2] == ["1배", "4배 목표"]
    assert sc["p"] == sorted(sc["p"]) and 0 < sc["p"][0] and sc["p"][3] < 100 and sc["off"][0] == 0 and sc["off"][1] == 100 and sc["off"][2] == 0
    ats = [t["at"] for t in sc["ticks"]]
    assert all(abs(a - b) >= 17 for i, a in enumerate(ats) for b in ats[:i])             # no two tick labels sit on each other
    assert o["wide"]["lo"] == 0.05 and o["wide"]["hi"] <= 1000 and {"1배", "4배 목표"} <= {t[0] for t in o["wide"]["ticks"]}      # a wild range still keeps x1 and the goal
    assert o["none"]["lo"] == 0.5 and o["none"]["hi"] == pytest.approx(4.6) and [t for t in o["none"]["ticks"]][:2] == ["1배", "4배 목표"]    # no bar at all: the default axis
    assert o["norm"] == [None] * 5 and o["gate"] == ["wait", "wait"]


# ---------------------------------------------------------------- the static rules and the registration
def test_screen_files_and_static_rules():
    from candleague import dash as D
    js = open(os.path.join(STATIC, "js", "screens", "monthsim.js"), encoding="utf-8").read()
    css = open(os.path.join(STATIC, "scr", "monthsim.css"), encoding="utf-8").read()
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "document.write", "new Function", "eval(", "binance.com"):
        assert bad not in js, bad
    assert 'export const css = ["scr/kinds.css", "scr/monthsim.css"]' in js
    assert "js/screens/monthsim.js" in D.STATIC_FILES and "scr/monthsim.css" in D.STATIC_FILES and "scr/kinds.css" in D.STATIC_FILES
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsl\(", js) and not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsl\(", re.sub(r"/\*.*?\*/", "", css, flags=re.S))   # tokens only
    for m in re.finditer(r'fontSize: "([^"]+)"', js):
        assert m.group(1).startswith("var(--t-"), m.group(0)
    for m in re.finditer(r"font-size:\s*([^;}]+)", css):
        assert m.group(1).strip().startswith("var(--t-"), m.group(0)
    for m in re.finditer(r"font:\s*([^;}]+)", css):
        assert "var(--t-" in m.group(1), m.group(0)
    code = re.sub(r"/\*.*?\*/", "", re.sub(r"^\s*//.*$", "", js, flags=re.M), flags=re.S)
    assert not re.search(r"5,?000|1,000|\$\s*\d", code)                                                  # no start wallet (no dollar amount) is written in the screen
    # every selector of the stylesheet is scoped to this screen
    flat = re.sub(r"@media[^{]*\{", "", re.sub(r"/\*.*?\*/", "", css, flags=re.S))
    sels = [x.strip() for x in re.findall(r"([^{}]+)\{", flat) if x.strip()]
    assert len(sels) > 30 and all(p.strip().startswith(".scr.ms ") for sel in sels for p in sel.split(",")), [x for x in sels if not x.startswith(".scr.ms ")]
    assert os.path.exists(os.path.join(STATIC, "js", "screens", "monthsim.js"))


def _patched_static(tmp_path):
    """A copy of the static folder with the four registration snippets applied (a no-op for one the coordinator has already put in)."""
    dst = tmp_path / "static"
    shutil.copytree(STATIC, dst)
    app = (dst / "js" / "app.js").read_text(encoding="utf-8")
    find = (dst / "js" / "find.js").read_text(encoding="utf-8")
    applied = 'id: "monthsim"' not in app                        # False: the coordinator has registered the menu entry already
    if applied:
        a = '  {id: "decision", ko: "판정", group: "home"},\n'
        assert app.count(a) == 1
        app = app.replace(a, a + "  " + SNIPPETS["menu"] + "\n")
    if not re.search(r"\bmonthsim: \"[^\"]*\",\n  events: ", app):
        t = '  events: "발동 기록 (빠른'
        assert app.count(t) == 1
        app = app.replace(t, "  " + SNIPPETS["title"] + "\n" + t)
    if 'monthsim: "monthsim"' not in app:
        s = 'decision: "decision", '
        assert app.count(s) == 1
        app = app.replace(s, s + SNIPPETS["screen"] + " ")
    if not re.search(r"^  monthsim: \"", find, re.M):
        w = '  events: "발동 기록 빠른 손절'
        assert find.count(w) == 1
        find = find.replace(w, "  " + SNIPPETS["words"] + "\n" + w)
    (dst / "js" / "app.js").write_text(app, encoding="utf-8")
    (dst / "js" / "find.js").write_text(find, encoding="utf-8")
    return str(dst), app, find, applied


def test_registration_snippets(tmp_path):
    static, app, find, applied = _patched_static(tmp_path)
    menu = re.findall(r'\{id: "(\w+)", ko: "([^"]+)", group: "(\w+)"', re.search(r"const MENU = \[(.*?)\];", app, re.S).group(1))
    ids = [m[0] for m in menu]
    i = ids.index("monthsim")
    assert menu[i][1] == "한 달 시뮬"
    if applied:
        assert menu[i][2] == "home" and ids[i - 1] == "decision"                                                    # the snippet puts it in the 홈 group, right after 판정
    order = re.findall(r'\{id: "(\w+)", ko: "[^"]+"\}', re.search(r"const GROUPS = \[(.*?)\];", app, re.S).group(1))
    assert [m[2] for m in menu] == sorted([m[2] for m in menu], key=order.index)                                    # groups stay together
    assert re.search(r"const SCREENS = \{[^}]*\bmonthsim: \"monthsim\"", app)
    titles = re.search(r"const MENU_TITLE = \{(.*?)\};\s*/\*\*", app, re.S) or re.search(r"const MENU_TITLE = \{(.*?)\};\s*const", app, re.S)
    assert titles and re.search(r"\bmonthsim: \"한 달 시뮬 ", titles.group(1))
    assert re.search(r"^  monthsim: \"한 달 시뮬 ", find, re.M)
    node = _node()
    for f in ("app.js", "find.js"):
        r = subprocess.run([node, "--check", os.path.join(static, "js", f)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    # the screen mounts from the patched folder (its files are the same)
    o = _run(tmp_path, _doc(), SELS, static=static)
    assert len(o["sel"]["bars"]) == 4


def test_find_knows_the_screen(tmp_path):
    static, _app, _find, _applied = _patched_static(tmp_path)
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
F.setFindScreens([["decision", "판정"], ["monthsim", "한 달 시뮬"], ["versus", "메인 vs 대조"]].map(([id, ko]) => ({id, ko, group: "home", groupKo: "홈", title: ko})));
const q = (s) => F.search(s).filter((x) => x.kind === "screen").map((x) => x.id);
console.log(JSON.stringify({name: q("한 달 시뮬"), word: q("운 계산기"), eng: q("monthsim"), coin: q("동전 짝"), none: q("zzzz")}));
process.exit(0);
""")
    (tmp_path / "cfg.json").write_text(json.dumps({"static": static, "routes": {}, "local": {}, "doc": _doc()}, ensure_ascii=False))
    r = subprocess.run([_node(), str(tmp_path / "run.mjs"), str(tmp_path / "cfg.json")], capture_output=True, text=True, timeout=60, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr[-1500:]
    o = json.loads(r.stdout.strip().splitlines()[-1])
    assert o["name"][0] == "monthsim" and o["word"] == ["monthsim"] and o["eng"] == ["monthsim"] and "monthsim" in o["coin"] and o["none"] == []
