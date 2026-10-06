# 다툼 하나 (편 가르기 켜짐: 순위·비용·조합·코인·손익비·낙폭 회의)

이번 회의에서 두 직원이 서로 반대로 답한 점(`this_round`의 `responds_to.stance`가 `disagree`)이 있고, 그것이 매매법 하나에 대해 시험으로 가릴 수 있는 주장이면 `dispute`에 하나만 적습니다. 없으면 null입니다.
- `strategy`: 매매법 코드(잠긴 36개 중 하나). `side_a`: 주장이 맞다는 직원의 role. `side_b`: 반대한 직원의 role. 둘 다 이번 회의에서 말한 직원이어야 합니다.
- `claim`: 주장 한 줄. `settle`: 가릴 시험. 5년 시험이면 `{"kind": "lab", "test": {"template": "stop_atr | lock_start | skip_tag", "timeframe": "15m | 30m | 1h | 4h", "value": 값}}`, 앞으로 거래로 가리면 `{"kind": "forward", "check": "tag_gap | vs_flip", "tag": "tag_gap일 때 진입 특징", "timeframe": 봉 또는 null}`. 거래 수 N은 코드가 정합니다.
- 코드가 두 직원의 반대 기록과 시험 형식을 확인한 뒤에만 다툼을 엽니다. 5년 시험은 그 매매법 방의 장부로 돌고(그 방 시험 수에 들어감), 채점도 코드가 합니다. 같은 주장을 다시 열면 점수 없이 이전 결과만 보여 줍니다.
