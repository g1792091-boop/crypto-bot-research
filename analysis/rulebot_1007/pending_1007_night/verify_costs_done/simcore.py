# Own vectorised simulator of the paper house exits (from paperbot/ladder.py + config defaults):
# entry at raw open price, fill raw*(1+s*2bp); stop = raw - s*2*ATR; ladder: lock L=0.10+0.05k once best net ROE >= L+0.02,
# lock price = fill*(1+s*(L/lev+RT)); lock applies from the next bar; stop hit at the bar's adverse extreme (gap -> open);
# optional isolated-margin liquidation at fill*(1 - s*(1/lev - mm)).  Returns raw exit price, reason (0 SL,1 LOCK,2 LIQ,3 END), bars held.
import numpy as np
RT = 0.0014
def sim(o, h, l, c, idx, side, atr, lev, H=3000, liq=False, mm=0.005):
    n = len(o); m = len(idx)
    raw = o[idx]; fill = raw * (1 + side * 2e-4)
    stop = raw - side * 2 * atr
    liqpx = fill * (1 - side * (1.0 / lev - mm))
    best = np.zeros(m); lock = np.full(m, np.nan)
    xr = np.full(m, np.nan); rs = np.full(m, 3); hd = np.zeros(m, int)
    act = np.arange(m)
    for j in range(H):
        if not len(act): break
        J = idx[act] + j
        ok = J < n
        if not ok.all():
            e = act[~ok]; xr[e] = c[n - 1]; hd[e] = j; act = act[ok]; J = J[ok]
            if not len(act): break
        s = side[act]
        st = np.where(np.isnan(lock[act]), stop[act], np.where(s == 1, np.fmax(stop[act], lock[act]), np.fmin(stop[act], lock[act])))
        adv = np.where(s == 1, l[J], h[J]); oo = o[J]
        hit = np.where(s == 1, adv <= st, adv >= st)
        gap = np.where(s == 1, oo <= st, oo >= st)
        if liq:
            lq = liqpx[act]
            lhit = np.where(s == 1, adv <= lq, adv >= lq) & ~np.where(s == 1, st >= lq, st <= lq)  # liq before stop when liq is closer
            lhit &= ~gap | np.where(s == 1, oo <= lq, oo >= lq)
        else:
            lhit = np.zeros(len(act), bool)
        out = hit | lhit
        e = act[out]
        px = np.where(gap[out], oo[out], st[out])
        if liq:
            px = np.where(lhit[out], np.where(np.where(s[out] == 1, oo[out] <= liqpx[e], oo[out] >= liqpx[e]), oo[out], liqpx[e]), px)
        xr[e] = px; hd[e] = j + 1
        rs[e] = np.where(lhit[out], 2, np.where(np.isnan(lock[e]), 0, 1))
        act = act[~out]; J = J[~out]; s = side[act]
        fav = np.where(s == 1, h[J] / fill[act] - 1, 1 - l[J] / fill[act])
        best[act] = np.maximum(best[act], fav)
        roe = lev * (best[act] - RT)
        k = np.floor((roe - 0.12) / 0.05 + 1e-9)
        L = np.where(roe >= 0.12 - 1e-12, 0.10 + 0.05 * k, np.nan)
        px = fill[act] * (1 + s * (L / lev + RT))
        old = lock[act]
        lock[act] = np.where(np.isnan(old), px, np.where(s == 1, np.fmax(old, px), np.fmin(old, px)))
    if len(act):
        xr[act] = c[np.minimum(idx[act] + H - 1, n - 1)]; hd[act] = H
    return raw, xr, rs, hd
