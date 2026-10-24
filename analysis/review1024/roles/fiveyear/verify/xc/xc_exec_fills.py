"""Verifier part 3: real live executor trades (read-only sqlite from the untrusted extra export, path given as
arguments): entry latency after the signal bar close, entry price vs the paper/reference price, real vs assumed cost.
    python3 -I xc_exec_fills.py <executor db> ..."""
import sqlite3
import sys
import json
import statistics as st

for f in sys.argv[1:]:
    con = sqlite3.connect("file:" + f + "?mode=ro", uri=True)
    cols = [d[1] for d in con.execute("pragma table_info(trades)")]
    print("==", f.split("/")[-1])
    lat, slp, rc, ac = [], [], [], []
    for r in con.execute("select * from trades order by entry_ts"):
        d = dict(zip(cols, r))
        dd = json.loads(d.get("data") or "{}")
        et = dd.get("entry_time")
        lat_s = (d["entry_ts"] - et) / 1000 if et else None
        pe, ep, er = dd.get("paper_entry"), d.get("entry_price"), dd.get("entry_ref")
        adv = None
        if pe and ep:
            adv = d["side"] * (ep / pe - 1) * 100      # + = paid more than the paper entry (adverse), in %
        notional = (d["qty"] or 0) * (ep or 0)
        rcp = (d.get("real_cost") or 0) / notional * 100 if notional else None
        acp = (d.get("assumed_cost") or 0) / notional * 100 if notional else None
        print(f"{d['key'][:40]:40s} side {d['side']:+d} lev {d['leverage']} lat {lat_s} s  paper {pe} fill {ep} ref {er} "
              f"adverse {adv if adv is None else round(adv, 4)} %  notional {notional:.0f}  real_cost {rcp if rcp is None else round(rcp, 4)} % "
              f"assumed {acp if acp is None else round(acp, 4)} %  exit {d['exit_reason']}  mode {d.get('mode')}")
        if lat_s is not None:
            lat.append(lat_s)
        if adv is not None:
            slp.append(adv)
        if rcp is not None and d.get("exit_ts"):
            rc.append(rcp)
            ac.append(acp)
    if lat:
        print(f"  latency s: median {st.median(lat):.1f} min {min(lat):.1f} max {max(lat):.1f} n {len(lat)}")
    if slp:
        print(f"  entry vs paper (adverse +): mean {st.mean(slp):.4f} % median {st.median(slp):.4f} % n {len(slp)}")
    if rc:
        print(f"  round-trip real cost {st.mean(rc):.4f} % vs assumed {st.mean(ac):.4f} % of notional (n {len(rc)})")
