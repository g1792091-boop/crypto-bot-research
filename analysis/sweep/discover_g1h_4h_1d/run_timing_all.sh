#!/bin/bash
W=/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sweep/discover_g1h_4h_1d
cd $W
./run_timed.sh logs/timing_4h.log python3 run_strategy_timing_controls.py --tf 4h --reps 200 --out out
./run_timed.sh logs/timing_1d.log python3 run_strategy_timing_controls.py --tf 1d --reps 200 --out out
./run_timed.sh logs/timing_1h.log python3 run_strategy_timing_controls.py --tf 1h --reps 40 --out out
