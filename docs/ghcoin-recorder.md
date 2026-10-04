# GH Coin 타점 기록기

친구분이 만든 GH Coin의 **"실시간 종합 지표 타점"**을 서버에서 따로 돌려, 156개 paper 계좌(2026-10-04 재시작 전에는 195개)와 **같은 기간에 나란히** 비교하는 기록기입니다.

## 무엇을 하나
- GH Coin 코드를 **고치지 않고 그대로** 씁니다. `deploy/ghcoin.commit`에 적힌 커밋(브랜치 `claude/eloquent-johnson-nnt7gh`)에서 네 파일만 `/opt/ghcoin`으로 복사합니다(`deploy/install.sh`).
  - `gh-coin/combo.js`: 지표 136개 → 5분·15분·1시간·4시간 점수 → 타점(진입·손절·익절)
  - `gh-coin/lib/patterns.js`: 쌍바닥·헤드앤숄더·깃발·삼각수렴·추세선 등 패턴
  - `gh-coin/lib/ta_rating.js`: 트레이딩뷰식 기술 요약
  - `nuri-ai/terminal/ind.js`: 지표 계산
- 5분봉이 닫힐 때마다(8초 뒤) 6개 코인을 계산합니다. **닫힌 봉만** 씁니다. GH Coin 화면은 아직 안 닫힌 봉도 쓰는데, 공정한 비교를 위해 여기서는 뺐습니다.
- 타점 규칙은 GH Coin 기록장(`coin-office.js`의 comboScan)과 같습니다.
  - 상태가 롱/숏 타점으로 **바뀐 순간**에만 기록, 같은 방향 타점이 열려 있으면 기록 안 함
  - 채점: 같은 봉에 둘 다 닿으면 손절 먼저, 익절1 = +1.5R, 24시간 지나면 그때 종가로 마감, 반대 타점이 나오면 그 가격에 마감
- **비용:** 수수료 0.05% + 미끄러짐 0.02%를 양쪽에 매깁니다. R로 바꾸면 `2 × 0.07% × 진입가 ÷ 손절 거리`입니다.
- **동전 던지기 비교:** 타점마다 반대 방향 "거울 타점"을 같이 채점합니다. 같은 시각에 방향만 무작위로 고르면 둘 중 하나가 됩니다. 그래서 무작위 선택 2만 번과 비교해 p값을 냅니다.

## 무엇을 하지 않나
- 주문하지 않습니다. 키도 없습니다(공개 시세만). 텔레그램도 보내지 않습니다.
- paper 계좌는 이 기록을 읽지 않습니다. 매매 코드가 아니라서 30일 기간(Q5)과 상관없습니다.

### 가져오지 않기로 한 것 (2026-10-02 두 분과 정리)
- **자동 최적화(hyperopt)**: 같은 과거 자료에서 값을 계속 골라 맞추면 과거에만 맞는 값이 나옵니다(과최적화). 우리 쪽은 미리 정한 규칙을 세 기간으로 시험하는 방식만 씁니다.
- **그리드·분할매수(DCA) 봇**: 손실 난 포지션에 계속 더 사는 구조라 20~50배 선물에서는 한 번의 큰 움직임에 계좌가 끝납니다.
- **앱 전용 기능**(AI 채팅, 감성 분석, 바깥 AI 연결, 지갑 화면, 실시간 안내, 앱 화면·실행 파일): 매매 판단과 상관없는 화면 기능이거나, 인터넷·바깥 AI를 쓰는 것이라 에이전트 안전 원칙(인터넷 없음)과 맞지 않습니다.
- 친구 봇의 **매매 템플릿 8개**는 버리지 않고, 새 매매법 연구실의 참고 아이디어로 넣었습니다(`docs/agent-rooms.md`).
- 기록기는 1시간·4시간봉마다 GH Coin의 패턴 판단(쌍바닥, 삼각수렴, 추세선 등)과 보조지표 종합 평가를 `patterns.jsonl`에 쌓습니다. 나중에 패턴 연구를 할 때 실제 기록으로 씁니다.

## 보는 법
- 대시보드 **순위표** 탭 아래 "GH Coin 타점 비교" 카드
- 서버에서: `cd /opt/crypto-bot-research && /opt/paperbot/venv/bin/python -m paperbot.ghcoin report`
- 파일: `/var/lib/paperbot/ghcoin/` (`calls.jsonl` 타점 기록, `board.json` 지금 판단, `state.json` 재시작용)

## 백업과 되살리기
- 매일 08:40 DB 백업(`deploy/paperbot-backup.sh`)이 `calls.jsonl`·`patterns.jsonl`·`state.json`을 한 파일 `ghcoin.db`(SQLite, 표 `files`: 이름·내용)로 묶어 다른 DB와 함께 둡니다. 그래서 09:15 서버 밖 백업(텔레그램)에도 같이 갑니다. `board.json`은 5분마다 새로 만들어지므로 넣지 않습니다.
- 되살릴 때(`docs/offsite-backup.md` 9-5): 풀린 `ghcoin.db`는 `/var/lib/paperbot`에 넣지 않고, 아래 네 줄로 파일을 꺼냅니다. 세 번째 줄의 `/root/restore-out/날짜/ghcoin.db`는 붙여 넣기 전에 9-4 "다음 순서"의 `ghcoin.db` 줄(`sudo install … /root/restore-out/20261007/ghcoin.db /var/lib/paperbot/ghcoin.db`)에 나온 **앞쪽 경로**로 바꿉니다. 하루 전 날짜로 다시 풀었거나 `--out`을 다른 이름으로 했으면 폴더가 둘 이상이라, 꼭 그 줄의 경로를 씁니다(바꾸지 않으면 "unable to open database"가 나오고 아무것도 꺼내지 않습니다).
  ```bash
  sudo systemctl stop paperbot-ghcoin
  sudo install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/ghcoin
  sudo sqlite3 /root/restore-out/날짜/ghcoin.db "SELECT writefile('/var/lib/paperbot/ghcoin/' || name, data) FROM files"
  sudo chown -R paperbot:paperbot /var/lib/paperbot/ghcoin
  ```
  숫자(파일 크기)가 줄마다 나오면 된 것입니다. 기록기는 서버를 켤 때(`docs/server-setup-v3.md` 11번) 같이 켜집니다. 백업 뒤 꺼져 있던 동안의 타점은 기록되지 않습니다.

## GH Coin 코드를 새 버전으로 바꿀 때
`deploy/ghcoin.commit`의 커밋을 바꾸고 설치를 다시 돌립니다. 바꾼 날부터는 다른 규칙이므로 `report --since 날짜`로 나눠 봅니다.
