"""The 'VWAP 개선판' world (owners 10-23, docs/vwap-bot-ko.md) for the live site's VWAP 봇 screens
(tests/test_dash_livevwap.py and the offline screenshots): the 추세판단 봇's paper and two executors as in
tests/test_dash_livebots_fees.py, plus the VWAP bot's own database made by the REAL bot code, and WOO X Pro switched to it.

- vwap.db: paperbot/combo.py ``ComboRunner`` with the owners' config (deploy/combo.vwap.json: F6_VWAP_FAIL 30m,
  S3_CMO_SANDWICH 1h, 2 ATR, margin 40 %, 30x, max_hold_bars 96, the pauses, the coin-flip twin), stepped minute by minute
  on a hand-made rule-bot database (1m bars and the rule bot's signal rows, store3's own writers). The entry gates are a
  stand-in (``PlanGates``, like tests/test_combo_vwap.py's Stub): per signal the reason and what the gates read, in the
  shape of paperbot/entrygates.EntryGates.check; the weekend and the NYSE open are the runner's own checks. The
  picture of every coin (state ``gates_now``) is made by the real ``entrygates.picture`` over real ``EntryGates`` (the
  trend judge on synthetic 4h bars, the ATR% gate on synthetic 30m / 1h bars), written by the runner itself.
- The executors (paperbot/executor.py ExecStore, the fees world's writers): 바이비트 follows the trend bot all along;
  WOO X Pro (slot "mexc") followed the trend bot, then its start at ``SWITCH`` names vwap.db (deploy/vwap_switch.py's
  config: signal light 20 / 75 %, ladder_from own): it follows four VWAP trades, misses one (late), holds the open one.
- livecheck.db ``missed`` per the Telegram side's contract (column ``paper`` = 'vwap', keys 'vwap#…', group 'gate' with
  why_kind gate_vote / gate_vol / gate_unread, detail keeps the gates read), written with livemissed's own schema.

Times are KST (``K(day, hour, minute)``, day 0 = Wednesday 10/21/2026); NOW = Tuesday 10/27 12:00 KST.

VWAP paper (COMBO@mix, $1,000):
  E1 BTC long  VWAP 30m  10/23 10:00  +0.8 % then back      -> LOCK (~+15 %)        vote 같은 방향 · ATR 0.42 / 0.61
  F1 ETH short VWAP 30m  10/23 10:30  in position           -> SKIPPED
  F2 SOL long  CMO 1h    10/23 11:00  4h vote against       -> FILTERED (gate_vote)
  E2 ETH short VWAP 30m  10/23 13:30  ETH +1.6 %            -> SL (~−43 %)          vote 보류 · ATR 0.38 / 0.52
  F3 DOGE long VWAP 30m  10/23 14:00  ATR above its point   -> FILTERED (gate_vol)
  E3 LTC long  VWAP 30m  10/23 15:00  +0.3 % in 48 h        -> TIME 10/25 15:00 (~+4.8 %)
  F4 BCH long  VWAP 30m  10/24 12:00  Saturday              -> FILTERED (주말, the runner's own)
  F5 BTC short VWAP 30m  10/26 09:30  30m bars unread       -> FILTERED (gate_unread)
  E4 BCH long  CMO 1h    10/26 10:00  −0.8 %, +1.8 %, back  -> LOCK (~+20 %, after −28 % first)   WOO X Pro follows
  E5 SOL short VWAP 30m  10/26 17:30  −0.65 % then back     -> LOCK            WOO X Pro follows
  F6 BTC long  VWAP 30m  10/26 22:30  NYSE open             -> FILTERED (나스닥, the runner's own)
  E6 ETH long  VWAP 30m  10/26 23:30  +0.7 % then back      -> LOCK            WOO X Pro misses it (late)
  L1 SOL long  VWAP 30m  10/27 01:00  seen 4 minutes late   -> REJECTED late
  E7 DOGE short VWAP 30m 10/27 07:00  DOGE +1.5 %           -> SL              WOO X Pro follows
  E8 BTC long  CMO 1h    10/27 11:00  +0.3 % by now         -> open            WOO X Pro holds it
  F7 ETH long  VWAP 30m  10/27 11:30  in position           -> SKIPPED
"""
from __future__ import annotations

from typing import Optional

import dataclasses
import json
import os
import sqlite3

import numpy as np

from paperbot import combo as C
from paperbot import entrygates as G
from paperbot.executor import ExecStore
from paperbot.notify import ListNotifier
from paperbot.store3 import Store3
from paperbot.trendjudge import Judge, Klines, TrendRules
from tests import test_dash_livebots_fees as FW
from tests.test_combo import BRACKETS, PX, SPECS

MIN, H, DAY = 60_000, 3_600_000, 86_400_000
KST0 = FW.KST0                                  # 2026-10-21 00:00 KST (a Wednesday)
NOW = FW.NOW                                    # 10/27 (Tuesday) 12:00 KST
ACC, FLIP = C.ACCOUNT, C.FLIP_ACCOUNT
SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
ATR_FRAC = 0.0065                               # the signal bar's ATR: 2 ATR = 1.3 % (about −43 % net ROE at 30x)
VWAP, CMO = ("F6_VWAP_FAIL", "30m"), ("S3_CMO_SANDWICH", "1h")
M30, H4 = 30 * MIN, 4 * H


def K(day: int, hour: int, minute: int = 0) -> int:
    """A KST moment: ``day`` days after Wednesday 10/21/2026 00:00 KST."""
    return KST0 + day * DAY + hour * H + minute * MIN


VS = K(2, 9)                                    # the VWAP bot's first start (Friday 10/23 09:00 KST)
SWITCH = K(5, 8)                                # WOO X Pro's start that names vwap.db (Monday 10/26 08:00 KST)
PIC_AT = K(6, 11, 51)                           # the picture of every coin (the runner's first live minute 11:50, for 11:51)


def _gi(raw, with_side, up, down, tf, atr, q):
    """What the gates read (paperbot/entrygates.EntryGates.check's info), in its own words."""
    vote = {"tf": "4h", "bar_close": None, "votes": {}, "up": up, "down": down, "raw": raw, "with_side": with_side,
            "text": G.vote_words("4h", raw, up, down)}
    out = {"vote": vote}
    if atr is not None:
        v = {**G.VOL_DEFAULT}
        out["vol"] = {"tf": tf, "atr_pct": atr, "q_pct": q, "days": 30, "q": 0.8,
                      "text": G.vol_words(tf, atr / 100, (q / 100) if q is not None else float("nan"), v)}
    return out


# (name, member, symbol, side, bar close, gates' reason, what they read, price path after the entry [(minutes, total move)])
PLAN = [
    ("E1", VWAP, "BTCUSDT", 1, K(2, 10), "", _gi(1, 1, 3, 0, "30m", 0.42, 0.61), [(40, 0.008), (40, -0.0045)]),
    ("F1", VWAP, "ETHUSDT", -1, K(2, 10, 30), "", _gi(-1, 1, 0, 3, "30m", 0.35, 0.5), []),
    ("F2", CMO, "SOLUSDT", 1, K(2, 11), "4시간 추세 반대: 상승 0·하락 3·중립 1", _gi(-1, -1, 0, 3, "1h", None, None), []),
    ("E2", VWAP, "ETHUSDT", -1, K(2, 13, 30), "", _gi(0, 0, 2, 1, "30m", 0.38, 0.52), [(60, 0.016)]),
    ("F3", VWAP, "DOGEUSDT", 1, K(2, 14), "변동성 높음: ATR 0.912% > 지난 30일 80% 위치 0.655%",
     _gi(1, 1, 3, 0, "30m", 0.912, 0.655), []),
    ("E3", VWAP, "LTCUSDT", 1, K(2, 15), "", _gi(1, 1, 4, 0, "30m", 0.30, 0.48), [(2880, 0.003)]),
    ("F4", VWAP, "BCHUSDT", 1, K(3, 12), "", _gi(1, 1, 3, 0, "30m", 0.3, 0.5), []),
    ("F5", VWAP, "BTCUSDT", -1, K(5, 9, 30), "변동성 판단에 쓸 30분봉을 못 읽음(진입 안 함): BTCUSDT 30m 봉을 못 받음: OSError: down",
     _gi(0, 0, 2, 1, "30m", None, None), []),
    ("E4", CMO, "BCHUSDT", 1, K(5, 10), "", _gi(1, 1, 3, 1, "1h", 0.55, 0.70), [(30, -0.008), (120, 0.018), (60, -0.006)]),
    ("E5", VWAP, "SOLUSDT", -1, K(5, 17, 30), "", _gi(0, 0, 1, 2, "30m", 0.61, 0.70), [(40, -0.0065), (40, 0.004)]),
    ("F6", VWAP, "BTCUSDT", 1, K(5, 22, 30), "", _gi(1, 1, 3, 0, "30m", 0.3, 0.5), []),
    ("E6", VWAP, "ETHUSDT", 1, K(5, 23, 30), "", _gi(1, 1, 4, 0, "30m", 0.40, 0.55), [(40, 0.007), (40, -0.004)]),
    ("L1", VWAP, "SOLUSDT", 1, K(6, 1), "", _gi(0, 0, 1, 1, "30m", 0.3, 0.5), []),
    ("E7", VWAP, "DOGEUSDT", -1, K(6, 7), "", _gi(-1, 1, 0, 3, "30m", 0.50, 0.66), [(60, 0.015)]),
    ("E8", CMO, "BTCUSDT", 1, K(6, 11), "", _gi(0, 0, 2, 0, "1h", 0.33, 0.58), [(55, 0.003)]),
    ("F7", VWAP, "ETHUSDT", 1, K(6, 11, 30), "", _gi(1, 1, 3, 0, "30m", 0.3, 0.5), []),
]
LATE = {"L1"}                                   # seen 4 minutes after its close (a restart's catch-up): REJECTED late


class PlanGates:
    """The entry gates as the plan says (the shape of entrygates.EntryGates.check: reason, what they read)."""

    def __init__(self, plan):
        self.by = {(sym, tf, side, bc): (why, info) for _n, (_s, tf), sym, side, bc, why, info, _p in plan}
        self.asked = []

    def check(self, symbol, tf, side, bar_close):
        self.asked.append((symbol, tf, side, bar_close))
        why, info = self.by.get((symbol, tf, int(side), int(bar_close)), ("", {}))
        return why, json.loads(json.dumps(info))

    def block(self, symbol, tf, side, bar_close):
        return self.check(symbol, tf, side, bar_close)[0]


# ================================================================ the rule bot's database and the runner
class Rule:
    """The rule bot's paper3.db (store3's writers): 1m bars of the six coins and its signal rows."""

    def __init__(self, path):
        self.path = path
        self.s = Store3(path)
        self.px = dict(PX)
        self.t = None
        self.moves: list = []               # [(symbol, from ms, to ms, move a minute)]

    def bars_to(self, end):
        """1m bars from the last one written to ``end`` (exclusive), each coin moving as the plan's paths say."""
        rows = []
        t = self.t
        while t < end:
            for s in SYMS:
                step = sum(m for sym, a, b, m in self.moves if sym == s and a <= t < b)
                o = self.px[s]
                c = o * (1 + step)
                rows.append({"ts": t, "symbol": s, "open": o, "high": max(o, c) * 1.00005, "low": min(o, c) * 0.99995, "close": c,
                             "volume": 10.0, "mark_open": o, "mark_high": max(o, c), "mark_low": min(o, c), "mark_close": c,
                             "close_time": t + MIN - 1, "processed_at": t + MIN + 5000})
                self.px[s] = c
            t += MIN
        if rows:
            self.s.live_bars(rows)
            self.s.commit()
        self.t = end

    def signal(self, member, sym, side, bar_close, late=False):
        strat, tf = member
        ref = self.px[sym]
        self.s.log_signals([{"bar_close": bar_close, "timeframe": tf, "strategy": strat, "symbol": sym, "side": side,
                             "atr": ref * ATR_FRAC, "ref_price": ref, "ref_time": bar_close + 20_000, "delay_ms": 20_000,
                             "status": "SUBMITTED", "data": {"ctx": {}}}])
        self.s.commit()


def vwap_config(rule_db: str, vwap_db: str) -> dict:
    """The owners' config file (deploy/combo.vwap.json) on this world's files, no Telegram."""
    with open(os.path.join(FW.ROOT, "deploy", "combo.vwap.json"), encoding="utf-8") as fh:
        raw = json.load(fh)
    return {**raw, "paper_db": rule_db, "db": vwap_db, "telegram": False}


# ---------------------------------------------------------------- the picture of every coin (state gates_now)
def _rows(n, end_open, step, drift, seed, spike=None, wide=0.002):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.002, n)))
    o = np.r_[c[0], c[:-1]]
    w = np.abs(rng.normal(0, wide, n)) + 0.001
    if spike is not None:
        w[-spike:] *= 6
    h, lo = np.maximum(o, c) * (1 + w), np.minimum(o, c) * (1 - w)
    v = 100 + 50 * (c > o)
    t = end_open - (n - 1 - np.arange(n)) * step
    return [[int(t[i]), float(o[i]), float(h[i]), float(lo[i]), float(c[i]), float(v[i])] for i in range(n)]


def picture_gates(at: int) -> G.EntryGates:
    """Real entry gates on synthetic bars, one feed per coin: BTC 4h up (calm), ETH 4h down with its 30m ATR in its top
    20 %, SOL flat, DOGE too few 4h bars (the vote unread), LTC 4h down with its 1h ATR high, BCH 4h up with its 30m / 1h
    bars failing (the ATR% unread; the bars' back-off makes the 1h wait too, as on the server)."""
    last4 = at - at % H4 - H4
    plan4 = {"BTCUSDT": (400, 0.01), "ETHUSDT": (400, -0.01), "SOLUSDT": (400, 0.0), "DOGEUSDT": (60, 0.01), "LTCUSDT": (400, -0.01),
             "BCHUSDT": (400, 0.008)}
    k4 = {s: _rows(n, last4, H4, d, 11 + i) for i, (s, (n, d)) in enumerate(plan4.items())}
    # (30m: seed, spike) and (1h: seed, spike); None = the feed fails (seeds picked so a calm one is under its 80 % point)
    vol = {"BTCUSDT": ((2, None), (1, None)), "ETHUSDT": ((7, 3), (2, None)), "SOLUSDT": ((3, None), (3, None)),
           "DOGEUSDT": ((4, None), (5, None)), "LTCUSDT": ((5, None), (6, 3)), "BCHUSDT": (None, None)}
    feeds = {}
    for s in SYMS:
        for tf, step, n, x in (("30m", M30, 2000, vol[s][0]), ("1h", H, 1200, vol[s][1])):
            feeds[(s, tf)] = None if x is None else _rows(n, at - at % step - step, step, 0.0, x[0], spike=x[1])

    def bars(symbol, tf, start, limit):
        rows = feeds[(symbol, tf)]
        if rows is None:
            raise OSError("down")
        return [r for r in rows if r[0] >= start][:limit]
    clock = lambda: at + 5_000                                            # noqa: E731
    judge = Judge(Klines(lambda s, tf, n: [r for r in k4[s] if r[0] <= at][-n:], clock), TrendRules(vote_min=3))
    return G.EntryGates(vote={"tf": "4h", "vote_min": 3}, vol={"atr": 14, "days": 30, "q": 0.8}, judge=judge,
                        bars=G.BarCache(bars, clock))


def vwap_db(folder: str, plan=PLAN, until: int = NOW, picture: bool = True, name: str = "vwap.db",
            extra: Optional[dict] = None) -> dict:
    """vwap.db by the real runner (module docstring); {"path", "rule", "cfg", "runner"}. ``name`` / ``extra``: another
    database of the same bot with config keys changed (a shadow, tests/test_vwap_shadow.py)."""
    rule = Rule(os.path.join(folder, "rule-paper3.db"))
    path = os.path.join(folder, name)
    raw = {**vwap_config(rule.path, path), **(extra or {})}
    cfg = C.ComboConfig.from_dict(raw)
    assert cfg.problems() == [], cfg.problems()
    clock = [VS - 10 * MIN]
    rule.t = VS - 20 * MIN
    rule.bars_to(VS - 10 * MIN)                                          # the rule bot is already running
    members = C.resolve_members(cfg.members, core=["S3_CMO_SANDWICH"])
    store = Store3(cfg.db)
    note = ListNotifier()
    book = C.build_book(cfg, C.settings_of(cfg), BRACKETS, store, note, SPECS)
    gates = PlanGates(plan)
    run = C.ComboRunner(cfg, members, book, store, note, None, now_ms=lambda: clock[0], prices=lambda: {}, gates=gates)
    store.put_state("combo_run", VS, {"version": C.VERSION, "brackets": "example", "taker_fee": C.settings_of(cfg).taker_fee,
                                      "members": [m.describe() for m in members], "config": dataclasses.asdict(cfg)})
    store.commit()

    def step_to(t, now=None):
        rule.bars_to(t)
        clock[0] = (t + 5_000) if now is None else now
        while run.poll():                                               # at most 600 minutes a poll (catch-up)
            pass
    clock[0] = VS + 5_000
    run.poll()                                                           # the first start: from the rule bot's latest minute
    events = sorted(plan, key=lambda x: x[4])
    for name, member, sym, side, bc, _why, _info, moves in events:
        if bc > until:
            break
        step_to(bc)                                                      # up to the signal's close
        rule.signal(member, sym, side, bc)
        if name in LATE:
            step_to(bc + MIN, now=bc + 4 * MIN)                          # seen four minutes late: refused as late
        else:
            step_to(bc + MIN)                                            # the minute that opens at its close: entered
        t = bc + MIN
        for minutes, move in moves:                                      # its price path after the entry
            rule.moves.append((sym, t, t + minutes * MIN, move / minutes))
            t += minutes * MIN
    if picture:                                                          # the picture of every coin, by the runner itself
        run.picture_gates = picture_gates(PIC_AT)                        # (its first live minute: 10 minutes before now)
    step_to(until - MIN, now=until - 40_000)
    store.close()
    rule.s.close()
    # the accounts' first record: the bot's first start (the runner's book stamps the wall clock; the world's clock is VS)
    c = sqlite3.connect(path)
    try:
        c.execute("UPDATE accounts SET created_ts = ?", (VS,))
        c.commit()
    finally:
        c.close()
    return {"path": path, "rule": rule.path, "cfg": raw}


# ================================================================ the executors and the live checks
def paper_trades(path: str, account: str = ACC) -> list:
    """The closed trades of an account in a paper database (the engine's own records), oldest first."""
    c = sqlite3.connect(path)
    try:
        rows = c.execute("SELECT id, data FROM trades WHERE account_id = ? ORDER BY exit_time, id", (account,)).fetchall()
    finally:
        c.close()
    return [{**json.loads(d), "id": i} for i, d in rows]


def paper_position(path: str) -> dict:
    c = sqlite3.connect(path)
    try:
        d = json.loads(c.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()[0])
    finally:
        c.close()
    return d["engines"][ACC]["position"]


def exec_db(path: str, cfg_path: str, exchange: str, paper: str, closed: list, *, vwap: str = None, switch: int = None,
            vwap_closed: list = (), late: list = (), open_pos: dict = None, light=(20, 0.85), extra: dict = None) -> dict:
    """An executor's database (ExecStore, the fees world's ``_live`` for every close) and its config: ``closed`` the trend
    paper trades it followed, then with ``switch`` a start naming ``vwap`` and the VWAP paper trades it followed; ``late``
    the VWAP paper trades it saw too late (the executor's own WARN event with the key); ``open_pos`` the VWAP position it
    holds now."""
    st = ExecStore(path, lock=False)
    st.put_state("meta", KST0 - 10 * DAY, {"mode": "mainnet", "account": ACC, "exchange": exchange})
    st.event(KST0 - 10 * DAY, "INFO", "start", "시작", {"paper_db": paper})
    out = [FW._live(st, pt, FW.WOO_TAKER if exchange == "wooxpro" else FW.BYBIT_TAKER, fid=100 * (i + 1)) for i, pt in enumerate(closed)]
    if switch is not None:
        st.event(switch, "INFO", "start", f"시작: paper 계좌 {ACC} 따라 하기 (페이퍼 DB {vwap}), mainnet", {"paper_db": vwap})
    out += [FW._live(st, pt, FW.WOO_TAKER, fid=1000 + 100 * i) for i, pt in enumerate(vwap_closed)]
    for pt in late:
        st.event(pt["entry_time"] + 4 * MIN, "WARN", "late", "paper 진입이 240초 전이라 따라 하지 않습니다",
                 {"key": f"{ACC}|{pt['symbol']}|{pt['entry_time']}"})
    trade = None
    if open_pos:
        p = open_pos
        e = p["entry_price"] * (1 + p["side"] * 0.0003)
        trade = {"key": f"{ACC}|{p['symbol']}|{p['entry_time']}", "symbol": p["symbol"], "side": p["side"], "qty": 10.0 * p["leverage"] / e,
                 "leverage": p["leverage"], "stop": p["stop_price"], "stop_initial": p["stop_price"], "status": "open",
                 "entry_ts": p["entry_time"] + 4_000, "entry_price": e, "entry_time": p["entry_time"], "paper_entry": p["entry_price"],
                 "mode": "mainnet", "stop_algo_id": "w1"}
        st.trade_open(trade)
    eq = 100.0 + sum(x["pnl"] for x in out)
    st.equity(KST0 - 5 * DAY, 100.0, 100.0, 0.0)
    st.equity(NOW - H, eq, eq, 0.0)
    st.put_state("bot", NOW - 5_000, {"trade": trade, "done": [], "loops": 9000, "mode": "mainnet", "account": ACC,
                                      "risk": {"halted": False, "halt_reason": "", "consecutive_losses": 0, "last_equity": eq}})
    st.close()
    cfg = {"account": ACC, "paper_db": vwap if switch is not None else paper, "db": path, "exchange": exchange, "mode": "mainnet",
           "qty_scale": 0.025, "signal_light_n": light[0], "signal_light_min_win": light[1], **(extra or {})}
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)
    return {"live": out, "trade": trade}


def missed_db(path: str, rows: list, paper_col: bool = True) -> str:
    """livecheck.db ``missed`` made with paperbot/livemissed.py's own schema (``_schema``), plus the contract's column
    ``paper`` when ``paper_col`` (the Telegram side's next version); ``rows`` [{column: value}]."""
    from paperbot import livemissed as LM
    conn = sqlite3.connect(path)
    try:
        LM._schema(conn)                              # since the Telegram side's VWAP rows: with the column ``paper``
        have = {r[1] for r in conn.execute("PRAGMA table_info(missed)")}
        if paper_col and "paper" not in have:
            conn.execute("ALTER TABLE missed ADD COLUMN paper TEXT")
        if not paper_col and "paper" in have:         # an older livecheck.db (before that version): no such column
            conn.execute("ALTER TABLE missed DROP COLUMN paper")
        for r in rows:
            row = {"t": r["step_ts"], "member": None, "strategy": None, "tf": None, "why": r.get("why_kind"), "sims": 1,
                   "first_ts": NOW - H, "updated_ts": NOW - MIN, "signal": "{}", "grp": "one", **r}
            cols = [c for c in row if paper_col or c != "paper"]
            conn.execute(f"INSERT INTO missed ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [row[c] for c in cols])
        conn.execute("INSERT OR REPLACE INTO missed_meta VALUES (?,?,?)", ("pass", NOW - MIN, json.dumps({"state": "ok"})))
        conn.execute("INSERT OR IGNORE INTO missed_meta VALUES (?,?,?)", ("first", VS, json.dumps({"since": VS})))
        conn.commit()
    finally:
        conn.close()
    return path


def missed_rows(plan_by: dict, vt: dict) -> list:
    """The watcher's rows for this world: the VWAP bot's (paper 'vwap', keys 'vwap#…') blocked by each gate, by the
    pauses, by the one position, an executor's miss, and one of the trend bot's (paper NULL: never on the VWAP screens)."""
    def sig(name, grp, kind, state, roe, why, reason="LOCK", **kw):
        _n, (strat, tf), sym, side, bc, _w, info, _p = plan_by[name]
        member = f"{strat}@{tf}"
        closed = state == "closed"
        return {"key": f"vwap#{member}|{sym}|{bc}", "t": bc, "step_ts": bc, "member": member, "strategy": strat, "tf": tf,
                "symbol": sym, "side": side, "why_kind": kind, "why": why, "state": state, "grp": grp, "paper": "vwap",
                "entry_ts": bc, "entry_price": 100.0, "leverage": 30, "margin": 400.0, "roe_net": roe, "pnl": 400.0 * roe if roe is not None else None,
                "exit_ts": bc + 2 * H if closed else None, "reason": reason if closed else None, "last_ts": bc + 90 * MIN,
                "detail": json.dumps({"gates": info, "why_raw": why}, ensure_ascii=False), **kw}
    e6 = vt["E6"]
    return [
        sig("F2", "gate", "gate_vote", "closed", 0.121, "4시간 추세 반대: 상승 0·하락 3·중립 1"),
        sig("F3", "gate", "gate_vol", "closed", -0.43, "변동성 높음: ATR 0.912% > 지난 30일 80% 위치 0.655%", reason="SL"),
        sig("F5", "gate", "gate_unread", "open", -0.05, plan_by["F5"][5]),
        sig("F4", "pause", "weekend", "closed", 0.104, "주말(한국 시간 토·일) 진입 안 함"),
        sig("F6", "pause", "usopen", "no_data", None, "나스닥 개장 앞 30분·뒤 30분 진입 안 함"),
        sig("F1", "one", "held", "closed", 0.11, "포지션 있음 (한 번에 하나)"),
        {"key": f"vwap#exec|mexc|{e6['id']}", "t": e6["entry_time"], "step_ts": e6["entry_time"], "member": "F6_VWAP_FAIL@30m",
         "strategy": "F6_VWAP_FAIL", "tf": "30m", "symbol": e6["symbol"], "side": e6["side"], "why_kind": "late", "why": "늦음",
         "state": "closed", "grp": "exec", "executor": "mexc", "paper": "vwap", "entry_ts": e6["entry_time"], "roe_net": e6["roe"],
         "pnl": e6["pnl"], "exit_ts": e6["exit_time"], "reason": e6["exit_reason"]},
        {"key": f"N20_EMA9_CHOP@30m|ETHUSDT|{K(5, 12)}", "t": K(5, 12), "step_ts": K(5, 12), "member": "N20_EMA9_CHOP@30m",
         "strategy": "N20_EMA9_CHOP", "tf": "30m", "symbol": "ETHUSDT", "side": 1, "why_kind": "held", "why": "포지션 있음", "state": "closed",
         "grp": "one", "paper": None, "roe_net": 0.2, "pnl": 80.0, "reason": "LOCK", "exit_ts": K(5, 14)},
    ]


def build(folder: str, *, switch: bool = True, picture: bool = True, missed: bool = True, paper_col: bool = True) -> dict:
    """Every file of the world in ``folder``: the site's paths (``p``, ``more``), the plan, the VWAP trades by plan name."""
    os.makedirs(folder, exist_ok=True)
    trend = os.path.join(folder, "live-ac.db")
    _old, pts, _wallet = FW._paper_world(trend)
    v = vwap_db(folder, picture=picture)
    vwap = v["path"]
    vts = paper_trades(vwap)
    plan_by = {x[0]: x for x in PLAN}
    by_entry = {(t["symbol"], t["entry_time"]): t for t in vts}
    vt = {n: by_entry.get((x[2], x[4])) for n, x in plan_by.items() if (x[2], x[4]) in by_entry}
    p = {"paper": trend, "paper2": vwap, "bybit_db": os.path.join(folder, "bybit.db"), "mexc_db": os.path.join(folder, "woo.db"),
         "bybit_config": os.path.join(folder, "executor.json"), "mexc_config": os.path.join(folder, "executor-mexc.json")}
    by = exec_db(p["bybit_db"], p["bybit_config"], "bybit", trend, pts)
    if switch:
        woo = exec_db(p["mexc_db"], p["mexc_config"], "wooxpro", trend, [pts[0], pts[2]], vwap=vwap, switch=SWITCH,
                      vwap_closed=[vt["E4"], vt["E5"], vt["E7"]], late=[vt["E6"]], open_pos=paper_position(vwap), light=(20, 0.75),
                      extra={"ladder_from": "own", "risk": {"max_loss_frac": 0.2}})
    else:
        woo = exec_db(p["mexc_db"], p["mexc_config"], "wooxpro", trend, [pts[0], pts[2], pts[3]])
    check = os.path.join(folder, "livecheck.db")
    if missed:
        missed_db(check, missed_rows(plan_by, vt), paper_col=paper_col)
    no = os.path.join(folder, "none")
    more = {"combo_config": no + "-combo.json", "combo2_config": no + "-combo-vwap.json", "check_db": check, "improve_db": no + "-imp.db",
            "rule_db": v["rule"], "shadow_dir": no}
    return {"p": p, "more": more, "pts": pts, "vts": vts, "vt": vt, "plan": plan_by, "by": by, "woo": woo, "vwap_cfg": v["cfg"],
            "folder": folder}


def env_of(w: dict) -> dict:
    """The site's environment for this world (livebots ENV and ENV_MORE)."""
    from paperbot.dash.more.livebots import ENV, ENV_MORE
    out = {ENV[k][0]: val for k, val in w["p"].items() if k in ENV}
    out.update({ENV_MORE[k][0]: val for k, val in w["more"].items() if k in ENV_MORE})
    return out
