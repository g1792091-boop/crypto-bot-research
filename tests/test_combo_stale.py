"""The combined bot's ``unlocked_close_min`` (owners 10-26 "둘 다 해줘": the VWAP shadow of research/opentime A3, a
position not at its first lock 4 hours after its entry is closed, exit "STALE") and its shadow config: the live VWAP
config with that one change, its own database, no Telegram; no running bot has it."""
from __future__ import annotations

import json
import os

import pytest

from paperbot import combo as C

from test_combo import MIN, World, cfg_of

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _deploy(name):
    with open(os.path.join(ROOT, "deploy", name), encoding="utf-8") as fh:
        return json.load(fh)


def _open(w):
    B = w.now - w.now % MIN + 15 * MIN
    w.add_minutes(w.now - w.now % MIN, 15)
    w.signal("V39_ALL", "BTCUSDT", 1, B)
    w.add_minutes(B, 1)
    w.now = B + 65_000
    w.run.poll()
    assert w.engine().position is not None and w.engine().position.entry_time == B
    return B


def _world(tmp_path, **kw):
    w = World(tmp_path, **kw)
    w.now += 5_000
    w.run.poll()
    return w


def _trade(w):
    return json.loads(w.store.conn.execute("SELECT data FROM trades WHERE account_id = ? ORDER BY rowid DESC",
                                           (C.ACCOUNT,)).fetchone()[0])


def test_not_locked_in_4_hours_closes_at_the_open_of_that_minute(tmp_path):
    w = _world(tmp_path, unlocked_close_min=240)
    B = _open(w)
    w.add_minutes(B + MIN, 239)                                  # minutes B+1 .. B+239: still open
    w.now = B + 240 * MIN + 5_000
    w.run.poll()
    assert w.engine().position is not None and w.engine().position.lock_roe is None
    w.add_minutes(B + 240 * MIN, 1)
    w.now = B + 241 * MIN + 5_000
    w.run.poll()
    assert w.engine().position is None
    t = _trade(w)
    assert t["exit_reason"] == "STALE" and t["exit_time"] == B + 240 * MIN
    assert abs(t["exit_price"] - w.px["BTCUSDT"] * (1 - 0.0002)) < 1e-6
    assert t["context"]["exit_why"] == "4시간 안에 첫 잠금에 못 닿음"
    assert "잠금 전 시간 정리(4시간 안에 첫 잠금에 못 닿음)" in C.exit_text(w.cfg, w.engine().trades[-1])


def test_a_locked_position_stays(tmp_path):
    w = _world(tmp_path, unlocked_close_min=240)
    B = _open(w)
    w.add_minutes(B + MIN, 20, move={"BTCUSDT": 0.003})          # +6 %: the ladder locks
    w.now = B + 21 * MIN + 5_000
    w.run.poll()
    assert w.engine().position is not None and w.engine().position.lock_roe is not None
    w.add_minutes(B + 21 * MIN, 230)
    w.now = B + 251 * MIN + 5_000
    w.run.poll()
    assert w.engine().position is not None                       # past 4 hours, but locked: the ladder decides


def test_off_keeps_the_position(tmp_path):
    w = _world(tmp_path)
    B = _open(w)
    w.add_minutes(B + MIN, 300)
    w.now = B + 301 * MIN + 5_000
    w.run.poll()
    assert w.engine().position is not None


def test_config_values_and_words(tmp_path):
    assert cfg_of(tmp_path).unlocked_close_min is None
    for bad in (0, -5, 10081, True, 2.5, "240"):
        assert any("unlocked_close_min" in x for x in cfg_of(tmp_path, unlocked_close_min=bad).problems()), bad
    assert cfg_of(tmp_path, unlocked_close_min=240).problems() == []
    assert C.gate_lines(cfg_of(tmp_path, unlocked_close_min=240))[-1] == "진입 4시간 안에 첫 잠금에 못 닿으면 시장가 청산"
    assert C.gate_lines(cfg_of(tmp_path, unlocked_close_min=90))[-1] == "진입 90분 안에 첫 잠금에 못 닿으면 시장가 청산"


def test_the_shadow_is_the_live_vwap_config_with_one_change():
    live, sh = _deploy("combo.vwap.json"), _deploy("combo.shadow-vwap-4h.json")
    assert sh["db"] == "/var/lib/paperbot/combo/shadow-vwap-4h.db" and sh["telegram"] is False   # the unit's own check
    assert sh["unlocked_close_min"] == 240 and sh["paper_db"] == live["paper_db"]
    rest = {k: v for k, v in sh.items() if k not in ("db", "telegram", "name", "unlocked_close_min")}
    assert rest == {k: v for k, v in live.items() if k not in ("db", "telegram", "name")}
    assert C.ComboConfig.from_dict(sh).problems() == []


@pytest.mark.parametrize("name", ["combo.vwap.json", "combo.trend.json", "combo.range.json", "combo.live15.json"])
def test_no_running_bot_has_it(name):
    assert C.ComboConfig.from_dict(_deploy(name)).unlocked_close_min is None
