# WOO X Pro 실행기 (10/20, "바이비트 + WOO X Pro")

두 분이 10/20에 정했습니다: **실거래봇은 바이비트와 WOO X Pro, 두 거래소로 돌린다.** MEXC는 쉽니다.

## 무엇이 바뀌나

- **두 번째 실행기 자리**가 MEXC 대신 **WOO X Pro**로 거래합니다.
  - 서비스 이름(`paperbot-executor-mexc`)과 설정 파일 이름(`/etc/paperbot/executor-mexc.json`)은 **예전 그대로** 둡니다.
    대시보드·아침 점검·텔레그램이 모두 이 이름으로 두 번째 실행기를 찾기 때문입니다.
  - 안의 설정만 `"exchange": "wooxpro"`로 바뀝니다. 그래서 실거래 사이트와 텔레그램에는 **"WOO X Pro"**로 나옵니다.
  - DB는 새 파일입니다: `/var/lib/paperbot/exec/executor-wooxpro-live.db` (MEXC 기록은 예전 DB에 그대로 남습니다).
- 매매 규칙은 그대로입니다. WOO X Pro는 MEXC 자리에 있던 **손절 −35% 페이퍼 봇**을 따라갑니다.
  - 15개 매매법, 계단 익절(거래소 기준), 빠른 청산, 1포지션, BTC 40배·알트 30배, 증거금 40%가 그대로입니다.
- **수수료:** TetherMax로 가입하면 시장가(테이커) 편도 0.042%입니다(할인 전 0.06%).
  - 설정의 `net_costs`에 0.042%를 넣었습니다. 계단 익절의 순ROE 계산에 쓰입니다.
  - drill 결과의 `fee_rate_pct`가 실제로 떼인 수수료입니다. 0.042%와 다르면 알려 주세요. 설정을 맞추겠습니다.
  - TetherMax 페이백(90%)은 나중에 따로 들어오는 돈이라 봇 계산에는 넣지 않습니다.

## 문서로 확인한 것과, 실제로 해 봐야 아는 것

WOO X Pro의 API는 BitMart 선물 API와 같은 구조입니다. 공식 문서(developer.wooxpro.com)와 BitMart용 ccxt 코드로 확인했습니다:
- 시장가 주문과 청산 전용 주문
- 손절(`stop_loss`, 마지막 체결가 기준)과 그 취소
- 포지션, 체결(수수료·실현손익 포함), 잔고, 펀딩 기록
- 배수 설정, 단방향 모드, 1분봉

아래는 실제 거래소에서만 확인됩니다. **drill이 하나씩 확인합니다:**
1. 손절 두 개가 **잠깐 동시에** 걸리는지. 손절을 옮길 때 "새 손절 → 확인 → 옛 손절 취소" 순서라서 필요합니다.
2. 손절이 **진짜로 발동해서** 포지션을 닫는지. drill의 "손절 발동 시험"이 마지막 가격 0.1% 옆에 손절을 걸고 최대
   20분 기다립니다.
3. 발동한 손절이 만든 주문 번호를 찾는지. 못 찾아도 그 거래 손익은 지갑 변화로 잡힙니다.
4. 서버 시간, 실제 수수료율, 체결의 `realised_profit`이 우리 계산과 맞는지.

**drill이 모두 `[OK]`가 아니면 실행기를 켜지 않습니다.** 결과를 그대로 붙여 주시면 고칠 것을 고친 뒤 다시 합니다.

## 서버에서 하는 순서

명령은 서버에서 순서대로 한 번씩 합니다. **키 값은 채팅에 절대 쓰지 않습니다.**

**0) 코드 받기, 6개 코인 정보 보기 (키 없이 됨)**

```bash
cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh wooxpro specs
```

- 6줄(BTC, ETH, SOL, DOGE, LTC, BCH)에 `상태 Trading`이 보여야 합니다. `최대`는 BTC 40배 이상, 나머지 30배 이상이어야 합니다.
- 결과를 붙여 주세요(공개 정보라 키가 없습니다).

**1) WOO X Pro 준비 (앱·웹에서)**

- 신원 확인(KYC)을 끝냅니다. API로 선물을 거래하려면 필요합니다.
- USDT를 입금하고 **선물(계약) 계좌로 옮깁니다.**
- 계정 → API 관리 → 새 API 만들기:
  - 메모: 영문·숫자로 짧게. 예: `paperbot`. **메모도 서명에 들어가서 아래 2)에 그대로 적습니다.**
  - 권한: **"읽기 전용, 선물 거래"**
  - 바인딩 IP: **`158.247.200.152`** (서버 주소. 집 컴퓨터 주소가 아닙니다)
  - 접근 키(Access Key)와 비밀 키(Secret Key)는 한 번만 보입니다. 따로 안전하게 적어 둡니다.

**2) 키를 서버 키 파일에 넣기**

```bash
sudo nano /etc/paperbot/executor.env
```

아래 네 줄을 넣고(이미 빈 줄이 있으면 채우고) 저장합니다(Ctrl+O, Enter, Ctrl+X):

```
WOOXPRO_LIVE_KEY=(접근 키)
WOOXPRO_LIVE_SECRET=(비밀 키)
WOOXPRO_LIVE_MEMO=(키 만들 때 적은 메모, 예: paperbot)
WOOXPRO_LIVE_KEY_CHECKED=FUTURES_ONLY_NO_WITHDRAW_IP_BOUND
```

- 마지막 줄은 "키를 '읽기 전용, 선물 거래 + 서버 IP'로 만들었다"는 두 분의 확인입니다. WOO X Pro는 키 권한을 API로 알려 주지
  않아서, 이 줄이 없으면 실행기가 켜지지 않습니다.
- 바이비트·MEXC 키와 같은 값이면 실행기가 거부합니다(거래소마다 다른 키).

**3) 읽기 점검 (주문 없음)**

```bash
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh wooxpro check
```

- 모든 줄이 `[OK]`여야 합니다: 서버 시간, 계약 정보, 선물 계정 읽기, 수수료율, 열린 주문, 포지션 모드 단방향, 격리 레버리지
  BTC 40배·나머지 30배, 키 확인.
- `수수료율` 줄의 `taker_pct`가 0.042면 TetherMax 할인이 API에도 적용된 것입니다.

**4) 진짜 최소 주문 시험 (약 $6, 손절 발동 시험 포함, 최대 25분쯤)**

```bash
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh wooxpro drill --confirm-order REAL_ORDER
```

- 가장 싼 코인(보통 DOGE)으로 진입 → 손절 걸기 → 손절 옮기기(두 개 동시) → 손절 발동 시험 → 정리 → 손익 대조를 합니다.
- 수수료와 약간의 손실(몇 센트)이 납니다.
- **결과 전체를 붙여 주세요.** 모두 `[OK]`인지 같이 봅니다.
- 20분 안에 가격이 시험 손절에 닿지 않으면 "발동을 못 봤습니다"로 끝납니다(실패는 아님). 그때는 한 번 더 합니다.

**5) 두 번째 실행기 설정을 WOO X Pro로 (실행기가 꺼진 상태에서)**

```bash
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-mexc-live.db
sudo cp -p /etc/paperbot/executor-mexc.json /etc/paperbot/executor-mexc.json.mexc-1020
sudo install -o root -g paperbot -m 640 /opt/crypto-bot-research/deploy/executor.live-wooxpro.json /etc/paperbot/executor-mexc.json
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor-mexc.json
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh executor preflight --config /etc/paperbot/executor-mexc.json
```

- 첫 줄: MEXC 실행기 `포지션: null`(꺼져 있고 포지션 없음)을 확인합니다.
- check-config에서 볼 줄:
  - `익절(계단 잠금): 거래소 기준 …`
  - `순ROE 비용: WOO X Pro 테이커 0.042% + 슬리피지 0.02% (한쪽), 왕복 0.124%`
  - `멈춤: 연패·낙폭으로는 멈추지 않음 …`, `신호등: 꺼짐 …`, 마지막 줄 **`준비됨`**
- preflight는 실제 계정을 읽어 시작 조건을 봅니다(주문 없음). 끝이 문제 없음이어야 합니다.
- 페이퍼는 `/var/lib/paperbot/combo/live15-mexc.db`(손절 −35% 봇)를 따라갑니다. 이 봇의 시작 지갑은 **WOO X Pro 선물 계좌
  잔고 × 10**이어야 증거금이 잔고의 40%가 됩니다(`docs/live15-mexc-ko.md` 2)의 WALLET 명령에서 MEXC 잔고 대신 WOO X Pro
  잔고). −35% 봇을 이미 켰다면 이 값은 바뀌지 않으니, 그때는 `qty_scale`을 "WOO X Pro 잔고 ÷ 페이퍼 지갑"으로 맞춥니다
  (`docs/live15-start-ko.md` 6)과 같은 방법, 파일만 `/etc/paperbot/executor-mexc.json`).

**6) 켜기**

```bash
sudo systemctl start paperbot-executor-mexc
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-wooxpro-live.db
```

- status에 `시작: paper 계좌 COMBO@mix 따라 하기 (페이퍼 DB /var/lib/paperbot/combo/live15-mexc.db), mainnet, …, 익절 거래소 기준`과
  `포지션: null`이 보여야 합니다.
- 텔레그램에 `▶️ WOO X Pro 실행기 켜짐 …`이 옵니다. 매번 켤 때 "키 권한은 두 분이 확인한 내용" 경고가 한 번 붙습니다(정상).

## 되돌리기 (MEXC로)

포지션이 없을 때만:

```bash
sudo systemctl stop paperbot-executor-mexc
sudo install -o root -g paperbot -m 640 /etc/paperbot/executor-mexc.json.mexc-1020 /etc/paperbot/executor-mexc.json
sudo systemctl start paperbot-executor-mexc
```

## 같이 알아 두실 것

- 비상 정지는 그대로 `sudo touch /var/lib/paperbot/STOP` 하나로 두 실행기가 모두 멈춥니다.
- WOO X Pro 키는 출금 권한이 아예 없습니다. 그래도 키 값은 채팅·사진에 보이지 않게 합니다.
- 새 거래소이니 처음에는 정한 금액만 넣고, 첫 거래 몇 번은 앱 화면과 텔레그램을 같이 봅니다.
- 코드: `paperbot/wooxpro.py`(연결), 시험 `tests/test_wooxpro.py`(가짜 거래소 `tests/fakewooxpro.py`), 설정 `deploy/executor.live-wooxpro.json`.
