#!/bin/bash
cd /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sweep/discover_g1h_4h_1d
./run_timed.sh logs/tail_1d.log python3 tail_check.py --tf 1d --reps 500 --cells N01_ST_EMA:64,N23_HA_ST:64,N04_ST_KLINGER:64,N25_DST_CCI:64,S2_ST_ROC:64,N02_ST_KST:64,N02_ST_KST:4,N18_VWMA_MACD:4,N23_HA_ST:4,N23_HA_ST:16
./run_timed.sh logs/tail_4h.log python3 tail_check.py --tf 4h --reps 500 --cells N13_3OUTSIDE:64,N13_3OUTSIDE:16,S4_BB_BBP:4
