"""커스텀값 실시간 비교 (dash/more/paramlive.py, screens/strategies-paramlive.js, screens/analysis-paramlive.js): the
dashboard's read-only view of the nightly custom-value shadow (paperbot/paramshadow.py) summary.

Checks: GET /api/v4/paramlive sits behind the login; without a summary it is {available: false, none_ko: '아직 첫 계산
전 ...'} (the strategy route too, never a 404 then); with one it carries status, line_ko, the totals, the texts, the
settings and ONE COMPACT cell per strategy x timeframe (no variant rows, no parameter list); GET
/api/v4/paramlive/<strategy> gives that strategy's four cells in timeframe order with every variant row and the
parameters' Korean names (params.PARAM_KO); an unknown name is a 404 once a summary exists; an error.json newer than the
summary adds error_ko / error_at next to the last good data (an older one is ignored); a damaged, non-object or no_run
file and NaN numbers never give a 500; the file is parsed once per mtime and nothing is written; the 분석 view is
registered (기존 36 only), the 매매법 상세 card is added for the 36 only, right after the parameter card; the
paperbot-paramshadow timer is in the 예약 작업 list with its Korean name and its 10:00 KST calendar."""

import json
import os
import re
import shutil
import subprocess
import time
from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.dash.app import create_app, hash_password  # noqa: E402
from paperbot.dash.more import jobs as J  # noqa: E402
from paperbot.dash.more import paramlive as P  # noqa: E402
from paperbot.dash.more.params import PARAM_KO  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
PW = "paramlive horse battery"
SECRET = b"q" * 32
TFS = ("15m", "30m", "1h", "4h")
GEN = 1_791_511_200_000                       # 2026-10-09 02:00 UTC
TEXTS = {"what": "기존 36개 매매법을 숫자 하나만 바꿔 ...", "base": "기본값(재계산) = ...", "parity": "재계산 일치 = ...",
         "luck": "★는 거래 20건 이상이고 ... 우연으로도 최대 약 0.4칸에 ★가 붙을 수 있습니다.", "caution": "참고용입니다. ..."}


def _read(*p):
    with open(os.path.join(*p), encoding="utf-8") as fh:
        return fh.read()


def _stats(trades, pnl, h1=None):
    return {"trades": trades, "wins": trades // 2, "win_rate": (trades // 2) / trades if trades else None, "pnl": pnl,
            "equity": 5000 + pnl, "max_dd": 0.1, "pnl_h1": pnl / 2 if h1 is None else h1, "pnl_h2": pnl / 2,
            "mean_ret": 0.001 if trades else None, "sd_ret": 0.02 if trades > 1 else None}


def _cell(strategy, tf, params, star_key=None, same_keys=(), small=False):
    base = {**_stats(30, -100.0), "open": tf == "15m", "bust": False}
    variants = []
    for p in params:
        for m in (0.5, 0.75, 1.25, 1.5):
            key = f"{p['name']}x{m:g}"
            same = key in same_keys
            diff = 0.0 if same else round(40.0 * (m - 1) * (1 if p["name"].endswith("len") else -1), 2)
            value = [int(x * m) for x in p["default"]] if isinstance(p["default"], list) else round(p["default"] * m, 3)
            v = {"key": key, "param": p["name"], "mult": m, "value": value, "default": p["default"],
                 "same_as_base": same, "signals": 50, "signals_diff": 0 if same else 7,
                 **{k: x for k, x in _stats(30, -100.0 + diff).items() if k in ("trades", "wins", "win_rate", "pnl", "equity", "max_dd")},
                 "open": False, "bust": False, "diff_pnl": diff}
            if same:
                v.update(luck=None, both_halves=None, star=False)
            else:
                v.update(luck={"small": small, "z": None if small else 0.5, "z_need": 2.7, "luck_pp": None if small else 1.0,
                               "diff_pp": None if small else 0.2, "ratio": None if small else 0.19, "beyond": key == star_key},
                         both_halves=key == star_key, star=key == star_key)
            variants.append(v)
    diffs = [v for v in variants if not v["same_as_base"]]
    best = max(diffs, key=lambda v: v["diff_pnl"]) if diffs else None
    return {"strategy": strategy, "tf": tf, "params": params, "base": base,
            "real": {**_stats(28, -90.0), "open": False}, "parity": {"base_trades": 30, "real_trades": 28, "same": 24, "share": 0.8},
            "k": len(diffs), "variants": variants, "better": sum(1 for v in diffs if v["diff_pnl"] > 0),
            "stars": sum(1 for v in variants if v["star"]),
            "best": {"key": best["key"], "diff_pnl": best["diff_pnl"], "star": best["star"]} if best else None}


def summary(status="ok", nan=False):
    """A small last.json of paramshadow's shape: two of the 36 x the four timeframes."""
    s2 = [{"name": "st_atr_len", "default": 10, "kind": "length"}, {"name": "st_mult", "default": 6.0, "kind": "mult"}]
    n03 = [{"name": "adx_len", "default": 14, "kind": "length"}, {"name": "kst_roc_lens", "default": [10, 15, 20, 30], "kind": "length"}]
    cells = [_cell("S2_ST_ROC", tf, s2, star_key="st_atr_lenx1.5" if tf == "1h" else None,
                   same_keys=("st_multx0.75",) if tf == "4h" else ()) for tf in TFS]
    cells += [_cell("N03_ADX_GC", tf, n03, small=True) for tf in TFS]
    if nan:
        cells[0]["base"]["mean_ret"] = float("nan")
        cells[0]["variants"][0]["luck"]["z"] = float("inf")
    variants = sum(c["k"] for c in cells)
    better = sum(c["better"] for c in cells)
    d = {"version": 1, "status": status, "generated_ms": GEN, "run_start_ms": GEN - 5 * 86_400_000, "through_day": "2026-10-08",
         "days": 4, "days_remaining": 3 if status == "filling" else 0,
         "settings": {"version": "paper-v4", "initial_equity": 5000.0, "taker_fee": 0.0005, "slippage": 0.0002,
                      "leverage_rule": "quality_v1", "stop_atr": 2.0},
         "brackets_src": "test", "multipliers": [0.5, 0.75, 1.25, 1.5], "min_trades": 20, "alpha": 0.05, "tfs": list(TFS),
         "overview": {"cells": len(cells), "variants": variants, "better": better, "stars": 1, "cells_tested": 8,
                      "stars_by_luck": 0.4, "parity": 0.8},
         "cells": cells, "notes": ["BTCUSDT 4h: 차트 봉 40개(필요 61개 이상), 이 구간 신호 없음"], "texts_ko": TEXTS,
         "line_ko": f"커스텀값 그림자 10/8까지 4일: 변형 {variants}개 중 기본값보다 번 것 {better} · ★ 1(우연으로도 최대 0.4) · 기본값 재계산 일치 80%"}
    return d


def _write(folder, name, obj, mtime=None):
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False))
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def psdir(tmp_path, monkeypatch):
    d = tmp_path / "paramshadow"
    d.mkdir()
    monkeypatch.setenv("PAPERBOT_PARAMSHADOW_DIR", str(d))
    P._CACHE.clear()
    yield str(d)
    P._CACHE.clear()


@pytest.fixture
def client(tmp_path, psdir):
    db = str(tmp_path / "paper3.db")
    Store3(db).close()
    app = create_app(db, hash_password(PW), SECRET, candles=lambda s, i, n: [], inbox_db=str(tmp_path / "inbox.db"))
    c = TestClient(app)
    assert c.get("/api/v4/paramlive").status_code == 401                     # behind the same login
    assert c.get("/api/v4/paramlive/S2_ST_ROC").status_code == 401
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    assert "paramlive" in app.state.more
    return c


# ---------------------------------------------------------------- the routes
def test_missing_file_is_not_available_yet_never_a_404(client, psdir):
    d = client.get("/api/v4/paramlive").json()
    assert d["available"] is False and d["none_ko"] == "아직 첫 계산 전입니다 (매일 10:00 KST에 계산)"
    assert "cells" not in d and "error_ko" not in d and d["about_ko"] and "판정 아님" in d["label_ko"]
    r = client.get("/api/v4/paramlive/S2_ST_ROC")
    assert r.status_code == 200 and r.json()["available"] is False and r.json()["strategy"] == "S2_ST_ROC"
    assert client.get("/api/v4/paramlive/NOT_ONE").status_code == 200     # nothing to tell a name from yet


def test_overview_is_compact_with_the_jobs_counts(client, psdir):
    s = summary()
    _write(psdir, "last.json", s)
    d = client.get("/api/v4/paramlive").json()
    assert d["available"] is True and d["status"] == "ok" and d["line_ko"] == s["line_ko"]
    assert (d["through_day"], d["days"], d["days_remaining"], d["generated_ms"]) == ("2026-10-08", 4, 0, GEN)
    assert d["overview"] == s["overview"] and d["texts_ko"] == TEXTS and d["min_trades"] == 20
    assert d["settings"] == s["settings"] and d["multipliers"] == [0.5, 0.75, 1.25, 1.5] and d["tfs"] == list(TFS)
    assert d["notes"] == s["notes"] and "error_ko" not in d and "error" not in d    # 분석 paints a bare d.error as a failure
    assert len(d["cells"]) == 8
    for c in d["cells"]:
        assert set(c) == {"strategy", "tf", "name_ko", "base", "real", "parity", "k", "better", "stars", "best",
                          "summary_ko", "summary_rule"}
        assert set(c["base"]) == {"trades", "pnl", "win_rate"} and set(c["real"]) == {"trades", "pnl"}
        assert set(c["parity"]) == {"share"}
    assert "variants" not in json.dumps(d["cells"]) and "params" not in json.dumps(d["cells"])
    src = {(c["strategy"], c["tf"]): c for c in s["cells"]}
    for c in d["cells"]:
        o = src[(c["strategy"], c["tf"])]
        assert (c["k"], c["better"], c["stars"]) == (o["k"], o["better"], o["stars"])
        assert c["base"]["trades"] == o["base"]["trades"] and c["parity"]["share"] == o["parity"]["share"]
    assert sum(c["k"] for c in d["cells"]) == d["overview"]["variants"]
    assert sum(c["better"] for c in d["cells"]) == d["overview"]["better"]
    one = next(c for c in d["cells"] if c["strategy"] == "S2_ST_ROC" and c["tf"] == "1h")
    assert one["name_ko"] == "슈퍼트렌드·ROC" and one["stars"] == 1
    assert one["best"]["param"] and one["best"]["param_ko"] == PARAM_KO[one["best"]["param"]] and one["best"]["mult"]
    assert len(client.get("/api/v4/paramlive").content) < 20_000


def test_strategy_route_gives_full_rows_with_korean_names(client, psdir):
    s = summary(status="filling")
    _write(psdir, "last.json", s)
    d = client.get("/api/v4/paramlive/S2_ST_ROC").json()
    assert d["available"] is True and d["status"] == "filling" and d["days_remaining"] == 3
    assert d["strategy"] == "S2_ST_ROC" and d["name_ko"] == "슈퍼트렌드·ROC" and d["texts_ko"] == TEXTS
    assert d["through_day"] == "2026-10-08" and d["days"] == 4
    assert [c["tf"] for c in d["cells"]] == list(TFS)
    for c in d["cells"]:
        assert len(c["variants"]) == 8 and {"base", "real", "parity", "k", "better", "stars", "best"} <= set(c)
        for p in c["params"]:
            assert p["param_ko"] == PARAM_KO[p["name"]]
        for v in c["variants"]:
            assert v["param_ko"] == PARAM_KO[v["param"]] and "diff_pnl" in v and "same_as_base" in v and "luck" in v
    h1 = d["cells"][2]
    assert [v["key"] for v in h1["variants"] if v["star"]] == ["st_atr_lenx1.5"]
    four = d["cells"][3]
    assert [v["key"] for v in four["variants"] if v["same_as_base"]] == ["st_multx0.75"] and four["k"] == 7
    n03 = client.get("/api/v4/paramlive/N03_ADX_GC").json()
    lens = next(v for v in n03["cells"][0]["variants"] if v["param"] == "kst_roc_lens")
    assert lens["param_ko"] == "KST ROC 길이들" and isinstance(lens["value"], list)
    assert all(v["luck"]["small"] for c in n03["cells"] for v in c["variants"])


# ---------------------------------------------------------------- the owners' one line, 지켜볼 후보, cells ready
def _vrow(key, param, mult, value, default, diff, star=False, same=False, ratio=0.3, small=False, param_ko=None):
    return {"key": key, "param": param, "param_ko": param_ko, "mult": mult, "value": value, "default": default,
            "same_as_base": same, "trades": 30, "pnl": -100.0 + diff, "diff_pnl": diff, "star": star,
            "luck": None if same else {"small": small, "ratio": None if small else ratio, "beyond": star}}


def _c(trades=30, k=12, better=3, stars=0):
    return {"base": {"trades": trades, "pnl": -100.0}, "k": k, "better": better, "stars": stars}


def test_cell_summary_rules_first_match_wins():
    star_a = _vrow("st_atr_lenx1.5", "st_atr_len", 1.5, 15, 10, 1234.5, star=True, ratio=1.4, param_ko="슈퍼트렌드 ATR 길이")
    star_b = _vrow("st_multx0.5", "st_mult", 0.5, 3.0, 6.0, 300.0, star=True, ratio=1.9, param_ko="슈퍼트렌드 배수")
    plain = _vrow("st_multx1.5", "st_mult", 1.5, 9.0, 6.0, 50.0)
    tail = "운으로 설명하기 어려운 차이 → 지켜볼 후보 (바꿀지는 30일 판정 뒤 두 분이)"
    # 1. too few default trades: before anything else (even a star or k == 0)
    assert P.cell_summary(_c(trades=12, stars=1), [star_a]) == ("thin", "아직 거래 12건뿐이라 판단하기 이릅니다 (거래 20건부터 판단)")
    assert P.cell_summary(_c(trades=0, k=0), []) == ("thin", "아직 거래가 없어 판단하기 이릅니다 (거래 20건부터 판단)")
    assert P.cell_summary(_c(trades=25), [], min_trades=30)[1].endswith("(거래 30건부터 판단)")    # the file's own floor
    # 2. a star: the starred variant that made the most over the default, its Korean name, default -> value, +$
    assert P.cell_summary(_c(stars=2, better=9), [plain, star_b, star_a]) == \
        ("star", f"★ 슈퍼트렌드 ATR 길이 10→15: 기본값보다 +$1,234.50, {tail}")
    lens = _vrow("kst_roc_lensx1.5", "kst_roc_lens", 1.5, [15, 22, 30, 45], [10, 15, 20, 30], 80.0, star=True)
    assert P.cell_summary(_c(stars=1), [lens]) == ("star", f"★ kst_roc_lens 10·15·20·30→15·22·30·45: 기본값보다 +$80.00, {tail}")
    # 3. no variant changed a signal; 4. more than half made more; 5. the rest (half exactly is not "more")
    assert P.cell_summary(_c(k=0, better=0), []) == ("same", "숫자를 바꿔도 신호가 달라지지 않았습니다")
    assert P.cell_summary(_c(k=12, better=7), [plain]) == \
        ("more", "숫자를 바꾼 12개 중 7개가 더 벌었지만 운 기준선을 넘은 것은 없음 → 아직 바꿀 근거 없음")
    assert P.cell_summary(_c(k=12, better=6), [plain]) == \
        ("less", "숫자를 바꾼 12개 대부분이 기본값보다 못하거나 비슷함 → 기본값 유지가 무난")
    assert P.cell_summary(_c(k=5, better=0), []) == ("less", "숫자를 바꾼 5개 대부분이 기본값보다 못하거나 비슷함 → 기본값 유지가 무난")
    # the page's number words
    assert [P.value_ko(x) for x in (10, 6.0, 0.75, 1.125, 0.0075, [5, 8, 10, 15], None, 1500)] == \
        ["10", "6", "0.75", "1.125", "0.0075", "5·8·10·15", "—", "1,500"]
    assert [P.money_ko(x) for x in (4165.61, -51.15, 0, 0.001, None)] == ["+$4,165.61", "−$51.15", "$0.00", "$0.00", "—"]
    for rule, line in [P.cell_summary(_c(**kw), vs) for kw, vs in ((dict(trades=3), []), (dict(stars=1), [star_a]),
                                                                    (dict(k=0), []), (dict(better=9), []), ({}, []))]:
        assert "통과" not in line and "합격" not in line                          # a shadow, never a verdict


def test_every_cell_carries_its_line_on_both_routes(client, psdir):
    s = summary()
    s["cells"][1]["base"]["trades"] = 7                                        # S2_ST_ROC 30m: too early
    _write(psdir, "last.json", s)
    one = client.get("/api/v4/paramlive/S2_ST_ROC").json()
    lines = {c["tf"]: (c["summary_rule"], c["summary_ko"]) for c in one["cells"]}
    assert lines["30m"] == ("thin", "아직 거래 7건뿐이라 판단하기 이릅니다 (거래 20건부터 판단)")
    assert lines["1h"] == ("star", "★ 슈퍼트렌드 ATR 길이 10→15: 기본값보다 +$20.00, 운으로 설명하기 어려운 차이 → 지켜볼 후보 "
                                   "(바꿀지는 30일 판정 뒤 두 분이)")
    assert lines["15m"] == ("less", "숫자를 바꾼 8개 대부분이 기본값보다 못하거나 비슷함 → 기본값 유지가 무난")   # 4 of 8: half
    grid = client.get("/api/v4/paramlive").json()
    for c in grid["cells"]:                                                    # the map's tooltips say the same
        full = next(x for x in client.get(f"/api/v4/paramlive/{c['strategy']}").json()["cells"] if x["tf"] == c["tf"])
        assert (c["summary_rule"], c["summary_ko"]) == (full["summary_rule"], full["summary_ko"])


def test_candidates_closest_to_the_luck_line_first(client, psdir):
    s = summary()
    by = {(c["strategy"], c["tf"]): {v["key"]: v for v in c["variants"]} for c in s["cells"]}
    by[("S2_ST_ROC", "1h")]["st_atr_lenx1.5"]["luck"]["ratio"] = 1.3          # the starred one
    by[("S2_ST_ROC", "15m")]["st_multx0.5"]["luck"]["ratio"] = 0.9
    by[("S2_ST_ROC", "30m")]["st_atr_lenx1.25"]["luck"]["ratio"] = -0.2       # below the default per trade: never
    by[("S2_ST_ROC", "4h")]["st_multx0.75"]["luck"] = {"small": False, "ratio": 5.0}   # same signals: never
    _write(psdir, "last.json", s)
    d = client.get("/api/v4/paramlive").json()
    cands = d["candidates"]
    assert len(cands) == P.CANDIDATES == 8
    assert all(set(c) == set(P.CANDIDATE_KEYS) for c in cands)
    assert set(P.CANDIDATE_KEYS) == {"strategy", "name_ko", "tf", "param", "param_ko", "default", "value", "mult", "trades",
                                     "diff_pnl", "ratio", "star", "combo", "parts", "change_ko"}
    assert all(c["combo"] == "single" and len(c["parts"]) == 1 for c in cands)          # a version-1 file: one change each
    first, second = cands[0], cands[1]
    assert (first["strategy"], first["tf"], first["param"], first["mult"], first["ratio"], first["star"]) == \
        ("S2_ST_ROC", "1h", "st_atr_len", 1.5, 1.3, True)
    assert (first["name_ko"], first["param_ko"], first["default"], first["value"]) == ("슈퍼트렌드·ROC", PARAM_KO["st_atr_len"], 10, 15.0)
    assert (second["tf"], second["param"], second["mult"], second["ratio"], second["star"]) == ("15m", "st_mult", 0.5, 0.9, False)
    rest = cands[2:]
    assert all(c["ratio"] == 0.19 for c in rest)                               # the same ratio: more money first
    assert [c["diff_pnl"] for c in rest] == sorted((c["diff_pnl"] for c in rest), reverse=True)
    assert all(c["strategy"] == "S2_ST_ROC" for c in cands)                    # N03's variants are all under the floor
    assert not any(c["tf"] == "4h" and c["param"] == "st_mult" and c["mult"] == 0.75 for c in cands)
    assert not any(c["ratio"] <= 0 for c in cands)
    # nothing the job could test yet: an empty list (the page says so)
    for c in s["cells"]:
        for v in c["variants"]:
            if v["luck"]:
                v["luck"].update(small=True, ratio=None)
    _write(psdir, "last.json", s, mtime=time.time() + 5)
    assert client.get("/api/v4/paramlive").json()["candidates"] == []


def test_cells_ready_counts_the_defaults_with_enough_trades(client, psdir):
    s = summary()
    _write(psdir, "last.json", s)
    d = client.get("/api/v4/paramlive").json()
    assert (d["cells_ready"], d["cells_total"]) == (8, 8)
    for c in s["cells"][:3]:
        c["base"]["trades"] = 19                                               # one under the job's floor (20)
    _write(psdir, "last.json", s, mtime=time.time() + 5)                      # same size: a new mtime
    d = client.get("/api/v4/paramlive").json()
    assert (d["cells_ready"], d["cells_total"]) == (5, 8)
    assert d["overview"] == s["overview"]                                      # the job's own totals stay as written
    assert "candidates" not in client.get("/api/v4/paramlive/S2_ST_ROC").json()


def _with_pairs(s, strategy="S2_ST_ROC", tf="1h", star_pair=True):
    """The job's version 2 on one cell: singles carry combo + parts, and the four pairs of its two parameters (each
    x0.75 or x1.25) are added; the x1.25 / x0.75 pair is starred and made the most (or not starred)."""
    c = next(x for x in s["cells"] if x["strategy"] == strategy and x["tf"] == tf)
    for v in c["variants"]:
        v.update(combo="single", parts=[{k: v[k] for k in ("param", "mult", "value", "default")}])
    (a, b) = c["params"][:2]
    for ma in (0.75, 1.25):
        for mb in (0.75, 1.25):
            win = (ma, mb) == (1.25, 0.75)
            diff = 60.0 if win else -10.0 * ma
            parts = [{"param": p["name"], "mult": m, "value": round(p["default"] * m, 3), "default": p["default"]}
                     for p, m in ((a, ma), (b, mb))]
            c["variants"].append({
                "key": f"{a['name']}x{ma:g}+{b['name']}x{mb:g}", "combo": "pair", "parts": parts,
                "param": None, "mult": None, "value": None, "default": None, "same_as_base": False, "signals": 50,
                "signals_diff": 9, "trades": 31, "wins": 16, "win_rate": 16 / 31, "pnl": -100.0 + diff, "equity": 4900 + diff,
                "max_dd": 0.1, "open": False, "bust": False, "diff_pnl": diff,
                "luck": {"small": False, "z": 3.0 if win else 0.1, "z_need": 2.7, "ratio": 1.5 if win else 0.04, "beyond": win},
                "both_halves": win, "star": win and star_pair})
    c["k"] += 4
    c["better"] += 1
    c["stars"] = sum(1 for v in c["variants"] if v["star"])
    s["pair_multipliers"] = [0.75, 1.25]
    s["overview"].update(singles=s["overview"]["variants"], pairs=4)
    s["overview"]["variants"] += 4
    return c


def test_pairs_name_both_changes_and_old_rows_read_as_one_change(client, psdir):
    s = summary()
    cell = _with_pairs(s)
    cell["best"] = {"key": "st_atr_lenx1.25+st_multx0.75", "combo": "pair",
                    "parts": next(v for v in cell["variants"] if v["key"] == "st_atr_lenx1.25+st_multx0.75")["parts"],
                    "diff_pnl": 60.0, "star": True}
    _write(psdir, "last.json", s)
    ko_a, ko_b = PARAM_KO["st_atr_len"], PARAM_KO["st_mult"]
    pair_words = f"{ko_a} 10→12.5 + {ko_b} 6→4.5"
    d = client.get("/api/v4/paramlive/S2_ST_ROC").json()
    assert d["pair_multipliers"] == [0.75, 1.25]
    h1 = next(c for c in d["cells"] if c["tf"] == "1h")
    pairs = [v for v in h1["variants"] if v["combo"] == "pair"]
    assert len(pairs) == 4 and len(h1["variants"]) == 12
    for v in pairs:
        assert v["param"] is None and len(v["parts"]) == 2
        assert [p["param_ko"] for p in v["parts"]] == [ko_a, ko_b]
    for v in h1["variants"]:
        if v["combo"] == "single":
            assert len(v["parts"]) == 1 and v["parts"][0]["param_ko"] == v["param_ko"] == PARAM_KO[v["param"]]
    # the starred pair made the most of the two starred rows: the one line names both changes
    assert h1["summary_rule"] == "star"
    assert h1["summary_ko"] == f"★ {pair_words}: 기본값보다 +$60.00, 운으로 설명하기 어려운 차이 → 지켜볼 후보 (바꿀지는 30일 판정 뒤 두 분이)"
    # a version-1 row (no combo, no parts) reads as its one change
    n03 = client.get("/api/v4/paramlive/N03_ADX_GC").json()["cells"][0]["variants"][0]
    assert n03["combo"] == "single" and n03["parts"] == [{"param": "adx_len", "mult": 0.5, "value": 7.0, "default": 14,
                                                          "param_ko": PARAM_KO["adx_len"]}]
    # the map's compact best and 지켜볼 후보 carry both changes
    grid = client.get("/api/v4/paramlive").json()
    best = next(c for c in grid["cells"] if c["strategy"] == "S2_ST_ROC" and c["tf"] == "1h")["best"]
    assert best["combo"] == "pair" and [p["param_ko"] for p in best["parts"]] == [ko_a, ko_b] and best["param"] is None
    first = grid["candidates"][0]
    assert (first["combo"], first["change_ko"], first["ratio"], first["star"], first["param"]) == ("pair", pair_words, 1.5, True, None)
    assert [p["param_ko"] for p in first["parts"]] == [ko_a, ko_b]
    single = next(c for c in grid["candidates"] if c["combo"] == "single")
    assert single["change_ko"] == f"{single['param_ko']} {P.value_ko(single['default'])}→{P.value_ko(single['value'])}"
    assert P.change_ko({"key": "x", "parts": []}) == "x"


def test_unknown_strategy_is_404_once_a_summary_exists(client, psdir):
    _write(psdir, "last.json", summary())
    r = client.get("/api/v4/paramlive/NOT_A_STRATEGY")
    assert r.status_code == 404 and r.json()["detail"] == "그런 매매법이 없습니다"
    assert client.get("/api/v4/paramlive/F9_FVG").status_code == 404           # DeepSeek: not in the shadow


def test_error_json_newer_than_the_summary_is_shown_next_to_the_last_good_data(client, psdir):
    _write(psdir, "last.json", summary())
    err = {"generated_ms": GEN + 86_400_000, "error": "1m bars of 2026-10-09 unavailable: timeout",
           "line_ko": "커스텀값 그림자: 이번 밤 계산 못 함 (1m bars of 2026-10-09 unavailable: timeout)"}
    _write(psdir, "error.json", err)
    d = client.get("/api/v4/paramlive").json()
    assert d["available"] is True and d["error_ko"] == err["line_ko"] and d["error_at"] == err["generated_ms"]
    assert len(d["cells"]) == 8 and "error" not in d
    s = client.get("/api/v4/paramlive/S2_ST_ROC").json()
    assert s["error_ko"] == err["line_ko"] and len(s["cells"]) == 4
    # an older failure (the good night after it wrote last.json) is not news
    _write(psdir, "error.json", {**err, "generated_ms": GEN - 86_400_000})
    assert "error_ko" not in client.get("/api/v4/paramlive").json()
    # the very first night failed: no summary, the failure line
    os.remove(os.path.join(psdir, "last.json"))
    d = client.get("/api/v4/paramlive").json()
    assert d["available"] is False and d["none_ko"].startswith("아직 첫 계산 전") and d["error_ko"] == err["line_ko"]


def test_damaged_no_run_and_nan_files_never_give_a_500(client, psdir):
    _write(psdir, "last.json", '{"status": "ok", "cells": [')                # half-written
    d = client.get("/api/v4/paramlive").json()
    assert d["available"] is False and d["none_ko"] == P.BAD_KO
    assert client.get("/api/v4/paramlive/S2_ST_ROC").json()["available"] is False
    _write(psdir, "last.json", "[1, 2, 3]")
    assert client.get("/api/v4/paramlive").json()["none_ko"] == P.BAD_KO
    _write(psdir, "last.json", {"status": "ok", "cells": [{"strategy": "S2_ST_ROC", "tf": "1h", "base": 5}], "settings": [1]})
    r = client.get("/api/v4/paramlive")
    assert r.status_code == 200 and r.json()["available"] is False
    _write(psdir, "last.json", {"status": "no_run", "generated_ms": GEN, "line_ko": "커스텀값 그림자: 실행 중인 규칙봇 기록 없음"})
    d = client.get("/api/v4/paramlive").json()
    assert d["available"] is False and d["status"] == "no_run" and d["none_ko"] == "커스텀값 그림자: 실행 중인 규칙봇 기록 없음"
    _write(psdir, "last.json", json.dumps(summary(nan=True)))                 # json.dumps writes NaN / Infinity
    assert "NaN" in _read(psdir, "last.json")
    r = client.get("/api/v4/paramlive/S2_ST_ROC")
    assert r.status_code == 200
    c = r.json()["cells"][0]
    assert c["base"]["mean_ret"] is None and c["variants"][0]["luck"]["z"] is None
    assert client.get("/api/v4/paramlive").status_code == 200


def test_parsed_once_per_file_change_and_nothing_written(psdir):
    path = _write(psdir, "last.json", summary(), mtime=time.time() - 60)
    before = sorted(os.listdir(psdir))
    a, b = P._summary(psdir), P._summary(psdir)
    assert a[1] is b[1] and P.overview(psdir)["available"] is True
    s = summary(status="filling")
    _write(psdir, "last.json", s)
    assert P.overview(psdir)["status"] == "filling" and P._summary(psdir)[1] is not a[1]
    assert sorted(os.listdir(psdir)) == before == ["last.json"] and os.path.exists(path)
    src = _read(ROOT, "paperbot", "dash", "more", "paramlive.py")
    assert "sqlite3" not in src and not re.search(r"open\([^)]*['\"][wa]", src)
    assert "import paramshadow" not in src and "from ...paramshadow" not in src and "from ... import paramshadow" not in src
    # the default folder is the job's own (deploy/paperbot-paramshadow.service --out)
    assert re.search(r'^DEFAULT_OUT = "%s"$' % re.escape(P.DIR), _read(ROOT, "paperbot", "paramshadow.py"), re.M)
    assert f"--out {P.DIR}" in _read(ROOT, "deploy", "paperbot-paramshadow.service")


# ---------------------------------------------------------------- the pages
def _no_unsafe(js):
    for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "DOMParser", "eval(", "toLocaleString", "toFixed(2)"):
        assert bad not in js, bad
    assert "통과" not in js and "합격" not in js                              # a shadow, never a verdict


def test_the_analysis_view_is_registered_for_the_36():
    an = _read(SCREENS, "analysis.js")
    assert 'import {paramlive} from "./analysis-paramlive.js";' in an
    assert re.search(r'\{id: "paramlive", label: "커스텀값 비교", path: "/api/v4/paramlive", render: paramlive, groups: "core",', an)
    css = _read(SCREENS, "analysis.css")
    assert '@import url("analysis-paramlive.css");' in css and '@import url("strategies-paramlive.css");' in css
    js = _read(SCREENS, "analysis-paramlive.js")
    assert "export function paramlive(d, env)" in js and 'ctx.href("strategies", s)' in js
    assert 'ctx.href("strategies", c.strategy, {tf: c.tf})' in js
    assert "변형 ${fmt.int(o.variants || 0)}개${mix} 중 기본값보다 번 것" in js and "우연으로도 최대" in js and "재계산 일치" in js
    _no_unsafe(js)
    for p in ("analysis-paramlive.css", "strategies-paramlive.css"):
        c = re.sub(r"/\*.*?\*/", "", _read(SCREENS, p), flags=re.S)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", c) and not re.search(r"\brgba?\(\s*\d", c), p
        assert "var(--up)" not in c or p == "strategies-paramlive.css"           # the map's tint is the neutral pair
    assert "--cmp-hi" in _read(SCREENS, "analysis-paramlive.css")
    assert "/api/v4/paramlive" in _read(V4, "INVENTORY.md")


def test_the_detail_card_is_for_the_36_only_after_the_parameter_card():
    detail = _read(SCREENS, "strategies-detail.js")
    assert 'import {paramliveCard} from "./strategies-paramlive.js";' in detail
    lines = detail.splitlines()
    i = next(n for n, x in enumerate(lines) if re.match(r"^\s*paramsCard\(ctx, name, kind, \{after: profCard, scope: sc\}\);", x))
    assert re.match(r'^\s*if \(group === "core" && kind === "strategy"\) paramliveCard\(ctx, name, \{after: profCard, scope: sc, tf: v\.tf\}\);',
                    lines[i + 1])
    js = _read(SCREENS, "strategies-paramlive.js")
    assert "export function paramliveCard(ctx, name" in js and "`/api/v4/paramlive/${encodeURIComponent(name)}`" in js
    assert 'plate: "커스텀값 실시간 비교", sub: "v4 시작부터 · 숫자를 바꾼 그림자 계좌 · 매일 10:00 갱신"' in js
    assert 'cls: "strat-o7 strat-pl"' in js and 'nx.classList.contains("strat-pm")' in js
    for words in ("기본값(재계산)", "실제 계좌", "재계산 일치", "기본값과 신호 같음", "거래 부족", "운 기준선까지", "채우는 중", "지난 계산 실패",
                  "기본값 대비", "motion.shimmer(", "ui.errorBox(err, load)", "ui.assume()"):
        assert words in js, words
    assert "운 기준선 대비" not in js and "표본 적음" not in js         # the luck test reads as a percentage now
    assert '"luck", "parity", "caution"' in js
    _no_unsafe(js)
    assert '@import url("strategies-paramlive.css");' in _read(SCREENS, "strategies.css")
    css = _read(SCREENS, "strategies-paramlive.css")
    assert "container-type: inline-size" in css and "@container (min-width: 480px)" in css


def test_the_card_reads_at_a_glance():
    """Second round (10/10): the timeframe's one line on top, five bars per parameter, the luck line as a percentage,
    the pairs in their own group; all drawn with h() / s() and tokens."""
    js = _read(SCREENS, "strategies-paramlive.js")
    # the one-line reading: the server's words, the accent only for a ★
    assert "function sayLine(c)" in js and "c.summary_ko" in js and 'c.summary_rule === "star"' in js
    assert js.index("sayLine(c),") < js.index('h("div", {class: "pl-sides"}')           # first in the timeframe
    # the five bars: an SVG through s(), ×0.5 ×0.75 기본 ×1.25 ×1.5 on one scale, ★ above, 같음, the value under each bar
    assert 'import {h, s, put, ui, fmt, motion} from "../core/pb.js";' in js
    assert 's("svg", {class: "pl-ch-svg"' in js and 's("rect", {class: ["pl-ch-bar"' in js and 's("line", {class: "pl-ch-zero"' in js
    assert 'x.base ? "기본" : multKo(x.mult)' in js and '(x.same ? "같음"' in js and 'h("b", {class: "pl-ch-star"}, "★")' in js
    assert "숫자 하나만 바꾸면" in js and "가운데가 지금 숫자, 왼쪽은 작게 · 오른쪽은 크게" in js
    assert js.index("paramChart(g.p, g.rows, c.base)") < js.index("headRow(), g.rows.map(")   # the bars above the rows
    # the luck line as a percentage, the hint once per timeframe, "거래 부족" for a small sample
    assert "`운 기준선까지 ${fmt.int(luckPct(l.ratio))}%`" in js and "100%를 넘고 기간 앞·뒤 모두 나아야 ★" in js
    assert js.count("100%를 넘고 기간 앞·뒤 모두 나아야 ★") == 1 and '"거래 부족")' in js
    # the pairs: their own group after the parameters, both changes named, top PAIR_TOP then 전체 보기 (N개)
    assert "두 숫자 함께 바꾸기" in js and "ui.disclosure(`전체 보기 (${fmt.int(n)}개)`" in js and "export const PAIR_TOP = 8;" in js
    assert "groups(c, minT),\n    pairSection(c, minT)," in js
    assert "const singles = (c.variants || []).filter((v) => !isPair(v));" in js
    css = re.sub(r"/\*.*?\*/", "", _read(SCREENS, "strategies-paramlive.css"), flags=re.S)
    for sel in (".pl-say.is-star", ".pl-ch-bar.up", ".pl-ch-bar.down", ".pl-ch-bar.is-base", ".pl-ch-hl", ".pl-row.is-pair", ".pl-lbar::after"):
        assert sel in css, sel
    assert "var(--accent-soft)" in css and "var(--up)" in css and "var(--down)" in css
    an = _read(SCREENS, "analysis-paramlive.js")
    assert "function candidatesCard(ctx, d)" in an and "out.push(candidatesCard(ctx, d));" in an
    assert an.index("out.push(candidatesCard(ctx, d));") < an.index('plate: "한눈에"')        # the top of the view
    assert "판단할 수 있는 칸 (기본값 거래 ${fmt.int(minT)}건 이상): " in an and "d.cells_ready" in an
    assert "아직 운 기준선 가까이 간 변형이 없습니다 — 거래가 쌓이면 여기에 나타납니다" in an
    assert 'href: ctx.href("strategies", c.strategy, {tf: c.tf})' in an and "luckBar(c.ratio)" in an
    assert "[`${name} · ${fmt.tfKo(c.tf)}`, c.summary_ko," in an                              # the map's tooltips
    assert "하나씩 ${fmt.int(o.singles || 0)} · 두 숫자 함께 ${fmt.int(o.pairs)}" in an
    _no_unsafe(an)
    _no_unsafe(js)


def test_value_and_tint_helpers_in_node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    pl, an = _read(SCREENS, "strategies-paramlive.js"), _read(SCREENS, "analysis-paramlive.js")
    grab = lambda src, n: re.search(r"^export function %s\(.*?^}$" % n, src, re.S | re.M).group(0)[len("export "):]  # noqa: E731
    js = ("const fmt = {num: (x, d) => (x < 0 ? '−' : '') + Math.abs(x).toFixed(d)};\n" + grab(pl, "valueKo") + "\n" + grab(an, "step")
          + "\nconsole.log(JSON.stringify([[10, 6.0, 0.75, 1.125, 0.0075, [5, 8, 10, 15], null].map(valueKo),"
            " [[0, 0], [0, 12], [2, 12], [5, 12], [8, 12], [12, 12]].map(([b, k]) => step(b, k))]));")
    out = json.loads(subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=20, check=True).stdout)
    assert out == [["10", "6", "0.75", "1.125", "0.0075", "5·8·10·15", "—"], ["", "0", "1", "2", "3", "4"]]


def test_luck_percent_bars_and_pair_helpers_in_node():
    """The card's helpers as they run in the page: the luck line as a percentage, the five bars' order and shared
    scale, the pair rows' order and split, the words of a change (one number or two, a version-1 row too)."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    pl, an = _read(SCREENS, "strategies-paramlive.js"), _read(SCREENS, "analysis-paramlive.js")
    fn = lambda src, n: re.search(r"^export function %s\(.*?^}$" % n, src, re.S | re.M).group(0)[len("export "):]  # noqa: E731
    one = lambda src, n: re.search(r"^(?:export )?const %s = .*$" % n, src, re.M).group(0).replace("export ", "", 1)  # noqa: E731
    js = "\n".join([
        "const fmt = {num: (x, d) => (x < 0 ? '−' : '') + Math.abs(x).toFixed(d)};",
        fn(pl, "valueKo"), one(pl, "multKo"), fn(pl, "luckPct"), fn(pl, "chartSlots"), one(pl, "CH_H"), fn(pl, "chartScale"),
        one(pl, "isPair"), fn(pl, "changeKo"), one(pl, "PAIR_TOP"), fn(pl, "pairRows"), fn(an, "changeWords"),
        "const rows = [{mult: 1.5, pnl: 30, trades: 9}, {mult: 0.5, pnl: -10, trades: 9, star: true}, {mult: 1.25, pnl: 0, trades: 9, same_as_base: true},"
        " {mult: 0.75, pnl: 5, trades: 9}, {combo: 'pair', mult: null, pnl: 99}];",
        "const slots = chartSlots({default: 10}, rows.filter((v) => !isPair(v)), {pnl: -20, trades: 30});",
        "const Y = chartScale([30, -10]);",
        "const pr = Array.from({length: 11}, (_, i) => ({key: 'p' + i, combo: 'pair', diff_pnl: (i * 7) % 11 - 5}));",
        "const pp = pairRows(pr.concat([{key: 's', combo: 'single', diff_pnl: 99}]));",
        "const A = {param: 'st_mult', param_ko: '슈퍼트렌드 배수', mult: 0.75, value: 4.5, default: 6.0};",
        "const B = {param: 'roc_len', param_ko: 'ROC 길이', mult: 1.25, value: 11, default: 9};",
        "console.log(JSON.stringify([[0.37, -0.2, 1.21, 0, 0.004, null].map(luckPct),",
        " slots.map((x) => [x.mult, x.pnl, !!x.base, x.same, x.star]),",
        " [Y(30), Y(0), Y(-10), CH_H - CH_PAD], (Y(0) - Y(30)) / (Y(-10) - Y(0)), chartScale([0, 0])(0),",
        " [isPair({combo: 'pair'}), isPair({parts: [A, B]}), isPair({parts: [A]}), isPair({param: 'x'})],",
        " [changeKo([A, B]), changeKo([A]), changeKo([])],",
        " [pp.n, pp.top.length, pp.rest.length, pp.top.map((v) => v.diff_pnl), PAIR_TOP],",
        " [changeWords({parts: [A, B], combo: 'pair'}), changeWords({param: 'st_mult', param_ko: '슈퍼트렌드 배수', mult: 0.5, value: 3, default: 6}),",
        "  changeWords({change_ko: '서버 글', parts: [A]}), changeWords(null)]]));",
    ])
    out = json.loads(subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=20, check=True).stdout)
    pct, slots, ys, ratio, flat, pairs, words, prows, cw = out
    assert pct == [37, 0, 121, 0, 0, None]                                     # below the default: 0%
    assert slots == [[0.5, -10, False, False, True], [0.75, 5, False, False, False], [1, -20, True, False, False],
                     [1.25, 0, False, True, False], [1.5, 30, False, False, False]]   # ×0.5 ×0.75 기본 ×1.25 ×1.5
    assert ys[0] == 3 and ys[2] == ys[3] and ys[0] < ys[1] < ys[2]           # the highest at the top, the lowest at the bottom
    assert abs(ratio - 3) < 1e-9 and flat == 3                                 # heights in proportion to |P&L|
    assert pairs == [True, True, False, False]
    assert words == ["슈퍼트렌드 배수 6→4.5 + ROC 길이 9→11", "슈퍼트렌드 배수 6→4.5", ""]
    assert prows == [11, 8, 3, [5, 4, 3, 2, 1, 0, -1, -2], 8]                  # pairs only, the most money first
    assert cw == [["슈퍼트렌드 배수 6→4.5 + ROC 길이 9→11", "×0.75 · ×1.25"], ["슈퍼트렌드 배수 6→3", "×0.5"],
                  ["서버 글", "×0.75"], ["—", ""]]


# ---------------------------------------------------------------- 예약 작업
def test_the_jobs_list_has_the_shadow_timer(monkeypatch):
    assert "paperbot-paramshadow" in J.UNITS and J._UNIT.match("paperbot-paramshadow")
    kit = _read(SCREENS, "server-kit.js")
    assert re.search(r'\{unit: "paperbot-paramshadow", ko: "커스텀값 그림자", what: "[^"]+", cal: \{daily: \[1, 0\]\}\}', kit)
    assert "OnCalendar=*-*-* 01:00:00 UTC" in _read(ROOT, "deploy", "paperbot-paramshadow.timer")     # = 10:00 KST
    assert '"paperbot-paramshadow": "커스텀값 그림자"' in _read(V4, "core", "since.js")
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        units = [c for c in cmd if c.startswith("paperbot-")]
        if units[0].endswith(".timer"):
            out = "\n\n".join(f"Id={u}\nLoadState=loaded\nUnitFileState=enabled\nActiveState=active\n"
                              f"LastTriggerUSec=Fri 2026-10-09 01:00:03 UTC\nNextElapseUSecRealtime=Sat 2026-10-10 01:00:00 UTC" for u in units)
        else:
            out = "\n\n".join(f"Id={u}\nLoadState=loaded\nActiveState=inactive\nSubState=dead\nResult=success\n"
                              f"ExecMainExitTimestamp=Fri 2026-10-09 01:04:00 UTC" for u in units)
        return SimpleNamespace(returncode=0, stdout=out, stderr="")
    monkeypatch.setattr(J.shutil, "which", lambda name: "/usr/bin/systemctl" if name == "systemctl" else None)
    d = J.jobs(run)
    row = d["jobs"]["paperbot-paramshadow"]
    assert d["available"] and row["state"] == "on" and row["ok"] is True
    assert row["last_ms"] == J.parse_ts("Fri 2026-10-09 01:00:03 UTC")
    assert row["next_ms"] == J.parse_ts("Sat 2026-10-10 01:00:00 UTC") and any("paperbot-paramshadow.timer" in c for c in calls)


def test_a_summary_of_another_run_is_not_shown(psdir, tmp_path):
    """After a reset the old run's summary stays until the next 10:00 run: the routes say so instead of showing it."""
    import contextlib
    import sqlite3
    from paperbot.store3 import Store3
    doc = summary()
    _write(psdir, P.SUMMARY, doc)
    db = str(tmp_path / "paper3.db")
    st = Store3(db)
    st.add_account("S2_ST_ROC@15m", "S2_ST_ROC", "15m", "strategy", doc["run_start_ms"], "paper-v4")
    st.commit()
    st.close()

    class Data:
        @contextlib.contextmanager
        def conn(self):
            c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                yield c
            finally:
                c.close()
    data = Data()
    P._RUN.clear()
    assert P.run_start(data) == doc["run_start_ms"]
    assert P.overview(psdir, run=P.run_start(data))["available"] is True
    other = P.overview(psdir, run=doc["run_start_ms"] + 86_400_000)
    assert other["available"] is False and other["status"] == "old_run" and "새 실행" in other["none_ko"]
    assert "cells" not in other
    one = P.strategy_view("S2_ST_ROC", psdir, run=doc["run_start_ms"] + 86_400_000)
    assert one["available"] is False and "cells" not in one
    assert P.run_start(object()) is None                                # no reader: shown as it is
    assert P.overview(psdir, run=None)["available"] is True
