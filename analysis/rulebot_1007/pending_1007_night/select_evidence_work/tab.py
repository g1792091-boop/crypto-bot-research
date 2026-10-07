import csv,sys,math
P='/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/fiveyear/verify3/'
rows=list(csv.DictReader(open(P+'agg_cells.csv')))
# BH over n>=200 cells
el=[r for r in rows if float(r['n'])>=200]
ps=sorted([(float(r['gross_p']),i) for i,r in enumerate(el)])
m=len(ps); q=[0]*m; prev=1
for rank in range(m,0,-1):
    p,i=ps[rank-1]; v=min(prev,p*m/rank); q[i]=v; prev=v
qd={(r['kind'],r['strategy'],r['tf']):q[i] for i,r in enumerate(el)}
print('BH cells',m, 'pos q<.05',sum(1 for i,r in enumerate(el) if q[i]<.05 and float(r['grossR'])>0),'neg',sum(1 for i,r in enumerate(el) if q[i]<.05 and float(r['grossR'])<0))
out=[]
for r in rows:
    k=(r['kind'],r['strategy'],r['tf'])
    f=lambda x: float(x) if x not in ('',None) else float('nan')
    out.append(dict(kind=r['kind'][:2],s=r['strategy'],tf=r['tf'],d=f(r['per_day_sized']),n=int(f(r['n'])),net=f(r['netR']),g=f(r['grossR']),gt=f(r['gross_t']),gi=float(r['g_is']) if r['g_is'] else float('nan'),gc=float(r['g_cf']) if r['g_cf'] else float('nan'),q=qd.get(k,float('nan'))))
w=csv.writer(open('cells.csv','w'));w.writerow(out[0].keys())
for o in out: w.writerow([round(v,4) if isinstance(v,float) else v for v in o.values()])
