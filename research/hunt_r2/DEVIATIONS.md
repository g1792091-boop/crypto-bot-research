# Hunt round 2: deviations and the design-hash record

## 1. Design hash (2026-10-12)

- **Design hash.** `PREREG_HUNT_R2.md` sha256 `bb7fc9432b88324266c296d27c76629e1da54297eaff810294c3be14c9848fd8`.
- **Where it is recorded.** It is the first line of `PREREG_HUNT_R2.sha256`, in commit
  `d4d69d17ba` on `claude/keen-pasteur-wav02u`.
- **Push time (the remote's).** GitHub's repository activity shows that commit's push at **2026-10-12T00:46:46Z**.
- **What the main session had seen of round 1 at the push.** No select, pick, test or read output. The hunt-results
  branch had not been fetched.
- **What the owners had shown of round 1.** Only the bootstrap progress lines. The last of them, at 2026-10-11 22:53
  UTC, was `진행 중: 6/9 … 지금: wide 시험 (2024-01 ~ 2026-09, 한 번만)`. It holds no result.
- **Whether the owners had seen the verdict themselves.** Not known at the hash. The progress screen they shared shows
  no verdict line.
- **Effect on section 0.1.** Its sentence "written, reviewed and hashed before any round-1 select, pick, test or read
  output was seen, fetched or inferred" holds for this hash.

## 2. Code-review corrections before the code pin (2026-10-12)

**Seen at this date.** The agents that wrote and corrected round 2's code saw no round-1 output: no select table,
pick, batch, `test.json`, control, read, R22 file or server log; `research/hunt/out/**` (other than the name of the
pinned `parity.json`) and the hunt-results branch were neither listed, fetched nor opened, and nothing of round 1 was
inferred. No forward record of a hunt system was seen. The full grid's results branch (seen by the designers, 0.2) was
read for one file, `research/fullgrid/results/select.json` (entry 2.10). The main session adds, when it commits these
entries, what it had seen of round 1 by then.

**Types (0.3).** (i) = the code now does what the quoted line says; (ii) = a feasibility change; (note) = a record
that changes no rule. Every entry below is dated 2026-10-12, the design-hash date, so none moves the forward-count
date of 0.5.

### 2.1 (note) Runs on real prices on the development machine (11, last bullet; 0.2)

11 says "Nothing runs on real prices on the development machine." Before this entry, two code jobs did:

- **Core job (timing).** On the hunt's pinned 30-coin 5m data cut at 2024-01-01 (the select period 2021-01 .. 2023-12):
  the event store, the engine runs of Stage 0 + Stage A at base cost and cost x2, and null units, for **N15_KC_AO and
  S2_ST_ROC**, plus single engine runs of those names. The engine computed S, S2, n and bust for every system it ran;
  they were not printed or kept. Printed and kept: seconds per step, run counts (N15 127-161, S2 61), store bytes,
  and signal-only default 15m event densities of 15 names on 2 coins. The report does not record whether the anchor was
  forced; the printed run counts depend on the anchor chosen by S, so they carry at most that much of an outcome.
  Seen by: that job and the main session (its report).
- **Kit job (timing).** Round 2's store code for **all 85 names** on every timeframe of **BTCUSDT and AVAXUSDT**, practice
  bars cut at 2024-01-01: signal functions only (no engine run, no position, no outcome); kept: CPU seconds and event
  counts per combo, summarised in SERVER_R2_KO.md as densities (median 0.13 events per day per coin).
- **This job:** synthetic bars only. No timing on real bars runs again before the pin.

### 2.2 (i) 4.2 and 3.6: the peak search keeps the default and defaults in effect

4.2: "Peak = the coarse-eligible point with the highest P_c" and "A name is a candidate only if it has a peak, the peak
is not the default (nor a default in effect), and P_c(peak) > P_c(default point)". 3.6: a default in effect "is counted
as the default and can never be a peak or a pick". The draft code removed the default and defaults in effect before
choosing the peak, so a name whose best plateau point was a default in effect could still become a candidate through
its next point. The code now follows 4.2: the peak is chosen over every eligible point; when it is the default or a
default in effect the name is no candidate, and picks.json shows that peak with `peak_is`. 3.6's "can never be a peak
or a pick" is read as "never a pick, and a name whose peak it is has no candidate" (4.2's candidate clause). Points
another name owns (3.6, one system two names) stay out of the peak search, as 3.6 says. The nulls replay the same rule.

### 2.3 (i) 3.6: a default in effect is decided on the gated event list

3.6: "a combo whose gated select-period event list (all 30 coins: coin, signal-bar close, side) on the same timeframe
and gate hashes equal to its default's". The draft compared the lists after the ATR14 and fill filters. The code now
hashes the store's events after the gate and before those filters. Equal gated lists give equal signal lists, so such a
point still shares the default's run. In a null replicate the identity of the real search is kept: every null transform
is a function of the list, so a real default in effect stays one in every replicate; an equality that only a transform
creates is not treated as one.

### 2.4 (i) 4.3 (a′): the redraw share is the replicate's own

4.3: "If more than 10% of the replicate's events (all systems and coins) are dropped, Δ_i is redrawn with j = 1, 2,
...". The draft took the share over a histogram of every coarse combo at every slot before any engine run. The code
now counts the drops and events of every system the replicate's own Stage 0 and Stage A ran (all coins); a replicate
above 10% is replayed whole at the next draw (its part files under `null_a/<i>_j<j>/`). The (a′) histogram stage is
gone. Collisions: two events of one coin landing on one bar are one event when their sides are equal and none when
opposite (W 3.2's both-sides rule), counted "collided"; the same rule applies to (a-c) in 7.1.

### 2.5 (i) 6: CSCV, the 2023 lift and leave-one-year-out re-choose Stage 0 in sample

6: "in each split Stage 0 and Stage A are replayed on the in-sample half with the same rules". The draft ran Stage A
only at the full-period anchor, which was chosen on all 36 months (an earlier proposal to record this as a (ii) entry is
withdrawn). The pretest step now runs every coarse point at every (timeframe, gate) slot once (base and cost x2, monthly
series, from the store; about 26,000 more systems), re-chooses each name's anchor on the in-sample months and runs
Stage A at that anchor, for CSCV and for the two 24-month reads. Quantities: in-sample S and S2 = mean ln M over the
in-sample months; n = positions opened in them; bust = the bust month lies in them; median monthly multiple over them;
the out-of-sample score = mean ln M over the other months; omega = average rank / (N + 1) among the 4,369 selectable
systems of the real search (a rank-1 peak at another slot is ranked as one more member); PBO = share of splits with
logit(omega) <= 0; slope = rank-1 peak's out-of-sample mean ln M on its in-sample mean ln M. Leave-one-year-out counts a
return only at the full-period anchor.

### 2.6 (i) 3.6: two names reach one system

"An identical system ... reached under two names belongs to the name whose default is nearer in log distance". A system
is "reached" by a name when it is that name's default or a coarse point at that name's anchor (same timeframe and gate);
in practice only TSMOM 14 days at a shared anchor is affected.

### 2.7 (i) Smaller readings of 4.2, 4.4 and 5

"At least half of the existing coarse neighbours" holds when there is none (0 >= 0). The box plateau's medians and the
2/3 share are over the box points that exist, the centre included. Box best ties go to the earlier box point. Null
percentiles are printed to rank 30 for "ranks held by no real candidate".

### 2.8 (i) 5: the box result in picks.json

5: picks.json holds "for taken names the box result and the box best". A draft overwrote the box result of F1, F2 and
F5 names with their money figures; fixed before any run.

### 2.9 (i) 3.7: only the signal code's own errors remove a combo

3.7: "The removal depends on signals only". A MemoryError or OSError in a worker is a resource error: the unit now stops
(and is retried by the kit) instead of being recorded as a removal. Store units carry the sha256 of the signal code
(round 2's modules and the folders of round 1's signal path) and are recomputed under other code (11: "resumable part
files under the pin's hash"); box checks have part files too.

### 2.10 (i) 5: the label "same numbers as a full-grid select pick"

5 lists this label in picks.json and nothing in picks.json changes after its hash. Its input is now pinned with round
2's code: `research/hunt_r2/fullgrid_select_picks.json`, the full grid's 711 select picks reduced to kind, name,
timeframe, rank, exit and numbers (no money figure), extracted from `research/fullgrid/results/select.json` on branch
`fullgrid-results-20261010-1602` (git blob cfadf890ef0abd67e2b931d7d2dac40af8e5e810, sha256
fec3b4f50fe359c2f36782ef485a8fdeb1b18fed9d3a6076c2d4d05dc0eb2a0d). A peak whose name and every number equal one of
them (any timeframe and exit) gets the label and the matching timeframes and ranks. 31 coarse points of 23 names match
(numbers only). The F4 watch list is read the same way, and an unreadable list now stops the select step.

### 2.11 (i) 7.1 and 7.2: controls and p-values

- (b-c): one coin per distinct signal-bar close of the pick, drawn in ascending order of the close; heads = a uniform
  draw < 0.5 (seed parts with control "bc").
- (a-c): 4.3 (a′)'s shift on the test span, drops and collisions counted (2.4).
- t_32 with a zero standard deviation: p = 0 when the mean is > 0, else 1.
- Seed parts of 7.2: ("tune", "boot") for p_tune and ("tune", "ci") for the 90% CI, a 100,000-resample month percentile
  interval.

### 2.12 (i) 8: the ledger

8 (A): "every test-period hypothesis of the hunt program that has a p", including "every round-1 read that prints a p"
and "round 2's p and p_tune"; (L): "every confirm look whose pre-registration is hashed but not yet run".

- Round-1 reads with a p: the r = 1% line of each tested pick and O4's R6 (e) p per row.
- Round 2's own reads now count like round 1's: the r = 1% line p of every row (picks and baskets) and the O4 (e) p
  per row, DeepSeek rows from round 2's private reads files after their sha256 check; while a reads file is absent its
  rows count in (L) at p = 1. Round 2's maximum: 30 x (p, p_tune) + 30 r = 1% lines + 32 O4 rows = 122.
- DeepSeek read p-values of other studies enter at p = 1 (their private files supply confirm rows only).
- Pending maxima: hunt v1 2, wide 93, wide O4 n + 3, round 2 as above, track 2 its picks or 315.
- Hashed pre-registrations: a pinned registry (`ledger_registry.json`) lists every `research/*/*.sha256` of the code
  pin with its role; a later hash file that neither the registry nor a `--ledger-extra` row ("prereg") names makes
  print (L) "incomplete": no rejection is printed and no round-2 pick passes the live gate until it is registered with
  its maximum (for example the flexible-exit study's 2024-2026 confirm once it is hashed). `ledger_extra.json` (pinned,
  empty) is passed by the kit. `hunt_r2 pinlist` lists unregistered files as problems before the pin.
- The registry's roles for older studies (run before this design, outside 8's family) were set from the file list at
  this date; the main session checks them before the pin.
- Parity with track 2 (8, last bullets): the same round-1 and track-2 confirm rows enter both ledgers with the same ids
  and p (a test). Intended differences: p = 1 where a p is missing (track 2 prints "incomplete"), the read rows, the full
  grid's 711, the 38 F4 picks and the pending maxima.

### 2.13 (i) 8: the owners' private files

8: "with one line given in the server guide". The guide gives two scp lines, one per study, because the two archives
must arrive under different names. The kit takes every member named `wide_test_private.json` or `test_private.json` out
of every archive and keeps the one whose sha256 equals the public output's `private_sha256`; the code then reads only
the p-value fields of the confirm rows. Nobody opens the files.

### 2.14 (i) 9: reads

- Round 1's pinned reads modules run unchanged on round 2's context; O2 and round 1's select-period weekend map are
  not run (not round-2 reads); the weekend d_m 90% CI uses seed parts ("hunt-r2", "weekend", period, control, "ci").
- 9.1 ROWS: the baskets now get the rows module's reads too (new 24, extra 2020, the r = 1% line with member-wise
  controls, select-period controls, the correlation with the basket of anchor defaults, and the basket's plain test
  run).
- 9.1 "The reads stop at 12 hours wall": the wall is the reads' own running time summed over restarts (an idle stopped
  server does not count). reads_a runs one row at a time and keeps every finished row; the reads stop starting rows at
  the wall, and the kit stops a running row at the wall as a backstop. R13's cross-row overlaps and R15's union come
  from one last pass without windows. `reads_status.json` is rewritten after every module and row.

### 2.15 (ii) 9.2: R14 and R19 are not computed by the pinned reads

9.2 lists the R14 forward band and R19 1m + mark fidelity for passing picks. Round 1's code has no R14 module and its
fidelity command takes round-1 specs only; the kit downloads no 1m data. The pinned reads print "not computed" for
both. Any later computation of either is post hoc (9.1) and gets its own entry. Dated on the design-hash date, so the
forward-count date of 0.5 does not move.

### 2.16 (i) 6: a pretest failure stops before the test

6: the select-only reads are written "before test.json exists". The kit used to warn and go on to the one-look test.
It now stops before the test on any pretest failure; only on the developer's word (`SKIP_PRETEST`) does it go on, and
the reads are then post hoc.

### 2.17 (note) 0.3 and 12: the pinned checkout, the kit and the compute plan

- 0.3 blind code: the pinned commit holds no round-1 output. `check_pin("select")` and `hunt_r2 pinlist` refuse
  `research/hunt/out/{v1,wide}/{select,picks,test,reads_o,reads_a}.json` and `research/hunt/results` (existence only).
  The ledger inputs are fetched from the results branches at the test step only; round 1's select and picks files for
  the results page's labels after round 2's `test.json` is pinned.
- File names: `bootstrap_r2.sh`, `wait_go_r2.sh`, `SERVER_R2_KO.md` (11, 12).
- 12's disk: the server's own disk, no Block Storage (as track 2); the kit stops before any work below 40 GB free.
- 12's times, measured on synthetic bars and the timing of 2.1: select about 3-8 h on 32 vCPU, the verdict about 4-10 h
  after the start (12 said 5-15 h and 7-17 h); reads up to the 12-hour wall; a 64 vCPU server is optional. The kit
  raises the open-file limit (the store keeps memory maps open; Ubuntu's default soft limit is 1024).
- Fidelity: the in-repo tests check a sample; `tests/test_hunt_r2_fidelity.py` (`HUNT_R2_FIDELITY=1`) checks every
  default system through the store and the engine and every coarse F2 / F3 combo with the memo kept and fresh; run
  before the pin.
- Fidelity run on 2026-10-12 after these corrections (synthetic bars): every default system (670) through the store and
  the engine and every coarse F2 / F3 combo with the memo kept and fresh gave 0 differences (2 passed, about 9 minutes on
  4 vCPU).
