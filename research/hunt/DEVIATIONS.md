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
- **The server runs a later commit.** It runs the code commit named in the owners' line
  (`bootstrap.sh update <commit>`). The results record that commit in stamps/code_stamp.json (`git.commit` and the
  settings' `HUNT_GO`). `research/hunt/GO_COMMIT` is read only by `wait_go.sh` on a new server; it is updated to the
  same commit afterwards. The code commit has the same pin files as ca561234bd and changes only unpinned files:
  - `bootstrap.sh`:
    - A verdict written before a read stops is kept, and the run goes on.
    - reads_a is tried once more per code commit (`READS_A_TRIED`, written after the try; a try cut off by a reboot
      or a pane kill is not counted and runs again on the next restart): right away when
      `hunt test` stops after writing test.json (half the workers if run.log says "workers keep dying" or after an
      OOM kill), or after a restart that skipped the test step. There is no retry after a Python error caught inside
      the test's own read hook.
    - The printed restart line starts with `bootstrap.sh idle`, so a paste from another shell during a run changes
      nothing; reads_o stops with the run (pane kill or Ctrl+C).
    - Known, not handled: an OOM kill (exit 137) of the main `hunt test` process leaves its forked pool workers
      alive (ppid 1). They hold memory during the reads_a retry, and running() then reports the run as busy until
      they are killed or the server reboots. This is unlikely at 32 workers on 128 GB; if it happens, check with
      `pgrep -af research.hunt` and kill the leftovers.
    - A reads_o timeout (8 h) is reported apart from a failure.
    - The restart line works inside tmux and is printed on its own line.
    - The status and update messages are clearer.
  - `SERVER_KO.md` (times and the restart line)
  - `READS_PLANNED.md`
  - this file
  - the track 2 drafts `research/hiwr/PREREG_HIWR.md` and `research/hiwr/README_KO.md` (a separate study, not read
    by the hunt)
- **Not delivered in this run.** O2 does not run, because the calendar is unverified and unpinned. O3 is not
  computed. See PREREG_HUNT_WIDE 16.6 items 3 and 4, and READS_PLANNED.md P4.
