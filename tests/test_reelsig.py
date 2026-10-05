"""The reel's live signal wrapper (paperbot/reelsig.py, plan P3): pins and the contained load of lib_reel5m, parity
with lib_reel5m's position-independent machine (simulate(trade=False), H1 = SMA200 / CLOSE / LONG) on the last
config.REEL_WINDOW_5M closed 5m bars, no look-ahead, start invariance, the H1 rules as the wrapper reports them
(never short, a filter turning off cancels the arming, the setup expires 12 bars after its last breach, the breach
bar is never the signal, short / NaN windows give None), the 5m coin flips' entry levels (owners' D4) and the
Signal contract of paperbot/reel_engine.py.

The reference is lib_reel5m itself, loaded by the wrapper from the pinned bytes, run on the WHOLE frame (anchored:
started flat on the frame's first bar) with one placeholder bar appended (a copy of the last bar 5 minutes later;
the wrapper appends a NaN entry to the indicator arrays instead, so the two are independent formulations), with the
real cost object of the 5-year run.

Real-data tests read <coin>-5m.csv.gz from DS_BARS_DIR (the Binance USDT-M 5m bar files of the 5-year run,
2021-01..2026-09, 604,177 bars per coin) and are skipped without it (about 3 minutes with it). Recorded once with
those files (scratch scripts, 2026-10-05; the tests repeat a sample): EXHAUSTIVE_2026Q3 = every 5m bar of
2026-07-01..2026-09-29 of the six coins at the live window equals the anchored 5-year machine; the longest setup in 5
years (first breach bar to signal) is 14 bars, so the machine of any window over 214 bars is the anchored one; the
indicators differ only by rounding at float ties, all of which are listed in TIE_MISMATCHES below.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import textwrap

import numpy as np
import pandas as pd
import pytest

from paperbot import reelsig as RS
from paperbot.config import REEL_TF, REEL_WINDOW_5M

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BARS = os.environ.get("DS_BARS_DIR", "")
FIVE = 300_000
T0 = 1_767_225_600_000                      # 2026-01-01 00:00 UTC, on the 5m grid
KEYS = {"side", "bar_open", "atr14", "swing_low", "stop", "up_band", "closes"}
# the exhaustive offline run (2026-10-05) the docstring cites: reelsig.signal on the window ending at every bar
# (157,248 coin-bars, 2,091 signals in both, 0 differing; levels within 2.3e-9 relative, the upper band's anchored
# rounding; flip_levels on every 7th bar, 22,464: within 3.3e-9 relative)
EXHAUSTIVE_2026Q3 = {"window": 5_000, "period": "2026-07-01..2026-09-29", "coins": 6, "bars": 157_248,
                     "signals": 2_091, "mismatches": 0, "max_rel_level_diff": 2.3e-9, "flip_bars": 22_464}


# ------------------------------------------------------------------ helpers
@pytest.fixture(scope="module")
def R():
    return RS._load()


@pytest.fixture(scope="module")
def cost(R):
    return R.env()["L"]._cost("5m", R.MAX_HOLD)


def synth(n: int, seed: int = 7, red: float = 0.002, up_only: bool = False) -> pd.DataFrame:
    """5m bars: a random walk whose drift switches sign every 200-700 bars (the middle band crosses SMA200 both
    ways; ``up_only``: the drift stays positive, the filter is mostly on) with fat-tailed moves (closes fall below
    the lower band); opens sit about ``red`` above the last close, so red candles are common and some setups wait
    out their 12 bars."""
    rng = np.random.default_rng(seed)
    drift = np.empty(n)
    i, sign = 0, 1.0
    while i < n:
        k = int(rng.integers(200, 700))
        drift[i:i + k] = sign * rng.uniform(0.0001, 0.0006)
        sign, i = (sign if up_only else -sign), i + k
    c = 100 * np.exp(np.cumsum(drift + rng.standard_t(3, n) * 0.0015))
    o = np.r_[100.0, c[:-1]] * (1 + rng.normal(red, 0.0003, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.001, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.001, n)))
    return pd.DataFrame({"ts": pd.to_datetime(T0 + FIVE * np.arange(n, dtype=np.int64), unit="ms", utc=True),
                         "open": o, "high": h, "low": lo, "close": c, "volume": rng.uniform(1, 10, n)})


def ref(R, cost, df: pd.DataFrame):
    """({signal_idx: lib signal dict}, indicators) of H1's anchored position-independent machine on the whole frame
    (one placeholder bar appended so that simulate also reads the frame's last bar)."""
    df = df.reset_index(drop=True)
    pad = df.iloc[[-1]].copy()
    pad["ts"] = pad["ts"] + pd.Timedelta(minutes=5)
    d2 = pd.concat([df, pad], ignore_index=True)
    ind = R.indicators(d2)
    P = R.Prep(ind, "SMA200", "CLOSE", "LONG")
    _t, sg, _s = R.simulate(P, cost, 0, len(d2), "open", False)
    out = {}
    for s in sg:
        assert s["side"] == 1 and s["signal_idx"] < len(df)
        out[int(s["signal_idx"])] = s
    return out, ind


def rel(a: float, b: float) -> float:
    return abs(float(a) - float(b)) / max(abs(float(b)), 1e-300)


def same_as_ref(r: dict, a: dict, ind: dict, t: int, df: pd.DataFrame, tol: float = 1e-9,
                band_tol: float = 1e-7) -> None:
    """The wrapper's dict for bar t equals the anchored lib signal a. The swing low is exact; ATR14 (Wilder, forgets
    its start) within ``tol``; the upper band within ``band_tol``: pandas' rolling variance accumulates rounding over
    the bars it has updated, up to 2e-8 relative after the 5-year series (measured against exact sums), while a
    5,000-bar window is fresh."""
    assert set(r) == KEYS and r["side"] == 1
    assert r["bar_open"] == int(pd.Timestamp(df["ts"].iloc[t]).value // 1_000_000)
    assert r["swing_low"] == float(a["extreme"])
    assert rel(r["atr14"], ind["atr"][t]) <= tol
    assert rel(r["stop"], a["stop_px"]) <= tol
    assert rel(r["up_band"], a["target0"]) <= band_tol
    assert r["closes"] == [float(x) for x in df["close"].to_numpy(float)[t - 18:t + 1]]


def window_end(df: pd.DataFrame, t: int, w: int = None) -> pd.DataFrame:
    w = RS.WINDOW if w is None else w
    return df.iloc[t - w + 1:t + 1]


_VIEW = []


def _reel_view():
    """The dashboard's REEL_H1 view function (paperbot/strategy_view_defs/REEL_H1.py; the vendor indicators it imports
    come with the locked library)."""
    if not _VIEW:
        import importlib
        from paperbot import sweepsig
        sweepsig.lib()
        _VIEW.append(importlib.import_module("paperbot.strategy_view_defs.REEL_H1").view_REEL_H1)
    return _VIEW[0]


def check_view(view, w: pd.DataFrame) -> bool:
    """On the frame ``w`` (a live window): every long condition of the view is on at the last bar exactly when
    ``reelsig.signal(w)`` fires, and then the view draws that signal's swing low, stop and first target (the upper band
    of bar s) at the last bar. Returns whether it fired."""
    v = view(w.reset_index(drop=True).copy(), REEL_TF)
    assert v["short"] == []
    on = np.ones(len(w), bool)
    for _label, arr in v["long"]:
        on &= np.asarray(arr, bool)
    r = RS.signal(w)
    assert bool(on[-1]) == (r is not None), str(w["ts"].iloc[-1])
    if r is not None:
        lines = {o["name"]: np.asarray(o["values"], float) for o in v["overlays"]}
        assert lines["볼린저 상단(20, 2)"][-1] == r["up_band"]
        assert lines["눌림 최저점(하단 이탈 뒤)"][-1] == r["swing_low"]
        assert lines["손절선(최저점 − ATR 0.05배)"][-1] == r["stop"]
    return r is not None


# ------------------------------------------------------------------ pins and the contained load
def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def test_pins_equal_the_research_records():
    got = RS.verify()
    assert list(got)[:2] == ["PREREG_REEL5M.md", "lib_reel5m.py"]
    assert got == {"PREREG_REEL5M.md": RS.PIN_PREREG, "lib_reel5m.py": RS.PIN_LIB_REEL5M, **RS.PIN_FILES}
    with open(RS.PREREG_SHA) as fh:
        assert fh.read().split() == [RS.PIN_PREREG, "PREREG_REEL5M.md"]
    with open(RS.SUMMARY) as fh:
        summary = json.load(fh)
    assert summary["prereg_sha256"] == RS.PIN_PREREG == _sha(RS.PREREG)
    assert summary["code_sha256"]["lib_reel5m.py"] == RS.PIN_LIB_REEL5M == _sha(RS.LIB_REEL5M)
    with open(os.path.join(ROOT, "paperbot", "ds_pins.json")) as fh:
        ds = json.load(fh)["files"]
    assert all(ds[k] == v for k, v in RS.PIN_FILES.items())        # the same library files as the DeepSeek group
    for rel_path, sha in RS.PIN_FILES.items():
        assert _sha(os.path.join(ROOT, rel_path)) == sha


def _copy(src: str, dst, extra: bytes = b"") -> str:
    with open(src, "rb") as fh:
        data = fh.read()
    with open(dst, "wb") as fh:
        fh.write(data + extra)
    return str(dst)


@pytest.mark.parametrize("case", ["lib_changed", "lib_missing", "prereg_changed", "sha_file_other", "sha_file_bad",
                                  "summary_lib_other", "summary_prereg_other", "summary_missing", "pin_lib_other",
                                  "pin_prereg_other", "library_changed"])
def test_a_pin_mismatch_refuses_the_reel_only(R, monkeypatch, tmp_path, case):
    monkeypatch.setattr(RS, "_R", None)
    monkeypatch.setattr(RS, "_PINS", None)
    if case == "lib_changed":
        monkeypatch.setattr(RS, "LIB_REEL5M", _copy(RS.LIB_REEL5M, tmp_path / "lib_reel5m.py", b"\n# edited\n"))
    elif case == "lib_missing":
        monkeypatch.setattr(RS, "LIB_REEL5M", str(tmp_path / "lib_reel5m.py"))
    elif case == "prereg_changed":
        monkeypatch.setattr(RS, "PREREG", _copy(RS.PREREG, tmp_path / "PREREG_REEL5M.md", b" "))
    elif case in ("sha_file_other", "sha_file_bad"):
        p = tmp_path / "PREREG_REEL5M.sha256"
        p.write_text(("0" * 64 + "  PREREG_REEL5M.md\n") if case == "sha_file_other" else RS.PIN_PREREG + "\n")
        monkeypatch.setattr(RS, "PREREG_SHA", str(p))
    elif case.startswith("summary"):
        p = tmp_path / "summary.json"
        if case != "summary_missing":
            with open(RS.SUMMARY) as fh:
                s = json.load(fh)
            if case == "summary_lib_other":
                s["code_sha256"]["lib_reel5m.py"] = "1" * 64
            else:
                s["prereg_sha256"] = "2" * 64
            p.write_text(json.dumps(s))
        monkeypatch.setattr(RS, "SUMMARY", str(p))
    elif case == "pin_lib_other":
        monkeypatch.setattr(RS, "PIN_LIB_REEL5M", "3" * 64)
    elif case == "pin_prereg_other":
        monkeypatch.setattr(RS, "PIN_PREREG", "4" * 64)
    elif case == "library_changed":
        monkeypatch.setattr(RS, "PIN_FILES", {**RS.PIN_FILES, "research/search/search.py": "5" * 64})
    with pytest.raises(RS.ReelUnavailable):
        RS.verify()
    df = synth(RS.WINDOW + 5, 3)
    for fn in (RS.signal, RS.flip_levels):
        with pytest.raises(RS.ReelUnavailable):
            fn(df)
    assert issubclass(RS.ReelUnavailable, RS.ReelError)


def test_verify_rehashes_after_the_load(R, monkeypatch, tmp_path):
    assert RS._R is R
    monkeypatch.setattr(RS, "PREREG", _copy(RS.PREREG, tmp_path / "PREREG_REEL5M.md", b"x"))
    with pytest.raises(RS.ReelUnavailable, match="PREREG_REEL5M.md"):
        RS.verify()


def test_a_changed_lib_constant_refuses(R, monkeypatch):
    monkeypatch.setattr(R, "WAIT", 13)
    with pytest.raises(RS.ReelUnavailable, match="WAIT"):
        RS._check_module(R)
    monkeypatch.setattr(R, "WAIT", 12)
    monkeypatch.setattr(R, "H1", ("5m", "BB_EMA200_CLOSE_LONG", "SWING_BAND"))
    with pytest.raises(RS.ReelUnavailable, match="H1"):
        RS._check_module(R)


def test_the_contained_load_leaves_sys_path_and_warnings_unchanged():
    code = textwrap.dedent(f"""
        import sys, warnings
        sys.path.insert(0, {ROOT!r})
        from paperbot import sweepsig
        sweepsig.lib()
        path0, filters0 = list(sys.path), list(warnings.filters)
        from paperbot import reelsig
        reelsig.verify()
        assert sys.path == path0, "sys.path changed"
        assert warnings.filters == filters0, "warnings filters changed"
        assert reelsig.MODULE_NAME in sys.modules and "lib_reel5m" not in sys.modules
        print("ok")
    """)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300, cwd=ROOT)
    assert r.returncode == 0 and r.stdout.strip().endswith("ok"), r.stderr[-2000:]


# ------------------------------------------------------------------ parity with lib_reel5m, look-ahead, windows
@pytest.mark.parametrize("seed", [7, 11])
def test_signal_equals_lib_at_the_live_window(R, cost, seed):
    df = synth(REEL_WINDOW_5M + 2500, seed)
    A, ind = ref(R, cost, df)
    n = len(df)
    lo = REEL_WINDOW_5M - 1
    sig_bars = [t for t in A if t >= lo]
    assert len(sig_bars) >= 10
    rng = np.random.default_rng(seed)
    bars = set(sig_bars) | {t + 1 for t in sig_bars if t + 1 < n} | {t - 1 for t in sig_bars if t - 1 >= lo}
    bars |= set(rng.integers(lo, n, 40).tolist()) | {n - 1}
    for t in sorted(bars):
        r = RS.signal(window_end(df, t) if t % 2 else df.iloc[:t + 1])   # exactly the window, or a longer frame
        if t in A:
            same_as_ref(r, A[t], ind, t, df)
        else:
            assert r is None, t


@pytest.mark.parametrize("seed", [3, 5, 8])
def test_signal_equals_lib_on_every_bar_small_window(R, cost, monkeypatch, seed):
    monkeypatch.setattr(RS, "WINDOW", 600)
    df = synth(1500, seed, up_only=True)
    A, ind = ref(R, cost, df)
    hits = 0
    for t in range(len(df) - 600, len(df)):
        r = RS.signal(df.iloc[:t + 1])
        if t in A:
            same_as_ref(r, A[t], ind, t, df)
            hits += 1
        else:
            assert r is None, t
    assert hits >= 3


@pytest.mark.parametrize("seed", [7, 11, 23])
def test_the_dashboard_view_is_all_on_at_the_last_bar_exactly_when_the_bot_signals(R, cost, seed):
    """Views review, finding 1: lib_reel5m.simulate never reads a frame's last bar as a signal (it needs the entry bar
    s+1), so the live wrapper appends one NaN entry and the dashboard's REEL_H1 view runs its own machine. On the live
    window (the last config.REEL_WINDOW_5M closed 5m bars, as the dashboard fetches and the bot computes) the view's
    long conditions are all on at the last bar exactly when ``reelsig.signal`` fires, with the same levels: never "all
    four conditions on" while the bot stays silent, or the reverse. Every signal bar, the bars around it and random
    bars."""
    view = _reel_view()
    df = synth(REEL_WINDOW_5M + 1500, seed)
    A, _ind = ref(R, cost, df)
    n, lo = len(df), REEL_WINDOW_5M - 1
    sig = [t for t in A if t >= lo]
    rng = np.random.default_rng(seed)
    ends = set(sig) | {t + 1 for t in sig if t + 1 < n} | {t - 1 for t in sig if t - 1 >= lo}
    ends |= set(rng.integers(lo, n, 25).tolist()) | {n - 1}
    hits = sum(check_view(view, window_end(df, t)) for t in sorted(ends))
    assert hits == len(sig) >= 5


def test_no_lookahead(R, cost):
    """The signal of bar s uses bars <= s only: the anchored lib machine says the same about s whether the bars
    after s are the real ones or junk, and the wrapper (which never sees them) agrees."""
    df = synth(REEL_WINDOW_5M + 600, 21)
    A, ind = ref(R, cost, df)
    rng = np.random.default_rng(1)
    cuts = sorted([t for t in A if t >= REEL_WINDOW_5M][:6]) + sorted(rng.integers(REEL_WINDOW_5M, len(df), 6).tolist())
    for s in cuts:
        r = RS.signal(df.iloc[:s + 1])
        junk = synth(60, int(rng.integers(1e6)), red=-0.01)
        junk["ts"] = df["ts"].iloc[s] + pd.to_timedelta(FIVE * np.arange(1, 61), unit="ms")
        junk[["open", "high", "low", "close"]] *= df["close"].iloc[s] / 100 * rng.uniform(0.5, 2.0)
        A2, ind2 = ref(R, cost, pd.concat([df.iloc[:s + 1], junk], ignore_index=True))
        assert (s in A2) == (s in A) == (r is not None), s
        if r is not None:
            same_as_ref(r, A2[s], ind2, s, df)
            assert A2[s]["stop_px"] == A[s]["stop_px"] and A2[s]["target0"] == A[s]["target0"]


def test_only_the_last_window_is_read():
    df = synth(REEL_WINDOW_5M + 400, 13)
    ends = list(range(len(df) - 300, len(df)))
    junk = synth(500, 99)
    junk[["open", "high", "low", "close"]] = np.nan
    junk["ts"] = df["ts"].iloc[0] - pd.to_timedelta(FIVE * np.arange(500, 0, -1), unit="ms")
    for t in ends[::7] + [ends[-1]]:
        w = window_end(df, t)
        longer = pd.concat([junk, df.iloc[:t + 1]], ignore_index=True)
        assert RS.signal(longer) == RS.signal(w)
        assert RS.flip_levels(longer) == RS.flip_levels(w)


def test_ts_as_ms_naive_or_utc_datetimes_give_the_same_result(R, cost):
    df = synth(REEL_WINDOW_5M + 300, 7)
    A, _ind = ref(R, cost, df)
    late = [t for t in A if t >= REEL_WINDOW_5M - 1]
    assert late
    t = max(late)
    w = window_end(df, t)
    ms = w.assign(ts=(w["ts"].astype("int64") // 1_000_000).astype("int64"))
    naive = w.assign(ts=w["ts"].dt.tz_localize(None))
    base = RS.signal(w)
    assert base is not None and RS.signal(ms) == base == RS.signal(naive)
    assert RS.flip_levels(ms) == RS.flip_levels(w) == RS.flip_levels(naive)


# ------------------------------------------------------------------ H1 rules through the wrapper (hand-built bands)
NEUTRAL = (100.2, 100.6, 99.6, 100.0)        # red, inside the band [90, 110]
HOLD = (95.0, 95.4, 94.0, 94.5)              # red, inside
GREEN = (99.0, 100.5, 98.8, 100.0)           # green, closes inside: the signal bar when armed
BREACH = (91.0, 91.5, 88.0, 89.0)            # closes below the lower band (90): arms
GREEN_BREACH = (88.5, 89.5, 88.2, 89.0)      # green but closes below the band: a breach, never a signal


def hand(R, monkeypatch, rows, mid=None, ma=95.0, upper=None, lower=90.0, atr=None):
    """A frame of exactly WINDOW bars ending with ``rows`` (o, h, l, c), and lib_reel5m.indicators replaced by
    hand-built arrays: lower band 90, upper band 110, middle line 100 over the MA (95), ATR 1; ``mid`` / ``upper`` /
    ``atr`` = {offset from the end: value} change single bars."""
    n = RS.WINDOW
    a = np.array([NEUTRAL] * (n - len(rows)) + list(rows), float)
    df = pd.DataFrame({"ts": T0 + FIVE * np.arange(n, dtype=np.int64), "open": a[:, 0], "high": a[:, 1],
                       "low": a[:, 2], "close": a[:, 3], "volume": 1.0})

    def arr(changes, default):
        x = np.full(n, float(default))
        for off, val in (changes or {}).items():
            x[n + off] = val
        return x

    def fake(frame):
        assert len(frame) == n
        return {"o": a[:, 0].copy(), "h": a[:, 1].copy(), "l": a[:, 2].copy(), "c": a[:, 3].copy(),
                "upper": arr(upper, 110.0), "mid": arr(mid, 100.0), "lower": np.full(n, lower),
                "SMA200": np.full(n, ma), "EMA200": np.full(n, ma), "atr": arr(atr, 1.0),
                "up_live": np.full(n, np.nan), "dn_live": np.full(n, np.nan)}
    monkeypatch.setattr(R, "indicators", fake)
    return df


def test_breach_then_green_inside_is_the_signal(R, monkeypatch):
    df = hand(R, monkeypatch, [BREACH, HOLD, HOLD, GREEN])
    r = RS.signal(df)
    assert r == {"side": 1, "bar_open": T0 + FIVE * (RS.WINDOW - 1), "atr14": 1.0, "swing_low": 88.0,
                 "stop": 88.0 - 0.05 * 1.0, "up_band": 110.0,
                 "closes": [100.0] * 15 + [89.0, 94.5, 94.5, 100.0]}
    assert len(r["closes"]) == 19


def test_the_breach_bar_is_never_the_signal(R, monkeypatch):
    for rows in ([BREACH], [GREEN_BREACH], [BREACH, GREEN_BREACH], [BREACH, HOLD, GREEN_BREACH]):
        df = hand(R, monkeypatch, rows)
        assert RS.signal(df) is None, rows


def test_the_setup_expires_twelve_bars_after_the_last_breach(R, monkeypatch):
    df = hand(R, monkeypatch, [BREACH] + [HOLD] * 11 + [GREEN])        # green 12 bars after the breach
    assert RS.signal(df) is not None
    df = hand(R, monkeypatch, [BREACH] + [HOLD] * 12 + [GREEN])        # 13 bars after: expired
    assert RS.signal(df) is None


def test_a_new_breach_restarts_the_clock_and_keeps_the_first_low(R, monkeypatch):
    first = (91.0, 91.5, 85.0, 89.0)
    df = hand(R, monkeypatch, [first] + [HOLD] * 8 + [BREACH] + [HOLD] * 11 + [GREEN])
    r = RS.signal(df)
    assert r is not None and r["swing_low"] == 85.0 and r["stop"] == 85.0 - 0.05


def test_the_filter_turning_off_cancels_the_arming(R, monkeypatch):
    rows = [BREACH, HOLD, HOLD, GREEN]
    assert RS.signal(hand(R, monkeypatch, rows)) is not None
    assert RS.signal(hand(R, monkeypatch, rows, mid={-2: 94.0})) is None     # off on a waiting bar, on again
    assert RS.signal(hand(R, monkeypatch, rows, mid={-1: 94.0})) is None     # off on the green bar
    assert RS.signal(hand(R, monkeypatch, rows, mid={-4: 94.0})) is None     # off on the breach bar: never armed


def test_the_machine_is_free_after_a_signal(R, monkeypatch):
    assert RS.signal(hand(R, monkeypatch, [BREACH, GREEN, GREEN])) is None   # a second green needs a new breach
    assert RS.signal(hand(R, monkeypatch, [BREACH, GREEN, BREACH, GREEN])) is not None


def test_nan_or_zero_atr_or_nan_band_on_the_signal_bar_gives_none(R, monkeypatch):
    rows = [BREACH, HOLD, GREEN]
    assert RS.signal(hand(R, monkeypatch, rows, atr={-1: np.nan})) is None
    assert RS.signal(hand(R, monkeypatch, rows, atr={-1: 0.0})) is None
    assert RS.signal(hand(R, monkeypatch, rows, upper={-1: np.nan})) is None
    assert RS.flip_levels(hand(R, monkeypatch, rows, atr={-1: np.nan})) is None
    assert RS.flip_levels(hand(R, monkeypatch, rows, upper={-1: np.nan})) is None


def test_never_short(R, cost, monkeypatch):
    up_breach = (109.0, 112.0, 108.5, 111.0)                 # closes above the upper band, MA over the middle line
    red_in = (101.0, 101.5, 99.5, 100.0)
    assert RS.signal(hand(R, monkeypatch, [up_breach, red_in], ma=105.0)) is None
    monkeypatch.undo()
    for seed in (2, 4, 6):                                    # falling and rising markets: only longs, ever
        df = synth(REEL_WINDOW_5M + 300, seed)
        for t in range(len(df) - 300, len(df), 10):
            r = RS.signal(df.iloc[:t + 1])
            assert r is None or r["side"] == 1
            f = RS.flip_levels(df.iloc[:t + 1])
            assert f is not None and f["side"] == 1


def test_a_short_from_lib_is_an_error_not_a_trade(R, monkeypatch):
    df = synth(RS.WINDOW + 10, 3)
    n = RS.WINDOW
    monkeypatch.setattr(R, "simulate", lambda *a, **k: ([], [{"signal_idx": n - 1, "side": -1, "extreme": 1.0,
                                                              "stop_px": 1.1, "target0": 0.9}], {}))
    with pytest.raises(RS.ReelError, match="side"):
        RS.signal(df)


# ------------------------------------------------------------------ short, NaN and malformed frames
def test_short_and_nan_windows_give_none():
    df = synth(RS.WINDOW + 50, 5)
    assert RS.signal(df.iloc[:RS.WINDOW - 1]) is None and RS.flip_levels(df.iloc[:RS.WINDOW - 1]) is None
    assert RS.signal(df.iloc[:0]) is None
    for col in ("open", "high", "low", "close"):
        for bad in (np.nan, np.inf):
            d = df.copy()
            d.loc[len(d) - 100, col] = bad                   # inside the window
            assert RS.signal(d) is None and RS.flip_levels(d) is None
    d = df.copy()
    d.loc[10, "close"] = np.nan                               # before the window: not read
    assert RS.flip_levels(d) == RS.flip_levels(df) and RS.signal(d) == RS.signal(df)
    d = df.copy()
    d["volume"] = np.nan                                      # volume is not used
    assert RS.flip_levels(d) == RS.flip_levels(df)


@pytest.mark.parametrize("case", ["unsorted", "duplicate", "off_grid", "no_close", "not_a_frame", "text_ts"])
def test_malformed_frames_raise_reel_error(case):
    df = synth(RS.WINDOW + 10, 5)
    if case == "unsorted":
        df = df.iloc[list(range(len(df) - 2)) + [len(df) - 1, len(df) - 2]]
    elif case == "duplicate":
        df.loc[len(df) - 1, "ts"] = df["ts"].iloc[-2]
    elif case == "off_grid":
        df["ts"] = df["ts"] + pd.Timedelta(minutes=1)
    elif case == "no_close":
        df = df.drop(columns=["close"])
    elif case == "not_a_frame":
        df = df.to_dict("list")
    elif case == "text_ts":
        df["ts"] = df["ts"].astype(str)
    for fn in (RS.signal, RS.flip_levels):
        with pytest.raises(RS.ReelError):
            fn(df)


def test_every_failure_inside_becomes_reel_error(R, monkeypatch):
    df = synth(RS.WINDOW + 10, 5)

    def boom(*a, **k):
        raise ValueError("boom")
    monkeypatch.setattr(R, "simulate", boom)
    with pytest.raises(RS.ReelError, match="ValueError"):
        RS.signal(df)
    monkeypatch.setattr(R, "indicators", lambda frame: {})
    for fn in (RS.signal, RS.flip_levels):
        with pytest.raises(RS.ReelError):
            fn(df)


# ------------------------------------------------------------------ 5m coin flips (owners' D4)
def _wilder_atr(h, l, c, n=14):
    tr = np.r_[h[0] - l[0], np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])]
    out = np.empty(len(tr))
    out[0] = tr[0]
    for i in range(1, len(tr)):
        out[i] = out[i - 1] + (tr[i] - out[i - 1]) / n
    return out


def test_flip_levels_from_first_principles():
    df = synth(RS.WINDOW + 200, 17)
    for t in (len(df) - 1, len(df) - 50, len(df) - 133):
        w = window_end(df, t)
        f = RS.flip_levels(w)
        h, l, c = (w[k].to_numpy(float) for k in ("high", "low", "close"))
        swing = float(l[-12:].min())
        atr = _wilder_atr(h, l, c)[-1]
        up = c[-20:].mean() + 2.0 * c[-20:].std(ddof=0)
        assert set(f) == KEYS and f["side"] == 1
        assert f["swing_low"] == swing and rel(f["atr14"], atr) < 1e-9 and rel(f["up_band"], up) < 1e-9
        assert f["stop"] == swing - 0.05 * f["atr14"]
        assert f["closes"] == [float(x) for x in c[-19:]]
        assert f["bar_open"] == int(w["ts"].iloc[-1].value // 1_000_000)


def test_flip_swing_low_is_the_last_twelve_bars(R, monkeypatch):
    low12 = (95.0, 95.4, 93.0, 94.5)
    low13 = (95.0, 95.4, 92.0, 94.5)
    f = RS.flip_levels(hand(R, monkeypatch, [low12] + [NEUTRAL] * 11))
    assert f["swing_low"] == 93.0 and f["stop"] == 93.0 - 0.05
    f = RS.flip_levels(hand(R, monkeypatch, [low13] + [NEUTRAL] * 12))
    assert f["swing_low"] == 99.6


def test_flip_and_signal_share_the_bar_numbers(R, cost):
    df = synth(REEL_WINDOW_5M + 400, 7)
    A, _ind = ref(R, cost, df)
    for t in [t for t in A if t >= REEL_WINDOW_5M][:5]:
        r, f = RS.signal(df.iloc[:t + 1]), RS.flip_levels(df.iloc[:t + 1])
        assert {k: r[k] for k in ("side", "bar_open", "atr14", "up_band", "closes")} == \
               {k: f[k] for k in ("side", "bar_open", "atr14", "up_band", "closes")}


# ------------------------------------------------------------------ the Signal contract of reel_engine
def test_the_dict_is_what_reel_engine_takes(R, cost):
    from paperbot import reel_engine as RE
    from paperbot.models import Signal
    assert RS.WAIT == R.WAIT and RS.STOP_BUF_ATR == R.STOP_BUF_ATR == RE.STOP_BUF_ATR
    assert RS.FLIP_LOOKBACK == RE.FLIP_LOOKBACK and RS.BB_LEN == RE.BB_LEN == R.BB_LEN
    assert RS.WINDOW == REEL_WINDOW_5M >= 2_000 and REEL_TF == R.H1[0] == "5m"
    df = synth(REEL_WINDOW_5M + 500, 11)
    A, ind = ref(R, cost, df)
    sigs = [t for t in A if REEL_WINDOW_5M <= t < len(df) - 1][:6]
    assert sigs
    for t in sigs:
        for lv in (RS.signal(df.iloc[:t + 1]), RS.flip_levels(df.iloc[:t + 1])):
            assert json.loads(json.dumps(lv)) == lv
            sig = Signal(ts=lv["bar_open"] + FIVE - 1, symbol="BTCUSDT", timeframe="5m", strategy_id="REEL_H1", side=1,
                         stop_price=lv["stop"], tier="best", tp_price=lv["up_band"], atr=lv["atr14"],
                         meta={"ref_price": 1.0, "ref_time": 0, "delay_ms": 0, "account": "REEL_H1@5m", "reel": lv})
            assert RE.signal_problem(sig) is None
            c = df["close"].to_numpy(float)
            assert rel(RE.upper_band(c[t - 19:t + 1]), lv["up_band"]) < 1e-9         # the first target
            assert rel(RE.upper_band(lv["closes"] + [c[t + 1]]), ind["upper"][t + 1]) < 1e-9   # the next one


# ------------------------------------------------------------------ real 5m bars (DS_BARS_DIR)
COINS = ("btcusd", "ethusd", "solusd", "dogeusd", "ltcusd", "bchusd")
_REAL: dict = {}


def real(R, cost, coin):
    """(5-year 5m frame up to 2026-09-29, anchored signals, indicators) of one coin, cached."""
    if coin not in _REAL:
        p = os.path.join(BARS, f"{coin}-5m.csv.gz")
        if not os.path.exists(p):
            pytest.skip(f"{p} missing")
        df = pd.read_csv(p)
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df[df["ts"] < pd.Timestamp("2026-09-30", tz="UTC")].reset_index(drop=True)
        A, ind = ref(R, cost, df)
        _REAL.clear()                                     # keep one coin in memory
        _REAL[coin] = (df, A, ind)
    return _REAL[coin]


needs_bars = pytest.mark.skipif(not BARS, reason="set DS_BARS_DIR to the Binance bar files (<coin>-5m.csv.gz)")


# Float ties (recorded 2026-10-05 with pandas 2.3.3 / numpy 2.4.6 on the 5-year files). On a few bars the H1 decision
# is a tie in real numbers: four of the 20 closes equal the close and sixteen another price, so the close IS the
# lower band; or the 20-bar mean equals the 200-bar mean on the tick grid. lib_reel5m's pandas rolling sums then
# decide by their rounding, which depends on where the computation started: the research's anchored 5-year series
# (band error up to 2e-8 relative against exact sums; middle line and SMA200 below 4e-16) and a fresh window round
# differently. No window length removes this. A decision can differ only where the exact margin is below the two
# rounding errors, so every bar whose anchored margin (|close - band| / close or |mid - SMA200| / SMA200) is below
# TIE_REL = 1e-7 was taken (129 bars in 5 years of six coins) and every bar of the 25 after it (a setup lasts at most
# 14 bars) was run with windows of 2,000 / 3,000 / 5,000 bars: these are ALL the differences from the anchored
# machine, {coin: {window: [(tie bar, differing bar)]}}. At the live window (5,000): 2 in 5 years of six coins (3.6
# million coin-bars), both 2023, both a signal in the anchored series that the window does not give.
TIE_MISMATCHES = {
    "btcusd": {}, "ethusd": {},
    "solusd": {2_000: [(573421, 573422)], 3_000: [(573421, 573422)]},
    "dogeusd": {2_000: [(295250, 295251)], 3_000: [(295250, 295251), (346500, 346501)], 5_000: [(295250, 295251)]},
    "ltcusd": {2_000: [(540395, 540396)], 3_000: [(268814, 268815)], 5_000: [(268814, 268815)]},
    "bchusd": {2_000: [(180666, 180668)], 3_000: [(180666, 180668)]},
}
TIE_REL = 1e-7
VIEW_LAST_BARS = 576         # every bar of the last two days: the view's contiguous check (``check_view_last_bar``)
TIE_AFTER = 16               # bars checked after each tie bar in the test (the recorded run checked 25)


def tie_bars(ind) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        return np.flatnonzero((np.abs(ind["mid"] - ind["SMA200"]) / ind["SMA200"] < TIE_REL)
                              | (np.abs(ind["c"] - ind["lower"]) / ind["c"] < TIE_REL)
                              | (np.abs(ind["c"] - ind["upper"]) / ind["c"] < TIE_REL))


def check_start_invariance(R, cost, coin):
    """A window started W bars back runs the anchored machine exactly once its SMA200 has warmed up (200 bars),
    unless a setup began before that: every setup of 5 years is far shorter than 2,000 - 200 bars, so the machine
    itself never depends on the window. The indicators can, by rounding, only on a float tie: real windows of
    2,000 / 3,000 / 5,000 bars equal the anchored machine at random signal bars, the bars after them and random bars,
    and on the TIE_AFTER bars after every tie bar they differ exactly at the recorded TIE_MISMATCHES."""
    df, A, ind = real(R, cost, coin)
    assert len(df) > 600_000 and len(A) > 7_000
    span = max(t - a["arm_idx"] for t, a in A.items())
    assert span + 200 < 2_000 <= REEL_WINDOW_5M, span
    rng = np.random.default_rng(len(A))
    sig = np.array(sorted(A))
    picks = set(rng.choice(sig[sig >= 5_000], 12, replace=False).tolist())
    picks |= {t + 1 for t in picks} | set(rng.integers(5_000, len(df), 12).tolist()) | {len(df) - 1}
    ties = tie_bars(ind)
    for i in ties[ties >= 5_000]:
        picks |= set(range(int(i), min(int(i) + TIE_AFTER, len(df))))
    old = RS.WINDOW
    for w in (2_000, 3_000, 5_000):
        found = []
        RS.WINDOW = w
        try:
            for t in sorted(picks):
                if t - w + 1 < 0:
                    continue
                r = RS.signal(window_end(df, t, w))
                if (r is None) != (t not in A):
                    near = [int(i) for i in ties if i <= t < i + 25]
                    assert near, (w, t, "differs without a float tie")
                    found.append((max(near), t))
                elif r is not None:
                    same_as_ref(r, A[t], ind, t, df)
        finally:
            RS.WINDOW = old
        assert found == TIE_MISMATCHES[coin].get(w, []), (w, found)


def check_parity_2026_07_to_09(R, cost, coin):
    """Live window (REEL_WINDOW_5M bars) against the anchored 5-year lib_reel5m machine: every signal bar of
    September 2026 and the bar after it, and 60 random bars of July..September 2026. (Every bar of July..September,
    all six coins: recorded in the module docstring.)"""
    df, A, ind = real(R, cost, coin)
    lo = int(df["ts"].searchsorted(pd.Timestamp("2026-07-01", tz="UTC")))
    sep = int(df["ts"].searchsorted(pd.Timestamp("2026-09-01", tz="UTC")))
    rng = np.random.default_rng(7)
    sig = [t for t in A if t >= sep]
    assert len(sig) > 50
    picks = set(sig) | {t + 1 for t in sig if t + 1 < len(df)} | set(rng.integers(lo, len(df), 60).tolist())
    for t in sorted(picks):
        r = RS.signal(window_end(df, t))
        if t in A:
            same_as_ref(r, A[t], ind, t, df)
        else:
            assert r is None, t
        if t % 5 == 0:
            f = RS.flip_levels(window_end(df, t))
            assert f["swing_low"] == float(ind["l"][t - 11:t + 1].min())
            assert rel(f["atr14"], ind["atr"][t]) < 1e-9 and rel(f["up_band"], ind["upper"][t]) < 1e-7


def check_view_last_bar(R, cost, coin):
    """The dashboard's REEL_H1 view on real live windows (the last config.REEL_WINDOW_5M closed 5m bars each, as the
    dashboard fetches and the bot computes): AND(view_REEL_H1(w)["long"])[-1] == (reelsig.signal(w) is not None), with
    the same levels, at signals of the 5 years whose window holds no float tie (TIE_MISMATCHES), sampled, the bars
    after them, random bars and every bar of the last two days. (Recorded once, 2026-10-05, scratch script: every bar
    of 2026-08-31..2026-09-29, the six coins, 51,840 live windows, 632 of them signals: the AND agreed on every one.)"""
    df, A, ind = real(R, cost, coin)
    view = _reel_view()
    rng = np.random.default_rng(len(A) + 1)
    lo = REEL_WINDOW_5M - 1
    sig = np.array(sorted(t for t in A if t >= lo))
    pick = rng.choice(sig, 40, replace=False)
    ends = set(pick.tolist()) | {int(t) + 1 for t in pick} | set(rng.integers(lo, len(df), 40).tolist())
    ends |= set(range(len(df) - VIEW_LAST_BARS, len(df)))
    ties = {b for pairs in TIE_MISMATCHES[coin].values() for pair in pairs for b in pair}
    ends = {t for t in ends if not any(t - REEL_WINDOW_5M < b <= t for b in ties)}
    hits = sum(check_view(view, window_end(df, t)) for t in sorted(ends))
    assert hits == len([t for t in ends if t in A]) >= 30


@needs_bars
@pytest.mark.parametrize("coin,check", [(c, k) for c in COINS
                                        for k in ("start_invariance", "parity_2026_07_09", "view_last_bar")])
def test_real_5m_bars(R, cost, coin, check):
    """Coin by coin (one coin's 5 years in memory at a time): start invariance, parity with lib_reel5m, and the
    dashboard view's last bar against the live signal."""
    {"start_invariance": check_start_invariance, "parity_2026_07_09": check_parity_2026_07_to_09,
     "view_last_bar": check_view_last_bar}[check](R, cost, coin)
