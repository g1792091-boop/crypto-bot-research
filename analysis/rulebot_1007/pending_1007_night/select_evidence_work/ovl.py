import csv,sys,collections,itertools
base=sys.argv[1]
runs=['run-20261005T014624Z','run-20261005T183457Z','current']
S=collections.defaultdict(set)   # (strat,tf)-> set of (run,bar,sym,side)
W=collections.defaultdict(set)   # window version: (run, hourbucket, sym, side)
for r in runs:
    for row in csv.DictReader(open(f'{base}/{r}/signal_log.csv')):
        if row['status']!='SUBMITTED' or row['strategy'].startswith('RANDOM'): continue
        tf=row['timeframe']
        if tf not in ('15m','30m','1h'): continue
        b=int(row['bar_close'])
        S[(row['strategy'],tf)].add((r,b,row['symbol'],row['side']))
        W[(row['strategy'],tf)].add((r,b//(4*3600*1000),row['symbol'],row['side']))
for tf in ('15m','30m','1h'):
    keys=[k for k in S if k[1]==tf and len(S[k])>=10]
    out=[]
    for a,b in itertools.combinations(sorted(keys),2):
        c=len(S[a]&S[b]); m=min(len(S[a]),len(S[b]))
        cw=len(W[a]&W[b]); mw=min(len(W[a]),len(W[b]))
        if c/m>=0.5 or cw/mw>=0.8:
            out.append((round(c/m,2),round(cw/mw,2),a[0],b[0],len(S[a]),len(S[b])))
    out.sort(reverse=True)
    print('==',tf,len(keys),'cells; pairs exact>=0.5 or 4h-window>=0.8:',len(out))
    for o in out[:60]: print(*o)
