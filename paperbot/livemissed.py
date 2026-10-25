"""못 탄 신호 성적 (owners 10/19 "못 탄 신호들은 어땠나", then "진입을 안 했는데 좋은 놓친 신호 분석 같은 거"): what every signal
the paper bot did NOT take would have done, and the paper trades the live executors did not follow. View only: no rule of
the bots changes here (the one-position rule, the research filters, the pauses: the owners decide those, start guide 13장).

    missed_pass(src, conn, now_ms)           one pass, from the 1-minute watcher (paperbot/livecheck.py run_watch)
    morning_line(conn, trades, pos, w0, w1)  the one quiet line of the morning check ("어제 못 탄 신호 n개(가상): …")
    python -m paperbot.livemissed show       the owners' summary per group and the newest rows, in Korean
    python -m paperbot.livemissed run        one pass now (the watcher does it every minute)

The groups ("왜 못 탔나", column ``grp``; COMBO@mix, the paper account both executors follow, the last 7 KST days):
  one       한 번에 하나: outcomes SKIPPED "in position" / "lower score than entered signal" / "early exit this minute"
            (engine.py _handle_entries, combo.py ComboEngine.step), with the trade that had the place ("그때 탄 거래")
  research  연구 조건 밖: signal_log FILTERED by the setting's own rules (combo.py _research_signal / _research_entry /
            _allowed): "연구 조건 밖: <tags>" (signal-time filter), "연구 조건 밖: 신호봉 크기" (disp), "끈 구간: <buckets>"
            (the switched-off buckets, in words), "조건 밖" (``when``), "연구 조건을 못 읽음"
  nobreak   돌파 없음: a break setting whose break never came within its bar (_breaks): simulated as "돌파를 안 기다리고 바로
            탔다면" (entered at the signal like an entry "now" setting), and labelled so
  pause     쉬는 시간: FILTERED by the KST weekend or ±N minutes around a US macro release (_submit_due)
  late      늦음·재시작: outcomes REJECTED "late" (the reference price too old when submitted: a restart's catch-up); a break
            confirmed too late ("돌파 확인이 늦음") cannot be rebuilt (its break minute is not recorded): rebuild_failed
  exec      실행기가 안 따라감: a paper trade an executor did not follow (signal light red, halted, late, refused, not
            running …): no simulation, the paper trade's own result, per executor (the 실거래 › 거래 tab's own matching and
            reasons: dash/more/livebots.py read_exec, match, why_missed)
Other refusals (the engine's "stop rule" / "sizing") are not listed: the simulation would refuse them the same way.

The second paper bot (owners 10-23, docs/vwap-bot-ko.md: 'VWAP 개선판', livecheck.Sources.paper2_db, once its file is there,
followed by an executor or not): its own rows, column ``paper`` = its database's name ('vwap'; NULL or '' = the main bot,
as every row before), keys "vwap#<the usual key>" (its executors' rows "exec:<executor>|COMBO@mix#vwap|…"), simulated
with ITS config (its combo_run record: 2 ATR stop, its ladder, 30x, margin 40 %, the 96-bar hold limit: TIME exits in its
words, data ``time_ko``). Its groups (VWAP_GROUPS): one / pause / late / exec as above, and
  gate      VWAP 조건이 막음: signal_log FILTERED by its entry gates (combo.py _entry_block, paperbot/entrygates.py):
            "<N>시간 추세 반대: …" (gate_vote), "변동성 높음: …" (gate_vol), and a gate that could not read its bars
            ("… 추세 판단을 못 읽음(진입 안 함)" / "변동성 판단에 쓸 …봉을 못 읽음", gate_unread: simulated like the others: the
            signal itself is known, only the gate's answer is not); what the gates read stays in the row's detail
            (``gates``, row_out).
read_rows(conn, since, paper=None) is the main bot's rows only (every screen as it was); paper='vwap' its rows. The
pass's work (MAX_SIMS, BUDGET_S) is shared: the main bot first, each at least half when both have work.

How a signal is simulated (paperbot/livesim.py, the paper bot's own ComboEngine of the config it runs, its taker fee, the
rule bot's 1m bars, the account's wallet at that moment as if it were flat; funding not included: livesim FUNDING_NOTE_KO):
- an outcome (one, late): the Signal exactly as the engine received it (outcomes.data), from the outcome's minute;
- a signal_log row (research, nobreak, pause): the Signal rebuilt the way combo.py make_signal builds it (the row's ATR,
  reference price and time, side after invert, score; the setting found in the config by its label
  ``name@tf#order~spec_tag`` as combo.resolve_members makes it; its research stop ``rstop`` and, for a swing stop, the
  window's lowest low / highest high from the rule bot's 1m bars of the n x tf minutes before the entry minute, the bars
  the paper bot's research data steps on), entered at the minute that opens at the signal bar's close. A row that cannot
  be rebuilt exactly (the setting no longer in the config, the swing window's bars missing, no ATR) is stored as
  ``rebuild_failed`` with the reason: never a guess. No other filter is applied (the question is "if it had gone in").

Stored in livecheck.db, table ``missed`` (one row per signal, key member|coin|signal bar close; per executor and paper trade
for ``exec``): state open (simulated again until it closes), closed (never again), no_data (no 1m bar at its entry minute),
refused (the engine would not have entered it either), rebuild_failed, error (the reason; tried again later). An older
livecheck.db (the first version, without ``grp`` / ``executor``) is altered in place (PRAGMA table_info first): its rows are
group ``one``. ``missed_meta`` holds the last pass.
Bounded: at most MAX_SIMS simulations (and rebuild attempts) and BUDGET_S seconds a pass, the oldest unfinished first (said
on stderr when capped); the executor rows are lookups. A pass never raises and never undoes the watcher's other passes
(a savepoint): an error is stored with its row or in ``missed_meta``.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import sys
import time
from typing import Callable, Optional

MIN = 60_000
H1 = 3_600_000
DAY = 86_400_000
KST_MS = 9 * H1
ACCOUNT = "COMBO@mix"
DEFAULT_DB = "/var/lib/paperbot/livecheck.db"
PAPER_DB = "/var/lib/paperbot/combo/live-ac.db"
RULE_DB = "/var/lib/paperbot/paper3.db"
COMBO_CONFIG = "/etc/paperbot/combo.json"
REASONS = {"in position": "held", "lower score than entered signal": "lost", "early exit this minute": "early"}
GROUPS = ("one", "research", "nobreak", "pause", "late", "exec")
SIM_GROUPS = GROUPS[:-1]
# the second paper bot (owners 10-23, 'VWAP 개선판', docs/vwap-bot-ko.md): its rows (column ``paper`` = its database's name,
# keys "vwap#…") use the groups that fit it and one of its own: ``gate``, the signals its entry gates kept out (the 4h vote
# against the side, the volatility gate, a gate that could not read its bars). GROUPS (the main bot's screen) stays as it is.
GATE = "gate"
VWAP_GROUPS = ("one", "pause", "late", GATE, "exec")
ALL_GROUPS = GROUPS + (GATE,)
GROUP_KO = {"one": "한 번에 하나", "research": "연구 조건 밖", "nobreak": "돌파 없음", "pause": "쉬는 시간",
            "late": "늦음·재시작", "exec": "실행기가 안 따라감", GATE: "VWAP 조건이 막음"}
GROUP_SHORT = {"one": "한 번에 하나", "research": "연구 조건", "nobreak": "돌파 없음", "pause": "쉬는 시간", "late": "늦음",
               "exec": "실행기 안 따라감", GATE: "VWAP 조건"}
# the one-line read: who blocked, and what "blocking" was
GROUP_SUBJ = {"one": "한 번에 하나 규칙이 막은 신호", "research": "연구 조건이 막은 신호", "nobreak": "돌파를 안 기다리고 바로 탔다면",
              "pause": "쉬는 시간(주말·미국 지표)이 막은 신호", "late": "늦어서 못 탄 신호", "exec": "실행기가 안 따라간 페이퍼 거래",
              GATE: "VWAP 조건(4시간 추세·변동성)이 막은 신호"}
GROUP_VERB = {"one": "막은 게", "research": "막은 게", "nobreak": "돌파를 기다린 게", "pause": "쉰 게", "late": "안 탄 게",
              "exec": "안 따라간 게", GATE: "막은 게"}
HOW_KO = {"one": "따로 탔다면 (가상)", "research": "그때 들어갔다면 (가상 · 계좌가 비어 있었다고 치고)",
          "nobreak": "돌파를 안 기다리고 바로 탔다면 (가상)", "pause": "그때 들어갔다면 (가상 · 계좌가 비어 있었다고 치고)",
          "late": "제때 들어갔다면 (가상 · 계좌가 비어 있었다고 치고)", "exec": "페이퍼 거래의 결과 (실행기는 안 탐 · 가상 아님)",
          GATE: "조건을 안 보고 그때 들어갔다면 (가상 · 계좌가 비어 있었다고 치고)"}
WINDOW_DAYS = 7                     # the KST days a pass looks back
MAX_SIMS = 60                       # simulations (and rebuild attempts) per pass
BUDGET_S = 10.0                     # seconds of simulation per pass
RETRY_MS = 10 * MIN                 # an error row is tried again after this
RETRY_SLOW_MS = 60 * MIN            # ... a no_data or rebuild_failed row after this (the bars rarely come later)
OPEN_DAYS = 14                      # a virtual trade is followed this long from its entry (livesim.MAX_MINUTES)
KEEP_DAYS = 90                      # rows older than this are deleted
FOLLOW_MS = 3 * MIN                 # a paper entry older than this must have been followed (livecheck FOLLOW_MS)
SMALL = 20                          # fewer closed trades than this: 표본 적음
KO_SIDE = {1: "롱", -1: "숏"}
KO_TF = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
KO_EXIT = {"SL": "손절", "LOCK": "계단 익절", "LIQ": "강제청산", "HALT": "멈춤 청산", "MANUAL": "수동 청산", "REV": "빠른 청산",
           "TP": "익절", "END": "끝", "JUDGE": "감독 청산(추세 뒤집힘)", "TIME": "감독 청산(시간 정리)"}
# TIME of a bot with a hold limit and no trend supervisor ('VWAP 개선판'): its rows keep the words in their data
# (``time_ko``, livepapers.time_exit_ko of the bot's own config) and row_out uses them
KO_STATE = {"open": "진행 중", "closed": "끝남", "no_data": "1분봉 없음", "refused": "진입 안 됨", "rebuild_failed": "다시 못 만듦",
            "error": "못 읽음"}
KO_WHY = {"held": "포지션 있음 (한 번에 하나)", "lost": "같은 분 다른 신호에 밀림", "early": "빠른 청산 분 (갈아타지 않음)",
          "filter": "연구 조건 밖", "disp": "신호봉 크기", "off": "끈 구간", "when": "조건 밖", "unread": "조건을 못 읽음",
          "config": "설정이 바뀜", "nobreak": "돌파 없음", "weekend": "주말", "macro": "경제 발표 앞뒤", "late": "늦음",
          "late_break": "돌파 확인이 늦음", "usopen": "나스닥 개장 뒤", "chase": "추격 진입 막기",
          "chase_unread": "추격 판단 못 함", "own_busy": "실거래가 자기 포지션(거래소 기준) 중",
          "gate_vote": "4시간 추세 반대", "gate_vol": "변동성 높음", "gate_unread": "조건 판단에 쓸 봉을 못 읽음"}
NOTE_KO = ("가상 결과예요: 페이퍼 봇과 같은 엔진·같은 1분봉으로 계산했지만 실제 체결이 아니에요. 1포지션 규칙은 그대로이고, 이건 "
           "바꾸자는 뜻이 아니라 보기만 하는 거예요. 거래가 적을 때는 대부분 운이에요.")
FILTER_NOTE_KO = ("필터는 5년 시험에서 평균적으로 나쁜 자리를 걸렀기 때문에 넣은 거예요. 이긴 것만 보면 아쉬움만 커져요: 진 것과 같이 봐야 "
                  "해요. 규칙을 바꿀지는 두 분이 정하고, 바꾸려면 13장 순서(백테스트 → 그림자 → 채택)를 따라요.")
SCHEMA_TABLES = """
CREATE TABLE IF NOT EXISTS missed (
    key TEXT PRIMARY KEY,
    t INTEGER NOT NULL,
    step_ts INTEGER NOT NULL,
    member TEXT,
    strategy TEXT,
    tf TEXT,
    symbol TEXT NOT NULL,
    side INTEGER NOT NULL,
    why_kind TEXT NOT NULL,
    why TEXT NOT NULL,
    state TEXT NOT NULL,
    entry_ts INTEGER,
    entry_price REAL,
    stop REAL,
    leverage INTEGER,
    margin REAL,
    exit_ts INTEGER,
    exit_price REAL,
    reason TEXT,
    roe_net REAL,
    pnl REAL,
    best_roe REAL,
    last_ts INTEGER,
    wallet REAL,
    taken_id INTEGER,
    taken_state TEXT,
    taken_roe REAL,
    taken_pnl REAL,
    taken TEXT,
    error TEXT,
    sims INTEGER NOT NULL DEFAULT 0,
    first_ts INTEGER NOT NULL,
    updated_ts INTEGER NOT NULL,
    signal TEXT NOT NULL,
    detail TEXT,
    data TEXT,
    path TEXT,
    grp TEXT NOT NULL DEFAULT 'one',
    executor TEXT,
    paper TEXT
);
CREATE TABLE IF NOT EXISTS missed_meta (
    k TEXT PRIMARY KEY,
    ts INTEGER NOT NULL,
    data TEXT NOT NULL
)
"""
SCHEMA_INDEXES = ("CREATE INDEX IF NOT EXISTS missed_t ON missed (t)",
                  "CREATE INDEX IF NOT EXISTS missed_grp ON missed (grp, t)")
# columns the first version did not have; ``paper`` (owners 10-23): NULL or '' = the main paper bot (every row before),
# else the second paper bot's database name ('vwap')
ADDED_COLS = (("grp", "TEXT NOT NULL DEFAULT 'one'"), ("executor", "TEXT"), ("paper", "TEXT"))
SCHEMA = SCHEMA_TABLES + ";\n" + ";\n".join(SCHEMA_INDEXES) + ";\n"
COLS = ("key", "t", "step_ts", "member", "strategy", "tf", "symbol", "side", "why_kind", "why", "state", "entry_ts", "entry_price",
        "stop", "leverage", "margin", "exit_ts", "exit_price", "reason", "roe_net", "pnl", "best_roe", "last_ts", "wallet",
        "taken_id", "taken_state", "taken_roe", "taken_pnl", "taken", "error", "sims", "first_ts", "updated_ts", "signal",
        "detail", "data", "path", "grp", "executor", "paper")
# what the screen and ``show`` read (the detail too, for what a VWAP row's gates read; the signal and path are not)
READ_COLS = tuple(c for c in COLS if c not in ("signal", "path"))
LIGHT_COLS = ("key", "t", "step_ts", "state", "updated_ts", "taken_state", "taken_roe", "why_kind", "grp", "paper")
FINAL = ("closed", "refused")       # never simulated again


class MissedError(RuntimeError):
    """A reason a signal could not be simulated (Korean, stored with the row)."""


# ====================================================================== small helpers
def coin(symbol) -> str:
    return str(symbol or "").replace("USDT", "")


def kst(ms: int, fmt: str = "%m/%d %H:%M") -> str:
    return time.strftime(fmt, time.gmtime(int(ms) / 1000 + 9 * 3600))


def window_start(now_ms: int, days: int = WINDOW_DAYS) -> int:
    """00:00 KST of the day ``days - 1`` KST days before today (today and the six days before it)."""
    kd = (int(now_ms) + KST_MS) // DAY
    return (kd - (days - 1)) * DAY - KST_MS


def _f(x) -> Optional[float]:
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _j(raw) -> dict:
    try:
        d = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except (TypeError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _stderr(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def _pct(x: Optional[float], d: int = 1) -> str:
    if x is None:
        return "-"
    s = f"{abs(x) * 100:.{d}f}%"
    return ("+" if x > 0 and float(s[:-1]) else "−" if x < 0 and float(s[:-1]) else "") + s


def _dur(ms: Optional[int]) -> str:
    if ms is None:
        return "-"
    m = max(0, int(ms) // MIN)
    if m < 60:
        return f"{m}분"
    if m < 1440:
        return f"{m // 60}시간 {m % 60}분" if m % 60 else f"{m // 60}시간"
    return f"{m // 1440}일 {(m % 1440) // 60}시간"


def classify(why: str, gates: bool = False) -> Optional[tuple]:
    """(group, kind) of a FILTERED signal_log row from the bot's own why (combo.py _allowed, _submit_due, _research_signal,
    _research_entry, _breaks), None for anything else. ``gates`` (the second paper bot, owners 10-23: combo.py
    _entry_block with paperbot/entrygates.py): "<N>시간 추세 반대: …" (gate_vote), "변동성 높음: …" (gate_vol), "<N>시간 추세
    판단을 못 읽음(진입 안 함)…" / "변동성 판단에 쓸 …봉을 못 읽음(진입 안 함)…" (gate_unread: the signal itself is known
    and is simulated like the others; only what the gate would have said is not)."""
    w = str(why or "")
    if gates:
        if re.match(r"^\S+ 추세 반대", w):
            return GATE, "gate_vote"
        if w.startswith("변동성 높음"):
            return GATE, "gate_vol"
        if re.match(r"^\S+ 추세 판단을 못 읽음", w) or w.startswith("변동성 판단에 쓸"):
            return GATE, "gate_unread"
    if w.startswith("연구 조건 밖: 신호봉 크기"):
        return "research", "disp"
    if w.startswith("연구 조건 밖"):
        return "research", "filter"
    if w.startswith("끈 구간"):
        return "research", "off"
    if w.startswith("조건 밖"):
        return "research", "when"
    if w.startswith("연구 조건을 못 읽음"):
        return "research", "unread"
    if w.startswith("설정에 없는 연구 매매법"):
        return "research", "config"
    if w.startswith("돌파 없음"):
        return "nobreak", "nobreak"
    if w.startswith("주말"):
        return "pause", "weekend"
    if w.startswith("경제 발표"):
        return "pause", "macro"
    if w.startswith("나스닥 개장"):
        return "pause", "usopen"
    if w.startswith("추격 진입 막기"):
        return "research", "chase"
    if w.startswith("추격 판단"):
        return "research", "chase_unread"
    if w.startswith("돌파 확인이 늦음"):
        return "late", "late_break"
    return None


def _why_words(why: str) -> str:
    """The bot's why with its bucket codes in words (the 신호 tab's own wording, dash/more/livebots.py why_words)."""
    try:
        from .dash.more.livebots import why_words
        return why_words(why) or str(why or "")
    except Exception:  # noqa: BLE001  the words only
        return str(why or "")


# ====================================================================== the paper bot's records (read-only)
SIGLOG_SQL = ("SELECT id, bar_close, timeframe, strategy, symbol, side, atr, ref_price, ref_time, delay_ms, status, data FROM signal_log "
              "WHERE timeframe IN ('15m', '30m', '1h', '4h') AND bar_close >= ? AND status = 'FILTERED' ORDER BY bar_close, id")


def read_paper(pc, since: int, trades_since: Optional[int] = None, gates: bool = False) -> dict:
    """One snapshot of the paper bot's database: the candidates since ``since`` (outcomes SKIPPED for the one-position rule
    and REJECTED late, signal_log FILTERED rows), its closed trades (``trades_since``: those that closed from then on and
    the last one before, for the wallet; None: all), its open position and last marks, its ``combo_run`` record.
    ``gates``: the second paper bot's (classify: its gate group; what its gates read stays in the row's detail)."""
    q = "SELECT id, symbol, entry_time, exit_time, exit_reason, pnl, roe, equity_after, data FROM trades WHERE account_id = ? "
    pc.execute("BEGIN")
    try:
        outs = pc.execute("SELECT id, step_ts, status, reason, symbol, data FROM outcomes WHERE account_id = ? AND step_ts >= ? "
                          "AND (status = 'SKIPPED' OR (status = 'REJECTED' AND reason = 'late')) ORDER BY step_ts, id",
                          (ACCOUNT, int(since))).fetchall()
        try:
            cur = pc.execute(SIGLOG_SQL, (int(since),))
            scols = [c[0] for c in cur.description]
            srows = [dict(zip(scols, r)) for r in cur.fetchall()]
        except sqlite3.OperationalError:            # a database without signal_log (an older run): no such rows
            srows = []
        if trades_since is None:
            trows = pc.execute(q + "ORDER BY exit_time, id", (ACCOUNT,)).fetchall()
        else:
            trows = pc.execute(q + "AND exit_time < ? ORDER BY exit_time DESC, id DESC LIMIT 1", (ACCOUNT, int(trades_since))).fetchall()
            trows += pc.execute(q + "AND exit_time >= ? ORDER BY exit_time, id", (ACCOUNT, int(trades_since))).fetchall()
        st = pc.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
        run = pc.execute("SELECT data FROM state WHERE k = 'combo_run'").fetchone()
    finally:
        pc.execute("ROLLBACK")
    cands = []
    for oid, step, status, reason, sym, data in outs:
        grp, kind = ("one", REASONS.get(reason)) if status == "SKIPPED" else ("late", "late")
        if kind is None:
            continue
        d = _j(data)
        sig = d.get("signal") if isinstance(d.get("signal"), dict) else None
        if not sig or sig.get("ts") is None:
            cands.append({"key": f"outcome:{oid}", "bad": True, "grp": grp, "src": "outcome", "step_ts": int(step), "symbol": sym,
                          "kind": kind, "t": int(step), "member": None, "strategy": None, "tf": None, "side": 0, "signal": {},
                          "detail": {}, "why_raw": ""})
            continue
        meta = sig.get("meta") if isinstance(sig.get("meta"), dict) else {}
        t = int(sig["ts"]) + 1
        member = meta.get("member") or sig.get("strategy_id")
        det = d.get("detail") if isinstance(d.get("detail"), dict) else {}
        cands.append({"key": f"{member}|{sym}|{t}", "bad": False, "grp": grp, "src": "outcome", "step_ts": int(step), "symbol": sym,
                      "kind": kind, "t": t, "member": member, "strategy": sig.get("strategy_id"), "tf": sig.get("timeframe"),
                      "side": int(sig.get("side") or 0), "signal": sig, "detail": det, "why_raw": ""})
    for r in srows:
        d = _j(r.get("data"))
        gk = classify(d.get("why"), gates)
        if gk is None:
            continue
        bc = int(r["bar_close"])
        cands.append({"key": f"{r['strategy']}|{r['symbol']}|{bc}", "bad": False, "grp": gk[0], "src": "siglog", "step_ts": bc,
                      "symbol": r["symbol"], "kind": gk[1], "t": bc, "member": r["strategy"],
                      "strategy": d.get("strategy") or str(r["strategy"]).split("@")[0], "tf": r["timeframe"],
                      "side": int(r.get("side") or 0), "signal": {"siglog": {k: r[k] for k in scols}},
                      "detail": {"gates": d["gates"]} if gates and isinstance(d.get("gates"), dict) else {},
                      "why_raw": str(d.get("why") or "")})
    cands.sort(key=lambda c: (c["step_ts"], c["key"]))
    trades = []
    for tid, sym, et, xt, why, pnl, roe, eq, data in trows:
        d = _j(data)
        trades.append({"id": int(tid), "symbol": sym, "entry_time": int(et), "exit_time": int(xt), "reason": why, "pnl": _f(pnl),
                       "roe": _f(roe), "equity_after": _f(eq), "side": int(d.get("side") or 0), "strategy": d.get("strategy_id"),
                       "tf": d.get("timeframe"), "entry_price": _f(d.get("entry_price")), "exit_price": _f(d.get("exit_price")),
                       "leverage": d.get("leverage"), "margin": _f(d.get("margin"))})
    eng = ((_j(st[0]).get("engines") or {}).get(ACCOUNT) or {}) if st else {}
    pos = eng.get("position") if isinstance(eng.get("position"), dict) else None
    marks = eng.get("last_mark") if isinstance(eng.get("last_mark"), dict) else {}
    run_d = _j(run[0]) if run else {}
    return {"cands": cands, "trades": trades, "pos": pos, "marks": marks, "run": run_d}


def config_of(paper: dict, config_file: str) -> tuple:
    """(config, taker fee, where from): the paper bot's own ``combo_run`` record, else the config file."""
    run = paper.get("run") or {}
    if isinstance(run.get("config"), dict):
        return run["config"], _f(run.get("taker_fee")), "기록"
    try:
        with open(config_file, encoding="utf-8") as fh:
            raw = json.load(fh)
        return (raw if isinstance(raw, dict) else None), None, config_file
    except (OSError, ValueError):
        return None, None, ""


def wallet_at(trades: list, step_ts: int, initial: float, inclusive: bool = False) -> float:
    """The account's wallet after its last trade closed before the minute ``step_ts`` (``inclusive``: at that minute too,
    an early exit closes before the entries), else the initial equity."""
    w = None
    for t in trades:
        if t["exit_time"] < step_ts or (inclusive and t["exit_time"] <= step_ts):
            if t["equity_after"] is not None:
                w = t["equity_after"]
    return float(w if w is not None else initial)


def _pos_roe(pos: dict, marks: dict, rt: float) -> Optional[float]:
    side = int(pos.get("side") or 0)
    entry, lev = _f(pos.get("entry_price")), _f(pos.get("leverage"))
    qty, fund = _f(pos.get("qty")) or 0.0, _f(pos.get("funding_paid")) or 0.0
    mark = _f(marks.get(pos.get("symbol")))
    ff = fund / (qty * entry) if qty and entry else 0.0
    return lev * (side * (mark / entry - 1.0) - rt - ff) if (mark and entry and lev) else None


def _pos_taken(pos: dict, marks: dict, rt: float) -> dict:
    sig = pos.get("signal") if isinstance(pos.get("signal"), dict) else {}
    return {"id": None, "symbol": pos.get("symbol"), "side": int(pos.get("side") or 0), "strategy": sig.get("strategy_id"),
            "tf": sig.get("timeframe"), "state": "open", "roe": _pos_roe(pos, marks, rt), "pnl": None, "reason": None,
            "entry_time": int(pos.get("entry_time") or 0), "exit_time": None}


def _trade_taken(t: dict) -> dict:
    return {"id": t["id"], "symbol": t["symbol"], "side": t["side"], "strategy": t["strategy"], "tf": t["tf"], "state": "closed",
            "roe": t["roe"], "pnl": t["pnl"], "reason": t["reason"], "entry_time": t["entry_time"], "exit_time": t["exit_time"]}


def taken_of(kind: str, step_ts: int, detail: dict, trades: list, pos: Optional[dict], marks: dict, rt: float) -> Optional[dict]:
    """The paper trade that had the place at that moment (group ``one`` only): the open one ("held": entered before the
    minute, closed at or after it, on the held coin), the one entered in that same minute ("lost"), or the one the early
    exit closed then ("early"). Closed trades from the trades table; one still open from the engine's state (its net ROE at
    the last mark, the ladder's formula)."""
    step_ts = int(step_ts)
    if kind == "held":
        sym = (detail or {}).get("held_symbol")
        xs = [t for t in trades if t["entry_time"] < step_ts <= t["exit_time"] and (not sym or t["symbol"] == sym)]
        if xs:
            return _trade_taken(max(xs, key=lambda t: (t["entry_time"], t["id"])))
        if pos and int(pos.get("entry_time") or 0) < step_ts and (not sym or pos.get("symbol") == sym):
            return _pos_taken(pos, marks, rt)
        return None
    if kind == "lost":
        xs = [t for t in trades if t["entry_time"] == step_ts]
        if xs:
            return _trade_taken(xs[0])
        if pos and int(pos.get("entry_time") or 0) == step_ts:
            return _pos_taken(pos, marks, rt)
        return None
    if kind == "early":
        xs = [t for t in trades if t["exit_time"] == step_ts and t["reason"] == "REV"]
        return _trade_taken(xs[-1]) if xs else None
    return None


def why_of(c: dict, taken: Optional[dict]) -> str:
    """Why the signal was not taken, in the owners' words."""
    kind = c["kind"]
    if kind == "held":
        if taken:
            return f"이미 {coin(taken['symbol'])} {KO_SIDE.get(taken['side'], '')} 보유 중".replace("  ", " ")
        sym = (c.get("detail") or {}).get("held_symbol")
        return f"이미 {coin(sym)} 포지션 보유 중" if sym else "이미 포지션 보유 중"
    if kind == "lost":
        if taken:
            return f"같은 분에 {coin(taken['symbol'])} {KO_SIDE.get(taken['side'], '')} 신호가 먼저 들어감"
        return "같은 분에 다른 신호가 먼저 들어감"
    if kind == "early":
        return "그 분에 반대 신호로 빠른 청산 (갈아타지 않음)"
    if kind == "late":
        age = _f((c.get("detail") or {}).get("age_ms"))
        return f"기준 가격이 {age / 1000:.0f}초 지나 진입 안 함 (재시작 따라잡기 등)" if age else "늦어서 진입 안 함"
    if kind == "nobreak":
        return "돌파 없음(신호봉 시간 안에)"
    return _why_words(c.get("why_raw") or "") or KO_WHY.get(kind, kind)


# ====================================================================== rebuilding a signal_log row
def member_map(cfg_raw: dict) -> dict:
    """The config's settings by the label the paper bot gives them (combo.resolve_members, without importing any strategy
    code): research settings ``name@tf#order~spec_tag`` -> (order, RSpec), picks by their id, the others (house stop) by
    ``name@tf`` (their label adds ``~hash`` of custom numbers) -> (order, None)."""
    from . import rmember as RM
    research, plain = {}, {}
    for i, sp in enumerate((cfg_raw or {}).get("members") or [], 1):
        if not isinstance(sp, dict):
            continue
        try:
            r = RM.parse_spec(sp, "")
        except RM.RSpecError:
            continue
        if r is not None:
            research[f"{sp.get('strategy')}@{sp.get('tf')}#{i}~{RM.spec_tag(r)}"] = (i, r)
        elif sp.get("pick"):
            plain[str(sp["pick"])] = (i, None)
        else:
            plain.setdefault(f"{sp.get('strategy')}@{sp.get('tf')}", (i, None))
    return {"research": research, "plain": plain}


def rebuild(row: dict, rig, mm: dict, rc, entry_ts: int) -> tuple:
    """(Signal, None) as combo.py make_signal (and _research_entry for the stop's meta) would have built it from this
    signal_log row, or (None, the reason in Korean) when it cannot be rebuilt exactly."""
    from . import livesim as LS
    from . import rmember as RM
    from .models import Signal
    label = str(row.get("strategy") or "")
    data = _j(row.get("data"))
    tf, sym, side = row.get("timeframe"), row.get("symbol"), int(row.get("side") or 0)
    atr, ref = _f(row.get("atr")), _f(row.get("ref_price"))
    if label in mm["research"]:
        order, research = mm["research"][label]
    elif "#" in label:
        return None, "지금 설정에 없는 연구 매매법이에요 (설정이 바뀌었어요)"
    else:
        hit = mm["plain"].get(label) or mm["plain"].get(label.split("~")[0])
        if hit is None:
            return None, "지금 설정에 없는 매매법이에요 (설정이 바뀌었어요)"
        order, research = hit
    if side not in (1, -1):
        return None, "신호의 방향 기록이 없어요"
    if atr is None or not atr > 0:
        return None, "신호의 ATR 기록이 없어요"
    if tf not in RM.TF_MIN:
        return None, f"봉 {tf}을(를) 몰라요"
    meta = {"stop_dist": rig.cfg.stop_atr * atr, "ref_time": row.get("ref_time"), "delay_ms": row.get("delay_ms"), "account": ACCOUNT,
            "member": label, "member_order": order, "source": data.get("source") or "custom", "score_raw": data.get("score"),
            "ctx": {}}
    if ref is not None:
        meta["ref_price"] = ref
    if research is not None:
        meta.update(research=True, rstop=list(research.stop))
        if research.stop[0] == "swing":
            w = int(research.stop[1]) * RM.TF_MIN[tf]
            if rc is None:
                return None, "스윙 손절 창의 규칙봇 1분봉을 못 읽어요"
            bars = LS.read_bars(rc, sym, int(entry_ts) - w * MIN, int(entry_ts))
            if len(bars) < w:
                return None, f"스윙 손절 창({w}분)의 규칙봇 1분봉이 {w - len(bars)}분 빠져 있어요"
            meta["rswing"] = {"lo": float(min(b.low for b in bars)), "hi": float(max(b.high for b in bars))}
    score = _f(data.get("score"))
    return Signal(ts=int(row["bar_close"]) - 1, symbol=sym, timeframe=tf, strategy_id=data.get("strategy") or label.split("@")[0],
                  side=side, stop_price=0.0, tier="best", score=rig.cfg.no_score if score is None else score, atr=atr,
                  meta=meta), None


# ====================================================================== the pass
def _schema(conn) -> None:
    """The tables, one statement at a time (``executescript`` would commit whatever the watcher has pending); an older
    table (the first version) gets the new columns (PRAGMA table_info first: safe to run every pass)."""
    for stmt in SCHEMA_TABLES.split(";"):
        if stmt.strip():
            conn.execute(stmt)
    have = {r[1] for r in conn.execute("PRAGMA table_info(missed)")}
    for col, decl in ADDED_COLS:
        if col not in have:
            conn.execute(f"ALTER TABLE missed ADD COLUMN {col} {decl}")
    for stmt in SCHEMA_INDEXES:
        conn.execute(stmt)


def _meta_put(conn, now_ms: int, data: dict) -> None:
    conn.execute("INSERT OR REPLACE INTO missed_meta VALUES (?,?,?)", ("pass", int(now_ms), json.dumps(data, ensure_ascii=False)))


def _first_put(conn, now_ms: int, since: int) -> None:
    """The start of what the table covers (the first pass's window), kept once."""
    conn.execute("INSERT OR IGNORE INTO missed_meta VALUES (?,?,?)", ("first", int(now_ms), json.dumps({"since": int(since)})))


def _existing(conn, since: int) -> dict:
    """{key: the few columns that decide the work} of the rows from ``since`` on (no JSON read)."""
    cur = conn.execute(f"SELECT {', '.join(LIGHT_COLS)} FROM missed WHERE t >= ?", (int(since),))
    return {r[0]: dict(zip(LIGHT_COLS, r)) for r in cur.fetchall()}


def _full(conn, key: str) -> Optional[dict]:
    cur = conn.execute("SELECT * FROM missed WHERE key = ?", (key,))
    r = cur.fetchone()
    return None if r is None else dict(zip([c[0] for c in cur.description], r))


def _upsert(conn, row: dict) -> None:
    conn.execute(f"INSERT OR REPLACE INTO missed ({', '.join(COLS)}) VALUES ({', '.join('?' * len(COLS))})",
                 tuple(row.get(c) for c in COLS))


def _base(c: dict, old: Optional[dict], now_ms: int) -> dict:
    """A row's identity, kept from its first sight."""
    row = dict(old) if old else {}
    row.update(key=c["key"], t=c["t"], step_ts=c["step_ts"], member=c["member"], strategy=c["strategy"], tf=c["tf"],
               symbol=c["symbol"], side=c["side"], why_kind=c["kind"], grp=c["grp"], executor=c.get("executor"),
               paper=c.get("paper"),
               signal=json.dumps(c["signal"], default=str, ensure_ascii=False),
               detail=json.dumps({**(c["detail"] or {}), "why_raw": c.get("why_raw") or ""}, default=str, ensure_ascii=False))
    row.setdefault("first_ts", int(now_ms))
    row.setdefault("sims", 0)
    return row


def _with_taken(row: dict, taken: Optional[dict]) -> dict:
    row.update(taken_id=taken.get("id") if taken else None, taken_state=taken.get("state") if taken else None,
               taken_roe=taken.get("roe") if taken else None, taken_pnl=taken.get("pnl") if taken else None,
               taken=json.dumps(taken, ensure_ascii=False) if taken else None)
    return row


def _apply(row: dict, r: dict, rig_notes: list) -> dict:
    """The simulation's answer into the row (livesim.simulate's shape)."""
    from .livesim import thin_path
    ent, ex = r.get("entry") or {}, r.get("exit") or {}
    roe = ex.get("roe") if r["state"] == "closed" else (r.get("latest") or {}).get("roe")
    row.update(state=r["state"], entry_ts=ent.get("ts"), entry_price=ent.get("price"), stop=ent.get("stop"),
               leverage=ent.get("leverage"), margin=ent.get("margin"), exit_ts=ex.get("ts"), exit_price=ex.get("price"),
               reason=ex.get("reason"), roe_net=roe, pnl=ex.get("pnl"), best_roe=r.get("best_roe"), last_ts=r.get("last_ts"),
               error=None,
               data=json.dumps({"stop_now": r.get("stop"), "lock": r.get("lock"), "why": r.get("why") or "", "reject": r.get("reject"),
                                "stop_rule": ent.get("stop_rule"), "funding": r.get("funding"), "minutes": r.get("minutes"),
                                "notes": rig_notes}, default=str, ensure_ascii=False),
               path=json.dumps(thin_path(r.get("path") or []), default=str))
    return row


def missed_pass(src, conn, now_ms: int, cap: int = MAX_SIMS, budget_s: float = BUDGET_S,
                log: Optional[Callable[[str], None]] = None) -> dict:
    """One pass of 못 탄 신호 성적 for the 1-minute watcher (module docstring). ``src``: livecheck.Sources (its paper_db,
    rule_db, combo_config, executors); ``conn``: livecheck.db open for writing (the watcher's own connection; committed
    here). Returns {new, resim, closed, errors, left, capped, taken, exec, rows, elapsed_s} (``error`` when the pass itself
    failed). Never raises."""
    say = log or _stderr
    res = {"new": 0, "resim": 0, "closed": 0, "errors": 0, "left": 0, "capped": False, "taken": 0, "exec": 0, "rows": 0}
    t0 = time.monotonic()
    try:
        _schema(conn)
        # a savepoint: a failure here undoes this pass only, never the watcher's other passes on the same connection
        conn.execute("SAVEPOINT missed_pass")
        try:
            _pass(src, conn, int(now_ms), int(cap), float(budget_s), res, t0)
        except BaseException:
            conn.execute("ROLLBACK TO missed_pass")
            conn.execute("RELEASE missed_pass")
            raise
        conn.execute("RELEASE missed_pass")
        conn.commit()
    except Exception as exc:  # noqa: BLE001  the watcher's other passes go on
        res["error"] = f"{type(exc).__name__}: {exc}"[:300]
        try:
            _schema(conn)
            _meta_put(conn, now_ms, {"state": "error", "error": res["error"], "now": int(now_ms)})
            conn.commit()
        except Exception:  # noqa: BLE001
            pass
        say(f"[못 탄 신호] 이번 계산 실패: {res['error']}")
    res["elapsed_s"] = round(time.monotonic() - t0, 3)
    if res.get("capped"):
        say(f"[못 탄 신호] 이번에 {res['new'] + res['resim']}개만 계산했어요(한 번에 {cap}개·{budget_s:g}초까지), "
            f"남은 {res['left']}개는 다음 감시 때 (오래된 것부터)")
    return res


def _cand_of(row: dict) -> dict:
    """A stored row back into a candidate (re-simulation of a row its source no longer lists)."""
    sig = _j(row.get("signal"))
    det = _j(row.get("detail"))
    return {"key": row["key"], "bad": not sig, "grp": row.get("grp") or "one", "src": "siglog" if "siglog" in sig else "outcome",
            "step_ts": int(row["step_ts"]), "symbol": row["symbol"], "kind": row["why_kind"], "t": int(row["t"]),
            "member": row["member"], "strategy": row["strategy"], "tf": row["tf"], "side": int(row["side"]), "signal": sig,
            "detail": {k: v for k, v in det.items() if k != "why_raw"}, "why_raw": det.get("why_raw") or "",
            "paper": row.get("paper") or None}


def _due(row: dict, now_ms: int, since: int) -> bool:
    """A stored row worked on again: open (followed OPEN_DAYS), an error (after RETRY_MS), no_data / rebuild_failed
    (after RETRY_SLOW_MS, inside the window). closed and refused never."""
    st = row["state"]
    if st == "open":
        return int(row["step_ts"]) >= now_ms - OPEN_DAYS * DAY
    if st == "error":
        return int(row["t"]) >= since and int(row["updated_ts"]) <= now_ms - RETRY_MS
    if st in ("no_data", "rebuild_failed"):
        return int(row["t"]) >= since and int(row["updated_ts"]) <= now_ms - RETRY_SLOW_MS
    return False


def _sim_one(c: dict, row: dict, rig, rig_err, rc, mm, src) -> None:
    """Simulate one candidate into its row (an error is stored with the row)."""
    from . import livesim as LS
    try:
        if c.get("bad"):
            raise MissedError("페이퍼 봇 기록의 신호를 못 읽음")
        if rig is None:
            raise MissedError(rig_err)
        if rc is None:
            raise MissedError(f"규칙봇 1분봉 파일을 못 읽음 ({getattr(src, 'rule_db', '')})")
        if c["kind"] == "late_break":
            row.update(state="rebuild_failed", error=None, data=json.dumps({"why": "돌파 확인 시각이 기록에 없어요 (재시작 따라잡기): "
                                                                                   "언제 들어갔을지 모름"}, ensure_ascii=False))
            return
        if c["src"] == "outcome":
            sig = LS.signal_of(c["signal"])
        else:
            sig, why = rebuild(c["signal"].get("siglog") or {}, rig, mm, rc, c["step_ts"])
            if sig is None:
                row.update(state="rebuild_failed", error=None, data=json.dumps({"why": why}, ensure_ascii=False))
                return
        _apply(row, LS.simulate_db(rig, sig, rc, c["step_ts"], wallet=row["wallet"]), rig.notes)
    except Exception as exc:  # noqa: BLE001  stored with the row, tried again later
        row["state"] = "error"
        row["error"] = str(exc)[:300] if isinstance(exc, MissedError) else f"{type(exc).__name__}: {exc}"[:300]


def paper_tag(path: str) -> str:
    """The second paper bot's name in the table: its database's name without the extension ('vwap')."""
    return os.path.splitext(os.path.basename(str(path or "")))[0]


def paper2_of(src) -> Optional[str]:
    """The second paper bot's database (``src.paper2_db``, livecheck.paper2_default) when it is there and is not the
    main one; None otherwise (then the pass is what it always was)."""
    from . import livepapers as LP
    p2 = getattr(src, "paper2_db", None) or ""
    if not p2 or not os.path.exists(p2) or LP.same(p2, getattr(src, "paper_db", "") or ""):
        return None
    return p2


def _config2_file() -> str:
    """The second paper bot's config file when its database has no run record (the live site's default)."""
    try:
        from .dash.more.livebots import ENV_MORE
        var, default = ENV_MORE["combo2_config"]
    except Exception:  # noqa: BLE001
        var, default = "PAPERBOT_LIVE_COMBO2_CONFIG", "/etc/paperbot/combo-vwap.json"
    return os.environ.get(var) or default


def _prep(src, conn, now_ms: int, since: int, path: str, tag: Optional[str], config_file: str) -> Optional[dict]:
    """One paper bot's work of a pass: its snapshot (read_paper), its engine rules (its own combo_run config), its rows
    already stored, its jobs (the oldest unfinished first); ``tag``: the second paper bot's name (its keys "tag#…", its
    rows' ``paper``), None for the main one. None when its database cannot be read."""
    from . import livecheck as LC
    from . import livepapers as LP
    from . import livesim as LS
    pc = LC.open_ro(path)
    if pc is None:
        return None
    look = since - OPEN_DAYS * DAY                 # the rows still worked on: open ones are followed OPEN_DAYS
    try:
        paper = read_paper(pc, since, trades_since=look, gates=tag is not None)
    finally:
        pc.close()
    cfg_raw, fee, cfg_src = config_of(paper, config_file)
    rig, rig_err = None, None
    if cfg_raw is None:
        rig_err = "페이퍼 봇 설정을 못 읽음 (기록에도 설정 파일에도 없음)"
    else:
        try:
            rig = LS.rig_of(cfg_raw, taker_fee=fee)
        except Exception as exc:  # noqa: BLE001  every row says so
            rig_err = f"페이퍼 봇 설정으로 엔진을 못 만듦: {type(exc).__name__}: {exc}"[:300]
    if tag is not None:
        for c in paper["cands"]:
            c["key"], c["paper"] = f"{tag}#{c['key']}", tag
    time_ko = LP.time_exit_ko(cfg_raw) if tag is not None else None
    have = {k: r for k, r in _existing(conn, look).items() if (r.get("paper") or None) == tag}
    cands = {c["key"]: c for c in paper["cands"]}
    jobs = [(c["step_ts"], "new", c["key"]) for c in paper["cands"] if c["key"] not in have]
    jobs += [(int(r["step_ts"]), "resim", k) for k, r in have.items() if r["grp"] != "exec" and _due(r, now_ms, since)]
    jobs.sort()
    return {"path": path, "tag": tag, "paper": paper, "cfg": cfg_raw, "cfg_src": cfg_src, "rig": rig, "rig_err": rig_err,
            "mm": member_map(cfg_raw or {}), "look": look, "have": have, "cands": cands, "jobs": jobs,
            "time_ko": time_ko if time_ko and time_ko != KO_EXIT["TIME"] else None,
            "initial": rig.initial if rig is not None else (_f((cfg_raw or {}).get("initial_equity")) or 1000.0),
            "rt": rig.settings.round_trip_cost if rig is not None else 0.0014}


def _run(w: dict, src, conn, now_ms: int, cap: int, deadline: float, res: dict, sub: dict) -> None:
    """Simulate ``w``'s jobs, at most ``cap`` and until ``deadline`` (time.monotonic()); counts into ``res`` (the pass)
    and ``sub`` (this paper bot)."""
    from . import livecheck as LC
    trades, pos, marks = w["paper"]["trades"], w["paper"]["pos"], w["paper"]["marks"]
    rc = LC.open_ro(getattr(src, "rule_db", ""))
    try:
        for i, (_t, kind, key) in enumerate(w["jobs"]):
            if i >= cap or time.monotonic() > deadline:
                left = len(w["jobs"]) - i
                res["capped"], res["left"] = True, res["left"] + left
                sub["capped"], sub["left"] = True, left
                break
            old = _full(conn, key) if key in w["have"] else None
            c = w["cands"].get(key) or _cand_of(old)
            row = _base(c, old, now_ms)
            taken = taken_of(c["kind"], c["step_ts"], c["detail"], trades, pos, marks, w["rt"]) if c["grp"] == "one" else None
            _with_taken(row, taken)
            row["why"] = why_of(c, taken)
            if row.get("wallet") is None:
                row["wallet"] = wallet_at(trades, c["step_ts"], w["initial"], inclusive=c["kind"] == "early")
            row["sims"] = int(row.get("sims") or 0) + 1
            row["updated_ts"] = now_ms
            _sim_one(c, row, w["rig"], w["rig_err"], rc, w["mm"], src)
            if w["time_ko"]:                         # this bot's TIME words with the row (row_out)
                row["data"] = json.dumps({**_j(row.get("data")), "time_ko": w["time_ko"]}, default=str, ensure_ascii=False)
            res["errors"] += int(row["state"] == "error")
            _upsert(conn, row)
            for d in (res, sub):
                d["new" if kind == "new" else "resim"] += 1
                d["closed"] += int(row["state"] == "closed")
    finally:
        if rc is not None:
            rc.close()


def _taken_pass(w: dict, conn, since: int, res: dict) -> None:
    """The trade that had the place (group one), while it is still open (no simulation: a lookup), of ``w``'s rows."""
    trades, pos, marks = w["paper"]["trades"], w["paper"]["pos"], w["paper"]["marks"]
    for key, light in _existing(conn, w["look"]).items():
        if (light.get("paper") or None) != w["tag"]:
            continue
        if light["grp"] != "one" or light["taken_state"] == "closed" or (light["taken_state"] is None and int(light["t"]) < since):
            continue
        row = _full(conn, key)
        c = _cand_of(row)
        taken = taken_of(row["why_kind"], int(row["step_ts"]), c["detail"], trades, pos, marks, w["rt"])
        if (taken or {}).get("state") != row["taken_state"] or (taken and taken.get("roe") != row["taken_roe"]):
            row = _with_taken(row, taken)
            row["why"] = why_of(c, taken)
            _upsert(conn, row)
            res["taken"] += 1


def _pass(src, conn, now_ms: int, cap: int, budget_s: float, res: dict, t0: float) -> None:
    since = window_start(now_ms)
    main = _prep(src, conn, now_ms, since, getattr(src, "paper_db", ""), None, getattr(src, "combo_config", COMBO_CONFIG))
    if main is None:
        _meta_put(conn, now_ms, {"state": "no_paper", "now": now_ms, "paper_db": getattr(src, "paper_db", "")})
        return
    _first_put(conn, now_ms, since)
    # the second paper bot (owners 10-23, 'VWAP 개선판'): its own rows, simulated with its own config. The pass's work is
    # shared, the main bot first: each gets half of it at least, and what one does not need goes to the other
    p2 = paper2_of(src)
    second = _prep(src, conn, now_ms, since, p2, paper_tag(p2), _config2_file()) if p2 else None
    if second is not None:
        conn.execute("INSERT OR IGNORE INTO missed_meta VALUES (?,?,?)",
                     (f"first:{second['tag']}", int(now_ms), json.dumps({"since": int(since)})))
    need2 = len(second["jobs"]) if second is not None else 0
    cap1 = cap - min(need2, cap // 2)
    sub1 = {"new": 0, "resim": 0, "closed": 0, "capped": False, "left": 0}
    _run(main, src, conn, now_ms, cap1, t0 + budget_s * (cap1 / cap if cap else 1.0), res, sub1)
    sub2 = None
    if second is not None:
        sub2 = {"new": 0, "resim": 0, "closed": 0, "capped": False, "left": 0}
        _run(second, src, conn, now_ms, cap - sub1["new"] - sub1["resim"], t0 + budget_s, res, sub2)
    for w in (main, second):
        if w is not None:
            _taken_pass(w, conn, since, res)
    p = main["paper"]
    exec_states = _exec_pass(src, conn, now_ms, since, p["trades"], p["pos"], p["marks"], main["rt"], res)
    conn.execute("DELETE FROM missed WHERE t < ?", (now_ms - KEEP_DAYS * DAY,))
    res["rows"] = int(conn.execute("SELECT COUNT(*) FROM missed").fetchone()[0])
    if second is not None:
        res[second["tag"]] = {**sub2, "config": second["cfg_src"], "rig_error": second["rig_err"]}
    rig = main["rig"]
    _meta_put(conn, now_ms, {"state": "ok", "now": now_ms, "since": since, "config": main["cfg_src"], "rig_error": main["rig_err"],
                             "funding": "excluded", "notes": rig.notes if rig is not None else [], "executors": exec_states,
                             **{k: res[k] for k in ("new", "resim", "closed", "errors", "left", "capped", "taken", "exec", "rows")},
                             **({"papers": {second["tag"]: res[second["tag"]]}} if second is not None else {}),
                             "elapsed_s": round(time.monotonic() - t0, 3)})


# ---------------------------------------------------------------- group exec: the paper trades an executor did not follow
def _exec_paper(trades: list, pos: Optional[dict], marks: dict, rt: float, since: int, now_ms: int) -> list:
    """One paper bot's trades entered in the window more than FOLLOW_MS ago, its open position as one more (id None)."""
    paper = [t for t in trades if since <= t["entry_time"] <= now_ms - FOLLOW_MS]
    if pos and since <= int(pos.get("entry_time") or 0) <= now_ms - FOLLOW_MS:
        sig = pos.get("signal") if isinstance(pos.get("signal"), dict) else {}
        paper.append({"id": None, "symbol": pos.get("symbol"), "side": int(pos.get("side") or 0), "entry_time": int(pos["entry_time"]),
                      "exit_time": None, "reason": None, "pnl": None, "roe": _pos_roe(pos, marks, rt), "strategy": sig.get("strategy_id"),
                      "tf": sig.get("timeframe"), "entry_price": _f(pos.get("entry_price")), "exit_price": None,
                      "leverage": pos.get("leverage"), "margin": _f(pos.get("margin_initial"))})
    return paper


def _exec_pass(src, conn, now_ms: int, since: int, trades: list, pos: Optional[dict], marks: dict, rt: float, res: dict) -> dict:
    """Per executor (src.executors, else livecheck.load_executors: the configs as plain JSON) the paper trades entered in
    the window more than FOLLOW_MS ago that it has no trade for, with its own reason (the 거래 tab's matching and words:
    livebots.match, why_missed; an executor that started after the entry is not asked). The paper result, no simulation.
    Owners 10-19 (docs/live15-mexc-ko.md): each executor only against the paper bot it followed at the entry
    (paperbot/livepapers.py from its own start records; another bot's rows carry that bot's database in their key).
    Returns {executor: its record's state}."""
    from . import livecheck as LC
    from . import livepapers as LP
    from .dash.more import livebots as LB
    infos = list(getattr(src, "executors", None) or LC.load_executors())
    main = getattr(src, "paper_db", None) or PAPER_DB
    paper = _exec_paper(trades, pos, marks, rt, since, now_ms)
    others: dict = {}
    time_kos: dict = {}

    def paper_of(path: str) -> list:
        """Another paper bot's window (read once a pass, read-only)."""
        k = LP.norm(path)
        if k not in others:
            pc = LC.open_ro(path)
            got: list = []
            if pc is not None:
                try:
                    d = read_paper(pc, since, since)
                    got = _exec_paper(d["trades"], d["pos"], d["marks"], rt, since, now_ms)
                    tko = LP.time_exit_ko((d.get("run") or {}).get("config"))
                    time_kos[k] = tko if tko != KO_EXIT["TIME"] else None
                except sqlite3.Error:
                    got = []
                finally:
                    pc.close()
            others[k] = got
        return others[k]
    states = {}
    for ex in infos:
        rec = LB.read_exec(ex.db, now_ms)
        states[ex.name] = rec.get("state")
        if rec.get("state") != "ok":
            continue                                   # not readable: nothing is said about it (the 거래 tab says why)
        xc = LC.open_ro(ex.db)                         # its own start records (which paper database each start followed)
        try:
            starts = LP.starts_of(xc) if xc is not None else []
        finally:
            if xc is not None:
                xc.close()
        segs = LP.segments(starts, main)
        for path in LP.paths_of(segs):
            is_main = LP.same(path, main)
            mine = [t for t in (paper if is_main else paper_of(path)) if LP.followed_at(segs, path, t["entry_time"])]
            lts = [lt for lt in rec.get("trades") or [] if LP.same(LP.paper_at(segs, lt.get("entry_ts")), path)]
            pairs = LB.match([t for t in mine if t["id"] is not None], lts)
            followed = set(pairs.values())
            for t in mine:
                key = f"exec:{ex.name}|{LC.card_key(ACCOUNT, t['symbol'], t['entry_time'], None if is_main else path)}"
                w = None if (t["id"] is not None and t["id"] in followed) else LB.why_missed(rec, t, ACCOUNT)
                if w is None or w.get("state") != "missed":
                    conn.execute("DELETE FROM missed WHERE key = ?", (key,))    # followed (or it was not running yet)
                    continue
                old = _full(conn, key)
                if old and old["state"] == "closed":
                    continue
                row = dict(old) if old else {"first_ts": now_ms, "sims": 0}
                closed = t["exit_time"] is not None
                row.update(key=key, t=t["entry_time"], step_ts=t["entry_time"], member=None, strategy=t["strategy"], tf=t["tf"],
                           symbol=t["symbol"], side=t["side"], why_kind=w.get("why_kind") or "unknown",
                           why=f"{getattr(ex, 'label', ex.name)}: {w.get('why_ko') or '이유 기록 없음'}", grp="exec", executor=ex.name,
                           state="closed" if closed else "open", entry_ts=t["entry_time"], entry_price=t.get("entry_price"),
                           stop=None, leverage=t.get("leverage"), margin=t.get("margin"), exit_ts=t["exit_time"],
                           exit_price=t.get("exit_price"), reason=t["reason"], roe_net=t["roe"], pnl=t["pnl"], best_roe=None,
                           last_ts=None, wallet=None, error=None, updated_ts=now_ms,
                           signal=json.dumps({"paper": t["id"]} if is_main else {"paper": t["id"], "paper_db": path}),
                           detail=json.dumps({"why_text": w.get("why_text")}, ensure_ascii=False),
                           data=json.dumps({"why": ""} if is_main or not time_kos.get(LP.norm(path))
                                           else {"why": "", "time_ko": time_kos[LP.norm(path)]}, ensure_ascii=False),
                           path=None, paper=None if is_main else paper_tag(path))
                _with_taken(row, None)
                _upsert(conn, row)
                res["exec"] += 1
    return states


# ====================================================================== reading it back (the CLI, the dashboard, the morning)
def row_out(d: dict) -> dict:
    """A stored row as the screen and the CLI use it: numbers, the group, the trade that had the place, hold time, win."""
    data = _j(d.get("data"))
    taken = _j(d.get("taken")) or None
    st = d.get("state")
    grp = d.get("grp") or "one"
    entry, exit_ts, last = d.get("entry_ts"), d.get("exit_ts"), d.get("last_ts")
    hold = (int(exit_ts) - int(entry)) if (st == "closed" and entry is not None and exit_ts is not None) else \
        (int(last) + MIN - int(entry)) if (st == "open" and entry is not None and last is not None) else None
    tko = data.get("time_ko")                           # the second paper bot's TIME words ('VWAP 개선판': 보유 한도 청산)

    def reason_ko(r):
        return tko if (r == "TIME" and tko) else KO_EXIT.get(r, r)
    if taken is not None:
        taken["reason_ko"] = reason_ko(taken.get("reason"))
    gates = _j(d.get("detail")).get("gates") if d.get("detail") else None
    return {"key": d.get("key"), "t": d.get("t"), "step_ts": d.get("step_ts"), "member": d.get("member"), "strategy": d.get("strategy"),
            "tf": d.get("tf"), "symbol": d.get("symbol"), "side": d.get("side"), "grp": grp, "grp_ko": GROUP_KO.get(grp, grp),
            "how_ko": HOW_KO.get(grp, ""), "executor": d.get("executor"), "why_kind": d.get("why_kind"),
            "why_kind_ko": KO_WHY.get(d.get("why_kind"), d.get("why_kind")), "why": d.get("why"), "state": st,
            "state_ko": KO_STATE.get(st, st), "entry_ts": entry, "entry_price": _f(d.get("entry_price")), "stop": _f(d.get("stop")),
            "leverage": d.get("leverage"), "margin": _f(d.get("margin")), "exit_ts": exit_ts, "exit_price": _f(d.get("exit_price")),
            "reason": d.get("reason"), "reason_ko": reason_ko(d.get("reason")), "roe": _f(d.get("roe_net")),
            "pnl": _f(d.get("pnl")), "best_roe": _f(d.get("best_roe")), "last_ts": last, "hold_ms": hold,
            "win": (st == "closed" and (_f(d.get("pnl")) or 0) > 0), "lock": _f(data.get("lock")), "stop_now": _f(data.get("stop_now")),
            "stop_rule": data.get("stop_rule") or "", "note": data.get("why") or "", "error": d.get("error") or "",
            "taken": taken, "updated_ts": d.get("updated_ts"), "sims": d.get("sims"),
            # owners 10-23: whose row ('vwap': the second paper bot; None: the main one) and what its gates read
            "paper": d.get("paper") or None, "gates": gates if isinstance(gates, dict) else None}


def read_rows(conn, since: int, limit: Optional[int] = None, paper: Optional[str] = None) -> list:
    """The rows of signals from ``since`` on, newest first (``row_out``; the stored signal and path are not read). An older
    table without ``grp`` / ``executor`` (before the watcher's first pass of this version) reads as group ``one``.
    ``paper``: None = the main paper bot's rows only (``paper`` NULL or '': every row before the second bot, and every
    screen as it was); 'vwap' = the second paper bot's rows (owners 10-23)."""
    have = {r[1] for r in conn.execute("PRAGMA table_info(missed)")}
    sel = [c if c in have else ("'one' AS grp" if c == "grp" else f"NULL AS {c}") for c in READ_COLS]
    if "paper" not in have:
        where, args = ("1 = 1", ()) if paper is None else ("0 = 1", ())
    elif paper is None:
        where, args = "(paper IS NULL OR paper = '')", ()
    else:
        where, args = "paper = ?", (str(paper),)
    q = f"SELECT {', '.join(sel)} FROM missed WHERE t >= ? AND {where} ORDER BY t DESC, key" + (" LIMIT ?" if limit else "")
    cur = conn.execute(q, (int(since),) + args + ((int(limit),) if limit else ()))
    return [row_out(dict(zip(READ_COLS, r))) for r in cur.fetchall()]


def read_path(conn, key: str) -> list:
    """One row's thinned per-minute path ({t, c, roe, stop, lock}, the exit last)."""
    r = conn.execute("SELECT path FROM missed WHERE key = ?", (key,)).fetchone()
    try:
        return json.loads(r[0]) if r and r[0] else []
    except ValueError:
        return []


def block_of(rows: list, open_n: Optional[int] = None) -> dict:
    """Counts of a set of rows (or paper trades): n, closed, wins (pnl > 0, the executors' rule) and losses, open, the other
    states, win rate, the sum and mean of net ROE over the closed ones, small sample under SMALL closed."""
    closed = [r for r in rows if r.get("state", "closed") == "closed"]
    roes = [x for x in (_f(r.get("roe")) for r in closed) if x is not None]
    w = sum(1 for r in closed if (_f(r.get("pnl")) or 0) > 0)
    out = {"n": len(rows) + (open_n or 0), "closed": len(closed), "wins": w, "losses": len(closed) - w,
           "open": open_n if open_n is not None else sum(1 for r in rows if r.get("state") == "open"),
           "win_rate": w / len(closed) if closed else None, "roe_sum": sum(roes) if roes else 0.0,
           "roe_mean": sum(roes) / len(roes) if roes else None, "small": len(closed) < SMALL}
    out.update({k: sum(1 for r in rows if r.get("state") == k) for k in ("no_data", "refused", "rebuild_failed", "error")})
    out["moments"] = len({(r.get("symbol"), r.get("side"), r.get("step_ts")) for r in rows})
    return out


def read_ko(grp: str, b: dict) -> str:
    """The group's one line in plain words: "연구 조건이 막은 신호: 가상 12승 9패 · 순ROE 합 −31.0% → 이번엔 막은 게 손해를
    줄였어요" (or "… 이익을 놓쳤어요"), and under SMALL closed "· 표본 적음 · 대부분 운"."""
    subj = GROUP_SUBJ.get(grp, grp)
    what = "페이퍼 결과" if grp == "exec" else "가상"
    if not b.get("n"):
        return f"{subj}: 이 기간에 없어요"
    if not b.get("closed"):
        return f"{subj}: 끝난 것이 아직 없어요 (진행 중 {b.get('open', 0)})"
    s = b.get("roe_sum") or 0.0
    tail = ("이번엔 " + GROUP_VERB.get(grp, "막은 게") + (" 손해를 줄였어요" if s < 0 else " 이익을 놓쳤어요")) if s else "이번엔 본전이에요"
    line = f"{subj}: {what} {b['wins']}승 {b['losses']}패 · 순ROE 합 {_pct(s)} → {tail}"
    return line + (" · 표본 적음 · 대부분 운" if b.get("small") else "")


def summary_of(rows: list, trades: list, pos_entry: Optional[int], since: int, groups_: Optional[tuple] = None) -> dict:
    """The cards of the screen: the paper trades actually taken (entered since ``since``: the closed ones, and the open
    position), each group's rows of the same span (``row_out`` shape) with its one-line read, and every simulated group
    together (``all``; the executors' rows are paper results, not in it). ``groups_``: the groups to list (default
    GROUPS, plus ``gate`` when a row has it: the second paper bot's, VWAP_GROUPS)."""
    rs = [r for r in rows if (r.get("t") or 0) >= since]
    tk = [{**t, "state": "closed"} for t in trades if (t.get("entry_time") or 0) >= since]
    taken = block_of(tk, 1 if pos_entry is not None and pos_entry >= since else 0)
    groups = []
    if groups_ is None:
        groups_ = GROUPS + ((GATE,) if any(r.get("grp") == GATE for r in rs) else ())
    for g in groups_:
        b = block_of([r for r in rs if (r.get("grp") or "one") == g])
        groups.append({"id": g, "ko": GROUP_KO[g], "subj": GROUP_SUBJ[g], "how_ko": HOW_KO[g], **b, "read_ko": read_ko(g, b)})
    return {"taken": taken, "groups": groups, "all": block_of([r for r in rs if (r.get("grp") or "one") != "exec"]),
            "small_n": SMALL}


def result_ko(r: dict) -> str:
    st = r["state"]
    if st == "closed":
        return f"{'✅' if r['win'] else '❌'} {_pct(r['roe'])} {r['reason_ko'] or ''}".strip()
    if st == "open":
        return f"진행 중 {_pct(r['roe'])}"
    if st == "no_data":
        return "1분봉 없음"
    if st == "refused":
        return f"진입 안 됨 ({r['note'] or '엔진이 거절'})"
    if st == "rebuild_failed":
        return f"다시 못 만듦 ({r['note'] or '이유 기록 없음'})"
    return f"못 읽음 ({r['error'] or '이유 없음'})"


def taken_ko(t: Optional[dict]) -> str:
    if not t:
        return "그때 탄 거래: 기록 못 찾음"
    head = f"그때 탄 거래: {coin(t.get('symbol'))} {KO_SIDE.get(t.get('side'), '')}"
    if t.get("state") == "open":
        return f"{head} 진행 중 {_pct(t.get('roe'))}" if t.get("roe") is not None else f"{head} 진행 중"
    return f"{head} {_pct(t.get('roe'))}"


def morning_line(conn, trades: list, pos_entry: Optional[int], w0: int, w1: int, paper: Optional[str] = None) -> Optional[str]:
    """The morning check's one quiet line for the checked day [w0, w1) (livecheck.db ``missed``, read as it is; None when
    the day has no such row or the table is not there): "어제 못 탄 신호 n개(가상): 한 번에 하나 a승 b패 · 연구 조건 c승 d패
    · … · 실행기 안 따라감 n번(페이퍼 a승 b패) · 실제로 탄 거래 x승 y패". Only groups with signals; open ones as "진행 n".
    ``paper`` (owners 10-23, the second paper bot's rows: 'vwap'; ``trades`` / ``pos_entry`` its own): its gate group
    first, "VWAP 조건이 막은 신호 어제 n개(가상): a승 b패 · 그 밖에 못 탄 신호 … · 실제로 탄 거래 x승 y패"."""
    if conn is None:
        return None
    try:
        rows = [r for r in read_rows(conn, w0, paper=paper) if (r.get("t") or 0) < w1]
    except sqlite3.Error:
        return None
    if not rows:
        return None
    if paper is not None:
        gate = block_of([r for r in rows if r["grp"] == GATE])
        rest = [r for r in rows if r["grp"] != GATE]
        head = (f"VWAP 조건이 막은 신호 어제 {gate['n']}개(가상): {gate['wins']}승 {gate['losses']}패"
                + (f" 진행 {gate['open']}" if gate["open"] else ""))
        tail = morning_line_parts(rest, trades, pos_entry, w0, w1, groups=tuple(g for g in VWAP_GROUPS if g != GATE))
        return " · ".join([head] + ([f"그 밖에 {' · '.join(tail['parts'])}"] if tail["parts"] else []) + [tail["taken"]])
    out = morning_line_parts(rows, trades, pos_entry, w0, w1)
    return f"어제 못 탄 신호 {out['n']}개(가상): " + " · ".join(out["parts"] + [out["taken"]])


def morning_line_parts(rows: list, trades: list, pos_entry: Optional[int], w0: int, w1: int, groups: tuple = GROUPS) -> dict:
    """The pieces of morning_line: {"n" (simulated signals of the groups), "parts" (a piece per group with rows),
    "taken" (실제로 탄 거래 …)}."""
    parts, n = [], 0
    for g in groups:
        grp = [r for r in rows if r["grp"] == g]
        b = block_of(grp)
        if not b["n"]:
            continue
        more = f" 진행 {b['open']}" if b["open"] else ""
        label = GROUP_SHORT[g]
        if g == "research":                    # 규칙봇 15 has no research setting: its filter there is the chase block
            chase = {r.get("why_kind") for r in grp} & {"chase", "chase_unread"}
            label = ("추격 막기" if all(r.get("why_kind") in ("chase", "chase_unread") for r in grp)
                     else "연구 조건·추격 막기" if chase else label)
        if g == "exec":
            parts.append(f"{label} {b['n']}번(페이퍼 {b['wins']}승 {b['losses']}패{more})")
        else:
            n += b["n"]
            parts.append(f"{label} {b['wins']}승 {b['losses']}패{more}")
    tk = block_of([{**t, "state": "closed"} for t in trades if w0 <= (t.get("entry_time") or 0) < w1],
                  1 if pos_entry is not None and w0 <= pos_entry < w1 else 0)
    return {"n": n, "parts": parts,
            "taken": f"실제로 탄 거래 {tk['wins']}승 {tk['losses']}패" + (f" 진행 {tk['open']}" if tk["open"] else "")}


def show_text(db: str, paper_db: str, now_ms: int, days: Optional[int] = WINDOW_DAYS, limit: int = 30,
              group: Optional[str] = None, paper: Optional[str] = None) -> tuple:
    """(exit code, text) of ``show``. ``paper``: the second paper bot's rows ('vwap'; ``paper_db`` is then its database)."""
    from . import livecheck as LC
    conn = LC.open_ro(db)
    if conn is None:
        return 1, f"{db}가 없어요 (1분 감시가 아직 기록 전)"
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "missed" not in tables:
            return 1, "1분 감시가 아직 못 탄 신호를 계산하기 전이에요 (missed 표가 없음)"
        meta = {k: (ts, _j(d)) for k, ts, d in conn.execute("SELECT k, ts, data FROM missed_meta")} if "missed_meta" in tables else {}
        first = meta.get(f"first:{paper}" if paper else "first") or (0, {})
        since = window_start(now_ms, days) if days else int(first[1].get("since") or 0)
        rows = read_rows(conn, since, paper=paper)
    finally:
        conn.close()
    trades, pos_entry, paper_ok = [], None, False
    pc = LC.open_ro(paper_db)
    if pc is not None:
        try:
            p = read_paper(pc, now_ms, trades_since=since)
            trades, pos_entry, paper_ok = p["trades"], (int(p["pos"]["entry_time"]) if p["pos"] else None), True
        except sqlite3.Error:
            paper_ok = False
        finally:
            pc.close()
    s = summary_of(rows, trades, pos_entry, since)
    last = meta.get("pass")
    span = f"최근 {days}일" if days else "기록 전체"
    lines = [f"못 탄 신호 성적 ({span}, 한국 시간 {kst(since)}부터)" + (f" · 마지막 계산 {kst(last[0])}" if last else "")]
    tk = s["taken"]
    if paper_ok:
        wr = f"{tk['win_rate']:.0%}" if tk["win_rate"] is not None else "-"
        lines.append(f"실제로 탄 거래: {tk['n']}번 · {tk['wins']}승 {tk['losses']}패 (승률 {wr}) · 순ROE 합 {_pct(tk['roe_sum'])}"
                     + (f" · 진행 중 {tk['open']}" if tk["open"] else "") + (" · 표본 적음(20번 미만)" if tk["small"] else ""))
    else:
        lines.append("실제로 탄 거래: 페이퍼 봇 DB를 못 읽음")
    for g in s["groups"]:
        if not g["n"]:
            continue
        other = "".join(f" · {KO_STATE[k]} {g[k]}" for k in ("open", "no_data", "refused", "rebuild_failed", "error") if g[k])
        lines.append(f"- {g['ko']} {g['n']}개{other}: {g['read_ko']}")
    shown = [r for r in rows if not group or r["grp"] == group]
    if shown:
        lines.append("")
    for r in shown[:limit]:
        tail = f" · {taken_ko(r['taken'])}" if r["grp"] == "one" else ""
        lines.append(f"{kst(r['t'])} [{GROUP_SHORT.get(r['grp'], r['grp'])}] {coin(r['symbol'])} {KO_SIDE.get(r['side'], '')} {r['strategy']} "
                     f"{KO_TF.get(r['tf'], r['tf'])} · {r['why']} → {result_ko(r)}"
                     + (f" ({_dur(r['hold_ms'])})" if r["hold_ms"] is not None else "") + tail)
    if len(shown) > limit:
        lines.append(f"… 나머지 {len(shown) - limit}개 (--limit)")
    lines += ["", NOTE_KO, FILTER_NOTE_KO, _funding_note()]
    return 0, "\n".join(lines)


def _funding_note() -> str:
    from .livesim import FUNDING_NOTE_KO
    return FUNDING_NOTE_KO


def _sources(a):
    from . import livecheck as LC
    try:
        with open(a.combo_config, encoding="utf-8") as fh:
            cc = json.load(fh)
    except (OSError, ValueError):
        cc = {}
    return LC.Sources(db=a.db, paper_db=a.paper_db or cc.get("db") or PAPER_DB, rule_db=a.rule_db or cc.get("paper_db") or RULE_DB,
                      combo_config=a.combo_config)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.livemissed", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--db", default=DEFAULT_DB, help="livecheck.db (the watcher's file: table missed)")
        p.add_argument("--paper-db", default=None, help="the paper bot's database (default: combo.json's db)")
        p.add_argument("--rule-db", default=None, help="paper3.db, the rule bot's 1m bars (default: combo.json's paper_db)")
        p.add_argument("--combo-config", default=COMBO_CONFIG)
        p.add_argument("--now", type=int, default=None, help=argparse.SUPPRESS)   # tests: a fixed clock (ms)
    s = sub.add_parser("show", help="the summary per group (실제로 탄 거래 next to each) and the newest rows")
    common(s)
    s.add_argument("--days", type=int, default=WINDOW_DAYS, help="KST days (0: everything recorded)")
    s.add_argument("--limit", type=int, default=30)
    s.add_argument("--group", choices=ALL_GROUPS, default=None, help="rows of one group only (the summary stays whole)")
    s.add_argument("--vwap", action="store_true", help="the second paper bot's rows ('VWAP 개선판', PAPERBOT_LIVE_PAPER2_DB)")
    r = sub.add_parser("run", help="one pass now (the 1-minute watcher does it every minute)")
    common(r)
    a = ap.parse_args(argv)
    now = int(time.time() * 1000) if a.now is None else int(a.now)
    src = _sources(a)
    if a.cmd == "show":
        if getattr(a, "vwap", False):
            code, text = show_text(a.db, src.paper2_db, now, a.days or None, a.limit, a.group, paper=paper_tag(src.paper2_db))
        else:
            code, text = show_text(a.db, src.paper_db, now, a.days or None, a.limit, a.group)
        print(text)
        return code
    from . import livecheck as LC
    conn = LC.open_out(a.db)
    try:
        out = missed_pass(src, conn, now)
    finally:
        conn.close()
    print(json.dumps(out, ensure_ascii=False))
    return 1 if out.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
