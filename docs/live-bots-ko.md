# 자동매매 봇 최종 정리 (11/03부터)

두 분(11/03): "자동매매봇 거래소는 총 2개 거래소를 쓸꺼야", "바이비트말고 woox pro1 거래소랑 친구봇 woox pro2 이렇게 쓸꺼야",
"PRO1 OBV · PRO2 3합", "woo x pro 1 거래소는 이더 리플 bch 삭제하고 비트 추가해주고", "woox2에 솔라나 이더만 삭제하고 비트 추가해줘",
"각 봇들 매매법도 최종 정리해줘", "Woo x pro2 거래소 아이디를 실수로 탈퇴해서 woo x pro2 친구봇 거래소를 투빗으로 해줘",
그리고 "레인지봇 도지 bch 이더 리플 삭제해주고 친구봇 bch 삭제해줘".

자동매매는 **WOO X Pro 1**(레인지 봇)과 **투비트**(친구 15분 봇) 두 곳만 합니다. 바이비트 봇은 꺼 둡니다(`docs/mixbybit-ko.md` 13장). 게이트 봇은 친구가 직접 진입한
포지션에 손절과 계단만 거는 봇이라 자동매매가 아닙니다(`docs/gate-bot-ko.md`). 게이트 봇의 계단도 11/03부터 두 봇과 같은 기준
(**거래소 ROE** +10%→+8%, 그 뒤 2%마다; `docs/gate-bot-ko.md` 8장)입니다. **백테스트는 하지 않았습니다.**

## 한눈에

| | 레인지 봇 | 친구 15분 봇 |
|---|---|---|
| 계정 | **WOO X Pro 1** (첫 계정) | **투비트** (11/03부터, WOO X Pro 2 계정이 없어져서) |
| 키 파일 | `/etc/paperbot/executor.env` (예전과 같음) | `/etc/paperbot/executor-toobit.env` (예전 투비트 실행기의 파일) |
| 코인 (같은 봉이면 이 순서) | **BTC → SOL → ZEC** (11/03 저녁 DOGE 뺌) | **BTC → XRP → ZEC → DOGE** (11/03 저녁 BCH 뺌) |
| 레버리지 | 40배 (ZEC만 20배) | 40배 (ZEC만 20배) |
| 추세 | 30분봉 추세 MACD 히스토그램 | 30분봉 추세 MACD 히스토그램 |
| 진입 신호 | 15분봉 **OBV 히스토그램 전환** | 15분봉 **3합 히스토그램 0선 돌파** |
| 설정 파일 | `/etc/paperbot/mixrange.json` (`deploy/mixrange.live.json`) | `/etc/paperbot/mixchop.json` (`deploy/mixchop.live.json`) |
| 서비스 | `paperbot-mixrange` (모의 `paperbot-mixrange-paper`) | `paperbot-mixchop` (모의 `paperbot-mixchop-paper`) |
| 프로그램 | `paperbot/mixchop.py` 규칙 `o4h` | `paperbot/mixchop.py` 규칙 `h3x` |

## 1. 추세 (두 봇 같음): 30분봉 '추세 MACD' 히스토그램

- 15분봉이 끝날 때마다, 그때까지 **끝난 마지막 30분봉**의 추세 MACD 히스토그램을 봅니다. 15분봉의 추세는 보지 않습니다.
- 히스토그램이 **0선 위면 상승**(롱만), **0선 아래면 하락**(숏만). 정확히 0이면 진입하지 않습니다.
- **노란 막대**(추세 바 종합이 횡보인 봉)도 색은 보지 않고 0선 위 · 아래로만 봅니다. 노란 막대여도 진입할 수 있습니다.
- 계산(보내 주신 `추세 MACD` 파인 스크립트 기본값): 추세 바 6줄(3개 점수 · 6종 평균 · 하늘·보라 선 · EMA RSI · 슈퍼트렌드 평균 · 4종
  평균)을 각각 −100 ~ +100 값으로 바꿔 평균 → EMA 3 = MACD 선, 그 EMA 9 = 시그널선, **히스토그램 = MACD 선 − 시그널선**.

## 2. 레인지 봇 (WOO X Pro 1): OBV 히스토그램 전환

- **롱**: 30분봉 추세 상승 + 15분봉 OBV 히스토그램이 **0선 아래에서 양봉으로 바뀜** (전 봉은 양봉이 아니었고 이번 봉은 양봉, 그 값이 0 아래).
- **숏**: 30분봉 추세 하락 + 15분봉 OBV 히스토그램이 **0선 위에서 음봉으로 바뀜** (전 봉은 음봉이 아니었고 이번 봉은 음봉, 그 값이 0 위).
- 진입 안 함: 0선 위에서 양봉 전환 · 0선 아래에서 음봉 전환, 전환 없음, 전환 방향이 추세와 반대.
- **OBV 선은 보지 않습니다.** 히스토그램만 봅니다.
- OBV 히스토그램(보내 주신 `OBV4 MACD` 기본값): OBV · 클링거 통합선 − 그 EMA 52, AO, AC, MACD 12/26을 각각 정규화해 평균 × 100
  → EMA 3 = MACD 선, 그 EMA 9 = 시그널선, 히스토그램(기본 'AC 오실레이터') = (MACD 선 − 시그널선) − 그 SMA 5.
  전 봉보다 커지면 양봉(초록), 작아지면 음봉(빨강).

## 3. 친구 15분 봇 (투비트): 3합 히스토그램 0선 돌파

- **롱**: 30분봉 추세 상승 + 15분봉 3합 히스토그램이 **0선 위로 돌파** (전 봉 0 이하 → 이번 봉 0 위).
- **숏**: 30분봉 추세 하락 + 15분봉 3합 히스토그램이 **0선 아래로 돌파** (전 봉 0 이상 → 이번 봉 0 아래).
- 진입 안 함: 돌파 없음, 돌파 방향이 추세와 반대.
- 3합 히스토그램(보내 주신 `3합 히스토그램` 기본값): ① WOOX pro2('ALL + OBV6 MACD')의 MACD 선, ② 레인지봇 = 2 × (EMA RSI − 50),
  ③ 15종 MACD 선의 평균, 그 EMA 9 = 시그널선, 히스토그램 = 평균 − 시그널선.

## 4. 두 봇 공통 규칙

| 항목 | 내용 |
|---|---|
| 신호 봉 | 바이낸스 무기한 15분봉, **끝난 봉만** (봉 마감 직후 판단) |
| 주문 | 시장가 (지정가 안 씀) |
| 포지션 | 봇마다 **한 번에 1개** (같은 봉에 신호가 여러 코인이면 코인 순서대로 첫 번째만) · 불타기 · 물타기 없음 |
| 증거금 | 진입마다 잔고의 **40%** |
| 손절 | 진입 봉의 15분봉 **ATR(14) × 3**, 거래소에 걸어 둠 |
| 청산가 안전 | 손절 거리가 40배는 가격의 2.0%, 20배(ZEC)는 4.5% 안쪽일 때만 진입 (청산가보다 손절이 먼저) |
| 계단 익절 | **거래소에 찍히는 ROE**(수수료 빼기 전, 앱의 미실현 손익 %)가 **+10%**가 되면 손절을 **+8%**로 올리고, 그 뒤 **2%마다** 한 칸씩 (+12%→+10%, +14%→+12%, +16%→+14% …) · 1분봉으로 60초마다 확인 · 11/03 "익절을 거래소에 찍히는 10프로 부터 계단식 익절 2프로 뛰기로" |
| 청산 | 손절 또는 계단 잠금에 닿을 때만 (반대 신호나 시간으로는 닫지 않음) |
| 수수료 | 계단은 수수료 빼기 전 ROE라서, 실제로 남는 돈은 왕복 수수료만큼 적어요. 40배에서 레인지 봇(WOO X Pro, 시장가 0.042%)은 ROE 약 3.4%, 친구 15분 봇(투비트, 시장가 0.06%)은 ROE 약 4.8%. 예: +8% 잠금에서 닫히면 수수료 뒤 레인지 봇 약 +4.6%, 친구 15분 봇 약 +3.2% |
| 진입 금지 시간 | 한국 시간 주말(토 · 일), 나스닥 개장 앞뒤 30분, 미국 경제 발표(CPI · FOMC · 고용 · PCE) 앞뒤 30분 |
| 잔고 하한 | 없음 |
| 모의 쌍둥이 | 같은 신호를 모의 계좌(레인지 봇 $100 · 친구 15분 봇 $50에서 시작)로 따라 해서 실거래와 비교 (진짜 돈 아님) |

## 5. 알림 · 화면

- 텔레그램: 시작(`… 15분봉 마감마다 판단 (추세는 30분봉 추세 MACD 히스토그램)`), 진입(근거 줄), 계단, 청산, 아침 점검
  (레인지 봇 09:09 · 친구 15분 봇 09:05), 손실 카드(5분마다).
  - 근거 줄 예(레인지 봇): `근거: OBV 히스토그램 0선 아래 양봉 전환(-2.00) · 추세 MACD 30분 히스토그램 0선 위 상승(+1.00)`
  - 근거 줄 예(친구 15분 봇): `근거: 3합 히스토그램 0선 위로 돌파(히스토그램 2.5) · 추세 MACD 30분 히스토그램 0선 위 상승(+3.21)`
- 사이트 메뉴: 지금(관제실 · 회의실 · 친구 추세판) · 친구 15분 봇 · 레인지 봇 · 게이트 봇. 관제실 코인은 두 봇 코인을 합친
  BTC · SOL · XRP · ZEC · DOGE입니다.

## 6. 서버 순서

`docs/mixbybit-ko.md` 13-1(코드 받기 · 바이비트 봇 끄기) → `docs/mixchop-ko.md` 19-1(친구 15분 봇을 투비트로) → `docs/range-bot-ko.md` 맨 앞의
'바꾸는 순서'(레인지 봇). 봇마다 포지션이 없을 때 하는 것을 권합니다. 다시 켜도 들고 있던 포지션은 이어받아 손절과 계단을 계속 봅니다.

## 7. 11/03 저녁: 코인 줄이기

두 분: "레인지봇 도지 bch 이더 리플 삭제해주고 친구봇 bch 삭제해줘".

| 봇 | 전 | 지금 |
|---|---|---|
| 레인지 봇 (WOO X Pro 1) | BTC · SOL · ZEC · DOGE | **BTC · SOL · ZEC** (ETH · XRP · BCH는 원래 없었고, DOGE를 뺌) |
| 친구 15분 봇 (투비트) | BTC · XRP · BCH · ZEC · DOGE | **BTC · XRP · ZEC · DOGE** |

- 매매법 · 레버리지(ZEC 20배, 나머지 40배) · 손절 · 계단은 그대로입니다.
- 뺀 코인에 포지션을 들고 있을 때 다시 켜도, 봇은 그 포지션을 끝까지 지킵니다(손절 · 계단 · 청산 알림). 그 코인에 새로 들어가지만 않습니다.
- 모의 쌍둥이도 같은 코인으로 바뀝니다.

### 서버 순서 (두 분이 직접, 한 단계씩)

1. 코드 받기
   ```
   cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh
   ```
2. 서버 설정과 비교 (`coins`에서 뺀 코인만 다르면 3번으로)
   ```
   sudo diff /etc/paperbot/mixrange.json deploy/mixrange.live.json
   sudo diff /etc/paperbot/mixchop.json deploy/mixchop.live.json
   ```
3. 옛 설정 보관 후 새 설정 넣기 (실거래 · 모의 둘 다)
   ```
   sudo cp -p /etc/paperbot/mixrange.json /etc/paperbot/mixrange.json.before-coins
   sudo cp -p /etc/paperbot/mixrange-paper.json /etc/paperbot/mixrange-paper.json.before-coins
   sudo cp -p /etc/paperbot/mixchop.json /etc/paperbot/mixchop.json.before-coins
   sudo cp -p /etc/paperbot/mixchop-paper.json /etc/paperbot/mixchop-paper.json.before-coins
   sudo install -o root -g paperbot -m 640 deploy/mixrange.live.json /etc/paperbot/mixrange.json
   sudo install -o root -g paperbot -m 640 deploy/mixrange.paper.json /etc/paperbot/mixrange-paper.json
   sudo install -o root -g paperbot -m 640 deploy/mixchop.live.json /etc/paperbot/mixchop.json
   sudo install -o root -g paperbot -m 640 deploy/mixchop.paper.json /etc/paperbot/mixchop-paper.json
   ```
4. 점검 (읽기만): 레인지 봇은 BTC · SOL · ZEC 세 줄, 친구 15분 봇은 BTC · XRP · ZEC · DOGE 네 줄이 ✔로 나와야 합니다.
   ```
   sudo deploy/paperbot-exec.sh mixchop check --config /etc/paperbot/mixrange.json
   sudo deploy/paperbot-exec.sh --keys toobit mixchop check --config /etc/paperbot/mixchop.json
   ```
5. 다시 켜기
   ```
   sudo systemctl restart paperbot-mixrange paperbot-mixrange-paper paperbot-mixchop paperbot-mixchop-paper
   sudo journalctl -u paperbot-mixrange -n 4 --no-pager
   sudo journalctl -u paperbot-mixchop -n 4 --no-pager
   ```
   - 시작 알림의 줄이 `코인 BTC · SOL · ZEC`(레인지 봇), `코인 BTC · XRP · ZEC · DOGE`(친구 15분 봇)여야 합니다.

되돌리기: 각 `….before-coins` 파일을 원래 이름으로 `sudo cp -p` 한 뒤 5번.
