"""combo-5y on the dashboard: GET /api/v4/combo5y and /api/v4/combo5y/monthly (paperbot/dash/more/combo5y.py) on a tiny
synthetic result file and a synthetic paper3.db: the missing-file answer, the login, the trimmed combination answer, the
monthly answer with the paper run so far ranked among the 5-year months cut at the same day (hand-computed), the waiting
state (no trades yet), the cache and the file-change reload; DeepSeek never in either answer. Then the committed result
file itself (shape, size, honesty words, no DeepSeek, consistent counts) and the page pieces (route, tab, exports)."""
from __future__ import annotations

import json
import math
import os
import time

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.dash.app import create_app, hash_password  # noqa: E402
from paperbot.dash.more import combo5y as M  # noqa: E402
from paperbot.models import TradeRecord  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
COMMITTED = os.path.join(ROOT, "paperbot", "dash", "data", "combo5y.json")
HOUR, DAY = 3_600_000, 86_400_000
PW = "combo five years ok"
SECRET = b"k" * 32


def _doc(strategies=("S_A", "S_B", "S_C")):
    per = {}
    for i, s in enumerate(strategies):
        # 3 months; day-2 values (bp): S_A 100 / -200 / 300
        el = [[(j + 1) * 10 * (1 + i)] * 31 for j in range(3)]
        if s == "S_A":
            el = [[50, 100] + [100] * 29, [-100, -200] + [-200] * 29, [100, 300] + [300] * 29]
        m = [0.01 * (i + 1), -0.02, 0.03]
        per[s] = {"m": m, "n": 3, "best": max(m), "worst": min(m), "median": sorted(m)[1], "mean": sum(m) / 3,
                  "pos_share": 2 / 3, "p10": -0.02, "p25": -0.01, "p75": 0.02, "p90": 0.03, "trades": 30,
                  "win_rate": 0.5, "liq": 1, "bust_months": 0, "elapsed_bp": el, "one": {"multiple": 0.5, "mdd": 0.6},
                  "tfs": {tf: {"m": m, "n": 3, "median": m[1], "pos_share": 2 / 3, "best": max(m), "worst": min(m),
                               "bust_months": 0, "trades": 5, "win_rate": 0.4, "liq": 0,
                               "one": {"multiple": 0.2, "mdd": 0.9, "bust": True, "bust_ms": 1, "trades": 9, "win_rate": 0.3}}
                          for tf in ("15m", "30m", "1h", "4h")}}
    return {"version": 1, "generated": "2026-10-06T00:00:00+00:00", "label": "설명용, 판정 아님",
            "months": ["2021-08", "2021-09", "2021-10"], "month_start_ms": [0, 1, 2], "strategies": list(strategies),
            "names": {s: f"이름{s}" for s in strategies}, "tfs": ["15m", "30m", "1h", "4h"], "initial": 5000.0,
            "per": per, "flips": {"units": 4, "unit_months": {"n": 12, "median": -0.1, "pos_share": 0.2},
                                  "tfs": {"15m": {"n": 3}}, "median_month": [-0.1, -0.1, -0.1]},
            "parity": {"cells": 2, "same_final": 2, "same_trades": 2, "agree": True},
            "portfolio": {"all": {"top": [{"units": ["S_A", "S_B"], "k": 2, "score": 1.0, "curve": [0.0, 0.01, 0.02]}]}},
            "merged": {"trials": 10, "tested": 5, "bh_pass": 0, "both_pass": 0, "top": []},
            "shared": {"all": [], "active": []}, "methods": {"caveat": "선택 편향", "accounts": "매달", "sizing": "v4", "costs": {}, "period": {}}}


def _write(path, doc):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)


def _trade(st, aid, t, pnl):
    strat, tf = aid.split("@")
    st.trade(aid, TradeRecord(
        strategy_id=strat, symbol="BTCUSDT", timeframe=tf, side=1, signal_ts=t - HOUR, entry_time=t - 30 * 60_000,
        entry_price=100.0, exit_time=t, exit_price=101.0, exit_reason="SL", qty=1.0, leverage=30, tier="normal",
        margin=100.0, stop_price=99.0, tp_price=0.0, liq_price=95.0, fees=1.0, funding=0.0, pnl=pnl,
        roe=pnl / 100.0, price_move=0.01, mae_price=99.5, mfe_price=101.5, equity_after=5000.0 + pnl, score=0.0,
        context={}))


def _paper(tmp_path, start, trades=True):
    db = str(tmp_path / "paper3.db")
    st = Store3(db)
    for aid, kind in (("S_A@15m", "strategy"), ("S_A@1h", "strategy"), ("S_B@15m", "strategy"),
                      ("F3_BOS@15m", "ds200"), ("RANDOM_1@15m", "random")):
        s, tf = aid.split("@")
        st.add_account(aid, s, tf, kind, start, "paper-v4", None, {})
    st.put_state("run", start, {"initial_equity": 5000.0})
    if trades:
        _trade(st, "S_A@15m", start + 2 * HOUR, 200.0)
        _trade(st, "S_A@1h", start + 5 * HOUR, -50.0)
        _trade(st, "F3_BOS@15m", start + 3 * HOUR, 999.0)
        _trade(st, "S_A@15m", start - 2 * HOUR, 7777.0)          # before the run start: not counted
    st.commit()
    st.conn.close()
    return db


# ---------------------------------------------------------------- pure views
def test_rank_among_hand_case():
    assert M.rank_among(0.015, [0.01, -0.02, 0.03]) == {"rank": 2, "of": 4, "below": 2, "ties": 0, "n": 3,
                                                       "share_below": 0.6667}
    assert M.rank_among(0.5, [0.01])["rank"] == 1 and M.rank_among(-1, [0.01])["rank"] == 2


def test_rank_among_puts_a_tie_in_the_middle():
    # level with 4 of 5 months (a strategy that hardly trades): not "2nd of 6", the middle of its equals
    r = M.rank_among(0.0, [0.0, 0.0, 0.0, 0.0, -0.1])
    assert (r["rank"], r["below"], r["ties"], r["of"]) == (3, 1, 4, 6)
    assert r["share_below"] == pytest.approx((1 + 4 / 2) / 5)


def test_median_and_same_time_hand_cases():
    assert M.median([3.0, 1.0, 2.0]) == 2.0 and M.median([4.0, 1.0, 3.0, 2.0]) == 2.5 and M.median([]) is None
    row = [100, 300] + [300] * 29                                   # bp by the end of day 1, 2, ...
    assert M.same_time(row, 0.0) == 0.0                             # the month's start: nothing yet
    assert M.same_time(row, 0.4) == pytest.approx(0.004)            # 0.4 of day 1 (not the whole day 1)
    assert M.same_time(row, 1.0) == pytest.approx(0.01)
    assert M.same_time(row, 1.5) == pytest.approx(0.02)             # half way from day 1 (100) to day 2 (300)
    assert M.same_time(row, 40.0) == pytest.approx(0.03)            # past the month: its total
    assert M.same_time([], 1.0) is None


def test_monthly_view_ranks_the_paper_run_at_the_same_day(tmp_path):
    import sqlite3
    start = 1_790_000_000_000
    db = _paper(tmp_path, start)
    now = start + int(1.5 * DAY)
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    paper = M.paper_so_far(c, now)
    c.close()
    assert paper["start"] == start
    sa = paper["strategies"]["S_A"]
    assert (sa["trades"], sa["pnl"], sa["wins"], sa["accounts"], sa["initial"]) == (2, 150.0, 1, 2, 10_000.0)
    assert "F3_BOS" not in paper["strategies"] and "RANDOM_1" not in paper["strategies"]   # the 36 only
    v = M.monthly_view(_doc(), paper, now)
    assert v["ready"] and v["day"] == 2 and v["elapsed_days"] == 1.5
    row = next(r for r in v["rows"] if r["strategy"] == "S_A")
    p = row["paper"]
    # 1.5 days: each 5-year month half way between its day-1 and day-2 ends (bp 50/100, -100/-200, 100/300)
    assert p["ret"] == pytest.approx(0.015) and p["same_day"] == [0.0075, -0.015, 0.02]
    assert p["rank"] == {"rank": 2, "of": 4, "below": 2, "ties": 0, "n": 3, "share_below": 0.6667}
    assert p["same_day_median"] == 0.0075 and p["small"] is True and p["trades"] == 2 and p["waiting"] is False
    assert "elapsed_bp" not in row and row["tfs"]["15m"]["median"] == -0.02
    sc = next(r for r in v["rows"] if r["strategy"] == "S_C")
    assert "paper" not in sc                                    # no account of S_C in this run
    assert "DeepSeek" not in json.dumps(v, ensure_ascii=False) and "F3_BOS" not in json.dumps(v)


def test_monthly_view_waiting_and_without_paper(tmp_path):
    import sqlite3
    start = 1_790_000_000_000
    db = _paper(tmp_path, start, trades=False)
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    paper = M.paper_so_far(c, start + HOUR)
    c.close()
    v = M.monthly_view(_doc(), paper, start + HOUR)
    p = next(r for r in v["rows"] if r["strategy"] == "S_A")["paper"]
    assert v["day"] == 1 and p["trades"] == 0 and p["ret"] == 0.0 and p["small"] is True
    # one hour in: 1/24 of each 5-year month's day 1 (50, -100, 100 bp), never the whole day
    assert p["same_day"] == [round(0.005 / 24, 4), round(-0.01 / 24, 4), round(0.01 / 24, 4)]
    assert p["waiting"] is True and p["rank"] is None            # nothing closed yet: no place among the months
    v2 = M.monthly_view(_doc(), None, start)
    assert v2["day"] is None and all("paper" not in r for r in v2["rows"])
    assert M.monthly_view(None, None, start)["unavailable"] is True


def test_monthly_view_without_a_readable_paper_db():
    v = M.monthly_view(_doc(), {"start": None, "strategies": {}, "error": "paper3.db를 읽지 못함 (OperationalError)"},
                       int(time.time() * 1000))
    assert v["ready"] and v["paper_error"] and v["day"] is None and all("paper" not in r for r in v["rows"])


def test_monthly_route_empty_database_answers_the_5_years(tmp_path, monkeypatch):
    """A paper3.db without tables (a fresh install): the 5-year side, no paper side, no error page."""
    path = str(tmp_path / "combo5y.json")
    _write(path, _doc())
    monkeypatch.setattr(M, "DATA_JSON", path)
    db = str(tmp_path / "empty.db")
    import sqlite3
    sqlite3.connect(db).close()
    app = create_app(db, hash_password(PW), SECRET, candles=lambda s, i, n: [], inbox_db=str(tmp_path / "inbox.db"))
    c = TestClient(app)
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    r = c.get("/api/v4/combo5y/monthly")
    assert r.status_code == 200
    v = r.json()
    assert v["ready"] and len(v["rows"]) == 3 and all("paper" not in x for x in v["rows"])
    assert v["paper_error"] and "paper3.db" in v["paper_error"]


def test_combo_view_is_trimmed():
    v = M.combo_view(_doc())
    assert set(v["per"]["S_A"]) <= {"n", "best", "worst", "median", "mean", "pos_share", "trades", "win_rate", "one"}
    assert "tfs" not in v["flips"] and v["portfolio"]["all"]["top"][0]["units"] == ["S_A", "S_B"]
    assert M.combo_view(None)["unavailable"] is True
    assert M.load("/nonexistent/x.json") is None


# ---------------------------------------------------------------- the routes
@pytest.fixture
def app_with(tmp_path, monkeypatch):
    def make(doc=True, trades=True):
        path = str(tmp_path / "combo5y.json")
        if doc:
            _write(path, _doc())
        monkeypatch.setattr(M, "DATA_JSON", path)
        db = _paper(tmp_path, int(time.time() * 1000) - int(1.5 * DAY), trades=trades)
        app = create_app(db, hash_password(PW), SECRET, candles=lambda s, i, n: [], inbox_db=str(tmp_path / "inbox.db"))
        c = TestClient(app)
        return c, app, path
    return make


def test_routes_missing_file_and_login(app_with):
    c, app, _ = app_with(doc=False)
    assert c.get("/api/v4/combo5y").status_code == 401 and c.get("/api/v4/combo5y/monthly").status_code == 401
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    a = c.get("/api/v4/combo5y").json()
    assert a["unavailable"] is True and "combo5y" in a["note"]
    assert c.get("/api/v4/combo5y/monthly").json()["unavailable"] is True
    assert "combo5y" in app.state.more


def test_routes_answer_cached_and_reload_on_change(app_with):
    c, app, path = app_with()
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    t = time.perf_counter()
    a = c.get("/api/v4/combo5y")
    assert a.status_code == 200 and time.perf_counter() - t < 2
    d = a.json()
    assert d["strategies"] == ["S_A", "S_B", "S_C"] and "elapsed_bp" not in json.dumps(d)
    m = c.get("/api/v4/combo5y/monthly").json()
    assert m["ready"] and m["day"] == 2
    p = next(r for r in m["rows"] if r["strategy"] == "S_A")["paper"]
    assert p["trades"] == 2 and p["ret"] == pytest.approx(0.015) and p["rank"]["rank"] == 2 and not p["waiting"]
    assert c.get("/api/v4/combo5y/monthly").json() == m                       # cached
    doc = _doc(("S_A", "S_B"))
    _write(path, doc)
    os.utime(path, (time.time() + 5, time.time() + 5))
    assert c.get("/api/v4/combo5y").json()["strategies"] == ["S_A", "S_B"]    # file changed: read again


# ---------------------------------------------------------------- the committed result file
@pytest.fixture(scope="module")
def committed():
    if not os.path.exists(COMMITTED):
        pytest.skip("paperbot/dash/data/combo5y.json not generated")
    with open(COMMITTED, encoding="utf-8") as fh:
        raw = fh.read()
    return raw, json.loads(raw)


def test_committed_file_shape_and_honesty(committed):
    raw, d = committed
    assert len(raw.encode()) < 2_000_000
    assert "NaN" not in raw and "Infinity" not in raw
    assert d["version"] == 1 and d["label"] == "설명용, 판정 아님"
    n = len(d["months"])
    assert d["months"][0] == "2021-08" and d["months"][-1] == "2026-09" and n == 62
    from paperbot import sweepsig
    from paperbot.sigservice import strategy_names
    assert d["strategies"] == strategy_names(sweepsig.lib()) and len(d["strategies"]) == 36
    for s in d["strategies"]:
        p = d["per"][s]
        assert len(p["m"]) == n and len(p["elapsed_bp"]) == n and all(len(r) == 31 for r in p["elapsed_bp"])
        assert set(p["tfs"]) == {"15m", "30m", "1h", "4h"} and all(len(t["m"]) == n for t in p["tfs"].values())
        assert p["worst"] <= p["median"] <= p["best"] and 0 <= p["pos_share"] <= 1
    mt = d["methods"]
    assert "선택 편향" in mt["caveat"] and "판정이 아니" in mt["caveat"] and "미리 등록한 연구도 아닙니다" in mt["caveat"]
    assert mt["data"]["group_lookup"]["missed"] == 0
    # parity with the research's own per-strategy accounts
    pr = d["parity"]
    assert pr["agree"] is True and pr["cells"] == pr["same_final"] == pr["same_trades"] and pr["cells"] >= 288
    assert pr["cards_same"] == pr["cards_cells"] and pr["cards_cells"] + pr["cards_blank"] == 288
    # merged-rule counts are consistent and every trial is counted
    m = d["merged"]
    assert m["both_pass"] <= m["bh_pass"] <= m["tested"] <= m["trials"]
    assert sum(f["trials"] for f in m["families"].values()) == m["trials"]
    assert len(m["top"]) <= 15 and all(len(r["w"]) == 3 for r in m["top"])
    # portfolios (both searches): top 10 with monthly curves, the guards, walk-forward; one correlation map
    pf = d["portfolio"]
    rule = pf["active_rule"]
    assert set(pf["all"]["units"]) == set(d["strategies"])
    assert set(pf["active"]["units"]) == {s for s in d["strategies"] if pf["trades"][s] >= rule["min_trades"]}
    assert [x["strategy"] for x in rule["left_out"]] == sorted(set(d["strategies"]) - set(pf["active"]["units"]),
                                                               key=lambda s: pf["trades"][s])
    for v in ("all", "active"):
        V = pf[v]
        assert 1 <= len(V["top"]) <= 10 and all(len(t["curve"]) == n and 2 <= t["k"] <= 5 for t in V["top"])
        assert all(set(t["units"]) <= set(V["units"]) for t in V["top"])
        assert [t["score"] for t in V["top"]] == sorted((t["score"] for t in V["top"]), reverse=True)
        assert V["shuffled_days"]["runs"] == 100 and len(V["coin_flips"]["groups"]) == 4
        assert V["coin_flips"]["units_per_group"] == len(V["units"])
        assert [w["test_year"] - w["pick_year"] for w in V["walk_forward"]] == [1] * len(V["walk_forward"])
        assert all(set(w["units"]) <= set(V["units"]) and 0 <= w["beat_share"] <= 1 for w in V["walk_forward"])
        assert len(d["shared"][v]) == min(5, len(V["top"]))
        for sh, t in zip(d["shared"][v], V["top"]):
            assert sh["units"] == t["units"] and sh["capital"] == t["capital"]
            assert sh["shared"]["conflicts"] >= 0 and len(sh["shared"]["curve"]) == n == len(sh["separate"]["curve"])
            assert sh["shared"]["signals"] == (sh["shared"]["trades"] + sh["shared"]["same_side_skipped"]
                                               + sh["shared"]["conflicts"] + sh["shared"]["refused"])
    tri = 36 * 35 // 2
    assert len(pf["corr"]["r"]) == len(pf["corr"]["tail"]) == len(pf["corr"]["coloss"]) == tri
    assert all(-1.0001 <= x <= 1.0001 for x in pf["corr"]["r"] if x is not None)
    assert all(0 <= x <= 1 for x in pf["corr"]["coloss"] if x is not None)
    assert set(pf["flip_band"]) == {"2", "3", "4", "5"}


def test_committed_file_has_no_deepseek(committed):
    raw, _d = committed
    from paperbot.config import DS200_IDS
    assert not any(f'"{x}"' in raw for x in DS200_IDS)
    assert "ds200" not in raw and "딥시크" not in raw


# ---------------------------------------------------------------- the page pieces
def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as fh:
        return fh.read()


def test_route_tab_and_exports():
    routes = _read("core", "routes.js")
    assert 'combo5y: {ko: "5년 조합", group: "strat"' in routes and '"analysis", "combo5y"]' in routes
    assert "combo5y: () =>" in routes                                 # its own rail icon
    js = _read("screens", "combo-5y.js")
    assert "export async function render5y(ctx, el)" in js and "/api/v4/combo5y" in js
    page = _read("screens", "combo5y.js")
    assert 'import {render5y} from "./combo-5y.js"' in page and "export async function mount" in page
    an = _read("screens", "analysis.js")
    assert '{id: "monthly5y", label: "5년 월별", path: "/api/v4/combo5y/monthly", render: M.monthly5y, groups: "core"' in an
    mo = _read("screens", "analysis-monthly.js")
    assert "export function monthly5y" in mo and "표본 적음" in mo and "refNote" in mo
    for src in (js, page, mo):
        for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "toLocaleString", "Intl.NumberFormat", "eval("):
            assert bad not in src
    for css in ("combo-5y.css", "combo5y.css", "analysis-monthly.css"):
        c = _read("screens", css)
        import re
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", c) and "rgb(" not in c   # tokens only, no colour literals
        for line in c.splitlines():
            if "font-size" in line:
                assert "var(--t-" in line, line


def test_more_module_registered():
    from paperbot.dash.more import MODULES
    assert "combo5y" in MODULES
