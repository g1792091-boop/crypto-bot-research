"""실거래 (#/livebots): 두 분의 실거래 봇 두 개(바이비트 · MEXC 주문 실행기)와 그 둘이 따라가는 페이퍼 계좌(A+C 합본,
``COMBO@mix``)를 보여 줍니다. 읽기만 합니다: 봇 쪽 코드(paperbot/combo.py, paperbot/executor.py)는 가져오지 않고, 그 봇들이
쓰는 표 모양(paperbot/store3.py SCHEMA, executor.py SCHEMA + MIGRATIONS)만 알고 그 모양에서 읽습니다. 주문 키 파일
(executor.env)은 열지 않습니다.

    GET /api/v4/livebots     요약(실거래 터미널): 세 계좌(페이퍼 · 바이비트 · MEXC)의 잔고 · 멈춤 · 열린 포지션 · 오늘 · 시간별
                             손익 · 달력, 체결 줄, 신호등, 40번 판단까지, 주의·긴급 기록 (5초 캐시)

어디서 읽나 (환경 변수로 바꿀 수 있음, 기본값 = 10/19 시작 안내 docs/live1019-start-ko.md):
    PAPERBOT_LIVE_PAPER_DB      /var/lib/paperbot/combo/live-ac.db              페이퍼 봇 (store3 표)
    PAPERBOT_LIVE_BYBIT_DB      /var/lib/paperbot/exec/executor-bybit-live.db   바이비트 실행기
    PAPERBOT_LIVE_MEXC_DB       /var/lib/paperbot/exec/executor-mexc-live.db    MEXC 실행기
    PAPERBOT_LIVE_BYBIT_CONFIG  /etc/paperbot/executor.json                     (키 없음: 계좌 · 신호등 · 크기 비율 · 위험 한도만 씀)
    PAPERBOT_LIVE_MEXC_CONFIG   /etc/paperbot/executor-mexc.json

DB는 모두 ``mode=ro``(쓰는 쪽이 멈춘 WAL 파일은 immutable, paperbot.livepnl.open_ro) + ``query_only``로 열고, 한 번 읽는 동안
하나의 시점(BEGIN)으로 읽습니다.

못 읽은 것을 '없음'으로 보이지 않기 (CONTRACT §1.6), 출처마다:
    ``state: "missing"``  파일이나 표가 아직 없음 -> 화면은 '수집 전'
    ``state: "error"``    있는데 읽지 못함(권한, 망가짐, 잠김) -> '못 읽음' + 이유, 0이나 빈 목록으로 바뀌지 않음
    ``state: "ok"``

신호등은 실행기의 규칙(executor.Executor._light_ok, Paper3Source.recent)을 그대로 옮겼습니다: 실행기가 따라가는 페이퍼 계좌의
마지막 N번 닫힌 거래(exit_time, id 순으로 최신부터) 중 이긴(pnl > 0) 수가 N x 기준 이상이면 초록, 아니면 빨강, N번이 안 되면 근거
쌓는 중(모든 진입을 따라감), N = 0이면 꺼짐.

시간은 UTC 밀리초, 비율은 비율(0.85 = 85%), 돈은 각 계좌의 단위(페이퍼 USDT, 실거래 거래소 USDT).
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import os
import sqlite3
import stat
import threading
import time
from typing import Any, Iterable, Optional

ACCOUNT = "COMBO@mix"                  # paperbot/combo.py ACCOUNT (the account both executors follow)
FLIP_ACCOUNT = "COMBOFLIP@mix"         # paperbot/combo.py FLIP_ACCOUNT (coin-flip twin: same moments, random side; 참고)
ENV = {
    "paper": ("PAPERBOT_LIVE_PAPER_DB", "/var/lib/paperbot/combo/live-ac.db"),
    "bybit_db": ("PAPERBOT_LIVE_BYBIT_DB", "/var/lib/paperbot/exec/executor-bybit-live.db"),
    "mexc_db": ("PAPERBOT_LIVE_MEXC_DB", "/var/lib/paperbot/exec/executor-mexc-live.db"),
    "bybit_config": ("PAPERBOT_LIVE_BYBIT_CONFIG", "/etc/paperbot/executor.json"),
    "mexc_config": ("PAPERBOT_LIVE_MEXC_CONFIG", "/etc/paperbot/executor-mexc.json"),
}
# (id, Korean name, db key, config key)
EXECS = (("bybit", "바이비트", "bybit_db", "bybit_config"), ("mexc", "MEXC", "mexc_db", "mexc_config"))
LIGHT_N_DEFAULT = 0                    # executor.ExecConfig.signal_light_n: 0 = the light is off
LIGHT_MIN_DEFAULT = 0.85               # executor.ExecConfig.signal_light_min_win
MATCH_MS = 5 * 60_000                  # a live trade and a paper trade of the same coin and side within 5 minutes
EXEC_STALE_MS = 3 * 60_000             # the executor saves its state every loop (~3 s); a 418 wait is 2 minutes
PAPER_STALE_MS = 5 * 60_000            # the paper saves every stepped minute (its ts is the minute's open)
EVENTS_KEEP = 200                      # WARN / CRITICAL events per executor
FILLS_KEEP = 60                        # 실거래 체결 rows (entries and exits of the three accounts)
WHY_SCAN = 4000                        # recent events read for the reasons of a missed entry
CURVE_MAX = 300                        # points of an equity line (thinned, the last one always kept)
TTL_S = 5.0
HOUR = 3_600_000
DAY = 86_400_000
KST_MS = 9 * HOUR
SMALL = (20, 40)                       # 표본 적음 under 20, then under 40 closed trades (the page says which)
# 10/19 start guide (docs/live1019-start-ko.md "매일 볼 것"): reference win rates, 참고 only (not a promise)
REFS = {"backtest": 0.91, "shake": [0.84, 0.86], "breakeven": 0.78,
        "label_ko": "참고 · 10/19 시작 안내의 숫자예요. 지나간 기간의 시험 결과이지 약속이 아니에요"}
# owners 10/19: at 40 paper trades they decide (88 % or more: think about more money; 82-88 %: keep watching; below 82 %:
# stop and think again). Before 40 trades nothing is decided: the page shows the progress only.
CHECKPOINT = {"trades": 40, "up": 0.88, "low": 0.82,
              "up_ko": "88% 이상이면 금액 늘리기 검토", "mid_ko": "82~88%면 그대로 지켜보기", "low_ko": "82% 미만이면 멈추고 다시 생각"}
EXEC_TRADE_COLS = ("key", "symbol", "side", "qty", "leverage", "entry_ts", "entry_price", "stop_initial", "exit_ts",
                   "exit_reason", "pnl", "data", "pnl_source", "realized", "commission", "funding", "slippage")
# reasons a paper entry was not followed, strongest first (executor.py events carrying data.key)
WHY = (("light_red", "신호등 빨강이라 따라가지 않았어요"),
       ("late", "페이퍼 진입을 늦게 봐서 건너뛰었어요"),
       ("entry_check", "진입 검사에서 막혔어요"),
       ("entry_skip", "가격이 이미 손절선을 지나 들어가지 않았어요"),
       ("leverage_refused", "거래소가 레버리지 설정을 거절했어요"),
       ("entry_refused", "거래소가 진입 주문을 거절했어요"),
       ("entry_unfilled", "진입 주문이 체결되지 않았어요"),
       ("light_unread", "신호등이 페이퍼 기록을 읽지 못해 미뤘어요"),
       ("direct_skip", "빠른 진입을 건너뛰었어요"))
WHY_KO = dict(WHY)
KIND_KO = {
    "halt": "멈춤", "halted": "멈춘 채 시작", "halt_cleared": "멈춤 풀림", "light_red": "신호등 빨강",
    "light_unread": "신호등 기록 못 읽음", "pnl_check": "거래소 기록과 다름", "unknown_position": "모르는 포지션",
    "wrong_side": "반대 방향 포지션", "protect_failed": "손절 못 걺", "not_flat": "닫았는데 남음", "no_stop": "손절 없음",
    "oversize": "크기 넘침", "paper_unreadable": "페이퍼 못 읽음", "paper_stale": "페이퍼 기록 멈춤", "late": "늦어서 건너뜀",
    "entry_check": "진입 검사 막힘", "entry_skip": "진입 안 함", "entry_refused": "진입 거절", "leverage_refused": "레버리지 거절",
    "entry_unfilled": "체결 안 됨", "entry_unknown": "진입 결과 모름", "entry_pending": "진입 확인 중", "partial_fill": "일부만 체결",
    "loop_error": "반복 오류", "rate_limit": "요청 한도", "move_failed": "손절 옮기기 실패", "exit": "청산", "transfer": "입출금",
    "db_error": "기록 실패", "fills_unread": "체결 기록 못 읽음", "time_sync": "서버 시간", "reconcile_failed": "대조 실패",
    "stop_size": "손절 크기", "stop_level": "손절 가격", "stop_would_trigger": "손절이 바로 걸릴 자리", "size_mismatch": "크기 다름",
    "cancel_failed": "취소 실패", "mainnet_refused": "실거래 관문 거절", "mainnet_unreachable": "관문 확인 못 함",
    "mainnet_unverified": "관문 확인 안 됨", "mode_refused": "포지션 모드 거절", "margin_refused": "격리 마진 거절",
    "margin": "격리 마진", "key_permission": "키 권한", "position_read": "포지션 못 읽음", "account_unread": "잔고 못 읽음",
    "transfers_unread": "입출금 못 읽음", "signal_read": "신호 못 읽음", "signal_mode_off": "빠른 진입 꺼짐",
    "oversize_retry": "크기 줄이기 다시", "cap_unchecked": "한도 확인 못 함", "recover": "복구", "direct_confirmed": "빠른 진입 확인",
}
LEVEL_KO = {"WARN": "주의", "CRITICAL": "긴급"}
# exit reasons: the paper engine's codes (paperbot/combo.py KO_EXIT) and what an executor's close was
EXIT_KO = {"SL": "손절", "LOCK": "잠금 익절", "LIQ": "강제청산", "HALT": "멈춤 청산", "MANUAL": "수동 청산", "REV": "빠른 청산",
           "END": "끝냄", "TP": "익절", "PAPER": "페이퍼 따라 청산", "OTHER": "기타 청산"}
MISSING_KO = "아직 파일이 없어요 (봇을 아직 켜지 않았거나, 설정의 경로가 달라요)"
NO_TABLE_KO = "파일은 있지만 아직 기록 표가 없어요 (봇이 첫 기록을 쓰기 전)"

_lock = threading.Lock()
_cache: dict = {}


# ---------------------------------------------------------------- small helpers
def _f(x: Any) -> Optional[float]:
    """A finite float, else None."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _i(x: Any) -> Optional[int]:
    if x is None or isinstance(x, bool):
        return None
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _j(raw: Any) -> dict:
    try:
        d = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except (TypeError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def paths(env: Optional[dict] = None) -> dict:
    """Where each source is: the environment variable when set, else the start guide's path."""
    env = os.environ if env is None else env
    return {k: (env.get(var) or default) for k, (var, default) in ENV.items()}


def thin(points: list, n: int = CURVE_MAX) -> list:
    """At most ``n`` points, evenly picked; the first and the last always kept."""
    if len(points) <= n:
        return list(points)
    step = (len(points) - 1) / (n - 1)
    idx = sorted({round(i * step) for i in range(n)} | {0, len(points) - 1})
    return [points[i] for i in idx]


def kst_day(ts: int) -> int:
    """The Korea-time day number of an epoch-ms time (days since 1970-01-01 KST; dash/more/flow.py's rule)."""
    return (int(ts) + KST_MS) // DAY


def kst_day_start(kd: int) -> int:
    return kd * DAY - KST_MS


def reason_ko(exc: BaseException, path: str = "") -> str:
    """A failed read in plain words (the raw text goes next to it, for whoever fixes it)."""
    msg = str(exc).lower()
    if "is not a file" in msg:
        return "그 자리에 파일이 아니라 다른 것(폴더 등)이 있어요"
    if isinstance(exc, PermissionError) or "permission" in msg or "unable to open" in msg or "readonly" in msg:
        if "/exec" in str(path):
            return ("대시보드가 이 파일을 읽을 권한이 없어요. 서버의 대시보드 서비스 설정(paperbot-dash.service)이 실행기 폴더"
                    "(/var/lib/paperbot/exec)를 막고 있으면 이렇게 보여요. 서버 설정을 바꾸는 쪽에 부탁해 주세요")
        return "대시보드가 이 파일을 읽을 권한이 없어요 (읽기 권한이나 위치를 확인해야 해요)"
    if "not a database" in msg or "malformed" in msg or "corrupt" in msg:
        return "기록 파일이 망가졌거나 데이터베이스 파일이 아니에요"
    if "locked" in msg or "busy" in msg:
        return "쓰는 쪽이 잡고 있어서 이번엔 못 읽었어요 (곧 다시 읽어요)"
    if "no such table" in msg or "no such column" in msg:
        return "기록 파일의 표 모양이 예상과 달라요"
    return "읽는 중 문제가 생겼어요"


def _err(path: str, exc: BaseException) -> dict:
    return {"state": "error", "path": path, "reason": f"{type(exc).__name__}: {exc}"[:300], "reason_ko": reason_ko(exc, path)}


def _missing(path: str, why: str = MISSING_KO) -> dict:
    return {"state": "missing", "path": path, "reason_ko": why}


def open_ro(path: str) -> sqlite3.Connection:
    """A read-only connection in autocommit mode (the caller opens one BEGIN for a consistent read). FileNotFoundError when
    nothing is there; PermissionError / OSError / sqlite3.Error when it cannot be read."""
    from ...livepnl import open_ro as livepnl_open_ro            # mode=ro; immutable for a WAL file whose writer stopped
    mode = os.stat(path).st_mode                                  # FileNotFoundError / PermissionError go up as they are
    if not stat.S_ISREG(mode):
        raise OSError(f"{path} is not a file")
    conn = livepnl_open_ro(path)
    try:
        conn.isolation_level = None
        conn.execute("PRAGMA query_only=ON")
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchall()
    except sqlite3.Error:
        conn.close()
        raise
    return conn


def _tables(conn: sqlite3.Connection) -> set:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _cols(conn: sqlite3.Connection, table: str) -> set:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def stats(pnls: Iterable[float]) -> dict:
    """Closed-trade record: count, wins (pnl > 0, the executor's rule), win share, net P&L."""
    xs = [p for p in (_f(v) for v in pnls) if p is not None]
    n = len(xs)
    wins = sum(1 for p in xs if p > 0)
    return {"trades": n, "wins": wins, "losses": n - wins, "win_rate": wins / n if n else None, "pnl": sum(xs) if n else 0.0,
            "small": n < SMALL[1], "small_floor": SMALL[0] if n < SMALL[0] else SMALL[1]}


# ---------------------------------------------------------------- the light (executor._light_ok, word for word)
def need_wins(n: int, min_win: float) -> int:
    """The fewest wins of the last n that keep the light green (wins >= min_win x n, the executor's 1e-9 slack)."""
    return int(math.ceil(float(min_win) * int(n) - 1e-9))


def light(n: Any, min_win: Any, pnl_newest_first: list) -> dict:
    """The light for a new entry right now. ``pnl_newest_first``: the paper account's closed-trade P&L, newest first (at
    least the last n). Fewer than n closed trades: no basis yet, every entry is followed (``building``)."""
    n = _i(n) or 0
    mw = _f(min_win)
    mw = LIGHT_MIN_DEFAULT if mw is None else mw
    if n <= 0:
        return {"state": "off", "n": 0, "min_win": mw}
    recent = [p > 0 for p in (_f(v) for v in pnl_newest_first[:n]) if p is not None]
    have, wins, need = len(recent), sum(recent), need_wins(n, mw)
    out = {"n": n, "min_win": mw, "need_wins": need, "have": have, "wins": wins, "recent": recent}
    if have < n:
        return {**out, "state": "building", "need_more": n - have, "share": wins / have if have else None}
    green = wins >= mw * n - 1e-9
    oldest_win = recent[-1]                      # the result that drops out of the window at the next close
    out.update(state="green" if green else "red", share=wins / n, spare=wins - need)
    if green:
        out["next_loss_red"] = (wins - (1 if oldest_win else 0)) < need
    else:
        out["next_win_green"] = (wins + 1 - (1 if oldest_win else 0)) >= need
    return out


# ---------------------------------------------------------------- the executors' configs (no secrets in them)
RISK_KEYS = ("max_consecutive_losses", "max_drawdown_pct", "daily_max_loss_usd", "max_loss_frac", "max_leverage",
             "max_notional_usd", "allowed_symbols", "kill_file")


def risk_limits(risk: dict, budget: Any = None) -> list:
    """The limits a config REALLY has, in the owners' words, in a fixed order; a limit the config does not set is left out
    (owners 10/19: the $40 daily limit and the wallet check were taken out, so they must not show up as if they held)."""
    out = []
    v = _i(risk.get("max_consecutive_losses"))
    if v:
        out.append({"key": "max_consecutive_losses", "value": v, "ko": f"{v}연패면 멈춤", "what_ko": "연속 손실"})
    v = _f(risk.get("max_drawdown_pct"))
    if v:
        out.append({"key": "max_drawdown_pct", "value": v, "ko": f"최고점에서 {round(v * 100)}% 빠지면 멈춤", "what_ko": "낙폭"})
    v = _f(risk.get("daily_max_loss_usd"))
    if v:
        out.append({"key": "daily_max_loss_usd", "value": v, "ko": f"하루 ${v:,.0f} 잃으면 멈춤", "what_ko": "하루 손실"})
    v = _f(risk.get("max_loss_frac"))
    if v:
        out.append({"key": "max_loss_frac", "value": v, "ko": f"손절 한 번에 잔고의 최대 {round(v * 100)}%", "what_ko": "손절 한 번"})
    v = _i(risk.get("max_leverage"))
    if v:
        out.append({"key": "max_leverage", "value": v, "ko": f"최대 {v}배", "what_ko": "최대 배수"})
    v = _f(risk.get("max_notional_usd"))
    if v:
        out.append({"key": "max_notional_usd", "value": v, "ko": f"포지션 크기 최대 ${v:,.0f}", "what_ko": "포지션 크기"})
    syms = risk.get("allowed_symbols")
    if isinstance(syms, list) and syms:
        names = [str(s).upper().replace("USDT", "") for s in syms]
        out.append({"key": "allowed_symbols", "value": names, "ko": f"코인 {len(names)}개만 ({' · '.join(names)})", "what_ko": "코인"})
    b = _f(budget)
    if b:
        out.append({"key": "budget_usd", "value": b, "ko": f"정한 금액 ${b:,.0f}", "what_ko": "정한 금액"})
    return out


def read_config(path: str) -> dict:
    """The few settings this page needs from an executor config: account, paper_db, db, exchange, mode, the light, the
    size ratio, the risk limits it really has, the kill file. Nothing else of the file is passed on."""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return _missing(path, "실행기 설정 파일이 아직 없어요")
    except ValueError as exc:
        return {**_err(path, exc), "reason_ko": "실행기 설정 파일이 JSON 모양이 아니에요"}
    except OSError as exc:
        return _err(path, exc)
    if not isinstance(raw, dict):
        return {"state": "error", "path": path, "reason": "not an object", "reason_ko": "실행기 설정 파일의 모양이 달라요"}
    risk = raw.get("risk") if isinstance(raw.get("risk"), dict) else {}
    n = _i(raw.get("signal_light_n"))
    mw = _f(raw.get("signal_light_min_win"))
    kill = risk.get("kill_file") if isinstance(risk.get("kill_file"), str) else None
    out = {"state": "ok", "path": path,
           "account": raw.get("account") if isinstance(raw.get("account"), str) else None,
           "paper_db": raw.get("paper_db") if isinstance(raw.get("paper_db"), str) else None,
           "db": raw.get("db") if isinstance(raw.get("db"), str) else None,
           "exchange": raw.get("exchange") if isinstance(raw.get("exchange"), str) else "binance",
           "mode": raw.get("mode") if isinstance(raw.get("mode"), str) else None,
           "entry_source": raw.get("entry_source") if isinstance(raw.get("entry_source"), str) else "paper",
           "signal_light_n": LIGHT_N_DEFAULT if n is None else n,
           "signal_light_min_win": LIGHT_MIN_DEFAULT if mw is None else mw,
           "qty_scale": _f(raw.get("qty_scale")), "budget_usd": _f(raw.get("budget_usd")),
           "max_consecutive_losses": _i(risk.get("max_consecutive_losses")),
           "limits": risk_limits(risk, raw.get("budget_usd")), "kill_file": None}
    if kill:
        try:
            present = os.path.exists(kill)
        except OSError:
            present = None
        out["kill_file"] = {"path": kill, "present": present}
    return out


# ---------------------------------------------------------------- the paper bot (paperbot.store3 tables)
def _paper_trade(r: tuple) -> dict:
    tid, sym, et, xt, why, lev, pnl, roe, eq, data = r
    d = _j(data)
    return {"id": _i(tid), "symbol": sym, "side": _i(d.get("side")), "entry_time": _i(et), "exit_time": _i(xt),
            "exit_reason": why, "leverage": _i(lev), "pnl": _f(pnl), "roe": _f(roe), "equity_after": _f(eq),
            "entry_price": _f(d.get("entry_price")), "exit_price": _f(d.get("exit_price")), "qty": _f(d.get("qty")),
            "margin": _f(d.get("margin")), "fees": _f(d.get("fees")), "funding": _f(d.get("funding")),
            "strategy_id": d.get("strategy_id"), "timeframe": d.get("timeframe"), "lock_roe": _f(d.get("lock_roe")),
            "stop_initial": _f(d.get("stop_initial")), "stop_price": _f(d.get("stop_price")), "liq_price": _f(d.get("liq_price"))}


def round_trip(taker_fee: Any) -> float:
    """The paper rules' round-trip cost as a share of notional (taker fee + slippage, both ways), as the engine's ladder
    uses it (the dashboard's Data._round_trip)."""
    from ...config import v3_settings
    fee = _f(taker_fee)
    return v3_settings(**({"taker_fee": fee} if fee else {})).round_trip_cost


def next_lock(lock_roe: Optional[float], ladder: dict) -> Optional[dict]:
    """The next ladder step: the net ROE that arms it and the lock it sets (paperbot.ladder.Ladder.lock_for)."""
    first, step, gap = _f(ladder.get("first_lock")), _f(ladder.get("step")), _f(ladder.get("trigger_gap"))
    if first is None or step is None or gap is None:
        return None
    lock = first if lock_roe is None else lock_roe + step
    return {"lock": lock, "at": lock + gap}


def roe_price(side: int, entry: Optional[float], lev: Optional[int], roe: float, rt: float = 0.0, ff: float = 0.0) -> Optional[float]:
    """The price at which the paper's net ROE reaches ``roe`` (paperbot/ladder.py: entry x (1 + side x (roe / lev + round
    trip + funding / notional)))."""
    if not entry or not lev or not side:
        return None
    return entry * (1 + side * (roe / lev + rt + ff))


def _paper_position(aid: str, e: dict, rt: float, ladder: dict) -> Optional[dict]:
    p = e.get("position") if isinstance(e.get("position"), dict) else None
    if not p:
        return None
    sig = p.get("signal") if isinstance(p.get("signal"), dict) else {}
    meta = sig.get("meta") if isinstance(sig.get("meta"), dict) else {}
    sym, side = p.get("symbol"), _i(p.get("side")) or 0
    qty, entry, lev = _f(p.get("qty")), _f(p.get("entry_price")), _i(p.get("leverage"))
    fund = _f(p.get("funding_paid")) or 0.0
    notional = (qty or 0) * (entry or 0)
    ff = fund / notional if notional else 0.0
    mark = _f((e.get("last_mark") or {}).get(sym)) if isinstance(e.get("last_mark"), dict) else None
    roe = lev * (side * (mark / entry - 1.0) - rt - ff) if (mark and entry and lev) else None
    lock = _f(p.get("lock_roe"))
    nx = next_lock(lock, ladder)
    if nx:
        nx["price"] = roe_price(side, entry, lev, nx["at"], rt, ff)
        nx["lock_price"] = roe_price(side, entry, lev, nx["lock"], rt, ff)
    return {"key": f"{aid}|{sym}|{_i(p.get('entry_time'))}", "symbol": sym, "side": side, "qty": qty, "leverage": lev,
            "entry": entry, "entry_time": _i(p.get("entry_time")), "stop": _f(p.get("stop_price")),
            "stop_initial": _f(p.get("stop_initial")), "lock_roe": lock, "locked": lock is not None,
            "liq": _f(p.get("liq_price")), "margin": _f(p.get("margin_initial")) or _f(p.get("margin")), "funding_paid": fund,
            "funding_frac": ff, "round_trip": rt, "last_mark": mark, "last_mark_roe_net": roe, "next_lock": nx,
            "strategy_id": sig.get("strategy_id"), "timeframe": sig.get("timeframe"), "member": meta.get("member"),
            "member_order": _i(meta.get("member_order")), "stop_rule": meta.get("stop_rule"), "status": "open"}


def read_paper(path: str, accounts: Iterable[str], now_ms: int) -> dict:
    """The paper database: each asked account's engine state and closed trades, the run's settings (one snapshot)."""
    accounts = list(dict.fromkeys(accounts))
    try:
        conn = open_ro(path)
    except FileNotFoundError:
        return _missing(path)
    except (OSError, sqlite3.Error) as exc:
        return _err(path, exc)
    try:
        conn.execute("BEGIN")
        tables = _tables(conn)
        if not {"state", "trades"} <= tables:
            return _missing(path, NO_TABLE_KO)
        st = conn.execute("SELECT ts, data FROM state WHERE k = 'accounts'").fetchone()
        run = conn.execute("SELECT ts, data FROM state WHERE k = 'combo_run'").fetchone()
        created = {}
        if "accounts" in tables:
            created = {a: _i(t) for a, t in conn.execute("SELECT account_id, created_ts FROM accounts")}
        rows = {a: [_paper_trade(r) for r in conn.execute(
            "SELECT id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, data FROM trades "
            "WHERE account_id = ? ORDER BY exit_time, id", (a,))] for a in accounts}
    except sqlite3.Error as exc:
        return _err(path, exc)
    finally:
        conn.close()
    ts = _i(st[0]) if st else None
    engines = _j(st[1]).get("engines") if st else None
    engines = engines if isinstance(engines, dict) else {}
    run_d = _j(run[1]) if run else {}
    cfg = run_d.get("config") if isinstance(run_d.get("config"), dict) else {}
    rt = round_trip(run_d.get("taker_fee"))
    ladder = cfg.get("ladder") if isinstance(cfg.get("ladder"), dict) else {}
    init_cfg = _f(cfg.get("initial_equity"))
    out_acc = {}
    for a in accounts:
        e = engines.get(a) if isinstance(engines.get(a), dict) else None
        trades = rows.get(a, [])
        first = trades[0] if trades else None
        initial = init_cfg if init_cfg is not None else (
            first["equity_after"] - first["pnl"] if first and first["equity_after"] is not None and first["pnl"] is not None else None)
        curve = []
        if trades and initial is not None:
            curve.append([first["entry_time"], initial])
            curve += [[t["exit_time"], t["equity_after"]] for t in trades if t["equity_after"] is not None]
        out_acc[a] = {
            "account": a, "known": e is not None or bool(trades), "since_ms": created.get(a),
            "wallet": _f(e.get("wallet")) if e else None, "initial": initial,
            "halted": bool(e.get("halted")) if e else None, "halt_reason": (e or {}).get("halt_reason") or "",
            "bust": bool(e.get("bust")) if e else None, "max_drawdown": _f(e.get("max_drawdown")) if e else None,
            "position": _paper_position(a, e, rt, ladder) if e else None,
            "stats": {**stats(t["pnl"] for t in trades), "fees": sum(t["fees"] or 0 for t in trades),
                      "funding": sum(t["funding"] or 0 for t in trades)},
            "curve": thin(curve), "trades": trades,
        }
    return {"state": "ok", "path": path, "as_of_ms": ts, "stale": ts is None or now_ms - ts > PAPER_STALE_MS,
            "name_ko": cfg.get("name") if isinstance(cfg.get("name"), str) else None, "round_trip": rt,
            "ladder": {k: _f(ladder.get(k)) for k in ("first_lock", "step", "trigger_gap")} if ladder else None,
            "leverage": cfg.get("leverage") if isinstance(cfg.get("leverage"), dict) else None, "margin": _f(cfg.get("margin")),
            "taker_fee": _f(run_d.get("taker_fee")), "started_ms": _i(run[0]) if run else None, "accounts": out_acc}


# ---------------------------------------------------------------- the order executors (executor.py tables)
def parse_key(key: Any) -> Optional[tuple]:
    """'COMBO@mix|BTCUSDT|1760000000000' -> (account, symbol, paper entry ms); None for another shape."""
    if not isinstance(key, str):
        return None
    parts = key.rsplit("|", 2)
    if len(parts) != 3:
        return None
    t = _i(parts[2])
    return (parts[0], parts[1], t) if t is not None else None


def live_exit(reason: Any, data: dict, side: int, entry: Optional[float]) -> str:
    """What closed an executor trade, from its own words (executor.py _finish reasons): its exchange stop firing (a stop
    already on the profit side of the entry is a lock: 잠금 익절), following the paper's close (the paper's reason is
    added by the caller when the paper trade is known), a halt, or something else."""
    r = str(reason or "")
    stop = _f(data.get("stop"))
    locked = bool(stop and entry and side and (stop - entry) * side > 0)
    if "발동" in r or "이미 지나" in r:
        return "LOCK" if locked else "SL"
    if "paper 청산" in r:
        return "PAPER"
    if "멈" in r or "비상" in r or "정지" in r:
        return "HALT"
    return "OTHER"


def _live_trade(d: dict) -> dict:
    data = _j(d.get("data"))
    k = parse_key(d.get("key"))
    side = _i(d.get("side")) or 0
    entry, qty, lev, pnl = _f(d.get("entry_price")), _f(d.get("qty")), _i(d.get("leverage")), _f(d.get("pnl"))
    margin = entry * qty / lev if entry and qty and lev else None
    src = d.get("pnl_source") or "wallet"
    return {"key": d.get("key"), "symbol": d.get("symbol"), "side": side, "qty": qty, "leverage": lev,
            "entry_ts": _i(d.get("entry_ts")), "entry_price": entry, "stop_initial": _f(d.get("stop_initial")),
            "stop_final": _f(data.get("stop")), "exit_ts": _i(d.get("exit_ts")), "exit_raw": d.get("exit_reason"),
            "exit_reason": live_exit(d.get("exit_reason"), data, side, entry) if d.get("exit_ts") else None,
            "exit_ref": _f(data.get("exit_ref")), "pnl": pnl, "margin": margin,
            "roe": pnl / margin if pnl is not None and margin else None, "pnl_source": src, "est": src != "fills",
            "commission": _f(d.get("commission")), "funding": _f(d.get("funding")), "slippage": _f(d.get("slippage")),
            "paper_entry": _f(data.get("paper_entry")), "paper_time": k[2] if k else (_i(data.get("entry_time")) or _i(d.get("entry_ts"))),
            "account": k[0] if k else None}


def _live_position(t: Optional[dict]) -> Optional[dict]:
    if not isinstance(t, dict) or t.get("status") not in ("open", "entering"):
        return None
    side, entry, stop = _i(t.get("side")) or 0, _f(t.get("entry_price")), _f(t.get("stop"))
    qty, lev = _f(t.get("qty")), _i(t.get("leverage"))
    return {"key": t.get("key"), "status": t.get("status"), "symbol": t.get("symbol"), "side": side, "qty": qty,
            "leverage": lev, "entry": entry, "entry_time": _i(t.get("entry_ts")), "stop": stop,
            "stop_initial": _f(t.get("stop_initial")), "locked": bool(entry and stop and (stop - entry) * side > 0),
            "lock_roe": None, "liq": None, "margin": entry * qty / lev if entry and qty and lev else None,
            "stop_order": t.get("stop_algo_id"), "paper_entry": _f(t.get("paper_entry")),
            "paper_time": (parse_key(t.get("key")) or (None, None, _i(t.get("entry_time"))))[2]}


def read_exec(path: str, now_ms: int) -> dict:
    """One executor's database: its saved state (halt, open trade, last equity), closed trades, equity samples, halts and
    its WARN / CRITICAL events (one snapshot)."""
    try:
        conn = open_ro(path)
    except FileNotFoundError:
        return _missing(path)
    except (OSError, sqlite3.Error) as exc:
        return _err(path, exc)
    try:
        conn.execute("BEGIN")
        tables = _tables(conn)
        if not {"state", "events", "trades"} <= tables:
            return _missing(path, NO_TABLE_KO)
        bot = conn.execute("SELECT ts, data FROM state WHERE k = 'bot'").fetchone()
        meta = conn.execute("SELECT data FROM state WHERE k = 'meta'").fetchone()
        have = _cols(conn, "trades")
        cols = [c for c in EXEC_TRADE_COLS if c in have]
        cur = conn.execute(f"SELECT {', '.join(cols)} FROM trades ORDER BY entry_ts, key")
        trades = [dict(zip(cols, r)) for r in cur.fetchall()]
        eq = []
        if "equity" in tables:
            tcol = "COALESCE(transfers, 0)" if "transfers" in _cols(conn, "equity") else "0"
            eq = conn.execute(f"SELECT ts, equity, wallet, {tcol} FROM equity ORDER BY ts").fetchall()
        halts = conn.execute("SELECT ts, action, reason FROM halts ORDER BY id").fetchall() if "halts" in tables else []
        events = conn.execute("SELECT id, ts, level, kind, text FROM events WHERE level IN ('WARN', 'CRITICAL') "
                              "AND kind != 'retry' ORDER BY id DESC LIMIT ?", (EVENTS_KEEP,)).fetchall()
        why = conn.execute("SELECT id, ts, level, kind, text, data FROM events WHERE kind IN "
                           f"({', '.join('?' * len(WHY))}) ORDER BY id DESC LIMIT ?", (*WHY_KO, WHY_SCAN)).fetchall()
        retry = conn.execute("SELECT COUNT(*) FROM events WHERE kind = 'retry' AND ts >= ?", (now_ms - DAY,)).fetchone()[0]
        first_start = conn.execute("SELECT MIN(ts) FROM events WHERE kind = 'start'").fetchone()[0]
    except sqlite3.Error as exc:
        return _err(path, exc)
    finally:
        conn.close()
    st = _j(bot[1]) if bot else {}
    meta_d = _j(meta[0]) if meta else {}
    risk = st.get("risk") if isinstance(st.get("risk"), dict) else {}
    ts = _i(bot[0]) if bot else None
    live = [_live_trade(t) for t in trades]
    closed = [t for t in live if t["exit_ts"] is not None and t["pnl"] is not None]
    pos = _live_position(st.get("trade"))
    by_key: dict = {}
    for _id, ets, lvl, kind, text, data in why:          # newest first: the first seen per key and kind is the latest
        k = _j(data).get("key")
        if isinstance(k, str):
            if kind == "entry_check" and lvl == "INFO":
                continue                                    # an entry check that passed is not a reason
            by_key.setdefault(k, {}).setdefault(kind, {"ts": _i(ets), "text": text})
    eqs = [(_i(r[0]), _f(r[1]), _f(r[2]), _f(r[3]) or 0.0) for r in eq if _f(r[1]) is not None]
    first_eq = eqs[0] if eqs else None
    last_eq = _f(risk.get("last_equity"))
    if last_eq is None and eqs:
        last_eq = eqs[-1][1]
    # the change since the first recorded balance, deposits and withdrawals left out (executor.equity 'transfers')
    base = None
    if first_eq is not None:
        base = first_eq[1] + ((_f(risk.get("transfers")) if risk.get("transfers") is not None else eqs[-1][3]) - first_eq[3])
    return {
        "state": "ok", "path": path, "as_of_ms": ts, "stale": ts is None or now_ms - ts > EXEC_STALE_MS,
        "mode": st.get("mode") or meta_d.get("mode"), "account": st.get("account") or meta_d.get("account"),
        "exchange": meta_d.get("exchange") or ("binance" if meta_d else None),
        "since_ms": _i(meta_d.get("live_since")) or _i(first_start) or _i(meta_d.get("since")),
        "halted": bool(risk.get("halted")), "halt_reason": risk.get("halt_reason") or "", "halted_ts": _i(risk.get("halted_ts")),
        "consecutive_losses": _i(risk.get("consecutive_losses")),
        "last_equity": last_eq, "first_equity": first_eq[1] if first_eq else None, "first_equity_ts": first_eq[0] if first_eq else None,
        "base_equity": base, "equity_ts": eqs[-1][0] if eqs else None,
        "position": pos,
        "stats": {**stats(t["pnl"] for t in closed), "commission": sum(t["commission"] or 0 for t in closed),
                  "funding": sum(t["funding"] or 0 for t in closed), "estimated": sum(1 for t in closed if t["est"])},
        "curve": thin([[t, e - (tr - (first_eq[3] if first_eq else 0.0))] for t, e, _w, tr in eqs]),
        "trades": closed, "halts": [{"ts": _i(r[0]), "action": r[1], "reason": r[2]} for r in halts],
        "events": [{"id": _i(i), "ts": _i(t), "level": lvl, "kind": k, "kind_ko": KIND_KO.get(k, k), "level_ko": LEVEL_KO.get(lvl, lvl),
                    "text": txt} for i, t, lvl, k, txt in events],
        "retry_24h": int(retry or 0), "why": by_key,
    }


# ---------------------------------------------------------------- 페이퍼 vs 실거래 (the matching every tab uses)
def match(paper: list, live: list, window: int = MATCH_MS) -> dict:
    """{live key: paper trade id}: same coin, same side, paper entry time within ``window``; the closest pairs first, each
    trade used once."""
    cand = []
    for lt in live:
        if lt.get("paper_time") is None:
            continue
        for pt in paper:
            if pt.get("symbol") == lt.get("symbol") and pt.get("side") == lt.get("side") and pt.get("entry_time") is not None:
                gap = abs(int(pt["entry_time"]) - int(lt["paper_time"]))
                if gap <= window:
                    cand.append((gap, str(lt.get("key")), pt["id"]))
    out, used = {}, set()
    for gap, lk, pid in sorted(cand):
        if lk in out or pid in used:
            continue
        out[lk] = pid
        used.add(pid)
    return out


# ---------------------------------------------------------------- the three accounts of the terminal
def hours_of(trades: list, t_key: str = "exit_time") -> list:
    """[[hour END ms, realized P&L, trades, wins, losses]] of the hours in which something closed (dash/more/termpnl.py's
    rule: a close at exactly 13:00:00 belongs to the hour ending 13:00; a win is pnl > 0, a loss pnl < 0)."""
    by: dict = {}
    for t in trades:
        ts, p = _i(t.get(t_key)), _f(t.get("pnl"))
        if ts is None or p is None:
            continue
        e = -(-ts // HOUR) * HOUR
        b = by.setdefault(e, [e, 0.0, 0, 0, 0])
        b[1] += p
        b[2] += 1
        b[3] += 1 if p > 0 else 0
        b[4] += 1 if p < 0 else 0
    return [by[k] for k in sorted(by)]


def calendar_of(trades: list, key: str, since: Optional[int], now: int, t_key: str = "exit_time") -> dict:
    """The current Korea-time month as the terminal's 수익 캘린더 reads it (dash/more/flow.py calendar shape): every day with
    ``state`` future / empty (before the account's first record: no record, never a zero) / done / today, and for a day
    with a record ``g[key] = {pnl, trades, wins}`` of the trades that closed that day."""
    today = kst_day(now)
    epoch = _dt.date(1970, 1, 1)
    d = epoch + _dt.timedelta(days=today)
    first = (_dt.date(d.year, d.month, 1) - epoch).days
    last = ((_dt.date(d.year + 1, 1, 1) if d.month == 12 else _dt.date(d.year, d.month + 1, 1)) - epoch).days - 1
    by: dict = {}
    for t in trades:
        ts, p = _i(t.get(t_key)), _f(t.get("pnl"))
        if ts is None or p is None:
            continue
        g = by.setdefault(kst_day(ts), {"pnl": 0.0, "trades": 0, "wins": 0})
        g["pnl"] += p
        g["trades"] += 1
        g["wins"] += 1 if p > 0 else 0
    start = kst_day(since) if since else None
    days = []
    for kd in range(first, last + 1):
        e = {"d": time.strftime("%Y-%m-%d", time.gmtime(kd * 86_400)), "ts": kst_day_start(kd), "dow": (kd + 3) % 7}
        if kd > today:
            e["state"] = "future"
        elif (start is None or kd < start) and kd not in by:
            e["state"] = "empty"
        else:
            e["state"] = "today" if kd == today else "done"
            e["g"] = {key: by.get(kd, {"pnl": 0.0, "trades": 0, "wins": 0})}
        days.append(e)
    return {"ready": True, "now": now, "today": time.strftime("%Y-%m-%d", time.gmtime(today * 86_400)), "keys": [key], "days": days}


def today_of(trades: list, now: int, t_key: str = "exit_time") -> dict:
    t0 = kst_day_start(kst_day(now))
    xs = [t for t in trades if (_i(t.get(t_key)) or 0) >= t0 and _f(t.get("pnl")) is not None]
    return {"trades": len(xs), "wins": sum(1 for t in xs if t["pnl"] > 0), "losses": sum(1 for t in xs if t["pnl"] < 0),
            "pnl": sum(t["pnl"] for t in xs), "from_ms": t0}


def checkpoint(trades: list) -> dict:
    """Progress to the owners' 40-trade look (paper closed trades of this database). Nothing is judged before 40."""
    st = stats(t.get("pnl") for t in trades)
    n, goal = st["trades"], CHECKPOINT["trades"]
    out = {**CHECKPOINT, "n": n, "left": max(0, goal - n), "win_rate": st["win_rate"], "ready": n >= goal, "zone": None}
    if n >= goal:
        last = [t.get("pnl") for t in trades[-goal:]]
        w = sum(1 for p in last if (_f(p) or 0) > 0) / goal
        out["last_win_rate"] = w
        out["zone"] = "up" if w >= CHECKPOINT["up"] - 1e-9 else "mid" if w >= CHECKPOINT["low"] - 1e-9 else "low"
    return out


def acct_paper(paper: dict, account: str, now: int) -> dict:
    """The paper account (A+C 합본) as one of the terminal's three accounts."""
    base = {"id": "paper", "name_ko": "페이퍼", "kind": "paper", "account": account}
    if paper.get("state") != "ok":
        return {**base, "state": paper.get("state"), "reason_ko": paper.get("reason_ko"), "reason": paper.get("reason"), "path": paper.get("path")}
    a = (paper.get("accounts") or {}).get(account) or {}
    if not a.get("known"):
        return {**base, "state": "missing", "reason_ko": "페이퍼 DB에 이 계좌의 기록이 아직 없어요", "path": paper.get("path")}
    trades = a.get("trades") or []
    since = a.get("since_ms") or paper.get("started_ms")
    return {**base, "state": "ok", "sub_ko": paper.get("name_ko") or "A+C 합본", "as_of_ms": paper.get("as_of_ms"),
            "stale": paper.get("stale"), "balance": a.get("wallet"), "initial": a.get("initial"), "halted": bool(a.get("halted")),
            "halt_reason": a.get("halt_reason") or "", "bust": bool(a.get("bust")), "position": a.get("position"),
            "stats": a.get("stats"), "today": today_of(trades, now), "since_ms": since,
            "hours": hours_of(trades), "start": since, "calendar": calendar_of(trades, "paper", since, now),
            "curve": a.get("curve")}


def acct_exec(x: dict, paper_pos: Optional[dict], now: int) -> dict:
    """An executor as one of the terminal's three accounts. Its open position borrows the paper position's next lock step
    when it follows that very paper position (the executor moves its stop when the paper's lock moves)."""
    r, cfg = x["record"], x["config"] or {}
    base = {"id": x["id"], "name_ko": x["name_ko"], "kind": "live", "account": x["follows"]}
    if r.get("state") != "ok":
        return {**base, "state": r.get("state"), "reason_ko": r.get("reason_ko"), "reason": r.get("reason"), "path": r.get("path")}
    trades = r.get("trades") or []
    pos = r.get("position")
    if pos:
        pos = dict(pos)
        if paper_pos and pos.get("key") == paper_pos.get("key") and paper_pos.get("next_lock"):
            pos["next_lock"] = {**paper_pos["next_lock"], "from": "paper"}
            pos["paper_lock_roe"] = paper_pos.get("lock_roe")
    since = r.get("since_ms")
    return {**base, "state": "ok", "sub_ko": "실거래 실행기" if r.get("mode") == "mainnet" else f"실행기 · {r.get('mode') or '모드 모름'}",
            "as_of_ms": r.get("as_of_ms"), "stale": r.get("stale"), "balance": r.get("last_equity"), "initial": r.get("base_equity"),
            "initial_ts": r.get("first_equity_ts"), "halted": bool(r.get("halted")), "halt_reason": r.get("halt_reason") or "",
            "halted_ts": r.get("halted_ts"), "consecutive_losses": r.get("consecutive_losses"),
            "max_consecutive_losses": cfg.get("max_consecutive_losses"), "kill_file": cfg.get("kill_file"),
            "budget_usd": cfg.get("budget_usd"), "position": pos, "stats": r.get("stats"),
            "today": today_of(trades, now, "exit_ts"), "since_ms": since, "hours": hours_of(trades, "exit_ts"), "start": since,
            "calendar": calendar_of(trades, x["id"], since, now, "exit_ts"), "curve": r.get("curve")}


def fills_of(paper: dict, execs: list, account: str, limit: int = FILLS_KEEP) -> list:
    """실거래 체결: every entry and exit of the three accounts, newest first. A live exit that followed the paper's close takes
    the paper trade's reason (손절 / 잠금 익절) when the two trades are matched; the reason is never guessed from the P&L."""
    out = []
    a = (paper.get("accounts") or {}).get(account) if paper.get("state") == "ok" else None
    ptrades = (a or {}).get("trades") or []
    by_id = {t["id"]: t for t in ptrades}
    for t in ptrades:
        base = {"acct": "paper", "symbol": t["symbol"], "side": t["side"], "lev": t["leverage"]}
        out.append({**base, "key": f"paper:e:{t['id']}", "kind": "entry", "t": t["entry_time"], "price": t["entry_price"]})
        out.append({**base, "key": f"paper:x:{t['id']}", "kind": "exit", "t": t["exit_time"], "price": t["exit_price"], "pnl": t["pnl"],
                    "roe": t["roe"], "reason": t["exit_reason"], "reason_ko": EXIT_KO.get(t["exit_reason"], t["exit_reason"])})
    p = (a or {}).get("position")
    if p:
        out.append({"acct": "paper", "symbol": p["symbol"], "side": p["side"], "lev": p["leverage"], "key": f"paper:e:{p['key']}",
                    "kind": "entry", "t": p["entry_time"], "price": p["entry"], "open": True})
    for x in execs:
        r = x["record"]
        if r.get("state") != "ok":
            continue
        pairs = match(ptrades, r.get("trades") or [])
        for t in r.get("trades") or []:
            base = {"acct": x["id"], "symbol": t["symbol"], "side": t["side"], "lev": t["leverage"]}
            reason = t["exit_reason"]
            if reason == "PAPER" and str(t["key"]) in pairs:
                reason = by_id[pairs[str(t["key"])]]["exit_reason"] or reason
            out.append({**base, "key": f"{x['id']}:e:{t['key']}", "kind": "entry", "t": t["entry_ts"], "price": t["entry_price"]})
            out.append({**base, "key": f"{x['id']}:x:{t['key']}", "kind": "exit", "t": t["exit_ts"], "price": t["exit_ref"], "pnl": t["pnl"],
                        "roe": t["roe"], "est": t["est"], "reason": reason, "reason_ko": EXIT_KO.get(reason, reason)})
        q = r.get("position")
        if q and q.get("entry_time"):
            out.append({"acct": x["id"], "symbol": q["symbol"], "side": q["side"], "lev": q["leverage"], "key": f"{x['id']}:e:{q['key']}",
                        "kind": "entry", "t": q["entry_time"], "price": q["entry"], "open": True})
    out = [f for f in out if f.get("t") is not None]
    out.sort(key=lambda f: (-(f["t"] or 0), 0 if f["kind"] == "exit" else 1, f["key"]))
    return out[:limit]


def marks_of(paper: dict, execs: list, account: str, sym_limit: int = 12) -> list:
    """Recent closed trades of every account for the chart's entry / exit marks: {acct, symbol, side, entry_time, exit_time,
    pnl}, newest first, at most ``sym_limit`` per coin."""
    out, per = [], {}
    a = (paper.get("accounts") or {}).get(account) if paper.get("state") == "ok" else None
    rows = [("paper", t["symbol"], t["side"], t["entry_time"], t["exit_time"], t["pnl"]) for t in (a or {}).get("trades") or []]
    for x in execs:
        r = x["record"]
        if r.get("state") == "ok":
            rows += [(x["id"], t["symbol"], t["side"], t["entry_ts"], t["exit_ts"], t["pnl"]) for t in r.get("trades") or []]
    for acct, sym, side, et, xt, pnl in sorted(rows, key=lambda r: -(r[4] or 0)):
        if et is None or xt is None or per.get(sym, 0) >= sym_limit:
            continue
        per[sym] = per.get(sym, 0) + 1
        out.append({"acct": acct, "symbol": sym, "side": side, "entry_time": et, "exit_time": xt, "pnl": pnl})
    return out


# ---------------------------------------------------------------- the whole answer
def sources(p: dict, now: int) -> tuple:
    """(configs, follows, paper, execs): every source read once, in one snapshot each."""
    configs = {ex: read_config(p[ck]) for ex, _ko, _dk, ck in EXECS}
    follows = {ex: (c.get("account") if c.get("state") == "ok" and c.get("account") else ACCOUNT) for ex, c in configs.items()}
    paper = read_paper(p["paper"], [ACCOUNT, FLIP_ACCOUNT, *follows.values()], now)
    execs = []
    for ex, ko, dk, _ck in EXECS:
        cfg = configs[ex]
        rec = read_exec(p[dk], now)
        acc = (paper.get("accounts") or {}).get(follows[ex]) or {}
        if cfg.get("state") != "ok":
            lt = {"state": "unknown", "reason_ko": "실행기 설정을 읽지 못해 신호등 기준을 몰라요" if cfg.get("state") == "error"
                  else "실행기 설정 파일이 아직 없어 신호등 기준을 몰라요", "config_state": cfg.get("state")}
        elif paper.get("state") != "ok":
            lt = {"state": "unknown", "reason_ko": "페이퍼 기록을 읽지 못해 신호등을 계산하지 못해요", "paper_state": paper.get("state"),
                  "n": cfg["signal_light_n"], "min_win": cfg["signal_light_min_win"]}
        else:
            newest = [t["pnl"] for t in sorted(acc.get("trades") or [], key=lambda t: (t["exit_time"] or 0, t["id"] or 0), reverse=True)]
            lt = light(cfg["signal_light_n"], cfg["signal_light_min_win"], newest)
        if rec.get("state") == "ok":
            last = next((e for e in rec.get("events") or [] if e["kind"] in ("light_red", "light_unread")), None)
            lt["last_event"] = last
        notes = []
        if cfg.get("state") == "ok":
            if cfg.get("paper_db") and os.path.abspath(cfg["paper_db"]) != os.path.abspath(p["paper"]):
                notes.append(f"이 실행기는 다른 페이퍼 DB({cfg['paper_db']})를 따라가요. 이 화면의 신호등과 비교는 {p['paper']} 기준이에요")
            if cfg.get("db") and os.path.abspath(cfg["db"]) != os.path.abspath(p[dk]):
                notes.append(f"실행기 설정의 DB({cfg['db']})와 이 화면이 읽는 DB({p[dk]})가 달라요")
            if follows[ex] != ACCOUNT:
                notes.append(f"이 실행기는 {follows[ex]} 계좌를 따라가요")
        if rec.get("state") == "ok" and rec.get("account") and rec["account"] != follows[ex]:
            notes.append(f"실행기 기록의 계좌({rec['account']})와 설정의 계좌({follows[ex]})가 달라요")
        execs.append({"id": ex, "name_ko": ko, "follows": follows[ex], "config": cfg, "record": rec, "light": lt, "notes": notes})
    return configs, follows, paper, execs


def build(p: Optional[dict] = None, now_ms: Optional[int] = None) -> dict:
    """GET /api/v4/livebots: the terminal's answer."""
    p = p or paths()
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    _configs, _follows, paper, execs = sources(p, now)
    pa = (paper.get("accounts") or {}).get(ACCOUNT) if paper.get("state") == "ok" else None
    ppos = (pa or {}).get("position")
    accts = [acct_paper(paper, ACCOUNT, now)] + [acct_exec(x, ppos, now) for x in execs]
    fills = fills_of(paper, execs, ACCOUNT)
    marks = marks_of(paper, execs, ACCOUNT)
    events = sorted(((dict(e, ex=x["id"], ex_ko=x["name_ko"])) for x in execs for e in (x["record"].get("events") or [])),
                    key=lambda e: (e["ts"] or 0, e["id"] or 0), reverse=True)[:2 * EVENTS_KEEP]
    cp = checkpoint((pa or {}).get("trades") or []) if pa else None
    flip = (paper.get("accounts") or {}).get(FLIP_ACCOUNT) if paper.get("state") == "ok" else None
    for x in execs:                                      # the page needs neither the raw reasons nor the full trade list here
        rec = x["record"]
        rec.pop("why", None)
        rec.pop("events", None)
        if rec.get("trades") is not None:
            rec["trades_n"] = len(rec.pop("trades"))
        rec.pop("curve", None)
    paper_out = {k: v for k, v in paper.items() if k != "accounts"}
    if paper.get("state") == "ok":
        paper_out["accounts"] = {}
        for aid, a in paper["accounts"].items():
            paper_out["accounts"][aid] = {k: v for k, v in a.items() if k not in ("trades", "curve")}
    return {"now_ms": now, "paths": p, "account": ACCOUNT, "flip_account": FLIP_ACCOUNT, "paper": paper_out, "execs": execs,
            "accts": accts, "fills": fills, "marks": marks, "events": events, "checkpoint": cp,
            "flip": {"stats": flip.get("stats")} if flip and flip.get("known") else None,
            "refs": REFS, "match_ms": MATCH_MS, "small": list(SMALL)}


# ================================================================ the other tabs (거래 · 신호 · 성적 · 안전 · 그림자 · 설정)
TF_KO = {"5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
SIDE_KO = {1: "롱", -1: "숏"}
COINS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")      # paperbot/rmember.py SYMS (the index of `sym`)
DOW_KO = "월화수목금토일"
REG_KO = {0: "상승장", 1: "하락장", 2: "횡보장"}
REG5_KO = {0: "강한 상승", 1: "약한 상승", 2: "강한 하락", 3: "약한 하락", 4: "횡보"}
POS_KO = {0: "7일 범위 아래 밖", 1: "7일 범위 아래 20%", 2: "7일 범위 가운데", 3: "7일 범위 위 20%", 4: "7일 범위 위 밖"}
SESSION_KO = {0: "아시아(09-17시)", 1: "유럽(17-22시)", 2: "미국(22-06시)", 3: "새벽(06-09시)"}
DIM_KO = {"sym": "코인", "side": "방향", "symside": "코인x방향", "hb": "4시간대", "hr": "시각", "dow": "요일", "wk": "주말", "btc": "BTC추세",
          "ctr4": "코인4h추세", "mom24": "24h모멘텀", "vol3": "변동성", "fund": "펀딩", "reg": "장세", "regwk": "장세x주말",
          "regside": "장세x방향", "reg5": "추세세기", "reg5side": "추세세기x방향", "pos": "7일위치", "posside": "7일위치x방향",
          "oi24": "미결제약정"}                                  # paperbot/rmember.py KO_DIM
FILTER_KO = {"session": "시간대", "weekend": "주말", "btc": "BTC 4시간 추세", "ctr4": "코인 4시간 추세", "mom24": "24시간 흐름", "vol3": "변동성",
             "fund": "펀딩", "side": "방향"}
SIGNALS_KEEP = 200                     # recent signal rows sent (the page pages them 10 at a time)
TRADES_KEEP = 500                      # closed trades per account sent to 거래 (newest first)
SHADOWS = (("b", "shadow-b.db", "그림자 B 안정형"), ("nocut", "shadow-nocut.db", "그림자 끄는 구간 없음"), ("ac32", "shadow-ac32.db", "그림자 32개"))
ENV_MORE = {"shadow_dir": ("PAPERBOT_LIVE_SHADOW_DIR", "/var/lib/paperbot/combo"),
            "combo_config": ("PAPERBOT_LIVE_COMBO_CONFIG", "/etc/paperbot/combo.json")}


def paths_more(env: Optional[dict] = None) -> dict:
    env = os.environ if env is None else env
    return {k: (env.get(var) or default) for k, (var, default) in ENV_MORE.items()}


def dim_value_ko(dim: str, v: Any) -> str:
    """One ``off`` bucket in the owners' words (paperbot/rmember.py definitions)."""
    v = _i(v)
    if v is None:
        return "?"
    coin = lambda i: COINS[i].replace("USDT", "") if 0 <= i < len(COINS) else str(i)          # noqa: E731
    ls = lambda x: "롱" if x else "숏"                                                         # noqa: E731
    if dim == "sym":
        return coin(v)
    if dim == "side":
        return SIDE_KO.get(v, str(v))
    if dim == "symside":
        return f"{coin(v // 2)} {ls(v % 2)}"
    if dim == "hb":
        return f"{v * 4:02d}~{v * 4 + 4:02d}시"
    if dim == "hr":
        return f"{v:02d}시"
    if dim == "dow":
        return DOW_KO[v] + "요일" if 0 <= v < 7 else str(v)
    if dim == "wk":
        return "주말" if v else "평일"
    if dim in ("btc", "ctr4", "mom24"):
        return "같은 방향" if v else "반대 방향"
    if dim == "vol3":
        return {0: "낮음", 1: "보통", 2: "높음"}.get(v, str(v))
    if dim == "fund":
        return "이 방향이 펀딩을 냄" if v else "펀딩을 안 냄"
    if dim == "reg":
        return REG_KO.get(v, str(v))
    if dim == "regwk":
        return f"{REG_KO.get(v // 2, v // 2)} {'주말' if v % 2 else '평일'}"
    if dim == "regside":
        return f"{REG_KO.get(v // 2, v // 2)} {ls(v % 2)}"
    if dim == "reg5":
        return REG5_KO.get(v, str(v))
    if dim == "reg5side":
        return f"{REG5_KO.get(v // 2, v // 2)} {ls(v % 2)}"
    if dim == "pos":
        return POS_KO.get(v, str(v))
    if dim == "posside":
        return f"{POS_KO.get(v // 2, v // 2)} {ls(v % 2)}"
    if dim == "oi24":
        return {0: "미결제약정 줄어듦(-5% 아래)", 1: "미결제약정 비슷", 2: "미결제약정 늘어남(+5% 위)", 3: "미결제약정 모름"}.get(v, str(v))
    return str(v)


def filter_ko(tag: str, v: Any) -> str:
    v = _i(v)
    if tag == "session":
        return f"시간대 {SESSION_KO.get(v, v)}"
    if tag == "weekend":
        return "주말만" if v else "평일만"
    if tag == "side":
        return "롱만" if v == 1 else "숏만"
    if tag == "vol3":
        return f"변동성 {({0: '낮음', 1: '보통', 2: '높음'}).get(v, v)}"
    if tag == "fund":
        return "그 방향이 펀딩을 낼 때" if v else "그 방향이 펀딩을 안 낼 때"
    return f"{FILTER_KO.get(tag, tag)} {'같은 방향' if v else '반대 방향'}"


def stop_ko(stop: Any, cfg_stop: Optional[dict] = None) -> dict:
    """A member's stop rule in words: its own research stop, or the config's house stop."""
    if isinstance(stop, (list, tuple)) and len(stop) == 2:
        mode, k = str(stop[0]), _f(stop[1])
        ko = {"atr": f"ATR {k:g}배 (강제청산 안쪽에 안 맞으면 당김, 최소 ATR 1배)" if k else "ATR",
              "pct": f"진입가의 {k:g}% (강제청산 안쪽으로 당김)" if k else "%", "swing": f"스윙 {k:g}봉 너머 +0.1% (최소 0.3%)" if k else "스윙"}.get(mode, mode)
        return {"mode": mode, "value": k, "ko": ko}
    c = cfg_stop or {}
    mode, k = c.get("mode", "atr"), _f(c.get("atr"))
    if mode == "roe":
        return {"mode": "roe", "value": _f(c.get("roe")), "ko": f"ROE -{(_f(c.get('roe')) or 0) * 100:g}%"}
    return {"mode": mode, "value": k, "ko": f"ATR {k:g}배" + (" (안 맞으면 당김)" if mode == "atr_fit" else "") if k else "ATR"}


def describe_member(sp: dict, order: int, cfg_stop: Optional[dict] = None) -> dict:
    """One setting of the combined bot's config (a ``members`` item) in the owners' words."""
    sp = sp if isinstance(sp, dict) else {}
    off = [{"dim": str(o[0]), "dim_ko": DIM_KO.get(str(o[0]), str(o[0])), "value": o[1], "ko": f"{DIM_KO.get(str(o[0]), o[0])}: {dim_value_ko(str(o[0]), o[1])}"}
           for o in sp.get("off") or [] if isinstance(o, (list, tuple)) and len(o) == 2]
    flt = [{"tag": str(f[0]), "value": f[1], "ko": filter_ko(str(f[0]), f[1])} for f in sp.get("filter") or [] if isinstance(f, (list, tuple)) and len(f) == 2]
    disp = sp.get("disp")
    disp_ko = None
    if isinstance(disp, (list, tuple)) and len(disp) == 2:
        disp_ko = {"range": f"신호봉 높이 ATR {disp[1]:g}배 이상", "body": f"신호봉 몸통 ATR {disp[1]:g}배 이상",
                   "small": f"신호봉 높이 ATR {disp[1]:g}배 미만"}.get(str(disp[0]), str(disp[0]))
    numbers = sp.get("numbers") if isinstance(sp.get("numbers"), dict) else None
    return {"order": order, "strategy": sp.get("strategy") or sp.get("pick"), "tf": sp.get("tf"), "tf_ko": TF_KO.get(sp.get("tf"), sp.get("tf")),
            "numbers": numbers, "custom": numbers is not None, "entry": sp.get("entry", "now"),
            "entry_ko": "돌파 확인" if sp.get("entry") == "break" else "즉시", "invert": bool(sp.get("invert")),
            "stop": stop_ko(sp.get("stop"), cfg_stop), "filter": flt, "disp": disp_ko, "off": off, "cell": sp.get("cell"),
            "when": sp.get("when")}


def read_combo(paper_path: str, cfg_path: str) -> dict:
    """The combined bot's settings: the config it really runs (combo_run in its database) or, before its first start,
    the config file (/etc/paperbot/combo.json). Nothing is computed from strategy code."""
    run = None
    try:
        conn = open_ro(paper_path)
        try:
            if "state" in _tables(conn):
                r = conn.execute("SELECT ts, data FROM state WHERE k = 'combo_run'").fetchone()
                run = (_i(r[0]), _j(r[1])) if r else None
        finally:
            conn.close()
    except (OSError, sqlite3.Error):
        run = None
    if run and isinstance(run[1].get("config"), dict):
        return {"state": "ok", "source": "db", "path": paper_path, "since_ms": run[0], "config": run[1]["config"],
                "describe": run[1].get("members") if isinstance(run[1].get("members"), list) else None, "taker_fee": _f(run[1].get("taker_fee"))}
    try:
        with open(cfg_path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return _missing(cfg_path, "합친 봇 설정이 아직 없어요 (봇의 DB에도, 설정 파일에도)")
    except ValueError as exc:
        return {**_err(cfg_path, exc), "reason_ko": "합친 봇 설정 파일이 JSON 모양이 아니에요"}
    except OSError as exc:
        return _err(cfg_path, exc)
    if not isinstance(raw, dict):
        return {"state": "error", "path": cfg_path, "reason": "not an object", "reason_ko": "합친 봇 설정 파일의 모양이 달라요"}
    return {"state": "ok", "source": "file", "path": cfg_path, "since_ms": None, "config": raw, "describe": None, "taker_fee": None}


def members_of(combo: dict) -> list:
    cfg = combo.get("config") or {}
    return [describe_member(sp, i, cfg.get("stop")) for i, sp in enumerate(cfg.get("members") or [], 1)]


def rules_of(combo: dict) -> dict:
    """The fixed rules every setting shares, from the config."""
    c = combo.get("config") or {}
    lev = c.get("leverage") if isinstance(c.get("leverage"), dict) else {"BTCUSDT": 40, "default": 30}
    lad = c.get("ladder") if isinstance(c.get("ladder"), dict) else {}
    first, step, gap = _f(lad.get("first_lock")), _f(lad.get("step")), _f(lad.get("trigger_gap"))
    margin = c.get("margin", "leverage")
    return {"leverage_btc": _i(lev.get("BTCUSDT")), "leverage_alt": _i(lev.get("default")), "margin": margin if isinstance(margin, str) else _f(margin),
            "ladder": {"first_lock": first, "step": step, "trigger_gap": gap}, "max_loss_frac": _f(c.get("max_loss_frac")),
            "no_weekend": bool(c.get("no_weekend")), "macro_blackout_min": _i(c.get("macro_blackout_min")), "early_exit": c.get("early_exit"),
            "one_position": True, "initial_equity": _f(c.get("initial_equity")), "name": c.get("name"),
            "stop": stop_ko(None, c.get("stop") if isinstance(c.get("stop"), dict) else None),
            "rank": c.get("rank"), "flip_twin": bool(c.get("flip_twin", True))}


# ---------------------------------------------------------------- the paper bot's signals and outcomes (신호 · 거래)
def why_cat(status: str, why: str) -> tuple:
    """(category id, Korean) of a FILTERED / WAITING / BROKE signal_log row (paperbot/combo.py: _allowed, _submit_due,
    _research_signal, _research_entry, _breaks)."""
    w = str(why or "")
    if status == "WAITING":
        return "waiting", "돌파 기다림"
    if status == "BROKE":
        return "broke", "돌파 확인 (진입 신호로 바뀜)"
    if w.startswith("연구 조건 밖"):
        return "research", "연구 조건 밖"
    if w.startswith("끈 구간"):
        return "off", "끈 구간"
    if w.startswith("주말"):
        return "weekend", "주말 진입 안 함"
    if w.startswith("경제 발표"):
        return "macro", "경제 발표 앞뒤"
    if w.startswith("돌파 없음"):
        return "nobreak", "돌파 없음"
    if w.startswith("돌파 확인이 늦음"):
        return "late", "늦음"
    if "못 읽음" in w:
        return "unread", "조건을 못 읽음"
    if w.startswith("조건 밖"):
        return "when", "조건 밖"
    if w.startswith("설정에 없는"):
        return "config", "설정이 바뀜"
    return "other", w or "이유 기록 없음"


def why_words(why: Any) -> Optional[str]:
    """The bot's why of a filtered signal with its bucket codes in words ('끈 구간: hr=5, symside=7' -> '끈 구간: 시각 05시 · 코인x방향
    DOGE 롱'; '연구 조건 밖: weekend=0' -> '연구 조건 밖 (필요: 평일만)'); any other text as it is."""
    w = str(why or "")
    for head, kind in (("끈 구간: ", "off"), ("연구 조건 밖: ", "filter")):
        if not w.startswith(head):
            continue
        parts = []
        for item in w[len(head):].split(", "):
            k, sep, v = item.partition("=")
            if not sep:
                return w
            if kind == "off":
                parts.append(f"{DIM_KO.get(k, k)} {'읽기 실패' if v == '읽기 실패' else dim_value_ko(k, v)}")
            else:
                parts.append(filter_ko(k, v))
        return f"끈 구간: {' · '.join(parts)}" if kind == "off" else f"연구 조건 밖 (필요: {' · '.join(parts)})"
    return w or None


def outcome_cat(status: str, reason: str) -> tuple:
    """(category id, Korean) of an engine outcome (paperbot/engine.py _record, combo.py)."""
    r = str(reason or "")
    if status == "ENTERED":
        return "entered", "진입"
    if r == "in position":
        return "held", "포지션 있음 (한 번에 하나)"
    if r.startswith("lower score"):
        return "lost", "같은 때 다른 신호에 밀림"
    if r == "late":
        return "late", "늦음"
    if r == "stop rule":
        return "stoprule", "손절 자리가 안 맞음"
    if r == "sizing":
        return "sizing", "크기 계산 거절"
    if r.startswith("halted"):
        return "halted", "페이퍼 멈춤"
    if r.startswith("early exit"):
        return "early", "빠른 청산 분"
    if r.startswith("guard"):
        return "guard", "보호 장치"
    return "other", r or "이유 기록 없음"


def read_signals(path: str, account: str, now: int, keep: int = SIGNALS_KEEP) -> dict:
    """신호: every signal_log row of the combined bot and what became of it (its outcome for the account), counted per
    reason for today (KST) and the last 7 days, and the newest ``keep`` rows."""
    try:
        conn = open_ro(path)
    except FileNotFoundError:
        return _missing(path)
    except (OSError, sqlite3.Error) as exc:
        return _err(path, exc)
    since = kst_day_start(kst_day(now)) - 6 * DAY
    try:
        conn.execute("BEGIN")
        tables = _tables(conn)
        if "signal_log" not in tables:
            return _missing(path, NO_TABLE_KO)
        rows = conn.execute("SELECT id, bar_close, timeframe, strategy, symbol, side, status, data FROM signal_log WHERE bar_close >= ? "
                            "ORDER BY bar_close, id", (since,)).fetchall()
        outs = conn.execute("SELECT step_ts, status, reason, symbol, data FROM outcomes WHERE account_id = ? AND step_ts >= ? ORDER BY id",
                            (account, since)).fetchall() if "outcomes" in tables else []
    except sqlite3.Error as exc:
        return _err(path, exc)
    finally:
        conn.close()
    oc: dict = {}
    for step, st, reason, sym, data in outs:
        d = _j(data)
        sig = d.get("signal") if isinstance(d.get("signal"), dict) else {}
        meta = sig.get("meta") if isinstance(sig.get("meta"), dict) else {}
        k = (_i(sig.get("ts")), sig.get("timeframe"), meta.get("member") or sig.get("strategy_id"), sym)
        if k[0] is None:
            continue
        oc[(k[0] + 1, k[1], k[2], k[3])] = (st, reason, _i(step))
    t0 = kst_day_start(kst_day(now))
    out_rows, counts = [], {"today": {}, "week": {}}
    for _id, bc, tf, strat, sym, side, status, data in rows:
        d = _j(data)
        if status in ("FILTERED", "WAITING", "BROKE"):
            cat, ko = why_cat(status, d.get("why"))
            stage = "filtered" if status == "FILTERED" else status.lower()
        elif status == "SUBMITTED":
            o = oc.get((_i(bc), tf, strat, sym))
            if o:
                cat, ko = outcome_cat(o[0], o[1])
                stage = "entered" if o[0] == "ENTERED" else "skipped" if o[0] == "SKIPPED" else "rejected"
            else:
                cat, ko, stage = "pending", "제출됨 (결과 기록 전)", "submitted"
        else:
            cat, ko, stage = "other", str(status), "other"
        name = d.get("strategy") or str(strat).split("@")[0]
        row = {"id": _i(_id), "t": _i(bc), "tf": tf, "member": strat, "strategy": name, "symbol": sym, "side": _i(side), "status": status,
               "stage": stage, "cat": cat, "ko": ko, "why": d.get("why"), "why_ko": why_words(d.get("why")) if d.get("why") else None,
               "source": d.get("source")}
        out_rows.append(row)
        for span in ("week",) + (("today",) if (_i(bc) or 0) >= t0 else ()):
            c = counts[span].setdefault(cat, {"cat": cat, "ko": ko, "stage": stage, "n": 0})
            c["n"] += 1
    stages = {}
    for span in ("today", "week"):
        st_ = {"signals": 0, "filtered": 0, "entered": 0, "skipped": 0, "rejected": 0, "waiting": 0}
        for r in out_rows:
            if span == "today" and (r["t"] or 0) < t0:
                continue
            if r["status"] == "BROKE":
                continue                                   # its entry signal is a SUBMITTED row of its own
            st_["signals"] += 1
            if r["stage"] in st_:
                st_[r["stage"]] += 1
        stages[span] = st_
    return {"state": "ok", "path": path, "since_ms": since, "today_ms": t0,
            "counts": {k: sorted(v.values(), key=lambda c: -c["n"]) for k, v in counts.items()}, "stages": stages,
            "rows": out_rows[::-1][:keep], "n": len(out_rows)}


def entered_meta(path: str, account: str) -> dict:
    """{(symbol, entry ms): the entered signal's meta} of the account: which setting (member, its order in the config),
    the stop rule, the score, the research tags. Read from the ENTERED outcomes (their step is the entry minute)."""
    try:
        conn = open_ro(path)
    except (OSError, sqlite3.Error):
        return {}
    try:
        if "outcomes" not in _tables(conn):
            return {}
        rows = conn.execute("SELECT step_ts, symbol, data FROM outcomes WHERE account_id = ? AND status = 'ENTERED'", (account,)).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    out = {}
    for step, sym, data in rows:
        d = _j(data)
        sig = d.get("signal") if isinstance(d.get("signal"), dict) else {}
        meta = sig.get("meta") if isinstance(sig.get("meta"), dict) else {}
        det = d.get("detail") if isinstance(d.get("detail"), dict) else {}
        out[(sym, _i(step))] = {"member": meta.get("member"), "member_order": _i(meta.get("member_order")), "stop_rule": meta.get("stop_rule"),
                                "score": _f(sig.get("score")), "source": meta.get("source"), "fill": _f(det.get("fill")),
                                "ref_price": _f(meta.get("ref_price")), "break_level": _f(meta.get("break_level"))}
    return out


# ---------------------------------------------------------------- 거래
def trade_rows(p: dict, now: int) -> dict:
    """GET /api/v4/livebots/trades: every closed trade of the three accounts (newest first, at most TRADES_KEEP each) with
    its setting, its reason, its costs and its partners on the other side (live <-> paper: same coin and side, entry within
    5 minutes; slippage = the live entry against the paper's, in the trade's favour positive)."""
    _configs, _follows, paper, execs = sources(p, now)
    combo = read_combo(p["paper"], paths_more()["combo_config"])
    members = members_of(combo) if combo.get("state") == "ok" else []
    meta = entered_meta(p["paper"], ACCOUNT) if paper.get("state") == "ok" else {}
    a = (paper.get("accounts") or {}).get(ACCOUNT) if paper.get("state") == "ok" else None
    ptrades = (a or {}).get("trades") or []
    by_pid = {t["id"]: t for t in ptrades}
    pairs = {x["id"]: (match(ptrades, x["record"].get("trades") or []) if x["record"].get("state") == "ok" else {}) for x in execs}
    rev = {xid: {pid: lk for lk, pid in m.items()} for xid, m in pairs.items()}
    live_by = {x["id"]: {str(t["key"]): t for t in x["record"].get("trades") or []} for x in execs if x["record"].get("state") == "ok"}

    def setting(sym, et):
        m = meta.get((sym, et)) or {}
        order = m.get("member_order")
        mem = members[order - 1] if order and 0 < order <= len(members) else None
        return {"member": m.get("member"), "order": order, "stop_rule": m.get("stop_rule"), "score": m.get("score"), "setting": mem,
                "break_level": m.get("break_level")}

    out = {"paper": None, "bybit": None, "mexc": None}
    if a is not None:
        rows = []
        for t in reversed(ptrades[-TRADES_KEEP:]):
            cells = {}
            for x in execs:
                lk = rev.get(x["id"], {}).get(t["id"])
                if x["record"].get("state") != "ok":
                    cells[x["id"]] = {"state": "unknown"}
                elif lk is not None:
                    lt = live_by[x["id"]][lk]
                    cells[x["id"]] = {"state": "matched", "key": lt["key"], "pnl": lt["pnl"], "est": lt["est"], "entry_price": lt["entry_price"],
                                      "slip": (lt["side"] * (t["entry_price"] - lt["entry_price"]) / t["entry_price"]) if t.get("entry_price") and lt.get("entry_price") else None,
                                      "diff": (lt["pnl"] - t["pnl"] * (x["config"].get("qty_scale") or 0)) if lt.get("pnl") is not None and x["config"].get("qty_scale") else None}
                else:
                    cells[x["id"]] = why_missed(x["record"], t, ACCOUNT)
            rows.append({**{k: t.get(k) for k in ("id", "symbol", "side", "entry_time", "exit_time", "exit_reason", "leverage", "pnl", "roe",
                                                   "entry_price", "exit_price", "qty", "margin", "fees", "funding", "strategy_id", "timeframe",
                                                   "lock_roe", "stop_initial", "stop_price", "liq_price")},
                         "key": f"paper:{t['id']}", "reason_ko": EXIT_KO.get(t["exit_reason"], t["exit_reason"]), "win": (t["pnl"] or 0) > 0,
                         **setting(t["symbol"], t["entry_time"]), "live": cells})
        out["paper"] = {"state": "ok", "rows": rows, "n": len(ptrades)}
    else:
        out["paper"] = {k: paper.get(k) for k in ("state", "reason_ko", "reason", "path")} if paper.get("state") != "ok" else \
            {"state": "missing", "reason_ko": "페이퍼 DB에 이 계좌의 기록이 아직 없어요"}
    for x in execs:
        r = x["record"]
        if r.get("state") != "ok":
            out[x["id"]] = {k: r.get(k) for k in ("state", "reason_ko", "reason", "path")}
            continue
        rows = []
        for t in reversed((r.get("trades") or [])[-TRADES_KEEP:]):
            pid = pairs[x["id"]].get(str(t["key"]))
            pt = by_pid.get(pid) if pid is not None else None
            reason = t["exit_reason"]
            if reason == "PAPER" and pt:
                reason = pt["exit_reason"] or reason
            scale = x["config"].get("qty_scale")
            slip = (t["side"] * (pt["entry_price"] - t["entry_price"]) / pt["entry_price"]) if pt and pt.get("entry_price") and t.get("entry_price") else None
            rows.append({**{k: t.get(k) for k in ("key", "symbol", "side", "qty", "leverage", "entry_price", "pnl", "roe", "margin", "est",
                                                   "commission", "funding", "slippage", "stop_initial", "stop_final", "exit_raw")},
                         "entry_time": t["entry_ts"], "exit_time": t["exit_ts"], "exit_reason": reason, "reason_ko": EXIT_KO.get(reason, reason),
                         "win": (t["pnl"] or 0) > 0, "locked": bool(t.get("stop_final") and t.get("entry_price") and (t["stop_final"] - t["entry_price"]) * t["side"] > 0),
                         "paper": ({k: pt.get(k) for k in ("id", "entry_time", "exit_time", "entry_price", "exit_price", "pnl", "roe", "exit_reason", "lock_roe",
                                                             "strategy_id", "timeframe")} if pt else None),
                         "paper_scaled": pt["pnl"] * scale if pt and pt.get("pnl") is not None and scale else None,
                         "diff": (t["pnl"] - pt["pnl"] * scale) if pt and pt.get("pnl") is not None and t.get("pnl") is not None and scale else None,
                         "slip_vs_paper": slip, "gap_ms": abs(pt["entry_time"] - t["paper_time"]) if pt and t.get("paper_time") is not None else None,
                         "strategy_id": pt.get("strategy_id") if pt else None, "timeframe": pt.get("timeframe") if pt else None,
                         **(setting(pt["symbol"], pt["entry_time"]) if pt else {"member": None, "order": None, "setting": None})})
        out[x["id"]] = {"state": "ok", "rows": rows, "n": len(r.get("trades") or []), "qty_scale": x["config"].get("qty_scale")}
    return {"now_ms": now, "accts": out, "match_ms": MATCH_MS, "combo_state": combo.get("state"), "members_n": len(members)}


def why_missed(rec: dict, pt: dict, account: str) -> dict:
    """Why a paper trade has no live trade on this executor, from its own records (never a guess)."""
    since = rec.get("since_ms")
    if since and pt.get("entry_time") is not None and pt["entry_time"] < since:
        return {"state": "before", "why_ko": "실행기가 시작하기 전의 페이퍼 거래예요"}
    key = f"{account}|{pt.get('symbol')}|{pt.get('entry_time')}"
    pos = rec.get("position")
    if pos and pos.get("key") == key:
        return {"state": "open", "why_ko": "실거래 쪽은 아직 닫는 중이에요"}
    found = (rec.get("why") or {}).get(key) or {}
    for kind, ko in WHY:
        if kind in found:
            return {"state": "missed", "why_kind": kind, "why_ko": ko, "why_text": found[kind].get("text")}
    last = None
    for hh in rec.get("halts") or []:
        if hh.get("ts") is not None and pt.get("entry_time") is not None and hh["ts"] <= pt["entry_time"]:
            last = hh.get("action")
    if last == "halt":
        return {"state": "missed", "why_kind": "halted", "why_ko": "그때 실행기가 멈춰 있었어요"}
    return {"state": "missed", "why_kind": None, "why_ko": "실행기 기록에 이유가 없어요 (그때 실행기가 꺼져 있었을 수 있어요)"}


# ---------------------------------------------------------------- 성적
def rolling(trades: list, n: int) -> list:
    """[[exit ms, win share of the last n closed trades]] from the n-th trade on (fewer than n: no point)."""
    out, wins = [], []
    for t in trades:
        wins.append(1 if (_f(t.get("pnl")) or 0) > 0 else 0)
        if len(wins) >= n:
            out.append([_i(t.get("exit_time") if t.get("exit_time") is not None else t.get("exit_ts")), sum(wins[-n:]) / n])
    return thin(out)


def breakdown(trades: list, key) -> list:
    by: dict = {}
    for t in trades:
        k = key(t)
        if k is None:
            continue
        b = by.setdefault(k, [])
        b.append(t.get("pnl"))
    return sorted(({"key": k, **stats(v)} for k, v in by.items()), key=lambda r: (-r["trades"], str(r["key"])))


def perf_of(trades: list, t_entry: str = "entry_time", t_exit: str = "exit_time") -> dict:
    """The record of one account: totals, the rolling 20 / 40 win share, and per strategy, coin, timeframe, side and KST hour
    of the entry (표본 적음 flags from stats: under 20, then under 40)."""
    norm = [{**t, "exit_time": t.get(t_exit), "entry_time": t.get(t_entry)} for t in trades]
    hour = lambda t: ((int(t["entry_time"]) + KST_MS) // HOUR) % 24 if t.get("entry_time") is not None else None   # noqa: E731
    return {"stats": stats(t.get("pnl") for t in norm), "roll20": rolling(norm, 20), "roll40": rolling(norm, 40),
            "by_strategy": breakdown(norm, lambda t: t.get("strategy_id")), "by_coin": breakdown(norm, lambda t: t.get("symbol")),
            "by_tf": breakdown(norm, lambda t: t.get("timeframe")), "by_side": breakdown(norm, lambda t: t.get("side")),
            "by_hour": breakdown(norm, hour), "curve": thin([[t["exit_time"], c] for t, c in zip(norm, _cum(norm))])}


def _cum(trades: list) -> list:
    c, out = 0.0, []
    for t in trades:
        c += _f(t.get("pnl")) or 0.0
        out.append(c)
    return out


def perf(p: dict, now: int) -> dict:
    """GET /api/v4/livebots/perf."""
    _configs, _follows, paper, execs = sources(p, now)
    out = {}
    a = (paper.get("accounts") or {}).get(ACCOUNT) if paper.get("state") == "ok" else None
    if a is not None:
        out["paper"] = {"state": "ok", **perf_of(a.get("trades") or [])}
    else:
        out["paper"] = {k: paper.get(k) for k in ("state", "reason_ko", "reason", "path")} if paper.get("state") != "ok" else {"state": "missing", "reason_ko": "기록 없음"}
    for x in execs:
        r = x["record"]
        if r.get("state") != "ok":
            out[x["id"]] = {k: r.get(k) for k in ("state", "reason_ko", "reason", "path")}
            continue
        ptrades = (a or {}).get("trades") or []
        m = match(ptrades, r.get("trades") or [])
        by_pid = {t["id"]: t for t in ptrades}
        live = []
        for t in r.get("trades") or []:                    # the live trade takes its paper partner's strategy and timeframe
            pt = by_pid.get(m.get(str(t["key"])))
            live.append({**t, "strategy_id": pt.get("strategy_id") if pt else None, "timeframe": pt.get("timeframe") if pt else None})
        out[x["id"]] = {"state": "ok", **perf_of(live, "entry_ts", "exit_ts")}
    flip = (paper.get("accounts") or {}).get(FLIP_ACCOUNT) if paper.get("state") == "ok" else None
    return {"now_ms": now, "accts": out, "refs": REFS, "checkpoint": checkpoint((a or {}).get("trades") or []) if a else None,
            "flip": {"state": "ok", **perf_of(flip.get("trades") or [])} if flip and flip.get("known") else None, "small": list(SMALL)}


# ---------------------------------------------------------------- 안전
def safety(p: dict, now: int, keep: int = 500) -> dict:
    """GET /api/v4/livebots/safety: per executor its halt, the limits its config really has, the kill file, the light now and
    every light_red / light_unread event, the halt log and its WARN / CRITICAL log (newest ``keep``)."""
    _configs, _follows, paper, execs = sources(p, now)
    out = []
    for x in execs:
        r, cfg = x["record"], x["config"]
        lights, log = [], []
        if r.get("state") == "ok":
            try:
                conn = open_ro(r["path"])
                try:
                    lights = [{"id": _i(i), "ts": _i(t), "kind": k, "kind_ko": KIND_KO.get(k, k), "text": txt, "data": _j(dd)} for i, t, k, txt, dd in conn.execute(
                        "SELECT id, ts, kind, text, data FROM events WHERE kind IN ('light_red', 'light_unread') ORDER BY id DESC LIMIT 200")]
                    log = [{"id": _i(i), "ts": _i(t), "level": lv, "level_ko": LEVEL_KO.get(lv, lv), "kind": k, "kind_ko": KIND_KO.get(k, k), "text": txt}
                           for i, t, lv, k, txt in conn.execute("SELECT id, ts, level, kind, text FROM events WHERE level IN ('WARN', 'CRITICAL') "
                                                                "AND kind != 'retry' ORDER BY id DESC LIMIT ?", (keep,))]
                finally:
                    conn.close()
            except (OSError, sqlite3.Error) as exc:
                r = {**r, "log_error": _err(r["path"], exc)}
        out.append({"id": x["id"], "name_ko": x["name_ko"], "config": cfg, "light": x["light"], "notes": x["notes"],
                    "record": {k: r.get(k) for k in ("state", "reason_ko", "reason", "path", "as_of_ms", "stale", "mode", "halted", "halt_reason",
                                                     "halted_ts", "consecutive_losses", "since_ms", "halts", "retry_24h", "log_error")},
                    "lights": lights, "log": log})
    return {"now_ms": now, "execs": out, "paper": {k: paper.get(k) for k in ("state", "reason_ko", "path", "as_of_ms", "stale")}}


# ---------------------------------------------------------------- 그림자
def shadows(p: dict, now: int) -> dict:
    """GET /api/v4/livebots/shadows: the shadow paper bots (other settings of the same combined bot, same database shape,
    account COMBO@mix) next to the live paper bot, each counted from the same start (the later of the two first records)."""
    more = paths_more()
    main = read_paper(p["paper"], [ACCOUNT], now)
    ma = (main.get("accounts") or {}).get(ACCOUNT) if main.get("state") == "ok" else None
    out = []
    for sid, fname, ko in SHADOWS:
        path = os.path.join(more["shadow_dir"], fname)
        sh = read_paper(path, [ACCOUNT], now)
        row = {"id": sid, "name_ko": ko, "path": path, "state": sh.get("state"), "reason_ko": sh.get("reason_ko"), "reason": sh.get("reason")}
        sa = (sh.get("accounts") or {}).get(ACCOUNT) if sh.get("state") == "ok" else None
        if sh.get("state") == "ok" and not (sa and sa.get("known")):
            row.update(state="missing", reason_ko="이 그림자 DB에 아직 계좌 기록이 없어요")
        elif sa:
            start = max(x for x in (sa.get("since_ms"), (ma or {}).get("since_ms"), 0) if x is not None)
            st_ = [t for t in sa.get("trades") or [] if (t.get("entry_time") or 0) >= start]
            mt = [t for t in (ma or {}).get("trades") or [] if (t.get("entry_time") or 0) >= start] if ma else None
            row.update(since_ms=start, as_of_ms=sh.get("as_of_ms"), stale=sh.get("stale"), name_cfg=sh.get("name_ko"),
                       stats=stats(t["pnl"] for t in st_), curve=thin([[t["exit_time"], c] for t, c in zip(st_, _cum(st_))]),
                       main=({"stats": stats(t["pnl"] for t in mt), "curve": thin([[t["exit_time"], c] for t, c in zip(mt, _cum(mt))])} if mt is not None else None),
                       position=sa.get("position"))
        out.append(row)
    return {"now_ms": now, "shadows": out, "main": {"state": main.get("state"), "reason_ko": main.get("reason_ko"),
            "since_ms": (ma or {}).get("since_ms"), "stats": (ma or {}).get("stats")},
            "start_ko": "sudo systemctl start paperbot-combo-shadow@b paperbot-combo-shadow@nocut paperbot-combo-shadow@ac32",
            "dir": more["shadow_dir"]}


# ---------------------------------------------------------------- 설정
def settings(p: dict, now: int) -> dict:
    """GET /api/v4/livebots/settings: the combined bot's fixed rules and its settings grouped by strategy (from the config it
    runs), each executor's light threshold and risk limits."""
    combo = read_combo(p["paper"], paths_more()["combo_config"])
    configs = {ex: read_config(p[ck]) for ex, _ko, _dk, ck in EXECS}
    execs = [{"id": ex, "name_ko": ko, "config": configs[ex]} for ex, ko, _dk, _ck in EXECS]
    if combo.get("state") != "ok":
        return {"now_ms": now, "combo": {k: combo.get(k) for k in ("state", "reason_ko", "reason", "path")}, "execs": execs}
    members = members_of(combo)
    groups: dict = {}
    for m in members:
        groups.setdefault(m["strategy"], []).append(m)
    return {"now_ms": now, "combo": {"state": "ok", "source": combo["source"], "path": combo["path"], "since_ms": combo.get("since_ms")},
            "rules": rules_of(combo), "execs": execs, "n_settings": len(members), "n_strategies": len(groups),
            "groups": [{"strategy": k, "n": len(v), "tfs": sorted({m["tf"] for m in v}), "members": v}
                       for k, v in sorted(groups.items(), key=lambda kv: (-len(kv[1]), str(kv[0])))]}


def _cached(key: str, make) -> dict:
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit is not None and now - hit[0] < TTL_S:
            return hit[1]
    out = make()
    with _lock:
        _cache[key] = (now, out)
        if len(_cache) > 64:
            for k in sorted(_cache, key=lambda k: _cache[k][0])[:16]:
                _cache.pop(k, None)
    return out


def register(app, ctx) -> dict:
    from ..app import json_finite

    def key(name: str, p: dict) -> str:
        return name + ":" + json.dumps([p, paths_more()], sort_keys=True)

    @app.get("/api/v4/livebots")
    def get_livebots():
        """실거래 요약 (터미널): the two live executors and the paper account they follow (read-only, 5 s cache, honest states)."""
        p = paths()
        return _cached(key("sum", p), lambda: json_finite(build(p)))

    @app.get("/api/v4/livebots/trades")
    def get_livebots_trades():
        """실거래 › 거래: the three accounts' closed trades with their settings, reasons, costs and partners (5 s cache)."""
        p = paths()
        return _cached(key("trades", p), lambda: json_finite(trade_rows(p, int(time.time() * 1000))))

    @app.get("/api/v4/livebots/signals")
    def get_livebots_signals():
        """실거래 › 신호: the combined bot's signals of the last 7 KST days and what became of each (5 s cache)."""
        p = paths()
        return _cached(key("signals", p), lambda: json_finite(read_signals(p["paper"], ACCOUNT, int(time.time() * 1000))))

    @app.get("/api/v4/livebots/perf")
    def get_livebots_perf():
        """실거래 › 성적: rolling win shares and the breakdowns of each account (5 s cache)."""
        p = paths()
        return _cached(key("perf", p), lambda: json_finite(perf(p, int(time.time() * 1000))))

    return {"routes": ["/api/v4/livebots", "/api/v4/livebots/trades", "/api/v4/livebots/signals", "/api/v4/livebots/perf"], "paths": paths}
