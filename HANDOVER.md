# 인수인계 — GH Nano · GH Coin (crypto-bot-research)

> 기준일 **2026-10-04** · 브랜치 `claude/eloquent-ride-3o1bqv`
> 새로 맡는 사람(또는 새 AI 채팅)은 이 문서만 읽으면 이어서 작업할 수 있게 썼습니다.
> 맨 아래 "새 채팅에 붙여 넣을 문장"부터 써도 됩니다.

---

## 0. 지금 상태 한눈에

| 항목 | 상태 |
|---|---|
| 코드 | 이 브랜치에 전부 있음. 10/4 작업(뉴럴 데스크 · 자체 뇌 · 지식 그래프 UI, 5-1번)이 최신 |
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
- **뉴럴 데스크**는 실제 NVIDIA 키가 있어야 모델들이 직접 판단함(키 없으면 자체 뉴런만). 모델 판단 품질·뇌 누적 효과는 실제 키로 장시간 돌려 봐야 확인됨 — 함수/문법 단위로만 검증.
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
