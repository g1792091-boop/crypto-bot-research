"""나스닥 개장 뒤 30분 진입 안 함 (owners 2026-10-19 "나스닥 개장하고 30분 진입금지"): paperbot/combo.py us_open_pause
and ComboConfig.us_open_pause_min, set to 30 in the live config and every shadow (so they stay comparable)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from paperbot import combo as C

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"


def ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


@pytest.mark.parametrize("iso, blocked", [
    ("2026-10-19T13:29:00Z", False),   # 22:29 KST, a minute before the open (New York on summer time)
    ("2026-10-19T13:30:00Z", True),    # 09:30 New York = 22:30 KST
    ("2026-10-19T13:59:00Z", True),
    ("2026-10-19T14:00:00Z", False),   # 30 minutes later: entries again
    ("2026-12-01T13:30:00Z", False),   # winter: the open is 14:30 UTC = 23:30 KST
    ("2026-12-01T14:30:00Z", True),
    ("2026-12-01T14:59:00Z", True),
    ("2026-10-24T13:35:00Z", False),   # Saturday
    ("2026-11-26T14:35:00Z", False),   # Thanksgiving, NYSE closed
])
def test_the_window(iso, blocked):
    why = C.us_open_pause(ms(iso), 30)
    assert bool(why) is blocked
    if blocked:
        assert why == "나스닥 개장 뒤 30분 진입 안 함 (뉴욕 09:30 개장)"


def test_the_config_value_is_checked():
    base = json.loads((DEPLOY / "combo.live-ac.json").read_text(encoding="utf-8"))
    assert base["us_open_pause_min"] == 30 and C.ComboConfig.from_dict(base).problems() == []
    for bad in (0, -5, 241, 1.5, "30", True):
        assert any("us_open_pause_min" in p for p in C.ComboConfig.from_dict({**base, "us_open_pause_min": bad}).problems()), bad
    assert C.ComboConfig.from_dict({**base, "us_open_pause_min": None}).problems() == []


def test_live_and_every_shadow_pause_at_the_open():
    for p in [DEPLOY / "combo.live-ac.json", *sorted(DEPLOY.glob("combo.shadow-*.json"))]:
        assert json.loads(p.read_text(encoding="utf-8"))["us_open_pause_min"] == 30, p.name


def test_check_config_says_so(capsys):
    assert C.main(["check-config", "--config", str(DEPLOY / "combo.live-ac.json")]) == 0
    out = capsys.readouterr().out
    assert "- 나스닥 개장 뒤 30분 진입 안 함" in out and out.rstrip().splitlines()[-1] == "준비됨"


@pytest.mark.parametrize("iso, blocked", [
    ("2026-10-19T12:59:00Z", False),   # 21:59 KST (New York on summer time)
    ("2026-10-19T13:00:00Z", True),    # 22:00 KST = 09:00 New York, 30 minutes before the open
    ("2026-10-19T13:29:00Z", True),
    ("2026-10-19T13:30:00Z", True),    # the open
    ("2026-10-19T13:59:00Z", True),    # 22:59 KST
    ("2026-10-19T14:00:00Z", False),   # 23:00 KST: entries again
    ("2026-11-02T13:59:00Z", False),   # winter (from 11/2): 22:59 KST
    ("2026-11-02T14:00:00Z", True),    # 23:00 KST = 09:00 New York
    ("2026-11-02T14:59:00Z", True),    # 23:59 KST
    ("2026-11-02T15:00:00Z", False),   # 00:00 KST
    ("2026-10-24T13:10:00Z", False),   # Saturday
    ("2026-11-26T14:10:00Z", False),   # Thanksgiving, NYSE closed
])
def test_the_window_with_30_minutes_before_the_open(iso, blocked):
    # owners 2026-10-21 night: "나스닥 개장전 30분도 진입금지로 하자 ... 22시00분~23시00분" (entries only)
    why = C.us_open_pause(ms(iso), 30, 30)
    assert bool(why) is blocked
    if blocked:
        assert why == "나스닥 개장 앞 30분·뒤 30분 진입 안 함 (뉴욕 09:00~10:00, 09:30 개장)"


def test_the_words():
    assert C.us_open_ko(30) == "나스닥 개장 뒤 30분"
    assert C.us_open_ko(30, 30) == "나스닥 개장 앞 30분·뒤 30분"
    assert C.us_open_ko(0, 30) == "나스닥 개장 앞 30분"
    assert C.us_open_pause(ms("2026-10-19T13:10:00Z"), 0, 30) and not C.us_open_pause(ms("2026-10-19T13:30:00Z"), 0, 30)


def test_the_trend_bot_pauses_30_minutes_before_and_after_the_open(capsys):
    base = json.loads((DEPLOY / "combo.trend.json").read_text(encoding="utf-8"))
    assert base["us_open_pause_min"] == 30 and base["us_open_pre_min"] == 30
    assert C.ComboConfig.from_dict(base).problems() == []
    for bad in (0, -5, 241, 1.5, "30", True):
        assert any("us_open_pre_min" in p for p in C.ComboConfig.from_dict({**base, "us_open_pre_min": bad}).problems()), bad
    assert C.main(["check-config", "--config", str(DEPLOY / "combo.trend.json")]) == 0
    out = capsys.readouterr().out
    assert "- 나스닥 개장 앞 30분·뒤 30분 진입 안 함" in out and "서머타임 22:00~23:00 / 겨울 23:00~00:00" in out
    assert out.rstrip().splitlines()[-1] == "준비됨"
