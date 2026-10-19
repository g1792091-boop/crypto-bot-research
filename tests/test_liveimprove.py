"""매매법 성적표와 개선 후보 장부 (paperbot/liveimprove.py): hand-made databases in the real schemas (the paper bot's
paperbot.store3, the executor's paperbot.executor.ExecStore), the real backtest reference
(deploy/combo.live-ac.expected.json), an in-memory notifier, no network."""

import hashlib
import math
import os
import re
import sqlite3
from pathlib import Path

import pytest

from paperbot import livecheck as LC
from paperbot import liveimprove as LI
from paperbot.models import Signal, SignalOutcome, TradeRecord
from paperbot.notify import CRITICAL, INFO, ListNotifier, telegram_text
from paperbot.store3 import Store3

MIN = 60_000
H1 = 3_600_000
DAY = 86_400_000
T0 = LC.window_of("2026-10-19")[0]              # Monday 09:00 KST, the first live day
NOW = T0 + 7 * DAY + 30 * MIN                   # the next Monday 09:30 KST
BTC, ETH, SOL, DOGE = "BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"
REF = LI.load_ref()
REPO = Path(__file__).resolve().parent.parent
DEPLOY = REPO / "deploy"


# ====================================================================== builders
def _rstop(stop: str) -> list:
    kind, val = re.match(r"([a-z]+)([\d.]+)$", stop).groups()
    return [kind, float(val)]


class World:
    """Paper trades of the combined account, each with its ENTERED signal (member, member_order, rdims, rstop) as
    paperbot/combo.py records it; one entry an hour from T0 (so the KST blocks turn over). ``key`` is the reference's
    member key (from 0); the paper bot numbers its settings from 1 (member_order = key + 1, combo.py)."""

    def __init__(self):
        self.items = []
        self.t = T0

    def add(self, key, wins=0, losses=0, symbol=BTC, side=1, reg5=4, signal=True, win_roe=0.125, loss_roe=-0.5,
            number=None, label_only=False):
        m = REF["members"][str(key)]
        order = key + 1 if number is None else number
        for won in [True] * wins + [False] * losses:
            self.t += H1
            t = self.t
            pnl = 5.0 if won else -20.0
            rec = TradeRecord(strategy_id=m["strategy"], symbol=symbol, timeframe=m["tf"], side=side, signal_ts=t - 1,
                              entry_time=t, entry_price=100.0, exit_time=t + 30 * MIN,
                              exit_price=101.0 if won else 99.0,
                              exit_reason="LOCK" if won else "SL", qty=1.0, leverage=40, tier="best", margin=40.0,
                              stop_price=99.0, tp_price=float("nan"), liq_price=90.0, fees=0.1, funding=0.0, pnl=pnl,
                              roe=win_roe if won else loss_roe, price_move=0.01, mae_price=99.5, mfe_price=101.5,
                              equity_after=1000.0, score=3.0, stop_initial=99.0)
            out = None
            if signal:
                meta = {"member": f"{m['strategy']}@{m['tf']}#{order}~abc", "member_order": order,
                        "rdims": {"sym": LI.SYMS.index(symbol), "side": side, "reg5": reg5, "hb": LI.kst_hb(t)},
                        "rstop": _rstop(m["stop"])}
                if label_only:
                    del meta["member_order"]
                sig = Signal(ts=t - 1, symbol=symbol, timeframe=m["tf"], strategy_id=m["strategy"], side=side,
                             stop_price=99.0, meta=meta)
                out = SignalOutcome(signal=sig, status="ENTERED", reason="", step_ts=t)
            self.items.append((rec, out))
        return self

    def db(self, path, config=None) -> str:
        s = Store3(str(path))
        for rec, out in self.items:
            s.trade(LC.ACCOUNT, rec)
            if out is not None:
                s.outcome(LC.ACCOUNT, out)
        if config is not None:
            s.put_state("combo_run", T0, {"config": config})
        s.close()
        return str(path)


def exec_db(path, trades) -> str:
    from paperbot.executor import ExecStore
    st = ExecStore(str(path), lock=False)
    for t in trades:
        st.trade_open(t)
        if t.get("exit_ts") is not None:
            st.trade_close(t["key"], t["exit_ts"], "paper 청산", t["pnl"], t)
    st.close()
    return str(path)


def info(name, db):
    return LC.ExecInfo(name=name, config="-", unit=f"paperbot-executor-{name}", db=str(db), light_n=20,
                       light_min=0.85, exchange=name, kill_file="/nonexistent/STOP")


def src(tmp_path, paper, execs=()):
    return LI.Sources(db=str(tmp_path / "liveimprove.db"), paper_db=str(paper), executors=list(execs))


def card_of(tmp_path, world, execs=(), cuts=LI.CUTS):
    g = LI.gather(src(tmp_path, world.db(tmp_path / "live-ac.db"), execs))
    return g, LI.scorecard(g["trades"], g["ref"], g["follow"], cuts=cuts)


def row(card, cut, key):
    return next(r for r in card["cuts"][cut] if r["key"] == key)


def _sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ====================================================================== statistics
def test_binomial_tail_matches_counting():
    for n in (1, 5, 12, 20):
        for p in (0.3, 0.6709, 0.75, 0.95):
            for k in range(-1, n + 1):
                want = sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(0, k + 1))
                assert LI.binom_cdf(k, n, p) == pytest.approx(min(1.0, want), rel=1e-9, abs=1e-15)
    assert LI.binom_cdf(5, 0, 0.75) == 1.0 and LI.binom_cdf(20, 20, 0.75) == 1.0
    assert LI.binom_cdf(1000, 5000, 0.75) < 1e-300 or LI.binom_cdf(1000, 5000, 0.75) == 0.0   # large n: no overflow
    assert LI.binom_cdf(11, 20, 0.75) == pytest.approx(0.0409, abs=1e-4)


def test_status_words_small_samples_and_the_multiple_testing_bar():
    assert LI.verdict(9, 0, 0.75, 27) == (LI.SMALL, None)                 # under 10 trades: no verdict, even 0 wins
    word, p = LI.verdict(10, 10, 0.75, 27)
    assert word == LI.OK and p == 1.0
    word, p = LI.verdict(20, 11, 0.75, 27)                                 # p = 0.041: below 0.05, above 0.05 / 27
    assert word == LI.WATCH and LI.ALPHA / 27 < p < LI.ALPHA
    assert LI.verdict(20, 11, 0.75, 1)[0] == LI.BAD                        # the same alone would be "확실히 나쁨"
    word, p = LI.verdict(20, 8, 0.75, 27)                                  # p = 0.0009 < 0.0019
    assert word == LI.BAD and p < LI.ALPHA / 27
    assert LI.verdict(20, 9, 0.75, 27)[0] == LI.WATCH                       # p = 0.0039: still only "주의" among 27
    assert LI.verdict(20, 9, 0.75, 95)[0] == LI.WATCH and LI.verdict(20, 5, 0.75, 95)[0] == LI.BAD


def test_honest_rate_falls_back_to_the_overall_one_below_30_unseen_trades():
    assert LI.strategy_honest(REF, "N03_ADX_GC") == (pytest.approx(0.8363), "이 매매법 171번")
    assert LI.strategy_honest(REF, "F15_LON_BRK") == (pytest.approx(0.8667), "이 매매법 30번")
    for name in ("DOGE", "F12_MSS_DISP", "F17_Z", "F5_BOX_HTF", "NOT_A_STRATEGY"):   # [12, ..], none, [9, ..], [7, ..]
        assert LI.strategy_honest(REF, name) == (pytest.approx(0.7497), "전체")


# ====================================================================== 1. the scorecard
def _score_world():
    return (World()
            .add(4, wins=11, losses=1, symbol=BTC, side=1, reg5=0)              # N03_ADX_GC 15m atr4 now
            .add(0, wins=4, losses=6, symbol=SOL, side=-1, reg5=2)              # F12_MSS_DISP: honest n/a -> 75%
            .add(76, wins=1, losses=2, symbol=DOGE, side=1, reg5=4)             # F4_FAN: 3 trades
            .add(1, wins=2, symbol=BTC, side=-1, reg5=1)                        # N08_ICHI_WR 15m swing20 break invert
            .add(4, wins=1, symbol=BTC, side=1, signal=False))                  # no ENTERED record


def test_scorecard_per_strategy_with_fit_honest_and_status(tmp_path):
    g, card = card_of(tmp_path, _score_world())
    rows = card["cuts"]["strategy"]
    assert len(rows) == 27 and {r["key"] for r in rows} == set(REF["strategies"])          # every strategy, 0 too
    n03 = row(card, "strategy", "N03_ADX_GC")
    assert (n03["n"], n03["wins"], n03["losses"]) == (13, 12, 1) and rows[0] is n03          # most trades first
    assert n03["avg_roe"] == pytest.approx((12 * 0.125 - 0.5) / 13) and n03["loss_roe_median"] == pytest.approx(-0.5)
    assert n03["fit"] == pytest.approx(0.9516) and n03["honest"] == pytest.approx(0.8363)
    assert n03["status"] == LI.OK and n03["family"] == 27
    f12 = row(card, "strategy", "F12_MSS_DISP")
    assert (f12["n"], f12["wins"]) == (10, 4) and f12["honest_src"] == "전체"
    assert f12["status"] == LI.WATCH and f12["p"] == pytest.approx(0.0198, abs=1e-4)          # not "확실히 나쁨"
    assert row(card, "strategy", "F4_FAN")["status"] == LI.SMALL
    assert row(card, "strategy", "F17_Z")["n"] == 0 and row(card, "strategy", "F17_Z")["status"] == LI.SMALL
    o = card["overall"]
    assert (o["n"], o["wins"]) == (28, 19)
    assert o["fit"] == pytest.approx(0.9132) and o["honest"] == pytest.approx(0.7497)
    assert o["roll"][20]["fit_p5"] == 16 and o["roll"][20]["honest_p5"] == 12 and 40 not in o["roll"]
    text = "\n".join(LI.overall_lines(o))
    assert "본전 77.6%" in text and "첫 진짜 점검은 거래 40번(지금 28번)" in text
    assert text.startswith("전체: 19/28 (68%) · 손익 -$85.00 · 평균 순ROE ")
    assert n03["label"] == "N03_ADX_GC 15분" and row(card, "strategy", "F17_Z")["label"] == "F17_Z"


def test_scorecard_per_setting_and_every_cut(tmp_path):
    g, card = card_of(tmp_path, _score_world())
    m5 = row(card, "member", "5")                       # setting 5 as the paper bot counts it = reference key 4
    assert m5["label"] == "N03_ADX_GC 15분 · ATR 4배 · 즉시 진입 (#5)" and (m5["n"], m5["wins"]) == (12, 11)
    assert m5["fit"] == pytest.approx(0.913) and m5["honest"] == pytest.approx(0.8363) and m5["family"] == 95
    assert row(card, "member", "2")["label"] == "N08_ICHI_WR 15분 · 스윙 20봉 · 돌파 확인 뒤 진입 · 방향 반대 (#2)"
    unknown = row(card, "member", None)
    assert unknown["n"] == 1 and unknown["label"] == "모름(기록 없음)"                        # the trade without its signal
    assert row(card, "coin", BTC)["n"] == 15 and row(card, "coin", BTC)["fit"] == pytest.approx(0.9064)
    assert [r["key"] for r in card["cuts"]["side"]] == ["1", "-1"] and row(card, "side", "-1")["label"] == "숏"
    reg = row(card, "reg5", "2")
    assert reg["label"] == "강하락" and reg["n"] == 10 and reg["fit"] == pytest.approx(0.9256)
    assert row(card, "reg5", None)["n"] == 1                                                  # no rdims: regime unknown
    assert sum(r["n"] for r in card["cuts"]["hb"]) == 28 and card["cuts"]["hb"][0]["label"].endswith("시")
    stop = row(card, "stop", "atr4")
    assert stop["label"] == "ATR 4배" and stop["n"] == 12 and stop["fit"] == pytest.approx(0.9133)
    assert row(card, "stop", "swing20")["label"] == "스윙 20봉" and row(card, "stop", None)["n"] == 1
    assert row(card, "entry", "break")["n"] == 5 and row(card, "entry", "break")["label"] == "돌파 확인 뒤 진입"
    assert row(card, "invert", "1")["n"] == 2 and row(card, "invert", "0")["n"] == 25
    lines = LI.table_lines(card["cuts"]["strategy"], "strategy", [])
    assert lines[0] == "[매매법별]" and any(ln.startswith("N03_ADX_GC") for ln in lines)
    assert "이 표의 \"확실히 나쁨\" 기준: p < 0.05 / 27 = 0.0019" in lines
    assert any("처음 보는 기간 거래가 30번 미만" in ln for ln in lines)


def test_settings_are_numbered_from_1_like_the_paper_bot(tmp_path):
    """combo.py numbers its settings from 1 (member_order); the reference's members are keyed from 0
    (livecheck.ref_member). Without member_order the label's '#N' is read; a number whose setting is another
    strategy or timeframe (the config changed) is not trusted."""
    w = (World().add(4, wins=1)                                # member_order 5 -> reference key 4 (N03_ADX_GC 15m atr4)
         .add(29, wins=1, symbol=SOL, label_only=True)        # 'F5_BOX_RSI@30m#30~abc' only
         .add(9, wins=1, symbol=ETH, number=4))               # F10_M2022 1h numbered 4: reference key 3 is N03 15m
    g = LI.gather(src(tmp_path, w.db(tmp_path / "live-ac.db")))
    got = [(t["strategy"], t["order"], t["stop"], t["entry"]) for t in g["trades"]]
    assert got == [("N03_ADX_GC", 5, "atr4", "now"), ("F5_BOX_RSI", 30, "atr3", "now"),
                   ("F10_M2022", None, "swing10", None)]          # the stop still comes from the signal's own rstop
    card = LI.scorecard(g["trades"], g["ref"], g["follow"], cuts=("member",))
    assert [r["key"] for r in card["cuts"]["member"]] == ["5", "30", None]
    assert LI.ref_of_order(REF, 5) is REF["members"]["4"] and LI.ref_of_order(REF, None) is None


def test_executor_columns_compare_live_and_paper_roe_on_the_same_trades(tmp_path):
    w = World().add(4, wins=3, symbol=BTC).add(0, losses=1, symbol=SOL, side=-1)
    paper = w.db(tmp_path / "live-ac.db")
    ts = [rec.entry_time for rec, _ in w.items]
    by = exec_db(tmp_path / "bybit.db", [
        # by the paper key: margin 1 x 100 / 40 = 2.5, pnl 0.25 -> +10% (paper +12.5%)
        {"key": f"{LC.ACCOUNT}|{BTC}|{ts[0]}", "symbol": BTC, "side": 1, "qty": 1.0, "leverage": 40,
         "entry_ts": ts[0] + 3000, "entry_price": 100.0, "exit_ts": ts[0] + 31 * MIN, "pnl": 0.25},
        # no key: the same coin and side within 5 minutes; pnl 0.30 -> +12% (paper +12.5%)
        {"key": "other", "symbol": BTC, "side": 1, "qty": 1.0, "leverage": 40, "entry_ts": ts[1] + 60_000,
         "entry_price": 100.0, "exit_ts": ts[1] + 31 * MIN, "pnl": 0.30},
        # the SOL short lost more live: -1.5 -> -60% (paper -50%)
        {"key": f"{LC.ACCOUNT}|{SOL}|{ts[3]}", "symbol": SOL, "side": -1, "qty": 1.0, "leverage": 40,
         "entry_ts": ts[3] + 3000, "entry_price": 100.0, "exit_ts": ts[3] + 31 * MIN, "pnl": -1.5},
        # still open and unmatched: left out
        {"key": f"{LC.ACCOUNT}|{BTC}|{ts[2]}", "symbol": BTC, "side": 1, "qty": 1.0, "leverage": 40,
         "entry_ts": ts[2] + 3000, "entry_price": 100.0},
        {"key": "lone", "symbol": DOGE, "side": 1, "qty": 1.0, "leverage": 40, "entry_ts": T0 - DAY,
         "entry_price": 100.0, "exit_ts": T0 - DAY + H1, "pnl": 1.0}])
    g = LI.gather(LI.Sources(db=str(tmp_path / "li.db"), paper_db=paper,
                             executors=[info("bybit", by), info("mexc", tmp_path / "missing.db")]))
    assert g["follow"]["mexc"] is None and len(g["follow"]["bybit"]) == 3
    card = LI.scorecard(g["trades"], g["ref"], g["follow"], cuts=("strategy",))
    e = row(card, "strategy", "N03_ADX_GC")["exec"]["bybit"]
    assert e["n"] == 2 and e["wins"] == 2
    assert e["live_roe"] == pytest.approx(0.11) and e["paper_roe"] == pytest.approx(0.125)
    assert e["leak"] == pytest.approx(-0.015) and "mexc" not in row(card, "strategy", "N03_ADX_GC")["exec"]
    assert row(card, "strategy", "F12_MSS_DISP")["exec"]["bybit"]["leak"] == pytest.approx(-0.10)
    lines = LI.table_lines(card["cuts"]["strategy"], "strategy", g["infos"])
    n03 = next(ln for ln in lines if ln.startswith("N03_ADX_GC"))
    assert "2번 -1.5%p" in n03
    text = "\n".join(LI.exec_lines(card["overall"], g["infos"], g["follow"]))
    assert "- 바이비트: 따라감 2/3 (67%) · 실현 -$0.95 · 순ROE가 페이퍼보다 -4.3%p" in text
    assert "- MEXC: 기록 없음(아직 시작 전이거나 읽을 수 없음)" in text


def test_since_counts_from_0900_kst_of_that_date(tmp_path):
    w = World().add(4, wins=2)
    w.t = T0 + 3 * DAY
    w.add(4, losses=1)
    s = src(tmp_path, w.db(tmp_path / "live-ac.db"))
    assert LI.gather(s)["since"] == T0 + H1 and len(LI.gather(s)["trades"]) == 3
    g = LI.gather(s, LI.since_ms("2026-10-21"))
    assert g["since"] == T0 + 2 * DAY and [t["pnl"] for t in g["trades"]] == [-20.0]


def test_a_config_the_reference_does_not_describe_is_said(tmp_path):
    import json
    cfg = json.loads((DEPLOY / "combo.live-ac.json").read_text(encoding="utf-8"))
    w = World().add(4, wins=1)
    assert not LI.gather(src(tmp_path, w.db(tmp_path / "a.db", config=cfg)))["problems"]
    cfg["members"] = cfg["members"][:-1]
    probs = LI.gather(src(tmp_path, w.db(tmp_path / "b.db", config=cfg)))["problems"]
    assert probs and "기준표가 페이퍼 봇의 지금 설정과 다름(세팅 수가 다름" in probs[0]


# ====================================================================== 2. candidates
def _cell_world():
    """87 trades, 65 wins (75% against the honest 75%: nothing "확실히 나쁨", the weekly message stays silent)."""
    return (World()
            .add(29, wins=3, losses=7, symbol=SOL, side=-1, reg5=4)      # F5_BOX_RSI SOL short: 3/10 vs 67%
            .add(29, wins=10, symbol=BTC, side=1, reg5=4)                 # ... and 10 wins: the strategy is fine
            .add(9, wins=4, losses=6, symbol=BTC, side=1, reg5=1)         # F10_M2022 bad all over (BTC long only)
            .add(4, wins=0, losses=7, symbol=DOGE, side=1, reg5=1)        # 7 trades: never a candidate (< 8)
            .add(4, wins=8, losses=2, symbol=BTC, side=-1, reg5=1)        # 8/10 vs 84%: not
            .add(11, wins=40, symbol=BTC, side=1))                        # N03_ADX_GC 30m: the account's good part


def test_cell_finder_needs_8_trades_and_p_below_005_and_notes_the_luck(tmp_path):
    g = LI.gather(src(tmp_path, _cell_world().db(tmp_path / "live-ac.db")))
    c = LI.find_candidates(g["trades"], g["ref"])
    cells = {x["cell"]: x for x in c["flagged"]}
    sol = cells["strategy_coin:F5_BOX_RSI:SOLUSDT"]
    assert (sol["n"], sol["wins"]) == (10, 3) and sol["expected"] == pytest.approx(0.6709)   # honest (fit is higher)
    assert sol["p"] == pytest.approx(0.01826, abs=1e-4) and sol["expected_src"] == "처음 보는 기간 이 매매법 79번"
    assert sol["label"] == "F5_BOX_RSI 30분 SOL"
    # the same 10 trades are also "F5_BOX_RSI short" and "every strategy's SOL short": one candidate, the most
    # specific cell, the others named in its question (live trades cannot tell them apart; the backtest can)
    assert sol["same"] == ["F5_BOX_RSI 30분 숏", "모든 매매법 SOL 숏"]
    assert sol["question"] == ("F5_BOX_RSI 30분 SOL 끄기: 2020-24와 2025-26 둘 다 좋아지나? 거래 수는 얼마나 줄어드나? "
                               "같은 거래가 보인 다른 칸도 함께 비교: F5_BOX_RSI 30분 숏, 모든 매매법 SOL 숏.")
    assert "strategy_side:F5_BOX_RSI:-1" not in cells and "coin_side:SOLUSDT:-1" not in cells
    assert c["cells"]["coin_side:SOLUSDT:-1"]["p"] < LI.ALPHA                       # tested and flagged, then merged
    assert c["cells"]["coin_side:SOLUSDT:-1"]["expected_src"] == "처음 보는 기간 전체"
    assert c["cells"]["coin_side:SOLUSDT:-1"]["expected"] == pytest.approx(0.7497)
    assert "strategy:F5_BOX_RSI" not in cells
    reg = next(x for x in c["flagged"] if x["kind"] == "strategy_reg5")
    assert reg["question"] == ("BTC 4시간 '약상승' 장세에서 N03_ADX_GC 15분 끄기: 2020-24와 2025-26 둘 다 좋아지나? "
                               "거래 수는 얼마나 줄어드나?") and reg["label"] == "N03_ADX_GC 15분 · BTC 4시간 '약상승' 장세"
    # a flagged strategy: its own cells are kept only when more lopsided than it (here the same trades: dropped)
    assert cells["strategy:F10_M2022"]["p"] == pytest.approx(LI.binom_cdf(4, 10, 0.7475))
    assert "strategy_coin:F10_M2022:BTCUSDT" in c["cells"]
    assert not any(k.startswith(("strategy_coin:F10_M2022", "strategy_side:F10_M2022", "strategy_reg5:F10_M2022"))
                   for k in cells)
    assert cells["strategy:F10_M2022"]["question"].startswith("F10_M2022 1시간 손보기(손절·진입 방식 바꾸기, 또는 끄기): ")
    # fewer than 8 trades: not even tested; 8/10 against 84%: tested, not a candidate
    assert "strategy_coin:N03_ADX_GC:DOGEUSDT" not in c["cells"] and "coin_side:DOGEUSDT:1" not in c["cells"]
    assert "strategy_side:N03_ADX_GC:-1" in c["cells"] and "strategy_side:N03_ADX_GC:-1" not in cells
    assert "strategy:N03_ADX_GC" in c["cells"] and "strategy:N03_ADX_GC" not in cells
    # the multiple-testing note: every cell tested, about 5% by luck, the ones that survive 0.05 / tested
    assert c["tested"] == len(c["cells"]) >= 20 and c["luck"] == pytest.approx(c["tested"] * 0.05)
    assert all(x["family"] == c["tested"] and x["survives"] == (x["p"] < 0.05 / c["tested"]) for x in c["flagged"])
    assert not sol["survives"] and not cells["strategy:F10_M2022"]["survives"]
    assert [x["p"] for x in c["flagged"]] == sorted(x["p"] for x in c["flagged"])
    bad = LI.gather(src(tmp_path, World().add(9, wins=5, losses=15).db(tmp_path / "b.db")))    # 5/20: p ~ 4e-6
    loud = LI.find_candidates(bad["trades"], bad["ref"])
    assert next(x for x in loud["flagged"] if x["cell"] == "strategy:F10_M2022")["survives"]


def test_the_fixed_rules_are_never_candidates(monkeypatch, tmp_path):
    assert set(LI.CELL_KINDS) == {"strategy", "strategy_coin", "strategy_reg5", "strategy_side", "coin_side", "hb"}
    g = LI.gather(src(tmp_path, _cell_world().db(tmp_path / "live-ac.db")))
    real = LI.cells_of

    def more(trades):
        out = real(trades)
        out[("leverage", (40,))] = list(trades)               # a cell that would change a fixed rule
        out[("coin", ("SOLUSDT",))] = list(trades)            # dropping a coin (the 6 coins are fixed)
        out[("weekend", (1,))] = list(trades)
        return out
    monkeypatch.setattr(LI, "cells_of", more)
    c = LI.find_candidates([dict(t, pnl=-1.0) for t in g["trades"]], g["ref"])
    assert c["flagged"] and all(x["kind"] in LI.CELL_KINDS for x in c["flagged"])
    assert not any(x["cell"].startswith(("leverage", "coin:", "weekend")) for x in c["cells"].values())
    assert "레버리지" in LI.FIXED_RULES and "코인 6개" in LI.FIXED_RULES and "증거금 40%" in LI.FIXED_RULES


# ====================================================================== the ledger
def _ledger_world(extra_sol=0):
    w = _cell_world()
    if extra_sol:
        w.add(29, wins=extra_sol // 2 - 2, losses=extra_sol - extra_sol // 2 + 2, symbol=SOL, side=-1)
    return w


def test_weekly_adds_new_cells_once_and_refreshes_their_evidence(tmp_path):
    paper = _ledger_world().db(tmp_path / "live-ac.db")
    s = src(tmp_path, paper)
    n = ListNotifier()
    out = LI.run_weekly(s, now_ms=NOW, notifier=n)
    assert out["new"] and len(n.messages) == 1 and out["sent"] is True
    conn = sqlite3.connect(s.db)
    rows = conn.execute("SELECT id, cell, status, question, n, wins, found FROM ledger ORDER BY id").fetchall()
    assert {r[2] for r in rows} == {"발견"} and all(LI.QUESTION_TAIL in r[3] for r in rows)
    assert {r[6] for r in rows} == {"2026-10-26"}
    sol = next(r for r in rows if r[1] == "strategy_coin:F5_BOX_RSI:SOLUSDT")
    assert (sol[4], sol[5]) == (10, 3)
    log = conn.execute("SELECT old, new, who FROM ledger_log WHERE item = ?", (sol[0],)).fetchall()
    assert log == [(None, "발견", "liveimprove")]
    conn.close()
    # a week later, more SOL shorts: no second row, the evidence of the row is refreshed
    paper2 = _ledger_world(extra_sol=10).db(tmp_path / "live-ac2.db")
    out2 = LI.run_weekly(src(tmp_path, paper2), now_ms=NOW + 7 * DAY, notifier=ListNotifier())
    conn = sqlite3.connect(s.db)
    assert conn.execute("SELECT COUNT(*) FROM ledger WHERE cell = ?",
                        ("strategy_coin:F5_BOX_RSI:SOLUSDT",)).fetchone()[0] == 1
    item = next(r for r in LI.ledger_rows(conn) if r["cell"] == "strategy_coin:F5_BOX_RSI:SOLUSDT")
    assert (item["n"], item["wins"]) == (10, 3) and (item["latest"]["n"], item["latest"]["wins"]) == (20, 6)
    assert LI.rule_a(item["latest"]) and item["status"] == "발견"                  # a status never moves by itself
    assert "strategy_coin:F5_BOX_RSI:SOLUSDT" not in {c["cell"] for c in out2["new"]}
    weeks = conn.execute("SELECT week, trades, tested FROM weeks ORDER BY week").fetchall()
    assert [w[0] for w in weeks] == ["2026-10-26", "2026-11-02"] and weeks[1][1] == 97
    snap = conn.execute("SELECT COUNT(*) FROM snapshots WHERE week = '2026-10-26' AND cut = 'strategy'").fetchone()[0]
    assert snap == 27
    assert conn.execute("SELECT status, n, wins FROM snapshots WHERE week = '2026-10-26' "
                        "AND cut = 'overall'").fetchone() == ("기대 안", 87, 65)
    m = conn.execute("SELECT label, n, honest_win, honest_src FROM snapshots WHERE week = '2026-10-26' "
                     "AND cut = 'member' "
                     "AND cell = '30'").fetchone()                  # the paper bot's setting 30 = reference key 29
    assert m[0] == "F5_BOX_RSI 30분 · ATR 3배 · 즉시 진입 (#30)" and m[1] == 20 and m[3] == "이 매매법 79번"
    conn.close()


def test_ledger_status_moves_only_by_hand_along_the_flow(tmp_path):
    s = src(tmp_path, _ledger_world(extra_sol=10).db(tmp_path / "live-ac.db"))
    LI.run_weekly(s, now_ms=NOW, notifier=ListNotifier())
    conn = LI.open_out(s.db)
    item = next(r for r in LI.ledger_rows(conn) if r["cell"] == "strategy_coin:F5_BOX_RSI:SOLUSDT")
    i = item["id"]
    with pytest.raises(LI.LedgerError, match="메모"):
        LI.set_status(conn, i, "백테스트 시험", "  ", now_ms=NOW)
    with pytest.raises(LI.LedgerError, match="'발견' 다음은 백테스트 시험, 기각만 됩니다"):
        LI.set_status(conn, i, "채택", "좋아 보임", now_ms=NOW)
    with pytest.raises(LI.LedgerError, match="상태는"):
        LI.set_status(conn, i, "끄기", "x", now_ms=NOW)
    with pytest.raises(LI.LedgerError, match="#999"):
        LI.set_status(conn, 999, "기각", "x", now_ms=NOW)
    assert LI.set_status(conn, i, "backtest", "2020-24/2025-26 돌림", now_ms=NOW + DAY, who="두 분")["new"] == "백테스트 시험"
    with pytest.raises(LI.LedgerError, match="규칙 b"):
        LI.set_status(conn, i, "그림자 시험", "둘 다 좋아짐", now_ms=NOW + 2 * DAY)
    LI.set_status(conn, i, "그림자 시험", "둘 다 좋아짐, 거래 -12%", now_ms=NOW + 2 * DAY, backtest_ok=True)
    with pytest.raises(LI.LedgerError) as e:
        LI.set_status(conn, i, "채택", "그림자 괜찮음", now_ms=NOW + 5 * DAY)
    assert "(c) 그림자 결과 확인 없음" in str(e.value) and "(a)" not in str(e.value) and "(b)" not in str(e.value)
    with pytest.raises(LI.LedgerError, match=r"\(c\) 그림자 시험 3일째"):
        LI.set_status(conn, i, "채택", "그림자 괜찮음", now_ms=NOW + 5 * DAY, shadow_ok=True)
    LI.set_status(conn, i, "채택", "그림자 22번, 지금 봇과 같음", now_ms=NOW + 5 * DAY, shadow_ok=True, shadow_trades=22)
    with pytest.raises(LI.LedgerError, match="없음\\(끝난 항목\\)"):
        LI.set_status(conn, i, "기각", "취소", now_ms=NOW + 6 * DAY)
    got = next(r for r in LI.ledger_rows(conn) if r["id"] == i)
    assert got["status"] == "채택" and got["rule_b"] == 1 and got["rule_c"] == 1
    log = conn.execute("SELECT day, old, new, note, who FROM ledger_log WHERE item = ? ORDER BY id", (i,)).fetchall()
    assert [(o, n) for _d, o, n, _note, _w in log] == [(None, "발견"), ("발견", "백테스트 시험"),
                                                       ("백테스트 시험", "그림자 시험"), ("그림자 시험", "채택")]
    assert log[1][0] == "2026-10-27" and log[1][4] == "두 분"
    conn.close()


def test_adoption_needs_live_evidence_of_20_trades(tmp_path):
    s = src(tmp_path, _ledger_world().db(tmp_path / "live-ac.db"))       # SOL short: 10 trades only
    LI.run_weekly(s, now_ms=NOW, notifier=ListNotifier())
    conn = LI.open_out(s.db)
    i = next(r["id"] for r in LI.ledger_rows(conn) if r["cell"] == "strategy_coin:F5_BOX_RSI:SOLUSDT")
    LI.set_status(conn, i, "백테스트 시험", "시작", now_ms=NOW)
    LI.set_status(conn, i, "그림자 시험", "둘 다 좋아짐", now_ms=NOW, backtest_ok=True)
    with pytest.raises(LI.LedgerError, match=r"\(a\) 실거래 증거 부족: 지금 10번 3승"):
        LI.set_status(conn, i, "채택", "x", now_ms=NOW + 15 * DAY, shadow_ok=True)
    LI.set_status(conn, i, "기각", "증거 부족", now_ms=NOW + 15 * DAY)
    LI.set_status(conn, i, "reopen", "다시 봄", now_ms=NOW + 16 * DAY)
    got = next(r for r in LI.ledger_rows(conn) if r["id"] == i)
    assert got["status"] == "발견" and got["rule_b"] == 0 and got["note"] == "다시 봄"
    conn.close()


def test_ledger_commands(tmp_path, capsys):
    s = src(tmp_path, _ledger_world().db(tmp_path / "live-ac.db"))
    assert LI.main(["ledger", "list", "--db", s.db]) == 0
    assert "개선 후보 장부: 아직 비어 있음" in capsys.readouterr().out and not os.path.exists(s.db)
    assert LI.main(["ledger", "set", "1", "--status", "기각", "--note", "x", "--db", s.db]) == 1
    LI.run_weekly(s, now_ms=NOW, notifier=ListNotifier())
    capsys.readouterr()
    assert LI.main(["ledger", "set", "1", "--status", "채택", "--note", "x", "--db", s.db]) == 2
    assert "바꾸지 않았습니다" in capsys.readouterr().out
    assert LI.main(["ledger", "set", "1", "--status", "백테스트 시험", "--note", "돌려 봄", "--db", s.db]) == 0
    assert "#1: 발견 → 백테스트 시험" in capsys.readouterr().out
    assert LI.main(["ledger", "list", "--db", s.db]) == 0
    out = capsys.readouterr().out
    assert "#1 [백테스트 시험]" in out and "질문: " in out and "--backtest-ok" in out
    assert "(a) 실거래에서 그 칸 거래 20번 이상, p<0.05" in out and "자동으로 바뀌는 것은 없습니다" in out


# ====================================================================== 3. weekly
def test_quiet_weekly_message(tmp_path):
    s = src(tmp_path, _ledger_world().db(tmp_path / "live-ac.db"))
    n = ListNotifier()
    out = LI.run_weekly(s, now_ms=NOW, notifier=n)
    level, text = n.messages[0]
    assert level == INFO and out["level"] == INFO and not out["bad"]
    lines = text.splitlines()
    assert lines[0] == "📊 주간 성적표 · 10/19~10/25"                    # emoji + what + the week
    assert lines[1].startswith("시작(10/19 10:00)부터: 65/87 (75%) · 손익 -$")
    assert "기대보다 못하는 매매법" in text and "- F10_M2022 1시간: 4/10 (40%) · 손익 " in text and "주의(p=0.021)" in text
    assert "기대보다 잘하는 매매법" in text and "- N03_ADX_GC 15분·30분: 48/57 (84%)" in text
    assert LI.LUCK_NOTE in text and "운만으로도 약" in text
    assert "새 개선 후보" in text and "질문: F5_BOX_RSI 30분 SOL 끄기" in text
    assert "@" not in text and "~abc" not in text                       # never an internal setting label or hash
    assert "(c) 바꾼 그림자 페이퍼 봇이 2주 이상 또는 거래 20번 이상 돌고" in text
    assert "자동으로 바뀌는 것은 없습니다. 두 분이 정합니다." in text and len(text) <= 3900
    lvl, body = telegram_text(level, text)                      # the notifier's wording keeps the message as it is
    assert lvl == INFO and "질문: F5_BOX_RSI 30분 SOL 끄기" in body and "F10_M2022 1시간: 4/10 (40%)" in body
    assert body.startswith("📊 주간 성적표 · 10/19~10/25")                # no second mark in front
    # the next week, the items are open ledger items with their next step
    n2 = ListNotifier()
    LI.run_weekly(s, now_ms=NOW + 7 * DAY, notifier=n2)
    t2 = n2.messages[0][1]
    assert t2.startswith("📊 주간 성적표 · 10/26~11/1\n이번 주 페이퍼: 0/0 · 손익 +$0.00\n")
    assert "새 개선 후보 0개" in t2 and "열린 장부" in t2 and "다음: 백테스트로 질문 확인(2020-24, 2025-26 따로)" in t2


def test_loud_only_when_something_is_surely_bad(tmp_path):
    w = World().add(9, wins=5, losses=15, symbol=BTC)            # F10_M2022 5/20 against 75%: p ~ 4e-6
    n = ListNotifier()
    out = LI.run_weekly(src(tmp_path, w.db(tmp_path / "live-ac.db")), now_ms=NOW, notifier=n)
    level, text = n.messages[0]
    assert level == CRITICAL and out["bad"]
    assert text.splitlines()[0] == "🚨 주간 성적표 · 10/19~10/25 · 확실히 나쁨 2개"
    assert "- 전체: 5/20 (25%) · 기대 75% · p<0.0001" in text
    assert "- F10_M2022 1시간: 5/20 (25%) · 기대 75% · p<0.0001" in text
    assert telegram_text(level, text)[1].startswith("🚨 ")
    # a coin that is "확실히 나쁨" in its own small table (0.05 / 6) does not ring: only the account and the strategies
    w2 = (World().add(29, wins=3, losses=7, symbol=SOL, side=-1).add(11, wins=30, symbol=BTC)
          .add(4, wins=10, symbol=ETH))
    g = LI.gather(src(tmp_path, w2.db(tmp_path / "b.db")))
    card = LI.scorecard(g["trades"], g["ref"], g["follow"])
    assert row(card, "coin", SOL)["status"] == LI.BAD and not LI.bad_rows(card)
    n2 = ListNotifier()
    LI.run_weekly(src(tmp_path, tmp_path / "b.db"), now_ms=NOW, notifier=n2)
    assert n2.messages[0][0] == INFO


def test_the_message_goes_only_through_the_livecheck_notifier(tmp_path, monkeypatch):
    """The live chat and the live sound rules live in livecheck._notifier: the weekly message takes that helper."""
    got = ListNotifier()
    monkeypatch.setattr(LC, "_notifier", lambda: got)
    out = LI.run_weekly(src(tmp_path, _ledger_world().db(tmp_path / "live-ac.db")), now_ms=NOW)
    assert out["sent"] is True and got.messages == [(INFO, out["text"])]
    text = Path(LI.__file__).read_text(encoding="utf-8")
    assert "TelegramNotifier" not in text and "from .live import" not in text and "LC._notifier()" in text


def test_preview_prints_the_first_monday_message_and_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    quiet, loud = LI.preview(), LI.preview(loud=True)
    assert quiet["level"] == INFO and quiet["text"].splitlines()[0] == "📊 주간 성적표 · 10/19~10/25"
    assert "- F5_BOX_RSI 30분: 6/12 (50%) · 손익 -$696.00" in quiet["text"]
    assert "- 바이비트: 따라감 " in quiet["text"] and "#1 F5_BOX_RSI 30분 SOL: 2/8 (25%)" in quiet["text"]
    assert loud["level"] == CRITICAL and loud["text"].splitlines()[:2] == [
        "🚨 주간 성적표 · 10/19~10/25 · 확실히 나쁨 1개", "- F10_M2022 1시간: 3/14 (21%) · 기대 75% · p<0.0001"]
    for out in (quiet, loud):
        assert "@" not in out["text"] and len(out["text"]) <= 3900
        assert re.search(r"\d+/\d+ \(\d+%\)", out["text"]) and re.search(r"[+-]\$\d[\d,]*\.\d\d", out["text"])
    assert LI.main(["preview", "--loud"]) == 0
    printed = capsys.readouterr().out
    assert printed.startswith("[미리 보기: 손으로 만든 한 주 · CRITICAL · 보내지도 쓰지도 않음]\n🚨 주간 성적표")
    assert os.listdir(tmp_path) == []


def test_dry_run_writes_nothing_and_sends_nothing(tmp_path, capsys):
    paper = _ledger_world().db(tmp_path / "live-ac.db")
    before = (sorted(os.listdir(tmp_path)), _sha(paper))
    s = src(tmp_path, paper)
    n = ListNotifier()
    out = LI.run_weekly(s, now_ms=NOW, notifier=n, dry_run=True)
    assert not n.messages and out["sent"] is None and out["new"] and all(c["id"] == "새" for c in out["new"])
    assert out["text"].startswith("📊 주간 성적표 · 10/19~10/25\n") and "- (새) " in out["text"]
    cand, new, _ledger = LI.run_candidates(s, now_ms=NOW, dry_run=True)
    assert new and cand["flagged"]
    for argv in (["weekly", "--dry-run"], ["candidates", "--dry-run"], ["score", "--by", "all"]):
        assert LI.main(argv + ["--db", s.db, "--paper-db", paper, "--expected", str(LI.EXPECTED)]) == 0
    printed = capsys.readouterr().out
    assert "(--dry-run: 보내지도 쓰지도 않았습니다)" in printed and "(--dry-run: 장부에 쓰지 않았습니다)" in printed
    assert "[세팅별]" in printed and "[한국 시간 4시간대별]" in printed and "읽는 법" in printed
    assert (sorted(os.listdir(tmp_path)), _sha(paper)) == before and not os.path.exists(s.db)
    # an existing ledger is read, never written, by a dry run
    LI.run_weekly(s, now_ms=NOW, notifier=ListNotifier())
    led = _sha(s.db)
    out = LI.run_weekly(s, now_ms=NOW + 7 * DAY, notifier=n, dry_run=True)
    assert _sha(s.db) == led and not out["new"] and "열린 장부" in out["text"] and not n.messages


def test_the_bots_databases_are_opened_read_only(tmp_path):
    paper = _ledger_world().db(tmp_path / "live-ac.db")
    ex = exec_db(tmp_path / "bybit.db", [{"key": "k", "symbol": BTC, "side": 1, "qty": 1.0, "leverage": 40,
                                          "entry_ts": T0, "entry_price": 100.0, "exit_ts": T0 + H1, "pnl": 1.0}])
    conn = LI.open_ro(paper)
    assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO alerts VALUES (1, 'INFO', 'x')")
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("CREATE TABLE x (a)")
    conn.close()
    assert LI.open_ro(str(tmp_path / "missing.db")) is None and not os.path.exists(tmp_path / "missing.db")
    before = {p: _sha(p) for p in (paper, ex)}
    files = sorted(os.listdir(tmp_path))
    LI.run_weekly(LI.Sources(db=str(tmp_path / "out" / "liveimprove.db"), paper_db=paper,
                             executors=[info("bybit", ex)]), now_ms=NOW, notifier=ListNotifier())
    assert {p: _sha(p) for p in (paper, ex)} == before
    assert sorted(os.listdir(tmp_path)) == sorted(files + ["out"])          # only its own folder was added


def test_no_order_code_no_network_and_no_key_file_in_the_module():
    text = Path(LI.__file__).read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from\s+\S*\b(executor|testnet|mainnet|risk|bybit|mexc|binance|exchange)\b\s+import|"
                         r"import\s+\S*\b(executor|testnet|mainnet|bybit|mexc|binance|urllib|requests|socket|http)\b|"
                         r"from\s+\.+\s+import\s+.*\b(executor|testnet|mainnet|risk|bybit|mexc|binance)\b)", text, re.M)
    assert "executor.env" not in text and "livereplay" not in text
    for word in ("일일 손실", "하루 손실", "$120", "budget_usd"):      # both removed on 10/19
        assert word not in text


# ====================================================================== deploy
def _unit(name: str) -> dict:
    out: dict = {}
    sec = ""
    for ln in (DEPLOY / name).read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if ln.startswith("["):
            sec = ln
            continue
        out.setdefault(sec, []).append(ln)
    return out


def test_the_weekly_unit_has_the_livecheck_hardening_and_never_the_key_file():
    from paperbot import failalert as FA
    mine, theirs = _unit("paperbot-liveimprove.service"), _unit("paperbot-livecheck.service")
    svc = mine["[Service]"]
    assert "OnFailure=paperbot-failed@%n.service" in mine["[Unit]"] and "paperbot-liveimprove.service" in FA.JOBS_KO
    for k in ("User=paperbot", "Group=paperbot", "Type=oneshot", "WorkingDirectory=/opt/crypto-bot-research",
              "EnvironmentFile=/etc/paperbot/live.env", "NoNewPrivileges=yes", "PrivateTmp=yes", "ProtectSystem=strict",
              "ProtectHome=yes", "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6", "Nice=15", "CPUWeight=10",
              "IOSchedulingClass=idle"):
        assert k in svc and k in theirs["[Service]"], k
    assert "ExecStart=/opt/paperbot/venv/bin/python -m paperbot.liveimprove weekly" in svc
    assert any(ln.startswith("MemoryMax=") for ln in svc) and any(ln.startswith("TimeoutStartSec=") for ln in svc)
    unset = next(ln for ln in svc if ln.startswith("UnsetEnvironment=")).split("=", 1)[1].split()
    assert {"BINANCE_API_KEY", "BINANCE_API_SECRET"} <= set(unset)            # no exchange call: no key
    assert not {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_CRITICAL"} & set(unset)  # the one message goes out

    def paths(u, k):
        return next(ln for ln in u["[Service]"] if ln.startswith(k + "=")).split("=", 1)[1].split()
    assert paths(mine, "ReadWritePaths") == ["/var/lib/paperbot"]
    for k in ("ReadOnlyPaths", "InaccessiblePaths"):
        assert set(paths(theirs, k)) <= set(paths(mine, k)), k
    assert "-/var/lib/paperbot/combo/live-ac.db" in paths(mine, "ReadOnlyPaths")
    assert "-/etc/paperbot/executor.env" in paths(mine, "InaccessiblePaths")
    used = [ln for lines in mine.values() for ln in lines if "executor.env" in ln]
    assert len(used) == 1 and used[0].startswith("InaccessiblePaths=")
    t = _unit("paperbot-liveimprove.timer")
    assert "OnCalendar=Mon *-*-* 00:30:00 UTC" in t["[Timer]"] and "Persistent=true" in t["[Timer]"]
    assert "WantedBy=timers.target" in t["[Install]"]
    inst = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    block = re.search(r"for u in paperbot-liveimprove\.service paperbot-liveimprove\.timer; do\s+"
                      r"install -m 644 \"\$APP/deploy/\$u\" /etc/systemd/system/\$u\s+done", inst)
    assert block and "systemctl enable --now paperbot-liveimprove.timer" in inst
    assert inst.index("for t in paperbot-livecheck.timer") < block.start()
