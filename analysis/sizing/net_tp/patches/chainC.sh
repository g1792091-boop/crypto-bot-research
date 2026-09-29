#!/bin/bash
cd /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/netTP/verify
export TPNET=1 OTAG=_net SCEN='[["S0",0.0,false],["S4",0.001,true],["TOP1",0.0,"top1"]]'
python3 -u vsim.py 1h 32 3 adv > v_1h_net.log 2>&1
python3 -u vsim.py 4h 48 2 adv > v_4h_net.log 2>&1
python3 -u vsim.py 1h 32 3 adv 1 > v_1h_net_b1.log 2>&1
python3 -u vsim.py 4h 48 2 adv 1 > v_4h_net_b1.log 2>&1
echo CHAIN_C_DONE >> /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/netTP/logs/chainC.log
