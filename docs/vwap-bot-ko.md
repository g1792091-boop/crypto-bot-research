# VWAP 개선판 봇 (실거래용, 2026-10-23)

두 분 결정(10/23): "A + CMO 1시간 37승 3패가 제일 좋은 거 같네", "시드 비중은 40%, 비트도 30배", "바이비트 봇이나 WOO X Pro 봇 중에
1개를 중지시키고 이번에 새로 만들 실거래봇을 돌릴 예정", "이대로 만들어줘".

**같은 날 바뀜:** "지금 돌리고 있는 실거래봇 바이비트 봇이랑 woo x pro봇은 그대로 계속 돌릴꺼고 방금 만든 봇은 다른 거래소에서 돌릴
예정", "플립스터로 확정할게 만들어줘". 그래서 기존 실행기를 옮기지 않고 세 번째 실행기를 새로 둡니다.

**10/24 거래소 바뀜:** 플립스터 API는 신청한 사람에게만 열려 있어서 "그냥 다른거래소 쓸래" → **딥코인(DeepCoin)**. 세 번째 실행기는
딥코인으로 거래합니다(5-C, `docs/deepcoin-ko.md`). 플립스터 연결 코드는 나중을 위해 남겨 두지만 쓰지 않습니다.

## 1. 한눈에

| 항목 | 내용 |
|---|---|
| 이름 | VWAP 개선판 (텔레그램: `[합친 봇 페이퍼 VWAP 개선판]`) |
| 매매법 | VWAP 복귀 실패 30분 + CMO·샌드위치 캔들 1시간 (규칙봇 신호) |
| 코인 | BTC, ETH, SOL, DOGE, LTC, BCH, 합쳐서 포지션 1개 |
| 크기 | 증거금 40%, 전 코인 30배, 손절 한 번 최대 계좌 −20% |
| 페이퍼 봇 | `paperbot-combo-vwap` · 설정 `/etc/paperbot/combo-vwap.json` · 기록 `/var/lib/paperbot/combo/vwap.db` |
| 실거래 | **세 번째 실행기, 딥코인** `paperbot-executor-deepcoin` · 설정 `/etc/paperbot/executor-deepcoin.json` · 기록 `/var/lib/paperbot/exec/executor-deepcoin-live.db` |
| 추세판단 봇 | 그대로. 바이비트·WOO X Pro 실행기 두 개가 계속 따라감 |

## 2. 규칙 (설정 파일 `deploy/combo.vwap.json` 그대로)

### 진입: 신호가 나오면 차례로 확인

| 순서 | 확인 | 걸리면 | 설정 이름 |
|---|---|---|---|
| 1 | 한국 시간 토·일요일 | 진입 안 함 | `no_weekend` |
| 2 | 미국 경제 발표 앞뒤 30분 | 진입 안 함 | `macro_blackout_min` |
| 3 | 나스닥 개장 30분 전 ~ 30분 후 | 진입 안 함 | `us_open_pre_min`, `us_open_pause_min` |
| 4 | 그 코인 4시간 추세가 반대 (판단 4개 중 3개 이상 반대) | 진입 안 함. 보류는 통과 | `vote_gate` |
| 5 | 신호 봉 ATR%가 지난 30일의 80% 위치보다 큼 (변동성 상위 20%) | 진입 안 함 | `vol_gate` |
| 6 | 이미 포지션이 있음 | 건너뜀 | (항상) |

- 4번 판단 4개는 추세판단 봇과 같습니다: V3.9(슈퍼트렌드), EMA·DMI·ADX, OBV, 일목·AO. 신호 순간 가장 최근에 끝난 4시간봉을 봅니다.
- 5번은 신호를 낸 매매법 자기 봉입니다(VWAP 30분봉, CMO 1시간봉). 4번·5번은 바이낸스 공개 봉으로 계산하고, 봉을 못 읽으면 그 신호는
  들어가지 않고 이유가 기록됩니다.
- 통과하면 신호 봉이 닫힌 다음 1분 시가에 시장가로 들어갑니다. 2분 반 넘게 늦은 신호는 따라가지 않습니다.
- 같은 분에 신호가 겹치면 VWAP 먼저, 그다음 BTC → ETH → SOL → DOGE → LTC → BCH.

### 청산

| 항목 | 내용 | 설정 이름 |
|---|---|---|
| 손절 | 진입가에서 2 ATR (신호 봉 ATR14). 실행기가 거래소에 손절 주문을 바로 걸어 둠 | `stop` |
| 계단 익절 | 순ROE 10% → 8% 잠금, 14% → 12%, 18% → 16%, 이후 4%씩 (10/27부터 페이퍼·실거래 둘 다, 11장; 그 전에는 12% → 10%, 이후 5%씩) | `ladder` |
| 보유 한도 | 자기 봉 96개: VWAP 48시간, CMO 96시간 (넘으면 시장가 정리, 기록·메시지에는 "보유 한도 청산") | `max_hold_bars` |
| 반대 신호 청산 · 추세 뒤집힘 청산 | 없음 | `early_exit` null |

### 크기

- 잔고의 40%를 증거금으로, 30배(`margin` 0.4, `leverage` 30).
- 2 ATR 손절이 ROE −50%보다 크면 수량을 줄입니다(`max_loss_frac` 0.2, `loss_cap` shrink). 그래서 손절 한 번에 계좌는 최대 약 −20%.
- 페이퍼는 1,000달러로 시작합니다. 실거래 수량은 "페이퍼 수량 × qty_scale"이고, 딥코인 실행기를 켜기 전에 도구가 qty_scale을
  "딥코인 잔고 ÷ 그때 페이퍼 지갑"으로 맞춥니다(5-C).
- 배수: 페이퍼는 모든 코인 30배. **실거래(딥코인)는 10/27부터 BTC 40배 · 나머지 30배**(실행기 `leverage_by_symbol`), 강제청산 가격보다
  먼 손절이면 진입 안 함(`liq_guard`). 페이퍼는 5년 연구와 비교하려고 그대로 둡니다(11장).

## 3. 숫자 (솔직하게)

| | 거래 | 승패 | 결과 | 최대 낙폭 |
|---|---|---|---|---|
| 17일 (10/05 19:30 ~ 10/23), 연구 계산, 증거금 40% | 40번 | 37승 3패 | ×3.64 | −23.7% |
| 같은 17일, **실거래 봇 코드로 1분씩 다시 돌림**, 증거금 40% | 40번 | 37승 3패 | ×4.01 | −23.2% |
| 지난 79개월 (2020-03 ~ 2026-09), 증거금 40%, 달마다 새로 시작 | 한 달 약 70번 | | 플러스인 달 6번, 가운데 달 −77% | |

- 실거래 코드로 다시 돌린 40번 중 39번이 연구와 같은 진입이었습니다. 1번은 앞 거래의 익절 시각이 몇 분 달라 다른 코인으로 들어갔습니다.
  4번·5번 판정은 7월 이후 신호 1,714개에서 연구 계산과 모두 같았습니다(`research/vwap30/livepar.json`).
- 실거래 코드가 조금 더 좋게 나온 것(×4.01)은 계단 잠금 가격을 수수료까지 넣어 계산하는 방식 차이(잠긴 익절 한 번에 약 +0.02%)입니다.
  실제 거래소에서는 체결 미끄러짐이 따로 생깁니다.
- 이 17일은 고를 때 본 기간이고, 지난 80개월 중 이 계열이 가장 좋았던 달입니다. 5년 전체로는 거래당 마이너스였습니다.
  그래서 작게 시작해서 맞으면 키우는 순서를 권합니다(6).

## 4. 무엇이 바뀌나

- 새로 생김: 페이퍼 봇 서비스 `paperbot-combo-vwap`(설치만, 두 분이 켬), 설정 `/etc/paperbot/combo-vwap.json`, 기록
  `/var/lib/paperbot/combo/vwap.db`(매일 밤 백업에 포함).
- 봇 코드(`paperbot/combo.py`, `paperbot/entrygates.py`): 새 기능 3개(4시간 추세 금지, 변동성 금지, 보유 한도)는 설정에 있을 때만
  동작합니다. 추세판단 봇 설정에는 없어서 그 봇의 동작은 바뀌지 않습니다(시험으로 확인).
- 새로 생김(설치만, 두 분이 켬): 딥코인 실행기 서비스 `paperbot-executor-deepcoin`, 연결 코드 `paperbot/deepcoin.py`, 설정 원본
  `deploy/executor.live-deepcoin.json`(VWAP 페이퍼를 따라가게 이미 맞춰 둠: 계단 10%→8% 잠금 이후 4%씩(10/27부터), 신호등 20번 75%, 손절 한 번
  최대 손실 20%), 기록 `/var/lib/paperbot/exec/executor-deepcoin-live.db`(매일 밤 백업에 포함).
- **바이비트·WOO X Pro 실행기는 아무것도 안 바뀝니다.** 설정·키·기록 그대로 추세판단 봇을 따라갑니다. 실행기 코드는 딥코인 연결이
  더해지고 말(따라가는 페이퍼의 보유 한도 청산 이름)만 바뀌었습니다. 다음에 그 실행기들을 다시 켤 때 적용되고, 지금 켜진 것을 다시 켤
  필요는 없습니다.
- 실거래 사이트·텔레그램 감시(8장): 설치(5-A) 뒤 바로 적용됩니다. 딥코인 설정 파일과 기록이 없는 동안에는 실행기 칸이 지금처럼 두 개로
  보입니다(시험으로 확인). 설정 파일을 넣으면(5-C 1) 세 번째 칸 "딥코인"가 생깁니다.

## 5. 서버 순서 (한 줄씩 붙여 넣기)

### A. 설치 — 추세판단 봇 페이퍼에 포지션이 없을 때

`install.sh`는 코드를 바꾸는 동안 규칙봇·페이퍼 봇들을 잠깐 껐다 켭니다(실행기는 건드리지 않음. 딥코인 실행기 서비스는 설치만 하고 켜지 않음). 그래서 페이퍼 포지션이 없을 때 합니다.

```bash
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo status --db /var/lib/paperbot/combo/live-ac.db
```

- `COMBO@mix: … 포지션 없음`이면 다음 줄로. 포지션이 있으면 닫힐 때까지 기다렸다가 다시.

```bash
cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh
```

- 끝에 `VWAP 개선판 페이퍼 봇(paperbot-combo-vwap) 설치만 했습니다` 줄이 나옵니다.
- 사이트 설정 한 줄 확인(한 번만):

```bash
sudo grep -n PAPER2 /etc/paperbot/dash.env
```

- 아무것도 안 나오거나 `#`로 시작하는 줄만 나오면 그대로 둡니다.
- `PAPERBOT_LIVE_PAPER2_DB=/var/lib/paperbot/combo/live15-mexc.db`처럼 `#` 없이 예전 −35% 봇을 가리키는 줄이 나오면 그 줄을 지우고
  `sudo systemctl restart paperbot-livedash`를 합니다. 그대로 두면 사이트의 VWAP 화면이 계속 "꺼져 있어요"로 보입니다.

### B. VWAP 페이퍼 봇 켜기 — 언제든 (돈·주문 없음)

```bash
sudo install -o root -g paperbot -m 640 /opt/crypto-bot-research/deploy/combo.vwap.json /etc/paperbot/combo-vwap.json
cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo check-config --config /etc/paperbot/combo-vwap.json
```

- 확인 줄: `4시간 추세 판단이 반대면 진입 안 함(4개 중 3개 반대; 보류는 진입)`, `변동성(ATR14%)이 지난 30일의 80% 위치보다 크면 진입
  안 함(상위 20% 금지)`, `보유 한도 96봉(30분 48시간 · 1시간 96시간), 넘으면 시장가 청산`, 매매법 1·2번, 마지막 줄 **`준비됨`**.

```bash
sudo systemctl enable --now paperbot-combo-vwap
systemctl is-active paperbot-combo-vwap
```

- `active`. 텔레그램에 `[합친 봇 페이퍼 VWAP 개선판] 시작: 매매법 2개, BTC 30배·나머지 30배, 증거금 잔고의 40%, 손절 2 ATR, …` 가 옵니다.
- 1~2분 뒤 기록 확인:

```bash
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo status --db /var/lib/paperbot/combo/vwap.db
```

- `마지막 1분봉: (지금에 가까운 시각) KST`, `COMBO@mix: 지갑 $1,000.00, 거래 0번 …`. 이때부터 페이퍼로 돌기 시작합니다.

### C. 딥코인 실행기 켜기 — drill이 모두 `[OK]`인 뒤에만

바이비트·WOO X Pro 실행기는 건드리지 않습니다. 그 둘은 켜진 채로 두고 아래를 합니다.

0) 먼저 할 것:
- A(설치)와 B(VWAP 페이퍼 봇 켜기)를 끝냅니다. 텔레그램 감시가 새 버전이어야 두 봇의 메시지가 따로 나옵니다.
- `docs/deepcoin-ko.md`의 순서대로 합니다: 딥코인 API 키 만들기, 서버 키 파일에 넣기, `specs` · `check` · `drill`.
  **drill 결과가 모두 `[OK]`이고 결과를 같이 본 뒤에만** 다음으로 갑니다.
- 딥코인 선물 계좌에 정한 금액을 넣어 둡니다.

1) 설정 파일 넣기 (처음 한 번. 이미 있으면 덮어쓰지 않고 그대로 둠):

```bash
sudo test -e /etc/paperbot/executor-deepcoin.json || sudo install -o root -g paperbot -m 640 /opt/crypto-bot-research/deploy/executor.live-deepcoin.json /etc/paperbot/executor-deepcoin.json
```

- 이때부터 사이트에 세 번째 실행기 칸 "딥코인"가 "꺼짐"으로 보입니다.

2) 시작 금액 맞추기, 먼저 보기만 (아직 안 바뀜). `123.45` 자리에 딥코인 선물 잔고(달러)를 넣습니다:

```bash
cd /opt/crypto-bot-research && sudo python3 deploy/vwap_switch.py --exec deepcoin --balance 123.45
```

- `budget_usd: 100 → 123.45`, `qty_scale: 0.1 → …`, `(실거래 크기 = 페이퍼 수량 × …: 페이퍼 지갑 $…, 실거래 잔고 $…)`가 나옵니다.
  나머지(따라가는 페이퍼, 계단, 신호등, 손절 한 번 최대 손실)는 원본에 이미 맞춰져 있어 안 바뀝니다.
- VWAP 페이퍼 기록이 아직 없거나 딥코인 실행기가 켜져 있으면 `멈춤 - …`이 나오고 아무것도 바꾸지 않습니다.

3) 바꾸기 → 확인:

```bash
cd /opt/crypto-bot-research && sudo python3 deploy/vwap_switch.py --exec deepcoin --balance 123.45 --write
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor-deepcoin.json
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh executor preflight --config /etc/paperbot/executor-deepcoin.json
```

- 예전 설정은 `/etc/paperbot/executor-deepcoin.json.before-vwap-<시각>`으로 남습니다.
- check-config에서 볼 줄: 계단 `순ROE 10%에서 8% 잠금, 이후 4%씩`(10/27부터), `순ROE 비용: 딥코인 테이커 0.05% + 슬리피지 0.02% …`,
  `신호등: 켜짐 - paper 최근 20번 중 75% 이상 이겼을 때만 진입을 따라감`, 마지막 줄 **`준비됨`**. preflight도 통과해야 합니다.

4) 켜기 → 확인:

```bash
sudo systemctl start paperbot-executor-deepcoin
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-deepcoin-live.db
```

- 기록에 `시작: paper 계좌 COMBO@mix 따라 하기 (페이퍼 DB /var/lib/paperbot/combo/vwap.db), mainnet, …`. `포지션: null`.
- 텔레그램에 `▶️ 딥코인 실행기 켜짐 …`이 옵니다. 켤 때마다 "키 권한은 두 분이 확인한 내용" 경고가 한 번 붙습니다(정상).
- VWAP 페이퍼가 이미 포지션을 들고 있었으면 `paper 진입이 n초 전이라 따라 하지 않습니다`가 하나 생깁니다. 정상입니다(다음 진입부터 따라감).
- 처음 며칠이 괜찮으면 서버를 다시 켜도 같이 켜지게 `sudo systemctl enable paperbot-executor-deepcoin`.

### D. 딥코인 실행기 끄기 — 포지션이 없을 때만

```bash
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-deepcoin-live.db
sudo systemctl stop paperbot-executor-deepcoin
```

- 첫 줄이 `포지션: null`일 때만 끕니다. 끄기만 하면 포지션과 거래소 손절은 그대로 남습니다(손절이 계속 보호).
- `sudo touch /var/lib/paperbot/STOP`(비상 정지)은 **세 실행기를 모두** 닫고 멈춥니다. 딥코인만 멈출 때는 쓰지 않습니다.
- VWAP 페이퍼 봇은 계속 돌려도 되고(비교용), 끄려면 `sudo systemctl disable --now paperbot-combo-vwap`.

## 6. 운영 순서와 지켜볼 숫자

| 단계 | 내용 |
|---|---|
| ① 시작 | 실거래 계좌에는 적은 돈만. 페이퍼는 옆에서 같은 규칙으로 비교 |
| ② 신호등 | 페이퍼 최근 20번 승률이 75% 아래면 실행기가 새 진입을 따라가지 않음(페이퍼는 계속). 20번 전에는 모두 따라감 |
| ③ 키우기 | 실거래 50번(약 3주) 동안 승률 80% 이상이고 페이퍼와 결과가 비슷하면 돈을 늘림. **함께 볼 것:** 승률이 본전 승률보다 확실히 높고, 순ROE 합이 플러스이고, 페이퍼가 동전 쌍둥이 계좌보다 나을 때만 (아래 설명) |
| ④ 멈추기 | 승률이 본전 승률(평균 이익·손실로 계산; 5년 기록으로는 약 79%) 아래로 이어지면 멈추고 다시 봄. 딥코인만 멈추려면 포지션이 없을 때 5-D. `sudo touch /var/lib/paperbot/STOP`은 세 실행기를 모두 닫는 비상용 |

- **본전 승률(10/23 다시 계산):**
  - 이 봇은 이길 때 작게(5년 평균 +10.8%) 벌고 질 때 크게(−39.4%) 잃습니다. 그래서 본전 승률은 약 79%입니다.
  - 처음에 적었던 71%는 틀린 숫자였습니다.
  - 사이트 'VWAP 성적' 화면과 아침 점검은 실제 거래의 평균으로 본전 승률을 다시 계산해서 보여 줍니다.
- **5년 기록으로 본 키우기 기준:**
  - 50번 승률 80% 이상인 구간 뒤에도 다음 50번은 평균 손해였습니다(승률 77%). 90% 이상 뒤에도 승률은 84%였지만 평균은 여전히 손해였습니다.
  - 그래서 승률만 보지 말고 순ROE 합과 동전 쌍둥이 비교를 같이 봅니다(`research/vwap30/QA_KO.md` 마지막 절).
- 손절 한 번이 계좌 약 −20%라서 3번 연속이면 약 −49%입니다.
- 실행기는 자기 체결가로 계단을 따로 계산합니다. 자기 첫 잠금 뒤에는 페이퍼의 시간 정리를 따르지 않고 자기 계단으로 갑니다
  (5년 동안 보유 한도에 걸린 거래는 0번).

## 7. 알아 둘 것

- **경제 발표 일정**: `data/macro_events.csv`가 2026-12-23까지 들어 있습니다. 그 뒤 일정은 채워야 2번 금지가 계속 동작합니다
  (check-config가 "앞으로 일정 n개"로 보여 줌).
- **바이낸스 봉**: 4번·5번 판정에 바이낸스 공개 봉을 씁니다(신호 하나에 작은 요청 몇 개). 바이낸스가 안 될 때는 그 신호를 들어가지 않고
  이유("… 못 읽음(진입 안 함)")를 기록합니다.
- **추세판단 봇과 동시 진입**: 두 봇은 서로 다른 거래소 계정이라 같은 코인에 동시에 들어가도 서로 영향이 없습니다.
- **딥코인 키**: 키를 만들 때 정하는 암호(Passphrase)도 서버에 넣어야 합니다. 서버 IP를 묶어 둡니다(공식 문서: 거래 권한이 있는데
  IP를 묶지 않은 키는 30일 동안 안 쓰면 지워짐). 자세한 것은 `docs/deepcoin-ko.md`.
- **계산 파일**: 설계 근거와 숫자는 `research/vwap30/QA_KO.md`, 앞으로 확인 후보 D는 `research/vwap30/PREREG_FWD1_AMEND3.md`.

## 8. 실거래 사이트(8093)와 텔레그램에서 보는 법

VWAP 페이퍼 봇을 켜면(5-B) 실행기가 아직 따라가지 않아도 사이트와 텔레그램에 나옵니다. 이름은 어디서나 "VWAP 개선판"과 "추세판단 봇"입니다.

### 사이트: 메뉴 맨 끝 "VWAP 봇"

| 화면 | 보이는 것 |
|---|---|
| VWAP 관제 | 봇이 도는지 · 포지션(진입 때 통과한 조건 숫자, 보유 한도까지 남은 시간) · 따라가는 실행기와 그 신호등(20번 75%) · **지금 코인별** 4시간 판단과 30분·1시간 변동성 → 신호가 오면 롱/숏이 되는지 · 다음 진입 쉼 · 최근 48시간 신호와 들어가지 않은 이유 |
| VWAP 성적 | 페이퍼와 동전 쌍둥이(같은 순간, 방향만 무작위) 나란히 · 본전 승률(평균 이익·손실로 계산) · 키우기·멈추기 점검표(딥코인 실거래만) · 운이냐 고장이냐(9장) · 연구 숫자와 나란히 · 나눠 보기(매매법·코인·방향·4시간 판단·변동성 위치·시간대·청산 이유·보유 시간) · 거래 목록 |
| VWAP 막은 신호 | 이유별로 막은 신호 수(오늘·7일·시작부터) · "막지 않았다면" 가상 결과(1분 감시가 같은 엔진으로 계산) |

- 지금 코인별 그림은 봇이 30분마다(30분봉이 닫히고 2분 뒤) 새로 적습니다. 서버에서는
  `sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo status --db /var/lib/paperbot/combo/vwap.db`로도 봅니다(막은 신호 수 포함).
- 기존 화면도 두 봇을 나눠 셉니다. 관제·검토·재현 비교·목표·순위·지도·비용의 추세판단 봇 숫자에는 추세판단 봇을 따라간 거래만 들어갑니다.
  딥코인 실행기는 처음부터 VWAP 쪽에만 셉니다(실행기 칸이 세 개가 됨). 신호·못 탄 신호에는 "어느 봇의 신호" 선택이 있고, 설정에는 두 번째 봇 카드가, 진입 근거에는
  4시간 판단·변동성 숫자와 보유 한도가 나옵니다.

### 텔레그램

- 🟢 진입: 매매법 이름과 그때 읽은 조건 한 줄(예: `4시간 상승(상승 3·하락 0·중립 1) · 변동성 30분 ATR 0.45% (30일 80% 위치 0.62%)`).
- ✅ · ❌ · 🔒: 앞에 봇 이름. 두 봇이 같은 분에 들어가도 메시지는 따로 옵니다. 보유 한도로 닫히면 `보유 한도 청산(96봉(48시간) 지남)`.
- 실행기가 따라가기 전에는 `페이퍼만 (따라가는 실행기 없음)`이 붙습니다. 켠 뒤 처음 보는 예전 거래는 보내지 않습니다.
- 아침 점검의 "VWAP 개선판" 칸: 어제 · 시작부터 · 본전 승률(이 봇 평균, 참고 5년 79%) · 늘리기 기준 · 딥코인 실행기 성적 · 신호등 ·
  조건이 막은 신호 수와 가상 결과 · 맨 끝에 운이냐 고장이냐(9장).
- 알람: VWAP 페이퍼 봇이 10분 넘게 기록하지 않으면 실행기가 따라갈 때 🚨, 페이퍼만일 때 ⚠(무음). 할 일 줄에 `paperbot-combo-vwap`.
- 미리보기(서버, 보내지 않음): `cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.livecheck preview --vwap`

## 9. 운이냐 고장이냐 · 분석팀 (10/25)

두 분 요청(10/25): "vwap 개선판봇이랑 친구 매매봇도 연구분석이나 손실 분석 그런부분들은 없어?? 매매법 성공을 위해서 필요한 부분들 있을꺼
같은데" → "전부 다 만들어줘". 이 장은 VWAP 개선판 쪽입니다. 매매 규칙·크기·코인은 하나도 바뀌지 않았습니다. 보기만 하는 기능입니다.

### 9-1. 운이냐 고장이냐

지금 성적이 "운이 나쁜 정도"인지, "봇이 설계와 다르게 돌고 있는지"를 숫자로 봅니다. 잣대는 같은 규칙으로 돌린 5년 페이퍼 거래
5,805번입니다(`research/vwap30/band.json`, 만든 코드 `research/vwap30/code/vwband.py`).

| 보는 것 | 어떻게 재나 | 5년 숫자 |
|---|---|---|
| 승률 | 지금 거래 수에서 5년 승률(72.0%)대로라면 이만큼 이하가 나올 확률 | 50번이면 보통 31~41승 |
| 연패 | 지금 연패가 5년 연패 중 몇 %만큼 길었나 | 연패 1,158번: 2연패 이상 27% · 3연패 이상 9.2% · 4연패 이상 2.5% · 5연패 이상 0.9% · 가장 긴 것 6연패 |
| 낙폭 | 시작 뒤 가장 깊게 빠진 정도가, 5년의 같은 거래 수 구간 중 몇 %만큼 깊었나 | 10번 구간 가운데 −30% · 50번 구간 가운데 −71% |

- 판정 말:
  - **정상 범위**: 5년에 이만큼 이상 나쁜 경우가 5% 넘게 있었음.
  - **드묾**: 1~5%.
  - **아주 드묾: 설계와 다르게 돌고 있을 수 있어요**: 1% 미만.
- 세 가지 중 가장 나쁜 것이 그 계좌의 판정입니다. 거래 20번 미만이면 "아직 표본 적음"이 붙습니다.
- 페이퍼와 실거래(딥코인)는 따로 잽니다. 딥코인은 VWAP 개선판을 따라간 거래만 셉니다.
- 낙폭 계산: 페이퍼는 지갑 기록 그대로, 딥코인은 "진입마다 잔고의 40% × 순ROE"로 계산합니다.

**솔직하게:**

- 5년 승률 72.0%는 본전 승률 78.6%보다 낮습니다. 5년 동안 거래당 손해였습니다(평균 순ROE −3.3%).
- 그래서 **정상 범위 = 5년처럼 돈다는 뜻이지, 돈을 번다는 뜻이 아닙니다.**
- 낙폭도 5년 기준으로는 큰 낙폭이 흔했습니다. 낙폭이 "정상 범위"여도 안심하라는 뜻이 아닙니다.
- 17일(10/05~10/23, 40번 37승 3패, 가장 긴 연패 1번, 가장 깊은 낙폭 −23.7%)은 이 봇을 고를 때 본 가장 좋은 기간입니다. 참고로만
  보여 주고, 기대치로 쓰지 않습니다.
- "아주 드묾"이 나와도 봇이 저절로 멈추지 않습니다. 멈출지는 두 분이 정합니다(6장 ④, 5-D).

**어디서 보나:**

- 아침 점검: "VWAP 개선판" 칸 맨 끝. 예:
  `- 운이냐 고장이냐 · 페이퍼(거래 50번): 정상 범위`
  `  승률 36/50승(5년이면 보통 31~41승, 이만큼 이하 55%) 정상 · 지금 2연패(5년 연패 중 27%가 이만큼) 정상 · 가장 깊은 낙폭 −45%(…) 정상`
  `- 운이냐 고장이냐 · 딥코인 실거래(거래 12번): …`
  그 아래 한 줄은 기준입니다(5년은 거래당 손해, 17일은 기대치 아님).
- 사이트 "VWAP 성적" → "운이냐 고장이냐" 카드: 페이퍼와 딥코인 실거래가 따로 한 칸씩. 줄마다 판정 표시(초록 정상 범위 · 노랑 드묾 · 빨강
  아주 드묾)와 숫자. 아래에 "솔직히" 문장과 17일 참고.
- 분석팀 회의 자료(9-2).

### 9-2. 분석팀이 VWAP 개선판도 봅니다

실거래 분석팀(`paperbot/liveteam.py`, 사이트 실거래 › 분석팀)이 이제 VWAP 개선판 회의를 따로 엽니다. 추세판단 봇 회의는 그대로입니다.

| 회의 | 언제 열리나 | 메시지 첫 줄 예 |
|---|---|---|
| 손실 회의 | VWAP 개선판을 따라간 실행기(딥코인)의 마지막 닫힌 거래 2개가 모두 손실일 때(3일 안). 다른 실행기와 같은 규칙. 같은 두 거래로는 한 번만 | `🧭 [실거래 분석팀] VWAP 개선판 · 딥코인 손실 회의 🟠 주의` |
| 거래 점검(페이퍼) | VWAP 페이퍼가 시작 뒤 50번, 100번 … 거래를 닫을 때마다(이 안내서 6장의 50번 단위) | `… VWAP 개선판 · 딥코인 50번째 거래 점검(페이퍼) …` |
| 실거래 점검 | 딥코인이 VWAP 개선판을 따라간 거래가 50번, 100번 …이 될 때(6장 ③ 키우기를 판단하는 때) | `… VWAP 개선판 · 딥코인 실거래 50번 점검 …` |
| 주간 보고 | 월요일 10시 주간 보고에 VWAP 개선판 칸이 따로 붙음 | 메시지 안에 `— VWAP 개선판 · 딥코인 🟡 지켜보기` 줄 |

- 딥코인이 VWAP 개선판을 따라간 거래는 추세판단 봇 손실 회의에 들어가지 않습니다(이전에는 섞일 수 있었음).
- 회의 자료(코드가 만듦, AI는 도구 없음):
  - 이 봇의 규칙: 지금 돌고 있는 설정 그대로(4시간 판단·변동성 조건, 2 ATR 손절, 계단 익절, 96봉 보유 한도, 쉬는 시간)
  - 딥코인 실행기 규칙(잔고의 40%로 진입, 신호등 20번 75%, 거래소 손절)
  - 시작 뒤 성적: 페이퍼·동전 쌍둥이·딥코인 따로
  - 키우기·멈추기 점검표
  - 운이냐 고장이냐(9-1)
  - 비용: 딥코인 테이커 수수료 0.04%(한쪽), 연구가 쓴 비용(한쪽 0.05% + 미끄러짐 0.02%), 실제 체결에서 잰 수수료
  - 조건이 막은 신호와 "막지 않았다면"(가상)
  - 지금 코인별 판단, 나눠 보기
- 회의에서 지키는 것:
  - 고정 규칙과 두 분 결정은 회의 주제가 아닙니다.
  - 아이디어는 "시험해 볼 가설"뿐입니다(2020-24로 고르고 2025-26에서 확인, 또는 그림자 봇). 정하는 것은 두 분입니다.
  - 5년이 거래당 손해였다는 것과 17일은 고른 기간이라는 것을 회의마다 그대로 말합니다.
- 비용 참고: 코드의 비용 계산(실행기 자기 계단 등)은 드릴이 재기 전까지 딥코인 0.05%를 씁니다. 회의 자료에는 두 숫자가 다 나옵니다.
- 손으로 보기(서버, AI 부르지 않음, 아무것도 안 씀):
  `cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.liveteam preview loss --vwap`
  (`checkpoint --vwap`, `weekly --vwap`도 됨). 손으로 열기: `… run loss --vwap --force`.
- 분석팀 타이머는 그대로입니다(설치만, 두 분이 켬: `sudo systemctl enable --now paperbot-liveteam.timer`).

## 10. 그림자 "4시간 정리" (두 분 10/26: "둘 다 해줘")

나스닥 개장·횡보 대책 시험(research/opentime/REPORT_KO.md)에서 VWAP만 "진입 4시간 안에 첫 잠금(순ROE +10%)에 못 닿으면 닫기"가
기준을 통과했습니다. 그런데 신호등(최근 20번 중 75%)을 거친 실거래 쪽에서만 좋아졌고, 모의 거래 전체로는 차이가 없었고, 10월에는
오히려 나빴습니다. 그래서 **실거래 규칙은 그대로** 두고, 같은 시장에서 그 규칙 하나만 바꾼 모의 봇(그림자)을 같이 돌려 몇 주 봅니다.

- 설정: `deploy/combo.shadow-vwap-4h.json` = `deploy/combo.vwap.json`에 `"unlocked_close_min": 240` 하나만 더한 것(이름, 기록 파일
  `/var/lib/paperbot/combo/shadow-vwap-4h.db`, 텔레그램 끔은 그림자마다 다름). 돈·주문·텔레그램 없음, 실행기는 그림자를 따라가지 않습니다.
- 청산 이유 "잠금 전 시간 정리": 진입 4시간이 지난 첫 분에 아직 첫 잠금 전이면 그 분 시가에 시장가로 닫습니다(수수료 포함).
- 보는 곳: 실거래 사이트(8093) → 그림자 화면 맨 위 "VWAP 개선판 그림자 비교". 그림자를 켠 때부터, VWAP 페이퍼도 같은 기간만:
  - "모든 페이퍼 거래": 거래 수, 이긴 비율, 거래당 평균 순ROE, 순ROE 합, 최대 낙폭, 청산 이유.
  - "실행기가 따라갔을 거래": 딥코인 실행기 신호등(20번 · 75%)을 각자의 거래 순서로 다시 계산해 따라갔을 거래만. 5년 시험에서 차이가
    난 쪽이 여기입니다.
  - 양쪽 다 닫힌 거래가 20번이 넘기 전에는 "표본 적음 · 아직 판단 못 함".
- 정하는 법(제안): 2~3주 뒤 "실행기가 따라갔을 거래"의 순ROE 합이 그림자 쪽이 분명히 높고 모든 거래 쪽도 나쁘지 않으면, 그때 실거래에
  넣을지 두 분이 정합니다. 그 전에는 실거래 규칙을 바꾸지 않습니다.

### 10-1. 켜는 순서 (서버에서, 언제든 · 실거래에 영향 없음)

1. 코드 받기: `cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh`
   - 설치는 그림자를 켜거나 끄지 않습니다. 돌고 있는 VWAP 봇·실행기도 그대로입니다(새 설정 항목은 기본값이 꺼짐).
2. 설정 확인(읽기만): `cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo check-config --config deploy/combo.shadow-vwap-4h.json`
   - 마지막 줄 `준비됨`, 규칙 줄에 `진입 4시간 안에 첫 잠금에 못 닿으면 시장가 청산`.
3. 켜기: `sudo systemctl start paperbot-combo-shadow@vwap-4h`
   - 약 2분 기다렸다가 돌기 시작합니다(바이낸스 요청 순서). 확인: `systemctl is-active paperbot-combo-shadow@vwap-4h`, 몇 분 뒤 사이트의 그림자 화면.
4. 끄기: `sudo systemctl stop paperbot-combo-shadow@vwap-4h` (기록은 남습니다).

## 11. 실거래 계단 10%→8% · BTC 40배 (두 분 10/27)

두 분: "그래도 10→8로 간다면 친구봇 간격 5 / VWAP 간격 4 … 이렇게 가자 그 대신에 vwap 봇도 비트는 40배로 나머지 종목들은 30배로 가자",
"5년기록 하지말고 그냥 바꿔".

처음에는 딥코인 실행기(실거래)만 바꿨습니다. 같은 날 두 분이 "vwap 매매법도 순수익+8%로 해줘", "순수익 8% 계단식익절 알지?"라고 해서
**VWAP 페이퍼(모의, `deploy/combo.vwap.json`)의 계단도 같은 10→8, 4%마다로 바꿨습니다**(11-2; 배수는 페이퍼 그대로 모두 30배).
실행기는 페이퍼의 계단을 따르지 않고 자기 체결가로 자기 계단을 돕니다. 페이퍼를 맞추면 페이퍼가 실거래와 같은 자리에서 닫혀서,
다음 신호를 받을 때(포지션 하나)와 신호등(최근 20번 승률)이 실거래 규칙과 같은 거래로 계산됩니다. 그림자 "4시간 정리"
(`deploy/combo.shadow-vwap-4h.json`)도 페이퍼와 같은 계단으로 맞췄습니다(그 하나만 다른 쌍둥이).

- **계단** (`ladder`: `first_lock 0.08, trigger_gap 0.02, step 0.04`): 순ROE 10%에 닿으면 손절을 순 8% 자리로, 14%면 12%, 18%면 16%,
  그 뒤 4%마다 한 칸.
  - 거래소 화면 기준(딥코인 비용 왕복 0.14%): 30배 코인은 화면 +14.2% → +12.2%, +18.2% → +16.2%, +22.2% → +20.2%.
    BTC 40배는 화면 +15.6% → +13.6%, +19.6% → +17.6%, +23.6% → +21.6%.
- **배수** (`leverage_by_symbol`: BTC 40, 나머지 30): 진입 전에 딥코인 배수를 이 값으로 맞춥니다. 크기는 그대로 잔고의 40% × 배수.
  BTC는 손절 한 번이 전보다 약 1.3배 큽니다(같은 손절 거리에서 30배 → 40배).
- **청산가 확인** (`liq_guard`, 유지증거금률 0.5%): 손절이 강제청산 거리(40배 약 2.0%, 30배 약 2.83%)와 같거나 더 멀면 그 진입은 하지
  않습니다(놓친 신호로 기록). 레인지 봇·투비트 실행기와 같은 장치입니다.
- 참고(바꾸기 전 한 번 돌려 본 5년 기록, `research/opentime/vwap_ladder.py`, `vwap_btc40.py`): 계단 10→8은 12→10보다 같거나 조금 나빴고,
  BTC 40배는 2021~23에는 나빴고 2024~26에는 나았습니다. 두 분이 정한 대로 바꿉니다.
- 바꾼 설정 원본: `deploy/executor.live-deepcoin.json`(다른 거래소로 옮길 때 쓰는 `executor.live-wooxpro-vwap.json`,
  `executor.live-bybit-vwap.json`, `executor.live-flipster.json`도 같게), `deploy/vwap_switch.py`(같은 값을 씀).

### 11-1. 바꾸는 순서 (서버에서, 딥코인 포지션이 없을 때)

한 단계씩 하고 결과를 확인한 뒤 다음으로 갑니다.

1. **코드 받기:** `cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh`
2. **미리 보기 (아무것도 안 바꿈):** 딥코인 앱에서 선물 잔고(달러)를 보고 그 숫자를 넣습니다.
   ```bash
   cd /opt/crypto-bot-research && sudo python3 deploy/vwap_switch.py --exec deepcoin --balance (딥코인 선물 잔고)
   ```
   - 바뀌는 줄: `ladder` → `{"first_lock": 0.08, "trigger_gap": 0.02, "step": 0.04}`, `leverage_by_symbol` → `{"BTCUSDT": 40, "*": 30}`,
     `liq_guard` → `true`, `liq_guard_mmr` → `0.005`, 그리고 `budget_usd`·`qty_scale`(잔고 기준 크기에서는 쓰지 않음). 다른 줄이 나오면 쓰지 말고
     결과를 보내 주세요.
3. **딥코인 포지션이 없을 때 끄고 쓰기:**
   ```bash
   sudo systemctl stop paperbot-executor-deepcoin
   cd /opt/crypto-bot-research && sudo python3 deploy/vwap_switch.py --exec deepcoin --balance (딥코인 선물 잔고) --write
   ```
4. **확인 (주문 없음):** `cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor-deepcoin.json`
   - `계단: 순ROE 10%에서 8% 잠금, 이후 4%씩`, `배수: BTC 40배, 나머지 30배 (페이퍼 배수 대신)`, `청산가 확인: 켜짐 …`, 마지막 줄 `준비됨`.
5. **켜기:** `sudo systemctl start paperbot-executor-deepcoin` 그리고 `journalctl -u paperbot-executor-deepcoin -n 20`.

**되돌리기:** 끈 뒤 `sudo python3 deploy/vwap_switch.py --exec deepcoin --back --write`(바로 전 사본으로) 그리고 다시 켭니다.

### 11-2. VWAP 페이퍼도 계단 10%→8% (두 분 10/27 "vwap 매매법도 순수익+8%로 해줘")

`deploy/combo.vwap.json`의 `ladder`만 바뀝니다: `{"first_lock": 0.08, "trigger_gap": 0.02, "step": 0.04}`. 모의라 돈·주문은 없습니다.
11-1과 같이(딥코인 포지션이 없을 때) 하면 깔끔합니다. 한 줄씩:

1. 코드 받기(11-1의 1과 같음, 이미 했으면 건너뜀): `cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh`
2. 서버 설정과 새 원본 비교(읽기만): `sudo diff /etc/paperbot/combo-vwap.json /opt/crypto-bot-research/deploy/combo.vwap.json`
   → `first_lock` 0.1 → 0.08, `step` 0.05 → 0.04 두 줄만 나와야 합니다. 다른 줄이 나오면 멈추고 알려 주세요.
3. 백업하고 바꾸기:
   ```bash
   sudo cp -p /etc/paperbot/combo-vwap.json /etc/paperbot/combo-vwap.json.before-8
   sudo install -o root -g paperbot -m 640 /opt/crypto-bot-research/deploy/combo.vwap.json /etc/paperbot/combo-vwap.json
   cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo check-config --config /etc/paperbot/combo-vwap.json
   ```
   → 계단 줄 `순ROE 10%에서 8% 잠금, 이후 4%씩`, 마지막 줄 `준비됨`.
4. 다시 켜기: `sudo systemctl restart paperbot-combo-vwap` (기록에서 이어서 돕니다). 그림자를 켜 두셨다면
   `sudo systemctl restart paperbot-combo-shadow@vwap-4h`도(그림자는 설치된 원본을 바로 읽습니다).

되돌리기: `sudo cp -p /etc/paperbot/combo-vwap.json.before-8 /etc/paperbot/combo-vwap.json` → `sudo systemctl restart paperbot-combo-vwap`.
