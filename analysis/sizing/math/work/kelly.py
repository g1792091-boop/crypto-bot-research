"""Binary-bet Kelly on the empirical class means (5m paths, zero-edge classes): win probability needed for the
Kelly-optimal margin fraction f* (of equity) to be >= M (full Kelly) or >= 2M (so that M is half-Kelly)."""
import numpy as np, pandas as pd
from common import *
br = pd.read_csv(f"{OUT}/bracket_zero_edge.csv")
b = br[(br.tf == "5m") & (br.res == "5m")]
rows = []
for var in ("liq", "stop1.0", "stop0.5"):
    for L in LEVS:
        r = b[(b.L == L) & (b.variant == var)].iloc[0]
        w, lo = r.winROE_adv, -r.lossROE_adv          # lo > 0: fraction of margin lost
        # binary Kelly on margin fraction: f* = p/lo - (1-p)/w  ->  p = (f + 1/w) / (1/lo + 1/w)
        need = lambda f: (f + 1 / w) / (1 / lo + 1 / w)
        row = dict(variant=var, L=L, win_roe=w, loss_roe=-lo, p_free=r.pTP_adv, p_breakeven=need(0.0))
        for M in MARGINS:
            row[f"p_fullKelly_M{int(M*100)}"] = need(M)
            row[f"p_halfKelly_M{int(M*100)}"] = need(2 * M)
        # Kelly margin fraction at the free (zero-edge) p and at p_free + 3pp
        for dp in (0.0, 0.03, 0.05):
            p = r.pTP_adv + dp
            row[f"fstar_at_free+{int(dp*100)}pp"] = p / lo - (1 - p) / w
        rows.append(row)
k = pd.DataFrame(rows)
k.to_csv(f"{OUT}/kelly_binary.csv", index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
print(k.round(4).to_string(index=False))
