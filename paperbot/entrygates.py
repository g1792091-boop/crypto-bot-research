"""Entry gates of the 'VWAP 개선판' bot (owners 2026-10-23 "실거래봇을 돌려야 한다니까"; research/vwap30/PREREG_FWD1.md
candidate A). Both are optional in any combined bot (paperbot/combo.py config ``vote_gate`` / ``vol_gate``; off = null,
the default) and only ever take an entry away:

- ``vote_gate`` {"tf": "4h", "vote_min": 3}: no entry when the trend bot's four judges (paperbot/trendjudge.py: V3.9,
  EMA·DMI·ADX, OBV, 일목·AO) on the last CLOSED ``tf`` bar at the signal bar's close vote against the side
  (``vote_min`` of the four the other way). The same vote with the trade or 보류 passes; no ADX, hold or 끝물 rule here.
  Research: vwfix2.rows_tf ``j4h`` (research/newlive judge files, ``4h_raw3``).
- ``vol_gate`` {"atr": 14, "days": 30, "q": 0.8}: no entry when the signal bar's ATR% (Wilder ATR(14) of the signal's
  own timeframe / its close) is above the ``q`` quantile of the same ATR% over the last ``days`` days of bars up to and
  including the signal bar (linear interpolation; at least half of them, else it passes as in the research).
  Research: vwbuild.features ``atrp`` / ``atrp_q80``.

Bars: Binance USDT-M klines (public), closed ones only (``SETTLE_MS`` after the close), oldest first; the same answer
for the same signal on a replay. A gate whose bars cannot be read blocks that entry and says why (never a guess).
"""

from __future__ import annotations

import math
from typing import Callable, Optional

import numpy as np
import pandas as pd

from .trendjudge import KO_TF, TF_MS, Judge, Klines, TrendError, TrendRules

TF_GATE_MS = {"15m": 900_000, **TF_MS}
VOTE_TFS = ("1h", "4h", "1d")
VOL_TFS = ("15m", "30m", "1h", "4h")
KO_GATE_TF = {"15m": "15분", **KO_TF}
SETTLE_MS = 3_000
PAGE = 1500                  # Binance klines rows per request (the most it gives)
WARM = 300                   # bars before the window: the Wilder ATR forgets its start long before (13/14 ** 300)
RETRY_MS = 20_000            # after a failed fetch no fetch for this long (doubling to RETRY_MAX_MS while it fails)
RETRY_MAX_MS = 120_000
VOTE_DEFAULT = {"tf": "4h", "vote_min": 3}
VOL_DEFAULT = {"atr": 14, "days": 30, "q": 0.8}


def gate_problems(vote: Optional[dict], vol: Optional[dict], member_tfs) -> list[str]:
    """Config problems of ``vote_gate`` / ``vol_gate`` (Korean, for combo.ComboConfig.problems)."""
    out = []
    if vote is not None:
        if not isinstance(vote, dict):
            out.append('vote_gate는 {"tf": "4h", "vote_min": 3} 형식 또는 null입니다')
        else:
            bad = sorted(set(vote) - set(VOTE_DEFAULT))
            if bad:
                out.append(f"vote_gate에 알 수 없는 이름: {', '.join(bad)}")
            if vote.get("tf", "4h") not in VOTE_TFS:
                out.append(f"vote_gate.tf는 {', '.join(VOTE_TFS)} 중 하나입니다")
            vm = vote.get("vote_min", 3)
            if isinstance(vm, bool) or not isinstance(vm, int) or not 2 <= vm <= 4:
                out.append("vote_gate.vote_min은 2~4 정수입니다(4개 판단 중 몇 개)")
    if vol is not None:
        if not isinstance(vol, dict):
            out.append('vol_gate는 {"atr": 14, "days": 30, "q": 0.8} 형식 또는 null입니다')
        else:
            bad = sorted(set(vol) - set(VOL_DEFAULT))
            if bad:
                out.append(f"vol_gate에 알 수 없는 이름: {', '.join(bad)}")
            n = vol.get("atr", 14)
            if isinstance(n, bool) or not isinstance(n, int) or not 2 <= n <= 100:
                out.append("vol_gate.atr는 2~100 정수입니다(ATR 기간)")
            d = vol.get("days", 30)
            if isinstance(d, bool) or not isinstance(d, int) or not 5 <= d <= 30:
                out.append("vol_gate.days는 5~30 정수입니다(바이낸스 한 번에 1500봉: 30분봉 30일)")
            q = vol.get("q", 0.8)
            if isinstance(q, bool) or not isinstance(q, (int, float)) or not 0.5 <= q < 1:
                out.append("vol_gate.q는 0.5~1 사이 비율입니다(상위 20% 금지 = 0.8)")
            bad_tf = sorted({tf for tf in member_tfs if tf not in VOL_TFS})
            if bad_tf:
                out.append(f"vol_gate: {', '.join(bad_tf)} 매매법은 안 됩니다({', '.join(VOL_TFS)}만)")
            elif not bad and isinstance(d, int) and not isinstance(d, bool):
                for tf in sorted(set(member_tfs)):
                    if window_bars(tf, d) + WARM > 2 * PAGE:
                        out.append(f"vol_gate: {KO_GATE_TF[tf]}봉 {d}일은 너무 깁니다(봉 {window_bars(tf, d)}개)")
    return out


def vote_text(vote: dict) -> str:
    v = {**VOTE_DEFAULT, **vote}
    return f"{KO_GATE_TF[v['tf']]} 추세 판단이 반대면 진입 안 함(4개 중 {v['vote_min']}개 반대; 보류는 진입)"


def vol_text(vol: dict) -> str:
    v = {**VOL_DEFAULT, **vol}
    return (f"변동성(ATR{v['atr']}%)이 지난 {v['days']}일의 {float(v['q']):.0%} 위치보다 크면 진입 안 함"
            f"(상위 {1 - float(v['q']):.0%} 금지)")


def vote_words(tf: str, raw: int, up: int, down: int) -> str:
    """"4시간 상승(상승 3·하락 0·중립 1)" — the 4h judgment in the owners' words."""
    word = {1: "상승", -1: "하락"}.get(int(raw), "보류")
    return f"{KO_GATE_TF[tf]} {word}(상승 {up}·하락 {down}·중립 {4 - up - down})"


def vol_words(tf: str, atrp: float, qv: float, v: dict) -> str:
    """"변동성 30분 ATR 0.45% (30일 80% 위치 0.62%)"."""
    q = f"{qv:.2%}" if math.isfinite(qv) else "아직 모름"
    return f"변동성 {KO_GATE_TF[tf]} ATR {atrp:.2%} ({int(v['days'])}일 {float(v['q']):.0%} 위치 {q})"


def window_bars(tf: str, days: int) -> int:
    """Bars of ``days`` days on ``tf`` (research vwbuild.features: int(30 * 1440 / k))."""
    return int(days * 1440 * 60_000 / TF_GATE_MS[tf])


def wilder_atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int) -> np.ndarray:
    """research/vwap30/code/vwcommon.atr_adx's ATR: true range (the first bar's previous close = its own close),
    Wilder's average from the first bar (ewm alpha 1/n, adjust=False)."""
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().to_numpy()


def atr_pct_and_q(h, l, c, n: int, win: int, q: float) -> tuple[float, float]:
    """(ATR% of the last bar, the ``q`` quantile of ATR% over the last ``win`` bars incl. it; nan when fewer than
    win // 2 are known: research pandas rolling(win, min_periods=win // 2).quantile(q))."""
    atrp = wilder_atr(h, l, c, n) / c
    w = atrp[-win:]
    w = w[np.isfinite(w)]
    qv = float(np.quantile(w, q)) if len(w) >= max(win // 2, 1) else math.nan
    return float(atrp[-1]), qv


class BarCache:
    """Closed klines per (coin, timeframe), oldest first. ``fetch(symbol, interval, start_ms, limit)``: Binance rows
    [open_ms, open, high, low, close, volume, ...] from ``start_ms`` (the bar still forming may be in them)."""

    def __init__(self, fetch: Callable[[str, str, int, int], list], now_ms: Callable[[], int]):
        self.fetch, self.now_ms = fetch, now_ms
        self.rows: dict[tuple, list] = {}
        self.wait_until = 0
        self.fails = 0
        self.errors: list[str] = []

    def upto(self, symbol: str, tf: str, open_ms: int, need: int) -> Optional[np.ndarray]:
        """The last ``need`` (or fewer) bars ending with the bar that opened at ``open_ms``: array [open, h, l, c];
        None when that bar cannot be read (yet)."""
        ms, key = TF_GATE_MS[tf], (symbol, tf)
        have = self.rows.get(key, [])
        first = int(open_ms) - (need - 1) * ms
        if (not have or have[-1][0] < open_ms or have[0][0] > first) and self.now_ms() >= self.wait_until:
            start = first if (not have or have[0][0] > first) else have[-1][0] + ms
            self._load(symbol, tf, start, open_ms)
            have = self.rows.get(key, [])
        rows = [r for r in have if r[0] <= open_ms][-need:]
        if not rows or rows[-1][0] != open_ms:
            return None
        return np.array(rows, dtype=float)

    def _load(self, symbol: str, tf: str, start: int, open_ms: int) -> None:
        ms, key = TF_GATE_MS[tf], (symbol, tf)
        got, t = [], int(start)
        try:
            while t <= open_ms:
                page = self.fetch(symbol, tf, t, PAGE)
                asked = self.now_ms()
                page = [(int(r[0]), float(r[2]), float(r[3]), float(r[4])) for r in page
                        if int(r[0]) + ms + SETTLE_MS <= asked]
                if not page:
                    break
                got += page
                t = page[-1][0] + ms
                if len(page) < PAGE:
                    break
        except Exception as exc:  # noqa: BLE001  the gate says "not readable" and blocks the entry meanwhile
            self.fails += 1
            self.wait_until = self.now_ms() + min(RETRY_MS * 2 ** (self.fails - 1), RETRY_MAX_MS)
            self.errors = (self.errors + [f"{symbol} {tf} 봉을 못 받음: {type(exc).__name__}: {exc}"[:300]])[-20:]
            return
        self.fails, self.wait_until = 0, 0
        merged = {r[0]: r for r in self.rows.get(key, [])}
        merged.update({r[0]: r for r in got})
        self.rows[key] = [merged[k] for k in sorted(merged)][-3 * PAGE:]


class EntryGates:
    """``check(symbol, tf, side, bar_close)``: ('' or why the signal of the ``tf`` bar closing at ``bar_close`` (ms) takes
    no entry, what each gate read: {"vote": {...}, "vol": {...}} for the records, the messages and the live site);
    ``block``: the reason alone. ``judge``: a trendjudge.Judge for ``vote``; ``bars``: a BarCache for ``vol``."""

    def __init__(self, vote: Optional[dict] = None, vol: Optional[dict] = None, judge: Optional[Judge] = None,
                 bars: Optional[BarCache] = None):
        self.vote = None if vote is None else {**VOTE_DEFAULT, **vote}
        self.vol = None if vol is None else {**VOL_DEFAULT, **vol}
        if self.vote is not None and judge is None:
            raise ValueError("vote_gate needs a judge")
        if self.vol is not None and bars is None:
            raise ValueError("vol_gate needs bars")
        self.judge, self.bars = judge, bars
        self._vol: dict = {}

    def block(self, symbol: str, tf: str, side: int, bar_close: int) -> str:
        return self.check(symbol, tf, side, bar_close)[0]

    def check(self, symbol: str, tf: str, side: int, bar_close: int) -> tuple[str, dict]:
        info: dict = {}
        if self.vote is not None:
            why = self._vote_block(symbol, int(side), int(bar_close), info)
            if why:
                return why, info
        if self.vol is not None:
            return self._vol_block(symbol, tf, int(bar_close), info), info
        return "", info

    def _vote_block(self, symbol: str, side: int, bar_close: int, info: Optional[dict] = None) -> str:
        tf = self.vote["tf"]
        try:
            j = self.judge.judgment(symbol, tf, bar_close)
        except TrendError as exc:
            return f"{KO_GATE_TF[tf]} 추세 판단을 못 읽음(진입 안 함): {exc}"[:200]
        if info is not None:
            info["vote"] = {"tf": tf, "bar_close": j.bar_close, "votes": dict(j.votes), "up": j.up, "down": j.down,
                            "raw": j.raw, "with_side": j.raw * side, "text": vote_words(tf, j.raw, j.up, j.down)}
        if j.raw == -side:
            return f"{KO_GATE_TF[tf]} 추세 반대: {j.vote_text()}"
        return ""

    def _vol_block(self, symbol: str, tf: str, bar_close: int, info: Optional[dict] = None) -> str:
        v = self.vol
        key = (symbol, tf, bar_close)
        got = self._vol.get(key)
        if got is None:
            win = window_bars(tf, int(v["days"]))
            arr = self.bars.upto(symbol, tf, bar_close - TF_GATE_MS[tf], win + WARM)
            if arr is None:
                last = self.bars.errors[-1] if self.bars.errors else "끝난 봉을 아직 못 받음"
                return f"변동성 판단에 쓸 {KO_GATE_TF[tf]}봉을 못 읽음(진입 안 함): {last}"[:200]
            got = atr_pct_and_q(arr[:, 1], arr[:, 2], arr[:, 3], int(v["atr"]), win, float(v["q"]))
            self._vol[key] = got
            if len(self._vol) > 400:
                for k in sorted(self._vol, key=lambda x: x[2])[:200]:
                    self._vol.pop(k, None)
        atrp, qv = got
        if info is not None:
            info["vol"] = {"tf": tf, "atr_pct": round(atrp * 100, 4),
                           "q_pct": round(qv * 100, 4) if math.isfinite(qv) else None,
                           "days": int(v["days"]), "q": float(v["q"]), "text": vol_words(tf, atrp, qv, v)}
        if math.isfinite(qv) and atrp > qv:
            return (f"변동성 높음: ATR {atrp:.3%} > 지난 {int(v['days'])}일 {float(v['q']):.0%} 위치 {qv:.3%}")
        return ""


def picture(gates: EntryGates, symbols, tfs, at_ms: int) -> dict:
    """What the gates read for every coin at ``at_ms`` (ms, a minute's open): the vote on the last closed ``vote.tf``
    bar and the ATR% against its quantile on the last closed bar of each timeframe in ``tfs``. For the live site's
    'VWAP 개선판' screen (state ``gates_now``): which side a signal could take now, and why not. A part that cannot
    be read says so ({"error": ...}); nothing here blocks or allows an entry (EntryGates.check does that per signal).
    Use a gates object of its own (make_gates once more): its caches and back-off never touch the entry checks."""
    coins: dict = {}
    for sym in symbols:
        row: dict = {}
        if gates.vote is not None:
            info: dict = {}
            why = gates._vote_block(sym, 1, int(at_ms), info)
            row["vote"] = info.get("vote") or {"tf": gates.vote["tf"], "error": why or "읽지 못함"}
        if gates.vol is not None:
            row["vol"] = {}
            for tf in tfs:
                close = int(at_ms) - int(at_ms) % TF_GATE_MS[tf]
                info = {}
                why = gates._vol_block(sym, tf, close, info)
                v = info.get("vol")
                row["vol"][tf] = {**v, "bar_close": close, "high": bool(why)} if v else \
                    {"tf": tf, "bar_close": close, "error": why or "읽지 못함"}
        coins[sym] = row
    return {"at": int(at_ms), "coins": coins, "vote": gates.vote, "vol": gates.vol, "tfs": list(tfs)}


def make_gates(vote: Optional[dict], vol: Optional[dict], rest) -> Optional[EntryGates]:
    """The gates on Binance's public klines: their own client (5 s timeout, one retry), so a failing endpoint costs
    seconds, never the minute. None when both are off."""
    if vote is None and vol is None:
        return None
    import time
    from .binance import BinanceREST, urllib_fetch
    own = BinanceREST(base_url=rest.base, fetch=lambda u, h: urllib_fetch(u, h, timeout=5.0), max_retries=1,
                      backoff=0.5)
    clock = lambda: int(time.time() * 1000)            # noqa: E731
    judge = bars = None
    if vote is not None:
        v = {**VOTE_DEFAULT, **vote}
        judge = Judge(Klines(lambda s, tf, n: own.klines(s, tf, limit=n), clock),
                      TrendRules(vote_min=int(v["vote_min"])))
    if vol is not None:
        bars = BarCache(lambda s, tf, t, n: own.klines(s, tf, start_time=t, limit=n), clock)
    return EntryGates(vote, vol, judge, bars)
