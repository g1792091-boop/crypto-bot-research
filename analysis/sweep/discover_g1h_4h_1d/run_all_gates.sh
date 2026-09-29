#!/bin/bash
W=/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sweep/discover_g1h_4h_1d
cd $W
for tf in 1h 4h 1d; do
  ./run_timed.sh logs/gate_$tf.log python3 run_gate_tf.py --tf $tf --split is --out out
done
