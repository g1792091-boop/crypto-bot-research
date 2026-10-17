"""paperbot/combo.py, the combined bot (합친 봇): one paper account for several strategies, fixed leverage per coin,
one position, the better spot first; the order executor follows it unchanged.

- members: default numbers, a candidate league pick, custom numbers equal to the defaults, the refusals;
- sizing: BTC 40x / others 30x, margin = leverage %, the 15% loss cap (cut or refuse), the stop inside liquidation;
- the stop rules (2 ATR, pulled in to fit, a fixed ROE) and the ranking (score, timeframe, list order);
- the runner on a synthetic paper3.db: a signal is entered on the minute that opens at its bar's close at its
  reference price, a competing one is recorded as skipped, a late one is refused, a restart goes on, the coin-flip
  twin gets every signal; the executor's own reader sees the position and mirrors it at 40x into a fake exchange;
- custom numbers: the custom path with the default numbers gives exactly the rule bot's signals (36: compute_last;
  DeepSeek: dssig's job), so a custom pick runs on the same frames as the rule bot;
- conditions (when): parsing and refusals, KST sessions and weekends at their edges, the BTC 4h trend equal to the
  candidate league's gate g1, and the runner keeping a signal outside its member's conditions from both accounts."""

import dataclasses
import json
import math
import warnings

import numpy as np
import pytest

from paperbot import combo as C
from paperbot.margin import BracketTier, Brackets
from paperbot.models import Bar, Signal
from paperbot.notify import ListNotifier
from paperbot.store3 import Store3

MIN = 60_000
FIVE = 300_000
T0 = 1_791_158_400_000                        # 2026-10-05 00:00 UTC
SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
PX = {"BTCUSDT": 60000.0, "ETHUSDT": 2500.0, "SOLUSDT": 150.0, "DOGEUSDT": 0.2, "LTCUSDT": 80.0, "BCHUSDT": 400.0}
SPECS = {s: {"qty_step": 0.0001 if s == "BTCUSDT" else 0.001, "min_notional": 5.0, "tick_size": 0.01} for s in SYMS}
BRK = Brackets([BracketTier(300_000, 125, 0.004, 0.0), BracketTier(800_000, 50, 0.005, 300.0)])
BRACKETS = {s: BRK for s in SYMS}


def cfg_of(tmp_path, **kw):
    d = dict(paper_db=str(tmp_path / "paper3.db"), db=str(tmp_path / "combo.db"),
             members=[{"strategy": "V39_ALL", "tf": "15m"}, {"strategy": "OBV_S", "tf": "15m"}],
             telegram=False)
    d.update(kw)
    return C.ComboConfig.from_dict(d)


# ---------------------------------------------------------------- members
def test_members_default_pick_custom_and_refusals(tmp_path):
    core = ["V39_ALL", "OBV_S", "N13_3OUTSIDE"]
    ms = C.resolve_members([{"strategy": "V39_ALL", "tf": "1h"}, {"pick": "core-N13_3OUTSIDE-30m-1"},
                            {"strategy": "F9_FVG", "tf": "1h"}], core=core)
    assert [(m.kind, m.name, m.tf, m.custom, m.order) for m in ms] == [
        ("core", "V39_ALL", "1h", False, 1), ("core", "N13_3OUTSIDE", "30m", True, 2), ("ds", "F9_FVG", "1h", False, 3)]
    picks = C.load_picks(C.CANDIDATES_FILE)
    assert ms[1].numbers == {**C.default_numbers("core", "N13_3OUTSIDE"), **picks["core-N13_3OUTSIDE-30m-1"]["combo"]}
    # custom numbers equal to the defaults -> the rule bot's own signals
    d = C.default_numbers("core", "OBV_S")
    m = C.resolve_members([{"strategy": "OBV_S", "tf": "30m", "numbers": d}], core=core)[0]
    assert not m.custom and m.label == "OBV_S@30m"
    for bad, text in [([{"strategy": "NOPE", "tf": "1h"}], "없는 매매법"),
                      ([{"strategy": "OBV_S", "tf": "5m"}], "15m/30m/1h/4h"),
                      ([{"strategy": "OBV_S", "tf": "1h", "numbers": {"zzz": 1}}], "없는 숫자"),
                      ([{"strategy": "OBV_S", "tf": "1h"}, {"strategy": "OBV_S", "tf": "1h"}], "두 번"),
                      ([{"pick": "core-NOPE-1h-1"}], "없습니다"), ([], "비어")]:
        with pytest.raises(C.ComboError, match=text):
            C.resolve_members(bad, core=core)


def test_config_problems(tmp_path):
    assert cfg_of(tmp_path).problems() == []
    bad = cfg_of(tmp_path, db=str(tmp_path / "paper3.db"), stop={"mode": "roe", "roe": 5}, margin=2,
                 max_signal_age_s=500, rank=["score", "x"], leverage={"BTCUSDT": 200})
    probs = " | ".join(bad.problems())
    for want in ("다른 파일", "stop.roe", "margin", "max_signal_age_s", "rank", "leverage BTCUSDT"):
        assert want in probs
    with pytest.raises(C.ComboError, match="알 수 없는"):
        C.ComboConfig.from_dict({"paper_db": "a", "db": "b", "members": [], "nope": 1})


# ---------------------------------------------------------------- sizing
def _sig(sym="BTCUSDT", side=1, tf="15m", strategy="V39_ALL", score=3.0, atr=None, ref=None, order=1, dist=None):
    ref = PX[sym] if ref is None else ref
    atr = ref * 0.003 if atr is None else atr
    return Signal(ts=T0 - 1, symbol=sym, timeframe=tf, strategy_id=strategy, side=side, stop_price=0.0, tier="best",
                  score=score, atr=atr, meta={"ref_price": ref, "stop_dist": 2 * atr if dist is None else dist,
                                              "member_order": order, "member": f"{strategy}@{tf}"})


def _engine(cfg):
    st = C.settings_of(cfg)
    return C.ComboEngine(st, BRACKETS, combo=cfg, symbol_specs=SPECS)


def _bar(sym, t, o, h=None, l=None, c=None):
    h = max(o, c or o) if h is None else h
    l = min(o, c or o) if l is None else l
    return Bar(sym, t, t + MIN - 1, o, h, l, o if c is None else c)


def test_fixed_leverage_margin_and_loss_cap(tmp_path):
    cfg = cfg_of(tmp_path)
    e = _engine(cfg)
    pol = e.policy
    s = _sig("BTCUSDT", atr=60000 * 0.001)           # stop 0.2%: 40x, margin 40% fits under 15%
    dec = pol.size(1000.0, dataclasses.replace(s, stop_price=60000 * 0.998), 60000.0, BRK, SPECS["BTCUSDT"])
    assert dec.ok and dec.leverage == 40 and abs(dec.margin - 400) < 1 and dec.loss_at_stop <= 150
    s = _sig("ETHUSDT", atr=2500 * 0.001)
    dec = pol.size(1000.0, dataclasses.replace(s, stop_price=2500 * 0.998), 2500.0, BRK, SPECS["ETHUSDT"])
    assert dec.ok and dec.leverage == 30 and abs(dec.margin - 300) < 1
    # stop 1.2% at 40x: margin 40% would lose ~19% -> cut to 15%
    s = _sig("BTCUSDT", atr=60000 * 0.0015)
    stop = 60000 * 0.988
    dec = pol.size(1000.0, dataclasses.replace(s, stop_price=stop), 60000.0, BRK, SPECS["BTCUSDT"])
    assert dec.ok and dec.leverage == 40 and dec.loss_at_stop <= 150.0001 and dec.margin < 400
    assert any("cut" in r for r in dec.reasons)
    skip = C.FixedLevPolicy(C.settings_of(cfg), dataclasses.replace(cfg, loss_cap="skip"))
    assert not skip.size(1000.0, dataclasses.replace(s, stop_price=stop), 60000.0, BRK, SPECS["BTCUSDT"]).ok
    # 2.4% at 40x is past liquidation (~2.1%): refused
    s = _sig("BTCUSDT", atr=60000 * 0.012)
    dec = pol.size(1000.0, dataclasses.replace(s, stop_price=60000 * 0.976), 60000.0, BRK, SPECS["BTCUSDT"])
    assert not dec.ok and "liq" in dec.reasons[-1]


def test_stop_rules(tmp_path):
    t = T0
    bar = _bar("BTCUSDT", t, 60000.0)
    # roe: -50% at 40x = 1.25% of price
    e = _engine(cfg_of(tmp_path, stop={"mode": "roe", "roe": 0.5}))
    s, why = e._with_stop(_sig("BTCUSDT"), bar)
    assert why is None and abs(s.meta["stop_dist"] - 60000 * 0.0125) < 1e-6
    s, _ = e._with_stop(_sig("ETHUSDT"), _bar("ETHUSDT", t, 2500.0))
    assert abs(s.meta["stop_dist"] - 2500 * 0.5 / 30) < 1e-9
    # atr_fit: 2 x ATR of 1.1% = 2.2% does not fit at 40x -> pulled in inside liquidation, the entry goes ahead
    e = _engine(cfg_of(tmp_path, stop={"mode": "atr_fit", "atr": 2.0, "min_atr": 1.0}))
    sig = _sig("BTCUSDT", atr=60000 * 0.011 / 2 * 1.0)     # ATR 0.55%: 2 ATR = 1.1% fits as is
    s, _ = e._with_stop(sig, bar)
    assert abs(s.meta["stop_dist"] - 2 * sig.atr) < 1e-9
    sig = _sig("BTCUSDT", atr=60000 * 0.0075)                # ATR 0.75%: 2 ATR = 1.5% + 1 ATR buffer > 2.1%
    s, _ = e._with_stop(sig, bar)
    assert s.meta["stop_dist"] < 2 * sig.atr and "pulled in" in s.meta["stop_rule"]
    assert e._try_enter(s, bar) and e.position.leverage == 40
    sig = _sig("BTCUSDT", atr=60000 * 0.012)                 # 1 ATR + 1 ATR buffer > 2.1%: refused
    s, why = _engine(cfg_of(tmp_path, stop={"mode": "atr_fit", "atr": 2.0, "min_atr": 1.0}))._with_stop(sig, bar)
    assert s is None and "does not fit" in why[1]
    # plain 2 ATR that does not fit: the sizing refuses it (recorded)
    e = _engine(cfg_of(tmp_path))
    assert not e._try_enter(_sig("BTCUSDT", atr=60000 * 0.0075), bar)
    assert e.outcomes[-1].status == "REJECTED" and e.outcomes[-1].reason == "sizing"


def test_rank_score_then_timeframe_then_order(tmp_path):
    cfg = cfg_of(tmp_path)
    st = C.settings_of(cfg)
    a = _sig("ETHUSDT", score=4.0, tf="15m", order=2)
    b = _sig("BTCUSDT", score=3.0, tf="4h", order=1)
    c = _sig("SOLUSDT", score=3.0, tf="1h", order=1)
    d = _sig("LTCUSDT", score=3.0, tf="1h", order=3)
    order = sorted([d, c, b, a], key=lambda x: C.rank_key(cfg, st, x))
    assert [x.symbol for x in order] == ["ETHUSDT", "BTCUSDT", "SOLUSDT", "LTCUSDT"]
    cfg2 = dataclasses.replace(cfg, rank=("order", "timeframe"))
    order = sorted([d, c, b, a], key=lambda x: C.rank_key(cfg2, st, x))
    assert [x.symbol for x in order] == ["BTCUSDT", "SOLUSDT", "ETHUSDT", "LTCUSDT"]


# ---------------------------------------------------------------- the runner on a synthetic paper3.db
class World:
    """paper3.db with the rule bot's tables; the combined bot reading it."""

    def __init__(self, tmp_path, **kw):
        self.tmp = tmp_path
        self.paper = Store3(str(tmp_path / "paper3.db"))
        self.now = T0
        self.px = dict(PX)
        self.cfg = cfg_of(tmp_path, **kw)
        self.note = ListNotifier()
        self.add_minutes(T0 - 10 * MIN, 10)           # the rule bot is already running
        self.open()

    def open(self):
        self.members = C.resolve_members(self.cfg.members, core=["V39_ALL", "OBV_S"])
        self.store = Store3(self.cfg.db)
        self.book = C.build_book(self.cfg, C.settings_of(self.cfg), BRACKETS, self.store, self.note, SPECS)
        self.run = C.ComboRunner(self.cfg, self.members, self.book, self.store, self.note, None,
                                 now_ms=lambda: self.now, prices=lambda: {})

    def add_minutes(self, start, n, move=None):
        rows = []
        for k in range(n):
            t = start + k * MIN
            for s in SYMS:
                o = self.px[s]
                c = o * (1 + (move or {}).get(s, 0.0))
                rows.append({"ts": t, "symbol": s, "open": o, "high": max(o, c) * 1.0001, "low": min(o, c) * 0.9999,
                             "close": c, "volume": 10.0, "mark_open": o, "mark_high": max(o, c), "mark_low": min(o, c),
                             "mark_close": c, "close_time": t + MIN - 1, "processed_at": t + MIN + 5000})
                self.px[s] = c
        self.paper.live_bars(rows)
        self.paper.commit()

    def signal(self, strategy, sym, side, bar_close, atr_frac=0.002, ref_time=None, status="SUBMITTED", tf="15m"):
        ref = self.px[sym]
        self.paper.log_signals([{"bar_close": bar_close, "timeframe": tf, "strategy": strategy, "symbol": sym,
                                 "side": side, "atr": ref * atr_frac, "ref_price": ref,
                                 "ref_time": bar_close + 20_000 if ref_time is None else ref_time,
                                 "delay_ms": 20_000, "status": status, "data": {"ctx": {}}}])
        self.paper.commit()

    def engine(self, aid=C.ACCOUNT):
        return self.book.engines[aid]


def test_runner_enters_the_better_signal_once_and_the_executor_can_read_it(tmp_path):
    w = World(tmp_path)
    w.now = T0 + 5_000
    w.run.poll()                                    # first start: from the rule bot's latest minute and signal row
    assert w.book.last_ts == T0 - MIN and w.engine().position is None
    B = T0 + 15 * MIN                              # a 15m close
    w.add_minutes(T0, 15)
    w.signal("OBV_S", "ETHUSDT", -1, B)            # same score: the list order decides -> V39 (first) wins
    w.signal("V39_ALL", "BTCUSDT", 1, B)
    w.signal("RANDOM_1", "SOLUSDT", 1, B)          # not a member
    w.now = B + 10_000
    w.run.poll()
    assert w.engine().position is None             # the minute that opens at B is not there yet
    w.add_minutes(B, 1)
    w.now = B + 65_000
    w.run.poll()
    p = w.engine().position
    assert p is not None and p.symbol == "BTCUSDT" and p.side == 1 and p.leverage == 40
    assert abs(p.entry_price - 60000 * (1 + 0.0002)) < 1e-6           # the reference price + slippage
    outs = w.store.conn.execute("SELECT status, reason FROM outcomes WHERE account_id = ? ORDER BY id",
                                (C.ACCOUNT,)).fetchall()
    assert ("ENTERED", "ok") in outs and ("SKIPPED", "lower score than entered signal") in outs
    # the executor's own reader: the combined bot's database and account, unchanged executor code
    from paperbot.executor import Paper3Source
    it, ts = Paper3Source(w.cfg.db, C.ACCOUNT).read()
    assert it.symbol == "BTCUSDT" and it.leverage == 40 and it.side == 1 and ts == B
    # the coin-flip twin got both signals at the same moment
    flip = w.engine(C.FLIP_ACCOUNT)
    assert flip.position is not None or any(o.status == "REJECTED" for o in flip.outcomes)
    # a later signal while in position: skipped
    B2 = B + 15 * MIN
    w.add_minutes(B + MIN, 14)
    w.signal("OBV_S", "ETHUSDT", 1, B2)
    w.add_minutes(B2, 1)
    w.now = B2 + 65_000
    w.run.poll()
    assert w.engine().position.symbol == "BTCUSDT"
    assert w.store.conn.execute("SELECT COUNT(*) FROM outcomes WHERE account_id = ? AND reason = 'in position'",
                                (C.ACCOUNT,)).fetchone()[0] == 1
    # the stop: BTC drops 2% -> SL, a trade row with the member's strategy
    w.add_minutes(B2 + MIN, 1, move={"BTCUSDT": -0.02})
    w.now = B2 + 125_000
    w.run.poll()
    assert w.engine().position is None
    t = json.loads(w.store.conn.execute("SELECT data FROM trades WHERE account_id = ?", (C.ACCOUNT,)).fetchone()[0])
    assert t["strategy_id"] == "V39_ALL" and t["exit_reason"] == "SL" and t["leverage"] == 40


def test_late_signals_are_refused_and_a_restart_goes_on(tmp_path):
    w = World(tmp_path)
    w.now = T0 + 5_000
    w.run.poll()
    B = T0 + 15 * MIN
    w.add_minutes(T0, 15)
    w.signal("V39_ALL", "BTCUSDT", 1, B)
    w.now = B + 10_000
    w.run.poll()                                    # queued (its minute is not stepped yet)
    st = w.store.get_state(C.STATE_KEY)[1]
    assert len(st["queue"]) == 1
    # the combined bot stops here; the rule bot runs on for 10 minutes
    w.store.close()
    w.add_minutes(B, 10)
    w.now = B + 11 * MIN
    w.open()                                       # restart: the queued signal is now 11 minutes old
    assert w.book.last_ts == B - MIN
    w.run.poll()
    assert w.book.last_ts == B + 9 * MIN and w.engine().position is None
    assert w.store.conn.execute("SELECT COUNT(*) FROM outcomes WHERE account_id = ? AND reason = 'late'",
                                (C.ACCOUNT,)).fetchone()[0] == 1
    # a new signal after the restart trades
    B2 = B + 15 * MIN
    w.add_minutes(B + 10 * MIN, 5)
    w.signal("OBV_S", "ETHUSDT", -1, B2)
    w.add_minutes(B2, 1)
    w.now = B2 + 65_000
    w.run.poll()
    p = w.engine().position
    assert p is not None and p.symbol == "ETHUSDT" and p.leverage == 30


def test_executor_mirrors_the_combined_account_at_40x(tmp_path):
    """End to end: the combined bot's database -> the unchanged executor -> a fake exchange: 40x on BTC."""
    from fakefutures import FakeFutures
    from paperbot import risk as R
    from paperbot.executor import ExecConfig, ExecStore, Executor, Paper3Source
    from paperbot.testnet import TestnetClient
    w = World(tmp_path)
    w.now = T0 + 5_000
    w.run.poll()
    B = T0 + 15 * MIN
    w.add_minutes(T0, 15)
    w.signal("V39_ALL", "BTCUSDT", 1, B)
    w.add_minutes(B, 1)
    w.now = B + 65_000
    w.run.poll()
    assert w.engine().position.leverage == 40
    fake = FakeFutures(prices={"BTCUSDT": w.px["BTCUSDT"], "ETHUSDT": w.px["ETHUSDT"]}, wallet=100.0)
    clock = lambda: w.now                                  # noqa: E731
    fake.clock = clock
    risk = R.RiskConfig(daily_max_loss_usd=10.0, max_drawdown_pct=0.3, max_consecutive_losses=6, max_leverage=40,
                        max_notional_usd=400.0, allowed_symbols=("BTCUSDT", "ETHUSDT"), kill_file=str(tmp_path / "STOP"))
    cfg = ExecConfig(account=C.ACCOUNT, paper_db=w.cfg.db, db=str(tmp_path / "exec.db"), qty_scale=0.1, risk=risk,
                     sweep_every=1)
    ex = Executor(cfg, TestnetClient("k", "s", send=fake, clock_ms=clock), Paper3Source(cfg.paper_db, cfg.account),
                  ExecStore(cfg.db), ListNotifier(), now_ms=clock, sleep=lambda s: None)
    ex.start()
    ex.loop_once()
    evs = [r[0] for r in ex.store.conn.execute("SELECT text FROM events ORDER BY id")]
    assert fake.lev["BTCUSDT"] == 40 and fake.pos["BTCUSDT"] > 0, evs
    # live size = paper qty x 0.1, then cut to the $400 cap and the $10 loss at the stop: never more
    assert fake.pos["BTCUSDT"] * w.px["BTCUSDT"] <= 400.0 + 1e-6


def test_seed_40_percent_runs_through_the_executor_when_both_allow_it(tmp_path):
    """Owners 2026-10-17: margin 40% of equity on every coin. The paper account sizes 40% (max_loss_frac 0.35, so a
    wide stop is not cut) and the executor follows it when its own risk.max_loss_frac allows the larger stop loss;
    without that setting the executor keeps the paper rules' 15% and cuts the live size."""
    from fakefutures import FakeFutures
    from paperbot import risk as R
    from paperbot.executor import ExecConfig, ExecStore, Executor, Paper3Source
    from paperbot.testnet import TestnetClient

    def run(sub, frac):
        w = World(tmp_path / sub, margin=0.4, max_loss_frac=0.35)
        w.now = T0 + 5_000
        w.run.poll()
        B = T0 + 15 * MIN
        w.add_minutes(T0, 15)
        w.signal("V39_ALL", "BTCUSDT", 1, B, atr_frac=0.006)     # 2 ATR = 1.2%: a stop costs ~21% at 40% x 40
        w.add_minutes(B, 1)
        w.now = B + 65_000
        w.run.poll()
        p = w.engine().position
        assert p is not None and p.leverage == 40
        assert abs(p.margin - 0.4 * 1000) < 1.0                    # 40% of the paper wallet, not cut
        fake = FakeFutures(prices={"BTCUSDT": w.px["BTCUSDT"], "ETHUSDT": w.px["ETHUSDT"]}, wallet=100.0)
        clock = lambda: w.now                                      # noqa: E731
        fake.clock = clock
        risk = R.RiskConfig(daily_max_loss_usd=100.0, max_drawdown_pct=0.6, max_consecutive_losses=3, max_leverage=40,
                            max_notional_usd=2000.0, allowed_symbols=("BTCUSDT", "ETHUSDT"),
                            kill_file=str(tmp_path / sub / "STOP"), max_loss_frac=frac)
        cfg = ExecConfig(account=C.ACCOUNT, paper_db=w.cfg.db, db=str(tmp_path / sub / "exec.db"), qty_scale=0.1,
                         risk=risk, sweep_every=1)
        ex = Executor(cfg, TestnetClient("k", "s", send=fake, clock_ms=clock), Paper3Source(cfg.paper_db, cfg.account),
                      ExecStore(cfg.db), ListNotifier(), now_ms=clock, sleep=lambda s: None)
        ex.start()
        ex.loop_once()
        return fake.pos.get("BTCUSDT", 0.0), p.qty

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    live, paper = run("a", 0.35)
    assert live == pytest.approx(math.floor(paper * 0.1 / 0.001 + 1e-9) * 0.001)   # paper x 0.1 on the exchange's
    assert live * PX["BTCUSDT"] > 1500                                       # 0.001 BTC step: ~$1,600 at 40x
    cut, _ = run("b", None)
    assert 0 < cut < live * 0.8                                            # the default 15% cuts it


# ---------------------------------------------------------------- custom numbers = the rule bot's path
def _synth5(seed, p0, n):
    rng = np.random.default_rng(seed)
    r = rng.standard_t(4, n) * 0.0018
    c = p0 * np.exp(np.cumsum(r))
    o = np.r_[p0, c[:-1]]
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.0009, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.0009, n)))
    v = rng.lognormal(10, 0.6, n)
    ts = T0 - n * FIVE + FIVE * np.arange(n)
    return ts.astype(np.int64), o, hi, lo, c, v


def test_custom_path_with_default_numbers_equals_the_rule_bot_core():
    from paperbot import sweepsig
    from paperbot.sigservice import compute_last, window_5m
    lib = sweepsig.lib()
    tf = "15m"
    names = ["V39_ALL", "OBV_S", "N13_3OUTSIDE", "DOGE"]
    ms = [C.Member(label=n, kind="core", name=n, tf=tf, numbers=C.default_numbers("core", n), order=i)
          for i, n in enumerate(names, 1)]
    need = window_5m(lib, tf)
    n = need + 300
    cols = _synth5(11, 2500.0, n)
    cs = C.CustomSignals(ms, ["ETHUSDT"], lib=lib)
    fired = 0
    for k in range(need, n + 1, 3):            # 15m boundaries inside the data
        end = int(cols[0][k - 1]) + FIVE
        if end % (15 * MIN):
            continue
        cs.hist["ETHUSDT"].clear()
        cs.bootstrap("ETHUSDT", list(zip(*(a[:k] for a in cols))))
        got = {g["member"].name: g["side"] for g in cs.compute(end)}
        assert not cs.errors, cs.errors
        win = tuple(a[k - need:k] for a in cols)
        ref = compute_last(("ETHUSDT", tf, end) + win)
        want = {nm: s for nm, s in ref["sides"].items() if nm in names and s}
        assert got == want, (end, got, want)
        fired += len(got)
    assert fired > 0


def test_custom_path_with_default_numbers_equals_the_rule_bot_deepseek():
    from paperbot import dssig, sweepsig
    from paperbot.config import DS_WINDOW_5M
    lib = sweepsig.lib()
    tf = "15m"
    names = [d for d in dssig.defs_for(tf)][:8]
    ms = [C.Member(label=nm, kind="ds", name=nm, tf=tf, numbers=C.default_numbers("ds", nm), order=i)
          for i, nm in enumerate(names, 1)]
    need = DS_WINDOW_5M[tf]
    n = need + 60
    eth, btc = _synth5(5, 2500.0, n), _synth5(6, 60000.0, n)
    cs = C.CustomSignals(ms, ["BTCUSDT", "ETHUSDT"], lib=lib)
    checked = 0
    for k in range(need, n + 1):
        end = int(eth[0][k - 1]) + FIVE
        if end % (15 * MIN):
            continue
        for sym, cols in (("BTCUSDT", btc), ("ETHUSDT", eth)):
            cs.hist[sym].clear()
            cs.bootstrap(sym, list(zip(*(a[:k] for a in cols))))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            got = {g["member"].name: g["side"] for g in cs.compute(end) if g["symbol"] == "ETHUSDT"}
        assert not cs.errors, cs.errors
        job = ("ETHUSDT", tf, end) + tuple(a[k - need:k] for a in eth) + (tuple(a[k - need:k] for a in btc),)
        ref = dssig._job(job)
        assert ref["ready"], ref.get("why")
        want = {nm: s for nm, s in ref["sides"].items() if nm in names}
        assert got == want, (end, got, want)
        checked += 1
    assert checked >= 3


def test_custom_signals_are_computed_at_the_boundary_and_entered(tmp_path):
    """The runner's custom path: at the 5m boundary after the minute that completes the bar, the custom members are
    computed, priced (ask for a long) and queued; the next minute enters them like the rule bot's signals."""
    class Stub(C.CustomSignals):
        def __init__(self, members):
            super().__init__(members, SYMS, lib=object())
            self.calls, self.gaps = [], []

        def window_need(self):
            return 10

        def fill_gaps(self, fetch, boundary):
            self.gaps.append(boundary)

        def compute(self, boundary):
            self.calls.append(boundary)
            m = self.members[0]
            return [{"member": m, "symbol": "SOLUSDT", "side": 1, "atr": 0.3, "ctx": {}}] if boundary % (15 * MIN) == 0 else []

    w = World(tmp_path, members=[{"pick": "core-N13_3OUTSIDE-30m-1"}, {"strategy": "V39_ALL", "tf": "15m"}])
    w.members = C.resolve_members(w.cfg.members, core=["V39_ALL", "OBV_S", "N13_3OUTSIDE"])
    custom = Stub(w.members)
    w.run = C.ComboRunner(w.cfg, w.members, w.book, w.store, w.note, custom, now_ms=lambda: w.now,
                          prices=lambda: {"SOLUSDT": (149.9, 150.1)}, fetch_5m=lambda s, a, b: [])
    w.now = T0 + 5_000
    w.run.poll()
    B = T0 + 15 * MIN
    w.add_minutes(T0, 15)
    w.now = B + 8_000                               # the rule bot has stepped the minute that closes the 5m bar
    w.run.poll()
    assert B in custom.calls and B in custom.gaps and w.engine().position is None
    q = w.store.get_state(C.STATE_KEY)[1]["queue"]
    assert len(q) == 1 and q[0]["signal"]["meta"]["source"] == "custom"
    assert q[0]["signal"]["meta"]["ref_price"] == 150.1                     # the ask: a long
    w.add_minutes(B, 1)
    w.now = B + 65_000
    w.run.poll()
    p = w.engine().position
    assert p is not None and p.symbol == "SOLUSDT" and p.leverage == 30 and p.signal.strategy_id == "N13_3OUTSIDE"
    assert p.signal.meta["member"] == "core-N13_3OUTSIDE-30m-1"
    # a boundary seen only in a catch-up (older than max_signal_age_s) is not computed
    n = len(custom.calls)
    w.add_minutes(B + MIN, 20)
    w.now = B + 60 * MIN
    w.run.poll()
    assert len(custom.calls) == n


def test_funding_is_paid_once_at_its_minute():
    class Rest:
        def __init__(self):
            self.rows = [{"fundingTime": T0 - 8 * 3_600_000, "fundingRate": "0.01"},       # before the start: never
                         {"fundingTime": T0 + 5 * MIN + 7, "fundingRate": "0.0001"}]

        def funding_rates(self, symbol, start_time=None):
            return [r for r in self.rows if start_time is None or int(r["fundingTime"]) >= start_time]

    f = C.FundingFeed(Rest(), ["BTCUSDT"], start=T0)
    f.poll(T0 + 10 * MIN)
    assert f.take(T0 + 4 * MIN) == {}
    assert f.take(T0 + 5 * MIN) == {"BTCUSDT": 0.0001}
    assert f.take(T0 + 6 * MIN) == {}
    f.poll(T0 + 30 * MIN)                               # polled again later: the same rate is not taken twice
    assert f.take(T0 + 40 * MIN) == {}


# ---------------------------------------------------------------- conditions (when)
def test_conditions_parse_describe_and_refusals():
    core = ["V39_ALL", "OBV_S", "N13_3OUTSIDE"]
    ms = C.resolve_members([
        {"strategy": "V39_ALL", "tf": "1h", "when": [{"symbol": "SOLUSDT", "session": "asia"},
                                                     {"side": "short", "btc_trend": "against", "weekend": False}]},
        {"pick": "core-N13_3OUTSIDE-30m-1", "when": {"symbol": ["BCHUSDT", "LTCUSDT"], "session": ["dawn", "us"]}},
        {"strategy": "OBV_S", "tf": "30m"}], core=core)
    assert ms[0].when == ((("symbol", ("SOLUSDT",)), ("session", ("asia",))),
                          (("side", -1), ("weekend", False), ("btc_trend", "against")))
    assert ms[1].when == ((("symbol", ("BCHUSDT", "LTCUSDT")), ("session", ("dawn", "us"))),)
    assert ms[2].when is None and ms[0].needs_btc and not ms[1].needs_btc
    d = ms[0].describe()
    assert "조건: (SOL + 아시아(09-17시)) 또는 (숏만 + 평일 + BTC 4시간 추세와 반대 방향)" in d
    hash(ms[0])                                                     # Members stay hashable
    for bad, text in [({"symbol": "XRPUSDT"}, "6개 코인"), ({"side": "up"}, "long"), ({"session": "night"}, "session"),
                      ({"weekend": "yes"}, "weekend"), ({"btc_trend": "up"}, "btc_trend"), ({"hour": 3}, "없는 조건"),
                      ("asia", "조건 목록"), (["asia"], "형식")]:
        with pytest.raises(C.ComboError, match=text):
            C.resolve_members([{"strategy": "OBV_S", "tf": "1h", "when": bad}], core=core)
    with pytest.raises(C.ComboError, match="알 수 없는 이름"):
        C.resolve_members([{"strategy": "OBV_S", "tf": "1h", "whne": [{"side": "long"}]}], core=core)


def test_conditions_kst_session_weekend_and_btc_trend():
    H = 3_600_000
    # T0 = Monday 2026-10-05 00:00 UTC = 09:00 KST
    assert [C.kst_session(T0 + h * H) for h in (0, 7, 8, 12, 13, 20, 21, 23)] == [
        "asia", "asia", "europe", "europe", "us", "us", "dawn", "dawn"]
    assert C.kst_session(T0 - 1) == "dawn" and C.kst_session(T0 + 21 * H - 1) == "us"
    fri = T0 + 4 * 24 * H                                         # Friday 00:00 UTC
    assert not C.kst_weekend(fri + 15 * H - 1) and C.kst_weekend(fri + 15 * H)    # Saturday 00:00 KST
    sun_end = fri + (15 + 48) * H                                  # Monday 00:00 KST
    assert C.kst_weekend(sun_end - 1) and not C.kst_weekend(sun_end)
    m = C.resolve_members([{"strategy": "V39_ALL", "tf": "1h", "when": [
        {"symbol": "SOLUSDT", "session": "asia"}, {"side": "short", "btc_trend": "against"}]}], core=["V39_ALL"])[0]
    up = lambda t: 1                                               # noqa: E731
    assert m.allows("SOLUSDT", 1, T0, up) == (True, "")            # first condition
    assert m.allows("SOLUSDT", 1, T0 + 8 * H, up) == (False, "조건 밖")
    assert m.allows("ETHUSDT", -1, T0 + 8 * H, up) == (True, "")   # short against an up trend
    assert m.allows("ETHUSDT", -1, T0 + 8 * H, lambda t: -1)[0] is False
    assert m.allows("ETHUSDT", -1, T0 + 8 * H, lambda t: None) == (False, "조건 밖(BTC 4시간 추세를 못 읽음)")
    assert m.allows("SOLUSDT", 1, T0, lambda t: None) == (True, "")      # a condition without the trend still holds


def _btc_rows(n, end_open, seed=3):
    rng = np.random.default_rng(seed)
    c = 60000 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    return [[end_open - (n - 1 - k) * C.H4, c[k], c[k] * 1.01, c[k] * 0.99, c[k], 1.0] for k in range(n)]


def test_btc_trend_equals_the_league_gate_and_fetches_only_when_a_bar_is_due():
    from candleague.rulex import gate_g1_arrays, gate_g1_stamp
    rows = _btc_rows(600, T0)                    # the last row opens at T0: still forming until T0 + 4h
    calls = []
    now = {"t": T0 + 3_600_000}

    def fetch():
        calls.append(now["t"])
        return [r for r in rows if r[0] <= now["t"]]

    bt = C.BtcTrend(fetch, lambda: now["t"])
    closed = [r for r in rows if r[0] + C.H4 <= now["t"]]
    cm, sg = gate_g1_arrays(np.array([r[0] + C.H4 for r in closed]), np.array([r[4] for r in closed]))
    for k in (60, 200, 598):
        t = int(cm[k]) + 5 * MIN
        want = gate_g1_stamp(cm, sg, t, 1)
        got = bt.sign_at(t)
        assert (None if got is None else got == 1) == want
    assert bt.sign_at(int(cm[10])) is None                         # the EMA is cold for the first 50 bars
    assert len(calls) == 1                                         # one fetch: every bar asked for was there
    t = T0 + 30 * MIN
    assert bt.sign_at(t) == int(sg[-1]) and len(calls) == 1
    now["t"] = T0 + C.H4 + 2_000                                   # the bar of T0 has closed
    assert bt.sign_at(T0 + C.H4 + MIN) is not None and len(calls) == 2
    assert int(bt.close_ms[-1]) == T0 + C.H4
    bad = C.BtcTrend(lambda: (_ for _ in ()).throw(OSError("down")), lambda: now["t"])
    assert bad.sign_at(T0) is None and "BTC 4h klines failed" in bad.errors[0]


def test_runner_keeps_signals_outside_the_conditions_from_both_accounts(tmp_path):
    w = World(tmp_path, members=[{"strategy": "V39_ALL", "tf": "15m", "when": [{"symbol": "ETHUSDT"}]},
                                 {"strategy": "OBV_S", "tf": "15m", "when": [{"btc_trend": "with"}]}])
    rising = [[T0 - (100 - k) * C.H4, 50000.0 + 100 * k, 0, 0, 50000.0 + 100 * k, 1.0] for k in range(100)]
    btc = C.BtcTrend(lambda: rising, lambda: w.now)
    w.run = C.ComboRunner(w.cfg, w.members, w.book, w.store, w.note, None, now_ms=lambda: w.now,
                          prices=lambda: {}, btc=btc)
    w.now = T0 + 5_000
    w.run.poll()
    B = T0 + 15 * MIN
    w.add_minutes(T0, 15)
    w.signal("V39_ALL", "BTCUSDT", 1, B)           # outside: V39 only on ETH
    w.signal("OBV_S", "ETHUSDT", -1, B)            # outside: a short against the up trend
    w.signal("OBV_S", "SOLUSDT", 1, B)             # inside: a long with the up trend
    w.add_minutes(B, 1)
    w.now = B + 65_000
    w.run.poll()
    p = w.engine().position
    assert p is not None and p.symbol == "SOLUSDT" and p.signal.strategy_id == "OBV_S"
    rows = w.store.conn.execute("SELECT strategy, symbol, status, data FROM signal_log ORDER BY id").fetchall()
    st = {(r[0], r[1]): (r[2], json.loads(r[3]).get("why")) for r in rows}
    assert st[("V39_ALL@15m", "BTCUSDT")] == ("FILTERED", "조건 밖")
    assert st[("OBV_S@15m", "ETHUSDT")] == ("FILTERED", "조건 밖")
    assert st[("OBV_S@15m", "SOLUSDT")][0] == "SUBMITTED"
    for aid in (C.ACCOUNT, C.FLIP_ACCOUNT):        # the filtered signals reached neither account
        n = w.store.conn.execute("SELECT COUNT(*) FROM outcomes WHERE account_id = ?", (aid,)).fetchone()[0]
        assert n == 1
    assert w.run.counts["V39_ALL@15m"] == {"filtered": 1}
    assert w.run.counts["OBV_S@15m"] == {"filtered": 1, "submitted": 1}
