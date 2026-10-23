"""실거래 › VWAP 봇 (#/vwap · #/vwperf · #/vwblock; owners 10-23: the second paper bot 'VWAP 개선판', docs/vwap-bot-ko.md, and
the executor that will follow it; "천천히 작업해도 되니까 완벽하게 … 성공 매매법을 위한 연구 부분이나 분석 부분 필요한 것 다
추가해도 돼"). Read-only, three answers:

    GET /api/v4/livebots/vwap      관제: the bot (running: its heartbeat; its first start and its last start ``combo_run``),
                                   who follows it (an executor whose start record names its database: since when, its own
                                   signal light on this bot's trades), its rules (its ``combo_run`` config, in words), the
                                   position (the strategy in the owners' words, entry, stop, lock and next lock, net ROE at the
                                   last mark, held so far and the time left to the 96-bar limit, the gates it passed) with the
                                   follower's own position, every coin now (state ``gates_now``: the 4h vote, the ATR% of the
                                   30m / 1h bar against its 30-day 80 % point, and which side a signal could take), the entry
                                   pauses by its config (now and next), the last 48 hours of its signals (entered, refused
                                   and why, with what the gates read)
    GET /api/v4/livebots/vwperf    성적: the paper account and its coin-flip twin side by side (wallet, change, trades, wins,
                                   average win / loss ROE, the break-even win rate of those averages, profit factor, deepest
                                   drop of the closed-trade equity, the curve), "실력 vs 운", the scale-up / stop checklist of
                                   each follower (its live trades while it followed this bot only), the research's numbers next
                                   to the live ones, the splits (strategy, coin, side, the 4h vote and the ATR% at the entry,
                                   KST session, exit, hold), the trades with what the gates read and the follower's part
    GET /api/v4/livebots/vwblock   막은 신호: its FILTERED signals by reason (4시간 추세 반대 · 변동성 높음 · 주말·발표·나스닥 ·
                                   못 읽음 · 기타) today, 7 days and since its start (always: its own database), and "막지
                                   않았다면": the 1-minute watcher's virtual results of what it did not take (livecheck.db
                                   ``missed``, rows ``paper = 'vwap'``), per reason
    (5 s cache each, as every 실거래 tab)

Which database is 'the VWAP bot' (the site and these screens must agree): the paper bots of livebots.paper_bots (the main
paper bot, PAPERBOT_LIVE_PAPER_DB, and the second one: the paper database an executor follows that is not the main one,
else PAPERBOT_LIVE_PAPER2_DB, default /var/lib/paperbot/combo/vwap.db, once the file is there), and of those the one whose
config (its database's ``combo_run``, else PAPERBOT_LIVE_COMBO2_CONFIG) has an entry gate (``vote_gate`` / ``vol_gate``)
or 'VWAP' in its name; never the file name alone. None (the one-paper world, or the 10-19 −35 % twin): ``state: "off"``
with OFF_KO, and nothing of the rest is read. Its database is opened ``mode=ro`` + ``query_only`` (livebots.open_ro), one
snapshot; the executors through livebots.sources (their own snapshots). Honest states as every live page (CONTRACT §1.6):
``missing`` (수집 전) / ``error`` (못 읽음 + why), never a zero for an unread value; a part without data says so.

The numbers: ratios (0.12 = 12 %), net ROE at the trade's leverage (the paper's ``roe``; a live trade's P&L over its
margin), win = P&L > 0 (the executors' rule, livebots.stats), times UTC ms. "Since its start" = the paper account's first
record (its ``accounts`` row), the bot's own trades only. An executor's numbers on this bot count only the live trades it
entered while following it (livepapers segments, from its start records): its trend-bot trades before the switch never.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
from typing import Any, Optional

from ... import livepapers as LP
from . import livebots as L

ACCOUNT, FLIP = L.ACCOUNT, L.FLIP_ACCOUNT
MIN, HOUR, DAY = 60_000, L.HOUR, L.DAY
KST_MS = L.KST_MS
OFF_KO = "VWAP 개선판 페이퍼 봇이 아직 꺼져 있어요 (docs/vwap-bot-ko.md 5장 B로 켜요)"
FIRST_KO = "VWAP 개선판 페이퍼 봇이 아직 첫 기록 전이에요 (켜고 1~2분 뒤 생겨요)"
NO_ACCOUNT_KO = "VWAP 개선판 기록에 페이퍼 계좌가 아직 없어요 (첫 기록 전)"
NO_FOLLOWER_KO = "아직 따라가는 실행기 없음 (페이퍼만)"
READ_KO = "VWAP 개선판 페이퍼 기록을 읽지 못했어요"
HB_STALE_MS = L.PAPER_STALE_MS          # the bot saves every stepped minute
PIC_STALE_MS = 40 * MIN                 # the picture is redrawn two minutes after every 30-minute close
SIG_SPAN_MS = 48 * HOUR                 # 최근 신호
SIG_KEEP = 300
TRADES_KEEP = 300
BLOCK_RECENT = 40                       # the newest filtered signals listed on 막은 신호
VIRTUAL_ROWS = 8                        # the newest rows per reason of 막지 않았다면
SPLIT_MIN_N = 10                        # a split row with fewer trades says 표본 적음 (the 지도 tab's floor, TREND_MAP_MIN_N)
SKILL_MIN_N = 30                        # 실력 vs 운 under this many trades: 표본 적음
SMALL_N = 20                            # a record under this many trades: 표본 적음 (livebots SMALL[0])
TF_MIN = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
TF_KO = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간", "1d": "일봉"}
SIDE_KO = {1: "롱", -1: "숏"}
# docs/vwap-bot-ko.md 6장 (owners 10-23): 50 live trades at 80 % or more and close to the paper: more money. The stop line
# (the lead's correction, 10-23): the break-even win rate of the averages, not a fixed number (the guide's 71 % is not
# what the 5-year averages give: 78.6 %)
SCALE_N = 50
SCALE_WIN = 0.80
SCALE_KO = "실거래 50번(약 3주) 동안 승률 80% 이상이고 페이퍼와 결과가 비슷하면 돈을 늘려요 (docs/vwap-bot-ko.md 6장)"
SCALE_HONEST_KO = ("5년 기록에서 50번 80% 이상 뒤 다음 50번도 평균 손해였어요 — 승률과 함께 순ROE 합이 플러스이고 동전 쌍둥이보다 "
                   "나은지 같이 보세요")
STOP_KO = "승률이 본전 승률 아래로 이어지면 멈추고 다시 봐요 (멈추려면 sudo touch /var/lib/paperbot/STOP)"
# the research's numbers, said next to the live ones (research/vwap30/QA_KO.md, month2.json, docs/vwap-bot-ko.md 3장)
SCALE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, os.pardir, "research", "vwap30", "scale.json")
# research/vwap30/scale.json (the bot's 5,805 five-year paper trades, margin 40 %): used when the file cannot be read
SCALE_DEFAULT = {"trades": 5805, "win_rate": 0.7201, "avg_win_roe": 0.1076, "avg_loss_roe": -0.3943, "breakeven_win": 0.7856,
                 "share_80": 0.1878, "next_win_80": 0.7695, "next_roe_80": -0.0302, "next_mult_80": 0.4264}
PICK17 = {"n": 40, "wins": 37, "losses": 3, "span_ko": "10/05 19:30 ~ 10/23 (17일)", "src": "docs/vwap-bot-ko.md 3장",
          "ko": "이 17일은 이 봇을 고를 때 본 기간이라 실제보다 좋게 나와요 (지난 80개월 중 이 계열이 가장 좋았던 달)"}
# research/vwap30/QA_KO.md "A + CMO 1시간 A 조건" (add.json): net per trade on the price, after costs
PER_TRADE = {"a": -0.00133, "a_ko": "2020~2024", "b": -0.00115, "b_ko": "2025~2026", "src": "research/vwap30/QA_KO.md (add.json)"}
# research/vwap30/month2.json "증거금 40%": a fresh start every KST month, 79 months
MONTHS = {"months": 79, "plus": 6, "median": 0.2329, "src": "research/vwap30/month2.json"}
# the reasons a signal took no entry, grouped (막은 신호), in this order
BLOCK_GROUPS = (("vote", "4시간 추세 반대"), ("vol", "변동성 높음"), ("pause", "주말·발표·나스닥"), ("unread", "못 읽음"),
                ("other", "기타"))
BLOCK_SUB_KO = {"vote": "4시간 판단 4개 중 3개 이상이 신호 반대쪽", "vol": "신호 봉 ATR%가 지난 30일 80% 위치보다 큼",
                "pause": "한국 시간 토·일 · 미국 경제 발표 앞뒤 30분 · 나스닥 개장 앞뒤 30분",
                "unread": "판단에 쓸 바이낸스 봉을 못 읽어서 들어가지 않음", "other": "그 밖의 이유"}
# the watcher's kinds of a VWAP row (paperbot/livemissed.py: the VWAP bot's group 'gate' with gate_vote / gate_vol /
# gate_unread, and livemissed's own groups one / pause / late / exec); an executor's miss (group exec) is one bucket "exec"
KIND_KO = {"gate_vote": "4시간 추세 반대", "gate_vol": "변동성 높음", "gate_unread": "판단 못 읽음", "weekend": "주말",
           "macro": "경제 발표 앞뒤", "usopen": "나스닥 개장 앞뒤", "held": "포지션 있음 (한 번에 하나)", "lost": "같은 분 다른 신호에 밀림",
           "early": "빠른 청산 분", "late": "늦음·재시작", "exec": "실행기가 안 따라감"}
KIND_SUBJ = {"gate_vote": "4시간 추세 반대로 막은 신호", "gate_vol": "변동성 높음으로 막은 신호", "gate_unread": "봉을 못 읽어 막은 신호",
             "weekend": "주말이라 쉰 신호", "macro": "경제 발표 앞뒤라 쉰 신호", "usopen": "나스닥 개장 앞뒤라 쉰 신호",
             "held": "한 번에 하나 규칙이 막은 신호", "lost": "같은 분 다른 신호에 밀린 신호", "early": "빠른 청산 분에 안 탄 신호",
             "late": "늦어서 못 탄 신호", "exec": "실행기가 안 따라간 페이퍼 거래"}
KIND_VERB = {"gate": "막은 게", "pause": "쉰 게", "one": "막은 게", "late": "안 탄 게", "exec": "안 따라간 게"}
KIND_ORDER = ("gate_vote", "gate_vol", "gate_unread", "weekend", "macro", "usopen", "held", "lost", "early", "late", "exec")
GRP_KO = {"gate": "진입 조건(4시간·변동성)"}
VIRTUAL_PENDING_KO = "아직 계산 전 (감시가 새 버전으로 돌아야 생겨요)"
VIRTUAL_NOTE_KO = ("막은 신호가 이겼을 거면 그 막기가 돈을 잃게 한 거고, 졌을 거면 도운 거예요. 가상 결과(같은 엔진·같은 1분봉, 실제 체결 "
                   "아님)이고, 표본이 적으면 아무것도 결정하지 않아요. 조건을 바꿀지는 두 분이 정해요")
SESSIONS_ORDER = ("asia", "europe", "us", "dawn")
HOLD_BUCKETS = ((HOUR, "1시간 안"), (4 * HOUR, "1~4시간"), (12 * HOUR, "4~12시간"), (24 * HOUR, "12~24시간"),
                (48 * HOUR, "24~48시간"), (None, "48시간 넘게"))
ATR_BUCKETS = ((0.6, "0.6 미만"), (0.8, "0.6~0.8"), (1.0, "0.8~1.0"), (None, "1.0 이상"))
VOTE_KO = {1: "같은 방향", 0: "보류", -1: "반대 (동전 쌍둥이만)"}


# ---------------------------------------------------------------- small helpers
def _C():
    from ... import combo as C          # the bot's own words (MEMBER_KO, KO_EXIT, SESSIONS, gate_lines)
    return C


def _G():
    from ... import entrygates as G
    return G


def _LM():
    from ... import livemissed as LM
    return LM


def tf_ko(tf: Any) -> str:
    return TF_KO.get(tf, str(tf or ""))


def member_ko(strategy: Any, tf: Any = None) -> str:
    """"VWAP 복귀 실패 30분" / "CMO·샌드위치 캔들 1시간" (combo.member_ko: the owners' names)."""
    name = _C().member_ko(str(strategy or "")) if strategy else "매매법 모름"
    return f"{name} {tf_ko(tf)}".strip() if tf else name


def exit_ko(reason: Any, cfg: Optional[dict]) -> str:
    """손절 / 계단 익절 / 보유 한도 청산 (the bot's own words: combo.KO_EXIT, TIME by livepapers.exit_ko)."""
    return LP.exit_ko(reason, cfg, _C().KO_EXIT)


def pct_ko(x: Optional[float], d: int = 1, unit: str = "%") -> str:
    """"+12.1%" / "−4.3%" / "0.0%" (a ratio; the page's own minus sign); "—" for unknown."""
    if x is None:
        return "—"
    s = f"{abs(float(x)) * 100:.{d}f}"
    return ("+" if x > 0 and float(s) else "−" if x < 0 and float(s) else "") + s + unit


def obj_ko(word: str) -> str:
    """The object particle after ``word``: 을 after a closed Hangul syllable, else 를 ("추세판단 봇을", "페이퍼 −35%를")."""
    w = str(word or "").strip()
    last = w[-1] if w else ""
    return "을" if "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 else "를"


def dur_ko(ms: Optional[int]) -> Optional[str]:
    """"31시간 20분" / "45분" (None for unknown)."""
    if ms is None:
        return None
    m = max(0, int(ms) // MIN)
    if m < 60:
        return f"{m}분"
    return f"{m // 60}시간" + (f" {m % 60}분" if m % 60 else "")


def is_vwap(cfg: Any) -> bool:
    """A config of the VWAP bot: an entry gate, or 'VWAP' in its name (never the file name alone)."""
    if not isinstance(cfg, dict):
        return False
    return bool(cfg.get("vote_gate") or cfg.get("vol_gate")) or "VWAP" in str(cfg.get("name") or "").upper()


def kst_day0(ms: int) -> int:
    return L.kst_day_start(L.kst_day(ms))


# ---------------------------------------------------------------- which database is the VWAP bot
def locate(p: dict, now: int, more: Optional[dict] = None) -> dict:
    """The VWAP bot among the site's paper bots (module docstring), with every source the site reads (livebots.sources):
    {"state", "reason_ko", "bot" (the paper_bots item), "cfg", "cfg_source" ("db" | "file"), "execs", "configs", "bots"}.
    ``state``: "ok" (found, its database readable) / "off" (no VWAP bot: OFF_KO, ``other_ko`` naming the second bot when
    there is another one) / "missing" (its config says so but its database has no record yet) / "error"."""
    more = more or L.paths_more()
    configs, _follows, paper, execs = L.sources(p, now)
    bots = L.paper_bots(p, paper, execs)
    base = {"execs": execs, "configs": configs, "bots": bots}
    other = None
    for b in bots:
        fallback = more.get("combo_config") if b["id"] == "paper" else more.get("combo2_config")
        combo = L.read_combo(b["path"], fallback or "-")
        cfg = combo.get("config") if combo.get("state") == "ok" else None
        if not is_vwap(cfg):
            if b["id"] != "paper":
                other = b
            continue
        out = {**base, "bot": b, "cfg": cfg, "cfg_source": combo.get("source"), "combo_since": combo.get("since_ms")}
        rd = b["read"]
        if rd.get("state") == "error":
            return {**out, "state": "error", "reason_ko": rd.get("reason_ko") or READ_KO, "reason": rd.get("reason"), "path": b["path"]}
        if rd.get("state") != "ok" or combo.get("source") != "db":
            return {**out, "state": "missing", "reason_ko": FIRST_KO, "path": b["path"]}
        return {**out, "state": "ok"}
    if other is not None and other["read"].get("state") == "error":
        return {**base, "state": "error", "bot": other, "reason_ko": "두 번째 페이퍼 기록을 읽지 못해 VWAP 개선판인지 몰라요",
                "reason": other["read"].get("reason"), "path": other["path"]}
    return {**base, "state": "off", "reason_ko": OFF_KO,
            "other_ko": f"두 번째 페이퍼 봇({other['short_ko']})은 VWAP 개선판이 아니에요" if other is not None else None}


def head_of(loc: dict, now: int) -> dict:
    """The part of every answer that says which bot and in what state (never the full records)."""
    out = {"now_ms": now, "state": loc["state"], "reason_ko": loc.get("reason_ko"), "reason": loc.get("reason"),
           "other_ko": loc.get("other_ko"), "off_ko": OFF_KO}
    b = loc.get("bot")
    if b is not None and loc["state"] != "off":
        out["bot"] = {"id": b["id"], "path": b["path"], "name": b.get("name") or (loc.get("cfg") or {}).get("name"),
                      "short_ko": b.get("short_ko"), "label_ko": b.get("label_ko")}
    return out


# ---------------------------------------------------------------- the VWAP bot's database (one snapshot)
def _trade_of(r: tuple) -> dict:
    """A closed paper trade (livebots._paper_trade) with what the gates read at its entry (its context ``gates``)."""
    t = L._paper_trade(r)
    d = L._j(r[9])
    ctx = d.get("context") if isinstance(d.get("context"), dict) else {}
    t["gates"] = ctx.get("gates") if isinstance(ctx.get("gates"), dict) else None
    return t


def snapshot(path: str, now: int, sig_from: Optional[int] = None, filtered: bool = False) -> dict:
    """The VWAP bot's database in one read: its states (accounts, combo_run, heartbeat, gates_now), its accounts' first
    records, the closed trades of both accounts (with the gates read at each entry), the raw position of each account,
    and on request its signal rows from ``sig_from`` with their outcomes, and every FILTERED row (``filtered``)."""
    try:
        conn = L.open_ro(path)
    except FileNotFoundError:
        return L._missing(path, FIRST_KO)
    except (OSError, sqlite3.Error) as exc:
        return {**L._err(path, exc), "reason_ko": READ_KO + f" · {L.reason_ko(exc, path)}"}
    try:
        conn.execute("BEGIN")
        tables = L._tables(conn)
        if not {"state", "trades"} <= tables:
            return L._missing(path, L.NO_TABLE_KO)
        st = {k: (L._i(ts), L._j(d)) for k, ts, d in conn.execute(
            "SELECT k, ts, data FROM state WHERE k IN ('accounts', 'combo_run', 'heartbeat', 'gates_now')")}
        created = {a: L._i(t) for a, t in conn.execute("SELECT account_id, created_ts FROM accounts")} if "accounts" in tables else {}
        trades = {a: [_trade_of(r) for r in conn.execute(
            "SELECT id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, data FROM trades "
            "WHERE account_id = ? ORDER BY exit_time, id", (a,))] for a in (ACCOUNT, FLIP)}
        sigs, outs, filt = [], [], []
        if sig_from is not None and "signal_log" in tables:
            sigs = conn.execute("SELECT id, bar_close, timeframe, strategy, symbol, side, status, data FROM signal_log WHERE bar_close >= ? "
                                "ORDER BY bar_close DESC, id DESC LIMIT ?", (int(sig_from), SIG_KEEP)).fetchall()
            if "outcomes" in tables:
                outs = conn.execute("SELECT step_ts, status, reason, symbol, data FROM outcomes WHERE account_id = ? AND step_ts >= ? "
                                    "ORDER BY id", (ACCOUNT, int(sig_from))).fetchall()
        if filtered and "signal_log" in tables:
            filt = conn.execute("SELECT bar_close, timeframe, strategy, symbol, side, data FROM signal_log WHERE status = 'FILTERED' "
                                "ORDER BY bar_close DESC, id DESC").fetchall()
    except sqlite3.Error as exc:
        return {**L._err(path, exc), "reason_ko": READ_KO + f" · {L.reason_ko(exc, path)}"}
    finally:
        conn.close()
    acc_ts, acc = st.get("accounts") or (None, {})
    engines = acc.get("engines") if isinstance(acc.get("engines"), dict) else {}
    run_ts, run = st.get("combo_run") or (None, {})
    cfg = run.get("config") if isinstance(run.get("config"), dict) else {}
    return {"state": "ok", "path": path, "as_of_ms": acc_ts, "engines": engines, "cfg": cfg, "run_ts": run_ts,
            "taker_fee": L._f(run.get("taker_fee")), "heartbeat": st.get("heartbeat") or (None, {}),
            "gates_now": st.get("gates_now") or (None, None), "created": created, "trades": trades, "signals": sigs, "outcomes": outs,
            "filtered": filt}


def since_of(snap: dict) -> Optional[int]:
    """The bot's first start on its database: its paper account's first record, else its last start (``combo_run``)."""
    return snap["created"].get(ACCOUNT) or snap.get("run_ts")


def bot_status(snap: dict, now: int) -> dict:
    """Running or not (the heartbeat the bot writes every poll), its first and its last start."""
    hb_ts, hb = snap["heartbeat"]
    age = now - hb_ts if hb_ts is not None else None
    return {"since_ms": since_of(snap), "started_ms": snap.get("run_ts"), "heartbeat_ms": hb_ts, "age_ms": age,
            "last_step_ms": L._i((hb or {}).get("last_step")) if isinstance(hb, dict) else None,
            "running": None if age is None else age <= HB_STALE_MS, "stale": age is None or age > HB_STALE_MS,
            "as_of_ms": snap.get("as_of_ms")}


# ---------------------------------------------------------------- what the gates read, in the page's shape
def gates_view(g: Any, side: Optional[int] = None) -> Optional[dict]:
    """What the entry gates read (entrygates info): the 4h vote (its word, counts, with the side: 1 같은 방향 / 0 보류 / −1
    반대) and the ATR% of the signal bar against its 30-day point (and their ratio), with the bot's own words."""
    if not isinstance(g, dict):
        return None
    out: dict = {"text": _C().gates_text(g) or None}
    v = g.get("vote") if isinstance(g.get("vote"), dict) else None
    if v is not None:
        raw = L._i(v.get("raw"))
        up, down = L._i(v.get("up")), L._i(v.get("down"))
        ws = raw * int(side) if raw is not None and side else L._i(v.get("with_side"))
        out["vote"] = {"tf": v.get("tf"), "raw": raw, "up": up, "down": down, "neutral": (4 - up - down) if up is not None and down is not None else None,
                       "word": {1: "상승", -1: "하락", 0: "보류"}.get(raw), "with_side": ws, "text": v.get("text")}
    o = g.get("vol") if isinstance(g.get("vol"), dict) else None
    if o is not None:
        a, q = L._f(o.get("atr_pct")), L._f(o.get("q_pct"))
        out["vol"] = {"tf": o.get("tf"), "atr_pct": a, "q_pct": q, "ratio": (a / q) if a is not None and q else None, "text": o.get("text")}
    return out


def block_group(why: Any) -> str:
    """vote / vol / pause / unread / other of a FILTERED row's reason (paperbot/entrygates.py and combo.py _entry_block's
    own words: "4시간 추세 반대: …", "변동성 높음: …", "… 못 읽음(진입 안 함): …", 주말 / 경제 발표 / 나스닥 개장)."""
    w = str(why or "")
    if "못 읽음" in w:
        return "unread"
    if re.match(r"^\S+ 추세 반대", w):
        return "vote"
    if w.startswith("변동성 높음"):
        return "vol"
    if w.startswith(("주말", "경제 발표", "나스닥 개장")):
        return "pause"
    return "other"


# ---------------------------------------------------------------- 지금 코인별 (state gates_now)
def _side_why(vote: Optional[dict], vol: Optional[dict], vote_on: bool, vol_on: bool, tf: str, vote_tf: str) -> dict:
    """{1: [(kind, words)], -1: [...]} of what would stop a long / a short of a ``tf`` signal now (empty: it could go in)."""
    out: dict = {1: [], -1: []}
    vk = tf_ko(vote_tf)
    for side in (1, -1):
        if vote_on:
            if not isinstance(vote, dict) or vote.get("error"):
                out[side].append(("unread", f"{vk} 판단 못 읽음"))
            elif L._i(vote.get("raw")) == -side:
                n = vote.get("up") if side < 0 else vote.get("down")
                out[side].append(("vote", f"{vk} {'상승' if side < 0 else '하락'} {n}표"))
        if vol_on:
            if not isinstance(vol, dict) or vol.get("error"):
                out[side].append(("unread", f"{tf_ko(tf)} 변동성 못 읽음"))
            elif vol.get("high"):
                out[side].append(("vol", f"변동성 높음 {tf_ko(tf)}"))
    return out


def sides_ko(why: dict) -> str:
    """"롱·숏 둘 다 가능" / "롱 가능 · 숏 막힘(4시간 상승 3표)" / "둘 다 막힘(변동성 높음 30분)" / "못 읽음 → 진입 안 함 (…)"."""
    lo, sh = why[1], why[-1]
    if not lo and not sh:
        return "롱·숏 둘 다 가능"
    unread = [w for k, w in lo + sh if k == "unread"]
    if unread:
        return f"못 읽음 → 진입 안 함 ({', '.join(dict.fromkeys(unread))})"
    if lo and sh:
        return f"둘 다 막힘({', '.join(dict.fromkeys(w for _k, w in lo + sh))})"
    ok_side, bad_side, bad = (1, -1, sh) if not lo else (-1, 1, lo)
    return f"{SIDE_KO[ok_side]} 가능 · {SIDE_KO[bad_side]} 막힘({', '.join(w for _k, w in bad)})"


def picture_view(snap: dict, cfg: dict, now: int) -> dict:
    """지금 코인별: the bot's own picture (state ``gates_now``, entrygates.picture: written two minutes after every 30-minute
    close) per coin: the 4h judgment in words with its counts, each signal bar's ATR% against its 30-day point, and per
    member which side a signal could take now. ``state`` "none" before the first picture, "error" when the bot could not
    make it; ``stale`` when older than PIC_STALE_MS."""
    ts, pic = snap["gates_now"]
    if not isinstance(pic, dict):
        return {"state": "none", "ko": "아직 그림 없음 (봇이 30분봉이 끝날 때마다 2분 뒤에 그려요)"}
    at = L._i(pic.get("at")) or ts
    base = {"at": at, "ts": ts, "age_ms": now - at if at is not None else None,
            "stale": at is None or now - at > PIC_STALE_MS, "stale_ms": PIC_STALE_MS}
    if pic.get("error"):
        return {**base, "state": "error", "ko": "봇이 그림을 못 만들었어요", "reason": str(pic.get("error"))[:300]}
    vote_cfg = pic.get("vote") if isinstance(pic.get("vote"), dict) else cfg.get("vote_gate")
    vol_cfg = pic.get("vol") if isinstance(pic.get("vol"), dict) else cfg.get("vol_gate")
    vote_tf = (vote_cfg or {}).get("tf", "4h")
    tfs = [tf for tf in (pic.get("tfs") or []) if tf in TF_MIN] or sorted({m.get("tf") for m in cfg.get("members") or [] if isinstance(m, dict)},
                                                                         key=lambda x: TF_MIN.get(x, 0))
    members = [m for m in cfg.get("members") or [] if isinstance(m, dict)]
    rows = []
    coins = pic.get("coins") if isinstance(pic.get("coins"), dict) else {}
    for sym in sorted(coins, key=lambda s: L.COINS.index(s) if s in L.COINS else 99):
        r = coins[sym] if isinstance(coins[sym], dict) else {}
        v = r.get("vote") if isinstance(r.get("vote"), dict) else None
        vote = None
        if v is not None:
            vote = {"error": v["error"]} if v.get("error") else {
                "raw": L._i(v.get("raw")), "word": {1: "상승", -1: "하락", 0: "보류"}.get(L._i(v.get("raw")), "보류"),
                "up": L._i(v.get("up")), "down": L._i(v.get("down")),
                "neutral": 4 - (L._i(v.get("up")) or 0) - (L._i(v.get("down")) or 0), "votes": v.get("votes"), "bar_close": L._i(v.get("bar_close")),
                "text": v.get("text")}
        vols = {}
        for tf in tfs:
            x = (r.get("vol") or {}).get(tf) if isinstance(r.get("vol"), dict) else None
            if x is None:
                vols[tf] = None
            elif x.get("error"):
                vols[tf] = {"error": x["error"], "bar_close": L._i(x.get("bar_close"))}
            else:
                a, q = L._f(x.get("atr_pct")), L._f(x.get("q_pct"))
                vols[tf] = {"atr_pct": a, "q_pct": q, "ratio": a / q if a is not None and q else None, "high": bool(x.get("high")),
                            "bar_close": L._i(x.get("bar_close")), "text": x.get("text")}
        sides = []
        for m in members:
            tf = m.get("tf")
            why = _side_why(vote, vols.get(tf), vote_cfg is not None, vol_cfg is not None, tf, vote_tf)
            sides.append({"tf": tf, "strategy": m.get("strategy"), "member_ko": member_ko(m.get("strategy"), tf),
                          "long": {"ok": not why[1], "why": [w for _k, w in why[1]]}, "short": {"ok": not why[-1], "why": [w for _k, w in why[-1]]},
                          "unread": any(k == "unread" for k, _w in why[1] + why[-1]), "ko": sides_ko(why)})
        rows.append({"symbol": sym, "vote": vote, "vol": vols, "sides": sides})
    return {**base, "state": "ok", "rows": rows, "tfs": tfs, "vote_tf": vote_tf, "vote_cfg": vote_cfg, "vol_cfg": vol_cfg}


# ---------------------------------------------------------------- the position
def position_view(snap: dict, cfg: dict, now: int) -> Optional[dict]:
    """The paper position: the strategy in the owners' words, entry, size, stop, lock and the next step (livebots
    ._paper_position: the config's ladder), net ROE at the bot's last mark, held so far and the time left to the hold
    limit (``max_hold_bars`` of its own bar: the bot closes it at the first minute past it, exit "TIME"), what the gates
    read at its entry."""
    e = snap["engines"].get(ACCOUNT) if isinstance(snap["engines"].get(ACCOUNT), dict) else None
    if not e or not isinstance(e.get("position"), dict):
        return None
    rt = L.round_trip(snap.get("taker_fee"))
    ladder = cfg.get("ladder") if isinstance(cfg.get("ladder"), dict) else {}
    p = L._paper_position(ACCOUNT, e, rt, ladder)
    raw = e["position"]
    sig = raw.get("signal") if isinstance(raw.get("signal"), dict) else {}
    meta = sig.get("meta") if isinstance(sig.get("meta"), dict) else {}
    tf = sig.get("timeframe")
    bars = L._i(cfg.get("max_hold_bars"))
    limit = bars * TF_MIN[tf] * MIN if bars and tf in TF_MIN else None
    et = p.get("entry_time")
    deadline = et + limit if limit is not None and et is not None else None
    g = meta.get("gates") if isinstance(meta.get("gates"), dict) else (meta.get("ctx") or {}).get("gates") if isinstance(meta.get("ctx"), dict) else None
    return {**p, "strategy_ko": member_ko(p.get("strategy_id"), tf), "member_name_ko": member_ko(p.get("strategy_id")),
            "roe_now": p.get("last_mark_roe_net"), "mark": p.get("last_mark"), "hold_ms": now - et if et is not None else None,
            "limit_bars": bars, "limit_ms": limit, "deadline_ms": deadline, "left_ms": deadline - now if deadline is not None else None,
            "left_ko": f"보유 한도까지 {dur_ko(deadline - now)}" if deadline is not None and deadline > now else
            ("보유 한도 지남 · 다음 1분에 정리" if deadline is not None else "보유 한도 없음"),
            "gates": gates_view(g, p.get("side"))}


# ---------------------------------------------------------------- who follows it
def segs_of(x: dict, path: str) -> list:
    """[[from, to or None]] of the stretches the executor followed ``path`` (livepapers segments: from its start records)."""
    out, segs = [], x.get("segs") or []
    for i, (frm, pth) in enumerate(segs):
        if LP.same(pth, path):
            to = segs[i + 1][0] if i + 1 < len(segs) else None
            out.append([frm, to])
    return out


def followers(loc: dict, snap: dict, now: int) -> list:
    """Each executor that follows the VWAP bot now (its last start named its database), did before, or whose config names
    it but has not been restarted yet: since when, its own signal light on this bot's trades (livebots.light with its own
    config's n and share: the executor's rule), its record state, its own position."""
    path = loc["bot"]["path"]
    pnls = [t["pnl"] for t in sorted(snap["trades"][ACCOUNT], key=lambda t: (t["exit_time"] or 0, t["id"] or 0), reverse=True)]
    out = []
    for x in loc["execs"]:
        cfg = x["config"] if isinstance(x.get("config"), dict) else {}
        stretches = segs_of(x, path)
        now_on = LP.same(x["paper_path"], path)
        pending = cfg.get("state") == "ok" and LP.same(cfg.get("paper_db"), path) and not now_on
        if not stretches and not pending:
            continue
        rec = x["record"]
        state = "following" if now_on else "pending" if pending else "was"
        lt = (L.light(cfg.get("signal_light_n"), cfg.get("signal_light_min_win"), pnls) if cfg.get("state") == "ok"
              else {"state": "unknown", "reason_ko": "실행기 설정을 읽지 못해 신호등 기준을 몰라요"})
        if rec.get("state") == "ok":
            lt["last_event"] = next((e for e in rec.get("events") or [] if e["kind"] in ("light_red", "light_unread")), None)
        pos = rec.get("position") if rec.get("state") == "ok" else None
        out.append({"id": x["id"], "name_ko": x["name_ko"], "exchange": cfg.get("exchange"), "state": state,
                    "state_ko": {"following": "따라가는 중", "pending": "설정은 바뀜 · 실행기를 다시 켜야 따라가요",
                                 "was": "예전에 따라감 · 지금은 다른 페이퍼"}[state],
                    "since_ms": stretches[-1][0] if stretches else None, "until_ms": stretches[-1][1] if stretches else None,
                    "stretches": stretches, "light": lt, "name_light": x["name_ko"],
                    "record": {k: rec.get(k) for k in ("state", "reason_ko", "reason", "path", "as_of_ms", "stale", "halted", "halt_reason")},
                    "position": pos, "follows_ko": x.get("follows_ko"), "notes": x.get("notes") or [],
                    "light_rule": {"n": cfg.get("signal_light_n"), "min_win": cfg.get("signal_light_min_win")}})
    return out


# ---------------------------------------------------------------- rules in words
def rules_view(cfg: dict) -> dict:
    """The rules of the config the bot runs (its ``combo_run``), in the bot's own words (combo.py: gate_lines,
    stop_text, the ladder's describe); the raw numbers next to them."""
    C = _C()
    lines = []
    members = [m for m in cfg.get("members") or [] if isinstance(m, dict)]
    lines.append("매매법 " + " · ".join(member_ko(m.get("strategy"), m.get("tf")) for m in members) + " (규칙봇 신호, 포지션 하나)")
    try:
        co = C.ComboConfig.from_dict(cfg)
        lev_b, lev_o = co.lev_of("BTCUSDT"), co.lev_of("ETHUSDT")
        lines.append(f"BTC {lev_b}배 · 나머지 {lev_o}배 · 증거금 " + ("배수%" if co.margin == "leverage" else f"잔고의 {float(co.margin):.0%}"))
        lines.append(f"손절 {C.stop_text(co)} · 계단 익절 {co.ladder_spec.describe()}")
        if co.max_loss_frac:
            lines.append(f"손절 한 번에 계좌 최대 −{float(co.max_loss_frac):.0%} (넘으면 수량을 줄임)")
        lines += C.gate_lines(co)
        rest = (["주말(한국 시간 토·일)"] if co.no_weekend else []) + ([f"미국 경제 발표 앞뒤 {co.macro_blackout_min}분"] if co.macro_blackout_min else []) \
            + ([C.us_open_ko(co.us_open_pause_min or 0, co.us_open_pre_min or 0)] if co.us_open_pause_min or co.us_open_pre_min else [])
        if rest:
            lines.append("진입 쉼: " + " · ".join(rest))
        lines.append("반대 신호 청산 없음" if not co.early_exit else f"빠른 청산 {C.KO_EARLY.get(co.early_exit, co.early_exit)}")
        if co.flip_twin:
            lines.append("동전 쌍둥이 계좌(같은 진입 · 방향만 무작위)를 같이 기록")
        error = None
    except Exception as exc:  # noqa: BLE001  a config this code cannot read: its raw numbers only, said so
        error = f"{type(exc).__name__}: {exc}"[:200]
    return {"lines": lines, "error": error, "name": cfg.get("name"), "members": [{"strategy": m.get("strategy"), "tf": m.get("tf"),
            "ko": member_ko(m.get("strategy"), m.get("tf")),
            "hold_ko": dur_ko(int(cfg["max_hold_bars"]) * TF_MIN[m["tf"]] * MIN) if cfg.get("max_hold_bars") and m.get("tf") in TF_MIN else None}
            for m in members],
            "margin": cfg.get("margin"), "leverage": cfg.get("leverage"), "stop": cfg.get("stop"), "ladder": L.ladder_numbers(cfg.get("ladder")),
            "max_loss_frac": L._f(cfg.get("max_loss_frac")), "max_hold_bars": L._i(cfg.get("max_hold_bars")), "vote_gate": cfg.get("vote_gate"),
            "vol_gate": cfg.get("vol_gate"), "initial_equity": L._f(cfg.get("initial_equity"))}


# ---------------------------------------------------------------- signals (최근 신호 · 막은 신호)
def _outcomes(snap: dict) -> dict:
    """{(bar close, tf, member, coin): (status, reason, step, signal meta)} of the paper account's outcomes."""
    oc: dict = {}
    for step, st, reason, sym, data in snap["outcomes"]:
        d = L._j(data)
        sig = d.get("signal") if isinstance(d.get("signal"), dict) else {}
        meta = sig.get("meta") if isinstance(sig.get("meta"), dict) else {}
        ts = L._i(sig.get("ts"))
        if ts is None:
            continue
        oc[(ts + 1, sig.get("timeframe"), meta.get("member") or sig.get("strategy_id"), sym)] = (st, reason, L._i(step), meta)
    return oc


STAGE_KO = {"entered": "진입", "skipped": "건너뜀", "late": "늦음", "rejected": "거절", "filtered": "막힘", "submitted": "결과 기록 전"}


def signals_view(snap: dict, now: int, since: Optional[int], cfg: Optional[dict] = None) -> dict:
    """The last 48 h of the bot's signals (from its start when younger), newest first: entered, skipped (one position),
    late, refused by the engine, or filtered (the reason group and the bot's own words), each with what the gates read."""
    lo = max(int(now) - SIG_SPAN_MS, int(since or 0))
    oc = _outcomes(snap)
    rows, counts = [], {}
    for _id, bc, tf, member, sym, side, status, data in snap["signals"]:
        if (L._i(bc) or 0) < lo:
            continue
        d = L._j(data)
        strat = d.get("strategy") or str(member).split("@")[0]
        g, grp, why = d.get("gates"), None, None
        if status == "FILTERED":
            stage, why = "filtered", L.why_words(d.get("why"))
            grp = block_group(d.get("why"))
        elif status == "SUBMITTED":
            o = oc.get((L._i(bc), tf, member, sym))
            if o is None:
                stage = "submitted"
            else:
                g = (o[3] or {}).get("gates") or g
                if o[0] == "ENTERED":
                    stage = "entered"
                else:
                    cat, why = L.outcome_cat(o[0], o[1])
                    stage = "skipped" if o[0] == "SKIPPED" else "late" if cat == "late" else "rejected"
                    if stage == "late":            # combo.py: a signal seen more than max_signal_age_s after its close
                        a = int(L._f((cfg or {}).get("max_signal_age_s")) or 150)
                        age = (f"{a // 60}분" + (f" {a % 60}초" if a % 60 else "")) if a >= 60 else f"{a}초"
                        why = f"신호를 {age} 넘게 늦게 봐서 들어가지 않음 (재시작 뒤 따라잡기 등)"
        else:
            stage, why = "other", d.get("why") or status
        counts[stage] = counts.get(stage, 0) + 1
        rows.append({"t": L._i(bc), "tf": tf, "member": member, "strategy": strat, "member_ko": member_ko(strat, tf), "symbol": sym,
                     "side": L._i(side), "status": status, "stage": stage, "stage_ko": STAGE_KO.get(stage, status), "group": grp,
                     "group_ko": dict(BLOCK_GROUPS).get(grp) if grp else None, "why": why, "gates": gates_view(g, L._i(side))})
    return {"from": lo, "span_ms": SIG_SPAN_MS, "cut": lo > int(now) - SIG_SPAN_MS, "rows": rows, "counts": counts}


def blocked_counts(snap: dict, now: int, since: Optional[int]) -> dict:
    """막은 신호: the FILTERED rows by reason group, today (KST), the last 7 KST days (today and the six before) and since the
    bot's start; and the newest of them with what the gates read."""
    t_day, t_week = kst_day0(now), kst_day0(now) - 6 * DAY
    lo = int(since or 0)
    by = {k: {"id": k, "ko": ko, "sub_ko": BLOCK_SUB_KO[k], "today": 0, "week": 0, "all": 0, "kinds": {}} for k, ko in BLOCK_GROUPS}
    recent = []
    for bc, tf, member, sym, side, data in snap["filtered"]:
        t = L._i(bc) or 0
        if t < lo:
            continue
        d = L._j(data)
        g = block_group(d.get("why"))
        b = by[g]
        b["all"] += 1
        b["week"] += t >= t_week
        b["today"] += t >= t_day
        if g == "pause":
            kind, kko = L.why_cat("FILTERED", d.get("why"))
            b["kinds"].setdefault(kind, {"id": kind, "ko": kko, "n": 0})["n"] += 1
        if len(recent) < BLOCK_RECENT:
            strat = d.get("strategy") or str(member).split("@")[0]
            recent.append({"t": t, "tf": tf, "member": member, "member_ko": member_ko(strat, tf), "symbol": sym, "side": L._i(side), "group": g,
                           "group_ko": b["ko"], "why": L.why_words(d.get("why")), "gates": gates_view(d.get("gates"), L._i(side))})
    groups = [{**b, "kinds": sorted(b["kinds"].values(), key=lambda k: -k["n"])} for b in by.values()]
    tot = {k: sum(b[k] for b in groups) for k in ("today", "week", "all")}
    return {"groups": groups, "total": tot, "from": {"today_ms": t_day, "week_ms": t_week, "since_ms": since}, "recent": recent}


# ---------------------------------------------------------------- 막지 않았다면 (livecheck.db missed, paper 'vwap')
def read_virtual(path: str, now: int, since: Optional[int]) -> dict:
    """The watcher's virtual results of the VWAP bot's signals it did not take (paperbot/livemissed.py, table ``missed``,
    rows ``paper = 'vwap'``; the Telegram side's contract: column ``paper``, group 'gate' with why_kind gate_vote / gate_vol /
    gate_unread, the gates read in ``detail``). ``state`` "pending" while the table has no ``paper`` column yet (the watcher
    of the version before), "missing" / "error" as every source."""
    LM = _LM()
    try:
        conn = L.open_ro(path)
    except FileNotFoundError:
        return L._missing(path, "1분 감시가 아직 기록 전이에요 (못 탄 신호는 1분 감시가 매번 계산해요)")
    except (OSError, sqlite3.Error) as exc:
        return L._err(path, exc)
    try:
        conn.execute("BEGIN")
        tables = L._tables(conn)
        if "missed" not in tables:
            return L._missing(path, "점검 파일은 있지만 못 탄 신호 표가 아직 없어요 (1분 감시가 아직 기록 전)")
        have = L._cols(conn, "missed")
        if "paper" not in have:
            return {"state": "pending", "path": path, "reason_ko": VIRTUAL_PENDING_KO}
        lo = int(since or 0)
        try:
            rows = LM.read_rows(conn, lo, paper="vwap")
        except TypeError:                                 # livemissed before the contract's ``paper`` filter: the same rows here
            sel = [c if c in have else f"NULL AS {c}" for c in LM.READ_COLS]
            cur = conn.execute(f"SELECT {', '.join(sel)}, paper FROM missed WHERE t >= ? AND paper = 'vwap' ORDER BY t DESC, key", (lo,))
            rows = [{**LM.row_out(dict(zip(LM.READ_COLS, r[:-1]))), "paper": r[-1]} for r in cur.fetchall()]
        rows = [r for r in rows if r.get("paper", "vwap") == "vwap"]
        details = {}
        keys = [r["key"] for r in rows if r.get("key")]
        for i in range(0, len(keys), 500):
            part = keys[i:i + 500]
            for k, det in conn.execute(f"SELECT key, detail FROM missed WHERE key IN ({', '.join('?' * len(part))})", part):
                details[k] = L._j(det)
        meta = {k: (ts, L._j(d)) for k, ts, d in conn.execute("SELECT k, ts, data FROM missed_meta")} if "missed_meta" in tables else {}
    except sqlite3.Error as exc:
        return L._err(path, exc)
    finally:
        conn.close()
    for r in rows:
        r["gates"] = gates_view((details.get(r["key"]) or {}).get("gates"), r.get("side"))
    last_ts, _last = meta.get("pass") or (None, {})
    return {"state": "ok", "path": path, "rows": rows, "since_ms": since,
            "pass": {"last_ms": last_ts, "stale": last_ts is None or now - last_ts > 10 * MIN}}


def virtual_read_ko(kind: str, grp: Optional[str], b: dict) -> str:
    """"4시간 추세 반대로 막은 신호: 가상 1승 0패 · 순ROE 합 +12.1% → 이번엔 막은 게 이익을 놓쳤어요 · 표본 적음 · 대부분 운"
    (an executor's miss: the paper trade's own result, never 가상)."""
    subj = KIND_SUBJ.get(kind, KIND_KO.get(kind, kind))
    if not b.get("n"):
        return f"{subj}: 아직 없어요"
    if not b.get("closed"):
        rest = [f"진행 중 {b['open']}"] if b.get("open") else []
        rest += [f"{_LM().KO_STATE.get(k, k)} {b[k]}" for k in ("no_data", "refused", "rebuild_failed", "error") if b.get(k)]
        return f"{subj}: 끝난 것이 아직 없어요" + (f" ({' · '.join(rest)})" if rest else "")
    s = b.get("roe_sum") or 0.0
    verb = KIND_VERB.get(grp or "", "막은 게")
    tail = (f"이번엔 {verb} " + ("손해를 줄였어요" if s < 0 else "이익을 놓쳤어요")) if s else "이번엔 본전이에요"
    what = "페이퍼 결과" if kind == "exec" else "가상"
    return f"{subj}: {what} {b['wins']}승 {b['losses']}패 · 순ROE 합 {pct_ko(s)} → {tail}" + (" · 표본 적음 · 대부분 운" if b.get("small") else "")


def virtual_view(v: dict, sigs: dict, names: Optional[dict] = None) -> dict:
    """막지 않았다면, per reason (the gates first; an executor's misses in one bucket): n, closed, wins, losses, open, the
    virtual ROE sum, the one-line read and the newest rows with the gates read (the watcher's ``detail``, else the bot's own
    signal row) and their result. ``sigs``: {(member, coin, bar close): gates} of the bot's FILTERED rows; ``names``: {slot:
    the executor's name}."""
    if v.get("state") != "ok":
        return {k: v.get(k) for k in ("state", "reason_ko", "reason", "path")}
    LM = _LM()
    by: dict = {}
    for r in v["rows"]:
        if r.get("gates") is None:
            r["gates"] = sigs.get((r.get("member"), r.get("symbol"), r.get("t")))
        r["member_ko"] = member_ko(r.get("strategy"), r.get("tf")) if r.get("strategy") else None
        if r.get("executor"):
            r["executor_ko"] = (names or {}).get(r["executor"], r["executor"])
        k = "exec" if r.get("grp") == "exec" else (r.get("why_kind") or "?")
        by.setdefault(k, []).append(r)
    kinds = []
    for k in sorted(by, key=lambda k: KIND_ORDER.index(k) if k in KIND_ORDER else 99):
        rows = by[k]
        b = LM.block_of(rows)
        grp = rows[0].get("grp")
        kinds.append({"id": k, "ko": KIND_KO.get(k) or LM.KO_WHY.get(k, k), "grp": grp, "grp_ko": GRP_KO.get(grp) or LM.GROUP_KO.get(grp, grp),
                      "paper_result": k == "exec", **b, "read_ko": virtual_read_ko(k, grp, b), "rows": rows[:VIRTUAL_ROWS]})
    gate_rows = [r for r in v["rows"] if r.get("grp") == "gate"]
    return {"state": "ok", "kinds": kinds, "gate": LM.block_of(gate_rows), "n": len(v["rows"]), "pass": v["pass"], "small_n": LM.SMALL,
            "note_ko": VIRTUAL_NOTE_KO, "how_ko": "그때 들어갔다면 (가상 · 계좌가 비어 있었다고 치고)"}


# ---------------------------------------------------------------- 성적
def record(trades: list, wallet: Optional[float] = None, initial: Optional[float] = None) -> dict:
    """An account's closed trades in numbers: n, wins, losses, win rate, average win / loss net ROE, the break-even win
    rate of those two averages (|loss| / (win + |loss|): the win rate at which the average trade nets zero), profit factor
    (gross profit / gross loss), P&L, ROE sum, the deepest drop of the closed-trade equity from its running peak (from
    ``initial``), the wallet's change, the curve [[t, equity]]."""
    n = len(trades)
    wins = [t for t in trades if (L._f(t.get("pnl")) or 0) > 0]
    losses = [t for t in trades if (L._f(t.get("pnl")) or 0) <= 0]
    roe = lambda ts: [x for x in (L._f(t.get("roe")) for t in ts) if x is not None]          # noqa: E731
    aw = sum(roe(wins)) / len(roe(wins)) if roe(wins) else None
    al = sum(roe(losses)) / len(roe(losses)) if roe(losses) else None
    be = abs(al) / (aw + abs(al)) if aw is not None and al is not None and (aw + abs(al)) > 0 else None
    gp = sum(L._f(t.get("pnl")) or 0 for t in wins)
    gl = -sum(L._f(t.get("pnl")) or 0 for t in losses)
    pf = gp / gl if gl > 0 else None
    eq0 = initial
    if eq0 is None and trades and trades[0].get("equity_after") is not None and trades[0].get("pnl") is not None:
        eq0 = trades[0]["equity_after"] - trades[0]["pnl"]
    peak, dd, curve = eq0, 0.0, []
    if trades and eq0 is not None:
        curve.append([trades[0].get("entry_time"), eq0])
    for t in trades:
        e = L._f(t.get("equity_after"))
        if e is None:
            continue
        curve.append([t.get("exit_time"), e])
        peak = e if peak is None or e > peak else peak
        if peak:
            dd = max(dd, 1 - e / peak)
    return {"n": n, "wins": len(wins), "losses": len(losses), "win_rate": len(wins) / n if n else None, "avg_win": aw, "avg_loss": al,
            "breakeven": be, "pf": pf, "gross_profit": gp, "gross_loss": gl, "pnl": sum(L._f(t.get("pnl")) or 0 for t in trades),
            "roe_sum": sum(roe(trades)), "max_dd": dd if trades and eq0 is not None else None, "initial": eq0, "wallet": wallet,
            "change": (wallet / eq0 - 1) if wallet is not None and eq0 else None, "curve": L.thin(curve), "small": n < SMALL_N}


def account_view(snap: dict, aid: str, cfg: dict, since: Optional[int]) -> dict:
    """One account of the VWAP database (the paper or its coin-flip twin) since the bot's start."""
    e = snap["engines"].get(aid) if isinstance(snap["engines"].get(aid), dict) else None
    trades = [t for t in snap["trades"][aid] if (t.get("entry_time") or 0) >= int(since or 0)]
    if e is None and not trades:
        return {"state": "missing", "reason_ko": "이 계좌 기록이 아직 없어요" if aid == ACCOUNT else "동전 쌍둥이 계좌 기록이 없어요 (설정에서 꺼짐)"}
    init = L._f(cfg.get("initial_equity"))
    return {"state": "ok", "account": aid, **record(trades, L._f((e or {}).get("wallet")), init), "open": bool((e or {}).get("position")),
            "halted": bool((e or {}).get("halted"))}


def skill_view(paper: dict, flip: dict) -> Optional[dict]:
    """실력 vs 운: the real side against the coin-flip twin (the same entries, a random side), win rate and ROE sum."""
    if paper.get("state") != "ok" or flip.get("state") != "ok":
        return None
    n = min(paper["n"], flip["n"])
    dw = paper["win_rate"] - flip["win_rate"] if paper["win_rate"] is not None and flip["win_rate"] is not None else None
    dr = paper["roe_sum"] - flip["roe_sum"]
    if dw is None:
        ko = "실력 vs 운: 아직 둘 다 닫힌 거래가 없어요"
    else:
        ko = f"실력 vs 운: 진짜 방향이 동전보다 승률 {pct_ko(dw, 1, '%p')} · 순ROE 합 {pct_ko(dr, 1, '%p')}"
    return {"win_rate_diff": dw, "roe_sum_diff": dr, "pnl_diff": paper["pnl"] - flip["pnl"], "n": n, "small": n < SKILL_MIN_N,
            "small_n": SKILL_MIN_N, "ko": ko + (" · 표본 적음 (30번 미만은 대부분 운)" if n < SKILL_MIN_N else "")}


def scale_ref() -> dict:
    """The 5-year reference of the scale-up / stop lines (research/vwap30/scale.json, read now; SCALE_DEFAULT when the file
    cannot be read, said so)."""
    try:
        with open(SCALE_FILE, encoding="utf-8") as fh:
            d = json.load(fh)
        t80 = ((d.get("thresholds") or {}).get("승률 80% 이상") or {})
        out = {"trades": L._i(d.get("trades")), "win_rate": L._f(d.get("win_rate")), "avg_win_roe": L._f(d.get("avg_win_roe")),
               "avg_loss_roe": L._f(d.get("avg_loss_roe")), "breakeven_win": L._f(d.get("breakeven_win")),
               "share_80": L._f((d.get("stretches") or {}).get("share_80_or_more")), "next_win_80": L._f(t80.get("next_win")),
               "next_roe_80": L._f(t80.get("next_roe_per_trade")), "next_mult_80": L._f(t80.get("next_mult_median"))}
        if None in (out["win_rate"], out["breakeven_win"]):
            raise ValueError("scale.json without win_rate / breakeven_win")
        return {**{k: (v if v is not None else SCALE_DEFAULT[k]) for k, v in out.items()}, "src": "research/vwap30/scale.json"}
    except (OSError, ValueError, TypeError, AttributeError):
        return {**SCALE_DEFAULT, "src": "research/vwap30/scale.json (이 서버에 파일이 없어 그 숫자를 적어 둔 값)"}


def era_trades(x: dict, path: str) -> list:
    """The executor's closed live trades it entered while following ``path`` (livepapers: never the ones before a switch)."""
    r = x["record"]
    if r.get("state") != "ok":
        return []
    return [t for t in r.get("trades") or [] if LP.followed_at(x["segs"], path, t.get("entry_ts"))]


def pairs_view(x: dict, path: str, era: list) -> dict:
    """페이퍼와 비슷한가: the live trades of the era against the paper trades they followed (livebots.pairs_of: the same coin
    and side within MATCH_MS): how many, the same result (both won / both lost), the mean net-ROE difference (live − paper)
    and the mean entry slippage against the paper (in the trade's favour positive)."""
    pairs = L.pairs_of(x)
    rows = []
    for t in era:
        pt = pairs.get(str(t["key"]))
        if not pt or not LP.same(pt.get("paper_path"), path):
            continue
        slip = (t["side"] * (pt["entry_price"] - t["entry_price"]) / pt["entry_price"]) if pt.get("entry_price") and t.get("entry_price") else None
        rows.append({"key": t["key"], "symbol": t["symbol"], "side": t["side"], "entry_time": t.get("entry_ts"), "live_roe": t.get("roe"),
                     "paper_roe": pt.get("roe"), "diff": (t["roe"] - pt["roe"]) if t.get("roe") is not None and pt.get("roe") is not None else None,
                     "slip": slip, "same": ((t.get("pnl") or 0) > 0) == ((pt.get("pnl") or 0) > 0), "paper_id": pt.get("id")})
    diffs = [r["diff"] for r in rows if r["diff"] is not None]
    slips = [r["slip"] for r in rows if r["slip"] is not None]
    return {"n": len(rows), "of": len(era), "same": sum(1 for r in rows if r["same"]), "diff_mean": sum(diffs) / len(diffs) if diffs else None,
            "slip_mean": sum(slips) / len(slips) if slips else None, "rows": rows}


def checklist(x: dict, path: str, paper: dict, flip: dict, ref: dict) -> dict:
    """키우기 · 멈추기 (docs/vwap-bot-ko.md 6장, with the lead's 10-23 correction): the follower's live trades of the VWAP era
    only — n of 50, the win rate against 80 % (the owners' scale-up rule) and against the break-even win rate of its own
    averages (the stop line; the paper's when the live record has no win or no loss yet, else the 5-year one), the live ROE
    sum above zero and the paper above its coin-flip twin (the two checks the 5-year record asks for: a 50-trade stretch at
    80 % or more was followed by 50 more that still lost on average), and how close it is to the paper (no rule: numbers)."""
    era = era_trades(x, path)
    rec = record(sorted(era, key=lambda t: (t.get("exit_ts") or 0)), None, None) if era else record([], None, None)
    n = rec["n"]
    if rec["breakeven"] is not None:
        be, be_src = rec["breakeven"], "live"
    elif paper.get("state") == "ok" and paper.get("breakeven") is not None:
        be, be_src = paper["breakeven"], "paper"
    else:
        be, be_src = ref["breakeven_win"], "5y"
    be_ko = {"live": "실거래 평균 익절·손절로 계산", "paper": "실거래에 이긴·진 거래가 아직 다 없어 페이퍼 평균으로 계산",
             "5y": "실거래·페이퍼 평균이 아직 없어 5년 기록으로 계산"}[be_src]
    wr = rec["win_rate"]
    rows = [
        {"id": "n", "ko": f"실거래 {SCALE_N}번", "state": "ok" if n >= SCALE_N else "wait", "value_ko": f"{n} / {SCALE_N}번",
         "note": None if n >= SCALE_N else f"{SCALE_N - n}번 더 · 그 전엔 키우기·멈추기를 정하지 않아요"},
        {"id": "win80", "ko": "승률 80% 이상 (키우기)", "state": "wait" if n < SCALE_N or wr is None else "ok" if wr >= SCALE_WIN - 1e-9 else "no",
         "value_ko": f"{wr * 100:.1f}%" if wr is not None else "아직 없음", "note": f"{SCALE_N}번이 되면 판단해요" if n < SCALE_N else None},
        {"id": "roe", "ko": "순ROE 합 플러스", "state": "wait" if not n else "ok" if rec["roe_sum"] > 0 else "no",
         "value_ko": pct_ko(rec["roe_sum"]) if n else "아직 없음",
         "note": "승률이 높아도 손절 한 번이 익절 4~5번을 지워요"},
        {"id": "twin", "ko": "페이퍼가 동전 쌍둥이보다 나음", "state": "wait" if paper.get("state") != "ok" or flip.get("state") != "ok" or not paper.get("n")
         else "ok" if paper["roe_sum"] > flip["roe_sum"] else "no",
         "value_ko": (f"페이퍼 순ROE 합 {pct_ko(paper['roe_sum'])} · 동전 {pct_ko(flip['roe_sum'])}"
                      if paper.get("state") == "ok" and flip.get("state") == "ok" and paper.get("n") else "아직 없음"),
         "note": "같은 진입을 방향만 무작위로 한 계좌보다 나아야 방향을 맞히는 힘이 있다고 볼 수 있어요"},
    ]
    pv = pairs_view(x, path, era)
    rows.append({"id": "paper", "ko": "페이퍼와 비슷한가", "state": "info" if pv["n"] else "wait",
                 "value_ko": (f"결과가 같은 거래 {pv['same']}/{pv['n']} · 순ROE 차이 평균 {pct_ko(pv['diff_mean'], 1, '%p')}"
                              + (f" · 진입 미끄러짐 평균 {pct_ko(pv['slip_mean'], 3)}" if pv["slip_mean"] is not None else "")) if pv["n"] and pv["diff_mean"] is not None
                 else "짝지은 거래 없음", "note": "정해진 기준은 없어요 · 숫자를 보고 두 분이 판단해요"})
    stop_state = "wait" if wr is None else "bad" if wr < be - 1e-9 else "ok"
    return {"id": x["id"], "name_ko": x["name_ko"], "since_ms": (segs_of(x, path) or [[None]])[-1][0], "n": n, "goal": SCALE_N,
            "record": {k: rec[k] for k in ("n", "wins", "losses", "win_rate", "avg_win", "avg_loss", "breakeven", "pf", "pnl", "roe_sum")},
            "breakeven": {"value": be, "src": be_src, "ko": be_ko, "ref": ref["breakeven_win"],
                          "paper": paper.get("breakeven") if paper.get("state") == "ok" else None},
            "rows": rows, "stop": {"state": stop_state, "ko": STOP_KO, "small": n < SMALL_N,
                                   "value_ko": (f"승률 {wr * 100:.1f}% · 본전 승률 {be * 100:.1f}%" if wr is not None else "아직 거래 없음")},
            "scale_ko": SCALE_KO, "honest_ko": SCALE_HONEST_KO, "pairs": pv, "record_state": x["record"].get("state"),
            "reason_ko": x["record"].get("reason_ko")}


def research_view(ref: dict, paper: dict, follows: list) -> dict:
    """The research's numbers next to the live ones, honestly (module constants and research/vwap30/scale.json)."""
    return {"pick17": {**PICK17, "win_rate": PICK17["wins"] / PICK17["n"]},
            "five_year": {**ref, "per_trade": PER_TRADE, "months": MONTHS,
                          "ko": "5년 페이퍼(같은 규칙, 달마다 새로 시작)는 승률이 본전 승률보다 낮아 거래당 손해였어요"},
            "paper": {k: paper.get(k) for k in ("n", "wins", "win_rate", "avg_win", "avg_loss", "breakeven", "roe_sum")} if paper.get("state") == "ok" else None,
            "live": [{"id": c["id"], "name_ko": c["name_ko"], **c["record"]} for c in follows]}


def _hold_key(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    for top, ko in HOLD_BUCKETS:
        if top is None or ms < top:
            return ko
    return None


def _atr_key(g: Optional[dict]) -> str:
    r = ((g or {}).get("vol") or {}).get("ratio")
    if r is None:
        return "기록 없음"
    for top, ko in ATR_BUCKETS:
        if top is None or r < top:
            return ko
    return "기록 없음"


def split_rows(trades: list, key, order: Optional[list] = None) -> list:
    """One split: [{key, ko, n, wins, losses, win_rate, roe_sum, pnl, small}] in ``order`` (then the rest by count)."""
    by: dict = {}
    for t in trades:
        k = key(t)
        if k is None:
            continue
        by.setdefault(k, []).append(t)
    keys = [k for k in (order or []) if k in by] + sorted((k for k in by if k not in (order or [])), key=lambda k: (-len(by[k]), str(k)))
    out = []
    for k in keys:
        ts = by[k]
        w = sum(1 for t in ts if (L._f(t.get("pnl")) or 0) > 0)
        out.append({"key": str(k), "ko": str(k), "n": len(ts), "wins": w, "losses": len(ts) - w, "win_rate": w / len(ts),
                    "roe_sum": sum(L._f(t.get("roe")) or 0 for t in ts), "pnl": sum(L._f(t.get("pnl")) or 0 for t in ts),
                    "small": len(ts) < SPLIT_MIN_N})
    return out


def splits(trades: list, cfg: dict) -> list:
    """나눠 보기 (to find what works): by strategy, coin, side, the 4h vote at the entry (with the trade's side: 같은 방향 /
    보류; 반대 only in the coin-flip twin), the ATR% at the entry against its 30-day point, the KST session of the entry
    (combo.SESSIONS), the exit and the hold time."""
    C = _C()
    gv = {id(t): gates_view(t.get("gates"), t.get("side")) for t in trades}
    vote = lambda t: VOTE_KO.get(((gv[id(t)] or {}).get("vote") or {}).get("with_side"), "기록 없음")          # noqa: E731
    members = [member_ko(m.get("strategy"), m.get("tf")) for m in cfg.get("members") or [] if isinstance(m, dict)]
    sess = lambda t: C.KO_SESSION.get(C.kst_session(t["entry_time"])) if t.get("entry_time") is not None else None   # noqa: E731
    hold = lambda t: _hold_key((t["exit_time"] - t["entry_time"]) if t.get("exit_time") is not None and t.get("entry_time") is not None else None)  # noqa: E731
    return [
        {"id": "strategy", "ko": "매매법", "rows": split_rows(trades, lambda t: member_ko(t.get("strategy_id"), t.get("timeframe")), members)},
        {"id": "coin", "ko": "코인", "rows": split_rows(trades, lambda t: str(t.get("symbol") or "").replace("USDT", "") or None,
                                                       [c.replace("USDT", "") for c in L.COINS])},
        {"id": "side", "ko": "롱·숏", "rows": split_rows(trades, lambda t: SIDE_KO.get(t.get("side")), ["롱", "숏"])},
        {"id": "vote", "ko": "진입 때 4시간 판단", "sub_ko": "판단 4개의 방향이 신호와 같았나 (3개 이상 반대면 진입 안 함)",
         "rows": split_rows(trades, vote, list(VOTE_KO.values()) + ["기록 없음"])},
        {"id": "atr", "ko": "진입 때 변동성", "sub_ko": "신호 봉 ATR% ÷ 지난 30일 80% 위치 (1.0 넘으면 진입 안 함)",
         "rows": split_rows(trades, lambda t: _atr_key(gv[id(t)]), [ko for _t, ko in ATR_BUCKETS] + ["기록 없음"])},
        {"id": "session", "ko": "시간대(한국)", "rows": split_rows(trades, sess, [C.KO_SESSION[s] for s in SESSIONS_ORDER])},
        {"id": "exit", "ko": "청산", "rows": split_rows(trades, lambda t: exit_ko(t.get("exit_reason"), cfg), [exit_ko(r, cfg) for r in ("LOCK", "SL", "TIME")])},
        {"id": "hold", "ko": "보유 시간", "rows": split_rows(trades, hold, [ko for _t, ko in HOLD_BUCKETS])},
    ]


def trades_view(snap: dict, cfg: dict, since: Optional[int], loc: dict, follows: list) -> list:
    """The bot's closed trades, newest first: entry / exit, coin, side, the strategy in words, prices, the exit in words
    (and why: "96봉(48시간) 지남"), net ROE, what the gates read at the entry, and per executor that ever followed this bot
    its part (followed: its own result; not followed while following: why, from its own records; followed another paper
    then: said so)."""
    path = loc["bot"]["path"]
    ex_by = {x["id"]: x for x in loc["execs"]}
    rev = {c["id"]: L.rev_pairs(ex_by[c["id"]]) for c in follows if c["id"] in ex_by}
    live_by = {c["id"]: {str(t["key"]): t for t in ex_by[c["id"]]["record"].get("trades") or []} for c in follows
               if c["id"] in ex_by and ex_by[c["id"]]["record"].get("state") == "ok"}
    out = []
    for t in reversed([t for t in snap["trades"][ACCOUNT] if (t.get("entry_time") or 0) >= int(since or 0)][-TRADES_KEEP:]):
        cells = {}
        for c in follows:
            x = ex_by.get(c["id"])
            if x is None:
                continue
            if x["record"].get("state") != "ok":
                cells[c["id"]] = {"state": "unknown", "why_ko": "실행기 기록을 못 읽음"}
                continue
            lk = rev.get(c["id"], {}).get((LP.norm(path), t["id"]))
            if lk is not None and lk in live_by.get(c["id"], {}):
                lt = live_by[c["id"]][lk]
                cells[c["id"]] = {"state": "matched", "pnl": lt.get("pnl"), "roe": lt.get("roe"), "est": lt.get("est"),
                                  "entry_price": lt.get("entry_price"),
                                  "slip": (lt["side"] * (t["entry_price"] - lt["entry_price"]) / t["entry_price"]) if t.get("entry_price") and lt.get("entry_price") else None}
            elif not L.followed_at(x, path, t.get("entry_time")):
                then = LP.paper_at(x["segs"], t.get("entry_time"))
                other = next((b for b in loc["bots"] if LP.same(b["path"], then)), None)
                name = (other or {}).get("short_ko") or "다른 페이퍼"
                cells[c["id"]] = {"state": "other", "why_ko": f"이때 {x['name_ko']}는 {name}{obj_ko(name)} 따라갔어요"}
            else:
                cells[c["id"]] = L.why_missed(x["record"], t, ACCOUNT)
        g = gates_view(t.get("gates"), t.get("side"))
        out.append({"id": t["id"], "symbol": t["symbol"], "side": t["side"], "strategy": t.get("strategy_id"), "tf": t.get("timeframe"),
                    "member_ko": member_ko(t.get("strategy_id"), t.get("timeframe")), "entry_time": t.get("entry_time"),
                    "exit_time": t.get("exit_time"), "entry_price": t.get("entry_price"), "exit_price": t.get("exit_price"),
                    "reason": t.get("exit_reason"), "reason_ko": exit_ko(t.get("exit_reason"), cfg), "why": t.get("exit_why"),
                    "roe": t.get("roe"), "pnl": t.get("pnl"), "win": (t.get("pnl") or 0) > 0, "lock_roe": t.get("lock_roe"),
                    "hold_ms": (t["exit_time"] - t["entry_time"]) if t.get("exit_time") is not None and t.get("entry_time") is not None else None,
                    "gates": g, "live": cells})
    return out


# ---------------------------------------------------------------- the three answers
def _start(p: dict, now: int, more: Optional[dict], **snap_kw) -> tuple:
    """(loc, head, snap) of an answer; snap None unless the VWAP bot was found readable (the head then says why not)."""
    loc = locate(p, now, more)
    head = head_of(loc, now)
    if loc["state"] != "ok":
        return loc, head, None
    snap = snapshot(loc["bot"]["path"], now, **snap_kw)
    if snap.get("state") != "ok":
        head.update(state=snap.get("state"), reason_ko=snap.get("reason_ko"), reason=snap.get("reason"))
        return loc, head, None
    if not snap["engines"].get(ACCOUNT) and not snap["trades"][ACCOUNT]:
        head.update(state="missing", reason_ko=NO_ACCOUNT_KO)
        return loc, head, None
    return loc, head, snap


def control(p: Optional[dict] = None, now_ms: Optional[int] = None, more: Optional[dict] = None) -> dict:
    """GET /api/v4/livebots/vwap (module docstring)."""
    from . import livetrend as LT                    # the entry pauses by a config's own rules (pause_now, next_pause)
    p = p or L.paths()
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    loc, head, snap = _start(p, now, more, sig_from=now - SIG_SPAN_MS)
    if snap is None:
        return head
    cfg = snap["cfg"] or loc.get("cfg") or {}
    since = since_of(snap)
    fol = followers(loc, snap, now)
    pos = position_view(snap, cfg, now)
    if pos is not None:
        for f in fol:
            q = f.get("position")
            f["pos_state"] = ("same" if q and q.get("key") == pos.get("key") else "other" if q else "none")
    paper = account_view(snap, ACCOUNT, cfg, since)
    try:
        pause = {"now": LT.pause_now(cfg, now), "next": LT.next_pause(cfg, now)}
    except Exception as exc:  # noqa: BLE001  the calendar's own failure: said, never a guess
        pause = {"now": {"paused": None, "ko": "쉬는 시간을 계산하지 못했어요"}, "next": None, "error": f"{type(exc).__name__}: {exc}"[:200]}
    return {**head, "bot": {**head["bot"], **bot_status(snap, now)}, "since_ms": since, "followers": fol,
            "following": [f["id"] for f in fol if f["state"] == "following"], "no_follower_ko": NO_FOLLOWER_KO,
            "rules": rules_view(cfg), "account": {k: paper.get(k) for k in ("state", "wallet", "initial", "change", "n", "wins", "losses", "win_rate", "roe_sum", "pnl", "reason_ko")},
            "position": pos, "picture": picture_view(snap, cfg, now), "pause": pause, "signals": signals_view(snap, now, since, cfg)}


def perf(p: Optional[dict] = None, now_ms: Optional[int] = None, more: Optional[dict] = None) -> dict:
    """GET /api/v4/livebots/vwperf (module docstring)."""
    p = p or L.paths()
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    loc, head, snap = _start(p, now, more)
    if snap is None:
        return head
    cfg = snap["cfg"] or loc.get("cfg") or {}
    since = since_of(snap)
    paper = account_view(snap, ACCOUNT, cfg, since)
    flip = account_view(snap, FLIP, cfg, since)
    fol = followers(loc, snap, now)
    ref = scale_ref()
    ex_by = {x["id"]: x for x in loc["execs"]}
    checks = [checklist(ex_by[f["id"]], loc["bot"]["path"], paper, flip, ref) for f in fol if f["id"] in ex_by]
    mine = [t for t in snap["trades"][ACCOUNT] if (t.get("entry_time") or 0) >= int(since or 0)]
    twin = [t for t in snap["trades"][FLIP] if (t.get("entry_time") or 0) >= int(since or 0)]
    return {**head, "bot": {**head["bot"], **bot_status(snap, now)}, "since_ms": since, "paper": paper, "flip": flip,
            "skill": skill_view(paper, flip), "followers": fol, "checklist": checks, "no_follower_ko": NO_FOLLOWER_KO,
            "scale_ko": SCALE_KO, "honest_ko": SCALE_HONEST_KO, "stop_ko": STOP_KO, "research": research_view(ref, paper, checks),
            "splits": {"paper": splits(mine, cfg), "flip": splits(twin, cfg)}, "split_min_n": SPLIT_MIN_N,
            "trades": trades_view(snap, cfg, since, loc, fol)}


def blocked(p: Optional[dict] = None, now_ms: Optional[int] = None, more: Optional[dict] = None) -> dict:
    """GET /api/v4/livebots/vwblock (module docstring)."""
    more = more or L.paths_more()
    p = p or L.paths()
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    loc, head, snap = _start(p, now, more, filtered=True)
    if snap is None:
        return head
    since = since_of(snap)
    counts = blocked_counts(snap, now, since)
    sig_gates = {}
    for bc, _tf, member, sym, _side, data in snap["filtered"]:
        g = L._j(data).get("gates")
        if isinstance(g, dict):
            sig_gates[(member, sym, L._i(bc))] = gates_view(g, L._i(_side))
    v = read_virtual(more["check_db"], now, since)
    names = {x["id"]: x["name_ko"] for x in loc["execs"]}
    return {**head, "bot": {**head["bot"], **bot_status(snap, now)}, "since_ms": since, "counts": counts,
            "virtual": virtual_view(v, sig_gates, names)}


def register(app, ctx) -> dict:
    from ..app import json_finite

    def key(name: str, p: dict) -> str:
        return name + ":" + json.dumps([p, L.paths_more()], sort_keys=True)

    @app.get("/api/v4/livebots/vwap")
    def get_livebots_vwap():
        """실거래 › VWAP 관제: the VWAP bot, its followers, its rules, its position, every coin's gates now, the pauses and the
        last 48 h of its signals (read-only, 5 s cache)."""
        p = L.paths()
        return L._cached(key("vwap", p), lambda: json_finite(control(p)))

    @app.get("/api/v4/livebots/vwperf")
    def get_livebots_vwperf():
        """실거래 › VWAP 성적: the paper and its coin-flip twin, the followers' checklists, the research's numbers, the splits
        and the trades (read-only, 5 s cache)."""
        p = L.paths()
        return L._cached(key("vwperf", p), lambda: json_finite(perf(p)))

    @app.get("/api/v4/livebots/vwblock")
    def get_livebots_vwblock():
        """실거래 › VWAP 막은 신호: the bot's filtered signals by reason and the watcher's virtual results of them (read-only,
        5 s cache)."""
        p = L.paths()
        return L._cached(key("vwblock", p), lambda: json_finite(blocked(p)))

    return {"routes": ["/api/v4/livebots/vwap", "/api/v4/livebots/vwperf", "/api/v4/livebots/vwblock"], "paths": L.paths}
