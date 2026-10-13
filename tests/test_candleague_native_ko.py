"""candleague/data/native_ko.json: what each strategy bets on and when ITS OWN "long / short structure has broken" (the 매매법별 구조 기준
screen, js/screens/judge.js; GET /api/judge returns this file).

Sources of the conditions: research/exitflex/native.py (SPEC), native_ds.py, README_KO.md (public Korean explanations) and
candleague/data/strategies_ko.json. The 16 strategies the study's native-exit code knows (candleague.rulex.NATIVE_STUDY: 8 core +
8 DeepSeek-style) and the 11 the league added itself (candleague/native_more.py, native_more_ds.py; rulex.NATIVE_MORE: 6 core + 5
DeepSeek-style) all have conditions: 27 of 27 (rulex.NATIVE_COVERS)."""

from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from candleague import rulex  # noqa: E402

DATA = os.path.join(ROOT, "candleague", "data")
ADDED = {"N02_ST_KST", "N12_ICHI_AO", "N07_ICHI_CMO", "N04_ST_KLINGER", "N23_HA_ST", "N21_ST_RSI_ADX", "F3_BOS", "F15_ORB", "F4_FAN",
        "F6_VWAP_FAIL", "F15_LON_BRK"}
FIELDS = {"kind", "name_ko", "native", "bet_ko", "long_broken_ko", "short_broken_ko", "notes_ko"}


def _load() -> dict:
    with open(os.path.join(DATA, "native_ko.json"), encoding="utf-8") as fh:
        doc = json.load(fh)
    assert set(doc) == {"strategies"}
    return doc["strategies"]


def _picks() -> list:
    with open(os.path.join(DATA, "candidates_owner.json"), encoding="utf-8") as fh:
        return json.load(fh)["candidates"]


def test_native_true_names_are_exactly_the_native_covers():
    """The strategies marked native are the ones candleague.rulex.NATIVE_COVERS lists (core + DeepSeek-style), no more, no less."""
    s = _load()
    native = {n for n, v in s.items() if v["native"] is True}
    covers = set(rulex.NATIVE_COVERS["core"]) | set(rulex.NATIVE_COVERS["ds"])
    assert native == covers and len(native) == 27
    assert native == set(rulex.NATIVE_STUDY["core"]) | set(rulex.NATIVE_STUDY["ds"]) | ADDED
    for kind in ("core", "ds"):
        assert {n for n in native if s[n]["kind"] == kind} == set(rulex.NATIVE_COVERS[kind])


def test_the_eleven_added_strategies_have_their_structure_written_out():
    """The 11 strategies the league gave a structure itself (native_more.py / native_more_ds.py): native true, a long and a short condition,
    and notes that say the criterion is the league's own (not from the study's code)."""
    s = _load()
    assert {n for n in ADDED if n in rulex.NATIVE_MORE["core"] or n in rulex.NATIVE_MORE["ds"]} == ADDED == set(rulex.NATIVE_MORE["core"]) | set(rulex.NATIVE_MORE["ds"])
    for n in ADDED:
        v = s[n]
        assert v["native"] is True and v["long_broken_ko"] and v["short_broken_ko"], n
        assert "리그에서 새로 정했습니다" in v["notes_ko"] and "3봉" not in v["notes_ko"], n
    assert "슈퍼트렌드" in s["N02_ST_KST"]["long_broken_ko"] and "KST" in s["N02_ST_KST"]["long_broken_ko"] and "아래로 꺾인" in s["N02_ST_KST"]["long_broken_ko"]
    assert "클링거" in s["N04_ST_KLINGER"]["short_broken_ko"] and "위로 꺾인" in s["N04_ST_KLINGER"]["short_broken_ko"]
    assert "전환선이 기준선 아래" in s["N07_ICHI_CMO"]["long_broken_ko"] and "구름대 아래" in s["N07_ICHI_CMO"]["long_broken_ko"] and "CMO" in s["N07_ICHI_CMO"]["long_broken_ko"]
    assert "구름대 위" in s["N12_ICHI_AO"]["short_broken_ko"] and "AO" in s["N12_ICHI_AO"]["short_broken_ko"]
    assert "역추세" in s["N21_ST_RSI_ADX"]["notes_ko"] and "RSI" in s["N21_ST_RSI_ADX"]["long_broken_ko"]
    assert "하이킨아시" in s["N23_HA_ST"]["long_broken_ko"] and "슈퍼트렌드" in s["N23_HA_ST"]["long_broken_ko"]
    assert "런던 범위" in s["F15_LON_BRK"]["long_broken_ko"] and "처음" in s["F15_ORB"]["long_broken_ko"]
    assert "스윙 저점" in s["F3_BOS"]["long_broken_ko"] and "스윙 고점" in s["F3_BOS"]["short_broken_ko"]
    assert "가장 짧은 EMA" in s["F4_FAN"]["long_broken_ko"] and "VWAP" in s["F6_VWAP_FAIL"]["long_broken_ko"]


def test_every_strategy_among_the_picks_appears_with_its_kind():
    picks = _picks()
    s = _load()
    names = {p["name"] for p in picks}
    assert len(names) == 27 and names <= set(s) and set(s) == names
    for p in picks:
        assert s[p["name"]]["kind"] == p["kind"], p["id"]
    for n, v in s.items():
        assert set(v) == FIELDS, n
        assert v["kind"] in ("core", "ds") and isinstance(v["native"], bool), n


def test_no_field_is_empty_text():
    """Every text is a real sentence (not blank); a native strategy has its two conditions as text, a non-native one (none today) has null."""
    for n, v in _load().items():
        assert isinstance(v["name_ko"], str) and len(v["name_ko"].strip()) >= 2, n
        for k in ("bet_ko", "notes_ko"):
            assert isinstance(v[k], str) and len(v[k].strip()) >= 8, (n, k)
        for k in ("long_broken_ko", "short_broken_ko"):
            if v["native"]:
                assert isinstance(v[k], str) and len(v[k].strip()) >= 8, (n, k)
            else:
                assert v[k] is None, (n, k)
        for k, x in v.items():
            if isinstance(x, str):
                assert x == x.strip() and "  " not in x, (n, k)


def test_korean_names_agree_with_strategies_ko():
    """strategies_ko.json (the earlier league's 16 strategies) names the study's 16: the same Korean name and kind here."""
    with open(os.path.join(DATA, "strategies_ko.json"), encoding="utf-8") as fh:
        ko = json.load(fh)["strategies"]
    s = _load()
    assert set(ko) == set(rulex.NATIVE_STUDY["core"]) | set(rulex.NATIVE_STUDY["ds"]) and set(ko) <= set(s)
    for n, v in ko.items():
        assert s[n]["name_ko"] == v["ko"] and s[n]["kind"] == v["kind"], n


def test_conditions_follow_the_study_code():
    """A few facts that must stay as native.py / native_ds.py / README_KO.md have them (the file is a translation, nothing invented)."""
    s = _load()
    # native.py SPEC: DOGE exits on EMA fast < slow OR StochRSI K crossing below D; N03 on EMA cross undone OR ADX under the level
    assert "빠른 평균선" in s["DOGE"]["long_broken_ko"] and "K선이 D선 아래" in s["DOGE"]["long_broken_ko"]
    assert "ADX" in s["N03_ADX_GC"]["long_broken_ko"] and "ADX" in s["N03_ADX_GC"]["short_broken_ko"]
    # OBV_S: OBV against its own average
    assert "OBV" in s["OBV_S"]["long_broken_ko"] and "평균선 아래" in s["OBV_S"]["long_broken_ko"] and "평균선 위" in s["OBV_S"]["short_broken_ko"]
    # N13: the pattern's lowest low (short: highest high) or the opposite pattern; N19: the fib line or the slope
    assert "최저가" in s["N13_3OUTSIDE"]["long_broken_ko"] and "최고가" in s["N13_3OUTSIDE"]["short_broken_ko"]
    assert "되돌림 선" in s["N19_FIB_CHOP"]["long_broken_ko"] and "기울기" in s["N19_FIB_CHOP"]["short_broken_ko"]
    # the DeepSeek-style ones: a level (swing low / pattern low / box floor / gap edge ...) or the per-bar flags
    assert "스윙 저점" in s["F10_OTE"]["long_broken_ko"] and "스윙 고점" in s["F10_OTE"]["short_broken_ko"]
    assert "박스 바닥" in s["F5_BOX"]["long_broken_ko"] and "박스 천장" in s["F5_BOX"]["short_broken_ko"]
    assert "틈" in s["F9_FVG"]["long_broken_ko"]
    assert "반대 신호" in s["F7_RF_ONLY"]["long_broken_ko"]
    assert "하나라도" in s["F7_RF_TRIPLE"]["long_broken_ko"] and "하나라도" in s["F7_RF_TRIPLE"]["short_broken_ko"]
    assert "구조" in s["F12_MSS_DISP"]["long_broken_ko"] and "스윙 저점" in s["F12_MSS_DISP"]["long_broken_ko"]


def test_no_private_sources_are_named():
    """Only the public sources feed the file: no result folders, no private reports."""
    raw = open(os.path.join(DATA, "native_ko.json"), encoding="utf-8").read()
    for bad in ("ds_private", "/out/", "research/hunt", "2024", "2025", "2026"):
        assert bad not in raw, bad
    assert not re.search(r"\$\s?[0-9]", raw)                  # no money amounts
