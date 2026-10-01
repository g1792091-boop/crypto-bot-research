# 실거래 안전장치 (테스트넷 → 실거래)

작성: 2026-10-01 (KST). 대상: 두 분(운영자). 코드: `paperbot/executor.py`, `paperbot/testnet.py`, `paperbot/mainnet.py`, `paperbot/risk.py`, `paperbot/livepnl.py`.

## 한눈에 보기
- **실행기:** paper 계좌 **1개**를 골라, 그 계좌의 진입·잠금·청산을 바이낸스 선물에 실제 주문으로 따라 합니다. 위험 규칙이 막아 세웁니다.
- **기본은 테스트넷(가짜 돈)입니다.** 실거래(진짜 돈)는 설정·환경 변수·키·거래소 확인이 **모두** 맞을 때만 켜집니다(아래 1-9). 하나라도 틀리면 주문 하나 없이 멈춥니다.
- **테스트넷과 실거래는 같은 코드로 주문합니다.** 다른 것은 주소, 키, 시작할 때의 확인뿐입니다. 그래서 테스트넷에서 확인한 동작이 실거래에서도 같습니다.
- **빠른 진입(선택):** paper 계좌가 신호를 받는 순간(1~2초 안) 진입합니다. 예전에는 paper 포지션이 생긴 뒤라 1~2분 늦었습니다(1-10).
- **진짜 손익과 비용:** 거래마다 거래소의 실제 체결 기록으로 손익·수수료·펀딩·슬리피지를 계산하고, 보충 규칙 Q6 4번의 "실제 비용 ÷ 가정 비용"을 잽니다(1-11).
- **레버리지 단계 점검:** `stage-check` 명령 하나로 2단계(20~50배) 조건을 한국어로 보여 줍니다. 레버리지를 올리는 것은 두 분이 설정을 고치는 일입니다.
- **서버:** 실행기 서비스(`paperbot-executor`)는 설치만 되고 **꺼져 있습니다.** 두 분이 켭니다.
- **순서:** 테스트넷 연습(drill) → 테스트넷 1주 운영 → 실거래 $500 (3장).
- **테스트넷이 못 보여주는 것:** 테스트넷 가격·체결은 실제 시장과 달라서 수익과 실제 슬리피지는 실거래에서만 알 수 있습니다.

---

## 1. 안전장치가 하는 일

### 1-1. 손절은 거래소에 걸어 둡니다
- 진입하자마자 손절 주문을 **바이낸스 서버에** 걸어 둡니다. 봇이나 서버가 죽어도 손절은 거래소가 실행합니다.
- 손절은 paper 규칙과 같은 **마지막 체결가**로 발동합니다(보충 규칙 Q4). 마크 가격이 아닙니다.
- 바이낸스는 2025-12-09부터 손절 같은 조건부 주문을 별도 창구("알고 주문")로만 받습니다. 그 창구로 보냅니다.
- 손절 주문은 "포지션을 줄이기만 하는" 주문(reduce-only)이라, 잘못 발동해도 반대 포지션을 새로 만들지 않습니다.
- 걸고 나면 거래소에 다시 물어서 **정말 걸려 있는지 확인**합니다.

### 1-2. 잠금(익절선) 올리는 순서
paper 계좌가 잠금을 올리면 거래소 손절도 따라 올립니다.
1. **새 손절을 먼저 겁니다.** (잠깐 동안 손절이 2개 있습니다.)
2. 새 손절이 걸려 있는지 **확인합니다.**
3. 그다음에 **옛 손절을 취소합니다.**

그래서 손절이 하나도 없는 순간이 생기지 않습니다.
- 새 손절이 "가격이 이미 지나서 바로 발동한다"(오류 -2021)며 거절되면: **시장가로 바로 닫습니다**(reduce-only).
- 그 밖의 이유로 거절되면: 옛 손절은 그대로 두고 다음 반복에서 다시 시도합니다. 3번 연속 실패하면 **소리 있는 알림**.

### 1-3. 매 반복마다 거래소와 대조 (약 3초마다)
| 발견한 상황 | 하는 일 |
|---|---|
| 포지션이 있는데 손절이 없음 | **즉시 손절을 다시 겁니다.** 걸 수 없으면 바로 닫습니다. 소리 있는 알림 |
| 손절 수량이 포지션보다 작음(부분 체결 등) | 맞는 수량의 새 손절을 먼저 걸고 옛 것을 취소 |
| 손절이 2개 이상 남아 있음 | 맞는 손절 하나만 남기고 나머지 취소 |
| 손절 위치가 기록과 다름 | 기록대로 옮김(새 것 먼저) |
| 실행기가 모르는 포지션(다른 코인, 손으로 연 주문 등) | **바로 닫고** 소리 있는 알림 |
| 포지션 방향이 기록과 반대 | 닫고 **멈춤** |
| 기록엔 포지션이 있는데 거래소엔 없음 | 손절이 발동했는지 확인하고 거래를 마감 기록 |
| 포지션 없이 손절만 남아 있음 | 취소 |

**주의:** 실행기 계정에서 사람이 손으로 주문하면 "모르는 포지션"으로 보고 닫습니다. 같은 계정에서 손으로 거래하지 마세요.

### 1-4. 위험 규칙 (`paperbot/risk.py`)
결정은 네 가지입니다: **허용 / 줄여서 허용 / 막음 / 모두 닫고 멈춤**. 이유는 한국어로 기록되고 알림에 나갑니다.

| 규칙 | 걸리면 |
|---|---|
| 비상 정지 파일이 있음 | 모두 닫고 멈춤 |
| 하루 손실이 한도에 닿음(09:00 KST 시작 금액 대비, 열린 포지션 손실 포함) | 모두 닫고 멈춤 |
| 최고점 대비 낙폭이 멈춤 기준에 닿음 | 모두 닫고 멈춤 |
| 연속 손실 횟수가 기준에 닿음 | 모두 닫고 멈춤 |
| 레버리지가 상한보다 높음 | 상한으로 낮춰서 진입 |
| 포지션 크기가 상한보다 큼 | 상한에 맞게 줄여서 진입. 거래소 최소보다 작아지면 진입 안 함 |
| 허용 코인이 아님 | 진입 안 함 |

- **멈춤은 저절로 풀리지 않습니다.** 다시 켜도 멈춤 그대로입니다. 사람이 `clear-halt` 명령으로 풉니다(3-5).
- 하루 손실로 멈춘 것을 같은 날 풀면 곧바로 다시 멈춥니다. 다음 날 09:00 KST 이후에 푸세요.
- 멈춤을 풀면 낙폭 기준점(최고점)과 연속 손실 수는 그때부터 새로 셉니다.
- 설정 값이 하나라도 비어 있으면 실행기는 **켜지지 않습니다.**

### 1-5. 비상 정지
- 설정의 파일(`/var/lib/paperbot/STOP`)을 만들면, 다음 반복(약 3초 안)에 **모두 닫고 멈춥니다.**
  ```
  sudo touch /var/lib/paperbot/STOP
  ```
- 파일을 지워도 멈춤은 그대로입니다. 풀려면 3-5를 따르세요.
- 실행기 자체를 끄려면 `sudo systemctl stop paperbot-executor`. **끄기만 하면 포지션과 거래소 손절은 그대로 남습니다**(손절이 계속 보호). 모두 닫으려면 STOP 파일을 먼저 만들고, 닫힌 것을 확인한 뒤 끄세요.

### 1-6. 오류와 시계
- **인터넷 끊김, 시간 초과, 거래소 5xx:** 0.5 → 1 → 2초 간격으로 다시 시도합니다.
- **주문은 두 번 들어가지 않게:** 모든 주문에 고유 번호를 붙입니다. 답을 못 받으면 그 번호로 "들어갔나?"를 먼저 묻고, 없을 때만 다시 보냅니다.
- **거래소가 거절한 주문(4xx):** 그대로 다시 보내지 않습니다.
- **서버 시간:** 10분마다 거래소 시간에 다시 맞춥니다. 시계가 어긋나 거절(오류 -1021)되면 바로 맞추고 한 번만 다시 보냅니다.
- **요청 한도:** 한도의 80% 가까이면 쉬어 갑니다. 429면 거래소가 말한 시간만큼, 418(일시 차단)이면 2분 이상 쉬고 소리 있는 알림.
- 반복 중 오류가 나도 실행기는 기록하고 다음 반복으로 갑니다(3, 10, 30번째 연속 오류에 소리 있는 알림).

### 1-7. 재시작
- 진입 주문을 보내기 **전에** "진입 중"을 먼저 기록합니다. 주문 직후 꺼져도 다시 켜질 때 거래소를 보고 정리합니다(체결됐으면 이어받고 손절 확인, 아니면 취소로 기록).
- 열린 포지션, 손절 위치, 멈춤, 연속 손실 수가 모두 실행기 DB에 있어 재시작 뒤 그대로 이어집니다.
- 서비스가 오류로 죽으면 systemd가 30초 뒤 다시 켭니다. **시작 확인에서 거부된 경우(종료 코드 2)는 다시 켜지 않습니다.** 원인을 고치고 사람이 켭니다.

### 1-8. 기록
실행기는 **자기 DB 하나**에만 씁니다. 모드마다 다른 파일입니다.
- 테스트넷: `/var/lib/paperbot/exec/executor-testnet.db`
- 실거래: `/var/lib/paperbot/exec/executor.db`

DB에는 처음 쓴 모드와 계좌가 적힙니다. **다른 모드나 다른 계좌로 같은 DB를 쓰려 하면 켜지지 않습니다**(테스트넷 기록이 실거래 기록에 섞이지 않게).

| 표 | 내용 |
|---|---|
| `events` | 모든 판단과 일(진입 검사, 손절, 대조 결과, 오류, 재시도) |
| `requests` | 거래소에 보낸 모든 주문·취소와 답(서명·키는 기록하지 않음), 실패한 모든 요청 |
| `trades` | 거래별 진입·청산·이유·손익, 그리고 체결 기준 실현 손익·수수료·펀딩·슬리피지·비용 |
| `fills` / `funding` | 거래소의 체결 기록·펀딩 기록 원본 |
| `equity` | 5분마다 계좌 금액(낙폭 계산용) |
| `halts` | 멈춤과 해제(누가, 언제, 메모, 계획된 멈춤인지) |
| `state` | 재시작용 현재 상태, 모드·계좌·시작일 |

`paper3.db`는 **읽기만** 합니다. 실행기 DB는 매일 백업됩니다(`deploy/paperbot-backup.sh`, 14일치).

### 1-9. 접근 막기와 실거래 관문
**언제나:**
- **AI 에이전트는 주문하지 않습니다.** 에이전트·대시보드·paper 실행기·매일 점검 코드는 실행기·테스트넷·실거래 코드를 불러오지 않습니다(시험으로 확인).
- **키 파일은 root만 읽습니다.** `/etc/paperbot/executor.env`는 `root:root 600`입니다. systemd가 실행기에게만 넘겨 줍니다. 에이전트와 대시보드 서비스는 이 파일과 실행기 DB 폴더(`/var/lib/paperbot/exec`)를 아예 볼 수 없습니다.
- **paper 실행기의 읽기 전용 키(`BINANCE_API_KEY`)는 주문 키로 받지 않습니다.** 환경 변수와 `/etc/paperbot/live.env` 둘 다 비교합니다.
- 키는 저장소에 넣지 않습니다.

**테스트넷:** 주소 `testnet.binancefuture.com`만, 키 `TESTNET_API_KEY`/`TESTNET_API_SECRET`만(실거래 키·paper 키와 같으면 거부).

**실거래 관문 — 모두 맞아야 켜집니다:**
| # | 관문 | 틀리면 |
|---|---|---|
| 1 | 설정 `"mode": "mainnet"` | 테스트넷으로 돎 |
| 2 | 환경 변수 `PAPERBOT_LIVE_MAINNET=I_UNDERSTAND` (정확히 이 글자) | 거부 |
| 3 | 키는 `LIVE_API_KEY`/`LIVE_API_SECRET`에서만. paper 키·테스트넷 키와 같으면 안 됨 | 거부 |
| 4 | 주소는 `fapi.binance.com`만(키 확인은 `api.binance.com`) | 거부 |
| 5 | 키 권한 확인(`api.binance.com`): **출금 꺼짐, 선물 켜짐, IP 제한 있음**. 확인 자체가 안 되면(연결 안 됨) | 거부 |
| 6 | 위험 설정이 모두 채워짐, `budget_usd`(정한 금액) 있음 | 거부 |
| 7 | 선물 지갑이 `budget_usd × 1.2` 이하($500이면 $600 이하) | 거부(주 계정을 실수로 쓰는 것 방지) |

- 관문 5에서 이체·현물 거래 같은 필요 없는 권한이 켜져 있으면 거부하지는 않고 **주의 알림**을 보냅니다. 꺼 두세요.
- 관문 7은 **시작할 때** 봅니다. 수익이 쌓여 $600을 넘으면 다음에 켤 때 거부됩니다. 그때 수익을 빼거나, 두 분이 `budget_usd`를 고칩니다.
- 거부되면 주문은 하나도 나가지 않고, 이유가 한국어로 화면·알림·DB에 남습니다.

### 1-10. 빠른 진입 (`"entry_source": "signal"`)
**예전(`"paper"`, 기본):** paper 계좌가 신호를 받은 뒤, 다음 1분봉이 끝나 paper 포지션이 기록되면 따라 들어갑니다. 그래서 **1~2분 늦습니다.**

**빠른 진입(`"signal"`):**
1. 실행기가 `paper3.db`의 신호 기록(`signal_log`)을 1.5초마다 읽습니다(읽기만).
2. 고른 계좌(예: `V45_AMB@15m`)의 매매법·봉에 "SUBMITTED"(계좌에 넘겨짐) 신호가 새로 생기면, 같은 순간 저장된 그 계좌의 대기 신호를 봅니다.
3. paper 규칙대로 들어갈지 판단합니다: 이미 포지션 중이거나 멈춤·파산이면 안 들어감, 여러 신호면 paper와 같은 순서로 하나, 크기는 paper 규칙의 크기 계산(거래소 레버리지 구간 사용)에 `qty_scale`과 위험 한도를 적용.
4. **바로 시장가로 진입**하고 손절을 겁니다. 신호가 준비된 뒤 보통 **2초 안**입니다(시험에서 1.5초 이내 확인).
5. 1~2분 뒤 paper 포지션이 **같은 번호(계좌|코인|진입 시각)**로 나타나면 "확인됨". 그다음 잠금·청산은 예전처럼 paper 포지션을 따릅니다.
6. paper가 그 신호로 **진입하지 않았으면**(그 분봉을 처리했는데 포지션이 없음) 바로 닫습니다. 4분(`direct_confirm_s`) 안에 paper 확인이 없어도 닫습니다. 그동안은 거래소 손절이 지킵니다.
7. 불분명하면(신호를 20초 넘게 늦게 봄, 재시작 직후, 대기 신호 없음, 레버리지 구간을 못 읽음) 빠른 진입을 하지 않고 예전 방식으로 paper 포지션을 따릅니다.

**남는 차이:**
- **진입 가격:** paper는 "다음 1분봉 시작 + 신호 때의 호가(매수는 매도 1호가) + 0.02% 슬리피지"로 체결했다고 **가정**합니다. 실거래는 **지금 시장가로 실제 체결**됩니다. 같은 순간이 아니므로 가격이 조금 다릅니다. 손절은 paper와 같은 **비율 거리**를 실제 체결가에 적용합니다.
- **크기:** 실행기의 크기 계산이 paper가 나중에 정한 크기와 다르면 기록하고 알려 주지만(`direct_confirmed`), 이미 들어간 크기를 바꾸지는 않습니다.
- **청산:** 잠금·청산은 여전히 paper 포지션(1분봉 처리 뒤)을 따르므로, 거래소 손절에 걸리지 않는 청산은 paper보다 몇 초~1분쯤 늦습니다. 거래소 손절은 즉시 발동합니다.
- paper가 진입하지 않은 신호로 잠깐 들어갔다 나오는 일이 드물게 생길 수 있습니다(그 비용도 기록됨).

### 1-11. 진짜 손익과 비용 (보충 규칙 Q6 4번)
거래가 끝나면 거래소에서 그 거래의 **체결 기록**(`/fapi/v1/userTrades`)과 **펀딩 기록**(`/fapi/v1/income`)을 읽습니다.
- **손익** = 실현 손익 합 − 수수료 합 + 펀딩 합. 이 값이 거래 기록과 연속 손실 계산에 쓰입니다. 읽기에 실패하면 잠시 지갑 잔고 차이로 적어 두고, 다음 반복에서 다시 읽어 바꿉니다.
- **실제 비용** = 수수료 + 슬리피지. 슬리피지는 실행기가 판단한 순간 본 가격과 실제 체결가의 차이입니다(진입: 주문 직전 마지막 체결가, 손절 청산: 손절 가격, 시장가 청산: 주문 직전 마지막 체결가). 불리하면 +.
- **가정 비용** = 같은 거래 금액에 paper 규칙이 매기는 비용: 진입·청산 각각 테이커 수수료(paper가 실제로 쓰는 값, `paper3.db` 거래에서 읽음, 기본 0.05%) + 슬리피지 0.02%.
- **비용 비율** = 실제 비용 합 ÷ 가정 비용 합. 1.5 이하여야 2단계 조건 4번을 채웁니다.
- 기준 가격을 "마지막 체결가"로 잡아서 호가 차이의 절반이 실제 비용에 들어갑니다. 즉 **조금 불리하게(보수적으로)** 잽니다.
- **BNB로 수수료를 내면** USDT로 환산하지 않아 그 거래는 "잰 거래"에서 빠집니다. 실행기 하위 계정에서 **BNB 수수료 할인을 꺼 두세요.**
- 펀딩은 손익에는 들어가고 비용 비율에는 들어가지 않습니다(paper도 펀딩을 따로 계산).

---

## 2. 두 분이 정할 것 (설정 파일)
설정 파일 `/etc/paperbot/executor.json`(서버에만, 저장소에 넣지 않음). 빈 칸이 있으면 켜지지 않습니다.

| 설정 이름 | 뜻 | 두 분 결정 |
|---|---|---|
| `mode` | `"testnet"`(기본) 또는 `"mainnet"` | 테스트넷 → 1주 뒤 실거래 |
| `account` | 따라 할 paper 계좌(예: `V45_AMB@15m`), 매매법 1개 | ☐ ____ |
| `db` | 실행기 DB(1-8) | 테스트넷 `.../exec/executor-testnet.db`, 실거래 `.../exec/executor.db` |
| `budget_usd` | 실행기 계정에 넣는 돈(실거래 필수) | Q6: **500** |
| `qty_scale` | 실행기 수량 = paper 수량 × 이 값 | $500 ÷ paper $5,000 = **0.1** |
| `entry_source` | `"paper"`(paper 포지션 따라가기) / `"signal"`(빠른 진입, 1-10) | `"signal"` 추천 |
| `risk.daily_max_loss_usd` | 하루 최대 손실($) | Q6: **100** |
| `risk.max_drawdown_pct` | 멈춤 낙폭(비율) | Q6: **0.4** (40%) |
| `risk.max_consecutive_losses` | 연속 손실 멈춤(번) | Q6: **4** |
| `risk.max_leverage` | 최대 레버리지(배) | Q6: 1단계 **20** |
| `risk.max_notional_usd` | 포지션 하나 최대 크기($, 레버리지 포함) | ☐ $____ (아래 참고) |
| `risk.allowed_symbols` | 거래 허용 코인 | paper v3의 6개 |
| `risk.kill_file` | 비상 정지 파일 | `/var/lib/paperbot/STOP` |
| `stop_from` | `"ratio"`(paper 손절과 같은 비율 거리, 추천) / `"price"` | `"ratio"` |
| `max_entry_age_s` | paper 포지션 방식에서 이보다 오래된 진입은 안 따라감 | 180 |
| `paper_stale_s` | paper 기록이 이만큼 멈추면 새 진입 안 함 | 300 |

**포지션 크기 참고:** paper는 계좌의 20~40%를 증거금으로 20~50배를 씁니다. 1단계는 20배 상한이라, paper가 40%×50배(계좌의 20배 크기)로 들어가면 실행기는 같은 크기를 20배로 열려고 해서 증거금이 $500 전부가 됩니다. `max_notional_usd`를 예컨대 **$4,000**(= $500 × 40% × 20배)로 두면 증거금이 40%를 넘지 않습니다. 대신 그런 거래는 paper보다 작게 들어갑니다. 숫자는 두 분이 정하세요.

실거래 설정 예시:
```json
{
  "mode": "mainnet",
  "account": "V45_AMB@15m",
  "paper_db": "/var/lib/paperbot/paper3.db",
  "db": "/var/lib/paperbot/exec/executor.db",
  "budget_usd": 500,
  "qty_scale": 0.1,
  "entry_source": "signal",
  "stop_from": "ratio",
  "risk": {
    "daily_max_loss_usd": 100,
    "max_drawdown_pct": 0.4,
    "max_consecutive_losses": 4,
    "max_leverage": 20,
    "max_notional_usd": null,
    "allowed_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"],
    "kill_file": "/var/lib/paperbot/STOP"
  }
}
```
(`max_notional_usd`를 채우기 전에는 켜지지 않습니다.) 테스트넷 설정은 `"mode": "testnet"`, `"db": "/var/lib/paperbot/exec/executor-testnet.db"`이고 `budget_usd`는 빼도 됩니다.

**참고:** 하루 손실과 낙폭은 거래소 계정 **전체 잔고**로 계산합니다. 테스트넷 계정에는 가짜 돈이 많아서 %가 작게 나옵니다. 실거래는 하위 계정에 정한 금액만 넣어야 숫자가 뜻대로 작동합니다.

### 레버리지 단계 (2026-10-01 두 분 결정)
- **1단계:** 최대 20배(`max_leverage: 20`).
- **2단계:** 실거래 30일 뒤 아래를 **모두** 채우면 paper와 같은 20~50배로 올릴 수 있습니다.
  1. 실거래 30일 이상, 끝난 거래 30건 이상
  2. 실거래 순손익 플러스, 같은 기간 따라 하는 paper 계좌도 플러스
  3. 최대 낙폭 25% 미만
  4. 실제 비용 ÷ 가정 비용 1.5 이하 (체결 기록으로 잰 값)
  5. 계획에 없던 멈춤 0번(방향이 반대인 포지션 같은 멈춤, 그리고 대조 비상 처리: 모르는 포지션, 손절 없음, 손절 실패, 닫은 뒤 남은 포지션)
- 점검 명령(아무 주문도 하지 않음, DB를 읽기만 함):
  ```
  cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.executor stage-check --config /etc/paperbot/executor.json
  ```
  예시 출력:
  ```
  레버리지 단계 점검 (실거래 기록, 2026-11-02 09:00 KST ~ 2026-12-03 10:00 KST)
  - 통과: 실거래 기간 31일 (30일 이상 필요)
  - 통과: 끝난 거래 34건 (30건 이상 필요)
  - 통과: 실거래 순손익 $41.20 (플러스 필요)
  - 통과: 같은 기간 paper 계좌 손익 $388.00 (플러스 필요)
  - 통과: 최대 낙폭 12% (25% 미만 필요)
  - 미달: 실제 비용 ÷ 가정 비용 1.62 (1.5 이하 필요)
  - 통과: 계획에 없던 멈춤 0번 (0번 필요)
  비용: 실제 $9.70 ÷ paper 규칙 가정 $5.99 = 1.62 (체결 기록으로 잰 거래 34/34건)
  paper 계좌 V45_AMB@15m 같은 기간: 끝난 거래 29건, 손익 $+388.00 (실행기 크기로 환산 $+38.80)
  결론: 아직 아님 — 최대 레버리지 20배. 아직 20배 상한을 유지합니다.
  ```
- 테스트넷 DB로 돌리면 "테스트넷 기록입니다(참고용)"라고 나오고 통과로 보지 않습니다.
- 코드는 **판정만** 합니다. 통과하면 두 분이 설정의 `max_leverage`를 50으로 고치고 실행기를 다시 켭니다. AI가 레버리지를 올리지 않습니다.

---

## 3. 순서: 테스트넷 연습 → 테스트넷 1주 → 실거래 $500
아래 명령은 모두 서버에서 실행합니다. 코드는 `/opt/crypto-bot-research`, 파이썬은 `/opt/paperbot/venv`입니다.

### 3-0. 준비 (한 번)
1. 코드를 올리고 `sudo bash deploy/install.sh`. 실행기 서비스가 **설치만** 되고, `/etc/paperbot/executor.env`(빈 틀, root만 읽음)와 `/var/lib/paperbot/exec` 폴더가 생깁니다.
2. 키 파일 편집(채팅이나 저장소에 키를 붙이지 마세요):
   ```
   sudo nano /etc/paperbot/executor.env
   ```
   테스트넷 단계에서는 `TESTNET_API_KEY`, `TESTNET_API_SECRET`(https://testnet.binancefuture.com 에서 만든 키)과 텔레그램 값만 채웁니다. `LIVE_*`와 `PAPERBOT_LIVE_MAINNET`은 **비워 둡니다.**
3. 설정 파일 `/etc/paperbot/executor.json`을 2장처럼 만들고(`"mode": "testnet"`, `"db": "/var/lib/paperbot/exec/executor-testnet.db"`) 확인:
   ```
   sudo install -o root -g paperbot -m 640 /dev/null /etc/paperbot/executor.json    # 처음 한 번
   sudo nano /etc/paperbot/executor.json
   cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor.json
   ```
   "준비됨"이 나와야 합니다.

키 파일은 root만 읽으므로, 손으로 돌리는 명령은 `deploy/paperbot-exec.sh`로 돌립니다(키를 넘겨 paperbot 사용자로 실행).

### 3-1. 테스트넷 연습(drill), 롱·숏 각각
```
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh testnet drill --symbol BTCUSDT --side long
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh testnet drill --symbol BTCUSDT --side short
```
9줄 모두 `[OK]`여야 합니다:
1. 시작 전 포지션·주문 없음
2. 레버리지 설정
3. 시장가 진입 체결
4. 포지션 크기 일치
5. 손절이 거래소에 걸림(알고 주문, 마지막 체결가)
6. 손절 옮기기: 새 손절이 걸린 뒤(이때 2개) 옛 손절 취소
7. 재시작 점검: 손절을 일부러 지우면 다시 걸어 놓음
8. 가격보다 잘못된 쪽에 건 손절이 -2021로 거절되고 시장가로 닫힘
9. 포지션·주문 모두 없음

하나라도 `[FAIL]`이면 다음으로 가지 말고 출력 전체를 개발 쪽에 보내 주세요.

그다음 관문 점검(주문 없음):
```
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh executor preflight --config /etc/paperbot/executor.json
```
모두 `[OK]`여야 합니다(설정, 주소, 서버 시간 차이 1초 미만, 지갑, paper3.db 읽기).

### 3-2. 테스트넷 운영 (1주 추천)
paper 실행기(`paperbot-live3`)가 돌고 있어야 합니다.
```
sudo systemctl start paperbot-executor
sudo journalctl -fu paperbot-executor                      # 화면으로 보기 (Ctrl+C로 보기만 끝남)
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-testnet.db
```
첫날 일부러 문제 만들어 보기(포지션이 열려 있을 때):
| 해 볼 것 | 기대하는 결과 |
|---|---|
| 테스트넷 웹 화면에서 손절 주문 취소 | 3초 안에 손절이 다시 걸리고 소리 있는 알림 |
| 테스트넷 웹 화면에서 다른 코인 포지션을 손으로 열기 | 바로 닫히고 "모르는 포지션" 알림 |
| `sudo systemctl restart paperbot-executor` | 포지션과 손절 그대로 이어받음 |
| `sudo touch /var/lib/paperbot/STOP` | 모두 닫히고 "거래를 멈춥니다" 알림, 다시 켜도 멈춤 |

거래 기록 보기(읽기만):
```
sudo -u paperbot sqlite3 -readonly /var/lib/paperbot/exec/executor-testnet.db "SELECT datetime(entry_ts/1000,'unixepoch','+9 hours'), symbol, exit_reason, round(pnl,2), pnl_source, round(real_cost,3), round(assumed_cost,3) FROM trades ORDER BY entry_ts DESC LIMIT 10"
```

1주 동안 확인할 것(모두 "예"여야 실거래로):
- ☐ 설명 안 되는 알림이나 `loop_error`가 계속 나오지 않음
- ☐ 거래마다 `trades`의 `pnl_source`가 `fills`(체결 기록으로 계산됨)
- ☐ 빠른 진입을 쓰면: `entry` 기록에 "빠른 진입, 신호 후 N초"가 대부분 2초 안, `direct_confirmed`가 대부분 "맞습니다"
- ☐ `stage-check`가 돌아감(테스트넷이라 "참고용"으로 나오는 것이 정상)
- ☐ 텔레그램 알림이 두 분 폰에 옴

그다음 테스트넷 실행기를 끕니다: `sudo systemctl stop paperbot-executor`.

### 3-3. 실거래 $500
**바이낸스에서(두 분이 직접):**
1. 실행기 전용 **하위 계정**(sub-account)을 만들고, 선물(USDⓈ-M)을 켭니다. 주 계정은 쓰지 않습니다.
2. 하위 계정에 **$500 USDT만** 선물 지갑으로 옮깁니다($600을 넘으면 실행기가 켜지지 않습니다).
3. 하위 계정에서 API 키를 만듭니다: **선물 거래 켬, 출금 끔, 서버 IP만 허용**(IP 제한 필수). 이체·현물·마진 권한은 끕니다. **BNB 수수료 할인 끔.** 포지션 모드는 단방향(one-way).
4. 이 키는 paper 실행기의 읽기 전용 키와 **다른 키**여야 합니다.

**서버에서:**
1. `sudo nano /etc/paperbot/executor.env`:
   ```
   LIVE_API_KEY=(하위 계정 키)
   LIVE_API_SECRET=(하위 계정 비밀키)
   PAPERBOT_LIVE_MAINNET=I_UNDERSTAND
   ```
   (`TESTNET_*`는 남겨 둬도 됩니다. 실거래 모드에서는 쓰지 않습니다.)
2. `/etc/paperbot/executor.json`을 2장의 실거래 예시처럼 바꿉니다: `"mode": "mainnet"`, `"db": "/var/lib/paperbot/exec/executor.db"`, `"budget_usd": 500`, `"qty_scale": 0.1`, 위험 숫자(Q6), `max_notional_usd`.
3. 관문 점검(주문 없음):
   ```
   sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh executor preflight --config /etc/paperbot/executor.json
   ```
   출금 꺼짐·선물 켜짐·IP 제한·지갑 $600 이하를 포함해 모두 `[OK]`여야 합니다.
4. 켜기: `sudo systemctl start paperbot-executor`. 첫 거래는 두 분이 화면(`journalctl -fu paperbot-executor`)과 바이낸스 앱으로 같이 봅니다: 진입, 손절이 거래소에 걸림, 청산, `trades`의 손익이 바이낸스 앱과 같음.
5. 며칠 문제없이 돌면 부팅 때 자동으로 켜지게: `sudo systemctl enable paperbot-executor`.
6. 30일 뒤부터 `stage-check`로 2단계를 점검합니다(2장).

**실거래를 끄려면:** `executor.env`에서 `PAPERBOT_LIVE_MAINNET`을 비우거나 설정의 `mode`를 `"testnet"`으로 돌리면, 다음 시작부터 실거래는 켜지지 않습니다. 열린 포지션은 그 전에 STOP 파일로 닫으세요.

### 3-4. 상태 보기
```
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor.db
```

### 3-5. 멈춤 풀기
```
sudo rm /var/lib/paperbot/STOP                       # 비상 정지 파일이 있었다면
sudo systemctl stop paperbot-executor                # 켜져 있으면 해제 명령이 거부됩니다
cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.executor clear-halt --config /etc/paperbot/executor.json --by 이름 --note "이유"
sudo systemctl start paperbot-executor
```
누가 언제 왜 풀었는지 `halts` 표에 남습니다.

---

## 4. 바이낸스 API에 대해 가정한 것
바이낸스 문서 사이트는 작업 환경에서 열리지 않아, **바이낸스 공식 파이썬 SDK**(PyPI: `binance-sdk-derivatives-trading-usds-futures` 17.5.0, `binance-sdk-wallet` 13.5.0, `binance-common` 4.5.0, 2026-10 기준)의 코드로 확인했습니다.

| 가정 | 확인 근거 | 어디서 확인 |
|---|---|---|
| 손절은 `POST /fapi/v1/algoOrder`, `algoType=CONDITIONAL`, `type=STOP_MARKET`, `triggerPrice` | SDK | drill 5 |
| `workingType=CONTRACT_PRICE`가 마지막 체결가, `priceProtect=false` | SDK | drill 5 |
| 알고 주문 조회·목록·취소: `GET/DELETE /fapi/v1/algoOrder`, `GET /fapi/v1/openAlgoOrders`, `DELETE /fapi/v1/algoOpenOrders` | SDK | drill 5~9 |
| 알고 주문 응답 `algoId`, `algoStatus`, `triggerPrice`, `quantity`; 발동하면 `actualOrderId`·`actualPrice`·`actualQty` | SDK | 실거래 첫 손절 |
| `closePosition=true`는 `quantity`·`reduceOnly`와 같이 못 씀 | SDK | (실행기는 수량+reduce-only) |
| 같은 쪽 reduce-only 손절 2개가 동시에 걸림 | **미확인** | drill 6 |
| 가격이 지난 손절은 -2021로 거절(알고 창구에서도) | **미확인** | drill 8 |
| 발동한 알고 주문 상태 `TRIGGERING`/`TRIGGERED`/`FINISHED` | ccxt 코드, **부분 확인** | 테스트넷 운영 |
| 없는 주문 -2013/-2011, 시계 어긋남 -1021 | 바이낸스 일반 오류 목록(기억), 알고 주문은 **미확인** | drill 7, 로그 |
| 체결 기록 `GET /fapi/v1/userTrades`: `symbol` 필수, `startTime`~`endTime` 최대 7일, 최근 3개월만; 응답 `price`, `qty`, `realizedPnl`, `commission`, `commissionAsset`, `orderId`, `side`, `time` | SDK | 테스트넷 운영 |
| 펀딩 `GET /fapi/v1/income?incomeType=FUNDING_FEE`: 응답 `income`(받으면 +), `asset`, `time`, `tranId` | SDK | 실거래(테스트넷 펀딩은 드묾) |
| 레버리지 구간 `GET /fapi/v1/leverageBracket` | SDK, paper 실행기도 사용 | 빠른 진입 시작 |
| 키 권한 `GET /sapi/v1/account/apiRestrictions`(`api.binance.com`, 서명 필요): `ipRestrict`, `enableWithdrawals`, `enableFutures`, `enableInternalTransfer`, `permitsUniversalTransfer` 등 | wallet SDK | 실거래 preflight |
| 주소: 실거래 `https://fapi.binance.com`, 테스트넷 `https://testnet.binancefuture.com`, 지갑 `https://api.binance.com` | `binance_common/constants.py` | preflight |
| 5xx·시간 초과는 "결과 모름", 429는 `Retry-After`, 418은 일시 차단, 사용량 헤더 `X-MBX-USED-WEIGHT-1M` | 바이낸스 일반 규칙 | 로그 |
| 테스트넷이 알고 주문 창구를 실제와 똑같이 지원 | **미확인** | drill 5~9 |

---

## 5. 실거래 전·후에 남은 일
1. **거래소 실시간 알림(사용자 데이터 스트림):** 지금은 3초마다 묻습니다. 손절 발동·체결을 즉시 받는 연결은 아직 없습니다.
2. **청산 시각:** 거래소 손절이 아닌 청산(paper 청산 따라가기)은 paper가 1분봉을 처리한 뒤라 몇 초~1분 늦습니다. 빠르게 하려면 paper 엔진의 청산 판단을 실행기가 직접 해야 합니다.
3. **청산가 확인:** 실제 크기·레버리지에서 손절이 청산가보다 안쪽인지 거래소 값으로 다시 확인하지 않습니다(paper는 확인함).
4. **서버 밖 생존 감시:** 실행기가 멈추면 폰에 알리는 외부 감시(paper 실행기의 `DEADMAN_URL` 같은 것)가 실행기에는 아직 없습니다. 지금은 systemd 재시작과 텔레그램 알림뿐입니다.
5. **잔고 확인은 시작할 때만:** 운영 중에 큰돈이 입금되면 다음 시작 때 거부됩니다(운영 중에는 막지 않음).
6. **거래소 사정:** 점검 시간, 코인 거래 중지·상장 폐지, 계정이 헤지 모드로 바뀐 경우의 처리.
7. **실거래 첫 거래 확인:** 실거래용 자동 연습(drill)은 없습니다. 첫 거래를 두 분이 같이 지켜보는 것으로 대신합니다(3-3).
8. **4장의 "미확인"** 항목은 테스트넷 연습과 운영에서 확인해야 합니다.
9. **규칙 조건:** 보충 규칙 Q3(30일 판정), Q6(거래 200건, 우연 아님, 국면 2개, 비용 확인)을 두 분이 확인한 계좌만 실거래합니다. 코드는 이 조건을 대신 판정하지 않습니다(`stage-check`는 레버리지 단계만 봄). 아무것도 통과하지 못하면 실거래는 하지 않습니다.
