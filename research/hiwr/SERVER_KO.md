# 2번 트랙(승률 70% + 낙폭 한도): 계산 서버 빌리기 → 돌리기 → 결과 보내기 → 삭제 (두 분용)

이 서버는 **계산만** 합니다. 바이낸스 공개 가격 자료만 받고, 거래소 키·AI 키·텔레그램·규칙봇과 아무 관계가 없습니다.
다 끝나면 **반드시 삭제(Destroy)** 합니다. 끄기(Stop)만 하면 요금이 계속 나갑니다.

**언제 만드나**: 추세 사냥 서버(hunt-compute)가 끝나서 결과를 보내고 **그 서버를 Destroy한 뒤**에 만듭니다.
두 서버를 동시에 두지 않습니다 (Vultr 월 요금 한도). 개발자가 "2번 트랙 고정했어요"라고 한 뒤에 만들면 기다리는 요금이
나가지 않습니다.

**순서 (손이 가는 건 다 합쳐 15분쯤)**

1. Vultr에서 서버 만들기 (1번, 5분)
2. 한 줄 붙여 넣기 (2번). 그다음 약 12 ~ 20시간 (반나절 ~ 하루) 동안 알아서 돕니다 (맨 아래 표).
3. 끝나면 결과 보내기 (4번) → 서버 Destroy (5번)

## 1. 서버 만들기 (Vultr, 5분)

추세 사냥 서버를 만들 때와 **같은 방법**입니다.

1. Vultr → **Deploy +** → **Deploy New Server**
2. 크기: 추세 사냥 때와 같은 **32 vCPU, 메모리 128GB** (vx1-g-32c-128g). 회색이라 안 골라지면 고를 수 있는 것 중
   **가장 큰 것**을 고르세요 (결과는 같고 시간만 늘어납니다).
3. 디스크: 서버에 딸린 디스크만 씁니다. **Block Storage는 만들지 마세요.** 디스크 여유가 60GB보다 적으면 시작하자마자
   멈추고 알려 줍니다.
4. 위치: **Tokyo** (**미국 위치는 고르지 마세요**), 운영체제: **Ubuntu 24.04 LTS x64**, 자동 백업(Auto Backups): **끔**
5. 이름(Hostname / Label): **hiwr-compute**
6. **Deploy Now** → 1~2분 뒤 서버 IP와 root 비밀번호가 나옵니다.

## 2. 돌리기 (명령 한 줄)

PC에서 접속: `ssh root@서버IP` (비밀번호는 Vultr 화면의 것. 붙여 넣어도 화면에 안 보이는 게 정상)

접속한 뒤 아래 **한 줄**을 붙여 넣습니다. 고정이 아직이면 2분마다 확인하다가 개발자가 고정하는 순간 **알아서** 시작하고,
이미 고정돼 있으면 바로 시작합니다.

```bash
apt-get -o DPkg::Lock::Timeout=600 update -y && apt-get -o DPkg::Lock::Timeout=600 install -y git tmux && git clone -q -b claude/keen-pasteur-wav02u https://github.com/g1792091-boop/crypto-bot-research.git /root/hiwr/crypto-bot-research && cp /root/hiwr/crypto-bot-research/research/hiwr/wait_go.sh /root/hiwr/wait_go.sh && tmux new -s hiwr "bash /root/hiwr/wait_go.sh; bash"
```

- 알아서 1/10 설치 → 2/10 자체 점검 → 3/10 고정 확인 → 4/10 연습 기간 자료 받기 → 5/10 자료 확인 → **6/10 고르기(가장 김)**
  → 7/10 고른 것 고정 → 8/10 확인 기간 시험 → 9/10 참고 분석 → 10/10 결과 묶기를 합니다.
- **창을 닫아도 계속 돕니다.** (화면에서 빠져나오려면 `Ctrl+B` 누르고 손을 뗀 뒤 `D`.)
- 이 한 줄은 **처음 한 번만** 씁니다. `already exists`가 보이면 아래 3번의 "이어서 하기" 줄을 쓰세요.
- 안전장치 (멈추면 정상입니다, 화면만 보내 주세요):
  - 코드가 고정된 커밋이 아니거나, 시험 코드가 통과하지 않거나, 고정 파일이 맞지 않으면 자료를 받기 전에 멈춥니다.
  - 5/10: 받은 자료가 고정된 자료 기준과 **숫자 하나라도** 다르면 계산하지 않고 멈춥니다.
  - 확인 기간(2024년 이후) 자료는 고른 것이 고정된 **뒤에만**(8/10) 받습니다.
  - 6/10 전에 멈췄는데 개발자가 바로 못 고치면 **서버를 Destroy해도 잃는 것이 없습니다** (아직 계산 전).
- 기다리는 동안 진행 보기(3번)를 하면 "고정된 커밋을 기다리는 중입니다"가 나옵니다. 아무것도 붙여 넣지 않아도 됩니다.
- 12시간 안에 고정이 오지 않거나 기다리는 중에 서버가 재부팅되면, 3번의 "이어서 하기" 줄을 붙여 넣으면 다시
  기다립니다 (그때도 Destroy해도 잃는 것이 없습니다).

## 3. 진행 보기 (언제든)

```bash
bash /root/hiwr/crypto-bot-research/research/hiwr/bootstrap.sh status
```

이렇게 나옵니다 (남은 시간은 길게 잡은 어림입니다):

```
진행 중: 6/10 고르기 (연습 기간 2021~2023만: 조합 약 100만 개 × 청산 162가지, 작업 32개 동시에) (이 단계 300분째)
  남은 시간: 약 11시간 41분 (어림, CPU 32개 기준; 길게 잡은 값)
  지금: 고르기 시작 (반나절쯤 걸릴 수 있습니다; 진행: bash /root/hiwr/crypto-bot-research/research/hiwr/bootstrap.sh status)
  고르기 작업: 120/435 끝 (무거운 작업이 먼저 시작해서 끝 무렵에 몰려 끝납니다)
  6/10 고르기는 이 연구에서 가장 깁니다(하루 이상일 수 있음). 남은 시간이 그대로여도 정상이니 다시 시작하지 마세요.
```

화면을 다시 보려면 `tmux attach -t hiwr`.

**멈췄다면 → 이어서 하기** (서버 재부팅, `멈춤:` 메시지, status가 "지금 돌고 있지 않습니다"): 아래를 붙여 넣으면 끝난 부분은
건너뛰고 이어서 합니다. 멈춘 뒤의 tmux 창이나 새 SSH 창에서 붙여 넣으세요. **계산이 돌고 있는 tmux 화면 안에는 아무것도
붙여 넣지 마세요.** 새 SSH 창에서 붙여 넣으면 "이미 돌고 있습니다"만 나오고 아무것도 바뀌지 않습니다.

```bash
bash /root/hiwr/crypto-bot-research/research/hiwr/bootstrap.sh idle && { tmux respawn-pane -k -t hiwr "bash /root/hiwr/crypto-bot-research/research/hiwr/bootstrap.sh; bash" 2>/dev/null || tmux new -d -s hiwr "bash /root/hiwr/crypto-bot-research/research/hiwr/bootstrap.sh; bash"; [ -n "$TMUX" ] || tmux attach -t hiwr; }
```

같은 `멈춤:`이 두 번 나오면 **그 화면을 그대로 복사해** 보내 주세요. `tail -50 /root/hiwr/run.log` 결과도 같이 주시면
더 빨리 고칩니다. **개발자가 "고쳤다"고 하면** 개발자가 주는 줄을 붙여 넣습니다 (코드는 계산 시작 전, 6/10 전에만 바꿀 수
있습니다).

## 4. 끝나면: 결과 보내기

화면에 `끝.`이 나옵니다. `참고(건너뛴 것)`이 같이 나오면 그 줄도 알려 주세요.

**(가) GitHub로 바로 올리기 (추천)**
1. GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token
2. Repository access: **Only select repositories** → `crypto-bot-research`, Permissions → **Contents: Read and write**, 만료 **7일**
3. 계산 서버에서: `bash /root/hiwr/crypto-bot-research/research/hiwr/bootstrap.sh push`
   - Username: GitHub 아이디, Password: 방금 만든 토큰 (화면에 안 보이는 게 정상)
4. `보냈습니다: 브랜치 hiwr-results`(같은 이름이 이미 있으면 `hiwr-results-날짜`)가 나오면 채팅에 "2번 트랙 결과
   올렸어"라고 알려 주세요.

**(나) 파일로 받기**: PC의 명령창(PowerShell)에서 `scp root@서버IP:/root/hiwr/results.tgz .` → 채팅에 첨부.

딥시크 매매법의 돈 숫자는 규칙(D11)대로 결과 묶음에 넣지 않았습니다. Destroy 전에
`scp root@서버IP:/root/hiwr/private.tgz .` 로 두 분 PC에 받아 두세요. **채팅에는 올리지 마세요.**

## 5. 서버 삭제 (꼭)

결과를 보낸 뒤 Vultr → 서버 → **Server Destroy**. **Stop이 아니라 Destroy**입니다.

## 걸리는 시간과 비용 (어림)

근거: 2026-10-12 이 개발 컴퓨터에서 연습 기간 자료(BTC, 2024-01 전만)로 실제 고르기 코드를 돌려 잰 시간을 30개
코인 · 32 vCPU로 늘리고 1.3배를 더했습니다. 확인 기간 자료로는 아무것도 돌리지 않았습니다.

| 단계 | 32 vCPU |
|---|---|
| 설치 · 자체 점검 · 고정 확인 | 약 15분 |
| 연습 기간 자료 받기 · 확인 (30개 코인 1분봉, 약 4GB) | 약 30분 ~ 1시간 |
| 고르기 (조합 약 100만 개 × 청산 162가지) | 약 10 ~ 14시간 |
| 확인 기간 자료 받기 · 시험 (고른 것만) | 약 1 ~ 2시간 |
| 참고 분석 (고른 것 여러 개를 동시에; 12시간 뒤에는 새로 시작하지 않음) | 약 30분 ~ 3시간 |
| **합계** | **약 12 ~ 20시간 (반나절 ~ 하루)** |

- 요금은 **Vultr 화면의 시간당 값**이 정확합니다. 32 vCPU가 시간당 약 $1.2이면 약 **$15 ~ 25**입니다.
- 서버 크기는 **결과에 영향이 없습니다.** 같은 계산을 몇 개로 나눠 동시에 하느냐만 다릅니다.
- 끝난 뒤 Destroy를 잊으면 그 시간만큼 계속 요금이 나갑니다.
