"""매매법 라이브러리 — 널리 알려진 매매법을 전략 JSON 으로. 불러와서 백테스트·페이퍼 봇에 바로 쓴다.
(유명하다고 수익이 나는 것은 아니다. 반드시 백테스트와 모의 매매로 확인)"""
from __future__ import annotations


def _c(l, op, r):
    return {"left": l, "op": op, "right": str(r)}


def _g(*conds, logic="all"):
    return {"logic": logic, "conditions": list(conds)}


LIBRARY = [
    {"key": "turtle", "cat": "돌파", "name": "터틀 트레이딩 (돈치안 20/10)", "desc": "20봉 최고가를 넘으면 롱, 최저가를 깨면 숏. 반대쪽 10봉 채널에서 청산. 추세장에서 크게 먹고 횡보장에서 자주 잃는 대표 추세추종",
     "spec": {"indicators": [{"id": "dc20", "type": "donchian", "length": 20}, {"id": "dc10", "type": "donchian", "length": 10}],
              "long_entry": _g(_c("close", ">", "dc20.upper[1]")), "short_entry": _g(_c("close", "<", "dc20.lower[1]")),
              "long_exit": _g(_c("close", "<", "dc10.lower[1]")), "short_exit": _g(_c("close", ">", "dc10.upper[1]")),
              "risk": {"atr_stop_mult": 2.0}}},
    {"key": "golden", "cat": "추세", "name": "골든·데드 크로스 (EMA 50/200)", "desc": "EMA50 이 EMA200 을 위로 뚫으면 롱, 아래로 뚫으면 숏. 느리지만 큰 추세만 탐",
     "spec": {"indicators": [{"id": "e50", "type": "ema", "length": 50}, {"id": "e200", "type": "ema", "length": 200}],
              "long_entry": _g(_c("e50", "crosses_above", "e200")), "short_entry": _g(_c("e50", "crosses_below", "e200")), "risk": {"atr_stop_mult": 3.0}}},
    {"key": "ema_adx", "cat": "추세", "name": "EMA 20/50 교차 + ADX 필터", "desc": "EMA20·50 교차를 ADX 20 이상(추세가 있을 때)에서만",
     "spec": {"indicators": [{"id": "e20", "type": "ema", "length": 20}, {"id": "e50", "type": "ema", "length": 50}, {"id": "adx", "type": "adx", "length": 14}],
              "long_entry": _g(_c("e20", "crosses_above", "e50"), _c("adx.adx", ">", 20)), "short_entry": _g(_c("e20", "crosses_below", "e50"), _c("adx.adx", ">", 20)),
              "risk": {"atr_stop_mult": 2.0, "atr_tp_mult": 4.0}}},
    {"key": "supertrend", "cat": "추세", "name": "슈퍼트렌드 추세 추종", "desc": "슈퍼트렌드(10, 3) 방향이 바뀔 때마다 진입·반전",
     "spec": {"indicators": [{"id": "st", "type": "supertrend", "length": 10, "mult": 3}],
              "long_entry": _g(_c("st.trend", "crosses_above", 0)), "short_entry": _g(_c("st.trend", "crosses_below", 0))}},
    {"key": "rsi2", "cat": "역추세", "name": "RSI(2) 눌림 매수 (래리 코너스)", "desc": "200 이평 위에서 RSI(2) 가 10 아래로 떨어지면 롱, 70 넘으면 청산. 상승장 짧은 눌림을 삼",
     "spec": {"indicators": [{"id": "rsi2", "type": "rsi", "length": 2}, {"id": "s200", "type": "sma", "length": 200}],
              "long_entry": _g(_c("close", ">", "s200"), _c("rsi2", "<", 10)), "long_exit": _g(_c("rsi2", ">", 70)), "risk": {"stop_loss_pct": 4.0}}},
    {"key": "bb_revert", "cat": "역추세", "name": "볼린저 밴드 평균 회귀", "desc": "종가가 하단 밖에서 안으로 들어오면 롱(상단은 숏), 중심선에서 청산. 횡보장용",
     "spec": {"indicators": [{"id": "bb", "type": "bb", "length": 20, "mult": 2}],
              "long_entry": _g(_c("close", "crosses_above", "bb.lower")), "short_entry": _g(_c("close", "crosses_below", "bb.upper")),
              "long_exit": _g(_c("close", ">", "bb.middle")), "short_exit": _g(_c("close", "<", "bb.middle")), "risk": {"atr_stop_mult": 1.5}}},
    {"key": "bb_break", "cat": "돌파", "name": "볼린저 돌파 + 거래량 2배", "desc": "종가가 상단(하단)을 뚫고 거래량이 평소 2배 이상이면 추세 시작으로 보고 진입",
     "spec": {"indicators": [{"id": "bb", "type": "bb", "length": 20, "mult": 2}, {"id": "vma", "type": "volume_sma", "length": 20}],
              "long_entry": _g(_c("close", "crosses_above", "bb.upper"), _c("volume", ">", "vma*2")), "short_entry": _g(_c("close", "crosses_below", "bb.lower"), _c("volume", ">", "vma*2")),
              "long_exit": _g(_c("close", "<", "bb.middle")), "short_exit": _g(_c("close", ">", "bb.middle")), "risk": {"atr_stop_mult": 2.0}}},
    {"key": "macd200", "cat": "추세", "name": "MACD 교차 + EMA200 필터", "desc": "EMA200 위에서는 MACD 골든크로스 롱만, 아래에서는 데드크로스 숏만",
     "spec": {"indicators": [{"id": "macd", "type": "macd", "fast": 12, "slow": 26, "signal": 9}, {"id": "e200", "type": "ema", "length": 200}],
              "long_entry": _g(_c("macd.line", "crosses_above", "macd.signal"), _c("close", ">", "e200")),
              "short_entry": _g(_c("macd.line", "crosses_below", "macd.signal"), _c("close", "<", "e200")), "risk": {"atr_stop_mult": 1.5, "atr_tp_mult": 3.0}}},
    {"key": "ichimoku", "cat": "추세", "name": "일목균형표 (전환선×기준선, 구름 위/아래)", "desc": "구름 위에서 전환선이 기준선을 뚫으면 롱, 구름 아래 반대면 숏, 기준선 이탈 청산",
     "spec": {"indicators": [{"id": "ich", "type": "ichimoku"}],
              "long_entry": _g(_c("ich.tenkan", "crosses_above", "ich.kijun"), _c("close", ">", "ich.span_a"), _c("close", ">", "ich.span_b")),
              "short_entry": _g(_c("ich.tenkan", "crosses_below", "ich.kijun"), _c("close", "<", "ich.span_a"), _c("close", "<", "ich.span_b")),
              "long_exit": _g(_c("close", "crosses_below", "ich.kijun")), "short_exit": _g(_c("close", "crosses_above", "ich.kijun"))}},
    {"key": "psar_adx", "cat": "추세", "name": "파라볼릭 SAR + ADX", "desc": "SAR 방향 전환을 ADX 25 이상일 때만",
     "spec": {"indicators": [{"id": "sar", "type": "psar"}, {"id": "adx", "type": "adx", "length": 14}],
              "long_entry": _g(_c("sar.trend", "crosses_above", 0), _c("adx.adx", ">", 25)), "short_entry": _g(_c("sar.trend", "crosses_below", 0), _c("adx.adx", ">", 25)),
              "long_exit": _g(_c("sar.trend", "crosses_below", 0)), "short_exit": _g(_c("sar.trend", "crosses_above", 0))}},
    {"key": "stochrsi_pull", "cat": "눌림", "name": "스토캐스틱 RSI 눌림 (EMA50 방향)", "desc": "EMA50 위에서 스토캐스틱 RSI 가 20 아래에서 위로 교차하면 롱 (아래면 반대)",
     "spec": {"indicators": [{"id": "sr", "type": "stochrsi", "length": 14, "k_smooth": 3, "d_smooth": 3}, {"id": "e50", "type": "ema", "length": 50}],
              "long_entry": _g(_c("sr.k", "crosses_above", "sr.d"), _c("sr.k", "<", 20), _c("close", ">", "e50")),
              "short_entry": _g(_c("sr.k", "crosses_below", "sr.d"), _c("sr.k", ">", 80), _c("close", "<", "e50")),
              "long_exit": _g(_c("sr.k", ">", 80)), "short_exit": _g(_c("sr.k", "<", 20)), "risk": {"atr_stop_mult": 1.5}}},
    {"key": "vwap_trend", "cat": "일중", "name": "VWAP 되찾기 (EMA50 방향)", "desc": "일중: EMA50 위에서 가격이 VWAP 을 다시 위로 뚫으면 롱 (반대는 숏). 1~15분봉용",
     "spec": {"indicators": [{"id": "vw", "type": "vwap"}, {"id": "e50", "type": "ema", "length": 50}],
              "long_entry": _g(_c("close", "crosses_above", "vw"), _c("close", ">", "e50")), "short_entry": _g(_c("close", "crosses_below", "vw"), _c("close", "<", "e50")),
              "risk": {"atr_stop_mult": 1.5, "atr_tp_mult": 2.5}}, "interval": "15m"},
    {"key": "willr200", "cat": "역추세", "name": "윌리엄스 %R 반전 + EMA200", "desc": "EMA200 위에서 %R 이 -80 을 위로 넘으면 롱",
     "spec": {"indicators": [{"id": "wr", "type": "willr", "length": 14}, {"id": "e200", "type": "ema", "length": 200}],
              "long_entry": _g(_c("wr", "crosses_above", -80), _c("close", ">", "e200")), "short_entry": _g(_c("wr", "crosses_below", -20), _c("close", "<", "e200")),
              "long_exit": _g(_c("wr", ">", -20)), "short_exit": _g(_c("wr", "<", -80)), "risk": {"atr_stop_mult": 2.0}}},
    {"key": "mfi", "cat": "역추세", "name": "MFI 과매도·과매수 반전", "desc": "거래량까지 본 RSI(MFI) 가 20 을 위로 넘으면 롱, 80 을 아래로 넘으면 숏",
     "spec": {"indicators": [{"id": "mfi", "type": "mfi", "length": 14}],
              "long_entry": _g(_c("mfi", "crosses_above", 20)), "short_entry": _g(_c("mfi", "crosses_below", 80)),
              "long_exit": _g(_c("mfi", ">", 70)), "short_exit": _g(_c("mfi", "<", 30)), "risk": {"atr_stop_mult": 2.0}}},
    {"key": "utbot", "cat": "추세", "name": "UT Bot (ATR 추적손절 전환)", "desc": "ATR(10)×1 추적손절선을 종가가 넘으면 진입·반전. 짧고 빠른 추세추종",
     "spec": {"indicators": [{"id": "ut", "type": "atr_stop", "length": 10, "mult": 1.0}],
              "long_entry": _g(_c("ut.trend", "crosses_above", 0)), "short_entry": _g(_c("ut.trend", "crosses_below", 0))}},
    {"key": "hma", "cat": "추세", "name": "HMA 기울기 추세", "desc": "헐 이동평균(55)이 3봉 연속 오르면 롱, 3봉 연속 내리면 숏",
     "spec": {"indicators": [{"id": "h", "type": "hma", "length": 55}],
              "long_entry": _g(_c("h", "rising", 3)), "short_entry": _g(_c("h", "falling", 3)), "risk": {"atr_stop_mult": 2.5}}},
    {"key": "aroon", "cat": "추세", "name": "아룬 추세 전환", "desc": "아룬 업이 다운을 위로 교차하면 롱",
     "spec": {"indicators": [{"id": "ar", "type": "aroon", "length": 25}],
              "long_entry": _g(_c("ar.up", "crosses_above", "ar.down")), "short_entry": _g(_c("ar.up", "crosses_below", "ar.down")), "risk": {"atr_stop_mult": 2.0}}},
    {"key": "keltner", "cat": "돌파", "name": "켈트너 채널 돌파", "desc": "EMA20 ± ATR×2 채널을 종가가 뚫으면 진입, 중심선 복귀 청산",
     "spec": {"indicators": [{"id": "kc", "type": "keltner", "length": 20, "mult": 2}],
              "long_entry": _g(_c("close", "crosses_above", "kc.upper")), "short_entry": _g(_c("close", "crosses_below", "kc.lower")),
              "long_exit": _g(_c("close", "<", "kc.middle")), "short_exit": _g(_c("close", ">", "kc.middle"))}},
    {"key": "funding_fade", "cat": "파생", "name": "펀딩비 과열 역매매", "desc": "펀딩비가 0.05% 넘게 과열(롱 쏠림)이면 숏, -0.05% 아래면 롱. 쏠림의 반대편 (파생 데이터 필요)",
     "spec": {"indicators": [{"id": "e20", "type": "ema", "length": 20}],
              "long_entry": _g(_c("funding", "<", -0.05), _c("close", ">", "e20")), "short_entry": _g(_c("funding", ">", 0.05), _c("close", "<", "e20")),
              "risk": {"atr_stop_mult": 2.0, "atr_tp_mult": 3.0}}},
    {"key": "oi_break", "cat": "파생", "name": "미결제약정 급증 + 돌파", "desc": "OI 가 직전 봉보다 2% 넘게 늘면서 20봉 고점(저점)을 돌파하면 그 방향 (파생 데이터 필요)",
     "spec": {"indicators": [{"id": "dc", "type": "donchian", "length": 20}],
              "long_entry": _g(_c("close", ">", "dc.upper[1]"), _c("oi_change_pct", ">", 2)), "short_entry": _g(_c("close", "<", "dc.lower[1]"), _c("oi_change_pct", ">", 2)),
              "risk": {"atr_stop_mult": 2.0, "atr_tp_mult": 4.0}}},
]


def items(symbol: str = "BTCUSDT", interval: str = "1h") -> list[dict]:
    out = []
    for x in LIBRARY:
        spec = {"name": x["name"], "description": x["desc"], "symbol": symbol, "interval": x.get("interval", interval), **x["spec"]}
        spec.setdefault("risk", {})
        spec["risk"] = {"leverage": 3, "position_pct": 20, **spec["risk"]}
        out.append({"key": x["key"], "cat": x["cat"], "name": x["name"], "desc": x["desc"], "spec": spec})
    return out
