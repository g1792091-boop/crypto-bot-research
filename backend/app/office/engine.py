"""AI 사무실 엔진 — 4개 팀 24명이 24시간 스스로 일한다 (다른 연구 세션의 AI 팀 사무실을 코인 전용으로 옮김).

스케줄러(백그라운드 스레드)
- 자동 회의: 정해진 간격(기본 30분)마다 안건을 돌아가며 연다. 하루 12번 한도. 급변동(BTC ±4%, ETH ±5%, SOL ±6%) 이면 긴급 회의.
- 주기 업무: 기본 3분마다 한 가지 일 (매매법 연구 · 방향 예측 · 머신러닝 · SNS · 미디어 · 수급 점검 · 회고 · 과제 …). 하루 AI 호출 한도(기본 600).
- 수다: 3분마다 2~3명이 방금 본 것으로 잡담 (하루 80번). '회의 한번 하죠' 가 나오면 진짜 회의.
- 관찰: 코드만으로 시세·호가·고래·뉴스를 보고 말풍선에 띄운다 (AI 호출 없음).
- 매시 정각: 민재(CSO)가 팀별 성과 발표.
회의는 코드가 순서를 정한다: 담당 분석가 → (투자·실행 판단이면) 전략 총괄 → 반론 검토관 → 리스크 책임자 → 정리(민재).
AI 는 말과 도구 호출만 한다. 백테스트 통과·ML 우위·예측 채점은 코드 판정이고 AI 가 뒤집지 못한다. 주문 기능은 없다(가상 체결만).
"""
from __future__ import annotations

import json
import math
import random
import re
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from .. import config, llm
from ..data import market
from ..llm import LLMUnavailable
from . import flow, media, org, quantlab, roster, tools as T  # noqa: F401  (org: 확장 조직을 roster 에 붙인다)

_paper = None
_lock = threading.RLock()
LOG: list[dict] = []
_next = {"id": 1}
DEFAULT_CFG = {"enabled": True, "auto": True, "every": 30, "daily_max": 12, "chat": True, "chat_every": 3, "chat_max": 80,
               "cycle": True, "cycle_min": 3, "call_max": 1500, "files": True, "alert": True,
               "team_cycle": True, "team_cycle_min": 4, "team_meet_max": 30,
               "models": {}}          # 직원·팀별 AI 모델: {"team:팀id": "nvidia#2:auto", "직원id": "gemini:auto"} — 비우면 기본 배정
CFG: dict = dict(DEFAULT_CFG)
ST: dict = {}
RT = {"queue": deque(), "meeting": None, "agents": {}, "huddle": None, "presenting": None, "job": None, "paused_until": 0.0,
      "limits": deque(maxlen=10), "seen": {}, "last_work_post": {}, "stop_meeting": False, "visible": 0.0, "started": time.time(),
      "events": deque(maxlen=200)}
JOB_KO = {"research": "매매법 연구", "forecast": "방향 예측 토론", "ml": "머신러닝 실험", "sns": "SNS 여론 확인", "media": "유튜브·인스타 조사",
          "paper": "시그널 추적 점검", "flowscan": "선물 수급 점검", "alt": "알트 순환 점검", "coinnews": "코인 뉴스 해설", "pm": "포트폴리오 점검",
          "scen": "시나리오 대비", "comp": "컴플라이언스 점검", "datacheck": "데이터 품질 점검", "viz": "시각화 자료", "files": "파일 작업",
          "chat": "동료 수다", "task": "성장 과제 수행", "retro": "팀 회고"}
JOB_TEAM = {"research": "quant", "ml": "quant", "paper": "quant", "forecast": "strat", "pm": "strat", "scen": "strat", "comp": "strat",
            "sns": "data", "media": "data", "datacheck": "data", "viz": "data", "files": "data", "flowscan": "coin", "alt": "coin",
            "coinnews": "coin", "chat": "coin", "task": "strat", "retro": "strat"}
JOBS = ["research", "forecast", "sns", "ml", "flowscan", "task", "media", "research", "paper", "coinnews", "chat", "files", "retro",
        "research", "alt", "forecast", "ml", "pm", "media", "scen", "datacheck", "viz", "comp", "task"]
MARKETS = [("BTCUSDT", "4h", "비트코인 선물"), ("ETHUSDT", "1h", "이더리움 선물"), ("SOLUSDT", "4h", "솔라나 선물"), ("BTCUSDT", "1d", "비트코인 선물 일봉"),
           ("ETHUSDT", "4h", "이더리움 선물 4시간"), ("XRPUSDT", "4h", "리플 선물"), ("BNBUSDT", "4h", "BNB 선물"), ("DOGEUSDT", "1h", "도지 선물")]
ML_MARKETS = [("BTCUSDT", "1h"), ("ETHUSDT", "1h"), ("SOLUSDT", "1h"), ("BTCUSDT", "4h"), ("ETHUSDT", "4h")]
ML_MODELS = ["mlp", "logreg", "gbs", "dnn", "cnn"]
FC_ASSETS = [("비트코인", "BTCUSDT"), ("이더리움", "ETHUSDT"), ("솔라나", "SOLUSDT"), ("리플", "XRPUSDT")]
MEDIA_Q = ["비트코인 전망", "이더리움 전망", "알트코인 시즌", "코인 선물 청산", "솔라나 전망", "비트코인 ETF", "코인 규제", "밈코인"]
WATCH_EMERGENCY = [("BTCUSDT", "비트코인", 4), ("ETHUSDT", "이더리움", 5), ("SOLUSDT", "솔라나", 6)]
MAX_BOTS = 8


def bind(paper_manager) -> None:
    global _paper
    _paper = paper_manager


# ------------------------------------------------------------------ 저장
def _dir() -> Path:
    d = config.STATE_DIR / "office"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _default_state() -> dict:
    return {"usage": {"day": _today(), "meetings": 0, "calls": 0, "auto": 0, "chats": 0, "cap_noted": False},
            "last_auto": 0.0, "agenda_i": 0, "bands": {}, "last_chat": 0.0, "last_cycle": 0.0, "job_i": 0, "research": [],
            "notes": {t["id"]: [] for t in roster.TEAMS}, "backlog": [], "retro_i": 0, "last_report": 0.0, "forecasts": [],
            "ml_i": 0, "media_i": 0, "sns_i": 0, "research_n": 0, "bots": {}, "last_emergency": 0.0, "flow_i": 0,
            "first_start": time.time(), "last_score": 0.0}


def load() -> None:
    global ST, CFG
    try:
        d = json.loads((_dir() / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    ST = {**_default_state(), **(d.get("state") or {})}
    CFG = {**DEFAULT_CFG, **(d.get("cfg") or {})}
    try:
        rows = json.loads((_dir() / "log.json").read_text(encoding="utf-8"))
        LOG[:] = rows
        _next["id"] = max((e["id"] for e in rows), default=0) + 1
    except (OSError, ValueError):
        pass


_save_at = {"t": 0.0}


def save(force: bool = False) -> None:
    if not force and time.time() - _save_at["t"] < 2:
        return
    _save_at["t"] = time.time()
    with _lock:
        try:
            (_dir() / "state.json").write_text(json.dumps({"state": ST, "cfg": CFG}, ensure_ascii=False, default=str), encoding="utf-8")
            (_dir() / "log.json").write_text(json.dumps(LOG, ensure_ascii=False, default=str), encoding="utf-8")
        except OSError:
            pass


def _trim():
    work = [e for e in LOG if e["kind"] == "work"]
    other = [e for e in LOG if e["kind"] != "work"]
    if len(other) > 800 or len(work) > 300:
        keep = {e["id"] for e in other[-600:]} | {e["id"] for e in work[-200:]}
        LOG[:] = [e for e in LOG if e["id"] in keep]


def post(ch: str, kind: str, **kw) -> dict:
    with _lock:
        e = {"id": _next["id"], "t": time.time(), "ch": ch, "kind": kind, **kw}
        _next["id"] += 1
        LOG.append(e)
        _trim()
    save()
    return e


def update(e: dict, **kw) -> None:
    with _lock:
        e.update(kw)
        e["rev"] = e.get("rev", 0) + 1
        e["u"] = _next["id"]
        _next["id"] += 1
    save()


def event(kind: str, **kw) -> None:
    RT["events"].append({"t": time.time(), "kind": kind, **kw})


def bubble(aid: str, text: str, sec: float = 7.0, busy: bool = False) -> None:
    RT["agents"][aid] = {"bubble": text[:170], "until": time.time() + sec, "busy": busy}


def _reset_usage():
    if ST["usage"].get("day") != _today():
        ST["usage"] = {"day": _today(), "meetings": 0, "calls": 0, "auto": 0, "chats": 0, "cap_noted": False}


def note(team: str, text: str) -> None:
    n = ST["notes"].setdefault(team, [])
    text = text.strip()[:240]
    if text and text not in n:
        n.append(text)
        del n[:-40]


def notes_text(team: str) -> str:
    n = ST["notes"].get(team) or []
    return f"- 우리 팀이 지금까지 배운 것(반영할 것): {' / '.join(n[-6:])}\n" if n else ""


# ------------------------------------------------------------------ AI 호출
def ai_ok() -> bool:
    return config.llm_enabled() and CFG["enabled"]


def paused() -> bool:
    return time.time() < RT["paused_until"]


def _limit_hit(err: str) -> bool:
    if re.search(r"429|quota|rate.?limit|한도|too many", err, re.I):
        RT["limits"].append(time.time())
        recent = [t for t in RT["limits"] if time.time() - t < 120]
        if len(recent) >= 3 and not paused():
            RT["paused_until"] = time.time() + 180
            post("hq", "system", text="무료 AI 한도에 걸렸습니다 · 3분 쉬었다가 다시 일합니다. 질문은 계속 받습니다.")
        return True
    return False


def _ai(system: str, user: str, aid: str, max_tokens: int = 1400) -> tuple[str | None, str | None, str | None]:
    """(텍스트, 모델, 오류). 하루 호출 한도·쉬는 중이면 호출하지 않는다."""
    _reset_usage()
    if not ai_ok():
        return None, None, "AI 키가 없습니다"
    if ST["usage"]["calls"] >= CFG["call_max"]:
        return None, None, "오늘 AI 호출 한도"
    ST["usage"]["calls"] += 1
    a = roster.BY_ID.get(aid) or {}
    tier = "opus" if a.get("role") == "reason" else "sonnet"
    feature = "team_heavy" if tier == "opus" else "team_light"
    from .. import ai_routes
    errs = []
    for r in assigned_routes(aid):                       # 이 직원·팀에 배정한 모델(키)부터
        if not ai_routes.available(r):
            continue
        try:
            out, route = llm._run("text", system, user, max_tokens, None, None, feature, None, tier, r)
            return out, route, None
        except Exception as e:  # noqa: BLE001
            errs.append(f"{r}: {str(e)[:120]}")
            _limit_hit(str(e))
    try:
        out, route = llm._run("text", system, user, max_tokens, None, None, feature, None, tier)
        return out, route, None
    except (LLMUnavailable, Exception) as e:  # noqa: BLE001
        msg = " / ".join(errs + [str(e)])
        _limit_hit(msg)
        return None, None, msg[:300]


def assigned_routes(aid: str) -> list[str]:
    a = roster.BY_ID.get(aid) or {}
    m = CFG.get("models") or {}
    return [r for r in (m.get(aid), m.get(f"team:{a.get('team')}")) if r]


def assign_keys_evenly() -> dict:
    """넣어 둔 키들을 팀마다 골고루 나눠 배정 (무료 키 한도를 나눠 쓰게)."""
    from .. import keyring
    pool = []
    for prov in ("nvidia", "gemini", "claude"):
        for n in keyring.slots(prov):
            model = "auto" if prov != "claude" else config.CLAUDE_MODEL
            pool.append(f"{prov}{'' if n == 1 else '#' + str(n)}:{model}")
    if not pool:
        raise ValueError("AI 키가 없습니다. 먼저 키를 넣어 주세요.")
    m = dict(CFG.get("models") or {})
    for i, t in enumerate(roster.TEAMS):
        m[f"team:{t['id']}"] = pool[i % len(pool)]
    CFG["models"] = m
    save(True)
    return m


# ------------------------------------------------------------------ 한국어 정리 · 속마음
PLAN_RE = re.compile(r"^\s*(💭\s*)?(we need|we should|we must|we can|we have|need |must |let'?s|let me|the user|user (wants|asks|requested)|i need|i should|i will|i'll|ok(ay)?[,. ]|so (we|i)|now (we|i)|also[, ]|maybe |but |given |thus|therefore|first line|then |could |however|probably|done\.|alright)", re.I)


def _englishy(t: str) -> bool:
    lat = len(re.findall(r"[A-Za-z]", t))
    han = len(re.findall(r"[가-힣]", t))
    return lat > 25 and han < lat * 0.15


def ko_only(text: str) -> str:
    text = re.sub(r"(?is)<think>.*?</think>", "", text or "")
    text = re.sub(r"(?is)<tool[^>]*>.*?</tool>", "", text)
    parts = re.split(r"(```.*?```)", text, flags=re.S)
    out, kept = [], False
    for p in parts:
        if p.startswith("```"):
            out.append(p)
            kept = True
            continue
        paras = [x for x in re.split(r"\n{2,}", p)]
        for para in paras:
            if _englishy(para) and (not kept or PLAN_RE.search(para)):
                continue
            para = "\n".join(l for l in para.split("\n") if not (PLAN_RE.search(l) and not re.search(r"[가-힣]", l)))   # 영어 계획 줄
            if para.strip():
                out.append(para)
                kept = True
    return "\n\n".join(x.strip("\n") for x in out).strip()


def split_think(text: str) -> tuple[str, str]:
    lines = text.strip().split("\n")
    think = ""
    if lines and lines[0].strip().startswith("💭"):
        t = re.sub(r"\s+", " ", lines[0].strip()[1:].strip())
        if re.search(r"[가-힣]", t) and not _englishy(t):
            t = re.split(r"(?<=[.!?。])\s", t)[0]
            think = t[:118] + ("…" if len(t) > 118 else "")
        lines = lines[1:]
    body = "\n".join(l for l in lines if not l.strip().startswith("💭")).strip()
    return think, body


# ------------------------------------------------------------------ 페르소나
def persona(aid: str, extra: str = "") -> str:
    a = roster.BY_ID[aid]
    team = roster.TEAM_BY[a["team"]]
    return (f"너는 세계적인 기업 수준의 GH Quant AI 사무실 {team['name']}의 '{a['name']}'({a['title']})다. 역할: {a['duty']}\n{notes_text(a['team'])}"
            "반드시 한국어로만 쓰고, 영어 생각이나 답 계획은 쓰지 않는다. 이번 일에서는 도구를 부를 수 없으니 주어진 자료로만 말한다. "
            "첫 줄은 '💭 '로 시작하는 한 문장 속마음(무엇을 보고 어떻게 판단하는지)이다. 그다음 동료에게 말하듯 자연스러운 한국어로 말한다. "
            f"데이터에 없는 숫자는 지어내지 않는다. 이 앱은 분석 전용이라 주문을 하지 않는다. {extra}")


def solo(aid: str, room: str, extra: str, user: str, max_tokens: int = 1200, system: str | None = None, **card) -> dict | None:
    """도구 없이 한 사람이 말한다 (대부분의 주기 업무). system 을 주면 페르소나 대신 그것을 쓴다."""
    a = roster.BY_ID[aid]
    bubble(aid, "💭 생각 중…", 60, True)
    e = post(room, "agent", agent=aid, text="", think="", live=True, steps=[], **card)
    sysp = system or persona(aid, extra)
    text, model, err = _ai(sysp, user, aid, max_tokens)
    ok = lambda t: bool(t) and (bool(re.search(r"[가-힣]", ko_only(t))) or "```json" in t)     # 한국어 답이나 JSON 블록이 있으면 받는다
    if text and not ok(text):
        text2, model2, err2 = _ai(sysp + "\n반드시 한국어로 답한다.", user, aid, max_tokens)
        text, model = (text2, model2) if ok(text2) else (None, model)
        err = err or "한국어 답을 내지 못함"
    if not text:
        update(e, live=False, text=f"({a['name']}: {'무료 AI 한도에 걸려 이번에는 쉬었습니다 · 잠시 뒤 다시 합니다' if err and _limit_hit(err) else '연결된 모델들이 이번에는 답하지 못했습니다'})",
               error=(err or "")[:160])
        bubble(aid, "😮‍💨 이번엔 쉬어요", 5)
        return None
    think, body = split_think(ko_only(text))
    update(e, live=False, text=body, think=think, model=model)
    bubble(aid, "🗣 " + (body.split("\n")[0][:110] if body else "…"), 7)
    return {**e, "raw": text}


# ------------------------------------------------------------------ 회의
def _speaker_order(text: str, room: str, fixed: list[str] | None, user: bool) -> list[str]:
    lead: list[str] = []
    if fixed:
        lead = list(fixed)
    else:
        lead += roster.find_mentions(text)
        if re.search(r"매매법|전략 ?(개발|만들)|백테스트|보조지표|지표 ?(조합|전부)|퀀트", text):
            lead += ["qa", "qb"]
        if re.search(r"머신러닝|딥러닝|ML|신경망|예측 모델", text):
            lead += ["ml"]
        if re.search(r"모의|가상 ?(계좌|매매|체결)|시그널 추적|포지션 현황", text):
            lead += ["trader"]
        if re.search(r"sns|SNS|레딧|트위터|스톡트윗|여론|커뮤니티|공포.?탐욕|심리|분위기|유튜브|인스타", text, re.I):
            lead += ["sns"]
        if re.search(r"고래|호가|청산|펀딩|미결제|롱숏", text):
            lead += ["deriv"]
        if re.search(r"알트|밈|섹터|순환", text):
            lead += ["alt"]
        if re.search(r"규제|법|컴플라이언스", text):
            lead += ["comp"]
        for sk, rx in roster.SKILL_RE.items():
            if rx.search(text) and roster.SKILL_AGENT.get(sk):
                lead.append(roster.SKILL_AGENT[sk])
        if room in roster.MEMBERS:
            mem = [m for m in roster.MEMBERS[room] if m not in ("devil", "risk")]
            inroom = [m for m in lead if m in mem]
            lead = inroom + [m for m in lead if m not in inroom]
            if not inroom:
                lead.insert(0, mem[0] if room != "strat" else "strat")
        if not lead:
            lead = [roster.TEAM_LEAD.get(room, "coin_fut")]
    lead = [x for x in dict.fromkeys(lead) if x in roster.BY_ID and x not in ("devil", "risk")][:3]
    order = list(lead)
    if any(x in order for x in ("qa", "qb", "cind")):
        order.append("val")
    if any(x in roster.MARKET for x in order) and roster.DECIDE.search(text):
        if "strat" not in order and roster.PLAN.search(text):
            order.append("strat")
        order += ["devil", "risk"]
    elif fixed:
        order.append("devil")
    if len(order) > 1:
        order.append(roster.CLOSER)
    if user and len(order) > 4:
        core = [x for x in order[:-1] if x not in ("devil", "risk", "val")][:2]
        order = core + (["risk"] if "risk" in order else []) + [roster.CLOSER]
    out = []
    for i, x in enumerate(order):                       # 정리 담당은 마지막에 한 번 더 말할 수 있다 (전략 초안 + 최종 정리)
        if x in out and not (i == len(order) - 1 and x == roster.CLOSER):
            continue
        out.append(x)
    return out


def _place(order: list[str], room: str) -> str:
    teams = {roster.BY_ID[x]["team"] for x in order}
    if len(teams) == 1:
        return next(iter(teams))
    if len(teams) == 2 and room in teams:
        return room
    return "meet"


def enqueue(name: str, room: str, topic: str, trigger: str = "auto", agents: list[str] | None = None, wait: bool = False) -> dict:
    order = _speaker_order(topic, room, agents, trigger == "user")
    m = {"id": f"m{int(time.time() * 1000)}{random.randint(0, 99)}", "name": name, "room": room, "topic": topic, "trigger": trigger,
         "order": order, "done": [], "t": time.time(), "place": _place(order, room), "turns": [], "ev": threading.Event()}
    with _lock:
        if trigger == "user":
            idx = next((i for i, x in enumerate(RT["queue"]) if x["trigger"] != "user"), len(RT["queue"]))
            RT["queue"].insert(idx, m)
            cur = RT["meeting"]
            if cur and cur["trigger"] != "user":
                post(room, "system", text=f"질문 먼저 답합니다 · '{cur['name']}' 회의는 잠시 멈췄다가 이어서 합니다")
                cur["preempt"] = True
            elif cur:
                post(room, "system", text="질문을 받았습니다 · 앞 질문 다음에 바로 답합니다")
        else:
            RT["queue"].append(m)
    if trigger in ("auto", "event"):
        ST["usage"]["auto"] += 1
    if wait:
        m["ev"].wait(timeout=900)
    return m


TOOL_RE = re.compile(r'<tool\s+name\s*=\s*"?([a-z_]+)"?\s*>(.*?)(?:</tool>|$)', re.S)


def _parse_args(s: str) -> dict:
    s = s.strip()
    s = re.sub(r"^```(?:json)?|```$", "", s).strip()
    try:
        return json.loads(s) if s else {}
    except ValueError:
        m = re.search(r"\{.*\}", s, re.S)
        try:
            return json.loads(m.group(0)) if m else {}
        except ValueError:
            return {}


def _turn(m: dict, aid: str, i: int) -> dict:
    a = roster.BY_ID[aid]
    team = roster.TEAM_BY[a["team"]]
    closer = i == len(m["order"]) - 1 and aid == roster.CLOSER and len(m["order"]) > 1
    prev = roster.BY_ID[m["turns"][-1]["agent"]] if m["turns"] else None
    mates = [f"@{x['name']}({x['title']})" for x in roster.AGENTS if x["id"] != aid and (x["team"] == a["team"] or x["lead"])]
    names = roster.tools_for(aid)
    skills = "\n".join(roster.SKILL_PROMPT[s] for s in a["skills"] if s in roster.SKILL_PROMPT)
    sysp = (f"[GH Quant AI 사무실 · 에이전트 팀 회의]\n너는 GH Quant AI 사무실 {team['name']}의 '{a['name']}'({a['title']})다. 지금 동료들과 자유롭게 토론하는 회의 중이다.\n"
            f"- 네 역할: {a['duty']}\n"
            "- 답의 첫 줄은 반드시 '💭 '로 시작하는 한 문장 속마음이다(무엇을 확인하고 어떻게 판단하려는지). 그다음 줄부터 말한다.\n"
            f"- {'앞사람(' + prev['name'] + ')의 말에 이름을 불러 반응하며 시작한다(동의·보충·반박). ' if prev else ''}같은 말은 반복하지 말고 네 전문 분야 관점을 더한다. "
            f"다른 전문가가 꼭 필요하면 @이름 으로 한 명만 부른다(동료: {', '.join(mates[:14])}).\n"
            "- 반드시 한국어로만 쓴다. 영어로 생각하거나 '어떻게 답할지' 계획을 쓰지 말고 바로 말한다.\n"
            "- 회사 동료와 대화하듯 자연스러운 한국어로 말한다. 숫자 나열이 아니라 해설로 말한다. 수치는 도구로 확인한 것만 쓰고 지어내지 않는다. 차트·뉴스를 봤다면 무엇을 봤는지 말한다.\n"
            f"{notes_text(a['team'])}"
            + ("- 너는 마지막 정리 담당이다. 사용자에게 주는 최종 답을 결론부터 짧고 쉽게 쓴다(5~8줄, 꼭 필요할 때만 표).\n" if closer
               else "- 3~5문장으로 짧게. 사용자에게 주는 최종 답은 마지막 정리 담당이 하니, 너는 네 판단과 근거 한두 개에 집중한다.\n")
            + "- 이 앱은 분석 전용이다. 주문을 내지 않으며 '사라/팔아라'고 단정하지 않는다. " + roster.RISK_LINE + "\n"
            + (f"\n[전문 분야]\n{skills}\n" if skills else "")
            + "\n[도구] 도구가 필요하면 그 차례에는 말 대신 한 줄로 <tool name=\"도구이름\">{JSON 인자}</tool> 만 쓰고 멈춘다. 결과를 받은 뒤 말한다. "
              "도구 결과는 사용자에게 보이지 않으므로 중요한 내용은 말로 해설한다. 도구 없이 답할 수 있으면 쓰지 않는다. 도구 결과를 지어내지 않는다.\n"
            + T.describe(names))
    user_head = ("사용자 질문" if m["trigger"] == "user" else "회의 안건") + f": {m['topic']}\n\n"
    if m["trigger"] == "user":
        user_head += status_text() + "\n\n"
    transcript = "\n\n".join(f"[{roster.BY_ID[t['agent']]['name']} · {roster.BY_ID[t['agent']]['title']}]\n{t['text'][:2500]}" for t in m["turns"])
    conv = user_head + (f"지금까지 회의 내용:\n{transcript}\n\n" if transcript else "") + f"이제 {a['name']}({a['title']}) 차례입니다."
    max_steps = 2 if closer or aid == "devil" else 3 if m["trigger"] == "user" else 5
    e = post(m["room"], "agent", agent=aid, text="", think="", live=True, steps=[], meeting=m["id"])
    bubble(aid, "💭 생각 중…", 120, True)
    steps, model, final, err = [], None, "", None
    t0 = time.time()
    for step in range(max_steps + 1):
        text, model, err = _ai(sysp, conv, aid, 1600)
        if not text:
            break
        mt = TOOL_RE.search(text)
        if mt and step < max_steps and mt.group(1) in T.TOOLS and time.time() - t0 < (200 if m["trigger"] == "user" else 360):
            name, args = mt.group(1), _parse_args(mt.group(2))
            act = T.TOOLS[name][1](args)
            st = {"act": act, "name": name, "icon": T.ICON.get(name, "🔧"), "status": "running"}
            steps.append(st)
            update(e, steps=steps)
            bubble(aid, f"{st['icon']} {act} 하는 중…", 60, True)
            res = T.run(name, args)
            st.update(status="error" if res.get("error") else "done", summary=res.get("summary", "")[:140], sources=(res.get("sources") or [])[:5])
            if res.get("chart"):
                st["chart"] = res["chart"]
            update(e, steps=steps)
            bubble(aid, f"{st['icon']} {act} → {st['summary']}"[:170], 8, True)
            conv += f"\n\n(네가 부른 도구) <tool name=\"{name}\">{json.dumps(args, ensure_ascii=False)[:400]}</tool>\n<tool_result name=\"{name}\">\n{res.get('text', '')[:3000]}\n</tool_result>\n도구 결과를 보고 이어서 말하세요(필요하면 도구를 한 번 더 부를 수 있습니다)."
            continue
        final = text
        break
    think, body = split_think(ko_only(final)) if final else ("", "")
    if final and not re.search(r"[가-힣]", body or ""):          # 빈 답·영어만·JSON 만 → 실패로 보고 다시
        body = ""
        text, model2, err = _ai(sysp + "\n반드시 한국어로, 바로 말한다.", conv, aid, 1200)
        if text:
            think, body = split_think(ko_only(text))
            model = model2 or model
    if body and not re.search(r"[가-힣]", body):
        body, err = "", err or "한국어 답을 내지 못함"
    if not body:
        body = f"({a['name']}: {'무료 AI 한도에 걸려 이번에는 쉬었습니다 · 잠시 뒤 다시 합니다' if err and re.search('429|한도|quota', err or '') else '연결된 모델들이 이번에는 답하지 못했습니다'})"
        update(e, live=False, text=body, error=(err or "")[:160], steps=steps)
        return {"agent": aid, "text": "", "failed": True}
    update(e, live=False, text=body, think=think, model=model, steps=steps)
    bubble(aid, "🗣 " + re.split(r"(?<=[.!?。])\s", body.replace("\n", " "))[0][:110], 6)
    return {"agent": aid, "text": body, "entry": e["id"]}


def _run_meeting(m: dict) -> None:
    RT["meeting"] = m
    ST["usage"]["meetings"] += 1
    if m["trigger"] == "user":
        post(m["room"], "system", text=f"{' → '.join(roster.BY_ID[x]['name'] for x in m['order'])} 순서로 답합니다 · 보통 1~3분 (최대 6분)", meeting=m["id"])
    post(m["room"], "divider", text=f"회의 · #{m['name']} · {len(m['order'])}명 참석", meeting=m["id"], place=m["place"], order=m["order"])
    event("start", meeting=m["id"], place=m["place"], order=m["order"])
    deadline = m["t"] + (360 if m["trigger"] == "user" else 600)
    m["t"] = time.time()
    deadline = time.time() + (360 if m["trigger"] == "user" else 600)
    i, cut_noted = 0, False
    while i < len(m["order"]) and i < 8:
        if RT["stop_meeting"]:
            post(m["room"], "system", text="회의를 멈췄습니다", meeting=m["id"])
            break
        if m.get("preempt"):
            m["preempt"] = False
            m["order"] = m["order"][i:]
            m["done"] = []
            with _lock:
                RT["queue"].insert(1 if RT["queue"] and RT["queue"][0]["trigger"] == "user" else 0, m)
            RT["meeting"] = None
            return
        aid = m["order"][i]
        last = i == len(m["order"]) - 1
        if time.time() > deadline and not last:
            if not cut_noted:
                post(m["room"], "system", text="시간이 길어져 정리 담당이 지금까지 내용으로 정리합니다", meeting=m["id"])
                cut_noted = True
            i += 1
            continue
        if time.time() > deadline + 120:
            break
        if paused() and m["trigger"] != "user" and m["turns"]:
            post(m["room"], "system", text="AI 한도 때문에 이 회의는 여기서 줄입니다", meeting=m["id"])
            break
        m["speaking"] = aid
        r = _turn(m, aid, i)
        m["done"].append(aid)
        if not r.get("failed"):
            m["turns"].append(r)
            added = 0
            for x in roster.find_mentions(r["text"], set(m["order"])):
                if added >= 2 or len(m["order"]) >= 8:
                    break
                pos = len(m["order"]) - 1 if m["order"][-1] == roster.CLOSER else len(m["order"])
                m["order"].insert(pos, x)
                added += 1
                post(m["room"], "system", text=f"{roster.BY_ID[aid]['name']}님이 {roster.BY_ID[x]['name']}({roster.BY_ID[x]['title']})님을 불렀습니다", meeting=m["id"])
                bubble(x, "부르셨어요? 갑니다", 5)
            if added and m["order"][-1] != roster.CLOSER:
                m["order"].append(roster.CLOSER)
        i += 1
    m["speaking"] = None
    event("end", meeting=m["id"])
    if m["turns"] and m["trigger"] in ("auto", "event") and CFG["alert"]:
        first = re.split(r"(?<=[.!?。])\s", m["turns"][-1]["text"].replace("\n", " "))[0][:140]
        post(m["room"], "alert", text=f"팀 회의 결과 · #{m['name']}: {first}")
        _push_alert(f"AI 사무실 · #{m['name']}", first)
    RT["meeting"] = None
    m["ev"].set()


def _push_alert(title: str, text: str) -> None:
    """앱 공통 알림(오토파일럿 시그널 스트림)에도 넣어 종·차트 옆 AI 패널에 뜨게 한다."""
    try:
        from .. import autopilot
        autopilot._signal({"type": "ai_auto", "symbol": "BTCUSDT", "interval": "1h", "status": "ai", "strategy": title[:80], "text": f"[{title}] {text}"[:300]})
    except Exception:  # noqa: BLE001
        pass


def _runner():
    while True:
        try:
            m = None
            with _lock:
                if RT["queue"] and not RT["meeting"]:
                    head = RT["queue"][0]
                    if head["trigger"] == "user" or not RT.get("chatting"):
                        m = RT["queue"].popleft()
            if m:
                RT["stop_meeting"] = False
                _run_meeting(m)
                save(True)
            else:
                time.sleep(1.0)
        except Exception as e:  # noqa: BLE001
            post("hq", "system", text=f"회의 진행 중 문제: {str(e)[:160]}")
            if RT["meeting"]:
                RT["meeting"]["ev"].set()
            RT["meeting"] = None
            time.sleep(3)


def status_text() -> str:
    m = RT["meeting"]
    rec = [e for e in LOG if e["kind"] in ("bt", "ml", "forecast", "files", "task", "report", "work") and e["ch"] != "hq"][-8:]
    lines = [f"[지금 사무실 상황 · 코드가 확인한 사실]",
             f"진행 중인 회의: {m['name'] if m and m['trigger'] != 'user' else '없음'} · 지금 하는 업무: {JOB_KO.get(RT['job'] or '', '없음')} · 다음 업무: {JOB_KO.get(JOBS[ST['job_i'] % len(JOBS)])}",
             "최근에 한 일:"]
    for e in rec:
        who = roster.BY_ID.get(e.get("agent") or "", {}).get("name", "")
        what = (f"매매법 '{e.get('name')}' {'통과' if e.get('pass') else '불통과'}" if e["kind"] == "bt" else
                f"과제 '{e.get('title')}' {e.get('status')}" if e["kind"] == "task" else (e.get("text") or e.get("title") or "")[:60])
        lines.append(f"- {datetime.fromtimestamp(e['t']).strftime('%H:%M')} {who} {what}")
    open_ = [b for b in ST["backlog"] if b["status"] != "done"][:4]
    if open_:
        lines.append("남은 성장 과제:")
        lines += [f"- {roster.TEAM_BY[b['team']]['name']}: {b['title']}" for b in open_]
    return "\n".join(lines)


ACTIONS = [("research", re.compile(r"(매매법|전략|지표).*(만들|찾|개발|짜|연구|발굴|백테스트)|(만들|찾|개발|짜).*(매매법|전략)|백테스트\s*(해|돌려)"),
            "퀀트 연구소가 지금 바로 매매법을 만들어 가장 오래된 과거부터 백테스트합니다"),
           ("forecast", re.compile(r"(방향|예측|전망).*(토론|예측해|맞춰)"), "전략팀이 지금 바로 방향 예측 토론을 엽니다"),
           ("ml", re.compile(r"(머신러닝|딥러닝|신경망|ML).*(돌려|학습|실험|예측해|해봐|해 줘|해줘)"), "퀀트 연구소 유진이 지금 바로 머신러닝 실험을 합니다")]


def ask(text: str, room: str = "hq") -> dict:
    text = text.strip()[:1500]
    if not text:
        raise ValueError("메시지를 입력하세요")
    room = room if room in roster.MEMBERS else "hq"
    e = post(room, "user", text=text)
    for job, rx, say in ACTIONS:
        if rx.search(text):
            team = JOB_TEAM[job]
            post(team, "system", text=f"▶ {say} (결과는 #{roster.TEAM_BY[team]['name']} 방 카드로)")
            threading.Thread(target=_safe_job, args=(job, text), daemon=True).start()
            break
    if not ai_ok():
        post(room, "system", text="AI 키가 없어 회의를 열 수 없습니다. 'AI 모델' 창에서 무료 NVIDIA·Gemini 키를 넣어 주세요.")
        return e
    enqueue("질문 · " + text[:18], room, text, "user")
    return e


# ------------------------------------------------------------------ 시그널 추적 (가상 체결) 장부
def office_bots() -> list:
    if not _paper:
        return []
    return [(bid, _paper.bots[bid], meta) for bid, meta in ST["bots"].items() if bid in _paper.bots]


def book_text() -> str:
    bots = office_bots()
    if not bots:
        return "아직 추적 중인 전략 시그널이 없습니다. 퀀트 연구소가 검증을 통과한 전략을 올리면 여기서 가상 체결로 추적합니다."
    rows, tot = [], 0.0
    for bid, b, meta in bots:
        snap = b.sim.snapshot(b.last_price)
        eq = snap.get("equity", b.initial_equity)
        tot += eq - b.initial_equity
        p = b.sim.position
        pos = f"보유 {'롱' if p.side == 1 else '숏'} {p.entry_price:.6g} (x{p.leverage:g})" if p else "무포지션"
        n = len(b.sim.trades)
        w = sum(1 for t in b.sim.trades if t.pnl > 0)
        rows.append(f"- {b.spec.name} ({b.spec.symbol} {b.spec.interval}, 레버리지 {b.spec.risk.leverage:g}배, {roster.BY_ID.get(meta.get('author'), {}).get('name', meta.get('author'))}) · "
                    f"평가 {eq:,.0f} ({(eq / b.initial_equity - 1) * 100:+.1f}%) · 거래 {n}회 승 {w} · {pos}")
    return f"추적 중 {len(bots)}개 (코인 선물, 전략마다 가상 10,000) · 합계 {tot:+,.0f} ({tot / (len(bots) * 10000) * 100:+.2f}%)\n" + "\n".join(rows)


def board() -> dict:
    out, tot = [], 0.0
    for bid, b, meta in office_bots():
        snap = b.sim.snapshot(b.last_price)
        eq = snap.get("equity", b.initial_equity)
        tot += eq - b.initial_equity
        p = b.sim.position
        out.append({"id": bid, "name": b.spec.name, "symbol": b.spec.symbol, "interval": b.spec.interval, "lev": b.spec.risk.leverage,
                    "pos": ("롱" if p.side == 1 else "숏") if p else "대기", "ret": round((eq / b.initial_equity - 1) * 100, 2),
                    "trades": len(b.sim.trades), "author": meta.get("author")})
    out.sort(key=lambda x: -x["ret"])
    n = len(out)
    return {"items": out[:MAX_BOTS], "total_pct": round(tot / (n * 10000) * 100, 2) if n else 0.0}


def _add_bot(spec, author: str, kind: str, wf: dict) -> str | None:
    if not _paper:
        return None
    bots = office_bots()
    if len(bots) >= MAX_BOTS:
        worst = min(bots, key=lambda x: x[1].sim.snapshot(x[1].last_price).get("equity", 1e18))
        _paper.bots.pop(worst[0], None)
        ST["bots"].pop(worst[0], None)
        post("quant", "trade", agent="trader", text=f"📤 [{worst[1].spec.name}] 새 전략에 자리를 내줌(성과 최하위) — 추적을 멈췄습니다")
    bot = _paper.add_bot(spec, 10_000.0)
    ST["bots"][bot.id] = {"author": author, "kind": kind, "created": time.time(), "wf": wf, "n": 0, "pos": None}
    _paper.save()
    return bot.id


def _watch_trades() -> None:
    """추적 중인 시그널의 새 진입·청산을 트레이더 현우가 #퀀트 연구소 방에 올린다."""
    for bid, b, meta in office_bots():
        p = b.sim.position
        cur = None if not p else f"{p.side}:{p.entry_time}"
        if cur and cur != meta.get("pos"):
            post("quant", "trade", agent="trader", text=f"📗 [{b.spec.name}] {b.spec.symbol} {'롱' if p.side == 1 else '숏'} 가상 진입 {p.entry_price:.6g} (x{p.leverage:g}, 손절 {p.stop or '-'}, 익절 {p.take or '-'})")
            bubble("trader", f"📗 {b.spec.name} {'롱' if p.side == 1 else '숏'} 진입", 9)
        n = len(b.sim.trades)
        for t in b.sim.trades[meta.get("n", 0):n]:
            post("quant", "trade", agent="trader", text=f"{'💰' if t.pnl > 0 else '📕'} [{b.spec.name}] {b.spec.symbol} {'롱' if t.side == 'long' else '숏'} 가상 청산 {t.exit_price:.6g} · {t.pnl:+.0f} (ROE {t.pnl_pct_on_margin:+.1f}%) · {t.exit_reason}")
        meta["n"], meta["pos"] = n, cur
        if b.sim.blown:
            post("quant", "trade", agent="trader", text=f"💥 [{b.spec.name}] 가상 계좌가 파산해 추적을 멈췄습니다")
            _paper.bots.pop(bid, None)
            ST["bots"].pop(bid, None)


# ------------------------------------------------------------------ 전략 JSON 정리
_OP = {"crossover": "crosses_above", "cross_above": "crosses_above", "crosses_over": "crosses_above", "cross_up": "crosses_above",
       "crossunder": "crosses_below", "cross_below": "crosses_below", "crosses_under": "crosses_below", "cross_down": "crosses_below",
       "gt": ">", "lt": "<", "gte": ">=", "lte": "<=", "=>": ">=", "=<": "<=", "≥": ">=", "≤": "<="}
_ALIAS = {"bollinger": "bb", "bbands": "bb", "vol_sma": "volume_sma", "volume_ma": "volume_sma", "williams": "willr", "williams_r": "willr",
          "stochastic": "stoch", "stoch_rsi": "stochrsi", "ichi": "ichimoku", "parabolic_sar": "psar", "sar": "psar", "ut_bot": "atr_stop", "dmi": "adx"}


def normalize_spec(raw: dict) -> dict:
    """AI 가 낸 전략 JSON 을 엔진 형식으로 너그럽게 고친다 (별칭·문자열 조건·배열 그룹 등)."""
    d = dict(raw or {})
    d["symbol"] = str(d.get("symbol") or "BTCUSDT").upper()
    d["interval"] = str(d.get("interval") or "1h")
    inds = []
    for x in d.get("indicators") or []:
        if not isinstance(x, dict):
            continue
        x = {**(x.get("params") or {}), **{k: v for k, v in x.items() if k != "params"}}
        x["type"] = _ALIAS.get(str(x.get("type", "")).lower(), str(x.get("type", "")).lower())
        for k in ("length", "fast", "slow", "signal", "k_smooth", "d_smooth", "horizon"):
            if x.get(k) is not None:
                try:
                    x[k] = max(1, int(round(float(x[k]))))
                except (TypeError, ValueError):
                    x.pop(k)
        inds.append(x)
    d["indicators"] = inds
    for g in ("long_entry", "short_entry", "long_exit", "short_exit"):
        v = d.get(g)
        if not v:
            d[g] = None
            continue
        if isinstance(v, list):
            v = {"logic": "all", "conditions": v}
        v = dict(v)
        v["logic"] = {"and": "all", "or": "any"}.get(str(v.get("logic", "all")).lower(), str(v.get("logic", "all")).lower())
        conds = []
        for c in v.get("conditions") or []:
            if isinstance(c, str):
                p = c.split()
                if len(p) == 3:
                    c = {"left": p[0], "op": p[1], "right": p[2]}
                else:
                    continue
            c = {"left": str(c.get("left", "")), "op": _OP.get(str(c.get("op", "")).lower(), str(c.get("op", ""))), "right": str(c.get("right", ""))}
            conds.append(c)
        v["conditions"] = conds
        d[g] = v if conds else None
    r = dict(d.get("risk") or {})
    for k, val in list(r.items()):
        if k == "allow_reverse":
            r[k] = str(val).lower() not in ("false", "0", "no", "off", "아니오")
        elif val is not None:
            try:
                r[k] = float(val)
            except (TypeError, ValueError):
                r.pop(k)
    if "leverage" in r:
        r["leverage"] = min(125.0, max(1.0, r["leverage"]))
    if "position_pct" in r:
        r["position_pct"] = min(100.0, max(1.0, r["position_pct"]))
    d["risk"] = {**r, **quantlab.COSTS}
    d["name"] = str(d.get("name") or "이름 없는 전략")[:60]
    return d


def _extract_json(text: str) -> dict | None:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    s = m.group(1) if m else None
    if not s:
        a, b = text.find("{"), text.rfind("}")
        s = text[a:b + 1] if a >= 0 and b > a else None
    if not s:
        return None
    try:
        return json.loads(s)
    except ValueError:
        try:
            return json.loads(re.sub(r",\s*([}\]])", r"\1", s))
        except ValueError:
            return None


# ------------------------------------------------------------------ 주기 업무
def _bt_card(spec, author: str, g: dict, sc: dict | None, hist: str, market_: str, kind: str = "research") -> dict:
    return post("quant", "bt", agent="val", name=spec.name, market=spec.symbol, mname=market_, tf=spec.interval, hist=hist,
                all=g["all"], is_=g["is"], oos=g["oos"], **{"pass": g["pass"]}, reasons=g["reasons"], author=author,
                spec=spec.model_dump(), scen=(sc or {}).get("text"), grade=(sc or {}).get("grade"), lev=spec.risk.leverage, source=kind)


def job_research(note_: str | None = None, author: str | None = None) -> None:
    from ..knowledge import brief
    from ..nl_strategy import SYSTEM_PROMPT, _indicator_table
    from ..quant.customind import CUSTOM_DOC
    from ..strategy import StrategySpec
    n = ST["research_n"]
    ST["research_n"] += 1
    a = author or ("cind" if n % 3 == 2 else "qb" if n % 2 else "qa")
    sym, iv, mname = MARKETS[n % len(MARKETS)]
    custom = a == "cind" or n % 2 == 1 or bool(note_)
    style = {"qa": "추세추종", "qb": "역추세·변동성", "cind": "커스텀 수식 지표 중심"}[a]
    bubble(a, f"🧪 {mname} {iv}봉 매매법 구상 중 (가장 오래된 과거부터)", 120, True)
    c, hist = quantlab.history(sym, iv)
    snap = quantlab.snapshot(c[-400:])
    ft = flow.flow_snapshot(sym)
    tried = "\n".join(f"- {r['name']} ({r['market']} {r['tf']}): {'통과' if r['pass'] else '불통과'}, 검증 구간 {r.get('oos')}%" for r in ST["research"][-8:]) or "(아직 없음)"
    sysp = (persona(a, "이번 일은 새 매매법 개발이다. 아래 형식 설명을 따라 전략 JSON 하나를 ```json 블록으로 쓰고, 블록 뒤에 왜 이 전략인지 2~3문장으로 말한다.")
            + "\n\n" + SYSTEM_PROMPT.format(indicator_table=_indicator_table())
            + "\n- 검증 관문: 앞 70% 학습 / 뒤 30% 검증으로 나눠, 검증 구간 거래 20건 이상 · 손익비 1.2 이상 · 두 구간 모두 이익이어야 통과. 거래가 너무 드문 조건은 통과하지 못한다."
            + "\n- 리스크 필드: leverage, position_pct, stop_loss_pct, take_profit_pct, atr_stop_mult, atr_tp_mult, trailing_stop_pct, allow_reverse"
            + f"\n\n## 레버리지\n레버리지는 자유롭게 정한다({T.LEV_HINT}가 일반적). 정한 뒤 코드가 모든 레버리지(1~200배)·상승장·하락장·횡보·폭락·수수료 2~3배·진입 지연 시나리오로 다시 시험한다."
            + ("\n\n## 이번 과제: 커스텀 지표\n거래소 기본 보조지표만 쓰지 말고 {\"type\":\"custom\",\"expr\":\"수식\"} 지표를 최소 1개 직접 발명해서 조건에 쓴다(예: 거래량 가중 모멘텀, 변동성 대비 이격, 여러 지표의 합성 점수).\n\n" + CUSTOM_DOC if custom else "")
            + (f"\n\n## 사용자 지시 (최우선)\n{note_}\n지시에 맞춰 만든다. 커스텀 수식 지표를 1개 이상 쓰고 여러 보조지표를 조합한다." if note_ else "")
            + "\n\n## 지금까지의 백테스트 연구 카드(참고)\n" + brief(sym, iv))
    user = (f"시장: {mname} ({sym}, 바이낸스 선물) · {iv}봉\n시험할 과거: {hist}\n지금 차트(보조지표 29종):\n{snap['text']}\n{json.dumps(snap['ind'], ensure_ascii=False, default=float)[:2200]}\n\n"
            f"호가·고래·선물 흐름(지금):\n{ft.get('text', '')[:1500]}\n\n최근 우리 팀이 시험한 전략(겹치지 않게):\n{tried}\n\n{style} 계열로 새 전략 하나를 만들어 주세요. symbol은 {sym}, interval은 {iv}.")
    out = solo(a, "quant", "", user, 1800, system=sysp)
    if not out:
        return
    raw = _extract_json(out["raw"])
    rec = {"name": "-", "market": sym, "tf": iv, "pass": False, "oos": None, "t": time.time(), "author": a}
    if not raw:
        post("quant", "system", text=f"{roster.BY_ID[a]['name']}의 답에서 전략 JSON을 찾지 못했습니다")
        ST["research"].append(rec)
        return
    try:
        spec = StrategySpec.model_validate(normalize_spec({**raw, "symbol": sym, "interval": iv}))
    except Exception as e:  # noqa: BLE001
        post("quant", "system", text=f"전략 형식 오류({roster.BY_ID[a]['name']}): {str(e)[:200]}")
        ST["research"].append(rec)
        return
    bubble("val", f"🧮 {spec.name} · {len(c):,}봉 백테스트 · 시나리오 검사 중", 120, True)
    try:
        g = quantlab.gate(spec, c)
        sc = quantlab.scenarios(spec, c, sig=g["sig"])
    except Exception as e:  # noqa: BLE001
        post("quant", "system", text=f"백테스트 실패({spec.name}): {str(e)[:200]}")
        ST["research"].append({**rec, "name": spec.name})
        return
    _bt_card(spec, a, g, sc, hist, mname)
    rec.update(name=spec.name, **{"pass": g["pass"]}, oos=g["oos"].get("ret"), grade=sc.get("grade"))
    ST["research"].append(rec)
    del ST["research"][:-60]
    bubble("val", f"{'✅ 통과' if g['pass'] else '❌ 불통과'}: {spec.name} — {' / '.join(g['reasons'][:2])}"[:170], 9)
    solo("val", "quant", "코드가 낸 백테스트·시나리오 결과를 3~5문장으로 설명한다. 어느 레버리지까지 견디는지, 어떤 장세에서 약한지, 최악의 해와 낙폭을 짚고, 통과·불통과 판정은 코드 판정을 따른다.",
         f"전략: {spec.name} ({mname} {iv}봉, 레버리지 {spec.risk.leverage:g}배)\n과거: {hist}\n판정: {'통과' if g['pass'] else '불통과'} — {' / '.join(g['reasons'])}\n\n시나리오:\n{sc.get('text', '')}", 900)
    if g["pass"] and sc.get("grade") != "취약":
        bid = _add_bot(spec, a, "research", {"is": g["is"], "oos": g["oos"]})
        if bid:
            from . import teamjobs
            teamjobs.pipe_add(spec, a, any(i.type == "custom" for i in spec.indicators), "demo",
                              {"pass": True, "grade": sc.get("grade"), "oos": g["oos"], "is": g["is"], "all": g["all"], "reasons": g["reasons"], "hist": hist}, bid, "quant")
            post("quant", "trade", agent="trader", text=f"📈 시그널 추적 시작: {spec.name} ({mname} {iv}봉 · 레버리지 {spec.risk.leverage:g}배 · {roster.BY_ID[a]['name']} 개발 · 다온 검증 통과 · 시나리오 {sc.get('grade')}) · 가상 10,000")
            bubble("trader", f"📈 {spec.name} 추적 시작합니다", 9)
            note("quant", f"통과: {spec.name} ({sym} {iv}) — 검증 구간 {g['oos'].get('ret')}%, 시나리오 {sc.get('grade')}")
    elif g["pass"]:
        post("quant", "system", text=f"{spec.name}: 70/30 관문은 통과했지만 시나리오 판정이 '취약'이라 시그널 추적에 올리지 않습니다")


def job_ml() -> None:
    from ..quant import ml
    from ..strategy import StrategySpec
    i = ST["ml_i"]
    ST["ml_i"] += 1
    sym, iv = ML_MARKETS[i % len(ML_MARKETS)]
    model = ML_MODELS[i % len(ML_MODELS)]
    bubble("ml", f"🧠 {sym} {ml.MODEL_KO[model]} 학습 중", 180, True)
    try:
        c, hist = quantlab.history(sym, iv, 6000)
        res = ml.walk_forward(c, model=model, horizon=1, seed=7 + i)
    except Exception as e:  # noqa: BLE001
        post("quant", "system", text=f"머신러닝 실험 실패: {str(e)[:160]}")
        return
    m = res["metrics"]
    post("quant", "ml", agent="ml", market=sym, tf=iv, model=ml.MODEL_KO[model], acc=round(m["accuracy"] * 100, 1), base=round(m["baseline"] * 100, 1),
         auc=m["auc"], edge=res["edge"], text=ml.text(res), equity=res["equity"][-200:])
    verdict = {"edge": "통계적 우위", "weak": "약한 신호(우위 아님)", "none": "우위 없음"}[res["edge"]]
    note("quant", f"{sym} {iv} {ml.MODEL_KO[model]}: 정확도 {m['accuracy'] * 100:.1f}% vs 기준 {m['baseline'] * 100:.1f}% → {verdict}")
    bubble("ml", f"🧠 {ml.MODEL_KO[model]} {sym}: {verdict}", 9)
    if ai_ok():
        solo("ml", "quant", "머신러닝 실험 결과를 3~4문장으로 동료에게 설명한다. 정확도·AUC 가 기준선보다 의미 있게 높은지(2σ), 보정이 맞는지, 어떤 특징이 중요했는지 말하고, 우위가 없으면 없다고 분명히 말한다.",
             f"{sym} {iv}봉 · {hist}\n{ml.text(res)}", 700)
    if res["edge"] == "edge":
        spec = StrategySpec.model_validate(normalize_spec({
            "name": f"ML {ml.MODEL_KO[model]} {sym.removesuffix('USDT')} {iv}", "symbol": sym, "interval": iv,
            "indicators": [{"id": "mlp", "type": "ml", "model": model, "horizon": 1}],
            "long_entry": {"logic": "all", "conditions": [{"left": "mlp.prob", "op": ">", "right": "0.58"}]},
            "long_exit": {"logic": "any", "conditions": [{"left": "mlp.prob", "op": "<", "right": "0.5"}]},
            "short_entry": {"logic": "all", "conditions": [{"left": "mlp.prob", "op": "<", "right": "0.42"}]},
            "short_exit": {"logic": "any", "conditions": [{"left": "mlp.prob", "op": ">", "right": "0.5"}]},
            "risk": {"leverage": 2, "position_pct": 20, "atr_stop_mult": 2}}))
        try:
            g = quantlab.gate(spec, c[-3000:])
            _bt_card(spec, "ml", g, None, f"머신러닝 예측 확률 전략 · {min(len(c), 3000):,}봉", f"{sym} {iv}", "ml")
            if g["pass"]:
                bid = _add_bot(spec, "ml", "ml", {"is": g["is"], "oos": g["oos"]})
                if bid:
                    from . import teamjobs
                    teamjobs.pipe_add(spec, "ml", False, "demo", {"pass": True, "oos": g["oos"], "is": g["is"], "all": g["all"], "reasons": g["reasons"]}, bid, "ml")
                    post("quant", "trade", agent="trader", text=f"📈 시그널 추적 시작: {spec.name} (머신러닝 확률 전략 · 다온 검증 통과) · 가상 10,000")
        except Exception as e:  # noqa: BLE001
            post("quant", "system", text=f"ML 전략 백테스트 실패: {str(e)[:160]}")


FC_RE = re.compile(r"예측\s*[:：]\s*([^\n:：]+?)\s+(상승|하락|횡보)\s*(?:확률)?\s*(\d{1,3})\s*%")


def score_forecasts() -> list[dict]:
    due = [f for f in ST["forecasts"] if f.get("result") is None and time.time() >= f["due"]]
    if not due:
        return []
    try:
        px = {r["symbol"]: r["price"] for r in market.tickers(list({f["q"] for f in due}))[0]}
    except Exception:  # noqa: BLE001
        return []
    out = []
    for f in due:
        p1 = px.get(f["q"])
        if not p1 or not f.get("p0"):
            continue
        ret = (p1 / f["p0"] - 1) * 100
        actual = "flat" if abs(ret) < 0.2 else "up" if ret > 0 else "down"
        hit = f["dir"] == actual or (f["dir"] == "flat" and abs(ret) < 0.5)
        f.update(result="hit" if hit else "miss", ret=round(ret, 2), p1=p1, paper=round({"up": 1, "down": -1, "flat": 0}[f["dir"]] * ret, 2))
        out.append(f)
        who = roster.BY_ID.get(f["by"], {})
        note(who.get("team", "strat"), f"{f['asset']} 24시간 예측({ {'up': '상승', 'down': '하락', 'flat': '횡보'}[f['dir']]} {f['prob']}%) → {'적중' if hit else '빗나감'}({ret:+.2f}%)")
    if out:
        post("strat", "forecast", agent="scen", items=[_fc_view(f) for f in out], score=forecast_score(), scored=True)
    return out


def forecast_score() -> dict:
    sc = [f for f in ST["forecasts"] if f.get("result")]
    n = len(sc)
    hit = sum(1 for f in sc if f["result"] == "hit")
    brier = sum((f["prob"] / 100 - (1 if f["result"] == "hit" else 0)) ** 2 for f in sc) / n if n else None
    return {"n": n, "hit": hit, "rate": round(hit / n * 100, 1) if n else None, "brier": round(brier, 3) if brier is not None else None,
            "paper": round(sum(f.get("paper", 0) for f in sc), 2)}


def _fc_view(f: dict) -> dict:
    return {"asset": f["asset"], "dir": f["dir"], "prob": f["prob"], "horizon": "24시간", "due": f["due"], "by": roster.BY_ID.get(f["by"], {}).get("name", f["by"]),
            "result": f.get("result"), "ret": f.get("ret")}


def job_forecast() -> None:
    score_forecasts()
    if not ai_ok():
        return
    names = ", ".join(a for a, _ in FC_ASSETS)
    m = enqueue("24시간-방향-예측", "strat", f"향후 24시간 방향 예측 토론: {names}. 각자 차트·호가·뉴스를 확인하고 반드시 '예측: 자산이름 상승|하락|횡보 확률%' 형식의 줄을 남겨 주세요. "
                "반대 의견도 환영합니다. 민재가 최종 예측을 정리합니다.", "auto", ["coin_fut", "deriv", "onchain"], wait=True)
    try:
        px = {r["symbol"]: r["price"] for r in market.tickers([q for _, q in FC_ASSETS])[0]}
    except Exception:  # noqa: BLE001
        px = {}
    new, seen = [], set()
    for t in m["turns"]:
        for mt in FC_RE.finditer(t["text"]):
            name, d, p = mt.group(1).strip(), mt.group(2), int(mt.group(3))
            hit = next(((a, q) for a, q in FC_ASSETS if a in name or name in a or q.removesuffix("USDT") in name.upper()), None)
            if not hit or (t["agent"], hit[1]) in seen or not px.get(hit[1]):
                continue
            seen.add((t["agent"], hit[1]))
            f = {"id": f"f{int(time.time() * 1000)}{len(new)}", "t": time.time(), "due": time.time() + 86400, "asset": hit[0], "q": hit[1],
                 "dir": {"상승": "up", "하락": "down", "횡보": "flat"}[d], "prob": min(99, p), "p0": px[hit[1]], "by": t["agent"]}
            new.append(f)
    if new:
        ST["forecasts"] += new
        del ST["forecasts"][:-300]
        post("strat", "forecast", agent="scen", items=[_fc_view(f) for f in new], score=forecast_score())


def job_sns() -> None:
    i = ST["sns_i"]
    ST["sns_i"] += 1
    sym = ["BTC", "ETH", "SOL"][i % 3]
    bubble("sns", "📱 코인 SNS 둘러보는 중", 60, True)
    r = media.sns_buzz(sym)
    for s in (r.get("sources") or [])[:4]:
        post("data", "work", agent="sns", icon="📱", text=s["title"], url=s["url"], src="reddit")
    if ai_ok():
        solo("sns", "data", "SNS에서 본 분위기를 3~5문장으로 해설한다. 사람들이 무엇에 흥분하거나 겁먹는지, 쏠림이 지나친지(역발상 신호인지) 말한다. SNS 글은 의견일 뿐이라는 점을 잊지 않는다.",
             r["text"][:5000], 900)
    fg = r.get("fear_greed")
    if fg is not None and (fg <= 15 or fg >= 85) and ST["usage"]["auto"] < CFG["daily_max"] and ai_ok():
        enqueue(f"여론-극단-{fg}", "data", f"코인 공포·탐욕 지수가 {fg}로 극단입니다. SNS 분위기와 시장을 함께 점검해 주세요.", "event", ["sns", "coin_spot", "coin_fut"])


def job_media() -> None:
    i = ST["media_i"]
    ST["media_i"] += 1
    q = MEDIA_Q[i % len(MEDIA_Q)]
    yt = i % 3 != 2
    aid = "yt" if yt else "insta"
    bubble(aid, f"{'▶️ 유튜브' if yt else '📸 인스타·커뮤니티'}에서 ‘{q}’ 찾는 중", 90, True)
    if yt:
        r = media.youtube_search(q, 10)
        text = media.media_text(r, "유튜브 영상")
    else:
        r1, r2 = media.instagram_search(q), media.community_search(q)
        r = {"items": r1["items"] + r2["items"], "via": "web"}
        text = media.media_text(r, "인스타그램·커뮤니티")
    for x in r["items"][:4]:
        post("data", "work", agent=aid, icon="▶️" if yt else "📸", text=f"{x.get('title', '')[:90]}{(' · ' + x['views']) if x.get('views') else ''}", url=x.get("url"),
             src=x.get("channel") or x.get("source") or "")
    if ai_ok() and r["items"]:
        solo(aid, "data", "본 영상·게시물 제목과 조회수로 지금 대중이 무엇에 관심 있고 어떤 분위기인지 3~5문장으로 해설한다. 의견·인기일 뿐 사실이 아님을 짚고, 역발상 신호인지도 말한다.", text, 900)
    elif not r["items"]:
        post("data", "system", text=f"‘{q}’ 검색 결과를 가져오지 못했습니다 (접속 제한일 수 있음)")


def job_paper() -> None:
    if not office_bots():
        return job_research()
    if ai_ok():
        solo("trader", "quant", "시그널 추적(가상 체결) 현황을 팀에 3~5문장으로 보고한다. 잘 되는 전략과 안 되는 전략, 지금 포지션의 위험을 짚는다. 실제 주문이 아닌 가상 체결임을 잊지 않는다.",
             "시그널 추적 장부:\n" + book_text(), 800)


def job_flowscan() -> None:
    i = ST["flow_i"]
    ST["flow_i"] += 1
    aid, sym = ("deriv", "BTCUSDT") if i % 2 == 0 else ("onchain", "ETHUSDT")
    bubble(aid, f"🌊 {sym} 선물 수급·고래·청산 구간 보는 중", 60, True)
    fs = flow.flow_snapshot(sym)
    lq = flow.liquidation_estimate(sym)
    post("coin", "work", agent=aid, icon="🌊", text=fs.get("summary", ""), src="바이낸스 선물")
    if ai_ok() and "error" not in fs:
        solo(aid, "coin", "코드가 계산한 흐름 점수·호가·고래·선물 수급·예상 청산 구간을 3~5문장으로 해설한다. 어느 쪽이 쏠렸는지, 연쇄 청산이 어느 방향이 더 위험한지 말한다. 예상 청산 구간은 추정이라는 점을 밝힌다.",
             fs["text"] + "\n\n" + lq.get("text", ""), 900)


def job_alt() -> None:
    bubble("alt", "🏁 알트 거래대금·상승률 순위 보는 중", 60, True)
    try:
        rows = market.heatmap(150)
    except Exception as e:  # noqa: BLE001
        post("coin", "system", text=f"알트 순위를 가져오지 못했습니다: {str(e)[:120]}")
        return
    btc = next((r for r in rows if r["symbol"] == "BTCUSDT"), None)
    gain = sorted(rows, key=lambda r: -r["change_pct"])[:8]
    loss = sorted(rows, key=lambda r: r["change_pct"])[:5]
    vol = sorted(rows, key=lambda r: -r["quote_volume"])[:10]
    txt = (f"BTC 24h {btc['change_pct']:+.2f}%\n" if btc else "") + "상승 상위: " + ", ".join(f"{r['symbol'].removesuffix('USDT')} {r['change_pct']:+.1f}%" for r in gain) + \
          "\n하락 상위: " + ", ".join(f"{r['symbol'].removesuffix('USDT')} {r['change_pct']:+.1f}%" for r in loss) + \
          "\n거래대금 상위: " + ", ".join(f"{r['symbol'].removesuffix('USDT')} {r['change_pct']:+.1f}% ({flow.usd(r['quote_volume'])})" for r in vol)
    post("coin", "work", agent="alt", icon="🏁", text=txt.split("\n")[1][:120] if btc else txt[:120], src="바이낸스 선물 24h")
    if ai_ok():
        solo("alt", "coin", "알트 순위로 지금 돈이 어느 섹터(레이어1·AI·밈 등)로 도는지, 비트코인 대비 강약은 어떤지 3~5문장으로 해설한다. 펌핑 추격의 위험도 짚는다.", txt, 800)


def job_coinnews() -> None:
    bubble("coinnews", "📰 코인 뉴스·규제 소식 모으는 중", 60, True)
    a, b = T.market_news("crypto"), T.market_news("regulation")
    for s in (a.get("sources") or [])[:3]:
        post("coin", "work", agent="coinnews", icon="📰", text=s["title"], url=s["url"])
    if ai_ok():
        solo("coinnews", "coin", "기사 제목을 늘어놓지 말고 큰 줄기 2~3개로 묶어 시장에 어떤 의미인지 해설한다. 근거 문장 끝에만 [번호]를 단다.", a["text"] + "\n\n[규제·법]\n" + b["text"], 1000)


def job_pm() -> None:
    bots = office_bots()
    if not bots:
        return job_research()
    curves = {}
    for bid, b, meta in bots:
        curves[b.spec.name] = [p["value"] for p in b.sim.equity_curve[-200:]]
    lines = [book_text()]
    names = list(curves)
    corr = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            x, y = curves[names[i]], curves[names[j]]
            k = min(len(x), len(y))
            if k > 10:
                rx = [x[t] / x[t - 1] - 1 for t in range(len(x) - k + 1, len(x))]
                ry = [y[t] / y[t - 1] - 1 for t in range(len(y) - k + 1, len(y))]
                mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
                sx = math.sqrt(sum((v - mx) ** 2 for v in rx)) or 1e-12
                sy = math.sqrt(sum((v - my) ** 2 for v in ry)) or 1e-12
                corr.append(f"{names[i]}↔{names[j]} {sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / sx / sy:+.2f}")
    if corr:
        lines.append("수익 곡선 상관: " + " · ".join(corr[:10]))
    if ai_ok():
        solo("pm", "strat", "추적 중인 전략 시그널들을 포트폴리오로 본다. 같은 코인·같은 방향에 몰렸는지, 상관이 높아 사실상 한 베팅인지, 합산 낙폭이 감당 가능한지 3~5문장으로 말하고 비중 조정 의견을 낸다(실제 주문 없음).",
             "\n".join(lines), 900)


def job_scen() -> None:
    lq = flow.liquidation_estimate("BTCUSDT")
    lines = [lq.get("text", "")]
    for bid, b, meta in office_bots():
        p = b.sim.position
        if p and b.last_price:
            for shock in (-20, -10, 10):
                px = b.last_price * (1 + shock / 100)
                pnl = p.qty * (px - p.entry_price) * p.side
                liq = (p.side == 1 and px <= p.liq_price) or (p.side == -1 and px >= p.liq_price)
                lines.append(f"{b.spec.name} {'롱' if p.side == 1 else '숏'}: 가격 {shock:+d}% → {pnl:+,.0f}{' (강제청산)' if liq else ''}")
    if ai_ok():
        solo("scen", "strat", "급락(-10%·-20%)·급등·펀딩 급등·거래소 장애 시나리오에서 무엇이 먼저 무너지는지와 대응 원칙을 3~5문장으로 정리한다. 예상 청산 구간은 추정임을 밝힌다.", "\n".join(lines)[:3000], 900)


def job_comp() -> None:
    recent = [e for e in LOG if e["kind"] == "agent" and e.get("text")][-12:]
    flagged = [e for e in recent if re.search(r"무조건|확실히|100%|지금 사|지금 팔|풀매수|올인|몰빵|레버리지\s*(50|100|125)", e["text"])]
    txt = "\n".join(f"- {roster.BY_ID.get(e['agent'], {}).get('name')}: {e['text'][:200]}" for e in (flagged or recent[-6:]))
    if ai_ok():
        out = solo("comp", "strat", "최근 사무실 발언에서 투자 권유처럼 단정하는 표현, 고레버리지를 부추기는 표현, 출처 없는 숫자를 찾아 3~4문장으로 지적하고 고칠 표현을 제안한다. 문제가 없으면 없다고 말한다.",
                   f"코드가 표시한 의심 발언 {len(flagged)}건\n{txt}", 800)
        if flagged and out:
            add_task("strat", "단정적 표현·고레버리지 권유 줄이기", f"컴플라이언스 점검에서 {len(flagged)}건 지적", "comp")


def job_datacheck() -> None:
    from ..data import altex
    lines = []
    for src, fn in (("binance", lambda: market._one("binance", "BTCUSDT", "1h", 50, None)), ("bybit", lambda: altex.bybit_klines("BTCUSDT", "1h", 50)),
                    ("okx", lambda: altex.okx_klines("BTCUSDT", "1h", 50))):
        try:
            c = fn()
            gaps = sum(1 for a, b in zip(c, c[1:]) if b["time"] - a["time"] != 3600)
            age = time.time() - c[-1]["time"]
            lines.append(f"{src}: 마지막 종가 {c[-1]['close']:.2f} · 빈 봉 {gaps}개 · 마지막 봉 {age / 60:.0f}분 전")
        except Exception as e:  # noqa: BLE001
            lines.append(f"{src}: 실패 ({str(e)[:80]})")
    closes = [float(re.search(r"종가 ([\d.]+)", l).group(1)) for l in lines if "종가" in l]
    if len(closes) >= 2:
        lines.append(f"거래소 간 종가 차이 {(max(closes) / min(closes) - 1) * 100:.3f}%")
    post("data", "work", agent="crawl", icon="📥", text=" · ".join(l.split(":")[0] + ("✓" if "실패" not in l else "✗") for l in lines[:3]), src="데이터 점검")
    if ai_ok():
        solo("crawl", "data", "거래소 데이터 품질 점검 결과를 2~3문장으로 보고한다(빈 봉·지연·거래소 차이). 문제가 있으면 무엇에 영향을 주는지 말한다.", "\n".join(lines), 500)


def job_viz() -> None:
    rs = ST["research"][-12:]
    fs = forecast_score()
    table = "| 전략 | 시장 | 판정 | 검증 수익 | 시나리오 |\n|---|---|---|---|---|\n" + "\n".join(
        f"| {r['name'][:24]} | {r['market'].removesuffix('USDT')} {r['tf']} | {'✅' if r['pass'] else '❌'} | {r.get('oos') if r.get('oos') is not None else '-'}% | {r.get('grade') or '-'} |" for r in reversed(rs))
    md = f"### 퀀트 연구 결과 (최근 {len(rs)}개)\n\n{table}\n\n### 방향 예측 성적\n채점 {fs['n']}건 · 적중 {fs['hit']} ({fs['rate'] or '-'}%) · Brier {fs['brier'] or '-'} · 1배 가상 손익 {fs['paper']}%\n\n### 시그널 추적\n{book_text()}"
    post("data", "files", agent="viz", title="발표용 요약표", md=md, files=[])
    bubble("viz", "📈 발표용 요약표를 만들었어요", 8)


def job_files() -> None:
    d = _dir() / "files"
    (d / "reports").mkdir(parents=True, exist_ok=True)
    (d / "strategies").mkdir(exist_ok=True)
    rows, stats = ["strategy,symbol,side,entry_time,entry,exit_time,exit,pnl_usdt,roe_pct,reason"], []
    for bid, b, meta in office_bots():
        losing = streak = 0
        for t in b.sim.trades:
            rows.append(f"{b.spec.name},{b.spec.symbol},{t.side},{t.entry_time},{t.entry_price},{t.exit_time},{t.exit_price},{t.pnl:.2f},{t.pnl_pct_on_margin:.2f},{t.exit_reason}")
            streak = streak + 1 if t.pnl <= 0 else 0
            losing = max(losing, streak)
        n = len(b.sim.trades)
        stats.append(f"- {b.spec.name}: 거래 {n} · 승률 {sum(1 for t in b.sim.trades if t.pnl > 0) / n * 100 if n else 0:.0f}% · 평균 {sum(t.pnl for t in b.sim.trades) / n if n else 0:+.1f} · 최장 연속 손실 {losing}")
        (d / "strategies" / f"{re.sub(r'[^0-9A-Za-z가-힣_-]+', '_', b.spec.name)[:50]}.json").write_text(json.dumps(b.spec.model_dump(), ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "trades.csv").write_text("\n".join(rows), encoding="utf-8")
    rep = f"# {_today()} 사무실 일일 보고\n\n## 시그널 추적\n{book_text()}\n\n## 전략별 통계\n" + ("\n".join(stats) or "-") + "\n\n## 최근 연구\n" + \
          "\n".join(f"- {'✅' if r['pass'] else '❌'} {r['name']} ({r['market']} {r['tf']}) 검증 {r.get('oos')}%" for r in ST["research"][-20:])
    (d / "reports" / f"{_today()}.md").write_text(rep, encoding="utf-8")
    files = ["reports/" + _today() + ".md", "trades.csv"] + [f"strategies/{p.name}" for p in (d / "strategies").glob("*.json")][:5]
    post("data", "files", agent="eng", title="일일 보고서·거래 기록·전략 파일 저장", files=files, md="\n".join(stats))
    bubble("eng", "💾 보고서·거래 기록 저장했어요", 8)


def add_task(team: str, title: str, why: str = "", owner: str | None = None) -> dict | None:
    title = title.strip()[:160]
    if not title or any(b["title"] == title and b["status"] != "done" for b in ST["backlog"]):
        return None
    mem = roster.MEMBERS.get(team, [])
    own = next((x for x in mem if owner and (x == owner or roster.BY_ID[x]["name"] in owner)), None) or next((x for x in mem if not roster.BY_ID[x]["lead"]), mem[0] if mem else None)
    b = {"id": f"b{int(time.time() * 1000)}", "team": team, "title": title, "why": why[:200], "status": "todo", "owner": own, "t": time.time(), "result": ""}
    ST["backlog"].append(b)
    del ST["backlog"][:-200]
    post(team, "task", agent=own, title=title, status="todo", result=why[:200])
    return b


def job_retro() -> None:
    teams = [t["id"] for t in roster.TEAMS]
    team = teams[ST["retro_i"] % len(teams)]
    ST["retro_i"] += 1
    lead = roster.TEAM_LEAD[team]
    RT["huddle"] = {"host": lead, "ids": roster.MEMBERS[team], "until": time.time() + 90}
    recent = [e for e in LOG if e["ch"] == team and time.time() - e["t"] < 6 * 3600][-25:]
    rec = "\n".join(f"- [{e['kind']}] {roster.BY_ID.get(e.get('agent') or '', {}).get('name', '')}: {(e.get('text') or e.get('name') or e.get('title') or '')[:160]}"
                    + (f" ({'통과' if e.get('pass') else '불통과'})" if e["kind"] == "bt" else "") for e in recent)
    open_ = "\n".join(f"- {b['title']}" for b in ST["backlog"] if b["team"] == team and b["status"] != "done")
    out = solo(lead, team, f"지금은 {roster.TEAM_BY[team]['name']} 회고·성장 회의다. 최근 기록을 보고 ① 배운 것(다음에 반드시 반영할 교훈) 2~4개 ② 우리 팀에 부족한 점을 메울 구체적인 새 과제 1~3개(누가 맡을지 팀원 이름 포함)를 정한다. "
                    "세계적인 기업 수준의 기준으로 냉정하게. 답 마지막에 ```json {\"lessons\":[\"...\"],\"tasks\":[{\"title\":\"...\",\"why\":\"...\",\"owner\":\"팀원 이름\"}]}``` 를 붙인다.",
               f"팀원: {', '.join(roster.BY_ID[x]['name'] + '(' + roster.BY_ID[x]['title'] + ')' for x in roster.MEMBERS[team])}\n최근 기록:\n{rec or '(없음)'}\n\n아직 안 끝난 과제:\n{open_ or '(없음)'}", 1200)
    RT["huddle"] = None
    if not out:
        return
    j = _extract_json(out["raw"]) or {}
    for l in (j.get("lessons") or [])[:4]:
        note(team, str(l))
    for t in (j.get("tasks") or [])[:3]:
        if isinstance(t, dict):
            add_task(team, str(t.get("title", "")), str(t.get("why", "")), str(t.get("owner", "")))


def job_task() -> None:
    b = next((x for x in ST["backlog"] if x["status"] == "todo"), None)
    if not b:
        return job_retro()
    b["status"] = "doing"
    post(b["team"], "task", agent=b["owner"], title=b["title"], status="doing", result="")
    m = enqueue(f"과제-{b['title'][:14]}", b["team"], f"성장 과제: {b['title']}\n왜: {b['why']}\n도구(검색·차트·백테스트·머신러닝 등)를 써서 실제로 해내고, 결과물과 배운 점을 보고해 주세요. 못 한 부분은 솔직히 말합니다.",
                "auto", [b["owner"]] if b["owner"] else None, wait=True)
    res = (m["turns"][-1]["text"] if m["turns"] else "결과 없음")[:300]
    b.update(status="done", result=res, done=time.time())
    post(b["team"], "task", agent=b["owner"], title=b["title"], status="done", result=res)
    note(b["team"], f"과제 '{b['title'][:50]}' 결과: {res[:140]}")


def chatter() -> None:
    if not ai_ok() or RT["meeting"] or RT["queue"] or paused():
        return
    _reset_usage()
    if ST["usage"]["chats"] >= CFG["chat_max"]:
        return
    fresh = [aid for aid, obs in RT["seen"].items() if obs and time.time() - obs[-1]["t"] < 600]
    starter = random.choice(fresh) if fresh else random.choice(list(roster.WATCH))
    obs = (RT["seen"].get(starter) or [None])[-1] or observe(starter)
    if not obs:
        return
    rel = list(roster.RELATED.get(starter, []))
    random.shuffle(rel)
    parts = rel[:random.choice((1, 2))]
    people = [starter] + parts
    who = ", ".join(f"{roster.BY_ID[x]['name']}({roster.BY_ID[x]['title']})" for x in people)
    sysp = (f"[잡담] 너는 GH Quant AI 사무실 직원들의 대화를 쓰는 작가다. 회사 동료들이 자리에서 일하다 나누는 자연스러운 한국어 대화를 쓴다.\n참여자: {who}\n"
            f"규칙: 4~7줄. 각 줄은 '이름: 대사' 형식(참여자 이름만). 대사는 1~2문장. {roster.BY_ID[starter]['name']}가 방금 본 것을 꺼내며 시작한다. 각자 자기 전문 분야 관점으로 반응하고, 가벼운 농담이나 생활 이야기가 섞여도 좋다.\n"
            "방금 본 것 외의 숫자·사실은 지어내지 말고, 모르면 '확인해 볼게요'라고 한다. 투자 권유처럼 단정하지 않는다. 팀 회의가 꼭 필요할 만큼 중요하면 마지막 줄에 누군가 '회의 한번 하죠'라고 말한다.")
    RT["chatting"] = True
    try:
        ST["usage"]["chats"] += 1
        text, model, err = _ai(sysp, f"{roster.BY_ID[starter]['name']}가 방금 본 것: {obs['icon']} {obs['text']}" + (f" (출처: {obs['src']})" if obs.get("src") else ""), "chat", 600)
        if not text:
            return
        lines = []
        for l in ko_only(text).split("\n"):
            l = re.sub(r"^[\s\-*•]+|\*\*", "", l).strip()
            mt = re.match(r"^([^:：]{1,12})\s*[:：]\s*(.+)$", l)
            if not mt:
                continue
            sp = next((x for x in people if roster.BY_ID[x]["name"] in mt.group(1)), None)
            if sp:
                lines.append((sp, mt.group(2).strip()))
        lines = lines[:8]
        if len(lines) < 2:
            return
        post(roster.BY_ID[starter]["team"], "divider", text=f"수다 · {', '.join(roster.BY_ID[x]['name'] for x in people)} · {model or ''}", chat=True)
        RT["huddle"] = {"host": starter, "ids": people, "until": time.time() + 15 + 4 * len(lines)}
        for sp, line in lines:
            post(roster.BY_ID[sp]["team"], "agent", agent=sp, text=line, chat=True, model=model)
            bubble(sp, line[:150], min(9, 2.5 + len(line) * 0.05))
            time.sleep(min(6.5, 1.6 + len(line) * 0.045))
        if re.search(r"회의\s*(한번|한 번)?\s*(하죠|합시다|해요|하자|열|해보|잡)", lines[-1][1]) and ST["usage"]["auto"] < CFG["daily_max"]:
            enqueue(f"잡담에서-{roster.BY_ID[starter]['name']}", roster.BY_ID[starter]["team"],
                    f"잡담에서 나온 이야기입니다. {roster.BY_ID[starter]['name']}가 본 것: {obs['text']}. 의미와 대응을 팀으로 점검해 주세요.", "auto", people[:3])
    finally:
        RT["chatting"] = False
        RT["huddle"] = None


JOB_FN = {"research": job_research, "forecast": job_forecast, "ml": job_ml, "sns": job_sns, "media": job_media, "paper": job_paper,
          "flowscan": job_flowscan, "alt": job_alt, "coinnews": job_coinnews, "pm": job_pm, "scen": job_scen, "comp": job_comp,
          "datacheck": job_datacheck, "viz": job_viz, "files": job_files, "retro": job_retro, "task": job_task, "chat": chatter}
NO_AI_JOBS = {"ml", "datacheck", "viz", "files", "alt", "flowscan"}


def run_job(job: str, note_: str | None = None) -> None:
    team = JOB_TEAM.get(job, "strat")
    RT["job"] = job
    lead = roster.TEAM_LEAD[team]
    post(team, "work", agent=lead, icon="▶", text=f"{JOB_KO.get(job, job)} 시작")
    event("cycle", job=job)
    try:
        if job == "research" and note_:
            job_research(note_)
        elif job == "forecast" and note_:
            job_forecast()
        else:
            JOB_FN[job]()
    finally:
        RT["job"] = None
        save(True)


def _safe_job(job: str, note_: str | None = None) -> None:
    try:
        run_job(job, note_)
    except Exception as e:  # noqa: BLE001
        post("hq", "system", text=f"{JOB_KO.get(job, job)} 중 문제: {str(e)[:120]}")
        RT["job"] = None


def cycle() -> None:
    _watch_trades()
    _reset_usage()
    if ST["usage"]["calls"] >= CFG["call_max"]:
        if not ST["usage"]["cap_noted"]:
            ST["usage"]["cap_noted"] = True
            post("hq", "system", text=f"오늘 사무실 AI 호출 한도({CFG['call_max']}번)를 다 썼습니다. 시그널 추적 갱신과 차트·뉴스 확인은 계속합니다.")
        return
    job = JOBS[ST["job_i"] % len(JOBS)]
    ST["job_i"] += 1
    if not ai_ok() and job not in NO_AI_JOBS:
        job = random.choice(sorted(NO_AI_JOBS))
    if job == "chat" and (RT["meeting"] or RT["queue"]):
        job = "coinnews"
    _safe_job(job)


# ------------------------------------------------------------------ 관찰 (코드만)
def observe(aid: str) -> dict | None:
    kinds = roster.WATCH.get(aid)
    if not kinds:
        return None
    kind, arg = random.choice(kinds)
    o = None
    try:
        if kind == "quote":
            r = market.tickers([arg])[0][0]
            o = {"icon": "📈" if r["change_pct"] >= 0 else "📉", "text": f"바이낸스 선물 {arg.removesuffix('USDT')} {r['price']:,.6g} USDT ({r['change_pct']:+.2f}%) 차트 보는 중"}
        elif kind == "whale":
            r = flow.whale_trades(arg)
            o = None if r.get("error") else {"icon": "🐋", "text": r["summary"][:120]}
        elif kind == "book":
            r = flow.order_book(arg, 500)
            o = None if r.get("error") else {"icon": "📚", "text": r["summary"][:120]}
        elif kind == "flow":
            r = flow.futures_flow(arg)
            o = None if r.get("error") else {"icon": "🌊", "text": r["summary"][:120]}
        elif kind == "liq":
            r = flow.liquidation_estimate(arg)
            o = None if r.get("error") else {"icon": "💥", "text": f"{arg.removesuffix('USDT')} " + r["summary"][:110]}
        elif kind == "news":
            items = T.market_news(arg).get("sources") or []
            if items:
                x = random.choice(items[:6])
                o = {"icon": "📰", "text": x["title"][:110], "url": x["url"], "src": re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*$", r"\1", x["url"]))}
        elif kind == "movers":
            rows = sorted(market.heatmap(100), key=lambda r: -r["change_pct"])[:3]
            o = {"icon": "🏁", "text": "오늘 상승 상위 " + ", ".join(f"{r['symbol'].removesuffix('USDT')} {r['change_pct']:+.1f}%" for r in rows)}
        elif kind == "indicators":
            c, _ = market.candles(arg, "1h", 300)
            o = {"icon": "📊", "text": f"{arg.removesuffix('USDT')} 1시간 " + quantlab.snapshot(c)["text"].split("\n")[0][4:110]}
        elif kind == "research" and ST["research"]:
            r = ST["research"][-1]
            o = {"icon": "🧪", "text": f"최근 연구 '{r['name']}' {'통과' if r['pass'] else '불통과'} ({r['market'].removesuffix('USDT')} {r['tf']})"}
        elif kind == "paper":
            o = {"icon": "📒", "text": book_text().split("\n")[0][:120]}
        elif kind == "fng":
            from ..data import sentiment
            f = sentiment.fear_greed(7)
            o = {"icon": "😨" if f["value"] < 45 else "🤑" if f["value"] > 55 else "😐", "text": f"공포·탐욕 지수 {f['value']} ({f['label']})"}
        elif kind == "sources":
            o = {"icon": "📥", "text": "시세 소스 " + " → ".join(market.sources()) + (" · 최근 오류 있음" if market.last_errors else " · 정상")}
    except Exception:  # noqa: BLE001
        o = None
    if not o:
        return None
    o["t"] = time.time()
    seen = RT["seen"].setdefault(aid, [])
    seen.append(o)
    del seen[:-8]
    bubble(aid, f"{o['icon']} {o['text']}", 7)
    if time.time() - RT["last_work_post"].get(aid, 0) > 180:
        RT["last_work_post"][aid] = time.time()
        post(roster.BY_ID[aid]["team"], "work", agent=aid, icon=o["icon"], text=o["text"], url=o.get("url"), src=o.get("src"))
    return o


# ------------------------------------------------------------------ 자동 회의 · 급변동 · 발표
def _emergency() -> None:
    if time.time() - ST["last_emergency"] < 600:
        return
    ST["last_emergency"] = time.time()
    try:
        rows = {r["symbol"]: r for r in market.tickers([s for s, _, _ in WATCH_EMERGENCY])[0]}
    except Exception:  # noqa: BLE001
        return
    for sym, name, th in WATCH_EMERGENCY:
        r = rows.get(sym)
        if not r:
            continue
        band = int(r["change_pct"] / th)
        key = f"{sym}|{_today()}"
        if band and ST["bands"].get(key) != band and ST["usage"]["auto"] < CFG["daily_max"]:
            ST["bands"][key] = band
            post("coin", "system", text=f"급변동 감지: {name} {r['change_pct']:+.1f}% → 긴급 회의를 엽니다")
            enqueue(f"긴급-{name}", "coin", f"{name}가 하루 {r['change_pct']:+.1f}% 움직였습니다. 원인과 지금 대응 방법을 점검해 주세요.", "event", ["coin_spot", "coin_fut", "deriv"])
            _push_alert(f"AI 사무실 · 급변동 {name}", f"{r['change_pct']:+.1f}% — 코인팀 긴급 회의")


def report(manual: bool = False) -> dict | None:
    since = ST["last_report"] or (time.time() - 3600)
    ST["last_report"] = time.time()
    sections = []
    for t in roster.TEAMS:
        es = [e for e in LOG if e["ch"] == t["id"] and e["t"] >= since]
        items = []
        talk = sum(1 for e in es if e["kind"] == "agent" and not e.get("chat"))
        if talk:
            items.append(f"발언·분석 {talk}건")
        bts = [e for e in es if e["kind"] == "bt"]
        if bts:
            ok = [e["name"] for e in bts if e.get("pass")]
            items.append(f"매매법 {len(bts)}개 검증 (통과 {len(ok)}: {', '.join(ok) or '-'})")
        tr = [e for e in es if e["kind"] == "trade"]
        if tr:
            items.append(f"가상 체결 {len(tr)}건")
        items += [f"머신러닝 {e['market']} {e['tf']} {e['model']} 정확도 {e['acc']}% (기준 {e['base']}%)" for e in es if e["kind"] == "ml"]
        for e in es:
            if e["kind"] == "forecast":
                items.append(f"방향 예측 {len(e['items'])}건" + (f" · 적중 {sum(1 for x in e['items'] if x.get('result') == 'hit')}/{len(e['items'])}" if e.get("scored") else ""))
        items += [f"파일 저장: {e['title']}" for e in es if e["kind"] == "files"]
        items += [f"성장 과제 완료: {e['title']}" for e in es if e["kind"] == "task" and e.get("status") == "done"]
        nxt = [b["title"] for b in ST["backlog"] if b["team"] == t["id"] and b["status"] != "done"][:2]
        if items or nxt:
            sections.append({"team": t["id"], "name": t["name"], "lead": roster.BY_ID[roster.TEAM_LEAD[t["id"]]]["name"], "items": items, "next": nxt})
    if not sections and not manual:
        return None
    h = datetime.now().hour
    facts = "\n\n".join(f"## {s['name']} (팀장 {s['lead']})\n" + "\n".join(f"- {x}" for x in s["items"]) + (f"\n다음: {' / '.join(s['next'])}" if s["next"] else "") for s in sections)
    text = None
    if ai_ok():
        RT["presenting"] = {"until": time.time() + 30, "title": f"{h}시 성과 발표"}
        out = solo(roster.CLOSER, "hq", "지금은 매시간 하는 사무실 성과 발표다. 아래 사실만으로 대표(사용자)에게 짧게 발표한다: 핵심 성과 3줄 → 기록이 있는 팀만 한 줄씩(해낸 것 · 다음 할 일) → 도움이 필요한 것 1줄. "
                                       "전체 15줄 이내, 한국어, 마크다운 목록. 기록이 없는 팀은 쓰지 않고, 지어내지 않는다.",
                   f"{h}시 발표 · 지난 {int((time.time() - since) / 60)}분\n\n{facts or '(기록 없음)'}\n\n시그널 추적:\n{book_text()[:1500]}", 1600)
        text = out and next((e.get("text") for e in reversed(LOG) if e.get("id") == out["id"]), None)
    rep = {"id": f"r{int(time.time())}", "t": time.time(), "since": since, "title": f"{h}시 성과 발표", "text": text or facts or "기록이 없습니다.", "sections": sections}
    reps = _load_reports()
    reps.append(rep)
    try:
        (_dir() / "reports.json").write_text(json.dumps(reps[-60:], ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    post("hq", "report", title=rep["title"], text=rep["text"][:4000], report=rep["id"])
    _push_alert("AI 사무실 · " + rep["title"], (rep["text"] or "").split("\n")[0][:140])
    return rep


def _load_reports() -> list:
    try:
        return json.loads((_dir() / "reports.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def reports() -> list:
    return list(reversed(_load_reports()))


# ------------------------------------------------------------------ 스케줄러
def _tick() -> None:
    if not CFG["enabled"]:
        return
    _reset_usage()
    now = time.time()
    if now - RT.get("last_obs", 0) > 20:                                   # 관찰 (코드만)
        RT["last_obs"] = now
        free = [a for a in roster.WATCH if not (RT["meeting"] and a in RT["meeting"]["order"])]
        if free:
            observe(random.choice(free))
    if now - ST["last_score"] > 600:                                         # 예측 채점 (마감된 것)
        ST["last_score"] = now
        score_forecasts()
    if paused():
        return
    _emergency()
    if CFG["auto"] and ai_ok() and not RT["meeting"] and not RT["queue"] and ST["usage"]["auto"] < CFG["daily_max"]:
        first = ST["first_start"] + 120
        if now >= first and now - ST["last_auto"] >= CFG["every"] * 60:
            ST["last_auto"] = now
            ag = roster.AGENDA[ST["agenda_i"] % len(roster.AGENDA)]
            ST["agenda_i"] += 1
            enqueue(ag["title"], ag["room"], ag["topic"], "auto", ag["agents"])
    if CFG["chat"] and now - ST["last_chat"] >= CFG["chat_every"] * 60 and not RT["meeting"]:
        ST["last_chat"] = now
        threading.Thread(target=chatter, daemon=True).start()
    if CFG["cycle"] and not RT["job"] and now - ST["last_cycle"] >= CFG["cycle_min"] * 60 and now - RT["started"] > 45:
        ST["last_cycle"] = now
        threading.Thread(target=cycle, daemon=True).start()
    if CFG.get("team_cycle") and not RT.get("team_job") and now - ST.get("last_team", 0) >= CFG.get("team_cycle_min", 4) * 60 and now - RT["started"] > 60:
        ST["last_team"] = now
        from . import teamjobs
        threading.Thread(target=teamjobs.team_cycle, daemon=True).start()
    if now - RT.get("last_live", 0) > 30:
        RT["last_live"] = now
        from .. import live as livex
        if livex.S.get("enabled"):
            from . import teamjobs
            ready = [x for x in teamjobs.live_items() if x["approved"] and x["price"]]
            if ready:
                threading.Thread(target=livex.sync, args=(ready,), daemon=True).start()
    if ai_ok() and now - (ST["last_report"] or ST["first_start"]) >= 3600:
        threading.Thread(target=report, daemon=True).start()
        ST["last_report"] = now


def _loop() -> None:
    while True:
        try:
            _tick()
            save()
        except Exception as e:  # noqa: BLE001
            try:
                post("hq", "system", text=f"사무실 스케줄 오류: {str(e)[:160]}")
            except Exception:  # noqa: BLE001
                pass
        time.sleep(5)


_started = {"v": False}


def start() -> None:
    load()
    if _started["v"]:
        return
    _started["v"] = True
    threading.Thread(target=_runner, daemon=True, name="office-runner").start()
    threading.Thread(target=_loop, daemon=True, name="office-loop").start()


# ------------------------------------------------------------------ 화면용
def snapshot_state(since: int = 0) -> dict:
    _reset_usage()
    m = RT["meeting"]
    now = time.time()
    agents = {aid: {"bubble": v["bubble"], "busy": v.get("busy", False)} for aid, v in RT["agents"].items() if v["until"] > now}
    with _lock:
        new = [e for e in LOG if e["id"] > since or e.get("u", 0) > since]
    nxt_auto = max(0, int((ST["last_auto"] + CFG["every"] * 60 - now) / 60)) if CFG["auto"] else None
    return {"now": now, "cursor": _next["id"] - 1, "log": new[-300:], "cfg": CFG, "usage": ST["usage"], "ai": ai_ok(),
            "paused": max(0, int(RT["paused_until"] - now)), "job": RT["job"], "job_ko": JOB_KO.get(RT["job"] or ""),
            "next_job": JOB_KO.get(JOBS[ST["job_i"] % len(JOBS)]), "next_auto_min": nxt_auto,
            "meeting": None if not m else {"id": m["id"], "name": m["name"], "room": m["room"], "place": m["place"], "order": m["order"],
                                           "done": m["done"], "speaking": m.get("speaking"), "trigger": m["trigger"]},
            "queue": len(RT["queue"]), "agents": agents, "huddle": RT["huddle"] if RT["huddle"] and RT["huddle"]["until"] > now else None,
            "presenting": RT["presenting"] if RT["presenting"] and RT["presenting"]["until"] > now else None,
            "board": board(), "forecast": forecast_score(), "backlog_open": sum(1 for b in ST["backlog"] if b["status"] != "done"),
            "team_job": RT.get("team_job"), "pipe": _pipe_counts()}


def _pipe_counts() -> dict:
    out: dict = {}
    for p in ST.get("pipeline", []):
        k = ("c_" if p["custom"] else "") + p["stage"]
        out[k] = out.get(k, 0) + 1
    return out


def roster_view() -> dict:
    from .. import ai_routes, keyring
    return {"teams": roster.TEAMS, "agents": [{**a, "tools": roster.tools_for(a["id"]), "seen": RT["seen"].get(a["id"], [])[-6:],
                                               "model": (assigned_routes(a["id"]) or [None])[0]} for a in roster.AGENTS],
            "models": CFG.get("models") or {}, "key_slots": keyring.view(), "suggest": ai_routes.view().get("suggest"),
            "agenda": [{"id": g["id"], "title": g["title"], "room": g["room"]} for g in roster.AGENDA], "jobs": JOB_KO, "closer": roster.CLOSER}


def run_agenda(aid: str) -> dict:
    ag = next((g for g in roster.AGENDA if g["id"] == aid), None)
    if not ag:
        raise ValueError("없는 안건입니다")
    if not ai_ok():
        raise ValueError("AI 키가 없어 회의를 열 수 없습니다")
    m = enqueue(ag["title"], ag["room"], ag["topic"], "auto", ag["agents"])
    return {"id": m["id"], "order": m["order"]}


def set_cfg(body: dict) -> dict:
    from .. import ai_routes
    for k, v in body.items():
        if k == "models":
            bad = [r for r in (v or {}).values() if r and not ai_routes.valid(r)]
            if bad:
                raise ValueError(f"모델 형식이 틀렸습니다: {', '.join(bad[:3])} ('공급자#키번호:모델' 예: nvidia#2:auto)")
            CFG["models"] = {kk: vv for kk, vv in (v or {}).items() if vv}
        elif k in DEFAULT_CFG:
            CFG[k] = type(DEFAULT_CFG[k])(v)
    if body.get("chat"):
        ST["last_chat"] = 0.0
    save(True)
    return CFG


def rate(entry_id: int, v: int) -> None:
    for e in LOG:
        if e["id"] == entry_id:
            update(e, rating=max(-1, min(1, int(v))))
            return


def clear_log() -> None:
    with _lock:
        LOG.clear()
    post("hq", "system", text="기록을 지웠습니다")
    save(True)


def backlog() -> list:
    return list(reversed(ST["backlog"]))
