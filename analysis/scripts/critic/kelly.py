"""What leverage could ANY plausible edge support?  Growth-optimal (Kelly) notional
leverage and ruin at the user's sizing (40% margin x 50x = 20x notional), using the
empirical per-trade return shapes from the stage-1 ledgers, mean-shifted to
hypothetical net edges."""
import numpy as np, pandas as pd, os
R = "/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/repro/results"
want = {("S6_EMA_DMI_ADX","F_sl2.0_tp3.0"),("N17_KC_RSI","L50_sl20"),("S2_ST_ROC","F_sl2.0_tp2.0"),("N17_KC_RSI","F_sl1.0_tp1.5")}
parts=[]
for ch in pd.read_csv(os.path.join(R,"trades_IS_15m_all5.csv"),usecols=["strategy","exit","symbol","net","mae","entry_ts","exit_ts"],chunksize=200000):
    m = ch.set_index(["strategy","exit"]).index.isin(list(want))
    parts.append(ch[m])
t15=pd.concat(parts)
t5=pd.read_csv(os.path.join(R,"trades_ALL_5m_v45g1.csv"),usecols=["strategy","exit","symbol","net","mae","entry_ts","exit_ts"])
t5=t5[(t5.strategy=="V45_EXACT_AMB_G1")&(t5.exit.isin(["L50_sl15","F_sl2.0_tp3.0"]))]
allt=pd.concat([t15,t5])
rng=np.random.default_rng(0)
rows=[]
for (s,e),g in allt.groupby(["strategy","exit"]):
    x=g.net.to_numpy(); mae=g.mae.to_numpy()
    days=(pd.to_datetime(g.exit_ts).max()-pd.to_datetime(g.entry_ts).min()).total_seconds()/86400
    # trades per 30 days in ONE account with max 1 position overall is lower; use per-symbol-ledger count/5 as a proxy for a single symbol
    per_month_all=len(x)/days*30
    sd=x.std()
    for mu in (0.0005,0.001,0.002):
        y=x-x.mean()+mu                  # empirical shape, hypothetical net edge
        kelly=mu/(y.var()+mu**2)         # notional leverage maximising E[log(1+f*y)] (2nd-order)
        # exact growth per trade at 20x notional, with liquidation when mae <= -(1/50-0.005)
        liq = mae <= -(1/50-0.005)
        roe = np.where(liq,-1.0,np.maximum(-1.0,50*y))
        g20 = np.log(np.maximum(1e-12,1+0.4*roe)).mean()
        # 30-day bootstrap at the ledger's pooled trade rate
        n=int(round(per_month_all)); sims=np.log(np.maximum(1e-12,1+0.4*roe[rng.integers(0,len(y),(2000,n))])).sum(1)
        rows.append(dict(strategy=s,exit=e,n=len(x),sd_pct=sd*100,mu_net_pct=mu*100,kelly_notional_x=kelly,
                         user_notional_x=20,logg_per_trade_20x=g20,trades_30d=n,
                         median_30d_multiple=float(np.exp(np.median(sims))),p_below_half=float((sims<np.log(0.5)).mean()),
                         p_20x=float((sims>=np.log(20)).mean())))
res=pd.DataFrame(rows); pd.set_option("display.width",250)
print(res.round(4).to_string(index=False))
res.to_csv("kelly.csv",index=False)
# required net edge per trade for x20 in 30 days at 20x notional (solve numerically on each shape)
print("\nRequired net edge/trade for median x20 in 30 days at 40%x50x:")
for (s,e),g in allt.groupby(["strategy","exit"]):
    x=g.net.to_numpy(); mae=g.mae.to_numpy(); days=(pd.to_datetime(g.exit_ts).max()-pd.to_datetime(g.entry_ts).min()).total_seconds()/86400
    n=len(x)/days*30
    for mu in np.arange(0,0.01,0.00005):
        y=x-x.mean()+mu; liq=mae<=-(1/50-0.005)
        roe=np.where(liq,-1.0,np.maximum(-1.0,50*y)); gg=np.log(np.maximum(1e-12,1+0.4*roe)).mean()
        if gg*n>=np.log(20):
            print(f"  {s:18s} {e:14s} trades/30d={n:6.0f}  need net {mu*100:.3f}%/trade (gross {mu*100+0.14:.3f}%), best observed net {x.mean()*100:+.3f}%"); break
    else:
        print(f"  {s:18s} {e:14s} trades/30d={n:6.0f}  not reachable with net edge < 1%/trade")
