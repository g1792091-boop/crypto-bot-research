# 5년 전체 조합 연구: 계산 서버 빌리기 → 돌리기 → 결과 보내기 → 삭제 (두 분용)

이 서버는 **계산만** 합니다. 바이낸스 공개 자료만 받고, 거래소 키·텔레그램·규칙봇·데모봇과 아무 관계가 없습니다.
다 끝나면 **반드시 삭제(Destroy)** 합니다. 끄기(Stop)만 하면 요금이 계속 나갑니다.

## 0. 먼저 (규칙봇 서버에서, 5분)

레버리지 구간 표(거래소가 정한 "몇 배까지 얼마어치" 표)가 필요합니다. 규칙봇 서버에 이미 있는 읽기 전용 키로 받습니다.
규칙봇 서버에 접속해서 아래를 붙여 넣으세요(한 줄입니다).

```bash
cd /root/crypto-bot-research && git pull && sudo bash -c 'set -a; . /etc/paperbot/live.env; set +a; /opt/paperbot/venv/bin/python research/fullgrid/dump_exchange.py'
```

`{"fetched_utc":...` 로 시작하는 긴 한 줄이 나옵니다. **그 줄 전체를 복사해서 채팅에 붙여 주세요.** 키는 들어 있지 않습니다
(거래소가 누구에게나 보여 주는 표입니다). 제가 저장소에 넣으면 1번으로 갑니다.

## 1. 서버 만들기 (Vultr, 5분)

1. Vultr → **Deploy +** → **Deploy New Server**
2. 종류: **Optimized Cloud Compute → CPU Optimized**
3. 위치: **Seoul** (없으면 Tokyo)
4. 운영체제: **Ubuntu 24.04 LTS x64**
5. 크기: **32 vCPU / 64 GB** (추천) — 16 vCPU / 32 GB도 됩니다(시간이 약 2배)
6. 자동 백업(Auto Backups)은 **끕니다**. 나머지는 그대로.
7. **Deploy Now** → 1~2분 뒤 서버 IP와 root 비밀번호가 나옵니다.

요금은 시간 단위입니다. 몇 시간 쓰고 지우면 그만큼만 나옵니다.

## 2. 돌리기 (명령 한 줄)

PC에서 접속: `ssh root@서버IP` (비밀번호는 Vultr 화면의 것, 붙여 넣어도 화면에 안 보이는 게 정상)

접속한 뒤 아래 **한 줄**을 붙여 넣습니다.

```bash
apt-get update -y && apt-get install -y git tmux && git clone -q -b claude/keen-pasteur-wav02u https://github.com/g1792091-boop/crypto-bot-research.git /root/fg/crypto-bot-research && tmux new -s fg "bash /root/fg/crypto-bot-research/research/fullgrid/bootstrap.sh; bash"
```

- 알아서 1/6 설치 → 2/6 자체 점검 → 3/6 자료 받기 → 4/6 계산 → 5/6 고르기·확인 → 6/6 결과 묶기를 합니다.
- **창을 닫아도 계속 돕니다.** (tmux 안에서 돕니다. 화면에서 빠져나오려면 `Ctrl+B` 누르고 손을 뗀 뒤 `D`.)
- `Could not get lock`이 보이면 새 서버가 자동 업데이트 중인 것이니 5분 뒤 같은 줄을 다시 붙여 넣으세요.

## 3. 진행 보기 (언제든)

```bash
ssh root@서버IP
bash /root/fg/crypto-bot-research/research/fullgrid/bootstrap.sh status
```

`계산 중: [grid 1234/5678 3.2h, ~4.1h left] ...` 처럼 남은 시간이 나옵니다. 화면을 다시 보려면 `tmux attach -t fg`.

**멈췄다면**(서버 재부팅, `멈춤:` 메시지): 2번의 `tmux new ...` 부분만 다시 실행하면 끝난 부분은 건너뛰고 이어서 합니다.

```bash
tmux new -s fg "bash /root/fg/crypto-bot-research/research/fullgrid/bootstrap.sh; bash"
```

`멈춤:` 이 나오면 그 화면을 복사해 보내 주세요.

## 4. 끝나면: 결과 보내기

화면에 `끝.`과 결과 요약이 나옵니다. 결과를 저에게 보내는 방법은 둘 중 하나입니다.

**(가) GitHub로 바로 올리기 (추천)**
1. GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token
2. Repository access: **Only select repositories** → `crypto-bot-research`
3. Permissions → Repository permissions → **Contents: Read and write**
4. 만료: **7일**
5. 계산 서버에서: `bash /root/fg/crypto-bot-research/research/fullgrid/bootstrap.sh push`
   - Username: GitHub 아이디, Password: 방금 만든 토큰(화면에 안 보이는 게 정상)
6. `보냈습니다: 브랜치 fullgrid-results-...` 가 나오면 채팅에 "결과 올렸어"라고 알려 주세요.
   (토큰은 계산 서버와 함께 지워집니다. 걱정되면 GitHub에서 토큰을 바로 삭제해도 됩니다.)

**(나) 파일로 받기**
PC의 명령창(PowerShell)에서: `scp root@서버IP:/root/fg/results.tgz .` → 받은 `results.tgz`를 채팅에 첨부.

## 5. 서버 삭제 (꼭)

결과를 보낸 뒤 Vultr → 서버 → **Server Destroy** (휴지통 아이콘). Stop이 아니라 **Destroy**입니다.

## 걸리는 시간과 비용 (2026-10-10 측정)

| 서버 | 계산 시간(예상) | 비용(예상) |
|---|---|---|
| 32 vCPU / 64 GB | (측정 후 적음) | (측정 후 적음) |
| 16 vCPU / 32 GB | (측정 후 적음) | (측정 후 적음) |

자료 받기 10~20분, 자체 점검 2~3분이 더 걸립니다.
