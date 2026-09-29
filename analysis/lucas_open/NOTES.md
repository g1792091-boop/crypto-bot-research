# Lucas Lalk open-source Astral strategies (#1199, #1233)

Of 23 strategies published by lucas_lalk on Astral Explore (checked 2026-09-30), only #1199 and #1233 have
copy_policy=everyone / source_locked=false; the other 21 are source-locked. `run.py` re-implements the two open
ones from their published code and runs them on the sweep's 15m data (2021-08 .. 2026-09, 7 coins), as published
(BTC long, no cost) and with real costs and a mirrored short side. Replication check on the published 7-week
windows (no cost, BTC long): #1199 19 trades, 95% win (Astral 32 positions, 94%; Astral adds to the position on
every oversold bar); #1233 55 trades, 33% win, +34% (Astral 51, 33%, +38%). Results: `summary.csv`.
Usage: python3 run.py <dir with full/<coin>-15m.csv>  (rebuild the data with ../sweep/data/inputs/rebuild.py).
