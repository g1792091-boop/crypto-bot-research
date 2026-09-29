#!/bin/bash
cd /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sweep/holdout
for sp in oos final; do
  ./run_timed.sh logs/gate_${sp}_5mB.log python3 lib/run_gate_tf.py --tf 5m --split $sp --out out --names S2_ST_ROC,N01_ST_EMA,N03_ADX_GC,N07_ICHI_CMO,N09_ALLIG_AROON,N10_HA_PSAR,N14_ICHI_RSI,N17_KC_RSI,N21_ST_RSI_ADX,N24_DMI,S1_EMA_RSI_CHOP,S3_CMO_SANDWICH,N05_PSAR_POC,N11_BREAKAWAY,N20_EMA9_CHOP,V39_ALL,OBV_S,V45_AMB,DOGE_L
  for tf in 1h 4h 1d; do ./run_timed.sh logs/gate_${sp}_$tf.log python3 lib/run_gate_tf.py --tf $tf --split $sp --out out; done
done
