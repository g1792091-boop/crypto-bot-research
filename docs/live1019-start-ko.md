# 10/19(월) 실거래 시작 순서: 바이비트 $100 + MEXC $100

두 분이 10/18 밤에 정한 것:
- 매매법: 16개 매매법 봇(설정 78개). 2020-01~2026-09 전체 백테스트가 가장 좋았던 조합입니다.
- 고정 규칙: BTC 40배, 알트 30배, 계단식 익절(ROE 11%에서 10% 잠금, 이후 3%씩), 증거금 = 계좌의 40%, 한 번에 한 포지션, 코인 6개.
- 주말(한국 시간 토·일)에는 진입하지 않습니다. 미국 경제 발표(CPI·고용·FOMC·PCE) 앞뒤 30분에도 진입하지 않습니다.
- 봇 두 개를 따로 돌립니다. 바이비트 $100, MEXC $100. 둘 다 같은 신호(같은 페이퍼 계좌)를 따라갑니다.

## 0. 백테스트 숫자 (알고 시작할 것)

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
- 이 구조는 손익분기 승률이 약 81~84%입니다. 실거래 승률이 90% 위면 크게 벌고, 80% 아래로 내려가면 줄어듭니다.
- 그래서 처음 며칠은 **승률**을 가장 먼저 봅니다(7장).

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

## 4. 합친 봇(페이퍼)을 16개 설정으로 바꾸기

```bash
# 실행기가 돌고 있으면 먼저 멈추고 실제 포지션이 없는지 확인
sudo touch /var/lib/paperbot/STOP
sudo systemctl stop paperbot-combo
sudo cp /opt/crypto-bot-research/deploy/combo.live16w.json /etc/paperbot/combo.json
cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo check-config --config /etc/paperbot/combo.json
```

마지막 줄이 **"준비됨"**이면 켭니다.

```bash
sudo systemctl start paperbot-combo
sudo journalctl -fu paperbot-combo      # "[합친 봇 페이퍼] 시작" 확인 (1분봉 7일치를 받느라 몇 분 걸림)
```

- 페이퍼 DB는 새 파일 `/var/lib/paperbot/combo/live16w.db`입니다. 옛 DB는 지우거나 옮기지 마세요.
- 규칙봇(paperbot-live3)이 돌고 있어야 합니다. 합친 봇은 규칙봇의 1분봉을 읽습니다.

## 5. 바이비트 실행기 설정

```bash
sudo nano /etc/paperbot/executor.json
```

```json
{
  "exchange": "bybit",
  "mode": "mainnet",
  "account": "COMBO@mix",
  "paper_db": "/var/lib/paperbot/combo/live16w.db",
  "db": "/var/lib/paperbot/exec/executor-bybit-live16w.db",
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

```bash
sudo nano /etc/paperbot/executor-mexc.json
```

5장의 바이비트 설정과 같고, 아래 세 줄만 다릅니다.

```json
  "exchange": "mexc",
  "mode": "mainnet",
  "db": "/var/lib/paperbot/exec/executor-mexc-live16w.db",
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
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo status --db /var/lib/paperbot/combo/live16w.db
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-bybit-live16w.db
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-mexc-live16w.db
```

| 볼 것 | 기준 |
|---|---|
| 실거래 승률 | 백테스트 92%. 20번 넘게 거래한 뒤 85% 아래면 알려 주세요(손익분기 81~84%) |
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
