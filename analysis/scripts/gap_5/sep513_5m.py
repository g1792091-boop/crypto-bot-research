"""Try to reproduce the handoff's 'Sep 5-13: 3 symbols 59 trades, 46% win, 1000 -> 380' from the 5m ledger."""
import sys, os, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bt"))
from portfolio import single_account
R="/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/repro/results"
t=pd.read_csv(os.path.join(R,"trades_ALL_5m_v45g1.csv"))
t=t[(t.strategy=="V45_EXACT_AMB_G1")&(t.exit=="L50_sl15")].copy()
t["entry_ts"]=pd.to_datetime(t.entry_ts,utc=True)
for a,b in [("2026-09-05","2026-09-14"),("2026-09-05","2026-09-13"),("2026-09-04T15:00","2026-09-13T15:00"),("2026-09-05T15:00","2026-09-13T15:00"),("2026-09-05T12:00","2026-09-13T06:00")]:
    g=t[(t.entry_ts>=pd.Timestamp(a,tz="UTC"))&(t.entry_ts<pd.Timestamp(b,tz="UTC"))]
    sa=single_account(g,50.0)
    tk=g.sort_values(["entry_ts","symbol"])
    print(a,b,"per-symbol n",len(g),"wr %.3f"%(g.net>0).mean(),"| single acct taken",sa["taken"],"skipped",sa["skipped"],"final %.1f"%sa["final"])
