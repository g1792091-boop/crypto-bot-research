"""When the agent staff meet: code-only triggers for the rooms (no model calls).

The owners do not have to type anything for a discussion to start. Every tick of
the agents process calls ``find_due``; it reads the live run (paper3.db), the
nightly check (daily3.db), the owners' inbox (inbox.db) - all opened read-only by
the caller - and the rooms' own history (agents3.db: ``rounds`` and ``cursors``),
and returns the rounds that should run now, most urgent first.

Triggers (defaults in ``TriggerPolicy``; every number is configurable):

    incident      0  team:ops      new CRITICAL alert (liquidation, engine halted), signal
                                   timeout or data-gap WARN in paper3.db alerts (by alert
                                   rowid); nightly parity mismatch, missing 00:00 snapshot or
                                   missing 1m bars in daily3.db reports (by report day). A report whose
                                   mismatches are all proven early 1m klines (daily3 ``early_kline``)
                                   opens none.
    owner         1  <room>        new owner_messages in that room (inbox.db) since the cursor (the
                                   oldest ``owner_batch`` (10) per meeting; the rest open the next one).
    loss_cluster  2  strat:<S>     since the room's last round: >= 2 new losing trades of the
                                   strategy (any timeframe), or one loss-card tag
                                   (cards.tag_stats) in >= 3 of them; >= 2h between
                                   loss_cluster rounds of a room.
    bust          2  strat:<S>     a strategy account went bust (once per account).
    checkpoint    3  team:lead     day 30 / 60 / 90 ... since the run started, once the checkpoint job has
                                   stored that day's verdict (checkpoint.db, read-only).
    morning       3  team:market   08:00 KST, once per KST day (window 4h).
    ranking       3  team:review   14:00 KST, once per KST day (window 4h): the top and bottom strategies by P&L.
    evening       3  team:review   22:00 KST, once per KST day (window 4h),
                     team:lead     then the lead (after the review team has met).
    weekly        4  strat:<S>     on weekday (strategy index mod 7, KST) when the strategy has
                                   >= 30 closed trades since its last weekly review; a review
                                   the budget deferred or stopped stays due on the next days
                                   until it has run (same slot key).
    tf_split      4  strat:<S>     at ``tf_split_hour_kst`` (18:00 on the server; -1 = off here) once per KST day
                                   (window 4h): up to ``tf_split_per_day`` strategies whose timeframe accounts
                                   disagree (best > 0 > worst, each >= 8 closed trades, spread >= 10% of the
                                   starting equity, a busted account never one of the pair; digest.tf_split),
                                   widest first, a strategy at most every 3 days. Weekly class (the reviews' budget).
    market_move   2  team:market   a coin's last-hour high or low >= 4% (BTC), 5% (ETH), 6% (others) away from its
                                   price an hour before (``market``: the caller fetches the 5m bars; none = never
                                   due). One meeting for all coins that moved, a coin at most every 3h, at most 4 a
                                   KST day (exempt from the room's daily cap).
    cost_review   4  team:ops      Monday   } the weekly analysis meetings (owners' choice 2026-10-04): at
    combo_review  4  team:risk     Tuesday  } ``<name>_hour_kst`` (11:00 on the server; -1 = off here) of
    coin_review   4  team:review   Wednesday} their KST weekday, once per KST week (key = that day); a meeting the
    learning_review 4 team:lead    Saturday } budget deferred or stopped stays due on the following days until the
    rr_review     4  team:review   Thursday } (risk-reward / exit meeting, owners' request 2026-10-04: agents/riskreward.py)
    risk_review   4  team:risk     Friday   } (drawdown / bust risk and the backtest gap, owners' request 2026-10-04:
                                              agents/survival.py, agents/btgap.py)
                                   next one. Only once there is enough data (``analysis_ok``: >= ``analysis_min_trades``
                                   closed strategy trades in the 7 days before the slot and >= ``analysis_min_days``
                                   since the run started); otherwise nothing is due and ``analysis_status`` says why
                                   (the rooms tick keeps it in the cursor ``meetings:skipped``). Weekly class.
    event_review  4  team:market   the KST day after each US release of data/macro_events.csv (CPI, FOMC, NFP, PCE) at
                                   ``event_review_hour_kst`` (11:00 on the server; -1 = off), once per event, due until
                                   ``event_review_window_ms`` after; only when the paper run covered the event's window
                                   (2h before .. 6h after the release). Weekly class.
    bull_bear     3  team:market   daily at ``bull_bear_hour_kst`` (12:00 on the server; -1 = off), window 4h: one coin
                                   a day in rotation (``bull_bear_coin``). Scheduled class. The chair's call is recorded
                                   and graded 24h later by code (agents/committee.py); no trade ever follows.
    research      5  team:lab      the new-strategy lab, every ``research_every_ms`` (one slot per
                                   period of the KST day; a slot that could not start is skipped,
                                   not caught up). 0 = off (the default here; the rooms server's
                                   policy turns it on, rooms.policy_from_env). Its own budget class,
                                   paced over the day, so it only uses spare calls; exempt from the
                                   room's daily cap (the budget bounds it).

Extra paper accounts (agents/extra_accounts.py): a copy account's losses, bust and trades count in its
parent strategy's room (loss_cluster, bust, weekly: accounts of kind 'strategy' or 'copy'); the
new-strategy accounts (kind 'newlab') have the same three triggers in team:lab (``_lab_accounts``: cursors
``loss:team:lab``, ``bust:<account>``, ``weekly:team:lab``, the weekly review on Sunday KST). A meeting that
only extras' trades open (the originals alone would not) is marked ``extras`` in its data: it never uses
the room's daily slots (those stay for the 195) and is bounded instead by its own line,
``extras_meetings_per_day`` (6) a KST day over all rooms; when the line is full it waits for the next day.

Limits: at most 4 rounds per room per KST day (incidents and research exempt; one of the 4 is kept
for the owners' posts until they have used one that day), one round per room per tick,
at most 4 rounds per tick. Output order: (priority, bust before loss_cluster, oldest
evidence).

Crash safety (the caller's side of the contract; ``begin_round`` / ``finish_round``
implement it): the round row stores ``trigger_data`` = ``Due.data`` (JSON) when
it starts. ``Due.data["cursors"]`` holds the evidence high-water marks; they are
written to ``cursors`` only when the round ends as ``done`` or ``no_action``.
Until then the same evidence is found again, so a crash never loses a trigger:

- a ``running`` round younger than 2h blocks the same trigger in the same room
  (it may still be working; the rooms tick, which holds the tick lock, first marks every
  'running' round it finds as failed, since no live pass can own one then);
- a ``running`` round older than 2h, or a ``failed`` round, counts as a failed
  attempt: the trigger fires again once (``data["retry_of"]``); after two failed
  attempts for the same evidence it waits for new evidence;
- a ``stopped_budget`` round pauses what its stop says (``decision.stopped``): a class
  cap its own class, the total / weekly cap every class, the reserve for incidents and
  scheduled meetings the other classes, until the next KST day (the budgets reset); a
  Claude plan usage limit pauses everything for ``usage_backoff_ms`` (1h from when the round
  stopped), because the plan's window resets within hours, not at midnight. A loss_cluster or
  non-critical incident round stopped at its reduced cap (``budget_subcap``) pauses nothing: the
  reserve for busts / liquidations stays usable. A stopped round does not count
  against the room's daily cap;
- a ``failed`` round marked ``transient`` (the runner never answered: outage, CLI error)
  is not a failed attempt: the same evidence fires again. Nothing is due for
  ``transient_backoff_ms`` after it (from when it failed), doubling with each transient failure
  in a row (at most ``transient_backoff_max_ms``), so a long outage does not fill a room with notices;
- a round that ended ``done`` / ``no_action`` is never repeated for the same
  evidence key, even if its cursors were not written.

Evidence keys carry times (a trade's exit time, an alert's time, the run start), and
``reconcile_paper_cursors`` pulls the cursors back when paper3.db was replaced (restore from
a backup, new run): ids restart then, and new evidence must never look like handled evidence.

``find_due`` never writes anything. All texts for the owners (``summary_ko``)
are Korean and written by code from the numbers.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional, Union

from .roster3 import STRATEGY_KO

MIN_MS = 60_000
HOUR_MS = 3_600_000
DAY_MS = 86_400_000
KST_OFFSET_MS = 9 * HOUR_MS          # Korea has no daylight saving time

STRATEGIES = tuple(STRATEGY_KO)       # fixed order: the index decides the weekly weekday
TEAM_ROOMS = ("team:market", "team:risk", "team:ops", "team:review", "team:lead")
LAB_ROOM = "team:lab"                 # the new-strategy lab (rooms_db.LAB_ROOM)
LAB_WEEKDAY = 6                       # the new-strategy accounts' weekly review: Sunday (KST)

# The weekly analysis meetings (owners' choice 2026-10-04): trigger -> (KST weekday, Monday = 0, room)
ANALYSES = {"cost_review": (0, "team:ops"), "combo_review": (1, "team:risk"), "coin_review": (2, "team:review"),
            "learning_review": (5, "team:lead"), "rr_review": (3, "team:review"), "risk_review": (4, "team:risk")}
ANALYSIS_KO = {"cost_review": "비용·체결 회의", "combo_review": "조합·동시 손실 회의", "coin_review": "코인·장세 회의",
               "learning_review": "학습 정리 회의", "rr_review": "손익비·청산 회의", "risk_review": "낙폭·파산 위험 회의"}
TRIGGERS = ("incident", "owner", "loss_cluster", "bust", "checkpoint", "morning", "evening", "weekly", "research",
            "market_move", "ranking", "tf_split", *ANALYSES, "event_review", "bull_bear")
PRIORITY = {"incident": 0, "owner": 1, "loss_cluster": 2, "bust": 2, "market_move": 2, "checkpoint": 3, "morning": 3, "ranking": 3,
            "evening": 3, "bull_bear": 3, "weekly": 4, "tf_split": 4, **{k: 4 for k in ANALYSES}, "event_review": 4,
            "research": 5}
# Sub-budget class of each trigger (the rooms engine keeps one AI budget per class). The weekly analyses and the
# event review are analysis meetings that can wait a day: the weekly reviews' class; the daily debate is a fixed
# daily meeting: the scheduled class (reserved, like the 08:00 / 14:00 / 22:00 meetings).
TRIGGER_CLASS = {"incident": "incident", "owner": "owner", "loss_cluster": "loss", "bust": "loss", "market_move": "loss",
                 "checkpoint": "scheduled", "morning": "scheduled", "evening": "scheduled", "ranking": "scheduled",
                 "bull_bear": "scheduled", "weekly": "weekly", "tf_split": "weekly", **{k: "weekly" for k in ANALYSES},
                 "event_review": "weekly", "research": "research"}
# the coins of the daily debate, one a day in this order (the bot's own coins, config.V3_SYMBOLS)
BULL_BEAR_COINS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
SKIPPED_CURSOR = "meetings:skipped"   # why a weekly analysis / event review did not open (written by the rooms tick)
ENDED_OK = ("done", "no_action")      # the only statuses that advance cursors
CLASSES = ("incident", "owner", "loss", "scheduled", "weekly", "research")
# What a stopped_budget round pauses until the next KST day, by decision.stopped (when the
# decision has no explicit 'blocks' list). None = only the round's own class.
STOP_BLOCKS = {"budget_class": None, "budget_total": CLASSES, "budget_week": CLASSES,
               "budget_reserve": ("owner", "loss", "weekly"),     # rooms.stop_blocks adds research for its own
               "budget_subcap": ()}      # a reduced cap (class minus the bust / critical reserve): nothing

# (kind, level, text fragment) for paper3.db alerts; the first match wins, "" matches any text.
INCIDENT_ALERTS = (
    ("liquidation", "CRITICAL", "LIQUIDATED"),
    ("engine_halted", "CRITICAL", "ENGINE HALTED"),
    ("critical", "CRITICAL", ""),
    ("signal_timeout", "WARN", "did not answer within"),
    ("data_gap", "WARN", "data gap at"),
    ("data_gap", "WARN", "no new closed bars"),
    ("data_gap", "WARN", "history incomplete"),
    ("data_gap", "WARN", "returned no bars"),
)
INCIDENT_KO = {"liquidation": "강제청산", "engine_halted": "계좌 정지", "critical": "긴급 알림",
               "signal_timeout": "신호 계산 시간 초과", "data_gap": "데이터 끊김",
               "parity_mismatch": "재계산 불일치", "no_snapshot": "재계산 못 함(00:00 상태 저장 없음)",
               "missing_bars": "빠진 1분봉"}


def strat_room(strategy: str) -> str:
    return f"strat:{strategy}"


def all_rooms() -> tuple[str, ...]:
    return tuple(strat_room(s) for s in STRATEGIES) + TEAM_ROOMS + (LAB_ROOM,)


@dataclass
class Due:
    room_id: str
    trigger: str
    priority: int            # lower = sooner
    data: dict               # JSON-safe; stored as the round's trigger_data
    meeting: str


@dataclass
class TriggerPolicy:
    enabled: tuple = TRIGGERS
    priorities: dict = field(default_factory=lambda: dict(PRIORITY))
    # rate limits
    max_rounds_per_room_day: int = 4     # owners' choice 2026-10-03 (was 3): more reviews, the plan has room
    cap_exempt: tuple = ("incident", "research", "market_move")   # research: its own paced budget; market_move: below
    owner_reserved_per_room_day: int = 1     # slots of the daily cap only an owner post may use
    max_rounds_per_tick: int = 4
    max_per_room_per_tick: int = 1
    # crash safety
    stale_ms: int = 2 * HOUR_MS          # a 'running' round older than this has failed
    max_attempts: int = 2                # first try + one retry for the same evidence
    usage_backoff_ms: int = HOUR_MS      # after a Claude plan usage limit, nothing is due for this long
    transient_backoff_ms: int = 10 * MIN_MS      # after a transient failure (runner down): wait, doubling
    transient_backoff_max_ms: int = 4 * HOUR_MS  # per failure in a row, up to this
    transient_same_key: int = 3          # this many in a row for ONE meeting: it waits alone (not an outage)
    rounds_lookback_ms: int = 40 * DAY_MS
    # incident
    incident_alerts: tuple = INCIDENT_ALERTS
    incident_min_gap_ms: int = 30 * MIN_MS   # batch a burst of alerts into one round
    incident_lookback_ms: int = 2 * DAY_MS   # first scan (no cursor yet) looks this far back
    nightly_parity: bool = True
    nightly_no_snapshot: bool = True
    nightly_min_missing_bars: int = 1
    # market move (owners' choice 2026-10-03): a coin's high or low of the last hour this far from its price an
    # hour ago opens a market-team meeting; the same coin at most every ``market_move_gap_ms``, at most
    # ``market_move_max_per_day`` such meetings a KST day (their own line, not the room's daily slots)
    market_move_pct: dict = field(default_factory=lambda: {"BTCUSDT": 0.04, "ETHUSDT": 0.05})
    market_move_pct_other: float = 0.06
    market_move_gap_ms: int = 3 * HOUR_MS
    market_move_max_per_day: int = 4
    # loss cluster
    loss_min_count: int = 2              # owners' choice 2026-10-03 (was 3)
    loss_tag_min_count: int = 3
    loss_min_gap_ms: int = 2 * HOUR_MS   # owners' choice 2026-10-03 (was 4h)
    loss_lookback_ms: int = 7 * DAY_MS
    any_round_resets_losses: bool = True     # "since the room's last round" (any trigger)
    # weekly / checkpoint / scheduled meetings
    weekly_min_trades: int = 30
    owner_batch: int = 10                    # owner posts one owner meeting answers (oldest first)
    checkpoint_every_days: int = 30
    morning_hour_kst: int = 8
    evening_hour_kst: int = 22
    # the review team's ranking review (owners' choice 2026-10-03: 14:00 on the server, rooms.policy_from_env);
    # -1 = off, as in TriggerPolicy() itself
    ranking_hour_kst: int = -1
    # the timeframe-split review in a strategy room (owners' choice 2026-10-03: 18:00 on the server); -1 = off
    tf_split_hour_kst: int = -1
    tf_split_per_day: int = 2
    tf_split_gap_ms: int = 3 * DAY_MS
    tf_split_min_trades: int = 8
    tf_split_min_spread_pct: float = 0.10
    meeting_window_ms: int = 4 * HOUR_MS
    # the weekly analysis meetings and the event review (owners' choice 2026-10-04: 11:00 on the server,
    # rooms.policy_from_env); -1 = off, as in TriggerPolicy() itself. Each opens only with enough data: this many
    # closed strategy trades in the 7 days before its slot and this many days since the run started
    cost_review_hour_kst: int = -1
    combo_review_hour_kst: int = -1
    coin_review_hour_kst: int = -1
    learning_review_hour_kst: int = -1
    rr_review_hour_kst: int = -1          # Thursday's risk-reward / exit meeting (owners' request 2026-10-04)
    risk_review_hour_kst: int = -1        # Friday's drawdown / bust risk meeting (owners' request 2026-10-04)
    analysis_min_trades: int = 200
    analysis_min_days: int = 7
    # owners' decision 2026-10-04: besides its weekday, a weekly analysis may meet once more in the same KST week
    # (Monday-Sunday), at its hour on another day, when ``analysis_extra_factor`` x ``analysis_min_trades`` new closed
    # strategy trades came in since its last meeting and at least ``analysis_extra_gap_days`` KST days have passed;
    # never more than ``analysis_max_per_week`` meetings of one kind in a KST week
    analysis_extra_factor: int = 2
    analysis_extra_gap_days: int = 2
    analysis_extra_per_week: int = 1
    analysis_max_per_week: int = 2
    event_review_hour_kst: int = -1
    event_review_window_ms: int = 36 * HOUR_MS    # 11:00 the day after the release .. 23:00 the day after that
    event_before_ms: int = 2 * HOUR_MS            # the event's window: 2h before the release ..
    event_after_ms: int = 6 * HOUR_MS             # .. 6h after it
    # the market team's daily bull vs bear debate (12:00 on the server); -1 = off
    bull_bear_hour_kst: int = -1
    # new-strategy lab: one meeting slot per this period of the KST day; 0 = off (rooms.policy_from_env
    # turns it on for the server, RESEARCH_EVERY_MIN_DEFAULT)
    research_every_ms: int = 0
    research_idle_max_ms: int = 6 * HOUR_MS  # the longest wait after empty lab meetings (research_gap)
    # meetings opened only by extra accounts' trades (copies, new-strategy accounts) per KST day, all rooms
    # together: their own line, never the 195's room slots (env AGENTS_EXTRAS_MEETINGS_PER_DAY)
    extras_meetings_per_day: int = 6
    max_items: int = 30                      # evidence rows copied into Due.data


# ---------------------------------------------------------------- time (KST)
def kst_day_start(ms: int) -> int:
    """UTC ms of 00:00 KST of the KST day containing ``ms``."""
    return ms - (ms + KST_OFFSET_MS) % DAY_MS


def kst_date(ms: int) -> str:
    return dt.datetime.fromtimestamp((ms + KST_OFFSET_MS) / 1000, dt.timezone.utc).strftime("%Y-%m-%d")


def kst_weekday(ms: int) -> int:
    """Monday = 0 ... Sunday = 6, in KST."""
    return dt.datetime.fromtimestamp((ms + KST_OFFSET_MS) / 1000, dt.timezone.utc).weekday()


def slot_start(now_ms: int, hour_kst: int) -> int:
    """UTC ms of the latest ``hour_kst``:00 KST at or before ``now_ms``."""
    s = kst_day_start(now_ms) + hour_kst * HOUR_MS
    return s if s <= now_ms else s - DAY_MS


# ---------------------------------------------------------------- small db helpers
def _rows(conn: Optional[sqlite3.Connection], sql: str, args: Iterable = ()) -> list:
    """Rows as tuples; a missing database or table reads as empty."""
    if conn is None:
        return []
    try:
        return [tuple(r) for r in conn.execute(sql, tuple(args)).fetchall()]
    except sqlite3.DatabaseError:        # missing table, or not a database file (bad restore)
        return []


def _one(conn, sql: str, args: Iterable = ()):
    rows = _rows(conn, sql, args)
    return rows[0] if rows else None


def _json(text: Any) -> dict:
    if isinstance(text, dict):
        return text
    try:
        v = json.loads(text) if text else {}
    except (TypeError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}


def _int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- state of the rooms
class _Rooms:
    """Rounds and cursors of agents3.db, read once per ``find_due``."""

    def __init__(self, conn: sqlite3.Connection, now_ms: int, p: TriggerPolicy):
        self.now, self.p = now_ms, p
        self.cursors = {k: v for k, v in _rows(conn, "SELECT k, v FROM cursors")}
        self.rounds = []
        for rid, room, trig, tdata, started, ended, status, calls, decision in _rows(
                conn, "SELECT round_id, room_id, trigger, trigger_data, started_ts, ended_ts, status, calls, decision "
                      "FROM rounds WHERE started_ts >= ? OR status = 'running' ORDER BY round_id",
                (now_ms - p.rounds_lookback_ms,)):
            d, dec = _json(tdata), _json(decision)
            blocks = dec.get("blocks")
            self.rounds.append({"round_id": rid, "room_id": room, "trigger": trig, "key": d.get("key"),
                                "extras": d.get("extras") is True,
                                "class": d.get("class") or TRIGGER_CLASS.get(trig),
                                "started_ts": _int(started), "ended_ts": _int(ended, _int(started)),
                                "status": status, "calls": _int(calls),
                                "stopped": dec.get("stopped"), "transient": dec.get("transient") is True,
                                "calls_ok": _int(dec.get("calls_ok"), _int(calls)),
                                "candidates": dec.get("candidates") if isinstance(dec.get("candidates"), int) else None,
                                "blocks": tuple(blocks) if isinstance(blocks, list) else None})
        self.day_start = kst_day_start(now_ms)
        self.rooms = set(all_rooms()) | {r[0] for r in _rows(conn, "SELECT room_id FROM rooms")}

    def cursor(self, k: str, default: Optional[str] = None) -> Optional[str]:
        return self.cursors.get(k, default)

    def cursor_int(self, k: str) -> int:
        return _int(self.cursors.get(k), 0)

    def stale(self, r: dict) -> bool:
        return r["status"] == "running" and self.now - r["started_ts"] >= self.p.stale_ms

    def running_fresh(self, room: str, trigger: str) -> bool:
        return any(r["room_id"] == room and r["trigger"] == trigger and r["status"] == "running"
                   and not self.stale(r) for r in self.rounds)

    def same_key(self, room: str, trigger: str, key: str) -> list[dict]:
        return [r for r in self.rounds if r["room_id"] == room and r["trigger"] == trigger and r["key"] == key]

    def handled(self, room: str, trigger: str, key: str) -> bool:
        return any(r["status"] in ENDED_OK for r in self.same_key(room, trigger, key))

    def failed_attempts(self, room: str, trigger: str, key: str) -> list[dict]:
        """Rounds that tried this evidence and failed. A 'transient' failure (the runner never
        answered: outage, CLI error) is not an attempt: the evidence fires again next tick."""
        return [r for r in self.same_key(room, trigger, key)
                if (r["status"] == "failed" and not r["transient"]) or self.stale(r)]

    def settled(self, room: str, trigger: str, key: str) -> bool:
        """Nothing more will happen for this evidence (met, given up, or deferred by the budget)."""
        rs = self.same_key(room, trigger, key)
        return (any(r["status"] in ENDED_OK + ("stopped_budget",) for r in rs)
                or len(self.failed_attempts(room, trigger, key)) >= self.p.max_attempts)

    def last_ok_start(self, room: str, trigger: str) -> Optional[int]:
        ts = [r["started_ts"] for r in self.rounds if r["room_id"] == room and r["trigger"] == trigger
              and (r["status"] in ENDED_OK or (r["status"] == "running" and not self.stale(r)))]
        return max(ts) if ts else None

    def blocks(self, r: dict) -> tuple:
        """Classes a stopped_budget round pauses for the rest of its KST day."""
        if r["blocks"] is not None:
            return r["blocks"]
        got = STOP_BLOCKS.get(r["stopped"] or "budget_class", None)
        if r["stopped"] == "usage_limit":
            return ()                      # handled by usage_paused (hours, not the whole day)
        return (r["class"],) if got is None else got

    def class_blocked(self, cls: str) -> bool:
        return any(r["status"] == "stopped_budget" and r["started_ts"] >= self.day_start
                   and cls in self.blocks(r) for r in self.rounds)

    def usage_paused(self) -> bool:
        """A round hit the Claude plan's usage limit less than ``usage_backoff_ms`` ago (measured from
        when it stopped, not from when it started)."""
        return any(r["status"] == "stopped_budget" and r["stopped"] == "usage_limit"
                   and self.now - r["ended_ts"] < self.p.usage_backoff_ms for r in self.rounds)

    def _backoff(self, k: int) -> int:
        return min(self.p.transient_backoff_max_ms, self.p.transient_backoff_ms * 2 ** min(max(k, 1) - 1, 20))

    def transient_run(self, room: str, trigger: str, key: str) -> list[dict]:
        """This evidence's latest rounds, newest first, while they are transient failures."""
        out = []
        for r in reversed(self.same_key(room, trigger, key)):
            if r["status"] == "failed" and r["transient"]:
                out.append(r)
            elif r["status"] != "running":
                break
        return out

    def key_waiting(self, room: str, trigger: str, key: str) -> bool:
        """This meeting failed 'transiently' ``transient_same_key`` times in a row (its first speaker's
        model is refused, its packet always times out) while the others may be fine: it waits on its
        own, with the same growing pause, instead of pausing every room."""
        run = self.transient_run(room, trigger, key)
        if len(run) < self.p.transient_same_key:
            return False
        return self.now - run[0]["ended_ts"] < self._backoff(len(run))

    def transient_paused(self) -> bool:
        """The latest finished rounds failed because the runner never answered: back off. Not when
        they are all the same meeting failing ``transient_same_key`` times or more (``key_waiting``)."""
        k, last, keys = 0, None, set()
        for r in reversed(self.rounds):
            if r["status"] == "running":
                continue
            if not (r["status"] == "failed" and r["transient"]):
                break
            k += 1
            keys.add((r["room_id"], r["trigger"], r["key"]))
            last = r["ended_ts"] if last is None else last      # the pause runs from when it failed
        if not k:
            return False
        if len(keys) == 1 and len(self.transient_run(*next(iter(keys)))) >= self.p.transient_same_key:
            return False            # one meeting keeps failing by itself: it waits alone (key_waiting)
        pause = self._backoff(k)
        return self.now - last < pause

    def _counted(self, r: dict) -> bool:
        """Does this round use one of its room's daily slots? Budget/usage stops and transient
        failures without any answered call do not (the same evidence runs again later)."""
        if r["status"] == "stopped_budget":
            return False
        return not (r["transient"] and r["calls_ok"] == 0)

    def rounds_today(self, room: str, trigger: Optional[str] = None) -> int:
        """The room's meetings today that use its daily slots (not the extras' own meetings)."""
        return sum(1 for r in self.rounds if r["room_id"] == room and r["started_ts"] >= self.day_start
                   and r["trigger"] not in self.p.cap_exempt and (trigger is None or r["trigger"] == trigger)
                   and not r["extras"] and self._counted(r))

    def extras_today(self) -> int:
        """Meetings opened only by extra accounts' trades today, in every room (their own daily line)."""
        return sum(1 for r in self.rounds if r["extras"] and r["started_ts"] >= self.day_start and self._counted(r))

    def room_full(self, room: str, trigger: str, extra: int = 0) -> bool:
        """The room's daily cap. Until an owner round has run today, ``owner_reserved_per_room_day``
        slots are kept for the owners' posts (other triggers stop earlier)."""
        if trigger in self.p.cap_exempt:
            return False
        cap = self.p.max_rounds_per_room_day
        if trigger != "owner":
            cap -= max(0, self.p.owner_reserved_per_room_day - self.rounds_today(room, "owner"))
        return self.rounds_today(room) + extra >= cap


# ---------------------------------------------------------------- paper3.db helpers
def run_start(paper_ro: Optional[sqlite3.Connection], strict: bool = False) -> Optional[int]:
    """When the paper run started: the creation time of its original accounts (the state
    'run' row is rewritten at every restart), else the first ``runs`` row, else state 'run'.
    ``strict``: a read error (e.g. 'database is locked') raises LookupError instead of reading as
    'no rows' and falling back to a restart time (the cursor reconciliation would take that for a
    new run and reset every trigger cursor); only a missing table reads as empty."""
    one = _q1_tables if strict else _one
    r = one(paper_ro, "SELECT MIN(created_ts) FROM accounts WHERE kind IN ('strategy', 'random')")
    if r and r[0] is not None:
        return int(r[0])
    r = one(paper_ro, "SELECT MIN(started_ts) FROM runs")
    if r and r[0] is not None:
        return int(r[0])
    r = one(paper_ro, "SELECT ts FROM state WHERE k = 'run'")
    return None if r is None else int(r[0])


def _trade_hwm(paper_ro) -> int:
    r = _one(paper_ro, "SELECT MAX(id) FROM trades")
    return 0 if r is None or r[0] is None else int(r[0])


def _round_trip(paper_ro) -> float:
    from ..config import v3_settings
    r = _one(paper_ro, "SELECT data FROM state WHERE k = 'run'")
    fee = _json(r[0]).get("taker_fee") if r else None
    return v3_settings(**({"taker_fee": fee} if fee else {})).round_trip_cost


def _strategy_cursors(st: _Rooms, room: str, hwm: int) -> dict:
    """Cursors every strategy-room round advances: the room has now seen these trades."""
    return {f"loss:{room}": str(hwm)} if st.p.any_round_resets_losses else {}


# ---------------------------------------------------------------- triggers
def _incident(paper_ro, daily_ro, st: _Rooms) -> list[Due]:
    p, room = st.p, "team:ops"
    items: list[dict] = []
    cur_a = st.cursor_int("incident:alert_rowid")
    top = _one(paper_ro, "SELECT MAX(rowid) FROM alerts")       # read BEFORE the scan (no row is skipped)
    hwm_a = max(cur_a, _int(top[0]) if top else 0)
    since = st.now - p.incident_lookback_ms if cur_a == 0 else 0
    levels = sorted({lvl for _k, lvl, _f in p.incident_alerts})
    # only the levels an incident can have: the INFO rows (every exit of 195 accounts) are never read
    for rowid, ts, level, text in _rows(paper_ro, "SELECT rowid, ts, level, text FROM alerts WHERE rowid > ? "
                                                  f"AND level IN ({','.join('?' * len(levels))}) ORDER BY rowid",
                                        (cur_a, *levels)):
        hwm_a = max(hwm_a, int(rowid))
        if int(ts) < since:
            continue
        kind = next((k for k, lvl, frag in p.incident_alerts
                     if level == lvl and (not frag or frag in (text or ""))), None)
        if kind:
            items.append({"source": "alert", "rowid": int(rowid), "ts": int(ts), "kind": kind,
                          "level": level, "text": (text or "")[:300]})
    cur_d = st.cursor("incident:report_day") or ""
    if not cur_d:
        cur_d = kst_date(st.now - p.incident_lookback_ms - DAY_MS)
    hwm_d = cur_d
    for day, ts, data in _rows(daily_ro, "SELECT day, ts, data FROM reports WHERE day > ? ORDER BY day",
                               (cur_d,)):
        hwm_d = max(hwm_d, day)
        rep = _json(data)
        par = rep.get("parity")
        found = []
        # mismatched_accounts counts only the unexplained ones: a mismatch daily3 proved to be an early 1m kline
        # (parity.early_kline, "1분봉을 확정 전에 읽음") or an extra's restart gap never opens a meeting by itself;
        # one unexplained mismatch does, as before
        if isinstance(par, dict) and p.nightly_parity and _int(par.get("mismatched_accounts")) > 0:
            early = _int(par.get("early_kline"))
            found.append(("parity_mismatch", {"mismatched_accounts": _int(par["mismatched_accounts"]),
                                              "accounts": _int(par.get("accounts")),
                                              **({"early_kline": early} if early else {})}))
        elif isinstance(par, str) and p.nightly_no_snapshot:
            found.append(("no_snapshot", {"parity": par[:200]}))
        dq = rep.get("data_quality") or {}
        missing = {s: _int(q.get("missing")) for s, q in dq.items()
                   if isinstance(q, dict) and _int(q.get("missing")) >= p.nightly_min_missing_bars}
        if missing:
            found.append(("missing_bars", {"missing": missing}))
        for kind, extra in found:
            items.append({"source": "nightly", "day": day, "ts": _int(ts), "kind": kind, **extra})
    if not items:
        return []
    last = st.last_ok_start(room, "incident")
    if last is not None and st.now - last < p.incident_min_gap_ms:
        return []
    counts: dict[str, int] = {}
    for it in items:
        counts[it["kind"]] = counts.get(it["kind"], 0) + 1
    a_ids = [it["rowid"] for it in items if it["source"] == "alert"]
    d_ids = [it["day"] for it in items if it["source"] == "nightly"]
    # the newest item's time is part of the key: after paper3.db is restored alert rowids restart
    key = f"incident:a{max(a_ids) if a_ids else cur_a}@{max(it['ts'] for it in items)}:d{max(d_ids) if d_ids else '-'}"
    cursors = {"incident:alert_rowid": str(hwm_a), "incident:report_day": hwm_d}
    text = "사고 점검: " + ", ".join(f"{INCIDENT_KO.get(k, k)} {n}건" for k, n in counts.items())
    return [_due(st, room, "incident", key, min(it["ts"] for it in items), cursors, text,
                 counts=counts, items=items[-p.max_items:], n_items=len(items))]


def _owner(inbox_ro, paper_ro, st: _Rooms) -> list[Due]:
    lo = min((st.cursor_int(f"owner:{r}") for r in st.rooms), default=0)
    by_room: dict[str, list] = {}
    for mid, ts, room, author, text in _rows(inbox_ro, "SELECT id, ts, room_id, author, text FROM owner_messages "
                                                       "WHERE id > ? ORDER BY id", (lo,)):
        if room in st.rooms and int(mid) > st.cursor_int(f"owner:{room}"):
            by_room.setdefault(room, []).append({"id": int(mid), "ts": _int(ts), "author": author,
                                                 "text": (text or "")[:1000]})
    hwm = _trade_hwm(paper_ro) if any(r.startswith("strat:") for r in by_room) else 0
    out = []
    for room, msgs in by_room.items():
        # one meeting answers the oldest posts it can show the staff (the packet holds the last 10, the
        # room shows at most 50 copied posts); the rest open the next owner meeting of that room
        batch = max(1, st.p.owner_batch)
        # a batch given up after max_attempts failed meetings stays given up (like any evidence), but the
        # posts after it are new evidence: they get their own meeting instead of waiting behind it forever
        # (the batch's key never changes while it has a full batch in front of the newer posts)
        while len(msgs) > batch:
            head = msgs[batch - 1]
            if len(st.failed_attempts(room, "owner", f"owner:{room}:{head['id']}@{head['ts']}")) < st.p.max_attempts:
                break
            msgs = msgs[batch:]
        msgs = msgs[:batch]
        last = msgs[-1]["id"]
        cursors = {**(_strategy_cursors(st, room, hwm) if room.startswith("strat:") else {}),
                   f"owner:{room}": str(last)}
        # the post's time is part of the key: after inbox.db is replaced ids restart, and a new post
        # with an old id must not look like evidence that was already handled
        out.append(_due(st, room, "owner", f"owner:{room}:{last}@{msgs[-1]['ts']}", msgs[0]["ts"], cursors,
                        f"두 분이 남긴 새 메시지 {len(msgs)}건", message_ids=[m["id"] for m in msgs],
                        messages=msgs[-10:]))
    return out


def _strategy_trades(paper_ro, since_id: int, losses_only: bool, since_ms: int = 0,
                     upto_id: Optional[int] = None) -> list[tuple]:
    """(id, account_id, exit_time, pnl, data, strategy, timeframe, kind) of the strategy accounts' and their
    copies' closed trades (a copy's strategy column is its parent's)."""
    q = ("SELECT t.id, t.account_id, t.exit_time, t.pnl, t.data, a.strategy, a.timeframe, a.kind FROM trades t "
         "JOIN accounts a ON a.account_id = t.account_id WHERE a.kind IN ('strategy', 'copy') AND t.id > ? "
         "AND t.exit_time >= ?")
    args: tuple = (since_id, since_ms)
    if upto_id is not None:
        q += " AND t.id <= ?"
        args += (int(upto_id),)
    if losses_only:
        q += " AND t.pnl < 0"
    return _rows(paper_ro, q + " ORDER BY t.id", args)


def _loss_cluster(paper_ro, st: _Rooms) -> list[Due]:
    from ..cards import card, tag_stats
    p = st.p
    cur = {s: st.cursor_int(f"loss:{strat_room(s)}") for s in STRATEGIES}
    # the high-water mark is read BEFORE the scan and bounds it: a loss the live runner commits in
    # between is neither in this cluster nor behind the cursor this meeting writes (it counts next time)
    hwm = _trade_hwm(paper_ro)
    rows = _strategy_trades(paper_ro, min(cur.values(), default=0), True, st.now - p.loss_lookback_ms, upto_id=hwm)
    by_s: dict[str, list] = {}
    for r in rows:
        if r[5] in cur and r[0] > cur[r[5]]:
            by_s.setdefault(r[5], []).append(r)
    if not by_s:
        return []
    rt = _round_trip(paper_ro)
    out = []
    for s, lst in by_s.items():
        room = strat_room(s)
        last = st.last_ok_start(room, "loss_cluster")
        if last is not None and st.now - last < p.loss_min_gap_ms:
            continue
        cards, kinds = [], []
        for r in lst:
            try:
                cards.append(card(r[1], json.loads(r[4]), rt))
                kinds.append(r[7])
            except (KeyError, TypeError, ValueError):
                pass                                  # an odd row still counts as a loss
        top = [{"tag": r["tag"], "losses": r["losses"]} for r in tag_stats(cards)
               if r["losses"] >= p.loss_tag_min_count]
        top.sort(key=lambda r: -r["losses"])
        if len(lst) < p.loss_min_count and not top:
            continue
        # would the strategy's own accounts alone open it? If not, only its copies' losses do: an extras meeting
        orig = [r for r in lst if r[7] == "strategy"]
        orig_top = [r for r in tag_stats([c for c, k in zip(cards, kinds) if k == "strategy"])
                    if r["losses"] >= p.loss_tag_min_count]
        extras_only = len(orig) < p.loss_min_count and not orig_top
        copies = sorted({r[1] for r in lst if r[7] == "copy"})
        tfs: dict[str, int] = {}
        for r in lst:
            tfs[r[6]] = tfs.get(r[6], 0) + 1
        reasons: dict[str, int] = {}
        for c in cards:
            reasons[c["reason"]] = reasons.get(c["reason"], 0) + 1
        cursors = {**_strategy_cursors(st, room, hwm), f"loss:{room}": str(hwm)}
        text = (f"{STRATEGY_KO[s]}: 새 손실 {len(lst)}건 ("
                + ", ".join(f"{tf} {n}건" for tf, n in tfs.items()) + ")")
        if top:
            text += " · 많이 나온 특징: " + ", ".join(f"{t['tag']} {t['losses']}건" for t in top[:3])
        # trade id AND its exit time: after paper3.db is restored ids restart, and new trades with old
        # ids must not look like evidence that was already handled
        if copies:
            text += f" · 그중 복제 계좌 손실 {len(lst) - len(orig)}건"
        extra = {"extras": True} if extras_only else {}
        if copies:
            extra["extra_accounts"] = copies
        out.append(_due(st, room, "loss_cluster", f"loss:{s}:{lst[-1][0]}@{lst[-1][2]}", min(r[2] for r in lst), cursors,
                        text, strategy=s, losses=len(lst), trade_ids=[r[0] for r in lst][-p.max_items:],
                        by_timeframe=tfs, exit_reasons=reasons, top_tags=top,
                        touched_first_lock=sum(bool(c.get("touched_first_lock")) for c in cards),
                        oldest_exit=min(r[2] for r in lst), newest_exit=max(r[2] for r in lst), **extra))
    return out


def busts_of(paper_ro) -> dict[str, int]:
    """{account_id: bust time} of the accounts paper3.db shows as bust. Evidence time: the first BUST
    alert; for a bust only seen in the saved state (whose row time changes at every save), the
    account's last closed trade (the one that emptied it)."""
    busts: dict[str, int] = {}
    for ts, text in _rows(paper_ro, "SELECT ts, text FROM alerts WHERE level = 'WARN' AND text LIKE '[%] BUST:%'"):
        aid = text[1:text.find("]")]
        busts[aid] = min(int(ts), busts.get(aid, int(ts)))
    r = _one(paper_ro, "SELECT ts, data FROM state WHERE k = 'accounts'")
    if r is not None:
        for aid, e in (_json(r[1]).get("engines") or {}).items():
            if isinstance(e, dict) and e.get("bust") and aid not in busts:
                last = _one(paper_ro, "SELECT MAX(exit_time) FROM trades WHERE account_id = ?", (aid,))
                busts[aid] = int(last[0]) if last and last[0] is not None else int(r[0])
    return busts


def _bust(paper_ro, st: _Rooms) -> list[Due]:
    """A strategy account or one of its copies went bust (in the strategy's room)."""
    accts = {aid: (s, tf, k) for aid, s, tf, k in _rows(paper_ro, "SELECT account_id, strategy, timeframe, kind "
                                                                  "FROM accounts WHERE kind IN ('strategy', 'copy')")}
    busts = busts_of(paper_ro)
    by_s: dict[str, dict] = {}
    for aid, ts in busts.items():
        if aid in accts and accts[aid][0] in STRATEGY_KO and st.cursor(f"bust:{aid}") is None:
            by_s.setdefault(accts[aid][0], {})[aid] = ts
    hwm = _trade_hwm(paper_ro) if by_s else 0
    out = []
    for s, got in by_s.items():
        room = strat_room(s)
        aids = sorted(got)
        cursors = {**_strategy_cursors(st, room, hwm), **{f"bust:{a}": str(got[a]) for a in aids}}
        # the bust times are part of the key: after paper3.db is restored an account can go bust again,
        # and that new bust must not look like evidence that was already handled
        extra = {"extras": True} if all(accts[a][2] == "copy" for a in aids) else {}
        copies = [a for a in aids if accts[a][2] == "copy"]
        if copies:
            extra["extra_accounts"] = copies
        out.append(_due(st, room, "bust", "bust:" + ",".join(f"{a}@{got[a]}" for a in aids), min(got.values()), cursors,
                        f"{STRATEGY_KO[s]}: 계좌 파산 " + ", ".join(aids)
                        + (" (복제 계좌)" if extra.get("extras") else ""), strategy=s, accounts=aids, **extra))
    return out


def _checkpoint(paper_ro, st: _Rooms, checkpoint_db: Optional[str] = None) -> list[Due]:
    """Day 30 / 60 / 90 ... since the run started. With ``checkpoint_db`` (the rooms tick always passes it) the
    meeting waits until the checkpoint job has stored that day's verdict (00:00 UTC of the run's start date + the
    days, paperbot/checkpoint.py), so the staff discuss the official result, not a guess before it."""
    every = st.p.checkpoint_every_days
    start = run_start(paper_ro)
    if start is None or every <= 0 or st.now < start:
        return []
    days = (st.now - start) // DAY_MS
    cp = days // every * every
    if cp < every or cp <= st.cursor_int("checkpoint:day"):
        return []
    extra = {}
    if checkpoint_db is not None:
        from .. import checkpoint as CP
        date = CP.day_str(CP.floor_day(start) + cp * DAY_MS)
        if CP.verdict(checkpoint_db, date) is None:
            return []
        extra["verdict_date"] = date
    return [_due(st, "team:lead", "checkpoint", f"checkpoint:{start}:{cp}", start + cp * DAY_MS,
                 {"checkpoint:day": str(cp)}, f"{cp}일 점검: 시작 후 {days}일째",
                 day=cp, days_elapsed=int(days), run_start=start, **extra)]


def weekly_slot(now_ms: int, index: int) -> int:
    """00:00 KST of the latest weekly-review day of the strategy with this index (index mod 7 =
    KST weekday, Monday = 0), today included."""
    return kst_day_start(now_ms) - ((kst_weekday(now_ms) - index % 7) % 7) * DAY_MS


def _weekly(paper_ro, st: _Rooms) -> list[Due]:
    """A strategy's weekly review is due on its weekday when it has >= weekly_min_trades closed trades
    since its last review. The evidence key is that weekday's date: a review that could not run on
    its day (AI budget used up, or stopped midway) stays due on the following days, until a round
    for that slot ends done / no_action; the next weekday opens a new slot. A strategy that only
    reaches the trade count after its day waits for its next weekday (reviews stay spread out)."""
    hwm = _trade_hwm(paper_ro)
    out = []
    for i, s in enumerate(STRATEGIES):
        room = strat_room(s)
        slot = weekly_slot(st.now, i)
        slot_day = kst_date(slot)
        key = f"weekly:{s}:{slot_day}"
        if st.handled(room, "weekly", key):
            continue
        cur = st.cursor_int(f"weekly:{room}")
        # trades closed by the end of the slot day decide whether the slot was due at all (the strategy's own
        # accounts and its copies; a review only the copies' trades open is an extras meeting)
        r = _one(paper_ro, "SELECT COUNT(*), SUM(a.kind = 'strategy') FROM trades t JOIN accounts a "
                           "ON a.account_id = t.account_id WHERE a.kind IN ('strategy', 'copy') AND a.strategy = ? "
                           "AND t.id > ? AND t.exit_time < ?", (s, cur, slot + DAY_MS))
        n_slot = 0 if r is None else int(r[0])
        n_orig = 0 if r is None else int(r[1] or 0)
        if n_slot < st.p.weekly_min_trades:
            continue
        n = _one(paper_ro, "SELECT COUNT(*) FROM trades t JOIN accounts a ON a.account_id = t.account_id "
                           "WHERE a.kind IN ('strategy', 'copy') AND a.strategy = ? AND t.id > ?", (s, cur))
        n = n_slot if n is None else int(n[0])
        cursors = {**_strategy_cursors(st, room, hwm), f"weekly:{room}": str(hwm)}
        late = "" if slot_day == kst_date(st.now) else f" ({slot_day} 검토를 미뤘던 것)"
        extra = {"extras": True} if n_orig < st.p.weekly_min_trades else {}
        out.append(_due(st, room, "weekly", key, slot, cursors,
                        f"{STRATEGY_KO[s]} 주간 검토: 지난 검토 뒤 거래 {n}건{late}", strategy=s, trades=n,
                        slot_day=slot_day, **extra))
    return out


def _tf_split(paper_ro, st: _Rooms) -> list[Due]:
    """Once per KST day from ``tf_split_hour_kst`` (window ``meeting_window_ms``): the strategies whose timeframe
    accounts disagree most (digest.tf_split), at most ``tf_split_per_day`` of them, none met about for this in
    the last ``tf_split_gap_ms`` (cursor ``tf_split:<room>``, the meeting's start). The key is the day: a meeting
    the budget could not start stays due within the window."""
    p = st.p
    if p.tf_split_hour_kst < 0 or paper_ro is None:
        return []
    s0 = slot_start(st.now, p.tf_split_hour_kst)
    if st.now - s0 >= p.meeting_window_ms:
        return []
    day = kst_date(s0)
    taken = sum(1 for r in st.rounds if r["trigger"] == "tf_split" and r["started_ts"] >= s0
                and r["status"] in ENDED_OK)
    if taken >= p.tf_split_per_day:
        return []               # the day's meetings are held: no need to read every closed trade again
    from .digest import tf_split
    try:
        got = tf_split(paper_ro, min_trades=p.tf_split_min_trades, min_spread_pct=p.tf_split_min_spread_pct)
    except Exception:  # noqa: BLE001  (unreadable paper3.db: no such meeting this tick)
        return []
    rows = {r["strategy"]: r for r in got.get("strategies") or []}
    out = []
    for s in got.get("split") or []:
        if len(out) + taken >= p.tf_split_per_day:
            break
        room = strat_room(s)
        key = f"tf_split:{s}:{day}"
        # what find_due would drop anyway does not take one of the day's places (another strategy gets it)
        if (st.handled(room, "tf_split", key) or st.room_full(room, "tf_split") or st.running_fresh(room, "tf_split")
                or len(st.failed_attempts(room, "tf_split", key)) >= p.max_attempts
                or st.key_waiting(room, "tf_split", key)):
            continue
        last = st.cursor_int(f"tf_split:{room}")
        if last and st.now - last < p.tf_split_gap_ms:
            continue
        r = rows[s]
        t = r["timeframes"]
        cursors = {**_strategy_cursors(st, room, _trade_hwm(paper_ro)), f"tf_split:{room}": st.now}
        out.append(_due(st, room, "tf_split", key, s0, cursors,
                        f"{STRATEGY_KO.get(s, s)} 봉 비교: {r['best_tf']} {r['best_pnl']:+,.0f}$ "
                        f"({t[r['best_tf']]['trades']}건) vs {r['worst_tf']} {r['worst_pnl']:+,.0f}$ "
                        f"({t[r['worst_tf']]['trades']}건)",
                        strategy=s, best_tf=r["best_tf"], worst_tf=r["worst_tf"], spread=r["spread"], slot_day=day))
    return out


# ---------------------------------------------------------------- weekly analyses, event review, daily debate
def analysis_slot(now_ms: int, weekday: int, hour_kst: int) -> int:
    """UTC ms of the latest ``weekday`` (Monday = 0) ``hour_kst``:00 KST at or before ``now_ms``."""
    s = weekly_slot(now_ms, weekday) + hour_kst * HOUR_MS
    return s if s <= now_ms else s - 7 * DAY_MS


def analysis_data(paper_ro, slot_ms: int, p: TriggerPolicy) -> dict:
    """Is there enough data for a weekly analysis meeting at ``slot_ms``? Closed trades of the strategy accounts
    in the 7 days before the slot and days since the run started (both as of the slot, so the answer for a slot
    never changes). {ok, trades, days, why}."""
    start = run_start(paper_ro)
    if start is None:
        return {"ok": False, "trades": 0, "days": 0.0, "why": "paper 실험이 아직 시작되지 않음"}
    days = max(0.0, (slot_ms - start) / DAY_MS)
    r = _one(paper_ro, "SELECT COUNT(*) FROM trades t JOIN accounts a ON a.account_id = t.account_id "
                       "WHERE a.kind = 'strategy' AND t.exit_time >= ? AND t.exit_time < ?", (slot_ms - 7 * DAY_MS, slot_ms))
    n = 0 if r is None else _int(r[0])
    why = []
    if days < p.analysis_min_days:
        why.append(f"실험 시작 뒤 {days:.1f}일(최소 {p.analysis_min_days}일)")
    if n < p.analysis_min_trades:
        why.append(f"지난 7일 매매법 계좌의 끝난 거래 {n}건(최소 {p.analysis_min_trades}건)")
    return {"ok": not why, "trades": n, "days": round(days, 1), "why": ", ".join(why)}


def _analysis_runs(st: _Rooms, trig: str) -> list[dict]:
    """The meetings of one weekly analysis that ended done / no_action or are running now, oldest first."""
    room = ANALYSES[trig][1]
    return [r for r in st.rounds if r["room_id"] == room and r["trigger"] == trig
            and (r["status"] in ENDED_OK or (r["status"] == "running" and not st.stale(r)))]


def analysis_week_runs(st: _Rooms, trig: str) -> list[dict]:
    """This KST week's (Monday 00:00 KST on) meetings of one weekly analysis."""
    wk0 = weekly_slot(st.now, 0)
    return [r for r in _analysis_runs(st, trig) if r["started_ts"] >= wk0]


def analysis_extra(paper_ro, st: _Rooms, trig: str) -> dict:
    """May the weekly analysis ``trig`` meet once more this KST week, today at its hour (owners' decision
    2026-10-04)? Not on its own weekday, at most ``analysis_extra_per_week`` extra and ``analysis_max_per_week``
    meetings in all in the KST week, at least ``analysis_extra_gap_days`` KST days after its last meeting, and at
    least ``analysis_extra_factor`` x ``analysis_min_trades`` closed strategy trades since that meeting started (as
    of today's slot). {ok, why, day, slot, new_trades, need, last_run, week_runs}."""
    p = st.p
    wd = ANALYSES[trig][0]
    hour = int(getattr(p, f"{trig}_hour_kst", -1))
    s0 = kst_day_start(st.now) + max(0, hour) * HOUR_MS
    week = analysis_week_runs(st, trig)
    runs = _analysis_runs(st, trig)
    last = max((r["started_ts"] for r in runs), default=None)
    need = p.analysis_extra_factor * p.analysis_min_trades
    out = {"ok": False, "day": kst_date(s0), "slot": s0, "need": need, "week_runs": len(week),
           "last_run": None if last is None else kst_date(last), "new_trades": None}
    if hour < 0:
        return {**out, "why": "꺼짐"}
    if kst_weekday(st.now) == wd:
        return {**out, "why": "오늘은 정해진 요일(추가 회의는 다른 날에만)"}
    if st.now < s0:
        return {**out, "why": f"오늘 {hour:02d}:00 전"}
    if len(week) >= p.analysis_max_per_week:
        return {**out, "why": f"이번 주에 이미 {len(week)}번 열림(주 {p.analysis_max_per_week}번까지)"}
    if sum(1 for r in week if ":extra:" in str(r["key"] or "")) >= p.analysis_extra_per_week:
        return {**out, "why": "이번 주 추가 회의를 이미 함"}
    if last is None:
        return {**out, "why": "아직 한 번도 열리지 않음(정해진 요일 회의가 먼저)"}
    gap = (kst_day_start(s0) - kst_day_start(last)) // DAY_MS
    if gap < p.analysis_extra_gap_days:
        return {**out, "why": f"지난 회의({kst_date(last)}) 뒤 {gap}일(최소 {p.analysis_extra_gap_days}일)"}
    r = _one(paper_ro, "SELECT COUNT(*) FROM trades t JOIN accounts a ON a.account_id = t.account_id "
                       "WHERE a.kind = 'strategy' AND t.exit_time >= ? AND t.exit_time < ?", (last, s0))
    n = 0 if r is None else _int(r[0])
    out["new_trades"] = n
    if n < need:
        return {**out, "why": f"지난 회의 뒤 새 거래 {n:,}건(추가 회의는 {need:,}건 이상)"}
    return {**out, "ok": True, "why": f"지난 회의({kst_date(last)}) 뒤 새 거래 {n:,}건(기준 {need:,}건 이상)"}


def _weekly_analysis(paper_ro, st: _Rooms) -> list[Due]:
    """The four weekly analysis meetings (``ANALYSES``): on their KST weekday from their hour, once per week (the
    key is the slot's date: a meeting the budget deferred or stopped stays due until it ends done / no_action or
    the next week's slot replaces it), only with enough data as of the slot (``analysis_data``). Besides, once in a
    KST week on another day when much new data came in (``analysis_extra``, key ``<trigger>:extra:<date>``, due that
    day from its hour); never more than ``analysis_max_per_week`` meetings of one kind in a KST week."""
    p, out = st.p, []
    if paper_ro is None:
        return out
    for trig, (wd, room) in ANALYSES.items():
        hour = int(getattr(p, f"{trig}_hour_kst", -1))
        if trig not in p.enabled or hour < 0:
            continue
        full = len(analysis_week_runs(st, trig)) >= p.analysis_max_per_week
        s0 = analysis_slot(st.now, wd, hour)
        day = kst_date(s0)
        key = f"{trig}:{day}"
        if not full and not st.handled(room, trig, key):
            info = analysis_data(paper_ro, s0, p)
            if info["ok"]:          # otherwise rooms.store_skipped keeps why (meetings:skipped); nothing to retry
                late = "" if day == kst_date(st.now) else f" ({day} 회의를 미뤘던 것)"
                out.append(_due(st, room, trig, key, s0, {f"analysis:{trig}": day},
                                f"{ANALYSIS_KO[trig]} ({hour:02d}:00): 지난 7일 매매법 계좌의 끝난 거래 "
                                f"{info['trades']:,}건{late}",
                                slot=day, slot_start=s0, trades=info["trades"], days_running=info["days"]))
                continue            # the regular meeting first; an extra one is never due beside it
        ex = analysis_extra(paper_ro, st, trig)
        if ex["ok"]:
            out.append(_due(st, room, trig, f"{trig}:extra:{ex['day']}", ex["slot"], {f"analysis_extra:{trig}": ex["day"]},
                            f"{ANALYSIS_KO[trig]} 추가 회의 ({hour:02d}:00): {ex['why']}", slot=ex["day"],
                            slot_start=ex["slot"], trades=ex["new_trades"], extra_run=True, why_ko=ex["why"]))
    return out


def _event_review(paper_ro, st: _Rooms) -> list[Due]:
    """The market team's review of a US release (data/macro_events.csv): from ``event_review_hour_kst`` of the KST
    day after the release, for ``event_review_window_ms``, once per event (key = kind and time). Only when the paper
    run had started before the event's window (``event_before_ms`` before the release)."""
    p = st.p
    if p.event_review_hour_kst < 0 or paper_ro is None:
        return []
    from .. import events as EV
    try:
        evs = EV.all_events()
    except Exception:  # noqa: BLE001  (an unreadable calendar: no event meeting)
        return []
    start = run_start(paper_ro)
    out = []
    for ev in evs:
        s0 = kst_day_start(ev.ts_ms) + DAY_MS + p.event_review_hour_kst * HOUR_MS
        if not s0 <= st.now < s0 + p.event_review_window_ms:
            continue
        key = f"event:{ev.kind}:{ev.ts_ms}"
        if st.handled("team:market", "event_review", key):
            continue
        if start is None or start > ev.ts_ms - p.event_before_ms:
            continue                # the run did not cover the event's window (rooms.store_skipped says so)
        hm = dt.datetime.fromtimestamp((ev.ts_ms + KST_OFFSET_MS) / 1000, dt.timezone.utc).strftime("%m/%d %H:%M")
        out.append(_due(st, "team:market", "event_review", key, s0, {"event_review:last": ev.ts_ms},
                        f"경제지표 복기: {EV.KIND_KO.get(ev.kind, ev.kind)} 발표({hm} 한국 시간) 전후 우리 계좌의 반응",
                        event={"kind": ev.kind, "ts_ms": ev.ts_ms, "name_ko": EV.KIND_KO.get(ev.kind, ev.kind)},
                        slot=kst_date(s0), slot_start=s0))
    return out


def bull_bear_coin(ms: int) -> str:
    """The coin of the KST day containing ``ms``: one a day, in ``BULL_BEAR_COINS`` order."""
    return BULL_BEAR_COINS[((kst_day_start(ms) + KST_OFFSET_MS) // DAY_MS) % len(BULL_BEAR_COINS)]


def _bull_bear(st: _Rooms) -> list[Due]:
    """The market team's daily bull vs bear debate: once per KST day from ``bull_bear_hour_kst`` (window
    ``meeting_window_ms``), on the day's coin."""
    p = st.p
    if p.bull_bear_hour_kst < 0:
        return []
    s0 = slot_start(st.now, p.bull_bear_hour_kst)
    if st.now - s0 >= p.meeting_window_ms:
        return []
    day = kst_date(s0)
    ck = "sched:bull_bear:team:market"
    if (st.cursor(ck) or "") >= day:
        return []
    sym = bull_bear_coin(s0)
    return [_due(st, "team:market", "bull_bear", f"bull_bear:{day}", s0, {ck: day},
                 f"낙관·비관 토론 ({p.bull_bear_hour_kst:02d}:00): {sym.replace('USDT', '')} 앞으로 24시간 (기록·채점만, 거래 없음)",
                 symbol=sym, slot=day, slot_start=s0)]


def skipped_status(paper_ro, now_ms: int, p: TriggerPolicy, agents_conn=None) -> dict:
    """Why each weekly analysis (this week's slot, once its hour has come) or the event reviews of the last week did
    or did not open: {trigger: {slot, ok, trades, days, why, extra: {ok, why, new_trades, need, ...}},
    'event_review': [{event, why}]}. ``extra`` (with ``agents_conn``): whether an extra meeting may open today
    (``analysis_extra``). Code only; the rooms tick stores it in the cursor ``SKIPPED_CURSOR`` (find_due never
    writes)."""
    out: dict = {}
    if paper_ro is None:
        return out
    st = _Rooms(agents_conn, now_ms, p) if agents_conn is not None else None
    for trig, (wd, _room) in ANALYSES.items():
        hour = int(getattr(p, f"{trig}_hour_kst", -1))
        if trig not in p.enabled or hour < 0:
            continue
        s0 = analysis_slot(now_ms, wd, hour)
        info = analysis_data(paper_ro, s0, p)
        out[trig] = {"slot": kst_date(s0), **info}
        if st is not None:
            ex = analysis_extra(paper_ro, st, trig)
            out[trig]["extra"] = {k: ex[k] for k in ("ok", "why", "day", "new_trades", "need", "last_run", "week_runs")}
    if p.event_review_hour_kst >= 0 and "event_review" in p.enabled:
        from .. import events as EV
        start = run_start(paper_ro)
        evs = []
        try:
            for ev in EV.all_events():
                s0 = kst_day_start(ev.ts_ms) + DAY_MS + p.event_review_hour_kst * HOUR_MS
                if s0 <= now_ms < s0 + 7 * DAY_MS and (start is None or start > ev.ts_ms - p.event_before_ms):
                    evs.append({"event": f"{ev.kind} {ev.ts_utc}", "why": "그 발표 시간대에 paper 실험이 아직 돌지 않음"})
        except Exception:  # noqa: BLE001
            pass
        if evs:
            out["event_review"] = evs
    return out


def _lab_accounts(paper_ro, st: _Rooms) -> list[Due]:
    """The new-strategy accounts (kind 'newlab') in team:lab: a loss cluster (same thresholds as a strategy
    room, cursor ``loss:team:lab``), a bust (cursor ``bust:<account>``) and a weekly review on Sunday KST
    (cursor ``weekly:team:lab``). Every one is an extras meeting (their own daily line)."""
    p, room = st.p, LAB_ROOM
    accts = {aid: tf for aid, tf in _rows(paper_ro, "SELECT account_id, timeframe FROM accounts WHERE kind = 'newlab'")}
    if not accts:
        return []
    from ..cards import card, tag_stats
    hwm = _trade_hwm(paper_ro)
    out: list[Due] = []
    sel = ("SELECT t.id, t.account_id, t.exit_time, t.pnl, t.data, a.strategy, a.timeframe FROM trades t "
           "JOIN accounts a ON a.account_id = t.account_id WHERE a.kind = 'newlab' AND t.id > ? AND t.id <= ? ")
    if "loss_cluster" in p.enabled:
        rows = _rows(paper_ro, sel + "AND t.exit_time >= ? AND t.pnl < 0 ORDER BY t.id",
                     (st.cursor_int(f"loss:{room}"), hwm, st.now - p.loss_lookback_ms))
        last = st.last_ok_start(room, "loss_cluster")
        if rows and (last is None or st.now - last >= p.loss_min_gap_ms):
            rt = _round_trip(paper_ro)
            cards = []
            for r in rows:
                try:
                    cards.append(card(r[1], json.loads(r[4]), rt))
                except (KeyError, TypeError, ValueError):
                    pass
            top = sorted(({"tag": r["tag"], "losses": r["losses"]} for r in tag_stats(cards)
                          if r["losses"] >= p.loss_tag_min_count), key=lambda r: -r["losses"])
            if len(rows) >= p.loss_min_count or top:
                by_acct: dict[str, int] = {}
                for r in rows:
                    by_acct[r[1]] = by_acct.get(r[1], 0) + 1
                text = "새 매매법 계좌: 새 손실 " + f"{len(rows)}건 (" + ", ".join(f"{a} {n}건" for a, n in by_acct.items()) + ")"
                if top:
                    text += " · 많이 나온 특징: " + ", ".join(f"{t['tag']} {t['losses']}건" for t in top[:3])
                out.append(_due(st, room, "loss_cluster", f"loss:lab:{rows[-1][0]}@{rows[-1][2]}", min(r[2] for r in rows),
                                {f"loss:{room}": str(hwm)}, text, extras=True, losses=len(rows),
                                trade_ids=[r[0] for r in rows][-p.max_items:], accounts=sorted(by_acct), top_tags=top,
                                oldest_exit=min(r[2] for r in rows), newest_exit=max(r[2] for r in rows)))
    if "bust" in p.enabled:
        got = {aid: ts for aid, ts in busts_of(paper_ro).items() if aid in accts and st.cursor(f"bust:{aid}") is None}
        if got:
            aids = sorted(got)
            out.append(_due(st, room, "bust", "bust:" + ",".join(f"{a}@{got[a]}" for a in aids), min(got.values()),
                            {f"loss:{room}": str(hwm), **{f"bust:{a}": str(got[a]) for a in aids}},
                            "새 매매법 계좌 파산: " + ", ".join(aids), extras=True, accounts=aids))
    if "weekly" in p.enabled:
        slot = weekly_slot(st.now, LAB_WEEKDAY)
        slot_day = kst_date(slot)
        key = f"weekly:lab:{slot_day}"
        if not st.handled(room, "weekly", key):
            cur = st.cursor_int(f"weekly:{room}")
            r = _one(paper_ro, "SELECT COUNT(*) FROM trades t JOIN accounts a ON a.account_id = t.account_id "
                               "WHERE a.kind = 'newlab' AND t.id > ? AND t.exit_time < ?", (cur, slot + DAY_MS))
            if r is not None and int(r[0]) >= p.weekly_min_trades:
                n = _one(paper_ro, "SELECT COUNT(*) FROM trades t JOIN accounts a ON a.account_id = t.account_id "
                                   "WHERE a.kind = 'newlab' AND t.id > ?", (cur,))
                n = int(r[0]) if n is None else int(n[0])
                late = "" if slot_day == kst_date(st.now) else f" ({slot_day} 검토를 미뤘던 것)"
                out.append(_due(st, room, "weekly", key, slot, {f"loss:{room}": str(hwm), f"weekly:{room}": str(hwm)},
                                f"새 매매법 계좌 주간 검토: 지난 검토 뒤 거래 {n}건{late}", extras=True, trades=n,
                                slot_day=slot_day))
    return out


def _scheduled(st: _Rooms) -> list[Due]:
    p, out = st.p, []
    plan = [("morning", p.morning_hour_kst, (("team:market", "아침 회의 (08:00)"),)),
            ("ranking", p.ranking_hour_kst, (("team:review", f"순위 검토 ({p.ranking_hour_kst:02d}:00): 잔고 상위·하위 매매법"),)),
            ("evening", p.evening_hour_kst, (("team:review", "저녁 점검 (22:00): 손익 복기"),
                                            ("team:lead", "저녁 점검 (22:00): 팀장 요약")))]
    for name, hour, rooms in plan:
        if name not in p.enabled or hour < 0:
            continue
        s0 = slot_start(st.now, hour)
        if st.now - s0 >= p.meeting_window_ms:
            continue
        day = kst_date(s0)
        key = f"{name}:{day}"
        for seq, (room, text) in enumerate(rooms):
            ck = f"sched:{name}:{room}"
            if (st.cursor(ck) or "") >= day:
                continue
            d = _due(st, room, name, key, s0, {ck: day}, text, slot=day, slot_start=s0)
            d.data["seq"] = seq
            if seq > 0:
                d.data["after"] = {"room_id": rooms[seq - 1][0], "key": key}
            out.append(d)
    return out


def research_gap(st: _Rooms, every: int) -> int:
    """The wait after the lab's last meeting: ``every``, doubled for each meeting in a row (from the second) in
    which the inventor proposed nothing, up to ``research_idle_max_ms`` (2026-10-03: 18 empty meetings in a
    day). A meeting with a candidate, or an owners' post in the lab (its own trigger), starts over."""
    empty = 0
    for r in sorted((r for r in st.rounds if r["room_id"] == LAB_ROOM and r["trigger"] in ("research", "owner")
                     and r["status"] in ENDED_OK), key=lambda r: -r["started_ts"]):
        if r["trigger"] == "owner" or r["candidates"] != 0:     # the owners spoke in the lab, or a candidate came
            break
        empty += 1
    if empty < 2:
        return every
    return max(every, min(every * 2 ** (empty - 1), st.p.research_idle_max_ms))


def _research(st: _Rooms) -> list[Due]:
    """The lab meets once per ``research_every_ms`` slot of the KST day, at most once per that period.
    The key is the slot: a slot the budget could not start (pacing, spare calls used up) is simply
    skipped; no cursor (nothing to catch up). Whether the lab can test at all (cache present, tests left
    that can still pass) and whether the budget can carry it is decided by the caller (``can_start``)."""
    every = int(st.p.research_every_ms or 0)
    if every <= 0:
        return []
    idx = (st.now - st.day_start) // every
    slot = st.day_start + idx * every
    last = st.last_ok_start(LAB_ROOM, "research")
    if last is not None and st.now - last < research_gap(st, every):
        return []
    hm = dt.datetime.fromtimestamp((slot + KST_OFFSET_MS) / 1000, dt.timezone.utc).strftime("%H:%M")
    return [_due(st, LAB_ROOM, "research", f"research:{kst_date(st.now)}:{idx}", slot, {},
                 f"새 매매법 연구 ({hm} 차례, 남는 AI 한도로)", slot=int(idx), slot_start=int(slot))]


def move_of(m: dict) -> float:
    """The larger of the hour's rise (high) and fall (low) against the price an hour before, signed."""
    up, down = m["high"] / m["ref"] - 1, m["low"] / m["ref"] - 1
    return up if abs(up) >= abs(down) else down


def _market_move(market: dict, st: _Rooms) -> list[Due]:
    """``market``: {symbol: {"t": close time of the last closed 5m bar, "ref": close an hour before it,
    "high", "low", "last"}} (rooms.fetch_market_moves). Every coin past its threshold and not met about in
    the last ``market_move_gap_ms`` goes into one market-team meeting."""
    p = st.p
    today = sum(1 for r in st.rounds if r["trigger"] == "market_move" and r["started_ts"] >= st.day_start
                and st._counted(r))
    if today >= p.market_move_max_per_day:
        return []
    moved, cursors, t_max = [], {}, 0
    for sym in sorted(market or {}):
        m = market[sym]
        try:
            mv = move_of(m)
        except (KeyError, TypeError, ZeroDivisionError):
            continue
        if abs(mv) < p.market_move_pct.get(sym, p.market_move_pct_other):
            continue
        last = st.cursor_int(f"move:{sym}")
        if last and st.now - last < p.market_move_gap_ms:
            continue
        moved.append({"symbol": sym, "move": round(mv, 5), "ref": m["ref"], "high": m["high"], "low": m["low"],
                      "last": m["last"], "t": int(m["t"])})
        cursors[f"move:{sym}"] = st.now
        t_max = max(t_max, int(m["t"]))
    if not moved:
        return []
    text = ", ".join(f"{x['symbol'].replace('USDT', '')} 1시간 {x['move'] * 100:+.1f}%" for x in moved)
    key = "move:" + "+".join(x["symbol"] for x in moved) + f":{t_max // HOUR_MS}"
    return [_due(st, "team:market", "market_move", key, t_max, cursors, f"시세 급변: {text}", moves=moved)]


def _due(st: _Rooms, room: str, trigger: str, key: str, evidence_ts: int, cursors: dict, summary_ko: str,
         **extra) -> Due:
    data = {"key": key, "evidence_ts": int(evidence_ts), "cursors": {k: str(v) for k, v in cursors.items()},
            "class": TRIGGER_CLASS[trigger], "kst_day": kst_date(st.now), "summary_ko": summary_ko,
            "retry_of": None, **extra}
    return Due(room_id=room, trigger=trigger, priority=int(st.p.priorities.get(trigger, PRIORITY[trigger])),
               data=data, meeting=trigger)


# ---------------------------------------------------------------- main entry
def find_due(paper_ro: Optional[sqlite3.Connection], daily_ro: Optional[sqlite3.Connection],
             agents_conn: sqlite3.Connection, inbox_ro: Optional[sqlite3.Connection], now_ms: int,
             policy: Optional[TriggerPolicy] = None, *, defer_classes: Iterable[str] = (),
             defer_triggers: Iterable[str] = (), skip_rooms: Iterable[str] = (),
             can_start: Optional[Callable[[Due], bool]] = None, market: Optional[dict] = None,
             checkpoint_db: Optional[str] = None) -> list[Due]:
    """Rounds to run now, sorted by (priority, bust before loss_cluster, oldest evidence). Reads only.
    ``defer_classes`` / ``defer_triggers``: what the caller cannot start now (its AI budget is used
    up or paced), left out before the per-tick pick so it never hides other meetings;
    ``can_start``: the caller's exact check of one meeting (e.g. its AI budget can carry that
    meeting's shortest form); meetings it refuses are left out BEFORE the per-tick cut, so meetings
    that cannot start never take the slots of ones that can;
    ``skip_rooms``: rooms that already met in the caller's current tick;
    ``market``: the last hour of each coin for ``market_move`` (fetched by the caller; None = not due);
    ``checkpoint_db``: checkpoint.db (read-only); the checkpoint meeting waits for its verdict (None: no wait)."""
    p = policy or TriggerPolicy()
    st = _Rooms(agents_conn, now_ms, p)
    if st.usage_paused() or st.transient_paused():
        return []
    defer, skip = set(defer_classes), set(skip_rooms)
    defer_t = set(defer_triggers)
    found: list[Due] = []
    if "incident" in p.enabled:
        found += _incident(paper_ro, daily_ro, st)
    if "owner" in p.enabled:
        found += _owner(inbox_ro, paper_ro, st)
    if "loss_cluster" in p.enabled:
        found += _loss_cluster(paper_ro, st)
    if "bust" in p.enabled:
        found += _bust(paper_ro, st)
    if "checkpoint" in p.enabled:
        found += _checkpoint(paper_ro, st, checkpoint_db)
    if "weekly" in p.enabled:
        found += _weekly(paper_ro, st)
    if "tf_split" in p.enabled:
        found += _tf_split(paper_ro, st)
    found += _scheduled(st)
    found += _weekly_analysis(paper_ro, st)
    if "event_review" in p.enabled:
        found += _event_review(paper_ro, st)
    if "bull_bear" in p.enabled:
        found += _bull_bear(st)
    if "market_move" in p.enabled and market:
        found += _market_move(market, st)
    if "research" in p.enabled:
        found += _research(st)
    found += _lab_accounts(paper_ro, st)

    ok: list[Due] = []
    for d in found:
        key = d.data["key"]
        if d.data["class"] in defer or d.trigger in defer_t or d.room_id in skip:
            continue
        if st.class_blocked(d.data["class"]) or st.running_fresh(d.room_id, d.trigger):
            continue
        if st.handled(d.room_id, d.trigger, key):
            continue
        failed = st.failed_attempts(d.room_id, d.trigger, key)
        if len(failed) >= p.max_attempts:
            continue
        if st.key_waiting(d.room_id, d.trigger, key):
            continue            # this meeting keeps failing by itself: it waits its own pause
        if can_start is not None and not can_start(d):
            continue            # e.g. its AI budget cannot carry it now: found again on a later tick
        if failed:
            d.data["retry_of"] = failed[-1]["round_id"]
            d.data["summary_ko"] = "(중단된 회의 다시 시작) " + d.data["summary_ko"]
        ok.append(d)
    # within a priority a bust (an account at zero) goes before routine loss clusters
    ok.sort(key=lambda d: (d.priority, 0 if d.trigger == "bust" else 1, d.data["evidence_ts"],
                           d.data.get("seq", 0), d.room_id))

    picked: list[Due] = []
    per_room: dict[str, int] = {}
    extras_used = st.extras_today()
    for d in ok:
        if len(picked) >= p.max_rounds_per_tick:
            break
        room = d.room_id
        if per_room.get(room, 0) >= p.max_per_room_per_tick:
            continue
        if d.data.get("extras"):
            # opened only by extra accounts' trades: their own daily line, never the room's slots
            if extras_used >= p.extras_meetings_per_day:
                continue
        elif st.room_full(room, d.trigger, per_room.get(room, 0)):
            continue
        after = d.data.get("after")
        if after and not (st.settled(after["room_id"], d.trigger, after["key"])
                          or st.room_full(after["room_id"], d.trigger)
                          or any(x.room_id == after["room_id"] and x.data["key"] == after["key"]
                                 for x in picked)):
            continue            # the lead meets after the review team
        picked.append(d)
        per_room[room] = per_room.get(room, 0) + 1
        extras_used += 1 if d.data.get("extras") else 0
    return picked


# ---------------------------------------------------------------- the caller's side (rounds + cursors)
def trigger_data(due: Due) -> str:
    return json.dumps(due.data, ensure_ascii=False, sort_keys=True, default=str)


def _newer(old: Optional[str], new: str) -> bool:
    if old is None:
        return True
    try:
        return int(new) > int(old)
    except (TypeError, ValueError):
        return str(new) > str(old)


def advance_cursors(agents_conn: sqlite3.Connection, due_or_data: Union[Due, dict], commit: bool = True) -> dict:
    """Write the evidence high-water marks of a finished round. Cursors only move forward
    (numbers by value, days by text). Returns what was written."""
    data = due_or_data.data if isinstance(due_or_data, Due) else _json(due_or_data)
    wrote = {}
    for k, v in (data.get("cursors") or {}).items():
        r = agents_conn.execute("SELECT v FROM cursors WHERE k = ?", (k,)).fetchone()
        if _newer(None if r is None else r[0], str(v)):
            agents_conn.execute("INSERT INTO cursors (k, v) VALUES (?, ?) "
                                "ON CONFLICT(k) DO UPDATE SET v = excluded.v", (k, str(v)))
            wrote[k] = str(v)
    if commit:
        agents_conn.commit()
    return wrote


def expire_stale_rounds(agents_conn: sqlite3.Connection, now_ms: int,
                        policy: Optional[TriggerPolicy] = None, *, stale_ms: Optional[int] = None,
                        detail: str = "회의 도중 멈춤 (2시간 넘게 진행 중)") -> list[int]:
    """Mark 'running' rounds older than ``policy.stale_ms`` (or ``stale_ms``) as 'failed' (a tick died
    during them), so the dashboard stops showing them as live; each counts as one failed attempt (the
    evidence is tried once more). The rooms tick calls it with ``stale_ms=0`` once it holds the tick
    lock: no other pass can own a 'running' round then, so every one is failed whatever its start time
    (after the clock stepped back, a dead pass's round can have started 'later' than now)."""
    p = policy or TriggerPolicy()
    age = p.stale_ms if stale_ms is None else int(stale_ms)
    if age <= 0:
        ids = [int(r[0]) for r in _rows(agents_conn, "SELECT round_id FROM rounds WHERE status = 'running'", ())]
    else:
        ids = [int(r[0]) for r in _rows(agents_conn, "SELECT round_id FROM rounds WHERE status = 'running' "
                                                     "AND started_ts <= ?", (now_ms - age,))]
    why = json.dumps({"reason": "stale", "detail": detail}, ensure_ascii=False)
    for rid in ids:
        agents_conn.execute("UPDATE rounds SET status = 'failed', ended_ts = ?, decision = ? WHERE round_id = ?",
                            (int(now_ms), why, rid))
    if ids:
        agents_conn.commit()
    return ids


def begin_round(agents_conn: sqlite3.Connection, due: Due, now_ms: int) -> int:
    """Insert the 'running' round with its trigger_data (evidence and cursors) and commit,
    before the first model call."""
    cur = agents_conn.execute("INSERT INTO rounds (room_id, trigger, trigger_data, started_ts, status, calls, "
                              "tokens) VALUES (?, ?, ?, ?, 'running', 0, 0)",
                              (due.room_id, due.trigger, trigger_data(due), int(now_ms)))
    agents_conn.commit()
    return int(cur.lastrowid)


def finish_round(agents_conn: sqlite3.Connection, round_id: int, status: str, now_ms: int,
                 decision: Optional[dict] = None, calls: Optional[int] = None,
                 tokens: Optional[int] = None) -> dict:
    """End a round; for 'done' / 'no_action' also advance the cursors stored in its
    trigger_data, in the same transaction. 'failed' and 'stopped_budget' leave the
    cursors, so the trigger fires again (once, or on the next KST day)."""
    r = agents_conn.execute("SELECT trigger_data FROM rounds WHERE round_id = ?", (round_id,)).fetchone()
    if r is None:
        raise KeyError(round_id)
    sets, args = ["ended_ts = ?", "status = ?"], [int(now_ms), status]
    if decision is not None:
        sets.append("decision = ?")
        args.append(json.dumps(decision, ensure_ascii=False, default=str))
    if calls is not None:
        sets.append("calls = ?")
        args.append(int(calls))
    if tokens is not None:
        sets.append("tokens = ?")
        args.append(int(tokens))
    agents_conn.execute(f"UPDATE rounds SET {', '.join(sets)} WHERE round_id = ?", (*args, round_id))
    wrote = advance_cursors(agents_conn, _json(r[0]), commit=False) if status in ENDED_OK else {}
    agents_conn.commit()
    return wrote


# ---------------------------------------------------------------- paper3.db replaced (restore, new run)
PAPER_FP = "paper:fingerprint"
TRADE_CURSOR_PREFIXES = ("loss:", "weekly:")
ALERT_CURSOR = "incident:alert_rowid"


def _q1(paper_ro: sqlite3.Connection, sql: str, args: Iterable = ()) -> Optional[tuple]:
    """One row; raises LookupError when paper3.db cannot be read (never mistaken for 'empty')."""
    try:
        r = paper_ro.execute(sql, tuple(args)).fetchone()
    except sqlite3.DatabaseError as exc:
        raise LookupError(str(exc)) from None
    return tuple(r) if r else None


def _q1_tables(paper_ro: Optional[sqlite3.Connection], sql: str, args: Iterable = ()) -> Optional[tuple]:
    """``_q1`` where a missing table (an older or brand-new paper3.db) reads as no row."""
    if paper_ro is None:
        return None
    try:
        return _q1(paper_ro, sql, args)
    except LookupError as exc:
        if "no such table" in str(exc):
            return None
        raise


def _paper_cursors(agents_conn: sqlite3.Connection) -> dict[str, str]:
    return {k: v for k, v in _rows(agents_conn, "SELECT k, v FROM cursors WHERE k LIKE 'loss:%' OR k LIKE 'weekly:%' "
                                                "OR k LIKE 'bust:%' OR k IN (?, 'checkpoint:day')", (ALERT_CURSOR,))}


def paper_fingerprint(paper_ro: Optional[sqlite3.Connection], agents_conn: sqlite3.Connection) -> Optional[dict]:
    """What the trigger cursors stand on in paper3.db: the run start, the newest trade [id, exit_time]
    and alert [rowid, ts], and the time of the row each trade / alert cursor points at ("at").
    None when paper3.db is missing or cannot be read."""
    if paper_ro is None:
        return None
    try:
        t = _q1(paper_ro, "SELECT id, exit_time FROM trades ORDER BY id DESC LIMIT 1")
        a = _q1(paper_ro, "SELECT rowid, ts FROM alerts ORDER BY rowid DESC LIMIT 1")
        at: dict[str, int] = {}
        for k, v in _paper_cursors(agents_conn).items():
            n = _int(v)
            if n <= 0:
                continue
            if k.startswith(TRADE_CURSOR_PREFIXES):
                r = _q1(paper_ro, "SELECT exit_time FROM trades WHERE id = ?", (n,))
            elif k == ALERT_CURSOR:
                r = _q1(paper_ro, "SELECT ts FROM alerts WHERE rowid = ?", (n,))
            else:
                continue
            if r is not None and r[0] is not None:
                at[k] = int(r[0])
        run = run_start(paper_ro, strict=True)
    except LookupError:
        return None
    return {"run": run, "t": [_int(t[0]), _int(t[1])] if t else [0, 0],
            "a": [_int(a[0]), _int(a[1])] if a else [0, 0], "at": at}


def reconcile_paper_cursors(agents_conn: sqlite3.Connection, paper_ro: Optional[sqlite3.Connection]) -> dict:
    """paper3.db replaced by an older copy (restore from backup) or by a new run: its trade ids and
    alert rowids restart, so new losses, busts and incidents could carry ids the cursors already
    count as seen, and no meeting would open. Detected when the newest trade / alert seen last tick
    (``PAPER_FP``) is gone or has another time, the run start changed, or the highest id is below a
    cursor. Then (``set_cursor``-style, backwards too):
      - every loss:* / weekly:* cursor moves to the last trade not newer (by exit time) than the one
        it stood on (0 when the run changed): handled trades stay handled, newer ones are read;
      - incident:alert_rowid likewise by alert time;
      - bust:<account> cursors whose bust is no longer in paper3.db are dropped (all of them when
        the run changed), so a new bust opens a meeting; checkpoint:day restarts at 0 for a new run.
    The evidence keys carry times (triggers above), so new evidence never matches a handled key.
    An unreadable paper3.db changes nothing. Returns what changed ({key: new value or None})."""
    if paper_ro is None:
        return {}
    row = _one(agents_conn, "SELECT v FROM cursors WHERE k = ?", (PAPER_FP,))
    fp = _json(row[0]) if row else {}
    try:
        top_t = _int(_q1(paper_ro, "SELECT COALESCE(MAX(id), 0) FROM trades")[0])
        top_a = _int(_q1(paper_ro, "SELECT COALESCE(MAX(rowid), 0) FROM alerts")[0])

        def moved(key: str, sql: str) -> bool:
            old = fp.get(key)
            if not (isinstance(old, list) and len(old) == 2 and _int(old[0]) > 0):
                return False
            r = _q1(paper_ro, sql, (_int(old[0]),))
            return r is None or _int(r[0]) != _int(old[1])
        run = run_start(paper_ro, strict=True)          # unreadable: change nothing (LookupError)
        run_changed = fp.get("run") is not None and run is not None and fp.get("run") != run
        curs = _paper_cursors(agents_conn)
        trade_keys = [k for k in curs if k.startswith(TRADE_CURSOR_PREFIXES)]
        replaced = (run_changed or moved("t", "SELECT exit_time FROM trades WHERE id = ?")
                    or moved("a", "SELECT ts FROM alerts WHERE rowid = ?")
                    or any(_int(curs[k]) > top_t for k in trade_keys) or _int(curs.get(ALERT_CURSOR)) > top_a)
        if not replaced:
            return {}
        at = fp.get("at") if isinstance(fp.get("at"), dict) else {}
        last_t = fp["t"][1] if isinstance(fp.get("t"), list) and len(fp["t"]) == 2 and _int(fp["t"][0]) > 0 else None
        last_a = fp["a"][1] if isinstance(fp.get("a"), list) and len(fp["a"]) == 2 and _int(fp["a"][0]) > 0 else None
        changed: dict[str, Optional[str]] = {}
        for k in trade_keys:
            ref = None if run_changed else at.get(k, last_t)
            if run_changed:
                new = 0
            elif ref is None:              # nothing known about its time: what is there now counts as seen
                new = min(_int(curs[k]), top_t)
            else:
                new = _int(_q1(paper_ro, "SELECT COALESCE(MAX(id), 0) FROM trades WHERE exit_time <= ?",
                               (_int(ref),))[0])
            if str(new) != str(curs[k]):
                changed[k] = str(new)
        if ALERT_CURSOR in curs:
            ref = at.get(ALERT_CURSOR, last_a)
            new = (min(_int(curs[ALERT_CURSOR]), top_a) if ref is None else
                   _int(_q1(paper_ro, "SELECT COALESCE(MAX(rowid), 0) FROM alerts WHERE ts <= ?", (_int(ref),))[0]))
            if str(new) != str(curs[ALERT_CURSOR]):
                changed[ALERT_CURSOR] = str(new)
        still = {} if run_changed else busts_of(paper_ro)
        for k in curs:
            if k.startswith("bust:") and k[len("bust:"):] not in still:
                changed[k] = None
        if run_changed and _int(curs.get("checkpoint:day")) != 0:
            changed["checkpoint:day"] = "0"
    except LookupError:
        return {}
    for k, v in changed.items():
        if v is None:
            agents_conn.execute("DELETE FROM cursors WHERE k = ?", (k,))
        else:
            agents_conn.execute("INSERT INTO cursors (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                                (k, v))
    agents_conn.commit()
    return changed


def store_paper_fingerprint(agents_conn: sqlite3.Connection, paper_ro: Optional[sqlite3.Connection]) -> Optional[dict]:
    """Remember what the cursors stand on now (``paper_fingerprint``), for the next tick's check.
    While paper3.db has no run start yet (a new run's file before its accounts are committed, or a
    crash loop at that point) the run start of the last fingerprint is kept, so the tick that first
    sees the new accounts still finds the run changed (checkpoint:day back to 0)."""
    fp = paper_fingerprint(paper_ro, agents_conn)
    if fp is None:
        return None
    r = _one(agents_conn, "SELECT v FROM cursors WHERE k = ?", (PAPER_FP,))
    if fp.get("run") is None and r is not None:
        fp["run"] = _json(r[0]).get("run")
    text = json.dumps(fp, sort_keys=True)
    if r is None or r[0] != text:
        agents_conn.execute("INSERT INTO cursors (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                            (PAPER_FP, text))
        agents_conn.commit()
    return fp
