"""The 추세판단 봇 and 'VWAP 개선판' side by side (owners 10-23, docs/vwap-bot-ko.md) for the live checks' tests
(tests/test_livecheck_vwap.py): one executor follows the VWAP bot from its switch, the other stays on the trend bot; or,
``follow=False``, the VWAP bot runs paper-only next to them (its first stage).

trend paper (live-ac.db): the standard world of tests/livebots_world.py (t1 .. t6, an open BTC long entered T0+9h) under
    the 추세판단 봇's own config record (deploy/combo.trend.json).
VWAP paper (vwap.db): 'VWAP 개선판' ITSELF (paperbot/livepreview.py VwapBot: combo.ComboRunner on deploy/combo.vwap.json,
    its own engine and database, its entry gates scripted) over its rule-bot file (vwap-rules.db), from T0 (Monday 10/19
    09:00 KST):
      v1 ETH long  VWAP 복귀 실패 30분      T0+1h30  won (its first lock, then back to it)
      v2 SOL long  VWAP 복귀 실패 30분      T0+3h    lost (its 2 ATR stop)
      v3 DOGE long CMO·샌드위치 캔들 1시간  T0+4h    won
      [SWITCH T0+5h: ``who`` starts with paper_db vwap.db]
      v4 LTC long  VWAP 복귀 실패 30분      T0+6h    lost
      T0+7h ETH (4h vote against), T0+7h30 SOL (volatility), T0+8h BCH 1h (4h vote unreadable): FILTERED by its gates
      v5 BTC long  VWAP 복귀 실패 30분      T0+9h    open (the same minute and coin as the trend bot's open BTC long)
      T0+13h30 (22:30 KST) a SOL signal in the NYSE-open pause: FILTERED
executors (paperbot.executor.ExecStore and its own writers): ``who`` (bybit or mexc) followed the trend bot's t2 and t3,
    then (``follow``) the VWAP bot's v4 (its loss) and v5 (open); the other follows the trend bot (t2, t4, t6, the open
    BTC long). ``who``'s light: ``light`` (N, share; deploy/vwap_switch.py sets 20 / 75 %, smaller here so the trades
    above decide it); the trend bot's executor runs none (the live configs since owners 10-19). ``skip``: the VWAP trades
    (``v4``, ``v5``) and the trend bot's open BTC long (``trend_open``) the executors did not follow.
The world is built in time order up to ``until`` (``advance``: later steps one by one), so a test can look at it before
something happens and again after.
"""
from __future__ import annotations

import json
import os

from paperbot import livecheck as LC
from paperbot.executor import ExecStore
from paperbot.livepreview import VwapBot, gate_read
from paperbot.store3 import Store3
from tests import livebots_world as W
from tests.two_papers_world import _run, deploy_config

H, MIN, DAY, T0, NOW = W.H, W.MIN, W.DAY, W.T0, W.NOW
ACCOUNT = W.ACCOUNT
SWITCH = T0 + 5 * H
V1, V2, V3, V4, V5 = T0 + H + 30 * MIN, T0 + 3 * H, T0 + 4 * H, T0 + 6 * H, T0 + 9 * H
GATE_T = (T0 + 7 * H, T0 + 7 * H + 30 * MIN, T0 + 8 * H)
NYSE_T = T0 + 13 * H + 30 * MIN
VOTE_WHY = "4시간 추세 반대: 상승 0·하락 3·중립 1"
VOL_WHY = "변동성 높음: ATR 0.512% > 지난 30일 80% 위치 0.433%"
UNREAD_WHY = "4시간 추세 판단을 못 읽음(진입 안 함): 바이낸스 응답 없음"
LIVE_EQ = 100.0


class VwapWorld:
    """The files of the world in ``folder`` and the VWAP bot that keeps running (``vb``)."""

    def __init__(self, folder: str, who: str = "bybit", follow: bool = True, until: int = NOW, light: tuple = (4, 0.75),
                 skip: tuple = ()):
        os.makedirs(folder, exist_ok=True)
        self.folder, self.who, self.follow, self.skip = folder, who, follow, tuple(skip)
        self.other = "mexc" if who == "bybit" else "bybit"
        p = {k: os.path.join(folder, f) for k, f in (("paper", "live-ac.db"), ("vwap", "vwap.db"),
                                                    ("bybit_db", "executor-bybit-live.db"), ("mexc_db", "executor-mexc-live.db"),
                                                    ("bybit_config", "executor.json"), ("mexc_config", "executor-mexc.json"))}
        self.p = p
        W.paper_db(p["paper"])
        _run(p["paper"], deploy_config("combo.trend.json"), T0)
        self.rule = os.path.join(folder, "vwap-rules.db")
        self.vb = VwapBot(p["vwap"], self.rule, T0)
        kill = os.path.join(folder, "STOP")
        for name in ("bybit", "mexc"):
            mine = name == who and follow
            W.config(p[f"{name}_config"], p[f"{name}_db"], p["vwap"] if mine else p["paper"], name,
                     light[1] if mine else 0.85, kill, n=light[0] if mine else 0)
        self.st = {name: ExecStore(p[f"{name}_db"], lock=False) for name in ("bybit", "mexc")}
        for name, st in self.st.items():
            st.put_state("meta", T0, {"mode": "mainnet", "account": ACCOUNT, "since": T0, "exchange": name,
                                      "live_since": W.LIVE_SINCE})
            st.event(W.LIVE_SINCE, "INFO", "start", "시작", {"paper_db": p["paper"]})
            st.equity(W.LIVE_SINCE, LIVE_EQ, LIVE_EQ, 0.0)
        self.eq = {"bybit": LIVE_EQ, "mexc": LIVE_EQ}
        self.held = {"bybit": None, "mexc": None}
        self.vtrades: dict = {}
        steps = [(T0 + 2 * H, lambda: self._trend_follow(who, ("t2", "t3"))),
                 (T0 + 2 * H, lambda: self._trend_follow(self.other, ("t2", "t4", "t6"))),
                 (V1, lambda: self._vtrade("v1", "F6_VWAP_FAIL", "ETHUSDT", V1, "win")),
                 (V2, lambda: self._vtrade("v2", "F6_VWAP_FAIL", "SOLUSDT", V2, "loss")),
                 (V3, lambda: self._vtrade("v3", "S3_CMO_SANDWICH", "DOGEUSDT", V3, "win")),
                 (V4, lambda: self._vtrade("v4", "F6_VWAP_FAIL", "LTCUSDT", V4, "loss")),
                 (GATE_T[0], lambda: self._gated("F6_VWAP_FAIL", "ETHUSDT", 1, GATE_T[0], VOTE_WHY, gate_read(1, "30m", up=0, down=3), True)),
                 (GATE_T[1], lambda: self._gated("F6_VWAP_FAIL", "SOLUSDT", -1, GATE_T[1], VOL_WHY,
                                                 gate_read(-1, "30m", atr_pct=0.512, q_pct=0.433), False)),
                 (GATE_T[2], lambda: self._gated("S3_CMO_SANDWICH", "BCHUSDT", 1, GATE_T[2], UNREAD_WHY,
                                                 {"vote": {"tf": "4h", "error": "바이낸스 응답 없음"}}, True)),
                 (V5 - MIN, lambda: self._trend_open(self.other)),
                 (V5, lambda: self._vtrade("v5", "F6_VWAP_FAIL", "BTCUSDT", V5, "hold")),
                 (NYSE_T, lambda: self._gated("F6_VWAP_FAIL", "SOLUSDT", 1, NYSE_T, "", None, True))]
        if follow:
            steps.append((SWITCH, self._switch))
        self.steps = sorted(steps, key=lambda s: s[0])
        self.t = T0
        self.advance(until)

    # ---- time
    def advance(self, until: int) -> "VwapWorld":
        """Every scripted step that starts before ``until``, then the VWAP bot's minutes up to it."""
        while self.steps and self.steps[0][0] < until:
            _t, fn = self.steps.pop(0)
            fn()
        self.vb.run_to(max(until, self.vb.t))
        self.t = until
        for name, st in self.st.items():           # both executors keep running: their state is fresh
            st.put_state("bot", until - 5_000, {"trade": self.held[name], "done": [], "loops": 1, "mode": "mainnet",
                                                "account": ACCOUNT, "risk": {"halted": False, "halt_reason": "",
                                                                            "last_equity": self.eq[name],
                                                                            "peak_equity": max(LIVE_EQ, self.eq[name])}})
            st.commit()
        return self

    # ---- the executors
    def _trend_follow(self, name: str, which: tuple) -> None:
        by = {n: (sym, side, t) for n, sym, side, t, *_r in W.PAPER}
        for n in which:
            sym, side, t = by[n]
            W._live(self.st[name], W._k(sym, t), sym, side, t, 0.8, 0.05)
            self.eq[name] += 0.8

    def _trend_open(self, name: str) -> None:
        if "trend_open" in self.skip:
            return                                      # it did not follow the trend bot's open BTC long
        t = {"key": W._k("BTCUSDT", V5), "symbol": "BTCUSDT", "side": 1, "qty": 0.025, "leverage": 40, "stop": 61610.0,
             "stop_initial": 61610.0, "status": "open", "entry_ts": V5 + 15_000, "entry_price": 62012.0, "entry_time": V5,
             "paper_entry": 62000.0, "mode": "mainnet", "stop_algo_id": "w1"}
        self.st[name].trade_open(t)
        self.held[name] = t

    def _switch(self) -> None:
        self.st[self.who].event(SWITCH, "INFO", "start", f"시작: paper 계좌 COMBO@mix 따라 하기 (페이퍼 DB {self.p['vwap']})",
                                {"paper_db": self.p["vwap"]})

    def following(self, t: int) -> bool:
        return self.follow and t >= SWITCH

    # ---- the VWAP bot
    def _vtrade(self, name: str, strat: str, sym: str, b: int, outcome: str) -> None:
        vb = self.vb
        vb.run_to(b)
        p0 = vb.price(sym, b)
        vb.signal(strat, sym, 1, b)
        vb.run_to(b + MIN)
        pos = vb.engine().position
        assert pos is not None and pos.entry_time == b, (name, pos)
        key = W._k(sym, b)
        if self.following(b) and name not in self.skip:
            fill = round(pos.entry_price * 1.0002, 6)
            qty = round(self.eq[self.who] * 0.4 * pos.leverage / fill, 6)
            stop = round(fill * pos.stop_price / pos.entry_price, 6)
            t = {"key": key, "symbol": sym, "side": 1, "qty": qty, "leverage": pos.leverage, "entry_ts": b + 3_000,
                 "entry_price": fill, "stop_initial": stop, "stop": stop, "status": "open", "mode": "mainnet",
                 "entry_time": b, "stop_algo_id": "v1"}
            self.st[self.who].trade_open(t)
            self.held[self.who] = t
        if outcome == "win":
            vb.move(sym, b + 20 * MIN, p0 * 1.007)
            vb.move(sym, b + 40 * MIN, p0 * 1.004)
            vb.move(sym, b + 50 * MIN, p0 * 1.004)
            vb.run_to(b + 50 * MIN)
        elif outcome == "loss":
            vb.move(sym, b + 30 * MIN, p0 * 0.98)
            vb.run_to(b + 40 * MIN)
        if outcome != "hold":
            self.settle(name)

    def settle(self, name: str) -> None:
        """The VWAP bot's last closed trade is ``name``; its follower (if any) closes 2 bps worse than its exit."""
        rec = self.vb.engine().trades[-1]
        self.vtrades[name] = rec
        key = W._k(rec.symbol, rec.entry_time)
        t = self.held.get(self.who)
        if t is not None and t["key"] == key:
            px = rec.exit_price * (1 - rec.side * 0.0002)
            pnl = round(rec.side * t["qty"] * (px - t["entry_price"]) - t["qty"] * (t["entry_price"] + px) * 0.00055, 4)
            self.st[self.who].trade_close(key, rec.exit_time + 2_000, "paper 청산 → 거래소 포지션 닫기", pnl, t, "wallet")
            self.st[self.who].trade_costs(key, {"pnl": pnl, "realized": pnl, "commission": 0.01, "funding": 0.0, "slippage": 0.0,
                                                "real_cost": 0.01, "assumed_cost": 0.01, "ok": True})
            self.eq[self.who] = round(self.eq[self.who] + pnl, 4)
            self.st[self.who].equity(rec.exit_time + 2_000, self.eq[self.who], self.eq[self.who], 0.0)
            self.held[self.who] = None

    def _gated(self, strat: str, sym: str, side: int, t: int, why: str, info, won: bool) -> None:
        """A signal its gates keep out (``why``; '' = passes them), and where the price goes after (its virtual trade)."""
        vb = self.vb
        vb.run_to(t)
        if why:
            vb.gates.set(sym, t, why, info)
        q = vb.price(sym, t)
        vb.signal(strat, sym, side, t)
        vb.run_to(t + MIN)
        if won:
            vb.move(sym, t + 25 * MIN, q * (1 + side * 0.007))
            vb.move(sym, t + 50 * MIN, q * (1 + side * 0.004))
        else:
            vb.move(sym, t + 30 * MIN, q * (1 - side * 0.02))

    def hold_v5(self, outcome: str = "time") -> None:
        """v5 from here: "time" (below its first lock for 96 bars: its hold limit), "win" or "loss"."""
        vb = self.vb
        p0 = vb.engine().position.entry_price
        if outcome == "time":
            vb.move("BTCUSDT", vb.t + 60 * MIN, p0 * 1.0025)
            vb.run_to(V5 + 96 * 30 * MIN + 2 * MIN)
        elif outcome == "win":
            vb.move("BTCUSDT", vb.t + 20 * MIN, p0 * 1.007)
            vb.move("BTCUSDT", vb.t + 40 * MIN, p0 * 1.004)
            vb.move("BTCUSDT", vb.t + 50 * MIN, p0 * 1.004)
            vb.run_to(vb.t + 50 * MIN)
        else:
            vb.move("BTCUSDT", vb.t + 30 * MIN, p0 * 0.98)
            vb.run_to(vb.t + 40 * MIN)
        assert vb.engine().position is None
        self.settle("v5")

    # ---- what the checks read
    def infos(self) -> list:
        return W.exec_infos(self.p)

    def src(self, **kw) -> LC.Sources:
        f = self.folder
        return LC.Sources(**{"db": os.path.join(f, "livecheck.db"), "paper_db": self.p["paper"], "rule_db": self.rule,
                             "combo_config": os.path.join(f, "no-combo.json"), "cache": os.path.join(f, "cache.db"),
                             "shadow_glob": os.path.join(f, "shadow-*.db"), "executors": self.infos(),
                             "paper2_db": self.p["vwap"], **kw})

    def set_vwap_config(self, **change) -> None:
        """Its run record's config changed (a config the owners edited: e.g. its pauses)."""
        s = Store3(self.p["vwap"])
        run = json.loads(s.conn.execute("SELECT data FROM state WHERE k = 'combo_run'").fetchone()[0])
        run["config"].update(change)
        s.put_state("combo_run", T0, run)
        s.close()

    def stale_vwap(self, at: int) -> None:
        """The VWAP bot stopped writing at ``at`` (its heartbeat)."""
        s = Store3(self.p["vwap"])
        s.put_state("heartbeat", at, {})
        s.close()

    def close(self) -> None:
        self.vb.close()
        for st in self.st.values():
            st.close()
