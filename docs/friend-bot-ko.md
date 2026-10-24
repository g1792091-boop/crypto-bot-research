## 7. 실행기(WOO X Pro 2)

두 번째 WOO X Pro 계정(친구 계정)으로 '친구 매매법' 페이퍼 봇을 그대로 따라 하는 실거래 실행기입니다. **10/26(월)부터** 돌고,
설치·확인은 **10/25(일)** 에 합니다. 두 분의 바이비트·WOO X Pro·딥코인 실행기는 하나도 안 바뀝니다.

### 7-1. 한눈에

| 항목 | 내용 |
|---|---|
| 이름 | **WOO X Pro 2** (텔레그램 머리말 `[WOO X Pro 2 실거래 실행기]`. 두 분의 WOO X Pro 실행기는 예전처럼 `[WOO X Pro 실거래 실행기]`) |
| 서비스 | `paperbot-executor-wooxpro2` · 설정 `/etc/paperbot/executor-wooxpro2.json`(원본 `deploy/executor.live-wooxpro2.json`) · 기록 `/var/lib/paperbot/exec/executor-wooxpro2-live.db` |
| 키 파일 | **자기 키 파일** `/etc/paperbot/executor-wooxpro2.env` (두 분의 `/etc/paperbot/executor.env`는 아예 못 봄) |
| 따라가는 페이퍼 | 친구 매매법 `/var/lib/paperbot/combo/friend.db`, 계좌 `COMBO@mix` |
| 코인 | 페이퍼와 같은 여섯 개: BTC · ETH · SOL · DOGE · LTC · BCH (XRP 등 다른 코인은 거래하지 않음) |
| 배수 | 페이퍼 그대로 **모든 코인 35배**(진입할 때마다 그 코인을 격리 35배로 맞추고 다시 읽어 확인, 진입 주문에도 35배를 적어 보냄). 설정의 상한 `max_leverage`도 35 |
| 35배가 안 될 때 | **진입하지 않고 텔레그램으로 알립니다. 다른 배수로 몰래 거래하지 않습니다.** 그 코인의 거래소 최대 배수가 35보다 낮을 때(`레버리지 35배 설정이 거절돼 진입하지 않습니다`), 포지션이 35배로 열 수 있는 크기보다 클 때(`진입 주문이 거절됐습니다`), 페이퍼가 35배가 아닌 배수로 진입했을 때(`paper는 …배인데 … 상한 risk.max_leverage가 35배라 진입하지 않습니다`) |
| 손절 | **순ROE −50%**(페이퍼와 같은 정의, 수수료·슬리피지 포함): 이 실행기의 **자기 체결가**에서 가격 **1.3046%**(50% ÷ 35 − WOO X Pro 왕복 비용 0.124%) 반대쪽에 거래소 손절을 겁니다. 거래소 앱 화면 ROE로는 약 **−45.7%**. 가격 단위에 맞추면 한 틱 이내로 조금 더 가깝게, 멀어지는 쪽으로는 안 감. 페이퍼 손절 가격을 베끼지 않아서, 체결가가 페이퍼와 달라도 늘 순ROE −50%. 펀딩은 넣지 않습니다(손절 자리는 진입 때 정해지고, 펀딩만큼 실제 손익이 조금 달라짐) |
| 청산가 확인 | 35배 격리의 청산가는 체결가에서 약 2.86%(= 1 ÷ 35)에서 그 크기의 유지증거금률을 뺀 자리입니다. 진입 전에 거래소 위험 한도로 이것을 어림해, **손절(1.30%)이 청산가보다 0.2% 넘게 가깝지 않으면 진입하지 않고 알립니다**(`… 진입하지 않습니다: 35배 포지션 $…의 청산가가 약 …% 거리 … 손절은 옮기지 않습니다`). 손절을 청산가 안쪽으로 옮겨 맞추는 일은 하지 않습니다 |
| 계단 익절 | 거래소 기준: 이 실행기의 체결가 · WOO X Pro 1분봉 · WOO X Pro 비용(테이커 0.042% + 슬리피지 0.02%)으로, 페이퍼와 같은 계단(순ROE 12% → 10% 잠금, 17% → 15%, 22% → 20%, 이후 5%씩) |
| 손절 한 번 손실 | 증거금 40% × 순ROE 50% = **잔고의 약 20%**(펀딩·손절 체결 슬리피지에 따라 조금 더). 한도는 잔고의 35%(`max_loss_frac` 0.35)라 크기를 줄이지 않고 페이퍼 그대로 들어갑니다 |
| 신호등 | 꺼짐(페이퍼의 모든 진입을 따라감. 이 실행기만의 추가 관문 없음) |
| 잔고 바닥 | 잔고가 **시작 금액의 70%** 에 닿으면 새 진입을 멈춤(7-8) |
| 원금 회수 안내 | 잔고가 **시작 금액의 2배**가 되면 텔레그램 한 번(7-8) |

### 7-2. 친구에게 받을 것 (두 분이 친구 계정에 들어갈 일은 없습니다)

친구가 자기 WOO X Pro 앱·웹에서 직접 합니다:
- 신원 확인(KYC)을 끝내고, USDT를 **선물(계약) 계좌**로 옮겨 둡니다.
- 계정 → API 관리 → 새 API 만들기:
  - 메모: 영문·숫자로 짧게(예: `paperbot`). 메모도 서명에 들어가서 두 분이 그대로 받아 적어야 합니다.
  - 권한: **"읽기 전용, 선물 거래"만.** 출금은 없습니다(WOO X Pro 키 화면에는 출금 권한이 아예 없습니다).
  - 바인딩 IP: **`158.247.200.152`** (서버 주소)
- 두 분께 **접근 키(Access Key), 비밀 키(Secret Key), 메모** 세 가지를 줍니다. 비밀 키는 만들 때 한 번만 보입니다.
  - 이 대화(채팅), 텔레그램 단체방, 사진으로 주고받지 않습니다. 서버에 넣을 때(7-3) 옆에서 직접 불러 주거나, 친구가 직접 입력하는 것이
    가장 안전합니다.
- 친구에게 꼭 알려 둘 것:
  - **봇이 도는 동안 그 계정에서 직접 거래하지 않습니다.** 실행기는 자기가 모르는 포지션을 보면 바로 닫습니다.
  - 입금·출금은 **포지션이 없을 때** 하고 두 분께 알려 줍니다(잔고 바닥 기준은 입출금으로 바뀌지 않습니다: 7-8).
  - 키를 지우거나 새로 만들면 실행기가 멈춥니다. 새 키를 만들면 7-9 순서로 바꿉니다.

### 7-3. 키를 서버 키 파일에 넣기 (일요일)

`install.sh`가 빈 키 파일(`/etc/paperbot/executor-wooxpro2.env`, root만 읽음)을 만들어 둡니다. 그 파일을 엽니다:

```bash
sudoedit /etc/paperbot/executor-wooxpro2.env
```

아래 다섯 줄을 채우고 저장합니다(nano면 Ctrl+O, Enter, Ctrl+X):

```
WOOXPRO_LIVE_KEY=(친구 키의 접근 키)
WOOXPRO_LIVE_SECRET=(친구 키의 비밀 키)
WOOXPRO_LIVE_MEMO=(친구가 키 만들 때 적은 메모)
WOOXPRO_LIVE_KEY_CHECKED=FUTURES_ONLY_NO_WITHDRAW_IP_BOUND
PAPERBOT_LIVE_MAINNET=I_UNDERSTAND
```

- `WOOXPRO_LIVE_KEY_CHECKED` 줄은 "키를 '읽기 전용, 선물 거래 + 서버 IP'로 만든 것을 확인했다"는 두 분의 확인입니다. WOO X Pro는
  키 권한을 API로 알려 주지 않아서, 이 줄이 없으면 실행기가 켜지지 않습니다.
- 텔레그램 줄은 쓰지 않아도 됩니다: 이 실행기도 `/etc/paperbot/live-telegram.env`(실거래 봇 토큰과 두 분 개인 채팅)를 읽습니다.
  그 파일이 없는 서버라면 이 키 파일의 `#TELEGRAM_…` 줄에서 `#`을 지우고 채웁니다(채팅 줄을 빈 채로 두지 않습니다).
- **`/etc/paperbot/executor.env`를 복사해서 만들지 않습니다.** 이 파일에 다른 거래소 키(BYBIT_…, DEEPCOIN_… 등)가 있으면 실행기가
  켜지지 않습니다(키가 섞였다고 봅니다).
- 확인: `sudo ls -l /etc/paperbot/executor-wooxpro2.env` 가 `-rw------- 1 root root`여야 합니다.

### 7-4. 읽기 점검 (주문 없음) · 친구 계정이 맞는지 확인

이 키 파일로 돌리려면 명령 앞에 `--keys wooxpro2`를 붙입니다(없으면 두 분의 executor.env로 돕니다). 끝의 `--leverage 35`는 "여섯 코인
모두 35배로 맞춰 보고, 35배로 열 수 있는 크기를 읽어라", `--stop-net-roe 0.5`는 "순ROE −50% 손절과 청산가를 코인마다 견주어라"입니다:

```bash
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh --keys wooxpro2 wooxpro check --leverage 35 --stop-net-roe 0.5
```

- 이 줄들이 `[OK]`여야 합니다: 서버 시간, `계약 정보(6개 코인), 최대 배수 35배 이상`, 선물 계정 읽기, 수수료율, 열린 주문, 포지션 모드
  단방향, `격리 레버리지 모든 코인 35배(다시 읽어 확인)`, 키 확인. 이 점검이 친구 계정의 포지션 모드를 단방향으로, 여섯 코인을 격리
  35배로 맞춥니다.
  - `계약 정보`가 `[FAIL]`이면(어떤 코인의 `max_leverage`가 35보다 작음) 점검이 거기서 멈춥니다. 결과를 붙여 주세요. 그대로 켜면 그
    코인의 진입은 매번 거절·알림만 하고 거래하지 않습니다.
- `35배로 열 수 있는 포지션 크기(거래소 위험 한도)` 줄: 코인마다 `$…까지`가 나옵니다(WOO X Pro는 포지션이 클수록 최대 배수를 낮춥니다).
  이 금액이 **친구 잔고 × 14**(증거금 40% × 35배 = 한 번에 여는 포지션 크기)보다 커야 그 코인을 35배로 다 들어갈 수 있습니다. 작은
  코인이 있거나 `35배 안 됨`이면 알려 주세요(그 코인 진입은 거래소가 거절하고, 실행기는 진입하지 않고 알립니다). 이 줄은 `[FAIL]`이어도
  점검을 멈추지 않습니다.
- `35배 청산가와 손절(잔고 $… × 40% × 35배 = 포지션 $…, 손절 = 순ROE -50% = 가격 1.30%, …)` 줄: 지금 잔고로 여는 포지션 크기에서
  코인마다 `청산 약 2.36%(유지증거금률 0.50%) · 손절 1.30% → 손절이 먼저 · 잔고 $…까지 같음`처럼 나와야 합니다. `청산이 먼저이거나
  너무 붙음`이 나온 코인은 실행기가 진입하지 않습니다(알림만). `잔고 $…까지 같음`은 잔고가 그만큼 커질 때까지 손절이 청산보다 먼저라는
  뜻입니다. 이 줄도 `[FAIL]`이어도 점검을 멈추지 않습니다. 결과를 붙여 주세요.
- **친구 계정이 맞는지:** `선물 계정 읽기` 줄의 `equity`(잔고)가 **친구가 앱에서 보는 선물 잔고와 같아야** 합니다. 두 분 WOO X Pro
  잔고와 같으면 키가 바뀐 것이니 거기서 멈추고 7-3을 다시 봅니다. WOO X Pro API에는 "계정 번호"를 알려 주는 기능이 없어서, 잔고로
  확인합니다.
- `수수료율` 줄의 `taker_pct`가 0.042면 TetherMax 할인이 친구 계정에도 적용된 것입니다. 다르면 알려 주세요(설정의 비용을 맞춥니다).

### 7-5. 진짜 최소 주문 시험 (친구 계정에서 약 $6, 손절 발동 시험 포함, 최대 35분쯤)

```bash
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh --keys wooxpro2 wooxpro drill --confirm-order REAL_ORDER
```

- 가장 싼 코인(보통 DOGE)으로 진입 → 손절 걸기 → 손절 옮기기 → 손절 발동 시험 → 정리 → 손익 대조. 수수료와 몇 센트 손실이 납니다
  (친구에게 미리 알려 둡니다).
- 마지막 줄 `끝: drill …`이 나올 때까지 창을 닫지 않고 Ctrl+C를 누르지 않습니다(`docs/wooxpro-ko.md` 4)과 같습니다).
- 모두 `[OK]`가 아니면 실행기를 켜지 않습니다. 결과 전체를 붙여 주세요(키 값은 결과에 나오지 않습니다).

### 7-6. 설정 넣기 (실행기가 꺼진 상태에서)

```bash
sudo test -e /etc/paperbot/executor-wooxpro2.json || sudo install -o root -g paperbot -m 640 /opt/crypto-bot-research/deploy/executor.live-wooxpro2.json /etc/paperbot/executor-wooxpro2.json
sudoedit /etc/paperbot/executor-wooxpro2.json
```

두 값만 채웁니다(템플릿에는 비어 있어서, 채우기 전에는 실행기가 켜지지 않습니다):
- `"budget_usd"`: 친구 계정 선물 잔고(7-4 `equity`). 예: `500`
- `"qty_scale"`: 친구 잔고 ÷ 페이퍼 지갑. 페이퍼는 $1,000으로 시작하고 주말에는 진입하지 않으니 월요일 전에는 잔고 ÷ 1000.
  예: 잔고 $500이면 `0.5`. 그래야 실거래도 잔고의 40%를 증거금으로 씁니다.
- 잔고가 **$714보다 크면** `"risk"`의 `"max_notional_usd"`(포지션 최대 크기 $10,000)도 잔고 × 14보다 크게 바꿉니다(예: 잔고 $3,000이면
  `45000`). 그대로 두면 포지션이 $10,000으로 잘려 페이퍼보다 작게 들어갑니다.
- `"max_leverage": 35`, `"stop_from": "roe"`, `"stop_roe": 0.5`, `"stop_net": true`, `"ladder"`는 바꾸지 않습니다(두 분이 정한 35배 ·
  순ROE −50% · 10/5 계단).

확인:

```bash
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor-wooxpro2.json
```

볼 줄:
- `계단: 순ROE 12%에서 10% 잠금, 이후 5%씩`
- `손절: 이 실행기의 체결가에서 순ROE -50%(이 거래소 비용 왕복 0.124% 포함, 펀딩 제외) 자리, 거래하는 배수로 계산 (35배면 가격 1.3046%, 화면 ROE 약 -45.66%). 페이퍼의 손절 가격은 쓰지 않음`
- `청산가 확인: 진입 전에 거래소 위험 한도(그 크기의 유지증거금률)로 청산가를 어림해, 손절이 청산가보다 0.2% 넘게 가깝지 않으면 진입하지 않고 알림 (손절은 옮기지 않음)`
- `순ROE 비용: WOO X Pro 테이커 0.042% + 슬리피지 0.02% (한쪽), 왕복 0.124%, 펀딩은 계산에 넣지 않음`
- `신호등: 꺼짐 (paper의 모든 진입을 따라감)`
- `이름: WOO X Pro 2 (알림 머리말 [WOO X Pro 2 실거래 실행기])`
- `잔고 바닥: 켜짐 - …70%에 닿으면 새 진입 멈춤 …`, `원금 회수 안내: 켜짐 - …`
- 마지막 줄 **`준비됨`**

### 7-7. 시작 전 점검 · 켜기 (월요일 첫 신호 전, 친구 매매법 페이퍼가 돌고 있을 때)

```bash
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh --keys wooxpro2 executor preflight --config /etc/paperbot/executor-wooxpro2.json
```

- 끝 줄이 `관문 모두 통과(주문은 하지 않았습니다)`여야 합니다. 볼 줄: `키: 이 실행기 자기 키(다른 거래소 키 없음, 다른 실행기 DB의 키
  아님 …)`, `선물 지갑 $…`(친구 잔고), `paper3.db 계좌 COMBO@mix 읽기`(친구 매매법 기록).

켜기:

```bash
sudo systemctl start paperbot-executor-wooxpro2
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-wooxpro2-live.db
```

- 텔레그램에 `[WOO X Pro 2 실거래 실행기] 시작 금액 기록: 이 계정의 잔고 $… .` 이 옵니다. **이 금액이 친구 잔고인지 한 번 더
  봅니다.**
- `status`의 `포지션: null`, `잔고 바닥: 시작 금액 $…, 70% = $…에 닿으면 새 진입 멈춤 (아직 아님)`.
- 며칠 괜찮으면 서버를 다시 켜도 같이 켜지게 `sudo systemctl enable paperbot-executor-wooxpro2`.
- 실거래 사이트(8093)에 **WOO X Pro 2** 칸이 생기고, 따라가는 페이퍼가 "친구 매매법"으로 나옵니다. 아침 점검·텔레그램에도 WOO X Pro 2로
  나옵니다.

### 7-8. 잔고 바닥(70%)과 원금 회수 안내(2배)

- **시작 금액**: 실행기가 처음 돌 때의 잔고(열린 포지션 없을 때의 잔고)를 기록합니다. 입금·출금으로는 바뀌지 않습니다.
- **잔고 바닥**: 닫힌 거래 기준 잔고(열린 포지션의 평가손익은 빼고)가 시작 금액의 70% 이하가 되면:
  - 텔레그램에 🚨 `잔고 바닥: 잔고 $…가 시작 금액 $…의 70%($…)에 닿아 새 진입을 멈춥니다 …`가 **한 번** 옵니다(소리 나는 알림).
  - 그 뒤로 페이퍼가 진입해도 따라가지 않습니다(실거래 사이트에 "잔고 바닥 멈춤(새 진입 없음) 동안이라 따라가지 않았어요").
  - **열린 포지션은 닫지 않습니다.** 거래소에 걸린 손절과 계단 익절이 그대로 지킵니다.
  - 실행기를 다시 켜도 멈춤은 그대로입니다. `status`, `preflight`, 아침 점검에 "잔고 바닥 멈춤 중"으로 나옵니다.
  - 숫자: 손절 한 번이 잔고의 약 20%(증거금 40% × 순ROE −50%)라, 사이에 이긴 거래가 없으면 손절 1번 약 80%, **2번이면 약 64%로
    바닥 아래**라 멈춥니다(시작 금액의 −36%). 이긴 거래가 사이에 있으면 그만큼 늦어집니다. 손절 세 번까지 버티게 하려면 `0.55`
    (3번이면 약 51%)로 바꾸는 방법이 있습니다. 정하시면 알려 주세요(지금 설정은 두 분이 정한 70%).
- **원금 회수 안내**: 잔고가 시작 금액의 2배가 되면 💰 `원금 회수 안내: 잔고 $…가 시작 금액 $…의 2배가 됐어요. 원금을 빼실지
  정하세요`가 한 번 옵니다. 실행기는 그대로 거래합니다. 원금을 빼도 바닥 기준(처음 시작 금액의 70%)은 그대로입니다.
- **다시 시작하기**(바닥에서 계속하기로 정했을 때, 또는 입출금 뒤 기준을 새로 잡을 때): 포지션이 없을 때 실행기를 끄고, 기록을 지우고,
  켭니다. 다음에 켤 때의 잔고가 새 시작 금액이 됩니다(2배 안내도 그 금액 기준으로 다시).

```bash
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-wooxpro2-live.db
sudo systemctl stop paperbot-executor-wooxpro2
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor clear-floor --config /etc/paperbot/executor-wooxpro2.json --by 이름 --note "이유"
sudo systemctl start paperbot-executor-wooxpro2
```

- 첫 줄의 `포지션: null`을 보고 나서 끕니다.
- 잔고 바닥을 끄려면 설정의 `"equity_floor_frac"`을 `null`로, 2배 안내를 끄려면 `"double_notice"`를 `false`로 바꾸고 다시 켭니다.

### 7-9. 키가 섞이지 않게 (자동으로 막는 것)

WOO X Pro API에는 계정 번호를 알려 주는 기능이 없습니다. 그래서 실행기는 **키**로 계정을 구별합니다(키 값은 어디에도 적거나 보내지 않고,
키에서 만든 짧은 지문만 기록 파일에 남깁니다):
- WOO X Pro 2 실행기는 처음 켤 때의 키에 자기 기록 파일을 묶습니다. 다른 키로 켜면 켜지지 않습니다.
- WOO X Pro 2의 키가 두 분 WOO X Pro 실행기가 쓰는 키와 같으면 켜지지 않습니다. 이 확인은 두 분 WOO X Pro 실행기가 **새 코드로 한 번
  켜진 뒤부터** 됩니다(그때 그 키의 지문이 기록됩니다. `install.sh` 뒤 포지션 없을 때 다시 켜는 그 한 번). 그 전에는 7-4의 잔고 확인이
  그 역할을 합니다.
- 거꾸로 두 분 WOO X Pro 실행기가 친구 키로 켜지려 하면(executor.env에 친구 키를 잘못 넣은 경우) 그것도 켜지지 않습니다. WOO X Pro 2가
  한 번 켜져서 친구 키에 묶인 뒤부터입니다.
- WOO X Pro 2 키 파일에 다른 거래소 키가 있으면 켜지지 않습니다.
- 막히면 텔레그램에 🚨 `[WOO X Pro 2 실거래 실행기] 실행기를 시작하지 않습니다(키가 섞임, 주문 없음): …`가 오고, 주문은 하나도 나가지
  않습니다. 열린 포지션이 있으면 거래소 손절이 지킵니다. 키 파일을 고친 뒤 다시 켭니다.

친구가 **새 키**를 만들었을 때(같은 계정): 포지션이 없을 때 끄고 → 7-3으로 키 파일을 고치고 → 7-4 `check`의 잔고로 친구 계정인지
확인하고 → 묶음을 풀고 → 켭니다(켤 때 새 키에 다시 묶입니다):

```bash
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor untie-key --config /etc/paperbot/executor-wooxpro2.json --by 이름 --note "새 키, 잔고 확인함"
sudo systemctl start paperbot-executor-wooxpro2
```

### 7-10. 끄기 · 비상 정지

- 끄기는 **친구 계정 포지션이 없을 때만**: `status`의 `포지션: null`을 보고 `sudo systemctl stop paperbot-executor-wooxpro2`.
  (포지션이 있을 때 끄면 그 포지션은 거래소 손절만 지키고, 계단 익절·페이퍼 따라가기는 다시 켤 때까지 멈춥니다.)
- 비상 정지는 그대로 `sudo touch /var/lib/paperbot/STOP` 하나로 **네 실행기가 모두** 포지션을 닫고 멈춥니다(바이비트·WOO X Pro·딥코인·
  WOO X Pro 2). 다시 켜는 법은 다른 실행기와 같습니다(파일 지우기 → 실행기 끄기 → clear-halt).
- 기록 파일 `executor-wooxpro2-live.db`는 매일 밤 백업과 외부 백업에 같이 들어갑니다.
- 메시지 미리 보기: `cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.livecheck preview --wooxpro2`
  (보내지 않음).
