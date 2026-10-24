"""Funding paid in the rule bot's real paper trades (forward window) -- the study's recomputed outcomes use funding 0
for October. Read-only over ../data forward_rule.csv.gz (built from the export)."""
import sys
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
import rolesdata as RD
from common import *
F = RD.forward("rule")
F = F[(F.taken == 1) & F.tr_roe.notna() & F.tf.isin(TFS) & (F.coin >= 0)].copy()
print(len(F))
print(F[["tr_funding", "tr_fees", "tr_margin", "tr_leverage", "tr_pnl", "tr_roe"]].describe().T)
F["notional"] = F.tr_margin * F.tr_leverage
F["fund_frac"] = F.tr_funding / F.notional      # sign as stored
F["fees_frac"] = F.tr_fees / F.notional
for sd in (1, -1):
    x = F[F.side == sd]
    print("side", sd, "n", len(x), "funding/notional mean %.6f%%" % (100 * x.fund_frac.mean()),
          "fees/notional mean %.4f%%" % (100 * x.fees_frac.mean()),
          "funding x35 ROE pts %.3f" % (100 * 35 * x.fund_frac.mean()),
          "share nonzero %.3f" % (x.tr_funding != 0).mean())
