"""게이트 봇 (owners 10-31, docs/gate-bot-ko.md): the stop and the take-profit ladder on positions a friend opens by hand.

There is no trading rule. The friend enters on their own Gate account (USDT perpetuals, one-way mode); the bot watches
the account's positions and, for each one, puts a stop on Gate and moves it up the ladder:

* 손절 (owners: "손절은 3TR", "atr은 15분봉"): entry -/+ ATR(14) of Gate's closed 15m candles x 3 (Pine's ta.atr:
  Wilder's average of the true range, as paperbot/mixchop.py ``atr``). A stop that would sit beyond the liquidation
  price is pulled inside it (``liq_keep``: 15 % of the entry -> liquidation distance short of the liquidation price) and
  the owners are told.
* 계단식 익절 (owners: "순수익 8% 위로 2%씩", "10프로 가면 8프로"): net ROE (the margin's return at the position's
  leverage, the taker fee paid on both sides) of the best price since the entry; 10 % -> the stop at +8 %, then one 2 %
  step more per 2 % more (12 -> 10, 14 -> 12 ...): paperbot/ladder2.py ``ComboLadder`` (first_lock 0.08, trigger_gap
  0.02, step 0.02) on paperbot/ladder.py ``net_roe`` / ``roe_price``. The best price is read from Gate's 1m candles of
  the last price (what the stop triggers on), so a spike between two loops is not missed. The stop only ever tightens.
* A lock whose price the market already passed between two loops (Gate refuses a stop on the wrong side of the last
  price) closes the position at market: what the stop would have done. The same for a first stop already crossed (a
  position the bot first sees late).
* The friend adds to a position (its size grows): everything is computed again from the new average entry (a fresh
  ATR stop, the ladder from zero, the best price from then on). A part closed: the stop already closes whatever is left.
* The friend's own orders come first: the bot never touches an order it did not place. The friend closes by hand or
  with their own TP/SL: the bot cancels its own stop and reports the result. The friend cancels the bot's stop: the bot
  leaves that position alone (told once) until it changes (a new entry or an add).
* Each coin on its own (one-way mode: one position per coin). Hedge mode / split positions: refused at the start (and
  such a position later is skipped with a warning).

The stop is a Gate price order (paperbot/gate.py ``place_stop``): it rests on the exchange and closes the whole position
at market, so it keeps protecting while this program is off; only the ladder waits. A stop is moved new-first: the new
one is placed, then the old one cancelled (never a moment without one). Its state (the stop ids, the lock reached, the
best price) is saved in ``state`` (/var/lib/paperbot/exec/gateguard.json).

    python -m paperbot.gateguard check --config /etc/paperbot/gateguard.json   # reads only: what it would do now
    python -m paperbot.gateguard run --config /etc/paperbot/gateguard.json     # the unit paperbot-gateguard

Keys: GATE_LIVE_KEY / GATE_LIVE_SECRET (futures trade only, no withdrawal, bound to the server's IP), the owners'
GATE_LIVE_KEY_CHECKED=FUTURES_ONLY_NO_WITHDRAW_IP_BOUND and PAPERBOT_LIVE_MAINNET=I_UNDERSTAND, all in the root-only
/etc/paperbot/executor-gate.env that only this unit loads. Exit 2 = refused at the start (systemd does not restart it).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import gate as G
from .ladder import net_roe, roe_price
from .ladder2 import ComboLadder

NAME = "게이트 봇"
MODE_MAINNET = "mainnet"
FLAG, FLAG_VALUE = "PAPERBOT_LIVE_MAINNET", "I_UNDERSTAND"
DEFAULT_STATE = "/var/lib/paperbot/exec/gateguard.json"
DEFAULT_FEE = 0.0005                   # Gate's base taker fee, when the account's own cannot be read
TF_S = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600}
TF_KO = {"5m": "5분봉", "15m": "15분봉", "30m": "30분봉", "1h": "1시간봉"}
MIN_S = 60
LOOKBACK_S = 86_400                    # the best price is read at most a day back (a long stop of this program)
CLOSE_WAIT_S = 120                     # how long a closed position's P&L is looked for in Gate's records
CLOSING_WAIT_S = 60                    # a market close sent: not sent again for this long while the position shows
LATE_S = 300                           # a position first seen this long after it opened: "seen late"
ACCOUNT_EVERY_S = 600
FOREIGN_PREFIXES = ("BYBIT_", "MEXC_", "WOOXPRO_", "FLIPSTER_", "DEEPCOIN_", "TOOBIT_", "LIVE_API_", "TESTNET_API_",
                    "BINANCE_API_")
INFO, WARN, CRITICAL = "INFO", "WARN", "CRITICAL"


class Refused(Exception):
    """The bot will not start (Korean reason). Exit 2."""


# ====================================================================== config
@dataclass
class Config:
    name: str = NAME
    mode: str = MODE_MAINNET
    stop_atr: float = 3.0
    atr_tf: str = "15m"
    atr_n: int = 14
    ladder: ComboLadder = field(default_factory=lambda: ComboLadder(0.08, 0.02, 0.02))
    fee: Optional[float] = None          # taker fee per side; None = the account's own (GET fee), else DEFAULT_FEE
    liq_keep: float = 0.15               # a stop past the liquidation price: this share of entry -> liq kept short of it
    poll_s: float = 10.0
    coins: Optional[list] = None         # None = every position of the account; else contracts like "BTC_USDT"
    state: str = DEFAULT_STATE
    telegram: bool = True

    def ladder_words(self) -> str:
        lad = self.ladder
        return (f"순ROE {lad.first_trigger:.0%}에서 {lad.first_lock:.0%} 잠금, 이후 {lad.step:.0%}씩 "
                f"({lad.first_trigger + lad.step:.0%}→{lad.first_lock + lad.step:.0%}, "
                f"{lad.first_trigger + 2 * lad.step:.0%}→{lad.first_lock + 2 * lad.step:.0%} …)")

    def words(self) -> str:
        return (f"손절 {TF_KO[self.atr_tf]} ATR({self.atr_n}) × {self.stop_atr:g} · 계단 익절 {self.ladder_words()} · "
                f"수수료 {'계정 수수료' if self.fee is None else f'{self.fee:.3%}'} 양쪽 반영 · "
                f"코인 {'전부' if not self.coins else ', '.join(coin_ko(c) for c in self.coins)}")


def load_config(path: str) -> Config:
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError) as e:
        raise Refused(f"설정 파일 {path}을 못 읽습니다: {e}") from None
    if not isinstance(raw, dict):
        raise Refused(f"설정 파일 {path}은 JSON 객체여야 합니다")
    known = {"name", "mode", "stop_atr", "atr_tf", "atr_n", "ladder", "fee", "liq_keep", "poll_s", "coins", "state",
             "telegram", "note"}
    extra = sorted(set(raw) - known)
    if extra:
        raise Refused(f"설정에 모르는 항목이 있습니다: {', '.join(extra)}")
    cfg = Config()
    cfg.name = str(raw.get("name") or NAME)
    cfg.mode = str(raw.get("mode") or "")
    try:
        cfg.stop_atr = float(raw.get("stop_atr", 3.0))
        cfg.atr_n = int(raw.get("atr_n", 14))
        cfg.liq_keep = float(raw.get("liq_keep", 0.15))
        cfg.poll_s = float(raw.get("poll_s", 10.0))
        cfg.fee = None if raw.get("fee") is None else float(raw["fee"])
    except (TypeError, ValueError) as e:
        raise Refused(f"설정 숫자를 못 읽습니다: {e}") from None
    cfg.atr_tf = str(raw.get("atr_tf") or "15m")
    lad = ComboLadder.of(raw.get("ladder"))
    if lad is None:
        raise Refused("\"ladder\"에 first_lock, trigger_gap, step(0~1 비율)이 필요합니다")
    if lad.two_part or lad.problems():
        raise Refused("ladder: " + "; ".join(lad.problems() or ["게이트 봇은 한 가지 간격의 계단만 씁니다"]))
    cfg.ladder = lad
    coins = raw.get("coins")
    if coins is not None and (not isinstance(coins, list) or not all(isinstance(c, str) and c.endswith("_USDT")
                                                                        for c in coins)):
        raise Refused("\"coins\"는 null(전부) 또는 [\"BTC_USDT\", ...] 목록입니다")
    cfg.coins = coins or None
    cfg.state = str(raw.get("state") or DEFAULT_STATE)
    cfg.telegram = bool(raw.get("telegram", True))
    if cfg.mode != MODE_MAINNET:
        raise Refused(f"게이트 봇은 실거래만 합니다: \"mode\": \"mainnet\"이 필요합니다(지금 {cfg.mode!r})")
    if cfg.atr_tf not in TF_S:
        raise Refused(f"\"atr_tf\"는 {', '.join(TF_S)} 중 하나입니다(지금 {cfg.atr_tf!r})")
    if not (0.5 <= cfg.stop_atr <= 10 and 5 <= cfg.atr_n <= 50):
        raise Refused("\"stop_atr\"는 0.5~10, \"atr_n\"은 5~50입니다")
    if not (0.02 <= cfg.liq_keep <= 0.5):
        raise Refused("\"liq_keep\"은 0.02~0.5(청산가까지 거리 중 남길 몫)입니다")
    if not (3 <= cfg.poll_s <= 60):
        raise Refused("\"poll_s\"는 3~60초입니다")
    if cfg.fee is not None and not (0 <= cfg.fee <= 0.002):
        raise Refused("\"fee\"는 null(계정 수수료) 또는 0~0.002입니다")
    return cfg


def trading_keys(cfg: Config, env) -> tuple[str, str]:
    """The Gate key and secret, or Refused."""
    if cfg.mode != MODE_MAINNET:
        raise Refused("게이트 봇은 \"mode\": \"mainnet\"만 됩니다")
    if (env.get(FLAG) or "") != FLAG_VALUE:
        raise Refused(f"실거래 스위치가 꺼져 있습니다: 환경 변수 {FLAG}={FLAG_VALUE} 가 필요합니다")
    key, secret = (str(env.get(n) or "").strip() for n in G.KEY_NAMES)
    if not (key and secret):
        raise Refused(f"{G.KEY_NAMES[0]} / {G.KEY_NAMES[1]} 가 비어 있습니다 (sudoedit /etc/paperbot/executor-gate.env)")
    if key == secret:
        raise Refused(f"{G.KEY_NAMES[0]}와 {G.KEY_NAMES[1]}가 같습니다")
    if str(env.get(G.KEY_CHECKED) or "").strip() != G.KEY_CHECKED_VALUE:
        raise Refused(f"{G.KEY_CHECKED}={G.KEY_CHECKED_VALUE} 가 없습니다: 게이트 키 화면에서 선물 거래만 · 출금 없음 · "
                      "서버 IP 묶음을 확인한 뒤 적어 주세요")
    foreign = sorted(k for k, v in env.items() if str(v or "").strip() and k.startswith(FOREIGN_PREFIXES))
    if foreign:
        raise Refused("게이트 봇의 환경에 다른 거래소 키가 있습니다(" + ", ".join(foreign) + "). "
                      "executor-gate.env에는 게이트 키만 둡니다")
    return key, secret


# ====================================================================== helpers
def coin_ko(c: str) -> str:
    return c.replace("_USDT", "")


def side_ko(side: int) -> str:
    return "롱" if side > 0 else "숏"


def round_stop(price: float, tick: float, side: int) -> float:
    """To the tick, never looser than asked: up for a long's stop, down for a short's."""
    n = price / tick
    n = math.ceil(n - 1e-9) if side > 0 else math.floor(n + 1e-9)
    return round(n * tick, 12)


def wilder_atr(rows: list, n: int) -> Optional[float]:
    """ATR(n) of the last row (Pine ta.atr: the first true range is high - low; seeded with the simple average)."""
    if len(rows) < n + 1:
        return None
    trs, prev = [], None
    for _, _o, h, l, c in rows:
        trs.append(h - l if prev is None else max(h, prev) - min(l, prev))
        prev = c
    s = sum(trs[:n]) / n
    for tr in trs[n:]:
        s = (tr + (n - 1) * s) / n
    return s


def fmt(x: Optional[float]) -> str:
    if x is None:
        return "-"
    return f"{x:,.8g}" if abs(x) < 1e6 else f"{x:,.2f}"


def pct(x: float) -> str:
    return f"{x:+.1%}"


def kst(ts: float) -> str:
    return time.strftime("%m-%d %H:%M", time.gmtime(ts + 9 * 3600))


# ====================================================================== the guard
class Guard:
    """One loop per ``poll_s``: positions -> stops placed, moved, cleaned up; messages through ``notify``."""

    def __init__(self, cfg: Config, client: G.GateClient, notify: Callable[[str, str], None],
                 save: bool = True) -> None:
        self.cfg, self.c, self.notify, self.save_on = cfg, client, notify, save
        self.st = self._load()
        self.coins: dict = self.st.setdefault("coins", {})
        self.pending: list = self.st.setdefault("pending", [])
        self.orphans: list = self.st.setdefault("orphans", [])     # [contract, id] of our stops still to cancel
        self.fails = 0
        self.last_account = 0.0
        self.warned: dict = {}

    # ------------------------------------------------------------------ state
    def _load(self) -> dict:
        try:
            with open(self.cfg.state, encoding="utf-8") as fh:
                d = json.load(fh)
            return d if isinstance(d, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            raise Refused(f"상태 파일 {self.cfg.state}을 못 읽습니다: {e} (지우지 말고 알려 주세요)") from None

    def save(self) -> None:
        if not self.save_on:
            return
        tmp = self.cfg.state + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.st, fh, ensure_ascii=False, indent=1, sort_keys=True)
        os.chmod(tmp, 0o640)
        os.replace(tmp, self.cfg.state)

    def say(self, level: str, text: str) -> None:
        self.notify(level, f"[{self.cfg.name}] {text}")

    def say_once(self, key: str, level: str, text: str, every_s: float = 3600.0) -> None:
        now = self.c.now()
        if now - self.warned.get(key, -1e18) >= every_s:
            self.warned[key] = now
            self.say(level, text)

    # ------------------------------------------------------------------ start
    def start_checks(self) -> dict:
        """Hedge mode or split positions refuse the start; an unbound key too (when Gate shows the binding)."""
        acct = self.c.account()
        self._mode_ok(acct, start=True)
        try:
            det = self.c.detail()
        except G.GateRefused:
            det = {}
        ips = det.get("ip_whitelist") if isinstance(det, dict) else None
        if isinstance(ips, list) and not ips:
            raise Refused("이 키는 IP가 묶여 있지 않습니다(게이트 키 화면에서 서버 IP 158.247.200.152 를 묶어 주세요)")
        self.last_account = self.c.now()
        return {"account": acct, "ips": ips}

    def _mode_ok(self, acct: dict, start: bool = False) -> bool:
        mode = str(acct.get("position_mode") or "")
        if acct.get("in_dual_mode") or mode not in ("", "single"):
            msg = (f"게이트 선물 계정이 한 방향 모드가 아닙니다(position_mode {mode or 'dual'}). 앱에서 '단방향(원웨이)' "
                   "모드로 바꿔 주세요. 양방향 포지션은 지키지 않습니다")
            if start:
                raise Refused(msg)
            self.say_once("dual", CRITICAL, msg)
            return False
        return True

    # ------------------------------------------------------------------ the loop
    def loop_once(self) -> None:
        now = self.c.now()
        if now - self.last_account >= ACCOUNT_EVERY_S:
            self._mode_ok(self.c.account())
            self.last_account = now
        positions, held = {}, set()
        for p in self.c.positions():
            held.add(p["contract"])
            if self.cfg.coins and p["contract"] not in self.cfg.coins:
                continue
            if p["mode"] != "single":
                self.say_once(f"mode:{p['contract']}", WARN, f"{coin_ko(p['contract'])} 포지션이 양방향 모드"
                              f"({p['mode']})라 지키지 않습니다")
                continue
            positions[p["contract"]] = p
        open_orders = {o["id"]: o for o in self.c.price_orders()}
        for c in list(self.coins):
            p = positions.get(c)
            if p is None or p["side"] != self.coins[c]["side"]:
                self._closed(c, open_orders)
        for c, p in positions.items():
            try:
                self._watch(c, p, open_orders)
            except G.GateError as e:
                self.say_once(f"err:{c}", WARN, f"{coin_ko(c)} 처리 중 오류(다음 회차에 다시): {e}", 600)
        self._clean_orphans(open_orders)
        self._sweep(open_orders, held)
        self._report_pending()
        self.save()

    def run(self, loops: Optional[int] = None, sleep: Callable[[float], None] = time.sleep) -> None:
        n = 0
        while loops is None or n < loops:
            n += 1
            try:
                self.loop_once()
                if self.fails >= 3:
                    self.say(INFO, "게이트 연결이 다시 됩니다")
                self.fails = 0
            except G.GateError as e:
                self.fails += 1
                if self.fails in (3, 30) or self.fails % 360 == 0:
                    self.say(CRITICAL if self.fails >= 30 else WARN,
                             f"게이트를 {self.fails}번 연속 못 읽었습니다(걸린 손절은 게이트에 그대로 있음): {e}")
                if self.fails % 60 == 0:
                    try:
                        self.c.sync_time()
                    except G.GateError:
                        pass
            except Exception as e:                        # noqa: BLE001 (a bug of ours: told, the loop goes on)
                self.say_once(f"bug:{type(e).__name__}", CRITICAL, f"봇 내부 오류(걸린 손절은 게이트에 그대로 있음): "
                              f"{type(e).__name__}: {e}")
            if loops is None or n < loops:
                sleep(self.cfg.poll_s)

    # ------------------------------------------------------------------ one position
    def _watch(self, c: str, p: dict, open_orders: dict) -> None:
        s = self.coins.get(c)
        if s is not None and p["size"] > s["size"] * (1 + 1e-9) and abs(p["entry"] - s["entry"]) > 1e-12 * p["entry"]:
            self.say(INFO, f"{coin_ko(c)} {side_ko(p['side'])} 추가 진입 확인: 평단 {fmt(s['entry'])} → {fmt(p['entry'])}, "
                     f"수량 {s['size']:g} → {p['size']:g}. 새 평단 기준으로 손절과 계단을 다시 잡습니다")
            s = self._new(c, p, old=s)
            return
        if s is None:
            self._new(c, p)
            return
        if p["size"] < s["size"] * (1 - 1e-9):
            self.say(INFO, f"{coin_ko(c)} 일부 종료 확인: 수량 {s['size']:g} → {p['size']:g} (봇 손절은 남은 수량 전부를 닫음)")
        s["size"] = p["size"]
        if p["lev"] > 0:
            s["lev"] = p["lev"]
        s["liq"] = p["liq"]
        if s.get("hands_off"):
            return
        sid = s.get("stop_id")
        if sid is not None and sid not in open_orders:
            self._stop_gone(c, s, p)
            return
        if sid is None:                                  # the first stop could not be placed yet
            if self._set_stop(c, s, s["stop"], s.get("kind") or "atr"):
                self._intro(s)
            return
        self._liq_check(c, s, p)
        self._ladder(c, s)

    def _new(self, c: str, p: dict, old: Optional[dict] = None) -> Optional[dict]:
        """A position first seen (or added to): its ATR stop placed."""
        side, entry = p["side"], p["entry"]
        if entry <= 0:
            raise G.GateError(f"{coin_ko(c)} 평단을 못 읽음")
        spec = self.c.contract(c)
        fee = self.cfg.fee
        if fee is None:
            try:
                fee = self.c.taker_fee(c)
            except G.GateError:
                fee = None
            fee = fee if fee is not None and 0 <= fee <= 0.002 else (spec.get("taker") or DEFAULT_FEE)
        atr = self._atr(c)
        raw = entry - side * self.cfg.stop_atr * atr
        kind = "atr"
        liq = p["liq"]
        if liq > 0 and (raw - liq) * side <= 0:
            raw = liq + side * self.cfg.liq_keep * abs(entry - liq)
            kind = "liq"
        stop = round_stop(raw, spec["tick"], side)
        now = self.c.now()
        late = old is None and bool(p["open_s"]) and now - p["open_s"] > LATE_S
        s = {"side": side, "size": p["size"], "entry": entry, "lev": p["lev"], "liq": liq, "fee": fee, "atr": atr,
             "atr_stop": round_stop(entry - side * self.cfg.stop_atr * atr, spec["tick"], side),
             "stop": stop, "kind": kind, "stop_id": None, "lock": None, "best": entry, "best_roe": None,
             "open_s": p["open_s"] or int(now), "seen_s": int(now), "hands_off": False,
             "read_min": int(now // MIN_S * MIN_S) if old is not None or late or not p["open_s"]
             else int(p["open_s"] // MIN_S * MIN_S), "entry_min": None, "late": late}
        s["entry_min"] = s["read_min"]
        if old is not None:
            prev_ids = [i for i in (old.get("stop_id"), *old.get("keep", [])) if i is not None]
        else:                       # ours already resting there (a lost state file): replaced by the new one
            try:
                rows = self.c.price_orders(contract=c)
            except G.GateError:
                rows = []
            prev_ids = [o["id"] for o in rows if o["text"] == "api" and o["close"]
                        and int(o.get("rule") or 0) == (G.RULE_LE if side > 0 else G.RULE_GE)]
        self.coins[c] = s
        lev = p["lev"]
        dist = abs(entry - stop) / entry
        roe = -(dist + 2 * fee) * lev if lev > 0 else None
        head = "" if old is not None else f"{coin_ko(c)} {side_ko(side)} 진입 확인: 평단 {fmt(entry)}, 수량 {p['size']:g}" \
            + (f", {lev:g}배" if lev > 0 else "") + (" (교차)" if p.get("cross") else "") + "\n"
        why = (f"{TF_KO[self.cfg.atr_tf]} ATR {fmt(atr)} × {self.cfg.stop_atr:g}" if kind == "atr" else
               f"{TF_KO[self.cfg.atr_tf]} ATR × {self.cfg.stop_atr:g} 자리 {fmt(s['atr_stop'])}가 청산가 {fmt(liq)} 너머라 "
               f"청산가 안쪽으로 당김")
        text = (head + f"손절 {fmt(stop)} ({why}, 가격 {pct(-dist)}" + (f" · 순ROE {pct(roe)}" if roe is not None else "")
                + f")\n익절: {self.cfg.ladder_words()}" + ("" if lev > 0 else "\n레버리지를 못 읽어 계단은 아직 못 셉니다")
                + (f"\n봇이 늦게 본 포지션(진입 {kst(p['open_s'])})이라 최고가는 지금부터 셉니다" if late else ""))
        s["intro"], s["intro_level"] = text, (WARN if kind == "liq" else INFO)
        s["keep"] = prev_ids                              # the old stop keeps protecting until the new one is there
        if self._set_stop(c, s, stop, kind):
            self._intro(s)
        return s

    def _intro(self, s: dict) -> None:
        text = s.pop("intro", None)
        level = s.pop("intro_level", INFO)
        if text:
            self.say(level, text)

    def _atr(self, c: str) -> float:
        tf_s = TF_S[self.cfg.atr_tf]
        rows = self.c.candles(c, self.cfg.atr_tf, limit=200)
        now = self.c.now()
        closed = [r for r in rows if r[0] / 1000 + tf_s <= now + 1]
        atr = wilder_atr(closed, self.cfg.atr_n)
        if not atr or atr <= 0:
            raise G.GateError(f"{coin_ko(c)} {TF_KO[self.cfg.atr_tf]} ATR을 못 셈(닫힌 봉 {len(closed)}개)")
        return atr

    # ------------------------------------------------------------------ stops
    def _set_stop(self, c: str, s: dict, target: float, kind: str, lock: Optional[float] = None) -> bool:
        """Place ``target`` as the stop (then cancel the old one). A target the price already passed: close at market
        (a position the bot saw late whose first stop is already passed: left to the friend, told)."""
        side = s["side"]
        last = self.c.last_price(c)
        if (last - target) * side <= 0:
            if s.get("late") and s.get("stop_id") is None and lock is None:
                s["hands_off"] = True
                s.pop("intro", None)
                self.say(CRITICAL, f"{coin_ko(c)} {side_ko(side)}: 봇이 늦게 본 포지션인데 가격 {fmt(last)}이 이미 손절 자리 "
                         f"{fmt(target)}를 지났습니다. 이 포지션은 봇이 닫지 않고 건드리지 않습니다. 직접 정리해 주세요")
                self.save()
                return False
            self._close_now(c, s, target, last, kind, lock)
            return False
        sent = self.c.now()
        try:
            oid = self.c.place_stop(c, side, target)
        except G.GateUnknown as e:
            oid = self._find_placed(c, s, target, sent)
            if oid is None:
                self.say_once(f"place:{c}", WARN, f"{coin_ko(c)} 손절 {fmt(target)} 주문의 응답이 없습니다. 게이트 목록에도 "
                              f"아직 없어 다음 회차에 다시 겁니다: {e}", 300)
                return False
        except G.GateRefused as e:
            self.say_once(f"place:{c}", CRITICAL, f"{coin_ko(c)} 손절 {fmt(target)} 주문을 게이트가 거절했습니다. 다음 회차에 "
                          f"다시 겁니다: {e}", 300)
            return False
        old = s.get("stop_id")
        s.update(stop_id=oid, stop=target, kind=kind)
        if lock is not None:
            s["lock"] = lock
        self.warned.pop(f"place:{c}", None)
        self.save()
        for prev in [old] + s.pop("keep", []):
            if prev is not None and prev != oid:
                self._cancel(c, prev)
        return True

    def _find_placed(self, c: str, s: dict, target: float, sent: float) -> Optional[int]:
        """A stop whose answer was lost: one of ours resting at that price, made after it was sent."""
        try:
            rows = self.c.price_orders(contract=c)
        except G.GateError:
            return None
        tick = self.c.contract(c)["tick"]
        known = {s.get("stop_id"), *s.get("keep", [])} | {i for _, i in self.orphans}
        want_rule = G.RULE_LE if s["side"] > 0 else G.RULE_GE
        for o in sorted(rows, key=lambda o: -o["create_s"]):
            if (o["id"] not in known and o["close"] and int(o.get("rule") or 0) == want_rule and o["price"] is not None
                    and abs(o["price"] - target) <= tick / 2 and o["create_s"] >= sent - 30):
                return o["id"]
        return None

    def _cancel(self, c: str, oid: int) -> None:
        try:
            self.c.cancel_stop(oid)
        except G.GateRefused:
            pass                                          # already gone (fired, cancelled): nothing left to cancel
        except G.GateError:
            self.orphans.append([c, oid])                 # tried again every loop

    def _sweep(self, open_orders: dict, held: set) -> None:
        """A whole-position close order made through the API (Gate writes "api" in it: ours; the friend's come from the
        app or the web) resting on a coin with no position: a stop of ours whose id was lost (cut off before the save,
        a lost state file). It would close the friend's next position there at an old price: cancelled."""
        for o in open_orders.values():
            c = str(o.get("contract") or "")
            if o["text"] == "api" and o["close"] and c and c not in held:
                self._cancel(c, o["id"])
                self.say_once(f"sweep:{o['id']}", INFO, f"{coin_ko(c)} 포지션이 없는데 남아 있던 봇 손절({fmt(o['price'])})을 "
                              "지웠습니다", 86_400)

    def _clean_orphans(self, open_orders: dict) -> None:
        left = []
        for c, oid in self.orphans:
            if oid not in open_orders:
                continue
            try:
                self.c.cancel_stop(oid)
            except G.GateRefused:
                pass
            except G.GateError:
                left.append([c, oid])
        self.orphans[:] = left

    def _close_now(self, c: str, s: dict, target: float, last: float, kind: str, lock: Optional[float]) -> None:
        what = f"잠금 +{lock:.0%} 자리" if lock is not None else "손절 자리"
        if s.get("closing") and self.c.now() - float(s["closing"].get("at") or 0) < CLOSING_WAIT_S:
            return                                        # sent: the position should be gone by the next loops
        try:
            self.c.close_market(c, f"gg-{coin_ko(c)}-{int(self.c.now())}")
        except G.GateUnknown as e:          # it may have run: the next loop reads the position again
            self.say_once(f"close:{c}", WARN, f"{coin_ko(c)} 가격 {fmt(last)}이 이미 {what} {fmt(target)}를 지나 시장가 종료를 "
                          f"보냈는데 응답이 없습니다. 다음 회차에 포지션을 다시 봅니다: {e}", 300)
            return
        except G.GateRefused as e:
            self.say_once(f"close:{c}", CRITICAL, f"{coin_ko(c)} 가격 {fmt(last)}이 이미 {what} {fmt(target)}를 지나 시장가로 "
                          f"닫으려 했지만 게이트가 거절했습니다(다음 회차에 다시): {e}", 300)
            return
        s["closing"] = {"kind": kind, "lock": lock, "target": target, "last": last, "at": self.c.now()}
        self.save()
        self.say(WARN, f"{coin_ko(c)} 가격 {fmt(last)}이 이미 {what} {fmt(target)}를 지나 있어 시장가로 닫았습니다"
                       "(손절이 있었다면 걸렸을 자리)")

    def _stop_gone(self, c: str, s: dict, p: dict) -> None:
        """Our stop is no longer resting while the position is open."""
        oid = s["stop_id"]
        try:
            rec = self.c.price_order(oid)
        except G.GateRefused:
            rec = {}
        if rec.get("status") == "open":                   # the list lagged
            return
        how = rec.get("finish_as") or ""
        if how == "cancelled":
            s["hands_off"] = True
            self.say(WARN, f"{coin_ko(c)} 봇 손절 주문({fmt(s['stop'])})이 직접 취소됐습니다. 이 포지션은 더 건드리지 않습니다"
                     "(새로 진입하거나 추가 진입하면 다시 지킵니다)")
            return
        if how == "succeeded":
            # it fired after the positions were read: the next loop sees the position gone. Still there when read again
            # (a part filled, or a new entry right after): start again from the position as it is now
            now_p = next((q for q in self.c.positions() if q["contract"] == c and q["side"] == s["side"]), None)
            if now_p is None:
                return
            self.say(WARN, f"{coin_ko(c)} 봇 손절이 발동했는데 포지션이 남아 있습니다. 지금 포지션 기준으로 다시 겁니다")
            self.coins.pop(c, None)
            self.pending.append(self._closed_row(c, s, f"봇 손절 발동({fmt(s['stop'])}) 뒤 포지션이 남음"))
            self._new(c, now_p)
            return
        s["stop_id"] = None
        self.say(WARN, f"{coin_ko(c)} 봇 손절 주문이 게이트에서 끝났습니다({how or rec.get('status') or '기록 없음'}"
                       f"{': ' + rec['reason'] if rec.get('reason') else ''}). 같은 자리 {fmt(s['stop'])}에 다시 겁니다")
        self._set_stop(c, s, s["stop"], s.get("kind") or "atr")

    def _liq_check(self, c: str, s: dict, p: dict) -> None:
        liq = p["liq"]
        if not liq or liq <= 0 or (s["stop"] - liq) * s["side"] > 0:
            return
        spec = self.c.contract(c)
        target = round_stop(liq + s["side"] * self.cfg.liq_keep * abs(s["entry"] - liq), spec["tick"], s["side"])
        if (target - s["stop"]) * s["side"] > spec["tick"] / 2 and self._set_stop(c, s, target, "liq", s.get("lock")):
            self.say(WARN, f"{coin_ko(c)} 청산가가 {fmt(liq)}로 바뀌어 손절이 그 너머가 됐습니다. 손절을 {fmt(target)}로 당겼습니다")

    # ------------------------------------------------------------------ ladder
    def _ladder(self, c: str, s: dict) -> None:
        lev = s.get("lev") or 0
        if lev <= 0:
            self.say_once(f"lev:{c}", WARN, f"{coin_ko(c)} 레버리지를 못 읽어 계단 익절을 못 셉니다(손절은 걸려 있음)")
            return
        best = self._best(c, s)
        side, entry, rt = s["side"], s["entry"], 2 * s["fee"]
        s["best"] = best
        roe = net_roe(side, entry, best, lev, rt)
        s["best_roe"] = roe
        want = self.cfg.ladder.lock_for(roe)
        cur = s.get("lock")
        if want is None or (cur is not None and want <= cur + 1e-12):
            return
        tick = self.c.contract(c)["tick"]
        target = round_stop(roe_price(side, entry, lev, want, rt), tick, side)
        old = s["stop"]
        if (target - old) * side <= tick / 2:
            s["lock"] = want                              # the stop is already tighter than this lock
            return
        if self._set_stop(c, s, target, "lock", lock=want):
            self.say(INFO, f"{coin_ko(c)} 잠금 순ROE +{want:.0%}: {'최고' if side > 0 else '최저'} {fmt(best)} (순ROE {pct(roe)}) "
                     f"→ 손절 {fmt(old)} → {fmt(target)}")

    def _best(self, c: str, s: dict) -> float:
        """The best price since the entry from 1m candles (the entry's own minute: only its close)."""
        side = s["side"]
        best = float(s.get("best") or s["entry"])
        now = self.c.now()
        start = max(int(s.get("read_min") or 0), int(now - LOOKBACK_S) // MIN_S * MIN_S)
        try:
            rows = self.c.candles(c, "1m", start_s=start, end_s=int(now))
        except G.GateError as e:
            self.say_once(f"kl:{c}", WARN, f"{coin_ko(c)} 1분봉을 못 읽어 이번엔 현재가만 봅니다: {e}", 1800)
            px = self.c.last_price(c)
            return max(best, px) if side > 0 else min(best, px)
        newest = None
        for t_ms, _o, h, l, cl in rows:
            t = t_ms // 1000
            if t < (s.get("entry_min") or 0):
                continue
            px = cl if t == s.get("entry_min") else (h if side > 0 else l)
            best = max(best, px) if side > 0 else min(best, px)
            newest = t
        if newest is not None:
            s["read_min"] = max(int(s.get("read_min") or 0), int(newest))
        return best

    # ------------------------------------------------------------------ closed
    def _closed(self, c: str, open_orders: dict) -> None:
        s = self.coins.pop(c)
        sid, rec = s.get("stop_id"), {}
        if sid is not None:
            try:
                rec = self.c.price_order(sid)
            except G.GateError:
                rec = {}
            if rec.get("status") == "open" or (not rec and sid in open_orders):
                self._cancel(c, sid)
        for oid in s.get("keep", []):
            if oid in open_orders:
                self._cancel(c, oid)
        cause = "직접 종료(또는 직접 건 익절·손절)"
        if s.get("closing"):
            cl = s["closing"]
            cause = (f"봇 시장가 종료(잠금 +{cl['lock']:.0%} 자리를 지나서)" if cl.get("lock") is not None
                     else "봇 시장가 종료(손절 자리를 지나서)")
        elif rec.get("finish_as") == "succeeded":
            cause = (f"봇 잠금 익절(순ROE +{s['lock']:.0%} 자리 {fmt(s['stop'])})" if s.get("lock") is not None
                     and s.get("kind") == "lock" else f"봇 손절({fmt(s['stop'])})")
        self.pending.append(self._closed_row(c, s, cause))

    def _closed_row(self, c: str, s: dict, cause: str) -> dict:
        return {"contract": c, "side": s["side"], "entry": s["entry"], "open_s": s["open_s"], "seen_s": s["seen_s"],
                "cause": cause, "until": self.c.now() + CLOSE_WAIT_S, "best_roe": s.get("best_roe"),
                "lock": s.get("lock")}

    def _report_pending(self) -> None:
        left = []
        for d in self.pending:
            row = None
            try:
                rows = self.c.closes(d["contract"], int(min(d["open_s"], d["seen_s"]) - 120))
                mine = [r for r in rows if (G.fnum(r.get("time")) or 0) >= d["seen_s"] - 5
                        and str(r.get("side") or "") == ("long" if d["side"] > 0 else "short")]
                row = max(mine, key=lambda r: G.fnum(r.get("time")) or 0) if mine else None
            except G.GateError:
                row = None
            if row is None and self.c.now() < d["until"]:
                left.append(d)
                continue
            head = f"{coin_ko(d['contract'])} {side_ko(d['side'])} 종료: {d['cause']}"
            if row is not None:
                pnl, fee = G.fnum(row.get("pnl")), G.fnum(row.get("pnl_fee"))
                out = G.fnum(row.get("short_price") if d["side"] > 0 else row.get("long_price"))
                head += (f"\n평단 {fmt(d['entry'])} → 종료 {fmt(out)}, 손익 {pnl:+.2f} USDT" if pnl is not None else "")
                head += (f" (수수료 {fee:+.2f} 포함)" if fee is not None and pnl is not None else "")
            else:
                head += "\n손익은 게이트 기록에서 아직 못 찾았습니다(앱의 포지션 기록을 봐 주세요)"
            self.say(INFO, head)
        self.pending[:] = left

    # ------------------------------------------------------------------ check (reads only)
    def plan_lines(self) -> list[str]:
        out = []
        positions = self.c.positions()
        orders = self.c.price_orders()
        mine = {s.get("stop_id") for s in self.coins.values()}
        if not positions:
            out.append("지금 열린 포지션이 없습니다. 친구가 진입하면 손절과 계단을 겁니다")
        for p in positions:
            c = p["contract"]
            if self.cfg.coins and c not in self.cfg.coins:
                out.append(f"- {coin_ko(c)}: 설정의 coins에 없어 안 지킴")
                continue
            if p["mode"] != "single":
                out.append(f"- {coin_ko(c)}: 양방향 모드 포지션이라 안 지킴")
                continue
            spec = self.c.contract(c)
            try:
                atr = self._atr(c)
                stop = round_stop(p["entry"] - p["side"] * self.cfg.stop_atr * atr, spec["tick"], p["side"])
                liq_note = ""
                if p["liq"] > 0 and (stop - p["liq"]) * p["side"] <= 0:
                    stop = round_stop(p["liq"] + p["side"] * self.cfg.liq_keep * abs(p["entry"] - p["liq"]),
                                      spec["tick"], p["side"])
                    liq_note = " (청산가 안쪽으로 당김)"
                atr_w = f"{TF_KO[self.cfg.atr_tf]} ATR {fmt(atr)}"
            except G.GateError as e:
                stop, liq_note, atr_w = None, "", f"ATR 못 셈: {e}"
            s = self.coins.get(c)
            out.append(f"- {coin_ko(c)} {side_ko(p['side'])} 평단 {fmt(p['entry'])} 수량 {p['size']:g} 레버 {p['lev']:g}"
                       f"{' (교차)' if p['cross'] else ''} 청산가 {fmt(p['liq'] or None)}: "
                       + (f"지금 봇 손절 {fmt(s['stop'])}" + (f" · 잠금 +{s['lock']:.0%}" if s.get('lock') else "")
                          if s else f"새로 걸 손절 {fmt(stop)}{liq_note} ({atr_w} × {self.cfg.stop_atr:g})"))
        others = [o for o in orders if o["id"] not in mine]
        if others:
            out.append("봇이 건 것이 아닌 조건부 주문(손대지 않음): " + ", ".join(
                f"{coin_ko(str(o['contract']))} {fmt(o['price'])}" for o in others))
        return out


# ====================================================================== CLI
def make_notify(cfg: Config):
    if not cfg.telegram or not os.environ.get("TELEGRAM_BOT_TOKEN") or not os.environ.get("TELEGRAM_CHAT_CRITICAL"):
        return lambda level, text: print(f"{level}: {text}", flush=True)
    from .notify import TelegramNotifier
    tg = TelegramNotifier()

    def send(level: str, text: str) -> None:
        print(f"{level}: {text}", flush=True)
        tg.send(level, text)
    return send


def build(cfg: Config, env, send=None) -> G.GateClient:
    key, secret = trading_keys(cfg, env)
    client = G.GateClient(key, secret, send=send)
    client.sync_time()
    return client


def cmd_check(args) -> int:
    cfg = load_config(args.config)
    client = build(cfg, dict(os.environ))
    g = Guard(cfg, client, lambda level, text: None, save=False)
    info = g.start_checks()
    acct = info["account"]
    print(f"{cfg.name}: 키 확인됨 · 서버 시각 차 {client.offset_s:+.1f}초 · 한 방향 모드 · "
          f"IP 묶음 {', '.join(info['ips']) if isinstance(info['ips'], list) else '(이 키로는 못 읽음: 키 화면에서 확인)'}")
    print(f"선물 잔고 {G.fnum(acct.get('total')) or 0:.2f} USDT (사용 가능 {G.fnum(acct.get('available')) or 0:.2f})")
    print(f"규칙: {cfg.words()}")
    for line in g.plan_lines():
        print(line)
    print("주문은 하나도 내지 않았습니다(읽기만).")
    return 0


def cmd_run(args) -> int:
    cfg = load_config(args.config)
    notify = make_notify(cfg)
    try:
        client = build(cfg, dict(os.environ))
        g = Guard(cfg, client, notify)
        g.start_checks()
    except Refused as e:
        notify(CRITICAL, f"[{cfg.name}] 시작 거부: {e}")
        raise
    g.say(INFO, f"시작: {cfg.words()}. 지켜보던 포지션 {len(g.coins)}개")
    g.run()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.gateguard", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "run"):
        sp = sub.add_parser(name)
        sp.add_argument("--config", required=True)
    args = ap.parse_args(argv)
    try:
        return {"check": cmd_check, "run": cmd_run}[args.cmd](args)
    except Refused as e:
        print(f"시작하지 않습니다: {e}", file=sys.stderr, flush=True)
        return 2
    except G.GateError as e:
        print(f"게이트 오류: {e}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
