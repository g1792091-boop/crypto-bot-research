# Phase 2, amendment 1 (before any result)

Written 2026-10-10 22:52 KST; the full-grid run was still in its grid stage and no result of it had been seen.
Pinned by `PHASE2_AMEND_1.sha256`. Owners 2026-10-10 asked for teams by other market views too ("큰 흐름·변동성"), and
left the analysis to us for their goal.

Section 7 of PHASE2_PREREG.md is run on three market views instead of one, each exactly as section 7 describes:

* **장세** (as registered): 추세장 / 횡보장 / 급변장 / 보통.
* **큰 흐름**: the last completed UTC day's close against the EMA200 of daily closes: 위 (상승장) / 아래 (하락장)
  (`regimes.py`, fixed 2026-10-10 before any result).
* **변동성**: the 15m ATR14 / close against its previous 90 days: 작음 (below the 30th percentile) / 보통 / 큼 (above
  the 70th) (`regimes.py`, demobot.regime).

Home states, persistence and teams are computed per view; a team's two members come from the same view. One BH family
(10%) over the persistence tests of all views together, and one over all teams of all views together, so testing more
views makes each pass harder. Everything else in section 7 is unchanged. `teams.py` runs the three views by default.
