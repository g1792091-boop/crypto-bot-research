"""추세판단 봇 (owners 2026-10-21): the trend judge and the entry checks of the trend bot (paperbot/trendbot.py).

The four trend-type strategies never enter. Their indicator STATES on the last CLOSED higher bar decide the direction
(owners: "추세형 매매법은 진입 안 하고 추세만 보는 거"):
- a 30m entry reads the last closed 1h bar, a 1h entry the last closed 4h bar (a 30m entry never reads 4h);
- each judge is +1 / -1 / 0 on that bar, with the same indicator functions and numbers as its chart view
  (paperbot/strategy_view_defs), so the dashboard's lines show what the bot read:
    V39  V3.9's supertrend (10, 3) direction             pi.exchange_supertrend      view "슈퍼트렌드(10·3) 상승"
    S6   close vs EMA20 and +DI vs -DI (14, 14), both    fg.ema, fg.dmi_adx          view "종가가 EMA20 위", "+DI가 -DI 위"
    OBV  OBV vs its 30-bar average                       pi.obv, pi.pine_sma         view "OBV가 30봉 평균 위"
    N12  close above (below) the whole Ichimoku cloud visible at the bar (9, 26, 52, 26) and AO (5, 34) above (below) 0
- direction: ``vote_min`` (3) or more of the four on one side, else 보류 (no entry);
- strength: ADX (14, 14) of that bar at least ``adx_min`` (20); above ``adx_tired`` (40) and lower than the bar
  before = 끝물 (no entry). A high ADX is never a reason to enter;
- hold: the same direction on the last ``hold`` closed bars (1h: 2, 4h: 1), else 보류.

The entry checks (``check``) of an entry member's signal, all on closed bars and the signal's reference price:
the higher bar's direction = the signal's side, its strength, not 끝물; a breakout member (BOS, ORB, MACD·시가범위)
only early in the trend (ADX below ``breakout_adx_max`` and rising); the price at most ``htf_ema_atr`` (1.5) ATR
beyond the higher bar's EMA20 in the trade's direction and within ``etf_ema_atr`` (1.5) ATR of the entry bar's EMA20;
entry-bar RSI below 70 for a long, above 30 for a short. A pass returns the pullback to wait for: ``pullback_atr``
(0.25) entry-bar ATR from the reference price, ``pullback_big_atr`` (0.5) when the signal bar's range is over
``big_bar_atr`` (2) ATR (a long bar is never chased: a deeper pullback).

Bars: Binance USDT-M klines (public; volume for OBV), only bars closed ``SETTLE_MS`` before now, the last ``KEEP`` closed
bars at or before the time asked (``Klines.frame``): the same answer for the same minute on a replay.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import pandas as pd

MIN = 60_000
TF_MS = {"30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}
HTF_OF = {"30m": "1h", "1h": "4h"}             # the entry timeframe -> the timeframe its trend is judged on
KO_TF = {"30m": "30분", "1h": "1시간", "4h": "4시간"}
JUDGES = ("V39", "S6", "OBV", "N12")
KO_JUDGE = {"V39": "V3.9", "S6": "EMA·DMI·ADX", "OBV": "OBV 추세형", "N12": "일목·AO"}
JUDGE_STRATEGY = {"V39": "V39_ALL", "S6": "S6_EMA_DMI_ADX", "OBV": "OBV_S", "N12": "N12_ICHI_AO"}
BREAKOUT = ("F3_BOS", "F15_ORB", "N06_MACD_ORB")
KO_DIR = {1: "상승", -1: "하락", 0: "보류"}
KEEP = 300                  # closed bars per frame (Ichimoku needs 78, the RMA / EMA / supertrend settle long before 300)
MIN_BARS = 120              # fewer closed bars than this: not judged
FETCH = 499                 # rows per klines request (Binance weight 2 below 500)
SETTLE_MS = 3_000           # a bar counts as closed this long after its close (the exchange's last trades of it)
RETRY_MS = 20_000           # after a failed fetch no fetch at all for this long (doubling to RETRY_MAX_MS while it fails),
                            # counted from the end of the failed request; the live site's picture (``bg``) waits apart
RETRY_MAX_MS = 120_000      # (Binance down: one short failed request per wait, never one per coin per minute)


class TrendError(ValueError):
    """A trend judgment that cannot be made, or a config the trend bot refuses (message in Korean)."""


# ====================================================================== the rules
@dataclass(frozen=True)
class TrendRules:
    """The trend bot's numbers (config ``"trend": {...}``; every key optional, these are the owners' 10-21 numbers)."""
    vote_min: int = 3                 # of the 4 judges on one side
    adx_min: float = 20.0             # higher bar's ADX at least this: a trend
    adx_tired: float = 40.0           # above this and lower than the bar before: 끝물
    hold_1h: int = 2                  # closed 1h bars the direction must have held
    hold_4h: int = 1
    htf_ema_atr: float = 1.5          # price at most this many higher-bar ATR beyond its EMA20, in the trade's direction
    etf_ema_atr: float = 1.5          # price within this many entry-bar ATR of the entry bar's EMA20 (either side)
    big_bar_atr: float = 2.0          # a signal bar longer than this many ATR: the deeper pullback
    pullback_atr: float = 0.25        # the pullback waited for (entry-bar ATR from the reference price)
    pullback_big_atr: float = 0.5
    rsi_long_max: float = 70.0        # entry-bar RSI(14): no long at or above, no short at or below rsi_short_min
    rsi_short_min: float = 30.0
    breakout: tuple = BREAKOUT        # strategies that take only an early trend
    breakout_adx_max: float = 30.0    # early trend: ADX below this and rising
    time_bars: int = 4                # entry bars without the first lock: closed (TIME)
    judge_exit: bool = True           # the higher bar's judgment turned against the position before the first lock: closed
    member_losses: int = 2            # losing trades in a row of one member ...
    member_pause_h: float = 24.0      # ... pause that member this long
    coin_pause_h: float = 2.0         # after a losing trade: no entry on that coin and side for this long
    daily_loss: Optional[float] = None  # the account lost this share in a KST day: no entry until the next day; None
                                        # = no daily limit (owners 10-21: "10번은 없애고")
    record_n: int = 10                # a member's recent trades read for the score
    record_min: int = 3               # fewer trades than this: the record counts 0

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "TrendRules":
        if d is None:
            d = {}
        if not isinstance(d, dict):
            raise TrendError("trend는 {이름: 값} 형식입니다")
        known = {f.name for f in dataclasses.fields(cls)}
        unknown = sorted(set(d) - known)
        if unknown:
            raise TrendError(f"trend에 알 수 없는 이름: {', '.join(unknown)}")
        d = dict(d)
        if "breakout" in d and isinstance(d["breakout"], list):
            d["breakout"] = tuple(d["breakout"])
        return cls(**d)

    def hold(self, htf: str) -> int:
        return self.hold_4h if htf == "4h" else self.hold_1h

    def problems(self) -> list[str]:
        out = []

        def num(name, lo, hi, integer=False):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or (integer and not isinstance(v, int)):
                out.append(f"trend.{name}는 {'정수' if integer else '숫자'}입니다")
            elif not lo <= v <= hi:
                out.append(f"trend.{name}는 {lo:g}~{hi:g}입니다")
        num("vote_min", 2, 4, True)
        num("adx_min", 0, 100)
        num("adx_tired", 0, 100)
        num("hold_1h", 1, 6, True)
        num("hold_4h", 1, 6, True)
        for k in ("htf_ema_atr", "etf_ema_atr", "big_bar_atr", "pullback_big_atr"):
            num(k, 0.05, 10)
        num("pullback_atr", 0, 5)
        num("rsi_long_max", 50, 100)
        num("rsi_short_min", 0, 50)
        num("breakout_adx_max", 0, 100)
        num("time_bars", 1, 48, True)
        num("member_losses", 1, 10, True)
        num("member_pause_h", 0, 240)
        num("coin_pause_h", 0, 240)
        if self.daily_loss is not None:
            num("daily_loss", 0.01, 1)
        num("record_n", 1, 100, True)
        num("record_min", 1, 100, True)
        if not isinstance(self.judge_exit, bool):
            out.append("trend.judge_exit는 true 또는 false입니다")
        if not (isinstance(self.breakout, tuple) and all(isinstance(s, str) for s in self.breakout)):
            out.append("trend.breakout은 매매법 이름 목록입니다")
        if not out and self.adx_tired <= self.adx_min:
            out.append("trend.adx_tired는 adx_min보다 커야 합니다")
        if not out and self.breakout_adx_max <= self.adx_min:
            out.append("trend.breakout_adx_max는 adx_min보다 커야 합니다")
        return out

    def describe(self) -> list[str]:
        """The rules in the owners' words (check-config, the start message, the docs)."""
        return [
            f"추세 판단: 30분 진입은 끝난 1시간봉, 1시간 진입은 끝난 4시간봉 / 판단 4개(V3.9·EMA·DMI·ADX·OBV 추세형·일목·AO) 중 "
            f"{self.vote_min}개 이상 같은 쪽 / ADX {self.adx_min:g} 이상, {self.adx_tired:g} 넘고 꺾이면 끝물 / "
            f"유지 1시간봉 {self.hold_1h}개·4시간봉 {self.hold_4h}개 / 보류면 진입 안 함",
            f"진입 전 검사: 상위 봉 EMA20에서 진입 방향 {self.htf_ema_atr:g} ATR 넘게 멀면 안 함 / 진입 봉 EMA20에서 "
            f"{self.etf_ema_atr:g} ATR 안 / RSI 롱 {self.rsi_long_max:g} 미만·숏 {self.rsi_short_min:g} 초과 / 돌파형("
            f"{', '.join(self.breakout)})은 ADX {self.breakout_adx_max:g} 미만이고 오를 때만 / 추격 막기 전체",
            f"진입 방식: 진입 봉 하나 동안 {self.pullback_atr:g} ATR 되돌림을 기다림(신호 봉이 {self.big_bar_atr:g} ATR 넘는 "
            f"장대봉이면 {self.pullback_big_atr:g} ATR), 안 오면 버림 / 동시 신호는 점수(판단 강도+자리+최근 성적)",
            f"쉬기: 같은 매매법 손실 {self.member_losses}번 연속이면 {self.member_pause_h:g}시간 / 손실 뒤 같은 코인·같은 "
            f"방향 {self.coin_pause_h:g}시간 / " + (f"하루(한국 시간) 계좌 -{self.daily_loss:.0%}면 그날 진입 안 함"
                                                 if self.daily_loss is not None else "하루 손실 한도 없음"),
            f"감독(첫 잠금 전까지만): 상위 봉 판단이 반대로 바뀌면 청산({'켬' if self.judge_exit else '끔'}) / "
            f"진입 봉 {self.time_bars}개 안에 첫 잠금 못 가면 청산",
        ]


# ====================================================================== bars
class Klines:
    """Closed Binance klines per (coin, timeframe), oldest first, fetched when a newer closed bar is wanted.
    ``fetch(symbol, interval, limit)``: Binance rows [open_ms, open, high, low, close, volume, ...] (the newest last,
    the bar still forming included); ``now_ms()``: the clock. Errors are kept in ``errors`` (never raised by a fetch).
    Back-off: a failed fetch for a decision (an entry check, the supervisor) stops every fetch for ``RETRY_MS``
    (doubling); a failed fetch for the live site's picture (``bg``) stops only the picture's fetches, so it never costs a
    signal its one check (review 10/21)."""

    def __init__(self, fetch: Callable[[str, str, int], list], now_ms: Callable[[], int], keep: int = KEEP):
        self.fetch, self.now_ms, self.keep = fetch, now_ms, keep
        self.rows: dict[tuple, list] = {}
        self.wait_until = 0             # no fetch before this (ms) after a failed decision fetch
        self.fails = 0                  # decision fetches failed in a row
        self.bg_wait_until = 0          # no picture fetch before this (ms) after a failed picture fetch
        self.bg_fails = 0
        self.errors: list[str] = []

    def _load(self, symbol: str, tf: str, bg: bool = False) -> None:
        key, ms, asked = (symbol, tf), TF_MS[tf], self.now_ms()
        try:
            got = self.fetch(symbol, tf, FETCH)
        except Exception as exc:  # noqa: BLE001  every fetch waits; the judgment is "not readable" meanwhile
            now = self.now_ms()                       # after the failed request (its timeouts are not the wait)
            if bg:
                self.bg_fails += 1
                self.bg_wait_until = now + min(RETRY_MS * 2 ** (self.bg_fails - 1), RETRY_MAX_MS)
            else:
                self.fails += 1
                self.wait_until = now + min(RETRY_MS * 2 ** (self.fails - 1), RETRY_MAX_MS)
            self.errors.append(f"{symbol} {tf} 봉을 못 받음: {type(exc).__name__}: {exc}"[:300])
            return
        self.fails = self.bg_fails = 0
        self.wait_until = self.bg_wait_until = 0
        new = [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])) for r in got
               if int(r[0]) + ms + SETTLE_MS <= asked]      # settled when it was asked for
        merged = {r[0]: r for r in self.rows.get(key, [])}
        merged.update({r[0]: r for r in new})
        self.rows[key] = [merged[k] for k in sorted(merged)][-(FETCH + self.keep):]

    def frame(self, symbol: str, tf: str, t: int, bg: bool = False) -> pd.DataFrame:
        """The last ``keep`` bars closed at or before ``t`` (ms), the last one closing at the tf boundary at or
        before t. Raises TrendError when that bar is not readable (yet). ``bg``: for the live site's picture only."""
        ms = TF_MS[tf]
        need = int(t) - int(t) % ms - ms                 # the open of the bar that closes at the boundary <= t
        key = (symbol, tf)
        have = self.rows.get(key, [])
        now = self.now_ms()
        if (not have or have[-1][0] < need) and now >= self.wait_until and (not bg or now >= self.bg_wait_until):
            self._load(symbol, tf, bg)
            have = self.rows.get(key, [])
        rows = [r for r in have if r[0] <= need][-self.keep:]
        if not rows or rows[-1][0] != need:
            raise TrendError(f"{symbol} {KO_TF.get(tf, tf)} 끝난 봉을 아직 못 받음")
        if len(rows) < MIN_BARS:
            raise TrendError(f"{symbol} {KO_TF.get(tf, tf)} 봉이 {len(rows)}개뿐(최소 {MIN_BARS})")
        a = np.array(rows, dtype=float)
        return pd.DataFrame({"ts": pd.to_datetime(a[:, 0].astype(np.int64), unit="ms"), "open": a[:, 1],
                             "high": a[:, 2], "low": a[:, 3], "close": a[:, 4], "volume": a[:, 5]})


def lib():
    """The vendored indicator modules (fg_indicators, pine_indicators) the chart views use, after the hash check."""
    from . import sweepsig
    L = sweepsig.lib()
    return L.fg, L.pi


# ====================================================================== the judgment
@dataclass(frozen=True)
class Judgment:
    """The trend of one coin on one closed higher bar."""
    symbol: str
    tf: str
    bar_close: int                    # ms: the close of the bar judged
    votes: dict                       # {"V39": +1/-1/0, ...}
    raw: int                          # +1 / -1 by the vote of this bar, 0 = 보류
    dir: int                          # raw held on the last ``hold`` bars, else 0
    held: tuple                       # raw of the last ``hold`` bars, oldest first
    adx: float
    adx_prev: float
    close: float
    ema20: float
    atr: float

    @property
    def up(self) -> int:
        return sum(1 for v in self.votes.values() if v > 0)

    @property
    def down(self) -> int:
        return sum(1 for v in self.votes.values() if v < 0)

    def strength(self, side: int) -> int:
        """Judges on ``side`` (4 = all)."""
        return self.up if side > 0 else self.down

    def tired(self, rules: TrendRules) -> bool:
        return self.adx > rules.adx_tired and self.adx < self.adx_prev

    def vote_text(self) -> str:
        return f"상승 {self.up}·하락 {self.down}·중립 {4 - self.up - self.down}"

    def text(self, rules: TrendRules) -> str:
        """One line in the owners' words: 1시간 상승(상승 3·하락 1·중립 0, ADX 27 오름)."""
        word = KO_DIR[self.dir]
        if self.dir == 0 and self.raw != 0:
            word = f"보류({KO_DIR[self.raw]} 유지 확인 중)"
        trend = "오름" if self.adx > self.adx_prev else "내림"
        extra = ", 끝물" if self.tired(rules) else (", 힘 약함" if not self.adx >= rules.adx_min else "")
        return f"{KO_TF.get(self.tf, self.tf)} {word}({self.vote_text()}, ADX {self.adx:.0f} {trend}{extra})"

    def to_dict(self, rules: Optional[TrendRules] = None) -> dict:
        d = dataclasses.asdict(self)
        d["held"] = list(self.held)
        if rules is not None:
            d["text"] = self.text(rules)
            d["tired"] = self.tired(rules)
            d["strong"] = bool(self.adx >= rules.adx_min)
        return d


def _f(x) -> np.ndarray:
    return np.asarray(x.to_numpy(dtype=float) if isinstance(x, pd.Series) else x, dtype=float)


def _sign_pair(up: np.ndarray, down: np.ndarray) -> np.ndarray:
    return np.where(up, 1, np.where(down, -1, 0)).astype(np.int8)


def vote_arrays(df: pd.DataFrame, fg=None, pi=None) -> dict:
    """Per bar of ``df``: each judge's state (+1 / -1 / 0), ADX(14, 14), EMA20 and ATR(14)."""
    if fg is None or pi is None:
        fg, pi = lib()
    high, low, close, vol = _f(df["high"]), _f(df["low"]), _f(df["close"]), _f(df["volume"])
    with np.errstate(invalid="ignore"):
        _line, d3 = pi.exchange_supertrend(high, low, close, 10, 3.0)
        v39 = _sign_pair(np.asarray(d3) == 1, np.asarray(d3) == -1)
        e20 = _f(fg.ema(df["close"], 20))
        plus, minus, adx = (_f(x) for x in fg.dmi_adx(df, 14, 14))
        s6 = _sign_pair((close > e20) & (plus > minus), (close < e20) & (minus > plus))
        o = np.asarray(pi.obv(close, vol), dtype=float)
        ma = np.asarray(pi.pine_sma(o, 30), dtype=float)
        obv = _sign_pair(o > ma, o < ma)
        _t, _k, sa, sb = fg.ichimoku(df, 9, 26, 52, 26)
        sa, sb = _f(sa), _f(sb)
        top, bot = np.fmax(sa, sb), np.fmin(sa, sb)
        ao = _f(fg.awesome_oscillator(df, 5, 34))
        n12 = _sign_pair((close > top) & (ao > 0), (close < bot) & (ao < 0))
        atr = _f(fg.atr(df, 14))
    return {"V39": v39, "S6": s6, "OBV": obv, "N12": n12, "adx": adx, "ema20": e20, "atr": atr, "close": close,
            "span_a": sa, "span_b": sb, "ao": ao, "obv": o, "obv_ma": ma, "plus": plus, "minus": minus}


def raw_votes(arr: dict, vote_min: int) -> np.ndarray:
    m = np.vstack([arr[k] for k in JUDGES]).astype(int)
    up, down = (m > 0).sum(axis=0), (m < 0).sum(axis=0)
    return np.where(up >= vote_min, 1, np.where(down >= vote_min, -1, 0)).astype(np.int8)


def judge_frame(df: pd.DataFrame, symbol: str, tf: str, rules: TrendRules, fg=None, pi=None) -> Judgment:
    """The judgment on the last bar of ``df`` (closed bars only). Raises TrendError when a value is missing."""
    arr = vote_arrays(df, fg, pi)
    raw = raw_votes(arr, rules.vote_min)
    hold = rules.hold(tf)
    held = tuple(int(x) for x in raw[-hold:])
    adx, adx_prev = float(arr["adx"][-1]), float(arr["adx"][-2])
    close, ema20, atr = float(arr["close"][-1]), float(arr["ema20"][-1]), float(arr["atr"][-1])
    if not all(math.isfinite(v) for v in (adx, adx_prev, close, ema20, atr)) or not atr > 0:
        raise TrendError(f"{symbol} {KO_TF.get(tf, tf)} 지표 값이 비어 있음")
    r = int(raw[-1])
    d = r if (r != 0 and len(held) == hold and all(h == r for h in held)) else 0
    bar_close = int(df["ts"].iloc[-1].value // 1_000_000) + TF_MS[tf]
    return Judgment(symbol=symbol, tf=tf, bar_close=bar_close, votes={k: int(arr[k][-1]) for k in JUDGES}, raw=r,
                    dir=d, held=held, adx=adx, adx_prev=adx_prev, close=close, ema20=ema20, atr=atr)


@dataclass(frozen=True)
class Spot:
    """The entry bar (the signal's own timeframe, the bar that closed at the signal)."""
    tf: str
    bar_close: int
    close: float
    ema20: float
    atr: float
    rsi: float
    range: float                      # high - low of the signal bar


def spot_frame(df: pd.DataFrame, tf: str, fg=None) -> Spot:
    if fg is None:
        fg, _pi = lib()
    close = _f(df["close"])
    e20, atr, rsi = _f(fg.ema(df["close"], 20)), _f(fg.atr(df, 14)), _f(fg.rsi(df["close"], 14))
    v = (float(close[-1]), float(e20[-1]), float(atr[-1]), float(rsi[-1]),
         float(df["high"].iloc[-1]) - float(df["low"].iloc[-1]))
    if not all(math.isfinite(x) for x in v) or not v[2] > 0:
        raise TrendError(f"{KO_TF.get(tf, tf)} 진입 봉 지표 값이 비어 있음")
    return Spot(tf=tf, bar_close=int(df["ts"].iloc[-1].value // 1_000_000) + TF_MS[tf], close=v[0], ema20=v[1],
                atr=v[2], rsi=v[3], range=v[4])


class Judge:
    """Judgments and entry bars from ``Klines``, each computed once per (coin, timeframe, bar)."""

    def __init__(self, klines: Klines, rules: TrendRules):
        self.k, self.rules = klines, rules
        self._j: dict = {}
        self._s: dict = {}
        self._mods = None

    def mods(self):
        if self._mods is None:
            self._mods = lib()
        return self._mods

    def judgment(self, symbol: str, tf: str, t: int, bg: bool = False) -> Judgment:
        """The judgment of the last ``tf`` bar closed at or before t. Raises TrendError. ``bg``: for the live site's
        picture (its failed fetches never hold back a decision's)."""
        key = (symbol, tf, int(t) - int(t) % TF_MS[tf])
        got = self._j.get(key)
        if got is None:
            fg, pi = self.mods()
            got = judge_frame(self.k.frame(symbol, tf, t, bg), symbol, tf, self.rules, fg, pi)
            self._j[key] = got
            if len(self._j) > 400:
                for k in sorted(self._j, key=lambda x: x[2])[:200]:
                    self._j.pop(k, None)
        return got

    def spot(self, symbol: str, tf: str, t: int) -> Spot:
        key = (symbol, tf, int(t) - int(t) % TF_MS[tf])
        got = self._s.get(key)
        if got is None:
            fg, _pi = self.mods()
            got = spot_frame(self.k.frame(symbol, tf, t), tf, fg)
            self._s[key] = got
            if len(self._s) > 400:
                for k in sorted(self._s, key=lambda x: x[2])[:200]:
                    self._s.pop(k, None)
        return got


# ====================================================================== the entry checks
def check(rules: TrendRules, strategy: str, tf: str, side: int, price: float, j: Judgment, s: Spot) -> tuple[str, dict]:
    """('' , info) when the signal may wait for its pullback, else (why not in Korean, info). ``info``: the numbers
    read (kept with the signal) and, on a pass, ``depth`` (price distance) and ``level`` (the pullback price)."""
    hk, ek = KO_TF.get(j.tf, j.tf), KO_TF.get(tf, tf)
    word = "롱" if side > 0 else "숏"
    far_h = side * (price - j.ema20) / j.atr
    far_e = (price - s.ema20) / s.atr
    info = {"judge": j.to_dict(rules), "spot": dataclasses.asdict(s), "price": price, "far_htf_atr": far_h,
            "far_etf_atr": far_e}
    if j.dir == 0:
        return f"{hk} 추세 보류({j.vote_text()}" + (f", {KO_DIR[j.raw]} 유지 확인 중" if j.raw else "") + ")", info
    if j.dir != side:
        return f"{hk} 추세가 {KO_DIR[j.dir]}이라 {word} 안 함({j.vote_text()})", info
    if not j.adx >= rules.adx_min:
        return f"{hk} 추세 힘 약함(ADX {j.adx:.0f}, {rules.adx_min:g} 미만)", info
    if j.tired(rules):
        return f"{hk} 추세 끝물(ADX {j.adx:.0f}, {rules.adx_tired:g} 넘고 꺾임)", info
    if strategy in rules.breakout and not (j.adx < rules.breakout_adx_max and j.adx > j.adx_prev):
        return (f"돌파형은 추세 초입만(ADX {j.adx:.0f}" + (", 꺾임" if not j.adx > j.adx_prev else "")
                + f", 초입은 {rules.breakout_adx_max:g} 미만이고 오를 때)"), info
    if far_h > rules.htf_ema_atr:
        return f"{hk} EMA20에서 {far_h:.1f} ATR {'위' if side > 0 else '아래'}(너무 뻗음, {rules.htf_ema_atr:g} 넘음)", info
    if abs(far_e) > rules.etf_ema_atr:
        return (f"{ek} EMA20에서 {abs(far_e):.1f} ATR {'위' if far_e > 0 else '아래'}(진입 자리 아님, "
                f"{rules.etf_ema_atr:g} 안이어야 함)"), info
    if side > 0 and s.rsi >= rules.rsi_long_max:
        return f"{ek} RSI {s.rsi:.0f} 과열(롱은 {rules.rsi_long_max:g} 미만)", info
    if side < 0 and s.rsi <= rules.rsi_short_min:
        return f"{ek} RSI {s.rsi:.0f} 침체(숏은 {rules.rsi_short_min:g} 초과)", info
    big = s.range > rules.big_bar_atr * s.atr
    k = rules.pullback_big_atr if big else rules.pullback_atr
    info.update(big_bar=big, pullback_atr=k, depth=k * s.atr, level=price - side * k * s.atr)
    return "", info


def score(rules: TrendRules, side: int, j: Judgment, s: Spot, price: float, record: list) -> tuple[float, dict]:
    """The rank of a signal that passed (higher first; owners: "자리 + 판단 강도 + 그 매매법 최근 성적"):
    judge strength (4 of 4: 1, 3 of 4: 0) + spot (1 at the entry bar's EMA20 .. 0 at the ``etf_ema_atr`` edge)
    + record (the member's win rate over its last ``record_n`` trades minus one half; 0 below ``record_min`` trades).
    ``record``: those trades' net P&L, newest first."""
    strength = 1.0 if j.strength(side) >= 4 else 0.0
    spot = max(0.0, 1.0 - abs(price - s.ema20) / (rules.etf_ema_atr * s.atr))
    rec = [p for p in record[:rules.record_n]]
    form = (sum(1 for p in rec if p > 0) / len(rec) - 0.5) if len(rec) >= rules.record_min else 0.0
    return strength + spot + form, {"strength": strength, "spot": round(spot, 4), "record": round(form, 4),
                                    "record_n": len(rec)}
