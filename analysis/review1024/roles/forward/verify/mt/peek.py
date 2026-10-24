import sys
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *
S = load("sig")
print(S.shape)
print(list(S.columns)[:80])
print(S.tj_why_1022.value_counts().head(20))
import json
mem = json.load(open("/home/user/crypto-bot-research/deploy/combo.trend.json"))["members"]
print([(m["strategy"], m["tf"]) for m in mem])
for m in mem:
    x = S[(S.name == m["strategy"]) & (S.tf == m["tf"])]
    print(m["strategy"], m["tf"], len(x), x.role.iloc[0] if len(x) else None, (x.tj_why_1022 == "").sum())
