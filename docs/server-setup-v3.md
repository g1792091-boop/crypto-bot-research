# paper v3 시작 안내서 (준비 → 서버 → 시작 → 첫 30일)

두 분이 처음부터 끝까지 이 문서 하나로 paper 봇을 켤 수 있게 썼습니다. 위에서부터 번호 순서대로 하시면 됩니다.

- 규칙은 `docs/paper-v3-rules.md`와 보충 규칙 `docs/paper-v3-rules-addendum.md`에 있습니다. 이 문서는 설치와 운영만 다룹니다.
- 에이전트 방 설명은 `docs/agent-rooms.md`, 실거래 안전장치는 `docs/live-safety.md`에 있습니다.

## 보안 원칙 (꼭 지킵니다)

- **키·비밀번호·토큰은 서버 안에서만 입력합니다.** 채팅(Claude 포함), 저장소, 스크린샷, 메모 앱에 넣지 않습니다.
- 바이낸스 키는 **읽기 전용**이고, **서버 IP에서만** 쓸 수 있게 묶습니다. 주문·출금 권한은 켜지 않습니다.
- **AI는 주문하지 않습니다.** 에이전트는 거래소 API를 부르지 않고, 195개 계좌·규칙·코드를 바꾸지 못합니다.
- 주문 실행기(`paperbot-executor`)는 설치만 되고 **켜지 않습니다.** 이 문서의 어떤 명령도 그것을 켜지 않습니다.
- 대시보드는 인터넷에 열지 않습니다. 두 분 기기에서 Tailscale로만 봅니다.
- 배포(코드 올리기)와 서버 작업은 **저장소 주인 한 분**이 합니다(보충 규칙 Q5).

## 이 문서 읽는 법

- 회색 상자는 서버에 붙여 넣는 명령입니다. **상자 하나를 통째로** 복사해 붙여 넣으면 됩니다.
- `#`으로 시작하는 줄은 설명입니다. 붙여 넣어도 아무 일도 하지 않습니다.
- 줄 끝의 `\`는 "다음 줄과 이어짐"이라는 뜻입니다.
- `<...>`는 두 분 값으로 바꿔 넣는 자리입니다(꺾쇠는 지웁니다).
- 서버 시계는 UTC(한국보다 9시간 느림)입니다. 이 문서의 시각은 모두 **한국 시간**으로 적었습니다.

## 전체 순서 한눈에

| 번호 | 할 일 | 시간 |
|---|---|---|
| 0 | 계정과 앱 준비 | 30~60분 |
| 1 | 서버 만들기 (Vultr) | 10분 |
| 2 | 코드 받기 | 5분 |
| 3 | 설치 스크립트 | 5~10분 |
| 4 | 바이낸스 키·텔레그램 넣기 | 15분 |
| 5 | 봇 멈춤 알림 (healthchecks) | 5분 |
| 6 | 대시보드 비밀번호 | 5분 |
| 7 | Tailscale | 10분 |
| 8 | 에이전트 (Claude 로그인) | 10분 |
| 9 | 5년 시험 자료 만들기 | 30~60분 (기다림) |
| 10 | 시작 전 최종 점검 | 5분 |
| 11 | 시작 | 1분 |
| 12 | 첫 1시간 확인 | 1시간 |
| 13 | 그다음 매일·매주, 30일째, 업데이트, 백업, 고장 | — |

---

## 0. 먼저 준비할 것 (계정과 앱)

서버를 만들기 전에 아래를 준비합니다. 여기서는 **키를 만들지 않습니다.** 바이낸스 키는 서버 IP가 생긴 뒤 4번에서 만듭니다.

### 0-1. 휴대폰에 SSH 앱 (서버에 붙여 넣기용)

바이낸스 키나 Claude 토큰처럼 긴 글자는 손으로 칠 수 없습니다. 붙여 넣기가 되는 SSH 앱을 씁니다.
1. App Store / Play 스토어에서 **Termius**(무료)를 설치합니다. PC가 있다면 PC의 터미널도 됩니다.
2. 서버 주소와 비밀번호는 1번에서 생깁니다. 지금은 설치만 합니다.

참고: Vultr 화면의 **View Console**(웹 콘솔)도 쓸 수 있지만 붙여 넣기가 잘 안 됩니다. 비상용으로만 씁니다.

### 0-2. Vultr 계정
1. https://www.vultr.com 에서 가입하고 결제 카드를 등록합니다.
2. 계정에 2단계 인증(Account → Authentication)을 켭니다.

### 0-3. GitHub 토큰 (저장소 주인 한 분)
저장소가 비공개라서 서버가 코드를 받으려면 토큰이 필요합니다.
1. GitHub → 오른쪽 위 사진 → **Settings** → 맨 아래 **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
2. Repository access: **Only select repositories** → `crypto-bot-research` 하나만.
3. Permissions → Repository permissions → **Contents: Read-only**. 다른 권한은 주지 않습니다.
4. 만료일을 정하고(예: 90일) 만듭니다. 토큰은 2번 단계에서 서버에만 입력합니다.
- 만료되면 다음 `git pull` 때 비밀번호를 다시 묻습니다. 그때 새 토큰을 만들어 넣으면 됩니다.

### 0-4. 바이낸스 (키는 아직 만들지 않음)
1. 바이낸스 계정에 2단계 인증(인증 앱 또는 패스키)이 켜져 있는지 확인합니다. 키를 만들 때 필요합니다.
2. **USD-M 선물 계정**을 아직 연 적이 없다면 앱의 '선물' 화면에서 개설을 마칩니다. 돈을 넣을 필요는 없습니다. 봇은 이 계정의 실제 수수료율과 레버리지 구간을 읽습니다.
3. 키는 **4번에서**, 서버 IP를 알게 된 뒤에 만듭니다.

### 0-5. 텔레그램 봇과 단체방
1. 텔레그램에서 **@BotFather**(파란 체크 표시)를 찾아 **시작**을 누릅니다.
2. `/newbot`을 보냅니다. 봇 이름(아무거나)과 아이디(`bot`으로 끝나야 함, 예: `ourpaper_bot`)를 차례로 보냅니다.
3. BotFather가 **토큰**(`123456789:AA...` 모양)을 줍니다. 4번에서 서버에 넣습니다. 다른 채팅에 붙여 넣지 않습니다.
4. 텔레그램 → 새 그룹 → 다른 한 분과 방금 만든 봇을 넣어 **단체방**을 만듭니다.
5. 단체방에 `/start@<봇 아이디>`를 한 번 보냅니다(예: `/start@ourpaper_bot`). 4번에서 방 번호를 찾을 때 필요합니다.
- 방 번호(chat id)는 4번에서 서버로 찾습니다.
- 알림 종류는 13번 표에 있습니다. 소리 나는 알림은 적고, 요약은 무음으로 옵니다.

### 0-6. healthchecks.io (서버 밖 감시)
서버가 꺼지거나 봇이 멈추면 봇 스스로는 알릴 수 없습니다. 서버 밖 감시 서비스가 대신 두 분 폰을 울립니다.
1. https://healthchecks.io 무료 가입.
2. **Add Check** → 이름 `paperbot`.
3. 그 체크의 **Change Schedule**(또는 Period/Grace 설정)에서 **Period 1 minute**, **Grace 5 minutes** → Save.
4. **Integrations**에서 두 분이 받을 방법을 연결합니다. 이메일(두 분 주소 각각), 또는 Telegram(화면 안내대로 단체방에 연결).
5. 체크 화면에서 그 알림 방법이 켜져 있는지 확인합니다.
- 체크 주소(`https://hc-ping.com/...`)는 5번에서 서버에 넣습니다. 이 주소도 비밀로 다룹니다(누가 알면 가짜 '살아 있음' 신호를 보낼 수 있음).

### 0-7. Tailscale (대시보드를 두 분 기기에서만 보기)
1. https://tailscale.com → **Get started** → Google·Apple 등 계정으로 가입(저장소 주인 계정).
2. 두 분 휴대폰에 **Tailscale** 앱을 설치합니다.
3. 저장소 주인 폰: 같은 계정으로 로그인하고 VPN 허용.
4. 다른 한 분: 관리 화면(https://login.tailscale.com/admin) → **Users** → **Invite users**로 초대 → 받은 메일로 가입 → 앱 로그인.

### 0-8. Claude Max (에이전트 방, 저장소 주인 계정)
에이전트 방은 저장소 주인의 **Claude Max 구독**으로 돕니다(보충 규칙 Q8). API 키는 쓰지 않습니다.
1. claude.ai에 로그인해 요금제가 **Max**인지 확인합니다.
2. 설정의 사용량/결제 화면에서 **Extra usage**(한도를 넘으면 따로 결제)가 **꺼져 있는지** 확인합니다. 켜져 있으면 한도를 넘은 사용이 따로 청구됩니다.
3. 로그인 토큰은 8번에서 서버에서 만듭니다.

---

## 1. 서버 만들기 (Vultr)

1. Vultr → **Deploy +** → **Deploy New Server** → **Cloud Compute (Shared CPU)**.
2. 지역(Location): **Seoul**, **Tokyo**, **Singapore** 중 하나. 미국 지역은 바이낸스가 막습니다.
3. OS(Image): **Ubuntu 24.04 LTS x64**.
4. 크기(Plan): **4 vCPU / 8 GB**. 195개 계좌와 36개 매매법 신호를 코어 4개로 계산합니다. 더 작게 하면 신호가 늦어지고 이 안내서의 설정과 맞지 않습니다.
5. **Automatic Backups(자동 백업): 켭니다.** 보충 규칙 Q10입니다. 서버 요금에 조금 더 붙습니다.
6. Hostname/Label에 `paperbot`이라고 적고 **Deploy**를 누릅니다.
7. 몇 분 뒤 서버가 **Running**이 되면 서버 화면에서 두 가지를 확인합니다.
   - **IP Address**(IPv4, 예: `141.164.x.x`). 적어 둡니다. 바이낸스 키를 이 주소로 묶습니다.
   - **Password**(root 비밀번호, 눈 모양 아이콘). 아래 Termius에만 넣습니다(채팅·메모 앱 금지).
8. 자동 백업을 깜빡했다면: 서버 화면 → **Backups** 탭 → **Enable**. 일정은 매일(Daily)을 권장합니다.

### 서버에 접속하기 (Termius)
1. Termius → **New Host**.
2. Address: 서버 IP, Username: `root`, Password: 위 비밀번호 → 저장 → 접속.
3. 처음 접속할 때 서버 지문(fingerprint)을 물으면 **Continue/Accept**.
4. `root@paperbot:~#`이 보이면 접속된 것입니다.

---

## 2. 코드 받기

```bash
apt-get update && apt-get install -y git
git clone -b claude/keen-pasteur-wav02u https://github.com/g1792091-boop/crypto-bot-research.git /root/crypto-bot-research
```
- 사용자명을 물으면: GitHub 아이디.
- 비밀번호를 물으면: 0-3에서 만든 **토큰**을 붙여 넣습니다(화면에 안 보이는 게 정상).
- 토큰을 주소 안에 넣지 마세요. 설치 스크립트가 코드 폴더를 통째로 복사하므로 주소에 넣으면 서버의 다른 곳에 남습니다.

---

## 3. 설치 스크립트와 바이낸스 연결 확인 (키 없이)

```bash
cd /root/crypto-bot-research
sudo bash deploy/install.sh
```
이 스크립트가 하는 일:
- 방화벽: SSH만 열고 나머지는 모두 닫음
- fail2ban(무차별 로그인 차단), 자동 보안 업데이트, 시계 동기화(chrony)
- 전용 사용자 `paperbot`, Python 환경(`/opt/paperbot/venv`), 코드 복사(`/opt/crypto-bot-research`)
- 빈 설정 파일 `/etc/paperbot/live.env`, `dash.env`, `agents.env`, `executor.env`
- 서비스 등록 (아직 아무것도 켜지 않음)

끝나면 바이낸스에 닿는지 확인합니다(키 필요 없음). 스크립트 끝에 나오는 영어 'Next' 안내 대신 이 문서를 따릅니다.
```bash
cd /opt/crypto-bot-research
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.live check
```
- 줄마다 `[OK]`이고, 마지막에 `[SKIP] leverage brackets need BINANCE_API_KEY/SECRET`가 하나 있으면 정상입니다(키는 아직 없음).
- `[FAIL]`에 `451`이나 `403`이 나오면 그 지역은 바이낸스가 막은 것입니다. Vultr에서 서버를 지우고(Destroy) 다른 지역으로 1번부터 다시 합니다.
- **`cd /opt/crypto-bot-research`를 빼먹지 마세요.** 이 문서의 `python -m paperbot...` 명령은 모두 이 폴더에서 실행해야 합니다. 빼먹으면 `No module named 'paperbot'`이 나옵니다.

---

## 4. 바이낸스 키와 텔레그램 넣기

### 설정 파일 고치는 법 (nano)
```bash
sudo nano /etc/paperbot/live.env
```
- 화살표로 `BINANCE_API_KEY=` 줄 끝으로 가서 붙여 넣습니다(Termius: 길게 누르기 → Paste).
- `=` 앞뒤에 빈칸이나 따옴표를 넣지 않습니다. 예: `BINANCE_API_KEY=abcd1234...`
- 저장: **Ctrl+O** → **Enter**. 나가기: **Ctrl+X**. (Termius 키보드 위 줄에 Ctrl 키가 있습니다.)

### 4-1. 바이낸스 읽기 전용 키 만들기
서버 접속 화면(nano로 `live.env`를 열어 둔 상태)과 바이낸스를 번갈아 씁니다.
1. binance.com(브라우저) 또는 앱 → 프로필 → **API Management(API 관리)** → **Create API** → **System generated** → 이름 `paperbot-read` → 보안 인증.
2. **API Key**와 **Secret Key**가 나옵니다. **Secret Key는 이때 한 번만 보입니다.** 바로 서버의 `live.env`에 붙여 넣습니다.
   - `BINANCE_API_KEY=` 뒤에 API Key
   - `BINANCE_API_SECRET=` 뒤에 Secret Key
3. 바이낸스에서 그 키의 **Edit restrictions(제한 편집)**:
   - **Enable Reading(읽기)만** 체크된 상태로 둡니다.
   - Enable Spot & Margin Trading, **Enable Futures**, **Enable Withdrawals**, 그 밖의 권한은 모두 **끔**.
   - IP 접근 제한: **Restrict access to trusted IPs only (Recommended)** → 1번에서 적은 **서버 IPv4**를 넣고 **Confirm**.
   - **Save** → 보안 인증.
4. 서버에서 `live.env`를 저장(Ctrl+O, Enter)합니다. 텔레그램 칸은 다음 단계에서 채우므로 nano는 열어 둬도 됩니다.

### 4-2. 텔레그램 토큰과 방 번호
1. `live.env`의 `TELEGRAM_BOT_TOKEN=` 뒤에 0-5의 봇 토큰을 붙여 넣고 저장 → 나가기.
2. 방 번호(chat id)를 찾습니다. 토큰을 다시 치지 않도록 파일에서 읽어 씁니다.
   ```bash
   sudo bash -c 'set -a; . /etc/paperbot/live.env; curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates"'
   ```
   - 결과에서 `"chat":{"id":-` 뒤의 숫자를 찾습니다. 단체방 번호는 **빼기(-)로 시작**합니다(예: `-1001234567890` 또는 `-4123456789`). 빼기 기호까지 그대로 씁니다.
   - `"result":[]`처럼 비어 있으면 단체방에 `/start@<봇 아이디>`를 다시 보내고 위 명령을 다시 실행합니다.
3. `sudo nano /etc/paperbot/live.env` → `TELEGRAM_CHAT_CRITICAL=` 뒤에 방 번호 → 저장.
   - `TELEGRAM_CHAT_WARN`, `TELEGRAM_CHAT_INFO`는 비워 둡니다. 비어 있으면 같은 단체방으로 갑니다. INFO(요약)는 무음으로 옵니다.
4. 에이전트 방도 같은 텔레그램을 씁니다. 아래 상자는 `live.env`의 텔레그램 네 줄을 `agents.env`에 그대로 옮깁니다(손으로 다시 칠 필요 없음).
   ```bash
   for k in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_CRITICAL TELEGRAM_CHAT_WARN TELEGRAM_CHAT_INFO; do
     v=$(sudo grep "^$k=" /etc/paperbot/live.env | cut -d= -f2-)
     sudo sed -i "s|^$k=.*|$k=$v|" /etc/paperbot/agents.env
   done
   sudo grep -c '^TELEGRAM_' /etc/paperbot/agents.env
   ```
   - 마지막 줄이 `4`면 됩니다.

시험 메시지는 10번 최종 점검이 보냅니다.

---

## 5. 봇 멈춤 알림 (healthchecks)

1. healthchecks.io의 `paperbot` 체크 화면에서 **Ping URL**(`https://hc-ping.com/...`)을 복사합니다.
2. 서버에서:
   ```bash
   sudo nano /etc/paperbot/live.env
   ```
   `DEADMAN_URL=` 뒤에 붙여 넣고 저장합니다.

동작 방식:
- 봇은 **새 1분봉을 정상 처리하고 있을 때만** 1분마다 이 주소를 부릅니다. 서버 꺼짐, 봇 멈춤, 바이낸스 데이터 끊김 중 무엇이든 6분쯤(1분 + 여유 5분) 이어지면 두 분 폰이 울립니다.
- 봇이 응답 없이 10분 멈추면 서버가 봇을 자동으로 재시작합니다(systemd watchdog).
- **주의:** healthchecks는 첫 신호를 받기 전(회색 "new" 상태)에는 **울리지 않습니다.** 10번 최종 점검이 첫 신호를 보내고, 12번에서 초록 "up"인지 꼭 확인합니다.

---

## 6. 대시보드 비밀번호

대시보드 비밀번호(12자 이상)를 정합니다. 아래 상자는 비밀번호를 두 번 묻고, 그 해시를 `dash.env`에 바로 적습니다(복사할 필요 없음). 입력하는 글자가 화면에 안 보이는 게 정상입니다.
```bash
cd /opt/crypto-bot-research
H=$(sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.dash hash) && \
  sudo sed -i "s|^DASH_PASSWORD_HASH=.*|DASH_PASSWORD_HASH='$H'|" /etc/paperbot/dash.env && echo 비밀번호 저장됨
S=$(openssl rand -hex 32) && \
  sudo sed -i "s|^DASH_SECRET=.*|DASH_SECRET=$S|" /etc/paperbot/dash.env && echo 비밀값 저장됨
sudo grep -E '^DASH_(PASSWORD_HASH|SECRET)=' /etc/paperbot/dash.env | cut -c1-32
```
- 마지막 줄에 `DASH_PASSWORD_HASH='pbkdf2$200000$...`와 `DASH_SECRET=...` 두 줄이 보이면 됩니다.
- `use at least 12 characters`나 `passwords differ`가 나오면 저장되지 않은 것입니다. 상자를 다시 붙여 넣습니다.
- 손으로 넣을 때: 해시는 `$` 기호가 들어 있으므로 **작은따옴표로 감쌉니다**(`DASH_PASSWORD_HASH='pbkdf2$...'`).
- (선택) 대시보드 글·승인에 이름을 남기려면 `sudo nano /etc/paperbot/dash.env`에서 `#DASH_OWNERS=` 줄의 `#`을 지우고 두 분 이름을 쉼표로 적습니다.

---

## 7. Tailscale (대시보드를 인터넷에 열지 않고 보기)

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```
- `To authenticate, visit:` 뒤의 주소를 폰 브라우저에서 열고, 0-7의 계정으로 로그인해 서버를 승인합니다.

```bash
tailscale ip -4
sudo ufw allow in on tailscale0
sudo sed -i "s|^DASH_HOST=.*|DASH_HOST=$(tailscale ip -4)|" /etc/paperbot/dash.env
sudo grep '^DASH_HOST=' /etc/paperbot/dash.env
```
- 첫 줄의 `100.x.y.z`가 대시보드 주소입니다. 마지막 줄에 같은 주소가 보이면 됩니다.
- 대시보드 주소(12번부터): 폰의 Tailscale 앱을 켠 상태로 브라우저에서 `http://100.x.y.z:8080`. `https`가 아니라 `http`입니다.

**꼭 할 것: 서버의 키 만료 끄기.** Tailscale은 기본으로 180일마다 서버 연결을 끊습니다.
1. https://login.tailscale.com/admin → **Machines**.
2. `paperbot` 줄 오른쪽 **⋯** → **Disable key expiry**.

---

## 8. 에이전트 (Claude Code 설치와 구독 로그인)

에이전트 방은 15분마다 서버가 회의할 일이 있는지 코드로 보고, 있으면 Claude로 회의를 엽니다. 저장소 주인의 Claude Max 구독을 씁니다(API 키 아님).

### 8-1. Claude Code 설치 (paperbot 사용자)
```bash
sudo -u paperbot -H bash -c 'cd ~ && curl -fsSL https://claude.ai/install.sh | bash'
```
- 설치 위치는 `/var/lib/paperbot/.local/bin/claude`입니다.

### 8-2. 구독 로그인 토큰 만들기
```bash
sudo -u paperbot -H /var/lib/paperbot/.local/bin/claude setup-token
```
1. 화면에 나온 주소를 폰 브라우저에서 열고, **Claude Max 계정**으로 로그인해 승인합니다.
   - "Anthropic Console account"(API 키 계정)는 **절대 고르지 않습니다.**
2. 브라우저에 코드가 나오면 복사해 서버 화면에 붙여 넣고 Enter.
3. 서버 화면에 긴 토큰(`sk-ant-oat01-...`)이 나옵니다. 복사합니다(채팅·메모 앱 금지).
4. 토큰을 넣습니다.
   ```bash
   sudo nano /etc/paperbot/agents.env
   ```
   `CLAUDE_CODE_OAUTH_TOKEN=` 뒤에 붙여 넣고 저장합니다.
- 이 토큰은 약 1년 동안 씁니다. 휴대폰 달력에 **11개월 뒤 "Claude 토큰 갱신"** 알림을 넣어 두세요(8-2를 다시 하면 됩니다).

### 8-3. agents.env의 나머지
- 텔레그램 네 줄은 4-2에서 이미 옮겼습니다.
- `AGENTS_BUDGET=` 줄은 두 분이 정한 Max 요금제 한도(코드 기본값의 2배, 하루 160번·7일 900번)가 **이미 적혀 있습니다.** 고치지 않습니다.
- `ANTHROPIC_API_KEY`는 **넣지 않습니다.** 넣으면 따로 요금이 나갈 수 있습니다(코드가 지우기는 하지만 넣지 않는 것이 원칙).
- 처음 21일은 관찰 기간입니다(기본값). 따로 적을 것이 없습니다.

### 8-4. 로그인 확인
```bash
sudo -u paperbot -H bash -c 'set -a; . /etc/paperbot/agents.env; set +a; ~/.local/bin/claude --setting-sources "" auth status --json'
```
- `"loggedIn": true`가 있어야 합니다.
- `"apiKeySource"`라는 글자가 **없어야** 합니다. 있으면 API 키로 잡힌 것이니 8-2를 다시 합니다.
- 이 확인을 통과하지 못하면 에이전트는 회의를 열지 않고 멈춥니다(대시보드에 "에이전트 멈춤 (로그인 확인)").

---

## 9. 5년 시험 자료 만들기 (30~60분)

에이전트가 매매법 변경을 5년 자료로 시험할 때 쓰는 자료입니다. 바이낸스 공개 자료만 받습니다(키 필요 없음). 받는 양 약 230MB, 디스크 약 1.5GB.

접속이 끊겨도 계속 돌도록 **서버 뒤에서** 실행합니다.
```bash
sudo systemd-run --uid=paperbot --gid=paperbot --unit=paperbot-labbuild --collect \
  -p WorkingDirectory=/opt/crypto-bot-research -p Nice=10 \
  /opt/paperbot/venv/bin/python -m paperbot.agents.labdata build --out /var/lib/paperbot/lab --procs 2
```
진행 보기(언제든 다시 봐도 됩니다. **Ctrl+C**는 보기만 멈추고 작업은 계속됩니다):
```bash
sudo journalctl -u paperbot-labbuild -f
```
- 끝나면 `60/60 files identical to the research caches`가 나옵니다.
- 앱을 닫아도 됩니다. 30~60분 뒤 다시 접속해 아래로 확인합니다.
  ```bash
  cd /opt/crypto-bot-research
  sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.agents.labdata check --out /var/lib/paperbot/lab
  ```
  `60/60 files identical`이면 끝입니다.
- `download failed ... run the same command again`이 나왔거나 60/60이 아니면, 첫 상자(systemd-run)를 **다시 붙여 넣습니다.** 받은 것은 두고 이어서 합니다.

자료가 다 되면 에이전트 배관 점검(AI 호출 없음, 실제 기록은 건드리지 않음)을 한 번 합니다.
```bash
cd /opt/crypto-bot-research
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.agents.rooms tick \
  --paper-db /var/lib/paperbot/paper3.db --daily-db /var/lib/paperbot/daily3.db \
  --agents-db /var/lib/paperbot/agents3.db --inbox-db /var/lib/paperbot/inbox.db \
  --lab-dir /var/lib/paperbot/lab --dry-run
```
- 봇이 아직 시작 전이라 `nothing due`가 나오면 정상입니다. 오류 글이 나오면 그 화면을 개발자에게 보여 줍니다(키·토큰이 안 보이는지 확인 후).
- 에이전트 명령은 꼭 `sudo -u paperbot`으로 실행합니다. root로 실행하면 root 소유 파일이 생겨 자동 실행이 막힐 수 있습니다.

---

## 10. 시작 전 최종 점검 (전부 OK여야 시작)

설치, 설정 파일, 바이낸스 키, 텔레그램, healthchecks, 대시보드, Tailscale, 에이전트 로그인을 한 번에 점검합니다.
```bash
cd /opt/crypto-bot-research
sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck --stage before --send-test --ping
```
- `--send-test`: 텔레그램 단체방에 시험 메시지를 보냅니다. 단체방에 왔는지 봅니다.
- `--ping`: healthchecks에 첫 신호를 보냅니다. healthchecks 화면이 회색 "new"에서 초록 "up"으로 바뀌는지 봅니다.
- **모든 줄이 OK여야 합니다.** OK가 아닌 줄이 있으면 해당 단계로 돌아가 고친 뒤 이 점검을 다시 합니다: 바이낸스 키 → 4-1, 텔레그램 → 4-2, healthchecks → 5, 대시보드 → 6, Tailscale → 7, 에이전트 로그인 → 8, 5년 자료 → 9, 설치·서비스 → 3.
- 이 점검이 끝나면 **바로 11번**으로 갑니다. `--ping` 뒤 6분쯤 신호가 없으면 healthchecks가 "down" 알림을 보내기 때문입니다(11번에서 봇이 준비하는 몇 분 동안 "down"이 한 번 올 수 있고, 봇이 돌기 시작하면 "up"이 옵니다).

**시작 시각 팁:** 30일 판정은 시작한 날(UTC 날짜)부터 셉니다. 한국 시간 **오전 9시 이후**에 켜면 첫 30일이 온전합니다. 오전 9시 전에 켜면 첫 기간이 거의 하루 짧아집니다.

---

## 11. 시작 (한 번에 전부 켜기)

```bash
sudo systemctl enable --now \
  paperbot-live3 paperbot-dash paperbot-liq \
  paperbot-daily3.timer paperbot-backup.timer paperbot-checkpoint.timer \
  paperbot-agents.timer paperbot-labmonthly.timer
```
이 한 줄로 켜지는 것:

| 이름 | 하는 일 |
|---|---|
| `paperbot-live3` | paper 봇 (195개 계좌, 늘 켜짐) |
| `paperbot-dash` | 대시보드 (Tailscale 주소 :8080) |
| `paperbot-liq` | 바이낸스 강제청산 기록 (과거 자료가 없어서 첫날부터) |
| `paperbot-daily3.timer` | 매일 점검, 09:20 |
| `paperbot-backup.timer` | 매일 DB 백업, 08:40 |
| `paperbot-checkpoint.timer` | 30일마다 판정 (매시 35분에 확인만) |
| `paperbot-agents.timer` | 에이전트 방, 15분마다 |
| `paperbot-labmonthly.timer` | 매달 재검사, 6일 03:30 |

- **`paperbot-executor`(주문 실행기)는 켜지 않습니다.** 실거래는 이 문서의 범위가 아닙니다(`docs/live-safety.md`).
- 서버가 재부팅돼도 위의 것들은 저절로 다시 켜집니다.

---

## 12. 첫 1시간 확인

### 처음 몇 분: 봇이 준비되는지
```bash
systemctl status paperbot-live3 --no-pager
sudo journalctl -u paperbot-live3 -f
```
- `active (running)`이어야 합니다. 처음에는 5분봉 기록 400일치를 받느라 몇 분 걸립니다. 로그 보기는 **Ctrl+C**로 나갑니다.
- `activating (auto-restart)`가 보이고 15초마다 다시 시작하면 대개 바이낸스 키나 IP 제한 문제입니다. 이때는 텔레그램이 오지 않습니다. 아래 "문제가 생기면"을 봅니다.

### 첫 텔레그램 (무음)
- `paper v3 started: 195 accounts, brackets: Binance leverageBracket (live), taker fee 0.0xxx%`
- `brackets:` 뒤가 `Binance leverageBracket (live)`여야 합니다(거래소 실제 값).

### 10~15분 뒤: 최종 점검 (시작 후)
```bash
cd /opt/crypto-bot-research
sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck --stage after
```
- 모든 줄이 OK여야 합니다.

### 대시보드
1. 폰에서 Tailscale 앱을 켜고 `http://100.x.y.z:8080`을 열어 6번의 비밀번호로 들어갑니다.
2. **서버 상태** 탭:
   - 봇 생존 신호: **정상**
   - 계좌: **195**, "새로 시작"
   - 수수료(편도): 계정 실제 수수료율
   - 레버리지 구간: **거래소 실제 값** ("예시 표"면 안 됩니다)
3. 위쪽 표시: "봇 실시간", "바이낸스 시세". 15분 안에 에이전트 표시가 "자동 토론 대기" 또는 "자동 토론 중"으로 바뀝니다.

### healthchecks
- 체크가 초록 **up**인지 봅니다. 회색 "new"면 감시가 시작되지 않은 것입니다(봇이 아직 1분봉을 처리하지 않음). 30분 넘게 회색이면 "문제가 생기면"을 봅니다.

### 나머지 (선택, 한 번만)
```bash
cd /opt/crypto-bot-research
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.live3 status --db /var/lib/paperbot/paper3.db
systemctl list-timers 'paperbot-*' --no-pager
sudo journalctl -u paperbot-agents -n 30 --no-pager
```
- 첫 줄: `accounts 195, open positions ..., bust 0` 모양.
- 둘째: 타이머 5개와 다음 실행 시각.
- 셋째: 에이전트의 첫 실행 기록(15분 안).

---

## 13. 그다음: 매일·매주, 30일째, 업데이트, 백업, 고장

### 13-1. 하루 동안 오는 것 (한국 시간)

| 시각 | 무엇 | 어디서 |
|---|---|---|
| 08:00 | 시장분석팀 아침 회의 | 대시보드 '에이전트 방' |
| 08:40 | DB 백업 (조용히) | 서버 `/var/backups/paperbot/` |
| 09:20 | 매일 점검 요약: `[날짜] 매일 점검: 재계산 일치 n/n · 거래 n건 · ...` | 텔레그램 **무음** |
| 22:00 | 손익 복기팀 → 총괄 세 줄 요약 | 텔레그램 **무음** + 에이전트 방 |
| 수시 | 개별 거래 | 대시보드만 |

수시로 오는 알림(보충 규칙 Q9):

| 종류 | 받는 방법 |
|---|---|
| 봇·데이터 5분 넘게 멈춤 | healthchecks → **두 분 폰** |
| 강제청산, 재계산 불일치 | 텔레그램 **소리** |
| 빠진 1분봉, 신호 계산 멈춤, 재시작 때 체결·청산·사이즈 코드 변경 | 텔레그램 **소리** |
| 파산, 낙폭 −20/−30/−40% | 1시간에 한 번 묶어서 텔레그램 **무음** |
| 직원들이 스스로 보내는 알림 | 하루 3번까지 |

매일 아침 30초: 09:20 메시지의 **재계산 일치 n/n**이 모두 일치인지 봅니다. 다르면 소리 알림이 따로 오고, 운영·검증팀 회의가 저절로 열립니다.

### 13-2. 일주일에 한 번 (5분)
```bash
systemctl --failed --no-pager
ls /var/backups/paperbot
df -h /
```
- 첫 줄이 `0 loaded units listed`면 정상입니다. 백업·매일 점검·판정이 실패하면 **텔레그램 없이 여기에만** 나옵니다. 나오면 13-7을 봅니다.
- 둘째: 최근 날짜 폴더(`20261008` 모양)가 있어야 합니다. 14일치가 남습니다.
- 셋째: 사용률(Use%)이 80% 밑이면 됩니다.
- healthchecks가 초록인지, Vultr 서버 화면 **Backups** 탭에 최근 백업이 있는지 봅니다.
- 대시보드 서버 상태 탭의 "최근 경고" 목록을 훑어봅니다.

### 13-3. 처음 21일: 관찰 기간
두 분이 처음 3주는 지켜보기만 하기로 했습니다.
- 봇이 처음 시작한 뒤 **21일 동안** 직원들은 토론·메모·가설·5년 시험은 하지만 **복제 계좌 제안은 하지 않습니다.**
- 두 분이 할 일은 없습니다. 원하시면 에이전트 방에 글을 남길 수 있습니다(15분 안에 다룸).
- 매매법 방의 주간 검토는 그 매매법 거래가 30건 쌓일 때마다 정해진 요일에 열립니다.
- 첫날 예상되는 것(고장 아님):
  - 처음 맞는 09:20에 텔레그램 `[날짜] 재계산 못 함: 그날 00:00 상태 저장이 없습니다 (봇이 멈춰 있었음)` 한 번. 시작한 날은 그날 09:00(00:00 UTC) 상태 저장이 없기 때문입니다. 이 일로 운영·검증팀 회의가 한 번 열립니다.
  - 봇이 paper3.db를 만들기 전에 판정 타이머(매시 35분)가 먼저 돌면 `systemctl --failed`에 `paperbot-checkpoint`가 한 번 보일 수 있습니다. 해롭지 않습니다. `sudo systemctl reset-failed`로 지웁니다.
- 22일째부터 직원들이 복제 계좌를 제안할 수 있습니다. 처음 60일은 두 분이 대시보드에서 승인·거절을 눌러야 합니다(`docs/agent-rooms.md` "승인·거절").

### 13-4. 30일째 판정
- **언제:** 시작한 UTC 날짜 + 30일의 오전 9시(한국) 기준. 판정 타이머가 09:35에 돌고 약 10분 계산합니다. 그 뒤 60일, 90일… 마다 같습니다.
- **어디서:** 텔레그램 무음 `[체크포인트 30일 · 날짜 09:00 KST] 판정: 1차 합격 n · 2차 통과 n · 불합격 n · 보류 n · 관찰용 n`, 대시보드 순위표의 "체크포인트 판정", 총괄 방의 30일 점검 회의.
- **뜻:** 1차 합격은 아직 "실거래 검토 대상"이 아닙니다. 1차 합격 계좌의 그다음 30일로 하는 **2차 통과**가 실거래 검토 대상입니다. 거래 30건이 안 된 계좌는 "보류", 4시간봉과 동전 봇은 "관찰용"입니다. 자세한 기준은 아래 "체크포인트 판정".
- **실거래:** 판정은 코드가 하고, 실거래 여부는 두 분이 정합니다. 시작은 보충 규칙 Q3·Q6의 작은 금액과 테스트넷 연습을 마친 뒤에만입니다(`docs/live-safety.md`). AI는 주문하지 않습니다.

### 13-5. 코드 업데이트 (보충 규칙 Q5)
- **배포는 저장소 주인 한 분만** 합니다. 커밋된 코드만 배포됩니다(설치 스크립트가 강제).
- 수정은 두 가지입니다.
  - **화면·운영 수정**(대시보드, 알림, 에이전트, 문서): 언제든 배포합니다.
  - **체결·청산·사이즈가 바뀔 수 있는 수정:** 영향을 받는 계좌의 현재 30일 기간을 **배포일부터 다시 셉니다**(판정이 뒤로 밀림). 그래서 몇 개씩 모아 한 번에, 가능하면 판정일 직후에 배포합니다.
- 받기 전에 체결·청산·사이즈 파일이 바뀌는지 볼 수 있습니다(아무것도 안 나오면 해당 없음).
  ```bash
  cd /root/crypto-bot-research
  git fetch
  git diff --stat HEAD origin/claude/keen-pasteur-wav02u -- \
    paperbot/engine.py paperbot/ladder.py paperbot/margin.py paperbot/sizing.py \
    paperbot/config.py paperbot/models.py paperbot/accounts.py paperbot/sigservice.py \
    paperbot/aggregate.py paperbot/feed.py paperbot/live3.py
  ```
  (이 목록은 `paperbot/runinfo.py`의 `TRADING_FILES`와 같습니다. 봇은 이 밖에 설정, 바이낸스 레버리지 구간, 잠긴 신호 코드가 바뀌어도 같은 알림을 보냅니다.)
- **피할 시간:** 매일 08:30~09:40(백업·매일 점검), 판정일 09:30~10:30, 매달 6일 03:00~07:00(매달 재검사). 업데이트가 이 작업들을 멈추지 않아서, 도는 중에 코드가 바뀔 수 있습니다.
- 업데이트 순서:
  1. (선택) healthchecks에서 체크를 **Pause**. 봇이 다시 준비하는 몇 분 동안 "down" 알림이 오지 않게 합니다. 다음 신호가 오면 감시가 저절로 다시 시작됩니다.
  2. 배포:
     ```bash
     cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh
     ```
     돌고 있던 서비스는 교체하는 순간만 멈췄다가 다시 켜집니다. 이전 코드는 `/opt/crypto-bot-research.old`에 남습니다.
  3. 텔레그램: `paper v3 resumed: ...`와 `재시작 때 바뀐 것: ...`. 끝에 "(체결·청산·사이즈에는 영향 없음)"이면 화면·운영 수정입니다. "해당 30일 기간을 오늘부터 다시 셉니다"면 Q5가 적용됩니다(소리 알림). 날짜와 내용을 적어 둡니다(서버도 `runs` 표에 자동 기록).
  4. 확인:
     ```bash
     cd /opt/crypto-bot-research
     sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck --stage after
     ```
- **되돌리기**(새 코드가 문제일 때, 개발자와 상의 후):
  ```bash
  cat /opt/crypto-bot-research.old/VERSION.json
  cd /root/crypto-bot-research
  git checkout <위에 나온 "commit" 값>
  sudo bash deploy/install.sh
  ```
  되돌리기도 배포라서 체결 코드가 바뀌면 Q5가 똑같이 적용됩니다. 다음에 새 코드를 받을 때는 `git checkout claude/keen-pasteur-wav02u && git pull`부터 합니다.

### 13-6. 백업 (보충 규칙 Q10)
- **서버 안, 매일:** 08:40 `/var/backups/paperbot/<날짜>/`에 14일치. agents3(가설 장부), inbox(두 분 글·승인), liq(강제청산), checkpoint(판정), daily3(매일 점검), paper3(계좌). 실거래 기록(exec)이 생기면 그것도.
- **서버 통째로:** Vultr 자동 백업(1번에서 켬). 서버 화면 → **Backups** 탭에 목록이 있습니다.
- **DB 하나를 되살릴 때:** 순서를 꼭 지켜야 파일이 깨지지 않습니다. `docs/agent-rooms.md`의 "데이터베이스를 백업에서 되살릴 때"를 따릅니다. 거기 적힌 것 외에, `liq.db`를 되살릴 때는 `paperbot-liq`도, `checkpoint.db`를 되살릴 때는 `paperbot-checkpoint.timer paperbot-checkpoint.service`도 먼저 멈춥니다.
- **서버를 통째로 잃었을 때:** Vultr → 서버 → Backups → 날짜 고르기 → **Restore**. 서버가 그 백업 시점으로 돌아갑니다(그 뒤 기록은 사라짐). 봇은 저장된 상태에서 이어서 돌고, 꺼져 있던 동안의 신호는 "늦음"으로 기록만 됩니다. 에이전트의 AI 사용 기록도 그 시점으로 돌아가므로, `docs/agent-rooms.md`의 안내대로 그날은 `sudo systemctl stop paperbot-agents.timer`로 에이전트를 쉬게 하고 다음 날 `sudo systemctl start paperbot-agents.timer`로 켭니다. 되살린 뒤 12번 확인을 다시 하고 개발자에게 알립니다.

### 13-7. 문제가 생기면

먼저: 개발자에게 화면을 보여 줄 때는 **키·토큰·비밀번호가 안 보이는지** 확인합니다.

**서버에 접속이 안 됨**
- 비밀번호를 여러 번 틀리면 그 폰의 주소가 10분쯤 막힙니다(fail2ban). 기다렸다 다시 하거나, Vultr 서버 화면의 **View Console**로 들어갑니다.

**폰에 healthchecks "DOWN" 알림**
1. Vultr 화면에서 서버가 **Running**인지 봅니다. 아니면 **Restart**.
2. 서버에서:
   ```bash
   systemctl status paperbot-live3 --no-pager
   sudo journalctl -u paperbot-live3 -n 50 --no-pager
   ```
3. 대부분은 바이낸스 쪽 끊김이고, 저절로 "UP" 알림이 옵니다. 30분 넘게 계속되면 `sudo systemctl restart paperbot-live3`.

**봇이 15초마다 다시 시작함 (`activating (auto-restart)`)**
- 대개 바이낸스 키나 IP 제한입니다. 이때는 텔레그램이 오지 않습니다.
  ```bash
  sudo journalctl -u paperbot-live3 -n 30 --no-pager
  cd /opt/crypto-bot-research
  sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck --stage after
  ```
- 로그에 `-2015`(키·IP·권한이 틀림)나 `-2014`/`-1022`(키 모양·서명이 틀림)가 보이면 키 문제입니다.
- 키 문제면 4-1을 다시 합니다(바이낸스에서 서버 IP 확인, 새 키를 `live.env`에) → `sudo systemctl restart paperbot-live3`.

**대시보드가 안 열림**
- 폰의 Tailscale 앱이 켜져 있는지, 주소가 `http://`인지 봅니다.
  ```bash
  systemctl status paperbot-dash --no-pager
  tailscale status
  ```
- 서버 쪽 Tailscale이 끊겼으면 `sudo tailscale up` 후 7번의 "키 만료 끄기"를 확인합니다.

**텔레그램이 안 옴**
- 시험 메시지를 직접 보내 봅니다(토큰은 파일에서 읽음).
  ```bash
  sudo bash -c 'set -a; . /etc/paperbot/live.env; curl -s -d chat_id="$TELEGRAM_CHAT_CRITICAL" -d text="paperbot test" "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage"'
  ```
- 결과에 `"ok":true`가 있고 단체방에 메시지가 오면 정상입니다.
- `chat not found`나 `upgraded to a supergroup`이 나오면 방 번호가 바뀐 것입니다(단체방 설정을 바꾸면 바뀔 수 있음). 4-2의 방 번호 찾기를 다시 하고, `live.env`와 `agents.env` 둘 다 고친 뒤 `sudo systemctl restart paperbot-live3`.
- `Unauthorized`면 봇 토큰이 틀린 것입니다. BotFather에서 토큰을 다시 확인합니다.

**대시보드에 "에이전트 멈춤 (로그인 확인)"**
- Claude 토큰이 만료됐거나 틀렸습니다. 8-2와 8-4를 다시 합니다. 다음 15분 차례부터 저절로 이어집니다.

**대시보드에 "에이전트 멈춤 (오류)"**
```bash
systemctl status paperbot-agents --no-pager
sudo journalctl -u paperbot-agents -n 50 --no-pager
```
- 설정 값을 잘못 적으면 여기에 이유가 나옵니다. 화면을 개발자에게 보여 줍니다.

**텔레그램 "재계산 불일치" (소리)**
- 봇은 그대로 둡니다. 운영·검증팀 회의가 저절로 열립니다. 메시지 내용을 개발자에게 알립니다.

**`systemctl --failed`에 무언가 있음**
```bash
sudo journalctl -u <그 이름> -n 50 --no-pager
```
- 백업·매일 점검은 대개 일시적인 네트워크 문제이고 다음 날 다시 돕니다. 이틀 연속이면 개발자에게.
- 확인한 뒤 `sudo systemctl reset-failed`로 목록을 비웁니다.

**디스크가 거의 참 (`df -h /` 80% 넘음)**
- 개발자에게 알립니다. 파일을 직접 지우지 않습니다.

---

## 운영

| 일 | 방법 |
|---|---|
| 전체 상태 | `systemctl list-units 'paperbot-*' --no-pager`, 타이머: `systemctl list-timers 'paperbot-*' --no-pager`, 실패한 것: `systemctl --failed --no-pager` |
| 재시작 | `sudo systemctl restart paperbot-live3`. 계좌 상태는 저장돼 있어 이어서 돕니다. 꺼져 있던 동안의 신호는 "늦음"으로 기록만 됩니다 |
| 매일 점검 | 09:20(한국 시간)에 자동. paper와 재계산 일치, 지정가·놓친 신호 그림자 기록, 데이터 품질 |
| 체크포인트 판정 | 시작 후 30·60·90…일째 09:00(한국 시간) 기준. 매시 35분에 확인하고, 판정할 날이면 약 10분 계산한 뒤 텔레그램(무음)과 대시보드 순위표에 결과. 아래 "체크포인트 판정" 참고 |
| 체결 비용 기록 | 모의 거래가 진입·청산할 때마다 그 코인의 호가창(양쪽 100칸)을 받아, 같은 크기의 시장가 주문이 실제로 얼마에 체결됐을지 `paper3.db`의 `fill_costs`에 적습니다(`paperbot/fillcost.py`). 모의 체결 자체는 바꾸지 않습니다(엔진은 늘 0.02%로 계산). 매일 점검 보고서의 `fill_costs`에 코인별 중간값·상위 10%·0.02%를 넘은 횟수가 나옵니다 |
| 청산 기록 | `paperbot-liq`가 바이낸스 강제청산 흐름을 `liq.db`에 모읍니다(공개 자료, 키 필요 없음). 바이낸스는 청산의 과거 자료를 주지 않아서 첫날부터 켜 둡니다. 확인: `cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.liqstream status --db /var/lib/paperbot/liq.db` |
| 계좌 요약 | `cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.live3 status --db /var/lib/paperbot/paper3.db` |
| 에이전트 | 15분마다 자동. 기록: `sudo journalctl -u paperbot-agents -n 50 --no-pager`. 끄기: `sudo systemctl disable --now paperbot-agents.timer`(방과 기록은 남음). 설정: `docs/agent-rooms.md` "설정 바꾸기" |
| 매달 재검사 | 매달 6일 03:30(한국 시간). 5년 자료 뒤의 새 기간으로 다시 계산해 총괄 방에 요약 |
| 백업 | 매일 08:40(한국 시간) `/var/backups/paperbot/날짜/`, 14일 보관. 서버 통째로는 Vultr 자동 백업 |
| 코드 업데이트 | `cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh`. 배포는 **한 분만** 합니다. 커밋 안 된 수정이 있으면 멈추고, 돌던 서비스는 교체하는 순간만 멈췄다가 다시 켜집니다. 이전 코드는 `/opt/crypto-bot-research.old`에 남습니다. 봇은 켜질 때마다 코드 버전·설정을 기록하고, 체결·청산·사이즈 코드가 바뀌었으면 알림을 보냅니다(규칙상 그 기간을 다시 셈). 13-5 참고 |
| 최종 점검 다시 | `cd /opt/crypto-bot-research && sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck --stage after` |
| 비밀번호 로그인 끄기 (권장) | SSH 키를 등록하고 **키로 접속되는 것을 확인한 뒤** `echo 'PasswordAuthentication no' \| sudo tee /etc/ssh/sshd_config.d/00-paperbot.conf && sudo systemctl restart ssh`. 확인: `sudo sshd -T \| grep -i passwordauthentication`이 `no`. `/etc/ssh/sshd_config`만 고치면 Vultr가 넣어 둔 `sshd_config.d` 설정이 이겨서 효과가 없을 수 있습니다. 지금 접속은 끊지 말고 새 창으로 키 접속을 먼저 시험합니다. 키 등록 전에 끄면 들어갈 수 없게 되니, Vultr 웹 콘솔이 되는지 먼저 확인 |
| 규칙 문서가 그대로인지 | `cd /opt/crypto-bot-research && sha256sum -c docs/paper-v3-rules.sha256 docs/paper-v3-rules-addendum.sha256` (둘 다 `OK`) |

## 체크포인트 판정 (30일마다, `paperbot/checkpoint.py`)
규칙은 `docs/paper-v3-rules.md` 4장과 보충 규칙(확정) Q1·Q2·Q3 그대로입니다. 코드가 계산하고, 사람이 말로 판단하지 않습니다.

- **언제:** 시작일(첫 계좌가 만들어진 UTC 날짜)부터 30·60·90…일째 00:00 UTC(한국 09:00). `paperbot-checkpoint.timer`가 매시 35분에 돌고, 판정할 날이 아니면 바로 끝납니다.
- **스냅샷(Q2):** 봇이 그 시각에 저장한 상태(`paper3.db`의 `day:<날짜>`)를 그대로 옮겨 고정합니다. 평가금 = 지갑 + 열린 포지션의 마크 가격 기준 미실현 손익 − 예상 청산 수수료·슬리피지. 열린 거래는 진입한 기간의 거래로 셉니다. 스냅샷은 해시(sha256)와 함께 `checkpoint.db`에 한 번만 쓰이고 고칠 수 없으며(표가 수정·삭제를 거부), 판정은 해시를 확인한 스냅샷만 씁니다. `paper3.db`는 읽기만 합니다(봇이 유일한 작성자).
- **판정 순서(Q3):** 계좌(매매법 × 봉)마다 거래 30건을 넘긴 첫 판정일에 1차 판정. 1차 합격 = 거래 30건 이상 + 평가금 > 시작 금액($5,000) + 파산 아님 + 우연 기준 통과. 1차 합격 계좌는 그다음 30일만으로 2차 확인(그 기간 거래 30건 이상, 그 기간 손익 플러스(시작 금액 기준으로 환산), 우연 기준 다시 통과) → "2차 통과" = 실거래 검토 대상. 4시간봉과 동전 봇 계좌 15개는 "관찰용"(판정 안 함). 180일까지 30건이 안 되면 "보류 · 판정 불가".
- **우연 기준(Q1):** 판정하는 계좌마다 동전 봇 2,000개를 **같은 기간의 실제 1분봉**(바이낸스 공개 API에서 받은 마지막 체결가·마크 가격·실제 펀딩, `/var/lib/paperbot/checkpoint_bars`에 하루 단위로 보관)으로 같은 규칙(2 ATR 손절, 레버리지 단계와 거래소 구간, 코인 순서, 계단식 잠금, 마크 가격 강제청산, $10 파산)과 같은 시작 금액으로 돌립니다. 동전 봇의 신호 빈도는 그 계좌가 그 기간에 실제로 낸 신호 수 ÷ (6코인 × 봉 수)와 같습니다. p = (계좌 이상인 동전 봇 수 + 1) / 2,001. 그날 판정하는 모든 계좌(개선 복사 계좌 포함)를 모아 FDR 10%(Benjamini–Hochberg)로 보정해 q ≤ 0.10이어야 통과입니다. "우연으로 기대되는 합격 수"는 통과 수 × 10%(상한)로 함께 보고합니다.
- **동전 봇 엔진:** paper 엔진과 같은 규칙을 2,000 × 계좌 수만큼 한꺼번에 계산하는 벡터 버전입니다. 테스트가 같은 신호를 진짜 `PaperEngine`에 넣어 거래 하나하나(손절·잠금·강제청산·펀딩·파산) 같은 결과인지 확인합니다. 시간: 30일 창에서 한 봉의 36계좌 × 2,000개가 약 2~3분, 첫 판정(4개 봉 전부)이 약 10분(코어 1개, 낮은 우선순위). 그래서 계좌끼리 동전 봇을 나눠 쓰지 않고 계좌마다 따로 2,000개를 돌립니다.
- **결과 보기:** 대시보드 순위표의 "체크포인트 판정", 텔레그램 무음 요약, 서버에서 `cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.checkpoint show --out /var/lib/paperbot/checkpoint.db`. 에이전트는 `paperbot.checkpoint.latest_verdict` / `account_status` / `statuses`로 읽습니다.
- **주의:** 기간 중에 체결·청산·사이즈 코드가 바뀐 재시작이 있으면 판정 결과에 "주의"로 표시합니다. Q5(그 계좌의 기간을 배포일부터 다시 셈)는 아직 코드가 자동으로 적용하지 않으므로 규칙 관리자가 확인합니다.

## 실거래 준비 (이 문서 범위 밖)
테스트넷 주문 연습과 실거래는 `docs/live-safety.md` 3장을 따릅니다. 주문 키는 `live.env`가 아니라 root만 읽을 수 있는 `/etc/paperbot/executor.env`에 넣고, 주문 실행기(`paperbot-executor`)는 그 문서의 순서대로 사람이 직접 켭니다. paper 봇의 읽기 전용 키를 주문 키로 쓰지 않습니다.
