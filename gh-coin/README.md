# GH Coin

코인 전문 AI 에이전트 회사. GH Nano(`../nuri-ai/`)의 엔진(AI 연결·지표 165종·커스텀 수식·백테스트·ML/딥러닝·데모·실거래·차트 터미널·자체 코드 수정)을 그대로 쓰고, 조직과 업무만 코인에 맞게 따로 둔다. 저장소(회의 기록 `coin:log`, 데모 장부 `coin:paper`, 과제·노트 `coin*`, 결과물 `coindoc:`)는 GH Nano 와 섞이지 않는다. AI 키 설정은 같은 주소에서 실행하면 GH Nano 와 공유한다.

- `coin-org.js` 28개 팀 × (팀장 1 + 팀원 10) + CEO실 (투자위원회·퀀트 리스크·데이터 플랫폼·전략 최적화는 오픈소스 분석으로 추가), 질문 단어 → 담당 팀장, 자동 회의 안건, 관찰 대상, 수다 상대
- `coin-office.js` 엔진 (`../nuri-ai/office.js` 에서 갈라짐): 일반·커스텀 두 라인(`LANES`) 매매법 개발 → 백테스트 → 데모, 관문 심사(`promoteJob`), 분석 팀 업무(`indJob`·`trendJob`·`entryJob`·`srJob`·`tpslJob`·`patternJob`·`situJob`·`coinJob`), `pipeline()`
- `combo.js` 실시간 종합 지표 타점 엔진: 차트 터미널 지표 136종 → 지표별 상승·하락 표(`voteOf`) · 장세 필터 · 레벨 묶음(`clusterLevels`) → 시간대 점수(`analyzeTF`) → 타점(`planOf`) · 기록장 채점(`gradeCall`). `coin-office.js`의 `startCombo`(60초 루프)·`comboJob`·`comboBoard` 가 쓴다
- `coin-ui.js` 픽셀 본부 화면 (`../nuri-ai/office-ui.js` 에서 갈라짐): 6열 배치, 분석 표 카드, 실거래 후보 카드, #⚡실시간 타점판·#파이프라인 탭, 타점판 크게 보기
- `coin-app.js` 시작·AI 연결 창·학습 데이터 내려받기, `index.html` 코드 수정 안전장치 포함

실거래는 코드가 판정한 관문(14일·20거래·손익비 1.2·수익+·낙폭<25%)을 통과한 뒤에도 사용자가 실거래 화면에서 직접 켜고 연결해야 하며, `live.js`의 한도·승인 안에서만 주문한다. GH Nano 안에서는 [🪙 코인 본부] 버튼으로 같은 화면이 열린다(iframe, 같은 키 공유).

## 오픈소스에서 들여온 것 (`lib/`, `tech.js`)
대표가 준 23개 저장소를 코드까지 읽고, 규칙·공식만 다시 만들었다(코드 복사 없음). 부서별 정리는 앱의 **#📚 도입 기술** 탭과 `tech.js`.
- `lib/hyperopt.js` freqtrade 손실함수·ROI/손절/추적손절 탐색 + backtrader 분석기 → 전략 최적화팀 `optJob`
- `../nuri-ai/quant.js` 백테스터에 `risk.minimal_roi`, `trailing_stop_positive_pct/_offset_pct`, `risk.protections`(StoplossGuard·MaxDrawdown·CooldownPeriod·LowProfitPairs), 지표 `sqn`·`expectancy_ratio`
- `lib/execution.js` nautilus RiskEngine 점검 순서·거래 상태·TWAP·고정위험 사이저 + vnpy 리스크 매니저 (점검·계획용, 주문은 live.js)
- `lib/riskq.js` gs-quant 시계열(변동성·EWMA·상관·베타·백분위·튀는 값) + VaR/CVaR·포트폴리오 VaR → `qriskJob`
- `lib/dmn.js` jdmn 결정표(단항 검사·적중 정책) → `RISK_TABLE`, `PROMO_TABLE`
- `lib/sdlc.js` Legend 제약(Error/Warn)·검토→승인→버전(MAJOR/MINOR/PATCH)·캔들 품질
- `lib/migrate.js` obevo 변경 기록·체크섬·되돌림 → `runMigrations()`
- `lib/journal.js` reladomo 이중 시간 기록·감사 전용·as-of·해시 사슬
- `lib/exchanges.js` ccxt 통일 개념으로 8개 거래소 공개 REST + 김치 프리미엄 + 펀딩 상태
- `lib/patterns.js` stock-pattern·chart_patterns 규칙 → `patternScanJob`
- `lib/ta_rating.js` 트레이딩뷰식 기술 요약(python-tradingview-ta 규칙) + 캔들 17종 → 실시간 타점판·투자위원회
- `lib/robust.js` Vibe-Trading 순열 검정·부트스트랩·다구간·위생 → 백테스트 검증 보강, 최적화 채택, 승격표
- `lib/runchart.js` runcharter 규칙 → `driftJob`, 승격표
- `lib/alpha.js` vnpy Alpha158 계열 팩터 + 견고 z점수 → `alphaJob`
- 투자위원회 `icJob`(TradingAgents), 경제 캘린더 `openFeedsJob`(OpenBB 공급원), 독립 QA 채점(my-cc-harness), 추천 질문·최근 질문(gemini-clone)

## 차트 터미널 연결
- `../nuri-ai/analysisbus.js`: 직원 업무가 `pubTo(심볼, 섹션, {title, text, lines, markers, segs, rows, spec})` 로 남김 → 터미널 `🤖 AI 팀` 탭이 `TermChart.setAiOverlay()` 로 가격선·표시·패턴 선을 그림
- 터미널 `🧪 실험` 탭: SDLC 버전·본부 백테스트 기록·최적화 결과·전략 JSON → 백테스트·70/30 검증·견고성·하이퍼옵트·버전 저장 (`lib/hyperopt.js`, `lib/robust.js`, `lib/sdlc.js` 공용)
- `../nuri-ai/uikit.js`: 방 탭 가로 이동(휠·끌기·◀ ▶)·☰ 모든 방·사무실 확대/축소/이동 (GH Nano 사무실과 공용)
