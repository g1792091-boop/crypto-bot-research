"""실거래 분석 팀 (owners 10/19: "실거래봇인데 에이전트 팀 분석은 필요없어?" -> "만들어주고 실거래 대시보드 화면 안에").

Four AI members read what the live side recorded and explain it in plain Korean; they never trade. Everything they see is
a packet the code builds from the same readers as the dashboard's 실거래 screen (paperbot/dash/more/livebots.py: the
paper bot's database, both executors' databases, livecheck.db, liveimprove.db, the 5-year reference), read-only. They
have no tools (paperbot/agents/runner.py: Claude Code in print mode, ``--tools ""``, on the owners' subscription login),
no order key, no way to change a setting. What they write lands in their own database (``liveteam.db``), on the 실거래 ›
분석팀 tab and, the conclusion only, as a quiet message in the live bot's private chats.

The members (each one call per meeting, in this order; the lead reads the others):
    방패  리스크 담당   drawdown, losing runs, halts, the light, costs, what the executors did
    저울  통계 담당     is it luck? sample size, the honest band, the 5-year numbers (fitted vs unseen)
    나침반 시장 담당    regime, coin, time of day, side, the macro calendar
    등대  팀장          the conclusion: summary, good, worries, what to watch, at most three ideas to TEST

Meetings (code decides when; ``tick`` runs one due meeting at most):
    loss        the last two closed trades of a live executor both lost (closed within 3 days): once per pair
    checkpoint  the paper account reached 40, 80, 120 ... closed trades: once each (the A+C bot's 40-trade 88% / 82%
                rule only while its 5-year reference is the running config's; 규칙봇 15 has none: checkpoint_rule)
    weekly      Monday from 10:00 KST: the week before (Monday 09:00 to Monday 09:00); no closed trade = a quiet
                line without AI
The fixed rules are never up for discussion (fixed_rules: read from the running configs, the paper bot's and both
executors'; the owners' 10-19 decisions, FIXED, for a config that cannot be read), an idea is only ever a hypothesis
to test in the way the improvement ledger already does (2020-24 then 2025-26, then a shadow bot): the owners decide, by
hand.

Budget (the owners' Claude plan, shared with their chats): LIVETEAM_BUDGET="day=12,week=40,tokens_day=900000"
(calls per KST day, calls per 7 KST days, tokens per KST day). A meeting starts only when all its calls fit, each call
is charged at its worst case first (runner.call_charge) and at what it used after.

    python -m paperbot.liveteam tick [--dry-run]          the timer (deploy/paperbot-liveteam.timer, installed off)
    python -m paperbot.liveteam run weekly|loss|checkpoint [--force] [--dry-run]
    python -m paperbot.liveteam preview weekly|loss|checkpoint     the packet and the prompts, no AI call
    python -m paperbot.liveteam status
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sqlite3
import sys
import time
from typing import Any, Callable, Optional

from .notify import INFO

DB_DEFAULT = "/var/lib/paperbot/liveteam.db"
DB_ENV = "PAPERBOT_LIVETEAM_DB"
BUDGET_ENV = "LIVETEAM_BUDGET"
MODEL_ENV = "LIVETEAM_MODEL"
BUDGET_DEFAULT = {"day": 12, "week": 40, "tokens_day": 900_000}
MODEL_DEFAULT = "sonnet"
MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000
KST_MS = 9 * HOUR
CHECK_EVERY = 40                       # the owners' 40-trade decision, then every 40 more
LOSS_FRESH_MS = 3 * DAY                # a losing pair older than this when the team is turned on is left alone
WEEKLY_HOUR = 10                       # Monday from 10:00 KST (after liveimprove's 09:30 scorecard)
TEXT_MAX = 400                         # characters kept of one line a member wrote
LIST_MAX = 6
IDEAS_MAX = 3
SMALL_N = 20
DASH_HINT = "대시보드 › 실거래 › 분석팀"

ROLES = {
    "risk": {"name": "방패", "title": "리스크 담당",
             "focus": "잔고와 낙폭, 연속 손실, 실행기 멈춤·비상 정지, 실거래가 페이퍼를 제대로 따라갔는지(신호등은 켜져 있을 때만), "
                      "수수료·미끄러짐 같은 비용"},
    "stats": {"name": "저울", "title": "통계 담당",
              "focus": "이게 우연인지 아닌지. 거래 수가 충분한지, 본전 승률보다 높은지, 이 봇의 5년 기준표가 있으면 현실 기대 범위"
                       "(처음 보는 기간) 안인지와 맞춘 숫자(낙관)와 비교해 어떤지, 없으면 시작 근거와 비교해 어떤지. 다른 사람이 성급하게 "
                       "결론 내면 반박하는 역할"},
    "market": {"name": "나침반", "title": "시장 담당",
               "focus": "BTC 4시간 장세(강상승·약상승·강하락·약하락·횡보), 코인, 한국 시간대, 롱/숏, 다가오는 미국 경제 발표"},
    "lead": {"name": "등대", "title": "팀장",
             "focus": "팀원 셋의 말을 모아 두 분이 1분 안에 읽을 결론을 쓰는 역할. 팀원끼리 다르면 어느 쪽이 숫자에 맞는지 밝힘"},
}
KIND_ROLES = {"weekly": ("risk", "stats", "market", "lead"), "loss": ("risk", "stats", "lead"),
              "checkpoint": ("risk", "stats", "market", "lead")}
KIND_KO = {"weekly": "주간 보고", "loss": "손실 회의", "checkpoint": "판단 회의"}
VERDICTS = ("정상 범위", "지켜보기", "주의")
# The owners' fixed rules as the running configs say them (fixed_rules: the paper bot's config, both executors' configs).
# What a config that cannot be read would have said comes from the owners' 10-19 decisions for 규칙봇 15 (from 10-20):
FIXED_PAPER = ("매매법 15개(규칙봇 기본값, 30분·1시간)", "BTC 40배 · 나머지 30배", "증거금 잔고의 30%", "한 번에 포지션 하나",
               "시장가 진입", "손절 순ROE -50%(수수료·슬리피지 포함: 40배 가격 1.11%, 30배 가격 1.53%)",
               "계단 익절(순ROE 11%에서 10% 잠금, 15%에서 12%, 20%에서 17%, 그 뒤 5%마다 (닿은 순ROE - 3%))",
               "빠른 청산: 같은 매매법이 반대 신호를 내면 바로 청산(첫 잠금 전까지만)",
               "추격 진입 막기 4개 매매법(롱은 7일 범위 위 20%·24시간 고점 쪽 10% 안이면, 숏은 아래쪽이면 진입 안 함)",
               "코인 6개(BTC ETH SOL DOGE LTC BCH)", "한국 시간 주말 진입 없음", "미국 경제 발표 앞뒤 30분 진입 없음",
               "나스닥 개장 뒤 30분 진입 없음")
FIXED_EXEC = ("거래소에 거는 손절", "연패·낙폭으로 저절로 멈추지 않음(비상 정지 파일 /var/lib/paperbot/STOP으로만 멈춤)",
              "손절 한 번 최대 잔고의 35%", "신호등 없음(실거래는 페이퍼의 모든 진입을 따라감)")
FIXED = FIXED_PAPER + FIXED_EXEC
# what the owners knew when they started a bot without a 5-year reference (keyed by its config name; its guide)
START_BASIS = {"규칙봇 15": ("docs/live15-start-ko.md '근거와 한계': 규칙봇의 지난 2주 실제 진입을 새 규칙으로 다시 판정하면 58승 4패(94%), "
                            "평일 하루 6.2번 진입, 최대 낙폭 20%(증거금 40%로 계산). 이 2주는 15개를 고를 때 쓴 바로 그 기간이라 앞으로는 "
                            "더 낮을 가능성이 큼. 같은 장에서 동전 던지기로 들어가도 75% 이김. 본전 승률 약 86%(복리) / 82~83%(단순 합계). "
                            "두 분은 첫 1~2주 페이퍼 승률을 이 숫자들과 비교해 판단")}
HOW_RARE_OLD = "현실 숫자(2025-26)로 2연패는 거래 1,000번에 약 47번, 3연패는 약 9번 나왔습니다(5년 기준표 streaks)"
HOW_RARE_NONE = "이 봇은 5년 기준표가 없어 연패가 얼마나 드문지 정한 숫자가 없습니다(페이퍼 승률과 본전 승률로만 봅니다)"
CHECK_RULE_OLD = "페이퍼 거래 40번에서 두 분이 판단: 88% 이상 금액 늘리기 검토 · 82~88% 지켜보기 · 82% 미만 멈추고 다시 생각"
CHECK_RULE_NONE = ("이 봇에는 40번 판단 기준(88%/82%)이 없음(그 숫자는 지난 봇의 5년 기준표로 정한 것). 두 분이 페이퍼 승률을 "
                   "본전 승률(bot.break_even)과 시작 근거(bot.start_basis)에 비교해 판단")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    key TEXT NOT NULL UNIQUE,          -- weekly:<Monday, YYYY-MM-DD> | loss:<the pair> | checkpoint:40
    title TEXT NOT NULL,
    started_ts INTEGER NOT NULL,
    finished_ts INTEGER,
    state TEXT NOT NULL,               -- running | done | failed | quiet
    why TEXT,                          -- why it was held, or why it failed
    packet TEXT,                       -- the facts the members read (JSON)
    headline TEXT,
    verdict TEXT,
    result TEXT,                       -- the lead's answer (JSON)
    sent INTEGER,                      -- 1 sent, 0 not sent, NULL no message
    calls INTEGER NOT NULL DEFAULT 0,
    tokens INTEGER NOT NULL DEFAULT 0,
    dry INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    ts INTEGER NOT NULL,
    text TEXT NOT NULL,                -- the member's answer as shown (headline and points)
    data TEXT,                         -- the member's JSON
    model TEXT,
    tokens INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
CREATE TABLE IF NOT EXISTS ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    idea TEXT NOT NULL,
    why TEXT,
    test TEXT,
    status TEXT NOT NULL DEFAULT '제안'  -- the owners decide what happens next (liveimprove's ledger, by hand)
);
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    day TEXT NOT NULL,                 -- KST date
    meeting INTEGER,
    role TEXT,
    calls INTEGER NOT NULL,
    tokens INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS state (k TEXT PRIMARY KEY, ts INTEGER NOT NULL, data TEXT);
"""


# ---------------------------------------------------------------- small helpers
def kst_date(ms: int) -> str:
    return _dt.datetime.fromtimestamp((int(ms) + KST_MS) / 1000, _dt.timezone.utc).strftime("%Y-%m-%d")


def kst_text(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    return _dt.datetime.fromtimestamp((int(ms) + KST_MS) / 1000, _dt.timezone.utc).strftime("%m-%d %H:%M")


def monday_09(ms: int) -> int:
    """09:00 KST of the Monday of the KST week ``ms`` is in."""
    day = (int(ms) + KST_MS) // DAY
    dow = (day + 3) % 7                                    # Monday 0 .. Sunday 6 (day 0 was a Thursday)
    return (day - dow) * DAY - KST_MS + 9 * HOUR


def parse_budget(raw: Optional[str]) -> dict:
    """LIVETEAM_BUDGET "day=12,week=40,tokens_day=900000" (any subset); a bad part raises ValueError."""
    out = dict(BUDGET_DEFAULT)
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        k, _, v = part.partition("=")
        k = k.strip()
        if k not in out or not v.strip().isdigit():
            raise ValueError(f"{BUDGET_ENV}: '{part}' (쓸 수 있는 것: day=정수, week=정수, tokens_day=정수)")
        out[k] = int(v)
    return out


def _clip(x: Any, n: int = TEXT_MAX) -> str:
    s = " ".join(str(x).split()) if x is not None else ""
    return s if len(s) <= n else s[: n - 1] + "…"


def _list(x: Any, n: int = LIST_MAX) -> list:
    if isinstance(x, str):
        x = [x]
    return [_clip(v) for v in (x or []) if isinstance(v, (str, int, float)) and str(v).strip()][:n] if isinstance(x, list) else []


def connect(path: str) -> sqlite3.Connection:
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.executescript(SCHEMA)
    return conn


def get_state(conn, k: str) -> Optional[dict]:
    r = conn.execute("SELECT data FROM state WHERE k = ?", (k,)).fetchone()
    try:
        return json.loads(r[0]) if r and r[0] else None
    except ValueError:
        return None


def put_state(conn, k: str, now: int, data: dict) -> None:
    conn.execute("INSERT OR REPLACE INTO state VALUES (?,?,?)", (k, int(now), json.dumps(data, ensure_ascii=False, default=str)))
    conn.commit()


# ---------------------------------------------------------------- the running bot (its configs, read-only)
def bot_world(p: Optional[dict] = None) -> dict:
    """The configs the live side runs, read-only: the paper bot's (its own ``combo_run`` record, else the config file the
    live side runs: livecheck.combo_config), both executors' (livecheck.load_executors: plain JSON, never a key file; the
    dashboard's paths) and why the 5-year reference does not apply when it was made for another config
    (livecheck.usable_expected; '' = it applies)."""
    from . import livecheck as LC
    from .dash.more import livebots as L
    p = p or L.paths()
    conn = LC.open_ro(p.get("paper") or "")
    try:
        cfg, _where = LC.combo_config(LC.Sources(paper_db=p.get("paper") or LC.PAPER_DB), conn)
    finally:
        if conn is not None:
            conn.close()
    specs = tuple((name, p.get(f"{name}_config") or path, unit, p.get(f"{name}_db") or db, n, share)
                  for name, path, unit, db, n, share in LC.EXECUTORS)
    _exp, ref_ko = LC.usable_expected(LC.Sources())
    out = {"config": cfg, "infos": LC.load_executors(specs), "ref_ko": ref_ko}
    # owners 10-19 (docs/live15-mexc-ko.md): a second paper bot (규칙봇 15 at -35 %) and which executor follows which:
    # the paper database each executor's last start recorded (livecheck.PaperSet, paperbot/livepapers.py)
    second = second_paper(p.get("paper") or LC.PAPER_DB, out["infos"])
    if second:
        out["second"] = second
    return out


COMBO2_CONFIG_ENV, COMBO2_CONFIG = "PAPERBOT_LIVE_COMBO2_CONFIG", "/etc/paperbot/combo-mexc.json"


def second_paper(main: str, infos: list) -> Optional[dict]:
    """{"config", "label", "first_label", "follows": {executor: its paper bot's short name}} when an executor follows
    another paper bot than ``main`` (its last start recorded it), else None."""
    from . import livecheck as LC
    from . import livepapers as LP
    ps = LC.PaperSet(main)
    cur = {}
    for ex in infos:
        c = LC.open_ro(ex.db)
        try:
            cur[ex.label] = LP.current(ps.segs(ex, c))
        finally:
            if c is not None:
                c.close()
    other = next((p for p in cur.values() if not LP.same(p, main)), None)
    if other is None:
        return None
    c2 = LC.open_ro(other)
    try:
        cfg2, _w = LC.combo_config(LC.Sources(paper_db=other, combo_config=os.environ.get(COMBO2_CONFIG_ENV) or COMBO2_CONFIG), c2)
    finally:
        if c2 is not None:
            c2.close()
    names = {LP.norm(main): LC.paper_name(main), LP.norm(other): LC.paper_name(other)}
    fol = lambda path: "·".join(k for k, v in cur.items() if LP.same(v, path))           # noqa: E731
    return {"config": cfg2, "label": f"{names[LP.norm(other)]} ({fol(other)}가 따라감)",
            "first_label": f"{names[LP.norm(main)]}" + (f" ({fol(main)}가 따라감)" if fol(main) else ""),
            "follows": {k: names.get(LP.norm(v), v) for k, v in cur.items()}}


def _combo(cfg: Optional[dict]):
    """paperbot.combo.ComboConfig of a config dict (a record may lack the paths), None when it cannot be read."""
    if not isinstance(cfg, dict):
        return None
    from . import combo as C
    try:
        return C.ComboConfig.from_dict({"paper_db": "", "db": "", **cfg, "members": list(cfg.get("members") or [])})
    except Exception:  # noqa: BLE001  an unreadable config: the owners' decisions are said instead
        return None


def _paper_rules(cfg: Optional[dict]) -> Optional[list]:
    c = _combo(cfg)
    if c is None or c.ladder_spec is None:
        return None
    from . import combo as C
    try:
        stop = C.stop_text(c)
    except Exception:  # noqa: BLE001
        return None
    members = [m for m in (cfg.get("members") or [])]
    nc = sum(1 for m in members if isinstance(m, dict) and m.get("no_chase"))
    out = [f"매매법 {len(members)}개", f"BTC {c.lev_of('BTCUSDT')}배 · 나머지 {c.lev_of('ETHUSDT')}배",
           "증거금 " + ("배수%" if c.margin == "leverage" else f"잔고의 {float(c.margin):.0%}"), "한 번에 포지션 하나",
           "시장가 진입", f"손절 {stop}", f"계단 익절({c.ladder_spec.describe()})",
           f"빠른 청산: {C.KO_EARLY.get(c.early_exit, c.early_exit)}"
           + ("(첫 잠금 전까지만)" if c.early_exit and c.early_exit_until_lock else "")]
    if nc:
        out.append(f"추격 진입 막기 {nc}개 매매법(" + C.CHASE_KO.split("(", 1)[1])
    out.append(f"코인 {len(c.symbols)}개({' '.join(s.replace('USDT', '') for s in c.symbols)})")
    if c.no_weekend:
        out.append("한국 시간 주말 진입 없음")
    if c.macro_blackout_min:
        out.append(f"미국 경제 발표 앞뒤 {c.macro_blackout_min}분 진입 없음")
    if c.us_open_pause_min:
        out.append(f"나스닥 개장 뒤 {c.us_open_pause_min}분 진입 없음")
    return out


def _exec_rules(infos: list) -> list:
    out = ["거래소에 거는 손절"]
    streaks = sorted({e.max_streak for e in infos if e.max_streak})
    dds = sorted({e.max_dd for e in infos if e.max_dd is not None})
    kill = infos[0].kill_file
    if not streaks and not dds:
        out.append(f"연패·낙폭으로 저절로 멈추지 않음(비상 정지 파일 {kill}으로만 멈춤)")
    else:
        out.append(" · ".join(([f"{'/'.join(map(str, streaks))}연패 멈춤"] if streaks else [])
                              + ([f"최고점에서 {'/'.join(f'{d:.0%}' for d in dds)} 빠지면 멈춤"] if dds else [])
                              + [f"비상 정지 파일 {kill}"]))
    losses = sorted({e.max_loss for e in infos if e.max_loss is not None})
    if losses:
        out.append(f"손절 한 번 최대 잔고의 {'/'.join(f'{x:.0%}' for x in losses)}")
    lit = [e for e in infos if e.light_on]
    if not lit:
        out.append("신호등 없음(실거래는 페이퍼의 모든 진입을 따라감)")
    for e in lit:
        out.append(f"신호등: {e.label}는 페이퍼 최근 {e.light_n}번 중 {e.light_min:.0%} 이상 이겼을 때만 새 진입을 따라감")
    money = [f"{e.label} ${e.budget:,.0f}" for e in infos if e.budget]
    if money:
        out.append("실거래 금액 " + " · ".join(money))
    return out


def fixed_rules(cfg: Optional[dict], infos: Optional[list], second: Optional[dict] = None) -> list:
    """The owners' fixed rules of the live side as the running configs say them (the paper bot's config, the executors'
    configs that could be read); a part whose config cannot be read: the owners' decisions (FIXED_PAPER / FIXED_EXEC).
    ``second`` (bot_world, owners 10-19): the second paper bot's rules where they differ from the first's (its stop), and
    which executor follows which paper bot."""
    readable = [e for e in (infos or []) if not e.problem]
    out = list(_paper_rules(cfg) or FIXED_PAPER)
    if second:
        mine = _paper_rules(second.get("config")) or []
        diff = [r for r in mine if r not in out and not r.startswith("매매법 ")]
        out.append(f"두 번째 페이퍼 봇 {second.get('label')}: " + (" · ".join(diff) if diff else "규칙을 못 읽음")
                   + " (나머지 규칙은 첫 번째와 같음)")
        out.append("따라가는 페이퍼: " + " · ".join(f"{k}는 {v}" for k, v in (second.get("follows") or {}).items()))
    return out + (_exec_rules(readable) if readable else list(FIXED_EXEC))


def bot_facts(world: Optional[dict]) -> dict:
    """The bot itself: its name, its strategies, its break-even win rate when the stop and the first lock are fixed net
    ROEs (a -50% stop and a +10% first lock: 50 / 60 = 83%, plain sum), whether a 5-year reference applies, and what
    the owners started it on (START_BASIS)."""
    w = world or {}
    cfg = w.get("config") if isinstance(w.get("config"), dict) else {}
    c = _combo(cfg) if cfg else None
    be = None
    if c is not None and c.stop_mode == "roe" and c.ladder_spec is not None:
        s, f = float(c.stop["roe"]), float(c.ladder_spec.first_lock)
        be = round(s / (s + f), 3)
    name = (cfg or {}).get("name") or None
    out = {"name": name or "(설정 이름 없음)", "strategies": len(cfg.get("members") or []) or None,
           "reference": w.get("ref_ko") or "5년 기준표 있음(expect)",
           "break_even": be, "break_even_words": ("본전 승률 = 이길 때 첫 잠금만큼, 질 때 손절만큼일 때 본전이 되는 승률(단순 합계, "
                                                  "수수료 포함 순ROE 기준; 복리로는 조금 더 높음)") if be is not None else None}
    if name in START_BASIS:
        out["start_basis"] = START_BASIS[name]
    sec = w.get("second") if isinstance(w.get("second"), dict) else None
    c2 = _combo(sec.get("config")) if sec else None
    if c2 is not None and c2.stop_mode == "roe" and c2.ladder_spec is not None:
        s2, f2 = float(c2.stop["roe"]), float(c2.ladder_spec.first_lock)
        out["second"] = {"name": (sec.get("config") or {}).get("name"), "label": sec.get("label"), "break_even": round(s2 / (s2 + f2), 3),
                         "why": "손절만 다른 같은 봇: 손절이 좁으면 지는 거래의 손실이 작고 지는 거래는 늘어요(본전 승률이 낮아짐)"}
    return out


# ---------------------------------------------------------------- the facts (the dashboard's own readers)
def sources(now: int, p: Optional[dict] = None) -> dict:
    """Everything the 실거래 screen shows, read once (read-only): the summary, 순위, 지도, 비용, 지금, 일정, 거래, the loss cards
    and the watcher's alarms."""
    from .dash.more import livebots as L
    p = p or L.paths()
    more = L.paths_more()
    out = {"now": now}
    for name, fn in (("summary", lambda: L.build(p, now)), ("rank", lambda: L.rank(p, now)), ("map", lambda: L.map_view(p, now)),
                     ("costs", lambda: L.costs(p, now)), ("whynow", lambda: L.whynow(p, now)), ("calendar", lambda: L.calendar(p, now)),
                     ("trades", lambda: L.trade_rows(p, now, more)), ("cards", lambda: L.read_cards(more["check_db"], now)),
                     ("safety", lambda: L.safety(p, now, more=more))):
        try:
            out[name] = fn()
        except Exception as exc:  # noqa: BLE001  one unreadable source is said, never fatal
            out[name] = {"state": "error", "reason": f"{type(exc).__name__}: {exc}"}
    try:
        out["bot"] = bot_world(p)
    except Exception as exc:  # noqa: BLE001  the rules then come from the owners' decisions (FIXED)
        out["bot"] = {"config": None, "infos": [], "ref_ko": "", "error": f"{type(exc).__name__}: {exc}"}
    return out


def _acct_line(a: dict) -> dict:
    st = a.get("stats") or {}
    return {"id": a.get("id"), "name": a.get("label_ko") or a.get("name_ko"),
            "kind": "페이퍼(연습)" if a.get("kind") == "paper" else "실거래(진짜 돈)",
            "state": a.get("state"), "balance": a.get("balance"), "start": a.get("initial"), "halted": a.get("halted"),
            "halt_reason": a.get("halt_reason") or None, "losing_run": a.get("consecutive_losses"),
            "trades": st.get("trades"), "wins": st.get("wins"), "pnl": st.get("pnl"), "today": a.get("today"),
            "reason": a.get("reason_ko") if a.get("state") != "ok" else None}


def _trade_line(r: dict) -> dict:
    live = {}
    for ex, c in (r.get("live") or {}).items():
        if not isinstance(c, dict):
            continue
        live[ex] = ({"followed": True, "pnl": c.get("pnl"), "slip": c.get("slip")} if c.get("state") == "matched"
                    else {"followed": False, "why": c.get("why_ko") or c.get("state")})
    card = r.get("card") or {}
    return {"time_kst": kst_text(r.get("entry_time")), "coin": r.get("symbol"), "side": "롱" if (r.get("side") or 0) > 0 else "숏",
            "strategy": r.get("strategy_id"), "tf": r.get("timeframe"), "roe": r.get("roe"), "pnl": r.get("pnl"),
            "exit": r.get("reason_ko"), "minutes": round((r["exit_time"] - r["entry_time"]) / MIN) if r.get("exit_time") and r.get("entry_time") else None,
            "loss_card": card.get("label") if card else None, "live": live}


def facts(src: dict, kind: str, window: Optional[tuple] = None, focus: Optional[dict] = None) -> dict:
    """The packet every member of one meeting reads: numbers only, with their meaning in words."""
    now = src["now"]
    summ = src.get("summary") or {}
    accts = [_acct_line(a) for a in summ.get("accts") or []]
    mp = src.get("map") or {}
    band = (mp.get("band") or {})
    rank = src.get("rank") or {}
    strategies = []
    for r in rank.get("rows") or []:
        pp, sg, bt, sc = r.get("paper") or {}, (r.get("sig") or {}).get("week") or {}, r.get("bt") or {}, r.get("status") or {}
        if not (pp.get("n") or sg.get("signals") or r.get("open")):
            continue
        strategies.append({"strategy": r.get("strategy"), "type": bt.get("type_ko"), "in_config": r.get("in_config"),
                           "paper_n": pp.get("n"), "paper_wins": pp.get("wins"), "paper_pnl": pp.get("pnl"), "status": sc.get("status"),
                           "fit_win": bt.get("win"), "honest_win": bt.get("honest_win"), "week_signals": sg.get("signals"),
                           "week_entered": sg.get("entered"), "holding_now": bool(r.get("open"))})
    cuts = {}
    for cut, rows in (mp.get("cuts") or {}).items():
        cuts[cut] = [{"label": x.get("label"), "n": x.get("n"), "win": x.get("win"), "bt_win": x.get("bt_win"), "status": x.get("status")}
                     for x in rows if x.get("n")]
    costs = {}
    for ex, c in ((src.get("costs") or {}).get("accts") or {}).items():
        costs[ex] = ({k: c.get(k) for k in ("n", "matched", "slip_avg", "fees", "funding", "diff_total", "roe_gap_avg", "est_n")}
                     | {"missed": [{"why": m.get("ko"), "n": m.get("n")} for m in c.get("missed") or []]}) if c.get("state") == "ok" \
            else {"state": c.get("state"), "reason": c.get("reason_ko")}
    wn = src.get("whynow") or {}
    cal = src.get("calendar") or {}
    world = src.get("bot") or {}
    ref_ko = world.get("ref_ko") or ""
    words = ("fit = 5년에 맞춘 숫자(낙관), honest = 2020-24에만 맞춘 쌍둥이가 처음 본 2025-26에서 낸 숫자(현실), "
             "break_even = 본전 승률. p_under_honest = 현실 승률대로라면 지금보다 적게 이길 확률(작을수록 현실보다 못함)")
    if ref_ko:
        words = (f"{ref_ko}. 이 봇은 5년 숫자(fit·honest)가 없습니다: 지난 봇 숫자를 쓰지 말고, 페이퍼 승률을 본전 승률"
                 "(bot.break_even)과 시작 근거(bot.start_basis)에 비교합니다")
    out = {"meeting": KIND_KO.get(kind, kind), "now_kst": kst_text(now),
           "fixed_rules": fixed_rules(world.get("config"), world.get("infos"), world.get("second")), "bot": bot_facts(world),
           "accounts": accts,
           "expect": {"fit_win": band.get("fit"), "honest_win": band.get("honest"), "break_even": band.get("break_even"),
                      "so_far": {k: {"n": v.get("n"), "wins": v.get("wins"), "rate": v.get("rate"), "p_under_honest": v.get("p_honest")}
                                 for k, v in (band.get("accounts") or {}).items()},
                      "words": words},
           "strategies": strategies[:30], "cuts": cuts, "costs": costs,
           "now": {"head": wn.get("head_ko"), "blocked": [i.get("ko") for i in wn.get("items") or [] if i.get("ok") is False]},
           "next_releases": [{"when_kst": kst_text(x.get("ts")), "what": x.get("kind_ko")} for x in cal.get("items") or []
                             if x.get("when") in ("now", "soon", "later")][:6],
           "checkpoint_rule": CHECK_RULE_NONE if ref_ko else CHECK_RULE_OLD}
    rows = ((src.get("trades") or {}).get("accts") or {}).get("paper") or {}
    prow = rows.get("rows") or [] if isinstance(rows, dict) else []
    if window:
        a, b = window
        out["window_kst"] = [kst_text(a), kst_text(b)]
        out["trades"] = [_trade_line(r) for r in prow if r.get("exit_time") is not None and a <= r["exit_time"] < b][:60]
        rows2 = ((src.get("trades") or {}).get("accts") or {}).get("paper2")
        if isinstance(rows2, dict) and rows2.get("rows") is not None:    # the second paper bot's (its own executors' cells)
            out["trades_paper2"] = {"label": rows2.get("label_ko"), "rows": [_trade_line(r) for r in rows2["rows"]
                                    if r.get("exit_time") is not None and a <= r["exit_time"] < b][:60]}
        cards = (src.get("cards") or {}).get("cards") or []
        out["loss_cards"] = [{"label": c.get("label"), "strategy": c.get("strategy"), "tf": c.get("tf"), "coin": c.get("symbol"),
                              "roe": c.get("roe"), "regime": c.get("reg5_ko"), "noise": (c.get("noise") or {}).get("state"),
                              "text": _clip(c.get("text") or "", 300)}
                             for c in cards if c.get("exit_time") is not None and a <= int(c["exit_time"]) < b][:12]
        alarms = []
        for x in (((src.get("safety") or {}).get("checks") or {}).get("watch") or {}).get("items") or []:
            if x.get("ts") is not None and a <= x["ts"] < b:
                alarms.append({"when_kst": kst_text(x["ts"]), "level": x.get("level_ko"), "what": x.get("title")})
        out["alarms"] = alarms[:20]
    if focus:
        out["focus"] = focus
    return out


# ---------------------------------------------------------------- when a meeting is due
def due_loss(src: dict) -> Optional[tuple]:
    """(key, focus) when a live executor's last two closed trades both lost, closed within LOSS_FRESH_MS; one meeting per
    pair (by the paper trades they followed, so both executors losing the same pair is one meeting)."""
    now = src["now"]
    tr = (src.get("trades") or {}).get("accts") or {}
    for ex in ("bybit", "mexc"):
        a = tr.get(ex) or {}
        rows = [r for r in (a.get("rows") or []) if r.get("exit_time") is not None and r.get("pnl") is not None]
        rows.sort(key=lambda r: (r["exit_time"], str(r.get("key"))))
        if len(rows) < 2:
            continue
        last2 = rows[-2:]
        if all(r["pnl"] <= 0 for r in last2) and now - last2[-1]["exit_time"] <= LOSS_FRESH_MS:
            ids = [str((r.get("paper") or {}).get("id") or r.get("key")) for r in last2]
            focus = {"executor": ex, "losses": [{"coin": r.get("symbol"), "side": "롱" if (r.get("side") or 0) > 0 else "숏",
                                                  "strategy": r.get("strategy_id"), "tf": r.get("timeframe"), "pnl": r.get("pnl"),
                                                  "roe": r.get("roe"), "paper_roe": (r.get("paper") or {}).get("roe"),
                                                  "exit": r.get("reason_ko"), "closed_kst": kst_text(r.get("exit_time")),
                                                  "loss_card": (r.get("card") or {}).get("label")} for r in last2],
                     "how_rare": HOW_RARE_NONE if (src.get("bot") or {}).get("ref_ko") else HOW_RARE_OLD}
            return "loss:" + "+".join(sorted(ids)), focus
    return None


def due_checkpoint(src: dict) -> Optional[tuple]:
    rows = (((src.get("trades") or {}).get("accts") or {}).get("paper") or {})
    n = rows.get("n") if isinstance(rows, dict) else None
    if not n or n < CHECK_EVERY:
        return None
    k = (int(n) // CHECK_EVERY) * CHECK_EVERY
    pr = [r for r in (rows.get("rows") or []) if r.get("pnl") is not None]
    wins = sum(1 for r in pr[:k] if r["pnl"] > 0) if len(pr) >= k else None
    return f"checkpoint:{k}", {"paper_closed": n, "milestone": k,
                               "last_k_wins": wins, "last_k_rate": wins / k if wins is not None else None}


def due_weekly(src: dict) -> Optional[tuple]:
    now = src["now"]
    m9 = monday_09(now)
    if now < m9 + (WEEKLY_HOUR - 9) * HOUR:
        return None
    return f"weekly:{kst_date(m9)}", {"window": [m9 - 7 * DAY, m9]}


# ---------------------------------------------------------------- the members
def system_prompt(role: str) -> str:
    r = ROLES[role]
    common = (f"당신은 두 분(코딩과 통계를 모르는 한국인 운영자)의 암호화폐 실거래 봇을 지켜보는 '실거래 분석 팀'의 {r['title']} "
              f"'{r['name']}'입니다. 맡은 것: {r['focus']}.\n\n"
              "지킬 것:\n"
              "1. 읽기만 합니다. 매매 권한이 없습니다. 진입·청산·건너뛰기·크기·레버리지·코인을 바꾸라는 말은 하지 않습니다.\n"
              "2. 고정 규칙(fixed_rules)은 두 분이 정한 것이라 바꾸자고 하지 않습니다.\n"
              "3. 패킷(JSON)에 있는 숫자만 씁니다. 없는 숫자는 '자료 없음'이라고 씁니다. 추측한 숫자를 만들지 않습니다.\n"
              f"4. 거래가 {SMALL_N}번보다 적으면 결론을 내리지 말고 '아직 우연이 큰 단계'라고 분명히 씁니다.\n"
              "5. 5년 기준표가 있을 때만 숫자 둘을 구분해 씁니다: fit(맞춘 숫자, 낙관)과 honest(처음 보는 기간, 현실). 기준표가 없다고 "
              "적혀 있으면(bot.reference) 5년 숫자를 만들거나 지난 봇 숫자를 빌려 오지 않고, 본전 승률(break_even)과 시작 근거"
              "(start_basis)에 비교합니다.\n"
              "6. 페이퍼(연습 돈)와 실거래(진짜 돈)를 섞지 않습니다.\n"
              "7. 쉬운 한국어로, 짧게. 전문용어는 풀어서. 매매법은 코드 그대로 부릅니다(화면이 이름으로 바꿔 보여줍니다).\n")
    if role == "lead":
        return common + (
            "8. 팀원들의 말(team)을 읽고, 숫자와 맞지 않는 말은 고칩니다. 아이디어는 '시험해 볼 가설'로만 씁니다: 무엇을 2020-24 자료로 "
            "고르고 2025-26 자료로 한 번 확인할지, 또는 그림자 봇으로 볼지. 채택은 두 분이 정해진 순서로만 합니다.\n\n"
            "답은 JSON 하나만: {\"headline\": \"한 줄 결론\", \"verdict\": \"정상 범위|지켜보기|주의\", \"summary\": [\"3~5줄\"], "
            "\"good\": [\"잘된 점\"], \"worries\": [\"걱정되는 점\"], \"watch_next\": [\"다음에 볼 것\"], "
            "\"ideas\": [{\"idea\": \"가설\", \"why\": \"근거 숫자\", \"test\": \"시험 방법\"}] (최대 3개, 없으면 [])}")
    return common + ("\n답은 JSON 하나만: {\"headline\": \"한 줄\", \"points\": [\"2~4줄, 숫자와 함께\"], "
                     "\"worry\": \"가장 걱정되는 한 가지 또는 null\", \"luck\": \"이게 우연일 수 있는 정도를 한 줄로\"}")


def instruction(role: str, kind: str) -> str:
    return (f"{KIND_KO.get(kind, kind)} 회의입니다. 표준입력의 JSON 패킷(facts: 사실, team: 앞 팀원들의 말)을 읽고 "
            f"'{ROLES[role]['name']}'({ROLES[role]['title']})로서 정해진 JSON 하나만 답하세요.")


def member_text(role: str, data: Optional[dict], raw: str) -> str:
    if not isinstance(data, dict):
        return _clip(raw, 1200)
    if role == "lead":
        lines = [_clip(data.get("headline"))] + [f"· {x}" for x in _list(data.get("summary"))]
        return "\n".join(x for x in lines if x)
    lines = [_clip(data.get("headline"))] + [f"· {x}" for x in _list(data.get("points"), 4)]
    if data.get("worry"):
        lines.append(f"걱정: {_clip(data['worry'])}")
    if data.get("luck"):
        lines.append(f"우연일 정도: {_clip(data['luck'])}")
    return "\n".join(x for x in lines if x)


def lead_result(data: Optional[dict]) -> dict:
    d = data if isinstance(data, dict) else {}
    ideas = []
    for i in (d.get("ideas") or [])[:IDEAS_MAX] if isinstance(d.get("ideas"), list) else []:
        if isinstance(i, dict) and str(i.get("idea") or "").strip():
            ideas.append({"idea": _clip(i.get("idea")), "why": _clip(i.get("why")), "test": _clip(i.get("test"))})
    v = d.get("verdict") if d.get("verdict") in VERDICTS else "지켜보기"
    return {"headline": _clip(d.get("headline")) or "(팀장 결론 없음)", "verdict": v, "summary": _list(d.get("summary")),
            "good": _list(d.get("good")), "worries": _list(d.get("worries")), "watch_next": _list(d.get("watch_next")), "ideas": ideas}


# ---------------------------------------------------------------- budget
def used(conn, now: int) -> dict:
    day = kst_date(now)
    d = conn.execute("SELECT COALESCE(SUM(calls),0), COALESCE(SUM(tokens),0) FROM usage WHERE day = ?", (day,)).fetchone()
    w = conn.execute("SELECT COALESCE(SUM(calls),0) FROM usage WHERE ts >= ?", (now - 7 * DAY,)).fetchone()
    return {"day_calls": int(d[0]), "day_tokens": int(d[1]), "week_calls": int(w[0])}


def fits(conn, now: int, budget: dict, calls: int, tokens: int) -> Optional[str]:
    """None when ``calls`` more calls of at most ``tokens`` each fit the budget, else why not (in words)."""
    u = used(conn, now)
    if u["day_calls"] + calls > budget["day"]:
        return f"오늘 AI 호출 한도({budget['day']}번) 안에 들어가지 않아 다음으로 미룹니다"
    if u["week_calls"] + calls > budget["week"]:
        return f"최근 7일 AI 호출 한도({budget['week']}번) 안에 들어가지 않아 다음으로 미룹니다"
    if u["day_tokens"] + calls * tokens > budget["tokens_day"]:
        return f"오늘 AI 토큰 한도({budget['tokens_day']:,}) 안에 들어가지 않아 다음으로 미룹니다"
    return None


# ---------------------------------------------------------------- one meeting
def hold(conn, kind: str, key: str, packet: dict, runner, now: int, budget: dict, notifier=None, dry: bool = False,
         model: str = MODEL_DEFAULT, clock: Callable[[], int] = lambda: int(time.time() * 1000)) -> dict:
    """Hold one meeting: the members in order, then the lead; recorded as it goes (a member who fails is recorded and the
    others still speak; a plan limit stops the meeting). Returns the meeting row as a dict."""
    from .agents import runner as R
    roles = KIND_ROLES[kind]
    title = f"{KIND_KO[kind]} · {kst_text(now)}"
    est = R.call_charge(R.input_estimate(R.packet_payload({"role": "lead", "facts": packet, "team": [{"text": "x" * 1200}] * 3}),
                                         system_prompt("lead"), instruction("lead", kind)))
    why = None if dry else fits(conn, now, budget, len(roles), est)
    if why:
        return {"state": "deferred", "why": why, "key": key}
    cur = conn.execute("INSERT INTO meetings (kind, key, title, started_ts, state, why, packet, dry) VALUES (?,?,?,?,?,?,?,?)",
                       (kind, key, title, now, "running", None, json.dumps(packet, ensure_ascii=False, default=str), int(dry)))
    mid = cur.lastrowid
    conn.commit()
    team, calls, tokens, lead, failed = [], 0, 0, None, None
    for seq, role in enumerate(roles, 1):
        pkt = {"role": role, "meeting": kind, "facts": packet, "team": team}
        t0 = clock()
        try:
            res = runner.call(model, system_prompt(role), instruction(role, kind), pkt)
            used_t = R._sum((res.meta or {}).get("usage"), R.USAGE_KEYS) if isinstance(res.meta, dict) else 0
            text, data, err = member_text(role, res.data, res.text), res.data, None
        except R.UsageLimitReached as exc:
            used_t, text, data, err = int(getattr(exc, "tokens", 0) or 0), "", None, f"AI 사용 한도: {_clip(exc, 200)}"
            failed = "AI 사용 한도에 걸려 회의를 멈췄습니다(다음에 다시 열지 않음)"
        except Exception as exc:  # noqa: BLE001  a member's failure is recorded, the others still speak
            used_t, text, data, err = int(getattr(exc, "tokens", 0) or 0), "", None, _clip(f"{type(exc).__name__}: {exc}", 300)
        calls += 1
        tokens += used_t
        if not dry:
            conn.execute("INSERT INTO usage (ts, day, meeting, role, calls, tokens) VALUES (?,?,?,?,?,?)",
                         (t0, kst_date(t0), mid, role, 1, used_t))
        conn.execute("INSERT INTO messages (meeting, seq, role, ts, text, data, model, tokens, error) VALUES (?,?,?,?,?,?,?,?,?)",
                     (mid, seq, role, t0, text or ("(답 없음: " + (err or "알 수 없음") + ")"),
                      json.dumps(data, ensure_ascii=False) if data is not None else None, model, used_t, err))
        conn.commit()
        if err is None:
            if role == "lead":
                lead = lead_result(data)
            else:
                team.append({"who": f"{ROLES[role]['name']}({ROLES[role]['title']})", "text": text})
        if failed:
            break
    if lead is None:
        why = failed or "팀장이 결론을 쓰지 못했습니다(아래 팀원 기록 참고)"
        conn.execute("UPDATE meetings SET state = 'failed', why = ?, finished_ts = ?, calls = ?, tokens = ? WHERE id = ?",
                     (why, clock(), calls, tokens, mid))
        conn.commit()
        return {"id": mid, "state": "failed", "why": why, "key": key}
    for i in lead["ideas"]:
        conn.execute("INSERT INTO ideas (meeting, ts, idea, why, test) VALUES (?,?,?,?,?)", (mid, now, i["idea"], i["why"], i["test"]))
    sent = None
    if notifier is not None and not dry:
        sent = int(bool(_send(notifier, message(kind, lead))))
    conn.execute("UPDATE meetings SET state = 'done', finished_ts = ?, headline = ?, verdict = ?, result = ?, sent = ?, calls = ?, "
                 "tokens = ? WHERE id = ?", (clock(), lead["headline"], lead["verdict"], json.dumps(lead, ensure_ascii=False), sent,
                                             calls, tokens, mid))
    conn.commit()
    return {"id": mid, "state": "done", "key": key, "lead": lead, "calls": calls, "tokens": tokens}


def quiet(conn, kind: str, key: str, now: int, why: str) -> dict:
    conn.execute("INSERT INTO meetings (kind, key, title, started_ts, finished_ts, state, why, headline) VALUES (?,?,?,?,?,?,?,?)",
                 (kind, key, f"{KIND_KO[kind]} · {kst_text(now)}", now, now, "quiet", why, why))
    conn.commit()
    return {"state": "quiet", "key": key, "why": why}


def message(kind: str, lead: dict) -> str:
    icon = {"정상 범위": "🟢", "지켜보기": "🟡", "주의": "🟠"}.get(lead.get("verdict"), "🟡")
    lines = [f"🧭 [실거래 분석팀] {KIND_KO.get(kind, kind)} {icon} {lead.get('verdict')}", lead.get("headline") or ""]
    lines += [f"· {x}" for x in (lead.get("summary") or [])[:4]]
    if lead.get("ideas"):
        lines.append(f"시험해 볼 아이디어 {len(lead['ideas'])}개 (결정은 두 분)")
    lines.append(f"자세히: {DASH_HINT} · AI 의견이라 참고만, 매매는 고정 규칙대로")
    return "\n".join(x for x in lines if x)


def _send(notifier, text: str) -> bool:
    try:
        r = notifier.send(INFO, text)
        return r is not False
    except Exception:  # noqa: BLE001  the meeting stands without its message
        return False


# ---------------------------------------------------------------- tick / run
def due(conn, src: dict) -> list:
    """[(kind, key, focus)] not held yet, strongest first (loss, checkpoint, weekly)."""
    out = []
    for kind, fn in (("loss", due_loss), ("checkpoint", due_checkpoint), ("weekly", due_weekly)):
        got = fn(src)
        if got and not conn.execute("SELECT 1 FROM meetings WHERE key = ?", (got[0],)).fetchone():
            out.append((kind, got[0], got[1]))
    return out


def packet_for(src: dict, kind: str, focus: dict) -> dict:
    if kind == "weekly":
        a, b = focus["window"]
        return facts(src, kind, window=(a, b))
    if kind == "loss":
        return facts(src, kind, window=(src["now"] - 3 * DAY, src["now"] + 1), focus=focus)
    return facts(src, kind, window=(src["now"] - 14 * DAY, src["now"] + 1), focus=focus)


def week_has_trades(packet: dict) -> bool:
    return bool(packet.get("trades"))


def tick(conn, src: dict, runner, budget: dict, notifier=None, dry: bool = False, model: str = MODEL_DEFAULT,
         only: Optional[str] = None, force: bool = False) -> Optional[dict]:
    """Hold the first due meeting (``only``: that kind; ``force``: hold it even if held before, under a new key)."""
    now = src["now"]
    items = due(conn, src) if not force else []
    if force and only:
        got = {"loss": due_loss, "checkpoint": due_checkpoint, "weekly": due_weekly}[only](src)
        focus = got[1] if got else ({"window": [now - 7 * DAY, now]} if only == "weekly" else {"note": "손으로 연 회의"})
        items = [(only, f"{only}:manual:{now}", focus)]
    for kind, key, focus in items:
        if only and kind != only:
            continue
        packet = packet_for(src, kind, focus)
        if kind == "weekly" and not week_has_trades(packet):
            return quiet(conn, kind, key, now, "지난주 닫힌 거래가 없어 AI 회의 없이 넘어갑니다")
        return hold(conn, kind, key, packet, runner, now, budget, notifier=notifier, dry=dry, model=model)
    return None


def status_lines(conn, now: int, budget: dict) -> list:
    u = used(conn, now)
    out = [f"AI 사용: 오늘 {u['day_calls']}/{budget['day']}번 · 토큰 {u['day_tokens']:,}/{budget['tokens_day']:,} · 최근 7일 "
           f"{u['week_calls']}/{budget['week']}번"]
    for r in conn.execute("SELECT id, kind, title, state, headline, why FROM meetings ORDER BY id DESC LIMIT 10"):
        out.append(f"#{r[0]} {r[2]} [{r[3]}] {r[4] or r[5] or ''}")
    return out


def _runner(dry: bool):
    from .agents import runner as R
    if dry:
        return R.FakeRunner(answers={
            "lead": {"headline": "(연습) 결론", "verdict": "지켜보기", "summary": ["(연습) 요약"], "good": [], "worries": [],
                     "watch_next": [], "ideas": []}})
    return R.ClaudeCodeRunner(timeout=900.0)


def _notifier():
    from .notify import TelegramNotifier
    try:
        return TelegramNotifier()
    except KeyError:
        return None


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.liveteam", description="실거래 분석 팀 (읽기만, 매매 권한 없음)")
    ap.add_argument("--db", default=os.environ.get(DB_ENV) or DB_DEFAULT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tick")
    t.add_argument("--dry-run", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("kind", choices=sorted(KIND_ROLES))
    r.add_argument("--force", action="store_true")
    r.add_argument("--dry-run", action="store_true")
    pv = sub.add_parser("preview")
    pv.add_argument("kind", choices=sorted(KIND_ROLES))
    sub.add_parser("status")
    a = ap.parse_args(argv)
    try:
        budget = parse_budget(os.environ.get(BUDGET_ENV))
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    model = os.environ.get(MODEL_ENV) or MODEL_DEFAULT
    now = int(time.time() * 1000)
    if a.cmd == "preview":
        src = sources(now)
        got = {"loss": due_loss, "checkpoint": due_checkpoint, "weekly": due_weekly}[a.kind](src)
        focus = got[1] if got else ({"window": [now - 7 * DAY, now]} if a.kind == "weekly" else {"note": "지금은 열릴 조건이 아님"})
        pkt = packet_for(src, a.kind, focus)
        print(json.dumps(pkt, ensure_ascii=False, indent=1, default=str))
        for role in KIND_ROLES[a.kind]:
            print(f"\n===== {ROLES[role]['name']} ({ROLES[role]['title']})\n{system_prompt(role)}\n--- {instruction(role, a.kind)}")
        return 0
    conn = connect(a.db)
    try:
        if a.cmd == "status":
            print("\n".join(status_lines(conn, now, budget)))
            return 0
        dry = bool(getattr(a, "dry_run", False))
        if not dry:
            from .agents import runner as R
            ok, why = R.auth_preflight(env=dict(os.environ))
            put_state(conn, "auth", now, {"ok": ok, "why": why})
            if not ok:
                print(f"Claude 로그인 확인 실패: {why}", file=sys.stderr)
                return 0                    # nothing held; the 분석팀 tab says why
        src = sources(now)
        got = tick(conn, src, _runner(dry), budget, notifier=None if dry else _notifier(), dry=dry, model=model,
                   only=getattr(a, "kind", None), force=bool(getattr(a, "force", False)))
        put_state(conn, "tick", now, {"result": {k: v for k, v in (got or {}).items() if k != "lead"}, "dry": dry})
        print(json.dumps(got or {"state": "nothing due"}, ensure_ascii=False, default=str)[:2000])
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
