"""Extra paper accounts next to the originals: started from the owners' approved proposals, never changing them.

    python -m paperbot.extras status --db paper3.db

Two kinds (docs/extra-accounts.md):
- copy (``kind='copy'``, id ``"<S>@<tf>~c<n>"``): one of the 36 strategies on one timeframe with exactly one
  lab-template change: ``stop_atr`` k (initial stop k x ATR14), ``lock_start`` first_lock (first step of the
  profit lock), ``skip_tag`` tag (entries whose chart context carries that tag are skipped, recorded as a
  FILTERED outcome). It receives its parent's signals of bars closing after its start.
- newlab (``kind='newlab'``, id ``"NL<n>@<tf>"``): a strategy of the new-strategy lab's grammar; its signals
  come from paperbot/newlab_live.py, exits, sizing and costs are paper v3.

Where the code runs (the parity argument, docs/extra-accounts.md)
- The live runner calls ``Extras.post_boundary(boundary, submitted, timed_out)`` after the originals' work at a
  boundary is committed. Phase 1 (always, pure Python on the originals' submitted list): copies get their
  parents' signals. Phase 2 (only when the boundary is live: at most 120 s old at hook entry, after the
  restart's catch-up, and the originals did not time out; under a wall-time budget): new-strategy signals and the
  activation of approved proposals. Each phase commits only through its own ``book.save``; an exception
  rolls back that phase's writes and undoes its in-memory changes. Nothing here can stop the runner.
- Extras step in the same engine loop as the originals, so they are ``GuardedEngine`` (an exception holds that
  account) or ``HeldEngine`` (frozen), and every Signal they get is plain JSON before it is submitted. Inside
  that loop they cost the originals nothing but their engines' step: their CRITICAL lines are written to the alerts
  table at once and sent to Telegram only after the poll (``post_batch``) or after phase 2 of a live boundary,
  and their fills never fetch an order book (live3 ``_fill_costs``).
- At load only runtime-owned code judges an account (``COPY_TEMPLATES``, ``NEWLAB_V1``, ``spec_sha``);
  nothing from paperbot.agents is imported. A copy whose rule cannot be read is held; a new-strategy
  account whose spec or code pin is wrong is suspended (its engine steps, no new signals).

Activation (``Activator.poll``): reads agents3.db and inbox.db read-only, only at live boundaries, only the
structured columns listed in ``Activator`` (never model text), and re-checks everything at the moment of
creation: run binding and the observation period, the owners' click, a sticky reject click, the gate
re-judged with strict counts and high-water marks (cross-checked with the agents' own functions), the
parent's facts from paper3.db, caps and duplicates, and its own validation. Any failure means no account
and a reason code in state ``extras`` (``PERMANENT`` codes only a status change can resolve).

Identity: an account is its proposal row (id and ts) plus its trial (id and ts) and its content
(``source``), stored once in ``accounts.data.source``. Account ids are assigned here, never taken from
agents3 ids.

Configuration: /etc/paperbot/extras.json (optional, re-read at each live poll): agents_db, inbox_db
(default next to paper3.db), observe_days (21, never lower), observe_until (KST date), owner_ok_days (60,
never lower), budget_s (20), pause_activation, agents_ack, inbox_ack, accept_code. deploy/extras.example.json.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import datetime as dt
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import time
from typing import Any, Callable, Optional

from .accounts import ORIGINAL_KINDS, HeldEngine
from .config import DS200_IDS, REEL_NAME, V3_STOP_ATR, V3_TRADE_TFS, Settings
from .engine import PaperEngine, engine_state, restore_engine
from .health import sd_notify
from .models import Signal, SignalOutcome
from .notify import CRITICAL, INFO, KO_KINDS, WARN, Digest, NullNotifier

V = 1
STATE_KEY = "extras"
MIN = 60_000
FIVE = 300_000
DAY_MS = 86_400_000
KST_MS = 9 * 3_600_000
TRADE_TFS = ("5m", "15m", "30m", "1h", "4h")
TF_MS = {"5m": 5 * MIN, "15m": 15 * MIN, "30m": 30 * MIN, "1h": 60 * MIN, "4h": 240 * MIN}
TF_KO = {"5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
KINDS = ("copy", "newlab")
LIVE_MS = 120_000                       # a boundary older than this at hook entry is not live
DEFAULT_CONFIG = "/etc/paperbot/extras.json"
OBSERVE_DAYS_MIN = 21
OWNER_OK_DAYS_MIN = 60
DAYS_MAX = 3650                         # observe_days / owner_ok_days above this are read as this (ten years)
DEFAULT_BUDGET_S = 20.0
PARENT_MIN_TRADES = 30                  # closed trades of the copy's parent in paper3 (owners' rule; tests lower it)
CAP_COPY_PER_STRATEGY = 1
CAP_COPY_TOTAL = 10
CAP_NEWLAB_TOTAL = 10
MAX_EVENTS = 2_000
FILTERED = "FILTERED"
FILTER_REASON = "copy rule: skip_tag"

PERMANENT = frozenset({"contract_missing", "contract_mismatch", "spec_invalid", "trial_status", "stale_run",
                       "owner_ok_missing", "duplicate", "gate_now_fail", "parent_missing", "parent_bust"})
# owner_click_missing is temporary: a lost click (an inbox.db restore) is fixed by the deciding owner clicking
# approve again on the dashboard, never by closing the owners' approval
TEMPORARY = frozenset({"observing", "paused", "agents_unreadable", "inbox_unreadable", "agents_regressed",
                       "inbox_regressed", "stale_ok", "owner_click_missing", "reject_pending", "gate_disagree",
                       "gate_code_unavailable", "parent_trades", "cap_strategy", "cap_copy_total", "cap_newlab_total",
                       "newlab_unavailable", "id_conflict"})
LOUD = frozenset({"id_conflict", "owner_click_missing", "inbox_regressed"})     # temporary codes sent as WARN
CODES_KO = {
    "contract_missing": "제안에 계좌 정의가 없음(예전 형식)",
    "contract_mismatch": "제안의 계좌 정의가 시험 장부와 맞지 않음",
    "spec_invalid": "규칙이 허용 목록 밖",
    "trial_status": "시험 장부 상태가 맞지 않음",
    "stale_run": "이번 paper 운영 전(또는 관찰 기간 중)의 제안",
    "owner_ok_missing": "두 분 승인이 필요한데 두 분 결정이 아님",
    "owner_click_missing": "두 분 결정인데 대시보드 승인 클릭 기록이 없음: 승인한 분이 '다시 승인'을 누르면 다시 확인",
    "inbox_regressed": "승인 클릭 기록(inbox.db)이 예전 것으로 바뀜(운영자 확인 필요)",
    "duplicate": "같은 계좌가 이미 있음",
    "gate_now_fail": "지금 시험 수로 다시 판정하면 관문 미통과",
    "parent_missing": "원본 계좌가 없음",
    "parent_bust": "원본 계좌가 파산",
    "observing": "관찰 기간",
    "paused": "운영자가 시작을 멈춰 둠",
    "agents_unreadable": "에이전트 장부를 읽지 못함",
    "inbox_unreadable": "승인 클릭 기록을 읽지 못함",
    "agents_regressed": "에이전트 장부가 예전 것으로 바뀜(운영자 확인 필요)",
    "stale_ok": "기능 시작 전의 승인: 두 분이 다시 한 번 승인을 눌러야 함",
    "reject_pending": "거절 클릭이 있음",
    "gate_disagree": "관문 재판정 숫자가 에이전트 쪽과 다름(운영자 확인 필요)",
    "gate_code_unavailable": "관문 코드를 불러오지 못함",
    "parent_trades": "원본 계좌 거래가 아직 30건 미만",
    "cap_strategy": "이 매매법의 복제 계좌가 이미 있음(1개 한도)",
    "cap_copy_total": "복제 계좌 10개 한도",
    "cap_newlab_total": "새 매매법 계좌 10개 한도",
    "newlab_unavailable": "새 매매법 신호 코드를 쓸 수 없음",
    "id_conflict": "같은 제안 번호로 다른 계좌가 이미 있음(운영자 확인 필요)",
}

COPY_ID_RE = re.compile(r"^(?P<S>[A-Za-z0-9_]+)@(?P<tf>5m|15m|30m|1h|4h)~c(?P<n>[1-9][0-9]{0,3})$")
NEWLAB_ID_RE = re.compile(r"^NL(?P<n>[1-9][0-9]{0,3})@(?P<tf>5m|15m|30m|1h|4h)$")


# ====================================================================== the contract (docs/extra-accounts.md)
def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_key_copy(rule: dict) -> str:
    return "copy:" + _canon(rule)


def content_key_newlab(spec_hash: str) -> str:
    return "newlab:" + str(spec_hash)


def content_key_of(kind: str, rule: Optional[dict] = None, spec_hash: Optional[str] = None) -> str:
    return content_key_copy(rule) if kind == "copy" else content_key_newlab(spec_hash)


def source(proposal_id: int, proposal_ts: int, trial_id: int, trial_ts: int, content: str) -> dict:
    """The identity of an extra account (compared by exact dict equality)."""
    return {"proposal_id": proposal_id, "proposal_ts": proposal_ts, "trial_id": trial_id, "trial_ts": trial_ts,
            "content": content}


def copy_account_id(strategy: str, tf: str, n: int) -> str:
    return f"{strategy}@{tf}~c{int(n)}"


def newlab_account_id(n: int, tf: str) -> str:
    return f"NL{int(n)}@{tf}"


def id_n(kind: str, aid: str) -> Optional[int]:
    m = (COPY_ID_RE if kind == "copy" else NEWLAB_ID_RE).match(aid or "")
    return int(m.group("n")) if m else None


def next_n(conn: sqlite3.Connection, kind: str) -> int:
    """1 + the largest n among this paper3.db's accounts of ``kind`` (0 if none): never reused, rows are
    never deleted."""
    ns = [id_n(kind, r[0]) for r in conn.execute("SELECT account_id FROM accounts WHERE kind = ?", (kind,))]
    return 1 + max([n for n in ns if n is not None] or [0])


# ---------------------------------------------------------------------- copy rules
def _against(side: int, regime: Optional[str]) -> bool:
    return (side > 0 and regime == "trend_down") or (side < 0 and regime == "trend_up")


# The runtime's own copy of the 7 skip-tag tests of paperbot.cards.TAGS (tests compare them with
# labtests.has_tag on a battery of contexts), applied to a card-like dict as labtests.has_tag does.
SKIP_PREDICATES: dict = {
    "추세 반대 진입": lambda c: _against(c["side"], c["ctx"].get("regime")),
    "상위 봉 추세 반대": lambda c: _against(c["side"], c["ctx"].get("htf_regime")),
    "횡보장 진입": lambda c: c["ctx"].get("regime") in ("chop", "box"),
    "추세 약함 (ADX 20 미만)": lambda c: c["ctx"].get("adx") is not None and c["ctx"]["adx"] < 20,
    "DI 방향 반대": lambda c: None not in (c["ctx"].get("di_plus"), c["ctx"].get("di_minus"))
    and (c["ctx"]["di_plus"] - c["ctx"]["di_minus"]) * c["side"] < 0,
    "많이 오른/내린 뒤 추격": lambda c: c["ctx"].get("ema20_dist_atr") is not None
    and c["ctx"]["ema20_dist_atr"] * c["side"] >= 2.0,
    "최근 범위 끝에서 진입": lambda c: c["ctx"].get("range_pct") is not None
    and ((c["side"] > 0 and c["ctx"]["range_pct"] >= 0.9) or (c["side"] < 0 and c["ctx"]["range_pct"] <= 0.1)),
}
SKIP_TAGS = tuple(SKIP_PREDICATES)
COPY_TEMPLATES = {"stop_atr": {"k": (1.5, 2.5, 3.0)},
                  "lock_start": {"first_lock": (0.15, 0.2, 0.3)},
                  "skip_tag": {"tag": SKIP_TAGS}}


def skip_hit(tag: str, side: int, ctx: Any) -> bool:
    """Does the skip tag apply to a ``side`` entry with chart context ``ctx`` (a missing ctx: no tag)."""
    fn = SKIP_PREDICATES.get(tag)
    if fn is None:
        return False
    c = {"side": int(side), "ctx": ctx or {}, "reason": None, "best_roe": None, "hold_bars": None}
    try:
        return bool(fn(c))
    except (TypeError, KeyError, AttributeError):
        return False


def _num_match(v: Any, allowed) -> Optional[float]:
    """The runtime's own float equal to ``v`` (a JSON number, not a bool), else None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        x = float(v)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    for a in allowed:
        if abs(x - float(a)) < 1e-9:
            return float(a)
    return None


def parse_rule(rule: Any) -> Optional[dict]:
    """The canonical copy rule ({"template", <param>: runtime value}) or None when it is not one of
    COPY_TEMPLATES exactly."""
    if not isinstance(rule, dict) or len(rule) != 2:
        return None
    t = rule.get("template")
    if not isinstance(t, str) or t not in COPY_TEMPLATES:
        return None
    (param, allowed), = COPY_TEMPLATES[t].items()
    if set(rule) != {"template", param}:
        return None
    v = rule[param]
    if t == "skip_tag":
        return {"template": t, param: v} if isinstance(v, str) and v in allowed else None
    x = _num_match(v, allowed)
    return None if x is None else {"template": t, param: x}


# paper v4 (owners' D9, docs/paper-v4-rules.md): no copy account of a DeepSeek or reel parent (the runner refuses it
# for good, 'spec_invalid'); copies stay copies of the 36 (their parent must be a kind 'strategy' account, check C9).
NO_COPY_PARENTS = frozenset(DS200_IDS) | {REEL_NAME}
NO_COPY_KO = "딥시크·릴스 5분 단타 계좌는 복제 계좌를 만들지 않음(v4 규칙 D9)"


def rule_of_trial_spec(spec: Any, names) -> tuple[Optional[dict], Optional[str], Optional[str], str]:
    """(rule, strategy, timeframe, why) from a copy trial's spec, which must be exactly
    {"template", "strategy", "timeframe", <param>} with values the runtime allows."""
    if not isinstance(spec, dict):
        return None, None, None, "trial spec is not an object"
    t = spec.get("template")
    if not isinstance(t, str) or t not in COPY_TEMPLATES:
        return None, None, None, f"template {str(t)[:40]!r} not allowed"
    (param, _allowed), = COPY_TEMPLATES[t].items()
    if set(spec) != {"template", "strategy", "timeframe", param}:
        return None, None, None, "trial spec keys"
    s, tf = spec.get("strategy"), spec.get("timeframe")
    if isinstance(s, str) and s in NO_COPY_PARENTS:
        return None, None, None, NO_COPY_KO
    if not isinstance(s, str) or s not in set(names):
        return None, None, None, "strategy not one of the 36"
    if tf not in TRADE_TFS:
        return None, None, None, "timeframe not allowed"
    rule = parse_rule({"template": t, param: spec[param]})
    if rule is None:
        return None, None, None, f"{t}.{param} not allowed"
    return rule, s, tf, ""


def rule_fields(rule: Optional[dict]) -> dict:
    """{"stop_atr": k, "first_lock": f, "skip_tag": tag or None} of a copy rule (base values otherwise)."""
    out = {"stop_atr": V3_STOP_ATR, "first_lock": None, "skip_tag": None}
    if rule:
        if rule["template"] == "stop_atr":
            out["stop_atr"] = float(rule["k"])
        elif rule["template"] == "lock_start":
            out["first_lock"] = float(rule["first_lock"])
        elif rule["template"] == "skip_tag":
            out["skip_tag"] = rule["tag"]
    return out


def settings_for(base: Settings, rule: Optional[dict]) -> Settings:
    """lock_start: the base settings with the first lock replaced (step and trigger gap unchanged);
    anything else: ``base`` itself (the same object)."""
    if rule and rule.get("template") == "lock_start":
        return dataclasses.replace(base, ladder_first_lock=float(rule["first_lock"]))
    return base


def copy_meta(parent_sig: Signal, copy_aid: str) -> dict:
    meta = copy.deepcopy(parent_sig.meta)            # nothing shared with the parent's pending signal
    meta["account"] = copy_aid
    return meta


def derive(rule: dict, parent_sig: Signal, copy_aid: str) -> Optional[Signal]:
    """The copy's signal from its parent's (None: the rule skips it)."""
    meta = copy_meta(parent_sig, copy_aid)
    if rule["template"] == "stop_atr":
        meta["stop_dist"] = float(rule["k"]) * float(parent_sig.atr)   # sizing follows the stop (engine)
    if rule["template"] == "skip_tag" and skip_hit(rule["tag"], parent_sig.side, parent_sig.meta.get("ctx") or {}):
        return None
    return dataclasses.replace(parent_sig, meta=meta)


def plain_json(sig: Signal) -> str:
    """The Signal as JSON without any default= conversion; raises TypeError/ValueError when it holds anything
    the state JSON could not store (so ``book.save`` can never fail because of an extra)."""
    return json.dumps(dataclasses.asdict(sig))


# ---------------------------------------------------------------------- the new-strategy grammar (frozen v1)
NEWLAB_V1: dict = {
    "v": "newlab-v1",
    "tfs": ("5m", "15m", "30m", "1h", "4h"),
    "directions": ("long", "short", "both"),
    "max_filters": 2,
    "families": {
        "ema_cross": (("fast", "slow"), ((9, 21), (20, 50), (50, 200))),
        "sma_cross": (("fast", "slow"), ((10, 30), (50, 200))),
        "macd_cross": (("fast", "slow", "signal"), ((12, 26, 9), (8, 21, 5))),
        "macd_hist_zero": ((), ((),)),
        "supertrend_flip": (("length", "mult"), ((10, 2.0), (10, 3.0), (14, 4.0))),
        "donchian_break": (("length",), ((20,), (55,))),
        "keltner_break": ((), ((),)),
        "psar_flip": ((), ((),)),
        "dmi_cross": ((), ((),)),
        "ichimoku_tk": ((), ((),)),
        "aroon_cross": ((), ((),)),
        "hma_turn": (("length",), ((21,), (55,))),
        "rsi_reversal": (("length", "low", "high"), ((14, 30, 70), (7, 20, 80))),
        "rsi_cross50": ((), ((),)),
        "stoch_zone": ((), ((),)),
        "stochrsi_zone": ((), ((),)),
        "cci_extreme": ((), ((),)),
        "williams_r": ((), ((),)),
        "mfi_reversal": ((), ((),)),
        "roc_zero": (("length",), ((9,), (21,))),
        "cmo_zero": ((), ((),)),
        "bb_break": ((), ((),)),
        "bb_revert": ((), ((),)),
        "squeeze_break": ((), ((),)),
        "obv_cross": ((), ((),)),
        "volume_spike": ((), ((),)),
        "engulfing": ((), ((),)),
        "hammer_star": ((), ((),)),
        "inside_break": ((), ((),)),
        "three_same": ((), ((),)),
    },
    "filters": {
        "trend_ema": {"length": (50, 100, 200)},
        "adx": {"mode": ("above", "below"), "level": (20, 25, 30)},
        "htf_trend": {"length": (20, 50)},
        "vol_regime": {"mode": ("high", "low"), "lookback": (100, 500)},
        "session": {"window": ("asia", "europe", "us")},
    },
}


def _same_value(v: Any, a: Any) -> bool:
    """Canonical equality: same JSON type and value (an int is not a float, a bool is not a number)."""
    if isinstance(a, str):
        return isinstance(v, str) and v == a
    if isinstance(v, bool) or isinstance(a, bool):
        return False
    if type(v) is not type(a):
        return False
    return v == a


def check_newlab_v1(spec: Any) -> Optional[str]:
    """None when ``spec`` is a canonical newlab-v1 strategy (exactly what newlab.normalize_spec returns),
    else why not. Strict: exact key sets, exact values and JSON types, filters sorted by kind, no coercion."""
    g = NEWLAB_V1
    if not isinstance(spec, dict):
        return "not an object"
    if set(spec) != {"v", "timeframe", "entry", "filters", "direction"}:
        return "keys"
    if not _same_value(spec["v"], g["v"]):
        return "grammar version"
    if not any(_same_value(spec["timeframe"], t) for t in g["tfs"]):
        return "timeframe"
    if not any(_same_value(spec["direction"], d) for d in g["directions"]):
        return "direction"
    e = spec["entry"]
    if not isinstance(e, dict) or set(e) != {"family", "params"}:
        return "entry keys"
    fam = e["family"]
    if not isinstance(fam, str) or fam not in g["families"]:
        return "family"
    names, grid = g["families"][fam]
    p = e["params"]
    if not isinstance(p, dict) or set(p) != set(names):
        return "params keys"
    if not any(all(_same_value(p[k], a) for k, a in zip(names, combo)) for combo in grid):
        return "params values"
    fl = spec["filters"]
    if not isinstance(fl, list) or len(fl) > g["max_filters"]:
        return "filters"
    kinds = []
    for f in fl:
        if not isinstance(f, dict):
            return "filter not an object"
        k = f.get("kind")
        if not isinstance(k, str) or k not in g["filters"]:
            return "filter kind"
        allowed = g["filters"][k]
        if set(f) != {"kind", *allowed}:
            return f"filter {k} keys"
        for param, vals in allowed.items():
            if not any(_same_value(f[param], a) for a in vals):
                return f"filter {k}.{param}"
        kinds.append(k)
    if len(set(kinds)) != len(kinds):
        return "filter kinds repeat"
    if kinds != sorted(kinds):
        return "filters not sorted by kind"
    return None


def spec_sha(spec: dict) -> str:
    """sha256 of the canonical JSON (equal to newlab.spec_hash for a canonical spec)."""
    return hashlib.sha256(_canon(spec).encode("utf-8")).hexdigest()


class Refusal(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = str(detail)[:300]


def parse_copy(account: Any, trial: dict, p: dict, names) -> tuple[dict, str, str, str]:
    """The runner's own validation of a copy proposal (C1..C3). Returns (rule, strategy, timeframe, content);
    raises Refusal. ``trial``: {id, ts, kind, strategy, room_id, spec, ...}; ``p``: the proposal row."""
    if not isinstance(account, dict) or account.get("v") != 1:
        raise Refusal("contract_missing", "change.account missing or v != 1")
    if account.get("kind") != "copy" or account.get("trial_id") != p.get("trial_id"):
        raise Refusal("contract_mismatch", "kind or trial_id")
    rule, s, tf, why = rule_of_trial_spec(trial.get("spec"), names)
    if rule is None:
        raise Refusal("spec_invalid", why)
    if parse_rule(account.get("rule")) != rule:
        raise Refusal("contract_mismatch", "rule")
    if account.get("strategy") != s or trial.get("strategy") != s:
        raise Refusal("contract_mismatch", "strategy")
    if p.get("room_id") != "strat:" + s:
        raise Refusal("contract_mismatch", "room")
    if account.get("timeframe") != tf:
        raise Refusal("contract_mismatch", "timeframe")
    if account.get("parent") != f"{s}@{tf}":
        raise Refusal("contract_mismatch", "parent")
    return rule, s, tf, content_key_copy(rule)


# paper v4 (docs/paper-v4-rules.md): the run's 5m accounts are the reel and its three 5m coin flips only (their own
# exits); the 36, their copies and the new-strategy accounts trade the core group's timeframes
NO_5M_KO = ("paper v4의 5분봉은 릴스 5분 단타(REEL_H1)와 그 비교용 동전 3개만 씀(자기 청산 규칙, docs/paper-v4-rules.md): "
            "매매법 36개·복제 계좌·새 매매법 계좌는 5분봉 없음")


def run_timeframe_refusal(tf: Any, run_tfs: Optional[Any] = None) -> str:
    """Why a new-strategy account cannot start on ``tf`` ('' when it can). The lab grammar (NEWLAB_V1) still
    allows 5m, the run does not: the account must be on one of the core group's timeframes, config.V3_TRADE_TFS (the
    signal service's ``trade_tfs``, which is that tuple in the live runner; paper v4's 5m path for the reel and its
    coin flips is separate and never in it)."""
    allowed = tuple(run_tfs) if run_tfs else V3_TRADE_TFS
    if tf in allowed:
        return ""
    if tf == "5m":
        return f"{NO_5M_KO}: 새 매매법 계좌는 {'·'.join(allowed)}봉에서만 시작"
    return f"{tf}봉은 이번 실행의 봉({'·'.join(allowed)})이 아님"


def parse_newlab(account: Any, trial: dict, p: dict) -> tuple[dict, str, str]:
    """The runner's own validation of a new-strategy proposal (C1..C3). Returns (spec, spec_hash, content)."""
    if not isinstance(account, dict) or account.get("v") != 1:
        raise Refusal("contract_missing", "change.account missing or v != 1")
    if account.get("kind") != "newlab" or account.get("trial_id") != p.get("trial_id"):
        raise Refusal("contract_mismatch", "kind or trial_id")
    spec = trial.get("spec")
    why = check_newlab_v1(spec)
    if why is not None:
        raise Refusal("spec_invalid", why)
    h = spec_sha(spec)
    if trial.get("spec_hash") != h:
        raise Refusal("spec_invalid", "spec hash")
    if account.get("spec_hash") != h or account.get("spec") != spec:
        raise Refusal("contract_mismatch", "spec")
    if account.get("timeframe") != spec["timeframe"]:
        raise Refusal("contract_mismatch", "timeframe")
    if p.get("room_id") != "team:lab":
        raise Refusal("contract_mismatch", "room")
    if account.get("parent") is not None:
        raise Refusal("contract_mismatch", "parent")
    return spec, h, content_key_newlab(h)


def strategy_ko(s: str) -> str:
    try:
        from .agents.roster3 import STRATEGY_KO      # display only, at creation (never at load)
        return STRATEGY_KO.get(s, s)
    except Exception:  # noqa: BLE001
        return s


def rule_ko(rule: dict) -> str:
    t = rule["template"]
    if t == "stop_atr":
        return f"손절 {float(rule['k']):g} ATR"
    if t == "lock_start":
        return f"첫 익절 잠금 {float(rule['first_lock']):.0%}"
    return f"'{rule['tag']}' 진입 건너뜀"


def label_ko(kind: str, n: int, tf: str, strategy: Optional[str] = None, rule: Optional[dict] = None,
             trial_id: Optional[int] = None) -> str:
    if kind == "copy":
        return f"{strategy_ko(strategy)} {TF_KO[tf]} 복제 c{n} · {rule_ko(rule)}"
    return f"새 매매법 NL{n} (장부 #{trial_id}) · {TF_KO[tf]}"


# ====================================================================== engines
class GuardedEngine(PaperEngine):
    """A PaperEngine whose ``step`` can never raise into the shared loop: an exception holds the account (no
    more steps or submits), keeps a state that still serialises (else the state from before that step), and
    reports through ``on_fault(account_id, why)``."""

    on_fault: Optional[Callable[[str, str], None]] = None

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.held: Optional[str] = None

    def step(self, bars, funding=None) -> None:
        if self.held:
            return
        snap = engine_state(self)
        try:
            super().step(bars, funding)
        except Exception as exc:  # noqa: BLE001  an extra's bug must not reach the originals
            self.held = f"fault: {type(exc).__name__}"
            try:
                json.dumps(engine_state(self))
            except Exception:  # noqa: BLE001
                restore_engine(self, snap)
            if self.on_fault is not None:
                try:
                    self.on_fault(self.book, f"{type(exc).__name__}: {exc}"[:200])
                except Exception:  # noqa: BLE001
                    pass

    def submit(self, signal: Signal) -> None:
        if self.held:
            return
        super().submit(signal)


def engine_args(kind: str, rule: Optional[dict], base: Settings, digest=None, forward=None) -> dict:
    """How the book builds an extra's engine (AccountBook._make keywords). ``forward``: where its CRITICAL
    lines go (the extras' outbox, sent when no originals' compute can wait for them)."""
    return {"settings": settings_for(base, rule if kind == "copy" else None), "cls": GuardedEngine,
            "digest": digest, "forward": forward}


class _Outbox:
    """The forward notifier of the extras' engines: a CRITICAL line (already written to the alerts table by
    the engine's store notifier) is held in ``Extras.outbox`` instead of being sent inside the shared step."""

    def __init__(self, ext: "Extras"):
        self.ext = ext

    def send(self, level: str, text: str) -> None:
        self.ext.outbox.append((level, text))


class ExtrasDigest(Digest):
    """The extras' own hourly digest ("추가 계좌 알림 모음"), so the originals' digest text never changes."""

    def flush(self, now_ms: int, force: bool = False):
        if self.last_ms is None:
            self.last_ms = now_ms
        if not self.items or (not force and now_ms - self.last_ms < self.every_ms):
            return None
        counts: dict = {}
        for t in self.items:
            kind = next((ko for key, ko in KO_KINDS if key in t), "기타")
            counts[kind] = counts.get(kind, 0) + 1
        head = "추가 계좌 알림 모음: " + " · ".join(f"{k} {n}" for k, n in counts.items())
        lines = self.items[:self.max_lines]
        more = len(self.items) - len(lines)
        text = "\n".join([head] + lines + ([f"외 {more}건 (대시보드 알림 목록)"] if more else []))
        try:
            self.forward.send(INFO, text)
        except Exception:  # noqa: BLE001
            pass
        self.items = []
        self.last_ms = now_ms
        return text


# ====================================================================== configuration
def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclasses.dataclass
class Config:
    agents_db: Optional[str] = None
    inbox_db: Optional[str] = None
    observe_days: float = OBSERVE_DAYS_MIN
    observe_until: Optional[str] = None          # KST date YYYY-MM-DD, inclusive
    owner_ok_days: float = OWNER_OK_DAYS_MIN
    budget_s: float = DEFAULT_BUDGET_S
    pause_activation: bool = False
    agents_ack: Optional[str] = None
    inbox_ack: Optional[str] = None
    accept_code: dict = dataclasses.field(default_factory=dict)
    sha256: str = "default"
    path: Optional[str] = None
    warning: Optional[str] = None                 # why activation is off (half-configured)

    @property
    def activation(self) -> bool:
        return bool(self.agents_db) and bool(self.inbox_db)

    def summary(self) -> dict:
        return {"agents_db": self.agents_db, "inbox_db": self.inbox_db, "pause_activation": self.pause_activation,
                "observe_days": self.observe_days, "observe_until": self.observe_until,
                "owner_ok_days": self.owner_ok_days, "budget_s": self.budget_s, "sha256": self.sha256}

    @classmethod
    def default(cls, db_path: str) -> "Config":
        d = os.path.dirname(os.path.abspath(db_path))
        return cls(agents_db=os.path.join(d, "agents3.db"), inbox_db=os.path.join(d, "inbox.db"))

    @classmethod
    def from_text(cls, text: str, db_path: str, path: Optional[str] = None) -> "Config":
        """Parse extras.json. The file can never lower observe_days below 21 or owner_ok_days below 60; values
        above DAYS_MAX are read as DAYS_MAX (a huge number would overflow the floor's timestamp).
        Raises ValueError for a file that is not a valid configuration."""
        raw = json.loads(text)
        if not isinstance(raw, dict):
            raise ValueError("extras.json must be a JSON object")
        d = os.path.dirname(os.path.abspath(db_path))
        cfg = cls.default(db_path)
        cfg.sha256, cfg.path = _sha_text(text), path

        def _path(v):
            if v is None or v == "":
                return None
            if not isinstance(v, str):
                raise ValueError("database paths must be strings")
            return v if os.path.isabs(v) else os.path.join(d, v)
        has_a, has_i = "agents_db" in raw, "inbox_db" in raw
        if has_a or has_i:
            cfg.agents_db = _path(raw.get("agents_db")) if has_a else None
            cfg.inbox_db = _path(raw.get("inbox_db")) if has_i else None
            if not (cfg.agents_db and cfg.inbox_db):
                cfg.warning = "agents_db와 inbox_db 중 하나만 설정되어 새 계좌 시작을 끕니다"
                cfg.agents_db = cfg.inbox_db = None
        for key, lo in (("observe_days", OBSERVE_DAYS_MIN), ("owner_ok_days", OWNER_OK_DAYS_MIN)):
            if key in raw:
                v = raw[key]
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
                    raise ValueError(f"{key} must be a number")
                setattr(cfg, key, min(max(float(v), float(lo)), float(DAYS_MAX)))
        if "observe_until" in raw and raw["observe_until"] not in (None, ""):
            v = raw["observe_until"]
            if not isinstance(v, str):
                raise ValueError("observe_until must be a date YYYY-MM-DD")
            dt.datetime.strptime(v, "%Y-%m-%d")
            cfg.observe_until = v
        if "budget_s" in raw:
            v = raw["budget_s"]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not (0 < float(v) <= 120):
                raise ValueError("budget_s must be a number in (0, 120]")
            cfg.budget_s = float(v)
        if "pause_activation" in raw:
            if not isinstance(raw["pause_activation"], bool):
                raise ValueError("pause_activation must be true or false")
            cfg.pause_activation = raw["pause_activation"]
        for key in ("agents_ack", "inbox_ack"):
            if raw.get(key) not in (None, ""):
                if not isinstance(raw[key], str):
                    raise ValueError(f"{key} must be a string")
                setattr(cfg, key, raw[key])
        if "accept_code" in raw:
            ac = raw["accept_code"]
            if not isinstance(ac, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in ac.items()):
                raise ValueError("accept_code must map account ids to code pin strings")
            cfg.accept_code = dict(ac)
        return cfg


def observe_floor(run_start: Optional[int], cfg: Config) -> Optional[int]:
    """The first moment an account may be created: run start + observe_days, or later the end (KST) of
    observe_until."""
    if run_start is None:
        return None
    floor = int(run_start + cfg.observe_days * DAY_MS)
    if cfg.observe_until:
        d = dt.datetime.strptime(cfg.observe_until, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
        end = int(d.timestamp() * 1000) + DAY_MS - KST_MS          # 00:00 KST after that date
        floor = max(floor, end)
    return floor


def inbox_fingerprint_text(fp: Optional[list]) -> str:
    fp = fp or [0, 0]
    return f"approval:{int(fp[0])}@{int(fp[1])}"


def fingerprint_text(fp: Optional[dict]) -> str:
    if not fp:
        return "none"
    t, p = fp.get("trial") or [0, 0], fp.get("proposal") or [0, 0]
    return f"trial:{t[0]}@{t[1]}/proposal:{p[0]}@{p[1]}"


# ====================================================================== the runtime
@dataclasses.dataclass
class Extra:
    aid: str
    kind: str
    strategy: str
    timeframe: str
    parent: Optional[str]
    created_ts: int
    data: dict
    rule: Optional[dict] = None
    spec: Optional[dict] = None
    status: str = "active"           # active / suspended / held
    code: Optional[str] = None
    since: Optional[int] = None
    detail: str = ""

    @property
    def source(self) -> dict:
        s = self.data.get("source") if isinstance(self.data, dict) else None
        return s if isinstance(s, dict) else {}


def _new_state(now: int) -> dict:
    return {"v": V, "ts": now, "boundary": None, "since": now, "run_start": None, "observe_until": None,
            "config": {}, "agents_db": "off", "inbox_db": "off", "fingerprint": None,
            "hwm": {"room_tests": {}, "newlab_tests": 0}, "created": {}, "refused": {}, "accounts": {},
            "events": [], "counts": {"copy": 0, "newlab": 0},
            "health": {"hook_ms": None, "phase2_ms": None, "newlab_jobs": 0, "budget_skips": 0, "errors": 0,
                       "last_error": None, "skipped_boundaries": {}, "skipped_runs": []}}


class Journal:
    """What a hook phase changed in memory, to undo it when the phase's transaction is rolled back."""

    def __init__(self, ext: "Extras", snapshot: bool = True):
        self.ext = ext
        self.state = copy.deepcopy(ext.state) if snapshot else None
        self.registry = dict(ext.extras) if snapshot else None
        self.ready = dict(ext.ready) if snapshot else None
        self.submits: list[tuple[str, Signal]] = []
        self.added_ids: list[str] = []
        self.registered_ids: list[str] = []
        self.after: list[tuple[str, str]] = []       # (level, text) to send once the phase is committed

    def submitted(self, aid: str, sig: Signal) -> None:
        self.submits.append((aid, sig))

    def added(self, aid: str) -> None:
        self.added_ids.append(aid)

    def registered(self, aid: str) -> None:
        self.registered_ids.append(aid)

    def merge(self, sub: "Journal") -> None:
        """A part of the phase that was kept (its savepoint released): its changes are the phase's, so a later
        failure of the phase undoes them too."""
        self.submits += sub.submits
        self.added_ids += sub.added_ids
        self.registered_ids += sub.registered_ids
        self.after += sub.after

    def undo(self) -> None:
        x = self.ext
        for aid, sig in reversed(self.submits):
            e = x.book.engines.get(aid)
            if e is not None:
                e.pending = [s for s in e.pending if s is not sig]
        for aid in reversed(self.registered_ids):
            if x.newlab is not None:
                x.newlab.unregister(aid)
        for aid in reversed(self.added_ids):
            x.book.remove(aid)
        if self.state is not None:
            x.state = self.state
            x.extras = self.registry
            x.ready = self.ready


class Extras:
    """The extras runtime of one live runner process (module docstring). Build with ``start``."""

    def __init__(self, store, notifier, db_path: str, settings: Settings, config: Config,
                 config_path: Optional[str], now_ms: Callable[[], int], state: dict, digest: Digest,
                 newlab_factory: Optional[Callable] = None):
        self.store = store
        self.notifier = notifier or NullNotifier()
        self.db_path = db_path
        self.settings = settings
        self.cfg = config
        self.config_path = config_path
        self.cfg_mtime: Optional[float] = None
        self.cfg_warned: Optional[str] = None
        self.clock = now_ms
        self.state = state
        self.digest = digest
        self.prev_accounts = dict(state.get("accounts") or {})
        self.extras: dict[str, Extra] = {}
        self.ready: dict[str, Optional[str]] = {}       # aid -> None ready / why not (one WARN per change)
        self.book = None
        self.runner = None
        self.service = None
        self.newlab = None
        self.newlab_factory = newlab_factory
        self.live_gate = True                            # tests only: False runs phase 2 at every boundary
        self.activator = Activator(self)
        self.bound = False
        # CRITICAL lines of the extras (their engines, faults, state changes): written to the alerts table at once,
        # sent to Telegram only where no originals' compute can wait for the send (flush_outbox)
        self.outbox: list[tuple[str, str]] = []
        self.forward = _Outbox(self)

    # ------------------------------------------------------------ construction
    @classmethod
    def start(cls, store, notifier, db_path: str, settings: Settings, config: Optional[Config] = None,
              config_path: Optional[str] = DEFAULT_CONFIG, now_ms: Optional[Callable[[], int]] = None,
              digest: Optional[Digest] = None, newlab_factory: Optional[Callable] = None) -> "Extras":
        """Read the configuration and state ``extras`` (``since`` is set once, on the first start with this
        feature, and written uncommitted: live3 commits it with the run record). Never raises for data
        problems (a bad configuration file gives the defaults and a WARN)."""
        clock = now_ms or (lambda: int(time.time() * 1000))
        now = clock()
        warn = None
        cfg = config
        mtime = None
        if cfg is None:
            cfg = Config.default(db_path)
            if config_path and os.path.exists(config_path):
                try:
                    mtime = os.path.getmtime(config_path)
                    with open(config_path) as fh:
                        cfg = Config.from_text(fh.read(), db_path, config_path)
                except Exception as exc:  # noqa: BLE001
                    warn = f"[extra] extras.json를 읽지 못해 기본값으로 시작합니다: {type(exc).__name__}: {exc}"[:300]
                    cfg = Config.default(db_path)
        got = None
        try:
            got = store.get_state(STATE_KEY)
        except Exception:  # noqa: BLE001
            got = None
        state = got[1] if got is not None and isinstance(got[1], dict) and got[1].get("v") == V else None
        fresh = state is None
        if fresh:
            state = _new_state(now)
        else:
            base = _new_state(now)
            for k, v in base.items():
                state.setdefault(k, v)
            for k, v in base["health"].items():
                state["health"].setdefault(k, v)
            for k, v in base["hwm"].items():
                state["hwm"].setdefault(k, v)
        ext = cls(store, notifier, db_path, settings, cfg, config_path if config is None else None, clock, state,
                  digest or ExtrasDigest(notifier or NullNotifier()), newlab_factory)
        ext.cfg_mtime = mtime
        state["config"] = cfg.summary()
        if warn:
            ext._alert(WARN, warn)
        if cfg.warning:
            ext._alert(WARN, f"[extra] {cfg.warning}")
        if fresh:
            store.put_state(STATE_KEY, now, state)
        return ext

    # ------------------------------------------------------------ alerts and events
    def _alert(self, level: str, text: str, digest: bool = True) -> None:
        """An "[extra]" line: alerts table at once; CRITICAL held in the outbox (flush_outbox), WARN to the
        extras digest."""
        now = self.clock()
        try:
            self.store.alert(now, level, text)
        except Exception:  # noqa: BLE001
            pass
        if level == CRITICAL:
            self.outbox.append((CRITICAL, text))
        elif level == WARN and digest:
            self.digest.add(text)

    def flush_outbox(self) -> None:
        """Send the held CRITICAL lines as one Telegram message. Called only where no originals' compute can wait for
        the send: at start-up (bind), at a live boundary after phase 2, and at the end of a poll
        (``post_batch``). Never inside the shared step or at a catch-up boundary."""
        items, self.outbox = [t for _lvl, t in self.outbox], []
        if not items:
            return
        if len(items) == 1:
            text = items[0]
        else:
            more = len(items) - 15
            text = "\n".join([f"추가 계좌 긴급 알림 {len(items)}건"] + items[:15]
                             + ([f"외 {more}건 (대시보드 알림 목록)"] if more > 0 else []))
        try:
            self.notifier.send(CRITICAL, text)
        except Exception:  # noqa: BLE001
            pass

    def post_batch(self, now: int) -> None:
        """The runner's end of a poll (after every boundary of the batch and its commit): the held CRITICAL
        lines are sent here. The hourly extras digest is not: a poll can end a second before a 5m close, so it
        goes out only right after a live boundary's compute (post_boundary)."""
        self.flush_outbox()

    def _effective(self) -> int:
        """From which 1m step a state change applies (daily3 and checkpoint read it): the next step."""
        r = self.runner
        if r is not None and r.skip_before is not None and (self.book.last_ts is None
                                                             or self.book.last_ts < r.skip_before):
            return int(r.skip_before)
        if self.book is not None and self.book.last_ts is not None:
            return int(max(self.book.last_ts, getattr(self.book, "_now", 0) or 0) + MIN)
        return self.clock()

    def _event(self, aid: str, event: str, code: Optional[str] = None, detail: str = "",
               effective: Optional[int] = None, **extra) -> None:
        ev = {"ts": self.clock(), "account_id": aid, "event": event, "code": code, "detail": str(detail)[:300],
              "effective": int(effective) if effective is not None else self._effective()}
        ev.update(extra)
        self.state.setdefault("events", []).append(ev)
        if len(self.state["events"]) > MAX_EVENTS:
            self.state["events"] = self.state["events"][-MAX_EVENTS:]

    def _set_status(self, x: Extra, status: str, code: Optional[str] = None, detail: str = "") -> None:
        """Record an account's safety state. Before ``bind`` the states are only collected (``_settle``
        compares them with the ones recorded by the previous run); afterwards a change is an event and a
        CRITICAL alert naming the account at once."""
        if not self.bound:
            x.status, x.code, x.detail = status, code, str(detail)[:300]
            return
        before = (x.status, x.code)
        x.status, x.code, x.detail = status, code, str(detail)[:300]
        x.since = self.clock() if status != "active" else None
        if (status, code) != before:
            self._transition(x, before)

    def _transition(self, x: Extra, before: tuple) -> None:
        if x.status == "active":
            self._event(x.aid, "resumed", before[1], x.detail)
            self._alert(CRITICAL, f"[extra] {x.aid}: 다시 정상 운영 ({CODES_KO.get(before[1] or '', before[1])} 해소)")
        else:
            self._event(x.aid, x.status, x.code, x.detail)
            what = "정지(동결: 저장된 상태 그대로)" if x.status == "held" else "멈춤(새 진입 없음, 열린 포지션은 규칙대로 관리)"
            self._alert(CRITICAL, f"[extra] {x.aid}: {what} — {x.code}: {x.detail}"[:300])

    def _settle(self) -> None:
        """At start: every account whose state differs from the previous run's record is an event."""
        now = self.clock()
        for aid, x in self.extras.items():
            prev = self.prev_accounts.get(aid)
            before = (prev.get("status", "active"), prev.get("code")) if isinstance(prev, dict) else ("active", None)
            cur = (x.status, x.code)
            if x.status != "active":
                x.since = prev.get("since") if isinstance(prev, dict) and before == cur and prev.get("since") else now
            if cur != before:
                self._transition(x, before)

    def _on_fault(self, aid: str, why: str) -> None:
        x = self.extras.get(aid)
        if x is None:
            return
        self._set_status(x, "held", "fault", why)
        self._write_state(self.clock())

    # ------------------------------------------------------------ load
    def make_of(self, row: dict) -> Optional[dict]:
        """How ``book.load`` builds an account. None for the originals (nothing else is touched); never raises."""
        if row.get("kind") in ORIGINAL_KINDS:
            return None
        try:
            return self._make_of(row)
        except Exception as exc:  # noqa: BLE001
            aid = str(row.get("account_id"))
            x = self.extras.get(aid) or Extra(aid, str(row.get("kind")), str(row.get("strategy")),
                                              str(row.get("timeframe")), row.get("parent"),
                                              int(row.get("created_ts") or 0), {})
            self.extras[aid] = x
            self._set_status(x, "held", "load_error", f"{type(exc).__name__}: {exc}")
            return {"cls": HeldEngine}

    def _make_of(self, row: dict) -> dict:
        aid, kind = row["account_id"], row["kind"]
        raw = row.get("data")
        data = json.loads(raw) if isinstance(raw, str) else (raw or {})
        if not isinstance(data, dict):
            data = {}
        x = Extra(aid, kind, row["strategy"], row["timeframe"], row.get("parent"), int(row["created_ts"]), data)
        self.extras[aid] = x
        if kind == "copy":
            rule = parse_rule(data.get("rule"))
            ok = (rule is not None and data.get("kind") == "copy" and COPY_ID_RE.match(aid) is not None
                  and row.get("parent") == f"{row['strategy']}@{row['timeframe']}")
            if not ok:
                self._set_status(x, "held", "rule_invalid", "copy rule unreadable or unknown")
                return {"cls": HeldEngine}
            x.rule = rule
            self._set_status(x, "active")
            return engine_args("copy", rule, self.settings, self.digest, self.forward)
        if kind == "newlab":
            spec = data.get("spec")
            x.spec = spec if isinstance(spec, dict) else None
            why = check_newlab_v1(spec)
            if why is None and spec_sha(spec) != data.get("spec_hash"):
                why = "spec hash"
            if why is None and (spec["timeframe"] != row["timeframe"] or NEWLAB_ID_RE.match(aid) is None):
                why = "timeframe or id"
            if why is not None:
                self._set_status(x, "suspended", "spec_invalid", why)
            else:
                self._set_status(x, "active")       # the code pin is checked in bind()
            return engine_args("newlab", None, self.settings, self.digest, self.forward)
        self._set_status(x, "held", "unknown_kind", f"kind {kind!r}")
        return {"cls": HeldEngine}

    # ------------------------------------------------------------ bind
    def _newlab_source(self):
        if self.newlab is None:
            from .newlab_live import NewlabSignals
            factory = self.newlab_factory or (lambda service: NewlabSignals(service))
            self.newlab = factory(self.service)
        return self.newlab

    def bind(self, runner) -> None:
        """Attach to the runner: fault reporting, new-strategy sources and code pins, the hook."""
        from .newlab_live import pin_text
        self.runner, self.book, self.service = runner, runner.book, runner.service
        for aid, x in self.extras.items():
            e = self.book.engines.get(aid)
            if isinstance(e, GuardedEngine):
                e.on_fault = self._on_fault
        nl = [x for x in self.extras.values() if x.kind == "newlab" and x.status == "active"]
        if nl:
            src = self._newlab_source()
            ok, why = src.available()
            for x in nl:
                if not ok:
                    self._set_status(x, "suspended", "newlab_unavailable", why or "")
                    continue
                pin, want = src.pin(), x.data.get("code") if isinstance(x.data.get("code"), dict) else {}
                if any(want.get(k) != pin.get(k) for k in ("newlab_signals", "context", "recorder", "lib")):
                    text = pin_text(pin)
                    if self.cfg.accept_code.get(x.aid) == text:
                        done = any(ev.get("event") == "code_accepted" and ev.get("account_id") == x.aid
                                   and ev.get("pin") == text for ev in self.state.get("events", []))
                        if not done:
                            self._event(x.aid, "code_accepted", "code_changed",
                                        f"{pin_text(want)} -> {text}", pin=text)
                            self._alert(CRITICAL, f"[extra] {x.aid}: 두 분이 바뀐 신호 코드를 받아들임 ({text}); "
                                                  "이 계좌만 Q5 사건(30일 기간을 다시 셈)")
                    else:
                        self._set_status(x, "suspended", "code_changed",
                                         f"{pin_text(want)} -> {text} (extras.json accept_code에 이 값을 넣으면 재개)")
                        continue
                why = src.register(x.aid, x.strategy, x.timeframe, x.spec)
                self._readiness(x.aid, why)
        self._settle()
        self.bound = True
        runner.post_boundary = self.post_boundary
        runner.post_batch = self.post_batch
        self._write_state(self.clock())
        self.store.commit()
        self.flush_outbox()                     # start-up: no compute is waiting

    def _readiness(self, aid: str, why: Optional[str]) -> None:
        if self.ready.get(aid, "unknown") == why:
            return
        self.ready[aid] = why
        if why is not None:
            self._alert(WARN, f"[extra] {aid}: 아직 신호를 계산하지 않음 ({why})")

    # ------------------------------------------------------------ the hook
    def live(self, boundary: int) -> bool:
        r = self.runner
        if not self.live_gate:
            return True
        return (r.skip_before is None or boundary >= r.skip_before) and r.now_ms() - boundary <= LIVE_MS

    def post_boundary(self, boundary: int, submitted: list, timed_out: bool) -> None:
        """Called by the runner after the originals' work at ``boundary`` was committed (see the module docstring)."""
        if self.book.last_ts is None:
            return
        t0 = time.monotonic()
        sd_notify("WATCHDOG=1")
        live = self.live(boundary)
        if submitted and self._copies_of({aid for aid, _ in submitted}, boundary):
            self._phase(1, boundary, lambda j: self._phase1(boundary, submitted, j), snapshot=False)
        if not live or timed_out:
            # nothing is sent here: in a catch-up burst a later boundary's originals' compute may still follow in this
            # batch (the outbox and the digest go out at the end of the poll, post_batch)
            self._count_skipped(boundary)
            self.state["health"]["hook_ms"] = int((time.monotonic() - t0) * 1000)
            return
        t2 = time.monotonic()
        deadline = t2 + float(self.cfg.budget_s)
        after = self._phase(2, boundary, lambda j: self._phase2(boundary, deadline, j, t2, t0))
        for level, text in after or []:
            try:
                self.notifier.send(level, text)
            except Exception:  # noqa: BLE001
                pass
        self.flush_outbox()
        self.digest.flush(self.clock())

    def _phase(self, n: int, boundary: int, fn, snapshot: bool = True) -> Optional[list]:
        j = Journal(self, snapshot)
        try:
            wrote = fn(j)
            if wrote:
                self._commit(n)
            return j.after
        except Exception as exc:  # noqa: BLE001  rolls back only this phase's writes
            try:
                self.store.conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            j.undo()
            h = self.state["health"]
            h["errors"] = int(h.get("errors") or 0) + 1
            h["last_error"] = f"phase {n} at {boundary}: {type(exc).__name__}: {exc}"[:300]
            try:
                self._alert(WARN, f"[extra] 추가 계좌 처리 {n}단계 실패, 이번 경계는 되돌림: {type(exc).__name__}: {exc}"[:300])
                self.store.commit()
            except Exception:  # noqa: BLE001
                pass
            return None

    def _commit(self, phase: int) -> None:
        """The phase's only commit: state ``extras`` and the book's state, in one transaction."""
        self._write_state(self.clock())
        self.book.save(self.book.last_ts)

    def _write_state(self, now: int) -> None:
        st = self.state
        st["ts"] = now
        st["config"] = self.cfg.summary()
        st["accounts"] = {aid: {"status": x.status, "code": x.code, "since": x.since}
                          for aid, x in self.extras.items() if x.status != "active"}
        st["counts"] = {k: sum(1 for x in self.extras.values() if x.kind == k) for k in KINDS}
        self.store.put_state(STATE_KEY, now, st)

    def _count_skipped(self, boundary: int) -> None:
        """A boundary the new-strategy accounts were not computed at (not live, or the originals timed out): counted
        per timeframe and kept as runs [[first, last], ...] (checkpoint leaves those bars out of the rate).
        Kept in memory and written with the next state write."""
        if self.newlab is None or not self.newlab.specs:
            return
        due = self.newlab.due(boundary)
        if not due:
            return
        h = self.state["health"]
        sk = h.setdefault("skipped_boundaries", {})
        for tf in due:
            sk[tf] = int(sk.get(tf, 0)) + 1
        runs = h.setdefault("skipped_runs", [])
        if runs and runs[-1][1] < boundary <= runs[-1][1] + FIVE:
            runs[-1][1] = boundary
        else:
            runs.append([boundary, boundary])
            if len(runs) > 1000:
                del runs[:-1000]

    # ------------------------------------------------------------ phase 1: copies
    def _copies_of(self, parents: set, boundary: int) -> dict:
        """{parent: [active copies started before ``boundary``]} for these parents."""
        out: dict[str, list[Extra]] = {}
        for x in self.extras.values():
            if x.kind == "copy" and x.parent in parents and x.status == "active" and x.created_ts < boundary \
                    and x.rule:
                out.setdefault(x.parent, []).append(x)
        return out

    def _phase1(self, boundary: int, submitted: list, j: Journal) -> bool:
        copies = self._copies_of({aid for aid, _ in submitted}, boundary)
        if not copies:
            return False
        wrote = False
        for aid, sig in submitted:
            for c in copies.get(aid, ()):
                if c.aid not in self.book.engines:
                    continue
                d = derive(c.rule, sig, c.aid)
                if d is None:
                    out_sig = dataclasses.replace(sig, meta=copy_meta(sig, c.aid))
                    self.store.outcome(c.aid, SignalOutcome(out_sig, FILTERED, FILTER_REASON, boundary,
                                                            {"tag": c.rule["tag"]}))
                    wrote = True
                    continue
                try:
                    plain_json(d)
                except (TypeError, ValueError) as exc:
                    self._alert(WARN, f"[extra] {c.aid}: 신호가 JSON이 아니어서 넣지 않음 ({type(exc).__name__})")
                    wrote = True
                    continue
                self.book.submit(c.aid, d)
                j.submitted(c.aid, d)
                wrote = True
        return wrote

    # ------------------------------------------------------------ phase 2: new strategies and activation
    def _phase2(self, boundary: int, deadline: float, j: Journal, t2: float, t0: float) -> bool:
        """The new strategies' signals and the activation poll, each in its own savepoint inside the phase's
        transaction: a failure in one part undoes only that part (its writes and in-memory changes), so a bad
        configuration value or an activation bug never costs the new-strategy accounts their signals, and a
        failing signal job never blocks the activation of copies."""
        h = self.state["health"]
        self.state["boundary"] = boundary
        if self.newlab is not None and self.newlab.specs:
            self._part(j, "newlab", boundary, lambda sub: self._newlab_boundary(boundary, deadline, sub))
        if time.monotonic() < deadline:
            self._activation(boundary, j)
        else:
            h = self.state["health"]
            h["budget_skips"] = int(h.get("budget_skips") or 0) + 1
            self._alert(WARN, f"[extra] 경계 {boundary}: 시간 예산을 넘어 이번에는 새 계좌 확인을 건너뜀")
        h = self.state["health"]
        h["phase2_ms"] = int((time.monotonic() - t2) * 1000)
        h["hook_ms"] = int((time.monotonic() - t0) * 1000)
        return True

    def _part(self, j: Journal, name: str, boundary: int, fn) -> tuple[bool, Any]:
        """Run one part of phase 2 in a savepoint. Kept: its journal joins the phase's. An exception: the savepoint
        is rolled back, the part's in-memory changes are undone, the error is counted and a WARN written
        (``_LateReject`` is not an error: the activation runs again). Returns (kept, result)."""
        conn = self.store.conn
        if not conn.in_transaction:
            conn.execute("BEGIN")             # so releasing the savepoint never commits on its own
        sub = Journal(self)
        conn.execute("SAVEPOINT extras_part")
        try:
            out = fn(sub)
        except Exception as exc:  # noqa: BLE001  only this part is undone
            try:
                conn.execute("ROLLBACK TO extras_part")
                conn.execute("RELEASE extras_part")
            except Exception:  # noqa: BLE001
                sub.undo()
                raise                         # the phase's own handler rolls the whole phase back
            sub.undo()
            if isinstance(exc, _LateReject):
                return False, exc
            h = self.state["health"]
            h["errors"] = int(h.get("errors") or 0) + 1
            h["last_error"] = f"phase 2 {name} at {boundary}: {type(exc).__name__}: {exc}"[:300]
            what = "새 매매법 신호" if name == "newlab" else "새 계좌 확인"
            self._alert(WARN, f"[extra] 추가 계좌 처리 2단계({what}) 실패, 이번 경계의 그 부분만 되돌림: "
                              f"{type(exc).__name__}: {exc}"[:300])
            return False, exc
        conn.execute("RELEASE extras_part")
        j.merge(sub)
        return True, out

    def _activation(self, boundary: int, j: Journal) -> None:
        """The activation poll (its own savepoint). Just before the phase's commit the sticky reject (R1) is read
        again on a fresh inbox connection for every proposal this poll created: a reject click made while the
        accounts were being created undoes the poll, which runs once more (C5 then refuses that proposal)."""
        def run(sub):
            created = self.activator.poll(boundary, sub)
            late = self.activator.recheck_rejects()
            if late:
                raise _LateReject(late)
            return created
        for _attempt in range(2):
            kept, out = self._part(j, "activation", boundary, run)
            if kept or not isinstance(out, _LateReject):
                return
            self._alert(INFO, f"[extra] 경계 {boundary}: 계좌를 만드는 동안 거절 클릭이 들어와 이번 확인을 되돌리고 "
                              f"다시 확인함 (제안 {', '.join('#' + str(p) for p in out.pids)})"[:300])

    def _newlab_boundary(self, boundary: int, deadline: float, j: Journal) -> None:
        src = self.newlab
        due = src.due(boundary)
        if not due:
            return
        results, skipped = src.compute(boundary, due, deadline)
        h = self.state["health"]
        h["newlab_jobs"] = int(h.get("newlab_jobs") or 0) + len(results)
        if skipped:
            h["budget_skips"] = int(h.get("budget_skips") or 0) + len(skipped)
            self._alert(WARN, f"[extra] 경계 {boundary}: 시간 예산을 넘어 새 매매법 계산 {len(skipped)}개를 건너뜀 "
                              f"({', '.join(skipped[:6])})"[:300])
        r = self.runner
        ready_at = r.now_ms()
        try:
            prices = r.prices() or {}
        except Exception:  # noqa: BLE001  no price: the rows say NO_PRICE
            prices = {}
        delay = ready_at - boundary
        max_delay = getattr(self.service, "max_delay_ms", 180_000)
        rows, subs = [], []
        ready_tf: dict = {}
        for res in results:
            tf = res["tf"]
            if res.get("ready"):
                ready_tf[tf] = None
            else:
                ready_tf.setdefault(tf, res.get("why") or "not ready")
            for e in res.get("errors") or []:
                self._alert(WARN, f"[extra] 새 매매법 신호 오류 {res['tf']} {res['symbol']}: {e}"[:300])
        for aid, (_n, tf, _s) in list(src.specs.items()):
            if tf in ready_tf:
                self._readiness(aid, ready_tf[tf])
        for res in results:
            if not res.get("ready"):
                continue
            sym, tf = res["symbol"], res["tf"]
            for aid, side in res["sides"].items():
                if not side:
                    continue
                x = self.extras.get(aid)
                if x is None or x.status != "active":
                    continue
                bid, ask = prices.get(sym, (None, None))
                ref = ask if side > 0 else bid
                atr = res.get("atr_last")
                if delay > max_delay:
                    status = "LATE"
                elif ref is None or atr is None:
                    status = "NO_PRICE" if ref is None else "NO_ATR"
                else:
                    status = "SUBMITTED"
                ctx = res.get("ctx")
                rows.append({"bar_close": boundary, "timeframe": tf, "strategy": x.strategy, "symbol": sym,
                             "side": int(side), "atr": atr, "ref_price": ref, "ref_time": ready_at, "delay_ms": delay,
                             "status": status,
                             "data": {"close": res.get("close"), "bid": bid, "ask": ask, "ctx": ctx,
                                      "newlab": {"account_id": aid, "trial_id": x.source.get("trial_id"),
                                                 "spec_hash": x.data.get("spec_hash"), "bars": res.get("bars")}}})
                if status == "SUBMITTED":
                    subs.append((aid, Signal(
                        ts=boundary - 1, symbol=sym, timeframe=tf, strategy_id=x.strategy, side=int(side),
                        stop_price=0.0, tier="best", atr=atr,
                        meta={"stop_dist": src.stop_atr * atr, "ref_price": ref, "ref_time": ready_at,
                              "delay_ms": delay, "account": aid, "ctx": ctx or {}})))
        if rows:
            self.store.log_signals(rows)
        for aid, sig in subs:
            try:
                plain_json(sig)
            except (TypeError, ValueError) as exc:
                self._alert(WARN, f"[extra] {aid}: 신호가 JSON이 아니어서 넣지 않음 ({type(exc).__name__})")
                continue
            if aid in self.book.engines:
                self.book.submit(aid, sig)
                j.submitted(aid, sig)

    # ------------------------------------------------------------ creation (called by the Activator)
    def create(self, j: Journal, boundary: int, kind: str, p: dict, t: dict, parsed: dict, gate: dict,
               owner_click_ts: Optional[int]) -> str:
        """Add the account inside the phase-2 transaction (committed by the phase's book.save)."""
        now = self.clock()
        # the same check as C0, on paper3.db itself (inside this transaction): an account another runner process
        # made for this proposal row is never made twice, even if this process's registry does not know it
        try:            # an extras row with unreadable data (held at load) must not abort every activation
            dup = self.store.conn.execute(
                "SELECT account_id FROM accounts WHERE kind IN ('copy', 'newlab') AND json_valid(data) "
                "AND json_extract(data, '$.source.proposal_id') = ? AND json_extract(data, '$.source.proposal_ts') = ?",
                (int(p["id"]), int(p["ts"]))).fetchone()
        except sqlite3.Error as exc:
            raise ValueError(f"could not check paper3 for an account of proposal #{p['id']}: {exc}") from exc
        if dup is not None:
            raise ValueError(f"account {dup[0]} already exists for proposal #{p['id']}")
        n = next_n(self.store.conn, kind)
        content = parsed["content"]
        src = source(int(p["id"]), int(p["ts"]), int(t["id"]), int(t["ts"]), content)
        activation = {"wall_ts": now, "boundary": boundary, "gate": gate, "decided_by": p.get("decided_by"),
                      "decided_ts": p.get("decided_ts"), "owner_click_ts": owner_click_ts}
        if kind == "copy":
            rule, s, tf = parsed["rule"], parsed["strategy"], parsed["timeframe"]
            aid, name, parent = copy_account_id(s, tf, n), s, f"{s}@{tf}"
            f = rule_fields(rule)
            data = {"v": V, "kind": "copy", "source": src, "rule": rule, "spec": None, "spec_hash": None,
                    "stop_atr": f["stop_atr"],
                    "first_lock": f["first_lock"] if f["first_lock"] is not None else self.settings.ladder_first_lock,
                    "label_ko": label_ko("copy", n, tf, strategy=s, rule=rule), "description_ko": None,
                    "window_5m": None, "code": None, "activation": activation}
        else:
            spec, h = parsed["spec"], parsed["spec_hash"]
            tf = spec["timeframe"]
            aid, name, parent = newlab_account_id(n, tf), f"NL{n}", None
            desc = None
            try:
                from .agents import newlab as _nl          # display only
                desc = _nl.describe_ko(spec)
            except Exception:  # noqa: BLE001
                desc = None
            src_nl = self._newlab_source()
            data = {"v": V, "kind": "newlab", "source": src, "rule": None, "spec": spec, "spec_hash": h,
                    "stop_atr": V3_STOP_ATR, "first_lock": self.settings.ladder_first_lock,
                    "label_ko": label_ko("newlab", n, tf, trial_id=int(t["id"])), "description_ko": desc,
                    "window_5m": int(src_nl.windows[tf]), "code": src_nl.pin(), "activation": activation}
            rule = None
        mk = engine_args(kind, rule, self.settings, self.digest, self.forward)
        e = self.book.add_extra({"account_id": aid, "strategy": name, "timeframe": tf, "kind": kind,
                                 "parent": parent, "data": data}, created_ts=boundary, **mk)
        j.added(aid)
        if isinstance(e, GuardedEngine):
            e.on_fault = self._on_fault
        x = Extra(aid, kind, name, tf, parent, boundary, data, rule=rule,
                  spec=data["spec"] if kind == "newlab" else None)
        self.extras[aid] = x
        if kind == "newlab":
            why = self.newlab.register(aid, name, tf, data["spec"])
            j.registered(aid)
            self._readiness(aid, why)
        pid = int(p["id"])
        text = f"[extra] 새 paper 계좌 시작: {data['label_ko']} ({aid}), 제안 #{pid}"
        self.store.alert(now, INFO, text)
        self._event(aid, "created", None, f"proposal #{pid}", effective=boundary, proposal_id=pid, boundary=boundary)
        self.state["created"][str(pid)] = {"account_id": aid, "boundary": boundary, "source": src}
        self.state["refused"].pop(str(pid), None)
        j.after.append((INFO, text))
        return aid

    # ------------------------------------------------------------ status
    def status(self) -> dict:
        return {"state": self.state, "extras": {aid: dataclasses.asdict(x) for aid, x in self.extras.items()}}


# ====================================================================== activation
class Activator:
    """Creates accounts from approved proposals at live boundaries (docs/extra-accounts.md, checks C0..C13).

    agents3.db is read in one read transaction on a fresh read-only connection, with exactly these queries
    (no model text: no change.why/approver/test/proposal, messages, notes, owner_messages, approvals.note or
    approvals.author is ever loaded):
        SELECT id, ts, room_id, trial_id, status, decided_ts, decided_by,
               COALESCE(json_extract(change, '$.kind'), 'copy'), json_extract(change, '$.account'),
               json_extract(gate, '$.pass') FROM proposals WHERE status = 'approved' ORDER BY id
        the trial (id, ts, kind, strategy, room_id, spec, spec_hash) with its latest result's status and the
        result paths $.result, $.n_trials, $.gate_input, $.n_tests_so_far, of kind 'test' or 'newlab' only
        COUNT(*) of the 'test' trials per room (every room); COUNT(*) of 'newlab' trials; the max id/ts of
        trials and proposals and the ts of the stored fingerprint rows (during the observation period only
        these counts and the fingerprint, so a restore then is seen too)
    inbox.db (a separate connection, read after agents3): the three approvals queries R1 (a reject click),
    R2 (the owner's approve click, author compared in SQL), R3 (an approve click after the feature start).
    """

    R1 = ("SELECT 1 FROM approvals WHERE proposal_id = ? AND decision = 'reject' AND ts >= ? LIMIT 1")
    R2 = ("SELECT MAX(ts) FROM approvals WHERE proposal_id = ? AND decision = 'approve' AND ts >= ? "
          "AND rtrim('owner:' || author, ':') = ?")
    R3 = ("SELECT MAX(ts) FROM approvals WHERE proposal_id = ? AND decision = 'approve' AND ts >= MAX(?, ?)")
    Q_PROPOSALS = ("SELECT id, ts, room_id, trial_id, status, decided_ts, decided_by, "
                   "COALESCE(json_extract(change, '$.kind'), 'copy') AS kind, "
                   "json_extract(change, '$.account') AS account, json_extract(gate, '$.pass') AS gate_pass "
                   "FROM proposals WHERE status = 'approved' ORDER BY id")
    Q_TRIAL = ("SELECT t.id, t.ts, t.kind, t.strategy, t.room_id, t.spec, t.spec_hash, r.status AS result_status, "
               "json_extract(r.result, '$.result') AS test_result, json_extract(r.result, '$.n_trials') AS n_trials, "
               "json_extract(r.result, '$.gate_input') AS gate_input, "
               "json_extract(r.result, '$.n_tests_so_far') AS n_tests_so_far "
               "FROM trials t LEFT JOIN trial_results r ON r.id = (SELECT MAX(id) FROM trial_results "
               "WHERE trial_id = t.id) WHERE t.id = ? AND t.kind IN ('test', 'newlab')")
    Q_ROOM_TESTS = "SELECT room_id, COUNT(*) FROM trials WHERE kind = 'test' GROUP BY room_id"
    Q_NEWLAB_TESTS = "SELECT COUNT(*) FROM trials WHERE kind = 'newlab'"

    def __init__(self, ext: Extras):
        self.x = ext
        self.min_parent_trades: Optional[int] = None     # tests: overrides PARENT_MIN_TRADES
        self.created_now: list[tuple[int, int]] = []     # (proposal id, ts) of the accounts the last poll created

    def recheck_rejects(self) -> list[int]:
        """R1 again, on a fresh inbox connection, for the proposals whose accounts the last poll created (called
        just before the phase-2 commit). Returns the proposal ids that now have a reject click; when the inbox
        cannot be read, all of them (nothing of the poll is kept; the next boundary checks again)."""
        if not self.created_now:
            return []
        from .agents import rooms_db as R
        pids = [pid for pid, _ts in self.created_now]
        inbox = R.open_ro(self.x.cfg.inbox_db) if self.x.cfg.inbox_db else None
        if inbox is None:
            return pids
        try:
            return [pid for pid, p_ts in self.created_now
                    if inbox.execute(Activator.R1, (pid, p_ts)).fetchone() is not None]
        except sqlite3.Error:
            return pids
        finally:
            inbox.close()

    # ------------------------------------------------------------ helpers
    def _reload_config(self) -> None:
        x = self.x
        p = x.config_path
        if not p:
            return
        try:
            mt = os.path.getmtime(p) if os.path.exists(p) else None
        except OSError:
            mt = None
        if mt == x.cfg_mtime:
            return
        x.cfg_mtime = mt
        if mt is None:
            x.cfg = Config.default(x.db_path)
            return
        try:
            with open(p) as fh:
                cfg = Config.from_text(fh.read(), x.db_path, p)
        except Exception as exc:  # noqa: BLE001  keep the last good configuration
            text = f"[extra] extras.json를 읽지 못해 이전 설정을 그대로 씁니다: {type(exc).__name__}: {exc}"[:300]
            if x.cfg_warned != text:
                x.cfg_warned = text
                x._alert(WARN, text)
            return
        x.cfg_warned = None
        if cfg.warning:
            x._alert(WARN, f"[extra] {cfg.warning}")
        x.cfg = cfg

    def run_start(self) -> Optional[int]:
        """The run's start: its earliest original account (every original kind, accounts.ORIGINAL_KINDS)."""
        q = ",".join("?" * len(ORIGINAL_KINDS))
        r = self.x.store.conn.execute(
            f"SELECT MIN(created_ts) FROM accounts WHERE kind IN ({q})", ORIGINAL_KINDS).fetchone()
        return None if r is None or r[0] is None else int(r[0])

    def _set_dbs(self, agents: str, inbox: str) -> None:
        self.x.state["agents_db"], self.x.state["inbox_db"] = agents, inbox

    def _refuse(self, refused: dict, p: dict, code: str, detail: str, boundary: int) -> None:
        key = str(p["id"])
        old = self.x.state["refused"].get(key)
        same = old is not None and old.get("code") == code and old.get("proposal_ts") == p["ts"]
        refused[key] = {"code": code, "permanent": code in PERMANENT, "proposal_ts": p["ts"],
                        "since": old.get("since") if same else boundary, "detail": str(detail)[:300]}
        if not same:
            level = WARN if (code in PERMANENT or code in LOUD) else INFO
            self.x._alert(level, f"[extra] 제안 #{p['id']}: 새 계좌를 시작하지 않음 — {code} "
                                 f"({CODES_KO.get(code, code)}){': ' + str(detail)[:120] if detail else ''}"[:300])

    # ------------------------------------------------------------ the poll
    def poll(self, boundary: int, j: Journal) -> list[str]:
        """G1..G5 and C0..C13 for every approved proposal (docs/extra-accounts.md). Returns created ids."""
        x = self.x
        self.created_now = []
        self._reload_config()
        cfg = x.cfg
        st = x.state
        if cfg.pause_activation:
            self._set_dbs("paused", "paused")
            return []
        if not cfg.activation:
            self._set_dbs("off", "off")
            return []
        run_start = self.run_start()
        floor = observe_floor(run_start, cfg)
        st["run_start"], st["observe_until"] = run_start, floor
        if run_start is None:
            self._set_dbs("observing", "observing")
            return []
        # During the observation period nothing is created, but agents3.db is still read (fingerprint and test
        # counts only), so a restore in those days is seen and the gate's high-water marks never drop.
        observing = boundary < floor
        inbox_now = "observing" if observing else st.get("inbox_db")
        from .agents import rooms_db as R      # read-only openers (frozen interface)
        conn = R.open_ro(cfg.agents_db)
        if conn is None:
            self._set_dbs("observing" if observing else
                          ("missing" if not os.path.exists(cfg.agents_db) else "unreadable"), inbox_now)
            return []
        inbox = None
        created: list[str] = []
        try:
            try:
                conn.execute("BEGIN")
                snap = self._read_agents(conn, proposals=not observing)
            except sqlite3.Error as exc:
                self._set_dbs("unreadable", inbox_now)
                st["health"]["last_error"] = f"agents3 read: {type(exc).__name__}: {exc}"[:300]
                return []
            self._fold_hwm(snap)
            fp_ok = self._fingerprint(conn, snap, cfg)
            if not fp_ok:
                self._set_dbs("regressed", inbox_now)
                return []
            if observing:
                self._set_dbs("observing", "observing")
                return []
            self._set_dbs("ok", st.get("inbox_db"))
            inbox = R.open_ro(cfg.inbox_db)
            inbox_state = "ok" if inbox is not None else ("missing" if not os.path.exists(cfg.inbox_db) else "unreadable")
            inbox_code = "inbox_unreadable"
            if inbox is not None:
                try:
                    fp_in = self._inbox_fingerprint(inbox, cfg)
                except sqlite3.Error:
                    fp_in = None
                if fp_in is not True:              # unreadable, or restored to an older copy (not acknowledged)
                    inbox.close()
                    inbox = None
                    inbox_state = "unreadable" if fp_in is None else "regressed"
                    inbox_code = "inbox_unreadable" if fp_in is None else "inbox_regressed"
            if inbox_state != st.get("inbox_db") and inbox_state in ("missing", "unreadable"):
                self.x._alert(WARN, f"[extra] inbox.db({cfg.inbox_db}) {'없음' if inbox_state == 'missing' else '읽지 못함'}: "
                                    "승인·거절 클릭을 확인할 수 없어 새 계좌를 만들지 않습니다(대시보드가 켜져 있는지, "
                                    "extras.json의 inbox_db 경로가 맞는지 확인)"[:300])
            refused: dict = {}
            for p in snap["proposals"]:
                try:
                    aid = self._candidate(boundary, p, snap, conn, inbox, cfg, run_start, floor, j, refused,
                                          inbox_code)
                except _InboxError as exc:
                    inbox_state = "unreadable"
                    try:
                        inbox.close()
                    except Exception:  # noqa: BLE001
                        pass
                    inbox = None
                    self._refuse(refused, p, "inbox_unreadable", str(exc), boundary)
                    continue
                if aid:
                    created.append(aid)
                    self.created_now.append((int(p["id"]), int(p["ts"])))
            st["inbox_db"] = inbox_state
            st["refused"] = refused
            try:
                conn.execute("COMMIT")
            except sqlite3.Error:
                pass
            return created
        finally:
            for c in (conn, inbox):
                if c is not None:
                    try:
                        c.close()
                    except Exception:  # noqa: BLE001
                        pass

    def _read_agents(self, conn, proposals: bool = True) -> dict:
        """One snapshot. The strict test counts are read for every room on every poll (one query), so the
        high-water marks hold every room's count, not only the rooms with an approved proposal at that moment.
        ``proposals=False`` (the observation period): the counts only."""
        props = []
        if proposals:
            for r in conn.execute(self.Q_PROPOSALS).fetchall():
                props.append({"id": int(r[0]), "ts": int(r[1]), "room_id": r[2], "trial_id": r[3], "status": r[4],
                              "decided_ts": r[5], "decided_by": r[6], "kind": r[7], "account": r[8],
                              "gate_pass": r[9]})
        trials = {}
        for p in props:
            tid = p["trial_id"]
            if isinstance(tid, int) and tid not in trials:
                row = conn.execute(self.Q_TRIAL, (tid,)).fetchone()
                trials[tid] = None if row is None else {
                    "id": int(row[0]), "ts": int(row[1]), "kind": row[2], "strategy": row[3], "room_id": row[4],
                    "spec": _loads(row[5]), "spec_hash": row[6], "result_status": row[7],
                    "test_result": _loads(row[8]), "n_trials": row[9], "gate_input": _loads(row[10]),
                    "n_tests_so_far": row[11]}
        rooms = {r[0]: int(r[1]) for r in conn.execute(self.Q_ROOM_TESTS).fetchall() if isinstance(r[0], str)}
        newlab = int(conn.execute(self.Q_NEWLAB_TESTS).fetchone()[0])
        return {"proposals": props, "trials": trials, "room_counts": rooms, "newlab_count": newlab}

    def _fold_hwm(self, snap: dict) -> None:
        """The high-water marks take the counts just read (they never go down within a paper3.db)."""
        hw = self.x.state["hwm"]
        for room, n in snap["room_counts"].items():
            hw["room_tests"][room] = max(int(hw["room_tests"].get(room, 0)), int(n))
        hw["newlab_tests"] = max(int(hw.get("newlab_tests") or 0), int(snap["newlab_count"]))

    def _fingerprint(self, conn, snap: dict, cfg: Config) -> bool:
        """False while agents3.db looks restored to an older copy and the operator has not acknowledged it."""
        st = self.x.state
        t = conn.execute("SELECT id, ts FROM trials ORDER BY id DESC LIMIT 1").fetchone()
        p = conn.execute("SELECT id, ts FROM proposals ORDER BY id DESC LIMIT 1").fetchone()
        cur = {"trial": [int(t[0]), int(t[1])] if t else [0, 0], "proposal": [int(p[0]), int(p[1])] if p else [0, 0]}
        old = st.get("fingerprint")
        if not old:
            st["fingerprint"] = cur
            return True
        bad = False
        for key, table in (("trial", "trials"), ("proposal", "proposals")):
            oid, ots = (old.get(key) or [0, 0])[:2]
            if cur[key][0] < int(oid):
                bad = True
            elif int(oid) > 0:
                r = conn.execute(f"SELECT ts FROM {table} WHERE id = ?", (int(oid),)).fetchone()
                if r is None or int(r[0]) != int(ots):
                    bad = True
        text = fingerprint_text(cur)
        if bad:
            if cfg.agents_ack and cfg.agents_ack == text:
                st["fingerprint"] = cur                # hwm is kept: the gate never loosens after a restore
                st.pop("regressed_alert", None)
                self.x._alert(WARN, f"[extra] 에이전트 장부 복원을 운영자가 확인함 ({text}); 새 계좌 확인을 다시 시작")
                return True
            if st.get("regressed_alert") != text:
                st["regressed_alert"] = text
                self.x._alert(CRITICAL, f"[extra] agents3.db가 예전 것으로 바뀐 것 같아 새 계좌 시작을 멈춤. 확인 후 "
                                        f"extras.json에 \"agents_ack\": \"{text}\" 를 넣으세요")
            return False
        st.pop("regressed_alert", None)
        if cur["trial"][0] > int((old.get("trial") or [0])[0]) or cur["proposal"][0] > int((old.get("proposal") or [0])[0]):
            st["fingerprint"] = cur
        return True

    def _inbox_fingerprint(self, inbox, cfg: Config) -> bool:
        """False while inbox.db looks restored to an older copy (or replaced by an empty one) and the operator has
        not acknowledged it: clicks made after its backup are lost, so a lost reject must not let an account
        start and a lost approve must not count as missing for good. ``state.inbox_fingerprint`` = [max approval
        id, its ts]; regressed when the max id went down or the stored id's row is gone or has another ts."""
        st = self.x.state
        r = inbox.execute("SELECT id, ts FROM approvals ORDER BY id DESC LIMIT 1").fetchone()
        cur = [int(r[0]), int(r[1])] if r else [0, 0]
        old = st.get("inbox_fingerprint")
        if not old:
            st["inbox_fingerprint"] = cur
            return True
        oid, ots = int(old[0]), int(old[1])
        bad = cur[0] < oid
        if not bad and oid > 0:
            row = inbox.execute("SELECT ts FROM approvals WHERE id = ?", (oid,)).fetchone()
            bad = row is None or int(row[0]) != ots
        text = inbox_fingerprint_text(cur)
        if bad:
            if cfg.inbox_ack and cfg.inbox_ack == text:
                st["inbox_fingerprint"] = cur
                st.pop("inbox_regressed_alert", None)
                self.x._alert(WARN, f"[extra] 승인 클릭 기록 복원을 운영자가 확인함 ({text}); 새 계좌 확인을 다시 시작")
                return True
            if st.get("inbox_regressed_alert") != text:
                st["inbox_regressed_alert"] = text
                self.x._alert(CRITICAL, "[extra] inbox.db(승인·거절 클릭 기록)가 예전 것으로 바뀐 것 같아 새 계좌 시작을 "
                                        "멈춤. 백업 뒤에 누른 승인·거절은 두 분이 다시 누른 뒤 extras.json에 "
                                        f"\"inbox_ack\": \"{text}\" 를 넣으세요")
            return False
        st.pop("inbox_regressed_alert", None)
        if cur[0] > oid:
            st["inbox_fingerprint"] = cur
        return True

    def _gate_modules(self):
        from .agents import actions as A
        from .agents import labtests as LT
        from .agents import newlab as NL
        return A, LT, NL

    # ------------------------------------------------------------ one proposal
    def _candidate(self, boundary: int, p: dict, snap: dict, conn, inbox, cfg: Config, run_start: int,
                   floor: int, j: Journal, refused: dict, inbox_code: str = "inbox_unreadable") -> Optional[str]:
        x = self.x
        kind = p["kind"]
        t = snap["trials"].get(p["trial_id"]) if isinstance(p["trial_id"], int) else None
        # C0 already created (the proposal row's identity is (id, ts))
        for e in x.extras.values():
            s = e.source
            if s.get("proposal_id") == p["id"] and s.get("proposal_ts") == p["ts"]:
                if t is not None and s.get("trial_id") == t["id"] and s.get("trial_ts") == t["ts"]:
                    x.state["created"].setdefault(str(p["id"]), {"account_id": e.aid, "boundary": e.created_ts,
                                                                  "source": s})
                    return None
                self._refuse(refused, p, "id_conflict", f"account {e.aid} has another trial", boundary)
                return None
        # the same, from the record written with the creation (an account whose data cannot be read any more)
        rec = x.state["created"].get(str(p["id"]))
        if isinstance(rec, dict) and (rec.get("source") or {}).get("proposal_ts") == p["ts"] \
                and rec.get("account_id") in x.book.engines:
            return None
        try:
            parsed = self._checks(boundary, p, t, kind, snap, conn, inbox, cfg, run_start, floor, inbox_code)
        except Refusal as r:
            self._refuse(refused, p, r.code, r.detail, boundary)
            return None
        try:
            return x.create(j, boundary, kind, p, t, parsed, parsed["gate"], parsed.get("owner_click_ts"))
        except ValueError as exc:                                      # C13: the next id exists
            self._refuse(refused, p, "id_conflict", str(exc), boundary)
            return None

    def _checks(self, boundary, p, t, kind, snap, conn, inbox, cfg, run_start, floor,
                inbox_code: str = "inbox_unreadable") -> dict:
        x = self.x
        # C1 contract
        acct = _loads(p["account"]) if isinstance(p["account"], str) else p["account"]
        if kind not in KINDS:
            raise Refusal("contract_mismatch", f"kind {str(kind)[:20]}")
        if not isinstance(acct, dict) or acct.get("v") != 1:
            raise Refusal("contract_missing", "change.account missing or v != 1")
        if acct.get("kind") != kind or acct.get("trial_id") != p["trial_id"]:
            raise Refusal("contract_mismatch", "kind or trial_id")
        # C2 trial
        want_kind, want_status = ("test", "passed") if kind == "copy" else ("newlab", "proposed")
        if t is None or t["kind"] != want_kind:
            raise Refusal("trial_status", "missing" if t is None else f"kind {t['kind']}")
        if t["result_status"] != want_status:
            raise Refusal("trial_status", str(t["result_status"]))
        # C3 the runner's own validation
        names = list(getattr(x.service, "names", []) or [])
        if kind == "copy":
            rule, s, tf, content = parse_copy(acct, t, p, names)
            parsed = {"rule": rule, "strategy": s, "timeframe": tf, "content": content}
        else:
            spec, h, content = parse_newlab(acct, t, p)
            parsed = {"spec": spec, "spec_hash": h, "timeframe": spec["timeframe"], "content": content}
            why_tf = run_timeframe_refusal(spec["timeframe"], getattr(x.service, "trade_tfs", None))
            if why_tf:
                raise Refusal("spec_invalid", why_tf)
        # C4 run binding
        dts = p["decided_ts"]
        if p["ts"] < floor or not isinstance(dts, int) or dts < run_start:
            raise Refusal("stale_run", f"proposal {p['ts']} / decided {dts} vs run {run_start} floor {floor}")
        # C5 sticky reject
        if inbox is None:
            raise Refusal(inbox_code, "inbox.db restored to an older copy" if inbox_code == "inbox_regressed"
                          else "inbox.db missing or unreadable")
        try:
            rej = inbox.execute(Activator.R1, (p["id"], p["ts"])).fetchone()
        except sqlite3.Error as exc:
            raise _InboxError(f"{type(exc).__name__}: {exc}")
        if rej is not None:
            raise Refusal("reject_pending", "reject click")
        # C6 owner OK
        need_owner = kind == "newlab" or dts < run_start + cfg.owner_ok_days * DAY_MS
        click = None
        if need_owner:
            by = p["decided_by"]
            if not (isinstance(by, str) and (by == "owner" or by.startswith("owner:"))):
                raise Refusal("owner_ok_missing", f"decided_by {str(by)[:40]}")
            try:
                click = inbox.execute(Activator.R2, (p["id"], p["ts"], by)).fetchone()[0]
            except sqlite3.Error as exc:
                raise _InboxError(f"{type(exc).__name__}: {exc}")
            if click is None:
                raise Refusal("owner_click_missing", "no matching approve click")
        # C7 the feature start
        since = int(x.state.get("since") or 0)
        if dts < since:
            try:
                fresh = inbox.execute(Activator.R3, (p["id"], p["ts"], since)).fetchone()[0]
            except sqlite3.Error as exc:
                raise _InboxError(f"{type(exc).__name__}: {exc}")
            if fresh is None:
                raise Refusal("stale_ok", "approved before the feature started")
            click = max(click or 0, int(fresh))
        parsed["owner_click_ts"] = click
        # C8 duplicate
        for e in x.extras.values():
            if kind == "copy" and e.kind == "copy" and e.parent == f"{parsed['strategy']}@{parsed['timeframe']}" \
                    and e.source.get("content") == parsed["content"]:
                raise Refusal("duplicate", e.aid)
            if kind == "newlab" and e.kind == "newlab" and e.data.get("spec_hash") == parsed["spec_hash"]:
                raise Refusal("duplicate", e.aid)
        # C9 parent
        if kind == "copy":
            parent = f"{parsed['strategy']}@{parsed['timeframe']}"
            meta = x.book.meta.get(parent)
            if meta is None or meta.get("kind") != "strategy":
                raise Refusal("parent_missing", parent)
            eng = x.book.engines.get(parent)
            if eng is None or eng.bust:
                raise Refusal("parent_bust", parent)
            n = int(x.store.conn.execute("SELECT COUNT(*) FROM trades WHERE account_id = ?", (parent,)).fetchone()[0])
            need = PARENT_MIN_TRADES if self.min_parent_trades is None else self.min_parent_trades
            if n < need:
                raise Refusal("parent_trades", f"{n} < {need}")
        # C10 gate now
        parsed["gate"] = self._gate(kind, p, t, snap, conn)
        # C11 caps on existing extras (held and suspended included)
        if kind == "copy":
            if sum(1 for e in x.extras.values() if e.kind == "copy" and e.strategy == parsed["strategy"]) \
                    >= CAP_COPY_PER_STRATEGY:
                raise Refusal("cap_strategy", parsed["strategy"])
            if sum(1 for e in x.extras.values() if e.kind == "copy") >= CAP_COPY_TOTAL:
                raise Refusal("cap_copy_total", str(CAP_COPY_TOTAL))
        elif sum(1 for e in x.extras.values() if e.kind == "newlab") >= CAP_NEWLAB_TOTAL:
            raise Refusal("cap_newlab_total", str(CAP_NEWLAB_TOTAL))
        # C12 newlab readiness
        if kind == "newlab":
            try:
                src = x._newlab_source()
                ok, why = src.available()
            except Exception as exc:  # noqa: BLE001
                ok, why = False, f"{type(exc).__name__}: {exc}"
            if not ok:
                raise Refusal("newlab_unavailable", why or "")
            tf = parsed["timeframe"]
            if src.windows.get(tf, 0) > src.maxlen():
                raise Refusal("newlab_unavailable", f"window {src.windows.get(tf)} > history {src.maxlen()}")
        return parsed

    def _gate(self, kind: str, p: dict, t: dict, snap: dict, conn) -> dict:
        """C10: the gate judged now with strict counts and high-water marks, cross-checked with the agents'
        own re-judging functions (which fail open to a stored n when a count read fails)."""
        x = self.x
        try:
            A, LT, NL = self._gate_modules()
        except Exception as exc:  # noqa: BLE001
            raise Refusal("gate_code_unavailable", f"{type(exc).__name__}: {exc}")
        hw = x.state["hwm"]
        if kind == "copy":
            n_strict = int(snap["room_counts"].get(p["room_id"], 0))
            nt = t.get("n_trials")
            n_at = nt if isinstance(nt, int) and not isinstance(nt, bool) and nt > 0 else 1
            n_hwm = int(hw["room_tests"].get(p["room_id"], 0))
            n = max(n_strict, n_hwm, n_at)
            res = t.get("test_result")
            try:
                ok = isinstance(res, dict) and res.get("ok") is True and LT.gate(res, n).get("pass") is True
            except Exception:  # noqa: BLE001
                ok = False
            if not ok:
                raise Refusal("gate_now_fail", f"n {n}")
            trial_min = {"id": t["id"], "kind": "test", "strategy": t["strategy"], "spec": t["spec"],
                         "result": {"status": t["result_status"],
                                    "result": {"result": res, "n_trials": t.get("n_trials")}}}
            try:
                env = A.ActionEnv(conn=conn, room_id=p["room_id"], strategy=t["strategy"], round_id=None,
                                  meeting="activation", now_ms=x.clock())
                g, n_a = A.current_gate(env, trial_min)
            except Exception as exc:  # noqa: BLE001
                raise Refusal("gate_disagree", f"{type(exc).__name__}: {exc}")
            if int(n_a) != max(n_strict, n_at) or (g or {}).get("pass") is not True:
                raise Refusal("gate_disagree", f"actions n {n_a} vs {max(n_strict, n_at)}")
            return {"n": n, "n_strict": n_strict, "n_hwm": n_hwm, "n_at_test": n_at}
        nts = t.get("n_tests_so_far")
        n_then = nts if isinstance(nts, int) and not isinstance(nts, bool) and nts > 0 else 0
        n_strict = int(snap["newlab_count"])
        n_hwm = int(hw.get("newlab_tests") or 0)
        n = max(n_then, max(n_strict, n_hwm) - 1)
        gi = t.get("gate_input")
        try:
            ok = isinstance(gi, dict) and bool(gi) and \
                NL.gate({"ok": True, "status": "done", "periods": gi}, n).get("pass") is True
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            raise Refusal("gate_now_fail", f"n {n}")
        trial_min = {"id": t["id"], "kind": "newlab", "spec": t["spec"], "spec_hash": t["spec_hash"],
                     "result": {"status": t["result_status"],
                                "result": {"gate_input": gi, "n_tests_so_far": t.get("n_tests_so_far")}}}
        try:
            g, n_a = A.newlab_gate_now(conn, trial_min)
        except Exception as exc:  # noqa: BLE001
            raise Refusal("gate_disagree", f"{type(exc).__name__}: {exc}")
        if int(n_a) != max(n_then, n_strict - 1) or (g or {}).get("pass") is not True:
            raise Refusal("gate_disagree", f"actions n {n_a} vs {max(n_then, n_strict - 1)}")
        return {"n": n, "n_strict": n_strict, "n_hwm": n_hwm, "n_then": n_then}


class _InboxError(Exception):
    pass


class _LateReject(Exception):
    """A reject click arrived for a proposal while its account was being created (before the commit)."""

    def __init__(self, pids: list):
        super().__init__(f"reject click for proposal(s) {pids} during creation")
        self.pids = list(pids)


def _loads(v: Any) -> Any:
    if v is None or not isinstance(v, (str, bytes)):
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return None


# ====================================================================== status command
def status_text(paper_db: str) -> str:
    """The extras state of a paper3.db in plain words (read only)."""
    import urllib.parse
    uri = "file:" + urllib.parse.quote(os.path.abspath(paper_db)) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        r = conn.execute("SELECT ts, data FROM state WHERE k = ?", (STATE_KEY,)).fetchone()
        q = ",".join("?" * len(ORIGINAL_KINDS))
        rows = conn.execute("SELECT account_id, kind, created_ts, parent FROM accounts "
                            f"WHERE kind NOT IN ({q}) ORDER BY rowid", ORIGINAL_KINDS).fetchall()
    finally:
        conn.close()
    if r is None:
        return "no extras state yet (the runner with the extras feature has not started on this database)"
    st = json.loads(r[1])
    lines = [f"extras state {st.get('ts')}: agents3 {st.get('agents_db')}, inbox {st.get('inbox_db')}, "
             f"since {st.get('since')}, observe until {st.get('observe_until')}",
             f"accounts: {len(rows)} (copy {st.get('counts', {}).get('copy', 0)}, "
             f"newlab {st.get('counts', {}).get('newlab', 0)}), fingerprint {fingerprint_text(st.get('fingerprint'))}, "
             f"inbox fingerprint {inbox_fingerprint_text(st.get('inbox_fingerprint'))}"]
    acc = st.get("accounts") or {}
    for aid, kind, created, parent in rows:
        a = acc.get(aid) or {"status": "active"}
        lines.append(f"  {aid:28s} {kind:7s} created {created} {a.get('status')}"
                     + (f" ({a.get('code')})" if a.get("code") else "") + (f" parent {parent}" if parent else ""))
    for pid, rf in sorted((st.get("refused") or {}).items(), key=lambda kv: int(kv[0])):
        lines.append(f"  proposal #{pid}: {rf.get('code')}{' (permanent)' if rf.get('permanent') else ''} "
                     f"{CODES_KO.get(rf.get('code'), '')}")
    h = st.get("health") or {}
    lines.append(f"health: hook {h.get('hook_ms')} ms, phase2 {h.get('phase2_ms')} ms, newlab jobs "
                 f"{h.get('newlab_jobs')}, budget skips {h.get('budget_skips')}, errors {h.get('errors')}, "
                 f"last error {h.get('last_error')}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status")
    s.add_argument("--db", default="paper3.db")
    args = ap.parse_args(argv)
    print(status_text(args.db))
    return 0


if __name__ == "__main__":
    sys.exit(main())
