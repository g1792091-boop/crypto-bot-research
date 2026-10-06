"""Shared pieces of the shadow league tests: committed synthetic bars, a fake Binance klines endpoint, hand-made bars.
Nothing here touches the network or the research environment."""

from __future__ import annotations

import os
import urllib.parse

import numpy as np

from paperbot.shadowleague import league as LG
from paperbot.shadowleague.feed import SETTLE_MS, TF_MS
from paperbot.shadowleague.store import Store

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "shadowleague")
T0 = LG.utc_ms(2026, 1, 1)                      # a multiple of 4 hours: every bar grid starts here
MIN, HOUR = 60_000, 3_600_000
SEEDS = {"BTC": 10, "ETH": 1, "SOL": 24, "DOGE": 10, "LTC": 1, "BCH": 24}
SCALE = {"BTC": 1.0, "ETH": 0.5, "SOL": 0.25, "DOGE": 0.002, "LTC": 0.8, "BCH": 3.0}


def load_fixture(seed: int, scale: float = 1.0, flip: bool = False) -> dict:
    """{'o','h','l','c','v'} of one committed fixture; ``scale`` multiplies the prices, ``flip`` mirrors them (p -> 200 - p
    before scaling) so a series differs from another that uses the same seed."""
    import pandas as pd
    df = pd.read_csv(os.path.join(DATA, f"synth_{seed}.csv.gz"))
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    v = df["volume"].to_numpy(float)
    if flip:
        o, c, h, l = 200.0 - o, 200.0 - c, 200.0 - l, 200.0 - h
    return {"o": o * scale, "h": h * scale, "l": l * scale, "c": c * scale, "v": v}


def series_arrays(coin: str, tf: str) -> dict:
    flip = tf in ("30m", "4h")
    return load_fixture(SEEDS[coin], SCALE[coin], flip=flip)


class FakeExchange:
    """Binance USD-M klines as the agents tick sees them through ``get(url)``. Bars of (coin, tf) lie on the tf grid from
    T0; a bar exists once it has opened (the forming bar is returned, like the real endpoint does, if the request allows).
    ``requests`` records every call; ``fail`` makes the next calls raise; ``garbage`` returns rubbish rows."""

    def __init__(self, coins=("BTC", "ETH"), tfs=("1h",), now_ms: int = T0, arrays=None, t0: int = T0):
        self.now_ms = int(now_ms)
        self.t0 = int(t0)
        self.data = {(c, tf): (arrays or {}).get((c, tf)) or series_arrays(c, tf) for c in coins for tf in tfs}
        self.requests: list[dict] = []
        self.fail = 0
        self.garbage = False

    def get(self, url: str):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        sym, tf = q["symbol"][0], q["interval"][0]
        self.requests.append({"symbol": sym, "interval": tf, "start": int(q.get("startTime", [0])[0]),
                              "end": int(q["endTime"][0]) if "endTime" in q else None, "limit": int(q["limit"][0])})
        if self.fail:
            self.fail -= 1
            raise TimeoutError("timed out")
        coin = sym[:-4]
        arr = self.data[(coin, tf)]
        tfm = TF_MS[tf]
        n = len(arr["o"])
        start = int(q.get("startTime", [self.t0])[0])
        end = int(q["endTime"][0]) if "endTime" in q else self.now_ms
        first = max(0, -(-(start - self.t0) // tfm))
        last = min(n - 1, (min(end, self.now_ms) - self.t0) // tfm)        # opened bars only
        rows = []
        for i in range(first, last + 1):
            t = self.t0 + i * tfm
            rows.append([t] + [repr(float(arr[k][i])) for k in ("o", "h", "l", "c", "v")]
                        + [t + tfm - 1, "0", 0, "0", "0", "0"])
            if len(rows) >= int(q["limit"][0]):
                break
        if self.garbage:
            return [[r[0], "x", "y", "z", "w", "1", r[6]] for r in rows]
        return rows

    def requests_for(self, coin: str, tf: str) -> list[dict]:
        return [r for r in self.requests if r["symbol"] == coin + "USDT" and r["interval"] == tf]


def make_member(member_id="test", coins=("BTC",), tfs=("1h",), start_ms: int = T0 + 1300 * HOUR, k: int = 10,
                min_bars=None, name_ko="시험 멤버") -> LG.Member:
    det = LG.ZoneFlipDetector()
    return LG.Member(member_id=member_id, name_ko=name_ko, detector=det, start_ms=int(start_ms), tfs=tuple(tfs),
                     coins=tuple(coins), clones_k=k, study="zoneflip")


def open_store(tmp_path, name="shadow_league.db") -> Store:
    return Store(os.path.join(str(tmp_path), name))


def now_after_bar(tf: str, index: int) -> int:
    """A wall-clock time shortly after bar ``index`` (0-based on the grid) closed: the bar is settled, the next one not."""
    return T0 + (index + 1) * TF_MS[tf] + SETTLE_MS + 5_000


# ------------------------------------------------------------------------------------------------ hand-made bars
def hand_made(touch_bars=(150, 152, 200, 240), break_close: float = 99.0, retest_close: float = 99.5,
              target_zone=(92.5, 94.5), mirror: bool = False) -> dict:
    """300 bars (the study's own hand-made case, lib_zoneflip.handmade, in numpy). The profile of the break bar 270 (bars
    70..269: lowest low 90, highest high 115, 50 buckets of 0.5) has exactly three zones: A [100, 101] (the support), the
    target zone and C [108, 110]. Price sits at 102.5-103.5 above A, touches A at ``touch_bars``, breaks below at bar 270,
    retests at bar 273 (high 100.5, closes ``retest_close``) and falls to 94 by bar 276. ``mirror``: p -> 205 - p."""
    n = 300
    o = np.full(n, 103.0)
    c = np.full(n, 103.0)
    hh = np.full(n, 103.5)
    ll = np.full(n, 102.5)
    v = np.ones(n)

    def bar(i, oo, hi, lo, cc, vol=1.0):
        o[i], hh[i], ll[i], c[i], v[i] = oo, hi, lo, cc, vol

    bar(70, 90.5, 91.0, 90.0, 90.5)
    bar(71, 114.5, 115.0, 114.0, 114.5)
    t0, t1 = target_zone
    nbk = int(round((t1 - t0) / 0.5))
    for i in range(72, 82):
        bar(i, t0 + 0.5, t1, t0, t1 - 0.5, 100.0 * nbk)
    for i in range(82, 92):
        bar(i, 108.5, 110.0, 108.0, 109.5, 400.0)
    for i in range(92, 102):
        bar(i, 100.5, 101.0, 100.0, 100.5, 200.0)
    for j in touch_bars:
        bar(j, 103.0, 103.5, 100.5, 102.0)
    bar(270, 103.0, 103.0, 98.5, break_close)
    bar(271, break_close, max(99.5, break_close), 98.5, 99.0)
    bar(272, 99.0, 99.5, 98.5, 99.0)
    bar(273, 99.0, 100.5, 98.75, retest_close)
    bar(274, retest_close, 99.75, 98.0, 98.25)
    bar(275, 98.25, 98.5, 96.5, 96.75)
    bar(276, 96.75, 97.0, 94.0, 94.25)
    for i in range(277, n):
        bar(i, 94.25, 94.5, 94.0, 94.25)
    if mirror:
        o, c, hh, ll = 205.0 - o, 205.0 - c, 205.0 - ll, 205.0 - hh
    return {"o": o, "h": hh, "l": ll, "c": c, "v": v}
