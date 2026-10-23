"""The executor's words for the paper bot's TIME exit (owners 10-23, docs/vwap-bot-ko.md): 'VWAP 개선판' closes on its
96-bar hold limit ("보유 한도 청산"), the 추세판단 봇's supervisor on time ("감독 청산(시간 정리)"). Words only: the executor
reads its paper bot's run record (combo_run) once at its start, and what it does with the exit is the same rule as
before (followed before its own first lock, not after). The real executor on the fake exchange (tests/
test_executor_own_ladder.py's Rig) and a real paper database. No network."""
from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from paperbot.executor import PAPER_EXIT_KO, ExecConfig, ladder_lines, paper_time_ko
from paperbot.store3 import Store3
from test_executor_own_ladder import BTC, COSTS, Clock, Paper, Rig

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a test tried to open a network connection")
    monkeypatch.setattr(socket, "create_connection", refuse)


def _cfg(name: str) -> dict:
    return json.loads((DEPLOY / name).read_text(encoding="utf-8"))


def _paper(tmp_path, clock, config: dict) -> Paper:
    p = Paper(str(Path(tmp_path) / "paper.db"), clock)
    p.s.put_state("combo_run", clock.t, {"version": "combo-v2", "config": config})
    p.s.commit()
    return p


def test_the_words_come_from_the_followed_paper_bots_config(tmp_path):
    for name, words in (("combo.vwap.json", "보유 한도 청산"), ("combo.trend.json", "감독 청산(시간 정리)")):
        s = Store3(str(tmp_path / name))
        s.put_state("combo_run", 1, {"config": _cfg(name)})
        s.close()
        assert paper_time_ko(str(tmp_path / name)) == words
    assert paper_time_ko(str(tmp_path / "missing.db")) == PAPER_EXIT_KO["TIME"] == "감독 청산(시간 정리)"
    (tmp_path / "junk.db").write_bytes(b"not a database")
    assert paper_time_ko(str(tmp_path / "junk.db")) == PAPER_EXIT_KO["TIME"]


def test_a_vwap_time_exit_before_its_own_first_lock_is_followed_in_its_words(tmp_path):
    clock = Clock()
    paper = _paper(tmp_path, clock, _cfg("combo.vwap.json"))
    r = Rig(tmp_path, paper=paper)
    try:
        assert r.ex.time_ko == "보유 한도 청산"
        r.enter(BTC, 1, 10_000.0, 20, qty=0.5, fill=10_000.0)
        r.next_minute()
        r.price(BTC, 10_050.0)
        r.loop()
        assert r.ex.trade["own"]["lock"] is None
        r.paper.exit("TIME", 10_050.0)
        r.loop()
        assert r.amt() == 0 and r.ex.trade is None
        assert r.trades()[0][1] == "paper 청산 → 거래소 포지션 닫기 (paper 보유 한도 청산, 자기 첫 잠금 전)"
    finally:
        r.close()
        paper.close()


def test_a_vwap_time_exit_after_its_own_first_lock_is_not_followed_and_says_so(tmp_path):
    clock = Clock()
    paper = _paper(tmp_path, clock, _cfg("combo.vwap.json"))
    r = Rig(tmp_path, paper=paper)
    try:
        r.enter(BTC, 1, 10_010.0, 20, qty=0.5, fill=10_000.0)
        r.next_minute()
        r.price(BTC, 10_072.0)
        r.loop()
        assert r.ex.trade["own"]["lock"] == pytest.approx(0.1)
        r.paper.exit("TIME", 10_070.0)
        r.loop(2)
        assert r.amt() == 0.05 and r.ex.trade["paper_exit"]["action"] == "stay"
        (_lv, text, _d), = r.events("own_stay")
        assert "paper가 보유 한도 청산으로 닫았습니다 → 자기 잠금 +10%가 있어 보유 한도 청산을 따르지 않고 계속 들고 갑니다" in text
        assert "감독" not in text
    finally:
        r.close()
        paper.close()


def test_the_trend_bots_paper_keeps_its_words(tmp_path):
    clock = Clock()
    paper = _paper(tmp_path, clock, _cfg("combo.trend.json"))
    r = Rig(tmp_path, paper=paper)
    try:
        assert r.ex.time_ko == "감독 청산(시간 정리)"
    finally:
        r.close()
        paper.close()


def test_check_config_names_the_hold_limit_for_the_vwap_bots_executor(tmp_path):
    for name, words in (("combo.vwap.json", "빠른 청산(반대 신호)·감독 청산(추세 판단 뒤집힘)·보유 한도 청산은 자기 첫 잠금 전에만 따름"),
                        ("combo.trend.json", "빠른 청산(반대 신호)과 감독 청산(추세 판단 뒤집힘·시간 정리)은 자기 첫 잠금 전에만 따름")):
        s = Store3(str(tmp_path / name))
        s.put_state("combo_run", 1, {"config": _cfg(name)})
        s.close()
        base = _cfg("executor.live-bybit.json")
        base.update(db=str(tmp_path / "x.db"), paper_db=str(tmp_path / name), net_costs=COSTS,
                    risk={**base["risk"], "kill_file": str(tmp_path / "STOP")})
        cfg = ExecConfig.from_dict(base)
        assert words in "\n".join(ladder_lines(cfg))
