"""전략 DSL (JSON) 정의와 신호 계산.

자연어 → (Claude) → StrategySpec JSON → 백테스트 / 페이퍼 트레이딩.
사용자가 UI에서 지표를 조합해도 같은 JSON이 만들어진다.

조건식 피연산자(left/right) 문법:
  - 가격/거래량: open, high, low, close, volume, hl2, hlc3
  - 지표: "<id>" (출력 1개) 또는 "<id>.<출력>" (예: "macd.hist", "bb.lower", "st.trend")
  - 파생 데이터: funding (펀딩비 %), oi (미결제약정), oi_change_pct (직전 봉 대비 OI 변화율 %),
                long_short (롱/숏 계정 비율)
  - 과거 값: 뒤에 [n] (예: "close[1]", "rsi[2]")
  - 숫자: "30", "-0.01"
  - 배수: "<참조>*<숫자>" (예: "vol_ma*2", "bb.upper*1.005")
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from . import indicators as ind

IndicatorType = Literal[
    "sma", "ema", "rsi", "macd", "bb", "atr", "stoch", "supertrend", "adx",
    "cci", "vwap", "obv", "highest", "lowest", "volume_sma",
    "wma", "hma", "vwma", "mfi", "willr", "roc", "psar", "donchian", "keltner", "stochrsi", "ichimoku", "cmf", "aroon", "atr_stop", "ml",
]
Op = Literal[">", "<", ">=", "<=", "crosses_above", "crosses_below", "rising", "falling"]


class IndicatorSpec(BaseModel):
    id: str = Field(description="조건식에서 참조할 이름. 영문 소문자/숫자/_ (예: ema_fast, rsi, macd)")
    type: IndicatorType
    length: Optional[int] = None
    fast: Optional[int] = None
    slow: Optional[int] = None
    signal: Optional[int] = None
    mult: Optional[float] = None
    k_smooth: Optional[int] = None
    d_smooth: Optional[int] = None
    source: Optional[Literal["close", "open", "high", "low", "hl2", "hlc3", "ohlc4"]] = None
    model: Optional[Literal["logreg", "mlp", "gbs", "dnn", "cnn"]] = Field(None, description="type=ml 일 때 모델")
    horizon: Optional[int] = Field(None, description="type=ml 일 때 몇 봉 뒤 방향을 예측할지")

    def params(self) -> dict:
        return self.model_dump(exclude={"id", "type"}, exclude_none=True)


class Condition(BaseModel):
    left: str
    op: Op = Field(description="rising/falling 은 right 에 봉 개수를 넣는다 (left가 N봉 연속 상승/하락)")
    right: str


class ConditionGroup(BaseModel):
    logic: Literal["all", "any"] = "all"
    conditions: list[Condition]


class RiskSpec(BaseModel):
    leverage: float = Field(3, description="레버리지 배수")
    position_pct: float = Field(20, description="진입 시 증거금으로 쓰는 자본 비율 (%)")
    stop_loss_pct: Optional[float] = Field(None, description="진입가 대비 손절 % (가격 기준)")
    take_profit_pct: Optional[float] = Field(None, description="진입가 대비 익절 % (가격 기준)")
    atr_stop_mult: Optional[float] = Field(None, description="ATR(14) x 배수 손절")
    atr_tp_mult: Optional[float] = Field(None, description="ATR(14) x 배수 익절")
    trailing_stop_pct: Optional[float] = Field(None, description="고점(저점) 대비 추적 손절 %")
    fee_pct: float = Field(0.04, description="편도 수수료 % (바이낸스 테이커 0.04)")
    slippage_pct: float = Field(0.01, description="편도 슬리피지 %")
    funding_rate_8h_pct: float = Field(0.01, description="8시간당 가정 펀딩비 % (롱이 지불, 숏이 수령)")
    allow_reverse: bool = Field(True, description="반대 신호 시 즉시 스위칭")


class StrategySpec(BaseModel):
    name: str
    description: str = ""
    symbol: str = "BTCUSDT"
    interval: str = "1h"
    indicators: list[IndicatorSpec] = []
    long_entry: Optional[ConditionGroup] = None
    short_entry: Optional[ConditionGroup] = None
    long_exit: Optional[ConditionGroup] = None
    short_exit: Optional[ConditionGroup] = None
    risk: RiskSpec = RiskSpec()


# ---------------------------------------------------------------------------
# 신호 계산
# ---------------------------------------------------------------------------

_REF = re.compile(r"^([a-zA-Z_][\w.]*)(?:\[(\d+)\])?$")
PRICE_FIELDS = {"open", "high", "low", "close", "volume", "hl2", "hlc3", "ohlc4"}
DERIV_FIELDS = {"funding", "oi", "oi_change_pct", "long_short"}


def _align(candles: list[dict], points: list[dict]) -> list:
    """시간 순 (time, value) 포인트를 캔들 시간축에 forward-fill 로 맞춘다."""
    out, j, last = [], 0, None
    pts = sorted(points, key=lambda p: p["time"])
    for b in candles:
        while j < len(pts) and pts[j]["time"] <= b["time"]:
            last = pts[j]["value"]; j += 1
        out.append(last)
    return out


def build_series(spec: StrategySpec, candles: list[dict], deriv: dict | None = None) -> dict[str, list]:
    s: dict[str, list] = {}
    for f in PRICE_FIELDS:
        s[f] = ind._src(candles, f)
    for spec_i in spec.indicators:
        res = ind.compute(candles, spec_i.type, spec_i.params())
        for out_name, series in res.items():
            s[f"{spec_i.id}.{out_name}"] = series
        if len(res) == 1 or "value" in res:
            s[spec_i.id] = res.get("value", next(iter(res.values())))
        elif "line" in res:
            s[spec_i.id] = res["line"]
    s["__atr14"] = ind.atr(candles, 14)
    deriv = deriv or {}
    if deriv.get("funding"):
        s["funding"] = _align(candles, deriv["funding"])
    if deriv.get("long_short"):
        s["long_short"] = _align(candles, deriv["long_short"])
    if deriv.get("open_interest"):
        oi = _align(candles, deriv["open_interest"])
        s["oi"] = oi
        s["oi_change_pct"] = [None] + [
            (oi[i] - oi[i - 1]) / oi[i - 1] * 100 if oi[i] is not None and oi[i - 1] else None
            for i in range(1, len(oi))
        ]
    # 파생 데이터가 없으면 None 시리즈 → 해당 조건은 항상 거짓 (백테스트가 경고로 알려 줌)
    for f in DERIV_FIELDS:
        s.setdefault(f, [None] * len(candles))
    return s


def referenced_names(spec: StrategySpec) -> set[str]:
    names = set()
    for g in (spec.long_entry, spec.short_entry, spec.long_exit, spec.short_exit):
        if not g:
            continue
        for c in g.conditions:
            for side in (c.left, c.right):
                side = side.split("*", 1)[0]
                m = _REF.match(side.strip())
                if m and not _is_number(side):
                    names.add(m.group(1))
    return names


def _is_number(x: str) -> bool:
    try:
        float(x)
        return True
    except ValueError:
        return False


def _operand(series: dict[str, list], token: str, n: int) -> list:
    token = token.strip()
    if _is_number(token):
        return [float(token)] * n
    if "*" in token:
        ref, k = token.rsplit("*", 1)
        k = float(k)
        return [v * k if v is not None else None for v in _operand(series, ref, n)]
    m = _REF.match(token)
    if not m:
        raise ValueError(f"해석할 수 없는 피연산자: {token!r}")
    name, shift = m.group(1), int(m.group(2) or 0)
    if name not in series:
        raise ValueError(f"알 수 없는 시리즈: {name!r} (지표 id 또는 {sorted(PRICE_FIELDS | DERIV_FIELDS)})")
    base = series[name]
    return ([None] * shift + base[:-shift]) if shift else base


def _eval_condition(series: dict[str, list], c: Condition, n: int) -> list[bool]:
    a = _operand(series, c.left, n)
    out = [False] * n
    if c.op in ("rising", "falling"):
        k = max(1, int(float(c.right)))
        for i in range(k, n):
            w = a[i - k: i + 1]
            if any(v is None for v in w):
                continue
            pairs = zip(w, w[1:])
            out[i] = all(y > x for x, y in pairs) if c.op == "rising" else all(y < x for x, y in pairs)
        return out
    b = _operand(series, c.right, n)
    for i in range(n):
        x, y = a[i], b[i]
        if x is None or y is None:
            continue
        if c.op == ">":
            out[i] = x > y
        elif c.op == "<":
            out[i] = x < y
        elif c.op == ">=":
            out[i] = x >= y
        elif c.op == "<=":
            out[i] = x <= y
        elif i > 0 and a[i - 1] is not None and b[i - 1] is not None:
            if c.op == "crosses_above":
                out[i] = x > y and a[i - 1] <= b[i - 1]
            elif c.op == "crosses_below":
                out[i] = x < y and a[i - 1] >= b[i - 1]
    return out


def eval_group(series: dict[str, list], g: ConditionGroup | None, n: int) -> list[bool]:
    if not g or not g.conditions:
        return [False] * n
    parts = [_eval_condition(series, c, n) for c in g.conditions]
    if g.logic == "any":
        return [any(p[i] for p in parts) for i in range(n)]
    return [all(p[i] for p in parts) for i in range(n)]


def signals(spec: StrategySpec, candles: list[dict], deriv: dict | None = None) -> dict:
    n = len(candles)
    series = build_series(spec, candles, deriv)
    return {
        "long_entry": eval_group(series, spec.long_entry, n),
        "short_entry": eval_group(series, spec.short_entry, n),
        "long_exit": eval_group(series, spec.long_exit, n),
        "short_exit": eval_group(series, spec.short_exit, n),
        "atr": series["__atr14"],
        "series": series,
    }


# 전략(백테스트·페이퍼 봇)에 쓸 수 있는 봉 간격 — 1분봉부터 월봉까지
INTERVALS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "3d", "1w", "1M"]


def validate(spec: StrategySpec) -> list[str]:
    """실행 전 정적 검증. 문제 목록 반환 (빈 리스트면 OK)."""
    problems = []
    if not (spec.long_entry or spec.short_entry):
        problems.append("롱 또는 숏 진입 조건이 최소 1개 필요합니다.")
    ids = {i.id for i in spec.indicators}
    if len(ids) != len(spec.indicators):
        problems.append("지표 id가 중복됩니다.")
    known = set(PRICE_FIELDS) | DERIV_FIELDS | ids
    for i in spec.indicators:
        known |= {f"{i.id}.{o}" for o in ind.REGISTRY[i.type]["outputs"]}
    for name in referenced_names(spec):
        if name not in known:
            problems.append(f"조건식이 정의되지 않은 시리즈를 참조합니다: {name}")
    if spec.interval not in INTERVALS:
        problems.append(f"지원하지 않는 봉 간격입니다: {spec.interval} (가능: {', '.join(INTERVALS)})")
    r = spec.risk
    if not (0 < r.leverage <= 125):
        problems.append("레버리지는 0~125 사이여야 합니다.")
    if not (0 < r.position_pct <= 100):
        problems.append("position_pct 는 0~100 사이여야 합니다.")
    return problems
