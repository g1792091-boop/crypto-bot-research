# 데모 랩 봇 설치 (규칙봇 서버에 함께)

데모 랩은 48개의 **모의** 계좌로 S2·N02·N04 매매법의 모든 설정을 실시간으로 비교하는 봇입니다.

- **주문하지 않습니다.** 거래소 키가 없고 필요도 없습니다. 바이낸스 공개 시세만 읽습니다.
- 규칙봇과 **완전히 따로** 돕니다. 사용자, 코드 사본, 데이터베이스, 서비스, 대시보드 포트(8090), 텔레그램 봇이 모두 따로입니다.
- 도는 것: 엔진 `demobot-live`(15분마다 계좌 계산), 대시보드 `demobot-dash`, 순위표 `demobot-rank`(매시 7분에 몇 분 동안 모든 설정의 순위를 다시 만듦, 타이머 `demobot-rank.timer`).

아래 상자는 서버에 root로 접속한 화면(`root@…:~#`)에 하나씩 붙여 넣습니다. 상자 밑의 "보여야 할 것"과 다르면 멈추고, 그 화면을 개발자에게 보냅니다.

순서: 0 점검 → 1 설치 → 2 텔레그램 → 3 대시보드 비밀번호 → 4 첫 채우기와 켜기 → 5 대시보드 열기

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

## 2. 텔레그램 (새 봇, 새 단체방)

**폰에서 (명령 없음)**

1. 텔레그램에서 `@BotFather`를 열고 `/newbot`을 보냅니다. 이름은 `데모 랩 봇`, 아이디는 영문으로 `bot`으로 끝나게 짓습니다(예: `demolab_우리이름_bot`).
2. BotFather가 주는 **토큰**(숫자:영문으로 된 긴 줄)을 복사합니다. 토큰은 **채팅·메모·메일에 붙이지 않습니다.** 아래 서버 편집기 안에만 붙입니다.
3. BotFather에 `/setprivacy`를 보내고 → 이 봇을 고르고 → `Disable`을 누릅니다. 그래야 봇이 단체방에 쓴 `관점 …` 줄을 읽을 수 있습니다(기본값이면 봇은 `/`로 시작하는 명령만 받습니다). 대신 봇을 단체방의 관리자로 만들어도 됩니다.
4. 텔레그램에서 **새 단체방**을 만듭니다(이름 예: `데모 랩`). 두 분과 새 봇만 넣습니다. 규칙봇 알림방과 **다른 방**입니다.
   봇을 방에 넣은 **뒤에** 3번을 했다면, 봇을 방에서 뺐다가 다시 넣어야 적용됩니다.
5. 그 방에 `/start@봇아이디`를 한 번 보냅니다(예: `/start@demolab_우리이름_bot`).

**서버에서: 토큰 넣기**

```bash
SUDO_EDITOR=nano sudoedit /etc/demobot/demobot.env
```

편집기에서 `DEMOBOT_TG_TOKEN=` 줄 끝에 토큰을 붙여 넣습니다. 저장 Ctrl+O, Enter, 종료 Ctrl+X.

**방 번호 찾기** (토큰은 화면에 나오지 않습니다)

```bash
cd /opt/demobot/app && sudo -u demobot /opt/demobot/venv/bin/python -m demobot.notify chatid
```

- 보여야 할 것: `방 번호 -100…   이름 데모 랩   (supergroup)` 같은 줄. 그 번호(마이너스 포함)를 씁니다. 줄 끝에 `번호가 … 로 바뀜`이 있으면 바뀐 번호를 씁니다.
- `최근 메시지가 없습니다`가 나오면 그 방에 `/start@봇아이디`를 다시 보내고 이 상자를 다시 붙여 넣습니다.

**방 번호 넣기**

```bash
SUDO_EDITOR=nano sudoedit /etc/demobot/demobot.env
```

`DEMOBOT_TG_CHAT=` 줄 끝에 번호를 적고 저장(Ctrl+O, Enter, Ctrl+X).

**시험 메시지**

```bash
cd /opt/demobot/app && sudo -u demobot /opt/demobot/venv/bin/python -m demobot.notify test
```

- 보여야 할 것: `보냈습니다`, 그리고 새 단체방에 `🧪 데모 랩 테스트 메시지`.
- `토큰이 틀렸습니다` / `방 번호가 틀렸거나` 줄이 나오면 그 줄이 말하는 대로 고치고 다시 합니다.
- 데모 랩 알림은 모두 무음으로 옵니다(규칙봇과 같음). 15분마다 거래가 있을 때 한 번 묶어서, 아침 9시에 하루 요약이 옵니다. 관점 줄(6번)에는 바로 답합니다.

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

- 보여야 할 것: `demobot-live.service: active`, `demobot-dash.service: active`, `demobot-rank.timer: active`. 텔레그램 단체방에 `▶️ 데모 랩 시작` 메시지가 옵니다.
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

두 분의 관점(어느 코인이 어느 구간에서 오를지·내릴지)을 데모 랩 단체방에 **한 줄**로 쓰면, 봇이 기록하고 48시간 동안 시장을 따라가며 채점합니다. 주문은 하지 않습니다.

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
- 관점과 번호는 **이 서버의 데이터베이스에만** 남습니다. GitHub(코드 저장소)에는 올라가지 않습니다.
- 데모 랩 단체방(`DEMOBOT_TG_CHAT`)에서 쓴 줄만 받습니다. 봇이 답하지 않으면 2단계 3번(`/setprivacy` → `Disable`)을 확인합니다.

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
| 끄기 (엔진·대시보드·순위표 모두, 재부팅 뒤에도 꺼진 채) | `sudo bash /root/demobot-src/deploy/demobot/off.sh` |
| 켜기 (설정 파일을 바꾼 뒤 다시 읽힐 때도) | `sudo bash /root/demobot-src/deploy/demobot/on.sh` |
| 상태 보기 | `systemctl status demobot-live demobot-dash demobot-rank.timer --no-pager` |
| 순위표 시간표 보기 (지난번·다음 실행) | `systemctl list-timers demobot-rank.timer` |
| 순위표 기록 보기 | `journalctl -u demobot-rank -n 30 --no-pager` |
| 기록 보기 | `journalctl -u demobot-live -n 50 --no-pager` |
| 업데이트 (개발자가 알려 줄 때만) | `cd /root/demobot-src && git pull && sudo bash deploy/demobot/update.sh` |
| 지우기 (데이터와 설정은 남김) | `sudo bash /root/demobot-src/deploy/demobot/uninstall.sh` |
| 모두 지우기 (데이터·설정·사용자까지) | `sudo bash /root/demobot-src/deploy/demobot/uninstall.sh --purge` |

- 업데이트는 데모 랩의 코드만 다시 복사하고, 켜져 있던 데모 랩 서비스만 다시 시작합니다(꺼 둔 것은 꺼진 채). 이전 코드는 `/opt/demobot/app.old`에 남습니다.
- 끄고 켜도 데이터는 그대로이고, 켜면 이어서 돕니다.

---

## 9. 이 봇이 하지 않는 것

- **주문하지 않습니다.** 거래소 키가 없고, 주문 코드도 없습니다. 바이낸스 공개 시세만 읽습니다.
- **규칙봇을 건드리지 않습니다.** paperbot 서비스를 켜거나 끄지 않고, `/etc/paperbot`·`/var/lib/paperbot`·백업 폴더는 데모 랩 서비스에서 아예 보이지 않게 막혀 있습니다. 규칙봇 코드 폴더도 쓰지 않습니다.
- **서버를 정해진 만큼만 씁니다.** 평소 메모리 약 800 MB, 매시 몇 분 동안 순위표를 만들 때 최대 약 1.8 GB. 상한: 엔진 1.2 GB와 CPU 1개의 30%, 순위표 1.5 GB와 CPU 1개의 50%(매시 몇 분), 대시보드 300 MB. 우선순위도 규칙봇보다 낮습니다.
- **대시보드를 인터넷에 열지 않습니다.** Tailscale을 켠 두 분의 기기에서만 열립니다. 대시보드는 읽기만 합니다.
- **관점과 비공개 매매법을 밖으로 내보내지 않습니다.** 관점 기록은 서버의 데이터베이스에만, 비공개 매매법 파일은 `/etc/demobot/plugins`에만 있습니다.
- **실제 돈을 쓰지 않습니다.** 어떤 계좌가 "우리 기준"을 통과해도 알려 줄 뿐이고, 실제 돈을 쓸지는 두 분이 정합니다. 통과 전에는 실제 돈 금지.
