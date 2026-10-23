"""The 실거래 site's existing screens with two DIFFERENT paper bots (owners 10-23, docs/vwap-bot-ko.md): 바이비트 follows the
추세판단 봇 (live-ac.db), WOO X Pro followed it until SWITCH and the 'VWAP 개선판' (vwap.db) since (tests/trend_vwap_world.py).

- each bot by its name (never "페이퍼 2" or a stop), a TIME exit in its own bot's words (the VWAP bot: 보유 한도 청산 and why);
- era separation both ways: the trend screens count only an executor's trades made while it followed the trend bot, the
  VWAP numbers only its trades on the VWAP bot (since its move);
- the 10-19 twin texts only for twins: two different bots are side by side with no stop test;
- the VWAP gates' reasons in their own categories, its rules from its own config (combo.gate_lines' words), the signals
  and missed screens by bot, its entry checks with the numbers its gates read (or why there are none);
- a one-paper world shows nothing new; the screens draw all of it in node (the tiny DOM)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

from paperbot import combo as C
from paperbot.dash.app import json_finite
from paperbot.dash.more import liveinsight as I
from paperbot.dash.more import livebots as L
from paperbot.dash.more import livejournal as J
from paperbot.dash.more import livemissed as M
from paperbot.dash.more import livepos as P
from paperbot.dash.more import livereplayref as X
from paperbot.dash.more import livereview as R
from paperbot.dash.more import livetape as TP
from paperbot.dash.more import livetrend as LT
from paperbot.dash.more import livewhy as Y
from tests import livebots_world as W
from tests import trend_vwap_world as TW
from tests import two_papers_world as TPW

NOW, MIN, H, DAY = TW.NOW, TW.MIN, TW.H, TW.DAY
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENS = os.path.join(ROOT, "paperbot", "dash", "static", "v4", "screens")
DOM = os.path.join(ROOT, "tests", "anasyn_dom.mjs")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    d = str(tmp_path_factory.mktemp("vwap") / "w")
    return TW.build(d), TW.more(d)


@pytest.fixture
def vw(world, monkeypatch):
    p, more = world
    monkeypatch.setattr(L, "paths_more", lambda env=None: more)
    return p, more


def _by(xs, key="id"):
    return {x[key]: x for x in xs}


def _entry(name):
    return TW.by(TW.VWAP + TW.TREND, name)[3]


# ---------------------------------------------------------------- 1 names
def test_each_paper_bot_is_named_by_its_name(vw):
    p, more = vw
    d = L.build(p, NOW)
    assert [(b["id"], b["short_ko"], b["label_ko"]) for b in d["papers"]] == [
        ("paper", "추세판단 봇", "추세판단 봇 (바이비트가 따라감)"), ("paper2", "VWAP 개선판", "VWAP 개선판 (WOO X Pro가 따라감)")]
    x = _by(d["execs"])
    assert (x["bybit"]["follows_ko"], x["mexc"]["follows_ko"]) == ("추세판단 봇", "VWAP 개선판")
    a = _by(d["accts"])
    assert a["mexc"]["follows_ko"] == "VWAP 개선판" and a["bybit"]["follows_ko"] == "추세판단 봇"
    h = [i["ko"] for i in I.health(p, NOW, more)["items"] if i["id"].startswith("paper")]
    assert h == ["추세판단 봇 심장 박동", "추세판단 봇 마지막 1분", "VWAP 개선판 봇 심장 박동", "VWAP 개선판 봇 마지막 1분"]
    cards = _by(P.build(p, more, NOW)["cards"])
    assert cards["mexc"]["follows_ko"] == "VWAP 개선판" and cards["bybit"]["follows_ko"] == "추세판단 봇"
    text = json.dumps(json_finite(d), ensure_ascii=False)
    for bad in ("페이퍼 2(연습)", "−35%", "2 ATR 봇"):
        assert bad not in text, bad


# ---------------------------------------------------------------- 2 TIME exit words by bot
def test_a_time_exit_says_what_its_own_bot_did(vw):
    p, more = vw
    trend_cfg = L.cfg_of(L.read_paper(p["paper"], L.ACCOUNT, NOW))
    vwap_cfg = L.cfg_of(L.read_paper(p["paper2"], L.ACCOUNT, NOW))
    assert L.exit_words("TIME", trend_cfg) == "감독 청산(시간 정리)"
    assert L.exit_words("TIME", vwap_cfg, "96봉(48시간) 지남") == "보유 한도 청산(96봉(48시간) 지남)"
    rows = L.trade_rows(p, NOW, more)["accts"]["paper2"]
    v1 = [r for r in (rows.get("rows") or rows.get("trades") or []) if r.get("symbol") == "BTCUSDT"]
    assert v1 and v1[0]["reason_ko"] == "보유 한도 청산(96봉(48시간) 지남)"
    tape = TP.build_list(p, NOW, bot="paper2")
    assert any(r["reason_ko"] == "보유 한도 청산(96봉(48시간) 지남)" for r in tape["rows"])
    assert "감독 청산(시간 정리)" not in json.dumps(tape, ensure_ascii=False)


# ---------------------------------------------------------------- 3 era separation, both ways
def test_trend_screens_count_only_the_trades_made_on_the_trend_bot(vw):
    p, more = vw
    pf = L.perf(p, NOW, more)["accts"]
    assert pf["bybit"]["stats"]["trades"] == 4                       # T1..T4 (OLD: before the trend bot's start)
    assert pf["mexc"]["stats"]["trades"] == 2                        # T1, T2 only: V3, V4, V6 are the VWAP bot's
    assert pf["mexc"]["era"] == {"other_ko": "VWAP 개선판", "now_other": True, "since": TW.SWITCH, "other_n": 3}
    assert "era" not in pf["bybit"]
    rows = _by(L.rank(p, NOW)["rows"], "strategy")
    # S3_CMO / F6_VWAP are members of both bots: a live trade counts where its paper trade was (paper first)
    assert rows["S3_CMO_SANDWICH"]["live"]["mexc"]["n"] == 1 and rows["F6_VWAP_FAIL"]["live"]["mexc"]["n"] == 0
    assert rows["F6_VWAP_FAIL"]["live"]["bybit"]["n"] == 1
    rv = _by(R.build(p, NOW, more, budget_s=0.2)["execs"])
    assert rv["mexc"]["n"] == 2 and rv["mexc"]["other"] == {"bot_ko": "VWAP 개선판", "now": True, "since": TW.SWITCH, "n": 3}
    assert rv["bybit"]["n"] == 4 and "other" not in rv["bybit"]
    xr = _by(X.build(p, NOW)["results"]["execs"])
    assert xr["mexc"]["record"]["n"] == 2 and xr["mexc"]["era"]["other_n"] == 3
    path = {a["id"]: a for a in I.goal(p, NOW, more)["path"]["actual"]}
    assert path["mexc"]["n"] == 2 and path["mexc"]["era"]["other_ko"] == "VWAP 개선판"
    fo = LT.build(p, NOW)["position"]["follow"]
    assert _by(fo)["mexc"] == {"id": "mexc", "name_ko": "WOO X Pro", "state": "other_bot", "bot_ko": "VWAP 개선판",
                               "ko": "VWAP 개선판을 따라가는 중"}
    assert _by(fo)["bybit"]["state"] == "follow"


def test_vwap_numbers_count_only_the_trades_made_on_the_vwap_bot(vw):
    p, more = vw
    g = _by(I.goal(p, NOW, more)["accts"])
    m = g["mexc"]
    assert m["era"]["from_ms"] == TW.SWITCH and m["era"]["bot_ko"] == "VWAP 개선판" and m["era"]["now_other"] is True
    assert m["scale"]["vwap"] is True and m["scale"]["checks"][0]["value"] == 3          # V3, V4, V6: never T1 / T2
    assert m["scale"]["checks"][1]["ko"] == "실거래 승률 67% (3번 중 2번)"
    assert m["light"]["n"] == 20 and m["light"]["min_win"] == 0.75                       # its own config's light
    assert m["weekday_ref_ko"] == I.VWAP_WEEKDAY_REF_KO and "1,718" in m["weekday_ref_ko"]
    assert "era" not in g["bybit"] and g["bybit"]["scale"].get("vwap") is None
    fees = _by(L.costs(p, NOW)["fees"]["execs"])
    assert fees["mexc"]["since_ko"] == "VWAP 개선판 따라간 때부터" and fees["mexc"]["since_ms"] == TW.SWITCH
    assert fees["mexc"]["since"]["n"] == 3 and fees["bybit"]["since"]["n"] == 4 and "since_ko" not in fees["bybit"]
    h2h = I.goal(p, NOW, more)["h2h"]
    live = {s["id"]: s["live"][0] for s in h2h["sides"]}
    assert live["paper2"]["n"] == 3 and live["paper"]["n"] == 2                          # each bot's trades since the move


# ---------------------------------------------------------------- 4 twins only keep the twin texts
def test_two_different_bots_are_side_by_side_not_a_stop_test(vw):
    p, more = vw
    _c, _f, paper, execs = L.sources(p, NOW)
    bots = L.paper_bots(p, paper, execs)
    assert L.twins(bots) is False
    c = L.compare_papers(bots)
    assert c["twin"] is False and c["shared"] is None and c["parted_rows"] == []
    assert c["words_ko"].startswith("두 봇 나란히: 매매법이 서로 달라요")
    h = I.goal(p, NOW, more)["h2h"]
    assert h["twin"] is False and h["review_ko"] == I.PLAIN_H2H_KO and h["live_since_ms"] == TW.SWITCH
    text = json.dumps(h, ensure_ascii=False)
    assert "11/3" not in text and "손절만" not in text
    why = Y.build(p, more, "paper2", "SOLUSDT", _entry("V3"), None, NOW)
    assert why["five_year"]["reason_ko"] == Y.REF_OTHER_KO.format(name="VWAP 개선판")


def test_the_twins_of_10_19_keep_their_words(tmp_path, monkeypatch):
    p = TPW.build(str(tmp_path / "w"))
    more = {**L.paths_more({}), "rule_db": str(tmp_path / "r.db"), "check_db": str(tmp_path / "c.db"), "improve_db": str(tmp_path / "i.db"),
            "combo_config": str(tmp_path / "no.json"), "combo2_config": str(tmp_path / "no2.json")}
    monkeypatch.setattr(L, "paths_more", lambda env=None: more)
    _c, _f, paper, execs = L.sources(p, TPW.NOW)
    bots = L.paper_bots(p, paper, execs)
    assert L.twins(bots) is True
    c = L.compare_papers(bots)
    assert c.get("twin") is not False and c["shared"] is not None
    assert I.goal(p, TPW.NOW, more)["h2h"]["review_ko"] == I.H2H_REVIEW_KO


# ---------------------------------------------------------------- 5 the VWAP gates' reasons
@pytest.mark.parametrize("why, cat, ko", [
    ("4시간 추세 반대: 상승 0·하락 3·중립 1", "vote_gate", "4시간 추세 반대 (VWAP 조건)"),
    ("변동성 높음: ATR 0.812% > 지난 30일 80% 위치 0.633%", "vol_high", "변동성 높음 (VWAP 조건)"),
    ("4시간 추세 판단을 못 읽음(진입 안 함): LTCUSDT 4h 봉을 못 받음", "trend_unread", "추세 판단 못 읽음"),
    ("변동성 판단에 쓸 30분봉을 못 읽음(진입 안 함): 끝난 봉을 아직 못 받음", "unread", "조건을 못 읽음"),
])
def test_gate_reasons_have_their_own_categories(why, cat, ko):
    assert L.why_cat("FILTERED", why) == (cat, ko)
    assert LT.BLOCK_OF[cat] in {"vote_gate", "vol_high", "unread"}


def test_signals_and_missed_switch_between_the_bots(vw):
    p, more = vw
    main = L.signals(p, NOW)
    assert main["bot"] == "paper" and [b["id"] for b in main["bots"]] == ["paper", "paper2"]
    s2 = L.signals(p, NOW, "paper2")
    assert s2["bot"] == "paper2" and s2["bot_ko"] == "VWAP 개선판"
    cats = {c["cat"]: c["n"] for c in s2["counts"]["week"]}
    assert cats["vote_gate"] == 1 and cats["vol_high"] == 1 and cats["trend_unread"] == 1 and cats["unread"] == 1
    vg = next(r for r in s2["rows"] if r["cat"] == "vote_gate")
    assert vg["why"] == "4시간 추세 반대: 상승 0·하락 3·중립 1" and vg["gates_ko"] == "4시간 하락(상승 0·하락 3·중립 1)"
    assert any(r["stage"] == "entered" and r.get("gates_ko", "").startswith("4시간 ") for r in s2["rows"])
    assert not any("gates_ko" in r for r in main["rows"])                               # the trend bot has no gates
    m2 = M.build(p, more, NOW, bot="paper2")
    assert m2["kind"] == "plain" and m2["bot_ko"] == "VWAP 개선판" and m2["note_ko"] == M.PLAIN_KO
    assert m2["filter_note_ko"] == M.PLAIN_FILTER_KO
    g = _by(m2["groups"])
    assert g["vote_gate"]["n"] == 1 and g["vol_high"]["n"] == 1 and g["exec"]["n"] == 1 and m2["counts"]["all"] == 8
    ex = next(r for r in m2["rows"] if r["grp"] == "exec")
    assert ex["symbol"] == "BCHUSDT" and ex["grp_ko"] == "WOO X Pro가 안 따라감" and ex["state"] == "closed"
    assert all(r["state"] == "none" for r in m2["rows"] if r["grp"] != "exec")         # no virtual result is made up
    one = M.build(p, more, NOW, bot="paper2", group="vote_gate")
    assert one["group"] == "vote_gate" and [r["grp"] for r in one["rows"]] == ["vote_gate"]
    mm = M.build(p, more, NOW)
    assert mm.get("kind") != "plain" and mm["bot"] == "paper" and len(mm["bots"]) == 2


# ---------------------------------------------------------------- 6 the second bot's rules
def test_settings_show_the_vwap_bots_own_rules(vw):
    p, more = vw
    s = L.settings(p, NOW)
    assert "gates" not in s["rules"]                                                     # the trend bot's: as before
    b = s["bots"][0]
    assert b["id"] == "paper2" and b["short_ko"] == "VWAP 개선판" and b["followers"] == ["WOO X Pro"]
    r = b["rules"]
    assert (r["leverage_btc"], r["leverage_alt"], r["margin"], r["max_loss_frac"]) == (30, 30, 0.4, 0.2)
    assert r["early_exit"] is None and r["max_hold_bars"] == 96 and r["stop"]["ko"] == "ATR 2배"
    want = C.gate_lines(C.ComboConfig(**TW.deploy("combo.vwap.json")))
    assert [g["ko"] for g in r["gates"]] == want                                         # the bot's own words
    assert [g["id"] for g in r["gates"]] == ["vote_gate", "vol_gate", "max_hold"]
    assert [g["strategy"] for g in b["groups"]] == ["F6_VWAP_FAIL", "S3_CMO_SANDWICH"]
    assert _by(s["execs"])["mexc"]["follows_ko"] == "VWAP 개선판"


# ---------------------------------------------------------------- 11 진입 근거 of a VWAP trade
def test_a_vwap_entry_shows_its_gates_numbers(vw):
    p, more = vw
    d = Y.build(p, more, "paper2", "SOLUSDT", _entry("V3"), None, NOW)
    assert d["state"] == "ok" and d["gate"] is True and d["bot_ko"] == "VWAP 개선판"
    assert d["signal"]["strategy_ko"] == "VWAP 복귀 실패"
    assert d["setting"] is None or d["setting"]["group"] is None                         # no A / B group on this bot
    ko = [c["ko"] for c in d["checks"]]
    assert "4시간 추세: 상승 3·하락 0·중립 1 → 롱 통과" in ko
    assert "변동성 30분 ATR 0.45% · 30일 80% 위치 0.62% → 통과" in ko
    assert "보유 한도 96봉 = 30분봉 48시간 / 1시간봉 96시간, 지나면 시장가 정리" in ko
    assert [c["id"] for c in d["checks"]] == ["weekend", "macro", "usopen", "vote", "vol", "one", "hold"]
    hold = d["checks"][-1]
    assert hold["info"] is True and hold["ok"] is None and hold["detail"] == {"bars": 96, "tf": "30m", "hold_ko": "48시간"}
    assert not any(c["id"] in ("chase", "member") for c in d["checks"])
    text = json.dumps(d, ensure_ascii=False)
    assert Y.REF_PAPER2_KO not in text and "A그룹" not in text and "B그룹" not in text
    cmo = Y.build(p, more, "paper2", "ETHUSDT", _entry("V6"), None, NOW)
    assert cmo["signal"]["strategy_ko"] == "CMO·샌드위치 캔들" and cmo["signal"]["tf"] == "1h"
    assert "4시간 추세: 상승 3·하락 0·중립 1 → 롱 통과" in [c["ko"] for c in cmo["checks"]]


def test_a_vwap_entry_before_the_gates_record_says_so(vw):
    p, more = vw
    d = Y.build(p, more, "paper2", "BTCUSDT", _entry("V1"), None, NOW)
    g = next(c for c in d["checks"] if c["id"] == "gates")
    assert g["ok"] is None and g["ko"] == "이 진입은 조건 기록 전이라 숫자가 없어요" == Y.GATES_NONE_KO
    assert not any(c["id"] in ("vote", "vol") for c in d["checks"])


def test_a_trend_entry_keeps_its_checks(vw):
    p, more = vw
    d = Y.build(p, more, "paper", "BTCUSDT", _entry("T1"), None, NOW)
    assert d["state"] == "ok" and "gate" not in d and "strategy_ko" not in d["signal"]
    assert not any(c["id"] in ("vote", "vol", "hold", "gates") for c in d["checks"])


# ---------------------------------------------------------------- the journal and the trades
def test_the_journal_tags_each_executor_event_with_its_bot(vw):
    p, more = vw
    ev = J.build(p, 72, NOW, more)["events"]
    skip = [e for e in ev if e["kind"] == "exec" and e["sub"] == "skip"]
    assert any(e["text"] == "WOO X Pro · BCH 롱 VWAP 개선판 진입을 안 따라갔어요" for e in skip)
    start = next(e for e in ev if e["id"] == f"x:mexc:start:{TW.SWITCH}")
    assert start["detail"].startswith("따라가는 페이퍼: VWAP 개선판 (")


# ---------------------------------------------------------------- one paper bot: nothing new
def test_one_paper_world_is_as_before(tmp_path, monkeypatch):
    p = W.build_world(str(tmp_path / "w"))
    more = {**L.paths_more({}), "rule_db": str(tmp_path / "r.db"), "check_db": str(tmp_path / "c.db"), "improve_db": str(tmp_path / "i.db"),
            "combo_config": str(tmp_path / "no.json"), "combo2_config": str(tmp_path / "no2.json")}
    monkeypatch.setattr(L, "paths_more", lambda env=None: more)
    sg = L.signals(p, W.NOW)
    assert "bots" not in sg and "bot" not in sg and sg == L.read_signals(p["paper"], L.ACCOUNT, W.NOW)
    assert L.signals(p, W.NOW, "paper2") == sg
    mm = M.build(p, more, W.NOW)
    assert "bots" not in mm and mm.get("kind") != "plain" and M.build(p, more, W.NOW, bot="paper2") == mm
    st = L.settings(p, W.NOW)
    assert not st.get("bots") and all("follows_ko" not in x for x in st["execs"])
    assert all("era" not in a for a in L.perf(p, W.NOW, more)["accts"].values())
    g = I.goal(p, W.NOW, more)
    assert g["h2h"] is None and all("era" not in a and "weekday_ref_ko" not in a for a in g["accts"])
    assert all("other" not in x for x in R.build(p, W.NOW, more, budget_s=0.2).get("execs") or [])
    assert all("since_ko" not in x for x in (L.costs(p, W.NOW).get("fees") or {}).get("execs") or [])
    assert all(f.get("state") != "other_bot" for f in ((LT.build(p, W.NOW).get("position") or {}).get("follow") or []))


# ---------------------------------------------------------------- the screens in node
def _node(body: str, data) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    mods = "".join(f"const {n} = await import('file://{os.path.join(SCREENS, f)}');\n" for n, f in (
        ("KIT", "livebots-kit.js"), ("SIG", "livebots-signals.js"), ("MS", "livebots-missed.js"), ("GO", "livebots-goal.js"),
        ("WHY", "livebots-why.js"), ("TR", "livebots-trend.js"), ("RV", "livebots-review.js"), ("MO", "livebots-more.js"),
        ("JU", "livebots-judge.js"), ("RK", "livebots-rank.js")))
    script = (f"const D = await import('file://{DOM}');\n{mods}const d = {json.dumps(data, ensure_ascii=False)};\n"
              "const tick = async () => { for (let i = 0; i < 4; i++) await new Promise((r) => setTimeout(r, 0)); };\n"
              "const shown = (n) => (n == null || n.hidden ? '' : n instanceof Text ? n.t : (n.childNodes || []).map(shown).join(' '));\n"
              "const text = (n) => shown(n).replace(/\\s+/g, ' ');\n"
              "const mkCtx = (map) => ({calls: [], api(u) { this.calls.push(u); const k = Object.keys(map).find((x) => u.startsWith(x));"
              " return Promise.resolve(map[k]); }, every() {}, watch() {}, alive: () => true, href: (n, a) => '#/' + n, track() {}});\n"
              + body)
    r = subprocess.run([node, "--input-type=module"], input=script, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def _bad(text):
    return [w for w in ("null", "undefined", "NaN", "Infinity", "[object") if w in text]


def test_screens_say_who_follows_which_bot(vw):
    p, more = vw
    papers = json_finite(L.build(p, NOW))["papers"]
    out = _node("""
const before = [TR.kickKo(), RV.kickKo(), KIT.mainFollowKo()];
KIT.setPapers(d.papers);
console.log(JSON.stringify({before, after: [TR.kickKo(), RV.kickKo(), KIT.mainFollowKo()],
  other: [TR.otherBotOf({follows_ko: "VWAP 개선판"}), TR.otherBotOf({follows_ko: "추세판단 봇"})],
  line: KIT.followLine(d.papers), acct: [KIT.acctKo("paper"), KIT.acctKo("paper2")],
  era: KIT.eraWords("WOO X Pro", {other_ko: "VWAP 개선판", now_other: true, since: d.sw, other_n: 3}),
  was: KIT.eraWords("바이비트", {other_ko: "VWAP 개선판", now_other: false, other_n: 2}),
  rv: RV.otherKo({bot_ko: "VWAP 개선판", now: true, since: d.sw, n: 3}),
  goal: GO.goalEraKo({id: "mexc", era: {other_ko: "VWAP 개선판", now_other: true, since: d.sw, other_n: 3, from_ms: d.sw, bot_ko: "VWAP 개선판"}})}));
""", {"papers": papers, "sw": TW.SWITCH})
    assert out["before"] == ["추세판단 봇 · 바이비트 · WOO X Pro가 따라가는 페이퍼(−50%)",
                             "2주 검토 · 추세판단 봇 · 바이비트 · WOO X Pro가 따라가는 페이퍼(연습)", None]
    assert out["after"] == ["추세판단 봇 · 바이비트가 따라가는 페이퍼(−50%)", "2주 검토 · 추세판단 봇 · 바이비트가 따라가는 페이퍼(연습)",
                            "바이비트가 따라가는"]
    assert out["other"] == ["VWAP 개선판", None]
    assert out["line"] == "바이비트 → 추세판단 봇 · WOO X Pro → VWAP 개선판" and out["acct"] == ["추세판단 봇", "VWAP 개선판"]
    assert out["era"] == "WOO X Pro는 10/22 14:00부터 VWAP 개선판을 따라가요 · 그 봇 거래 3번은 여기 안 셈"
    assert out["was"] == "바이비트는 한때 VWAP 개선판을 따라갔어요 · 그 봇 거래 2번은 여기 안 셈"
    assert out["rv"] == "10/22 14:00부터 VWAP 개선판을 따라가요 · 그 봇 거래 3번은 안 셈"
    assert out["goal"].startswith("WOO X Pro는 10/22 14:00부터 VWAP 개선판을 따라가요 · 필요한 승률과 돈 늘리기 기준은 그때부터의 거래로 셌어요")


def test_signals_and_missed_screens_draw_the_vwap_bot(vw):
    p, more = vw
    s2 = json_finite(L.signals(p, NOW, "paper2"))
    m2 = json_finite(M.build(p, more, NOW, bot="paper2"))
    out = _node("""
const sc = mkCtx({"/api/v4/livebots/signals": d.s2, "/api/v4/livebots/now": {pending: {state: "ok", waits: [], closes: []}}});
const sv = SIG.signalsView(sc);
const mc = mkCtx({"/api/v4/livebots/missed": d.m2});
const mv = MS.missedView(mc);
await tick();
console.log(JSON.stringify({sig: text(sv.el), miss: text(mv.el), calls: [sc.calls, mc.calls],
  urls: [SIG.signalsApi("paper"), SIG.signalsApi("paper2"), MS.missedUrl({span: "7d", group: "all", result: "all", bot: "paper"}),
    MS.missedUrl({span: "all", group: "one", result: "win", bot: "paper2", pgroup: "vote_gate"})],
  pr: [MS.plainResult({state: "none"}).text, MS.plainResult({state: "closed", win: true, roe: 0.03, reason_ko: "잠금 익절"}).text]}));
""", {"s2": s2, "m2": m2})
    sig, miss = out["sig"], out["miss"]
    assert not _bad(sig) and not _bad(miss), (_bad(sig), _bad(miss))
    for w in ("어느 봇의 신호", "추세판단 봇", "VWAP 개선판의 신호 · 한국 시간", "4시간 추세 반대 (VWAP 조건)", "변동성 높음 (VWAP 조건)",
              "조건이 읽은 값: 4시간 하락(상승 0·하락 3·중립 1)", "자기가 따라가는 페이퍼 봇이 진입한 것만"):
        assert w in sig, w
    for w in ("VWAP 개선판의 못 탄 신호를 왜 못 탔는지 그룹마다", "가상 결과 없음", "조건이 읽은 값: 4시간 하락(상승 0·하락 3·중립 1)",
              "4시간 추세 반대 (VWAP 조건) 1", "WOO X Pro가 안 따라감", "페이퍼 거래의 결과 (실행기는 안 탐 · 가상 아님)", M.PLAIN_KO,
              M.PLAIN_FILTER_KO, "전체 8"):
        assert w in miss, w
    assert "이겼을 신호" not in miss and "펀딩비" not in miss                       # no virtual results here
    assert out["urls"] == ["/api/v4/livebots/signals", "/api/v4/livebots/signals?bot=paper2",
                           "/api/v4/livebots/missed?span=7d&group=all&result=all", "/api/v4/livebots/missed?span=all&group=vote_gate&bot=paper2"]
    assert out["calls"][0][0] in ("/api/v4/livebots/now", "/api/v4/livebots/signals")
    assert out["pr"] == ["가상 결과 없음", "+3.0% 잠금 익절"]


def test_goal_judge_why_and_settings_screens_draw_two_different_bots(vw):
    p, more = vw
    goal = json_finite(I.goal(p, NOW, more))
    judge = json_finite(I.judge(p, NOW, more))
    why = json_finite(Y.build(p, more, "paper2", "SOLUSDT", _entry("V3"), None, NOW))
    why0 = json_finite(Y.build(p, more, "paper2", "BTCUSDT", _entry("V1"), None, NOW))
    sett = json_finite(L.settings(p, NOW))
    out = _node("""
const gv = GO.goalView(mkCtx({"/api/v4/livebots/goal": d.goal}));
const jv = JU.judgeView(mkCtx({"/api/v4/livebots/judge": d.judge}));
const mv = MO.settingsView(mkCtx({"/api/v4/livebots/settings": d.sett}));
await tick();
console.log(JSON.stringify({goal: text(gv.el), judge: text(jv.el), why: text(WHY.whyBody(d.why)), why0: text(WHY.whyBody(d.why0)),
  sett: text(mv.el)}));
""", {"goal": goal, "judge": judge, "why": why, "why0": why0, "sett": sett})
    g, j, w, w0, s = out["goal"], out["judge"], out["why"], out["why0"], out["sett"]
    for t in (g, j, w, w0, s):
        assert not _bad(t), _bad(t)
    for x in ("두 봇 나란히", "추세판단 봇 · VWAP 개선판 · 매매법이 서로 달라요", "추세판단 봇 · 바이비트", "VWAP 개선판 · WOO X Pro",
              "WOO X Pro는 10/22 14:00부터 VWAP 개선판을 따라가요", "신호등 (이 실행기 설정)", "평일 하루 진입 참고: 2020-03~2026-09",
              "WOO X Pro가 옮긴 때 · 각 봇 거래만"):
        assert x in g, x
    assert "손절 비교 (11/3 검토용)" not in g and "손절만 다름" not in g
    assert "두 봇 나란히 · 매매법이 서로 달라요 · 둘 다 돌던 때부터" in j and "손절만 다름" not in j
    for x in ("VWAP 복귀 실패 · 30분봉", "VWAP 복귀 실패 (F6_VWAP_FAIL) · 30분봉", "4시간 추세: 상승 3·하락 0·중립 1 → 롱 통과",
              "변동성 30분 ATR 0.45% · 30일 80% 위치 0.62% → 통과", "보유 한도 96봉 = 30분봉 48시간 / 1시간봉 96시간, 지나면 시장가 정리",
              "이 거래는 30분봉이라 48시간", Y.REF_OTHER_KO.format(name="VWAP 개선판")):
        assert x in w, x
    assert "A그룹" not in w and "B그룹" not in w and "추격" not in w and Y.REF_PAPER2_KO not in w
    assert "이 진입은 조건 기록 전이라 숫자가 없어요" in w0
    for x in ("VWAP 개선판 규칙", "두 번째 페이퍼(연습) 봇 · WOO X Pro가 따라가요", "진입 조건", "보유 한도", "BTC 30배 · 나머지 30배",
              "잔고의 최대 20%", "ATR 2배", "없음 (손절 · 계단 잠금 · 보유 한도만)", "따라가는 페이퍼 봇: VWAP 개선판",
              "열린 포지션 청산은 계속", *C.gate_lines(C.ComboConfig(**TW.deploy("combo.vwap.json")))):
        assert x in s, x
    assert s.count("(추세 판단·청산은 계속)") == 1                                       # the trend bot's card keeps its words


def test_one_paper_screens_draw_as_before(tmp_path, monkeypatch):
    p = W.build_world(str(tmp_path / "w"))
    more = {**L.paths_more({}), "rule_db": str(tmp_path / "r.db"), "check_db": str(tmp_path / "c.db"), "improve_db": str(tmp_path / "i.db"),
            "combo_config": str(tmp_path / "no.json"), "combo2_config": str(tmp_path / "no2.json")}
    monkeypatch.setattr(L, "paths_more", lambda env=None: more)
    sg = json_finite(L.signals(p, W.NOW))
    out = _node("""
KIT.setPapers(null);
const sv = SIG.signalsView(mkCtx({"/api/v4/livebots/signals": d.sg, "/api/v4/livebots/now": {pending: {state: "ok", waits: [], closes: []}}}));
await tick();
console.log(JSON.stringify({sig: text(sv.el), kick: [TR.kickKo(), RV.kickKo()], mf: KIT.mainFollowKo()}));
""", {"sg": sg})
    assert "어느 봇의 신호" not in out["sig"] and "페이퍼 봇의 신호 · 한국 시간" in out["sig"]
    assert "실거래 실행기는 페이퍼가 진입한 것만 따라가요" in out["sig"] and "조건이 읽은 값" not in out["sig"]
    assert out["kick"] == ["추세판단 봇 · 바이비트 · WOO X Pro가 따라가는 페이퍼(−50%)",
                           "2주 검토 · 추세판단 봇 · 바이비트 · WOO X Pro가 따라가는 페이퍼(연습)"] and out["mf"] is None
