"""Own fixed-leverage replay of every ds200 SUBMITTED signal (v4), through analyze.py's engine wrappers (imported, not edited).
args: <verify_dir> <analyze.py> <export_root> <repo> <out_csv>"""
import sys, site, importlib.util, os
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
vdir, apath, eroot, repo, out = sys.argv[1:6]
sys.path.insert(0, repo)
spec = importlib.util.spec_from_file_location("an_mod", apath); an = importlib.util.module_from_spec(spec)
sys.modules["an_mod"] = an; spec.loader.exec_module(an)
import numpy as np, pandas as pd
from paperbot.config import Tier, v3_settings
run = an.Run(eroot, "current")
taker = an.implied_taker(run)
brackets, _ = an.make_brackets(None)
specs = an.infer_specs(run.trades)
rates, finfo = an.infer_funding(run.trades, run.bars)
ts_list, ssteps = an.build_steps(run.bars, rates)
strength = an.load_ctx_strength(run.ctx_path)
acc = run.accounts.set_index("account_id")
sub = run.sig[run.sig.status == "SUBMITTED"]
sigs = []
for r in sub.itertuples(index=False):
    aid = f"{r.strategy}@{r.timeframe}"
    if acc["kind"].get(aid) != "ds200":
        continue
    d = dict(sig_id=int(r.id), bar_close=int(r.bar_close), timeframe=r.timeframe, strategy=r.strategy, symbol=r.symbol,
             side=int(r.side), atr=an.fnum(r.atr), ref_price=an.fnum(r.ref_price),
             ref_time=int(r.ref_time) if r.ref_time == r.ref_time else None, delay_ms=int(r.delay_ms) if r.delay_ms == r.delay_ms else None)
    ctx = strength.get(int(r.id)); d["data"] = {"ctx": ctx} if ctx else {}
    sigs.append(d)
print("signals", len(sigs), "taker", taker, finfo)
res = []
for L in (10, 20, 30, 40, 50):
    S = v3_settings(taker_fee=taker, min_leverage=5, min_margin_frac=0.05, max_margin_frac=0.50,
                    tiers=(Tier("best", L / 100, (L,)), Tier("normal", L / 100, (L,))))
    an._G.clear(); an._G.update(sigs=sigs, ssteps=ssteps, ts_list=ts_list, settings=S, brackets=brackets, specs=specs, flip=False)
    rows = an._replay_chunk(list(range(len(sigs))))
    df = pd.DataFrame(rows); df["L"] = L; res.append(df)
    print(L, df.status.value_counts().to_dict(), flush=True)
R = pd.concat(res, ignore_index=True)
R.to_csv(out, index=False)
