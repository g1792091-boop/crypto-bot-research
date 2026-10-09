"""The 48 demo accounts (CONTRACT section 2), recomputed from the live start on every tick.

Every account trades the 7 coins of one strategy and timeframe (coin flips: one timeframe), one position per coin,
with four separate wallets (20/30/40/50x, $1,000 each). Sizing is the owners' rule (margin = L% of the wallet) with the
rule bot's entry checks, as the 5-year study's account simulation ('house' mode, exchange minimums on). Outcomes come
from the cell book (house exit at L with liquidation, or a fixed TP/stop pair); funding is the real Binance rate.
A wallet below $100 is ruined: recorded, then restarted at $1,000 (the record keeps the count).

Switching accounts keep their decisions in the database (table ``decisions``) so a restart replays the same history.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from . import exits as X
from . import grid as G
from . import store as ST

SEED = 1000.0
RUIN = 0.10
M15 = 15 * 60 * 1000
H4 = 4 * 3600 * 1000
WEEK_MS = 7 * 86400 * 1000
MONDAY0 = 1577664000000          # 2019-12-30 00:00 UTC, a Monday
MIN_POOLED, MIN_COIN = 200, 100  # study selection minimums (s3_select)
FRIEND_MIN_N = 20                # friend rule: trades of a candidate in the last 26 weeks (per coin)
FRIEND_WEEKS = 26
NOTIFY_KINDS = ("adaptive", "friend", "private")


@dataclass
class Acct:
    id: str
    kind: str          # fixed / adaptive / friend / flip
    sub: str           # default / friend / pick / r26 / r4 / r26c / wk / rule / flip
    name: str
    strat: Optional[str]
    tf: str
    rule_ko: str
    combo: Optional[int] = None
    extra: dict = field(default_factory=dict)

    @property
    def short(self):
        return G.SHORT.get(self.strat, "") if self.strat else ""

    @property
    def notify(self) -> bool:
        return self.kind in NOTIFY_KINDS or (self.kind == "fixed" and self.sub == "friend")


def tf_ko(tf: str) -> str:
    return {"15m": "15분", "30m": "30분"}[tf]


def all_accounts() -> list:
    out = []
    for strat in G.STRATS:
        sh = G.SHORT[strat]
        for tf in G.TFS:
            d = G.default_combo(strat)
            out.append(Acct(f"fx-def-{sh}-{tf}", "fixed", "default", f"{sh} 기본값 · {tf_ko(tf)}", strat, tf,
                            f"기본값 그대로 ({G.combo_label(strat, d)})", combo=d))
    for strat in G.STRATS:
        f = G.friend_combo(strat)
        if f is None:
            continue
        sh = G.SHORT[strat]
        for tf in G.TFS:
            out.append(Acct(f"fx-fr-{sh}-{tf}", "fixed", "friend", f"{sh} 친구 값 · {tf_ko(tf)}", strat, tf,
                            f"친구 값 그대로 ({G.combo_label(strat, f)})", combo=f))
    for strat in G.STRATS:
        sh = G.SHORT[strat]
        for tf in G.TFS:
            p = G.PICK[(strat, tf)]
            out.append(Acct(f"fx-pk-{sh}-{tf}", "fixed", "pick", f"{sh} 5년 1등 값 · {tf_ko(tf)}", strat, tf,
                            f"5년 시험(2021-23)에서 주변 평균 1등 ({G.combo_label(strat, p)})", combo=p))
    modes = (("r26", "자동 · 5거래마다(26주)", "5거래 끝날 때마다 최근 26주 기록에서 주변 평균 1등 값으로 (7코인 공통)"),
             ("r4", "자동 · 5거래마다(4주)", "5거래 끝날 때마다 최근 4주 기록에서 주변 평균 1등 값으로 (7코인 공통)"),
             ("r26c", "자동 · 5거래마다 코인별(26주)", "5거래 끝날 때마다 코인마다 그 코인의 최근 26주 1등 값으로"),
             ("wk", "자동 · 매주(26주)", "매주 월요일 09:00(한국)에 최근 26주 기록에서 주변 평균 1등 값으로 (7코인 공통)"))
    for sub, nm, rule in modes:
        for strat in G.STRATS:
            sh = G.SHORT[strat]
            for tf in G.TFS:
                out.append(Acct(f"ad-{sub}-{sh}-{tf}", "adaptive", sub, f"{sh} {nm} · {tf_ko(tf)}", strat, tf, rule))
    for strat in G.STRATS:
        sh = G.SHORT[strat]
        for tf in G.TFS:
            out.append(Acct(f"fr-{sh}-{tf}", "friend", "rule", f"{sh} 친구 규칙 · 매주 · {tf_ko(tf)}", strat, tf,
                            "매주 월요일, 코인·레버리지마다 최근 26주에 돈을 번 (값 x 익절·손절) 중 낙폭이 가장 작은 것을 "
                            "일주일 돌림 (번 것이 없으면 쉼)"))
    for tf in G.TFS:
        out.append(Acct(f"cf-{tf}", "flip", "flip", f"동전 던지기 · {tf_ko(tf)}", None, tf,
                        "아무 봉에서나 무작위 방향 (기본값과 같은 빈도), 사다리 청산: 운의 기준"))
    return out


ACCOUNTS = all_accounts()
BY_ID = {a.id: a for a in ACCOUNTS}
_PLUGIN_ACCTS: list = []


def current_accounts() -> list:
    """The 48 built-in accounts plus the private plug-in accounts loaded at the last refresh."""
    return ACCOUNTS + _PLUGIN_ACCTS


def by_id(aid: str) -> Acct:
    return BY_ID.get(aid) or next(a for a in _PLUGIN_ACCTS if a.id == aid)


def refresh_plugins(log=print) -> list:
    from . import plugins as PL
    accts = []
    for mod in PL.load(log=log):
        for spec in mod.ACCOUNTS:
            v = str(spec["variant"])
            accts.append(Acct(PL.account_id(mod, v), "private", mod.KEY, str(spec.get("name", f"비공개 {mod.KEY}"))[:60],
                              None, spec.get("tf", "15m"), str(spec.get("rule_ko", ""))[:300],
                              extra={"mod": mod, "variant": v}))
    _PLUGIN_ACCTS[:] = accts
    return accts


# ------------------------------------------------------------------ signal access
class Ctx:
    """Per-tick read access to the engine state for the accounts."""

    def __init__(self, eng, now_ms: int):
        self.eng = eng
        self.now = now_ms
        self.live0 = eng.live_start
        self.hist0 = eng.history_start
        self._live = {}

    def live_sigs(self, coin: str, tf: str, strat: str):
        """Signals with entry at/after the live start: (ts, combo, side)."""
        key = (coin, tf, strat)
        if key not in self._live:
            ts, cb, sd = self.eng.sigs[key].arrays()
            step = G.TF_MIN[tf] * 60000
            m = ts + step >= self.live0
            self._live[key] = (ts[m], cb[m], sd[m])
        return self._live[key]

    def combo_events(self, coin: str, tf: str, strat: str, combo: int):
        ts, cb, sd = self.live_sigs(coin, tf, strat)
        m = cb == combo
        return ts[m], sd[m]

    def cell(self, coin: str, tf: str, sig_ts: int, side: int):
        book = self.eng.books[(coin, tf)]
        k = book.index(np.array([sig_ts]))[0]
        if k < 0:
            return None
        s = 0 if side > 0 else 1
        return dict(F=book.F[k, s], T=book.T[k, s], raw=float(book.raw[k, s]), atr=float(book.atr[k]),
                    done=bool(book.done[k, s]))

    def coin_closed(self, coin: str, strat: str, tf: str, lo_ms: int):
        """Signals of one coin since lo_ms with their main-exit outcome: combo int16, R float32, exit end ms
        (only finished trades). Built per call, one coin at a time (memory)."""
        ts, cb, sd = self.eng.sigs[(coin, tf, strat)].arrays()
        a = int(np.searchsorted(ts, lo_ms))
        ts, cb, sd = ts[a:], cb[a:], sd[a:]
        book = self.eng.books[(coin, tf)]
        k = book.index(ts)
        ok = k >= 0
        cb, k, s = cb[ok], k[ok], np.where(sd[ok] > 0, 0, 1)
        R = book.F[k, s, ST.F_MAIN_R]
        reason = book.F[k, s, ST.F_MAIN_REASON]
        x = book.T[k, s, ST.T_MAIN]
        done = (reason != 3) & np.isfinite(R) & (x >= 0)
        return cb[done], R[done], x[done] + M15


# ------------------------------------------------------------------ switching rules
def repick(ctx: Ctx, strat: str, tf: str, T: int, weeks: int, coin: Optional[str] = None):
    """Study ROLL5 / WEEKLY re-pick (research/st_custom/s5_reopt.Data.repick): best plateau combo on trades closed in
    the trailing window, exit ends binned in 4-hour bins (bins ended by T). None if nothing is eligible."""
    b1 = (T // H4) * H4
    b0 = -(-(T - weeks * WEEK_MS) // H4) * H4
    nc = G.NCOMBO[strat]
    n = np.zeros(nc)
    sm = np.zeros(nc)
    # signals whose trades can end inside the window: at most 60 days before its start (longer trades are rare)
    lo_sig = b0 - 60 * 86400 * 1000
    for c_ in ([coin] if coin else G.COINS):
        cb, R, x_end = ctx.coin_closed(c_, strat, tf, lo_sig)
        # study: bin = (end of the exit bar) // 4h; bins in [b0, b1) count, i.e. exit ends in [b0, b1)
        m = (x_end >= b0) & (x_end < b1)
        n += np.bincount(cb[m].astype(np.int64), minlength=nc)
        sm += np.bincount(cb[m].astype(np.int64), weights=R[m].astype(np.float64), minlength=nc)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = sm / n
    sc = G.plateau(n, mean, strat, MIN_COIN if coin else MIN_POOLED)
    t = G.top(sc, 1)
    if not t:
        return None, {"n": 0}
    c = t[0]
    return c, {"score": float(sc[c]), "n": int(n[c]), "mean": float(mean[c])}


def friend_pick(ctx: Ctx, strat: str, tf: str, T: int, coin: str, levs=G.LEVS) -> dict:
    """Friend rule at T for one coin, every leverage in one pass: among (setting x exit) with >= FRIEND_MIN_N trades
    closed in the last 26 weeks that pass the entry checks at L, keep those whose compounded wallet (margin = L%
    per trade, signal by signal) ended above the start; pick the smallest drawdown (ties: larger return).
    Returns {L: ((combo, exit) | None, info)}."""
    eng = ctx.eng
    ts, cb, sd = eng.sigs[(coin, tf, strat)].arrays()
    lo = T - FRIEND_WEEKS * WEEK_MS
    a, b = np.searchsorted(ts, [lo - 30 * 86400 * 1000, T])
    ts, cb, sd = ts[a:b], cb[a:b].astype(np.int64), sd[a:b].astype(np.int64)
    out = {L: (None, {}) for L in levs}
    if not len(ts):
        return out
    book = eng.books[(coin, tf)]
    k = book.index(ts)
    ok = k >= 0
    ts, cb, sd, k = ts[ok], cb[ok], sd[ok], k[ok]
    s = np.where(sd > 0, 0, 1)
    raw = book.raw[k, s]
    atr = book.atr[k]
    fill = raw * (1 + sd * X.SLIP)
    order = np.lexsort((ts, cb))           # by combo, then time
    cb_o = cb[order]
    starts = np.flatnonzero(np.r_[True, cb_o[1:] != cb_o[:-1]])
    seg_combo = cb_o[starts]
    lens = np.diff(np.r_[starts, len(order)])
    segno = np.repeat(np.arange(len(starts)), lens).astype(float)
    ends = np.r_[starts[1:], len(order)] - 1
    best = {L: None for L in levs}
    okc = {}                               # entry checks depend only on the stop width and the leverage
    for e in range(G.NEXIT):
        kk = G.exit_stop_k(e)
        risk = np.abs(fill - (raw - sd * kk * atr))
        rf = risk / fill
        af = atr / fill
        if e == G.HALFBE:
            R_e = book.F[k, s, ST.F_HB_R].astype(float)
            x_e = book.T[k, s, ST.T_HB]
            dn_e = np.isfinite(R_e) & (x_e >= 0)
        elif e > 0:
            R_e = book.F[k, s, ST.F_TP_R + e - 1].astype(float)
            x_e = book.T[k, s, ST.T_TP + e - 1]
            dn_e = np.isfinite(R_e) & (x_e >= 0)
        for L in levs:
            if e == 0:
                li = G.LEVS.index(L)
                R = book.F[k, s, ST.F_L_R + li].astype(float)
                x = book.T[k, s, ST.T_L + li]
                dn = (book.F[k, s, ST.F_L_REASON + li] != 3) & (x >= 0)
            else:
                R, x, dn = R_e, x_e, dn_e
            x_end = np.where(dn, x + M15, -1)
            use = dn & (x_end <= T) & (x_end > lo) & np.isfinite(R)
            if (kk, L) not in okc:
                okc[(kk, L)] = X.check_ok_frac(coin, sd, rf, af, L)
            use &= okc[(kk, L)]
            r = np.where(use, np.maximum((L / 100.0) * np.maximum(R * L * rf, -1.0), -0.999), 0.0)
            lr = np.log1p(r)[order]
            n_seg = np.add.reduceat(use[order].astype(np.int64), starts)
            cs = np.cumsum(lr)
            base = np.r_[0.0, cs][starts]
            rel = cs - np.repeat(base, lens)
            tot = rel[ends]
            Kb = (np.abs(rel).max() + 10.0) * 4
            adj = rel + segno * Kb
            runmax = np.maximum(np.maximum.accumulate(adj), segno * Kb)
            mdd = 1.0 - np.exp(-np.maximum.reduceat(runmax - adj, starts))
            ret = np.expm1(tot)
            cand = np.flatnonzero((n_seg >= FRIEND_MIN_N) & (ret > 0))
            if not len(cand):
                continue
            j = cand[np.lexsort((seg_combo[cand], -ret[cand], mdd[cand]))[0]]
            key = (mdd[j], -ret[j], int(seg_combo[j]), e)
            if best[L] is None or key < best[L][0]:
                best[L] = (key, int(seg_combo[j]), e, int(n_seg[j]), float(ret[j]), float(mdd[j]))
    for L in levs:
        if best[L] is None:
            out[L] = (None, {"why": "none"})
        else:
            _k, c, e, n, ret, mdd = best[L]
            out[L] = ((c, e), {"n": n, "ret": ret, "mdd": mdd})
    return out


def mondays(t0: int, t1: int) -> list:
    """Monday 00:00 UTC times in (t0, t1]."""
    first = MONDAY0 + (-(-(t0 + 1 - MONDAY0) // WEEK_MS)) * WEEK_MS
    return list(range(first, t1 + 1, WEEK_MS))


# ------------------------------------------------------------------ decisions (switching accounts)
class Decider:
    """Replays a switching account's decision points from the live start and returns its timeline:
    list of (t_ms, {coin: combo}) for adaptive accounts. Cached decisions are reused (same seq and time)."""

    def __init__(self, ctx: Ctx, acct: Acct):
        self.ctx = ctx
        self.acct = acct
        self.cached = {}
        for d in ST.load_decisions(ctx.eng.conn, acct.id):
            self.cached.setdefault(d["seq"], {})[(d["coin"], d["L"])] = d
        self.new_rows = []
        self.switch_events = []

    def _decide_adaptive(self, seq: int, T: int, prev: dict) -> dict:
        a = self.acct
        got = self.cached.get(seq)
        if got and all(v["t_ms"] == T for v in got.values()):
            if ("ALL", 0) in got:
                return {c: got[("ALL", 0)]["combo"] for c in G.COINS}
            if all((c, 0) in got for c in G.COINS):
                return {c: got[(c, 0)]["combo"] for c in G.COINS}
        weeks = 4 if a.sub == "r4" else 26
        default = G.default_combo(a.strat)
        out, info = {}, {}
        if a.sub == "r26c":
            for coin in G.COINS:
                c, inf = repick(self.ctx, a.strat, a.tf, T, weeks, coin=coin)
                out[coin] = default if c is None else c
                info[coin] = inf
        else:
            c, inf = repick(self.ctx, a.strat, a.tf, T, weeks)
            for coin in G.COINS:
                out[coin] = default if c is None else c
                info[coin] = inf
        rows = []
        if a.sub == "r26c":
            for coin in G.COINS:
                rows.append((coin, out[coin], info[coin]))
        else:
            rows.append(("ALL", out[G.COINS[0]], info[G.COINS[0]]))
        for coin, c, inf in rows:
            ST.put_decision(self.ctx.eng.conn, a.id, seq, T, coin, 0, c, 0, inf)
            pc = prev.get(G.COINS[0] if coin == "ALL" else coin)
            if pc is not None and pc != c:
                self.switch_events.append(dict(t_ms=T, coin=coin, L=None, from_ko=G.combo_label(a.strat, pc),
                                               to_ko=G.combo_label(a.strat, c), why_ko=why_ko(a, inf)))
        return out

    def adaptive_timeline(self) -> list:
        """s5_reopt.run on the live period with the main-exit outcomes (signal level, one position per coin)."""
        ctx, a = self.ctx, self.acct
        T0, now = ctx.live0, ctx.now
        seq = 0
        active = self._decide_adaptive(seq, T0, {})
        timeline = [(T0, dict(active))]
        step = G.TF_MIN[a.tf] * 60000
        evs = {}

        def load_coin(coin, T):
            ts, sd = ctx.combo_events(coin, a.tf, a.strat, active[coin])
            e = ts + step
            m = e >= T
            evs[coin] = [e[m], ts[m], sd[m], 0]

        for coin in G.COINS:
            load_coin(coin, T0)
        busy = {c: -1 for c in G.COINS}
        heap = []
        closes = 0
        next_monday = mondays(T0, now + WEEK_MS)[0] if a.sub == "wk" else None
        while True:
            # next entry over coins
            nk, ncoin = None, None
            for ci, coin in enumerate(G.COINS):
                e, ts, sd, p = evs[coin]
                while p < len(e) and e[p] <= now:
                    if busy[coin] >= e[p]:
                        p += 1
                        continue
                    break
                evs[coin][3] = p
                if p < len(e) and e[p] <= now and (nk is None or e[p] < nk):
                    nk, ncoin = int(e[p]), coin
            hc = heap[0][0] if heap else None
            if a.sub == "wk" and next_monday is not None and next_monday <= now and \
                    (nk is None or next_monday <= nk) and (hc is None or next_monday <= hc):
                seq += 1
                prev = dict(active)
                active = self._decide_adaptive(seq, next_monday, prev)
                timeline.append((next_monday, dict(active)))
                for coin in G.COINS:
                    if active[coin] != prev[coin]:
                        load_coin(coin, next_monday)
                next_monday += WEEK_MS
                continue
            if hc is not None and (nk is None or hc < nk) and hc <= now:
                x_end, coin = heapq.heappop(heap)
                closes += 1
                if a.sub != "wk" and closes % 5 == 0:
                    seq += 1
                    prev = dict(active)
                    active = self._decide_adaptive(seq, x_end, prev)
                    timeline.append((x_end, dict(active)))
                    for c2 in G.COINS:
                        if active[c2] != prev[c2]:
                            load_coin(c2, x_end)
                continue
            if nk is None:
                break
            e, ts, sd, p = evs[ncoin]
            cell = ctx.cell(ncoin, a.tf, int(ts[p]), int(sd[p]))
            evs[ncoin][3] = p + 1
            if cell is None:
                continue
            reason = cell["F"][ST.F_MAIN_REASON]
            x = cell["T"][ST.T_MAIN]
            if reason != 3 and x >= 0:
                busy[ncoin] = int(x)           # exit bar open time; entries at/before it are skipped
                heapq.heappush(heap, (int(x) + M15, ncoin))
            else:
                busy[ncoin] = 2**62           # still open
        return timeline

    def friend_timelines(self) -> dict:
        """Weekly per-coin (combo, exit) or None for every leverage: {L: [(t_ms, {coin: pick | None})]}."""
        ctx, a = self.ctx, self.acct
        times = [ctx.live0] + mondays(ctx.live0, ctx.now)
        out = {L: [] for L in G.LEVS}
        prev = {L: None for L in G.LEVS}
        for seq, T in enumerate(times):
            got = self.cached.get(seq, {})
            cur = {L: {} for L in G.LEVS}
            for coin in G.COINS:
                need = []
                for L in G.LEVS:
                    d = got.get((coin, L))
                    if d is not None and d["t_ms"] == T:
                        cur[L][coin] = None if d["combo"] < 0 else (d["combo"], d["exit"])
                    else:
                        need.append(L)
                if not need:
                    continue
                picks = friend_pick(ctx, a.strat, a.tf, T, coin, levs=tuple(need))
                for L in need:
                    pick, inf = picks[L]
                    cur[L][coin] = pick
                    ST.put_decision(ctx.eng.conn, a.id, seq, T, coin, L, -1 if pick is None else pick[0],
                                    0 if pick is None else pick[1], inf)
                    old = None if prev[L] is None else prev[L].get(coin)
                    if prev[L] is not None and old != pick:
                        self.switch_events.append(dict(
                            t_ms=T, coin=coin, L=L, from_ko=setting_ko(a.strat, old),
                            to_ko=setting_ko(a.strat, pick), why_ko=friend_why(inf)))
            for L in G.LEVS:
                out[L].append((T, cur[L]))
                prev[L] = cur[L]
        return out


def setting_ko(strat: str, pick) -> str:
    if pick is None:
        return "쉼 (번 설정 없음)"
    c, e = pick
    return f"{G.combo_label(strat, c)} · {G.exit_ko(e)}"


def why_ko(a: Acct, inf: dict) -> str:
    if not inf or not inf.get("n"):
        return "조건을 채운 값이 없어 기본값"
    weeks = 4 if a.sub == "r4" else 26
    return f"최근 {weeks}주 주변 평균 1등 ({inf['score']:+.3f}R, {inf['n']:,}건)"


def friend_why(inf: dict) -> str:
    if not inf or "n" not in inf:
        return "최근 26주에 돈을 번 설정이 없어 쉼"
    return f"최근 26주 +{inf['ret'] * 100:.0f}% · 낙폭 {inf['mdd'] * 100:.0f}% ({inf['n']}건)"


# ------------------------------------------------------------------ wallet simulation of one line
def _funding_paid(eng, coin: str, e_ts: int, end_ts: int, side: int) -> Optional[float]:
    """Sum of side x rate over funding times in (e_ts, end_ts]; None when the funding data does not cover it."""
    fts, fr = eng.funding[coin]
    if not len(fts) or fts[-1] < min(end_ts, eng.clock_ms()) - 9 * 3600 * 1000:
        return None
    a, b = np.searchsorted(fts, [e_ts, end_ts], side="right")
    return float(side * fr[a:b].sum())


def _trade_outcome(ctx: Ctx, coin: str, tf: str, sig_ts: int, side: int, ex: int, L: int):
    """dict with fill, risk, stop, atr, roe (final or mark-to-market), R, done, x_ts, exit_raw, reason."""
    c = ctx.cell(coin, tf, sig_ts, side)
    if c is None or not np.isfinite(c["raw"]):
        return None
    raw, atr = c["raw"], c["atr"]
    if not (np.isfinite(atr) and atr > 0):
        return None
    fill = raw * (1 + side * X.SLIP)
    k = G.exit_stop_k(ex)
    stop0 = raw - side * k * atr
    risk = abs(fill - stop0)
    li = G.LEVS.index(L)
    b15 = ctx.eng.b15[coin]
    last_c = float(b15["c"][-1]) if len(b15["c"]) else raw
    if ex == 0:
        R = float(c["F"][ST.F_L_R + li])
        reason = int(c["F"][ST.F_L_REASON + li])
        x = int(c["T"][ST.T_L + li])
        done = reason != 3 and x >= 0
        exit_raw = float(c["F"][ST.F_L_EXIT + li]) if done else None
        if not np.isfinite(R):            # entry bar not closed yet: mark at the entry
            R = (-(X.TAKER * 2)) * fill / risk
        reason_s = {0: "stop", 1: "lock", 2: "liq"}.get(reason, "open")
    elif ex == G.HALFBE:
        R = float(c["F"][ST.F_HB_R])
        x = int(c["T"][ST.T_HB])
        done = np.isfinite(R) and x >= 0
        if done:
            gross = float(c["F"][ST.F_HB_G])
            exit_raw = float(c["F"][ST.F_HB_EXIT])
            reason_s = "tp" if gross > 0.9 else ("stop" if gross < -0.5 else "be")
        else:
            exit_raw = None
            reason_s = "open"
            held = max(1, int((ctx.now - (sig_ts + G.TF_MIN[tf] * 60000)) // M15))
            px = last_c * (1 - side * X.SLIP)
            roe_p = side * (px / fill - 1) - X.TAKER * (1 + px / fill) - X.F_BAR15 * held
            R = roe_p * fill / risk
    else:
        j = ex - 1
        R = float(c["F"][ST.F_TP_R + j])
        x = int(c["T"][ST.T_TP + j])
        done = np.isfinite(R) and x >= 0
        if done:
            gross = float(c["F"][ST.F_TP_G + j])
            is_tp = gross > 0
            xi = np.searchsorted(b15["ts"], x)
            xo = float(b15["o"][min(xi, len(b15["o"]) - 1)])
            exit_raw = X.tpsl_exit_price(raw, side, atr, j, xo, is_tp)
            reason_s = "tp" if is_tp else "stop"
        else:
            exit_raw = None
            reason_s = "open"
            held = max(1, int((ctx.now - (sig_ts + G.TF_MIN[tf] * 60000)) // M15))
            px = last_c * (1 - side * X.SLIP)
            roe_p = side * (px / fill - 1) - X.TAKER * (1 + px / fill) - X.F_BAR15 * held
            R = roe_p * fill / risk
    roe = max(R * L * risk / fill, -1.0)
    return dict(fill=fill, raw=raw, risk=risk, stop=stop0, atr=atr, roe=roe, R=R, done=done, x_ts=x if done else -1,
                exit_raw=exit_raw, reason=reason_s if done else "open")


def kst_day(t_ms: int) -> int:
    return (int(t_ms) + 9 * 3600 * 1000) // 86400000


class StopRules:
    """The real-money stop rules (CONTRACT 8.2), applied to NEW entries only: account -20% of the start -> no new
    entries ever again; realized P&L of the KST day <= -5% of the wallet at the day's first event -> none until the
    next KST day; 5 losing closes in a row -> none for 24 h after the 5th (the streak then starts again)."""
    HALT = 0.80
    DAY = 0.05
    STREAK = 5
    PAUSE_MS = 24 * 3600 * 1000

    def __init__(self, L: int):
        self.L = L
        self.halted_ms = None
        self.pause_until = -1
        self.day = None
        self.day_start_W = SEED
        self.day_pnl = 0.0
        self.day_block_until = -1
        self.streak = 0
        self.blocked = 0
        self.day_pauses = 0
        self.streak_pauses = 0
        self.events = []

    def _roll(self, t: int, W: float) -> None:
        d = kst_day(t)
        if d != self.day:
            self.day = d
            self.day_start_W = W
            self.day_pnl = 0.0

    def on_close(self, t: int, pnl: float, W_before: float, W_after: float) -> None:
        self._roll(t, W_before)
        self.day_pnl += pnl
        self.streak = self.streak + 1 if pnl < 0 else 0
        if self.streak >= self.STREAK:
            self.streak = 0
            self.pause_until = max(self.pause_until, t + self.PAUSE_MS)
            self.streak_pauses += 1
            self.events.append(dict(t_ms=int(t), L=self.L, what="streak", until_ms=int(self.pause_until),
                                    wallet=float(W_after)))
        if self.day_block_until < t and self.day_pnl <= -self.DAY * self.day_start_W:
            self.day_block_until = (self.day + 1) * 86400000 - 9 * 3600 * 1000
            self.day_pauses += 1
            self.events.append(dict(t_ms=int(t), L=self.L, what="day", until_ms=int(self.day_block_until),
                                    wallet=float(W_after)))
        if self.halted_ms is None and W_after <= self.HALT * SEED:
            self.halted_ms = int(t)
            self.events.append(dict(t_ms=int(t), L=self.L, what="halt", until_ms=None, wallet=float(W_after)))

    def block(self, e_ts: int, W: float) -> bool:
        self._roll(e_ts, W)
        if self.halted_ms is not None or e_ts < self.pause_until or e_ts < self.day_block_until:
            self.blocked += 1
            return True
        return False

    def summary(self) -> dict:
        return dict(blocked=self.blocked, halted_ms=self.halted_ms, day_pauses=self.day_pauses,
                    streak_pauses=self.streak_pauses)


def _parts(trades: list, unreal: float) -> dict:
    closed = [t for t in trades if t["status"] == "closed"]
    fees = sum(t.get("fee", 0.0) for t in closed)
    fund = sum(t.get("funding", 0.0) for t in closed)
    pnl = sum(t["pnl"] for t in closed)
    return dict(gross=pnl - fund + fees, fees=fees, funding=fund, open=unreal)


def simulate_line(ctx: Ctx, acct: Acct, L: int, events: list, rules: Optional[StopRules] = None,
                  cache: Optional[dict] = None) -> dict:
    """events: list of (e_ts, coin_i, sig_ts, side, combo, exit) sorted by (e_ts, coin_i). ``rules``: the stop-rule
    variant of the line (same entries, new entries blocked by the rules). ``cache``: trade outcomes shared between
    the plain and the stop-rule run of a line (an outcome does not depend on the wallet)."""
    eng = ctx.eng
    W = SEED
    peak = SEED
    used = np.zeros(len(G.COINS))
    busy = np.full(len(G.COINS), -1, np.int64)
    heap = []
    trades = []
    curve = [(ctx.live0, SEED)]
    st = dict(trades=0, wins=0, liqs=0, skipped=0, ruins=0, worst_streak=0, max_dd=0.0, sumR=0.0)
    streak = 0
    tf = acct.tf
    combos_strat = acct.strat

    def close_until(t):
        nonlocal W, peak, streak
        while heap and heap[0][0] < t:
            x_ts, ci, pnl, margin, tr = heapq.heappop(heap)
            W_before = W
            W += pnl
            if rules is not None:
                rules.on_close(x_ts + M15, pnl, W_before, W)
            used[ci] -= margin
            tr["status"] = "closed"
            st["trades"] += 1
            st["wins"] += pnl > 0
            st["liqs"] += tr["reason"] == "liq"
            st["sumR"] += tr["R"]
            streak = streak + 1 if pnl < 0 else 0
            st["worst_streak"] = max(st["worst_streak"], streak)
            t_end = x_ts + M15
            curve.append((t_end, W))
            if W > peak:
                peak = W
            st["max_dd"] = max(st["max_dd"], 1 - W / peak)
            if W < RUIN * SEED:
                st["ruins"] += 1
                tr["ruin"] = True
                W = SEED
                peak = SEED
                curve.append((t_end, W))

    for (e_ts, ci, sig_ts, side, combo, ex) in events:
        close_until(e_ts)
        if busy[ci] >= e_ts:
            st["skipped"] += 1
            continue
        coin = G.COINS[ci]
        if cache is not None:
            ck = (ci, sig_ts, side, ex)
            if ck not in cache:
                cache[ck] = _trade_outcome(ctx, coin, tf, sig_ts, side, ex, L)
            o = cache[ck]
        else:
            o = _trade_outcome(ctx, coin, tf, sig_ts, side, ex, L)
        if o is None:
            continue
        if rules is not None and rules.block(e_ts, W):
            continue
        ok, qty, margin, why = X.entry_check(coin, side, o["fill"], o["risk"], o["atr"], W, L)
        if not ok or used.sum() + margin > W + 1e-9:
            st["skipped"] += 1
            continue
        notional = qty * o["fill"]
        pnl = o["roe"] * margin
        fund = 0.0                                  # funding received (+) / paid (-) over the hold
        fee = notional * 2 * (X.TAKER + X.SLIP)     # taker fee and the assumed slippage, both sides
        if o["done"]:
            end = o["x_ts"] + M15
            held = (o["x_ts"] - e_ts) // M15 + 1
            if o["reason"] == "liq":
                fee = notional * (X.TAKER + X.SLIP)
            else:
                paid = _funding_paid(eng, coin, e_ts, end, side)
                if paid is not None:
                    pnl += notional * (X.F_BAR15 * held - paid)     # the cells hold the fixed rate: use the real one
                    fund = -notional * paid
                else:
                    fund = -notional * X.F_BAR15 * held
        used[ci] += margin
        tr = dict(key=f"{coin}|{tf}|{sig_ts}|{side}|{L}", L=L, coin=coin, side=int(side), signal_ms=int(sig_ts),
                  entry_ms=int(e_ts), entry=o["fill"], stop=o["stop"],
                  exit_ms=(o["x_ts"] + M15) if o["done"] else None, exit=o["exit_raw"],
                  status="closed" if o["done"] else "open", reason=o["reason"], pnl=pnl, roe=o["roe"], R=o["R"],
                  margin=margin, funding=fund, fee=fee, notional=notional, maker=False, risk=o["risk"],
                  combo=int(combo) if combo is not None else None, exit_i=int(ex),
                  setting_ko=(G.combo_label(combos_strat, combo) if combos_strat and combo is not None else "무작위"),
                  exit_ko=G.exit_ko(ex))
        trades.append(tr)
        if o["done"]:
            busy[ci] = o["x_ts"]
            heapq.heappush(heap, (int(o["x_ts"]), ci, float(pnl), float(margin), tr))
        else:
            busy[ci] = 2**62
            tr["unreal"] = pnl
    close_until(ctx.now + 1)
    unreal = sum(t.get("unreal", 0.0) for t in trades if t["status"] == "open")
    equity = W + unreal
    curve.append((ctx.now, equity))
    n = st["trades"]
    closed = [t for t in trades if t["status"] == "closed"]
    kst_day0 = ((ctx.now + 9 * 3600 * 1000) // 86400000) * 86400000 - 9 * 3600 * 1000
    today = sum(t["pnl"] for t in closed if t["exit_ms"] and t["exit_ms"] >= kst_day0)
    total_pnl = sum(t["pnl"] for t in closed) + unreal
    line = dict(equity=equity, wallet=W, pnl=total_pnl, pnl_pct=total_pnl / SEED * 100, today_pnl=today,
                trades=n, wins=st["wins"], win_rate=(st["wins"] / n if n else None),
                mean_R=(st["sumR"] / n if n else None), max_dd=st["max_dd"],
                open=sum(1 for t in trades if t["status"] == "open"), liqs=st["liqs"], skipped=st["skipped"],
                worst_streak=st["worst_streak"], ruined=st["ruins"] > 0, ruins=st["ruins"],
                parts=_parts(trades, unreal))
    out = dict(line=line, trades=trades, curve=curve)
    if rules is not None:
        out["rules"] = rules
    return out


def simulate_plugin_line(ctx: Ctx, acct: Acct, L: int, ptrades: list, rules: Optional[StopRules] = None) -> dict:
    """A private plug-in account line: the plug-in gives entries and exit legs (raw prices); sizing, entry checks,
    fees (maker for limit entries and take-profit legs, taker + slippage otherwise), real funding and the wallet are
    the same as every account."""
    eng = ctx.eng
    W = SEED
    peak = SEED
    used = np.zeros(len(G.COINS))
    busy = np.full(len(G.COINS), -1, np.int64)
    heap = []
    trades = []
    curve = [(ctx.live0, SEED)]
    st = dict(trades=0, wins=0, liqs=0, skipped=0, ruins=0, worst_streak=0, max_dd=0.0, sumR=0.0)
    streak = 0

    def close_until(t):
        nonlocal W, peak, streak
        while heap and heap[0][0] < t:
            x_ts, _n, ci, pnl, margin, tr = heapq.heappop(heap)
            W_before = W
            W += pnl
            if rules is not None:
                rules.on_close(x_ts + M15, pnl, W_before, W)
            used[ci] -= margin
            tr["status"] = "closed"
            st["trades"] += 1
            st["wins"] += pnl > 0
            st["liqs"] += tr["reason"] == "liq"
            st["sumR"] += tr["R"]
            streak = streak + 1 if pnl < 0 else 0
            st["worst_streak"] = max(st["worst_streak"], streak)
            curve.append((x_ts + M15, W))
            peak = max(peak, W)
            st["max_dd"] = max(st["max_dd"], 1 - W / peak)
            if W < RUIN * SEED:
                st["ruins"] += 1
                tr["ruin"] = True
                W = SEED
                peak = SEED
                curve.append((x_ts + M15, W))

    order = sorted(ptrades, key=lambda t: (int(t["entry_ms"]), G.COINS.index(t["coin"])))
    for n_, t in enumerate(order):
        e_ts = int(t["entry_ms"])
        if e_ts < ctx.live0 or e_ts > ctx.now:
            continue
        close_until(e_ts)
        coin = t["coin"]
        ci = G.COINS.index(coin)
        if busy[ci] >= e_ts:
            st["skipped"] += 1
            continue
        side = int(t["side"])
        maker = bool(t.get("maker_entry"))
        fill = float(t["entry"]) if maker else float(t["entry"]) * (1 + side * X.SLIP)
        stop = float(t["stop"])
        sdist = abs(fill - stop)
        if sdist <= 0:
            continue
        if rules is not None and rules.block(e_ts, W):
            continue
        atr = float(t["atr"]) if t.get("atr") else sdist / 2
        ok, qty, margin, _why = X.entry_check(coin, side, fill, sdist, atr, W, L)
        if not ok or used.sum() + margin > W + 1e-9:
            st["skipped"] += 1
            continue
        notional = qty * fill
        pnl = -(X.MAKER if maker else X.TAKER) * notional
        fee = (X.MAKER if maker else X.TAKER + X.SLIP) * notional
        b15 = eng.b15[coin]
        last_c = float(b15["c"][-1])
        legs = list(t["legs"])
        done = all(x[1] is not None for x in legs)
        kinds = [x[3] for x in legs if x[1] is not None]
        unreal = 0.0
        last_x = max([int(x[1]) for x in legs if x[1] is not None], default=None)
        exit_px = None
        for frac, xms, xpx, kind in legs:
            if xms is None:
                px = last_c * (1 - side * X.SLIP)
                part = frac * qty * side * (px - fill) - X.TAKER * frac * qty * px
                unreal += part
                pnl += part
            else:
                px = float(xpx) if kind == "tp" else float(xpx) * (1 - side * X.SLIP)
                pnl += frac * qty * side * (px - fill) - (X.MAKER if kind == "tp" else X.TAKER) * frac * qty * px
                fee += frac * qty * (X.MAKER * px if kind == "tp" else X.TAKER * px + abs(float(xpx) - px))
                exit_px = float(xpx)
        end = (last_x + M15) if done else ctx.now
        held = max(1, (end - e_ts) // M15)
        paid = _funding_paid(eng, coin, e_ts, end, side)
        fund = -notional * (paid if paid is not None else X.F_BAR15 * held)
        pnl += fund
        reason = "open"
        if done:
            reason = "stop" if "sl" in kinds else ("time" if "time" in kinds else ("be" if "be" in kinds else "tp"))
        if pnl < -margin:
            pnl = -margin
            reason = "liq" if done else reason
        R = pnl / (qty * sdist)
        used[ci] += margin
        tr = dict(key=f"{coin}|{acct.tf}|{int(t['signal_ms'])}|{side}|{L}", L=L, coin=coin, side=side,
                  signal_ms=int(t["signal_ms"]), entry_ms=e_ts, entry=fill, stop=stop,
                  exit_ms=end if done else None, exit=exit_px if done else None,
                  status="closed" if done else "open", reason=reason, pnl=pnl, roe=pnl / margin, R=R,
                  margin=margin, funding=fund, fee=fee, notional=notional, maker=maker, risk=sdist, combo=None,
                  exit_i=None,
                  setting_ko=str(t.get("setting_ko", ""))[:80], exit_ko=str(t.get("exit_ko", ""))[:80])
        trades.append(tr)
        if done:
            busy[ci] = last_x
            heapq.heappush(heap, (int(last_x), n_, ci, float(pnl), float(margin), tr))
        else:
            busy[ci] = 2**62
            tr["unreal"] = pnl
    close_until(ctx.now + 1)
    unreal = sum(t.get("unreal", 0.0) for t in trades if t["status"] == "open")
    equity = W + unreal
    curve.append((ctx.now, equity))
    n = st["trades"]
    closed = [t for t in trades if t["status"] == "closed"]
    kst_day0 = ((ctx.now + 9 * 3600 * 1000) // 86400000) * 86400000 - 9 * 3600 * 1000
    today = sum(t["pnl"] for t in closed if t["exit_ms"] and t["exit_ms"] >= kst_day0)
    total_pnl = sum(t["pnl"] for t in closed) + unreal
    line = dict(equity=equity, wallet=W, pnl=total_pnl, pnl_pct=total_pnl / SEED * 100, today_pnl=today,
                trades=n, wins=st["wins"], win_rate=(st["wins"] / n if n else None),
                mean_R=(st["sumR"] / n if n else None), max_dd=st["max_dd"],
                open=sum(1 for t in trades if t["status"] == "open"), liqs=st["liqs"], skipped=st["skipped"],
                worst_streak=st["worst_streak"], ruined=st["ruins"] > 0, ruins=st["ruins"],
                parts=_parts(trades, unreal))
    out = dict(line=line, trades=trades, curve=curve)
    if rules is not None:
        out["rules"] = rules
    return out


# ------------------------------------------------------------------ events per account
def _active_at(timeline: list, coin: str, e_ts: int):
    """Setting active for an entry at e_ts (decision at T applies to entries at/after T)."""
    cur = None
    for T, d in timeline:
        if T <= e_ts:
            cur = d.get(coin)
        else:
            break
    return cur


def flip_events(ctx: Ctx, tf: str, p: float) -> list:
    """Deterministic coin flips on every bar of the live period: probability p, random side."""
    out = []
    step = G.TF_MIN[tf] * 60000
    for ci, coin in enumerate(G.COINS):
        book = ctx.eng.books[(coin, tf)]
        ts = book.ts[book.ts + step >= ctx.live0]
        if not len(ts):
            continue
        h = ((ts // 60000).astype(np.uint64) * np.uint64(2654435761) + np.uint64(ci * 97 + (13 if tf == "30m" else 7)))
        h = (h ^ (h >> np.uint64(13))) * np.uint64(1274126177)
        u = (h % np.uint64(1_000_003)).astype(float) / 1_000_003
        v = ((h >> np.uint64(20)) % np.uint64(2)).astype(int)
        m = u < p
        for t, sv in zip(ts[m], v[m]):
            out.append((int(t + step), ci, int(t), 1 if sv else -1, None, 0))
    out.sort(key=lambda r: (r[0], r[1]))
    return out


def flip_rate(eng, tf: str) -> float:
    """Signals per bar per coin of the default settings over the history (the flips' frequency)."""
    tot_sig, tot_bars = 0, 0
    for coin in G.COINS:
        book = eng.books[(coin, tf)]
        tot_bars += len(book.ts)
        for strat in G.STRATS:
            ts, cb, _sd = eng.sigs[(coin, tf, strat)].arrays()
            tot_sig += int((cb == G.default_combo(strat)).sum())
    return (tot_sig / len(G.STRATS)) / tot_bars if tot_bars else 0.05


def account_events(ctx: Ctx, a: Acct, L: int, deciders: dict) -> tuple:
    """(events, settings_now list) of one account line."""
    step = G.TF_MIN[a.tf] * 60000
    ev = []
    now_settings = []
    if a.kind == "fixed":
        for ci, coin in enumerate(G.COINS):
            ts, sd = ctx.combo_events(coin, a.tf, a.strat, a.combo)
            for t, s in zip(ts, sd):
                ev.append((int(t + step), ci, int(t), int(s), a.combo, 0))
        now_settings = [dict(coin="ALL", L=None, setting_ko=G.combo_label(a.strat, a.combo), exit_ko=G.exit_ko(0))]
    elif a.kind == "adaptive":
        tl = deciders[a.id]["timeline"]
        for ci, coin in enumerate(G.COINS):
            ts, cb, sd = ctx.live_sigs(coin, a.tf, a.strat)
            if not len(ts):
                continue
            for T_i, (T, d) in enumerate(tl):
                T_next = tl[T_i + 1][0] if T_i + 1 < len(tl) else 2**62
                m = (cb == d[coin]) & (ts + step >= T) & (ts + step < T_next)
                for t, s in zip(ts[m], sd[m]):
                    ev.append((int(t + step), ci, int(t), int(s), int(d[coin]), 0))
        last = tl[-1][1]
        if a.sub == "r26c":
            now_settings = [dict(coin=c, L=None, setting_ko=G.combo_label(a.strat, last[c]), exit_ko=G.exit_ko(0))
                            for c in G.COINS]
        else:
            now_settings = [dict(coin="ALL", L=None, setting_ko=G.combo_label(a.strat, last[G.COINS[0]]),
                                 exit_ko=G.exit_ko(0))]
    elif a.kind == "friend":
        tl = deciders[a.id]["friend"][L]
        for ci, coin in enumerate(G.COINS):
            ts, cb, sd = ctx.live_sigs(coin, a.tf, a.strat)
            for T_i, (T, d) in enumerate(tl):
                pick = d.get(coin)
                if pick is None:
                    continue
                T_next = tl[T_i + 1][0] if T_i + 1 < len(tl) else 2**62
                c, e = pick
                m = (cb == c) & (ts + step >= T) & (ts + step < T_next)
                for t, s in zip(ts[m], sd[m]):
                    ev.append((int(t + step), ci, int(t), int(s), int(c), int(e)))
        last = tl[-1][1]
        for coin in G.COINS:
            pk = last.get(coin)
            now_settings.append(dict(coin=coin, L=L, setting_ko=(G.combo_label(a.strat, pk[0]) if pk else "쉼"),
                                     exit_ko=(G.exit_ko(pk[1]) if pk else "-")))
    else:
        p = ST.get_meta(ctx.eng.conn, f"flip_p_{a.tf}")
        if p is None:
            p = flip_rate(ctx.eng, a.tf)
            ST.set_meta(ctx.eng.conn, f"flip_p_{a.tf}", p)
        ev = flip_events(ctx, a.tf, float(p))
        now_settings = [dict(coin="ALL", L=None, setting_ko=f"무작위 (봉마다 {float(p) * 100:.1f}%)",
                             exit_ko=G.exit_ko(0))]
    ev.sort(key=lambda r: (r[0], r[1]))
    return ev, now_settings


def run_all(eng, now_ms: int, log=print) -> dict:
    """Every account and line. Returns {id: {acct, lines: {L: sim}, settings_now, decisions, switches_new}}."""
    ctx = Ctx(eng, now_ms)
    out = {}
    deciders = {}
    refresh_plugins(log=log)
    for a in _PLUGIN_ACCTS:
        try:
            pt = a.extra["mod"].trades(a.extra["variant"], eng.b15, ctx.live0, now_ms)
            lines = {L: simulate_plugin_line(ctx, a, L, pt) for L in G.LEVS}
            slines = {L: _slim(simulate_plugin_line(ctx, a, L, pt, rules=StopRules(L))) for L in G.LEVS}
        except Exception as exc:          # a broken plug-in never stops the engine
            log("plugin failed:", a.id, type(exc).__name__, str(exc)[:200])
            eng.issues.append(f"비공개 매매법 {a.sub} 계산 실패")
            lines = {L: simulate_plugin_line(ctx, a, L, []) for L in G.LEVS}
            slines = {L: _slim(simulate_plugin_line(ctx, a, L, [], rules=StopRules(L))) for L in G.LEVS}
        out[a.id] = dict(acct=a, lines=lines, lines_stop=slines, switches_new=[],
                         settings_now=[dict(coin="ALL", L=None, setting_ko=a.name, exit_ko=a.rule_ko[:60])])
    for a in sorted(ACCOUNTS, key=lambda x: (x.strat or "", x.tf)):
        if a.kind == "adaptive":
            dz = Decider(ctx, a)
            deciders[a.id] = {"timeline": dz.adaptive_timeline(), "dz": dz}
        elif a.kind == "friend":
            dz = Decider(ctx, a)
            deciders[a.id] = {"friend": dz.friend_timelines(), "dz": dz}
    for a in ACCOUNTS:
        lines = {}
        slines = {}
        settings = []
        for L in G.LEVS:
            ev, sn = account_events(ctx, a, L, deciders)
            cache = {}
            lines[L] = simulate_line(ctx, a, L, ev, cache=cache)
            slines[L] = _slim(simulate_line(ctx, a, L, ev, rules=StopRules(L), cache=cache))
            if a.kind == "friend":
                settings.extend(sn)
            elif L == G.LEVS[0]:
                settings = sn
        dz = deciders.get(a.id, {}).get("dz")
        out[a.id] = dict(acct=a, lines=lines, lines_stop=slines, settings_now=settings,
                         switches_new=(dz.switch_events if dz else []))
    return out


_SLIM_KEYS = ("entry_ms", "exit_ms", "status", "reason", "pnl", "R", "ruin")


def _slim(sim: dict) -> dict:
    """A stop-rule line keeps what the judgment and the comparison need (memory: one line per account line)."""
    sim["trades"] = [{k: t.get(k) for k in _SLIM_KEYS} for t in sim["trades"]]
    return sim


def decision_log(conn, a: Acct, limit: int = 200) -> list:
    """Switch history for the account page: consecutive decisions whose setting changed."""
    rows = ST.load_decisions(conn, a.id)
    out = []
    prev = {}
    for d in rows:
        key = (d["coin"], d["L"])
        cur = (d["combo"], d["exit"])
        if key in prev and prev[key] != cur:
            p = prev[key]
            if a.kind == "friend":
                f_ko = setting_ko(a.strat, None if p[0] < 0 else p)
                t_ko = setting_ko(a.strat, None if cur[0] < 0 else cur)
                why = friend_why(d["info"])
            else:
                f_ko, t_ko = G.combo_label(a.strat, p[0]), G.combo_label(a.strat, cur[0])
                why = why_ko(a, d["info"])
            out.append(dict(t_ms=d["t_ms"], coin=d["coin"], L=(d["L"] or None), from_ko=f_ko, to_ko=t_ko, why_ko=why))
        prev[key] = cur
    out.sort(key=lambda r: -r["t_ms"])
    return out[:limit]


def week_blocks(trades: list) -> tuple:
    """(n per week, sum R per week) of closed trades (Monday weeks), for the bootstrap."""
    wk = {}
    for t in trades:
        if t["status"] != "closed" or t["exit_ms"] is None:
            continue
        w = (t["entry_ms"] - MONDAY0) // WEEK_MS
        n, s = wk.get(w, (0, 0.0))
        wk[w] = (n + 1, s + t["R"])
    if not wk:
        return np.zeros(0), np.zeros(0)
    a = np.array(list(wk.values()), float)
    return a[:, 0], a[:, 1]


def boot_low(week_n: np.ndarray, week_s: np.ndarray, B: int = 1000, seed: int = 0) -> Optional[float]:
    """Week-block bootstrap 2.5th percentile of the pooled mean R (study common.boot_ci)."""
    ok = week_n > 0
    n, s = week_n[ok], week_s[ok]
    W = len(n)
    if W < 2:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, W, size=(B, W))
    return float(np.percentile(s[idx].sum(1) / n[idx].sum(1), 2.5))


def sanity() -> None:
    assert len(ACCOUNTS) == 48, len(ACCOUNTS)
    assert len({a.id for a in ACCOUNTS}) == 48
    assert math.isclose(SEED, 1000.0)
