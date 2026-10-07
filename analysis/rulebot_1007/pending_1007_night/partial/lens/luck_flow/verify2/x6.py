import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from vc import *
import re
for lab in RUNS:
    o=load(lab,"outcomes")
    r=o[o.status=="REJECTED"]
    print("==",lab,len(r))
    for d in r.detail.head(3): print(d[:600])
    # failure reason at the 20x candidate
    def at20(d):
        try: j=json.loads(d)
        except: return "parse"
        rs=j.get("reasons",[])
        x=[q for q in rs if "/20x" in q]
        return re.sub(r"[\d\.e\-]+","#",x[-1]) if x else "no20x:"+"|".join(rs)[:80]
    print(r.detail.map(at20).value_counts().to_string())
    e=o[(o.status=="ENTERED")&(o.sig_timeframe=="4h")]
    lev=e.detail.map(lambda d: json.loads(d).get("leverage"))
    print("4h entered leverage:",lev.value_counts().to_dict())
