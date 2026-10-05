# paper v4 재시작 안내서 (오늘 밤: 스테이징 → 리셋 연습 → 진짜 리셋 → 확인)

두 분이 명령을 하나씩 붙여 넣으면서 **각 단계가 제대로 됐는지 눈으로 확인**할 수 있게 썼습니다. 서버 설치·키·대시보드·백업·고장 대응은
그대로 `docs/server-setup-v3.md`를 씁니다. 숫자나 재시작 절차가 다르면 이 문서가 이깁니다.

- 규칙: `docs/paper-v4-rules.md`, 판정 방법: `docs/paper-v4-verdict.md`, 레버리지 규칙 B 판정: `docs/levrule-eval-v4.md`.
- 서버 작업은 **저장소 주인 한 분**이 합니다. 다른 한 분은 텔레그램·대시보드를 봅니다.
- 시각은 모두 **한국 시간(KST)** 입니다. 서버 시계는 UTC(9시간 느림)입니다.
- 회색 상자는 **통째로** 붙여 넣습니다. `#` 줄은 설명이라 붙여 넣어도 아무 일도 하지 않습니다. 줄 끝 `\`는 "다음 줄과 이어짐"입니다.
- 키·토큰은 화면에 띄우지 않습니다. 이 문서의 어떤 명령도 키 값을 출력하지 않습니다.

## v4가 무엇인가 (한 번만 읽기)

v3 실행은 30일 판정 없이 **보관**하고(지우지 않음), 새 실행을 처음부터 시작합니다. 새 실행의 $5,000 계좌는 **331개**입니다.

| 그룹 | 무엇 | 봉 | 계좌 | 판정 |
|---|---|---|---|---|
| 매매법 | 잠긴 매매법 36개 (v3와 같음) | 15분·30분·1시간·4시간 | 36 × 4 | 15분·30분·1시간 (4시간은 관찰) |
| 딥시크 | DeepSeek-200 정의 44개 | 39개는 4개 봉, 세션 정의 5개는 15분·30분·1시간 | 171 | 15분·30분·1시간 (4시간은 관찰) |
| 릴스 5분 단타 | REEL_H1 (볼린저 20·2 + 200선, 롱만, 자기 청산 규칙) | 5분 | 1 | 5분 |
| 동전 | RANDOM_1~3 (비교용) | 5분·15분·30분·1시간·4시간 | 15 | 판정 안 함 |

- 매매법 36개는 5분봉에 없습니다. 5분봉에는 **릴스 1개와 그 비교용 동전 3개(롱만, 릴스와 같은 청산)** 만 있습니다.
- 텔레그램 거래 알림: 매매법·릴스·추가 계좌는 거래마다, 딥시크·동전은 개수만. 강제청산은 모든 그룹이 알림.
- 딥시크 손익은 대시보드의 딥시크 칸에서만 보입니다(거래마다 텔레그램 없음).
- 에이전트 회의(`paperbot-agents.timer`)는 리셋 뒤 **지금처럼 다시 켜집니다**. 개발자가 "에이전트는 꺼 두세요"라고 했을 때만 리셋 명령 끝에
  `--agents-off`를 붙입니다(두 분 결정 D15). 꺼 두면 아침·순위·저녁·주간·급변 알림이 오지 않습니다.
- 옵시디언 내보내기·딥시크 200 그림자 시험·딥시크 밤 재계산 점검 타이머는 리셋 뒤 **꺼진 채** 두었다가, 확인(4단계)을 마치고 두 분이
  켭니다(5단계).
- 날짜는 어디에도 미리 적지 않았습니다. 첫 30일 판정일, 관찰 기간 끝(21일)은 **새 시작 시각에서 저절로 계산**되고 리셋 스크립트가 보여 줍니다.

## 오늘 밤 순서 (한눈에)

| 시각(KST) | 단계 | 걸리는 시간 |
|---|---|---|
| 23:00 | 개발자에게서 "통합 점검 통과, 커밋 ○○○○○○○" 받기 | — |
| 23:15 | **1. 접속하고 코드 받기** | 5분 |
| 23:32~23:35 | **2. 스테이징 시작** (v4 봇을 따로, 시험 DB로, 텔레그램 없이) → 01:00 4시간봉 경계까지 약 90분 지켜봄 | 90분 |
| 01:05~01:10 | 2단계 측정과 판단 (멈춤 기준) | 10분 |
| 01:10~01:35 | **3. 스테이징 끄기 → 진짜 리셋** (리셋 시작은 01:32~01:35 또는 01:47~01:50) | 10~60분 |
| 리셋 뒤 | **4. 시작 뒤 확인** (launchcheck, 시작 알림, 첫 5분봉·15분봉) | 40분 |
| 4단계가 깨끗하면 | **5. 타이머 켜기** (그림자 시험·옵시디언·딥시크 밤 점검) | 2분 |
| 문제가 보이면 | **6. 되돌리기** | — |

- **안전한 분(分)**: 봇을 멈추거나 켜는 명령(2-4, 3-6)은 15분봉 경계(00·15·30·45분) **2~5분 뒤**에 붙여 넣습니다. 예: 23:32~23:35,
  01:32~01:35, 01:47~01:50. 경계 바로 앞뒤에는 봇이 신호를 계산하고 있습니다.
- 01:00 경계를 놓쳤으면 같은 순서를 05:00 경계로 미룹니다(스테이징 03:32 시작, 05:05 측정, 리셋 05:32쯤). 08:30~09:40에는 리셋 스크립트가
  거절합니다(밤 점검·판정 시간).
- **중간에 하나라도 "멈춤 기준"(2-12)에 걸리면 진짜 리셋을 하지 않습니다.** v3 봇은 그동안 그대로 돌고 있으므로 잃는 것이 없습니다.
  화면을 개발자에게 보내고 다음 날 다시 합니다.
- 한 단계에 명령은 **하나**입니다. 상자를 통째로 붙여 넣고, 그 아래 "보여야 할 것"과 화면을 비교한 뒤 다음 단계로 갑니다.

---

## 1. 접속하고 코드 받기 (23:15)

1-1. 서버에 접속합니다(평소 쓰는 터미널에서):

```bash
ssh root@<서버 IP>
```

보여야 할 것: `root@...:~#` 로 끝나는 줄(서버의 명령 줄).

1-2. 저장소 폴더로 갑니다:

```bash
cd /root/crypto-bot-research
```

보여야 할 것: 아무 출력 없음.

1-3. 새 코드를 받습니다:

```bash
git pull
```

보여야 할 것: `Fast-forward` 와 바뀐 파일 목록(또는 `Already up to date.`). `CONFLICT`나 `error`가 나오면 멈추고 개발자에게.

1-4. 받은 커밋을 확인합니다:

```bash
git log -1 --format='%h %s'
```

보여야 할 것: 맨 앞 7자리가 개발자가 준 커밋 번호와 **같음**.

1-5. 수정된 파일이 없는지 봅니다:

```bash
git status --short --untracked-files=no
```

보여야 할 것: **아무 출력 없음**. (뭔가 나오면 리셋 스크립트가 거절합니다. 멈추고 개발자에게.)

**설치(`sudo bash deploy/install.sh`)는 따로 하지 않습니다.** 설치는 3단계의 리셋 스크립트가 v3 봇을 멈춘 뒤에 합니다(리셋 3단계,
`PAPERBOT_RESETTING=1`). 지금 설치하면 v3 봇이 v4 코드로 다시 켜지려다 "이 DB는 paper-v3" 이유로 거절되어 멈춥니다. `git pull`만으로는
돌고 있는 봇이 바뀌지 않습니다.

## 2. 스테이징 (23:32~01:10, 약 90분, 01:00 4시간봉 경계 포함)

v4 봇을 **따로** 한 번 돌려 봅니다. 시험 DB(`/var/lib/paperbot/staging/paper4.db`)에만 쓰고, 텔레그램과 healthchecks.io에는 아무것도
보내지 않습니다(설정 파일에서 그 줄을 빼고, `--no-telegram`으로 알림을 화면에만 찍음). 추가 계좌도 켜지 않습니다(`--no-extras`).
v3 봇은 그대로 돕니다.

2-1. 전에 만든 시험 폴더가 있으면 옆으로 옮깁니다(없으면 아무 일도 안 함):

```bash
[ -e /var/lib/paperbot/staging ] && sudo mv /var/lib/paperbot/staging /var/lib/paperbot/staging-old-$(date +%H%M); true
```

보여야 할 것: 아무 출력 없음.

2-2. 시험 폴더를 만듭니다:

```bash
sudo install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/staging
```

보여야 할 것: 아무 출력 없음.

2-3. 받은 코드를 시험 폴더로 복사합니다:

```bash
sudo git clone -q /root/crypto-bot-research /var/lib/paperbot/staging/repo && sudo chown -R paperbot:paperbot /var/lib/paperbot/staging/repo
```

보여야 할 것: 아무 출력 없음.

2-4. 복사본의 커밋을 확인합니다:

```bash
sudo -u paperbot git -C /var/lib/paperbot/staging/repo log -1 --format='%h %s'
```

보여야 할 것: 1-4와 **같은** 7자리.

2-5. 시험용 설정 파일 (바이낸스 **읽기 전용** 키 두 줄만 복사; 텔레그램·healthchecks 줄은 넣지 않음):

```bash
sudo sh -c "grep -E '^BINANCE_API_(KEY|SECRET)=' /etc/paperbot/live.env > /var/lib/paperbot/staging/live.env && chmod 600 /var/lib/paperbot/staging/live.env && grep -c '' /var/lib/paperbot/staging/live.env && grep -c -E 'TELEGRAM|DEADMAN' /var/lib/paperbot/staging/live.env"
```

보여야 할 것: `2` 그리고 `0` 두 줄(키 값은 화면에 나오지 않습니다). 둘째 숫자가 0이 아니면 멈추고 개발자에게.

2-6. **시험 봇 켜기** (15분 경계 2~5분 뒤, 예: 23:32~23:35):

```bash
sudo systemd-run --unit=paper4-staging --collect --uid=paperbot --gid=paperbot -p Nice=5 -p MemoryMax=3G -p KillMode=mixed -p TimeoutStopSec=60 -p EnvironmentFile=/var/lib/paperbot/staging/live.env -p WorkingDirectory=/var/lib/paperbot/staging/repo /opt/paperbot/venv/bin/python -m paperbot.live3 run --db /var/lib/paperbot/staging/paper4.db --procs 4 --no-extras --no-telegram
```

보여야 할 것: `Running as unit: paper4-staging.service` 한 줄.

2-7. 지켜보기 (처음에는 400일치 5분봉을 받느라 5~15분 걸립니다. `Ctrl+C`로 빠져나와도 봇은 계속 돕니다):

```bash
sudo journalctl -u paper4-staging -f
```

보여야 할 것: 몇 분 뒤 `paper v4 started: 331 accounts (core 144, ds200 171, reel 1, flip 15), brackets: …, taker fee …%` 줄.
`Traceback`, `refused`, `account held`가 보이면 멈춤 기준 1·2입니다.

2-8. **스테이징 첫 점검** (`started: 331 accounts`가 나오고 5분 뒤):

```bash
cd /var/lib/paperbot/staging/repo && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.launchcheck --db /var/lib/paperbot/staging/paper4.db
```

보여야 할 것 (`[고칠 것]` 줄이 하나도 없고 마지막 줄이 `[OK]`):
- `[OK] 원래 계좌 331개 = 매매법 … · 딥시크 171 · 릴스 5분 단타 1 · 동전 15 (paper v4 규칙과 같음 …)`
- `[OK] 멈춘(동결된) 계좌 0개 (held = 0)`
- 시작 10분 안이면 1분봉 줄이 `[참고] 봇이 아직 준비 중`일 수 있습니다. 5분 뒤 다시 돌립니다.

2-9. **재시작 연습** (00:10쯤, 15분 경계 2~5분 뒤): 봇을 껐다 켜도 계좌가 그대로 이어지는지 봅니다. 먼저 끕니다:

```bash
sudo systemctl stop paper4-staging
```

보여야 할 것: 아무 출력 없음(최대 1분). 그다음 **2-6 상자를 그대로 한 번 더** 붙여 넣고, 2~5분 뒤 **2-8 상자를 다시** 돌립니다.
보여야 할 것: 2-8과 같은 `[OK]` 줄들, 계좌 줄에 `재시작 뒤 이어서 돌림`, `멈춘(동결된) 계좌 0개 (held = 0)`.

2-10. **리셋 연습** (00:20쯤): 진짜 DB의 **복사본**에 리셋 스크립트를 끝까지 돌려 봅니다. 진짜 서비스는 멈추지도, 바꾸지도, 옮기지도
않습니다. 개발자가 에이전트를 꺼 두라고 했으면 끝에 ` --agents-off`를 붙입니다(3-6과 똑같이).

```bash
cd /root/crypto-bot-research && sudo bash deploy/rehearse-reset.sh
```

보여야 할 것: 마지막 줄 `[OK] 연습 리셋 통과`. 그 위에 `[OK]` 줄들: 보관 폴더, 모든 방에 v4 재시작 메모, `paperbot-debate`·
`paperbot-obsidian.timer` 멈춤 목록, shadow200은 안 멈춤, 옵시디언·딥시크 밤 재계산 타이머는 다시 켜지 않음, 에이전트 회의 타이머
(`--agents-off`면 다시 켜지 않음, 아니면 다시 켬), `원래 계좌 331개`. 연습 폴더(`/var/lib/paperbot-rehearsal/<시각>`)는 나중에 지워도 됩니다.

2-11. **01:00 경계 측정** (01:05에): 01:00(KST)은 4시간봉·1시간봉·30분봉·15분봉·5분봉이 한꺼번에 닫히는 가장 바쁜 순간입니다.

```bash
sudo -u paperbot /opt/paperbot/venv/bin/python - /var/lib/paperbot/staging/paper4.db <<'PY'
import sqlite3, sys
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
def show(label, sql, args=()):
    d = sorted(r[0] for r in c.execute(sql, args) if r[0] is not None)
    if d:
        print(f"{label:>6} 신호 {len(d)}개 지연(초) 보통 {d[len(d)//2]/1000:.1f} 느린쪽 {d[int(.95*(len(d)-1))]/1000:.1f} 최대 {d[-1]/1000:.1f}")
for (tf,) in c.execute("SELECT DISTINCT timeframe FROM signal_log ORDER BY timeframe").fetchall():
    show(tf, "SELECT delay_ms FROM signal_log WHERE timeframe = ?", (tf,))
show("4h경계", "SELECT delay_ms FROM signal_log WHERE bar_close % (4 * 3600 * 1000) = 0")
print("상태별:", c.execute("SELECT status, COUNT(*) FROM signal_log GROUP BY status").fetchall())
print("5분봉 신호 이름:", [r[0] for r in c.execute("SELECT DISTINCT strategy FROM signal_log WHERE timeframe = '5m'")])
print("timeout 알림:", c.execute("SELECT COUNT(*) FROM alerts WHERE lower(text) LIKE '%timeout%' OR text LIKE '%timed out%'").fetchone()[0])
print("멈춘 계좌 알림:", c.execute("SELECT COUNT(*) FROM alerts WHERE text LIKE '%account held%'").fetchone()[0])
print("CRITICAL 알림:", c.execute("SELECT COUNT(*) FROM alerts WHERE level = 'CRITICAL'").fetchone()[0])
PY
```

보여야 할 것: `5분봉 신호 이름`에는 `REEL_H1`과 `RANDOM_1`~`RANDOM_3`만. `4h경계` 줄이 있음. 아래 숫자는 2-12의 기준과 비교합니다.

2-12. 오류 줄 세기 (스테이징 봇):

```bash
sudo journalctl -u paper4-staging --since "100 min ago" --no-pager | grep -c -E "Traceback|account held|engine code failed|refused| 429| 418"
```

보여야 할 것: `0`.

2-13. 오류 줄 세기 (지금 도는 v3 봇: 스테이징이 방해했는지):

```bash
sudo journalctl -u paperbot-live3 --since "100 min ago" --no-pager | grep -c -i -E "Traceback|timeout"
```

보여야 할 것: 평소와 같은 숫자(평소 0이면 `0`).

2-14. 메모리:

```bash
systemctl show paper4-staging -p MemoryCurrent -p MemoryPeak -p NRestarts
```

보여야 할 것: `NRestarts=0`, `MemoryPeak`(없으면 `MemoryCurrent`)가 3G(약 3,221,225,472)보다 한참 작음.

**멈춤 기준 (01:10 판단).** 하나라도 해당하면 3단계(진짜 리셋)를 하지 않습니다:

1. `started: 331 accounts`가 시작 30분이 지나도 안 나옴, 또는 2-14의 `NRestarts`가 0이 아님(혼자 꺼졌다 켜짐).
2. 2-8·2-9의 launchcheck에 `[고칠 것]`이 있음 (특히 계좌 수가 331이 아님, 멈춘 계좌가 1개 이상).
3. 2-11 숫자: `4h경계` 최대 지연 **60초 초과**, 또는 `5m` 느린쪽 지연 **30초 초과**, 또는 `timeout 알림`·`멈춘 계좌 알림`이 1 이상.
4. 2-12 숫자가 0이 아님.
5. 2-13 숫자가 평소보다 늘어남.
6. 메모리: 2-14의 값이 3G에 가까움.
7. `5분봉 신호 이름`에 `REEL_H1`·`RANDOM_k`가 아닌 이름이 있음.
8. 2-10 리셋 연습이 `[OK] 연습 리셋 통과`로 끝나지 않음.

## 3. 스테이징 끄기, 그리고 진짜 리셋 (01:10~01:35)

3-1. 스테이징을 끕니다(시험 DB는 개발자가 볼 수 있게 남겨 둡니다):

```bash
sudo systemctl stop paper4-staging
```

보여야 할 것: 아무 출력 없음(최대 1분).

3-2. 꺼졌는지 확인합니다:

```bash
systemctl is-active paper4-staging
```

보여야 할 것: `inactive` (또는 아무 줄 없음).

3-3. healthchecks.io 웹 화면 → 체크 → **Pause**(일시정지). 리셋 동안 봇이 몇 분~최대 1시간 꺼져 있어서 그대로 두면 "DOWN" 알림이 옵니다.
끝나면 봇의 다음 핑으로 저절로 다시 감시합니다. (명령 없음)

3-4. 주문 실행기가 꺼져 있는지 봅니다:

```bash
systemctl is-active paperbot-executor
```

보여야 할 것: `inactive`. (`active`면 `sudo systemctl stop paperbot-executor`를 한 뒤 다시 확인.)

3-5. 미리 보기 (아무것도 바꾸지 않음):

```bash
cd /root/crypto-bot-research && sudo bash deploy/paperbot-reset.sh --dry-run
```

보여야 할 것:
- `[멈출 것]`: 봇, 대시보드, 거래 알림, 켜져 있으면 토론방(`paperbot-debate`)과 타이머들.
- `[끝나고 다시 켤 것]` 목록, `[꺼 둘 것] paperbot-obsidian.timer (리셋 뒤 점검을 마치고 두 분이 켬 …)`(켜져 있었으면),
  `[에이전트 회의] 다시 켬(지금처럼)`, `[계속 돌 것] paperbot-shadow200.timer`.
- `[지금 paper3.db] … v3 실행(이번에 보관할 것)`, `[새 실행] paper v4: $5,000 계좌 331개 …`.
- `!! 재시작은 이미 끝났습니다`, `!! 저장소에 커밋 안 된 수정`, `!! paperbot-executor`가 나오면 멈추고 개발자에게.

3-6. **리셋** (15분 경계 2~5분 뒤, 예: 01:32~01:35). 개발자가 **"에이전트는 꺼 두세요"라고 했을 때만** 끝에 ` --agents-off`를 붙여
`sudo bash deploy/paperbot-reset.sh --yes --agents-off`로 합니다. 그런 말이 없었으면 아래 그대로:

```bash
cd /root/crypto-bot-research && sudo bash deploy/paperbot-reset.sh --yes
```

화면에 0~6단계가 차례로 나옵니다. 보여야 할 것:
- `== 1. stop` 아래 `no process has the run files open`
- `== 2.` 아래 `backup ok:` 와 `pre-reset copy kept:` (실패하면 **아무것도 옮기지 않고** 멈추고, 다시 켜는 명령이 나옵니다)
- `== 3.` 아래 install.sh 출력과 `리셋 중: 아래 타이머는 설치만 했고 여기서 켜거나 끄지 않았습니다(지금 실제 상태):`, 그 밑에 타이머
  3개의 `자동 시작 …, 지금 …` 줄
- `== 4.` 아래 `moved to /var/lib/paperbot/archive/run-…` (지우지 않고 옮김)
- `== 5.` 아래 `방 n곳에 재시작 메모`
- `== 6.` 아래 `started: …`, 그리고 `kept off (and not started at boot): …`(옵시디언·딥시크 밤 점검, `--agents-off`면 에이전트도)
- 요약: `에이전트 회의(paperbot-agents.timer): 켜짐` — `--agents-off`로 했으면 대신
  `!! 에이전트 꺼짐: 아침·순위·저녁·주간·급변 알림 없음 (paperbot-agents.timer 꺼짐, --agents-off).`
- 요약 끝: `새 실행 시작 … KST, 원래 계좌 331개 (…; 매매법 … · 딥시크 171 · 릴스 5분 단타 1 · 동전 15)` 와 `첫 30일 판정 … KST`
  - `봇이 아직 새 계좌를 만들지 않았습니다`가 나오면 정상입니다(400일치 5분봉을 받는 중). 5~15분 뒤 4-1로 확인합니다.

## 4. 시작 뒤 확인

4-1. 봇 로그에서 시작 줄을 봅니다(`Ctrl+C`로 빠져나옴):

```bash
sudo journalctl -u paperbot-live3 -f
```

보여야 할 것: `paper v4 started: 331 accounts (core 144, ds200 171, reel 1, flip 15), brackets: …, taker fee …%` 줄.
텔레그램에는 `▶️ 봇 시작 · 모의 v4 · 계좌 331개` 와 그 아래 `매매법 … · 딥시크 171 · 5분 단타 1 · 동전 15 · 추가 계좌 n`이 옵니다.
`refused`(딥시크·릴스 코드 거절, CRITICAL)나 `account held`가 보이면 6단계 전에 개발자에게.

4-2. **launchcheck** (새 시작 10~15분 뒤):

```bash
cd /opt/crypto-bot-research && sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck --stage after
```

보여야 할 것: `[고칠 것]` 없음, 마지막 줄 `[OK] 봇이 정상으로 돌고 있습니다 … 'paper v4 started: 331 accounts'가 왔는지 …`. 그리고
- `원래 계좌 331개 = … (paper v4 규칙과 같음 …)`, `멈춘(동결된) 계좌 0개 (held = 0)`, `규칙 문서 7개가 확정본과 같음`
- `[참고] 리셋 뒤 꺼 둔 타이머 …` 한 줄 (5단계에서 켤 것: 정상)
- `--agents-off`로 했으면 `[참고] 에이전트 꺼짐: 아침·순위·저녁·주간·급변 알림 없음 …` 한 줄 (정상)

4-3. 대시보드를 휴대폰으로 엽니다. 보여야 할 것: 새 화면, 위쪽 띠에 `v4 규칙`, 그룹 칸 `기존 36`·`딥시크 44`·`5분봉`·`동전 봇`.
(명령 없음)

4-4. **첫 5분봉·15분봉 줄** (첫 15분봉 경계가 지난 뒤, 예: 01:40에 시작했으면 02:05쯤):

```bash
sudo -u paperbot /opt/paperbot/venv/bin/python - /var/lib/paperbot/paper3.db <<'PY'
import sqlite3, sys, time
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
kst = lambda ms: time.strftime("%H:%M", time.gmtime(ms / 1000 + 9 * 3600))
for tf, n, mx in c.execute("SELECT timeframe, COUNT(*), MAX(delay_ms) FROM signal_log GROUP BY timeframe ORDER BY timeframe"):
    print(f"{tf:>4} 신호 {n}개, 최대 지연 {(mx or 0)/1000:.1f}초")
for tf in ("5m", "15m"):
    r = c.execute("SELECT bar_close, strategy, symbol, side, status FROM signal_log WHERE timeframe = ? ORDER BY bar_close, id LIMIT 1", (tf,)).fetchone()
    print(f"첫 {tf} 줄:", "아직 없음" if r is None else f"{kst(r[0])} KST {r[1]} {r[2]} {'롱' if r[3] > 0 else '숏'} {r[4]}")
print("5분봉 이름:", [r[0] for r in c.execute("SELECT DISTINCT strategy FROM signal_log WHERE timeframe = '5m'")])
print("딥시크 신호:", c.execute("SELECT COUNT(*) FROM signal_log s JOIN accounts a ON a.strategy = s.strategy "
                                "AND a.timeframe = s.timeframe WHERE a.kind = 'ds200'").fetchone()[0])
PY
```

보여야 할 것: `5분봉 이름`은 `REEL_H1`·`RANDOM_k`만. `첫 5m 줄`·`첫 15m 줄`에 시각과 이름. 15분봉 경계가 지나면 딥시크 신호가 생깁니다
(그 봉에 신호가 없었으면 0일 수 있음). 최대 지연은 60초 안. (5분봉은 신호가 드물어 첫 5m 줄이 한동안 `아직 없음`일 수 있습니다.)

4-5. **재시작 훈련** (새 시작 30분쯤 뒤, 15분 경계 2~5분 뒤):

```bash
sudo systemctl restart paperbot-live3
```

보여야 할 것: 아무 출력 없음. 5분 뒤 **4-2를 다시** 돌립니다: 계좌 줄에 `재시작 뒤 이어서 돌림`, `held = 0`, `[고칠 것]` 없음.

4-6. 그 밖에 알아 둘 것 (명령 없음):
- 다음 날 09:20 밤 점검 보고: 시작한 날이라 재계산이 없습니다. 조용한(알림음 없는) 한 줄
  `시작한 날: 재계산 없음 (09:00 상태 저장 뒤에 시작 · 첫 재계산은 내일 09:20)`이 오고, 사고 회의는 열리지 않습니다(정상).
  첫 `재계산 일치 331/331 (매매법 144/144 · 딥시크 171/171 · 5분 단타 1/1 · 동전 15/15)`은 시작 이틀째 아침입니다.
- 로그·알림에서 `[ds200] …`·`[reel] …`로 시작하는 줄은 **그룹** 알림입니다(딥시크 그룹, 5분봉 그룹: 릴스와 5분 동전 3개). 계좌 이름이
  아닙니다(계좌 알림은 `[F9_FVG@15m] …`처럼 `@`가 있음). 예: `[ds200] DeepSeek signal workers timed out after 60s; …`는 그 경계의
  딥시크 신호만 건너뛴 것이고 매매법 36개는 그대로 돕니다. 대시보드는 `딥시크 그룹: …`·`5분봉 그룹: …`으로 보여 줍니다.
- 리셋 직후 텔레그램 `⚠ [작업 실패] …`가 한 번 오면, 놓친 예약 작업이 새 DB가 생기기 몇 초 전에 돈 것입니다. `sudo systemctl reset-failed`로
  지우고, 다음 회차에도 실패하면 개발자에게.
- 주문 실행기를 쓰는 경우: 따라 할 계좌는 **매매법 36개의 15분·30분·1시간·4시간 계좌만** 됩니다(launchcheck가 `[고칠 것]`으로 알려 줌).

## 5. 타이머 켜기 (4-2와 4-5가 깨끗하면)

5-1. 딥시크 200 그림자 시험, 옵시디언 내보내기, 딥시크 밤 재계산 점검을 켭니다:

```bash
sudo systemctl enable --now paperbot-obsidian.timer paperbot-shadow200.timer paperbot-dscheck.timer
```

보여야 할 것: `Created symlink …` 줄 0~3개(이미 켜져 있던 것은 줄이 없음). 오류 줄 없음.

5-2. 켜졌는지 확인합니다:

```bash
systemctl list-timers 'paperbot-*' --no-pager
```

보여야 할 것: `paperbot-shadow200.timer`(15분마다), `paperbot-dscheck.timer`(다음 09:30 KST = 00:30 UTC),
`paperbot-obsidian.timer`(다음 09:50 KST = 00:50 UTC)가 `NEXT` 칸에 시각과 함께 보임.
- 딥시크 밤 재계산은 매일 09:30에 전날(UTC) 딥시크 신호를 다시 계산해 기록과 비교합니다. 결과 한 줄: `cat /var/lib/paperbot/dscheck/last.txt`.
  다르면 텔레그램 `⚠ [작업 실패] 딥시크 신호 밤 재계산 점검`이 옵니다(계좌·주문과 무관). 첫날 밤은 시세를 처음 받느라 몇 분 더 걸립니다.

5-3. (`--agents-off`로 리셋한 경우에만, 개발자가 "에이전트 v4 준비 끝"이라고 한 뒤) 에이전트 회의를 켭니다:

```bash
sudo systemctl enable --now paperbot-agents.timer
```

보여야 할 것: `Created symlink …` 한 줄. 그 뒤로 아침·순위·저녁·주간·급변 알림이 다시 옵니다.

5-4. 날짜 확인(언제든):

```bash
cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.resetrun start --paper-db /var/lib/paperbot/paper3.db
```

보여야 할 것: 새 시작 시각, 첫 30일 판정일(시작한 UTC 날짜 + 30일, 09:00 KST), 관찰 기간 끝(시작 + 21일).

## 6. 되돌리기 (rollback)

- **스테이징 중 문제(2단계)**: 3-1로 스테이징만 끕니다. v3 봇은 처음부터 그대로 돌고 있습니다. 끝.
- **리셋 스크립트가 중간에 실패하면** 화면 끝에 어디까지 했는지와 다음 명령이 나옵니다. 그대로 따릅니다.
  - 1~3단계(멈춤·백업·설치)에서 실패: 이전 실행(v3)은 그대로입니다. 화면의 `sudo systemctl start …`로 다시 켜고 개발자에게.
    (설치까지 끝난 뒤라면 v3 봇이 v4 코드로 켜지려다 거절됩니다: 그때는 아래 "v3로 완전히 돌아가기"의 코드 부분만 하거나, 개발자와
    원인을 고친 뒤 리셋을 다시 돌립니다.)
  - 4단계 뒤(파일을 옮긴 뒤) 실패: 화면에 "새 실행으로 계속하기"와 "이전 실행으로 되돌리기"(`sudo mv …` 줄들)가 나옵니다. 개발자와 고릅니다.
- **v4가 시작된 뒤 문제가 보이면**: 원칙은 고쳐서 앞으로 갑니다. 개발자가 고친 코드를 받은 뒤(1-3처럼 `git pull`) 같은 날 처음부터
  다시 시작합니다: `cd /root/crypto-bot-research && sudo bash deploy/paperbot-reset.sh --yes --force-again`
  (24시간 안의 두 번째 리셋은 `--force-again` 없이는 거절됩니다. 새 시작 시각이 새 0일이 됩니다.)
- **v3로 완전히 돌아가기**(드묾, 반드시 개발자와 함께): v3 파일은 `/var/lib/paperbot/archive/run-<리셋 시각>/`에, v3 코드는
  `/opt/crypto-bot-research.old`와 git 기록에 있습니다. 순서: 봇·대시보드·거래 알림·토론방을 멈춤 → v4 파일(`paper3.db*`, `daily3.db*`,
  `checkpoint.db*`, `tradealerts.json`)을 다른 보관 폴더로 옮김 → 보관 폴더의 v3 파일을 `/var/lib/paperbot/`로 옮김 →
  `agents3-before-reset.db`를 `agents3.db`로 복사(커서만 다름) → v3 커밋으로 `git checkout` 후 `sudo bash deploy/install.sh` → 다시 켬.
  두 분은 v3를 이미 끝내기로 했으므로 마지막 수단입니다.

## 7. 무엇을 그대로 두고 무엇을 옮기나

| `/var/lib/paperbot/…` | 리셋 |
|---|---|
| `paper3.db`, `daily3.db`, `checkpoint.db`, `checkpoint_bars/`, `rehearsal/`, `tradealerts.json`, `evening-latest.json`, `dscheck/`(결과 파일만) | **보관 폴더로 옮김**(지우지 않음; `rehearsal/`·`dscheck/`는 빈 폴더를 새로 만듦) |
| `agents3.db` | **그대로**. 보관 폴더에 사본을 만든 뒤 이전 실행을 가리키던 커서만 초기화, 열린 제안은 닫음, 방마다 v4 메모 1개 |
| `inbox.db`, `price_alerts.json` | 그대로(사본만 만듦) |
| `liq.db`, `flow.db`, `market.db`, `ghcoin/`, `lab/`, `paper.db`, `failalert/`, `exec/` | 그대로 |
| `debate/` (토론방 기록) | 그대로. 토론방은 리셋 동안 멈췄다가 다시 켜짐(켜져 있었으면). 이전 실행의 주장은 채점 때 무효 처리 |
| `shadow200/` (딥시크 200 그림자 시험) | 그대로, **계속 돎**(자기 DB와 자기 시작일; 실행 파일을 읽지 않음) |
| `obsidian/` | 그대로(매일 밤 새로 만듦). 타이머는 리셋 때 멈추고 **꺼 둠** → 5단계에서 켬 |
| `dscheck/bars5m.db` (딥시크 밤 재계산의 5분봉 저장본) | 그대로(공개 시세라 다시 받을 수 있음; 백업·서버 밖 복사에도 넣지 않음) |
| `/etc/paperbot/*`, `/var/backups/paperbot` | 그대로(옮기기 전에 새 백업을 하나 더 만들어 따로 둠) |

## 8. 대시보드만 업데이트 (봇은 계속 돎, 30일 실험 그대로)

새 대시보드 화면처럼 **대시보드 파일만** 바뀐 버전을 올릴 때 씁니다. 봇·거래 알림·에이전트·예약 작업은 멈추지 않고,
대시보드만 몇 초 다시 켜집니다.

```bash
cd /root/crypto-bot-research && git pull && sudo bash deploy/update-dash.sh
```

- 마지막 줄이 `대시보드 업데이트 완료: <커밋> (봇·알림·에이전트는 멈추지 않았습니다)`면 끝입니다. 휴대폰에서 대시보드를 새로고침하세요.
- `대시보드 밖의 파일이 설치본과 다릅니다`가 나오면 아무것도 바뀌지 않은 것입니다. 봇 파일이 바뀐 버전이라 이 방법으로는 못 올립니다. 그대로 두고 알려 주세요.
- 새 대시보드가 응답하지 않으면 스스로 이전 대시보드로 되돌립니다(`되돌림`). 그래도 직접 되돌리려면:

```bash
cd /root/crypto-bot-research && sudo bash deploy/update-dash.sh --rollback
```

## 9. 텔레그램 소리

두 분 결정(2026-10-05)으로 **모든 텔레그램 알림은 무음**입니다. 메시지는 그대로 오고, 첫 줄의 🚨(긴급)·⚠(경고) 표시로 급한 정도를
봅니다. 봇이 멈춰도 소리가 나지 않으니 하루 한두 번 텔레그램이나 대시보드를 보세요. 나중에 긴급·경고만 다시 울리게 하려면
`/etc/paperbot/live.env`(에이전트 방 알림은 `/etc/paperbot/agents.env`)에 `TELEGRAM_SOUND=1` 한 줄을 넣고 봇을 다시 켭니다
(봇 재시작은 실험을 다시 시작하지 않습니다).
