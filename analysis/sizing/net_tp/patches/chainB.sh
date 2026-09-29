#!/bin/bash
export OMP_NUM_THREADS=1
cd /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/netTP/sizing
for tf in 15m 1h 4h 1d 5m; do python3 -u run_sim.py --tf $tf --seeds 100 --tag net --tpnet 1 >> /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/netTP/logs/sizing_run.log 2>&1 && python3 -u boot.py --tf $tf --tag net >> /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/netTP/logs/sizing_run.log 2>&1 || echo "FAIL $tf" >> /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/netTP/logs/chainB.log; done
python3 -u report.py --tag net > /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/netTP/logs/sizing_report.log 2>&1
python3 -u killswitch.py > /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/netTP/logs/sizing_killswitch.log 2>&1
echo "sizing exit $?" >> /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/netTP/logs/chainB.log
echo CHAIN_B_DONE >> /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/netTP/logs/chainB.log
