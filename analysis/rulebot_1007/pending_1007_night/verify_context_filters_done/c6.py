import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1]); sys.dont_write_bytecode = True
from lib import *
A = load(kinds=('strategy', 'ds200'))
cells = [('S4_BB_BBP', '15m'), ('S4_BB_BBP', '30m'), ('N18_VWMA_MACD', '15m'), ('N25_DST_CCI', '15m'), ('N01_ST_EMA', '15m'), ('N10_HA_PSAR', '30m'), ('N20_EMA9_CHOP', '30m'), ('N17_KC_RSI', '15m'), ('F3_HHHL', '15m'), ('F7_RF_TRIPLE', '15m'), ('F6_VWAP_CROSS', '15m'), ('F4_PULL', '15m')]
for s, tf in cells:
    X = A[(A.strategy == s) & (A.timeframe == tf)]
    per = X.groupby('run').R.agg(['size', 'mean']).round(3)
    y = X.R.values; cl = X.run.values + (X.bar_close.values // (2 * H)).astype(str)
    u, inv = np.unique(cl, return_inverse=True); r = np.bincount(inv, y - y.mean()); se = np.sqrt(np.sum(r ** 2)) / len(y)
    fl = X.flipR.dropna()
    print(s, tf, 'n', len(X), dict(zip(per.index, zip(per['size'], per['mean']))), 'pooled', round(y.mean(), 3), 'clSE', round(se, 3), 'side-flip(R-flip)', round((X.R - X.flipR).mean(), 3), 'ndays', X.kst_day.nunique(), 'long', round(X.long.mean(), 2))
