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
sudo install -o root -g paperbot -m 640 /opt/crypto-bot-research/deploy/combo.live-ac.json /etc/paperbot/combo.json
cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo check-config --config /etc/paperbot/combo.json
```

마지막 줄이 **"준비됨"**이면 켭니다.

- `Permission denied: '/etc/paperbot/combo.json'`이 나오면 `cp`로 복사해서 봇이 못 읽는 것입니다(10/19 서버에서 실제로 나옴). `sudo chown root:paperbot /etc/paperbot/combo.json && sudo chmod 640 /etc/paperbot/combo.json` 뒤 check-config를 다시 합니다. 실행기 설정 두 파일도 같습니다.

```bash
sudo systemctl start paperbot-combo
sudo journalctl -fu paperbot-combo      # "[합친 봇 페이퍼 A+C 합본] 시작" 확인 (1분봉 7일치를 받느라 몇 분 걸림)
```

**3) 바이비트 실행기**

아래 내용이 담긴 파일이 저장소에 있습니다. 직접 치지 말고 복사합니다(10/19 추가).

```bash
sudo install -o root -g paperbot -m 640 /opt/crypto-bot-research/deploy/executor.live-bybit.json /etc/paperbot/executor.json
```

내용(손으로 고칠 때만 `sudo nano /etc/paperbot/executor.json`):

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
- MEXC 실행기 설정도 복사합니다: `sudo install -o root -g paperbot -m 640 /opt/crypto-bot-research/deploy/executor.live-mexc.json /etc/paperbot/executor-mexc.json`
- 이 파일은 3)의 내용과 같고 아래 세 줄만 다릅니다.

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
- 실거래 메시지(진입·청산·알람·아침 점검)는 **실거래 전용 봇**(@BotFather에서 새로 만든 봇)이 두 분 **개인 채팅**으로 보냅니다. 12장의 "실거래 텔레그램을 개인 채팅으로"를 한 번 따라 하면 규칙봇 단체방에는 규칙봇 메시지만 남습니다.

**7) 두 분 운영 수칙** (참고 자료 『기술적 분석은 처음이지?』 9장의 "매매를 망치는 습관"을 우리 봇에 맞춘 것)

봇은 감정 없이 규칙대로만 움직입니다. 봇을 망치는 건 대개 사람이 끼어드는 순간입니다.

| 하지 말 것 | 이유 |
|---|---|
| 손절 몇 번 뒤 금액을 늘려 만회하기 (리벤지) | 손실 뒤에 크기를 키우면 다음 손절 한 번이 더 커집니다. 금액은 40번 판단 기준(88% 이상)으로만 늘립니다 |
| 실행기 계정에서 손으로 따라 들어가기 (추격) | 실행기는 모르는 포지션을 보면 바로 닫습니다. 같은 계정에서는 손으로 진입하지 않습니다 |
| 며칠 성적을 보고 설정 바꾸기 (잦은 스위칭) | 거래 몇 번은 운입니다. 바꾸는 건 40번 또는 한 달에, 그림자 봇과 같은 기준으로 비교한 뒤에만 합니다 |
| 손절을 손으로 넓히거나 지우기 (손절 타협) | 거래소 손절이 봇의 생명줄입니다. 봇은 손절을 수익 쪽으로만 옮깁니다 |
| 손실 중인 포지션을 본전에서 손으로 닫기 (본전 심리) | 봇의 성적이 백테스트와 달라져서 판단 기준이 흐려집니다. 정말 위험하다고 느끼면 손으로 닫지 말고 STOP 파일로 전부 멈춥니다 |
| 멈춤 알림 직후 바로 풀기 | 3연패나 낙폭 50% 멈춤은 이유가 있어서 걸린 것입니다. 두 분이 같이 원인을 본 뒤에 풉니다 |

- 넣는 돈은 잃어도 생활에 지장이 없는 금액만 넣습니다(지금 거래소당 $100).
- 돈이 늘면 원금은 빼고 수익으로만 굴리는 규칙을 미리 정해 두면 좋습니다. 예: "$200이 되면 $100 출금". 출금은 포지션이 없을 때 합니다.

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
TELEGRAM_BOT_TOKEN=(실거래 전용 봇 토큰)
TELEGRAM_CHAT_CRITICAL=(개인 채팅 번호)
```

텔레그램 두 줄은 규칙봇(`live.env`)의 것을 옮기지 않습니다. @BotFather에서 새로 만든 **실거래 전용 봇**의 토큰과 개인 채팅 번호를 넣습니다(번호 찾기는 12장). 실행기 알람이 오늘부터 그 봇으로 옵니다. 12장의 `live-telegram.env`를 만든 뒤에는 같은 값이 두 곳에 있게 되고, 실행기는 나중에 읽는 `live-telegram.env`의 값을 씁니다. 두 곳을 같은 값으로 두면 됩니다.

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
sudo install -o root -g paperbot -m 640 /opt/crypto-bot-research/deploy/combo.live-plateau37.json /etc/paperbot/combo.json
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
sudo install -o root -g paperbot -m 640 /opt/crypto-bot-research/deploy/combo.live16w.json /etc/paperbot/combo.json          # A 최고형 -> 바이비트
sudo install -o root -g paperbot -m 640 /opt/crypto-bot-research/deploy/combo.live-plateau37.json /etc/paperbot/combo2.json  # B 안정형 -> MEXC
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

## 12. 실거래 일일 점검과 알람 (10/19 추가)

서버가 매일 아침 실거래를 대신 점검하고, 1분마다 지켜보며 거래와 문제를 텔레그램으로 알려 줍니다. 봇과 주문에는 손대지 않고 기록만 읽습니다.

**실거래 텔레그램을 개인 채팅으로 (한 번만)**

실거래 쪽 메시지(페이퍼 봇 `paperbot-combo`, 두 실행기, 아침 점검과 1분 감시)는 **실거래 전용 봇**이 두 분 각자의 개인 채팅으로 보냅니다. 규칙봇 단체방에는 규칙봇 메시지만 남습니다. 토큰과 채팅 번호는 `/etc/paperbot/live-telegram.env` 한 파일에 둡니다. 실거래 쪽 서비스가 모두 `live.env`(실행기는 `executor.env`) 다음에 이 파일을 읽어 덮어씁니다.

1. 텔레그램에서 **@BotFather** → `/newbot` → 이름 → 아이디(끝이 `bot`)를 정하면 토큰이 나옵니다. 토큰은 채팅으로 보내지 말고 서버에만 넣습니다.
2. 두 분이 각자 새 봇을 열고 **시작(Start)** 을 누른 뒤 "hi"를 한 번 보냅니다. 봇은 시작을 누른 사람에게만 보낼 수 있습니다.
3. 파일을 토큰 한 줄로 만듭니다.
   ```bash
   sudo nano /etc/paperbot/live-telegram.env
   ```
   ```
   TELEGRAM_BOT_TOKEN=(1에서 받은 토큰)
   ```
   - 권한: `sudo chown root:paperbot /etc/paperbot/live-telegram.env && sudo chmod 640 /etc/paperbot/live-telegram.env` (설치 스크립트도 파일이 있으면 맞춰 줍니다. 내용은 건드리지 않습니다).
   - 이 상태로 두지 말고 바로 4~5를 합니다. 새 봇은 규칙봇 방에 없어서 채팅 줄 없이 토큰만 있으면 실거래 메시지가 가지 않습니다. 10분이 넘으면 1분 감시가 규칙봇 방에 🚨 "텔레그램 설정"을 한 번 보냅니다.
4. 개인 채팅 번호를 봅니다. 지금 쓰이는 토큰(`live.env` 다음 `live-telegram.env`)으로 묻습니다. 토큰은 화면에 나오지 않고, 아무것도 보내지 않습니다.
   ```bash
   cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.livecheck chat-ids
   ```
   - 첫 줄이 `봇: @(새 봇 아이디) · 토큰: live-telegram.env(실거래 전용 봇)`인지 봅니다. "아직 규칙봇 토큰입니다"가 나오면 3을 다시 봅니다.
   - 결과 예: `111111111 · 민수 · @minsu · 10/19 21:05`. 두 분 번호만 고릅니다.
5. 같은 파일에 나머지 줄을 넣어 모두 여섯 줄로 만듭니다.
   ```
   TELEGRAM_BOT_TOKEN=(1에서 받은 토큰)
   TELEGRAM_CHAT_CRITICAL=111111111,222222222
   TELEGRAM_CHAT_WARN=111111111,222222222
   TELEGRAM_CHAT_INFO=111111111,222222222
   TELEGRAM_SOUND=critical
   PAPERBOT_COMBO_TRADE_MSGS=0
   ```
   - 토큰 줄과 채팅 줄 3개는 함께 있어야 합니다. 세 줄 모두 같은 두 번호(쉼표로 구분)를 넣습니다. **빈 줄(`TELEGRAM_CHAT_CRITICAL=`)로 두면 안 됩니다**: 실거래 메시지가 아무 데도 가지 않습니다.
   - `TELEGRAM_SOUND=critical`: 🚨 알람만 소리가 나고 나머지는 무음입니다. `PAPERBOT_COMBO_TRADE_MSGS=0`: 페이퍼 봇의 날것 진입·청산 줄 대신 1분 감시의 🟢·✅·❌ 메시지가 갑니다.
6. 다시 켭니다.
   - 페이퍼 봇은 바로: `sudo systemctl restart paperbot-combo`
   - 실행기는 **포지션이 없을 때만**(`executor status`에서 포지션 `null`) 또는 처음 켜기 전에: `sudo systemctl restart paperbot-executor paperbot-executor-mexc`
   - 아침 점검과 1분 감시는 다음 실행부터 저절로 따릅니다.
7. 확인: 다음 진입부터 두 분 개인 채팅에 새 봇의 🟢 진입이 오고, 규칙봇 단체방에는 규칙봇 메시지만 남습니다. `cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.livecheck show`의 마지막 줄이 `텔레그램 설정: live-telegram.env(실거래 전용 봇) → 채팅 2곳 · 🚨만 소리 · 페이퍼 봇 날것 진입·청산 줄 끔`이면 맞습니다. 전체 모양은 `... -m paperbot.livecheck preview`로 미리 볼 수 있습니다.
- `executor.env`에도 같은 새 봇 토큰과 개인 채팅 번호가 있습니다(3장, 실행기 알람이 오늘부터 오도록 넣은 것). 이 업데이트 뒤에는 두 곳에 같이 있고, 나중에 읽는 `live-telegram.env`가 이깁니다. 두 곳을 같은 값으로 두면 됩니다.

**실거래 메시지 (1분마다 확인, 한 거래에 한 번씩)**

- ⏳ **진입 대기** (무음): 돌파형 설정(95개 중 33개)이 신호를 냈고, 다음 한 봉(15분·30분·1시간) 안에 신호 봉의 고점(롱)·저점(숏)을 넘으면 들어가는 상태. 코인·방향·매매법, "101 위로 올라가면 진입 (지금 100 · 1.00% 남음)", 몇 시까지인지. **진입 확정이 아닙니다**: 시간 안에 못 넘으면 진입이 없고, 들어가면 🟢 진입이 따로 옵니다. 한 대기에 한 번만, 포지션이 이미 있거나 주말·지표 시간이면 보내지 않습니다. **결과가 나오면 같은 메시지 끝에 한 줄이 붙습니다**(새 메시지 아님, 소리 없음): "→ ✅ 돌파! 19:07에 진입했어요 (🟢 진입 알림 참고)", "→ 돌파했지만 진입 안 함: 이미 포지션 있음", "→ ⌛ 시간 지남 · 진입 없음", "→ 진입 안 함: 신호봉 크기가 연구 조건 밖". 메시지를 지웠거나 48시간이 지났으면 그대로 둡니다. 끄려면 `live-telegram.env`에 `PAPERBOT_LIVE_WAIT_MSGS=0`(결과 줄도 같이 꺼짐).
- ⏸ **진입 쉼 시작** · 🔔 **진입 쉼 끝** (무음): 페이퍼 봇이 새로 진입하지 않는 시간(주말 토 00:00~월 00:00, 미국 경제 발표 앞뒤 30분)이 시작할 때와 끝날 때 한 번씩. 예: "⏸ 진입 쉼 시작 · CPI 발표 21:30 앞뒤 30분 / 22:00까지 새 진입 없음", "⏸ 주말 진입 쉼 시작 · 월 00:00까지", "🔔 진입 쉼 끝 · 다시 진입할 수 있어요"(24시간 안에 다음 쉼이 있으면 그 시간도). 포지션이 열려 있으면 "열린 포지션은 손절·잠금 그대로 관리돼요"가 붙습니다. 겹치거나 이어지는 쉼(금요일 밤 발표 → 주말)은 하나로 보냅니다. 감시가 꺼져 있다 10분 넘게 늦게 알게 된 것은 보내지 않습니다. 끄려면 `live-telegram.env`에 `PAPERBOT_LIVE_PAUSE_MSGS=0`.
- 🟢 **진입**: 페이퍼 진입과 거래소마다의 결과(✅ 들어감·증거금·손절 / ⛔ 신호등이 막음 / ⏸ 멈춤 중 / ⚠ 따라가지 않음). 실행기가 답할 때까지(들어감·이유 기록) 최대 3분 기다렸다 한 번 보냅니다.
- **각 실행기는 포지션을 한 번에 하나만 듭니다.** 바이비트와 MEXC는 서로 다른 계정이라 각자 최대 하나씩, 따로 움직입니다. 그래서 진입 메시지에 거래소가 한 줄씩 나옵니다(`포지션 1/1`).
- 🔒 **잠금 시작**: 처음 잠금(+10% 확보)만, 거래소 손절이 어디로 옮겨졌는지. 그 뒤 +3%씩 올리는 것은 보내지 않고, 청산 메시지에 마지막 잠금이 나옵니다.
- ✅ **청산(이김)**: 순ROE, 보유 시간, 잠금, 거래소마다 손익·잔고, 오늘 승패·최근 20번·신호등.
- ❌ **청산(짐) = 손실 카드**(아래). 🚦 신호등 색이 바뀔 때, 🏁 페이퍼 40번째 거래(미리 정한 판단 기준, 82% 미만이면 소리), ▶️·⏹ 실행기를 켜거나 사람이 껐을 때.
- 소리: 🚨로 시작하는 메시지만 소리가 납니다(`TELEGRAM_SOUND=critical`). 나머지는 모두 무음입니다.

**아침 메시지 (매일 09:10, 한 통)**

- 점검하는 하루: **어제 09:00 ~ 오늘 09:00** (한국 시간). 페이퍼 봇의 하루 기록도 같은 경계입니다.
- 문제가 없으면 **소리 없이**("📋 실거래 일일 점검 · 이상 없음"), 아래 중 하나라도 있으면 **소리 나게**("🚨 … 확인할 것 N개") 옵니다.
  - 대조에서 이유를 모르는 차이가 있음
  - 실제 비용이 기준을 넘음(한쪽 평균 5bps보다 나쁜 체결, 가정보다 높은 수수료, 페이퍼 거래와 짝이 없는 실거래)
  - 실행기가 멈춤
- 메시지 내용
  1. **대조**: 페이퍼 봇을 그 하루 동안 처음부터 다시 돌려(같은 1분봉, 09:00 상태부터) 실제 기록과 비교합니다. 거래(진입 시각·코인·방향·청산 이유·순ROE)와 신호(상태)가 몇 개 같은지, 다르면 무엇이 어떻게 다른지 한 줄씩. 페이퍼 봇이 꺼져 있었다거나 다시 시작했다는 등 기록으로 이유를 알 수 있으면 그 이유를 붙이고, 그런 차이는 소리를 내지 않습니다. 바이낸스에 연결이 안 되면 "대조: 못 함"이라고 적습니다.
  2. **실제 비용**: 어제 닫힌 실거래를 각자의 페이퍼 거래와 짝지어, 진입·청산 가격 차이(bps, +가 불리), 낸 수수료율(가정: 바이비트 0.055%, MEXC 0.08%), 펀딩.
  3. **성적표**: 페이퍼(시작부터 거래·승·승률·최근 20번·최근 40번·손익), 바이비트·MEXC(거래·승률·실현 손익·잔고·멈춤 여부·신호등 색과 신호등이 거른 진입 수), 동전 쌍둥이(참고), 그림자 봇이 있으면 한 줄씩(참고), 그리고 **판단: 거래 40번에서 88% 이상이면 늘리기 검토 / 82~88% 계속 지켜보기 / 82% 미만 멈추고 다시 생각** (남은 거래 수). 20번 미만은 "표본이 작음"이라고 적습니다.
  4. **월요일**에는 지난 7일 요약이 붙습니다.
  5. **오늘 진입 쉬는 시간**: 앞으로 24시간 안의 미국 경제 발표 앞뒤 30분(`data/macro_events.csv`). 금요일에는 "주말(토·일 KST)은 진입하지 않습니다"가 붙습니다.
- 결과는 `/var/lib/paperbot/livecheck.db`에도 남습니다(나중에 대시보드용).

**알람 (1분마다 확인, 소리 나게, 같은 문제는 한 번만, 끝에 "지금 할 일:")**

| 알람 | 언제 | 할 일 |
|---|---|---|
| 실거래가 페이퍼를 따라가지 않았습니다 | 페이퍼가 들어간 지 3분이 지났는데 실행기에 그 거래가 없음. 신호등이 초록(또는 근거 쌓는 중)이고, 멈춤도 비상 정지 파일도 없고, 실행기가 켜져 있어야 할 때만 | 거래소 앱에서 포지션 확인, 메시지의 `journalctl` 명령으로 이유 보기 |
| 실거래 포지션에 손절 기록이 없습니다 | 실행기가 연 포지션에 손절 주문 번호가 1분 넘게 없음(거래소에 묻지 않고 실행기 기록만 봄) | 앱에서 손절이 걸려 있는지 바로 보고, 없으면 앱에서 손절을 걸거나 닫기 |
| 실행기가 10분 넘게 기록을 남기지 않습니다 | 켜져 있어야 할 실행기의 기록이 10분 넘게 멈춤 | `systemctl status`·`journalctl`로 확인 |
| 페이퍼 봇이 10분 넘게 아무것도 쓰지 않습니다 / 규칙봇 1분봉이 5분 넘게 들어오지 않습니다 | 페이퍼 봇이나 그 1분봉이 멈춤(그동안 실거래도 새 진입 없음). 업데이트(install.sh)로 규칙봇이 다시 켜진 뒤 10분은 1분봉이 따라잡는 시간이라 참습니다(1분봉이 15분 넘게 없으면 그래도 울림) | 메시지의 `systemctl status` 명령으로 확인 |
| 실거래 잔고가 최고점보다 25% 줄었습니다 | 50% 자동 멈춤 전에 미리 | 두 분이 계속할지 정하기 |
| 디스크 부족 / 메모리 부족 | 서버의 남은 디스크가 2GB 아래, 남은 메모리가 500MB 아래 | 메시지의 "먼저 끌 것(실험)" 명령으로 실험 서비스부터 끄기. paperbot-live3·paperbot-combo·실행기는 끄지 않기 |
| 텔레그램 설정 · 실거래 전용 봇의 채팅 줄이 없습니다 / 채팅 줄이 비어 있습니다 | `live-telegram.env`에 새 봇 토큰만 있고 채팅 줄이 없거나(채팅이 `live.env`의 규칙봇 방 그대로), `TELEGRAM_CHAT_CRITICAL=`이 빈 채로 10분이 지남. 실거래 메시지가 못 가므로 이것만 **규칙봇 방으로**(live.env의 봇) 한 번 옵니다 | 위 "실거래 텔레그램을 개인 채팅으로" 4~6. 고치면 새 봇이 개인 채팅으로 "✅ 텔레그램 설정이 맞춰졌습니다"를 보냅니다 |

- 문제가 풀리면 소리 없이 "✅ …다시 들어옵니다"가 오고, 같은 문제가 다시 생기면 다시 울립니다(잔고 알람은 20% 안으로 돌아온 뒤에).
- 좋은 소식은 소리 없이 한 번만: 실거래 잔고가 처음으로 시작보다 +50%, +100%가 됐을 때.
- 실행기를 일부러 끈 경우(`systemctl stop`이고 자동 시작도 꺼져 있음)에는 그 실행기 알람을 보내지 않습니다.
- 아침 점검은 이 감시 기록으로 "그때 페이퍼 봇이 멈춰 있었음"을 대조 차이의 이유로 붙입니다.

**손실 카드 (페이퍼가 질 때마다 한 장)**

- 페이퍼(`COMBO@mix`) 거래가 손실로 끝나면 몇 분 뒤 카드가 옵니다. 보통은 소리 없이, 아래 셋 중 하나면 소리 나게: 그 매매법의 백테스트 최악 손실보다 큼 / 실거래-페이퍼 차이 / 연속 손실 2번째 이상.
- 카드에 있는 것: 매매법·봉·세팅 번호·종류, 코인·방향·진입과 청산 시각·보유 시간, 순ROE·청산 이유·손절 종류와 거리(가격 %), 장세(BTC 4시간)·진입 시각, 먼저 얼마나 이익 쪽으로 갔는지, 백테스트와 비교(그 매매법의 승률, 처음 보는 2025-26 승률, 보통 손실·최악 손실, 손절까지 보통 시간, 이 장세·이 코인에서의 승률), 연속 손실 몇 번째인지(백테스트 최장 3번, 처음 보는 기간 5번), 바이비트·MEXC가 따라갔는지(따라갔으면 순ROE와 가격 차이, 아니면 신호등이 막았는지).
- 판정은 하나: 정상 범위 손실 / 평소보다 큰 손실 / 실거래-페이퍼 차이 / 백테스트에서도 약한 자리 / 연속 손실 N번째.
- 4시간 뒤 값이 원래 방향으로 +11% ROE까지 돌아갔는지(노이즈 손절)를 확인해 다음 아침 점검에 한 줄로 붙입니다(따로 메시지 없음).
- 비교 숫자는 `deploy/combo.live-ac.expected.json`(백테스트 기준표)에서 옵니다. 설정 파일이 바뀌어 기준표와 다르면 아침 점검에 "참고만"이라고 적힙니다.

**기대 이탈**

- 페이퍼 최근 20번(또는 40번) 승리가 처음 보는 기간(2025-26) 백테스트의 하위 5%(20번 중 12승, 40번 중 25승)보다 적으면 소리 나게 "기대 범위 밑"이 옵니다.
- 맞춘 백테스트의 하위 5%(16승, 33승)보다 적지만 처음 보는 기간 기준 위면 소리 없는 참고, 한 매매법이 최근 5번 중 3번 이상 지면 소리 없는 참고입니다.
- 실행기가 페이퍼는 이긴 거래에서 진 것이 최근 20번 중 2번 이상이면 소리 나게 옵니다.
- 페이퍼 거래가 20번이 안 되면 "표본 작음"이라고만 적고 승률 알람은 보내지 않습니다.

**멈춤 요약**

- 실행기가 멈추면 한 번, 소리 나게: 어느 멈춤인지(3연패 / 낙폭 50% / STOP 파일 / 기타), 멈추기 전 거래와 그 손실 카드 판정, 시작 금액 대비 잔고, 페이퍼 최근 20번과 신호등, 그리고 9장의 안내("다시 켤지는 두 분이 정합니다")와 [`live-safety.md`](live-safety.md) 3-5의 `clear-halt` 명령 그대로.
- 푸는 순서와 규칙은 이 문서 9장과 위의 운영 원칙 그대로입니다(새 규칙 없음).

**손으로 돌리기**

```bash
cd /opt/crypto-bot-research
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.livecheck run --day 2026-10-19 --dry-run   # 10/19 09:00 ~ 10/20 09:00, 보내지도 저장하지도 않고 화면에만
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.livecheck show                             # 마지막 아침 메시지와 대조 차이 전체, 끝줄에 텔레그램 설정
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.livecheck watch --dry-run                  # 지금 울릴 알람이 있는지(보내지 않음)
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.livecheck preview                          # 모든 메시지 모양을 예시로(보내지 않음)
sudo systemctl list-timers paperbot-livecheck.timer paperbot-livewatch.timer                         # 다음 실행 시각
```

- `--day`는 점검하는 하루가 시작되는 날짜(그날 09:00)입니다. 다시 계산에 6~10분 걸립니다. 빨리 보려면 `--no-replay`(대조 없이).
- 설치(`deploy/install.sh`)가 두 타이머를 켭니다. 끄기: `sudo systemctl disable --now paperbot-livecheck.timer paperbot-livewatch.timer`.

## 13. 매매법 성적표와 개선 후보 장부 (10/19 추가)

실거래를 돌리면서 봇을 조금씩 고쳐 완성해 가는 도구입니다. 서버가 매주 페이퍼 봇(A+C 합본)의 거래를 매매법별로 채점하고, 손실이 몰리는 곳을 "개선 후보"로 장부에 적습니다. **봇과 설정은 하나도 바꾸지 않습니다.** 바꿀지는 두 분이 정합니다. 몇 번의 거래에 맞춰 고치지 않도록(과적합) 기준과 순서를 미리 정해 두었습니다.

**무엇을 보여 주나**

- **매매법 성적표**: 페이퍼 봇이 시작한 뒤 닫힌 거래를 매매법(27개)별, 세팅(95개)별로 셉니다. 거래 수, 승, 승률, 평균 순ROE(수수료 뺀 손익 ÷ 증거금), 진 거래 수, 진 거래 순ROE 중간값.
- 매매법은 이름과 봉으로 적습니다(예: `N03_ADX_GC 15분·30분`). 세팅 번호는 페이퍼 봇처럼 1부터 셉니다(예: `N03_ADX_GC 15분 · ATR 4배 · 즉시 진입 (#5)`, 손실 카드의 #번호와 같음).
- 옆에 백테스트 기준 두 개를 붙입니다(`deploy/combo.live-ac.expected.json`).
  - **맞춘 승률**: 전체 기간(2020-01~2026-09)에 맞춘 숫자입니다. 낙관적입니다(전체 91%).
  - **처음 보는 기간 승률**: 2020-24에만 맞춘 쌍둥이가 처음 보는 2025-26에서 낸 숫자입니다. 정직한 기준입니다(전체 75%). 본전은 77.6%입니다.
  - 그 매매법의 처음 보는 기간 거래가 30번 미만이면 전체 75%를 씁니다(표에 `*` 표시).
- **상태**: 실거래 승 수를 처음 보는 기간 승률과 비교합니다. p는 "그 승률이 맞다면 이만큼 적게 이길 확률"입니다. 작을수록 운으로 보기 어렵습니다.
  - **표본 작음**: 거래 10번 미만. 판단하지 않습니다.
  - **기대 안**: 운으로 설명되는 범위입니다.
  - **주의**: p가 0.05(5%)보다 작음.
  - **확실히 나쁨**: p가 0.05 ÷ 27 = 0.0019보다 작음. 27개를 함께 본 운까지 빼도 나쁩니다.
- 같은 표를 이렇게도 나눠 봅니다: 코인, 방향(롱·숏), BTC 4시간 장세(강상승·약상승·강하락·약하락·횡보), 한국 시간 4시간대(00~04시 …), 손절 방식(ATR 몇 배 = 평균 변동폭의 몇 배, % 고정, 스윙 N봉 = 최근 N봉의 고점·저점), 진입 방식(즉시 / 돌파 확인 뒤), 방향 뒤집기. 이 표들의 "확실히 나쁨" 기준은 각 표의 줄 수로 나눕니다(코인 표는 0.05 ÷ 6, 세팅 표는 0.05 ÷ 95).
- **실거래 열**: 바이비트·MEXC가 따라간 같은 거래에서 실제 순ROE - 페이퍼 순ROE(%p). -면 수수료·미끄러짐으로 샌 만큼입니다.
- 맨 위 줄: 전체 승률, 그리고 최근 20번·40번의 승 수를 백테스트의 "하위 5%"(맞춘 기간 16승·33승, 처음 보는 기간 12승·25승)와 비교합니다.

**"주의"와 "확실히 나쁨"을 정직하게 읽기**

- 거래가 적을 때의 차이는 대부분 운입니다. 처음 보는 기간 75%짜리 봇도 10번 중 5번 이하로 이길 확률이 8%쯤 됩니다.
- 매매법 27개를 한꺼번에 보면, 모두 정상이어도 운만으로 1~2개는 "주의"가 나옵니다. **"주의" 하나로는 아무것도 바꾸지 않습니다.**
- "확실히 나쁨"은 그 운을 빼고도 나쁜 경우입니다. 그래도 바로 끄지 않고 아래 장부 순서(백테스트 → 그림자)를 밟습니다.
- **거래 40번이 첫 진짜 점검입니다**(12장 아침 메시지의 판단과 같은 지점). 그 전에는 지켜보기만 합니다.
- 실거래가 맞춘 숫자(91%)보다 낮게 나오는 것은 예상된 일입니다. 비교 기준은 처음 보는 기간 숫자입니다.

**개선 후보 장부**

- 매주 한 번, 손실이 기대보다 몰린 칸을 찾습니다. 칸은 6가지입니다: 매매법, 매매법×코인, 매매법×장세, 매매법×방향, 코인×방향(모든 매매법), 한국 시간 4시간대(모든 매매법).
- 후보 조건: 그 칸의 실거래가 8번 이상이고 p<0.05(처음 보는 기간 승률과 그 칸의 맞춘 승률 중 낮은 쪽과 비교).
- 칸을 여러 개 보면 운으로도 후보가 나옵니다. 그래서 "이번에 본 칸 N개 · 운만으로도 약 몇 개는 나옴"을 함께 적습니다(본 칸 수 × 5%). 그 몫을 빼고도 남는 후보에는 "여러 칸 보정 뒤에도 남음"이 붙습니다.
- 새 후보는 장부에 **발견**으로 적히고, 바로 돌릴 수 있는 연구 질문이 붙습니다. 예: "F5_BOX_RSI 30분 SOL 끄기: 2020-24와 2025-26 둘 다 좋아지나? 거래 수는 얼마나 줄어드나?"
- 같은 거래들이 여러 칸으로 보이면 후보 하나로 묶습니다. 예: F5_BOX_RSI의 SOL 숏만 졌다면 'F5_BOX_RSI SOL', 'F5_BOX_RSI 숏', '모든 매매법 SOL 숏'이 모두 같은 거래입니다. 가장 좁은 칸 하나만 장부에 적고, 다른 칸은 질문에 "함께 비교"로 붙입니다. 실거래로는 셋을 구별할 수 없고, 백테스트로 구별합니다.
- 같은 칸은 두 번 적히지 않습니다. 매주 그 칸의 "지금" 실거래 증거(거래 수, 승, p)만 새로 고칩니다.
- **고정 규칙은 후보가 되지 않습니다**: 레버리지, 계단 익절, 증거금 40%, 한 번에 포지션 하나, 코인 6개, 주말 쉬기, 미국 지표 ±30분 진입 없음.
- 상태는 사람만 명령으로 바꿉니다. 메모와 날짜가 남습니다: **발견 → 백테스트 시험 → 그림자 시험 → 채택 또는 기각.** 기각한 것은 다시 "발견"으로 열 수 있습니다.
- 그림자 시험은 11장의 그림자 페이퍼 봇과 같은 방식입니다. 바꾼 설정 파일(`deploy/combo.shadow-이름.json`)은 개발자에게 부탁하고, `paperbot-combo-shadow@이름`으로 켭니다. 돈은 걸리지 않습니다.

**채택 규칙 (미리 정함, 셋 다 맞아야 채택)**

1. (a) 실거래에서 그 칸 거래 20번 이상, p<0.05.
2. (b) 백테스트에서 2020-24와 2025-26을 따로 돌려 둘 다 좋아짐.
3. (c) 바꾼 그림자 페이퍼 봇이 2주 이상 또는 거래 20번 이상 돌고, 지금 페이퍼 봇보다 나쁘지 않음.

- 장부 명령이 이 규칙을 지킵니다. (a)가 안 맞거나, (b)·(c) 확인 표시(`--backtest-ok`, `--shadow-ok`)가 없거나, 그림자 시험이 2주(또는 거래 20번)가 안 됐으면 "채택"으로 바꾸지 않습니다.
- 채택해도 자동으로 바뀌는 것은 없습니다. 설정 변경은 두 분이 따로 합니다(4장).

**월요일 메시지 (09:30, 한 통)**

- 첫 줄: "📊 주간 성적표 · 10/19~10/25"(지난 7일, 하루는 09:00 ~ 09:00).
- 내용: 이번 주와 시작부터의 성적, 기대보다 잘하는 매매법·못하는 매매법(각 3개까지), 실거래가 따라간 거래의 비용, 새 후보와 질문, 열린 장부와 다음 할 일, 채택 규칙.
- 승률은 "17/20 (85%)"(승/거래), 돈은 "+$12.34"처럼 적습니다. 페이퍼 손익은 페이퍼 계좌($1,000) 기준입니다.
- 실거래 알림과 같은 텔레그램 채팅과 소리 규칙으로 갑니다.
- **소리 없이** 옵니다. 매매법이나 전체에 "확실히 나쁨"이 있을 때만 **소리 나게**("🚨 주간 성적표 · 10/19~10/25 · 확실히 나쁨 N개") 옵니다. 다른 표(코인 등)의 "확실히 나쁨"은 소리를 내지 않습니다. 표가 많아 운으로도 자주 나오기 때문입니다. 그런 칸은 후보 장부로 갑니다.
- 결과는 `/var/lib/paperbot/liveimprove.db`에 남습니다(나중에 대시보드용): 주간 성적표 `snapshots`, 주간 기록 `weeks`, 장부 `ledger`, 장부 변경 기록 `ledger_log`.

**손으로 돌리기**

```bash
cd /opt/crypto-bot-research
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.liveimprove score                      # 매매법별 성적표
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.liveimprove score --by member          # 세팅별 (coin, side, reg5, hb, stop, entry, invert, all도 됨)
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.liveimprove score --since 2026-11-02   # 그날 09:00부터의 거래만
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.liveimprove candidates --dry-run       # 후보 찾기만, 장부에 안 씀
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.liveimprove weekly --dry-run           # 월요일 메시지 미리 보기, 안 보내고 안 씀
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.liveimprove preview                    # 손으로 만든 한 주로 본 메시지 모양(--loud: 확실히 나쁨이 있는 주)
sudo systemctl list-timers paperbot-liveimprove.timer                                             # 다음 실행 시각
```

**장부 명령**

```bash
cd /opt/crypto-bot-research
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.liveimprove ledger list
# 백테스트를 시작할 때
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.liveimprove ledger set 3 --status "백테스트 시험" --note "질문대로 두 기간 돌림"
# 두 기간 모두 좋아졌을 때: (b) 확인
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.liveimprove ledger set 3 --status "그림자 시험" --backtest-ok --note "두 기간 다 좋아짐, 거래 -9%"
# 2주(또는 20번) 뒤 그림자가 지금 봇보다 나쁘지 않을 때: (c) 확인
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.liveimprove ledger set 3 --status 채택 --shadow-ok --note "그림자 22번 86%, 지금 봇 84%"
# 아니면 언제든
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.liveimprove ledger set 3 --status 기각 --note "2025-26에서 나빠짐"
```

- `--note`(메모)는 꼭 적습니다. 무엇을 보고 바꿨는지가 날짜와 함께 장부에 남습니다.
- 그림자 시험이 2주가 안 됐지만 그림자 거래가 20번을 넘었으면 `--shadow-trades 22`처럼 그 수를 적습니다.
- 설치(`deploy/install.sh`)가 월요일 타이머를 켭니다. 끄기: `sudo systemctl disable --now paperbot-liveimprove.timer`.
- 읽기만 합니다. 페이퍼 봇과 실행기의 DB는 읽기 전용으로 열고, 거래소에 연결하지 않고, 주문을 내지 않습니다.

## 14. 대시보드 실거래 화면 (10/19 추가)

규칙봇 대시보드의 **실거래** 메뉴(금색 점)입니다. 주문 버튼은 없고 보기만 합니다. 맨 위 금색 줄 "진짜 돈"이 있는 화면은 실거래, 나머지는 모의입니다.

| 탭 | 보는 것 |
|---|---|
| 관제 (처음 화면) | 바이비트·MEXC 잔고와 상태, 열린 포지션의 손절·잠금 게이지, **⏳ 진입 대기**(돌파를 기다리는 신호: 넘어야 할 가격·남은 %·마감까지 남은 시간), **진입 가능성 TOP 5**, **왜 지금 진입 안 하나**(주말·지표 시간·포지션 있음·실행기·신호등), 오늘 24시간 쉬는 시간, 40번 판단까지, 매매법 27개가 이번 주 낸 신호 |
| 요약 | 규칙봇 터미널 모양의 실거래 화면 (차트·체결·포지션·수익 달력) |
| 순위 | 위쪽 스위치로 두 가지. **진입 가능성**(처음 화면): 지금과 같은 요일·한국 시각에 5년 동안 1·4·24시간 안에 그 매매법의 진입 신호가 나온 비율(최근 2025~26년이 큰 숫자, 5년은 작게)로 줄 세움. 돌파를 기다리는 신호가 있는 매매법이 맨 위(⏳). 이길 확률이 아니라 신호가 나오는 빈도이고, 예측이 아니라 과거 빈도예요. **성적 순위**: 페이퍼·실거래 성적, 이번 주 신호, 5년 시험 승률(맞춘 숫자)과 처음 보는 기간 승률(현실 숫자), 성적표 판정. 거래 전에는 5년 시험 순서 |
| 분석팀 | 실거래 분석 팀(AI 4명)의 회의 기록, 결론, 시험해 볼 아이디어, AI 사용량, 켜짐/꺼짐 (15장) |
| 신호 | 맨 위에 **⏳ 진입 대기**(관제와 같은 것, 대기가 없으면 15분·30분·1시간 봉 다음 마감 시각), 그 아래 전과 같은 신호 기록 |
| 차트 · 거래 · 성적 | 전과 같음 |
| 지도 | 기대 범위 띠(이긴 횟수가 현실 기대 범위 안에 있나)와 장세·코인·시간대·롱숏별 성적을 5년 숫자 옆에 |
| 비용 | 실거래가 페이퍼보다 얼마나 덜 버나(진입가 차이·수수료·펀딩), 따라가지 못한 페이퍼 거래와 이유 |
| 일정 | 지금 진입할 수 있는 시간인지, 앞으로 7일의 쉬는 시간, 미국 지표(CPI·FOMC·고용·PCE) 3주치와 한국 시간, 시장 숫자 |
| 안전 · 그림자 · 설정 | 전과 같음 |

- 진입 가능성 표(`deploy/combo.live-ac.likely.json`)는 지금 설정 95개로 만든 것입니다. 설정을 바꾸면 이 표도 다시 만들어야 합니다(안 바꾸면 테스트가 실패해서 알 수 있어요).
- 거래가 적을 때의 순위와 장세별 숫자는 대부분 운입니다. 20번 미만은 "표본 적음"으로 표시됩니다.
- 일정 탭이 "등록된 일정이 곧 끝나요"라고 하면 `data/macro_events.csv`에 다음 해 일정을 넣어야 합니다(12/23 전).

## 15. 실거래 분석 팀 (AI, 10/19 추가)

AI 팀원 4명이 실거래 기록을 읽고 쉬운 말로 설명합니다. **읽기만 하고 매매 권한이 없습니다.** 주문, 설정, 고정 규칙은 건드리지 않습니다.

| 팀원 | 맡은 것 |
|---|---|
| 방패 (리스크 담당) | 잔고·낙폭, 연속 손실, 멈춤, 신호등, 실거래가 페이퍼를 제대로 따라갔는지, 비용 |
| 저울 (통계 담당) | 우연인지 아닌지: 거래 수, 현실 기대 범위, 5년 숫자(맞춘 숫자와 현실 숫자) |
| 나침반 (시장 담당) | 장세, 코인, 시간대, 롱/숏, 미국 경제 발표 |
| 등대 (팀장) | 셋의 말을 모아 결론, 걱정, 다음에 볼 것, 시험해 볼 아이디어(최대 3개) |

회의는 코드가 정한 때만 열립니다.
- **손실 회의**: 바이비트나 MEXC 실거래의 마지막 닫힌 거래 2개가 모두 손실일 때(3일 안), 그 두 거래로 한 번.
- **판단 회의**: 페이퍼 거래가 40, 80, 120…번이 될 때(두 분의 40번 판단).
- **주간 보고**: 월요일 10:00부터(09:30 매매법 성적표 다음), 지난 한 주. 닫힌 거래가 없으면 AI 없이 한 줄만 남깁니다.

결과는 대시보드 **실거래 › 분석팀** 탭에 쌓이고, 결론만 실거래 텔레그램(새 봇 개인 채팅)으로 조용히 갑니다. 아이디어는 "제안"으로만 남고, 장부에 올릴지는 두 분이 정합니다(13장 순서: 백테스트 → 그림자 봇 → 채택 규칙).

**설치하면 꺼져 있습니다.** 실거래가 20번쯤 쌓이면(약 1주) 켭니다.

```
sudo systemctl enable --now paperbot-liveteam.timer      # 켜기 (15분마다 열릴 회의가 있는지 봄)
sudo systemctl disable --now paperbot-liveteam.timer     # 끄기
cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.liveteam status
```

- 미리 보기(AI 안 부름, 보내지 않음): `... -m paperbot.liveteam preview weekly` (팀원이 읽을 사실과 지시문을 그대로 보여 줌)
- 연습 회의(가짜 답, 보내지 않음): `... -m paperbot.liveteam run weekly --force --dry-run`
- AI 사용은 규칙봇 회의실과 같은 Claude 구독(`/etc/paperbot/agents.env`의 로그인)을 씁니다. 기본 한도는 하루 12번, 최근 7일 40번, 하루 토큰 90만입니다. 회의 하나는 3~4번을 씁니다. 바꾸려면 agents.env에 `LIVETEAM_BUDGET=day=8,week=30` 같은 줄을 넣습니다.
- 한도가 모자라면 회의를 미뤘다가 다음에 엽니다. Claude 사용 한도에 걸리면 그 회의는 멈추고, 그 이유가 탭에 남습니다.
