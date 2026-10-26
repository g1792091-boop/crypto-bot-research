"""The '믹스 30분 봇' world (owners 10-25 night, docs/mixchop-ko.md) for the live site's 믹스 봇 screens
(tests/test_dash_livemix.py), made by the bot's own code: paperbot/mixchop.py's Bot over the deploy configs (coins, risk,
entry blocks), the live one on a fake WOO X Pro account (tests/test_mixchop.py FakeWoo: market orders, resting stops,
the stop protocol), the paper one on its PaperBroker with the service's paper_equity save; the 30m signals are handed
in per close (mixchop.evaluate replaced by a plan), the bars by hand. The macro calendar is the world's own file.

Live (KST): Sat 10/24 10:00 start · Sun 10/25 14:00 ETH short (weekend: skipped) and a DOGE colour change refused ·
Mon 10/26 09:00 SOL long entered (XRP the same bar: skipped), 09:30 ladder step 1 (BCH skipped: 보유 중), 09:50 the
stop fires (계단 익절, +$0.02), 10:30 a DOGE long skipped by the bot's own stop file, 11:00 XRP short entered, 11:20
stopped (−$0.13) · 12:00 a restart (ZEC's leverage refused: ZEC off) · 22:00 SOL long in the Nasdaq-open block ·
Tue 10/27 09:00 BCH long entered, 09:30 ladder step 1 (DOGE refused, ETH 보유 중), 10:00 three exchange read failures,
10:30 the stop gone missing and placed again, 12:00 the last close: BCH open at NOW (12:10).
Paper: Mon 10/26 08:00 start · 09:00 SOL long · 09:30 ladder · 10:00 out at the lock (the bar's low) · 11:00 XRP short
· 11:30 stopped · Tue 12:00 the last close."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paperbot import events as EV  # noqa: E402
from paperbot import mixchop as M  # noqa: E402
from tests.test_mixchop import FakeWoo  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIN, H, DAY = 60_000, 3_600_000, 86_400_000
KST0 = 1_792_508_400_000                             # 2026-10-21 00:00 KST (a Wednesday)


def K(day: int, hour: int = 0, minute: int = 0, sec: int = 0) -> int:
    """2026-10-<day> <hour>:<minute>:<sec> KST in UTC ms."""
    return KST0 + (day - 21) * DAY + hour * H + minute * MIN + sec * 1000


NOW = K(27, 12, 10)                                     # Tuesday 12:10 KST
EVENTS = ("ts_utc,kind,source_url\n2026-10-28T18:00:00Z,FOMC,https://www.federalreserve.gov/x\n"
          "2026-10-29T12:30:00Z,PCE,https://www.bea.gov/x\n")


def config(folder: str, mode: str) -> str:
    """The deploy config of ``mode`` with the world's files (state, log, stop files) in ``folder``."""
    src = os.path.join(ROOT, "deploy", "mixchop.live.json" if mode == "mainnet" else "mixchop.paper.json")
    with open(src, encoding="utf-8") as fh:
        raw = json.load(fh)
    tag = "live" if mode == "mainnet" else "paper"
    # this world plays the friend's design (risk sizing, the coins' ladder at 30m closes, the friend's rule and stops):
    # the owners' 10-26 options (margin_frac, the net-ROE ladder, 1m follow-up, the second rule, one ATR multiple) are
    # tested in tests/test_mixchop.py, test_mixchop_1026_site.py and test_mixchop_st.py
    for k in ("margin_frac", "ladder", "ladder_every_s", "rules", "stop_atr"):
        raw.pop(k, None)
    raw["max_notional_usd"] = 500
    raw.update(state=os.path.join(folder, f"{tag}-state.json"), log=os.path.join(folder, f"{tag}-log.jsonl"),
               kill_file=os.path.join(folder, "STOP"), own_stop_file=os.path.join(folder, f"{tag}.STOP"), telegram=False)
    path = os.path.join(folder, f"{tag}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(raw, fh)
    return path


def ev(sym: str, ce: int, side: int, close: float = 100.0, dist: float = 1.0, why: str = "", colour: str = "",
       r30: float = 60.0, r1h: float = 55.0) -> dict:
    colour = colour or ("cyan" if side > 0 else "purple")
    return {"symbol": sym, "close_ms": ce, "side": side, "why": why, "to_cyan": colour == "cyan", "to_purple": colour == "purple",
            "gold": colour == "cyan", "close": close, "atr": dist, "stop_dist": dist, "stop_pct": round(dist / close * 100, 3),
            "liq_ok": True, "avg_rsi_30m": r30, "avg_rsi_1h": r1h, "trend_close_ms": ce}


class World:
    """A clock, a plan of signals per (coin, close), 30m bars per coin; mixchop.evaluate replaced while it runs."""

    def __init__(self):
        self.t = 0
        self.plan: dict = {}
        self.bars: dict = {}

    def now(self) -> int:
        return self.t

    def fetch(self, symbol: str, tf: str, n: int) -> list:
        if n == M.BARS:                                     # the signal read: Binance has opened the next bar
            return [[self.t - self.t % M.MIN30, 1.0, 1.0, 1.0, 1.0]]
        return list(self.bars.get(symbol, []))

    def evaluate(self, co, b30, b1h, ce):
        return dict(self.plan.get((co.symbol, ce)) or {"symbol": co.symbol, "close_ms": ce, "side": 0, "why": "색 변화 없음"})

    def close(self, bot, ce: int, *signals) -> None:
        for s in signals:
            self.plan[(s["symbol"], ce)] = s
        self.t = ce + 5000
        bot.on_close(ce)


class NoZec(FakeWoo):
    """WOO X Pro refuses ZEC's leverage (the bot turns ZEC off at its start)."""

    def leverage(self, s, lev):
        if s == "ZECUSDT":
            raise RuntimeError("leverage 20 not allowed")
        return super().leverage(s, lev)


def paper_bot(cfg, w: World, broker):
    """mixchop.cmd_run's paper bot: its save also writes the paper equity (it survives restarts)."""
    bot = M.Bot(cfg, broker, w.fetch, w.now, sleep=lambda s: None)
    orig = bot.save

    def save_with_equity():
        orig()
        st = M.read_state(cfg.state)
        st["paper_equity"] = broker.equity()
        M.write_state(cfg.state, st)
    bot.save = save_with_equity
    return bot


def build_live(folder: str, w: World) -> dict:
    cfg = M.load_config(config(folder, "mainnet"))
    fake = NoZec()
    w.t = K(24, 10, 0, 10)
    bot = M.Bot(cfg, M.WooBroker(fake, cfg.coins), w.fetch, w.now, sleep=lambda s: None)
    bot.start()
    w.close(bot, K(24, 10, 30), ev("SOLUSDT", K(24, 10, 30), 1))                                    # Saturday: weekend
    w.close(bot, K(25, 14, 0), ev("ETHUSDT", K(25, 14, 0), -1, close=2500.0, dist=20.0),
            ev("DOGEUSDT", K(25, 14, 0), 0, close=0.2, why="1시간 평균 RSI 조건 안 맞음", colour="cyan", r1h=40.0))
    w.close(bot, K(26, 9, 0), ev("SOLUSDT", K(26, 9, 0), 1), ev("XRPUSDT", K(26, 9, 0), 1, close=2.0, dist=0.02))
    fake.px = 103.6
    w.bars["SOLUSDT"] = [[K(26, 9, 0), 100.0, 103.8, 99.5, 103.6]]
    w.close(bot, K(26, 9, 30), ev("BCHUSDT", K(26, 9, 30), 1))                                      # ladder 1; BCH: 보유 중
    fake.fire("SOLUSDT")
    fake.eq = 50.02
    w.t = K(26, 9, 50)
    bot.poll()                                                                                      # the stop fired: +0.02
    open(cfg.own_stop_file, "w").close()
    w.close(bot, K(26, 10, 30), ev("DOGEUSDT", K(26, 10, 30), 1, close=0.2, dist=0.002))           # its own stop file
    os.remove(cfg.own_stop_file)
    fake.px = 2.0
    w.close(bot, K(26, 11, 0), ev("XRPUSDT", K(26, 11, 0), -1, close=2.0, dist=0.02, r30=40.0, r1h=45.0))
    fake.fire("XRPUSDT")
    fake.eq = 49.89
    w.t = K(26, 11, 20)
    bot.poll()                                                                                      # stopped: −0.13
    w.t = K(26, 12, 0)
    fake.eq = 49.95                                                                                 # (funding, a transfer)
    bot = M.Bot(cfg, M.WooBroker(fake, cfg.coins), w.fetch, w.now, sleep=lambda s: None)
    bot.start()                                                                                     # restart: ZEC refused
    w.close(bot, K(26, 22, 0), ev("SOLUSDT", K(26, 22, 0), 1))                                      # Nasdaq open block
    fake.px = 100.0
    w.close(bot, K(27, 9, 0), ev("BCHUSDT", K(27, 9, 0), 1))
    fake.px = 103.0
    w.bars["BCHUSDT"] = [[K(27, 9, 0), 100.0, 103.8, 99.6, 103.0]]
    w.close(bot, K(27, 9, 30), ev("DOGEUSDT", K(27, 9, 30), 0, close=0.2, why="30분 평균 RSI 조건 안 맞음", r30=48.0),
            ev("ETHUSDT", K(27, 9, 30), 1, close=2500.0, dist=20.0))
    for i in range(3):
        w.t = K(27, 10, 0, i)
        bot.log("read_failed", symbol="BCHUSDT", error="timeout")
    fake.cancel_all_algo("BCHUSDT")
    w.t = K(27, 10, 30)
    bot._last_stop_check = -1e9
    bot.poll()                                                                                      # stop missing: placed again
    w.bars["BCHUSDT"] += [[K(27, 9, 30) + i * M.MIN30, 103.0, 103.4, 101.0, 102.0] for i in range(5)]
    w.close(bot, K(27, 12, 0))
    return {"cfg": cfg, "fake": fake, "bot": bot}


def build_paper(folder: str, w: World) -> dict:
    cfg = M.load_config(config(folder, "paper"))
    broker = M.PaperBroker(50.0, cfg.taker_fee)
    w.t = K(26, 8, 0, 10)
    bot = paper_bot(cfg, w, broker)
    bot.start()
    w.bars = {"SOLUSDT": [[K(26, 9, 0), 100.0, 103.8, 99.5, 103.6], [K(26, 9, 30), 103.0, 103.2, 100.0, 100.1]],
              "XRPUSDT": [[K(26, 11, 0), 2.0, 2.03, 1.99, 2.025]]}
    w.close(bot, K(26, 9, 0), ev("SOLUSDT", K(26, 9, 0), 1), ev("XRPUSDT", K(26, 9, 0), 1, close=2.0, dist=0.02))
    w.close(bot, K(26, 9, 30), ev("BCHUSDT", K(26, 9, 30), 1))                                      # ladder 1; BCH: 보유 중
    w.close(bot, K(26, 10, 0))                                                                      # out at the lock
    w.close(bot, K(26, 11, 0), ev("XRPUSDT", K(26, 11, 0), -1, close=2.0, dist=0.02, r30=40.0, r1h=45.0))
    w.close(bot, K(26, 11, 30))                                                                     # stopped at 2.02
    w.close(bot, K(27, 12, 0))
    return {"cfg": cfg, "broker": broker, "bot": bot}


def build(folder: str) -> dict:
    """Both bots' files in ``folder`` (the world's macro calendar in place while they run)."""
    os.makedirs(folder, exist_ok=True)
    cal = os.path.join(folder, "macro_events.csv")
    with open(cal, "w", encoding="utf-8") as fh:
        fh.write(EVENTS)
    keep_eval, keep_path = M.evaluate, EV.PATH
    w = World()
    try:
        M.evaluate = w.evaluate
        EV.PATH = cal
        EV.reset()
        live = build_live(folder, w)
        w.plan, w.bars = {}, {}
        paper = build_paper(folder, w)
    finally:
        M.evaluate = keep_eval
        EV.PATH = keep_path
        EV.reset()
    return {"folder": folder, "calendar": cal, "live": live, "paper": paper, "env": env_of(folder)}


def env_of(folder: str) -> dict:
    """The site's environment variables for the world's files (dash/more/livemix.py ENV)."""
    j = lambda n: os.path.join(folder, n)          # noqa: E731
    return {"PAPERBOT_MIX_STATE": j("live-state.json"), "PAPERBOT_MIX_LOG": j("live-log.jsonl"), "PAPERBOT_MIX_CONFIG": j("live.json"),
            "PAPERBOT_MIX_PAPER_STATE": j("paper-state.json"), "PAPERBOT_MIX_PAPER_LOG": j("paper-log.jsonl"),
            "PAPERBOT_MIX_PAPER_CONFIG": j("paper.json"),
            "PAPERBOT_MIX_REPO_CONFIG": os.path.join(ROOT, "deploy", "mixchop.live.json"),
            "PAPERBOT_MIX_PAPER_REPO_CONFIG": os.path.join(ROOT, "deploy", "mixchop.paper.json")}


def rows(path: str) -> list:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(x) for x in fh if x.strip()]
