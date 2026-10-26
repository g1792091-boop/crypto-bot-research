"""The TradingView indicator of the VWAP 개선판 bot (tradingview/vwap-bot-signals.pine, owners 10-26 "지금 돌아가고 있는 vwap
실거래봇 트뷰 적용되게 시그널 지표 만들어줘"): its method, run bar by bar in Python (tradingview/pine_mirror.py), against
the bot's own code on the same bars — the VWAP fail and CMO sandwich signals (paperbot/strategy_view_defs, checked
against the live signals there), the 4h judges (paperbot/trendjudge.py, full history and the bot's 300-bar frames), the
volatility gate (paperbot/entrygates.py), which 4h bar a 30m close reads, the time blocks (paperbot/combo.py,
paperbot/events.py) and the ladder (paperbot/ladder.py, ladder2.py). The script's numbers and calendars must be the
bot's (deploy/combo.vwap.json, data/macro_events.csv, paperbot/sessions.py)."""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tradingview"))
import pine_mirror as PM  # noqa: E402
from paperbot import sweepsig  # noqa: E402

sweepsig.lib()                                       # the locked indicator library on sys.path, as the bot loads it
from paperbot import combo as C  # noqa: E402
from paperbot import entrygates as G  # noqa: E402
from paperbot import ladder as LD  # noqa: E402
from paperbot import trendjudge as TJ  # noqa: E402
from paperbot.sessions import NYSE_HOLIDAYS  # noqa: E402
from paperbot.strategy_view_defs.DS_F6_VWAP_FAIL import view_DS_F6_VWAP_FAIL  # noqa: E402
from paperbot.strategy_view_defs.S3_CMO_SANDWICH import view_S3_CMO_SANDWICH  # noqa: E402

PINE = os.path.join(ROOT, "tradingview", "vwap-bot-signals.pine")
T0 = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp() * 1000)


def _walk30(n: int, seed: int) -> np.ndarray:
    """30m rows [open_ms, o, h, l, c, v]: a walk with trending stretches and quiet ones (the signals all fire)."""
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.normal(0, 0.0012, n // 120 + 1), 120)[:n]
    vol = np.repeat(rng.uniform(0.002, 0.007, n // 300 + 1), 300)[:n]
    c = 100.0 * np.exp(np.cumsum(drift + rng.normal(0, 1, n) * vol))
    o = np.r_[100.0, c[:-1]] * (1 + rng.normal(0, 0.0005, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.002, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.002, n)))
    v = rng.lognormal(3, 0.6, n)
    t = T0 + np.arange(n) * PM.MS30
    return np.column_stack([t, o, h, l, c, v])


def _agg(a30: np.ndarray, ms: int) -> np.ndarray:
    """Higher bars from 30m rows (Binance's: aligned to UTC, open first, high max, low min, close last, volume sum)."""
    key = (a30[:, 0].astype(np.int64) // ms) * ms
    out = []
    for k in np.unique(key):
        g = a30[key == k]
        if len(g) * PM.MS30 != ms:
            continue
        out.append([k, g[0, 1], g[:, 2].max(), g[:, 3].min(), g[-1, 4], g[:, 5].sum()])
    return np.array(out)


def _df(a: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame({"ts": pd.to_datetime(a[:, 0].astype(np.int64), unit="ms", utc=True), "open": a[:, 1],
                         "high": a[:, 2], "low": a[:, 3], "close": a[:, 4], "volume": a[:, 5]})


@pytest.fixture(scope="module")
def world():
    a30 = _walk30(8000, 11)                          # ~5.5 months of 30m bars
    return {"a30": a30, "a1h": _agg(a30, PM.MS1H), "a4h": _agg(a30, PM.MS4H)}


def _and(conds):
    return np.logical_and.reduce([np.asarray(x, bool) for _k, x in conds])


# ====================================================================== the signals
def test_vwap_fail_is_the_bots_on_every_bar(world):
    a = world["a30"]
    view = view_DS_F6_VWAP_FAIL(_df(a), "30m")
    want = np.where(_and(view["long"]), 1, np.where(_and(view["short"]), -1, 0))
    got = PM.f6(a)
    assert (got["sig"] == want).all()
    assert np.allclose(got["vwap"], view["overlays"][0]["values"], equal_nan=True)
    assert (want == 1).sum() > 20 and (want == -1).sum() > 20                 # the walk really fires both sides


def test_cmo_sandwich_is_the_bots_after_the_warm_up(world):
    a = world["a1h"]
    view = view_S3_CMO_SANDWICH(_df(a), "1h")
    want = np.where(_and(view["long"]), 1, np.where(_and(view["short"]), -1, 0))
    got = PM.s3(a, 720, 0.8)["sig"]
    assert (got[300:] == want[300:]).all()                                     # the ATR seeds differ only at the start
    assert (want[300:] != 0).sum() >= 5


def test_the_4h_judges_are_the_bots(world):
    a = world["a4h"]
    df = _df(a)
    full = TJ.vote_arrays(df)
    mine = PM.judges(a)
    for k in ("V39", "S6", "OBV", "N12"):
        assert (mine[k][200:] == full[k][200:]).all(), k                       # same formulas, Pine's seeds forgotten
    # the bot judges each closed 4h bar on its last 300 bars (trendjudge.KEEP): the raw vote nearly always agrees
    raw_m = np.where(mine["up"] >= 3, 1, np.where(mine["down"] >= 3, -1, 0))
    same = total = 0
    for i in range(400, len(a)):
        j = TJ.judge_frame(df.iloc[i - TJ.KEEP + 1:i + 1].reset_index(drop=True), "BTCUSDT", "4h", TJ.TrendRules(vote_min=3))
        same += int(j.raw == raw_m[i])
        total += 1
    assert total > 500 and same / total >= 0.99, (same, total)


def test_a_30m_close_reads_the_same_4h_bar_as_the_bot():
    for k in range(200):
        close = T0 + (k + 1) * PM.MS30
        need = close - close % PM.MS4H - PM.MS4H                               # trendjudge.Klines.frame
        assert PM.judged_4h_open(close) == need


def test_the_volatility_gate_is_the_bots(world):
    for key, tf, win in (("a30", "30m", 1440), ("a1h", "1h", 720)):
        a = world[key]
        h, l, c = a[:, 2], a[:, 3], a[:, 4]
        atrp = PM.pine_atr(h, l, c, 14) / c
        buf = []
        mine = []
        for i in range(len(c)):
            buf.append(atrp[i])
            mine.append(PM.quantile_window(buf, win, 0.8))
        for i in range(len(c) - 1, max(win + 300, len(c) - 400), -37):
            lo = max(0, i - (win + G.WARM) + 1)
            ap, qv = G.atr_pct_and_q(h[lo:i + 1], l[lo:i + 1], c[lo:i + 1], 14, win, 0.8)
            assert atrp[i] == pytest.approx(ap, rel=1e-6) and mine[i] == pytest.approx(qv, rel=1e-6), (tf, i)
        assert G.window_bars(tf, 30) == win


# ====================================================================== times, ladder, numbers
def test_the_time_blocks_are_the_bots():
    from paperbot import events as EV
    evs = [int(datetime.fromisoformat(r[0].replace("Z", "+00:00")).timestamp() * 1000)
           for r in csv.reader(open(os.path.join(ROOT, "data", "macro_events.csv"), encoding="utf-8"))
           if r and not r[0].startswith("#") and r[0] != "ts_utc"]
    start = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp() * 1000)
    keep = EV.PATH
    try:
        EV.PATH = os.path.join(ROOT, "data", "macro_events.csv")
        EV.reset()
        for ts in range(start, start + 92 * PM.MSDAY, 30 * PM.MIN // 2):          # every 15 minutes, Oct-Dec 2026
            assert PM.weekend(ts) == C.kst_weekend(ts), ts
            assert PM.us_open(ts, NYSE_HOLIDAYS) == bool(C.us_open_pause(ts, 30, 30)), ts
            assert PM.macro(ts, evs) == bool(EV.near(ts, 30 * PM.MIN, 30 * PM.MIN)), ts
    finally:
        EV.PATH = keep
        EV.reset()


def test_the_ladder_is_the_bots():
    lad = C.ComboConfig.from_file(os.path.join(ROOT, "deploy", "combo.vwap.json")).ladder_spec
    rt = 2 * (0.0005 + 0.0002)
    for best in np.arange(0.0, 0.6, 0.0037):
        assert PM.lock_for(float(best)) == (None if lad.lock_for(float(best)) is None else pytest.approx(lad.lock_for(float(best))))
    for side in (1, -1):
        assert PM.lock_price(side, 100.0, 30, 0.15, rt) == pytest.approx(LD.roe_price(side, 100.0, 30, 0.15, rt))


def _pine() -> str:
    with open(PINE, encoding="utf-8") as fh:
        return fh.read()


def test_the_scripts_numbers_are_the_bots():
    s = _pine()
    cfg = json.load(open(os.path.join(ROOT, "deploy", "combo.vwap.json"), encoding="utf-8"))
    num = lambda name: float(re.search(rf'{name} = input\.(?:int|float)\(([0-9.]+)', s).group(1))   # noqa: E731
    assert num("lev") == cfg["leverage"]["default"] == cfg["leverage"]["BTCUSDT"]
    assert num("stopAtr") == cfg["stop"]["atr"] and cfg["stop"]["mode"] == "atr"
    assert num("firstLock") / 100 == cfg["ladder"]["first_lock"] and num("trigGap") / 100 == cfg["ladder"]["trigger_gap"]
    assert num("stepPct") / 100 == cfg["ladder"]["step"] and num("holdBars") == cfg["max_hold_bars"]
    assert num("voteMin") == cfg["vote_gate"]["vote_min"] and cfg["vote_gate"]["tf"] == "4h"
    assert num("volDays") == cfg["vol_gate"]["days"] and num("volQ") == cfg["vol_gate"]["q"] and cfg["vol_gate"]["atr"] == 14
    assert cfg["no_weekend"] and cfg["macro_blackout_min"] == 30 and cfg["us_open_pre_min"] == cfg["us_open_pause_min"] == 30
    assert [m["strategy"] for m in cfg["members"]] == ["F6_VWAP_FAIL", "S3_CMO_SANDWICH"]
    assert [m["tf"] for m in cfg["members"]] == ["30m", "1h"] and cfg["rank"] == ["order"]
    st = C.settings_of(C.ComboConfig.from_dict(cfg))                          # the paper's fees (the runner may read Binance's)
    assert num("takerPct") / 100 == st.taker_fee and num("slipPct") / 100 == st.slippage_frac


def test_the_script_carries_the_bots_calendars():
    s = _pine()
    got = {datetime(*map(int, m), tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z")
           for m in re.findall(r'timestamp\("UTC", (\d+), (\d+), (\d+), (\d+), (\d+)\)', s)}
    want = {r[0] for r in csv.reader(open(os.path.join(ROOT, "data", "macro_events.csv"), encoding="utf-8"))
            if r and not r[0].startswith("#") and r[0] != "ts_utc"}
    assert got == want                     # data/macro_events.csv changed: put the same times in the script
    hol = re.search(r"NYSE_HOL = array\.from\(([^)]*)\)", s, re.S).group(1)
    assert set(re.findall(r'"(\d{4}-\d\d-\d\d)"', hol)) == set(NYSE_HOLIDAYS)


def test_the_script_never_reads_a_bar_that_has_not_closed():
    s = _pine()
    assert s.count("request.security(") == 3 and s.count("lookahead=barmerge.lookahead_on") == 3
    # the bar that closes with this 30m bar (end1h / end4h) or the one before it; never the 1h / 4h bar still open
    assert "int s3Sig = end1h ? s3Cur : 0" in s and "int vUp = end4h ? upCur : upPrev" in s and "f_judges(1)" in s
    assert "bool end1h = time_close % MS1H == 0" in s and "bool end4h = time_close % MS4H == 0" in s
    # signals and the simulated position only on closed chart bars
    assert s.count("barstate.isconfirmed") >= 4
    # the 30-day windows live in arrays filled every bar (a function's [i] only counts the bars it was called on)
    assert "src[i]" not in s and s.count("f_push(") == 3
    assert s.splitlines()[0].startswith("// VWAP 개선판 봇 신호") and "//@version=5" in s
