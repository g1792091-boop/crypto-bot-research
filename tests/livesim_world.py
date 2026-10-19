"""A small live world for 못 탄 신호 성적 (tests/test_livesim.py, tests/test_livemissed.py, tests/test_dash_livebots_missed.py and the
offline screenshots): the combined paper bot (paperbot/combo.py) REALLY runs over it, minute by minute, with its own
``ComboRunner``, ``AccountBook`` and ``ComboEngine``, so every trade, every ENTERED / SKIPPED / REJECTED outcome and every
FILTERED / WAITING signal_log row in its database is the bot's own record, never written by hand.

- the rule bot's paper3.db: 1m bars (``live_bars`` through store3's own writer, mark fields = last price) of the six coins,
  each a piecewise-linear price path (``PATHS``), and ``signal_log`` rows (status SUBMITTED) of two default members
  (V39_ALL 15m = order 1, OBV_S 15m = order 2) at their bar closes, the way the rule bot writes them;
- the paper bot's live-ac.db: ``combo.build_book`` + ``ComboRunner.poll`` once per minute (the clock 65 s after the minute
  opened, so no signal is late unless the script says so), its ``combo_run`` record as cmd_run writes it; the leverage
  brackets and coin specs of the repository's saved Binance table (research/fullgrid/exchange.json: what
  paperbot/livesim.py uses);
- the live config's rules (BTC 40x / others 30x, margin 40 %, stop 3 ATR pulled in to fit, loss cap 35 %, ladder: lock
  10 % at 11 %, then 3 % steps, rank by list order);
- funding (``funding=True``): one BTC rate (0.01 %) paid at T0 + 20 min, through the runner's funding feed.

The script (T0 = 2026-10-19 00:00 UTC = Monday 09:00 KST; B1 = T0 + 15 min):
  B1      V39_ALL BTC long (entered: 40x)  +  OBV_S ETH short (same minute, order 2: SKIPPED "lower score than entered signal")
  B1+15m  OBV_S SOL long while BTC is open: SKIPPED "in position" (held BTC)
          BTC climbs to +0.67 % by B1+25m (best net ROE ~20 %: lock 19 %), falls back: exit LOCK
          SOL climbs to +0.67 % by B1+75m, falls to -0.67 % by B1+135m: its virtual trade locks and exits LOCK (~+13 %)
          ETH climbs 1.6 % by B1+60m: the ETH short's virtual trade is stopped (SL)
  B1+60m  V39_ALL ETH long (entered: 30x), ETH falls to 2,480 by B1+90m: SL
  B1+120m a BCH long with a research stop (rstop ["pct", 1.0]) submitted to the engine directly (entered), a DOGE long of
          a later setting in the same minute (SKIPPED "lower score"); BCH climbs and locks, DOGE stays flat

``research=True`` adds five research settings (``RMEMBERS``, config order 3-7, labels as combo.resolve_members makes them),
the runner's research data (``RM.RData`` on these same prices: 1m / 1h / 4h klines, no funding, flat open interest), a US
macro release at R0 (``MACRO_CSV``, the caller points paperbot.events at it) and, from R0 = T0 + 4 h (13:00 KST, the
account flat), signals that the bot's OWN code keeps out (each through ``ComboRunner._research_signal`` / ``_queue``,
``_submit_due``, ``_research_entry``, ``_breaks``):
  R0       V39_ALL ETH long (rule)            -> FILTERED "경제 발표 앞뒤 30분: …" (macro pause)
  R0       N03_ADX_GC BTC long (filter weekend=1) -> FILTERED "연구 조건 밖: weekend=1"
  R0+45m   N08_ICHI_WR SOL long (disp range 50 ATR) -> FILTERED "연구 조건 밖: 신호봉 크기"
  R0+60m   S2_ST_ROC LTC long (swing 2, off hr=14)  -> FILTERED "끈 구간: hr=14" (14:00 KST)
  R0+75m   F4_FAN DOGE short (entry break, pct 1) -> WAITING, DOGE flat: FILTERED "돌파 없음(신호봉 시간 안에)"
  R0+105m  OBV_S SOL short (rule) whose reference price is 200 s old -> REJECTED "late"
  R0+120m  F12_MSS_DISP BCH long (swing 2) -> ENTERED (swing stop from the bot's own 1m window), locks, exits LOCK
  after: BTC up, ETH down, SOL down, LTC up then down, DOGE down, BCH up then down (each virtual trade closes by END_R).
"""
from __future__ import annotations

import dataclasses
import os
from typing import Optional

from paperbot import combo as C
from paperbot import livereplay as LR
from paperbot import rmember as RM
from paperbot.models import Signal
from paperbot.notify import ListNotifier
from paperbot.store3 import Store3

MIN = 60_000
H = 3_600_000
DAY = 86_400_000
T0 = 1_792_368_000_000                     # 2026-10-19 00:00 UTC (09:00 KST, Monday)
B1 = T0 + 15 * MIN
SYMS = C.V3_SYMBOLS
BASE = {"BTCUSDT": 60000.0, "ETHUSDT": 2500.0, "SOLUSDT": 150.0, "DOGEUSDT": 0.2, "LTCUSDT": 80.0, "BCHUSDT": 400.0}
# price knots (ms, price): linear in between, flat before the first and after the last
PATHS = {
    "BTCUSDT": [(T0, 60000.0), (B1, 60000.0), (B1 + 25 * MIN, 60400.0), (B1 + 45 * MIN, 59800.0)],
    "ETHUSDT": [(T0, 2500.0), (B1, 2500.0), (B1 + 60 * MIN, 2540.0), (B1 + 90 * MIN, 2480.0)],
    "SOLUSDT": [(T0, 150.0), (B1 + 15 * MIN, 150.0), (B1 + 75 * MIN, 151.0), (B1 + 135 * MIN, 149.0)],
    "DOGEUSDT": [(T0, 0.2)],
    "LTCUSDT": [(T0, 80.0)],
    "BCHUSDT": [(T0, 400.0), (B1 + 120 * MIN, 400.0), (B1 + 150 * MIN, 403.0), (B1 + 170 * MIN, 398.0)],
}
ATR_FRAC = 0.002
MEMBERS = [{"strategy": "V39_ALL", "tf": "15m"}, {"strategy": "OBV_S", "tf": "15m"}]
CONFIG = {"name": "시험 합본", "initial_equity": 1000.0, "leverage": {"BTCUSDT": 40, "default": 30}, "margin": 0.4,
          "max_loss_frac": 0.35, "loss_cap": "shrink", "stop": {"mode": "atr_fit", "atr": 3.0, "min_atr": 1.0},
          "ladder": {"first_lock": 0.1, "step": 0.03, "trigger_gap": 0.01}, "rank": ["order"], "flip_twin": True,
          "members": MEMBERS, "telegram": False}
# (bar close, strategy, coin, side[, reference price age in s]) logged by the rule bot
SIGNALS = [(B1, "V39_ALL", "BTCUSDT", 1), (B1, "OBV_S", "ETHUSDT", -1), (B1 + 15 * MIN, "OBV_S", "SOLUSDT", 1),
           (B1 + 60 * MIN, "V39_ALL", "ETHUSDT", 1)]
# research-stop signals submitted to the paper engine directly at their minute (the runner's research path needs Binance)
DIRECT_T = B1 + 120 * MIN
FUNDING = {B1 + 5 * MIN: {"BTCUSDT": 0.0001}}
END = B1 + 200 * MIN                       # every trade and virtual trade of the script is closed by then

# ---------------------------------------------------------------- research mode
R0 = T0 + 4 * H                            # 13:00 KST: the macro release; the account is flat from END on
RMEMBERS = [
    {"strategy": "N03_ADX_GC", "tf": "15m", "numbers": {"adx_len": 14}, "cell": "t-filter", "stop": ["atr", 2.0], "entry": "now",
     "filter": [["weekend", 1]]},
    {"strategy": "S2_ST_ROC", "tf": "15m", "numbers": {"st_len": 10}, "cell": "t-off", "stop": ["swing", 2], "entry": "now",
     "off": [["hr", 14]]},
    {"strategy": "F4_FAN", "tf": "15m", "numbers": {"fan": 3}, "cell": "t-break", "stop": ["pct", 1.0], "entry": "break"},
    {"strategy": "N08_ICHI_WR", "tf": "15m", "numbers": {"wr_len": 11}, "cell": "t-disp", "stop": ["atr", 2.0], "entry": "now",
     "disp": ["range", 50.0]},
    {"strategy": "F12_MSS_DISP", "tf": "15m", "numbers": {"swing_k": 3}, "cell": "t-ok", "stop": ["swing", 2], "entry": "now"},
]
# (bar close, config order of the research setting, coin, side)
RSIGNALS = [(R0, 3, "BTCUSDT", 1), (R0 + 45 * MIN, 6, "SOLUSDT", 1), (R0 + 60 * MIN, 4, "LTCUSDT", 1),
            (R0 + 75 * MIN, 5, "DOGEUSDT", -1), (R0 + 120 * MIN, 7, "BCHUSDT", 1)]
# (bar close, strategy, coin, side, reference price time after the bar close in ms: -135 s = 200 s old at the submit)
RRULE = [(R0, "V39_ALL", "ETHUSDT", 1, 20_000), (R0 + 105 * MIN, "OBV_S", "SOLUSDT", -1, -135_000)]
PATHS_R = {
    "BTCUSDT": PATHS["BTCUSDT"] + [(R0, 59800.0), (R0 + 40 * MIN, 60300.0), (R0 + 60 * MIN, 59700.0)],
    "ETHUSDT": PATHS["ETHUSDT"] + [(R0, 2480.0), (R0 + 30 * MIN, 2440.0)],
    "SOLUSDT": PATHS["SOLUSDT"] + [(R0 + 45 * MIN, 149.0), (R0 + 100 * MIN, 147.0), (R0 + 150 * MIN, 145.5), (R0 + 170 * MIN, 146.5)],
    "DOGEUSDT": [(T0, 0.2), (R0 + 90 * MIN, 0.2), (R0 + 120 * MIN, 0.198), (R0 + 140 * MIN, 0.1995)],
    "LTCUSDT": [(T0, 80.0), (R0 + 60 * MIN, 80.0), (R0 + 80 * MIN, 80.5), (R0 + 100 * MIN, 79.6)],
    "BCHUSDT": PATHS["BCHUSDT"] + [(R0 + 120 * MIN, 398.0), (R0 + 140 * MIN, 401.0), (R0 + 160 * MIN, 397.0)],
}
END_R = R0 + 200 * MIN
MACRO_CSV = "ts_utc,kind,source_url\n2026-10-19T04:00:00Z,CPI,https://www.bls.gov/schedule/news_release/cpi.htm\n"


def price(sym: str, t: int, paths: Optional[dict] = None) -> float:
    k = (paths or PATHS)[sym]
    if t <= k[0][0]:
        return k[0][1]
    for (a, pa), (b, pb) in zip(k, k[1:]):
        if a <= t <= b:
            return pa + (pb - pa) * (t - a) / (b - a)
    return k[-1][1]


def bar_row(sym: str, t: int, paths: Optional[dict] = None) -> dict:
    o, c = price(sym, t, paths), price(sym, t + MIN, paths)
    hi, lo = max(o, c) * 1.00005, min(o, c) * 0.99995
    return {"ts": t, "symbol": sym, "open": o, "high": hi, "low": lo, "close": c, "volume": 10.0, "mark_open": o,
            "mark_high": hi, "mark_low": lo, "mark_close": c, "close_time": t + MIN - 1, "processed_at": t + MIN + 5_000}


class _Fund:
    """The funding feed the runner reads (livereplay._Fund's shape): rates paid at the first step at or after them."""

    def __init__(self, rates: dict):
        self.rates = {int(k): dict(v) for k, v in rates.items()}

    def poll(self, now: int) -> None:
        pass

    def take(self, ts: int) -> dict:
        out = {}
        for t in [k for k in self.rates if k <= ts]:
            out.update(self.rates.pop(t))
        return out


def direct_signals() -> list:
    """The two signals handed to the engine at DIRECT_T: a BCH long with a research 1 % stop (order 1, entered) and a DOGE
    long (order 2, the same minute: SKIPPED "lower score than entered signal")."""
    out = []
    for sym, order, member in (("BCHUSDT", 1, "V39_ALL@15m#1~pct1"), ("DOGEUSDT", 2, "OBV_S@15m#2~pct1")):
        ref = price(sym, DIRECT_T)
        atr = ref * ATR_FRAC
        out.append(Signal(ts=DIRECT_T - 1, symbol=sym, timeframe="15m", strategy_id=member.split("@")[0], side=1, stop_price=0.0,
                          tier="best", score=3.0, atr=atr,
                          meta={"stop_dist": 3.0 * atr, "ref_time": DIRECT_T + 20_000, "delay_ms": 20_000, "account": C.ACCOUNT,
                                "member": member, "member_order": order, "source": "custom", "score_raw": None, "ctx": {},
                                "ref_price": ref, "research": True, "rstop": ["pct", 1.0]}))
    return out


def research_members() -> list:
    """The research settings as combo.resolve_members makes them (label ``name@tf#order~spec_tag``), without importing the
    strategies' code (their numbers are never computed here: the signals are handed in)."""
    out = []
    for i, sp in enumerate(RMEMBERS, len(MEMBERS) + 1):
        r = RM.parse_spec(sp, sp["strategy"])
        out.append(C.Member(label=f"{sp['strategy']}@{sp['tf']}#{i}~{RM.spec_tag(r)}", kind="core", name=sp["strategy"], tf=sp["tf"],
                            numbers=dict(sp["numbers"]), order=i, research=r))
    return out


class LiveWorld:
    """paper3.db (the rule bot) and live-ac.db (the paper bot) in ``folder``; ``run_to(t)`` steps the paper bot to minute t."""

    def __init__(self, folder: str, funding: bool = True, direct: bool = True, research: bool = False):
        os.makedirs(folder, exist_ok=True)
        self.folder = folder
        self.research = research
        self.paths = PATHS_R if research else PATHS
        self.rule_db = os.path.join(folder, "paper3.db")
        self.paper_db = os.path.join(folder, "live-ac.db")
        self.rule = Store3(self.rule_db)
        raw = {**CONFIG, "paper_db": self.rule_db, "db": self.paper_db}
        if research:
            raw.update(members=MEMBERS + RMEMBERS, macro_blackout_min=30)
        self.cfg = C.ComboConfig.from_dict(raw)
        self.members = C.resolve_members(MEMBERS, core=["V39_ALL", "OBV_S"]) + (research_members() if research else [])
        self.settings = C.settings_of(self.cfg, taker_fee=0.0005)
        self.brackets, src = LR.file_brackets(SYMS)
        self.specs = LR.file_specs(SYMS)
        self.store = Store3(self.paper_db)
        self.note = ListNotifier()
        self.book = C.build_book(self.cfg, self.settings, self.brackets, self.store, self.note, self.specs)
        self.store.put_state("combo_run", T0 - 10 * MIN, {"version": C.VERSION, "brackets": src, "taker_fee": self.settings.taker_fee,
                                                         "members": [m.describe() for m in self.members],
                                                         "config": dataclasses.asdict(self.cfg)})
        self.store.commit()
        self.now = T0 - 9 * MIN
        self.fund = _Fund(FUNDING if funding else {})
        self.direct = direct
        rdata = RM.RData(SYMS, self._klines, lambda s, start: [], self._oi) if research else None
        self.run = C.ComboRunner(self.cfg, self.members, self.book, self.store, self.note, None, now_ms=lambda: self.now,
                                 prices=lambda: {}, funding=self.fund, rdata=rdata)
        self.t = T0 - 10 * MIN                       # the next minute to write
        self._minute(self.t)                           # the rule bot is already running
        self.t += MIN
        self.run.poll()                                # first start: from the rule bot's latest minute

    # ---- the research data the runner reads (Binance in the live bot): these same prices, closed bars only
    def _klines(self, symbol: str, interval: str, start: int, end: int) -> list:
        ms = {"1m": MIN, "1h": H, "4h": 4 * H}[interval]
        t = int(start) - int(start) % ms + (ms if int(start) % ms else 0)
        out = []
        while t < int(end) and t + ms <= self.now:
            o, c = price(symbol, t, self.paths), price(symbol, t + ms, self.paths)
            if interval == "1m":
                b = bar_row(symbol, t, self.paths)
                out.append([t, b["open"], b["high"], b["low"], b["close"]])
            else:
                out.append([t, o, max(o, c) * 1.00005, min(o, c) * 0.99995, c])
            t += ms
        return out

    def _oi(self, symbol: str, start: int, end: int) -> list:
        return [(t, 1_000_000.0) for t in range(int(start) - int(start) % (5 * MIN), int(end), 5 * MIN)]

    def _minute(self, t: int) -> None:
        sigs = [(*s, 20_000) for s in SIGNALS if s[0] == t] + ([s for s in RRULE if s[0] == t] if self.research else [])
        if sigs:
            rows = []
            for bc, strat, sym, side, ref_after in sigs:
                ref = price(sym, bc, self.paths)
                rows.append({"bar_close": bc, "timeframe": "15m", "strategy": strat, "symbol": sym, "side": side,
                             "atr": ref * ATR_FRAC, "ref_price": ref, "ref_time": bc + ref_after,
                             "delay_ms": 20_000, "status": "SUBMITTED", "data": {"ctx": {}}})
            self.rule.log_signals(rows)
        self.rule.live_bars([bar_row(s, t, self.paths) for s in SYMS])
        self.rule.commit()

    def _research_signals(self, t: int) -> None:
        """The research settings' signals of the bar closing at t, handed to the runner as its custom path does (after the
        strategy computation, which is not run here): make_signal with the reference price, then _research_signal."""
        by = {m.order: m for m in self.members}
        for bc, order, sym, side in RSIGNALS:
            if bc != t:
                continue
            m = by[order]
            ref = price(sym, bc, self.paths)
            sig = C.make_signal(self.cfg, m, bc, sym, side, ref * ATR_FRAC, ref, bc + 20_000, 20_000, {"close": ref}, "custom")
            self.run._research_signal(m, sig, bc)

    def run_to(self, t_end: int) -> "LiveWorld":
        """Write and step every minute before ``t_end``."""
        while self.t < t_end:
            t = self.t
            self._minute(t)
            if self.direct and t == DIRECT_T:
                for sig in direct_signals():
                    self.book.engines[C.ACCOUNT].submit(sig)
            self.now = t + 65_000
            if self.research:
                self._research_signals(t)
            self.run.poll()
            self.t += MIN
        return self

    def engine(self, aid: str = C.ACCOUNT):
        return self.book.engines[aid]

    def close(self) -> None:
        self.store.close()
        self.rule.close()


def build(folder: str, until: Optional[int] = END, **kw) -> LiveWorld:
    w = LiveWorld(folder, **kw)
    if until is not None:
        w.run_to(until)
    return w


# ---------------------------------------------------------------- the executors (group 5: 실행기가 안 따라감)
def exec_db(path: str, name: str, followed: list, events: Optional[list] = None, halt_at: Optional[int] = None,
            live_since: int = T0 - H) -> str:
    """An order executor's database by its own writers (paperbot.executor.ExecStore): ``followed`` = [(symbol, side, paper entry
    ms, pnl)] trades it opened and closed under the paper trade's key, ``events`` = [(ts, kind, text, paper key)] its reasons
    (light_red, late, entry_check …), ``halt_at``: halted from then on (halt_log), ``live_since``: when it went live."""
    from paperbot.executor import ExecStore
    st = ExecStore(path, lock=False)
    st.put_state("meta", live_since, {"mode": "mainnet", "account": C.ACCOUNT, "since": live_since, "exchange": name,
                                      "live_since": live_since})
    st.event(live_since, "INFO", "start", "시작")
    for sym, side, entry_t, pnl in followed:
        key = f"{C.ACCOUNT}|{sym}|{entry_t}"
        t = {"key": key, "symbol": sym, "side": side, "qty": 1.0, "leverage": 30, "entry_ts": entry_t + 20_000, "entry_price": 100.0,
             "stop_initial": 99.0, "mode": "mainnet", "entry_time": entry_t}
        st.trade_open(t)
        st.trade_close(key, entry_t + 30 * MIN, "paper 청산 → 거래소 포지션 닫기", pnl, t, "wallet")
    for ts, kind, text, key in events or []:
        st.event(ts, "WARN", kind, text, {"key": key})
    if halt_at is not None:
        st.halt_log(halt_at, "halt", "연속 손실 3번", planned=True)
        st.event(halt_at, "CRITICAL", "halt", "거래를 멈춥니다(사람이 풀 때까지): 연속 손실 3번")
    st.put_state("bot", T0 + 10 * H, {"trade": None, "done": [], "loops": 1, "mode": "mainnet", "account": C.ACCOUNT,
                                      "risk": {"halted": halt_at is not None, "halt_reason": "연속 손실 3번" if halt_at else "",
                                               "consecutive_losses": 0, "trades": len(followed)}})
    st.close()
    return path
