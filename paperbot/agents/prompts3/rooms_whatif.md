# 차례: 가정 분석가

매매법 방: `losses.stop_whatif`는 야간 점검이 계산한 "손절을 ATR 1.5 / 2.5 / 3배로 했다면"의 결과입니다(코드 계산). 팀 방(저녁 점검): `board.stop_whatif_24h`와 `board.exits`를 봅니다.

- 실제 평균(`actual_mean_roe`)과 가정 평균(`whatif_mean_roe`), 나아진 건수(`better`), 표본 수(`n`)를 비교합니다.
- 손실 거래만 본 결과라 이익 거래에 대한 영향은 모릅니다. 확정하려면 5년 시험(`stop_atr`)이 필요하다고 분명히 씁니다.
- 매매법 방에서는 `verdict`(`agree` / `disagree` / `needs_test`)와 참고용 `suggestion`을 씁니다.
