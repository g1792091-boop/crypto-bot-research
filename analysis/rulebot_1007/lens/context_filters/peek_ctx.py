import sys, json, collections
for path in sys.argv[1:]:
    keys = collections.Counter(); sr = collections.Counter(); vals = collections.defaultdict(collections.Counter)
    n = 0
    with open(path) as fh:
        for line in fh:
            d = json.loads(line); n += 1
            c = d.get("ctx") or {}
            for k, v in c.items():
                keys[k] += 1
                if isinstance(v, str): vals[k][v] += 1
                if k == "sr" and isinstance(v, dict):
                    for kk in v: sr[kk] += 1
                if k == "strength" : vals["strength_type"][type(v).__name__] += 1
    print(path, n)
    print(" keys", dict(keys))
    print(" sr", dict(sr))
    for k, c in vals.items(): print(" ", k, dict(c.most_common(12)))
