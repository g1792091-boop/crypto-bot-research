"""사용자 수식 지표 (type "custom") — 퀀트 연구소가 지표를 수식으로 직접 발명한다.

안전한 식 언어: 토크나이저 → 재귀 하강 파서 → AST → numpy 벡터 계산. 파이썬 eval 은 절대 쓰지 않는다.
- 값이 없는 봉(워밍업·데이터 없음)은 NaN 으로 퍼진다. and/or/not 은 NaN 을 거짓으로 본다. 0 으로 나누면 NaN.
- 제한: 수식 2000자 · 중첩 40 · 노드 400 · 창 길이 1~2000 · 계산량 1e8.
"""
from __future__ import annotations

import math
import re

import numpy as np

MAX_LEN, MAX_DEPTH, MAX_NODES, MAX_WIN, MAX_COST = 2000, 40, 400, 2000, 1e8
BANNED = re.compile(r"^__|^(constructor|prototype|toString|valueOf|hasOwnProperty)$")

CUSTOM_DOC = """사용자 수식 지표 (type "custom") — 지표를 수식으로 직접 만든다
선언: {"id": "이름", "type": "custom", "expr": "수식"} → 조건식에서 "이름" 으로 참조 (봉마다 값 1개, 참/거짓은 1/0)
- 변수: open high low close volume hl2 hlc3 ohlc4, bar(봉 번호), hour·dow(UTC 시·요일 0=일)
  · 앞에서 선언한 지표 id ("rsi", "macd.hist" 처럼), 파생 funding oi oi_change_pct long_short
  · 외부 시리즈: ml_prob(머신러닝 상승확률 0~1), ml_signal(+1/0/-1) 등 ml_*, ext_* 이름 — 데이터가 없으면 null
- 연산: + - * / ^ %, > < >= <= == !=, and or not (&& || !), 조건 ? a : b, 괄호, x[n] = n봉 전 값
- null(워밍업·데이터 없음)은 계산에 퍼진다. and/or/not 은 null 을 거짓으로 본다. 0으로 나누면 null.
- 함수 (n 은 숫자 상수 1~2000):
  sma ema wma rma stdev highest lowest sum (x,n) · roc(x,n) 변화율% · change(x,n) · delay(x,n)=ref
  zscore(x,n) · rank(x,n)=percentile 직전 n개 중 백분위 0~100 · corr(x,y,n) · slope(x,n) 회귀 기울기 · linreg(x,n) 회귀값
  abs sqrt log log10 exp sign round floor ceil, pow(a,b), min(a,b,..) max(a,b,..), clamp(x,lo,hi), nz(x,대체값=0), iff(c,a,b)
  crossover(a,b) crossunder(a,b) (1/0) · barssince(조건) · valuewhen(조건, x, k=0) · cum(x) 누적합
  ind("지표", {파라미터}, "출력") — 내장 지표 표의 아무 지표 (예: ind("rsi",{length:14}), ind("macd",{},"hist"), ind("bb",{length:20},"upper"))
- 길이 2000자 이하. 함수·변수 이름 외의 코드는 쓸 수 없다.
예시
1) 변동성 조정 모멘텀: (close - close[20]) / (ind("atr", {length:14}) * sqrt(20))
2) Z점수 평균회귀 (-2 아래면 과매도): zscore(close, 50)
3) 거래량 충격 (방향 포함): zscore(log(volume), 50) * sign(close - open)
4) 추세 강도 종합 (-1~1): (sign(close - ema(close,50)) + sign(ema(close,20) - ema(close,50)) + (ind("adx",{length:14},"adx") > 25 ? sign(slope(close,20)) : 0)) / 3
5) 20봉 신고가 돌파 후 경과 봉 수: barssince(crossover(close, highest(high, 20)[1]))
6) ML 확률 + 추세 필터 (1이면 롱 후보): ml_prob > 0.6 and close > ema(close, 200) and zscore(funding, 30) < 2
전략 예: indicators 에 {"id":"vmom","type":"custom","expr":"(close - close[20]) / (ind(\\"atr\\",{length:14}) * sqrt(20))"} → 조건 {"left":"vmom","op":"crosses_above","right":"1"}"""


class FormulaError(ValueError):
    pass


# ------------------------------------------------------------------ 토크나이저
_TOK = re.compile(r"""\s*(?:
    (?P<num>\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)
  | (?P<str>"[\w .\-]{0,64}")
  | (?P<id>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)
  | (?P<op>&&|\|\||>=|<=|==|!=|[-+*/^%><!?:(),{}\[\]])
)""", re.X)


def tokenize(src: str) -> list[tuple[str, str]]:
    if len(src) > MAX_LEN:
        raise FormulaError(f"수식이 너무 깁니다 ({len(src)}자 > {MAX_LEN})")
    out, i = [], 0
    while i < len(src):
        if src[i:].strip() == "":
            break
        m = _TOK.match(src, i)
        if not m or m.end() == i:
            raise FormulaError(f"알 수 없는 문자: {src[i:i + 12]!r} (단일 =, &, | 는 쓸 수 없습니다)")
        kind = m.lastgroup
        val = m.group(kind)
        if kind == "id":
            low = val.lower()
            if low in ("and", "or", "not"):
                kind, val = "op", {"and": "&&", "or": "||", "not": "!"}[low]
            elif BANNED.search(val):
                raise FormulaError(f"쓸 수 없는 이름: {val}")
        out.append((kind, val))
        i = m.end()
    out.append(("end", ""))
    return out


# ------------------------------------------------------------------ 파서 (AST = 튜플)
class _Parser:
    def __init__(self, toks):
        self.t, self.i, self.nodes = toks, 0, 0

    def peek(self):
        return self.t[self.i]

    def take(self, val=None):
        k, v = self.t[self.i]
        if val is not None and v != val:
            raise FormulaError(f"'{val}' 이(가) 필요한 곳에 '{v or '끝'}'")
        self.i += 1
        return k, v

    def node(self, *a):
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise FormulaError(f"수식이 너무 복잡합니다 (노드 {MAX_NODES}개 초과)")
        return a

    def parse(self):
        e = self.ternary(0)
        if self.peek()[0] != "end":
            raise FormulaError(f"수식 끝에 남은 부분: {self.peek()[1]!r}")
        return e

    def _d(self, d):
        if d > MAX_DEPTH:
            raise FormulaError("괄호·함수 중첩이 너무 깊습니다")
        return d + 1

    def ternary(self, d):
        d = self._d(d)
        c = self.binop(0, d)
        if self.peek()[1] == "?":
            self.take("?")
            a = self.ternary(d)
            self.take(":")
            b = self.ternary(d)
            return self.node("iff", c, a, b)
        return c

    LEVELS = [("||",), ("&&",), ("==", "!="), (">", "<", ">=", "<="), ("+", "-"), ("*", "/", "%")]

    def binop(self, lv, d):
        if lv == len(self.LEVELS):
            return self.unary(d)
        left = self.binop(lv + 1, d)
        while self.peek()[0] == "op" and self.peek()[1] in self.LEVELS[lv]:
            op = self.take()[1]
            left = self.node("bin", op, left, self.binop(lv + 1, d))
        return left

    def unary(self, d):
        d = self._d(d)
        k, v = self.peek()
        if k == "op" and v in ("-", "+", "!"):
            self.take()
            return self.node("un", v, self.unary(d))
        return self.power(d)

    def power(self, d):
        base = self.postfix(d)
        if self.peek()[1] == "^":
            self.take()
            return self.node("bin", "^", base, self.unary(d))          # 오른쪽 결합
        return base

    def postfix(self, d):
        e = self.primary(d)
        while self.peek()[1] == "[":
            self.take("[")
            n = self.ternary(d)
            self.take("]")
            e = self.node("call", "delay", [e, n], None)
        return e

    def primary(self, d):
        k, v = self.take()
        if k == "num":
            return self.node("num", float(v))
        if k == "str":
            raise FormulaError("문자열은 ind() 안에서만 쓸 수 있습니다")
        if v == "(":
            e = self.ternary(d)
            self.take(")")
            return e
        if k == "id":
            if self.peek()[1] == "(":
                self.take("(")
                if v == "ind":
                    return self._ind(d)
                args = []
                if self.peek()[1] != ")":
                    args.append(self.ternary(d))
                    while self.peek()[1] == ",":
                        self.take(",")
                        args.append(self.ternary(d))
                self.take(")")
                return self.node("call", v.lower(), args, None)
            low = v.lower()
            if low in ("true", "false"):
                return self.node("num", 1.0 if low == "true" else 0.0)
            if low == "na":
                return self.node("num", math.nan)
            return self.node("var", v)
        raise FormulaError(f"예상하지 못한 '{v or '끝'}'")

    def _ind(self, d):
        k, name = self.take()
        if k != "str":
            raise FormulaError('ind() 의 첫 인자는 "지표이름" 문자열입니다')
        params, out = {}, None
        if self.peek()[1] == ",":
            self.take(",")
            if self.peek()[1] == "{":
                self.take("{")
                while self.peek()[1] != "}":
                    pk, pn = self.take()
                    if pk not in ("id", "str"):
                        raise FormulaError("ind() 파라미터 이름이 필요합니다")
                    self.take(":")
                    sign = -1 if self.peek()[1] == "-" and self.take() else 1
                    nk, nv = self.take()
                    if nk == "num":
                        params[pn.strip('"')] = sign * float(nv)
                    elif nk == "str":
                        params[pn.strip('"')] = nv.strip('"')
                    else:
                        raise FormulaError("ind() 파라미터 값은 숫자 상수여야 합니다")
                    if len(params) > 12:
                        raise FormulaError("ind() 파라미터는 12개까지")
                    if self.peek()[1] == ",":
                        self.take(",")
                self.take("}")
            if self.peek()[1] == ",":
                self.take(",")
                ok, ov = self.take()
                if ok != "str":
                    raise FormulaError('ind() 의 출력 이름은 "value" 같은 문자열입니다')
                out = ov.strip('"')
        self.take(")")
        return self.node("ind", name.strip('"'), params, out)


def parse(src: str):
    return _Parser(tokenize(src)).parse()


# ------------------------------------------------------------------ 계산
def _nan(n):
    return np.full(n, np.nan)


def _const(node) -> float:
    """창 길이 같은 상수 인자 (상수식만 허용)."""
    if node[0] == "num":
        return node[1]
    if node[0] == "un" and node[1] == "-" and node[2][0] == "num":
        return -node[2][1]
    if node[0] == "bin" and node[2][0] == "num" and node[3][0] == "num":
        a, b = node[2][1], node[3][1]
        return {"+": a + b, "-": a - b, "*": a * b, "/": a / b if b else math.nan}.get(node[1], math.nan)
    raise FormulaError("창 길이(n)는 숫자 상수여야 합니다")


def _win(node, lo=1, hi=MAX_WIN) -> int:
    v = _const(node)
    if not math.isfinite(v) or not lo <= int(v) <= hi:
        raise FormulaError(f"창 길이는 {lo}~{hi} 사이 숫자입니다")
    return int(v)


def _rolling(x, n, fn):
    out = _nan(len(x))
    if n > len(x):
        return out
    w = np.lib.stride_tricks.sliding_window_view(x, n)
    with np.errstate(all="ignore"):
        r = fn(w)
    r[np.isnan(w).any(axis=1)] = np.nan
    out[n - 1:] = r
    return out


def _ema(x, n, alpha=None):
    a = alpha if alpha is not None else 2 / (n + 1)
    out, prev, buf = _nan(len(x)), math.nan, []
    for i, v in enumerate(x):
        if math.isnan(v):
            if not math.isnan(prev):
                prev = math.nan
                buf = []
            continue
        if math.isnan(prev):
            buf.append(v)
            if len(buf) == n:
                prev = sum(buf) / n          # SMA 시드 (Pine 과 같음)
                out[i] = prev
            continue
        prev = prev + a * (v - prev)
        out[i] = prev
    return out


def _shift(x, k):
    if k <= 0:
        return x.copy()
    out = _nan(len(x))
    out[k:] = x[:-k]
    return out


def _bool(x):
    return np.where(np.isnan(x), False, x != 0)


class Evaluator:
    def __init__(self, candles: list[dict], series: dict[str, list]):
        self.c, self.n = candles, len(candles)
        self.series = series
        self.cost = 0.0
        t = np.array([b["time"] for b in candles], dtype=float)
        self.base = {"bar": np.arange(self.n, dtype=float), "hour": (t % 86400) // 3600, "dow": ((t // 86400) + 4) % 7}

    def _charge(self, k=1.0):
        self.cost += self.n * k
        if self.cost > MAX_COST:
            raise FormulaError("계산량이 너무 큽니다 (창 길이·함수 수를 줄이세요)")

    def var(self, name):
        if name in self.base:
            return self.base[name]
        if name in self.series:
            return np.array([np.nan if v is None else float(v) for v in self.series[name]], dtype=float)
        if name.startswith(("ml_", "ext_")):
            return _nan(self.n)
        raise FormulaError(f"알 수 없는 변수: {name} (가격·앞에서 선언한 지표 id·funding 등만)")

    def ev(self, node):
        self._charge()
        k = node[0]
        if k == "num":
            return np.full(self.n, node[1])
        if k == "var":
            return self.var(node[1])
        if k == "un":
            x = self.ev(node[2])
            if node[1] == "-":
                return -x
            if node[1] == "+":
                return x
            return (~_bool(x)).astype(float)
        if k == "bin":
            op = node[1]
            a, b = self.ev(node[2]), self.ev(node[3])
            with np.errstate(all="ignore"):
                if op == "&&":
                    return (_bool(a) & _bool(b)).astype(float)
                if op == "||":
                    return (_bool(a) | _bool(b)).astype(float)
                nan = np.isnan(a) | np.isnan(b)
                r = {"+": lambda: a + b, "-": lambda: a - b, "*": lambda: a * b,
                     "/": lambda: np.where(b == 0, np.nan, a / np.where(b == 0, 1, b)),
                     "%": lambda: np.where(b == 0, np.nan, np.mod(a, np.where(b == 0, 1, b))),
                     "^": lambda: np.power(a, b),
                     ">": lambda: (a > b).astype(float), "<": lambda: (a < b).astype(float),
                     ">=": lambda: (a >= b).astype(float), "<=": lambda: (a <= b).astype(float),
                     "==": lambda: (a == b).astype(float), "!=": lambda: (a != b).astype(float)}[op]()
                r = np.where(nan, np.nan, r)
                r[~np.isfinite(r)] = np.nan
                return r
        if k == "iff":
            c, a, b = self.ev(node[1]), self.ev(node[2]), self.ev(node[3])
            return np.where(np.isnan(c), np.nan, np.where(c != 0, a, b))
        if k == "ind":
            return self._ind(node[1], node[2], node[3])
        if k == "call":
            return self.call(node[1], node[2])
        raise FormulaError("잘못된 수식")

    def _ind(self, name, params, out):
        from .. import indicators as ind
        name = name.strip().lower()
        if name in ("custom", "ml") or name not in ind.REGISTRY:
            raise FormulaError(f"ind() 에 쓸 수 없는 지표: {name}")
        self._charge(50)
        p = {k: (int(v) if k in ("length", "fast", "slow", "signal", "k_smooth", "d_smooth") else v) for k, v in params.items()}
        res = ind.compute(self.c, name, p)
        key = out or ("value" if "value" in res else next(iter(res)))
        if key not in res:
            raise FormulaError(f"{name} 의 출력은 {', '.join(res)} 중 하나입니다")
        return np.array([np.nan if v is None else float(v) for v in res[key]], dtype=float)

    def call(self, fn, args):
        A = lambda i: self.ev(args[i])
        argc = len(args)

        def need(lo, hi=None):
            if not (lo <= argc <= (hi if hi is not None else lo)):
                raise FormulaError(f"{fn}() 인자 개수가 맞지 않습니다")
        roll = {"sma": np.mean, "highest": np.max, "lowest": np.min, "sum": np.sum,
                "stdev": lambda w: np.std(w, axis=-1)}
        if fn in roll:
            need(2)
            n = _win(args[1])
            self._charge(n)
            f = roll[fn]
            return _rolling(A(0), n, (lambda w: f(w, axis=-1)) if fn != "stdev" else f)
        if fn in ("ema", "rma"):
            need(2)
            n = _win(args[1])
            return _ema(A(0), n, None if fn == "ema" else 1 / n)
        if fn == "wma":
            need(2)
            n = _win(args[1])
            self._charge(n)
            wts = np.arange(1, n + 1, dtype=float)
            return _rolling(A(0), n, lambda w: (w * wts).sum(axis=-1) / wts.sum())
        if fn in ("delay", "ref"):
            need(1, 2)
            return _shift(A(0), _win(args[1], 0) if argc > 1 else 1)
        if fn in ("change", "roc"):
            need(1 if fn == "change" else 2, 2)
            k = _win(args[1]) if argc > 1 else 1
            x = A(0)
            p = _shift(x, k)
            with np.errstate(all="ignore"):
                r = x - p if fn == "change" else np.where(p == 0, np.nan, (x / p - 1) * 100)
            return r
        if fn == "zscore":
            need(2)
            n = _win(args[1])
            self._charge(n)
            x = A(0)
            m = _rolling(x, n, lambda w: w.mean(axis=-1))
            sd = _rolling(x, n, lambda w: w.std(axis=-1))
            with np.errstate(all="ignore"):
                return np.where(np.isnan(sd), np.nan, np.where(sd > 1e-12, (x - m) / np.where(sd > 1e-12, sd, 1), 0.0))
        if fn in ("rank", "percentile"):
            need(2)
            n = _win(args[1])
            self._charge(n)
            x = A(0)
            out = _nan(self.n)
            for i in range(n, self.n):
                w = x[i - n:i]
                if np.isnan(w).any() or np.isnan(x[i]):
                    continue
                out[i] = (w <= x[i]).mean() * 100
            return out
        if fn == "corr":
            need(3)
            n = _win(args[2], 2)
            self._charge(n)
            x, y = A(0), A(1)
            out = _nan(self.n)
            for i in range(n - 1, self.n):
                a, b = x[i - n + 1:i + 1], y[i - n + 1:i + 1]
                if np.isnan(a).any() or np.isnan(b).any() or a.std() < 1e-12 or b.std() < 1e-12:
                    continue
                out[i] = float(np.corrcoef(a, b)[0, 1])
            return out
        if fn in ("slope", "linreg"):
            need(2)
            n = _win(args[1], 2)
            self._charge(n)
            t = np.arange(n, dtype=float)
            tm = t.mean()
            den = ((t - tm) ** 2).sum()

            def fit(w):
                ym = w.mean(axis=-1, keepdims=True)
                b = ((w - ym) * (t - tm)).sum(axis=-1) / den
                return b if fn == "slope" else ym[:, 0] + b * (n - 1 - tm)
            return _rolling(A(0), n, fit)
        one = {"abs": np.abs, "exp": np.exp, "sign": np.sign, "round": np.round, "floor": np.floor, "ceil": np.ceil,
               "sqrt": lambda x: np.where(x < 0, np.nan, np.sqrt(np.abs(x))),
               "log": lambda x: np.where(x <= 0, np.nan, np.log(np.where(x <= 0, 1, x))),
               "log10": lambda x: np.where(x <= 0, np.nan, np.log10(np.where(x <= 0, 1, x)))}
        if fn in one:
            need(1)
            with np.errstate(all="ignore"):
                r = one[fn](A(0))
            r = np.asarray(r, dtype=float)
            r[~np.isfinite(r)] = np.nan
            return r
        if fn == "pow":
            need(2)
            with np.errstate(all="ignore"):
                r = np.power(A(0), A(1))
            r[~np.isfinite(r)] = np.nan
            return r
        if fn in ("min", "max"):
            if argc < 1:
                raise FormulaError(f"{fn}() 에 값이 필요합니다")
            st = np.vstack([A(i) for i in range(argc)])
            with np.errstate(all="ignore"):
                r = st.min(axis=0) if fn == "min" else st.max(axis=0)
            return r
        if fn == "clamp":
            need(3)
            return np.clip(A(0), A(1), A(2))
        if fn == "nz":
            need(1, 2)
            x = A(0)
            return np.where(np.isnan(x), A(1) if argc > 1 else 0.0, x)
        if fn == "iff":
            need(3)
            c = A(0)
            return np.where(np.isnan(c), np.nan, np.where(c != 0, A(1), A(2)))
        if fn in ("crossover", "crossunder"):
            need(2)
            a, b = A(0), A(1)
            pa, pb = _shift(a, 1), _shift(b, 1)
            with np.errstate(invalid="ignore"):
                r = (a > b) & (pa <= pb) if fn == "crossover" else (a < b) & (pa >= pb)
            r = r.astype(float)
            r[np.isnan(a) | np.isnan(b) | np.isnan(pa) | np.isnan(pb)] = 0.0
            return r
        if fn == "barssince":
            need(1)
            c, out, last = _bool(A(0)), _nan(self.n), None
            for i in range(self.n):
                if c[i]:
                    last = i
                if last is not None:
                    out[i] = i - last
            return out
        if fn == "valuewhen":
            need(2, 3)
            c, x = _bool(A(0)), A(1)
            k = _win(args[2], 0, 100) if argc > 2 else 0
            out, hits = _nan(self.n), []
            for i in range(self.n):
                if c[i]:
                    hits.append(x[i])
                if len(hits) > k:
                    out[i] = hits[-1 - k]
            return out
        if fn == "cum":
            need(1)
            x = A(0)
            return np.cumsum(np.nan_to_num(x))
        if fn == "ind":
            raise FormulaError('ind("지표", {파라미터}, "출력") 형식으로 쓰세요')
        raise FormulaError(f"알 수 없는 함수: {fn}()")


def evaluate(expr: str, candles: list[dict], series: dict[str, list]) -> list:
    """수식을 계산해 캔들 길이의 리스트(None = 값 없음)로 돌려준다."""
    tree = parse(expr)
    r = Evaluator(candles, series).ev(tree)
    r = np.asarray(r, dtype=float)
    if r.shape != (len(candles),):
        r = np.full(len(candles), r.flat[0] if r.size else np.nan)
    return [None if not math.isfinite(v) else round(float(v), 10) for v in r]


def check(expr: str) -> str | None:
    """문법만 확인 (None = 정상)."""
    try:
        parse(expr)
        return None
    except FormulaError as e:
        return str(e)
