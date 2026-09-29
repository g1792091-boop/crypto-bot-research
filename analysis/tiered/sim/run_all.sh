#!/bin/bash
cd /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/tiered/sim
for tf in 4h 1h 15m 5m; do python3 -u run.py --tf $tf --seeds 48 > logs/run_$tf.log 2>&1; done
echo ALLDONE >> logs/run_5m.log
