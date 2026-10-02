# GH Coin

코인 전문 AI 에이전트 회사. GH Nano(`../nuri-ai/`)의 엔진(AI 연결·지표 165종·커스텀 수식·백테스트·ML/딥러닝·데모·실거래·차트 터미널·자체 코드 수정)을 그대로 쓰고, 조직과 업무만 코인에 맞게 따로 둔다. 저장소(회의 기록 `coin:log`, 데모 장부 `coin:paper`, 과제·노트 `coin*`, 결과물 `coindoc:`)는 GH Nano 와 섞이지 않는다. AI 키 설정은 같은 주소에서 실행하면 GH Nano 와 공유한다.

- `coin-org.js` 28개 팀 × (팀장 1 + 팀원 10) + CEO실 (투자위원회·퀀트 리스크·데이터 플랫폼·전략 최적화는 오픈소스 분석으로 추가), 질문 단어 → 담당 팀장, 자동 회의 안건, 관찰 대상, 수다 상대
- `coin-office.js` 엔진 (`../nuri-ai/office.js` 에서 갈라짐): 일반·커스텀 두 라인(`LANES`) 매매법 개발 → 백테스트 → 데모, 관문 심사(`promoteJob`), 분석 팀 업무(`indJob`·`trendJob`·`entryJob`·`srJob`·`tpslJob`·`patternJob`·`situJob`·`coinJob`), `pipeline()`
- `combo.js` 실시간 종합 지표 타점 엔진: 차트 터미널 지표 136종 → 지표별 상승·하락 표(`voteOf`) · 장세 필터 · 레벨 묶음(`clusterLevels`) → 시간대 점수(`analyzeTF`) → 타점(`planOf`) · 기록장 채점(`gradeCall`). `coin-office.js`의 `startCombo`(60초 루프)·`comboJob`·`comboBoard` 가 쓴다
- `coin-ui.js` 픽셀 본부 화면 (`../nuri-ai/office-ui.js` 에서 갈라짐): 6열 배치, 분석 표 카드, 실거래 후보 카드, #⚡실시간 타점판·#파이프라인 탭, 타점판 크게 보기
- `coin-app.js` 시작·AI 연결 창·학습 데이터 내려받기·[👛 내 지갑 보기] 버튼, `index.html` 코드 수정 안전장치 포함
- `wallet.js` **내 지갑 보기 (읽기 전용)**: 공개 주소만 붙여 넣어 목록으로 보관(이 브라우저 `localStorage`)하고, 잔액은 공개 블록 익스플로러에서 본다(BTC·EVM은 공개 API로 한 번 읽어 보여 주고 실패 시 익스플로러 링크). **개인키·시드문구는 입력하면 막고 저장하지 않으며, 이 앱에는 송금·출금·서명 기능이 없다.** EVM·BTC·트론·리플·도지·솔라나 주소 형식을 알아본다.

실거래(`live.js`)는 코드가 판정한 관문(14일·20거래·손익비 1.2·수익+·낙폭<25%)을 통과한 뒤에도 사용자가 실거래 화면에서 직접 켜고 연결해야 하며, 한도·승인 안에서만 주문한다. 실거래 화면(`live-ui.js`)에는 **[📘 실전 연결 안내]**(테스트넷 → 거래 전용 키 → 관문 → 한도 → 승인 모드 → 메인넷 → 긴급 정지의 8단계 가이드)와 **레버리지·마진 설정**(최대 레버리지 입력 시 청산까지 대략 역방향 거리를 바로 보여 주고, 격리/교차 마진을 고를 수 있음)이 있다. GH Nano 안에서는 [🪙 코인 본부] 버튼으로 같은 화면이 열린다(iframe, 같은 키 공유).

### 봇 전략 (`coin-office.js`의 `BOT_TEMPLATES`)
실거래 한도에 맞춘 레버리지(기본 3배) 단일 포지션 봇. 추세추종·돌파·평균회귀·슈퍼트렌드·추세 캐리에 더해 **MACD 추세·켈트너 추세·스토캐스틱RSI 되돌림·변동성(돈치언) 돌파** 봇을 추가했다. 모두 백테스트→70/30 검증 관문을 통과해야 데모에 올라가고, 데모 관문을 다시 통과해야 실거래 후보가 된다. 그리드·DCA(`lib/botsim.js`)는 지갑 노출·물타기 횟수 한도로 막은 **연구용 백테스트 전용**이라 실거래로 나가지 않는다.

**자동 개선 (`botImproveJob`, 선물 자동매매봇팀):** 데모에 올라간 🤖 봇 전략의 **보조지표 길이·문턱값(buy 공간)** 과 ROI·손절·추적손절·보호장치를 하이퍼옵트(`lib/hyperopt.js`, freqtrade 손실함수 6종)로 다듬는다. 앞 70%에서만 탐색하고 **뒤 30%(검증) + 견고성(순열검정·5구간·위생, `lib/robust.js`) + SDLC 버전 관리(`lib/sdlc.js`)** 를 통과한 개선안만 새 버전으로 데모에 올려 원본과 비교 운용한다. 실거래 관문(14일·20거래·손익비…)은 그대로라 자동 개선이 실거래를 건너뛰지 않는다. 봇 조종판 [🔧 봇 자동개선(하이퍼옵트)] 버튼이나 "봇 자동개선 해줘"로 바로 실행된다. (전략 최적화팀 `optJob`은 봇을 포함한 모든 데모 전략을 같은 방식으로 다듬는다.)

### 🧠 자체 AI (`lib/selfai.js`, 자체 AI 데스크팀)
**외부 LLM 키 없이** 이 앱 안에서만 도는 앙상블 판단 엔진. 네 신호를 하나의 **방향 + 확신도(0~95)** 로 합친다: 기술 평점(트레이딩뷰식 `lib/ta_rating.js`) · 멀티 시간대 종합 점수(`combo.js`, 높은 시간대에 가중) · ML 확률(`../nuri-ai/ml.js` walk-forward, 통계적 우위만큼만 신뢰) · 알파 팩터 합성(`lib/alpha.js`). 확신도는 **신호 크기 + 신호 간 합의**로 매기고, 신호가 엇갈리면 낮아진다. `selfaiJob`(자체 AI 데스크팀)이 6개 코인 순위를 내고(1위는 ML까지 더해 정밀 재판단), "자체 AI 확신도 순위 보여줘"·봇 조종판 [🧠 자체 AI 확신도] 버튼·`window.ghCoinSelfAI(sym)`로 쓸 수 있다. **자체 AI 는 판단만 하고 주문은 내지 않는다** — 실제 주문은 그대로 `live.js`(한도·승인·긴급정지)만 낸다. 아이디어 출처: TLSRUF/ai-trader-team·jnMetaCode/agency-agents-ko·anthropics/claude-cookbooks·financial-services·continuedev/continue·ten-builder(코드 복사 없음, `THIRD_PARTY.md`).

### 🤖 코인 AI 봇 (`coinai.js` + `lib/ragstore.js`) — 완전 자체 RAG 챗
이 앱이 아는 것(앱 설명 고정 지식 + 사무실 분석·표·노트 + 데모 전략 + 실시간 자체 AI 판단)을 모아 **외부 서비스·벡터DB 없이** 브라우저 안에서 도는 가벼운 검색(TF-IDF + 코사인, 한국어 2-그램 `lib/ragstore.js`)으로 질문에 답한다. **외부 AI 키가 없으면 추출 답변(완전 자체)**, 키가 있으면 그 지식에 **근거한** LLM 답변(`brainStream`). 코인을 물으면 자체 AI 데스크(`selfAIFor`)의 실시간 방향·확신도를 함께 붙인다. 화면 오른쪽 아래 **떠다니는 [💬 코인 AI] 버튼**과 상단 **[🤖 코인 AI]** 버튼으로 어디서나 열린다. **설명·판단만 하고 주문은 내지 않는다.** 아이디어: langgenius/dify(RAG·지식베이스)·FlowiseAI/Flowise(임베드 위젯)·Mintplex-Labs/anything-llm(완전 자체 프라이빗 RAG) — 코드 복사 없이 개념만. probot(GitHub App 프레임워크)은 코인 앱과 무관해 적용하지 않음.

### 📦 `vendor/` — 외부 저장소의 실제 원본 코드
받은 GitHub 저장소의 **실제 소스를 그대로 보관**한다(수정 없음, 각 `LICENSE` 포함): `vendor/ai-trader-team/`(trading_rigor.py·backtest.py·cli_utils.py), `vendor/anythingllm-embed/`(useSessionId.js·constants.js·date.js), `vendor/agency-agents-ko/`(투자 리서처 원칙). 그중 **의존성 없는 `anythingllm-embed/constants.js` 는 코인 AI 봇이 그대로 `import` 해 사용**(위젯 열림 상태 기억). 나머지 파이썬/React 파일은 빌드 없는 브라우저 앱에서 그대로 실행되지 않아, 같은 공식·반올림으로 **충실히 이식한 실행본**(`lib/rigor.js`, `lib/attbacktest.js`, `coinai.js` 세션 로직)을 두고 원본과 출력 일치를 테스트로 확인했다. (`vendor/README.md` 참고)

### 📊 ai-trader-team 백테스트 (`lib/attbacktest.js`) — 실제 이식
`vendor/ai-trader-team/backtest.py` 를 그대로 이식: SMA20 상향 돌파 진입·고정 5% 손절·목표 2R·최대 60일 보유·왕복비용 0.1%, 여러 거래를 한 계좌로 묶어 거래당 1% 리스크 복리 수익(+히트 한도). Python 원본과 거래·R-멀티플·수익률이 일치한다. 코인 AI 봇에 "에이아이 트레이더 백테스트 비트코인"처럼 물으면 일봉으로 돌려 보여 주고, `window.ghCoinAttBacktest` 로도 호출.

### 🧮 리스크 계산기 (`lib/rigor.js`) — 실제 이식
`TLSRUF/ai-trader-team` 의 `tools/trading_rigor.py`(MIT, 표준 라이브러리 결정론적 계산)를 바닐라 JS 로 **그대로 이식**: 포지션 사이징(계좌·리스크%·진입·손절)·손익비(R:R)·실현/미실현 R-멀티플·켈리(full/half/quarter)·포트폴리오 히트(동시 손절 손실률)·상관계수. 같은 공식·같은 반올림(ROUND_HALF_EVEN)·같은 검증 규칙이라 Python 원본과 출력이 일치한다(단위 테스트 확인). 코인 AI 봇에 "포지션 크기 계좌 10000 리스크 1 진입 100 손절 95"처럼 물으면 바로 계산해 주고, 자체 AI 데스크 1위 코인에는 1.5×ATR 손절·3R 목표 예시 계획을 보여 준다. `window.ghCoinRigor` 로도 호출.

### 🔌 자체 AI 외부 API 연동
자체 AI 데스크는 외부 키 없이도 돌지만, **API 키가 연결되면 외부 LLM 의 방향·확신도 의견을 앙상블의 '한 표'로** 더한다(확신도만큼 가중, 과신 방지 상한 0.25). 1위 코인에 대해 LLM 에게 엄격 JSON 의견을 받아 `selfai.fuse` 의 `ai` 신호로 반영한다. 기본은 키가 있으면 켜짐이고 설정에서 끌 수 있다(`window.ghCoinSelfAIExternal(false)` / `setSelfaiExternal`). 코인 AI 봇도 키가 있으면 RAG 지식에 근거한 LLM 답변, 없으면 추출 답변(완전 자체).

### 넣지 않은 것 (안전·합법성)
`THIRD_PARTY.md`대로 **코인 지갑 헌터**(남의 개인키·시드로 지갑 열기 = 절도)와 **앱 내장 채굴기 + 한 지갑으로 자동 입금**(배포되는 .exe 안에 넣으면 받은 사람 PC에서 몰래 도는 **크립토재킹** 모양)은 넣지 않는다. 본인 PC에서 xmrig를 **직접 본인 지갑으로** 돌리는 것은 사용자 자유이고, 자금 보관은 Rainbow 등 검증된 지갑을 쓴다. 이 앱에는 송금·출금·개인키 보관 기능이 없다.

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
