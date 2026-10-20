# MEXC로 실행기 돌리기, 바이비트와 같이 돌리기 (두 분용)

작성 2026-10-18. 내일(10/19) 아침 두 봇을 같이 켭니다.

- **바이비트 $100** 과 **MEXC $100**. 둘 다 같은 paper 계좌 `COMBO@mix`(합친 봇)를 따라갑니다.
- 실행기 프로그램은 하나입니다. 설정에 `"exchange": "mexc"`를 넣으면 MEXC에서 주문합니다.
- MEXC에는 **선물 테스트넷이 없습니다.** 그래서 처음부터 실거래입니다. 대신 아주 작은 연습(4장)을 먼저 합니다.
- 거래 대상: USDT 무기한 선물. 코인 이름은 같습니다(BTCUSDT …). MEXC 안에서는 `BTC_USDT`로 바꿔 보냅니다.
- 손절은 MEXC에 걸어 둡니다(조건 주문, 마지막 체결가 기준). 실행기가 꺼져도 손절은 남습니다.
- 잠금이 올라가면 새 손절을 먼저 걸고, 걸린 것을 확인한 뒤 옛 손절을 지웁니다(빈틈 없음).
- 손익은 MEXC 체결 기록으로 계산합니다(수수료, 펀딩 포함).
- MEXC는 2026-03-31부터 KYC 인증 계정에 API 선물 주문을 열었습니다.
- **API 수수료는 앱과 다릅니다.** MEXC 공지(Updates to API Futures Trading Fees, 2026-06-01)에 따르면 API로 낸 선물 주문은 **메이커 0.06%, 테이커 0.08%** 입니다. 앱·웹의 0% 이벤트, MX 할인은 API 주문에 적용되지 않습니다. (예전 공지의 메이커 0.01%·테이커 0.05%는 지난 숫자입니다.)
  - 이 서버에서는 mexc.com이 막혀 있어서 공지 원문을 직접 열어 보지 못했습니다(검색 결과로 확인). 그래서 연습 주문(4장) 결과의 마지막 줄 `fee_rate_pct`로 실제로 낸 수수료율을 확인합니다. 0.08 근처면 공지대로이고, 0.05 이하면 백테스트 가정보다 싸거나 같습니다.
  - 백테스트는 테이커 0.05%를 가정했습니다. 0.08%면 40배에서 거래마다 ROE가 약 2.4%포인트, 30배에서 약 1.8%포인트 더 나갑니다. 숫자는 `docs/live1019-start-ko.md`의 "거래소 수수료" 표에 있습니다.

## 1. 계정 준비 (MEXC 앱 또는 웹)

1. **KYC 인증**을 끝냅니다. KYC가 없으면 API로 선물 주문이 안 됩니다.
2. 실행기용 돈은 **선물(Futures) 지갑에 $100 USDT만** 둡니다.
   - USDT 말고 다른 코인이 선물 지갑에 있으면 실행기가 켜지지 않습니다(금액 상한 확인은 10/19에 없앰).
   - 현물 지갑의 돈은 상관없습니다. 키에 이체 권한이 없으니 실행기는 현물 돈을 옮길 수 없습니다.
   - 하위 계정(sub-account)을 쓸 수 있으면 하위 계정이 더 좋습니다.
3. **보너스·체험금**이 선물 지갑에 있으면 실행기가 켜지지 않습니다. 보너스가 없는 계정을 씁니다.
4. **MX로 수수료 내기(수수료 할인)** 는 끕니다. 수수료가 MX로 나가면 손익 계산이 틀어집니다.
5. 포지션 모드는 **단방향(One-way)** 이어야 합니다. 연습(4장)이 포지션·주문이 없을 때 맞춰 줍니다.

## 2. API 키 만들기

키 값은 **채팅·저장소·메신저에 절대 붙이지 마세요.** 서버 파일에만 넣습니다(3장).

1. MEXC → 프로필 → **API 관리** → 새 키 만들기.
2. 권한
   - 켤 것: **선물(Futures/Contract)의 보기와 거래(주문)만.**
   - 끌 것: **출금(Withdraw)**, 이체(Transfer), 현물(Spot) 거래, 그 밖의 모든 권한.
3. **IP 제한: 서버 IP만 (158.247.200.152).**
4. 만든 뒤 키 목록에서 한 번 더 봅니다: 출금이 꺼져 있고, IP가 서버 하나뿐인지.

**MEXC는 키 권한을 API로 알려 주지 않습니다.** 바이비트처럼 실행기가 출금·IP 설정을 직접 확인할 수 없습니다.
실행기가 확인하는 것은 "이 키로 선물 계정을 읽을 수 있다"와 "포지션 모드를 읽을 수 있다(거래 권한)"까지입니다.
그래서 두 분이 4번을 확인한 뒤, 확인했다는 문구를 키 파일에 직접 넣습니다(3장). 이 문구가 없으면 실행기가 켜지지 않습니다.

## 3. 키 넣기

```bash
cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh
sudo nano /etc/paperbot/executor.env
```

아래 세 줄을 채웁니다. 줄이 없으면 `deploy/executor.env.example`의 MEXC 세 줄을 그대로 추가합니다.

```
MEXC_LIVE_KEY=(MEXC 키)
MEXC_LIVE_SECRET=(MEXC 비밀키)
MEXC_LIVE_KEY_CHECKED=FUTURES_ONLY_NO_WITHDRAW_IP_BOUND
```

- 마지막 줄은 "선물 거래만, 출금 없음, 서버 IP만으로 만든 것을 확인했다"는 뜻입니다. 확인한 뒤에만 넣으세요.
- 실거래 스위치 `PAPERBOT_LIVE_MAINNET=I_UNDERSTAND` 도 있어야 합니다(바이비트 실거래와 같은 줄).
- 저장: Ctrl+O → Enter → Ctrl+X.
- 키는 거래소마다 달라야 합니다. MEXC 키가 바이비트·바이낸스·paper 키와 같으면 실행기가 거부합니다.

## 4. 연습 (drill): 꼭 이 순서로

실행기를 켜기 **전에** 합니다. MEXC 선물 계정에 포지션·주문이 없어야 합니다.

### 4-1. 계약 정보 보기 (주문 없음)

```bash
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh mexc specs
```

6개 코인(BTC ETH SOL DOGE LTC BCH)의 1계약 크기, 최소 계약 수, 가격 단위, 최대 배수가 나옵니다.
MEXC는 수량을 "계약"으로 셉니다. 실행기가 이 값을 MEXC에서 직접 읽어 코인 수량으로 바꿉니다.

### 4-2. 읽기 점검 + 설정 (주문 없음)

```bash
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh mexc drill
```

1분 안쪽입니다. 이것만 합니다(주문은 하나도 하지 않습니다):

1. 서버 시간 차이 1초 미만
2. 6개 코인 계약 정보 (상태 0 = 거래 중, 격리 마진 가능)
3. 선물 계정 읽기 (자산, 보너스, 포지션)
4. 열린 주문·조건 주문 목록 읽기
5. 포지션 모드 단방향 (아니면 바꿈)
6. 격리 레버리지: **BTC 40배, 나머지 30배** (다시 읽어 확인)
7. 키 확인 (선물 계정·포지션 모드 읽기, 3장의 확인 문구)

모두 `[OK]` 여야 합니다. 마지막 줄은 "주문 단계 건너뜀"입니다.

### 4-3. 진짜 주문 한 번 (가장 작은 수량)

```bash
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh mexc drill --confirm-order REAL_ORDER
```

4-2를 다시 한 뒤, **한 코인에서 가장 작은 수량(1계약)** 으로 한 번 사고팝니다.
코인은 최소 주문 금액이 가장 싼 것을 고릅니다(보통 몇 달러). 다른 코인은 `--symbol BTCUSDT`처럼 고릅니다.
수수료는 몇 센트입니다. 펀딩 정산 시각(한국 시간 오전 9시, 오후 5시, 새벽 1시) 바로 전후에는 하지 마세요.

1. 시작 전 그 코인에 포지션·주문·조건 주문 없음
2. 시장가 진입 체결
3. 진입 주문을 우리 주문 번호(externalOid)로 찾음 (응답이 끊겨도 두 번 사지 않는 장치)
4. 포지션 크기 일치 (계약 수 × 1계약 크기)
5. 평가액(equity)이 진입 때 증거금만큼 줄지 않음 (하루 손실 한도가 이 값을 봅니다)
6. 손절이 MEXC에 걸림 (청산 방향 조건 주문, 마지막 가격 기준, 시장가)
7. 손절 옮기기: 새 손절 → 확인 → 옛 손절 취소 (빈틈 없음)
8. 줄이기 전용 시장가로 청산
9. 포지션 없음, 주문·조건 주문 없음
10. 체결로 계산한 손익 = 체결 가격으로 계산한 값 = MEXC의 profit 기록 = 지갑 변화(수수료 포함)

**모두 `[OK]`** 여야 실행기를 켭니다. 하나라도 `[FAIL]`이면 다음으로 가지 말고 **출력 전체**를 보내 주세요(키 값은 빼고).
실패해도 실행기가 그 코인의 포지션과 주문을 정리하고 끝납니다. 그래도 MEXC 앱에서 포지션·조건 주문이 없는지 한 번 보세요.

**잘 안 될 때 (출력을 보내 주시면 같이 봅니다)**

- 2번에서 시장가 주문이 거절됨: `--market-type 6` 을 붙여 다시 해 보세요. 되면 설정에 `"mexc_market_type": 6` 을 넣습니다.
- 연결이 안 됨: `--host contract.mexc.com` 을 붙여 보세요. 되면 설정에 `"mexc_host": "contract.mexc.com"` 을 넣습니다.

## 5. MEXC 실행기 설정

```bash
sudo nano /etc/paperbot/executor-mexc.json
```

```json
{
  "exchange": "mexc",
  "mode": "mainnet",
  "account": "COMBO@mix",
  "paper_db": "/var/lib/paperbot/combo/research16.db",
  "db": "/var/lib/paperbot/exec/executor-mexc.db",
  "budget_usd": 100,
  "qty_scale": 0.1,
  "entry_source": "paper",
  "stop_from": "ratio",
  "risk": {
    "max_drawdown_pct": 0.5,
    "max_consecutive_losses": 3,
    "max_leverage": 40,
    "max_notional_usd": 10000,
    "max_loss_frac": 0.35,
    "allowed_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"],
    "kill_file": "/var/lib/paperbot/STOP"
  }
}
```

| 설정 | 뜻 |
|---|---|
| `exchange` | `"mexc"` |
| `mode` | `"mainnet"`만 됩니다(테스트넷 없음) |
| `paper_db` | 바이비트 설정과 **같은 파일**. 읽기만 합니다 |
| `db` | **MEXC 전용 새 파일**. 다른 거래소 DB를 쓰면 거부합니다 |
| `qty_scale` | 0.1 = $100 ÷ 페이퍼 $1,000 |
| `kill_file` | 바이비트와 같은 파일. 이 파일 하나로 두 봇이 모두 멈춥니다 |

확인 (둘 다 주문 없음):

```bash
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor-mexc.json
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh executor preflight --config /etc/paperbot/executor-mexc.json
```

- check-config 마지막 줄: **"준비됨"**
- preflight 마지막 줄: **"관문 모두 통과(주문은 하지 않았습니다)"**
- preflight의 `[주의]` 한 줄("MEXC는 키 권한을 API로 알려 주지 않습니다…")은 정상입니다. 알림은 처음 켤 때 한 번만 옵니다(그 뒤로 켤 때는 실행기 기록에만 남김).

## 6. 두 봇 같이 돌리기 (바이비트 $100 + MEXC $100)

| | 바이비트 | MEXC |
|---|---|---|
| 서비스 | `paperbot-executor` | `paperbot-executor-mexc` |
| 설정 파일 | `/etc/paperbot/executor.json` (`"exchange": "bybit"`, `"mode": "mainnet"`) | `/etc/paperbot/executor-mexc.json` |
| 실행기 DB | `/var/lib/paperbot/exec/executor-bybit.db` | `/var/lib/paperbot/exec/executor-mexc.db` |
| paper DB | `/var/lib/paperbot/combo/research16.db` | **같은 파일** |
| 키 | `BYBIT_LIVE_API_KEY/SECRET` | `MEXC_LIVE_KEY/SECRET` |
| 알림 앞머리 | [바이비트 실거래 실행기] | [MEXC 실거래 실행기] |

- 키 파일 `/etc/paperbot/executor.env`는 하나입니다. 두 봇이 같은 파일에서 자기 키만 씁니다.
- 바이비트 설정과 키는 [`bybit-ko.md`](bybit-ko.md) 7장 그대로입니다.
- 두 봇은 서로 모릅니다. 한도(연속 손실 3번, 낙폭 50% 등)도 봇마다 따로 셉니다.
- 같은 paper 진입을 따라가도 체결 가격·수량은 조금 다릅니다. 거래소마다 주문 단위가 다르기 때문입니다.

켜기:

```bash
sudo systemctl start paperbot-executor          # 바이비트
sudo systemctl start paperbot-executor-mexc     # MEXC
sudo journalctl -fu paperbot-executor-mexc
```

상태 보기 (읽기만):

```bash
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-mexc.db
```

며칠 문제없으면 부팅 때 자동으로 켜지게 합니다: `sudo systemctl enable paperbot-executor-mexc`

| 하고 싶은 것 | 명령 | 포지션 |
|---|---|---|
| MEXC만 잠깐 끄기 | `sudo systemctl stop paperbot-executor-mexc` | 남음. MEXC 손절이 지킴 |
| 두 봇 모두 닫고 멈추기 | `sudo touch /var/lib/paperbot/STOP` | 두 실행기가 시장가로 닫음 |
| 멈춤 풀기 | STOP 파일 지우고, 그 실행기를 끈 뒤 `clear-halt --config /etc/paperbot/executor-mexc.json` ([`live-safety.md`](live-safety.md)) | |

## 7. 첫 거래 뒤 확인할 것

첫 거래는 두 분이 텔레그램과 MEXC 앱을 같이 보세요.

**진입했을 때**

- ☐ 텔레그램 "[MEXC 실거래 실행기] 진입 …" 알림
- ☐ MEXC 앱 포지션: **격리(Isolated)**, 배수가 paper와 같음(BTC 40배, 나머지 30배)
- ☐ MEXC 앱 조건 주문(트리거 주문): **청산 방향 한 개**, 가격 = 실행기가 알린 손절, 수량 = 포지션 전체
- ☐ 잠금이 올라가면 새 조건 주문이 생기고 옛 것은 없어짐 (조건 주문은 늘 한 개)

**청산한 뒤**

- ☐ MEXC 앱에 포지션도 조건 주문도 없음
- ☐ 텔레그램 청산 알림의 손익 ≈ MEXC 앱의 실현 손익(수수료 포함)
- ☐ 거래 기록의 손익 출처가 `fills`

```bash
sudo -u paperbot-exec sqlite3 -readonly /var/lib/paperbot/exec/executor-mexc.db "SELECT datetime(entry_ts/1000,'unixepoch','+9 hours'), symbol, exit_reason, round(pnl,2), pnl_source FROM trades ORDER BY entry_ts DESC LIMIT 10"
```

- ☐ "거래소 기록(MEXC 체결 profit)과 다릅니다" 알림이 오지 않음. 오면 알려 주세요(그 거래는 지갑 변화로 손익을 잡습니다).
- ☐ 설명 안 되는 `loop_error` 알림이 계속 오지 않음

## 8. 바이비트와 다른 점 (알고 계시면 되는 것)

- **테스트넷이 없습니다.** 연습은 진짜 돈 1계약으로 합니다(4-3).
- **키 권한을 실행기가 직접 볼 수 없습니다.** 출금·IP 설정은 두 분 확인 문구(3장)로 대신합니다.
- **수량이 계약 단위입니다.** 예: BTC 1계약 = 0.0001 BTC (MEXC에서 읽은 값을 씁니다).
- **격리 마진은 주문마다 정합니다.** 실행기의 모든 주문은 격리로 나갑니다. 시작할 때 코인마다 격리 배수(BTC 40, 나머지 30)를 맞춥니다.
- **손절 조건 주문은 7일이 지나면 MEXC가 지웁니다.** 실행기가 6일째에 같은 가격으로 새로 걸고 옛 것을 지웁니다("손절 갱신", 알림 없음).
  실행기가 7일 넘게 꺼져 있었다면 손절이 없을 수 있습니다. 다시 켜면 실행기가 바로 다시 겁니다.
- **청산 방향 주문만 씁니다.** 손절과 청산은 "롱 청산/숏 청산" 주문이라 새 포지션을 열 수 없습니다.
- **빠른 진입(signal)** 은 MEXC에서 쓰지 않습니다. 합친 봇은 원래 `paper`라 상관없습니다.
- **요청 한도**: 2초에 20번(주소마다). 실행기가 알아서 늦춥니다. MEXC가 IP를 막으면(HTTP 403) 실행기는 5분 쉬고, 그동안 MEXC 손절이 지킵니다.

## 9. 아직 확인 못 한 것 (연습이 확인합니다)

MEXC 서버에 이 컴퓨터에서 접속할 수 없어, 아래는 공식 문서와 ccxt(널리 쓰는 거래소 라이브러리) 코드로만 맞췄습니다.
4-2, 4-3 연습이 하나씩 확인합니다. 연습 출력 전체를 보내 주시면 같이 봅니다.

| 확인할 것 | 연습 단계 |
|---|---|
| 주소 api.mexc.com 이 계약 API를 받는지 (안 되면 contract.mexc.com) | 4-2 1~3 |
| 서명 방식이 맞는지 (틀리면 602 오류) | 4-2 3 |
| 계약 정보의 단위 (contractSize, minVol, volUnit, priceUnit) | 4-1, 4-2 2 |
| 자산 응답의 equity가 포지션 증거금을 포함하는지 | 4-3 5, 10 (지갑 변화) |
| 빈 포지션 목록이 `[]`로 오는지 | 4-2 3 |
| 포지션 모드 바꾸기, 격리 배수 맞추기와 다시 읽기 | 4-2 5, 6 |
| 시장가 주문 종류 5가 API에서 되는지 (안 되면 6) | 4-3 2 |
| 우리 주문 번호(externalOid)로 주문을 찾을 수 있는지 | 4-3 3 |
| 청산 방향 조건 주문(트리거 주문)이 받아지고, 목록에 보이는지 | 4-3 6 |
| 조건 주문 취소가 되는지 | 4-3 7, 9 |
| 청산 방향 시장가(롱 청산 = 4)가 되는지 | 4-3 8 |
| 체결 기록(order_deals)의 방향·수량·수수료 부호, profit 값 | 4-3 10 |
| 이미 지난 가격의 손절을 MEXC가 거절하는지, 바로 발동하는지 | 실행기는 둘 다 처리합니다(시험 완료) |
| 같은 externalOid를 다시 보내면 MEXC가 어떻게 답하는지 | 실행기는 진입 주문을 절대 다시 보내지 않습니다(시험 완료) |
| 조건 주문이 발동하면 목록의 orderId로 그 시장가 주문을 알려 주는지 | 첫 손절 발동 때 (7장) |
| 펀딩 기록(+ 받음 / − 냄)과 이체 기록 | 첫 펀딩 정산 뒤 거래 기록 |
| 1분봉(kline) 응답의 모양과 시간 단위(초) — 거래소 기준 익절(`docs/live15-own-ladder-ko.md`)이 최고가를 읽는 곳 | 첫 포지션 때 status의 `"src": "kline"`. 못 읽으면 "1분봉을 못 읽어" 경고가 오고, 그동안은 지금 가격으로 판단합니다 |
