"""에이전트 답을 코드가 검사한다 (다른 세션 paperbot/agents/roles.py 의 근거 검사를 옮김).

- 형식: 필요한 키와 타입
- 근거: 주장마다 evidence 로 단 패킷 경로가 그 역할이 받은 입력에 모두 있어야 한다. 없으면 그 주장을 버린다
- 권한: 리스크 책임자는 유지·축소·중지만(확대 불가), 허용 방향은 전략가보다 넓힐 수 없다,
  검증관·승인관은 코드 관문 탈락을 뒤집을 수 없다
"""
from __future__ import annotations

from typing import Any, Optional

RISK_ACTIONS = {"keep", "reduce", "pause_strategy", "pause_all"}
DIRS = {"long", "short", "both", "none"}
ALLOWS = {"long": {"long"}, "short": {"short"}, "both": {"long", "short"}, "none": set()}


def resolve(data: Any, path: str) -> tuple[bool, Any]:
    """점으로 이은 경로를 따라간다. 키에 점이 들어 있을 수 있어 가장 긴 키부터 맞춘다. '*' 는 쓰지 않는다."""
    parts = [p for p in str(path).strip().split(".") if p != ""]

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

    return walk(data, 0) if parts else (False, None)


def _evidence(items, given: dict, where: str, problems: list, need: bool = True) -> list:
    kept = []
    for i, it in enumerate(items or []):
        if not isinstance(it, dict):
            problems.append(f"{where}[{i}] 형식 오류")
            continue
        ev = it.get("evidence") or []
        if isinstance(ev, str):
            ev = [ev]
        if need and not ev:
            problems.append(f"{where}[{i}] 근거 없음: {str(it.get('claim') or it.get('change') or it.get('reason') or '')[:60]}")
            continue
        bad = [p for p in ev if not isinstance(p, str) or not resolve(given, p)[0]]
        if bad:
            problems.append(f"{where}[{i}] 입력에 없는 경로 인용: {bad[:2]}")
            continue
        kept.append({**it, "evidence": ev})
    return kept


def _strs(x) -> list[str]:
    return [s for s in (x or []) if isinstance(s, str)]


def check(kind: str, out: Any, given: dict) -> tuple[Optional[dict], list[str]]:
    """(정리된 답 또는 None, 문제 목록)."""
    problems: list[str] = []
    if not isinstance(out, dict):
        return None, ["JSON 객체가 아님"]
    msg = out.get("message") if isinstance(out.get("message"), str) else ""
    if kind == "lead":
        summary = _strs(out.get("summary"))
        if not summary:
            return None, ["summary 없음"]
        return {"message": msg or summary[0], "summary": summary[:3], "human_actions": _strs(out.get("human_actions")),
                "glossary": [g for g in out.get("glossary") or [] if isinstance(g, dict) and "term" in g and "meaning" in g][:4],
                "watch_next": _strs(out.get("watch_next"))}, problems
    head = out.get("headline") if isinstance(out.get("headline"), str) else ""
    if not head:
        problems.append("headline 없음")
    clean: dict = {"message": msg or head, "headline": head, "data_gaps": _strs(out.get("data_gaps")),
                   "questions_for_humans": _strs(out.get("questions_for_humans")),
                   "findings": _evidence(out.get("findings"), given, "findings", problems)}
    for f in clean["findings"]:
        if f.get("kind") not in ("fact", "hypothesis"):
            f["kind"] = "hypothesis"
        if f.get("severity") not in ("info", "warn", "critical"):
            f["severity"] = "info"
    if kind == "analyst":
        clean["proposals"] = _evidence(out.get("proposals"), given, "proposals", problems)
        calls = []
        for c in _evidence(out.get("calls"), given, "calls", problems):
            if c.get("bias") in ("long", "short", "neutral") and isinstance(c.get("symbol"), str):
                calls.append(c)
        clean["calls"] = calls
    elif kind == "strategist":
        rows = []
        for a in _evidence(out.get("allowed"), given, "allowed", problems):
            if a.get("direction") not in DIRS or not isinstance(a.get("symbol"), str):
                problems.append(f"allowed 방향 오류: {a.get('direction')!r}")
                continue
            rows.append(a)
        clean["allowed"] = rows
        clean["focus"] = _strs(out.get("focus"))
    elif kind == "risk":
        lvl = out.get("risk_level")
        if lvl not in ("normal", "caution", "danger"):
            problems.append(f"risk_level 오류: {lvl!r} → caution")
            lvl = "caution"
        clean["risk_level"] = lvl
        base = {a["symbol"]: a["direction"] for a in (given.get("strategist") or {}).get("allowed", [])}
        decs = []
        for d in _evidence(out.get("decisions"), given, "decisions", problems):
            sym, dr = d.get("symbol"), d.get("direction")
            if dr not in DIRS:
                problems.append(f"decisions 방향 오류: {dr!r}")
                continue
            if sym in base and not ALLOWS[dr] <= ALLOWS[base[sym]]:
                problems.append(f"확대 거부: {sym} {base[sym]} → {dr} (리스크는 좁히기만 가능)")
                continue
            decs.append(d)
        clean["decisions"] = decs
        acts = []
        for a in _evidence(out.get("actions"), given, "actions", problems):
            if a.get("action") not in RISK_ACTIONS:
                problems.append(f"허용되지 않은 조치(확대 등): {a.get('action')!r}")
                continue
            acts.append(a)
        clean["actions"] = acts
    elif kind == "validator":
        cands = {c["id"]: c for c in given.get("candidates") or []}
        vs = []
        for v in _evidence(out.get("verdicts"), given, "verdicts", problems):
            c = cands.get(v.get("candidate"))
            if not c or v.get("verdict") not in ("pass", "fail", "need_more_data"):
                problems.append(f"verdicts 후보·판정 오류: {v.get('candidate')!r}")
                continue
            if v["verdict"] == "pass" and not (c.get("gate") or {}).get("passed"):
                problems.append(f"코드 관문 탈락 후보를 통과시킬 수 없음: {c['id']} → fail")
                v = {**v, "verdict": "fail"}
            vs.append(v)
        clean["verdicts"] = vs
    elif kind == "approver":
        cands = {c["id"]: c for c in given.get("candidates") or []}
        verd = {v["candidate"]: v["verdict"] for v in (given.get("verdicts") or [])}
        aps = []
        for a in _evidence(out.get("approvals"), given, "approvals", problems):
            c = cands.get(a.get("candidate"))
            if not c or a.get("decision") not in ("approve", "reject"):
                problems.append(f"approvals 오류: {a.get('candidate')!r}")
                continue
            if a["decision"] == "approve" and (not (c.get("gate") or {}).get("passed") or verd.get(c["id"]) != "pass"):
                problems.append(f"관문·검증관을 통과하지 못한 후보는 승인 불가: {c['id']} → reject")
                a = {**a, "decision": "reject"}
            aps.append(a)
        clean["approvals"] = aps
    elif kind == "researcher":
        hs = []
        for h in _evidence(out.get("hypotheses"), given, "hypotheses", problems, need=False):
            if isinstance(h.get("rule"), str) and h["rule"].strip():
                hs.append(h)
        clean["hypotheses"] = hs[:3]
    elif kind == "cio":
        ws = []
        bots = given.get("bots") or {}
        for w in _evidence(out.get("weights"), given, "weights", problems):
            if w.get("bot") not in bots or not isinstance(w.get("weight_pct"), (int, float)):
                problems.append(f"weights 봇 이름 오류: {w.get('bot')!r}")
                continue
            ws.append({**w, "weight_pct": max(0.0, float(w["weight_pct"]))})
        tot = sum(w["weight_pct"] for w in ws)
        if tot > 0:
            for w in ws:
                w["weight_pct"] = round(w["weight_pct"] / tot * 100, 1)
        clean["weights"] = ws
    elif kind == "learning":
        clean["memos"] = [m for m in _evidence(out.get("memos"), given, "memos", problems) if isinstance(m.get("text"), str)]
        clean["promote"] = [p for p in out.get("promote") or [] if isinstance(p, dict) and p.get("memo_id")]
        clean["expire"] = [p for p in out.get("expire") or [] if isinstance(p, dict) and p.get("lesson_id")]
    return clean, problems
