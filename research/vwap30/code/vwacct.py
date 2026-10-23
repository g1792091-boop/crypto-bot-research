"""The account pass of the VWAP-fail study (PREREG.md "고정한 계산 방식"): one position across the six coins, signals in
time order (ties in COINS order), a signal is taken only when no position is open; the stake from the risk share r
(a stop costs r of the balance: leverage = r / (stop distance + round-trip cost), cap 50) or the owners' form (margin
40 % at BTC 40x / others 30x). Reads what vwbuild.py wrote."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwbuild import *
import numba

LEV_CAP = 50.0
OWNERS_MARGIN = 0.40
_EX = {e["id"]: e for e in EXITS}
EX_B1 = next(e["id"] for e in EXITS if e["kind"] == "house")
EX_B2 = next(e["id"] for e in EXITS if e["kind"] == "owners")
EX_B3 = next(e["id"] for e in EXITS if e["kind"] == "grid" and e["stop"] == 2.0 and e["target"] == 1.0
             and e["time"] == 96 and e["be"] is None)


def exit_name(j):
    e = _EX[j]
    if e["kind"] == "grid":
        t = "없음" if e["target"] is None else f"{e['target']:g}"
        b = "" if e["be"] is None else " · 본전(+1ATR 뒤)"
        return f"손절 {e['stop']:g}ATR · 익절 {t}{'ATR' if e['target'] else ''} · {e['time']}봉{b}"
    if e["kind"] == "trail":
        return f"손절 2ATR · +{e['act']:g}ATR 뒤 {e['dist']:g}ATR 따라가기 · 96봉"
    return "B1 규칙봇(2ATR + 계단 30배)" if e["kind"] == "house" else "B2 두 분 방식(순ROE −50% + 계단)"


class Book:
    """All signals of one timeframe, in entry order, with their outcomes under every exit."""

    def __init__(self, tf):
        self.tf = tf
        Fs, R = [], {k: [] for k in ("ret", "t", "ret_o", "t_o")}
        for c in COINS:
            Fs.append(pd.read_pickle(os.path.join(OUT, tf, f"{c}_features.pkl")))
            Z = np.load(os.path.join(OUT, tf, f"{c}.npz"))
            for k in R:
                R[k].append(Z[k])
        F = pd.concat(Fs, ignore_index=True)
        F["rank"] = F.coin.map({c: i for i, c in enumerate(COINS)})
        o = np.lexsort((F["rank"].to_numpy(), F.bar_close.to_numpy()))
        self.F = F.iloc[o].reset_index(drop=True)
        for k in R:
            setattr(self, k, np.concatenate(R[k])[o])
        self.entry = self.F.bar_close.to_numpy(np.int64)
        self._btc()
        kst = pd.to_datetime(self.entry + KST, unit="ms")
        self.wd = np.asarray(kst.dayofweek < 5)
        self.month = np.asarray(kst.year * 12 + kst.month - 1, np.int64)
        self.lev_owner = np.where(self.F.coin.to_numpy() == "BTCUSDT", 40.0, 30.0)

    def _btc(self):
        """BTC's own move on the signal bar (bar ending at the signal's close) and BTC's 4h vote, for the BTC filters."""
        g = grid("BTCUSDT")
        k = TF_MIN[self.tf]
        m = (self.entry - T0) // MIN
        self.F["btc_bar"] = (g["c"][m - 1] / g["o"][m - k] - 1) * self.F.side.to_numpy()
        Z = np.load(os.path.join(JUDGE_DIR, "BTCUSDT.npz"))
        tc = Z["4h_tclose"]
        x = np.searchsorted(tc, self.entry, side="right") - 1
        ok = (x >= 0) & (self.entry - tc[np.maximum(x, 0)] < 2 * 240 * MIN)
        self.F["btc4h_raw3"] = np.where(ok, Z["4h_raw3"].astype(float)[np.maximum(x, 0)] * self.F.side.to_numpy(), np.nan)

    def risk_dist(self, j):
        """Price distance lost at the stop, cost included (1 R)."""
        e = _EX[j]
        af = self.F.atrf.to_numpy()
        if e["kind"] == "owners":
            return 0.5 / self.lev_owner
        return e["stop"] * af + COST_RT


@numba.njit(cache=True)
def _take(entry, exit_t, use):
    """Indices taken by the one-position pass over signals in entry order."""
    n = len(entry)
    out = np.empty(n, np.int64)
    k = 0
    free = -1
    for i in range(n):
        if not use[i] or entry[i] < free:
            continue
        out[k] = i
        k += 1
        free = exit_t[i]
    return out[:k]


def period_mask(book, per):
    a, b = PERIODS[per]
    return (book.entry >= a) & (book.entry < b)


def trades(book, mask, j, flip=None):
    """(taken indices, net return, exit time, R distance) for exit j over the signals in mask (flip: bool per signal,
    True = the other side, for the coin-flip twin)."""
    ret, t = book.ret[:, j], book.t[:, j]
    if flip is not None:
        ret = np.where(flip, book.ret_o[:, j], ret)
        t = np.where(flip, book.t_o[:, j], t)
    ext = book.entry + (t.astype(np.int64) + 1) * MIN
    idx = _take(book.entry, ext, mask)
    return idx, ret[idx].astype(float), ext[idx], book.risk_dist(j)[idx]


def stake(book, idx, D, r):
    """Exposure as a multiple of the balance: risk r (or 'owners')."""
    if r == "owners":
        return OWNERS_MARGIN * book.lev_owner[idx]
    if r == "rb9":                                      # the rule bot: margin 30 % of the balance at 30x
        return np.full(len(idx), 9.0)
    return np.minimum(r / D, LEV_CAP)


_WD = {}


def weekdays(a, b):
    """KST weekdays (Mon-Fri) in [a, b)."""
    if (a, b) not in _WD:
        d = pd.date_range(pd.Timestamp(a + KST, unit="ms").normalize(), pd.Timestamp(b - 1 + KST, unit="ms").normalize())
        _WD[(a, b)] = int((d.dayofweek < 5).sum())
    return _WD[(a, b)]


def metrics(book, mask, j, per, r=0.02, flip=None, full=True, take=None):
    a, b = PERIODS[per]
    m = mask & (book.entry >= a) & (book.entry < b)
    idx, net, ext, D = (take or trades)(book, m, j, flip)
    R = net / D
    x = stake(book, idx, D, r) * net
    ruin = bool((x <= -1).any())
    lg = np.log1p(np.maximum(x, -1 + 1e-12))
    days = (b - a) / DAY
    yrs = days / 365.25
    n_wd = weekdays(a, b)
    out = {"n": int(len(idx)), "growth": float(lg.sum()), "growth_yr": float(lg.sum() / yrs), "ruin": ruin,
           "per_weekday": len(idx[book.wd[idx]]) / max(n_wd, 1)}
    if not full:
        return out
    win, loss = R[R > 0], R[R <= 0]
    eq = np.exp(np.cumsum(lg))
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    dd = float((eq / peak - 1).min()) if len(eq) else 0.0
    mon_all = np.arange(int((pd.Timestamp(a + KST, unit="ms").year * 12 + pd.Timestamp(a + KST, unit="ms").month - 1)),
                        int((pd.Timestamp(b - 1 + KST, unit="ms").year * 12 + pd.Timestamp(b - 1 + KST, unit="ms").month - 1)) + 1)
    em = pd.to_datetime(ext + KST, unit="ms")
    emon = np.asarray(em.year * 12 + em.month - 1)
    mon = np.array([np.expm1(lg[emon == q].sum()) for q in mon_all])
    out.update({
        "per_day": len(idx) / days,
        "win": float((net > 0).mean()) if len(net) else np.nan,
        "avgR": float(R.mean()) if len(R) else np.nan,
        "avg_winR": float(win.mean()) if len(win) else np.nan, "avg_lossR": float(loss.mean()) if len(loss) else np.nan,
        "payoff": float(win.mean() / -loss.mean()) if len(win) and len(loss) and loss.mean() < 0 else np.nan,
        "pf": float(win.sum() / -loss.sum()) if len(loss) and loss.sum() < 0 else np.nan,
        "avg_win_pct": float(net[net > 0].mean() * 100) if (net > 0).any() else np.nan,
        "avg_loss_pct": float(net[net <= 0].mean() * 100) if (net <= 0).any() else np.nan,
        "mult": float(np.exp(lg.sum())), "cagr": float(np.expm1(lg.sum() / yrs)), "maxdd": dd,
        "mon_median": float(np.median(mon)), "mon_x6": float((mon >= 5.0).mean()), "mon_worst": float(mon.min()),
        "mon_best": float(mon.max()), "mon_pos": float((mon > 0).mean()), "months": len(mon),
        "lev_med": float(np.median(stake(book, idx, D, r))) if len(idx) else np.nan,
    })
    return out
