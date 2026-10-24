# 역할 조합 연구 공용 데이터 (review1024 / roles / data) — 목록과 사용법

친구 원칙("추세형은 상위 봉에서 방향만 보고, 횡보 자리·눌림·돌파 매매법이 그 추세 쪽으로 진입")을 시험할 네 연구가 함께 쓰는 데이터입니다. 한 번 만들고 스스로 점검했습니다. **이 데이터는 결과(수익)를 고르지 않습니다.** 무엇을 고르든 다른 기간에서 한 번 확인하고, 같은 신호의 동전 던지기 쪽과 비교하고, 시도한 수만큼 보정해야 합니다(맨 아래 "주의").

- 스크립트(이 폴더): `/home/user/crypto-bot-research/analysis/review1024/roles/data/`
- 큰 파일: `/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/review1024_roles/data/` (아래에서 `OUT/`)
- 내보내기 추출본(믿지 않는 데이터, 읽기만): `/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/review1024_roles/data_x/`
- 실행: 이 폴더에서 `-I` 없이 `python3 <스크립트>` (pandas 때문). 다른 폴더의 스크립트에서는 `sys.path.insert(0, "<이 폴더>")` 후 `import rolesdata as RD`.

## 1. 공통 약속

| 항목 | 내용 |
|---|---|
| 시각 | `t` = 신호 봉의 마감 시각(ms, UTC). 진입 = 그 분(봉 마감 직후 1분봉)의 시가. `e` = 2020-01-01 00:00 UTC부터의 분 수(`t = T0 + e분`). `t_kst` = 한국 시간. |
| 코인 | `coin` = 0 BTC, 1 ETH, 2 SOL, 3 DOGE, 4 LTC, 5 BCH (`common.COINS` 순서). 규칙봇이 기록한 XRPUSDT(기록 전용 3,510줄)는 `coin = -1`, 재계산 값 없음. |
| 방향 | `side` = +1 롱, -1 숏. |
| 1분 자료 | 연구 1분 격자(바이낸스 USDT-M, 2020-01-01 ~ 2026-10-23 00:00 UTC) + 규칙봇 자체 1분봉(`live_bars.csv`, 10-23 00:00 ~ 10-24 14:11 UTC)으로 늘림. 겹치는 24,805분/코인에서 시가·고가·저가 완전히 같음(종가·거래량 2분만 4e-6 이하 차이). |
| 비용 | 왕복 0.124% = (테이커 0.042% + 슬리피지 0.02%) × 2 (WOO X Pro). **TetherMax 페이백(테이커의 90%) 미포함.** 넣으려면 r에 `common.PAYBACK` = 0.0756%를 더함(`add_outcomes(payback=True)`; 35배에서 ROE +2.65%p). |
| 펀딩 | 격자의 실제 펀딩. **2026-10월은 공개된 월 파일이 없어 0**, 늘린 구간도 0. |
| 결과 열 | `<v>_r` = 순 가격 수익률(비용·펀딩 뺀 뒤), `<v>_roe` = 레버리지 × r, `<v>_k` = 진입 분부터 청산 분까지 분 수, `<v>_why` = 0 손절, 1 계단 잠금 청산, 3 자료 끝에서 아직 열림(마지막 종가로 표시: **빼거나 표시할 것**). `<v>_opp_*` = 같은 진입 시각의 **반대 방향**(동전 던지기 쌍둥이). |
| 청산 `<v>` | `w35` 주인님 실거래 청산: 35배, 순 ROE -50% 손절, 계단(+12% → +10% 잠금, 이후 5%마다: +17 → +15, +22 → +20 …; `frdeep.walk3`, 시간·취소·BTC·본전 청산 없음) / `w30` 같은 것 30배 / `w35s20` 35배 순 ROE -20% 손절 / `a2` 하우스형: 신호 봉(그 봉 자신의 시간봉) ATR14 × 2 가격 손절 + 같은 계단, 30배, 순 ROE 상한 없음(바닥 -100% = 증거금), 레버리지 낮추기 없음(`frloss.walk2`). |
| 기간 | `five` = 봉 마감 2020-03-01 ~ 2026-10-23 00:00 UTC / `fwd` = 2026-10-05 15:00 ~ 10-24 15:00 UTC(= 10-06 ~ 10-24 KST) / 고르기·확인용 보조: `select` 2020-03 ~ 2023-12, `confirm` 2024-01 ~ 2025-06, `late` 2025-07 ~ 2026-10-22 (`rolesdata.PERIODS`; 다른 분할을 써도 됨, 단 고르기 전에 정할 것). |
| 상위 봉 | 신호 마감 시각 이하에 **마감한** 마지막 상위 봉(`common.last_closed`). 같은 분에 마감한 상위 봉은 포함(실봇도 마감 8~20초 뒤 읽음), 그 뒤 봉은 절대 안 씀. |
| 예열 | 신호: `signals(min_nb=300)`이 기본(코인별 그 시간봉 첫 300봉 제외). 상태: `add_states(min_nb=300)`이면 상위 봉 번호 < 300인 상태를 0으로. 판단: `add_judge(min_nb=120)`(실봇 MIN_BARS). |
| 진입 막기 | `blk` = `frcore.blocked` 코드: 0 없음, 1 한국 주말, 2 미국 지표 ±30분, 3 나스닥 개장 ±30분. **지표 일정 파일(data/macro_events.csv)이 2026-10부터만 있어 5년 구간에서 2는 거의 안 나옴.** |

## 2. 파일

### 2-1. 늘린 1분 격자 캐시 — `OUT/ext/<coin>.npz` (6개, 각 111 KB)
- 열: `ts`(분 시작 ms), `o h l c v`; 2,292분/코인 (2026-10-23 00:00 ~ 10-24 14:11 UTC).
- 쓰임: `common.grid(coin)`이 연구 격자 뒤에 붙임. 추출본 `live_bars.csv`는 디스크 때문에 지웠음(캐시가 있으니 필요 없음; 다시 만들려면 규칙봇 zip의 `current/live_bars.csv`를 새 빈 폴더에 풀고 `common.LIVE_BARS`를 그 경로로).

### 2-2. 결과 격자 — `OUT/grid/<coin>.npz` (6개, 합 61 MB) + `OUT/grid/blk15.npy`
**모든 15분봉 마감(2020-01 ~ 2026-10-24 14:00 UTC, 코인당 238,904개)에서 롱·숏 둘 다**의 거래 결과. 실거래 청산(w35/w30/w35s20)의 결과는 (코인, 진입 분, 방향)에만 달려 있으므로 **어느 매매법·어느 조합 신호든 이 표에서 바로 찾습니다**(30분·1시간·4시간 마감도 15분 마감 위에 있음).
- `valid15` (bool, 238,904): 봉이 온전하고 진입 분이 있음. 15분봉 번호 j: 봉 시작 = T0 + j×15분, 진입 분 e = (j+1)×15.
- `w35_L_r / _k / _why`, `w35_S_*`, `w30_*`, `w35s20_*`: float32 / int32 / int8 (위 약속).
- `a2_<tf>_<L|S>_r / _k / _why` (tf = 15m, 30m, 1h, 4h; 그 시간봉의 봉 번호 기준), `atr14_<tf>`(float64, 그 봉의 ATR14).
- `blk15` (int8): 15분 마감 진입 분의 막기 코드(코인 공통, `blk15.npy`와 같음). `first`, `n_minutes`, `n_grid`.
- 기간: 각 코인의 첫 온전한 봉 ~ 2026-10-24 14:00 UTC. 끝 근처 진입은 열린 채 끝날 수 있음(`why == 3`).

### 2-3. 신호 — `OUT/signals/<coin>.npz` (6개, 합 15 MB) + `OUT/signals/names.csv`
2020-01 ~ 2026-10-24 14:00 UTC(늘린 격자)의 **모든 코드화된 매매법 121개 × 15m·30m·1h·4h** 신호(진입·타이밍·추세형 모두; 연구에서 역할로 거름), 추세 소스 44개는 1d도.
- `names.csv`: `sid, set, name` — core 36(잠긴 규칙, `research/entry_study/param_defs` sha256 확인), ds 44(DeepSeek, `research/fullgrid/ds_defs.py` 기본값 = lib_c), lib 40(`research/library/lib.py` entries, 타이밍 오실레이터 O1~O7 포함, +F200 쌍둥이 제외), friend 1(FRIEND_ROC). 역할은 `rolesdata.names()`가 `../map/roles.json`에서 붙임(trend 44, pullback 25, reversal 18, breakout 15, range 9, timing 7, other 3; 릴스 5분은 없음).
- 형식: `<tf>_<sid>_L`, `<tf>_<sid>_S` = 봉마다 신호 여부의 `np.packbits`, `<tf>_n` = 봉 수, `<tf>_e0` = 0번 봉의 마감 분. 신호의 e = e0 + 봉번호 × tf분. 읽기는 `rolesdata.signals()` 또는 `rolesdata.signal_bits()`.
- 개수(6코인, 예열 포함 전체): 15m 7,383,270 / 30m 3,782,164 / 1h 1,959,524 / 4h 501,654 / 1d 34,211.
- 4h는 116개(DeepSeek 일부는 4h 정의 없음), 1d는 core + lib 추세 소스 44개만(DeepSeek·FRIEND_ROC는 1d 정의 없음).
- 같은 봉에 롱·숏이 둘 다면: lib는 롱, ds는 둘 다 버림(코드 그대로).

### 2-4. 상위 봉 추세 상태 — `OUT/states/<coin>_<htf>.npz` (18개, 합 17 MB) + `OUT/states/state_defs_ko.json`
htf = 1h(코인당 53,551~59,726봉), 4h(13,387~14,931), 1d(2,230~2,488). 닫힌 봉 하나마다 한 값.
- `ts`(봉 시작 ms), `nb`(코인의 봉 번호).
- 추세판단 봇 판단(`paperbot/trendjudge.vote_arrays`를 그대로 호출): `j_V39 j_S6 j_OBV j_N12`(+1/-1/0), `j_raw3`(4개 중 3개 같은 쪽), `j_dir`(raw3가 유지 봉 수만큼 유지: 1h 2봉, 4h·1d 1봉 = TrendRules 기본), `j_adx`(ADX 14·14), `j_ema20`, `j_atr`(ATR14), `j_close`. 2-of-4나 4-of-4는 네 표에서 직접 계산.
- `c_<소스>` (int8, 52개 = roles.json `trend_incl_dual`): **조건 상태** — 그 매매법 코드가 읽는 지표로, 그 숫자 그대로 +1/-1/0. 정의는 `state_defs_ko.json`(예: OBV_S = OBV vs 30봉 평균, F4_FAN = EMA 8>13>21>34>55, T1_EMA50_200 = EMA50 vs EMA200, N03 = EMA50 vs 200 그리고 ADX ≥ 25일 때만). V39_ALL·S6·OBV_S·N12는 추세판단 봇 판단과 같은 값.
- `l_<소스>` (int8): **래치 상태** — 그 매매법 자기 신호의 마지막 방향(반대 신호까지 유지, 첫 신호 전 0). 1h·4h는 52개 모두, 1d는 44개(DeepSeek·FRIEND_ROC 없음).
- 1d에서 F6_VWAP_CROSS, F15_OPEN0930, F15_OPEN0000의 조건 상태는 정의가 안 돼 0. F7_RF_TRIPLE의 '한 단계 위 봉'은 1h→4h, 4h→1d, 1d는 없이 둘만.
- 처음 몇 봉: ADX는 26번째 봉부터, EMA20은 20번째부터 값이 있음(그 전은 NaN → 판단 0).
- 쓰는 대응(7개 모두 가능): 15m→1h, 15m→4h, 30m→1h, 30m→4h, 1h→4h, 1h→1d, 4h→1d — `add_states(S, "1h"/"4h"/"1d", …)`; `"auto"` = 추세판단 봇 대응(15m·30m→1h, 1h→4h, 4h→1d).

### 2-5. 실시간(forward) 표 — `OUT/forward_*.csv.gz`
모든 표에 공통으로 붙은 재계산 열: `e, blk, p0`(진입 분 시가), 위 네 청산의 `*_r/_k/_why` + `*_opp_*`, `j1h_* j4h_* j1d_*`(각 상위 봉의 `i`(봉 번호), V39 S6 OBV N12 raw3 dir adx adx_prev ema20 atr close bar_close), `spot_ema20 spot_atr spot_rsi spot_range spot_close`(신호 봉 자신의 값, trendjudge.spot_frame과 같은 식), `tj_htf tj_dir`(추세판단 봇 대응의 상위 봉 판단), `tj_why_1022`(10-22 설계: 보류여도 진입) / `tj_why_1021`(10-21 설계: 보류면 안 함) — '' 또는 NaN = 통과, 아니면 hold / against / weak / tired / breakout / far_htf / far_etf / rsi / na, `far_htf_atr far_etf_atr`(가격 = p0). 15m 신호에도 1h 판단을 붙였음(실봇엔 15m 멤버 없음).

| 파일 | 줄 × 열 | 기간 | 내용 |
|---|---|---|---|
| `forward_rule.csv.gz` | 53,333 × 114 | 봉 마감 2026-10-05 18:40 ~ 10-24 14:00 UTC | 규칙봇 v4가 기록한 **모든 신호**(signal_log): `sig_id, t, t_kst, coin, symbol, side, strategy, tf, role, log_status`(SUBMITTED 49,619 / RECORD 3,578 = 1d·XRP 기록 전용 / LATE 136 = 180초 넘게 늦어 거래 안 함), `delay_ms, ref_price, atr_logged`; 종이 계좌의 결정 `acct, group`(core / ds200 / flip / reel / record), `acct_status`(ENTERED 13,175 / SKIPPED 35,768 / REJECTED 676), `acct_reason`(in position, lower score…), `taken`; 거래된 것은 **하우스 청산 실제 결과** `tr_id, tr_entry_time, tr_entry_price, tr_exit_time, tr_exit_reason`(SL / LOCK), `tr_leverage`(20~50배 품질 규칙), `tr_tier, tr_margin, tr_roe`(순), `tr_pnl, tr_fees, tr_funding, tr_price_move, tr_equity_after, tr_lock_roe, tr_htf_regime, tr_regime, tr_htf`, `tr_open`(내보낼 때 아직 열림, 136) + 공통 재계산 열. 시간봉: 15m 25,723 / 30m 13,250 / 1h 7,198 / 4h 1,941 / 5m 1,643(릴스·5분 동전, a2 없음) / 1d 68(a2 없음) + XRP 3,510. |
| `forward_trendbot.csv.gz` | 268 × 122 | 봉 마감 2026-10-22 00:00 ~ 10-24 23:00 KST | 추세판단 봇 종이(`combo/live-ac.db`의 10-21 15:00 UTC 이후 142줄, `bot = trend`)와 되돌림 대기 그림자(`combo/shadow-trend-wait.db` 126줄, `bot = trend_wait`)의 signal_log 전부: `row_id, member, strategy, status`(FILTERED / SUBMITTED / BROKE), `why`(봇이 남긴 한국어 이유), `source, score`, **봇이 기록한 판단** `log_j_*`(bar_close, tf, raw, dir, 4표, adx, adx_prev, ema20, atr, close), `log_spot_*, log_price, log_far_*`, 그 봇 거래 `tr_*`(COMBO@mix만) + 공통 재계산 열. |
| `forward_ac.csv.gz` | 301 × 122 | 봉 마감 2026-10-19 13:00 ~ 10-21 23:00 KST | 같은 DB의 전환 전(A+C 합본 봇) 줄. |
| `forward_league.csv.gz` | 4,456 × 95 | 신호 봉 마감 2026-10-13 18:00 ~ 10-24 21:30 KST | **후보 리그는 신호별 기록이 없음**(DB에 거래·일별 개수만). 그래서 리그의 거래: `acct, strategy, symbol, tf, side, t`(신호 봉 마감), `tr_entry_time … tr_roe, tr_pnl, tr_style`(청산 규칙 이름), `role` + 공통 재계산 열. |

### 2-6. 점검과 기준 표 (이 폴더)
- `selfcheck_report.json`, `match_rates.csv`(전략 × 시간봉 293칸의 기록 vs 재계산 일치), `baseline_5y.csv`(475줄, 아래 4절).

### 2-7. 스크립트 (이 폴더)
| 파일 | 하는 일 |
|---|---|
| `common.py` | 경로, 늘린 격자 `grid()`, `bars()`, 기간·비용·청산 상수, 매매법 코드 불러오기 |
| `build_grid.py` | 결과 격자 + 막기 코드 (≈ 40초) |
| `build_signals.py` | 신호 비트맵 (3개 병렬 ≈ 6분) |
| `build_states.py` | 상위 봉 상태 (≈ 1분; 신호가 먼저 있어야 함 — 래치) |
| `build_forward.py` | 실시간 표 4개 (≈ 1분; 상태가 먼저) |
| `rolesdata.py` | **연구용 불러오기**: `names, signals, signal_bits, add_outcomes, add_blocks, htf_index, add_states, add_judge, spot, forward, one_position, account, goal_bootstrap` |
| `selfcheck.py` | 아래 3절 점검 (≈ 1분) |
| `baseline.py` | 아래 4절 기준 표 (≈ 1분) |

다시 만들기(순서대로): `python3 build_grid.py && python3 build_signals.py 3 && python3 build_states.py 3 && python3 build_forward.py && python3 selfcheck.py && python3 baseline.py`.

## 3. 자기 점검 결과 (`selfcheck_report.json`)
- **A. 실시간 신호 재현:** 규칙봇이 기록한 6코인 15m~4h 신호 47,350개(10-05 18:45 ~ 10-24 14:00 UTC, 293칸, core·DeepSeek 모두)와 늘린 격자에서 다시 계산한 신호가 **양쪽 모두 100% 같음**(기록된 것 중 재계산에 있는 비율 1.0, 재계산된 것 중 기록에 있는 비율 1.0; 반대 방향으로 다른 것 0). 칸별 결과는 `match_rates.csv`(전부 1.0). XRP 3,510줄은 격자가 없어 제외. (처음 돌렸을 때 0.93이 나왔는데 원인은 XRP를 빼지 않은 것과 불러오기의 기간 끝 1봉 누락이었고, 고친 뒤 경계 단위 시험을 통과.)
- **B. 추세판단 봇 판단 재현:** (1) 실봇처럼 마지막 300개 닫힌 봉으로 `trendjudge.judge_frame`을 돌린 900곳(6코인 × 1h·4h·1d × 50)에서 4표·raw3·dir·봉 마감 100% 같음, ADX 차이 최대 1e-6. (2) 추세판단 봇이 기록한 판단 97줄과 4표·raw·dir·ADX·진입 봉 RSI·EMA20 100% 같음. 봇이 남긴 이유 95줄과 다시 계산한 검사 이유도 100% 같음(그 시각에 쓰던 설계로 비교: 보류 허용 10-22 설계는 로그상 **2026-10-23 01:00 KST부터**). (3) 봇이 마지막으로 저장한 판단(10-24 23:25 KST, 6코인 × 1h·4h·1d 18개) 모두 같음.
- **C. 손으로 확인한 5개 신호**(매법 5개에서 하나씩 무작위): 읽은 상위 봉의 마감이 신호 마감 이하이고 다음 상위 봉은 신호 뒤에 마감; S6(종가 vs EMA20, +DI vs −DI를 직접 Wilder 식으로), OBV vs 30봉 평균, EMA50 vs EMA200, ROC9 부호를 따로 계산해 표와 모두 같음; 그 상위 봉에서 자료를 잘라(미래 봉 없이) 52개 조건 상태와 4개 판단을 다시 계산해도 **하나도 다르지 않음**(지표 코드가 미래를 보지 않음).
- **D. 결과 격자:** 실시간 표의 직접 계산과 격자 찾아보기가 48,112줄 × 8개(4 청산 × 양쪽) 모두 같음; 규칙 글만 보고 따로 짠 순수 파이썬 걷기와 격자가 무작위 1,554건에서 r·k·이유 100% 같음; 계단 잠금이 `paperbot/ladder.LadderSpec`과 같음. 규칙봇 하우스 실제 거래 12,082건 vs a2 재계산: 손익 부호 95.3% 같음, ROE 상관 0.88(같을 수 없음: 실봇은 기준가 + 슬리피지 체결, 20~50배, 바이낸스 수수료, 실제 펀딩).
- **E. 빈 값·미래 보기:** 격자에 유효한 칸의 NaN 0, 무효 칸에 값 0; 실시간 표의 상위 봉 마감 > 신호 마감인 줄 0; 불러오기의 상태 연결에서 미래·묵은 봉 0. 실시간 표 15m~4h의 빈 결과 3,499줄 = 모두 XRP. `w35` 기준 열린 채 끝난 줄 554(대부분 10-23~24 신호).

## 4. 기준 표 `baseline_5y.csv` (설명용, 고르기용 아님)
5년(2020-03 ~ 2026-10-22), 각 신호를 하나씩(한 포지션 규칙 없이), 35배 실거래 청산:
- 열: `name, tf, set, role, n, per_day, long_share, w35_roe`(신호 방향 평균 순 ROE), `w35_opp_roe`(같은 진입의 반대 방향), `agree_raw`(상위 봉 3-of-4 투표와 같은 쪽 비율), `n_with / roe_with`(유지 판단과 같은 쪽), `n_against / roe_against`, `n_nodir / roe_nodir`, `rolemap_htf_agree`(역할 지도 값).
- 교차 확인: `agree_raw`가 역할 지도(`../map/roles_measured.csv`, 2021-01부터, 따로 계산)와 중앙값 차이 0.002, 0.05 넘게 다른 칸 2개(신호 7개·19개짜리, 시작 시점 차이).
- **연구 전에 알아둘 사실:** 475칸 평균 신호 방향 -3.66% / 반대 방향 -3.76% ROE(거래 하나당, 35배, 비용 후). 신호 방향이 플러스인 칸 9개, 반대가 플러스인 칸 5개. 즉 **매매법 하나를 단독으로 모든 신호에 쓰면 5년 동안 동전 던지기와 거의 같고 비용만큼 잃습니다.** 조합(추세 상태 + 진입 + 타이밍)이 이것을 넘는지가 네 연구의 질문입니다.

## 5. 불러오기 예 (친구가 말한 그대로: 4시간 OBV 추세 + 1시간 스토캐스틱 RSI 타점)
```python
import sys; sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
import rolesdata as RD
S = RD.signals(names=["O4_STOCHRSI_ZONE"], tfs=["1h"], period="select")   # 고르기 기간
S = RD.add_outcomes(S, ["w35"])                    # w35_roe + w35_opp_roe(동전 쌍둥이)
S = RD.add_states(S, "4h", ["OBV_S"], kind="c")    # c4h_OBV_S: 마지막으로 닫힌 4시간봉의 OBV 상태
S = RD.add_judge(S)                                # 추세판단 봇 판단 + 진입 검사 이유
S = RD.add_blocks(S)
A = S[(S.c4h_OBV_S == S.side) & (S.blk == 0) & (S.w35_why != 3)].reset_index(drop=True)
took = RD.one_position(A, "w35")                   # 한 번에 한 포지션(전 코인)
print(RD.account(A[took], "w35", margin=0.4))       # 거래 수, 하루 거래, 평균 ROE, 최종 배수, 최대 낙폭
print(RD.account(A[took], "w35", margin=0.4, side_col="_opp"))   # 같은 진입의 반대 방향
print(RD.goal_bootstrap(A[took], "w35", margin=0.4))  # 30일 x6 확률, 50%·90% 먼저 잃을 확률(일 단위 블록 부트스트랩)
```
- `one_position`: 앞 거래의 청산 분(e + k)보다 뒤에 진입하는 신호만. 같은 분이면 `priority` 열(작은 것 먼저), 없으면 코인 순서 → 시간봉 순서.
- `account`: 자산 × (1 + 증거금 비율 × ROE), ROE 바닥 -100%.
- `goal_bootstrap`: 그 기간의 UTC 날을 (거래 없는 날 포함) 30개 뽑아 순서대로 복리. 결과: `p_target`(기간 안에 목표 배수 도달), `p_lose50_first`(목표 전에 -50%), `p_lose90_first`(목표 전에 -90%), `median_final_x`. 다른 방식(거래 단위, 다른 기간 길이)을 써도 되지만 같은 표를 쓰면 네 연구가 비교됩니다.
- 실거래 진입 가격은 신호 봉 마감 직후 분의 시가(`p0`). 실봇은 몇 초 뒤 기준가로 들어가므로 아주 조금 다를 수 있음. `add_judge(check=True)`의 거리 검사 가격은 신호 봉 종가(실봇 기준가에 가장 가까운 값), 실시간 표의 검사 가격은 `p0`.

## 6. 주의 (정직하게)
1. **결과는 지표가 아니라 시뮬레이션입니다.** 1분봉 안의 순서(고가·저가 중 먼저)는 모르므로 손절과 잠금이 같은 분에 닿으면 손절 먼저(보수적). 진입 분 시가 체결, 슬리피지는 비용 0.02%로만 반영, 호가 깊이·지연 없음.
2. **10월 펀딩 0**(공개 파일 없음). 늘린 구간(10-23 ~ 10-24)도 0. 하락장 숏에 유리했을 수 있는 펀딩 효과가 실시간 재계산에는 없습니다.
3. **실시간 기간은 대부분 하락장**이었습니다. 숏이 많은 조합은 운으로 좋아 보일 수 있으니 반대 방향(`*_opp_*`)과, 같은 기간 시장 방향을 같이 보세요. 실시간 표본도 작습니다(규칙봇 계좌당 닫힌 거래 중앙값 21~32개, 추세판단 봇 표에 연결된 거래 11개 = 종이 7 + 되돌림 대기 그림자 4).
4. **macro 막기는 2026-10 이후에만** 의미가 있습니다(일정 파일이 그때부터). 5년 결과에서 지표 발표 시간은 걸러지지 않습니다.
5. **a2는 하우스 청산과 똑같지 않습니다:** 30배 고정, 레버리지 낮추기(손절 손실 ≤ 자금 15%) 없음, 순 ROE 상한 없음. 4시간 신호의 2 ATR은 30배 청산가 근처일 수 있어 -100%까지 갑니다. 실제 하우스 결과는 `forward_rule.tr_*`(거래된 것만).
6. 규칙봇 신호 재현은 100%이지만, 이는 **기본값 규칙**의 신호입니다. 리그·A+C·추세판단 봇 멤버의 맞춤값·필터·뒤집기는 신호 표에 없습니다(그 봇들의 실제 선택은 `forward_trendbot / forward_ac / forward_league`).
7. 조건 상태(`c_`)는 매매법의 "진입 순간"이 아니라 그 코드가 읽는 지표의 **상태**를 제가 정의한 것입니다(`state_defs_ko.json`). 래치(`l_`)는 그 매매법 신호 자체의 방향입니다. 둘이 다를 수 있으니 연구에서 둘 다 볼 수 있습니다. S5_DONCHIAN_MFI, T6_DON20/55, C4_THREE_SAME의 조건 상태는 정의상 래치입니다.
8. 1d의 DeepSeek·FRIEND_ROC 래치, 1d의 VWAP·뉴욕 시가 조건 상태는 없음(0).
9. 신호 표의 초기 봉: 코인이 늦게 상장된 SOL(2020-09), DOGE(2020-07) 등은 첫 300봉을 기본으로 뺍니다. EMA200·1d 같은 느린 지표는 처음 몇 달 값이 불안정할 수 있습니다.
10. **고르기 규칙:** 어떤 조합·필터를 고르든 고르는 기간과 확인 기간을 미리 나누고, 확인 기간은 한 번만 보고, 같은 진입의 동전 쌍둥이(반대 방향 / 무작위 방향)와 비교하고, 시도한 조합 수로 BH 보정 또는 전체 탐색 순열 검정을 하세요. 기준 표(4절)에서 좋아 보이는 칸을 고르는 것도 '시도'입니다.
11. 디스크가 거의 차 있습니다(남은 공간 약 150 MB, 다른 분석도 씀). 이 데이터는 약 95 MB입니다. 큰 중간 파일을 만들 때는 압축하고 끝나면 지우세요.
