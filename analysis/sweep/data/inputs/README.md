# Sweep input data (committed copy)

The ~1 GB of sweep input CSVs (full/ is/ oos/ final/ x 8 timeframes x 7 coins, 224 files) is rebuilt from the
7 base 5-minute series in this folder (`<coin>usd-5m.csv.xz`, 63 MB, identical to `full/<coin>usd-5m.csv`).

    cd analysis/sweep/data/inputs && python3 rebuild.py            # writes ../full ../is ../oos ../final
    # or: python3 rebuild.py /some/dir  and  export SWEEP_DATA=/some/dir

`rebuild.py` checks every file against `../MANIFEST.json` (tested: sha256 match 224 / 224).
Source: Astral (Polygon) spot USD aggregate, see `../NOTES.md` for provenance, clean_from dates and known defects.
