# 주문 흐름 수집기 (서버용)

작성: 2026-09-30 (KST)

## 왜 필요한가
- 가격·거래량 매매법은 약 1,300개 조합에서 통과 0개였습니다. 다음 연구는 **주문 흐름**(누가 레버리지로 한쪽에 몰렸는지)입니다(`research/orderflow/PREREG_ORDERFLOW.md`).
- 바이낸스는 이 통계(미결제약정, 롱숏 비율, 테이커 비율)를 **최근 30일만** 보여 줍니다. 그래서 서버에서 계속 모아 두어야 합니다.
- **청산 기록은 공개된 과거 자료가 없습니다.** 지금부터 모으지 않으면 청산 가설은 영영 검사할 수 없습니다.
- 모은 자료의 쓰임새는 두 가지입니다.
  - 주문 흐름 매매법이 과거 백테스트를 통과했을 때, paper에서 실시간 신호를 내는 입력
  - 새 데이터로 판정할 때 쓰는 기록

## 무엇을 모으나
| 자료 | 주기 | 저장 위치 | 쓰는 프로세스 | 거래소 보관 기간 |
|---|---|---|---|---|
| 미결제약정 (수량, 금액) | 5분 | `flow.db` `oi5m` | 매시간 타이머 | 30일 |
| 일반 계정 롱숏 비율 | 5분 | `flow.db` `ls_global5m` | 매시간 타이머 | 30일 |
| 상위 트레이더 계정 비율 | 5분 | `flow.db` `ls_top_account5m` | 매시간 타이머 | 30일 |
| 상위 트레이더 포지션 비율 | 5분 | `flow.db` `ls_top_position5m` | 매시간 타이머 | 30일 |
| 테이커 매수/매도 비율, 거래량 | 5분 | `flow.db` `taker5m` | 매시간 타이머 | 30일 |
| 프리미엄 지수 5분봉 | 5분 | `flow.db` `premium5m` | 매시간 타이머 | 전체 (처음 실행 때 3년치 받음) |
| **청산 주문** (전 종목) | 실시간 | `liq.db` `liq` | 상시 프로세스 | **없음** (놓치면 끝) |

- 코인: 7개(BTC, ETH, SOL, LTC, BCH, DOGE, XRP). 청산은 전 종목을 기록합니다(시장 전체 청산 규모도 신호가 될 수 있어서).
- 공개 데이터라 **API 키가 필요 없습니다.**
- 데이터베이스마다 쓰는 프로세스는 하나입니다: `flow.db` = 매시간 타이머, `liq.db` = 청산 수집기. 기존 `market.db`, `paper.db`와 섞지 않습니다.
- 한 번 저장한 값은 고치지 않습니다. 거래소가 나중에 다른 값을 주면 `revisions`에 따로 남깁니다.
- 과거 백테스트에 쓰는 공개 자료(data.binance.vision `metrics`)와 열 이름은 이렇게 대응합니다.

| 공개 자료 열 | 서버 기록 |
|---|---|
| sum_open_interest(_value) | `oi5m.sum_oi(_value)` |
| count_long_short_ratio | `ls_global5m.ratio` |
| count_toptrader_long_short_ratio | `ls_top_account5m.ratio` |
| sum_toptrader_long_short_ratio | `ls_top_position5m.ratio` |
| sum_taker_long_short_vol_ratio | `taker5m.buy_sell_ratio` |

서버에서 며칠 모은 뒤, 같은 날짜의 공개 자료와 값이 같은지 한 번 대조해야 합니다(아직 안 함).

## 서버가 꺼졌다 켜지면
- **매시간 타이머:** 켜지면 마지막 저장 시점부터 이어 받습니다(`Persistent=true`). 30일 안에 다시 켜지면 **빠지는 자료가 없습니다.** 30일을 넘기면 받을 수 없는 구간을 `gaps` 표에 남기고 텔레그램 경고를 보냅니다.
- **청산 수집기:** systemd가 자동으로 다시 켭니다(`Restart=always`). 끊기면 1, 2, 4… 최대 60초 간격으로 다시 연결합니다.
  - 10분 동안 아무 메시지가 없으면 연결이 죽은 것으로 보고 다시 연결합니다.
  - 23시간마다 스스로 다시 연결합니다(바이낸스가 24시간에 끊음).
  - 5분 넘게 끊겼다가 다시 연결되면 텔레그램 경고를 보냅니다.
  - 연결·끊김 시각은 `conn_log`에 남아서, 어느 구간이 비었는지 알 수 있습니다.

## 한계 (미리 적음)
- 바이낸스 청산 스트림은 **종목마다 1초에 가장 최근 청산 1건만** 보냅니다. 폭락처럼 청산이 몰리면 실제보다 적게 잡힙니다. 날짜끼리 비교하는 데는 쓸 수 있지만 절대 금액은 실제보다 작습니다.
- 5분 통계의 시각은 거래소가 준 값 그대로 저장합니다. 연구 코드는 보수적으로 "찍힌 시각 + 5분"부터 씁니다.

## 서버 설치
```bash
cd /opt/crypto-bot-research
sudo pip3 install -r requirements.txt          # websocket-client 추가됨
# 1) 매시간 주문 흐름 받기: 처음 한 번 손으로 (30일치 + 프리미엄 3년치, 몇 분)
sudo -u paperbot python3 -m paperbot.flow sync --flow /var/lib/paperbot/flow.db
sudo -u paperbot python3 -m paperbot.flow status --flow /var/lib/paperbot/flow.db
sudo cp deploy/paperbot-flow.service deploy/paperbot-flow.timer /etc/systemd/system/
# 2) 청산 수집기 (상시)
sudo cp deploy/paperbot-liq.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now paperbot-flow.timer paperbot-liq.service
# 3) 확인
sudo -u paperbot python3 -m paperbot.liqstream status --db /var/lib/paperbot/liq.db
systemctl status paperbot-liq.service
```
- `status`는 최근 24시간 저장 개수(5분 자료는 288개가 정상), 빈 구간, 연결 비율(1에 가까워야 정상), 청산이 많았던 종목을 보여 줍니다.
- 텔레그램 설정은 기존 `/etc/paperbot/live.env`를 같이 씁니다.

## 시험
`tests/test_flow.py` (가짜 거래소, 네트워크 없이 통과):
- 첫 실행에서 29일치를 빈틈 없이 저장하는지, 아직 안 끝난 5분은 저장하지 않는지
- 다시 실행하면 새로 늘어난 것만 추가하는지, 값이 바뀌면 원래 값을 두고 `revisions`에 남기는지
- 40일 동안 꺼져 있다 켜지면 `gaps`에 남는지
- 청산 메시지 해석, 잘못된 메시지 무시, 중복 무시, 끊김 후 재연결, 경고, 연결 비율 계산

실제 바이낸스 연결은 이 작업 환경에서 막혀 있어서 **아직 확인하지 못했습니다.** 서버에서 처음 실행할 때 `status`로 확인합니다.
