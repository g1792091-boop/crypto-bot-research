# paper v3 서버 설치 (Vultr, 핸드폰으로 가능)

규칙은 `docs/paper-v3-rules.md`에 있습니다. 이 문서는 서버 설치 순서만 다룹니다.

**보안 원칙:** 키·비밀번호·토큰은 **서버 안에서만** 입력합니다. 채팅, 저장소, 스크린샷에 넣지 않습니다.

## 0. 준비물
- Vultr 계정
- 바이낸스 **읽기 전용** API 키. 서버를 만든 뒤 서버 IP로 제한해서 발급합니다(4번)
- 텔레그램 봇 토큰과 채팅 ID (선택)
- 핸드폰에 **Tailscale** 앱 (무료. 대시보드를 인터넷에 열지 않고 두 분 기기에서만 보게 해 줍니다)

## 1. 서버 만들기 (Vultr 웹, 핸드폰 브라우저 가능)
1. Deploy New Server → **Cloud Compute (Shared CPU)**
2. 지역: **Seoul, Tokyo, Singapore** 중 하나. 미국 지역은 바이낸스가 막습니다.
3. OS: **Ubuntu 24.04 LTS x64**
4. 크기: **4 vCPU / 8 GB** 권장. 195개 계좌와 36개 매매법 신호 계산에 코어 4개를 씁니다. 2 vCPU로 하려면 서비스 파일의 `--procs 4`를 `--procs 2`로 바꿉니다(신호 지연이 길어짐).
5. 만든 뒤 서버 화면의 **View Console**(웹 콘솔)로 접속합니다. root 비밀번호는 Vultr 화면에 있습니다.

## 2. 코드 받기
저장소가 비공개라면 GitHub에서 **이 저장소만 읽을 수 있는 토큰**(Fine-grained token, Contents: Read-only)을 만들어 서버에서만 씁니다.
```bash
apt-get update && apt-get install -y git
git clone -b claude/keen-pasteur-wav02u https://github.com/g1792091-boop/crypto-bot-research.git /root/crypto-bot-research
# 비밀번호를 물으면: 사용자명 = GitHub 아이디, 비밀번호 = 방금 만든 토큰
```

## 3. 설치 스크립트
```bash
cd /root/crypto-bot-research
sudo bash deploy/install.sh
```
이 스크립트가 하는 일:
- 방화벽: SSH만 열고 나머지는 모두 닫음
- fail2ban(무차별 로그인 차단), 자동 보안 업데이트, 시계 동기화(chrony)
- 전용 사용자 `paperbot`, Python 환경
- 서비스 등록 (아직 시작하지 않음)

## 4. 바이낸스 연결 확인과 키 넣기
```bash
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.live check
```
- 모든 줄이 `[OK]`인지 봅니다. `451`이나 `403`이 나오면 지역을 바꿔야 합니다.
- 서버 IP(Vultr 화면)로 제한한 **읽기 전용** 키를 바이낸스에서 만듭니다. 주문·출금 권한은 **끕니다.**
- 키 넣기:
  ```bash
  sudo nano /etc/paperbot/live.env
  ```
  `BINANCE_API_KEY=`, `BINANCE_API_SECRET=` 뒤에 붙여 넣고 저장합니다. 텔레그램도 같은 파일에 넣습니다.
- 다시 `check`를 돌려 레버리지 구간 줄이 `[OK]`인지 봅니다.

## 4-1. 봇 멈춤 알림 (서버 밖에서 감시)
서버가 꺼지거나 봇이 멈추면 봇 스스로는 알릴 수 없습니다. 그래서 서버 밖 감시 서비스를 씁니다.
1. https://healthchecks.io 무료 계정을 만들고 **Add Check**를 누릅니다. Period **1 minute**, Grace **5 minutes**로 설정합니다.
2. **Integrations**에서 두 분의 폰(텔레그램, 앱 푸시 또는 이메일)을 연결합니다.
3. 체크 주소(`https://hc-ping.com/...`)를 `/etc/paperbot/live.env`의 `DEADMAN_URL=` 뒤에 넣습니다.
- 봇은 **새 1분봉을 정상 처리하고 있을 때만** 1분마다 신호를 보냅니다. 서버 꺼짐, 봇 멈춤, 바이낸스 데이터 끊김 중 무엇이든 5분 넘게 이어지면 두 분 폰이 울립니다.
- 봇이 응답 없이 10분 멈추면 서버가 봇을 자동으로 재시작합니다 (systemd watchdog).
- 텔레그램: `TELEGRAM_CHAT_WARN`, `TELEGRAM_CHAT_INFO`를 비워두면 CRITICAL 채팅방으로 갑니다. 강제청산·재계산 불일치는 바로 울리고, 파산·낙폭은 1시간에 한 번 묶어서 **무음**으로, 매일 점검 요약도 무음으로 옵니다.

## 5. 대시보드 비밀번호
```bash
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.dash hash   # 12자 이상 비밀번호 두 번 입력
openssl rand -hex 32                                                      # 비밀 값 생성
sudo nano /etc/paperbot/dash.env
```
- 첫 줄 결과를 `DASH_PASSWORD_HASH=` 뒤에, 두 번째 결과를 `DASH_SECRET=` 뒤에 넣습니다.

## 6. Tailscale로 대시보드 열기 (인터넷에는 열지 않음)
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up            # 나온 링크를 핸드폰에서 열어 두 분 계정으로 승인
tailscale ip -4              # 100.x.y.z 주소가 나옴
sudo ufw allow in on tailscale0
```
- `/etc/paperbot/dash.env`의 `DASH_HOST=`를 그 `100.x.y.z` 주소로 바꿉니다.
- 핸드폰에서 Tailscale 앱에 같은 계정으로 로그인한 뒤, 브라우저에서 `http://100.x.y.z:8080`을 엽니다.
- 친구분도 같은 Tailscale 네트워크에 초대하면 볼 수 있습니다.

## 7. 시작
```bash
sudo systemctl enable --now paperbot-live3 paperbot-dash paperbot-liq paperbot-daily3.timer paperbot-backup.timer
sudo journalctl -u paperbot-live3 -f          # 첫 몇 분 로그 보기 (Ctrl+C로 나가기)
sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.live3 status --db /var/lib/paperbot/paper3.db
```
- 처음 시작할 때 5분봉 기록 400일치를 바이낸스에서 받느라 몇 분 걸립니다.
- 대시보드의 **서버 상태** 탭에서 "봇 생존 신호: 정상"을 확인합니다.

## 운영
| 일 | 방법 |
|---|---|
| 재시작 | `sudo systemctl restart paperbot-live3`. 계좌 상태는 저장돼 있어 이어서 돕니다. 꺼져 있던 동안의 신호는 "늦음"으로 기록만 됩니다 |
| 매일 점검 | 09:20(한국 시간)에 자동. paper와 재계산 일치, 지정가·놓친 신호 그림자 기록, 데이터 품질 |
| 청산 기록 | `paperbot-liq`가 바이낸스 강제청산 흐름을 `liq.db`에 모읍니다(공개 자료, 키 필요 없음). 바이낸스는 청산의 과거 자료를 주지 않아서 첫날부터 켜 둡니다. 확인: `sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.liqstream status --db /var/lib/paperbot/liq.db` |
| 백업 | 매일 08:40(한국 시간) `/var/backups/paperbot/날짜/`, 14일 보관 |
| 코드 업데이트 | `cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh`. 배포는 **한 분만** 합니다. 커밋 안 된 수정이 있으면 멈추고, 돌던 서비스는 교체하는 순간만 멈췄다가 다시 켜집니다. 이전 코드는 `/opt/crypto-bot-research.old`에 남습니다. 봇은 켜질 때마다 코드 버전·설정을 기록하고, 체결·청산·사이즈 코드가 바뀌었으면 알림을 보냅니다 (규칙상 그 기간을 다시 셈) |
| 비밀번호 로그인 끄기 (권장) | SSH 키를 등록한 뒤 `/etc/ssh/sshd_config`에서 `PasswordAuthentication no`. 키 등록 전에 끄면 들어갈 수 없게 되니, Vultr 웹 콘솔이 되는지 먼저 확인 |

## 실거래 준비: 테스트넷 주문 연습 (가짜 돈)
실거래 전에 주문 처리가 제대로 되는지 바이낸스 **테스트넷**에서 연습합니다. 코드가 테스트넷 주소만 허용하므로 실제 돈에 주문이 나갈 수 없습니다.
1. https://testnet.binancefuture.com 에서 테스트넷 계정과 API 키를 만듭니다(실제 계정 키와 별개).
2. 서버의 `/etc/paperbot/live.env`에 `TESTNET_API_KEY=`, `TESTNET_API_SECRET=`를 넣습니다.
3. 연습 실행:
   ```bash
   sudo -u paperbot bash -c 'set -a; . /etc/paperbot/live.env; /opt/paperbot/venv/bin/python -m paperbot.testnet drill --symbol BTCUSDT'
   ```
4. 확인하는 것: 한 방향 모드·격리 마진·레버리지 설정 → 시장가 진입 체결 → **거래소에 걸린 손절**(마지막 체결가 기준으로 바꿀 예정: `docs/paper-v3-rules-addendum.md` Q4. 지금 연습 코드는 아직 마크 가격이라 실거래 연습 전에 고칩니다) → 잠금선 올리기(새 손절 먼저, 옛 손절 나중 취소: 보호 공백 없음) → 재시작 점검(손절 없는 포지션 발견·복구) → 청산 → 포지션·주문 0개. 모든 줄이 `[OK]`여야 합니다.
