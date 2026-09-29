#!/bin/sh
for tf in 5m 15m 1h 4h; do python3 run_sim.py --tf $tf --seeds 60 --tag maker --cost maker && python3 boot.py --tf $tf --tag maker; done
echo ALLDONE
