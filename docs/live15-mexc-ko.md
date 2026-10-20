# MEXC는 손절 −35% 페이퍼 봇을 따라갑니다 (10/19 최종 결정)

**결정(10/19, "Mexc -35%로 가자"):** 바이비트는 규칙봇 15(손절 순ROE −50%)를, MEXC는 **손절만 순ROE −35%인 같은 봇**을 따라갑니다.
나머지 규칙(매매법 15개, 계단 익절, 빠른 청산, 추격 막기, 증거금 40%, 배수, 쉬는 시간)은 똑같습니다.

- **왜:** 11/3 검토 때 어느 손절에 돈을 더 넣을지 정하려는 **2주 비교 시험**입니다(−50% 바이비트 대 −35% MEXC). 두 봇을 다르게
  돌리면 한쪽만 잘 돼도 좋다는 생각(10/19 "두 봇을 다른 느낌으로 돌리면 한 개만 성공해도 좋잖아")에서 나왔습니다. 계획 전체는
  `docs/live15-plan-ko.md`.
- **오늘(10/20 시작):** 두 실행기 모두 `docs/live15-start-ko.md` 순서대로 **−50%로 시작**합니다. 그 순서는 지금 서버에 올라간 코드로
  그대로 됩니다.
- **그다음:** 이 문서가 들어간 코드가 서버에 올라오고 MEXC가 `포지션: null`일 때, 아래 순서로 MEXC만 −35% 봇으로 옮깁니다.
  바이비트는 손대지 않습니다.
- 두 실행기가 같은 페이퍼를 따라가는 동안(옮기기 전)은 실거래 사이트·아침 점검·텔레그램이 모두 예전과 똑같습니다. 옮긴 뒤에는
  "어느 실행기가 어느 페이퍼를 따라가는지"가 화면과 메시지에 함께 나옵니다.

## 숫자 (솔직하게)

규칙봇의 지난 2주 실제 진입을 손절만 바꿔 다시 계산한 결과입니다(`research/live15/stops.py`, 서버에서 돌림).

| 경우 | 진입 | 결과 | 계좌 | 최대 낙폭 |
|---|---|---|---|---|
| 두 실행기 모두 −50% | | | ×2.57 | 23% |
| −35% 하나만 | 74번 | 61승 11패, 빠른 청산 2번 · 승률 82% (본전 약 74%) | ×2.08 | 23% |
| 바이비트 −50% + MEXC −35% (이번 결정, 반씩) | 같은 진입 54번 중 4번만 결과가 갈림 | | ×2.32 | 18% |

- **이 2주는 15개를 고를 때 쓴 바로 그 기간이고, 15개는 −50% 손절로 골랐습니다.** 그래서 이 기간에서는 −50%가 가장 좋아 보이는 것이 당연합니다. 앞으로도 그럴지는 모릅니다. 그것을 실제로 보려는 것이 이번 2주 시험입니다.
- −35%는 손절 한 번이 덜 아프고(계좌 약 −10.5%, −50%는 약 −15%), 대신 −35%와 −50% 사이까지 갔다가 돌아오는 거래를 손절로 끝냅니다. 본전 승률(단순 계산, 이긴 거래 평균 +10~12.5%)은 −35%가 약 74~78%, −50%가 약 80~83%입니다.
- 두 봇은 같은 신호로 같은 때 들어갑니다. 결과가 갈리는 것은 값이 −35%와 −50% 손절 사이까지 갔다가 돌아오는 거래입니다. 한쪽이 먼저 손절되면 그 봇은 비어 있어서 다른 진입을 혼자 할 수 있습니다(한 번에 포지션 하나).

### 거래소 화면에서 보이는 손절

손절은 수수료·슬리피지까지 넣은 **순ROE**로 정합니다(왕복 비용 0.14% = 테이커 0.05% + 슬리피지 0.02%, 양쪽). 거래소 앱의 ROE는 비용을 빼기 전 숫자라 더 작게 보입니다.

| | 진입가에서 손절까지 | 거래소 앱에 보이는 ROE | 손절 한 번 = 계좌의 (증거금 40%) |
|---|---|---|---|
| MEXC −35% · BTC 40배 | 0.735% (check-config에는 0.73%) | 약 −29% | 약 −14% |
| MEXC −35% · 알트 30배 | 1.03% | 약 −31% | 약 −14% |
| 바이비트 −50% · BTC 40배 | 1.11% | 약 −44% | 약 −20% |
| 바이비트 −50% · 알트 30배 | 1.53% | 약 −46% | 약 −20% |

## 무엇이 바뀌나

- 서버에 `/etc/paperbot/combo-mexc.json`(두 번째 페이퍼 봇 설정)이 생깁니다. 규칙봇 15 설정과 다른 곳은 세 줄뿐입니다: `"stop"`(순ROE −35%), `"db"`(`/var/lib/paperbot/combo/live15-mexc.db`, 자기 기록 파일), `"name"`(`규칙봇 15 MEXC −35%`).
- 서비스 `paperbot-combo-mexc`(페이퍼 봇, 주문 없음)가 켜집니다. `paperbot-combo`와 같은 사용자·보호 설정입니다. `install.sh`는 설치만 하고 켜지 않습니다. 예전 `paperbot-combo2`는 건드리지 않습니다.
- MEXC 실행기 설정 `/etc/paperbot/executor-mexc.json`에서 **`paper_db` 한 줄만** 바뀝니다. 계좌 이름(`COMBO@mix`), 금액, 한도, 키는 그대로입니다. 바이비트 설정(`/etc/paperbot/executor.json`)은 그대로입니다. (저장소의 `deploy/executor.live-mexc.json`도 같은 값입니다.)
- 텔레그램: 두 번째 봇은 시작·오류 알림만 보냅니다(날것 진입·청산 줄은 끔). 실거래 감시의 🟢 메시지에 두 페이퍼 줄이 함께 나오고, 두 번째 봇의 손실 카드에는 "페이퍼 −35%"와 MEXC만 나옵니다. 미리 보기: `cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.livecheck preview --two` (보내지 않고 화면에만 찍음).

## 실행기가 페이퍼를 바꿀 때 안전한가 (확인한 것)

- 실행기 기록 파일(`/var/lib/paperbot/exec/executor-mexc-live.db`)은 **그대로 씁니다.** 이 파일은 모드·계좌 이름·거래소에만 묶여 있고 페이퍼 DB에는 묶여 있지 않습니다. 두 페이퍼 봇 모두 계좌 이름이 `COMBO@mix`라 그대로 켜집니다. 지난 거래 기록도 이어집니다.
- 켜질 때 새 페이퍼 봇이 **이미 들고 있는 포지션은 따라가지 않습니다** (3분이 지난 진입은 "늦어서 건너뜀" 기록을 남기고, 다음 진입부터 따라감). 켜기 3분 안에 생긴 진입은 따라갑니다(평소 재시작과 같음).
- 예전 페이퍼(−50%) 봇의 거래는 더 이상 보지 않습니다. 지난 거래의 키는 진입 시각이 들어 있어 새 봇의 다음 진입과 겹치지 않습니다.
- **MEXC에 포지션이 있을 때 바꾸면 안 됩니다.** 새 페이퍼 봇에 같은 포지션이 없으면 실행기는 켜지자마자 그 포지션을 닫습니다. 그래서 4)는 MEXC를 끈 뒤 `포지션: null`을 확인하고 합니다.
- 새 봇이 아직 기록을 하나도 쓰지 않았으면 실행기는 "paper 계좌를 읽을 수 없습니다"(긴급)를 남기고 진입하지 않습니다. 그래서 **페이퍼 봇을 먼저 켜고**(3), 기록이 생긴 뒤에 실행기를 다시 켭니다(4).
- 실행기 코드에서 바뀐 것은 시작 기록 한 가지입니다: 시작할 때 "어느 페이퍼 DB를 따라가는지"를 기록에 남깁니다(`시작: paper 계좌 COMBO@mix 따라 하기 (페이퍼 DB …)`). 주문 쪽은 바뀌지 않았습니다. 대시보드와 점검은 이 기록으로 MEXC의 거래를 그때 따라간 페이퍼와만 비교합니다(바꾸기 전 거래는 −50% 페이퍼와, 바꾼 뒤 거래는 −35% 페이퍼와).
- 크기: 실거래 수량은 **따라가는 페이퍼의 수량 × 0.1** 입니다. 새 봇은 지갑 $1,000으로 시작하므로 옮긴 뒤 MEXC 크기는 "잔고 $100 계좌의 증거금 30%"에 맞습니다. MEXC 잔고가 그때 $100에서 많이 멀면 2)의 "시작 지갑" 줄을 보세요.
- 이 모든 것을 확인하는 시험: `tests/test_executor_paper_switch.py`, `tests/test_livecheck_two_papers.py`, `tests/test_combo_live15_mexc.py`.

## 옮기는 순서 (이 코드가 올라온 뒤, MEXC 포지션이 없을 때)

명령은 모두 서버에서, 순서대로 한 번씩 합니다. 키 파일은 열거나 보여 주지 않습니다. 1)~3)은 MEXC 실행기를 건드리지 않으므로 언제 해도 됩니다. 4)만 MEXC 포지션이 없을 때 합니다.

**1) 코드 받기 (이 문서가 들어간 코드가 이미 있으면 건너뜀)**

```bash
cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh
```

- 끝에 `MEXC용 -35% 페이퍼 봇(paperbot-combo-mexc) 설치만 했습니다` 줄이 나옵니다. 실행기는 install.sh가 다시 켜지 않습니다.

**2) 두 번째 페이퍼 봇 설정 넣고 확인**

```bash
sudo install -o root -g paperbot -m 640 /opt/crypto-bot-research/deploy/combo.live15-mexc.json /etc/paperbot/combo-mexc.json
cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo check-config --config /etc/paperbot/combo-mexc.json
```

- 확인할 줄:
  - `- 따라 읽는 규칙봇 DB: /var/lib/paperbot/paper3.db / 자기 DB: /var/lib/paperbot/combo/live15-mexc.db`
  - `- 손절: 순ROE -35%(수수료·슬리피지 포함: 40배 가격 0.73%, 30배 가격 1.03%) / 계단 익절: 순ROE 11%에서 10% 잠금, 15%에서 12%, 20%에서 17%, …`
  - 매매법 1~15번, 마지막 줄 **`준비됨`**
- 시작 지갑(필요할 때만): MEXC 잔고(실거래 사이트 관제 또는 MEXC 앱)가 $90~$110이면 그대로 둡니다. 그 밖이면, 3)을 하기 **전에** 시작 지갑을 "MEXC 잔고 × 10"으로 맞춥니다(아래 `130`을 그 잔고로 바꿔서). 그래야 MEXC도 잔고의 40%로 들어갑니다. 봇이 한 번 켜진 뒤에는 이 값이 쓰이지 않습니다.

```bash
sudo python3 - <<'EOF'
import json
WALLET = 130          # MEXC 잔고(달러)
p = "/etc/paperbot/combo-mexc.json"
d = json.load(open(p, encoding="utf-8"))
print(p, "initial_equity:", d.get("initial_equity"), "->", round(WALLET * 10))
d["initial_equity"] = round(WALLET * 10)
open(p, "w", encoding="utf-8").write(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
EOF
```

**3) 두 번째 페이퍼 봇 켜고 도는지 확인**

```bash
sudo systemctl enable --now paperbot-combo-mexc
systemctl is-active paperbot-combo-mexc
sudo journalctl -u paperbot-combo-mexc -n 20 --no-pager
```

- `active`가 나와야 합니다. 텔레그램에 `[합친 봇 페이퍼 규칙봇 15 MEXC −35%] 시작: 매매법 15개, … 손절 순ROE -35%(…) …` 가 옵니다.
- 1~2분 뒤 기록이 생겼는지 봅니다:

```bash
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.combo status --db /var/lib/paperbot/combo/live15-mexc.db
```

- `마지막 1분봉: (지금 시각에 가까운 시각) KST` 와 `COMBO@mix: 지갑 $1,000.00, 거래 0번 …`(2)에서 바꿨으면 그 금액)이 나오면 됩니다. "아직 계좌 상태가 없습니다"면 1분 더 기다렸다 다시 봅니다.
- 이때부터 실거래 사이트(8093) 규칙 점검에 "두 페이퍼 비교"가 나옵니다. MEXC는 아직 −50%를 따라갑니다.

**4) MEXC 포지션이 없을 때: MEXC 실행기만 끄고, `paper_db`를 바꾸고, 다시 켜기**

```bash
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-mexc-live.db
sudo systemctl stop paperbot-executor-mexc
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-mexc-live.db
```

- 첫 status에 `포지션: null`일 때만 끕니다. 끈 뒤 둘째 status도 `포지션: null`이어야 합니다(끄는 사이에 들어갔으면 `sudo systemctl start paperbot-executor-mexc`로 다시 켜고, 그 포지션이 끝난 뒤 4)를 처음부터). MEXC 앱에서도 열린 포지션·남은 주문이 없는지 봅니다.

```bash
sudo python3 - <<'EOF'
import json
p = "/etc/paperbot/executor-mexc.json"
d = json.load(open(p, encoding="utf-8"))
print(p, "paper_db:", d.get("paper_db"), "-> /var/lib/paperbot/combo/live15-mexc.db")
d["paper_db"] = "/var/lib/paperbot/combo/live15-mexc.db"
open(p, "w", encoding="utf-8").write(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
EOF
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor-mexc.json
```

- 첫 줄에 `paper_db: /var/lib/paperbot/combo/live-ac.db -> /var/lib/paperbot/combo/live15-mexc.db` 가 나옵니다(이 파일에는 키가 없습니다).
- check-config의 끝 세 줄: `멈춤: 연패·낙폭으로는 멈추지 않음 (비상 정지 파일 /var/lib/paperbot/STOP만)`, `신호등: 꺼짐 (paper의 모든 진입을 따라감)`, **`준비됨`**.
- 바이비트 설정(`/etc/paperbot/executor.json`)은 건드리지 않습니다.

```bash
sudo systemctl start paperbot-executor-mexc
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-mexc-live.db
```

- **확인 줄:** status 기록에 `시작: paper 계좌 COMBO@mix 따라 하기 (페이퍼 DB /var/lib/paperbot/combo/live15-mexc.db), mainnet, …` 이 있어야 합니다. `포지션: null`.
  `(페이퍼 DB /var/lib/paperbot/combo/live-ac.db)`가 보이면 바뀌지 않은 것이니 4)의 설정 바꾸기를 다시 봅니다.
- 텔레그램(실거래 감시)에 `▶️ MEXC 실행기 켜짐 · 잔고 $… · 따라가는 페이퍼: 페이퍼 −35%` 가 옵니다.
- `paper 진입이 n초 전이라 따라 하지 않습니다` 기록이 하나 있으면, 새 봇이 켜기 전에 이미 들고 있던 포지션입니다. 정상입니다(다음 진입부터 따라감).
- 바이비트 실행기(`paperbot-executor`)는 다시 켜지 않습니다.

## 옮긴 뒤 실거래 사이트(8093)에서 볼 것

- **관제**: MEXC 칸 아래 `따라감 · 페이퍼 −35% · 규칙봇 15 MEXC −35%`, 바이비트 칸은 `페이퍼 −50%`.
- **요약 · 포지션**: 페이퍼가 둘(`페이퍼 −50% (바이비트가 따라감)`, `페이퍼 −35% (MEXC가 따라감)`)로 보이고, MEXC 포지션 카드의 손절·계단은 두 번째 봇 기준입니다.
- **거래**: 페이퍼 표가 둘입니다. 다른 페이퍼를 따라간 실행기 칸에는 "이때 MEXC는 페이퍼 −35%를 따라갔어요"처럼 나옵니다. 옮기기 전 MEXC 거래는 그때 따라간 −50% 페이퍼와 비교됩니다.
- **목표**: 맨 아래 "손절 비교 (11/3 검토용)" — −50%(바이비트)와 −35%(MEXC)의 거래 수·승률·순ROE 합·잔고 변화·최대 낙폭을 나란히 보여 줍니다(두 번째 봇 시작부터). 계좌마다 필요한 승률은 자기 손절로 계산합니다.
- **규칙 점검**: "두 페이퍼 비교" — 같은 숫자와 "같은 진입 n번 중 결과가 갈린 거래 m번".
- **봇 상태**: `페이퍼 −35% 봇 심장 박동`, `… 마지막 1분` 줄이 따로 있습니다.
- **위험**: 계좌마다 자기 페이퍼의 손절로 계산합니다(MEXC 손절 한 번 ≈ 계좌 −10.5%).
- 아침 점검 텔레그램의 성적표에 `- 페이퍼 −50%(바이비트가 따라감)`, `- 페이퍼 −35%(MEXC가 따라감)` 두 줄이 나옵니다.

## 되돌리기 (MEXC도 다시 −50%로)

MEXC가 `포지션: null`일 때만:

```bash
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-mexc-live.db
sudo systemctl stop paperbot-executor-mexc
sudo python3 - <<'EOF'
import json
p = "/etc/paperbot/executor-mexc.json"
d = json.load(open(p, encoding="utf-8"))
print(p, "paper_db:", d.get("paper_db"), "-> /var/lib/paperbot/combo/live-ac.db")
d["paper_db"] = "/var/lib/paperbot/combo/live-ac.db"
open(p, "w", encoding="utf-8").write(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
EOF
cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor check-config --config /etc/paperbot/executor-mexc.json
sudo systemctl start paperbot-executor-mexc
sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor status --db /var/lib/paperbot/exec/executor-mexc-live.db
```

- 마지막 status 기록에 `(페이퍼 DB /var/lib/paperbot/combo/live-ac.db)`가 보이면 됩니다.
- 두 번째 페이퍼 봇은 그대로 두어 비교용으로 계속 볼 수 있습니다. 끄려면 `sudo systemctl disable --now paperbot-combo-mexc` (기록 파일은 남습니다).

## 손절 값을 바꾸지 않습니다 (11/3까지)

- 2주 시험 동안 두 손절(−50%, −35%)은 그대로입니다. 넓히거나 좁히는 점검도 두지 않았습니다. 고장·위험 때의 비상 정지(`sudo touch /var/lib/paperbot/STOP`)만 예외입니다.
- 11/3 뒤에 값을 바꾸기로 하면: `/etc/paperbot/combo-mexc.json`의 `"stop"` 안 `"roe"`만 바꾸고 check-config를 본 뒤, **그 봇과 MEXC 둘 다 포지션이 없을 때** `sudo systemctl restart paperbot-combo-mexc` 만 합니다. 페이퍼 봇은 손절을 **진입할 때만** 정합니다. 다시 켤 때 들고 있던 포지션은 원래 손절을 그대로 쓰고(계단 익절만 올림), 그다음 진입부터 새 값을 씁니다(확인: `tests/test_combo_live15_mexc.py`).
