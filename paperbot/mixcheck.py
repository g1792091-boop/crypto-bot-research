"""믹스 30분 봇 점검 (owners 10-25 night: "친구 매매봇도 연구분석이나 손실 분석 그런부분들은 없어?? 매매법 성공을 위해서 필요한
부분들 있을꺼 같은데" -> "전부 다 만들어줘"): read-only analysis of the '믹스 30분 봇' (paperbot/mixchop.py: the second WOO X Pro
account, real money) with its paper twin next to it (docs/mixchop-ko.md 8장).

    python -m paperbot.mixcheck morning [--day YYYY-MM-DD] [--dry-run] [--no-replay] [--force]   # 09:05 KST
    python -m paperbot.mixcheck pass [--dry-run]                                                 # every 5 minutes
    python -m paperbot.mixcheck band                                                             # prints the band now
    python -m paperbot.mixcheck show                                                             # the last morning text

A. 아침 점검 (``morning``, deploy/paperbot-mixcheck.timer, 00:05 UTC = 09:05 KST): ONE Telegram message about the
   previous KST day (00:00 -> 24:00 KST; ``--day`` names it), quiet INFO, WARN when something is wrong: the 30m colour
   changes and signals the live bot logged, its entries, the skipped signals by reason (entry block and which, too small
   for the minimum order, holding, the stop files, the floor, the liquidation check), live against paper (the same
   entries and exits, each difference with the other side's own reason when it logged one), the entry fill against the
   signal bar's close and the taker fee estimate, whether a stop rested the whole time (stop failures, stops placed
   again, closes for protection, unknown positions, restarts), the exchange read failures, the equity against the start
   and the room above the floor; the day's closed trades with their card verdicts; the luck band (C) and the signal
   replay (D). It is kept in <dir>/last-morning.json (the 믹스 성적 screen shows it); a day is sent once (``--force``).
B. 손실 카드 (``pass``, deploy/paperbot-mixcheck-pass.timer, every 5 minutes): each closed live trade once, a few
   minutes after the close: a losing one gets a card (the plan: one stop-out = ``risk_pct`` of the equity plus the
   fees; the loss in R; normal stop-out as designed, or abnormal when it is well past the plan, with the causes the
   bot's own log and the numbers show: the exit past the stop (a gap or slippage, or far past it), the entry worse than
   the signal close, a stop that was missing or placed again, a close for protection or while the bot was down, a size
   taken from the exchange (partial fill, late fill), an entry block that started right after the entry or an exit
   inside one, a restart while holding; the paper twin's result on the same signal; the place in the losing streak);
   a winning one a short line. The bot does not log its exit fill: the exit price is worked back from the equity
   change (the entry fill, the size and WOO X Pro's taker fee on both sides; funding is in it too), said so. Its own
   state, <dir>/state.json: the trades already told, and what the bot's state file said at each pass (its
   ``last_close_ms``: the signal replay knows from it which 30-minute closes the bot handled).
C. 운이냐 고장이냐 (``band``): the live record (trades, wins, R sum, the current losing streak, the drawdown from its peak
   in R; R = the equity change of a trade over ``risk_pct`` of the equity before it) placed in the 5-year replay of the
   live rules with the bot's own code (research/mixchop5y/summary.json, research/mixchop5y/replay.py): over every run of
   the same number of trades in the replay, how often the record is this bad or worse. 정상 범위 (10 % or more), 드묾
   (2-10 %), 아주 드묾 (under 2 %: 설계와 다르게 돌고 있을 수 있어요), with the numbers. Without the summary: a Bernoulli model
   of the design notes' win rates, labelled as such (wins and the losing streak only).
D. 신호 다시 계산 (in ``morning``; ``--no-replay`` skips it): the previous day's 30-minute closes recomputed with
   mixchop.evaluate on Binance's closed bars (the public klines, no key) and put against the live log: a colour change
   or a signal the bot never recorded (it did not handle that close: down or late; its bars were late; or it saw it
   differently), a different decision, a signal without an entry and without a recorded reason. "놓친 신호 0개" or the
   list. TradingView itself cannot be read automatically; this is the bot's own formula on Binance's bars, and
   ``python -m paperbot.mixchop signals`` stays the manual comparison with the chart.

Two mix bots (owners 10-29, docs/mixbybit-ko.md): the same checks for the '바이비트 봇' (the Bybit account, the friend's
OBV / Stoch RSI rules) run as their own units (deploy/paperbot-mixbybitcheck*.service: ``PAPERBOT_MIX_BOT=bybit``, its
folder /var/lib/paperbot/mixbybitcheck). Every word that names the bot, its exchange (the app to look in), its unit and
its taker fee comes from its own config (``name``, ``exchange``, ``taker_fee``: words_of); its rules' signals are
counted and replayed as its log writes them (the OBV turn, the Stoch RSI ●); it has no 5-year replay, so no luck band.
The friend bot's checks and words are as they were.

Read-only towards the bot and the exchange: the bot's config, state file and log are read as files (the live site's own
readers, paperbot/dash/more/livemix.py), never written; no exchange account, no key, no order. The only network calls are
Binance's public klines (D) and Telegram. Telegram: the live bot's own bot and chats from the environment
(/etc/paperbot/live-telegram.env, loaded by the systemd unit; this module never opens an env file); without them the
text goes to the journal. Writes only <dir> (default /var/lib/paperbot/mixcheck, ``PAPERBOT_MIXCHECK_DIR``).
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import math
import os
import sys
import time
from typing import Any, Callable, Optional

from . import mixchop as M
from .dash.more import livemix as X

MIN, H1, DAY = 60_000, 3_600_000, 86_400_000
KST_MS = 9 * H1
DIR = "/var/lib/paperbot/mixcheck"
DIR_ENV = "PAPERBOT_MIXCHECK_DIR"
SUMMARY = os.path.join(X.REPO, "research", "mixchop5y", "summary.json")
SUMMARY_ENV = "PAPERBOT_MIX_REPLAY_SUMMARY"
TAKER = 0.00042                     # WOO X Pro's taker fee, each side (the live bot's market orders)
PASS_TAIL = 4 * 1024 * 1024         # the pass reads the logs' last 4 MB (an open trade's entry row is in it)
FIRST_BACK_MS = 3 * H1              # the first pass ever: closes older than this are only marked as told
KEEP_KEYS = 600
OBS_KEEP_MS = 4 * DAY
SEND_TRIES = 3                      # a card Telegram refused is tried again on the next passes, at most this often
# loss card: normal while the loss is within TOL_R of the plan (the stop at exit, the size, both fees)
TOL_R = 0.25
BIG_R = 1.0
GAP_FRAC = 0.001                    # the worked-back exit past the stop by more than 0.1 % of the price
FAR_GAP_FRAC = 0.005                # ... by more than 0.5 %: the stop fired far past its price
SLIP_FRAC = 0.0015                  # the entry fill worse than the signal close by more than 0.15 %
RULE_TAG = {"st": "(슈퍼트렌드·스톡RSI)",  # the second rule's lines say whose they are (owners 10-26)
            "obv": "(OBV 진한색)", "srsi": "(스톡RSI 50선)"}            # the 바이비트 봇's (owners 10-29)
# what a signal row of each rule is, for the replay's lines (the friend's colour change, the Stoch RSI cross / ●, the OBV
# light -> dark turn)
RULE_WHAT = {"mix": "색 변화", "st": "스톡RSI 크로스", "srsi": "스톡RSI ●", "obv": "OBV 연한→진한"}
BLOCK_NEAR_MS = 60 * MIN            # an entry block that started within an hour after the entry
# luck band: the share of the replay's runs that are this bad or worse
RARE, VERY_RARE = 0.10, 0.02
VERDICT_KO = {"ok": "정상 범위", "rare": "드묾", "very_rare": "아주 드묾: 설계와 다르게 돌고 있을 수 있어요"}
VERDICT_TONE = {"ok": "good", "rare": "warn", "very_rare": "bad"}
SMALL_N = 10
# the design notes' win rates per coin (docs/mixchop-ko.md 7장): the Bernoulli fallback's rate is their mean
DESIGN_WIN = {s["symbol"]: s["win"] for s in X.BACKTEST["rows"]}
BERNOULLI_P = sum(DESIGN_WIN.values()) / len(DESIGN_WIN)
# the log's kinds of a stop that was not resting for a while / placed again
STOP_KINDS = ("stop_failed", "protect_failed", "protect_close_failed", "reconcile_failed", "stop_replaced")
READ_KINDS = ("read_failed", "poll_failed", "bars_failed", "bars_missing", "close_failed", "cancel_failed")
READ_KO = {"read_failed": "거래소 읽기", "poll_failed": "점검 중 거래소 읽기", "bars_failed": "계단용 바이낸스 봉", "bars_missing": "신호용 바이낸스 봉",
           "close_failed": "30분봉 처리", "cancel_failed": "남은 손절 취소"}
ODD_EXITS = {"protect": "손절을 못 걸어 시장가로 닫았어요", "closed_while_down": "봇이 꺼진 사이에 닫혔어요",
             "manual": "직접 닫았어요", "wrong_side": "방향이 기록과 달라 닫았어요"}
WEEK_KO = "월화수목금토일"
SKIP_ORDER = ("block", "small", "held", "same_bar", "halt", "liq", "other")


# ====================================================================== small helpers
def _f(x: Any) -> Optional[float]:
    return X._f(x)


def _i(x: Any) -> Optional[int]:
    return X._i(x)


def usd(x: Optional[float], d: int = 3) -> str:
    """"+$0.020" / "−$0.130"; "모름"."""
    if x is None or not math.isfinite(x):
        return "모름"
    return f"{'+' if x > 0 else '−' if x < 0 else ''}${abs(x):,.{d}f}"


def money(x: Optional[float]) -> str:
    return "모름" if x is None else f"${x:,.2f}"


def r_ko(x: Optional[float], d: int = 1) -> str:
    if x is None or not math.isfinite(x):
        return "R 모름"
    return f"{'+' if x > 0 else '−' if x < 0 else ''}{abs(x):.{d}f}R"


def pct(x: Optional[float], d: int = 2, sign: bool = True) -> str:
    if x is None or not math.isfinite(x):
        return "모름"
    s = ("+" if x > 0 else "−" if x < 0 else "") if sign else ("−" if x < 0 else "")
    return f"{s}{abs(x) * 100:.{d}f}%"


def px(x: Optional[float]) -> str:
    return "모름" if x is None else f"{x:.6g}"


def kst(ms: Optional[int]) -> str:
    return "?" if ms is None else M.kst(int(ms))


def hold_ko(ms: Optional[int]) -> str:
    if ms is None:
        return "?"
    m = max(0, int(ms) // MIN)
    if m < 60:
        return f"{m}분"
    if m < 48 * 60:
        return f"{m // 60}시간" + (f" {m % 60}분" if m % 60 else "")
    return f"{m // 1440}일 {(m % 1440) // 60}시간"


def day_label(w0: int) -> str:
    t = time.gmtime((w0 + KST_MS) / 1000)
    return f"{t.tm_mon}/{t.tm_mday}({WEEK_KO[t.tm_wday]})"


def kst_day_of(day: Optional[str], now: int) -> int:
    """The UTC ms of 00:00 KST of ``day`` (YYYY-MM-DD, a KST date); None: the day before today (KST)."""
    if day:
        import calendar
        y, m, d = (int(x) for x in day.split("-"))
        return calendar.timegm((y, m, d, 0, 0, 0)) * 1000 - KST_MS
    return ((now + KST_MS) // DAY - 1) * DAY - KST_MS


def prof_env() -> "X.Profile":
    """The mix bot a command checks: ``PAPERBOT_MIX_BOT`` (its own units say "bybit"), else the friend bot."""
    return X.PROFILES.get(os.environ.get(X.BOT_ENV) or "mix", X.MIX)


def state_dir(arg: Optional[str] = None, prof: Optional["X.Profile"] = None) -> str:
    prof = prof or prof_env()
    return arg or os.environ.get(prof.check_env) or prof.check_dir


def read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path: str, d: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, default=float)
    os.replace(tmp, path)


@contextlib.contextmanager
def locked(dir_: str):
    """The pass (every 5 minutes) and the morning check both change <dir>/state.json: each read-change-write holds this
    lock, so neither puts back an older copy over the other's (a card told twice, a morning marked unsent)."""
    os.makedirs(dir_, exist_ok=True)
    with open(os.path.join(dir_, "state.lock"), "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def notifier(dry: bool) -> Optional[Callable[[str, str], bool]]:
    """The live bot's own Telegram bot and chats (the environment: /etc/paperbot/live-telegram.env through the unit, as
    paperbot/mixchop.py make_notify); the journal without them; None for a dry run."""
    if dry:
        return None
    if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_CRITICAL"):
        from .notify import TelegramNotifier
        tg = TelegramNotifier()
        return lambda level, text: bool(tg.send(level, text))

    def console(level: str, text: str) -> bool:
        print(f"{level}: {text}", flush=True)
        return True
    return console


# ====================================================================== the bots' files (the live site's readers)
def load(p: Optional[dict] = None, now: Optional[int] = None, tail: Optional[int] = None) -> dict:
    p = p or X.paths()
    now = int(time.time() * 1000) if now is None else int(now)
    return {bid: X.load_bot(bid, p[bid], now, tail) for bid in ("live", "paper")} | {"now": now, "bot": X.prof_of(p).id}


def words_of(data: dict) -> dict:
    """The bot's own words (owners 10-29: two bots run this code): its name (its config's ``name``), its short name in
    the cards ("믹스" for the friend bot), its exchange (the app to look in), its taker fee (its config's ``taker_fee``),
    its unit."""
    prof = X.PROFILES.get(data.get("bot") or "mix", X.MIX)
    cfg = ((data.get("live") or {}).get("conf") or {}).get("cfg") or ((data.get("paper") or {}).get("conf") or {}).get("cfg")
    fee = float(getattr(cfg, "taker_fee", TAKER)) if cfg is not None else TAKER
    return {"name": prof.name, "short": "믹스" if prof is X.MIX else prof.name, "ex": prof.exchange_ko, "fee": fee,
            "unit": prof.bots[0][2], "mix": prof is X.MIX, "guide": prof.guide}


def rows_of(b: dict) -> list:
    return (b["lg"].get("rows") or []) if b["lg"].get("state") == "ok" else []


def entries_of(rows: list) -> dict:
    return {(r.get("symbol"), _i(r.get("opened_ms"))): r for r in rows if r.get("kind") in ("entry", "adopted")}


def risk_of(b: dict) -> float:
    cfg = b["conf"].get("cfg")
    return float(cfg.risk_pct) if cfg is not None else 0.25


def plan_changed(cfg: Any) -> bool:
    """Owners 10-26: sized by margin or a net-ROE ladder: the 5-year replay (risk sizing, the coins' ladder) is not
    this plan's reference, so the luck band and the losing-run odds are not given."""
    return cfg is not None and (float(getattr(cfg, "margin_frac", 0) or 0) > 0 or getattr(cfg, "ladder", None) is not None)


PLAN_CHANGED_KO = "설정을 바꿔서(증거금 비율·순ROE 계단) 5년 재생과 비교하지 않아요 · 실거래 기록이 쌓이면 그 기록끼리 봐요"


def live_rs(trades: list) -> list:
    """The R of the closed trades with a known P&L, oldest first."""
    return [t["r"] for t in sorted(trades, key=lambda t: t.get("exit_ms") or 0) if t.get("r") is not None]


# ====================================================================== B. the loss card
def implied_exit(side: int, entry: float, qty: float, pnl: float, fee: float = TAKER) -> Optional[float]:
    """The exit price that turns ``entry`` into ``pnl`` for ``qty`` with the taker fee on both sides
    (pnl = side x (exit - entry) x qty - fee x qty x (entry + exit)); None when it cannot be told."""
    if not (entry and qty and side) or pnl is None:
        return None
    if side > 0:
        v = (pnl / qty + entry * (1 + fee)) / (1 - fee)
    else:
        v = (entry * (1 - fee) - pnl / qty) / (1 + fee)
    return v if v > 0 else None


def streak_at(trades: list, t: dict) -> int:
    """The losing run ending at ``t`` (counting it) in the record, oldest first."""
    n = 0
    for x in sorted(trades, key=lambda z: z.get("exit_ms") or 0):
        if x.get("pnl") is None:
            continue
        n = n + 1 if x["pnl"] <= 0 else 0
        if x is t:
            return n
    return n


def first_block_after(cfg: Any, t0: int, span: int = BLOCK_NEAR_MS) -> Optional[tuple]:
    """(minute, words) of the first entry-block minute in (t0, t0 + span] by the bot's own rules; None."""
    if cfg is None:
        return None
    t = int(t0) - int(t0) % MIN + MIN
    while t <= t0 + span + 4 * MIN:
        if M.entry_block(cfg, t):
            a = max(int(t0) - int(t0) % MIN + MIN, t - 4 * MIN)
            while not M.entry_block(cfg, a):
                a += MIN
            return (a, M.entry_block(cfg, a)) if a <= t0 + span else None
        t += 5 * MIN
    return None


def paper_twin(en: Optional[dict], p_entries: dict, p_trades: list) -> Optional[dict]:
    """The paper bot's trade on the same signal (coin, side, signal bar): its R and how it ended, or that it is still
    open / not there."""
    if en is None:
        return None
    sc = _i(en.get("signal_close_ms"))
    for (sym, om), r in p_entries.items():
        if sym == en.get("symbol") and _i(r.get("side")) == _i(en.get("side")) and sc is not None and _i(r.get("signal_close_ms")) == sc:
            tr = next((t for t in p_trades if t["symbol"] == sym and t["opened_ms"] == om), None)
            if tr is None:
                return {"state": "open", "ko": "모의: 같은 신호로 들어가 아직 보유 중"}
            return {"state": "closed", "r": tr.get("r"), "pnl": tr.get("pnl"), "why": tr.get("why"), "exit": tr.get("exit"),
                    "step": tr.get("step"), "ko": f"모의: 같은 신호에서 {r_ko(tr.get('r'))} ({tr.get('why_ko')}"
                                                  + (f" {px(tr.get('exit'))}" if tr.get("exit") is not None else "") + ")"}
    return {"state": "none", "ko": "모의에는 이 신호의 거래가 없어요"}


def card(t: dict, en: Optional[dict], rows: list, cfg: Any, risk_pct: float, twin: Optional[dict] = None,
         streak: int = 0, band_streak: Optional[dict] = None, fee: float = TAKER, ex: str = "WOO X Pro") -> dict:
    """One closed live trade read against its plan (module docstring B). ``t``: livemix.trades_of's trade; ``en``: its
    entry row; ``rows``: the live log (the rows while it was held are looked at)."""
    side, e, q, eb, pnl = t.get("side") or 0, t.get("entry"), t.get("qty"), t.get("equity_before"), t.get("pnl")
    om, xm = t.get("opened_ms"), t.get("exit_ms")
    dist = _f((en or {}).get("stop_dist"))
    sig_close = _f((en or {}).get("signal_close"))
    stop_x = t.get("stop")
    by_margin = cfg is not None and float(getattr(cfg, "margin_frac", 0) or 0) > 0
    if by_margin and q and dist:                    # owners 10-26: the stop's loss of this entry is the unit
        risk_usd = q * dist
        risk_pct = risk_usd / eb * 100.0 if eb else risk_pct
    else:
        risk_usd = eb * risk_pct / 100.0 if eb else None
    exit_px = t.get("exit") if t.get("exit") is not None else (implied_exit(side, e, q, pnl, fee) if e and q and pnl is not None else None)
    exit_src = "log" if t.get("exit") is not None else ("equity" if exit_px is not None else None)
    plan = (side * (stop_x - e) * q - fee * q * (e + stop_x)) if (stop_x and e and q and side) else None
    plan_r = plan / risk_usd if plan is not None and risk_usd else None
    fees = fee * q * (e + (exit_px or e)) if e and q else None
    gap = side * (stop_x - exit_px) / stop_x if (stop_x and exit_px and side) else None
    slip = side * (e - sig_close) / sig_close if (e and sig_close and side) else None
    r = t.get("r")
    held = [x for x in rows if om is not None and xm is not None and om - 1000 <= (_i(x.get("ts")) or 0) <= xm + 1000]
    causes, notes = [], []
    if t.get("why") in ODD_EXITS:
        causes.append({"id": "exit_" + str(t["why"]), "ko": ODD_EXITS[t["why"]]})
    if gap is not None and gap > FAR_GAP_FRAC:
        causes.append({"id": "far", "ko": f"손절이 가격을 한참 지나서 체결됐어요: 손절 {px(stop_x)}, 청산 추정 {px(exit_px)} ({pct(gap, sign=False)} 더 밀림)"})
    elif gap is not None and gap > GAP_FRAC:
        causes.append({"id": "gap", "ko": f"손절가보다 {pct(gap, sign=False)} 더 밀려 나갔어요 (급하게 움직였거나 갭): 손절 {px(stop_x)}, 청산 추정 {px(exit_px)}"})
    if slip is not None and slip > SLIP_FRAC:
        causes.append({"id": "slip", "ko": f"진입이 신호 종가 {px(sig_close)}보다 {pct(slip, sign=False)} 불리하게 체결됐어요 ({px(e)})"})
    stops = [x for x in held if x.get("kind") in STOP_KINDS]
    if stops:
        failed = [x for x in stops if x.get("kind") != "stop_replaced"]
        causes.append({"id": "stop", "ko": ("손절 주문을 걸지 못한 적이 있어요" if failed else "손절이 없거나 모자라 다시 걸었어요")
                       + f" ({len(stops)}번, {kst(_i(stops[0].get('ts')))}부터)"})
    if (en or {}).get("kind") == "adopted" or any(x.get("kind") == "qty_adopted" for x in held):
        causes.append({"id": "size", "ko": "체결을 늦게 확인했거나 수량을 거래소 기준으로 맞췄어요 (일부 체결 등)"})
    if any(x.get("kind") in ("move_failed", "ladder_closed") for x in held):
        causes.append({"id": "ladder", "ko": "계단 손절을 제때 옮기지 못했어요"})
    starts = [x for x in held if x.get("kind") == "start" and om is not None and (_i(x.get("ts")) or 0) > om + 1000]
    if starts:
        causes.append({"id": "restart", "ko": f"보유 중에 봇이 다시 켜졌어요 ({', '.join(kst(_i(x.get('ts'))) for x in starts[:3])})"})
    near = first_block_after(cfg, om) if om is not None else None
    if near is not None:
        causes.append({"id": "block_near", "ko": f"진입 {max(1, round((near[0] - om) / MIN))}분 뒤 진입 금지 시간이 시작됐어요: "
                                                 f"{X.BLOCK_KO.get(X.block_kind(near[1]), near[1])} (변동이 큰 시간대)"})
    if xm is not None and cfg is not None:
        w = M.entry_block(cfg, int(xm))
        if w:
            causes.append({"id": "block_exit", "ko": f"청산이 진입 금지 시간 안에서 일어났어요: {X.BLOCK_KO.get(X.block_kind(w), w)}"})
    reads = [x for x in held if x.get("kind") in ("read_failed", "poll_failed")]
    if reads:
        notes.append(f"보유 중 거래소를 {len(reads)}번 못 읽었어요")
    if pnl is None:
        verdict, tone, ko = "unknown", "thin", "손익 모름 (청산 뒤 잔고를 못 읽었어요)"
    elif pnl > 0:
        verdict, tone, ko = "win", "good", f"{X.SIDE_KO.get(side, '?')} 익절" if not t.get("step") else f"계단 {t['step']}단계 익절"
    else:
        if r is not None and plan_r is not None:
            worse = r < plan_r - TOL_R
        else:                                               # no stop price at the exit: one stop-out plus both fees
            sp = _f(((en or {}).get("why") or {}).get("stop_pct")) if isinstance((en or {}).get("why"), dict) else None
            worse = r is not None and r < -1.0 - (2 * fee * 100 / sp if sp else 0.0) - TOL_R
        if worse:
            verdict, tone = ("very_abnormal" if plan_r is not None and r < plan_r - BIG_R else "abnormal"), "bad"
            ko = "설계보다 아주 큰 손실" if verdict == "very_abnormal" else "설계보다 큰 손실"
            if not causes:
                causes.append({"id": "unknown", "ko": f"기록에서 이유를 못 찾았어요 ({ex} 앱의 체결 내역을 확인해 주세요)"})
        elif t.get("step"):
            verdict, tone, ko = "normal", "warn", "계단 손절인데 수수료·밀림으로 손실"
        else:
            verdict, tone, ko = "normal", "thin", "설계대로 손절 (정상)"
    out = {"key": f"{t.get('symbol')}|{om}|{xm}", "symbol": t.get("symbol"), "coin": X.coin_ko(t.get("symbol")), "side": side,
           "side_ko": X.SIDE_KO.get(side, "?"), "opened_ms": om, "exit_ms": xm, "hold_ms": t.get("hold_ms"), "why": t.get("why"),
           "why_ko": t.get("why_ko"), "step": t.get("step") or 0, "entry": e, "signal_close": sig_close, "entry_slip": slip, "qty": q,
           "notional": e * q if e and q else None, "stop_dist": dist, "first_stop": (e - side * dist) if e and dist else None,
           "stop": stop_x, "exit": exit_px, "exit_src": exit_src, "exit_gap": gap, "pnl": pnl, "r": r, "plan": plan, "plan_r": plan_r,
           "risk_usd": risk_usd, "risk_pct": risk_pct, "margin_frac": float(getattr(cfg, "margin_frac", 0) or 0) if cfg is not None else 0.0,
           "fees_est": fees, "equity_before": eb, "equity": t.get("equity"), "verdict": verdict, "tone": tone,
           "ko": ko, "causes": causes, "notes": notes, "twin": twin, "streak": streak if pnl is not None and pnl <= 0 else 0,
           "streak_band": band_streak, "fee": fee, "ex": ex}
    out["lines"] = card_lines(out)
    return out


def card_lines(c: dict) -> list:
    """The card's body in plain words (the Telegram message's lines after its title; the site shows the same)."""
    ls = [f"{kst(c['opened_ms'])} → {kst(c['exit_ms'])} ({hold_ko(c['hold_ms'])}) · 손익 {usd(c['pnl'])} ({r_ko(c['r'], 2)})"]
    if c["verdict"] in ("win", "unknown"):
        return ls
    plan = ((f"계획: 진입마다 증거금 잔고의 {c['margin_frac']:.0%} · 이번 손절 1번 = 잔고의 {c['risk_pct']:.1f}%" if c.get("margin_frac")
             else f"계획: 손절 1번 = 잔고의 {c['risk_pct']:g}%") + (f" ({usd(c['risk_usd'])[1:]})" if c.get("risk_usd") else ""))
    ls.append(plan + (f" · 이번 손절가에서 계획 손익 {usd(c['plan'])} ({r_ko(c['plan_r'], 2)}, 수수료 포함)" if c.get("plan") is not None else ""))
    if c.get("entry") is not None:
        sl = c.get("entry_slip")
        ls.append(f"진입 {px(c['entry'])}"
                  + ("" if sl is None else f" (신호 종가 {px(c['signal_close'])}와 같음)" if abs(sl) < 5e-5
                     else f" (신호 종가 {px(c['signal_close'])}보다 {pct(abs(sl))} {'불리' if sl > 0 else '유리'})")
                  + (f" · 수수료 약 {usd(c['fees_est'])[1:]} (테이커 {c.get('fee', TAKER) * 100:.3f}% 양쪽, 추정)" if c.get("fees_est") else ""))
    if c.get("stop") is not None:
        src = "" if c.get("exit_src") == "log" else " (잔고 변화로 거꾸로 계산: 수수료 추정·펀딩이 섞여 조금 다를 수 있어요)"
        g = c.get("exit_gap")
        ls.append(f"손절 {px(c['stop'])} · 청산 {'추정 ' if c.get('exit_src') != 'log' else ''}{px(c['exit'])}"
                  + ("" if g is None else " (손절가와 거의 같음)" if abs(g) < 5e-5 else f" (손절가보다 {pct(abs(g))} {'밀림' if g > 0 else '유리'})") + src)
    if c.get("twin"):
        ls.append(c["twin"]["ko"])
    if c.get("streak", 0) >= 2:
        b = c.get("streak_band")
        ls.append(f"이번이 연속 손절 {c['streak']}번째" + (f" · {b['ko']}" if b else ""))
    return ls


def card_message(c: dict) -> tuple[str, str]:
    """(level, text) of a card: a loss = the card (WARN when abnormal), a win = one short line (INFO)."""
    head = f"{c['coin']} {c['side_ko']}"
    who = c.get("bot_short") or "믹스"
    if c["verdict"] == "win":
        tw = c.get("twin") or {}
        return "INFO", (f"✅ {who} {head} {usd(c['pnl'])} ({r_ko(c['r'], 2)}) · {c['ko']} · {hold_ko(c['hold_ms'])}"
                        + (f" · 모의 {r_ko(tw.get('r'), 2)}" if tw.get("state") == "closed" else ""))
    if c["verdict"] == "unknown":
        return "WARN", f"⚠ {who} 손실 카드 · {head} · {c['ko']}\n" + "\n".join(c["lines"])
    bad = c["verdict"] in ("abnormal", "very_abnormal")
    lines = [f"{'⚠' if bad else '❌'} {who} 손실 카드 · {head} · {c['ko']}"] + c["lines"]
    if c["causes"]:
        lines += ["이유 후보:" if bad else "참고:"] + [f"- {x['ko']}" for x in c["causes"]]
    if c["notes"]:
        lines += [f"- {x}" for x in c["notes"]]
    if bad:
        lines.append(f"지금 할 일: {c.get('ex') or 'WOO X Pro'} 앱의 체결 내역에서 청산 가격과 수수료를 확인해 주세요")
    return ("WARN" if bad else "INFO"), "\n".join(lines)


def cards_of(data: dict, band_ref: Optional[dict] = None) -> list:
    """Every closed live trade as a card, newest first (the site; the pass sends the new ones)."""
    lb, pb = data["live"], data["paper"]
    rows = rows_of(lb)
    if not rows:
        return []
    cfg = lb["conf"].get("cfg")
    ts = X.trades_of(rows, cfg)
    ens = entries_of(rows)
    prow = rows_of(pb)
    p_trades = X.trades_of(prow, pb["conf"].get("cfg")) if prow else []
    p_entries = entries_of(prow)
    risk = risk_of(lb)
    w = words_of(data)
    out = []
    for t in ts:
        en = ens.get((t["symbol"], t["opened_ms"]))
        k = streak_at(ts, t)
        twin = paper_twin(en, p_entries, p_trades) if prow else {"state": "off", "ko": "모의 봇 기록이 없어 비교하지 못했어요"}
        c = card(t, en, rows, cfg, risk, twin, k,
                 streak_band(k, band_ref) if k and band_ref is not None and not plan_changed(cfg) else None, fee=w["fee"], ex=w["ex"])
        c["bot_short"] = w["short"]
        out.append(c)
    return out


# ====================================================================== C. the luck band
_summary: dict = {}


def load_summary(path: Optional[str] = None) -> dict:
    """research/mixchop5y/summary.json: {"state": "ok", "d"} / missing / error (read once per change)."""
    path = path or os.environ.get(SUMMARY_ENV) or SUMMARY
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return {"state": "missing", "path": path}
    except OSError as exc:
        return {"state": "error", "path": path, "reason": str(exc)[:200]}
    key = (path, st.st_mtime_ns, st.st_size)
    if _summary.get("key") == key:
        return _summary["v"]
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        rs = d["variants"]["live_rules"]["band"]["r"]
        if not isinstance(rs, list) or len(rs) < 50:
            raise ValueError("too few replay trades")
        v = {"state": "ok", "path": path, "d": d}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        v = {"state": "error", "path": path, "reason": f"{type(exc).__name__}: {exc}"[:200]}
    _summary.update(key=key, v=v)
    return v


def verdict_of(p: Optional[float]) -> Optional[str]:
    if p is None:
        return None
    return "ok" if p >= RARE else "rare" if p >= VERY_RARE else "very_rare"


def _trailing_streaks(rs: list) -> list:
    out, n = [], 0
    for r in rs:
        n = n + 1 if r <= 0 else 0
        out.append(n)
    return out


def _quant(xs: list, q: float) -> float:
    s = sorted(xs)
    if not s:
        return float("nan")
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


def band_ref(summary: Optional[dict] = None) -> Optional[dict]:
    """The replay's R sequence and its reference numbers (None without a readable summary)."""
    s = summary if summary is not None else load_summary()
    if s.get("state") != "ok":
        return None
    v = s["d"]["variants"]["live_rules"]
    return {"r": [float(x) for x in v["band"]["r"]], "v": v, "period": s["d"].get("period") or {}}


def streak_band(k: int, ref: Optional[dict]) -> Optional[dict]:
    """How often the replay was in a losing run of ``k`` or more (the share of its trades)."""
    if not k:
        return None
    if ref is None:
        p = (1 - BERNOULLI_P) ** k
        model = "단순 모델"
    else:
        ts = _trailing_streaks(ref["r"])
        p = sum(1 for x in ts if x >= k) / len(ts)
        model = "5년 재생"
    v = verdict_of(p)
    return {"p": p, "verdict": v, "ko": f"{model}에서 {k}번 이상 연속 손절 중이었던 때 {p:.0%} ({VERDICT_KO[v]})"}


def _binom_cdf(k: int, n: int, p: float) -> float:
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(0, k + 1))


def band(rs: list, ref: Optional[dict] = None, month_r: Optional[float] = None) -> dict:
    """The live record ``rs`` (R per closed trade, oldest first) in the replay's distribution (module docstring C)."""
    n = len(rs)
    base = {"n": n, "small": n < SMALL_N, "small_n": SMALL_N, "rare": RARE, "very_rare": VERY_RARE}
    if not n:
        return {**base, "state": "empty", "model": "replay" if ref else "bernoulli", "ko": "아직 닫힌 실거래가 없어요", "rows": []}
    wins = sum(1 for r in rs if r > 0)
    rsum = sum(rs)
    cur = _trailing_streaks(rs)[-1]
    cum, peak = 0.0, 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
    dd = peak - cum
    rows = []

    def row(rid, ko, live, p, rng="", why=""):
        v = verdict_of(p)
        rows.append({"id": rid, "ko": ko, "live": live, "p": p, "verdict": v, "verdict_ko": VERDICT_KO.get(v) if v else None,
                     "tone": VERDICT_TONE.get(v, "thin"), "range": rng, "why": why})

    if ref is None:
        p = BERNOULLI_P
        row("wins", "이긴 횟수", f"{wins}승 / {n}번", _binom_cdf(wins, n, p),
            f"설계 승률 {p:.0%}이면 보통 {_binom_q(n, p, 0.1)}~{_binom_q(n, p, 0.9)}승",
            f"설계 승률로 {n}번 하면 {wins}승 이하가 나올 확률")
        if cur:
            row("streak", "지금 연속 손절", f"{cur}번", (1 - p) ** cur, "", f"설계 승률이면 {cur}번 이상 연속으로 질 확률")
        out = {**base, "state": "ok", "model": "bernoulli",
               "model_ko": "5년 재생 파일이 없어 설계서 승률(코인 평균)로 만든 단순 모델이에요 · R 합과 낙폭은 계산하지 않아요", "rows": rows}
    else:
        seq = ref["r"]
        N = len(seq)
        m = min(n, N)
        c = [0.0]
        for x in seq:
            c.append(c[-1] + x)
        wc = [0]
        for x in seq:
            wc.append(wc[-1] + (1 if x > 0 else 0))
        sums = [c[i + m] - c[i] for i in range(N - m + 1)]
        wins_w = [wc[i + m] - wc[i] for i in range(N - m + 1)]
        p_w = sum(1 for x in wins_w if x <= wins) / len(wins_w)
        p_s = sum(1 for x in sums if x <= rsum + 1e-9) / len(sums)
        row("wins", "이긴 횟수", f"{wins}승 / {n}번", p_w, f"5년 재생의 {m}번 묶음에서 보통 {_quant(wins_w, 0.1):.0f}~{_quant(wins_w, 0.9):.0f}승 (가운데 80%)",
            f"5년 재생에서 {m}번 연속 거래 중 {wins}승 이하였던 비율")
        row("rsum", "R 합", r_ko(rsum), p_s, f"보통 {r_ko(_quant(sums, 0.1))} ~ {r_ko(_quant(sums, 0.9))} (가운데 80%)",
            f"5년 재생에서 {m}번 연속 거래의 R 합이 이만큼 이하였던 비율")
        if cur:
            ts = _trailing_streaks(seq)
            p_c = sum(1 for x in ts if x >= cur) / len(ts)
            row("streak", "지금 연속 손절", f"{cur}번", p_c, f"5년 재생에서 가장 길었던 연속 손절 {max(ts)}번",
                f"5년 재생에서 {cur}번 이상 연속 손절 중이었던 때의 비율")
        if dd > 1e-9:
            dds = window_drawdowns(c, m)
            p_d = sum(1 for x in dds if x >= dd - 1e-9) / len(dds)
            row("dd", "고점에서 내려온 만큼", r_ko(-dd), p_d, f"보통 {r_ko(-_quant(dds, 0.5))}, 나쁜 10%는 {r_ko(-_quant(dds, 0.9))}보다 깊음",
                f"5년 재생의 {m}번 묶음에서 끝에 이만큼 이상 내려와 있던 비율")
        v = ref["v"]
        mr = (v.get("band") or {}).get("monthly_r") or {}
        if month_r is not None and mr.get("p50") is not None:
            rows.append({"id": "month", "ko": "이번 달 R 합 (진행 중)", "live": r_ko(month_r), "p": None, "verdict": None, "verdict_ko": None,
                         "tone": "thin", "range": f"5년 재생 한 달: 가운데 50% {r_ko(mr.get('p25'))} ~ {r_ko(mr.get('p75'))}, 마이너스 달 {mr.get('neg')}번/60",
                         "why": "달이 끝나기 전이라 판정하지 않아요"})
        out = {**base, "state": "ok", "model": "replay",
               "model_ko": (f"5년 재생 (봇 코드 그대로, 실거래 규칙: 1포지션·진입 금지 시간·최소 주문 $5) · 거래 {v['trades']}번 · "
                            f"승률 {v['win_rate']:.0%} · 평균 익절 {r_ko(v['avg_win_r'])} · 평균 손절 {r_ko(v['avg_loss_r'])} · "
                            f"가장 긴 연속 손절 {v['max_losing_streak']}번 · 가장 깊은 낙폭 {r_ko(-v['max_dd_r'])}"),
               "rows": rows, "ref": {k: v.get(k) for k in ("trades", "per_year", "win_rate", "avg_win_r", "avg_loss_r", "r_per_trade",
                                                           "r_per_month", "max_losing_streak", "max_dd_r", "month_mean", "neg_months", "months")}}
    judged = [x for x in rows if x["verdict"]]
    worst = max(judged, key=lambda x: ("ok", "rare", "very_rare").index(x["verdict"]))["verdict"] if judged else "ok"
    out["worst"] = worst
    out["ko"] = VERDICT_KO[worst] + (f" · 거래 {n}번은 아직 표본이 작아요 (대부분 운)" if n < SMALL_N else "")
    return out


def window_drawdowns(c: list, m: int) -> list:
    """For each run of ``m`` trades (c: the running R sum from 0), how far its end is below the run's own peak (the
    run starts at 0): a sliding maximum of c over c[i+1 .. i+m]."""
    from collections import deque
    n = len(c) - 1
    out, dq = [], deque()
    for j in range(1, n + 1):
        while dq and c[dq[-1]] <= c[j]:
            dq.pop()
        dq.append(j)
        i = j - m
        if i < 0:
            continue
        while dq[0] <= i:
            dq.popleft()
        pk = max(0.0, c[dq[0]] - c[i])
        out.append(pk - (c[j] - c[i]))
    return out


def _binom_q(n: int, p: float, q: float) -> int:
    acc = 0.0
    for k in range(n + 1):
        acc += math.comb(n, k) * p ** k * (1 - p) ** (n - k)
        if acc >= q:
            return k
    return n


def band_lines(b: dict) -> list:
    if b.get("state") != "ok":
        return [f"- {b.get('ko')}"]
    out = [f"- {x['ko']} {x['live']}: {x['verdict_ko'] or '참고'}" + (f" (이만큼 나쁘거나 더 나빴던 때 {x['p']:.0%})" if x.get("p") is not None else "")
           + (f" · {x['range']}" if x.get("range") else "") for x in b["rows"]]
    if b.get("small"):
        out.append(f"- 거래 {b['n']}번은 아직 표본이 작아 대부분 정상 범위로 나와요")
    return out


NO_REPLAY_KO = "이 봇은 5년 재생이 없어요(두 분의 새 규칙) · 거래가 쌓이면 실거래 기록끼리 봐요"


def live_band(data: dict, ref: Optional[dict], now: int) -> dict:
    lb = data["live"]
    rows = rows_of(lb)
    ts = X.trades_of(rows, lb["conf"].get("cfg")) if rows else []
    rs = live_rs(ts)
    if not words_of(data)["mix"]:                        # owners 10-29: the 바이비트 봇 has no 5-year replay
        return {"state": "none", "n": len(rs), "ko": NO_REPLAY_KO, "rows": []}
    if plan_changed(lb["conf"].get("cfg")):
        return {"state": "changed", "n": len(rs), "ko": PLAN_CHANGED_KO, "rows": []}
    t = time.gmtime(now / 1000)
    import calendar
    m0 = calendar.timegm((t.tm_year, t.tm_mon, 1, 0, 0, 0)) * 1000
    mt = [x["r"] for x in ts if x.get("r") is not None and (x.get("exit_ms") or 0) >= m0]
    return band(rs, ref, sum(mt) if mt else None)


# ====================================================================== D. the signal replay
def binance_klines() -> Callable[[str, str, int, int], list]:
    """Binance USDT-M public klines (no key), the bot's own client (paperbot/binance.py) and host."""
    from .binance import BinanceREST, urllib_fetch
    rest = BinanceREST(base_url="https://fapi.binance.com", fetch=lambda u, h: urllib_fetch(u, h, timeout=10.0), max_retries=2, backoff=1.0)
    return lambda symbol, tf, start_ms, limit: rest.klines(symbol, tf, start_time=start_ms, limit=limit)


def bars_range(klines: Callable, symbol: str, tf: str, start_ms: int, end_ms: int) -> list:
    """Kline rows with open time in [start_ms, end_ms), paged."""
    out, t = [], int(start_ms)
    for _ in range(8):
        got = klines(symbol, tf, t, 1500) or []
        rows = [r for r in got if int(r[0]) >= t]
        out += [r for r in rows if int(r[0]) < end_ms]
        if not rows or int(rows[-1][0]) >= end_ms - 1 or len(got) < 1500:
            break
        t = int(rows[-1][0]) + 1
    return out


def handled_closes(rows: list, obs: list, st_last: Optional[int]) -> set:
    """The 30-minute closes the bot is known to have handled: the ones its state file showed at a pass, its signal /
    bars_missing rows' ``close_ms``, the closes of its skip / entry rows, the state's last one."""
    out = {int(o[1]) for o in obs if len(o) > 1 and o[1]}
    for r in rows:
        if r.get("kind") in ("signal", "bars_missing") and _i(r.get("close_ms")):
            out.add(int(r["close_ms"]))
        elif r.get("kind") in ("skip", "entry", "adopted") and _i(r.get("ts")):
            out.add(int(r["ts"]) // M.MIN30 * M.MIN30)
    if st_last:
        out.add(int(st_last))
    return out


def covered(obs: list, ce: int) -> bool:
    """Did a pass look at the bot's state between 2 and 30 minutes after the close ``ce``?"""
    return any(ce + 2 * MIN <= int(o[0]) < ce + M.MIN30 for o in obs if o)


def _rule(r: dict) -> str:
    """The entry rule of a signal row (rows from before the second rule, 10-26, are the friend's)."""
    return r.get("rule") or "mix"


def _moved(ev: dict) -> bool:
    """A row the bot logs: a colour change (the friend's rule), a Stoch RSI cross (the second; the 바이비트 봇's ●), an
    OBV light -> dark turn (the 바이비트 봇's, owners 10-29) or a side."""
    return bool(ev.get("to_cyan") or ev.get("to_purple") or ev.get("cross") or ev.get("turn") or ev.get("side"))


def _mark(ev: dict, rule: str) -> Any:
    """What the rule saw on the bar, to compare the log with the replay: the colour, the cross / ●, the OBV turn."""
    if rule == "mix":
        return bool(ev.get("to_cyan"))
    if rule == "obv":
        return _i(ev.get("turn")) or 0
    return ev.get("cross") or ""


def signal_replay(cfg: Any, w0: int, w1: int, rows: list, klines: Callable, obs: Optional[list] = None,
                  st_last: Optional[int] = None) -> dict:
    """D (module docstring): every 30-minute close in (w0, w1] of the config's coins recomputed with the bot's rules
    (mixchop.evaluate, and evaluate_st when the config runs the second rule) on Binance's closed bars (the 1,499 closed
    bars the bot holds), against the live log; one answer per (coin, close, rule)."""
    obs = obs or []
    rules = tuple(getattr(cfg, "rules", None) or ("mix",))
    closes = list(range(w0 + M.MIN30, w1 + 1, M.MIN30))
    rep: dict = {}
    fails, failed_syms = [], set()
    for co in cfg.coins:
        try:
            r30 = bars_range(klines, co.symbol, "30m", w0 - (M.BARS + 10) * M.MIN30, w1 + M.MIN30)
            r1h = bars_range(klines, co.symbol, "1h", w0 - (M.BARS + 10) * M.H1, w1 + M.H1)
        except Exception as exc:  # noqa: BLE001  Binance unreachable: said, never guessed
            fails.append(f"{co.symbol}: {type(exc).__name__}: {exc}"[:160])
            failed_syms.add(co.symbol)
            continue
        for ce in closes:
            b30 = M.bars_frame(r30, M.MIN30, ce).tail(M.BARS - 1).reset_index(drop=True)
            b1h = M.bars_frame(r1h, M.H1, ce).tail(M.BARS - 1).reset_index(drop=True)
            for rule in rules:
                ev = M.Bot.judge(rule, co, b30, b1h, ce)
                if _moved(ev) or ev["why"].endswith("아직 없음"):
                    rep[(co.symbol, ce, rule)] = ev
    if fails and len(fails) == len(cfg.coins):
        return {"state": "error", "ko": "바이낸스 봉을 못 읽어 신호를 다시 계산하지 못했어요", "reason": "; ".join(fails)[:400]}
    day = [r for r in rows if w0 <= (_i(r.get("ts")) or 0) <= w1 + M.MIN30]
    sig = {(r.get("symbol"), _i(r.get("close_ms")), _rule(r)): r for r in day if r.get("kind") == "signal"}
    late = {(r.get("symbol"), _i(r.get("close_ms"))) for r in day if r.get("kind") == "bars_missing"}
    failed = {_i(r.get("close_ms")) for r in day if r.get("kind") == "close_failed"}
    handled = handled_closes(day, obs, st_last)
    missed, different, unexplained, unsure = [], [], [], []
    for (sym, ce, rule), ev in sorted(rep.items(), key=lambda kv: (kv[0][1], kv[0][0], rules.index(kv[0][2]))):
        if ev["why"].endswith("아직 없음"):
            continue                                            # Binance's own bar missing now: nothing to compare
        lv = sig.get((sym, ce, rule))
        st = rule == "st"
        colour = ("cyan" if ev.get("to_cyan") else "purple") if rule == "mix" else \
            ({1: "up", -1: "down"}.get(_i(ev.get("turn")) or 0, "") if rule == "obv" else (ev.get("cross") or ""))
        item = {"symbol": sym, "coin": X.coin_ko(sym), "close_ms": ce, "side": ev.get("side") or 0, "rule": rule,
                "colour": colour, "why": ev.get("why") or ""}
        if lv is not None:
            if (_i(lv.get("side")) or 0) != item["side"] or _mark(lv, rule) != _mark(ev, rule):
                different.append({**item, "live_side": _i(lv.get("side")) or 0, "live_why": lv.get("why") or "",
                                  "ko": f"봇은 {_side_word(_i(lv.get('side')) or 0, lv.get('why'))}, 다시 계산하면 {_side_word(item['side'], item['why'])}"})
            continue
        if (sym, ce) in late:
            why, kind = "바이낸스 봉이 늦어 봇이 이 봉을 건너뛰었어요", "late"
        elif ce in failed:
            why, kind = "봇이 이 봉 처리에 실패했어요", "failed"
        elif ce in handled:
            seen_what = ("스톡RSI 크로스를" if st else "색 변화를") if rule in ("mix", "st") else f"{RULE_WHAT.get(rule, rule)} 신호를"
            why, kind = (f"봇은 이 봉에서 {seen_what} 보지 못했어요 "
                         "(봉 값이 마감 직후와 달랐을 수 있어요)", "unseen")
        elif covered(obs, ce):
            why, kind = "봇이 이 봉을 처리하지 않았어요 (꺼져 있었거나 늦었어요)", "down"
        else:
            why, kind = "봇 기록에 없어요 (그때 봇이 돌았는지는 확인 못 함)", "unknown"
        entry = {**item, "kind": kind, "ko": why}
        (missed if item["side"] else unsure).append(entry)
    for (sym, ce, rule), lv in sig.items():
        if (sym, ce, rule) not in rep and rule in rules and ce is not None and w0 < ce <= w1 and sym not in failed_syms:
            what = RULE_WHAT.get(rule, "색 변화")
            different.append({"symbol": sym, "coin": X.coin_ko(sym), "close_ms": ce, "side": 0, "rule": rule,
                              "live_side": _i(lv.get("side")) or 0, "live_why": lv.get("why") or "",
                              "ko": (f"봇은 {what}로 기록했는데 다시 계산하면 {what} 없음" if rule in ("mix", "st")
                                     else f"봇은 {what} 신호로 기록했는데 다시 계산하면 없음")})
    # one entry or skip per coin and close: the first rule with a side was taken, the other rule's side goes with it
    acted = {(r.get("symbol"), (_i(r.get("ts")) or 0) // M.MIN30 * M.MIN30) for r in day
             if r.get("kind") in ("skip", "entry", "adopted", "entry_failed", "entry_none")}
    told = set()
    for (sym, ce, rule), lv in sig.items():
        if (_i(lv.get("side")) or 0) and (sym, ce) not in acted and (sym, ce) not in told and ce is not None and w0 < ce <= w1:
            told.add((sym, ce))
            unexplained.append({"symbol": sym, "coin": X.coin_ko(sym), "close_ms": ce, "side": _i(lv.get("side")), "rule": rule,
                                "ko": "신호가 나왔는데 진입도, 건너뛴 이유도 기록에 없어요"})
    n_sig = len({(s, ce) for (s, ce, rule), ev in rep.items() if ev.get("side")})
    n_chg = sum(1 for (s, ce, rule), ev in rep.items() if ev.get("to_cyan") or ev.get("to_purple"))
    out = {"state": "ok", "closes": len(closes), "coins": len(cfg.coins) - len(fails), "changes": n_chg, "signals": n_sig,
           "missed": missed, "different": different, "unexplained": unexplained, "unsure": unsure,
           "fails": fails, "observed": sum(1 for ce in closes if covered(obs, ce))}
    if "st" in rules:
        out["crosses"] = sum(1 for (s, ce, rule), ev in rep.items() if rule == "st" and ev.get("cross"))
    if "obv" in rules:                                   # the 바이비트 봇's (owners 10-29)
        out["turns"] = sum(1 for (s, ce, rule), ev in rep.items() if rule == "obv" and ev.get("turn"))
    if "srsi" in rules:
        out["dots"] = sum(1 for (s, ce, rule), ev in rep.items() if rule == "srsi" and ev.get("cross"))
    out["rules"] = list(rules)
    return out


def _side_word(side: int, why: Any = "") -> str:
    return "롱 신호" if side > 0 else "숏 신호" if side < 0 else f"진입 안 함({why})" if why else "진입 안 함"


def replay_lines(d: Optional[dict]) -> list:
    if d is None:
        return ["- 다시 계산은 건너뛰었어요"]
    if d.get("state") != "ok":
        return [f"- {d.get('ko')}"]
    cross = f" · 스톡RSI 크로스 {d['crosses']}번" if d.get("crosses") is not None else ""
    seen = f"색 변화 {d['changes']}번{cross}" if "mix" in (d.get("rules") or ["mix"]) else " · ".join(
        x for x in ((f"OBV 연한→진한 {d['turns']}번" if d.get("turns") is not None else ""),
                    (f"스톡RSI ● {d['dots']}번" if d.get("dots") is not None else ""), cross.lstrip(" ·")) if x)
    out = [f"- 놓친 신호 {len(d['missed'])}개 (봇 공식으로 바이낸스 봉을 다시 계산: 30분봉 {d['closes']}개 × 코인 {d['coins']}개, "
           f"{seen} · 신호 {d['signals']}번)"]
    for x in d["missed"][:8]:
        out.append(f"  · {kst(x['close_ms'])} {x['coin']} {'롱' if x['side'] > 0 else '숏'}{RULE_TAG.get(x.get('rule'), '')}: {x['ko']}")
    if d["different"]:
        out.append(f"- 판정이 다른 봉 {len(d['different'])}개")
        out += [f"  · {kst(x['close_ms'])} {x['coin']}{RULE_TAG.get(x.get('rule'), '')}: {x['ko']}" for x in d["different"][:6]]
    if d["unexplained"]:
        out.append(f"- 이유 없이 안 들어간 신호 {len(d['unexplained'])}개")
        out += [f"  · {kst(x['close_ms'])} {x['coin']}: {x['ko']}" for x in d["unexplained"][:6]]
    if d["unsure"]:
        what = "색 변화" if "mix" in (d.get("rules") or ["mix"]) else "신호"
        out.append(f"- 봇 기록에 없는 {what}(진입 조건은 안 맞음) {len(d['unsure'])}개")
    if d["fails"]:
        out.append(f"- 봉을 못 읽은 코인: {', '.join(x.split(':')[0] for x in d['fails'])}")
    return out


# ====================================================================== A. the morning check
def day_rows(rows: list, w0: int, w1: int) -> list:
    return [r for r in rows if w0 <= (_i(r.get("ts")) or 0) < w1]


def signal_counts(rows: list) -> dict:
    """The day's colour changes (the friend's rule), Stoch RSI crosses (the second rule, when it logged any), signals
    (one per coin and close), entries and skips by reason (livemix.skip_group; blocks by kind)."""
    sig = [r for r in rows if r.get("kind") == "signal"]
    mix = [r for r in sig if _rule(r) == "mix"]
    st = [r for r in sig if _rule(r) == "st"]
    skips: dict = {}
    blocks: dict = {}
    for r in rows:
        if r.get("kind") != "skip":
            continue
        g = X.skip_group(r.get("why"))
        if g == "halt" and str(r.get("why") or "").startswith("정지 파일"):
            g = "stopfile"
        elif g == "halt" and str(r.get("why") or "").startswith("잔고 $"):
            g = "floor"
        skips[g] = skips.get(g, 0) + 1
        if g == "block":
            k = X.block_kind(r.get("why")) or "other"
            blocks[k] = blocks.get(k, 0) + 1
    out = {"changes": len({(r.get("symbol"), _i(r.get("close_ms"))) for r in mix}),
           "signals": len({(r.get("symbol"), _i(r.get("close_ms"))) for r in sig if r.get("side")}),
           "refused": len({(r.get("symbol"), _i(r.get("close_ms")), _rule(r)) for r in sig if not r.get("side")}),
           "entries": sum(1 for r in rows if r.get("kind") in ("entry", "adopted")), "skips": skips, "blocks": blocks}
    if st:
        out["crosses"] = len({(r.get("symbol"), _i(r.get("close_ms"))) for r in st})
    obv = [r for r in sig if _rule(r) == "obv"]          # the 바이비트 봇's rules (owners 10-29)
    srsi = [r for r in sig if _rule(r) == "srsi"]
    if obv:
        out["turns"] = len({(r.get("symbol"), _i(r.get("close_ms"))) for r in obv})
    if srsi:
        out["dots"] = len({(r.get("symbol"), _i(r.get("close_ms"))) for r in srsi})
    return out


SKIP_KO = {"block": "진입 금지 시간", "small": "최소 주문보다 작음", "held": "보유 중", "same_bar": "같은 봉 다른 코인 먼저",
           "stopfile": "정지 파일", "floor": "잔고 바닥선", "halt": "새 진입 멈춤", "liq": "청산가에 너무 가까움", "other": "기타"}


def skip_text(c: dict) -> str:
    if not c["skips"]:
        return "건너뜀 없음"
    parts = []
    for g in ("block", "small", "held", "same_bar", "stopfile", "floor", "halt", "liq", "other"):
        if c["skips"].get(g):
            s = f"{SKIP_KO[g]} {c['skips'][g]}"
            if g == "block" and c["blocks"]:
                s += " (" + ", ".join(f"{X.BLOCK_KO.get(k, k)} {n}" for k, n in c["blocks"].items()) + ")"
            parts.append(s)
    return f"건너뜀 {sum(c['skips'].values())}번: " + " · ".join(parts)


def live_vs_paper(lrows: list, prows: list, lall: list, pall: list, w0: int, w1: int, paper_on: bool,
                  lcfg: Any = None, pcfg: Any = None) -> dict:
    """The day's entries of both bots by (coin, side, signal bar), and the exits of the trades both made: each difference
    with what the other bot logged at that close (its own reason), else unexplained."""
    def ent(rows):
        return {(r.get("symbol"), _i(r.get("side")), _i(r.get("signal_close_ms"))): r for r in rows if r.get("kind") in ("entry", "adopted")}
    le, pe = ent(lrows), ent(prows)
    diffs = []

    def reason(rows_all, key):
        sym, side, sc = key
        for r in rows_all:
            t = _i(r.get("ts")) or 0
            if sc is not None and sc <= t < sc + M.MIN30 and r.get("symbol") == sym and r.get("kind") in ("skip", "entry_failed", "entry_none"):
                return str(r.get("why") or r.get("error") or r.get("kind"))
        return None
    if not paper_on:
        return {"state": "off", "ko": "모의 봇 기록이 없어 비교하지 못했어요", "same": 0, "diffs": []}
    for k in sorted(set(le) | set(pe), key=lambda z: (z[2] or 0, z[0] or "")):
        if k in le and k in pe:
            continue
        who = "실거래만" if k in le else "모의만"
        why = reason(pall if k in le else lall, k)
        diffs.append({"symbol": k[0], "coin": X.coin_ko(k[0]), "side": k[1], "close_ms": k[2], "who": who, "why": why,
                      "explained": why is not None,
                      "ko": f"{X.coin_ko(k[0])} {X.SIDE_KO.get(k[1], '?')} ({kst(k[2])} 봉): {who} 진입"
                            + (f" · {'모의' if k in le else '실거래'}는 {why}" if why else " · 다른 쪽 기록에 이유 없음")})
    lt = {(t["symbol"], t["opened_ms"]): t for t in X.trades_of(lall, lcfg)}
    pt = {(t["symbol"], t["opened_ms"]): t for t in X.trades_of(pall, pcfg)}
    lent, pent = ent(lall), ent(pall)
    same_exit = 0
    for k in set(lent) & set(pent):
        a, b = lent[k], pent[k]
        ta, tb = lt.get((a.get("symbol"), _i(a.get("opened_ms")))), pt.get((b.get("symbol"), _i(b.get("opened_ms"))))
        if not ta or not tb or not (w0 <= (ta.get("exit_ms") or 0) < w1 or w0 <= (tb.get("exit_ms") or 0) < w1):
            continue
        if ta.get("why") != tb.get("why") or (ta.get("step") or 0) != (tb.get("step") or 0) or \
                (ta.get("r") is not None and tb.get("r") is not None and abs(ta["r"] - tb["r"]) > 0.5):
            diffs.append({"symbol": k[0], "coin": X.coin_ko(k[0]), "side": k[1], "close_ms": k[2], "who": "청산", "why": None, "explained": True,
                          "ko": f"{X.coin_ko(k[0])} {X.SIDE_KO.get(k[1], '?')} 청산: 실거래 {ta.get('why_ko')} {r_ko(ta.get('r'))} · "
                                f"모의 {tb.get('why_ko')} {r_ko(tb.get('r'))}"})
        else:
            same_exit += 1
    same = len(set(le) & set(pe))
    return {"state": "ok", "same": same, "same_exit": same_exit, "diffs": diffs,
            "unexplained": sum(1 for d in diffs if not d["explained"])}


def safety(rows: list) -> dict:
    """What the day's log says about the stop and the exchange."""
    k = lambda kinds: [r for r in rows if r.get("kind") in kinds]          # noqa: E731
    unknown = [r for r in rows if r.get("kind") == "skip" and str(r.get("why") or "").startswith("봇이 모르는 포지션")]
    odd = [r for r in rows if r.get("kind") == "exit" and r.get("why") in ODD_EXITS]
    reads = k(READ_KINDS)
    return {"stop": k(STOP_KINDS), "odd_exits": odd, "unknown": unknown, "entry_trouble": k(("entry_failed", "entry_none", "adopted", "qty_adopted")),
            "reads": len(reads), "read_kinds": {x: sum(1 for r in reads if r.get("kind") == x) for x in READ_KINDS if any(r.get("kind") == x for r in reads)},
            "starts": k(("start",))}


def entry_costs(lrows: list, fee: float = TAKER) -> dict:
    """The day's live entries: the fill against the signal bar's close (+ = worse), the taker fee estimate (``fee``: the
    bot's own, words_of)."""
    slips, fees = [], 0.0
    for r in lrows:
        if r.get("kind") != "entry":
            continue
        e, sc, q, side = _f(r.get("entry")), _f(r.get("signal_close")), _f(r.get("qty")), _i(r.get("side")) or 0
        if e and sc and side:
            slips.append(side * (e - sc) / sc)
        if e and q:
            fees += 2 * fee * e * q
    return {"n": len(slips), "avg": sum(slips) / len(slips) if slips else None, "worst": max(slips) if slips else None, "fees": fees}


def morning(data: dict, w0: int, *, klines: Optional[Callable] = None, obs: Optional[list] = None,
            ref: Optional[dict] = None, use_ref: bool = True) -> dict:
    """A (module docstring): the report of the KST day starting at ``w0`` and its message (level, text)."""
    now, w1 = data["now"], w0 + DAY
    lb, pb = data["live"], data["paper"]
    cfg = lb["conf"].get("cfg")
    wd = words_of(data)
    lall, pall = rows_of(lb), rows_of(pb)
    lrows, prows = day_rows(lall, w0, w1), day_rows(pall, w0, w1)
    if use_ref and ref is None and wd["mix"]:           # the 5-year replay is the friend bot's own
        ref = band_ref()
    warn = []
    st = lb["status"]
    if st["state"] == "off":
        warn.append("실거래 봇 기록이 없어요 (꺼져 있거나 아직 안 켰어요)")
    elif st["state"] in ("stopped", "error"):
        warn.append(f"실거래 봇이 지금 멈춘 것 같아요: {st.get('ko')}")
    if lb["lg"].get("state") not in ("ok", "missing"):
        warn.append(f"실거래 봇 기록을 못 읽었어요: {lb['lg'].get('reason_ko')}")
    sc = signal_counts(lrows)
    vs = live_vs_paper(lrows, prows, lall, pall, w0, w1, pb["lg"].get("state") == "ok", cfg, pb["conf"].get("cfg"))
    if vs.get("unexplained"):
        warn.append(f"실거래와 모의가 이유 없이 다른 진입 {vs['unexplained']}개")
    sf = safety(lrows)
    if sf["stop"]:
        warn.append(f"손절 주문 문제 {len(sf['stop'])}번 (다시 걸기·실패)")
    if sf["odd_exits"]:
        warn.append(f"보통과 다른 청산 {len(sf['odd_exits'])}번 ({', '.join(M.EXIT_KO.get(r.get('why'), str(r.get('why'))) for r in sf['odd_exits'][:3])})")
    if sf["unknown"]:
        warn.append("봇이 모르는 포지션이 있었어요 (새 진입 멈춤)")
    if sf["reads"] >= 10:
        warn.append(f"거래소·바이낸스 읽기 실패 {sf['reads']}번")
    costs = entry_costs(lrows, wd["fee"])
    if costs["avg"] is not None and costs["avg"] > 2 * SLIP_FRAC:
        warn.append(f"진입 체결이 신호 종가보다 평균 {pct(costs['avg'])} 불리")
    eq = X.equity_view("live", lb)
    if eq.get("below"):
        warn.append("잔고가 바닥선 아래라 새 진입이 멈춰 있어요")
    all_cards = cards_of(data, ref)
    day_cards = [c for c in all_cards if w0 <= (c.get("exit_ms") or 0) < w1]
    bad_cards = [c for c in day_cards if c["verdict"] in ("abnormal", "very_abnormal", "unknown")]
    if bad_cards:
        warn.append(f"설계보다 큰 손실이나 손익 모름 {len(bad_cards)}번")
    bd = live_band(data, ref, now)
    if bd.get("worst") == "very_rare":
        warn.append("성적이 5년 재생에 비해 아주 드문 수준이에요")
    rp = None
    if klines is not None and cfg is not None:
        try:
            st_last = _i(((lb["st"].get("d") or {}) if lb["st"].get("state") == "ok" else {}).get("last_close_ms"))
            rp = signal_replay(cfg, w0, w1, lall, klines, obs, st_last)
        except Exception as exc:  # noqa: BLE001  the rest of the check still goes out
            rp = {"state": "error", "ko": "신호를 다시 계산하지 못했어요", "reason": f"{type(exc).__name__}: {exc}"[:300]}
        if rp.get("state") == "ok" and (rp["missed"] or rp["unexplained"] or any(x.get("live_side") != x.get("side") for x in rp["different"])):
            warn.append(f"놓친 신호 {len(rp['missed'])}개 · 판정이 다른 봉 {len(rp['different'])}개 · 이유 없는 미진입 {len(rp['unexplained'])}개")
        elif rp.get("state") != "ok":
            warn.append("신호 다시 계산을 못 했어요 (바이낸스)")
    lines = [(f"⚠ {wd['name']} 아침 점검 · 확인할 것 " + str(len(warn)) + "개") if warn else f"📋 {wd['name']} 아침 점검 · 이상 없음",
             f"{day_label(w0)} 00:00 ~ 24:00 (한국 시간)"]
    if warn:
        lines += [""] + [f"- {x}" for x in warn]
    rules = tuple(getattr(cfg, "rules", None) or ("mix",))
    seen = (f"- 색 변화 {sc['changes']}번" + (f" · 스톡RSI 크로스 {sc['crosses']}번" if "crosses" in sc else "")) if "mix" in rules else \
        "- " + " · ".join(x for x in ((f"OBV 연한→진한 {sc.get('turns', 0)}번" if "obv" in rules else ""),
                                      (f"스톡RSI ● {sc.get('dots', 0)}번" if "srsi" in rules else ""),
                                      (f"스톡RSI 크로스 {sc.get('crosses', 0)}번" if "st" in rules else "")) if x)
    lines += ["", "신호 (30분봉)",
              seen + f" · 조건 맞은 신호 {sc['signals']}번 · 진입 {sc['entries']}번",
              f"- {skip_text(sc)}"]
    if vs["state"] == "ok":
        lines.append(f"- 모의와 같은 진입 {vs['same']}번" + (f" · 다른 것 {len(vs['diffs'])}개" if vs["diffs"] else " · 다른 것 없음"))
        lines += [f"  · {d['ko']}" for d in vs["diffs"][:6]]
    else:
        lines.append(f"- {vs['ko']}")
    lines += replay_lines(rp)
    lt = X.trades_of(lall, cfg) if lall else []
    dt = [t for t in lt if w0 <= (t.get("exit_ms") or 0) < w1]
    lines += ["", "거래 (어제)"]
    if dt:
        known = [t for t in dt if t.get("pnl") is not None]
        w = sum(1 for t in known if t["pnl"] > 0)
        rs = [t["r"] for t in known if t.get("r") is not None]
        lines.append(f"- 닫힌 거래 {len(dt)}번 · {w}승 {len(known) - w}패 · 손익 {usd(sum(t['pnl'] for t in known) if known else None)}"
                     + (f" ({r_ko(sum(rs), 2)})" if rs else ""))
        for c in day_cards[:8]:
            lines.append(f"  · {c['coin']} {c['side_ko']} {usd(c['pnl'])} ({r_ko(c['r'], 2)}): {c['ko']}")
    else:
        lines.append("- 닫힌 거래 없음")
    if costs["n"]:
        lines.append(f"- 진입 체결: 신호 종가보다 평균 {pct(costs['avg'])} ({'불리' if costs['avg'] > 0 else '유리' if costs['avg'] < 0 else '같음'})"
                     f" · 수수료 약 {money(costs['fees'])} (테이커 {wd['fee'] * 100:.3f}% 양쪽, 추정)")
    lines += ["", "안전"]
    pos = (lb["st"].get("d") or {}).get("position") if lb["st"].get("state") == "ok" else None
    held = any((t.get("opened_ms") or 0) < w1 and (t.get("exit_ms") or 0) >= w0 for t in lt) or \
        (isinstance(pos, dict) and (_i(pos.get("opened_ms")) or 0) < w1)
    if lb["lg"].get("state") != "ok":
        lines.append("- 봇 기록이 없어 손절과 읽기 실패를 확인하지 못했어요")
    elif sf["stop"]:
        lines.append(f"- 손절: 문제 {len(sf['stop'])}번 · " + ", ".join(f"{kst(_i(r.get('ts')))} {X.WARN_KO.get(r.get('kind'), (r.get('kind'),))[0]}" for r in sf["stop"][:4]))
    elif held:
        lines.append("- 손절: 기록상 보유 내내 걸려 있었어요 (실패·다시 걸기 없음)")
    else:
        lines.append("- 손절: 어제는 보유한 포지션이 없었어요")
    if lb["lg"].get("state") == "ok":
        lines.append(f"- 거래소·바이낸스 읽기 실패 {sf['reads']}번" + (f" ({', '.join(f'{READ_KO.get(k, k)} {v}' for k, v in sf['read_kinds'].items())})" if sf["reads"] else "")
                     + f" · 봇 시작 {len(sf['starts'])}번" + (" · 모르는 포지션 있었음" if sf["unknown"] else " · 모르는 포지션 없음"))
    if isinstance(pos, dict) and pos.get("symbol"):
        lines.append(f"- 지금 보유: {X.coin_ko(pos.get('symbol'))} {X.SIDE_KO.get(_i(pos.get('side')), '?')} · 손절 {px(_f(pos.get('stop')))}"
                     + ("" if pos.get("stop_id") else " · 상태 파일에 손절 주문 번호 없음"))
    lines += ["", "잔고"]
    v = (eq.get("now") or {}).get("value")
    risk = risk_of(lb)
    if v is not None and not eq.get("floor_frac"):        # no floor (the 바이비트 봇, owners: "파산당하면 파산 당한다는 마인드")
        lines.append(f"- {money(v)} (시작 {money(eq.get('start'))}, {pct(eq.get('change'), 1)}) · 바닥선 없음(잔고가 줄어도 새 진입을 "
                     "멈추지 않아요)")
    elif v is not None:
        room = eq.get("room")
        by_margin = cfg is not None and float(getattr(cfg, "margin_frac", 0) or 0) > 0   # a stop's loss is not risk_pct then
        lines.append(f"- {money(v)} (시작 {money(eq.get('start'))}, {pct(eq.get('change'), 1)}) · 바닥선 {money(eq.get('floor'))}"
                     + ((f"까지 여유 {money(room)}" + ("" if by_margin else f" (손절 약 {room / (v * risk / 100):.0f}번)"))
                        if room is not None and room > 0 else " 아래: 새 진입 멈춤"))
    else:
        lines.append(f"- {eq.get('none_ko')}")
    lines += ["", "운이냐 고장이냐 (실거래 전체)"] + band_lines(bd)
    if bd.get("model_ko"):
        lines.append(f"  ({bd['model_ko']})")
    nxt = []
    if rp and rp.get("state") == "ok" and (rp["missed"] or rp["different"]):
        nxt.append("트레이딩뷰 30분 차트에서 그 봉을 직접 확인해 주세요 (python -m paperbot.mixchop signals)")
    if bad_cards:
        nxt.append(f"{wd['ex']} 앱의 체결 내역에서 그 거래의 청산 가격을 확인해 주세요")
    if st["state"] in ("stopped", "error"):
        nxt.append(f"서버에서 systemctl status {wd['unit']}")
    if nxt:
        lines += [""] + [f"지금 할 일: {x}" for x in nxt]
    full = "\n".join(lines)
    text = full if len(full) <= 3900 else full[:3870] + "\n…(나머지: python -m paperbot.mixcheck show)"
    level = "WARN" if warn else "INFO"
    report = {"day": time.strftime("%Y-%m-%d", time.gmtime((w0 + KST_MS) / 1000)), "w0": w0, "w1": w1, "made_ms": now, "level": level,
              "warn": warn, "signals": sc, "vs_paper": vs, "replay": rp, "safety": {k: (len(v) if isinstance(v, list) else v) for k, v in sf.items()},
              "costs": costs, "equity": {k: eq.get(k) for k in ("start", "floor", "room", "below", "change")} | {"now": v},
              "trades": [{k: c.get(k) for k in ("key", "coin", "side_ko", "pnl", "r", "verdict", "ko")} for c in day_cards],
              "band": {k: bd.get(k) for k in ("state", "model", "n", "worst", "ko")}, "text": full}
    return {"level": level, "text": text, "report": report}


# ====================================================================== the frequent pass (B) and the commands
def observe(data: dict, state: dict) -> None:
    """Keep what the bots' state files say now (the signal replay's evidence of the closes the bot handled)."""
    now = data["now"]

    def last(b):
        return _i(((b["st"].get("d") or {}) if b["st"].get("state") == "ok" else {}).get("last_close_ms"))
    obs = [o for o in state.get("obs") or [] if isinstance(o, list) and o and now - int(o[0]) <= OBS_KEEP_MS]
    obs.append([now, last(data["live"]), last(data["paper"])])
    state["obs"] = obs[-2000:]


def run_pass(data: dict, state: dict, send: Optional[Callable[[str, str], bool]], ref: Optional[dict] = None,
             out: Callable[[str], None] = print) -> list:
    """B: the cards of the closes not told yet (a first pass ever marks the old ones only). Returns the cards sent (or,
    dry, printed)."""
    now = data["now"]
    observe(data, state)
    if rows_of(data["live"]) == [] and data["live"]["lg"].get("state") != "ok":
        return []
    cards = cards_of(data, ref)
    told = state.setdefault("told", {})
    first = not state.get("started_ms")
    if first:
        state["started_ms"] = now
    done = []
    for c in reversed(cards):                               # oldest first
        k = c["key"]
        if k in told and (told[k].get("ok") or told[k].get("tries", 0) >= SEND_TRIES):
            continue
        if first and now - (c.get("exit_ms") or 0) > FIRST_BACK_MS:
            told[k] = {"ok": True, "ms": now, "skipped": "first pass"}
            continue
        level, text = card_message(c)
        if send is None:
            out(f"[{level}] {text}\n")
            done.append(c)
            continue
        ok = False
        try:
            ok = bool(send(level, text))
        except Exception:  # noqa: BLE001  a failed send is tried again next pass
            ok = False
        prev = told.get(k) or {}
        told[k] = {"ok": ok, "ms": now, "tries": int(prev.get("tries", 0)) + 1, "verdict": c["verdict"]}
        if ok:
            done.append(c)
    if len(told) > KEEP_KEYS:
        for k in sorted(told, key=lambda z: told[z].get("ms", 0))[:len(told) - KEEP_KEYS]:
            told.pop(k, None)
    return done


def cmd_pass(args) -> int:
    d = state_dir(args.dir)
    path = os.path.join(d, "state.json")
    data = load(now=args.now, tail=PASS_TAIL)
    ref = band_ref() if words_of(data)["mix"] else None   # the 5-year replay is the friend bot's own
    if args.dry_run:
        sent = run_pass(data, read_json(path), None, ref)
    else:
        with locked(d):                                     # about a second (the morning only holds it to write)
            state = read_json(path)
            sent = run_pass(data, state, notifier(False), ref)
            write_json(path, state)
    print(f"pass: {len(sent)} card(s)" + (" (dry run, nothing written)" if args.dry_run else ""))
    return 0


def cmd_morning(args) -> int:
    d = state_dir(args.dir)
    spath = os.path.join(d, "state.json")
    state = read_json(spath)
    data = load(now=args.now)
    w0 = kst_day_of(args.day, data["now"])
    day = time.strftime("%Y-%m-%d", time.gmtime((w0 + KST_MS) / 1000))
    done = (state.get("mornings") or {}).get(day) or {}
    if done.get("sent") and not args.force and not args.dry_run:
        print(f"{day}: already sent ({done.get('level')}); --force to send again")
        return 0
    res = morning(data, w0, klines=None if args.no_replay else binance_klines(), obs=state.get("obs") or [])
    if args.dry_run:
        print(f"[{res['level']}]\n{res['text']}")
        return 0
    send = notifier(False)
    ok = bool(send(res["level"], res["text"])) if send else False
    with locked(d):                                         # the passes ran meanwhile: their newer state is kept
        state = read_json(spath)
        ms = state.setdefault("mornings", {})
        ms[day] = {"level": res["level"], "sent": ok, "ms": data["now"], "warn": len(res["report"]["warn"])}
        for k in sorted(ms)[:-30]:
            ms.pop(k, None)
        write_json(spath, state)
        write_json(os.path.join(d, "last-morning.json"), {**res["report"], "sent": ok})
    print(f"{day}: {res['level']} sent={ok}")
    return 0


def cmd_band(args) -> int:
    data = load(now=args.now)
    b = live_band(data, band_ref() if words_of(data)["mix"] else None, data["now"])
    print("운이냐 고장이냐 (실거래 전체)")
    print("\n".join(band_lines(b)))
    print(b.get("model_ko") or "")
    return 0


def cmd_show(args) -> int:
    d = read_json(os.path.join(state_dir(args.dir), "last-morning.json"))
    print(d.get("text") or "아직 아침 점검 기록이 없어요")
    return 0


# ====================================================================== the 믹스 성적 screen
def last_morning(dir_: Optional[str] = None, prof: Optional["X.Profile"] = None) -> dict:
    """<dir>/last-morning.json for the site: {"state": "ok", "d"} / missing / error (never a guess)."""
    prof = prof or prof_env()
    path = os.path.join(state_dir(dir_, prof), "last-morning.json")
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except FileNotFoundError:
        return {"state": "missing", "path": path, "ko": f"아침 점검 기록이 아직 없어요 (점검 타이머: {prof.guide}"
                                                        + (" 8장)" if prof is X.MIX else ")")}
    except (OSError, ValueError) as exc:
        return {"state": "error", "path": path, "ko": "아침 점검 기록을 못 읽었어요", "reason": f"{type(exc).__name__}: {exc}"[:200]}
    keep = ("day", "level", "warn", "made_ms", "sent", "signals", "vs_paper", "replay", "band", "equity", "trades")
    return {"state": "ok", "path": path, "d": {k: d.get(k) for k in keep}}


def site_view(p: Optional[dict] = None, now_ms: Optional[int] = None) -> dict:
    """The 믹스 성적 screen's analysis part (paperbot/dash/more/livemix.py perf): the live trades' cards (newest first),
    the luck band now, the replay's reference numbers next to the design's, the last morning check."""
    data = load(p, now_ms)
    prof = X.PROFILES.get(data.get("bot") or "mix", X.MIX)
    s = load_summary() if prof is X.MIX else {"state": "none", "path": None, "reason": "이 봇은 5년 재생이 없어요(두 분의 새 규칙)"}
    ref = band_ref(s) if prof is X.MIX else None
    cards = cards_of(data, ref)
    bd = live_band(data, ref, data["now"])
    design = None
    if s.get("state") == "ok":
        vv = s["d"]["variants"]
        dsg = (vv.get("design") or {}).get("coins") or {}
        dsg2 = (vv.get("design_fee02") or {}).get("coins") or {}
        design = {"rows": [{"symbol": sym, "coin": X.coin_ko(sym), "design_month": v.get("design_month_mean"), "design_win": v.get("design_win_rate"),
                            "month": v.get("month_mean"), "month_fee02": (dsg2.get(sym) or {}).get("month_mean"), "win": v.get("win_rate"),
                            "trades_year": v.get("per_year"), "neg_months": v.get("neg_months"), "max_losing_streak": v.get("max_losing_streak")}
                           for sym, v in dsg.items()],
                  "one_position": {k: (vv.get("one_position") or {}).get(k) for k in ("trades", "per_year", "win_rate", "r_per_month", "month_mean", "neg_months", "max_dd_equity")},
                  "live_rules": {k: (vv.get("live_rules") or {}).get(k) for k in ("trades", "per_year", "win_rate", "avg_win_r", "avg_loss_r", "r_per_month",
                                                                                 "month_mean", "neg_months", "max_losing_streak", "max_dd_r", "max_dd_equity", "min_order")},
                  "skips": (vv.get("live_rules") or {}).get("skips"), "made_utc": s["d"].get("made_utc"), "period": s["d"].get("period"),
                  "not_modelled": s["d"].get("not_modelled") or [], "src": "research/mixchop5y/summary.json (research/mixchop5y/replay.py)"}
    return {"cards": cards[:X.TRADES_KEEP], "band": bd, "design": design,
            "summary": {k: s.get(k) for k in ("state", "path", "reason")}, "morning": last_morning(None, prof),
            "tol_r": TOL_R, "taker": words_of(data)["fee"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.mixcheck", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("morning", "pass", "band", "show"):
        p = sub.add_parser(name)
        p.add_argument("--dir", default=None, help=f"its own folder (default ${DIR_ENV} or {DIR})")
        p.add_argument("--now", type=int, default=None, help=argparse.SUPPRESS)
        if name in ("morning", "pass"):
            p.add_argument("--dry-run", action="store_true", help="print only: no Telegram, nothing written")
        if name == "morning":
            p.add_argument("--day", default=None, help="the KST date YYYY-MM-DD (default: yesterday, KST)")
            p.add_argument("--no-replay", action="store_true", help="skip the signal replay (no Binance call)")
            p.add_argument("--force", action="store_true", help="send again a day already sent")
    args = ap.parse_args(argv)
    return {"morning": cmd_morning, "pass": cmd_pass, "band": cmd_band, "show": cmd_show}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
