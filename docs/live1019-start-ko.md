# 10/19(월) 실거래 시작 순서: 바이비트 $100 + MEXC $100

## ★ 최종 시작 순서 (10/19 확정 구성, 이 장만 따라 하세요)

확정 구성:
- **페이퍼 봇 1개: A+C 합본, 매매법 27개·세팅 95개** (10/19 정리). 설정 `deploy/combo.live-ac.json`, DB `/var/lib/paperbot/combo/live-ac.db`.
  백테스트: 평일 하루 3.09번, 승률 91.3%, 월 중간 x7.91, 손실 난 달 0/81 (바이비트 수수료).
- **바이비트 실행기:** $100, 신호등 최근 20번 중 85% 이상일 때만 따라감.
- **MEXC 실행기:** $100, 신호등 최근 20번 중 90% 이상일 때만 따라감.
- 두 실행기 모두 같은 페이퍼 계좌(`COMBO@mix`)를 따라갑니다.

이 장 아래의 옛 장들(고원형 합본 `live-plateau37`, A 최고형 `live16w` 예시)은 비교 기록입니다. 파일 이름은 이 장을 따르세요. 봇 설명은 [최종 설계](live1019-final-design-ko.md)와 [봇 이해하기](live1019-bot-guide-ko.md)에 있습니다.

**1) 멈추고 코드 받기**

```bash
sudo touch /var/lib/paperbot/STOP
sudo systemctl stop paperbot-executor paperbot-executor-mexc paperbot-combo
```

- 거래소 앱에서 두 계정 모두 열린 포지션과 남은 주문이 없는지 봅니다.
- 2장의 명령으로 코드를 받습니다. 키가 아직 없으면 1장·3장을 먼저 합니다.
- `paperbot-combo2`를 켠 적이 있으면 `sudo systemctl stop paperbot-combo2`로 끕니다. 이 구성에서는 쓰지 않습니다.

**2) 페이퍼 봇 (A+C 합본)**

```bash
sudo cp /opt/crypto-bot-research/deploy/combo.live-ac.json /etc/paperbot/combo.json
cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo check-config --config /etc/paperbot/combo.json
```

마지막 줄이 **"준비됨"**이면 켭니다.

```bash
sudo systemctl start paperbot-combo
sudo journalctl -fu paperbot-combo      # "[합친 봇 페이퍼 A+C 합본] 시작" 확인 (1분봉 7일치를 받느라 몇 분 걸림)
```

**3) 바이비트 실행기**

```bash
sudo nano /etc/paperbot/executor.json
```

```json
{
  "exchange": "bybit",
  "mode": "mainnet",
  "account": "COMBO@mix",
  "paper_db": "/var/lib/paperbot/combo/live-ac.db",
  "db": "/var/lib/paperbot/exec/executor-bybit-live.db",
  "budget_usd": 100,
  "qty_scale": 0.1,
  "entry_source": "paper",
  "stop_from": "ratio",
  "signal_light_n": 20,
  "signal_light_min_win": 0.85,
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

```bash
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor.json
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh executor preflight --config /etc/paperbot/executor.json
```

- check-config 끝 두 줄: **"신호등: 켜짐 - paper 최근 20번 중 85% 이상 이겼을 때만 진입을 따라감"**, **"준비됨"**.
- preflight는 모든 줄이 `[OK]`여야 합니다(5장).

**4) MEXC: 연습 → 실행기**

- 먼저 6장의 연습 두 단계(`mexc drill`, `mexc drill --confirm-order REAL_ORDER`)를 합니다. 모든 줄이 OK이고 `fee_rate_pct`가 0.08 근처여야 합니다.
- `/etc/paperbot/executor-mexc.json`은 3)의 내용과 같고 아래 세 줄만 다릅니다.

```json
  "exchange": "mexc",
  "db": "/var/lib/paperbot/exec/executor-mexc-live.db",
  "signal_light_min_win": 0.9,
```

(`"paper_db"`는 바이비트와 같은 `/var/lib/paperbot/combo/live-ac.db`입니다.)

```bash
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor-mexc.json
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh executor preflight --config /etc/paperbot/executor-mexc.json
```

- check-config 끝 두 줄: **"신호등: 켜짐 - paper 최근 20번 중 90% 이상 …"**, **"준비됨"**.

**5) 켜기**

```bash
sudo rm -f /var/lib/paperbot/STOP
sudo systemctl start paperbot-executor paperbot-executor-mexc
sudo journalctl -fu paperbot-executor -u paperbot-executor-mexc
```

- 평일 하루 평균 3번쯤 진입합니다. 몇 시간 동안 진입이 없을 수도 있습니다.
- **첫 거래는 두 분이 앱으로 같이 봅니다.** 진입 → 손절 주문 걸림 → 순ROE 11%에서 잠금 이동 → 청산 → 손익이 앱과 같음.
- **10/19 두 분 결정:** 하루 손실 한도($40)와 지갑 금액 상한($120) 확인은 없앴습니다. 서버의 `/etc/paperbot/executor.json`, `executor-mexc.json`에 `"daily_max_loss_usd"` 줄이 있으면 지우고 check-config를 다시 하세요.
- **새 페이퍼 DB라 거래가 20번 쌓이기 전(약 1주)에는 신호등에 판단 근거가 없어서 모든 진입을 따라갑니다.** 그동안은 3연패와 낙폭 50% 멈춤 장치(9장)가 지킵니다.

**6) 매일 볼 것**

```bash
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo status --db /var/lib/paperbot/combo/live-ac.db
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-bybit-live.db
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-mexc-live.db
```

- **페이퍼 최근 20번 승률이 가장 중요한 숫자입니다.**
  - 백테스트는 91%입니다. 하지만 커스텀값 흔들기 시험과 처음 보는 기간 시험은 75~86%를 가리킵니다.
  - 84% 이상이면 버는 쪽, 80% 안팎이면 손해 쪽입니다.
- 신호등이 빨강이 되면 텔레그램이 옵니다. 페이퍼는 계속 거래하고, 승률이 돌아오면 실거래도 자동으로 다시 따라갑니다.
- 페이퍼와 실거래가 같은 신호에 다르게 움직였거나, "거래소 기록과 다릅니다" 알림이 오면 알려 주세요.
- 며칠 문제없으면 부팅 때 자동으로 켜지게 합니다: `sudo systemctl enable paperbot-combo paperbot-executor paperbot-executor-mexc`.

---

두 분이 10/18 밤에 정한 것:
- 매매법: 16개 매매법 봇(설정 78개). 2020-01~2026-09 전체 백테스트가 가장 좋았던 조합입니다.
- 고정 규칙: BTC 40배, 알트 30배, 계단식 익절(ROE 11%에서 10% 잠금, 이후 3%씩), 증거금 = 계좌의 40%, 한 번에 한 포지션, 코인 6개.
- 주말(한국 시간 토·일)에는 진입하지 않습니다. 미국 경제 발표(CPI·고용·FOMC·PCE) 앞뒤 30분에도 진입하지 않습니다.
- 봇 두 개를 따로 돌립니다. 바이비트 $100, MEXC $100. 둘 다 같은 신호(같은 페이퍼 계좌)를 따라갑니다.

## 버전 비교와 추천 (10/18 밤 시험 결과)

같은 매매법 계열에서 만든 네 가지 버전입니다. 숫자는 2020-01~2026-09, 실거래 규칙(주말 쉼, 발표 30분 금지)을 넣은 백테스트입니다.

| | 지금 버전 | 안정 버전 | 고원형 | **고원형 합본 (추천)** |
|---|---|---|---|---|
| 설정 파일 | `combo.live16w.json` | `combo.live16w-stable.json` | `combo.live16w-plateau.json` | **`combo.live-plateau37.json`** |
| 매매법 / 설정 | 15 / 78 | 13 / 38 | 12 / 25 | 13 / 37 |
| 평일 하루 진입 | 2.6번 | 1.7번 | 1.05번 | 1.34번 |
| 승률 | 92.0% | 85.8% | 89.5% | 88.5% |
| 한 달 중간값 | 6.0배 | 1.9배 | 1.8배 | 2.0배 |
| 손실 난 달 (81개월) | 0 | 14 | 6 | 6 |
| 가장 나쁜 달 | 1.66배 | 0.45배 | 0.52배 | 0.75배 |
| 커스텀값 ±10% 바꾸면 | 0.55~1.04배로 무너짐 | 0.52~0.98배로 무너짐 | 1.4배 유지 | 고원형 설정만 모음 |
| 비용 2배 | 2.2배 | 1.0배 (본전) | 1.24배 | 1.15배 |
| 같은 방식을 2020~24년에만 맞춰 2025~26년(처음 보는 기간)에 돌리면 | 승률 74.4%, 한 달 0.28배 | 77.1%, 0.41배 | 77.3%, 0.70배 | **78.3%, 0.77배 (가장 덜 잃음)** |
| 최대 낙폭 | -72% | -78% | -83% | -73% |

- **커스텀값 시험**: 지금 버전은 커스텀값을 10%만 바꿔도 대부분의 달이 손실로 바뀝니다. 92%와 한 달 6배는 정확히 그 숫자에서만 나옵니다(과최적화).
- **고원형**: 값을 10% 내려도, 그대로여도, 10% 올려도 모두 버는 설정만 남긴 것입니다. 숫자 하나에 덜 기댑니다.
- **처음 보는 기간 시험**: 8가지가 넘는 방법을 2020~24년에 맞춰 2025~26년에 돌렸습니다. 모두 승률 75~78%로 모였고, 손익분기(약 78%) 근처이거나 조금 아래였습니다. 고원형 합본이 가장 덜 잃었지만 아직 플러스는 아닙니다.
- **추천: 고원형 합본.** 백테스트 숫자는 낮지만 실거래에서 백테스트와 덜 어긋날 버전입니다. 지금 버전의 한 달 6배는 기대하지 않는 것이 정직합니다.

**고원형 합본으로 $100 시작한 첫 한 달** (거래를 섞어 2만 번 돌린 결과)

| 실거래 승률 | 한 달 뒤 중간값 | $100 아래로 끝남 | 한 번이라도 $50 아래 |
|---|---|---|---|
| 88.5% (백테스트 그대로) | $198 | 10% | 3% |
| 85% | $155 | 22% | 7% |
| 80% | $109 | 44% | 19% |

## 10/19 새벽 추가 시험 (모두 "처음 보는 기간"으로 판정)

고정 규칙은 그대로 두고, 과거로 고른 봇이 다음 기간에도 통하는지 본 시험입니다.

| 시험 | 고른 기간 성적 | 처음 보는 기간 성적 |
|---|---|---|
| 2025년 12월까지 최대한 보정 → 2026년 1~9월 | 승률 90.8%, 한 달 x6.17, 손실 달 0/72 | **승률 73.5%, x0.35, 손실 달 9/9** |
| A의 매매법을 모두 뺀 다른 매매법 16개 (2020~24 → 2025~26) | 91.7%, x2.5 | 73.8%, x0.60, 손실 달 17/21 |
| 자동 보정: 손실 난 세팅을 자동으로 끄고 켜기 (22가지) | - | 최고 80% (진입 하루 0.2번), 고른 방식은 효과 없음 |
| 합의 진입: 여러 매매법이 같은 방향일 때만 (42가지) | - | 74~79% |
| (연구용) 익절 구조 30% 잠금 | x17 | 58.3%, x0.29 |
| 매달 그때까지의 과거만 보고 세팅 다시 고르기 | 2021~24도 같은 방식: 80.0%, x0.99 | 76~79%, x0.5~0.95 |
| 머신러닝 필터 (2020~23 학습, 2024로 기준 선택) | - | 78~80%, x0.71 |
| 참고: 같은 자리·같은 손절에서 방향을 동전으로 | - | 74.2% |

왜 고른 기간만 좋은가 (데이터로 확인):
- 같은 고르기 방식을 **방향을 동전으로 정한 가짜 매매법**에 쓰면 2020~2026 전체 백테스트가 승률 89.6%, 한 달 x2.91입니다(진짜 매매법은 89.2%, x3.07).
- 2020~24년 성적 상위 10% 세팅(승률 84.9%)은 2025~26년에 78.3%, 하위 10%(73.0%)는 73.4%였습니다. 진짜 실력 차이는 약 5%포인트이고, 나머지는 고른 기간의 운입니다.
- 매달 과거만 보고 고르는 정직한 방식은 2021~24년 안에서도 승률 80%, 한 달 x0.99였습니다. 92%는 지나간 기간을 보고 고를 때만 나오는 숫자입니다.

- 어떤 방법으로 골라도 처음 보는 기간에서는 승률 73~80%로 모였습니다. 고정 익절 구조(가격 0.275% 익절 대 약 1% 손절)에서는 무작위 진입도 약 78%가 나옵니다.
- 지금까지 가장 덜 잃은 방법은 B 안정형 계열(78.3%, x0.77)입니다.

## 신호등 (선택, 10/19 아침 추가)

실행기 옵션입니다. **페이퍼 봇의 최근 N번 거래 중 일정 비율 이상 이겼을 때만** 실거래 진입을 따라갑니다.
- 페이퍼 봇은 신호등과 상관없이 계속 거래합니다. 그래서 성적이 회복되면 실거래도 자동으로 다시 시작합니다.
- 승률을 올리는 장치가 아닙니다. **봇이 안 맞는 시기에 실거래를 쉬게 해서 손실을 줄이는 장치**입니다.
- 기본은 꺼짐입니다. 켜지 않으면 지금과 똑같이 동작합니다.

같은 방식을 2020~24년에만 맞춘 봇으로 2025~26년(처음 보는 기간)을 본 결과입니다.

| 봇 (수수료) | 신호등 | 2020~24 월 중간값 | 2025~26 월 중간값 | 2025~26 손실 난 달 |
|---|---|---|---|---|
| A+C 방식 (바이비트) | 끔 | x11.6 | x0.24 | 20/21 |
| | 최근 20번 중 85% | x10.2 | x0.65 | 18/21 |
| | 최근 20번 중 90% | x6.0 | **x1.00** | 10/21 |
| B 방식 (MEXC) | 끔 | x1.82 | x0.60 | 17/21 |
| | 최근 20번 중 80% | x1.74 | x0.84 | 13/21 |
| | 최근 20번 중 90% | x1.20 | **x1.00** | 6/21 |

실제로 쓸 봇의 전체 백테스트(2020~2026.09)에서는 이렇게 달라집니다.

| 봇 | 신호등 | 2020~24 월 중간값 | 2025~26 월 중간값 |
|---|---|---|---|
| A+C 합본 (바이비트) | 끔 / 85% / 90% | x7.53 / x5.53 / x3.18 | x7.66 / x7.29 / x7.29 |
| B 안정형 (MEXC) | 끔 / 80% / 90% | x1.63 / x1.49 / x1.13 | x1.51 / x1.47 / x1.19 |

정리하면, 기준을 높일수록 봇이 무너지는 시기의 손실은 줄고, 잘 맞는 시기의 수익도 조금 줄어듭니다.

켜는 법: 실행기 설정(`/etc/paperbot/executor.json`, `/etc/paperbot/executor-mexc.json`)에 두 줄을 넣습니다.

```json
  "signal_light_n": 20,
  "signal_light_min_win": 0.85,
```

- `check-config` 결과에 "신호등: 켜짐 - paper 최근 20번 중 85% 이상 …"이 나오면 맞게 들어간 것입니다.
- 새 페이퍼 봇은 거래가 20번 쌓이기 전까지 모든 진입을 따라갑니다. 처음 며칠은 기존 멈춤 장치(3연패, 낙폭 50%)가 지킵니다.
- 빨간불일 때는 텔레그램으로 "신호등 빨강: paper 최근 20번 중 16번 이김(80%, 기준 85%) → … 진입을 따라 하지 않습니다"가 옵니다.

## 거래소 수수료 (10/19 새벽 확인)

백테스트는 테이커 수수료 0.05%를 가정했습니다. 실제 수수료는 다릅니다.
- 바이비트: 일반 등급(VIP0) 무기한 선물 테이커 0.055%, 메이커 0.02%.
- MEXC: **API 주문은 메이커 0.06%, 테이커 0.08%** (MEXC 공지 2026-06-01). 앱의 0% 이벤트와 MX 할인은 API 주문에 적용되지 않습니다. MEXC 연습 주문 결과의 `fee_rate_pct`로 실제 수수료율을 꼭 확인하세요(6장).

진입과 청산은 모두 시장가(테이커)라서, 수수료는 이 숫자로 다시 계산했습니다. 2020-01~2026-09, 실거래 규칙.

| 봇 | 수수료 | 승률 | 한 달 중간값 | 손실 난 달 (81개월) |
|---|---|---|---|---|
| A 최고형 (`combo.live16w.json`) | 백테스트 0.05% | 92.0% | 6.0배 | 0 |
| | 바이비트 0.055% | 91.9% | 5.65배 | 0 |
| | MEXC API 0.08% | 90.9% | **4.0배** | 0 |
| B 안정형 (`combo.live-plateau37.json`) | 백테스트 0.05% | 88.5% | 1.97배 | 6 |
| | 바이비트 0.055% | 88.4% | 1.90배 | 6 |
| | MEXC API 0.08% | 87.4% | **1.54배** | 13 |

같은 방식을 2020~24년에만 맞추고 2025~26년(처음 보는 기간)에 돌린 정직한 숫자(B 안정형 계열):

| 수수료 | 승률 | 한 달 중간값 | 손실 난 달 (21개월) |
|---|---|---|---|
| 0.05% | 78.3% | 0.77배 | 14 |
| 바이비트 0.055% | 78.1% | 0.75배 | 15 |
| MEXC API 0.08% | 76.9% | 0.60배 | 17 |

- 거래가 많은 봇일수록 수수료 영향이 큽니다. 같은 봇이면 바이비트 쪽이 낫습니다.
- 그래서 A 최고형(거래가 더 많음)은 바이비트에 두는 것이 수수료 면에서 유리합니다.

## 0. 백테스트 숫자 (지금 버전 기준, 알고 시작할 것)

2020-01~2026-09, 실거래 규칙(주말 쉼, 발표 30분)을 넣은 결과입니다.

| 항목 | 값 |
|---|---|
| 거래 수 | 4,592번 (평일 하루 약 2.6번) |
| 승률 | 92.0% (롱 92.2%, 숏 91.8%) |
| 평균 이익 / 평균 손실 | ROE +13.1% / -38.9% |
| 한 달 배수 중간값 | 약 5.9배 (바이비트 수수료 0.055%로 계산하면 5.65배) |
| 손실 난 달 | 81개월 중 0개월 |
| 2026년 1~9월 | 6.4 / 4.1 / 30.6 / 6.0 / 8.3 / 7.3 / 26.3 / 3.7 / 10.5배 |
| 최대 연패 | 5번 |
| 최대 낙폭 | 계좌 -72% (한 번 지면 계좌 약 -17%) |

**정직하게 알아야 할 것**
- 이 숫자는 이 기간에 **맞춰서 고른** 결과입니다. 시험 성적이 아닙니다.
- 같은 방법으로 2020~24년만 보고 고른 봇은 2025~26년에 승률 76% 안팎으로 내려가 손실이었습니다.
- 이 봇(평균 이익 +13.1%, 평균 손실 -38.9%)의 손익분기 승률은 약 77%입니다. 승률이 조금만 내려가도 한 달 결과가 크게 달라집니다(아래 표).
- 그래서 처음 며칠은 **승률**을 가장 먼저 봅니다(8장).

**$100으로 시작한 첫 한 달** (이 봇의 거래를 섞어 2만 번 돌린 결과. 승률만 낮춰 본 줄은 "실거래가 백테스트보다 못하면"입니다)

| 실거래 승률 | 한 달 뒤 중간값 | $100 아래로 끝남 | 한 번이라도 $50 아래 | $600 이상 | $1,000 이상 |
|---|---|---|---|---|---|
| 92% (백테스트 그대로) | $647 | 0% | 0% | 55% | 23% |
| 88% | $390 | 3% | 3% | 26% | 7% |
| 85% | $267 | 10% | 7% | 12% | 3% |
| 80% | $142 | 33% | 24% | 2% | 0% |

**안정성 점검** (끄는 조건 461개와 설정 78개를 앞 기간 2020.1~2023.4와 뒤 기간 2023.5~2026.9로 나눠 확인)
- 끄는 조건 461개 중 **두 기간 모두에서 손실을 막아 준 것은 141개**뿐입니다. 나머지 320개는 한쪽 기간에서만 도움이 됐습니다. 우연에 맞춘 조건일 가능성이 큽니다.
- 그 141개만 남기고, 두 기간 모두 이긴 설정 38개(매매법 13개)만 쓴 **안정 버전**(`deploy/combo.live16w-stable.json`)의 백테스트:

| | 지금 버전 (78개 설정) | 안정 버전 (38개 설정) |
|---|---|---|
| 평일 하루 진입 | 2.6번 | 1.7번 |
| 승률 | 92.0% | 85.8% |
| 한 달 배수 중간값 | 6.0배 | 1.9배 |
| 손실 난 달 | 0 / 81 | 14 / 81 |
| 2026년 1~9월 | 6.4 / 4.1 / 30.6 / 6.0 / 8.3 / 7.3 / 26.3 / 3.7 / 10.5 | 1.5 / 2.0 / 5.2 / 1.1 / 4.1 / 1.5 / 2.1 / 0.7 / 1.5 |

- 지금 버전의 6배는 우연일 수 있는 조건 320개에 기대고 있습니다. 실거래에서 기대할 수 있는 수준은 두 버전 사이 어딘가로 보는 것이 정직합니다.

## 1. 두 분이 먼저 할 것 (휴대폰·PC)

**바이비트** ([`bybit-ko.md`](bybit-ko.md) 1장)
- 실행기 전용 **하위 계정**을 만들고 USDT $100만 넣습니다(10/19부터 지갑 금액 상한 확인은 없습니다. USDT 말고 다른 코인은 두지 마세요).
- 하위 계정 API 키: 선물(계약) 거래만, **출금 권한 없음**, 서버 IP로 제한.

**MEXC** ([`mexc-ko.md`](mexc-ko.md) 1~2장)
- KYC 인증을 마칩니다(API 선물 주문은 KYC 계정만 됩니다).
- 선물 지갑에 USDT $100만 둡니다.
- API 키: 선물 거래만, **출금 권한 없음**, 서버 IP로 제한.

키는 **채팅으로 보내지 마세요.** 서버의 `/etc/paperbot/executor.env`에만 넣습니다(3장).

## 2. 서버 코드 받기

```bash
cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh
```

## 3. 키 넣기

```bash
sudo nano /etc/paperbot/executor.env
```

```
BYBIT_LIVE_API_KEY=(바이비트 하위 계정 키)
BYBIT_LIVE_API_SECRET=(바이비트 하위 계정 비밀키)
MEXC_LIVE_KEY=(MEXC 키)
MEXC_LIVE_SECRET=(MEXC 비밀키)
MEXC_LIVE_KEY_CHECKED=FUTURES_ONLY_NO_WITHDRAW_IP_BOUND
PAPERBOT_LIVE_MAINNET=I_UNDERSTAND
```

`MEXC_LIVE_KEY_CHECKED` 줄은 "MEXC 키를 선물 거래만, 출금 없음, IP 제한으로 만들었다"는 두 분의 확인입니다. MEXC는 키 권한을 API로 알려 주지 않아서 이 줄이 대신합니다([`mexc-ko.md`](mexc-ko.md) 3장).

## 4. 합친 봇(페이퍼)을 고른 버전으로 바꾸기

두 분이 고른 버전의 설정 파일을 씁니다. 실행기 설정의 `paper_db`도 같은 줄의 DB로 맞춥니다(5장·6장).

| 버전 | 설정 파일 | 페이퍼 DB (`paper_db`) |
|---|---|---|
| A+C 합본 (바이비트 추천, 10/19 아침) | `deploy/combo.live-ac.json` | `/var/lib/paperbot/combo/live-ac.db` |
| 고원형 합본 = B 안정형 (MEXC 추천) | `deploy/combo.live-plateau37.json` | `/var/lib/paperbot/combo/live-plateau37.db` |
| 고원형 | `deploy/combo.live16w-plateau.json` | `/var/lib/paperbot/combo/live16w-plateau.db` |
| 안정 버전 | `deploy/combo.live16w-stable.json` | `/var/lib/paperbot/combo/live16w-stable.db` |
| 지금 버전 | `deploy/combo.live16w.json` | `/var/lib/paperbot/combo/live16w.db` |

아래는 고원형 합본 예시입니다.

```bash
# 실행기가 돌고 있으면 먼저 멈추고 실제 포지션이 없는지 확인
sudo touch /var/lib/paperbot/STOP
sudo systemctl stop paperbot-combo
sudo cp /opt/crypto-bot-research/deploy/combo.live-plateau37.json /etc/paperbot/combo.json
cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo check-config --config /etc/paperbot/combo.json
```

마지막 줄이 **"준비됨"**이면 켭니다.

```bash
sudo systemctl start paperbot-combo
sudo journalctl -fu paperbot-combo      # "[합친 봇 페이퍼] 시작" 확인 (1분봉 7일치를 받느라 몇 분 걸림)
```

- 페이퍼 DB는 고른 버전의 새 파일입니다(위 표, 고원형 합본이면 `/var/lib/paperbot/combo/live-plateau37.db`). 옛 DB는 지우거나 옮기지 마세요.
- 규칙봇(paperbot-live3)이 돌고 있어야 합니다. 합친 봇은 규칙봇의 1분봉을 읽습니다.

### 4-2. (두 분이 고르면) 두 봇을 서로 다른 유형으로: A 최고형 = 바이비트, B 안정형 = MEXC

**10/19 아침 추천은 A 대신 A+C 합본입니다.** 아래 명령에서 `combo.live16w.json`을 `combo.live-ac.json`으로, 바이비트 `paper_db`의 `live16w.db`를 `live-ac.db`로 바꾸면 됩니다. 텔레그램 이름은 "[합친 봇 페이퍼 A+C 합본]"으로 나옵니다.
- A+C 합본: 평일 하루 3.1번, 승률 91.2%, 월 x7.66(바이비트 수수료), 손실 난 달 0/81, 최대 연패 3번입니다.
- 실거래 코드 재생 확인(9/14~9/25 평일 10일): 계좌까지 온 신호 48개가 백테스트와 같았고, 거래 27건이 시각·코인·방향·결과까지 모두 같았습니다(매매법 18개).
  - 차이 3건은 모두 설명됩니다. 2건은 재생을 시작한 그 순간의 신호입니다(실거래 봇은 켜진 순간보다 앞선 신호를 거래하지 않습니다). 1건은 같은 분에 더 높은 점수 신호가 있어 건너뛴 신호로, 백테스트에서도 손절 규칙 때문에 빠지는 자리였습니다.
- 신호등을 쓰면 두 실행기 설정에 "신호등" 장의 두 줄을 넣습니다. 바이비트는 0.85(또는 0.9), MEXC는 0.8을 권합니다.

바이비트와 MEXC가 **다른 페이퍼 봇**을 따라가게 하는 방법입니다. 페이퍼 봇 두 개를 켭니다(`paperbot-combo`, `paperbot-combo2`).
- A 최고형은 거래가 많아서 수수료가 싼 바이비트에 둡니다.
- 두 봇은 A가 하는 거래 중 약 40%만 같이 합니다(같은 코인·방향·1시간 안).

```bash
sudo touch /var/lib/paperbot/STOP
sudo systemctl stop paperbot-combo paperbot-combo2
sudo cp /opt/crypto-bot-research/deploy/combo.live16w.json /etc/paperbot/combo.json          # A 최고형 -> 바이비트
sudo cp /opt/crypto-bot-research/deploy/combo.live-plateau37.json /etc/paperbot/combo2.json  # B 안정형 -> MEXC
cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo check-config --config /etc/paperbot/combo.json
cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo check-config --config /etc/paperbot/combo2.json
```

둘 다 마지막 줄이 **"준비됨"**이면 켭니다.

```bash
sudo systemctl start paperbot-combo paperbot-combo2
sudo journalctl -fu paperbot-combo -u paperbot-combo2   # "[합친 봇 페이퍼 A 최고형] 시작", "[합친 봇 페이퍼 B 안정형] 시작"
```

실행기 설정의 `paper_db`만 봇마다 다르게 씁니다(5장·6장의 나머지는 그대로).

| 실행기 | 설정 파일 | `paper_db` |
|---|---|---|
| 바이비트 | `/etc/paperbot/executor.json` | `/var/lib/paperbot/combo/live16w.db` (A 최고형) |
| MEXC | `/etc/paperbot/executor-mexc.json` | `/var/lib/paperbot/combo/live-plateau37.db` (B 안정형) |

- 매일 볼 것(8장)의 첫 줄은 두 번 봅니다: `--db /var/lib/paperbot/combo/live16w.db`, `--db /var/lib/paperbot/combo/live-plateau37.db`.
- 실거래 승률 기준은 봇마다 다릅니다. A는 백테스트 92%, B는 88.5%입니다. 20번 넘게 거래한 뒤 A가 85%, B가 82% 아래면 알려 주세요.
- 며칠 문제없으면 부팅 때 자동으로 켜지게 합니다: `sudo systemctl enable paperbot-combo paperbot-combo2`.
- `/var/lib/paperbot/STOP` 하나로 두 실행기가 모두 멈춥니다.

## 5. 바이비트 실행기 설정

```bash
sudo nano /etc/paperbot/executor.json
```

```json
{
  "exchange": "bybit",
  "mode": "mainnet",
  "account": "COMBO@mix",
  "paper_db": "/var/lib/paperbot/combo/live-plateau37.db",
  "db": "/var/lib/paperbot/exec/executor-bybit-live.db",
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

확인 (둘 다 통과해야 합니다):

```bash
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor.json
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh executor preflight --config /etc/paperbot/executor.json
```

preflight에서 다음이 모두 `[OK]`여야 합니다: 주소 api.bybit.com, 키 권한(출금 꺼짐·IP 제한·하위 계정), 지갑은 USDT만.

## 6. MEXC: 연습 먼저, 그다음 실행기 설정

MEXC에는 테스트넷이 없습니다. 그래서 연습을 **진짜 계정**에서, 가장 작은 수량으로 합니다.

```bash
# 6-1. 읽기 점검 + 설정(격리·단방향·배수), 주문 없음
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh mexc drill
# 6-2. 진짜 주문 한 번 (가장 작은 수량: 진입 -> 손절 걸기 -> 손절 옮기기 -> 청산 -> 남은 주문 없음 확인)
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh mexc drill --confirm-order REAL_ORDER
```

모든 줄이 OK여야 합니다. 하나라도 실패하면 거기서 멈추고 그 화면을 보내 주세요. 연습 비용은 수수료 몇 센트입니다.

6-2의 마지막 줄에 `fee_rate_pct`가 나옵니다. 실제로 낸 수수료율(%)입니다. 0.08 근처면 MEXC 공지대로이고, 위 "거래소 수수료" 표의 MEXC 줄이 맞는 숫자입니다.

```bash
sudo nano /etc/paperbot/executor-mexc.json
```

5장의 바이비트 설정과 같고, 아래 세 줄만 다릅니다.

```json
  "exchange": "mexc",
  "mode": "mainnet",
  "db": "/var/lib/paperbot/exec/executor-mexc-live.db",
```

확인:

```bash
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor-mexc.json
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh executor preflight --config /etc/paperbot/executor-mexc.json
```

## 7. 켜기

```bash
sudo rm -f /var/lib/paperbot/STOP
sudo systemctl start paperbot-executor          # 바이비트
sudo systemctl start paperbot-executor-mexc     # MEXC
sudo journalctl -fu paperbot-executor -u paperbot-executor-mexc
```

- 월요일 한국 시간 00:00부터 평일이라 바로 진입할 수 있습니다. 신호가 없으면 몇 시간 동안 진입이 없을 수 있습니다(평일 하루 평균 2.6번).
- **첫 거래는 두 분이 앱으로 같이 봅니다**: 진입, 손절 주문이 걸림, +11%에서 잠금이 옮겨짐, 청산, 손익이 앱과 같음.
- 며칠 문제없으면 부팅 때 자동으로 켜지게 합니다: `sudo systemctl enable paperbot-executor paperbot-executor-mexc`

## 8. 매일 볼 것

```bash
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo status --db /var/lib/paperbot/combo/live-plateau37.db
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-bybit-live.db
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-mexc-live.db
```

| 볼 것 | 기준 |
|---|---|
| 실거래 승률 | 백테스트 92%. 20번 넘게 거래한 뒤 85% 아래면 알려 주세요(손익분기 약 77%) |
| 페이퍼와 실거래 차이 | 같은 신호인데 한쪽만 들어갔거나, 손익이 크게 다르면 알려 주세요 |
| 동전 계좌(`COMBOFLIP@mix`) | 같은 시점에 방향만 무작위. 우리 봇이 이 계좌보다 못하면 실력이 아니라 운입니다 |
| 텔레그램 알림 | "연구 조건을 못 읽어 진입 안 함", "거래소 기록과 다릅니다"가 오면 알려 주세요 |

## 9. 멈춤 장치 (자동)

| 멈춤 | 값 | 백테스트에서 걸린 횟수 (81개월) |
|---|---|---|
| 연속 손실 | 3번 | 6번 (3연패 이상) |
| 낙폭 | 계좌 고점 대비 50% | 7번 |

- 백테스트에서도 평균 1년에 한 번쯤 멈춥니다. 멈추면 텔레그램이 오고, 실행기는 새 진입을 하지 않습니다.
- 다시 켤지는 두 분이 정합니다: STOP 파일 지우기 → 실행기 끄기 → `clear-halt` ([`live-safety.md`](live-safety.md)).

| 하고 싶은 것 | 명령 |
|---|---|
| 두 봇 모두 닫고 멈추기 | `sudo touch /var/lib/paperbot/STOP` |
| 바이비트만 잠깐 끄기 | `sudo systemctl stop paperbot-executor` (포지션은 거래소 손절이 지킴) |
| MEXC만 잠깐 끄기 | `sudo systemctl stop paperbot-executor-mexc` |

## 10. 매매법별 점검표 (2020-01~2026-09, 실거래 규칙, 맞춘 기간)

| 매매법 | 역할 | 거래 | 평일 하루 | 승률 | 평균 이익/손실 ROE | 역할 밖 진입 (승률) | 손절 직전까지 밀린 승리 | 15분 안 손절 | 노이즈 손절 | 가장 나쁜 달 | 손실 연도 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| N03_ADX_GC | 추세추종 | 911 | 0.52 | 95.2% | +12.5 / -41.9 | 325 (96%) | 14% | 9% | 27% | x0.65 | 없음 |
| N08_ICHI_WR | 횡보·되돌림 | 581 | 0.33 | 89.7% | +13.1 / -30.8 | 207 (92%) | 18% | 7% | 33% | x0.82 | 없음 |
| N19_FIB_CHOP | 횡보·되돌림 | 404 | 0.23 | 93.6% | +13.2 / -55.2 | 154 (93%) | 8% | 4% | 38% | x0.73 | 없음 |
| S4_BB_BBP | 돌파 | 270 | 0.15 | 90.7% | +15.4 / -28.2 | 103 (90%) | 27% | 24% | 44% | x0.83 | 없음 |
| F10_M2022 | 반전 | 453 | 0.26 | 88.1% | +12.7 / -35.5 | 119 (90%) | 21% | 20% | 39% | x0.74 | 없음 |
| F5_BOX | 횡보·되돌림 | 282 | 0.16 | 93.3% | +12.4 / -51.5 | 104 (95%) | 7% | 5% | 16% | x0.75 | 없음 |
| F12_MSS_DISP | 반전 | 178 | 0.10 | 91.6% | +15.3 / -29.9 | 36 (97%) | 20% | 53% | 60% | x0.79 | 없음 |
| F9_IFVG | 반전 | 247 | 0.14 | 90.7% | +12.8 / -35.6 | 46 (93%) | 19% | 9% | 39% | x0.63 | 없음 |
| F5_BOX_RSI | 추세추종 | 167 | 0.09 | 96.4% | +13.4 / -32.1 | 56 (96%) | 45% | 50% | 67% | x0.83 | 없음 |
| N02_ST_KST | 추세추종 | 200 | 0.11 | 92.5% | +13.1 / -39.8 | 26 (96%) | 10% | 7% | 27% | x0.79 | 없음 |
| S6_EMA_DMI_ADX | 횡보·되돌림 | 223 | 0.13 | 92.8% | +13.0 / -50.5 | 107 (93%) | 3% | 25% | 38% | x0.58 | 없음 |
| S1_EMA_RSI_CHOP | 횡보·되돌림 | 136 | 0.08 | 94.9% | +14.6 / -18.3 | 52 (92%) | 63% | 57% | 71% | x0.71 | 없음 |
| F15_ASIA_BRK | 돌파 | 390 | 0.22 | 86.2% | +12.3 / -45.8 | 67 (87%) | 5% | 9% | 35% | x0.60 | 없음 |
| N06_MACD_ORB | 돌파 | 96 | 0.05 | 99.0% | +13.5 / -40.2 | 27 (96%) | 13% | 0% | 0% | x0.84 | 없음 |
| F4_PULL | 추세추종 | 54 | 0.03 | 94.4% | +12.3 / -29.9 | 36 (94%) | 10% | 33% | 0% | x0.91 | 없음 |

- **실제로 진입하는 매매법은 15개입니다.** 16번째 F13_FVG_PD는 설정이 "주말에만"이라, 주말을 쉬는 실거래 규칙에서는 들어가지 않습니다.
- **역할 밖 진입**: 역할(BTC 4시간 장세 기준) 밖에서 들어간 거래 수와 그 승률입니다. 역할 안 거래와 승률이 비슷하거나 높습니다. 손실 나던 역할 밖 구간은 이미 꺼져 있습니다.
- **손절 직전까지 밀린 승리**: 이긴 거래 중 손절 거리의 80% 이상 밀렸다가 이긴 비율입니다. 높으면 진입이 이르다는 뜻입니다(S1_EMA_RSI_CHOP 63%, F5_BOX_RSI 45%).
- **노이즈 손절**: 손절된 뒤 4시간 안에 원래 방향으로 +11% ROE까지 간 비율입니다. 높으면 손절이 좁거나 진입이 이릅니다(S1 71%, F5_BOX_RSI 67%, F12_MSS_DISP 60%).
- **늦은 진입 점검**: S1_EMA_RSI_CHOP, F5_BOX_RSI, F12_MSS_DISP는 진 거래가 이긴 거래보다 진입 전에 더 많이 움직인 뒤였습니다. "이미 많이 움직였으면 진입 안 함" 조건을 넣어 다시 돌렸지만, 앞·뒤 두 기간 모두에서 좋아지는 경우가 없어 넣지 않았습니다(넣어도 전체 성적 변화가 거의 없음: 4,592 → 4,586거래, 승률 92.0% 그대로).
- **커스텀값**: 같은 매매법의 다른 커스텀값은 대부분 손실입니다. 92%는 지금 정확한 값과 끄기 조건이 함께 만든 숫자입니다. 실거래가 백테스트와 달라질 수 있는 가장 큰 이유입니다.

## 11. 그림자 페이퍼 봇 (선택, 10/19 추가)

지금 페이퍼 봇(A+C 합본) 옆에서 다른 설정의 페이퍼 봇 3개를 같은 실제 시장으로 돌립니다. 한 달 뒤 어느 버전이 처음 보는 데이터에서 나았는지 같은 조건으로 비교하려는 것입니다.

| 그림자 | 설정 파일 | 무엇이고 왜 돌리나 |
|---|---|---|
| `@b` 그림자 B 안정형 | `deploy/combo.shadow-b.json` | 고원형 합본(세팅 37개). 백테스트는 낮지만(88.5%) 처음 보는 기간 시험에서 가장 덜 잃었습니다. 실제 시장에서도 그런지 봅니다. |
| `@nocut` 그림자 끄는 구간 없음 | `deploy/combo.shadow-nocut.json` | 지금 봇과 같은 세팅 95개에서 끄는 구간만 뺐습니다. 백테스트 91%의 대부분은 끄는 구간이 만듭니다(빼면 약 79%). 처음 보는 데이터에서도 끄는 구간이 도움이 되는지 잽니다. |
| `@ac32` 그림자 32개 | `deploy/combo.shadow-ac32.json` | 오늘 27개로 줄이기 전 버전(매매법 32개·세팅 101개). 줄인 것이 나았는지 봅니다. |

- **돈이 걸리지 않습니다.** 주문을 내지 않고, 실행기는 그림자를 따라가지 않습니다. 텔레그램도 보내지 않습니다.
- DB는 각자 따로입니다: `/var/lib/paperbot/combo/shadow-b.db`, `shadow-nocut.db`, `shadow-ac32.db`. 실행기 설정의 `"paper_db"`는 그대로 `live-ac.db`입니다. 그림자 DB를 넣지 않습니다.
- 지금 페이퍼 봇과 실행기보다 낮은 순위로 돕니다(CPU·디스크를 덜 받고, 메모리 한도 768M).

**켜기·끄기**

```bash
sudo systemctl start paperbot-combo-shadow@b paperbot-combo-shadow@nocut paperbot-combo-shadow@ac32
sudo systemctl stop paperbot-combo-shadow@b paperbot-combo-shadow@nocut paperbot-combo-shadow@ac32
```

- 켜는 데 8분쯤 걸립니다. 바이낸스 요청 한도를 넘지 않게 2분 간격으로 하나씩 켜집니다. 명령이 끝날 때까지 기다립니다.
- 서버를 다시 켜면 그림자는 저절로 켜지지 않습니다. 같은 start 명령을 다시 칩니다.
- 코드를 새로 받으면(install.sh) 화면에 나온 `restart` 명령으로 그림자도 다시 켭니다. 그래야 모든 봇이 같은 코드로 돕니다.

**켠 뒤 메모리 확인** (켜고 10분쯤 뒤, 다음 날 한 번 더)

```bash
free -m
systemctl status paperbot-combo-shadow@b paperbot-combo-shadow@nocut paperbot-combo-shadow@ac32 --no-pager
```

- `free -m`의 `available`이 1000 이상이면 됩니다. 시험에서 그림자 하나가 약 270MB를 썼습니다(셋이면 약 0.8GB, 서버는 8GB).
- `systemctl status`에서 셋 다 `active (running)`이고 `Memory:`가 300M 안팎이면 됩니다(한도 768M).
- `available`이 1000 아래로 내려가면 그림자부터 끕니다(위 stop 명령). 지금 페이퍼 봇과 실행기가 먼저입니다.

**보기**

```bash
cd /opt/crypto-bot-research
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo status --db /var/lib/paperbot/combo/shadow-b.db
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo status --db /var/lib/paperbot/combo/shadow-nocut.db
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo status --db /var/lib/paperbot/combo/shadow-ac32.db
```

비교 기준은 지금 페이퍼 봇입니다(`live-ac.db`, 맨 위 6)의 첫 줄).

**읽는 법**

- 거래가 40번쯤 쌓이거나 한 달이 지난 뒤에만 비교합니다. 그 전의 차이는 대부분 운입니다.
- 넷 모두 같은 방식으로 봅니다: 같은 기간, 같은 숫자(거래 수, 승률 = 승 ÷ 거래, 지갑). 그래서 그림자는 되도록 오늘 켭니다. 며칠 늦게 켰다면 켠 날짜를 적어 두고 알려 주세요. 지금 페이퍼 봇도 그날부터의 거래만 세어야 같은 비교입니다.
- 며칠 결과를 보고 실행기가 따라가는 페이퍼 봇을 바꾸지 않습니다.
- 끄는 구간 없음이 지금 봇만큼 하면 끄는 구간은 처음 보는 데이터에서 도움이 안 된 것입니다. 지금 봇이 분명히 앞서면 도움이 된 것입니다.
