"""Account groups of the paper v4 run, for display and reports only (dashboard, Telegram texts, agents, daily
report). NOT a trading file: it is in none of runinfo's TRADING_FILES / EXTRA_FILES / RULES_FILES, so a name or a
label here can change during the run without restarting any window. Nothing on the trading path imports it.

Groups (config.V4_GROUPS has the run shape; accounts.GROUP_OF_KIND maps a kind to its group):
    core   the 36 locked strategies (kind "strategy")          매매법
    ds200  the 44 DeepSeek-200 definitions (kind "ds200")      딥시크
    reel   the 5m reel strategy REEL_H1 (kind "reel")          5분 단타
    flip   the coin flips RANDOM_k (kind "random")             동전
    extra  copies and new-lab strategies (kinds copy, newlab)  추가 계좌
A surface that has not been taught a group leaves it out (fail safe), it never mixes it into the 36.

Owners' decisions this module carries (docs/paper-v4-rules.md): D10 (per-trade Telegram for core, reel and extras;
counts only for DeepSeek and the coin flips), D11 (DeepSeek P&L is visible, but only in its own group view: no blind
switch), the five new specialist roles that cover DeepSeek and the reel (the 36 specialists and 12 teams stay).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Optional

from .accounts import GROUP_OF_KIND, ORIGINAL_KINDS
from .config import DS200_DEFS, DS200_FAMILY, REEL_NAME, REEL_TF, V4_GROUPS

GROUPS = ("core", "ds200", "reel", "flip", "extra")
ORIGINAL_GROUPS = ("core", "ds200", "reel", "flip")
GROUP_KO = {"core": "매매법", "ds200": "딥시크", "reel": "5분 단타", "flip": "동전", "extra": "추가 계좌"}
GROUP_LONG_KO = {"core": "잠긴 매매법 36개", "ds200": "딥시크 200 정의 44개", "reel": "인스타 릴스 5분봉 단타",
                 "flip": "동전 던지기(비교용)", "extra": "복사·새 매매법 계좌"}

# Telegram (owners' D10): one message per trade for these groups; DeepSeek and the coin flips are counted only.
# Liquidations stay loud for every group (bundled).
TRADE_ALERT_GROUPS = ("core", "reel", "extra")
COUNT_ONLY_GROUPS = ("ds200", "flip")
# Dashboard: the group switch starts on these (plan P10).
DEFAULT_SHOWN_GROUPS = ("core", "reel")

# DeepSeek families, names from research/deepseek200/PREREG_DEEPSEEK200.md section 5 headings.
DS_FAMILY_KO = {
    "F1": "다이버전스", "F2": "디마크 피벗", "F3": "구조 돌파·공급수요", "F4": "EMA 눌림·정렬", "F5": "박스권",
    "F6": "VWAP", "F7": "Range Filter 3중 일치", "F8": "Virgin Wick POI", "F9": "FVG·오더 블록", "F10": "ICT 모델",
    "F11": "유동성 스윕", "F12": "구조 전환 MSS", "F13": "프리미엄/디스카운트", "F14": "SMT 다이버전스",
    "F15": "세션 레인지·시가 편향", "F16": "피보나치 되돌림", "F17": "Z-score 평균회귀",
}
REEL_KO = "릴스 5분 단타 (볼린저 20·2 + 200선)"
FLIP5M_KO = "동전 던지기 5분 (롱만, 릴스 청산)"

# The five specialist roles added for v4 (owners 2026-10-05): four for the DeepSeek families, one for the reel.
# (key, Korean title, DeepSeek families, extra definition ids). F11_PO3 (Power of 3) sits with the session role,
# with F15 (sessions, ORB); the other F11 definitions with structure and liquidity.
V4_ROLES = (
    ("ds_structure", "구조·유동성 담당", ("F3", "F9", "F10", "F11", "F12", "F13", "F14"), ()),
    ("ds_trend", "추세·눌림 담당", ("F4", "F6", "F7"), ()),
    ("ds_session", "세션·시가 담당", ("F15",), ("F11_PO3",)),
    ("ds_reversal", "반전·되돌림 담당", ("F1", "F2", "F5", "F8", "F16", "F17"), ()),
    ("reel_5m", "5분봉 단타 담당", (), (REEL_NAME,)),
)
ROLE_KO = {k: ko for k, ko, _f, _x in V4_ROLES}


def _data(row: dict) -> dict:
    raw = row.get("data")
    if isinstance(raw, dict):
        return raw
    try:
        d = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def group_of(row: dict) -> str:
    """The group of an accounts row (needs "kind"): by kind, "other" for a kind this module does not know."""
    return GROUP_OF_KIND.get(row.get("kind"), "other")


def family_of(row: dict) -> Optional[str]:
    """A DeepSeek account's family ("F9"), from its row data or the definition table; None for other accounts."""
    if row.get("kind") != "ds200":
        return None
    fam = _data(row).get("family")
    return fam if isinstance(fam, str) and fam else DS200_FAMILY.get(row.get("strategy"))


def role_of(strategy: str) -> Optional[str]:
    """The v4 specialist role key of a DeepSeek definition or the reel; None for every other strategy (the 36 keep
    their own specialists)."""
    for key, _ko, fams, ids in V4_ROLES:
        if strategy in ids:
            return key
    fam = DS200_FAMILY.get(strategy)
    if fam is None:
        return None
    for key, _ko, fams, ids in V4_ROLES:
        if fam in fams:
            return key
    return None


def role_members(role: str) -> list[str]:
    """The strategies one v4 specialist role covers (DeepSeek ids in PREREG order, or the reel)."""
    return [d for d, _f, _t in DS200_DEFS if role_of(d) == role] + ([REEL_NAME] if role_of(REEL_NAME) == role else [])


def label_ko(strategy: str, timeframe: Optional[str] = None) -> Optional[str]:
    """A Korean label for a DeepSeek definition, the reel or a 5m coin flip; None for anything else (callers keep
    their own names for the 36, the v3 coin flips and the extras)."""
    if strategy in DS200_FAMILY:
        return f"딥시크 {strategy} ({DS_FAMILY_KO[DS200_FAMILY[strategy]]})"
    if strategy == REEL_NAME:
        return REEL_KO
    if timeframe == REEL_TF and isinstance(strategy, str) and strategy.startswith("RANDOM_"):
        return f"{FLIP5M_KO} {strategy[len('RANDOM_'):]}"
    return None


def shape_from_db(conn: sqlite3.Connection) -> dict:
    """The run shape as the accounts table holds it (display code reads this, never config's numbers):
    {"accounts": n, "originals": n, "versions": [settings_version, ...],
     "groups": {group: {"accounts": n, "tfs": {tf: n}, "judged": n}}, "tfs": {tf: n}}.
    "judged" counts the original accounts on their group's judged timeframes (config.V4_GROUPS); 0 for the coin
    flips and the extras (the checkpoint decides about copies and new-lab accounts)."""
    rows = conn.execute("SELECT account_id, strategy, timeframe, kind, settings_version FROM accounts").fetchall()
    groups: dict[str, dict] = {}
    tfs: dict[str, int] = {}
    versions = set()
    originals = 0
    kind_group = {spec["kind"]: g for g, spec in V4_GROUPS.items()}
    for _aid, _strategy, tf, kind, version in rows:
        g = group_of({"kind": kind})
        e = groups.setdefault(g, {"accounts": 0, "tfs": {}, "judged": 0})
        e["accounts"] += 1
        e["tfs"][tf] = e["tfs"].get(tf, 0) + 1
        tfs[tf] = tfs.get(tf, 0) + 1
        versions.add(version)
        if kind in ORIGINAL_KINDS:
            originals += 1
            spec = V4_GROUPS.get(kind_group.get(kind, ""))
            if spec is not None and tf in spec["judged"]:
                e["judged"] += 1
    order = {g: k for k, g in enumerate(GROUPS)}
    return {"accounts": len(rows), "originals": originals, "versions": sorted(v for v in versions if v),
            "groups": dict(sorted(groups.items(), key=lambda kv: order.get(kv[0], len(order)))), "tfs": tfs}
