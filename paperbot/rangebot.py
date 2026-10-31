"""레인지 봇 (owners 2026-10-26): the combined paper bot (paperbot/combo.py) with ``"range"`` in its config.

Owners: "그 구조로 가자" (analysis/f7tp10_1026/FINAL_KO.md, the research engine analysis/f7tp10_1026/hunt.py set-up F1),
then "1패후 24시간 휴식을 왜해 빼" (no pause after a loss). The member is the candidate league's custom pick of
F7_RF_TRIPLE 1h (레인지 필터 3중 일치, range filter 80 / 9.0, computed here at each 1h close as combo.CustomSignals does);
everything of the combined bot stays (one position, BTC 40x / others 30x, margin 40 % of the wallet, the -50 % net stop,
the weekend / macro / NYSE-open pauses at the minute of the entry, the coin-flip twin); the config's ``take_profit_roe``
(0.10) was the only take-profit until 10-29 (combo.FixedLevPolicy.take_profit: net ROE on the fill, no ladder); since
10-30 the config's ``ladder`` (net ROE 10 % -> lock 8 %, then every 5 %) and no ``take_profit_roe`` (item 6). This adds:

1. 한 신호씩: a signal is taken only while nothing else is going on: no pullback wait, no open position and no entry
   about to be filled in the bot's account. Else FILTERED "한 신호씩: …". Signals of one 1h close are looked at in the
   config's coin order (BTC, ETH, SOL, DOGE, LTC, BCH); the first that passes everything below is the one.
2. 추세 확인: the coin's 1h V3.9 supertrend (10, 3) and BTC's on the signal's side, both read on the 1h bar the signal
   closed (pine_indicators.exchange_supertrend on the same 1h chart frame as the signal, dssig.frame of the 5m history).
   Owners 10-29 ("친구 지표 1시간봉 + 레인지 필터 3중 일치 1시간봉으로 가자"): ``friend_tf`` "1h" reads the friend's trend
   indicator instead (paperbot/friendtrend.py: four votes, sky / purple line · EMA RSI · chop zone · supertrend average, on
   the same closed 1h bar of the signal's coin; two or more sideways, or two up and two down, is no entry), with
   ``coin_st`` and ``btc_st`` off (deploy/combo.range.json). Each check that is on must agree with the signal.
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
5. State ``range`` each live minute (the live site): the wait, each coin's last 1h supertrend side (``friend``: the
   friend's trend and votes instead), the rules.
6. Owners 10-30 ("b로 가자 레인지도 woox pro1 순수익8% 방식으로 가고 3번은 atr x3으로 가자"): ``roc_tf`` "30m" adds a second
   entry, the friend's OBV ROC pane on 30m bars (paperbot/friendtrend.py part 5, the same 5m history made into 30m bars,
   ROC_BARS of them): at each 30m close (live minutes only), a light -> dark green bar with the purple line under 50 is a
   long, a light -> dark red one over 50 a short, taken when the 30m four-vote trend is on its side (else FILTERED
   "추세 확인: 친구 추세지표 30분 …"); queued for the next minute's open, no pullback; its stop ATR(14, RMA) of that bar x
   ``roc_stop_atr`` (3; combo's research stop ["atr", k]) when that distance fits inside (1 / leverage - liq_mmr) of the
   price, else FILTERED "강제청산 여유 부족"; item 1 holds for both entries (one position). Its member ``ROC50-30m`` is the
   runner's own (roc_member), not in the config's ``members``. Both entries take the ladder.
7. Owners 10-31 ("너꺼 WOOX봇 바꾸자 … 레인지봇 매매법 싹 없애고"): ``members`` [] (no range filter member: items 1-4 and
   the pullback never happen) and ``ema3_tf`` "15m": '추세 3개 일치' (paperbot/friendtrend.py part 7) on 15m bars made from
   the same 5m history (kept without a custom member: hist_need, combo.CustomSignals keep_min): the three trends all one
   way and the EMA RSI histogram's light -> dark bar of that colour -> queued for the next minute's open, its stop ATR(14)
   of that bar x ``ema3_stop_atr`` (3) within the liquidation room, one position, the ladder. Member ``EMA3-15m``.
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
from . import friendtrend as FT
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
RULE_KEYS = ("pullback_atr", "wait_min", "coin_st", "btc_st", "st_period", "st_mult", "liq_check", "liq_mmr", "friend_tf",
             "roc_tf", "roc_stop_atr", "ema3_tf", "ema3_stop_atr")
FRIEND_TFS = ("1h",)
ROC_TFS = {"30m": 30 * MIN}            # the ROC entry's bar (owners 10-30)
EMA3_TFS = {"15m": 15 * MIN}           # 추세 3개 일치's bar (owners 10-31)
EXTRA_TFS = {**ROC_TFS, **EMA3_TFS}
ROC_NAME = "ROC50"                      # its strategy name in the records (signal_log, trades); combo.MEMBER_KO says it
EMA3_NAME = "EMA3"
ROC_BARS = 1500                         # bars an own entry reads (the 바이비트 봇's history per request, paperbot/mixchop.BARS)
TF_KO = {"15m": "15분", "30m": "30분", "1h": "1시간"}
# the runner's own entries (owners 10-30 / 10-31): kind -> (strategy name, its timeframe key, its stop key)
EXTRAS = {"roc": (ROC_NAME, "roc_tf", "roc_stop_atr"), "ema3": (EMA3_NAME, "ema3_tf", "ema3_stop_atr")}


FRIEND_WORDS = ("친구 추세지표 1시간봉(하늘·보라 선·EMA RSI·찹존·슈퍼트렌드)이 신호와 같은 방향일 때만: 같은 추세 2개 이상이면 "
                "그 추세, 횡보(찹존·슈퍼트렌드 노랑) 2개 이상이나 상승 2·하락 2면 진입 안 함")


ROC_WORDS = ("ROC 진입(30분봉): 친구 추세지표 30분봉(네 표)이 상승일 때 ROC 막대가 연한 초록→진한 초록이고 보라선이 50 아래면 롱, "
             "하락일 때 연한 빨강→진한 빨강이고 50 위면 숏 · 30분봉 마감 다음 분 시가에 시장가(되돌림 안 기다림) · "
             "손절 30분 ATR(14) × {k:g}, 그 거리가 (1/배수 - {mmr:.1%}) 안쪽일 때만 · 한 신호씩(레인지 신호와 합쳐 포지션 1개)")


EMA3_WORDS = ("추세 3개 일치(15분봉): EMA RSI · 하늘·보라 선 · 슈퍼트렌드(14·3 / 14·5) 셋이 모두 상승일 때 EMA RSI 막대가 "
              "연한 초록→진한 초록이면 롱, 셋이 모두 하락일 때 연한 빨강→진한 빨강이면 숏(하나라도 다르거나 횡보면 진입 안 함) · "
              "15분봉 마감 다음 분 시가에 시장가 · 손절 15분 ATR(14) × {k:g}, 그 거리가 (1/배수 - {mmr:.1%}) 안쪽일 때만 · 포지션 1개")
ONE_WORDS = "한 신호씩: 포지션 있는 동안 다른 신호 안 받음(같은 시각이면 BTC→ETH→SOL→DOGE→LTC→BCH 순서)"


def hist_need(range_cfg) -> int:
    """5m bars the runner's own entries read (combo's history keeps at least this many; 0 without them)."""
    try:
        tfs = RangeRules.from_dict(range_cfg).extras().values()
    except (RangeError, TypeError):
        return 0
    return max((ROC_BARS * EXTRA_TFS[tf] // FIVE + 12 for tf in tfs if tf in EXTRA_TFS), default=0)


OWN_KO = {"roc": "ROC 진입", "ema3": "추세 3개 일치"}


def own_stop_words(range_cfg) -> str:
    """The own entries' stops in words ("추세 3개 일치 15분 ATR(14) × 3"), '' without them."""
    try:
        r = RangeRules.from_dict(range_cfg)
    except (RangeError, TypeError):
        return ""
    return " / ".join(f"{OWN_KO[k]} {TF_KO.get(tf, tf)} ATR(14) × {float(getattr(r, EXTRAS[k][2])):g}"
                      for k, tf in r.extras().items())


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
    friend_tf: Optional[str] = None   # "1h": the friend's trend indicator on the signal's 1h bar (owners 10-29)
    roc_tf: Optional[str] = None      # "30m": the second entry, the OBV ROC turn on the 30m bar (owners 10-30)
    roc_stop_atr: float = 3.0         # its stop: ATR(14) of that 30m bar x this
    ema3_tf: Optional[str] = None     # "15m": '추세 3개 일치' on the 15m bar (owners 10-31, friendtrend part 7)
    ema3_stop_atr: float = 3.0        # its stop: ATR(14) of that 15m bar x this

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
        if self.friend_tf is not None and self.friend_tf not in FRIEND_TFS:
            out.append("range.friend_tf는 \"1h\"(친구 추세지표 1시간봉) 또는 null입니다")
        if self.roc_tf is not None and self.roc_tf not in ROC_TFS:
            out.append("range.roc_tf는 \"30m\"(ROC 30분봉 진입) 또는 null입니다")
        if not (num(self.roc_stop_atr) and 0.5 <= self.roc_stop_atr <= 10):
            out.append("range.roc_stop_atr는 0.5~10(ATR 배수)입니다(예: 3)")
        if self.ema3_tf is not None and self.ema3_tf not in EMA3_TFS:
            out.append("range.ema3_tf는 \"15m\"(추세 3개 일치 15분봉 진입) 또는 null입니다")
        if not (num(self.ema3_stop_atr) and 0.5 <= self.ema3_stop_atr <= 10):
            out.append("range.ema3_stop_atr는 0.5~10(ATR 배수)입니다(예: 3)")
        return out

    def extras(self) -> dict:
        """{kind: timeframe} of the runner's own entries that are on (ROC 30m, 추세 3개 일치 15m)."""
        return {k: getattr(self, tk) for k, (_n, tk, _sk) in EXTRAS.items() if getattr(self, tk)}

    def st_words(self) -> str:
        who = [w for w, on in (("코인", self.coin_st), ("BTC", self.btc_st)) if on]
        out = []
        if self.friend_tf:
            out.append(FRIEND_WORDS)
        if who:
            out.append(f"{'·'.join(who)} 1시간 슈퍼트렌드({self.st_period}, {self.st_mult:g})가 신호와 같은 방향일 때만")
        return " · ".join(out) or "슈퍼트렌드 확인 없음"

    def describe(self, range_on: bool = True) -> list[str]:
        """The rules in the owners' words (check-config, the start message, the live site); ``range_on``: the config has
        the range filter member (owners 10-31: none, its own entries only)."""
        if range_on:
            out = [f"추세 확인: {self.st_words()}",
                   f"되돌림 진입: 신호 1시간봉 종가에서 {self.pullback_atr:g} ATR(14, 1시간) 되돌림을 최대 {self.wait_min}분 기다림, "
                   "닿은 5분봉 다음 5분봉 시가에 시장가(안 오면 버림)",
                   "한 신호씩: 기다리는 동안·포지션 있는 동안 다른 신호 안 받음(같은 시각이면 BTC→ETH→SOL→DOGE→LTC→BCH 순서)"]
            if self.liq_check:
                out.append(f"강제청산 여유: 손절 거리 + 1시간 ATR이 (1/배수 - {self.liq_mmr:.1%}) 안쪽일 때만")
        else:
            out = [ONE_WORDS]
        if self.roc_tf:
            out.append(ROC_WORDS.format(k=self.roc_stop_atr, mmr=self.liq_mmr))
        if self.ema3_tf:
            out.append(EMA3_WORDS.format(k=self.ema3_stop_atr, mmr=self.liq_mmr))
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
    if not members and not rules.extras():
        out.append("레인지 봇 members가 비어 있습니다(그리고 roc_tf · ema3_tf 진입도 없음)")
    for i, m in enumerate(members, 1):
        if not isinstance(m, dict) or "pick" not in m:
            out.append(f"레인지 봇 members {i}번째: 후보 리그의 커스텀값 pick(예: ds-F7_RF_TRIPLE-1h-1)만 씁니다")
        elif "-1h-" not in str(m["pick"]):
            out.append(f"레인지 봇 members {i}번째({m['pick']}): 1시간봉 매매법만 됩니다")
        elif set(m) - {"pick"}:
            out.append(f"레인지 봇 members {i}번째({m['pick']}): pick 말고 다른 설정은 쓰지 않습니다")
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
    """The entry's range facts in words (the Telegram entry line): the pullback and the two supertrends; for the ROC
    entry its 30m bar, the purple line and the 30m trend."""
    try:
        side = int(r["side"])
        if r.get("ema3"):                            # owners 10-31: 추세 3개 일치
            colour = "초록" if side > 0 else "빨강"
            tfk = TF_KO.get(r.get("tf") or "15m", "15분")
            return (f"추세 3개 일치 {tfk}봉 {kst(r['t0'])} 마감: EMA RSI 막대 연한 {colour}→진한 {colour}"
                    + (f"(EMA RSI {float(r['ersi']):.1f})" if r.get("ersi") is not None else "")
                    + f" · 추세 {FT.ema3_words({'trend': r.get('e3_trend', side), 'votes': r.get('e3_votes') or {}})}"
                    + f" · 손절 {tfk} ATR({float(r['atr']):.6g}) × {float(r['k']):g}")
        if r.get("roc"):
            colour = "초록" if side > 0 else "빨강"
            osc = r.get("osc")
            return (f"ROC 30분봉 {kst(r['t0'])} 마감: 연한 {colour}→진한 {colour}, 보라선 "
                    + (f"{float(osc):.1f}({'50 아래' if side > 0 else '50 위'})" if osc is not None else "모름")
                    + f" · 손절 30분 ATR({float(r['atr']):.6g}) × {float(r['k']):g}"
                    + (f" · 친구 추세 30분 {FT.trend_words(r['friend'])}" if isinstance(r.get("friend"), dict) else ""))
        waited = max(0, int(r["entry_t"]) - int(r["t0"])) // MIN
        sts = " · ".join(f"{w} 슈퍼트렌드 {KO_ST.get(int(v), v)}" for w, v in (("코인", r.get("coin_st")),
                                                                               ("BTC", r.get("btc_st"))) if v is not None)
        if isinstance(r.get("friend"), dict):
            sts = " · ".join(x for x in (f"친구 추세 {FT.trend_words(r['friend'])}", sts) if x)
        return (f"신호 {kst(r['t0'])} 종가 {float(r['close']):.6g} → {float(r['k']):g} ATR({float(r['atr']):.6g}) "
                f"{'아래' if side > 0 else '위'} {float(r['level']):.6g}에 닿음, {waited}분 뒤 진입"
                + (f" · {sts}" if sts else ""))
    except (KeyError, TypeError, ValueError):
        return ""


def extra_member(rules: RangeRules, kind: str, order: int) -> Optional[C.Member]:
    """An own entry (``kind`` "roc" / "ema3") as a member of the account (its signals, counts and records), None when
    its timeframe is off."""
    name, tk, _sk = EXTRAS[kind]
    tf = getattr(rules, tk)
    if not tf:
        return None
    return C.Member(label=f"{name}-{tf}", kind=kind, name=name, tf=tf, numbers=None, order=order)


def roc_member(rules: RangeRules, order: int) -> Optional[C.Member]:
    """The ROC entry as a member of the account, None when ``roc_tf`` is off."""
    return extra_member(rules, "roc", order)


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
        self._ft: dict = {}                       # (symbol, bar close) -> the friend's trend and its votes
        self._snap: Optional[tuple] = None
        self.st_fails = 0
        if self.wait is not None and self.wait.get("member") not in self.by_label:
            self._restate(C._sig_from(self.wait["signal"]), "FILTERED", "설정이 바뀌어 기다리던 되돌림 신호를 버림",
                          expect=("WAITING",))
            self.wait = None
            self.store.commit()

    def _drop_old_members(self, st: dict) -> None:
        """ComboRunner's check of the saved queue against the config's members, with the ROC entry's member known
        first (it is not in the config's ``members``: ``range.roc_tf`` makes it)."""
        rules = RangeRules.from_dict(self.cfg.range)
        self.extra: dict = {}                     # kind -> the member of an own entry (ROC 30m, 추세 3개 일치 15m)
        for i, kind in enumerate(rules.extras()):
            m = extra_member(rules, kind, len(self.members) + 1 + i)
            self.extra[kind] = m
            self.by_label[m.label] = m
        self.roc = self.extra.get("roc")
        self._last: dict = {kind: {} for kind in self.extra}   # kind -> symbol -> its last read (the live site)
        self._roc_last: dict = self._last.get("roc", {})
        super()._drop_old_members(st)

    def _own_signals(self) -> bool:
        return bool(self.extra)

    def _state_extra(self) -> dict:
        return {"range_wait": getattr(self, "wait", None)}

    # ---- the 1h supertrend
    def supertrend(self, symbol: str, bar_close: int) -> int:
        """The side (+1 / -1) of the 1h supertrend on the 1h bar that closed at ``bar_close``, from the 5m history the
        custom signals use (5m bars that opened before ``bar_close``). Raises C.ComboError when it cannot be read."""
        key = (symbol, int(bar_close))
        if key in self._st:
            return self._st[key]
        df = self._frame(symbol, bar_close, "슈퍼트렌드")
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

    def _frame(self, symbol: str, bar_close: int, what: str, tf: str = "1h"):
        """The ``tf`` chart frame (dssig.frame) of the 5m history the custom signals use, its last bar closed at
        ``bar_close`` (1h: DS_WINDOW_5M of 5m bars; 30m: ROC_BARS bars). Raises C.ComboError when it cannot be made."""
        if self.custom is None or symbol not in self.custom.hist:
            raise C.ComboError(f"{coin(symbol)} 5분봉 기록 없음")
        per = (HOUR if tf == "1h" else EXTRA_TFS[tf]) // FIVE
        keep = DS_WINDOW_5M["1h"] if tf == "1h" else ROC_BARS * per
        rows = [r for r in self.custom.hist[symbol] if r[0] < int(bar_close)][-keep:]
        if len(rows) < ST_MIN_BARS * per:
            raise C.ComboError(f"{coin(symbol)} 5분봉 {len(rows)}개뿐({what}에 {ST_MIN_BARS * per}개 필요)")
        a = np.array(rows, dtype=float)
        from .dssig import frame
        df = frame(a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5], tf=tf, lib=self.custom.lib)
        if not len(df) or int(df["ts"].iloc[-1].value // 1_000_000) + per * FIVE != int(bar_close):
            raise C.ComboError(f"{coin(symbol)} {kst(bar_close)}에 닫힌 {TF_KO.get(tf, tf)}봉이 없음")
        return df

    # ---- the friend's trend indicator (owners 10-29)
    def friend_trend(self, symbol: str, bar_close: int) -> dict:
        """The friend's trend on the 1h bar that closed at ``bar_close`` (paperbot/friendtrend.py last_trend: trend +1 /
        -1 / 0 and the four votes), from the same 1h frame as the supertrend. Raises C.ComboError when unreadable."""
        key = (symbol, int(bar_close))
        if key in self._ft:
            return self._ft[key]
        df = self._frame(symbol, bar_close, "친구 추세지표")
        t = FT.last_trend(*(df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume")))
        if len(self._ft) > 50:
            self._ft = {k: v for k, v in self._ft.items() if k[1] >= int(bar_close)}
        self._ft[key] = t
        return t

    # ---- the ROC entry (owners 10-30)
    def roc_read(self, symbol: str, bar_close: int) -> dict:
        """The ROC entry's read on the 30m bar that closed at ``bar_close`` (the 바이비트 봇's indicator parts, on the
        same 5m history): {"roc": friendtrend.roc_state, "trend": friendtrend.last_trend, "atr": ATR(14) RMA, "close"}.
        Raises C.ComboError when it cannot be read."""
        from .mixchop import atr as atr_of
        df = self._frame(symbol, bar_close, "ROC", self.rules.roc_tf)
        o, h, l, c, v = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
        a = float(atr_of(h, l, c, 14)[-1])
        if not (np.isfinite(a) and a > 0 and np.isfinite(c[-1]) and c[-1] > 0):
            raise C.ComboError(f"{coin(symbol)} {kst(bar_close)} 30분 ATR·종가를 못 읽음")
        return {"roc": FT.roc_state(h, l, c, v), "trend": FT.last_trend(o, h, l, c, v), "atr": a, "close": float(c[-1])}

    def ema3_read(self, symbol: str, bar_close: int) -> dict:
        """'추세 3개 일치' on the 15m bar that closed at ``bar_close`` (friendtrend part 7 on the same 5m history):
        {"e3": friendtrend.ema3_state, "atr": ATR(14) RMA, "close"}. Raises C.ComboError when it cannot be read."""
        from .mixchop import atr as atr_of
        df = self._frame(symbol, bar_close, "추세 3개 일치", self.rules.ema3_tf)
        h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
        a = float(atr_of(h, l, c, 14)[-1])
        if not (np.isfinite(a) and a > 0 and np.isfinite(c[-1]) and c[-1] > 0):
            raise C.ComboError(f"{coin(symbol)} {kst(bar_close)} 15분 ATR·종가를 못 읽음")
        return {"e3": FT.ema3_state(h, l, c), "atr": a, "close": float(c[-1])}

    def _custom(self, boundary: int) -> None:
        super()._custom(boundary)
        for kind, m in self.extra.items():
            if boundary % EXTRA_TFS[m.tf] == 0:
                self._extra_signals(kind, boundary)

    def _roc_signals(self, boundary: int) -> None:
        self._extra_signals("roc", boundary)

    def _extra_signals(self, kind: str, boundary: int) -> None:
        """At a close of an own entry's bar (live only, as the custom signals): each coin's read. ROC (30m): a turn on
        its side of 50 with the 30m four-vote trend the same way is queued; against it or 진입 금지: FILTERED. 추세 3개
        일치 (15m): the light -> dark histogram bar with the three trends that way is queued. Queued = SUBMITTED, entered
        at the next minute's open, its stop ATR x the kind's stop multiple. One signal at a time and the liquidation
        room: _divert."""
        now = self.now_ms()
        if now - boundary > self.cfg.max_signal_age_s * 1000:
            return                                    # a catch-up: late anyway
        m = self.extra[kind]
        k = float(getattr(self.rules, EXTRAS[kind][2]))
        tfk = TF_KO.get(m.tf, m.tf)
        try:
            px = self.prices()
        except Exception:  # noqa: BLE001  without a price the fill is the next minute's open
            px = {}
        for sym in self.cfg.symbols:
            try:
                r = self.roc_read(sym, boundary) if kind == "roc" else self.ema3_read(sym, boundary)
            except Exception as exc:  # noqa: BLE001  unreadable: no entry, said so
                why = f"{type(exc).__name__}: {exc}" if not isinstance(exc, C.ComboError) else str(exc)
                self._last[kind][sym] = {"at": boundary, "error": why[:200]}
                self._st_failed(f"{coin(sym)} {kst(boundary)}: {why}", "ROC 30분 지표" if kind == "roc" else
                                f"추세 3개 일치 {tfk} 지표")
                continue
            base = {"side": 0, "close": r["close"], "atr": r["atr"], "k": k, "t0": int(boundary), "tf": m.tf}
            if kind == "roc":
                roc, t = r["roc"], r["trend"]
                self._last[kind][sym] = {"at": boundary, "turn": roc["turn"], "cs": roc["cs"], "dark": roc["dark"],
                                         "osc": roc["osc"], "side": roc["side"], "trend": t["trend"]}
                side, trend = int(roc["side"]), int(t["trend"])
                info = {"roc": True, **base, "side": side, "osc": roc["osc"], "turn": roc["turn"], "friend": dict(t)}
            else:
                e3 = r["e3"]
                self._last[kind][sym] = {"at": boundary, "turn": e3["turn"], "cs": e3["cs"], "dark": e3["dark"],
                                         "ersi": e3["ersi"], "side": e3["side"], "trend": e3["trend"], "votes": e3["votes"]}
                side, trend = int(e3["side"]), int(e3["trend"])
                info = {"ema3": True, **base, "side": side, "ersi": e3["ersi"], "turn": e3["turn"], "e3_trend": trend,
                        "e3_votes": dict(e3["votes"])}
            if not side:
                continue
            bid, ask = px.get(sym, (None, None))
            ref = ask if side > 0 else bid
            ready = self.now_ms()
            sig = C.make_signal(self.cfg, m, boundary, sym, side, r["atr"], ref, ready, ready - boundary,
                                {"close": r["close"]}, "custom")
            sig = replace(sig, meta={**sig.meta, "rstop": ["atr", k], "range": info,
                                     "ctx": {**(sig.meta.get("ctx") or {}), "range": info}})
            if trend != side:                         # (the ROC turn's four-vote trend; 추세 3개 일치's side has its own)
                tail = "" if trend == 0 else f"(신호 {KO_SIDE.get(side, side)}와 반대)"
                self._log(sig, "FILTERED", "custom", f"추세 확인: 친구 추세지표 {tfk} {FT.trend_words(r['trend'])}{tail}",
                          {"range": info})
                self._count(m.label, "filtered")
                continue
            self._queue(m, sig, boundary, "custom")

    def _st_failed(self, text: str, what: str = "슈퍼트렌드") -> None:
        self.st_fails += 1
        msg = f"{self.cfg.tag} {what}를 못 읽어 진입 안 함({self.st_fails}번째): {text}"[:300]
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
        info = sig.meta.get("range") or {}
        if info.get("roc") or info.get("ema3"):
            # an own entry: its trend was read at its close; its stop (ATR x k) must fit inside the liquidation room
            close, atr = float(info["close"]), float(sig.atr or 0.0)
            lev = self.cfg.lev_of(sig.symbol)
            dist, room = float(info["k"]) * atr, (1.0 / lev - float(r.liq_mmr)) * close
            if dist > room:
                tfk = TF_KO.get(info.get("tf") or sig.timeframe, sig.timeframe)
                self._filtered(sig, f"강제청산 여유 부족: 손절 {tfk} ATR × {float(info['k']):g} = {dist / close:.2%} > "
                                    f"{room / close:.2%}({lev}배)", {"range": info})
                return True
            return False
        sts: dict = {}
        if r.friend_tf:
            try:
                ft = self.friend_trend(sig.symbol, bar_close)
            except Exception as exc:  # noqa: BLE001  unreadable: no entry, said so
                why = f"{type(exc).__name__}: {exc}" if not isinstance(exc, C.ComboError) else str(exc)
                self._filtered(sig, f"친구 추세지표를 못 읽어 진입 안 함: {why}"[:200])
                self._st_failed(f"{coin(sig.symbol)} {kst(bar_close)}: {why}", "친구 추세지표")
                return True
            sts["friend"] = dict(ft)
            if int(ft["trend"]) != side:
                tail = "" if int(ft["trend"]) == 0 else f"(신호 {KO_SIDE.get(side, side)}와 반대)"
                self._filtered(sig, f"추세 확인: 친구 추세지표 1시간 {FT.trend_words(ft)}{tail}", {"range": sts})
                return True
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
        said = (f"친구 추세 {FT.trend_words(sts['friend'])}" if "friend" in sts else "") or (r.st_words() if sts else "")
        self._restate(sig, "WAITING", f"되돌림 기다림: {level:.6g}까지(종가 {close:.6g} {'-' if side > 0 else '+'} "
                                      f"{r.pullback_atr:g} ATR, {kst(until)}까지) · {said}".rstrip(" ·"),
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
        """State ``range``: the wait, each coin's supertrend (and/or the friend's trend, ``friend``) on the last closed 1h
        bar, the rules (live minutes only)."""
        now = self.now_ms()
        if now - int(ts) > 10 * MIN:
            return                                # a catch-up: only the live minute is shown
        h = int(ts) - int(ts) % HOUR
        sts: dict = {}
        fts: dict = {}
        if (int(ts) % HOUR == 0 or self._snap is None) and self.members:     # (owners 10-31: no range member, no 1h trend)
            for sym in self.cfg.symbols:
                if self.rules.coin_st or self.rules.btc_st or not self.rules.friend_tf:
                    try:
                        sts[sym] = self.supertrend(sym, h)
                    except Exception as exc:  # noqa: BLE001  shown as unreadable
                        sts[sym] = {"error": str(exc)[:200]}
                if self.rules.friend_tf:
                    try:
                        fts[sym] = dict(self.friend_trend(sym, h))
                    except Exception as exc:  # noqa: BLE001  shown as unreadable
                        fts[sym] = {"error": str(exc)[:200]}
        elif self._snap is not None:
            sts, fts = dict(self._snap[2]), dict(self._snap[3])
        w = self.wait
        wait = None
        if w is not None:
            s = w["signal"]
            wait = {"member": w["member"], "symbol": s["symbol"], "side": s["side"], "t0": w["t0"], "until": w["until"],
                    "level": w["level"], "hit": w.get("hit"), "info": w.get("info")}
        key = json.dumps([sts, fts, wait, getattr(self, "_last", None)], sort_keys=True, default=str)
        if self._snap is not None and self._snap[0] == key and int(ts) - self._snap[1] < SNAP_EVERY_MS:
            return
        self._snap = (key, int(ts), sts, fts)
        snap = {"ts": int(ts), "st_at": h, "supertrend": sts, "wait": wait, "busy": self._busy(),
                "rules": self.rules.describe(), "numbers": dataclasses.asdict(self.rules)}
        if self.rules.friend_tf:
            snap["friend"] = fts
        for kind in self.extra:
            snap[kind] = dict(self._last[kind])
        self.store.put_state(STATE_RANGE, int(ts), snap)
