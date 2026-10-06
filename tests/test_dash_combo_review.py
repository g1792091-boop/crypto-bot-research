"""조합 성과 review fixes (combo-paper): the vote rule keeps each timeframe's signal alive for its own bar only, the
'skipped while busy' count leaves out the entry an account holds or waits on now and anything after 'now', coin-flip
rule rows carry no dollar sum, the 계좌 겹침 progress is the closest PAIR's (not the best single account's), extra
accounts in the pairs table are marked as not pickable, the day still going on is named, inverse-volatility /
equal-risk weights say they were measured on the whole record (in-sample), and the page wiring of those fixes."""
import json
import os
import sqlite3
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from combo_world import blank, build, signal, trade  # noqa: E402

from paperbot.dash.more import combo as CB  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
H, M, DAY = 3_600_000, 60_000, 86_400_000
A = "S1_EMA_RSI_CHOP@1h"
A4 = "S1_EMA_RSI_CHOP@4h"
B15, B4 = "S2_ST_ROC@15m", "S2_ST_ROC@4h"
F1 = "RANDOM_1@1h"


class _Data:
    def __init__(self, db):
        self.db = db

    def conn(self):
        c = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        return c


def _read(*p):
    with open(os.path.join(*p), encoding="utf-8") as fh:
        return fh.read()


def _start():
    return (int(time.time() * 1000) - 40 * H) // H * H


def test_vote_keeps_each_timeframe_signal_alive_for_its_own_bar(tmp_path):
    db = str(tmp_path / "vote.db")
    start = _start()
    T = start + 6 * H
    st = blank(db, start, [(A, "strategy"), (A4, "strategy"), (B15, "strategy"), (B4, "strategy"), (F1, "random")])
    trade(st, A, T, T + H, 40.0, symbol="BTCUSDT", side=1)                  # a1
    trade(st, A, T + 5 * H, T + 6 * H, -10.0, symbol="ETHUSDT", side=-1)    # a2
    signal(st, "S2_ST_ROC", "15m", T - 2 * H, "BTCUSDT", 1)   # 2 h before a1: a 15m signal is long gone (old: alive 4 h)
    signal(st, "S2_ST_ROC", "4h", T + 3 * H, "ETHUSDT", -1)   # 2 h before a2: a 4h signal is still alive
    st.commit()
    st.close()
    c = CB.Combo(_Data(db))
    d = c.rules({"kind": "vote", "m": f"{A},S2_ST_ROC", "k": "2"}, now=T + 10 * H)
    rows = {r["id"]: r for r in d["rows"]}
    assert rows["rule"]["trades"] == 1 and rows["rule"]["pnl"] == -10           # a2 only
    assert rows["alone"]["trades"] == 2 and rows["dropped"]["trades"] == 1
    assert rows["flip_all"]["pnl"] is None and rows["flip_rule"]["pnl"] is None


def test_busy_count_leaves_out_the_open_entry_and_the_future(tmp_path):
    db = str(tmp_path / "busy.db")
    start = _start()
    T = start + 4 * H
    now = T + 20 * H
    st = blank(db, start, [(A, "strategy"), (A4, "strategy"), (F1, "random")])
    trade(st, A, T, T + 2 * H, 50.0, symbol="BTCUSDT", side=1)
    signal(st, "S1_EMA_RSI_CHOP", "4h", T - 4 * H, "BTCUSDT", 1)            # the 4h side: long BTC from before
    for bar in (T, T + H, T + 10 * H, T + 30 * H):                           # taken, busy, open now, after 'now'
        signal(st, "S1_EMA_RSI_CHOP", "1h", bar, "BTCUSDT", 1)
    st.put_state("accounts", now, {"engines": {A: {"position": {"symbol": "BTCUSDT", "side": 1, "entry_time": T + 10 * H + M,
                                                                 "signal": {"ts": T + 10 * H - 1}}, "pending": []}}})
    st.commit()
    st.close()
    c = CB.Combo(_Data(db))
    d = c.rules({"kind": "tf", "s": "S1_EMA_RSI_CHOP", "lo": "1h", "hi": "4h"}, now=now)
    assert d["busy_passed"] == 1                                              # only T + 1h (old count: 3)
    assert {r["id"]: r for r in d["rows"]}["rule"]["trades"] == 1


def test_held_reads_the_open_position_and_the_pending_signals(tmp_path):
    db = str(tmp_path / "held.db")
    start = _start()
    st = blank(db, start, [(A, "strategy"), (A4, "strategy")])
    st.put_state("accounts", start, {"engines": {
        A: {"position": {"symbol": "ETHUSDT", "entry_time": start + 5 * H + M, "signal": {"meta": {}}},
            "pending": [{"symbol": "BTCUSDT", "ts": start + 7 * H - 1}]},
        A4: {"position": None, "pending": []}, "F1_RSI_DIV@1h": {"position": {"symbol": "SOLUSDT", "entry_time": 1}}}})
    st.commit()
    st.close()
    book = CB.Combo(_Data(db)).book
    assert sorted(book.held([A, A4])) == [("BTCUSDT", start + 7 * H, start + 7 * H),
                                         ("ETHUSDT", start + 4 * H + M, start + 5 * H + M)]
    assert book.held(["NOPE@1h"]) == []


def test_pairs_table_marks_extra_accounts_and_progress_is_the_closest_pair(tmp_path):
    db = str(tmp_path / "w.db")
    info = build(db, days=3, strategies=["S1_EMA_RSI_CHOP", "S2_ST_ROC", "S3_CMO_SANDWICH"], ds_defs=1)
    c = CB.Combo(_Data(db))
    c.book.refresh()
    snap = CB.overlap_snapshot(c.book)
    assert snap["ready"] and snap["pair_trades"] <= snap["max_trades"] and snap["pair_days"] <= 7.0 + 1e-9
    # by hand: the closest pair's smaller trade count among the non-excluded (not coin-flip) accounts
    from paperbot import overlap as OV
    with c.book._conn() as conn:
        w = OV.load_window(conn, days=7)
    tr = [int(w.trades[j]) for j in range(len(w.ids)) if not w.excluded()[j]]
    best = max(min(tr[i], tr[j]) for i in range(len(tr)) for j in range(i + 1, len(tr)))
    assert snap["pair_trades"] == best
    fake = {**snap, "top": [{"a": "S1_EMA_RSI_CHOP@1h", "b": "S2_ST_ROC@1h", "corr": 0.9},
                            {"a": "S1_EMA_RSI_CHOP@1h", "b": "NEWLAB_X@1h", "corr": 0.8}]}
    m = CB.corr_map(c.book, "strategy", None, "day", info["now"], fake)
    assert [p["pickable"] for p in m["overlap"]["top"]] == [True, False]
    assert m["overlap"]["pair_trades"] == best and "F1_RSI_DIV" not in json.dumps(m)


def test_the_day_going_on_is_named_and_in_sample_weights_say_so(tmp_path):
    db = str(tmp_path / "w2.db")
    info = build(db, days=2.5, strategies=["S1_EMA_RSI_CHOP", "S2_ST_ROC", "S3_CMO_SANDWICH"], ds_defs=1)
    c = CB.Combo(_Data(db))
    d = c.combo("S1_EMA_RSI_CHOP,S2_ST_ROC@1h", "eq", None, now=info["now"])
    s = d["stats"]
    assert s["partial_last"] is True and s["partial_day"] == CB.K.kst_day(info["now"])
    assert d["method"]["in_sample"] is False and d["method"]["in_sample_ko"] is None
    assert d["curve"]["thinned"] is (d["curve"]["points"] > CB.CURVE_POINTS)
    iv = c.combo("S1_EMA_RSI_CHOP,S2_ST_ROC@1h", "invvol", None, now=info["now"])
    assert iv["method"]["used"] == "invvol" and iv["method"]["in_sample"] is True and "처음부터" in iv["method"]["in_sample_ko"]
    rp = c.combo("S1_EMA_RSI_CHOP,S2_ST_ROC@1h,S3_CMO_SANDWICH", "rp", None, now=info["now"])
    assert rp["method"]["used"] in ("rp", "invvol") and rp["method"]["in_sample"] is True
    # the weights still add up and the members' contributions still add up to the combined P&L
    assert sum(u["weight"] for u in rp["units"]) == pytest.approx(1.0, abs=1e-3)
    assert sum(u["pnl"] for u in rp["units"]) == pytest.approx(rp["stats"]["pnl"], abs=0.05)


def test_page_wiring_of_the_review_fixes():
    build_js = _read(V4, "screens", "combo-build.js")
    assert 'd.basis === "mark" ? "비중 반영 · 열린 포지션은 지금 시세로 평가" : "비중 반영 · 닫힌 거래만"' in build_js
    assert 'ui.assume("closed", d.basis === "mark"' in build_js
    assert "S.partial_day && wd.day === S.partial_day" in build_js and "d.method.in_sample_ko" in build_js
    assert 'st.corr == null && b === "hour"' in build_js and 'local.get("combo-corrbasis", null)' in build_js
    assert "st.hidden.clear()" in build_js and "지금보다" in build_js
    assert 'st.fromSyn = q.from === "synergy"' in build_js and "하루 마감·닫힌 거래 기준" in build_js
    # the chart keeps chartOptions' Korea-time axis: no timeScale of its own (it would replace kstTick: UTC labels)
    i = build_js.index("await makeChart(box,")
    assert "timeScale" not in build_js[i:build_js.index("});", i)] and "cv.thinned" in build_js
    main = _read(V4, "screens", "combo.js")
    assert 'tab === "build" || tab === "y5" ? pickQuery() : {}' in main
    mp = _read(V4, "screens", "combo-map.js")
    assert "p.pickable === false" in mp and "ov.pair_trades" in mp and "둘 중 적은 쪽" in mp
    rules = _read(V4, "screens", "combo-rules.js")
    assert "d.flip_money_ko" in rules and "r.pnl == null" in rules
