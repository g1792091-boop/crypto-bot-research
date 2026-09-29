"""Verifier part 1: closed-form distances/fees + independent ATR and path stats (IS only)."""
import numpy as np, pandas as pd
D = "/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sweep/data/is"
COINS = ["btcusd","ethusd","solusd","xrpusd","dogeusd","ltcusd","bchusd"]
IS_END = pd.Timestamp("2024-07-01", tz="UTC")
MMR = 0.005; CFILL = 0.0005 + 0.0002
print("L  dliq%  dliq_exact_long%  dliq_exact_short%  tp%  fee/tp  feeRT%eq(M=.2) (M=.4) liqloss%eq(M=.2)")
for L in [5,10,20,25,30,40,50]:
    dl = 1/L - MMR
    ex_l = (1/L - MMR)/(1-MMR); ex_s = (1/L - MMR)/(1+MMR)
    tp = 0.10/L
    print(L, round(100*dl,3), round(100*ex_l,4), round(100*ex_s,4), round(100*tp,3), round(2*CFILL/tp,3),
          round(100*0.2*L*2*CFILL,3), round(100*0.4*L*2*CFILL,3), round(100*0.2*(1+L*CFILL),3))

def load(sym, tf):
    df = pd.read_csv(f"{D}/{sym}-{tf}.csv", parse_dates=["ts"])
    assert df.ts.max() < IS_END
    return df

def atr_pct(df):
    pc = df.close.shift(1)
    tr = pd.concat([df.high-df.low, (df.high-pc).abs(), (df.low-pc).abs()], axis=1).max(axis=1)
    a = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    return (a/df.close).dropna().values

rows=[]
for tf in ["5m","15m","30m","1h","4h","1d"]:
    A=[]; m1=[]; m16=[]; per={}
    for s in COINS:
        df = load(s, tf); a = atr_pct(df); A.append(a); per[s]=np.median(a)
        c = df.close.values
        m1.append(np.abs(c[1:]/c[:-1]-1)); m16.append(np.abs(c[16:]/c[:-16]-1))
    A=np.concatenate(A); m1=np.concatenate(m1); m16=np.concatenate(m16)
    L20 = 1/(3*A+MMR)
    rows.append(dict(tf=tf, atr_med=100*np.median(A), btc=100*per["btcusd"], sol=100*per["solusd"],
        H1_med=100*np.median(m1), H1_p90=100*np.quantile(m1,.9), H16_med=100*np.median(m16), H16_p90=100*np.quantile(m16,.9),
        liq20_over_atr=0.045/np.median(A), tp20_over_atr=0.005/np.median(A), share_3atr_at20=np.mean(L20>=20),
        medL3=np.median(L20)))
pd.set_option("display.width",250)
print(pd.DataFrame(rows).round(4).to_string(index=False))
