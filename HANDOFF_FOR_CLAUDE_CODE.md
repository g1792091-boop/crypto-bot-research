# 자동매매봇 프로젝트 인수인계 문서 (Claude Code용)

작성: 2026-09-29 (KST) · 이 채팅방(Claude 앱)에서 진행한 내용 전부를 정리한 것. Claude Code 세션의 첫 메시지로 이 파일과 동봉 ZIP을 주고 "읽고 이어서 진행"하라고 하면 된다.

---

## 0. 한 줄 요약

31개 매매법 + V3.9·V4.5·OBV 매매법을 실제 바이낸스 수수료(테이커 0.05%)로 14개월 백테스트한 결과, **사전 기준을 통과한 조합이 0개**다. 5분·15분 단타 + 50배 + 고정 ROE 손절 구조는 이 결과로 닫는 게 맞고, 다음 단계 후보는 A(1시간·4시간봉 재실행) / B(V4.5 저속 변형) / C(1분봉 청산 검증) 중 선택이다. **봇 제작과 PAPER는 아직 하지 않는다.**

---

## 1. 사용자·프로젝트 배경 (사용자가 말한 것)

- 사용자와 친구 둘이서 코인 선물 자동매매봇을 만들려고 함. 한국(Asia/Seoul).
- 원래 목표: 단타(스캘핑) 봇, 레버리지 50~60배, 시드의 30~40% 진입, 익절은 바이낸스 수수료 후 순 10% 이상(이상적으로 20~40%). 손절·익절 구조, 어떤 매매법을 쓸지, 타임프레임(5분/15분 써봄)은 미정.
- 처음 목표 "$1,000 → 한 달 $100k~$1M"은 "그냥 해본 말"로 철회, 이후 "$1,000 → $20,000 한 달"을 목표로 잡아보자고 함(달성 가능하다는 뜻이 아니라 목표 설정).
- 사용자 지시: **냉정하게(듣기 좋은 말 말고) 말할 것, 더 필요한 자료가 있으면 먼저 말할 것, 아직 봇 제작은 하지 말 것.**
- Astral(heyastral.ai) 유료 계정($9 첫 달) 보유. 인스타그램 인플루언서 lucas_lalk 링크로 알게 됨.
- 친구가 만든 V4.5/V3.9/OBV 매매법 세트(트레이딩뷰 Pine)와 ChatGPT로 만든 31개 매매법 세트가 있음. 둘은 별개 프로젝트.
- VPS 여러 대 운영 중(FOCUS5 rc1 봇 2대 가동 중이라고 함). VPS IP가 인수인계 문서에 노출돼 있으니 외부 공유 전 삭제 권고함.

## 2. 이 채팅에서 한 일 (시간 순)

1. **Astral 분석**: 정식 소프트웨어. $9 첫 달 → $30/월, 무료 체험 없음. 전략 DSL(`EMA_5 CROSS_ABOVE EMA_50`), MCP 연동, SnapTrade 브로커 연결. **롱 온리, 레버리지 없음, 숏 백테스트 불가, 현물 데이터(Polygon 집계 BTCUSD)**. 지표는 표준 세트(EMA/SMA/RSI/MACD/Stoch/ATR/BB/ROC 등)만 있어 SuperTrend·DMI/ADX·Chop Zone·STC·OBV 없음. 백테스트·차트 데이터는 시간봉당 최근 40,000봉(5분 ≈ 4.6개월, 15분 ≈ 14개월, 1시간 ≈ 4.6년). 페이퍼 트레이딩 가능. Explore의 연환산 수익률은 며칠짜리 백테스트를 연율화한 숫자라 신뢰 금물. lucas_lalk는 제휴 링크 홍보 계정, 실계좌 증거 없음.
2. **31개 매매법 프로젝트 분석** (FINGRAD V3.3.1, CORE4/ALT5 zip): 원본이 인스타그램 이미지 → ChatGPT 근사식. 31개 중 표준지표 15~19개, 근사식 12~14개, 모드선택 2개. 7일 감사(2026-08-26~09-02): 124장부, 2,728거래, 순손실 −23.8%, 수수료가 손실의 53%, 승률 42%, PF 0.60, 양수 4개(N19, N13, N08, N11). 코드상 수수료 가정 0.02%(실제 0.05%). 보고서 문서: https://claude.ai/artifact/46br7PTC1MtZoe78PAgGNF
3. **V4.5·V3.9·OBV 프로젝트 분석** (CLAUDE_V45_V39_OBV_HANDOVER_20260918_3.zip): 진짜 Pine v6 원본 3개, 해시 일치. 원본 3봇 RC2 7.72일 결과 전부 손실(V3.9 −748, V4.5 −419, OBV −1,547; 정책당 5,000 USDT). 양수 후보(A: V4.5 정확 AM+B+G1 SL15, B/C: V3.9 15M+G1 SL20 gross/net 계단, O: OBV S+G2R)는 같은 자료에서 사후 선별. 수수료 0.01% 가정을 0.05%로 바꾸면 V45_AMB_G1_SL15 +1,725 → ≈ −55, V39_F15_G1_SL20 +696 → ≈ −181. NQP 실행엔진 실패 원인은 `/root` 권한(PermissionError → BrokenProcessPool). −20% 손절이 −144.6%로 체결된 사고는 SQLite FD 고갈. 보고서 문서: https://claude.ai/artifact/BTbPemKPBxQjiZEvX2htiX
4. **1단계 백테스트** (이 문서의 핵심, 아래 3~5절).

## 3. 1단계 백테스트 — 무엇을 어떻게 돌렸나

- **데이터**: Astral 계정에서 `astral_price_get(symbol, tf, limit=40000, delivery="download")`로 뽑은 CSV. 15분: BTC/ETH/SOL/LTC/BCH 각 40,000봉(2025-08-07~2026-09-29). 5분: BTC/ETH/SOL 각 40,000봉(2026-05-13~09-29). LTC/BCH 5분은 다운로드 오류로 없음. 컬럼: timestamp(UTC, 봉 시작), open, high, low, close, volume. SHA256은 `data/expected_sha256.txt`. 현물(Polygon 집계) 가격이지 바이낸스 선물 Mark가 아님. 15분 자료에 2026-04-23 하루(1,455분) 공백 있음.
  - 주의: Claude 앱 샌드박스에서는 Astral의 S3 다운로드 링크가 회사 정책으로 차단돼 사용자가 브라우저로 받아 업로드했음. Claude Code(로컬)에서는 curl로 직접 받을 수 있을 가능성이 높음.
- **엔진** (`bt/engine.py`): 확정봉 종가 신호 → 다음 봉 시가 시장가 진입(+슬리피지). SL/트레일/계단은 스탑 시장가(갭이면 시가 체결, −슬리피지), TP는 지정가. 같은 봉에 SL·TP 둘 다 닿으면 SL 우선. 트레일·계단 스탑은 직전 봉까지의 고점으로 계산(보수적). 비용: 테이커 0.05%/편도, 슬리피지 0.02%/시장가 체결, 펀딩 0.01%/8h(양방향 비용). 결과는 가격% 기준으로 저장 → 레버리지 계층(5/10/20/50 × 증거금 40%, MAE ≥ 1/L − 0.5%면 강제청산)에서 복리. 종목별 독립 1포지션, 최대 보유 1,000봉.
- **엔진 검사**: 랜덤워크 데이터에서 비용 전 기대값 −0.03%(슬리피지분), 비용 후 −0.13% → 미래참조 없음 확인. `fg_fast.py`(numpy로 다시 짠 슈퍼트렌드·PSAR·하이킨아시·Aroon·CCI)는 `test_fg_fast.py`로 FINGRAD 원본 함수와 결과 일치 검증.
- **전략** (`bt/strategies.py`): 31개 중 표준지표 19개(S2·S5·S6·N01·N02·N03·N07·N08·N09·N10·N12·N14·N17·N18·N21·N22·N23·N24·N25; `fg_indicators.py`는 FINGRAD `indicators.py` 원본 복사본), V3.9 15분 차트(전체·S42·S52·SR·D16·AC1·STC 켠 변형·G1), OBV S/B(+G1), V4.5(정확 AM+B = signalB ∧ ¬signalC, +G1, 전체 A/B/C; 5분+확정 15분). Pine은 `pine_indicators.py`에 한 줄씩 이식(Pine 시드 방식 그대로). 31개 중 근사식 12개는 원본이 없어 제외. N14·N21은 14개월 동안 신호 0건.
- **청산 격자 13종**: 고정 SL {1, 1.5, 2} ATR14 × TP {1.5, 2, 3} ATR14 (9), 트레일 SL 1.5ATR + 고점 대비 {1.5, 2.5} ATR (2), 원래 방식 50배 gross ROE SL {−15%, −20%} + 계단 12→11/16→15/21→20/+5 (2).
- **구간**: 15분 앞 9개월(2025-08-07~2026-05-07) 선별, 뒤 5개월(2026-05-08~09-29) 검증 — 선별 통과 후보만 검증 구간을 열기로 사전에 정함. 5분(V4.5)은 4.6개월 전체를 한 구간으로.
- **사전 통과 기준**: 합산 PF ≥ 1.2, 거래 ≥ 100, 비용 후 기대값 > 0, 양수 종목 ≥ 3/5.

## 4. 결과 (숫자)

- **15분 5종목 앞 9개월**: 28전략 × 13청산 = 364조합, 851,035거래, **통과 0개**. 최고 S6(EMA·DMI·ADX) SL2/TP3 PF 0.93, 835건, 비용 후 −0.052%/거래. 비용 전 기대값 28개 전부 −0.10%~+0.06%.
- **청산 방식 평균 PF(28전략 평균)**: SL2/TP3 0.77 → … → 트레일1.5 0.54 → **원래 50배 SL−20%+계단 0.38, SL−15%+계단 0.34 (꼴찌)**. 원래 방식 평균 보유 2.6~3.2봉, 거래당 −0.16%.
- **V3.9 15분 전체**: 원래 청산 PF 0.30(4,073건), 최고 청산 PF 0.72. STC 변형·G1 변형 동일. 서브 5개 전부 PF 0.71~0.81.
- **OBV S**: 원래 청산 PF 0.32~0.37, 최고 PF 0.79.
- **V4.5 정확 AM+B+G1 (5분, BTC/ETH/SOL, 2026-05-13~09-29)**: 원래 청산(50배 SL−15%) PF 0.20, 1,112건, 승률 39.6%, 5개월 전부 손실. 수수료 0.01%로 재계산해도 매달 마이너스(5월 −14.8%, 6월 −22.1%, 7월 −24.9%, 8월 −14.1%, 9월 −19.2%; 가격% 합). 최고 청산 SL2/TP3 PF 0.80. 통과 0/39.
- **보고서의 9월 5~13일 교차검증**: 보고서는 V45_AMB_G1_SL15 56건·75%·+1,724. 내 재현: 3종목 59건(건수 유사), 승률 46%, 단일계좌 50배·40% 복리 1,000 → 380. 손절 0.3%·잠금 0.22%라 데이터(현물 vs Mark)·봉 내 경로·종목 선택에 따라 뒤집히는 구조.
- **신호 품질(청산 무관, 신호 후 N봉 뒤 방향 수익률, 비용 0)**: 15분 28개 중 4시간 뒤 +0.1% 넘는 건 S5(324건, +0.103%)뿐. V3.9 계열은 음수(−0.035~−0.121%) = 늦은 추격. **V4.5 정확 AM+B만 64봉(5.3h) 뒤 +0.135%(BTC +0.09, ETH +0.14, SOL +0.18; t 2.8~3.1, 양수 비율 57%)** — 유일한 희미한 신호. 단 왕복 비용(0.10~0.14%)과 같은 크기이고 원래 청산은 7봉(35분) 안에 끝나 이 드리프트를 못 받음.
- **원인 요약**: 왕복 비용 0.14% vs 15분봉 1 ATR 중앙값 0.54%; 50배 −20% = 가격 0.4%로 1 ATR보다 작아 노이즈에 잘림; 계단 +11% = 가격 0.22%로 이겨도 작게 이김(손익비 0.5, 본전 승률 75% 필요, 실제 40%); V3.9는 4추세+교차기억+쿨다운을 다 통과한 시점이 추세 후반.
- 결과 문서: https://claude.ai/artifact/JJDDW6tFh3nXQg1ZEiAud1

## 5. 결정된 것 / 열린 것

결정(결과가 정한 것):
- 5분·15분 단타는 이 데이터에서 성립하지 않음. 50배는 어떤 청산으로도 자산 0. 고정 ROE 손절·계단은 버림.
- 봇 제작·PAPER 진행 안 함(거래당 기대값 음수).
- Astral 역할 = 데이터 공급(+나중에 롱 쪽 페이퍼 확인용). Astral 안에서 이 매매법들을 백테스트하는 건 불가능.

열린 것(사용자 선택 대기):
- **A. 1시간·4시간봉으로 같은 28개 재실행** (권장 1순위). Astral 1시간봉 40,000봉 = 4.6년. 필요: `astral_price_get(symbol, tf="1h", limit=40000, delivery="download")` 5종목. 4시간은 Astral tf 목록에 없으므로 1시간을 리샘플. 엔진은 `CostCfg(bar_minutes=60)`로 그대로.
- **B. V4.5 저속 변형**: 지정가(메이커 0.02%) 진입·청산, 4~6시간 보유, 3~5배, ATR 손절. 지금 데이터로 가능. 지정가 미체결 가정을 보수적으로 넣을 것.
- **C. 1분봉으로 청산 모형 검증**: 9월 한 달(40,000봉 = 27.8일)을 1분봉으로 다시 돌려 봉 단위 계단 처리가 결과를 바꾸는지 확인.
- 사용자가 아직 답하지 않은 것: 목표 재설정, rc1/C1 봇 현재 상태.

하지 말 것: 같은 데이터로 파라미터를 더 돌려 양수 조합 찾기(사후 선택), Astral Explore 연환산 수익률로 전략 고르기, 50배 복귀.

## 6. 동봉 파일 구조

```
stage1_handoff/
  HANDOFF_FOR_CLAUDE_CODE.md   ← 이 문서
  bt/
    engine.py          백테스트 엔진 (ExitCfg, CostCfg, run_backtest, summarize, leverage_layer)
    strategies.py      28개 신호 생성기 + V4.5(5분+15분) + G1 필터, CANDIDATES_15M 레지스트리
    pine_indicators.py Pine v6 이식(exchange_supertrend, chop_angle, stc, dmi/adx, stoch, stoch_rsi, ao_ac, obv, pine_ema/rma)
    fg_indicators.py   FINGRAD indicators.py 원본 복사본
    fg_fast.py         위 원본 중 느린 함수의 numpy 버전(결과 동일)
    test_fg_fast.py    fg_fast 동일성 검증
    run.py             격자 실행기: python3 run.py --window IS|OOS|ALL --tf 15m|5m --symbols ... --tag ...
    analyze.py         종목 합산 + 사전 기준 판정: python3 analyze.py --window IS --tag all5
    forward.py         청산 무관 신호 품질(N봉 뒤 수익률)
    portfolio.py       단일 계좌(전체 1포지션) 시뮬
    report_tables.py   보고서 마크다운 표 생성
  data/                CSV 8개 + expected_sha256.txt  (별도 zip: stage1_data.zip)
  results/
    pooled_IS_15m_all5.csv         15분 5종목 앞 9개월 합산(364행 + G1 변형), pass 열
    pooled_ALL_5m_v45_final.csv    V4.5 5분 합산(39행)
    summary_*.csv                  종목별 행
    forward_IS_all5.csv, forward_ALL_5m_v45.csv   신호 품질
    tables_15m.md, tables_5m.md    보고서 표
    (trades_*.csv는 용량 때문에 제외 — run.py 다시 돌리면 재생성)
```

실행 순서(15분 재현): `cd bt && python3 run.py --window IS --tag all5 && python3 analyze.py --window IS --tag all5 && python3 forward.py --window IS --tag all5`. 5종목 15분 격자 약 5분 소요. 의존성: pandas ≥ 2, numpy.

## 7. 이전 프로젝트 파일(사용자가 보유, 이 zip에는 없음)

- `FOCUS5_31_STRATEGY_FINAL_HANDOFF_20260929.zip`, `CORE4_WINDOWS_EASY_V3_3_1.zip`, `ALT5_UBUNTU_EASY_UPLOAD_V3_3_1.zip` — 31개 프로젝트.
- `CLAUDE_V45_V39_OBV_HANDOVER_20260918_3.zip`, `MASTER_HANDOVER_KO.md` — V4.5/V3.9/OBV 프로젝트. Pine 원본: `01_STRATEGY_SOURCE/V45/V4_5_5M_15M_DIRECTION_PRIORITY_STRICT_CLEAN_SIGNAL.txt`, `V39/V3_9_5M15M_4TREND_STC_ADX10_60_FINAL.pine`, `OBV/OBV30_STOCH_OBV11_9_AC_STC_CLEAN_V1_2.pine`.
- 패키지에 없는 것: G2R 원형 `selected/reentry_v2.py`, PAPER 엔진 Python, 과거 RC2 거래 CSV, NQP 런타임 소스.

## 8. Claude Code 첫 메시지 예시

> 첨부한 stage1_handoff.zip을 풀고 HANDOFF_FOR_CLAUDE_CODE.md를 먼저 읽어. 자동매매봇 프로젝트 인수인계 문서야. 냉정하게 판단해주고, 봇 제작은 아직 하지 마. 다음 단계로 A(1시간·4시간봉 재실행)를 진행하자 — Astral MCP로 BTC/ETH/SOL/LTC/BCH 1시간봉 40,000봉을 받아서 bt/ 엔진으로 같은 28개 전략 × 13개 청산을 돌리고, 사전 기준(PF ≥ 1.2, 100건 이상, 실제 수수료 후 양수, 양수 종목 3/5)으로 판정해줘.
