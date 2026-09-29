#!/bin/bash
cd /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sweep/holdout
sp=$1
./run_timed.sh logs/exits_${sp}_1h_4h_1d.log python3 exits_holdout.py $sp 1h 4h 1d
./run_timed.sh logs/exits_${sp}_5m.log python3 exits_holdout.py $sp 5m
