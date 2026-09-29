# 백테스트 결과 전달 양식 (다른 채팅방 → 이 저장소)

목적: 다른 채팅에서 돌린 백테스트 결과로 아래 분석을 **바로** 하기 위한 양식입니다.
- 요일·주말·시간대 분석
- 익절 방식 비교: ROE 10·15·20% vs 구조 익절 등
- 매매법 조합 시너지
- 봇 코드 재현 검사
- 과최적화 검정: 시도 횟수 반영

## 1. 필요한 파일 (매매법 × 타임프레임마다)

### ① `trades.csv`: 거래 한 건당 한 줄
| 열 | 설명 | 예 |
|---|---|---|
| strategy_id | 매매법 이름 | trend_breakout |
| params_version | 파라미터 묶음 이름 또는 해시 | v1_ema20_50 |
| timeframe | 봉 | 15m |
| symbol | 종목 | BTCUSDT |
| side | 방향 | LONG / SHORT |
| signal_time_utc | 신호가 확정된 봉의 마감 시각(UTC) | 2025-03-04T12:15:00Z |
| entry_time_utc | 진입 체결 시각 | 2025-03-04T12:15:00Z |
| entry_price | 진입가 | 64250.5 |
| entry_type | 시장가 / 지정가 | market |
| stop_price | 최초 손절가 | 63890.0 |
| tp_price | 익절가(있으면) | 64571.8 |
| tp_rule | 익절 규칙 설명 | ROE 10% / 직전 고점 / 트레일링 등 |
| leverage | 사용 레버리지 | 20 |
| margin_usdt | 증거금 | 100 |
| notional_usdt | 명목가 | 2000 |
| exit_time_utc | 청산 시각 | 2025-03-04T14:30:00Z |
| exit_price | 청산가 | 64571.8 |
| exit_reason | TP / SL / TRAIL / SIGNAL / TIME / LIQUIDATION | TP |
| fee_usdt | 수수료 합계 | 2.0 |
| funding_usdt | 펀딩 합계(없으면 0, 반영 안 했으면 빈칸) | -0.3 |
| slippage_assumed | 가정한 슬리피지 | 0.01% |
| pnl_usdt | 순손익 | 7.7 |
| roe_pct | 순 ROE % | 7.7 |
| mae_price / mfe_price | (가능하면) 보유 중 최대 역행·순행 가격 | 64010 / 64620 |

### ② `settings.json`: 백테스트 설정
- 매매법 규칙 **글 설명**: 진입, 청산, 손절, 익절, 반대 신호 처리, 재진입
- 파라미터 값 전체
- **데이터 출처**: 바이낸스 **USDⓈ-M 무기한 선물** 캔들인지 현물인지, 기간, 시간대(UTC 권장)
- 체결 가정
  - 신호 봉 마감가인지 다음 봉 시가인지
  - 같은 봉에서 손절과 익절이 모두 닿으면 어느 쪽을 우선했는지
- 수수료율, 슬리피지, 펀딩 반영 여부
- 레버리지·증거금 규칙: 고정인지, 복리인지, 초기 자본
- 청산 계산 여부

### ③ `search_log.csv`: 시도 기록 (과최적화 검정에 꼭 필요)
- **시험해 본 파라미터 조합·매매법의 총개수**와 각각의 요약 결과(거래 수, 수익, 최대 낙폭)
- 최종 파라미터를 **어느 기간 데이터로 골랐는지**(학습 구간 / 검증 구간)
- 기록이 없으면 대략적인 시도 횟수라도 적어 주세요

### ④ `equity_daily.csv`: 일별 자산 곡선
- date, equity (매매법별로 따로)

## 2. 다른 채팅방에 그대로 붙여넣을 요청문

```
백테스트가 끝나면 매매법 × 타임프레임마다 아래 4개 파일로 결과를 내보내 줘.

1) trades.csv — 거래 한 건당 한 줄. 열:
strategy_id, params_version, timeframe, symbol, side, signal_time_utc, entry_time_utc,
entry_price, entry_type, stop_price, tp_price, tp_rule, leverage, margin_usdt, notional_usdt,
exit_time_utc, exit_price, exit_reason(TP/SL/TRAIL/SIGNAL/TIME/LIQUIDATION),
fee_usdt, funding_usdt, slippage_assumed, pnl_usdt, roe_pct, mae_price, mfe_price
(시각은 모두 UTC, 없는 값은 빈칸)

2) settings.json — 매매법 규칙 설명(진입·청산·손절·익절·반대신호·재진입), 파라미터 전체,
데이터 출처(바이낸스 USDⓈ-M 무기한 선물인지 현물인지), 기간, 체결 가정(봉 마감가/다음 봉 시가,
같은 봉 손절·익절 동시 도달 시 우선순위), 수수료율, 슬리피지, 펀딩 반영 여부,
레버리지·증거금 규칙, 초기 자본, 청산 계산 여부

3) search_log.csv — 시험해 본 파라미터 조합·매매법 전체 목록과 각각의 거래 수·수익·최대 낙폭,
최종 파라미터를 고른 기간(학습/검증 구분)

4) equity_daily.csv — 매매법별 일별 자산

가능하면 5종목(BTC, ETH, SOL, LTC, BCH) 모두, 5m·15m·30m·1h·4h·1d 전부.
```

## 3. 받은 뒤 이 저장소에서 하는 일
1. **재현 검사**: 봇의 체결 코어로 같은 거래가 나오는지 확인합니다(거래 일치율 95% 이상 목표).
2. **과최적화 검정**: search_log의 시도 수로 Deflated Sharpe와 PBO를 계산합니다.
3. **요일·주말·시간대 표**: 세션 4구간 × 평일/주말, 신뢰구간 포함
4. **청산 실험실**: ROE 10·15·20%(레버리지별 가격 환산), 구조 익절, R배수, 트레일링, 분할 익절을 같은 거래에 적용해 비교
5. **동적 레버리지 엔진 재계산**: 같은 신호에 §2 규칙을 적용했을 때의 결과와, 20배 하한과 충돌하는 거래 수
6. **조합 시너지 행렬**
