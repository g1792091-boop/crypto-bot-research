# 5년 익절 방식 비교: 계단 잠금 vs 고정 익절 (사전 등록)

작성: 2026-10-04 (KST). 스크립트(`research/exitstyle/exitstyle.py`)를 쓰고 돌리기 **전에** 고정합니다. 이 파일의 해시는 `PREREG_EXITSTYLE.sha256`에 있습니다. 바꾸려면 새 문서를 만들고 바꾼 이유를 적습니다.

연구일 뿐입니다. paper v3 실험의 규칙, 계좌, 주문은 이 연구로 바뀌지 않습니다. 결과는 "권고"이며, 규칙을 바꾸려면 두 분 결정과 규칙 버전 올림이 필요합니다. 판단은 이틀치 실거래 자료가 아니라 5년 자료로 합니다.

## 1. 질문 (2026-10-04 두 분)
지금 익절(계단 잠금: 비용 뺀 ROE 최고가 +12%면 +10% 잠금, +17%면 +15%, +22%면 +20%, 그 뒤 5%씩, 잠금은 올라가기만 함) 대신 **고정 익절(TP)**을 썼다면 더 나았는가? 나머지는 모두 같음: 처음 손절 2 × ATR14(신호 봉), 레버리지 단계 50/40/30/20배(증거금 40/40/30/20%), 크기 조건, 비용, 파산 $10 미만, 계좌당 한 포지션.

## 2. 비교하는 방식 (arm)
"R" = 처음 손절 거리 = 2 × ATR14(신호 봉). 진입 기준가(다음 봉 시가, 슬리피지 전)에서 잽니다.

| 이름 | 손절 | 잠금(계단) | 고정 익절 |
|---|---|---|---|
| `ladder` (지금, 기준) | 2 ATR | 있음 | 없음 |
| `tp1R` | 2 ATR, 끝까지 그대로 | 없음 | 기준가 + 1R |
| `tp1.5R` | 〃 | 없음 | + 1.5R |
| `tp2R` | 〃 | 없음 | + 2R |
| `tp3R` | 〃 | 없음 | + 3R |
| `ladder_tp2R` | 2 ATR | 있음 | + 2R (잠금 + 2R 상한) |

- 크기(레버리지·증거금)는 모든 방식에서 같습니다(지금 규칙의 크기 계산, 2 ATR 손절 기준). 그래서 **같은 신호, 같은 진입, 같은 크기**이고 나가는 방식만 다릅니다.
- `ladder`는 `research/levstop/levstop.py`의 `tiers|2.0`과 **완전히 같은 숫자**여야 합니다(스크립트가 직접 확인하고, 다르면 결과를 쓰지 않음).

## 3. 계산 (기존 기계를 읽기만 함)
- 자료: 5년 신호 캐시(`sig_<tf>_<COIN>.npz`, levstop과 같은 캐시), 기간 **1기** 2021-08-01 ~ 2024-07-01, **2기** 2024-07-01 ~ 2026-09-30(신호 봉 UTC), levstop과 같음.
- 신호마다 따로(포지션 제한 없음), `profiles._scan`과 같은 봉 경로(그 시간봉의 시가·고가·저가·종가), 같은 탐색 단계(64 → 512 → 4096봉). 다음 봉 시가 + 슬리피지 진입, 비용(테이커 0.05% 양쪽, 슬리피지 0.02% 양쪽, 펀딩 8시간 0.01%)은 `rules_bt` 값. 4096봉 안에 안 끝난 신호는 뺍니다.
- **고정 익절 체결:** 봉의 유리한 쪽 극값(매수는 고가, 매도는 저가)이 익절가에 닿으면 그 봉에서 익절가로 나갑니다. 다른 청산과 같은 테이커 수수료와 슬리피지를 냅니다. 봉이 익절가 너머에서 열려도 익절가로 칩니다(유리한 갭은 쳐주지 않음, 보수적).
- **같은 봉에서 손절(또는 잠금, 또는 청산)과 익절이 둘 다 닿으면 손절이 먼저**라고 봅니다(봉 안의 순서는 모름, 보수적).
- 잠금은 levstop/`_scan`과 같이 그 봉에서 올라가면 다음 봉부터 적용됩니다.
- 강제청산: 크기 조건상 손절이 청산가 안쪽이므로, 봉이 청산가 너머에서 열릴 때만(ROE −100%) — `_scan`과 같음.

## 4. 숫자
- **지표:** 거래당 **자금 대비 손익**(ROE × 증거금 비율; levstop의 `mean_eq`).
- 칸 = 매매법 × 시간봉. **주 대상: 15분·30분·1시간·4시간**(144칸). 5분은 v3에서 빠지므로 **참고로만** 따로 적고 판정에 넣지 않습니다(5분은 따로 BH 보정).
- 칸 × 방식마다: 거래 수, 평균 ROE, 평균 자금 대비 손익(전체, 1기, 2기), 승률, 익절 비율, 강제청산 비율, 평균 보유 봉 수, 계좌 결과.
- **짝지은 차이:** 같은 신호에서 (그 방식의 자금 대비 손익 − `ladder`의 자금 대비 손익). 두 방식 모두 끝난 신호만. 칸마다 차이의 평균(전체, 1기, 2기).
- **검정:** 짝지은 차이의 평균에 대해 levstop과 같은 주 단위 블록 부트스트랩(`paperbot/agents/newlab.py` `boot_mean_p`, 2,000번, 한쪽): `p_better`(차이 > 0), `p_worse`(부호를 뒤집어).
- **보정:** 방식마다, 주 대상에서 짝지은 거래가 **30건 이상인 칸들**에 대해 Benjamini–Hochberg FDR 10%(좋은 쪽, 나쁜 쪽 각각).
- **파산:** 칸 × 방식 × 기간마다 계좌 하나(levstop `account`와 같음): $5,000 시작, 여섯 코인에 한 번에 한 포지션, 코인 순서 BTC·ETH·SOL·DOGE·LTC·BCH, 거래마다 자금 × (1 + 자금 대비 손익), $10 아래면 파산.
- **합친 평균(pooled):** 주 대상 모든 칸의 짝지은 거래를 합친 거래당 평균, 방식과 `ladder` 각각, 1기·2기 따로와 전체.

## 5. 판정 규칙 (결과 보기 전에 정함)
고정 익절 방식(`tp1R`, `tp1.5R`, `tp2R`, `tp3R`, 그리고 `ladder_tp2R`) 하나로 **바꾸라고 권하는 것은 아래 셋을 모두 만족할 때만**입니다. 주 대상(15분~4시간)만 봅니다.

- (a) 합친 평균(짝지은 거래)이 `ladder`보다 **1기와 2기 모두에서** 높다.
- (b) 짝지은 차이가 BH 10% 보정 뒤 **유의하게 플러스인 칸이, 짝지은 거래 30건 이상인 칸의 절반 이상**이다.
- (c) 파산한 계좌 수(주 대상 칸 × 2기간)가 `ladder`보다 **많지 않다**.

하나라도 못 미치면 **계단 잠금을 유지**하라고 권합니다. 여러 방식이 모두 통과하면 전체 합친 차이가 가장 큰 것을 적되, 여러 개를 본 데서 오는 선택 편향이 있다고 같이 적습니다.

미리 밝혀 둠: 익절 방식은 거래 결과의 모양(작게 자주 벌기 vs 드물게 크게)을 바꿀 뿐, 진입의 우위를 만들지 않습니다. 지금 규칙의 5년 거래당 평균은 대부분 칸에서 마이너스(levstop `tiers|2.0`)이므로, **고정 익절로 마이너스 매매법이 플러스가 되는 것은 기대하지 않습니다.** 통과하더라도 "덜 잃는다"일 수 있습니다.

## 6. 실행 시간과 출력
- 목표: 4코어에서 20분 안. 넘으면 부트스트랩만 1,000번으로 줄이고 JSON에 적습니다.
- 출력: `research/exitstyle/out/exitstyle.json`(2 MB 미만), `research/exitstyle/out/SUMMARY_KO.md`(쉬운 한국어 요약표와 위 규칙에 따른 판정, 코드가 씀).

---

## English (short)
Pre-registered before any run. Question: would a fixed take-profit beat the current stepped lock ("ladder") with everything else unchanged (2×ATR14 stop, 50/40/30/20x tiers at 40/40/30/20% margin, same sizing checks, costs, bust < $10, one position per account)? Arms: `ladder` (baseline; must reproduce levstop `tiers|2.0` exactly), `tp1R`, `tp1.5R`, `tp2R`, `tp3R` (stop fixed at 2 ATR, no lock, TP at raw entry ± R·2ATR), `ladder_tp2R` (lock plus a 2R cap). Same signals, entries and sizes; only exits differ. Bars of the timeframe as in `profiles._scan`; TP filled at the TP price with taker fee and slippage (no favourable-gap credit); a bar touching both stop/lock/liquidation and TP is a stop (conservative). Metric: P&L per trade as share of equity. Primary scope 15m/30m/1h/4h; 5m reported separately as context only. Test: paired per-signal difference (arm − ladder), week-block bootstrap 2,000, one-sided each way; BH FDR 10% per arm over primary cells with ≥30 paired trades. Busts: one $5,000 account per cell/arm/period. Decision: recommend switching only if (a) pooled paired mean beats ladder in both periods, (b) significantly positive after BH in at least half the cells with ≥30 trades, and (c) no more busts than ladder; otherwise keep the ladder. Turning negative strategies positive is not expected.
