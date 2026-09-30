"""에이전트 팀 실행 — 파이프라인을 돌리며 대화를 채팅 메시지로 쌓는다 (화면이 실시간으로 읽음).

흐름(아침 계획 예): 코드가 데이터 수집 → 시장분석 5명(서로 모름) → 전략가 → 반론 검토관 → 리스크 책임자 → 팀장
- 에이전트마다 자기 입력(패킷 조각) + 지금까지의 대화(thread) 를 받고 JSON 하나로 답한다
- 코드가 근거·권한을 검사하고(checks.py), 통과한 답만 다음 사람이 본다. 버린 주장은 채팅에 '코드 검사' 로 표시
- AI 키가 없거나 AI 가 실패하면 같은 형식의 규칙 분석(rules.py)
- 사람이 채팅에 쓰면(@이름) 그 에이전트가 답한다. 기본은 팀장
- 결과: 오늘의 허용범위(전략가 ∩ 리스크, 좁히기만), 리스크 조치 권고, 후보 승인 — 적용은 사람이 버튼으로
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from datetime import datetime
from typing import Optional

from .. import config, llm
from ..data import market
from . import checks, packets, rules
from .roster import BY_ID, COMMON, PIPELINES, ROLES, SCHEMAS, TEAMS  # noqa: F401  (main 이 TEAMS·PIPELINES 를 씀)

_paper = None
_lock = threading.RLock()
runs: dict[str, "Run"] = {}
DEFAULT_SETTINGS = {
    "coins": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LTCUSDT", "BCHUSDT", "DOGEUSDT"],
    "auto": {"morning": True, "evening": True, "weekly": True, "emergency": True},
    "times": {"morning": "08:00", "evening": "22:00", "weekly": "SUN 21:00"},
    "bot_gate": False,                       # 켜면 페이퍼 봇이 오늘의 허용범위 밖 방향으로는 진입하지 않음 (코드 관문)
    "daily_call_limit": 150,                  # 하루 AI 호출 상한 (넘으면 규칙 분석)
    "rules": {"leverage": "1~20배 (모의)", "margin_pct": "계좌의 10~40%", "max_loss_per_trade_pct": 15,
              "note": "사람이 정한 한도. 에이전트는 평가만 하고 바꾸지 않음"},
}
settings: dict = json.loads(json.dumps(DEFAULT_SETTINGS))
_calls = {"day": "", "n": 0}
_state = {"plan": None, "last_auto": {}, "last_emergency": 0.0, "candidates": {}}


def _dir():
    d = config.STATE_DIR / "team"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_json(name, default):
    try:
        return json.loads((_dir() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save_json(name, data):
    try:
        (_dir() / name).write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    except OSError:
        pass


def bind(paper_manager) -> None:
    global _paper, settings
    _paper = paper_manager
    saved = _load_json("settings.json", {})
    for k, v in saved.items():
        if isinstance(v, dict) and isinstance(settings.get(k), dict):
            settings[k].update(v)
        elif k in settings:
            settings[k] = v
    _state["plan"] = _load_json("plan.json", None)
    for f in sorted(_dir().glob("run_*.json"))[-30:]:
        try:
            r = Run.from_dict(json.loads(f.read_text(encoding="utf-8")))
            runs[r.id] = r
        except (OSError, ValueError, KeyError):
            pass


def save_settings(**kw) -> dict:
    with _lock:
        for k, v in kw.items():
            if v is None or k not in settings:
                continue
            if isinstance(settings[k], dict) and isinstance(v, dict):
                settings[k].update(v)
            else:
                settings[k] = v
        _save_json("settings.json", settings)
    return settings


# ---------------------------------------------------------------- 지식 (관찰 메모 · 교훈 · 기각 · 채점)
def knowledge() -> dict:
    return _load_json("knowledge.json", {"memos": [], "lessons": [], "rejected": []})


def _save_knowledge(k):
    _save_json("knowledge.json", k)


def _predictions() -> list:
    return _load_json("predictions.json", [])


def scorecards() -> dict:
    """아침 판단(차트 분석가 bias, 전략가 허용 방향)을 24시간 뒤 실제 가격으로 채점."""
    preds, now, changed = _predictions(), time.time(), False
    for p in preds:
        if p.get("hit") is None and now - p["ts"] >= 86400:
            try:
                c, _ = market.candles(p["symbol"], "1h", 60)
                after = next((b for b in c if b["time"] >= p["ts"] + 86400), None)
                if after:
                    ret = after["close"] / p["price"] - 1
                    p["ret_pct"] = round(ret * 100, 3)
                    p["hit"] = (p["bias"] == "long" and ret > 0) or (p["bias"] == "short" and ret < 0)
                    changed = True
            except Exception:
                pass
    if changed:
        _save_json("predictions.json", preds[-2000:])
    out = {}
    for rid in ("chart", "strategist"):
        done = [p for p in preds if p["role"] == rid and p.get("hit") is not None and now - p["ts"] < 30 * 86400]
        out[rid] = {"n": len(done), "hits": sum(p["hit"] for p in done),
                    "hit_rate_pct": round(sum(p["hit"] for p in done) / len(done) * 100, 1) if done else None,
                    "status": "ok" if len(done) >= 30 else "insufficient", "window": "최근 30일, 24시간 뒤 방향"}
    return out


def _record_predictions(rid: str, rows: list[tuple[str, str]], market_sec: dict):
    preds = _predictions()
    ts = time.time()
    for sym, bias in rows:
        px = (market_sec.get(sym) or {}).get("price")
        if bias in ("long", "short") and px:
            preds.append({"ts": ts, "role": rid, "symbol": sym, "bias": bias, "price": px})
    _save_json("predictions.json", preds[-2000:])


# ---------------------------------------------------------------- 실행 기록 (채팅)
class Run:
    def __init__(self, pipeline: str, trigger: str = "사람"):
        self.id = datetime.now(packets.KST).strftime("%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        self.pipeline, self.trigger = pipeline, trigger
        self.title = PIPELINES[pipeline][0] if pipeline in PIPELINES else "팀 채팅"
        self.started, self.ended = time.time(), None
        self.status = "running"
        self.typing: list[str] = []
        self.messages: list[dict] = []
        self.results: dict = {}
        self.packet: dict = {}
        self.failed: list[str] = []
        self.engine = llm.provider() or "rules"

    def post(self, sender: str, text: str, kind: str = "message", data: Optional[dict] = None, to: Optional[list] = None, meta: Optional[dict] = None):
        with _lock:
            m = {"i": len(self.messages), "ts": time.time(), "from": sender, "kind": kind, "text": text,
                 "to": to or [], "data": data, "meta": meta or {}}
            self.messages.append(m)
        return m

    def view(self, since: int = 0) -> dict:
        return {"id": self.id, "pipeline": self.pipeline, "title": self.title, "trigger": self.trigger, "status": self.status,
                "started": self.started, "ended": self.ended, "typing": list(self.typing), "engine": self.engine,
                "messages": self.messages[since:], "total": len(self.messages), "failed": self.failed,
                "results": {k: v for k, v in self.results.items() if k in ("plan", "risk", "lead", "approvals", "candidates", "weights")}}

    def to_dict(self) -> dict:
        return {**self.view(), "results": self.results}

    @classmethod
    def from_dict(cls, d: dict) -> "Run":
        r = cls.__new__(cls)
        r.id, r.pipeline, r.trigger, r.title = d["id"], d["pipeline"], d.get("trigger", ""), d.get("title", "")
        r.started, r.ended, r.status = d["started"], d.get("ended"), d.get("status", "done")
        if r.status == "running":
            r.status = "stopped"
        r.typing, r.messages, r.results, r.failed = [], d.get("messages", []), d.get("results", {}), d.get("failed", [])
        r.packet, r.engine = {}, d.get("engine", "rules")
        return r

    def save(self):
        _save_json(f"run_{self.id}.json", self.to_dict())
        files = sorted(_dir().glob("run_*.json"))
        for f in files[:-40]:
            try:
                f.unlink()
            except OSError:
                pass


def roster() -> list[dict]:
    last: dict = {}
    for r in sorted(runs.values(), key=lambda x: x.started):
        for m in r.messages:
            if m["from"] in BY_ID:
                last[m["from"]] = m["ts"]
    sc = scorecards()
    return [{"id": r.rid, "name": r.name, "team": r.team, "team_name": TEAMS[r.team][0], "color": TEAMS[r.team][1], "emoji": r.emoji,
             "tier": r.tier, "model": _model_label(r.tier, r.rid), "duty": r.duty, "pipelines": [k for k, v in PIPELINES.items() if any(r.rid in st for st in v[2])],
             "last_active": last.get(r.rid), "scorecard": sc.get(r.rid)} for r in ROLES]


def _model_label(tier: str, rid: str | None = None) -> str:
    from .. import ai_routes
    c = ai_routes.chain("team_heavy" if tier == "opus" else "team_light", rid, tier)
    if not c:
        return "규칙 분석"
    p, m = ai_routes.split(c[0])
    if p == "nvidia" and m in ("auto", "auto-fast"):
        from .. import nvidia
        pick = nvidia.peek_auto(m == "auto-fast")
        return pick or "NVIDIA 자동"
    return "Gemini" if p == "gemini" and m == "auto" else m


# ---------------------------------------------------------------- 한 명 실행
def _budget_ok() -> bool:
    day = datetime.now(packets.KST).strftime("%Y-%m-%d")
    if _calls["day"] != day:
        _calls.update(day=day, n=0)
    return _calls["n"] < int(settings.get("daily_call_limit", 80))


def _thread(run: Run, n: int = 14) -> list[dict]:
    out = []
    for m in run.messages[-n:]:
        if m["kind"] in ("message", "human"):
            who = BY_ID[m["from"]].name if m["from"] in BY_ID else ("사람" if m["from"] == "human" else "코드")
            out.append({"from": who, "text": m["text"][:400]})
    return out


def _given(run: Run, role, extra: dict) -> dict:
    pk = {**run.packet, **extra, "thread": _thread(run)}
    g = packets.slice_for(pk, role.inputs)
    g["role"] = role.name
    return g


def _empty(clean: dict) -> bool:
    body = {k: v for k, v in clean.items() if k not in ("message", "headline", "data_gaps", "questions_for_humans")}
    return not (clean.get("message") or clean.get("headline")) and not any(body.values())


def call_role(run: Run, rid: str, extra: dict) -> Optional[dict]:
    role = BY_ID[rid]
    given = _given(run, role, extra)
    clean, problems, source, err = None, [], "rules", None
    if llm.provider() and _budget_ok():
        system = f"{COMMON}\n\n# 당신의 역할: {role.name} ({TEAMS[role.team][0]})\n{role.prompt}\n\n# 출력 형식 (JSON 객체 하나만)\n{SCHEMAS[role.kind]}"
        for attempt in range(2):
            try:
                _calls["n"] += 1
                data, txt, model = llm.json_call(system, json.dumps(given, ensure_ascii=False, default=str), role.tier, role=rid)
                clean, problems = checks.check(role.kind, data, given)
                if clean is not None and _empty(clean):          # 형식만 맞고 내용이 없는 답 (약한 모델에서 흔함) → 다시 / 규칙으로
                    clean, err = None, "내용 없는 답"
                    continue
                if clean is not None:
                    source = model
                    break
                err = f"형식 오류: {'; '.join(problems)[:120]}"
            except Exception as e:
                err = str(e)[:160]
                break
    if clean is None:
        if err:
            run.post("code", f"{role.name}: AI 실패 → 규칙 분석으로 대신합니다 ({err})", "system")
        clean, problems = checks.check(role.kind, rules.RULES[rid](given), given)
        source = "rules"
    if clean is None:
        run.failed.append(rid)
        run.post("code", f"{role.name}: 쓸 수 있는 답이 없어 건너뜁니다", "system")
        return None
    run.post(rid, clean.get("message") or clean.get("headline") or "", "message", data=clean,
             meta={"source": source, "dropped": problems, "tier": role.tier})
    if problems:
        run.post("code", f"코드 검사 — {role.name} 의 주장·항목 {len(problems)}개를 뺐습니다: " + "; ".join(problems[:3]), "check",
                 meta={"role": rid, "problems": problems})
    return clean


def _stage(run: Run, rids: tuple, extra_fn) -> dict:
    out = {}
    run.typing = list(rids)
    threads = []

    def one(rid):
        out[rid] = call_role(run, rid, extra_fn(rid))
    for rid in rids:
        t = threading.Thread(target=one, args=(rid,), daemon=True)
        t.start()
        threads.append(t)
        if llm.provider() == "gemini":
            t.join()                                     # 무료 등급 분당 한도 → 차례로
    for t in threads:
        t.join()
    run.typing = []
    return out


# ---------------------------------------------------------------- 데이터 수집
def _meta(kind: str) -> dict:
    return {"generated_kst": packets.kst(time.time()), "pipeline": kind, "coins": settings["coins"], "rules": settings["rules"],
            "min_n": packets.MIN_N, "mode": "paper (모의 계좌 · 페이퍼 봇)", "units": {"pct": "%", "roe": "증거금 대비 %"}}


def build_packet(kind: str, run: Run, extra: Optional[dict] = None) -> dict:
    extra = extra or {}
    coins = extra.get("coins") or settings["coins"]
    run.post("code", "데이터 수집 중…" + ("" if kind == "autopilot" else f" ({', '.join(c.replace('USDT', '') for c in coins)})"), "system")
    k = knowledge()
    pk: dict = {"meta": _meta(kind), "knowledge": {"lessons": k["lessons"][-12:], "rejected": k["rejected"][-12:],
                                                  "memos": k["memos"][-20:], "scorecards": scorecards()}}
    t0 = time.time()
    if kind in ("morning", "emergency", "weekly", "monitor"):
        pk["market"] = packets.market_section(coins)
    if kind == "monitor":
        pk["flow"] = packets.flow_section(coins)
    if kind == "morning":
        pk["flow"] = packets.flow_section(coins)
        pk["macro"] = packets.macro_section(coins)
        pk["news"] = packets.news_section()
        pk["analog"] = packets.analog_section(coins)
        pk["signals"] = packets.signals_section(coins)
    if _paper is not None:
        pk["book"] = packets.book_section(_paper, whatif=kind != "morning")
        pk["bots"] = packets.bots_section(_paper)
        pk["ops"] = packets.ops_section(_paper)
        if kind == "weekly":
            pk["synergy"] = packets.synergy_section(_paper)
    pk["plan"] = _state.get("plan")
    if extra.get("candidates"):
        pk["candidates"] = extra["candidates"]
    src = (pk.get("ops") or {}).get("data_source")
    run.post("code", f"데이터 준비 완료 ({time.time() - t0:.1f}초" + (", ⚠ 가상 데이터" if src == "synthetic" else "") + ")", "system",
             meta={"sections": [k for k in pk if k not in ("meta",)]})
    return pk


# ---------------------------------------------------------------- 후보 (주간): 수정안 · 새 가설 · 다른 코인/봉 탐색
GATE = {"min_test_trades": 20, "min_test_pf": 1.2}


def _gate_from_backtest(spec, bars=1500) -> dict:
    from .. import backtest
    from ..improve import TRAIN_SHARE, _score
    candles, _ = market.candles(spec.symbol, spec.interval, bars)
    deriv = market.derivatives(spec.symbol, spec.interval, 500) if backtest.needs_derivatives(spec) else None
    res = backtest.run(spec, candles, deriv)
    split = candles[int(len(candles) * TRAIN_SHARE)]["time"]
    tr = _score([t for t in res["trades"] if t["entry_time"] < split])
    te = _score([t for t in res["trades"] if t["entry_time"] >= split])
    ok = (te["trades"] >= GATE["min_test_trades"] and (te["profit_factor"] or 0) >= GATE["min_test_pf"]
          and te["net_pnl"] > 0 and tr["net_pnl"] > 0)
    why = "통과" if ok else ("검증 구간 거래 부족" if te["trades"] < GATE["min_test_trades"] else "검증 구간 손익비·손익 기준 미달")
    return {"passed": ok, "train": tr, "test": te, "test_trades": te["trades"], "reason": why,
            "rule": f"검증 구간(뒤 30%) 거래 {GATE['min_test_trades']}건 이상 · 손익비 {GATE['min_test_pf']} 이상 · 두 구간 모두 이익"}


def improve_candidates(run: Run) -> list[dict]:
    from ..improve import run_for
    out = []
    for b in list(_paper.bots.values())[:4] if _paper else []:
        try:
            rep = run_for(b.spec, 1500)
        except Exception as e:
            run.post("code", f"봇 {b.spec.name} 수정안 계산 실패: {str(e)[:80]}", "system")
            continue
        out.append({"id": f"imp:{b.id}", "kind": "improve", "target": b.spec.name, "bot_id": b.id, "changes": rep.get("changes") or [],
                    "gate": {"passed": bool(rep.get("applied")), "before": rep.get("baseline"), "after": rep.get("after"),
                             "test_trades": ((rep.get("after") or {}).get("test") or {}).get("trades"),
                             "reason": "검증 구간에서 개선" if rep.get("applied") else "검증 구간에서 나아지는 변경 없음"},
                    "spec": rep.get("spec") if rep.get("applied") else None})
    return out


def hypothesis_candidates(run: Run, hyps: list[dict]) -> list[dict]:
    from ..nl_strategy import from_text_safe
    out = []
    for i, h in enumerate(hyps[:3]):
        try:
            spec, how, _ = from_text_safe(h["rule"], h.get("symbol") or "BTCUSDT", h.get("interval") or "1h")
            gate = _gate_from_backtest(spec)
            out.append({"id": f"hyp:{i}", "kind": "hypothesis", "target": h.get("name") or f"가설 {i + 1}", "rule": h["rule"],
                        "symbol": spec.symbol, "interval": spec.interval, "gate": gate, "spec": spec.model_dump(), "parsed_by": how})
        except Exception as e:
            out.append({"id": f"hyp:{i}", "kind": "hypothesis", "target": h.get("name") or f"가설 {i + 1}", "rule": h.get("rule"),
                        "gate": {"passed": False, "reason": f"규칙을 읽지 못함: {str(e)[:80]}", "test_trades": 0}})
    return out


def scan_bots(run: Run) -> dict:
    from .. import backtest
    rows, tried = [], 0
    for b in list(_paper.bots.values())[:3] if _paper else []:
        for s in settings["coins"][:4]:
            for iv in ("15m", "1h", "4h"):
                tried += 1
                try:
                    spec = b.spec.model_copy(update={"symbol": s, "interval": iv})
                    m = backtest.run_live_data(spec, 1000, 10_000)["metrics"]
                    rows.append({"bot": b.spec.name, "symbol": s, "interval": iv, "return_pct": packets._r(m.get("total_return_pct"), 4),
                                 "trades": m.get("trades") or m.get("num_trades"), "profit_factor": packets._r(m.get("profit_factor"), 3)})
                except Exception:
                    pass
    rows.sort(key=lambda r: -(r["return_pct"] or -1e9))
    return {"tried": tried, "top": rows[:5], "note": "같은 기간 데이터로 여러 조합을 시험함 — 가장 좋은 것은 과대평가됨"}


# ---------------------------------------------------------------- 파이프라인
def _finish_plan(run: Run, strat: dict, risk_out: Optional[dict]):
    base = {a["symbol"]: a for a in strat.get("allowed", [])}
    final = {}
    decs = {d["symbol"]: d for d in (risk_out or {}).get("decisions", [])}
    for sym, a in base.items():
        d = decs.get(sym)
        dr = d["direction"] if d else a["direction"]
        if not checks.ALLOWS[dr] <= checks.ALLOWS[a["direction"]]:
            dr = a["direction"]
        final[sym] = {"direction": dr, "strategist": a["direction"], "reason": (d or a).get("reason", "")}
    plan = {"date": datetime.now(packets.KST).strftime("%Y-%m-%d"), "made": time.time(), "run_id": run.id, "allowed": final,
            "risk_level": (risk_out or {}).get("risk_level", "caution"), "actions": (risk_out or {}).get("actions", [])}
    _state["plan"] = plan
    _save_json("plan.json", plan)
    run.results["plan"] = plan
    txt = " · ".join(f"{s.replace('USDT', '')} {rules.NAME[v['direction']]}" for s, v in final.items())
    run.post("code", f"오늘의 허용범위 확정 (전략가 ∩ 리스크, 좁히기만): {txt}" + (" — 봇 관문 켜짐" if settings.get("bot_gate") else " — 봇 관문 꺼짐(참고용)"),
             "result", data={"plan": plan})


def run_pipeline(kind: str, trigger: str = "사람", extra: Optional[dict] = None) -> Run:
    run = Run(kind, trigger)
    runs[run.id] = run
    threading.Thread(target=_execute, args=(run, extra), daemon=True).start()
    return run


def _monitor_coins() -> list[str]:
    try:
        from .. import autopilot
        coins = [autopilot.context["symbol"]] + [m["symbol"] for m in autopilot.state["bots"].values()]
    except Exception:
        coins = []
    if _paper is not None:
        coins += list(_paper.manual.positions)
    return list(dict.fromkeys(coins))[:4] or settings["coins"][:2]


def _execute(run: Run, extra: Optional[dict] = None):
    kind = run.pipeline
    extra = dict(extra or {})
    if kind == "monitor" and not extra.get("coins"):
        extra["coins"] = _monitor_coins()
    try:
        run.post("code", f"[{run.title}] 시작 — {PIPELINES[kind][1]}" + ("" if llm.provider() else " (AI 키 없음 → 규칙 분석)"), "system")
        run.packet = build_packet(kind, run, extra)
        if kind == "autopilot":
            _keep_candidates(run, run.packet.get("candidates", []))
        res: dict = {"analysts": {}}
        stages = PIPELINES[kind][2]
        for rids in stages:
            if kind == "weekly" and rids[0] == "researcher":
                run.post("code", "주간 후보 준비: 봇 수정안 계산 · 여러 코인/봉 탐색", "system")
                run.packet["candidates"] = improve_candidates(run)
                run.packet["scan"] = scan_bots(run)
            if kind == "weekly" and rids[0] == "validator":
                hyps = (res.get("researcher") or {}).get("hypotheses") or []
                if hyps:
                    run.post("code", f"전략 연구원 가설 {len(hyps)}개를 파서로 읽고 70/30 백테스트 중…", "system")
                    run.packet["candidates"] = run.packet.get("candidates", []) + hypothesis_candidates(run, hyps)
                cands = run.packet.get("candidates", [])
                _keep_candidates(run, cands)
                run.post("code", f"코드 관문: 후보 {len(cands)}개 중 통과 {sum((c.get('gate') or {}).get('passed', False) for c in cands)}개 "
                                 f"({GATE['min_test_trades']}건·손익비 {GATE['min_test_pf']} 기준). 관문 탈락은 에이전트가 뒤집을 수 없습니다.", "system")

            def extra(rid):
                e = {"analysts": res["analysts"], "failed": run.failed}
                for k in ("strategist", "critic", "risk", "verdicts"):
                    if k in res:
                        e[k] = res[k]
                return e
            out = _stage(run, rids, extra)
            for rid, o in out.items():
                if o is None:
                    continue
                role = BY_ID[rid]
                if role.kind in ("analyst", "learning", "cio", "validator", "approver"):
                    res["analysts"][rid] = o
                if rid in ("strategist", "critic", "risk", "researcher"):
                    res[rid] = o
                if rid == "validator":
                    res["verdicts"] = o.get("verdicts", [])
                if rid == "approver":
                    run.results["approvals"] = o.get("approvals", [])
                if rid == "cio":
                    run.results["weights"] = o.get("weights", [])
                if rid == "lead":
                    run.results["lead"] = o
                if rid == "chart" and kind == "morning":
                    _record_predictions("chart", [(c["symbol"], c["bias"]) for c in o.get("calls", [])], run.packet.get("market", {}))
                if rid == "learning":
                    _apply_learning(run, o)
            if "risk" in rids and res.get("risk"):
                run.results["risk"] = res["risk"]
                if kind == "morning" and res.get("strategist"):
                    _finish_plan(run, res["strategist"], res["risk"])
                    _record_predictions("strategist", [(s, v["direction"]) for s, v in run.results["plan"]["allowed"].items()], run.packet.get("market", {}))
        if kind == "morning" and "plan" not in run.results and res.get("strategist"):
            _finish_plan(run, res["strategist"], None)
        run.status = "done"
        run.post("code", f"[{run.title}] 끝 · {len(run.messages)}개 메시지" + (f" · 실패 {', '.join(run.failed)}" if run.failed else ""), "system")
    except Exception as e:
        run.status = "error"
        run.post("code", f"오류로 중단: {str(e)[:200]}", "system")
    finally:
        run.typing = []
        run.ended = time.time()
        run.save()


def _keep_candidates(run: Run, cands: list[dict]) -> None:
    """후보를 결과에 남긴다. 전략(spec)도 따로 저장해서 앱을 다시 켜도 '페이퍼 봇으로 시작'이 된다."""
    run.results["candidates"] = [{k: v for k, v in c.items() if k != "spec"} for c in cands]
    run.results["cand_specs"] = {c["id"]: c["spec"] for c in cands if c.get("spec")}


def _apply_learning(run: Run, o: dict):
    k = knowledge()
    ids = {m["text"]: m for m in k["memos"]}
    for m in o.get("memos", []):
        if m["text"] in ids:
            ids[m["text"]]["seen"] = ids[m["text"]].get("seen", 1) + 1
            ids[m["text"]]["n"] = max(ids[m["text"]].get("n", 0), int(m.get("n") or 0))
        else:
            k["memos"].append({"id": "m" + uuid.uuid4().hex[:6], "text": m["text"], "n": int(m.get("n") or 0), "seen": 1,
                               "ts": time.time(), "run": run.id, "evidence": m.get("evidence", [])})
    promoted = []
    for p in o.get("promote", []):
        m = next((x for x in k["memos"] if x["id"] == p["memo_id"]), None)
        if not m:
            continue
        if m.get("n", 0) < packets.MIN_N or m.get("seen", 1) < 2:           # 코드 규칙: 표본 30 이상 · 두 번 이상 관찰
            run.post("code", f"교훈 승격 거부: '{m['text'][:50]}' — 표본 {m.get('n', 0)}건·관찰 {m.get('seen', 1)}회 (기준 30건·2회)", "check")
            continue
        k["memos"].remove(m)
        k["lessons"].append({**m, "id": "L" + m["id"][1:], "promoted": time.time(), "review_date": time.time() + 30 * 86400, "reason": p.get("reason", "")})
        promoted.append(m["text"])
    for e in o.get("expire", []):
        les = next((x for x in k["lessons"] if x["id"] == e["lesson_id"]), None)
        if les:
            k["lessons"].remove(les)
            k["rejected"].append({**les, "expired": time.time(), "reason": e.get("reason", "")})
    k["memos"] = k["memos"][-200:]
    _save_knowledge(k)
    if promoted:
        run.post("code", f"교훈 카드 등록 {len(promoted)}개: " + " / ".join(x[:40] for x in promoted), "result")


# ---------------------------------------------------------------- 사람이 채팅에 쓰기
def human_say(run_id: str, text: str) -> dict:
    run = runs.get(run_id)
    if run is None:
        raise ValueError("대화방이 없습니다.")
    run.post("human", text, "human")
    target = None
    for r in ROLES:
        if f"@{r.name}" in text or f"@{r.name.replace(' ', '')}" in text.replace(" ", ""):
            target = r
            break
    target = target or BY_ID["lead"]
    threading.Thread(target=_answer, args=(run, target, text), daemon=True).start()
    return {"ok": True, "to": target.rid}


ASK = ("사람(최종 권한자)이 채팅방에서 당신에게 질문했습니다. 입력의 thread(대화)·packet·당신의 역할 범위 안에서만 답합니다. "
       "모르는 것은 모른다고 합니다. 주문·한도 변경은 하지 않습니다. 출력은 JSON {\"message\": \"채팅 답변 (3~6문장)\", \"evidence\": [\"패킷.경로\"]}")


def _answer(run: Run, role, question: str):
    run.typing = [role.rid]
    try:
        if not llm.provider():
            run.post(role.rid, "AI 키가 없어 자유 질문에는 답할 수 없습니다. 위 대화의 규칙 분석을 참고하시고, settings.txt 에 NVIDIA·Gemini(무료) 또는 Claude 키를 넣어 주세요.",
                     "message", meta={"source": "rules"})
            return
        if not run.packet:
            run.packet = {"meta": _meta(run.pipeline), "plan": _state.get("plan")}
            if _paper is not None:
                run.packet.update(book=packets.book_section(_paper, whatif=False), bots=packets.bots_section(_paper))
        given = _given(run, role, {"analysts": {m["from"]: m["data"] for m in run.messages if m.get("data") and m["from"] in BY_ID}})
        given["question"] = question
        system = f"{COMMON}\n\n# 당신의 역할: {role.name}\n{role.prompt}\n\n{ASK}"
        _calls["n"] += 1
        data, txt, model = llm.json_call(system, json.dumps(given, ensure_ascii=False, default=str), role.tier, 2000, role=role.rid)
        msg = (data or {}).get("message") if isinstance(data, dict) else None
        ev = [p for p in ((data or {}).get("evidence") or []) if isinstance(p, str)] if isinstance(data, dict) else []
        bad = [p for p in ev if not checks.resolve(given, p)[0]]
        run.post(role.rid, msg or txt.strip()[:1500], "message", meta={"source": model, "reply_to": "human", "evidence": ev, "bad_evidence": bad})
    except Exception as e:
        run.post("code", f"{role.name} 답변 실패: {str(e)[:160]}", "system")
    finally:
        run.typing = []
        run.save()


def open_chat() -> Run:
    """파이프라인 없이 팀에게 바로 묻는 대화방."""
    run = Run("chat", "사람")
    run.status = "done"
    run.post("code", "팀 채팅방입니다. @이름 으로 부르면 그 에이전트가, 아니면 팀장이 답합니다.", "system")
    runs[run.id] = run
    run.save()
    return run


# ---------------------------------------------------------------- 사람이 적용 (최종 권한)
def apply(kind: str, **kw) -> dict:
    if _paper is None:
        raise ValueError("페이퍼 매니저 없음")
    if kind == "pause_all":
        for b in _paper.bots.values():
            b.running = False
        _paper.save()
        return {"ok": True, "msg": "모든 봇을 멈췄습니다."}
    if kind == "pause_bot":
        b = _find_bot(kw.get("target"))
        b.running = False
        _paper.save()
        return {"ok": True, "msg": f"봇 {b.spec.name} 을 멈췄습니다."}
    if kind == "resume_bot":
        b = _find_bot(kw.get("target"))
        b.running = True
        _paper.save()
        return {"ok": True, "msg": f"봇 {b.spec.name} 을 다시 켰습니다."}
    if kind == "candidate":
        run = runs.get(kw.get("run_id") or "")
        if not run:
            raise ValueError("이 회의 기록을 찾지 못했습니다. 에이전트 팀 화면을 새로고침한 뒤 다시 눌러 주세요.")
        cid = kw.get("candidate")
        c = next((x for x in (run.packet or {}).get("candidates", []) if x["id"] == cid), None) \
            or next((x for x in run.results.get("candidates") or [] if x["id"] == cid), None)
        if not c:
            raise ValueError(f"후보 {cid} 를 이 회의 기록에서 찾지 못했습니다.")
        spec_d = c.get("spec") or (run.results.get("cand_specs") or {}).get(cid)
        appr = next((a for a in (run.results.get("approvals") or []) if a["candidate"] == cid), None)
        approved = bool(appr and appr["decision"] == "approve" and (c.get("gate") or {}).get("passed"))
        from ..strategy import StrategySpec
        if c["kind"] == "improve":
            if not approved:
                raise ValueError("봇 수정안은 승인관이 승인하고 코드 관문을 통과한 것만 적용할 수 있습니다.")
            b = _paper.bots.get(c["bot_id"])
            if not b:
                raise ValueError("봇이 없습니다.")
            if not spec_d:
                raise ValueError("이 수정안의 전략 정보가 저장돼 있지 않습니다 (예전 버전 기록). 주간 검토를 다시 돌려 주세요.")
            new = StrategySpec(**spec_d)
            new.name = b.spec.name
            b.spec, b.sim.risk = new, new.risk
            b.versions.append({"time": int(time.time()), "reason": "에이전트 팀 승인: " + " / ".join(c.get("changes") or []), "spec": new.model_dump()})
            _paper.save()
            return {"ok": True, "msg": f"봇 {b.spec.name} 에 수정안을 적용했습니다."}
        if not approved and not kw.get("force"):
            raise ValueError("승인관이 승인하고 코드 관문을 통과한 가설이 아닙니다. 그래도 시험하려면 '관찰 봇으로 시험'을 누르세요 (모의 매매).")
        if spec_d:
            spec = StrategySpec(**spec_d)
        elif c.get("rule"):                         # 예전 기록 · 규칙을 못 읽었던 가설 → 규칙 문장을 다시 읽는다
            spec = _spec_from_rule(c["rule"], c.get("symbol"), c.get("interval"))
        else:
            raise ValueError("이 가설에는 매매 규칙이 없습니다.")
        spec.name = (f"팀 가설 · {c['target']}" if approved else f"팀 가설(미검증) · {c['target']}")[:40]
        b = _paper.add_bot(spec)
        return {"ok": True, "msg": f"새 페이퍼 봇 '{b.spec.name}' 을 시작했습니다." + ("" if approved else " 검증을 통과하지 않은 관찰용입니다 (모의 매매).")}
    if kind == "hypothesis":                        # 채팅에 올라온 가설 문장을 바로 시험
        rule = (kw.get("rule") or "").strip()
        if not rule:
            raise ValueError("가설 규칙이 비어 있습니다.")
        spec = _spec_from_rule(rule, kw.get("symbol"), kw.get("interval"))
        spec.name = f"팀 가설(미검증) · {kw.get('name') or rule[:20]}"[:40]
        b = _paper.add_bot(spec)
        return {"ok": True, "msg": f"새 페이퍼 봇 '{b.spec.name}' 을 시작했습니다 ({spec.symbol} {spec.interval}). 관문 검증 전인 관찰용입니다 (모의 매매)."}
    raise ValueError("알 수 없는 적용 종류")


def _spec_from_rule(rule: str, symbol: str | None, interval: str | None):
    from ..data import symbols
    from ..nl_strategy import from_text_safe
    from ..strategy import INTERVALS
    sym = symbols.resolve(symbol or "BTCUSDT")
    iv = interval if interval in INTERVALS else "1h"
    try:
        spec, _, _ = from_text_safe(rule, sym, iv)
    except Exception as e:
        raise ValueError(f"가설 규칙을 전략으로 읽지 못했습니다: {str(e)[:160]}") from e
    spec = spec.model_copy(update={"symbol": symbols.resolve(spec.symbol or sym)})
    market.candles(spec.symbol, spec.interval, 2)      # 없는 종목이면 여기서 오류
    return spec


def _find_bot(target):
    for b in _paper.bots.values():
        if target in (b.id, b.spec.name) or (target and str(target).startswith(b.spec.name)):
            return b
    raise ValueError(f"봇을 찾지 못했습니다: {target}")


def gate_allows(symbol: str, side: str) -> bool:
    """봇 관문: 켜져 있고 오늘 계획이 있으면 허용 방향만 통과. 계획이 없거나 오래됐으면(36시간) 통과."""
    if not settings.get("bot_gate"):
        return True
    plan = _state.get("plan")
    if not plan or time.time() - plan.get("made", 0) > 36 * 3600:
        return True
    row = (plan.get("allowed") or {}).get(symbol)
    if not row:
        return True
    return side in checks.ALLOWS[row["direction"]]


# ---------------------------------------------------------------- 자동 실행 · 긴급 복기
def _due(kind: str, now: datetime) -> bool:
    t = settings["times"][kind]
    if kind == "weekly":
        day, hm = t.split()
        if now.strftime("%a").upper()[:3] != day.upper()[:3]:
            return False
        t = hm
    hh, mm = map(int, t.split(":"))
    key = now.strftime("%Y-%m-%d")
    return (now.hour, now.minute) >= (hh, mm) and (now.hour * 60 + now.minute) - (hh * 60 + mm) < 60 and _state["last_auto"].get(kind) != key


def tick() -> Optional[Run]:
    now = datetime.now(packets.KST)
    for kind in ("morning", "evening", "weekly"):
        if settings["auto"].get(kind) and _due(kind, now) and not any(r.status == "running" for r in runs.values()):
            _state["last_auto"][kind] = now.strftime("%Y-%m-%d")
            return run_pipeline(kind, "자동 일정")
    if settings["auto"].get("emergency") and time.time() - _state["last_emergency"] > 3600 and _paper is not None:
        from ..quant import copilot
        hot = [a for a in copilot.alerts_feed if a["level"] == "high" and time.time() - a["created"] < 600]
        big = [t for t in _paper.manual.trades if t.exit_time > time.time() - 600 and (t.pnl_pct_on_margin <= -30 or t.exit_reason == "liquidation")]
        if (hot or big) and not any(r.status == "running" for r in runs.values()):
            _state["last_emergency"] = time.time()
            why = hot[0]["text"] if hot else f"큰 손실 {big[0].symbol} {big[0].pnl_pct_on_margin:.0f}%"
            return run_pipeline("emergency", f"긴급: {why[:60]}")
    return None


async def run_forever():
    while True:
        try:
            await asyncio.to_thread(tick)
        except Exception:
            pass
        await asyncio.sleep(30)


_task = None


def start():
    global _task
    if _task is None:
        _task = asyncio.create_task(run_forever())
