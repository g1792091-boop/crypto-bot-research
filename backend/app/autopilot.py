"""오토파일럿 — 시작 버튼 없이 계속 돈다.

1) 화면이 보내 준 '지금 차트에 띄운 보조지표'로 매매법 후보를 만든다
   (지표마다 진입 규칙 · 추세/거래량 필터 · 손절·익절 방식 · 방향을 조합, 최대 240개)
2) 3구간 관문으로 검증한다: 앞 60% 학습 구간 순위 → 다음 20% 검증 → 마지막 20% 최종 확인(이 구간은 고를 때 안 봄).
   세 구간 모두 거래 수·손익비·순이익 기준을 넘어야 '검증 통과'. 시도한 후보 수를 모두 기록한다.
3) 통과한 매매법은 페이퍼 봇으로 바로 돌린다. 하나도 없으면(흔함) 가장 나은 후보를 '관찰(미통과)' 봇으로 돌려
   앞으로의 실제 시세로 검증한다 (설정으로 끌 수 있음).
4) 봇이 진입·청산하면 시그널을 쌓는다 → 화면이 알림으로 띄우고 차트에 진입·손절·익절선이 나온다.
5) AI 상시 감시: 지금 차트 코인을 실시간 AI 가 몇 분마다 다시 보고 판단이 바뀌면 알림, 에이전트 팀은 정해진 간격으로
   '상시 감시' 회의, 새 매매법이 통과하면 '오토파일럿 검토' 회의(검증관 → 승인관 → 리스크 → 팀장)를 스스로 연다.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import math
import random
import threading
import time
from collections import deque

from . import backtest, config
from .data import market
from .strategy import INTERVALS, StrategySpec, validate

SETTINGS = {
    "enabled": True,
    "scope": "chart",                # chart = 지금 차트 코인·봉 / chart+watch = 관심 종목 앞 3개도
    "extra_interval": True,          # 차트 봉보다 한 단계 긴 봉도 같이 탐색
    "max_bots": 3,
    "search_every_hours": 6,
    "observe_if_none": True,         # 통과가 없으면 가장 나은 후보를 관찰 봇으로
    "team_review": True,             # 통과 매매법은 에이전트 팀 검토 뒤 배치 (승인관이 거부하면 배치 안 함)
    "team_monitor_min": 120,         # 에이전트 팀 상시 감시 회의 간격 (0 = 끔)
    "copilot_every_min": 5,          # 실시간 AI 가 차트 코인을 다시 보는 간격 (0 = 끔)
    "leverage": 3, "position_pct": 20, "bars": 3000,
}
GATE = {"train": {"trades": 20, "pf": 1.1}, "valid": {"trades": 8, "pf": 1.15}, "hold": {"trades": 8, "pf": 1.1}}
NEXT_IV = {"1m": "5m", "3m": "15m", "5m": "15m", "15m": "1h", "30m": "2h", "1h": "4h", "2h": "4h", "4h": "12h", "6h": "1d", "8h": "1d", "12h": "1d", "1d": "3d"}

_paper = None
_lock = threading.RLock()
context = {"symbol": "BTCUSDT", "interval": "1h", "indicators": [], "watch": [], "updated": 0.0}
state = {"searching": False, "last_search": 0.0, "last_context_key": None, "results": [], "log": deque(maxlen=200),
         "bots": {}, "history": [], "last_copilot": 0.0, "copilot_bias": {}, "last_team_monitor": 0.0, "team_runs": []}
signals: deque[dict] = deque(maxlen=400)


def bind(paper_manager) -> None:
    global _paper
    _paper = paper_manager
    saved = _load()
    SETTINGS.update(saved.get("settings", {}))
    context.update(saved.get("context", {}))
    state["bots"] = saved.get("bots", {})
    state["history"] = saved.get("history", [])
    state["results"] = saved.get("results", [])
    state["last_search"] = saved.get("last_search", 0.0)
    state["last_context_key"] = saved.get("last_context_key")
    for s in saved.get("signals", []):
        signals.append(s)


def _path():
    return config.STATE_DIR / "autopilot.json"


def _load() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save() -> None:
    try:
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        _path().write_text(json.dumps({"settings": SETTINGS, "context": context, "bots": state["bots"], "history": state["history"][-100:],
                                       "results": state["results"][-8:], "last_search": state["last_search"],
                                       "last_context_key": state["last_context_key"], "signals": list(signals)[-200:]},
                                      ensure_ascii=False, default=str), encoding="utf-8")
    except OSError:
        pass


def log(msg: str) -> None:
    state["log"].appendleft({"time": int(time.time()), "msg": msg})


def set_settings(**kw) -> dict:
    for k, v in kw.items():
        if v is not None and k in SETTINGS:
            SETTINGS[k] = type(SETTINGS[k])(v) if not isinstance(SETTINGS[k], bool) else bool(v)
    save()
    return dict(SETTINGS)


def set_context(symbol: str, interval: str, indicators: list[dict], watch: list[str] | None = None) -> dict:
    with _lock:
        context.update(symbol=symbol, interval=interval if interval in INTERVALS else "1h",
                       indicators=[{"key": x.get("key"), "params": x.get("params") or {}} for x in indicators if x.get("key")][:40],
                       watch=(watch or [])[:20], updated=time.time())
    save()
    return {"context": context, "usable": usable(context["indicators"])}


# ---------------------------------------------------------------- 차트 지표 → 규칙 조각
def _n(p: dict, k: str, d):
    try:
        v = p.get(k)
        return type(d)(v) if v not in (None, "") else d
    except (TypeError, ValueError):
        return d


def _c(left, op, right):
    return {"left": left, "op": op, "right": str(right)}


def blocks_for(key: str, p: dict) -> list[dict]:
    """차트 지표 하나 → [{name, ind:[IndicatorSpec…], entry:(롱 조건들, 숏 조건들, 롱 청산, 숏 청산) | None, filter:(롱, 숏) | None}]"""
    out = []
    MA = {"ema": "ema", "sma": "sma", "wma": "wma", "hma": "hma", "vwma": "vwma"}
    if key in MA:
        L = _n(p, "length", {"hma": 55}.get(key, 20))
        i = f"{key}{L}"
        spec = [{"id": i, "type": MA[key], "length": L}]
        out.append({"name": f"{key.upper()}{L} 돌파", "ind": spec, "entry": ([_c("close", "crosses_above", i)], [_c("close", "crosses_below", i)],
                                                                          [_c("close", "crosses_below", i)], [_c("close", "crosses_above", i)])})
        if L >= 50:
            out.append({"name": f"{key.upper()}{L} 위/아래", "ind": spec, "filter": ([_c("close", ">", i)], [_c("close", "<", i)])})
    elif key == "ema_ribbon":
        spec = [{"id": "e20", "type": "ema", "length": 20}, {"id": "e50", "type": "ema", "length": 50}, {"id": "e200", "type": "ema", "length": 200}]
        out.append({"name": "EMA20/50 교차", "ind": spec, "entry": ([_c("e20", "crosses_above", "e50")], [_c("e20", "crosses_below", "e50")],
                                                                  [_c("e20", "crosses_below", "e50")], [_c("e20", "crosses_above", "e50")])})
        out.append({"name": "EMA200 위/아래", "ind": spec, "filter": ([_c("close", ">", "e200")], [_c("close", "<", "e200")])})
    elif key in ("supertrend", "psar", "atr_stop", "ut_bot", "chandelier"):
        if key == "supertrend":
            spec = [{"id": "st", "type": "supertrend", "length": _n(p, "length", 10), "mult": _n(p, "mult", 3.0)}]
        elif key == "psar":
            spec = [{"id": "st", "type": "psar"}]
        else:
            spec = [{"id": "st", "type": "atr_stop", "length": _n(p, "length", _n(p, "atr", 14)), "mult": _n(p, "mult", _n(p, "key", 3.0))}]
        nm = {"supertrend": "슈퍼트렌드", "psar": "파라볼릭 SAR", "atr_stop": "ATR 추적손절", "ut_bot": "UT Bot", "chandelier": "샹들리에"}[key]
        out.append({"name": f"{nm} 전환", "ind": spec, "entry": ([_c("st.trend", "crosses_above", 0)], [_c("st.trend", "crosses_below", 0)],
                                                            [_c("st.trend", "crosses_below", 0)], [_c("st.trend", "crosses_above", 0)])})
        out.append({"name": f"{nm} 방향", "ind": spec, "filter": ([_c("st.trend", ">", 0)], [_c("st.trend", "<", 0)])})
    elif key == "ichimoku":
        spec = [{"id": "ich", "type": "ichimoku", "fast": _n(p, "conv", 9), "slow": _n(p, "base", 26), "length": _n(p, "span", 52)}]
        out.append({"name": "일목 전환선×기준선 (구름 위/아래)", "ind": spec,
                    "entry": ([_c("ich.tenkan", "crosses_above", "ich.kijun"), _c("close", ">", "ich.span_a"), _c("close", ">", "ich.span_b")],
                              [_c("ich.tenkan", "crosses_below", "ich.kijun"), _c("close", "<", "ich.span_a"), _c("close", "<", "ich.span_b")],
                              [_c("close", "crosses_below", "ich.kijun")], [_c("close", "crosses_above", "ich.kijun")])})
        out.append({"name": "구름 위/아래", "ind": spec, "filter": ([_c("close", ">", "ich.span_a"), _c("close", ">", "ich.span_b")],
                                                                [_c("close", "<", "ich.span_a"), _c("close", "<", "ich.span_b")])})
    elif key == "macd":
        spec = [{"id": "macd", "type": "macd", "fast": _n(p, "fast", 12), "slow": _n(p, "slow", 26), "signal": _n(p, "signal", 9)}]
        out.append({"name": "MACD 시그널 교차", "ind": spec, "entry": ([_c("macd.line", "crosses_above", "macd.signal")], [_c("macd.line", "crosses_below", "macd.signal")],
                                                                    [_c("macd.line", "crosses_below", "macd.signal")], [_c("macd.line", "crosses_above", "macd.signal")])})
        out.append({"name": "MACD 0선", "ind": spec, "entry": ([_c("macd.line", "crosses_above", 0)], [_c("macd.line", "crosses_below", 0)],
                                                            [_c("macd.line", "crosses_below", 0)], [_c("macd.line", "crosses_above", 0)])})
        out.append({"name": "MACD 히스토그램 +/-", "ind": spec, "filter": ([_c("macd.hist", ">", 0)], [_c("macd.hist", "<", 0)])})
    elif key in ("rsi", "rsi_div", "crsi", "laguerre"):
        L = _n(p, "length", 14)
        spec = [{"id": "rsi", "type": "rsi", "length": L}]
        out.append({"name": f"RSI{L} 과매도·과매수 반전", "ind": spec, "entry": ([_c("rsi", "crosses_above", 30)], [_c("rsi", "crosses_below", 70)],
                                                                          [_c("rsi", ">", 70)], [_c("rsi", "<", 30)])})
        out.append({"name": f"RSI{L} 50선 모멘텀", "ind": spec, "entry": ([_c("rsi", "crosses_above", 50)], [_c("rsi", "crosses_below", 50)],
                                                                      [_c("rsi", "crosses_below", 45)], [_c("rsi", "crosses_above", 55)])})
        out.append({"name": "RSI 50 위/아래", "ind": spec, "filter": ([_c("rsi", ">", 50)], [_c("rsi", "<", 50)])})
    elif key in ("stoch", "stochrsi", "smi"):
        t = "stochrsi" if key == "stochrsi" else "stoch"
        spec = [{"id": "sk", "type": t, "length": _n(p, "length", 14), "k_smooth": _n(p, "k", 3), "d_smooth": _n(p, "d", 3)}]
        out.append({"name": f"{'스토캐스틱 RSI' if t == 'stochrsi' else '스토캐스틱'} 바닥·천장 교차", "ind": spec,
                    "entry": ([_c("sk.k", "crosses_above", "sk.d"), _c("sk.k", "<", 30)], [_c("sk.k", "crosses_below", "sk.d"), _c("sk.k", ">", 70)],
                              [_c("sk.k", ">", 80)], [_c("sk.k", "<", 20)])})
    elif key == "cci":
        spec = [{"id": "cci", "type": "cci", "length": _n(p, "length", 20)}]
        out.append({"name": "CCI ±100 복귀", "ind": spec, "entry": ([_c("cci", "crosses_above", -100)], [_c("cci", "crosses_below", 100)],
                                                                [_c("cci", ">", 100)], [_c("cci", "<", -100)])})
    elif key == "willr":
        spec = [{"id": "wr", "type": "willr", "length": _n(p, "length", 14)}]
        out.append({"name": "윌리엄스 %R 반전", "ind": spec, "entry": ([_c("wr", "crosses_above", -80)], [_c("wr", "crosses_below", -20)],
                                                                   [_c("wr", ">", -20)], [_c("wr", "<", -80)])})
    elif key == "mfi":
        spec = [{"id": "mfi", "type": "mfi", "length": _n(p, "length", 14)}]
        out.append({"name": "MFI 반전", "ind": spec, "entry": ([_c("mfi", "crosses_above", 20)], [_c("mfi", "crosses_below", 80)],
                                                             [_c("mfi", ">", 80)], [_c("mfi", "<", 20)])})
    elif key in ("bb", "bb_pctb", "bbw", "squeeze"):
        L, m = _n(p, "length", 20), _n(p, "mult", 2.0)
        spec = [{"id": "bb", "type": "bb", "length": L, "mult": m}]
        out.append({"name": "볼린저 하단·상단 되돌림", "ind": spec, "entry": ([_c("close", "crosses_above", "bb.lower")], [_c("close", "crosses_below", "bb.upper")],
                                                                        [_c("close", ">", "bb.middle")], [_c("close", "<", "bb.middle")])})
        out.append({"name": "볼린저 밴드 돌파", "ind": spec, "entry": ([_c("close", "crosses_above", "bb.upper")], [_c("close", "crosses_below", "bb.lower")],
                                                                  [_c("close", "crosses_below", "bb.middle")], [_c("close", "crosses_above", "bb.middle")])})
    elif key == "keltner":
        spec = [{"id": "kc", "type": "keltner", "length": _n(p, "length", 20), "mult": _n(p, "mult", 2.0)}]
        out.append({"name": "켈트너 돌파", "ind": spec, "entry": ([_c("close", "crosses_above", "kc.upper")], [_c("close", "crosses_below", "kc.lower")],
                                                               [_c("close", "crosses_below", "kc.middle")], [_c("close", "crosses_above", "kc.middle")])})
    elif key in ("donchian", "pdhl"):
        L = _n(p, "length", 20)
        spec = [{"id": "dc", "type": "donchian", "length": L}]
        out.append({"name": f"돈치안 {L} 돌파 (터틀)", "ind": spec, "entry": ([_c("close", ">", "dc.upper[1]")], [_c("close", "<", "dc.lower[1]")],
                                                                          [_c("close", "<", "dc.middle")], [_c("close", ">", "dc.middle")])})
    elif key == "adx":
        spec = [{"id": "adx", "type": "adx", "length": _n(p, "length", 14)}]
        out.append({"name": "DI 교차 (ADX>20)", "ind": spec, "entry": ([_c("adx.plus_di", "crosses_above", "adx.minus_di"), _c("adx.adx", ">", 20)],
                                                                      [_c("adx.plus_di", "crosses_below", "adx.minus_di"), _c("adx.adx", ">", 20)],
                                                                      [_c("adx.plus_di", "crosses_below", "adx.minus_di")], [_c("adx.plus_di", "crosses_above", "adx.minus_di")])})
        out.append({"name": "추세 있을 때만 (ADX>20)", "ind": spec, "filter": ([_c("adx.adx", ">", 20)], [_c("adx.adx", ">", 20)])})
    elif key == "aroon":
        spec = [{"id": "ar", "type": "aroon", "length": _n(p, "length", 25)}]
        out.append({"name": "아룬 교차", "ind": spec, "entry": ([_c("ar.up", "crosses_above", "ar.down")], [_c("ar.up", "crosses_below", "ar.down")],
                                                             [_c("ar.up", "crosses_below", "ar.down")], [_c("ar.up", "crosses_above", "ar.down")])})
    elif key in ("roc", "mom", "ao", "tsi", "trix", "ppo"):
        spec = [{"id": "roc", "type": "roc", "length": _n(p, "length", 9)}]
        out.append({"name": "모멘텀 0선 (ROC)", "ind": spec, "entry": ([_c("roc", "crosses_above", 0)], [_c("roc", "crosses_below", 0)],
                                                                   [_c("roc", "crosses_below", 0)], [_c("roc", "crosses_above", 0)])})
    elif key in ("cmf", "tmf", "chaikin_osc"):
        spec = [{"id": "cmf", "type": "cmf", "length": _n(p, "length", 20)}]
        out.append({"name": "자금 유입/유출 (CMF)", "ind": spec, "filter": ([_c("cmf", ">", 0)], [_c("cmf", "<", 0)])})
    elif key in ("vwap", "vwap_bands", "avwap"):
        spec = [{"id": "vw", "type": "vwap"}]
        out.append({"name": "VWAP 돌파", "ind": spec, "entry": ([_c("close", "crosses_above", "vw")], [_c("close", "crosses_below", "vw")],
                                                              [_c("close", "crosses_below", "vw")], [_c("close", "crosses_above", "vw")])})
        out.append({"name": "VWAP 위/아래", "ind": spec, "filter": ([_c("close", ">", "vw")], [_c("close", "<", "vw")])})
    elif key in ("volume", "rvol", "vol_osc"):
        spec = [{"id": "vma", "type": "volume_sma", "length": _n(p, "ma", 20)}]
        out.append({"name": "거래량 1.5배 이상", "ind": spec, "filter": ([_c("volume", ">", "vma*1.5")], [_c("volume", ">", "vma*1.5")])})
    elif key == "obv":
        spec = [{"id": "obv", "type": "obv"}]
        out.append({"name": "OBV 3봉 상승/하락", "ind": spec, "filter": ([_c("obv", "rising", 3)], [_c("obv", "falling", 3)])})
    return out


def usable(indicators: list[dict]) -> dict:
    ok, no = [], []
    for x in indicators:
        (ok if blocks_for(x["key"], x.get("params") or {}) else no).append(x["key"])
    return {"usable": list(dict.fromkeys(ok)), "unusable": list(dict.fromkeys(no))}


DEFAULT_CHART = [{"key": "ema", "params": {"length": 50}}, {"key": "rsi", "params": {"length": 14}}, {"key": "supertrend", "params": {}},
                 {"key": "macd", "params": {}}, {"key": "volume", "params": {}}]
RISK_PROFILES = [
    ("신호 청산 + ATR×2 손절", {"atr_stop_mult": 2.0}),
    ("ATR×1.5 손절 · ATR×3 익절", {"atr_stop_mult": 1.5, "atr_tp_mult": 3.0}),
    ("ATR×2 손절 · ATR×4 익절", {"atr_stop_mult": 2.0, "atr_tp_mult": 4.0}),
    ("ATR×3 손절 + 신호 청산", {"atr_stop_mult": 3.0}),
]


def candidates(symbol: str, interval: str, indicators: list[dict], limit: int = 240) -> tuple[list[StrategySpec], bool]:
    used_default = False
    blocks = [b for x in indicators for b in blocks_for(x["key"], x.get("params") or {})]
    if not any("entry" in b for b in blocks):
        blocks += [b for x in DEFAULT_CHART for b in blocks_for(x["key"], x["params"])]
        used_default = True
    seen, entries, filters = set(), [], []
    for b in blocks:
        k = (b["name"], "entry" in b)
        if k in seen:
            continue
        seen.add(k)
        (entries if "entry" in b else filters).append(b)
    out = []
    for e, f, (rname, risk), side in itertools.product(entries, [None] + filters, RISK_PROFILES, ("both", "long")):
        inds = {i["id"]: i for i in e["ind"] + (f["ind"] if f else [])}
        le, se, lx, sx = e["entry"]
        long_c = le + (f["filter"][0] if f else [])
        short_c = se + (f["filter"][1] if f else [])
        signal_exit = "신호" in rname
        name = f"{e['name']}" + (f" + {f['name']}" if f else "") + f" · {rname}" + (" · 롱만" if side == "long" else "")
        spec = StrategySpec(name=name[:80], description="오토파일럿이 차트 보조지표로 만든 후보", symbol=symbol, interval=interval,
                            indicators=list(inds.values()),
                            long_entry={"logic": "all", "conditions": long_c},
                            short_entry={"logic": "all", "conditions": short_c} if side == "both" else None,
                            long_exit={"logic": "any", "conditions": lx} if signal_exit else None,
                            short_exit={"logic": "any", "conditions": sx} if signal_exit and side == "both" else None,
                            risk={"leverage": SETTINGS["leverage"], "position_pct": SETTINGS["position_pct"], **risk})
        if not validate(spec):
            out.append(spec)
    if len(out) > limit:
        rng = random.Random(f"{symbol}{interval}{len(out)}")
        out = rng.sample(out, limit)
    return out, used_default


# ---------------------------------------------------------------- 3구간 검증
def _seg(trades: list[dict]) -> dict:
    n = len(trades)
    pnl = [t["pnl"] for t in trades]
    gw, gl = sum(x for x in pnl if x > 0), -sum(x for x in pnl if x <= 0)
    mean = sum(pnl) / n if n else 0
    sd = math.sqrt(sum((x - mean) ** 2 for x in pnl) / (n - 1)) if n > 1 else 0
    return {"trades": n, "net": round(sum(pnl), 2), "pf": round(gw / gl, 3) if gl > 0 else (99.0 if gw > 0 else None),
            "win_rate": round(sum(x > 0 for x in pnl) / n * 100, 1) if n else None, "t": round(mean / (sd / math.sqrt(n)), 3) if n > 1 and sd > 0 else 0.0}


def _family(name: str) -> str:
    """진입 규칙 이름 (필터·청산만 다른 후보는 거의 같은 매매라 한 가족으로)."""
    return name.split(" · ")[0].split(" + ")[0]


def _ok(s: dict, g: dict) -> bool:
    return s["trades"] >= g["trades"] and (s["pf"] or 0) >= g["pf"] and s["net"] > 0


def evaluate(symbol: str, interval: str, indicators: list[dict]) -> dict:
    t0 = time.time()
    c, src = market.candles(symbol, interval, SETTINGS["bars"])
    if len(c) < 600:
        return {"symbol": symbol, "interval": interval, "error": f"봉이 부족합니다 ({len(c)}개)", "tried": 0, "rows": []}
    t1, t2 = c[int(len(c) * 0.6)]["time"], c[int(len(c) * 0.8)]["time"]
    specs, used_default = candidates(symbol, interval, indicators)
    rows = []
    for sp in specs:
        try:
            r = backtest.run(sp, c, None)
        except Exception:
            continue
        tr = r["trades"]
        seg = {"train": _seg([t for t in tr if t["entry_time"] < t1]), "valid": _seg([t for t in tr if t1 <= t["entry_time"] < t2]),
               "hold": _seg([t for t in tr if t["entry_time"] >= t2])}
        rows.append({"spec": sp, "seg": seg, "all": {k: r["metrics"].get(k) for k in ("total_return_pct", "max_drawdown_pct", "trades", "win_rate_pct", "profit_factor")}})
    # 1) 학습 구간만 보고 순위 (검증·최종 구간은 안 봄)
    train_ok = sorted([r for r in rows if _ok(r["seg"]["train"], GATE["train"])], key=lambda r: -r["seg"]["train"]["t"])
    finalists = train_ok[:15]
    for r in rows:
        r["stage"] = "train_fail"
    for r in train_ok:
        r["stage"] = "train_pass"
    # 2) 상위 15개만 검증 구간 · 3) 검증 통과만 최종 확인
    for r in finalists:
        r["stage"] = "valid_fail"
        if _ok(r["seg"]["valid"], GATE["valid"]):
            r["stage"] = "hold_fail"
            if _ok(r["seg"]["hold"], GATE["hold"]) and (r["all"]["max_drawdown_pct"] or 0) < 35:
                r["stage"] = "pass"
    passed, fams = [], set()
    for r in sorted([r for r in rows if r["stage"] == "pass"], key=lambda r: -(r["seg"]["valid"]["t"] + r["seg"]["hold"]["t"])):
        fam = _family(r["spec"].name)
        if fam not in fams:                              # 같은 진입 규칙은 가장 나은 청산 방식 하나만
            fams.add(fam)
            passed.append(r)
    # 관찰 후보: 통과가 없을 때 학습 통과 중 검증+최종 구간 합이 가장 나은 것 (둘 다 이익이면 우선)
    obs = sorted([r for r in finalists if r["stage"] != "pass"],
                 key=lambda r: (-(r["seg"]["valid"]["net"] > 0 and r["seg"]["hold"]["net"] > 0), -(r["seg"]["valid"]["t"] + r["seg"]["hold"]["t"])))
    view = lambda r: {"name": r["spec"].name, "seg": r["seg"], "all": r["all"], "stage": r["stage"], "spec": r["spec"].model_dump()}
    return {"symbol": symbol, "interval": interval, "data_source": src, "bars": len(c), "tried": len(rows), "used_default": used_default,
            "train_pass": len(train_ok), "finalists": len(finalists), "passed": [view(r) for r in passed[:5]],
            "observe": [view(r) for r in obs[:3]], "top_train": [view(r) for r in train_ok[:10]],
            "stage_counts": {k: sum(r["stage"] == k for r in rows) for k in ("train_fail", "train_pass", "valid_fail", "hold_fail", "pass")},
            "periods": {"train_to": t1, "valid_to": t2, "hold_to": c[-1]["time"], "from": c[0]["time"]},
            "gate": GATE, "seconds": round(time.time() - t0, 1), "time": int(time.time())}


# ---------------------------------------------------------------- 봇 배치 · 교체
def _ap_bots() -> dict:
    return {bid: m for bid, m in state["bots"].items() if _paper and bid in _paper.bots}


def deploy(res: dict, row: dict, kind: str, team_note: str = "") -> str | None:
    if _paper is None:
        return None
    spec = StrategySpec(**row["spec"])
    tag = "✅" if kind == "pass" else "👀"
    spec.name = f"{tag} 오토 · {spec.name}"[:80]
    for bid, m in _ap_bots().items():                             # 같은 규칙이 이미 돌고 있으면 건너뜀
        if m["rule"] == row["name"] and m["symbol"] == res["symbol"] and m["interval"] == res["interval"]:
            return None
    bot = _paper.add_bot(spec, 10_000.0)
    state["bots"][bot.id] = {"kind": kind, "rule": row["name"], "symbol": res["symbol"], "interval": res["interval"], "created": time.time(),
                             "backtest": row["seg"], "team": team_note, "last_pos": None, "last_trades": 0}
    log(f"{'검증 통과' if kind == 'pass' else '관찰(미통과)'} 페이퍼 봇 시작: {res['symbol']} {res['interval']} — {row['name']}")
    _signal({"type": "deploy", "symbol": res["symbol"], "interval": res["interval"], "strategy": row["name"], "status": kind,
             "text": f"{'검증 통과' if kind == 'pass' else '관찰(미통과)'} 매매법을 페이퍼 봇으로 시작했습니다"})
    return bot.id


def retire(bid: str, why: str) -> None:
    m = state["bots"].pop(bid, None)
    b = _paper.bots.pop(bid, None) if _paper else None
    if b:
        st = b.sim.trades
        state["history"].append({**(m or {}), "retired": time.time(), "why": why, "name": b.spec.name, "trades": len(st),
                                 "net": round(sum(t.pnl for t in st), 2)})
        _paper.save()
        log(f"봇 정리: {b.spec.name} — {why}")


def _review_old():
    """정리 (포지션이 없을 때만): 지금 차트와 다른 코인·봉의 봇, 앞으로의 성적이 나쁜 봇."""
    tg = set(targets())
    for bid, m in list(_ap_bots().items()):
        b = _paper.bots[bid]
        tr = b.sim.trades
        if b.sim.position:
            continue
        if (m["symbol"], m["interval"]) not in tg:
            retire(bid, "차트 코인·봉이 바뀌어 정리")
            continue
        if len(tr) < 20:
            continue
        s = _seg([t.__dict__ for t in tr])
        if (s["pf"] or 0) < 0.9 or s["net"] < 0:
            retire(bid, f"실전 모의 {s['trades']}건 손익비 {s['pf']} · 손익 {s['net']} — 기준 미달")


# ---------------------------------------------------------------- 시그널 (봇 진입·청산)
def _signal(item: dict) -> None:
    item.setdefault("id", f"{int(time.time() * 1000)}-{len(signals)}")
    item.setdefault("created", int(time.time()))
    signals.append(item)


def watch_bots() -> int:
    n = 0
    for bid, m in list(_ap_bots().items()):
        b = _paper.bots[bid]
        p = b.sim.position
        cur = None if not p else f"{p.side}:{p.entry_time}"
        if cur and cur != m.get("last_pos"):
            side = "long" if p.side == 1 else "short"
            _signal({"type": "entry", "bot_id": bid, "symbol": m["symbol"], "interval": m["interval"], "side": side, "entry": p.entry_price,
                     "stop": p.stop, "take": p.take, "liq": p.liq_price, "leverage": p.leverage, "strategy": m["rule"], "status": m["kind"],
                     "text": f"{'롱' if side == 'long' else '숏'} 진입 {p.entry_price:,.6g}" + (f" · 손절 {p.stop:,.6g}" if p.stop else "") + (f" · 익절 {p.take:,.6g}" if p.take else "")})
            n += 1
        if len(b.sim.trades) > m.get("last_trades", 0):
            for t in b.sim.trades[m.get("last_trades", 0):]:
                _signal({"type": "exit", "bot_id": bid, "symbol": m["symbol"], "interval": m["interval"], "side": t.side, "pnl": round(t.pnl, 2),
                         "roe_pct": round(t.pnl_pct_on_margin, 2), "reason": t.exit_reason, "strategy": m["rule"], "status": m["kind"],
                         "text": f"{'롱' if t.side == 'long' else '숏'} 청산 ({t.exit_reason}) 손익 {t.pnl:+.2f} ({t.pnl_pct_on_margin:+.1f}%)"})
                n += 1
        m["last_pos"], m["last_trades"] = cur, len(b.sim.trades)
    return n


def recent_signals(since: int = 0) -> list[dict]:
    return [s for s in reversed(signals) if s["created"] > since]


# ---------------------------------------------------------------- 탐색 → 검토 → 배치
def targets() -> list[tuple[str, str]]:
    syms = [context["symbol"]]
    if SETTINGS["scope"] == "chart+watch":
        syms += [s for s in context.get("watch", []) if s != context["symbol"]][:3]
    ivs = [context["interval"]] + ([NEXT_IV[context["interval"]]] if SETTINGS["extra_interval"] and context["interval"] in NEXT_IV else [])
    return [(s, iv) for s in syms for iv in ivs]


def _context_key() -> str:
    return json.dumps([targets(), sorted(x["key"] + json.dumps(x.get("params"), sort_keys=True) for x in context["indicators"])])


def search_now(reason: str = "직접 요청") -> dict:
    if state["searching"]:
        return {"ok": False, "msg": "이미 탐색 중입니다."}
    state["searching"] = True
    threading.Thread(target=_search, args=(reason,), daemon=True).start()
    return {"ok": True, "msg": "매매법 탐색을 시작했습니다."}


def _search(reason: str):
    try:
        log(f"매매법 탐색 시작 ({reason}) — {', '.join(f'{s} {iv}' for s, iv in targets())}")
        results = []
        for s, iv in targets():
            try:
                r = evaluate(s, iv, context["indicators"])
            except Exception as e:
                r = {"symbol": s, "interval": iv, "error": str(e)[:160], "tried": 0}
            results.append(r)
            if r.get("error"):
                log(f"{s} {iv}: {r['error']}")
            else:
                log(f"{s} {iv}: 후보 {r['tried']}개 → 학습 통과 {r['train_pass']} → 검증·최종 통과 {len(r['passed'])} ({r['seconds']}초)")
        state["results"] = results
        state["last_search"] = time.time()
        state["last_context_key"] = _context_key()
        _deploy_from(results)
    finally:
        state["searching"] = False
        save()


def _team_review(results: list[dict]) -> dict[str, str]:
    """통과 후보를 에이전트 팀이 검토 (검증관 → 승인관 → 리스크 → 팀장). 승인관이 거부하면 배치하지 않는다."""
    from .team import engine as team
    cands = []
    for r in results:
        for i, row in enumerate(r.get("passed", [])[:3]):
            cands.append({"id": f"ap:{r['symbol']}:{r['interval']}:{i}", "kind": "autopilot", "target": row["name"], "symbol": r["symbol"],
                          "interval": r["interval"], "gate": {"passed": True, "train": row["seg"]["train"], "valid": row["seg"]["valid"],
                                                             "hold": row["seg"]["hold"], "tried": r["tried"], "test_trades": row["seg"]["hold"]["trades"],
                                                             "reason": f"3구간 통과 (후보 {r['tried']}개 중)"}})
    if not cands:
        return {}
    if any(x.status == "running" for x in team.runs.values()):
        return {c["id"]: "approve" for c in cands}
    run = team.run_pipeline("autopilot", "오토파일럿", extra={"candidates": cands})
    state["team_runs"].append(run.id)
    t0 = time.time()
    while run.status == "running" and time.time() - t0 < 600:
        time.sleep(1)
    return {a["candidate"]: a["decision"] for a in (run.results.get("approvals") or [])}


def _deploy_from(results: list[dict]):
    _review_old()
    room = SETTINGS["max_bots"] - len(_ap_bots())
    decisions = _team_review(results) if SETTINGS["team_review"] else {}
    deployed = 0
    # 코인·봉마다 1등부터 번갈아 (같은 진입 규칙에 청산만 다른 것은 사실상 같은 매매라 하나만)
    order = []
    for rank in range(3):
        for r in results:
            if rank < len(r.get("passed", [])):
                order.append((r, rank))
    for r, i in order:
        row = r["passed"][i]
        fam = _family(row["name"])
        if any(_family(m["rule"]) == fam and m["symbol"] == r["symbol"] and m["interval"] == r["interval"] for m in _ap_bots().values()):
            continue
        cid = f"ap:{r['symbol']}:{r['interval']}:{i}"
        if decisions and decisions.get(cid) == "reject":
            log(f"에이전트 팀 승인관이 거부해 배치 안 함: {row['name']}")
            continue
        if room <= 0:
            _make_room()
            room = SETTINGS["max_bots"] - len(_ap_bots())
        if room > 0 and deploy(r, row, "pass", "팀 승인" if decisions else ""):
            room -= 1
            deployed += 1
    if not deployed and SETTINGS["observe_if_none"] and not any(m["kind"] == "pass" for m in _ap_bots().values()):
        for r in results:
            obs = r.get("observe") or []
            if obs and room > 0 and not any(m["symbol"] == r["symbol"] and m["interval"] == r["interval"] for m in _ap_bots().values()):
                if deploy(r, obs[0], "observe"):
                    room -= 1
    if not any(r.get("passed") for r in results):
        log("검증을 통과한 매매법이 없습니다 — 과거 데이터에서 수수료를 이기는 규칙을 찾지 못함 (흔한 결과)")


def _make_room():
    """관찰 봇 중 포지션 없는 가장 오래된 것부터 정리."""
    for bid, m in sorted(_ap_bots().items(), key=lambda kv: kv[1]["created"]):
        if m["kind"] == "observe" and not _paper.bots[bid].sim.position:
            retire(bid, "검증 통과 매매법에 자리를 내줌")
            return


# ---------------------------------------------------------------- AI 상시 감시
def _copilot_watch():
    from .quant import copilot
    sym, iv = context["symbol"], context["interval"]
    r = copilot.live(sym, iv, max_age=900)
    a = r["analysis"]
    key = f"{sym}:{iv}"
    prev = state["copilot_bias"].get(key)
    state["copilot_bias"][key] = a["bias"]
    if prev and prev != a["bias"]:
        name = {"long": "롱 우위", "short": "숏 우위", "neutral": "중립"}
        _signal({"type": "ai", "symbol": sym, "interval": iv, "status": "ai", "strategy": "실시간 AI",
                 "text": f"AI 판단 변경: {name[prev]} → {name[a['bias']]} (확신 {a['confidence']}%) — {a['headline'][:90]}"})


def tick():
    if not SETTINGS["enabled"] or _paper is None:
        return
    now = time.time()
    watch_bots()
    if not context.get("updated") and now - _started < 120:      # 앱을 막 켰으면 화면이 차트 지표를 보내 줄 때까지 기다림
        return
    due = now - state["last_search"] >= SETTINGS["search_every_hours"] * 3600
    changed = state["last_context_key"] != _context_key() and now - context.get("updated", 0) > 60   # 지표를 바꾸고 1분 뒤
    if (due or changed) and not state["searching"]:
        state["searching"] = True
        threading.Thread(target=_search, args=("차트 지표 변경" if changed and not due else "정기 탐색",), daemon=True).start()
    if SETTINGS["copilot_every_min"] and now - state["last_copilot"] >= SETTINGS["copilot_every_min"] * 60:
        state["last_copilot"] = now
        try:
            _copilot_watch()
        except Exception as e:
            log(f"실시간 AI 감시 오류: {str(e)[:100]}")
    if SETTINGS["team_monitor_min"] and now - state["last_team_monitor"] >= SETTINGS["team_monitor_min"] * 60:
        from .team import engine as team
        if not any(x.status == "running" for x in team.runs.values()):
            state["last_team_monitor"] = now
            run = team.run_pipeline("monitor", "오토파일럿 상시 감시")
            state["team_runs"].append(run.id)
    save()


def status() -> dict:
    bots = []
    for bid, m in _ap_bots().items():
        b = _paper.bots[bid]
        p = b.sim.position
        tr = b.sim.trades
        s = _seg([t.__dict__ for t in tr])
        bots.append({"id": bid, "name": b.spec.name, **{k: m[k] for k in ("kind", "rule", "symbol", "interval", "created", "backtest")},
                     "running": b.running, "equity": round(b.sim.equity(b.last_price) if b.last_price else b.sim.cash, 2),
                     "forward": s, "position": None if not p else {"side": "long" if p.side == 1 else "short", "entry": p.entry_price,
                                                                 "stop": p.stop, "take": p.take, "liq": p.liq_price, "leverage": p.leverage},
                     "last_price": b.last_price})
    return {"settings": SETTINGS, "context": context, "usable": usable(context["indicators"]), "targets": targets(),
            "searching": state["searching"], "last_search": state["last_search"],
            "next_search": state["last_search"] + SETTINGS["search_every_hours"] * 3600,
            "results": [{k: v for k, v in r.items() if k not in ("top_train",)} for r in state["results"]],
            "bots": bots, "history": state["history"][-20:], "log": list(state["log"])[:60], "gate": GATE,
            "team_runs": state["team_runs"][-5:], "copilot_bias": state["copilot_bias"]}


async def run_forever():
    await asyncio.sleep(5)
    while True:
        try:
            await asyncio.to_thread(tick)
        except Exception as e:
            log(f"오류: {str(e)[:120]}")
        await asyncio.sleep(20)


_task = None
_started = time.time()


def start():
    global _task, _started
    _started = time.time()
    if _task is None:
        _task = asyncio.create_task(run_forever())
