# 1번 트랙 2차(커스텀값): 계산 서버 빌리기 → 돌리기 → 결과 보내기 → 삭제 (두 분용)

이 서버는 **계산만** 합니다. 바이낸스 공개 가격 자료만 받고, 거래소 키·AI 키·텔레그램·규칙봇과 아무 관계가 없습니다.
다 끝나면 **반드시 삭제(Destroy)** 합니다. 끄기(Stop)만 하면 요금이 계속 나갑니다.

**언제 만드나**: 2번 트랙 서버(hiwr-compute)가 끝나 결과를 보내고 **그 서버와 디스크를 Destroy한 뒤**에 만듭니다.
Vultr 사용 한도 때문에 계산 서버는 한 번에 한 대입니다. (한도 증액이 승인되면 개발자가 "같이 만들어도 된다"고
알려 드립니다. 규칙은 그대로입니다.) 개발자가 "2차 고정했어요"라고 한 뒤에 만들면 기다리는 요금이 나가지 않습니다.

**순서 (손이 가는 건 다 합쳐 20분쯤)**

1. Vultr에서 서버 만들기 (1번, 5분)
2. 한 줄 붙여 넣기 (2번) + PC에서 비공개 파일 보내기 (2-C번, 1~2줄)
3. 그다음 약 10~20시간 동안 알아서 돕니다 (판정은 시작 뒤 약 6~15시간; 아래 표)
4. 끝나면 결과 보내기 (4번) → 서버와 디스크 Destroy (5번)

## 1. 서버 만들기 (Vultr, 5분)

1. Vultr → **Deploy +** → **Deploy New Server**
2. 크기: 추세 사냥·2번 트랙 때와 같은 **32 vCPU, 메모리 128GB** (vx1-g-32c-128g).
   사용 한도 증액이 승인됐으면 **64 vCPU**(목록에서 32 vCPU 바로 위)도 됩니다. 아래 표처럼 몇 시간 빨라지고 시간당
   요금은 약 2배라, 전체 요금은 비슷합니다.
3. 디스크: **100GB** (전처럼 Block Storage로 만들면 이름은 **hunt-r2-disk**)
4. 위치: **Tokyo** (**미국 위치는 고르지 마세요**), 운영체제: **Ubuntu 24.04 LTS x64**, 자동 백업(Auto Backups): **끔**
5. 이름(Hostname / Label): **hunt-r2-compute**
6. **Deploy Now** → 1~2분 뒤 서버 IP와 root 비밀번호가 나옵니다.

## 2. 돌리기 (명령 한 줄)

PC에서 접속: `ssh root@서버IP` (비밀번호는 Vultr 화면의 것. 붙여 넣어도 화면에 안 보이는 게 정상)

접속한 뒤 아래 **한 줄**을 붙여 넣습니다. 고정이 아직이면 2분마다 확인하다가 개발자가 고정하는 순간 **알아서** 시작하고,
이미 고정돼 있으면 바로 시작합니다. 커밋 번호를 적을 필요가 없습니다.

```bash
apt-get -o DPkg::Lock::Timeout=600 update -y && apt-get -o DPkg::Lock::Timeout=600 install -y git tmux && git clone -q -b claude/keen-pasteur-wav02u https://github.com/g1792091-boop/crypto-bot-research.git /root/hunt_r2/crypto-bot-research && cp /root/hunt_r2/crypto-bot-research/research/hunt_r2/wait_go_r2.sh /root/hunt_r2/wait_go_r2.sh && tmux new -s hunt-r2 "bash /root/hunt_r2/wait_go_r2.sh; bash"
```

- 알아서 1/11 설치 → 2/11 자체 점검 → 3/11 고정 확인 → 4/11 자료 받기 → 5/11 자료 확인 → **6/11 고르기(가장 김)**
  → 7/11 고른 것 고정 → 8/11 시험 전 표 → **9/11 시험(판정)** → 10/11 참고 분석 → 11/11 결과 묶기를 합니다.
- **창을 닫아도 계속 돕니다.** (화면에서 빠져나오려면 `Ctrl+B` 누르고 손을 뗀 뒤 `D`.)
- 이 한 줄은 **처음 한 번만** 씁니다. `already exists`가 보이면 아래 3번의 "이어서 하기" 줄을 쓰세요.
- `Could not get lock`이 보이면 새 서버가 자동 업데이트 중인 것이니 5분 뒤 같은 줄을 다시 붙여 넣으세요.
- 안전장치 (멈추면 정상입니다, 화면만 보내 주세요):
  - 코드가 고정된 커밋이 아니거나, 시험 코드가 통과하지 않거나, 고정 파일이 맞지 않으면 자료를 받기 전에 멈춥니다.
  - 5/11: 받은 자료가 1차 때 고정한 자료와 **숫자 하나라도** 다르면 계산하지 않고 멈춥니다.
  - 시험 기간(2024년 이후)은 고른 것이 고정된 **뒤에만**(9/11) 읽습니다. 고른 것이 없으면 시험 기간은 읽지 않습니다.
  - 6/11 전에 멈췄는데 개발자가 바로 못 고치면 **서버를 Destroy해도 잃는 것이 없습니다** (아직 계산 전).
- 24시간 안에 고정이 오지 않으면 멈추고 그 말을 화면에 남깁니다 (그때도 Destroy해도 잃는 것이 없습니다).

## 2-C. PC에서 비공개 파일 보내기 (장부용, 1~2줄)

2차의 **프로그램 전체 장부**는 1차와 2번 트랙에서 딥시크 매매법의 p값(비공개 파일 안)도 셉니다. 전에 서버를 지우기 전에
PC에 받아 둔 `private.tgz`를 새 서버로 보내 주세요. 서버는 그 안에서 **장부에 필요한 파일 두 개만** 꺼내고, 공개 결과에
적힌 지문(sha256)이 맞을 때만 p 칸만 읽습니다. 사람은 아무도 열어 보지 않습니다.

PC의 **PowerShell**에서, `private.tgz`가 있는 폴더에서(보통 PowerShell을 열면 바로 그 폴더) 아래 줄을 붙여 넣습니다.
`서버IP`만 바꾸세요. 비밀번호는 서버 비밀번호입니다.

1차(추세 사냥) 때 받은 것:

```
scp private.tgz root@서버IP:/root/r1_private.tgz
```

2번 트랙 때 받은 것 (이름이 같아 다른 폴더에 있거나 이름을 바꿔 두셨으면 그 이름으로):

```
scp private.tgz root@서버IP:/root/t2_private.tgz
```

- 2번 단계 줄을 붙여 넣은 **직후**에 하면 됩니다. 늦어도 고르기(6/11)가 끝나기 전까지 (보통 5시간 넘게 걸립니다).
- 어느 것이 어느 것인지 헷갈려도 괜찮습니다. 서버가 파일 안의 이름표만 보고 고릅니다. **보내는 이름만 서로 다르게** 하세요.
- 둘 다 이름이 `private.tgz`라서 한 폴더에 받으셨다면 나중 것(2번 트랙)만 남았을 수 있습니다. 있는 것만 보내세요.
- 없어도 계산은 그대로 됩니다. 장부에서 그 딥시크 줄이 p = 1(가장 불리하게)로 적힐 뿐이고 **판정에는 영향이 없습니다**.
- 제대로 갔는지는 3번의 status 줄에 `장부용 비공개 파일(.tgz) 2개 받음`처럼 나옵니다. 시험(9/11) 때 화면에
  `비공개 파일 sha256 일치` / `다름` / `없음`이 나옵니다.
- 이 파일들은 **채팅에 올리지 마세요.**

## 3. 진행 보기 (언제든)

```bash
bash /root/hunt_r2/crypto-bot-research/research/hunt_r2/bootstrap_r2.sh status
```

이렇게 나옵니다 (남은 시간은 길게 잡은 어림입니다):

```
진행 중: 6/11 고르기 (2021~2023만: 85개 이름의 숫자, 가짜 탐색 400번 포함, 작업 32개 동시에) (이 단계 140분째)
  남은 시간: 약 7시간 10분 (어림, CPU 32개 기준; 길게 잡은 값)
  작업: 가짜 탐색 (b′) 동전 200번 5200/17000 끝
  6/11 고르기가 가장 깁니다(5~15시간). 무거운 작업이 먼저 돌아 처음 몇 분의 남은 시간은 길게 나옵니다.
  남은 시간이 그대로여도 정상이니 다시 시작하지 마세요.
  장부용 비공개 파일(.tgz) 2개 받음 (시험 전에 확인합니다)
```

화면을 다시 보려면 `tmux attach -t hunt-r2`.

**멈췄다면 → 이어서 하기** (서버 재부팅, `멈춤:` 메시지, status가 "지금 돌고 있지 않습니다"): 아래 한 줄 전체를 붙여
넣으면 끝난 부분은 건너뛰고 이어서 합니다(고르기·시험·참고 분석 모두 끝난 조각부터). 고정 전이면 다시 기다립니다.
멈춘 뒤의 tmux 창이나 새 SSH 창 어디에서 붙여 넣어도 됩니다. 계산이 돌고 있을 때 붙여 넣으면 "이미 돌고 있습니다"만
나오고 아무것도 바뀌지 않습니다. status가 이 줄을 그대로 보여 주므로 거기서 복사해도 됩니다.

```bash
bash /root/hunt_r2/crypto-bot-research/research/hunt_r2/bootstrap_r2.sh idle && { tmux respawn-pane -k -t hunt-r2 "bash /root/hunt_r2/crypto-bot-research/research/hunt_r2/bootstrap_r2.sh; bash" 2>/dev/null || tmux new -d -s hunt-r2 "bash /root/hunt_r2/crypto-bot-research/research/hunt_r2/bootstrap_r2.sh; bash"; [ -n "$TMUX" ] || tmux attach -t hunt-r2; }
```

같은 `멈춤:`이 두 번 나오면 **그 화면을 그대로 복사해** 보내 주세요. `tail -50 /root/hunt_r2/run.log` 결과도 같이 주시면
더 빨리 고칩니다. **개발자가 "고쳤다"고 하면** 개발자가 주는 줄을 붙여 넣습니다 (코드는 계산 시작 전, 6/11 전에만
바꿀 수 있습니다).

## 4. 끝나면: 결과 보내기

화면에 `끝.`과 `판정: ...` 줄이 나옵니다. `참고(건너뛴 것)`이 같이 나오면 그 줄도 알려 주세요.

**(가) GitHub로 바로 올리기 (추천)**
1. GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token
2. Repository access: **Only select repositories** → `crypto-bot-research`, Permissions → **Contents: Read and write**, 만료 **7일**
3. 계산 서버에서: `bash /root/hunt_r2/crypto-bot-research/research/hunt_r2/bootstrap_r2.sh push`
   - Username: GitHub 아이디, Password: 방금 만든 토큰 (화면에 안 보이는 게 정상)
4. `보냈습니다: 브랜치 hunt-r2-results`가 나오면 채팅에 "2차 결과 올렸어"라고 알려 주세요.

**(나) 파일로 받기**: PC의 PowerShell에서 `scp root@서버IP:/root/hunt_r2/results.tgz .` → 채팅에 첨부.

딥시크 매매법의 돈 숫자는 규칙(D11)대로 결과 묶음에 넣지 않았습니다. Destroy 전에 PowerShell에서
`scp root@서버IP:/root/hunt_r2/private.tgz r2_private.tgz` 로 두 분 PC에 받아 두세요 (이번에는 이름을 `r2_private.tgz`로
받아 앞의 파일을 덮어쓰지 않게 합니다). **채팅에는 올리지 마세요.**

## 5. 서버 삭제 (꼭)

결과를 보낸 뒤 Vultr → 서버 → **Server Destroy**. 그다음 **Block Storage** 목록에 `hunt-r2-disk`가 남아 있으면 그것도
삭제합니다. **Stop이 아니라 Destroy**입니다.

## 걸리는 시간과 비용 (어림, 길게 잡은 값)

TIMING_TABLE_PLACEHOLDER
