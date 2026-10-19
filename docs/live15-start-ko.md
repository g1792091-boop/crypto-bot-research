# 새 실거래봇 "규칙봇 15" 바꾸는 순서 (10/19 결정, 10/20 시작)

지금 돌고 있는 A+C 합본 페이퍼 봇의 **설정만 바꿉니다.** 페이퍼 봇 DB(`/var/lib/paperbot/combo/live-ac.db`)와 계좌(`COMBO@mix`)는 그대로라서 바이비트·MEXC 실행기 설정은 손대지 않습니다. 실행기는 지금처럼 이 페이퍼 계좌의 진입·잠금·청산을 따라갑니다.

## 무엇이 바뀌나

| 항목 | A+C 합본 (지금) | 규칙봇 15 (새 봇) |
|---|---|---|
| 매매법 | 27개 · 세팅 95개 (연구 조건) | **규칙봇 기본값 15개** (30분·1시간만) |
| 손절 | 3 ATR (강제청산 안쪽으로 당김) | **순ROE −50% 고정** (수수료·슬리피지 포함: BTC 40배 가격 1.11%, 알트 30배 1.53%) |
| 계단 익절 | 11%→10%, 그 뒤 3%씩 | **11%→10%, 15%→12%, 20%→17%, 25%→22%, 그 뒤 5%마다 (닿은 순ROE − 3%)** |
| 빠른 손절 | 없음 | **같은 매매법이 반대 신호를 내면 바로 청산** (첫 잠금 +10% 전까지만) |
| 추격 진입 막기 | 없음 | **B 4개만**: 롱은 7일 범위 위 20% 또는 24시간 고점 쪽 10% 안이면 진입 안 함 (숏은 아래쪽) |
| 그대로 | BTC 40배 / 알트 30배, 증거금 40%, 한 번에 1포지션, 6코인, 한국 시간 토·일 진입 안 함, 미국 경제 발표 앞뒤 30분·나스닥 개장 뒤 30분 진입 안 함 | 같음 |

**15개 매매법** (같은 시각에 신호가 겹치면 이 순서로 고릅니다)

- A (그대로 11개): V3.9 1시간 · CMO 샌드위치 30분 · EMA9·초피 30분(숏만) · PSAR POC 30분 · CMO 샌드위치 1시간 · MACD 시가범위 돌파 30분 · OBV 추세형 30분 · 뒤집힌 FVG 1시간 · EMA DMI ADX 1시간 · 시가 범위 돌파(ORB) 30분 · 일목·윌리엄스%R 30분
- B (추격 진입 막기 4개): 구조 이어짐 돌파 30분 · 레인지 필터만 1시간 · FVG 되돌림 1시간 · 일목 AO 30분

설정 파일: `deploy/combo.live15.json`.

## 근거와 한계 (솔직하게)

- 규칙봇의 지난 2주 실제 진입을 새 규칙으로 다시 판정: 1포지션·주말 쉼·추격 막기까지 적용하면 평일 하루 6.2번 진입, 58승 4패(94%), 최대 낙폭 20%.
- **이 2주는 15개를 고를 때 쓴 바로 그 기간입니다.** 앞으로는 이보다 낮게 나올 가능성이 큽니다. 같은 장에서 동전 던지기로 들어가도 새 규칙 승률이 75%였습니다.
- 본전 승률은 하루 6번 기준 약 89%(계산). −50% 한 번은 계좌 약 −20%입니다.
- 첫 1~2주 페이퍼 승률을 이 숫자들과 비교해서 판단하세요.

## 바꾸는 순서 (지금 포지션이 끝난 뒤)

**1) 두 실행기 모두 포지션이 없는지 확인**

```bash
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-bybit-live.db
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-mexc-live.db
```

- 둘 다 `포지션: null`일 때만 다음으로 갑니다. 거래소 앱에서도 열린 포지션·남은 주문이 없는지 봅니다.

**2) 코드 받기**

```bash
cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh
```

- 설치가 끝나면 페이퍼 봇은 아직 **예전 설정(A+C)** 으로 다시 켜져 있습니다. 새 코드는 예전 설정을 똑같이 돌립니다.
- 실행기는 install.sh가 다시 켜지 않습니다. 그대로 둡니다.

**3) 새 설정 넣기 (예전 설정은 따로 보관)**

```bash
sudo cp -p /etc/paperbot/combo.json /etc/paperbot/combo.json.ac-1019
sudo install -o root -g paperbot -m 640 /opt/crypto-bot-research/deploy/combo.live15.json /etc/paperbot/combo.json
cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo check-config --config /etc/paperbot/combo.json
```

- check-config에서 확인할 줄:
  - `손절: 순ROE -50%(수수료·슬리피지 포함: 40배 가격 1.11%, 30배 가격 1.53%)`
  - `계단 익절: 순ROE 11%에서 10% 잠금, 15%에서 12%, 20%에서 17%, 그 뒤 5%마다 (닿은 순ROE - 3%)`
  - `빠른 청산: 같은 매매법이 반대 신호를 내면 바로 청산 (첫 잠금 +10% 전까지만, 잠긴 뒤에는 계단 익절만)`
  - `추격 진입 막기: 4개 매매법 (...)`
  - 매매법 1~15번 목록, 마지막 줄 **`준비됨`**

**4) 페이퍼 봇만 다시 켜기**

```bash
sudo systemctl restart paperbot-combo
```

- 텔레그램에 `[합친 봇 페이퍼 규칙봇 15] 시작: 매매법 15개 ... 손절 순ROE -50% ... 계단 익절 ... 빠른 청산 ...(첫 잠금 전까지만), 추격 진입 막기 4개, 포지션 1개` 메시지가 옵니다.
- 예전 매매법의 대기 신호가 남아 있었다면 "설정이 바뀜: 예전 매매법의 대기 신호 n개 ... 버렸습니다" 알림이 남습니다. 정상입니다(진입하지 않음).
- **실행기는 다시 켜지 않습니다.** 같은 페이퍼 DB를 계속 읽습니다.

## 같이 알아 두실 것

- **신호등:** 바이비트는 페이퍼 최근 20번 중 85%, MEXC는 90% 이상 이겼을 때만 따라갑니다. 새 봇의 기대 승률(89~94%) 근처라서, 특히 **MEXC는 20번 중 3번만 져도 따라가기를 멈춥니다**(페이퍼는 계속 돌고, 기록이 회복되면 다시 따라감). 신호등은 예전 A+C 봇의 거래도 함께 셉니다(같은 계좌). 바꾸려면 `/etc/paperbot/executor-mexc.json`의 `signal_light_min_win`을 고치고, **포지션이 없을 때** `sudo systemctl restart paperbot-executor-mexc`.
- **대시보드·아침 점검의 5년 기준표**(`combo.live-ac.expected.json`, `likely.json`)는 예전 A+C 봇의 것이라 새 설정에서는 쓰지 않습니다("이 설정의 5년 기준표가 없어요"로 나옴). 새 봇은 백테스트 없이 시작했기 때문입니다.
- **페이퍼 계좌 기록은 이어집니다.** 순위표에서 예전 매매법 거래는 지금 설정에 없는 매매법으로 따로 표시됩니다.
- **수수료:** 계산은 테이커 0.05% + 슬리피지 0.02%로 했습니다. 바이비트 0.055%, MEXC 0.06~0.08%라 실제는 조금 더 나쁩니다.

## 되돌리기 (A+C로)

포지션이 없을 때:

```bash
sudo install -o root -g paperbot -m 640 /etc/paperbot/combo.json.ac-1019 /etc/paperbot/combo.json
cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo check-config --config /etc/paperbot/combo.json
sudo systemctl restart paperbot-combo
```
