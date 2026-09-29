#!/bin/bash
cd /tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/tiered/verify
nice -n 5 python3 -u vsim.py 4h 48 2 adv > v_4h.log 2>&1
nice -n 5 python3 -u vsim.py 1h 32 3 adv > v_1h.log 2>&1
nice -n 5 python3 -u vsim.py 15m 12 6 adv > v_15m.log 2>&1
echo ALLDONE >> v_15m.log
