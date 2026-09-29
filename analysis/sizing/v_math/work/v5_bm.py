"""Verifier part 5: closed-form Brownian-with-drift break-even (sanity check of injected-drift IR)."""
import numpy as np
from scipy.optimize import brentq
sig_ann = 0.002790742766575803*np.sqrt(365*288)   # pooled 5m sd, annualised
def p_up(theta, a, b):  # P(hit +a before -b), X = nu t + sigma W, theta = 2 nu / sigma^2
    if abs(theta) < 1e-12: return b/(a+b)
    return (1 - np.exp(theta*b)) / (np.exp(-theta*a) - np.exp(theta*b))
for L, pstar in ((20, 0.9351), (30, 0.947), (50, 0.9724)):
    a, b = 0.10/L, 1/L - 0.005
    # arithmetic price barriers approximated in log space
    a, b = np.log(1+a), -np.log(1-b)
    th = brentq(lambda t: p_up(t, a, b) - pstar, 1e-9, 1e4)
    print(f"L={L}: p0={p_up(0,a,b):.4f} theta={th:.2f} -> annual IR = theta*sigma/2 = {th*sig_ann/2:.2f}")
