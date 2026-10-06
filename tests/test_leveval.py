"""Leverage rule B's pre-registered evaluation (docs/levrule-eval.md, agents/leveval.py), the per-entry 'why this
leverage' (paperbot/levwhy.py), and where they are shown: the Thursday rr packet, the Friday risk packet, the
checkpoint meeting, the specialists, the dashboard ('좋은 자리 vs 보통', '그림자 비교', the restart banner, the
positions / account views) and the Telegram entry line. Also: the sizing itself is unchanged (no trading file is
touched by any of this)."""

import hashlib
import json
import os
import sqlite3
import sys

import numpy as np
import pytest

from paperbot import levwhy as LW
from paperbot.agents import leveval as LV
from paperbot.agents import packets3 as P3
from paperbot.agents import riskreward as RR
from paperbot.agents import rooms as RM
from paperbot.agents import rooms_db as R
from paperbot.config import v3_settings
from paperbot.margin import Brackets
from paperbot.models import TradeRecord
from paperbot.sizing import size_position
from paperbot.store3 import Store3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAY = 86_400_000
HOUR = 3_600_000
START = 1_791_158_400_000            # 2026-10-05 00:00 UTC
UNTIL = START + 30 * DAY             # the day-30 checkpoint (checkpoint_ts(START, 1))


# ---------------------------------------------------------------- synthetic paper3.db
def _trade(store, aid, group, lev, r, entry, exit_=None, margin=100.0, tier=None):
    strat, tf = aid.split("@")
    pnl = r * margin * lev
    store.trade(aid, TradeRecord(
        strategy_id=strat, symbol="BTCUSDT", timeframe=tf, side=1, signal_ts=entry - 1, entry_time=entry,
        entry_price=100.0, exit_time=exit_ if exit_ is not None else entry + HOUR, exit_price=100.0,
        exit_reason="LOCK" if pnl > 0 else "SL", qty=1.0, leverage=lev, tier=tier or group, margin=margin,
        stop_price=99.0, tp_price=0.0, liq_price=90.0, fees=0.1, funding=0.0, pnl=pnl, roe=pnl / margin,
        price_move=0.0, mae_price=99.5, mfe_price=100.5, equity_after=5000.0 + pnl, score=0.0, context={}))


def make_db(path, strat=(0.002, -0.001), flips=(0.0, 0.0), n=3, weeks=5, cells=("S1@15m", "S1@1h", "S2@15m"),
            flip_cells=("RANDOM_1@15m", "RANDOM_2@1h"), week_sign=None, seed=1):
    """Each cell gets ``n`` best and ``n`` normal trades per week for ``weeks`` weeks (r around the given means,
    small noise); ``week_sign(w)`` flips the strategies' best mean in week w."""
    store = Store3(path)
    for a in cells:
        store.add_account(a, a.split("@")[0], a.split("@")[1], "strategy", START, "paper-v3")
    for a in flip_cells:
        store.add_account(a, a.split("@")[0], a.split("@")[1], "random", START, "paper-v3")
    store.put_state("run", START, {"taker_fee": 0.0005, "initial_equity": 5000.0})
    rng = np.random.default_rng(seed)
    for w in range(weeks):
        for k in range(n):
            t = START + w * 7 * DAY + (k + 1) * 6 * HOUR
            for a in cells:
                sb = strat[0] * (week_sign(w) if week_sign else 1.0)
                _trade(store, a, "best", 50, sb + rng.normal(0, 1e-4), t)
                _trade(store, a, "normal", 30, strat[1] + rng.normal(0, 1e-4), t + HOUR)
            for a in flip_cells:
                _trade(store, a, "best", 50, flips[0] + rng.normal(0, 1e-4), t)
                _trade(store, a, "normal", 30, flips[1] + rng.normal(0, 1e-4), t + HOUR)
    store.commit()
    return store


def ro(path):
    return R.open_ro(path)


# ---------------------------------------------------------------- the pre-registered document
def test_prereg_document_is_hashed_registered_and_matches_the_code():
    from paperbot.launchcheck import RULES_SUMS
    from paperbot.runinfo import RULES_FILES
    assert "docs/levrule-eval.md" in RULES_FILES and "docs/levrule-eval.sha256" in RULES_SUMS
    with open(os.path.join(ROOT, "docs", "levrule-eval.sha256")) as fh:
        want, rel = fh.read().split()
    assert rel == "docs/levrule-eval.md"
    with open(os.path.join(ROOT, rel), "rb") as fh:
        raw = fh.read()
    assert hashlib.sha256(raw).hexdigest() == want
    doc = raw.decode("utf-8")
    # the numbers the code uses are the document's
    assert (LV.MIN_TRADES, LV.ALPHA, LV.N_BOOT, LV.SEED, LV.BLOCK_DAYS) == (10, 0.10, 10_000, 20261004, 7)
    for s in ("10건 이상", "p_s ≤ 0.10", "D_s > D_c", "10,000번, 시드 20261004", "7일씩", "20배·증거금 20% 고정",
              "30일 판정 전 결론 없음", "이 문서의 방법으로만 평가", "창 중간에는 아무것도 바꾸지 않습니다",
              "손익 ÷ (증거금 × 레버리지)", "levrule_eval"):
        assert s in doc, s
    assert LV.DOC == "docs/levrule-eval.md"


# ---------------------------------------------------------------- the evaluation on synthetic data
def test_metric_window_and_groups(tmp_path):
    p = str(tmp_path / "paper3.db")
    store = make_db(p, n=1, weeks=1, cells=("S1@15m",), flip_cells=())
    _trade(store, "S1@15m", "best", 40, 0.01, START - HOUR)                 # entered before the start: out
    _trade(store, "S1@15m", "best", 40, 0.01, UNTIL - HOUR, exit_=UNTIL + HOUR)   # still open at day 30: out
    _trade(store, "S1@15m", "base", 20, 0.01, START + DAY)                  # the old tier walk's name: out
    store.commit()
    rows = LV.trade_rows(ro(p), START, UNTIL)
    assert len(rows) == 2 and {r["group"] for r in rows} == {"best", "normal"}
    b = [r for r in rows if r["group"] == "best"][0]
    assert b["r"] == pytest.approx(b["roe"] / 50) and b["lev"] == 50          # r = pnl / (margin x lev) = ROE / lev
    assert b["eq"] == pytest.approx((b["r"] * 100 * 50) / 5000.0, rel=1e-6)   # P&L on equity before the trade


def test_keep_when_best_beats_normal_and_the_coin_flips(tmp_path):
    p = str(tmp_path / "paper3.db")
    make_db(p, strat=(0.002, -0.001), flips=(0.0, 0.0))
    ev = LV.levrule_eval(ro(p), now_ms=UNTIL + HOUR)
    assert ev["status"] == "decided" and ev["decision"] == "keep" and "유지" in ev["decision_ko"]
    assert ev["cells"]["strategy_eligible"] == 3 and ev["cells"]["coin_flips_eligible"] == 2
    assert ev["d_s"] == pytest.approx(0.003, abs=2e-4) and abs(ev["d_c"]) < 2e-4
    assert ev["p_s"] == pytest.approx(1 / 10_001, abs=1e-6) and ev["boot"]["blocks"] == 5
    assert ev["conditions"] == {"a_best_beats_normal": True, "b_beats_coin_flips": True, "alpha": 0.10}
    g = ev["groups"]["best"]["strategy"]
    assert g["trades"] == 45 and g["win_rate"] == 1.0 and g["mean_r"] == pytest.approx(0.002, abs=1e-4)
    assert ev["groups"]["best"]["strategy_by_leverage"] == {"50": [45, pytest.approx(0.002, abs=1e-4)]}
    assert ev["groups"]["best"]["coin_flips_at_strategy_mix"]["coverage"] == 1.0
    assert set(ev["cell_rows"]) == {"S1@15m", "S1@1h", "S2@15m"}
    assert ev["leverage_mix"]["best"]["by_leverage"] == {"50": 45}
    # deterministic: the same data, the same p
    assert LV.levrule_eval(ro(p), now_ms=UNTIL + DAY)["p_s"] == ev["p_s"]


def test_fixed20_when_best_is_worse(tmp_path):
    p = str(tmp_path / "paper3.db")
    make_db(p, strat=(-0.001, 0.001))
    ev = LV.levrule_eval(ro(p), now_ms=UNTIL)
    assert ev["decision"] == "fixed20" and ev["d_s"] < 0 and ev["p_s"] > 0.9
    assert ev["conditions"]["a_best_beats_normal"] is False and "20배" in ev["status_ko"]


def test_fixed20_when_the_coin_flips_show_the_same_or_more(tmp_path):
    p = str(tmp_path / "paper3.db")
    make_db(p, strat=(0.002, -0.001), flips=(0.004, -0.001))
    ev = LV.levrule_eval(ro(p), now_ms=UNTIL)
    assert ev["conditions"] == {"a_best_beats_normal": True, "b_beats_coin_flips": False, "alpha": 0.10}
    assert ev["decision"] == "fixed20" and ev["did"] < 0


def test_fixed20_when_the_difference_is_not_significant(tmp_path):
    """Positive on average but carried by some weeks only: the week-block bootstrap p is above 0.10."""
    p = str(tmp_path / "paper3.db")
    make_db(p, strat=(0.004, 0.0), week_sign=lambda w: 1.0 if w % 2 == 0 else -1.2)
    ev = LV.levrule_eval(ro(p), now_ms=UNTIL)
    assert ev["d_s"] > 0 and ev["p_s"] > LV.ALPHA and ev["decision"] == "fixed20"


def test_no_eligible_cell_and_no_coin_flip_baseline(tmp_path):
    p = str(tmp_path / "paper3.db")
    make_db(p, n=1, weeks=9)                                # 9 trades a group per cell: under 10
    ev = LV.levrule_eval(ro(p), now_ms=UNTIL)
    assert ev["cells"]["strategy_eligible"] == 0 and ev["d_s"] is None and ev["decision"] == "fixed20"
    p2 = str(tmp_path / "p2.db")
    make_db(p2, n=2, weeks=5, flip_cells=())                # 10 a group: eligible; no coin flips at all
    ev2 = LV.levrule_eval(ro(p2), now_ms=UNTIL)
    assert ev2["cells"]["strategy_eligible"] == 3 and ev2["d_c"] is None
    assert ev2["conditions"]["a_best_beats_normal"] is True and ev2["decision"] == "fixed20"   # (나) not met


def test_interim_before_day_30_has_no_decision(tmp_path):
    p = str(tmp_path / "paper3.db")
    make_db(p)
    ev = LV.levrule_eval(ro(p), now_ms=START + 10 * DAY)
    assert ev["status"] == "interim" and ev["status_ko"] == "30일 판정 전 결론 없음"
    assert "decision" not in ev and "decision_ko" not in ev
    assert ev["window"]["to"] == START + 10 * DAY and ev["trades"]["strategy"] == 36          # weeks 0 and 1
    assert all(t["entry"] < START + 10 * DAY for t in LV.trade_rows(ro(p), START, START + 10 * DAY))


def test_no_run_and_no_database():
    assert LV.levrule_eval(None)["error"]
    c = sqlite3.connect(":memory:")
    assert LV.levrule_eval(c, now_ms=UNTIL)["status"] == "no_run"
    assert LV.compact(LV.levrule_eval(c, now_ms=UNTIL))["status"] == "no_run"
    assert LV.strategy_line(c, "S1", UNTIL) == ""


def test_p_value_counts_draws_at_or_below_zero():
    assert LV.p_one_sided(np.array([0.1, 0.2, -0.1, np.nan])) == pytest.approx(3 / 5)
    assert LV.decide(0.001, 0.10, 0.0)["keep"] is True and LV.decide(0.001, 0.1001, 0.0)["keep"] is False
    assert LV.decide(0.001, 0.01, None)["keep"] is False and LV.decide(None, None, None)["decision"] == "fixed20"


def test_packet_forms_stay_small_with_every_cell(tmp_path):
    p = str(tmp_path / "paper3.db")
    cells = tuple(f"S{i}@{tf}" for i in range(36) for tf in ("15m", "30m", "1h", "4h"))
    make_db(p, n=2, weeks=5, cells=cells)
    ev = LV.levrule_eval(ro(p), now_ms=UNTIL, n_boot=2000)
    assert ev["cells"]["strategy_eligible"] == 144
    assert len(json.dumps(LV.compact(ev), ensure_ascii=False)) < 1_000
    assert len(json.dumps(LV.rr_section(ev), ensure_ascii=False)) < 4_500 and len(LV.rr_section(ev)["cell_rows"]) == 12
    assert len(json.dumps(LV.meeting_section(ev), ensure_ascii=False)) < 2_000
    line = LV.strategy_line(ro(p), "S3", START + 10 * DAY)
    assert line.startswith("좋은 자리 ") and "보통 " in line and "30일 판정 전 결론 없음" in line and len(line) < 200


# ---------------------------------------------------------------- why this leverage
def test_reasons_of_the_real_sizing_are_classified():
    s, b = v3_settings(), Brackets.example()
    d = size_position(s, 5000.0, 1, 100.0, 98.0, "best", b, atr=0.3, qty_step=0.001, min_notional=5.0)
    rej = LW.parse_downgrades(d.reasons)
    assert [(r["lev"], r["code"]) for r in rej] == [(50, "bracket"), (40, "bracket"), (30, "loss_cap")]
    d = size_position(s, 5000.0, 1, 100.0, 95.0, "normal", b, atr=0.3, qty_step=0.001, min_notional=5.0)
    assert [r["code"] for r in LW.parse_downgrades(d.reasons)] == ["liq", "liq"]
    d = size_position(s, 5000.0, 1, 100.0, 99.0, "normal", b, atr=0.3, qty_step=0.001, min_notional=1e12)
    assert {r["code"] for r in LW.parse_downgrades(d.reasons)} == {"min_size"}
    assert LW.reason_code("??") == "other" and LW.parse_downgrades(None) == [] and LW.parse_downgrades(["junk"]) == []


def test_explain_short_line_and_mix():
    w = LW.explain("best", 30, ["best/50x: stop loss 900 > 15% of equity", "best/40x: stop 1 too close to liq 2"])
    assert w["group_ko"] == "좋은 자리" and w["tried"] == [50, 40, 30]
    assert w["short_ko"] == "50배 불가: 손절 손실 > 자금 15% · 40배 불가: 손절이 청산가에 너무 가까움 → 30배"
    assert LW.explain("normal", 30, [])["short_ko"] == "첫 후보 30배 그대로"
    assert "기록 못 찾음" in LW.explain("best", 30, None)["short_ko"]
    assert LW.first_reason_ko(["best/50x: bracket allows 25x", "best/40x: bracket allows 25x"], 30) == \
        "50배 불가: 거래소 구간 한도 · 40배 불가: 거래소 구간 한도 → 30배"
    assert LW.first_reason_ko([], 50) == "" and LW.first_reason_ko(None, 30) == ""
    m = LW.mix([w, LW.explain("best", 50, []), LW.explain("best", 20, None)])
    assert m["by_leverage"] == {"50": 1, "30": 1, "20": 1}
    assert m["why_lower"] == {"30": {"loss_cap": 1}, "20": {"unknown": 1}}
    # a coin flip's group is the seeded draw; a strategy without strength has no score
    cf = LW.explain(None, 30, [], {"strategy_id": "RANDOM_1", "timeframe": "15m", "symbol": "BTCUSDT", "ts": 0, "meta": {}})
    assert cf["source"] == "coin_flip" and cf["group"] in ("best", "normal") and cf["p_best"] > 0
    q = LW.explain(None, 30, [], {"strategy_id": "X", "timeframe": "15m", "symbol": "BTCUSDT", "ts": 0, "meta": {}})
    assert q["group"] == "normal" and q["no_score"] == "no_strength" and q["score"] is None


def test_sizing_outputs_are_unchanged():
    """Golden decisions of sizing.size_position under the restarted run's rule (captured before this change;
    nothing here touches a trading file)."""
    s, b = v3_settings(), Brackets.example()
    want = {("best", 99.7): (True, "best", 30, 1500.0, 450.0, 188.901013),
            ("best", 98.0): (True, "best", 20, 1000.0, 200.0, 423.71804),
            ("best", 95.0): (False, "", 0, 0.0, 0.0, 0.0),
            ("normal", 99.0): (True, "normal", 30, 1500.0, 450.0, 503.680545),
            ("normal", 97.5): (True, "normal", 20, 1000.0, 200.0, 523.64805)}
    for (g, stop), w in want.items():
        d = size_position(s, 5000.0, 1, 100.0, stop, g, b, atr=0.3, qty_step=0.001, min_notional=5.0)
        assert (d.ok, d.tier, d.leverage, round(d.margin, 6), round(d.qty, 6), round(d.loss_at_stop, 6)) == w, (g, stop)


def test_the_engine_records_what_levwhy_reads(tmp_path):
    """A 좋은 자리 signal whose 50x / 40x fail enters lower; the ENTERED outcome's downgrades explain it, for the
    open position (engine snapshot) and for the closed trade."""
    from paperbot import Bar, Signal
    from paperbot.accounts import AccountBook
    from paperbot.config import V3_SYMBOLS
    MIN = 60_000
    store = Store3(str(tmp_path / "paper3.db"))
    book = AccountBook(v3_settings(), {s: Brackets.example() for s in V3_SYMBOLS}, store, equity_every_ms=MIN)
    book.open_accounts([{"strategy": "A", "timeframe": "15m", "kind": "strategy"}], 0)
    flat = lambda i, lo=99.95: {s: Bar(s, i * MIN, i * MIN + MIN - 1, 100.0, 100.05, lo, 100.0) for s in V3_SYMBOLS}  # noqa: E731
    book.step(0, flat(0))
    book.submit("A@15m", Signal(ts=MIN - 1, symbol="BTCUSDT", timeframe="15m", strategy_id="A", side=1,
                                stop_price=0.0, tier="best", atr=0.3, meta={"stop_dist": 2.0, "lev_group": "best"}))
    book.step(MIN, flat(1))
    store.commit()
    from paperbot.engine import engine_state
    p = engine_state(book.engines["A@15m"])["position"]          # what the runner's snapshot holds
    c = R.open_ro(str(tmp_path / "paper3.db"))
    w = LW.for_position(c, "A@15m", p)
    assert w["group"] == "best" and w["leverage"] == 20
    assert [r["lev"] for r in w["rejected"]] == [50, 40, 30] and w["short_ko"].endswith("→ 20배")
    book.step(2 * MIN, flat(2, lo=97.0))                     # the stop: the trade closes
    store.commit()
    d = json.loads(c.execute("SELECT data FROM trades").fetchone()[0])
    t = LW.for_trade(d, LW.entered_outcomes(c, "A@15m"))
    assert t["short_ko"] == w["short_ko"] and t["group_ko"] == "좋은 자리"


# ---------------------------------------------------------------- packets
def test_rr_packet_and_the_specialist_brief_carry_levrule(tmp_path):
    p = str(tmp_path / "paper3.db")
    make_db(p)
    pk = RR.rr_packet(ro(p), None, START + 10 * DAY)
    assert pk["levrule"]["status"] == "interim" and pk["levrule"]["doc"] == "docs/levrule-eval.md"
    assert pk["shadows"]["lev_curves"] == {"error": "daily3.db 없음"}
    b = RR.strategy_brief(ro(p), "S1", START + 10 * DAY)
    assert b["levrule"].startswith("좋은 자리 ") and "docs/levrule-eval.md" in b["levrule"]


def test_restart_line_for_meta():
    c = sqlite3.connect(":memory:")
    assert P3.run_restarted(None) is None and P3.run_restarted(c) is None          # no cursors table
    c.execute("CREATE TABLE cursors (k TEXT PRIMARY KEY, v TEXT)")
    assert P3.run_restarted(c) is None
    c.execute("INSERT INTO cursors VALUES (?, ?)", ("run:restarted", json.dumps(
        {"day_kst": "2026-10-04", "text_ko": "실험을 2026-10-04에 처음부터 다시 시작함 (5분봉 제외, 좋은 자리 50·40배·보통 30·20배(비중=배수%), 1분봉 8초 뒤 읽기)"})))
    line = P3.run_restarted(c)
    assert line.startswith("실험을 2026-10-04에 처음부터 다시 시작함") and "이전 실행" in line and "\n" not in line
    from paperbot import resetrun
    assert resetrun.MARKER == P3.RESTART_MARKER


@pytest.fixture
def world(tmp_path):
    from test_rooms import World
    return World(tmp_path)


def test_the_specialist_sees_the_restart_line_and_its_levrule(world):
    from test_new_meetings import tpol
    from test_rooms import NOTE, QUIET, SPEC, QueueRunner, analysis, challenge
    R.set_cursor(world.agents, "run:restarted", {"day_kst": "2026-10-04", "text_ko": "실험을 2026-10-04에 처음부터 다시 시작함"})
    world.agents.commit()
    world.losses()
    runner = QueueRunner({SPEC: [analysis(NOTE)], "devils_advocate": [challenge("agree")]})
    world.tick(runner, QUIET, policy=RM.RoomsPolicy(triggers=tpol(enabled=("loss_cluster",))))
    spec = runner.calls[0]["packet"]["specialist"]
    assert spec["meta"]["run_restarted"].startswith("실험을 2026-10-04에")
    assert spec["risk_reward"]["levrule"].startswith("좋은 자리 ")
    assert "levrule" in runner.calls[0]["system"]


def test_risk_meeting_has_levrule_and_the_curves(world):
    from test_levstop import V45
    from test_new_meetings import bulk, tpol
    from test_rooms import HOUR as H, QueueRunner, team_answer
    from test_survival import FRI
    bulk(world, 250, FRI - H, aid=f"{V45}@15m")
    pol = RM.RoomsPolicy(triggers=tpol(enabled=("risk_review",), risk_review_hour_kst=11))
    lead = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": []}
    runner = QueueRunner({"risk_officer": [team_answer("r", "survival.levrule.status")],
                          "validator": [team_answer("v")], "team_lead": [lead]})
    out = RM.tick(world.paths["paper"], world.paths["daily"], world.paths["agents"], world.paths["inbox"], runner,
                  policy=pol, now_ms=FRI, clock_ms=lambda: FRI)
    assert [r["status"] for r in out["rounds"]] == ["done"]
    sv = runner.calls[0]["packet"]["survival"]
    assert sv["levrule"]["status"] in ("interim", "decided") and sv["levrule"]["doc"] == "docs/levrule-eval.md"
    assert "variants" in sv["lev_curves"] and "survival.levrule" in runner.calls[0]["system"]


def test_checkpoint_meeting_has_the_levrule_decision(world, tmp_path):
    from test_new_meetings import tpol
    from test_readiness import LEAD, seed, verdict
    from test_rooms import MIN, QueueRunner, team_answer
    from test_rooms_round3 import DAY30
    seed(world)
    verdict(tmp_path)
    runner = QueueRunner({"league_referee": [team_answer("ref", "readiness.levrule.status")],
                          "rule_keeper": [team_answer("rk")], "team_lead": [LEAD]})
    out = world.tick(runner, DAY30 + 10 * MIN, policy=RM.RoomsPolicy(triggers=tpol(enabled=("checkpoint",))))
    assert [(r["trigger"], r["status"]) for r in out["rounds"]] == [("checkpoint", "done")]
    lv = runner.calls[0]["packet"]["readiness"]["levrule"]
    assert lv["doc"] == "docs/levrule-eval.md" and "note" in lv
    assert lv["status"] == "decided" and lv["decision"] in ("keep", "fixed20")    # day 30 is past: decided
    assert "readiness.levrule" in runner.calls[0]["system"]


# ---------------------------------------------------------------- dashboard
fastapi = pytest.importorskip("fastapi")


def _client(db):
    from fastapi.testclient import TestClient
    from test_dash_analysis import _client as mk
    return mk(db)


def _login(c):
    from test_dash_analysis import _login as lg
    lg(c)


NEW_ROUTES = ("/api/analysis/levrule", "/api/analysis/shadows", "/api/analysis/shadows?account=A@15m", "/api/levwhy",
              "/api/doc/rules-change-1", "/api/doc/levrule-eval")


def test_new_routes_need_the_login_and_answer_bounded(tmp_path):
    from test_dash import _store
    db = str(tmp_path / "paper3.db")
    _store(db).close()
    c = _client(db)
    for r in NEW_ROUTES:
        assert c.get(r).status_code == 401, r
    _login(c)
    for r in NEW_ROUTES:
        got = c.get(r)
        assert got.status_code == 200 and len(got.content) < 300_000, r
    lv = c.get("/api/analysis/levrule").json()
    assert lv["doc"] == "docs/levrule-eval.md" and "groups" in lv and "reason_ko" in lv
    sh = c.get("/api/analysis/shadows").json()
    assert [g["title"] for g in sh["groups"]] == ["청산 잠금", "시간 청산", "손절 폭", "고정 익절", "레버리지 고정(티어 비중)",
                                                  "레버리지 = 비중"]
    assert all(g["five_year"] for g in sh["groups"]) and sh["accounts"] == ["A@15m"]
    assert "5년" in sh["groups"][2]["five_year"] and "5년" in sh["groups"][4]["five_year"]
    assert c.get("/api/doc/levrule-eval").text.startswith("# 레버리지 규칙 B 평가 방법")
    assert c.get("/api/doc/../../etc/passwd").status_code == 404 and c.get("/api/doc/nope").status_code == 404
    assert c.get("/api/analysis/shadows?account=x%27%3B").json()["account"] is None
    a = c.get("/api/account/A@15m").json()
    assert a["trades"][0]["why"]["group"] in ("best", "normal") and a["trades"][0]["why"]["short_ko"]
    assert "tier" in c.get("/api/trades").json()[0]
    s = c.get("/api/summary").json()["restart"]
    # paper v4 (owners 2026-10-05): the banner names the v4 rules (dash RULES_V4_KO); its document link is the v4 rules
    # once docs/paper-v4-rules.md is in docs/, the v3 rules change before that
    from paperbot.dash.app import RULES_V4_KO
    assert s["ready"] and s["rules_ko"] == RULES_V4_KO and "5분봉 제외" not in s["rules_ko"]
    assert s["doc"] in ("/api/doc/rules-v4", "/api/doc/rules-change-1")


def test_new_routes_with_missing_or_empty_databases(tmp_path):
    db = str(tmp_path / "nope" / "paper3.db")
    os.makedirs(os.path.dirname(db))
    c = _client(db)
    _login(c)
    for r in NEW_ROUTES[:3]:
        got = c.get(r)
        assert got.status_code == 200 and len(got.content) < 300_000, r
    assert c.get("/api/analysis/levrule").json()["error"]
    assert os.listdir(os.path.dirname(db)) == []                            # read-only: nothing created
    db2 = str(tmp_path / "empty.db")
    sqlite3.connect(db2).close()
    c2 = _client(db2)
    _login(c2)
    for r in NEW_ROUTES[:3]:
        assert c2.get(r).status_code == 200, r
    assert c2.get("/api/analysis/levrule").json()["status"] == "no_run"


def test_restart_banner_math():
    from paperbot.dash.app import RULES_V4_KO, restart_banner
    start = START + 15 * HOUR                                   # 2026-10-05 15:00 UTC (00:00 KST 10-06)
    cp1 = START + 30 * DAY                                      # 2026-11-04 00:00 UTC = 09:00 KST
    b = restart_banner(start, start)
    assert (b["day"], b["of"], b["checkpoint"], b["verdict_ts"], b["verdict_mmdd"]) == (0, 30, 1, cp1, "11/04")
    assert b["text"] == "새 실험 D+0 / 30 · 첫 판정 11/04" and b["rules_ko"] == RULES_V4_KO
    assert restart_banner(start, START + DAY + HOUR)["text"] == "새 실험 D+1 / 30 · 첫 판정 11/04"
    assert restart_banner(start, cp1 - 1)["day"] == 29
    # review 10/06 fix 1: at 09:00 on the verdict day the checkpoint stays named until its verdict is stored
    # (dash/more/verdictday.py); without checkpoint.db's word it is 'not known', never the next one
    late = restart_banner(start, cp1)
    assert late["day"] == 30 and late["checkpoint"] == 1 and late["due"] and late["state"] == "unknown"
    assert late["text"] == "새 실험 D+30 · 30일 판정 결과 기다림" and late["verdict_mmdd"] == "11/04"
    judged = restart_banner(start, cp1, {"db": "ok", "verdicts": {"2026-11-04": cp1 + 7_200_000}, "snapshots": {}, "log": {}})
    assert judged["checkpoint"] == 2 and judged["of"] == 60 and judged["text"] == "새 실험 D+30 · 2번째 판정 12/04"
    assert restart_banner(None, cp1)["ready"] is False
    assert "5분봉 제외" not in RULES_V4_KO and "딥시크" in RULES_V4_KO            # the v4 run trades 5m (the reel)


def test_pages_have_the_new_views():
    st = os.path.join(ROOT, "paperbot", "dash", "static")
    html = open(os.path.join(st, "index.html"), encoding="utf-8").read()
    assert 'data-t="levrule"' in html and "좋은 자리 vs 보통" in html and 'data-t="shadows"' in html and "그림자 비교" in html
    js = open(os.path.join(st, "analysis.js"), encoding="utf-8").read()
    assert "30일 판정 전 결론 없음" in js and "addLineSeries" in js and "/api/doc/levrule-eval" in js
    assert "--c1" in open(os.path.join(st, "style.css"), encoding="utf-8").read()
    assert "/api/levwhy" in open(os.path.join(st, "pos.js"), encoding="utf-8").read()
    assert "rs.rules_ko" in open(os.path.join(st, "summary.js"), encoding="utf-8").read()
    assert "position_why" in open(os.path.join(st, "app.js"), encoding="utf-8").read()


# ---------------------------------------------------------------- Telegram
def test_entry_alert_says_why_a_good_spot_entered_lower():
    from paperbot import tradealerts as TA
    p = {"symbol": "BTCUSDT", "side": 1, "entry": 100.0, "entry_time": 0, "leverage": 30, "margin": 1500.0,
         "stop": 98.0, "kind": "strategy", "tier": "best", "wallet": 5000.0,
         "lev_why": "50배 불가: 손절 손실 > 자금 15% → 30배"}
    L = TA.entry_block("A@15m", p, {})
    assert L[1].endswith("30배 · 좋은 자리") and L[2] == "50배 불가: 손절 손실 > 자금 15% → 30배"
    assert "50배 불가" not in "\n".join(TA.entry_block("A@15m", {**p, "tier": "normal"}, {}))
