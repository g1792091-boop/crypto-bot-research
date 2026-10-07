import json, sys, datetime, site
sys.path.append(site.getusersitepackages())
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import features as F
proto = {
  "written_utc": datetime.datetime.utcnow().isoformat(),
  "note": "written before any outcome-by-context statistic was computed (only context-free design checks: design_effect_by_block.csv, peek_dist.py)",
  "unit": "one SUBMITTED signal, outcome = net R of the signal run alone (replay for v3b/v4; trade or skipped shadow for v3a, v3a restricted to the shadow-covered window)",
  "universe": "kind strategy (core 36) for cross-run tests; ds200 (v4 only) as a transfer target; tf 15m and 30m primary, 1h secondary (separate BH family)",
  "contrast": "mean R in bucket minus mean R of the other signals of the same run x tf x kind; runs pooled as n-weighted within-run differences",
  "clusters": "time blocks run x floor(bar_close / 2h) (main) and 4h (sensitivity); bootstrap SE (B=2000, blocks resampled within run); t with df = sum(G_r - 1)",
  "min_n": "bucket and rest >= 5 per run to enter, total in-bucket >= 30 to be tested",
  "direction_A": "discover on v3a (two-sided p < 0.05, also BH q < 0.10 reported) -> test on v3b+v4 one-sided in the discovered direction; BH q 0.05 across all carried tests",
  "direction_B": "discover on v4 -> test on v3a+v3b, same rules",
  "replicated": "OOS BH q < 0.05 one-sided at 2h blocks AND one-sided p < 0.05 at 4h blocks AND same sign",
  "omnibus": "correlation of all contrast effects v3a vs v4 (per tf), null from circular index shifts of R within run x tf (1000 draws)",
  "multivariate": "ridge regression on all bucket dummies, fit on one run, filter top third on the other; uplift vs all signals, cluster bootstrap CI and circular-shift null",
  "robustness": "winsorized R clip(-2, 3), win rate, gross R estimate (R + 2(taker+slip)/stop_frac)",
  "features": {k: {"desc": v[0], "buckets": v[1]} for k, v in F.FEATURES.items()},
  "binary_once": F.BINARY_ONE_TEST,
  "er_cuts": F.ER_CUTS, "stop_cuts": F.STOP_CUTS,
  "hypotheses": [dict(zip(["id", "family", "feature", "hi", "lo", "sign"], h)) for h in F.HYP],
  "per_strategy_features": F.PER_STRATEGY_FEATURES,
  "n_contrasts_per_cell": len(F.contrasts()),
}
json.dump(proto, open(sys.argv[2], "w"), indent=1)
print(len(F.contrasts()), "contrasts per tf x kind cell")
