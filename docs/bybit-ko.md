# 바이비트(Bybit)로 실행기 돌리기 (두 분용)

작성 2026-10-18. 두 분이 거래소를 바이비트로 정했습니다. 실행기는 그대로이고, 설정에 `"exchange": "bybit"` 한 줄을
넣으면 바이비트에서 주문합니다. 바이낸스 설정은 바뀌지 않습니다.

순서는 바이낸스 때와 같습니다. **테스트넷 연습 → 테스트넷으로 하루 이상 → 실거래 $100.**

- 거래 대상: USDT 무기한(바이비트 "linear"). 코인 이름은 바이낸스와 같습니다(BTCUSDT, ETHUSDT …).
- 손절은 바이비트에 걸어 둡니다(조건부 주문, 마지막 체결가 기준). 실행기가 꺼져도 손절은 남습니다.
- 잠금이 올라가면 새 손절을 먼저 걸고, 걸린 것을 확인한 뒤 옛 손절을 지웁니다(빈틈 없음).
- 손익은 바이비트 체결 기록으로 계산합니다(수수료, 펀딩 포함).

## 1. 키 만들기

키 값은 **채팅·저장소·메신저에 절대 붙이지 마세요.** 서버 파일에만 넣습니다(2장).

### 1-1. 테스트넷 키 (가짜 돈)

1. PC 브라우저로 https://testnet.bybit.com 에 들어가 가입합니다. 실계정과 따로입니다.
2. 테스트넷 자산 화면에서 시험용 USDT를 받습니다(메뉴 이름은 바뀔 수 있습니다).
3. 프로필 → API → 새 키 만들기.
   - 키 종류: **시스템 생성(System-generated)**
   - 권한: **읽기·쓰기(Read-Write)**
   - IP 제한: **서버 IP만 (158.247.200.152)**. IP를 묶지 않은 키는 몇 달 뒤 만료될 수 있습니다.
   - 켤 것: **계약(Contract) 또는 통합 거래(Unified Trading)의 주문(Orders)·포지션(Positions)만.**
   - 끌 것: 출금, 이체, 현물(Spot), 옵션, Earn, 환전(Exchange).

### 1-2. 실거래 키 (진짜 돈)

1. 바이비트 실계정에서 **실행기 전용 하위 계정(sub-account)** 을 만듭니다. 주 계정은 쓰지 않습니다.
2. 하위 계정은 통합 거래 계정(UTA)이면 됩니다(요즘 기본).
3. 하위 계정에 **$100 USDT만** 옮깁니다. $120을 넘거나 USDT 말고 다른 코인이 있으면 실행기가 켜지지 않습니다.
4. 하위 계정에서 키를 만듭니다. 설정은 1-1과 같습니다.
   - 읽기·쓰기, 서버 IP만, 계약 주문·포지션만.
   - **출금·이체·현물·옵션·Earn·환전은 끕니다.** 켜져 있으면 실행기가 거부합니다.
5. 실행기는 처음 켤 때 이 하위 계정을 **격리 마진(Isolated Margin)** 으로 바꿉니다. 바이비트에서는 계정 전체 설정입니다.
   그래서 전용 하위 계정을 씁니다. 바꿀 때 포지션·주문이 없어야 합니다.
6. 포지션 모드는 단방향(One-way)이어야 합니다. 실행기가 켤 때 맞춥니다.

## 2. 키 넣기

바이낸스 키와 같은 파일입니다. root만 읽을 수 있습니다.

```bash
cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh
sudo nano /etc/paperbot/executor.env
```

- 테스트넷: `BYBIT_TESTNET_API_KEY=`, `BYBIT_TESTNET_API_SECRET=` 뒤에 값을 붙입니다.
- 실거래 키(`BYBIT_LIVE_API_KEY`, `BYBIT_LIVE_API_SECRET`)와 `PAPERBOT_LIVE_MAINNET`은 **아직 비워 둡니다.**
- 줄이 없으면 `deploy/executor.env.example`의 BYBIT 네 줄을 그대로 추가합니다.
- 저장: Ctrl+O → Enter → Ctrl+X.

같은 키를 두 곳에 쓰면 실행기가 거부합니다(바이낸스 키, paper 키, 테스트넷·실거래 키는 모두 달라야 합니다).

## 3. 실행기 설정 (테스트넷)

합친 봇 계좌 `COMBO@mix`를 따라갑니다. 페이퍼 DB는 5년 탐색 봇 16개 설정(`research16.db`)입니다.
숫자는 두 분이 10/17에 정한 "시드 40%"와 같습니다([`combo-bot-ko.md`](combo-bot-ko.md) 6장).

```bash
sudo nano /etc/paperbot/executor.json
```

```json
{
  "exchange": "bybit",
  "mode": "testnet",
  "account": "COMBO@mix",
  "paper_db": "/var/lib/paperbot/combo/research16.db",
  "db": "/var/lib/paperbot/exec/executor-bybit-testnet.db",
  "budget_usd": 100,
  "qty_scale": 0.1,
  "entry_source": "paper",
  "stop_from": "ratio",
  "risk": {
    "daily_max_loss_usd": 40,
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
| `exchange` | `"bybit"`. 없으면 바이낸스입니다 |
| `db` | **새 파일**. 바이낸스 실행기 DB를 쓰면 거부됩니다 |
| `qty_scale` | 0.1 = $100 ÷ 페이퍼 $1,000 |
| `max_leverage` | 40. 페이퍼가 BTC 40배, 알트 30배로 들어가면 그대로 씁니다 |
| `entry_source` | `paper`. 합친 봇에서는 signal을 쓰지 않습니다 |

확인:
```bash
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor.json
```
마지막 줄이 **"준비됨"** 이어야 합니다.

## 4. 연습 (drill)

실행기가 꺼진 상태에서 합니다. 테스트넷 계정에 BTC 포지션·주문이 없어야 합니다.

```bash
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh bybit specs
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh bybit drill --symbol BTCUSDT --side long
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh bybit drill --symbol BTCUSDT --side short
```

`specs`는 주문 없이 6개 코인의 주문 단위·최소 금액·최대 배수를 바이비트에서 읽어 보여 줍니다.

연습은 1분 안쪽입니다. **두 번 모두 11줄 전부 `[OK]`** 여야 합니다. 펀딩 정산 시각(한국 시간 오전 9시, 오후 5시, 새벽 1시) 바로 전후에는 하지 마세요(11번 비교에 펀딩이 끼어듭니다).

1. 시작 전 포지션·주문 없음
2. 격리 마진, 레버리지 40배 (다시 읽어 확인)
3. 시장가 진입 체결
4. 진입 주문을 우리 주문 번호(orderLinkId)로 찾음 (응답이 끊겨도 두 번 사지 않는 장치)
5. 포지션 크기 일치
6. 손절이 바이비트에 걸림 (마지막 체결가 기준, 줄이기 전용)
7. 손절을 옮길 때 빈틈 없음 (새 손절 → 옛 손절 취소)
8. 손절을 일부러 지우면 다시 걸어 놓음
9. 이미 지난 가격의 손절은 거절되고 시장가로 닫음
10. 끝나고 포지션·주문 없음
11. 체결 기록으로 계산한 손익 = 바이비트 "Closed P&L" 기록 (실현 손익, 수수료, 순손익)

하나라도 `[FAIL]`이면 다음으로 가지 말고 **출력 전체**를 보내 주세요(키 값은 빼고). 실패해도 계정은 비우고 끝납니다.

## 5. 관문 점검 (주문 없음)

```bash
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh executor preflight --config /etc/paperbot/executor.json
```
마지막 줄이 **"관문 모두 통과(주문은 하지 않았습니다)"** 여야 합니다.

## 6. 테스트넷으로 하루 이상 돌리기

```bash
sudo systemctl start paperbot-executor
sudo journalctl -fu paperbot-executor
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-bybit-testnet.db
```

텔레그램 알림 앞머리는 **"[바이비트 테스트넷 실행기]"** 입니다.

**포지션이 열려 있을 때 일부러 해 볼 것**

| 해 볼 것 | 기대하는 결과 |
|---|---|
| 바이비트 화면에서 손절(조건부 주문) 취소 | 몇 초 안에 다시 걸리고 알림 |
| 바이비트 화면에서 다른 코인 포지션을 손으로 열기 | 바로 닫히고 "모르는 포지션" 알림 |
| `sudo systemctl restart paperbot-executor` | 포지션과 손절을 이어받음 |
| `sudo touch /var/lib/paperbot/STOP` | 모두 닫고 "거래를 멈춥니다", 다시 켜도 멈춤 |
| 테스트넷 지갑에 USDT를 조금 넣거나 빼기 | "선물 지갑 입금/출금" 알림. 손실로 세지 않음 |

**실거래 전에 꼭 확인할 것 (모두 "예"여야 합니다)**

- ☐ 연습 롱·숏 모두 11줄 `[OK]`
- ☐ 거래 기록의 손익 출처가 `fills`
- ☐ 끝난 거래의 손익이 바이비트 화면의 Closed P&L과 같음 (실행기 손익은 펀딩을 포함합니다. 펀딩이 있던 거래는 차이가 0이거나 펀딩 금액과 같아야 합니다. 어느 쪽인지 알려 주세요)
- ☐ 펀딩이 있었던 거래: 받은 펀딩은 +, 낸 펀딩은 −로 기록됨
- ☐ 거래소 손절이 실제로 발동한 거래가 "거래소 손절(또는 잠금) 발동"으로 기록됨
- ☐ 설명 안 되는 `loop_error`가 계속 나오지 않음
- ☐ 텔레그램 알림이 두 분 폰에 모두 옴

거래 기록 보기(읽기만):
```bash
sudo -u paperbot-exec sqlite3 -readonly /var/lib/paperbot/exec/executor-bybit-testnet.db "SELECT datetime(entry_ts/1000,'unixepoch','+9 hours'), symbol, exit_reason, round(pnl,2), pnl_source FROM trades ORDER BY entry_ts DESC LIMIT 10"
```

## 7. 실거래 $100 켜기

1. 테스트넷 실행기를 끕니다: `sudo systemctl stop paperbot-executor`
2. 키 넣기 (`sudo nano /etc/paperbot/executor.env`):
   ```
   BYBIT_LIVE_API_KEY=(하위 계정 키)
   BYBIT_LIVE_API_SECRET=(하위 계정 비밀키)
   PAPERBOT_LIVE_MAINNET=I_UNDERSTAND
   ```
3. 설정에서 세 가지만 바꿉니다:
   - `"mode": "mainnet"`
   - `"db": "/var/lib/paperbot/exec/executor-bybit.db"` (새 파일)
   - `"budget_usd": 100` (이미 있음)
4. 관문 점검(5장 명령). 다음이 모두 `[OK]`여야 합니다.
   - 주소 api.bybit.com (mainnet)
   - 키 권한: 출금 꺼짐, 선물 켜짐, IP 제한 있음, 필요 없는 권한 꺼짐
   - 지갑 $120 이하, USDT만
5. 켜기: `sudo systemctl start paperbot-executor`. 첫 거래는 두 분이 화면과 바이비트 앱으로 같이 봅니다:
   진입, 손절이 걸림, 잠금 이동, 청산, 손익이 앱과 같음.
6. 며칠 문제없으면: `sudo systemctl enable paperbot-executor`

api.bybit.com이 서버에서 잘 안 되면 설정에 `"bybit_host": "api.bytick.com"`을 넣을 수 있습니다(바이비트 공식 대체 주소).
다른 주소는 실행기가 거부합니다.

## 8. 바이낸스와 다른 점 (알고 계시면 되는 것)

- **격리 마진은 계정 전체 설정입니다.** 그래서 실행기 전용 하위 계정을 씁니다. 격리로 못 바꾸면 새 진입을 하지 않습니다.
- **주문 접수가 비동기입니다.** 시장가 주문을 낸 뒤 체결 결과를 다시 읽습니다. 손절을 걸기까지 한 번 더 읽는 만큼(1초 안쪽) 늦습니다.
- **손절 수량**: 포지션보다 큰 손절은 포지션 크기의 새 손절로 바꿉니다(새 것 먼저, 옛 것 나중).
- **취소도 비동기입니다.** 지운 손절이 잠깐 목록에 남으면 다음 확인에서 한 번 더 지웁니다.
- **주문 단위가 다릅니다.** 예: ETH 최소 단위가 바이낸스 0.001, 바이비트 0.01. 실행기가 바이비트에서 직접 읽어 맞춥니다.
- **요청 한도**: 바이비트는 IP 요청이 너무 많으면 10분 이상 막습니다(HTTP 403). 실행기는 10분 기다리고, 그동안 거래소 손절이 지킵니다.
- **손익 계산**: 바이비트 체결 기록에는 실현 손익이 없습니다. "Closed P&L" 기록의 평균 진입가로 체결마다 계산합니다.
  기록이 늦으면 체결들로 다시 계산합니다.

## 9. 끄기와 비상 정지

바이낸스 때와 같습니다.

| 하고 싶은 것 | 명령 | 포지션 |
|---|---|---|
| 잠깐 끄기 | `sudo systemctl stop paperbot-executor` | 남음. 거래소 손절이 지킴 |
| 모두 닫고 멈추기 | `sudo touch /var/lib/paperbot/STOP` | 실행기가 시장가로 닫음 |
| 멈춤 풀기 | STOP 파일 지우고, 실행기를 끈 뒤 `clear-halt` ([`live-safety.md`](live-safety.md)) | |
