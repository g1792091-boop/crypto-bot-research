# GH Quant 를 내 컴퓨터가 아닌 곳에서 24시간 무료로 돌리기

추천: **오라클 클라우드 Always Free(평생 무료) 서버 + Tailscale(무료)**.
서버가 24시간 돌면서 오토파일럿 · AI 자동 모드 · AI 봇 · 에이전트 팀 브리핑을 계속 하고,
나는 폰이나 PC 브라우저로 언제든 들어가 봅니다. 내 컴퓨터는 꺼도 됩니다.

## 왜 오라클인가
| 선택지 | 24시간 | 무료 기간 | 바이낸스 선물 데이터 | 비고 |
|---|---|---|---|---|
| **오라클 클라우드 Always Free** | ✅ | 평생 | ✅ (한국·일본 리전) | 가입 때 카드 인증만 (무료 자원만 쓰면 청구 없음) |
| 구글 클라우드 e2-micro | ✅ | 평생 | ❌ 미국 리전만 무료 → 바이낸스가 막음 | |
| AWS 프리 티어 | ✅ | 12개월 | ✅ | 1년 뒤 유료 |
| Render · Railway · HF Spaces 무료 | ❌ 안 쓰면 잠듦 | | | 봇이 멈춤 |

## 1. 오라클 클라우드 가입 (10분)
1. https://www.oracle.com/kr/cloud/free/ → "무료로 시작하기"
2. **홈 리전을 "South Korea Central (Seoul)" 또는 "South Korea North (Chuncheon)"** 으로 고릅니다.
   나중에 못 바꾸고, 무료 서버는 홈 리전에만 만들 수 있습니다. **미국 리전은 고르지 마세요** (바이낸스 선물 데이터가 막힘).
3. 카드 인증을 합니다 (본인 확인용 · Always Free 자원만 쓰면 청구되지 않음).

## 2. 서버 만들기 (5분)
1. 콘솔 → **컴퓨트 → 인스턴스 → 인스턴스 생성**
2. 이미지: **Ubuntu 22.04 또는 24.04**
3. 모양(Shape):
   - 추천: **Ampere (VM.Standard.A1.Flex) 1~2 OCPU · 6~12GB** (무료 한도: 합계 4 OCPU · 24GB)
   - "용량 부족(Out of capacity)"이 나오면 잠시 뒤 다시 하거나 **VM.Standard.E2.1.Micro**(1GB, 이것도 무료)로. 설치 스크립트가 알아서 스왑을 만들어 줍니다.
4. SSH 키: **"개인 키 저장"** 을 눌러 키 파일을 받아 둡니다.
5. 생성 → 몇 분 뒤 **공인 IP 주소** 가 보입니다.

## 3. 서버에 접속 (SSH)
- Windows: PowerShell 에서 `ssh -i 받은키파일.key ubuntu@공인IP`
- Mac: 터미널에서 `chmod 600 받은키파일.key` 후 `ssh -i 받은키파일.key ubuntu@공인IP`

## 4. 한 줄 설치
지금 GitHub 저장소가 **비공개** 라서, 서버가 코드를 받으려면 **읽기 전용 토큰** 이 필요합니다 (1번만).

**4-1. 토큰 만들기 (2분)** — GitHub → 오른쪽 위 프로필 → Settings → Developer settings → Personal access tokens →
**Fine-grained tokens → Generate new token**
- Repository access: **Only select repositories → crypto-bot-research**
- Permissions → Repository permissions → **Contents: Read-only** (나머지는 그대로)
- 만든 토큰(`github_pat_…`)을 복사

**4-2. 서버에서 실행**
```bash
export GH_TOKEN=github_pat_여기에_붙여넣기
curl -fsSL -H "Authorization: token $GH_TOKEN" https://raw.githubusercontent.com/g1792091-boop/crypto-bot-research/claude/sweet-pascal-t82h6j/deploy/install.sh | sudo -E bash
```
(저장소를 공개로 바꿨다면 토큰 없이 `curl -fsSL https://raw.githubusercontent.com/.../deploy/install.sh | sudo bash` 만 해도 됩니다.
 설정 파일 · API 키는 저장소에 올라가지 않지만, 공개하면 코드는 누구나 볼 수 있습니다.)
물어보는 것:
- **접속 비밀번호** — 브라우저로 들어갈 때 쓸 비밀번호 (다른 사람이 못 들어오게)
- **NVIDIA / Gemini 키** — 무료 AI 키 (없으면 Enter, 나중에 화면의 'AI 모델' 창에서 넣어도 됨)
- **Tailscale 로 접속할지** — Y 권장 (아래 5-A)

설치가 끝나면 서비스로 등록돼서 **꺼지면 5초 뒤 자동으로 다시 켜지고, 서버를 재부팅해도 자동 시작**됩니다.

## 5-A. 접속 (권장) — Tailscale
포트를 인터넷에 열지 않고, 내 기기끼리만 암호화해서 연결합니다.
1. 설치 중 나온 주소를 열어 Tailscale 에 로그인 (구글 계정 등)
2. 폰 · PC 에도 **Tailscale 앱** 을 설치하고 같은 계정으로 로그인
3. 브라우저에서 설치 끝에 나온 주소 `http://100.x.x.x:8000` 접속 → 아이디는 아무거나, 비밀번호 입력

## 5-B. 접속 — 공인 IP 로 바로 (간단하지만 덜 안전)
설치 때 Tailscale 을 N 으로 하면 서버 방화벽의 8000 포트를 엽니다. 오라클 콘솔에서도 열어야 합니다:
**인스턴스 → 서브넷 → 기본 보안 목록 → 수신 규칙 추가**: 소스 CIDR `0.0.0.0/0`, 대상 포트 `8000`, TCP.
그 뒤 `http://공인IP:8000` 접속. http 는 암호화되지 않으니 **긴 비밀번호** 를 쓰세요.

## 자주 쓰는 명령
| 하고 싶은 것 | 명령 |
|---|---|
| 돌고 있는지 보기 | `sudo systemctl status gh-quant` |
| 실시간 로그 | `journalctl -u gh-quant -f` |
| 설정 바꾸기 (비밀번호 · 키) | `sudo nano /opt/gh-quant-data/settings.txt` → 저장 후 `sudo systemctl restart gh-quant` |
| 새 버전으로 업데이트 | `sudo bash /opt/gh-quant/deploy/update.sh` (토큰은 설치 때 저장돼서 다시 안 넣어도 됨) |
| 멈추기 / 다시 켜기 | `sudo systemctl stop gh-quant` / `sudo systemctl start gh-quant` |

기록(모의 계좌 · 봇 · AI 시그널 · 에이전트 팀 회의)은 `/opt/gh-quant-data/state` 에 남아서 업데이트해도 그대로입니다.

## 알아 둘 것
- **바이낸스 데이터 확인**: 화면 오른쪽 위가 "바이낸스 연결"이어야 합니다. "가상 데이터"로 나오면 서버가 바이낸스에 닿지 못하는 것 (리전 확인).
- **오라클 유휴 회수**: 오라클은 7일 동안 거의 안 쓰는 무료 서버를 회수할 수 있습니다. 걱정되면 계정을 **"Pay As You Go(종량제)"로 업그레이드** 하세요.
  무료 자원만 쓰면 여전히 0원이고, 회수 대상에서 빠집니다.
- **무료 AI 한도**: 24시간 돌면 AI 를 많이 부릅니다. 오토파일럿 화면 'AI 자동 모드'의 하루 호출 상한(기본 600)과 에이전트 팀 상한(400)을 넘으면 규칙 분석으로 대신합니다.
- **알림**: 브라우저 알림은 화면을 열어 둘 때만 뜹니다. 서버는 화면이 닫혀 있어도 계속 분석 · 모의 매매하고, 들어가면 'AI 상시 알림'과 '체결 내역'에 기록이 쌓여 있습니다.
- 기본은 분석·가상 체결만 합니다. 실거래는 'AI 사무실 → 실거래' 에서 직접 켜고 매매법마다 승인해야 하며 기본은 테스트넷입니다. 서버에 실거래 키를 둘 때는 APP_PASSWORD 를 꼭 쓰고, 출금 권한 없는 키만 쓰세요.
