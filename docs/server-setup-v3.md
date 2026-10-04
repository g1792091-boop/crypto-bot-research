# paper v3 시작 안내서 (준비 → 서버 → 시작 → 첫 30일)

두 분이 처음부터 끝까지 이 문서 하나로 paper 봇을 켤 수 있게 썼습니다. 위에서부터 번호 순서대로 하시면 됩니다.

- 규칙은 `docs/paper-v3-rules.md`와 보충 규칙 `docs/paper-v3-rules-addendum.md`에 있습니다. 이 문서는 설치와 운영만 다룹니다.
- 에이전트 방 설명은 `docs/agent-rooms.md`, 실거래 안전장치는 `docs/live-safety.md`에 있습니다.

## 보안 원칙 (꼭 지킵니다)

- **키·비밀번호·토큰은 서버 안에서만 입력합니다.** 채팅(Claude 포함), 저장소, 스크린샷, 메모 앱에 넣지 않습니다.
- 바이낸스 키는 **읽기 전용**이고, **서버 IP에서만** 쓸 수 있게 묶습니다. 주문·출금 권한은 켜지 않습니다.
- **AI는 주문하지 않습니다.** 에이전트는 거래소 API를 부르지 않고, 156개 계좌·규칙·코드를 바꾸지 못합니다.
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
| 4 | 바이낸스 키·텔레그램·백업 방 넣기 | 20분 |
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
- GitHub는 토큰을 만들 때 **한 번만** 보여 줍니다. 서버가 2번에서 처음 넣은 토큰을 root만 읽을 수 있는 파일(`/root/.git-credentials`)에 저장해 두고, 코드 업데이트(13-5) 때 그것을 씁니다. 다른 곳(채팅·메모 앱)에는 적어 두지 않습니다.
- 만료되면 `git pull`이 `Authentication failed`로 멈춥니다(그때 저장된 옛 토큰은 지워집니다). 위 1~4로 새 토큰을 만들고 **같은 명령을 한 번 더** 실행하면 사용자명과 비밀번호를 다시 묻습니다. 비밀번호 자리에 새 토큰을 넣습니다.

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
4. 크기(Plan): **4 vCPU / 8 GB**. 156개 계좌와 36개 매매법 신호를 코어 4개로 계산합니다. 더 작게 하면 신호가 늦어지고 이 안내서의 설정과 맞지 않습니다.
5. **Automatic Backups(자동 백업): 끕니다**(켜져 있으면 체크를 풉니다). 두 분은 비용 때문에 Vultr 자동 백업 대신 매일 DB 백업을 텔레그램 비공개 단체방으로 보내기로 했습니다(4-3, `docs/offsite-backup.md`). 보충 규칙 Q10의 "Vultr 자동 백업" 권장은 이 결정으로 바뀌었습니다.
6. Hostname/Label에 `paperbot`이라고 적고 **Deploy**를 누릅니다.
7. 몇 분 뒤 서버가 **Running**이 되면 서버 화면에서 두 가지를 확인합니다.
   - **IP Address**(IPv4, 예: `141.164.x.x`). 적어 둡니다. 바이낸스 키를 이 주소로 묶습니다.
   - **Password**(root 비밀번호, 눈 모양 아이콘). 아래 Termius에만 넣습니다(채팅·메모 앱 금지).
8. 자동 백업이 켜진 채로 만들었다면(요금이 더 나감): 서버 화면 → **Backups** 탭에서 끕니다(Disable).

### 서버에 접속하기 (Termius)
1. Termius → **New Host**.
2. Address: 서버 IP, Username: `root`, Password: 위 비밀번호 → 저장 → 접속.
3. 처음 접속할 때 서버 지문(fingerprint)을 물으면 **Continue/Accept**.
4. `root@paperbot:~#`이 보이면 접속된 것입니다.

---

## 2. 코드 받기

**개발자가 "시작용 코드 완료"라고 알려 준 뒤에** 받습니다. 시작한 뒤에 체결·청산·사이즈 코드가 바뀌면 그 배포일부터 30일 기간을 다시 셉니다(13-5, 보충 규칙 Q5). 그래서 그런 수정은 시작 전에 모두 들어가 있어야 합니다.

```bash
apt-get update && apt-get install -y git tmux
git config --global credential.helper store
git clone -b claude/keen-pasteur-wav02u https://github.com/g1792091-boop/crypto-bot-research.git /root/crypto-bot-research
```
- 사용자명을 물으면: GitHub 아이디.
- 비밀번호를 물으면: 0-3에서 만든 **토큰**을 붙여 넣습니다(화면에 안 보이는 게 정상).
- 둘째 줄 덕분에 토큰이 root만 읽는 `/root/.git-credentials`에 저장되어, 업데이트(13-5) 때 다시 묻지 않습니다. 설치 스크립트는 코드 폴더만 복사하므로 이 파일은 다른 곳으로 가지 않습니다.
- 토큰을 주소 안에 넣지 마세요. 설치 스크립트가 코드 폴더를 통째로 복사하므로 주소에 넣으면 서버의 다른 곳에 남습니다.
- `Could not get lock …`(뒤에 `unattended-upgr`나 `apt-get`)가 나오면 새 서버가 처음 몇 분 동안 자동 업데이트를 하는 중입니다. 5~10분 기다렸다가 같은 상자를 다시 붙여 넣습니다.

---

## 3. 설치 스크립트와 바이낸스 연결 확인 (키 없이)

```bash
cd /root/crypto-bot-research
sudo bash deploy/install.sh
```
- 여기서도 `Could not get lock`이 나오면(`== packages`에서 멈춤) 5~10분 뒤 같은 명령을 다시 실행합니다. 다시 실행해도 안전합니다.

이 스크립트가 하는 일:
- 방화벽: SSH만 열고 나머지는 모두 닫음
- fail2ban(무차별 로그인 차단), 자동 보안 업데이트, 시계 동기화(chrony)
- 전용 사용자 `paperbot`, Python 환경(`/opt/paperbot/venv`), 코드 복사(`/opt/crypto-bot-research`)
- 빈 설정 파일 `/etc/paperbot/live.env`, `dash.env`, `agents.env`, `executor.env`
- 서비스 등록 (아직 아무것도 켜지 않음)

끝나면 바이낸스에 닿는지 확인합니다(키 필요 없음). 스크립트 끝에 나오는 영어 'Next' 안내는 **따르지 않습니다**(순서와 명령이 이 문서와 다름). 이 문서를 따릅니다.
```bash
cd /opt/crypto-bot-research
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.live check
```
- 줄마다 `[OK]`이고, 마지막에 `[SKIP] leverage brackets need BINANCE_API_KEY/SECRET`가 하나 있으면 정상입니다(키는 아직 없음).
- `[FAIL]`에 `451`이나 `403`이 나오면 그 지역은 바이낸스가 막은 것입니다. Vultr에서 서버를 지우고(Destroy) 다른 지역으로 1번부터 다시 합니다.
- **`cd /opt/crypto-bot-research`를 빼먹지 마세요.** 이 문서의 `python -m paperbot...` 명령은 모두 이 폴더에서 실행해야 합니다. 빼먹으면 `No module named 'paperbot'`이 나옵니다.

---

## 4. 바이낸스 키와 텔레그램 넣기

### 4-0. 접속이 끊겨도 이어서 하기 (휴대폰이면 꼭)
4~8번은 서버 화면과 바이낸스·브라우저 앱을 오가며 합니다. 휴대폰은 다른 앱으로 가 있는 동안 Termius 접속을 끊을 수 있습니다. 그래서 먼저 아래를 붙여 넣습니다.
```bash
tmux new -A -s setup
```
- 화면 맨 아래에 초록 줄이 생기면 됩니다. 4~8번은 이 화면 안에서 합니다.
- 접속이 끊기면: Termius로 다시 접속한 뒤 **같은 명령**(`tmux new -A -s setup`)을 붙여 넣습니다. 하던 화면(열어 둔 nano 포함)이 그대로 돌아옵니다.
- PC 터미널이라면 없어도 됩니다.

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
   - 붙여 넣자마자 **저장합니다(Ctrl+O, Enter).** 다음 단계로 바이낸스에 갔다 오는 사이 접속이 끊겨도 키가 남습니다.
3. 바이낸스에서 그 키의 **Edit restrictions(제한 편집)**:
   - **Enable Reading(읽기)만** 체크된 상태로 둡니다.
   - Enable Spot & Margin Trading, **Enable Futures**, **Enable Withdrawals**, 그 밖의 권한은 모두 **끔**.
   - IP 접근 제한: **Restrict access to trusted IPs only (Recommended)** → 1번에서 적은 **서버 IPv4**를 넣고 **Confirm**.
   - **Save** → 보안 인증.
4. 서버에서 `live.env`를 한 번 더 저장(Ctrl+O, Enter)합니다. 텔레그램 칸은 다음 단계에서 채우므로 nano는 열어 둬도 됩니다.

**nano를 연 채 접속이 끊겼고 tmux로도 화면이 돌아오지 않을 때:** nano는 끊기기 직전 내용을 `이름.save` 파일로 남깁니다(키가 들어 있음).
```bash
sudo ls /etc/paperbot/
```
- `live.env.save`가 보이면 그 안에 붙여 넣었던 키가 있습니다. 그 내용을 쓰려면 `sudo cp /etc/paperbot/live.env.save /etc/paperbot/live.env`(권한은 live.env 것이 그대로 남음), 그다음 **꼭** `sudo rm -f /etc/paperbot/*.save*`로 지웁니다. 지우지 않으면 10번 점검이 `[고칠 것]`으로 알려 줍니다.
- Secret Key가 어디에도 없으면 바이낸스에서 그 키를 지우고(Delete) 1번부터 새로 만듭니다.

### 4-2. 텔레그램 토큰과 방 번호
1. `live.env`의 `TELEGRAM_BOT_TOKEN=` 뒤에 0-5의 봇 토큰을 붙여 넣고 저장 → 나가기.
2. 방 번호(chat id)를 찾습니다. 토큰을 화면에 띄우지 않고, 봇이 최근에 본 방의 번호와 이름만 보여 주는 명령입니다.
   ```bash
   sudo -u paperbot bash -c 'set -a; . /etc/paperbot/live.env; cd /opt/crypto-bot-research && /opt/paperbot/venv/bin/python -m paperbot.offsite chats'
   ```
   - 결과 예: `방 번호 -1001234567890   이름 우리 알림방   (supergroup)`. 0-5에서 만든 단체방 이름의 줄을 봅니다.
   - 단체방 번호는 **빼기(-)로 시작**합니다(예: `-1001234567890` 또는 `-4123456789`). 빼기 기호까지 그대로 씁니다.
   - "최근 메시지가 없습니다"가 나오면 단체방에 `/start@<봇 아이디>`를 다시 보내고 위 명령을 다시 실행합니다.
3. `sudo nano /etc/paperbot/live.env` → `TELEGRAM_CHAT_CRITICAL=` 뒤에 방 번호 → 저장.
   - `TELEGRAM_CHAT_WARN`, `TELEGRAM_CHAT_INFO`는 비워 둡니다. 비어 있으면 같은 단체방으로 갑니다. INFO(요약)는 무음으로 옵니다.
4. 에이전트 방도 같은 텔레그램을 씁니다. 아래 상자는 `live.env`의 텔레그램 네 줄을 `agents.env`에 그대로 옮깁니다(손으로 다시 칠 필요 없음).
   ```bash
   for k in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_CRITICAL TELEGRAM_CHAT_WARN TELEGRAM_CHAT_INFO; do
     v=$(sudo grep "^$k=" /etc/paperbot/live.env | cut -d= -f2-)
     sudo sed -i "s|^$k=.*|$k=$v|" /etc/paperbot/agents.env
   done
   sudo grep -cE '^TELEGRAM_(BOT_TOKEN|CHAT_CRITICAL)=.+' /etc/paperbot/agents.env
   ```
   - 마지막 줄이 `2`면 됩니다(봇 토큰과 CRITICAL 방이 옮겨짐. WARN·INFO는 비어 있는 것이 맞음). `0`이면 1~3을 다시 확인하고 이 상자를 다시 붙여 넣습니다.

시험 메시지는 10번 최종 점검이 보냅니다.

### 4-3. 서버 밖 백업 방 (텔레그램 'paperbot 백업')
서버 안의 매일 백업은 서버가 사라지면 같이 사라집니다. Vultr 자동 백업 대신(1-5), 매일 09:15에 그 백업을 텔레그램 비공개 단체방으로 한 부 더 보냅니다. 자세한 설명과 되살리는 법은 `docs/offsite-backup.md`에 있습니다.
1. 텔레그램 → 새 그룹 → 다른 한 분과 우리 봇만 넣고 이름을 `paperbot 백업`으로 만듭니다(알림 단체방과 **따로**). 공개 링크는 만들지 않습니다.
2. 그 방에 `/start@<봇 아이디>`를 한 번 보냅니다.
3. 4-2의 2번 명령(`... paperbot.offsite chats`)을 다시 실행해 이름이 **paperbot 백업**인 줄의 번호를 찾습니다. 알림 단체방 번호와 달라야 합니다.
4. 번호를 넣습니다.
   ```bash
   sudo nano /etc/paperbot/live.env
   ```
   맨 아래에 `TELEGRAM_CHAT_BACKUP=<방 번호>` 한 줄을 넣고 저장합니다(이미 `TELEGRAM_CHAT_BACKUP=` 줄이 있으면 그 뒤에 적습니다).
5. 서비스 파일이 설치돼 있는지 봅니다.
   ```bash
   ls /etc/systemd/system/paperbot-offsite.*
   ```
   - `.service`와 `.timer` 두 파일이 보이면 됩니다. `No such file`이 나오면(설치 스크립트가 아직 이 서비스를 설치하지 않는 버전) 아래 상자로 설치합니다. 켜지는 않습니다.
     ```bash
     sudo install -m 644 /opt/crypto-bot-research/deploy/paperbot-offsite.service /opt/crypto-bot-research/deploy/paperbot-offsite.timer /etc/systemd/system/
     sudo systemctl daemon-reload
     ```
- 켜는 것은 11번에서, 첫 시험과 되살리기 연습은 12번에서 합니다.
- 폰 저장 공간을 아끼려면 이 방을 알림 끄기(Mute)하고, 텔레그램의 파일 자동 다운로드를 끕니다(`docs/offsite-backup.md` 3번).
- 암호를 걸고 싶을 때만 `docs/offsite-backup.md` 7번을 봅니다(선택). 암호를 잃으면 백업을 되살릴 수 없습니다.

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
H=$(/opt/paperbot/venv/bin/python -B -m paperbot.dash hash) && \
  sudo sed -i "s|^DASH_PASSWORD_HASH=.*|DASH_PASSWORD_HASH='$H'|" /etc/paperbot/dash.env && echo 비밀번호 저장됨
S=$(openssl rand -hex 32) && \
  sudo sed -i "s|^DASH_SECRET=.*|DASH_SECRET=$S|" /etc/paperbot/dash.env && echo 비밀값 저장됨
sudo awk -F= '/^DASH_(PASSWORD_HASH|SECRET)=/{print $1": "(length($2)>2?"set":"EMPTY")}' /etc/paperbot/dash.env
```
- 마지막에 `DASH_PASSWORD_HASH: set`과 `DASH_SECRET: set` 두 줄이 보이면 됩니다(값 자체는 화면에 내지 않습니다). `EMPTY`가 있으면 상자를 다시 붙여 넣습니다. 해시 모양은 10번 점검이 다시 확인합니다.
- `use at least 12 characters`나 `passwords differ`가 나오면 저장되지 않은 것입니다. 상자를 다시 붙여 넣습니다.
- 해시는 root 화면에서 sudo 없이 만듭니다(`sudo`나 `sudo -u paperbot`을 붙이지 않습니다). Ubuntu 24.04의 sudo는 실행할 때마다 새 터미널을 만들어서, `$( )` 안에서는 비밀번호 입력이 `OSError: [Errno 5] Input/output error`로 실패합니다. 해시 계산만 하고 아무 파일도 쓰지 않습니다(`-B`).
- 손으로 넣을 때: 해시는 `$` 기호가 들어 있으므로 **작은따옴표로 감쌉니다**(`DASH_PASSWORD_HASH='pbkdf2$...'`).
- (선택) 대시보드 글·승인에 이름을 남기려면 `sudo nano /etc/paperbot/dash.env`에서 `#DASH_OWNERS=` 줄의 `#`을 지우고 두 분 이름을 쉼표로 적습니다.

---

## 7. Tailscale (대시보드를 인터넷에 열지 않고 보기)

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```
- `To authenticate, visit:` 뒤의 주소를 폰 브라우저에서 열고, 0-7의 계정으로 로그인해 서버를 승인합니다.
- 브라우저에 다녀오는 사이 접속이 끊겼으면 다시 접속해 `sudo tailscale up`을 한 번 더 실행합니다. 주소가 다시 나오거나, 이미 승인됐으면 바로 끝납니다.

```bash
tailscale ip -4
sudo ufw allow in on tailscale0
IP=$(tailscale ip -4) && [ -n "$IP" ] && sudo sed -i "s|^DASH_HOST=.*|DASH_HOST=$IP|" /etc/paperbot/dash.env
sudo grep '^DASH_HOST=' /etc/paperbot/dash.env
```
- 첫 줄의 `100.x.y.z`가 대시보드 주소입니다. 마지막 줄에 같은 주소가 보이면 됩니다.
- 첫 줄이 `no current Tailscale IPs; state: NeedsLogin`이면 로그인이 끝나지 않은 것입니다(승인을 기다리는 `tailscale up`을 Ctrl+C로 끊으면 이렇게 됩니다). `sudo tailscale up`을 다시 실행해 `Success.`가 나올 때까지 기다린 뒤 이 상자를 다시 붙여 넣습니다. 그 전에는 `DASH_HOST`를 바꾸지 않습니다.
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
   - 주소가 길어 여러 줄로 나뉘어 보여도 한 주소입니다. 끝까지 통째로 복사합니다.
   - 브라우저에 다녀오는 사이 접속이 끊겨 서버 화면이 사라졌으면(4-0의 tmux로도 안 돌아옴) 이 명령을 처음부터 다시 실행합니다.
2. 브라우저에 코드가 나오면 복사해 서버 화면에 붙여 넣고 Enter.
3. 서버 화면에 긴 토큰(`sk-ant-oat01-...`)이 나옵니다. 복사합니다(채팅·메모 앱 금지).
4. 토큰을 넣습니다.
   ```bash
   sudo nano /etc/paperbot/agents.env
   ```
   `CLAUDE_CODE_OAUTH_TOKEN=` 뒤에 붙여 넣고 저장합니다. 화면에서 여러 줄로 나뉘어 보여도 한 줄입니다. 중간에 빈칸이나 줄바꿈이 끼지 않게 붙여 넣습니다(10번 점검이 토큰 모양을 확인합니다).
- 이 토큰은 약 1년 동안 씁니다. 휴대폰 달력에 **11개월 뒤 "Claude 토큰 갱신"** 알림을 넣어 두세요(8-2를 다시 하면 됩니다).

### 8-3. agents.env의 나머지
- 텔레그램 네 줄은 4-2에서 이미 옮겼습니다.
- `AGENTS_BUDGET=` 줄은 두 분이 정한 Max 요금제 한도(하루 200번·토큰 600만, 7일 1,100번·3,000만; 2026-10-03에 160번·900번에서 올림)가 **이미 적혀 있습니다.** 고치지 않습니다. 10월 3일 전에 설치한 서버는 예전 줄이 남아 있으니 13-5의 "AI 한도 줄 바꾸기"를 한 번 합니다.
- `ANTHROPIC_API_KEY`는 **넣지 않습니다.** 넣으면 따로 요금이 나갈 수 있습니다(코드가 지우기는 하지만 넣지 않는 것이 원칙).
- 처음 21일은 관찰 기간입니다(기본값). 따로 적을 것이 없습니다.

### 8-4. 로그인 확인
```bash
sudo -u paperbot -H bash -c 'set -a; . /etc/paperbot/agents.env; set +a; ~/.local/bin/claude --setting-sources "" auth status --json'
```
- `"loggedIn": true`가 있어야 합니다.
- `"apiKeySource"`라는 글자가 **없어야** 합니다. 있으면 API 키로 잡힌 것이니 8-2를 다시 합니다.
- 이 확인을 통과하지 못하면 에이전트는 회의를 열지 않고 멈춥니다(대시보드에 "에이전트 멈춤 (로그인 확인)").
- 이 확인은 토큰이 **들어 있는지만** 봅니다. 토큰이 실제로 되는지는 시작 뒤 첫 회의에서 알 수 있어서, 12번에서 꼭 확인합니다.

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
- 60/60이 아니면 먼저 아직 만드는 중인지 봅니다.
  ```bash
  systemctl is-active paperbot-labbuild
  ```
  - `active`: 아직 만드는 중입니다. 다시 붙여 넣지 말고 기다립니다(진행은 위의 `journalctl` 상자로 봄). 다 만들기 전에는 `check`가 60/60보다 적게 나오고 "개발자에게 보내라"는 영어 줄이 나와도 신경 쓰지 않습니다.
  - `inactive`(끝났는데 60/60이 아님, 또는 `download failed ... run the same command again`이 나옴): 첫 상자(systemd-run)를 **다시 붙여 넣습니다.** 받은 것은 두고 이어서 합니다.
  - `failed`: 먼저 `sudo systemctl reset-failed paperbot-labbuild`, 그다음 첫 상자를 다시 붙여 넣습니다.

자료가 다 되면 에이전트 배관 점검(AI 호출 없음, 실제 기록은 건드리지 않음)을 한 번 합니다.
```bash
cd /opt/crypto-bot-research
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.agents.rooms tick \
  --paper-db /var/lib/paperbot/paper3.db --daily-db /var/lib/paperbot/daily3.db \
  --agents-db /var/lib/paperbot/agents3.db --inbox-db /var/lib/paperbot/inbox.db \
  --lab-dir /var/lib/paperbot/lab --dry-run
```
- 정상인 결과는 두 가지입니다. ① `team:lab research: ... (3 calls)`처럼 회의 이름 줄과 그 아래 `(dry-run)` 줄이 이어지는 회의 기록(새 매매법 연구 회의, 한국 시간 08~12시면 아침 회의, 22~02시면 저녁 점검도), ② `nothing due`. AI를 부르지 않고 연습한 것이라 실제 기록은 바뀌지 않습니다. 기록 안에 "자료가 없습니다" 같은 말이 있어도 연습이라 괜찮습니다.
- `Traceback`이나 `Error`가 들어 있는 줄이 나올 때만 그 화면을 개발자에게 보여 줍니다(키·토큰이 안 보이는지 확인 후).
- 에이전트 명령은 꼭 `sudo -u paperbot`으로 실행합니다. root로 실행하면 root 소유 파일이 생겨 자동 실행이 막힐 수 있습니다.

---

## 10. 시작 전 최종 점검 ([고칠 것]이 없어야 시작)

설치, 설정 파일, 바이낸스 키, 텔레그램, healthchecks, 대시보드, Tailscale, 서버 밖 백업, 에이전트 로그인을 한 번에 점검합니다.
```bash
cd /opt/crypto-bot-research
sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck --stage before --send-test --ping
```
- `--send-test`: 텔레그램 단체방(서버 밖 백업 방 포함)에 시험 메시지를 보냅니다. 왔는지 봅니다.
- `--ping`: healthchecks에 첫 신호를 보냅니다. healthchecks 화면이 회색 "new"에서 초록 "up"으로 바뀌는지 봅니다.

줄마다 앞에 셋 중 하나가 붙습니다.
- `[OK]`: 됐습니다.
- `[고칠 것]`: 시작 전에 고칩니다. 줄 끝에 고치는 방법이 있습니다.
- `[참고]`: 읽어 보기만 합니다. 대개 할 일이 없고, 할 일이 있으면 그 줄에 적혀 있습니다.

**통과 조건:** `[고칠 것]` 줄이 하나도 없고, 맨 아래 결론이 `[OK] 시작 준비가 끝났습니다`로 시작하면 통과입니다. 모든 줄이 `[OK]`일 필요는 없습니다.
- 제대로 준비된 서버에서도 늘 나오는 `[참고]`는 하나입니다: `이제 체크가 켜졌습니다: 약 6분 …`(`--ping`을 붙이면 나옴. 아래 "바로 11번으로"의 이유입니다).
- 4-3을 건너뛰었으면 `서버 밖 백업 …` `[참고]`가 하나 더 나옵니다. 4-3을 하고 이 점검을 다시 합니다.
- 그 밖의 `[참고]`(예: Tailscale 키 만료 날짜, CPU·메모리가 권장보다 적음)는 그 줄을 읽고, 할 일이 적혀 있으면 합니다. 모르겠으면 그 줄을 개발자에게 보여 줍니다.
- `[고칠 것]`이 있으면 해당 단계로 돌아가 고친 뒤 이 점검을 다시 합니다: 바이낸스 키 → 4-1, 텔레그램 → 4-2, 서버 밖 백업 → 4-3, healthchecks → 5, 대시보드 → 6, Tailscale → 7, 에이전트 로그인 → 8, 5년 자료 → 9, 설치·서비스 → 3.
- 에이전트 방(8~9번)이 아직 덜 됐는데 봇부터 켜고 싶으면 끝에 `--agents no`를 붙여 점검합니다. 에이전트 줄은 건너뛰고, 결론의 시작 명령에서도 에이전트 타이머가 빠집니다. 그때는 11번 상자 대신 그 결론 줄의 `시작:` 뒤 명령으로 켜고, 8~9번을 마친 뒤 `sudo systemctl enable --now paperbot-agents.timer paperbot-labmonthly.timer`로 에이전트를 켭니다.
- 결론 줄의 `시작:` 뒤에는 이 서버에 맞춘 시작 명령이 나옵니다. 11번 상자와 같은 것을 켭니다.
- 이 점검이 끝나면 **바로 11번**으로 갑니다. `--ping` 뒤 6분쯤 신호가 없으면 healthchecks가 "down" 알림을 보내기 때문입니다(11번에서 봇이 준비하는 몇 분 동안 "down"이 한 번 올 수 있고, 봇이 돌기 시작하면 "up"이 옵니다).

**시작 시각 팁:** 30일 판정은 시작한 날(UTC 날짜)부터 셉니다. 한국 시간 **오전 9시 이후**에 켜면 첫 30일이 온전합니다. 오전 9시 전에 켜면 첫 기간이 거의 하루 짧아집니다.

---

## 11. 시작 (한 번에 전부 켜기)

```bash
sudo systemctl enable --now \
  paperbot-live3 paperbot-dash paperbot-liq \
  paperbot-daily3.timer paperbot-backup.timer paperbot-checkpoint.timer \
  paperbot-agents.timer paperbot-labmonthly.timer
sudo systemctl enable --now paperbot-offsite.timer paperbot-ghcoin paperbot-tgtrades
sudo systemctl enable --now paperbot-rehearsal.timer
```
- 상자 하나를 통째로 붙여 넣습니다. 둘째 줄(서버 밖 백업)에서 `does not exist`가 나오면 4-3의 5번(설치)을 하고 그 줄만 다시 붙여 넣습니다. 위의 것들은 이미 켜졌습니다. 마지막 줄(판정 미리 연습)에서 `does not exist`가 나오면 설치 스크립트가 아직 그 타이머를 설치하지 않는 버전입니다. 13-5대로 업데이트한 뒤 그 줄만 다시 붙여 넣습니다.

이 상자로 켜지는 것:

| 이름 | 하는 일 |
|---|---|
| `paperbot-live3` | paper 봇 (156개 계좌, 늘 켜짐) |
| `paperbot-dash` | 대시보드 (Tailscale 주소 :8080) |
| `paperbot-liq` | 바이낸스 강제청산 기록 (과거 자료가 없어서 첫날부터) |
| `paperbot-daily3.timer` | 매일 점검, 09:20 |
| `paperbot-backup.timer` | 매일 DB 백업, 08:40 |
| `paperbot-checkpoint.timer` | 30일마다 판정 (매시 35분에 확인만) |
| `paperbot-agents.timer` | 에이전트 방, 15분마다 |
| `paperbot-labmonthly.timer` | 매달 재검사, 6일 03:30 |
| `paperbot-offsite.timer` | 서버 밖 백업, 매일 09:15 (텔레그램 'paperbot 백업' 방) |
| `paperbot-rehearsal.timer` | 판정 미리 연습, 매주 수요일 12:30. 진짜 판정 파일은 건드리지 않고 텔레그램도 보내지 않음(실패할 때만 경고 한 번). 아래 "체크포인트 판정" |
| `paperbot-ghcoin` | GH Coin 타점 기록기 (5분마다, `docs/ghcoin-recorder.md`). paper 계좌와 섞이지 않음 |
| `paperbot-tgtrades` | 텔레그램 거래 알림: 1분마다 그 사이 진입·청산을 한 메시지로 묶어 **무음**으로 (아래 "텔레그램 거래 알림") |

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
- `paper v3 started: 156 accounts, brackets: Binance leverageBracket (live), taker fee 0.0xxx%`
- `brackets:` 뒤가 `Binance leverageBracket (live)`여야 합니다(거래소 실제 값).

### 10~15분 뒤: 최종 점검 (시작 후)
```bash
cd /opt/crypto-bot-research
sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck --stage after
```
- 통과 조건은 10번과 같습니다: `[고칠 것]` 줄이 없고, 맨 아래 결론이 `[OK] 봇이 정상으로 돌고 있습니다`로 시작하면 됩니다.
- 제대로 돌면 `[참고]`는 보통 하나도 없습니다. 봇이 1분봉을 받고 있는지, 봇이 healthchecks에 신호를 보내고 있는지, 강제청산 기록기가 연결돼 있는지도 이 점검이 봅니다.
- 시작한 지 10분이 안 됐으면 `봇이 아직 준비 중입니다`나 `첫 healthchecks.io 핑을 기다리는 중` `[참고]`가 나옵니다. 몇 분 뒤 다시 합니다.
- `[고칠 것]`이 있으면 그 줄의 안내대로 합니다. 모르겠으면 13-7 "문제가 생기면"을 봅니다.

### 15~30분 뒤: 에이전트 첫 회의 (꼭)
8-4의 확인은 토큰이 들어 있는지만 봅니다. 토큰이 실제로 되는지는 첫 회의에서 알 수 있습니다.
```bash
sudo journalctl -u paperbot-agents -n 30 --no-pager
```
- 정상: `team:lab research: done (3 calls) ...`처럼 회의 이름, 결과, `(n calls)`가 있는 줄. 또는 `nothing due`(지금 열 회의가 없음).
- `-- No entries --`면 아직 첫 차례 전입니다(15분마다). 15분 뒤 다시 봅니다.
- `refusing to run the rooms`가 있거나, 줄 끝에 `error=`가 붙어 있으면 대개 Claude 토큰 문제입니다. 8-2(토큰 새로 만들기)와 8-4를 다시 하고 15분 뒤 다시 봅니다. 그래도 같으면 그 화면을 개발자에게 보여 줍니다.

### 서버 밖 백업 첫 시험 (한 번)
```bash
sudo systemctl start paperbot-backup
sudo systemctl start paperbot-offsite
systemctl status paperbot-offsite --no-pager
```
- 끝날 때까지 몇 초~몇 분 걸립니다. `status=0/SUCCESS`가 보이고 'paperbot 백업' 방에 조각 파일과 목록 파일·요약이 오면 성공입니다.
- `status=1/FAILURE`면 `sudo journalctl -u paperbot-offsite -n 50 --no-pager`로 이유를 보고 `docs/offsite-backup.md` 8번 표를 봅니다.
- 처음 한 번은 되살리기 연습(`docs/offsite-backup.md` 9번 "연습")도 합니다. 백업은 되살려 봐야 믿을 수 있습니다.

### 대시보드
1. 폰에서 Tailscale 앱을 켜고 `http://100.x.y.z:8080`을 열어 6번의 비밀번호로 들어갑니다. **PC에서 보려면** PC에도 Tailscale을 설치하고(tailscale.com/download, 같은 계정으로 로그인) PC 브라우저에서 같은 주소를 엽니다.
2. **서버 상태** 탭:
   - 봇 생존 신호: **정상**
   - 계좌: **156**, "새로 시작"
   - 수수료(편도): 계정 실제 수수료율
   - 레버리지 구간: **거래소 실제 값** ("예시 표"면 안 됩니다)
3. 위쪽 표시: "봇 실시간", "바이낸스 시세". 15분 안에 에이전트 표시가 "자동 토론 대기" 또는 "자동 토론 중"으로 바뀝니다.
4. 화면 안내 (가상 계좌라 주문 버튼은 어디에도 없습니다):
   - **트레이드**: 이 코인의 열린 포지션마다 진입가에 가는 선이 있고, 선 위에 "롱 20배 +0.4% +$3"처럼 실시간 수익률과 금액이 붙습니다(수익이면 초록, 손실이면 빨강). 진입가가 거의 같은 포지션은 한 선으로 묶여 "3개 롱2·숏1 합계 +$12"로 나옵니다. "포지션 선" 버튼으로 끄고 켭니다. 위 메뉴에서 계좌를 고르면 그 계좌의 진입·청산 표시와 손절·청산가 선이 나오고, 차트도 그 계좌의 봉으로 바뀝니다. 아래 포지션 표의 "차트"·"매매법" 버튼은 그 계좌 차트, 그 매매법 화면으로 바로 갑니다.
   - **지지·저항** 버튼: 가까운 지지(초록)·저항(빨강) 선을 위아래 3개씩. 봇이 신호마다 기록하는 것과 같은 정의(스윙 고점·저점, 전날·지난주 고가·저가, 라운드 넘버, 매물대, 상위 봉 스윙)입니다. 진입 연구에서 수익과 관계없다고 나온 설명용 선입니다. 일봉에는 없습니다.
   - **GH Coin 타점** 버튼: GH Coin 기록기의 지금 계획(진입·손절·익절1·익절2). 계획이 대기·관망이면 선이 없거나 "대기"로 표시됩니다.
   - **경제지표** 버튼(기본 켜짐): 미국 경제지표 발표(CPI·FOMC·고용·PCE)가 있었던 봉 위에 작은 네모와 이름. `data/macro_events.csv`에 등록된 것만 보이고, 파일을 고치면 재시작 없이 30초 안에 반영됩니다.
   - 위쪽 "지금 시간대": 아시아·유럽·미국장·새벽(한국 시각), 주말, 미국 증시 개장까지 남은 시간.
   - 왼쪽 아래: **GH Coin 판단**(6개 코인의 지금 판단·확신·보조지표 종합 평가(4시간봉), 누르면 그 코인 차트에 GH Coin 선. 기록기는 1시간·4시간봉마다 GH Coin의 패턴 판단을 `/var/lib/paperbot/ghcoin/patterns.jsonl`에 쌓아 나중의 패턴 연구에 씁니다) / **오늘·일정**(오늘 청산·손익·강제청산, 다음 펀딩, 미국 증시 개장·마감, 등록된 미국 경제발표, 다음 판정일).
   - 오른쪽 아래: **호가**(차트 코인의 위아래 8개 호가와 매수/매도 비율) / **시장 강제청산**(바이낸스 전체에서 최근 1시간 이 코인의 롱·숏 강제청산 금액과 최근 12건, 강제청산 기록기 자료).
   - **매매법** 탭: 왼쪽 목록에 매매법마다 실전 "35승 14패 · 71%", 오른쪽 봉 계좌 칸마다 승·패·승률, 그 아래 "실전 기록 (봉 합계)"에 승률·손익·평균 이익·평균 손실·손익비(평균 이익 ÷ 평균 손실). 아래쪽 "과거 5년" 표의 승률은 백테스트 값입니다. **순위표**의 승률 칸에도 "14승 2패"가 붙습니다. 30일 동안은 거래 수가 적어 승률이 크게 흔들리니, 판정은 30일째 체크포인트(동전 봇과 비교)로 합니다.
   - **가격 알림** (트레이드 오른쪽 아래 "가격 알림" 칸): 지금 코인의 가격을 적고 "알림 걸기"를 누르면, 그 가격에 닿을 때 텔레그램으로 **소리 있는** 알림이 옵니다. 지금보다 높게 적으면 오를 때, 낮게 적으면 내릴 때 울립니다. 한 번 울리면 꺼지고("다시 켜기"로 다시 켬), 걸어 둔 가격은 차트에 "🔔 알림" 점선으로 보입니다. 50개까지. 보내는 일은 `paperbot-tgtrades`가 10초마다 확인해서 합니다(꺼져 있으면 칸에 빨간 안내가 나옵니다).
   - **마켓** 탭: 공포·탐욕 지수(오늘·어제·1주 전), 비트코인·이더리움 도미넌스와 코인 전체 시가총액, 나스닥·S&P 500·달러 지수·미국 10년 금리(5일 흐름), 미국 경제발표 일정(`data/macro_events.csv`에 등록된 것). 바깥 무료 자료라 늦거나 빌 수 있고, 매매에는 쓰이지 않습니다.
   - **회의실** 탭 (에이전트 방 옆): 에이전트 방을 사무실 그림 하나로 봅니다. 팀 방 5개(시장분석팀·리스크팀·운영·검증팀·손익 복기팀·총괄)와 새 매매법 연구실은 칸마다, 매매법 방 36개는 "공용 회의실" 한 칸에 모았습니다(회의 중인 매매법 방이 거기 나오고, 회의가 없으면 최근 매매법 방 회의 3개를 누를 수 있게 보여 줌). 직원은 팀 색깔의 작은 그림이고, 매매법 전담은 같은 모양에 매매법 이름표를 답니다.
     - 회의가 열려 있으면 그 방 직원들이 회의 탁자로 걸어가 앉고, 방금 말한 직원은 빛나며 그 아래 말풍선에 **실제로 남긴 말의 첫 문장**이 나옵니다. 회의 순서상 다음 차례가 분명하면 그 직원 위에 "💭 생각 중"이 뜹니다(다음 차례가 앞 사람 답에 달려 있으면 띄우지 않음). 다른 방 회의에 들어간 직원은 자기 자리에서 흐리게 보입니다.
     - 말풍선은 회의 기록(agents3.db)에 저장된 말이라, 직원 한 명의 AI 차례가 끝나야 바뀝니다(실시간 타이핑이 아님). 화면은 이 탭을 보고 있을 때만 6초마다 새로 읽습니다.
     - 회의가 없으면 모두 자기 책상에 앉아 있고, 위에 "지금 회의 없음 · 다음 정기 회의 HH:MM"이 나옵니다. 시각은 에이전트가 마지막으로 쓴 회의 시각(`agents.env`의 `AGENTS_*_HOUR`)을 그대로 따릅니다.
     - 오른쪽(폰에서는 아래)에는 지금 회의의 발언 순서와 각자의 첫 문장, 오늘 끝난 회의(결정 한 줄, 발언한 직원 순서), 오늘 회의 수·AI 호출 수. 칸이나 회의를 누르면 '에이전트 방'에서 그 방 대화가 열립니다.
   - **회의 요약** 탭 (에이전트 방 옆, 모두 코드가 정리한 숫자):
     - **회의 결론**: 하루(←·→로 날짜 이동) 동안 열린 회의를 한 화면에. 회의마다 방·종류·결과, 왜 열렸는지, 팀장 세 줄, 갈린 의견, 결론 요약, 누가 누구에게 동의·반대했는지, 직원이 물은 질문, 시험 결과. "방 열기"로 그 방 대화로 갑니다.
     - **직원 성적표**: 직원마다 최근 1·7·30일 발언 수, 회의 수, 반응(동의·반대·보완), 받은 반대, 질문, 사실·가설 수, 못 읽은 답, 제안 종류, 그리고 실험 전체의 **예측 채점**(가설에 붙인 예측이 나중 거래로 맞았는지: 맞음/채점, 적중률). 아래에 최근 채점된 예측.
     - **주간 성적표**: 최근 7일 매매법 계좌 손익·거래·승률(지난주 대비), 같은 봉 동전 봇 중간값보다 나은 계좌 수, 상위·하위 5개(순위 변화 ▲▼), 봉별 합계, 직원의 한 주(회의·AI·가설·예측·시험), 그리고 일요일 21:00에 텔레그램으로 갈 글 미리보기.
     - **봉 비교**: 매매법마다 4개 봉 계좌(15분·30분·1시간·4시간)의 손익·거래·승률을 나란히, 봉끼리 크게 갈린 것은 "봉마다 갈림". "자세히"는 봉별 비용 전 가격 움직임·거래당 비용·비용 ÷ 손익 크기·보유 시간·롱숏·청산 이유.
   - **포지션** 탭: 거래소 앱의 포지션 화면처럼 계좌마다 미실현 손익(USDT)·ROI·크기·증거금·진입가·마크 가격·청산가·청산까지 거리·손절에 닿으면 손익·익절 잠금 단계. 위쪽 합계(전체 미실현 손익, 수익 중/손실 중, 가장 많이 먹는/잃는 계좌), 코인을 고르면 호가창과 매수/매도 비율. "손절·잠금 주문" 탭은 걸려 있는 손절 가격, "오늘 체결"은 오늘(한국 0시 이후) 청산. 미실현 손익은 바이낸스 앱처럼 마크 가격 기준·나갈 때 수수료 전입니다.

### healthchecks
- 체크가 초록 **up**인지 봅니다. 회색 "new"면 감시가 시작되지 않은 것입니다(봇이 아직 1분봉을 처리하지 않음). 30분 넘게 회색이면 "문제가 생기면"을 봅니다.

### 나머지 (선택, 한 번만)
```bash
cd /opt/crypto-bot-research
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.live3 status --db /var/lib/paperbot/paper3.db
systemctl list-timers 'paperbot-*' --no-pager
```
- 첫 줄: `accounts 156, open positions ..., bust 0` 모양.
- 둘째: 타이머 7개(매일 점검, 백업, 서버 밖 백업, 판정, 판정 미리 연습, 에이전트, 매달 재검사)와 다음 실행 시각.

---

## 13. 그다음: 매일·매주, 30일째, 업데이트, 백업, 고장

### 13-1. 하루 동안 오는 것 (한국 시간)

| 시각 | 무엇 | 어디서 |
|---|---|---|
| 08:00 | 시장분석팀 아침 회의 → 팀장 세 줄 요약 | 텔레그램 **무음** + 에이전트 방 |
| 08:40 | DB 백업 (조용히) | 서버 `/var/backups/paperbot/` |
| 09:15 | 서버 밖 백업: 위 백업을 묶어서 보냄 + 요약 | 텔레그램 'paperbot 백업' 방 **무음** |
| 09:20 | 매일 점검 요약: `[날짜] 매일 점검: 재계산 일치 n/n · 거래 n건 · ...` | 텔레그램 **무음** |
| 11:00 (월~토, 일요일 빼고) | 요일별 분석 회의: 월 비용·체결(운영·검증팀), 화 조합·동시 손실(리스크팀), 수 코인·장세(손익 복기팀), 목 손익비·청산(손익 복기팀), 금 낙폭·파산 위험·백테스트 차이(리스크팀), 토 학습 정리(총괄). 자료가 모자라면(지난 7일 거래 200건 미만, 시작 뒤 7일 전) 열지 않음. 새 거래가 많이 쌓인 주에는 다른 날 11:00에 한 번 더(주 2번까지) | 에이전트 방 |
| 11:00 (발표 다음 날) | 경제지표 복기: 미국 발표(CPI·FOMC·고용·PCE) 전후 우리 계좌의 반응 | 에이전트 방(시장분석팀) |
| 12:00 | 낙관·비관 토론: 코인 하나의 앞으로 24시간(상승·하락·중립 판정을 코드가 24시간 뒤 채점, 거래 없음) | 에이전트 방(시장분석팀) |
| 14:00 | 순위 검토: 성과 분석가가 순위 숫자 정리 → 잔고 상위 3·하위 3 매매법(이긴 거래 vs 진 거래 비교) → 순위 숫자 + 팀장 세 줄 | 텔레그램 **무음** + 에이전트 방(손익 복기팀) |
| 18:00 | 봉 비교 회의: 봉마다 성적이 정반대로 갈린 매매법(최대 2개, 같은 매매법은 3일에 한 번)의 방에서 전담이 이유 분석, 봉 비교 분석가가 다른 매매법의 같은 봉 패턴과 비교 | 에이전트 방(그 매매법 방), 대시보드 '회의 요약 → 봉 비교' |
| 22:00 | 손익 복기팀 → 총괄 세 줄 요약 | 텔레그램 **무음** + 에이전트 방 |
| 1분마다 (있을 때만) | 거래 알림: 그 1분 동안의 진입·청산을 한 메시지로 (진입가·배수·손절, 청산 손익·이유) | 텔레그램 **무음** |

**텔레그램 거래 알림** (`paperbot-tgtrades`, `paperbot/tradealerts.py`): 거래가 하루 수백 건이라 건별로 보내면 폰이 쉬지 않고 울립니다. 그래서 1분마다 그 사이 진입·청산을 **한 메시지로 묶어 무음**으로 보냅니다(새 거래가 없으면 안 보냄). 한 메시지에 진입·청산 각각 큰 것부터 20건까지, 나머지는 "외 n건". 강제청산은 지금처럼 따로 **소리**로도 옵니다. 바꾸려면 `sudo nano /etc/paperbot/live.env`에 아래 줄을 넣고 `sudo systemctl restart paperbot-tgtrades`:
- `TRADE_ALERTS=strategy` (기본: 매매법·복제·새 매매법 계좌) / `all` (동전 봇까지) / `off` (끔)
- `TRADE_ALERTS_EVERY=300` (5분마다 묶기; 기본 60초)
- `TRADE_ALERTS_MIN_USD=50` (손익 $50 미만 청산은 개수만 세고 목록에서 뺌)

수시로 오는 알림(보충 규칙 Q9):

| 종류 | 받는 방법 |
|---|---|
| 봇·데이터 5분 넘게 멈춤 | healthchecks → **두 분 폰** |
| 강제청산, 재계산 불일치 | 텔레그램 **소리** |
| 재계산 차이가 모두 "1분봉을 확정 전에 읽음"으로 확인된 날 | 텔레그램 ⚠ **소리** 한 번 (회의는 열리지 않음) |
| 빠진 1분봉, 신호 계산 멈춤, 재시작 때 체결·청산·사이즈 코드 변경 | 텔레그램 **소리** |
| 파산, 낙폭 −20/−30/−40% | 1시간에 한 번 묶어서 텔레그램 **무음** |
| 직원들이 스스로 보내는 알림 | 하루 3번까지 |

매일 아침 30초: 09:20 메시지의 **재계산 일치 n/n**이 모두 일치인지 봅니다. 다르면 소리 알림이 따로 오고, 운영·검증팀 회의가 저절로 열립니다. `재계산 일치 150/156 (확정 전 1분봉 7)`처럼 괄호가 붙으면, 그 계좌들은 계산 오류가 아니라 봇이 1분봉을 확정 전에 읽은 것으로 확인된 것입니다(13-7).

### 13-2. 일주일에 한 번 (5분)
일요일 21:00에 텔레그램(무음)으로 **주간 성적표**가 옵니다(코드 계산, AI 없음): 최근 7일 매매법 계좌 손익·승률(지난주 대비), 동전 봇 중간값보다 나은 계좌 수, 낙폭 한 줄(이번 주 가장 깊게 내려간 매매법 3개, 5년 시험보다 유의하게 나쁜 매매법 수), 상위·하위 5개와 순위 변화, 봉별 합계, 직원의 한 주(회의·AI 호출·가설·예측 채점·5년 시험). 대시보드 '회의 요약 → 주간 성적표'에서 언제든 같은 숫자를 봅니다. 끄려면 `/etc/paperbot/agents.env`에 `AGENTS_WEEKLY_REPORT_HOUR=off`.

```bash
systemctl --failed --no-pager
ls /var/backups/paperbot
df -h /
```
- 첫 줄이 `0 loaded units listed`면 정상입니다. 판정·판정 미리 연습·매일 점검·매달 재검사·에이전트 작업이 실패하면 텔레그램 경고 `⚠ [작업 실패] …`가 작업마다 하루 한 번 오고, 여기에도 남습니다. 서버 안 백업이 실패하면 09:15의 "서버 밖 백업 실패 …" 경고로 알게 됩니다. 나오면 13-7을 봅니다.
- 둘째: 최근 날짜 폴더(`20261008` 모양)가 있어야 합니다. 14일치가 남습니다.
- 셋째: 사용률(Use%)이 80% 밑이면 됩니다.
- healthchecks가 초록인지, 텔레그램 'paperbot 백업' 방에 매일 아침 요약이 왔는지(날짜가 이어지는지) 봅니다. 서버 밖 백업이 실패한 날은 알림 단체방에도 "서버 밖 백업 실패 …"가 옵니다(`docs/offsite-backup.md` 8번).
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
- `git fetch`·`git pull`은 2번에서 저장한 GitHub 토큰을 씁니다. `Authentication failed`가 나오면 토큰이 만료된 것입니다: 0-3대로 새 토큰을 만들고 같은 명령을 한 번 더 실행해 새 토큰을 넣습니다.
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
- **피할 시간:** 매일 08:30~09:40(백업·서버 밖 백업·매일 점검), 판정일 09:30~10:30, 매달 6일 03:00~07:00(매달 재검사), 매주 수요일 12:30~13:30(판정 미리 연습). 업데이트가 이 작업들을 멈추지 않아서, 도는 중에 코드가 바뀔 수 있습니다.
- 설치 스크립트가 `Could not get lock`으로 멈추면 서버가 자동 보안 업데이트를 하는 중입니다. 5~10분 뒤 같은 명령을 다시 실행합니다.
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
- **판정 미리 연습 타이머 켜기** (10월 4일 전에 설치한 서버, 업데이트 뒤 한 번만): 설치 스크립트는 새 타이머를 설치만 하고 켜지 않습니다(끝에 "weekly checkpoint rehearsal installed but off"가 보임). 아래 한 줄로 켜고, 다음 줄로 확인합니다(`Wed ... 03:30:00 UTC`가 보이면 됨).
  ```bash
  sudo systemctl enable --now paperbot-rehearsal.timer
  systemctl list-timers paperbot-rehearsal.timer --no-pager
  ```
  바로 한 번 돌려 보려면 `sudo systemctl start paperbot-rehearsal` (수 분~수십 분, 끝날 때까지 기다림). 결과는 아래 "체크포인트 판정"의 "매주 미리 연습"대로 봅니다.
- **AI 한도 줄 바꾸기** (10월 3일 전에 설치한 서버, 한 번만): 설치 스크립트는 이미 있는 `/etc/paperbot/agents.env`를 덮어쓰지 않으므로, 새 한도 줄은 직접 바꿉니다. 먼저 지금 줄을 봅니다:
  ```bash
  sudo grep -n '^AGENTS_BUDGET' /etc/paperbot/agents.env
  ```
  `loss=48:1400000`이 들어간 예전 줄이 나오면 아래 한 줄로 새 줄로 바꾸고 확인합니다(다음 에이전트 차례부터 적용, 재시작 필요 없음):
  ```bash
  sudo sed -i 's/^AGENTS_BUDGET=.*/AGENTS_BUDGET=incident=30:1000000,owner=40:1400000,loss=64:2600000,scheduled=30:1200000,weekly=40:1600000,research=48:1600000,total=200:6000000,week=1100:30000000/' /etc/paperbot/agents.env
  sudo grep -n '^AGENTS_BUDGET' /etc/paperbot/agents.env
  ```
  며칠 뒤 Claude 앱의 사용량 화면에서 주간 사용량이 너무 빨리 오르면(두 분 채팅이 막힐 정도) 숫자를 낮춥니다. 오늘 어느 회의 몫을 얼마나 썼는지는 대시보드 '에이전트 방'의 방 정보(오른쪽) "오늘 AI 사용"에 나옵니다.

### 13-6. 백업 (보충 규칙 Q10, Vultr 자동 백업 대신 텔레그램)
- **서버 안, 매일:** 08:40 `/var/backups/paperbot/<날짜>/`에 14일치. agents3(가설 장부), inbox(두 분 글·승인), liq(강제청산), checkpoint(판정), daily3(매일 점검), paper3(계좌). 실거래 기록(exec)이 생기면 그것도.
- **서버 밖, 매일:** 09:15 위 백업을 묶어서 텔레그램 'paperbot 백업' 방으로 보냅니다(4-3, `docs/offsite-backup.md`). 두 분은 비용 때문에 Vultr 자동 백업을 켜지 않았습니다(1-5). 그래서 서버가 사라지면 이 텔레그램 사본이 유일한 사본입니다.
- **DB 하나를 되살릴 때:** 순서를 꼭 지켜야 파일이 깨지지 않습니다. `docs/agent-rooms.md`의 "데이터베이스를 백업에서 되살릴 때"를 따릅니다. 거기 적힌 것 외에, `liq.db`를 되살릴 때는 `paperbot-liq`도, `checkpoint.db`를 되살릴 때는 `paperbot-checkpoint.timer paperbot-checkpoint.service`도 먼저 멈춥니다.
- **서버를 통째로 잃었을 때:** `docs/offsite-backup.md` 9번 "새 서버에 되살리기"를 따릅니다. 새 서버를 1~9번대로 만들고(9번 5년 자료 포함), 텔레그램에서 마지막 백업을 내려받아 DB를 되살린 뒤 11번으로 켜고 12번으로 확인합니다. **10번(시작 전 점검)은 하지 않습니다:** 되살린 paper3.db를 "예전 시작 기록"으로 보고 옮기라는 줄이 나오는데, 따르면 되살린 기록이 빠집니다. 마지막 백업(08:40) 뒤의 기록은 없습니다(최대 하루). 봇은 백업 시점의 상태에서 이어서 돌고, 꺼져 있던 동안의 신호는 "늦음"으로 기록만 됩니다. 에이전트의 AI 사용 기록도 그 시점으로 돌아가므로, 그날은 `sudo systemctl stop paperbot-agents.timer`로 에이전트를 쉬게 하고 다음 날 `sudo systemctl start paperbot-agents.timer`로 켭니다(`docs/agent-rooms.md`). 되살린 뒤 12번 확인을 다시 하고(그날 쉬게 한 `paperbot-agents.timer: 꺼져 있음` 줄은 따르지 않습니다) 개발자에게 알립니다.

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
- 설정된 방마다 시험 메시지를 보내 봅니다(토큰은 화면에 나오지 않음).
  ```bash
  cd /opt/crypto-bot-research
  sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck --stage after --send-test
  ```
- `텔레그램` 칸의 줄이 모두 `[OK] 시험 메시지 보냄`이고 단체방에 메시지가 오면 정상입니다.
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

**대시보드에 "에이전트 멈춤 (AI 응답 없음 n시간)"**
- 에이전트 순번은 돌지만 직원들의 AI 호출이 6시간 넘게 모두 실패하고 있습니다(Claude 토큰 만료·취소, 서버에서 Claude로 연결 안 됨). 8-2와 8-4를 다시 합니다. 그래도 그대로면 위 "에이전트 멈춤 (오류)"의 두 명령 화면을 개발자에게. 두 분의 승인·거절은 그동안에도 코드가 반영합니다.

**텔레그램 "재계산 불일치" (🚨 소리)**
- 봇은 그대로 둡니다. 운영·검증팀 회의가 저절로 열립니다. 메시지 내용을 개발자에게 알립니다.
- 매일 점검(09:20)은 paper 거래를 다음 날 완성된 1분봉으로 다시 계산해 비교합니다. 이 알림은 이유를 확인하지 **못한** 계좌가 있다는 뜻입니다. 끝에 "(그 밖에 n개는 '1분봉을 확정 전에 읽음'으로 확인됨)"이 붙어 있으면 그 n개는 아래 ⚠ 경우이고, 나머지만 살펴보면 됩니다.

**텔레그램 "재계산 차이 n개 계좌: 모두 '1분봉을 확정 전에 읽음'으로 확인됨" (⚠ 소리)**
- 고장이 아닙니다. 할 일이 없고, 회의도 열리지 않습니다.
- 뜻: 봇이 1분이 끝나자마자 바이낸스 1분봉을 읽었는데, 그 순간에는 그 1분의 마지막 거래가 아직 봉에 들어가 있지 않았습니다. 그래서 paper는 손절·잠금을 몇 분 늦게 했고, 완성된 봉으로 다시 계산한 쪽은 그 1분 안에 했습니다. 매일 점검이 봇이 쓴 1분봉 기록(`paper3.db`의 `live_bars`) 또는 바이낸스 체결 기록으로 확인했을 때만 이 메시지가 옵니다. 확인하지 못하면 위 🚨 "재계산 불일치"로 옵니다.
- 자세한 이유와 고칠 계획(1분봉을 마감 몇 초 뒤에 읽기, 규칙 Q5 때문에 두 분이 시기를 정함): `docs/signal-recording.md`의 "1분봉을 확정 전에 읽는 문제". 같은 날 여러 번, 또는 며칠 연속 오면 개발자에게 알립니다(고치는 시기를 앞당길지 판단 자료).
- 계좌별 표시와 증거는 `daily3.db`의 `mismatches`에 있습니다(에이전트 회의 자료에도 표시가 같이 갑니다).

**지난 날짜의 매일 점검을 다시 돌리기** (예: 2026-10-03의 불일치에 새 표시를 붙일 때, 개발자가 요청할 때)
- 새 코드를 배포(13-5)한 뒤, 매일 점검이 도는 08:30~09:40(한국 시간)을 피해서:
  ```bash
  sudo -u paperbot bash -c 'set -a; . /etc/paperbot/live.env; cd /opt/crypto-bot-research && /opt/paperbot/venv/bin/python -m paperbot.daily3 run --db /var/lib/paperbot/paper3.db --out /var/lib/paperbot/daily3.db --day 2026-10-03'
  ```
- 몇 분 걸립니다. 그날의 보고서와 `mismatches`를 새로 지우고 다시 씁니다(다른 날짜는 그대로). 텔레그램에 그날 결과가 한 번 더 옵니다(⚠ 또는 🚨, 그리고 무음 요약). 텔레그램 없이 하려면 끝에 ` --no-notify`를 붙입니다. 지난 날짜를 다시 점검해도 운영·검증팀 회의는 다시 열리지 않습니다.
- 결과 보기(읽기만 함):
  ```bash
  sudo -u paperbot /opt/paperbot/venv/bin/python - <<'EOF'
  import json, sqlite3
  c = sqlite3.connect("file:/var/lib/paperbot/daily3.db?mode=ro", uri=True)
  day = "2026-10-03"
  print(json.loads(c.execute("SELECT data FROM reports WHERE day = ?", (day,)).fetchone()[0])["parity"])
  for aid, d in c.execute("SELECT account_id, data FROM mismatches WHERE day = ?", (day,)):
      m = json.loads(d)
      print(aid, "|", m.get("label", "이유 확인 못 함"), "|", (m.get("early_kline_check") or {}).get("failed", ""))
  EOF
  ```
  `early_kline (거래소 1분봉 확정 전 읽음)`이 붙은 계좌는 확인된 것이고, 그 밖의 줄은 이유(`failed`)와 함께 개발자에게 보냅니다.

**텔레그램 `⚠ [작업 실패] …` (소리) 또는 `systemctl --failed`에 무언가 있음**
```bash
sudo journalctl -u <그 이름> -n 50 --no-pager
```
- 경고에 작업 이름(`paperbot-checkpoint.service` 같은)과 위 명령이 그대로 적혀 옵니다. 같은 작업은 하루(한국 날짜)에 한 번만 알립니다. 봇(계좌 156개)은 그대로 돕니다.
- 백업·매일 점검은 대개 일시적인 네트워크 문제이고 다음 날 다시 돕니다. 이틀 연속이면 개발자에게.
- 판정(`paperbot-checkpoint`)은 매시 35분에 다시 시도합니다. 판정일(첫 판정 11/1)에 오면 화면을 바로 개발자에게 보냅니다.
- 에이전트(`paperbot-agents`)이고 "Claude 로그인 확인 거부"가 적혀 있으면 8-2와 8-4를 다시 합니다. 그 밖이면 화면을 개발자에게.
- 확인한 뒤 `sudo systemctl reset-failed`로 목록을 비웁니다.

**텔레그램 "신호 계산이 …초 안에 끝나지 않아 … 신호를 건너뜀" 또는 "1분봉 빠짐 …" (소리)**
- 봇은 계속 돕니다. 그 봉(또는 그 1분)의 신호만 빠집니다. 한두 번은 서버가 잠깐 바빴거나(판정 계산·5년 시험과 겹침) 바이낸스 쪽이 늦은 것이라 그대로 둡니다.
- 하루에 여러 번 오면 `sudo journalctl -u paperbot-live3 -n 50 --no-pager` 화면을 개발자에게 보냅니다.

**디스크가 거의 참 (`df -h /` 80% 넘음)**
- 개발자에게 알립니다. 파일을 직접 지우지 않습니다.

---

## 처음부터 다시 시작 (두 분 결정 2026-10-04, 한 번만)
1분봉을 확정 전에 읽던 문제(`docs/signal-recording.md`)를 고치고 **5분봉을 실험에서 빼면서**(`docs/paper-v3-rules-change-1.md`: 5년 자료 거래당 −2.3%, 36칸 중 34칸 유의한 손실) 실험을 처음부터 다시 시작합니다. 이번이 마지막 재시작이고, 새 시작부터 30일 동안 규칙과 매매 코드는 그대로 둡니다. 08:30~09:40(KST)은 피합니다.
1. 측정 결과 확인: `cat /root/kline_probe.txt` (마감 뒤 몇 초에 읽어야 안전한지. 5초보다 길게 나오면 개발자에게 먼저 보냅니다)
2. 코드 받기: `cd /root/crypto-bot-research && git pull`
3. 다시 시작: `sudo bash deploy/paperbot-reset.sh --yes`
   - 봇·대시보드·알림·예약 작업을 멈추고(돌고 있는 밤 작업은 끝날 때까지 기다림), 이전 실행의 `paper3.db`·`daily3.db`·`checkpoint.db`·`agents3.db`·`inbox.db`·`tradealerts.json` 등을 **지우지 않고** `/var/lib/paperbot/archive/run-<시각>/`으로 옮깁니다.
   - 코드를 설치하고(`deploy/install.sh`), 멈췄던 것을 다시 켭니다. 봇이 $5,000 계좌 **156개**(매매법 36개 × 15분·30분·1시간·4시간 = 144개 + 동전 던지기 봇 봉마다 3개 = 12개, 5분봉 없음)를 새로 만들고 그 시각이 새 시작입니다. 30일 판정과 관찰 기간(21일)은 시작에서 저절로 계산됩니다.
   - 청산·시장·GH Coin 기록, 설정 파일(`/etc/paperbot`), 주문 실행기와 키, 백업은 건드리지 않습니다.
   - 대시보드에서 걸어 둔 가격 알림과 직원에게 남긴 글은 이전 실행과 함께 보관되므로, 필요하면 다시 걸어 둡니다.
4. 5분 뒤 점검: `sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.launchcheck after`. "계좌 156개"가 나와야 합니다. paper3.db에 5분봉 계좌가 있으면(이전 실행의 DB가 그대로 남은 것) '고칠 것'으로 나옵니다.

## 운영

| 일 | 방법 |
|---|---|
| 전체 상태 | `systemctl list-units 'paperbot-*' --no-pager`, 타이머: `systemctl list-timers 'paperbot-*' --no-pager`, 실패한 것: `systemctl --failed --no-pager` |
| 재시작 | `sudo systemctl restart paperbot-live3`. 계좌 상태는 저장돼 있어 이어서 돕니다. 꺼져 있던 동안의 신호는 "늦음"으로 기록만 됩니다 |
| 매일 점검 | 09:20(한국 시간)에 자동. paper와 재계산 일치, 지정가·놓친 신호 그림자 기록, 데이터 품질. 불일치마다 "1분봉을 확정 전에 읽음"인지 증거로 확인(봇이 쓴 1분봉 기록 `paper3.db` `live_bars`, 없으면 바이낸스 체결 기록). 지난 날짜 다시 돌리기는 13-7 |
| 손절 체결 추정 (매일 점검) | 그날 손절·잠금·강제청산으로 끝난 거래마다, 실제 거래소의 손절 주문(STOP_MARKET, 마지막 체결가 기준)이었다면 얼마에 체결됐을지 바이낸스 공개 체결 기록으로 추정합니다: 손절가를 처음 넘은 체결(발동)부터 5초 동안의 체결을 거래 크기만큼 따라가고, 그 청산의 호가창 기록(`fill_costs`)이 있으면 그것도 봅니다. paper는 손절가에 0.02%(2bp)만 붙여 체결하므로, 거래마다 paper 가정과 실제 추정(bp, $)을 `daily3.db`의 `stop_slips`에 적고, 보고서 `stop_slippage`에 매매법·봉·코인별 중간값·상위 10%·최악·paper보다 더 든 $ 합계를 냅니다. 09:20 요약 끝에 `손절 체결 추정 n건: 중간 x bp(paper y bp), paper보다 $z`. 기록일 뿐 모의 체결·판정은 바뀌지 않습니다. 바이낸스 요청은 밤마다 상한(코인·분 150개, 600쪽)이 있고, 실패해도 매일 점검은 끝까지 돕니다(그 거래는 `api_error`로 표시) |
| 체크포인트 판정 | 시작 후 30·60·90…일째 09:00(한국 시간) 기준. 매시 35분에 확인하고, 판정할 날이면 약 10분 계산한 뒤 텔레그램(무음)과 대시보드 순위표에 결과. 아래 "체크포인트 판정" 참고 |
| 체결 비용 기록 | 모의 거래가 진입·청산할 때마다 그 코인의 호가창(양쪽 100칸)을 받아, 같은 크기의 시장가 주문이 실제로 얼마에 체결됐을지 `paper3.db`의 `fill_costs`에 적습니다(`paperbot/fillcost.py`). 모의 체결 자체는 바꾸지 않습니다(엔진은 늘 0.02%로 계산). 매일 점검 보고서의 `fill_costs`에 코인별 중간값·상위 10%·0.02%를 넘은 횟수가 나옵니다. `size_costs`에는 같은 기록으로 주문이 2·5·10배였다면의 슬리피지가 코인·봉별로 나옵니다. 지금 기록은 호가 칸 자체를 저장하지 않아서, 같은 순간의 다른 주문으로 알 수 있는 범위만 나오고(나머지는 `not_recorded`), 기록된 호가 100칸으로 그 크기를 못 채우면 `too_thin`입니다 |
| 판정 미리 연습 | 매주 수요일 12:30(한국 시간) 자동. 아래 "체크포인트 판정"의 "매주 미리 연습" |
| 청산 기록 | `paperbot-liq`가 바이낸스 강제청산 흐름을 `liq.db`에 모읍니다(공개 자료, 키 필요 없음). 바이낸스는 청산의 과거 자료를 주지 않아서 첫날부터 켜 둡니다. 확인: `cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.liqstream status --db /var/lib/paperbot/liq.db` |
| 계좌 요약 | `cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.live3 status --db /var/lib/paperbot/paper3.db` |
| 추가 계좌 (복제·새 매매법) | `cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.extras status --db /var/lib/paperbot/paper3.db`. 설정은 `/etc/paperbot/extras.json`(없어도 됨, 예시 `deploy/extras.example.json`). 아래 "추가 계좌"와 `docs/extra-accounts.md` |
| 에이전트 | 15분마다 자동. 기록: `sudo journalctl -u paperbot-agents -n 50 --no-pager`. 끄기: `sudo systemctl disable --now paperbot-agents.timer`(방과 기록은 남음). 설정: `docs/agent-rooms.md` "설정 바꾸기" |
| 매달 재검사 | 매달 6일 03:30(한국 시간). 5년 자료 뒤의 새 기간으로 다시 계산해 총괄 방에 요약 |
| 백업 | 매일 08:40(한국 시간) `/var/backups/paperbot/날짜/`, 14일 보관. 서버 밖 사본은 매일 09:15 텔레그램 'paperbot 백업' 방(`docs/offsite-backup.md`, Vultr 자동 백업은 쓰지 않음) |
| 코드 업데이트 | `cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh`. 배포는 **한 분만** 합니다. 커밋 안 된 수정이 있으면 멈추고, 돌던 서비스는 교체하는 순간만 멈췄다가 다시 켜집니다. 이전 코드는 `/opt/crypto-bot-research.old`에 남습니다. 봇은 켜질 때마다 코드 버전·설정을 기록하고, 체결·청산·사이즈 코드가 바뀌었으면 알림을 보냅니다(규칙상 그 기간을 다시 셈). 13-5 참고 |
| 최종 점검 다시 | `cd /opt/crypto-bot-research && sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck --stage after` |
| 비밀번호 로그인 끄기 (권장) | SSH 키를 등록하고 **키로 접속되는 것을 확인한 뒤** `echo 'PasswordAuthentication no' \| sudo tee /etc/ssh/sshd_config.d/00-paperbot.conf && sudo systemctl restart ssh`. 확인: `sudo sshd -T \| grep -i passwordauthentication`이 `no`. `/etc/ssh/sshd_config`만 고치면 Vultr가 넣어 둔 `sshd_config.d` 설정이 이겨서 효과가 없을 수 있습니다. 지금 접속은 끊지 말고 새 창으로 키 접속을 먼저 시험합니다. 키 등록 전에 끄면 들어갈 수 없게 되니, Vultr 웹 콘솔이 되는지 먼저 확인 |
| 규칙 문서가 그대로인지 | `cd /opt/crypto-bot-research && sha256sum -c docs/paper-v3-rules.sha256 docs/paper-v3-rules-addendum.sha256` (둘 다 `OK`) |

## 체크포인트 판정 (30일마다, `paperbot/checkpoint.py`)
규칙은 `docs/paper-v3-rules.md` 4장과 보충 규칙(확정) Q1·Q2·Q3 그대로입니다. 코드가 계산하고, 사람이 말로 판단하지 않습니다.

- **언제:** 시작일(첫 계좌가 만들어진 UTC 날짜)부터 30·60·90…일째 00:00 UTC(한국 09:00). `paperbot-checkpoint.timer`가 매시 35분에 돌고, 판정할 날이 아니면 바이낸스에 묻지도 않고 바로 끝납니다.
- **스냅샷(Q2):** 봇이 그 시각에 저장한 상태(`paper3.db`의 `day:<날짜>`)를 그대로 옮겨 고정합니다. 평가금 = 지갑 + 열린 포지션의 마크 가격 기준 미실현 손익 − 예상 청산 수수료·슬리피지. 열린 거래는 진입한 기간의 거래로 셉니다. 스냅샷은 해시(sha256)와 함께 `checkpoint.db`에 한 번만 쓰이고 고칠 수 없으며(표가 수정·삭제를 거부), 판정은 해시를 확인한 스냅샷만 씁니다. `paper3.db`는 읽기만 합니다(봇이 유일한 작성자).
- **판정 순서(Q3):** 계좌(매매법 × 봉)마다 거래 30건을 넘긴 첫 판정일에 1차 판정. 1차 합격 = 거래 30건 이상 + 평가금 > 시작 금액($5,000) + 파산 아님 + 우연 기준 통과. 1차 합격 계좌는 그다음 30일만으로 2차 확인(그 기간 거래 30건 이상, 그 기간 손익 플러스(시작 금액 기준으로 환산), 우연 기준 다시 통과) → "2차 통과" = 실거래 검토 대상. 4시간봉과 동전 봇 계좌 15개는 "관찰용"(판정 안 함). 180일까지 30건이 안 되면 "보류 · 판정 불가".
- **우연 기준(Q1):** 판정하는 계좌마다 동전 봇 2,000개를 **같은 기간의 실제 1분봉**(바이낸스 공개 API에서 받은 마지막 체결가·마크 가격·실제 펀딩, `/var/lib/paperbot/checkpoint_bars`에 하루 단위로 보관)으로 같은 규칙(2 ATR 손절, 레버리지 단계와 거래소 구간, 코인 순서, 계단식 잠금, 마크 가격 강제청산, $10 파산)과 같은 시작 금액으로 돌립니다. 동전 봇의 신호 빈도는 그 계좌가 그 기간에 실제로 낸 신호 수 ÷ (6코인 × 봉 수)와 같습니다. p = (계좌 이상인 동전 봇 수 + 1) / 2,001. 그날 판정하는 모든 계좌(개선 복사 계좌 포함)를 모아 FDR 10%(Benjamini–Hochberg)로 보정해 q ≤ 0.10이어야 통과입니다. "우연으로 기대되는 합격 수"는 통과 수 × 10%(상한)로 함께 보고합니다.
- **동전 봇 엔진:** paper 엔진과 같은 규칙을 2,000 × 계좌 수만큼 한꺼번에 계산하는 벡터 버전입니다. 테스트가 같은 신호를 진짜 `PaperEngine`에 넣어 거래 하나하나(손절·잠금·강제청산·펀딩·파산) 같은 결과인지 확인합니다. 시간: 30일 창에서 한 봉의 36계좌 × 2,000개가 약 2~3분, 첫 판정(4개 봉 전부)이 약 10분(코어 1개, 낮은 우선순위). 그래서 계좌끼리 동전 봇을 나눠 쓰지 않고 계좌마다 따로 2,000개를 돌립니다.
- **결과 보기:** 대시보드 순위표의 "체크포인트 판정", 텔레그램 무음 요약, 서버에서 `cd /opt/crypto-bot-research && sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.checkpoint show --out /var/lib/paperbot/checkpoint.db`. 에이전트는 `paperbot.checkpoint.latest_verdict` / `account_status` / `statuses`로 읽습니다.
- **판정이 안 될 때:** 판정할 날인데 오류로 판정을 못 하면 그 날짜·오류 종류마다 한 번 텔레그램 경고(소리 있음)가 오고, 타이머가 매시 35분에 다시 시도합니다. 판정 요약이 텔레그램에 전달되지 않았으면 다음 실행 때 다시 보냅니다.
- **미리 연습 (10/10쯤, 10/25쯤 한 번씩):** 실제 데이터로 판정 전 과정을 미리 돌려 봅니다. 오늘(UTC)을 판정일처럼, 거래 10건 이상·동전 봇 500개로 계산합니다. 진짜 `checkpoint.db`에는 쓰지 않고(이미 있는 파일이나 진짜 판정 파일 경로는 거부) 텔레그램도 보내지 않습니다. 1분봉 보관함을 미리 채워 11/1 판정도 빨라집니다. 수 분 걸립니다.
  `sudo systemd-run --wait --pipe --collect -p User=paperbot -p WorkingDirectory=/opt/crypto-bot-research -p EnvironmentFile=/etc/paperbot/live.env -p Nice=15 /opt/paperbot/venv/bin/python -m paperbot.checkpoint_preview --db /var/lib/paperbot/paper3.db --out /tmp/preview-$(date +%m%d%H%M).db --cache /var/lib/paperbot/checkpoint_bars`
  확인: 오류 없이 "미리보기 끝"까지 나오는지, 스냅샷 계좌 수(156개 + 추가 계좌), "신호 비율 0인 계좌"가 0개인지, 걸린 시간, "주의" 줄. 화면 내용을 그대로 개발 담당에게 보내 주세요.
- **매주 미리 연습 (자동):** `paperbot-rehearsal.timer`가 매주 수요일 12:30(한국 시간)에 위 미리 연습을 같은 조건(오늘을 판정일처럼, 거래 10건 이상, 동전 봇 500개)으로 돌립니다. 결과는 `/var/lib/paperbot/rehearsal/`에 새 파일로만 쓰고 최근 4번만 남깁니다. 진짜 `checkpoint.db`와 진짜 1분봉 보관함은 이 작업에서 아예 보이지 않게 막혀 있고(자기 보관함 `rehearsal/bars` 사용), 텔레그램도 보내지 않습니다. 실패하면(오류, 그날 00:00 상태 없음 등) `[작업 실패] 판정 미리 연습` 경고가 한 번 옵니다. 요약 보기: `sudo cat /var/lib/paperbot/rehearsal/latest.json` (`status`가 `ok`, `accounts_in_snapshot`이 156개 + 추가 계좌, `zero_rate_accounts`가 빈 목록 `[]`, `runtime_s` 걸린 초, `warnings` 주의, `counts` 상태별 계좌 수). 에이전트와 대시보드도 이 파일을 읽을 수 있습니다.
- **주의:** 기간 중에 체결·청산·사이즈 코드가 바뀐 재시작이 있으면 판정 결과에 "주의"로 표시합니다. Q5(그 계좌의 기간을 배포일부터 다시 셈)는 아직 코드가 자동으로 적용하지 않으므로 규칙 관리자가 확인합니다.

## 추가 계좌 (복제 계좌·새 매매법 계좌, `paperbot/extras.py`)
두 분이 승인한 제안으로 live 봇이 원래 156개 옆에 새 paper 계좌를 만듭니다. 원래 156개는 바뀌지 않습니다. 자세한 것은
`docs/extra-accounts.md`.

- **설정할 것 없음:** 기본값(관찰 21일, 처음 60일 두 분 승인, `paper3.db` 옆의 `agents3.db`·`inbox.db`를 읽기만 함)으로 돕니다.
  바꿀 때만 `deploy/extras.example.json`을 `/etc/paperbot/extras.json`로 복사해 고칩니다(봇이 5분마다 다시 읽음).
  `paperbot-live3.service`와 실행 명령은 그대로입니다.
- **한 대만:** 봇은 켜질 때 `paper3.db` 파일 자체를 잠급니다(flock). 같은 파일이면 경로를 어떻게 쓰든(심볼릭 링크, 하드 링크, 바인드 마운트) 두 번째 live 봇은 "another live runner already holds"로 바로 끝납니다.
- **보기:** 운영 표의 "추가 계좌" 명령, 대시보드 순위표의 "복제"/"새" 표시.
- **에이전트 장부(agents3.db)·inbox.db 복원:** live 봇을 멈추지 않고 `extras.json`에 `"pause_activation": true` → 복원 →
  `agents_db: regressed`가 보이면 알림의 값을 `"agents_ack"`에, `inbox_db: regressed`면 `"inbox_ack"`에 →
  (inbox.db면 그다음에 백업 뒤에 누른 승인·거절을 두 분이 다시 누름) → `pause_activation` false (`docs/extra-accounts.md` 6장).
- **알림:** 새 계좌 시작은 텔레그램 무음, 추가 계좌의 낙폭·파산은 "추가 계좌 알림 모음"(한 시간에 한 번, 무음), 멈춤·정지는
  CRITICAL로 바로 옵니다.
- **판정:** 추가 계좌는 자기가 시작된 날부터 30일을 세고, 동전 봇도 자기 묶음으로 따로 돌려 원래 계좌들의 판정은 그대로입니다.

## 실거래 준비 (이 문서 범위 밖)
테스트넷 주문 연습과 실거래는 `docs/live-safety.md` 3장을 따릅니다. 주문 키는 `live.env`가 아니라 root만 읽을 수 있는 `/etc/paperbot/executor.env`에 넣고, 주문 실행기(`paperbot-executor`)는 그 문서의 순서대로 사람이 직접 켭니다. paper 봇의 읽기 전용 키를 주문 키로 쓰지 않습니다.
