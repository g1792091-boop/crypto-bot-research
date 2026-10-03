# 인수인계 — GH Quant (crypto-bot-research)

마지막 갱신: 2026-10-03 · 기준 커밋 `570833b` (브랜치 `claude/sweet-pascal-t82h6j`)

이 문서만 읽고 바로 이어서 작업할 수 있게 정리했다. 기능 설명 전체는 [README.md](../README.md), 실행 안내(사용자용)는 [packaging/HOW-TO-RUN.txt](../packaging/HOW-TO-RUN.txt).

---

## 1. 한눈에 보기

- **무엇:** 코인 무기한 선물 분석 터미널. FastAPI 백엔드(`backend/`) + 바닐라 JS 프런트(`frontend/`). 트레이딩뷰식 차트를 직접 만들었고(lightweight-charts), AI 사무실(31개 팀 · 321명), 오토파일럿, 시나리오 진입 봇, 게이트가 걸린 실거래 실행기가 들어 있다.
- **어떻게 배포:** PyInstaller 로 묶은 **PC 앱**(윈도우 exe · 맥 .app). 브라우저 탭이 아니라 pywebview(WebView2/WebKit) 네이티브 창으로 뜬다. GitHub Actions 가 빌드해 릴리스 `desktop-latest` 에 올린다.
- **사용자:** 한국어로만 소통한다. 웹사이트가 아니라 "PC 앱"을 원한다. 결과가 화면에 **눈으로 보이는 것**을 중시한다(“달라진 게 없다”는 피드백이 나오면 대개 화면에 상태가 안 보이는 문제였다).
- **지금 상태:** 테스트 226개 통과. 마지막 CI(Build desktop app) 성공, 릴리스 `desktop-latest` 가 `570833b` 를 가리킴.

## 2. 저장소 · 브랜치 · 릴리스

| 항목 | 값 |
|---|---|
| 저장소 | `g1792091-boop/crypto-bot-research` |
| 작업 브랜치 | `claude/sweet-pascal-t82h6j` (여기에만 푸시. PR 은 요청이 있을 때만) |
| 다른 세션 브랜치 | `claude/eloquent-johnson-nnt7gh` — GH Nano / GH Coin. **직접 푸시 금지.** 수정은 `patches/ghnano-ghcoin-fixes.patch` 로만 (아래 7절) |
| GH Quant 릴리스 | https://github.com/g1792091-boop/crypto-bot-research/releases/tag/desktop-latest — `GHQuant-windows-x64.zip`(~40MB) · `GHQuant-macos-arm64.zip`(~32MB) · `preview-windows.png` |
| GH Nano/Coin 릴리스 | 태그 `ghnano-latest` — `GHNano-windows.zip` · `GHCoin-windows.zip`(각 ~23MB) |

CI 워크플로
- `.github/workflows/build-desktop.yml` — `backend/** frontend/** packaging/**` 가 바뀐 `claude/**`·`main` 푸시에서 실행. 윈도우·맥 빌드 → 스모크 테스트 → 윈도우에서 **앱 창 확인**(GHQuant 프로세스 창 제목 "GH Quant" + `app-window` 를 쓰는 msedgewebview2 프로세스) → 스크린샷 → 릴리스 갱신.
- `.github/workflows/build-ghnano.yml` — 다른 브랜치의 `NANO_BASE`(79440a4) 를 체크아웃 → 패치 적용 → Go 1.24 로 `launcher/build.sh` → 창 확인 → 릴리스 `ghnano-latest`.
- 릴리스가 어느 커밋인지: `GET /repos/g1792091-boop/crypto-bot-research/git/refs/tags/desktop-latest`.
- 릴리스 zip 은 30MB 가 넘어서 채팅으로 파일을 보낼 수 없다 → 릴리스 링크를 준다.

커밋 규칙
- 커밋 전에 `cd backend && python -m pytest -q` 전체 통과.
- 커밋 메시지 끝에 세션이 지정한 Co-Authored-By / Claude-Session 줄. 모델 이름·식별자는 커밋·코드·문서에 넣지 않는다.
- 푸시 실패(네트워크) 시 2·4·8·16초 간격으로 재시도.

## 3. 실행 · 테스트

```bash
# 개발 서버 (오프라인 가짜 시세)
cd backend
DATA_SOURCE=synthetic STATE_DIR=/tmp/gq_state python -m uvicorn app.main:app --port 8765
# → http://127.0.0.1:8765

# 테스트 (약 100초). conftest 가 SCENBOT_OFF=1 로 봇 스레드를 끈다
python -m pytest -q

# 데스크톱 빌드 (로컬)
pip install -r packaging/requirements-desktop.txt
python packaging/build.py      # frontend/build.txt 에 빌드 번호를 쓰고 PyInstaller 실행
```

작업 환경 함정 (클라우드 컨테이너 기준)
- 거래소(바이낸스·바이빗·OKX) 접속이 **403 으로 막힌다.** 실제 시세 검증은 여기서 못 한다 → `DATA_SOURCE=synthetic` 로 확인하고, 사용자에게 "가상 데이터로만 확인"이라고 밝힌다.
- 로컬 curl 은 `--noproxy '*'`, 서버는 `NO_PROXY=127.0.0.1,localhost`.
- `pkill -f "uvicorn app.main"` 은 자기 셸까지 잡아 exit 144 로 끝난다(서버는 꺼짐). 다른 명령과 같은 줄에 두지 말 것.
- 화면 확인은 Playwright: `require(require('child_process').execSync('npm root -g').toString().trim() + '/playwright')`. `playwright install` 은 하지 않는다.
- 차트 코인·분봉은 localStorage `ft.prefs` 로 미리 정할 수 있다: `{"symbol":"DOGEUSDT","interval":"5m"}`.

## 4. 코드 지도

백엔드 `backend/app/`
| 파일 | 역할 |
|---|---|
| `main.py` | FastAPI 라우트 전부. lifespan 에서 백그라운드 스레드 시작(`scenbot.start()` 등). `/api/status` 에 `build` |
| `config.py` | 환경 변수. `STATE_DIR`, `DATA_SOURCE`, AI 키, `FRONTEND_DIR`(PyInstaller 면 `_MEIPASS`) |
| `data/` | 시세: `market.py`(바이낸스 → 바이빗 → OKX 대체), `binance.py`, `altex.py`, `synthetic.py` … |
| `analysis.py` | 장세(regime) · 시나리오 엔진(박스권 양방향/돌파/이탈/눌림/반등 + 확률) |
| `scenbot.py` | **시나리오 진입 봇 런타임** (5절) |
| `quant/scenlearn.py` | 봇의 학습 코어: 삼중 장벽 채점 · 그림자 재생 · 보정 · 메타 라벨 · 정책 walk-forward |
| `quant/termind.py` | 프런트 `ind.js` 의 147개 지표를 서버에서 QuickJS 로 계산해 합의 점수 |
| `quant/` 기타 | `growth.py`(1억 챌린지 검증) · `grid.py` · `carry.py` · `protect.py`(freqtrade식 보호 장치) · `ml.py` · `risk.py` … |
| `live.py` | 실거래 실행기 (6절 안전 규칙) |
| `autopilot.py` | 오토파일럿. **`autopilot.context`** = 화면이 보고 있는 코인·분봉·지표 (프런트 `syncAutopilot()` 이 `/api/autopilot/context` 로 보냄). 봇의 '내 차트 따라가기'가 이걸 쓴다 |
| `office/` | AI 사무실: `org.py`(팀 정의 — 31팀/321명, `tests/test_office.py` 가 숫자를 검사), `roster.py`, `engine.py`, `teamjobs.py`(팀별 일), `tools.py`(직원 도구), `results.py`(파일 저장) |
| `knowledge/oss.py` | 오픈소스 조사 목록(적용한 것/다음 후보) |
| `launcher.py` | 데스크톱 실행기: 포트 찾기 → uvicorn 스레드 → pywebview 창, 실패 시 엣지/크롬 `--app` 창 + 유휴 종료 |

프런트 `frontend/js/`
| 파일 | 역할 |
|---|---|
| `chart.js` | 차트 엔진(`TermChart`). 오버레이 로딩 `refreshOverlays`, 봇 표시 `refreshSbot`·`_applyMarkers`, 범례 `_legend`, 봇 상태 줄 `sbotLine()` |
| `trade.js` | 트레이드 화면. 시나리오 패널 `renderScenarios`(배운 적중률·봇 상태), 5초마다 봇 갱신 |
| `office.js` | AI 사무실 화면. '진입 봇' 탭 `renderSbot`, '1억 점검' 탭 |
| `core.js` | `state`, `api()`, `syncAutopilot()` |
| `ind.js` | 지표 147종 (서버 termind 도 이 파일을 그대로 씀) |

상태 파일: `{STATE_DIR}/` 아래 JSON. 봇은 `scenbot.json`(설정·주문·거래·정책) + `scenbot_samples.json`(학습 표본, 최대 4만). 결과물은 `{STATE_DIR}/office/files/`. 데스크톱 앱은 실행 파일 옆 `state/`(쓰기 불가 폴더면 사용자 폴더로 대체), 로그는 `state/GHQuant.log`.

## 5. 최근 작업: 시나리오 진입 봇 (가장 최근에 손댄 곳)

사용자 요청: "시나리오 패널의 % 높은 것으로 계속 매매하는 진입 봇 + 진입 에이전트팀, 지표 확인하며 진입, 계속 학습·자동 개선" → "차트에 진입 보이게, 실시간 수익률, 레버리지 수정, 내 차트 분봉에서" → "달라진 게 없다".

동작 (`backend/app/scenbot.py`)
1. `_loop()` 15초마다 `tick()`. `pairs()` = 설정 코인 × 봉, '내 차트 따라가기'면 화면 분봉 + 화면 코인. **보고 있는 차트를 먼저** 처리.
2. 새 봉이 마감되면 `decide()`: `analysis.scenarios` → `L.setups`(체결 가능한 주문으로) → `L.rank`(정책 통과 순서) → 순위대로 `unfamiliar` · `checks`(지표) · 청산가 확인, 처음 통과한 것을 **가상 주문**. 막힌 이유는 `ST["status"]` 와 이벤트에 남는다.
3. `update_orders()` 가 이후 봉으로 체결/손절/목표/시간 청산을 판정(`L.simulate`), `mark()` 가 실시간 ROE.
4. `learn()` (뒤에서, 6시간마다 · 표본 없음 · 새 분봉): 과거 3000봉 그림자 채점 → 코인마다 보정(`cal`) 즉시 반영 → 메타 모델 → 정책 walk-forward(앞 70% 선택, 뒤 30% 판정, 부트스트랩 80% + 앞뒤 절반 모두 우세할 때만 채택). 무거운 계산은 잠금 밖.
5. 가상 성적이 기준(30건 · PF 1.2 · +0.05R · 낙폭 15R 이하)을 넘으면 실거래 탭에 `sb:SYMBOL` 승인 대기로만 올린다.

지표 확인 기준 (`scenbot.BLOCK`) — 종류마다 다르다. 여기를 바꾸면 체결 빈도가 크게 달라진다.
| 종류 | 파이썬 핵심지표 | 터미널 147종 | 내 차트 지표 |
|---|---|---|---|
| breakout(돌파) | 5개 중 점수 ≤ -3 | ≤ -35 | ≤ -40 |
| pullback(눌림목) | 추세 2개 모두 반대 | ≤ -50 | ≤ -55 |
| range(박스권, 역추세) | RSI·볼린저는 역으로 셈, ≤ -2 | ≤ -75 | ≤ -85 |

화면
- 차트 왼쪽 위 범례 + 시나리오 패널 맨 위: `🤖 시나리오 봇 켜짐 · 이 차트에서 판단 중 · 보유 ROE · 마지막 판단 · 다음 판단 · 학습 중…` (`chart.js sbotLine`, 데이터는 `scenbot._brain()`).
- 차트 주황색(#ff9f43): 지난 진입/청산 화살표, 대기 주문 점선, 보유 중 진입·손절·목표·청산가 선.
- 화면 맨 위 `GH QUANT` 옆 작은 글씨 = 빌드 번호(`frontend/build.txt`, 빌드 때 생성 · git 무시). 개발 서버에서는 "개발판".
- AI 사무실 → '진입 봇' 탭: 설정(레버리지 1–20, 증거금 %, 내 차트 따라가기), 코인·봉별 상태표, 주문, 보정, 정책 이력(되돌리기), 거래, 이벤트.

"달라진 게 없다"의 원인과 수정 (커밋 6ea5764, 570833b)
- 박스권이 돌파용 지표 기준에 걸려 절반가량 막힘 → 종류별 기준.
- 1순위가 막히면 끝 → 2·3순위 대체(`L.rank`).
- 주문이 없으면 화면에 아무것도 없음 → 상태 줄 항상 표시.
- 다른 코인 주문이 동시 한도 6개를 채우면 보는 차트가 판단 못 함 → 차트 쌍은 한도와 별도 한 자리.
- 학습 중 분봉 변경이 무시됨 → `_th["want"]` 로 끝난 뒤 재학습.
- 학습 마지막 단계가 몇 분간 잠금을 쥐어 봇이 멈춤 → 계산을 잠금 밖으로.

## 6. 반드시 지킬 안전 규칙

- 실거래는 **기본 꺼짐 · 테스트넷**. 켜려면 확인 문구 `실거래 켜기`, 테스트넷을 끄려면 `실제 돈` (`main.py` 의 `/api/live/settings`).
- 매매법(봇은 `sb:SYMBOL`)마다 **사람 승인** 필요. AI·자동 작업은 실거래를 켜거나 승인하지 않는다. 승인 엔드포인트는 `sb:` 항목을 `scenbot.candidate()["ok"]` 일 때만 받는다.
- 한도: 레버리지 최대 20배(코드에서 clamp), 주문·총액 한도, 하루 손실 한도 → 비상 정지(`live.kill`).
- 보호 장치(`quant/protect.py`)는 **새 진입만** 막고 청산은 언제나 허용.
- 바이낸스 키는 선물 거래 권한만, **출금 권한 금지**(문서·화면 안내 유지).
- "한 달 10만 원 → 1억을 보장하는 팀"은 만들지 않았다. 대신 정직한 검증팀(`quant/growth.py`)을 만들었다: 30일 1000배 = 매일 +25.9%, 좋은 전략 가정에서도 도달 확률 약 0.5% · 파산 약 86%. 비슷한 요청이 오면 같은 태도 유지.
- 다른 프로젝트 코드는 복사하지 않는다(GPL 등). 기법만 다시 구현하고 `knowledge/oss.py` 에 출처를 적는다.

## 7. GH Nano · GH Coin (다른 세션의 앱)

- 소스는 `claude/eloquent-johnson-nnt7gh` 브랜치(`nuri-ai/`, `gh-coin/`, `launcher/` Go 실행기). 이 브랜치에는 푸시하지 않는다.
- 우리 수정은 전부 `patches/ghnano-ghcoin-fixes.patch` (설명: `patches/README.md`). CI 가 79440a4 에 패치를 적용해 빌드한다.
- 패치를 고치려면: 79440a4 를 별도 worktree 로 체크아웃 → 수정 → 새 파일은 `git add -N` → `git -C <worktree> diff -- . ':(exclude)dist/*.exe' > patches/ghnano-ghcoin-fixes.patch`.
- 실행기: go-webview2 창(`native_windows.go`), 데이터 `%LOCALAPPDATA%\GHNano\WebView2`, 로그 `%LOCALAPPDATA%\GHNano\launcher.log`. 두 번째 실행(GH Coin)은 새 창을 만들지 않고 떠 있는 창을 `POST /__nuri/show`(헤더 `X-Nuri: 1`)로 전환한다 — WebView2 두 개를 같은 데이터 폴더로 띄우면 죽기 때문.

## 8. 아직 못 한 것 · 다음 후보

검증이 필요한 것
- **실제 시세에서 시나리오 봇 확인 못 함**(컨테이너에서 거래소 403). 사용자가 새 빌드(빌드 번호 `570833b`)로 봤을 때 상태 줄이 보이는지, 실제로 주문이 나가는지 피드백을 받아야 한다. 안 되면 상태 줄 캡처를 달라고 하면 이유가 그대로 적혀 있다.
- 실제 데이터에서 학습 시간(코인 5쌍 × 3000봉, 가상 데이터 기준 쌍당 약 7초 + 시세 받기)과 정책 채택 여부.

개선 후보
- 기본 정책 `min_prob` 40: 시나리오 세 개의 확률 합이 100이라 1순위가 40% 미만이면 아무것도 안 탄다. 사용자가 "왜 안 들어가냐"고 하면 35 로 낮추는 것을 검토(정책 최적화가 어차피 다시 고름).
- 범례 상태 줄 위로 EMA 등 일부 선이 겹쳐 그려진다(다른 캔버스 레이어가 위). 읽는 데 문제는 없지만 레이어 z-index 정리 여지.
- `knowledge/oss.py` 의 todo: ROI 표, Edge 포지셔닝, CUSUM 이벤트 필터, 정화·엠바고 교차검증, 온라인 메타 모델, 할인 톰슨 샘플링 등.
- 봇 → 실거래 경로: `scenbot.live_items()` 가 `teamjobs.live_items` 에 합쳐지고, 승인된 `sb:SYMBOL` 만 `live.sync` 가 실제 포지션으로 따라간다. 코드와 단위 테스트까지만 확인했고, **테스트넷 실주문으로는 아직 확인하지 않았다**(사람이 키를 넣고 한 번 확인해야 함).

## 9. 사용자 요청 이력 (최근 순)

1. 인수인계 파일 (이 문서)
2. "달라진 게 없어" (DOGEUSDT 5분 바이빗 실제 데이터 캡처, 봇 표시 없음) → 5절 수정, 릴리스 갱신
3. 시나리오 봇 차트 표시 · 실행 안 됨 · 실시간 수익률 · 레버리지 수정 · 내 차트 분봉
4. 시나리오 % 높은 것으로 계속 매매하는 진입 봇 + 진입 에이전트팀, 학습·자동 개선, 깃허브 코드 분석 반영
5. 깃허브 자동매매·챗봇 코드 적용 + "한 달 10만 원 → 1억" 팀 → 정직한 검증팀 · 그리드/펀딩 · 보호 장치 · 오픈소스 연구팀
6. 브라우저 창이 아니라 진짜 PC 앱으로 (GH Quant · GH Nano · GH Coin 모두)
7. 직원 AI 키 배정 방법 · zip 두 개 · GH Nano 직원 AI 키 문제 · 사업계획서 저장 위치 · 이전 앱에 팀 추가
8. GH Coin 에 터미널 보조지표 조합 추세·타점팀
