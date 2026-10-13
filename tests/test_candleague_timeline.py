"""candleague 타임라인, server side: candleague/timeline.py (league.json key ``timeline``) written by runner.write_snapshots (via screens3.add_blocks).

Hand-made rows and trades: the start (one row when the install and the start are the same time, two otherwise), the 14일째 / 28일째 days (passed or
coming, by the engine's time), the first closed trade of each of the four watched kinds, the biggest single win and loss ($) of 실전 후보 and 대조
only, liquidations and busts, the order (newest first, undated last), the cap of 60, DeepSeek money both ways, JSON without NaN, deterministic, the
limits (no restart time in the snapshot) and hygiene."""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_candleague_riskview as RT  # noqa: E402
from candleague import runner as RN  # noqa: E402
from candleague import timeline as TL  # noqa: E402

T0, H, DAY, LU = RT.T0, RT.H, RT.DAY, RT.LU
DEC = {"phase": "observe", "checkpoints": {"observe_day": 14, "decide_day": 28}, "observe_ms": T0 + 14 * DAY, "decide_ms": T0 + 28 * DAY}


def t(sym, side, pnl, i, why="SL"):
    return RT.tr(side, T0 + i * H, T0 + i * H + H // 2, pnl, sym, why)


def world():
    rows = [RT.row("a-fq", "fq"), RT.row("a-ld", "ld", bust=True), RT.row("a-fqc", "fqc"), RT.row("a-ldc", "ldc"), RT.row("a-nv", "nv"),
            RT.row("ds-fq", "fq", kind="ds", wallet=None)]
    book = {"a-fq": [t("BTCUSDT", 1, 30.0, 5), t("ETHUSDT", -1, -80.0, 9), t("SOLUSDT", 1, 55.0, 12)],
            "a-ld": [t("BTCUSDT", 1, 5.0, 2), t("DOGEUSDT", -1, -900.0, 20, "LIQ")], "a-fqc": [t("BTCUSDT", 1, 1.0, 7)], "a-ldc": [],
            "a-nv": [t("BTCUSDT", 1, 777.0, 1)], "ds-fq": [t("BTCUSDT", 1, 99999.0, 0, "LIQ")]}
    return rows, book


def views(done=T0 + 15 * DAY, ds=False, dec=DEC, **kw):
    rows, book = world()
    return TL.timeline_views(book, rows, LU, dec, kw.get("start", T0), kw.get("started", T0), done, kw.get("notes"), ds)


def of(out, kind):
    return [r for r in out["rows"] if r["kind"] == kind]


def test_the_milestones_in_order_newest_first():
    out = views()
    rows = out["rows"]
    ms = [r["ms"] for r in rows]
    assert ms == sorted(ms, reverse=True) and out["cap"] == 60 and out["more"] == 0
    assert [r["kind"] for r in rows[:2]] == ["decide", "observe"]                                    # the 28일째 is still coming, the 14일째 has passed
    dc, ob = of(out, "decide")[0], of(out, "observe")[0]
    assert dc["state"] == "coming" and ob["state"] == "done" and dc["tag_ko"] == "28일째 판정" and ob["tag_ko"] == "14일째 확인"
    assert len(of(out, "start")) == 1 and of(out, "install") == [] and of(out, "start")[0]["ms"] == T0
    firsts = {r["suffix"]: r for r in of(out, "first")}
    assert set(firsts) == {"-fq", "-ld", "-fqc"} and firsts["-ld"]["ms"] == T0 + 2 * H + H // 2 and firsts["-ld"]["account"] == "a-ld"   # -ldc has no trade; -nv is not watched
    best, worst = of(out, "best"), of(out, "worst")
    assert {r["suffix"] for r in best} == {"-fq", "-ld"} and {r["suffix"] for r in worst} == {"-fq", "-ld"}
    fqb = next(r for r in best if r["suffix"] == "-fq")
    assert "+$55.00" in fqb["text_ko"] and "SOL 롱" in fqb["text_ko"] and fqb["account"] == "a-fq"
    assert "−$80.00" in next(r for r in worst if r["suffix"] == "-fq")["text_ko"] and "−$900.00" in next(r for r in worst if r["suffix"] == "-ld")["text_ko"]
    liq = of(out, "liq")
    assert len(liq) == 1 and liq[0]["suffix"] == "-ld" and liq[0]["account"] == "a-ld" and "DOGE 숏" in liq[0]["text_ko"]
    bust = of(out, "bust")
    assert len(bust) == 1 and bust[0]["approx"] is True and bust[0]["ms"] == liq[0]["ms"]                 # the last closed trade stands for the time
    assert all("777" not in r["text_ko"] for r in rows)                                                 # 메인 kinds other than -fq are not watched


def test_the_passed_and_coming_days_follow_the_engine_time():
    d = lambda done: {r["kind"]: r["state"] for r in of(views(done=done), "observe") + of(views(done=done), "decide")}   # noqa: E731
    assert d(T0 + 13 * DAY) == {"observe": "coming", "decide": "coming"}
    assert d(T0 + 14 * DAY) == {"observe": "done", "decide": "coming"}
    assert d(T0 + 28 * DAY) == {"observe": "done", "decide": "done"}
    assert "판정 단계로 바뀌었습니다" in of(views(done=T0 + 29 * DAY), "decide")[0]["text_ko"]
    out = views(dec=None)
    assert of(out, "observe") == [] and of(out, "decide") == []                                         # no decision block: the rows are simply absent


def test_install_and_start_apart_and_the_undated_notes():
    out = views(started=T0 - 3 * DAY, notes=["복원 메모", 5])
    assert [r["ms"] for r in of(out, "install")] == [T0 - 3 * DAY] and len(of(out, "start")) == 1
    assert out["undated_ko"] == ["복원 메모"] and any("다시 시작" in n for n in out["note_ko"])
    rows, book = world()
    rows[1]["bust"], book["a-ld"] = True, []                                                           # a bust without any closed trade: no time, last
    o = TL.timeline_views(book, rows, LU, DEC, T0, T0, T0 + 15 * DAY, None, False)
    assert o["rows"][-1]["kind"] == "bust" and o["rows"][-1]["ms"] is None and o["rows"][-1]["approx"] is False


def test_cap_and_the_deepseek_money_and_json():
    rows, book = world()
    for i in range(30):                                                                                 # 30 accounts with a liquidation each
        rows.append(RT.row(f"x{i}-ld", "ld", bust=True))
        book[f"x{i}-ld"] = [t("BTCUSDT", 1, -500.0, 30 + i, "LIQ")]
    out = TL.timeline_views(book, rows, LU, DEC, T0, T0, T0 + 15 * DAY, None, False)
    assert len(out["rows"]) <= 60 and len(of(out, "liq")) == TL.MAX_LIQ and len(of(out, "bust")) == TL.MAX_BUST and out["more"] == (31 - TL.MAX_LIQ) + (31 - TL.MAX_BUST)
    json.dumps(out, allow_nan=False)
    assert json.dumps(out, sort_keys=True) == json.dumps(TL.timeline_views(dict(reversed(list(book.items()))), list(reversed(rows)), LU, DEC, T0, T0, T0 + 15 * DAY, None, False), sort_keys=True)
    off = views()
    on = views(ds=True)
    assert "ds-fq" not in json.dumps(off) and "99999" not in json.dumps(off)
    assert any(r["account"] == "ds-fq" for r in on["rows"]) and any("99,999" in r["text_ko"] for r in on["rows"])


def test_nothing_yet_odd_input_and_hygiene():
    assert TL.timeline_views({}, [], LU, None)["rows"] == [] and TL.timeline_views({}, [], None, None)["headline_ko"] == "아직 적을 일이 없습니다"
    out = TL.timeline_views({"a-fq": [{"symbol": "BTCUSDT", "pnl": float("nan"), "exit_time": None}, {"exit_time": T0, "pnl": None}]}, [RT.row("a-fq", "fq")], LU, {"observe_ms": "x"}, "bad", None, None)
    json.dumps(out, allow_nan=False)
    assert [r["kind"] for r in out["rows"]] == ["first"]
    src = open(os.path.join(ROOT, "candleague", "timeline.py"), encoding="utf-8").read()
    for bad in ("import time", "import random", "import datetime", "time.time", "os.environ", "open(", "5000", "5,000", "import sqlite3"):
        assert bad not in src, bad


def test_write_snapshots_carries_the_timeline_only_with_a_lineup(tmp_path):
    lg = RT.fake_league(tmp_path)
    doc = RN.write_snapshots(str(tmp_path / "snap"), lg, RT.NOW, ds_money=False)
    saved = json.load(open(tmp_path / "snap" / "league.json"), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
    tl = saved["timeline"]
    assert tl == doc["timeline"] and "timeline_error" not in doc and {"start", "observe", "decide", "first", "best", "worst"} <= {r["kind"] for r in tl["rows"]}
    assert not any(r["account"] and r["account"].startswith("ds-") for r in tl["rows"])
    on = RN.write_snapshots(str(tmp_path / "snap2"), lg, RT.NOW, ds_money=True)["timeline"]
    assert any(r["account"] and r["account"].startswith("ds-") for r in on["rows"])
    d2 = RN.write_snapshots(str(tmp_path / "snap3"), RT.fake_league(tmp_path, owner=False, name="b.db"), RT.NOW, ds_money=True)
    assert "timeline" not in d2 and "timeline_error" not in d2
