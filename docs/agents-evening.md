# 에이전트 저녁 점검 파이프라인 (v1)

매일 **22:00 (한국 시간)** 에 서버에서 자동으로 돌아갑니다. 에이전트 6명이 그날의 paper 거래를 점검하고, 결과를 텔레그램 "오늘의 점검"으로 보냅니다. 에이전트는 **두 분의 Claude 구독**으로 돌아가며, Claude Code를 서버에 설치해 자동 실행합니다. API 키 요금은 따로 나가지 않습니다.

## 흐름
```
코드: 장부(paper.db)에서 데이터 패킷 생성 (숫자는 모두 코드가 계산)
 → 운영 감사관 → 성과 분석가 → 손익 복기 분석가 → 가정 분석가   (Sonnet)
 → 리스크 책임자                                                (Opus)
 → 팀장                                                         (Sonnet)
 → 코드: 텔레그램 보고 조립·발송, 모든 답을 장부(agent_reports 표)에 저장
```

| 에이전트 | 받는 데이터 | 하는 일 |
|---|---|---|
| 운영 감사관 | 1분봉 누락, 알림, 신호 처리 결과, 가정 실험실 재현 검사, 잔고 기록 | 기계가 정상인지 |
| 성과 분석가 | 오늘·누적 표준 지표, 잔고·낙폭, 요일·시간대 표 | 성과 정리, 두 장부 비교 |
| 손익 복기 분석가 | 오늘 거래별 원인 태그, 누적 원인 분포, 진입 태그 표 | 정상 손실과 고칠 문제 구분 |
| 가정 분석가 | 가정 실험실 19개 규칙 결과 | 청산 규칙이 달랐다면 |
| 리스크 책임자 | 잔고·낙폭·거래 + 위 4명의 검사 통과 결과 | 위험 수준(정상/주의/위험), 유지·축소·중지 권고 |
| 팀장 | 위 전체 | 3줄 요약, 사람이 할 일, 용어 풀이 |

## 안전장치 (코드가 강제)
- **에이전트는 도구가 없습니다** (`--tools ""`). 파일을 읽거나, 명령을 실행하거나, 인터넷에 접속할 수 없습니다. 받은 데이터 패킷만 봅니다.
- **주문 불가, 한도 변경 불가.** 리스크 책임자는 유지·축소·중지만 권고할 수 있고, "확대"를 쓰면 코드가 버립니다. 권고는 사람이 적용 여부를 결정합니다.
- **근거 검사기**: 모든 주장에는 패킷 안의 경로(예: `books.owner.today.win_rate`)를 근거로 붙여야 합니다. 경로가 없거나 틀리면 그 주장은 버려지고, 다음 에이전트에게 전달되지 않으며, 버린 개수가 보고에 표시됩니다.
- **보고의 숫자는 코드가 씁니다.** 텔레그램의 "[숫자: 코드 계산]" 부분은 에이전트가 아니라 코드가 장부에서 계산합니다.
- 에이전트 프로그램에는 **최소한의 환경 변수만** 넘깁니다. 바이낸스 키, 텔레그램 토큰, `ANTHROPIC_API_KEY`는 넘기지 않습니다.
- 한 명이 실패해도 나머지는 돌고, 실패한 역할은 보고에 적힙니다. 사용량 한도에 걸리면 남은 호출을 멈추고 그 사실을 보고합니다.

## 구독 방식: 확인된 사실 (공식 문서 기준)
- 서버처럼 브라우저가 없는 곳에서는 `claude setup-token`으로 **1년짜리 로그인 토큰**을 만들어 `CLAUDE_CODE_OAUTH_TOKEN`에 넣습니다. Pro·Max 요금제에서 쓸 수 있습니다. ([인증 문서](https://code.claude.com/docs/en/authentication))
- 환경에 `ANTHROPIC_API_KEY`가 있으면 자동 실행 모드에서는 **항상 API 키가 우선**되어 API 요금이 따로 나갑니다. 그래서 서버 설정 파일에 넣지 않고, 코드도 넘기지 않습니다.
- `--bare` 옵션은 구독 로그인을 읽지 않고 API 키만 받습니다. ([자동 실행 문서](https://code.claude.com/docs/en/headless)) 그래서 쓰지 않고, 대신 `--safe-mode`(설정·플러그인 무시, 로그인은 정상)를 씁니다.
- 자동 실행 호출도 **같은 구독 사용량 한도**(5시간 단위, 주간 단위)를 씁니다. claude.ai 채팅, 이 세션, 백테스트 세션과 한도를 **함께** 씁니다.
- 공식 문서는 스크립트·CI 용도로 이 토큰 방식을 안내합니다. 다만 개인 자동화 사용에 대한 별도 정책 문구는 문서에서 찾지 못했습니다.

## 실제로 돌려 본 결과 (가짜 가격 데이터, 이 작업 환경에서)
- 6명 모두 성공, 약 **3분**, 한 번에 입력 약 8.3만 토큰 + 출력 약 2.2만 토큰 (리스크 책임자가 가장 큼). 실제 운영에서는 거래가 많은 날 손익 복기 분석가의 입력이 늘어납니다.
- 에이전트들이 찾아낸 것: 수수료가 수수료 전 이익보다 커서 손실로 끝난 점, 5개 종목 1분봉이 비어 있는 점(시험 데이터가 BTC만 있었음), 두 장부의 낙폭 차이.
- 첫 실행에서 드러난 문제와 수정:
  - 에이전트가 목록 번호를 잘못 세서 근거가 틀림 → 가정 실험실·시간대 표를 **이름으로 찾는 구조**로 변경
  - 규칙을 몰라서 정상 동작(연속 5패 후 24시간 정지, 이후 다시 0부터 셈)을 이상으로 보고, "15%가 증거금 기준이냐"고 질문 → 패킷에 **두 장부 규칙 전체**를 넣고, "규칙대로 동작한 것을 오류로 보고하지 말 것"을 공통 규칙에 추가
  - `TRAIL_1.5ATR`처럼 이름에 점이 든 경로를 근거 검사기가 잘못 끊음 → 수정
- 두 번째 실행에서는 규칙 오해가 사라졌고, 버려진 주장은 에이전트의 실제 경로 실수만 남았습니다.

## 서버 설치 (Vultr)
```bash
# 1) 전용 사용자와 폴더
sudo useradd -r -m -d /var/lib/paperbot paperbot
sudo mkdir -p /etc/paperbot && sudo chown paperbot /etc/paperbot && sudo chmod 700 /etc/paperbot
sudo git clone <저장소 주소> /opt/crypto-bot-research

# 2) Claude Code 설치 (paperbot 사용자로). 설치 방법은 공식 안내를 따릅니다:
#    https://code.claude.com/docs/en/setup
sudo -iu paperbot
curl -fsSL https://claude.ai/install.sh | bash

# 3) 구독 로그인 토큰 만들기 (한 번). 화면에 나오는 주소를 내 PC 브라우저에서 열어 로그인
claude setup-token
#    나온 토큰을 /etc/paperbot/agents.env 의 CLAUDE_CODE_OAUTH_TOKEN= 뒤에 붙여 넣기
#    (채팅창에 붙여 넣지 마세요). deploy/agents.env.example 참고
chmod 600 /etc/paperbot/agents.env
exit

# 4) 배관 점검 (Claude 호출 없음)
cd /opt/crypto-bot-research
sudo -u paperbot python3 -m paperbot.agents evening --ledger /var/lib/paperbot/paper.db --dry-run
# 5) 실제 한 번 실행, 텔레그램 대신 화면 출력
sudo -u paperbot bash -c 'set -a; . /etc/paperbot/agents.env; set +a; python3 -m paperbot.agents evening --ledger /var/lib/paperbot/paper.db --no-send'

# 6) 매일 22:00 자동 실행 켜기
sudo cp deploy/paperbot-evening.service deploy/paperbot-evening.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now paperbot-evening.timer
systemctl list-timers paperbot-evening.timer   # 다음 실행 시각 확인
```
- 데이터 패킷만 보고 싶으면: `python3 -m paperbot.agents evening --ledger paper.db --print-packet`
- 에이전트 답은 모두 `paper.db`의 `agent_reports` 표에 남습니다. 나중에 학습 관리 에이전트가 이 기록을 사례 기억으로 씁니다.

## 아직 없는 것
1. **재시작 복구**: paper 엔진이 다시 켜지면 잔고가 처음(1000)부터 시작합니다. 그래서 `paperbot-live.service`는 자동 재시작을 꺼 두었습니다. 다음 작업 후보입니다.
2. **아침 08:00 파이프라인**: 파생상품·매크로·뉴스 데이터 수집기와 계획 관문 코드가 먼저 필요합니다.
3. **학습 관리 에이전트, 전략 검증관, 자기진화팀**: 백테스트 결과와 연결된 매매법이 필요합니다.
4. **킬스위치 명령** (`/status`, `/halt`, `/flatten`).
