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
