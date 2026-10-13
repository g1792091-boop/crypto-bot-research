"""candleague screens 실제 비용 / 시장 국면 / 신호 / 알림 기록 (js/screens/costs.js regime.js signals.js telegram.js + kit4.js, css scr/s4.css) and, once the coordinator
registers them, their menu / 찾기 entries.

Mounted for real under node on the DOM stand-in of test_candleague_rank_ui (text nodes only, like the browser's). The doc blocks are written by the real server modules
(costview.cost_views, signalview.signal_views, notify.record_sent / read_log) from hand-made worlds, and the tests read what reached the page:
  (a) full data per screen: the rule box first, the one sentence, the cards / table in order, the words, the limits; (b) the phone's card view; (c) the block absent:
  "데이터 준비 중" / "새 리그 전용" / "준비 중" with the rule box still there; (d) null numbers read "—" (or "확인 못 함" with its reason), never 0 / NaN / undefined / null;
  (e) the snapshot's wallet, never a typed-in $5,000; (f) the DeepSeek note both ways; (g) the 시장 국면 numbers (BTC 4h EMA50 trend, ATR% percentile of 200 bars) against
  candleague/rulex.py's own functions on the same bars, the forming bar left out, an unreachable / switched-off price feed as a calm box; (h) the telegram texts as text only.
Plus the static rules (text only, tokens only), the defaults equal to the server's, and the registration snippets (checked as soon as app.js has them)."""

from __future__ import annotations

import json
import math
import os
import random
import re
import shutil
import subprocess
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_candleague_costview as CT  # noqa: E402
import test_candleague_rank_ui as RANK  # noqa: E402
import test_candleague_riskview as RT  # noqa: E402
import test_candleague_signalview as ST  # noqa: E402
from candleague import costview as CV  # noqa: E402
from candleague import notify as N  # noqa: E402
from candleague import rulex as RX  # noqa: E402
from candleague import signalview as SV  # noqa: E402

STATIC = os.path.join(ROOT, "candleague", "static")
BAD = ("NaN", "undefined", "null", "Infinity", "[object")
NOW = ST.NOW
SCREENS = ("costs", "regime", "signals", "telegram")


# ---------------------------------------------------------------- hand-made blocks
def cost_block(eq=1000.0, ds=False):
    book, rows = {}, []
    for i, r in enumerate(("fq", "ld", "ldc", "fqc")):
        rows += [RT.row(f"a-{r}", r), RT.row(f"b-{r}", r)]
        book[f"a-{r}"] = [CT.ct(lev=20 + 5 * i), CT.ct(side=-1, exit_=99.0, roe=0.19, lev=20), CT.ct(exit_=98.0, roe=-0.21, lev=20)]
        book[f"b-{r}"] = [CT.ct(lev=30, roe=0.28)]
    rows.append(RT.row("d-fq", "fq", kind="ds"))
    book["d-fq"] = [CT.ct(margin=500.0, pnl=95.0)]
    return json.loads(json.dumps(CV.cost_views(book, rows, RT.LU, eq, ds), allow_nan=False))


def signal_block(ds=False):
    book, rows = ST.world()
    rows.append(RT.row("d-fq", "fq", kind="ds", opened=ST.op("BTCUSDT", 1, NOW - ST.H)))
    return json.loads(json.dumps(SV.signal_views(book, rows, RT.LU, NOW, ds), allow_nan=False))


def telegram_block(tmp_path, n=3):
    snap = tmp_path / "snap"
    snap.mkdir(exist_ok=True)
    texts = ["📊 아침 요약 · 후보 리그\n\n빠른 손절 +1.2%\n10/13 09:00 KST", "🔄 새로 시작 · 후보 리그\n\n새 기록", "🚨 후보 리그 파산 · 도지 봇 15분\n\n잔고 $10 아래", "⚠ 후보 리그 경고등 · 도지 봇 15분\n\n알림일 뿐"]
    for i in range(n):
        N.record_sent(str(snap), texts[i % 4], NOW + i * 60_000)
    return json.loads(json.dumps(N.read_log(str(snap)), allow_nan=False))


def doc(costs="full", signals="full", telegram="full", equity0=1000, lineup=True, accounts=True, ds=False, tmp_path=None) -> dict:
    d = {"generated_ms": NOW - 60_000, "done_ms": NOW, "start_ms": RT.T0, "started_ms": RT.T0, "judge": {}, "ds_money": False, "watch": {"checkpoints": [], "pools": {}},
         "accounts": [{"id": "core-X-1h-1-fq", "role": "fq", "kind": "core", "name": "X", "tf": "1h", "trades": 5, "wins": 3, "mean_ret": 0.01, "wallet": 1000.0,
                       "max_dd": 0.02, "bust": False, "open": None}]}
    if not accounts:
        del d["accounts"]
    if equity0 is not None:
        d["equity0"] = equity0
    if lineup:
        d["lineup"] = [{"role": k["role"], "suffix": k["suffix"], "label_ko": k["label_ko"], "short_ko": k["short_ko"], "accounts": 12} for k in RT.LU]
    for key, val, make in (("costs", costs, lambda: cost_block(ds=ds)), ("signals", signals, lambda: signal_block(ds=ds)), ("telegram", telegram, lambda: telegram_block(tmp_path))):
        if val == "full":
            if key != "telegram" or tmp_path is not None:
                d[key] = make()
        elif val is not None:
            d[key] = val
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
const M = await import(`file://${S}/js/screens/${cfg.screen}.js`);
if (cfg.call) { console.log(JSON.stringify(M[cfg.call.fn](...cfg.call.args))); process.exit(0); }
const el = document.createElement("div");
el.dataset.screen = cfg.screen;
document.body.appendChild(el);
const ctx = {params: {name: cfg.screen, arg: null, query: {}}, alive: () => true, signal: null,
  api: async (p) => {
    if (cfg.apiFail) throw Object.assign(new Error("down"), {status: 0});
    const q = new URLSearchParams(String(p).split("?")[1] || "");
    return JSON.parse(JSON.stringify(cfg.klines ? cfg.klines[q.get("coin")] ?? null : {}));
  },
  meta: () => LK.getMeta(), onLeague: (fn) => { if (doc) fn(doc); }, onLive: () => () => {}, onPositions: () => () => {},
  every: () => {}, css: async () => null, wide() {}, setTitle() {}, setQuery() {}, href: (n, a) => `#/${n}${a ? "/" + a : ""}`};
await M.mount(el, ctx);
for (let i = 0; i < 4; i++) await new Promise((r) => setTimeout(r, 10));
const out = {text: txt(el), css: M.css, cls: el.className, sel: {}, rulesDefault: M.RULES_DEFAULT || M.RULES};
for (const [k, sel] of Object.entries(cfg.sels || {})) {
  out.sel[k] = el.querySelectorAll(sel).map((n) => ({t: txt(n), d: {...n.dataset}, c: n.className, a: Object.fromEntries(n.attrs)}));
}
console.log(JSON.stringify(out));
process.exit(0);
"""


def run(tmp_path, screen, d, sels=None, local=None, **extra) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    (tmp_path / "shim.mjs").write_text(RANK.SHIM)
    (tmp_path / "run.mjs").write_text(RUNNER)
    cfg = {"static": STATIC, "routes": {}, "local": local or {}, "doc": d, "sels": sels or {}, "screen": screen, **extra}
    (tmp_path / "cfg.json").write_text(json.dumps(cfg, ensure_ascii=False))
    r = subprocess.run([node, str(tmp_path / "run.mjs"), str(tmp_path / "cfg.json")], capture_output=True, text=True, timeout=120, cwd=str(tmp_path))
    assert r.returncode == 0, (r.stdout[-600:], r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def no_junk(text: str) -> None:
    for bad in BAD:
        assert bad not in text, bad


SELS = {"rules": "ol.kd-rules li", "big": ".kd-hero .dl-vbig", "line": ".kd-hero .dl-vline", "plates": ".plate", "legend": "dl.kd-legend dt", "limits": "ul.kd-list li",
        "rows": "tr.kd-row", "cards": "article.kd-kcard", "pills": ".pp", "seg": ".seg button"}


def is_blank(o):
    return not o["sel"]["rows"] and not o["sel"]["cards"]


# ---------------------------------------------------------------- 실제 비용
def test_costs_full_data_rules_first_then_the_sentence_then_the_table(tmp_path):
    d = doc(tmp_path=tmp_path)
    c = d["costs"]
    o = run(tmp_path, "costs", d, SELS)
    page = o["text"]
    assert o["css"] == ["scr/kinds.css", "scr/s4.css"] and "kd" in o["cls"].split()
    assert [x["t"] for x in o["sel"]["rules"]] == c["rules_ko"] and len(o["sel"]["rules"]) == 5
    assert page.index("이 화면은 무엇인가요") < page.index("한 줄 결론") < page.index("비용이 깎은 몫") < page.index("낱말 뜻") < page.index("이 숫자의 한계")
    assert o["sel"]["big"][0]["t"] == c["headline_ko"] and c["headline_ko"].startswith("빠른 손절: 추정 비용은")
    rows = o["sel"]["rows"]
    assert len(rows) == 5 and rows[0]["d"]["suffix"] == "-fq" and rows[-1]["d"]["pooled"] == "1"               # four kinds + the sum
    first = rows[0]["t"]
    assert "빠른 손절" in first and "실전 후보" in first and "배수 평균" in first and "수수료 · 펀딩" in first and "미끄러짐" in first
    assert re.search(r"\d+(\.\d)?%", first) and "$" in first and "vs" in first and "건 /" in first                 # the rt %, the dollars, cost vs net ROE, n of n
    heads = " ".join(x["t"] for x in o["sel"]["plates"])
    assert "비용이 깎은 몫" in heads
    assert page.count("추정") >= 8 and "총손익" in page                                                          # every figure is labelled 추정
    for w in ("수수료", "미끄러짐(슬리피지)", "펀딩비", "증거금 대비", "총손익", "추정"):
        assert w in [x["t"] for x in o["sel"]["legend"]], w
    no_junk(page)
    assert "5,000" not in page and "$1,000" in page


def test_costs_card_view_and_table_view(tmp_path):
    d = doc(tmp_path=tmp_path)
    o = run(tmp_path, "costs", d, SELS, local={"cl-costs-view": json.dumps("card")})
    assert is_blank(o) is False and not o["sel"]["rows"] and len(o["sel"]["cards"]) == 5 and [b["t"] for b in o["sel"]["seg"]] == ["표", "카드"]
    first = o["sel"]["cards"][0]
    assert "kd-live" in first["c"].split() and "빠른 손절" in first["t"] and "왕복 비용" in first["t"] and "총손익 대비 비용" in first["t"] and "거래 한 번 비용 vs 평균 순 ROE" in first["t"]
    no_junk(o["text"])
    o = run(tmp_path, "costs", d, SELS, local={"cl-costs-view": json.dumps("table")})
    assert len(o["sel"]["rows"]) == 5 and not o["sel"]["cards"]


def test_costs_cannot_derive_reads_as_dashes_and_reasons(tmp_path):
    book = {"p0-fq": [CT.ct(side=1, exit_=98.0, roe=-0.21)]}                                              # a loss: gross <= 0, net ROE <= 0
    b = json.loads(json.dumps(CV.cost_views(book, CT.rows_for(("fq", "ld")), RT.LU, 1000.0)))
    o = run(tmp_path, "costs", doc(costs=b), SELS)
    fq = o["sel"]["rows"][0]["t"]
    assert "확인 못 함" in fq and "총손익" in fq and "평균 순 ROE가 0 이하" in fq
    no_junk(o["text"])
    nul = json.loads(json.dumps(CV.cost_views({}, CT.rows_for(("fq", "ld")), RT.LU, 1000.0)))             # no trades at all: dashes, never 0
    o = run(tmp_path, "costs", doc(costs=nul), SELS)
    no_junk(o["text"])
    assert all("—" in r["t"] for r in o["sel"]["rows"]) and "0건 / 0건" in o["sel"]["rows"][0]["t"] and "확인 못 함" in o["sel"]["rows"][0]["t"]
    only = {"kinds": [{"role": "fq", "suffix": "-fq", "name_ko": "빠른 손절"}]}                           # a kind that is nothing but a name
    o = run(tmp_path, "costs", doc(costs=only), SELS)
    no_junk(o["text"])
    assert len(o["sel"]["rows"]) == 1 and "빠른 손절" in o["text"]


def test_costs_wallet_and_deepseek_notes(tmp_path):
    assert "$2,500" in run(tmp_path, "costs", doc(costs=cost_block(eq=2500.0), equity0=2500))["text"]
    o = run(tmp_path, "costs", doc(equity0=None, tmp_path=tmp_path))
    assert "시작하는 모의 계좌" not in o["text"] and "모의 계좌입니다 (가상 돈)" in o["text"]
    assert "이 숫자는 딥시크를 뺀 후보만으로 계산했습니다" in run(tmp_path, "costs", doc(ds=False, tmp_path=tmp_path))["text"]
    o = run(tmp_path, "costs", doc(ds=True, tmp_path=tmp_path))
    assert "이 숫자에는 딥시크 계좌도 들어 있습니다" in o["text"] and "딥시크를 뺀 후보만으로" not in o["text"]


# ---------------------------------------------------------------- 신호
def test_signals_full_data(tmp_path):
    d = doc(tmp_path=tmp_path)
    s = d["signals"]
    o = run(tmp_path, "signals", d, {**SELS, "coinrows": "tr.sg-row", "sides": ".side"})
    page = o["text"]
    assert [x["t"] for x in o["sel"]["rules"]] == s["rules_ko"] and "진입" in s["rules_ko"][0] and "전략의 조건이 지금 켜져 있는지는 아닙니다" in page
    assert o["sel"]["big"][0]["t"] == s["headline_ko"] and "‘진입’을 보여 줍니다" in o["sel"]["line"][0]["t"]
    plates = [p["t"] for p in o["sel"]["plates"]]
    assert plates.index("코인별 마지막 진입") < plates.index("종류별 진입 개수") < plates.index("낱말 뜻")
    rows = o["sel"]["coinrows"]
    assert [r["d"]["coin"] for r in rows] == ["BTC", "ETH", "SOL", "DOGE", "LTC", "BCH"]
    btc, eth = rows[0]["t"], rows[1]["t"]
    assert "롱" in btc and "5시간 전" in btc and "이미 닫힘" in btc and "같은 순간 2개 계좌" in btc                    # the newest BTC entry of 빠른 손절
    assert "숏" in eth and "2시간 전" in eth and "아직 열려 있음" in eth
    assert "진입 기록 없음" in rows[3]["t"] or "진입 기록 없음" in rows[5]["t"]
    assert "빠른 손절 (실전 후보)" in page and "(대조)" in page and "가장 최근 (모든 종류)" in page
    counts = o["sel"]["rows"]
    assert len(counts) == 4 and counts[0]["d"]["suffix"] == "-fq" and "4건" in counts[0]["t"] and "5건" in counts[0]["t"] and "1개" in counts[0]["t"]
    no_junk(page)


def test_signals_phone_cards_and_absent(tmp_path):
    o = run(tmp_path, "signals", doc(tmp_path=tmp_path), {**SELS, "coincards": "article.sg-coin"}, local={"cl-signals-view": json.dumps("card")})
    assert len(o["sel"]["coincards"]) == 6 and "BTC" in o["sel"]["coincards"][0]["t"] and "5시간 전" in o["sel"]["coincards"][0]["t"] and len(o["sel"]["cards"]) == 10
    no_junk(o["text"])
    assert "이 숫자는 딥시크를 뺀 후보만으로 계산했습니다" in o["text"]
    assert "이 숫자에는 딥시크 계좌도 들어 있습니다" in run(tmp_path, "signals", doc(signals=signal_block(ds=True)))["text"]
    blank = json.loads(json.dumps(SV.signal_views({}, [RT.row("a-fq", "fq")], RT.LU, NOW)))
    o = run(tmp_path, "signals", doc(signals=blank), SELS)
    no_junk(o["text"])
    assert "아직 진입 기록이 없습니다" in o["text"] and "진입 기록 없음" in o["text"]


# ---------------------------------------------------------------- 알림 기록
def test_telegram_list(tmp_path):
    d = doc(tmp_path=tmp_path)
    o = run(tmp_path, "telegram", d, {**SELS, "msgs": "article.tg-msg", "regions": ".dl-region"})
    page = o["text"]
    msgs = o["sel"]["msgs"]
    assert len(msgs) == 3
    assert [m["d"]["kind"] for m in msgs] == [m["kind"] for m in d["telegram"]["messages"]]                         # newest first, as the server writes them
    first = msgs[0]["t"]
    assert re.search(r"\d\d/\d\d \d\d:\d\d KST", first) and ("요약" in first or "시작" in first or "파산" in first or "경고" in first) and "전체 보기" in first
    assert "최근 알림 3개" in o["sel"]["big"][0]["t"] and "한국 시각 오전 9시" in page and "보내지 못한 알림은 목록에 없습니다" in page
    no_junk(page)
    assert "5,000" not in page


def test_telegram_text_only_and_control_characters(tmp_path):
    t = {"cap": 50, "messages": [{"ms": NOW, "kind": "summary", "title": "📊 <b>제목</b>\x00", "text": "📊 <b>제목</b>\x00\x1b[31m\r\n<script>x</script>\n" + "가" * 5000},
                                 {"ms": NOW - 1, "kind": "weird", "title": "", "text": ""}, {"ms": "x", "text": "no time"}, "junk", {"text": "no ms"}]}
    o = run(tmp_path, "telegram", doc(telegram=t), {"msgs": "article.tg-msg", "body": "p.tg-body", "titles": "b.tg-title", "pills": ".pp"})
    assert len(o["sel"]["msgs"]) == 2                                                                           # the two usable messages only
    body = o["sel"]["body"][0]["t"]
    assert "\x00" not in body and "\x1b" not in body and "\r" not in body and len(body) <= 4000
    assert "<b>제목</b>" in o["sel"]["titles"][0]["t"] and "<script>" in body                                     # shown as text, never parsed
    assert o["sel"]["msgs"][1]["d"]["kind"] == "alert" and "경고" in o["sel"]["msgs"][1]["t"]                     # an unknown kind reads as 경고
    no_junk(o["text"])
    assert open(os.path.join(STATIC, "js", "screens", "telegram.js"), encoding="utf-8").read().count("innerHTML") == 0


def test_telegram_empty_and_absent(tmp_path):
    o = run(tmp_path, "telegram", doc(telegram={"cap": 50, "messages": []}), SELS)
    assert "아직 보낸 알림 기록이 없습니다" in o["text"] and "아직 보낸 알림이 없습니다" in o["text"] and len(o["sel"]["rules"]) == 3
    no_junk(o["text"])
    o = run(tmp_path, "telegram", doc(telegram=None), SELS)
    assert "데이터 준비 중" in o["text"] and "첫 알림" in o["text"] and len(o["sel"]["rules"]) == 3 and "새 리그 전용" not in o["text"]


# ---------------------------------------------------------------- the states of the doc-block screens
@pytest.mark.parametrize("screen,key,rules", (("costs", "costs", 5), ("signals", "signals", 4), ("telegram", "telegram", 3)))
def test_absent_old_league_and_no_snapshot(tmp_path, screen, key, rules):
    for d, need, notneed in ((doc(**{key: None}), ("데이터 준비 중",), ("새 리그 전용",)),
                             (doc(**{key: {"kinds": "x", "messages": "x"}}), ("데이터 준비 중",), ("새 리그 전용",)),            # malformed = absent
                             (doc(**{key: None}, lineup=False), ("새 리그 전용", "이전 리그"), ("데이터 준비 중",)),
                             (doc(**{key: None}, accounts=False), ("준비 중", "후보 리그 기록이 아직 없습니다"), ("새 리그 전용",)),
                             (None, ("준비 중",), ("새 리그 전용",))):
        o = run(tmp_path, screen, d, SELS)
        for t in need:
            assert t in o["text"], (screen, t, o["text"][:300])
        for t in notneed:
            assert t not in o["text"], (screen, t)
        assert len(o["sel"]["rules"]) == rules and "이 화면은 무엇인가요" in o["text"] and is_blank(o)
        no_junk(o["text"])


def test_empty_kinds_is_absent(tmp_path):
    for screen, key in (("costs", "costs"), ("signals", "signals")):
        o = run(tmp_path, screen, doc(**{key: {"kinds": []}}), SELS)
        assert "데이터 준비 중" in o["text"] and is_blank(o)


def test_default_rules_are_the_servers_rules(tmp_path):
    assert run(tmp_path, "costs", doc(costs=None), SELS)["rulesDefault"] == CV.cost_rules_ko()
    assert run(tmp_path, "signals", doc(signals=None), SELS)["rulesDefault"] == SV.signal_rules_ko()
    c = cost_block()
    c["rules_ko"] = ["첫째: 하나", "둘째: 둘"]
    assert [x["t"] for x in run(tmp_path, "costs", doc(costs=c), SELS)["sel"]["rules"]] == ["첫째: 하나", "둘째: 둘"]


# ---------------------------------------------------------------- 시장 국면
TF = 4 * 3600 * 1000
T_FIRST = 1_780_000_000_000 // TF * TF


def bars(seed, n=300, drift=0.0006, vol=0.01, last_flat=False):
    rnd = random.Random(seed)
    p, cols = 100.0, {k: [] for k in "tohlcv"}
    for i in range(n):
        o = p
        p = p * (1 + drift + rnd.gauss(0, vol) * (0.3 if last_flat and i == n - 1 else 1.0))
        hi, lo = max(o, p) * (1 + abs(rnd.gauss(0, vol / 2))), min(o, p) * (1 - abs(rnd.gauss(0, vol / 2)))
        for k, v in zip("tohlcv", (T_FIRST + i * TF, o, hi, lo, p, 1.0)):
            cols[k].append(v)
    return cols


def kl(cols, closed=True, extra=None):
    last_open = cols["t"][-1]
    return {"coin": "X", "tf": "4h", "generated_ms": last_open + TF + 1000 if closed else last_open + TF // 2, "bars": cols, "stale": False, **(extra or {})}


def reference(cols, closed=True):
    """The league's own functions on the same closed bars: (sign of the last BTC 4h bar, ATR% now, share of the last 200 below it, rulex's g2 verdict)."""
    n = len(cols["c"]) - (0 if closed else 1)
    c, hi, lo = (np.array(cols[k][:n], float) for k in "chl")
    ms, sign = RX.gate_g1_arrays(np.array(cols["t"][:n], np.int64) + TF, c)
    y, atr = None, []
    for i in range(n):
        tr = hi[i] - lo[i] if i == 0 else max(hi[i] - lo[i], abs(hi[i] - c[i - 1]), abs(lo[i] - c[i - 1]))
        y = tr if y is None else (1 - 1 / 14) * y + tr / 14
        atr.append(y / c[i])
    w = np.array(atr[-200:])
    return int(sign[-1]), float(atr[-1]), float(np.mean(w < w[-1])), RX.gate_g2_stamp(np.array(atr), n - 1)


def market(**over):
    out = {"BTCUSD": kl(bars(1, drift=0.002)), "ETHUSD": kl(bars(2)), "SOLUSD": kl(bars(3, vol=0.02), closed=False), "DOGEUSD": kl(bars(4)), "LTCUSD": {"unavailable": True, "bars": {}},
           "BCHUSD": kl(bars(5, n=120))}
    out.update(over)
    return out


def test_regime_numbers_equal_the_leagues_own_functions(tmp_path):
    m = market()
    A = run(tmp_path, "regime", None, call={"fn": "analyze", "args": [m, T_FIRST + 400 * TF]})
    by = {c["coin"]: c for c in A["coins"]}
    sign, atr, pct, g2 = reference(m["BTCUSD"]["bars"])
    assert A["btc"]["sign"] == sign == 1
    assert by["BTCUSD"]["atrPct"] == pytest.approx(atr, rel=1e-9) and by["BTCUSD"]["pct"] == pytest.approx(pct, abs=1e-12)
    assert (by["BTCUSD"]["band"] == "normal") == g2
    _s, atr, pct, g2 = reference(m["SOLUSD"]["bars"], closed=False)                                    # the forming bar is left out
    assert by["SOLUSD"]["atrPct"] == pytest.approx(atr, rel=1e-9) and by["SOLUSD"]["pct"] == pytest.approx(pct, abs=1e-12) and (by["SOLUSD"]["band"] == "normal") == g2
    _s, atr, pct, g2 = reference(m["ETHUSD"]["bars"])
    assert by["ETHUSD"]["pct"] == pytest.approx(pct, abs=1e-12) and by["ETHUSD"]["band"] == ("normal" if g2 else ("low" if pct < 0.2 else "high"))
    assert by["LTCUSD"]["ok"] is False and by["BCHUSD"]["ok"] is True and by["BCHUSD"]["pct"] is None and by["BCHUSD"]["band"] is None      # 120 bars: no percentile
    assert by["BTCUSD"]["closeMs"] == m["BTCUSD"]["bars"]["t"][-1] + TF
    # a downtrend and the cold EMA
    dn = run(tmp_path, "regime", None, call={"fn": "analyze", "args": [market(BTCUSD=kl(bars(7, drift=-0.003))), T_FIRST]})
    assert dn["btc"]["sign"] == reference(bars(7, drift=-0.003))[0] == -1
    cold = run(tmp_path, "regime", None, call={"fn": "trendOf", "args": [[1.0] * 50]})
    assert cold["sign"] is None and run(tmp_path, "regime", None, call={"fn": "trendOf", "args": [[1.0] * 51]})["sign"] == 0       # flat = 횡보, 50 bars = still cold


def test_regime_page(tmp_path):
    m = market()
    sels = {"rules": "ol.kd-rules li", "big": ".kd-hero .dl-vbig", "coins": "article.rg-coin", "words": "dl.kd-legend dt", "plates": ".plate", "bars": ".rg-bar", "pills": ".pp"}
    o = run(tmp_path, "regime", None, sels, klines=m)
    page = o["text"]
    assert o["css"] == ["scr/kinds.css", "scr/s4.css"] and len(o["sel"]["rules"]) == 4 and page.index("이 화면은 무엇인가요") < page.index("한 줄 결론") < page.index("BTC 4시간 추세 (g1)")
    assert o["sel"]["big"][0]["t"].startswith("BTC 4시간 추세는 상승입니다, ") and "개 코인 중" in o["sel"]["big"][0]["t"]
    assert "g1은 지금 롱만 통과시킵니다" in page and "EMA50" in page and "마지막 종가" in page
    coins = o["sel"]["coins"]
    assert [c["d"]["coin"] for c in coins] == ["BTC", "ETH", "SOL", "DOGE", "LTC", "BCH"] and len(o["sel"]["bars"]) == 6
    ltc, bch = coins[4]["t"], coins[5]["t"]
    assert "자료 없음" in ltc and "4시간 봉을 받지 못했습니다" in ltc and "—" in ltc
    assert "봉이 200개 미만" in bch and "—" in bch
    assert coins[0]["d"]["band"] in ("low", "normal", "high") and re.search(r"최근 200봉 중 하위 \d+% 위치", coins[0]["t"])
    assert any(b["a"]["aria-label"].startswith("최근 200봉 중 하위") for b in o["sel"]["bars"])
    for w in ("g1 BTC 추세 필터", "g2 변동성 필터", "ATR%", "EMA", "하위 N%"):
        assert w in [x["t"] for x in o["sel"]["words"]], w
    assert "하위 20%에서 상위 20% 사이" in page and "4시간 봉으로 계산" in page
    no_junk(page)


def test_regime_unreachable_off_and_partial_are_calm(tmp_path):
    o = run(tmp_path, "regime", None, {"rules": "ol.kd-rules li"}, klines={c: {"unavailable": True, "bars": {}} for c in ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")})
    assert "시장 자료 준비 중" in o["text"] and "다시 불러오기" in o["text"] and "리그 기록에는 영향이 없습니다" in o["text"] and len(o["sel"]["rules"]) == 4
    no_junk(o["text"])
    o = run(tmp_path, "regime", None, klines={c: {"off": True} for c in ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")})
    assert "꺼짐" in o["text"] and "실시간 시세가 꺼져 있어" in o["text"]
    o = run(tmp_path, "regime", None, apiFail=True, klines={})
    assert "시장 자료 준비 중" in o["text"] and "Error" not in o["text"]
    o = run(tmp_path, "regime", None, klines=market(BTCUSD={"unavailable": True, "bars": {}}))                  # no BTC: the trend is unknown, the coins still show
    assert "BTC 4시간 추세는 아직 알 수 없습니다" in o["text"] and "BTC 4시간 봉을 받지 못했습니다" in o["text"]
    no_junk(o["text"])


# ---------------------------------------------------------------- the static rules, the registration
def test_the_files_and_the_static_rules():
    from candleague import dash as D
    css = open(os.path.join(STATIC, "scr", "s4.css"), encoding="utf-8").read()
    for name in SCREENS + ("kit4",):
        js = os.path.join(STATIC, "js", "screens", f"{name}.js")
        src = open(js, encoding="utf-8").read()
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "document.write", "new Function", "eval(", "binance.com"):
            assert bad not in src, (name, bad)
        assert f"js/screens/{name}.js" in D._static_files()
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsl\(", src), name
        assert not re.search(r"\$\s?5,?000|5000", src), name
        for m in re.finditer(r'fontSize: "([^"]+)"', src):
            assert m.group(1).startswith("var(--t-"), m.group(0)
        if name != "kit4":
            assert 'export const css = ["scr/kinds.css", "scr/s4.css"]' in src
        subprocess.run([shutil.which("node") or "node", "--check", js], check=True) if shutil.which("node") else None
    assert "scr/s4.css" in D._static_files()
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsl\(", css) and not re.search(r"5000|5,000", css)
    for decl in re.findall(r"(?<![\w-])font(?:-size)?:[^;}]*", css):
        assert "var(--t-" in decl, decl
    for sel in re.findall(r"^([^\s{@/][^{]*)\{", css, re.M):
        for part in sel.split(","):
            assert part.strip().startswith(".scr.kd "), part


def test_registration_snippets_once_the_coordinator_added_them():
    app = open(os.path.join(STATIC, "js", "app.js"), encoding="utf-8").read()
    menu = re.findall(r'\{id: "(\w+)", ko: "([^"]+)", group: "(\w+)"', re.search(r"const MENU = \[(.*?)\];", app, re.S).group(1))
    ids = [m[0] for m in menu]
    want = {"costs": ("실제 비용", "info"), "regime": ("시장 국면", "trade"), "signals": ("신호", "trade"), "telegram": ("알림 기록", "info")}
    if not all(k in ids for k in want):
        pytest.skip("the screens are not registered in app.js yet: the coordinator adds the MENU / MENU_TITLE / SCREENS / find.js lines (see the report)")
    for k, (ko, grp) in want.items():
        assert (menu[ids.index(k)][1], menu[ids.index(k)][2]) == (ko, grp)
    assert [m[2] for m in menu] == sorted([m[2] for m in menu], key=["trade", "home", "study", "method", "info"].index)
    screens = re.search(r"const SCREENS = \{([^}]*)\}", app).group(0)
    titles = re.search(r"const MENU_TITLE = \{(.*?)\};\s*const SCREENS", app, re.S).group(1)
    find = open(os.path.join(STATIC, "js", "find.js"), encoding="utf-8").read()
    for k in want:
        assert f'{k}: "{k}"' in screens and re.search(rf"\b{k}: \"", titles) and re.search(rf"\b{k}: \"{want[k][0]} ", find)
