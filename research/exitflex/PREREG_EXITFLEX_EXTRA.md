# Extra reads and twin accounts for the exit study (exitflex extra v1)

'The main file' is research/exitflex/PREREG_EXITFLEX.md, pinned in commit d038c93 (2026-10-12 11:59:51 UTC); section numbers without
a prefix refer to it. This file is its 16.7 item 4.

## E.0 Status, pins and record
1. Pins. This file and a first PREREG_EXITFLEX_EXTRA.sha256 that lists it are committed and pushed before `runner_x.py select` is
   started (O7). The modules and tests in research/exitflex/extra/ (E.6) are committed and pushed, with the pin file extended to list
   them, before any output of the select stage is opened (O8). The O7 and O8 commits and the select stage's [pin ok] time and HEAD go
   to sent.json (field extra_note), not into this file.
2. Changes. A change to a pinned file of this set after its pin goes to research/exitflex/DEVIATIONS.md, dated, with the reason. Two
   drops are pre-registered here and are not deviations: (a) at O8 a tier C read, or X-017 when its tests are not green, may be left
   uncoded; it is then listed in extra_reads.json, field dropped_at_o8, with the reason; (b) the time cap of E.5. A tier A or B read
   that is not coded at O8 is a deviation.
3. No file listed in PREREG_EXITFLEX.sha256 is changed for these reads. No module of the main file imports research/exitflex/extra/.
4. Record of looks during design (section 14). The reads were drafted on 2026-10-12 by sub-sessions of the main session. Some of
   their scratch scripts (scratchpad/reads_plan/; among them counts.py, feas.py, feas2.py, fund.py, lens_h/p2_funnel.py,
   lens_h/p5_funnel_coin.py and lens_h/p6_funnel_all.py) ran on the real select cut and, by their code, printed or saved
   select-period figures. These were:
   - E0's offered, entered, skipped and rejected counts per pick and pool;
   - E0 trade counts by weekend, side, timeframe, coin, session, weekday and 4-hour block per pool;
   - entered counts of all 89 arms on the picks they ran;
   - in fund.py, the mean funding paid as a percent of notional by side for each pool, the DeepSeek pool included. That is a
     DeepSeek money figure under D11.
   Saved files: reads_plan/e0_counts.pkl (sha256 prefix bf719e50f128676e), reads_plan/lens_h/funnel_all.json (cf45e12bc0ff6161) and
   console logs. This corrects the sentence in section 15 that the design sub-sessions printed pass or fail and seconds only. The
   dated DEVIATIONS.md entry lists each script, what its print lines show and whether any figure reached the main session. The
   files are deleted after their sha256 values are recorded there, before the select stage starts.
   Remarks in this file about thin cells may reflect these looks. No definition, threshold, bucket or order here was set from them,
   and no read chooses anything.

## E.1 What these reads and twins are not
1. Descriptive only. They choose nothing and change no gate (8.1), placebo (6), default (8.4), claim (8.5), Holm or confirm rule (9),
   ledger or BH rule (10), report or choice rule (8.2, 8.3) or league lineup or check (11). A test checks that gates, the default and
   the choosable ids are identical with every output of this file deleted.
2. No choice by split. There is no choice per pick, coin, timeframe, side, weekday, session, market state, BTC state, volatility
   level, character, leverage tier, size or cost level (8.3, 12). Every page carries the Korean box W1 and every table the tag
   '참고용 · 고르는 데 안 씀'.
3. Select period only. Every read and twin uses trades, signals and minutes of 2021-01-01 00:00 to 2024-01-01 00:00 UTC only:
   - data_x.assert_no_minute_at_or_after runs on every array loaded;
   - no mark, window or return needs a minute at or after 2024-01-01;
   - no confirm-stage file or 2024-2026 material is opened (8.3);
   - no read has a confirm version.
4. Row rule (8.2 item 6; 16.7 item 4). A money figure is computed into an output only for E0, for the house exit H (twins only) and
   for the variants listed in select.json pools.<pool>.eligible_ids. It is never computed for a variant marked 선택 불가, in any
   table, figure, label, count, rank, correlation or sentence. Statistics over all 88 variants' money are not computed. Count-class
   fields (C8) may be shown for all 88.
5. DeepSeek (D11; section 3, extension for the extra reads).
   - Committed outputs, sent messages, agent packets and notes hold no DeepSeek money figure, money-derived label, rank, interval,
     bust, after-bust count or p value. DeepSeek rows hold only the count class of C8.
   - DeepSeek money is written only to $WORK/<pin8>/ds_private/extra_reads_ds.json, which nobody opens, and to
     $WORK/<pin8>/ds_private/owner_report_extra.md. The report has part '핵심' first (the headline reads and the twins' E0 and H)
     and then part '부록', under every rule of section 3:
     - shown only in the chat with the owners, in the same turn as or before SELECT_KO.md;
     - never committed or copied;
     - E0, H and choosable rows only, in committed row order, with no ranking by money and no p value;
     - it passes the A8 (3) checks made by this file's code;
     - its sha256 goes to sent.json (ds_owner_report_extra_sha256);
     - its last line asks the owners to name variants by id.
   - Owners' words that quote it are redacted as in section 3.
6. No p value anywhere. X-044's sign-flip p is used only inside a count and is never printed or stored. Intervals appear only in
   X-004, X-005, X-007 and X-037, and for DeepSeek only in the private report.
7. Small cells are shown. A cell under 100 of the read's stated unit is marked 건수 적음; fewer than 3 picks, 픽 N개; an empty cell,
   '-'. Nothing is hidden.
8. Order. Rows follow the select table's canonical order with E0 first (H second on twin rows). Coins follow league order BTC, ETH,
   SOL, DOGE, LTC, BCH. Buckets follow the order written in each read. Nothing is sorted by a result.
9. Files read, as a program:
   - results/select/ and ds_private/results/select/ (select_r2/ after a select rerun under 14);
   - select.json;
   - the step-2 placebo block files of choosable rows (X-037, X-042);
   - the select cut through data_x.open_cut, with the check of A5;
   - candidates.json through data_x.picks;
   - candleague code for the twins (E.8).
   Never read: core_not_choosable.json, select_ds.json, any owner report of a stage, any confirm file, or research/exitflex/out/.
   The loader refuses these paths (test). Nothing is written into the select stage's folders or into research/exitflex/out/.
10. A later study of weekday or weekend, session, coin, BTC-state, volatility, size, leverage or cost rules on these 38 picks, or of
    these exits on their default-number cells, cannot treat 2021-2023 as unseen; it lists these reads as looks in its own record.
11. Nothing here is a league check. The restarted league is judged only by 11.5 (C1, C2, the repeat). X-023 and X-044 decide
    nothing.

## E.2 Conventions
C1 Scope.
- Pools core (23 picks) and DeepSeek (15). Arms E0 and the 88 variants; twins add H (E.8).
- Size: scale 0.25 unless a read says otherwise. Period select: 36 UTC months, 1,095 days.
- Coins: the six of data_x.SYMBOLS. Pick bars 15m/30m/1h/4h: core 4/7/6/6, DeepSeek 1/1/6/7.

C2 Re-runs.
- Only kernel_x.simulate(market, pdata, arm, scale, 'select', offered=..., S=...) of the pinned kernel. Never
  runner_x.real_config: it refuses other stage names, and with 'select' it would empty that stage's cache.
- The extra code builds its own config:
  - data_x.open_cut;
  - data_x.RealProvider with the cache $WORK/<pin8>/extra/cache;
  - data_x.Market;
  - assert_no_minute_at_or_after;
  - F11 registered through runner_x.f11_provider_from_modules(rprov, *runner_x.try_load_native());
  - kernel_x.warm_up.
- A masked offered table is {k: v[mask] for k, v in off.items()} (every key, order kept). A flipped table replaces only 'side'
  (E.8). A settings variant is a copy of market.S(scale) with the stated entries changed.
- Each worker builds one pick's PickData once, loops over arms outside and masks or settings inside.
- Re-runs keep only reduced arrays (g, w_end, w0, max_dd, counts, reasons, hold, marks, and the trade arrays a read needs), in one
  file per pick, size and read under $WORK/<pin8>/extra/reduced/ (DeepSeek under ds_private/extra/reduced/), never committed.
- An all-true mask and an unchanged S copy reproduce the step-1 account exactly (test).

C3 Rows. Count columns cover all 89 arms. Money columns and every re-run except the audit of C5 cover E0 plus the pool's choosable
rows (twins: also H).

C4 Trade record. Built per entered trade i of an account (E0 and choosable rows; t_sig, q_i, e_i and x_i for all rows):
- Matching: q_i = the offered index of the trade from C5; t_sig = off.close[q_i]; e_i and x_i = the positions of tr_fill and
  tr_exit in the coin's 1m ts (asserted exact).
- Prices and sizing:
  - raw = o[e_i]; fill = raw x (1 + side x S[1]);
  - Rd = stop_atr x off.atr[q_i], with stop_atr = kernel_x.exit_of_pick(pick, arm)[0];
  - Wb = np.cumsum(np.r_[S[10], tr_pnl])[:-1];
  - (ok, lev, margin, qty, liq) = kernel._size(S, brs[coin], Wb_i, side, fill, raw - side x Rd, off.atr[q_i], off.best[q_i],
    qty_step[coin], min_notional[coin]), with ok and lev == tr_lev asserted.
- Per-trade values: x_i = pnl_i/Wb_i; l_i = ln(max(Wb_i + pnl_i, 1e-12)/Wb_i), with sum l_i = ln(max(w_end, 1e-12)/w0) asserted to
  1e-9; R_i = pnl_i/(qty x Rd); ROE_i = pnl_i/margin.
- Excursions, over the 1m last-price highs and lows of minutes e_i..x_i - 1 plus the exit price xpx (for LIQ, R_i and ROE_i
  replace the exit term):
  - Rn0(P) = (side x (P - fill) - fill x S[5])/Rd; ROE0(P) = lev x (side x (P/fill - 1) - S[5]);
  - best and worst of each;
  - funding is not included, and the exit minute's own range is never used.

C5 Signal status (0 skipped while holding, 1 entered, 2 rejected, 3 no fill, 4 after bust). It is rebuilt for every account from
the step-1 file and the offered table by the kernel's walk. For each signal q in order:
- e_q = kernel._entry_index(ts_coin, close_q + 60,000 - market.bar_ms);
- no fill minute before the period end -> 3;
- else, if an earlier trade left the wallet < S[9] -> 4;
- else, if ts[e_q] <= busy_until -> 0;
- else, if the next unmatched step-1 trade has (tr_coin, tr_fill) = (coin_q, ts[e_q]) -> 1. Then busy_until = tr_exit - 1 ms for a
  RULE or RAND exit, else tr_exit;
- else -> 2.
Assertions:
- every step-1 trade is matched in order;
- the counts of 0, 2, 3 and 4 equal the file's counts;
- no two offered signals of one pick share (coin, fill minute); such a pick uses a real re-run.
Audit: the real re-run of E0 and F12.a per pick at both sizes gives identical status and tr_* arrays (w_end to 1e-9), or the stage
stops and the finding is handled under 14.

C6 Pooling.
- Trade statistics pool the pool's accounts.
- Per-pick money statistics are equal-weight means over picks, as M_P.
- 'k of N' always prints N.
- Rates per account-month use the calendar denominator picks x 36.
- Alive months (money samples only): for a busted account (w_end < $10) the months after its last month with g != 0 are dropped
  from month and window samples.

C7 Flags. As E.1 item 7.

C8 Classes.
- Count class: counts of offered, entered, skipped, rejected and closed signals or trades as the kernel's status gives them, and
  their splits by coin, side, timeframe, 장세, calendar bucket, BTC state, volatility third, hold bucket or trade-identity class;
  win shares; hold hours and durations computed only from entry and exit times; exit-reason counts and shares; F12 component
  counts; labels in select.json; labels computed from these only.
- Money: everything else, including:
  - pnl, x, l, R, ROE, cost and funding amounts, growth, drawdowns, multiples;
  - busts, after-bust and no-fill counts, alive-month denominators, pick-months with 0 entries;
  - sizeable flags, the entry ceiling, leverage tiers, margin shares, lock distances, price excursions, streaks;
  - r_sel and character per pick;
  - money-derived labels, ranks and intervals.
- A guard (xr_common.ds_guard) refuses any DeepSeek row of a committed output with a key outside xr_common.DS_EXTRA_ALLOWED, and
  every committed output passes runner_x.py audit-file (test on synthetic DeepSeek outputs of every read).

C9 Split columns, for key K, pool P, arm A and bucket b:
- n_off (offered signals with K = b; signal-level keys only; identical for every arm, asserted);
- n_ent, n_skip and n_rej (C5); n (closed trades); win share; median hold and share > 8 h; exit-reason shares;
- money: mean R ± se (se = sd/sqrt n);
- money: c(b) = 100 x mean over picks of (sum of l_i in b)/36;
- money: dc(b) = c_A(b) - c_E0(b), with sum_b dc(b) = 100 x M_P(A) asserted;
- money: share(b) = c_A(b)/sum c_A, under C17.

C10 Time.
- UTC, with KST (+9 h) printed beside.
- dow = ((t // 86,400,000) + 3) % 7, Monday = 0.
- Weekend = Sat 00:00 <= t_sig < Mon 00:00 UTC (KST Sat 09:00 to Mon 09:00), unless the owners answer otherwise before O7.

C11 Seeds. data_x.seed_of('exitflex-extra', read id, pool, arm id[, part]).

C12 Units on the Korean pages.
- Growth levels and differences: '%/월' = 100(e^M - 1).
- Additive contributions: '%/월 기여(근사)' = 100 x the log part, with a footnote.
- Multiples: 'x'. ROE: % per trade. Wallet shares: '지갑 %'.
- Log values only in json. R only in appendices, with a one-line definition.
- Every live-size cell carries '파산 k/N' in the same cell.

C13 F11 marks. Every one-pick cell and every per-pick row marks F11.a = F3.a and F11.b = F3.b on F7_RF_ONLY picks (Known limit 11).

C14 DeepSeek committed layout. The pool name appears only in a heading. Shares print as k/n. No ds- id or 딥시크/DeepSeek word appears
on a line that holds a figure.

C15 Chance-cell line, computed under every split table:
- 'cells N, flagged 건수 적음 K, outside the chance range J, expected about 0.05 x N with no real difference';
- tables without a range print N and K only.

C16 Absolute beside difference. Every core choosable row prints its own monthly growth (%/월) beside 'E0 대비'. When its own growth
is <= 0, the sentence W12 is printed.

C17 Share rule. Shares of a total (sources of a gain, a coin's or bucket's share, top-month share) are printed only when
100 x |total| >= 0.1 (%/월) and every part lies within ±300%. Otherwise the amounts are printed with sentence W15.

## E.3 The reads

Index with tiers: see the table of section 2 of the design plan (A = the body of `EXTRA_READS_KO.md` in the order X-046, X-024, X-025, X-027, X-047, X-014, X-001, X-037; B and C = `EXTRA_READS_APPENDIX_KO.md`). Ids X-012 and X-040 are retired (X-040's choosable-row parts are X-037 (e) and (f)). Each read below carries its fields verbatim from the design plan's reads array (2026-10-12), which was written and reviewed before this file was committed and before any select-stage output existed.

### E.3.X-001 코인별 성적표

* **definition**: Per pool P, arm A, coin k in league order (C1), quarter size, select, closed trades of the pool's accounts (C6). Count columns (all 89 arms; body prints E0 + choosable): n_k; entries per account-month = entered_k/(N x 36); wins_k (pnl > 0) and losses_k = n_k - wins_k; win share; median hold_h and share > 8 h; exit-reason counts TP, SL, LOCK, RULE, LIQ, END; dN_k = n_k(A)/n_k(E0) - 1 ('-' when n_k(E0) = 0). Money (E0 + choosable, C3): c_k(A) = 100 x mean over the pool's picks of (sum of l_i over the pick's coin-k trades)/36 ('%/월 기여(근사)', C12); dc_k = c_k(A) - c_k(E0), with sum_k dc_k = 100 M_P(A) asserted to 1e-9. E0 (body): c_k(E0) and its share c_k/sum_j c_j (C17); per-coin drawdown: per account y_0 = 0, y_t = cumulative sum of l_i over its coin-k trades in exit order, DD_k = 1 - exp(-max_t(max_{s<=t} y_s - y_t)); median and max over picks (an account with < 30 coin-k trades is left out and counted). Choosable rows (body): n_up = #{k: dc_k > 0} of 6; k* = argmax_k dc_k (ties to league order); 'without the top coin' = M_P(A) - dc_k*/100, shown as %/월 (C12). Appendix: the dc_k grid; picks_up_k = #{p: c_{p,k}(A) > c_{p,k}(E0)} of N; mean x_i and mean R_i per coin; DD_k of choosable rows; year part c_{k,y} = mean over picks of (sum of l_i of coin-k trades with tr_exit in UTC year y)/12 for 2021-2023, dc_{k,y}, and the number of coins with dc_{k,y} > 0 in 3, 2, 1, 0 years. Printed note: A's and E0's trades on a coin differ (other entries become possible), so dc_k is an accounting split of M_P, not a cause. No best-trade column.
* **why_owner_cares**: 코인마다 몇 번 들어가 몇 번 이기고 졌는지, 지금 청산이 어느 코인에서 벌고 잃었는지, 새 청산의 이득이 여러 코인에서 나왔는지 한 코인 덕인지를 봅니다.
* **computed_from**: step-1 result files (tr_coin, tr_pnl, hold_h, tr_reason, tr_exit, w0, counts) and the C4 record (x_i, l_i, R_i)
* **new_code**: post-processing (xr_coin.coin_card)
* **cost**: low (seconds)
* **pool_handling**: Count columns committed for both pools (DeepSeek layout C14, calendar denominators). Money (c_k, shares, DD_k, dc_k, n_up, top coin, picks_up, x, R, year part): core E0 + choosable committed; DeepSeek only in ds_private/extra_reads_ds.json and owner_report_extra.md (part 핵심 for the body cells, part 부록 for the rest).
* **confirm_use**: none
* **min_sample**: a coin cell with < 100 closed trades is marked 건수 적음; picks_up prints N; DD_k leaves out accounts with < 30 coin-k trades and prints how many
* **shown_as**: 본문 표 '코인별 성적표'(풀마다): 행 = 지금 청산(E0)과 선택 가능 방식, 열 = BTC·ETH·SOL·DOGE·LTC·BCH, 칸 = '한 달 진입 · 승/패 · 승률 · 보유 중앙값(시간)'. E0 줄 아래 '이 코인 몫(%/월 기여) · 이 코인 거래만의 최대 하락'. 선택 가능 줄 끝 '좋아진 코인 n/6 · 가장 좋아진 코인을 빼면 E0 대비 ±x%/월'. dc 격자·연도별·청산 이유별은 부록, 89줄 건수는 CSV. 표 밑 C15 칸 수 줄과 경고 W3 '코인별 차이는 대부분 그 기간 그 코인의 가격 흐름 때문입니다(예: 2021년 상반기 도지 급등). 코인을 빼거나 골라 쓰는 규칙은 이 시험으로 정할 수 없고, 새 사전 등록이 필요합니다.' 승률 칸 옆 W14.

### E.3.X-002 코인 하나 빼고 다시 돌리면

* **definition**: E0 + choosable arms, quarter size, select. For each pick p, arm A in {E0, V} and coin k: re-run (C2) with offered mask off.coin != k. L_p^{-k}(A) = ln(max(w_end, 1e-12)/w0)/36. M_P^{-k}(V) = mean over picks of [L_p^{-k}(V) - L_p^{-k}(E0)]. Printed as %/월 (C12): M_P(V) (six coins) and M_P^{-k}(V) for k = 0..5; n_hold = #{k: M_P^{-k}(V) > 0} of 6; label '한 코인 의존' when M_P(V) > 0 and min_k M_P^{-k}(V) <= 0; picks_pos_k = #{p: L_p^{-k}(V) - L_p^{-k}(E0) > 0} of N; top row: E0's own level 100(e^{mean_p L_p^{-k}(E0)} - 1) beside 100(e^{mean_p L_p(E0)} - 1). Json only: crowd_k(A) = [mean_p L_p^{-k}(A) - mean_p L_p(A)] + c_k(A)/100 (positive: coin k's trades crowded out better trades of other coins). The mask removes trading in coin k, not its data (DeepSeek signals still read BTC's frame). No coin is chosen or dropped. Reduced outputs only (C2).
* **why_owner_cares**: 코인 하나가 없었어도 이 방식이 지금 청산보다 나았을지, 한 코인 운 덕이었는지 확인합니다.
* **computed_from**: re-runs of the pinned KX.simulate(market, pdata, A, 0.25, 'select', offered=masked); step-1 files for the six-coin values
* **new_code**: post-processing (xr_rerun.mask_offered; no kernel change)
* **cost**: medium: 6 runs ≈ 5 account-equivalents per pick-arm, ≈ 4,940 in all; 3-5 CPU-min at 0.03-0.06 s; fifth in the cap's drop order
* **pool_handling**: All money. Core E0 + choosable committed; DeepSeek only in the private extra report (part 부록); the committed DeepSeek page carries nothing from this read.
* **confirm_use**: none
* **min_sample**: the 'k 뺌' column is marked 건수 적음 when coin k has < 100 closed trades in that arm
* **shown_as**: 부록 표 '코인 하나 빼고 다시 돌리면': 행 = 선택 가능 방식(맨 위 E0 자신의 성장 %/월), 열 = '6코인 전체 / BTC 뺌 … BCH 뺌'의 'E0 대비 %/월', 끝 열 '빼도 남는 경우 n/6'과 '한 코인 의존' 표시. 경고 W3.

### E.3.X-003 코인끼리 같이 움직이나

* **definition**: (a) Prices, once per period, no arm: P_{k,d} = the close 'c' of coin k's last 1m minute with ts < 00:00 UTC of day d + 1, read from the select-cut file through data_x.open_cut (assert_no_minute_at_or_after on the loaded ts), d = 2021-01-01..2023-12-31; r_{k,d} = ln(P_{k,d}/P_{k,d-1}) for d = 2021-01-02..2023-12-31 (1,094 returns per coin); a day without a minute for a coin is left out of the pairs with that coin. Pearson 6 x 6 matrix; mean of the 15 off-diagonal values, also per UTC year; N_eff (Li-Ji) = sum over eigenvalues lambda of [1(lambda >= 1) + (lambda - floor(lambda))]; share of days on which all six returns have the same sign. (b) P&L streams per pool and arm (E0 + choosable): weeks start Monday 00:00 UTC, the first part-week (2021-01-01..03) merged into the first full week (156 blocks); u_{k,w} = mean over picks of the sum of l_i over coin-k trades with tr_exit in week w (0 when none); Pearson 6 x 6 across weeks; mean off-diagonal; N_eff. A coin with < 100 pooled closed trades or zero variance is left out (the number used is printed). Weeks without trades count as 0, which pulls correlations toward 0 (stated).
* **why_owner_cares**: 여섯 코인이 같이 오르내리면 코인을 여러 개 써도 사실상 한 가지에 거는 셈이라, 실제로 몇 개로 나뉘어 있는지 봅니다.
* **computed_from**: (a) the select-cut 1m files' ts and c; (b) step-1 result files (tr_coin, tr_exit) and C4 l_i
* **new_code**: post-processing (xr_coin.price_corr, stream_corr)
* **cost**: low (seconds)
* **pool_handling**: (a) is market data with no account: committed once, no pool. (b) is built from P&L: core E0 + choosable committed; DeepSeek private.
* **confirm_use**: none
* **min_sample**: (b) coins under 100 closed trades are left out and the number used is printed; (a) has 1,094 days, no flag
* **shown_as**: 부록: 6x6 '같이 움직이는 정도' 표(1에 가까울수록 같이 움직임)와 한 줄 '가격 기준 사실상 x개, 손익 흐름 기준 y개의 베팅'. 경고 W3.

### E.3.X-004 주말과 평일

* **definition**: Key wk = 1 when t_sig is in the weekend (C10), else 0. Per pool and arm, quarter size, select. Count columns (all 89 arms): n by wk; weekend share of trades beside the calendar share 2/7 = 28.6% and the weekend share of offered signals (identical for every arm, asserted); win share and median hold by wk. Money (E0 + choosable): lam(wk) = pooled mean of l_i per trade; G(wk) = 100 x mean over picks of (sum of l_i over trades in wk)/36, with G(0) + G(1) = G(all) asserted; 'weekend erased' = G(0) (static: it ignores freed slots, which X-005 measures, and the sizing path); weekend share of growth G(1)/G(all) under C17; dlam = lam(1) - lam(0). Chance range: weeks = Monday-00:00-UTC weeks of t_sig (157 bins, the part-weeks at both ends kept); per (week, wk) precompute S = sum of l_i and n = count; 2,000 resamples of weeks with replacement (numpy default_rng, seed C11); per draw lam(b) = sum S/sum n per bucket and dlam; range = 2.5th and 97.5th percentiles; draws with an empty bucket are dropped and counted; label '우연 가능' when the range contains 0. No p. Appendix: the same columns split, each on its own (never crossed), by side, pick bar, coin, UTC year and 장세 (tr_state).
* **why_owner_cares**: 주말에 한 매매가 거래와 성장에서 얼마를 차지하는지, 주말 매매를 지우면 월 성장이 어떻게 보이는지 봅니다.
* **computed_from**: step-1 result files and C4 (t_sig, l_i); the offered table for the signal share
* **new_code**: post-processing (xr_calendar.weekend_table)
* **cost**: low (seconds; week aggregates)
* **pool_handling**: Counts, win shares and holds committed for both pools (C14). lam, G, shares of growth and ranges: core E0 + choosable committed; DeepSeek private.
* **confirm_use**: none
* **min_sample**: cell (pool x arm x bucket [x split]) < 100 trades -> 건수 적음
* **shown_as**: 부록 표 '주말과 평일': 방식마다 '주말 매매 비율(달력 28.6% 옆) / 승률 주말·평일 / (코어 선택 가능 줄) 월 성장 기여 주말·평일 / 주말 거래를 지우면 월 성장 / 주말-평일 차이와 우연 범위'. 롱·숏, 봉, 코인, 해, 장세로 나눈 표는 그 아래. 표마다 C15 줄과 경고 W4 '요일·시간대·주말 규칙은 이 표로 정하지 않습니다. 정하려면 새 사전 등록이 필요하고, 이 표를 본 뒤에는 2021~2023년이 이미 본 기간이 됩니다.'

### E.3.X-005 주말 신규 진입 없는 계좌

* **definition**: E0 + choosable arms, each pick, quarter size, select: re-run (C2) with offered mask = (t_sig not in the weekend, C10): weekend signals are removed before the account starts. Positions opened on weekdays still run through the weekend: this is 'no new entries at the weekend', not 'flat on Friday night'. Rule checks read chart arrays, not the offered table, so opposite-signal rules still see weekend bars. Per pool and arm: trades entered (this account vs the full one); weekend trades removed; newly entered = trades whose (coin, side, fill) key is absent from the full account; dropped = full-account weekday trades absent here; win share and median hold. Money (E0 + choosable): d_own = mean over picks of [ln W_end(no-weekend) - ln W_end(full)]/36, shown as %/월 (C12); d_vs_E0 = the same of the no-weekend account of A against the full E0; D_m = mean over picks of [g_m(no-weekend) - g_m(full)], months with D_m > 0 (k of 36) and the 95% interval of mean D_m by metrics.block_bootstrap_ci(D, seed C11, n_boot 2000, block 3); free-slot effect = 100 d_own - (G(0) - G(all)) of X-004; median max drawdown at closes and busts k/N, both accounts.
* **why_owner_cares**: 주말에 새 매매를 안 하는 계좌가 실제로 더 나았을지, 그 빈자리에 다른 신호를 잡는 효과까지 넣어 다시 계산해 봅니다.
* **computed_from**: re-runs of the pinned KX.simulate with a weekday mask; step-1 full accounts; metrics.block_bootstrap_ci
* **new_code**: post-processing (xr_rerun.mask_offered; no kernel change)
* **cost**: low: ≈ 0.75 account-equivalent per pick-arm, ≈ 740 in all; under 1 CPU-min
* **pool_handling**: Reduced outputs under $WORK/<pin8>/extra/reduced/weekend/ (DeepSeek under ds_private/extra/reduced/weekend/). Counts (entered, removed, newly entered, dropped, win share, hold) committed for both pools. Money, interval and busts: core E0 + choosable committed; DeepSeek private.
* **confirm_use**: none
* **min_sample**: entered trades of the pool's no-weekend accounts < 100 -> 건수 적음; the interval is printed with the line that 36 months make it wide
* **shown_as**: 부록 표 '주말 신규 진입 없는 계좌': 방식마다 '지금 %/월 / 주말 신규 진입 없는 계좌 %/월 / 차이(범위) / 빠진 주말 거래 수 / 대신 새로 들어간 거래 수 / 빈자리 효과'. 굵은 글씨 '새 진입만 쉬는 경우이며 금요일 밤에 정리하는 경우가 아닙니다.' 경고 W4.

### E.3.X-006 주말을 타는 포지션

* **definition**: Hold interval [tr_fill, tr_exit] in ms UTC. Weekend time elapsed up to t: F(t) = w x 172,800,000 + max(0, r - 432,000,000), with w = floor((t - 345,600,000)/604,800,000) and r = (t - 345,600,000) - w x 604,800,000 (345,600,000 = Mon 1970-01-05 00:00 UTC). A trade's weekend overlap = F(tr_exit) - F(tr_fill). Per pool and arm, quarter size: (a) share of all hold hours inside the weekend = sum of overlaps/sum of holds, beside 28.6%; (b) carried in = trades with a weekday t_sig and overlap > 0: count, share of weekday-opened trades, win share; money G(carried in) as in X-004; (c) weekend-opened trades with tr_exit >= the next Monday 00:00 UTC: count and share of weekend-opened trades; (d) trades exiting in a weekend: count. An overlap of 0 means no weekend contact (an exit exactly at Sat 00:00 has overlap 0). G(carried in) is what those trades earned, not what a Friday-flat rule would give.
* **why_owner_cares**: 주말 신규 진입을 막아도 금요일에 들어간 포지션이 주말을 그대로 타는 비율이 얼마나 되는지 미리 압니다.
* **computed_from**: step-1 result files (tr_fill, tr_exit, tr_pnl) and C4 (t_sig, l_i)
* **new_code**: post-processing (xr_calendar.weekend_exposure)
* **cost**: low (seconds)
* **pool_handling**: (a), (c), (d) and the counts and win share of (b) committed for both pools (time and count class). G(carried in): core E0 + choosable committed; DeepSeek private.
* **confirm_use**: none
* **min_sample**: group (pool x arm x group) < 100 trades -> 건수 적음
* **shown_as**: 부록 표 '주말을 타는 포지션': '보유 시간 중 주말 비율 / 평일에 들어가 주말에 걸친 거래 비율 / 주말에 들어가 월요일까지 간 비율'; 문장 '주말 신규 금지만으로도 이만큼은 주말에 노출됩니다'. 경고 W4.

### E.3.X-007 시간대·요일·4시간 구간

* **definition**: Three bucket sets from t_sig (UTC; KST = +9 h printed beside): session Asia h in [0,8), Europe [8,16), US [16,24) with h = (t_sig // 3,600,000) % 24 (a close at 08:00:00 is Europe); weekday dow = ((t_sig // 86,400,000) + 3) % 7, Monday = 0; 4-hour block floor(h/4), 6 blocks. Per pool and arm, per bucket and side (all / long / short): n, share of trades, win share, median hold (count class); lam, G and dlam = lam(bucket) - lam(rest) with X-004's chance range (week aggregates; money). E0 only: session x weekend (6 cells: n and win share, no range). No other crossing and no 7 x 24 map. Printed note: 4h picks close only at 0/4/8/12/16/20 UTC, so their trades fill each block's first hour.
* **why_owner_cares**: 하루 중 어느 시간대, 어느 요일에 들어간 매매가 잘 풀렸는지 한국 시간으로 같이 보되, 우연으로도 생기는 차이와 구분해서 봅니다.
* **computed_from**: step-1 result files and C4 (t_sig, l_i)
* **new_code**: post-processing (xr_calendar.session_tables)
* **cost**: low (seconds)
* **pool_handling**: Counts, shares, win shares and holds committed for both pools. lam, G and ranges: core E0 + choosable committed; DeepSeek private.
* **confirm_use**: none
* **min_sample**: cell (pool x arm x bucket x side) < 100 trades -> 건수 적음 (DeepSeek by side and the E0 session x weekend cells are often flagged)
* **shown_as**: 부록 표 3개: 시간대(아시아·유럽·미국, 한국시간 병기), 요일 7칸, 4시간 구간 6칸. 칸 = '건수 / 승률 / 성장 기여 / 나머지와의 차이(우연 범위)'. 표마다 C15 줄 '이 표의 칸은 N개, 그중 건수 적음 K개입니다. 실력 차이가 전혀 없어도 약 M개 칸은 우연 범위를 벗어나 보이고, 실제로 벗어난 칸은 J개입니다.'와 경고 W4.

### E.3.X-008 장세별 성적표

* **definition**: Key = tr_state for trades and the 장세 code at i0 for offered signals (7): 추세장, 횡보장, 급변장, 보통, 모름. Per pool and arm, quarter size: the C9 columns per state, plus exit-reason shares (TP, SL, LOCK, RULE, LIQ, END) per state; for F12 rows comp_fired and comp_alone (as metrics.summarize) restricted to that state. Footer: sum over the five states of dc = 100 M_P(A) (asserted). Hold by state is not repeated (8.2 second table).
* **why_owner_cares**: 같은 청산이라도 어느 장세에서 벌고 어느 장세에서 잃는지, 새 청산이 어느 장세에서 이득을 봤는지 봅니다.
* **computed_from**: step-1 result files (tr_state, tr_reason, tr_comp, tr_pnl), C4 (R_i, l_i), C5 statuses, state codes at i0
* **new_code**: post-processing (xr_state.state_card)
* **cost**: low (seconds)
* **pool_handling**: Count class (n_off, n_ent, n_skip, n_rej, n, win, hold, exit shares, F12 component counts) committed for both pools. mean R, c, dc and share: core E0 + choosable committed; DeepSeek private.
* **confirm_use**: none
* **min_sample**: cell n < 100 -> 건수 적음; mean R always printed with ± se
* **shown_as**: 부록 표 '장세별 성적표': 행 = E0 + 선택 가능 방식, 칸(장세마다) = '건수 / 승률 / 평균 R(±) / 월 기여(E0 대비 ±)', 아래 '장세별 끝난 이유'(익절·손절·잠금·규칙·강제청산·기간 끝 %). C15 줄과 W1 꼬리표.

### E.3.X-009 비트코인 흐름별

* **definition**: BTC 4h bars are built from the select-cut BTC 1m arrays on UTC 4h boundaries: open = o of the first minute, high = max h, low = min l, close = c of the last minute; close ms = open ms + 14,400,000. Key btc of each offered signal: b = the last BTC 4h bar with close ms <= t_sig (searchsorted(close_ms, t_sig, 'right') - 1). From data_x.regime_arrays('BTCUSDT', '4h', high, low, close) take adx and slope (EMA50 slope over 10 bars in ATR units) with regime5y's constants: 오름세 = adx >= 25 and slope >= +0.5; 내림세 = adx >= 25 and slope <= -0.5; 횡보 = adx < 20; 애매 = otherwise; 모름 = NaN or no bar. No 급변 override. Per pool and arm: the C9 columns per bucket, plus side x btc (10 cells: n, win share; money mean R and c).
* **why_owner_cares**: 알트코인 매매도 비트코인이 오를 때 잘 되는지, 내릴 때 롱이 무너지는지 봅니다.
* **computed_from**: select-cut BTC 1m arrays (o, h, l, c, ts) aggregated to 4h; data_x.regime_arrays; C4; C5 statuses
* **new_code**: post-processing (xr_state.btc_state)
* **cost**: low (one regime call, cached)
* **pool_handling**: As X-008: count class committed for both pools; money core E0 + choosable committed, DeepSeek private.
* **confirm_use**: none
* **min_sample**: cell n < 100 -> 건수 적음 (side x BTC cells often)
* **shown_as**: 부록 표 '비트코인 흐름별': 오름세·내림세·횡보·애매·모름 5칸, 아래 롱/숏 줄, 칸 배치 X-008과 같음. 문장: 2021~2023에는 2021 상승장과 2022 하락장이 섞여 있어 칸 크기가 고르지 않습니다. C15 줄.

### E.3.X-010 변동성 3등분별

* **definition**: Key vol of an offered signal = data_x.regime_arrays(coin, pick tf, chart high, low, close)['vol_q'] at the signal bar i0 (off['i0']) of the signal's coin: the causal trailing-window ATR% quantile used by the 장세 label. Buckets: 작음 vol_q < 1/3; 중간 1/3 <= vol_q < 2/3; 큼 vol_q >= 2/3; 모름 NaN. Per pool and arm: the C9 columns per bucket, with n_rej and the SL share printed first. (off['close'] is the bar's close time in ms, not a price; no cut points are computed or printed.)
* **why_owner_cares**: 변동성이 클 때 손절이 더 자주 터지고 진입이 거절되는지, 청산 방식에 따라 그게 달라지는지 봅니다.
* **computed_from**: regime arrays of each coin and pick timeframe (already built for the 장세 label), offered i0, C4, C5 statuses
* **new_code**: post-processing (xr_state.vol_thirds)
* **cost**: low
* **pool_handling**: Count class committed for both pools; money core E0 + choosable committed, DeepSeek private.
* **confirm_use**: none
* **min_sample**: cell n < 100 -> 건수 적음
* **shown_as**: 부록 표 '변동성 3등분별': 작음·중간·큼·모름, 칸 배치 X-008과 같고 '거절 수'·'손절 비율'을 앞에. C15 줄.

### E.3.X-011 롱과 숏 따로

* **definition**: Key side (+1 롱, -1 숏). Per pool and arm: the C9 columns per side; side x 장세 (10 cells: n, win share; money mean R and c); side x coin (12 cells: n, win share, median hold; money c_{k,s} = 100 x mean over picks of (sum of l_i over trades with coin k and side s)/36, so c_{k,long} + c_{k,short} = c_k of X-001). Printed note: the select period holds the 2021 rise and the 2022 fall, so a long/short gap mostly follows the market's direction in those years.
* **why_owner_cares**: 롱에서 벌고 숏에서 잃는 건 아닌지, 새 청산이 어느 쪽에서 효과가 있었는지 봅니다.
* **computed_from**: step-1 result files (tr_side, tr_coin, tr_state) and C4
* **new_code**: post-processing (xr_state.side_card)
* **cost**: low
* **pool_handling**: Count class committed for both pools; money core E0 + choosable committed, DeepSeek private.
* **confirm_use**: none
* **min_sample**: cell n < 100 -> 건수 적음 (many of the 12 coin x side cells)
* **shown_as**: 부록 표 '롱·숏 따로': 롱/숏 두 묶음(칸 배치 X-008과 같음), 그 아래 롱/숏 x 장세, 롱/숏 x 코인 작은 표. C15 줄과 W1 꼬리표.

### E.3.X-013 들고 있는 동안 장세가 바뀐 비율

* **definition**: For each closed trade, x = the 장세 code of the last chart bar of the traded coin (pick timeframe) whose close is <= tr_exit: idx = searchsorted(bar close ms, tr_exit, 'right') - 1, the same causal rule as the entry label. Per pool, arm (E0 + choosable printed; all 89 in the CSV) and entry state b: n, the share with x == b ('유지'), the most frequent other x and its share. Entry state 모름 has its own row.
* **why_owner_cares**: 장세별 표가 '들어갈 때의 장세' 기준이라는 한계를 숫자로 보여 주고, 짧게 들면 그 기준이 더 믿을 만해지는지 봅니다.
* **computed_from**: step-1 result files (tr_exit, tr_state, tr_coin) and the regime codes of each coin's chart
* **new_code**: post-processing (xr_state.state_persist)
* **cost**: low
* **pool_handling**: Counts and shares only: committed for both pools.
* **confirm_use**: none
* **min_sample**: entry-state row with < 100 trades -> 건수 적음
* **shown_as**: 부록 표 '장세 유지율': 들어갈 때 장세마다 '끝날 때도 같은 장세였던 비율 / 가장 많이 바뀐 곳'. 한 줄로 알려진 한계 18을 가리킴.

### E.3.X-014 한 달 눈금: 월 배수 분포

* **definition**: Sample = alive pick-months (C6). x = e^{g_m}. Per pool and arm (E0 + choosable), quarter size, with live size in a second row: p10, p25, p50, p75, p90, min and max of x; shares x >= 1.1, >= 1.5, >= 2, >= 5, x < 1, x < 0.5; share of flat months (no exit, x = 1 exactly), shown separately but kept in the sample. Touch (realised wallet at exits): peak_m = max(1, max over exits t in month m of W(t)/W_{m-1}), W(t) = w0 + cumsum of tr_pnl in exit order; shares peak >= 1.5, 2, 5, 10. Each share prints k/n, the number of distinct calendar months holding a hit, and the largest single month's share of the hits ('-' at 0 hits). Month grid: per calendar month the pool average 100(e^{mean_p g_m} - 1)% in a 3 x 12 grid; months with mean_p g_m > 0 (k of 36); best and worst month; mean per year. Goal counts: (pick, month) cells with W_m/W_{m-1} >= 2, >= 5, <= 0.5. The live row carries busts k/N in the same cell (C12). A position held across a month end counts in the month it closes (Known limit 8).
* **why_owner_cares**: 평균 한 달 몇 %가 아니라 보통 달이 얼마인지, x2·x5가 나온 달이 있었는지, 그런 달이 몇 개 달에 몰렸는지를 목표(월 x5~x100)와 같은 눈금으로 봅니다.
* **computed_from**: step-1 result files (g, W, w0, w_end, tr_exit, tr_pnl) at quarter and live size
* **new_code**: post-processing (xr_goal.month_dist)
* **cost**: low (about 1 ms per account)
* **pool_handling**: All money. Core E0 + choosable committed; DeepSeek private (part 핵심).
* **confirm_use**: none
* **min_sample**: < 100 pick-months in a cell -> 건수 적음 (828 core, 540 DeepSeek before busts); a by-year cell < 100 pick-months -> 건수 적음
* **shown_as**: 본문 표 '한 달 눈금'(풀마다, E0 줄 먼저), 꼬리표 '맞춘 기간의 성적': '보통 달 x__ / 좋은 달(10번 중 1번) x__ / 가장 좋은 달 x__ / 손해 본 달 __% / x1.5 이상 __% / x2 이상 __% / x5 이상 __% / 달 중에 x5에 닿은 달 k/n(m개 달에 몰림) / 거래 없던 달 __%'. 아래 '1/1 크기' 줄은 같은 칸에 '파산 k/N'. 3x12 달력표는 부록. 문장 '겹치지 않는 독립 표본은 약 36달입니다.'와 W7 ''x5에 닿음'은 그 달 안에 한 번이라도 계좌가 5배 이상이 된 것이며, 달 끝에 5배라는 뜻이 아닙니다.'

### E.3.X-015 30일 눈금과 반토막·파산 닿음

* **definition**: (a) Windows start at each UTC midnight D_j = 2021-01-01 + j days, j = 0..1,065 (D_j + 30 d <= 2024-01-01; 1,066 windows), window (D_j, D_j + 30 d]. For every (account, window) whose start is not in a dead month (C6): R_j = W(D_j + 30 d)/W(D_j) and P_j = max(1, max over exits in the window of W(t)/W(D_j)), where W(t) = w0 + sum of tr_pnl with tr_exit <= t (idx = searchsorted(tr_exit, t, 'right'); W = w0 when idx = 0; P_j via np.maximum.reduceat, an empty segment gives 1). Per pool and arm (E0 + choosable), quarter size: p5, p10, p25, p50, p75, p90, p95 of R_j; shares R_j >= 1.1, 1.5, 2, 5, R_j < 1, < 0.5; touch shares P_j >= 2, 5, 10; worst and best R_j with the UTC start date (no pick named); shares as k/n plus the distinct start months with a hit plus the top month's share. (b) Half-wallet and bust touches for H = 30, 92 and 365 days: windows (D_j, D_j + H] with D_j + H <= 2024-01-01 (1,066; 1,004; 731); per (account, window) not starting in a dead month: half = 1 if the realised wallet at some exit in the window is <= 0.5 W(D_j); bust = 1 if an exit in the window leaves W < $10; shares at quarter and at live size. Realised wallet only (deeper with open positions: X-019). Fixed line: the overlapping windows are about 36 independent months.
* **why_owner_cares**: '한 달에 x5'가 달력 한 달이 아니라 아무 30일에서라도 있었는지, 가장 나빴던 30일이 얼마나 아팠는지, 1년 안에 계좌가 반토막 나거나 파산한 경우가 얼마나 되는지 봅니다.
* **computed_from**: step-1 result files (tr_exit, tr_pnl, w0, w_end, g) at quarter and live size
* **new_code**: post-processing (xr_goal.windows30, half_touch)
* **cost**: low (about 2-5 ms per account)
* **pool_handling**: All money. Core E0 + choosable committed; DeepSeek private (no worst-window value or date in any committed file).
* **confirm_use**: none
* **min_sample**: the pool's closed trades < 100 -> 건수 적음; fewer than 100 (account, window) pairs -> 건수 적음 (not expected)
* **shown_as**: 부록 표 '30일 눈금', 꼬리표 '맞춘 기간의 성적': '보통 30일 x__ / 좋은 30일 x__ / 나쁜 30일 x__ / 가장 나빴던 30일 x__(시작일) / 가장 좋았던 30일 x__(시작일) / 30일 뒤 x2 이상 __% / 30일 안에 x5에 닿은 비율 __%(m개 달에 몰림) / 30일 뒤 절반 이하 __%'. 그 아래 '반토막·파산 닿음': '30일·92일·365일 안에 지갑이 절반 이하로 내려간 적이 있는 경우 __% · 파산 __%'(1/4 크기, 1/1 크기). W7.

### E.3.X-016 목표까지 필요한 것

* **definition**: Per pool and arm (E0 + choosable), quarter size, over the pool's closed trades: x_i (C4), win = pnl > 0; w = win share; a = mean ln(1 + x_i) over wins; b = mean ln(1 + x_i) over losses (<= 0); n = entered trades per account-month = entered/(N x 36) (calendar, both pools); L = w a + (1 - w) b; model monthly log growth n L beside the actual pooled value. For each monthly target T in {1.10, 1.50, 2, 5, 100}, g* = ln T: needed win share p* = (g*/n - b)/(a - b) ('불가능' if > 1, '이미 넘음' if < 0; T = 1 printed too); needed entries per account-month n* = g*/L if L > 0, else '불가능: 거래당 평균이 0 이하', compared with X-025's entry ceiling per account-month ('신호가 모자람' when n* is larger); needed typical win e^{a*} - 1 with a* = (g*/n - (1 - w) b)/w, beside the actual e^a - 1; ceiling at 100% wins = e^{n a} per month. Appendix only, quarter size only (never live): months to goal from m_med = X-014's p50 and m_geo = e^{mean of g over alive pick-months}: for m > 1, ceil(ln 5/ln m) and ceil(ln 100/ln m) months; m <= 1 prints '도달 안 함'. Constant table (no data): 5^(1/N) and 100^(1/N) for N = 1, 3, 6, 12, 36.
* **why_owner_cares**: 한 달 +10%·+50%·x2·x5·x100이 되려면 승률이나 진입 횟수가 얼마여야 하는지를 지금 숫자와 나란히 보여 줘서, 목표까지의 거리를 바로 봅니다.
* **computed_from**: step-1 result files (tr_pnl, w0, counts), C4 x_i, X-014, X-025
* **new_code**: post-processing (xr_goal.goal_math)
* **cost**: none (arithmetic)
* **pool_handling**: Money-derived. Core E0 + choosable committed; DeepSeek private, except n and w on the committed DeepSeek page (calendar denominator). The constant table is committed once.
* **confirm_use**: none
* **min_sample**: fewer than 100 winners or fewer than 100 losers -> 건수 적음 on a, b and everything derived; n or w on < 100 trades -> 건수 적음
* **shown_as**: 첫 장(X-046)에는 x5 줄만: '한 달 x5에는 승률 __%(지금 __%) 또는 한 달 진입 __번(지금 __번, 최대 __번) 필요, 또는 불가능'. 부록 표 '목표까지 필요한 것', 꼬리표 '맞춘 기간의 성적': 행 = +10% / +50% / x2 / x5 / x100, 열 = '필요한 승률 / 필요한 한 달 진입 / 필요한 보통 이익 / 다 이겨도 한 달 최대 x__'. '몇 달이면' 칸은 같은 칸에 W6 ''몇 달이면 x5'는 2021~2023의 보통 달이 앞으로 똑같이 반복된다고 가정한 산수이며 예측이 아닙니다.'

### E.3.X-017 신의 손 상한 (실제로는 불가능한 숫자)

* **definition**: Per pick, quarter and live size (quarter in the summary), select. Uses E0's offered signals, fill minutes, hard stop (raw open - side x stop_atr x ATR14), quality_v1 sizing and costs; only the exit time is chosen with hindsight. Candidate exits of a position filled at minute e: (1) a market exit at the open of the check minute of every pick-timeframe close C0 + m x tf (m >= 1) after e (kernel_x's check-minute rule; a close beyond the data gives none), at taker fee + slippage, after which the account is free from that minute (busy-until = exit - 1 ms, as for a RULE exit); (2) the pick's own take-profit at its first touch (maker) or at a gap through it at an open, with holding past the touch also a candidate path. Every minute follows kernel_x's order (funding at the open, mark-open liquidation, stop gap, TP gap, check-minute exit; then the range: hard stop, mark liquidation, TP); a minute whose range touches the stop or the liquidation price gives no TP or limit candidate in that minute (stop first). Forced ends: hard stop (SL), liquidation, period-end close (END). For every exit other than (1), busy-until = the exit minute's ts. Horizons: (i) no later than that signal's own E0 exit (E0's standalone trade by KX.simulate_trade at equity 5,000); (ii) within 24 h of C0; (iii) within 48 h; (iv) no limit; (v) = (iv) plus a maker limit at the 1m high (long) or low (short) of any minute after e and before the forced end, except minutes excluded by the stop-first rule. Value of a candidate = ln(1 + delta/5,000), delta by the kernel's formulas with size from kernel._size at W_ref = $5,000 for every trade (no compounding; bracket limits at larger wallets ignored, which can only raise the ceiling). Account rule unchanged: when flat the account takes the next signal sizeable at W_ref; a non-sizeable signal is rejected and does not block; a signal whose fill is not after busy-until is skipped. Backward DP over the offered list: V[n] = 0; V[i] = V[i+1] if signal i has no fill or is not sizeable at W_ref, else V[i] = max over its candidates x of value(i, x) + V[first index j > i whose fill > busy-until(x)] (candidates sharing a next index are grouped). G* = V[0]; monthly multiple e^{G*/36}; pooled = mean over the pool's picks of G*/36. On the best path of (iv): trades, median hold, win share. Capture (json only): pooled [sum over the arm's own trades of ln(1 + pnl_i x qty_ref_i/qty_i/5,000)]/36 divided by pooled G*(iv)/36, qty_ref_i = kernel._size at 5,000 for that trade, only when G*(iv) > 0. Pre-registered drop (E.0.2): if the X-017 tests are not green at O8, X-017 is dropped by rule.
* **why_owner_cares**: 미래를 다 아는 사람이 같은 진입들을 가장 좋은 때에 청산해도 한 달 최대 몇 배인지를 보여 주므로, 청산만 바꿔서 한 달 x5가 애초에 가능한지 먼저 압니다.
* **computed_from**: PickData.offered, the select-cut 1m arrays (ts, o, h, l, mo, mh, ml, fund), kernel._size / _liq / _bracket / _entry_index, exit_of_pick(pick, E0), market.S(scale), KX.simulate_trade
* **new_code**: post-processing (numba path scan in kernel_x's step order plus a backward DP in xr_hind.py; no kernel change)
* **cost**: low: about 95 s CPU for all five horizons, 38 picks, 2 sizes (lens H on the real select cut; not re-timed)
* **pool_handling**: Core committed (pooled ceilings and best-path counts; capture in json only). DeepSeek: everything private, the best-path counts included (they come from a money optimisation).
* **confirm_use**: none
* **min_sample**: a pick with no sizeable signal has G* = 0 and still counts; a pooled best path under 100 trades -> 건수 적음
* **shown_as**: 부록 표 '신의 손 상한(실제로는 불가능한 숫자)', 꼬리표 '맞춘 기간의 성적': 한 달 최대 배수 ① 지금 청산보다 오래 들지 않을 때(E0 옆) ④ 시간 제한 없이; 한 줄로 ② 24시간 · ③ 48시간 · ⑤ 최고가에 팔 때; ④ 길의 거래 수·보유 중앙값·승률. 얻은 비율은 json만. 경고 W5 '미래를 다 아는 사람만 낼 수 있는 숫자입니다. 이 값이 크다고 청산을 바꾸면 그만큼 벌 수 있다는 뜻은 아니며, 실제 청산은 이 값의 작은 부분만 얻는 것이 정상입니다. 반대로 이 값이 x5보다 작으면, 이 진입들로는 청산만 바꿔서 한 달 x5가 안 된다는 뜻입니다.'

### E.3.X-018 버티기: 낙폭·본전 아래 기간·연속 손실

* **definition**: Per pool and arm (E0 + choosable), quarter size (live beside). (a) Basket: B(t) = mean over the pool's accounts of W_a(t)/w0 at every exit time of any account (separate wallets, no transfers; a dead account stays at its last wallet); max drawdown of B (start 1.0 is the first peak) with peak, trough and recovery dates (first t after the trough with B >= the peak) or '미회복'; the longest stretch below a previous peak in days with dates ('진행 중' if open at the period end, counted to the end); final B; worst UTC month of B; share of months in which B fell. (b) Single account: the stored max_dd and the longest under-water stretch (days) per account; p50, p90 and max over the pool's picks (no pick named, no date); busted accounts k of N (w_end < $10); E0's quarter max_dd median is printed as 'select.json과 같음' (read, not recomputed). (c) Loss streaks: per account the longest run of consecutive closed trades with pnl <= 0 in exit order; p50 and max over picks; share of the pool's trades in runs of 5 or more; number of runs >= 8; median over picks of longest/L_exp with L_exp = ln(n(1 - q))/ln(1/q), q = the pick's loss share ('-' when q >= 1 or n(1 - q) <= 1). (d) Picks together: Pearson correlation of monthly g between every pair of picks (36 values); mean rho; N_eff = N/(1 + (N - 1) rho) (flag if rho <= -1/(N - 1)).
* **why_owner_cares**: x5를 노리다 얼마나 깊게 빠지는지, 본전 회복에 몇 주가 걸리는지, 몇 번 연속으로 지는지가 20~50배에서 버틸 수 있는지를 정합니다.
* **computed_from**: step-1 result files (tr_exit, tr_pnl, w0, w_end, max_dd, g); select.json for the reference value
* **new_code**: post-processing (xr_goal.endurance)
* **cost**: low (under 1 CPU-minute)
* **pool_handling**: All money or money-derived ((c) conservative, C8). Core E0 + choosable committed; DeepSeek private.
* **confirm_use**: none
* **min_sample**: streak cells on < 100 trades -> 건수 적음; a basket of fewer than 5 accounts is not formed (not expected)
* **shown_as**: 부록 표 '버티기', 꼬리표 '맞춘 기간의 성적': '가장 깊은 하락 __% (고점 날짜 → 바닥 날짜 → 회복 날짜 또는 아직 못 되찾음) / 가장 오래 본전 아래 __일 / 계좌 하나로 보면 하락 보통 __%·나쁜 경우 __%·최악 __% / 파산 계좌 k/N / 연속으로 진 횟수 보통 __·최대 __ / 매매법들이 사실상 몇 개의 독립 베팅인가'. 문장 '닫힌 거래 기준이라 들고 있는 동안의 흔들림은 빠져 있습니다(X-019 참고).' W9(1/1 크기 칸).

### E.3.X-019 들고 있는 동안의 최대 하락 (평가손 포함, 범위)

* **definition**: Per account (E0 + choosable), quarter and live size. Inside trade i the equity lies between U_i = Wb_i + margin_i x max(-1, worst_ROE_i) and Wb_i + margin_i x best_ROE_i (C4 excursions, funding not included). H_{i-1} = max(w0, Wb_1, ..., Wb_i) (realised highs before or at the entry of trade i). MDD_low = max over i of 1 - U_i/H_{i-1}. MDD_high = max over i of 1 - U_i/max(H_{i-1}, Wb_i + margin_i x best_ROE_i) (the order of best and worst inside a trade is unknown, so the trade's own best may be a peak). Worst single-position dip = max over i of (Wb_i - U_i)/Wb_i in % with its UTC date. Pool: median over picks of each, beside the closed-trade max_dd.
* **why_owner_cares**: 닫힌 거래 기준 낙폭은 들고 있는 동안 평가손으로 얼마나 내려갔는지를 가리므로, 20~50배에서 실제로 겪을 하락을 범위로 보여 줍니다.
* **computed_from**: C4 record (Wb_i, margin_i, best_ROE_i, worst_ROE_i) and the stored max_dd
* **new_code**: post-processing (uses the C4 1m scan)
* **cost**: low (seconds on top of the scan)
* **pool_handling**: Drawdown is money. Core E0 + choosable committed; DeepSeek private.
* **confirm_use**: none
* **min_sample**: account with < 100 trades -> 건수 적음
* **shown_as**: 부록 한 줄(방식마다), 꼬리표 '맞춘 기간의 성적': '최대 하락: 닫힌 거래 기준 __% · 들고 있는 동안 포함 __%~__% · 한 포지션이 가장 깊이 내려간 때 -__% (날짜)'.

### E.3.X-020 진 거래가 몰린 날

* **definition**: Per pool and arm (E0 + choosable), quarter size. Day = UTC calendar day of tr_exit; loss exit = closed trade with pnl < 0. (i) L_d = distinct picks with at least one loss exit on day d; C_d = distinct coins among them; report the days with L_d >= 3 (and those with C_d >= 2 too): count, share of all loss exits falling on them, max L_d. (ii) Clustering ratio = observed days with L_d >= 3 / expected, expected = 1,095 x P(PoissonBinomial(pi_1, ..., pi_N) >= 3), pi_p = share of the period's days with a loss exit of pick p; above 1 means losses come together. (iii) Per account: the max-drawdown window of the realised wallet at exits (peak to trough); the share of its log drop carried by its 5 most negative UTC days (daily log change of the realised wallet; 1.0 when fewer than 5 negative days) and by the worst day; pool = median over picks.
* **why_owner_cares**: 여러 매매법이 같은 날 함께 지면 계좌가 한 번에 크게 빠지므로, 그런 날이 얼마나 되고 낙폭의 얼마를 최악의 며칠이 만드는지 봅니다.
* **computed_from**: step-1 result files (tr_exit, tr_pnl, tr_coin, w0)
* **new_code**: post-processing (xr_goal.loss_days)
* **cost**: low
* **pool_handling**: (i) and (ii) are counts of losing trades (win-share class): committed for both pools, DeepSeek in the C14 layout. (iii) is money: core E0 + choosable committed, DeepSeek private.
* **confirm_use**: none
* **min_sample**: fewer than 30 loss days in a pool -> 건수 적음; (iii) account with < 100 trades -> 건수 적음
* **shown_as**: 부록 묶음 '진 거래가 몰린 날': '하루에 3개 이상 매매법이 진 거래로 끝난 날 __일 (서로 상관없다면 __일), 그 날들이 전체 진 거래의 __%, 최대 낙폭의 __%가 최악의 5일'. 딥시크 쪽은 건수만 k/n으로(C14).

### E.3.X-021 동시에 몇 개 열려 있나 (한 계좌로 합치면)

* **definition**: Per pool and arm (all 89 for counts; E0 + choosable printed), quarter and live size. Grid t_g = 2021-01-01 00:00 UTC + g x 900,000 ms while t_g < 2024-01-01 (105,120 points). Account p is in position at t_g iff a trade has tr_fill <= t_g < tr_exit (idx = searchsorted(tr_fill, t_g, 'right') - 1, then t_g < tr_exit[idx]); it then holds (tr_coin, tr_side). m_g = accounts in position. Report: share of points with m_g >= 1; mean, p90 and max of m_g; shares with m_g >= 3, 5, 10; mean of (distinct (coin, side) pairs)/m_g and of (largest (coin, side) group)/m_g over points with m_g >= 1; per coin the share of in-market points with >= 2 accounts on that coin; the largest number of accounts in one (coin, side) at once and the UTC date of its first point. One shared wallet (E0 + choosable, live size): m(t_g) = sum over open trades of margin_i/Wb_i (C4); p50, p90, max and the share of points with m > 100% (impossible in one real account). The league's accounts are separate wallets; this only shows what one real account could not do.
* **why_owner_cares**: 리그는 매매법마다 지갑이 따로지만, 진짜 계좌 하나로 돌리면 여러 포지션의 증거금을 동시에 못 대므로 몇 개가 한꺼번에 같은 코인·같은 방향에 열리는지 알아야 합니다.
* **computed_from**: step-1 result files (tr_coin, tr_side, tr_fill, tr_exit) and C4 margin_i/Wb_i
* **new_code**: post-processing (vectorised searchsorted per pick)
* **cost**: low (seconds)
* **pool_handling**: Time shares and counts of positions (time class) committed for both pools (C14). The one-wallet margin part: core committed; DeepSeek private (margin share is wallet-dependent, C8).
* **confirm_use**: none
* **min_sample**: a per-coin cell with < 100 in-position points -> 건수 적음
* **shown_as**: 부록 묶음 '동시 보유': '평소 __개 / 많을 때(90%) __개 / 최대 __개 동시에 열림, 시간의 __%가 포지션 중, 서로 다른 베팅 비율 __%, 같은 코인에 2개 이상 겹친 시간 __%, 가장 많이 겹친 날'. 코어만: '한 계좌로 합치면 증거금이 지갑의 평소 __%·최대 __%, 시간의 __%는 100% 초과'. W13 '숫자는 매매법마다 따로 5,000달러 지갑으로 돌린 결과입니다. 1,000달러 한 계좌로 여러 매매법을 같이 돌리면 증거금이 모자라 같은 결과가 나오지 않습니다.'

### E.3.X-022 베팅 크기·레버리지를 바꾸면

* **definition**: E0 + choosable arms, each pick, select. Settings: scales 0.5 and 2.0 via market.S(scale) (sizing.size_vector: the four margin fractions times the scale, capped at 0.98, leverages unchanged), beside the step-1 files at 0.25 and 1.0 (the 1.0 row of core choosable rows prints 'select.json과 같음' where select.json already holds the value); fixed leverage L in {20, 30, 40} at scale 0.25: S_L = a copy of market.S(0.25) with S[11], S[13], S[15], S[17] = min(0.98, L/100 x 0.25) and S[12], S[14], S[16], S[18] = L (a test asserts that writing the base values back reproduces market.S(0.25)). Re-run (C2) with S = setting. Per pool, arm and setting, in this column order: busted picks k of N; LIQ exits; entered; rejected (status 2); X-014's p50, p90 and shares >= x1.5, x2, x5; median over picks of the final multiple w_end/w0 and of ln(w_end/w0)/36 as %/월. No value between grid points is claimed. Information only: the study's size stays quarter (4) and leverages stay quality_v1 (12).
* **why_owner_cares**: 한 번에 얼마를 거느냐와 레버리지가 성장 속도와 파산 위험을 가장 크게 좌우하므로, 크기와 레버리지를 바꾸면 파산·강제청산·못 들어간 신호가 얼마나 달라지는지 같은 표에서 봅니다.
* **computed_from**: re-runs of the pinned KX.simulate with a settings vector S; step-1 files for 0.25 and 1.0
* **new_code**: post-processing (xr_rerun.S_variant; no kernel change)
* **cost**: medium: 5 runs per pick-arm, ≈ 4,940 account-equivalents; the fixed-leverage part is first and the whole read last in the cap's drop order
* **pool_handling**: Entered, rejected and LIQ counts committed for both pools; growth, multiples and busts: core E0 + choosable committed, DeepSeek private.
* **confirm_use**: none
* **min_sample**: a cell on < 100 trades or < 100 pick-months -> 건수 적음
* **shown_as**: 부록 표 '크기·레버리지를 바꾸면', 꼬리표 '맞춘 기간의 성적': 행 = 1/4배(지금), 1/2배, 1배, 2배, 20배 고정, 30배 고정, 40배 고정; 열 = '파산 k/N / 강제청산 횟수 / 진입 / 못 들어간 신호 / 보통 달 x__ / 좋은 달 x__ / x2 이상 달 __% / 최종 배수 중앙값 / 한 달 성장 %/월'. 표 밑 W9 '크게 걸면 좋은 달도 커지지만 파산도 함께 늘어납니다. 1/1 크기 숫자는 항상 옆의 파산 수와 같이 읽어 주세요. 연구와 리그는 1/4 크기로 판정하며, 이 표로 실제 돈의 크기를 정하지 않습니다.'

### E.3.X-023 2021~2023 참고 범위 (판정 기준 아님)

* **definition**: Fresh-start windows like a league restart: starts s = every Monday 00:00 UTC from 2021-01-04 with s + 92 d <= 2024-01-01 (143 starts). Per pick and arm (E0 + choosable), quarter size (core live beside): a $5,000 account at s, offered only the signals whose fill minute is in [s, s + 92 d) (C2 mask), positions running on to their own exit or END. Marked wallet at T (T = s + 30 d and s + 92 d; X-044 also uses the weekly marks s + 7w): realised wallet after trades with tr_exit <= T, plus a position open at T valued as 11.4 item 11: X = the close 'c' of the held coin's last 1m minute with ts < T (from the cut file) moved by the market exit's slippage, X' = X(1 - side S[1]); mark = Wb + side x qty x (X' - fill) - qty x fill x S[0] - qty x X' x S[0] - funding paid over the minutes (e, last minute before T], with qty, margin and lev from C4's rebuild at the window wallet. Every mark minute is < 2024-01-01. Per window and pool: G_D = mean over picks of ln(W_D/5,000)/(D/30.4375) for D = 30 and 92; trades entered per account; win share of closed trades. Report per pool and row the 5th, 25th, 50th, 75th and 95th percentiles over windows of G_D (as %/월), entered and win share; V - E0 differences go to json only. No per-pick band is stored or shown.
* **why_owner_cares**: 리그를 새로 시작한 뒤 30일·92일에 계좌가 2021~2023 기준으로 어느 범위였는지를 참고로 보여 주되, 리그 판정은 계약의 점검만 한다는 점을 같이 적습니다.
* **computed_from**: re-runs of KX.simulate with a time-window mask; the select-cut c, o, mo and fund arrays for the mark; C4
* **new_code**: post-processing (xr_rerun.window_runs; no kernel change)
* **cost**: medium: 143 windows per pick-arm, ≈ 0.084 account-equivalent each, ≈ 11,900 in all (shared with X-044); every second Monday (72 starts) is fourth in the cap's drop order
* **pool_handling**: Core committed (E0 + choosable). DeepSeek: G percentiles private; entered and win-share percentiles committed.
* **confirm_use**: none (select-period bands only, 16.7 item 4; the league's own drift bands are separate)
* **min_sample**: a D with < 100 windows -> 건수 적음 (143 windows; 72 if the cap drops)
* **shown_as**: 부록 표 '2021~2023 참고 범위 (판정 기준 아님)', 꼬리표 '맞춘 기간의 성적': 행 = 30일·92일, 열 = '나쁜 쪽 5% / 25% / 가운데 / 75% / 좋은 쪽 5%'(그 기간 %/월), 계좌당 진입 가운데, 승률 가운데. 가운데를 '예상'이라 부르지 않음. 경고 W10 '이 범위는 성적을 맞춘 2021~2023에서 만든 참고 범위라 실제보다 좋게 나왔을 수 있습니다. 리그에서 아무것도 결정하지 않으며, 결정은 계약 11.5의 30일(C1)·61일(C2) 점검만 합니다.'

### E.3.X-024 봉 종류별 (단타 15분·30분 묶음 먼저)

* **definition**: Cells per pool: 단타 = 15m + 30m picks pooled (core 11, DeepSeek 2), then 15m (4/1), 30m (7/1), 1h (6/6), 4h (6/7), then 1h + 4h (12/13); a pick's bar = its tf in candidates.json. Count columns (all 89 arms; quarter size, live beside), over the closed trades of the cell's pick accounts: picks n; entered (status 1) and its change in % against E0 of the same cell; entries per account-month = entered/(picks x 36); skipped while holding with E0's beside; median hold_h and the shares > 4 h, 8 h, 18 h; win share; exit-reason shares TP, SL, LOCK, RULE, LIQ, END; entries at a rule-exit minute. Money (E0 + choosable): M_cell = mean over the cell's picks of M_p (7), shown as %/월 (C12); picks improved = #{cell picks with M_p > 0} of n (M_p = 0 is not improved, 8.1); months better = #{months with D_m^cell > 0} of 36, D_m^cell = mean over cell picks of g_m(V) - g_m(E0); contribution (n_cell/N_pool) x M_cell for 15m/30m/1h/4h, summing to M_P (asserted), shown under C17; E0 per cell: own growth %/월 (C16) and median final multiple. Appendix: coin x bar group (단타 / 1h + 4h), counts only. q15 variants equal their base on 15m and 30m picks (5.1) and are marked so; one-pick cells carry the C13 marks.
* **why_owner_cares**: 두 분이 원하는 단타(15분·30분) 매매법에서 새 청산이 보유 시간과 진입 횟수를 실제로 바꾸는지, 성장이 단타 쪽에서 나오는지 1시간·4시간 쪽에서 나오는지 맨 먼저 확인합니다.
* **computed_from**: step-1 result files (hold_h, counts, reasons, g, w_end, w0) through the pool-summary formulas called per cell; pick bars from candidates.json
* **new_code**: post-processing (xr_mech.tf_cells)
* **cost**: low (seconds)
* **pool_handling**: Count columns committed for both pools (DeepSeek 15m and 30m cells are one pick each, marked 픽 1개, C13 marks, C14 layout). Money: core E0 + choosable committed (each core pick's M_p on choosable rows is already committed as Mp, so a one-pick cell shows nothing new); DeepSeek private (part 핵심).
* **confirm_use**: none
* **min_sample**: cell < 100 closed trades -> 건수 적음; cell < 3 picks -> 픽 N개 (both shown)
* **shown_as**: 본문 표(풀마다, 보유·진입 먼저): 행 = E0 + 선택 가능 방식, 열 묶음 = 단타(15분+30분) / 15분 / 30분 / 1시간 / 4시간, 칸 = '픽 수 · 진입(E0 대비 %) · 보유 중앙값(시간) · 8시간 넘는 비율 · 승률', 코어 선택 가능 줄은 '좋아진 픽 3/4 · E0 대비 +__%/월 · 36달 중 __달 더 좋음'. 읽는 법 한 줄. 문장 '봉마다 규칙을 따로 고르지 않습니다.'와 W21 '픽끼리 같은 코인을 거래하므로 3/4 같은 숫자는 설명이지 증거가 아닙니다.'

### E.3.X-025 신호는 어디로 갔나 (놓친 신호와 최대 진입 수)

* **definition**: From the C5 statuses (all 89 arms, both sizes; quarter decides, live beside), summed over the pool's picks. (a) offered; (b) rejected by the size rule (status 2); (c) skipped while holding (status 0), split into (c1) sizeable: kernel._size(S, brs[coin], W, side, fill, stop, ATR14, best, qty_step, min_notional) ok, with W = the account's realised wallet just before the fill (every trade with exit before the fill minute, plus a RULE or RAND exit at that same minute), fill = o[e](1 + side S[1]), stop = o[e] - side x stop_atr x ATR14; and (c2) not sizeable; (d) entered; (e) no fill (status 3) and after bust (status 4). Identity per account: (a) = (b) + (c) + (d) + (e), else the stage stops. (f) Entry ceiling (per pool and size, from E0's account): walk the offered list; count a signal that is sizeable at E0's realised wallet and fills after busy-until; then busy-until = (the ts of the minute kernel._entry_index(ts, C0 + tf), at least e + 1) - 1 ms (the period-end minute when beyond the data): the most entries any bar-close rule can make; a second number with C0 + 15 min (q15 on 1h/4h picks). (g) Time in market = sum of (tr_exit - tr_fill)/(picks x 1,095 days). Rates per account-month on the calendar denominator picks x 36: offered, entered, skipped, rejected; entries per pick-month p10, p50, p90 and the share of pick-months with 0 entries; capacity = 720 h/mean hold h; take rate = entered/offered. Blockers: for each skipped signal q the blocker is the entered trade with the greatest tr_fill <= fill_q; B[a][b] = skipped signals of coin a whose blocker is on coin b (6 x 6, sum = skipped asserted); same-coin share = trace(B)/sum(B); median blocker age (fill_q - blocker fill)/3.6e6 h; blocker state at fill_q: 'same minute' if the blocker's fill == fill_q, else the sign of side_b x (open of the blocker's coin at the first minute >= fill_q - blocker fill price): 수익 중 / 손실 중 / 본전. Appendix: (a)-(d) split by signal coin, pick bar and 장세 of the offered signal.
* **why_owner_cares**: '오래 들고 있어서 진입을 놓친다'는 생각을 숫자로 확인합니다: 놓친 신호 중 실제로 탈 수 있었던 것이 몇 번인지, 어떤 청산으로도 최대 몇 번까지 탈 수 있는지, 어느 코인이 자리를 막았는지.
* **computed_from**: C5 statuses (rebuilt from step-1 tr_* arrays and the offered table, audited by real re-runs of E0 and F12.a); PickData.offered; select-cut opens; kernel._size, kernel._entry_index, exit_of_pick
* **new_code**: post-processing (xr_common.rebuild_status, xr_mech.funnel; no kernel change)
* **cost**: low: the rebuild takes seconds per account; the audit re-run is 152 accounts
* **pool_handling**: Core: everything committed (all 89 rows in the CSV). DeepSeek committed: (a), (b), (c) total, (d), (g), the calendar rates of (a)-(d), capacity, take rate, the blocker matrix, same-coin share, blocker age and the coin/bar/장세 splits of these. DeepSeek private (wallet-dependent or bust-revealing, C8): (c1)/(c2), (e), (f), the pick-month quantiles and zero-month share, and the blocker profit state.
* **confirm_use**: none
* **min_sample**: a pool x arm cell with < 100 entered trades -> 건수 적음; coin, bar or 장세 cells with < 100 offered signals -> 건수 적음; a blocker row with < 100 skipped -> 건수 적음
* **shown_as**: 본문 표 '신호는 어디로 갔나'(E0 줄 먼저, 그다음 방식 순서): '나온 신호 / 크기 규칙에 걸려 못 탄 신호 / 들고 있어서 놓친 신호(코어: 그중 실제로 탈 수 있었던 것) / 탄 신호 / (코어) 어떤 청산으로도 최대로 탈 수 있었던 수 / 포지션을 들고 있던 시간 비율 / 한 달 진입'. E0 밑 한 줄(코어) '들고 있어서 놓친 A개 중 실제로 탈 수 있었던 것은 B개'. 읽는 법 한 줄. 6x6 '자리를 막은 코인' 표와 코인·봉·장세별 표는 부록. 딥시크 쪽은 C14 배치.

### E.3.X-026 놓친 신호는 좋은 신호였나

* **definition**: Per pool and arm (E0 + choosable), quarter size. M = the arm's skipped-while-holding signals that were sizeable (X-025 c1). For each q in M run its standalone trade under the same arm at that account's wallet W of X-025: KX.simulate_trade(market, pdata, arm, offered, q, 0.25, 'select', equity=W, tp_price=pdata.targets(offered)[q] when the arm is F11.b or F12.b, else NaN); r_q = (wallet change)/W, hold = exit - fill. For the entered trades r = x_i (C4). For M and for the entered trades: count, win share (r > 0), mean ln(1 + r), median hold h; and the difference of mean ln(1 + r) (missed - entered). The standalone trades overlap the trade that was open, so they cannot all be had together: this measures the quality of what was missed, not an achievable account.
* **why_owner_cares**: 들고 있어서 놓친 신호가 실제로 탄 신호보다 좋았는지 나빴는지 직접 보여 줘서, 빨리 나와 더 타는 게 이득인지 판단을 돕습니다.
* **computed_from**: X-025 sizeable flags and wallets; KX.simulate_trade with tp_price for F11.b/F12.b; C4
* **new_code**: post-processing (xr_mech.missed_quality)
* **cost**: low: 0.02-0.04 ms per standalone trade (synthetic benchmark); about 1 CPU-min
* **pool_handling**: Core E0 + choosable committed (counts, win shares, holds and means). DeepSeek: entirely private (M is defined through the wallet-dependent sizeable flag, C8).
* **confirm_use**: none
* **min_sample**: M or the entered set < 100 trades -> 건수 적음
* **shown_as**: 부록 표 '놓친 신호 vs 탄 신호': '건수 / 이긴 비율 / 한 번 평균(지갑 대비 %) / 보유 중앙값'; 한 줄 '놓친 신호를 혼자 탔다면의 성적이며, 동시에 다 탈 수는 없습니다'.

### E.3.X-027 이긴 이유 나누기 (청산을 잘해서인가, 진입이 달라져서인가)

* **definition**: Per pool and arm V against E0, quarter size, per pick. Entry key = (tr_coin, tr_side, tr_fill), unique per account (asserted). Part 1 (all 89 arms, counts): SAME = V trades whose key is an E0 key with equal tr_exit and tr_reason; EXIT = key in E0 but exit minute or reason differs; NEW = key not in E0; DROP = E0 trades whose key is not a V key; summed over picks; shares SAME/n_V, EXIT/n_V, NEW/n_V, DROP/n_E0 (EXIT + NEW = the contract's 'trades changed', asserted). Part 2 (E0 + choosable, money, C4 l_i): T_new = sum of l(V) over NEW; T_exit = sum over EXIT pairs of [l(V) - l(E0 matched)]; T_same = sum over SAME pairs of [l(V) - l(E0 matched)] (identical trade, different wallet: a size residual); T_drop = - sum of l(E0) over DROP; T_new + T_exit + T_same + T_drop = 36 x M_p exactly (asserted to 1e-9); pool values = mean over picks/36, printed as '%/월 기여(근사)' (C12) and, under C17, as % of M_P (adding to 100; negatives allowed). Part 3 (E0 + choosable): early exits = V trades with reason RULE (and LOCK for F13) matched by key to an E0 trade: count, matched, unmatched; for matched pairs dR = R_i(V) - R_i(E0): shares > 0, = 0 (|dR| < 1e-9), < 0; mean dR among better, among worse and overall; the mix of the E0 twin's reasons (TP, SL, LOCK, END, LIQ); median hold of V vs the E0 twin. Part 3 ignores the entries the earlier exit freed (Part 2 counts them).
* **why_owner_cares**: 새 청산이 이겼다면 '같은 매매를 더 잘 끝내서'인지 '빨리 비워서 더 탄 매매 덕분'인지 나눠 보여 주므로, 두 분 생각(빨리 나오면 더 탄다)이 실제로 돈이 됐는지 봅니다.
* **computed_from**: step-1 result files of V and E0 (tr_coin, tr_side, tr_fill, tr_exit, tr_reason, tr_pnl, w0) and C4 R_i
* **new_code**: post-processing (xr_mech.growth_sources)
* **cost**: low (1-2 CPU-min of set operations)
* **pool_handling**: Part 1 committed for both pools on all 89 rows; Part 3 count and matched count committed for both pools. Part 2 and the Part 3 sign shares and means: core E0 + choosable committed; DeepSeek private (part 핵심 for Part 2).
* **confirm_use**: none
* **min_sample**: row with n_V < 100 -> 건수 적음, and Part 2 is not printed below 100; a Part 2 part resting on < 100 trades -> 건수 적음; Part 3 with < 100 matched pairs -> 건수 적음
* **shown_as**: 본문 표 '무엇이 성장을 만들었나': 모든 줄 '같은 거래 __% · 같은 진입 다른 청산 __% · 새 진입 __% · 지금 방식 진입 중 빠진 것 __%'; 선택 가능 줄 아래 '이득의 출처: 새 진입 +__ · 청산 방법만 바뀐 곳 +__ · 빠진 진입 -__ · 크기 차이 +__ (%/월 기여, C17이면 합 100% 비율)'과 '일찍 나온 __건 중 같은 진입의 E0보다 나았던 건 __%'. 읽는 법 한 줄. 비율을 못 쓰는 줄은 W15 '이득이 작아(한 달 0.1% 미만) 나눈 비율은 표시하지 않고 금액만 적었습니다.' 절대 성장 0 이하 줄은 W12.

### E.3.X-028 어떻게 끝났나: 청산 이유 표

* **definition**: Per pool, arm and (appendix) coin, quarter size, closed trades. For each reason r in SL (hard stop, no lock raised), LOCK, TP, RULE, LIQ, END: n_r and share_r = n_r/n (shares sum to 1). The pooled counts equal select.json's 'reasons' (asserted) and that row is printed as 'select.json과 같음'; new: shares in Korean, the coin split, RULE labelled with the family's Korean name (구조 무너짐, 이동평균 이탈, 반대 신호, 고점 대비 되돌림, 수익 반납, 시간 제한, 멈춤, 매매법 자체 청산; F12 keeps its component table). Money (E0 + choosable): mean R_i per reason; share of SL trades with R < -1.25 (gap or overshoot); share of RULE trades with R >= 0; mean R of RULE trades with R < 0, beside -1R of the hard stop. RAND does not occur in real arms (asserted 0). A reason with n_r = 0 prints 0 and '-'.
* **why_owner_cares**: 새 청산이 손절·익절로 끝나는지 규칙으로 먼저 나오는지, 규칙으로 나오면 평균 얼마를 건졌는지 한눈에 봅니다.
* **computed_from**: step-1 result files (tr_reason, tr_coin), select.json reasons, C4 R_i
* **new_code**: post-processing (xr_mech.reason_table)
* **cost**: low
* **pool_handling**: Counts and shares committed for both pools (all 89 in the CSV). R-based columns: core E0 + choosable committed; DeepSeek private.
* **confirm_use**: none
* **min_sample**: cell n < 100 -> 건수 적음; a mean on < 20 trades of that reason is also 건수 적음
* **shown_as**: 부록 표 '청산 이유 표': 줄 = E0 + 선택 가능 방식, 칸 = 손절 / 계단 잠금 / 익절 / 규칙 청산 / 강제청산 / 기간 끝 각각 '비율과 평균 R', 오른쪽 '손절이 -1.25R보다 나빠진 비율', '규칙 청산 중 수익으로 끝난 비율'. R 한 줄 정의. 코인별은 그 아래.

### E.3.X-029 한 거래 결과 분포와 손익 모양 (R와 ROE)

* **definition**: Per pool and arm, quarter size (live beside for x), closed trades. Count columns (all 89 arms): SL and LOCK shares; leverage-tier mix n and share by tr_lev in {50, 40, 30, 20}; LIQ count and share per tier. Money (E0 + choosable): p5, p10, p25, p50, p75, p90, p95 of R_i and of ROE_i, by tier and overall (numpy linear); shares ROE <= -40%, <= -60%, >= +20%, >= +60% (reading levels from the owners' examples, not rules); avgWinR = mean R over wins (pnl > 0); avgLossR = mean R over the rest; payoff = avgWinR/|avgLossR|; profit factor = sum R(wins)/|sum R(losses)|; break-even win share = 1/(1 + payoff); edge = win share - break-even (pp); expectancy = mean R; R per month = mean over picks of (mean R x trades/36); quantiles of x_i at live size; busted accounts at quarter size k of N. A cell without wins or losses prints '-'.
* **why_owner_cares**: 두 분은 ROE로 생각하시므로, 실제 거래가 +몇 %·-몇 %로 끝나는지, 이길 때와 질 때 크기가 어떤지, 대부분 몇 배로 들어갔는지를 한 표로 봅니다.
* **computed_from**: C4 record (R_i, ROE_i, x_i) and step-1 result files (tr_lev, tr_reason, counts, w_end)
* **new_code**: post-processing (xr_mech.trade_shape)
* **cost**: low
* **pool_handling**: SL/LOCK shares committed for both pools. Tier mix and LIQ by tier: core committed, DeepSeek private (the tier depends on the wallet through the bracket check, C8). Every R, ROE, x and bust figure: core E0 + choosable committed; DeepSeek private.
* **confirm_use**: none
* **min_sample**: cell n < 100 -> 건수 적음 (the 50x and 40x tiers are often thin); avgWin or avgLoss on < 20 trades also flagged
* **shown_as**: 부록 표 '한 거래 결과': 행 = 20배·30배·40배·50배·전체, 열 = '거래 수(%) / 강제청산 수 / 하위10%·중앙·상위10% ROE / -40% 이하 비율 / +60% 이상 비율'; 아래 '손익 모양: 승률 / 이길 때 평균 R / 질 때 평균 R / 손익비 / 본전 승률 / 본전보다 몇 %p 위 / 거래 1건 기대 R'. 문장 'R은 가격 기준 단위라 계좌 성장 숫자와 같지 않습니다'와 W14 '일찍 나오는 청산은 승률을 올리는 대신 이길 때 크기를 줄입니다. 승률만 보지 말고 손익비·본전 승률과 함께 보세요.'

### E.3.X-030 먼저 얼마까지 갔다가 끝났나 (최고·최저)

* **definition**: From the C4 excursions (1m last-price highs and lows of minutes e..x-1 plus the exit price; funding not included; the exit minute's own range never used). Per pool and arm (E0 + choosable), quarter size, by leverage tier and by bar group (단타, 1h + 4h, all): reach shares best_R >= 1, 2, 3; ROE touch shares best_ROE >= 12%, 17%, 22% (the F13 lock triggers) and >= 60%; among SL exits the shares with best_R >= 1 and >= 2; among wins the shares with worst_R <= -0.5 and <= -0.75 and the median worst_R (an upper bound of the winners an early cut at -0.5R could have killed); of trades with best_ROE >= 12%: the share closed at ROE >= 10%, the share closed at a loss, the median ROE/best_ROE; of trades with worst_ROE <= -40%: the share closed > 0, the share closed by SL, the median ROE. Lock distance per trade: d12 = (0.12/lev + S[5]) x fill/ATR14 with S = market.S(0.25) (ATR multiples the price must move to arm the +12% lock, funding ignored); p10, p50, p90 by tier and the shares d12 < 1 and < 0.5. Denominators printed.
* **why_owner_cares**: +60%까지 갔다가 무너지는 일, -40%까지 갔다가 회복하는 일이 실제로 얼마나 흔한지, 12%→10% 잠금이 가격이 얼마만 움직여도 걸리는지 숫자로 봅니다.
* **computed_from**: C4 record (best_R, worst_R, best_ROE, worst_ROE, R_i, ROE_i, fill, lev, ATR14), tr_reason, market.S(0.25)
* **new_code**: post-processing (uses the C4 1m scan)
* **cost**: low (the scan is about 15 s for all quarter accounts, lens measurement; aggregation seconds)
* **pool_handling**: Core E0 + choosable committed. DeepSeek: entirely private (excursions are P&L-derived; d12 uses the wallet-dependent leverage, C8).
* **confirm_use**: none
* **min_sample**: each share's denominator < 100 -> 건수 적음 (SL trades of rule variants are often few)
* **shown_as**: 부록 묶음 '중간 과정': '+1R·+2R·+3R까지 간 거래 % / 12%·17%·22%·60%에 닿은 거래 % / 손절 맞은 거래 중 먼저 +1R 갔던 % / 이긴 거래 중 손절선 절반 이상 밀렸던 % / 12%에 닿은 거래 중 손실로 끝난 % / -40%까지 갔다가 +로 끝난 %'와 '잠금이 걸리려면 가격이 ATR의 몇 배 움직이면 되나'. E0 줄이 기준선.

### E.3.X-031 최고점에서 얼마나 돌려줬나 (반납)

* **definition**: Per pool and arm (E0 + choosable), quarter size. Population = closed trades with best_R >= 1 (C4). giveback_i = (best_R_i - R_i)/best_R_i (above 1 when the trade ended negative). Report: n; median giveback; share with giveback >= 0.5; share with R_i <= 0 (gave back everything after +1R); capture ratio = sum R_i/sum best_R_i over the population. The same by exit-reason class TP, SL + LOCK, RULE, END.
* **why_owner_cares**: +1R 넘게 갔던 거래에서 번 돈을 얼마나 챙기고 얼마나 도로 뱉는지가 '수익 반납 규칙'과 '계단 잠금'이 쓸모 있는지의 핵심입니다.
* **computed_from**: C4 (best_R, R_i) and tr_reason
* **new_code**: post-processing (xr_mech.giveback)
* **cost**: low
* **pool_handling**: Core E0 + choosable committed; DeepSeek entirely private, the population count n included (excursion-derived, C8).
* **confirm_use**: none
* **min_sample**: population < 100 -> 건수 적음; reason-class cells < 100 marked and shown
* **shown_as**: 부록 표 '반납': '+1R 넘게 간 거래 수 / 그중 번 것의 절반 이상 돌려준 % / 다 돌려주고 손실로 끝난 % / 챙긴 비율(최고점 대비 실제 R)', 청산 이유별 줄 포함.

### E.3.X-032 같은 분 재진입과 쉬는 시간

* **definition**: Per pool, arm (all 89) and coin (appendix), quarter size, entered trades of each account in fill order. gap_h(i) = (tr_fill[i+1] - tr_exit[i])/3.6e6. (a) Same-minute entries (gap = 0) split into 반전 (same coin, opposite side), 같은 방향 재진입 (same coin and side) and 다른 코인; the three sum to entries_at_rule_minute (asserted). (b) Idle time: median and p90 of gap_h over consecutive pairs; share with gap_h <= 1. (c) Quick same-direction re-entry: for exits of the classes 손절 (SL, LOCK), 규칙 청산 (RULE) and 익절 (TP), the share whose next entered trade has the same coin and side with gap_h <= 4. The last trade of an account has no next trade and is left out of (b) and (c).
* **why_owner_cares**: 규칙으로 나왔다가 바로 같은 방향으로 다시 들어가는 일이 잦으면 수수료만 두 번 낸 셈이라, 일찍 나오는 규칙이 헛수고인지 봅니다.
* **computed_from**: step-1 result files (tr_coin, tr_side, tr_fill, tr_exit, tr_reason)
* **new_code**: post-processing (xr_mech.reentry)
* **cost**: low
* **pool_handling**: Counts, shares and hours from entry and exit times only (count and time class): committed for both pools (C14 layout).
* **confirm_use**: none
* **min_sample**: (a) cell < 100 entries -> 건수 적음; (c) denominator (exits of that class) < 100 -> 건수 적음
* **shown_as**: 부록 표 '재진입': '같은 분에 바로 들어간 횟수(반전 / 같은 방향 / 다른 코인) / 청산 뒤 다음 진입까지 쉰 시간 중앙값·90% / 손절 뒤·규칙 청산 뒤·익절 뒤 4시간 안에 같은 코인 같은 방향으로 다시 들어간 비율'.

### E.3.X-033 보유시간 꼬리와 해마다

* **definition**: Per pool and arm (all 89), quarter size, closed trades, hold = (tr_exit - tr_fill)/3.6e6 h as in 7. (a) Tails: p10 of hold, share > 24 h, share > 72 h (strict), longest hold; p90 printed as 'select.json과 같음' (read). (b) Median hold of wins (pnl > 0) vs the rest; median hold by exit class TP, SL + LOCK, RULE, END. (c) By UTC year of tr_exit (2021, 2022, 2023): closed trades n_y, median hold, entered trades of V vs E0; labels 'E0 이상 진입 k/3해' (years with V's entered >= E0's) and '더 짧은 해 k/3해' (years with V's median hold < E0's). (d) Appendix: (a) per coin.
* **why_owner_cares**: '단타 느낌'을 원하시는데, 중앙값이 짧아도 며칠씩 들고 가는 꼬리 거래가 남아 있는지, 진 거래를 오래 들고 있지 않은지, 보유가 짧아지고 진입이 느는 게 매년 맞는지 봅니다.
* **computed_from**: step-1 result files (hold_h, tr_pnl, tr_reason, tr_exit, tr_coin, counts) and select.json hold
* **new_code**: post-processing (xr_mech.hold_tails)
* **cost**: low
* **pool_handling**: Hours, counts and win/loss splits of hold (no money): committed for both pools.
* **confirm_use**: none
* **min_sample**: cell n < 100 -> 건수 적음 (year cells included)
* **shown_as**: 부록 표 '보유시간 꼬리': '짧은 쪽 10% / 중앙값 / 긴 쪽 10%(select.json과 같음) / 24시간 넘게 든 % / 3일 넘게 든 % / 가장 길게 든 시간 / 이긴 거래 vs 진 거래 중앙값 / 청산 이유별 중앙값'; 해마다 표 '2021 중간 __시간(E0 __) · 2022 · 2023 / 진입 +__% … → 세 해 모두 진입이 늘고 보유가 짧아짐'.

### E.3.X-034 비용 장부 (수수료·미끄러짐·펀딩)

* **definition**: Per closed trade (C4: qty, fill, raw = o[e], exit minute x, xpx = tr_xpx), quarter size (live beside): fee_in = qty x fill x S[0]; fee_out = qty x xpx x (S[19] if TP, S[0] otherwise, 0 if LIQ); slip = qty x raw x S[1] + (for market exits SL, LOCK, RULE, END) qty x X x S[1] with X = xpx/(1 - side S[1]); fund = sum over minutes j in (e, x] of side x qty x mo[j] x fund[j] (positive = paid); move = pnl + fee_in + fee_out + slip + fund; for every non-LIQ trade |move - side x qty x (X - raw)| <= 1e-9 x notional is asserted (X = xpx at TP), else the stage stops. Per pool and arm (E0 + choosable): per month, (fees + slip)/Wb and fund/Wb summed over the trades exiting in the month, mean over alive pick-months in % of the wallet; round trips per account-month (calendar); cost per round trip in % of the wallet. Per trade in R: costR = (fee_in + fee_out + slip)/(qty Rd), fundR = fund/(qty Rd); gross = R + costR + fundR; cost share of gross (when gross > 0); first-order break-even multiple c* = (mean gross - mean fundR)/mean costR ('< 1' means the average trade already loses at today's cost; the trade set is held fixed). By hold bucket [0,1), [1,4), [4,8), [8,18), [18,48), >= 48 h: n, win share, share of sum l_i (C17), mean ROE, funding and fees per trade in ROE points (fund/margin, fees/margin). By side: settlements crossed per trade = #{j in (e, x]: fund[j] != 0} (the data's actual events, never assumed hours), share of trades that net receive, mean funding in % of notional.
* **why_owner_cares**: 짧게 들수록 사고팔기가 늘어 비용이 커지는데, 매달 지갑의 몇 %가 수수료·미끄러짐·펀딩으로 나가는지와 비용이 몇 배까지 올라도 평균 거래가 버티는지 봅니다.
* **computed_from**: C4 record, select-cut arrays (o, mo, fund), market.S(scale), step-1 result files
* **new_code**: post-processing (numba cost split in xr_scan.py; no kernel change)
* **cost**: low (about 0.01 s per account)
* **pool_handling**: Counts (n per hold bucket, win share per bucket, round trips per account-month on the calendar denominator, settlements per trade) committed for both pools. Every cost or funding amount, its sign share, R, ROE, c* and growth share: core E0 + choosable committed; DeepSeek private.
* **confirm_use**: none
* **min_sample**: cell n < 100 -> 건수 적음
* **shown_as**: 부록 표 '비용 장부': '한 달 거래 수 / 한 달 수수료+미끄러짐(지갑의 %) / 한 달 펀딩(지갑의 %) / 한 번 사고팔 때 비용 / 거래 1건당 비용 R / 비용이 몇 배까지 올라도 본전인가'; 보유 시간대별 6줄 표; 롱·숏 펀딩 표. 첫 장 W24에 E0의 한 달 비용 인용.

### E.3.X-035 하루 주문 횟수 (실전에서 봇이 할 일)

* **definition**: Per pool and arm (all 89), quarter size, order events per account-day over 1,095 UTC days. Each entered trade: 1 market entry + 1 stop order + 1 take-profit limit when the arm has one (E0, mode a, F11.b/F12.b when the native target lies beyond the fill). Each exit: 1 fill + 1 cancel per remaining resting order (TP, SL, LOCK exits), or 1 market order + cancels (RULE, END). F13 only: 1 stop amendment per minute in which the lock rose, replayed over minutes e+1..x-1 with the kernel's ladder (best net ROE with funding, lock 10% + 5% n armed at lock + 2%, the new stop applying from the next minute); every LOCK exit must lie at the replayed lock price less slippage or at a gapped open (asserted). Events are dated at their minute. Report: mean events per account-day, the 99th percentile and the maximum over account-days, the share of account-days with >= 1 event; F13 rows also amendments per trade (median, p90).
* **why_owner_cares**: 실전에서 봇이 하루에 주문을 몇 번 내고 손절선을 몇 번 옮기는지 알려 줘서, 실제 돈으로 돌릴 때 감당할 수 있는지(거래소 제한, 지켜보는 부담) 미리 판단합니다.
* **computed_from**: step-1 result files (tr_fill, tr_exit, tr_reason), exit_of_pick, C4 and the select-cut arrays (h, l, mo, fund) for the lock replay
* **new_code**: post-processing (numba lock replay in xr_scan.py; no kernel change)
* **cost**: low (<= 0.4 s per F13 account, lens measurement)
* **pool_handling**: Order-event counts committed for both pools. F13 amendment counts: core committed; DeepSeek private (they follow the price path in profit, C8).
* **confirm_use**: none
* **min_sample**: fewer than 100 trades -> 건수 적음
* **shown_as**: 부록 칸 묶음 '하루 주문': '하루 평균 / 많은 날(상위 1%) / 가장 많은 날 / 주문이 있는 날 비율'; 코어 계단 잠금(F13) 줄에 '거래 한 번에 손절선을 옮긴 횟수(가운데 / 상위 10%)'.

### E.3.X-036 매매법 성격별 (사후 분류)

* **definition**: Character per pick from select data only: r_sel = the share of the pick's offered select signals whose side equals sign(close[i0] - close[i0 - 20]) on the signal's coin at the pick's bars (pdata chart closes; a sign of 0 counts as not trend); 추세형 r_sel >= 0.60, 되돌림형 r_sel <= 0.25, 섞임 otherwise (cut-offs fixed here before any number). It is an in-sample label of the whole period (a 2021 trade's cell depends on later signals), not a rule. Per character cell (per pool): X-024's count columns (all 89 arms). No money columns and no family roll-up. The dashboard style label (candleague/data/strategies_ko.json) is not used, because it was built with 2024-2026 prices.
* **why_owner_cares**: 추세를 따라가는 매매법과 되돌림 매매법은 맞는 청산이 다를 수 있어서, 성격별로 보유·진입이 어떻게 달라지는지 참고합니다.
* **computed_from**: PickData chart closes and offered table (i0, side, coin); step-1 result files
* **new_code**: post-processing (xr_mech.character_cells)
* **cost**: low
* **pool_handling**: Count columns committed for both pools. Core r_sel and character per pick committed; DeepSeek r_sel and character per pick private (not an A8 (1) field, C8).
* **confirm_use**: none
* **min_sample**: cell < 3 picks -> 픽 N개; cell < 100 trades -> 건수 적음
* **shown_as**: 부록 표 '성격별(사후 분류)': 추세형·섞임·되돌림형 칸(X-024의 건수 칸). 문장 W20 '기간 전체로 정한 매매법 성격(사후 분류)이며 규칙이 아닙니다. 성격별로 청산을 따로 고르지 않습니다.'

### E.3.X-037 기간을 나눠도 나은가 (운 눈금 포함)

* **definition**: Per pool and choosable V (E0 rows show their own levels), quarter size. D_m = the contract's pooled monthly difference D_m^P(V) (7) from the step-1 g arrays; M(S) = mean of D_m over a month set S. (a) Halves: first = months 1-24 (2021-2022), second = 25-36 (2023); odd vs even calendar months (18 each); (24 M(first) + 12 M(second))/36 = M and (M(odd) + M(even))/2 = M asserted; per split '같은 방향' (both > 0) or '엇갈림'. (b) Years: M_2021, M_2022, M_2023; k = years > 0 ('세 해 모두 +' / '두 해만 +' / '한 해만 +' / '0해'); leave-one-year-out min_y (36M - 12 M_y)/24 and its year; the 25 rolling 12-month windows: worst window mean and count of windows > 0 (overlap stated); E0's and V's own pooled growth per year (%/월), so a plus is not read as 'both lost less'. (c) Months: m* = argmax D_m (ties to the earliest), its UTC month, its share 100 D_m*/sum D (C17); M without it = (36M - D_m*)/35; counts better / equal (|D_m| <= 1e-9) / worse; the 36-character sign string (+, =, -); top-3 removed (sum D - three largest)/33 with label '상위 3개월 의존' when <= 0 while M > 0; quarters with D_q > 0 (k of 12) and half-years (k of 6). (d) 95% interval of M by metrics.block_bootstrap_ci(D, seed C11, n_boot 2000, block 3, level 95): label '0을 안 걸침(88개 중 고른 것이라 증거 아님)' or '0을 걸침'. (e) Chance yardstick (choosable rows only; replaces the earlier X-040): C = the pool's choosable variants with a placebo (not F7, F7h, F13); n_h = #{V in C: M(first) > 0 and M(second) > 0}, n_y = #{V in C: all three M_y > 0}; for each placebo seed s common to every V in C, D_m^s(V) = mean over picks of [g_plc(V, s, p, m) - g_E0(p, m)] from the step-2 placebo block files (summarize_light g), and n_h^s and n_y^s the same counts over C; print the median and 95th percentile over s beside n_h and n_y (with |C| and the seed count). (f) Per V in C: shares of its own seeds with both halves > 0 and with all three years > 0. No p. Never a figure of a 선택 불가 variant.
* **why_owner_cares**: 좋아 보이는 결과가 3년 내내 꾸준했는지, 한 해나 한두 달 덕분인지, 그리고 아무렇게나 일찍 나오는 가짜 청산에서도 같은 '좋은 표시'가 얼마나 나오는지를 같이 봅니다.
* **computed_from**: step-1 result files (g of V and E0) through the contract's pooled-series formula; tr_exit for cell sizes; step-2 placebo block files of choosable rows (g per seed)
* **new_code**: post-processing (xr_trust.robust_rows, placebo_yardstick; one existing metrics call for (d))
* **cost**: low (seconds) plus a few minutes of I/O for the placebo files of choosable rows
* **pool_handling**: All money or money-derived (labels and yardstick included). Core choosable rows and core pool lines committed; DeepSeek entirely private (part 핵심).
* **confirm_use**: none
* **min_sample**: cell = closed trades of V and of E0 exited in the cell's months; either < 100 -> 건수 적음 on that cell (most single months are flagged); (e) prints |C| and the number of seeds
* **shown_as**: 본문 표 '믿을 만한가(참고용)': 표 위 한 줄 '나오는 때만 무작위로 바꾼 가짜 청산에서도 앞뒤 반 모두 + 가 보통 __개(상위 5% __개), 세 해 모두 + 가 보통 __개였고, 실제 선택 가능 방식은 __개·__개입니다'. 줄마다 '앞(21~22년) · 뒤(23년) → 같은 방향 / 홀짝 달 → … / 2021·2022·2023 → 두 해만 + / 가장 잘한 달 YYYY-MM이 이득의 __%, 빼면 __%/월 / 운 폭 __~__%/월 → 0을 걸침 / 이 방식의 가짜 청산이 같은 표시를 받은 비율 __%'. 36칸 부호열과 12개월 창은 부록. 읽는 법 한 줄. 경고 W8 '같은 기간에 88개를 돌려 좋은 것을 고르면 실력이 없어도 '세 해 모두 +'나 '같은 방향'이 나옵니다. 나오는 때만 무작위로 바꾼 가짜 청산에서도 보통 __개가 그렇게 나왔습니다. '0을 안 걸침'도 88개 중에서 고른 것이라 증거가 아닙니다.' C15 줄.

### E.3.X-038 큰 거래 몇 개 덕인가

* **definition**: Per pick and arm, quarter size, from C4 l_i. T5(A) = sum of the 5 largest l_i of A's own trades (all trades if fewer than 5); T1(A) = the largest. M5_p(V) = {[sum l(V) - T5(V)] - [sum l(E0) - T5(E0)]}/36 (each arm loses its own best 5; the other trades are not re-sized: an arithmetic removal, not a re-run); M1_p likewise. Pool (E0 + choosable): mean M5_P and M1_P (as %/월, C12); picks with M5_p > 0 out of N; gain kept = M5_P/M_P under C17; E0's and V's own share of growth from their best 5 = T5/sum l under C17; average trades per account of V and E0 (so 5 can be judged).
* **why_owner_cares**: 운 좋게 터진 큰 거래 몇 개를 양쪽에서 빼도 여전히 지금 방식보다 나은지 봅니다.
* **computed_from**: step-1 result files (tr_pnl, w0) through C4
* **new_code**: post-processing (xr_trust.top_trades_removed)
* **cost**: low
* **pool_handling**: Money. Core E0 + choosable committed; DeepSeek private.
* **confirm_use**: none
* **min_sample**: a pick with < 30 trades is 건수 적음 (left out of 'picks with > 0' and counted); a pool row with < 100 trades -> 건수 적음
* **shown_as**: 부록 한 줄(방식마다): '각자 가장 큰 5거래씩 빼도 E0보다 __%/월 (원래 __%/월), 이득의 __%가 큰 5거래 몫, __/__개 픽에서 여전히 +'. W15 규칙.

### E.3.X-039 옆 숫자도 되나 (이웃 비교)

* **definition**: Neighbours of V in the same pool: variants of the same family, mode (a/b) and q15 flag whose parameters differ from V's in exactly one parameter, by one step of that parameter's grid in kernel_x (F1 w 2,3,5; F2 n 10,20,50; F4 m 1.5,2,3; F5 P 1,1.5,2 and g .25,.5; F6 w and d 0,.5; F7 N 12,24,48; F7h H 4,8,16; F8 w and P 1,2; F10 N 6,12; q15 versions are their own rows). F3, F9, F9 q15, F11, F12 and F13 have no grid, so 12 variants print '이웃 없음' (of the other 76: 32 have 1 neighbour, 34 have 2, 10 have 3; asserted). Per choosable V: k neighbours; n1 = neighbours whose gate-1 mark is pass; ne = neighbours marked 선택 가능; edge flag '격자 끝' when a parameter of V sits at the first or last value of its grid (every value of a 2-value grid is an edge); label '이웃 모두 통과' (n1 = k), '이웃 일부 탈락' (0 < n1 < k), '이웃 모두 탈락' (n1 = 0), '이웃 없음'. Only the gate marks and labels already in select.json are read; no neighbour's growth number is used.
* **why_owner_cares**: 고른 숫자 바로 옆 숫자도 비슷하게 통과하는지, 아니면 우연히 맞은 한 점인지 봅니다.
* **computed_from**: select.json gate marks and eligible ids; kernel_x.variants() ids and parameters
* **new_code**: post-processing (table lookup)
* **cost**: none
* **pool_handling**: Built only from labels select.json commits for every row of both pools: committed for both pools.
* **confirm_use**: none
* **min_sample**: not a trade cell; a neighbour whose pool trades are < 100 is marked 건수 적음 beside the count
* **shown_as**: 부록 칸(선택 가능 줄마다): '이웃 2개 중 2개 통과, 선택 가능 1개, 격자 끝 아님 → 이웃 모두 통과'. 문장 '격자가 3칸이라 약한 근거입니다'.

### E.3.X-041 비용이 오르면 (다시 돌린 계좌)

* **definition**: E0 + choosable arms, each pick, quarter size, select: re-run (C2) with S_c = a copy of market.S(0.25) with S[0] (taker), S[1] (slippage), S[5] (round trip) and S[19] (maker) multiplied by c, c in {0, 1.5, 2, 3}; funding, margins, brackets and leverages unchanged. Rules and the lock that read net R or net ROE, and the size rule's 15% cap, see the new costs (more signals may be rejected; that is part of the answer). Per pool, arm and c: M_P(V; c) against E0 at the same c (section 7 definition), shown as %/월; E0's own pooled growth 100(e^{mean_p ln(w_end/w0)/36} - 1); entered and rejected; the crossing multiple where M_P(V; c) turns <= 0 by linear interpolation over c = 1, 1.5, 2, 3 ('3 이상' when it never crosses, '1 미만' when M_P(V; 1) <= 0); M_P(V; 0) as the gain before any cost.
* **why_owner_cares**: 실제 거래소에서는 미끄러짐이 생각보다 클 수 있는데, 자주 일찍 나오는 청산이 비용이 2~3배가 돼도 지금 청산보다 나은지 미리 봅니다.
* **computed_from**: re-runs of the pinned KX.simulate with a scaled settings vector S
* **new_code**: post-processing (xr_rerun.S_variant; no kernel change)
* **cost**: medium: 4 runs per pick-arm, ≈ 3,950 account-equivalents; c = 1.5 is second in the cap's drop order
* **pool_handling**: Entered and rejected counts committed for both pools. Growth figures and the crossing multiple: core E0 + choosable committed; DeepSeek private (no DeepSeek sign label committed).
* **confirm_use**: none
* **min_sample**: the pool's entered trades at that setting < 100 -> 건수 적음
* **shown_as**: 부록 표 '비용이 오르면': 줄 = 선택 가능 방식(맨 위 E0 자신의 성장), 칸 = '비용 0 / 지금 / 1.5배 / 2배 / 3배에서 지금 청산보다 %/월', 'E0 자체 성장', '이 방식이 E0보다 못해지는 비용 배수'. 첫 장 W24에 E0의 2배 칸 인용.

### E.3.X-042 가짜 청산과 나란히 (그림과 범위)

* **definition**: Per pool and choosable V with a placebo (not F7, F7h, F13). (a) Figure (SVG, hand-written, no new dependency): by month m = 1..36 the cumulative pooled log growth of V and of E0 (mean over picks of ln(W_m/W_0)) and the cumulative D_m(V), with the placebo band = per month the 5th to 95th percentile over V's seeds of the cumulative D_m^s (as X-037 (e)) and the median line. (b) Band table: per seed, with the dead-month rule of C6 on placebo accounts (w_end < $10), the pooled p50 and p90 of month multiples x, the shares x >= 1.5, 2, 5, the bust count, the median max_dd and the median final multiple; then the 5th, 50th and 95th percentiles over seeds, beside V's own values (same rules, absolute scale).
* **why_owner_cares**: 아무렇게나 일찍 나와도 이 정도 달이 나온다는 '운의 범위'를 옆에 놓고 그림으로 보면, 방식의 숫자가 운 이상인지 눈으로 알 수 있습니다.
* **computed_from**: step-1 result files (W, g) of V and E0; step-2 placebo block files of choosable rows (g, w_end, max_dd, counts)
* **new_code**: post-processing (xr_trust.placebo_band + SVG writer)
* **cost**: low (placebo arrays already read for X-037)
* **pool_handling**: Core figure and table committed for choosable rows. DeepSeek private.
* **confirm_use**: none
* **min_sample**: a seed with < 100 pick-months is skipped and counted; the band is 건수 적음 below 50 seeds
* **shown_as**: 부록 그림(풀마다, 선택 가능 방식마다): 선 3개 'E0 / 이 방식 / 가짜 청산의 5~95% 띠'; 캡션 '띠 안이면 시간만 줄인 것과 구분되지 않습니다. 가짜 청산은 나오는 시점만 무작위로 바꾼 것입니다.' 아래 작은 표 '가짜 청산 __번 중: 보통 달 x__ (5~95%: x__~x__) …'.

### E.3.X-043 1,000달러로 시작하면

* **definition**: E0 + choosable arms, each pick, select, scales 0.25 and 1.0: re-run (C2) with S = a copy of market.S(scale) with S[10] (starting wallet) = 1,000; the bust threshold S[9] = $10 unchanged (a test asserts the base S[10] is 5,000 and nothing else changes). Compared with the $5,000 account of the same scale: entered, rejected (lot step, minimum notional, brackets, the 15% rule), M_P(V vs E0) at both starts, the number of picks whose bust status differs, median final multiple. Verdict line: '1,000달러도 5,000달러와 거의 같습니다' when, for every printed row, entered differs by <= 1% and |dM_P| <= 0.1 %/월; otherwise the differences are listed. DeepSeek's committed verdict uses the entered and rejected counts only.
* **why_owner_cares**: 두 분은 1,000달러로 생각하시는데 연구는 5,000달러 계좌로 돌렸으므로, 최소 주문 크기 때문에 결과가 달라지지 않는지 한 번 확인합니다.
* **computed_from**: re-runs of the pinned KX.simulate with a settings vector S
* **new_code**: post-processing (xr_rerun.S_variant; no kernel change)
* **cost**: low-medium: 2 runs per pick-arm, ≈ 1,980 account-equivalents; the live-size part is third in the cap's drop order
* **pool_handling**: Entered and rejected counts committed for both pools; growth, multiples and busts: core committed, DeepSeek private.
* **confirm_use**: none
* **min_sample**: pick level; a pool's entered trades < 100 -> 건수 적음
* **shown_as**: 부록 한 줄 판정('거의 같습니다' 또는 '다릅니다: …')과 작은 표 '진입 / 거절 / E0 대비 %/월: 1,000달러 vs 5,000달러'. 첫 장 (5)에 판정 인용. W13.

### E.3.X-044 리그 점검이 차이를 잡아낼 확률 (최대치)

* **definition**: Core and DeepSeek computed; pool level only, naming no row; built on X-023's fresh-start windows (143 Monday starts). (a) C1 first condition: for each choosable V, s_V = the share of windows with G_30(V) < G_30(E0) (only 11.5 C1's first condition; the condition against the coin flip is not computed, so this is an upper bound of the stop chance); print the median and min-max of s_V over the pool's choosable rows. (b) For D = 61 and 92 days: weekly marks at s + 7w (w = 1..floor(D/7)), the last part-week merged into the last full week, marks as X-023; d_w = mean over picks of the weekly marked log growth of V minus E0's (as 11.5); p = one-sided exact sign-flip p over all 2^n patterns (n <= 13 here), code copied from candleague.rulex and tested equal; 'shown ahead' in a window = G(V) > G(E0), p < 0.03 (61 d) or < 0.02 (92 d), >= 150 closed V trades over the pool's accounts in the window, and G(V) > 0 (the condition against the coin flip not computed: an upper bound); s61_V, s92_V and the share at either look; print the median and min-max over choosable rows. The p values are used only inside the count and are never printed or stored.
* **why_owner_cares**: 새 청산이 정말 더 낫더라도 리그 30일·61일 점검에서 그게 드러날 확률이 높지 않을 수 있다는 것을 미리 알려 드려서, 몇 주 결과로 성급하게 판단하지 않게 합니다.
* **computed_from**: X-023 window runs and weekly marks; the select D series; candleague.rulex sign-flip code (copied)
* **new_code**: post-processing (xr_trust.league_power)
* **cost**: low (seconds per (V, pool) on the X-023 windows)
* **pool_handling**: Shares are outputs of money tests: core pool-level lines committed; DeepSeek private.
* **confirm_use**: none
* **min_sample**: fewer than 100 windows -> 건수 적음 (143 windows; 72 if the cap drops)
* **shown_as**: 부록 표 '리그 점검이 차이를 잡아낼 확률(최대치)': '30일 점검에서 E0보다 못해 보일 확률 / 61일에 앞선다고 나올 확률 / 92일 / 둘 중 한 번이라도', 선택 가능 방식들의 가운데와 범위, 방식 이름 없음, 칸마다 '최대치'. 경고 W11 '30일 점검(C1)은 계약대로 적용됩니다. C1을 통과해도 30일·61일 결과만으로 더 나은지 판단하지 마세요. 새 청산이 정말 더 낫더라도 그 기간에는 드러나지 않을 때가 많습니다. 이 확률은 리그에서 아무것도 결정하지 않습니다.'

### E.3.X-045 가장 좋은·나쁜 거래 5개

* **definition**: Per pool and arm (E0 + choosable), quarter size: rank the closed trades of the pool's accounts by x_i (C4); the 5 largest and the 5 smallest (ties to the earlier fill, then the canonical pick order). Row fields: pick id (C13: F11 rows on F7_RF_ONLY picks marked '= F3', Known limit 11), coin, side (롱/숏), fill and exit time (UTC and KST), hold hours, exit reason (for F12 the fired components of tr_comp), fill price, exit price (tr_xpx; LIQ shown as 강제청산), leverage, ROE_i, x_i in %, 장세 at entry.
* **why_owner_cares**: 가장 좋은 거래와 나쁜 거래를 눈으로 보면 계산 오류나 이상한 거래(너무 긴 보유, 기간 끝 강제 청산)를 바로 잡을 수 있습니다.
* **computed_from**: C4 record and step-1 result files (tr_*)
* **new_code**: post-processing (xr_trust.extreme_trades)
* **cost**: low
* **pool_handling**: Core list committed (16.7 item 4 allows per-pick rows in the extra file). DeepSeek: private only (each row is a P&L).
* **confirm_use**: none
* **min_sample**: not a cell (a list of 10 trades)
* **shown_as**: 부록 작은 표 두 개 '가장 좋았던 5 / 가장 나빴던 5'; 한 줄 '이상해 보이는 거래가 있으면 알려 주세요'.

### E.3.X-046 한 장 요약 (먼저 볼 숫자 5개, 주의 6개)

* **definition**: The first page of EXTRA_READS_KO.md, per pool, filled only from other reads and select.json: no new computation, no ranking by money, no recommendation. Line 0: W0. Five numbers: (1) E0's own monthly growth at quarter size = 100(e^{mean_p ln(w_end/w0)/36} - 1) %/월, labelled '맞춘 기간의 성적', with live size beside and live busts k/N in the same cell, and the sentence that a variant's own growth = E0's + its E0 대비 column; (2) X-016's x5 row for E0: needed win share and needed entries per month vs now (or 불가능); (3) X-025 for E0: offered, skipped while holding (core: of which sizeable), rejected, entered, and (core) the entry ceiling; (4) choosable variants K of 88 and the ids the default of 8.4 would take (from select.json); (5) X-043's verdict line and X-021's one-account line. Six warnings: W0 in-sample; W1 the winner's curse (W22), for core with X-037 (e)'s placebo count; W2 2024-2026 is not blind (W23; Known limits 1, 2); W3 quarter size decides and live size can bust (W9); W4 cost per month from X-034 and X-041's 2x column for E0 (W24); W5 the league clause (W11). The DeepSeek committed page carries (3) offered/skipped/rejected/entered counts, (4) and the warnings without figures (W18); its figures go to the private report, part 핵심.
* **why_owner_cares**: 표 여러 장을 읽기 전에, 목표와 관련된 가장 중요한 숫자 5개와 꼭 알아야 할 주의 6개를 한 장에서 먼저 봅니다.
* **computed_from**: X-014, X-016, X-021, X-025, X-034, X-037, X-041, X-043, X-044 outputs and select.json
* **new_code**: post-processing (report writer, xr_report_ko.first_page)
* **cost**: none
* **pool_handling**: Core page committed. DeepSeek page committed with counts and labels only (C14); DeepSeek figures only in owner_report_extra.md part 핵심.
* **confirm_use**: none
* **min_sample**: inherits the 건수 적음 marks of the reads it quotes
* **shown_as**: EXTRA_READS_KO.md 첫 장 '한 장 요약': 맨 위 W0 '이 문서의 숫자는 모두 2021~2023년 백테스트입니다. 이 기간은 매매법의 숫자와 지금 청산(E0)을 고른 기간이라, 앞으로보다 좋게 나온 값입니다. 고를 수 있는지는 고르기 표(SELECT_KO)의 기준으로만 정하고, 이 문서는 참고용입니다.' 숫자마다 한 줄 설명(예: '지금 청산은 한 달에 __%/월(맞춘 기간의 성적)', '한 달 x5에는 승률 __% 필요(지금 __%) 또는 불가능', '들고 있어서 놓친 신호 __개 중 탈 수 있었던 것 __개'), 주의 6줄은 굵은 글씨: W22, W23, W9, W24, W11 '30일 점검(C1)은 계약대로 적용됩니다. C1을 통과해도 30일 결과만으로 더 나은지 판단하지 마세요.' SELECT_KO.md는 바꾸지 않음.

### E.3.X-047 한 줄 성적표 (두 분의 말로)

* **definition**: Per pool, one row per arm (E0 + choosable), quarter size with live size beside. Columns: entries per account-month = entered/(N x 36); wins (pnl > 0) and losses (the rest) as counts; win share; mean ROE_i over wins and over losses (C4, % per trade); payoff = mean x_i over wins/|mean x_i over losses| ('-' without one side); break-even win share = 1/(1 + payoff); typical month = X-014's p50 (x); share of months with x >= 2 (X-014); max drawdown at closes = median over picks of the step-1 max_dd, with X-019's open-position range (median MDD_low..MDD_high); busts k/N at quarter and at live size (w_end < $10); own monthly growth = 100(e^{mean_p ln(w_end/w0)/36} - 1) %/월, and for choosable rows beside it the difference vs E0 = 100(e^{M_P} - 1) (C16: W12 when own growth <= 0). No new account is run; every value comes from the step-1 files, C4 and the reads named.
* **why_owner_cares**: 두 분이 늘 묻는 승률·승패·손익·낙폭·진입 횟수·수익률·파산 여부를 방식마다 한 줄로 모아, 표 여러 장을 뒤지지 않고 봅니다.
* **computed_from**: step-1 result files (counts, tr_pnl, max_dd, w_end, w0) at quarter and live size; C4 (x_i, ROE_i); X-014; X-019
* **new_code**: post-processing (xr_goal.scorecard)
* **cost**: none (from other reads)
* **pool_handling**: Entries per account-month, wins/losses and win share committed for both pools (C14). Everything else: core E0 + choosable committed; DeepSeek private (part 핵심).
* **confirm_use**: none
* **min_sample**: a row with < 100 closed trades -> 건수 적음; mean ROE of wins or losses on < 20 trades also flagged
* **shown_as**: 본문 표 '한 줄 성적표', 꼬리표 '맞춘 기간의 성적': 행 = E0 + 선택 가능 방식, 열 = '한 달 진입 · 승/패 · 승률 · 이길 때 평균 ROE · 질 때 평균 ROE · 손익비 · 본전 승률 · 보통 달 x · x2 이상 달 % · 최대 하락(닫힌 거래 / 들고 있는 동안 포함 범위) · 파산(1/4 크기, 1/1 크기) · 한 달 성장 %/월(E0 대비 ±)'. 읽는 법 한 줄. W14 '일찍 나오는 청산은 승률을 올리는 대신 이길 때 크기를 줄입니다. 승률만 보지 말고 손익비·본전 승률과 함께 보세요.', 절대 성장 0 이하 줄에 W12 '지금 청산보다 덜 잃은 것이지 돈을 번 것은 아닙니다.', 1/1 칸에 W9.

## E.4 Outputs and sending
- Committed:
  - research/exitflex/extra/out/EXTRA_READS_KO.md;
  - EXTRA_READS_APPENDIX_KO.md;
  - extra_reads.json, including the run record of E.5;
  - extra_reads_rows.csv (count columns of all 89 rows of both pools, and the twins);
  - figs/*.svg (core).
  None is named select*, confirm*, SELECT_KO* or REPORT_KO*. Each passes runner_x.py audit-file and the C8 guard before commit.
- Private: $WORK/<pin8>/ds_private/extra_reads_ds.json and owner_report_extra.md (E.1 item 5).
- Order of work:
  1. The stage `python research/exitflex/extra/run_extra.py extra-reads` runs after the select run, its post-run audits, the commit
     of the hashes of select.json and SELECT_KO.md (13, step 3), and O8.
  2. Its outputs and the private report are sent or shown in the same turn as, or before, SELECT_KO.md (8.7; extra_shown_utc).
  3. After a select rerun (14) it is rerun on the _r2 files under the same rules, or not at all.
- The stage console prints read ids, pass or fail, and seconds only.

## E.5 Compute, cap, disk and run record
- Expected: about 37,500 account-equivalents of re-runs (twins about 8,800 of them) plus about 15 CPU-minutes of post-processing,
  placebo reads and builds. That is about 12-25 min wall on 4 CPUs.
- Projection: before any read, the stage times on core-DOGE-15m-1 one account each of E0, F12.a and a q15 arm, plus one PickData
  build with F11, and projects every part.
- Order and cap:
  - The twins and tier A run first and are never dropped by the cap.
  - If the projection exceeds 45 min wall, parts are dropped in this order until under:
    1. X-022 fixed leverage;
    2. X-041 c = 1.5;
    3. X-043 live size;
    4. X-023 and X-044 on every second Monday (72 starts);
    5. X-002;
    6. X-022 entirely.
  - Each drop must lower the projection (test). Each drop is printed and written to extra_reads.json. A drop by this rule is
    pre-registered, not a deviation.
- Disk: the stage refuses to start with less than 1.5 GB free under $WORK and stops if the bytes written would leave less than
  1 GB. Expected writes are under 0.3 GB.
- Run record (extra_reads.json, field run, committed for both pools): for each read and twin, seconds, accounts run, bytes written,
  parts dropped and dropped_at_o8.

## E.6 Tests
test_extra_reads.py runs on synthetic data only and prints pass or fail and counts. It holds:
- the shared tests of C2-C17 and E.1;
- one fixed-input test per read and per twin kind (the plan's section 6).
It passes at the O8 commit and is rerun by the stage before any read runs.

## E.7 Not in this file
Each of these needs a kernel change, confirm data, an unverified input, an owners' answer or its own pre-registration:
- exit-order latency;
- intra-trade marked equity with funding;
- coin-count chains;
- any confirm-period version of a read (the X-047 scorecard on the confirm included) and the select-versus-confirm composition table;
- macro-event windows;
- the owners' own limit labels;
- placebo trade-level reads;
- the KST-calendar weekend account;
- the dashboard style label;
- statistics over the money of all 88 variants (rank agreement, top-10 overlap, PBO);
- X-044's waiting time at 182/365 days and its confirm pass chance;
- the coin-flip condition of C1/C2 in X-044;
- a trend-direction split;
- a family x character roll-up;
- per-pick forward bands.

## E.8 Twin accounts (16.7 item 4)

The twin accounts are defined in full in section TW below. The short form that the design plan had here is withdrawn.

## E.9 Decisions on the design's open points (main session, 2026-10-12, before this file was committed)

1. **Weekend** (X-004, X-005, X-006): Saturday 00:00 to Monday 00:00 UTC of the signal-bar close (Korean time Saturday 09:00 to Monday
   09:00), the definition of the hunt's O1 and of the league. The owners were offered the Korean calendar weekend as an alternative;
   a different answer before the reads run is recorded in `research/exitflex/DEVIATIONS.md` under `[extra/reads]` and changes only
   the label of the weekend reads, not which reads exist.
2. **The owners' limits table** (win share at least 70%; maximum drawdown up to 15% on 15m, 20% on 30m and 30% on 1h and 4h picks):
   kept, as information, with these numbers, which are the main session's reading of the owners' earlier messages; the report says
   so and asks the owners to confirm. A different answer is recorded as above and changes only that table's thresholds.
3. **The sizing and leverage table**: fixed 20x, 30x and 40x, and sizes 1/2x and 2x of the study's quarter size, as information only;
   the study and the league keep their sizes.
4. **Twins**: section E.8 below is replaced by the detailed twin section TW (with its decisions TW.0), which was designed and reviewed
   separately on 2026-10-12 before this file was committed. Where E.1-E.7 name a twin id, arm or size that differs from TW, TW holds.

### TW.0 Decisions of the main session on the section's open points (2026-10-12; they override the text below where it differs)

1. **House id** is the league's own `base-<kind>-<name>-<tf>` (`candleague.candidates.accounts`), so the house is exactly the league's `base` account.
2. **League start.** The candidate league's recorded start is 2026-10-11, about 03:00 UTC (`research/fullgrid/DEVIATIONS.md`); every
   sentence that dates the league's forward run uses that date.
3. **Flip size.** Seed 0 also runs E0 at size 1.0 (38 more accounts), so that its E0 row is the league's `<pick id>-flip` account at
   the league's size; all other flip accounts stay at 0.25.
4. **No time cap.** `SELECT_KO.md` waits for the twins and the extra reads (A 8.7, 13 step 3). The twins or the reads may be left out
   only as a dated deviation of A (`research/exitflex/DEVIATIONS.md`, heading `[extra/twins]` or `[extra/reads]`) with one line in the
   sending message; the O8-breach line replaces the fourth fixed line of the twins report.
5. **Names** are as the section writes them: `PREREG_EXITFLEX_EXTRA.sha256` (at O7 this file only; at O8 also the code, the league
   and paperbot files the tests and `check` use, and a copy of A's pin lines; the last line counts), `research/exitflex/extra/out/`,
   `$WORK/<pin8>/extra/`, `$WORK/<pin8>/ds_private/extra/`, one writer of `owner_report_extra.md`, labels TW.n, TW-Tn, TW-Cn, TW-An.
6. **Same message.** `extra_note` in A's `sent.json` also records whether the twins report and the reads report went in the same
   message as `SELECT_KO.md` (yes or no, with the times).
7. **`runner_x` import** for the pure helpers named in TW.3 is accepted (read-only use of A's pinned module; it also loads
   `placebo.py`, which the twins never call).
8. **League and paperbot files** listed at O8 are frozen from O8 until the end of `audit --private`; no edit of them is planned tonight.
9. **Checks.** TW-C1 to TW-C5, the audits TW-A1 to TW-A9 and the rule x lock differential test (TW-T6 b) are confirmed; a TW-C2
   failure removes F11 and F12 from that strategy's x twin and house + V units and blocks nothing else.
10. **DeepSeek keys.** `offered` and `no_fill` are left out of DeepSeek twin rows (with entered, skipped and rejected they would give
    `after_bust`, which A 3 keeps private).
11. **Rows and sizes.** No appendix shows counts of 선택 불가 rows; live size is shown only in Tables 1 and 1b, plus core M_P at live
    size in `twins.json`.
12. **Disk** as written (need measured by `check` on two core picks, 0.8 GB floor, refusal below need + 0.5 GB).
13. **Order.** `twins check` runs after A's select stage and its post-run audits (O8 is expected after the select stage starts), so its
    files never coexist with a running `runner_x` command.
14. The section's own choices (the 거래 적음 bases, the same-side rule with "0" for a zero sign and the median over seeds for flips,
    the per-unit counts from `select.json` and A's DeepSeek files, the lowest-to-highest seed spread, the split card) are confirmed.

## Twin accounts (쌍둥이 계좌)

This section defines the twin accounts promised in A 16.7 item 4. In this section:

* "A" means `research/exitflex/PREREG_EXITFLEX.md` at its pin commit `d038c93` (2026-10-12 11:59:51 UTC, sha256 `f9a71b3514197411a11b2e35c516b905ebe0bc0290d78d61257cefeabe86f01f`).
* "A n" means section n of A.
* `$WORK` is the `work` field of A's `data_pin.json`, and `<pin8>` is as in A 13.

The section answers the owners' message 10 (d): "1차 작업때 기본수치 작업도 같이 해야 커스텀값 수치랑 비교할수있지않을까?".

`twins.py` is one of the modules of A 16.7 item 4 in the sense of A 3 and A 14. That item defines the extra file as the reads and the twins. It also lets their modules read, as a program, the select stage's per-account result files (`results/select/` and `ds_private/results/select/`).

The section is pushed at O7, before A's select stage starts. Its code is pushed at O8, before any A select output is opened (TW.7).

Nothing here changes a rule of A. No gate, placebo, Holm test, default, ledger, report, choice, deadline or league rule changes.

### TW.1 Questions, and what the twins are not

* There are three questions. Each is asked per pool (core 23 picks, DeepSeek 15) and on the select period [2021-01-01, 2024-01-01) only.
  * **Q-T1 (커스텀값 대 기본수치).** Under the same exit, how do A's pick (its custom numbers) and its default-number twin differ? Hold hours and entries come first, then growth.
  * **Q-T2 (같은 쪽인가).** Each variant that is choosable in A's select table moves the picks in some direction. Does it move the default-number twin, the house account and the coin flips the same way?
  * **Q-T3 (리그 다섯 계좌).** What would the league's five account kinds have done over 2021-2023? The kinds are `cand`, `quarter`, `exitonly`, `base` and `flip` (`candleague.candidates.accounts`).
* **Descriptive only.**
  * There is no test, p value, interval, placebo, gate or ledger row.
  * No twin, house or flip account is choosable. Default numbers, the rule-bot exit and the coin flip are not options (A 12). The owners choose only ids of A's choosable rows (A 8.3).
  * No twin figure enters A's gates, A's default (A 8.4), the choice, the confirm or the ledger.
  * Every twin figure is a look in the sense of A 14. None is a hypothesis.
* **One part.** Every account below runs in one stage, named `twins` (`twins_r2` after a select rerun), after A's select stage and its audits. The report goes out with `SELECT_KO.md` or before it (TW.7). No later part follows.
* No minute at or after 2024-01-01 is read.

### TW.2 Units, ids and accounts

Each of A's 38 picks p (`DX.picks()`) is the only pick of its cell (kind, name, tf). There are four unit kinds per pick:

| kind | Korean (the league's name) | unit id | combo | arms | side | sizes | league account |
|---|---|---|---|---|---|---|---|
| x twin | 청산만 바꾼 기본값 | `<pick id>-x` | the cell's default | E0 (the pick's own exit) and A's 88 variants | the signal's | 0.25, 1.0 | `exitonly`, same id, live size |
| house | 기본값 | `base-<kind>-<name>-<tf>` | the cell's default | E0 = `ladder|2` | the signal's | 0.25, 1.0 | `base`, same id, live size |
| house + V | 규칙봇 청산 위에 | the house's (arm = V's id) | the cell's default | A's 88 variants translated onto `ladder|2`; F13.a and F13.b equal E0 and are not run | the signal's | 0.25, 1.0 | none |
| coin flip | 동전 던지기 | s = 0: `<pick id>-flip`; s = 1..19: `<pick id>-flip-x<s>` | the pick's | E0 and A's variants except F11.a, F11.b, F12.a and F12.b | side' | 0.25 only | `flip`, the id of s = 0, run by the league at live size |

* **Default combo.**
  * It is `run.default_combo(kind, name)`, with lists made into tuples as `DX.picks` does (`DX._tup`).
  * For core, these are the `PARAMS` defaults of the hash-checked `param_defs` (`run.core_module`, `DEFS_BC.sha256`).
  * For DeepSeek, these are the `DEFS` defaults of `research/fullgrid/ds_defs.py`.
  * Both files are pinned by A.
  * `candleague.candidates.default_combo` gives the league's `exitonly` and `base` accounts the same values (TW-T1).
* **x twin.**
  * The pick dict is `{**p, "id": p["id"] + "-x", "combo": <default combo>}`. Exit, `exit_index`, kind, pool, name, tf and rank stay the pick's.
  * Each arm is `KX.exit_of_pick(twin, V)`, as on the pick. Mode (a) keeps the pick's take-profit.
  * F11 and F12 read the strategy's own exit computed on the default combo, because the provider passes the pick dict's combo to `native.py` and `native_ds.py`.
* **house.**
  * The pick dict is `{**p, "id": "base-<kind>-<name>-<tf>", "combo": <default combo>, "exit": "ladder|2", "exit_index": 0}`.
  * `kernel.EXITS[0]` is `ladder|2`, which equals `candleague.exits.LIVE_EXIT`. It is a 2 x ATR14 stop with no fixed take-profit and the stepped lock (first lock 10%, steps of 5%, trigger gap 2%; `KX.F13_LOCK`).
* **house + V** is `KX.exit_of_pick(house, V)` on exit index 0 and nothing else.
  * E0 and every mode (a) of F1-F12 give a 2 ATR stop, no fixed take-profit and the lock on: the rule plus the house lock.
  * Every mode (b) of F1-F10 gives a 2 ATR stop, no take-profit and no lock: the rule replaces the lock.
  * F11.b and F12.b give a 2 ATR stop, the strategy's own target where Appendix A defines one (TP_STRUCT), and no lock.
  * **F13.a and F13.b.** `exit_of_pick(house, F13.a)`, `exit_of_pick(house, F13.b)`, `exit_of_pick(house, E0)` and `kernel.exit_args(0)` are equal. `pdata.chart(F13.a)` and `pdata.chart(F13.b)` return the same (rp, PT, PF, QT, cst, cen, qst, qen) as `pdata.chart(E0)`. Both F13 arms are therefore E0 on the house. They are not run, and their rows carry the house E0 figures with the mark "= 기본값 계좌".
  * No A variant runs a rule with the lock on: none of A's 38 picks has a `ladder` exit, and F13 has no rule. Mode (a) on the house is therefore a case that `kernel_x` has not run before. TW-T6 tests it.
* **coin flip.**
  * **The offer.** `off = pdata.offered("select", market)` on the pick's own `PickData`. The flipped offer is a new dict that holds every key of `off`. Three keys are replaced: `side` (int64), `best` (bool) and `lvl` (float64, NaN). Every other column (coin, close, atr, i0, fill, state, tp_idx) and the order stay as they are. The cached `pdata._off["select"]` is never modified, and TW-T2 asserts that it is unchanged afterwards.
  * **side'.** `side'[q] = 1 if hashlib.sha256(f"{acct}|{int(close[q])}".encode()).digest()[0] & 1 else -1`.
    * acct is the unit id of seed s.
    * close[q] is `off["close"][q]`, the signal bar's close in ms: the bar open plus the timeframe. `run.frame` and the league's `chunk_signals` both define it this way.
    * `twins.py` writes this line out itself and imports no `candleague` module at run time. It is `candleague.league.flip_side(acct, close)` (TW-T3, TW-C3). For s = 0 it gives the side that the league's `<pick id>-flip` account takes on the same bar.
  * **best'** is `np.where(side' > 0, pdata.best_l[off["tp_idx"]], pdata.best_s[off["tp_idx"]]).astype(bool)`, where `tp_idx = cst[coin] + i0`. For core this is the `run.best_flags` flag of side' at the signal bar. For DeepSeek both arrays are False ("normal"). The league's flip sizes by the strength of its own side in the same way (`_strength_feats(..., s)` in `chunk_signals`).
  * **F11.a, F11.b, F12.a and F12.b are not run on flips.** A flip of them would need mirrored levels (A 11.2), and A's placebo already checks their timing. The twin code refuses them on a flipped offer.
  * **Each account** is `KX.simulate(market, pdata, V, 0.25, "select", offered=<flipped offer>)`.
    * Every rule reads the position's side. F1, F2, F4-F10, F13 and the q15 variants therefore act for side' as they would for the pick's own trade on that side.
    * **F3 closes a position of side' on the pick's raw signal flag of the side opposite to side'.** `kernel_x` reads `P_SIGS` for a long and `P_SIGL` for a short, on the bars after the entry bar i0.
    * The signal of that bar is then offered at the freed minute with its own side'. It reverses the position or re-enters on the same side, decided by its own coin.
  * **Seeds** are the 20 ids above, fixed now. Nothing else in this section is random.
* **F11 = F3 marks.** On the three F7_RF_ONLY units, F11.a = F3.a and F11.b = F3.b hold for the pick, the x twin and house + V: no level and no target exist, on any combo (A Known limit 11). TW-C5 checks this on the x twin and the house. Flips have no F11.
* **If the strategy's own exit fails on the default combo** (TW-C2 fails for a strategy, or a guard of `native.py` or `native_ds.py` raises while its default-combo unit is built):
  * F11.a, F11.b, F12.a and F12.b are removed from that strategy's x twin and house + V units. The unit is built with `f11=None`, and the twin code refuses F11 and F12 on it.
  * Those cells read "기본수치에서 계산 못 함".
  * Those units are left out of the pooled F11 and F12 rows of their kinds, and each such row shows its unit count.
  * Everything else runs.
  * No A-pinned module is edited to fix such a failure.
* **Accounts.** All run over the select period with A's settings (A 4). The table assumes that no F11 or F12 arm is removed.

| kind | arms | units | sizes | seeds | accounts | core | DeepSeek |
|---|---|---|---|---|---|---|---|
| x twin | 89 (E0 + 88) | 38 | 2 | 1 | 6,764 | 4,094 | 2,670 |
| house E0 | 1 | 38 | 2 | 1 | 76 | 46 | 30 |
| house + V | 86 (88 less F13.a, F13.b) | 38 | 2 | 1 | 6,536 | 3,956 | 2,580 |
| coin flip | 85 (E0 + 84) | 38 | 1 | 20 | 64,600 | 39,100 | 25,500 |
| **total** | | | | | **77,976** | 47,196 | 30,780 |

### TW.3 Data, engine, code, folders and pin

* **Data.**
  * Only A's `data_pin.json` and A's select cut are used.
  * The twin process opens the cut with `DX.open_cut(work, pin_hash, DX.SELECT_CUT_MS)` and builds `DX.Market(<cut>)` and `DX.RealProvider(<cut>, <twin cache>)` on it.
  * On its `Market` it asserts that no array holds a minute at or after 2024-01-01 (`DX.assert_no_minute_at_or_after`, A's audit A5).
  * It never makes the cut and never calls `runner_x.ensure_cut`. A missing or unverified cut is a refusal. It loads no full array.
  * The period is `"select"` only, and the code has no path to `"confirm"`.
* **Engine.**
  * A's modules are imported unchanged: `kernel_x`, `data_x`, `metrics`, `native` and `native_ds`.
  * From `runner_x` only these are used: `Layout`, `gate_pin`, `require_pinned_file`, `read_sha_file`, `sha256_file`, `f11_provider_from_modules`, `try_load_native` and `OWNER_REPORT_LAST_LINE`. No stage function, `Config`, `real_config`, `report_config`, `ensure_cut` or `Store` is used.
  * The F11 provider is registered with `KX.register_f11`, as A's runner does. If the native modules are missing, every command refuses.
  * `KX.warm_up` compiles before the workers fork.
  * Chart data is built as `DX.PickData(market, <unit pick>, rprov, f11=<provider>)`. The x twin and the house share one `PickData`, since their combo is the same; the house arms run on `copy.copy` of it with `pick` set to the house dict. The flips use the pick's own `PickData`.
  * Accounts are `KX.simulate(market, pdata, V, scale, "select")`, with A's forced period-end close. For flips, `offered=` is added.
  * Costs, quality_v1 sizing, brackets, the stop-first rule, the free fill minute after RULE, END and the $5,000 start are as in A 4.
  * The process sets `sys.dont_write_bytecode = True` before it imports A's modules.
  * **Imports at run time.** `run`, `report` and `audit` import no `candleague` module and no `paperbot` module beyond what A's modules import. `twins.py` holds its own copies of three things: the `flip_side` line, the five `ROLE_KO` labels in the dashboard order, and the `base-` id format. Only `check` (TW-C3 (b)) and `test_twins.py` import `candleague`.
* **Code.**
  * `research/exitflex/extra/twins.py` has these commands:
    * `check`;
    * `run [--procs N] [--rerun]`, where N defaults to 3 and a worker takes one pick with its x twin, house and flip units;
    * `report [--rerun]`;
    * `audit [--rerun] [--private]`.
  * The tests are in `research/exitflex/extra/test_twins.py`.
  * A's gate lists `research/exitflex/*.py` with `os.listdir`, which does not recurse. These files therefore lie outside A's pin rule, and A's runner never imports them (TW-T12).
  * Every command calls `gate_pin` with its output captured, so that no second `[pin ok]` line appears. It prints its own line instead: `[twins pin ok] commit <10> pin <pin8> extra <first 8 of the sha256 of PREREG_EXITFLEX_EXTRA.sha256>`.
* **Folders.**
  * Cache: `$WORK/<pin8>/extra/twins/cache/` holds the chart frames of the cut. `check`, `run` and `audit` delete it at their start.
  * Core result files:
    * single accounts: `$WORK/<pin8>/extra/twins/results/<unit id>/<arm>__<q25|q100>.npz`;
    * flips: `$WORK/<pin8>/extra/twins/results/<pick id>-flip/<arm>__q25__s00-19.npz`, with 20 seeds per file;
    * after a rerun, `results_r2/` replaces `results/`.
  * DeepSeek result files use the same layout under `$WORK/<pin8>/ds_private/extra/twins/results/`. Two more private files sit there:
    * `$WORK/<pin8>/ds_private/extra/twins/twins_ds.json`;
    * the twins' private section `$WORK/<pin8>/ds_private/extra/twins/owner_report_extra_twins.md`.
  * **No person or agent opens a twin result file, `twins_ds.json` or the private section file**, core or DeepSeek. Only `twins.py report` and `twins.py audit` read them, as a program, in the way A treats `core_not_choosable.json` (A 8.7) and `ds_private/` (A 3). The private section reaches the owners only inside `owner_report_extra.md` (TW.6).
  * Committed files, all in `research/exitflex/extra/out/`:
    * `twins_check.json`, `twins.json` and `TWINS_KO.md`;
    * the `_r2` files after an A select rerun, and the `_fix<n>` files of TW.10.
  * `twins.py` never writes `$WORK/<pin8>/ds_private/owner_report_extra.md`. It has one writer, the extra file's common part (TW.6).
  * Nothing else is written under `research/exitflex/` or `$WORK/<pin8>/` (TW-A7).
  * No `runner_x.py` command runs while a `twins.py` command runs.
  * Disk freed for the twins never comes from a file under `$WORK/<pin8>/` outside `extra/` and `ds_private/extra/`.
* **Result file.**
  * There is one file per unit, arm and size. For flips there is one file per pick and arm, with the seeds stacked first (`MT.stack_light`).
  * Each file holds `MT.summarize_light(res, edges)`: monthly g over the 36 months, final wallet, counts, exit reasons, hold statistics and maximum drawdown.
  * It also holds `hold_min`: the hold of every entered trade in whole minutes, (exit − entry) / 60,000, as int32 in entry order. In flip files the seeds' holds are concatenated, with `hold_n` per seed.
  * Files are written atomically with `np.savez_compressed`, as A's `Store` does. A resume computes only the missing files.
  * Nothing is summarised or printed until every file exists. Until then the stage prints only progress lines: files done, out of how many.
* **Pin file.** `research/exitflex/PREREG_EXITFLEX_EXTRA.sha256` holds lines `<sha256>  <path from the repo root>`. When a path is listed twice, its last line counts (`read_sha_file`).
  * At O7 it lists this file.
  * At O8 it adds:
    * every `.py` file under `research/exitflex/extra/`;
    * the league and paperbot files that `check` and `test_twins.py` use: `candleague/league.py`, `candleague/candidates.py`, `candleague/exits.py`, `candleague/notify.py` and `paperbot/paramshadow.py`;
    * a copy of every line of `PREREG_EXITFLEX.sha256` as it stands at the O8 commit (A's code, inputs, `data_pin.json` and `timing.json`).
  * Later lines are the outputs of TW.7 and lines renewed under a DEVIATIONS entry (TW.10).
* **Gate.** Every `twins.py` command first refuses unless:
  * `runner_x.gate_pin(Layout())` passes (A's pin and A's data);
  * every file listed in `PREREG_EXITFLEX_EXTRA.sha256` has its listed hash;
  * every `.py` file under `research/exitflex/extra/` (`os.walk`) is listed.
* **Further refusals by command.**
  * `run`, `report` and `audit` refuse unless A's `out/select.json` and `out/SELECT_KO.md` (`_r2` with `--rerun`) are listed in `PREREG_EXITFLEX.sha256` with their present hashes (`require_pinned_file`).
  * `run` and `report` refuse unless `out/twins_check.json`:
    * is listed in `PREREG_EXITFLEX_EXTRA.sha256` with its present hash;
    * says pass;
    * records the sha256 that every file listed in `PREREG_EXITFLEX_EXTRA.sha256` had at check time, each equal to its present hash.
  * `report` refuses unless every result file of TW.2 exists.
  * `run` refuses when free disk is under need + 0.5 GB (TW.8).
* **A change of a listed league or paperbot file** before `audit --private` passes makes every command refuse. The main session either restores the file, or records the change in `research/exitflex/DEVIATIONS.md` (TW.10), renews its line under that entry, and reruns `test_twins.py` and `check`.

### TW.4 Metrics

Everything is at quarter size unless said otherwise, as in A 7:

* wallets are realised at exits;
* W_0 = $5,000;
* g_m and W_m are as in A 7;
* g_m is 0 after a bust.

* **Growth.**
  * For one account, G is the mean of g_m over the 36 months, which equals [ln W_end − ln 5,000] / 36. It is printed as 100 (e^G − 1) % per month.
  * Pooled, G_P is the mean of G over the pool's units.
* **Effect of V in a kind.**
  * M_p(V) = G(V) − G(E0) for the same unit and size (`MT.pick_Mp`), where E0 is the kind's own:
    * x twin: the pick's exit on the default numbers;
    * house + V: `ladder|2`;
    * flip seed s: the pick's exit with side'.
  * For the picks it is A's M_p.
  * A unit with no offered signal has G = 0 and M_p = 0 (A 7).
  * M_P(V) is the mean of M_p(V) over the pool's units, printed as 100 (e^{M_P} − 1) % per month, like A's `M_pct_month`.
* **Hold and entries**, pooled per pool as in A 7:
  * the median hold, and the shares held over 4 h, 8 h and 18 h, over all entered trades of the pool's accounts together, taken from `hold_min` (equal to `MT.hold_stats` on hours);
  * trades entered, signals skipped while holding and signals rejected, each summed over the pool's units;
  * the win share (wins / closed).
* **Flips.**
  * Every figure (G_P, M_P, median hold, share over 4 h, entered) is computed per seed s, pooled over the pool's picks.
  * Over the 20 seeds, the report gives the median, the lowest and the highest.
  * For M_P it also gives the number of seeds with M_P^s(V) > 0.
* **Direction** of a kind against its own E0.
  * x twin, house + V and the picks:
    * hold: 짧아짐 / 길어짐 / 같음, by the sign of median hold(V) − median hold(E0);
    * entries: 늘어남 / 줄어듦 / 같음, by the sign of entered(V) − entered(E0);
    * growth: 나아짐 / 나빠짐 / 같음, by the sign of M_P(V).
  * Flips:
    * hold: by the sign of median_s[medhold_s(V) − medhold_s(E0)];
    * entries: by the sign of median_s[entered_s(V) − entered_s(E0)];
    * growth: by the sign of median_s[M_P^s(V)].
* **Same side as the pick**, for a choosable V and a kind (flips use median_s[M_P^s(V)]):
  * 같은 쪽 when sign M_P(kind) = sign M_P(pick) ≠ 0;
  * 반대 쪽 when both signs are non-zero and opposite;
  * 0 otherwise.
  * Per unit, for the x twin and house + V, the report counts:
    * the units with M_p > 0;
    * the units with sign M_p(unit) = sign M_p(pick) ≠ 0.
  * The pick's M_p comes from `select.json` (`Mp`) for core, and from A's `ds_private/results/select/` files for DeepSeek (private).
* **거래 적음.**
  * A unit is marked when its own E0 entered fewer than 30 trades at quarter size in the 36 months.
  * The house + V units use the house E0. Flip units use seed 0's E0.
  * The unit is named in its pool's list and kept in every pooled figure. Nothing is dropped.
* **Live size (1.0)** appears in Tables 1 and 1b (TW.5). For core choosable rows, `twins.json` also carries M_P at live size for the x twin and house + V, reported only. The picks' live M_P is `select.json`'s `live.M_pct_month`.

### TW.5 The report

* **Inputs.** `twins.py report` computes no account. It reads only:
  * the twin result files of E0, the house E0 and the choosable ids;
  * A's `select.json` (`_r2` with `--rerun`):
    * per pool, `eligible_ids`;
    * on those rows, `name_ko`, `hold`, `entered` and `entered_e0`;
    * for core, also `M`, `M_pct_month`, `Mp` and `live`;
  * A's per-account result files of the 38 picks, as a program (A 3; A 16.7 item 4): E0 at both sizes, and the choosable ids at quarter size. Core files are under `$WORK/<pin8>/results/select/` and DeepSeek files under `$WORK/<pin8>/ds_private/results/select/` (`select_r2/` with `--rerun`).

  It reads no field or file of a variant marked "선택 불가", and never `core_not_choosable.json`, `select_ds.json`, A's owner reports or any confirm file.
* **Rows**, per pool:
  * The rows are 지금 청산(E0), then the ids of `eligible_ids` in A's canonical order. Rows are never ranked by a figure.
  * A pool with no choosable id has the E0 row only.
  * No "선택 불가" row is shown, in any kind or pool. Their figures stay in the result files.
  * These cells read as follows:
    * flips under F11 and F12: "동전 없음(계산 안 함)";
    * the house under F13.a and F13.b: "= 기본값 계좌";
    * a unit kind whose F11 and F12 were removed (TW.2): "기본수치에서 계산 못 함", with the unit count of the row.
  * F11 rows carry "(F7_RF_ONLY 3칸은 = F3.a / = F3.b)":
    * in the pick column, as in A;
    * in the x twin and house + V columns, only where TW-C5 passed.
* **Files.**
  * `out/twins.json` holds:
    * the core figures;
    * for DeepSeek, only the keys of `DS_TWIN_ALLOWED` (TW.6);
    * this file's O7 commit and the sha256 of `PREREG_EXITFLEX_EXTRA.sha256`;
    * the sha256 and file times (UTC) of A's `select.json` and `SELECT_KO.md`;
    * the run's start and end (UTC);
    * the account and file counts of TW.2 and TW.8;
    * the ids marked 거래 적음;
    * the sha256 of `twins_ds.json` and of `owner_report_extra_twins.md`.
  * `out/TWINS_KO.md` is the Korean report.
  * `twins_ds.json` holds the DeepSeek money and the money-derived counts.
  * `owner_report_extra_twins.md` is the twins' part of the owners' private view (TW.6).
* **`TWINS_KO.md`** starts with the fixed lines and the glossary, once. Then come the core section and the DeepSeek section, whose heading contains "딥시크". It ends with the last line.
  1. **Fixed lines** (verbatim):
     * "이 표로는 고르지 않습니다. 고르는 건 A 표(SELECT_KO.md)의 '선택 가능' 줄에서만 하시고, 이 표는 그 줄이 기본수치와 동전 계좌에서도 같은 쪽으로 움직이는지 참고로만 보세요."
     * "고를 수 있는 것은 A 표(SELECT_KO.md)의 '선택 가능' 줄의 청산 id뿐입니다. 숫자를 기본수치로 바꾸기, 규칙봇 청산으로 바꾸기, 동전 계좌는 이번 선택지에 없습니다(A 12)."
     * "'규칙봇 청산 위에' 줄은 실제로 돌고 있는 규칙봇의 청산을 바꾸자는 제안이 아닙니다. 규칙봇은 이번 연구 범위 밖입니다(A 12)."
     * "이 계좌들의 정의는 A 계획이 고정된 뒤, A 고르기 계산이 시작되기 전에 고정했고, 계산 코드는 A 고르기 결과를 열기 전에 고정했습니다. 참고용이고, 시험, 가짜 규칙 비교, 통과 기준이 없습니다."
     * "A의 통과 기준(코어 23개 중 14개·딥시크 15개 중 9개 픽에서 나아짐, 가짜 규칙 비교, 진입 횟수)은 쌍둥이 계좌에 적용되지 않습니다. 쌍둥이에는 통과·탈락이 없습니다."
     * "2021~2023년은 커스텀값과 지금 청산을 고른 기간입니다. 이 기간에 커스텀값이 기본수치보다 좋아 보이는 건 당연하고 증거가 아닙니다."
     * "커스텀값이 기본수치보다 나은지는 앞으로 쌓이는 리그 기록으로만 알 수 있습니다. A 계획대로 리그를 다시 시작하면 그 비교 계좌(기본값·청산만 바꾼 기본값)가 없어지므로, 이 비교를 계속하려면 따로 정해야 합니다(A 11.3)."
     * "2024~2026 숫자는 없습니다."
  2. **Glossary** (verbatim):
     * "커스텀값: 지금 후보 리그 픽의 숫자(5년 연구에서 고른 숫자)."
     * "기본수치: 규칙봇 숫자(매매법마다 원래 정해진 기본 설정값)."
     * "지금 청산(E0): 지금 후보 리그 픽의 청산(3R 고정 익절과 그 손절 등)."
     * "규칙봇 청산: 2 ATR 손절 + 계단 잠금(순 ROE, 곧 수수료를 뺀 증거금 대비 수익이 12%에 닿으면 10%를 잠그고, 17%면 15%, 22%면 20% ...)."
     * "청산만 바꾼 기본값 계좌: 기본수치 + 지금 청산(리그의 같은 이름 계좌)."
     * "기본값 계좌: 기본수치 + 규칙봇 청산(리그의 같은 이름 계좌)."
     * "규칙봇 청산 위에: 기본값 계좌에 A의 청산 규칙을 얹은 것. '.a'는 계단 잠금과 그 규칙을 함께, '.b'는 잠금 없이 2 ATR 손절과 그 규칙(11번·12번 '.b'는 매매법 자체 목표가 포함). 13번(규칙봇 계단 잠금)은 기본값 계좌와 같아 따로 계산하지 않았습니다."
     * "동전 던지기 계좌: 커스텀값 픽과 같은 신호 시각에 방향만 동전으로 정한 계좌. 20번 따로 던졌고, 리그의 동전 계좌는 그중 1번째 동전입니다. 리그 계좌는 실제 크기로 돌고, 이 보고서는 1/4 크기만 계산했습니다. 11번(매매법 자체 청산)과 12번(9가지 청산 동시 적용)은 동전 계좌로 계산하지 않았습니다."
     * "이 표의 '기본값 계좌'는 리그 화면의 그 계좌입니다. A 표의 '기본값'(답이 없을 때 자동으로 넣는 청산)과 다릅니다."
     * "거래 적음: 지금 청산으로 3년 동안 1/4 크기에서 진입이 30번 미만인 칸. 모든 합계에 그대로 들어 있습니다."
  3. **Per pool, in this order** (hold and entries before any growth figure, A 8.2). The DeepSeek section has items a, b, c and h only, plus the DeepSeek line of item i.
     * **a. 한눈에 보기 (1) 보유 시간과 진입 (참고용, 고르는 표 아님).** There is one line per choosable id. It gives the direction of hold, then of entries, for 픽 / 청산만 바꾼 기본값 / 규칙봇 청산 위에 / 동전. The line under it reads: "픽 칸은 '선택 가능' 줄만 보여 주므로 진입은 늘 '늘어남' 또는 '같음'입니다. A의 통과 기준을 넘은 줄만 남겼기 때문이고, 증거가 아닙니다."
     * **b. 표 2, 보유 시간과 진입 (지금 청산 → 각 청산).**
       * The rows are as above.
       * There are four kind columns:
         * 픽 (A's figures, equal to `select.json`);
         * 청산만 바꾼 기본값;
         * 규칙봇 청산 위에, whose E0 is the 기본값 계좌;
         * 동전 20번.
       * Each kind gives the median hold, the share over 4 h, trades entered, and the change in entries in percent against that kind's E0.
       * The flip column shows median_s of each value and median_s of the per-seed percent change in entries.
     * **c. 표 1, 리그 다섯 계좌 2021~2023 (보유 시간과 진입).**
       * Rows follow the dashboard's order (`ROLE_KO`):
         * 후보: A's E0 at 1.0;
         * 1/4 크기: A's E0 at 0.25;
         * 청산만 바꾼 기본값: x twin E0, at 1.0 and at 0.25;
         * 기본값: house E0, at 1.0 and at 0.25;
         * 동전 던지기(리그와 같은 동전, 1/4 크기): flip seed 0 E0;
         * 동전 20번(1/4 크기): the median over seeds, with [lowest ~ highest].
       * The columns are size, median hold, the shares over 4 h, 8 h and 18 h, entered, skipped while holding, rejected and win share.
       * Fixed lines under it:
         * "리그는 이 다섯 계좌를 2026-10-11부터 앞으로 돌리고 있습니다. 이 표는 같은 정의의 계좌를 2021~2023년에 대해 연구 계산기로 다시 계산한 것이고, 리그 기록이 아닙니다."
         * "리그의 동전 계좌는 실제 크기로 돌고, 이 표의 동전은 1/4 크기입니다."
         * "5년 연구 성적표의 같은 칸 숫자와 다릅니다. 이번 계산은 2021~2023년, 한 번에 한 자리, 1분봉이고, 자리를 잡고 있는 동안 놓친 신호까지 셉니다."
         * "이 표의 차이로 리그 계좌를 고르거나 바꾸지 않습니다."
     * **d. 한눈에 보기 (2) 성장 (코어만).**
       * There is one line per choosable id. It gives the growth direction for:
         * 픽;
         * 청산만 바꾼 기본값, with "23칸 중 나아진 칸 n";
         * 규칙봇 청산 위에, with "23칸 중 나아진 칸 n";
         * 동전, with "20번 중 나아진 번 n".
       * The lines under it read:
         * "픽 칸의 성장은 늘 '나아짐'입니다. A의 통과 기준을 넘은 줄만 남겼기 때문이고, 증거가 아닙니다."
         * "효과가 없어도 대략 절반은 '나아짐'으로 나옵니다. 같은 쪽이라는 것만으로는 증명되는 것이 없습니다."
         * "'나아짐'이나 '같은 쪽'의 개수를 더해 점수처럼 쓰지 마세요."
         * "동전 계좌에서도 나아졌다고 그 청산이 좋다는 증거는 아닙니다. 동전 계좌는 픽과 같은 시각에 들어가므로, 그 시각의 시장 움직임 덕분일 수도 있습니다."
     * **e. 표 3, 한 달 계좌 성장 차이 (1/4 크기, 코어만).**
       * Table 3a:
         * The E0 row gives each kind's G_P.
         * A V row gives each kind's M_P against its own E0, in % per month. The pick column is `select.json`'s `M_pct_month`, and flips show the median with [lowest ~ highest].
         * It also gives 같은 쪽 / 반대 쪽 / 0 for 청산만 바꾼 기본값, 규칙봇 청산 위에 and 동전.
       * Table 3b, per V:
         * the units with M_p > 0 (n/23), for the x twin and for house + V;
         * the units on the same side as their pick (n/23), for both kinds;
         * the flip seeds with M_P > 0 (n/20).
     * **f. 표 1b, 리그 다섯 계좌 2021~2023 (돈, 코어만).** The rows are those of Table 1. The columns are monthly growth (% per month), the median final multiple, the median maximum drawdown and the number of busts.
     * **g. 표 4, 커스텀값 대 기본수치 (같은 청산, 1/4 크기, 코어만).**
       * The rows are E0 and the choosable ids.
       * The columns are G_P of the picks, G_P of the x twins, and the units where the pick's G is above its twin's (n/23).
       * Lines under it:
         * "커스텀값은 이 기간을 보고 고른 숫자라 픽이 앞서는 게 당연합니다."
         * "기본수치가 앞서는 줄이 있어도 리그 픽의 숫자를 바꾸는 근거가 되지 않습니다."
     * **h. 거래 적음.** The list starts with "거래 적음(지금 청산으로 3년 동안 진입 30번 미만, 모든 합계에 그대로 들어 있음):", followed by the unit ids per kind. Unit ids appear only in this list and in no line that holds a figure.
     * **i. DeepSeek line** (DeepSeek section only): "딥시크는 거래 수·승률·보유 시간만 적습니다. 딥시크의 돈 숫자는 대화창에서만 보여 드리는 비공개 보고서에 있습니다."
  4. **Last line** (verbatim): "답은 A 표의 id(예: F9.a)로만 해 주세요. 이 보고서의 계좌 이름이나 숫자로 답하지 마세요."

### TW.6 DeepSeek (D11, A 3)

* **What is never shown.** No DeepSeek money figure, money-derived count or p value appears in any of these:
  * `twins_check.json`, `twins.json`, `TWINS_KO.md` or their `_r2` and `_fix` files;
  * an entry of `research/exitflex/DEVIATIONS.md`;
  * a Telegram message, an agent packet or a note to another session.

  Money-derived counts include units or seeds with M > 0, same-side counts and growth words.
* **The twin whitelist** `twins.DS_TWIN_ALLOWED` lists the only keys that a DeepSeek row of a committed twin file may hold:
  * labels: `id`, `kind`, `size`, `name_ko`, `order`, `same_as_f3`, `mark`, `n_units`, `thin_ids`;
  * counts: `entered`, `entered_e0`, `entered_change_pct`, `skipped`, `skipped_e0`, `rejected`, `closed`;
  * `win_share`;
  * `hold` and `hold_e0`, nested `median`, `p90`, `share_gt4`, `share_gt8` and `share_gt18`;
  * `reasons` and `reasons_e0`, nested A's `MT.REASONS`, LIQ included;
  * `dir_hold` and `dir_entries`;
  * for flips, nested `seed_median`, `seed_min` and `seed_max` of hold and entered.

  These keys are never allowed: `offered`, `no_fill`, `after_bust`, `bust`, `busts`, `w_end`, `g`, `G`, `M`, `M_pct_month`, `max_dd`, `final_multiple`, `n_pos`, `same_side` and `dir_growth`, and no p value. `offered` and `no_fill` are left out because, with the allowed counts, they would give `after_bust` by subtraction. The checks of A 14, A8 (1) are made by this whitelist (TW-T10, TW-A6), because `audit-file` makes only the free-text check on files not named like a stage file.
* **Where the figures live.**
  * DeepSeek result files, `twins_ds.json` and `owner_report_extra_twins.md` lie under `$WORK/<pin8>/ds_private/extra/twins/`.
  * Only `twins.py report` and `twins.py audit` read them, as a program.
* **The private section** (the owners' relaxation as A 3 extends it to 16.7 item 4).
  * Contents, for the DeepSeek pool, on E0, the house E0 and the DeepSeek choosable rows only:
    * Table 1b;
    * card d with n/15 and n/20;
    * Tables 3a, 3b and 4 with n/15;
    * the three growth lines of item d.
  * It holds no p value (none exists) and no "선택 불가" row.
  * Every heading carries "[비공개]" right after its `#` marks, and every prose line starts with "[비공개] ". Every table row's first cell reads "비공개" (separator rows excepted). No line of 20 or more characters that holds a letter, digit or Hangul is therefore equal to a line of a committed file. The glossary and the fixed lines are not repeated there.
  * `twins.py report` writes it only to `owner_report_extra_twins.md` and records its sha256 in `twins.json` and `twins_ds.json`.
* **The single writer of `owner_report_extra.md`** (the extra file's common part) does four things:
  * it includes the twins section verbatim;
  * it ends the file with `runner_x.OWNER_REPORT_LAST_LINE`;
  * it records the whole file's sha256 in a committed file of `research/exitflex/extra/out/` before the file is shown;
  * that value is the one the main session writes into `sent.json` as `ds_owner_report_extra_sha256` (A 8.7).
* **Showing it.**
  * It is shown only in the chat with the owners, in the same turn as the sending of `SELECT_KO.md` or before it. It is never committed, copied or forwarded (A 3).
  * Owner messages that quote it are redacted with `[딥시크 금액 삭제]` before they go into a committed file (A 3).

### TW.7 Order of work

1. **O7, before A's select stage is started** (A 13 step 2; A 17 O7). This file (all of `PREREG_EXITFLEX_EXTRA.md`) and a first `PREREG_EXITFLEX_EXTRA.sha256` that lists it are committed and pushed. The commit message carries the time in UTC and KST. This step has no fallback, because A's select stage is not started before this push.
2. **O8, before any A select output is opened** (`select.json`, `SELECT_KO.md`, any per-account result file, the private DeepSeek report) **and before any `twins.py` command touches real data** (A 17 O8).
   * `test_twins.py` passes on synthetic data. It prints pass or fail and counts only.
   * `twins.py`, `test_twins.py` and `PREREG_EXITFLEX_EXTRA.sha256`, extended as in TW.3, are committed and pushed.
   * If an A select output is opened before this push, that breaches A's O8. It is written, dated, into `research/exitflex/DEVIATIONS.md`. The main session then decides one of two things and records the decision in the same entry:
     * the twins are dropped (step 9);
     * they are sent with the first line "쌍둥이 계좌의 정의는 A 고르기 계산 전에 고정되었고, 코드는 A 고르기 결과를 연 뒤에 고정되었습니다.", which replaces the fourth fixed line.
   * The O7 and O8 commits (hash and UTC time), and the UTC time and HEAD of A's select `[pin ok]` line, go to `sent.json` `extra_note` (A 8.7, A 16.7 item 4), not into this file.
3. **`twins.py check`.**
   * It runs after O8 and after A's `make-cut`, at one of two times:
     * before A's select stage starts, if O8 was pushed by then;
     * otherwise after A's select stage and its audits have ended.
   * It never runs while a `runner_x.py` command runs.
   * It writes `out/twins_check.json` (pass or fail per check, counts only, and the recorded hashes of TW.3).
   * `runner_x.py audit-file --path research/exitflex/extra/out/twins_check.json` passes.
   * Its sha256 is appended to `PREREG_EXITFLEX_EXTRA.sha256`, then committed and pushed.
4. **A's select stage** runs and its audits pass. The sha256 of `select.json` and `SELECT_KO.md` are appended to `PREREG_EXITFLEX.sha256`, committed and pushed (A 13 step 3).
5. **`twins.py run`** starts after step 4; it refuses to start before. It prints progress only.
6. **`twins.py report`**, then **`twins.py audit`** (TW-A1 to TW-A8, pass or fail only), then:
   * `python research/exitflex/runner_x.py audit-file --path research/exitflex/extra/out/twins.json --path research/exitflex/extra/out/TWINS_KO.md`;
   * each file must print pass;
   * the sha256 of `twins.json` and `TWINS_KO.md` are appended to `PREREG_EXITFLEX_EXTRA.sha256`, committed and pushed.

   A FAIL at any point blocks the commit and the send.
7. **Private.** The single writer assembles `owner_report_extra.md` after the reads and the twins are done and records its sha256 (TW.6). Then `twins.py audit --private` (TW-A9) passes.
8. **Send.**
   * The main session checks the sha256 of `owner_report_extra.md` against the committed one.
   * In the chat with the owners, it shows `owner_report_select.md` and `owner_report_extra.md`, in the same turn as the sending of `SELECT_KO.md` or before it.
   * It sends `TWINS_KO.md` in the same message as `SELECT_KO.md`, by the same channel.
   * A's 48 h clock starts at that sending (A 8.3, 8.7).
   * Right after sending, and before reading any answer, the main session writes A's `out/sent.json` under A 8.7: `extra_note`, `extra_shown_utc` and `ds_owner_report_extra_sha256`. It runs A8 on that file, appends its sha256, commits and pushes.
9. **No cap; dropping.**
   * `SELECT_KO.md` is not sent before steps 6 and 7 are done (A 8.7, A 13 step 3).
   * If the twins cannot be finished without changing a rule of this section, the main session waits, or drops the twins for this select step.
   * A drop is a deviation of A 16.7 item 4. It is written, dated and with its reason, into `research/exitflex/DEVIATIONS.md`, and `audit-file` passes on that entry before `SELECT_KO.md` is sent.
   * The message that sends `SELECT_KO.md` then carries the line "이번 고르기 표에는 쌍둥이 계좌 보고서가 함께 가지 않습니다. 이유: <이유>".
   * Dropped twins are not sent while any pool's deadline runs. Whether they are shown after `choice.json` is hashed is decided then and recorded in `research/exitflex/DEVIATIONS.md`.
   * A late or dropped twin report changes no deadline, default or choice rule of A.
10. **A select rerun (A 14).** The twins are rerun on the `_r2` files under the same rules.
    * If a file named by the A lines of `PREREG_EXITFLEX_EXTRA.sha256` changed, the twin gate refuses. Those lines are renewed under a dated entry in `research/exitflex/DEVIATIONS.md`. Then `check`, `run --rerun` (`results_r2/`) and `report --rerun` follow.
    * If no such file changed, only `report --rerun` runs, from `select_r2.json` and A's `select_r2/` files.
    * Either way the rerun writes `twins_r2.json`, `TWINS_KO_r2.md` and `owner_report_extra_twins_r2.md`. They go out with `SELECT_KO_r2.md` under steps 6 to 9.

### TW.8 Compute and disk

* **Work.** There are 77,976 accounts (TW.2) and 76 chart builds with the F11 arrays: 38 on the default combos, shared by the x twin and the house, and 38 on the picks' combos for the flips.
* **Basis.** The design memo's probes measured these with A's kernel on the full 1m folder (2020-01-01 to 2026-09-30), with period `"select"` and the forced end at 2024-01-01. They did not use this code and are not re-measured here.
  * A twin or house account takes about 0.021 CPU-s: 2.4 CPU-min for 6,840 accounts, which are 38 x 89 x 2 x twin accounts and 76 house accounts.
  * A flip account takes about 0.012 CPU-s: 84 s per seed for 38 picks x 89 arms x 2 sizes.
  * 38 builds take about 2 CPU-min.
* **Estimate.**
  * `run` takes about 25 CPU-min:
    * about 5 for the x twin, house and house + V (13,376 accounts);
    * about 13 for the flips (64,600 accounts);
    * about 4 for the 76 builds;
    * about 2 for writing.
  * `check` takes about 8-10 CPU-min: 76 builds, TW-C3's 6,460 accounts, and the native re-derivations of TW-C2.
  * `report` takes about 3 CPU-min.
  * `audit` takes about 6-8 CPU-min, which includes 76 builds for TW-A4.
  * The total is about 45 CPU-min (0.75 CPU-h).
* **Wall time.**
  * `run` with 3 processes takes about 10 min on free CPUs, or 15-30 min on the shared machine (4 CPUs, load 1-3).
  * `check` takes about 5-10 min, and `report` with `audit` about 5-10 min.
* **Memory.**
  * Each worker holds two `PickData` (the default combo and the pick's combo), each with one chart set. That is up to about 300 MB per worker (A's `PickData.chart` keeps one set of up to about 100 MB).
  * The cut's minute arrays are shared after the fork.
  * In all this is about 1.5 GB. It was not measured beside the jobs already running.
* **Disk.**
  * There are 16,606 result files: 13,376 single-account files and 3,230 flip files of 20 seeds each.
  * `check` measures the compressed size of real result files. It writes the E0 and F3.a files of the x twin (both sizes) and of the flip, for the two core picks with the most and the fewest offered select signals, into `$WORK/<pin8>/extra/twins/check_tmp/`, which it deletes at its end. It sets need = max(0.8 GB, 1.5 x (13,376 x mean single-file size + 3,230 x mean flip-file size) + 0.15 GB of cache). Only need, rounded up to 0.1 GB, goes into `twins_check.json`.
  * `run` refuses when less than need + 0.5 GB is free on the filesystem of `$WORK`. It checks at its start and at every resume.
  * Free disk was 3.2 GB at 2026-10-12 12:18 UTC and has moved between 2.3 and 3.8 GB. A's select stage uses disk before the twins run.
  * There is no fallback with fewer seeds or arms. Short disk is a refusal (TW.10).

### TW.9 Tests, check and audits

Each prints pass or fail and counts of cases only, never a performance figure.

**Synthetic tests** (`test_twins.py`), which pass before O8:

* **TW-T1, league definitions.** This test reads `candidates.json` and code; it reads no market data.
  * For each pick, `candleague.candidates.accounts(candleague.candidates.load())` holds:
    * an `exitonly` account `<pick id>-x` with the pick's kind, name, tf and exit, and a combo equal to the x twin's (lists as tuples);
    * a `base` account `base-<kind>-<name>-<tf>` with the default combo and `LIVE_EXIT`, equal to the house. `kernel.EXITS[0][0]` is `"ladder|2"`;
    * a `flip` account `<pick id>-flip` with the pick's combo and exit.
  * `run.default_combo` equals `candleague.candidates.default_combo` for the 16 strategies.
  * The x twin's `exit_of_pick` for E0 equals `kernel.exit_args` of the pick's exit.
  * All twin ids are distinct, and no flip id with s ≥ 1 is a league account id.
  * `twins.py`'s copies equal the league's: the `ROLE_KO` labels in order, the `base-` id format, and the `flip_side` line (with TW-T3).
* **TW-T2, flip side and leverage group.** This runs on synthetic offers: core with best flags that differ by side, and DeepSeek.
  * side' follows TW.2 for every signal.
  * best' is `best_l` or `best_s` at `tp_idx` by side' for core, and False for DeepSeek.
  * Every other column and the order are unchanged, `lvl` is NaN, and the flipped offer is a new dict.
  * `pdata._off["select"]` is unchanged afterwards.
  * A flipped run of F11.a, F11.b, F12.a or F12.b is refused.
* **TW-T3, seed 0 is the league's flip.**
  * For the 38 pick ids, s = 0..19 and 1,000 synthetic bar closes, `twins.flip_side` equals `candleague.league.flip_side(<unit id>, close)`.
  * On a synthetic frame, `pdata.offered("select")["close"]` equals the bar open plus the timeframe, which is the time the league hashes.
* **TW-T4, F3 on side'.** This runs on a synthetic world, for F3.a and F3.b and both sides.
  * A flipped position closes at the first check close where the pick's raw flag of the side opposite to side' is true. It never closes on a raw flag of its own side.
  * A flip with side' = −raw is not closed by its own entry bar's raw flag. Its first F3 exit is at the next later bar that holds the opposite-side raw flag.
  * The bar's signal then enters at the freed minute with its own side'. One case reverses, and one re-enters on the same side.
* **TW-T5, flip identity.**
  * With side' set to the raw side, the flip path equals the pick's `KX.simulate` trade for trade (status, P&L, exit times, reasons, leverage), on every flip arm, at 0.25 and at 1.0.
  * With side' set to minus the raw side, the leverage group is the other side's.
* **TW-T6, translation onto ladder|2.**
  * (a) Exit tuples and charts:
    * `exit_of_pick(house, V)` gives the tuples of TW.2 for E0, every mode (a) and mode (b) variant, F11.b and F12.b;
    * `exit_of_pick(house, F13.a)`, `exit_of_pick(house, F13.b)`, `exit_of_pick(house, E0)` and `kernel.exit_args(0)` are equal;
    * `pdata.chart(F13.a)` and `pdata.chart(F13.b)` return the same eight values as `pdata.chart(E0)`;
    * one synthetic run of F13.a, F13.b and E0 on the house gives equal results trade for trade;
    * the twin code runs neither F13 arm on the house and copies E0's figures to their rows.
  * (b) **Rule × lock differential.**
    * Setting: random synthetic worlds of 15m and 1h picks with exit index 0, both sides, every family at its middle parameter, F11 and F12 through a synthetic native provider, modes a and b.
    * `KX.simulate` must equal A's plain-Python `ref_trade` (`test_exitflex.py`) trade for trade: minute, reason, price, and wallet change to 1e-9.
    * `ref_trade` uses `lock=(True, 0.10, 0.05, 0.02)` in mode a and the lock off in mode b.
    * LOCK, RULE, SL, END and (for F11.b) TP exits must all occur.
* **TW-T7, E0 parity.** On synthetic worlds with no forced end, the x twin's E0 and the house E0 through `KX.simulate` equal `kernel.account` with `kernel.exit_args` of the pick's exit and of index 0. Statuses, P&L, exit times, reasons, leverages and the final wallet all match.
* **TW-T8, metrics and marks.**
  * These equal hand computations: G, M_p, M_P, the flip seed statistics, the flip direction rules of TW.4, and the hold statistics from `hold_min`. The hold statistics also equal `MT.hold_stats` on hours.
  * A unit with no offered signal has M_p = 0.
  * 거래 적음 is set at 29 trades entered and not at 30.
  * The same-side marks handle a zero.
* **TW-T9, report rules**, on a synthetic `select.json` and synthetic result files:
  * the rows are E0 and `eligible_ids` in canonical order;
  * a figure of a "선택 불가" id planted in any kind is refused;
  * a pool with no choosable id shows E0 only;
  * the special cells of TW.5 read as written, including a synthetic TW-C2 removal;
  * the pick column equals `select.json`;
  * the parts come in the order of TW.5, so no growth figure comes before Table 2 and Table 1;
  * the fixed lines and the last line are verbatim;
  * the DeepSeek section has no item d, e, f or g.
* **TW-T10, D11.**
  * The following, planted in a DeepSeek row of `twins.json` or in a DeepSeek section of `TWINS_KO.md`, are refused: a DeepSeek money figure, a money-derived count, a p value, or any of the keys `bust`, `after_bust`, `offered`, `no_fill`, `n_pos`, `same_side` and `dir_growth`. The checks are the twin whitelist, `MT.ds_text_problems` and `MT.audit_text`.
  * Counts, win shares, hold hours, exit reasons and the hold and entry words pass.
  * A private file is refused outside `$WORK/<pin8>/ds_private/extra/`, and anywhere inside the repository.
  * The private section holds no p value and no "선택 불가" row. Its headings, prose lines and table rows carry the private markers of TW.6. None of its lines of 20 or more characters equals a line of the committed outputs.
* **TW-T11, isolation, period and cut.**
  * A synthetic run writes only the paths of TW.3. A listing with sha256 of the temporary A folders is equal before and after.
  * Asking for the confirm period raises an error.
  * A missing cut is a refusal, and the cut is never made.
  * An array with a minute at or after 2024-01-01 stops the run.
* **TW-T12, gate, resume and determinism.**
  * The gate refuses in each of these cases:
    * a changed A line;
    * a changed extra file;
    * a changed listed league or paperbot file;
    * an unlisted `.py` under `research/exitflex/extra/`;
    * an unpinned `select.json`;
    * a `twins_check.json` whose recorded hashes differ from the present ones;
    * free disk below need + 0.5 GB (simulated).
  * The gate prints `[twins pin ok]` and no `[pin ok]` line.
  * A's `gate_pin` and `pin_lines` on a temporary layout ignore `extra/`.
  * Deleting result files and resuming gives identical arrays.
  * Two report runs give identical files.

**Real-data check** (`twins.py check`), on the cut, before `run`:

* **TW-C1.** The 38 x twin E0 and the 38 house E0 accounts through `kernel_x`, with no forced end, equal `kernel.account` at both sizes. This is A's T1 on the twins.
* **TW-C2.** This is A's T6 on the default combos.
  * `native.py`'s re-derived entries equal `run.signals` bar for bar for the N13_3OUTSIDE and N19_FIB_CHOP x twins.
  * `native_ds` matches `run.signals` in the same way on the 15 DeepSeek x twin cells.
  * Every final DeepSeek x twin signal bar receives its levels.
  * A failure, or a native guard error while a unit is built, removes F11 and F12 from that strategy's x twin and house + V units (TW.2). It is recorded per strategy and does not fail `check`.
* **TW-C3.**
  * (a) With side' set to the raw side, the flip path equals the pick's `KX.simulate` at 0.25 on all 85 flip arms for the 38 picks.
  * (b) For every offered signal of the 38 picks, `twins.flip_side` for s = 0 equals `candleague.league.flip_side(<pick id>-flip, close)`. `check` imports `candleague.league` for this.
* **TW-C4.** `test_twins.py` (TW-T1 and TW-T3) runs again, in a subprocess, at the check's commit.
* **TW-C5.** On the three F7_RF_ONLY units, the x twin and the house + V F11.a equal F3.a, and F11.b equals F3.b, trade for trade at q25. A failure for a kind drops the mark from that kind's rows and does not fail `check`.

`check` passes when TW-C1, TW-C3 and TW-C4 pass. TW-C2 and TW-C5 decide removals and marks only.

**Audits** (`twins.py audit`), after `run` and `report`, before anything is committed or sent:

* **TW-A1** (as A2): for every account, offered = entered + skipped + rejected + no fill + after bust.
* **TW-A2** (as A4): every final wallet equals $5,000 plus the sum of its wallet changes, to 1e-9 relative.
* **TW-A3** (as A5): no array loaded by the twin process holds a minute at or after 2024-01-01.
* **TW-A4** (as A6):
  * The x twin E0 and the house E0 with the forced end equal `kernel.account` up to the position that END closes.
  * The picks' E0 at both sizes is recomputed in the twin process (76 accounts). It must equal A's `E0__q25` and `E0__q100` result files in final wallet and counts.
* **TW-A5.**
  * F13.a and F13.b were not run on the house. Their rows carry the house E0 figures and the mark.
  * No flip file exists for F11 or F12. No F11 or F12 file exists for a unit removed under TW-C2.
  * On the seven units whose pick has a 2 ATR stop (`kernel.exit_args(exit_index)[0] == 2.0`), the x twin's F13.b equals the house E0 account for account at both sizes. Both are `ladder|2` on the default combo.
* **TW-A6** (as A8), on `twins_check.json`, `twins.json`, `TWINS_KO.md` and their `_r2` and `_fix` files:
  * the twin whitelist runs on DeepSeek rows, `MT.ds_text_problems` on DeepSeek sections, and `MT.audit_text` on free text;
  * `runner_x.py audit-file` passes on each (A 14);
  * `twins_ds.json` and `owner_report_extra_twins.md` lie outside the repository, are not tracked by git, hold no p value, and have the sha256 recorded in `twins.json`;
  * no line of the private section of 20 or more characters that holds a letter, digit or Hangul appears in a committed output of this section;
  * `TWINS_KO.md` ends with the last line of TW.5.
* **TW-A7, isolation.** Two listings (path, size, sha256) must be the same at the start and at the end of each `twins.py` command:
  * `research/exitflex/` outside `extra/`;
  * `$WORK/<pin8>/` outside `extra/`, `ds_private/extra/` and `ds_private/owner_report_extra.md`.
* **TW-A8, consistency.**
  * Every number in `TWINS_KO.md` equals `twins.json`.
  * The pick column equals `select.json`.
  * On core choosable rows, the picks' M_p recomputed from A's files equals `select.json`'s `Mp`, id by id, to 1e-12.
  * For DeepSeek, the picks' hold and entered counts recomputed from A's `ds_private/results/select/` files equal `select.json`'s DeepSeek rows.
  * Every pooled figure recomputes from the result files.
* **TW-A9 (`audit --private`)**, after the single writer has assembled `owner_report_extra.md` and before it is shown:
  * the file exists at `$WORK/<pin8>/ds_private/owner_report_extra.md` and lies outside the repository;
  * `git ls-files` lists no `owner_report_*` file;
  * it contains `owner_report_extra_twins.md` verbatim, whose sha256 equals the one in `twins.json`;
  * it holds no p value (A's pattern);
  * its last line equals `runner_x.OWNER_REPORT_LAST_LINE`;
  * no stripped line of it of 20 or more characters that holds a letter, digit or Hangul appears in any of: a committed output of this section, a file of A's A8 scope, or `research/exitflex/DEVIATIONS.md`;
  * its sha256 equals the committed one (TW.6).

### TW.10 Failure handling

* **A refusal** (gate, cut, disk, a missing A file) means nothing runs. The cause is fixed without changing a rule, and TW.7 step 9 applies.
* **A failing test, check or audit, or a bug found while running, that lies in the twin code**:
  1. The code is fixed.
  2. A dated entry, headed `[extra/twins] <UTC> <KST>`, with the reason goes into `research/exitflex/DEVIATIONS.md` before the rerun's output is read. `runner_x.py audit-file --path research/exitflex/DEVIATIONS.md --after '<heading>'` passes on it.
  3. The changed files' sha256 lines are appended to `PREREG_EXITFLEX_EXTRA.sha256` under that entry.
  4. The result files of a changed computation are deleted, and the stage reruns.

  No rule of this section changes after a twin figure is seen. A new rule is a new pre-registration.
* **A failure whose cause lies in A's code or A's result files**, for example in TW-C1, TW-C3, TW-A4 or TW-A8, is a bug of A found before the confirm (A 14, A 16.7 item 4):
  * `SELECT_KO.md` is held until the cause is known.
  * The fix and its reason go into `research/exitflex/DEVIATIONS.md`, in an entry that names `select_r2`, before any rerun output is read.
  * A's select stage reruns once.
  * The twins follow TW.7 step 10 on the `_r2` files.

  The twins never change an A-pinned file.
* **A bug found after `TWINS_KO.md` was sent.** A corrected `TWINS_KO_fix1.md` is sent, then `fix2`, and so on.
  * Its first lines are "<UTC 날짜·시각> 고친 판: <무엇을 고쳤는지>" and "고르기 규칙과 마감은 그대로입니다."
  * It carries no question.
  * It passes `twins.py audit` and `audit-file` before it is sent.
  * Both files are kept and hashed.
  * The correction changes no rule, choice, default or deadline of A.
* Whatever the twins show, A's gates, default, choice and confirm stand.

### TW.11 What the twins cannot show, and other limits

1. **2021-2023 chose the custom numbers.** The 38 combos and their E0 exits were picked on 2021-2023 (A Known limit 2), after the full grid's 2024-2026 results had been seen (A Known limit 1). A pick that beats its x twin here is the expected result. It is no evidence that custom numbers beat default numbers. Only a forward record can show that, and the restarted league has no `base` or `exitonly` accounts (A 11.3).
2. **These 38 cells' select period is no longer unseen.** Once this report is read, the 2021-2023 results of the default numbers, the house exit and the coin flips on these 38 cells have been seen. No later study of these cells can use 2021-2023 as unseen data, whether it looks at default numbers, the house exit, flips or A's variants on them (A 16.7 item 4).
3. **Information, not evidence of an edge.**
   * There is no test, placebo or interval, and many rows and kinds are compared.
   * "같은 쪽" happens about half the time when there is no effect.
   * The pick column is 나아짐 on every choosable core row by construction (A's gate 1).
   * The counts n/23 are not A's gate 2.
   * The 20 flip seeds share the market and the signal times, so they are not 20 independent tries.
4. **Pick against twin mixes two things.** Default combos can give many times more signals than a pick's, or many times fewer. The difference therefore also carries the account's busy time and the cost of more or fewer round trips.
5. **The flip keeps the pick's timing.** It removes the direction, but not the timing or the frequency of the signals. A variant that does better on flips may be reading the market at those times. The flip's leverage group follows side', so its size can differ from the pick's on the same bar.
6. **F11 and F12 have no flip.** No mirrored levels are built for them; A's placebo is the check of their timing. On default combos they exist only where TW-C2 passed.
7. **Flip size and ids.**
   * Flips run at quarter size only, while the league's current `flip` accounts run at live size.
   * Seed 0 uses the current league's id. It is therefore not the coin of the restarted league's `-nflip` or `-eflip` accounts (A 11.2), which have other ids.
8. **House + V.**
   * Mode (a) combines a rule with the stepped lock, which no A variant does.
   * F13 on the house is E0.
   * The house is the league's `base` account. It is not one of the rule bot's live accounts, and the rule bot is out of scope (A 12).
9. **League correspondence** rests on equal definitions (TW-T1, TW-C3) and on A's kernel.
   * The league engine's own parity with `kernel_x` on archive data is still open (A 11.4 item 13).
   * The league's live record is built from live windows and starts on 2026-10-11 (about 03:00 UTC).
10. **Static inputs.** The core leverage groups of twins and flips use `paperbot/quality_edges.json`, which was fitted on 2021-08..2024-06 (A Known limit 3).
11. **Thin units** (거래 적음) add little to the pooled figures. They are kept in them.
12. **DeepSeek money is private** (TW.6).

### TW.12 Seen before this section was fixed

* **Who wrote it.**
  * A sub-session drafted this section for the main session on 2026-10-12, from about 11:40 UTC. It worked from the main session's decisions and the design memo `scratchpad/exitb/B_DESIGN_FINAL.md` (its "B1").
  * Two reviews followed.
  * A further sub-session applied their fixes from about 12:15 UTC.
* **What the drafter read.**
  * A's working tree, before the pin: sections 1-15 and 16.7.
  * A's code: `kernel_x.py`, `data_x.py`, `metrics.py`, `runner_x.py` and the header of `ref_trade`.
  * `research/fullgrid/kernel.py` and `run.py`, and `paperbot/paramshadow.py`.
  * The league code: `league.py`, `candidates.py`, `exits.py`, `notify.py` and `dash.py`.
  * `research/fullgrid/DEVIATIONS.md` lines 60-110.
  * The fields kind, name, tf, exit and variants of `candleague/data/candidates.json`, counted only.
* **What the fixing sub-session read.**
  * A at its pin: sections 3, 8.2, 8.7, 11.2, 11.3, 12, 13 (order of work), 14, 16.7 and 17 (items 18-20, O7, O8).
  * In `runner_x.py`: the header, `Layout`, `read_sha_file`, `gate_pin`, `require_pinned_file`, `Store`, `f11_provider_from_modules`, `try_load_native`, `ensure_cut`, `real_config`, `variant_row`, `build_select_summary`, `OWNER_REPORT_LAST_LINE`, `audit_a8_file`, `audit_a9_file`, `audit_a8` and `main`.
  * In `data_x.py`: `open_cut`, `picks`, `RealProvider` and `PickData`.
  * In `kernel_x.py`: `Variant`, `variants`, `exit_of_pick`, `simulate`, `simulate_trade` and the F3 flag read.
  * In `metrics.py`: the counts, `hold_stats`, `pool_summary`, `eligibility`, the D11 whitelist and tripwire, and `summarize_light`.
  * In `research/fullgrid/run.py`: `core_module`, `params_of`, `default_combo` and the `best_flags` header.
  * In the league code: `candidates.accounts` and `default_combo`, `league.flip_side` and its imports, `notify.ROLE_KO` and `exits.LIVE_EXIT`.
  * The league start lines of `research/fullgrid/DEVIATIONS.md`.
  * The exit names of `candidates.json`, counted.
  * The source of the memo's probe scripts: their data folder and loop structure only.
  * The memo in full.

  Neither sub-session opened a result file, probe output or log, or ran a stage or any code on market data. The fixing sub-session also read free disk, time and load.
* **Figures seen.** The memo quotes these figures from its probes:
  * the timings used in TW.8;
  * a parity count: the probe's own flip code equals A's `simulate` at quarter size on all 89 arms for 38 of 38 picks. That probe flipped F11 and F12 with mirrored levels, so the count is not for `twins.py`;
  * select-period entered counts at quarter size of E0, F9.a and F13.b on the x twins, the house accounts and the seed-0 flips, with the units under 30 entries named and counted;
  * signal counts of the default cells.

  The probes loaded the full 1m arrays, not the cut. As the memo says, they printed select-period counts and seconds only.

  The memo also quotes counts of the full grid's 2024-2026 default-cell results from `STRATEGIES_KO.md`, which A lists as already seen.

  No money, growth, hold time or win share of any x twin, house or flip account appears in the memo, and neither sub-session saw one.
* **What follows.**
  * The twins are not blind to the entered counts at quarter size of E0, F9.a and F13.b on these units.
  * The memo set the 거래 적음 threshold of 30 after those counts were printed. The mark only names units and drops none, so it changes no pooled figure.
  * Units, ids, arms, sizes, seeds, metrics, rows and the report follow the main session's decisions, A and the two reviews. None was chosen on a figure.
