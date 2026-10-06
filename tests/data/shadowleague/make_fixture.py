"""Writes the committed synthetic bar fixtures of the shadow league tests (run once; the .csv.gz files are the fixture).

    python tests/data/shadowleague/make_fixture.py

SYNTHETIC random walks (research/reel5m/lib_reel5m.synth: volatility clusters, drifting regimes, zero edge), 4,000 bars each,
no timestamps (the tests lay them on whatever bar grid they need). Seeds were picked because the MAIN rule finds both
shorts and longs in them. Values are written with full precision, so reading them back gives the same floats."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "research", "reel5m"))
import lib_reel5m as R  # noqa: E402

for seed in (10, 1, 24):
    df = R.synth(4000, "1h", seed)[["open", "high", "low", "close", "volume"]]
    df.to_csv(os.path.join(HERE, f"synth_{seed}.csv.gz"), index=False, compression={"method": "gzip", "mtime": 0})
    print("wrote", seed, len(df))
