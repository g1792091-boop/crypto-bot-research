"""paperbot/dssig.py: the DeepSeek-200 live wrapper (paper v4 plan, package P2).

Fast tests use synthetic bars. The two real-data tests (start invariance, parity with the research code on anchored
history) need the 5-year Binance bar files: set DS_BARS_DIR to a directory holding <coin>-<tf>.csv.gz (the
research/binance_data build); they are skipped without it.
"""

from __future__ import annotations

import datetime as dt
import json
import multiprocessing
import os
import pickle
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from paperbot import dssig
from paperbot.config import DS200_DEFS, DS_WINDOW_5M

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIVE = 300_000
H = 3_600_000
TF_MS = dssig.TF_MS
BARS = os.environ.get("DS_BARS_DIR", "")
HAVE_BARS = bool(BARS) and all(os.path.exists(os.path.join(BARS, f"{c.lower()}-{tf}.csv.gz"))
                               for c in dssig.COINS for tf in ("5m", "15m", "30m", "1h", "4h"))
NY = ZoneInfo("America/New_York")


def ms(text: str) -> int:
    return int(pd.Timestamp(text, tz="UTC").value // 1_000_000)


def synth(n: int, end_ms: int, seed: int) -> tuple:
    return dssig._synth5m(n, end_ms, seed)


def upto(cols: tuple, boundary: int, n: int) -> tuple:
    """The last n 5m bars of ``cols`` that close at or before ``boundary``."""
    keep = np.asarray(cols[0]) + FIVE <= boundary
    return tuple(np.asarray(a)[keep][-n:] for a in cols)


def job(symbol: str, tf: str, boundary: int, coin: tuple, btc) -> tuple:
    return (symbol, tf, boundary) + tuple(coin) + (btc,)


@pytest.fixture(scope="module")
def C():
    return dssig._load()


@pytest.fixture(scope="module")
def m15():
    """~75 days of synthetic 5m bars for ETH and BTC ending 2026-11-03 00:00 UTC (spans the US DST end)."""
    end = ms("2026-11-03")
    n = DS_WINDOW_5M["15m"] + 4_000
    return {"end": end, "ETH": synth(n, end, 11), "BTC": synth(n, end, 12)}


# ------------------------------------------------------------------ interface and pins
def test_interface_and_defs():
    assert issubclass(dssig.DsUnavailable, dssig.DsError)
    assert [len(dssig.defs_for(tf)) for tf in ("15m", "30m", "1h", "4h")] == [44, 44, 44, 39]
    assert dssig.defs_for("5m") == [] and dssig.defs_for("1d") == []
    assert dssig.coin_key("BTCUSDT") == "BTCUSD" and dssig.coin_key("DOGEUSDT") == "DOGEUSD"
    assert dssig.coin_key("XRPUSDT") is None and dssig.coin_key("BTCUSD") == "BTCUSD"
    assert pickle.loads(pickle.dumps(dssig.ds_job)) is dssig.ds_job          # top-level, picklable for the Pool
    e = pickle.loads(pickle.dumps(dssig.DsUnavailable("x")))
    assert isinstance(e, dssig.DsUnavailable) and str(e) == "x"


def test_verify_returns_the_pinned_hashes(C):
    got = dssig.verify()
    summary = json.load(open(os.path.join(ROOT, "research/deepseek200/out/summary.json")))["code_sha256"]["lib_c.py"]
    pins = json.load(open(os.path.join(ROOT, "paperbot/ds_pins.json")))
    assert got["lib_c.py"] == summary == pins["lib_c.py"] == dssig._sha256(dssig.LIB_C)
    for rel, sha in pins["files"].items():
        assert got[rel] == sha == dssig._sha256(os.path.join(ROOT, rel))
    prereg = open(os.path.join(ROOT, "research/deepseek200/PREREG_DEEPSEEK200.sha256")).read().split()[0]
    assert got["research/deepseek200/PREREG_DEEPSEEK200.md"] == prereg
    assert set(pins["files"]) == {"research/library/lib.py", "research/search/search.py",
                                  "third_party/sweep/harness/vendor/fg_indicators.py",
                                  "third_party/sweep/harness/vendor/pine_indicators.py"}
    assert [(d, f, tuple(t)) for d, f, t in C.DEFS] == [(d, f, tuple(t)) for d, f, t in DS200_DEFS]
    assert C.__name__ == dssig.MODULE_NAME != "lib_c_deepseek200"


def _fresh(monkeypatch):
    """dssig as a process that has not loaded lib_c yet (restored after the test)."""
    monkeypatch.setattr(dssig, "_C", None)
    monkeypatch.setattr(dssig, "_PINS", None)
    monkeypatch.delitem(sys.modules, dssig.MODULE_NAME, raising=False)


def _copy(tmp_path, src: str, name: str, change: bool = False) -> str:
    data = open(src, "rb").read()
    if change:
        data = data.replace(b"MAX_HOLD = 48", b"MAX_HOLD = 49", 1) if b"MAX_HOLD = 48" in data else data + b"\n"
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


@pytest.mark.parametrize("what", ["lib_c", "lib.py", "summary", "pins", "prereg", "missing"])
def test_a_pin_mismatch_refuses_only_deepseek(monkeypatch, tmp_path, what):
    _fresh(monkeypatch)
    pins = json.load(open(dssig.PINS))
    if what == "lib_c":
        monkeypatch.setattr(dssig, "LIB_C", _copy(tmp_path, dssig.LIB_C, "lib_c.py", change=True))
    elif what == "lib.py":
        pins["files"]["research/library/lib.py"] = "0" * 64
    elif what == "summary":
        s = json.load(open(dssig.SUMMARY))
        s["code_sha256"]["lib_c.py"] = "f" * 64
        p = tmp_path / "summary.json"
        p.write_text(json.dumps(s))
        monkeypatch.setattr(dssig, "SUMMARY", str(p))
    elif what == "pins":
        pins["lib_c.py"] = "e" * 64
    elif what == "prereg":
        monkeypatch.setattr(dssig, "PREREG", _copy(tmp_path, dssig.PREREG, "PREREG.md", change=True))
    elif what == "missing":
        pins["files"]["research/library/no_such_file.py"] = "1" * 64
    p = tmp_path / "ds_pins.json"
    p.write_text(json.dumps(pins))
    monkeypatch.setattr(dssig, "PINS", str(p))
    with pytest.raises(dssig.DsUnavailable):
        dssig.verify()
    assert dssig._C is None and dssig.MODULE_NAME not in sys.modules
    end = ms("2026-10-01")
    with pytest.raises(dssig.DsUnavailable):           # the Pool job refuses too, as a DsError
        dssig.ds_job(job("ETHUSDT", "4h", end, synth(DS_WINDOW_5M["4h"], end, 1), None))
    from paperbot import sweepsig
    sweepsig.verify()                                  # the core group's locked code is untouched


def test_unreadable_pins_are_unavailable(monkeypatch, tmp_path):
    _fresh(monkeypatch)
    p = tmp_path / "ds_pins.json"
    p.write_text("{not json")
    monkeypatch.setattr(dssig, "PINS", str(p))
    with pytest.raises(dssig.DsUnavailable, match="unreadable"):
        dssig.verify()


def test_load_leaves_sys_path_and_warnings_filters_unchanged():
    code = r"""
import sys, warnings
from paperbot import sweepsig
sweepsig.lib()                     # the core group loads the locked library first, as live3 does
p0, f0, fid = list(sys.path), list(warnings.filters), id(warnings.filters)
from paperbot import dssig
pins = dssig.verify()
end = 1790006400000 - 1790006400000 % 14400000
r = dssig.ds_job(("ETHUSDT", "4h", end) + dssig._synth5m(115200, end, 3) + (dssig._synth5m(115200, end, 4),))
assert r["ready"], r
assert sys.path == p0, (set(sys.path) ^ set(p0))
assert list(warnings.filters) == f0 and id(warnings.filters) == fid
assert "lib_c_deepseek200" not in sys.modules and dssig.MODULE_NAME in sys.modules
print("OK", len(pins))
"""
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-3000:]
    assert out.stdout.strip() == "OK 6"


# ------------------------------------------------------------------ the job
def test_not_ready_cases(C, m15):
    end = m15["end"]
    eth = upto(m15["ETH"], end, DS_WINDOW_5M["15m"])
    r = dssig.ds_job(job("XRPUSDT", "15m", end, eth, m15["BTC"]))
    assert not r["ready"] and "not a DeepSeek coin" in r["why"] and "sides" not in r
    r = dssig.ds_job(job("ETHUSDT", "5m", end, eth, None))
    assert not r["ready"] and "no DeepSeek definitions" in r["why"]
    r = dssig.ds_job(job("ETHUSDT", "15m", end - FIVE, eth, None))
    assert not r["ready"] and "not a 15m boundary" in r["why"]
    short = tuple(a[1:] for a in eth)
    r = dssig.ds_job(job("ETHUSDT", "15m", end, short, None))
    assert not r["ready"] and r["why"].startswith("warm-up")
    gap = tuple(a[:-1] for a in upto(m15["ETH"], end, DS_WINDOW_5M["15m"] + 1))   # last 5m bar missing
    r = dssig.ds_job(job("ETHUSDT", "15m", end, gap, None))
    assert not r["ready"] and "expected" in r["why"]


def test_sides_shape_and_btc_never_gets_f14(C, m15):
    end = m15["end"]
    n = DS_WINDOW_5M["15m"]
    eth_full = dssig.frame(*m15["ETH"], tf="15m")
    btc_full = dssig.frame(*m15["BTC"], tf="15m")
    R, notes = dssig.entries_frame(eth_full, "15m", "ETHUSD", btc_full)
    assert list(R) == dssig.defs_for("15m") and notes == []
    lg, sh = R["F14_SMT"]
    t = (eth_full["ts"].astype("int64") // 1_000_000).to_numpy() + TF_MS["15m"]
    first_full = int(m15["ETH"][0][0]) + n * FIVE                     # the first boundary with a full live window
    fire = [int(b) for b, x in zip(t, lg | sh) if x and first_full <= b <= end]
    assert len(fire) >= 3
    for b in fire[-3:]:
        eth, btc = upto(m15["ETH"], b, n), upto(m15["BTC"], b, n)
        r = dssig.ds_job(job("ETHUSDT", "15m", b, eth, btc))
        assert r["ready"] and r["errors"] == [] and r["bar_open"] == b - TF_MS["15m"]
        assert list(r["sides"]) == [d for d in dssig.defs_for("15m") if d in r["sides"]]
        assert set(r["sides"].values()) <= {1, -1} and r["atr"] > 0 and r["close"] == eth[4][-1]
        i = int(np.flatnonzero(t == b)[0])
        assert r["sides"]["F14_SMT"] == (1 if lg[i] else -1)
        # the BTC frame trimmed to its last BTC_TF_BARS bars gives the same last-bar sides as the full window
        dssig.BTC_TF_BARS, keep = 10 ** 9, dssig.BTC_TF_BARS
        try:
            assert dssig.ds_job(job("ETHUSDT", "15m", b, eth, btc)) == r
        finally:
            dssig.BTC_TF_BARS = keep
        # the same bars under the BTC symbol: no F14, even with a BTC context passed
        rb = dssig.ds_job(job("BTCUSDT", "15m", b, eth, btc))
        assert "F14_SMT" not in rb["sides"] and rb["errors"] == []
        assert {k: v for k, v in r["sides"].items() if k != "F14_SMT"} == rb["sides"]
    Rb, _ = dssig.entries_frame(eth_full, "15m", "BTCUSD", btc_full)
    assert not (Rb["F14_SMT"][0] | Rb["F14_SMT"][1]).any()
    r = dssig.ds_job(job("ETHUSDT", "15m", end, upto(m15["ETH"], end, n), None))
    assert r["ready"] and "F14_SMT" not in r["sides"] and r["errors"] == ["F14_SMT: no BTC bars"]


def test_no_look_ahead_in_the_job(C, m15):
    """Junk bars after the boundary (coin or BTC), or more history than the window, never change the job."""
    n = DS_WINDOW_5M["15m"]
    rng = np.random.default_rng(7)
    checked = 0
    for b in (m15["end"] - k * TF_MS["15m"] for k in range(0, 40, 8)):
        eth, btc = upto(m15["ETH"], b, n), upto(m15["BTC"], b, n)
        base = dssig.ds_job(job("ETHUSDT", "15m", b, eth, btc))
        assert base["ready"]
        k = 30
        jt = b + FIVE * np.arange(k, dtype=np.int64)
        junk = (jt,) + tuple(rng.uniform(1, 1e4, k) for _ in range(4)) + (rng.uniform(0, 1e6, k),)
        cat = lambda x, y: tuple(np.r_[p, q] for p, q in zip(x, y))   # noqa: E731
        assert dssig.ds_job(job("ETHUSDT", "15m", b, cat(eth, junk), btc)) == base
        assert dssig.ds_job(job("ETHUSDT", "15m", b, eth, cat(btc, junk))) == base
        longer = upto(m15["ETH"], b, n + 500)
        assert dssig.ds_job(job("ETHUSDT", "15m", b, longer, upto(m15["BTC"], b, n + 500))) == base
        checked += len(base["sides"])
    assert checked >= 5                     # not vacuous: the compared bars had signals


@pytest.mark.parametrize("tf", ["15m", "1h", "4h"])
def test_no_look_ahead_on_the_frame(C, tf):
    """Every definition's whole series up to a cut equals the series computed with junk bars after the cut."""
    span = TF_MS[tf]
    nbars = {"15m": 3000, "1h": 2000, "4h": 1300}[tf]
    end = ms("2026-09-01")
    eth, btc = synth(nbars * span // FIVE, end, 21), synth(nbars * span // FIVE, end, 22)
    rng = np.random.default_rng(5)
    for frac in (0.5, 0.8):
        cut = int(eth[0][int(len(eth[0]) * frac)]) // span * span
        ce, cb = upto(eth, cut, 10 ** 9), upto(btc, cut, 10 ** 9)
        k = 60 * span // FIVE
        jt = cut + FIVE * np.arange(k, dtype=np.int64)
        junk = lambda: (jt,) + tuple(rng.uniform(1, 1e3, k) for _ in range(4)) + (rng.uniform(0, 1e6, k),)  # noqa: E731
        a, _ = dssig.entries_frame(dssig.frame(*ce, tf=tf), tf, "ETHUSD", dssig.frame(*cb, tf=tf))
        je = tuple(np.r_[p, q] for p, q in zip(ce, junk()))
        jb = tuple(np.r_[p, q] for p, q in zip(cb, junk()))
        b, _ = dssig.entries_frame(dssig.frame(*je, tf=tf), tf, "ETHUSD", dssig.frame(*jb, tf=tf))
        m = len(a[next(iter(a))][0])
        assert len(b[next(iter(b))][0]) > m
        for d in a:
            assert np.array_equal(a[d][0], b[d][0][:m]) and np.array_equal(a[d][1], b[d][1][:m]), d


def test_f14_aligns_btc_by_timestamp_and_survives_a_missing_btc_bar(C):
    tf, span = "1h", H
    end = ms("2026-09-01")
    eth, btc = synth(1500 * 12, end, 31), synth(1600 * 12, end, 32)        # BTC starts 100 bars earlier
    fe = dssig.frame(*eth, tf=tf)
    fb_long = dssig.frame(*btc, tf=tf)
    fb_same = fb_long[fb_long["ts"] >= fe["ts"].iloc[0]].reset_index(drop=True)
    ref, _ = dssig.entries_frame(fe, tf, "ETHUSD", fb_same)
    lg, sh = ref["F14_SMT"]
    assert (lg | sh).sum() >= 20
    # a BTC frame with more history lines up by timestamp, not by position (identical once BTC's 21 bars exist)
    alt, _ = dssig.entries_frame(fe, tf, "ETHUSD", fb_long)
    assert np.array_equal(alt["F14_SMT"][0][25:], lg[25:]) and np.array_equal(alt["F14_SMT"][1][25:], sh[25:])
    # BTC moved one bar later in time: F14 changes (the timestamps are used)
    shifted = fb_same.copy()
    shifted["ts"] = shifted["ts"] + pd.Timedelta(hours=1)
    sft, _ = dssig.entries_frame(fe, tf, "ETHUSD", shifted)
    assert not (np.array_equal(sft["F14_SMT"][0], lg) and np.array_equal(sft["F14_SMT"][1], sh))
    # the other definitions never read BTC
    for d in ref:
        if d != "F14_SMT":
            assert np.array_equal(sft[d][0], ref[d][0]) and np.array_equal(sft[d][1], ref[d][1]), d
    # one BTC hour missing: no error, F14 off on that bar, unchanged from 21 bars after it
    gap_i = 900
    gap_t = int(fb_same["ts"].iloc[gap_i].value // 1_000_000)
    keep = (btc[0] < gap_t) | (btc[0] >= gap_t + span)
    fb_gap = dssig.frame(*(a[keep] for a in btc), tf=tf)
    fb_gap = fb_gap[fb_gap["ts"] >= fe["ts"].iloc[0]].reset_index(drop=True)
    assert len(fb_gap) == len(fb_same) - 1
    gp, notes = dssig.entries_frame(fe, tf, "ETHUSD", fb_gap)
    assert notes == [] and not gp["F14_SMT"][0][gap_i] and not gp["F14_SMT"][1][gap_i]
    j = gap_i + 22
    assert np.array_equal(gp["F14_SMT"][0][j:], lg[j:]) and np.array_equal(gp["F14_SMT"][1][:gap_i], sh[:gap_i])
    # the job with BTC's last hour missing: ready, F14 absent, nothing raised
    b = int(eth[0][-1]) + FIVE
    n = DS_WINDOW_5M["1h"]
    big_e, big_b = synth(n, b, 33), synth(n, b, 34)
    r = dssig.ds_job(job("ETHUSDT", tf, b, big_e, tuple(a[:-12] for a in big_b)))
    assert r["ready"] and "F14_SMT" not in r["sides"] and r["errors"] == []


def test_f14_context_failure_loses_only_f14(C, m15, monkeypatch):
    real = C.entries

    def flaky(df, tf, ctx=None, coin=""):
        if ctx is not None:
            raise ValueError("bad BTC frame")
        return real(df, tf, ctx, coin)
    monkeypatch.setattr(C, "entries", flaky)
    end, n = m15["end"], DS_WINDOW_5M["15m"]
    r = dssig.ds_job(job("ETHUSDT", "15m", end, upto(m15["ETH"], end, n), upto(m15["BTC"], end, n)))
    assert r["ready"] and "F14_SMT" not in r["sides"]
    assert r["errors"] and r["errors"][0].startswith("F14_SMT context failed (ValueError: bad BTC frame)")


def test_every_failure_becomes_ds_error(C, m15, monkeypatch):
    def boom(*a, **k):
        raise ZeroDivisionError("inside lib_c")
    monkeypatch.setattr(C, "entries", boom)
    end, n = m15["end"], DS_WINDOW_5M["15m"]
    with pytest.raises(dssig.DsError, match="ETHUSDT 15m ZeroDivisionError: inside lib_c") as ei:
        dssig.ds_job(job("ETHUSDT", "15m", end, upto(m15["ETH"], end, n), None))
    assert type(ei.value) is dssig.DsError
    with pytest.raises(dssig.DsError):
        dssig.ds_job(("ETHUSDT", "15m"))                   # malformed args
    with pytest.raises(dssig.DsError):
        eth = upto(m15["ETH"], end, n)
        dssig.ds_job(job("ETHUSDT", "15m", end, (eth[0],) + tuple(a[:-1] for a in eth[1:]), None))   # ragged


def test_through_a_real_pool(C, m15):
    """The job and its errors cross a fork Pool unchanged (what sigservice does)."""
    end, n = m15["end"], DS_WINDOW_5M["15m"]
    j = job("SOLUSDT", "15m", end, upto(m15["ETH"], end, n), upto(m15["BTC"], end, n))
    direct = dssig.ds_job(j)
    with multiprocessing.get_context("fork").Pool(1) as pool:
        assert pool.map(dssig.ds_job, [j]) == [direct]
        with pytest.raises(dssig.DsError):
            pool.map(dssig.ds_job, [("ETHUSDT", "15m")])


def test_zero_volume_5m_bars_are_left_out():
    span = TF_MS["15m"]
    t0 = ms("2026-09-01")
    ts = t0 + FIVE * np.arange(12, dtype=np.int64)
    o = np.array([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21], float)
    h, lo, c = o + 0.5, o - 0.5, o + 0.2
    v = np.array([0, 5, 5, 1, 1, 1, 0, 0, 0, 2, np.nan, 2], float)
    f = dssig.frame(ts, o, h, lo, c, v, tf="15m")
    got = (f["ts"].astype("int64") // 1_000_000).tolist()
    assert got == [t0, t0 + span, t0 + 3 * span]           # the third bin had no trade: no bar, as in the files
    assert f["open"].tolist() == [11, 13, 19] and f["high"].tolist() == [12.5, 15.5, 21.5]
    assert f["volume"].iloc[0] == 10 and f["volume"].iloc[2] == 4      # NaN volume is unknown, the bar is kept
    # the same bars with the last 5m bar missing: the last bin is partial and dropped (recorder.build_frames)
    f2 = dssig.frame(ts[:-1], o[:-1], h[:-1], lo[:-1], c[:-1], v[:-1], tf="15m")
    assert len(f2) == 2


def test_frame_matches_the_core_build_frames_on_traded_bars():
    from paperbot import sweepsig
    from paperbot.recorder import build_frames
    lib = sweepsig.lib()
    end = ms("2026-09-01")
    cols = synth(30_000, end, 41)
    df5 = pd.DataFrame({"ts": pd.to_datetime(cols[0], unit="ms", utc=True), "open": cols[1], "high": cols[2],
                        "low": cols[3], "close": cols[4], "volume": cols[5]}).iloc[7:].reset_index(drop=True)
    for tf in ("15m", "30m", "1h", "4h"):
        a = build_frames(lib, df5, [tf])[tf]
        b = dssig.frame(*(x[7:] for x in cols), tf=tf, lib=lib)
        pd.testing.assert_frame_equal(a, b)


# ------------------------------------------------------------------ ET sessions across the DST switches
def test_session_clock_matches_zoneinfo_across_dst(C):
    for a, b in (("2026-10-25", "2026-11-08"), ("2027-03-07", "2027-03-21")):
        ts = pd.date_range(a, b, freq="15min", tz="UTC")
        day, mins = C.et_wall(ts.tz_localize(None).to_numpy().astype("datetime64[ns]"))
        wall = ts.tz_convert(NY)
        want_day = np.array([(d.date() - dt.date(1970, 1, 1)).days for d in wall])
        want_min = np.array([d.hour * 60 + d.minute for d in wall])
        assert np.array_equal(day, want_day) and np.array_equal(mins, want_min)


def test_session_signals_follow_new_york_time_across_the_dst_end(C, m15):
    tf = "1h"
    fe = dssig.frame(*m15["ETH"], tf=tf)
    R, _ = dssig.entries_frame(fe, tf, "ETHUSD", dssig.frame(*m15["BTC"], tf=tf))
    opens = pd.DatetimeIndex(fe["ts"])
    wall = opens.tz_convert(NY)
    wm = np.array([w.hour * 60 + w.minute for w in wall])

    def bars(d):
        return np.flatnonzero(R[d][0] | R[d][1])
    o930 = bars("F15_OPEN0930")
    assert len(o930) >= 40 and set(wm[o930]) == {600}                    # judged on the 10:00 ET bar
    before = {opens[i].hour for i in o930 if opens[i] < pd.Timestamp("2026-11-01 06:00", tz="UTC")}
    after = {opens[i].hour for i in o930 if opens[i] >= pd.Timestamp("2026-11-01 06:00", tz="UTC")}
    assert before == {14} and after == {15}                             # EDT then EST
    assert set(wm[bars("F15_OPEN0000")]) == {0}
    assert set(wm[bars("F15_LON_BRK")]) <= set(range(300, 720, 60))
    asia = set(wm[bars("F15_ASIA_BRK")]) | set(wm[bars("F15_ASIA_SWEEP")])
    assert asia and asia <= set(range(0, 480, 60))
    # the live job at 15m: OPEN0930 is judged on the bar closing 10:30 New York time on both sides of the switch
    n = DS_WINDOW_5M["15m"]
    hit = []
    for text in ("2026-10-30 14:30", "2026-11-02 15:30", "2026-11-02 14:30"):
        b = ms(text)
        r = dssig.ds_job(job("ETHUSDT", "15m", b, upto(m15["ETH"], b, n), upto(m15["BTC"], b, n)))
        assert r["ready"]
        hit.append("F15_OPEN0930" in r["sides"])
    assert hit == [True, True, False]


# ------------------------------------------------------------------ speed
def test_a_4h_job_takes_at_most_300_ms(C):
    """Plan P2 test 7. The fastest of five runs, so other processes on the box do not decide the result."""
    b = ms("2026-09-01")
    n = DS_WINDOW_5M["4h"]
    j = job("ETHUSDT", "4h", b, synth(n, b, 51), synth(n, b, 52))
    assert dssig.ds_job(j)["ready"]
    t = []
    for _ in range(5):
        t0 = time.perf_counter()
        dssig.ds_job(j)
        t.append(time.perf_counter() - t0)
    assert min(t) <= 0.300, [round(x * 1000) for x in t]


def test_cli_verify_and_bench(capsys):
    assert dssig.main(["verify"]) == 0
    assert json.loads(capsys.readouterr().out)["lib_c.py"] == dssig._sha256(dssig.LIB_C)
    res = dssig.bench(rep=1, tfs=("30m",))
    assert res["source"] == "synthetic" and res["tfs"]["30m"]["jobs"] == 6 and res["tfs"]["30m"]["not_ready"] == 0


# ------------------------------------------------------------------ real bars (DS_BARS_DIR)
def _read5(coin: str) -> tuple:
    d = pd.read_csv(os.path.join(BARS, f"{coin.lower()}-5m.csv.gz"))
    t = (pd.to_datetime(d["ts"], utc=True).astype("int64") // 1_000_000).to_numpy(np.int64)
    return (t,) + tuple(d[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))


def _w_chart(tf: str) -> int:
    per = TF_MS[tf] // FIVE
    return (DS_WINDOW_5M[tf] - (per - 1)) // per     # chart bars of the live window when it starts mid-bin


def _invariance_task(a) -> dict:
    tf, coin, nstart = a
    W = _w_chart(tf)
    per = TF_MS[tf] // FIVE
    e5, b5 = _read5(coin), _read5("BTCUSD")
    fe = dssig.frame(*(x[-3 * W * per:] for x in e5), tf=tf)
    fb = dssig.frame(*(x[-3 * W * per - per:] for x in b5), tf=tf)
    ref, _ = dssig.entries_frame(fe, tf, coin, fb)
    starts = [int(W + k * (len(fe) - 2 * W) / max(1, nstart - 1)) for k in range(nstart)]
    bad, sig = {}, 0
    for s in starts:
        sub = fe.iloc[s:].reset_index(drop=True)
        sub.attrs["tf"] = tf
        bsub = fb[fb["ts"] >= sub["ts"].iloc[0]].reset_index(drop=True)
        got, _ = dssig.entries_frame(sub, tf, coin, bsub)
        for d in ref:
            sig += int((ref[d][0][s + W - 1:] | ref[d][1][s + W - 1:]).sum())
            mm = np.flatnonzero((got[d][0][W - 1:] != ref[d][0][s + W - 1:]) | (got[d][1][W - 1:] != ref[d][1][s + W - 1:]))
            if len(mm):
                bad[d] = bad.get(d, 0) + len(mm)
    return {"tf": tf, "coin": coin, "starts": len(starts), "bars": len(fe), "W": W, "bad": bad, "signals": sig}


@pytest.mark.skipif(not HAVE_BARS, reason="set DS_BARS_DIR to the 5-year Binance bar files")
def test_real_bars_start_invariance_at_the_live_windows():
    """Plan P2 test 3: 44 definitions x 6 coins x 24 starts: the signals of every bar that has a full live window of
    history in a later-starting frame equal the anchored ones."""
    tasks = [(tf, c, 24) for tf in ("15m", "30m", "1h", "4h") for c in dssig.COINS]
    with multiprocessing.get_context("fork").Pool(min(4, os.cpu_count() or 1)) as pool:
        res = pool.map(_invariance_task, tasks)
    assert [r for r in res if r["bad"]] == []
    assert all(r["starts"] == 24 and r["signals"] > 1000 for r in res)
    print(json.dumps({f"{r['tf']}|{r['coin']}": [r["W"], r["bars"], r["signals"]] for r in res}))


def _parity_task(a) -> dict:
    tf, coin, k_sig, k_rand = a
    from paperbot import sweepsig
    L = sweepsig.lib()
    span = TF_MS[tf]
    cut = pd.Timestamp("2026-09-30", tz="UTC")
    nat = {}
    for c in {coin, "BTCUSD"}:
        d = L.read_ohlcv(os.path.join(BARS, f"{c.lower()}-{tf}.csv.gz"))
        d = d[d["ts"] < cut].reset_index(drop=True)
        d.attrs["tf"] = tf
        nat[c] = d
    t = (nat[coin]["ts"].astype("int64") // 1_000_000).to_numpy(np.int64)
    end = int(t[-1]) + span
    first = end - 90 * 86_400_000
    lo = max(0, int(np.searchsorted(t, first)) - 2 * _w_chart(tf))       # anchored: two live windows before
    df = nat[coin].iloc[lo:].reset_index(drop=True)
    df.attrs["tf"] = tf
    bt = nat["BTCUSD"]
    bt = bt[bt["ts"] >= df["ts"].iloc[0]].reset_index(drop=True)
    bt.attrs["tf"] = tf
    C = dssig._load()
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ref = C.entries(df, tf, None if coin == "BTCUSD" else {"BTCUSD": bt}, coin)    # the research call
    defs = dssig.defs_for(tf)
    tt = t[lo:] + span
    idx = np.flatnonzero(tt > first)
    cnt = np.array([sum(bool(ref[d][0][i] or ref[d][1][i]) for d in defs) for i in idx])
    rng = np.random.default_rng(abs(hash((tf, coin))) % 2 ** 32)
    pick = set(idx[np.argsort(-cnt, kind="stable")[:k_sig]].tolist()) | set(rng.choice(idx, k_rand, replace=False).tolist())
    e5, b5 = _read5(coin), _read5("BTCUSD")
    n = DS_WINDOW_5M[tf]
    bad, sig = [], 0
    for i in sorted(pick):
        b = int(tt[i])
        r = dssig.ds_job((coin + "T", tf, b) + upto(e5, b, n) + (None if coin == "BTCUSD" else upto(b5, b, n),))
        want = {d: (1 if ref[d][0][i] else -1) for d in defs if ref[d][0][i] or ref[d][1][i]}
        sig += len(want)
        if not r["ready"] or r["sides"] != want:
            bad.append((b, r.get("why"), r.get("sides"), want))
    return {"tf": tf, "coin": coin, "bars": len(pick), "signals": sig, "bad": bad}


@pytest.mark.skipif(not HAVE_BARS, reason="set DS_BARS_DIR to the 5-year Binance bar files")
def test_real_bars_parity_with_the_research_entries_last_90_days():
    """Plan P2 test 4: the live job (5m window -> resample -> lib_c, last bar) against research lib_c.entries on the
    native timeframe files (anchored history), on the 12 most signal-rich and 12 random bars of the last 90 days per
    coin and timeframe."""
    tasks = [(tf, c, 12, 12) for tf in ("15m", "30m", "1h", "4h") for c in dssig.COINS]
    with multiprocessing.get_context("fork").Pool(min(4, os.cpu_count() or 1)) as pool:
        res = pool.map(_parity_task, tasks)
    assert [(r["tf"], r["coin"], r["bad"][:2]) for r in res if r["bad"]] == []
    assert sum(r["signals"] for r in res) > 1000 and all(r["bars"] >= 20 for r in res)
    print(json.dumps({f"{r['tf']}|{r['coin']}": [r["bars"], r["signals"]] for r in res}))
