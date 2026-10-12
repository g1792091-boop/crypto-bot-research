"""exitflex placebo (research/exitflex/PREREG_EXITFLEX.md section 6): the stratified random exit.

A rule that only shortens holds frees the account more often, and a random exit with the same timing profile does too. For
a variant V (not F7: it reads nothing by design) the placebo account has V's mode, check schedule (q15 included), hard stop,
sizing, period-end close and free fill minute; instead of V's rule it exits at a check with probability h[a, s, z], where
(a, s, z) is the stratum of its own position at that check:
  a  age bucket of the check index k: {1}, {2}, {3-4}, {5-8}, {9-16}, {17-32}, {33-64}, {65 and more}
  s  1 when Rc >= 0 (the check close is not at a net loss), else 0
  z  V's precondition, 1 where V could fire at this check on some close: F1, F1 q15 a reference exists; F6.w.d a reference
     exists and Rc < -d; F2 armed before the check; F5 armed; F8 armed and a reference; F9 a reference and (armed or Rc <
     -0.5R); F11 a finite invalidation level or an armed / event component (and the strategy's own 'can fire here' flag);
     F3, F4, F4 q15, F10 always 0
     F12 a swing reference exists, or F2 is armed, or F5 is armed, or F11's own z is 1 (F6's precondition adds nothing; F3, F4, F7h and
     F10 set none)
all computed from the state frozen at the end of the previous minute (the kernel's step 0), as the rule's own decision is.
F12 carries its own 8-hour clock (prereg 6): the first pick-timeframe check at or after C0 + 8 h (the clock check) is left out of the
hazard table (kernel_x counts neither its numerator nor its denominator), and the F12 placebo exits there with probability 1 and no
draw; before it, it exits at u < h as any placebo does. Its holds therefore never exceed F12's.
h comes from V's own quarter-size account of the same pick and period: RULE exits at checks of the stratum over the checks of
the stratum at which the position was still open after steps 1-5 of the check's minute (kernel_x counts both).
The draw of a check depends only on (V, period, seed, coin, check close time), not on the pick: u = (splitmix64(
splitmix64(base) XOR key) >> 11) / 2^53, key = coin index x 2^36 + close ms // 60,000 (the coin index is the position in the
priority order BTC, ETH, SOL, DOGE, LTC, BCH; the close is that of the latest closed chart bar of the check), base =
run._seed("exitflex", "placebo", V, period, s).

The numba pieces (draw, age bucket, the check itself) live in kernel_x; this file holds the plain-Python references that the
tests compare them with, the hazard tables, the seeds and the block runner.
"""

from __future__ import annotations

import math

import numpy as np

import data_x as DX
import kernel_x as KX

N_SEEDS = 200
AGE_LABELS = ("1", "2", "3-4", "5-8", "9-16", "17-32", "33-64", "65+")
MASK64 = (1 << 64) - 1


def age_bucket_py(k: int) -> int:
    """The age bucket of the check index k (1 = the first check), from the table in the pre-registration."""
    edges = (1, 2, 4, 8, 16, 32, 64)
    for b, hi in enumerate(edges):
        if k <= hi:
            return b
    return 7


def splitmix64_py(x: int) -> int:
    z = (x + 0x9E3779B97F4A7C15) & MASK64
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
    return z ^ (z >> 31)


def draw_u_py(base: int, coin: int, close_ms: int) -> float:
    key = coin * (1 << 36) + int(close_ms) // 60_000
    return (splitmix64_py(splitmix64_py(int(base)) ^ key) >> 11) / float(1 << 53)


def seed_base(variant_id: str, period: str, s: int) -> int:
    """run._seed("exitflex", "placebo", V, period, s): the pick is not part of the seed, so that two picks holding the same
    coin at the same check close draw the same u (prereg 6)."""
    return DX.seed_of("exitflex", "placebo", variant_id, period, s)


def hazard(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    """h[a, s, z] = RULE exits / checks at which the position was still open; 0 where there was no check."""
    h = np.zeros(num.shape)
    np.divide(num, den, out=h, where=den > 0)
    return h


def has_placebo(variant) -> bool:
    return KX.has_placebo(variant)


def run_block(market, pdata, variant, hz: np.ndarray, period: str, s0: int, s1: int, reduce_fn, scale: float = 0.25) -> list:
    """The placebo accounts of seeds s0 .. s1 - 1 (quarter size by default) for one pick and variant; ``reduce_fn(result)``
    turns each account into whatever the caller keeps."""
    if not has_placebo(variant):
        raise ValueError(f"{variant.id} has no placebo")
    out = []
    for s in range(s0, s1):
        r = KX.simulate(market, pdata, variant, scale, period, hz=hz, seed_base=seed_base(variant.id, period, s),
                        placebo=True)
        out.append(reduce_fn(r))
    return out


def pooled_means(Mp: np.ndarray) -> np.ndarray:
    """Seed-wise pooled mean: Mp has shape (picks, seeds) of the placebos' M_p; the pooled mean of seed s is the mean over
    the picks."""
    return np.asarray(Mp, float).mean(axis=0)


def percentiles(pooled: np.ndarray, qs=(5, 50, 95)) -> dict:
    """numpy's percentile (linear) of the placebo pooled means."""
    return {int(q): float(np.percentile(pooled, q)) for q in qs}


def binom_band_ok(num: int, den: int, h: float, alpha: float = 1e-3) -> bool:
    """True when ``num`` exits in ``den`` checks is within the two-sided (1 - alpha) binomial band around h (exact tails by
    log-gamma for small den, a normal approximation with continuity correction above 5,000 checks)."""
    if den <= 0:
        return num == 0
    if h <= 0.0:
        return num == 0
    if h >= 1.0:
        return num == den
    if den > 5000:
        sd = math.sqrt(den * h * (1 - h))
        return abs(num - den * h) <= 0.5 + sd * _z(alpha)
    logp = [(math.lgamma(den + 1) - math.lgamma(k + 1) - math.lgamma(den - k + 1) + k * math.log(h) + (den - k) * math.log1p(-h))
            for k in range(den + 1)]
    p = np.exp(np.array(logp))
    cdf = float(p[:num + 1].sum())
    sf = float(p[num:].sum())
    return cdf >= alpha / 2 and sf >= alpha / 2


def _z(alpha: float) -> float:
    """Two-sided normal quantile for tail alpha / 2 (bisection on erfc)."""
    lo, hi = 0.0, 12.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if math.erfc(mid / math.sqrt(2)) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def audit_realised_rates(num: np.ndarray, den: np.ndarray, h: np.ndarray, family_alpha: float = 1e-3) -> bool:
    """Audit A7 for one (pick, variant) placebo: in every stratum the realised exit rate lies within a binomial band around
    h, the band's total error rate being ``family_alpha`` over the strata tested (Bonferroni)."""
    tested = int((den > 0).sum())
    if tested == 0:
        return True
    a = family_alpha / tested
    for idx in np.ndindex(*h.shape):
        if den[idx] > 0 and not binom_band_ok(int(num[idx]), int(den[idx]), float(h[idx]), a):
            return False
    return True
