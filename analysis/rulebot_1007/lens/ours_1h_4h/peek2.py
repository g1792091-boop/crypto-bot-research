import site, sys, json
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import pandas as pd, numpy as np
E = sys.argv[1]
for run in ['run-20261005T014624Z', 'run-20261005T183457Z', 'current']:
    sl = pd.read_csv(f'{E}/{run}/signal_log.csv')
    print(run, sl.status.value_counts().to_dict(), sl.timeframe.value_counts().to_dict())
    rec = sl[sl.status == 'RECORD']
    print(' RECORD by tf/symbol', rec.groupby(['timeframe']).size().to_dict(), rec.symbol.value_counts().head(8).to_dict())
    rows = []
    with open(f'{E}/{run}/signal_ctx.jsonl') as fh:
        for line in fh:
            d = json.loads(line); c = d.get('ctx') or {}
            rows.append((d['id'], c.get('tf'), c.get('htf'), c.get('htf_regime'), c.get('regime')))
    cx = pd.DataFrame(rows, columns=['id', 'tf', 'htf', 'htf_regime', 'regime'])
    print(pd.crosstab(cx.tf, cx.htf_regime.fillna('NA')))
    print(' ts range', pd.to_datetime(sl.bar_close.min(), unit='ms'), pd.to_datetime(sl.bar_close.max(), unit='ms'))
