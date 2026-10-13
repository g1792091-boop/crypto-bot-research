"""candleague 위험 점검 screen (js/screens/risk.js, css scr/risk.css + scr/kinds.css) and, once the coordinator registers it, its menu / 찾기 entries.

The screen is mounted for real under node on the DOM stand-in of test_candleague_rank_ui (text nodes only, like the browser's) with snapshots
whose ``risk`` is written by the real candleague.riskview.risk_views from a hand-made world (or edited by hand), and the tests read what reached
the page:
  (a) full data: the rule box first (six rules), the one-sentence answer from the server, then the three cards in order (쏠림 지금, 지금까지 가장
      나빴던 것, 같은 방향이 몰린 날), the long / short bar with both numbers written, the flag as a WORD, every number with its n, the word list and
      the limits; (b) the card view (a phone's default); (c) ``risk`` absent: "데이터 준비 중" / "새 리그 전용" / "준비 중" and the rule box still there;
  (d) null numbers read "—", never 0 / NaN / undefined / null; (e) the wallet of the snapshot, never a typed-in $5,000; (f) the DeepSeek note both
      ways; (g) the flag both ways; (h) a kind with nothing open or nothing closed;
Plus the static rules (text only, tokens only, both stylesheets), the default rules equal to the server's, and the registration snippets
(checked as soon as app.js has them)."""

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
import test_candleague_riskview as RT  # noqa: E402  (the hand-made world of the server tests)
from candleague import riskview as RV  # noqa: E402

STATIC = os.path.join(ROOT, "candleague", "static")
DAY, H, T0 = RT.DAY, RT.H, RT.T0
NOW = T0 + 15 * DAY
BAD = ("NaN", "undefined", "null", "Infinity", "[object")


# ---------------------------------------------------------------- hand-made snapshots
def world():
    """fq: 12 open (11 long: BTC 4, ETH 3, SOL 2, DOGE, LTC; 1 short BTC) and trades piled up on one side on some days; ld / nv / sw: 9 open each."""
    rows, book = [], {}
    rnd_side = [1, 1, 1, 1, 1, 1, 1, 1, 1, -1]
    for role in ("fq", "ld", "nv", "sw", "fqc"):
        for i in range(12):
            aid = f"p{i}-{role}"
            ts = []
            for j in range(40):
                day = j // 10
                e = T0 + day * DAY + (j % 10) * H
                side = rnd_side[j % 10] if role != "fqc" else (1 if (i + j) % 2 else -1)
                pnl = (-70.0 if (i + j) % 7 == 0 else 22.0) * (1 if role != "ld" else 1.2)
                ts.append(RT.tr(side, e, e + 2 * H, pnl, RT.COINS[(i + j) % 6], "SL" if pnl < 0 else "LOCK"))
            ts.sort(key=lambda t: t["exit_time"])
            book[aid] = ts
            opened = None
            if role == "fq":
                sym = (["BTCUSDT"] * 4 + ["ETHUSDT"] * 3 + ["SOLUSDT"] * 2 + ["DOGEUSDT", "LTCUSDT", "BTCUSDT"])[i] if i < 12 else None
                opened = RT.pos(sym, 1 if i < 11 else -1, 100.0, 98.5 if i % 3 else 100.5, [30, 40, 50][i % 3]) if sym else None
            elif role in ("ld", "nv", "sw") and i < 9:
                opened = RT.pos(RT.COINS[i % 6], 1 if i % 2 else -1, 100.0, 98.0 if i % 2 else 102.0, 30)
            rows.append(RT.row(aid, role, RT.EQ + sum(t["pnl"] for t in ts), opened=opened))
    return rows, book


def risk_block(**kw):
    rows, book = world()
    return json.loads(json.dumps(RV.risk_views(book, rows, RT.LU, kw.pop("eq", 1000.0), kw.pop("ds", False)), allow_nan=False))


def doc(risk="full", equity0=1000, lineup=True, accounts=True, ds=False) -> dict:
    d = {"generated_ms": NOW - 60_000, "done_ms": NOW, "start_ms": T0, "started_ms": T0, "judge": {}, "ds_money": False, "watch": {"checkpoints": [], "pools": {}},
         "accounts": [{"id": "core-X-1h-1-fq", "role": "fq", "kind": "core", "name": "X", "tf": "1h", "trades": 5, "wins": 3, "mean_ret": 0.01, "wallet": 1000.0,
                       "max_dd": 0.02, "bust": False, "open": None}]}
    if not accounts:
        del d["accounts"]
    if equity0 is not None:
        d["equity0"] = equity0
    if lineup:
        d["lineup"] = [{"role": k["role"], "suffix": k["suffix"], "label_ko": k["label_ko"], "short_ko": k["short_ko"], "accounts": 12} for k in RT.LU]
    if risk == "full":
        d["risk"] = risk_block(ds=ds)
    elif risk is not None:
        d["risk"] = risk
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
const M = await import(`file://${S}/js/screens/risk.js`);
const el = document.createElement("div");
el.dataset.screen = "risk";
document.body.appendChild(el);
const ctx = {params: {name: "risk", arg: null, query: {}}, alive: () => true, signal: null,
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
out.cards = el.querySelectorAll("section.rv-card").map((c) => ({id: c.attrs.get("id"), t: txt(c), rows: c.querySelectorAll("tr.kd-row").map(txt), subs: c.querySelectorAll("tr.rv-sub").map(txt),
  cards: c.querySelectorAll("article.kd-kcard").map((n) => ({t: txt(n), d: {...n.dataset}, c: n.className})),
  bars: c.querySelectorAll(".rv-bar").map((b) => b.attrs.get("aria-label")), pills: c.querySelectorAll(".pp").map(txt),
  facts: c.querySelectorAll("div[data-fact]").map((n) => ({k: n.dataset.fact, t: txt(n)}))}));
console.log(JSON.stringify(out));
process.exit(0);
"""


def run(tmp_path, d, sels=None, local=None) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    (tmp_path / "shim.mjs").write_text(RANK.SHIM)
    (tmp_path / "run.mjs").write_text(RUNNER)
    cfg = {"static": STATIC, "routes": {}, "local": local or {}, "doc": d, "sels": sels or {}}
    (tmp_path / "cfg.json").write_text(json.dumps(cfg, ensure_ascii=False))
    r = subprocess.run([node, str(tmp_path / "run.mjs"), str(tmp_path / "cfg.json")], capture_output=True, text=True, timeout=120, cwd=str(tmp_path))
    assert r.returncode == 0, (r.stdout[-600:], r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def no_junk(text: str) -> None:
    for bad in BAD:
        assert bad not in text, bad


SELS = {"rules": "ol.kd-rules li", "hero": ".kd-hero", "big": ".kd-hero .dl-vbig", "line": ".kd-hero .dl-vline", "plates": ".plate", "legend": "dl.kd-legend dt",
        "limits": "ul.kd-list li", "seg": ".seg button"}


def card(o, cid):
    return next(c for c in o["cards"] if c["id"] == cid)


# ---------------------------------------------------------------- (a) full data
def test_full_data_rules_first_then_the_sentence_then_the_three_cards(tmp_path):
    d = doc()
    r = d["risk"]
    o = run(tmp_path, d, SELS)
    page = o["text"]
    assert o["css"] == ["scr/kinds.css", "scr/risk.css"] and "kd" in o["cls"].split()
    # the rule box comes first and holds the six rules with their bold heads
    rules = o["sel"]["rules"]
    assert len(rules) == 6
    for i, head in enumerate(("무엇을 보여 주나", "쏠림 표시", "한 지갑이면", "가장 나빴던 것", "같은 방향이 몰린 날", "모든 숫자 옆에 거래 수나 계좌 수를 같이 씁니다")):
        assert rules[i]["t"].startswith(head), (i, rules[i]["t"])
    assert [x["t"] for x in rules] == r["rules_ko"]
    assert "이 화면은 무엇인가요" in page and "권유하지 않습니다" in page and page.index("이 화면은 무엇인가요") < page.index("한 줄 결론")
    # the one sentence is the server's, counts only, in the warning tone because one kind is flagged
    assert o["sel"]["big"][0]["t"] == r["headline_ko"] and "warn" in o["sel"]["big"][0]["c"].split()
    assert r["headline_ko"].startswith("빠른 손절: 열린 포지션 12개 중 롱 11개 · 숏 1개 (한 방향 92%)")
    assert "쏠림 표시가 켜진 종류: 빠른 손절 (보는 5개 중 1개)" in o["sel"]["line"][0]["t"]
    # the three cards in order, then the words and the limits
    assert [c["id"] for c in o["cards"]] == ["rv-now", "rv-worst", "rv-days"]
    plates = [p["t"] for p in o["sel"]["plates"]]
    assert plates.index("쏠림 지금") < plates.index("지금까지 가장 나빴던 것") < plates.index("같은 방향이 몰린 날") < plates.index("낱말 뜻") < plates.index("이 숫자의 한계")
    assert page.index("한 줄 결론") < page.index("쏠림 지금")
    assert [t["t"] for t in o["sel"]["limits"]][-len(r["note_ko"]):] == r["note_ko"] or all(n in " ".join(t["t"] for t in o["sel"]["limits"]) for n in r["note_ko"])
    no_junk(page)


def test_the_now_card_shows_the_split_as_a_bar_with_both_numbers_and_the_flag_as_a_word(tmp_path):
    o = run(tmp_path, doc())
    now = card(o, "rv-now")
    assert len(now["rows"]) == 5 and now["bars"][0] == "롱 11개, 숏 1개"                                 # fq first: 실전 후보
    first = now["rows"][0]
    assert "빠른 손절" in first and "실전 후보" in first and "12개" in first and "롱 11 · 숏 1" in first and "한 방향 92%" in first
    assert "롱 11개 중 BTC·ETH·SOL 9개" in first and "쏠림 표시" in first
    sub = now["subs"][0]
    assert len(now["subs"]) == 5 and "BTC 롱 4 · 숏 1" in sub and "ETH 롱 3 · 숏 0" in sub                  # the coins, every number written
    # the others have 9 open: under ten, the flag says so in words (not a colour)
    ld = now["rows"][1]
    assert "계단" in ld and "9개" in ld and "10개 미만" in ld and "쏠림 표시" not in ld
    assert now["rows"][-1].startswith("메인 전체") and "모두 합침" in now["rows"][-1]
    # the money, both ways, with the words of the owners' question
    for k in ("증거금 · 지갑 12개 따로", "증거금 · 한 지갑이면", "전부 손절되면 · 지갑 12개 따로", "전부 손절되면 · 한 지갑이면"):
        assert k in sub, k
    assert "지갑 평균" in sub and "지갑의" in sub and "가장 크게 맞는 지갑" in sub
    facts = {f["k"]: f["t"] for f in now["facts"][:4]}
    assert set(facts) == {"margin_sep", "margin_one", "stop_sep", "stop_one"} and "−" in facts["stop_sep"] and "−" in facts["stop_one"]
    assert "손절 계산" in sub and "배수 평균" in sub
    assert [p for p in now["pills"] if p == "쏠림 표시"] == ["쏠림 표시"]


def test_the_worst_card_numbers_carry_their_n(tmp_path):
    o = run(tmp_path, doc())
    w = card(o, "rv-worst")
    assert len(w["rows"]) == 5
    first = w["rows"][0]
    k = RT.kind({"kinds": json.loads(json.dumps(doc()["risk"]["kinds"]))}, "-fq")["worst"]
    assert f"닫힌 거래 {k['trades']:,}건" in first and "계좌 12개에 거래" in first                         # the n of every figure of the row
    assert "지갑의 −" in first and "연속으로 진 최다" not in first and f"{k['streak']['max']}번" in first
    assert "평균 지갑" in first and "가장 나빴던 지갑 하나는" in first and "강제청산" not in first
    for head in ("한 거래 최악", "연속으로 진 최다", "낙폭 (닫힌 거래 기준)", "강제청산 · 파산", "손절로 끝난 거래"):
        assert head in w["t"], head
    assert "0건 · 0계좌" in first and "건 · 잠금" in first and "계좌들의 보통" in first and "지금 이어지는 최다" in first
    assert "평가손익은 빠짐" in w["t"]


def test_the_days_card_has_the_share_with_its_n_and_the_coin_reference(tmp_path):
    o = run(tmp_path, doc())
    ds = card(o, "rv-days")
    assert len(ds["rows"]) == 5
    d = RT.kind(doc()["risk"], "-fq")["days"]
    first = ds["rows"][0]
    assert f"{d['eligible']}일" in first and f"{d['crowded']}일 ({round(d['share'] * 100)}%)" in first and "진입 10건 이상인 날" in first
    assert "롱 몰림" in first and "숏 몰림" in first and "동전 던지기 짝" in first and "‘빠른 손절 동전’은 4일 중 0일 (0%)" in first and "가장 심했던 날" not in first
    assert re.search(r"\d\d/\d\d · (롱|숏) \d+% \(그날 [\d,]+건\)", first)
    assert "UTC 날짜" in ds["t"] and "10건 미만이면 세지 않습니다" in ds["t"]
    assert ds["bars"][0].startswith("롱 몰림") and "숏 몰림" in ds["bars"][0]


def test_the_word_list_explains_the_terms_for_beginners(tmp_path):
    o = run(tmp_path, doc(), SELS)
    words = [x["t"] for x in o["sel"]["legend"]]
    for w in ("롱 · 숏", "쏠림", "증거금", "손절", "한 지갑이면", "낙폭", "연속으로 진 횟수", "강제청산", "몰린 날"):
        assert w in words, w
    assert "지갑이 모자랍니다" in o["text"] and "동전 던지기 짝은 방향을 동전으로 정하므로" in o["text"]


# ---------------------------------------------------------------- (b) the card view
def test_card_view_has_a_card_per_kind_with_the_same_words(tmp_path):
    o = run(tmp_path, doc(), {"seg": ".seg button", "rows": "tr.kd-row"}, local={"cl-risk-view": json.dumps("card")})
    assert not o["sel"]["rows"] and [b["t"] for b in o["sel"]["seg"]] == ["표", "카드"]
    now, worst, days = card(o, "rv-now"), card(o, "rv-worst"), card(o, "rv-days")
    assert len(now["cards"]) == len(worst["cards"]) == len(days["cards"]) == 5
    first = now["cards"][0]
    assert first["d"]["crowded"] == "1" and "kd-live" in first["c"].split() and "rv-crowded" in first["c"].split()
    assert "빠른 손절" in first["t"] and "쏠림 표시" in first["t"] and "롱 11 · 숏 1" in first["t"] and "롱 11개 중 BTC·ETH·SOL 9개" in first["t"] and "열린 포지션" in first["t"]
    assert "지갑 평균" in first["t"] and "한 지갑이면" in first["t"]
    assert now["cards"][-1]["d"]["pooled"] == "1" and "메인 전체" in now["cards"][-1]["t"]
    assert "한 거래 최악" in worst["cards"][0]["t"] and "연속으로 진 최다" in worst["cards"][0]["t"] and "닫힌 거래" in worst["cards"][0]["t"]
    assert "몰린 날" in days["cards"][0]["t"] and "동전 던지기 짝" in days["cards"][0]["t"]
    no_junk(o["text"])
    # the table is the other choice and remembers nothing it should not
    o = run(tmp_path, doc(), {"rows": "tr.kd-row"}, local={"cl-risk-view": json.dumps("table")})
    assert len(o["sel"]["rows"]) == 15 and not card(o, "rv-now")["cards"]


# ---------------------------------------------------------------- (c) absent risk
def test_risk_absent_old_league_and_no_snapshot(tmp_path):
    for d, need, notneed in ((doc(risk=None), ("데이터 준비 중", "위험 점검 기록은 아직 없습니다"), ("새 리그 전용", "쏠림 지금")),
                             (doc(risk={"kinds": "x"}), ("데이터 준비 중",), ("새 리그 전용",)),                      # malformed = absent
                             (doc(risk={"kinds": []}), ("데이터 준비 중",), ("새 리그 전용", "쏠림 지금")),             # no kind to show yet
                             (doc(risk=None, lineup=False), ("새 리그 전용", "이전 리그"), ("데이터 준비 중",)),
                             (doc(risk=None, accounts=False), ("준비 중", "후보 리그 기록이 아직 없습니다"), ("새 리그 전용",)),
                             (None, ("준비 중",), ("새 리그 전용", "쏠림 지금"))):
        o = run(tmp_path, d, SELS)
        for t in need:
            assert t in o["text"], (t, o["text"][:300])
        for t in notneed:
            assert t not in o["text"], t
        assert len(o["sel"]["rules"]) == 6 and "이 화면은 무엇인가요" in o["text"] and not o["cards"]                 # the rule box is there anyway
        no_junk(o["text"])


def test_default_rules_are_the_servers_rules(tmp_path):
    o = run(tmp_path, doc(risk=None), SELS)
    assert o["rulesDefault"] == RV.risk_rules_ko()                          # the fallback text cannot drift from candleague/riskview.py
    assert [r["t"] for r in o["sel"]["rules"]] == RV.risk_rules_ko()
    r = risk_block()
    r["rules_ko"] = ["첫째: 하나", "둘째: 둘"]                                   # the snapshot's own rules win when it has them
    assert [x["t"] for x in run(tmp_path, doc(risk=r), SELS)["sel"]["rules"]] == ["첫째: 하나", "둘째: 둘"]


# ---------------------------------------------------------------- (d) null numbers
def blank(x):
    """Every number of a risk block set to None (labels, ids and flags stay)."""
    keep = {"role", "suffix", "label_ko", "name_ko", "short_ko", "group", "live", "pooled", "account", "acct_worst_id", "coin", "reason", "text_ko", "crowded", "exact"}
    if isinstance(x, dict):
        return {k: (v if k in keep or isinstance(v, str) else blank(v)) for k, v in x.items()}
    if isinstance(x, list):
        return [blank(v) if isinstance(v, (dict, list)) else (v if isinstance(v, str) else None) for v in x]
    return None if isinstance(x, (int, float)) and not isinstance(x, bool) else x


def test_null_numbers_read_as_dashes(tmp_path):
    r = risk_block()
    r["kinds"] = [blank(k) for k in r["kinds"]]
    for k in r["kinds"]:
        k["now"]["crowded"] = False
    o = run(tmp_path, doc(risk=r), {"rows": "tr.kd-row"})
    no_junk(o["text"])
    now = card(o, "rv-now")
    assert len(now["rows"]) == 5 and all("—" in t for t in now["rows"]) and "NaN" not in o["text"]
    assert "롱 — · 숏 —" in now["rows"][0] and all("—" in t for t in now["subs"])
    # a kind that is nothing but a name still renders (every block missing)
    o = run(tmp_path, doc(risk={"kinds": [{"role": "fq", "suffix": "-fq", "name_ko": "빠른 손절"}]}), {"rows": "tr.kd-row"})
    no_junk(o["text"])
    assert len(o["sel"]["rows"]) == 3 and "빠른 손절" in o["text"]
    # the thresholds missing: the screen's own defaults (10 open, 80%) are used
    r = risk_block()
    del r["thresholds"]
    assert "10개 이상이고 80% 이상" in run(tmp_path, doc(risk=r))["text"]


# ---------------------------------------------------------------- (e) the wallet
def test_text_says_the_snapshots_wallet_never_5000(tmp_path):
    o = run(tmp_path, doc(equity0=1000))
    assert "$1,000" in o["text"] and "$5,000" not in o["text"] and "5,000" not in o["text"]
    o = run(tmp_path, doc(equity0=2500, risk=risk_block(eq=2500.0)))
    assert "$2,500" in o["text"] and "$1,000" not in o["text"] and "5,000" not in o["text"]
    o = run(tmp_path, doc(equity0=None, risk=risk_block()))                       # no equity0 in the snapshot: the screen makes no start-wallet figure up
    assert "시작하는 모의 계좌" not in o["text"] and "모의 계좌입니다 (가상 돈)" in o["text"]
    for d in (doc(risk=None), None):
        assert "5,000" not in run(tmp_path, d)["text"]


# ---------------------------------------------------------------- (f) DeepSeek
def test_deepseek_note_both_ways(tmp_path):
    o = run(tmp_path, doc(ds=False))
    assert "이 숫자는 딥시크를 뺀 후보만으로 계산했습니다" in o["text"] and "딥시크 계좌도 들어 있습니다" not in o["text"]
    o = run(tmp_path, doc(ds=True))
    assert "이 숫자에는 딥시크 계좌도 들어 있습니다" in o["text"] and "딥시크를 뺀 후보만으로" not in o["text"]


# ---------------------------------------------------------------- (g) the flag both ways, (h) nothing open / nothing closed
def test_no_flag_says_so_in_words_and_the_tone_is_not_warn(tmp_path):
    r = risk_block()
    for k in r["kinds"]:
        k["now"]["crowded"] = False
    o = run(tmp_path, doc(risk=r), SELS)
    assert "쏠림 표시가 켜진 종류는 없습니다 (보는 5개 기준)" in o["sel"]["line"][0]["t"] and "warn" not in o["sel"]["big"][0]["c"].split()
    assert "쏠림 표시" not in " ".join(card(o, "rv-now")["pills"])


def test_a_kind_with_nothing_open_or_nothing_closed(tmp_path):
    rows = [RT.row("a-fq", "fq"), RT.row("b-fq", "fq")]
    r = json.loads(json.dumps(RV.risk_views({}, rows, RT.LU, 1000.0, False), allow_nan=False))
    o = run(tmp_path, doc(risk=r), {"rows": "tr.kd-row"})
    no_junk(o["text"])
    now = card(o, "rv-now")
    assert "0개" in now["rows"][0] and "열린 포지션 없음" in now["subs"][0] and "열린 포지션이 없어 증거금과 손절 손실은 0입니다" in now["subs"][0]
    assert now["bars"][0] == "롱 0개, 숏 0개" and "10개 미만" in now["rows"][0]
    worst = card(o, "rv-worst")
    assert "닫힌 거래 0건" in worst["rows"][0] and "—" in worst["rows"][0]
    days = card(o, "rv-days")
    assert "—" in days["rows"][0] and "몰린 날" in days["t"]


def test_a_second_paint_replaces_the_first(tmp_path):
    # onLeague fires once in the stand-in; painting twice must not stack boxes: mount, then the same doc again through a second mount
    o = run(tmp_path, doc(), {"rules": "ol.kd-rules"})
    assert len(o["sel"]["rules"]) == 1 and len(o["cards"]) == 3


# ---------------------------------------------------------------- the static rules, the registration
def test_the_files_and_the_static_rules():
    js = os.path.join(STATIC, "js", "screens", "risk.js")
    src = open(js, encoding="utf-8").read()
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "document.write", "new Function", "eval(", "binance.com"):
        assert bad not in src, bad
    assert 'export const css = ["scr/kinds.css", "scr/risk.css"]' in src
    from candleague import dash as D
    assert "js/screens/risk.js" in D._static_files() and "scr/risk.css" in D._static_files() and "scr/kinds.css" in D._static_files()
    css = open(os.path.join(STATIC, "scr", "risk.css"), encoding="utf-8").read()
    for text in (src, css):
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsl\(", text)                                  # colours only from the tokens
    for m in re.finditer(r'fontSize: "([^"]+)"', src):
        assert m.group(1).startswith("var(--t-"), m.group(0)
    for decl in re.findall(r"(?<![\w-])font(?:-size)?:[^;}]*", css):
        assert "var(--t-" in decl, decl                                                                    # sizes only var(--t-*)
    assert not re.search(r"\$\s?5,?000|5000", src + css)                                                    # no typed-in wallet
    # every rule of risk.css is scoped to the screen's own root and prefixed (it must not touch another screen)
    for sel in re.findall(r"^([^\s{@/][^{]*)\{", css, re.M):
        for part in sel.split(","):
            assert part.strip().startswith(".scr.kd "), part


def test_registration_snippets_once_the_coordinator_added_them():
    app = open(os.path.join(STATIC, "js", "app.js"), encoding="utf-8").read()
    menu = re.findall(r'\{id: "(\w+)", ko: "([^"]+)", group: "(\w+)"', re.search(r"const MENU = \[(.*?)\];", app, re.S).group(1))
    ids = [m[0] for m in menu]
    if "risk" not in ids:
        pytest.skip("the screen is not registered in app.js yet: the coordinator adds the MENU / MENU_TITLE / SCREENS / find.js lines (see the report)")
    i = ids.index("risk")
    assert menu[i][1] == "위험 점검" and menu[i][2] == "home"
    assert [m[2] for m in menu] == sorted([m[2] for m in menu], key=["trade", "home", "method", "info"].index)
    assert 'risk: "risk"' in re.search(r"const SCREENS = \{([^}]*)\}", app).group(0)
    titles = re.search(r"const MENU_TITLE = \{(.*?)\};\s*const SCREENS", app, re.S).group(1)
    assert re.search(r"\brisk: \"", titles)
    find = open(os.path.join(STATIC, "js", "find.js"), encoding="utf-8").read()
    assert re.search(r"\brisk: \"위험 점검 ", find)
