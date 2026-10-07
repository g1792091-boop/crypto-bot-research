"""Parity: common.margin_rule vs paperbot.sizing.size_position (single candidate) on random signals."""
import sys; sys.path.insert(0, sys.argv[1]); sys.dont_write_bytecode = True
import numpy as np
import common as C
from paperbot.config import v3_settings, Tier
from paperbot.margin import Brackets, BracketTier
from paperbot.sizing import size_position
rng = np.random.default_rng(1)
bad = 0; n = 0
for coin in C.BR:
    br = Brackets([BracketTier(*t) for t in C.BR[coin]])
    for L in (20, 30, 40, 50):
        S = v3_settings(leverage_rule="tier_walk", tiers=(Tier("best", L / 100, (L,)),), max_margin_frac=0.5)
        for _ in range(300):
            side = int(rng.choice([-1, 1])); a = rng.uniform(0.0005, 0.02); entry = 100.0
            stop = entry - side * 2 * a * entry
            dec = size_position(S, 5000.0, side, entry, stop, "best", br, atr=a * entry, qty_step=0, min_notional=5)
            d = 2 * a
            m = C.margin_rule(coin, side, np.array([d]), np.array([a]), L)
            n += 1
            if bool(m['ok'][0]) != dec.ok:
                bad += 1
                if bad < 5: print(coin, L, side, a, dec.ok, dec.reasons, {k: v for k, v in m.items()})
            elif dec.ok and abs(dec.loss_at_stop / 5000 - m['lossf'][0]) > 1e-9:
                bad += 1; print('loss', dec.loss_at_stop / 5000, m['lossf'][0])
print('checked', n, 'mismatch', bad)
