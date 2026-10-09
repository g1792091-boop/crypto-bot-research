# 데모 랩 봇 설치 (규칙봇 서버에 함께)

데모 랩은 48개의 **모의** 계좌로 S2·N02·N04 매매법의 모든 설정을 실시간으로 비교하는 봇입니다.

- **주문하지 않습니다.** 거래소 키가 없고 필요도 없습니다. 바이낸스 공개 시세만 읽습니다.
- 규칙봇과 **완전히 따로** 돕니다. 사용자, 코드 사본, 데이터베이스, 서비스, 대시보드 포트(8090), 텔레그램 봇이 모두 따로입니다.
- 도는 것: 엔진 `demobot-live`(15분마다 계좌 계산), 대시보드 `demobot-dash`, 순위표 `demobot-rank`(매시 7분에 몇 분 동안 모든 설정의 순위를 다시 만듦, 타이머 `demobot-rank.timer`), 밤 백업 `demobot-backup`(매일 04:40 기록을 텔레그램으로, 타이머 `demobot-backup.timer`), 감시 `demobot-watch`(10분마다 점검, 타이머 `demobot-watch.timer`).

아래 상자는 서버에 root로 접속한 화면(`root@…:~#`)에 하나씩 붙여 넣습니다. 상자 밑의 "보여야 할 것"과 다르면 멈추고, 그 화면을 개발자에게 보냅니다.

순서: 0 점검 → 1 설치 → 2 텔레그램 → 3 대시보드 비밀번호 → 4 첫 채우기와 켜기 → 5 대시보드 열기 → 9 서버 밖 감시(healthchecks.io) → 10 밤 백업 한 번 해 보기

**이미 설치해서 돌고 있으면** (2차 → 3차): 12번 업데이트만 하고, 이어서 9번과 10번을 합니다.

---

## 0. 용량 점검 (읽기만, 아무것도 바꾸지 않음)

```bash
git clone --branch claude/keen-pasteur-wav02u --depth 1 https://github.com/g1792091-boop/crypto-bot-research /root/demobot-src
sudo bash /root/demobot-src/deploy/demobot/capacity_check.sh
```

- 코드는 **새 폴더** `/root/demobot-src`에 받습니다. 규칙봇이 쓰는 기존 폴더(`/root/crypto-bot-research`, `/opt/crypto-bot-research`)는 건드리지 않습니다.
- `/root/demobot-src`가 이미 있다는 오류가 나오면 첫 줄 대신 `cd /root/demobot-src && git pull`을 붙여 넣습니다.
- 보여야 할 것: 맨 아래 판정이 **같은 서버에 설치해도 됩니다**. "모자란 것"이 나오면 여기서 멈추고 화면을 개발자에게 보냅니다.
- 이 점검은 CPU·메모리·디스크·규칙봇 서비스의 메모리와 CPU·포트 8090·Tailscale 상태를 읽기만 합니다.

---

## 1. 설치

```bash
sudo bash /root/demobot-src/deploy/demobot/install_demobot.sh
```

- 사용자 `demobot`, 폴더, 설정 파일(값은 비어 있음), 파이썬 환경, 코드 사본, 서비스 등록까지 합니다. 처음에는 파이썬 패키지를 받느라 몇 분 걸립니다.
- 첫 채우기 전이라 **아직 아무것도 켜지 않습니다.**
- 보여야 할 것: 마지막에 `== 요약`과 `다음 할 일` 목록이 나오면 됩니다. `selfcheck failed`가 보이면 멈추고 화면을 개발자에게 보냅니다(이때는 아무것도 바뀌지 않았습니다).

---

## 2. 텔레그램 (새 봇, 두 분 각자 개인 대화)

데모 랩 알림은 **두 분 각자와 봇의 개인 대화**(1:1)로 옵니다. 두 분이 같은 메시지를 받고, 관점 줄(6번)도 각자 봇에게 보내면 됩니다. 단체방은 필요 없습니다(원하면 맨 아래 "단체방으로 받으려면").

**폰에서 (명령 없음)**

1. 텔레그램에서 `@BotFather`를 열고 `/newbot`을 보냅니다. 이름은 `데모 랩 봇`, 아이디는 영문으로 `bot`으로 끝나게 짓습니다(예: `demolab_우리이름_bot`). 규칙봇의 봇과 **다른 새 봇**입니다.
2. BotFather가 주는 **토큰**(숫자:영문으로 된 긴 줄)을 복사합니다. 토큰은 **채팅·메모·메일에 붙이지 않습니다.** 아래 서버 편집기 안에만 붙입니다.
3. **두 분이 각자** 텔레그램 검색창에 새 봇의 아이디를 넣어 봇을 열고 **시작**(Start)을 누릅니다(`/start`를 보내도 같습니다). 시작을 누르지 않은 사람에게는 봇이 메시지를 보낼 수 없습니다.

**서버에서: 토큰 넣기**

```bash
SUDO_EDITOR=nano sudoedit /etc/demobot/demobot.env
```

편집기에서 `DEMOBOT_TG_TOKEN=` 줄 끝에 토큰을 붙여 넣습니다. 저장 Ctrl+O, Enter, 종료 Ctrl+X.

**두 분의 번호 찾기** (토큰은 화면에 나오지 않습니다)

```bash
cd /opt/demobot/app && sudo -u demobot /opt/demobot/venv/bin/python -m demobot.notify chatid
```

- 보여야 할 것: 두 분 각자의 줄, 예: `개인 번호 123456789   이름 민수   (개인)`. 그 숫자가 그 분의 번호입니다.
- 한 분만 보이거나 `최근 메시지가 없습니다`가 나오면, 안 보이는 분이 봇에게 아무 말이나 한 번 보내고 이 상자를 다시 붙여 넣습니다.
- 데모 랩이 이미 돌고 있는 서버(업데이트한 서버)에서는 엔진이 봇의 메시지를 먼저 읽어 가서 여기에 안 보입니다. 먼저 `sudo bash /root/demobot-src/deploy/demobot/off.sh`로 끄고, 봇에게 다시 한 번 말한 뒤 찾습니다. 다 넣은 뒤 `on.sh`로 켭니다.

**번호 넣기**

```bash
SUDO_EDITOR=nano sudoedit /etc/demobot/demobot.env
```

`DEMOBOT_TG_CHAT=` 줄 끝에 두 분의 번호를 **쉼표로 이어** 적고 저장합니다(Ctrl+O, Enter, Ctrl+X). 예: `DEMOBOT_TG_CHAT=123456789,987654321` (최대 4개).

**시험 메시지**

```bash
cd /opt/demobot/app && sudo -u demobot /opt/demobot/venv/bin/python -m demobot.notify test
```

- 보여야 할 것: 번호마다 `보냄: 123456789`, 마지막에 `보냈습니다 (2곳)`, 그리고 두 분 각자의 봇 대화에 `🧪 데모 랩 테스트 메시지`.
- `보내지 못했습니다: 번호 · …` 줄이 나오면 그 아래 줄이 말하는 대로 고치고 다시 합니다(대개 그 분이 아직 봇에서 시작을 누르지 않은 것). `토큰이 틀렸습니다`면 토큰을 다시 넣습니다.
- 데모 랩 알림은 모두 무음으로 옵니다(규칙봇과 같음). 15분마다 거래가 있을 때 한 번 묶어서, 아침 9시에 하루 요약, 월요일 아침 9시에 주간 회의록이 옵니다. 관점 줄(6번)에는 바로 답합니다.
- 봇은 `DEMOBOT_TG_CHAT`에 적힌 번호에서 온 메시지만 읽습니다. 다른 사람이 봇을 찾아 말을 걸어도 무시합니다.
- 개인 대화에는 BotFather의 `/setprivacy` 설정이 필요 없습니다.

**단체방으로 받으려면 (선택)**

개인 대화 대신, 또는 함께 단체방도 됩니다. 새 단체방을 만들어 두 분과 봇을 넣고(규칙봇 알림방이 아닌 방), BotFather에 `/setprivacy` → 이 봇 → `Disable`을 누릅니다. 그래야 봇이 단체방의 `관점 …` 줄을 읽습니다(대신 봇을 단체방의 관리자로 만들어도 됩니다. 봇을 방에 넣은 **뒤에** 바꿨다면 봇을 뺐다가 다시 넣습니다). 그 방에 `/start@봇아이디`를 보내고 `chatid`에 나오는 `방 번호 -100…`을 `DEMOBOT_TG_CHAT=`에 넣거나 개인 번호 뒤에 쉼표로 덧붙입니다.

---

## 3. 대시보드 비밀번호와 주소

대시보드 비밀번호(12자 이상, 규칙봇 대시보드와 다른 것)를 정합니다. 아래 상자는 비밀번호를 두 번 묻고, 해시·비밀값·Tailscale 주소를 설정 파일에 바로 적습니다(복사할 필요 없음). 입력하는 글자가 화면에 안 보이는 게 정상입니다.

```bash
cd /opt/demobot/app
H=$(/opt/demobot/venv/bin/python -B -m demobot.dash hash) && \
  sudo sed -i "s|^DEMOBOT_DASH_PASSWORD_HASH=.*|DEMOBOT_DASH_PASSWORD_HASH='$H'|" /etc/demobot/demobot.env && echo 비밀번호 저장됨
S=$(openssl rand -hex 32) && \
  sudo sed -i "s|^DEMOBOT_DASH_SECRET=.*|DEMOBOT_DASH_SECRET=$S|" /etc/demobot/demobot.env && echo 비밀값 저장됨
IP=$(tailscale ip -4) && [ -n "$IP" ] && \
  sudo sed -i "s|^DEMOBOT_DASH_HOST=.*|DEMOBOT_DASH_HOST=$IP|" /etc/demobot/demobot.env && echo "대시보드 주소 $IP"
sudo awk -F= '/^DEMOBOT_(TG_TOKEN|TG_CHAT|DASH_PASSWORD_HASH|DASH_SECRET|DASH_HOST)=/{print $1": "(length($2)>2?"set":"EMPTY")}' /etc/demobot/demobot.env
```

- 보여야 할 것: `비밀번호 저장됨`, `비밀값 저장됨`, `대시보드 주소 100.x.y.z`, 그리고 다섯 줄이 모두 `set`(값 자체는 화면에 내지 않습니다).
- `use at least 12 characters`나 `passwords differ`가 나오면 저장되지 않은 것입니다. 상자를 다시 붙여 넣습니다.
- 해시는 root 화면에서 `sudo` 없이 만듭니다(규칙봇 6단계와 같은 이유: `$( )` 안의 sudo는 비밀번호 입력이 안 됩니다).
- 손으로 넣고 싶으면 `SUDO_EDITOR=nano sudoedit /etc/demobot/demobot.env`로 열어 같은 세 줄을 채웁니다. 해시는 `$` 기호가 있으니 작은따옴표로 감쌉니다(`DEMOBOT_DASH_PASSWORD_HASH='pbkdf2$...'`). 비밀값은 `openssl rand -hex 32`로 만든 64글자, 주소는 `tailscale ip -4`가 보여 주는 `100.x.y.z`입니다.
- 설정 파일을 화면에 통째로 띄우지 않습니다(토큰이 화면 기록에 남습니다). 확인은 위의 마지막 줄처럼 `set`/`EMPTY`만 봅니다.

---

## 4. 첫 채우기와 켜기

지난 26주의 시세와 모든 설정의 결과를 채웁니다. 10~15분 걸립니다.

```bash
sudo bash /root/demobot-src/deploy/demobot/warm.sh
```

- 화면에 진행 줄이 나오고, 끝나면 `첫 채우기가 끝났습니다`가 보입니다. 이어서 순위표를 한 번 만들고(2~4분) `순위표도 만들었습니다`가 보입니다.
- SSH 접속이 끊겨도 서버에서 계속 돕니다. 다시 접속해서 `systemctl is-active demobot-warm`이 `inactive`면 끝난 것입니다(진행 보기: `journalctl -u demobot-warm -f`, Ctrl+C는 보기만 멈춥니다).
- `첫 채우기가 실패했습니다`가 나오면 `journalctl -u demobot-warm -n 40 --no-pager` 화면을 개발자에게 보냅니다.

끝났으면 켭니다(서버를 다시 켜도 자동으로 돕니다):

```bash
sudo bash /root/demobot-src/deploy/demobot/on.sh
```

- 보여야 할 것: `demobot-live.service: active`, `demobot-dash.service: active`, `demobot-rank.timer: active`, `demobot-backup.timer: active`, `demobot-watch.timer: active`. 두 분의 텔레그램(봇 대화)에 `▶️ 데모 랩 시작` 메시지가 옵니다.
- 순위표는 엔진과 따로, 매시 7분에 몇 분 동안 만들어집니다(서버를 다시 켜면 10분 뒤에 한 번). 순위표가 아직 없으면 이 스크립트가 바로 한 번 만듭니다.
- 방화벽: 규칙봇 설치 때 `sudo ufw allow in on tailscale0`을 했으면 8090도 이미 Tailscale로 열려 있어 바꾸는 것이 없습니다. 그 규칙이 없으면 이 스크립트가 8090을 Tailscale에만 엽니다(인터넷에는 열지 않음).
- `failed`가 보이면 `journalctl -u demobot-live -n 40 --no-pager`(대시보드면 `demobot-dash`) 화면을 개발자에게 보냅니다.

---

## 5. 대시보드 열기

폰이나 PC에서 Tailscale 앱을 켠 상태로 브라우저에 엽니다(`https`가 아니라 `http`):

`http://100.x.y.z:8090`

- `100.x.y.z`는 3단계에서 나온 서버의 Tailscale 주소입니다. 규칙봇 대시보드(`:8080`)와 주소는 같고 포트만 다릅니다.
- 비밀번호는 3단계에서 정한 것입니다.
- 켠 직후 몇 화면은 `준비 중`일 수 있습니다. 15분이 지나면 채워집니다.

---

## 6. 관점 기록장 쓰는 법

두 분의 관점(어느 코인이 어느 구간에서 오를지·내릴지)을 봇과의 개인 대화에 **한 줄**로 보내면, 봇이 기록하고 48시간 동안 시장을 따라가며 채점합니다. 주문은 하지 않습니다. 누가 보내든 기록은 하나로 모이고, 확인 답장과 결과는 **두 분 모두** 받습니다.

```
관점 [MM/DD HH:MM] 코인 롱|숏 [A 가격(-가격)] [B …] [C …] [손절 가격] [목표 가격[,가격]] [메모 글]
```

- 시각은 한국 시간이고, 빼면 보낸 시각입니다. 코인은 BTC ETH SOL DOGE LTC BCH XRP.
- 구간 A·B·C 중 **하나는 꼭** 씁니다. 범위는 `84750-84840` 또는 `84750~84840`, 쉼표를 넣어도 됩니다.
- 손절을 빼면 가장 먼 구간에서 0.3% 바깥, 목표를 빼면 1R에 절반 · 본전 · 나머지 2R로 채점합니다.

예:

```
관점 BTC 숏 B 84750-84840 C 85300 손절 85600
관점 10/10 14:00 ETH 롱 A 3,050~3,060 손절 3,010 목표 3,120,3,180 메모 지지선 반등
```

- 봇이 `📝 관점 #12 기록 · BTC 숏`처럼 번호를 붙여 답합니다. 못 알아들으면 `❓`로 이유와 예를 답합니다.
- `취소 12`: 12번 관점 취소 · `관점목록`: 최근 10개 · `관점도움`: 쓰는 법.
- 48시간 뒤(또는 두 가지 따라 하기가 모두 끝나면) `📊 관점 #12 결과`가 옵니다: 4·24·48시간 뒤 말한 방향으로 움직인 %, 구간 도달, "구간 바로 진입"과 "15분 종가 확인 진입"의 결과(R, 20배 잔고 %).
- 끝난 관점이 30개가 되기 전에는 판정이 "표본 부족"입니다.
- 관점과 번호는 **이 서버의 데이터베이스**와 매일 밤 두 분의 텔레그램으로 가는 **백업 파일**(10번)에만 남습니다. GitHub(코드 저장소)에는 올라가지 않습니다.
- `DEMOBOT_TG_CHAT`에 적힌 번호(두 분의 개인 대화, 또는 넣은 단체방)에서 온 줄만 받습니다. 봇이 답하지 않으면 그 번호가 `DEMOBOT_TG_CHAT`에 있는지 봅니다. 단체방에서만 답하지 않으면 2단계의 `/setprivacy` → `Disable`을 확인합니다.

---

## 7. 비공개 매매법 넣기 (선택)

두 분만 쓰는 매매법을 데모 랩에 계좌로 더할 수 있습니다. 그 코드는 공개 저장소(GitHub)에 올리지 않고 **이 서버에만** 둡니다.

1. 개발자가 채팅으로 **붙여 넣기 상자**를 드립니다. 그 상자는 `/etc/demobot/plugins/` 안에 파일 하나를 만들고(root:demobot, 640), 파일의 sha256이 맞는지 확인합니다.
2. 상자를 서버에 그대로 붙여 넣습니다. 보여야 할 것: 확인 줄 끝의 `OK`. `FAILED`가 나오면 켜지 말고, 아래 "빼기"로 그 파일을 지운 뒤 개발자에게 알립니다.
3. 다시 켜서 읽힙니다:

```bash
sudo bash /root/demobot-src/deploy/demobot/on.sh
```

- 보여야 할 것: `비공개 매매법 파일 N개를 읽습니다`. 대시보드에 "비공개 매매법" 계좌가 생깁니다.
- 지금 있는 파일 보기: `sudo ls -l /etc/demobot/plugins`

빼기:

```bash
sudo rm /etc/demobot/plugins/<파일 이름>.py
sudo bash /root/demobot-src/deploy/demobot/on.sh
```

- 설치·업데이트 스크립트는 이 폴더 안의 파일을 건드리지 않습니다(`uninstall.sh --purge`만 설정과 함께 지웁니다). 대시보드 서비스는 이 폴더를 볼 수 없습니다.
- 그 파일의 내용은 다른 채팅이나 GitHub에 올리지 않습니다.

---

## 8. 켜기 · 끄기 · 업데이트 · 지우기

| 할 일 | 붙여 넣을 것 |
|---|---|
| 끄기 (엔진·대시보드·순위표·밤 백업·감시 모두, 재부팅 뒤에도 꺼진 채) | `sudo bash /root/demobot-src/deploy/demobot/off.sh` |
| 켜기 (설정 파일을 바꾼 뒤 다시 읽힐 때도) | `sudo bash /root/demobot-src/deploy/demobot/on.sh` |
| 상태 보기 | `systemctl status demobot-live demobot-dash demobot-rank.timer --no-pager` |
| 순위표 시간표 보기 (지난번·다음 실행) | `systemctl list-timers demobot-rank.timer` |
| 타이머 셋 다 보기 (순위표·밤 백업·감시) | `systemctl list-timers 'demobot-*'` |
| 순위표 기록 보기 | `journalctl -u demobot-rank -n 30 --no-pager` |
| 기록 보기 | `journalctl -u demobot-live -n 50 --no-pager` |
| 밤 백업 지금 한 번 (10번) | `cd /opt/demobot/app && sudo -u demobot /opt/demobot/venv/bin/python -m demobot.backup now` |
| 밤 백업 기록 보기 | `journalctl -u demobot-backup -n 20 --no-pager` |
| 감시 기록 보기 (11번) | `journalctl -u demobot-watch -n 20 --no-pager` |
| 업데이트 (개발자가 알려 줄 때만, 12번) | `cd /root/demobot-src && git pull && sudo bash deploy/demobot/update.sh` |
| 지우기 (데이터와 설정은 남김) | `sudo bash /root/demobot-src/deploy/demobot/uninstall.sh` |
| 모두 지우기 (데이터·설정·사용자까지) | `sudo bash /root/demobot-src/deploy/demobot/uninstall.sh --purge` |

- 업데이트는 데모 랩의 코드만 다시 복사하고, 켜져 있던 데모 랩 서비스만 다시 시작합니다(꺼 둔 것은 꺼진 채). 이전 코드는 `/opt/demobot/app.old`에 남습니다.
- 끄고 켜도 데이터는 그대로이고, 켜면 이어서 돕니다.
- 9번 healthchecks.io를 넣었으면, 일부러 끌 때 healthchecks.io에서 `demolab`을 **Pause**해 둡니다(안 그러면 45분 뒤 "down" 메일이 옵니다). 다시 켜면 첫 신호에 저절로 풀립니다.

---

## 9. 서버 밖 감시: healthchecks.io (권장)

서버가 통째로 멈추면(전원, 네트워크, 서버 회사 문제) 봇은 스스로 알릴 수 없습니다. healthchecks.io가 대신 알려 줍니다. 엔진이 15분마다 계산을 마칠 때 정해진 주소(Ping URL)를 한 번 부르고, 그 신호가 45분(주기 15분 + 유예 30분) 동안 오지 않으면 healthchecks.io가 메일을 보냅니다.

**PC나 폰 브라우저에서 (명령 없음)**

1. https://healthchecks.io 에 로그인합니다(없으면 무료로 가입).
2. **Add Check**로 **새 체크**를 만듭니다. 이름(Name)은 `demolab`. 규칙봇용 체크가 이미 있어도 그것을 쓰지 않습니다.
3. 체크의 **Schedule**에서 **Period 15 minutes**, **Grace Time 30 minutes**로 하고 저장합니다.
4. 체크 화면의 **Ping URL**(`https://hc-ping.com/…`)을 복사합니다. 이 주소는 채팅·메모·메일에 붙이지 않습니다. 아래 서버 편집기 안에만 붙입니다.
5. 알림은 가입한 메일로 옵니다. 텔레그램으로도 받으려면 healthchecks.io의 **Integrations**에서 Telegram을 더합니다(선택).

**서버에서: 주소 넣기**

```bash
SUDO_EDITOR=nano sudoedit /etc/demobot/demobot.env
```

`DEMOBOT_DEADMAN_URL=` 줄 끝에 Ping URL을 붙여 넣고 저장합니다(Ctrl+O, Enter, Ctrl+X). 그 줄이 없으면(12번 업데이트 전) 맨 아래에 `DEMOBOT_DEADMAN_URL=`과 주소를 한 줄로 씁니다.

엔진이 새 설정을 읽도록 다시 켭니다:

```bash
sudo bash /root/demobot-src/deploy/demobot/on.sh
```

- 보여야 할 것: 15~30분 안에 healthchecks.io의 `demolab`이 회색(new)에서 **초록(up)**으로 바뀌고, **Last Ping**에 방금 시각이 보입니다.
- 1시간이 지나도 회색이면 `journalctl -u demobot-live -n 40 --no-pager` 화면을 개발자에게 보냅니다(주소를 잘못 붙였을 수 있습니다).
- 확인: `sudo awk -F= '/^DEMOBOT_DEADMAN_URL=/{print $1": "(length($2)>2?"set":"EMPTY")}' /etc/demobot/demobot.env` → `set` (주소 자체는 화면에 내지 않습니다).

---

## 10. 밤 백업과 되살리기

매일 밤 04:40(한국 시간)에 서버가 작은 백업 파일을 두 분의 텔레그램(봇 대화)으로 보냅니다(`💾 데모 랩 밤 백업`, 소리 없음). 서버가 사라져도 이 파일로 기록을 되살립니다.

- **들어 있는 것**: 바이낸스에서 다시 얻을 수 없는 기록만. 관점 기록, 계좌의 설정 바꿈 기록, 우리 기준 통과와 확인 기간 기록, 호가창 비용 기록, 주간 회의록(끝난 주), 알림 표시, 기본 정보(실시간 시작 시각 등), 지난 7일 동안 보낸 알림.
- **들어 있지 않은 것**: 시세(봉), 펀딩, 신호, 계산된 거래 결과. 이것들은 첫 채우기(`warm.sh`)가 바이낸스에서 다시 받아 다시 만들고, 계좌 성적은 엔진이 그 시세와 설정 바꿈 기록으로 다시 계산합니다. 대시보드 화면 파일도 엔진이 다시 씁니다.
- 파일은 보통 수 MB 이하입니다(45 MB가 넘으면 보내지 않고 알립니다).
- 다른 곳으로 받고 싶으면 설정 파일의 `DEMOBOT_BACKUP_CHAT=`에 그 번호를 넣습니다(여럿이면 쉼표로. 비우면 `DEMOBOT_TG_CHAT`의 모든 번호). 한 곳이라도 못 받으면 그날 백업은 실패로 치고 어느 번호가 못 받았는지 알려 줍니다.
- 실패하면 감시(11번)가 36시간 안에 `⚠ 데모 랩 경고 · 밤 백업이 안 됨`을 보냅니다.

**암호 (선택)**

넣으면 백업 파일을 openssl(AES-256)로 잠급니다. 텔레그램 방이나 폰을 잃어도 남이 파일을 열 수 없습니다.

```bash
openssl rand -hex 24
```

1. 화면에 나온 48글자를 **먼저 두 분의 비밀번호 관리 앱(서버 밖)**에 저장합니다. 서버가 사라지면 서버의 설정 파일도 같이 사라지므로, 이 암호를 잃으면 백업을 열 수 없습니다. 텔레그램에는 쓰지 않습니다.
2. `SUDO_EDITOR=nano sudoedit /etc/demobot/demobot.env`로 열어 `DEMOBOT_BACKUP_PASSPHRASE=` 줄 끝에 붙여 넣고 저장합니다.
3. 아래 "한 번 해 보기"로 확인합니다(백업은 할 때마다 설정 파일을 새로 읽어서 `on.sh`는 필요 없습니다).

**한 번 해 보기**

```bash
cd /opt/demobot/app && sudo -u demobot /opt/demobot/venv/bin/python -m demobot.backup now
```

- 보여야 할 것: `복사함: views … · decisions … …`, 번호마다 `보냄: …`, 마지막에 `보냈습니다: demolab-….db.gz (…, 암호화 예/아니오, 2곳)`, 그리고 두 분의 봇 대화에 `💾 데모 랩 밤 백업` 파일.
- `백업하지 못했습니다: …`가 나오면 그 줄이 말하는 대로 고치고 다시 합니다. 모르겠으면 그 화면을 개발자에게 보냅니다.
- 다음 밤 백업 시각: `systemctl list-timers demobot-backup.timer` (서버 시계가 UTC면 19:40으로 보입니다 = 한국 04:40).

**되살리기** (서버를 새로 만들었거나 데이터베이스가 망가졌을 때)

1. 봇 대화에서 가장 최근 `💾 데모 랩 밤 백업` 파일을 PC로 내려받습니다. 이름은 `demolab-날짜-시각.db.gz`이고, 암호를 썼으면 끝에 `.enc`가 붙습니다.
2. PC에서 서버로 올립니다(파일이 있는 폴더에서 PC의 터미널이나 PowerShell로. 쓰는 SSH 앱에 파일 올리기가 있으면 그것으로 `/root/`에 올려도 됩니다):

```bash
scp demolab-20261010-0440.db.gz.enc root@100.x.y.z:/root/
```

3. 서버에서 붙여 넣습니다(파일 이름은 올린 것으로 바꿉니다). **새 서버면** 먼저 1~3단계(설치, 텔레그램, 대시보드)까지 하고, 4단계 첫 채우기 **전에** 합니다.

```bash
sudo bash /root/demobot-src/deploy/demobot/off.sh
sudo install -o demobot -g demobot -m 600 /root/demolab-20261010-0440.db.gz.enc /var/lib/demobot/
cd /opt/demobot/app && sudo -u demobot /opt/demobot/venv/bin/python -m demobot.backup restore /var/lib/demobot/demolab-20261010-0440.db.gz.enc
```

- 암호를 물으면 백업 암호를 넣습니다(화면에 안 보이는 게 정상).
- 보여야 할 것: `백업 파일 확인 (integrity_check): ok`, `되살렸습니다: /var/lib/demobot/demo.db`, 표마다 줄 수, 그리고 `다음:` 목록. 그 목록대로 합니다. 새로 만든 데이터베이스면 첫 채우기(`warm.sh`) 다음에 켜기(`on.sh`), 원래 있던 데이터베이스면 켜기(`on.sh`)입니다.
- 엔진이 켜져 있으면 되살리지 않습니다(먼저 `off.sh`). 데이터베이스는 한꺼번에 바뀌거나 전혀 안 바뀝니다.
- 끝나면 올린 파일을 지웁니다: `sudo rm /var/lib/demobot/demolab-*.db.gz* /root/demolab-*.db.gz*`
- openssl만 있으면 다른 컴퓨터에서도 열 수 있습니다: `openssl enc -d -aes-256-cbc -pbkdf2 -in 파일.db.gz.enc -out 파일.db.gz` 다음 `gunzip 파일.db.gz` → SQLite 파일.

---

## 11. 감시 (10분마다)

`demobot-watch`가 10분마다 서버 안에서 확인하고, 문제가 있으면 두 분의 텔레그램으로 바로 알립니다. 엔진의 알림과 따로 보내므로 엔진이 멈춰도 옵니다.

| 알림 | 뜻 | 할 일 |
|---|---|---|
| `⚠ 데모 랩 경고 · 엔진이 멈춤` | 45분 넘게 15분 계산이 없거나, 엔진 서비스가 꺼짐 | `sudo bash /root/demobot-src/deploy/demobot/on.sh`. 그래도 다시 오면 `journalctl -u demobot-live -n 40 --no-pager` 화면을 개발자에게 |
| `⚠ 데모 랩 경고 · 순위표가 안 만들어짐` | 3시간 넘게 새 순위표가 없거나, 마지막 순위표 계산이 실패 | `journalctl -u demobot-rank -n 40 --no-pager` 화면을 개발자에게 |
| `⚠ 데모 랩 경고 · 밤 백업이 안 됨` | 36시간 넘게 성공한 백업이 없음 | 메시지의 오류 줄을 보고 10번 "한 번 해 보기" |

- 같은 경고는 3시간에 한 번만 옵니다. 고쳐지면 `✅ 데모 랩 회복 · …`이 한 번 옵니다.
- 켠 직후(`on.sh`, 업데이트, 재부팅)에는 첫 계산을 기다려 주므로 바로 경고하지 않습니다.
- 서버 전체가 멈추면 이 감시도 같이 멈춥니다. 그래서 9번 healthchecks.io가 따로 있습니다.
- 기록 보기: `journalctl -u demobot-watch -n 20 --no-pager` · 시간표: `systemctl list-timers demobot-watch.timer`

---

## 12. 업데이트: 이미 설치한 서버 (2차 → 3차)

2차(관점 기록장까지)를 설치해서 돌고 있으면 이것만 하면 됩니다. 데이터와 설정 값은 그대로입니다.

```bash
cd /root/demobot-src && git pull && sudo bash deploy/demobot/update.sh
```

- 데모 랩 코드만 다시 복사하고, 켜져 있던 데모 랩 서비스를 새 코드로 다시 시작합니다. 엔진이 켜져 있었으면 새 타이머 둘(밤 백업, 감시)도 켭니다. 꺼 둔 데모 랩은 꺼진 채입니다.
- 설정 파일 맨 아래에 빈 줄 셋이 생깁니다: `DEMOBOT_DEADMAN_URL=`, `DEMOBOT_BACKUP_CHAT=`, `DEMOBOT_BACKUP_PASSPHRASE=`. 비어 있으면 아무것도 바뀌지 않습니다.
- `selfcheck failed`가 보이면 아무것도 바뀌지 않은 것입니다. 그 화면을 개발자에게 보냅니다.

확인할 것:

1. `== 요약`에서 엔진, 대시보드, 순위표, 밤 백업, 감시가 모두 `켜짐`입니다. `꺼짐`이 있으면 `sudo bash /root/demobot-src/deploy/demobot/on.sh`.
2. 타이머 셋:

```bash
systemctl list-timers 'demobot-*'
```

   보여야 할 것: `demobot-rank.timer`(매시 7분), `demobot-backup.timer`(다음 19:40 UTC = 한국 04:40), `demobot-watch.timer`(10분 안).
3. 텔레그램에 `▶️ 데모 랩 시작 · 계좌 …개`와 `이어서 돌림`이 옵니다(엔진이 새 코드로 다시 시작함).
4. 대시보드를 새로 고칩니다. 새 화면은 다음 15분 계산 뒤에 채워집니다.
5. 알림을 단체방 대신 **개인 대화**로 받으려면(권장): 두 분이 각자 봇을 열어 시작(Start)을 누르고, `sudo bash /root/demobot-src/deploy/demobot/off.sh`로 끈 뒤, 2단계의 "두 분의 번호 찾기", "번호 넣기"(`DEMOBOT_TG_CHAT=번호1,번호2`), "시험 메시지"를 하고 `sudo bash /root/demobot-src/deploy/demobot/on.sh`로 켭니다. 단체방 번호를 그대로 두면 지금처럼 단체방으로 옵니다.
6. 이어서 9번(healthchecks.io, 권장)과 10번 "한 번 해 보기"(암호는 선택)를 합니다.

---

## 13. 이 봇이 하지 않는 것

- **주문하지 않습니다.** 거래소 키가 없고, 주문 코드도 없습니다. 바이낸스 공개 시세만 읽습니다.
- **규칙봇을 건드리지 않습니다.** paperbot 서비스를 켜거나 끄지 않고, `/etc/paperbot`·`/var/lib/paperbot`·백업 폴더는 데모 랩 서비스에서 아예 보이지 않게 막혀 있습니다. 규칙봇 코드 폴더도 쓰지 않습니다.
- **서버를 정해진 만큼만 씁니다.** 평소 메모리 약 800 MB, 매시 몇 분 동안 순위표를 만들 때 최대 약 1.8 GB. 상한: 엔진 1.2 GB와 CPU 1개의 30%, 순위표 1.5 GB와 CPU 1개의 50%(매시 몇 분), 대시보드 300 MB, 밤 백업 300 MB(하루 한 번 1분 안쪽), 감시 150 MB(10분마다 몇 초). 우선순위도 규칙봇보다 낮습니다.
- **대시보드를 인터넷에 열지 않습니다.** Tailscale을 켠 두 분의 기기에서만 열립니다. 대시보드는 읽기만 합니다.
- **관점과 비공개 매매법을 밖으로 내보내지 않습니다.** 관점 기록은 서버의 데이터베이스와 두 분의 텔레그램으로 가는 밤 백업 파일에만, 비공개 매매법 파일은 `/etc/demobot/plugins`에만 있습니다(밤 백업에 들어가지 않습니다). 바깥으로 나가는 것은 바이낸스 공개 시세 읽기, 텔레그램, 그리고 넣었으면 healthchecks.io 신호(내용 없는 빈 신호)뿐입니다.
- **실제 돈을 쓰지 않습니다.** 어떤 계좌가 "우리 기준"을 통과해도 알려 줄 뿐이고, 실제 돈을 쓸지는 두 분이 정합니다. 통과 전에는 실제 돈 금지.
