# 청산 비교 리그 설치 안내 (두 분용)

두 분 말씀(2026-10-12): "규칙봇은 그대로 두고 커스텀값봇들을 익절기준이랑 손절기준을 좀 바꾸고 싶어서".
이 안내대로 하면 **후보 리그(커스텀값 봇)만** 바뀝니다. 규칙봇은 손대지 않습니다.

## 무엇이 바뀌나

후보 49개(지금 돌던 16개 매매법의 38개 + 약한 단서 11개)마다 아래 계좌를 **같은 신호 · 같은 크기(규칙봇과 같은 크기)** 로 나란히 돌립니다.
모든 계좌가 **고른 커스텀값**으로 돌고, 기본수치 계좌는 없습니다(기본수치는 규칙봇이 이미 돌립니다).
**기준(실전 후보)은 첫 계좌 "계단 익절 · 손절 최대 2 ATR"** 이고, 나머지는 모두 같은 신호에서 청산만 다르게 가정한 연구용 모의입니다.

| 계좌 | 무엇이 다른가 |
|---|---|
| **계단 익절 · 손절 최대 2 ATR (실전 후보)** | 두 분 계단: 수수료 뺀 순수익이 +13%에 닿으면 +10%에 손절선을 올림, +20%면 +15%, +25%면 +20%, +30%면 +25% (이후 5%씩). 고정 익절 없음. 손절은 후보의 것, 단 최대 2 ATR |
| 계단 · 동전 던지기 | 위와 같은 청산인데 방향만 같은 신호 시각에 동전으로 정함 (번 것이 시장 방향 덕인지 가르는 대조) |
| 계단 · 후보의 손절 그대로 | 같은 계단, 손절은 후보의 것 그대로(3~4 ATR이 많음). 손절 폭의 효과를 보는 비교 (손절이 이미 2 ATR 이하인 후보는 위와 같은 계좌라 만들지 않음) |
| 계단 · 손절 최대 1 ATR | 같은 계단, 손절을 더 좁게 |
| 계단 5%부터 | +7%에 닿으면 +5% 잠금, +12%면 +10%, +17%면 +15% … (일찍 시작) |
| 계단 20%부터 | +22%에 닿으면 +20% 잠금, +27%면 +25% … (늦게 시작) |
| 지금 청산 | 후보의 지금 익절(3R 등)·손절 그대로 (비교 기준) |
| 고정 익절 +10% | 수수료 뺀 순수익 +10%에 미리 걸어 둔 지정가로 익절, 손절은 최대 2 ATR |
| 큰 수익 반납 보호 | 수익이 +1R(손절 거리만큼)에 닿은 뒤, 봉 마감 때 최고 수익의 절반을 돌려주면 시장가로 청산. 원래 익절도 그대로 |
| 이동평균 이탈 | 고정 익절 없음. 그 후보 봉의 EMA 50을 반대로 넘어 마감하면 다음 분에 시장가로 청산 (먼저 바른 쪽에서 한 번 마감해야 켜짐) |
| 빠른 손절 (관점 무너지면) | 손실이 0.5R 이상이고 그 봉의 스윙 구조(3봉)가 무너지면 다음 분에 시장가로 청산. 원래 익절·손절은 그대로 |
| 구조 무너지면 청산 | 손실 여부와 상관없이 스윙 구조(3봉)가 무너지면 청산. 원래 익절·손절은 그대로 |
| 시간 제한 4시간 | 4시간 안에 안 풀리면 시장가로 청산. 원래 익절·손절은 그대로 ("20시간 보유"를 직접 막음) |
| 추적 손절 1.5 ATR | 최고가에서 1.5 ATR 되돌리면 청산(수익이 나면 손절 범위가 좁아짐). 원래 익절·손절은 그대로 |
| 반대 신호 청산 (매매법 자체) | 고정 익절 없음. 그 매매법이 반대 방향 신호를 내면 청산. 손절은 그대로 |
| 주말 쉬는 계좌 | 지금 청산과 같음. 토 09:00 ~ 월 09:00(한국 시각)에 마감한 봉의 신호로는 새로 들어가지 않음 |

- 계단 규칙은 두 분이 정하신 숫자 그대로이고, 모두 수수료·슬리피지·펀딩을 뺀 순수익 기준입니다.
- 모두 **770계좌** (후보 49개 × 16종류에서, 손절이 이미 같은 후보의 중복 계좌를 뺀 것). 1/4 크기 · 청산만 바꾼 기본값 · 기본값 계좌는 이번에 뺐습니다.
  그래서 미리 정한 점검(11/11 · 12/11 · 1/11)과 "기준 통과" 판정은 이 리그에서 하지 않습니다(대시보드에 "판정 없음").
- 새 11개는 "약한 단서" 매매법입니다(5년 시험에서 우연 보정만 빼고 통과한 숫자가 있는 매매법 중, 이번 주 규칙봇 상위와 겹친 것). 돈이 된다는 증거가 아니라 모의로 보려는 것입니다.
- **새 기록 파일**(`league_exits.db`)에서 설치한 때부터 모든 계좌 $5,000으로 시작합니다. 지금 기록(`league.db`)은 **지우지 않고 그 자리에 그대로** 두고, 사본도 하나 만들어 둡니다.
  지금 열려 있는 포지션은 새 리그로 옮겨지지 않고 예전 기록에 남습니다.

## 설치 (규칙봇 서버에서, 10~15분)

개발자가 "코드 올렸습니다"라고 한 뒤에 합니다. 아래 명령을 한 줄씩 복사해 붙여 넣으세요.

**1. 최신 코드 받기**
```bash
cd /root/crypto-bot-research && git pull
```

**2. 엔진 잠깐 멈추기** (대시보드는 계속 켜져 있어도 됩니다)
```bash
sudo systemctl stop candleague-live candleague-watch.timer
```

**3. 지금 기록 사본 만들기** (원본은 그대로 둡니다)
```bash
D=$(date -u +%Y%m%d)
sudo -u candleague /opt/candleague/venv/bin/python -I -c "import sqlite3,sys; s=sqlite3.connect('/var/lib/candleague/league.db'); d=sqlite3.connect(sys.argv[1]); s.backup(d); d.close(); s.close(); print('사본 완료:', sys.argv[1])" /var/lib/candleague/league_watch_1011_to_$D.db
sudo cp -p /var/lib/candleague/league_start.json /var/lib/candleague/league_watch_1011_to_${D}_start.json
ls -la /var/lib/candleague/
```
`league.db`, `league_start.json`과 새 사본 `league_watch_1011_to_(날짜).db`가 모두 보이면 됩니다.

**4. 규칙 파일 쓰기** (저장소 밖, 서버에만 있는 파일)
```bash
sudo cp /root/crypto-bot-research/candleague/data/rules_owner_exits.json /etc/candleague/rules.json
sudo chown root:candleague /etc/candleague/rules.json && sudo chmod 640 /etc/candleague/rules.json
```

**4-2. 후보 파일 복사** (지금 후보 38개 + 약한 단서 11개 = 49개)
```bash
sudo cp /root/crypto-bot-research/candleague/data/candidates_owner.json /etc/candleague/candidates.json
sudo chown root:candleague /etc/candleague/candidates.json && sudo chmod 640 /etc/candleague/candidates.json
```

**5. 설치 시각을 정하고 설정 파일에 적기** (설치 시각 = 지금을 5분 단위로 내린 UTC 시각)
```bash
T=$(date -u -d "@$(( $(date +%s) / 300 * 300 ))" +%Y-%m-%dT%H:%MZ); echo "설치 시각: $T"
sudo sed -i '/^# 청산 비교 리그/d;/^CANDLEAGUE_RULES=/d;/^CANDLEAGUE_CANDIDATES=/d;/^CANDLEAGUE_DB=/d;/^CANDLEAGUE_START=/d;/^CANDLEAGUE_EXPECT_START=/d' /etc/candleague/candleague.env
printf '%s\n' "# 청산 비교 리그 (설치 $T)" "CANDLEAGUE_RULES=/etc/candleague/rules.json" "CANDLEAGUE_CANDIDATES=/etc/candleague/candidates.json" "CANDLEAGUE_DB=/var/lib/candleague/league_exits.db" "CANDLEAGUE_START=$T" "CANDLEAGUE_EXPECT_START=$T" | sudo tee -a /etc/candleague/candleague.env > /dev/null
sudo grep -E '^CANDLEAGUE_(RULES|CANDIDATES|DB|START|EXPECT_START)=' /etc/candleague/candleague.env
```
화면에 나온 **설치 시각(예: 2026-10-13T03:05Z)을 적어 두세요.** 마지막 줄에 다섯 줄(RULES, CANDIDATES, DB, START, EXPECT_START)이 보이면 됩니다.
엔진은 시작 시각이 이 설치 시각과 다르면 아무것도 쓰지 않고 멈춥니다(시작 지킴이). 그러니 날짜가 엉뚱하게 시작될 일은 없습니다.

**6. 설치 (코드 복사 + 엔진 켜기)**
```bash
sudo bash deploy/candleague/install_candleague.sh
```
화면에서 볼 것:
- `770 accounts (rules file)` 와 `selfcheck ok` (규칙 파일을 읽을 수 없으면 여기서 멈추고 아무것도 바꾸지 않습니다)
- `기록 없음 또는 후보 목록 없음: 복사할 것 없음` (새 기록 파일이라 정상입니다)
- 끝에 `엔진: 켜짐`, `감시: 10분마다`

## 확인

```bash
cd /opt/candleague/app                     # 설치된 코드 폴더에서 확인합니다
systemctl is-active candleague-live candleague-dash candleague-watch.timer      # active 세 줄이면 정상
sudo journalctl -u candleague-live -n 20 --no-pager
sudo -u candleague env CANDLEAGUE_SNAP=/var/lib/candleague/snap /opt/candleague/venv/bin/python -m candleague status
sudo -u candleague /opt/candleague/venv/bin/python -m candleague.rulex accounts --rules /etc/candleague/rules.json | head -10
```
- 기록(journalctl)에 `새 데이터베이스를 만듭니다: 시작 (설치 시각) UTC (CANDLEAGUE_START)` 와 `770 accounts` 가 있으면 됩니다.
  `멈춥니다` 가 보이면 화면을 개발자에게 보내 주세요(시작 지킴이가 막은 것이라 기록은 안전합니다).
- `status` 줄 끝이 `accounts 770` 이면 됩니다(엔진이 첫 기록을 쓰기까지 1~2분).
- 계좌 목록 첫 줄들이 `core-DOGE-15m-1-ld`, `-ldc`, `-ldp`, `-ld1`, `-l5`, `-l20`, `-e`, `-tp10` 순서면 됩니다.
- 대시보드를 **새로고침**: 요약 맨 위 "청산 비교", **계좌 비교**의 칸 이름이 계단 익절(실전 후보) · 계단 동전 · 계단 후보 손절 · 계단 손절 1 ATR · 계단 5%/20%부터 · 지금 청산 · 고정 익절 +10% · 큰 수익 반납 보호 · 이동평균 이탈 · 빠른 손절 · 구조 무너지면 청산 · 시간 제한 · 추적 손절 · 반대 신호 청산 · 주말 쉬는 계좌, 서버 상태의 시작 시각 = 설치 시각.
- 첫 거래는 신호가 나는 대로 보입니다(15분 봉 후보는 빠르면 15분 안). 텔레그램 아침 9시 요약에 "청산 비교" 줄이 생깁니다.
  설치한 날 9시가 이미 지났으면 그날 요약이 한 번 더 올 수 있습니다(새 기록 파일이라).

## 되돌리기 (예전 리그로)

설치 화면에서 멈췄거나(그때는 코드가 바뀌지 않았지만 2번에서 멈춘 엔진이 꺼진 채로 있습니다) 결과가 이상하면, 아래 세 줄로 예전 리그로 돌아갑니다.

```bash
sudo systemctl stop candleague-live
sudo sed -i '/^# 청산 비교 리그/d;/^CANDLEAGUE_RULES=/d;/^CANDLEAGUE_CANDIDATES=/d;/^CANDLEAGUE_DB=/d;/^CANDLEAGUE_START=/d;/^CANDLEAGUE_EXPECT_START=/d' /etc/candleague/candleague.env
sudo systemctl start candleague-live candleague-watch.timer
```
- 예전 리그(`league.db`, 후보 · 1/4 · 청산만 · 기본값 · 동전 190계좌)가 **멈춘 곳부터 지금까지 따라잡고** 이어 갑니다(같은 공개 시세 ·
  같은 규칙이라 멈추지 않았을 때와 같은 결과). 코드는 그대로 둬도 됩니다(규칙 파일 설정을 빼면 예전 계좌 그대로).
- 청산 비교 기록(`league_exits.db`)은 지우지 않고 남습니다. 다시 켜려면 4~6번을 하되, 5번의 설치 시각 `T` 는 **처음 적어 둔 값 그대로** 넣습니다
  (`T=2026-10-13T03:05Z` 처럼 직접 적고, `date` 로 새로 만들지 않음). 그러면 그 기록이 멈춘 곳부터 이어 갑니다.

## 서버 부담 (CPU · 메모리)

후보 리그 엔진은 CPU 한 개의 30%, 메모리 1.3 GB까지만 쓰도록 묶여 있습니다(규칙봇 보호). 계좌 수는 190개 → 770개로 4배 늘어납니다(아래 숫자의 약 4배, 평균 4~6초로 예상).
이 PC(Xeon 2.8 GHz)에서 가짜 시세(6코인, 실제 후보 38개 · 실제 매매법 코드)로 재 본 값:

| | 지금 리그 (190계좌) | 청산 비교 리그 (189계좌) |
|---|---|---|
| 5분마다 한 번 계산 (기록 쓰기 포함) | 평균 1.2초 | 평균 1.0초 |
| 하루치 따라잡기 | 약 5.4초 | 약 3.9초 |
| 메모리 최대 | 약 170 MB | 약 185 MB |

- 5분(300초)마다 1초 남짓(가장 길 때 3초)이라 평균으로는 CPU 한 개의 1%도 안 됩니다. 30% 제한 아래에서는 같은 계산이 3~10초쯤 걸릴 뿐입니다.
  서버의 실제 값은 대시보드 **서버 상태**의 '한 번 처리 시간'과 '엔진 메모리 (최대)'에 나옵니다.
- 엔진을 다시 켤 때(업데이트 등)는 열린 이동평균 · 반납 보호 포지션마다 1분 봉을 다시 받아 상태를 맞춰 보느라 처음 한 번 몇십 초 더 걸릴 수 있습니다.
- 메모리는 한도 1.3 GB의 2할도 안 됩니다. 실제 서버 값은 대시보드 **서버 상태**의 메모리 칸에서 볼 수 있습니다.
- 시세를 받아 오는 시간(바이낸스 응답 대기)은 CPU를 쓰지 않아 위 숫자에 없습니다. 지금 리그와 같습니다.

## 읽는 법 (짧게)

- **5계좌 비교** 화면에서 후보마다 한 줄: 다섯 계좌의 잔고 수익률($5,000 대비) · 거래 수 · 승률 · 보유 시간 중앙값. 그 후보에서 잔고가
  가장 많은 계좌에 ★. 위쪽에 "이동평균 > 지금 12 / 30"처럼 지금 청산보다 잔고가 많은 후보 수와, 묶음마다 보유 시간 중앙값 · 8시간 넘게
  들고 있던 비율이 나옵니다(이번에 문제였던 "20시간 넘게 보유"를 바로 봄).
- 거래가 적은 동안(후보마다 30번 전)은 운이 큽니다. 며칠 성적으로 청산을 바꾸지 말고, 몇 주 쌓인 뒤 두 분이 정하시면 됩니다.
