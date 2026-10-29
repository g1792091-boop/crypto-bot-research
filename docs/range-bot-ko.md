# 레인지 봇 (10/26, 10/29 추세 확인을 친구 추세지표로)

> **10/29 바뀐 것:** 추세 확인이 "코인·BTC 1시간 슈퍼트렌드"에서 **친구 추세지표 1시간봉**으로 바뀌었습니다(1-1절, 서버 순서는 3장 E).
> 나머지 규칙은 모두 그대로입니다.

두 분이 10/26에 "그 구조로 가자", "레인지봇을 추세 봇 woo x pro 거래소로 … 원래 있던 추세봇 woo x pro 는 없애고", "진행해줘",
"1패후 24시간 휴식을 왜해 빼"라고 하셔서 만든 봇입니다. 구조의 근거는 `analysis/f7tp10_1026/FINAL_KO.md`(최종 구조)와
`REPORT_KO.md` 17 ~ 23절입니다.

## 0. 먼저 숫자 (솔직하게)

| 기간 | 결과 (지갑 배수, 수수료·미끄러짐 포함) |
|---|---|
| 규칙봇 기간 10/06 ~ 10/25, 시험 엔진(hunt.py F1) | 38승 0패 ×6.24 |
| 같은 기간, **이 봇 코드 그대로 재현** (`analysis/f7tp10_1026/livepar.py`) | 38승 0패 ×6.23, 38개 모두 시험과 같은 거래 |
| 10/01 ~ 10/25, 시험 엔진 / 봇 코드 재현 | 40승 1패 ×5.53 / 40승 1패 ×5.51, 41개 모두 같은 거래 |
| 2025-01 ~ 2026-09 아무 날에 시작한 30일 632개 | ×6에 닿은 30일 없음, 가운데 달 약 ×0.7 |

- 10월처럼 추세가 강한 장에서 잘 됐고, 6 ~ 9월 같은 약한 장에서는 한 달 −30 ~ −60%가 날 수 있습니다.
- 한 번 지면(손절 −50%) 지갑 약 −20%, 한 번 이기면 약 +4.9%. 1패가 약 4승을 지웁니다.
- **다 잃어도 되는 금액으로만** 하세요.

## 1. 어떤 봇인가

- 페이퍼 봇 `paperbot-combo-range` (설정 `/etc/paperbot/combo-range.json`, 기록 `/var/lib/paperbot/combo/range.db`)가 신호를 내고,
  **WOO X Pro 실행기**(`paperbot-executor-mexc`)가 그 페이퍼를 따라 실제 주문을 냅니다.
- WOO X Pro 실행기는 지금까지 추세판단 봇을 따라갔습니다. 아래 C에서 레인지 봇으로 옮기면 **WOO X Pro의 추세판단 봇 실거래는 끝납니다**
  (추세판단 페이퍼 봇과 다른 실행기는 그대로).
- 매매법: 레인지 필터 3중 일치 1시간 (후보 리그 커스텀값 기간 80 · 배수 9.0), 코인 6개(BTC ETH SOL DOGE LTC BCH).

| 단계 | 규칙 |
|---|---|
| 신호 | 1시간봉 마감 때 레인지 필터 방향 · 그 봉 하이킨아시 · 마지막 4시간봉 하이킨아시가 처음 모두 같은 쪽 |
| 추세 확인 | (10/29부터) 그 코인의 친구 추세지표 1시간봉이 신호 쪽 (1-1절). 10/28까지는 그 코인·BTC의 1시간 V3.9 슈퍼트렌드(10, 3) |
| 강제청산 여유 | 손절 거리 + 1시간 ATR이 (1/배수 − 0.5%) 안쪽 (아주 거친 장이면 건너뜀) |
| 진입 | 신호 봉 종가에서 0.2 × ATR(14, 1시간) 되돌림을 최대 60분 기다림 → 닿은 5분봉이 끝나면 다음 5분봉 시가에 시장가. 안 오면 버림 |
| 한 신호씩 | 기다리는 동안·포지션 있는 동안 다른 신호는 안 받음. 같은 시각이면 BTC → ETH → SOL → DOGE → LTC → BCH 순서 |
| 진입 금지 | 한국 시간 토·일, 나스닥 개장 앞뒤 30분, 경제 발표 앞뒤 30분 (신호 때와 진입 때 둘 다 봄) |
| 크기 | BTC 40배, 알트 30배, 증거금 = 그때 잔고의 40%, 포지션 1개 |
| 익절 | 순ROE +10% 고정 (계단 없음) |
| 손절 | 순ROE −50% |
| 없는 것 | 진 뒤 쉬기, 시간 청산, 반대 신호 청산, 신호등, 잔고 바닥 |

- 페이퍼는 익절을 그 가격에 지정가처럼 체결해 수수료가 덜 나가므로, 페이퍼의 이긴 거래는 순ROE가 +12% 안팎으로 보입니다.
  실거래 실행기는 자기 체결가 기준 순ROE +10%에서 시장가로 닫습니다(지정가 안 씀). 그래서 실거래 이긴 거래는 +10% 안팎입니다.

## 1-1. 10/29: 추세 확인을 친구 추세지표로

두 분(10/29): "백테스트는 신경쓰지마 친구 지표 1시간봉 + 레인지 필터 3중 일치 1시간봉으로 가자", "만들어주고 … 포지션 종료되면 바로
돌리려고 미리 만들어줘".

- **추세 확인:** 신호가 나온 1시간봉에서 그 코인의 친구 추세지표(`paperbot/friendtrend.py`) 신호 4개를 봅니다.
  - 4개: 하늘·보라 선, EMA RSI(밴드 가운데 선 색), 찹존, 슈퍼트렌드 평균(14·6 / 14·3)
  - 같은 추세가 2개 이상이면 그 추세입니다. 상승이면 롱 신호만, 하락이면 숏 신호만 받습니다.
  - 횡보(찹존 노랑, 슈퍼트렌드 노랑)가 2개 이상이거나 상승 2·하락 2면 진입하지 않습니다.
  - BTC 방향은 더 이상 보지 않습니다.
- 설정: `range`에 `"friend_tf": "1h"`, `"coin_st": false`, `"btc_st": false` (`deploy/combo.range.json`).
- 진입·청산·크기·진입 금지·한 신호씩·강제청산 확인은 모두 그대로입니다. 실행기(`paperbot-executor-mexc`)도 그대로 페이퍼를 따라갑니다.
- 계산은 시험(`analysis/rangefriend1029/`)에 쓴 것과 같습니다. 6년 치 봉으로 봉마다 같은지 확인했습니다.
- **알아 둘 숫자:**
  - 시험에서 이 설정(칸 A)은 지금 설정보다 나빴습니다. 2021~23, 2024~26 두 기간 모두 거래당 순ROE와 가운데 달이 낮았습니다(`analysis/rangefriend1029/REPORT_KO.md`).
  - 두 분이 그래도 이 설정으로 가기로 정하셨습니다.
  - 진입은 요즘 장 기준 평일 하루 약 2.4 ~ 2.9번으로, 지금보다 20 ~ 30% 많습니다.
- 텔레그램 진입 줄에는 `친구 추세 상승 (하늘·보라 선 상승 · EMA RSI 상승 · 찹존 상승 · 슈퍼트렌드 상승)`이 붙습니다.
- 들어가지 않은 신호 이유: `추세 확인: 친구 추세지표 1시간 하락 (…)(신호 롱와 반대)` 또는 `… 진입 금지 (…)`.
- 사이트 레인지 봇 화면에 코인마다 "친구 추세지표 1시간"(상승·하락·진입 금지)이 나옵니다.

## 2. 준비물

- WOO X Pro 선물 계좌의 지금 잔고 그대로. 키도 지금 WOO X Pro 실행기의 키 그대로(새 키·새 계정 필요 없음).
- 크기는 진입할 때마다 그때 잔고의 40%라, 돈을 넣거나 빼도 따로 할 일이 없습니다(다음 진입부터 반영).

## 3. 서버 순서 (한 줄씩 붙여 넣기)

### A. 설치 — 추세판단 봇 페이퍼에 포지션이 없을 때

`install.sh`는 코드를 바꾸는 동안 페이퍼 봇들을 잠깐 껐다 켭니다(실행기는 건드리지 않음). 그래서 페이퍼 포지션이 없을 때 합니다.

```bash
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo status --db /var/lib/paperbot/combo/live-ac.db
```

- `COMBO@mix: … 포지션 없음`이면 다음 줄로. 포지션이 있으면 닫힐 때까지 기다렸다가 다시.

```bash
cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh
```

- 끝에 `레인지 봇 페이퍼 봇(paperbot-combo-range) 설치만 했습니다` 줄이 나옵니다.

### B. 레인지 페이퍼 봇 켜기 — 언제든 (돈·주문 없음)

```bash
sudo install -o root -g paperbot -m 640 /opt/crypto-bot-research/deploy/combo.range.json /etc/paperbot/combo-range.json
cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo check-config --config /etc/paperbot/combo-range.json
```

- 확인 줄: `손절: 순ROE -50%(…) / 고정 익절 순ROE +10%(…, 계단 없음)`, `추세 확인: 코인·BTC 1시간 슈퍼트렌드(10, 3)가 …`,
  `되돌림 진입: …`, `한 신호씩: …`, `F7_RF_TRIPLE 1시간 - 커스텀값 rf_mult=9.0, rf_period=80`, 마지막 줄 **`준비됨`**.

```bash
sudo systemctl enable --now paperbot-combo-range
systemctl is-active paperbot-combo-range
```

- `active`. 텔레그램에 `[합친 봇 페이퍼 레인지 봇] 시작: …`이 옵니다. 처음 켤 때 바이낸스에서 5분봉 약 125일치를 받느라 1 ~ 2분 걸립니다.
- 1 ~ 2분 뒤 기록 확인:

```bash
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo status --db /var/lib/paperbot/combo/range.db
```

- `마지막 1분봉: (지금에 가까운 시각) KST`, `COMBO@mix: 지갑 $1,000.00, 거래 0번 …`. 이때부터 페이퍼로 돌기 시작합니다.

### C. WOO X Pro 실행기를 레인지 봇으로 옮기기 — 실행기에 포지션이 없을 때만

1) 포지션 확인 → 끄기:

```bash
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-wooxpro-live.db
sudo systemctl stop paperbot-executor-mexc
```

- 첫 줄이 `포지션: null`일 때만 끕니다. 포지션이 있으면 닫힐 때까지 기다립니다.

2) 먼저 보기만 (아직 안 바뀜):

```bash
cd /opt/crypto-bot-research && sudo python3 deploy/range_switch.py
```

- 나오는 줄: `paper_db: "/var/lib/paperbot/combo/live-ac.db" → "/var/lib/paperbot/combo/range.db"`, `stop_from: … → "roe"`,
  `stop_roe: … → 0.5`, `ladder: {…} → null`, `take_profit_roe: … → 0.1`, (아직 아니면) `size_from → "equity"`, `margin_frac → 0.4` 등.
- 레인지 페이퍼 기록이 아직 없거나 실행기가 켜져 있으면 `멈춤 - …`이 나오고 아무것도 바꾸지 않습니다.

3) 바꾸기 → 확인:

```bash
cd /opt/crypto-bot-research && sudo python3 deploy/range_switch.py --write
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor-mexc.json
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh executor preflight --config /etc/paperbot/executor-mexc.json
```

- 예전 설정은 `/etc/paperbot/executor-mexc.json.before-range-<시각>`으로 남습니다.
- check-config에서 볼 줄: `익절: 순ROE +10%에서 시장가로 전부 닫음 (계단 없음)`, `손절: 이 실행기의 체결가에서 순ROE -50% …`,
  `크기: 진입할 때마다 실거래 잔고의 40%를 증거금으로 …`, `배수: BTC 40배, 나머지 30배`, `신호등: 꺼짐`, 마지막 줄 **`준비됨`**.
  preflight도 모두 `[OK]`여야 합니다.

4) 켜기 → 확인:

```bash
sudo systemctl start paperbot-executor-mexc
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-wooxpro-live.db
```

- 기록에 `시작: paper 계좌 COMBO@mix 따라 하기 (페이퍼 DB /var/lib/paperbot/combo/range.db), mainnet, …`. `포지션: null`.
- 레인지 페이퍼가 이미 포지션을 들고 있었으면 `paper 진입이 n초 전이라 따라 하지 않습니다`가 하나 생깁니다. 정상입니다(다음 진입부터).

### D. 되돌리기 — 추세판단 봇으로 다시 (포지션이 없을 때만)

```bash
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-wooxpro-live.db
sudo systemctl stop paperbot-executor-mexc
cd /opt/crypto-bot-research && sudo python3 deploy/range_switch.py --back --write
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor-mexc.json
sudo systemctl start paperbot-executor-mexc
```

- 가장 최근 `.before-range-<시각>` 사본(옮기기 전 설정)으로 돌아갑니다.
- `sudo touch /var/lib/paperbot/STOP`(비상 정지)은 **모든 실행기를** 닫고 멈춥니다. WOO X Pro만 멈출 때는 쓰지 않습니다.

### E. 추세 확인을 친구 추세지표로 바꾸기 (10/29) — WOO X Pro 실행기에 포지션이 없을 때

1) 코드 받기 (A와 같음, 이미 했으면 건너뜀). 페이퍼 봇이 새 코드로 다시 켜지지만, 설정을 바꾸기 전까지는 예전 규칙 그대로입니다.

```bash
cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh
```

2) 실행기 포지션 확인 (`포지션: null`일 때만 다음으로):

```bash
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-wooxpro-live.db
```

3) 설정 바꾸기 → 확인 (예전 설정은 `.before-friend`로 남김):

```bash
sudo cp -p /etc/paperbot/combo-range.json /etc/paperbot/combo-range.json.before-friend
sudo install -o root -g paperbot -m 640 /opt/crypto-bot-research/deploy/combo.range.json /etc/paperbot/combo-range.json
sudo diff /etc/paperbot/combo-range.json.before-friend /etc/paperbot/combo-range.json
cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo check-config --config /etc/paperbot/combo-range.json
```

- diff에는 `"coin_st"`(true → false), `"btc_st"`(true → false), 새 줄 `"friend_tf": "1h"` 세 곳만 나와야 합니다.
- check-config에서 볼 줄: `추세 확인: 친구 추세지표 1시간봉(하늘·보라 선·EMA RSI·찹존·슈퍼트렌드)이 …`, 마지막 줄 **`준비됨`**.

4) 페이퍼 봇 다시 켜기 → 실행기 켜기:

```bash
sudo systemctl enable paperbot-combo-range && sudo systemctl restart paperbot-combo-range
journalctl -u paperbot-combo-range -n 20 --no-pager
sudo systemctl enable --now paperbot-executor-mexc
```

- 텔레그램 `[합친 봇 페이퍼 레인지 봇] 시작: …`에 `추세 확인: 친구 추세지표 1시간봉 …`이 보이면 바뀐 것입니다.
- 되돌리기: 2)처럼 포지션이 없을 때 `sudo install -o root -g paperbot -m 640 /etc/paperbot/combo-range.json.before-friend /etc/paperbot/combo-range.json`
  하고 페이퍼 봇을 다시 켭니다.

## 4. 처음 며칠 지켜볼 것

- 평일 하루 평균 2 ~ 3번 진입합니다(0 ~ 7번). 주말(한국 시간 토·일)은 0번. 신호가 나도 되돌림이 안 오면 버려서 진입이 없는 날도 있습니다.
- 페이퍼와 실거래의 진입이 같은지 하루 한 번 봅니다(사이트 재현 비교, 또는 두 status).
- 실거래는 자기 체결가로 손절·익절을 정하므로 페이퍼와 청산 시각이 몇 분 다를 수 있습니다. 페이퍼는 손절·익절이 나도 실거래를 닫지
  않습니다(실거래는 자기 손절·익절로 닫힘).

## 5. 텔레그램과 사이트

- 레인지 페이퍼 봇은 자기 진입·청산을 텔레그램으로 보냅니다. 진입 줄에 `신호 10-27 10:00 종가 … → 0.2 ATR(…) 아래 …에 닿음,
  10분 뒤 진입 · 코인 슈퍼트렌드 상승 · BTC 슈퍼트렌드 상승`이 붙습니다.
- 진입하지 않은 신호는 이유와 함께 기록됩니다: `한 신호씩: …`, `추세 확인: ETH 1시간 슈퍼트렌드 하락(…)`, `되돌림 안 옴(…)`,
  `강제청산 여유 부족: …`, `주말 …`, `나스닥 개장 …`, `경제 발표 …`.
- 사이트(8093)의 실행기 칸에는 WOO X Pro가 레인지 봇을 따라가는 것으로 보이고, 규칙 목록에 위 규칙이 나옵니다.
- 아침 점검은 이 페이퍼 봇이 멈추면 `sudo systemctl status paperbot-combo-range`를 할 일로 알려 줍니다.

## 6. 주의할 점

- **크기 상한**: WOO X Pro 실행기 설정의 `risk.max_notional_usd`는 $10,000입니다. BTC 40배 × 40%면 잔고의 16배라, 잔고가 약 $625를
  넘으면 BTC 포지션이 상한으로 줄어듭니다. 올릴지는 두 분이 정합니다.
- 실행기의 고정 익절은 반복마다 WOO X Pro의 마지막 체결가를 읽어 판단합니다. 순간적으로 +10%를 찍고 바로 내려오는 경우 페이퍼는 익절,
  실거래는 못 닫는 일이 드물게 생길 수 있습니다.
- 손절·익절은 실거래 자기 체결가 기준이라, 미끄러짐이 크면 페이퍼보다 결과가 조금 나쁩니다.

## 9. 봇 코드 재현

`analysis/f7tp10_1026/livepar.py`: 이 봇 코드(ComboRunner + RangeRunner + `deploy/combo.range.json`)를 바이낸스 5분봉으로 1분씩 다시
돌려(신호 계산 · 슈퍼트렌드 · 되돌림 대기 · 진입 금지 · 익절 / 손절 모두 봇 코드 그대로) 시험 엔진(`hunt.py` F1)과 거래를 하나씩 비교했어요.

| 기간 | 시험 엔진 | 봇 코드 | 같은 거래 |
|---|---|---|---|
| 규칙봇 기간 10/06 ~ 10/25 | 38승 0패 ×6.24 | 38승 0패 ×6.23 | 38 / 38 (진입 분 · 코인 · 방향 · 청산 이유 · 순ROE까지) |
| 10/01 ~ 10/25 | 40승 1패 ×5.53 | 40승 1패 ×5.51 | 41 / 41 (진 거래 하나만 순ROE −49.4% / −50.0%: 손절 가격을 기준가에서 잡는 차이) |

- 처음 재현에서는 봇이 5개(DOGE 1, BCH 3, LTC 1)를 되돌림까지 기다린 뒤 진입을 거절했어요(×4.92). 페이퍼 엔진이 강제청산 여유를
  실제 거래소 단계(지갑이 커지면 BCH · LTC 유지증거금률 0.5% → 1%, DOGE는 처음부터 0.65%)로 한 번 더, 1 ATR을 더해 봤기 때문이에요.
  강제청산 여유는 시험과 같은 식(손절 거리 + 1시간 ATR ≤ 1/배수 − 0.5%) 하나로만 보도록 고쳤고(`liq_buffer_atr` 0), 그 뒤 위 표처럼
  모두 같아졌어요. 실거래 실행기는 따로 자기 거래소 유지증거금률로 손절이 청산가 안쪽인지 한 번 더 봐요(`liq_guard`).
- 결과 파일: `analysis/f7tp10_1026/livepar_rulebot.json`, `livepar_oct.json`.
