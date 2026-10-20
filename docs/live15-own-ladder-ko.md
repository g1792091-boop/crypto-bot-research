# 거래소 기준 익절 (10/20 결정)

**결정(10/20):** "거래소 기준으로 익절해야지". 바이비트·MEXC 실행기는 계단 익절을 **자기 포지션으로** 판단합니다.
자기 체결가, 자기 거래소의 가격, 자기 거래소의 수수료로 계산합니다. 페이퍼의 잠금은 더 이상 따라가지 않습니다.

## 왜 (10/20 DOGE 30배 롱)

| | 진입가 | 첫 잠금(순ROE +11%) 자리 | 거래소 최고가 0.07974에서 | 결과 |
|---|---|---|---|---|
| 페이퍼 (바이낸스 1분봉, 비용 왕복 0.14%) | 0.07937 | 0.07977 | 닿지 않음 | 잠금 없음 |
| 바이비트 (비용 왕복 0.15%) | 0.07924 | 0.07965 | 순ROE +14.4% | **+10% 잠금, 손절 0.07963** |
| MEXC (비용 왕복 0.20%) | 0.07925 | 0.07970 | 순ROE +12.5% | **+10% 잠금, 손절 0.07968** |

- 예전 실행기는 페이퍼가 잠글 때만 거래소 손절을 옮겼습니다. 페이퍼는 자기 진입가(0.07937)와 바이낸스 가격으로 0.07977을
  기다렸고, 거래소 가격은 0.07974에서 꺾였습니다. 그래서 두 거래소 모두 자기 체결가로는 순ROE +11%를 넘었는데도 아무것도
  잠기지 않았습니다.
- 이제는 위 표의 아래 두 줄처럼 됩니다(숫자는 `tests/test_executor_own_ladder.py`가 같은 식으로 확인합니다).

## 무엇이 바뀌나

- 실행기가 3초쯤마다 **자기 거래소의 1분봉 고가·저가**를 체결 뒤부터 읽어 최고가(숏은 최저가)를 잡습니다. 두 번 확인하는 사이에
  잠깐 튄 가격도 1분봉에 남아 있어 놓치지 않습니다. 거래소 손절이 걸리는 가격(마지막 체결가)과 같은 가격입니다.
- 체결한 바로 그 1분은 체결 전 가격이 섞일 수 있어서 그 분의 고가는 쓰지 않고, 확인할 때마다 그 순간의 가격(그 분의 종가)만
  씁니다. 그래서 체결하고 1분 안에 잠깐 튀었다 돌아온 가격은 못 볼 수 있습니다.
- 순ROE = 배수 × (가격 변화 − 왕복 비용). 왕복 비용 = 2 × (테이커 수수료 + 슬리피지):
  바이비트 2 × (0.044% + 0.02%) = **0.128%**, MEXC 2 × (0.08% + 0.02%) = **0.20%** (설정의 `net_costs`). 펀딩은 넣지 않습니다.
- 계단에 닿으면 거래소 손절을 그 잠금 자리로 올립니다. **손절은 올리기만 하고 내리지 않습니다.**
- 잠금 자리가 이미 지나 있으면(올리려는 사이 가격이 내려감) 예전처럼 바로 시장가로 닫습니다.
- 손절 옮기기가 실패하면 옛 손절이 그대로 있고, 3초 뒤 다음 확인에서 다시 합니다. 잠금은 거래소 손절이 실제로 옮겨진 뒤에만
  기록합니다.
- 최고가와 잠금은 실행기 기록에 저장됩니다. 실행기를 다시 켜도 그대로이고, 꺼져 있던 동안의 1분봉도 다시 읽습니다(최대 3일).
- 1분봉을 못 읽으면 그 순간의 가격만 보고(경고 알림), 다음에 못 읽은 분을 다시 읽습니다. 거래소가 빈 목록이나 2분보다 오래된 분만
  돌려줘도 못 읽은 것으로 봅니다("가격이 안 움직였다"로 보지 않음).

## 그대로인 것

- 순ROE의 뜻(수수료·슬리피지 포함)과 계단: **11%에서 10%, 15%에서 12%, 20%에서 17%, 25%에서 22%, 그 뒤 5%마다**(닿은 순ROE − 3%).
  설정의 `ladder`는 각 실행기가 따라가는 페이퍼 봇 설정의 `ladder`와 같습니다(시험으로 확인).
- 진입: 페이퍼 진입을 예전처럼 따라갑니다(실거래가 아직 자기 포지션을 들고 있을 때는 빼고: 아래 결정 1). 처음 손절도
  예전처럼 페이퍼 손절과 같은 거리입니다(`stop_from` "ratio").
- 빠른 손절(같은 매매법의 반대 신호): 페이퍼가 반대 신호로 닫으면 따라 닫습니다. 단 **그 실행기가 자기 첫 잠금 전일 때만**입니다.
- 비상 정지 파일, 진입 한도, 한 번에 포지션 하나.

## 페이퍼가 닫을 때 실거래가 하는 일

| 페이퍼 청산 이유 | 실거래(거래소 기준) |
|---|---|
| 손절 (SL), 계단 익절 (LOCK), 강제청산 (LIQ), 익절 (TP) — 페이퍼 가격의 자리 | 따라 닫지 않음. 자기 손절·자기 계단으로 계속 |
| 빠른 청산 (REV, 반대 신호) | 자기 첫 잠금 **전**이면 따라 닫음, 잠근 **뒤**면 닫지 않음 |
| 멈춤 청산 (HALT), 수동 청산 (MANUAL), 그 밖의 이유 | 따라 닫음 |
| 청산 기록을 못 읽음 | 30초 기다린 뒤 따라 닫음 (그동안 거래소 손절이 지킴) |

## 실거래가 아직 들고 있는데 페이퍼가 새로 진입할 때 (10/20 결정 1)

- 실거래 포지션은 **이 이유로는 절대 닫지 않습니다.** 자기 손절·자기 계단으로만 끝납니다.
- 페이퍼의 새 진입은 **따라가지 않습니다.** 실행기 기록에 한 번 남깁니다:
  `실거래가 아직 자기 포지션(거래소 기준, BTCUSDT 롱)을 들고 있어 이번 진입은 따라가지 않음`.
  알람이 아니라 **놓친 신호**로 보입니다(텔레그램 진입 줄, 못 탄 신호, 8093 사이트). "실거래가 페이퍼를 따라가지 않았습니다"
  긴급 알람은 오지 않습니다.
- 실거래 포지션이 자기 손절이나 계단으로 닫힌 뒤에는 **그다음에 새로 나오는 페이퍼 진입부터** 따라갑니다. 페이퍼가 아직 들고
  있는 그 포지션(따라가지 않기로 한 것)에 늦게 올라타지 않습니다. 새 진입도 예전 규칙대로 3분이 지나면 따라가지 않습니다.
- 페이퍼가 들고 있던 포지션을 **따라 닫는 이유**(빠른 청산·멈춤·수동)로 닫고 곧바로 새로 들어갔다면, 실거래도 따라 닫은 것이라
  그 새 진입은 예전처럼 따라갑니다. 페이퍼 청산 이유를 아직 못 읽는 30초 동안에는 새 진입을 포기하지도 따라가지도 않고 기다립니다.

## 결과로 달라지는 것 (솔직하게)

- **실거래와 페이퍼가 다른 때에 닫힐 수 있습니다.** 실거래가 먼저 잠그고 먼저 닫히기도 하고, 페이퍼가 닫은 뒤에도 실거래가
  자기 손절·계단으로 더 들고 있기도 합니다.
- 체결이 페이퍼보다 나쁘면 실거래는 더 늦게 잠기거나 못 잠급니다. 그래서 페이퍼가 이긴 거래를 실거래가 질 수 있습니다.
  체결이 좋으면 반대로 더 일찍 잠깁니다.
- 페이퍼의 빠른 청산은 페이퍼가 자기 첫 잠금을 지나면(또는 이미 닫으면) 더 나오지 않습니다. 그때 아직 자기 잠금이 없는
  실거래는 빠른 손절 없이 자기 손절과 계단만으로 갑니다.
- 실거래가 페이퍼보다 오래 들고 있는 동안 페이퍼가 새로 들어간 거래는 실거래가 타지 않습니다. 그래서 실거래 거래 수가 페이퍼보다
  적을 수 있고, 그 거래가 이겼다면 실거래는 그만큼 놓칩니다(졌다면 피함). 놓친 신호 목록에서 그 결과를 볼 수 있습니다.
- **11/3 손절 비교는 그대로 페이퍼끼리 비교합니다**(−50% 페이퍼 대 −35% 페이퍼, 같은 신호·같은 비용 가정). 실거래끼리의
  비교에는 이제 거래소 기준 익절의 차이도 섞입니다.

## 텔레그램·점검·실거래 사이트에서 보이는 것

- 🔒 실행기마다 자기 첫 잠금 한 번: `🔒 바이비트 잠금 +10% (자기 체결가 기준) · 손절 0.07963`
- 페이퍼와 따로 닫힌 실거래: `✅ 바이비트 청산 (거래소 기준) · DOGE 롱 · 순ROE +…%` (페이퍼가 그때 어땠는지 함께, 조용히)
- 페이퍼 청산 메시지와 손실 카드에 실행기가 아직 들고 있으면 `아직 열림 · 거래소 기준 손절·계단으로 따로 닫혀요`.
- **알람이 아닌 것:** 페이퍼는 닫혔는데 실거래가 열려 있음, 실거래만 잠금, 닫힌 시각이 다름, 거래소 기준으로 따로 닫힌 거래의
  청산 가격 차이(미끄러짐으로 세지 않음), 그런 거래에서 "페이퍼가 이긴 거래를 실거래가 짐", 들고 있는 동안 따라가지 않은 페이퍼
  진입(위 결정 1: 진입 메시지에 `⏸ 자기 포지션(거래소 기준)을 들고 있어 따라가지 않음`, 못 탄 신호 목록에 같은 이유).
- **진입 가격 차이 (10/20 결정 2):** 실거래가 페이퍼보다 **나쁘게** 들어갔을 때(롱은 더 비싸게, 숏은 더 싸게) 10bps를 넘을 때만
  예전처럼 "실거래-페이퍼 차이" 알람과 손실 카드 경고(🚨)가 됩니다. **좋게** 들어간 것(롱은 더 싸게, 숏은 더 비싸게)은 알람이
  아닙니다. 손실 카드에 숫자와 함께 `진입이 페이퍼보다 유리`라고 조용히 보여 줍니다. 예: 10/20 DOGE 롱, 페이퍼 0.07937 · 바이비트
  0.07924(16bps 좋음)는 조용합니다. 같은 16bps를 반대로(페이퍼 0.07911 · 바이비트 0.07924) 나쁘게 들어갔으면 알람입니다.
- 아침 점검: `거래소 기준 익절(어제, 페이퍼와 따로 닫힌 실거래 · 알람 아님)` 묶음.
- 8093 포지션 카드: `거래소 기준` 표시, 자기 잠금(`잠금선 (거래소 기준 +10% 잠금)`), 다음 잠금 자리(자기 체결가 기준), 거래소에서
  닿은 최고 순ROE, 페이퍼가 이미 닫았으면 그 이유.

## 나중의 선택: 화면 ROE 기준 (`ladder_basis`)

- 지금 값은 `"ladder_basis": "net"`(순ROE, 위 설명 그대로)입니다. 바꾸지 않았습니다.
- `"gross"`로 바꾸면 거래소 앱 화면에 보이는 **수수료 전 ROE**로 계단을 판단합니다. 잠금 가격 = 체결가 × (1 + 잠금 ÷ 배수)
  (숏은 1 −), 비용 없음. 예: "화면 13%에서 12% 잠금, 그 뒤 5%마다"는 `"ladder": {"first_lock": 0.12, "trigger_gap": 0.01,
  "step": 0.05}`.
- 그때 check-config가 첫 잠금이 수수료 뒤에 남기는 순ROE를 코인별로 보여 줍니다(잠금 − 배수 × 왕복 비용). 예: 바이비트 화면 +12%
  → BTC 40배 +6.0%, 알트 30배 +7.5%. MEXC 화면 +12% → BTC +4.0%, 알트 +6.0%.
- 정하는 것은 `research/live15/ladders.py` 결과를 본 뒤입니다. 바꿀 때도 아래 2)~4)처럼 설정만 바꾸고 포지션이 없을 때 다시 켭니다.

## 서버에서 하는 순서

명령은 서버에서 순서대로 한 번씩 합니다. 키 파일(`/etc/paperbot/executor.env`)은 열거나 보여 주지 않습니다.

**1) 코드 받기**

```bash
cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh
```

- install.sh는 실행기를 다시 켜지 않습니다. 새 설정 줄은 **이 다음에** 넣습니다(예전 코드는 모르는 설정 줄이 있으면 켜지지 않음).

**2) 두 실행기 설정에 새 줄 넣기 (다른 값은 그대로)**

각 실행기가 따라가는 페이퍼 봇 설정(`/etc/paperbot/combo.json` 또는 `combo-mexc.json`, `paper_db`로 찾음)의 계단이 규칙봇 15
계단과 같을 때만 씁니다. 다르면 아무것도 쓰지 않고 "다름"을 보여 줍니다.

```bash
sudo python3 - <<'EOF'
import json
LADDER = {"first_lock": 0.10, "trigger_gap": 0.01, "step": 0.05, "next_trigger": 0.15, "next_gap": 0.03}
COSTS = {"bybit": {"taker_fee": 0.00044, "slippage": 0.0002}, "mexc": {"taker_fee": 0.0008, "slippage": 0.0002}}
combos = {}
for c in ("/etc/paperbot/combo.json", "/etc/paperbot/combo-mexc.json"):
    try:
        j = json.load(open(c, encoding="utf-8"))
        combos[j.get("db")] = (c, j.get("ladder"))
    except OSError:
        pass
for p in ("/etc/paperbot/executor.json", "/etc/paperbot/executor-mexc.json"):
    d = json.load(open(p, encoding="utf-8"))
    src, lad = combos.get(d.get("paper_db"), (None, None))
    if lad != LADDER:
        print(p, "따라가는 페이퍼 설정", src, "의 계단이 다릅니다:", lad, "-> 쓰지 않음")
        continue
    print(p, "ladder_from:", d.get("ladder_from"), "-> own / ladder_basis:", d.get("ladder_basis"), "-> net / 계단: ", src, "와 같음")
    d.update(ladder_from="own", ladder=LADDER, ladder_basis="net", net_costs=COSTS)
    open(p, "w", encoding="utf-8").write(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
EOF
```

**3) check-config 두 번**

```bash
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor.json
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor-mexc.json
```

- 확인할 줄:
  - `익절(계단 잠금): 거래소 기준 - 이 실행기의 체결가, 이 거래소의 1분봉 고가·저가, 이 거래소의 비용으로 판단 (paper의 잠금은 따르지 않음)`
  - `계단: 순ROE 11%에서 10% 잠금, 15%에서 12%, 20%에서 17%, 그 뒤 5%마다 (닿은 순ROE - 3%)`
  - `기준(ladder_basis "net"): 순ROE - 수수료·슬리피지 왕복을 뺀 ROE (페이퍼와 같은 정의)`
  - 바이비트: `순ROE 비용: 바이비트 테이커 0.044% + 슬리피지 0.02% (한쪽), 왕복 0.128%, 펀딩은 계산에 넣지 않음`
  - MEXC: `순ROE 비용: MEXC 테이커 0.08% + 슬리피지 0.02% (한쪽), 왕복 0.2%, 펀딩은 계산에 넣지 않음`
  - `paper 새 진입: 실거래가 아직 자기 포지션을 들고 있으면 따라가지 않음(놓친 신호로 기록, 들고 있던 포지션은 닫지 않음). 닫힌 뒤의 새 진입부터 따름`
  - 끝 세 줄은 예전과 같습니다: `멈춤: …`, `신호등: 꺼짐 (paper의 모든 진입을 따라감)`, **`준비됨`**.

**4) 포지션이 없을 때만, 실행기마다 다시 켜기**

```bash
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-bybit-live.db
sudo systemctl restart paperbot-executor
```

- 첫 줄의 status에 **`포지션: null`일 때만** 둘째 줄을 합니다. 포지션이 있으면 그 포지션이 끝난 뒤에 다시 status부터 합니다.

```bash
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-mexc-live.db
sudo systemctl restart paperbot-executor-mexc
```

- 마찬가지로 **`포지션: null`일 때만** 다시 켭니다.
- 다시 켠 뒤 status 기록에 `시작: paper 계좌 COMBO@mix 따라 하기 (…), …, 익절 거래소 기준(순ROE 11%에서 10% 잠금, …; 비용 바이비트
  테이커 0.044% + …)`이 보이면 됩니다.
- 다시 켜기 전까지 그 실행기는 예전처럼 페이퍼의 잠금을 따라갑니다. 한쪽만 먼저 켜도 괜찮습니다.

## 되돌리기 (예전처럼 페이퍼 잠금 따라가기)

포지션이 없을 때만:

```bash
sudo python3 - <<'EOF'
import json
for p in ("/etc/paperbot/executor.json", "/etc/paperbot/executor-mexc.json"):
    d = json.load(open(p, encoding="utf-8"))
    print(p, "ladder_from:", d.get("ladder_from"), "-> paper")
    d["ladder_from"] = "paper"
    open(p, "w", encoding="utf-8").write(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
EOF
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor.json
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor-mexc.json
```

- check-config 첫 줄이 `익절(계단 잠금): 페이퍼 기준 - paper의 잠금을 따라 손절을 옮김 (stop_from "ratio": 체결가 비율)`이면 됩니다.
- 그다음 4)처럼 실행기마다 `포지션: null`을 보고 다시 켭니다. `ladder`·`net_costs`·`ladder_basis` 줄은 남겨 둬도 됩니다
  ("paper"에서는 쓰지 않음).
- 코드까지 예전으로 돌릴 때는 **먼저** 설정 줄 네 개(`ladder_from`, `ladder`, `ladder_basis`, `net_costs`)를 지워야 합니다.
  예전 코드는 모르는 설정 줄이 있으면 켜지지 않습니다. 지우는 명령(포지션이 없을 때만, 그다음 코드를 돌리고 4)처럼 다시 켜기):

```bash
sudo python3 - <<'EOF'
import json
for p in ("/etc/paperbot/executor.json", "/etc/paperbot/executor-mexc.json"):
    d = json.load(open(p, encoding="utf-8"))
    gone = [k for k in ("ladder_from", "ladder", "ladder_basis", "net_costs") if d.pop(k, None) is not None]
    print(p, "지운 줄:", gone)
    open(p, "w", encoding="utf-8").write(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
EOF
```

## 확인한 시험

`tests/test_executor_own_ladder.py` (DOGE 숫자, 롱·숏, 계단 여러 단, 다시 켜기, 페이퍼가 잠금으로 닫은 뒤 자기 손절로 닫힘, 빠른
청산 전·후, 손절이 느슨해지지 않음, 손절 옮기기 실패와 다시 하기, 1분봉 못 읽음, 1분봉 응답이 비었거나 오래된 분뿐임, 화면 ROE
기준, 들고 있는 동안의 페이퍼 새 진입은 안 따라가고 시장가 청산도 없음 → 자기 손절로 닫힌 뒤 새 진입부터 따라감),
`tests/test_livecheck_own.py` (텔레그램 줄, 손실 카드, 알람 아님, 아침 점검, 못 탄 신호, 포지션 카드, 좋은 진입 차이는 조용하고 같은
크기의 나쁜 진입 차이는 알람, 따라가지 않은 진입은 긴급 알람 없이 놓친 신호로).
