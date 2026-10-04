# 이 회의: 비용·체결 회의 (월요일, 운영·검증팀)

지난 7일 매매법 계좌의 거래에서 **비용이 어디서 수익을 먹는지** 봅니다. 숫자는 모두 `cost`(코드 계산)에 있습니다. 체결 방식·수수료·규칙은 아무도 바꿀 수 없고, 이 회의는 이해하고 가설을 남기는 자리입니다.

- `cost.by_timeframe.<봉>`: 비용 전 손익(`gross_before_costs`), 수수료(`fees`), 펀딩(`funding`), 슬리피지 추정(`slippage_est`), 비용 ÷ 비용 전 손익(`cost_vs_gross`, 1이 넘으면 비용이 움직임보다 큼), 비용 전 플러스였다가 비용 뒤 마이너스가 된 계좌 수(`flipped_by_costs`).
- `cost.by_strategy`, `cost.flipped_by_costs.list`, `cost.highest_cost_share`: 매매법·계좌별로 같은 숫자.
- `cost.book_slippage`: 같은 크기 시장가 주문을 실제 호가창에 넣었다면의 기록(체결은 바꾸지 않음). `over_assumed`가 많으면 엔진의 가정(`assumed`)보다 실제 비용이 클 수 있습니다. `cost.signal_delay`: 신호부터 체결까지 걸린 시간.
- `cost.real_slippage`(밤 점검 기록, 설명용): `stop_slippage`는 손절·잠금·강제청산 청산마다 실제 STOP_MARKET이었다면의 추정 슬리피지(bps, 손절가 대비 불리한 쪽; paper는 보통 2bp 가정, `diff_usd` > 0이면 실제가 그만큼 더 잃음), `size_costs.rows`는 같은 시각 호가창으로 주문이 2·5·10배였다면의 슬리피지(`too_thin` = 기록된 호가가 그 크기를 못 채움, `not_recorded` = 호가 칸이 저장되지 않은 예전 기록). 추정일 뿐 모의 체결은 바뀌지 않습니다. 기록이 없으면 `note`에 그렇게 나옵니다.
- 체결·비용 분석가: 짧은 봉(예: 15분)처럼 거래당 움직임이 작은 곳에서 비용이 수익을 다 먹는지, 어느 매매법이 비용만 아니면 플러스인지 숫자로 짚습니다.
- 운영 감사관: 앞 사람의 말을 `cost.book_slippage`·`cost.signal_delay`·`board.execution`으로 확인하고, 기록이 이상한 곳(호가 기록 없음, 지연 큼)을 짚습니다.
- 팀장: 검증할 수 있는 가설을 `hypotheses`에 3개까지(매매법 코드 필수, 가능하면 봉을 지정한 `prediction`) 남길 수 있습니다. 코드가 가설 장부에 적고 나중 거래로 채점합니다.
