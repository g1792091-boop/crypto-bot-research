# Cursor(커서)에서 GH Coin 열기

이 저장소의 GH Coin 코드는 전부 브랜치 **`claude/eloquent-ride-3o1bqv`** 에 있습니다.
Cursor는 VS Code 기반이라 아래대로 하면 됩니다.

## 1. 클론 (둘 중 하나)

**A. 터미널 (브랜치까지 한 번에 — 추천)**
```bash
git clone -b claude/eloquent-ride-3o1bqv https://github.com/g1792091-boop/crypto-bot-research.git
```
그다음 Cursor → File → Open Folder → `crypto-bot-research` 선택.

**B. Cursor 안에서**
1. `Ctrl+Shift+P` → `Git: Clone`
2. `https://github.com/g1792091-boop/crypto-bot-research.git` 붙여넣기
3. 폴더 선택 → GitHub 로그인(비공개 저장소라 필요)
4. 연 뒤 `Ctrl+Shift+P` → `Git: Checkout to...` → **`claude/eloquent-ride-3o1bqv`** 선택
   (main 에는 변경분이 없습니다. 꼭 이 브랜치로!)

## 2. 폴더 구조 (주요 코드)
- `gh-coin/` — GH Coin 앱 (코인 전문 AI 에이전트)
  - `coin-office.js` — 사무실 엔진(업무·플래너·자체 AI·감정 등)
  - `coin-ui.js` · `coin-app.js` — 화면/시작
  - `coinai.js` — 코인 AI 봇(RAG)
  - `lib/` — selfai·sentiment·rigor·attbacktest·planner·board·lessons 등
  - `tech.js` · `THIRD_PARTY.md` — 도입 기술 출처
- `nuri-ai/` — 공용 엔진(quant.js 백테스터, ml.js, engine.js, live.js 등)
- `launcher/` — exe 빌드용 Go 런처

## 3. 실행 / 빌드
- **편집만**: 폴더 열면 끝. Cursor AI에게 "gh-coin 수정해줘" 식으로 시키면 됩니다.
- **exe 만들기**(Go 필요):
  ```bash
  cd launcher
  bash build.sh      # → ../dist/GHCoin.exe
  ```
  본인이 직접 빌드하면 백신 오탐 다운로드 차단이 없습니다.

## 4. 계속 받아오기
클라우드(여기)에서 코드를 더 고쳐 push하면, Cursor 터미널에서:
```bash
git pull
```
하면 최신으로 갱신됩니다.
