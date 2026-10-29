"""The live checks after owners 10-29 (docs/mixbybit-ko.md): the Bybit account traded by the 바이비트 봇 itself, the
추세판단 봇 switched off.

- an executor slot whose account a mix bot trades (REPLACED_BY: that bot's config on the server) is left out of the
  checks: no "실행기 꺼짐 · 다시 켜기", no stale alarm, no score line;
- the main paper bot (the 추세판단 봇) is retired once no executor follows it and its unit is neither running nor
  enabled: no "페이퍼 봇 멈춤" alarm (and no "다시 들어옵니다" either), no drift, no replay in the morning (one line), its
  score line marked 꺼짐; followed, or its unit meant to run, or systemd unknown: every check as before;
- the memory alarm never suggests stopping the mix bots or the range paper bot;
- the morning part of the 레인지 봇 groups its own reasons (추세 확인 · 한 신호씩 · 강제청산 여유 · 되돌림 안 옴), the VWAP
  bot's line stays as it was."""
from __future__ import annotations

import pytest

from paperbot import livecheck as LC
from paperbot.notify import ListNotifier
from tests import vwap_world as VW

H, MIN, DAY, T0, NOW = VW.H, VW.MIN, VW.DAY, VW.T0, VW.NOW


def units(off=("paperbot-combo",)):
    return lambda unit: ("inactive", "disabled") if unit in off else ("active", "enabled")


@pytest.fixture
def world(tmp_path):
    w = VW.VwapWorld(str(tmp_path / "w"))           # Bybit follows the VWAP bot from its switch, MEXC the trend bot
    yield w
    w.close()


def _only(w, *names):
    return [x for x in w.infos() if x.name in names]


# ---------------------------------------------------------------- the replaced executor slot
def test_a_slot_a_mix_bot_trades_is_left_out(tmp_path, monkeypatch):
    cfg = tmp_path / "mixbybit.json"
    rp = {"bybit": (str(cfg), "paperbot-mixbybit", "바이비트 봇")}
    specs = (("bybit", str(tmp_path / "executor.json"), "paperbot-executor", str(tmp_path / "b.db"), 0, 0.85),
             ("mexc", str(tmp_path / "executor-mexc.json"), "paperbot-executor-mexc", str(tmp_path / "m.db"), 0, 0.9))
    assert [x[0] for x in LC.installed_specs(specs, (), replaced=rp)] == ["bybit", "mexc"]
    assert LC.replaced_now(rp) == []
    cfg.write_text("{}", encoding="utf-8")
    assert [x[0] for x in LC.installed_specs(specs, (), replaced=rp)] == ["mexc"]
    assert LC.replaced_now(rp) == [("bybit", "paperbot-mixbybit", "바이비트 봇")]
    # the server's own table: the Bybit slot and WOO X Pro 2's, each with the bot that took it
    assert LC.REPLACED_BY["bybit"] == ("/etc/paperbot/mixbybit.json", "paperbot-mixbybit", "바이비트 봇")
    assert LC.REPLACED_BY["wooxpro2"][1] == "paperbot-mixchop"
    monkeypatch.setattr(LC, "REPLACED_BY", rp)
    assert [x[0] for x in LC.installed_specs(specs, ())] == ["mexc"]


# ---------------------------------------------------------------- the retired main paper
def test_the_main_paper_is_retired_only_when_unfollowed_and_off(world):
    w = world
    src = w.src(executors=_only(w, "bybit"))                  # Bybit follows the VWAP bot; MEXC left out
    segs = LC.exec_segs(src, src.executors)
    assert LC.main_retired(src, segs, units())
    assert not LC.main_retired(src, segs, units(off=()))           # its unit still meant to run
    assert not LC.main_retired(src, segs, lambda u: ("", ""))       # systemd unknown: as before
    assert not LC.main_retired(src, segs, lambda u: ("inactive", "enabled"))
    both = w.src()
    assert not LC.main_retired(both, LC.exec_segs(both, both.executors), units())   # MEXC still follows it
    other = w.src(executors=_only(w, "bybit"), paper_db=str(w.folder) + "/paper.db")
    assert not LC.main_retired(other, segs, units())                # a file whose unit is unknown


def test_no_stale_alarm_for_a_retired_main_paper(world):
    w = world
    w.vb.run_to(NOW + 15 * MIN)                               # the trend paper bot wrote nothing since NOW
    conds, judged, seen = LC.watch_conditions(w.src(executors=_only(w, "bybit")), NOW + 15 * MIN, units(),
                                              exists=lambda p: False)
    assert "paper_stale" not in {x.key for x in conds} and "paper_stale" not in judged and seen["main_retired"]
    # followed by MEXC: the alarm as before
    conds, judged, seen = LC.watch_conditions(w.src(), NOW + 15 * MIN, units(), exists=lambda p: False)
    assert "paper_stale" in {x.key for x in conds} and not seen["main_retired"]


def test_the_morning_check_skips_a_retired_main_paper(world):
    w = world

    def no_replay(*a, **k):
        raise AssertionError("a retired bot is not replayed")
    r = LC.run_check(w.src(executors=_only(w, "bybit")), day="2026-10-19", now_ms=T0 + DAY + 10 * MIN,
                     replay=no_replay, notifier=ListNotifier(), units=units())
    text = r["text"]
    assert "대조: 안 함 — 추세판단 봇이 꺼져 있고 따라가는 실거래가 없어요" in text
    assert "- 추세판단 봇(꺼짐 · 따라가는 실거래 없음): 거래 " in text
    assert "40번 판단" not in text and "MEXC" not in text
    assert text.startswith("📋 실거래 일일 점검 · 이상 없음")


# ---------------------------------------------------------------- the server alarm and the range bot's groups
def test_the_memory_alarm_never_suggests_the_bots_that_trade():
    for u in ("paperbot-mixchop.service", "paperbot-mixbybit.service", "paperbot-combo-range.service",
              "paperbot-executor-mexc.service", "paperbot-combo-vwap.service"):
        assert u in LC.PROTECTED_UNITS, u


def test_the_range_bots_reasons_have_their_groups():
    k = LC.gate_kind
    assert k("추세 확인: 친구 추세지표 1시간 진입 금지 (하늘·보라 선 상승 · EMA RSI 상승 · 찹존 횡보 · 슈퍼트렌드 횡보)") == "trend"
    assert k("추세 확인: ETH 1시간 슈퍼트렌드 하락(신호 롱와 반대)") == "trend"
    assert k("한 신호씩: BTC 롱 포지션 들고 있음") == "one"
    assert k("강제청산 여유 부족: 손절 거리 1.53% + 1시간 ATR 1.40% > 2.83%") == "liq"
    assert k("되돌림 안 옴(10-27 11:00까지 100에 안 닿음)") == "nopull"
    assert k("친구 추세지표를 못 읽어 진입 안 함: BTC 5분봉 10개뿐") == "unread"
    assert k(VW.VOTE_WHY) == "vote" and k(VW.VOL_WHY) == "vol" and k(VW.UNREAD_WHY) == "unread"
    # the section's line lists the range groups only when they have some
    g = {"n": 3, "vote": 1, "vol": 1, "pause": 0, "unread": 1, "trend": 0, "one": 0, "liq": 0, "nopull": 0, "other": 0}
    line = next(x for x in LC.bot_section({"path": "v.db", "name": "VWAP 개선판", "trades": [], "cfg": None, "gates": g},
                                          [], 0, 1) if x.startswith("- 조건이 막은 신호"))
    assert line == "- 조건이 막은 신호(어제) 3개: 4시간 추세 반대 1 · 변동성 높음 1 · 주말·발표·나스닥 0 · 못 읽음 1"
    g.update(n=5, trend=2, one=1, vote=0, vol=0, unread=0, pause=2)
    line = next(x for x in LC.bot_section({"path": "r.db", "name": "레인지 봇", "trades": [], "cfg": None, "gates": g},
                                          [], 0, 1) if x.startswith("- 조건이 막은 신호"))
    assert "추세 확인(친구 추세 반대·진입 금지) 2 · 한 신호씩 1" in line and "강제청산" not in line


# ---------------------------------------------------------------- the VWAP bot switched off (owners 10-29 "VWAP 봇 끄자")
def test_a_bot_switched_off_for_good_raises_no_alarm(world):
    """Its executor and its paper bot stopped and disabled: no stale alarm for either, no quiet note for the paper; the
    same files with the units meant to run: the alarms as before."""
    w = world
    t = NOW + 15 * MIN                                          # neither paper bot wrote since NOW
    ex_unit = next(x.unit for x in w.infos() if x.name == "bybit")         # the executor that follows the VWAP bot
    conds, _judged, _seen = LC.watch_conditions(w.src(executors=_only(w, "bybit")), t, units(off=()), exists=lambda p: False)
    keys = {x.key for x in conds}
    assert any(k.startswith("paper2_stale:") for k in keys) or any(k.startswith("stale:bybit") for k in keys)
    off = units(off=("paperbot-combo", ex_unit, "paperbot-combo-vwap"))
    conds, _judged, _seen = LC.watch_conditions(w.src(executors=_only(w, "bybit")), t, off, exists=lambda p: False)
    keys = {x.key for x in conds}
    assert not any(k.startswith(("paper2_stale:", "paper2_quiet:", "stale:bybit", "paper_stale")) for k in keys), keys
    # what counts as switched off: known, not running (a failed unit still is), not enabled
    assert LC.switched_off("u", lambda u: ("inactive", "disabled")) and LC.switched_off("u", lambda u: ("inactive", "masked"))
    assert not LC.switched_off("u", lambda u: ("failed", "disabled")) and not LC.switched_off("u", lambda u: ("inactive", "enabled"))
    assert not LC.switched_off("u", lambda u: ("", "")) and not LC.switched_off(None, lambda u: ("inactive", "disabled"))
