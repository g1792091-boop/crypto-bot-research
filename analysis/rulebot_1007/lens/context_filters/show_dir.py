import sys, site
sys.path.append(site.getusersitepackages())
import pandas as pd, numpy as np
pd.set_option('display.width', 250)
J = pd.read_csv(sys.argv[1])
for name, g in J.groupby('direction'):
    for prim, h in g.groupby('primary'):
        print('==', name, 'primary' if prim else 'secondary(1h)')
        print(' contrasts', len(h), 'disc testable', int(h.disc_testable.sum()), 'disc p<.05', int((h.disc_testable & (h.p_two_disc < .05)).sum()),
              'disc BH q<.10', int((h.disc_q < .10).sum()), 'carried & test testable', int((h.carried & h.test_testable).sum()),
              'test 1s p<.05', int((h.p_test_1s < .05).sum()), 'test q<.05', int((h.test_q < .05).sum()), 'replicated', int(h.replicated.sum()),
              'same sign among carried', int((h.carried & h.test_testable & h.same_sign).sum()))
        c = h[h.carried].sort_values('p_two_disc')
        print(c[['tf','feature','bucket','n_in_disc','d_disc','se_disc','p_two_disc','disc_q','n_in_test','d_test','se_test','p_test_1s','p_test_1s_4h','test_q','replicated','mde80_test']].round(3).to_string())
