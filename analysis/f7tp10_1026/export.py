"""results.json for the repository from the work folder's study.json files: counts, win rates, mean net ROE, the wallet as a
multiple of its start (owners' rule D11: no DeepSeek backtest money in the repository) and the coin-flip twins' multiples.
Run: python3 export.py --main WORK/study_main.json --flips WORK/flipwork/study.json --out results.json"""
from __future__ import annotations

import argparse
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
KEEP = ("n", "win", "mean_roe", "avg_win", "avg_loss", "mdd", "bust", "mean_log", "sl")


def clean(d: dict) -> dict:
    out = {k: d[k] for k in KEEP if k in d}
    if "end" in d:
        out["wallet_x"] = round(d["end"] / 1000.0, 4)
    f = d.get("flip")
    if f:
        out["flip"] = {"n": f["n"], "wallet_x_p5": round(f["end_p5"] / 1000, 4), "wallet_x_p50": round(f["end_p50"] / 1000, 4),
                       "wallet_x_p95": round(f["end_p95"] / 1000, 4), "mean_roe_p50": f["mean_roe_p50"],
                       "mean_roe_p95": f["mean_roe_p95"], "beat_share": f["beat_share"]}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", required=True)
    ap.add_argument("--flips", required=True)
    ap.add_argument("--out", default=os.path.join(HERE, "results.json"))
    a = ap.parse_args(argv)
    main_, flips = json.load(open(a.main)), json.load(open(a.flips))
    arms = {}
    for arm, wins in main_.items():
        arms[arm] = {}
        for wn, d in wins.items():
            fd = flips.get(arm, {}).get(wn, {})
            arms[arm][wn] = clean({**d, **({"flip": fd["flip"]} if "flip" in fd else {})})
    plan = hashlib.sha256(open(os.path.join(HERE, "PLAN.md"), "rb").read()).hexdigest()
    json.dump({"plan_sha256": plan, "note_ko": "창마다 $1,000에서 새로 시작. 딥시크 매매법이라 금액 없이 지갑 배수만(D11).",
               "arms": arms}, open(a.out, "w"), indent=1, ensure_ascii=False)
    print(a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
