# GH Coin 을 Vultr VPS 에서 24시간 돌리기 (Ubuntu 24.04)

GH Coin 은 **브라우저 창 안에서 돌아가는 봇**이라, 서버에 가상 화면을 만들고 그 안에서 Chrome 으로 띄웁니다.
화면은 Tailscale 을 켜고 주소를 열면 **웹 원격화면(noVNC)** 으로 실시간으로 보고 조작할 수 있습니다.

> 다른 봇(paperbot)과는 **다른 서버**에 설치하세요. 서로 영향이 없습니다.

## 1. 서버 만들기 (Vultr)

| 항목 | 고를 것 |
|---|---|
| 종류 | Cloud Compute – Shared CPU → **High Performance**(AMD 또는 Intel) |
| 사양 | **2 vCPU / 4 GB** (Regular 도 되지만 CPU 가 느림) |
| 위치 | **Seoul** (미국 지역 X — 바이낸스가 미국 IP 를 막음) |
| OS | **Ubuntu 24.04 LTS x64** |

## 2. 설치 (명령 2줄, 약 10분)

SSH(Termius 등)로 `root` 접속 후:

```bash
curl -fsSLo install-ghcoin.sh https://raw.githubusercontent.com/g1792091-boop/crypto-bot-research/claude/vigilant-shannon-irq1vg/vps/install-ghcoin.sh
sudo bash install-ghcoin.sh '구글 드라이브 공유 링크'
```

- 구글 드라이브 zip 공유는 설치하는 동안만 **링크가 있는 모든 사용자** 로 두면 됩니다. 끝나면 다시 **제한됨** 으로.
- 마지막에 **Tailscale 로그인 주소**가 나오면 열어서 다른 봇 서버와 **같은 계정**으로 로그인하세요.
- 끝나면 화면에 **접속 주소**와 **원격화면 비밀번호**가 나옵니다.

## 3. 화면 보기

Tailscale 켜고 → `http://<tailscale IP>:6080/` → 비밀번호 입력 → GH Coin 화면
(PC · 휴대폰 브라우저 모두 됨. 이 주소는 Tailscale 안에서만 열립니다.)

> GH Coin 주소(`127.0.0.1:17860`)를 내 PC 브라우저에서 직접 열면 **내 PC 에서 봇이 하나 더** 켜집니다. 꼭 위 원격화면 주소로 보세요.

## 4. 처음 한 번

- 원격화면 안의 GH Coin 에서 **🔑 AI 연결** → AI 키 입력
- 거래소 API 키: **출금 권한 없이**, IP 제한에 **이 VPS 의 공인 IP**(Vultr 서버 화면의 IP — Tailscale IP 아님) 추가

## 운영

| 할 일 | 명령 |
|---|---|
| 상태 · 메모리 보기 | `ghcoin-status` |
| 앱 창 새로 띄우기 | `sudo systemctl restart ghcoin-chrome` |
| 비밀번호 다시 보기 | `sudo cat /root/ghcoin-원격화면-비밀번호.txt` |

- 앱 창을 닫거나 Chrome 이 죽어도 10초 뒤 다시 열립니다. 서버가 재부팅돼도 자동으로 켜집니다.
- 매일 새벽 5:15 에 앱 창을 새로 띄워 메모리를 비웁니다 (설정 · 기록은 브라우저 저장소에 그대로).
- 메모리가 바닥나면 Chrome 만 정리하고 다시 켭니다 (earlyoom). 2GB 스왑도 잡아 둡니다.
- **사양 올릴 때**: `ghcoin-status` 의 `남은메모리` 가 500MB 밑으로 자주 내려가면 Vultr 에서 8GB 로 Resize.

## 측정값 (2026-10-03)

| 구성 | 메모리 |
|---|---|
| 전체 (가상 화면 + XFCE + 실행기 + Chrome·GH Coin + noVNC), 대기 | 약 0.7 GB |
| Chrome·GH Coin, 백테스트·지표 계산을 계속 돌린 최대치 | 약 0.9 GB 증가 |
| Ubuntu 기본 | 약 0.3–0.5 GB |

→ 4 GB 중 평소 1.3–1.8 GB, 무겁게 돌려도 2–2.7 GB. CPU 는 평소 0.1 코어, 백테스트를 계속 돌릴 때 1.3–1.6 코어.
