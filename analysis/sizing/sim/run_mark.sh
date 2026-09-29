#!/bin/sh
while pgrep -f "run_maker[.]sh" > /dev/null; do sleep 5; done
for tf in 15m 1h 4h 1d; do python3 run_sim.py --tf $tf --seeds 60 --tag mark --wick mark && python3 boot.py --tf $tf --tag mark; done
echo ALLDONE
