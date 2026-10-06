"""The shadow league (그림자 리그): ideas that failed their pre-registered test are still followed on live bars, as
virtual trades, in a database of their own.

A shadow member is NOT a paper account: it never opens a position, never touches the 331 accounts, is never judged by
the 30-day checkpoint and never counts in anyone's multiple-testing correction. Everything it shows is labelled
'참고용, 판정 아님' (for reference, not a verdict).

Switch: AGENTS_SHADOW_LEAGUE=1 in /etc/paperbot/agents.env (default off = nothing is imported, opened or created; see
hook.py and docs/shadow-league.md).

Modules: zoneflip (the vendored detector), sim (vendored exit simulation and costs), league (Member, the registry and
the tick), store (SQLite tables and additive migrations), feed (where closed bars come from), account (the owners' style
account), clones (the coin-flip band), view (plain dicts for the dashboard), study (the 5-year result, static), hook
(the one call from the agents tick).
"""

ENV_SWITCH = "AGENTS_SHADOW_LEAGUE"
LABEL_KO = "참고용, 판정 아님"
DB_NAME = "shadow_league.db"
