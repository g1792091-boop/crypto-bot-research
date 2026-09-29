import json
import random
from datetime import datetime, timezone

import pytest

from paperbot import Bar, Brackets, PaperEngine, Settings, Signal
from paperbot.analyze import analyze, main as analyze_main, to_markdown
from paperbot.context import entry_context, regime
from paperbot.ledger import BarStore, Ledger, load_trades
from paperbot.live import LiveRunner
from paperbot.models import TradeRecord
from paperbot.notify import ListNotifier
from paperbot.replay import replay
from paperbot.sessions import session_of, session_report, time_features
from paperbot.tags import tag_table, tag_trade
from paperbot.whatif import (ExitPolicy, day_block_bootstrap, default_catalog, holm,
                             run_lab, simulate)

MIN = 60_000


def ms(y, mo, d, h=0, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp() * 1000)


def mk(i, o, h, l, c, sym="BTCUSDT", step=MIN):
    return Bar(sym, i * step, i * step + step - 1, o, h, l, c)


def trend_bars(n, up=True):
    out = []
    for i in range(n):
        c = 100 + (i if up else -i) * 0.5
        out.append(mk(i, c - 0.25, c + 0.3, c - 0.3, c))
    return out


def box_bars(n):
    # Triangle wave between 100 and 110, period 20 bars.
    out = []
    for i in range(n):
        ph = i % 20
        c = 100 + (ph if ph <= 10 else 20 - ph)
        out.append(mk(i, c, c + 0.2, c - 0.2, c))
    return out


# ---------------------------------------------------------------- context
def test_regime_labels():
    assert regime(trend_bars(60), 60)["label"] == "trend_up"
    assert regime(trend_bars(60, up=False), 60)["label"] == "trend_down"
    assert regime(box_bars(60), 60)["label"] == "box"
    assert regime(trend_bars(10), 60)["label"] == "unknown"


def test_entry_context_fields():
    ctx = entry_context("1m", box_bars(80), trend_bars(70), n=60)
    assert ctx["regime"] == "box" and ctx["htf"] == "15m"
    assert 0 <= ctx["box_pos"] <= 1.2
    assert ctx["htf_regime"] == "trend_up"
    for k in ("atr", "ema20_dist_atr", "trend_age", "range_pct", "er"):
        assert k in ctx


# ---------------------------------------------------------------- tags
def trade(**kw):
    base = dict(strategy_id="s", symbol="BTCUSDT", timeframe="1m", side=1, signal_ts=0,
                entry_time=MIN, entry_price=100.0, exit_time=5 * MIN, exit_price=99.0,
                exit_reason="SL", qty=1.0, leverage=20, tier="base", margin=5.0,
                stop_price=99.0, tp_price=102.0, liq_price=95.5, fees=0.1, funding=0.0,
                pnl=-1.1, roe=-0.22, price_move=-0.01, mae_price=99.0, mfe_price=100.2,
                equity_after=998.9, score=0.0, context={}, strategy_style="")
    base.update(kw)
    return TradeRecord(**base)


def test_counter_trend_loss_is_tagged_h0():
    t = trade(side=-1, stop_price=101.0, exit_price=101.0, tp_price=98.0,
              mae_price=101.0, mfe_price=99.8, context={"htf_regime": "trend_up"})
    tag = tag_trade(t)
    assert tag["class"] == "loss" and "H0" in tag["pre"] and tag["primary"] == "H0"


def test_gave_back_loss_goes_to_exit_first():
    t = trade(mfe_price=101.5, context={"htf_regime": "trend_down"})
    tag = tag_trade(t)
    assert tag["primary"] == "G1" and "H0" in tag["secondary"]


def test_stop_too_tight_needs_post_bars():
    t = trade()
    post = [mk(6, 99.2, 100.5, 99.0, 100.4), mk(7, 100.4, 102.5, 100.3, 102.4)]
    assert tag_trade(t, post)["primary"] == "T1"
    assert tag_trade(t)["primary"] == "N0"


def test_wins_and_liquidation():
    win = trade(exit_reason="TP", exit_price=102.0, pnl=1.9, mfe_price=102.1, equity_after=1001.9)
    assert tag_trade(win)["primary"] == "W3"
    liq = trade(exit_reason="LIQ", pnl=-5.0)
    assert tag_trade(liq)["primary"] == "LIQ"
    fee_eaten = trade(exit_reason="TP", exit_price=100.1, pnl=0.02, fees=0.1)
    assert tag_trade(fee_eaten)["primary"] == "W5"


def test_tag_table_marks_small_samples():
    tagged = [tag_trade(trade(side=-1, stop_price=101.0, exit_price=101.0, tp_price=98,
                              mae_price=101.0, mfe_price=99.9,
                              context={"htf_regime": "trend_up"})) for _ in range(3)]
    tagged.append(tag_trade(trade(exit_reason="TP", exit_price=102.0, pnl=1.9,
                                  context={"htf_regime": "trend_up"}, mfe_price=102.0)))
    rows = {r["tag"]: r for r in tag_table(tagged)}
    assert rows["H0"]["n"] == 3 and rows["H0"]["status"].startswith("insufficient")


# ---------------------------------------------------------------- what-if
def walk(n, seed=3, sym="BTCUSDT"):
    rng = random.Random(seed)
    p = 100.0
    out = []
    for i in range(n):
        o = p
        c = o * (1 + rng.gauss(0, 0.0015))
        h = max(o, c) * (1 + abs(rng.gauss(0, 0.0008)))
        l = min(o, c) * (1 - abs(rng.gauss(0, 0.0008)))
        out.append(Bar(sym, i * MIN, i * MIN + MIN - 1, o, h, l, c))
        p = c
    return out


def engine_trades(n_bars=3 * 1440, every=40):
    s = Settings()
    bars = walk(n_bars)
    sigs = []
    for k, i in enumerate(range(30, n_bars - 200, every)):
        b = bars[i]
        side = 1 if k % 2 == 0 else -1
        ctx = {"atr": b.close * 0.002}
        sigs.append(Signal(b.close_time, "BTCUSDT", "1m", "demo", side,
                           b.close * (1 - side * 0.005), meta={"ctx": ctx}))
    eng = PaperEngine(s, {x: Brackets.example() for x in s.symbols})
    replay(s, {"BTCUSDT": bars}, sigs, eng.brackets, {}, eng)
    return s, eng.trades, {"BTCUSDT": bars}


def test_c0_reproduces_engine_trades():
    s, trades, bars = engine_trades()
    assert len(trades) >= 30
    rep = run_lab(trades, bars, s, boot=200)
    assert rep["reproduction"]["ok"], rep["reproduction"]["mismatches"][:3]
    assert rep["reproduction"]["checked"] == len(trades)
    pols = {p["policy"]: p for p in rep["policies"]}
    assert set(pols) == {p.pid for p in default_catalog()}
    assert pols["SL_ROE50"]["over_cap"] == 0  # base 20% x ROE 50% = 10% of account
    for p in rep["policies"][1:]:
        assert "verdict" in p


def test_wider_stop_is_flagged_over_cap_and_small_n_insufficient():
    s, trades, bars = engine_trades(n_bars=1000, every=60)
    cat = [ExitPolicy("C0", "baseline"), ExitPolicy("SL_ROE90", "stop", sl_roe=0.9)]
    rep = run_lab(trades[:5], bars, s, catalog=cat, boot=50)
    p = rep["policies"][1]
    assert p["verdict"].startswith("insufficient")
    assert p["over_cap"] == p["n"]  # 20% margin x 90% ROE = 18% > 15%


def test_simulate_time_exit_and_breakeven():
    s = Settings()
    t = trade(entry_price=100.0, stop_price=99.0, tp_price=110.0, liq_price=95.5,
              exit_reason="TP", pnl=0.0)
    bars = [mk(1, 100, 100.2, 99.9, 100.1)] + [mk(i, 100.1, 100.3, 99.95, 100.1)
                                                 for i in range(2, 10)]
    r = simulate(t, ExitPolicy("T", "m", time_bars=3), bars, s)
    assert r.reason == "TIME" and r.bars == 3
    up = [mk(1, 100, 101.2, 99.9, 101.1), mk(2, 101.1, 101.2, 99.5, 99.6)]
    r = simulate(t, ExitPolicy("B", "m", be_at_r=1.0), up, s)
    assert r.reason == "SL" and r.exit_price > 100  # stopped at breakeven, not at 99


def test_bootstrap_and_holm():
    diffs = [(d, 0.01 + 0.001 * (i % 3)) for d in range(20) for i in range(3)]
    bs = day_block_bootstrap(diffs, b=300, alpha=0.05)
    assert bs["lo"] > 0 and bs["p"] < 0.05
    noisy = [(d, (-1) ** d * 0.01) for d in range(20) for _ in range(2)]
    nb = day_block_bootstrap(noisy, b=300)
    assert nb["lo"] < 0 < nb["hi"] and nb["p"] > 0.5
    adj = holm({"a": 0.01, "b": 0.04, "c": None})
    assert adj["a"] == pytest.approx(0.02) and adj["b"] == pytest.approx(0.04) and adj["c"] is None


# ---------------------------------------------------------------- sessions
def test_session_boundaries():
    assert [session_of(h) for h in (9, 15, 16, 21, 22, 4, 5, 8)] == [
        "asia", "asia", "europe", "europe", "us", "us", "dawn", "dawn"]


def test_time_features_kst_and_windows():
    f = time_features(ms(2024, 1, 15, 0, 5))  # Mon 09:05 KST, 5 min after funding
    assert f["kst_weekday"] == "Mon" and f["session"] == "asia" and "funding" in f["windows"]
    assert not f["weekend"]
    assert "us_open" in time_features(ms(2024, 7, 15, 13, 30))["windows"]  # EDT
    assert "us_open" in time_features(ms(2024, 1, 15, 14, 30))["windows"]  # EST
    assert "us_open" not in time_features(ms(2024, 1, 15, 13, 29))["windows"]
    assert "macro" in time_features(ms(2024, 7, 15, 12, 30))["windows"]
    sat = time_features(ms(2024, 1, 13, 3, 0))  # Sat 12:00 KST
    assert sat["weekend"] and "us_open" not in sat["windows"]


def test_session_report_cells():
    ts = [trade(entry_time=ms(2024, 1, 15, 1), pnl=1.0, equity_after=1001),
          trade(entry_time=ms(2024, 1, 13, 14), pnl=-1.0, equity_after=999)]
    rep = session_report(ts, min_n=30, by="symbol")
    cells = {(c["day"], c["session"]): c for c in rep["primary"]}
    assert cells[("weekday", "asia")]["n"] == 1
    assert cells[("weekend", "us")]["n"] == 1  # Sat 23:00 KST
    assert all(c["status"].startswith("insufficient") for c in rep["primary"])
    assert rep["heatmap"]["Mon"][10]["n"] == 1
    assert "BTCUSDT" in rep["split"]


# ---------------------------------------------------------------- storage, live hook, CLI
def test_barstore_and_trade_roundtrip(tmp_path):
    db = str(tmp_path / "p.db")
    st = BarStore(db)
    st.add(walk(5))
    st.add(walk(5))  # idempotent
    assert len(st.load("BTCUSDT")) == 5 and st.symbols() == ["BTCUSDT"]
    st.close()
    led = Ledger(db, "r1", "v")
    led.trade(trade(context={"regime": "box"}, strategy_style="trend"))
    led.close()
    got = load_trades(db, "r1")
    assert got[0].context == {"regime": "box"} and got[0].strategy_style == "trend"


class Every5m:
    strategy_id = "ctx5"
    timeframe = "5m"
    warmup_bars = 1
    style = "trend"

    def on_bar(self, symbol, history):
        b = history[-1]
        return [Signal(b.close_time, symbol, "5m", self.strategy_id, 1, b.close * 0.99)]


def test_live_runner_attaches_context_and_records_bars(tmp_path):
    s = Settings()
    eng = PaperEngine(s, {x: Brackets.example() for x in s.symbols})
    store = BarStore(str(tmp_path / "b.db"))
    lr = LiveRunner(None, eng, [Every5m()], ListNotifier(), bar_store=store)
    assert "30m" in lr.agg.tfs
    steps = [(b.open_time, {"BTCUSDT": b}, {}) for b in walk(12)]
    lr.process(steps)
    sig = eng.outcomes[0].signal if eng.outcomes else eng.pending[0]
    assert sig.meta["style"] == "trend" and sig.meta["ctx"]["tf"] == "5m"
    assert sig.meta["ctx"]["regime"] == "unknown"  # not enough 5m bars yet
    assert len(store.load("BTCUSDT")) == 12


def test_analyze_cli_end_to_end(tmp_path):
    s, trades, bars = engine_trades(n_bars=1500, every=50)
    db = str(tmp_path / "p.db")
    led = Ledger(db, "run-owner", s.version)
    for t in trades:
        led.trade(t)
    led.close()
    st = BarStore(db)
    st.add(bars["BTCUSDT"])
    st.close()
    out = str(tmp_path / "rep")
    analyze_main(["--ledger", db, "--run-id", "run-owner", "--out", out, "--bootstrap", "100"])
    rep = json.loads(open(out + ".json").read())
    assert rep["trades"] == len(trades)
    assert rep["whatif"]["reproduction"]["ok"]
    md = open(out + ".md").read()
    assert "What-if lab" in md and "C0 reproduction: OK" in md
    assert to_markdown(analyze(trades, bars, boot=50)).startswith("# Paper trade analysis")
