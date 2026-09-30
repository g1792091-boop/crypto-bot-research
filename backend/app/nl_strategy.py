"""자연어 진입 기준 → StrategySpec.

ANTHROPIC_API_KEY 가 있으면 Claude 가 구조화 출력(JSON 스키마)으로 변환하고,
없으면 한국어/영어 키워드 규칙 파서로 흔한 패턴만 변환한다.
"""
from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from . import config, indicators, llm
from .strategy import Condition, ConditionGroup, IndicatorSpec, RiskSpec, StrategySpec, validate

SYSTEM_PROMPT = """당신은 코인 선물 퀀트 전략 엔지니어다. 사용자가 말로 설명한 진입/청산 기준을
백테스트 엔진이 실행할 수 있는 StrategySpec JSON 으로 정확히 옮긴다.

규칙
- indicators 에 필요한 지표를 선언하고, 조건식의 left/right 는 아래 문법만 쓴다.
  * 가격: open, high, low, close, volume, hl2, hlc3
  * 지표: "<id>" 또는 "<id>.<출력>" (출력 이름은 아래 표 참고)
  * 파생 데이터: funding(펀딩비 %, 0.01 = 0.01%), oi(미결제약정 USD), oi_change_pct(직전 봉 대비 OI 변화 %), long_short(롱/숏 계정비율)
  * 과거 값: "close[1]", "rsi[2]" 처럼 [n]
  * 숫자는 문자열로: "30"
  * 배수: "vol_ma*2", "bb.upper*1.005" 처럼 참조*숫자
- op: >, <, >=, <=, crosses_above, crosses_below, rising, falling (rising/falling 은 right 에 봉 수)
- 같은 그룹 안의 조건은 logic 이 all(AND) 또는 any(OR).
- 사용자가 방향을 한쪽만 말하면 그 방향만 채우고 나머지는 null.
  "양방향", "반대로 숏" 같은 표현이 있으면 대칭 조건으로 숏도 만든다.
- 손절/익절/레버리지/비중이 언급되면 risk 에 반영. 언급 없으면 기본값 유지
  (leverage 3, position_pct 20, fee_pct 0.04). 퍼센트는 가격 기준 %.
- symbol 은 바이낸스 USDT 무기한 심볼(BTCUSDT 등), interval 은 1m,5m,15m,30m,1h,4h,1d 중 하나.
- 모호한 부분은 가장 일반적인 트레이더 해석을 택하고 description 에 가정을 한국어로 적는다.
- MACD 골든크로스 = macd.line crosses_above macd.signal. 슈퍼트렌드 상승전환 = st.trend crosses_above 0.

지표 표 (type: 출력들 / 파라미터 기본값)
{indicator_table}
"""


def _indicator_table() -> str:
    return "\n".join(f"- {k}: {', '.join(v['outputs'])} / {json.dumps(v['defaults'])} — {v['desc']}"
                     for k, v in indicators.REGISTRY.items())


def from_text(text: str, symbol: str | None = None, interval: str | None = None) -> tuple[StrategySpec, str]:
    """(spec, engine) 반환. engine 은 'claude' 또는 'rules'."""
    hint = ""
    if symbol or interval:
        hint = f"\n\n(기본값: symbol={symbol or 'BTCUSDT'}, interval={interval or '1h'} — 문장에 다른 값이 있으면 문장을 따른다)"
    if config.llm_enabled():
        spec = llm.parse(SYSTEM_PROMPT.format(indicator_table=_indicator_table()),
                         text + hint, StrategySpec, effort="high")
        problems = validate(spec)
        if problems:  # 한 번 더 고쳐 달라고 요청
            spec = llm.parse(SYSTEM_PROMPT.format(indicator_table=_indicator_table()),
                             f"{text}{hint}\n\n이전 변환 결과:\n{spec.model_dump_json()}\n\n"
                             f"검증 오류: {problems}\n오류를 고친 StrategySpec 을 다시 출력하라.",
                             StrategySpec, effort="high")
        return spec, "claude"
    spec = rule_parse(text, symbol, interval)
    return spec, "rules"


# ---------------------------------------------------------------------------
# 규칙 기반 파서 (API 키 없을 때)
# ---------------------------------------------------------------------------

_SYMBOLS = [
    (r"\b(btc|xbt)\b|비트", "BTCUSDT"), (r"\beth\b|이더", "ETHUSDT"), (r"\bsol\b|솔라나", "SOLUSDT"),
    (r"\bxrp\b|리플", "XRPUSDT"), (r"\bbnb\b|바낸", "BNBUSDT"), (r"\bdoge\b|도지", "DOGEUSDT"),
]
_INTERVALS = [
    (r"(?<!\d)15\s*m\b|(?<!\d)15분", "15m"), (r"(?<!\d)30\s*m\b|(?<!\d)30분", "30m"),
    (r"(?<!\d)5\s*m\b|(?<!\d)5분", "5m"), (r"(?<!\d)1\s*m\b|(?<!\d)1분", "1m"),
    (r"(?<!\d)4\s*h\b|(?<!\d)4시간", "4h"), (r"(?<!\d)1\s*h\b|(?<!\d)1시간|시간봉", "1h"),
    (r"(?<!\d)1\s*d\b|일봉|하루", "1d"),
]
_NUM = r"(\d+(?:\.\d+)?)"


def _find(pattern: str, t: str):
    m = re.search(pattern, t)
    return m.group(1) if m else None


def rule_parse(text: str, symbol: str | None = None, interval: str | None = None) -> StrategySpec:
    t = text.lower()
    sym = symbol or next((s for p, s in _SYMBOLS if re.search(p, t)), "BTCUSDT")
    iv = next((i for p, i in _INTERVALS if re.search(p, t)), interval or "1h")

    inds: dict[str, IndicatorSpec] = {}
    long_c: list[Condition] = []
    short_c: list[Condition] = []
    notes: list[str] = []

    def add(ind: IndicatorSpec):
        inds.setdefault(ind.id, ind)

    # 이동평균 크로스: "ema 20/50", "이평 9 21 골든크로스"
    m = re.search(r"(ema|sma|이평선?|이동평균선?)\s*(\d+)\s*(?:/|,|와|과|-|\s)\s*(\d+)", t)
    if m:
        kind = "sma" if m.group(1) == "sma" else "ema"
        a, b = sorted((int(m.group(2)), int(m.group(3))))
        add(IndicatorSpec(id="ma_fast", type=kind, length=a))
        add(IndicatorSpec(id="ma_slow", type=kind, length=b))
        long_c.append(Condition(left="ma_fast", op="crosses_above", right="ma_slow"))
        short_c.append(Condition(left="ma_fast", op="crosses_below", right="ma_slow"))
        notes.append(f"{kind.upper()} {a}/{b} 크로스")
    else:
        m = re.search(r"(ema|sma|이평선?|이동평균선?)\s*(\d+)\s*(위|이상|above|돌파)", t)
        if m:
            kind = "sma" if m.group(1) == "sma" else "ema"
            n = int(m.group(2))
            add(IndicatorSpec(id="ma_trend", type=kind, length=n))
            long_c.append(Condition(left="close", op=">", right="ma_trend"))
            short_c.append(Condition(left="close", op="<", right="ma_trend"))
            notes.append(f"{kind.upper()}{n} 추세 필터")

    # RSI
    if "rsi" in t:
        n = int(_find(r"rsi\s*\(?\s*(\d+)\s*\)?\s*(?:기간|period)", t) or 14)
        add(IndicatorSpec(id="rsi", type="rsi", length=n))
        lo = _find(r"rsi[^0-9]{0,12}" + _NUM + r"\s*(?:이하|아래|미만|밑|below|<)", t)
        hi = _find(r"rsi[^0-9]{0,12}" + _NUM + r"\s*(?:이상|위|초과|above|>)", t)
        cross = bool(re.search(r"(돌파|회복|반등|cross)", t))
        if lo:
            op = "crosses_above" if cross else "<"
            long_c.append(Condition(left="rsi", op=op, right=lo))
            short_c.append(Condition(left="rsi", op="crosses_below" if cross else ">",
                                     right=f"{100 - float(lo):g}"))
            notes.append(f"RSI {lo} 과매도 롱")
        excl = re.search(r"rsi[^.,]{0,20}(제외|아닐|말고|피하|빼고)", t)
        if hi and excl:
            long_c.append(Condition(left="rsi", op="<", right=hi))
            short_c.append(Condition(left="rsi", op=">", right=f"{100 - float(hi):g}"))
            notes.append(f"RSI {hi} 이상 롱 제외 필터")
        elif hi and not lo:
            short_c.append(Condition(left="rsi", op=">", right=hi))
            long_c.append(Condition(left="rsi", op="<", right=f"{100 - float(hi):g}"))
            notes.append(f"RSI {hi} 과매수 숏")
        if not lo and not hi:
            long_c.append(Condition(left="rsi", op="crosses_above", right="30"))
            short_c.append(Condition(left="rsi", op="crosses_below", right="70"))

    # MACD
    if "macd" in t:
        add(IndicatorSpec(id="macd", type="macd"))
        long_c.append(Condition(left="macd.line", op="crosses_above", right="macd.signal"))
        short_c.append(Condition(left="macd.line", op="crosses_below", right="macd.signal"))
        notes.append("MACD 시그널 크로스")

    # 볼린저
    if re.search(r"볼린저|bollinger|\bbb\b", t):
        add(IndicatorSpec(id="bb", type="bb"))
        if re.search(r"돌파|breakout|브레이크", t):
            long_c.append(Condition(left="close", op="crosses_above", right="bb.upper"))
            short_c.append(Condition(left="close", op="crosses_below", right="bb.lower"))
            notes.append("볼린저 밴드 돌파")
        else:
            long_c.append(Condition(left="close", op="<", right="bb.lower"))
            short_c.append(Condition(left="close", op=">", right="bb.upper"))
            notes.append("볼린저 밴드 역추세")

    # 슈퍼트렌드
    if re.search(r"슈퍼\s*트렌드|supertrend", t):
        add(IndicatorSpec(id="st", type="supertrend"))
        long_c.append(Condition(left="st.trend", op="crosses_above", right="0"))
        short_c.append(Condition(left="st.trend", op="crosses_below", right="0"))
        notes.append("슈퍼트렌드 전환")

    # 거래량 급증
    vm = _find(r"거래량[^0-9]{0,10}" + _NUM + r"\s*배", t)
    if vm:
        add(IndicatorSpec(id="vol_ma", type="volume_sma", length=20))
        cond = Condition(left="volume", op=">", right=f"vol_ma*{vm}")
        long_c.append(cond); short_c.append(cond)
        notes.append(f"거래량 20봉 평균 {vm}배 이상")

    # 파생 데이터 필터
    if re.search(r"펀딩[^.]{0,8}(음수|마이너스|negative)", t):
        long_c.append(Condition(left="funding", op="<", right="0"))
        notes.append("펀딩비 음수일 때만 롱")
    if re.search(r"펀딩[^.]{0,8}(양수|플러스|과열|positive)", t):
        short_c.append(Condition(left="funding", op=">", right="0.01"))
        notes.append("펀딩비 과열 시 숏")
    if re.search(r"(oi|미결제)[^.]{0,8}(증가|상승|늘)", t):
        long_c.append(Condition(left="oi_change_pct", op=">", right="0"))
        short_c.append(Condition(left="oi_change_pct", op=">", right="0"))
        notes.append("OI 증가 동반")

    if not long_c and not short_c:
        raise ValueError("규칙 파서가 이해한 조건이 없습니다. 예: 'BTC 1시간봉 EMA 20/50 골든크로스 롱, "
                         "RSI 70 이상이면 제외, 손절 2% 익절 4%, 레버리지 5배'. "
                         "복잡한 문장은 ANTHROPIC_API_KEY 를 설정하면 Claude 가 변환합니다.")

    only_long = bool(re.search(r"롱만|롱 전용|long only|매수만", t))
    only_short = bool(re.search(r"숏만|숏 전용|short only|매도만", t))
    risk = RiskSpec(
        leverage=float(_find(r"(?:레버리지|leverage)[^0-9]{0,6}" + _NUM, t)
                       or _find(_NUM + r"\s*(?:배|x\b)", re.sub(r"거래량[^0-9]{0,10}\d+(?:\.\d+)?\s*배", "", t))
                       or 3),
        stop_loss_pct=float(v) if (v := _find(r"(?:손절|stop\s*loss|sl)[^0-9]{0,6}" + _NUM, t)) else None,
        take_profit_pct=float(v) if (v := _find(r"(?:익절|take\s*profit|tp)[^0-9]{0,6}" + _NUM, t)) else None,
        trailing_stop_pct=float(v) if (v := _find(r"(?:트레일링|추적\s*손절|trailing)[^0-9]{0,6}" + _NUM, t)) else None,
        position_pct=float(_find(r"(?:비중|증거금|자본)[^0-9]{0,6}" + _NUM, t) or 20),
    )
    return StrategySpec(
        name=" + ".join(notes) or "규칙 전략",
        description=f"규칙 파서 변환: {text.strip()}",
        symbol=sym, interval=iv,
        indicators=list(inds.values()),
        long_entry=None if only_short or not long_c else ConditionGroup(logic="all", conditions=long_c),
        short_entry=None if only_long or not short_c else ConditionGroup(logic="all", conditions=short_c),
        risk=risk,
    )


# ---------------------------------------------------------------------------
# 대화로 전략 고치기
# ---------------------------------------------------------------------------

class Revision(BaseModel):
    spec: StrategySpec
    changes: list[str] = Field(description="바꾼 내용 목록 (한국어, 짧게)")
    reply: str = Field(description="사용자에게 하는 답변 2~4문장 (한국어). 무엇을 왜 바꿨는지, 주의점")


REFINE_PROMPT = SYSTEM_PROMPT + """
지금은 이미 만들어진 전략을 사용자와 대화하며 고치는 중이다.
- 사용자의 요청만 반영하고, 요청하지 않은 부분은 그대로 둔다.
- 사용자가 "손실이 많다", "진입이 너무 잦다" 처럼 문제만 말하면, 직전 백테스트 결과를 참고해
  가장 그럴듯한 원인 한두 가지를 고치고 무엇을 왜 바꿨는지 설명한다.
- 지표 id 는 기존 것을 재사용하고, 새 지표는 겹치지 않는 id 를 쓴다.
"""

IMPROVE_WORDS = ("자동 개선", "알아서", "보완", "개선해", "최적화", "손실 줄", "고쳐줘")
_KIND = [  # (정규식, 지표 type 들, 이름)
    (r"rsi", ("rsi",), "RSI"), (r"macd", ("macd",), "MACD"), (r"볼린저|bollinger|\bbb\b", ("bb",), "볼린저"),
    (r"ema|sma|이평|이동평균", ("ema", "sma"), "이동평균"), (r"슈퍼\s*트렌드|supertrend", ("supertrend",), "슈퍼트렌드"),
    (r"거래량|volume", ("volume_sma",), "거래량"), (r"adx", ("adx",), "ADX"), (r"스토캐|stoch", ("stoch",), "스토캐스틱"),
]


def wants_improve(message: str) -> bool:
    return any(w in message for w in IMPROVE_WORDS)


def refine(spec: StrategySpec, message: str, history: list[dict] | None = None,
           metrics: dict | None = None) -> tuple[StrategySpec, list[str], str, str]:
    """(새 전략, 변경 목록, 답변, 엔진)."""
    if config.llm_enabled():
        convo = "\n".join(f"{h.get('role')}: {h.get('text')}" for h in (history or [])[-8:])
        user = (f"현재 전략 JSON:\n{spec.model_dump_json()}\n\n직전 백테스트 결과:\n{json.dumps(metrics or {}, ensure_ascii=False)}\n\n"
                f"지금까지 대화:\n{convo}\n\n사용자 요청: {message}")
        rev = llm.parse(REFINE_PROMPT.format(indicator_table=_indicator_table()), user, Revision, effort="high")
        problems = validate(rev.spec)
        if problems:
            rev = llm.parse(REFINE_PROMPT.format(indicator_table=_indicator_table()),
                            user + f"\n\n직전 수정안:\n{rev.spec.model_dump_json()}\n검증 오류: {problems}\n오류를 고친 수정안을 다시 내라.",
                            Revision, effort="high")
        return rev.spec, rev.changes, rev.reply, "claude"
    new, changes = rule_edit(spec, message)
    if not changes:
        reply = ("어떤 부분을 바꿀지 이해하지 못했습니다. 예: '손절 3%로', '레버리지 10배', 'RSI 조건 빼줘', "
                 "'MACD 골든크로스도 추가', '롱만', '4시간봉으로', '알아서 개선해줘'. "
                 "복잡한 요청은 ANTHROPIC_API_KEY 를 넣으면 Claude가 처리합니다.")
    else:
        reply = "반영했습니다: " + " / ".join(changes)
    return new, changes, reply, "rules"


def rule_edit(spec: StrategySpec, message: str) -> tuple[StrategySpec, list[str]]:
    import copy
    s = copy.deepcopy(spec)
    t = message.lower()
    ch: list[str] = []
    removing = bool(re.search(r"빼|제거|삭제|없애|지워|말고", t))

    # 리스크 숫자
    for pat, field, label in ((r"(?:손절|stop)[^0-9]{0,8}" + _NUM, "stop_loss_pct", "손절 %"),
                              (r"(?:익절|목표|take)[^0-9]{0,8}" + _NUM, "take_profit_pct", "익절 %"),
                              (r"(?:트레일링|추적\s*손절)[^0-9]{0,8}" + _NUM, "trailing_stop_pct", "추적손절 %"),
                              (r"(?:비중|증거금)[^0-9]{0,8}" + _NUM, "position_pct", "증거금 비중 %")):
        v = _find(pat, t)
        if v:
            setattr(s.risk, field, float(v)); ch.append(f"{label} → {v}")
    lev = _find(r"(?:레버리지|leverage)[^0-9]{0,6}" + _NUM, t) or _find(_NUM + r"\s*배\s*(?:로|레버)", t)
    if lev:
        s.risk.leverage = float(lev); ch.append(f"레버리지 → {lev}배")
    for word, field, label in (("손절", "stop_loss_pct", "손절"), ("익절", "take_profit_pct", "익절"),
                               ("트레일링", "trailing_stop_pct", "추적손절")):
        if word in t and removing and not _find(word + r"[^0-9]{0,8}" + _NUM, t):
            setattr(s.risk, field, None); ch.append(f"{label} 제거")

    # 방향 · 봉 · 심볼
    if re.search(r"롱만|롱 전용|long only", t) and s.short_entry:
        s.short_entry = None; ch.append("숏 진입 끔 (롱만)")
    if re.search(r"숏만|숏 전용|short only", t) and s.long_entry:
        s.long_entry = None; ch.append("롱 진입 끔 (숏만)")
    iv = next((i for p, i in _INTERVALS if re.search(p, t)), None)
    if iv and iv != s.interval:
        s.interval = iv; ch.append(f"봉 → {iv}")
    sym = next((sy for p, sy in _SYMBOLS if re.search(p, t)), None)
    if sym and sym != s.symbol:
        s.symbol = sym; ch.append(f"심볼 → {sym}")

    # 지표 조건 빼기
    if removing:
        for pat, types, name in _KIND:
            if re.search(pat, t):
                ids = {i.id for i in s.indicators if i.type in types}
                if not ids:
                    continue
                refs = lambda c: bool({x.split(".")[0].split("[")[0].split("*")[0] for x in (c.left, c.right)} & ids)
                for g in ("long_entry", "short_entry", "long_exit", "short_exit"):
                    grp = getattr(s, g)
                    if grp:
                        grp.conditions = [c for c in grp.conditions if not refs(c)]
                        if not grp.conditions:
                            setattr(s, g, None)
                s.indicators = [i for i in s.indicators if i.id not in ids]
                ch.append(f"{name} 조건 제거")
    else:
        # 조건 추가: 규칙 파서로 해석되는 부분을 기존 전략에 덧붙인다
        try:
            add = rule_parse(message, s.symbol, s.interval)
        except ValueError:
            add = None
        if add and (add.long_entry or add.short_entry):
            rename = {}
            for i in add.indicators:
                same = next((x for x in s.indicators if x.type == i.type and x.params() == i.params()), None)
                if same:
                    rename[i.id] = same.id
                    continue
                new_id, n = i.id, 2
                while new_id in {x.id for x in s.indicators}:
                    new_id, n = f"{i.id}{n}", n + 1
                rename[i.id] = new_id
                s.indicators.append(i.model_copy(update={"id": new_id}))
            fix = lambda x: ".".join([rename.get(x.split(".")[0], x.split(".")[0])] + x.split(".")[1:]) if x else x
            for g in ("long_entry", "short_entry"):
                src, dst = getattr(add, g), getattr(s, g)
                if src and dst:
                    new = [Condition(left=fix(c.left), op=c.op, right=fix(c.right)) for c in src.conditions]
                    dst.conditions += new
                    ch.append(f"{'롱' if g == 'long_entry' else '숏'} 진입 조건 추가: " +
                              ", ".join(f"{c.left} {c.op} {c.right}" for c in new))
    return s, ch
