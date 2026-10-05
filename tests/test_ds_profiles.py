"""paperbot/ds_profiles.py: the 5-year research cards of the 44 DeepSeek definitions and the reel are read straight from
the research output files (research/deepseek200/out, research/reel5m/out) and say which exits the research used."""

from __future__ import annotations

import json
import math
import os
import shutil

import pandas as pd
import pytest

from paperbot import ds_profiles as P
from paperbot.config import DS200_DEFS, REEL_NAME

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "research", "deepseek200", "out", "results.csv")
H1 = os.path.join(ROOT, "research", "reel5m", "out", "h1.json")

pytestmark = pytest.mark.skipif(not (os.path.exists(RESULTS) and os.path.exists(H1)), reason="research output missing")


@pytest.fixture(autouse=True)
def fresh_cache():
    P._CACHE.clear()
    yield
    P._CACHE.clear()


def _finite(o):
    if isinstance(o, dict):
        return all(_finite(v) for v in o.values())
    if isinstance(o, list):
        return all(_finite(v) for v in o)
    return not (isinstance(o, float) and not math.isfinite(o))


def test_every_ds_definition_and_the_reel_have_a_card():
    cards = P.all_profiles()
    assert list(cards) == [d for d, _f, _t in DS200_DEFS] + [REEL_NAME]
    for d, fam, tfs in DS200_DEFS:
        c = cards[d]
        assert c["group"] == "ds200" and c["family"] == fam and c["timeframes"] == list(tfs)
        assert [(r["tf"], r["exit"]) for r in c["rows"]] == [(tf, x) for tf in tfs for x in ("X5_TRAIL2", "X2_SL15_TP3")]
        json.dumps(c, ensure_ascii=False, allow_nan=False)
        assert _finite(c)
    r = cards[REEL_NAME]
    assert r["group"] == "reel" and [(x["tf"], x["exit"]) for x in r["rows"]] == [("5m", "SWING_BAND")]
    json.dumps(r, ensure_ascii=False, allow_nan=False)


def test_ds_numbers_are_results_csv():
    t = pd.read_csv(RESULTS)
    assert len(t) == 342
    seen = 0
    for d, _fam, _tfs in DS200_DEFS:
        for row in P.profile(d)["rows"]:
            src = t[(t["entry"] == d) & (t["tf"] == row["tf"]) & (t["exit"] == row["exit"])]
            assert len(src) == 1
            s = src.iloc[0]
            for k in ("is", "cf", "pre"):
                b = row["periods"][k]
                n = 0 if pd.isna(s[f"{k}_n"]) else int(s[f"{k}_n"])
                assert b["n"] == n
                if n:
                    assert b["net_pct"] == pytest.approx(s[f"{k}_mean_pct"], abs=1e-4)
                    assert b["win_pct"] == pytest.approx(s[f"{k}_win_pct"], abs=1e-2)
                    assert b["hold_bars"] == pytest.approx(s[f"{k}_hold_mean"], abs=1e-2)
                    assert b["hold_hours"] == pytest.approx(s[f"{k}_hold_mean"] * P.TF_MIN[row["tf"]] / 60, abs=1e-2)
                    assert b["per_day"] == pytest.approx(n / P.window_days(row["tf"], k, P.DS_MAX_HOLD), abs=1e-3)
                else:
                    assert b["net_pct"] is None and b["win_pct"] is None
                assert b["small"] == (n < 20)
            seen += 1
    assert seen == 342


def test_window_days_are_the_research_windows():
    # lib_c.window_idx / lib_reel5m.window_idx on BTC's series (warm-up max(300 bars, 30 days), the last hold + 1
    # bars cut at the end), measured once on the bar files: first to last signal-bar time + one bar.
    want = {("15m", "is", 48): 1064.49, ("15m", "cf", 48): 820.49, ("15m", "pre", 48): 547.49,
            ("30m", "pre", 48): 546.98, ("1h", "is", 48): 1062.96, ("4h", "is", 48): 1056.83,
            ("4h", "cf", 48): 812.83, ("4h", "pre", 48): 519.83,
            ("5m", "is", 96): 1064.66, ("5m", "cf", 96): 820.66, ("5m", "pre", 96): 547.66}
    for (tf, k, mh), d in want.items():
        assert P.window_days(tf, k, mh) == pytest.approx(d, abs=0.01), (tf, k)


def test_exits_are_labelled_research_vs_live():
    c = P.profile("F9_FVG")
    assert [e["id"] for e in c["exits"]["research"]] == ["X5_TRAIL2", "X2_SL15_TP3"]
    assert c["exits"]["live"]["id"] == "house" and c["exits"]["same_as_live"] is False
    assert "ATR" in c["note_ko"] and "하우스" in c["note_ko"] and "계단" in c["exits"]["live"]["ko"]
    r = P.profile(REEL_NAME)
    assert r["exits"]["research"][0]["id"] == r["exits"]["live"]["id"] == "SWING_BAND"
    assert r["exits"]["same_as_live"] is True and "릴스 자체 청산" in r["note_ko"]
    for card in (c, r):
        assert card["descriptive_ko"] and set(card["units_ko"]) >= {"per_day", "net_pct", "win_pct", "hold"}
        assert [p["key"] for p in card["periods"]] == ["is", "cf", "pre"]


def test_reel_numbers_are_h1_json():
    with open(H1, encoding="utf-8") as fh:
        h1 = json.load(fh)
    row = P.profile(REEL_NAME)["rows"][0]
    for k, src in (("is", "is"), ("cf", "oos"), ("pre", "pre")):
        b, s = row["periods"][k], h1["periods"][src]
        assert b["n"] == s["n"]
        assert b["net_pct"] == pytest.approx(s["mean_net_pct"], abs=1e-4)
        assert b["win_pct"] == pytest.approx(s["win_pct"], abs=1e-2)
        assert b["hold_bars"] == s["hold_median"] and b["hold_hours"] == pytest.approx(s["hold_median"] * 5 / 60, abs=1e-2)
        assert b["per_day"] == pytest.approx(s["n"] / P.window_days("5m", k, P.REEL_MAX_HOLD), abs=1e-3)
    card = P.profile(REEL_NAME)
    assert card["research"]["pass"] is bool(h1["pass"])
    pv = pd.read_csv(os.path.join(ROOT, "research", "reel5m", "out", "per_variant.csv"), index_col=0)
    assert [v["variant"] for v in card["variants"]] == list(pv.index)
    for v in card["variants"]:
        assert v["net_pct"]["cf"] == pytest.approx(pv.loc[v["variant"], "cf_mean_pct"], abs=1e-4)


def test_other_names_have_no_card():
    assert P.profile("S5_DONCHIAN_MFI") is None
    assert P.profile("RANDOM_1") is None
    assert P.profile("") is None


def test_missing_research_files_give_none(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DS_RESULTS", str(tmp_path / "results.csv"))
    monkeypatch.setattr(P, "REEL_OUT", str(tmp_path))
    assert P.profile("F9_FVG") is None and P.profile(REEL_NAME) is None and P.all_profiles() == {}


def test_card_follows_a_changed_file(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    for f in ("results.csv", "summary.json"):
        shutil.copy(os.path.join(ROOT, "research", "deepseek200", "out", f), out / f)
    monkeypatch.setattr(P, "DS_RESULTS", str(out / "results.csv"))
    monkeypatch.setattr(P, "DS_SUMMARY", str(out / "summary.json"))
    n0 = P.profile("F2_DEMARK")["rows"][0]["periods"]["is"]["n"]
    t = pd.read_csv(out / "results.csv")
    t.loc[(t["entry"] == "F2_DEMARK") & (t["tf"] == "15m") & (t["exit"] == "X5_TRAIL2"), "is_n"] = n0 + 7
    t.to_csv(out / "results.csv", index=False)
    os.utime(out / "results.csv", ns=(1, os.stat(out / "results.csv").st_mtime_ns + 10**9))
    assert P.profile("F2_DEMARK")["rows"][0]["periods"]["is"]["n"] == n0 + 7


def test_table_rows_in_display_order():
    rows = P.table_ko(P.profile("F15_ORB"), "X5_TRAIL2")
    assert [(r["tf"], r["period"]) for r in rows] == [(tf, k) for tf in ("15m", "30m", "1h", "4h") for k in ("is", "cf", "pre")]
    assert all(r["period_ko"] for r in rows)


def test_card_has_profile_card_keys_and_one_row_per_timeframe():
    tfs = {d: t for d, _f, t in DS200_DEFS}
    keys = {"strategy", "name_ko", "style", "trend_share", "hold", "least_bad_tf", "rare", "rows", "data_source",
            "note", "note_5m"}
    if P.profile("F9_FVG") is None:
        pytest.skip("research files missing")
    c = P.card("F9_FVG")
    assert keys <= set(c) and c["exit"] == "X5_TRAIL2" and not c["same_exits_as_live"]
    assert [r["tf"] for r in c["rows"]] == list(tfs["F9_FVG"])
    assert "X5_TRAIL2/X2_SL15_TP3 ≠ 실계좌 사다리" in c["exits_ko"] and "NOT the live" in c["note"]
    full = {r["tf"]: r for r in P.profile("F9_FVG")["rows"] if r["exit"] == "X5_TRAIL2"}
    for r in c["rows"]:
        b = full[r["tf"]]["periods"]
        assert r["net_pct_is"] == b["is"]["net_pct"] and r["net_pct_cf"] == b["cf"]["net_pct"]
        assert r["trades_per_day"] == r["signals_per_day"] == b["is"]["per_day"]
        assert r["win_rate"] == pytest.approx(b["is"]["win_pct"] / 100, abs=1e-4)
    assert "적습니다" in c["note_ko"] and "수수료·펀딩만" in c["cost_note_ko"]
    assert P.card("S5_DONCHIAN_MFI") is None and P.card("NOPE") is None


def test_reel_card_is_its_own_exits_and_names_the_grid():
    if P.profile("REEL_H1") is None:
        pytest.skip("research/reel5m/out missing")
    c = P.card("REEL_H1")
    assert c["same_exits_as_live"] and c["exit"] == "SWING_BAND" and [r["tf"] for r in c["rows"]] == ["5m"]
    assert "연구·라이브 같은 청산" in c["exits_ko"] and "슬리피지·펀딩" in c["cost_note_ko"]
    g = c["research"].get("grid")
    if g is not None:
        assert g["configs"] == 40 and f"통과 {g['candidates']}개" in c["research"]["conclusion_ko"]
