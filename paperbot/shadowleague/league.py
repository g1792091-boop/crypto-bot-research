"""The shadow league: explicit members, and the tick that follows each of them on live closed bars.

A member is a pre-registered idea that failed its test and is still followed, for reference, as virtual trades:

    Member(member_id, name_ko, detector, trade spec, timeframes, coins, start date, account, clone settings)

The league never opens a position, never reads or writes a paper account, and nothing here is judged by the 30-day
checkpoint or counted in anyone's multiple-testing correction. Adding a member = one more explicit entry in MEMBERS
(its detector is a small object with ``id``, ``min_bars``, ``params()`` and ``detect()``; see zoneflip.ZoneFlipDetector).
A member's definition is hashed when it is first written to the database; if the code later describes the member
differently, that member stops with a plain message (a changed rule is a new member, never a quiet edit).

One tick, per member and series (coin x timeframe), in order of how far behind it is:
  1. feed: ask for new closed bars only if one is due (feed.py), keep them with their ATR14;
  2. process every closed bar after the series' cursor, in order: detect signals, enter at the next bar's open, follow
     the open trade bar by bar (stop first when a bar touches both), record the clones; the cursor moves on in the same
     transaction, so a crash re-does the chunk and a second tick of the same bars changes nothing;
  3. then, per member: resolve pending clones, recompute the owners'-style accounts from the trade rows.
A gap (a missed tick, a restart, minutes or days) is the same thing as a long chunk: the missing bars are fetched and
processed in order, nothing is skipped and nothing is counted twice.
"""

from __future__ import annotations

import calendar
import dataclasses
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

import numpy as np

from . import LABEL_KO
from . import account as AC
from . import clones as CL
from . import feed as FD
from . import sim as SM
from .store import KEEP_BARS, Store
from .zoneflip import ZoneFlipDetector

DAY_MS = 86_400_000
MAX_CHUNK_BARS = 2000             # new bars of one series handled in one tick (a long gap finishes over several ticks)
WORK_S = 14.0                     # no new series is started after this many seconds of a tick
HARD_S = 20.0                     # no network request is started that could end after this
STALE_MS = 6 * 3_600_000          # a member whose last tick is older than this reads 'off' on the card


class Detector(Protocol):
    id: str
    min_bars: int

    def params(self) -> dict: ...

    def detect(self, o, h, l, c, v, atr, first_r: int) -> list[dict]: ...


@dataclass(frozen=True)
class TradeSpec:
    """How a signal becomes a virtual trade: the study's engine conventions (sim.py)."""
    max_hold: int = SM.MAX_HOLD
    fee_side: float = SM.FEE_SIDE
    slip_side: float = SM.SLIP_SIDE
    funding_8h: float = SM.FUNDING_8H
    entry: str = "next bar open + slippage"
    one_per_series: bool = True            # one position per coin and timeframe

    def cost(self, tf: str) -> SM.Cost:
        return SM.Cost(fee_side=self.fee_side, slip_side=self.slip_side, funding_8h=self.funding_8h,
                       bar_minutes=SM.TF_MINUTES[tf], max_hold=self.max_hold)


@dataclass(frozen=True)
class AccountSpec:
    """The owners' style: 20 % of the equity as margin x 20x, one position at a time, 4.5 % adverse move = liquidation."""
    start_equity: float = AC.START_EQUITY
    margin_frac: float = AC.OWN_MARGIN
    leverage: int = 20
    liq_adverse: float = AC.OWN_LIQ


@dataclass(frozen=True)
class Member:
    member_id: str
    name_ko: str
    detector: Any
    start_ms: int
    trade: TradeSpec = field(default_factory=TradeSpec)
    tfs: tuple = ("15m", "30m", "1h", "4h")
    coins: tuple = ("BTC", "ETH", "SOL", "DOGE", "LTC", "BCH")        # Binance USDT-M perpetuals
    account: AccountSpec = field(default_factory=AccountSpec)
    clones_k: int = CL.DEFAULT_K
    clone_days: int = CL.DEFAULT_DAYS
    blurb_ko: str = ""
    study: str = ""                                                    # key into study.STUDIES

    def spec(self) -> dict:
        """The member's definition as stored (and hashed) in the database."""
        return {"member_id": self.member_id, "detector": self.detector.id, "detector_params": self.detector.params(),
                "trade": dataclasses.asdict(self.trade), "tfs": list(self.tfs), "coins": list(self.coins),
                "start_ms": self.start_ms, "account": dataclasses.asdict(self.account), "clones_k": self.clones_k,
                "clone_days": self.clone_days, "study": self.study}

    def spec_sha256(self) -> str:
        blob = json.dumps(self.spec(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def utc_ms(y: int, m: int, d: int) -> int:
    return calendar.timegm((y, m, d, 0, 0, 0)) * 1000


ZONEFLIP = Member(
    member_id="zoneflip",
    name_ko="매물대 지지→저항 전환 (릴스 parkdando_)",
    detector=ZoneFlipDetector(),
    start_ms=utc_ms(2026, 10, 7),
    blurb_ko="거래량이 쌓인 가격대를 3번 이상 지켜 준 뒤 그 가격대가 깨지고, 되돌아와 다시 막히면 깨진 쪽으로 들어가는 규칙. "
             "5년 시험에서 실패했고(8칸 중 통과 0), 지금은 같은 규칙을 실제 봉에서 가상 거래로만 지켜봅니다.",
    study="zoneflip")

MEMBERS = (ZONEFLIP,)          # explicit and short: a new idea is one more line here (and its detector)


def _series(member: Member) -> list[tuple]:
    return [(c, tf) for c in member.coins for tf in member.tfs]


class League:
    """The tick. ``get`` = the public-klines getter the agents tick has (None = no price source: every series says so)."""

    def __init__(self, store: Store, members: tuple = MEMBERS, get: Optional[Callable[[str], Any]] = None,
                 clock: Callable[[], float] = time.monotonic):
        self.store = store
        self.members = tuple(members)
        self.get = get
        self.clock = clock

    # ------------------------------------------------------------------------------------------------ the tick
    def tick(self, now_ms: int, work_s: float = WORK_S, hard_s: float = HARD_S) -> dict:
        t0 = self.clock()
        work_end, hard_end = t0 + work_s, t0 + hard_s
        st = self.store
        out: dict = {"now_ms": int(now_ms), "members": {}, "bars_added": 0, "signals": 0, "opened": 0, "closed": 0,
                     "clones": 0, "errors": [], "timed_out": False, "behind": 0}
        live = []
        for m in self.members:
            row = st.member(m.member_id)
            if row is None:
                row = st.add_member(m.member_id, m.name_ko, m.detector.id, m.spec(), m.spec_sha256(), m.start_ms, now_ms)
            if row["spec_sha256"] != m.spec_sha256():
                why = "정의가 처음 기록한 것과 달라져 멈춤 (바뀐 규칙은 새 멤버로 만들어야 합니다)"
                st.halt_member(m.member_id, why)
                out["members"][m.member_id] = {"halted": why}
                continue
            if row["halted"]:
                st.halt_member(m.member_id, None)
            st.touch_member(m.member_id, now_ms)
            live.append(m)
        work: list[tuple] = []
        for m in live:
            for coin, tf in _series(m):
                cur = st.series(m.member_id, coin, tf)
                lag = (FD.latest_closed_open(now_ms, tf) - (cur["last_bar_ms"] or 0)) // FD.TF_MS[tf] if cur else 10 ** 9
                work.append((-lag, m.member_id, coin, tf, m))
        work.sort(key=lambda x: x[:4])
        synced: dict = {}
        for _lag, _mid, coin, tf, m in work:
            if self.clock() > work_end:
                out["timed_out"] = True
                out["behind"] += 1
                continue
            res = out["members"].setdefault(m.member_id, {"series": 0, "errors": 0})
            try:
                if (coin, tf) not in synced:
                    anchor = min(FD.anchor_ms(x.start_ms, tf) for x in live if (coin, tf) in _series(x))
                    synced[(coin, tf)] = FD.sync_series(st, coin, tf, self.get, now_ms, anchor, deadline_at=hard_end,
                                                        clock=self.clock)
                    out["bars_added"] += synced[(coin, tf)]["added"]
                got = self._process(m, coin, tf, now_ms, synced[(coin, tf)])
            except Exception as exc:  # noqa: BLE001  (written on the series, never lost; the other series go on)
                why = f"{type(exc).__name__}: {str(exc)[:160]}"
                st.put_series(m.member_id, coin, tf, "error", now_ms, note=why)
                out["errors"].append(f"{m.member_id}/{coin}/{tf}: {why}")
                res["errors"] += 1
                continue
            res["series"] += 1
            for k in ("signals", "opened", "closed", "clones"):
                out[k] += got.get(k, 0)
        for m in live:
            try:
                out["clones"] += self._resolve_clones(m, now_ms)
                self.update_accounts(m)
            except Exception as exc:  # noqa: BLE001
                out["errors"].append(f"{m.member_id}/clones+account: {type(exc).__name__}: {str(exc)[:160]}")
        st.set_meta("last_tick", {"ms": int(now_ms), "wall_s": round(self.clock() - t0, 2), "bars_added": out["bars_added"],
                                  "signals": out["signals"], "opened": out["opened"], "closed": out["closed"],
                                  "errors": out["errors"][:10], "timed_out": out["timed_out"], "behind": out["behind"]})
        out["wall_s"] = round(self.clock() - t0, 2)
        return out

    # ------------------------------------------------------------------------------------------------ one series
    def _process(self, m: Member, coin: str, tf: str, now_ms: int, sync: dict) -> dict:
        st, tfm = self.store, FD.TF_MS[tf]
        out = {"signals": 0, "opened": 0, "closed": 0, "clones": 0}
        feed = st.feed(coin, tf)
        arr = st.load_bars(coin, tf)
        n_all = len(arr["t"])
        need = int(m.detector.min_bars)
        have = int(feed["n_ingested"]) if feed else 0
        if n_all == 0 or have < need:
            if feed and feed["state"] == "error" and have == 0:
                st.put_series(m.member_id, coin, tf, "error", now_ms, warm_have=have, warm_need=need,
                              note="시세를 받지 못함: " + (feed["error"] or ""))
            else:
                st.put_series(m.member_id, coin, tf, "warming", now_ms, warm_have=have, warm_need=need,
                              note=f"워밍업 중 ({max(0, need - have)}봉 더 필요)")
            return out
        t = arr["t"]
        i_start = int(np.searchsorted(t, m.start_ms, side="left"))
        if i_start >= n_all:
            st.put_series(m.member_id, coin, tf, "waiting", now_ms, warm_have=have, warm_need=need,
                          note="시작일 전 (봉만 모으는 중)")
            return out
        prior = st.series(m.member_id, coin, tf)
        last_done = prior["last_bar_ms"] if prior else None
        i0 = 0 if last_done is None else int(np.searchsorted(t, last_done, side="right"))
        if i0 < n_all:
            n = min(n_all, i0 + MAX_CHUNK_BARS)
            g0 = have - n_all                                   # global index of the first stored bar
            first_r = max(i0, i_start, need - g0)
            with st.tx():
                out = self._chunk(m, coin, tf, arr, n, i0, first_r, now_ms)
                st.put_series(m.member_id, coin, tf, "recording", now_ms, last_bar_ms=int(t[n - 1]),
                              warm_have=have, warm_need=need, note=None)
        cur = st.series(m.member_id, coin, tf)
        self._finish_status(m, coin, tf, cur, feed, sync, now_ms, tfm)
        self._prune(coin, tf, tfm)
        return out

    def _prune(self, coin: str, tf: str, tfm: int) -> None:
        """Drop bars older than KEEP_BARS before the slowest member's cursor (never while a member has not started on them)."""
        st, cursors = self.store, []
        for x in self.members:
            if (coin, tf) in _series(x):
                s = st.series(x.member_id, coin, tf)
                if s is None or s["last_bar_ms"] is None:
                    return
                cursors.append(int(s["last_bar_ms"]))
        if cursors:
            st.conn.execute("DELETE FROM bars WHERE coin = ? AND tf = ? AND t_ms < ?",
                            (coin, tf, min(cursors) - KEEP_BARS * tfm))

    def _finish_status(self, m: Member, coin: str, tf: str, cur: Optional[dict], feed: Optional[dict], sync: dict,
                       now_ms: int, tfm: int) -> None:
        """'error' only when the feed is failing AND this series has fallen two bars or more behind the newest closed bar;
        a single late bar is not an alarm. Otherwise the status stays 'recording' with the feed's last problem as the note."""
        if not cur or cur["status"] in ("waiting", "warming"):
            return
        feed = self.store.feed(coin, tf) or feed
        behind = (FD.latest_closed_open(now_ms, tf) - int(cur["last_bar_ms"])) // tfm
        if feed and feed["state"] == "error" and behind >= 2:
            self.store.put_series(m.member_id, coin, tf, "error", now_ms, warm_have=cur["warm_have"],
                                  warm_need=cur["warm_need"],
                                  note=f"시세를 못 받아 {behind}봉 늦음: {feed['error'] or ''}")
        elif cur["status"] == "error":
            self.store.put_series(m.member_id, coin, tf, "recording", now_ms, warm_have=cur["warm_have"],
                                  warm_need=cur["warm_need"], note=None)

    def _chunk(self, m: Member, coin: str, tf: str, arr: dict, n: int, i0: int, first_r: int, now_ms: int) -> dict:
        """Bars i0 .. n-1 (indices into the stored arrays) become signals and trades, in order. Inside one transaction."""
        st, tfm = self.store, FD.TF_MS[tf]
        out = {"signals": 0, "opened": 0, "closed": 0, "clones": 0}
        t, o, h, l, c, v, atr = (arr[k][:n] for k in ("t", "o", "h", "l", "c", "v", "atr"))
        cost = m.trade.cost(tf)
        feed = st.feed(coin, tf)

        def idx(ms: int) -> int:
            return int(np.searchsorted(t, int(ms), side="left"))

        recs = m.detector.detect(o, h, l, c, v, atr, first_r) if first_r < n else []
        cand: list[tuple] = []                                           # (r, signal row), the ones that may trade
        for rec in recs:
            sid = f"{m.member_id}|{coin}|{tf}|{int(t[rec['r']])}|{rec['side']}|{int(t[rec['b']])}|{rec['extra']['zone_lo']:.10g}"
            status = "candidate" if rec["chosen"] else ("skip_" + rec["skip"] if rec["skip"] else "not_chosen")
            row = {"signal_id": sid, "member_id": m.member_id, "coin": coin, "tf": tf, "side": rec["side"],
                   "bar_ms": int(t[rec["r"]]), "break_ms": int(t[rec["b"]]), "plan_entry": rec["ref"],
                   "stop": rec["stop"], "target": rec["target"], "rr": rec["rr"], "touches": rec["touches"],
                   "atr": rec["atr"], "zone_lo": rec["extra"]["zone_lo"], "zone_hi": rec["extra"]["zone_hi"],
                   "tz_lo": rec["extra"]["tz_lo"], "tz_hi": rec["extra"]["tz_hi"], "status": status,
                   "recorded_ms": int(now_ms)}
            if st.add_signal(row):
                out["signals"] += 1
            if rec["chosen"]:
                cand.append((rec["r"], row))
        for p in st.pending_signals(m.member_id, coin, tf):              # a signal on the last bar of the previous chunk
            cand.append((idx(p["bar_ms"]), p))
        cand.sort(key=lambda x: x[0])

        cur = st.open_trade(m.member_id, coin, tf)
        le = st.last_exit_ms(m.member_id, coin, tf)
        next_free = idx(le) if le is not None and le >= t[0] else -1
        if cur is not None:
            decided, tr = self._follow(cur, idx, o, h, l, c, cost)
            if decided:
                self._close(cur["trade_id"], tr, t, now_ms)
                next_free, cur = int(tr["exit_idx"]), None
                out["closed"] += 1
        for r, sig in cand:
            sid, side = sig["signal_id"], int(sig["side"])
            if cur is not None or r <= next_free:
                st.set_signal_status(sid, "busy")
                continue
            if r >= n - 1:
                st.set_signal_status(sid, "pending_entry")          # its entry bar (the next one) has not closed yet
                continue
            e = r + 1
            entry = o[e] * (1.0 + side * cost.slip_side)
            stop, tgt = float(sig["stop"]), float(sig["target"])
            if side * (entry - stop) <= 0 or side * (tgt - entry) <= 0:
                st.set_signal_status(sid, "skip_entry")             # the open is already beyond the stop or the target
                continue
            trade = {"trade_id": sid, "member_id": m.member_id, "coin": coin, "tf": tf, "side": side,
                     "signal_ms": int(t[r]), "entry_ms": int(t[e]), "entry_px": float(entry), "stop_px": stop,
                     "target_px": tgt, "sl_dist": side * (entry - stop) / entry, "tp_dist": side * (tgt - entry) / entry,
                     "status": "open", "recorded_ms": int(now_ms)}
            st.add_trade(trade)
            st.set_signal_status(sid, "taken")
            out["opened"] += 1
            out["clones"] += st.add_clones(CL.make_clones(m.member_id, trade, tfm, int(feed["first_bar_ms"]), now_ms,
                                                          m.clones_k, m.clone_days))
            decided, tr = self._follow(trade, idx, o, h, l, c, cost)
            if decided:
                self._close(sid, tr, t, now_ms)
                next_free = int(tr["exit_idx"])
                out["closed"] += 1
            else:
                cur = trade
        return out

    @staticmethod
    def _follow(trade: dict, idx: Callable[[int], int], o, h, l, c, cost) -> tuple[bool, dict]:
        e = idx(trade["entry_ms"])
        return SM.step_trade(int(trade["side"]), e, float(trade["entry_px"]), float(trade["stop_px"]),
                             float(trade["target_px"]), o, h, l, c, cost)

    def _close(self, trade_id: str, tr: dict, t: np.ndarray, now_ms: int) -> None:
        self.store.close_trade(trade_id, {**tr, "exit_ms": int(t[tr["exit_idx"]])}, now_ms)

    # ------------------------------------------------------------------------------------------------ clones, accounts
    def _resolve_clones(self, m: Member, now_ms: int) -> int:
        st, n = self.store, 0
        for coin, tf in st.pending_clone_series(m.member_id):
            bars = st.load_bars(coin, tf)
            if not len(bars["t"]):
                continue
            cost = m.trade.cost(tf)
            with st.tx():
                for cl in st.pending_clones(m.member_id, coin, tf):
                    row = CL.resolve_clone(cl, bars, cost, now_ms)
                    if row is None:
                        continue
                    st.update_clone(cl["clone_id"], row)
                    n += row["status"] == "closed"
        return n

    def update_accounts(self, m: Member) -> None:
        """Recompute the owners'-style accounts from the trade rows (a pure function of them, never accumulated)."""
        st = self.store
        trades = st.trades(m.member_id)
        series = st.series_rows(m.member_id)
        a = m.account
        sets = [(tf, [x for x in trades if x["tf"] == tf]) for tf in m.tfs] + [("all", trades)]
        acct_rows: list[tuple] = []
        with st.tx():
            for scope, tr in sets:
                res = AC.run_account(tr, a.start_equity, AC.OWN_EXPO, a.margin_frac, a.liq_adverse)
                asof = AC.frontier_ms(series, None if scope == "all" else scope)
                st.replace_account_daily(m.member_id, scope, AC.daily_equity(tr, res, m.start_ms, asof, a.start_equity)
                                         if asof else [])
                if scope != "all":
                    acct_rows += [(int(r["taken"]), r["ret"], r["equity"], int(r["liquidated"]), r["trade_id"])
                                  for r in res]
            st.set_trade_account(acct_rows)
