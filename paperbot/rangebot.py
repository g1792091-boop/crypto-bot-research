"""레인지 봇 (owners 2026-10-26): the combined paper bot (paperbot/combo.py) with ``"range"`` in its config.

Owners: "그 구조로 가자" (analysis/f7tp10_1026/FINAL_KO.md, the research engine analysis/f7tp10_1026/hunt.py set-up F1),
then "1패후 24시간 휴식을 왜해 빼" (no pause after a loss). The member is the candidate league's custom pick of
F7_RF_TRIPLE 1h (레인지 필터 3중 일치, range filter 80 / 9.0, computed here at each 1h close as combo.CustomSignals does);
everything of the combined bot stays (one position, BTC 40x / others 30x, margin 40 % of the wallet, the -50 % net stop,
the weekend / macro / NYSE-open pauses at the minute of the entry, the coin-flip twin); the config's ``take_profit_roe``
(0.10) is the only take-profit (combo.FixedLevPolicy.take_profit: net ROE on the fill, no ladder). This adds:

1. 한 신호씩: a signal is taken only while nothing else is going on: no pullback wait, no open position and no entry
   about to be filled in the bot's account. Else FILTERED "한 신호씩: …". Signals of one 1h close are looked at in the
   config's coin order (BTC, ETH, SOL, DOGE, LTC, BCH); the first that passes everything below is the one.
2. 추세 확인: the coin's 1h V3.9 supertrend (10, 3) and BTC's on the signal's side, both read on the 1h bar the signal
   closed (pine_indicators.exchange_supertrend on the same 1h chart frame as the signal, dssig.frame of the 5m history).
3. 강제청산 여유: the stop distance (net ROE -50 % at the coin's leverage) plus the signal bar's ATR(14) must fit inside
   (1 / leverage - 0.5 %) of the price (the research's check), else FILTERED (a very wild hour). This is the only ATR room:
   the config's ``liq_buffer_atr`` is 0, so the account's sizing keeps only its 0.2 % room between the stop and the
   liquidation price of the real brackets (with 1 ATR there too, a growing paper wallet reaches the brackets' higher
   maintenance rates on BCH / LTC, DOGE's first is 0.65 %, and 5 of the 38 research trades of 10/06 ~ 10/25 were refused
   after their pullback: analysis/f7tp10_1026/livepar.py).
4. 되돌림 진입: the signal waits ``wait_min`` (60) minutes for the price to come back ``pullback_atr`` (0.2) x ATR(14, 1h)
   from the signal bar's close (long: a low at or under close - 0.2 ATR; short: a high at or over close + 0.2 ATR),
   looked at on every 1m bar from the signal's close: WAITING "되돌림 기다림". The 5-minute bar that holds the first touch
   ends -> the entry is the next 5-minute open, at market (the reference price = the book then; the executor follows with
   a market order as always): BROKE "되돌림 확인" and a new SUBMITTED row. No touch in the hour: FILTERED "되돌림 안 옴".
   The entry minute is checked again for the weekend / macro / NYSE-open pauses (combo._entry_block).
5. State ``range`` each live minute (the live site): the wait, each coin's last 1h supertrend side, the rules.
No pause after a loss, no time exit, no reverse exit, no signal light (the owners' decisions of 10-26).
"""

from __future__ import annotations

import dataclasses
import json
import time
import warnings
from dataclasses import dataclass, replace
from typing import Optional

import numpy as np

from . import combo as C
from .config import DS_WINDOW_5M
from .models import Signal
from .notify import WARN

MIN = 60_000
FIVE = 300_000
HOUR = 3_600_000
KST_MS = 9 * HOUR
STATE_RANGE = "range"
SNAP_EVERY_MS = 5 * MIN
ST_MIN_BARS = 300                     # 1h bars the supertrend needs before it is read (its ATR settles long before)
KO_SIDE = {1: "롱", -1: "숏"}
KO_ST = {1: "상승", -1: "하락", 0: "없음"}
RULE_KEYS = ("pullback_atr", "wait_min", "coin_st", "btc_st", "st_period", "st_mult", "liq_check", "liq_mmr")


class RangeError(ValueError):
    """A bad ``range`` section (Korean)."""


def kst(ms: int) -> str:
    return time.strftime("%m-%d %H:%M", time.gmtime((int(ms) + KST_MS) / 1000))


def coin(symbol: str) -> str:
    return str(symbol).replace("USDT", "")


@dataclass(frozen=True)
class RangeRules:
    pullback_atr: float = 0.2         # the pullback from the signal bar's close, in ATR(14) of the 1h bar
    wait_min: int = 60                # how long a signal waits for it
    coin_st: bool = True              # the coin's 1h supertrend on the signal's side
    btc_st: bool = True               # BTC's 1h supertrend on the signal's side
    st_period: int = 10               # V3.9's supertrend
    st_mult: float = 3.0
    liq_check: bool = True            # stop distance + ATR inside (1 / leverage - liq_mmr) of the price
    liq_mmr: float = 0.005

    @classmethod
    def from_dict(cls, d) -> "RangeRules":
        if not isinstance(d, dict):
            raise RangeError("range는 {\"pullback_atr\": 0.2, \"wait_min\": 60, …} 모양입니다")
        unknown = sorted(set(d) - set(RULE_KEYS))
        if unknown:
            raise RangeError(f"range에 알 수 없는 이름: {', '.join(unknown)}")
        return cls(**d)

    def problems(self) -> list[str]:
        out = []
        num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)  # noqa: E731
        if not (num(self.pullback_atr) and 0 <= self.pullback_atr <= 3):
            out.append("range.pullback_atr는 0~3 ATR입니다(예: 0.2)")
        if not (isinstance(self.wait_min, int) and not isinstance(self.wait_min, bool) and 5 <= self.wait_min <= 240
                and self.wait_min % 5 == 0):
            out.append("range.wait_min은 5~240분, 5분 단위입니다(예: 60)")
        for k in ("coin_st", "btc_st", "liq_check"):
            if not isinstance(getattr(self, k), bool):
                out.append(f"range.{k}는 true 또는 false입니다")
        if not (isinstance(self.st_period, int) and not isinstance(self.st_period, bool) and 2 <= self.st_period <= 100):
            out.append("range.st_period는 2~100(정수)입니다(예: 10)")
        if not (num(self.st_mult) and 0.5 <= self.st_mult <= 10):
            out.append("range.st_mult는 0.5~10입니다(예: 3)")
        if not (num(self.liq_mmr) and 0 <= self.liq_mmr < 0.05):
            out.append("range.liq_mmr는 0~0.05입니다(예: 0.005)")
        return out

    def st_words(self) -> str:
        who = [w for w, on in (("코인", self.coin_st), ("BTC", self.btc_st)) if on]
        if not who:
            return "슈퍼트렌드 확인 없음"
        return f"{'·'.join(who)} 1시간 슈퍼트렌드({self.st_period}, {self.st_mult:g})가 신호와 같은 방향일 때만"

    def describe(self) -> list[str]:
        """The rules in the owners' words (check-config, the start message, the live site)."""
        out = [f"추세 확인: {self.st_words()}",
               f"되돌림 진입: 신호 1시간봉 종가에서 {self.pullback_atr:g} ATR(14, 1시간) 되돌림을 최대 {self.wait_min}분 기다림, "
               "닿은 5분봉 다음 5분봉 시가에 시장가(안 오면 버림)",
               "한 신호씩: 기다리는 동안·포지션 있는 동안 다른 신호 안 받음(같은 시각이면 BTC→ETH→SOL→DOGE→LTC→BCH 순서)"]
        if self.liq_check:
            out.append(f"강제청산 여유: 손절 거리 + 1시간 ATR이 (1/배수 - {self.liq_mmr:.1%}) 안쪽일 때만")
        out.append("진 뒤 쉬기·시간 청산·반대 신호 청산·신호등 없음")
        return out


def config_problems(cfg) -> list[str]:
    """The range section and what the 레인지 봇 needs of the rest of the config (Korean)."""
    try:
        rules = RangeRules.from_dict(cfg.range)
    except (RangeError, TypeError) as exc:
        return [str(exc)]
    out = rules.problems()
    members = [m for m in (cfg.members if isinstance(cfg.members, list) else [])]
    if not members:
        out.append("레인지 봇 members가 비어 있습니다")
    for i, m in enumerate(members, 1):
        if not isinstance(m, dict) or "pick" not in m:
            out.append(f"레인지 봇 members {i}번째: 후보 리그의 커스텀값 pick(예: ds-F7_RF_TRIPLE-1h-1)만 씁니다")
        elif "-1h-" not in str(m["pick"]):
            out.append(f"레인지 봇 members {i}번째({m['pick']}): 1시간봉 매매법만 됩니다")
        elif set(m) - {"pick"}:
            out.append(f"레인지 봇 members {i}번째({m['pick']}): pick 말고 다른 설정은 쓰지 않습니다")
    if cfg.take_profit_roe is None:
        out.append("레인지 봇은 take_profit_roe(고정 익절, 예: 0.1)가 필요합니다")
    if not cfg.stop_net:
        out.append('레인지 봇의 손절은 {"mode": "roe", "roe": 0.5, "net": true}(순ROE)입니다')
    if cfg.trend is not None:
        out.append("레인지 봇과 추세판단 봇(trend)은 같이 쓰지 않습니다")
    if cfg.early_exit is not None:
        out.append("레인지 봇은 early_exit(빠른 청산)를 쓰지 않습니다(null)")
    if cfg.max_hold_bars is not None:
        out.append("레인지 봇은 max_hold_bars(시간 청산)를 쓰지 않습니다(null)")
    if rules.liq_check and float(cfg.liq_buffer_atr) != 0.0:
        out.append("레인지 봇의 강제청산 여유는 range.liq_check 하나로 봅니다: liq_buffer_atr는 0입니다")
    if rules.btc_st and "BTCUSDT" not in tuple(cfg.symbols):
        out.append("range.btc_st(BTC 슈퍼트렌드)는 symbols에 BTCUSDT가 있어야 합니다")
    return out


def entry_words(r: dict) -> str:
    """The entry's range facts in words (the Telegram entry line): the pullback and the two supertrends."""
    try:
        side = int(r["side"])
        waited = max(0, int(r["entry_t"]) - int(r["t0"])) // MIN
        sts = " · ".join(f"{w} 슈퍼트렌드 {KO_ST.get(int(v), v)}" for w, v in (("코인", r.get("coin_st")),
                                                                               ("BTC", r.get("btc_st"))) if v is not None)
        return (f"신호 {kst(r['t0'])} 종가 {float(r['close']):.6g} → {float(r['k']):g} ATR({float(r['atr']):.6g}) "
                f"{'아래' if side > 0 else '위'} {float(r['level']):.6g}에 닿음, {waited}분 뒤 진입"
                + (f" · {sts}" if sts else ""))
    except (KeyError, TypeError, ValueError):
        return ""


# ====================================================================== the runner
class RangeRunner(C.ComboRunner):
    """ComboRunner with one signal at a time, the supertrend checks, the liquidation room and the pullback wait."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.rules = RangeRules.from_dict(self.cfg.range)
        st = self.store.get_state(C.STATE_KEY)
        st = st[1] if st else {}
        self.wait: Optional[dict] = st.get("range_wait")
        self._st: dict = {}                       # (symbol, bar close) -> supertrend side
        self._snap: Optional[tuple] = None
        self.st_fails = 0
        if self.wait is not None and self.wait.get("member") not in self.by_label:
            self._restate(C._sig_from(self.wait["signal"]), "FILTERED", "설정이 바뀌어 기다리던 되돌림 신호를 버림",
                          expect=("WAITING",))
            self.wait = None
            self.store.commit()

    def _state_extra(self) -> dict:
        return {"range_wait": getattr(self, "wait", None)}

    # ---- the 1h supertrend
    def supertrend(self, symbol: str, bar_close: int) -> int:
        """The side (+1 / -1) of the 1h supertrend on the 1h bar that closed at ``bar_close``, from the 5m history the
        custom signals use (5m bars that opened before ``bar_close``). Raises C.ComboError when it cannot be read."""
        key = (symbol, int(bar_close))
        if key in self._st:
            return self._st[key]
        if self.custom is None or symbol not in self.custom.hist:
            raise C.ComboError(f"{coin(symbol)} 5분봉 기록 없음")
        rows = [r for r in self.custom.hist[symbol] if r[0] < int(bar_close)][-DS_WINDOW_5M["1h"]:]
        if len(rows) < ST_MIN_BARS * 12:
            raise C.ComboError(f"{coin(symbol)} 5분봉 {len(rows)}개뿐(슈퍼트렌드에 {ST_MIN_BARS * 12}개 필요)")
        a = np.array(rows, dtype=float)
        from .dssig import frame
        df = frame(a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5], tf="1h", lib=self.custom.lib)
        if not len(df) or int(df["ts"].iloc[-1].value // 1_000_000) + HOUR != int(bar_close):
            raise C.ComboError(f"{coin(symbol)} {kst(bar_close)}에 닫힌 1시간봉이 없음")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _line, d = self.custom.lib.pi.exchange_supertrend(df["high"].to_numpy(float), df["low"].to_numpy(float),
                                                              df["close"].to_numpy(float), int(self.rules.st_period),
                                                              float(self.rules.st_mult))
        last = float(np.asarray(d, dtype=float)[-1])
        side = 1 if last == 1 else (-1 if last == -1 else 0)
        if len(self._st) > 50:
            self._st = {k: v for k, v in self._st.items() if k[1] >= int(bar_close)}
        self._st[key] = side
        return side

    def _st_failed(self, text: str) -> None:
        self.st_fails += 1
        msg = f"{self.cfg.tag} 슈퍼트렌드를 못 읽어 진입 안 함({self.st_fails}번째): {text}"[:300]
        self.store.alert(self.now_ms(), WARN, msg)
        if self.cfg.telegram and (self.st_fails in (1, 10, 100) or self.st_fails % 1000 == 0):
            self.notifier.send(WARN, msg)

    # ---- the signal
    def _busy(self) -> str:
        """'' or why the bot takes no new signal now (one signal at a time)."""
        if self.wait is not None:
            s = self.wait["signal"]
            return (f"한 신호씩: {coin(s['symbol'])} {KO_SIDE.get(int(s['side']), s['side'])} 되돌림 기다리는 중"
                    f"({kst(int(self.wait['until']))}까지)")
        e = self.book.engines.get(C.ACCOUNT)
        if e is not None and e.position is not None:
            p = e.position
            return f"한 신호씩: {coin(p.symbol)} {KO_SIDE.get(int(p.side), p.side)} 포지션 들고 있음"
        if e is not None and e.pending:
            g = e.pending[0]
            return f"한 신호씩: 이번 분에 {coin(g.symbol)} {KO_SIDE.get(int(g.side), g.side)} 진입이 먼저 들어감"
        return ""

    def _filtered(self, sig: Signal, why: str, extra: Optional[dict] = None) -> None:
        row = self.store.conn.execute(
            "SELECT data FROM signal_log WHERE bar_close = ? AND timeframe = ? AND strategy = ? AND symbol = ?",
            (sig.ts + 1, sig.timeframe, sig.meta.get("member", sig.strategy_id), sig.symbol)).fetchone()
        try:
            pulled = bool(row and json.loads(row[0] or "{}").get("pulled"))
        except ValueError:
            pulled = False
        if not pulled:                        # that row is a pulled entry's (same coin, same minute): left as it is
            self._restate(sig, "FILTERED", why, extra=extra)
        self._count(sig.meta.get("member", sig.strategy_id), "filtered")

    def _divert(self, sig: Signal, ts: int, bar_close: int, bars: dict) -> bool:
        if sig.meta.get("pulled"):
            return False                          # the entry after its pullback: submitted now
        busy = self._busy()
        if busy:
            self._filtered(sig, busy)
            return True
        r, side = self.rules, int(sig.side)
        sts: dict = {}
        try:
            if r.coin_st:
                sts["coin_st"] = self.supertrend(sig.symbol, bar_close)
            if r.btc_st:
                sts["btc_st"] = self.supertrend("BTCUSDT", bar_close)
        except Exception as exc:  # noqa: BLE001  unreadable: no entry, said so
            why = f"{type(exc).__name__}: {exc}" if not isinstance(exc, C.ComboError) else str(exc)
            self._filtered(sig, f"슈퍼트렌드를 못 읽어 진입 안 함: {why}"[:200])
            self._st_failed(f"{coin(sig.symbol)} {kst(bar_close)}: {why}")
            return True
        for k, who in (("coin_st", coin(sig.symbol)), ("btc_st", "BTC")):
            if k in sts and sts[k] != side:
                self._filtered(sig, f"추세 확인: {who} 1시간 슈퍼트렌드 {KO_ST.get(sts[k], sts[k])}"
                                    f"(신호 {KO_SIDE.get(side, side)}와 반대)", {"range": sts})
                return True
        close = float((sig.meta.get("ctx") or {}).get("close") or sig.meta.get("ref_price") or 0.0)
        atr = float(sig.atr or 0.0)
        if not (close > 0 and atr > 0):
            self._filtered(sig, "신호 봉 종가·ATR이 없어 진입 안 함")
            return True
        lev = self.cfg.lev_of(sig.symbol)
        rt = self.book.engines[C.ACCOUNT].s.round_trip_cost if C.ACCOUNT in self.book.engines else 0.0014
        dist = (float(self.cfg.stop["roe"]) / lev - rt) * close
        room = (1.0 / lev - float(r.liq_mmr)) * close
        if r.liq_check and dist + atr > room:
            self._filtered(sig, f"강제청산 여유 부족: 손절 거리 {dist / close:.2%} + 1시간 ATR {atr / close:.2%} > "
                                f"{room / close:.2%}({lev}배, 아주 거친 장)", {"range": sts})
            return True
        level = close - side * float(r.pullback_atr) * atr
        until = int(bar_close) + int(r.wait_min) * MIN
        info = {"side": side, "close": close, "atr": atr, "k": float(r.pullback_atr), "level": level, "t0": int(bar_close),
                "until": until, **sts}
        self.wait = {"member": sig.meta.get("member", sig.strategy_id), "t0": int(bar_close), "until": until,
                     "level": level, "hit": None, "info": info, "signal": dataclasses.asdict(sig)}
        self._restate(sig, "WAITING", f"되돌림 기다림: {level:.6g}까지(종가 {close:.6g} {'-' if side > 0 else '+'} "
                                      f"{r.pullback_atr:g} ATR, {kst(until)}까지) · {r.st_words() if sts else ''}".rstrip(" ·"),
                      extra={"range": info})
        self._count(self.wait["member"], "waiting")
        return True

    # ---- the wait
    def _after_step(self, ts: int, bars: dict) -> None:
        self._watch(ts, bars)
        self._snapshot(ts)

    def _watch(self, ts: int, bars: dict) -> None:
        """Minute ts traded at the waiting signal's level -> the entry is the open of the next 5-minute bar (queued);
        no touch by the end of the wait -> dropped. Minutes from the signal's close (its 1m bar opens there, after the
        signal bar's close) to the wait's last minute."""
        w = self.wait
        if w is None:
            return
        sig = C._sig_from(w["signal"])
        if w.get("member") not in self.by_label:
            self._restate(sig, "FILTERED", "설정이 바뀌어 기다리던 되돌림 신호를 버림", expect=("WAITING",))
            self.wait = None
            return
        bar = bars.get(sig.symbol)
        lvl = float(w["level"])
        if w.get("hit") is None and bar is not None and int(w["t0"]) <= ts < int(w["until"]):
            if bar.low <= lvl if sig.side > 0 else bar.high >= lvl:
                w["hit"] = int(ts)
        if w.get("hit") is None:
            if ts + MIN >= int(w["until"]):
                self._restate(sig, "FILTERED", f"되돌림 안 옴({kst(int(w['until']))}까지 {lvl:.6g}에 안 닿음)",
                              expect=("WAITING",))
                self._count(w["member"], "no_pullback")
                self.wait = None
            return
        hit = int(w["hit"])
        if ts + MIN < hit - hit % FIVE + FIVE:
            return                                # the 5-minute bar of the touch has not ended yet
        self.wait = None
        entry_t = ts + MIN
        now = self.now_ms()
        if now - entry_t > self.cfg.max_signal_age_s * 1000:
            self._restate(sig, "FILTERED", "되돌림 확인이 늦음(재시작 따라잡기)", expect=("WAITING",))
            return
        try:
            px = self.prices()
        except Exception:  # noqa: BLE001  without a price the fill is the entry minute's open
            px = {}
        bid, ask = px.get(sig.symbol, (None, None))
        ref = ask if sig.side > 0 else bid
        info = {**w["info"], "touch": hit, "entry_t": entry_t}
        ctx = {**(sig.meta.get("ctx") or {}), "range": info}
        meta = {**sig.meta, "pulled": True, "ref_time": now, "delay_ms": now - entry_t, "pull_level": lvl,
                "pull_minute": hit, "range": info, "ctx": ctx}
        meta.pop("ref_price", None)
        if ref is not None:
            meta["ref_price"] = float(ref)
        nsig = replace(sig, ts=entry_t - 1, meta=meta)
        self.queue.append(C.Queued(entry_t, dataclasses.asdict(nsig)))
        self._restate(sig, "BROKE", f"되돌림 확인: {kst(hit)}에 {lvl:.6g} 닿음 → {kst(entry_t)} 5분봉 시가에 진입",
                      expect=("WAITING",))
        self._log(nsig, "SUBMITTED", "custom", "되돌림 확인", extra={"pulled": True, "range": info})

    # ---- what the live site shows
    def _snapshot(self, ts: int) -> None:
        """State ``range``: the wait, each coin's supertrend on the last closed 1h bar, the rules (live minutes only)."""
        now = self.now_ms()
        if now - int(ts) > 10 * MIN:
            return                                # a catch-up: only the live minute is shown
        h = int(ts) - int(ts) % HOUR
        sts: dict = {}
        if int(ts) % HOUR == 0 or self._snap is None:
            for sym in self.cfg.symbols:
                try:
                    sts[sym] = self.supertrend(sym, h)
                except Exception as exc:  # noqa: BLE001  shown as unreadable
                    sts[sym] = {"error": str(exc)[:200]}
        else:
            sts = dict(self._snap[2])
        w = self.wait
        wait = None
        if w is not None:
            s = w["signal"]
            wait = {"member": w["member"], "symbol": s["symbol"], "side": s["side"], "t0": w["t0"], "until": w["until"],
                    "level": w["level"], "hit": w.get("hit"), "info": w.get("info")}
        key = json.dumps([sts, wait], sort_keys=True, default=str)
        if self._snap is not None and self._snap[0] == key and int(ts) - self._snap[1] < SNAP_EVERY_MS:
            return
        self._snap = (key, int(ts), sts)
        self.store.put_state(STATE_RANGE, int(ts), {"ts": int(ts), "st_at": h, "supertrend": sts, "wait": wait,
                                                     "busy": self._busy(), "rules": self.rules.describe(),
                                                     "numbers": dataclasses.asdict(self.rules)})
