import sys; exec(open(sys.argv[0].rsplit("/",1)[0]+"/h.py").read())
import json
for run in RUNS:
    print('####',run)
    r=rd(run,'runs.csv'); 
    for _,x in r.iterrows():
        d=json.loads(x.data); print(pd.to_datetime(x.started_ts,unit='ms'), d.get('settings_version'), {k:v for k,v in d.items() if k in('stopped_ts','ended_ts','reason','resume','resumed')})
    print('data keys', list(json.loads(r.data.iloc[-1]).keys()))
    s=rd(run,'signal_log.csv')
    print('RECORD by tf', s[s.status=='RECORD'].timeframe.value_counts().to_dict(), 'LATE by tf', s[s.status=='LATE'].timeframe.value_counts().to_dict())
    print('RECORD strategies sample', s[s.status=='RECORD'].strategy.value_counts().head(8).to_dict())
    # gaps: distinct 15m bar closes present vs expected
    b=np.sort(s[s.timeframe=='15m'].bar_close.unique()); gaps=np.diff(b)/60000
    print('15m bars with signals',len(b),'max gap min',gaps.max() if len(gaps) else None, 'gaps>60min', [(str(pd.to_datetime(b[i],unit='ms')),g) for i,g in enumerate(gaps) if g>60])
    eh=rd(run,'equity_hourly.csv'); print(eh.columns.tolist()[:8]); 
    tcol=[c for c in eh.columns if 'ts' in c or 'time' in c or 'hour' in c][0]
    t=np.sort(eh[tcol].unique()); print('eq hours',len(t), pd.to_datetime(t[0],unit='ms'), pd.to_datetime(t[-1],unit='ms'), 'gaps>1h', [(str(pd.to_datetime(t[i],unit='ms')),d/3.6e6) for i,d in enumerate(np.diff(t)) if d>3.6e6])
    a=rd(run,'accounts.csv'); print('created_ts uniq', pd.to_datetime(a.created_ts.unique(),unit='ms').tolist()[:6])
    o=rd(run,'outcomes.csv'); print('outcome step span', pd.to_datetime(o.step_ts.min(),unit='ms'), pd.to_datetime(o.step_ts.max(),unit='ms'))
