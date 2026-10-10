"""paperbot/paramshadow.py, the custom-value shadow (non-trading), on synthetic bars: the param_defs defaults equal the
locked signals of all 36 strategies; the variant list follows the study; the replay that skips idle engines gives
the same trades as stepping every engine every minute; a night split in pieces gives the same result as one night;
parity counts the real account's entries; the luck rule; a new run starts over; paper3.db is never written; the
unit files and the install script."""

import json
import os
import sqlite3
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from paperbot import paramshadow as PS
from paperbot import sweepsig
from paperbot.config import V3_SYMBOLS, v3_settings
from paperbot.engine import PaperEngine
from paperbot.margin import BracketTier, Brackets
from paperbot.models import Bar, Signal
from paperbot.store3 import Store3

REPO = Path(__file__).resolve().parent.parent
DAY = 86_400_000
D0 = 1_791_158_400_000                        # 2026-10-05 00:00 UTC
RUN_START = D0 + 13 * 3_600_000              # the run started 13:00 UTC
STRATS = ["S2_ST_ROC", "S1_EMA_RSI_CHOP"]
TFS = ("15m", "1h")
SYMS = ("BTCUSDT", "ETHUSDT")
P0 = {"BTCUSDT": 60000.0, "ETHUSDT": 2500.0}
HIST_DAYS = 64                                # > the 15m and 1h live windows (2 x 30 days of warm-up)


def _synth5(seed: int, p0: float, days: int = HIST_DAYS + 5):
    n = days * 288
    rng = np.random.default_rng(seed)
    r = rng.standard_t(4, n) * 0.0018
    c = p0 * np.exp(np.cumsum(r))
    o = np.r_[p0, c[:-1]]
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.0009, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.0009, n)))
    v = rng.lognormal(10, 0.6, n)
    ts = D0 - HIST_DAYS * DAY + 300_000 * np.arange(n)
    return ts.astype(np.int64), o, hi, lo, c, v


@pytest.fixture(scope="module")
def data():
    return {s: _synth5(i + 3, P0[s]) for i, s in enumerate(SYMS)}


def _steps_from(data):
    """1m steps made from the 5m bars (each 5m bar split into five minutes; funding every 8 h)."""
    def fetch(rest, symbols, start, end):
        out = []
        cols = {s: tuple(a[(data[s][0] >= start) & (data[s][0] < end)] for a in data[s]) for s in symbols}
        n = len(cols[symbols[0]][0])
        for j in range(n):
            for q in range(5):
                t0 = int(cols[symbols[0]][0][j]) + q * 60_000
                bars = {}
                for s in symbols:
                    ts, o, h, l, c, _v = cols[s]
                    oo = o[j] + (c[j] - o[j]) * q / 5
                    cc = o[j] + (c[j] - o[j]) * (q + 1) / 5
                    hh = max(oo, cc) + (h[j] - max(o[j], c[j])) * (1.0 if q == 2 else 0.3)
                    ll = min(oo, cc) - (min(o[j], c[j]) - l[j]) * (1.0 if q == 3 else 0.3)
                    bars[s] = Bar(s, t0, t0 + 59_999, oo, hh, ll, cc, oo, hh, ll, cc)
                fund = {s: 0.0001 for s in symbols} if t0 % (8 * 3_600_000) == 0 else {}
                out.append((t0, bars, fund))
        return out
    return fetch


BRACKETS = {s: Brackets([BracketTier(300_000, 75, 0.005, 0.0), BracketTier(800_000, 50, 0.01, 1500.0),
                         BracketTier(3_000_000, 20, 0.025, 13500.0)]) for s in SYMS}
SPECS = {s: {} for s in SYMS}


def _paper_db(path, real_trades=()):
    st = Store3(str(path))
    lib = sweepsig.lib()
    from paperbot.sigservice import strategy_names
    for n in strategy_names(lib):
        for tf in ("15m", "30m", "1h", "4h"):
            st.add_account(f"{n}@{tf}", n, tf, "strategy", RUN_START, "paper-v4")
    st.add_account("RANDOM_1@15m", "RANDOM_1", "15m", "random", RUN_START, "paper-v4")
    st.put_state("run", RUN_START, {"taker_fee": 0.0005})
    for aid, rec in real_trades:
        st.trade(aid, rec)
    st.commit()
    st.close()
    return str(path)


def _run(tmp_path, data, now, max_days=PS.MAX_DAYS, db=None, out=None, strategies=STRATS):
    Path(tmp_path).mkdir(parents=True, exist_ok=True)
    db = db or _paper_db(tmp_path / "paper3.db")
    out = out or str(tmp_path / "out")
    return PS.run(db, out, PS.FrameSource(data), None, None, BRACKETS, SPECS, now, max_days=max_days,
                  strategies=strategies, tfs=TFS, symbols=SYMS, fetch_steps=_steps_from(data),
                  log=lambda s: None, brackets_src="test")


# ---------------------------------------------------------------- definitions
def test_defaults_equal_the_locked_signals_of_all_36(data):
    """param_defs signals() with no override == the locked compute_signals (DOGE: the live doge_join)."""
    from paperbot.sigservice import doge_join, strategy_names, window_5m
    lib = sweepsig.lib()
    tf = "15m"
    cols = data["BTCUSDT"]
    end = D0 + 2 * DAY
    keep = cols[0] < end
    df = PS.chart_frame(lib, tuple(a[keep][-(window_5m(lib, tf) + 2 * 288):] for a in cols), tf)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        locked = lib.compute_signals({"X": df}, tf, list(lib.NAMES), strict=False)
    w = lib.warmup_bars(tf)
    man = PS.defs_manifest()
    fired = 0
    for n in strategy_names(lib):
        mod = PS.param_module(n, man)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            lo, sh = mod.signals(df, tf)
        side = np.where(lo, 1, np.where(sh, -1, 0))
        ref = doge_join(locked["DOGE_L"]["X"], locked["DOGE_S"]["X"]) if n == "DOGE" else np.asarray(locked[n]["X"])
        assert np.array_equal(side[w:], np.asarray(ref)[w:]), n
        fired += int(np.count_nonzero(ref[w:]))
    assert fired > 100


def test_variants_follow_the_study():
    man = PS.defs_manifest()
    for n in ("S2_ST_ROC", "N02_ST_KST", "DOGE"):
        mod = PS.param_module(n, man)
        vs = PS.variants_of(mod)
        assert vs[0]["key"] == "base" and vs[0]["ov"] == {} and vs[0]["combo"] == "base"
        k = len(mod.PARAMS)
        singles = [v for v in vs if v["combo"] == "single"]
        pairs = [v for v in vs if v["combo"] == "pair"]
        assert len(singles) == 4 * k and len(pairs) == 4 * k * (k - 1) // 2 and len(vs) == 1 + len(singles) + len(pairs)
        assert len({v["key"] for v in vs}) == len(vs)
        for v in singles:
            assert list(v["ov"]) == [v["param"]] and v["mult"] in PS.MULTS and len(v["parts"]) == 1
        one = {(v["param"], v["mult"]): v["ov"][v["param"]] for v in singles}
        for v in pairs:                    # two different numbers, each at a near step, the singles' own values
            (a, b) = v["parts"]
            assert a["param"] != b["param"] and {a["mult"], b["mult"]} <= set(PS.PAIR_MULTS)
            assert v["ov"] == {a["param"]: one[(a["param"], a["mult"])], b["param"]: one[(b["param"], b["mult"])]}
            assert v["param"] is None and v["key"] == f"{a['param']}x{a['mult']:g}+{b['param']}x{b['mult']:g}"


def test_a_changed_definition_is_refused(tmp_path, monkeypatch):
    from paperbot import entry_marks as EM
    fake = tmp_path / "study"
    (fake / "param_defs").mkdir(parents=True)
    src = Path(EM.STUDY) / "param_defs" / "S2_ST_ROC.py"
    (fake / "param_defs" / "S2_ST_ROC.py").write_bytes(src.read_bytes() + b"\n# edited\n")
    monkeypatch.setattr(EM, "STUDY", str(fake))
    with pytest.raises(PS.ParamShadowError, match="locked"):
        PS.param_module("S2_ST_ROC", PS.defs_manifest())


# ---------------------------------------------------------------- replay
def test_skipping_idle_engines_gives_the_same_trades(data):
    """replay_day steps only engines with a position or a pending signal; stepping every engine every minute (as
    the live book does) must give identical trades."""
    settings = v3_settings(taker_fee=0.0005)
    fetch = _steps_from(data)
    steps = fetch(None, list(SYMS), D0, D0 + DAY)
    rng = np.random.default_rng(7)
    by_close = {}
    aids = [f"X@15m#k{i}" for i in range(6)]
    for t in range(D0 + 900_000, D0 + DAY, 900_000):
        for aid in aids:
            if rng.random() < 0.15:
                sym = SYMS[int(rng.integers(2))]
                price = float(data[sym][4][np.searchsorted(data[sym][0], t) - 1])
                sig = Signal(ts=t - 1, symbol=sym, timeframe="15m", strategy_id="X", side=int(rng.choice([1, -1])),
                             stop_price=0.0, tier="best", atr=price * 0.004,
                             meta={"stop_dist": price * 0.008, "account": aid})
                by_close.setdefault(t, []).append((aid, sig))
    a = {aid: PaperEngine(settings, BRACKETS, book=aid) for aid in aids}
    PS.replay_day(a, set(), by_close, steps, BRACKETS)
    b = {aid: PaperEngine(settings, BRACKETS, book=aid) for aid in aids}
    for ts, bars, funding in steps:
        for e in b.values():
            PS.stamp_ref(e, bars)
            e.step(bars, funding)
        for aid, sig in by_close.get(ts + 60_000, ()):
            b[aid].submit(sig)
    n = 0
    for aid in aids:
        ta = [(t.symbol, t.entry_time, t.exit_time, t.exit_reason, round(t.pnl, 9)) for t in a[aid].trades]
        tb = [(t.symbol, t.entry_time, t.exit_time, t.exit_reason, round(t.pnl, 9)) for t in b[aid].trades]
        assert ta == tb, aid
        assert a[aid].wallet == pytest.approx(b[aid].wallet, abs=1e-9)
        n += len(ta)
    assert n > 10


def _trades(out):
    conn = sqlite3.connect(os.path.join(out, "paramshadow.db"))
    rows = conn.execute("SELECT account, symbol, side, entry_time, exit_time, exit_reason, round(pnl, 6) FROM trades "
                        "ORDER BY account, exit_time, entry_time").fetchall()
    counts = conn.execute("SELECT account, n, diff FROM sigcounts ORDER BY account").fetchall()
    conn.close()
    return rows, counts


def test_a_night_in_pieces_equals_one_night(tmp_path, data):
    now = D0 + 3 * DAY + 3_600_000                     # days 10-05 (from 13:00), 10-06, 10-07
    one = _run(tmp_path / "a", data, now)
    assert one["status"] == "ok" and one["through_day"] == "2026-10-07" and one["days"] == 3
    db = _paper_db(tmp_path / "b.db")
    out = str(tmp_path / "b")
    s1 = _run(tmp_path, data, now, max_days=1, db=db, out=out)
    assert s1["status"] == "filling" and s1["days_remaining"] == 2 and "채우는 중" in s1["line_ko"]
    _run(tmp_path, data, now, max_days=1, db=db, out=out)
    s3 = _run(tmp_path, data, now, max_days=1, db=db, out=out)
    assert s3["status"] == "ok" and s3["days_remaining"] == 0
    assert _trades(str(tmp_path / "a" / "out")) == _trades(out)
    assert json.dumps(one["cells"], sort_keys=True) == json.dumps(s3["cells"], sort_keys=True)
    again = _run(tmp_path, data, now, max_days=1, db=db, out=out)       # nothing left: no change
    assert _trades(out) == _trades(str(tmp_path / "a" / "out")) and again["days"] == 3
    rows, counts = _trades(out)
    assert rows and min(r[3] for r in rows) > RUN_START                  # nothing before the run started
    assert any(c[2] > 0 for c in counts) and all(c[2] == 0 for c in counts if c[0].endswith("#base"))


def test_summary_parity_and_paper3_untouched(tmp_path, data):
    """The real account's entries that the recomputed default also has are counted; paper3.db is opened read-only."""
    now = D0 + 2 * DAY + 3_600_000
    probe = _run(tmp_path / "probe", data, now)
    conn = sqlite3.connect(str(tmp_path / "probe" / "out" / "paramshadow.db"))
    base = conn.execute("SELECT symbol, side, entry_time, exit_time, pnl, equity_after FROM trades WHERE account = ? "
                        "ORDER BY exit_time", ("S2_ST_ROC@15m#base",)).fetchall()
    conn.close()
    assert len(base) >= 3
    from paperbot.models import TradeRecord
    recs = []
    for sym, side, et, xt, pnl, eq in base[:-1]:                         # the real account has all but one
        recs.append(("S2_ST_ROC@15m", TradeRecord(strategy_id="S2_ST_ROC", symbol=sym, timeframe="15m", side=side,
                     signal_ts=et - 1, entry_time=et + 20_000, entry_price=1.0, exit_time=xt, exit_price=1.0,
                     exit_reason="SL", qty=1.0, leverage=30, tier="normal", margin=100.0, stop_price=1.0,
                     tp_price=float("nan"), liq_price=0.5, fees=0.0, funding=0.0, pnl=pnl, roe=0.0,
                     price_move=0.0, mae_price=1.0, mfe_price=1.0, equity_after=eq, score=0.0)))
    db = _paper_db(tmp_path / "real.db", recs)
    before = Path(db).read_bytes()
    s = _run(tmp_path, data, now, db=db, out=str(tmp_path / "real"))
    cell = next(c for c in s["cells"] if c["strategy"] == "S2_ST_ROC" and c["tf"] == "15m")
    assert cell["parity"]["real_trades"] == len(base) - 1 and cell["parity"]["same"] == len(base) - 1
    assert cell["parity"]["share"] == pytest.approx((len(base) - 1) / len(base), abs=1e-4)
    assert cell["real"]["trades"] == len(base) - 1
    assert Path(db).read_bytes() == before
    assert probe["overview"]["cells"] == len(STRATS) * len(TFS)
    for c in s["cells"]:
        assert c["k"] == sum(1 for v in c["variants"] if not v["same_as_base"])
        for v in c["variants"]:
            assert v["diff_pnl"] == pytest.approx(v["pnl"] - c["base"]["pnl"], abs=0.02)
            if v["same_as_base"]:
                assert v["star"] is False and v["luck"] is None
    txt = (tmp_path / "real" / "last.txt").read_text(encoding="utf-8")
    assert txt.startswith("커스텀값 그림자 10/6까지 2일")


def test_luck_rule():
    base = {"trades": 40, "mean_ret": 0.0, "sd_ret": 0.05}
    good = {"trades": 40, "mean_ret": 0.04, "sd_ret": 0.05}
    meh = {"trades": 40, "mean_ret": 0.01, "sd_ret": 0.05}
    small = {"trades": 5, "mean_ret": 0.5, "sd_ret": 0.05}
    assert PS.luck_test(good, base, 16)["beyond"] is True
    assert PS.luck_test(meh, base, 16)["beyond"] is False
    r = PS.luck_test(small, base, 16)
    assert r["small"] is True and r["beyond"] is False
    # more variants in a cell need a larger z
    assert PS.luck_test(meh, base, 16)["z_need"] > PS.luck_test(meh, base, 1)["z_need"]


def test_a_new_run_starts_over(tmp_path, data):
    now = D0 + 2 * DAY + 3_600_000
    db = _paper_db(tmp_path / "p.db")
    out = str(tmp_path / "o")
    _run(tmp_path, data, now, db=db, out=out)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE accounts SET created_ts = ?", (RUN_START + DAY,))
    conn.commit()
    conn.close()
    s = _run(tmp_path, data, now, db=db, out=out)
    assert s["run_start_ms"] == RUN_START + DAY and s["days"] == 1
    rows, _ = _trades(out)
    assert all(r[3] > RUN_START + DAY for r in rows)


def test_no_paper_db_and_show(tmp_path, capsys):
    out = str(tmp_path / "o")
    s = PS.run(str(tmp_path / "missing.db"), out, None, None, None, {}, {}, D0)
    assert s["status"] == "no_run"
    assert PS.read_summary(out).startswith("커스텀값 그림자")
    assert PS.main(["show", "--out", out]) == 0
    assert "커스텀값 그림자" in capsys.readouterr().out


def test_error_file(tmp_path):
    PS.write_error(str(tmp_path), "5m klines of BTCUSDT unavailable", D0)
    d = json.loads((tmp_path / "error.json").read_text(encoding="utf-8"))
    assert "계산 못 함" in d["line_ko"] and "가격 자료" in d["line_ko"] and "unavailable" not in d["line_ko"]
    assert "unavailable" in d["error"]
    assert "정의 파일" in PS.error_ko("param_defs/X.py: sha256 ab != locked cd")
    assert "개발자" in PS.error_ko("KeyError: x")
    PS.write_outputs(str(tmp_path), {"status": "no_run", "line_ko": "커스텀값 그림자: x"})
    assert not (tmp_path / "error.json").exists()


# ---------------------------------------------------------------- deploy
def test_units_and_install():
    svc = (REPO / "deploy" / "paperbot-paramshadow.service").read_text()
    tim = (REPO / "deploy" / "paperbot-paramshadow.timer").read_text()
    assert "python -m paperbot.paramshadow run" in svc and "--out /var/lib/paperbot/paramshadow" in svc
    assert "MemoryMax=" in svc and "Nice=" in svc and "OnFailure=paperbot-failed@%n.service" in svc
    assert "-/var/lib/paperbot/paper3.db" in svc and "ReadOnlyPaths=" in svc
    assert "OnCalendar=" in tim
    inst = (REPO / "deploy" / "install.sh").read_text()
    assert "paperbot-paramshadow.service paperbot-paramshadow.timer" in inst
    assert "enable --now paperbot-paramshadow.timer" in inst
    assert "paperbot-paramshadow.service" in inst.split("JOBS=", 1)[1].split("n=0", 1)[0]


def test_not_a_trading_file():
    from paperbot import runinfo
    assert "paperbot/paramshadow.py" not in runinfo.TRADING_FILES
    for group in (runinfo.DS_FILES, runinfo.REEL_FILES):
        assert "paperbot/paramshadow.py" not in group


# ---------------------------------------------------------------- the specialists' packet
def test_specialist_packet_carries_live_params(tmp_path, data, monkeypatch):
    from paperbot.agents import packets3 as P3
    now = D0 + 2 * DAY + 3_600_000
    s = _run(tmp_path / "lp", data, now)
    path = str(tmp_path / "lp" / "out" / "last.json")
    lp = P3.live_params("S2_ST_ROC", path)
    assert lp["through_day"] == s["through_day"] and [t["tf"] for t in lp["timeframes"]] == list(TFS)
    for t in lp["timeframes"]:
        assert len(t["top"]) <= P3.LIVE_PARAMS_TOP and all(x["diff_pnl"] > 0 for x in t["top"])
        assert t["top"] == sorted(t["top"], key=lambda x: -x["diff_pnl"])
    assert len(json.dumps(lp, ensure_ascii=False)) < 4000
    assert P3.live_params("NOPE", path) is None
    assert P3.live_params("S2_ST_ROC", str(tmp_path / "missing.json")) is None
    monkeypatch.setattr(P3, "PARAMSHADOW_DIR", str(tmp_path / "lp" / "out"))
    sp = P3.specialist_packet({"pass_check": {}, "by_strategy": {}}, "S2_ST_ROC")
    assert sp["live_params"]["timeframes"][0]["tf"] == "15m"
    prompt = (REPO / "paperbot" / "agents" / "prompts3" / "rooms_specialist.md").read_text(encoding="utf-8")
    assert "`specialist.live_params`" in prompt


def test_a_day_with_too_few_minutes_is_not_replayed(tmp_path, data):
    now = D0 + 2 * DAY + 3_600_000
    full = _steps_from(data)

    def short(rest, symbols, start, end):
        steps = full(rest, symbols, start, end)
        return steps if start == D0 else steps[:600]               # the second day comes back in part
    db = _paper_db(tmp_path / "p.db")
    out = str(tmp_path / "o")
    Path(out).mkdir()
    with pytest.raises(PS.ParamShadowError, match="tried again next night"):
        PS.run(db, out, PS.FrameSource(data), None, None, BRACKETS, SPECS, now, strategies=STRATS, tfs=TFS,
               symbols=SYMS, fetch_steps=short, log=lambda s: None)
    conn = sqlite3.connect(os.path.join(out, "paramshadow.db"))
    assert [r[0] for r in conn.execute("SELECT day FROM days")] == ["2026-10-05"]
    conn.close()
    s = _run(tmp_path, data, now, db=db, out=out)                    # the next night fills the day
    assert s["through_day"] == "2026-10-06" and s["days"] == 2


def test_entry_minute_gets_the_fill_minutes_open_as_reference(data):
    """stamp_ref gives a pending signal the next minute's open (the same fill), so the engine skips the lock step on
    the entry minute as it does for live signals."""
    settings = v3_settings(taker_fee=0.0005)
    steps = _steps_from(data)(None, list(SYMS), D0, D0 + DAY)
    e = PaperEngine(settings, BRACKETS, book="X")
    t = D0 + 900_000
    price = float(data["BTCUSDT"][4][np.searchsorted(data["BTCUSDT"][0], t) - 1])
    by_close = {t: [("X", Signal(ts=t - 1, symbol="BTCUSDT", timeframe="15m", strategy_id="X", side=1, stop_price=0.0,
                                 tier="best", atr=price * 0.004, meta={"stop_dist": price * 0.008, "account": "X"}))]}
    PS.replay_day({"X": e}, set(), by_close, steps, BRACKETS)
    first = next(b for ts, b, _f in steps if ts == t)["BTCUSDT"]
    assert by_close[t][0][1].meta["ref_price"] == pytest.approx(first.open)
    entry = e.trades[0].entry_price if e.trades else e.position.entry_price
    assert entry == pytest.approx(first.open * (1 + settings.slippage_frac))      # the same fill as without it


def test_a_missing_minute_does_not_drop_a_signal(data):
    settings = v3_settings(taker_fee=0.0005)
    steps = _steps_from(data)(None, list(SYMS), D0, D0 + DAY)
    t = D0 + 3_600_000                                    # a 1h close
    gap = [st for st in steps if st[0] != t - 60_000]     # the minute ending at the close is missing
    price = float(data["BTCUSDT"][4][np.searchsorted(data["BTCUSDT"][0], t) - 1])
    sig = Signal(ts=t - 1, symbol="BTCUSDT", timeframe="1h", strategy_id="X", side=1, stop_price=0.0, tier="best",
                 atr=price * 0.004, meta={"stop_dist": price * 0.008, "account": "X"})
    e = PaperEngine(settings, BRACKETS, book="X")
    PS.replay_day({"X": e}, set(), {t: [("X", sig)]}, gap, BRACKETS)
    assert e.trades or e.position is not None
    last = PaperEngine(settings, BRACKETS, book="Y")       # a close after the day's last step stays pending
    late = Signal(ts=D0 + DAY - 1, symbol="BTCUSDT", timeframe="1h", strategy_id="X", side=1, stop_price=0.0,
                  tier="best", atr=price * 0.004, meta={"stop_dist": price * 0.008, "account": "Y"})
    PS.replay_day({"Y": last}, set(), {D0 + DAY: [("Y", late)]}, steps[:-30], BRACKETS)
    assert last.pending == [late]


def test_a_coin_missing_a_whole_day_is_caught_and_old_short_days_go_in_with_a_note(tmp_path, data):
    full = _steps_from(data)

    def no_eth(rest, symbols, start, end):
        steps = full(rest, symbols, start, end)
        if start == D0 + DAY:
            steps = [(t, {s: b for s, b in bars.items() if s != "ETHUSDT"}, f) for t, bars, f in steps]
        return steps
    db = _paper_db(tmp_path / "p.db")
    out = str(tmp_path / "o")
    Path(out).mkdir()
    with pytest.raises(PS.ParamShadowError, match="ETH 0분"):
        PS.run(db, out, PS.FrameSource(data), None, None, BRACKETS, SPECS, D0 + 2 * DAY + 3_600_000,
               strategies=STRATS, tfs=TFS, symbols=SYMS, fetch_steps=no_eth, log=lambda s: None)
    # four days later the day is replayed with what exists, and the summary says so
    s = PS.run(db, out, PS.FrameSource(data), None, None, BRACKETS, SPECS, D0 + 5 * DAY + 3_600_000,
               strategies=STRATS, tfs=TFS, symbols=SYMS, fetch_steps=no_eth, log=lambda s: None)
    assert s["through_day"] == "2026-10-09" and any("모자란 채로" in n and "ETH 0분" in n for n in s["notes"])


def test_the_fetcher_reads_funding_once_per_chunk_and_matches_daily3(data):
    from paperbot import daily3

    class Rest:
        def __init__(self):
            self.calls = []

        def klines(self, s, iv, start_time=None, limit=1500):
            self.calls.append(("k", s))
            ts, o, h, l, c, v = data[s]
            m = (ts >= start_time)
            idx = np.flatnonzero(m)[:limit]
            return [[int(ts[i]), o[i], h[i], l[i], c[i], v[i], int(ts[i]) + 59_999] for i in idx]

        def mark_klines(self, s, iv, start_time=None, limit=1500):
            self.calls.append(("m", s))
            return self.klines(s, iv, start_time, limit)

        def funding_rates(self, s, start_time=None, limit=1000):
            self.calls.append(("f", s))
            return [{"fundingTime": t, "fundingRate": "0.0001"} for t in range(D0, D0 + 3 * DAY, 8 * 3_600_000)
                    if t >= start_time]
    r1 = Rest()
    fetch = PS.make_fetcher(r1, list(SYMS), D0, D0 + 3 * DAY, sleep=lambda s: None)
    mine = [fetch(r1, list(SYMS), D0 + d * DAY, D0 + (d + 1) * DAY) for d in range(3)]
    assert sum(1 for c in r1.calls if c[0] == "f") == len(SYMS)               # once per coin for the chunk
    r2 = Rest()
    theirs = [daily3.fetch_steps(r2, list(SYMS), D0 + d * DAY, D0 + (d + 1) * DAY) for d in range(3)]
    assert sum(1 for c in r2.calls if c[0] == "f") == 3 * len(SYMS)
    for a, b in zip(mine, theirs):
        assert [(t, sorted(x), f) for t, x, f in a] == [(t, sorted(x), f) for t, x, f in b]


def test_luck_compares_starred_cells(tmp_path, data):
    now = D0 + 2 * DAY + 3_600_000
    s = _run(tmp_path / "lc", data, now)
    o = s["overview"]
    assert o["star_cells"] == sum(1 for c in s["cells"] if c["stars"]) and o["star_cells"] <= o["stars"]
    assert "★ 붙은 칸" in s["line_ko"] and "칸)" in s["line_ko"]


def test_any_failure_writes_the_error_file_and_exits_2(tmp_path, monkeypatch):
    db = tmp_path / "paper3.db"
    db.write_bytes(b"")
    monkeypatch.setattr(PS, "run", lambda *a, **k: (_ for _ in ()).throw(KeyError("boom")))
    import paperbot.live as L
    monkeypatch.setattr(L, "_rest", lambda: type("R", (), {"exchange_info": lambda self, s: {}})())
    monkeypatch.setattr(L, "load_brackets", lambda *a, **k: ({}, "x"))
    assert PS.main(["run", "--db", str(db), "--out", str(tmp_path / "o")]) == 2
    d = json.loads((tmp_path / "o" / "error.json").read_text(encoding="utf-8"))
    assert "KeyError" in d["error"] and "개발자" in d["line_ko"]


def test_the_packet_drops_another_runs_shadow(tmp_path, data):
    from paperbot.agents import packets3 as P3
    s = _run(tmp_path / "rs", data, D0 + 2 * DAY + 3_600_000)
    path = str(tmp_path / "rs" / "out" / "last.json")
    assert P3.live_params("S2_ST_ROC", path, run_start=s["run_start_ms"]) is not None
    assert P3.live_params("S2_ST_ROC", path, run_start=s["run_start_ms"] + DAY) is None
