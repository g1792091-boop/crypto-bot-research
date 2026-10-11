# Hunt deviations and errata (not pinned; nothing reads this file)

## 2026-10-12: the first pin never ran; second pin ca561234bd before any data

- **What stopped.** The run at the first pin 90d3a882f2 stopped at the server self-check (bootstrap step 2/9) at about
  15:20 UTC on 2026-10-11, before any data was downloaded. It failed on
  `tests/test_hunt.py::test_reads_hook_ctx_guard_and_d11[ok]`, the first stale test in pytest's order.
  `test_october_read_on_synthetic_daily_files` failed the same way, and so did
  `tests/test_hunt_reads_a.py::test_run_end_to_end_on_synthetic_coins`, which is not in the self-check list.
- **The second pin.** Commit ca561234bd128acbf8ff2d303ca82ffcc1cf2fcc was made at about 16:03 UTC (01:03 KST on
  10-12). Erratum to PREREG_HUNT_WIDE 16.6: its heading says "about 01:30 KST", and its item 1 overstates the
  test_hunt_reads_a change, which only points the test at an absent bench file.
- **Pin lines changed in ca561234bd.**
  - `PREREG_HUNT.sha256` (v1): `tests/test_hunt.py` changed from 7c623d18... to c74ab09a.... 16.6 does not say that
    the v1 pin changed too.
  - `PREREG_HUNT_WIDE.sha256` (wide), lines replaced:
    - `tests/test_hunt.py`: 7c623d18... to c74ab09a...
    - `research/hunt/PREREG_HUNT_WIDE.md`: a9c9e34e... to f14d7c84...
  - `PREREG_HUNT_WIDE.sha256`, line appended: `research/hunt/reads_o.py` fffdd0af....
  - No line of any study code (hunt.py, entries, data, reads_a.py) changed.
- **The server runs a later commit.** It runs the later GO commit named in `research/hunt/GO_COMMIT`. That commit
  has the same pin files as ca561234bd and changes only unpinned files:
  - `bootstrap.sh`: reads_a resumes after a restart; reads_o runs after fidelity; the restart line works inside tmux.
  - `SERVER_KO.md`: times.
  - `READS_PLANNED.md`
  - this file
- **Not delivered in this run.** O2 does not run, because the calendar is unverified and unpinned. O3 is not
  computed. See PREREG_HUNT_WIDE 16.6 items 3 and 4, and READS_PLANNED.md P4.
