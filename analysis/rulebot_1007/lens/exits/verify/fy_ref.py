import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
F = pd.read_csv(sys.argv[1], low_memory=False)
keys = [("N17_KC_RSI","15m"),("N17_KC_RSI","30m"),("N20_EMA9_CHOP","30m"),("N20_EMA9_CHOP","15m"),("F6_VWAP_CROSS","1h"),("N18_VWMA_MACD","30m"),("F4_PULL","15m"),("S4_BB_BBP","15m"),("N22_VORTEX_PSAR","15m")]
for s, tf in keys:
    g = F[(F.strategy==s)&(F.timeframe==tf)]
    for r in g.itertuples():
        if r.source == "profiles_binance":
            print(f"{s:16s} {tf} 5y every-signal n {int(r.n_signals)} mean_roe {r.mean_roe:+.4f} t {r.mean_roe_t:+.1f} IS {r.mean_roe_is:+.4f} CF {r.mean_roe_cf:+.4f} ret/notional {r.mean_ret_notional*1e4:+.1f}bps")
        else:
            print(f"{s:16s} {tf} ds200 {r.variant} IS mean% {r.ds_is_mean_pct:+.3f} CF {r.ds_cf_mean_pct:+.3f} pre {r.ds_pre_mean_pct:+.3f} gross IS {r.ds_is_gross_mean_pct:+.3f}")
