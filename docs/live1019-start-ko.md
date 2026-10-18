# 10/19(월) 실거래 시작 순서: 바이비트 $100 + MEXC $100

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
- 실행기 전용 **하위 계정**을 만들고 USDT $100만 넣습니다($120 넘으면 실행기가 거부합니다).
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
| 고원형 합본 (추천) | `deploy/combo.live-plateau37.json` | `/var/lib/paperbot/combo/live-plateau37.db` |
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
    "daily_max_loss_usd": 40,
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

preflight에서 다음이 모두 `[OK]`여야 합니다: 주소 api.bybit.com, 키 권한(출금 꺼짐·IP 제한·하위 계정), 지갑 $120 이하·USDT만.

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
| 하루 손실 | $40 | 하루 계좌 40% 이상 손실은 3일 |

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
