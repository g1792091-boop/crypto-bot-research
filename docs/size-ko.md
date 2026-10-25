# 실거래 크기: 진입할 때마다 잔고의 40% (2026-10-25 밤)

두 분 결정: "b로해줘", "파산당하면 파산 당한다는 마인드야 그냥 항상 시드비중 40%로 해줘".

## 무엇이 바뀌나

| | 예전 (`size_from` "paper") | 지금 (`size_from` "equity") |
|---|---|---|
| 크기 정하는 법 | 페이퍼 수량 × `qty_scale`(처음 정한 고정 비율) | **진입하는 순간의 실거래 잔고 × 40%**를 증거금으로, 페이퍼와 같은 배수 |
| 실거래 잔고가 페이퍼와 다르게 움직이면 | 증거금 비중이 40%에서 어긋남(예: 바이비트 약 30%) | 항상 40% |
| 손절이 멀 때 | 손절 한 번 손실이 잔고의 20% 또는 35%를 넘으면 수량을 줄임 | **줄이지 않음** (항상 40%) |
| `qty_scale` | 크기에 씀 | 파일에 남지만 크기에는 안 씀 (기록용) |

그대로인 것:
- 배수: 페이퍼와 같습니다(BTC 40배, 나머지 30배).
- 거래소 최소 주문보다 작으면 건너뜁니다.
- 포지션 크기 상한 `risk.max_notional_usd`($10,000)는 그대로입니다.
  - 잔고 × 40% × 배수가 $10,000를 넘으면 상한까지만 들어갑니다.
  - 상한에 걸리는 잔고는 30배일 때 약 $833, BTC 40배일 때 약 $625입니다.
- 손절·계단·신호등·멈춤 규칙은 바뀌지 않습니다.

**위험:** 손절이 멀어도 줄이지 않으므로 손절 한 번에 잃는 돈이 커질 수 있습니다.
- 배수 30배·증거금 40%에서 손절 거리가 가격의 2%면, 잔고의 약 24%를 잃습니다(비용 포함 약 26%).
- 손절이 강제청산 가격보다 먼 신호는 페이퍼 봇이 먼저 거릅니다.

## 서버에서 (두 분이 직접)

먼저 새 코드를 받습니다. `install.sh`는 페이퍼 봇들을 잠깐 다시 켜니, 추세판단 봇 페이퍼에 포지션이 없을 때 합니다.
```
cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh
```

### 바이비트 · WOO X Pro (지금 켜져 있는 실행기) — 각각 포지션이 없을 때 하나씩

| | 바이비트 | WOO X Pro |
|---|---|---|
| 서비스 | `paperbot-executor` | `paperbot-executor-mexc` |
| 설정 | `/etc/paperbot/executor.json` | `/etc/paperbot/executor-mexc.json` |
| `--exec` | `bybit` | `wooxpro` |

바이비트 예시입니다(WOO X Pro는 위 표의 값으로 바꿉니다).
```
sudo grep '"db"' /etc/paperbot/executor.json
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db (위에서 나온 db 경로)
```
`포지션: null`이면:
```
sudo systemctl stop paperbot-executor
cd /opt/crypto-bot-research && sudo python3 deploy/size_switch.py --exec bybit
cd /opt/crypto-bot-research && sudo python3 deploy/size_switch.py --exec bybit --write
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor.json
sudo systemctl start paperbot-executor
```
- `size_switch.py`를 `--write` 없이 돌리면 바뀔 내용만 보여 줍니다. `--write`를 붙여야 실제로 바뀝니다.
- check-config에서 `크기: 진입할 때마다 실거래 잔고의 40%를 증거금으로 …` 줄과 마지막 줄 `준비됨`이 보여야 합니다.
- 예전 설정은 `….before-size-<시각>`으로 남습니다. 되돌리려면 `--back --write`를 씁니다(실행기를 끈 뒤).

### 딥코인 (VWAP 개선판)
- `deploy/executor.live-deepcoin.json`에 이미 들어 있습니다(`size_from` "equity", `margin_frac` 0.4).
- 새 코드를 받은 뒤 설정을 처음 복사하면 그대로 적용됩니다.
- 새 코드를 받기 전에 이미 복사했다면, 실행기를 처음 켜기 전에 아래를 실행합니다.
  ```
  cd /opt/crypto-bot-research && sudo python3 deploy/size_switch.py --exec deepcoin --write
  ```
- `vwap_switch.py --balance 44`는 그대로 해도 됩니다. 이제 `qty_scale`은 기록용입니다.

코드: `paperbot/executor.py`(`size_from`, `margin_frac`, `_entry_qty`), `deploy/size_switch.py`. 시험: `tests/test_executor_equity_size.py`, `tests/test_size_switch.py`.
