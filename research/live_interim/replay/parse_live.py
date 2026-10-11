"""Parse the owners' pasted interim_full output into live_cells.json (core money; DS labels only)."""
import json
import re
import sys

txt = open(sys.argv[1]).read()
core, ds = {}, {}
sec = None
for line in txt.splitlines():
    if line.startswith("[4. "):
        sec = 4
        continue
    if line.startswith("[5. "):
        sec = 5
        continue
    if line.startswith("[6. "):
        sec = None
    if sec == 4:
        m = re.match(r"^\d+\. (\w+)(?: ★관찰)? \(([+−])\$([\d,]+)\): (.*)$", line)
        if not m:
            continue
        name = m.group(1)
        for part in m.group(4).split(" · "):
            tf = part.split()[0]
            if "거래 없음" in part:
                core[f"{name}@{tf}"] = {"n": 0}
                continue
            mm = re.match(r"(\w+) (\d+)건 (\d+)% ([+-][\d.]+)% \$([\d,]+) 낙폭(\d+)%( 파산)? \[([^\]]*)\]", part)
            if not mm:
                print("??", part)
                continue
            core[f"{name}@{tf}"] = {"n": int(mm.group(2)), "win": int(mm.group(3)) / 100,
                                   "mean": float(mm.group(4)) / 100,
                                   "wallet": float(mm.group(5).replace(",", "")), "dd": int(mm.group(6)) / 100}
    if sec == 5:
        m = re.match(r"^(\w+)(?: ★관찰)?: (.*)$", line)
        if not m:
            continue
        name = m.group(1)
        for part in m.group(2).split(" · "):
            tf = part.split()[0]
            if "거래 없음" in part:
                ds[f"{name}@{tf}"] = {"n": 0}
                continue
            mm = re.match(r"(\w+) (\d+)건 (\d+)% ([+−]) (↑|↓|파산)", part)
            if not mm:
                print("??", part)
                continue
            ds[f"{name}@{tf}"] = {"n": int(mm.group(2)), "win": int(mm.group(3)) / 100, "sign": mm.group(4),
                                 "wallet": mm.group(5)}
print(len(core), "core cells", len(ds), "ds cells")
json.dump({"core": core, "ds": ds}, open(sys.argv[2], "w"), ensure_ascii=False, indent=0)
