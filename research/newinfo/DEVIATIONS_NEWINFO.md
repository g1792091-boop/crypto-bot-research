# New-information batch: deviations and run notes

Changes to the pinned rules go here, never into `PREREG_NEWINFO.md`. Nothing below changes a rule.

## 2026-10-11 (KST) — run notes, no rule change

1. **First start stopped at `check` (09:45 UTC).** The 12 daily metrics files of 2026-09-29 and 2026-09-30 had not
   been downloaded yet (`data.py download` is a separate step the `all` command does not run). They were downloaded
   with `python3 research/newinfo/data.py download --dir NI_DATA --archive FG1M --procs 2` (all 12 ok, published
   checksums matched) and `check` was run again. No signal or outcome had been computed.
2. **Second start crashed in `grid` (10:07 UTC) on a cache race, not on a result.** Two workers built the same coin's
   metrics cache at the same time; both wrote `NI_DATA/metrics/LTCUSDT.npz.tmp.npz` and the second `os.replace`
   found the file already moved (`data.metrics`, line 238). The cache files are a pure function of the source files
   (their sha256 is stored inside and checked on every load), and all six existed and validated after the crash.
   The run was restarted with the same command; `grid` skips cells already written by the same pinned code
   (11 of 14), so the results are those of the pinned code. The code is not changed during this study; a lock or a
   per-process temporary name is the fix for any later run (it would need a new pin).
