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
| 증거금(시드 비중) | 잔고의 40% | **잔고의 30%** (10/19 결정) |
| 그대로 | BTC 40배 / 알트 30배, 한 번에 1포지션, 6코인, 한국 시간 토·일 진입 안 함, 미국 경제 발표 앞뒤 30분·나스닥 개장 뒤 30분 진입 안 함 | 같음 |

**15개 매매법** (같은 시각에 신호가 겹치면 이 순서로 고릅니다)

- A (그대로 11개): V3.9 1시간 · CMO 샌드위치 30분 · EMA9·초피 30분(숏만) · PSAR POC 30분 · CMO 샌드위치 1시간 · MACD 시가범위 돌파 30분 · OBV 추세형 30분 · 뒤집힌 FVG 1시간 · EMA DMI ADX 1시간 · 시가 범위 돌파(ORB) 30분 · 일목·윌리엄스%R 30분
- B (추격 진입 막기 4개): 구조 이어짐 돌파 30분 · 레인지 필터만 1시간 · FVG 되돌림 1시간 · 일목 AO 30분

설정 파일: `deploy/combo.live15.json`.

## 근거와 한계 (솔직하게)

- 규칙봇의 지난 2주 실제 진입을 새 규칙으로 다시 판정: 1포지션·주말 쉼·추격 막기까지 적용하면 평일 하루 6.2번 진입, 58승 4패(94%), 최대 낙폭 20%.
- **이 2주는 15개를 고를 때 쓴 바로 그 기간입니다.** 앞으로는 이보다 낮게 나올 가능성이 큽니다. 같은 장에서 동전 던지기로 들어가도 새 규칙 승률이 75%였습니다.
- 본전 승률은 약 86%(복리 계산, 이길 때 +10%·질 때 −50%+수수료 기준; 단순 합계로는 82~83%). 시드 비중 30%에서 −50% 한 번은 계좌 약 −15%, 이긴 한 번은 약 +3%입니다.
- 위 2주 결과(58승 4패)는 증거금 40%로 계산한 것이라 계좌 ×5.58이었고, 30%로는 같은 2주가 대략 ×3.5배 안팎입니다(손실도 그만큼 작아짐).
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
- **새 실거래 대시보드**도 이때 같이 켜집니다: `http://(Tailscale 주소):8093` (같은 비밀번호, 로그인은 따로). 규칙봇
  대시보드(8080) 메뉴에서는 실거래가 빠집니다. 자세한 것은 `docs/livedash-ko.md`.

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

**5) 연패 멈춤·낙폭 멈춤·신호등 없애기 (10/19 결정, 실행기 설정)**

2)에서 새 코드를 받은 뒤에 합니다. 예전 코드는 이 값들이 없으면 실행기를 켜지 않습니다. 실행기 설정 두 파일에서 `max_consecutive_losses`(연패 멈춤)와 `max_drawdown_pct`(낙폭 50% 멈춤)를 빼고, 신호등을 끕니다(`signal_light_n` 0). 다른 값은 그대로입니다:

```bash
sudo python3 - <<'EOF'
import json
for p in ("/etc/paperbot/executor.json", "/etc/paperbot/executor-mexc.json"):
    d = json.load(open(p, encoding="utf-8"))
    r = d.get("risk", {})
    print(p, "연패 멈춤:", r.pop("max_consecutive_losses", "이미 없음"), "/ 낙폭 멈춤:", r.pop("max_drawdown_pct", "이미 없음"),
          "/ 신호등:", d.get("signal_light_n"), "-> 0")
    d["signal_light_n"] = 0
    d.pop("signal_light_min_win", None)
    open(p, "w", encoding="utf-8").write(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
EOF
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor.json
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor-mexc.json
sudo systemctl restart paperbot-executor paperbot-executor-mexc
```

- 두 check-config 모두 끝 두 줄이 `신호등: 꺼짐 (paper의 모든 진입을 따라감)`, `준비됨`이어야 합니다. 그 바로 위 줄은 `멈춤: 연패·낙폭으로는 멈추지 않음 (비상 정지 파일 /var/lib/paperbot/STOP만)`입니다.
- 실행기 재시작은 **두 실행기 모두 포지션이 없을 때만** 합니다(1)에서 확인한 상태).
- **남는 것:** 비상 정지 파일(`/var/lib/paperbot/STOP`)과 진입 한도(최대 40배, 코인 6개, 포지션 크기, 손절 한 번 최대 35%)는 그대로입니다. 연패나 낙폭으로 저절로 멈추는 일은 없어집니다. 시드 비중 30%에서 −50% 손절 한 번이 계좌 약 −15%라서 연속 3번이면 약 −39%, 4번이면 약 −48%까지 갑니다. 멈추고 싶을 때는 `sudo touch /var/lib/paperbot/STOP`.

## 같이 알아 두실 것

- **신호등은 끕니다** (10/19 결정). 두 실행기가 페이퍼의 모든 진입을 그대로 따라갑니다. 그래서 실거래 결과를 페이퍼와 바로 비교할 수 있고, 예전 A+C 봇의 거래가 새 봇의 따라가기에 영향을 주지도 않습니다. 대신 성적이 나빠질 때 저절로 쉬는 장치는 없습니다(비상 정지 파일만 남음).
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
