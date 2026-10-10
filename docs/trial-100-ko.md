# 10/19 $100 실거래 시험 준비: 테스트넷 연습부터 (두 분용)

작성 2026-10-10. 두 분 계획: 10/18까지 규칙봇 결과를 보고, 10/19부터 $100으로 "한번 돌려 보는" 실거래 시험. 규칙봇(paper)은
그대로 계속 돕니다. 자세한 원래 설명은 [`live-safety.md`](live-safety.md) 3장이고, 이 문서는 $100 시험에 맞춘 순서와 숫자만
모았습니다.

> 참고: 예전에 정한 규칙(Q3·Q6)은 "30일 판정 뒤, $500, 테스트넷 연습 뒤"였습니다. 10/19 시험은 30일 판정(11월 초)보다 빠르고
> 금액은 더 작습니다. 두 분이 정하신 대로 하되, **테스트넷 연습은 꼭 먼저** 합니다.

## 일정

| 날짜 | 할 일 | 걸리는 시간 |
|---|---|---|
| 10/11 (일) | 0~5번: 테스트넷 키 만들기, 설정, 연습(롱·숏), 관문 점검 | 30분~1시간 |
| 10/12 ~ 10/18 | 6번: 테스트넷으로 1주 돌려 보기, 첫날 일부러 문제 만들어 보기 | 하루 5분 확인 |
| 10/18 | 7번: 따라 할 계좌를 함께 고르기, 바이낸스 하위 계정·키 준비 | 30분 |
| 10/19 | 8번: 실거래 $100 켜기, 첫 거래를 같이 보기 | |

1주를 다 채우려면 **10/12까지는 6번을 시작**해야 합니다.

## 0. 먼저 확인: 테스트넷 키를 만들 수 있나

1. PC 브라우저에서 https://testnet.binancefuture.com 에 들어가 로그인합니다(바이낸스 실계정과 별개, 처음이면 가입).
2. 화면 아래쪽 **API Key** 칸에서 키를 만듭니다. 키와 비밀키를 메모장에 잠시 적어 둡니다(**채팅·저장소에 붙이지 마세요**).

바이낸스가 2025년부터 이 사이트를 줄이고 "Demo Trading"(demo.binance.com)으로 옮긴다는 이야기가 있습니다(확인 안 됨).
**사이트가 열리지 않거나, Demo Trading 화면으로 넘어가거나, 키를 만들 곳이 없으면** 여기서 멈추고 저에게 알려 주세요.
실행기가 지금은 testnet.binancefuture.com 주소만 허용해서, Demo Trading 주소를 쓰도록 실행기 쪽 코드를 고쳐야 합니다(실행기만
바뀌고 규칙봇 30일 계산에는 영향 없음, 하루 정도 걸림).

## 1. 서버 코드 올리기

```bash
cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh
```

텔레그램에 "ℹ️ 재시작 변경 · 코드 버전 (거래에는 영향 없음)"이 오면 정상입니다. 실행기는 **설치만** 되고 켜지지 않습니다.

## 2. 테스트넷 키 넣기

```bash
sudo nano /etc/paperbot/executor.env
```

- `TESTNET_API_KEY=`, `TESTNET_API_SECRET=` 뒤에 0번에서 만든 값을 붙입니다.
- 텔레그램 4줄(`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_CRITICAL`, `TELEGRAM_CHAT_WARN`, `TELEGRAM_CHAT_INFO`)은
  규칙봇과 같은 봇·방 값을 넣습니다.
- `LIVE_API_KEY`, `LIVE_API_SECRET`, `PAPERBOT_LIVE_MAINNET`은 **비워 둡니다.**
- 저장: Ctrl+O → Enter → Ctrl+X.

## 3. 실행기 설정 (테스트넷, $100 크기로)

```bash
sudo install -o root -g paperbot -m 640 /dev/null /etc/paperbot/executor.json    # 처음 한 번
sudo nano /etc/paperbot/executor.json
```

아래를 그대로 붙여 넣습니다. `account`는 테스트넷 1주 동안 따라 할 규칙봇 계좌입니다. 거래가 자주 나는 15분봉 계좌가
연습에 좋습니다. 대시보드 순위표에서 하나 고르면 되고, 실거래 계좌는 10/18에 따로 고릅니다.

```json
{
  "mode": "testnet",
  "account": "V45_AMB@15m",
  "paper_db": "/var/lib/paperbot/paper3.db",
  "db": "/var/lib/paperbot/exec/executor-testnet.db",
  "qty_scale": 0.02,
  "entry_source": "signal",
  "stop_from": "ratio",
  "risk": {
    "daily_max_loss_usd": 20,
    "max_drawdown_pct": 0.4,
    "max_consecutive_losses": 4,
    "max_leverage": 20,
    "max_notional_usd": 800,
    "allowed_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"],
    "kill_file": "/var/lib/paperbot/STOP"
  }
}
```

숫자의 뜻($100 기준, 두 분이 바꾸셔도 됩니다):

| 설정 | 값 | 뜻 |
|---|---|---|
| `qty_scale` | 0.02 | 규칙봇 계좌는 $5,000이라 $100 ÷ $5,000 = 0.02배 크기로 따라 함 |
| `daily_max_loss_usd` | 20 | 하루(오전 9시 기준) $20 잃으면 그날 멈춤 |
| `max_drawdown_pct` | 0.4 | 최고점에서 40% 내려가면 멈춤 |
| `max_consecutive_losses` | 4 | 4번 연속 손실이면 멈춤 |
| `max_leverage` | 20 | 최대 20배 (1단계) |
| `max_notional_usd` | 800 | 포지션 하나 최대 $800 (= $100 × 40% × 20배) |

거래 하나가 손절로 잃을 수 있는 돈은 코드가 따로 계좌의 15% 안으로 줄입니다.

설정 확인:
```bash
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor.json
```
마지막 줄이 **"준비됨"** 이어야 합니다. 아니면 나온 줄을 보내 주세요.

## 4. 연습 (롱 한 번, 숏 한 번)

실행기가 꺼져 있는 상태에서 합니다(테스트넷 계정에 BTC 포지션·주문이 없어야 함).

```bash
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh testnet drill --symbol BTCUSDT --side long
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh testnet drill --symbol BTCUSDT --side short
```

각각 1분 안쪽으로 끝나고 9줄이 나옵니다. **두 번 모두 9줄 전부 `[OK]`** 여야 합니다.

1. 시작 전 포지션·주문 없음
2. 레버리지 설정
3. 시장가 진입 체결
4. 포지션 크기 일치
5. 손절 주문이 거래소에 걸림
6. 손절을 옮길 때 빈틈 없음(새 손절을 건 뒤 옛 손절 취소)
7. 손절을 일부러 지우면 다시 걸어 놓음
8. 잘못된 쪽에 건 손절은 거절되고 시장가로 닫음
9. 끝나고 포지션·주문 모두 없음

하나라도 `[FAIL]`이면 다음으로 가지 말고 **출력 전체**를 보내 주세요. 연습이 실패해도 테스트넷 계정은 비워 놓고 끝납니다.
(키 문제면 "시작하지 않습니다: …"가 나옵니다. 그 줄을 보내 주세요. 키 값은 보내지 마세요.)

## 5. 관문 점검 (주문 없음)

```bash
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh executor preflight --config /etc/paperbot/executor.json
```
마지막 줄이 **"관문 모두 통과(주문은 하지 않았습니다)"** 여야 합니다.

## 6. 테스트넷으로 1주 돌려 보기 (10/12 ~ 10/18)

```bash
sudo systemctl start paperbot-executor                     # 켜기
sudo journalctl -fu paperbot-executor                      # 화면으로 보기 (Ctrl+C는 보기만 끝냄)
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-testnet.db
```

**첫날, 포지션이 열려 있을 때 일부러 해 볼 것**

| 해 볼 것 | 기대하는 결과 |
|---|---|
| 테스트넷 웹 화면에서 손절 주문 취소 | 3초 안에 손절이 다시 걸리고 소리 있는 알림 |
| 테스트넷 웹 화면에서 다른 코인 포지션을 손으로 열기 | 바로 닫히고 "모르는 포지션" 알림 |
| `sudo systemctl restart paperbot-executor` | 포지션과 손절을 그대로 이어받음 |
| `sudo touch /var/lib/paperbot/STOP` | 모두 닫히고 "거래를 멈춥니다" 알림, 다시 켜도 멈춤 |

STOP 시험 뒤에는 멈춤을 풉니다(11번 "멈춤 풀기").

**1주 동안 확인할 것 (모두 "예"여야 실거래로)**
- ☐ 설명 안 되는 알림이나 `loop_error`가 계속 나오지 않음
- ☐ 거래 기록의 손익 출처가 `fills`(실제 체결로 계산)
- ☐ 진입이 대부분 신호 뒤 2초 안
- ☐ 텔레그램 알림이 두 분 폰에 모두 옴
- ☐ $100 크기라 "최소 주문 크기 미만"으로 건너뛴 거래가 너무 많지 않음

거래 기록 보기(읽기만):
```bash
sudo -u paperbot-exec sqlite3 -readonly /var/lib/paperbot/exec/executor-testnet.db "SELECT datetime(entry_ts/1000,'unixepoch','+9 hours'), symbol, exit_reason, round(pnl,2), pnl_source FROM trades ORDER BY entry_ts DESC LIMIT 10"
```

10/18에 테스트넷 실행기를 끕니다: `sudo systemctl stop paperbot-executor`

## 7. 10/18: 실거래 준비

- **계좌 고르기**: 10/18 결과(규칙봇 순위, 커스텀값 그림자)를 보고 함께 고릅니다. 5년 전체 조합 연구의 후보는 아직 고른
  뒤의 성적이 없어서 이번 시험에는 쓰지 않습니다.
- **바이낸스에서 (두 분이 직접)**
  1. 실행기 전용 **하위 계정(sub-account)**을 만들고 선물(USDⓈ-M)을 켭니다. 주 계정은 쓰지 않습니다.
  2. 하위 계정 선물 지갑에 **$100 USDT만** 넣습니다($120을 넘으면 실행기가 켜지지 않습니다).
  3. 하위 계정에서 API 키를 만듭니다: **선물 거래 켬, 출금 끔, 서버 IP만 허용(158.247.200.152)**. 이체·현물·마진·옵션은 끔.
     **BNB 수수료 할인 끔**, 포지션 모드는 **단방향(one-way)**.
  4. 이 키는 규칙봇의 읽기 전용 키와 **다른 키**여야 합니다.

## 8. 10/19: 실거래 $100 켜기

1. 키 넣기 (`sudo nano /etc/paperbot/executor.env`):
   ```
   LIVE_API_KEY=(하위 계정 키)
   LIVE_API_SECRET=(하위 계정 비밀키)
   PAPERBOT_LIVE_MAINNET=I_UNDERSTAND
   ```
2. 설정 바꾸기 (`sudo nano /etc/paperbot/executor.json`): 3번 내용에서 아래만 바꿉니다.
   - `"mode": "mainnet"`
   - `"db": "/var/lib/paperbot/exec/executor.db"`
   - `"account"`: 10/18에 고른 계좌
   - `"budget_usd": 100` 줄을 추가 (`"qty_scale"` 줄 위에)
3. 관문 점검 (5번과 같은 명령). 출금 꺼짐·선물 켜짐·IP 제한·지갑 $120 이하를 포함해 모두 통과해야 합니다.
4. 켜기: `sudo systemctl start paperbot-executor`. 첫 거래는 두 분이 화면(`sudo journalctl -fu paperbot-executor`)과
   바이낸스 앱으로 같이 봅니다: 진입, 손절이 거래소에 걸림, 청산, 손익이 앱과 같음.
5. 며칠 문제없으면: `sudo systemctl enable paperbot-executor` (서버가 재부팅돼도 다시 켜짐).

## 9. 끄기

| 하고 싶은 것 | 명령 | 포지션 |
|---|---|---|
| 잠시 끄기 | `sudo systemctl stop paperbot-executor` | **그대로 남음** (거래소 손절도 그대로) |
| **비상 정지** (모두 닫고 멈춤) | `sudo touch /var/lib/paperbot/STOP` | 3초 안에 모두 시장가로 닫음 |
| 실거래 완전히 끄기 | STOP으로 먼저 닫고 → `executor.env`에서 `PAPERBOT_LIVE_MAINNET` 값을 지움 → `sudo systemctl stop paperbot-executor` | 없음 |

휴대폰으로 급할 때도 서버에 접속해 `sudo touch /var/lib/paperbot/STOP` 한 줄이면 됩니다. 바이낸스 앱에서 직접 포지션을 닫아도
되지만, 그러면 실행기가 "모르는 상태"로 알림을 보냅니다.

## 10. 상태 보기

```bash
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor.db
```

## 11. 멈춤 풀기 (하루 손실·연속 손실·낙폭·STOP 뒤)

```bash
sudo rm /var/lib/paperbot/STOP                       # STOP 파일이 있었다면
sudo systemctl stop paperbot-executor                # 켜져 있으면 풀기가 거부됩니다
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor clear-halt --config /etc/paperbot/executor.json --by 이름 --note "이유"
sudo systemctl start paperbot-executor
```

- 하루 손실로 멈췄다면 **다음 날 오전 9시 뒤**에 풉니다.
- `sudo -u paperbot`(규칙봇 사용자)로 돌리면 거부됩니다. 꼭 `paperbot-exec`로 돌리세요.
