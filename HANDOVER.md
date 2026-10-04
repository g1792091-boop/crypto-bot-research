# 인수인계 — GH Nano · GH Coin (crypto-bot-research)

> 기준일 **2026-10-05** · 브랜치 `claude/eloquent-ride-3o1bqv`
> 새로 맡는 사람(또는 새 AI 채팅)은 이 문서만 읽으면 이어서 작업할 수 있게 썼습니다.
> 맨 아래 "새 채팅에 붙여 넣을 문장"부터 써도 됩니다.

---

## 0. 지금 상태 한눈에

| 항목 | 상태 |
|---|---|
| 코드 | 이 브랜치에 전부 있음. 10/5 뉴트론 MCP·옵시디언 연결(5-4번)이 최신 |
| GitHub 반영 | **이 PC에서만 커밋된 상태가 있을 수 있음.** 이어받기 전에 `git status` / `git log origin/claude/eloquent-ride-3o1bqv..HEAD` 로 확인하고 올릴 것 (아래 9번) |
| 배포 exe (`dist/`) | **최신** (10/4 뉴럴 데스크 포함 재빌드, 커밋 `e6c9f5a`). push 여부만 확인 |
| 자동 테스트 | 저장소에 고정된 테스트 묶음 **없음**. 그때그때 Node 스크립트 · 브라우저로 확인함 (4번) |
| 실제 거래소 · 실제 AI 로 확인 | 일부만. 대부분 가짜 시세 · 가짜 AI 로 확인 (7번) |

---

## 1. 저장소 · 브랜치 지도

저장소: `https://github.com/g1792091-boop/crypto-bot-research` (비공개). **브랜치마다 다른 앱**이 들어 있습니다. `main` 은 비어 있음 (첫 커밋뿐).

| 브랜치 | 내용 | 비고 |
|---|---|---|
| **`claude/eloquent-ride-3o1bqv`** | **GH Nano · GH Coin · 건축설계 AI** (이 문서) | 지금 주력. 웹(JS) + Go 실행기 → 윈도우 exe |
| `claude/eloquent-johnson-nnt7gh` | 위 앱의 이전 브랜치 (`5759dd1`) | 더 이상 작업 안 함. 이 브랜치가 이어받음 |
| `claude/sweet-pascal-t82h6j` | **GH Quant** — 코인 선물 분석 터미널 (Python FastAPI + JS), 시나리오 진입 봇 · 31개 팀 | 별도 앱. 설명은 그 브랜치 `README.md` · `packaging/HOW-TO-RUN.txt`. 빌드는 GitHub Actions → 릴리스 `desktop-latest` |
| `claude/keen-pasteur-wav02u` | paperbot · 리서치 · 대시보드 (Python) | 별도 실험 |
| `claude/handover-doc-analysis-l7q9u7` | Astral 전략 분석 · 코인별 거래 통계 문서 | 분석 자료 |
| `claude/backtesting-framework` | Python 백테스트 프레임워크 (`src/cryptobot`) | **로컬에만 있음** (GitHub에 없음) |

> 이 작업 폴더에 보이는 `src/`, `tests/`, `data/`, `results/` 는 `backtesting-framework` 브랜치를 체크아웃했을 때 남은 찌꺼기(캐시 · 데이터 · 그림)입니다. 이 브랜치 코드와 무관하며 git 에 올리지 않습니다.

---

## 2. 이 브랜치 구조

```
index.html          첫 화면 (앱 고르기)
nuri-ai/            GH Nano 본체 = 공용 엔진 (GH Coin 도 이걸 import)
  engine.js           AI 연결 · 모델 선택 · 저장소        ← 보호 파일
  agent.js            도구 (캔들 받기 candlesFor 등)
  office.js / office-ui.js   픽셀 사무실 (GH Nano 쪽)
  quant.js            지표 165종 · 전략 · 백테스트
  ml.js               ML walk-forward
  paper.js            모의투자
  live.js / live-ui.js       실거래 (한도 · 승인 · 신뢰 게이트 gateFor)  ← 보호 파일
  selfdev.js          스스로 코드 고치기 (보호 목록 PROTECTED)      ← 보호 파일
  terminal/           차트 터미널 (실험 탭 · 신뢰점수 · 다이버전스 지표)
gh-coin/            GH Coin (코인 전문 AI 에이전트 회사)
  coin-org.js         조직: 팀 · 직원 (팀장 1 + 팀원 10)
  coin-office.js      업무 엔진 (nuri-ai/office.js 에서 갈라짐) — 핵심 파일
  coin-ui.js          본부 화면 · coin-app.js 시작 · coinai.js 코인 AI 봇(RAG)
  combo.js            실시간 종합 지표 타점판 (60초 루프)
  wallet.js           내 지갑 보기 (읽기 전용 · 개인키 입력 차단)
  lib/                오픈소스에서 '규칙만' 다시 만든 모듈 (hyperopt · robust · selfai · sentiment · lessons …)
  THIRD_PARTY.md      도입한 오픈소스 출처 (코드 복사 없음)
arch-ai/            건축설계 AI (작은 별도 앱)
launcher/           Go 실행기: 웹 파일 내장 + AI · 거래소 중계 + 사무실 폴더 → exe
portable/           GH Coin 핵심 모듈을 다른 프로젝트에 떼어 쓰는 복붙용 묶음
devserver.py        개발 서버 (exe 없이 실행 · AI 중계)
dist/               배포물 exe · 사용법.txt (zip 은 git 제외)
CURSOR.md           Cursor 로 여는 법
```

더 자세한 기능 설명: `gh-coin/README.md`, `nuri-ai/README.md`.

---

## 3. 실행 · 빌드

### 3-1. 개발 중 실행 (빌드 없이, 가장 빠름)
```bash
python devserver.py
```
- GH Coin: http://127.0.0.1:8777/gh-coin/ · GH Nano: http://127.0.0.1:8777/nuri-ai/
- 디스크 파일을 그대로 보여 주고 캐시를 끄므로, **코드 고친 뒤 Ctrl+Shift+R** 이면 바로 반영.
- 외부 AI 요청은 `/__nuri/proxy/<회사>/…` 로 devserver 가 대신 보냄 (브라우저 CORS 우회). 회사 목록은 `devserver.py` 의 `UPSTREAMS`.

### 3-2. exe 빌드 (Go 1.22+ 필요 — **이 PC에는 Go 미설치**)
```bash
cd launcher
bash build.sh        # → dist/GHNano.exe, dist/ArchAI.exe, dist/GHCoin.exe
```
- Go 설치: https://go.dev/dl/ (Windows installer) → 터미널 다시 열고 `go version` 확인.
- 배포 zip = exe + 해당 `사용법.txt`. 직접 빌드한 exe 는 백신 오탐 다운로드 차단이 덜함.
- 참고: GH Quant 브랜치(`sweet-pascal`)에는 이 앱들을 GitHub Actions 로 빌드하는 워크플로(`build-ghnano.yml`, 릴리스 `ghnano-latest`)가 있으나, 그건 옛 브랜치(`eloquent-johnson`의 `79440a4`) + 패치 기준이라 **이 브랜치 최신 코드가 아님**.

### 3-3. 처음 쓰는 사람
1. exe 실행(또는 devserver) → GH Coin 위쪽 **[🔑 AI 연결]** / GH Nano 설정 → AI 두뇌 에 키 붙여 넣기 (회사 자동 인식).
   무료: NVIDIA · Groq · Cerebras · OpenRouter · Hugging Face · SambaNova / 유료: Claude · DeepSeek
2. 결과물 저장 위치: `문서/GHNano 사무실` (GH Coin 은 그 안 `ghcoin`).

---

## 4. 확인(테스트) 방법

고정 테스트 묶음이 없습니다. 지금까지는 이렇게 확인했습니다.
- **문법 확인**: `node --check gh-coin/coin-office.js` 처럼 고친 파일마다 (Node 필요 — 이 PC에는 Node 미설치, Cursor 내장 터미널이나 설치 후 사용)
- **함수 단위**: 순수 함수(`trustScore`, `lib/*.js`, `portable/*.js`)는 Node 에서 `import` 해서 값 확인 (예: 과최적화 +25% → 신뢰 45점 < 견고 +18% → 83점)
- **화면**: devserver 로 열어 해당 버튼 · 탭을 직접 눌러 봄

> 이어받는 사람에게 권장: `lib/` · `trustScore` · `live.js` 의 `checkLimits`/`gateFor` 부터 `node --test` 테스트를 만들어 두면 이후 수정이 안전해집니다.

---

## 5. 최근 작업 (10/2 ~ 10/3) — 이전 인수인계 이후 추가된 것

**신뢰성 레이어** (전략이 실거래로 가는 길을 실제로 결정)
- **신뢰점수 0~100** `trustScore()` (`gh-coin/coin-office.js`): 데모성과 35 + 견고성 30 + 코인 일반화 20 + 표본 15. 수익만 높고 과최적화면 깎임.
- **교차검증** `crossCoinTest()`: 통과 전략을 6개 코인 전부에서 백테스트 (시장 수 상한 있음).
- **콘테스트** `contestJob`: 신뢰점수 순위 · 30 미만 은퇴 검토 · 60+ 1위 실거래 승격 후보.
- **앙상블** `ensembleJob`: 신뢰 45+ 전략을 점수 비례 배분 (한 전략 40% 상한).
- **적응형 재학습** `adaptiveRetrain` (driftJob 안): 신뢰 30 미만 자동 은퇴 + 개발팀에 교체 요청 (실거래 연결분은 수동 점검).
- **실거래 신뢰 게이트** `gateFor` (`nuri-ai/live.js`): 견고성 미달 · 다른 코인에서 수익 0개인 전략은 실거래 차단 (옛 전략은 '미측정'으로 통과).
- 운영 안정성: 캔들 재시도 · 데이터 신선도 게이트(봉 2개/2분) · LLM 응답 캐시 · 포트폴리오 총노출 한도 · 예측 적중률 추적 · 성과 대시보드.
- **GH Nano 사무실에도 같은 기능 이식** (콘테스트 · 앙상블 · 적응형 재학습 · 표 UI).

**모델 쏠림 해결** — 직원 전원이 한 모델(gpt-oss-20b)만 쓰고 한국어 답을 못 내던 문제
- 원인: 브라우저 저장소에 쌓인 기록(`deadModels` 404 숨김, 옛 '전원 배정', `pinModel`)으로 후보 모델이 1개로 줄어듦.
- 해결: 팀 구성 화면 '전원 AI' 옆 **[🔄 모델 전체 켜기·초기화]** = `resetModels()`. 모델 점수에서 gpt-oss 를 한 단계 뒤로(한국어 우선). `assignModels` 가 최대 6개 모델로 분산. 모델이 한국어 최종 답을 못 내면 '생각' 부분이라도 보여 주는 폴백.

**차트 터미널**: 실험 탭 🏆 신뢰점수 · ⚡ 전체 분석 버튼 · 다이버전스 지표(일반 + 히든) · 지표 계산 캐시로 속도 개선.

**기타**: 단타/스윙 포지션 추천 · 투자위원회 투자 대가 페르소나 + 상황 유사도 기억 · AI 가 만든 전략 JSON 자동 교정(`pickJSON`, 봉 이름 · id 충돌 · 수식) · 👛 내 지갑 보기(읽기 전용, GH Nano 사무실 상단에도 버튼).

### 5-1. 뉴럴 데스크 (10/4) — GH Coin 전용. 연결된 NVIDIA 무료 AI 모델들이 **직접** 거래·학습·복기·설계
- **엔진** `gh-coin/neural.js`: 피처 뉴런(모멘텀·추세·RSI·거래흐름·호가압력·변동성) + 모델 트레이더. 1분봉 · SL-2/TP+3/시간청산(8분). `modelStep()` 이 틱당 1개 모델에게 `brainStream({role:"fast",fallback:true})` 로 직접 판단을 받고, **실제 응답 모델**(`route.model`)에 귀속(한 모델 429 로 전체 실패하던 문제 해결). `designStrategy()` 는 모델이 146개 지표 조합으로 매매법+커스텀지표 설계→`normalizeSpec/backtest/walkForward`→통과 시 사무실(`P.addStrategy`)에 인계.
- **자체 뇌** `gh-coin/brain.js`: localStorage 영속 집단 기억. `learn/recall(RAG식 회상)/reinforce`. **`consolidate()` 자체학습** = 오래된 기억 망각 + 자주 확인된 패턴을 '핵심 규칙'으로 승격. `graph(70)` 노드/엣지.
- **UI** `gh-coin/neural-ui.js`: 6카드(손익 · 🔍스캔·포지션 · NEURAL SHELL · 트레이더 리더보드 · 거래/설계 · 🧠뇌 지식 그래프). 뇌 그래프는 force 시뮬(새 지식=퍼지는 링, 유형별 색). 루프: step 매틱 · modelStep 매틱1개 · reflect 14틱 · designStrategy 26틱 · brainThink 10틱.
- 적용 개념(코드복사 없이): AI 트레이더 레포 5종 + brain 레포 5종 + Obsidian 6종(jsoncanvas·obsidian-api·clipper 등) → `gh-coin/tech.js` 크레딧.
- **뇌 지능(자가학습)** `brain.js`: `predict/learnOutcome`(국면별 피처 가중치 온라인 퍼셉트론, 거래 손익으로 교정)·`iqScore`(정확도·칼리브레이션 0~100)·`learnLoss/trapRisk`(손절 함정 기억→비슷한 자리 회피)·`refineForProfit`(이득 규칙 정제)·`ingest`(외부 결과 받기)·`toCanvas`(.canvas 내보내기, Obsidian에서 열림). 검증: 40판 학습 후 정확도↑·숏 함정 회피 확인.
- **닫힌 고리**: neural.js step/modelStep이 뇌 예측을 결정에 섞고 손절함정이면 진입 보류·모델에 "왜 손절났나" 교훈 주입 → closePos/closeModelPos가 결과를 뇌에 학습. coin-office.js `brainSyncJob`(JOBS에 "brainsync")이 에이전트 팀 데모거래를 뇌에 넣고→정제 규칙을 `ghcoin/brain/refined-rules.md`(옵시디언)로 저장·설계팀 인계.
- exe 재빌드 완료(`dist/*.exe`, 최신 커밋).

### 5-2. 뉴럴 데스크 매매 엔진 재작성 (10/5) — `gh-coin/strategies.js` + `neural.js`
- **손실 원인(코드 확인)**: 1분봉 8분 시간청산(→수수료만 내는 청산 반복) · 6피처 평균 노이즈 진입 · 손실마다 레버리지 깎는 학습(→저배) · 대상 없는 AI 호출이 로컬전용에서 조용히 실패(웹검색·복기 미작동).
- **새 구조**: 사용자 매매법 16종을 실행 규칙으로(`ENG.LIB`) → 1H 국면 + 4H 상위추세 필터 → **청산공식 역산**(레버=floor(0.4/손절)·최소 20x·손절 상한 단타1.5%/그외2%·1회 리스크 0.5~1%·순손익비·+1R 본절·물타기 금지·동시리스크 4%·일일손실 3%) → AI 모델이 신호 승인/거절(90초 무응답 시 자체 엔진).
- **자체 백테스트 선별**: 2시간마다 모든 매매법×시간봉을 실제 데이터로 프레임워크 그대로 시험, 백테스트+실전 최근 20건 기대값 > +0.1R(5·15분봉은 >0.15R·15건)만 실전.
- **검증(실제 바이낸스, 워크포워드)**: 5·15분 20x+ 스캘핑 −0.18R/거래(무작위 수준, 수수료가 엣지 잠식) · 1H+4H필터+선별 **+0.06R/거래(258건, 승률 31%)** — 작은 플러스, 보장 아님.
- 웹 리서치(3분)·뉴스 위험(5분, 일정 임박 시 45분 진입중지)·AI 전략회의(10분)·매매법 개발(8분, 통과 시 실전 후보). 실패도 피드에 표시.

### 5-3. 오픈소스 '표시만' → 실제 결정에 연결 (10/5) — 사용자 목록 52개 레포 감사
- **진입 관문** `coinGate()` (`gh-coin/coin-office.js`, `paper.js` `setEntryGate` 로 데모→연결된 실거래 진입 직전에 await): 데이터 품질(Legend: 비정상 봉·누락·지연 → 차단) · 리스크 결정표(gs-quant/jdmn) · 투자위원회 반대+합의 67%↑ 차단(TradingAgents) · 뉴스 위험 · **미국 고영향 일정 ±30분 차단**(OpenBB 캘린더 `coinCalendar`) · 심리 극단 0.5배(day_trading_bot·KOME) · **자체 AI 앙상블 반대 60%↑ 차단**(bitoracle·cookbooks `coinSelfAI`) · ML 반대 확률 0.7배(ml-ko `coinML`) · TA 평점 반대 0.6배(tradingview-mcp `coinTARating`) · 패턴 반대 0.7배(stock-pattern·chart_patterns `coinPatterns`) · 알파 순위 0.75배(vnpy `coinAlpha`) · 펀딩 과열 0.5배(Vibe `fundingRegime` + 바이낸스 펀딩 이력 30분 캐시)·김치 프리미엄 0.7배(ccxt `coinData`) · 같은 코인·방향 2개↑ 차단(passivbot) · 순 쏠림 0.5배(SolTrade) · 포트폴리오 히트 6%↑ 차단·켈리 무우위 0.5배·손익비<1.2 0.6배(ai-trader-team rigor). 6개 시나리오 Node 테스트 통과.
- 각 팀 잡이 판정을 localStorage 에 기록(`coinTARating` `coinPatterns` `coinAlpha` `coinData` `coinML` `coinSelfAI` `coinCalendar`) → 관문이 읽음. 뉴럴 데스크도 `teamCheck()` 로 결정표·캘린더·자체AI·TA·쏠림을 반영.
- **뉴럴 매매법 추가** (`strategies.js`): 스토RSI 교차·PSAR 반전·다우 HH/HL(robobytes) · ATR 그리드 평균회귀 단일포지션(beenchangseo) · **6전략 가중 앙상블**(bigpie, `tuneEnsemble` 가 calibrate 때 앞70% 선택→뒤30% 검증 통과 시에만 채택). 실제 1H 6코인: 앙상블 +0.083R(258건), 나머지 음수 → 워크포워드 선별이 자동으로 실전 제외.
- Erfaniaa: 다른 코인 3개+ 중 1개 이하 수익이면 데모 투입 차단(근접 후보로 보관) · reladomo: 감사 사슬 끊김/전략 해시 불일치면 승격 불가 · my-cc-harness: QA 불합격 수정안 자동 반려 · agency-agents-ko: 팀별 핵심 원칙·성공 지표를 페르소나에 · conor19w: 삼중 EMA+스토RSI 봇 템플릿.
- 로컬 모델(Ollama) 개발 실패 원인 = 12k 토큰 프롬프트가 60초 타임아웃에 잘림 → 로컬은 압축 프롬프트·긴 타임아웃 · JSON 강제 · 형식 오류 시 오류를 돌려줘 1회 자가 수정 · 지표 별칭(volma→volume_sma 등).
- **🧬 매매법 진화(개선·수정·조합)**: 뉴럴 `strategies.js` `evolve()` — 상위 매매법을 손익비·보유기간 조정(개선) / 필터 10종 추가(수정: 거래량·ADX·EMA200·슈퍼트렌드·MACD·VWAP·RSI·세션·스퀴즈) / A 신호 + B 확인 N봉 내(조합) / 채택본 재진화 → 앞 70% 원본보다 +0.03R↑ & 뒤 30% +0.05R↑(8건+)만 채택(최대 16개, 부진 퇴출). calibrate(2시간)마다 + 사무실 `evoJob`(JOBS 2칸, 말로 "매매법 조합해줘"). AI 전략회의·개발팀장이 `try` 실험 제안 → 다음 보정에서 검증. 사무실 데모 전략(JSON)도 `lib/evolve.js` `addFilter/tweakRR/combine`(진입 AND) → 워크포워드 통과 + 부모보다 표본외↑ + 순열 p≤0.1 이면 데모. 실데이터 1H 6코인 2세대 시험: 예) 돈치안+슈퍼트렌드 0.5→OOS 0.65R, 앙상블+ADX/EMA200 0.16→OOS 0.38R (무작위 탐색이라 매번 다름 · 다중검정 위험은 실전 워크포워드 선별로 한 번 더 거름).
- 작은 모델 전략 JSON 관대 파싱(`quant.js normGroup`): "rsi<30" · "a and b" · {indicator,operator,value} · 중첩 그룹 허용, 버린 조건 예시를 오류에 표시.
- 제외: 채굴기(xmrig·RandomX·CryptoWalletMiner)·지갑(rainbow) = 안전 규칙 · biomolecular = 무관. 상태표 `gh-coin/tech.js` 갱신.

### 5-4. 뉴트론 MCP — Claude Code · Claudian(옵시디언) 연결 (10/5)
- **브리지** `gh-coin/neutron.js` (exe 에서만, `startCycle` 이 시작): `문서/GHNano 사무실/neutron/state.json` 1분마다(뉴럴 상태·뇌 전체·팀 판정·데모 전략·리스크 정책·매매법 목록) · 옵시디언 볼트 `문서/GHNano 사무실/GHCoin 뇌/` 10분마다(홈·코인별·지식 유형별·전략 엔진·진화·검증된 셋업·정책·학습된 리스크·데모·팀 판정·일지, 위키링크) · `neutron/inbox.jsonl` 30초마다 반영(**지식 메모·실험 제안·팀 과제 3종만**, 주문 등 다른 종류는 무시).
- **MCP 서버** `gh-coin/mcp/neutron-mcp.mjs` (의존성 없음, Node 18+): 도구 18개 — neutron_status/query_knowledge/top_setups/learned_winrates/strategy_engine/strategy_library/team_verdicts/risk_policy/demo_strategies/recent_trades/funding_scan · brain_get_structure/search_notes/read_note/find_backlinks(brain-mcp 호환 이름) · neutron_log_note/propose_experiment/add_task. 주문 도구 없음.
- 연결: 저장소 루트 `.mcp.json`(이 프로젝트의 Claude Code) · 앱이 볼트에 `.mcp.json`+`CLAUDE.md`+`.neutron/`(서버 사본) 설치 → 옵시디언 Claudian 플러그인이 볼트에서 Claude Code 를 열면 자동 연결. 다른 경로에서 쓰려면 `NEUTRON_DIR` 환경변수.
- **거래소 간 펀딩 스캔** `gh-coin/lib/fundscan.js` (Sharpe MCP 개념, 바이낸스·바이빗·OKX·비트겟 공개 API): 에이전트 도구 `funding_scan`(선물 스킬) · 뉴럴 승인 자료 · coinGate(전 거래소 과열 방향 0.7배) · MCP.
- **ocean-agent 개념**: 셋업 순위(기대값×승률×신뢰도) · 국면별 학습 승률 → 손실 검증된 국면(8건+, 평균<0)에선 그 매매법 진입 건너뜀(neural step).
- 검증: MCP 핸드셰이크·도구 18개 호출(실시간 펀딩 포함) · 런처 응답을 흉내 낸 Node 테스트로 설치→내보내기→볼트 16노트→받은 편지함 3건 반영(주문 요청 무시) 확인. **실제 exe·Claudian 에서의 연결은 미확인.**
- 설치 안 함(확인 결과): sharpe-mcp(상용 API) · ocean-agent(BUSL·실주문) · AgentNova(→AgentKthx 개명) · ClawTrade(2★·라이선스 없음) · brain-mcp(0★) · HyperLLM-4b(LoRA 어댑터뿐·GGUF 없음).

### 5-5. 옛 자가수정 패치가 새 exe 를 덮던 문제 (10/5)
- 증상: 뉴럴 데스크 UI 일부만 그려지고 "오류: N.startAuto is not a function". 원인: `문서/GHNano 사무실/app-patches/` 의 옛 수정본(neural.js 10/5 01:47 · agent.js·quant.js 10/3)이 exe 안 새 파일보다 우선 → 옛 엔진·옛 도구가 섞임.
- 조치: 옛 수정본을 `app-patches-backup-20261005/` 로 옮김(삭제 아님). 런처 `override.go`: 수정본 저장 때 원본 지문(`.base`, sha256)을 같이 쓰고, 지금 exe 원본 지문과 다르면(또는 지문 없으면) 수정본을 **무시** → exe 를 새로 빌드하면 낡은 수정본이 자동으로 꺼짐. 목록 API 에 `stale` 표시.

### 5-6. 뉴럴 셸 UI · Ollama 리더보드 · Claudian · OpenClaw (10/5)
- 뉴럴 셸(전체 폭, 밝은 종이 테마): 마켓 인셋 7장(가격·호가압력·체결흐름·변동성·모멘텀·동시리스크 스파크라인) → 피처 48유닛 → 결정 코어 3D 입자 구(합의 셀수록 주황 코어 커짐) + CORE CHARGE·FAIR P(UP)(학습된 뉴런 가중 로지스틱) → 활성 마켓(코인별 1분 틱·보유 ◆). 전부 실데이터.
- 리더보드: 엔진 v2 이후 '승인해야 생기던' 모델 목록 → 연결된 Ollama 모델 전부 항상 표시(최대 12, 이전 6).
- 설치: 옵시디언(winget) · Claudian 2.3.12(볼트 `.obsidian/plugins/realclaudian`) · Claude Code CLI(npm) · OpenClaw 2026.9.8(npm). Claude Code 로컬 MCP 등록: 저장소 `neutron-local`, 볼트 `neutron-brain` (✔ Connected, 볼트에서 실제 호출 확인).
- OpenClaw: `~/.openclaw/openclaw.json` — ollama/qwen2.5:7b, 게이트웨이 loopback+토큰, 채널 없음, tools.profile minimal + alsoAllow `neutron__*`, deny exec/process/browser/apply_patch, toolSearch 끔(작은 모델이 숨은 도구를 못 찾음), 뉴트론 도구 11개만. 하트비트 1시간(`문서/GHNano 사무실/openclaw/HEARTBEAT.md`). 예약 작업 "OpenClaw Gateway". 검증: 상태 조회·메모 쓰기 → 앱 뇌 반영까지 확인. 끄기: `openclaw daemon stop` / 제거 `openclaw daemon uninstall`.

### 5-7. 모델 순환 스캔 · 옵시디언→뇌 · 형식 오류 · 화면 비율 (10/5)
- **모델 순환 스캔** (`neural.js scanStep`): 신호가 없을 때 30초마다 연결된 모델이 차례로(한 번에 하나) 코인 하나를 읽어 {방향·확신·한 줄} → 1시간 뒤 실제 가격으로 채점(모델별 '읽기 적중률') · 승인 검토 프롬프트에 다른 모델들의 최근 의견+적중률 포함 · 확신 70%↑ 의견은 뇌 '관찰'로. UI: 스캔 카드에 모델별 칩, 리더보드에 최근 의견·적중률.
- **옵시디언 → 뇌**: 볼트 `내 메모/` 폴더(앱이 덮어쓰지 않음)의 노트를 10분마다 읽어 줄 단위로 학습(손절·주의·금지 → 교훈, 코인 이름 → 그 코인 기억). `ingestMemos()`.
- **형식 오류**: `quant.normalizeSpec` 이 피연산자가 깨진 조건만 빼고(`spec.warnings`) 진입 조건이 하나도 없을 때만 실패. 개발 잡 수정: 본인 → 같은 팀 다른 모델 동료 순서로 2회.
- **비율**: 상단 행 최소 250px, 표 열 너비·말줄임, 뇌 그래프 반발력을 면적/노드 수로 맞추고 라벨은 허브 12개만.
- Claude Code 는 사용자가(또는 Claudian 에서) 부를 때 동작 — 앱이 스스로 Claude Code 를 호출하지는 않음(구독 사용량·권한 문제). 자동으로 도는 것은 옵시디언 볼트 쓰기/읽기·OpenClaw 1시간 하트비트.

### 5-8. Robinhood 레포 5개 → 코인 선물 적용 (10/5)
- **siropkin/robinhood-ai-trading-bot**: `reviewPositions()` 5분마다(보유 있을 때) 모델이 보유 전체를 보고 hold/close/breakeven JSON 배열 → 환각 필터(보유 종목 정확 일치·허용 결정·코드 조건: close 는 +0.5R↑ 또는 −0.3R↓+4H 역행, 본절은 +0.5R↑) → 실행. 한도 `cfg()`: 동시 포지션 4 · 하루 진입 12(PDT 대응) · 청산 후 재진입 쿨다운 30분 · 제외 코인 — 뉴럴 헤더 ⚙ 한도 버튼.
- **kevin1chun/robinhood-for-agents**: 주문 미리보기 = 가격 칼라(신호가 `px0` 대비 0.35R↑ 추격·0.5R↓ 역행이면 취소). 코인 리서치 카드 `coinResearch()`(일봉 365: 1년 범위·위치·7/30/365일·펀딩) → 승인·스캔 프롬프트·MCP `neutron_coin_research`. OpenClaw 스킬 `openclaw/skills/ghcoin-neutron`(SKILL.md → status/research/experiment.md, ready 확인).
- **casatrickdev/robinhood-trading-tools**: `lib/whalecopy.js` 감지→필터(3건↑·순 30%↑·5분 이내)→리스크(적중 45% 미만 무시)→신호. 신호 생성 때 첨부 → 반대면 뉴럴 리스크 ×0.5, 에이전트 팀 coinGate ×0.6. 30분 뒤 채점(`whaleTrust`).
- **RobinBundler · noxa-bundler-bot**: 제외(시세 조작 도구 + exe 다운로드만 있는 저장소 = 악성코드 위험). 다운로드·실행 안 함.

### 5-9. ⚡ 실시간 진입 (손매매용) — 에이전트 팀 ↔ 뉴럴 데스크 토론 (10/5)
- 엔진 `gh-coin/liveentry.js`: 지지·저항(1h/4h 스윙 피벗 군집 + 터치 강도 + 거래량 프로파일 POC/VAH/VAL + 스냅샷 간 유지되는 호가 벽) · 다중 시간대 추세(15m/1h/4h EMA·슈퍼트렌드·ADX) · 모멘텀(RSI·MACD·스토·BB·VWAP) · 고래·펀딩·팀 판정. 손절 = 구조 레벨 너머 0.25ATR(0.3~2%), 익절1/2 = 다음 레벨(벽) 바로 앞. 트리플 배리어(López de Prado) 방식으로 '절반 익절 → 본절 → 익절2' 계획을 과거 15m·1h 에 시뮬레이션, 조건 없는 기준값 쪽으로 베이지안 축소.
- **2개월·6코인 표본외 검증(4,092건)**: 스냅샷 조합(지표·지지저항·호가)만으로는 우위 없음(전체 −0.12R, 앞 60% 에서 찾은 최선 조합도 뒤 40% 에서 ≈0R). → 등급을 다시 정함: **유력 = 워크포워드 검증 통과 매매법 신호(`neural.recentSignal`, 75분 이내, 기대값 > +0.1R)가 같은 방향 + 추세 2/3↑ + 손익비 1.5↑** (그 매매법의 손절·손익비·+1R 본절 계획 그대로) · 보통 = 추세 3/3 + ADX 25↑(우위 미확인) · 그 외 관망. 각 카드에 근거 문장 표시.
- 토론 `runLiveEntry` (coin-office): 유력·보통 상위 2개를 진입 타점팀 대표(JSON 찬반 + 손절·익절 제안) → 뉴럴 모델 반박(`neural.debateReply`, 팀 문장 반복이면 기권 처리). 제안된 손절·익절은 같은 시뮬레이션으로 재검증해 기대값이 나아질 때만 채택. 둘 다 반대면 한 단계 내림(찬성으로 올리지는 않음).
- 자동: 앱 시작 40초 뒤부터 3분마다(토론은 같은 자리 10분에 한 번) · 사무실 업무 `rtentry`(말로 "실시간 진입/손매매/지금 진입") · 차트 터미널 선(진입·손절·익절·레벨) · 새 '유력'은 본부 알림 + 브라우저 알림(허용 시) · 뉴럴 데스크 ⚡ 카드(복사 버튼) · MCP `neutron_live_entry`.
- 버그 수정: 지지·저항팀 `levelsOf` 가 `data.walls`(없는 필드)를 읽어 호가 벽이 한 번도 안 들어가던 문제 → `bidWalls/askWalls`.

### 5-10. ⚡ 시장가 버튼 (손매매 즉시 타점) — 10/5
- **차트 터미널 상단 `⚡ 시장가`** (GH Coin 앱에서만, `window.ghCoinMarketEntry`) · **뉴럴 데스크 ⚡ 카드의 코인별 버튼** → `coin-office.marketEntryNow({sym})`: 분석 → 에이전트 팀(진입 타점팀 대표) 롱/숏/관망 선택 + 손절·익절 제안(재시뮬레이션 후 개선될 때만 채택) → 뉴트론(뉴럴 모델) 반박 → 반대면 팀 최종 유지/철회 → 결론. 결과 패널(터미널 오른쪽)·차트 선·`coinMarketEntry`·실시간 진입 목록 갱신.
- **내 차트 지표 사용**: `nuri-ai/terminal/readings.js` 가 `nuri:term:state.inds`(터미널에 띄운 보조지표)를 15분·1시간봉에서 봉마다 롱/숏 방향으로 읽음(늘 같은 방향인 거래량류 제외) → 지금 투표 + '지금과 80%↑ 같은 상태였던 과거'의 같은 계획 결과(베이지안 축소).
- **표본외(2개월·6코인) 결과**: 롱/숏 중 '더 나은 쪽' 고르기 규칙 4종 모두 음수(−0.03~−0.12R). 지표가 80%↑ 같은 방향일 때 그 방향 진입이 가장 나쁨(−0.15R, 추격) → 경고로 표시. 그래서 **'진입 가능'은 검증 매매법 신호(유력)일 때만**, 나머지는 '비권장 — 굳이라면 X쪽이 계산상 덜 불리'.
- 버그: 뉴럴 ⚡ 카드 클래스 `nd-live` 가 상단 초록 점(8px) 클래스와 겹쳐 카드가 8px 로 찌그러짐 → `nd-rtcard`.

---

## 6. 안전 규칙 (바꾸지 말 것)

- **AI 는 절대 주문하지 않음.** 주문은 코드(`nuri-ai/live.js`)가 한도 · 승인 안에서만.
- 실거래 기본 **꺼짐 · 테스트넷 먼저**. 메인넷은 `실거래를 시작합니다`, 자동 모드는 `자동매매에 동의합니다` 를 사용자가 직접 입력.
- 데모 → 실거래 관문: 14일 · 20거래 · 손익비 1.2 · 수익 + · 최대 낙폭 25% 미만 + 승격 결정표 + **신뢰 게이트**. 그래도 사용자가 실거래 화면에서 직접 연결해야 함.
- 기본 한도 (`live.js` `limits`): 주문당 20 USDT · 포지션당 최대 50 · 총 100 · 3배 · 동시 2포지션 · 하루 손실 20 USDT · 긴급 정지 · 주문마다 승인.
- API 키는 이 컴퓨터에만. 거래 키는 **출금 권한 없이 · IP 제한**.
- 지갑 보기는 **읽기 전용**: 개인키 · 시드문구 입력을 막고 저장하지 않음. 송금 · 서명 기능 없음.
- 스스로 코드 고치기: 독립 QA 채점 + **사용자 [적용] 승인** 필요, 안 열리면 자동 되돌림. 보호 파일(`selfdev.js` 의 `PROTECTED`: `live.js` `live-ui.js` `live.css` `sw.js` `index.html` `selfdev.js` `engine.js` + `vendor/**`)은 못 바꿈.
- 학습 데이터: Claude · Gemini · OpenAI 유료 모델이 쓴 글은 약관 때문에 제외.
- 오픈소스는 **코드 복사 없이 규칙만** 재구현 → 출처는 `gh-coin/THIRD_PARTY.md` 에 기록.
- 공격용 보안 도구(CyberStrikeAI · hexstrike-ai · strix · Cairn 등)는 넣지 않기로 함.

---

## 7. 알려진 문제 · 아직 확인 못 한 것

- **실제 거래소 · 실제 AI 응답으로 전체 흐름은 확인 못 함** (개발 환경 외부 접속 제한). 신뢰성 레이어는 함수 단위로만 검증.
- 투자위원회는 실제 AI 가 `등급:` 줄을 써야 결정이 나옴 (못 쓰면 REVIEW = 거래 안 함).
- 무료 모델은 404 · 느림 · 영어 답이 잦음 → 모델이 쏠리면 [🔄 모델 전체 켜기·초기화] 부터.
- 일부 경제 · 뉴스 사이트는 브라우저 차단이 있어 exe 실행기(`/__nuri/fetch`)로만 받아짐.
- 뉴럴 엔진의 +0.06R은 약 4개월·4코인 워크포워드 결과일 뿐 — 국면이 바뀌면 마이너스 가능. 선별 기준(SEL)·수수료(FW.fee 0.08%)는 `strategies.js`/`neural.js` 상단.
- **뉴럴 데스크**는 실제 NVIDIA 키가 있어야 모델들이 직접 판단함(키 없으면 자체 뉴런만). 모델 판단 품질·뇌 누적 효과는 실제 키로 장시간 돌려 봐야 확인됨 — 함수/문법 단위로만 검증.
- **진입 관문(5-3)** 은 Node 시나리오 테스트로만 검증. 각 팀 판정이 쌓이려면 사무실을 몇 시간 돌려야 함(판정 없으면 관문은 통과·1배). 관문이 너무 자주 막으면 데모 거래 수가 줄어 승격(20거래)이 늦어질 수 있음.
- **뉴트론 MCP(5-4)**: 실제 exe 로 `문서/GHNano 사무실` 에 파일이 생기는지, Claude Code 가 `.mcp.json` 을 승인 후 도구를 부르는지, Claudian 에서 볼트 연결되는지 아직 확인 못 함. 앱(Go)과 MCP 서버 모두 `%USERPROFILE%Documents` 고정 경로를 써서 서로 일치(다른 곳에서 쓰려면 `NEUTRON_DIR`).
- 로컬 소형 모델(qwen2.5:3b 등)은 전략 JSON 형식을 자주 틀림 → 자가 수정 1회로 일부 구제. 중형 모델(14b급)을 `code` 역할에 쓰는 게 낫다.
- `dist/*.exe` 는 **10/4 뉴럴 데스크 포함해 재빌드됨** (커밋 `e6c9f5a`). 단, 이 PC에서 아직 push 안 됐을 수 있음 → 9번대로 Cursor Sync.

## 8. 다음 할 일 후보 (우선순위 순)

1. 최신 코드로 exe 다시 빌드 → zip 두 개(GHNano · GHCoin) 배포.
2. 핵심 순수 함수에 `node --test` 테스트 추가 (4번).
3. 테스트넷 키로 실거래 흐름(관문 → 신뢰 게이트 → 승인 → 주문 → 긴급 정지) 실제 확인.
4. 실제 AI 키로 투자위원회 · 모델 배정이 한국어로 잘 도는지 확인.

---

## 9. 작업 습관 · 주의

- 사용자와는 **한국어로, 짧게**. 결과는 "무엇을 · 어디서 보는지 · 확인 못 한 것" 순서로.
- **push**: 이 PC의 비대화 셸(Claude Code 등)에서는 `git push` 가 인증 때문에 실패할 수 있음 → **Cursor 왼쪽 Source Control → Sync(↑)** 로 올림. 올린 뒤 `git status` 가 `up to date` 인지 확인.
- 커밋은 이 브랜치(`claude/eloquent-ride-3o1bqv`)에만. PR 은 요청 있을 때만.
- 다른 앱(GH Quant)은 `sweet-pascal` 브랜치에서 따로 작업 — 섞지 말 것.
- 화면 글씨 · 버튼은 한국어, 초보자도 알게.

---

## 10. 새 채팅에 붙여 넣을 문장

> GH Nano · GH Coin 이어서 작업해 줘. 저장소 g1792091-boop/crypto-bot-research, 브랜치 `claude/eloquent-ride-3o1bqv`. 먼저 저장소 맨 위 `HANDOVER.md` 를 읽고 시작해. 한국어로 짧게 답하고, 안전 규칙(6번)은 그대로 지켜. 실행은 `python devserver.py` → http://127.0.0.1:8777/gh-coin/ . 고친 뒤 확인하고, 필요하면 `launcher/build.sh` 로 exe 다시 만들어 줘.
