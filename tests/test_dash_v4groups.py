"""Paper v4 groups on the dashboard (P10 must subset): every /api/board row carries its group, DeepSeek family and exit
rule; the run shape is counted from the accounts table; the DeepSeek coin-flip comparison is reference only ("참고");
the DeepSeek P&L shows only in its own group view (owners' D11); the reel's position shows its band target and swing
stop instead of ladder lines; today's summary per group; the v4 rules banner (RULES_V4_KO); the group switch
(default: the 36 + the 5m reel + the extras); the 36's analyses (overlap, breakdown, risk) leave the other groups out."""

import json
import os
import re
import sqlite3
import sys
import time

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import paperbot.dash.app as A  # noqa: E402
from paperbot.config import (V3_JUDGED_TFS, V3_TRADE_TFS, V4_ACCOUNTS, V4_GROUP_ACCOUNTS, V4_GROUP_JUDGED,  # noqa: E402
                             V4_JUDGED_ACCOUNTS, v4_account_defs)
from paperbot.dash.app import Data, create_app, hash_password  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_dash import SECRET, _node, _static  # noqa: E402

PW = "correct horse battery"
NOW = int(time.time() * 1000)


def _pos(stop, tp, end=None, symbol="BTCUSDT"):
    """An open position as engine_state saves it (dataclasses.asdict(Position))."""
    meta = {"ref_price": 100.0}
    if end is not None:
        meta["reel_exit"] = {"closes": [100.0] * 19, "bucket": 0, "last": None, "end": end}
    sig = {"ts": NOW - 300_000, "symbol": symbol, "timeframe": "5m", "strategy_id": "X", "side": 1, "stop_price": stop,
           "tier": "normal", "tp_price": tp, "atr": 0.2, "meta": meta}
    return {"signal": sig, "symbol": symbol, "side": 1, "qty": 1.0, "entry_price": 100.0, "entry_time": NOW - 240_000,
            "leverage": 30, "tier": "normal", "margin": 1500.0, "margin_initial": 1500.0, "stop_price": stop,
            "tp_price": tp, "liq_price": 70.0, "entry_fee": 0.05, "funding_paid": 0.0, "mae_price": 0.0,
            "mfe_price": 0.0, "stop_initial": stop, "lock_roe": None}


def _trade(store, aid, pnl, tf="15m", reason="SL", exit_time=None):
    t = {"strategy_id": aid.split("@")[0], "timeframe": tf, "symbol": "BTCUSDT", "side": 1, "qty": 1.0, "leverage": 30,
         "entry_price": 100.0, "exit_price": 100.0 + pnl, "entry_time": NOW - 120_000, "exit_time": exit_time or NOW - 60_000,
         "exit_reason": reason, "roe": pnl / 1500, "pnl": pnl, "fees": 0.1, "funding": 0.0, "equity_after": 5000 + pnl,
         "signal_ts": NOW - 130_000, "stop_initial": 99.0, "best_roe": 0.0, "meta": {}}
    store.conn.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, "
                       "equity_after, data) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (aid, "BTCUSDT", t["entry_time"], t["exit_time"], reason, 30, pnl, t["roe"], t["equity_after"],
                        json.dumps(t)))


def _world(path, trades=True):
    """One account of each v4 group (the 36, a 15m coin flip, DeepSeek F9_FVG, the reel, a 5m coin flip with the
    reel's exits, a copy), their wallets, an open reel position and an open house position."""
    store = Store3(path)
    t0 = NOW - 3_600_000
    store.add_account("A@15m", "A", "15m", "strategy", t0, "paper-v4", None, {"group": "core", "family": None, "exits": "house"})
    store.add_account("RANDOM_1@15m", "RANDOM_1", "15m", "random", t0, "paper-v4", None, {"group": "flip", "exits": "house"})
    store.add_account("F9_FVG@15m", "F9_FVG", "15m", "ds200", t0, "paper-v4", None, {"group": "ds200", "family": "F9", "exits": "house"})
    store.add_account("REEL_H1@5m", "REEL_H1", "5m", "reel", t0, "paper-v4", None, {"group": "reel", "family": None, "exits": "reel"})
    store.add_account("RANDOM_1@5m", "RANDOM_1", "5m", "random", t0, "paper-v4", None, {"group": "flip", "exits": "reel"})
    store.add_account("A@15m~c1", "A", "15m", "copy", t0, "paper-v4", "A@15m",
                      {"v": 1, "kind": "copy", "label_ko": "복제 c1", "rule": {"template": "stop_atr", "k": 2.5}})
    w = {"A@15m": 5100.0, "RANDOM_1@15m": 5050.0, "F9_FVG@15m": 5200.0, "REEL_H1@5m": 5300.0, "RANDOM_1@5m": 5250.0,
         "A@15m~c1": 9000.0}
    eng = {aid: {"wallet": x, "bust": False, "max_drawdown": 0.01, "position": None} for aid, x in w.items()}
    eng["REEL_H1@5m"]["position"] = _pos(98.0, 103.5, end=NOW + 8 * 3_600_000)
    eng["A@15m"]["position"] = _pos(99.0, float("nan"))
    store.put_state("accounts", NOW, {"last_ts": NOW, "engines": eng})
    if trades:
        for aid, pnl in (("A@15m", 10.0), ("REEL_H1@5m", 5.0), ("F9_FVG@15m", -40.0), ("RANDOM_1@15m", 7.0),
                         ("F9_FVG@15m", 30.0)):
            _trade(store, aid, pnl, tf=aid.split("@")[1])
    store.commit()
    return store


def _client(db):
    c = TestClient(create_app(db, hash_password(PW), SECRET, candles=lambda s, i, n: []))
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    return c


# ---------------------------------------------------------------- server
def test_board_rows_carry_the_group_family_exits_and_the_reference_mark(tmp_path):
    db = str(tmp_path / "p.db")
    _world(db).close()
    b = _client(db).get("/api/board").json()
    by = {a["account_id"]: a for a in b["accounts"]}
    assert {a: by[a]["group"] for a in by} == {"A@15m": "core", "RANDOM_1@15m": "flip", "F9_FVG@15m": "ds200",
                                               "REEL_H1@5m": "reel", "RANDOM_1@5m": "flip", "A@15m~c1": "extra"}
    assert by["F9_FVG@15m"]["family"] == "F9" and by["A@15m"]["family"] is None
    assert {a: by[a]["exits"] for a in by} == {"A@15m": "house", "RANDOM_1@15m": "house", "F9_FVG@15m": "house",
                                               "REEL_H1@5m": "reel", "RANDOM_1@5m": "reel", "A@15m~c1": "house"}
    assert by["F9_FVG@15m"]["name_ko"].startswith("딥시크 F9_FVG") and by["REEL_H1@5m"]["name_ko"].startswith("릴스")
    assert by["RANDOM_1@5m"]["name_ko"].startswith("동전 던지기 5분") and by["A@15m"]["name_ko"] is None
    # the coin-flip comparison per timeframe: the reel against the three 5m flips (its own exits), DeepSeek only 참고
    assert b["best_random"] == {"15m": 5050.0, "5m": 5250.0}
    assert by["REEL_H1@5m"]["beats_random"] is True and by["REEL_H1@5m"]["vs_random_ref"] is False
    assert by["F9_FVG@15m"]["beats_random"] is True and by["F9_FVG@15m"]["vs_random_ref"] is True
    assert by["A@15m~c1"]["beats_random"] is None and by["A@15m"]["vs_random_ref"] is False
    assert "data" not in by["A@15m"]                                      # the raw column never leaves the server
    # the reel's position: band target, swing stop and time exit, no ladder; a house position has no target
    rp, hp = by["REEL_H1@5m"]["position"], by["A@15m"]["position"]
    assert (rp["exits"], rp["stop"], rp["tp"], rp["time_exit"]) == ("reel", 98.0, 103.5, NOW + 8 * 3_600_000)
    assert (hp["exits"], hp["tp"], hp["time_exit"]) == ("house", None, None)
    assert b["names_ko"]["REEL_H1"].startswith("릴스") and len(b["names_ko"]) == 45 and b["group_ko"]["ds200"] == "딥시크"
    assert b["family_ko"]["F9"] and b["default_groups"] == ["core", "reel"]
    # counted from the accounts table
    sh = b["run_shape"]
    assert sh["source"] == "accounts_table" and sh["accounts"] == 5 and sh["all_accounts"] == 6
    assert sh["trade_tfs"] == ["5m", "15m"] and sh["core_tfs"] == ["15m"] and sh["strategy_accounts"] == 1
    assert {g: v["accounts"] for g, v in sh["groups"].items()} == {"core": 1, "ds200": 1, "reel": 1, "flip": 2, "extra": 1}
    assert sh["judged"] == 3 and sh["judged_by_group"] == {"core": ["15m", "30m", "1h"], "ds200": ["15m", "30m", "1h"],
                                                           "reel": ["5m"]}
    a = _client(db).get("/api/account/REEL_H1@5m").json()
    assert a["account"]["exits"] == "reel" and a["account"]["group"] == "reel"
    assert a["state"]["position"]["tp_price"] == 103.5
    assert _client(db).get("/api/account/A@15m").json()["state"]["position"]["tp_price"] is None   # NaN -> null


def test_run_shape_of_a_full_v4_world_and_of_an_empty_database(tmp_path):
    db = str(tmp_path / "p.db")
    store = Store3(db)
    for d in v4_account_defs([f"S{k}" for k in range(36)]):
        store.add_account(f"{d['strategy']}@{d['timeframe']}", d["strategy"], d["timeframe"], d["kind"], 0, "paper-v4",
                          None, d["data"])
    store.commit()
    store.close()
    c = sqlite3.connect(db)
    sh = A.run_shape(c)
    assert sh["accounts"] == V4_ACCOUNTS == 331 and sh["judged"] == V4_JUDGED_ACCOUNTS == 241
    assert {g: v["accounts"] for g, v in sh["groups"].items()} == V4_GROUP_ACCOUNTS
    assert {g: v["judged"] for g, v in sh["groups"].items()} == V4_GROUP_JUDGED
    assert sh["trade_tfs"] == ["5m"] + list(V3_TRADE_TFS) and sh["core_tfs"] == list(V3_TRADE_TFS)
    assert sh["strategy_accounts"] == 144 and sh["q1_family"] == 108 and sh["judged_tfs"] == list(V3_JUDGED_TFS)
    assert sh["groups"]["reel"]["tfs"] == {"5m": 1} and sh["groups"]["flip"]["tfs"]["5m"] == 3
    assert "5m" not in sh["groups"]["core"]["tfs"] and "5m" not in sh["groups"]["ds200"]["tfs"]
    assert list(sh["groups"]) == ["core", "ds200", "reel", "flip"]
    empty = str(tmp_path / "e.db")
    Store3(empty).close()
    e = A.run_shape(sqlite3.connect(empty))
    assert e["source"] == "config" and e["accounts"] == 331 and e["judged"] == 241 and e["strategy_accounts"] == 144
    # 331 rows reach the page with their groups (no engine state yet: the starting wallet)
    b = Data(db).board()
    assert len(b["accounts"]) == 331 and sum(a["group"] == "ds200" for a in b["accounts"]) == 171
    assert sum(a["exits"] == "reel" for a in b["accounts"]) == 4


def test_today_summary_per_group_keeps_the_deepseek_pnl_in_its_own_group(tmp_path):
    db = str(tmp_path / "p.db")
    _world(db).close()
    t = Data(db).summary(NOW)["today"]
    by = t["by_group"]
    assert set(by) == {"core", "ds200", "reel", "flip", "extra"}
    assert (by["core"]["trades"], by["core"]["pnl"], by["core"]["wins"]) == (1, 10.0, 1)
    assert (by["ds200"]["trades"], by["ds200"]["pnl"], by["ds200"]["wins"]) == (2, -10.0, 1)
    assert by["reel"]["pnl"] == 5.0 and by["flip"]["pnl"] == 7.0 and by["extra"]["trades"] == 0
    # the home lists: the 36, the reel and the extras only (DeepSeek in its own group, the coin flips are the yardstick)
    assert [x["account_id"] for x in t["best"]] == ["A@15m", "REEL_H1@5m"] and t["worst"] == []
    assert [x["account_id"] for x in by["ds200"]["worst"]] == ["F9_FVG@15m"] or by["ds200"]["pnl"] < 0
    assert t["pnl"] == 10.0 and t["strategy_trades"] == 1 and t["trades"] == 5     # the 36's tile as before


def test_the_v4_rules_banner_and_its_documents(tmp_path, monkeypatch):
    assert A.RULES_V4_KO.startswith("기존 36 · 딥시크 44 · 5분봉 단타 1") and A.RULES_V4_LABEL == "v4 규칙"
    assert "5분봉 제외" not in A.RULES_V4_KO and "보통 30/20배" in A.RULES_V4_KO and "8초" in A.RULES_V4_KO
    monkeypatch.setattr(A, "DOCS_DIR", str(tmp_path))
    b = A.restart_banner(NOW, NOW)
    assert b["rules_ko"] == A.RULES_V4_KO and b["rules_label"] == "v4 규칙"
    assert b["doc"] == "/api/doc/rules-change-1" and b["levrule_doc"] == "/api/doc/levrule-eval"   # v4 docs not there yet
    for fn in ("paper-v4-rules.md", "paper-v4-verdict.md", "levrule-eval-v4.md"):
        (tmp_path / fn).write_text("# v4\n", encoding="utf-8")
    b = A.restart_banner(NOW, NOW)
    assert (b["doc"], b["verdict_doc"], b["levrule_doc"]) == ("/api/doc/rules-v4", "/api/doc/verdict-v4",
                                                              "/api/doc/levrule-eval-v4")
    db = str(tmp_path / "p.db")
    _world(db, trades=False).close()
    c = _client(db)
    assert c.get("/api/doc/rules-v4").text == "# v4\n"
    s = c.get("/api/summary").json()["restart"]
    assert s["rules_ko"] == A.RULES_V4_KO and s["doc"] == "/api/doc/rules-v4"
    assert 'rs.rules_label' in _static("summary.js") and "규칙 변경 1:" not in _static("summary.js")


def test_strategy_views_take_each_groups_own_timeframes(tmp_path):
    db = str(tmp_path / "p.db")
    _world(db, trades=False).close()
    c = _client(db)
    assert c.get("/api/strategy/V45_AMB", params={"tf": "5m"}).status_code == 400       # the 36 never trade 5m
    assert c.get("/api/strategy/F15_ASIA_BRK", params={"tf": "4h"}).status_code == 400  # session definitions: no 4h
    assert c.get("/api/strategy/REEL_H1", params={"tf": "15m"}).status_code == 400
    assert c.get("/api/strategy/REEL_H1", params={"tf": "5m"}).status_code != 400
    assert A.strategy_tfs("F9_FVG") == tuple(V3_TRADE_TFS) and A.strategy_tfs("REEL_H1") == ("5m",)
    assert c.get("/api/levels", params={"tf": "5m"}).json()["levels"] == []           # S/R stays on the 36's timeframes


def test_status_sends_the_signal_limits_of_the_signal_service(tmp_path):
    import inspect

    from paperbot import sigservice
    from paperbot.config import FIVE_M_MAX_DELAY_MS
    p = inspect.signature(sigservice.SignalService.__init__).parameters
    assert A.SIGNAL_LIMITS == {"max_delay_ms": p["max_delay_ms"].default, "max_delay_ms_5m": FIVE_M_MAX_DELAY_MS,
                               "timeout_s": p["timeout_s"].default}
    db = str(tmp_path / "p.db")
    _world(db, trades=False).close()
    assert _client(db).get("/api/status").json()["limits"] == A.SIGNAL_LIMITS


def test_trades_and_csv_by_group(tmp_path):
    db = str(tmp_path / "p.db")
    _world(db).close()
    c = _client(db)
    ids = lambda g: sorted({t["account_id"] for t in c.get("/api/trades", params={"group": g}).json()})  # noqa: E731
    assert ids("main") == ["A@15m", "REEL_H1@5m"] and ids("ds200") == ["F9_FVG@15m"]
    assert ids("flip") == ["RANDOM_1@15m"] and ids("core") == ["A@15m"] and ids("reel") == ["REEL_H1@5m"]
    assert len(c.get("/api/trades").json()) == 5                                          # no group: every trade
    assert {t["group"] for t in c.get("/api/trades").json()} == {"core", "reel", "ds200", "flip"}
    rows = list(__import__("csv").reader(c.get("/api/export/board.csv").text.lstrip("﻿").splitlines()))
    assert rows[0][-3:] == ["그룹", "딥시크 계열", "청산 방식"]
    by = {r[0]: r for r in rows[1:]}
    assert by["F9_FVG@15m"][-3:] == ["ds200", "F9", "house"] and by["F9_FVG@15m"][10] == "참고 True"
    assert by["REEL_H1@5m"][-3:] == ["reel", "", "reel"] and by["REEL_H1@5m"][10] == "True"


def test_the_36s_analyses_leave_the_other_groups_out(tmp_path):
    """overlap (계좌 겹침), breakdown (코인별 성적) and the risk view's coin flips: the 36, their flips and the extras only
    (171 DeepSeek accounts would make the groups theirs; the 5m flips run the reel's exits)."""
    from paperbot import breakdown, overlap
    db = str(tmp_path / "p.db")
    store = _world(db)
    for aid in ("A@15m", "RANDOM_1@15m", "F9_FVG@15m", "REEL_H1@5m", "RANDOM_1@5m", "A@15m~c1"):
        for k in range(3):
            store.conn.execute("INSERT INTO equity VALUES (?,?,?,?)", (aid, NOW - NOW % 300_000 - k * 300_000, 5000.0, 0.0))
    _trade(store, "RANDOM_1@5m", 3.0, tf="5m")
    store.commit()
    store.close()
    c = sqlite3.connect(db)
    w = overlap.load_window(c, days=1)
    assert sorted(w.ids) == ["A@15m", "A@15m~c1", "RANDOM_1@15m"]
    assert sorted({r["account_id"] for r in breakdown.load_trades(c)}) == ["A@15m", "RANDOM_1@15m"]
    # the 36's coin-flip yardstick (G21): the map view's flips and the risk view's flips leave the 5m flips out
    from paperbot.dash import analysis as AN
    data = A.Data(db)
    flips = AN._cards(data, "random", tfs=AN.CORE_FLIP_TFS)
    assert flips and {x["timeframe"] for x in flips} <= set(AN.CORE_FLIP_TFS)
    assert any(x["timeframe"] == "5m" for x in AN._cards(data, "random"))   # (they are in the database)
    src = open(os.path.join(os.path.dirname(A.__file__), "analysis.py"), encoding="utf-8").read()
    assert 'kinds=("random",), round_trip=rt) if tf != "5m"]' in src


# ---------------------------------------------------------------- page (node)
def _parts(src, consts=(), funcs=()):
    out = [re.search(r"^const %s = .*?;[ \t]*(?://[^\n]*)?$" % n, src, re.S | re.M).group(0) for n in consts]
    out += [re.search(r"^function %s\(.*?^}$" % n, src, re.S | re.M).group(0) for n in funcs]
    return "\n".join(out)


def test_the_group_switch_views_default_to_the_36_the_reel_and_the_extras():
    src = _static("app.js")
    out = json.loads(_node("const state = {group: 'main'};\n" + _parts(src, ("GROUP_VIEWS", "KIND_GROUP", "groupOf"), ("inView",)) + """
const accts = [{kind: "strategy", timeframe: "15m"}, {kind: "ds200", group: "ds200", timeframe: "15m"},
  {kind: "reel", group: "reel", timeframe: "5m"}, {kind: "random", timeframe: "5m"}, {kind: "random", timeframe: "15m"},
  {kind: "copy", timeframe: "15m"}, {kind: "newlab", timeframe: "1h"}, {kind: "mystery", timeframe: "15m"}];
console.log(JSON.stringify(GROUP_VIEWS.map(([v]) => [v, accts.map((a) => inView(a, v) ? 1 : 0).join("")])));"""))
    assert dict(out) == {"main": "10100110", "core": "10000000", "ds200": "01000000", "reel": "00110000",
                         "flip": "00011000", "extra": "00000110"}
    assert ': "main",' in re.search(r"^const state = \{.*?^\};", src, re.S | re.M).group(0)       # the default view
    assert "const positions = () => (state.board ? state.board.accounts.filter((a) => a.position && inView(a)) : []);" in src
    assert "&group=${state.group}" in src and "&group=${state.group}" in _static("pos.js")


def test_group_cards_show_the_deepseek_pnl_only_in_its_own_view():
    src = _static("app.js")
    js = ("const state = {group: 'main'}; let INITIAL = 5000;\n"
          + _parts(src, ("fmt", "pct", "cls", "KIND_GROUP", "groupOf", "REF_NOTE", "CARD_GROUPS"), ("median", "groupStats", "groupCards")) + """
const acc = (id, kind, tf, wallet, extra) => Object.assign({account_id: id, kind, timeframe: tf, wallet, trades: 3, position: null, bust: false,
  beats_random: wallet > 5050}, extra || {});
const all = [acc("A@15m", "strategy", "15m", 5100), acc("F9@15m", "ds200", "15m", 5432.1, {group: "ds200"}),
  acc("REEL_H1@5m", "reel", "5m", 5300, {group: "reel"}), acc("RANDOM_1@5m", "random", "5m", 5250), acc("RANDOM_1@15m", "random", "15m", 5050)];
const cards = (g) => { state.group = g; return groupCards(all).split("</button>").filter((x) => x.trim()); };
console.log(JSON.stringify([cards("main"), cards("ds200")]));""")
    main, ds = json.loads(_node(js))
    assert len(main) == 4 and "추가 계좌" not in "".join(main)                   # no extra account: no card
    dsm = next(c for c in main if "딥시크 44" in c)
    assert "5,432" not in dsm and "$" not in dsm and "손익은 눌러서" in dsm and "gcard on" not in dsm
    dss = next(c for c in ds if "딥시크 44" in c)
    assert "5,432" in dss and "(참고)" in dss and "gcard on" in dss
    reel = next(c for c in main if "5분봉" in c)
    assert "5,300" in reel and "5분 동전 봇 1개 최고 $5,250" in reel and "gcard on" in reel


def test_the_reel_position_shows_its_band_target_and_swing_stop_not_a_ladder():
    pos = _static("pos.js")
    app = _static("app.js")
    js = ("const fmt = (x, d = 2) => Number(x).toFixed(d); const cls = () => ''; const tsKo = (ms) => 'T' + ms;\n"
          + _parts(app, ("pxd", "px")) + "\n" + _parts(pos, ("LOCK",), ("usdt", "lockText")) + """
const reel = {exits: "reel", side: 1, qty: 2, entry: 100, stop: 98, tp: 103.5, time_exit: 42, lock_roe: null};
const house = {exits: "house", side: 1, qty: 2, entry: 100, stop: 98, tp: null, lock_roe: null};
console.log(JSON.stringify([lockText(reel, null), lockText(house, null)]));""")
    r, h = json.loads(_node(js))
    assert "익절 목표 103.50" in r and "+7.00" in r and "시간 청산 T42" in r and "사다리 없음" in r and "잠금" not in r
    assert "잠금 시작" in h
    # the trade chart and the account chart draw the stop and the target (no lock line) for the reel's exits
    assert app.count('title: "익절 목표(볼린저 윗선)"') == 2 and app.count('"손절(스윙 저점)"') == 2
    assert 'if (p.exits === "reel")' in app and 'd.account.exits === "reel"' in app
    assert 'row("익절 목표 · 볼린저 윗선 (지정가, 5분마다 바뀜)"' in pos
    assert 'TIME: "시간 청산"' in app


def test_todays_summary_follows_the_group_switch():
    app = _static("app.js")
    js = ("const els = {}; const $ = (id) => (els[id] = els[id] || {textContent: '', innerHTML: ''});\n"
          "const listeners = {}; const document = {querySelectorAll: () => [], addEventListener: (n, f) => { listeners[n] = f; }};\n"
          "const setInterval = () => 0; const fmt = (x, d) => Number(x).toFixed(d); const esc = (s) => String(s);\n"
          "const idName = (id) => id; const RUN = {strategy_accounts: 144}; const state = {group: 'main'};\n"
          + _parts(app, ("KIND_GROUP", "groupOf", "GROUP_ROW_KO"), ("inView",)) + """
const g = (trades, pnl, best) => ({trades, pnl, wins: pnl > 0 ? trades : 0, liquidations: 0, best: best || [], worst: []});
const v = {start: null, now: 0, today: {since: 0, trades: 9, pnl: 10, wins: 1, strategy_trades: 1, liquidations: 2,
  best: [{account_id: "A@15m", pnl: 10}], worst: [],
  by_group: {core: g(1, 10), ds200: g(4, -40, [{account_id: "F9@15m", pnl: 3}]), reel: g(1, 5), flip: g(3, 7), extra: g(0, 0)}}};
const api = async () => v;
""" + _static("summary.js") + """
setTimeout(() => { const main = els["today-tiles"].innerHTML + els["today-list"].innerHTML;
  state.group = "ds200"; listeners["pb-group"](); const ds = els["today-tiles"].innerHTML + els["today-list"].innerHTML;
  console.log(JSON.stringify([main, ds])); }, 20);""")
    main, ds = json.loads(_node(js))
    assert "+$15" in main and "-$40" not in main and "딥시크 4건" in main and "F9@15m" not in main
    assert "-$40" in ds and "F9@15m" in ds and "+$15" not in ds
