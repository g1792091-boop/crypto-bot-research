#!/bin/bash
export OMP_NUM_THREADS=1
cd /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/netTP/math/work && python3 -u sim.py > /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/netTP/logs/math_sim.log 2>&1 && python3 -u make_table.py > /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/netTP/logs/math_table.log 2>&1
echo "math exit $?" >> /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/netTP/logs/chainA.log
cd /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/netTP/tiered
python3 -u run.py --tf 4h --seeds 48 --he 2 --tpnet 1 > logs/run_4h.log 2>&1
python3 -u run.py --tf 1h --seeds 48 --he 3 --tpnet 1 > logs/run_1h.log 2>&1
python3 -u run.py --tf 15m --seeds 48 --he 6 --tpnet 1 > logs/run_15m.log 2>&1
python3 -u run.py --tf 5m --seeds 48 --he 10 --tpnet 1 > logs/run_5m.log 2>&1
python3 -u run.py --tf 4h --seeds 48 --fine 1 --tag _fine --he 2 --tpnet 1 > logs/fine_4h.log 2>&1
python3 -u run.py --tf 1h --seeds 48 --fine 1 --tag _fine --he 3 --tpnet 1 > logs/fine_1h.log 2>&1
python3 -u run.py --tf 15m --seeds 48 --fine 1 --tag _fine --he 6 --tpnet 1 > logs/fine_15m.log 2>&1
python3 -u mc.py > logs/mc.log 2>&1 && python3 -u report.py > logs/report.log 2>&1
echo "tiered exit $?" >> /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/netTP/logs/chainA.log
echo CHAIN_A_DONE >> /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/netTP/logs/chainA.log
