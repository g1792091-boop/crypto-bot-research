#!/bin/bash
cd /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/tiered/sim
python3 -u run.py --tf 4h --seeds 48 --fine 1 --tag _fine --he 2 > logs/fine_4h.log 2>&1
python3 -u run.py --tf 1h --seeds 48 --fine 1 --tag _fine --he 3 > logs/fine_1h.log 2>&1
python3 -u run.py --tf 15m --seeds 48 --fine 1 --tag _fine --he 6 > logs/fine_15m.log 2>&1
echo ALLDONE >> logs/fine_15m.log
