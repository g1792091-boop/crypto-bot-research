#!/bin/bash
cd /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sweep/holdout
for sp in oos final; do
  ./run_timed.sh logs/gate_${sp}_5mA.log python3 lib/run_gate_tf.py --tf 5m --split $sp --out out --names S5_DONCHIAN_MFI,S6_EMA_DMI_ADX,N02_ST_KST,N08_ICHI_WR,N12_ICHI_AO,N18_VWMA_MACD,N22_VORTEX_PSAR,N23_HA_ST,N25_DST_CCI,S4_BB_BBP,N04_ST_KLINGER,N06_MACD_ORB,N13_3OUTSIDE,N15_KC_AO,N16_BBRSI,N19_FIB_CHOP,OBV_B,DOGE_S
  for tf in 15m 30m; do ./run_timed.sh logs/gate_${sp}_$tf.log python3 lib/run_gate_tf.py --tf $tf --split $sp --out out; done
done
