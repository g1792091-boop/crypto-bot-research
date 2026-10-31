# 바이비트 봇 (10/29, 친구 매매법 2개)

두 분 결정(10/29):
- "바이비트 봇에 돌아가고 있던 추세판단 매매법 다 빼고 친구가 만든 매매법 2개로 돌릴꺼야"
- "아까 내가 친구가 만든 추세지표 보냈잖아 일단 추세는 그걸로 볼꺼고 … 진입타점 매매법 2개야"
- "Ema rsi가 맞고 연한색에서 진한색으로 변할때 진입이야", "Vwap 아니야"
- "종목이랑 익절은 지금 돌아가고있는 친구봇 매매봇 기준으로", "xrp빼고 btc ltc 넣어주고 손절은 30분봉 atr x3배로 가자 레버리지도 친구봇이랑 똑같이 가자"
- "만들어주고 각 봇들 포지션 종료되면 바로 돌리려고 미리 만들어줘"

코드:
- `paperbot/mixchop.py`: 친구봇(믹스 30분 봇)과 같은 프로그램이고, 설정만 다릅니다.
- `paperbot/friendtrend.py`: 친구 지표 계산입니다.
- 설정: `deploy/mixbybit.live.json`(실거래), `deploy/mixbybit.paper.json`(모의)
- 서비스: `paperbot-mixbybit`(실거래), `paperbot-mixbybit-paper`(모의)
- 테스트: `tests/test_mixbybit.py`

## 1. 규칙

**10/30부터 진입 규칙은 8장의 OBV 50선 하나입니다.** 아래 표의 ①·②는 10/29~30의 규칙입니다(추세·코인·손절·계단·크기는 그대로).

모든 판단은 바이낸스의 **마감된 30분봉**으로, 30분봉이 끝날 때마다 합니다(친구봇과 같음).

| 항목 | 내용 |
|---|---|
| 추세 | 친구 추세지표 30분봉 신호 4개: 하늘·보라 선, EMA RSI(밴드 가운데 선 색), 찹존, 슈퍼트렌드 평균(14·6 / 14·3) |
| 추세 판정 | 같은 추세가 2개 이상이면 그 추세. 횡보(찹존 노랑, 슈퍼트렌드 노랑)가 2개 이상이거나 상승 2·하락 2면 진입 금지 |
| 진입 ① OBV | 추세가 상승일 때 OBV 막대가 연한 초록에서 진한 초록으로 바뀐 봉이면 롱. 하락일 때 연한 빨강에서 진한 빨강이면 숏 |
| 진입 ② 스톡 RSI | 추세가 상승일 때 50선 아래에서 골든 ●이면 롱. 하락일 때 50선 위에서 데드 ●이면 숏 (14·11·4·6, 노이즈 줄이기 보통, 교차 확인 폭 2) |
| 같은 봉에 둘 다 | OBV 먼저 봅니다. 코인끼리는 BTC → ETH → SOL → DOGE → LTC → BCH → ZEC 순서 |
| 코인 | BTC, ETH, SOL, DOGE, LTC, BCH, ZEC (7개) |
| 레버리지 | 40배, ZEC만 20배 (친구봇과 같음). 격리 마진 |
| 크기 | 진입마다 증거금 = 그때 잔고의 40%, 포지션 1개 |
| 손절 | 30분봉 ATR(14) × 3, 진입가에서. 거래소(바이비트)에 바로 걸어 둠 |
| 익절(계단) | 순ROE 10%가 되면 8% 잠금, 15%면 13%, 20%면 18%, 그 뒤로 5%씩. 1분마다 바이낸스 1분봉으로 확인해서 거래소 손절을 올림 |
| 강제청산 확인 | 손절 폭이 (1/배수 − 0.5%)보다 멀면 그 신호는 건너뜀 (40배: 2.0%, 20배: 4.5%). 진입 전에 바이비트의 실제 유지증거금 단계로 한 번 더 봄 |
| 진입 금지 | 한국 시간 토·일, 나스닥 개장 앞뒤 30분, 경제 발표 앞뒤 30분 |
| 없는 것 | 반대 신호 청산, 시간 청산, 잔고 바닥(잔고가 줄어도 멈추지 않음, 레인지 봇과 같음) |
| 수수료 | 순ROE 계산은 바이비트 테이커 0.044% (10/20 실측) |

### 트레이딩뷰 지표와 맞춘 방법

- 친구가 보낸 세 지표(차트 믹스, 차트 믹스 + OBV, 차트 믹스 + 스톡 RSI)의 계산을 한 줄씩 옮겼습니다. 기본 설정 그대로입니다.
- 하늘·보라 선과 슈퍼트렌드는 친구봇이 트레이딩뷰와 소수점까지 맞춘 계산을 그대로 씁니다.
- 레인지 봇 시험에 쓴 계산과 같은 결과가 나오는지 6년 치 봉으로 확인했습니다. 서로 다른 봉이 0개였습니다.
- 바이낸스 봉 1,500개로 계산해도 더 긴 기록으로 계산한 마지막 값과 같습니다.

### OBV "진한색"을 정한 방법

- 트레이딩뷰 OBV 창의 막대는 길이가 앞 봉보다 커지면 진한색, 아니면 연한색입니다.
- 초록과 빨강은 지표 안의 상태입니다. 평균 RSI가 50 위이고 선이 시그널 위면 초록, 반대면 빨강입니다.
- **막대가 거의 안 보이는 봉은 연한색으로 봅니다.**
  - 초록 상태인데 선이 시그널 아래로 내려간 봉은, 지표가 막대를 아주 얇은 선(높이가 값의 100만분의 1)으로 그립니다. 반대 색도 마찬가지입니다.
  - 이런 봉의 진한색·연한색은 시장이 아니라 차트를 어디서부터 불러왔는지에 따라 바뀝니다. 그래서 봇은 이런 봉을 연한색으로 봅니다.
  - 이렇게 정해야 봉 수를 다르게 읽어도 결과가 같습니다(시험으로 확인).
- 빨강에서 연한색을 거치지 않고 바로 진한 초록이 되는 봉은 진입하지 않습니다. 같은 색에서 연한 → 진한일 때만 진입합니다.

## 2. 숫자로 미리 알아 둘 것 (최근 90일 바이낸스 30분봉, 6개 코인)

| 코인 | 손절 폭 가운데값 (ATR × 3) | 강제청산 확인에 걸려 건너뛰는 신호 |
|---|---|---|
| BTC | 1.00% | 3 ~ 5% |
| ETH | 1.36% | 13% |
| SOL | 1.66% | 32% |
| DOGE | 1.81% | 40% |
| LTC | 1.76% | 32 ~ 37% |
| BCH | 2.06% | 53 ~ 56% |

- ZEC는 이 자료에 없어 세지 못했습니다. 20배라 손절 폭이 4.5%까지 됩니다.
- **추세에 맞는 신호는 6개 코인을 합쳐 하루 약 45개**입니다(OBV 약 37개, 스톡 RSI 약 8개). 포지션은 1개라 대부분 건너뜁니다.
  - 그래서 포지션이 닫히면 곧 다음 진입이 나오는 봇입니다.
- **손절 한 번의 크기:** 40배에서 손절 폭 1%면 순ROE 약 −44%이고, 증거금 40%라 잔고 약 −17%입니다.
  - 강제청산 확인 한도(2.0%)에 가까운 손절이면 순ROE 약 −84%, 잔고 약 −33%입니다.
- 백테스트는 하지 않았습니다(두 분: "백테스트는 신경쓰지마").

## 3. 서버 순서 (두 분이 직접, 한 단계씩 결과를 보고)

### A. 코드 받기와 읽기만 하는 점검 — 언제든 (주문 없음)

1. 코드 받기
   ```
   cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh
   ```
   - 페이퍼 봇들만 몇 초 다시 켜집니다. 실행기와 친구봇은 건드리지 않습니다.
2. 설정 파일 복사 (이미 있으면 그대로 둠)
   ```
   sudo test -e /etc/paperbot/mixbybit.json || sudo install -o root -g paperbot -m 640 /opt/crypto-bot-research/deploy/mixbybit.live.json /etc/paperbot/mixbybit.json
   sudo test -e /etc/paperbot/mixbybit-paper.json || sudo install -o root -g paperbot -m 640 /opt/crypto-bot-research/deploy/mixbybit.paper.json /etc/paperbot/mixbybit-paper.json
   ```
3. 점검 (읽기만)
   ```
   sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh mixchop check --config /etc/paperbot/mixbybit.json
   ```
   - 키는 예전 바이비트 실행기와 같은 `/etc/paperbot/executor.env`의 `BYBIT_LIVE_API_KEY` / `BYBIT_LIVE_API_SECRET`입니다. 새로 넣을 것이 없습니다.
   - 잔고, 마진 모드, 열린 포지션, 코인 7개의 바이비트 계약이 나옵니다.
   - **✘가 나온 코인**은 계약이 없거나, 최대 배수가 설정보다 낮거나, 최소 주문보다 작은 코인입니다. 그 코인은 거래하지 않습니다.
4. 트레이딩뷰와 신호 맞춰 보기 (주문 없음)
   ```
   cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.mixchop signals --config /etc/paperbot/mixbybit-paper.json -n 3
   ```
   - 코인마다 OBV 연한→진한과 스톡 RSI ●의 최근 3개를 보여 줍니다.
   - 시각, 종가, 친구 추세(신호 4개), 손절 폭, 진입 또는 X가 나옵니다.
   - 트레이딩뷰 30분 차트(바이낸스 무기한)와 같은지 봅니다.
5. (권장) 모의 켜기 (주문 없음, $100에서 시작)
   ```
   sudo systemctl start paperbot-mixbybit-paper
   ```
   기록은 `/var/lib/paperbot/mixbybit-paper/log.jsonl`에 남습니다.

### B. 실거래 켜기 — A의 결과를 확인한 뒤

1. 예전 바이비트 실행기를 꺼 둔 채로 둡니다. 재부팅해도 켜지지 않게 합니다.
   ```
   sudo systemctl disable --now paperbot-executor
   ```
   - 새 봇의 서비스에는 `Conflicts=`가 있어서, 켜면 예전 실행기를 자동으로 끕니다. 두 봇이 한 계정을 같이 거래하는 일은 없습니다.
2. 켜기
   ```
   sudo systemctl start paperbot-mixbybit
   journalctl -u paperbot-mixbybit -n 30
   ```
   - 텔레그램에 `[바이비트 봇] ▶️ 시작` 메시지가 옵니다. 잔고, 코인 7개, 규칙이 함께 나옵니다.
   - 시작할 때 바이비트 계정을 단방향 모드와 격리 마진으로 바꾸고, 코인마다 레버리지를 맞춥니다.
   - 못 맞춘 코인은 `(꺼짐)`으로 나오고 거래하지 않습니다.
3. 며칠 문제없으면 재부팅 뒤에도 켜지게 합니다.
   ```
   sudo systemctl enable paperbot-mixbybit
   ```

## 4. 멈추기

| 하고 싶은 것 | 명령 |
|---|---|
| 새 진입만 멈춤 (열린 포지션은 손절·계단 유지) | `sudo -u paperbot-exec touch /var/lib/paperbot/exec/mixbybit.STOP` (다시 켜기: `sudo rm /var/lib/paperbot/exec/mixbybit.STOP`) |
| 봇 끄기 | `sudo systemctl stop paperbot-mixbybit` |
| 전부 정리 | 봇을 끈 뒤 바이비트 앱에서 포지션을 시장가로 닫고, 남은 손절 주문을 취소 |

- 봇을 꺼도 거래소에 건 손절은 그대로 남아 포지션을 지킵니다. 계단 이동만 멈춥니다.
- 다시 켜면 거래소의 포지션·손절을 확인하고 계단을 이어서 올립니다.

## 5. 텔레그램 메시지

친구봇과 같은 모양이고, 앞에 `[바이비트 봇]`이 붙습니다.
- 진입: 코인·방향·체결가·배수·크기, 손절 가격과 그 순ROE, 계단 첫 칸 가격.
  - 근거 줄 예: `근거(OBV 진한색): OBV 연한 초록→진한 초록 · 친구 추세 30분 상승 (하늘·보라 선 상승 · EMA RSI 상승 · 찹존 상승 · 슈퍼트렌드 횡보)`
- 계단: 몇 단계, 손절 몇에서 몇으로, 그 순ROE.
- 청산: 손절 / 계단 익절, 손익(잔고 변화), 잔고.

## 6. 알아 둘 점

- 신호와 계단은 바이낸스 캔들로 계산하고, 손절은 바이비트 마지막 가격에 걸립니다. 두 거래소 가격 차이만큼 다를 수 있습니다.
- 진입은 30분봉이 끝나고 몇 초 뒤 시장가입니다. 트레이딩뷰의 봉 종가와 조금 다를 수 있습니다.
- 예전 추세판단 봇 페이퍼(`paperbot-combo`)는 이 봇과 상관없습니다. 기록용으로 그대로 두어도 되고, 끄려면 `sudo systemctl disable --now paperbot-combo`입니다.
- 아침 점검(매일 09:07 한국 시간)과 5분마다 도는 손실 카드가 이 봇 것도 따로 옵니다 (`paperbot-mixbybitcheck*` 타이머).

## 7. 실거래 사이트에서 보기

`/etc/paperbot/mixbybit.json`이 서버에 있으면 사이트가 바이비트 칸을 이 봇으로 바꿉니다. 예전 바이비트 실행기 칸은 사라집니다.

- **한눈에** (사이트 첫 화면): 바이비트 카드가 이 봇의 잔고, 최근 거래, 오늘 손익, 포지션, 지금 진입 가능한지를 보여 줍니다.
- **봇별 › 바이비트 봇**, **바이비트 봇 › 바이비트 관제**: 실거래와 모의를 나란히 봅니다. 상태, 잔고(바닥선 없음), 진입 금지 시간, 포지션과 손절·계단, 최근 48시간 신호와 그 결과가 나옵니다.
- **바이비트 봇 › 바이비트 성적**: 거래 기록, 코인별 성적, 손실 카드, 아침 점검이 나옵니다. **실거래 vs 모의** 표로 두 봇을 한 줄씩 비교합니다.
- **바이비트 봇 › 친구 추세판**: 코인마다 이 봇이 마지막 30분봉에 본 값입니다.
  - 추세와 네 표(하늘·보라 선 · EMA RSI · 찹존 · 슈퍼트렌드)
  - OBV 색(연한색 / 진한색, 연한색→진한색으로 바뀐 봉)
  - OBV 50선 값(10/30부터의 규칙), 스톡RSI K·D와 골든·데드 ●(10/29 규칙의 기록이 있을 때만)
  - 두 매매법이 그 봉에 낸 답
  - 레인지 봇이 본 1시간 추세(레인지 봇 설정을 바꾼 뒤부터)
  - 이 표는 새 코드로 봇을 켠 뒤 첫 30분봉이 끝나야 채워집니다.
- **포지션**: 이 봇의 포지션 카드가 바이비트 자리에 나옵니다.
- 추세판단 봇 화면은 봇별 맨 끝으로 옮겼고, 지난 기록 보관용으로 남겨 둡니다.

## 8. 10/30: OBV 50선 하나로

두 분(10/30, 친구가 보낸 파일 4개와 대화): 예전 두 규칙(OBV 진한색, 스톡RSI)을 빼고 **OBV 50선** 하나로 갑니다.

| 항목 | 내용 |
|---|---|
| 추세 | 그대로: 친구 추세지표 30분봉 네 표. 같은 쪽 2개 이상이면 그 추세, 2:2나 횡보 2개면 진입 안 함 |
| 롱 | 추세 상승 + OBV 막대가 연한 초록 → 진한 초록으로 바뀐 봉 + 그 봉의 OBV 50선 값이 50 아래 |
| 숏 | 추세 하락 + 연한 빨강 → 진한 빨강 + OBV 50선 값이 50 위 |
| 그대로 | 코인 7개, 40배(ZEC 20배), 증거금 40%, 손절 30분 ATR × 3, 계단 순ROE 10%→8% 뒤 5%씩, 진입 금지 시간 |

- OBV 50선 값: OBV 창의 선(자금 흐름과 클링거를 반씩 섞어 쌓은 선)이 그 선의 EMA 52보다 얼마나 위·아래인지를 0~100으로 그린 값입니다.
  50 + 50 × tanh(차이 ÷ (차이의 100봉 표준편차 × 2)). 친구 파일의 기본값 그대로입니다(`paperbot/friendtrend.py` 4장).
- 텔레그램 근거 줄 예: `근거(OBV 50선): OBV 연한 초록→진한 초록 · OBV 50선 아래(41.0) · 친구 추세 30분 상승 (…)`.
- 설정은 `"rules": ["obv50"]` 한 줄만 바뀝니다(`deploy/mixbybit.live.json`, `deploy/mixbybit.paper.json`).

### 8-1. 바꾸는 순서 (서버에서, 봇이 꺼져 있을 때)

1. 코드 받기: `cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh`
2. 설정 바꾸기 (예전 것은 `.before-1030`):
   ```
   sudo cp -p /etc/paperbot/mixbybit.json /etc/paperbot/mixbybit.json.before-1030
   sudo cp -p /etc/paperbot/mixbybit-paper.json /etc/paperbot/mixbybit-paper.json.before-1030
   sudo install -o root -g paperbot -m 640 /opt/crypto-bot-research/deploy/mixbybit.live.json /etc/paperbot/mixbybit.json
   sudo install -o root -g paperbot -m 640 /opt/crypto-bot-research/deploy/mixbybit.paper.json /etc/paperbot/mixbybit-paper.json
   sudo diff /etc/paperbot/mixbybit.json.before-1030 /etc/paperbot/mixbybit.json
   ```
   - diff에는 `"rules"` 줄 하나(`["obv", "srsi"]` → `["obv50"]`)만 나와야 합니다.
3. 확인 (읽기만):
   ```
   sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh mixchop check --config /etc/paperbot/mixbybit.json
   cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.mixchop signals --config /etc/paperbot/mixbybit-paper.json -n 3
   ```
   - check에서 볼 줄: `매매법·손절: OBV 50선 · 손절 ATR 3배(모든 코인) · 신호 30분봉 · 추세: 네 표 중 같은 쪽 2개 이상`.
4. 켜기: `sudo systemctl enable --now paperbot-mixbybit paperbot-mixbybit-paper` 그리고 `journalctl -u paperbot-mixbybit -n 30`.
   - 바이비트에 포지션이 남아 있으면 켤 때 그 포지션을 이어받아 손절·계단을 계속 봅니다.
- 되돌리기: 끄고 `sudo cp -p /etc/paperbot/mixbybit.json.before-1030 /etc/paperbot/mixbybit.json`(모의도 같은 식) 뒤 다시 켭니다.

## 9. 10/31 저녁: OBV 진한색 + AC (50선 조건 삭제)

두 분(10/31 저녁, 친구 지표 'OBV MACD'): "30분봉 진입 추세는 그대로 두고 진입 방식만 바꾸는데 … 50일선위 숏 아래 롱은 삭제".
두 분 답: '초록 진한선' = 지금 봇이 보는 OBV 막대의 연한 초록 → 진한 초록.

| 항목 | 내용 |
|---|---|
| 추세 | 그대로: 친구 추세지표 30분봉 네 표. 같은 쪽 2개 이상이면 그 추세, 2:2나 횡보 2개면 진입 안 함 |
| 롱 | 추세 상승 + OBV 막대 연한 초록 → 진한 초록 + 그 봉의 AC 막대가 **플러스 양봉**(0 위, 앞 막대보다 커져 초록) |
| 숏 | 추세 하락 + 연한 빨강 → 진한 빨강 + AC 막대가 **마이너스 음봉**(0 아래, 앞 막대보다 작아져 빨강) |
| 진입 금지 | 상승인데 플러스 음봉, 하락인데 마이너스 양봉. 진한 초록인데 AC가 마이너스(양봉·음봉 모두)도 진입 안 함(진입 조건이 플러스 양봉뿐이라서) |
| 삭제 | OBV 50선 조건(50 아래 롱, 50 위 숏) |
| 그대로 | 코인 7개, 40배(ZEC 20배), 증거금 40%, 손절 30분 ATR × 3, 계단 순ROE 10%→8% 뒤 5%씩, 진입 금지 시간 |

- AC 막대: 'OBV MACD'의 기본 히스토그램('AC 오실레이터 (가속)')입니다. (OBV 선 − 조건 시그널선) − 그 값의 SMA 5.
  앞 막대보다 커지면 초록(양봉), 작아지면 빨강(음봉). OBV 선과 조건 시그널선은 지금 봇이 쓰는 OBV 창과 같은 식입니다
  (`paperbot/friendtrend.py` 8장).
- 텔레그램 근거 줄 예: `근거(OBV 진한색 + AC): OBV 연한 초록→진한 초록 · AC 플러스 양봉(0.42) · 친구 추세 30분 상승 (…)`.
- 신호가 막힌 이유 예: `OBV 진한 초록인데 AC 플러스 음봉(0.12)`.
- 설정은 `"rules": ["obvac"]` 한 줄만 바뀝니다(`deploy/mixbybit.live.json`, `deploy/mixbybit.paper.json`). 시험: `tests/test_rules1031b.py`.

### 9-1. 바꾸는 순서 (서버에서)

1. 코드 받기: `cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh`
2. 설정 바꾸기 (예전 것은 `.before-1031b`):
   ```
   sudo cp -p /etc/paperbot/mixbybit.json /etc/paperbot/mixbybit.json.before-1031b
   sudo cp -p /etc/paperbot/mixbybit-paper.json /etc/paperbot/mixbybit-paper.json.before-1031b
   sudo install -o root -g paperbot -m 640 /opt/crypto-bot-research/deploy/mixbybit.live.json /etc/paperbot/mixbybit.json
   sudo install -o root -g paperbot -m 640 /opt/crypto-bot-research/deploy/mixbybit.paper.json /etc/paperbot/mixbybit-paper.json
   sudo diff /etc/paperbot/mixbybit.json.before-1031b /etc/paperbot/mixbybit.json
   ```
   - diff에는 `"rules"` 줄 하나(`["obv50"]` → `["obvac"]`)만 나와야 합니다.
3. 확인 (읽기만): `sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh mixchop check --config /etc/paperbot/mixbybit.json | tail -8`
   - 볼 줄: `매매법·손절: OBV 진한색 + AC · 손절 ATR 3배(모든 코인) · 신호 30분봉 · 추세: 네 표 중 같은 쪽 2개 이상`.
4. 다시 켜기: `sudo systemctl restart paperbot-mixbybit paperbot-mixbybit-paper`
   - 들고 있던 포지션은 그대로 이어받아 손절·계단을 계속 봅니다.
- 되돌리기: `.before-1031b` 파일을 다시 복사하고 다시 켭니다.

