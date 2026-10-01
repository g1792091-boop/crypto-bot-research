"""확장 팀의 업무 — 팀마다 코드가 자료를 모으고, 그 팀 팀원(전공 순서대로 돌아가며)이 해설한다. 몇 번에 한 번은 팀 회의.

매매법 파이프라인(ST["pipeline"]): stage = backtest(대기) → demo(데모거래) → candidate(실거래 승인 대기) → live(승인됨)
                                    / rejected(불통과) / retired(데모 퇴출). custom=True 면 커스텀 지표 팀들이 맡는다.
결과는 모두 사무실 결과 폴더(files/)에 파일로도 저장된다 (화면 '결과·다운로드' 에서 받기).
"""
from __future__ import annotations

import csv
import io
import json
import random
import re
import time
from datetime import datetime

from .. import live as livex
from ..data import market
from . import engine as E
from . import flow, org, quantlab, roster
from . import tools as T

PROMOTE = {"trades": 10, "pf": 1.2, "ret": 0.0, "dd": 25.0, "days": 2.0}
RETIRE = {"dd": 35.0, "trades": 20, "pf": 1.0}
DEMO_MAX = 16
TF_ROT = ["1h", "4h", "1h", "15m", "4h", "1d"]


def _st(key, default):
    return E.ST.setdefault(key, default)


def _member(team: str) -> str:
    """전공 순서대로 돌아가며 (팀장 제외)."""
    rot = _st("team_rot", {})
    i = rot.get(team, 0)
    rot[team] = i + 1
    mem = roster.MEMBERS[team]
    return mem[1 + i % (len(mem) - 1)]


def _coin(team: str) -> str:
    t = roster.TEAM_BY[team]
    if t.get("symbol"):
        return t["symbol"]
    rot = _st("coin_rot", {})
    i = rot.get(team, 0)
    rot[team] = i + 1
    return org.COINS[i % len(org.COINS)][0]


def _files():
    d = E._dir() / "files"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_analysis(team: str, title: str, body: str) -> None:
    d = _files() / "teams" / team
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f"{datetime.now():%Y-%m-%d}.md", "a", encoding="utf-8") as f:
        f.write(f"\n\n## {datetime.now():%H:%M} {title}\n\n{body}\n")


def _say(team: str, data: str, task: str, title: str, max_tokens: int = 900) -> None:
    """팀원 한 명이 자기 전공 관점으로 해설 (AI 없으면 자료만 남긴다)."""
    aid = _member(team)
    a = roster.BY_ID[aid]
    E.post(team, "work", agent=aid, icon="📊", text=title, src=roster.TEAM_BY[team]["name"])
    out = None
    if E.ai_ok():
        out = E.solo(aid, team, f"이번 일: {task} 너의 전공은 '{a.get('spec') or a['title']}'이니 그 관점에서 3~5문장으로 해설하고, 팀장이 쓸 결론 한 줄을 마지막에 '결론:'으로 쓴다.",
                     data[:5000], max_tokens)
    text = next((e.get("text") for e in reversed(E.LOG) if out and e["id"] == out["id"]), "") if out else ""
    save_analysis(team, title, f"### 자료\n```\n{data[:4000]}\n```\n\n### {a['name']} ({a['title']})\n{text or '(AI 없음 — 자료만 기록)'}")
    runs = _st("team_runs", {})
    runs[team] = runs.get(team, 0) + 1
    if E.ai_ok() and runs[team] % 4 == 0 and _team_meet_ok():
        m1, m2 = _member(team), _member(team)
        E.enqueue(f"{roster.TEAM_BY[team]['name']}-회의", team, f"{title} — 팀원들이 본 자료를 두고 결론과 다음 할 일을 정해 주세요.\n\n{data[:1500]}",
                  "auto", [m1, m2, roster.TEAM_LEAD[team]])


def _team_meet_ok() -> bool:
    u = E.ST["usage"]
    u.setdefault("team_meet", 0)
    if u["team_meet"] >= E.CFG.get("team_meet_max", 30):
        return False
    u["team_meet"] += 1
    return True


# ------------------------------------------------------------------ 분석 팀
def j_ind(team):
    sym, iv = _coin(team), TF_ROT[_st("ind_i", [0])[0] % len(TF_ROT)]
    E.ST["ind_i"][0] += 1
    c, _ = market.candles(sym, iv, 400)
    s = quantlab.snapshot(c)
    _say(team, f"{sym} {iv}\n{s['text']}\n\n[지표 값]\n{json.dumps(s['ind'], ensure_ascii=False, default=float)[:3000]}",
         "보조지표 29종 값을 보고 지금 차트 상태를 읽는다.", f"{sym.removesuffix('USDT')} {iv} 보조지표 29종")


def j_trend(team):
    from ..analysis import regime
    sym = _coin(team)
    rows = []
    for iv in ("15m", "1h", "4h", "1d", "1w"):
        try:
            c, _ = market.candles(sym, iv, 300)
            r = regime(c)
            rows.append(f"{iv}: {r['label']} (점수 {r['score']:+d}, 신뢰도 {r['confidence']}) — {' · '.join(r.get('reasons', [])[:3])}")
        except Exception as e:  # noqa: BLE001
            rows.append(f"{iv}: 실패 {str(e)[:60]}")
    _say(team, f"{sym} 여러 시간 프레임 추세\n" + "\n".join(rows), "여러 시간 프레임의 추세가 같은 방향인지, 어느 봉이 먼저 꺾이는지 판단한다.",
         f"{sym.removesuffix('USDT')} 다중 시간 프레임 추세")


def j_entry(team):
    from ..quant import entry
    sym = _coin(team)
    try:
        e = entry.entry(sym, "1h")
        txt = json.dumps({k: e[k] for k in e if k in ("verdict", "score", "parts", "plan", "levels", "summary")}, ensure_ascii=False, default=str)[:3500]
    except Exception as ex:  # noqa: BLE001
        txt = f"진입 분석 실패: {ex}"
    ob = flow.order_book(sym, 500)
    _say(team, f"{sym} 1h 진입 분석\n{txt}\n\n{ob.get('text', '')[:900]}", "지금 들어갈 만한 가격대(롱·숏)와 그 근거, 무효화 조건(손절)을 제시한다. 근거가 약하면 관망을 말한다.",
         f"{sym.removesuffix('USDT')} 진입 타점")


def j_news(team):
    from ..data import news, sentiment
    a, b = T.market_news("crypto"), T.market_news("regulation")
    try:
        cal = news.economic_calendar()["items"][:10]
        caltxt = "\n".join(f"- {x.get('date')} {x.get('title')} 예상 {x.get('forecast') or '-'} 이전 {x.get('previous') or '-'}" for x in cal)
    except Exception:  # noqa: BLE001
        caltxt = "(경제지표 일정을 가져오지 못함)"
    try:
        mac = sentiment.macro()["items"]
        mtxt = " · ".join(f"{x['name']} {x['last']:.2f} ({x['change_pct']:+.2f}%)" for x in mac if not x.get("error"))
    except Exception:  # noqa: BLE001
        mtxt = ""
    _say(team, f"[코인 뉴스]\n{a['text']}\n\n[규제]\n{b['text'][:1200]}\n\n[이번 주 미국 경제지표]\n{caltxt}\n\n[매크로] {mtxt}",
         "기사 제목을 나열하지 말고, 뉴스·경제지표·매크로를 묶어 코인에 어떤 의미인지 해설한다. 근거 문장 끝에만 [번호].", "뉴스·경제지표·매크로", 1100)


def j_sr(team):
    from ..analysis import sr_levels
    sym = _coin(team)
    rows = []
    for iv in ("1h", "4h", "1d"):
        try:
            c, _ = market.candles(sym, iv, 500)
            lv = sr_levels(c)
            rows.append(f"{iv} (현재 {lv['price']:,.6g}): " + ", ".join(f"{'저항' if z['side'] == 'resistance' else '지지'} {z['price']:,.6g} (터치 {z['touches']}, 강도 {z['strength']})" for z in lv["zones"])
                        + (" · " + " / ".join(x["label"] for x in lv["trendlines"]) if lv["trendlines"] else ""))
        except Exception as e:  # noqa: BLE001
            rows.append(f"{iv}: 실패 {str(e)[:60]}")
    lq = flow.liquidation_estimate(sym)
    _say(team, f"{sym} 지지·저항\n" + "\n".join(rows) + "\n\n" + lq.get("text", "")[:900], "가장 가까운 지지·저항과 돌파·이탈 시나리오를 판단한다.",
         f"{sym.removesuffix('USDT')} 지지저항")


def j_tpsl(team):
    lines = []
    for p in pipeline():
        b = E._paper.bots.get(p.get("bot_id")) if E._paper and p.get("bot_id") else None
        if b and b.sim.position and b.last_price:
            pos = b.sim.position
            stop_d = abs(b.last_price - pos.stop) / b.last_price * 100 if pos.stop else None
            liq_d = abs(b.last_price - pos.liq_price) / b.last_price * 100
            r = ((b.last_price - pos.entry_price) * pos.side / abs(pos.entry_price - pos.stop)) if pos.stop and pos.stop != pos.entry_price else None
            lines.append(f"- [{p['stage']}] {b.spec.name} {b.spec.symbol} {'롱' if pos.side == 1 else '숏'} 진입 {pos.entry_price:.6g} · 현재 {b.last_price:.6g} · "
                         f"손절 {pos.stop or '없음'}{f' ({stop_d:.2f}%)' if stop_d else ''} · 익절 {pos.take or '없음'} · 청산가까지 {liq_d:.1f}%" + (f" · {r:+.2f}R" if r is not None else ""))
    try:
        from .. import aibot
        for t in aibot.compute()["open"][:6]:
            lines.append(f"- [AI 시그널] {t['symbol']} {t['interval']} {'롱' if t['side'] == 'long' else '숏'} 진입 {t['entry']:.6g} · 손절 {t['stop']:.6g} · 익절 {t['take']:.6g} · 현재 {t.get('mark') or '-'}")
    except Exception:  # noqa: BLE001
        pass
    _say(team, "열린 가상·AI 포지션\n" + ("\n".join(lines) or "(열린 포지션 없음)"), "손절이 없거나 너무 넓은 포지션, 청산가가 가까운 포지션, 본절 이동·분할 익절 시점을 짚는다.", "포지션 익절·손절 점검")


def j_board(team):
    syms = [s for s, _, _ in org.COINS]
    try:
        tick = {r["symbol"]: r for r in market.tickers(syms)[0]}
    except Exception:  # noqa: BLE001
        tick = {}
    from ..analysis import regime
    rows, csvrows = [], [["symbol", "price", "change_24h", "funding_pct", "oi_usd", "rsi_1h", "trend_4h", "score_4h"]]
    for s in syms:
        t = tick.get(s, {})
        try:
            c1, _ = market.candles(s, "1h", 200)
            c4, _ = market.candles(s, "4h", 300)
            from .. import indicators as ind
            rsi = ind.rsi([b["close"] for b in c1], 14)[-1]
            rg = regime(c4)
        except Exception:  # noqa: BLE001
            rsi, rg = None, {"label": "-", "score": 0}
        fund = oi = None
        try:
            d = market.derivatives(s, "1h", 10)
            fund = (d.get("funding") or [{}])[-1].get("value")
            oi = (d.get("open_interest") or [{}])[-1].get("value")
        except Exception:  # noqa: BLE001
            pass
        rows.append(f"{s.removesuffix('USDT'):5} {t.get('price', 0):>12,.6g}  24h {t.get('change_pct', 0):+6.2f}%  펀딩 {fund if fund is not None else '-'}  RSI1h {rsi:.0f}  4h {rg['label']}({rg['score']:+d})" if rsi else f"{s}: 데이터 부족")
        csvrows.append([s, t.get("price"), t.get("change_pct"), fund, oi, round(rsi, 1) if rsi else None, rg["label"], rg["score"]])
    buf = io.StringIO()
    csv.writer(buf).writerows(csvrows)
    d = _files() / "boards"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{datetime.now():%Y-%m-%d_%H%M}.csv").write_text(buf.getvalue(), encoding="utf-8-sig")
    _say(team, "코인별 상황표\n" + "\n".join(rows), "코인들을 비교해 가장 강한·약한 코인, 펀딩·추세가 엇갈리는 코인을 짚는다.", "코인별 상황표")


def j_pattern(team):
    from ..quant import candles
    sym, iv = _coin(team), random.choice(["1h", "4h"])
    c, _ = market.candles(sym, iv, 1500)
    r = candles.analyze(c)
    _say(team, f"{sym} {iv} ({len(c)}봉)\n{r['text']}", "찾은 패턴이 이 코인 과거에서 실제로 통했는지(통계)를 근거로 말한다. 30번 미만이면 패턴이라 부르지 않는다.",
         f"{sym.removesuffix('USDT')} {iv} 차트·캔들 패턴")


def j_coin(team):
    from ..analysis import regime, sr_levels
    from ..quant import candles
    sym = roster.TEAM_BY[team]["symbol"]
    aid = roster.MEMBERS[team][1 + _st("team_rot", {}).get(team, 0) % 10]
    spec = roster.BY_ID[aid].get("spec") or ""
    parts = []
    try:
        c, _ = market.candles(sym, "1h", 500)
        rg = regime(c)
        parts.append(f"1시간 시장 판단: {rg['label']} (점수 {rg['score']:+d}) — {' · '.join(rg.get('reasons', [])[:3])}")
        if spec in ("차트·추세", "진입 타점", "익절손절", "리스크"):
            parts.append(quantlab.snapshot(c[-400:])["text"])
        if spec in ("지지저항", "진입 타점", "익절손절"):
            lv = sr_levels(c)
            parts.append("지지저항: " + ", ".join(f"{'저항' if z['side'] == 'resistance' else '지지'} {z['price']:,.6g}" for z in lv["zones"]))
        if spec == "캔들 패턴":
            parts.append(candles.analyze(c)["text"])
    except Exception as e:  # noqa: BLE001
        parts.append(f"차트 실패: {e}")
    if spec in ("선물 수급", "리스크"):
        parts.append(flow.futures_flow(sym).get("text", ""))
    if spec == "고래·호가":
        parts.append(flow.whale_trades(sym).get("text", "") + "\n" + flow.order_book(sym).get("text", ""))
    if spec == "뉴스·이슈":
        parts.append(T.market_news("crypto", sym).get("text", ""))
    if spec == "심리·SNS":
        from . import media
        parts.append(media.sns_buzz(sym.removesuffix("USDT")).get("text", ""))
    _say(team, f"{sym} — {spec}\n" + "\n\n".join(p for p in parts if p), f"{roster.TEAM_BY[team]['name']}로서 {sym} 한 코인을 '{spec}' 관점에서 본다.",
         f"{sym.removesuffix('USDT')} {spec}")


# ------------------------------------------------------------------ 매매법 파이프라인
def pipeline() -> list[dict]:
    return _st("pipeline", [])


def pipe_add(spec, author: str, custom: bool, stage: str = "backtest", bt: dict | None = None, bot_id: str | None = None, origin: str = "dev") -> dict:
    p = {"id": f"p{int(time.time() * 1000)}{random.randint(10, 99)}", "name": spec.name, "spec": spec.model_dump(), "custom": custom, "stage": stage,
         "author": author, "origin": origin, "created": time.time(), "bt": bt, "bot_id": bot_id, "history": [{"t": time.time(), "stage": stage}]}
    pipeline().append(p)
    del pipeline()[:-300]
    return p


def _move(p: dict, stage: str, why: str = "") -> None:
    p["stage"] = stage
    p["history"].append({"t": time.time(), "stage": stage, "why": why})


def _queue_dir(custom: bool):
    return "cbt" if custom else "bt"


CUSTOM_TEMPLATES = [
    ("변동성 조정 모멘텀", "(close - close[20]) / (ind(\"atr\",{length:14}) * sqrt(20))", "1", "-1"),
    ("Z점수 평균회귀", "zscore(close, 50)", "-2", "2"),
    ("거래량 충격 방향", "zscore(log(volume), 50) * sign(close - open)", "2", "-2"),
    ("추세 강도 종합", "(sign(close - ema(close,50)) + sign(ema(close,20) - ema(close,50)) + (ind(\"adx\",{length:14},\"adx\") > 25 ? sign(slope(close,20)) : 0)) / 3", "0.6", "-0.6"),
    ("회귀 기울기 정규화", "slope(close, 30) / ind(\"atr\",{length:14}) * 30", "1.5", "-1.5"),
    ("RSI·밴드 합성", "(ind(\"rsi\",{length:14}) - 50) / 50 + (close - ind(\"bb\",{length:20},\"middle\")) / (ind(\"bb\",{length:20},\"upper\") - ind(\"bb\",{length:20},\"middle\"))", "1.2", "-1.2"),
]


def _rule_strategy(sym: str, iv: str, custom: bool):
    """AI 가 없거나 실패하면 규칙으로 후보를 만든다 (오토파일럿 조합기 / 커스텀 지표 템플릿)."""
    from ..strategy import StrategySpec
    if custom:
        name, expr, hi, lo = random.choice(CUSTOM_TEMPLATES)
        mean_rev = name.startswith("Z점수")
        return StrategySpec.model_validate(E.normalize_spec({
            "name": f"커스텀 {name} {sym.removesuffix('USDT')} {iv}", "symbol": sym, "interval": iv,
            "indicators": [{"id": "cx", "type": "custom", "expr": expr}, {"id": "e200", "type": "ema", "length": 200}],
            "long_entry": {"logic": "all", "conditions": [{"left": "cx", "op": "crosses_below" if mean_rev else "crosses_above", "right": hi if not mean_rev else lo}]},
            "short_entry": {"logic": "all", "conditions": [{"left": "cx", "op": "crosses_above" if mean_rev else "crosses_below", "right": lo if not mean_rev else hi}]},
            "risk": {"leverage": 3, "atr_stop_mult": 2, "atr_tp_mult": 3}}))
    from .. import autopilot
    import random as _r
    inds = _r.sample(autopilot.DEFAULT_CHART + [{"key": "bb", "params": {}}, {"key": "adx", "params": {}}, {"key": "stoch", "params": {}}], 4)
    try:
        cands, _ = autopilot.candidates(sym, iv, inds, limit=60)
    except Exception:  # noqa: BLE001
        cands = []
    if not cands:
        return None
    sp = _r.choice(cands)
    return StrategySpec.model_validate(E.normalize_spec(sp.model_dump()))


def j_dev(team, custom: bool = False, note_: str | None = None):
    from ..knowledge import brief
    from ..nl_strategy import SYSTEM_PROMPT, _indicator_table
    from ..quant.customind import CUSTOM_DOC
    from ..strategy import StrategySpec
    sym, iv, mname = E.MARKETS[_st("dev_i", [0])[0] % len(E.MARKETS)]
    E.ST["dev_i"][0] += 1
    aid = _member(team)
    a = roster.BY_ID[aid]
    spec = None
    if E.ai_ok():
        c = market.candles(sym, iv, 400)[0]
        snap = quantlab.snapshot(c)
        tried = "\n".join(f"- {p['name']} ({p['spec']['symbol']} {p['spec']['interval']}): {p['stage']}" for p in pipeline()[-10:]) or "(없음)"
        sysp = (E.persona(aid, "이번 일은 새 매매법 개발이다. 전략 JSON 하나를 ```json 블록으로 쓰고, 블록 뒤에 왜 이 전략인지 2~3문장으로 말한다.")
                + "\n\n" + SYSTEM_PROMPT.format(indicator_table=_indicator_table())
                + f"\n- 너의 전공 '{a.get('spec')}' 관점으로 설계한다. 보조지표 29종 중 서로 다른 성격의 지표를 2~4개 조합한다."
                + "\n- 검증 관문: 앞 70% 학습 / 뒤 30% 검증 · 검증 구간 거래 20건 이상 · 손익비 1.2 이상 · 두 구간 모두 이익. 거래가 너무 드문 조건은 통과하지 못한다."
                + ("\n\n## 필수: 커스텀 지표\n{\"type\":\"custom\",\"expr\":\"수식\"} 지표를 최소 1개 직접 발명해서 조건의 핵심으로 쓴다.\n\n" + CUSTOM_DOC if custom else "")
                + (f"\n\n## 사용자 지시 (최우선)\n{note_}" if note_ else "")
                + "\n\n## 연구 카드\n" + brief(sym, iv))
        user = f"시장: {mname} ({sym}) · {iv}봉\n지금 차트:\n{snap['text']}\n\n최근 우리 파이프라인 전략(겹치지 않게):\n{tried}\n\nsymbol은 {sym}, interval은 {iv}."
        out = E.solo(aid, team, "", user, 1800, system=sysp)
        raw = E._extract_json(out["raw"]) if out else None
        if raw:
            try:
                spec = StrategySpec.model_validate(E.normalize_spec({**raw, "symbol": sym, "interval": iv}))
                if custom and not any(i.type == "custom" for i in spec.indicators):
                    E.post(team, "system", text=f"{a['name']}의 전략에 커스텀 지표가 없어 돌려보냅니다")
                    spec = None
            except Exception as e:  # noqa: BLE001
                E.post(team, "system", text=f"전략 형식 오류({a['name']}): {str(e)[:160]}")
    if spec is None:
        spec = _rule_strategy(sym, iv, custom)
        if spec:
            E.post(team, "work", agent=aid, icon="🧩", text=f"규칙 조합으로 후보 생성: {spec.name}")
    if not spec:
        return
    p = pipe_add(spec, aid, custom, "backtest", origin=team)
    E.post(team, "pipe", agent=aid, pid=p["id"], name=spec.name, stage="backtest", text=f"🧪 {spec.name} → {roster.TEAM_BY[_queue_dir(custom)]['name']}로 넘김")
    _export_pipeline()


def j_bt(team, custom: bool = False):
    todo = [p for p in pipeline() if p["stage"] == "backtest" and p["custom"] == custom][:2]
    if not todo:
        E.post(team, "work", agent=roster.TEAM_LEAD[team], icon="⏳", text="백테스트 대기 중인 매매법이 없습니다 — 개발팀 결과를 기다립니다")
        return
    from ..strategy import StrategySpec
    for p in todo:
        aid = _member(team)
        spec = StrategySpec.model_validate(p["spec"])
        E.bubble(aid, f"🧮 {spec.name} 전체 과거 백테스트 중", 120, True)
        try:
            c, hist = quantlab.history(spec.symbol, spec.interval)
            g = quantlab.gate(spec, c)
            sc = quantlab.scenarios(spec, c, sig=g["sig"])
        except Exception as e:  # noqa: BLE001
            _move(p, "rejected", f"백테스트 실패: {e}")
            E.post(team, "system", text=f"백테스트 실패({spec.name}): {str(e)[:160]}")
            continue
        p["bt"] = {"pass": g["pass"], "reasons": g["reasons"], "all": g["all"], "is": g["is"], "oos": g["oos"], "grade": sc.get("grade"), "hist": hist,
                   "scen": sc.get("text"), "t": time.time()}
        E.post(team, "bt", agent=aid, name=spec.name, market=spec.symbol, mname=spec.symbol, tf=spec.interval, hist=hist, all=g["all"], is_=g["is"], oos=g["oos"],
               **{"pass": g["pass"]}, reasons=g["reasons"], author=p["author"], spec=p["spec"], scen=sc.get("text"), grade=sc.get("grade"), lev=spec.risk.leverage, pid=p["id"])
        _save_bt(p)
        ok = g["pass"] and sc.get("grade") != "취약"
        _move(p, "demo" if ok else "rejected", " / ".join(g["reasons"][:2]) + f" · 시나리오 {sc.get('grade')}")
        nxt = "cdemo" if custom else "demo"
        E.post(team, "pipe", agent=aid, pid=p["id"], name=spec.name, stage=p["stage"],
               text=f"{'✅' if ok else '❌'} {spec.name} — {'통과 → ' + roster.TEAM_BY[nxt]['name'] + '로' if ok else '불통과'} ({sc.get('grade')})")
        if E.ai_ok():
            E.solo(aid, team, f"코드가 낸 백테스트·시나리오 결과를 너의 전공 '{roster.BY_ID[aid].get('spec')}' 관점에서 3~4문장으로 설명한다. 통과·불통과는 코드 판정을 따른다.",
                   f"{spec.name} ({spec.symbol} {spec.interval}) · {hist}\n판정: {'통과' if g['pass'] else '불통과'} — {' / '.join(g['reasons'])}\n\n{sc.get('text', '')}", 700)
    _export_pipeline()


def _bot_stats(b) -> dict:
    snap = b.sim.snapshot(b.last_price)
    eq = snap.get("equity", b.initial_equity)
    tr = b.sim.trades
    gw = sum(t.pnl for t in tr if t.pnl > 0)
    gl = -sum(t.pnl for t in tr if t.pnl <= 0)
    vals = [p["value"] for p in b.sim.equity_curve] or [b.initial_equity]
    peak, dd = vals[0], 0.0
    for v in vals:
        peak = max(peak, v)
        dd = max(dd, (peak - v) / peak * 100 if peak else 0)
    return {"trades": len(tr), "ret": round((eq / b.initial_equity - 1) * 100, 2), "pf": round(gw / gl, 2) if gl > 0 else (99.0 if tr else None),
            "dd": round(dd, 2), "days": round((time.time() - b.created) / 86400, 2), "win": round(sum(1 for t in tr if t.pnl > 0) / len(tr) * 100, 1) if tr else None,
            "pos": None if not b.sim.position else ("long" if b.sim.position.side == 1 else "short")}


def j_demo(team, custom: bool = False):
    from ..strategy import StrategySpec
    if not E._paper:
        return
    lines = []
    for p in [x for x in pipeline() if x["stage"] == "demo" and x["custom"] == custom]:
        if not p.get("bot_id") or p["bot_id"] not in E._paper.bots:
            active = [x for x in pipeline() if x["stage"] in ("demo", "candidate", "live") and x.get("bot_id") in E._paper.bots]
            if len(active) >= DEMO_MAX:
                continue
            bot = E._paper.add_bot(StrategySpec.model_validate(p["spec"]), 10_000.0)
            p["bot_id"] = bot.id
            E._paper.save()
            E.post(team, "pipe", agent=_member(team), pid=p["id"], name=p["name"], stage="demo", text=f"📗 데모거래 시작: {p['name']} (실제 시세 · 가상 10,000)")
            continue
        b = E._paper.bots[p["bot_id"]]
        s = _bot_stats(b)
        p["demo"] = s
        lines.append(f"- {p['name']}: 거래 {s['trades']} · 수익 {s['ret']:+.2f}% · 손익비 {s['pf']} · 낙폭 {s['dd']}% · {s['days']}일 · {s['pos'] or '무포지션'}")
        if s["dd"] > RETIRE["dd"] or (s["trades"] >= RETIRE["trades"] and (s["pf"] or 0) < RETIRE["pf"]):
            _move(p, "retired", f"데모 퇴출: 낙폭 {s['dd']}% / 손익비 {s['pf']}")
            E._paper.bots.pop(p["bot_id"], None)
            E.post(team, "pipe", agent=_member(team), pid=p["id"], name=p["name"], stage="retired", text=f"📕 데모 퇴출: {p['name']} — 낙폭 {s['dd']}% · 손익비 {s['pf']}")
        elif s["trades"] >= PROMOTE["trades"] and (s["pf"] or 0) >= PROMOTE["pf"] and s["ret"] > PROMOTE["ret"] and s["dd"] < PROMOTE["dd"] and s["days"] >= PROMOTE["days"]:
            _move(p, "candidate", f"데모 통과: 거래 {s['trades']} · 손익비 {s['pf']} · 수익 {s['ret']}%")
            nxt = "clive" if custom else "live"
            E.post(team, "pipe", agent=_member(team), pid=p["id"], name=p["name"], stage="candidate",
                   text=f"🏁 데모 통과 → {roster.TEAM_BY[nxt]['name']} 승인 대기: {p['name']} (거래 {s['trades']} · 손익비 {s['pf']} · 수익 {s['ret']:+.2f}%)")
            E._push_alert("실거래 승인 대기", f"{p['name']} 데모 통과 — 'AI 사무실 → 실거래' 에서 승인해야 실거래로 돌아갑니다")
    if lines:
        _say(team, "데모거래 현황 (승격 기준: 거래 10건 이상 · 손익비 1.2 · 수익 > 0 · 낙폭 25% 미만 · 2일 이상)\n" + "\n".join(lines),
             "데모 성과를 보고 승격·퇴출 판단의 근거를 설명한다. 표본이 적으면 판단을 미룬다.", "데모거래 현황")
    _export_pipeline()


def live_items() -> list[dict]:
    out = []
    for p in pipeline():
        if p["stage"] not in ("candidate", "live"):
            continue
        b = E._paper.bots.get(p.get("bot_id")) if E._paper and p.get("bot_id") else None
        side = 0
        if b and b.sim.position:
            side = 1 if b.sim.position.side == 1 else -1
        out.append({"id": p["id"], "name": p["name"], "symbol": p["spec"]["symbol"], "side": side, "price": b.last_price if b else None,
                    "leverage": p["spec"]["risk"].get("leverage", 1), "custom": p["custom"], "stage": p["stage"], "demo": p.get("demo"),
                    "approved": p["id"] in livex.S.get("approved", {})})
    return out


def j_live(team, custom: bool = False):
    items = [x for x in live_items() if x["custom"] == custom]
    for p in pipeline():
        if p["stage"] == "candidate" and p["id"] in livex.S.get("approved", {}):
            _move(p, "live", "사람 승인")
    ready = [x for x in items if x["approved"] and x["price"]]
    if ready and livex.S.get("enabled"):
        livex.sync(ready)
    v = livex.view()
    txt = (f"실거래 {'켜짐' if v['settings']['enabled'] else '꺼짐'} · {'테스트넷' if v['settings']['testnet'] else '실제 돈'} · 키 {'있음' if v['has_keys'] else '없음'}\n"
           f"한도: 주문 {v['settings']['max_order_usdt']} USDT · 전체 {v['settings']['max_total_usdt']} USDT · 레버리지 {v['settings']['max_leverage']}배 · 하루 손실 {v['settings']['daily_loss_usdt']} USDT\n"
           f"오늘 실현 손익(추정) {v['realized_today']} USDT\n승인 대기: " + (", ".join(x["name"] for x in items if not x["approved"]) or "없음")
           + "\n승인됨: " + (", ".join(f"{x['name']}({'롱' if x['side'] > 0 else '숏' if x['side'] < 0 else '대기'})" for x in items if x["approved"]) or "없음")
           + "\n최근 기록:\n" + "\n".join(f"- {datetime.fromtimestamp(l['t']):%m-%d %H:%M} {l['text']}" for l in v["log"][:8]))
    _say(team, txt, "실거래 상태·한도·승인 대기 목록을 점검하고 위험을 짚는다. 승인은 사람만 할 수 있다는 점을 분명히 한다.", "실거래 점검")


# ------------------------------------------------------------------ 결과 파일
def _save_bt(p: dict) -> None:
    d = _files() / "backtests"
    d.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", p["name"])[:50]
    (d / f"{datetime.now():%Y%m%d_%H%M}_{safe}.json").write_text(json.dumps({k: p[k] for k in ("id", "name", "spec", "bt", "stage", "author", "custom")},
                                                                         ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def _export_pipeline() -> None:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "name", "custom", "stage", "symbol", "interval", "author", "created", "bt_pass", "bt_grade", "oos_ret", "oos_pf", "oos_trades",
                "demo_trades", "demo_ret", "demo_pf", "demo_dd"])
    for p in pipeline():
        bt, dm = p.get("bt") or {}, p.get("demo") or {}
        w.writerow([p["id"], p["name"], p["custom"], p["stage"], p["spec"]["symbol"], p["spec"]["interval"], roster.BY_ID.get(p["author"], {}).get("name", p["author"]),
                    datetime.fromtimestamp(p["created"]).strftime("%Y-%m-%d %H:%M"), bt.get("pass"), bt.get("grade"), (bt.get("oos") or {}).get("ret"),
                    (bt.get("oos") or {}).get("pf"), (bt.get("oos") or {}).get("n"), dm.get("trades"), dm.get("ret"), dm.get("pf"), dm.get("dd")])
    (_files() / "pipeline.csv").write_text(buf.getvalue(), encoding="utf-8-sig")


# ------------------------------------------------------------------ 터미널 지표 추세·타점팀 (실시간)
TERM: dict = {}                 # symbol → 최근 판정 (화면·도구용)


def term_coins() -> list[str]:
    out = [s for s, _, _ in org.COINS]
    try:
        from .. import autopilot
        out += [x for x in (autopilot.context.get("watch") or []) if x not in out]
    except Exception:  # noqa: BLE001
        pass
    return out[:12]


def termind_scan(symbol: str, post_changes: bool = True) -> dict:
    """한 코인을 147개 지표 × 4개 봉으로 다시 판정. 추세가 바뀌거나 새 타점이 나오면 방·알림·차트 시그널로 알린다."""
    from ..quant import termind
    p = termind.plan(symbol)
    prev = TERM.get(symbol)
    TERM[symbol] = p
    _term_csv(p)
    if not post_changes:
        return p
    team = "termind"
    lead = roster.TEAM_LEAD[team]
    e = p.get("entry")
    changed_trend = prev is not None and prev["trend_label"] != p["trend_label"]
    new_entry = e and (not prev or not prev.get("entry") or prev["entry"]["action"] != e["action"] or abs(prev["entry"]["entry"] - e["entry"]) > 0.5 * abs(e["entry"] - e["stop"]))
    if changed_trend:
        E.post(team, "work", agent=_member(team), icon="🧭", text=f"{symbol.removesuffix('USDT')} 추세 바뀜: {prev['trend_label']} → {p['trend_label']} ({p['trend']:+d})", src="147개 지표 합의")
    if new_entry:
        E.post(team, "term", agent=lead, symbol=symbol, plan={k: p[k] for k in ("trend", "trend_label", "aligned", "side", "verdict", "entry", "price")},
               per_tf={iv: {"score": a["score"], "label": a["label"]} for iv, a in p["per_tf"].items()})
        E.bubble(lead, f"🎯 {symbol.removesuffix('USDT')} {('롱' if e['action'] == 'long' else '숏')} 타점! 손익비 {e['rr']}", 12)
        E._push_alert(f"터미널 지표 타점 · {symbol}", p["verdict"])
        try:                                                      # 트레이드 차트의 AI 시그널(보라 표시)·가상 체결 성과로
            from ..quant import copilot
            from ..data import market
            c, _ = market.candles(symbol, e["tf"], 50)
            copilot.record_signal({"symbol": symbol, "interval": e["tf"], "candles": c, "bar_time": c[-1]["time"], "price": p["price"], "atr": None},
                                  {"entry_idea": {"action": e["action"], "entry": e["entry"], "stop": e["stop"], "take": e["take"], "trigger": e["trigger"],
                                                  "reason": e["reason"]}, "confidence": e["confidence"], "headline": "터미널 지표 147종 합의 · " + p["verdict"]},
                                  "terminal", "보조지표 147종")
        except Exception:  # noqa: BLE001
            pass
        if E.ai_ok() and time.time() - _st("term_ai", [0])[0] > 300:
            E.ST["term_ai"][0] = time.time()
            from ..quant import termind as tm
            E.solo(roster.MEMBERS[team][10], team, "새 타점이 나왔다. 코드가 계산한 147개 지표 합의를 보고 이 타점의 근거와 위험(반대 표, 과열·침체, 장세)을 3~4문장으로 설명한다. 진입은 사람이 판단한다.",
                   tm.text(p), 700)
    return p


def _term_csv(p: dict) -> None:
    d = _files() / "termind"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{datetime.now():%Y-%m-%d}.csv"
    new = not f.exists()
    e = p.get("entry") or {}
    with open(f, "a", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["time", "symbol", "price", "trend", "label"] + [f"score_{iv}" for iv in p["per_tf"]] + ["side", "kind", "entry", "stop", "take", "rr", "confidence", "verdict"])
        w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), p["symbol"], p["price"], p["trend"], p["trend_label"]] + [a["score"] for a in p["per_tf"].values()]
                   + [e.get("action"), e.get("kind"), e.get("entry"), e.get("stop"), e.get("take"), e.get("rr"), e.get("confidence"), p.get("verdict")])


def termind_tick() -> None:
    """실시간: 한 번에 한 코인씩 돌아가며 (코인 6개면 약 6분에 전부 한 바퀴, 설정으로 조절)."""
    coins = term_coins()
    i = _st("term_i", [0])
    sym = coins[i[0] % len(coins)]
    i[0] += 1
    E.RT["term_job"] = sym
    try:
        termind_scan(sym)
    except Exception as e:  # noqa: BLE001
        E.post("termind", "system", text=f"{sym} 지표 계산 실패: {str(e)[:160]}")
    finally:
        E.RT["term_job"] = None


def j_termind(team):
    from ..quant import termind
    sym = _coin(team)
    p = TERM.get(sym) if TERM.get(sym) and time.time() - TERM[sym]["time"] < 600 else termind_scan(sym, post_changes=False)
    _say(team, termind.text(p), "차트 터미널의 보조지표 147종 합의를 너의 전공 관점에서 해설하고, 추세와 타점(또는 관망) 판단을 말한다. 반대 표가 많은 지표도 짚는다.",
         f"{sym.removesuffix('USDT')} 147개 지표 추세·타점", 1000)


KIND_FN = {"ind": j_ind, "trend": j_trend, "entry": j_entry, "news": j_news, "sr": j_sr, "tpsl": j_tpsl, "board": j_board, "pattern": j_pattern,
           "coinx": j_coin, "termind": j_termind, "dev": lambda t: j_dev(t, False), "cdev": lambda t: j_dev(t, True), "bt": lambda t: j_bt(t, t == "cbt"),
           "demo": lambda t: j_demo(t, t == "cdemo"), "live": lambda t: j_live(t, t == "clive")}


def run_team(team: str) -> None:
    t = roster.TEAM_BY[team]
    E.RT["team_job"] = team
    E.post(team, "work", agent=roster.TEAM_LEAD[team], icon="▶", text=f"{t['name']} 업무 시작")
    try:
        KIND_FN[t["kind"]](team)
    except Exception as e:  # noqa: BLE001
        E.post(team, "system", text=f"{t['name']} 업무 중 문제: {str(e)[:160]}")
    finally:
        E.RT["team_job"] = None
        E.save(True)


def ext_teams() -> list[str]:
    return [t["id"] for t in roster.TEAMS if t.get("ext")]


def team_cycle() -> None:
    """확장 팀을 차례로 돌린다 (파이프라인 팀은 더 자주)."""
    order = _st("team_order", [])
    if not order or set(ext_teams()) - set(order):               # 팀이 새로 생겼으면 순서를 다시 만든다
        order.clear()
        base = ext_teams()
        pipe = ["dev", "bt", "demo", "cdev", "cbt", "cdemo", "live", "clive"]
        order[:] = [x for pair in itertools_zip(base, pipe) for x in pair if x]
    i = _st("team_i", [0])
    team = order[i[0] % len(order)]
    i[0] += 1
    if team in roster.TEAM_BY:
        run_team(team)


def itertools_zip(a: list, b: list):
    from itertools import zip_longest
    bb = (b * (len(a) // max(1, len(b)) + 1))[:len(a)]
    return zip_longest(a, bb)
