"""Evening review pipeline (22:00 KST).

    code builds packet -> ops auditor, performance analyst, P&L reviewer,
    what-if analyst -> risk officer -> team lead -> code sends Telegram

Every answer is checked by code (roles.check_output) before the next role
sees it. A role that fails (timeout, bad JSON, no usable answer) is skipped
and named in the report; the rest still run. If the usage limit is hit, the
remaining calls are not attempted. The numbers in the Telegram report are
written by code from the packet, not by an agent.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Optional

from ..ledger import SCHEMA
from ..notify import INFO, WARN, Notifier
from .packets import slice_for
from .roles import EVENING_ROLES, Role, check_output, system_prompt
from .runner import AgentCallError, Runner, UsageLimitReached

INSTRUCTION = ("표준입력으로 받은 JSON 패킷만 근거로, 시스템 프롬프트의 역할과 출력 형식에 맞춰 "
               "JSON 객체 하나로 답하세요.")
TELEGRAM_LIMIT = 3900


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _input_for(role: Role, packet: dict, analysts: dict, risk: Optional[dict],
               failed: list) -> dict:
    given = slice_for(packet, role.inputs)
    given["role"] = role.rid
    if role.kind in ("risk", "lead"):
        given["analysts"] = analysts
        given["failed_roles"] = list(failed)
    if role.kind == "lead":
        given["risk"] = risk
    return given


def _call_role(role: Role, given: dict, runner: Runner, retries: int = 1):
    problems: list[str] = []
    last_text = ""
    for attempt in range(retries + 1):
        res = runner.call(role.model, system_prompt(role), INSTRUCTION, given)
        last_text = res.text
        clean, probs = check_output(role, res.data, given)
        problems = probs
        if clean is not None:
            return clean, problems, res.meta, attempt + 1
    raise AgentCallError(f"no usable answer after {retries + 1} tries: "
                         f"{'; '.join(problems)[:200]} | {last_text[:200]}")


class ReportStore:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

    def add(self, ts: int, pipeline: str, role: str, status: str, packet_sha: str, data) -> None:
        self.conn.execute("INSERT INTO agent_reports (ts, pipeline, role, status, packet_sha, data) "
                          "VALUES (?,?,?,?,?,?)",
                          (ts, pipeline, role, status, packet_sha,
                           json.dumps(data, ensure_ascii=False, default=str)))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def run_evening(packet: dict, runner: Runner, store: Optional[ReportStore] = None,
                notifier: Optional[Notifier] = None, now_ms: Optional[int] = None,
                roles=EVENING_ROLES) -> dict:
    now_ms = now_ms or int(time.time() * 1000)
    psha = _sha(packet)
    analysts: dict = {}
    risk: Optional[dict] = None
    lead: Optional[dict] = None
    failed: list[str] = []
    notes: dict[str, list[str]] = {}
    stopped = ""

    def save(rid, status, data):
        if store:
            store.add(now_ms, "evening", rid, status, psha, data)

    for role in roles:
        if stopped:
            failed.append(role.rid)
            save(role.rid, "not_run", {"reason": stopped})
            continue
        given = _input_for(role, packet, analysts, risk, failed)
        try:
            clean, problems, meta, tries = _call_role(role, given, runner)
        except UsageLimitReached as exc:
            stopped = f"usage limit: {exc}"
            failed.append(role.rid)
            save(role.rid, "usage_limit", {"error": str(exc)})
            continue
        except AgentCallError as exc:
            failed.append(role.rid)
            save(role.rid, "failed", {"error": str(exc)})
            continue
        notes[role.rid] = problems
        save(role.rid, "ok", {"output": clean, "dropped": problems, "meta": meta, "tries": tries})
        if role.kind == "analyst":
            analysts[role.rid] = clean
        elif role.kind == "risk":
            risk = clean
        else:
            lead = clean

    report = {"analysts": analysts, "risk": risk, "lead": lead, "failed": failed,
              "dropped_claims": {k: v for k, v in notes.items() if v}, "stopped": stopped,
              "packet_sha": psha}
    report["telegram"] = compose_telegram(packet, report)
    if notifier:
        notifier.send(WARN if (failed or (risk and risk["risk_level"] != "normal")) else INFO,
                      report["telegram"])
    save("pipeline", "done", {"failed": failed, "stopped": stopped})
    return report


def _pct(x) -> str:
    return "-" if x is None else f"{x:+.1%}"


def compose_telegram(packet: dict, report: dict) -> str:
    meta = packet["meta"]
    L = [f"📋 오늘의 점검 ({meta['generated_kst']})", ""]
    lead = report.get("lead")
    if lead:
        L += [f"{i + 1}. {s}" for i, s in enumerate(lead["summary"])]
    else:
        L.append("팀장 요약 없음 (실패). 아래 숫자는 코드가 직접 계산한 값입니다.")
    L += ["", "[숫자: 코드 계산]"]
    for book, b in packet["books"].items():
        td, cu, eq = b.get("today") or {}, b.get("cumulative") or {}, b.get("equity") or {}
        name = "두 분 규칙" if book == "owner" else ("권고 규칙" if book == "recommended" else book)
        line = f"- {name}: 오늘 {td.get('trades', 0)}건"
        if td.get("trades"):
            line += f", 손익 {td['net_pnl']:+.2f} ({_pct(td.get('net_return'))}), 승률 {td['win_rate']:.0%}"
            if td.get("liquidations"):
                line += f", 강제청산 {td['liquidations']}"
        if eq.get("available"):
            line += f" | 잔고 {eq['equity']:.2f}, 낙폭 {eq['drawdown']:.1%} (최대 {eq['max_drawdown']:.1%})"
        line += f" | 누적 {cu.get('trades', 0)}건"
        L.append(line)
    ops = packet.get("ops", {})
    missing = {s: v["missing"] for s, v in (ops.get("bars_1m") or {}).items() if v["missing"]}
    if missing:
        L.append(f"- 1분봉 누락: {missing}")
    al = (ops.get("alerts") or {}).get("by_level") or {}
    if al.get("WARN") or al.get("CRITICAL"):
        L.append(f"- 알림: 경고 {al.get('WARN', 0)}, 치명 {al.get('CRITICAL', 0)}")
    risk = report.get("risk")
    if risk:
        lvl = {"normal": "정상", "caution": "주의", "danger": "위험"}[risk["risk_level"]]
        L += ["", f"[리스크: {lvl}] {risk['headline']}"]
        for a in risk["actions"]:
            if a.get("action") != "keep":
                L.append(f"- 권고 {a['action']} {a.get('target', '')}: {a.get('reason', '')}")
    if lead:
        if lead["human_actions"]:
            L += ["", "[사람이 할 일]"] + [f"- {x}" for x in lead["human_actions"]]
        if lead["glossary"]:
            L += ["", "[용어]"] + [f"- {g['term']}: {g['meaning']}" for g in lead["glossary"][:3]]
    tail = []
    if report["failed"]:
        tail.append(f"실패/미실행 역할: {', '.join(report['failed'])}")
    if report.get("stopped"):
        tail.append("사용량 한도로 중단됨")
    n_drop = sum(len(v) for v in report.get("dropped_claims", {}).values())
    if n_drop:
        tail.append(f"근거 검사에서 버린 주장 {n_drop}개")
    if tail:
        L += ["", "⚠️ " + " / ".join(tail)]
    text = "\n".join(L)
    return text if len(text) <= TELEGRAM_LIMIT else text[:TELEGRAM_LIMIT - 20] + "\n…(잘림)"
