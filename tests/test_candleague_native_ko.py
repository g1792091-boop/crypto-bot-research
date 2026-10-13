"""candleague/data/native_ko.json: what each strategy bets on and when ITS OWN "long / short structure has broken" (the 매매법별 구조 기준
screen, js/screens/judge.js; GET /api/judge returns this file).

Sources of the conditions: research/exitflex/native.py (SPEC), native_ds.py, README_KO.md (public Korean explanations) and
candleague/data/strategies_ko.json. The 16 strategies the study's native-exit code knows (candleague.rulex.NATIVE_COVERS: 8 core +
8 DeepSeek-style) have conditions; the other 11 picks' strategies have no own structure code, so no quick stop / narrowing / native
exit exists for them (the lineup of rules_owner_exits.json): their conditions are null and the notes say so."""

from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from candleague import rulex  # noqa: E402

DATA = os.path.join(ROOT, "candleague", "data")
WEAK = {"N02_ST_KST", "N12_ICHI_AO", "N07_ICHI_CMO", "N04_ST_KLINGER", "N23_HA_ST", "N21_ST_RSI_ADX", "F3_BOS", "F15_ORB", "F4_FAN",
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
    assert native == covers and len(native) == 16
    for kind in ("core", "ds"):
        assert {n for n in native if s[n]["kind"] == kind} == set(rulex.NATIVE_COVERS[kind])


def test_the_weak_clue_strategies_have_no_own_structure():
    """The 11 strategies without own structure code: native false, no long / short condition (null, never invented), and the notes say
    so without claiming the shared 3-bar swing is used for the quick stop (it is not: those picks have no quick stop or narrowing)."""
    s = _load()
    for n in WEAK:
        v = s[n]
        assert v["native"] is False, n
        assert v["long_broken_ko"] is None and v["short_broken_ko"] is None, n
        assert "자체 구조" in v["notes_ko"] and "3봉" not in v["notes_ko"] and "스윙" not in v["notes_ko"], n
        assert "스위칭" in v["notes_ko"], n
    assert {n for n, v in s.items() if v["native"] is False} == WEAK


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
    """Every text is a real sentence (not blank); the conditions are text for the 16 and null for the 11, nothing in between."""
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
    """The 16 strategies strategies_ko.json names carry the same Korean name and kind here."""
    with open(os.path.join(DATA, "strategies_ko.json"), encoding="utf-8") as fh:
        ko = json.load(fh)["strategies"]
    s = _load()
    assert set(ko) == {n for n, v in s.items() if v["native"]}
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
