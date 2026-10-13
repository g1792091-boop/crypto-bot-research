# Deviations of the exit study (exitflex)

Changes to pinned files after their pin, dated, with the reason (PREREG_EXITFLEX.md section 14; PREREG_EXITFLEX_EXTRA.md
E.0 item 2 and TW.10).

## [extra/twins] 2026-10-12 15:15 UTC 2026-10-13 00:15 KST

* What failed: `twins.py audit` reported TW-A5 FAIL on the first run (HEAD 9f1c9e3). TW-A1 to TW-A4, TW-A6 and TW-A8 passed.
* Cause, found by a read-only script on the twin result files: on one of the seven units with a 2 ATR stop
  (core-DOGE-4h-1), the x twin F13.b and the house E0 files hold the same keys, wallets, counts and per-trade holds. The
  account has no trade in 2021-2023, so its hold statistics (`hold`) are NaN on both sides. The audit compared them with
  `np.array_equal`, which counts NaN as unequal. The other six units passed. The diagnosis looked only at that unit's hold
  arrays, NaN flags and trade count; no twin report was opened.
* Fix: `twins.py` gets `same_arrays(a, b)`, which compares float arrays with `equal_nan=True`. TW-A5 uses it. A test
  in `test_twins.py` checks that NaN hold statistics compare equal and that a changed count, a changed hold value or a
  missing key still fails. No rule of TW changes and no twin computation changes, so no result file is deleted.
* Then, in this order: the extra tests (183 passed), the new lines of `twins.py` and `test_twins.py` in
  `PREREG_EXITFLEX_EXTRA.sha256` under this entry, `twins.py check` again (its file records the new hashes), its line
  appended, `report` again (same result files), and `audit`.

## [extra/reads] 2026-10-12 15:15 UTC 2026-10-13 00:15 KST

* What failed: in the first `reads.py run` (HEAD 9f1c9e3), read X-028 (청산 이유 표) stopped with "Refused: DeepSeek row
  holds fields outside the D11 whitelist". Its DeepSeek rows for F13.a and F13.b carried the family name
  '규칙봇 계단 잠금(...)', whose parenthesis lists the ladder steps as percentages. The C8 guard refuses any string with a
  figure in a DeepSeek row, so the guard worked and nothing was written for X-028.
* Fix: `reads_b.py` gets `_label_rule(pool, v)`. On a DeepSeek row it drops a parenthesis that holds a digit, so F13's
  name there is '규칙봇 계단 잠금'. Core rows and every other name are unchanged. A test in `test_reads_b.py` runs the C8
  guard on the DeepSeek name of every variant.
* The first run's outputs were not opened. Only its console lines (pass, failed or dropped per read) and the X-028 error
  text were seen. They are deleted, and the stage reruns once after the new lines of `reads_b.py` and `test_reads_b.py`
  are appended to `PREREG_EXITFLEX_EXTRA.sha256` under this entry.
* Note on the time cap of E.5, which is not a deviation: the first run's projection was 320 minutes before drops and 254
  minutes after them. It dropped X-041 c = 1.5, X-043 live size and X-002. That projection was timed while the twins'
  run used three of the four CPUs. The rerun projects again under the same rule, with the same `--procs 1`. Whatever it
  drops is printed and written to `extra_reads.json`.
* The private extra report is written by the rerun, after `TWINS_KO.md`'s private section exists. The first run wrote
  it before the twins report existed.

## [extra/twins] 2026-10-12 15:23 UTC 2026-10-13 00:23 KST

* What failed: after the fix above, `twins.py check` was rerun (pass) and its new file pinned, but `twins.py report`
  refused: "twins_check.json changed since twins check". `check` records the pinned hash of every file listed in
  `PREREG_EXITFLEX_EXTRA.sha256`, and on a rerun that list already holds the earlier `twins_check.json`. The new file
  therefore carried its own old hash, which can never match. The first check did not meet this, because the file was
  not listed yet.
* Fix: `twins.py` gets `is_check_file(path)`. `check` no longer records the hash of `twins_check.json` (or `_r2`), and
  `require_check` skips that entry. A test in `test_twins.py` covers a rerun of check whose file carries the earlier
  line. Extra tests: 183 passed. No rule and no twin computation changes, and no twin output was opened.
* Then: the new lines of `twins.py` and `test_twins.py` under this entry, `check` again, its line, `report`, `audit`.

## [look] 2026-10-12 21:45 UTC 2026-10-13 06:45 KST

* After the confirm (commit 80729e7: choice.json and confirm.json hashed, DeepSeek F2.n50.b FAIL), the owners asked
  which strategy had the best month (x4.30 at live size in X-014) and for its full record. That needs the per-account
  result files, which sections 7 and 14 say nobody opens.
* The main session opens only the core picks' E0 files (`E0__q25.npz`, `E0__q100.npz`, select period 2021-2023)
  to build a per-pick table for the owners. No variant file, no DeepSeek file, no placebo file and no confirm-period
  file is opened.
* Every decision of this study is already hashed: the choice, the confirm and its report. This look changes no rule,
  gate, choice or result of the study. It is recorded as a look under section 14.
* What it can still influence is later work. The conditional-rules study now being designed (research/condrules) uses
  2021-2023 as its select period on these picks. That study's pre-registration records this look, and its menu and
  portfolio rules may not use per-pick results.

## [league] 2026-10-13 (after the study: choice and confirm are hashed)

* `candleague/exits.py` is in the pin of the extra code (`PREREG_EXITFLEX_EXTRA.sha256`). The owners' league work added to it after the study
  ended: the exit family "ladderU|<k>" (the owners' stepped lock 13% -> 10%, 20% -> 15%, 25% -> 20%, 30% -> 25%), `user_lock_for`, the
  `UserLadder` engine and their branches in `spec`, `known`, `exit_ko` and `make_engine`. Nothing the study used changed: the 84 rules,
  `lock_exit`, the F13 names and every existing function behave as before (the league's tests, including the study's parity test, pass).
* `candleague/rulex.py`, `candleague/runner.py`, `candleague/notify.py` and `candleague/candidates.py`'s consumers changed for the owner-exit
  league (rules file form "owner_exits"). No study result, gate, choice or report is touched. The study's own outputs stay as hashed.
* Same day, `candleague/rulex.py` only (not in a pin): a decision rule of the study (F1 structure break, F6 early loss cut; mode a) may now run on the owners'
  ladder ("ladderU|<k>") as the engine `RuleUserLadder`, and an owner-exit entry may carry `tighten` (0 < t <= 1): when the rule fires the stop is moved to
  t x the stop distance from the first stop's reference (never loosened; a price already past it is closed by the engine's own gap handling) instead of
  closing at market. The rules' decisions (`decide`), the chart records and every study id are unchanged; a rule account with no ladder is as before.
  F11.a (the strategy's own exit, `native.py` / `native_ds.py`) may also run on the owners' ladder; its accounts exist for the 16 strategies those
  two modules define (`NATIVE_STUDY`, compared with the modules by a test; 11 more strategies are added below). The league's install now copies `native.py`, `native_ds.py` and the
  fullgrid modules they import (`run.py`, `kernel.py`, `memo.py`, `data.py`, `grid.py`) so the provider loads on the server (checked in a copy of
  the installed layout, with numba blocked: the provider loads and gives arrays for all 38 picks). No study file changed.
  Two more owner-league options, `own_stop` and `own_target`, use the study's own per-signal level and target (`native_inv`, `native_tgt`) on the owners' ladder:
  the first stop at the level (distance = level + 0.1 ATR, between 0.5 ATR and the account's cap; the cap when the level is missing or on the wrong side) and
  a take-profit limit at the target with the lock kept. The numbers 0.5 and 0.1 ATR are the league's own test values, not the study's. They exist only for the
  seven strategies that define a level and a target (`NATIVE_LEVELS`, compared with the modules by a test).
  Also `gate` (g1: the signal's side equals the BTC 4h trend, last closed bar's close vs its EMA50; g2: the pick bar's ATR% between the 20th and 80th percentile of
  its last 200 bars): a gate account takes a signal only when its stamped gate value is true (unknown = no entry), and the coin twin (`coin_of`) may now
  follow an entry that has a rule (same rule, the coin's side). League-side options only; the study's rules, ids and outputs are unchanged.
* Later the same day, `candleague/native_more.py` and `candleague/native_more_ds.py` (new league files, not in a pin; `research/exitflex/*` is untouched) give the
  eleven picks whose strategies the study's code does not cover (N02_ST_KST, N04_ST_KLINGER, N07_ICHI_CMO, N12_ICHI_AO, N21_ST_RSI_ADX, N23_HA_ST; F15_LON_BRK, F15_ORB,
  F3_BOS, F4_FAN, F6_VWAP_FAIL) the same structure kinds as the other 38: the league's own definition of "this long's structure is broken" (shorts mirrored), read from
  each strategy's own indicators with the pick's own numbers, in the shape of `native.py`'s arrays (tri-state, rules C1-C8; no level, no target). `NATIVE_COVERS` is now
  the study's 16 (`NATIVE_STUDY`, still compared with the two modules) plus these 11 (`NATIVE_MORE`), 27 strategies and all 49 picks; the account fingerprint includes the
  hash of the two new files (`native_hash`), so the league restarts. These eleven definitions are NOT the study's and no study result says anything about them.
