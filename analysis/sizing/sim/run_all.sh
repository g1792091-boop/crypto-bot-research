#!/bin/sh
# usage: run_all.sh <tag> <seeds> [extra args]; runs TFs sequentially (one heavy process)
tag=$1; seeds=$2; shift 2
for tf in 15m 1h 4h 1d 5m; do python3 run_sim.py --tf $tf --seeds $seeds --tag $tag "$@" && python3 boot.py --tf $tf --tag $tag; done
