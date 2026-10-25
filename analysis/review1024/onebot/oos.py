exec(open('onebot.py').read().split("res=[]")[0])
Q1=A0+(MID-A0)//2; Q3=MID+(Z0-MID)//2
def robust_pick(p1,p2,k=None,min_n=2):
    out=[]
    for c in cells:
        best=None
        for mode in ('B','S','L'):
            e1,n1=solo((c,mode),*p1); e2,n2=solo((c,mode),*p2)
            if n1>=min_n and n2>=min_n and e1>1 and e2>1:
                s=min(e1,e2)
                if best is None or s>best[0]: best=(s,(c,mode))
        if best: out.append(best)
    out.sort(reverse=True)
    return [m for _,m in (out if k is None else out[:k])]
def v39_plus_short(p,k=3):
    sc=[]
    for c in cells:
        if c=='V39_ALL@1h': continue
        e,n=solo((c,'S'),*p)
        if n>=3: sc.append((e,c))
    sc.sort(reverse=True); return [('V39_ALL@1h','B')]+[(c,'S') for _,c in sc[:k]]
rows=[]
for name,pick,check in (('앞 절반의 두 4분기로 고름 → 뒤 절반',((A0,Q1),(Q1,MID)),(MID,Z0)),('뒤 절반의 두 4분기로 고름 → 앞 절반',((MID,Q3),(Q3,Z0)),(A0,MID))):
    for k in (3,5,8,None):
        mem=robust_pick(*pick,k=k)
        eq,dd,n,took=run(mem,*check)
        rows.append((name,f'두 4분기 모두 플러스 상위 {k or "전부"}개',len(mem),round(eq,2),round(dd,2),n,round(float((r[took]>0).mean()),2) if n else None,int((side[took]<0).sum()) if n else 0))
    p=(pick[0][0],pick[1][1])
    for k in (3,5):
        mem=v39_plus_short(p,k); eq,dd,n,took=run(mem,*check)
        rows.append((name,f'V39 + 숏 전용 상위 {k}개',len(mem),round(eq,2),round(dd,2),n,round(float((r[took]>0).mean()),2) if n else None,int((side[took]<0).sum()) if n else 0))
    mem=[('V39_ALL@1h','B')]; eq,dd,n,took=run(mem,*check)
    rows.append((name,'V39 혼자',1,round(eq,2),round(dd,2),n,round(float((r[took]>0).mean()),2),int((side[took]<0).sum())))
    # coin baseline: random member sets of the same size (5) with random side modes, 300 draws
    rng=np.random.default_rng(11); xs=[]
    for _ in range(300):
        mem=[(cells[i],('B','S','L')[rng.integers(3)]) for i in rng.choice(len(cells),5,replace=False)]
        xs.append(run(mem,*check)[0])
    rows.append((name,'무작위 5개 (300번) 가운데 / 상위 10%',5,round(float(np.median(xs)),2),None,None,None,round(float(np.quantile(xs,0.9)),2)))
df=pd.DataFrame(rows,columns=['나누기','방법','멤버','확인 기간 배수(12배)','최대낙폭','거래','승률','숏 수(무작위는 상위10%)'])
print(df.to_string(index=False)); df.to_csv('oos.csv',index=False)
