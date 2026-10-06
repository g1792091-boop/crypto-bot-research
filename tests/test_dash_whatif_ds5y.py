"""ana7b: 만약 실험실 (#/whatif; /api/v4/whatif + /paper, dash/more/whatiflab.py) and 딥시크 5년 결과 (순위표 › 딥시크;
/api/v4/ds5y, dash/more/ds5y.py). Read-only and descriptive. Hand-computed pooling of the 5-year cells, the nightly
shadow pairs on a hand-made daily3.db (DeepSeek and the 5m coin flips never read), the tested-settings table against
the committed research files, the waiting states (no daily3.db, no rows yet, no 5-year file, a running job N/342, a
partial file), the endpoint shapes and that no database is written, and the cards rendered in node with the tiny DOM
of tests/anasyn_dom.mjs."""
import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from anasyn_world import DAY, blank, build, kst  # noqa: E402
from paperbot.dash import more as MORE  # noqa: E402
from paperbot.dash.more import ds5y as DS  # noqa: E402
from paperbot.dash.more import whatiflab as W  # noqa: E402
from whatif_world import build_daily  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
T0 = kst(2026, 10, 5, 0, 30)
LS_COLS = ["signals", "trades", "mean_roe", "mean_eq", "win_rate", "liq_share", "mean_eq_p1", "mean_eq_p2", "p_pos", "p_neg",
           "t", "bust_p1", "bust_p2", "mult_p1", "mult_p2", "rules_ok_share", "mean_eq_rules_ok"]
EX_COLS = ["trades", "mean_roe", "mean_eq", "mean_eq_p1", "mean_eq_p2", "win_rate", "tp_share", "lock_share", "liq_share",
           "mean_held", "bust_p1", "bust_p2", "mult_p1", "mult_p2", "paired_n", "paired_n_p1", "paired_n_p2", "diff", "diff_p1",
           "diff_p2", "p_better", "p_worse"]
S1, S2 = "S1_EMA_RSI_CHOP", "S2_ST_ROC"


def _read(rel):
    with open(os.path.join(V4, rel), encoding="utf-8") as f:
        return f.read()


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ---------------------------------------------------------------- the tested settings
def test_settings_are_exactly_the_tested_combinations():
    ss = W.settings()
    assert len(ss) == 34 and len({s["id"] for s in ss}) == 34
    cur = [s for s in ss if s["paper"] == "base"]
    assert len(cur) == 1 and cur[0]["five"] == "levstop:tiers|2.0"
    assert {k: cur[0][k] for k in W.CURRENT} == W.CURRENT
    from paperbot.agents.riskreward import ALL_SHADOWS
    assert {s["paper"] for s in ss if s["paper"]} - {"base"} <= set(ALL_SHADOWS)
    assert set(W.VARIANTS) == set(ALL_SHADOWS)
    C = W.controls()
    for s in ss:                                   # every value a setting uses is a control value, and back
        for k in ("stop", "tp", "time", "lev"):
            assert s[k] in [o["v"] for o in C[k]], (s, k)
        assert s["lock"] is None or s["lock"] in [o["v"] for o in C["lock"]]
        assert s["five"] or s["paper"], s          # never a setting nobody tested
        if s["tp"] in ("tp1R", "tp1.5R", "tp2R", "tp3R"):
            assert s["lock"] is None               # a fixed take-profit has no ladder, so no lock step
    # one change at a time for the shadows; two (leverage x stop) only on the 5-year side
    two = [s for s in ss if s["stop"] != 2.0 and s["lev"] != "rule"]
    assert len(two) == 15 and all(s["paper"] is None and s["five"].startswith("levstop:") for s in two)
    assert next(s for s in ss if s["lev"] == "50m50")["five"] is None
    assert {s["paper"] for s in ss if s["lock"] in (0.15, 0.2, 0.3)} == {"lock15", "lock20", "lock30"}
    assert next(s for s in ss if s["time"] == "bars")["five"] is None
    assert next(s for s in ss if s["tp"] == "ladder_tp2R")["paper"] == "ladder_cap2R"


def test_every_five_year_arm_exists_in_the_committed_files():
    if not (os.path.exists(W.LEVSTOP_JSON) and os.path.exists(W.EXITSTYLE_JSON)):
        pytest.skip("research outputs not in this checkout")
    v = W.view(None, None)
    fy = v["five_year"]
    for s in v["settings"]:
        if s["five"]:
            src, arm = s["five"].split(":", 1)
            assert fy[src]["ready"] and arm in fy[src]["arms"], s
    # today's 5-year reference: levstop tiers|2.0 is exitstyle's ladder number for number (its prereg checks it)
    ref, lad = fy["levstop"]["arms"]["tiers|2.0"], fy["exitstyle"]["arms"]["ladder"]
    assert ref["trades"] == lad["trades"] and ref["busts"] == lad["busts"] and ref["accounts"] == lad["accounts"]
    assert ref["mean_eq"] == pytest.approx(lad["mean_eq"], abs=1e-6) and ref["cells_pos"] == lad["cells_pos"]
    with open(W.EXITSTYLE_JSON, encoding="utf-8") as f:
        prim = json.load(f)["summary"]["primary"]
    # the pooled 36 x 15m-4h equals the research's own summary (15m-4h = its primary scope)
    for arm in ("ladder", "tp2R", "ladder_tp2R"):
        a = fy["exitstyle"]["arms"][arm]
        assert a["mean_eq"] == pytest.approx(prim[arm]["pooled_mean_eq"], abs=2e-6)
        assert (a["busts"], a["accounts"], a["cells_pos"]) == (prim[arm]["busts"], prim[arm]["accounts"], prim[arm]["cells_mean_positive"])
    one = W.view(S1, "1h")["five_year"]["levstop"]["arms"]["tiers|2.0"]
    assert one["cells"] == 1 and "mean_eq_p1" in one and "mean_eq_p2" in one
    assert "mean_eq_p1" not in fy["levstop"]["arms"]["tiers|2.0"]       # no per-period trade counts to pool them


def test_scope_is_checked():
    from fastapi import HTTPException
    assert W.scope(None, None)["tfs"] == ["15m", "30m", "1h", "4h"]
    assert W.scope(S1, "4h") == {"strategy": S1, "tf": "4h", "name_ko": W.strategies_ko()[S1], "tfs": ["4h"]}
    for bad in (("F1_RSI_DIV", None), ("NOPE", None), ("x;drop", None), (None, "5m"), (None, "1d")):
        with pytest.raises(HTTPException):
            W.scope(*bad)


# ---------------------------------------------------------------- 5 years, by hand
def test_levstop_pooling_by_hand():
    def row(trades, mean_eq, win, liq, p1, p2, b1, b2, m1, m2):
        return [trades * 2, trades, mean_eq * 3, mean_eq, win, liq, p1, p2, 0.5, 0.5, 0.0, b1, b2, m1, m2, None, None]
    doc = {"columns": LS_COLS, "cells": {
        "X|15m": {"tiers|2.0": row(100, -0.01, 0.6, 0.0, -0.02, 0.01, 1, 0, 0.5, 1.2)},
        "X|1h": {"tiers|2.0": row(300, 0.002, 0.5, 0.01, 0.001, 0.003, 0, 0, 1.1, 1.3)},
        "X|4h": {"tiers|2.0": row(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0, 1.0, 1.0)}}}
    p = W.pool_levstop(doc, ["X|15m", "X|1h", "X|4h", "X|30m"], "tiers|2.0")
    assert (p["cells"], p["cells_traded"], p["trades"]) == (3, 2, 400)
    assert p["mean_eq"] == pytest.approx(-0.001, abs=1e-6) and p["win_rate"] == pytest.approx(0.525, abs=1e-6)
    assert p["liq_share"] == pytest.approx(0.0075, abs=1e-6) and (p["busts"], p["accounts"]) == (1, 6)
    assert p["mult_median"] == pytest.approx(1.05, abs=1e-6)                     # 0.5 1.0 1.0 1.1 1.2 1.3
    assert (p["cells_pos"], p["cells_pos_p1"], p["cells_pos_p2"], p["cells_both"]) == (1, 1, 2, 1)
    one = W.pool_levstop(doc, ["X|15m"], "tiers|2.0")
    assert one["mean_eq_p1"] == pytest.approx(-0.02, abs=1e-6) and one["mean_eq_p2"] == pytest.approx(0.01, abs=1e-6)
    assert W.pool_levstop(doc, ["X|15m"], "10|2.0")["cells"] == 0


def test_exitstyle_pooling_by_hand():
    def row(trades, mean_eq, p1, n1, p2, n2, diff, d1, d2):
        return [trades, mean_eq * 3, mean_eq, p1, p2, 0.5, 0.3, 0.0, 0.0, 9.0, 0, 1, 1.0, 0.5, n1 + n2, n1, n2, diff, d1, d2, 0.5, 0.5]
    doc = {"columns": EX_COLS, "cells": {"X|15m": {"tp2R": row(100, -0.01, -0.02, 60, 0.005, 40, 0.001, 0.002, -0.0005)},
                                         "X|1h": {"tp2R": row(50, 0.004, 0.01, 10, 0.0028, 40, -0.002, 0.0, -0.0025)}}}
    p = W.pool_exitstyle(doc, ["X|15m", "X|1h"], "tp2R")
    assert p["trades"] == 150 and p["paired"] == 150
    assert p["mean_eq"] == pytest.approx((100 * -0.01 + 50 * 0.004) / 150, abs=1e-6)
    assert p["mean_eq_p1"] == pytest.approx((60 * -0.02 + 10 * 0.01) / 70, abs=1e-6) and p["mean_eq_p2"] == pytest.approx(0.0039, abs=1e-6)
    assert p["diff"] == pytest.approx(0.0, abs=1e-12) and p["diff_p2"] == pytest.approx(-0.0015, abs=1e-6)
    assert p["diff_p1"] == pytest.approx(0.12 / 70, abs=1e-6) and p["cells_better"] == 1 and (p["busts"], p["accounts"]) == (2, 4)


def test_five_year_coin_flips_by_hand(tmp_path):
    path = tmp_path / "accounts.csv"
    cols = ["tf", "strategy", "window", "k", "final", "multiple", "max_dd", "bust", "bust_ts", "trades", "signals", "busy",
            "rejected", "win", "mean_R", "lock_exits", "liquidations", "lev50", "lev40", "lev30", "lev20"]
    rows = [("15m", "RANDOM_1", "is", "2.0", 10, 0.5, -0.1, "True"), ("15m", "RANDOM_2", "cf", "2.0", 30, 0.6, 0.02, "False"),
            ("15m", S1, "is", "2.0", 20, 0.55, -0.05, "False"), ("15m", S2, "is", "2.0", 99, 0.1, 0.9, "True"),
            ("4h", "RANDOM_1", "is", "2.0", 1000, 0.9, 0.5, "False"), ("15m", "RANDOM_1", "is", "1.5", 5, 0.2, -0.3, "True")]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for tf, s, win, k, n, wr, mr, bust in rows:
            w.writerow([tf, s, win, k, 1, 1, 0, bust, "", n, n, 0, 0, wr, mr, 0, 0, 0, 0, 0, 0])
    c = W.coin_five_year(W.scope(S1, "15m"), str(path))
    f2, c2 = c["by_k"]["2.0"]["flips"], c["by_k"]["2.0"]["core"]
    assert (f2["accounts"], f2["trades"], f2["busts"]) == (2, 40, 1)
    assert f2["mean_r"] == pytest.approx(-0.01) and f2["win_rate"] == pytest.approx(0.575)
    assert (c2["accounts"], c2["trades"], c2["mean_r"]) == (1, 20, pytest.approx(-0.05))
    assert c["by_k"]["1.5"]["flips"]["trades"] == 5 and set(c["by_k"]) == {"1.5", "2.0"}
    assert W.coin_five_year(W.scope(None, None), str(tmp_path / "none.csv"))["ready"] is False


def test_missing_research_files_say_so(tmp_path):
    fy = W.five_year(W.scope(None, None), levstop_path=str(tmp_path / "a.json"), exitstyle_path=str(tmp_path / "b.json"),
                     coin_path=str(tmp_path / "c.csv"))
    assert fy["levstop"]["ready"] is False and "levstop.json" in fy["levstop"]["why"]
    assert fy["exitstyle"]["ready"] is False and fy["coin"]["ready"] is False


# ---------------------------------------------------------------- the nightly shadows, by hand
def _hand_world(tmp_path, rows):
    db = str(tmp_path / "paper3.db")
    blank(db, T0, [(f"{S1}@15m", "strategy"), (f"{S2}@1h", "strategy"), ("RANDOM_1@15m", "random"),
                   ("RANDOM_1@5m", "random"), ("F1_RSI_DIV@15m", "ds200")]).close()
    dd = str(tmp_path / "daily3.db")
    from paperbot.daily3 import SCHEMA
    d = sqlite3.connect(dd)
    d.executescript(SCHEMA)
    for kind, aid, bc, pe, resolved, reason in rows:
        roe = None if pe is None else pe / 0.3
        d.execute("INSERT INTO shadows VALUES (?, '2026-10-06', ?, ?, 'BTCUSDT', ?, 1, 1, ?, ?, ?, ?)",
                  (f"{kind}|{aid}|BTCUSDT|{bc}", kind, aid, aid.split("@")[1], roe, reason, resolved,
                   json.dumps({} if pe is None else {"pnl_equity": pe})))
    d.execute("INSERT INTO reports VALUES ('2026-10-06', ?, '{}')", (T0 + 2 * DAY,))
    d.commit()
    d.close()
    return db, dd


ROWS = [("base", f"{S1}@15m", 1, 0.01, 1, "LOCK"), ("lock15", f"{S1}@15m", 1, 0.02, 1, "LOCK"),
        ("base", f"{S1}@15m", 2, -0.02, 1, "SL"), ("lock15", f"{S1}@15m", 2, -0.03, 1, "SL"),
        ("lock15", f"{S1}@15m", 3, None, 0, None),                                  # not closed yet
        ("lev50m50", f"{S1}@15m", 1, None, 1, None),                                # sizing refused: not entered
        ("base", f"{S2}@1h", 5, 0.04, 1, "LOCK"), ("lock15", f"{S2}@1h", 5, 0.05, 1, "LOCK"),
        ("tp2R", f"{S2}@1h", 5, 0.06, 1, "TP"), ("lev50", f"{S2}@1h", 5, -0.3, 1, "LIQ"),
        ("base", "RANDOM_1@15m", 1, -0.01, 1, "SL"), ("lock15", "RANDOM_1@15m", 1, 0.0, 1, "SL"),
        ("base", "RANDOM_1@5m", 1, -0.5, 1, "SL"), ("lock15", "RANDOM_1@5m", 1, 0.5, 1, "TP"),       # own exits: never read
        ("base", "F1_RSI_DIV@15m", 1, -0.4, 1, "SL"), ("lock15", "F1_RSI_DIV@15m", 1, 0.4, 1, "LOCK")]   # DeepSeek: never


def test_shadow_pairs_by_hand(tmp_path):
    db, dd = _hand_world(tmp_path, ROWS)
    a = W.paper_all(db, dd, T0 + 3 * DAY)
    assert a["ready"] and a["accounts"] == {"core": 2, "coin": 1} and a["report"]["day"] == "2026-10-06"
    assert set(a["scopes"]) == {"core", "core|15m", "core|1h", f"core|{S1}", f"core|{S1}|15m", f"core|{S2}", f"core|{S2}|1h",
                                "coin", "coin|15m"}                  # no DeepSeek, no 5m scope at all
    core = W.paper_scope(a, W.scope(None, None))
    assert core["base"] == {"trades": 3, "mean_eq": pytest.approx(0.01, abs=1e-6)}
    lk = core["variants"]["lock15"]
    assert lk["trades"] == 3 and lk["open"] == 1 and lk["small"]
    assert lk["mean_eq"] == pytest.approx(0.04 / 3, abs=1e-6) and lk["base_mean_eq"] == pytest.approx(0.01, abs=1e-6)
    assert lk["vs_base_eq"] == pytest.approx(0.01 / 3, abs=1e-6)
    assert lk["better_share"] == pytest.approx(2 / 3, abs=1e-4) and lk["worse_share"] == pytest.approx(1 / 3, abs=1e-4)
    assert core["variants"]["lev50m50"] == {"trades": 0, "not_entered": 1, "small": True}
    assert core["variants"]["tp2R"]["tp"] == 1 and core["variants"]["lev50"]["liq"] == 1
    assert core["variants"]["lev50"]["base_liq"] == 0
    one = W.paper_scope(a, W.scope(S1, "15m"))
    assert one["base"]["trades"] == 2 and one["variants"]["lock15"]["vs_base_eq"] == pytest.approx(0.0, abs=1e-12)
    assert one["coin"]["base"]["trades"] == 1                         # the coin flips of the same timeframe
    assert one["coin"]["variants"]["lock15"]["vs_base_eq"] == pytest.approx(0.01, abs=1e-6)
    hour = W.paper_scope(a, W.scope(None, "1h"))
    assert hour["base"]["trades"] == 1 and hour["coin"]["base"]["trades"] == 0   # no 1h coin flip in this world
    text = json.dumps(a)
    assert "F1_RSI_DIV" not in text and "RANDOM_1@5m" not in text


def test_shadow_waiting_states(tmp_path):
    db, dd = _hand_world(tmp_path, [])
    a = W.paper_all(db, None, T0 + DAY)
    assert a["ready"] is False and "밤 점검 기록이 아직 없습니다" in a["why"]
    p = W.paper_scope(a, W.scope(None, None))
    assert p["ready"] is False and "scopes" not in p
    a = W.paper_all(db, dd, T0 + DAY)                                  # a report, but no shadow rows yet
    assert a["ready"] and a["rows"] == 0
    p = W.paper_scope(a, W.scope(None, None))
    assert p["base"] == {"trades": 0, "mean_eq": None} and p["variants"] == {}
    assert "paper3.db" in W.paper_all(str(tmp_path / "none.db"), dd, T0)["why"]
    # the background cache keeps a not-ready answer 60 s only (an 'error'), a ready one for the report's 3 hours
    assert W.paper_job(db, None, T0 + DAY)["error"] and "error" not in W.paper_job(db, dd, T0 + DAY)


def test_synthetic_world_shadows_cover_every_variant(tmp_path):
    db, dd = str(tmp_path / "paper3.db"), str(tmp_path / "daily3.db")
    info = build(db, days=6)
    build_daily(db, dd, until_ms=info["now"])
    a = W.paper_all(db, dd, info["now"])
    v = a["scopes"]["core"]["variants"]
    assert set(v) == set(W.VARIANTS) and all(c["trades"] > 0 for c in v.values())
    assert a["scopes"]["coin"]["base"]["trades"] > 0 and not [k for k in a["scopes"] if "F1_" in k or k.endswith("|5m")]


# ---------------------------------------------------------------- 딥시크 5년 결과
def _write_results(folder, rows):
    cols = ["tf", "entry", "exit", "family"] + [f"{p}_{c}" for p, *_r in DS.PERIODS for c in DS.COLS] + list(DS.STAGES) + ["max_lev"]
    with open(os.path.join(folder, "results.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def test_ds5y_states(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    v = DS.view(str(empty))
    assert v["state"] == "absent" and v["done"] == 0 and v["total"] == 342 and "아직" in v["absent_ko"] and "defs" not in v
    run = tmp_path / "run"
    run.mkdir()
    (run / "run.log").write_text("15m: 2321522 trades, 88 configs so far, 94s\n30m: 1272618 trades, 176 configs so far, 142s\n")
    v = DS.view(str(run))
    assert v["state"] == "running" and v["done"] == 176 and "계산하는 중" in v["absent_ko"] and "아직 시작 안 함" not in v["absent_ko"]
    part = tmp_path / "part"
    part.mkdir()
    base = {"is_n": 100, "is_win_pct": 40, "is_mean_pct": -0.1, "cf_n": 50, "cf_mean_pct": 0.2, "pre_n": 0,
            "is_own_final_x": 6e-18, "stage1": "True", "all3_positive": "False", "max_lev": 31}
    _write_results(str(part), [{"tf": "15m", "entry": "F1_RSI_DIV", "exit": "X5_TRAIL2", **base},
                               {"tf": "15m", "entry": "F1_RSI_DIV", "exit": "X5_TRAIL2", **base, "is_n": 1},      # duplicate
                               {"tf": "15m", "entry": "F1_RSI_DIV", "exit": "X2_SL15_TP3", **base},
                               {"tf": "4h", "entry": "F15_ORB", "exit": "X2_SL15_TP3", **base},
                               {"tf": "4h", "entry": "F15_OPEN0930", "exit": "X5_TRAIL2", **base},              # no 4h config
                               {"tf": "15m", "entry": "ZZ_UNKNOWN", "exit": "X5_TRAIL2", **base}])
    v = DS.view(str(part))
    assert v["state"] == "partial" and v["done"] == 3 and v["absent_ko"]
    d = {e["id"]: e for e in v["defs"]}
    assert set(d) == {"F1_RSI_DIV", "F15_ORB"} and d["F1_RSI_DIV"]["family"] == "F1" and d["F1_RSI_DIV"]["tfs"] == ["15m"]
    c = d["F1_RSI_DIV"]["cfg"]["15m|X5_TRAIL2"]
    assert c["p"]["is"][:3] == [100, 40.0, -0.1] and c["p"]["is"][DS.COLS.index("own_final_x")] == pytest.approx(6e-18)
    assert c["p"]["pre"][0] == 0 and c["flags"] == ["stage1"] and c["max_lev"] == 31
    assert len(DS.expected()) == 342 and len(set(DS.expected())) == 342


def test_ds5y_committed_results_are_complete():
    if not os.path.exists(os.path.join(DS.OUT_DIR, "results.csv")):
        pytest.skip("research/deepseek200/out not in this checkout")
    v = DS.view(DS.OUT_DIR)
    assert v["state"] == "done" and v["done"] == 342 and len(v["defs"]) == 44
    assert v["summary"]["candidate"] == 0 and v["summary"]["configs"] == 342
    assert sum(len(e["cfg"]) for e in v["defs"]) == 342
    from paperbot.dash.analysis import MONEY_KEYS
    keys = set()

    def walk(x):
        if isinstance(x, dict):
            keys.update(x)
            for y in x.values():
                walk(y)
        elif isinstance(x, list):
            for y in x:
                walk(y)
    walk(v)
    assert not keys & MONEY_KEYS                      # research percentages only, never a live money amount


# ---------------------------------------------------------------- endpoints, read-only
def test_endpoints_shapes_and_nothing_written(tmp_path, monkeypatch):
    import fastapi
    from fastapi.testclient import TestClient
    db, dd = _hand_world(tmp_path, ROWS)
    before = {p: _sha(p) for p in (db, dd)}
    monkeypatch.setenv("PAPERBOT_DS5Y_OUT", str(tmp_path / "nothing-here"))
    assert "whatiflab" in MORE.MODULES and "ds5y" in MORE.MODULES
    app = fastapi.FastAPI()
    done = MORE.register_all(app, data=None, rooms=None, db=db, daily_db=dd, agents_db=None, checkpoint_db=None,
                             candles=None, frames=None)
    assert done["whatiflab"]["routes"] == ["/api/v4/whatif", "/api/v4/whatif/paper"] and done["ds5y"]["routes"] == ["/api/v4/ds5y"]
    c = TestClient(app)
    v = c.get("/api/v4/whatif").json()
    assert set(v) >= {"scope", "current", "controls", "settings", "five_year", "caveat_ko", "rule_ko", "strategies", "label"}
    assert len(v["strategies"]) == 36 and v["label"] == "설명용, 판정 아님" and "과최적화" in v["caveat_ko"]
    assert c.get(f"/api/v4/whatif?strategy={S1}&tf=15m").json()["scope"]["strategy"] == S1
    assert c.get("/api/v4/whatif?strategy=F1_RSI_DIV").status_code == 400
    assert c.get("/api/v4/whatif/paper?tf=5m").status_code == 400
    p = None
    for _ in range(30):                                              # a first answer may be 'pending'
        p = c.get(f"/api/v4/whatif/paper?strategy={S2}").json()
        if not p.get("pending"):
            break
    assert p["ready"] and p["base"]["trades"] == 1 and p["variants"]["tp2R"]["tp"] == 1 and "scopes" not in p
    assert c.get("/api/v4/ds5y").json()["state"] == "absent"
    assert {p: _sha(p) for p in (db, dd)} == before


def test_create_app_registers_the_routes(tmp_path):
    from paperbot.dash.app import create_app
    db = str(tmp_path / "paper3.db")
    blank(db, T0, [(f"{S1}@15m", "strategy")]).close()
    app = create_app(db, None, b"s" * 32)
    paths = {getattr(r, "path", "") for r in app.routes}
    assert {"/api/v4/whatif", "/api/v4/whatif/paper", "/api/v4/ds5y"} <= paths


# ---------------------------------------------------------------- the page wiring
def test_route_icon_links_and_safe_dom():
    routes = _read("core/routes.js")
    assert re.search(r'screens: \[[^\]]*"whatif"[^\]]*\]', routes) and 'whatif: {ko: "만약 실험실", group: "strat"' in routes
    assert re.search(r"^  whatif: \(\) => \[", routes, re.M)
    js, css = _read("screens/whatif.js"), _read("screens/whatif.css")
    assert re.search(r"^export async function mount\(el, ctx\)", js, re.M) and "export function unmount(" in js
    assert "`/api/v4/whatif${qs()}`" in js and "/api/v4/whatif/paper" in js and "이 조합은 시험한 적 없음" in js
    assert '@import url("analysis.css");' in css
    assert 'ctx.href("whatif")' in _read("screens/analysis.js")
    assert 'ctx.href("whatif", null, {strategy: name})' in _read("screens/strategies-shadows.js")
    assert 'href("whatif")' in _read("screens/analysis-rules.js")
    board, ds = _read("screens/board.js"), _read("screens/board-ds5y.js")
    assert 'import {ds5yCard} from "./board-ds5y.js";' in board and "ds5.update(b, gs, st.sel" in board
    assert 'const show = sel === "ds";' in ds and '"/api/v4/ds5y"' in ds
    assert '@import url("board-ds5y.css");' in _read("screens/board.css")
    for src in (js, ds):
        assert not re.search(r"innerHTML|insertAdjacentHTML|outerHTML|DOMParser|eval\(|toLocaleString|Intl\.", src)
        assert not re.search(r"#[0-9a-fA-F]{3,6}\b", src)
        assert not re.search(r"합격(?!·)|✓|✕", src)                    # descriptive words only
    inv = _read("INVENTORY.md")
    assert "만약 실험실" in inv and "딥시크 5년 결과" in inv and "/api/v4/ds5y" in inv


# ---------------------------------------------------------------- the cards rendered in node
def _node(script):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def _prelude():
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    return f"const D = await import('{dom}');\n"


def test_ds5y_aggregate_and_paper_by_hand():
    cfg = {"15m|X5": {"p": {"is": [100, 40, -0.1, -10, 0.02, 0.12, -50, 0.5], "cf": [50, 60, 0.2, 10, 0.3, 0.1, -20, 1.5],
                            "pre": [0, None, None, 0, None, None, None, None]}, "flags": ["stage1"]},
           "1h|X5": {"p": {"is": [100, 50, 0.1, 10, 0.2, 0.1, -60, 2], "cf": [0, None, None, 0, None, None, None, None],
                           "pre": [0, None, None, 0, None, None, None, None]}, "flags": []},
           "15m|X2": {"p": {"is": [999, 99, 9, 9, 9, 9, -99, 9]}, "flags": ["candidate"]}}
    board = {"accounts": [{"kind": "ds200", "strategy": "F1", "timeframe": "15m", "trades": 4, "wins": 1, "wallet": 5500},
                          {"kind": "ds200", "strategy": "F1", "timeframe": "1h", "trades": 6, "wins": 3, "wallet": 4500, "bust": True},
                          {"kind": "ds200", "strategy": "F1", "timeframe": "4h", "trades": 0, "wins": 0, "wallet": None},
                          {"kind": "random", "strategy": "RANDOM_1", "timeframe": "15m", "trades": 2, "wins": 2, "wallet": 5100}]}
    out = _node(_prelude() + f"const M = await import('file://{SCREENS}/board-ds5y.js');\n"
                f"const def = {{id: 'F1', cfg: {json.dumps(cfg)}}}; const b = {json.dumps(board)};\n"
                "const a = M.aggregate(def, 'X5', ''); const a15 = M.aggregate(def, 'X5', '15m');\n"
                "const p = M.paperOf(b, (x) => x.kind === 'ds200' && x.strategy === 'F1', 5000);\n"
                "console.log(JSON.stringify({a: {...a, flags: [...a.flags]}, a15: {n: a15.n, cfgs: a15.cfgs}, p}));")
    a = out["a"]
    assert a["n"] == 250 and a["cfgs"] == 2 and a["mean"] == pytest.approx(0.04) and a["win"] == pytest.approx(48)
    assert a["sum"] == pytest.approx(10) and a["mdd"] == -60 and a["gross"] == pytest.approx((2 + 15 + 20) / 250)
    assert a["per"]["is"]["mean"] == pytest.approx(0) and a["per"]["cf"]["mean"] == pytest.approx(0.2) and a["per"]["pre"]["n"] == 0
    assert (a["pos"], a["seen"], a["ownUp"], a["ownN"]) == (1, 2, 2, 3) and a["flags"] == ["stage1"]
    assert out["a15"] == {"n": 150, "cfgs": 1}
    p = out["p"]
    assert (p["accounts"], p["trades"], p["wins"], p["bust"]) == (3, 10, 4, 1) and p["rate"] == pytest.approx(0.4)
    assert p["medRet"] == pytest.approx(0.0)                       # +10%, −10%, 0 (no trade yet: the start)


def test_ds5y_card_shows_only_on_the_deepseek_group_and_says_absent(tmp_path):
    absent = DS.view(str(tmp_path))
    full = DS.view(DS.OUT_DIR) if os.path.exists(os.path.join(DS.OUT_DIR, "results.csv")) else None
    board = {"accounts": [{"kind": "ds200", "strategy": "F1_RSI_DIV", "timeframe": "15m", "trades": 3, "wins": 2, "wallet": 5100}]}

    def render(view, sel):
        vf = tmp_path / f"view-{sel}-{view['state']}.json"
        vf.write_text(json.dumps(view), encoding="utf-8")
        return _node(_prelude() + f"const M = await import('file://{SCREENS}/board-ds5y.js');\n"
                     f"const fs = await import('fs'); const V = JSON.parse(fs.readFileSync('{vf}', 'utf8'));\n"
                     "localStorage.setItem('pb4-ds5-sort', JSON.stringify('paper'));\n"      # the paper account first
                     "const ctx = {api: async () => V, alive: () => true, href: () => '#'};\n"
                     f"const c = M.ds5yCard(ctx); c.update({json.dumps(board)}, {{initial: 5000}}, '{sel}', null);\n"
                     "await new Promise((r) => setTimeout(r, 30));\n"
                     "console.log(JSON.stringify({hidden: !!c.el.hidden, ...D.walk(c.el)}));")
    core = render(absent, "core")
    assert core["hidden"] is True
    a = render(absent, "ds")
    assert a["hidden"] is False and "아직 시작 안 함 / 서버에서 계산 중" in a["text"] and "0 / 342" in a["text"]
    assert "비용 전 손익" in a["text"] and "모의" in a["text"]
    if full:
        t = render(full, "ds")["text"]
        assert "5년 계산 끝" in t and "342 / 342" in t and "후보 0개" in t and t.count("기간·봉별 보기") == 10   # one page
        assert "계좌 1" in t and "거래 3건" in t and "표본 적음" in t and "참고" in t and "모의 · 실제 시세" in t
        assert "USDT" not in t


def test_whatif_map_sentence_follows_the_data(tmp_path):
    """One strategy on one timeframe can have plus cells: the 5-year map never says 'no plus cell' then."""
    if not os.path.exists(W.LEVSTOP_JSON):
        pytest.skip("research outputs not in this checkout")
    view = W.view("N03_ADX_GC", "4h")
    arms = list(view["five_year"]["levstop"]["arms"].values()) + list(view["five_year"]["exitstyle"]["arms"].values())
    vals = [a["mean_eq"] for a in arms if a["mean_eq"] is not None]
    pos = sum(1 for x in vals if x > 0)
    assert pos > 0
    f = tmp_path / "v.json"
    f.write_text(json.dumps(view), encoding="utf-8")
    out = _node(_prelude() + f"const M = await import('file://{SCREENS}/whatif.js');\n"
                f"const fs = await import('fs'); const V = JSON.parse(fs.readFileSync('{f}', 'utf8'));\n"
                "const el = document.createElement('div');\n"
                "const ctx = {params: {query: {strategy: 'N03_ADX_GC', tf: '4h'}}, setTitle() {}, api: async (p) => (p.startsWith('/api/v4/whatif/paper') ? {ready: false, why: 'x'} : V),\n"
                "  store: {need: async () => null}, every() {}, timeout() {}, track() {}, alive: () => true, href: () => '#'};\n"
                "await M.mount(el, ctx); await new Promise((r) => setTimeout(r, 30));\n"
                "const t = D.walk(el).text; M.unmount(); console.log(JSON.stringify({t}));")
    assert f"{len(vals)}칸 중 {pos}칸이 플러스입니다" in out["t"] and "하나도 없다" not in out["t"]


def test_ds5y_card_follows_a_running_job(tmp_path):
    """While the server job runs, the shown card asks again (every 2 minutes) and N / 342 moves on; once done it stops."""
    run = tmp_path / "run"
    run.mkdir()
    (run / "run.log").write_text("15m: 2321522 trades, 88 configs so far, 94s\n")
    v1 = DS.view(str(run))
    (run / "run.log").write_text("15m: 2321522 trades, 88 configs so far, 94s\n30m: 1272618 trades, 176 configs so far, 142s\n")
    v2 = DS.view(str(run))
    assert (v1["state"], v1["done"], v2["done"]) == ("running", 88, 176)
    f = tmp_path / "views.json"
    f.write_text(json.dumps([v1, v2]), encoding="utf-8")
    out = _node(_prelude() + f"const M = await import('file://{SCREENS}/board-ds5y.js');\n"
                f"const fs = await import('fs'); const V = JSON.parse(fs.readFileSync('{f}', 'utf8'));\n"
                "let k = 0, tick = null, every = 0;\n"
                "const ctx = {api: async () => V[Math.min(k++, 1)], alive: () => true, href: () => '#',\n"
                "  every: (ms, fn) => { every = ms; tick = fn; }};\n"
                "const c = M.ds5yCard(ctx); c.update({accounts: []}, {initial: 5000}, 'ds', null);\n"
                "await new Promise((r) => setTimeout(r, 30)); const t1 = D.walk(c.el).text;\n"
                "await tick(); await new Promise((r) => setTimeout(r, 30)); const t2 = D.walk(c.el).text;\n"
                "console.log(JSON.stringify({t1, t2, every, calls: k}));")
    assert out["every"] == 120000 and out["calls"] == 2
    assert "서버에서 계산 중" in out["t1"] and "88 / 342" in out["t1"]
    assert "176 / 342" in out["t2"] and "88 / 342" not in out["t2"]


def test_whatif_screen_renders_the_reference_and_a_changed_setting(tmp_path):
    if not os.path.exists(W.LEVSTOP_JSON):
        pytest.skip("research outputs not in this checkout")
    db, dd = _hand_world(tmp_path, ROWS)
    view = W.view(None, None)
    paper = W.paper_scope(W.paper_all(db, dd, T0 + 3 * DAY), W.scope(None, None))
    lev = next(s["id"] for s in view["settings"] if s["stop"] == 1.5 and s["lev"] == "30")
    lock = next(s["id"] for s in view["settings"] if s["paper"] == "lock15")
    m50 = next(s["id"] for s in view["settings"] if s["lev"] == "50m50")
    out = _node(_prelude() + f"const M = await import('file://{SCREENS}/whatif.js');\n"
                f"const V = {json.dumps(view)}; const P = {json.dumps(paper)};\n"
                "const el = document.createElement('div');\n"
                "const ctx = {params: {query: {}}, setTitle() {}, api: async (p) => (p.startsWith('/api/v4/whatif/paper') ? P : V),\n"
                "  store: {need: async () => null}, every() {}, timeout() {}, track() {}, alive: () => true, href: () => '#'};\n"
                "await M.mount(el, ctx); await new Promise((r) => setTimeout(r, 30));\n"
                "const t0 = D.walk(el).text;\n"
                f"M.update({{query: {{set: '{lev}'}}}}); const t1 = D.walk(el).text;\n"
                f"M.update({{query: {{set: '{lock}'}}}}); const t2 = D.walk(el).text;\n"
                f"M.update({{query: {{set: '{m50}'}}}}); const t3 = D.walk(el).text;\n"
                "M.unmount();\n"
                "console.log(JSON.stringify({t0, t1, t2, t3}));")
    t0, t1, t2, t3 = out["t0"], out["t1"], out["t2"], out["t3"]
    assert "먼저 읽어 주세요" in t0 and "30일 규칙은 바뀌지 않습니다" in t0 and "과최적화" in t0
    assert "지금 규칙(30일 동안 고정)" in t0 and "−1.41%" in t0 and "170/276" in t0 and "참고" in t0
    assert "지금 규칙 그대로 다시 돌린 거래" in t0 and "매매법 (지금 규칙)" in t0 and "동전 봇 (지금 규칙)" in t0   # coin flips next to it
    assert "손절 폭 1.5 ATR" in t1 and "레버리지·비중 30배·30%" in t1 and "밤 그림자 없음" in t1 and "이 설정" in t1
    assert "첫 잠금 +15%" in t2 and "5년에 시험한 적 없음" in t2 and "5년 실험실 관문" in t2 and "lock_start" not in t2
    assert "표본 적음" in t2 and "같은 거래 10건 필요" in t2                           # 3 paired trades: a filling bar
    assert "30칸 모두 마이너스" in t0 and "하나도 없다" in t0                         # the whole 36: every 5-year cell loses
    # 50배·50% was never run for five years: the nearest tested arm (50배·40%, same stop) is shown and named as such
    assert "5년에 시험한 적 없음" in t3 and "가장 가까운 5년 시험: 50배·40%" in t3
    v50 = view["five_year"]["levstop"]["arms"]["50|2.0"]["mean_eq"]
    assert f"{abs(v50) * 100:.2f}%" in t3
    for t in (t0, t1, t2):
        assert "USDT" not in t and "딥시크" in t0
