# 서버 밖 백업 (텔레그램 'paperbot 백업' 방)

서버가 통째로 사라져도 기록을 되살릴 수 있게, 매일 아침 데이터베이스 백업을 텔레그램 비공개 단체방으로 보냅니다.

- 코드: `paperbot/offsite.py` · 서비스: `deploy/paperbot-offsite.service`, `deploy/paperbot-offsite.timer`
- 서버 설치 전체 순서는 `docs/server-setup-v3.md`에 있습니다. 이 문서는 서버 밖 백업만 다룹니다.
- 서버 시계는 UTC입니다. 이 문서의 시각은 모두 **한국 시간**입니다.

---

## 1. 왜 필요한가

- 두 분은 Vultr **자동 백업(Automatic Backups)을 켜지 않기로** 했습니다(비용).
- 서버 안에는 매일 08:40에 DB 백업이 생깁니다(`/var/backups/paperbot/<날짜>/`, 14일치). 그런데 이 백업은 **같은 서버 안에** 있어서, 서버가 고장 나거나 실수로 지워지거나 Vultr 계정에 문제가 생기면 **원본과 같이 사라집니다.**
- 그래서 그 백업을 매일 한 번 **서버 밖**(텔레그램)으로 한 부 더 보냅니다. 텔레그램은 두 분이 이미 쓰고 있고, 돈이 들지 않습니다.

## 2. 무엇이 언제 어디로 가나

| 시각 | 무엇 | 어디 |
|---|---|---|
| 08:40 | 서버 안 DB 백업 (`paperbot-backup`) | 서버 `/var/backups/paperbot/<날짜>/` |
| 09:15 | 그 백업을 묶어서 텔레그램으로 (`paperbot-offsite`) | 텔레그램 **'paperbot 백업'** 방 (무음) |
| 실패하면 | "서버 밖 백업 실패 …" 경고 | 평소 알림 단체방 (WARN) |

- 보내는 것: agents3(가설 장부), inbox(두 분 글·승인), liq(강제청산), checkpoint(판정), daily3(매일 점검), paper3(계좌), 그리고 실거래 실행기 기록(executor, executor-testnet)이 있으면 그것도. 서버 안 백업 폴더에 있는 DB 전부입니다.
- 한 파일로 묶고 압축한 뒤, 텔레그램 한도(파일 하나 50 MB)에 맞게 **45 MB 조각**으로 나눠 보냅니다. 작으면 조각 1개입니다.
- 조각마다 설명(캡션)이 붙습니다: 날짜, 조각 번호(예: 2/3), 조각과 전체 파일의 확인값(sha256), 크기.
- 조각을 다 보낸 뒤 **목록 파일**(`paperbot-<날짜>.manifest.json`)을 보내고, 그 설명에 짧은 요약을 적습니다. 되살릴 때 이 목록 파일이 꼭 필요합니다.
- 폴더 이름의 날짜는 UTC 날짜라서 **한국 날짜보다 하루 앞**입니다. 예: 한국 10월 2일 08:40 백업 → 폴더 `20261001`. 요약에 "백업 시각 2026-10-02 08:41 (한국)"처럼 실제 시각이 함께 나옵니다.

요약 메시지 예:
```
paperbot 서버 밖 백업 완료: 20261001 폴더 (백업 시각 2026-10-02 08:41 한국)
DB 6개 412.3 MB → 보낸 파일 131.0 MB (zstd, 암호화 없음), 조각 3개
DB: agents3 1.2 MB · inbox 0.3 MB · liq 96.4 MB · checkpoint 0.1 MB · daily3 4.2 MB · paper3 310.1 MB
전체 sha256 85403d1bf1765cbc…
되살릴 때: 이 목록 파일과 조각 3개를 모두 내려받습니다 (docs/offsite-backup.md)
```

### 안에 든 것과 암호화

- 백업에는 **거래 기록**(paper 계좌, 실거래 실행기의 주문·체결 기록), 두 분이 대시보드에 쓴 글, 에이전트 기록이 들어 있습니다.
- **키·비밀번호·토큰은 들어 있지 않습니다.** 바이낸스 키, 텔레그램 토큰, 대시보드 비밀번호는 서버의 `/etc/paperbot/*.env` 파일에만 있고, 그 파일은 백업하지 않습니다.
- 그래서 **기본은 암호화하지 않습니다.** 다만 텔레그램 단체방은 텔레그램 회사 서버에 보관되며 종단간 암호화가 아닙니다. 그것도 싫다면 7번(선택)대로 암호를 걸 수 있습니다.

---

## 3. 텔레그램 단체방 'paperbot 백업' 만들기 (5분)

알림 단체방과 **따로** 만듭니다. 매일 큰 파일이 오므로 알림방에 섞이면 알림을 놓치기 쉽습니다.

1. 텔레그램 → 새 그룹(New Group).
2. 멤버: **다른 한 분**과 **우리 봇**(0-5에서 만든 봇, 예: `ourpaper_bot`)만 넣습니다. 다른 사람은 넣지 않습니다.
3. 그룹 이름: `paperbot 백업` → 만들기.
4. 공개 링크(공개 그룹, 사용자 이름)는 **만들지 않습니다.** 새 그룹은 처음부터 비공개입니다.
5. 단체방에 `/start@<봇 아이디>`를 한 번 보냅니다(예: `/start@ourpaper_bot`). 다음 단계에서 방 번호를 찾을 때 필요합니다.

휴대폰 저장 공간을 지키려면(권장):
- 이 방을 **알림 끄기(Mute)** 합니다. 요약은 원래 무음이지만, 방 자체를 꺼 두면 확실합니다.
- 텔레그램 설정 → **데이터 및 저장공간** → **자동 미디어 다운로드**에서 "파일"의 자동 다운로드를 끄거나 작게 둡니다. 그래야 매일 수십~수백 MB가 폰에 저절로 받아지지 않습니다. 파일은 텔레그램 클라우드에 남아 있어서, 필요할 때만 받으면 됩니다.

## 4. 방 번호 찾기 (서버에서)

토큰을 화면에 띄우지 않고, 봇이 최근에 본 방 번호와 이름만 보여 주는 명령입니다.
```bash
sudo -u paperbot bash -c 'set -a; . /etc/paperbot/live.env; cd /opt/crypto-bot-research && /opt/paperbot/venv/bin/python -m paperbot.offsite chats'
```
- 결과 예: `방 번호 -4987654321   이름 paperbot 백업   (group)`
- 이름이 **paperbot 백업**인 줄의 번호를 씁니다. 빼기(-)까지 그대로입니다. 알림 단체방 번호와 다른 번호여야 합니다.
- "최근 메시지가 없습니다"가 나오면 새 방에 `/start@<봇 아이디>`를 다시 보내고 명령을 다시 실행합니다.

## 5. 서버에 방 번호 넣기

```bash
sudo nano /etc/paperbot/live.env
```
- 맨 아래에 한 줄을 넣습니다(이미 `TELEGRAM_CHAT_BACKUP=` 줄이 있으면 그 뒤에 적습니다).
  ```
  TELEGRAM_CHAT_BACKUP=-4987654321
  ```
- 저장(Ctrl+O, Enter) → 나가기(Ctrl+X).
- 이 값이 비어 있으면 백업 파일이 **알림 단체방(CRITICAL)으로** 가고, 요약 끝에 "참고: TELEGRAM_CHAT_BACKUP 값이 비어 있어…"가 붙습니다. 동작은 하지만 알림방이 지저분해지므로 꼭 넣습니다.
- 다른 서비스는 다시 시작할 필요가 없습니다.

## 6. 켜기와 첫 시험

설치 스크립트(`deploy/install.sh`)가 서비스 파일을 설치합니다(켜지는 않음). 코드를 올린 뒤 설치 스크립트를 다시 돌렸는지 확인합니다.
```bash
ls /etc/systemd/system/paperbot-offsite.*
```
- 두 파일(`.service`, `.timer`)이 보이면 됩니다. 안 보이면 설치 스크립트를 다시 돌리거나, 아래 두 줄로 직접 설치합니다.
  ```bash
  sudo install -m 644 /opt/crypto-bot-research/deploy/paperbot-offsite.service /opt/crypto-bot-research/deploy/paperbot-offsite.timer /etc/systemd/system/
  sudo systemctl daemon-reload
  ```

매일 자동으로 돌게 켭니다.
```bash
sudo systemctl enable --now paperbot-offsite.timer
systemctl list-timers paperbot-offsite.timer paperbot-backup.timer --no-pager
```
- 둘째 명령에 다음 실행 시각이 보이면 됩니다(UTC로 표시: 백업 23:40, 서버 밖 백업 00:15).

지금 바로 한 번 시험합니다. 봇을 켠 뒤(`docs/server-setup-v3.md` 11번 이후)에 합니다. 그 전에는 백업할 DB가 없어서 "백업 폴더가 비어 있습니다"로 실패합니다. 서버 안 백업이 아직 한 번도 없었다면 먼저 만듭니다(1~2분).
```bash
sudo systemctl start paperbot-backup
sudo systemctl start paperbot-offsite
systemctl status paperbot-offsite --no-pager
```
- 명령이 끝날 때까지 몇 초~몇 분 걸립니다(보내는 동안 기다림).
- `status=0/SUCCESS`가 보이고, 'paperbot 백업' 방에 **조각 파일**과 **목록 파일 + 요약**이 오면 성공입니다.
- `status=1/FAILURE`면 아래로 이유를 봅니다. 알림방에도 "서버 밖 백업 실패 …"가 옵니다.
  ```bash
  sudo journalctl -u paperbot-offsite -n 50 --no-pager
  ```

**처음 한 번은 꼭 되살리기 연습(9번)을 합니다.** 백업은 되살려 봐야 믿을 수 있습니다. 같은 서버에서 해도 봇에는 영향이 없습니다(새 폴더에만 풉니다).

---

## 7. (선택) 암호 걸기

텔레그램에 올라가는 파일까지 암호로 잠그고 싶을 때만 합니다.

- 서버의 `openssl` 프로그램으로 잠급니다(`aes-256-cbc`, `pbkdf2` 20만 번). 직접 만든 암호화는 쓰지 않습니다. `openssl`이 없으면 **보내지 않고 실패**합니다(Ubuntu에는 기본으로 있습니다).
- **암호를 잃어버리면 백업을 영영 되살릴 수 없습니다.** 서버가 사라지면 서버 안의 암호도 같이 사라지므로, 암호는 **서버 밖에도** 적어 둡니다(두 분의 비밀번호 관리 앱, 또는 종이에 써서 안전한 곳). 채팅·메모 앱에는 적지 않습니다.

```bash
sudo nano /etc/paperbot/live.env
```
- 맨 아래에 `BACKUP_PASSPHRASE=<긴 암호>`를 넣습니다. 20자 이상, **영문·숫자·`-`만** 씁니다(예: 단어 4~5개를 `-`로 이은 것). 띄어쓰기, 따옴표, `$`·`#` 같은 기호는 설정 파일에서 다르게 읽힐 수 있어 쓰지 않습니다.
- 다음 날부터(또는 `sudo systemctl start paperbot-offsite`로 바로) 잠긴 파일이 갑니다. 파일 이름 끝에 `.enc`가 붙고, 요약에 "암호화함"이 나옵니다.
- 암호를 빼려면 그 줄을 지우거나 `BACKUP_PASSPHRASE=`로 비웁니다.

---

## 8. 잘 되고 있는지 보기

**매일 (5초):** 'paperbot 백업' 방에 오늘 아침 09:15쯤 요약이 왔는지 봅니다. 날짜가 맞으면 됩니다.

**실패하면:** 평소 알림 단체방에 이런 경고가 옵니다.
```
[WARN] 서버 밖 백업 실패 (20261001): <이유>
서버 안 백업(/var/backups/paperbot)은 그대로 있습니다. 내일 같은 시각에 다시 시도합니다.
```
자주 나오는 이유:

| 이유 (경고에 나오는 말) | 할 일 |
|---|---|
| 오늘 백업 폴더가 없습니다 / 백업이 빠졌습니다 / 백업이 끝나지 않았습니다 | 서버 안 백업이 실패한 것입니다. `systemctl status paperbot-backup --no-pager` 를 보고 개발자에게 |
| 방 번호가 틀렸거나 봇이 그 단체방에 없습니다 | 봇을 'paperbot 백업' 방에 다시 넣고, 4번으로 번호를 다시 확인 → 5번 |
| 단체방이 슈퍼그룹으로 바뀌어 방 번호가 …로 바뀌었습니다 | 경고에 적힌 새 번호로 5번의 값을 고칩니다 |
| 봇 토큰이 틀렸습니다 | `docs/server-setup-v3.md` 4-2 (봇 토큰) |
| 텔레그램 …: 6번 모두 실패 (network …) | 대개 일시적인 네트워크 문제입니다. 다음 날 다시 돕니다. 이틀 연속이면 개발자에게 |
| openssl … | 7번 (암호를 쓰면 openssl이 필요) |

- 한 번 실패한 날은 `systemctl --failed`에도 `paperbot-offsite.service`가 보입니다(`docs/server-setup-v3.md` 13-2의 주간 점검). 확인 뒤 `sudo systemctl reset-failed`.
- 실패한 날 다시 보내려면: `sudo systemctl start paperbot-offsite` (그날 폴더를 다시 보냅니다).

---

## 9. 새 서버에 되살리기 (서버를 잃었을 때)

준비물: PC(윈도우 또는 맥)에 **텔레그램 데스크톱 앱**, 그리고 암호를 걸었다면 그 암호.

### 9-1. 새 서버 만들고 설치 (봇은 아직 켜지 않음)
1. `docs/server-setup-v3.md` 1~3번: 새 서버(서울, Ubuntu 24.04, 4 vCPU / 8 GB), 코드 받기, 설치 스크립트.
2. 4~8번: env 파일을 다시 채웁니다. 예전 서버의 파일은 사라졌으므로 다시 넣습니다.
   - **바이낸스 키:** 예전 키는 **예전 서버 IP**로 묶여 있습니다. 바이낸스에서 그 키의 IP 제한을 **새 서버 IP**로 바꿉니다(또는 새 읽기 전용 키를 만듭니다).
   - **텔레그램 토큰:** BotFather → `/mybots` → 우리 봇 → **API Token**에서 다시 볼 수 있습니다. 방 번호는 4번의 `chats` 명령으로 다시 찾습니다(각 방에 `/start@<봇 아이디>`를 한 번 보낸 뒤). `TELEGRAM_CHAT_BACKUP`도 넣습니다.
   - 암호를 걸어 썼다면 `BACKUP_PASSPHRASE`도 같은 암호로 넣습니다.
3. **10~11번(시작)은 아직 하지 않습니다.** DB를 먼저 되살립니다.

### 9-2. 텔레그램에서 내려받기 (PC)
1. 텔레그램 데스크톱 → 'paperbot 백업' 방 → **가장 최근 요약**을 찾습니다.
2. 그 날짜의 **조각 파일 전부**(`paperbot-<날짜>.tar.zst.part01-of-03` …)와 **목록 파일**(`paperbot-<날짜>.manifest.json`)을 내려받습니다. 파일마다 오른쪽 클릭 → 다른 이름으로 저장(Save As).
3. 내려받은 파일만 새 폴더 `restore-in`에 모읍니다(예: 다운로드 폴더 안에). 다른 날짜의 파일은 넣지 않습니다.

### 9-3. 서버로 올리기
PC의 터미널에서(윈도우: **PowerShell**, 맥: **터미널**) `<새 IP>`를 바꿔 넣습니다. root 비밀번호를 물으면 Vultr 화면의 비밀번호를 넣습니다.
```bash
# 맥
scp -r ~/Downloads/restore-in root@<새 IP>:/root/
# 윈도우 PowerShell
scp -r $HOME\Downloads\restore-in root@<새 IP>:/root/
```
- Termius를 쓴다면 서버의 **SFTP** 화면에서 폴더를 끌어다 `/root/`에 놓아도 됩니다.

### 9-4. 서버에서 확인하고 풀기
```bash
cd /opt/crypto-bot-research
sudo /opt/paperbot/venv/bin/python -m paperbot.offsite restore --parts /root/restore-in/* --out /root/restore-out
```
- 암호를 걸었던 백업이면 암호를 묻습니다(입력하는 글자는 안 보입니다).
- 이 명령이 하는 일: 조각마다 확인값(sha256)을 목록과 대조 → 합치기 → 전체 확인값 대조 → (암호 풀기) → 풀기 → DB마다 `integrity_check`(파일이 온전한지 SQLite가 직접 검사).
- 끝에 DB마다 `integrity_check ok`가 나오고, **"다음 순서"** 아래에 그대로 붙여 넣을 명령이 나옵니다(DB마다 `sudo install …`과 `sudo rm -f …-wal …-shm`).
- "조각 3개 중 2번(…)이 없거나 손상되었습니다"가 나오면 그 조각을 텔레그램에서 다시 받습니다. "손상되었습니다"(integrity_check)가 나오면 그 날짜는 쓰지 말고 **하루 전 날짜**의 백업으로 9-2부터 다시 합니다.

### 9-5. 제자리에 넣고 켜기
1. "다음 순서"에 나온 명령을 위에서부터 붙여 넣습니다(멈추기 → DB 넣기 → `-wal/-shm` 지우기).
2. `docs/server-setup-v3.md` 10~11번대로 점검하고 켭니다. 이때 `paperbot-offsite.timer`도 함께 켭니다.
   ```bash
   sudo systemctl enable --now paperbot-offsite.timer
   ```
3. **그날은 에이전트를 쉬게 합니다.** AI 사용 기록도 백업 시점으로 돌아가서 하루 한도를 한 번 더 쓸 수 있기 때문입니다: `sudo systemctl stop paperbot-agents.timer`, 다음 날 `sudo systemctl start paperbot-agents.timer` (`docs/agent-rooms.md`).
4. **주문 실행기(`paperbot-executor`)는 켜지 않습니다** (`docs/live-safety.md`).
5. `docs/server-setup-v3.md` 12번(첫 1시간 확인)을 합니다. 그리고 개발자에게 알립니다.
6. 며칠 뒤 잘 돌면 임시 파일을 지웁니다: `sudo rm -rf /root/restore-in /root/restore-out`

무엇을 잃나:
- 마지막 백업(08:40) **뒤의 기록**은 없습니다(최대 하루). 봇은 백업 시점의 상태에서 이어서 돌고, 꺼져 있던 동안의 신호는 "늦음"으로 기록만 됩니다.
- 강제청산 기록(liq)은 바이낸스에 과거 자료가 없어서, 빈 기간은 영영 비어 있습니다.

### 연습 (처음 한 번, 그 뒤 몇 달에 한 번)
9-2~9-4만 **지금 서버에서** 해 봅니다(`--out /root/restore-test`). 9-5는 하지 않습니다. `integrity_check ok`가 모두 나오면 성공이고, 끝나면 `sudo rm -rf /root/restore-in /root/restore-test`로 지웁니다. 지금 돌고 있는 봇과 DB에는 손대지 않습니다.

---

## 10. 하루에 얼마나 가나

DB를 그대로 묶어 매일 **전체를** 보냅니다(그날 바뀐 것만이 아니라). 그래서 보내는 양은 DB가 커지는 만큼 조금씩 늘어납니다. 압축하면 보통 원래 크기의 1/3 안팎입니다.

| 시점 (추정) | 서버의 DB 합계 | 하루에 보내는 양 | 조각 |
|---|---|---|---|
| 첫 주 | 수십 MB | 수~수십 MB | 1개 |
| 한 달 | 수백 MB | 대략 100~300 MB | 3~7개 |
| 반년 | 수 GB | 대략 1 GB 안팎 | 20개 이상 |

- 추정치입니다. **실제 크기는 매일 요약의** "DB … → 보낸 파일 …" 숫자가 정확합니다.
- 텔레그램은 단체방 파일을 무료로, 기간 제한 없이 보관합니다. Vultr의 나가는 트래픽도 요금제에 포함된 양에 비하면 아주 적습니다.
- 조각이 **하루 20개를 넘기 시작하면** 개발자에게 알립니다(보내는 데 시간이 길어지고 한 번에 30분 제한이 있음).
- 오래된 백업을 지울 필요는 없습니다. 지우고 싶다면 방에서 직접 지웁니다(봇은 이틀 지난 메시지를 지울 수 없습니다). 적어도 최근 2주치는 남겨 둡니다.

## 11. 한계 (알아 둘 것)

- **하루 한 번**입니다. 서버를 잃으면 마지막 백업 뒤 최대 하루치가 사라집니다.
- 텔레그램은 백업 전문 서비스가 아닙니다. 보관을 약속하지 않으므로 **두 번째 사본**으로 생각합니다. 두 분 모두 이 방에 계속 남아 있습니다(한 분 계정에 문제가 생겨도 다른 분 계정에 남도록).
- 텔레그램은 오래 접속하지 않은 계정을 지웁니다(설정 → 개인정보 및 보안 → **계정 자동 삭제**). 두 분 모두 이 기간을 가장 길게(12개월 등) 둡니다.
- 파일 하나는 50 MB까지만 올릴 수 있어서 45 MB 조각으로 나눕니다. 봇은 20 MB가 넘는 파일을 다시 내려받을 수 없어서, **되살릴 때는 사람이 텔레그램 앱에서 내려받아** 서버로 올립니다(9번).
- 단체방은 텔레그램 서버에 저장되며 종단간 암호화가 아닙니다. 그래서 키·비밀번호는 백업에 넣지 않고, 원하면 7번처럼 암호를 겁니다.
- 한 번 보내는 데 30분이 넘으면 중간에 멈추고 실패로 끝납니다(10번 참고).
- 단체방 설정을 바꾸다 단체방이 "슈퍼그룹"으로 바뀌면 방 번호가 바뀝니다. 그날 경고에 새 번호가 나오므로 5번대로 고칩니다.
- 이 기능은 서버 안 백업 **폴더를 읽기만** 합니다. 돌고 있는 DB는 열지 않고(파일이 있는지만 확인), 아무 DB에도 쓰지 않습니다.

## 참고 (개발자용)

```bash
# 보내지 않고 묶기·나누기만 해 보기 (토큰 필요 없음)
sudo -u paperbot bash -c 'cd /opt/crypto-bot-research && /opt/paperbot/venv/bin/python -m paperbot.offsite send --from /var/backups/paperbot --lib /var/lib/paperbot --dry-run --work /tmp'
# 특정 날짜 폴더를 다시 보내기
sudo systemctl start paperbot-offsite            # 오늘(또는 어제 UTC) 폴더
# 목록 파일 없이 되살리기: 조각 설명의 '전체 sha256'을 --sha256으로
```
- 폴더 고르기: 오늘 UTC 날짜 폴더, 없으면 어제 UTC 날짜 폴더(백업이 23:40 UTC에 돌고 이 작업은 다음 날 00:15 UTC에 돌기 때문). 그보다 오래된 폴더는 보내지 않고 실패합니다. 다른 날짜는 `--date YYYYMMDD`.
- 완성 확인: 폴더에 `*.db.part`(쓰는 중)가 있으면 최대 5분 기다린 뒤 실패, `/var/lib/paperbot`에 있는 DB의 복사본이 폴더에 없으면 실패, SQLite 파일이 아니면 실패.
- 압축: `zstd` 프로그램이 있으면 zstd(-10, 2스레드), 없으면 gzip. 되살리는 서버에도 같은 프로그램이 필요합니다(`sudo apt install zstd`).
- 재시도: 네트워크 오류·5xx는 5·15·45·120·300초 뒤 다시(모두 6번), 429는 텔레그램이 말한 `retry_after`만큼 기다림(15분이 넘으면 실패). 그 밖의 4xx는 바로 실패.
- 토큰은 요청 주소에만 들어가고, 모든 오류·기록 줄에서 `<token>`으로 가립니다.
