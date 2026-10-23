"""Round-2 account pass (PREREG2.md): the books vwbuild2.py wrote, the pooled 15m + 30m + 1h book, and the two
path-dependent filters (skip a coin for the day after a loss on it; stop the day after two losses)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwacct import *
from vwbuild2 import OUT2, EXITS2, exit2_name
import numba

_EX2 = {e["id"]: e for e in EXITS2}
TF_RANK = {"1h": 0, "30m": 1, "15m": 2}                          # in the pool, the longer bar first at one minute


def ex2_id(stop, profit, early=()):
    key = (stop, profit, tuple(tuple(x) for x in early))
    for e in EXITS2:
        if (e["stop"], e["profit"], tuple(tuple(x) for x in e["early"])) == key:
            return e["id"]
    raise KeyError(key)


class Book2(Book):
    """A round-2 book: OUT2/<name>, or the pool of several."""

    def __init__(self, name, parts=None):
        self.tf = name
        if parts is None:
            Fs, R = [], {k: [] for k in ("ret", "t", "ret_o", "t_o")}
            for c in COINS:
                Fs.append(pd.read_pickle(os.path.join(OUT2, name, f"{c}_features.pkl")))
                Z = np.load(os.path.join(OUT2, name, f"{c}.npz"))
                for k in R:
                    R[k].append(Z[k])
            F = pd.concat(Fs, ignore_index=True)
            F["book"] = name
        else:
            F = pd.concat([p.F for p in parts], ignore_index=True)
            R = {k: [getattr(p, k) for p in parts] for k in ("ret", "t", "ret_o", "t_o")}
        F["rank"] = F.coin.map({c: i for i, c in enumerate(COINS)})
        F["tfrank"] = F.tf.map(TF_RANK)
        o = np.lexsort((F["rank"].to_numpy(), F["tfrank"].to_numpy(), F.bar_close.to_numpy()))
        self.F = F.iloc[o].reset_index(drop=True)
        for k in R:
            setattr(self, k, np.concatenate(R[k])[o])
        self.entry = self.F.bar_close.to_numpy(np.int64)
        if parts is None:
            self.tf = BOOK_TF_OF.get(name, name)
            self._btc()
        kst = pd.to_datetime(self.entry + KST, unit="ms")
        self.wd = np.asarray(kst.dayofweek < 5)
        self.kday = (self.entry + KST) // DAY
        self.month = np.asarray(kst.year * 12 + kst.month - 1, np.int64)
        self.lev_owner = np.where(self.F.coin.to_numpy() == "BTCUSDT", 40.0, 30.0)
        self.crank = self.F["rank"].to_numpy(np.int64)
        self.name = name

    def risk_dist(self, j):
        return _EX2[j]["stop"] * self.F.atrf.to_numpy() + COST_RT


BOOK_TF_OF = {"15m": "15m", "30m": "30m", "1h": "1h", "30mc": "30m"}


def pool(books):
    return Book2("pool", parts=books)


@numba.njit(cache=True)
def _take_rules(entry, exit_t, use, net, crank, kday, rule):
    """One position; rule 1: after a loss on a coin, no more entries on that coin that KST day; rule 2: after two losses
    in a KST day, no more entries that day; rule 3: both."""
    n = len(entry)
    out = np.empty(n, np.int64)
    k = 0
    free = -1
    day = -1
    lost_coin = np.zeros(6, np.int64)
    lost_day = 0
    for i in range(n):
        if kday[i] != day:
            day = kday[i]
            lost_coin[:] = 0
            lost_day = 0
        if not use[i] or entry[i] < free:
            continue
        if (rule == 1 or rule == 3) and lost_coin[crank[i]] > 0:
            continue
        if (rule == 2 or rule == 3) and lost_day >= 2:
            continue
        out[k] = i
        k += 1
        free = exit_t[i]
        if net[i] <= 0:
            lost_coin[crank[i]] += 1
            lost_day += 1
    return out[:k]


def take_rule(rule):
    """A trades() twin for metrics(take=...) with a path-dependent rule. The loss of a trade is known when it closes,
    before the next entry (one position)."""
    def f(book, mask, j, flip=None):
        ret, t = book.ret[:, j], book.t[:, j]
        if flip is not None:
            ret = np.where(flip, book.ret_o[:, j], ret)
            t = np.where(flip, book.t_o[:, j], t)
        ext = book.entry + (t.astype(np.int64) + 1) * MIN
        idx = _take_rules(book.entry, ext, mask, ret.astype(np.float64), book.crank, book.kday, rule)
        return idx, ret[idx].astype(float), ext[idx], book.risk_dist(j)[idx]
    return f
