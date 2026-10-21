"""추세판단 봇 (owners 2026-10-21): the combined paper bot (paperbot/combo.py) with ``"trend"`` in its config.

Owners: "추세형 매매법은 진입 안 하고 추세만 보는 거고, 1시간봉 추세 보고 30분봉에서 진입 ... 1시간봉 진입은 4시간봉 추세",
then "실거래 바로 돌릴꺼고 ... 나머지는 다 추천대로". Everything of the combined bot stays (the rule bot's signals of the
entry members, one position, BTC 40x / others 30x, margin 40 %, the -50 % net stop, the ladder, the fast stop before
the first lock, the weekend / macro / NYSE-open pauses, the chase block, the coin-flip twin); this adds:

1. 추세 판단 (paperbot/trendjudge.py): an entry member's signal goes on only when the last closed higher bar (30m -> 1h,
   1h -> 4h) is a trend on the signal's side (3 of the 4 judges, held, ADX 20+, not 끝물) and the entry checks pass
   (not stretched from the higher EMA20, near the entry bar's EMA20, RSI, breakout members only early). Else the
   signal is logged FILTERED with the reason and the numbers read (signal_log data ``trend``).
2. 되돌림 진입 (안 ①): a signal that passed waits one entry bar for the price to come back ``pullback_atr`` (0.25) ATR
   (0.5 after a long signal bar): WAITING "되돌림 기다림"; the first 1m bar that trades there -> the entry is the next
   minute (the reference price = the book then, the executors follow with a market order as always): BROKE
   "되돌림 확인" and a new SUBMITTED row; no touch by the entry bar's second-to-last minute: FILTERED "되돌림 안 옴".
3. 점수: the signals of one minute compete by ``trendjudge.score`` (judge strength + spot + the member's recent record).
4. 쉬기 (only this bot's own trades, from its first start on this database, ``trend_since``): a member whose last
   ``member_losses`` (2) trades lost pauses ``member_pause_h`` (24) h from the last loss; after a losing trade no
   entry on that coin and side for ``coin_pause_h`` (2) h; with ``daily_loss`` set (off in the owners' config, 10-21
   "10번은 없애고"), the account lost that share of the day's start in a KST day: no entry until the next KST day. Each pause starts with one Telegram line.
5. 감독 (every minute, before the first lock only; never a reverse entry): TIME: ``time_bars`` (4) entry bars after
   the entry without the first lock -> closed at that minute's open; JUDGE: a higher bar closed after the entry is
   judged the other way (3 of 4, ``judge_exit``) -> closed. Exit reasons "TIME" / "JUDGE" (the executors follow them
   like REV: only while their own position has no lock of its own, paperbot/executor.py).
6. The judgments of every coin (1h and 4h), the waits and the pauses are saved each minute as state ``trend`` (the
   live site shows them).

Stop tightening on events (급변, BTC 급변, macro / funding) is the next step (owners 10-21 plan): it needs the executors
to move their exchange stops with the paper and a drill first.
"""

from __future__ import annotations

import dataclasses
import json
import time
from dataclasses import replace
from typing import Optional

from . import combo as C
from .models import Signal
from .notify import WARN
from .trendjudge import (HTF_OF, KO_DIR, KO_TF, TF_MS, Judge, Klines, TrendError, TrendRules, check, score)

MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000
KST_MS = 9 * HOUR
STATE_TREND = "trend"
ENTRY_TFS = ("30m", "1h")
KO_SIDE = {1: "롱", -1: "숏"}
SUP_KO = {"JUDGE": "감독 청산(추세 판단 뒤집힘)", "TIME": "감독 청산(시간 정리)"}
SNAP_EVERY_MS = 5 * MIN
TRADES_READ = 400
RESEARCH_KEYS = ("pick", "numbers", "stop", "entry", "invert", "filter", "disp", "off", "cell")


def kst(ms: int) -> str:
    return time.strftime("%m-%d %H:%M", time.gmtime((int(ms) + KST_MS) / 1000))


def config_problems(cfg) -> list[str]:
    """The trend section and what the trend bot needs of the rest of the config (Korean)."""
    try:
        rules = TrendRules.from_dict(cfg.trend)
    except (TrendError, TypeError) as exc:
        return [str(exc)]
    out = rules.problems()
    for i, m in enumerate(cfg.members if isinstance(cfg.members, list) else [], 1):
        if not isinstance(m, dict):
            continue
        if m.get("tf") not in ENTRY_TFS:
            out.append(f"추세판단 봇 members {i}번째({m.get('strategy')}): 진입 봉은 30m 또는 1h만 됩니다")
        bad = [k for k in RESEARCH_KEYS if m.get(k) is not None]
        if bad:
            out.append(f"추세판단 봇 members {i}번째({m.get('strategy')}): 규칙봇 기본값 신호만 씁니다({', '.join(bad)} 빼기)")
    if not cfg.rank or cfg.rank[0] != "score":
        out.append('추세판단 봇의 rank는 "score"로 시작합니다(동시 신호는 점수로 고르기)')
    return out


def make_judge(cfg, rest) -> Judge:
    """The judge on Binance's public klines: its own client (5 s timeout, one retry), so a failing endpoint costs
    seconds, never the minute."""
    from .binance import BinanceREST, urllib_fetch
    own = BinanceREST(base_url=rest.base, fetch=lambda u, h: urllib_fetch(u, h, timeout=5.0), max_retries=1,
                      backoff=0.5)
    k = Klines(lambda s, tf, n: own.klines(s, tf, limit=n), lambda: int(time.time() * 1000))
    return Judge(k, TrendRules.from_dict(cfg.trend))


# ====================================================================== the account
class TrendEngine(C.ComboEngine):
    """ComboEngine with the supervisor's exits: ``supervise(reason, why)`` closes the open position at the next
    stepped minute's open (before the first lock only), and that minute enters nothing (as the early exit)."""

    def __init__(self, settings, brackets, combo=None, **kw):
        super().__init__(settings, brackets, combo=combo, **kw)
        self._sup: Optional[tuple] = None

    def supervise(self, reason: str, why: str) -> None:
        self._sup = (reason, why)

    def step(self, bars, funding=None) -> None:
        sup, self._sup = self._sup, None
        p = self.position
        if sup is not None and p is not None and p.symbol in bars and p.lock_roe is None:
            bar = bars[p.symbol]
            ctx = dict(p.signal.meta.get("ctx") or {})
            ctx["exit_why"] = sup[1]
            p.signal = replace(p.signal, meta={**p.signal.meta, "ctx": ctx})
            self._close_market(bar.open, bar.open_time, sup[0])
            for g in self.pending:
                self._record(g, "SKIPPED", "supervisor exit this minute", bar.open_time)
            self.pending = []
            self._exit_on = []
        super().step(bars, funding)


# ====================================================================== the runner
class TrendRunner(C.ComboRunner):
    """ComboRunner with the trend judge, the pullback wait, the pauses, the daily loss stop and the supervisor."""

    def __init__(self, *a, judge: Judge, **kw):
        super().__init__(*a, **kw)
        self.rules = TrendRules.from_dict(self.cfg.trend)
        self.judge = judge
        st = self.store.get_state(C.STATE_KEY)
        st = st[1] if st else {}
        self.pulls: list = list(st.get("pulls", []))
        self.told: dict = dict(st.get("told", {}))
        self.since: int = int(st.get("trend_since") or self.now_ms())
        self.jfails = 0
        self._snap: Optional[tuple] = None
        self._jnoted: set = set()
        known = set(self.by_label)
        old = [p for p in self.pulls if p.get("member") not in known]
        if old:
            self.pulls = [p for p in self.pulls if p.get("member") in known]
            for p in old:
                self._restate(C._sig_from(p["signal"]), "FILTERED", "설정이 바뀌어 기다리던 되돌림 신호를 버림",
                              expect=("WAITING",))
            self.store.commit()

    def _state_extra(self) -> dict:
        return {"pulls": getattr(self, "pulls", []), "told": getattr(self, "told", {}),
                "trend_since": getattr(self, "since", None)}

    # ---- this bot's own closed trades
    def _trades(self) -> list:
        """COMBO@mix trades entered since this bot started on the database, newest first (TradeRecord fields)."""
        rows = self.store.conn.execute(
            "SELECT data FROM trades WHERE account_id = ? AND entry_time >= ? ORDER BY exit_time DESC, id DESC LIMIT ?",
            (C.ACCOUNT, int(self.since), TRADES_READ)).fetchall()
        out = []
        for (d,) in rows:
            try:
                out.append(json.loads(d))
            except (TypeError, ValueError):
                continue
        return out

    def _record_of(self, sig: Signal, trades: Optional[list] = None) -> list:
        trades = self._trades() if trades is None else trades
        return [float(t["pnl"]) for t in trades
                if t.get("strategy_id") == sig.strategy_id and t.get("timeframe") == sig.timeframe]

    def _tell_once(self, key: str, text: str) -> None:
        if key in self.told:
            return
        self.told[key] = int(self.now_ms())
        if len(self.told) > 200:
            for k in sorted(self.told, key=self.told.get)[:100]:
                self.told.pop(k, None)
        self.store.alert(self.now_ms(), WARN, text[:300])
        if self.cfg.telegram:
            self.notifier.send(WARN, text)

    # ---- pauses (each entry minute, the pulled entries too)
    def pauses(self, ts: int, trades: Optional[list] = None) -> dict:
        """{"day": (why, until) or None, "members": {label: (why, until)}, "coins": {(symbol, side): (why, until)}}
        in force at minute ts."""
        r = self.rules
        trades = self._trades() if trades is None else trades
        out: dict = {"day": None, "members": {}, "coins": {}}
        day0 = int(ts) - (int(ts) + KST_MS) % DAY
        today = [t for t in trades if int(t["exit_time"]) >= day0 and int(t["exit_time"]) <= int(ts)]
        if today and r.daily_loss is not None:
            # the wallet before today's first closed trade (review 10/21: never the config's initial equity, the
            # database's wallet carries over from the bots before this one)
            first = today[-1]
            start = float(first["equity_after"]) - float(first["pnl"])
            lost = sum(float(t["pnl"]) for t in today)
            if start > 0 and lost <= -r.daily_loss * start:
                out["day"] = (f"하루 손실 한도: 오늘(한국 시간) 계좌 {lost / start:+.0%}라 오늘은 진입 안 함"
                              f"(한도 -{r.daily_loss:.0%})", day0 + DAY)
        done = [t for t in trades if int(t["exit_time"]) <= int(ts)]
        by_member: dict = {}
        for t in done:
            by_member.setdefault((t.get("strategy_id"), t.get("timeframe")), []).append(t)
        for (name, tf), ts_ in by_member.items():
            last = ts_[:r.member_losses]
            if len(last) == r.member_losses and all(float(t["pnl"]) < 0 for t in last):
                until = int(last[0]["exit_time"]) + int(r.member_pause_h * HOUR)
                if ts < until:
                    out["members"][f"{name}@{tf}"] = (f"{name} {KO_TF.get(tf, tf)} 손실 {r.member_losses}번 연속: "
                                                     f"{kst(until)}까지 쉼", until)
        seen: set = set()
        for t in done:
            key = (t.get("symbol"), int(t.get("side")))
            if key in seen:
                continue
            seen.add(key)
            until = int(t["exit_time"]) + int(r.coin_pause_h * HOUR)
            if float(t["pnl"]) < 0 and ts < until:
                out["coins"][key] = (f"{str(key[0]).replace('USDT', '')} {KO_SIDE.get(key[1], key[1])} 손실 뒤 "
                                     f"{r.coin_pause_h:g}시간 쉼({kst(until)}까지)", until)
        return out

    def _entry_block(self, sig: Signal, ts: int, bar_close: int, bars: dict) -> str:
        why = super()._entry_block(sig, ts, bar_close, bars)
        if why:
            return why
        pz = self.pauses(ts)
        if pz["day"]:
            self._tell_once(f"day|{pz['day'][1]}", f"{self.cfg.tag} ⛔ {pz['day'][0]}. 내일 00:00(한국 시간)부터 다시 "
                            "진입해요. 열린 포지션은 손절·익절 그대로")
            return pz["day"][0]
        label = sig.meta.get("member", sig.strategy_id)
        m = pz["members"].get(f"{sig.strategy_id}@{sig.timeframe}")
        if m:
            self._tell_once(f"member|{label}|{m[1]}", f"{self.cfg.tag} ⏸ {m[0]} (그 매매법만 쉼)")
            return m[0]
        c = pz["coins"].get((sig.symbol, int(sig.side)))
        if c:
            return c[0]
        return ""

    # ---- the judge and the pullback wait
    def _judge_failed(self, text: str) -> None:
        self.jfails += 1
        msg = f"{self.cfg.tag} 추세 판단을 못 읽어 진입 안 함({self.jfails}번째): {text}"[:300]
        self.store.alert(self.now_ms(), WARN, msg)
        if self.cfg.telegram and (self.jfails in (1, 10, 100) or self.jfails % 1000 == 0):
            self.notifier.send(WARN, msg)

    def _klines_errors(self) -> None:
        k = getattr(self.judge, "k", None)
        if k is None or not k.errors:
            return
        for e in k.errors[-3:]:
            self.store.alert(self.now_ms(), WARN, f"[trend] {e}"[:300])
        k.errors.clear()

    def _filtered(self, sig: Signal, why: str, extra: Optional[dict] = None) -> None:
        self._restate(sig, "FILTERED", why, extra=extra)
        self._count(sig.meta.get("member", sig.strategy_id), "filtered")

    def _divert(self, sig: Signal, ts: int, bar_close: int, bars: dict) -> bool:
        if sig.meta.get("pulled"):
            return False                              # the entry after its pullback: submitted now
        htf = HTF_OF.get(sig.timeframe)
        if htf is None:
            self._filtered(sig, "추세판단 봇은 30분·1시간 진입만 받아요")
            return True
        price = sig.meta.get("ref_price")
        if not price and sig.symbol in bars:
            price = bars[sig.symbol].open
        if not price:
            self._filtered(sig, "추세 판단에 쓸 가격이 없음(진입 안 함)")
            return True
        try:
            j = self.judge.judgment(sig.symbol, htf, bar_close)
            s = self.judge.spot(sig.symbol, sig.timeframe, bar_close)
        except Exception as exc:  # noqa: BLE001  unreadable: no entry, said so
            why = str(exc) if isinstance(exc, TrendError) else f"{type(exc).__name__}: {exc}"
            self._filtered(sig, f"추세 판단을 못 읽어 진입 안 함: {why}"[:200])
            self._judge_failed(f"{sig.symbol} {sig.timeframe}: {why}")
            return True
        finally:
            self._klines_errors()
        side = int(sig.side)
        why, info = check(self.rules, sig.strategy_id, sig.timeframe, side, float(price), j, s)
        if why:
            self._filtered(sig, why, {"trend": info})
            return True
        trades = self._trades()
        sc, parts = score(self.rules, side, j, s, float(price), self._record_of(sig, trades))
        until = int(bar_close) + TF_MS[sig.timeframe]
        meta = {**sig.meta, "trend": {"htf": htf, "dir": side, "judge": j.text(self.rules), "strength": j.strength(side),
                                      "score": parts, "level": info["level"], "pullback_atr": info["pullback_atr"],
                                      "big_bar": info["big_bar"], "far_htf_atr": info["far_htf_atr"],
                                      "far_etf_atr": info["far_etf_atr"]}}
        # the judgment it entered on rides in ctx too: the trade record keeps ctx (the live site's 최근 거래)
        meta["ctx"] = {**(sig.meta.get("ctx") or {}), "trend": {"judge": j.text(self.rules), "score": float(sc), "htf": htf}}
        nsig = replace(sig, score=float(sc), meta=meta)
        label = sig.meta.get("member", sig.strategy_id)
        self.pulls.append({"member": label, "t0": int(ts), "until": until, "level": float(info["level"]),
                           "signal": dataclasses.asdict(nsig)})
        self._restate(sig, "WAITING", f"되돌림 기다림: {info['level']:.6g}까지({info['pullback_atr']:g} ATR"
                      + (", 장대봉이라 깊게" if info["big_bar"] else "") + f", {kst(until - MIN)}까지) · {j.text(self.rules)}",
                      extra={"trend": {**info, "score": sc, "score_parts": parts}})
        self._count(label, "waiting")
        return True

    def _after_step(self, ts: int, bars: dict) -> None:
        self._pullbacks(ts, bars)
        self._snapshot(ts)

    def _pullbacks(self, ts: int, bars: dict) -> None:
        """Minute ts traded at a waiting signal's pullback level -> its entry is the next minute (queued); past its
        entry bar it lapses. The signal's own minute (t0) is not looked at: its 1m bar began before the signal's
        price was taken, so a dip before the signal would count (review 10/21); the wait looks from t0 + 1 minute to
        the entry bar's last minute (``until`` - 1 minute)."""
        if not self.pulls:
            return
        keep, now, px = [], self.now_ms(), None
        for p in self.pulls:
            sig = C._sig_from(p["signal"])
            if p.get("member") not in self.by_label:
                self._restate(sig, "FILTERED", "설정이 바뀌어 기다리던 되돌림 신호를 버림", expect=("WAITING",))
                continue
            if ts >= int(p["until"]) - MIN:           # the entry bar's last minute: an entry then would open at the
                # next bar's close, where the same member's next signal has its own row; the wait ends one minute early
                self._restate(sig, "FILTERED", f"되돌림 안 옴({kst(int(p['until']) - MIN)}까지 {float(p['level']):.6g}에 안 닿음)",
                              expect=("WAITING",))
                self._count(p["member"], "no_pullback")
                continue
            bar = bars.get(sig.symbol)
            if ts <= int(p["t0"]) or bar is None:
                keep.append(p)
                continue
            lvl = float(p["level"])
            if not (bar.low <= lvl if sig.side > 0 else bar.high >= lvl):
                keep.append(p)
                continue
            entry_t = ts + MIN
            if now - entry_t > self.cfg.max_signal_age_s * 1000:
                self._restate(sig, "FILTERED", "되돌림 확인이 늦음(재시작 따라잡기)", expect=("WAITING",))
                continue
            if px is None:
                try:
                    px = self.prices()
                except Exception:  # noqa: BLE001  without a price the fill is the entry minute's open
                    px = {}
            bid, ask = px.get(sig.symbol, (None, None))
            ref = ask if sig.side > 0 else bid
            meta = {**sig.meta, "pulled": True, "ref_time": now, "delay_ms": now - entry_t, "pull_level": lvl,
                    "pull_minute": ts}
            meta.pop("ref_price", None)
            if ref is not None:
                meta["ref_price"] = float(ref)
            nsig = replace(sig, ts=entry_t - 1, meta=meta)
            self.queue.append(C.Queued(entry_t, dataclasses.asdict(nsig)))
            self._restate(sig, "BROKE", f"되돌림 확인: {lvl:.6g} 닿음 → 다음 분에 진입", expect=("WAITING",))
            self._log(nsig, "SUBMITTED", "rule", "되돌림 확인")
        self.pulls = keep

    # ---- the supervisor
    def _before_step(self, ts: int, bars: dict) -> None:
        r = self.rules
        for e in self.book.engines.values():
            p = e.position
            if (p is None or p.lock_roe is not None or p.symbol not in bars or int(ts) <= int(p.entry_time)
                    or not hasattr(e, "supervise")):
                continue
            tf = p.signal.timeframe
            tfm = TF_MS.get(tf)
            if tfm is None:
                continue
            if int(ts) >= int(p.entry_time) + r.time_bars * tfm:
                e.supervise("TIME", f"진입 봉 {r.time_bars}개({KO_TF.get(tf, tf)} {r.time_bars}개) 안에 첫 잠금 못 감")
                continue
            htf = HTF_OF.get(tf)
            if not r.judge_exit or htf is None:
                continue
            try:
                j = self.judge.judgment(p.symbol, htf, ts)
            except Exception as exc:  # noqa: BLE001  no exit (the stop protects); noted once per bar
                key = (p.symbol, htf, int(ts) - int(ts) % TF_MS[htf])
                if key not in self._jnoted:
                    self._jnoted.add(key)
                    self.store.alert(self.now_ms(), WARN, f"{self.cfg.tag} 감독: {p.symbol} {KO_TF[htf]} 판단을 못 읽음"
                                     f"(청산 판단 미룸): {exc}"[:300])
                continue
            finally:
                self._klines_errors()
            # against the direction the entry was judged with: the bot's own side; the coin-flip twin's random side
            # is no judgment of its own, so it closes at the same event as the bot (review 10/21)
            want = int(((p.signal.meta or {}).get("trend") or {}).get("dir") or p.side)
            if j.bar_close > int(p.entry_time) and j.raw == -want:
                e.supervise("JUDGE", f"{KO_TF[htf]} 판단이 {KO_DIR[j.raw]}로 바뀜({j.vote_text()})")

    # ---- what the live site shows
    def _snapshot(self, ts: int) -> None:
        """State ``trend``: every coin's 1h and 4h judgment, the waits and the pauses (the live minute only)."""
        now = self.now_ms()
        if now - int(ts) > 10 * MIN:
            return                                    # a catch-up: only the live minute is shown
        coins: dict = {}
        for sym in self.cfg.symbols:
            row = {}
            for tf in ("1h", "4h"):
                try:
                    row[tf] = self.judge.judgment(sym, tf, ts, bg=True).to_dict(self.rules)
                except Exception as exc:  # noqa: BLE001  shown as unreadable
                    row[tf] = {"error": str(exc)[:200]}
            coins[sym] = row
        self._klines_errors()
        key = (json.dumps(coins, sort_keys=True, default=str), len(self.pulls))
        if self._snap is not None and self._snap[0] == key and int(ts) - self._snap[1] < SNAP_EVERY_MS:
            return
        self._snap = (key, int(ts))
        pz = self.pauses(ts)
        waits = []
        for p in self.pulls:
            s = p["signal"]
            waits.append({"member": p["member"], "symbol": s["symbol"], "side": s["side"], "tf": s["timeframe"],
                          "level": p["level"], "until": p["until"], "t0": p["t0"],
                          "judge": (s.get("meta") or {}).get("trend", {}).get("judge")})
        self.store.put_state(STATE_TREND, int(ts), {
            "ts": int(ts), "coins": coins, "waits": waits, "since": self.since,
            "pauses": {"day": pz["day"], "members": pz["members"],
                       "coins": [[k[0], k[1], v[0], v[1]] for k, v in pz["coins"].items()]},
            "rules": self.rules.describe(), "numbers": dataclasses.asdict(self.rules)})
