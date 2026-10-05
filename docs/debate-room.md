# 24시간 토론방 (유료 API, 선택)

AI들이 paper 실험의 숫자를 두고 하루 종일 짧게 토론하는 방입니다. 대시보드 **회의실** 탭 아래 '24시간 토론방' 카드에서 읽기만 하시면 됩니다. 코드는 `paperbot/agents/debate.py`, 서비스 이름은 `paperbot-debate`입니다.

**이 방은 두 분의 Anthropic API 크레딧(유료)으로 돌고, 처음에는 꺼져 있습니다.** 에이전트 방(Claude Max 구독으로 도는 회의)과는 완전히 별개이고, 에이전트 방은 이 API 키를 볼 수 없고 구독 대신 API로 바뀌지도 않습니다.

## 무엇이고 무엇이 아닌가
- 하는 일: 정해진 간격마다 **API를 한 번** 불러 토론 3~5마디(낙관론자, 비관론자, 회의론자, 리스크 책임자, 퀀트가 돌아가며, 한국어, 한 마디 4문장 이하)와 정리 한 줄, 가설 0~2개, 새 매매법 연구실에 줄 아이디어 0~2개를 받아 적습니다.
- 자료: 코드가 봇의 데이터(paper3.db, daily3.db, agents3.db, checkpoint.db)를 **읽기만 해서** 작게 만든 요약 하나입니다(현재 D+며칠, 계좌 상황, 청산 거래 수, 좋은 자리 vs 보통, 상위·하위 매매법과 표본 크기, 그림자 비교, 밤 점검, 눈에 띄는 알림, 전에 한 토론의 정리). AI는 이 요약의 숫자만 쓰도록 되어 있고, 표본이 작으면 "표본 작음"이라고 말해야 합니다.
- **하지 않는 일**: 주문, 규칙·계좌·코드 변경, 봇 데이터베이스에 쓰기. 30일 체크포인트 전에는 결론을 말하지 않고, 관찰 기간(실행 시작 후 21일, 날짜는 코드가 시작일에서 계산해 패킷 `meta.observation`에 넣음)에는 원본 계좌의 규칙 변경을 제안하지 않습니다(아이디어 목록으로만). 실험을 다시 시작하면(paper v4) 그 전 실행에서 한 주장은 채점하지 않고 '무효(이전 실행)'로 닫습니다. 매매 지시도 하지 않습니다.
- 가설은 코드가 채점합니다(AI가 아니라). 고를 수 있는 종류는 네 가지뿐입니다: ① 어떤 매매법·봉 계좌의 앞으로 N건 평균 ROE가 0보다 작다/크다, ② 앞으로 N건에서 좋은 자리가 보통보다 노출당 손익이 크다, ③ 밤 점검이 앞으로 N번 모두 불일치 0개다, ④ D+N일에 파산 계좌가 k개 이하다. 메뉴에 없거나 숫자가 범위를 벗어나면 코드가 버리고 '버림'으로 기록합니다. 사람별 적중 기록이 대시보드에 나오지만, 채점된 가설이 10개 미만이면 표본이 작은 것이라 아무것도 말해 주지 않습니다.
- 토론 내용은 AI가 쓴 **의견**입니다. 숫자 자체도 이 방이 아니라 대시보드의 원래 화면이 기준입니다.

## 비용 (먼저 `once --dry-run`으로 직접 재 보세요)
한 회차는 API 호출 **한 번**입니다(토론 전체가 한 답에 들어 있음). 고정 앞부분(규칙·역할·메뉴, 약 1,700 토큰)에 `cache_control`을 붙여 두고, 회차마다 바뀌는 자료는 작게(주제 하나, 평균 약 1,400~1,600 토큰, 상한 3,500) 만듭니다. 출력은 `max_tokens`로 막습니다: 기본 900, 생각을 하는 모델(Sonnet 5.5)은 생각과 답을 합쳐 1,500(생각 토큰도 이 상한 안에 들어감).

서버에서 키 없이, API 호출 없이 재는 법(안 쓰고 숫자만 봅니다):
```
cd /opt/crypto-bot-research && sudo -u paperbot-debate /opt/paperbot/venv/bin/python -m paperbot.agents.debate once --dry-run
```
이 명령은 모든 주제(11개)의 자료를 만들어 토큰 수를 추정하고 아래와 같은 표를 냅니다. **아래 표는 이 저장소의 합성 자료(156계좌, 10일, 하루 150건 청산)로 잰 것**이고(주제 9개일 때; v4 값은 아래 "Sonnet 5.5로 켜기"), 토큰은 코드가 센 추정값(한글은 글자마다 1토큰 안팎으로 넉넉히 셈)입니다. 실제 서버 값은 달라질 수 있으니 켜기 전에 위 명령을 직접 돌려 보시고, 켠 뒤에는 `status`의 "회당 평균"(API가 알려 준 실제 토큰)을 보세요.

측정 가정: 입력 3,100 토큰(고정 1,716 + 자료 평균 1,384), 출력 800 토큰, 캐시 읽기 없음(아래 설명), 30일 한 달. 단가는 100만 토큰당 입력/출력 달러: Haiku 4.5 $1/$5, Sonnet 5.5 $2/$10. **단가는 코드에 넣은 값이라 Anthropic 콘솔에서 꼭 다시 확인하세요**(환경 변수 `DEBATE_PRICE_IN`, `DEBATE_PRICE_OUT`으로 바꿀 수 있고, 바꿔도 월 한도 계산만 달라집니다. 실제 청구는 콘솔 기준입니다).

| 모델 | 간격 | 회당 | 한 달 (건너뛰기 없음) | 한 달 (약 30% 건너뜀) |
|---|---|---|---|---|
| Haiku 4.5 | 10분 | $0.0071 | $30.67 | $21.47 |
| Haiku 4.5 | **20분(기본)** | $0.0071 | $15.34 | $10.74 |
| Haiku 4.5 | 30분 | $0.0071 | $10.22 | $7.16 |
| Haiku 4.5 | 60분 | $0.0071 | $5.11 | $3.58 |
| Sonnet 5.5 | 10분 | $0.0142 | $61.34 | $42.94 |
| Sonnet 5.5 | 20분 | $0.0142 | $30.67 | $21.47 |
| Sonnet 5.5 | 30분 | $0.0142 | $20.45 | $14.31 |
| Sonnet 5.5 | 60분 | $0.0142 | $10.22 | $7.16 |

- **건너뛰기**: 지난 토론 뒤 청산이 10건 미만이고 새 경고 알림도, 새 밤 점검도 없으면 그 회차는 API를 부르지 않고 '건너뜀(바뀐 것 없음)'으로만 기록합니다(비용 0). 30%는 가정일 뿐이고, 실제 비율은 청산이 얼마나 자주 나느냐에 달렸습니다(청산이 자주 나면 거의 건너뛰지 않음). 6시간 동안 건너뛰기만 했으면 한 번은 돌립니다. 기준은 `DEBATE_MIN_NEW_TRADES`.
- **출력이 값의 절반 이상**입니다(Haiku: 출력 800토큰 $0.0040, 입력 3,100토큰 $0.0031). 비용을 줄이려면 간격을 늘리는 것이 가장 확실하고, 그다음이 발언 수(`DEBATE_TURNS` 3)입니다.
- **프롬프트 캐시**: 고정 앞부분은 약 1,700토큰이라 Haiku 4.5의 캐시 최소 길이(4,096토큰)에 못 미쳐 캐시되지 않고(Sonnet 5.5는 최소 512토큰이라 캐시됨: 아래 "Sonnet 5.5로 켜기"), 5분 캐시는 10분 이상 간격에서는 어차피 사라집니다. 그래서 위 표는 캐시 없이 셉니다. 코드는 간격이 50분 이하면 1시간짜리 캐시 표시(쓰기 2배, 읽기 0.1배)를 붙여 두므로, 모델의 최소 길이를 넘으면 `status`에 캐시 읽기가 잡히고 회당 최대 약 $0.0015(Haiku) 아낍니다. 50분보다 길면 표시를 붙이지 않습니다(쓰기 할증만 내고 못 읽으므로).
- Sonnet 5.5는 기본으로 '생각'을 하고 그 토큰도 출력으로 청구됩니다(API의 `usage.output_tokens`에 들어 있어 코드의 비용·월 한도에도 그대로 셈). `DEBATE_EFFORT=low`(요청의 `output_config.effort`로 보냄)는 생각을 짧게 하고, `DEBATE_THINKING=between_tools`는 생각을 끕니다. `DEBATE_THINKING=disabled`는 Sonnet 5.5가 거절하므로(400) 서비스가 시작하지 않고 고칠 방법을 알려 줍니다. 위 표는 생각 토큰을 뺀 값입니다.
- 월 한도 `DEBATE_MONTHLY_USD_CAP`(기본 $40)은 코드가 API가 알려 준 사용량으로 세는 **부드러운 한도**입니다. 한도의 80%에서 텔레그램 경고 한 번, 95%부터 호출을 멈추고(그 회차의 최악 비용이 한도를 넘을 때도 시작하지 않음) 다음 달(한국 시간 1일)에 저절로 이어집니다. 그래서 한도를 넘지 못하지만, **진짜 안전장치는 Anthropic 콘솔의 지출 한도**입니다. 둘 다 설정하세요. 폭주를 막는 시간당 한도(`DEBATE_HOURLY_USD_CAP`, 기본 월 한도÷24)도 있습니다.

## Sonnet 5.5로 켜기 (두 분 결정 2026-10-05: Sonnet 5.5, 30분, 월 $30, effort low)
paper v4 재시작 뒤 점검이 끝나면 켭니다. 크레딧은 **$30 선불**, 콘솔 지출 한도 **$30**, 자동 충전(auto reload) **끔**.

`debate.env`에 넣을 줄(키 넣는 법은 아래 "서버에서 켜기"의 `sudoedit`; 키는 편집기 안에만, 채팅·명령줄에는 절대 쓰지 않기):
```
DEBATE_MODEL=claude-sonnet-5-5
DEBATE_EVERY_MIN=30
DEBATE_MONTHLY_USD_CAP=30
DEBATE_EFFORT=low
```
`DEBATE_THINKING`과 `DEBATE_MAX_TOKENS`는 비워 둡니다(생각은 Sonnet 5.5 기본, 출력 상한은 생각까지 담는 1,500이 저절로 쓰임).

순서(서버에서):
1. 키 없이 비용 재 보기(키·API 호출 없음; 이 명령은 `debate.env`를 읽지 않으므로 네 설정을 명령에 직접 줌, 키는 주지 않음):
   ```
   cd /opt/crypto-bot-research && sudo -u paperbot-debate env DEBATE_MODEL=claude-sonnet-5-5 DEBATE_EVERY_MIN=30 DEBATE_MONTHLY_USD_CAP=30 DEBATE_EFFORT=low /opt/paperbot/venv/bin/python -m paperbot.agents.debate once --dry-run
   ```
   `설정 모델 claude-sonnet-5-5 … (월 한도 $30)`, `캐시가 잡히면 …`, `생각(thinking) … effort low, 출력 상한 1,500` 줄이 나오면 됩니다.
2. 키 넣기: `SUDO_EDITOR=nano sudoedit /etc/paperbot/debate.env` (위 네 줄도 이때 고침)
3. 켜기: `sudo systemctl enable --now paperbot-debate`
4. 확인: `sudo -u paperbot-debate /opt/paperbot/venv/bin/python -m paperbot.agents.debate status` 의 첫 줄이 `돌고 있음`이고 둘째 줄이 `모델 claude-sonnet-5-5 (effort low) (생각 adaptive(기본)), 30분 간격`. `journalctl -u paperbot-debate -n 20 --no-pager` 에 `회차 0 … 출력 N 토큰(생각 블록 n개 포함), $0.0…`.

**v4 모양에서 잰 비용**(키·API 없이 `once --dry-run`을 v4 합성 자료, 331계좌·6일·거래 4,410건에 돌린 값, 주제 11개, 2026-10-05): 고정 앞부분 약 1,967토큰, 회차 자료 평균 1,839(가장 큰 것 '딥시크 가족별 차이' 3,020)토큰, 출력 추정 800토큰. 2026-10-06부터 고정 앞부분에 이번 실행의 규칙(그룹별 계좌 수, 규칙 B, 그룹별 청산, 30일 판정 방법; `agents/facts.py`)이 들어가 약 3,500토큰(추정)이 됩니다(캐시되는 부분).

| Sonnet 5.5, 30분 | 회당 | 한 달(1,440회, 건너뛰기 없음) |
|---|---|---|
| 캐시 없이 | 약 $0.016 | $22.48 |
| 고정 앞부분 캐시(1시간 캐시, 읽기 0.1배) | 약 $0.012 | $17.38 |
| 생각 토큰 회당 평균 100개마다 | +$0.0010 | +$1.44 |

- 생각은 effort low에서 짧지만 양은 모델이 정합니다. 위 표에 생각을 더하면 회당 평균 생각이 300토큰일 때 한 달 약 $22~27, 600토큰이면 약 $26~31입니다. 코드는 월 $30의 95%($28.50)에서 멈추고 다음 달에 이어 가므로 넘지 않습니다. 실제 값은 켠 다음 날 `status`의 "최근 7일 회당 평균"(API가 알려 준 출력 토큰, 생각 포함)으로 확인하세요.
- 계좌가 331개라 30분마다 새 청산이 10건을 넘는 일이 거의 늘 있어 **건너뛰기는 거의 일어나지 않는다고 보고** 셉니다(위 표는 건너뛰기 0%).
- 토론 자료의 표(league, 순위, 봉별, 코인별, 청산 방식)는 잠긴 매매법 36개 계좌와 같은 봉의 동전 봇만 셉니다. 딥시크·릴스 5분 단타·5분봉 동전은 평소에는 `meta.groups`에 그룹별 계좌 수로만 들어가고 섞지 않습니다.
- 주제는 11개를 돌아가며 씁니다. 파산·긴급 알림·밤 점검 문제는 **새로 생긴 때만** 한 번 끼어듭니다(앞 회차가 본 표시 `agenda_marks`보다 파산 수가 늘었거나, 더 새 긴급 알림, 처음 보는 밤 점검 날; early_kline 불일치는 세지 않음). 그 밖에는 순서대로 돕니다. v4에서 늘어난 두 주제(paperbot/agents/debate_packet.py `TOPICS`):
  - **묶음 비교: 기존 36 · 딥시크 · 5분봉(영상) vs 같은 봉 동전 봇**(`groups_compare`): 묶음마다 전체와 봉별로 계좌 수, 거래 수, 계좌당 거래 수, 승률, 손익 합계, 잔고 중앙값, 파산 수, 표본 작음 표시를 같은 봉의 동전 봇 3개(릴스는 5분봉 동전) 숫자 옆에 둡니다. 딥시크 칸만은 돈 숫자(손익·잔고)가 없고 거래 수·계좌당 거래·승률·파산과 같은 봉 동전 봇 대비 부호(`vs_coin_flip`)만 있습니다(D11, `paperbot/agents/dsmoney.py`의 `DS_MONEY_STRICT`; 두 분이 풀기로 하면 False).
  - **딥시크 가족별 차이**(`ds_families`): 가족 17개를 네 담당(구조·유동성 / 추세·눌림 / 세션·시가 / 반전·되돌림)으로 나눠 같은 숫자(돈 숫자 없이)를, 딥시크 봉(15분·30분·1시간·4시간)의 동전 봇 숫자와 함께 둡니다.
  - 둘 다 paper3.db에서 읽기만 해서 만들고(에이전트 방이 읽는 packets3의 `groups`), 다른 주제와 같은 정직 규칙을 자료 안에 적어 둡니다: 30일 체크포인트 전에는 참고일 뿐(결론 없음), 계좌당 거래 30건 미만은 표본 작음, 묶음끼리 합계 손익을 바로 견주지 않고 같은 봉 동전 봇과 계좌당 숫자로 봄, 가족 17개를 견주면 우연히 좋아 보이는 가족이 나옴. 회차 자료 상한 3,500토큰 안입니다(위 측정에서 2,804과 3,020). `[ds200] …` 같은 그룹 알림 줄은 알림 목록에는 보이지만 계좌의 긴급 상황으로 세지 않습니다(주제를 끌어오지 않음). 가설은 여전히 36개 매매법 계좌만 다룹니다.

## 작게 시작하기: 선불 $5~10, 60분 간격
1. 아래 "계정·크레딧·키 만들기"를 하되 크레딧은 **$5 또는 $10 선불**, 자동 충전은 **끕니다**.
2. `debate.env`에 이렇게 넣습니다(키는 아래 "키 넣기"로):
   ```
   DEBATE_EVERY_MIN=60
   DEBATE_MONTHLY_USD_CAP=8
   ```
   Haiku 4.5, 60분 간격은 위 표대로 한 달 $3.6~5 정도라 $5로 한 달, $10으로 두 달쯤 갑니다. 월 한도 $8은 크레딧($10)보다 작게 둔 값입니다.
3. 하루 뒤 `status`의 "회당 평균"과 이번 달 사용액으로 실제 값을 보고, 괜찮으면 간격을 30분, 20분으로 줄입니다. 크레딧이 떨어지면 방이 'API 잔액 부족'으로 멈추고 텔레그램이 오며, 충전하면 저절로 이어집니다.

## 계정·크레딧·키 만들기 (두 분이 브라우저에서, 한 번)
Claude Max 구독과 API 크레딧은 **별개**입니다(구독으로는 API를 쓸 수 없습니다).
1. `console.anthropic.com`에 접속해 계정을 만들고 로그인합니다(구독 계정과 같은 메일을 써도 됩니다).
2. Billing(결제)에서 카드를 등록하고 크레딧을 삽니다. 처음에는 $5~10, **자동 충전(auto reload)은 끕니다**.
3. 지출 한도(spend limit)를 정합니다: 월 한도를 크레딧이나 두 분이 쓰고 싶은 금액(예: $10 또는 $40)으로 둡니다. 코드의 월 한도와 별개의, 콘솔이 지키는 진짜 한도입니다. 한도를 바꾸면 코드의 `DEBATE_MONTHLY_USD_CAP`도 그보다 작게 맞추세요.
4. API keys 화면에서 새 키를 만들고(이름 예: `paperbot-debate`) 화면에 한 번만 나오는 키(`sk-ant-`로 시작)를 복사해 둡니다. **이 키를 채팅, 메일, 문서에 붙이지 마세요.**
5. 키가 새거나 의심되면 같은 화면에서 그 키를 지우면 즉시 쓸 수 없습니다.

## 서버에서 켜기
먼저 `deploy/install.sh`를 돌려 설치합니다(아래 "적용"). 설치만 되고 **켜지지 않습니다**.

**키 넣기(채팅·셸 기록에 남기지 않는 방법):**
```
SUDO_EDITOR=nano sudoedit /etc/paperbot/debate.env
```
편집기가 열리면 `ANTHROPIC_API_KEY=` 뒤에 콘솔에서 복사한 키를 **편집기 안에 붙여 넣고**(터미널 앱의 붙여넣기), 필요하면 아래 `DEBATE_EVERY_MIN=`, `DEBATE_MONTHLY_USD_CAP=`도 고칩니다. 저장은 Ctrl+O, Enter, 종료는 Ctrl+X. 키를 `echo`, `export`, 명령줄에 쓰지 마세요(셸 기록에 남습니다).
- 접속이 끊긴 채 편집기를 닫았다면 임시 복사본이 남을 수 있습니다: `ls /var/tmp/debate.env* /etc/paperbot/*.save* 2>/dev/null` 에 뭔가 나오면 `sudo rm -f` 로 지웁니다(키가 들어 있을 수 있음).
- 키가 들어갔는지(내용은 안 보이게): `sudo grep -c '^ANTHROPIC_API_KEY=.' /etc/paperbot/debate.env` 가 `1`이면 들어간 것입니다.
- 파일 권한: `ls -l /etc/paperbot/debate.env` 가 `-rw-r----- 1 root paperbot-debate` 로 보여야 합니다(`paperbot` 사용자는 읽을 수 없음).

**먼저 비용 재 보기(키·API 없이):** 위 "비용"의 `once --dry-run` 명령.

**켜기와 확인:**
```
sudo systemctl enable --now paperbot-debate
sudo -u paperbot-debate /opt/paperbot/venv/bin/python -m paperbot.agents.debate status
cd /opt/crypto-bot-research && sudo /opt/paperbot/venv/bin/python -m paperbot.launchcheck --stage after
journalctl -u paperbot-debate -n 30 --no-pager
```
시작하면 첫 회차가 곧바로 돕니다(1분 안쪽, 약 1센트). 이후는 설정한 간격마다입니다. 키를 명령줄에 올려 시험하지 말고, 켠 뒤 `status`와 대시보드로 확인하세요.

**끄기:** `sudo systemctl disable --now paperbot-debate` (진행 중인 호출 하나는 끝까지 받아 저장하고 멈춥니다). 다시 켤 때는 `sudo systemctl enable --now paperbot-debate`. 기록(`/var/lib/paperbot/debate/debate.db`)은 남습니다.

**설정을 바꾸기(한도 올리기, 간격, 모델):** `SUDO_EDITOR=nano sudoedit /etc/paperbot/debate.env` 에서 `DEBATE_MONTHLY_USD_CAP`, `DEBATE_EVERY_MIN`, `DEBATE_MODEL` 등을 고치고 `sudo systemctl restart paperbot-debate`. 한도를 올릴 때는 **콘솔의 지출 한도도 함께** 올리세요. 이번 달 한도에 닿아 멈춘 방은 한도를 올리고 다시 시작하면 바로 이어집니다.

**새 코드 반영:** 설치 스크립트는 토론방을 멈추거나 다시 시작하지 않습니다(돈이 드는 서비스라서). 코드를 업데이트한 뒤 `sudo systemctl restart paperbot-debate`.

## 적용: 설치 스크립트는 봇을 잠깐 다시 시작합니다
토론방을 서버에 넣으려면 `deploy/install.sh`(`docs/server-setup-v3.md` 13-5)를 돌려야 하고, 이 스크립트는 코드를 바꿔 끼우는 동안 live 봇(paperbot-live3), 대시보드 등을 잠깐 멈췄다 다시 시작합니다. 봇은 저장된 상태에서 이어 가지만, 15분봉이 닫히는 순간과 겹치지 않게 **15분 경계(:00, :15, :30, :45) 직후**에 하세요. 이 스크립트가 하는 일: 사용자 `paperbot-debate`와 폴더 `/var/lib/paperbot/debate` 만들기, `/etc/paperbot/debate.env`(root:paperbot-debate 640)를 빈 틀로 만들기(없을 때만, 있으면 건드리지 않음, `agents.env`의 텔레그램 두 줄 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_CRITICAL`만 복사하고 화면에 찍지 않음), 서비스 파일 설치(켜지 않음).

## 키가 어떻게 따로 보관되나
- 키는 `/etc/paperbot/debate.env` 한 곳뿐이고, 파일 주인 root, 그룹 `paperbot-debate`, 권한 640입니다. 에이전트·대시보드·live 봇·주문 실행기는 사용자 `paperbot`(또는 `paperbot-exec`)로 돌아 이 그룹에 없어 **읽을 수 없습니다**(그 서비스의 `/proc/<pid>/environ`도 다른 사용자라 못 읽습니다).
- 토론방 서비스 파일(`paperbot-debate.service`)은 이 파일 하나만 `EnvironmentFile`로 읽고, systemd가 읽은 뒤에는 `/etc/paperbot` 전체가 서비스에 보이지 않게 막습니다(다른 키 파일 포함). 쓸 수 있는 곳은 `/var/lib/paperbot/debate` 하나이고 봇의 DB는 읽기 전용입니다. 에이전트·대시보드 서비스 파일도 이 파일을 명시적으로 숨깁니다.
- 에이전트의 Claude 실행기는 환경 변수 허용 목록(`runner.ENV_ALLOW`)에 `ANTHROPIC_API_KEY`가 없고, 있으면 구독이 API 과금으로 바뀌므로 시작을 거부합니다. 이 목록과 키 파일 권한은 테스트(`tests/test_debate_deploy.py`)와 `launchcheck`가 지킵니다.
- 키는 환경에서만 읽고 로그, 데이터베이스, 오류 문구, 텔레그램에 쓰지 않으며(오류 문구에서 키 모양은 `***`로 가림), 저장소 파일에는 없습니다.
- `launchcheck`는 이 방이 설치 안 됨·꺼짐이면 `[참고]`만, 켜졌는데 키가 비어 있으면 `[고칠 것]`, 켜져 있으면 마지막 토론 시각과 이번 달 사용액을 보여 줍니다. 키 파일 권한이 root:paperbot-debate 640이 아니면 `[고칠 것]`입니다.

## 멈추면 (텔레그램이 한국어로 알립니다)
오류가 나도 계속 두드리지 않습니다: 1분부터 두 배씩, 최대 30분 간격으로 쉬었다 다시 시도하고(429의 `retry-after`는 지킴), 같은 원인의 경고는 한 시간에 한 번, 다시 돌기 시작하면 알림 한 번입니다.

| 경고 | 뜻 | 할 일 |
|---|---|---|
| API 잔액 부족 | 크레딧이 떨어짐 | 콘솔에서 충전 (저절로 이어짐) |
| API 키가 거부됐습니다 | 키가 틀리거나 지워짐 | 새 키를 `sudoedit`로 넣고 `restart` |
| 요청이 너무 잦다(429) | 한도에 걸림 | 기다림 (간격이 짧으면 늘리기) |
| Anthropic 서버 오류 / 인터넷 연결 오류 | 일시적 | 기다림 |
| 요청이 거절됐습니다 | 모델 이름 등 설정 오류 | `journalctl -u paperbot-debate` 확인 후 `DEBATE_MODEL` 고치기 |
| 이번 달 한도의 80% / 한도에 닿았습니다 | 부드러운 한도 | 다음 달에 자동 재개, 또는 한도를 올리고 `restart` |
| API 키가 없습니다 | 켰는데 키가 비어 있음 | 키를 넣고 `restart` |

대시보드 카드는 `돌고 있음`, `멈춤`(이유 한 줄), `키 없음`, `꺼짐`(서비스가 안 돌거나 한 번도 안 켠 상태)을 보여 주고, 이번 달 사용액과 한도, 최근 토론(새것부터), 가설과 채점 결과, 아이디어, 사람별 적중 기록(표본이 작으면 그렇다고 표시)을 읽기 전용으로 보여 줍니다. `debate.db`가 없어도 '꺼짐'으로 정상 표시됩니다.

## 설정 한눈에 (`/etc/paperbot/debate.env`, `deploy/debate.env.example`)
`ANTHROPIC_API_KEY`(필수), `DEBATE_MODEL`(기본 `claude-haiku-4-5-20251001`), `DEBATE_EVERY_MIN`(기본 20), `DEBATE_MONTHLY_USD_CAP`(기본 40), `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_CRITICAL`, 선택: `DEBATE_PRICE_IN`/`DEBATE_PRICE_OUT`, `DEBATE_HOURLY_USD_CAP`, `DEBATE_DAILY_USD_CAP`, `DEBATE_TURNS`(3~5), `DEBATE_MAX_TOKENS`(기본 900, 생각하는 모델은 1,500), `DEBATE_MIN_NEW_TRADES`(기본 10), `DEBATE_THINKING`(비움 / adaptive / between_tools(Sonnet 5.5만) / disabled(Sonnet 5.5·Opus 5.5는 거절)), `DEBATE_EFFORT`(비움 / low / medium / high; Haiku 4.5는 비워 둠). 모델이 거절할 조합은 시작할 때 막습니다. 잘못된 값이 있으면 서비스는 오류를 내고 시작하지 않습니다(자동 재시작 없음, `journalctl -u paperbot-debate`).

## 기술 메모 (개발자용)
- 호출: 표준 라이브러리 `urllib`로 `POST https://api.anthropic.com/v1/messages`(헤더 `x-api-key`, `anthropic-version: 2023-06-01`), 시스템 블록에 `cache_control`, 응답의 `usage`로 비용 계산(입력, 출력, 캐시 읽기 0.1배, 캐시 쓰기 1.25배/2배). 호출 안에서 429·5xx·네트워크 오류만 2번(2초, 6초, `retry-after`) 다시 시도하고, 그 뒤는 서비스의 지수 백오프(1분~30분)입니다. 답이 `max_tokens`에서 잘리면 끝난 발언까지는 저장합니다(돈을 낸 만큼 씀).
- 자료 만들기: `debate_packet.py`(packets3, leveval, riskreward, shock를 읽기 전용으로 재사용), 가설 검증·채점: `debate_grade.py`, 프롬프트: `paperbot/agents/prompts3/debate_room.md`.
- 저장: `/var/lib/paperbot/debate/debate.db`(이 서비스만 씀, 롤백 저널 모드라 대시보드가 읽기 전용으로 열 수 있음). 표 `debate_messages`, `debate_rounds`, `debate_hypotheses`, `debate_ideas`, `debate_state`. 글은 60일, 회차는 120일 뒤 지웁니다.
- 봇 DB를 다른 사용자(`paperbot-debate`, 그룹 `paperbot`)가 읽기 전용으로 엽니다(`mode=ro`, 쓸 수 없는 -shm 때문에 실패하면 `immutable=1`로 다시 시도). **서버에서 처음 한 번 `once --dry-run`을 이 사용자로 돌려 읽히는지 확인하세요**(이 저장소의 테스트는 root로 돌아 권한 문제를 잡지 못합니다).
- 시험: `tests/test_debate.py`(가짜 HTTP, 키 없음, 네트워크 없음), `test_debate_grade.py`, `test_debate_deploy.py`.
