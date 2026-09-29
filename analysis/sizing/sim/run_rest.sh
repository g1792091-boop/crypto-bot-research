#!/bin/sh
# wait for the base run to finish, then: re-run 1h/4h with the extended edge grid, then sensitivities.
while pgrep -f "run_all.sh base" > /dev/null; do sleep 5; done
for tf in 1h 4h; do python3 run_sim.py --tf $tf --seeds 100 --tag base && python3 boot.py --tf $tf --tag base; done
for spec in "wick --wick robust" "adv --order adv" "fav --order fav"; do
  set -- $spec; tag=$1; shift
  for tf in 15m 1h 4h 1d; do python3 run_sim.py --tf $tf --seeds 60 --tag $tag "$@" && python3 boot.py --tf $tf --tag $tag; done
done
echo ALLDONE
