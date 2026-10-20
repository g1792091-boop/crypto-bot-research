"""The 실거래 site with two paper bots (owners 10-19, docs/live15-mexc-ko.md, docs/livedash-ko.md "페이퍼가 둘일 때"): MEXC
follows the -35 % twin of 규칙봇 15 since its switch, Bybit the -50 % bot (tests/two_papers_world.py). Every screen pairs
each executor with the paper bot it followed then; the paper accounts are labelled by their config's stop and who follows
them; a one-paper world (tests/livebots_world.py) shows nothing new. Plus the 목표 additions (owners 10-19): the win rate
the goal needs, the scale-up checklist, the rule freeze and 손절 비교 (owners 10-19 final: Bybit -50 % against MEXC -35 %,
the two-week test for the 11/3 review, side by side with no verdict)."""
from __future__ import annotations

import re

import pytest

from paperbot.dash.more import liveinsight as I
from paperbot.dash.more import livebots as L
from paperbot.dash.more import livepos as P
from paperbot.dash.more import livetape as TP
from tests import livebots_world as W
from tests import two_papers_world as TW

H, MIN, T0, NOW = TW.H, TW.MIN, TW.T0, TW.NOW


def _more(tmp_path) -> dict:
    return {**L.paths_more({}), "rule_db": str(tmp_path / "none-rule.db"), "check_db": str(tmp_path / "none-check.db"),
            "improve_db": str(tmp_path / "none-improve.db"), "combo_config": str(tmp_path / "no-combo.json"),
            "combo2_config": str(tmp_path / "no-combo2.json")}


@pytest.fixture
def two(tmp_path):
    return TW.build(str(tmp_path / "w")), _more(tmp_path)


@pytest.fixture
def one(tmp_path):
    return W.build_world(str(tmp_path / "w")), _more(tmp_path)


def _by(xs, key="id"):
    return {x[key]: x for x in xs}


# ---------------------------------------------------------------- one paper bot: nothing new
def test_one_paper_bot_looks_as_before(one, monkeypatch):
    p, more = one
    monkeypatch.setattr(L, "paths_more", lambda env=None: more)
    d = L.build(p, NOW)
    assert d["papers"] is None and [a["id"] for a in d["accts"]] == ["paper", "bybit", "mexc"]
    assert all("follows_ko" not in x and x["segs"] == [[None, p["paper"]]] for x in d["execs"])
    assert all(not k.startswith("_") for x in d["execs"] for k in x)
    assert "paper2" not in L.trade_rows(p, NOW, more)["accts"] and L.perf(p, NOW, more)["compare"] is None
    assert [c["id"] for c in P.build(p, more, NOW)["cards"]] == ["paper", "bybit", "mexc", "flip"]
    assert I.judge(p, NOW, more)["compare"] is None and "paper2" not in [a["id"] for a in I.risk(p, NOW, more)["accts"]]
    assert not [i for i in I.health(p, NOW, more)["items"] if i["id"].startswith("paper2")]
    assert TP.build_list(p, NOW)["papers"] is None


# ---------------------------------------------------------------- two paper bots
def test_the_summary_names_both_paper_bots_and_who_follows_which(two, monkeypatch):
    p, more = two
    monkeypatch.setattr(L, "paths_more", lambda env=None: more)
    d = L.build(p, NOW)
    assert [a["id"] for a in d["accts"]] == ["paper", "paper2", "bybit", "mexc"]
    assert [(b["id"], b["label_ko"]) for b in d["papers"]] == [("paper", "페이퍼 −50% (바이비트가 따라감)"), ("paper2", "페이퍼 −35% (MEXC가 따라감)")]
    x = _by(d["execs"])
    assert x["mexc"]["follows_ko"] == "페이퍼 −35% · 규칙봇 15 MEXC −35%" and x["bybit"]["follows_ko"] == "페이퍼 −50% · 규칙봇 15"
    assert x["mexc"]["segs"] == [[None, p["paper"]], [TW.SWITCH, p["paper2"]]] and x["mexc"]["switched_ms"] == TW.SWITCH
    a = _by(d["accts"])
    assert a["paper2"]["label_ko"] == "페이퍼 −35% (MEXC가 따라감)" and a["paper2"]["stats"]["trades"] == 6
    # each executor's open position borrows the next lock of the paper position IT follows
    assert a["mexc"]["position"]["next_lock"]["lock"] == pytest.approx(0.10)          # the -35 % bot: not locked yet
    assert a["bybit"]["position"]["next_lock"]["lock"] == pytest.approx(0.12)         # the -50 % bot: locked +10 % already
    assert any(f["acct"] == "paper2" for f in d["fills"])                             # its fills while MEXC follows it
    ltc = next(f for f in d["fills"] if f["acct"] == "mexc" and f["symbol"] == "LTCUSDT" and f["kind"] == "exit")
    assert ltc["reason"] == "SL"                                                      # its own paper's reason, not t5's LOCK


def test_trades_pair_each_live_trade_with_the_paper_trade_it_followed(two):
    p, more = two
    tr = L.trade_rows(p, NOW, more)["accts"]
    mx = _by(tr["mexc"]["rows"], "symbol")
    assert mx["LTCUSDT"]["paper"]["exit_reason"] == "SL" and mx["LTCUSDT"]["paper"]["paper_id"] == "paper2"
    assert mx["LTCUSDT"]["reason_ko"] == "손절" and mx["ETHUSDT"]["paper"]["paper_id"] == "paper"
    main = _by(tr["paper"]["rows"], "symbol")
    assert main["LTCUSDT"]["live"]["mexc"] == {"state": "other", "why_ko": "이때 MEXC는 페이퍼 −35%를 따라갔어요"}
    assert main["LTCUSDT"]["live"]["bybit"]["state"] == "missed"
    second = tr["paper2"]
    assert second["label_ko"] == "페이퍼 −35% (MEXC가 따라감)" and second["n"] == 6
    rows2 = {(r["symbol"], r["entry_time"]): r for r in second["rows"]}
    assert rows2[("LTCUSDT", T0 + 5 * H)]["live"]["mexc"]["state"] == "matched"
    assert rows2[("ETHUSDT", T0 + 2 * H)]["live"]["mexc"] == {"state": "other", "why_ko": "이때 MEXC는 페이퍼 −50%를 따라갔어요"}
    assert rows2[("SOLUSDT", T0 + 7 * H + 30 * MIN)]["live"]["bybit"]["state"] == "other"
    assert rows2[("LTCUSDT", T0 + 5 * H)]["key"].startswith("paper2:")
    c = L.costs(p, NOW)["accts"]["mexc"]
    assert c["n"] == 5 and c["matched"] == 5 and sum(m["n"] for m in c["missed"]) == 1        # t3 only (before the switch)


def test_the_two_paper_comparison(two):
    p, more = two
    cmp = L.perf(p, NOW, more)["compare"]
    assert cmp["state"] == "ok" and cmp["since_ms"] == TW.P2_SINCE
    assert (cmp["shared"], cmp["parted"], cmp["only"]) == (5, 1, {"paper": 0, "paper2": 1})
    assert cmp["words_ko"] == "같은 진입 5번 중 결과가 갈린 거래 1번 · 한쪽만 들어간 거래: −50% 0번, −35% 1번"
    r = _by(cmp["rows"])
    assert (r["paper"]["n"], r["paper"]["wins"], r["paper2"]["n"], r["paper2"]["wins"]) == (5, 4, 6, 4)
    assert r["paper2"]["max_dd"] > r["paper"]["max_dd"] > 0
    assert cmp["parted_rows"][0]["symbol"] == "LTCUSDT" and cmp["parted_rows"][0]["paper2"]["exit_reason"] == "SL"
    assert I.judge(p, NOW, more)["compare"] == cmp


def test_positions_risk_health_groups_and_replay_use_each_executors_own_paper(two):
    p, more = two
    cards = _by(P.build(p, more, NOW)["cards"])
    assert list(cards) == ["paper", "paper2", "bybit", "mexc", "flip"]
    assert cards["mexc"]["position"]["stop_rule_cfg"] == {"roe": 0.35, "net": True} and cards["mexc"]["follows_ko"] == "페이퍼 −35%"
    assert cards["bybit"]["position"]["stop_rule_cfg"] == {"roe": 0.5, "net": True}
    assert _by(cards["paper"]["position"]["execs"])["mexc"]["state"] == "other"
    assert _by(cards["paper2"]["position"]["execs"])["mexc"]["state"] == "following"
    rk = _by(I.risk(p, NOW, more)["accts"])
    assert rk["mexc"]["stop_roe"] == pytest.approx(0.35) and rk["mexc"]["next"][0]["left"] == pytest.approx(1 - 0.4 * 0.35)
    assert rk["bybit"]["next"][0]["left"] == pytest.approx(0.80) and rk["paper2"]["label_ko"].startswith("페이퍼 −35%")
    hb = [i for i in I.health(p, NOW, more)["items"] if i["id"].startswith("paper2")]
    assert [i["ko"] for i in hb] == ["페이퍼 −35% 봇 심장 박동", "페이퍼 −35% 봇 마지막 1분"] and hb[0]["severity"] == "bad"
    g = I.groups(p, NOW, more)["accts"]["mexc"]
    assert g["state"] == "ok" and sum(v["n"] for v in g["groups"].values()) == 5
    lst = TP.build_list(p, NOW, bot="paper2")
    assert lst["bot"] == "paper2" and lst["n"] == 6
    row = next(r for r in lst["rows"] if r["symbol"] == "LTCUSDT")
    assert _by(row["execs"])["mexc"]["state"] == "matched" and _by(row["execs"])["bybit"]["state"] == "other"
    main = TP.build_list(p, NOW)
    assert _by(next(r for r in main["rows"] if r["symbol"] == "LTCUSDT")["execs"])["mexc"]["state"] == "other"


def test_a_config_edited_but_not_restarted_is_said(two, tmp_path):
    p, more = two
    import json
    with open(p["bybit_config"], encoding="utf-8") as fh:
        d = json.load(fh)
    d["paper_db"] = p["paper2"]
    with open(p["bybit_config"], "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    _c, _f, _paper, execs = L.sources(p, NOW)
    by = _by(execs)["bybit"]
    assert by["paper_path"] == p["paper"]                  # its last start followed the -50 % bot: that one counts
    assert any("다시) 켜야 적용돼요" in n for n in by["notes"])


# ---------------------------------------------------------------- 목표 (owners 10-19)
def test_the_win_rate_the_goal_needs():
    # x6 in a month of 21.7 weekdays x 6 entries at 30 % margin, +12.5 % wins and -50 % losses: about 88 %
    assert I.need_win(6.0, 6 * 21.7, 0.3, 0.125, 0.5) == pytest.approx(0.884, abs=0.001)
    assert I.need_win(6.0, 5.5 * 21.7, 0.3, 0.10, 0.5) == pytest.approx(0.924, abs=0.001)
    assert I.need_win(None, 10, 0.3, 0.1, 0.5) is None and I.need_win(2.0, 10, 0.3, 0.1, 4.0) is None
    mo = {"weekdays_left": 10.0, "weekdays_gone": 11.7}
    cfg = TW.deploy_config("combo.live15.json")
    rec = {"n": 20, "wins": 18, "win_rate": 0.9, "avg_win": 0.125, "avg_loss": -0.5}
    w = I.win_need(rec, 3.0, mo, cfg, 6.0)
    assert w["state"] == "ok" and w["ko"].startswith(f"남은 기간 목표 속도: 승률 {w['p']:.0%} 필요 · 지금 90% (범위 ")
    assert w["month_ko"].startswith("한 달 전체로 보면 약 ") and w["per_weekday_src"] == "record" and w["w_src"] == "record"
    assert I.win_need(rec, 0.9, mo, cfg, 6.0)["ko"] == "이번 달 목표 이미 달성"
    hard = I.win_need(rec, 100.0, mo, cfg, 6.0)
    assert hard["state"] == "impossible" and hard["ko"].startswith("남은 기간 목표 속도: 승률 100%로도 모자람")
    early = I.win_need({"n": 0, "wins": 0, "win_rate": None, "avg_win": None, "avg_loss": None}, 3.0, mo, cfg, None)
    assert early["per_weekday"] == 6.2 and early["w"] == 0.10 and early["l"] == 0.5 and "참고값 6.2" in early["src_ko"]
    assert "지금 승률 기록 없음" in early["ko"] and I.GOAL_MATH_KO in early["note_ko"]


def test_the_rule_freeze_is_one_named_date():
    assert I.RULES_FROZEN_UNTIL == "2026-11-03"
    assert I.frozen(T0)["ko"] == "규칙 고정: 11/3까지 (15일 남음)"
    nov3 = T0 + 15 * 86_400_000
    assert I.frozen(nov3)["ko"] == "규칙 고정: 오늘(11/3)까지" and I.frozen(nov3 + 86_400_000)["on"] is False


def test_goal_answers_per_account_with_the_scale_checklist(one):
    p, more = one
    g = I.goal(p, NOW, more)
    assert g["frozen"]["until"] == "2026-11-03" and g["need_note_ko"] == I.GOAL_MATH_KO
    a = _by(g["accts"])
    assert set(a) == {"paper", "bybit", "mexc"} and "need" in a["paper"] and "scale" not in a["paper"]
    sc = a["bybit"]["scale"]
    assert [c["id"] for c in sc["checks"]] == ["trades", "paper_win", "gap"] and not sc["ok"]
    assert sc["checks"][0]["ko"].startswith("거래 ") and sc["checks"][0]["ko"].endswith("/40번")
    assert sc["ko"].startswith("아직 아니에요: 거래 ") and "증거금 비중이나 배수는 올리지 않아요" in sc["note_ko"]


def test_scale_up_when_all_three_hold(one, monkeypatch):
    p, more = one
    cx = I.context(p, NOW, more)
    x = _by(cx["execs"])["bybit"]
    x["record"]["trades"] = [dict(t, entry_ts=(t["entry_ts"] or 0)) for t in x["record"]["trades"]] * 20
    pairs = {str(t["key"]): {"pnl": 1.0, "paper_path": p["paper"], "id": 1} for t in x["record"]["trades"]}
    monkeypatch.setattr(L, "pairs_of", lambda xx: pairs)
    monkeypatch.setattr(L, "fill_gaps", lambda *a, **k: {"state": "ok", "entry_roe": -0.004, "entry_n": 40})
    cx["start"] = {"ms": None, "sure": False}
    s = I.scale_check(cx, x)
    assert s["ok"] and [c["ok"] for c in s["checks"]] == [True, True, True]
    assert s["ko"] == "돈 한 단계 늘릴 때: 같은 증거금 그대로, 넣는 돈을 지금만큼 더 (예: $100 → $200), 그 뒤 거래 40번 다시 확인"
    monkeypatch.setattr(L, "fill_gaps", lambda *a, **k: {"state": "ok", "entry_roe": -0.013, "entry_n": 40})
    s = I.scale_check(cx, x)
    assert not s["ok"] and s["ko"] == "아직 아니에요: 진입 차이 평균 순ROE +1.3%p (잰 거래 40번)"


def test_goal_shows_the_two_stops_side_by_side(two, tmp_path):
    import json
    from paperbot.dash.app import json_finite
    from tests.test_dash_liveinsight import _node
    p, more = two
    g = I.goal(p, NOW, more)
    h = g["h2h"]
    assert h["state"] == "ok" and h["since_ms"] == TW.P2_SINCE and h["live_since_ms"] == TW.SWITCH
    s = _by(h["sides"])
    assert [(x["stop_short"], x["followers"]) for x in h["sides"]] == [("−50%", ["바이비트"]), ("−35%", ["MEXC"])]
    assert (s["paper"]["paper"]["n"], s["paper"]["paper"]["wins"], s["paper2"]["paper"]["n"], s["paper2"]["paper"]["wins"]) == (5, 4, 6, 4)
    assert s["paper2"]["paper"]["max_dd"] > s["paper"]["paper"]["max_dd"] > 0
    # each live account under the stop it follows, counted from MEXC's switch (both accounts over the same time)
    assert [x["id"] for x in s["paper"]["live"]] == ["bybit"] and [x["id"] for x in s["paper2"]["live"]] == ["mexc"]
    by, mx = s["paper"]["live"][0], s["paper2"]["live"][0]
    assert (by["n"], by["wins"], mx["n"], mx["wins"]) == (2, 1, 3, 2) and by["since_ms"] == mx["since_ms"] == TW.SWITCH
    assert h["words_ko"] == "같은 진입 5번 중 결과가 갈린 거래 1번 · 한쪽만 들어간 거래: −50% 0번, −35% 1번" and h["small"]
    assert h["review_ko"] == I.H2H_REVIEW_KO and "어느 쪽이 낫다고 정하지 않아요" in h["note_ko"]
    words = json.dumps(h, ensure_ascii=False)
    assert "넓" not in words and "widen" not in words                                   # no stop-widening check
    one = W.build_world(str(tmp_path / "w1"))
    g1 = I.goal(one, NOW, more)
    assert g1["h2h"] is None                                                            # one paper bot: nothing new
    out = _node(tmp_path, """
    const t = G.h2hTable(D_g.h2h);
    const find = (n, c) => { if (!n || !n.childNodes) return null; if (String(n.className || "").split(" ").includes(c)) return n;
      for (const k of n.childNodes) { const f = find(k, c); if (f) return f; } return null; };
    const run = async (a) => { const c = mkCtx({"*": a}); const v = G.goalView(c.ctx); await tick(); await tick(); return v.el; };
    const e2 = await run(D_g), e1 = await run(D_g1);
    const c2 = find(e2, "lbg-h2h"), c1 = find(e1, "lbg-h2h");
    console.log(JSON.stringify({head: t.head, rows: t.rows, none: G.h2hTable(null), hid: [c2.hidden, c1.hidden],
      text: texts(c2), text1: texts(e1)}));""", g=json_finite(g), g1=json_finite(g1))
    assert out["head"] == ["손절 −50% · 바이비트", "손절 −35% · MEXC"] and out["none"] is None
    rows = {r["k"]: r for r in out["rows"]}
    assert list(rows) == ["페이퍼 거래", "페이퍼 승률", "페이퍼 순ROE 합", "페이퍼 잔고 변화", "페이퍼 최대 낙폭",
                          "실거래 거래", "실거래 승률", "실거래 손익", "실거래 잔고 변화"]
    assert rows["페이퍼 거래"]["cells"] == ["5번 (4승 1패)", "6번 (4승 2패)"]
    assert rows["실거래 거래"]["cells"] == ["2번 (1승 1패)", "3번 (2승 1패)"]
    assert rows["페이퍼 최대 낙폭"]["tones"] == ["down", "down"] and rows["페이퍼 승률"]["tones"] == ["", ""]
    assert out["hid"] == [False, True]
    assert "11/3 검토에서" in out["text"] and "표본" in out["text"] and not re.search(r"\b(null|undefined|NaN)\b", out["text"])
