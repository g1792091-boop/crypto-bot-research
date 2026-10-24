"""친구 매매법 (owners 2026-10-24 "실거래 해야된다니까", the structure of the live start: deploy/combo.friend.json,
docs/friend-bot-ko.md): the friend's EMA / RSI / ROC rules as a member of the combined bot (paperbot/combo.py member
``FRIEND_ROC``), two entry gates any combined bot may use (config ``adx_gate`` / ``quiet_gate``; off = null, the default)
and the loss review of its losing trades.

The signal (research/friendroc/code/frfamily.py ``tf_signals``), on CLOSED bars of the member's timeframe:
- long: EMA21 > EMA52, RSI26 > 50, ROC9 crosses 0 upward (the bar before <= 0, this bar > 0) and the higher-bar rule;
  short mirrored (EMA21 < EMA52, RSI26 < 50, crosses downward);
- the higher-bar rule, the member key ``higher`` (HIGHER_MODES): "roc_any" (the default) ROC9 > 0 on the last closed bar
  of either higher timeframe (frfamily.tf_signals); "rsi_roc_all" RSI26 > 50 and ROC9 > 0 on BOTH (research frand.py);
  "rsi_roc_1h" (the owners' first rule of 10-24 night, an option; 15m / 30m members) RSI26 > 50 and ROC9 > 0 on the last closed 1h bar only, the
  4h bar not read for it (research frhtrend.raw15 + frhtrend2.add_rsi); a short mirrored (< 50, < 0) in each;
- the higher timeframes (frfamily.TFS): 15m and 30m -> 1h | 4h, 1h -> 4h | 1d, 4h -> 1d | 3d, the 3d bars built from
  daily bars on the research's grid from 2020-01-01 00:00 UTC; a higher bar counts when its close <= the signal bar's;
- the repository's indicator library as the research calls it (paperbot.sweepsig.lib().fg): ema(c, 21), ema(c, 52),
  rsi(c, 26), roc(c, 9) on closes; at least 200 signal bars and 60 bars before the higher bar read (WARM15 / WARMH).
With it, for the messages: the volume ratio (the signal bar's volume over the mean of the 20 bars before it, frfamily
"vr") and ADX(14, 14) of the last closed 4h bar (fg.dmi_adx, as trendjudge.vote_arrays "adx": the code that wrote the
research's judge files, research/newlive/code/judge_all.py -> research/trendbot/fiveyear/code/judge5y.job).

The gates (paperbot/combo.py ``_entry_block``, after the KST weekend, the macro release and the NYSE open; a blocked
signal is recorded FILTERED with its reason and what the gate read):
- ``adx_gate`` {"tf": "4h", "min": 20}: no entry when ADX(14, 14) of the last closed ``tf`` bar at the signal bar's
  close is below ``min`` (research F4; an unknown ADX passes as in the research);
- ``quiet_gate`` {"bars": 20, "max_ratio": 0.64}: no entry when the signal bar's volume is above ``max_ratio`` x the
  mean of the ``bars`` bars before it (research V, VCUT; an unknown ratio passes as in the research).
A gate whose bars cannot be read blocks that entry and says why (never a guess).

Bars: Binance USDT-M klines (public), closed ones only (``SETTLE_MS`` after the close), oldest first, kept between bar
closes (each close fetches only the new bars). Enough of them that every value equals the research's full-history one:
1500 signal bars (EMA52 and RSI26 forget their start long before: (51/53) ** 1500 ~ 1e-25) and 1500 4h bars for the
ADX; research/friendroc/code/frlive_parity.py checks it on the research's own bars.

The loss review (owners: "손실이 나면 왜 손실이 났는지 알아보고 수정"): at each losing exit of a bot with this member,
one line in the paper's exit message and one row in its database (table ``loss_review``) with the values the research
looked at (frloss.coin_features / path_values): BTC's move with the trade's side from the entry to the exit, the best net
ROE before the exit, the hours held, the 4h ADX and the volume ratio of the signal bar, the 24 h range position of the
entry (research ``p24_side``: 1 = the chasing end) and the minutes from the nearest US macro release.
``python -m paperbot.combo status`` counts them.
"""

from __future__ import annotations

import math
import warnings
from typing import Optional

import numpy as np
import pandas as pd

from .entrygates import KO_GATE_TF, PAGE, RETRY_MAX_MS, RETRY_MS, SETTLE_MS, TF_GATE_MS, BarCache

FRIEND = "FRIEND_ROC"
FRIEND_KO = "친구 매매법(EMA·RSI·ROC)"
MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000
GRID_T0 = 1_577_836_800_000          # 2020-01-01 00:00 UTC: the research's bar grid (its 3d bars start here)
TF_MS = {**TF_GATE_MS, "3d": 3 * DAY}
KO_TF = {**KO_GATE_TF, "3d": "3일"}
HIGHER = {"15m": ("1h", "4h"), "30m": ("1h", "4h"), "1h": ("4h", "1d"), "4h": ("1d", "3d")}   # research frfamily.TFS
HIGHER_MODES = ("roc_any", "rsi_roc_all", "rsi_roc_1h")   # the member's ``higher`` (module docstring); the first = default
ONE_HIGHER = {"rsi_roc_1h": "1h"}    # modes that read one higher bar only: the timeframe it must be (15m / 30m members)
KO_HIGHER = {"roc_any": "ROC9이 같은 쪽", "rsi_roc_all": "RSI26·ROC9이 같은 쪽", "rsi_roc_1h": "RSI26·ROC9이 같은 쪽"}
WARM_SIGNAL, WARM_HIGHER = 200, 60   # research WARM15 / WARMH: bars before the one read
SIGNAL_BARS = 1500                   # closed signal bars read (one Binance page)
HIGHER_BARS = 1500                   # closed higher bars read (ROC9 needs 10; RSI26 forgets its start long before 1500)
HIGHER_BARS_3D = 600                 # 3d bars (1,800 daily bars, two pages): RSI26's start weighs (25/26) ** 600 ~ 6e-11
ADX_TF, ADX_BARS = "4h", 1500        # the 4h ADX(14, 14) of the messages; ADX forgets its start long before 1500 bars
VOL_BARS = 20                        # research "vr": the mean volume of the 20 bars before the signal bar
ADX_DEFAULT = {"tf": "4h", "min": 20}
QUIET_DEFAULT = {"bars": 20, "max_ratio": 0.64}
ADX_TFS = ("1h", "4h", "1d")
CHASE_END = 0.9                      # p24_side at or above this: "24시간 범위 끝에서 진입" (combo.chase_check's 90 %)


def lib():
    from . import sweepsig
    return sweepsig.lib()


def higher_words(tf: str, mode: Optional[str]) -> str:
    """The higher-bar rule in the owners' words: "상위 봉 1시간·4시간 중 하나라도 ROC9이 같은 쪽"."""
    names = "·".join(KO_TF[h] for h in HIGHER.get(tf, ()))
    if mode in ONE_HIGHER:
        return f"끝난 {KO_TF[ONE_HIGHER[mode]]}봉 {KO_HIGHER[mode]}(4시간봉은 안 봄)"
    if mode == "rsi_roc_all":
        return f"상위 봉 {names} 둘 다 {KO_HIGHER[mode]}"
    return f"상위 봉 {names} 중 하나라도 {KO_HIGHER['roc_any']}"


def last_open(tf: str, t: int) -> int:
    """The open (ms) of the last ``tf`` bar closed at or before ``t`` (3d bars on the research grid from 2020-01-01)."""
    ms = TF_MS[tf]
    a = GRID_T0 if tf == "3d" else 0
    return (int(t) - a) // ms * ms + a - ms


# ====================================================================== the signal (pure)
def _finite(x) -> Optional[float]:
    x = float(x)
    return x if math.isfinite(x) else None


def indicators(close, fg=None) -> dict:
    """EMA21, EMA52, RSI26 and ROC9 of ``close`` (oldest first) by the repository's library, as research
    frcore._ind."""
    fg = fg if fg is not None else lib().fg
    c = pd.Series(np.asarray(close, dtype=float))
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore")
        return {"e21": fg.ema(c, 21).to_numpy(float), "e52": fg.ema(c, 52).to_numpy(float),
                "rsi": fg.rsi(c, 26).to_numpy(float), "roc": fg.roc(c, 9).to_numpy(float)}


def friend_signal(close, higher, bar_close: int, fg=None, mode: str = "roc_any") -> tuple[int, dict]:
    """The side (+1 long, -1 short, 0 none) of the last bar of ``close`` (the signal bar, closing at ``bar_close``) by
    research frfamily.tf_signals, and the values read. ``close``: closes of the signal timeframe's closed bars, oldest
    first. ``higher``: (close_ms, close) array pairs of the higher timeframes, oldest first (two; one for a mode of
    ONE_HIGHER, only the first is read); only a bar closed at or before ``bar_close`` counts, the last such one is read
    (fewer than 60 bars before it: unknown). ``mode`` (HIGHER_MODES): "roc_any" ROC9 > 0 on either higher bar for a long
    (< 0 for a short); "rsi_roc_all" RSI26 > 50 and ROC9 > 0 on both higher bars for a long (RSI26 < 50 and ROC9 < 0 on
    both for a short); "rsi_roc_1h" the same on the first higher bar (1h) alone."""
    if mode not in HIGHER_MODES:
        raise ValueError(f"higher mode {mode!r}")
    fg = fg if fg is not None else lib().fg
    c = np.asarray(close, dtype=float)
    n = len(c)
    I = indicators(c, fg)
    e21, e52, rsi, roc = (float(I[k][-1]) if n else math.nan for k in ("e21", "e52", "rsi", "roc"))
    rocp = float(I["roc"][-2]) if n >= 2 else math.nan
    hr, hs, hinfo = [], [], []
    with_rsi = mode != "roc_any"
    for tc, hc in (list(higher)[:1] if mode in ONE_HIGHER else higher):
        tc = np.asarray(tc, dtype=np.int64)
        hc = np.asarray(hc, dtype=float)
        j = int(np.searchsorted(tc, int(bar_close), side="right")) - 1
        r = s = math.nan
        if j >= WARM_HIGHER:
            with warnings.catch_warnings(), np.errstate(all="ignore"):
                warnings.simplefilter("ignore")
                hser = pd.Series(hc[:j + 1])
                r = float(fg.roc(hser, 9).to_numpy(float)[-1])
                if with_rsi:
                    s = float(fg.rsi(hser, 26).to_numpy(float)[-1])
        hr.append(r)
        hs.append(s)
        hinfo.append({"close": int(tc[j]) if j >= 0 else None, "roc": _finite(r)}
                     | ({"rsi": _finite(s)} if with_rsi else {}))
    # NaN compares False everywhere, as the research's numpy masks
    up = e21 > e52 and rsi > 50 and rocp <= 0 and roc > 0
    dn = e21 < e52 and rsi < 50 and rocp >= 0 and roc < 0
    if mode == "roc_any":
        h_up, h_dn = hr[0] > 0 or hr[1] > 0, hr[0] < 0 or hr[1] < 0
    else:
        h_up = bool(hr) and all(s > 50 and r > 0 for s, r in zip(hs, hr))
        h_dn = bool(hr) and all(s < 50 and r < 0 for s, r in zip(hs, hr))
    warm = n - 1 >= WARM_SIGNAL
    side = 0
    if warm and up and h_up:
        side = 1
    elif warm and dn and h_dn:
        side = -1
    vals = {"bar_close": int(bar_close), "e21": _finite(e21), "e52": _finite(e52), "rsi": _finite(rsi),
            "roc": _finite(roc), "roc_prev": _finite(rocp), "higher": hinfo, "higher_mode": mode, "warm": bool(warm)}
    return side, vals


def volume_ratio(volume, bars: int = VOL_BARS) -> float:
    """The last bar's volume over the mean of the ``bars`` bars before it (research frfamily "vr": rolling mean shifted
    by one; NaN when fewer bars or a NaN among them, inf when they all traded nothing)."""
    v = np.asarray(volume, dtype=float)
    if len(v) < bars + 1:
        return math.nan
    with np.errstate(all="ignore"):
        return float(np.float64(v[-1]) / np.float64(np.mean(v[-bars - 1:-1])))


def adx_last(high, low, close, fg=None) -> float:
    """ADX(14, 14) of the last bar (fg.dmi_adx, the trend judge's and the research judge files' ADX)."""
    fg = fg if fg is not None else lib().fg
    df = pd.DataFrame({"high": np.asarray(high, float), "low": np.asarray(low, float),
                       "close": np.asarray(close, float)})
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore")
        _plus, _minus, adx = fg.dmi_adx(df, 14, 14)
    return float(np.asarray(adx, dtype=float)[-1]) if len(df) else math.nan


def atr_last(high, low, close, fg=None) -> float:
    fg = fg if fg is not None else lib().fg
    df = pd.DataFrame({"high": np.asarray(high, float), "low": np.asarray(low, float),
                       "close": np.asarray(close, float)})
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore")
        return float(fg.atr(df, 14).to_numpy(float)[-1]) if len(df) else math.nan


def three_day(day: np.ndarray) -> np.ndarray:
    """3d bars (open, o, h, l, c, v) from daily rows on the research grid from 2020-01-01 00:00 UTC; a 3d bar with
    fewer than its three days is left out."""
    if not len(day):
        return np.zeros((0, 6))
    g = (day[:, 0].astype(np.int64) - GRID_T0) // TF_MS["3d"]
    out = []
    for k in np.unique(g):
        rows = day[g == k]
        if len(rows) != 3:
            continue
        out.append([GRID_T0 + int(k) * TF_MS["3d"], rows[0, 1], rows[:, 2].max(), rows[:, 3].min(), rows[-1, 4],
                    rows[:, 5].sum()])
    return np.array(out, dtype=float) if out else np.zeros((0, 6))


# ====================================================================== bars
class KlineBars(BarCache):
    """entrygates.BarCache keeping the whole kline (open, o, h, l, c, v): ``fetch(symbol, interval, start_ms, limit)``
    Binance rows from ``start_ms``; closed bars only, the same back-off. ``closed`` reads the last bars closed at or
    before a time (3d from daily bars)."""

    def _load(self, symbol: str, tf: str, start: int, open_ms: int) -> None:
        ms, key = TF_GATE_MS[tf], (symbol, tf)
        got, t = [], int(start)
        try:
            while t <= open_ms:
                page = self.fetch(symbol, tf, t, PAGE)
                asked = self.now_ms()
                page = [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])) for r in page
                        if int(r[0]) + ms + SETTLE_MS <= asked]
                if not page:
                    break
                got += page
                t = page[-1][0] + ms
                if len(page) < PAGE:
                    break
        except Exception as exc:  # noqa: BLE001  the reader says "not readable" meanwhile
            self.fails += 1
            self.wait_until = self.now_ms() + min(RETRY_MS * 2 ** (self.fails - 1), RETRY_MAX_MS)
            self.errors = (self.errors + [f"{symbol} {tf} 봉을 못 받음: {type(exc).__name__}: {exc}"[:300]])[-20:]
            return
        self.fails, self.wait_until = 0, 0
        merged = {r[0]: r for r in self.rows.get(key, [])}
        merged.update({r[0]: r for r in got})
        self.rows[key] = [merged[k] for k in sorted(merged)][-3 * PAGE:]

    def closed(self, symbol: str, tf: str, t: int, need: int) -> Optional[np.ndarray]:
        """The last ``need`` (or fewer) ``tf`` bars closed at or before ``t``, ending with the last one: rows open, o, h,
        l, c, v. None when that bar cannot be read (yet)."""
        if tf == "3d":
            day = self.upto(symbol, "1d", last_open("1d", t), 3 * need + 3)
            if day is None:
                return None
            b = three_day(day)
            want = last_open("3d", t)
            b = b[b[:, 0] <= want] if len(b) else b
            if not len(b) or int(b[-1, 0]) != want:
                return None
            return b[-need:]
        return self.upto(symbol, tf, last_open(tf, t), need)


# ====================================================================== the member's signals
class FriendSignals:
    """The FRIEND_ROC members' signals at each close of their timeframe, from ``bars`` (KlineBars)."""

    def __init__(self, members: list, symbols, bars: KlineBars, fg=None):
        self.members = [m for m in members if m.kind == "friend"]
        self.symbols = list(symbols)
        self.bars = bars
        self._fg = fg
        self.errors: list[str] = []

    @property
    def fg(self):
        if self._fg is None:
            self._fg = lib().fg
        return self._fg

    def due(self, boundary: int) -> list:
        return [m for m in self.members if int(boundary) % TF_MS[m.tf] == 0]

    def read(self, tf: str, symbol: str, bar_close: int, mode: str = "roc_any") -> Optional[dict]:
        """The signal of the ``tf`` bar closing at ``bar_close`` (``mode``: the higher-bar rule, HIGHER_MODES):
        {"side", "atr", "values"}; None when a bar it needs cannot be read (yet)."""
        a = self.bars.closed(symbol, tf, bar_close, SIGNAL_BARS)
        if a is None or int(a[-1, 0]) + TF_MS[tf] != int(bar_close):
            return None
        hi = []
        higher = HIGHER[tf][:1] if mode in ONE_HIGHER else HIGHER[tf]
        for htf in higher:
            b = self.bars.closed(symbol, htf, bar_close, HIGHER_BARS_3D if htf == "3d" else HIGHER_BARS)
            if b is None:
                return None
            hi.append((b[:, 0].astype(np.int64) + TF_MS[htf], b[:, 4]))
        side, vals = friend_signal(a[:, 4], hi, bar_close, self.fg, mode)
        vals["tf"], vals["higher_tf"] = tf, list(higher)
        vals["vol_ratio"] = _finite(volume_ratio(a[:, 5]))          # None: unknown (the gate reads its own)
        out = {"side": side, "atr": math.nan, "values": vals}
        if side:
            out["atr"] = atr_last(a[:, 2], a[:, 3], a[:, 4], self.fg)
            b4 = self.bars.closed(symbol, ADX_TF, bar_close, ADX_BARS)
            vals["adx4h"] = None if b4 is None else _finite(adx_last(b4[:, 2], b4[:, 3], b4[:, 4], self.fg))
            vals["close"] = float(a[-1, 4])
        return out

    def compute(self, boundary: int, want: Optional[set] = None) -> tuple[list, set]:
        """([{member, symbol, side, atr, ctx}] of the members due at ``boundary`` that fire on the bar just closed,
        the (member label, symbol) pairs whose bars cannot be read yet). ``want``: only these pairs. A computation that
        fails is said in ``errors`` and not tried again."""
        got, left = [], set()
        for m in self.due(boundary):
            for sym in self.symbols:
                if want is not None and (m.label, sym) not in want:
                    continue
                try:
                    r = self.read(m.tf, sym, int(boundary), getattr(m, "higher", None) or "roc_any")
                except Exception as exc:  # noqa: BLE001  one coin of one member skipped, said
                    self.errors.append(f"{m.label} {sym}: {type(exc).__name__}: {exc}"[:300])
                    continue
                if r is None:
                    left.add((m.label, sym))
                    continue
                if r["side"] and math.isfinite(r["atr"]) and r["atr"] > 0:
                    got.append({"member": m, "symbol": sym, "side": int(r["side"]), "atr": float(r["atr"]),
                                "values": r["values"], "ctx": {"close": r["values"].get("close")}})
                elif r["side"]:
                    self.errors.append(f"{m.label} {sym}: no ATR at {boundary}")
        return got, left


# ====================================================================== the gates
def gate_problems(adx: Optional[dict], quiet: Optional[dict]) -> list[str]:
    """Config problems of ``adx_gate`` / ``quiet_gate`` (Korean, for combo.ComboConfig.problems)."""
    out = []
    if adx is not None:
        if not isinstance(adx, dict):
            out.append('adx_gate는 {"tf": "4h", "min": 20} 형식 또는 null입니다')
        else:
            bad = sorted(set(adx) - set(ADX_DEFAULT))
            if bad:
                out.append(f"adx_gate에 알 수 없는 이름: {', '.join(bad)}")
            if adx.get("tf", "4h") not in ADX_TFS:
                out.append(f"adx_gate.tf는 {', '.join(ADX_TFS)} 중 하나입니다")
            v = adx.get("min", 20)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v < 100:
                out.append("adx_gate.min은 0~100 사이 숫자입니다(ADX 20 미만 금지 = 20)")
    if quiet is not None:
        if not isinstance(quiet, dict):
            out.append('quiet_gate는 {"bars": 20, "max_ratio": 0.64} 형식 또는 null입니다')
        else:
            bad = sorted(set(quiet) - set(QUIET_DEFAULT))
            if bad:
                out.append(f"quiet_gate에 알 수 없는 이름: {', '.join(bad)}")
            n = quiet.get("bars", 20)
            if isinstance(n, bool) or not isinstance(n, int) or not 2 <= n <= 200:
                out.append("quiet_gate.bars는 2~200 정수입니다(평균을 내는 앞 봉 수)")
            r = quiet.get("max_ratio", 0.64)
            if isinstance(r, bool) or not isinstance(r, (int, float)) or not 0 < r <= 10:
                out.append("quiet_gate.max_ratio는 0~10 사이 배수입니다(평균의 0.64배 = 0.64)")
    return out


def adx_text(adx: dict) -> str:
    v = {**ADX_DEFAULT, **adx}
    return f"{KO_TF[v['tf']]} ADX(14)가 {float(v['min']):g} 미만이면 진입 안 함(추세 약함)"


def quiet_text(quiet: dict) -> str:
    v = {**QUIET_DEFAULT, **quiet}
    return f"신호 봉 거래량이 앞 {int(v['bars'])}봉 평균의 {float(v['max_ratio']):g}배보다 크면 진입 안 함(조용한 봉만)"


def adx_words(tf: str, adx: float) -> str:
    """"4시간 ADX 27"."""
    return f"{KO_TF[tf]} ADX {adx:.0f}" if math.isfinite(adx) else f"{KO_TF[tf]} ADX 모름"


def quiet_words(ratio: float, bars: int) -> str:
    """"거래량 0.41배(앞 20봉 평균 대비)"."""
    if math.isnan(ratio):
        return f"거래량 모름(앞 {bars}봉이 모자람)"
    if math.isinf(ratio):
        return f"거래량 계산 못 함(앞 {bars}봉 거래 없음)"
    return f"거래량 {ratio:.2f}배(앞 {bars}봉 평균 대비)"


class FriendGates:
    """``check(symbol, tf, side, bar_close)``: ('' or why the signal of the ``tf`` bar closing at ``bar_close`` takes
    no entry, what each gate read: {"adx": {...}, "quiet": {...}}), the interface of entrygates.EntryGates. ``bars``: a
    KlineBars (the FRIEND_ROC signals' own, so a signal's gates read the bars it was computed on)."""

    def __init__(self, adx: Optional[dict] = None, quiet: Optional[dict] = None, bars: Optional[KlineBars] = None,
                 fg=None):
        self.adx = None if adx is None else {**ADX_DEFAULT, **adx}
        self.quiet = None if quiet is None else {**QUIET_DEFAULT, **quiet}
        if (self.adx is not None or self.quiet is not None) and bars is None:
            raise ValueError("adx_gate / quiet_gate need bars")
        self.bars = bars
        self._fg = fg
        self._adx: dict = {}

    @property
    def fg(self):
        if self._fg is None:
            self._fg = lib().fg
        return self._fg

    def block(self, symbol: str, tf: str, side: int, bar_close: int) -> str:
        return self.check(symbol, tf, side, bar_close)[0]

    def check(self, symbol: str, tf: str, side: int, bar_close: int) -> tuple[str, dict]:
        info: dict = {}
        if self.adx is not None:
            why = self._adx_block(symbol, int(bar_close), info)
            if why:
                return why, info
        if self.quiet is not None:
            return self._quiet_block(symbol, tf, int(bar_close), info), info
        return "", info

    def _unread(self) -> str:
        return self.bars.errors[-1] if self.bars.errors else "끝난 봉을 아직 못 받음"

    def _adx_block(self, symbol: str, bar_close: int, info: dict) -> str:
        tf, lo = str(self.adx["tf"]), float(self.adx["min"])
        key = (symbol, tf, last_open(tf, bar_close))
        v = self._adx.get(key)
        if v is None:
            a = self.bars.closed(symbol, tf, bar_close, ADX_BARS)
            if a is None:
                return f"{KO_TF[tf]} ADX를 못 읽음(진입 안 함): {self._unread()}"[:200]
            v = adx_last(a[:, 2], a[:, 3], a[:, 4], self.fg)
            self._adx[key] = v
            if len(self._adx) > 400:
                for k in sorted(self._adx, key=lambda x: x[2])[:200]:
                    self._adx.pop(k, None)
        info["adx"] = {"tf": tf, "bar_close": key[2] + TF_MS[tf], "adx": _finite(v), "min": lo,
                       "text": adx_words(tf, v)}
        if v < lo:                                # NaN passes, as the research's ~(adx4h < 20)
            return f"{KO_TF[tf]} ADX 약함: {v:.1f} ({lo:g} 미만)"
        return ""

    def _quiet_block(self, symbol: str, tf: str, bar_close: int, info: dict) -> str:
        n, cut = int(self.quiet["bars"]), float(self.quiet["max_ratio"])
        a = self.bars.closed(symbol, tf, bar_close, n + 1)
        if a is None or int(a[-1, 0]) + TF_MS[tf] != bar_close:
            return f"거래량 판단에 쓸 {KO_TF.get(tf, tf)}봉을 못 읽음(진입 안 함): {self._unread()}"[:200]
        r = volume_ratio(a[:, 5], n)
        info["quiet"] = {"tf": tf, "ratio": _finite(r), "bars": n, "max_ratio": cut, "text": quiet_words(r, n)}
        if r > cut:                               # NaN passes, inf (nothing traded before) blocks: ~(vr > 0.64)
            return f"거래량 많음: 신호 봉 {r:.2f}배 (앞 {n}봉 평균의 {cut:g}배 넘음)"
        return ""


class GateChain:
    """Gate objects in order (entrygates.EntryGates, FriendGates): the first reason blocks; what each read is kept."""

    def __init__(self, *gates):
        self.gates = [g for g in gates if g is not None]

    def block(self, symbol: str, tf: str, side: int, bar_close: int) -> str:
        return self.check(symbol, tf, side, bar_close)[0]

    def check(self, symbol: str, tf: str, side: int, bar_close: int) -> tuple[str, dict]:
        info: dict = {}
        for g in self.gates:
            why, got = g.check(symbol, tf, side, bar_close)
            info.update(got)
            if why:
                return why, info
        return "", info


def make_friend(cfg, members: list, rest):
    """(FriendSignals or None, FriendGates or None) on Binance's public klines: their own client (5 s timeout, one
    retry), so a failing endpoint costs seconds, never the minute; one bar cache for both."""
    import time
    from .binance import BinanceREST, urllib_fetch
    own = BinanceREST(base_url=rest.base, fetch=lambda u, h: urllib_fetch(u, h, timeout=5.0), max_retries=1,
                      backoff=0.5)
    bars = KlineBars(lambda s, tf, t, n: own.klines(s, tf, start_time=t, limit=n), lambda: int(time.time() * 1000))
    sigs = FriendSignals(members, cfg.symbols, bars) if any(m.kind == "friend" for m in members) else None
    gates = FriendGates(cfg.adx_gate, cfg.quiet_gate, bars) \
        if cfg.adx_gate is not None or cfg.quiet_gate is not None else None
    return sigs, gates


# ====================================================================== words of an entry
def _px(x) -> str:
    return "?" if x is None else f"{float(x):.6g}"


def _pct(x) -> str:
    return "?" if x is None else f"{float(x):+.2f}"


def signal_words(vals: dict) -> str:
    """The signal bar's values in one line, to find the bar on TradingView: 15분봉 10/26 09:00~09:15 KST · EMA21 ... >
    EMA52 ... · RSI26 · ROC9 before -> now · the higher bars' ROC9 · the 4h ADX · the volume ratio."""
    import time as _t
    tf = str(vals.get("tf") or "15m")
    bc = int(vals.get("bar_close") or 0)
    kst = lambda ms: _t.strftime("%m/%d %H:%M", _t.gmtime(ms / 1000 + 9 * 3600))       # noqa: E731
    e21, e52 = vals.get("e21"), vals.get("e52")
    rel = ">" if (e21 is not None and e52 is not None and e21 > e52) else "<"
    parts = [f"{KO_TF.get(tf, tf)}봉 {kst(bc - TF_MS.get(tf, 0))}~{kst(bc)[6:]} KST",
             f"EMA21 {_px(e21)} {rel} EMA52 {_px(e52)}",
             "RSI26 " + ("?" if vals.get("rsi") is None else f"{vals['rsi']:.1f}"),
             f"ROC9 {_pct(vals.get('roc_prev'))} → {_pct(vals.get('roc'))}"]
    for htf, h in zip(vals.get("higher_tf") or [], vals.get("higher") or []):
        h = h or {}
        rsi = (f"RSI26 {h['rsi']:.1f}·" if h.get("rsi") is not None else "RSI26 ?·") if "rsi" in h else ""
        parts.append(f"{KO_TF.get(htf, htf)} {rsi}ROC9 {_pct(h.get('roc'))}")
    if vals.get("adx4h") is not None:
        parts.append(f"4시간 ADX {vals['adx4h']:.0f}")
    if vals.get("vol_ratio") is not None:
        parts.append(f"거래량 {vals['vol_ratio']:.2f}배")
    return " · ".join(parts)


# ====================================================================== the loss review
LOSS_TABLE = """CREATE TABLE IF NOT EXISTS loss_review (
    id INTEGER PRIMARY KEY,
    account_id TEXT NOT NULL,
    exit_time INTEGER NOT NULL,
    entry_time INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    side INTEGER NOT NULL,
    timeframe TEXT,
    strategy TEXT,
    exit_reason TEXT,
    roe REAL,
    btc_with_pct REAL,
    best_roe REAL,
    hours REAL,
    adx4h REAL,
    vol_ratio REAL,
    p24_side REAL,
    macro_min REAL,
    macro_kind TEXT,
    line TEXT,
    UNIQUE (account_id, entry_time, symbol)
)"""
CHASE_HOURS, CHASE_MIN_HOURS = 24, 20      # combo.chase_check's 24 h window (at least 20 of its hours read)


def entry_facts(hours: dict, bar_close: int, side: int, price: Optional[float], btc_open: Optional[float],
                ts: int, events=None) -> dict:
    """What the loss review needs from the entry minute ``ts``: the 24 h range position of the entry price over the 24
    hours before the signal bar's hour (research frloss p24 / p24_side; ``hours``: combo.chase_hours), BTC's open of
    the entry minute, the nearest US macro release (minutes from it, + = after it)."""
    k = int(bar_close) // HOUR
    v = [hours[j] for j in range(k - CHASE_HOURS, k) if j in hours]
    p24 = None
    if price and len(v) >= CHASE_MIN_HOURS:
        hi, lo = max(a for a, _ in v), min(b for _, b in v)
        if hi > lo:
            p24 = (float(price) - lo) / (hi - lo)
    if events is None:
        from . import events as EV
        events = EV.all_events()
    near = min(events, key=lambda e: abs(e.ts_ms - int(ts))) if events else None
    return {"price": None if price is None else float(price), "btc_open": None if btc_open is None else float(btc_open),
            "p24": p24, "p24_side": None if p24 is None else (p24 if side > 0 else 1 - p24),
            "macro_min": None if near is None else (int(ts) - near.ts_ms) / MIN,
            "macro_kind": None if near is None else near.kind}


def loss_facts(t, btc_close: Optional[float], round_trip: float) -> dict:
    """The loss review's values of a closed trade (a TradeRecord whose context has the signal's ``friend`` values and
    the ``entry`` facts): BTC's move with the side from the entry minute's open to the exit minute's close (research
    frloss.path_values btc_with), the best net ROE before the exit (ladder.net_roe at the best price: the ladder's own
    number), the hours held, the 4h ADX and the volume ratio of the signal bar, p24_side, the nearest macro release."""
    from .ladder import net_roe
    ctx = t.context if isinstance(t.context, dict) else {}
    ent, fr = ctx.get("entry") or {}, ctx.get("friend") or {}
    b0 = ent.get("btc_open")
    btc = t.side * (float(btc_close) / float(b0) - 1) if b0 and btc_close else None
    notional = t.qty * t.entry_price
    fund = t.funding / notional if notional else 0.0
    best = net_roe(t.side, t.entry_price, t.mfe_price, t.leverage, round_trip, fund) if t.mfe_price else None
    return {"btc_with_pct": None if btc is None else btc * 100, "best_roe": best,
            "hours": (int(t.exit_time) - int(t.entry_time)) / HOUR, "adx4h": fr.get("adx4h"),
            "vol_ratio": fr.get("vol_ratio"), "p24_side": ent.get("p24_side"), "macro_min": ent.get("macro_min"),
            "macro_kind": ent.get("macro_kind"), "exit_reason": t.exit_reason}


def _span(minutes: float) -> str:
    m = abs(minutes)
    return f"{m:.0f}분" if m < 120 else (f"{m / 60:.1f}시간" if m < 48 * 60 else f"{m / 1440:.1f}일")


def loss_line(f: dict) -> str:
    """"손실 이유 후보: BTC가 거래 동안 반대로 -1.2% · 손절 전 최고 +3% · 5.2시간 보유 · 4시간 ADX 27 · 거래량 0.41배 ·
    24시간 범위 끝에서 진입(0.93) · 고용보고서(NFP) 발표 3.2시간 뒤 진입" (a value not known is left out)."""
    from . import events as EV
    parts = []
    b = f.get("btc_with_pct")
    if b is not None:
        parts.append(f"BTC가 거래 동안 반대로 {b:+.1f}%" if b < 0 else f"BTC는 거래 방향으로 {b:+.1f}%")
    if f.get("best_roe") is not None:
        parts.append(f"{'손절' if f.get('exit_reason') == 'SL' else '청산'} 전 최고 {f['best_roe']:+.0%}")
    parts.append(f"{f['hours']:.1f}시간 보유")
    if f.get("adx4h") is not None:
        parts.append(f"4시간 ADX {f['adx4h']:.0f}")
    if f.get("vol_ratio") is not None:
        parts.append(f"거래량 {f['vol_ratio']:.2f}배")
    p = f.get("p24_side")
    if p is not None:
        parts.append(f"24시간 범위 끝에서 진입({p:.2f})" if p >= CHASE_END else f"24시간 범위 {p:.2f} 위치에서 진입")
    if f.get("macro_min") is not None:
        kind = EV.KIND_KO.get(f.get("macro_kind"), f.get("macro_kind"))
        parts.append(f"{kind} 발표 {_span(f['macro_min'])} {'뒤' if f['macro_min'] >= 0 else '전'} 진입")
    return "손실 이유 후보: " + " · ".join(parts)


def store_loss(conn, account: str, t, f: dict, line: str) -> None:
    """One row of ``loss_review`` in the bot's own database (the table is made here when missing); the same trade
    again (a replayed minute) replaces its row."""
    conn.execute(LOSS_TABLE)
    conn.execute(
        "INSERT OR REPLACE INTO loss_review (account_id, exit_time, entry_time, symbol, side, timeframe, strategy, "
        "exit_reason, roe, btc_with_pct, best_roe, hours, adx4h, vol_ratio, p24_side, macro_min, macro_kind, line) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (account, int(t.exit_time), int(t.entry_time), t.symbol, int(t.side), t.timeframe, t.strategy_id,
         t.exit_reason, float(t.roe), f.get("btc_with_pct"), f.get("best_roe"), f.get("hours"), f.get("adx4h"),
         f.get("vol_ratio"), f.get("p24_side"), f.get("macro_min"), f.get("macro_kind"), line))


def loss_status(conn, now_ms: int, days: int = 7) -> list[str]:
    """The weekly loss review in a few lines (combo status): the losses of the last ``days`` days, how many had each
    reason candidate, and the last ones' lines."""
    import time as _t
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'loss_review'").fetchone():
        return ["손실 리뷰: 아직 손실 거래 없음"]
    rows = conn.execute("SELECT exit_time, btc_with_pct, best_roe, hours, adx4h, vol_ratio, p24_side, macro_min, line "
                        "FROM loss_review WHERE exit_time >= ? ORDER BY exit_time", (int(now_ms) - days * DAY,)).fetchall()
    n_all = int(conn.execute("SELECT COUNT(*) FROM loss_review").fetchone()[0])
    if not rows:
        return [f"손실 리뷰(지난 {days}일): 손실 0번 (시작부터 {n_all}번)"]

    def cnt(f) -> int:
        return sum(1 for r in rows if f(r))
    hours = sorted(r[3] for r in rows if r[3] is not None)
    out = [f"손실 리뷰(지난 {days}일): 손실 {len(rows)}번 (시작부터 {n_all}번) · "
           f"BTC가 반대로 감 {cnt(lambda r: r[1] is not None and r[1] < 0)} · "
           f"손절 전 +10% 넘게 갔음 {cnt(lambda r: r[2] is not None and r[2] >= 0.10)} · "
           f"24시간 범위 끝에서 진입 {cnt(lambda r: r[6] is not None and r[6] >= CHASE_END)} · "
           f"4시간 ADX 25 미만 {cnt(lambda r: r[4] is not None and r[4] < 25)} · "
           f"경제 발표 3시간 안 {cnt(lambda r: r[7] is not None and abs(r[7]) <= 180)}"
           + (f" · 보유 가운데 {hours[len(hours) // 2]:.1f}시간" if hours else "")]
    for r in rows[-5:]:
        out.append(f"  {_t.strftime('%m-%d %H:%M', _t.gmtime(r[0] / 1000 + 9 * 3600))} KST {r[8]}")
    return out
