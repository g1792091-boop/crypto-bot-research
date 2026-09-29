# Vendored signal code from the backtest session

Copied byte-for-byte from branch `claude/handover-doc-analysis-l7q9u7`, commit `a20ebe5`
("Add strategy x timeframe sweep results and handoff v2"), directory `analysis/sweep/`.

| here | source |
|---|---|
| `PREREG.md`, `PREREG.sha256` | `analysis/sweep/` |
| `harness/sweep_lib.py`, `harness/run_gate_tf.py` | `analysis/sweep/harness/` |
| `harness/vendor/*.py`, `VENDOR_SHA256.txt` | `analysis/sweep/harness/vendor/` |
| `classify/classification.csv` | `analysis/sweep/classify/` (sha256 `1c3f2cdc0851cfc4181d887325883a8d23757b49f5ce4b01db0fe0666a8a6ce8`) |

Rules (handover v2, section 8): the bot imports this code and does not rewrite it. Do not edit
these files. `paperbot/sweepsig.py` checks every hash in `PREREG.sha256` before loading and
refuses to run if one differs. Check by hand: `cd third_party/sweep && sha256sum -c PREREG.sha256`.
