import site, sys, time
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
sys.path.insert(0, '/home/user/crypto-bot-research')
import numpy as np
from collections import namedtuple
from paperbot.context import regime, REGIME_N
B = namedtuple('B', 'high low close')
z = np.load(sys.argv[1])
bars = [B(h, l, c) for h, l, c in zip(z['h'].tolist(), z['l'].tolist(), z['c'].tolist())]
t = time.time()
n = REGIME_N['1h']
labs = [regime(bars[j - n + 1:j + 1], n)['label'] for j in range(n, n + 5000)]
print(time.time() - t, {k: labs.count(k) for k in set(labs)})
