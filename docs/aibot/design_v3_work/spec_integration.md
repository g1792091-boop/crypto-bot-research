# AI 트레이더를 돌아가는 규칙 봇에 붙이기: 엔지니어링 명세 (통합 담당, 초안 10/8)

> **설계 문서입니다. 아무것도 만들지 않았습니다.** 두 분이 "좋아" 하시기 전에는 코드·설치·API 호출을 하지 않습니다.
> 비용 숫자는 모두 **추정**입니다. 0차 재생 시험(10/14~15)에서 실제로 재기 전까지는 추정이라고 읽어 주세요.
> 환율 가정: 100만원 ≈ 700달러 (1달러 ≈ 1,429원).

읽은 코드: `paperbot/live3.py`, `extras.py`, `accounts.py`, `engine.py`, `config.py`, `store3.py`, `models.py`, `policy.py`, `sizing.py`,
`risk.py`, `levrule.py`, `margin.py`, `sigservice.py`(상태값), `daily3.py`, `obsshadows.py`, `checkpoint.py`, `runinfo.py`, `fillcost.py`,
`feed.py`, `flow.py`, `archive.py`, `live.py`, `agents/debate.py`, `deploy/install.sh`, `deploy/paperbot-live3.service`,
`deploy/paperbot-debate.service`, `deploy/debate.env.example`, `deploy/update-dash.sh`, `deploy/paperbot-backup.sh`,
`docs/extra-accounts.md`, `docs/live-safety.md`, `docs/paper-v4-rules.md`(8절), `docs/aibot/PLAN_ATTACH_KO.md`, `AIBOT_DESIGN_KO_v2.md`(1, 4, 5장).

---

## 0. 한 줄 요약

AI 트레이더는 **규칙 봇 프로세스 안에 넣지 않고, 규칙 봇을 "따라가는 장부"(follower)로 붙입니다.**
규칙 봇(`paperbot-live3`)이 이미 기록하는 신호(`paper3.db signal_log`)와 실제로 밟은 1분봉(`paper3.db live_bars`)을
**읽기 전용**으로 받아, 같은 엔진 코드(`engine.PaperEngine`)·같은 비용·같은 기준가로 AI 계좌를 따로 굴립니다.
규칙 봇 코드는 한 글자도 바뀌지 않고, AI 설치·수정 때 규칙 봇을 재시작하지 않습니다. 그래서 규칙 봇 결과는 바이트까지 그대로입니다.

---

## 1. 붙이는 방식 결정: 추가 계좌(extras) 방식 vs 따라가는 장부 방식

PLAN 초안은 "규칙 봇이 20초 안에 온 답만 읽는다"(PLAN 1-2 5번)고 적었습니다. 코드를 읽어 보니 그 방식(규칙 봇 프로세스 안에서
AI 답을 받는 것)은 아래 문제가 있어 **채택하지 않습니다.** 대신 같은 효과(같은 가상 거래소, 규칙 봇은 절대 기다리지 않음)를 더 안전하게 냅니다.

| 항목 | A. 추가 계좌 종류 `ai`를 `extras.py`에 넣기 | B. 따라가는 장부 (채택) |
|---|---|---|
| 바뀌는 규칙 봇 파일 | `extras.py`(EXTRA_FILES: 추가 계좌 Q5 사건), `runinfo.py`, `daily3.py`, `checkpoint.py` | **없음** |
| 규칙 봇 재시작 | 설치 때마다, AI 버그 수정 때마다. `live3.cmd_run`의 5분봉 부트스트랩(`fetch_5m`, 약 116,000봉, 0.5초 간격)이 몇 분 걸려 그동안의 신호는 LATE → 331개 규칙 계좌가 경계를 놓침 | 없음 |
| `daily3` 재계산 | `daily3.replay`는 `extras_of`로 원래 종류가 아닌 계좌를 모두 다시 돌리는데, AI 계좌의 진입은 `signal_log`가 아니라 AI 답에서 오므로 매일 불일치(CRITICAL) → daily3 수정 필요 | AI 계좌는 `paper3.db`에 없음 → daily3 그대로 |
| 11/04 판정 | `checkpoint.account_family`는 모르는 종류를 `"core"`로 보냄(572행 주석 "an unknown kind: never a group of its own") → AI 계좌가 규칙 봇 판정·FDR 묶음에 섞임 → checkpoint 수정 필요 | AI 계좌는 `paper3.db`에 없음 → 판정 분리가 저절로 됨 (PLAN 2-4) |
| 20초 답 받기 | `Runner3.post_boundary`는 경계 계산 직후 한 번 불림. 늦게 온 답을 넣으려면 `post_batch`(폴 끝, 5초마다)에서 제출해야 하고 체결 시점이 폴 타이밍에 좌우됨 | AI 장부가 **자기** 1분 처리를 답이 정해질 때까지 늦춤(장벽). 규칙 봇과 무관 |
| AI 오류의 영향 | 같은 프로세스·같은 `paper3.db` 쓰기 잠금·같은 메모리 | 다른 사용자, 다른 프로세스, `paper3.db`는 OS 수준에서 읽기만 |
| 초기화 규칙 (PLAN 2-5) | `paperbot-reset.sh`가 `paper3.db`를 보관하면 AI 계좌도 사라짐 | AI 계좌는 자기 DB에 있어 규칙 봇 초기화와 무관 (감지 장치는 11장) |

**extras에서 재사용하는 것(코드가 아니라 방식):** `GuardedEngine`(예외가 나면 그 계좌만 정지), 상태 어휘(active / suspended / held + 이유 코드 + `effective` 시각이 있는
events), `accept_code` 같은 "두 분이 받아들임" 키, 따로 모으는 알림 모음(`ExtrasDigest`), 단계별 저장과 되돌림(`Journal`, savepoint).
`GuardedEngine`은 **복사**합니다(`import`하지 않음): 그래야 `extras.py`가 바뀌어도 AI 엔진이 바뀌지 않습니다.

**import해서 그대로 쓰는 것(수정 없음):** `accounts.AccountBook`(`load(make_of=...)`로 엔진 클래스를 넘김), `engine.PaperEngine`·`engine_state`·`restore_engine`,
`policy.RecommendedPolicy`·`RecommendedSettings`·`OwnerPolicy`, `sizing.SizeDecision`·`size_position`, `margin.liquidation_price`·`Brackets`,
`levrule.requested_tier`, `config.v3_settings`·`V3_STOP_ATR`·`V3_SYMBOLS`, `store3.Store3`(AI 장부도 같은 표 구조), `aggregate.Aggregator`,
`daily3.make_signal`·`_alone`·`fetch_steps`·`load_live_bars`·`steps_on_live_bars`·`compare`, `obsshadows.symbol_steps`·`run_alone`,
`runinfo.code_hashes`·`brackets_hash`, `health.sd_notify`·`DeadMan`, `notify.Router`·`Digest`, `binance.BinanceREST`(공개 요청만).

---

## 2. 전체 구조

```
 [paperbot-live3]  (그대로, user paperbot)
   feed → 1분 step → 5분 경계 _signals → signal_log + live_bars + state(heartbeat) 커밋 (5초 폴마다)
        │ paper3.db  (WAL, 다른 프로세스는 file:...?mode=ro 로만)
        ▼
 [paperbot-aibook]  따라가는 장부 (user paperbot-aibook, 키 없음)            /var/lib/paperbot/aibook/aibook.db
   - signal_log를 id로 1초마다 읽음 → 범위·동점·보유 중 규칙·한도 사전 검사 → 질문(ask) 기록
   - live_bars를 ts로 읽음 → AccountBook(AI 엔진들).step  ※ 장벽: 그 분에 체결될 질문이 다 정해질 때까지 기다림
   - 답 해석(resolution) → 진입 제출 / 보유 행동 예약 / 무응답 = 건너뜀
   - 짝 비교 기록(규칙 혼자 R, 코드만 R, 방향 뒤집기), 한도 상태, 쌍둥이 결과
        │ aibook.db (ro)                       ▲ aidecide.db (ro)
        ▼                                      │
 [paperbot-aitrader]  AI 판단 (user paperbot-ai, ANTHROPIC 키 보유)      /var/lib/paperbot/ai/aidecide.db
   - 질문을 0.25초마다 읽음 → 화면 만들기(as-of 규칙) → Claude 호출(마감 = 질문 시각 + 20초, 재시도 0)
   - 답 검증 → decisions 기록, 호출마다 토큰·비용 장부, 예산·내림 사다리
        
 [paperbot-aicheck.timer] 매일 00:40 UTC (09:40 KST, daily3 00:20·dscheck 00:30 뒤)   /var/lib/paperbot/aibook/aicheck.db
   - AI 계좌 재계산 일치, 규칙 혼자 R 재계산(daily3._alone), 동전(무작위 시각), 기록 완전성, 비용 요약 → AI 전용 텔레그램
 [대시보드 AI 탭] paperbot-dash가 세 DB를 읽기 전용으로 (update-dash 방식 배포)
```

| 프로세스 | 사용자 | 쓰는 DB (유일한 writer) | 읽는 것 (읽기 전용) | 비밀 |
|---|---|---|---|---|
| `paperbot-live3` (기존) | paperbot | paper3.db | — | live.env (읽기 전용 거래소 키) |
| `paperbot-aibook` (새) | paperbot-aibook (+그룹 paperbot) | aibook/aibook.db | paper3.db, ai/aidecide.db | aibook.env: AI 텔레그램만 |
| `paperbot-aitrader` (새) | paperbot-ai (+그룹 paperbot) | ai/aidecide.db | aibook.db, paper3.db, market.db, flow.db, liq.db | aitrader.env: ANTHROPIC 키 + AI 텔레그램 |
| `paperbot-aicheck` (새, 하루 1번) | paperbot-aibook | aibook/aicheck.db | paper3.db, aibook.db, aidecide.db | aibook.env |

- **DB 하나에 writer 하나** (저장소 원칙, handover 5.3). 서로의 DB는 `file:...?mode=ro`로만 엽니다.
- 같은 서버여야 합니다(SQLite를 네트워크로 나누지 않음). v2의 "별도 서버" 안은 이 방식과 맞지 않습니다(열린 질문 9).
- 규칙 봇 사용자 `paperbot`은 키 파일도, 키를 가진 프로세스의 `/proc/<pid>/environ`도 읽지 못합니다(`docs/live-safety.md` 1-9와 같은 이유).
  AI 장부도 키를 못 봅니다(다른 사용자).

---

## 3. 신호가 AI에게 가는 길과 시간표

### 3-1. 측정한 지연 (v4 실행 1.5일, 신호가 난 경계 144개)

v4 내보내기 `signal_log.csv`의 `delay_ms`(봉 마감 → 기준가 읽은 시각)를 계산했습니다(스크립트 `design/work/delay.py`).

| 묶음·봉 | 중앙값 | p90 | 최대 |
|---|---|---|---|
| 우리 36개 15m | 21.3초 | 23.7초 | 26.7초 |
| 우리 36개 1h | 30.1초 | 33.2초 | 36.2초 |
| 딥시크 15m | 25.6초 | 33.5초 | 42.7초 |
| 딥시크 4h | 39.0초 | 45.5초 | 46.3초 |
| **경계마다 마지막 신호 (= 커밋되어 보이는 시각의 하한)** | **25.9초** | **34.9초** | **46.3초** |

`live3.Runner3._signals`는 우리 36개 신호를 `log_signals`로 적고 제출한 뒤 딥시크를 계산하고, 마지막에 `book.save`로 한 번 커밋합니다.
그래서 **다른 프로세스가 신호를 보는 시각 ≈ 그 경계의 마지막 신호 + 몇 초**입니다.

### 3-2. 한 15분 경계 B의 흐름

| 시각 | 무엇 |
|---|---|
| B | 봉 마감 |
| B+8~20초 | 규칙 봇 피드 확정 대기(`settle_ms` 8초, `grace_ms` 20초) → 5분봉 집계 → 신호 계산 |
| B+26초 (중앙값, 최대 약 46초) | `signal_log` 커밋 (규칙 계좌에는 이미 제출됨, 기준가 = `ref_price`) |
| +1초 이내 | aibook이 `signal_log`를 `id > 마지막 id AND status='SUBMITTED'`로 읽음 → 질문 생성, **마감 = 생성 시각 + 20초** |
| +0.25초 이내 | aitrader가 질문을 읽고 화면을 만들어 호출. 클라이언트 시간 제한 = 마감 − 지금 − 0.5초 |
| 마감까지 | 답(`decisions.received_at`) 기록. 마감 뒤 도착 = 무응답(늦음) |
| B+60초 | B 다음 1분봉 마감 |
| B+68~75초 | 규칙 봇이 그 1분봉을 처리: 규칙 계좌가 `ref_price`로 체결, `live_bars`에 그 봉 기록 |
| 그 뒤 | aibook이 같은 1분봉으로 AI 계좌를 밟음. **이 분에 체결될 질문이 모두 정해진 뒤에만** (장벽). AI 진입도 같은 `ref_price`·같은 미끄러짐·같은 수수료 |

- **규칙 봇은 AI의 존재를 모릅니다.** 기다리는 쪽은 언제나 aibook 자신입니다. 최악(커밋 B+46초 + 20초 = B+66초)에도 aibook이 몇 초 늦을 뿐입니다.
- **보내는 방식은 DB 폴링**입니다(1초 / 0.25초). 소켓·inotify 같은 푸시는 쓰지 않습니다: 프로세스가 죽어도 질문·답이 DB에 남아 재시작 뒤 그대로
  이어지고, 감사 기록이 저절로 남습니다. 추가 지연은 1.5초 이하입니다.
- **경계 계산과 겹치지 않기:** 보유 중 봉 마감 점검처럼 5분 경계에 생기는 AI 작업은 규칙 봇이 그 경계를 끝낸 뒤(`paper3.db state.heartbeat.last_step ≥ B − 60,000`,
  `Runner3.process`가 경계 처리 뒤 폴 끝에 쓰는 값)에만 시작합니다. 규칙 봇의 신호 계산(Pool 4개)과 CPU를 다투지 않게 하려는 것입니다.
  +1R 움직임처럼 1분봉에서 생기는 깨움은 바로 냅니다.
- **늦게 본 신호:** aibook이 신호를 `ref_time`보다 60초 넘게 늦게 보면(aibook이 꺼져 있었음) 질문하지 않고 `LATE`로 남깁니다(규칙 봇 `LATE`와 같은 생각).
  짝 기록에는 "놓침(missed)"으로 남기고 코드 결과는 계산합니다(기록 완전성 유지).

### 3-3. 왜 AI 진입도 `ref_price`로 체결하나

- PLAN 1-2 6번: "같은 다음 1분봉 가격, 같은 수수료와 미끄러짐". 규칙 계좌는 신호의 `meta["ref_price"]`로 다음 step에서 체결합니다(`engine._try_enter`).
  AI 계좌도 같은 `Signal`(`daily3.make_signal`로 `signal_log` 행에서 다시 만든 것, 일치 검증된 방법)을 같은 분에 제출하므로 체결가가 **똑같습니다.**
  그래서 "AI R − 규칙 R"에는 판단 차이만 남고 체결 잡음이 없습니다.
- 미리 보기(look-ahead) 방지: 화면은 **as-of = 신호의 `ref_time`** 기준 자료만 씁니다(확정 봉, 그 시각 이전에 받은 시장 자료). 질문 시각 이후 가격은 보여 주지 않습니다.
- 실전의 현실(답을 받은 뒤 주문)은 따로 잽니다: 모든 AI 진입에 **"늦은 체결 그림자"**(답을 받은 분의 다음 분 시가 체결)를 계산해 기록합니다.
  실제 돈 전 판단은 이 그림자로 합니다(v2 5-3 7번 규칙과 같은 체결). 열린 질문 4.

---

## 4. AI 계좌 (새 계좌 종류)

### 4-1. 어디에, 어떤 이름으로

- `aibook.db`는 `store3.Store3` 표 구조를 그대로 씁니다(accounts, trades, outcomes, equity, state, alerts, runs). 대시보드의 계좌·거래 화면 코드를 DB 경로만 바꿔 재사용할 수 있습니다.
- 계좌 행: `account_id = "AI_<매매법>"` (예 `AI_N10_HA_PSAR`), `strategy = <매매법>`, `timeframe = "B"`(봉 구성 B; 실제 범위는 data에),
  `kind = "ai"`(판정 대상 Sonnet) 또는 `"ai_x"`(판정 밖 탐색: 11/01 뒤에 시작한 2차 등), `data = {roster_version, scope, cluster, wave, judged, model, sizing, exit_ref, lock_sha}`.
- Opus 쌍둥이는 **계좌가 아닙니다**(9-3). 같은 질문·같은 화면에 대한 "결정 그림자"입니다.
- 시작 자산 5,000 USDT, 격리 마진, 한 번에 포지션 1개(`Settings.single_position`), 코인 6개(`config.V3_SYMBOLS`).
  설정은 규칙 봇 실행의 설정에서 만듭니다: `v3_settings(taker_fee=<paper3.db state 'run'.taker_fee>)` 뒤 `replace(..., bust_below=1000.0)`.
  시작할 때 `runinfo` 설정 해시를 다시 계산해 규칙 봇 runs 행과 같은 비용인지 확인합니다(다르면 시작 거부).

### 4-2. 엔진: `paperbot/aitrader/engine_ai.py`의 `AIEngine(PaperEngine)`

`engine.py`는 바꾸지 않습니다. `obsshadows.SameLeveragePolicy`("The engine and sizing.py are unchanged: this is passed to PaperEngine as its policy")와
`reel_engine.ReelEngine`이 이미 쓴 방법(정책 주입 + 하위 클래스)을 따릅니다.

- **크기:** `self.policy = sizing_ai.policy_for(cfg, timeframe)` (6장, 한 경로).
- **코드 청산 (`exit_ref`):** 기본값 `"rule"` = 그 신호에서 **규칙 계좌가 썼을 레버리지**(같은 `Settings`, `levrule.requested_tier`, `sizing.size_position`을
  새 5,000달러 계좌로 계산)로 계단 잠금 가격을 계산합니다(`_raise_lock` 재정의). 즉 AI 계좌의 손절·잠금 **가격**은 규칙 계좌와 같고,
  AI 계좌의 실제 레버리지·크기와 무관합니다. 이유: 지금 `ladder.py`는 수익률(ROE) 기준이라 레버리지가 바뀌면 잠금 가격이 바뀌는데(검증된 결과:
  "높은 레버리지에서 더 작은 가격 움직임에 잠김"), 이렇게 하면 크기 규칙(6장)이 청산을 바꾸지 않습니다. 대안 `"r_ladder"`는 15장/열린 질문 2.
- **AI 행동(보유 중):** 답을 받은 시각의 **다음 분 시가**(`apply_ts = ceil_to_minute(received_at)`)에 적용합니다. 순서는 v2 5-3 6번과 같이
  강제청산 → 손절 → (잠금) → 그 분의 AI 행동.

| 행동 | 코드 검사 | 실행 |
|---|---|---|
| `HOLD` | — | 없음 |
| `EXIT_NOW` | 열린 포지션이 있어야 함 | `apply_ts` 분 시가 × (1 − side × slippage), 시장가 수수료, 사유 `AI_EXIT` |
| `STOP_TO_BE` (본전) | **최대 유리 움직임(MFE) ≥ +1R** 일 때만, 손절은 유리한 쪽으로만, 새 손절이 현재가에서 0.3 ATR 이상 | 손절 = 진입가 ± 왕복 비용(순손익 0 근처), `stop_initial`은 그대로 |
| `STOP_UP_0.5ATR` / `STOP_UP_1ATR` | 유리한 쪽으로만, 현재가에서 0.3 ATR 이상 | 손절 이동 |
| 그 밖(갈아타기, 추가 진입, 일부 청산, 손절 넓히기) | **항상 거부** | 기록만 (`rejected: not_allowed`) |

- 손절·잠금은 언제나 코드가 지킵니다. AI가 답을 못 해도 그대로 걸립니다.
- 행동마다 "원래대로 뒀다면" 결과를 같이 계산합니다: 행동 직전 `engine_state`를 복사해 `restore_engine`한 그림자 엔진을 행동 없이 끝까지 밟음 → `ai_actions.counterfactual_R`.
- `GuardedEngine` 방식: `step` 중 예외 → 그 AI 계좌만 `held`(동결), CRITICAL 알림, 다른 AI 계좌·규칙 봇은 영향 없음.

### 4-3. 답이 없을 때 (무응답)

| 질문 종류 | 무응답이면 |
|---|---|
| 진입 | **건너뜀.** `outcomes`에 `SKIPPED`, 사유 `ai:no_answer:<이유>` (timeout, http_429, http_5xx, network, refusal:<category>, schema, budget, service_down, late) |
| 보유 점검 | 아무것도 안 함. 코드 손절·잠금 그대로 |
| 쌍둥이·그림자 질문 | 그 결정만 빠짐 (기록) |

- 판정에서 무응답을 "건너뜀(0R)"으로 셀지 "빼고" 셀지는 판정 명세가 정합니다(열린 질문 3). 통합 쪽은 사유와 함께 전부 남깁니다.
- 답 형식 오류는 다시 묻지 않습니다(마감·비용). `refusal`(안전 분류기 거절)도 무응답입니다. **서버 쪽 대체 모델(`fallbacks`)은 켜지 않습니다:**
  켜면 거절된 질문이 다른 모델로 조용히 답해져 "Sonnet 판단"과 "Opus 쌍둥이 비교"가 섞입니다.

### 4-4. 장벽과 재현성

- aibook은 분 m을 밟기 전에 `fill_step ≤ m`인 모든 질문이 정해졌는지 확인합니다. 정해짐 = (`decisions.received_at ≤ 마감`인 유효한 답) 또는 (지금 > 마감).
- 결과(take / skip / no_answer, 적용 분, 이유)는 **`resolutions` 표에 먼저 쓰고** 그다음 엔진에 제출합니다. 판단 결과는 기록된 시각만으로 정해지므로
  (처리한 순간과 무관) aibook이 언제 죽었다 살아나도 같은 결과가 나옵니다. `aicheck`는 이 표로 하루를 다시 계산합니다.
- 같은 분에 여러 트레이더의 진입이 정해지면 **정해진 순서**로 한도를 적용합니다: 긴 봉 먼저 → 손절 폭(손절 거리 ÷ 기준가) 넓은 것 먼저 → KST 날짜로 도는 고정 순번.

---

## 5. 트레이더별 봉 범위·동점·보유 중 규칙 (코드)

### 5-1. `paperbot/aitrader/roster.json` (잠금 파일, 해시는 LOCK_MANIFEST)

```json
{"version": "roster-v1", "d0": "2026-10-17T12:00:00Z", "window_end": "2026-12-26T00:00:00Z",
 "wave2_start": "2026-10-31T12:00:00Z", "wave2_latest_judged": "2026-11-01T15:00:00Z",
 "clusters": {"ST_HA": ["N10_HA_PSAR","N23_HA_ST","S2_ST_ROC","N01_ST_EMA","N02_ST_KST","N04_ST_KLINGER","DOGE"],
              "PULLBACK": ["F16_FIB382","F16_FIB500","F9_FVG"], "DS_TREND": ["F7_RF_TRIPLE","F4_FAN","F6_VWAP_CROSS"]},
 "traders": [
  {"id": "AI_N10_HA_PSAR", "strategy": "N10_HA_PSAR", "source": "core", "tfs": ["15m","30m","1h"], "tf4h_20x": false,
   "wave": 1, "judged": true, "twin": {"S": true, "M": true}, "shadow_asks": {"S": true, "M": true}},
  {"id": "AI_F16_FIB382", "strategy": "F16_FIB382", "source": "ds200", "tfs": ["15m","1h"], "tf4h_20x": false,
   "wave": 1, "judged": true, "twin": {"S": false, "M": true}, "shadow_asks": {"S": true, "M": true}}
 ]}
```

1차 10명 (보고서 15-2 표, 진입 봉은 미리 고정):

| 트레이더 | 신호 출처 (`signal_log.strategy`) | 진입 봉 | 4h (신호마다 20배 검사) | 묶음 |
|---|---|---|---|---|
| N10_HA_PSAR | core | 15m, 30m, 1h | 없음 | ST_HA |
| F16_FIB382 | ds200 | 15m, 1h | 없음 | PULLBACK |
| F9_FVG | ds200 | 15m, 30m | 없음 | PULLBACK |
| N18_VWMA_MACD | core | 15m, 30m | 없음 | — |
| S4_BB_BBP | core | 30m, 1h | 있음 | — |
| N25_DST_CCI | core | 15m, 1h | 없음 | — |
| F6_VWAP_CROSS | ds200 | 15m, 30m, 1h | 있음 | DS_TREND |
| N23_HA_ST | core | 15m, 30m, 1h | 있음 | ST_HA |
| F4_FAN | ds200 | 15m, 30m, 1h | 있음 | DS_TREND |
| V39_ALL | core | 15m, 30m | 있음 | — |

2차 (등급 M만, 10/31 21:00 KST, 운영 기준만): F16_FIB500 15m · F7_RF_TRIPLE 30m+1h · S2_ST_ROC 15m+4h · N02_ST_KST 15m+4h · N07_ICHI_CMO 30m+15m ·
DOGE 1h+15m+30m(4h 없음) · N13_3OUTSIDE 1h+15m · (선택) H3A_RETAIL_FADE. 이름은 모두 저장소 신호 코드에 있음을 확인했습니다(`config.DS200_DEFS`,
`third_party/sweep/harness`). **H3A_RETAIL_FADE는 규칙 봇 신호가 아닙니다:** 지정가 체결과 롱숏 비율 신호를 aibook 쪽에 새로 만들어야 하는 별도 작업이고,
10/30까지 시험을 통과하지 못하면 N01_ST_EMA 또는 N04_ST_KLINGER로 대체합니다(보고서 15-3).

### 5-2. 코드 규칙 (`paperbot/aitrader/intake.py`)

1. **범위:** `signal_log.strategy == trader.strategy` 이고 `timeframe in trader.tfs` 인 `SUBMITTED` 행만. 나머지는 기록도 하지 않음(규칙 봇이 이미 기록).
2. **4h 입장 검사 (`tf4h_20x`가 true일 때만):** 진입가 = `ref_price`, 손절 = `ref_price − side × stop_dist`(`data.stop_dist`, 없으면 `V3_STOP_ATR × atr`).
   "손절 너머 1 ATR" 지점이 **20배 격리 강제청산가 안쪽**인지 `margin.liquidation_price`(구간표 `Brackets.for_notional`)로 계산. 실패 → `scope_4h_fail` 기록, 질문 없음.
   이 검사는 크기 규칙(6장)과 상관없이 입장 조건으로 씁니다.
3. **동점 (같은 경계, 트레이더가 비어 있음):** 긴 봉 먼저 → 손절 폭(%) 넓은 것 먼저 → 코인 순번(`V3_SYMBOLS`를 KST 날짜 번호만큼 돌린 순서). **진입 질문은 경계마다 1개.**
   나머지 후보는 `paired.kind = 'tie'`로 남기고 코드 결과만 계산(그림자 질문 대상이면 그림자 질문). AI가 1순위를 건너뛰어도 2순위를 다시 묻지 않습니다(열린 질문 6).
4. **보유 중:** 새 신호는 진입 질문이 되지 않습니다. 예외 두 가지만 **보유 점검 질문**(깨움)이 됩니다: 들고 있는 코인의 반대 방향 신호, 자기 매매법의 더 긴 봉 신호.
   갈아타기는 없습니다(AI가 답해도 거부). 나머지는 `paired.kind = 'blocked'`, 그림자 질문 대상이면 그림자 질문.
5. **한도에 막힘:** 질문 전에 한도(7장)를 미리 검사해 확실히 막히면 묻지 않고 `REJECTED_CAP`(비용 절약). 답을 받은 뒤 다시 검사해 그 사이 다른 트레이더 체결로 막히면 `REJECTED_CAP_AFTER`.
   둘 다 코드 그림자 결과를 계산합니다(보고서 15-7 "한도가 비교를 왜곡하지 않게").
6. **보유 중 깨움 (`hold_wakes`, 등급별 설정, D0에 잠금):** 들고 있는 봉 마감, +1.0R 처음 도달, 반대 신호, 긴 봉 자기 신호, 경제 발표 30분 전·직후(`data/macro_events.csv`).
   0.5R 움직임 깨움은 쓰지 않습니다(15분 포지션에서 시간당 약 1.5~1.8번 울림, 보고서 15-9).

---

## 6. 크기 규칙 하나로: `RecommendedPolicy` 충돌을 코드에서 푸는 법

충돌(보고서 10-4, 16장 3번): 저장소 `policy.RecommendedPolicy`는 위험 1%, **맞는 레버리지 중 가장 낮은 것**(`lev = ceil(notional / equity)`), 10배 상한, 3 ATR 여유.
분석 권장은 위험 1%, **50/40/30/20배 중 맞는 가장 높은 것**, 1 ATR 여유, 최저 3배. 두 분이 하나를 고르십니다. 코드는 이렇게 한 경로만 둡니다.

- `paperbot/aitrader/sizing_ai.py`의 `policy_for(cfg, timeframe) -> Policy` **하나만** 정책 객체를 만듭니다. 설정값 `sizing`은 D0에 잠급니다.
  - `"recommended_v1"` (다): `policy.RecommendedPolicy(base, replace(RecommendedSettings(), risk_frac=r_tf))`. **policy.py의 클래스를 그대로** 씁니다(버전 문자열 `recommended-v1`).
    `RiskGuards`(하루 3%·5연패)는 넘기지 않습니다(한도는 7장 한 곳에서).
  - `"fixed_risk_maxlev_v1"` (라): 새 클래스 `FixedRiskMaxLevPolicy`(같은 파일). 위험 금액 = 지갑 × r_tf, 수량 = 위험 ÷ (손절 거리 + 손절 미끄러짐 + 왕복 수수료),
    레버리지 = 50, 40, 30, 20 순서로 "구간표 허용 + 손절 너머 1 ATR이 강제청산가 안쪽"을 처음 만족하는 값, 없으면 19배부터 3배까지 내려가며, 3배도 안 되면 거절.
    50배는 같은 검사를 통과할 때만. 수량은 `qty_step`으로 내림, `min_notional` 미만 거절, 반올림으로 위험이 5% 넘게 줄면 기록.
- `r_tf`: 15m·30m 1%. 1h·4h는 1%(기본) 또는 1.5%(두 분 선택, 검증 결과의 상한).
- **같은 객체를 AI 쪽 모든 곳이 씁니다:** AI 계좌, 코드만 그림자(9-1), 행동 반사실, 늦은 체결 그림자, 동전, 0차 재생, aicheck. 규칙 혼자 R만 규칙 계좌의 `OwnerPolicy`(v4 그대로)로 계산합니다.
- 확신도(1~5)는 기록만 하고 크기에 쓰지 않습니다(검증 결과: 200건 이상에서 순위 상관 > 0이 나오기 전까지).
- (다)를 고르면 실제 레버리지는 대개 2~5배, 증거금은 지갑의 대부분입니다(갭 손실 상한이 큼). (라)를 고르면 20~30배, 증거금은 지갑의 약 3~5%입니다. 기대 R은 같습니다(보고서 16-3).
  `exit_ref = "rule"`(4-2) 덕에 어느 쪽을 골라도 청산 가격은 바뀌지 않습니다.
- 나중에 실제 돈으로 갈 때 주문 실행기(`paperbot/executor.py`, `risk.py`)도 이 클래스를 써야 합니다. 이번 범위 밖이며, `risk.py`(실거래 전용)는 바꾸지 않습니다.

---

## 7. 한도와 손실 제한 (`paperbot/aitrader/caps.py`)

순수 함수 + `CapState`(aibook.db state `ai_caps`에 매 step 저장). 실거래용 `paperbot/risk.py`는 건드리지 않습니다(그 파일은 실행기의 경로).
엔진의 `guards`는 쓰지 않고, 제출 직전에 장부 단위로 검사합니다(여러 트레이더에 걸친 한도라서).

| 한도 | 값 (보고서 15-7) | 검사 시점 | 걸리면 |
|---|---|---|---|
| 같은 코인·같은 방향 | AI 전체 동시 3개 | 질문 전 + 답 뒤 | `REJECTED_CAP` + 그림자 |
| 같은 내기 묶음 | 묶음 안에서 코인·방향당 1개 (`roster.clusters`) | 같음 | 같음 |
| 책 전체 같은 방향 | 동시 8개 | 같음 | 같음 |
| 트레이더 하루 | 실현 R + 열린 포지션 평가 R ≤ −3R → 09:00 KST까지 새 진입 없음 | 같음 | 같음 |
| 트레이더 검토 | 1% 곡선 −15%(약 −16R) → **그 트레이더 AI 호출 중지**(미리 등록한 가망 없음 중지). 열린 포지션은 코드가 관리, 짝 기록은 계속 | 매 거래 종료 | 상태 `suspended: futility` |
| 책 하루 | AI 전체 −12R → 09:00 KST까지 새 AI 진입 없음 | 질문 전 + 답 뒤 | `REJECTED_CAP` |
| 기존 규칙 유지 | 3연패(R ≤ −0.25) → 1시간 쉼, 손실 뒤 같은 코인·방향 자기 봉 2개 금지, 발표 앞뒤 진입 금지(CPI·PCE·고용 ±15분, FOMC −15분~+90분), 지갑 1,000 USDT 아래 = 파산 정지 | 같음 | 같음 |
| 자료 멈춤 | aibook이 규칙 봇 `live_bars`보다 3분 넘게 뒤처짐, 또는 디스크 여유 15% 미만 | 매 분 | 새 진입 없음 |
| 11/16 가망 없음 | 전체 짝 비교 90% 상한 < 0 이고 평균 ≤ −0.05R → **AI 호출 전부 중지**(규칙 추적은 계속) | 11/16 aicheck | 자동, CRITICAL |

- 하루의 경계는 00:00 UTC = 09:00 KST (규칙 봇·`risk.py`와 같음).
- 한도에 막힌 비율이 20%를 넘으면 대시보드·보고서에 표시(보고서 17-3 8번).

---

## 8. 기록: DB 세 개 (`paper3.db`는 읽기만)

### 8-1. `aibook.db` (writer: paperbot-aibook)

`Store3` 표 + 아래 표. 한 분의 모든 쓰기는 `AccountBook.save`의 커밋 하나에 같이 들어갑니다.

| 표 | 내용 |
|---|---|
| `ai_signals` | 본 신호 사본: `sig_id`(= paper3 `signal_log.id`), bar_close, tf, strategy, symbol, side, atr, ref_price, ref_time, delay_ms, data(ctx·stop_dist·lev_group), `seen_at`. paper3.db가 보관돼도 AI 쪽 기록이 스스로 완전하도록 |
| `asks` | `ask_id`, trader, `kind`(entry / hold / shadow_blocked / shadow_tie / shadow_cap / twin / coach), sig_id, `wake_reason`, `created_at`, `deadline`, `fill_step`, `asof_ts`, `screen_sha`, priority, payload(화면에 필요한 숫자) |
| `resolutions` | ask_id, `result`(take / skip / no_answer / hold_action / rejected_cap_after), `apply_ts`, reason, `decided_from`(decision id) |
| `ai_actions` | 보유 행동: trader, ask_id, apply_ts, action, params, status(applied / rejected:<이유>), `counterfactual_R` |
| `paired` | **보여 준(또는 보여 줄 수 있었던) 모든 신호 한 줄:** trader, sig_id, `kind`(shown / tie / blocked / capped / scope_4h_fail / late / futility), ai_result(take / skip / no_answer / –), `ai_R`, `rule_alone_R`, `code_only_R`, `flip_R`, `late_fill_R`, resolved 표시, KST day, half(앞/뒤 반), long, regime |
| `twin` | 쌍둥이 결정: ask_id, model, 답, `twin_entry_R` 또는 `twin_path_R`, `sonnet_R` |
| `caps_log` | 막힌 진입: 어느 한도, 그때 상태 |
| `ai_events` | 상태 변화·내림 단계·설정 변경: ts, `effective`, event, code, detail (판정이 기간을 나눌 때 씀) |

### 8-2. `aidecide.db` (writer: paperbot-aitrader)

| 표 | 내용 |
|---|---|
| `calls` | call_id, ask_id, model, effort, started_at, finished_at, http_status, `error_kind`, stop_reason, `stop_category`, input_tokens, cache_read, cache_write_5m, cache_write_1h, output_tokens(생각 포함), thinking_blocks, `cost_usd`, `cost_basis`(usage / estimate_timeout), request_id |
| `decisions` | ask_id, model, `received_at`, `valid`, answer(JSON), schema_errors, latency_ms, confidence, p_plus1R |
| `screens` | `screen_sha` → zlib 압축 본문, 토큰 수(`count_tokens`, 무료). 같은 화면은 한 번만 저장 |
| `budget` | KST 날짜·월별 사용액, 내림 단계, 콘솔 한도 메모 |
| `state` | 마지막으로 읽은 ask_id, 캐시 미리 데우기 기록, 설정 요약 |

### 8-3. `aicheck.db` (writer: paperbot-aicheck, 밤마다)

`reports`(하루 요약), `parity`(AI 계좌 재계산 불일치), `paired_final`(밤에 다시 계산한 짝 기록 = **판정이 읽는 원본**), `coins`(같은 방향·무작위 시각 동전),
`weekly_custom`(일요일 커스텀 값 찾기 그림자 기록, 판정 트레이더에는 반영하지 않음).

### 8-4. 크기와 백업

- 화면 1개 약 6.4k~9.2k 토큰(추정) ≈ 25~35KB → 압축 약 5~8KB. 질문 하루 수백~천여 개(등급·보유 점검 설정에 따라) → 하루 수 MB, 12/31까지 수백 MB(추정).
  디스크 여유 25% 아래면 화면 본문 저장을 멈추고(해시·토큰 수는 남김), 15% 아래면 새 진입 중지(v2 5-2).
- `deploy/paperbot-backup.sh`의 목록에 세 DB를 추가합니다(`VACUUM INTO`를 읽기 전용 연결로, 기존 방식 그대로). 텔레그램 외부 백업 크기 한도에 걸리면
  `screens` 없이 백업하는 사본을 따로 만듭니다.

---

## 9. 규칙 혼자 R · 코드만 R · 동전 · Opus 쌍둥이 · 그림자 질문 만드는 법

### 9-1. 규칙 혼자 R (짝 비교의 기준)

- **정의:** 같은 신호를 규칙 계좌 규칙(v4 `Settings`, `OwnerPolicy`, 하우스 청산)으로 **혼자** 돌린 결과의 R. R = 순손익 ÷ (수량 × |진입가 − 처음 손절|) (분석과 같은 정의).
- **실시간(잠정):** aibook의 `paired.py`가 신호마다 그림자 `PaperEngine` 하나를 만들어(`obsshadows.symbol_steps`처럼 그 코인 봉만) 매 분 함께 밟고, 끝나면 `rule_alone_R`을 적습니다.
  열린 그림자는 많아야 수십 개라 가볍습니다.
- **밤(확정):** aicheck가 `daily3._alone(settings, brackets, specs, daily3.make_signal(row_with_data), steps, i0)`로 다시 계산합니다.
  steps는 `daily3.load_live_bars` + `steps_on_live_bars`(규칙 봇이 실제로 밟은 봉) + 바이낸스 펀딩. 실시간 값과 1e-9까지 같아야 합니다(다르면 경고).
- **코드만 R:** 같은 신호를 **AI 계좌 설정**(AI 크기 정책, `AIEngine`, AI 행동 없음)으로 돌린 R. `exit_ref = "rule"`이면 규칙 혼자 R과 같아야 하고(강제청산·수량 반올림 차이만),
  차이는 점검 숫자로 보고합니다. AI 기여 = AI R(건너뛰면 0) − 규칙 혼자 R (보고서 15-8). **② 규칙 계좌의 손익과는 비교하지 않습니다.**

### 9-2. 동전 두 가지 (판정용, AI 비용 0)

- **같은 순간 반대 방향:** 보여 준 모든 신호에 대해 방향만 뒤집고 같은 손절 거리로 코드만 돌린 R → `paired.flip_R`(실시간) / `paired_final`(밤).
- **같은 방향·무작위 시각:** 뽑는 범위와 시드를 D0 전에 `paperbot/aitrader/coinpool.json`에 고정(해시는 LOCK_MANIFEST). 정의 자체는 판정 명세가 정합니다.
  aicheck가 밤에 그날 시각의 봉으로 계산해 `coins`에 씁니다. 실시간 동전 계좌는 쓰지 않습니다(보고서 15-8).

### 9-3. Opus 쌍둥이 (판정 밖)

- 등급 S: N10_HA_PSAR 1명. 등급 M: N10_HA_PSAR, F16_FIB382 2명.
- **계좌가 아니라 결정 그림자입니다.** 짝 Sonnet 트레이더의 질문이 생기면 aitrader가 **같은 화면 바이트·같은 시스템 문구**로 Opus를 동시에 부릅니다(모델만 다름, 캐시는 모델별로 따로 씀).
  계좌로 만들면 쌍둥이의 보유 상태가 Sonnet과 달라져 "같은 순간·같은 화면"(보고서 15-4)이 깨지기 때문입니다.
- 결과 계산(aibook): 진입 질문 → `twin_entry_R` = (Opus가 탐이면 코드만 R, 아니면 0) vs Sonnet의 같은 값. 보유 질문 → 그 순간 Sonnet 계좌의 `engine_state`를 복사해
  Opus의 행동을 적용한 그림자 → `twin_path_R` vs 실제 경로 R. 결정마다 "Opus R − Sonnet R".
- 쌍둥이 호출은 판정 진입 질문보다 우선순위가 낮고, 예산 내림 2단계에서 먼저 빠집니다(10-5).

### 9-4. 그림자 질문 (등급 S: 5명, 등급 M: 1차 10명 전부)

- 보유 중이라 막힌 신호, 동점에서 밀린 신호, 한도에 막힌 신호를 "지금 비어 있다면"으로 AI에게 묻고 기록만 합니다. **절대 거래하지 않습니다.**
- 결과 = (탐이면 코드만 R, 아니면 0). "AI가 신호를 가려내는가"(보고서 15-12: 건너뛴 것 − 탄 것 ≥ +0.15R, 300결정 이상)를 빨리 재는 용도입니다.
- 화면 형식은 진입 질문과 바이트 형식이 같아야 합니다(AI가 그림자인지 알면 판단이 달라질 수 있음). 화면 명세가 정합니다.
- 등급 S의 5명 제안: N10_HA_PSAR, F16_FIB382, F9_FVG, N18_VWMA_MACD, F6_VWAP_CROSS (쌍둥이 기준 + 신호 공급이 큰 매매법). 비용 명세와 두 분이 확정.

---

## 10. Claude 호출 (`paperbot-aitrader`)

### 10-1. 클라이언트 (`paperbot/aitrader/claude.py`)

- 표준 라이브러리 `urllib`만 씁니다(venv에 새 패키지를 넣지 않음: `runinfo`의 `packages` 해시가 바뀌지 않게). `agents/debate.py`의 `call_api`·`classify`·`cost_of`·`redact`를
  **복사해** 고칩니다(import하지 않음: 토론방 코드가 바뀌어도 AI 트레이더가 바뀌지 않게).
- **재시도 0회.** 공식 SDK 기본값은 2회 재시도라 한 호출이 3번 청구될 수 있습니다(검증된 비용 사실). 429·5xx·네트워크 오류 = 그 질문 무응답.
- **시간 제한:** 마감 − 지금 − 0.5초. 늦은 답도 청구될 수 있으므로, 시간 초과 호출은 `cost_basis = estimate_timeout`(입력 전부 + `max_tokens` 전부를 출력으로 친 보수적 값)으로 장부에 넣습니다.
- **모델:** 트레이더 `claude-sonnet-5-5`, 쌍둥이 `claude-opus-5-5`. 값은 aitrader.env에 고정(D0 잠금).
- **생각 깊이:** 두 모델 모두 생각을 끌 수 없습니다(Sonnet 5.5는 `{"type":"disabled"}`가 400, 끄려면 `between_tools`; Opus 5.5는 항상 켜짐).
  기본값이 Sonnet `high`, Opus `medium`이라 **호출 종류마다 `output_config.effort`를 명시**하고 `max_tokens`를 정합니다(값은 0차 재생에서 확정, 비용 명세).
- **답 형식:** 구조화 출력(`output_config.format`, JSON 스키마) 기본. 강제 도구 호출(`tool_choice` any/tool)은 두 모델에서 400이라 쓰지 않습니다.
  코드가 스키마를 다시 검사합니다(열거값, 숫자 범위, 길이). 이유 문장은 길이를 잘라 저장하고 대시보드에서 이스케이프해 보여 줍니다.
- **거절(`stop_reason = "refusal"`)**: 무응답, `stop_details.category` 기록. `fallbacks`는 쓰지 않습니다(4-3).
- **키:** `ANTHROPIC_API_KEY`는 `/etc/paperbot/aitrader.env`에만. 로그·DB·예외 문구에는 절대 남기지 않습니다(`redact`). 상태 명령은 "설정됨/비어 있음"만 출력.

### 10-2. 캐시 (사실 확인한 것)

- 캐시는 **모델별**입니다(Opus 쌍둥이는 자기 쓰기를 따로 냄). 최소 캐시 길이는 Sonnet 5.5·Opus 5.5 모두 512토큰.
- 쓰기 1.25배(5분) / 2배(1시간), 읽기 Sonnet $0.20/MTok, Opus 5.5도 $0.20/MTok(입력 단가의 0.05배). **가격은 콘솔에서 다시 확인**하고 env로 덮어쓸 수 있게 합니다.
- 구조: 중단점 1 = 모든 트레이더 공통 지시문 끝(트레이더끼리 같은 캐시를 공유), 중단점 2 = 그 트레이더 매매법 카드 끝, 그 뒤가 매번 바뀌는 화면.
  `tools`·시스템 문구·`thinking`·`effort`가 바이트까지 같아야 캐시가 맞습니다(정렬된 JSON, 시각 같은 값은 화면 쪽에만).
- **봉 마감 동시 호출 문제:** 15분 간격은 5분 수명보다 길어 그대로 두면 캐시가 매번 식습니다(30명 기준 월 약 +$280, 추정). 대책 후보:
  (a) 공통·카드 부분 1시간 수명, (b) 경계 1분 전 미리 데우기(`max_tokens: 0`), (c) 경계 안에서 호출을 나눠 보냄.
  주의: `max_tokens: 0` 미리 데우기는 `output_config.format`과 함께 쓰면 거부됩니다. 형식 지정이 캐시 앞부분에 들어가는지에 따라 미리 데우기가 맞지 않을 수 있어,
  **0차 재생에서 첫 실제 호출의 `cache_read_input_tokens`로 확인**하고 (a)/(b)/(c) 중 고릅니다.
- 화면 토큰 수는 먼저 무료 `count_tokens`로 잽니다(0차 재생 `--dry`).

### 10-3. 줄 세우기와 동시 호출

- 작업자 스레드 풀: 등급 S 12개, 등급 M 24개(추정, 0차에서 조정). 우선순위: 판정 진입 > 판정 보유 점검 > 쌍둥이 > 그림자 > 코치.
- 마감 안에 시작하지 못할 질문(풀이 꽉 참)은 보내지 않고 무응답(`queue`)으로 기록합니다(보내 놓고 늦어 돈만 나가는 것보다 낫다).
- API 속도 한도(분당 요청·입력 토큰)는 조직 등급에 달려 있습니다. 경계마다 10~26개 호출이 몰리므로 0차·판단만 운행에서 429 비율을 잽니다.

### 10-4. 예산 장부 (두 등급 공통 코드, 값만 다름)

- 사용액 = 모든 호출의 `cost_usd`(+시간 초과 추정치) + 코치·분석가 호출. 서버비는 `AI_FIXED_USD_MONTH`로 따로 빼고 남은 것을 API 상한으로 씁니다
  (같은 서버면 0, 별도 서버면 약 $40, 추정).
- **한도 순서:** ① 월 사용액 + 진행 중 호출 최악값 ≥ 상한의 95% → 모든 호출 중지(새 진입 없음, 코드 관리는 계속) ② 하루 사용액 > 목표의 1.25배 ÷ 그 달 일수 →
  다음 내림 단계(하루 최대 1단계) ③ 3일 연속 목표의 90% 아래 → 한 단계 되돌림(D0 설정 위로는 못 감).
- **진짜 마지막 상한은 Anthropic 콘솔의 지출 한도**입니다. 콘솔 한도 = 등급 상한으로 설정(토론방 `debate.env.example`과 같은 안내).

| | 등급 S "월 40만원" | 등급 M "월 60~70만원" |
|---|---|---|
| 목표 평균 (추정) | $280 ≈ 40만원 | $400~440 ≈ 57~63만원 |
| **상한 (코드 95%에서 멈춤, 콘솔 한도)** | **$300 ≈ 42.9만원** | **$490 ≈ 70만원** |
| 하루 내림 기준 (목표 × 1.25 ÷ 30) | 약 $11.7 ≈ 1.7만원 | 약 $17.5 ≈ 2.5만원 |
| 작업자 풀 | 12 | 24 |

### 10-5. 내림 사다리 (자동, 순서는 D0에 잠금) / 올림 사다리 (두 분만)

| 단계 | 내림 (예산이 빠를 때) | 판정에 주는 영향 |
|---|---|---|
| L1 | 그림자 질문 중지 | 없음 (기록용) |
| L2 | 쌍둥이 호출 중지 | 없음 (판정 밖) |
| L3 | 보유 점검을 +1R·반대 신호·발표·1h 이상 봉 마감만으로 | 판정 트레이더의 보유 판단 기회가 줄어듦 → `ai_events`에 기록, 판정은 단계별로 나눠 봄 |
| L4 | 탐색(`ai_x`) 트레이더 호출 중지 | 없음 |
| L5 | 판정 트레이더 보유 점검 중지(코드 관리만) | 큼 → CRITICAL |
| L6 | 모든 호출 중지(진입 = 무응답 건너뜀) | 그 기간은 AI 결정 없음 |

- 올림: 등급 S → M은 두 분이 aitrader.env의 `AI_TIER=M`과 콘솔 한도를 바꾸고 재시작(10/31 전에만, 2차는 M에서만). 판정 진입 질문의 방식(지시문·화면·생각 깊이)은 어떤 사다리로도 바뀌지 않습니다.

---

## 11. 재시작 · 규칙 봇 초기화 · 밤 점검과의 관계

| 일 | 무엇이 일어나나 |
|---|---|
| **aibook 재시작** | `AccountBook.load(make_of=...)`로 AI 계좌 상태를 되살리고(`state 'accounts'`, 매 분 저장), `last_ts + 1분`부터 `live_bars`로 따라잡음. 처리 중이던 질문은 기록된 시각(`received_at ≤ deadline`)으로 그대로 결정 → 결과가 끊김 없이 같음. 따라잡는 동안 새 신호가 60초 넘게 지났으면 LATE |
| **aitrader 재시작** | 진행 중이던 호출은 잃음 → 무응답(`service_down`), 비용은 추정으로 장부에. 새 질문부터 정상 |
| **규칙 봇 재시작** | `paper3.db runs`에 새 행. aibook이 해시(`trading_code`, `ds_code`, `reel_code`, `settings`, `brackets`, `signal_code`)를 시작 때 값과 비교. 같으면 계속(재시작 동안의 LATE 신호는 질문 없음). **거래 해시가 바뀌면** AI 새 진입 중지(`suspended: rule_code_changed`) + CRITICAL. 두 분이 `aitrader.json`의 `accept_rule_run`에 새 run id를 넣으면 재개(그 사건은 `ai_events`) |
| **규칙 봇 초기화** (`paperbot-reset.sh`) | 새 `paper3.db`(다른 inode·다른 run 시작 시각) 감지 → `suspended: source_changed`. AI 계좌와 열린 포지션은 aibook.db에 남고, 새 `live_bars`가 오면 코드 관리는 계속. `accept_source`로 재개. `paperbot-reset.sh`에 "AI 서비스가 켜져 있으면 확인 문구를 다시 입력" 가드를 넣습니다(PLAN 2-5) |
| `live_bars` 빠짐 | 규칙 봇 체결 비용 기록(`Runner3._fill_costs`)이 실패하면 그 분 봉이 없음. aibook은 2분 기다린 뒤 바이낸스 공개 1분봉·마크봉으로 채우고 `bar_source = rest`로 표시(규칙 봇이 밟은 봉과 다를 수 있음, aicheck가 보고) |
| 펀딩 | 00·08·16 UTC 정산 분은 바이낸스 공개 `fundingRate`(`BinanceREST.funding_rates`)를 받을 때까지 그 분을 기다림(daily3 `fetch_steps`와 같은 값) |
| 구간표·거래 규격 | 규칙 봇은 읽기 전용 키로 구간표를 받음(`live.load_brackets`). AI 장부는 키가 없으므로 설치 때 한 번 `sudo -u paperbot ... -m paperbot.aitrader.brackets dump`로 `/var/lib/paperbot/aibook/brackets.json`을 만들고(비밀 없음), 시작 때 `runinfo.brackets_hash`가 규칙 봇 runs 행의 `brackets`와 같은지 확인(다르면 시작 거부). 거래 규격은 공개 `exchangeInfo` |
| **daily3 (00:20 UTC)** | 바뀌지 않음. AI 계좌는 `paper3.db`에 없어 재계산 "331/331"이 그대로. AI 쪽 재계산은 aicheck |
| dscheck (00:30), checkpoint (11/04), 에이전트, 백업 | 바뀌지 않음 (백업 목록에 AI DB 추가만) |
| **aicheck (00:40 UTC)** | AI 계좌의 전날을 aibook.db `day:<날짜>` 스냅숏(`AccountBook.step`이 00:00 UTC에 저장)부터 `resolutions`·`ai_actions`로 다시 돌려 거래가 같은지(`daily3.compare` 재사용), 규칙 혼자 R 재계산, 동전, 기록 완전성(보여 준 신호마다 짝 행 1개), 비용·무응답·형식 오류 비율 → AI 전용 텔레그램 한 통 |
| 서버 재부팅 | 세 서비스 모두 `Restart=` 로 다시 뜸. aibook은 paper3.db를, aitrader는 aibook.db를 기다렸다가 시작 |

---

## 12. 바꾸지 않는 파일 · 바꾸는 배포 파일 · 새 파일

### 12-1. 절대 바꾸지 않는 파일 (바뀌면 규칙 봇의 30일 기간이 다시 셈, `docs/paper-v4-rules.md` 8절)

- `runinfo.TRADING_FILES`: `paperbot/engine.py`, `ladder.py`, `margin.py`, `sizing.py`, `config.py`, `models.py`, `accounts.py`, `sigservice.py`, `aggregate.py`, `feed.py`,
  `live3.py`, `recorder.py`, `policy.py`, `levrule.py`, `quality_edges.json`, `entry_marks.py`, `binance.py`, `p_best_cells.json`, `sweepsig.py`,
  `research/paper_rules/out/summary.json`, `research/entry_study/DEFS_BC.sha256`, `research/entry_study/strength_defs/*`
- `DS_FILES`, `REEL_FILES`(딥시크·릴스 신호 코드와 고정 파일), `third_party/sweep`(`PREREG.sha256`), `research/deepseek200/FORWARD_PREREG.md`, `paperbot/shadow200.py`
- `EXTRA_FILES`(`extras.py`, `newlab_live.py`, `agents/newlab_signals.py`), `SHARED_SIGNAL_FILES`(`recorder.py`, `context.py`), `EXTRA_GATE_FILES`
- `RULES_FILES`(규칙·판정 문서와 sha256 파일)
- 해시에는 없지만 이번에 바꿀 필요가 없어 그대로 두는 것: `daily3.py`, `checkpoint.py`, `dscheck.py`, `runinfo.py`, `risk.py`, `executor.py`, `launchcheck.py`, `agents/debate.py`

### 12-2. 바꾸는 배포·운영 파일 (어느 거래 해시에도 없음, 규칙 봇 재시작 없이 배포)

| 파일 | 바꿀 내용 |
|---|---|
| `deploy/install.sh` | (다음 전체 설치 때를 위해) `install-ai.sh`와 같은 사용자·폴더·템플릿·유닛 설치를 포함하고, 코드 교체 때 멈추는 목록 `UNITS`에 AI 두 서비스 추가. **처음 설치에는 쓰지 않음**: install.sh는 코드 교체 동안 `paperbot-live3`를 멈추기 때문 |
| `deploy/paperbot-backup.sh` | 백업 목록에 aibook.db, aidecide.db, aicheck.db |
| `deploy/paperbot-reset.sh` | AI 서비스가 켜져 있으면 경고 + 확인 문구 재입력 |
| `deploy/update-dash.sh` | 비교 허용 목록에 `paperbot/aitrader/`, AI 배포 파일 추가(대시보드만 갱신할 때 거부되지 않게) |
| `paperbot/dash/` | AI 탭(세 DB 읽기 전용). `paperbot/aitrader`를 import하지 않고 표만 읽음 |

### 12-3. 새 파일

| 파일 | 역할 |
|---|---|
| `paperbot/aitrader/__init__.py` | — |
| `source.py` | `paper3.db` 읽기 전용 리더(신호 id 이후, `live_bars` ts 이후, heartbeat, runs 해시·실행 묶임 확인), 펀딩 공개 요청 |
| `book.py` | `paperbot-aibook` 본체: 폴링, 질문 생성, 장벽, 결과 해석, `AccountBook` step, 깨움, LATE |
| `intake.py` | 범위·4h 20배 검사·동점·보유 중 규칙 (5장) |
| `engine_ai.py` | `AIEngine(PaperEngine)`, 행동 적용, `exit_ref` 잠금, Guarded 방식 |
| `sizing_ai.py` | `policy_for` (한 경로), `FixedRiskMaxLevPolicy`, 4h 검사 함수 |
| `caps.py` | 한도·손실 제한 (7장) |
| `paired.py` | 규칙 혼자·코드만·방향 뒤집기·늦은 체결·반사실·쌍둥이 결과 |
| `decide.py` | `paperbot-aitrader` 본체: 질문 폴링, 풀, 마감, 답 기록 |
| `claude.py` | Messages API 클라이언트(재시도 0, 시간 제한, 비용) |
| `screen.py` | 화면 만들기(as-of 규칙). 내용은 화면 명세가 정함. 봉은 `market.db`(5분봉 역사) + `live_bars`(이후)를 `aggregate.Aggregator`로 묶음, 미결제약정·롱숏은 `flow.db` + 5분마다 공개 요청 1회(속도 제한), 강제청산은 `liq.db` |
| `budget.py` | 장부, 한도, 내림 사다리 |
| `rest.py` | AI 쪽 바이낸스 공개 요청 제한기(분당 무게 60 평균, `X-MBX-USED-WEIGHT-1M` 1,200 넘으면 멈춤, 418이면 금지 시간 동안 전부 멈춤) |
| `check.py` | `paperbot-aicheck` (11장), 11/16 가망 없음 판단, 2차 운영 관문 보고 |
| `gates.py` | 10/31 2차 운영 관문: 호출당 비용, 무응답 < 5%, 형식 오류 ≤ 1%, 짝 기록 완전. **R·짝 결과 표를 읽지 않음** |
| `replay.py` | 0차 재생(시뮬레이션 시계, `--dry`는 `count_tokens`만), 판단만 운행 모드 |
| `lock.py`, `LOCK_MANIFEST.json` | 지시문·화면 형식·roster·coinpool·판정 규칙·AI 코드 해시. 시작 때 확인, D0 뒤 바뀌면 CRITICAL + 그 트레이더 기간 표시 |
| `roster.json`, `coinpool.json`, `prompts/` | 잠금 자료 (내용은 다른 명세) |
| `brackets.py` | 구간표 내보내기(설치 때 1회) |
| `deploy/paperbot-aibook.service`, `paperbot-aitrader.service`, `paperbot-aicheck.service`, `paperbot-aicheck.timer` | 14장 |
| `deploy/aitrader.env.example`, `deploy/aibook.env.example`, `deploy/aitrader.example.json` | 14장 |
| `deploy/install-ai.sh` | 처음 1회: 사용자 `paperbot-ai`·`paperbot-aibook`(주 그룹 자기, 보조 그룹 paperbot), 폴더 `/var/lib/paperbot/ai`·`/var/lib/paperbot/aibook`(setgid 2750), env 템플릿(root:그룹 640, 키는 비움, 기존 파일은 덮어쓰지 않고 값 출력 안 함), 유닛 설치(켜지 않음). `/opt/crypto-bot-research`의 기존 파일과 `paperbot-live3`는 건드리지 않음 |
| `deploy/update-ai.sh` | 코드 배포(14-3). live3를 멈추지 않음 |
| `docs/aibot/AI_RUNBOOK_KO.md` | 두 분용 켜기·끄기·멈춤 풀기 안내 |
| `tests/test_ai_*.py`, `tests/ai_world.py` | 15장 |

---

## 13. 규칙 봇 결과가 그대로라는 보장

1. **코드:** 12-1의 파일이 하나도 바뀌지 않습니다. 시험 `test_ai_hashes_unchanged`가 `runinfo.code_hashes()`의 모든 키와 `third_party/sweep` 검사를 기준 커밋과 비교합니다.
2. **경로:** 규칙 봇이 불러오는 모듈 중 `paperbot.aitrader`가 없습니다(`tests/test_runinfo.py`의 import 검사와 같은 방법으로 확인). 그래서 `runinfo`에 새 묶음을 넣을 필요도 없습니다.
3. **쓰기:** AI 프로세스는 다른 사용자이고 systemd가 `/var/lib/paperbot`을 읽기 전용으로, 자기 폴더만 쓰기 가능으로 묶습니다. 코드도 `mode=ro`로만 엽니다. OS가 막으므로 실수로도 `paper3.db`를 못 씁니다.
4. **재시작 없음:** AI 설치·수정은 `deploy/update-ai.sh`로 합니다(14-3). 이 스크립트는 `paperbot-live3`를 멈추지도 재시작하지도 않고, 해시된 파일이 설치본과 다르면 거부합니다.
   그래서 AI 쪽은 언제나 규칙 봇과 **같은 바이트의 엔진**으로 돕니다(시작 때 `code_hashes`를 paper3.db 마지막 runs 행과 한 번 더 비교).
5. **자원:** AI 유닛은 `Nice=10`, `CPUWeight=20`, `MemoryHigh`/`MemoryMax`, 경계 작업은 규칙 봇 경계 커밋 뒤에만(3-2). 읽기는 짧은 트랜잭션(WAL 체크포인트를 막지 않음).
6. **바이낸스 IP:** 같은 서버 IP를 쓰므로 AI 쪽 요청은 `rest.py` 제한기를 거칩니다. 봉은 요청하지 않고 DB에서 읽습니다. 418 금지가 나면 AI 요청만 멈춥니다(규칙 봇이 금지당하지 않게).
7. **증명 시험:** `tests/extras_harness.py`의 합성 세계(26시간, 코인 7개, 거래 정지 1시간)를 AI 장부·가짜 aitrader가 함께 도는 상태로 돌려, 거래·결과·자산·알림·엔진 상태·하루 스냅숏·
   신호 기록·`live_bars`의 해시가 `tests/data/extras_parity_golden.json`과 같음을 확인. AI 쪽 고장(답 지연, 프로세스 강제 종료, 예외)을 넣어도 같아야 통과.
8. **운행 중 확인:** AI 운행 기간에도 daily3 09:20 텍스트의 "재계산 일치 331/331"이 그대로여야 합니다(0차 판단만 운행 통과 기준에 포함).

---

## 14. 설치와 배포

### 14-1. 사용자·폴더·비밀 파일

| 무엇 | 값 |
|---|---|
| 사용자 | `paperbot-ai` (aitrader, 키 보유), `paperbot-aibook` (aibook·aicheck, 키 없음). 둘 다 보조 그룹 `paperbot` (DB 읽기). `paperbot`·root와 다른 uid여야 함 (install.sh가 확인, 실행기·토론방과 같은 방식) |
| 폴더 | `/var/lib/paperbot/ai` (paperbot-ai:paperbot 2750), `/var/lib/paperbot/aibook` (paperbot-aibook:paperbot 2750). 파일은 640, 그룹 paperbot이 읽음 (대시보드) |
| 비밀 | `/etc/paperbot/aitrader.env` (root:paperbot-ai 640): `ANTHROPIC_API_KEY`, `AI_TIER`, `AI_MODEL_TRADER`, `AI_MODEL_TWIN`, `AI_MONTHLY_USD_CAP`, `AI_TARGET_USD`, `AI_FIXED_USD_MONTH`, 가격 덮어쓰기, `TELEGRAM_BOT_TOKEN_AI`, `TELEGRAM_CHAT_AI`. `/etc/paperbot/aibook.env` (root:paperbot-aibook 640): AI 텔레그램 두 줄만 |
| 비밀 아닌 설정 | `/etc/paperbot/aitrader.json` (root, 644): `mode`(replay / decide_only / live), `pause_entries`, `accept_source`, `accept_rule_run`, `wave2_enabled`. 잠금 값은 여기 없고 저장소 잠금 파일에 있음 |
| 키 넣는 법 | **`sudoedit /etc/paperbot/aitrader.env`** 안에서만 입력. 채팅·셸 명령줄(기록에 남음)·파일 출력 금지. install.sh는 기존 파일을 덮어쓰지 않고 값을 출력하지 않음. 콘솔에서 이 서비스 전용 작업 공간과 키, 지출 한도 = 등급 상한 |

### 14-2. 유닛 (토론방 `paperbot-debate.service`와 같은 격리)

`paperbot-aitrader.service` 요점:

```ini
[Service]
Type=notify                       # 루프마다 WATCHDOG=1 (paperbot.health.sd_notify)
User=paperbot-ai
Group=paperbot
UMask=0027
WorkingDirectory=/opt/crypto-bot-research
EnvironmentFile=/etc/paperbot/aitrader.env
ExecStart=/opt/paperbot/venv/bin/python -m paperbot.aitrader.decide run --book /var/lib/paperbot/aibook/aibook.db --db /var/lib/paperbot/ai/aidecide.db
Restart=on-failure
RestartPreventExitStatus=2        # 설정 값 오류: 고치고 재시작
WatchdogSec=300
KillMode=mixed
TimeoutStopSec=30                 # 진행 중 호출(≤20초)을 마치고 끝냄
Nice=10
CPUWeight=20
MemoryHigh=768M
MemoryMax=1G
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/var/lib/paperbot/ai
ReadOnlyPaths=/var/lib/paperbot
InaccessiblePaths=-/etc/paperbot -/var/lib/paperbot/exec -/var/backups/paperbot -/var/lib/paperbot/.claude -/var/lib/paperbot/.claude.json -/var/lib/paperbot/.local -/var/lib/paperbot/lab -/var/lib/paperbot/inbox.db
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
```

- `paperbot-aibook.service`: 같은 틀, `User=paperbot-aibook`, `EnvironmentFile=/etc/paperbot/aibook.env`, `ReadWritePaths=/var/lib/paperbot/aibook`,
  `ExecStart=... -m paperbot.aitrader.book run --paper3 /var/lib/paperbot/paper3.db --db /var/lib/paperbot/aibook/aibook.db --decide /var/lib/paperbot/ai/aidecide.db`,
  `Restart=always`, `RestartSec=15`.
- `paperbot-aicheck.service` (oneshot, `OnFailure=paperbot-failed@%n.service`) + `.timer` `OnCalendar=*-*-* 00:40:00 UTC`, `Persistent=true`.
- **install.sh는 설치만 하고 켜지 않습니다**(토론방과 같음: 돈이 드는 서비스).

### 14-3. 배포 (`deploy/update-ai.sh`, `update-dash.sh` 방식)

1. 커밋 안 된 변경이 있으면 거부.
2. 설치본(`/opt/crypto-bot-research`)과 파일별 비교: `paperbot/aitrader/`, `paperbot/dash/`, `deploy/` 중 AI 파일, `docs/`, `tests/` 밖이 하나라도 다르면 거부("전체 설치 절차 필요").
3. 그 폴더들만 복사·교체(이전 것은 `.old`로 보관), `AI_VERSION.json` 기록(규칙 봇의 `VERSION.json`은 건드리지 않음).
4. AI 서비스만 재시작(켜져 있을 때만), 대시보드가 바뀌었으면 대시보드만. **`paperbot-live3`는 절대 멈추지 않음.** 실패하면 이전 것으로 되돌림.

### 14-4. 켜는 순서 (두 분 "좋아" 뒤, 보고서 15-11 일정)

| 날짜 | 단계 | 명령 (서버, 몇 줄) | 통과 기준 |
|---|---|---|---|
| 만들기 끝 (~10/13) | 시험 전부 통과, 리뷰 | — | 15장 |
| 10/14 | 설치(켜지 않음), 키 입력 | `sudo bash deploy/install-ai.sh` → `sudo bash deploy/update-ai.sh` → `sudoedit /etc/paperbot/aitrader.env` (키는 편집기 안에서만) → 구간표 내보내기 1회 | 설치 점검 명령 통과(사용자·권한·키 있음·값 미출력, `paperbot-live3` 가동 시간이 끊기지 않음) |
| 10/14~15 | **0차 재생**: 저장된 v4 신호 일부로 1차 10명 | `... -m paperbot.aitrader.replay --dry` (무료 토큰 세기) → `--budget-usd 10` 실호출 | 호출당 비용·생각 토큰·지연 p50/p95·형식 오류·거절·캐시 적중 기록 → 월 비용 다시 계산, 등급별 인원·점검 빈도 확정 |
| 10/15~16 | **24시간 판단만 운행**: `mode=decide_only` (질문·답은 실제, AI 계좌 반영 없음) | `sudo systemctl enable --now paperbot-aibook paperbot-aitrader` | 무응답 < 5%, 형식 오류 ≤ 1%, 짝 기록 100%, aibook 지연 p99 < 5초, 비용이 등급 목표 안, daily3 331/331 유지 |
| 10/17 21:00 KST | D0: `mode=live` | `sudoedit /etc/paperbot/aitrader.json` 후 재시작, `systemctl enable --now paperbot-aicheck.timer` | — |
| 10/24~27 | 2차 운영 관문 보고 (등급 M만) | `... -m paperbot.aitrader.gates wave2` | 운영 기준만 |
| 10/31 21:00 KST | 2차 (M, 관문 통과 + 두 분 `wave2_enabled`) | 재시작 | 늦어도 11/01 |

---

## 15. 시험 목록과 통과 기준

| # | 시험 | 통과 기준 |
|---|---|---|
| 1 | `test_ai_hashes_unchanged` | `runinfo.code_hashes()` 모든 키, `RULES_FILES`, `third_party/sweep` 검사가 기준 커밋과 같음 |
| 2 | `test_ai_not_on_runner_path` | `paperbot.live3` import와 `start_extras` 뒤 `sys.modules`에 `paperbot.aitrader` 없음 |
| 3 | `test_rulebot_bit_identical_with_ai` | extras 합성 세계에서 AI 장부·가짜 aitrader 동시 운행(고장 주입 포함) 때 규칙 봇의 모든 해시가 골든 파일과 같음 |
| 4 | `test_ai_paper3_readonly` | AI 코드에서 paper3.db를 여는 곳은 모두 `mode=ro`(AST 검사), 운행 전후 paper3.db 내용 해시 같음, 쓰기 시도는 권한 오류 |
| 5 | `test_daily3_checkpoint_unaffected` | AI DB가 있든 없든 `daily3.run_day` 보고서와 `checkpoint` 스냅숏이 같음 |
| 6 | `test_intake_scope_and_4h` | 범위 밖 봉은 질문 없음, 4h는 "손절 너머 1 ATR이 20배 강제청산가 안쪽"일 때만(BTC 통과·DOGE 실패 예 포함) |
| 7 | `test_tie_rule` | 같은 경계 후보에서 긴 봉 → 손절 폭 → 순번으로 정확히 1개 질문, 나머지 `tie` 기록 |
| 8 | `test_holding_rule` | 보유 중 새 신호는 반대 방향(같은 코인)·긴 봉 자기 신호만 보유 점검, 갈아타기 답은 거부 |
| 9 | `test_deadline_barrier` | 가짜 시계로 19.9초 답 = 채택, 20.1초 = 무응답(늦음, 비용 기록), 마감 전에는 그 분을 밟지 않음 |
| 10 | `test_fill_identical_to_rule` | AI 탐 진입의 체결가·분·수수료·미끄러짐이 같은 신호 규칙 계좌 체결과 같음(1e-12) |
| 11 | `test_late_signals` | 60초 넘게 늦게 본 신호와 재시작 따라잡기 중 신호는 질문 없음, `late`로 짝 기록 |
| 12 | `test_one_sizing_path` | AI 쪽에서 정책 객체를 만드는 곳은 `sizing_ai.policy_for` 하나(AST), `recommended_v1` 결과가 `policy.RecommendedPolicy`와 같음, `fixed_risk_maxlev_v1`은 50/40/30/20 중 맞는 가장 높은 것·최저 3배·1 ATR 여유 예제 표대로 |
| 13 | `test_exit_ref_rule` | 행동 없는 AI 거래의 청산 시각·가격이 `daily3._alone` 규칙 혼자 거래와 같음(차이는 강제청산·수량 반올림 사례만, 사유 표시) |
| 14 | `test_actions` | 본전은 +1R 뒤에만, 손절은 유리한 쪽으로만·0.3 ATR, 즉시 청산은 다음 분 시가, `stop_initial` 불변, 닫힌 포지션 행동은 "대상 없음", 반사실 R 재현 |
| 15 | `test_no_answer_paths` | 시간 초과·429·5xx·네트워크·거절·형식 오류·예산·서비스 꺼짐 각각: 진입 건너뜀(사유), 보유 그대로 |
| 16 | `test_caps` | 7장 표의 모든 한도, 09:00 KST 초기화, 동시 탐의 정해진 순서, 재계산과 같은 결과 |
| 17 | `test_paired_complete` | 보여 준 모든 신호(탐·건너뜀·무응답·동점·막힘·한도·LATE)에 짝 행 정확히 1개, 규칙 혼자 R·방향 뒤집기 R 있음(또는 미해결 표시) |
| 18 | `test_rule_alone_parity` | 실시간 `rule_alone_R` = aicheck의 `daily3._alone` 재계산 (1e-9) |
| 19 | `test_aicheck_replay_parity` | 하루 스냅숏 + `resolutions`·`ai_actions`로 AI 계좌 거래를 정확히 재현, 일부러 바꾼 값은 CRITICAL로 잡음 |
| 20 | `test_restart_aibook` | 6곳(질문 쓰기 뒤, 답 도착 뒤 해석 전, step 중간, 체결 뒤, 하루 스냅숏 중, 한도 갱신 중) 강제 종료 후 재시작 결과가 끊김 없는 운행과 같음 |
| 21 | `test_rulebot_restart_reset` | 같은 해시 재시작 = 계속, 거래 해시 변경 = 새 진입 중지 + CRITICAL, paper3.db 교체 = `source_changed` 중지, `accept_*`로 재개 |
| 22 | `test_twin_same_screen` | 쌍둥이 호출의 시스템 문구·화면 바이트 해시가 Sonnet 호출과 같고 모델만 다름, 비용 행 따로, 쌍둥이 결과 재현 |
| 23 | `test_api_client` | 재시도 0, 시간 제한 = 마감 기준, usage → 비용(쓰기 1.25/2배, 읽기 단가, env 덮어쓰기), 키가 로그·DB·예외에 없음 |
| 24 | `test_budget_ladder` | 가상 지출 경로에서 내림 단계가 정한 순서로, 95%에서 호출 중지, 판정 진입이 마지막, 모든 단계 `ai_events`에 기록, KST 월 초기화 |
| 25 | `test_wave2_gate_blind` | `gates.py`가 R·짝 결과 표를 읽지 않음(SQL·import 검사), 등급 S는 2차 무시 |
| 26 | `test_replay_dry` | `--dry`는 `count_tokens`만 부르고 Messages 호출 0 |
| 27 | `test_units_and_install` | 유닛 사용자·경로 제한, env 파일 640과 주인, `install-ai.sh`·`update-ai.sh`는 `paperbot-live3`를 멈추지 않음(가짜 systemctl 기록으로 확인), `update-ai.sh`는 해시 파일이 다르면 거부, 어느 스크립트도 AI 서비스를 켜지 않음 |
| 28 | `test_no_secrets` | 저장소 파일에 키 모양 문자열 없음, 상태 명령은 "설정됨/비어 있음"만 |
| 29 | `test_rest_limiter` | AI 쪽 바이낸스 요청 무게가 제한 안, 418·429에서 멈춤 |

---

## 16. 두 등급의 차이 (통합 관점: 같은 코드, 설정만 다름)

| | 등급 S "월 40만원" (목표 ≈ $280, 상한 $300 ≈ 42.9만원) | 등급 M "월 60~70만원" (목표 ≈ $400~440, 상한 $490 ≈ 70만원) |
|---|---|---|
| 판정 트레이더 | 1차 10명 (K = 10) | 1차 10명 + 10/31에 최대 8명 (운영 기준만, K = 16~18) |
| Opus 쌍둥이 | 1명 (N10_HA_PSAR) | 2명 (N10_HA_PSAR, F16_FIB382) |
| 그림자 질문 | 5명 | 1차 10명 전부 |
| 보유 점검 (`hold_wakes`, 제안) | +1R, 반대 신호, 긴 봉 신호, 발표, 봉 마감은 max(들고 있는 봉, 30분) | +1R, 반대 신호, 긴 봉 신호, 발표, 들고 있는 봉 마감(15분 포함) |
| 작업자 풀 | 12 | 24 |
| 코치·분석가, 서버비 | 상한 안 | 상한 안 |
| 올림 | 10/31 전 두 분이 M으로 바꿀 때만 | — |
| 내림 사다리 | 10-5 (같은 순서) | 10-5 (같은 순서) |

공통(등급과 무관): 짝 기록, 코인 6개, 한도, 판정 방식, 커스텀 값 동결, 안전 장치, 규칙 봇 보호. **모든 비용 숫자는 추정이며 0차 재생에서 다시 잽니다.**

---

## 17. 위험

1. **바이낸스 IP 공유:** AI 쪽 요청이 많으면 같은 IP의 규칙 봇이 429/418을 맞을 수 있음 → 봉은 DB에서만, 공개 요청은 제한기, 418이면 AI만 멈춤.
2. **`live_bars` 빠짐:** 규칙 봇의 체결 비용 기록이 실패한 분은 AI가 바이낸스 확정 봉을 씀 → 그 분은 규칙 계좌와 다른 봉일 수 있음(aicheck 보고).
3. **지연:** 신호가 보이는 시각이 경계 뒤 26초(중앙값)~46초(최대). 답까지 더하면 최대 약 66초. 장부는 기다리면 되지만, 실제 돈이면 체결이 `ref_price`보다 늦음 → 늦은 체결 그림자로 따로 재야 함.
4. **20초 안 답:** Sonnet 기본 생각 깊이(`high`)와 7~9천 토큰 화면이면 p95가 20초를 넘을 수 있음 → 생각 깊이·`max_tokens`·화면 크기를 0차에서 맞춤.
5. **경계 몰림:** 10~26개 동시 호출의 속도 한도(429)와 캐시 식음(+약 $280/월, 30명 기준 추정). 미리 데우기는 구조화 출력과 `max_tokens: 0`이 함께 안 되는 제약이 있음.
6. **만들 양:** 새 파일 20여 개와 시험 29개. 10/17 시작은 만들기가 10/13까지 끝나야 가능(보고서 16-11). 하루씩 미루는 쪽 권장.
7. **판정 중 설정 변화:** 내림 사다리 L3·L5는 판정 트레이더의 판단 기회를 바꿈 → 단계별로 나눠 보고해야 함.
8. **디스크:** 화면 저장이 수백 MB(추정). 디스크 가드가 있지만 서버 여유 확인 필요.
9. **두 프로세스 시계:** 같은 서버 시계(chrony)라 문제는 작지만, 마감 판단은 aitrader의 `received_at` 기록에 기댐 → 시계 차이 검사(시작 때) 포함.
10. **가상 거래소가 후함:** 규칙 봇 엔진의 손절 체결(손절가 − 0.02% 미끄러짐)은 v2가 계획한 호가 기반 체결보다 후함(보고서 17-1). AI 결과도 같은 정도로 후함.
11. **11/04 판정 화면:** AI 계좌가 paper3.db에 없어 규칙 봇의 09:20 텔레그램·체크포인트에 안 나옴 → AI 전용 요약을 따로 봐야 함(의도한 분리).

---

## 18. 검증된 결과와 부딪히는 점

1. **크기 규칙:** `RecommendedPolicy`(다)를 고르면 실제 레버리지는 2~5배라 검증 결과의 "실제로는 20~30배"와 다름. 코드는 둘 다 받되 하나만 쓰게 함. 두 분 결정 필요(16-3).
2. **청산 단위:** 검증 결과는 "청산은 R·가격 기준(ROE 아님)". 이 명세의 기본 `exit_ref = "rule"`은 규칙 계좌의 계단 잠금(ROE 정의)을 그 신호의 규칙 레버리지로 **가격으로 고정**해 AI 크기와 무관하게 만듦. "R 계단"(예: +1R마다 잠금)을 뜻한 것이라면 그것은 새 청산 규칙이라 사전 등록이 필요 → `exit_ref = "r_ladder"`로 받을 자리는 둠.
3. **PLAN 초안과 다른 점 (검증 결과 쪽으로):** 진입 봉 15m/30m만(A) → 설정 B, 갈아타기 허용 → 금지, 매주 커스텀 값 반영 → 판정 트레이더 동결, 30분마다 + 0.5R 점검 → 봉 마감 + 1.0R.
4. **PLAN "규칙 봇이 20초 안 답을 읽음" → 따라가는 장부가 읽음.** 효과(규칙 봇은 기다리지 않음, 같은 체결)는 같고 규칙 봇 코드는 안 바뀜.
5. **v2 설계와 다른 점:** AI 진입 체결을 v2 5-3 7번("답 받은 분의 다음 분 시가")이 아니라 규칙 계좌와 같은 `ref_price`로 함(짝 비교를 깨끗하게). v2 방식은 늦은 체결 그림자로 기록.
6. **판정 묶음 크기:** 검증 결과의 BH 묶음 K = 16~18은 2차를 연다는 전제. 등급 S는 2차가 없으므로 K = 10(1차 10명)입니다. 묶음은 D0 전에 등급과 함께 고정해야 하며, S에서 M으로 올리면 10/31 전에 K를 다시 고정해야 합니다(판정 명세).

---

## 19. 열린 질문

1. (두 분) 크기 규칙: `recommended_v1`(다) / `fixed_risk_maxlev_v1`(라). 1h·4h 위험 1% / 1.5%.
2. (두 분·청산 명세) `exit_ref`: 규칙 계좌 잠금 가격(기본) / R 계단(새 사전 등록).
3. (판정 명세) 무응답을 주 지표에서 "건너뜀 0R"로 셀지, 빼고 셀지(빼면 몰림 시간대 선택 편향 가능).
4. (두 분) AI 진입 체결: `ref_price`(기본, 깨끗한 짝 비교) / 답 받은 다음 분 시가(현실적).
5. (비용 명세) 등급별 `hold_wakes`, 생각 깊이·`max_tokens`, 그림자 질문 5명 목록, 작업자 풀 크기 — 0차 재생 뒤 확정.
6. (두 분) 동점에서 1순위를 건너뛰면 2순위를 다시 물을지(기본: 묻지 않음).
7. (두 분) 쌍둥이를 결정 그림자(기본)로 둘지, 따로 거래하는 계좌로 둘지.
8. (구현) 답 형식: 구조화 출력(기본) / 지시문 JSON — 캐시 미리 데우기와 맞는지 0차에서 확인.
9. (두 분) 같은 서버(이 명세의 전제) — v2의 별도 서버 안은 SQLite를 따라 읽는 이 방식과 맞지 않음. 별도 서버를 원하면 신호·봉 복제 장치를 따로 만들어야 함.
10. (두 분) AI 전용 텔레그램 봇과 방을 새로 만들지(v2 12-2), 지금 방을 쓸지.
11. (두 분) AI 운행 중 규칙 봇 초기화를 허용할지(허용 시 확인 문구 + `accept_source`).
12. (조직) Anthropic 조직 등급의 속도 한도가 경계 몰림을 견디는지, 이 서비스 전용 작업 공간을 만들지.
