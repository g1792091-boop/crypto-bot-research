# 숏5 하락장 봇 (10/25)

두 분이 10/25에 "내일 실거래봇은 일단 돌려야" 한다고 하셔서 준비한 봇입니다. 연구 결과에서 가장 나았던 조합을 그대로 옮겼습니다.
근거는 `analysis/review1024/sweep1025/REPORT_KO.md`에 있습니다.

## 0. 먼저 숫자 (솔직하게)

**매달 ×5가 나오는 봇은 아닙니다.** 2020~2026년 수만 개 조합을 시험했지만 매달 ×5를 이어 간 조합은 없었습니다. 이 봇은 "가끔 한 달에
×5가 나오는 봇"입니다.

| 기간 | 결과 |
|---|---|
| 10/06~10/24 (19일) 시뮬레이션, 신호등 포함 | ×7.2 |
| 같은 기간, 봇 코드 그대로 재현 (페이퍼 비용 왕복 0.14%) | ×4.95 (진입 56개 중 47개 일치) |
| 2026년 1~9월, 아무 날에 시작한 30일 | ×5 도달 약 14% (7번에 1번), −30%에 먼저 닿음 약 33~37% |
| 2020~2026년 79개월, 매달 새로 시작 | ×5 달 3번, 바닥(−30%)에서 멈춘 달 20~32번 |
| 두 달 연속 ×5 | 한 번도 없음 |

- **비용에 아주 민감합니다.** 왕복 비용 0.12% → 0.16% → 0.20%에서 30일 ×5 확률이 12.7% → 4.5% → 0.4%입니다. 그래서 **바이비트로만**
  돌립니다(측정한 왕복 비용 0.116%).
- **실거래는 시뮬레이션보다 낮게 나옵니다.** 10월 시뮬레이션 ×7.5가 봇 코드 재현에서 ×4.95였습니다. 계단 잠금 근처에서 비용·슬리피지에
  따라 결과가 갈리기 때문입니다.
- **다 잃어도 되는 금액으로만** 하시고, ×5가 나오면 수익을 빼세요(6장).

## 1. 어떤 봇인가

- 페이퍼 봇 `paperbot-combo-short5` (설정 `/etc/paperbot/combo-short5.json`, 기록 `/var/lib/paperbot/combo/short5.db`)가 신호를 내고,
  바이비트 실행기 하나가 그 페이퍼를 따라 실제 주문을 냅니다.
- 고정 규칙: BTC 40배, 나머지 30배, 증거금 잔고의 40%, 한 포지션, 시장가, 기존 6개 코인.
- 매매법 5개, **BTC 4시간봉이 하락장일 때만** 들어갑니다. 상승장·횡보장일 때는 거래하지 않고 쉽니다.
  - 장세: BTC 4시간봉 ADX14가 20 미만이면 횡보장, 아니면 EMA50 위면 상승장, 아래면 하락장.
  - 1·2·3번은 숏만, 4·5번은 양방향입니다.

| 번호 | 매매법 | 봉 | 방향 | 손절 |
|---|---|---|---|---|
| 1 | V39_ALL | 15분 | 숏만 | 2.38% |
| 2 | S6_EMA_DMI_ADX | 15분 | 숏만 | 1.55% |
| 3 | F12_MSS | 1시간 | 숏만 | 2.38% |
| 4 | N12_ICHI_AO | 30분 | 양방향 | 2.38% |
| 5 | F16_FIB382 | 4시간 | 양방향 | 1 ATR |

- 익절: 계단. 순ROE 12%에서 10% 잠금, 이후 5%씩 올라갑니다. 고정 익절은 없습니다.
- 손절 한 번이 잔고의 35%를 넘지 않게 크기를 줄입니다(`max_loss_frac` 0.35).
- 실거래 실행기에만 붙는 두 가지:
  - **신호등**: 페이퍼의 최근 20번 중 90% 이상 이겼을 때만 진입을 따라갑니다. 페이퍼는 계속 거래합니다.
  - **잔고 바닥**: 잔고가 시작 금액의 70%에 닿으면 새 진입을 멈춥니다. 열린 포지션은 거래소 손절·계단이 그대로 지킵니다.
  - 둘 다 2020~25년 바닥 달을 크게 줄였습니다(신호등 없음 69달 → 있음 20~32달, 79개월 중).

## 2. 준비물

- 바이비트 선물 계좌에 정한 금액. 실행기 키는 지금 바이비트 실행기가 쓰는 키 그대로입니다(새 키 필요 없음).
- 지금 바이비트 실행기(`paperbot-executor`)는 추세판단 봇 페이퍼(`live-ac.db`)를 따라가고 있습니다. 아래 C에서 이 실행기를 숏5 봇으로
  옮깁니다. **WOO X Pro 실행기와 딥코인 실행기는 건드리지 않습니다.**

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

- 끝에 `숏5 하락장 페이퍼 봇(paperbot-combo-short5) 설치만 했습니다` 줄이 나옵니다.

### B. 숏5 페이퍼 봇 켜기 — 언제든 (돈·주문 없음)

```bash
sudo install -o root -g paperbot -m 640 /opt/crypto-bot-research/deploy/combo.short5.json /etc/paperbot/combo-short5.json
cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo check-config --config /etc/paperbot/combo-short5.json
```

- 확인 줄: `배수: BTCUSDT 40배, ETHUSDT 30배, …  / 증거금: 40%`, `계단 익절: 순ROE 12%에서 10% 잠금, 이후 5%씩`, 매매법 1~5번
  (각 줄 끝에 `끄기 장세2` = 상승장·횡보장에서 끔), 마지막 줄 **`준비됨`**.

```bash
sudo systemctl enable --now paperbot-combo-short5
systemctl is-active paperbot-combo-short5
```

- `active`. 텔레그램에 `[합친 봇 페이퍼 숏5 하락장] 시작: …`이 옵니다.
- 1~2분 뒤 기록 확인:

```bash
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo status --db /var/lib/paperbot/combo/short5.db
```

- `마지막 1분봉: (지금에 가까운 시각) KST`, `COMBO@mix: 지갑 $1,000.00, 거래 0번 …`. 이때부터 페이퍼로 돌기 시작합니다.

### C. 바이비트 실행기를 숏5 봇으로 옮기기 — 실행기에 포지션이 없을 때만

1) 포지션 확인 → 끄기:

```bash
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-bybit-live.db
sudo systemctl stop paperbot-executor
```

- 첫 줄이 `포지션: null`일 때만 끕니다. 포지션이 있으면 닫힐 때까지 기다립니다.

2) 먼저 보기만 (아직 안 바뀜). `123.45` 자리에 바이비트 선물 잔고(달러)를 넣습니다:

```bash
cd /opt/crypto-bot-research && sudo python3 deploy/short5_switch.py --exec bybit --balance 123.45
```

- 나오는 줄: `paper_db: "/var/lib/paperbot/combo/live-ac.db" → "/var/lib/paperbot/combo/short5.db"`, `ladder: … → {"first_lock": 0.1,
  "trigger_gap": 0.02, "step": 0.05}`, `signal_light_n: 0 → 20`, `signal_light_min_win: null → 0.9`, `equity_floor_frac: null → 0.7`,
  `budget_usd`, `qty_scale`, `(실거래 크기 = 페이퍼 수량 × …)`.
- 잔고가 약 $625를 넘으면 `(주의) … risk.max_notional_usd가 $10,000라 그 크기로 줄여 들어갑니다`가 나옵니다(7장).
- 숏5 페이퍼 기록이 아직 없거나 실행기가 켜져 있으면 `멈춤 - …`이 나오고 아무것도 바꾸지 않습니다.

3) 바꾸기 → 확인:

```bash
cd /opt/crypto-bot-research && sudo python3 deploy/short5_switch.py --exec bybit --balance 123.45 --write
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor.json
sudo /opt/crypto-bot-research/deploy/paperbot-exec.sh executor preflight --config /etc/paperbot/executor.json
```

- 예전 설정은 `/etc/paperbot/executor.json.before-short5-<시각>`으로 남습니다.
- check-config에서 볼 줄: `계단: 순ROE 12%에서 10% 잠금, 이후 5%씩`, `순ROE 비용: 바이비트 테이커 0.044% + 슬리피지 0.02% (한쪽),
  왕복 0.128%`, `신호등: 켜짐 - paper 최근 20번 중 90% 이상 이겼을 때만 진입을 따라감`, `잔고 바닥: 켜짐 - 잔고가 시작 금액(처음 돌 때
  기록)의 70%에 닿으면 새 진입 멈춤 …`, 마지막 줄 **`준비됨`**. preflight도 모두 `[OK]`여야 합니다.

4) 켜기 → 확인:

```bash
sudo systemctl start paperbot-executor
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-bybit-live.db
```

- 기록에 `시작: paper 계좌 COMBO@mix 따라 하기 (페이퍼 DB /var/lib/paperbot/combo/short5.db), mainnet, …`. `포지션: null`.
- 텔레그램에 `시작 금액 기록: 이 계정의 잔고 $…`이 옵니다. **이 금액이 바이비트 앱의 선물 잔고와 맞는지** 확인하세요.
- status에 `잔고 바닥: 시작 금액 $…(… 기록)`이 오늘 날짜가 아니라 예전 금액이면, 끄고 6장의 clear-floor를 한 번 한 뒤 다시 켭니다.
- 숏5 페이퍼가 이미 포지션을 들고 있었으면 `paper 진입이 n초 전이라 따라 하지 않습니다`가 하나 생깁니다. 정상입니다(다음 진입부터 따라감).

### D. 되돌리기 — 추세판단 봇으로 다시 (포지션이 없을 때만)

```bash
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-bybit-live.db
sudo systemctl stop paperbot-executor
cd /opt/crypto-bot-research && sudo python3 deploy/short5_switch.py --exec bybit --back --write
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor.json
sudo systemctl start paperbot-executor
```

- 가장 최근 `.before-short5-<시각>` 사본(옮기기 전 설정)으로 돌아갑니다.
- 숏5 페이퍼 봇은 계속 돌려도 되고(비교용), 끄려면 `sudo systemctl disable --now paperbot-combo-short5`.
- `sudo touch /var/lib/paperbot/STOP`(비상 정지)은 **모든 실행기를** 닫고 멈춥니다. 바이비트만 멈출 때는 쓰지 않습니다.

## 4. 처음 며칠 지켜볼 것

- **처음 20번은 신호등 없이 다 따라갑니다.** 페이퍼가 내일 새로 시작해서 닫힌 거래가 20번 쌓일 때까지는 신호등이 판단할 기록이 없습니다.
  시험 숫자(신호등 포함)는 기록이 이미 쌓인 상태 기준이라, 처음 20번은 "신호등 없음" 쪽 숫자에 가깝습니다(2026년 30일 ×5 약 9%,
  −30% 먼저 약 73%).
- BTC 4시간봉이 하락장이 아니면 며칠씩 거래가 없을 수 있습니다. 고장이 아닙니다.
- 페이퍼와 실거래의 진입·청산이 같은지 매일 한 번 봅니다(사이트 재현 비교, 또는 두 status).
- 실거래 크기는 "페이퍼 수량 × 고정 배율"입니다. 신호등이 진입을 건너뛰는 동안 페이퍼와 실거래 잔고가 벌어지면 크기도 조금 달라집니다.
  이 방식대로 다시 계산해 봤더니 30일 ×5 확률 13.9%(잔고 40%로 매번 맞출 때 14.2%), −30% 먼저 33%(37%)로 거의 같았습니다
  (`analysis/review1024/sweep1025/out/size13.json`).

## 5. 텔레그램과 사이트

- 숏5 페이퍼 봇은 자기 진입·청산을 텔레그램으로 보냅니다(`[합친 봇 페이퍼 숏5 하락장] …`).
- 바이비트 실행기 메시지는 지금과 같은 모양으로 옵니다. 신호등이 진입을 건너뛰면 `신호등 빨강: paper 최근 20번 중 n번 이김 …`이 기록됩니다.
- 아침 점검은 이 페이퍼 봇이 멈추면 `sudo systemctl status paperbot-combo-short5`를 할 일로 알려 줍니다.
- 사이트(8093)의 VWAP 화면은 VWAP 페이퍼 전용입니다. 숏5 페이퍼는 status 명령으로 봅니다. 바이비트 실행기 칸은 그대로 보입니다.

## 6. 매달 할 일 (월초, 실행기에 포지션이 없을 때)

목표가 "한 달 ×5"라서 달마다 새로 시작합니다.

1. ×5가 됐으면 수익을 먼저 뺍니다(바이비트 앱). 바닥(−30%)에서 멈췄으면 계속할지 두 분이 정합니다.
2. 실행기를 끄고, 잔고 바닥 기록을 지우고, 새 잔고로 크기를 다시 맞추고, 켭니다:

```bash
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-bybit-live.db
sudo systemctl stop paperbot-executor
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor clear-floor --config /etc/paperbot/executor.json --by 이름 --note "월초 새 시작"
cd /opt/crypto-bot-research && sudo python3 deploy/short5_switch.py --exec bybit --balance 123.45 --write
sudo systemctl start paperbot-executor
```

- `123.45`는 그때의 바이비트 선물 잔고입니다. 켜면 그 잔고가 새 시작 금액으로 기록되고(텔레그램), 70% 바닥도 그 금액 기준이 됩니다.
- 입금·출금 뒤에도 같은 순서로 다시 맞춥니다.

## 7. 주의할 점

- **크기 상한**: 바이비트 실행기 설정의 `risk.max_notional_usd`는 $10,000입니다. BTC 40배 × 40%면 잔고의 16배라, 잔고가 약 $625를
  넘으면 BTC 포지션이 상한으로 줄어듭니다(알트 30배는 약 $833부터). 올릴지는 두 분이 정합니다. 올리려면 `/etc/paperbot/executor.json`의
  그 숫자를 바꾸고 check-config 뒤 다시 켭니다.
- WOO X Pro나 딥코인으로 돌리면 비용 때문에 확률이 크게 떨어집니다(0장). 도구도 `(주의) … 바이비트로 돌리는 것을 권합니다`를 띄웁니다.
- 지금 바이비트 실행기를 옮기면 그동안 추세판단 봇은 실거래 없이 페이퍼로만 돕니다(WOO X Pro 실행기가 따라가는 쪽은 그대로).

## 8. 근거 파일

- 연구: `analysis/review1024/sweep1025/REPORT_KO.md` (0~6장), `s12_light.py`·`out/light12.json`(신호등·바닥),
  `s13_size.py`·`out/size13.json`(실행기 크기 방식), `parity/`(봇 코드 재현).
- 설치: `deploy/combo.short5.json`, `deploy/paperbot-combo-short5.service`, `deploy/short5_switch.py`,
  `deploy/executor.live-bybit-short5.json`(도구가 $100·페이퍼 $1,000일 때 쓰는 결과와 같은 견본), `tests/test_short5_switch.py`.
