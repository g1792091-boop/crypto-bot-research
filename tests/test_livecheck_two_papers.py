"""The live checks with two paper bots (owners 10-19, docs/live15-mexc-ko.md): MEXC follows 규칙봇 15's -35 % twin since its
switch, Bybit the -50 % bot (tests/two_papers_world.py). Each executor is held against the paper bot it followed then:
its costs, the watcher's "lost where the paper won" and "did not follow", the loss cards, the trade messages, the morning
check, 못 탄 신호's executor rows, the weekly scorecard and the analysis team's rules. With one paper bot (the standard
world) everything is what it was."""
from __future__ import annotations

import json
import os
import sqlite3

import pytest

from paperbot import livecheck as LC
from paperbot import livepapers as LP
from paperbot.notify import ListNotifier
from tests import livebots_world as W
from tests import two_papers_world as TW

H, MIN, DAY, T0, NOW = TW.H, TW.MIN, TW.DAY, TW.T0, TW.NOW
UNITS = lambda unit: ("active", "enabled")            # noqa: E731  (both executors meant to run)


@pytest.fixture
def world(tmp_path):
    p = TW.build(str(tmp_path / "w"))
    rule = W.rule_bars(str(tmp_path / "w" / "paper3.db"), "BTCUSDT", NOW - 5 * MIN, NOW + 30 * MIN)
    src = LC.Sources(db=str(tmp_path / "w" / "livecheck.db"), paper_db=p["paper"], rule_db=rule,
                     combo_config=str(tmp_path / "no-combo.json"), cache=str(tmp_path / "cache.db"),
                     shadow_glob=str(tmp_path / "shadow-*.db"), executors=TW.infos(p))
    return p, src


def _ex(src, name):
    return next(x for x in src.executors if x.name == name)


# ---------------------------------------------------------------- which paper bot, since when
def test_each_executor_follows_its_own_paper_bot_from_its_start_records(world):
    p, src = world
    ps = LC.PaperSet(p["paper"])
    mx, by = _ex(src, "mexc"), _ex(src, "bybit")
    assert mx.paper_db == p["paper2"] and by.paper_db == p["paper"]
    c = LC.open_ro(mx.db)
    segs = ps.segs(mx, c)
    c.close()
    assert segs == [[None, p["paper"]], [TW.SWITCH, p["paper2"]]]
    assert LP.paper_at(segs, T0 + 2 * H) == p["paper"] and LP.paper_at(segs, T0 + 5 * H) == p["paper2"]
    c = LC.open_ro(by.db)
    assert ps.segs(by, c) == [[None, p["paper"]]]
    c.close()
    assert LC.paper_name(p["paper"]) == "페이퍼 −50%" and LC.paper_name(p["paper2"]) == "페이퍼 −35%"
    assert LC.card_key("COMBO@mix", "LTCUSDT", 5) == "COMBO@mix|LTCUSDT|5"
    assert LC.card_key("COMBO@mix", "LTCUSDT", 5, p["paper2"]) == "COMBO@mix#live15-mexc|LTCUSDT|5"
    # an executor that never recorded a paper database (older code) follows the main one; a config edited but not
    # restarted yet does not change the past
    assert LP.segments([(1, None), (2, None)], "/m.db", "/x.db") == [[None, "/m.db"]]
    assert LP.config_differs([[None, "/m.db"]], "/x.db") and not LP.config_differs([[None, "/m.db"]], "/m.db")


def test_costs_of_each_live_trade_against_the_paper_trade_it_followed(world):
    p, src = world
    w0, w1 = LC.window_of("2026-10-19")
    pc = LC.open_ro(p["paper"])
    main = LC.paper_trades(pc, LC.ACCOUNT)
    pc.close()
    ps = LC.PaperSet(p["paper"], main)
    r = LC.exec_report(_ex(src, "mexc"), main, w0, w1, NOW, ps=ps)
    by = {row["symbol"]: row for row in r["costs"]}
    assert by["ETHUSDT"]["paper_roe"] == pytest.approx(0.0375)            # before the switch: the -50 % bot's t2
    assert by["LTCUSDT"]["paper_roe"] == pytest.approx(-0.35)             # after it: the -35 % bot's u5 (the -50 % bot won it)
    assert by["SOLUSDT"]["matched"] and r["paper_db"] == p["paper2"] and r["cost"]["unmatched"] == 0
    old = LC.exec_report(_ex(src, "mexc"), main, w0, w1, NOW)              # without the pairing: held against the -50 % bot
    assert {row["symbol"]: row for row in old["costs"]}["LTCUSDT"]["paper_roe"] == pytest.approx(0.03)
    b = LC.exec_report(_ex(src, "bybit"), main, w0, w1, NOW, ps=ps)
    assert "paper_db" not in b and {row["symbol"]: row["paper_roe"] for row in b["costs"] if row["matched"]}["ETHUSDT"] == pytest.approx(0.0375)


# ---------------------------------------------------------------- the 1-minute watcher
def test_the_watcher_never_holds_mexc_against_the_other_paper_bot(world):
    p, src = world
    pc = LC.open_ro(p["paper"])
    main = LC.paper_trades(pc, LC.ACCOUNT)
    pc.close()
    c = LC.open_ro(_ex(src, "mexc").db)
    ps = LC.PaperSet(p["paper"], main)
    segs = ps.segs(_ex(src, "mexc"), c)
    old = LC.exec_vs_paper(c, main)
    new = LC.exec_vs_paper(c, main, paper_for=lambda t: ps.at(segs, t))
    c.close()
    assert [t["symbol"] for t, _p in old] == ["LTCUSDT"]          # the -50 % bot won LTC, MEXC (on the -35 % bot) lost it
    assert new == []                                               # its own paper bot lost it too: no "실거래만 짐"
    conds, judged, _seen = LC.watch_conditions(src, NOW, UNITS, exists=lambda path: False)
    keys = [x.key for x in conds]
    assert not [k for k in keys if k.startswith(("vs_paper:mexc", "follow:mexc", "paper2_stale"))], keys
    assert "paper2_stale:" in judged


def test_a_silent_minus_35_bot_is_an_alarm_while_mexc_follows_it(world, tmp_path):
    p, src = world
    s = __import__("paperbot.store3", fromlist=["Store3"]).Store3(p["paper2"])
    s.put_state("heartbeat", NOW - 30 * MIN, {})
    s.put_state("accounts", NOW - 30 * MIN, json.loads(s.conn.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()[0]))
    s.close()
    conds, _j, _s = LC.watch_conditions(src, NOW, UNITS, exists=lambda path: False)
    c = next(x for x in conds if x.key == "paper2_stale:live15-mexc")
    assert c.level == LC.CRITICAL and "페이퍼 −35% 페이퍼 봇이 10분 넘게" in c.text and "paperbot-combo-mexc" in c.text
    assert "MEXC" in c.text


def test_loss_cards_name_only_the_executors_that_followed_that_paper_bot(world):
    p, src = world
    conn = LC.open_out(src.db)
    try:
        cards = {c["key"]: c for c in LC.cards_pass(src, conn, NOW, None, send=None)}
    finally:
        conn.close()
    t3 = f"COMBO@mix|SOLUSDT|{T0 + 3 * H}"
    u5 = f"COMBO@mix#live15-mexc|LTCUSDT|{T0 + 5 * H}"
    assert set(cards) == {t3, u5}                 # u3 (before MEXC followed the -35 % bot) has no card; t5 won
    assert [o["name"] for o in cards[t3]["executors"]] == ["bybit", "mexc"] and cards[t3]["paper_ko"] == "페이퍼 −50%"
    assert [(o["name"], o["status"]) for o in cards[u5]["executors"]] == [("mexc", "followed")]
    assert cards[u5]["executors"][0]["pnl"] == pytest.approx(-4.3) and cards[u5]["paper_db"] == p["paper2"]
    assert "페이퍼 −35% · S2_ST_ROC" in cards[u5]["text"] and "바이비트" not in cards[u5]["text"]
    assert "(페이퍼 −35%)" in LC.card_line(cards[u5], NOW)


def test_one_entry_of_both_bots_is_one_message_with_a_line_per_paper_bot(world):
    p, src = world
    conn = LC.open_out(src.db)
    sent = []
    try:
        got = LC.trade_pass(src, conn, T0 + 9 * H + 4 * MIN, None, lambda lv, tx: sent.append(tx) or True, units=UNITS)
    finally:
        conn.close()
    entry = [t for k, _key, _lv, t in got if k == "entry"]
    assert len(entry) == 1
    text = entry[0]
    assert "페이퍼 −50% 62,000 · 손절" in text and "페이퍼 −35% 62,000 · 손절 61,544 (-0.73%)" in text
    assert "바이비트 ✅" in text and "MEXC     ✅" in text


def test_the_morning_check_lists_both_paper_bots(world):
    p, src = world
    r = LC.run_check(src, day="2026-10-19", now_ms=T0 + DAY + 10 * MIN, no_replay=True, notifier=ListNotifier())
    text = r["text"]
    assert "- 페이퍼 −50%(바이비트가 따라감): 거래 6번" in text
    assert "- 페이퍼 −35%(MEXC가 따라감): 거래 6번 · 4승(67%)" in text
    assert r["report"]["other_papers"][0]["path"] == p["paper2"]


def test_one_paper_bot_reads_as_before(tmp_path):
    p = W.build_world(str(tmp_path / "w"))
    src = LC.Sources(db=str(tmp_path / "w" / "livecheck.db"), paper_db=p["paper"], rule_db=str(tmp_path / "none.db"),
                     combo_config=str(tmp_path / "no.json"), executors=W.exec_infos(p))
    r = LC.run_check(src, day="2026-10-19", now_ms=T0 + DAY + 10 * MIN, no_replay=True, notifier=ListNotifier())
    assert "- 페이퍼: 거래 6번" in r["text"] and "가 따라감" not in r["text"] and "other_papers" not in r["report"]
    conn = LC.open_out(src.db)
    try:
        cards = LC.cards_pass(src, conn, NOW, None, send=None)
    finally:
        conn.close()
    assert all("#" not in c["key"].split("|")[0] and "paper_ko" not in c for c in cards)


# ---------------------------------------------------------------- 못 탄 신호, the weekly scorecard, the analysis team
def test_missed_rows_of_an_executor_only_for_its_own_paper_bot(world):
    from paperbot import livemissed as LM
    p, src = world
    conn = sqlite3.connect(":memory:")
    conn.executescript(LM.SCHEMA_TABLES)
    pc = LC.open_ro(p["paper"])
    d = LM.read_paper(pc, T0 - DAY, T0 - DAY)
    pc.close()
    res = {"exec": 0}
    LM._exec_pass(src, conn, NOW, T0 - DAY, d["trades"], None, {}, 0.0014, res)
    rows = {r[0]: r[1] for r in conn.execute("SELECT key, executor FROM missed WHERE grp = 'exec'")}
    mexc = sorted(k for k, ex in rows.items() if ex == "mexc")
    # t3 (before the switch: its entry check refused it); never t5 / t6 of the -50 % bot (MEXC followed the -35 % bot then)
    assert mexc == [f"exec:mexc|COMBO@mix|SOLUSDT|{T0 + 3 * H}"]
    by = sorted(k for k, ex in rows.items() if ex == "bybit")
    assert by == [f"exec:bybit|COMBO@mix|DOGEUSDT|{T0 + 4 * H}", f"exec:bybit|COMBO@mix|LTCUSDT|{T0 + 5 * H}"]


def test_the_weekly_scorecard_counts_a_live_trade_only_on_its_own_paper_bot(world):
    from paperbot import liveimprove as LI
    p, src = world
    pc = LC.open_ro(p["paper"])
    main = LC.paper_trades(pc, LC.ACCOUNT)
    pc.close()
    ids = {t["id"]: t["symbol"] for t in main}
    old = LI.exec_follow(src.executors, main)
    new = LI.exec_follow(src.executors, main, paper_db=p["paper"])
    assert sorted(ids[i] for i in old["mexc"]) == ["BCHUSDT", "DOGEUSDT", "ETHUSDT", "LTCUSDT"]
    assert sorted(ids[i] for i in new["mexc"]) == ["DOGEUSDT", "ETHUSDT"]          # after the switch: the -35 % bot's
    assert new["bybit"] == old["bybit"]


def test_the_analysis_team_is_told_both_stops(world):
    from paperbot import liveteam as T
    p, src = world
    sec = T.second_paper(p["paper"], src.executors)
    assert sec["label"] == "페이퍼 −35% (MEXC가 따라감)" and sec["first_label"] == "페이퍼 −50% (바이비트가 따라감)"
    assert sec["follows"] == {"바이비트": "페이퍼 −50%", "MEXC": "페이퍼 −35%"}
    cfg = TW.deploy_config("combo.live15.json")
    rules = T.fixed_rules(cfg, src.executors, sec)
    two = next(r for r in rules if r.startswith("두 번째 페이퍼 봇"))
    assert "손절 순ROE -35%(수수료·슬리피지 포함: 40배 가격 0.73%, 30배 가격 1.03%)" in two and "-50%" not in two
    assert "따라가는 페이퍼: 바이비트는 페이퍼 −50% · MEXC는 페이퍼 −35%" in rules
    assert "손절 순ROE -50%(수수료·슬리피지 포함: 40배 가격 1.11%, 30배 가격 1.53%)" in rules
    facts = T.bot_facts({"config": cfg, "second": sec})
    assert facts["break_even"] == pytest.approx(0.833) and facts["second"]["break_even"] == pytest.approx(0.778)
    assert T.second_paper(p["paper"], [x for x in src.executors if x.name == "bybit"]) is None
    assert T.fixed_rules(cfg, src.executors) == T.fixed_rules(cfg, src.executors, None)


def test_the_two_paper_preview(monkeypatch):
    import urllib.request
    from paperbot import livepreview as PV

    def no_network(*a, **k):
        raise AssertionError("the preview must not reach the network")
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    items = PV.scenes("two")
    text = PV.render(items)
    assert "▶️ MEXC 실행기 켜짐 · 잔고 $107.87 · 따라가는 페이퍼: 페이퍼 −35%" in text
    assert "페이퍼 −50% 67,250 · 손절 66,504 (-1.11%)" in text and "페이퍼 −35% 67,250 · 손절 66,756 (-0.74%)" in text
    card = next(t for _s, _lv, t in items if t.startswith("❌") or t.startswith("🚨 ❌"))
    assert "페이퍼 −35% · V39_ALL" in card and "MEXC" in card and "바이비트" not in card
    win = next(t for _s, _lv, t in items if t.startswith("✅ 청산"))
    assert "바이비트" in win and "MEXC" not in win
    morning = items[-1][2]
    assert "- 페이퍼 −50%(바이비트가 따라감)" in morning and "- 페이퍼 −35%(MEXC가 따라감)" in morning
    assert LC.main(["preview", "--two"]) == 0


def test_the_second_slot_trading_woo_x_pro_is_named_woo_x_pro_in_trade_lines():
    """Owners 10-20: the "mexc" slot trades WOO X Pro; its Telegram trade lines say so, never "MEXC"."""
    def info(name, exchange):
        return LC.ExecInfo(name=name, config="-", unit=f"paperbot-executor-{name}", db="-", light_n=0, light_min=0.85,
                           exchange=exchange)
    assert LC._pad(info("mexc", "wooxpro")) == "WOO X Pro "
    assert LC._pad(info("mexc", "mexc")) == LC.PAD["mexc"]
    assert LC._pad(info("bybit", "bybit")) == LC.PAD["bybit"]
    assert LC.pad_of("mexc", "WOO X Pro") == "WOO X Pro "
