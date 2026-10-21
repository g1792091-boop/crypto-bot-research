"""All five-year runs of PREREG.md: C0..C7 (C0 = D0, the current rules), D1..D4 shadows, the fee sensitivity.
Run: python3 -I runall.py group   (group: exits | entries)  -> out/runs/<name>_trades.csv.gz, _cand.csv.gz, _info.json"""
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine5y import *

L20 = {"first_lock": 0.20, "trigger_gap": 0.01, "next_trigger": 0.25, "next_gap": 0.03, "step": 0.05}
L30 = {"first_lock": 0.30, "trigger_gap": 0.01, "next_trigger": 0.35, "next_gap": 0.03, "step": 0.05}
EXITS = [  # same entry rules -> the candidates are shared
    variant(name="C0_current"),
    variant(name="C1_lev20", lev={"default": 20}),
    variant(name="C2_lev10", lev={"default": 10}),
    variant(name="C3_lock20", ladder=L20),
    variant(name="C4_lock30", ladder=L30),
    variant(name="C5_stop35", stop_roe=0.35),
    variant(name="C6_lev20_lock20", lev={"default": 20}, ladder=L20),
    variant(name="C7_lev20_lock20_stop35", lev={"default": 20}, ladder=L20, stop_roe=0.35),
    variant(name="D1_time4", time_bars=4),
    variant(name="S_taker0044_bybit", taker=0.00044),
    variant(name="S_taker0042_woo", taker=0.00042),
]
ENTRIES = [
    variant(name="D2_immediate", entry="immediate"),
    variant(name="D3_vote4", vote_min=4),
    variant(name="D4_maker", entry="maker"),
]


def save(v, T, cand, info):
    os.makedirs(f"{OUT}/runs", exist_ok=True)
    T.to_csv(f"{OUT}/runs/{v['name']}_trades.csv.gz", index=False)
    cand[["t0", "label", "coin", "side", "tf", "stage", "entry_t"]].to_csv(f"{OUT}/runs/{v['name']}_cand.csv.gz", index=False)
    json.dump(info, open(f"{OUT}/runs/{v['name']}_info.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    group = sys.argv[1]
    t0 = time.time()
    sig = load_signals(BASE["start"], BASE["end"])
    mk = markets()
    print(f"loaded {len(sig)} signals, markets {time.time() - t0:.0f}s", flush=True)
    if group == "exits":
        c = candidates(EXITS[0], sig, mk)
        print(f"candidates {time.time() - t0:.0f}s", flush=True)
        for v in EXITS:
            T, cand, info = run(v, sig=sig, cand=c)
            save(v, T, cand, info)
    else:
        for v in ENTRIES:
            T, cand, info = run(v, sig=sig)
            save(v, T, cand, info)
    print(f"done {time.time() - t0:.0f}s", flush=True)
