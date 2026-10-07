import csv, json, sys, re
ps, fy, ov15 = sys.argv[1], sys.argv[2], sys.argv[3]
fy=json.load(open(fy)); ov=json.load(open(ov15))
rows=[x for x in csv.DictReader(open(ps)) if x['period']=='all' and x['combo']=='ALL|LTF']
short=sys.argv[4].split(',')
out={}
for x in rows:
    s=x['strategy']
    if s not in short: continue
    mix=dict((a,int(b)) for a,b in re.findall(r'(\w+):(\d+)',x['tf_mix']))
    N=sum(mix.values()); mu=0; m2=0
    for tf,c in mix.items():
        f=fy.get(s+'@'+tf)
        if not f or c==0: continue
        w=c/N; mu+=w*f['meanR']; m2+=w*(f['sdR']**2+f['meanR']**2)
    sd=(m2-mu*mu)**0.5
    tpd=float(x['trades_per_day'])
    def wk(d,sdv): return round((2.8*sdv/d)**2/tpd/7,1)
    out[s]=dict(tpd=round(tpd,2),sd=round(sd,2),mix={k:round(v/N,3) for k,v in mix.items()},netR=round(float(x['meanR']),3),gross=round(float(x['mean_gross']),3),
        wk_unpaired_0p1=wk(0.1,sd),wk_unpaired_0p2=wk(0.2,sd),wk_paired_0p1=wk(0.1,sd*0.5**0.5),wk_paired_0p2=wk(0.2,sd*0.5**0.5),
        mde_by_1231_unpaired=round(2.8*sd/(tpd*75)**0.5,3),mde_by_1231_paired=round(2.8*sd*0.5**0.5/(tpd*75)**0.5,3),
        mde_wave2_61d_paired=round(2.8*sd*0.5**0.5/(tpd*61)**0.5,3))
for s,v in out.items(): print(s,v)
# overlap among shortlist
print('--- 15m exact overlap among shortlist (>=0.15)')
for k,v in sorted(ov.items(),key=lambda t:-t[1]):
    a,b=k.split('|')
    if a in short and b in short and v>=0.15: print(v,k)
json.dump(out,open(sys.argv[5],'w'))
