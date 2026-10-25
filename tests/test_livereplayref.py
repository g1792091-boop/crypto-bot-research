"""실거래 › 재현 비교 (#/expect: the 추세판단 봇's 7/1~10/20 replay against its live record; GET /api/v4/livebots/replayref,
dash/more/livereplayref.py; screens/livebots-expect.js, livebots-expect.css).

- the reference file as committed: its trade list gives the file's own record (n, win rate, mean / median net ROE, the
  exits by reason with their median hold), the costs add up (before - slippage - fees = net), the key sentence;
- the bands: the entries band is the exact convolution of the replay's weekday histogram (checked against brute force;
  a partial weekday thinned to its fraction), the net ROE bands come from fixed-seed walks (deterministic, the first n
  steps independent of the length), the verdict words never say more than 표본 적음 under 20 trades;
- the answer on a fake world (a paper database in the trend bot's tables, two executor databases with their configs):
  entries a weekday and on the weekend, the funnel stages from livereview's funnel, the results with the exits (an
  executor's close that followed the paper takes the paper trade's reason), the costs from the paper's own records and
  from the executors' fills (an estimated or unmeasured trade left out of the costs, said so), the split, the curve;
- the paper's costs on the trend bot's own engine records (tests/test_livereview.py's world): before costs equals the
  price move at the leverage, the fees are the ones it booked;
- honest states: no file = missing, garbage = error, another bot = off, no start yet = missing, no reference = missing;
- the view in node (the tiny DOM): every block and its words, nothing printed as null / NaN, the states, the helpers;
- static checks (node --check, tokens only, the lex- prefix is this screen's alone) and the wiring (tab, menu, find,
  css, module, docs)."""
from __future__ import annotations

import itertools
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

from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import livereplayref as X  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
JS = os.path.join(SCREENS, "livebots-expect.js")
CSS = os.path.join(SCREENS, "livebots-expect.css")
REF = os.path.join(ROOT, "data", "trend_replay_0701_1020.json")
MIN, HOUR, DAY = 60_000, 3_600_000, 86_400_000
KST0 = 1_792_508_400_000                  # 2026-10-21 00:00 KST (a Wednesday): the replay's window ends here
SINCE = KST0 + 21 * HOUR                  # the trend bot's start: Wednesday 21:00 KST
NOW = SINCE + 5 * DAY                     # Monday 21:00 KST: Wed 3 h + Thu + Fri + (Sat, Sun) + Mon 21 h = 3 weekdays
SLIP, FEE = 0.0002, 0.0005
ACC, FLIP = L.ACCOUNT, L.FLIP_ACCOUNT


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


def _ref():
    with open(REF, encoding="utf-8") as fh:
        return json.load(fh)


# ================================================================ the reference file
def test_the_reference_file_gives_its_own_numbers():
    d = _ref()
    got = X.load_ref(REF)
    assert got["state"] == "ok" and got["d"]["trades"]["n"] == 89
    assert X.load_ref(REF) is got                          # read once per change of the file
    rows = X.replay_rows(d)
    rec = X.record(rows)
    tr = d["trades"]
    assert rec["n"] == tr["n"] == 89 and rec["win_rate"] == pytest.approx(tr["win_rate"], abs=5e-4)
    assert rec["roe_mean"] == pytest.approx(tr["roe_mean"], abs=5e-5) and rec["roe_median"] == pytest.approx(tr["roe_median"], abs=5e-5)
    assert rec["hold_med"] == tr["hold_min_median"]
    by = {x["id"]: x for x in rec["exits"]}
    assert [x["id"] for x in rec["exits"]] == ["LOCK", "TIME", "SL", "REV"] and "JUDGE" not in by and tr["judge_exits"] == 0
    for k, v in tr["by_reason"].items():
        assert by[k]["n"] == v["n"] and by[k]["roe_mean"] == pytest.approx(v["roe_mean"], abs=5e-5), k
        assert by[k]["hold_med"] == v["hold_min_median"], k
    # the costs add up, and the key sentence comes from them
    c = X.replay_costs(d)
    assert c["before"] - c["slip"] - c["fee"] == pytest.approx(c["net"], abs=1e-4) and c["funding"] is None
    assert c["cost"] == pytest.approx(0.0448)
    assert X.costs_ko(c) == "재현에서는 수수료·미끄러짐 전엔 거의 본전(거래당 −0.4%)이었고, 비용이 거래당 4.5%p를 가져갔어요."
    assert X.costs_ko({"before": 0.02, "cost": 0.03}).startswith("재현에서는 수수료·미끄러짐 전엔 거래당 +2.0%를 벌었고")
    assert X.costs_ko({"before": -0.03, "cost": 0.03}).startswith("재현에서는 수수료·미끄러짐 전에도 거래당 −3.0%였고")
    # the entries: 80 weekdays, 89 entries, none on the weekend
    e = d["entries"]
    assert sum(e["hist_weekdays"].values()) == 80 and sum(int(k) * v for k, v in e["hist_weekdays"].items()) == 89
    assert e["weekend_entries"] == 0
    # the funnel adds up stage by stage
    f = d["funnel"]
    assert f["signals"] - sum(f["blocked_at_signal"].values()) == f["after_time_rules"]
    assert f["after_time_rules"] - sum(f["check_failed"].values()) == f["passed_check"]
    assert f["passed_check"] - f["no_pullback"] == f["pullback_touched"]
    assert f["pullback_touched"] - f["skipped_in_position"] - f["skipped_lower_score"] == f["entered"] == 89
    assert set(f["blocked_at_signal"]) | set(f["check_failed"]) <= set(X.REF_BLOCK)


def test_the_reference_file_states(tmp_path):
    assert X.load_ref(tmp_path / "none.json")["state"] == "missing"
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    got = X.load_ref(bad)
    assert got["state"] == "error" and got["reason_ko"] == X.REF_BAD_KO and got["reason"]
    bad.write_text(json.dumps({"what": "x"}), encoding="utf-8")
    assert "missing keys" in X.load_ref(bad)["reason"]


# ================================================================ the bands
def test_the_entries_band_is_the_exact_convolution():
    hist = _ref()["entries"]["hist_weekdays"]
    p = X.day_pmf(hist)
    assert len(p) == 6 and p[4] == 0 and sum(p) == pytest.approx(1.0) and p[0] == pytest.approx(27 / 80)
    assert X.thin(p, 1.0) == p
    assert X.thin(p, 0.0) == pytest.approx([1, 0, 0, 0, 0, 0])
    half = X.thin(p, 0.5)
    assert sum(half) == pytest.approx(1.0)
    assert sum(k * x for k, x in enumerate(half)) == pytest.approx(0.5 * sum(k * x for k, x in enumerate(p)))
    # two whole weekdays against brute force
    brute: dict = {}
    for a, b in itertools.product(range(6), repeat=2):
        brute[a + b] = brute.get(a + b, 0.0) + p[a] * p[b]
    conv = X.conv(p, p)
    assert conv == pytest.approx([brute.get(k, 0.0) for k in range(len(conv))])
    b2 = X.entries_band(hist, [1.0, 1.0])
    cdf = list(itertools.accumulate(brute.get(k, 0.0) for k in range(11)))
    assert b2["lo"] == next(k for k, c in enumerate(cdf) if c >= 0.05) and b2["hi"] == next(k for k, c in enumerate(cdf) if c >= 0.95)
    assert X.entries_band(hist, [1.0]) == {"lo": 0, "hi": 3, "mean": pytest.approx(1.1125), "days": 1.0}
    # the replay's own 80 weekdays: 89 entries inside, the mean is the replay's
    b80 = X.entries_band(hist, [1.0] * 80)
    assert b80["lo"] < 89 < b80["hi"] and b80["mean"] == pytest.approx(89.0) and X.where_in(89, b80["lo"], b80["hi"]) == "inside"
    assert X.entries_band(hist, []) is None
    # the band grows with the days; a partial day counts as its fraction
    assert X.entries_band(hist, [1.0] * 10)["hi"] < X.entries_band(hist, [1.0] * 20)["hi"]
    assert X.entries_band(hist, [0.25, 1.0])["mean"] == pytest.approx(1.25 * 1.1125)
    assert X.where_in(5, 0, 3) == "above" and X.where_in(0, 1, 3) == "below" and X.where_in(None, 0, 1) is None


def test_the_weekdays_in_korea_time():
    fr = X.weekday_fracs(SINCE, NOW)
    assert [round(f, 4) for _d, f in fr] == [0.125, 1.0, 1.0, 0.875]
    assert [d for d, _f in fr] == [KST0 + k * DAY for k in (0, 1, 2, 5)]                  # KST midnights (UTC ms): Wed Thu Fri Mon
    assert X.weekday_fracs(NOW, SINCE) == []


def test_the_walks_are_deterministic_and_the_verdicts_never_overclaim():
    vals = tuple(r["roe"] for r in X.replay_rows(_ref()))
    w = X.walks(vals, 89)
    assert w["k_max"] == 100 and len(w["lo"]) == 101 and w["lo"][0] == w["hi"][0] == 0.0
    X._walks.clear()
    assert X.walks(vals, 89) == w                          # the same seed, the same band
    longer = X.walks(vals, 140)
    assert longer["k_max"] == 150 and longer["lo"][:101] == w["lo"] and longer["hi"][:101] == w["hi"]
    b20, b89 = X.mean_band(w, 20), X.mean_band(w, 89)
    mean = sum(vals) / len(vals)
    assert b89[0] < mean < b89[1] and b20[0] < b89[0] and b20[1] > b89[1]        # narrower with more trades
    assert X.mean_band(w, 0) is None and X.mean_band(w, 101) is None
    assert X.mean_band(w, 1) == [w["lo"][1], w["hi"][1]] and min(vals) <= w["lo"][1] < w["hi"][1] <= max(vals)
    # the words
    assert X.verdict(0, None, None)["kind"] == "none"
    v = X.verdict(5, 0.3, b20)
    assert v["kind"] == "small" and v["ko"] == "표본 적음 · 아직 판단 못 함 (거래 5번 · 20번부터 봐요)" and v["where"] == "above"
    assert X.verdict(25, mean, X.mean_band(w, 25))["kind"] == "inside"
    assert X.verdict(25, 0.2, X.mean_band(w, 25))["ko"].endswith("보통 범위보다 높아요")
    assert X.verdict(25, -0.5, X.mean_band(w, 25))["kind"] == "below"
    assert X.verdict(25, -0.04, None)["kind"] == "na"


# ================================================================ a fake world: the paper bot and both executors
def _paper_trade(conn, account, sym, side, et, xt, reason, e_raw, x_raw, strategy, tf, lev=30, margin=100.0, funding=0.0):
    """A closed trade as the engine books it (engine.py: fills with the slippage against, the taker fee both ways)."""
    fill = e_raw * (1 + side * SLIP)
    xfill = x_raw if reason == "LIQ" else x_raw * (1 - side * SLIP)
    qty = margin * lev / fill
    fees = qty * fill * FEE + qty * xfill * FEE
    pnl = side * qty * (xfill - fill) - fees - funding
    d = {"strategy_id": strategy, "symbol": sym, "timeframe": tf, "side": side, "entry_time": et, "entry_price": fill,
         "exit_time": xt, "exit_price": xfill, "exit_reason": reason, "qty": qty, "leverage": lev, "margin": margin, "fees": fees,
         "funding": funding, "pnl": pnl, "roe": pnl / margin, "context": {}}
    conn.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, data) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?)", (account, sym, et, xt, reason, lev, pnl, pnl / margin, 1000.0, json.dumps(d)))
    return d


# (coin, side, entry KST hours from Wed 00:00, hours held, reason, entry price, exit price, member, timeframe, leverage)
TRADES = (("BTCUSDT", 1, 24 + 10, 1, "LOCK", 60000.0, 60300.0, "F9_FVG", "1h", 40),
          ("ETHUSDT", -1, 24 + 15, 2, "TIME", 2500.0, 2502.0, "N20_EMA9_CHOP", "30m", 30),
          ("SOLUSDT", 1, 48 + 10, 1, "SL", 150.0, 147.5, "F9_IFVG", "1h", 30),
          ("DOGEUSDT", -1, 48 + 20, 1, "JUDGE", 0.2, 0.2001, "N20_EMA9_CHOP", "30m", 30),
          ("LTCUSDT", 1, 72 + 11, 3, "REV", 80.0, 80.1, "N08_ICHI_WR", "30m", 30),        # a Saturday entry
          ("BCHUSDT", -1, 120 + 10, 1, "LOCK", 400.0, 396.0, "F3_BOS", "30m", 30))
OPEN_AT = KST0 + (120 + 18) * HOUR                       # the open position's entry (Monday 18:00 KST)


def _signals(store):
    rows, k = [], itertools.count()

    def sig(t, status, why, sym="BTCUSDT"):
        rows.append({"bar_close": t + next(k) * MIN, "timeframe": "30m", "strategy": "F9_FVG@1h", "symbol": sym, "side": 1, "atr": 1.0,
                     "ref_price": 100.0, "ref_time": t, "delay_ms": 0, "status": status, "data": {"why": why}})
    t = SINCE + HOUR
    sig(SINCE - HOUR, "FILTERED", "1시간 추세가 하락이라 롱 안 함")                       # before the start: not counted
    for _ in range(3):
        sig(KST0 + 75 * HOUR, "FILTERED", "주말(한국 시간 토·일) 진입 안 함")
    for _ in range(2):
        sig(t, "FILTERED", "추격 진입 막기: 24시간 고점 쪽 10% 안")
    for _ in range(4):
        sig(t, "FILTERED", "1시간 추세가 상승이라 숏 안 함")
    sig(t, "FILTERED", "30분 RSI 71 과열")
    sig(t, "FILTERED", "되돌림 안 옴(10/22 10:29까지 2,496.25에 안 닿음)")
    for _ in range(8):
        sig(t, "BROKE", "되돌림 확인: 2,496.25 닿음")
    for _ in range(7):
        sig(t, "SUBMITTED", "되돌림 확인")                                            # the pulled entry's own row
    sig(t, "WAITING", "되돌림 기다림: 2,496.25까지(0.25 ATR, 10:29까지) · 상승 4/4")
    store.log_signals(rows)


def _paper_world(path):
    s = Store3(path)
    s.put_state("combo_run", SINCE - DAY, {"taker_fee": FEE, "config": {"name": "추세판단 봇", "trend": {"time_bars": 4},
                                                                     "members": [{"strategy": "F9_FVG", "tf": "1h"}]}})
    s.put_state("trend", NOW, {"since": SINCE})
    s.put_state("accounts", NOW, {"engines": {ACC: {"wallet": 990.0, "position": {"symbol": "ETHUSDT", "side": 1, "entry_time": OPEN_AT}}}})
    out = []
    for sym, side, hh, held, reason, e, x, strat, tf, lev in TRADES:
        et = KST0 + hh * HOUR
        out.append(_paper_trade(s.conn, ACC, sym, side, et, et + held * HOUR, reason, e, x, strat, tf, lev,
                                funding=0.05 if reason == "TIME" else 0.0))
        s.conn.execute("INSERT INTO outcomes (account_id, step_ts, status, reason, symbol, data) VALUES (?,?,?,?,?,?)",
                       (ACC, et, "ENTERED", "ok", sym, "{}"))
    _paper_trade(s.conn, ACC, "BTCUSDT", 1, SINCE - DAY, SINCE - DAY + HOUR, "SL", 60000.0, 59000.0, "F9_FVG", "1h")   # the bot before
    _paper_trade(s.conn, FLIP, "BTCUSDT", -1, KST0 + 34 * HOUR, KST0 + 35 * HOUR, "SL", 60000.0, 60300.0, "F9_FVG", "1h")
    for t, st in ((OPEN_AT, "ENTERED"), (KST0 + 49 * HOUR, "SKIPPED"), (SINCE - HOUR, "ENTERED")):
        s.conn.execute("INSERT INTO outcomes (account_id, step_ts, status, reason, symbol, data) VALUES (?,?,?,?,?,?)",
                       (ACC, t, st, "ok" if st == "ENTERED" else "in position", "ETHUSDT", "{}"))
    _signals(s)
    s.close()
    return out


def _exec_world(path, cfg_path, paper_path, exchange, mode, rows):
    """An executor's database (executor.py ExecStore) and its config. rows: (paper trade, entry gap s, reason words, pnl,
    costs or None (wallet estimate), cost ok)."""
    from paperbot.executor import ExecStore
    st = ExecStore(path, lock=False)
    st.put_state("bot", NOW, {"mode": mode, "risk": {"last_equity": 101.0}})
    for pt, gap, words, pnl, cost, ok in rows:
        key = f"{ACC}|{pt['symbol']}|{pt['entry_time']}"
        side, lev = pt["side"], pt["leverage"]
        entry = pt["entry_price"] * (1 + side * 0.0003)
        tr = {"key": key, "symbol": pt["symbol"], "side": side, "qty": 10.0 / entry * lev / 10, "leverage": lev,
              "entry_ts": pt["entry_time"] + gap * 1000, "entry_price": entry, "stop_initial": entry * (1 - side * 0.02),
              "mode": mode, "entry_time": pt["entry_time"], "paper_entry": pt["entry_price"],
              "stop": entry * (1 + side * 0.003) if "발동" in words else entry * (1 - side * 0.02)}
        st.trade_open(tr)
        st.trade_close(key, pt["exit_time"] + 2000, words, pnl, tr, "fills" if cost else "wallet")
        if cost:
            st.trade_costs(key, {"pnl": pnl, "realized": pnl + cost[0] - cost[2], "commission": cost[0], "slippage": cost[1],
                                 "funding": cost[2], "real_cost": cost[0] + cost[1], "assumed_cost": 0.01, "ok": ok})
    st.close()
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump({"account": ACC, "paper_db": paper_path, "db": path, "exchange": exchange, "mode": mode}, fh)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("expect")
    paper = str(tmp / "live-ac.db")
    pts = _paper_world(paper)
    p = {"paper": paper, "paper2": str(tmp / "none-paper2.db"), "bybit_db": str(tmp / "bybit.db"), "mexc_db": str(tmp / "woo.db"),
         "bybit_config": str(tmp / "executor.json"), "mexc_config": str(tmp / "executor-mexc.json"),
         "deepcoin_db": str(tmp / "none-deepcoin.db"), "deepcoin_config": str(tmp / "none-deepcoin.json"),
         "wooxpro2_db": str(tmp / "none-wooxpro2.db"), "wooxpro2_config": str(tmp / "none-wooxpro2.json"),
         "paper3": str(tmp / "none-paper3.db"),
         "toobit_db": str(tmp / "none-toobit.db"), "toobit_config": str(tmp / "none-toobit.json")}
    # 바이비트 (mainnet): the BTC lock on its own exchange stop, the ETH close after the paper's (시간 정리), the SOL one
    # still a wallet estimate
    _exec_world(p["bybit_db"], p["bybit_config"], paper, "bybit", "mainnet",
                [(pts[0], 3, "손절 발동(거래소)", 0.05, (0.006, 0.002, -0.001), True),
                 (pts[1], 4, "paper 청산 → 거래소 포지션 닫기", -0.02, (0.006, 0.001, 0.0), True),
                 (pts[2], 3, "paper 청산 → 거래소 포지션 닫기", -0.5, None, False)])
    # WOO X Pro (testnet: no real money): one trade whose fills did not add up (cost not measured)
    _exec_world(p["mexc_db"], p["mexc_config"], paper, "wooxpro", "testnet",
                [(pts[5], 5, "paper 청산 → 거래소 포지션 닫기", 0.3, (0.007, 0.004, 0.0), False)])
    X._walks.clear()
    d = X.build(p, NOW, ref_path=REF)
    return {"p": p, "pts": pts, "d": json.loads(json.dumps(d)), "tmp": tmp}


def test_the_answer_entries_and_funnel(world):
    d = world["d"]
    assert d["state"] == "ok" and d["since"] == SINCE and d["name"] == "추세판단 봇"
    assert d["ref"]["window_kst"] == ["2026-07-01", "2026-10-20"] and len(d["ref"]["honest_ko"]) == 5
    assert d["ref"]["honest_ko"][-1] == X.TIME_KEPT_KO                # its config keeps the 시간 정리 the replay ran with
    e = d["entries"]
    assert e["replay"]["per_weekday"] == pytest.approx(1.113) and e["replay"]["hist"] == [[0, 27], [1, 27], [2, 18], [3, 7], [5, 1]]
    live = e["live"]
    # 7 entries since the start (6 closed + the open one; the one before the start left out): 6 on weekdays, 1 on Saturday
    assert (live["entries"], live["weekend_entries"], live["all"], live["src"]) == (6, 1, 7, "outcomes")
    assert live["weekdays"] == pytest.approx(3.0) and live["per_weekday"] == pytest.approx(2.0)
    assert live["full_weekdays"] == 2 and live["hist"][2] == [2, 2]                  # Thursday and Friday: 2 each
    assert [x["n"] for x in live["days"]] == [0, 2, 2, 1, 0, 2] and [x["weekend"] for x in live["days"]] == [False] * 3 + [True] * 2 + [False]
    band = e["band"]
    assert band == X.entries_band(_ref()["entries"]["hist_weekdays"], [0.125, 1.0, 1.0, 0.875]) | {"where": band["where"]}
    assert band["mean"] == pytest.approx(3 * 1.1125) and band["where"] == X.where_in(6, band["lo"], band["hi"])
    assert e["ko"].startswith(f"평일 3.0일 동안 6번 들어갔어요 · 재현이라면 보통 {band['lo']}~{band['hi']}번 · ") and "범위가 넓어요" in e["ko"]
    assert e["weekend_ko"] == "주말에 1번 들어갔어요 · 재현은 주말 0번 (주말엔 쉬는 규칙)"
    f = d["funnel"]
    assert f["state"] == "ok"
    assert [x["n"] for x in f["replay"]] == [4923, 2391, 175, 119, 89]
    assert [(x["id"], x["n"]) for x in f["live"]] == [("signals", 20), ("after_time", 15), ("passed", 10), ("touched", 8), ("entered", 7)]
    assert f["live"][1]["share"] == pytest.approx(0.75) and f["live"][2]["of_prev"] == pytest.approx(10 / 15)
    assert f["replay"][4]["share"] == pytest.approx(89 / 4923)
    assert {b["id"]: b["n"] for b in f["live_blocked"]} == {"trend": 4, "spot": 1, "chase": 2, "pause": 3, "nopull": 1, "one": 1}
    assert {b["id"]: b["n"] for b in f["replay_blocked"]} == {"trend": 2124, "spot": 92, "chase": 1148, "pause": 1384, "nopull": 56, "one": 30}
    assert f["skipped"] == {"replay": 30, "live": 1}


def test_the_answer_results_and_costs(world):
    d, pts = world["d"], world["pts"]
    r = d["results"]
    paper = r["paper"]
    roes = [t["roe"] for t in pts]
    assert paper["n"] == 6 and paper["wins"] == sum(1 for x in roes if x > 0) and paper["roe_mean"] == pytest.approx(sum(roes) / 6, abs=1e-6)
    assert {x["id"]: x["n"] for x in paper["exits"]} == {"LOCK": 2, "TIME": 1, "SL": 1, "REV": 1, "JUDGE": 1}
    assert next(x for x in paper["exits"] if x["id"] == "TIME")["hold_med"] == 120 and paper["small"] is True
    assert paper["verdict"]["kind"] == "small" and paper["band"][0] < paper["band"][1]
    assert r["replay"]["n"] == 89 and r["replay"]["file"]["judge_exits"] == 0
    ex = {x["id"]: x for x in r["execs"]}
    by = ex["bybit"]
    assert (by["state"], by["real"], by["name_ko"]) == ("ok", True, "바이비트") and by["record"]["n"] == 3
    # its own stop above the entry = LOCK; a close that followed the paper takes the paper trade's reason (TIME, SL)
    assert {x["id"]: x["n"] for x in by["record"]["exits"]} == {"LOCK": 1, "TIME": 1, "SL": 1} and by["record"]["estimated"] == 1
    woo = ex["mexc"]
    assert (woo["state"], woo["real"], woo["name_ko"], woo["mode"]) == ("ok", False, "WOO X Pro", "testnet")
    assert {x["id"]: x["n"] for x in woo["record"]["exits"]} == {"LOCK": 1}
    # the paper's costs from its own records: the fees it booked, the slippage at the engine's rate, the funding it paid
    c = d["costs"]
    exp = []
    for t in pts:
        m, side = t["margin"], t["side"]
        raw_in, raw_out = t["entry_price"] / (1 + side * SLIP), t["exit_price"] / (1 - side * SLIP)
        slip = t["qty"] * SLIP * (raw_in + raw_out) / m
        before = side * t["qty"] * (raw_out - raw_in) / m
        assert before == pytest.approx(t["roe"] + slip + t["fees"] / m + t["funding"] / m)
        exp.append((before, slip, t["fees"] / m, t["funding"] / m))
    cp = c["paper"]
    assert cp["n"] == cp["of"] == 6 and cp["small"] is True
    for k, i in (("before", 0), ("slip", 1), ("fee", 2), ("funding", 3)):
        assert cp[k] == pytest.approx(sum(x[i] for x in exp) / 6, abs=1e-6), k
    assert cp["before"] - cp["slip"] - cp["fee"] - cp["funding"] == pytest.approx(cp["net"], abs=1e-5)
    assert c["paper_ko"].startswith("비용 전 거래당 ") and c["paper_ko"].endswith("· 표본 적음 (거래 6번)")
    assert c["ko"] == "재현에서는 수수료·미끄러짐 전엔 거의 본전(거래당 −0.4%)이었고, 비용이 거래당 4.5%p를 가져갔어요."
    # an executor's costs from its fills: the wallet estimate left out (2 of 3 measured)
    cb = by["costs"]
    assert (cb["n"], cb["of"]) == (2, 3)
    ms = []
    for pt, cost in ((pts[0], (0.006, 0.002, -0.001)), (pts[1], (0.006, 0.001, 0.0))):
        side = pt["side"]
        entry = pt["entry_price"] * (1 + side * 0.0003)
        m = entry * (10.0 / entry * pt["leverage"] / 10) / pt["leverage"]
        ms.append((m, cost))
    assert cb["fee"] == pytest.approx(sum(cst[0] / m for m, cst in ms) / 2, rel=1e-4)
    assert cb["slip"] == pytest.approx(sum(cst[1] / m for m, cst in ms) / 2, rel=1e-4)
    assert cb["funding"] == pytest.approx(sum(-cst[2] / m for m, cst in ms) / 2, rel=1e-4)
    assert cb["before"] - cb["slip"] - cb["fee"] - cb["funding"] == pytest.approx(cb["net"], abs=1e-5)
    assert by["costs_ko"].startswith("비용 전 거래당 ") and "표본 적음 (거래 2번)" in by["costs_ko"]
    # cost_ok 0: the fills did not measure the cost: none counted, said so
    assert woo["costs"]["n"] == 0 and woo["costs"]["of"] == 1 and woo["costs"]["before"] is None
    assert woo["costs_ko"] == "체결 기록으로 비용을 잰 거래가 아직 없어요 (닫힌 거래 1번)"


def test_the_answer_split_and_curve(world):
    d, pts = world["d"], world["pts"]
    sp = d["split"]
    mem = {r["id"]: r for r in sp["member"]}
    assert mem["N20_EMA9_CHOP@30m"]["replay"]["n"] == 20 and mem["N20_EMA9_CHOP@30m"]["paper"]["n"] == 2
    assert mem["N20_EMA9_CHOP@30m"]["role"] == "횡보" and mem["N20_EMA9_CHOP@30m"]["strategy"] == "N20_EMA9_CHOP"
    assert mem["F9_FVG@1h"]["bybit"]["n"] == 1 and mem["F9_FVG@1h"]["mexc"]["n"] == 0 and mem["F3_BOS@30m"]["mexc"]["n"] == 1
    assert [r["id"] for r in sp["member"]][0] == "N20_EMA9_CHOP@30m"           # the replay's most traded first
    coin = {r["id"]: r for r in sp["coin"]}
    assert coin["DOGEUSDT"]["replay"]["n"] == 19 and coin["BCHUSDT"]["paper"]["mean"] == pytest.approx(pts[5]["roe"], abs=1e-6)
    side = {r["id"]: r for r in sp["side"]}
    assert (side[-1]["replay"]["n"], side[1]["replay"]["n"]) == (61, 28) and side[1]["paper"]["n"] == 3
    cv = d["curve"]
    assert len(cv["replay"]) == 90 and cv["replay"][-1] == pytest.approx(sum(r["roe"] for r in X.replay_rows(_ref())), abs=1e-4)
    order = sorted(pts, key=lambda t: t["exit_time"])
    assert cv["paper"] == pytest.approx(list(itertools.accumulate([0.0] + [t["roe"] for t in order])), abs=1e-6)
    assert len(cv["execs"]["bybit"]) == 4 and len(cv["band"]["lo"]) == len(cv["band"]["hi"]) == 90
    assert all(lo <= hi for lo, hi in zip(cv["band"]["lo"], cv["band"]["hi"]))
    assert cv["band"]["lo"][89] < cv["replay"][-1] < cv["band"]["hi"][89]


def test_the_paper_costs_on_the_trend_bots_own_records(tmp_path):
    import test_livereview as RV
    w, now = RV._world(tmp_path)
    d = X.build({"paper": w.cfg.db, "bybit_db": str(tmp_path / "n1.db"), "mexc_db": str(tmp_path / "n2.db"),
                 "bybit_config": str(tmp_path / "x.json"), "mexc_config": str(tmp_path / "y.json")}, now, ref_path=REF)
    assert d["state"] == "ok"
    trades = w.trades()
    from paperbot.config import v3_settings
    s = v3_settings().slippage_frac
    rows = [X.paper_row(t, s) for t in trades]
    for t, r in zip(trades, rows):
        side, lev = t["side"], t["leverage"]
        raw_in, raw_out = t["entry_price"] / (1 + side * s), t["exit_price"] / (1 - side * s)
        assert r["fee"] == pytest.approx(t["fees"] / t["margin"]) and r["funding"] == pytest.approx(t["funding"] / t["margin"])
        # before costs = the raw price move at the leverage (the margin is the notional / leverage, up to the size step)
        assert r["before"] == pytest.approx(side * (raw_out / raw_in - 1) * lev, abs=2e-3)
        assert r["slip"] == pytest.approx(2 * s * lev, rel=0.02)
    assert d["costs"]["paper"]["n"] == 3 and d["results"]["paper"]["n"] == 3
    assert (d["funnel"]["live"][0]["n"], d["funnel"]["live"][4]["n"]) == (6, 3)        # livereview's own funnel
    assert d["entries"]["live"]["entries"] == 3


def test_honest_states(tmp_path):
    none = {"bybit_db": str(tmp_path / "a.db"), "mexc_db": str(tmp_path / "b.db"), "bybit_config": str(tmp_path / "a.json"),
            "mexc_config": str(tmp_path / "b.json")}
    assert X.build({"paper": str(tmp_path / "none.db"), **none}, NOW, REF)["state"] == "missing"
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not a database at all" * 50)
    d = X.build({"paper": str(bad), **none}, NOW, REF)
    assert d["state"] == "error" and d["reason_ko"] == "페이퍼 봇 기록을 읽지 못했어요" and d["reason"]
    s = Store3(str(tmp_path / "old.db"))
    s.put_state("combo_run", SINCE, {"config": {"name": "규칙봇 15", "trend": None}})
    s.commit()
    d = X.build({"paper": str(tmp_path / "old.db"), **none}, NOW, REF)
    assert d["state"] == "off" and "추세판단 봇이 아니에요" in d["reason_ko"] and "entries" not in d
    s.put_state("combo_run", SINCE, {"config": {"name": "추세판단 봇", "trend": {}}})
    s.commit()
    d = X.build({"paper": str(tmp_path / "old.db"), **none}, NOW, REF)
    assert d["state"] == "missing" and "첫 판단" in d["reason_ko"]
    s.put_state("combo", SINCE, {"trend_since": SINCE})              # (the start from state combo when state trend has none)
    s.commit()
    d = X.build({"paper": str(tmp_path / "old.db"), **none}, NOW, tmp_path / "no-ref.json")
    assert d["state"] == "missing" and d["reason_ko"] == X.REF_MISSING_KO
    # a start and nothing else: the replay's side in full, the live side empty but never a made-up zero record
    d = json.loads(json.dumps(X.build({"paper": str(tmp_path / "old.db"), **none}, NOW, REF)))
    s.close()
    assert d["state"] == "ok" and d["since"] == SINCE and d["results"]["paper"]["n"] == 0
    assert d["results"]["paper"]["roe_mean"] is None and d["results"]["paper"]["verdict"]["kind"] == "none"
    assert d["costs"]["paper"]["before"] is None and d["costs"]["paper_ko"] == "새 규칙 뒤 닫힌 거래가 아직 없어요"
    assert d["funnel"]["state"] == "ok" and d["funnel"]["live"][4]["n"] == 0                  # the tables exist (Store3)
    band = d["entries"]["band"]
    assert d["entries"]["live"]["entries"] == 0 and band["where"] == X.where_in(0, band["lo"], band["hi"])
    assert {x["id"]: x["state"] for x in d["results"]["execs"]} == {"bybit": "missing", "mexc": "missing"}
    assert all(x["record"] is None and x["costs_ko"] for x in d["results"]["execs"])


def test_a_stage_the_live_records_cannot_tell_says_so(tmp_path):
    path = str(tmp_path / "bare.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE state (k TEXT PRIMARY KEY, ts INTEGER NOT NULL, data TEXT NOT NULL)")
    conn.execute("INSERT INTO state VALUES ('combo_run', 1, ?)", (json.dumps({"config": {"name": "추세판단 봇", "trend": {}}}),))
    conn.execute("INSERT INTO state VALUES ('trend', 1, ?)", (json.dumps({"since": SINCE}),))
    conn.execute("CREATE TABLE signal_log (id INTEGER PRIMARY KEY, bar_close INTEGER, timeframe TEXT, strategy TEXT, symbol TEXT, "
                 "side INTEGER, atr REAL, ref_price REAL, status TEXT, data TEXT)")
    conn.execute("INSERT INTO signal_log (bar_close, timeframe, strategy, symbol, side, status, data) VALUES (?,?,?,?,?,?,?)",
                 (SINCE + HOUR, "30m", "F9_FVG@1h", "BTCUSDT", 1, "FILTERED", json.dumps({"why": "1시간 추세가 상승이라 숏 안 함"})))
    conn.commit()
    conn.close()
    d = X.build({"paper": path, "bybit_db": str(tmp_path / "a.db"), "mexc_db": str(tmp_path / "b.db"), "bybit_config": str(tmp_path / "a.json"),
                 "mexc_config": str(tmp_path / "b.json")}, NOW, REF)
    f = d["funnel"]
    assert f["live"][0]["n"] == 1 and f["live"][4]["n"] is None and f["live"][4]["why_ko"] == "진입 기록 표(outcomes)가 없어 모름"
    assert f["skipped"]["live"] is None and d["entries"]["live"]["src"] == "trades"
    # no signal table at all: the live funnel is missing with the reason (the replay's stays)
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE signal_log")
    conn.commit()
    conn.close()
    f = X.build({"paper": path, "bybit_db": str(tmp_path / "a.db"), "mexc_db": str(tmp_path / "b.db"), "bybit_config": str(tmp_path / "a.json"),
                 "mexc_config": str(tmp_path / "b.json")}, NOW, REF)["funnel"]
    assert f["state"] == "missing" and f["live"] is None and "signal_log" in f["reason_ko"] and f["replay"][0]["n"] == 4923


# ================================================================ the view in node
def _node(body: str, data) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    script = (f"Date.now = () => {int((data or {}).get('now_ms') or NOW)};\nconst D = await import('{dom}');\n"
              f"const X = await import('file://{JS}');\nconst d = {json.dumps(data)};\n"
              "const tick = async () => { for (let i = 0; i < 3; i++) await new Promise((r) => setTimeout(r, 0)); };\n" + body)
    r = subprocess.run([node, "--input-type=module"], input=script, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


VIEW = """const every = [];
const ctx = {api: () => Promise.resolve(d), every(ms, fn) { every.push(ms); }, watch() {}, alive: () => true, href: (n, a) => '#/' + a};
const v = X.expectView(ctx, {get: () => null});
await tick();
const w = D.walk(v.el);
const find = (n, c) => { if (!n || !n.childNodes) return null; if (String(n.className || "").split(" ").includes(c)) return n;
  for (const k of n.childNodes) { const f = find(k, c); if (f) return f; } return null; };
const sc = X.waterScale([{before: -0.0044, slip: 0.0128, fee: 0.032, funding: null, net: -0.0492}, {before: 0.05, slip: 0.01, fee: 0.03, funding: 0.0, net: 0.01}]);
console.log(JSON.stringify({text: w.text.replace(/\\s+/g, " "), classes: w.classes, every,
  hidden: !!(find(v.el, "lex-cards") || {}).hidden, head: X.headline(d),
  sc, wf: X.waterfall({before: -0.0044, slip: 0.0128, fee: 0.032, funding: null, net: -0.0492}, sc.lo, sc.hi), nowf: X.waterfall({before: null}, 0, 1),
  hist: X.histRows([[0, 27], [1, 27], [2, 18], [3, 7], [5, 1]], [[0, 1], [1, 0], [2, 2]]),
  escale: X.entryScale({lo: 1, hi: 6, mean: 3.3}, 6), noscale: X.entryScale(null, 3),
  bscale: X.bandScale([-0.2, 0.1], 0.05, -0.049), curve: X.curveModel({replay: [0, 0.1, -0.1, -0.2], paper: [0, 0.2], execs: {bybit: [0, -0.1, 0.0]},
    band: {lo: [0, -0.5, -0.7, -0.9], hi: [0, 0.2, 0.3, 0.4]}}, 100, 50, null),
  zoom: X.curveModel({replay: [0, 0.1, -0.1, -0.2], paper: [0, 0.2], execs: {}, band: {lo: [0, -0.5, -0.7, -0.9], hi: [0, 0.2, 0.3, 0.4]}}, 100, 50, 1),
  counts: [X.liveCount({replay: [0, 1, 2], paper: [0, 1], execs: {bybit: [0, 1, 2]}}), X.liveCount({replay: [0, 1], paper: [0], execs: {}}), X.liveCount(null)],
  fmt: [X.pc(-0.0492), X.pc(null), X.pp(0.0448), X.psum(-4.3816), X.share(0.3375), X.costKo(0.0128), X.costKo(-0.001), X.costKo(0),
    X.holdKo(49), X.holdKo(120), X.holdKo(167), X.holdKo(null), X.dayKo(1792508400000), X.accName("replay"), X.accName("paper"), X.accName("mexc")]}));"""


def test_the_view(world):
    out = _node(VIEW, world["d"])
    t, cls = out["text"], out["classes"]
    for bad in ("null", "undefined", "NaN", "[object", "Infinity"):
        assert bad not in t, bad
    for words in (
            # the first block: the key sentence, the window, 가상 vs 실제, the tiles, every caveat
            "재현 비교 · 추세판단 봇 · 가상(재현) vs 실제", "재현에서는 수수료·미끄러짐 전엔 거의 본전(거래당 −0.4%)이었고, 비용이 거래당 4.5%p를 가져갔어요.",
            "실제(페이퍼) 거래 6번 · 표본 적음 · 아직 판단 못 함", "2026-07-01 ~ 2026-10-20 (한국 시간)", "새 규칙 시작 10/21 21:00 뒤",
            "재현 (가상)", "−4.9%", "거래당 평균 순ROE · 89번", "가상 · 재현", "실제 · 페이퍼(연습)", "바이비트", "실거래 · 진짜 돈", "WOO X Pro",
            "실행기 · testnet", "그 기간 시장의 숫자라 앞으로는 다를 수 있어요", "펀딩비 없음",
            # 진입 횟수
            "진입 횟수", "재현 (가상) · 평일 하루", "1.11번", "실제 (페이퍼) · 평일 하루", "2.00번", "평일 3.0일 · 6번", "평일 3.0일 동안 6번 들어갔어요",
            "주말에 1번 들어갔어요 · 재현은 주말 0번 (주말엔 쉬는 규칙)", "하루에 몇 번? (평일)", "27일 · 34%", "2일 · 100%", "10/22 (목)",
            "재현 달마다 평일 하루: 7월", "1.33번",
            # 깔때기
            "깔때기", "쉬는 시간·추격 막기 뒤", "추세·자리 검사 통과", "되돌림 닿음", "4,923 · 100%", "2,391 · 49%", "15 · 75%", "7 · 35%",
            "재현에서 걸린 곳: ", "추격 막기 1,148 (23%)", "실제에서 걸린 곳: ", "실제 신호가 아직 20개라", "재현 30개 · 실제 1개",
            # 거래 결과
            "거래 결과", "이긴 비율", "평균 순ROE", "가운데 순ROE", "가운데 보유", "1시간 39분", "계단 익절", "감독: 시간 정리", "감독: 추세 뒤집힘",
            "빠른 청산", "손절", "가운데 49분", "표본 적음 · 아직 판단 못 함 (거래 6번 · 20번부터 봐요)", "지금은 재현 범위", "(1번 어림)",
            "2000번 다시 뽑아 본 범위", "재현에는 감독: 추세 뒤집힘 청산이 한 번도 없었어요",
            # 비용 쪼개기
            "비용 쪼개기", "핵심", "비용 전", "미끄러짐", "수수료", "펀딩비", "계산 안 함", "−1.3%p", "−3.2%p", "89번 평균",
            "닫힌 3번 중 비용을 잰 것", "바이비트 (진짜 돈): 비용 전 거래당", "WOO X Pro: 체결 기록으로 비용을 잰 거래가 아직 없어요 (닫힌 거래 1번)",
            "페이퍼의 미끄러짐은 규칙에 넣은 가정(한쪽 0.02%)이에요", "실거래의 '비용 전'은 주문 직전 본 가격 기준이에요", "가는 세로선 = 0",
            # 나눠 보기, 누적
            "나눠 보기", "매매법", "코인", "방향", "실제 · 페이퍼(연습)", "20번", "적음", "누적 순ROE", "전체", "실제 거래 수만큼",
            # (a few live trades: the lines open zoomed to the first 10 trades)
            "(10번)", "(6번)", "(3번)", "재현이라면 10번째에 보통", "10번째 거래", "재현 선은 지난 기간에 실제로 나온 순서 하나예요",
            "새 규칙이 재현(가상)처럼 가고 있나요? · 핵심은 아래 비용 쪼개기",
            # the captions
            "페이퍼(연습) 손익은 진짜 돈이 아니에요", "실제 돈은 실행기가 메인넷일 때만"):
        assert words in t, words
    assert out["every"] == [60000] and out["hidden"] is False
    assert t.count("비용이 거래당 4.5%p를 가져갔어요") == 1                    # the key sentence once, on top of 비용 쪼개기
    assert any("lex-hero" in c for c in cls) and any("lex-x-LOCK" in c for c in cls) and any("lex-wbar cost" in c for c in cls)
    assert out["head"] == "실제(페이퍼) 거래 6번 · 표본 적음 · 아직 판단 못 함"
    # the pure helpers
    sc, wf = out["sc"], out["wf"]
    assert sc["lo"] < -0.0492 and sc["hi"] > 0.05 and 0 < sc["zero"] < 1
    assert [p["k"] for p in wf] == ["before", "slip", "fee", "funding", "net"] and wf[3]["v"] is None
    assert wf[1]["from"] == pytest.approx(-0.0044) and wf[2]["to"] == pytest.approx(-0.0492) and wf[4]["to"] == pytest.approx(-0.0492)
    assert wf[2]["left"] + wf[2]["width"] == pytest.approx(wf[1]["left"]) and out["nowf"] is None
    assert [(r["k"], r["replay"]["days"], r["live"]["days"]) for r in out["hist"]] == [(0, 27, 1), (1, 27, 0), (2, 18, 2), (3, 7, 0), (4, 0, 0), (5, 1, 0)]
    assert out["hist"][2]["live"]["share"] == pytest.approx(2 / 3)
    assert out["escale"]["max"] == 7 and out["escale"]["live"] == pytest.approx(6 / 7) and out["noscale"] is None
    b = out["bscale"]
    assert b["band"][0] < b["ref"] < b["mark"] < b["band"][1]
    c = out["curve"]
    assert c["n"] == 3 and c["paths"]["replay"].startswith("M0.0 ") and c["paths"]["paper"].count("L") == 1 and c["band"].endswith("Z")
    assert c["last"] == {"replay": -0.2, "paper": 0.2, "bybit": 0.0} and c["count"] == {"replay": 3, "paper": 1, "bybit": 2}
    assert out["zoom"]["n"] == 1 and out["zoom"]["last"]["replay"] == 0.1 and out["counts"] == [2, 0, 0]
    assert out["fmt"] == ["−4.9%", "—", "4.5%p", "−438%p", "34%", "−1.3%p", "+0.1%p", "0.0%p", "49분", "2시간", "2시간 47분", "—",
                          "10/21 (수)", "재현 (가상)", "페이퍼(연습)", "WOO X Pro"]


def test_the_view_states():
    out = _node(VIEW, {"state": "off", "reason_ko": "지금 돌고 있는 페이퍼 봇은 추세판단 봇이 아니에요 (설정에 추세 판단이 없음)"})
    assert "꺼짐" in out["text"] and "추세판단 봇이 아니에요" in out["text"] and out["hidden"] is True
    out = _node(VIEW, {"state": "missing", "reason_ko": X.REF_MISSING_KO})
    assert "수집 전" in out["text"] and "재현 기준 파일" in out["text"] and out["hidden"] is True
    assert out["head"] == "재현 비교 기록을 기다리는 중"
    out = _node(VIEW, {"state": "error", "reason_ko": "페이퍼 봇 기록을 읽지 못했어요", "reason": "DatabaseError: file is not a database"})
    assert "못 읽음" in out["text"] and "DatabaseError" in out["text"] and out["hidden"] is True
    for bad in ("null", "undefined", "NaN"):
        assert bad not in out["text"], bad


def test_the_view_before_any_live_trade(tmp_path):
    s = Store3(str(tmp_path / "p.db"))
    s.put_state("combo_run", SINCE, {"config": {"name": "추세판단 봇", "trend": {}}})
    s.put_state("trend", SINCE, {"since": SINCE})
    s.close()
    d = json.loads(json.dumps(X.build({"paper": str(tmp_path / "p.db"), "bybit_db": str(tmp_path / "a.db"), "mexc_db": str(tmp_path / "b.db"),
                                       "bybit_config": str(tmp_path / "a.json"), "mexc_config": str(tmp_path / "b.json")}, SINCE + HOUR, REF)))
    out = _node(VIEW, d)
    t = out["text"]
    for bad in ("null", "undefined", "NaN", "Infinity"):
        assert bad not in t, bad
    for words in ("실제(페이퍼) 거래가 아직 없어요 · 재현 숫자만 먼저 보여 드려요", "새 규칙 뒤 닫힌 거래 없음", "새 규칙 뒤 닫힌 거래가 아직 없어요",
                  "아직 그런 평일이 없어요", "수집 전", "재현에서는 수수료·미끄러짐 전엔 거의 본전", "거래 없음"):
        assert words in t, words


# ================================================================ static checks and the wiring
def test_static():
    node = shutil.which("node")
    if node is not None:
        r = subprocess.run([node, "--check", JS], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
    css = re.sub(r"/\*.*?\*/", "", _read(CSS), flags=re.S)
    js = _read(JS)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and not re.search(r"#[0-9a-fA-F]{6}\b", js)
    assert not re.search(r"font-size:\s*\d", css) and not re.search(r"font:\s*\d+\s+\d", css)
    for m in re.finditer(r"font(?:-size)?:\s*([^;]+);", css):
        assert "var(--t-" in m.group(1) or "var(--ts)" in m.group(1), m.group(0)
    assert not re.search(r"innerHTML|insertAdjacentHTML|outerHTML|toLocaleString|Intl\.NumberFormat|eval\(", js)
    # every class of this file is the screen's own (lex-), and no other screen uses the prefix
    classes = set(re.findall(r"\.([a-zA-Z][\w-]*)", css))
    assert {c for c in classes if not c.startswith("lex")} <= {"seg", "pp", "up", "down", "na", "top", "bot", "above", "below", "small",
                                                              "none", "replay", "live", "ref", "warn", "wk", "today", "has", "zero",
                                                              "cost", "flat", "k-net", "k-before"}
    for f in os.listdir(SCREENS):                          # (the prefix, not "flex-": a class selector or a class name)
        if f.endswith(".css") and f != "livebots-expect.css":
            assert not re.search(r"\.lex-", _read(SCREENS, f)), f
        if f.endswith(".js") and f != "livebots-expect.js":
            assert not re.search(r"[\"' ]lex-", _read(SCREENS, f)), f
    assert '"/api/v4/livebots/replayref"' in js and "export function expectView" in js
    # the module reads its reference file relative to the repository (paperbot/events.py's rule), read-only everywhere
    assert X.REF_PATH == X.Path(ROOT).resolve() / "data" / "trend_replay_0701_1020.json"
    src = _read(ROOT, "paperbot", "dash", "more", "livereplayref.py")
    assert "sqlite3.connect" not in src and "INSERT" not in src and "UPDATE" not in src


def test_the_wiring():
    from paperbot.livedash import app as LA
    assert "livereplayref" in LA.MODULES
    js = _read(SCREENS, "livebots.js")
    assert 'import {expectView} from "./livebots-expect.js"' in js
    assert '{id: "expect", label: "재현 비교", make: (ctx, hub) => expectView(ctx, hub), own: true}' in js
    assert js.index('{id: "review", label: "검토"') < js.index('{id: "expect"') < js.index('{id: "perf", label: "성적"')
    routes = _read(V4, "core", "routes.js")
    assert '"review", "expect", "perf"' in routes
    assert 'expect: {ko: "재현 비교", group: "perf", title: "재현 비교 (7/1~10/20 가상 vs 실제)"},' in routes and "expect: () => SICON." in routes
    assert "expect:" in _read(V4, "core", "search.js").split("export const LIVE_ALIAS")[1]
    assert '@import url("livebots-expect.css");' in _read(SCREENS, "livebots.css")
    inv = _read(V4, "INVENTORY.md")
    assert "livebots-expect.js" in inv and "/api/v4/livebots/replayref" in inv
    assert "**재현 비교**" in _read(ROOT, "docs", "livedash-ko.md")


def test_the_route_serves(world, monkeypatch):
    import fastapi
    from fastapi.testclient import TestClient
    p = world["p"]
    for k, (var, _default) in L.ENV.items():
        monkeypatch.setenv(var, p[k])
    L._cache.clear()
    app = fastapi.FastAPI()
    assert X.register(app, None) == {"routes": ["/api/v4/livebots/replayref"]}
    r = TestClient(app).get("/api/v4/livebots/replayref")
    assert r.status_code == 200
    d = r.json()
    assert d["state"] == "ok" and d["results"]["paper"]["n"] == 6 and d["results"]["replay"]["n"] == 89      # (now: the real clock)
    L._cache.clear()
