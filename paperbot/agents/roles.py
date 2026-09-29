"""Agent roles for the evening review, their inputs and output checks.

Each role reads a slice of the evening packet (plus earlier roles' checked
outputs) and must answer with one JSON object. Code checks every answer:
- the shape (required keys and types)
- evidence: each claim lists packet paths; a claim whose paths do not all
  exist in what the role was given is marked unsupported and dropped
- permissions: the risk officer may keep, reduce or pause; never increase
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

PROMPT_DIR = os.path.join(os.path.dirname(__file__), "prompts")

ANALYST_SCHEMA = """{
  "headline": "한 문장 요약",
  "findings": [
    {"claim": "사실 한 가지 (숫자 포함)", "kind": "fact | hypothesis",
     "severity": "info | warn | critical", "evidence": ["packet.path", "..."]}
  ],
  "proposals": [
    {"change": "바꿔 볼 것", "reason": "왜", "evidence": ["packet.path"],
     "how_to_confirm": "어떤 데이터로, 몇 건 이후에 확인할지"}
  ],
  "data_gaps": ["판단에 모자란 데이터"],
  "questions_for_humans": ["사람이 답해야 할 질문"]
}"""

RISK_SCHEMA = """{
  "headline": "한 문장 요약",
  "risk_level": "normal | caution | danger",
  "findings": [ ...분석가와 같은 형식... ],
  "actions": [
    {"action": "keep | reduce | pause_strategy | pause_all", "target": "대상",
     "reason": "왜", "evidence": ["packet.path"]}
  ],
  "data_gaps": [],
  "questions_for_humans": []
}"""

LEAD_SCHEMA = """{
  "summary": ["첫째 줄", "둘째 줄", "셋째 줄"],
  "human_actions": ["사람이 오늘/내일 할 일 (없으면 빈 목록)"],
  "glossary": [{"term": "보고에 나온 어려운 말", "meaning": "쉬운 설명"}],
  "watch_next": ["다음 점검 때 볼 것"]
}"""


@dataclass(frozen=True)
class Role:
    rid: str
    name_ko: str
    model: str
    prompt: str  # file name in prompts/
    inputs: tuple[str, ...]  # packet paths, see packets.slice_for
    schema: str
    kind: str  # analyst / risk / lead


EVENING_ROLES: tuple[Role, ...] = (
    Role("ops_auditor", "운영 감사관", "sonnet", "ops_auditor.md",
         ("ops", "books.*.whatif", "books.*.equity"), ANALYST_SCHEMA, "analyst"),
    Role("performance_analyst", "성과 분석가", "sonnet", "performance_analyst.md",
         ("books.*.today", "books.*.cumulative", "books.*.equity", "books.*.sessions"),
         ANALYST_SCHEMA, "analyst"),
    Role("pnl_reviewer", "손익 복기 분석가", "sonnet", "pnl_reviewer.md",
         ("books.*.trades_today", "books.*.causes_cumulative", "books.*.entry_tag_table",
          "books.*.today"), ANALYST_SCHEMA, "analyst"),
    Role("whatif_analyst", "가정 분석가", "sonnet", "whatif_analyst.md",
         ("books.*.whatif", "books.*.cumulative"), ANALYST_SCHEMA, "analyst"),
    Role("risk_officer", "리스크 책임자", "opus", "risk_officer.md",
         ("books.*.equity", "books.*.today", "books.*.cumulative", "books.*.trades_today"),
         RISK_SCHEMA, "risk"),
    Role("team_lead", "팀장", "sonnet", "team_lead.md",
         ("books.*.today", "books.*.equity"), LEAD_SCHEMA, "lead"),
)

RISK_ACTIONS = {"keep", "reduce", "pause_strategy", "pause_all"}


def system_prompt(role: Role) -> str:
    with open(os.path.join(PROMPT_DIR, "common.md"), encoding="utf-8") as fh:
        common = fh.read()
    with open(os.path.join(PROMPT_DIR, role.prompt), encoding="utf-8") as fh:
        own = fh.read()
    return (f"{common}\n\n# 당신의 역할: {role.name_ko}\n\n{own}\n\n"
            f"# 출력 형식 (JSON 객체 하나만, 다른 글 없이)\n{role.schema}\n")


# ------------------------------------------------------------ checks
def resolve(data: Any, path: str) -> tuple[bool, Any]:
    """Follow a dotted path. Dict keys may themselves contain dots
    (e.g. policy "TP_1.5R"); the longest matching key wins."""
    parts = path.split(".")

    def walk(cur: Any, i: int) -> tuple[bool, Any]:
        if i == len(parts):
            return True, cur
        if isinstance(cur, dict):
            for j in range(len(parts), i, -1):
                key = ".".join(parts[i:j])
                if key in cur:
                    ok, val = walk(cur[key], j)
                    if ok:
                        return True, val
            return False, None
        if isinstance(cur, list):
            p = parts[i]
            if p.lstrip("-").isdigit() and -len(cur) <= int(p) < len(cur):
                return walk(cur[int(p)], i + 1)
        return False, None

    return walk(data, 0)


def _check_evidence(items: list, given: dict, where: str, problems: list) -> list:
    kept = []
    for i, it in enumerate(items or []):
        if not isinstance(it, dict):
            problems.append(f"{where}[{i}] is not an object")
            continue
        ev = it.get("evidence") or []
        if not isinstance(ev, list) or not ev:
            problems.append(f"{where}[{i}] has no evidence: {str(it.get('claim') or it.get('change') or it)[:80]}")
            continue
        bad = [p for p in ev if not isinstance(p, str) or not resolve(given, p)[0]]
        if bad:
            problems.append(f"{where}[{i}] cites paths not in its packet: {bad[:3]}")
            continue
        kept.append(it)
    return kept


def check_output(role: Role, out: Any, given: dict) -> tuple[Optional[dict], list[str]]:
    """Returns (cleaned output or None if unusable, list of problems)."""
    problems: list[str] = []
    if not isinstance(out, dict):
        return None, ["answer is not a JSON object"]
    if role.kind == "lead":
        summary = out.get("summary")
        if not isinstance(summary, list) or not summary or not all(isinstance(x, str) for x in summary):
            return None, ["summary missing"]
        clean = {
            "summary": summary[:3],
            "human_actions": [x for x in out.get("human_actions") or [] if isinstance(x, str)],
            "glossary": [g for g in out.get("glossary") or []
                         if isinstance(g, dict) and "term" in g and "meaning" in g],
            "watch_next": [x for x in out.get("watch_next") or [] if isinstance(x, str)],
        }
        return clean, problems
    if not isinstance(out.get("headline"), str):
        problems.append("headline missing")
    clean = {"headline": out.get("headline") or "",
             "findings": _check_evidence(out.get("findings"), given, "findings", problems),
             "data_gaps": [x for x in out.get("data_gaps") or [] if isinstance(x, str)],
             "questions_for_humans": [x for x in out.get("questions_for_humans") or []
                                      if isinstance(x, str)]}
    if role.kind == "analyst":
        clean["proposals"] = _check_evidence(out.get("proposals"), given, "proposals", problems)
    if role.kind == "risk":
        level = out.get("risk_level")
        if level not in ("normal", "caution", "danger"):
            problems.append(f"risk_level invalid: {level!r}")
            level = "caution"
        clean["risk_level"] = level
        acts = []
        for a in _check_evidence(out.get("actions"), given, "actions", problems):
            if a.get("action") not in RISK_ACTIONS:
                problems.append(f"action not allowed (risk may only keep/reduce/pause): {a.get('action')!r}")
                continue
            acts.append(a)
        clean["actions"] = acts
    return clean, problems
