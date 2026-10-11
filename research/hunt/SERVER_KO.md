# 추세 사냥 · 알트 급등: 계산 서버 빌리기 → 돌리기 → 결과 보내기 → 삭제 (두 분용)

이 서버는 **계산만** 합니다. 바이낸스 공개 가격 자료만 받고, 거래소 키·AI 키·텔레그램·규칙봇·데모봇과 아무 관계가 없습니다.
다 끝나면 **반드시 삭제(Destroy)** 합니다. 끄기(Stop)만 하면 요금이 계속 나갑니다.

왜 서버에서 하나: 이 개발 컴퓨터(4코어, 남은 디스크 약 2.5GB)에는 1분봉 정밀 재확인 자료가 들어가지 않고, 계산도 몇 시간 걸립니다.

**순서 (손이 가는 건 다 합쳐 15분쯤)**

1. Vultr에서 서버 만들기 (1번, 5분)
2. 한 줄 붙여 넣기 (2번). 그다음 1~2시간 반 동안 알아서 돕니다.
3. 끝나면 결과 보내기 (4번) → 서버 Destroy (5번)

## 1. 서버 만들기 (Vultr, 5분)

1. Vultr → **Deploy +** → **Deploy New Server**
2. 종류: **Optimized Cloud Compute → CPU Optimized**
3. 위치: **Tokyo** (없으면 Seoul이나 Singapore. **미국 위치는 고르지 마세요**)
4. 운영체제: **Ubuntu 24.04 LTS x64**
5. 크기: **32 vCPU** 짜리. 목록에 없거나 회색이라 안 골라지면 고를 수 있는 것 중 가장 큰 것으로 하세요.
   64 vCPU도 되지만 시간은 조금만 줄고 시간당 요금은 약 2배입니다 (아래 "걸리는 시간과 비용").
6. 자동 백업(Auto Backups)은 **끕니다**.
7. 이름(Server Hostname / Label): **hunt-compute**
8. **Deploy Now** → 1~2분 뒤 서버 IP와 root 비밀번호가 나옵니다.

## 2. 돌리기 (명령 한 줄)

PC에서 접속: `ssh root@서버IP` (비밀번호는 Vultr 화면의 것. 붙여 넣어도 화면에 안 보이는 게 정상)

접속한 뒤 아래 **한 줄**을 붙여 넣습니다. 줄 안의 커밋 번호(두 군데)는 검토를 마친 코드의 번호입니다. 개발자가 채팅으로
준 줄이 있으면 그 줄을 쓰세요.

```bash
apt-get update -y && apt-get install -y git tmux && git clone -q -b claude/keen-pasteur-wav02u https://github.com/g1792091-boop/crypto-bot-research.git /root/hunt/crypto-bot-research && git -C /root/hunt/crypto-bot-research checkout -q GO_COMMIT_HERE && tmux new -s hunt "HUNT_GO=GO_COMMIT_HERE bash /root/hunt/crypto-bot-research/research/hunt/bootstrap.sh; bash"
```

- 알아서 1/9 설치 → 2/9 자체 점검 → 3/9 고정 확인 → 4/9 자료 받기 → 5/9 자료 확인 → 6/9 추세 사냥 계산
  → 7/9 알트 급등 → 8/9 정밀 재확인 → 9/9 결과 묶기를 합니다. 자체 점검은 몇 분 동안 화면이 조용한 게 정상입니다.
- **창을 닫아도 계속 돕니다.** (tmux 안에서 돕니다. 화면에서 빠져나오려면 `Ctrl+B` 누르고 손을 뗀 뒤 `D`.)
- `Could not get lock`이 보이면 새 서버가 자동 업데이트 중인 것이니 5분 뒤 같은 줄을 다시 붙여 넣으세요.
- 이 한 줄은 **처음 한 번만** 씁니다. 한 번 붙여 넣은 뒤에는(`already exists`가 보이면) 아래 3번의 "이어서 하기" 줄을 쓰세요.
- 안전장치 (멈추면 정상입니다, 화면만 보내 주세요):
  - 시작 전: 코드가 검토를 마친 커밋이 아니면 멈춥니다.
  - 2/9·3/9: 시험 코드가 통과하지 않거나, 규칙·코드·자료 기준이 고정된 그대로가 아니면 자료를 받기 전에 멈춥니다.
  - 5/9: 받은 자료(가격·거래량·펀딩·마크 가격)가 고정된 자료와 **숫자 하나라도** 다르면 계산하지 않고 멈춥니다.
  - 여기까지(5/9 이전)에서 멈췄는데 개발자가 바로 못 고치면 **서버를 Destroy해도 잃는 것이 없습니다** (아직 계산 전).

## 2-B. 자기 전에 미리 걸어 두기 (고정이 아직 안 됐을 때)

두 분이 주무시기 전에 서버를 만들고 아래 **한 줄**을 붙여 넣어 두면, 서버가 2분마다 확인하다가 개발자가 시험 규칙을
고정하는 순간 **알아서** 위의 1/9~9/9를 시작합니다. 커밋 번호를 적을 필요가 없습니다(개발자가 고정한 커밋을 서버가
받아서 그대로 씁니다. 안전장치는 위와 같습니다). 알트 급등은 이미 끝나서 이번에는 돌리지 않습니다.

```bash
apt-get -o DPkg::Lock::Timeout=600 update -y && apt-get -o DPkg::Lock::Timeout=600 install -y git tmux && git clone -q -b claude/keen-pasteur-wav02u https://github.com/g1792091-boop/crypto-bot-research.git /root/hunt/crypto-bot-research && cp /root/hunt/crypto-bot-research/research/hunt/wait_go.sh /root/hunt/wait_go.sh && tmux new -s hunt "bash /root/hunt/wait_go.sh; bash"
```

- 화면에 "아직 고정 전입니다. 기다리는 중..."이 2분마다 나오면 정상입니다. 창을 닫고 주무셔도 됩니다.
- 아침에: 아래 3번의 status 줄로 확인 → `끝.`이면 4번(결과 보내기) → 5번(Destroy).
- 14시간 안에 고정이 안 오면 멈추고 그 말을 화면에 남깁니다 (그때는 Destroy해도 잃는 것이 없습니다).

## 3. 진행 보기 (언제든)

```bash
ssh root@서버IP
bash /root/hunt/crypto-bot-research/research/hunt/bootstrap.sh status
```

이렇게 나옵니다 (남은 시간은 어림이고 처음 몇 분은 들쭉날쭉합니다):

```
진행 중: 6/9 추세 사냥 계산 (v1·넓게 고르기 → 두 시험, 작업 32개 동시에) (이 단계 12분째)
  남은 시간: 약 64분 (어림, CPU 32개 기준; 처음 몇 분은 들쭉날쭉)
  지금: wide 시험 (2024-01 ~ 2026-09, 한 번만)
```

화면을 다시 보려면 `tmux attach -t hunt`.

**멈췄다면 → 이어서 하기** (서버 재부팅, `멈춤:` 메시지, status가 "지금 돌고 있지 않습니다"): 아래를 붙여 넣으면 끝난 부분은
건너뛰고 이어서 합니다 (이미 열린 tmux 창 안이라면 먼저 `exit`로 빠져나온 뒤). 처음에 정한 설정은 서버에 남아 있어서 이 줄에는
따로 적을 것이 없습니다.

```bash
tmux kill-session -t hunt 2>/dev/null; tmux new -s hunt "bash /root/hunt/crypto-bot-research/research/hunt/bootstrap.sh; bash"
```

같은 `멈춤:`이 두 번 나오면 **그 화면을 그대로 복사해** 보내 주세요. 아래 줄의 결과도 같이 주시면 더 빨리 고칩니다.

```bash
tail -50 /root/hunt/run.log
```

**개발자가 "고쳤다"고 하면**: 개발자가 주는 줄(`bash /root/hunt/crypto-bot-research/research/hunt/bootstrap.sh update 커밋번호`)을
붙여 넣은 뒤, 위의 "이어서 하기" 줄을 붙여 넣습니다. 코드는 계산을 시작하기 전(6/9 전)에만 바꿀 수 있습니다.

## 4. 끝나면: 결과 보내기

화면에 `끝.`이 나옵니다. `참고(건너뛴 것)`이 같이 나오면 그 줄도 알려 주세요 (예: 정밀 재확인 명령이 아직 코드에 없을 때).

`거의 끝: ... 알트 급등 5분봉 2차 확인이 끝나지 않았습니다`가 나오면: 몇 분 뒤 "이어서 하기" 줄을 한 번 더 붙여 넣으세요
(빠진 파일만 다시 받습니다). 또 같은 말이 나오면 아래 (가)로 결과를 보내고 화면을 보내 주세요. 이때는 개발자가
"Destroy 해도 된다"고 할 때까지 서버를 두세요 (시간당 약 $1).

결과를 저에게 보내는 방법은 둘 중 하나입니다.

**(가) GitHub로 바로 올리기 (추천)**
1. GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token
2. Repository access: **Only select repositories** → `crypto-bot-research`
3. Permissions → Repository permissions → **Contents: Read and write**
4. 만료: **7일**
5. 계산 서버에서: `bash /root/hunt/crypto-bot-research/research/hunt/bootstrap.sh push`
   - Username: GitHub 아이디, Password: 방금 만든 토큰 (화면에 안 보이는 게 정상. 올리기가 되면 다시 묻지 않습니다)
   - `토큰이 틀렸거나 권한이 없습니다`가 나오면 토큰을 확인하고 같은 줄을 다시 붙여 넣으세요 (아이디·토큰을 다시 묻습니다).
6. `보냈습니다: 브랜치 hunt-results` 가 나오면 채팅에 "결과 올렸어"라고 알려 주세요.
   (토큰은 계산 서버와 함께 지워집니다. 걱정되면 GitHub에서 토큰을 바로 삭제해도 됩니다.)

**(나) 파일로 받기**
PC의 명령창(PowerShell)에서: `scp root@서버IP:/root/hunt/results.tgz .` → 받은 `results.tgz`를 채팅에 첨부.

딥시크 매매법의 돈 숫자는 규칙(D11)대로 결과 묶음에 넣지 않았습니다. 그 파일을 두 분 PC에 보관하려면 Destroy 전에
`scp root@서버IP:/root/hunt/private.tgz .` 로 받아 두세요. **채팅에는 올리지 마세요.**

## 5. 서버 삭제 (꼭)

결과를 보낸 뒤 Vultr → 서버 → **Server Destroy** (휴지통 아이콘). **Stop이 아니라 Destroy**입니다.
Stop은 서버가 꺼져 있어도 요금이 계속 나갑니다.

## 걸리는 시간과 비용 (어림)

근거: 계산 시간은 가짜(합성) 자료로 개발 컴퓨터에서 잰 값(2026-10-11)을 32·64 vCPU로 늘려 잡고 넉넉히 2배를 더했습니다.
자료 받기는 이번 30개 코인 자료를 받을 때 걸린 시간에서 잡았습니다. 실제 자료로는 아직 한 번도 돌리지 않았습니다 (사전 등록 규칙).

| 단계 | 32 vCPU | 64 vCPU |
|---|---|---|
| 설치 · 자체 점검 · 고정 확인 | 약 10분 | 약 10분 |
| 자료 받기 · 확인 (30개 코인 5분봉, float64로 저장해 약 1.1GB) | 약 15~20분 | 약 15~20분 |
| 추세 사냥 계산 (v1 + 넓게 762개 시스템 · 후보 686개, 두 시험) | 약 15분 ~ 1시간 | 약 10분 ~ 50분 |
| 알트 급등 | 약 5 ~ 15분 | 약 5 ~ 15분 |
| 정밀 재확인 (1분봉 받기 + 계산) | 약 20 ~ 40분 | 약 20 ~ 40분 |
| **합계** | **약 1 ~ 2시간 반** | **약 1 ~ 2시간** |

- 알트 급등에서 1차를 통과한 것이 있으면, 5분봉 2차 확인 자료를 한 번에 2개씩 받느라(사전 등록 규칙) **1시간 남짓 더**
  걸릴 수 있습니다. 그때 status에 `알트 급등 2차 자료: 받은 수/전체 파일`이 나옵니다.
- 요금은 **Vultr 화면에 나오는 시간당 값**이 정확합니다. 지난번 풀그리드 때 32 vCPU가 **약 $1/시간**이었으니
  32 vCPU면 약 $1 ~ 3 (알트 2차 확인이 있으면 $1쯤 더), 64 vCPU는 시간당 값이 약 2배라 약 $2 ~ 4 정도입니다.
- 64 vCPU는 계산 단계만 조금 빨라지고 자료 받기는 같아서, 전체 시간은 크게 줄지 않습니다. 그래서 32 vCPU를 권합니다.
- 서버 크기는 **결과에 영향이 없습니다.** 같은 계산을 몇 개로 나눠 동시에 하느냐만 다릅니다.
- 끝난 뒤 Destroy를 잊으면 그 시간만큼 계속 요금이 나갑니다.
