#!/bin/sh
for tf in 4h 1d 1h 15m; do python3 run_sim.py --tf $tf --seeds 60 --tag sub --subbar 1 && python3 boot.py --tf $tf --tag sub; done
echo ALLDONE
