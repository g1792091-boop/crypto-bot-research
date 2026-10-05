# 레버리지 규칙 B 평가 — paper v4의 계좌 범위 (미리 정함)

## English summary

- **Method.** Rule B (quality-based leverage) is evaluated in the v4 run by exactly the method of `docs/levrule-eval.md` (sha256 def12e23…, unchanged), at the day-30 checkpoint of the v4 run.
- **Population (owners' D12).** The core group's 36 strategies on 15m/30m/1h/4h (144 accounts), plus the 12 original coin flips on the same timeframes. DeepSeek, the reel, the 5m coin flips, copies and new-strategy accounts are left out: they are never 'best', so they hold no good-spot vs normal contrast.
- **Fallback.** If rule B is not kept, the pre-registered fixed 20x/20% applies to every group at that switch. That is a trading change, so it is a new version with new accounts.

---

작성: 2026-10-05 (KST), 두 분 결정 D12(2026-10-05), v4 실행이 시작되기 전. 해시는 `docs/levrule-eval-v4.sha256`에 둡니다. 고치지 않고, 바꿀 일이 생기면 새 문서를 씁니다.

`docs/levrule-eval.md`(sha256 `def12e23b43e51ee544e8774a851701b5866fc5494bfa15d12d3a2c8f020b26c`)는 "고치지 않고, 바꿀 일이 생기면 새 문서를 씁니다"라고 정했습니다. 그 문서는 v3 실행(156개 계좌)을 기준으로 쓴 것입니다. 이 문서는 v4 실행(331개 계좌, `docs/paper-v4-rules.md`)에서 **누구를 세는지와 결과를 어디에 적용하는지만** 정합니다. **그 밖의 모든 것은 `docs/levrule-eval.md` 그대로입니다:**
- 질문
- 노출 1단위당 수익 r
- 묶음(`tier`)
- 적격 칸(두 묶음 모두 10건 이상)
- D_s·D_c·DiD
- 주 단위 블록 부트스트랩: 10,000번, 시드 20261004, 블록은 시작 시각부터 7일
- 한쪽 p값
- 판정 조건 (가)·(나)
- 지키는 것, 보는 곳

## 1. 기간
- **시작:** v4 실행의 시작 시각입니다.
- **끝:** v4의 첫 판정(D0 + 30일 00:00 UTC = 09:00 KST, `paperbot/checkpoint.py`의 `checkpoint_ts(시작, 1)`)입니다.
- 이 사이에 **진입하고 그 전에 끝난** 거래만 셉니다.
- v3 실행의 거래는 어떤 계산에도 넣지 않습니다(v3는 30일 판정 없이 보관됨).

## 2. 계좌 범위 (D12)

| 쪽 | 들어가는 계좌 | 수 |
|---|---|---|
| 매매법 쪽(D_s) | `kind = strategy`: 잠긴 36개 × 15분·30분·1시간·4시간 | 144 |
| 동전 쪽(D_c) | `kind = random`이고 봉이 15분·30분·1시간·4시간인 것: `RANDOM_1~3` × 4 | 12 |

넣지 않는 계좌:

| 계좌 | 이유 |
|---|---|
| 딥시크 171개(`kind = ds200`) | 진입 품질 경계가 없어 늘 보통입니다. 좋은 자리 거래가 없으므로 적격 칸이 될 수 없습니다 |
| 릴스 `REEL_H1@5m`(`kind = reel`) | 늘 보통이고, 청산도 하우스 규칙이 아닙니다 |
| **5분 동전 3개** | `kind = random`이지만 봉이 5분입니다. p_best = 0이라 늘 보통이고, 릴스 자체 청산을 씁니다. kind만 보면 들어가므로 **봉으로 뺍니다** |
| 복제·새 매매법 계좌 | v3 문서와 같이 넣지 않습니다 |

- **코드:** `paperbot/agents/leveval.py`가 범위를 정합니다. `trade_rows`는 `kind`가 `strategy`·`random`이고 봉이 `config.V3_TRADE_TFS`(15분·30분·1시간·4시간)인 계좌의 거래만 읽습니다(`POPULATION_TFS`).
- **확인:** 섞인 자료(331개 계좌 + 추가 계좌)에서 낸 결과는 위 156개 계좌만 있는 자료의 결과와 같아야 합니다(시험).

## 3. 판정과 적용 범위
- **판정 시점:** D0 + 30일 체크포인트에서 한 번, `docs/levrule-eval.md` 4절의 조건으로 판정합니다.
- **유지:** 규칙 B를 모든 그룹에서 그대로 씁니다. 딥시크·릴스·5분 동전은 늘 보통이므로 실제로 바뀌는 것은 없습니다. 다음 창(D0 + 30 ~ D0 + 60)의 끝에서 그 창의 거래로 같은 방법을 다시 씁니다.
- **유지하지 않음(계산할 수 없는 경우 포함):** 미리 정한 대로 **모든 신호를 20배·증거금 20% 고정**으로 바꿉니다.
  - 이 대체 규칙은 **모든 그룹**(매매법, 딥시크, 릴스, 동전 15개, 추가 계좌)에 적용합니다. 그룹마다 규칙이 갈리면 그룹끼리, 그리고 동전 봇과 비교할 때 조건이 달라지기 때문입니다.
  - 딥시크·릴스·5분 동전에는 "보통 30배·30% → 20배·20%"가 "20배·20% 고정"으로 바뀌는 것입니다.
  - 이것은 거래 규칙 변경이므로 **버전을 올리고(v5) 새 계좌로 시작**합니다(`docs/paper-v4-rules.md` 13절). 두 분이 확인합니다.
- **결과 전달:** 코드가 낸 그대로 전합니다. 결과를 보고 범위(어느 계좌를 셀지)나 기준(10건, 0.10, 블록 길이)을 옮기자는 말은 하지 않습니다.
