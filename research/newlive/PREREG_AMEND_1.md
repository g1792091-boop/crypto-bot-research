# 사전 등록 보충 1 (2026-10-22, 후보 결과를 보기 전)

Written after `PREREG.md` (sha256 783874cad1bd6523ca40c3f9e920c1d33e1414b52bca84986f12ac2eb164dbe7) and before any
candidate run. Two owner questions of 10/22: "추세형 매매법을 몇 개 넣어야 할지 모르겠다" and "진입횟수는 하루 최소
3~4번을 원한다". Everything in `PREREG.md` stays; this adds two things.

## A. How many judges (판단 매매법 수)

Two judge sets, defined now without any result (the owners must leave at 16:00 KST today, so a set with more judges,
which needs new judge code in the live bot, is left for a later test):

| id | judges | direction |
|---|---|---|
| J4 | V39, S6, OBV, N12 (current) | ≥ 3 of the 4 on one side (current) |
| J4L | the same 4 | up votes − down votes ≥ 2 (adds 2-up/2-neutral, keeps 3-0, 3-1, 4-0) |

ADX, 끝물, hold, the entry checks and the JUDGE exit (a closed higher bar judged against the position) stay as now,
computed on the set's own direction. Candidate solo runs and B0/B1 use J4 (as `PREREG.md`). Then, on the select period
only, the chosen basket (B1, or B0 if there is no B1) is run with J4 and J4L; the set with the better select-period
growth is the proposal; both are confirmed once and shown side by side. Each set's direction accuracy (share of
judged bars whose next 4 bars closed that way, 2021..2026) is shown too.

## B. 3~4 entries a day (진입 횟수)

Basket B3: candidates in the order of select-period growth (one label per strategy and timeframe), the smallest number
K from the top whose solo select-period entries per weekday add up to ≥ 4.0 (overlap and the one-position rule bring
the basket below the sum). B3 is run as a basket with J4 on the select period and confirmed once like B0. Its real
entries per weekday are reported in both periods.

The goal arithmetic shown with it: ×6 in a month = growth ln 6 = 1.79. At margin 40 %, n trades a month need a mean
net ROE of about (e^(1.79 / n) − 1) / 0.4 per trade: 22 trades (1 a weekday) ≈ +21 %, 66 trades (3 a weekday) ≈
+6.9 %, 88 trades (4 a weekday) ≈ +5.1 % (before the extra loss from wins and losses varying).
