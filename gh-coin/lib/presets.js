// 준비된 매매법 프리셋 — AI 없이 바로 백테스트/비교할 수 있는 고전 전략 모음.
// 아이디어 출처: io-uty/crypto-auto-trading (RSI·MACD 기반 매수/매도 + 전략별 수익률 비교, 업비트 1분봉).
//   코드 복사 없이 개념만 재구현하고, 우리 지표 엔진(차트 터미널 146종 tv_* + 네이티브)으로 일반화했다.
// 모든 프리셋은 normalizeSpec 규격의 전략 JSON. symbol/interval 은 쓰는 쪽에서 채운다.

export const PRESETS = [
  { name: "RSI 과매도 반등", why: "RSI 30 아래에서 사고 60 위에서 판다 (io-uty RSI 전략)",
    spec: { name: "RSI 과매도 반등", indicators: [{ id: "rsi", type: "tv_rsi", length: 14 }],
      long_entry: { conditions: [{ left: "rsi", op: "<", right: 30 }] },
      long_exit: { conditions: [{ left: "rsi", op: ">", right: 60 }] },
      risk: { leverage: 2, stop_loss_pct: 4, take_profit_pct: 8 } } },

  { name: "MACD 추세추종", why: "MACD 선이 시그널 위로 올라가면 사고 아래로 내려가면 판다 (io-uty MACD 전략)",
    spec: { name: "MACD 추세추종", indicators: [{ id: "m", type: "tv_macd" }],
      long_entry: { conditions: [{ left: "m", op: ">", right: "m.p1" }] },
      long_exit: { conditions: [{ left: "m", op: "<", right: "m.p1" }] },
      risk: { leverage: 2, stop_loss_pct: 5 } } },

  { name: "RSI+MACD 결합", why: "RSI 과매도 + MACD 상방 둘 다일 때만 산다 (io-uty 결합 전략 — 더 신중)",
    spec: { name: "RSI+MACD 결합", indicators: [{ id: "rsi", type: "tv_rsi", length: 14 }, { id: "m", type: "tv_macd" }],
      long_entry: { conditions: [{ left: "rsi", op: "<", right: 45 }, { left: "m", op: ">", right: "m.p1" }] },
      long_exit: { conditions: [{ left: "rsi", op: ">", right: 65 }] },
      risk: { leverage: 2, stop_loss_pct: 4, take_profit_pct: 10 } } },

  { name: "볼린저 하단 반등", why: "가격이 볼린저 하단을 깨고 내려가면 사고 중앙선 위에서 판다 (평균회귀)",
    spec: { name: "볼린저 하단 반등", indicators: [{ id: "bb", type: "tv_bb" }],
      long_entry: { conditions: [{ left: "close", op: "<", right: "bb.p2" }] },
      long_exit: { conditions: [{ left: "close", op: ">", right: "bb" }] },
      risk: { leverage: 2, stop_loss_pct: 4 } } },

  { name: "스토캐스틱 과매도", why: "스토캐스틱 %K 20 아래에서 사고 80 위에서 판다",
    spec: { name: "스토캐스틱 과매도", indicators: [{ id: "st", type: "tv_stoch" }],
      long_entry: { conditions: [{ left: "st", op: "<", right: 20 }] },
      long_exit: { conditions: [{ left: "st", op: ">", right: 80 }] },
      risk: { leverage: 2, stop_loss_pct: 4, take_profit_pct: 8 } } },

  { name: "EMA 골든크로스", why: "빠른 EMA(10)가 느린 EMA(30)를 넘으면 사고 깨면 판다 (추세)",
    spec: { name: "EMA 골든크로스", indicators: [{ id: "ef", type: "ema", length: 10 }, { id: "es", type: "ema", length: 30 }],
      long_entry: { conditions: [{ left: "ef", op: ">", right: "es" }] },
      long_exit: { conditions: [{ left: "ef", op: "<", right: "es" }] },
      risk: { leverage: 2, stop_loss_pct: 5 } } },

  { name: "돈치안 채널 추세 (EMA 스캐너)", why: "돈치안 채널 중앙 위에선 타고, 하단 깨면 판다 (Darthreign KuCoin-EMA-Scanner · 추세 추종)",
    spec: { name: "돈치안 채널 추세", indicators: [{ id: "dc", type: "tv_donchian", length: 20 }],
      long_entry: { conditions: [{ left: "close", op: ">", right: "dc.p1" }] },
      long_exit: { conditions: [{ left: "close", op: "<", right: "dc.p2" }] },
      risk: { leverage: 2, stop_loss_pct: 4, take_profit_pct: 10 } } },

  { name: "슈퍼트렌드 추세캐리", why: "슈퍼트렌드 선 위면 타고 가고 하방 전환에 내린다 (passivbot/ninjabot식 추세 유지)",
    spec: { name: "슈퍼트렌드 추세캐리", indicators: [{ id: "stt", type: "tv_supertrend" }],
      long_entry: { conditions: [{ left: "close", op: ">", right: "stt" }] },
      long_exit: { conditions: [{ left: "close", op: "<", right: "stt" }] },
      risk: { leverage: 2, trailing_stop_pct: 3 } } },

  { name: "변동성 타겟 (ATR 사이징)", why: "ADX로 추세 확인 + ATR 기반 손절로 변동성을 일정하게 (pupedator ADX/ER·변동성 타겟 포지션 사이징)",
    spec: { name: "변동성 타겟", indicators: [{ id: "adx", type: "tv_adx", length: 14 }, { id: "ef", type: "ema", length: 20 }, { id: "es", type: "ema", length: 50 }],
      long_entry: { conditions: [{ left: "adx", op: ">", right: 20 }, { left: "ef", op: ">", right: "es" }] },
      long_exit: { conditions: [{ left: "ef", op: "<", right: "es" }] },
      risk: { leverage: 2, atr_stop_mult: 2, atr_tp_mult: 4, position_pct: 15 } } },

  { name: "박스권 그리드형 반복", why: "RSI 과매도/과매수를 박스권에서 반복 매매 (passivbot 그리드 아이디어 — 추세장에선 손절로 보호)",
    spec: { name: "박스권 그리드형", indicators: [{ id: "rsi", type: "tv_rsi", length: 7 }],
      long_entry: { conditions: [{ left: "rsi", op: "<", right: 25 }] },
      long_exit: { conditions: [{ left: "rsi", op: ">", right: 55 }] },
      risk: { leverage: 2, stop_loss_pct: 6, take_profit_pct: 4 } } },

  { name: "평균회귀 (통계적 이격)", why: "가격이 20이평에서 2σ 아래로 벌어지면 사고 중앙 복귀에 판다 (시스템/통계 차익 아이디어)",
    spec: { name: "평균회귀 2σ", indicators: [{ id: "bb", type: "tv_bb", length: 20 }, { id: "rsi", type: "tv_rsi", length: 14 }],
      long_entry: { conditions: [{ left: "close", op: "<", right: "bb.p2" }, { left: "rsi", op: "<", right: 35 }] },
      long_exit: { conditions: [{ left: "close", op: ">", right: "bb" }] },
      risk: { leverage: 2, stop_loss_pct: 5, take_profit_pct: 6 } } },
];
