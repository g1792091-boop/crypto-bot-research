#!/bin/sh
while pgrep -f "run_rest.sh" > /dev/null; do sleep 5; done
for tf in 5m 15m 1h; do python3 run_sim.py --tf $tf --seeds 60 --tag front --edge_h 4 && python3 boot.py --tf $tf --tag front; done
for tf in 4h 1d; do python3 run_sim.py --tf $tf --seeds 60 --tag front --edge_h 1 && python3 boot.py --tf $tf --tag front; done
echo ALLDONE
