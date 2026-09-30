"""전략 자동 개선 · 거래 복기(학습 노트).

1. 복기: 각 거래의 진입 시점 시장 상태(추세·ADX·RSI·변동성·이격·거래량·슈퍼트렌드·펀딩)를 기록하고
   익절 거래는 '왜 됐는지', 손실 거래는 '무엇이 문제였는지'를 문장으로 남긴다.
2. 개선 후보: 손실 거래에 자주 나타난 문제를 막는 필터(추세 필터, ADX, 과매수 추격 금지, 거래량 확인,
   슈퍼트렌드 일치, 변동성 상한, 펀딩 과열)와 손절·익절 조정을 만든다.
3. 검증: 데이터 앞 70%(학습 구간)에서 좋아지고, 뒤 30%(검증 구간, 개선에 쓰지 않은 데이터)에서도 나빠지지
   않을 때만 채택한다. 과거에만 맞춘 과최적화를 줄이기 위한 장치다.
"""
from __future__ import annotations

import copy
from dataclasses import asdict

from . import backtest, config, indicators as ind, llm
from .strategy import Condition, ConditionGroup, IndicatorSpec, StrategySpec

TRAIN_SHARE = 0.7


# ---------------------------------------------------------------- 진입 시점 특징
def feature_series(candles: list[dict], deriv: dict | None = None) -> dict:
    close = [b["close"] for b in candles]
    atr = ind.atr(candles)
    atr_pct = [a / c * 100 if a else None for a, c in zip(atr, close)]
    valid = sorted(v for v in atr_pct if v is not None)
    vol_ma = ind.sma([b["volume"] for b in candles], 20)
    f = {
        "ema50": ind.ema(close, 50), "ema200": ind.ema(close, 200), "atr": atr, "atr_pct": atr_pct,
        "atr_p80": valid[int(len(valid) * 0.8)] if valid else None,
        "adx": ind.adx(candles)["adx"], "rsi": ind.rsi(close), "st": ind.supertrend(candles)["trend"],
        "vol_ratio": [b["volume"] / m if m else None for b, m in zip(candles, vol_ma)],
        "bb_width": ind.bbands(close)["width"],
    }
    if deriv and deriv.get("funding"):
        from .strategy import _align
        f["funding"] = _align(candles, deriv["funding"])
    return f


def _index_before(candles: list[dict], t: int) -> int:
    """진입은 신호 다음 봉 시가에 체결되므로, 신호가 난 봉 = 진입 시각 직전 봉."""
    lo, hi = 0, len(candles) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if candles[mid]["time"] < t:
            lo = mid
        else:
            hi = mid - 1
    return lo


def trade_features(candles: list[dict], fs: dict, trade: dict) -> dict:
    i = _index_before(candles, trade["entry_time"])
    side = 1 if trade["side"] == "long" else -1
    c = candles[i]["close"]
    g = lambda k: fs[k][i] if k in fs and i < len(fs[k]) else None
    e200, e50, atr = g("ema200"), g("ema50"), g("atr")
    bars_held = sum(1 for b in candles if trade["entry_time"] <= b["time"] <= trade["exit_time"])
    return {
        "with_trend": None if e200 is None else (side * (c - e200) > 0),
        "adx": g("adx"), "rsi": g("rsi"), "atr_pct": g("atr_pct"),
        "high_vol": (g("atr_pct") or 0) > (fs.get("atr_p80") or 1e9),
        "stretch_atr": side * (c - e50) / atr if e50 and atr else None,
        "vol_ratio": g("vol_ratio"), "st_agree": None if g("st") is None else (g("st") == side),
        "funding": g("funding"), "bars_held": bars_held,
    }


def explain(trade: dict, f: dict) -> dict:
    """거래 한 건 복기 문장."""
    side_kr = "롱" if trade["side"] == "long" else "숏"
    good, bad = [], []
    if f["with_trend"] is True:
        good.append(f"큰 추세(EMA200) 방향 {side_kr}")
    elif f["with_trend"] is False:
        bad.append(f"큰 추세(EMA200) 역방향 {side_kr}")
    if f["adx"] is not None:
        (good if f["adx"] >= 25 else bad if f["adx"] < 18 else [])\
            .append(f"ADX {f['adx']:.0f} ({'추세 뚜렷' if f['adx'] >= 25 else '방향성 약한 장'})")
    if f["st_agree"] is True:
        good.append("슈퍼트렌드 같은 방향")
    elif f["st_agree"] is False:
        bad.append("슈퍼트렌드 반대 방향")
    if f["stretch_atr"] is not None and f["stretch_atr"] > 2.5:
        bad.append(f"EMA50에서 {f['stretch_atr']:.1f} ATR 떨어진 곳에서 추격 진입")
    if f["rsi"] is not None:
        if (trade["side"] == "long" and f["rsi"] >= 70) or (trade["side"] == "short" and f["rsi"] <= 30):
            bad.append(f"RSI {f['rsi']:.0f} {'과매수' if trade['side'] == 'long' else '과매도'} 구간 진입")
    if f["vol_ratio"] is not None:
        if f["vol_ratio"] >= 1.5:
            good.append(f"거래량 평균의 {f['vol_ratio']:.1f}배 동반")
        elif f["vol_ratio"] < 0.7:
            bad.append(f"거래량 부족 (평균의 {f['vol_ratio']:.1f}배)")
    if f["high_vol"]:
        bad.append(f"변동성 상위 20% 구간 (ATR {f['atr_pct']:.2f}%)")
    if f["funding"] is not None and trade["side"] == "long" and f["funding"] > 0.05:
        bad.append(f"펀딩비 {f['funding']:.3f}% 롱 과열")
    win = trade["pnl"] > 0
    reason = {"take_profit": "익절가 도달", "stop_loss": "손절가 도달", "trailing_stop": "추적손절",
              "liquidation": "강제청산", "reverse_signal": "반대 신호로 전환", "exit_signal": "청산 신호",
              "end_of_test": "테스트 종료"}.get(trade["exit_reason"], trade["exit_reason"])
    if win:
        summary = f"{side_kr} 익절 ({reason}, {f['bars_held']}봉 보유). " + (
            "잘 된 이유: " + ", ".join(good) if good else "특별히 유리한 조건 없이 수익")
        if bad:
            summary += f". 다만 {', '.join(bad)} — 운이 따른 부분"
    else:
        summary = f"{side_kr} 손실 ({reason}, {f['bars_held']}봉 보유). " + (
            "원인 후보: " + ", ".join(bad) if bad else "진입 조건은 괜찮았으나 가격이 반대로 움직임 (정상적인 손실 범위)")
    return {"entry_time": trade["entry_time"], "exit_time": trade["exit_time"], "side": trade["side"],
            "pnl": trade["pnl"], "win": win, "good": good, "bad": bad, "note": summary}


# ---------------------------------------------------------------- 개선 후보
def _uid(spec: StrategySpec, base: str) -> str:
    ids = {i.id for i in spec.indicators}
    k, n = base, 2
    while k in ids:
        k, n = f"{base}{n}", n + 1
    return k


def _add_filter(spec: StrategySpec, ind_spec: IndicatorSpec | None, long_c: Condition | None,
                short_c: Condition | None) -> StrategySpec:
    s = copy.deepcopy(spec)
    if ind_spec:
        same = next((i for i in s.indicators if i.type == ind_spec.type and i.params() == ind_spec.params()), None)
        if same:
            ref_id = same.id
        else:
            ref_id = _uid(s, ind_spec.id)
            s.indicators.append(ind_spec.model_copy(update={"id": ref_id}))
        fix = lambda c: c and Condition(left=c.left.replace("$", ref_id), op=c.op, right=c.right.replace("$", ref_id))
        long_c, short_c = fix(long_c), fix(short_c)
    for grp, c in (("long_entry", long_c), ("short_entry", short_c)):
        g = getattr(s, grp)
        if g and c:
            if g.logic == "any":   # OR 그룹이면 AND 필터를 걸 수 없으므로 감싼다: 기존 조건 중 하나 AND 필터
                return s          # (DSL이 중첩을 지원하지 않아 이 후보는 건너뜀)
            g.conditions.append(c)
    return s


def candidates(spec: StrategySpec, fs: dict, has_funding: bool) -> list[tuple[str, StrategySpec, callable]]:
    """(설명, 새 전략, 거래 특징으로 이 필터를 통과하는지 판단하는 함수)."""
    out = []
    E = lambda i_, l, s: _add_filter(spec, i_, l, s)
    out.append(("큰 추세 방향으로만 진입 (롱은 EMA200 위, 숏은 아래)",
                E(IndicatorSpec(id="ema200", type="ema", length=200), Condition(left="close", op=">", right="$"),
                  Condition(left="close", op="<", right="$")), lambda f: f["with_trend"] is not False))
    out.append(("ADX 20 이상 추세장에서만 진입",
                E(IndicatorSpec(id="adx_f", type="adx", length=14), Condition(left="$.adx", op=">=", right="20"),
                  Condition(left="$.adx", op=">=", right="20")), lambda f: f["adx"] is None or f["adx"] >= 20))
    out.append(("ADX 25 미만 횡보장에서만 진입 (역추세 전략용)",
                E(IndicatorSpec(id="adx_f", type="adx", length=14), Condition(left="$.adx", op="<", right="25"),
                  Condition(left="$.adx", op="<", right="25")), lambda f: f["adx"] is None or f["adx"] < 25))
    out.append(("과매수에서 롱·과매도에서 숏 추격 금지 (RSI 70/30)",
                E(IndicatorSpec(id="rsi_f", type="rsi", length=14), Condition(left="$", op="<", right="70"),
                  Condition(left="$", op=">", right="30")),
                lambda f: f["rsi"] is None or not ((f["rsi"] >= 70) or (f["rsi"] <= 30))))
    out.append(("거래량이 20봉 평균의 1.2배 이상일 때만",
                E(IndicatorSpec(id="vol_f", type="volume_sma", length=20), Condition(left="volume", op=">", right="$*1.2"),
                  Condition(left="volume", op=">", right="$*1.2")), lambda f: f["vol_ratio"] is None or f["vol_ratio"] >= 1.2))
    out.append(("슈퍼트렌드와 같은 방향일 때만",
                E(IndicatorSpec(id="st_f", type="supertrend", length=10, mult=3.0), Condition(left="$.trend", op=">", right="0"),
                  Condition(left="$.trend", op="<", right="0")), lambda f: f["st_agree"] is not False))
    widths = sorted(v for v in fs["bb_width"] if v is not None)
    if widths:
        cap = round(widths[int(len(widths) * 0.85)], 3)
        out.append((f"변동성 과열 구간(볼린저 폭 상위 15%, {cap}% 초과) 진입 금지",
                    E(IndicatorSpec(id="bb_f", type="bb", length=20, mult=2.0), Condition(left="$.width", op="<", right=str(cap)),
                      Condition(left="$.width", op="<", right=str(cap))), lambda f: not f["high_vol"]))
    if has_funding:
        out.append(("펀딩비 과열(0.05% 초과) 시 롱 금지 / 음수 과열(-0.03% 미만) 시 숏 금지",
                    E(None, Condition(left="funding", op="<", right="0.05"), Condition(left="funding", op=">", right="-0.03")),
                    lambda f: f["funding"] is None or -0.03 < f["funding"] < 0.05))
    # 손절·익절 조정
    r = spec.risk
    if r.stop_loss_pct:
        for sm, tm, label in ((1.5, 1.0, "손절 폭 1.5배로 넓힘"), (1.0, 1.5, "익절 목표 1.5배로 늘림"),
                              (0.75, 1.0, "손절 폭 25% 좁힘"), (1.5, 1.5, "손절·익절 모두 1.5배")):
            s = copy.deepcopy(spec)
            s.risk.stop_loss_pct = round(r.stop_loss_pct * sm, 3)
            if r.take_profit_pct:
                s.risk.take_profit_pct = round(r.take_profit_pct * tm, 3)
            elif tm != 1.0:
                continue
            out.append((f"{label} (손절 {s.risk.stop_loss_pct}% / 익절 {s.risk.take_profit_pct}%)", s, None))
    else:
        s = copy.deepcopy(spec)
        s.risk.atr_stop_mult, s.risk.atr_tp_mult = 2.0, 3.0
        out.append(("ATR 기준 손절(2배)·익절(3배) 추가", s, None))
    if not r.trailing_stop_pct:
        s = copy.deepcopy(spec)
        s.risk.trailing_stop_pct = round((r.stop_loss_pct or 2.0) * 1.2, 3)
        out.append((f"추적손절 {s.risk.trailing_stop_pct}% 추가 (수익 반납 방지)", s, None))
    return out


# ---------------------------------------------------------------- 평가
def _score(trades: list[dict]) -> dict:
    pnl = sum(t["pnl"] for t in trades)
    wins = [t for t in trades if t["pnl"] > 0]
    gw, gl = sum(t["pnl"] for t in wins), -sum(t["pnl"] for t in trades if t["pnl"] <= 0)
    return {"trades": len(trades), "net_pnl": round(pnl, 2),
            "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else None,
            "profit_factor": round(gw / gl, 2) if gl > 0 else None}


def _evaluate(spec: StrategySpec, candles: list[dict], deriv: dict | None, split_time: int) -> dict:
    res = backtest.run(spec, candles, deriv)
    tr = [t for t in res["trades"] if t["entry_time"] < split_time]
    te = [t for t in res["trades"] if t["entry_time"] >= split_time]
    return {"train": _score(tr), "test": _score(te), "all": res["metrics"], "trades": res["trades"]}


def improve(spec: StrategySpec, candles: list[dict], deriv: dict | None = None, with_ai: bool = False) -> dict:
    split_time = candles[int(len(candles) * TRAIN_SHARE)]["time"]
    base = _evaluate(spec, candles, deriv, split_time)
    fs = feature_series(candles, deriv)
    notes = [explain(t, trade_features(candles, fs, t)) for t in base["trades"]]

    # 손실·익절 패턴 요약
    def tally(rows, key):
        cnt: dict[str, list] = {}
        for n in rows:
            for item in n[key]:
                k = _trait_key(item) if key == "good" else _cause_key(item)
                cnt.setdefault(k, []).append(n["pnl"])
        return sorted(({"cause": k, "count": len(v), "pnl": round(sum(v), 2)} for k, v in cnt.items()),
                      key=lambda x: (-x["count"], x["pnl"]))
    losses = [n for n in notes if not n["win"]]
    wins = [n for n in notes if n["win"]]

    # 후보 사전 선별: 학습 구간 거래만으로 "막았을 손실 − 놓쳤을 수익" 추정
    train_trades = [t for t in base["trades"] if t["entry_time"] < split_time]
    feats = [trade_features(candles, fs, t) for t in train_trades]
    cands = candidates(spec, fs, bool(deriv and deriv.get("funding")))
    ranked = []
    for name, s, passes in cands:
        if passes is None:
            ranked.append((0.0, name, s))
            continue
        removed = [t for t, f in zip(train_trades, feats) if not passes(f)]
        saved = -sum(t["pnl"] for t in removed if t["pnl"] <= 0) - sum(t["pnl"] for t in removed if t["pnl"] > 0)
        if removed and saved > 0:
            ranked.append((saved, name, s))
    ranked.sort(key=lambda x: -x[0])
    shortlist = ranked[:8]

    results = []
    min_trades = max(3, int(base["train"]["trades"] * 0.3))
    for est, name, s in shortlist:
        try:
            ev = _evaluate(s, candles, deriv, split_time)
        except ValueError:
            continue
        passed = (ev["train"]["net_pnl"] > base["train"]["net_pnl"]
                  and ev["train"]["trades"] >= min_trades
                  and ev["test"]["net_pnl"] >= base["test"]["net_pnl"]
                  and ev["test"]["trades"] >= 1)
        results.append({"change": name, "estimated_saving": round(est, 2), "train": ev["train"], "test": ev["test"],
                        "passed": passed, "_spec": s})
    # 통과한 것 중 학습 구간 성과가 가장 좋은 것 1개, 이어서 두 번째 개선을 겹쳐 시도
    passed = sorted((r for r in results if r["passed"]), key=lambda r: -r["train"]["net_pnl"])
    applied, new_spec, changes = False, spec, []
    if passed:
        best = passed[0]
        new_spec, changes, applied = best["_spec"], [best["change"]], True
        cur = _evaluate(new_spec, candles, deriv, split_time)
        for r in passed[1:3]:
            combo = _combine(new_spec, r["_spec"], spec)
            if combo is None:
                continue
            ev = _evaluate(combo, candles, deriv, split_time)
            if ev["train"]["net_pnl"] > cur["train"]["net_pnl"] and ev["test"]["net_pnl"] >= cur["test"]["net_pnl"]:
                new_spec, cur = combo, ev
                changes.append(r["change"])
        after = cur
    else:
        after = base

    report = {
        "applied": applied, "changes": changes,
        "baseline": {"train": base["train"], "test": base["test"]},
        "after": {"train": after["train"], "test": after["test"]},
        "split_time": split_time,
        "candidates": [{k: v for k, v in r.items() if k != "_spec"} for r in results],
        "loss_causes": tally(losses, "bad")[:8], "win_traits": tally(wins, "good")[:8],
        "journal": notes[-60:],
        "spec": new_spec.model_dump(),
        "ai_summary": None,
    }
    if with_ai and config.llm_enabled():
        import json
        report["ai_summary"] = llm.text(
            "너는 퀀트 트레이딩 코치다. 아래 전략 복기 결과(손실 원인 집계, 익절 특징, 개선 후보와 학습/검증 성과)를 보고 "
            "한국어로 5~7문장 코멘트를 쓴다. 무엇이 수익을 냈고 무엇이 손실을 냈는지, 적용된 변경이 왜 타당한지(또는 왜 "
            "아무것도 적용되지 않았는지), 다음에 시도할 만한 것을 구체적으로 말한다. 과최적화 위험도 짚는다.",
            json.dumps({k: report[k] for k in ("changes", "baseline", "after", "candidates", "loss_causes", "win_traits")},
                       ensure_ascii=False, default=str), effort="medium")
    return report


def _trait_key(text: str) -> str:
    if "추세(EMA200) 방향" in text:
        return "큰 추세(EMA200) 방향 진입"
    if text.startswith("ADX"):
        return "ADX 25 이상 (추세 뚜렷)"
    if "거래량" in text:
        return "거래량 평균의 1.5배 이상 동반"
    return text


def _cause_key(text: str) -> str:
    for k in ("추세(EMA200) 역방향", "방향성 약한 장", "슈퍼트렌드 반대", "추격 진입", "과매수", "과매도", "거래량 부족",
              "변동성 상위", "펀딩비"):
        if k in text:
            return {"방향성 약한 장": "ADX 낮은 장(방향성 약함)", "추세(EMA200) 역방향": "큰 추세 역방향 진입",
                    "추격 진입": "EMA50에서 멀리 떨어진 추격 진입"}.get(k, k)
    return text


def _combine(a: StrategySpec, b: StrategySpec, base: StrategySpec) -> StrategySpec | None:
    """a 에 (b - base) 변경분을 덧붙인다. 지표·조건 추가 또는 리스크 변경 한 가지씩만 지원."""
    s = copy.deepcopy(a)
    new_inds = [i for i in b.indicators if i.id not in {x.id for x in base.indicators}]
    for i in new_inds:
        if i.id in {x.id for x in s.indicators}:
            return None
        s.indicators.append(i)
    for grp in ("long_entry", "short_entry"):
        gb, g0, gs = getattr(b, grp), getattr(base, grp), getattr(s, grp)
        if gb and g0 and gs:
            gs.conditions += gb.conditions[len(g0.conditions):]
    if b.risk != base.risk:
        if s.risk != base.risk:
            return None
        s.risk = copy.deepcopy(b.risk)
    return s


def run_for(spec: StrategySpec, bars: int = 1500, with_ai: bool = False) -> dict:
    from .data import market
    candles, src = market.candles(spec.symbol, spec.interval, bars)
    deriv = market.derivatives(spec.symbol, spec.interval, 500) if backtest.needs_derivatives(spec) else None
    rep = improve(spec, candles, deriv, with_ai)
    rep["data_source"] = src
    return rep
