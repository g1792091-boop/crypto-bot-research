"""Cell search on the forward data: pick on the first half (H1 = 10-06 00:00 .. 10-15 12:00 KST), read ONCE on the
second half (H2 = 10-15 12:00 .. 10-24 23:12 KST), with a permutation of the WHOLE search.

Rules fixed before any H2 number was looked at (written here first, then run once):
  universe   entries = every coded strategy whose role is NOT trend (77 names: pullback, range, breakout, reversal,
             timing, other) on 15m / 30m / 1h / 4h; trend sources = 5 judge variants (Jdir, Jraw3, Jlive, J4of4,
             J2net) + 52 condition states (c_) + 52 latch states (l_); mappings 15m->1h, 15m->4h, 30m->1h, 30m->4h,
             1h->4h, 1h->1d, 4h->1d. A cell = (entry, tf, htf, source); its trades = the entry's signals whose side
             equals the source's state on the last closed htf bar ("with the trend"), each signal a separate trade.
  family     the same with the entry replaced by its role (6 roles): (role, tf, htf, source).
  H1 data    signals with bar close in H1 AND exit before the split (no outcome that needs H2 prices).
  eligible   entry cells: n >= 10 signals on >= 4 UTC days; family cells: n >= 30 on >= 5 days.
  score      mean net ROE - its standard error (per-signal), H1.
  picks      TOP1 = best cell; TOP10 = the best cell of each (entry, tf), the 10 best entries. Family: TOP1, TOP5.
  exits      run separately under w35 (owners' live: 35x, net -50 % stop, ladder) and a2 (2 ATR + ladder, 30x).
  H2 read    once, per pick and pooled: n, mean ROE, win rate, coin-flip twin (opposite side on the same entries),
             long / short split, the entry's unfiltered signals, follow-the-trend-at-every-bar baseline.
  null       side flips by (coin, UTC day) cluster (all signals of a coin-day flip together; outcome -> the opposite
             side's), whole search redone on H1, picks read on H2; 1,000 permutations; p = share of null >= actual.

Writes: search_cells_<v>.csv.gz (every eligible-or-not cell with n_all >= 5), search_picks.csv, search_perm.csv,
search.json.  Run: python3 fw_search.py [n_perm]"""
import json
import time
import scipy.sparse as sp
from fw_lib import *  # noqa: F401,F403

NPERM = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
SRCS = list(JUDGES) + [f"c_{x}" for x in SOURCES] + [f"l_{x}" for x in SOURCES]
TFMAPS = {"15m": ("1h", "4h"), "30m": ("1h", "4h"), "1h": ("4h", "1d"), "4h": ("1d",)}
SPLIT_E = (SPLIT - T0) // MIN
END_E = (DATA_END - T0) // MIN
MIN_N, MIN_D = 10, 4
FMIN_N, FMIN_D = 30, 5


class Engine:
    def __init__(self, S):
        self.S = S
        self.side = S.side.to_numpy(np.int8)
        self.e = S.e.to_numpy(np.int64)
        self.day = S.day.to_numpy(np.int64)
        d0 = self.day.min()
        self.dd = (self.day - d0).astype(np.int64)
        self.nd = int(self.dd.max() + 1)
        self.h1 = S.t.to_numpy() < SPLIT
        self.out = {}
        for v in ("w35", "a2"):
            self.out[v] = {s: (roe(S, v, s == "o"), S[f"{v}{'_opp' if s == 'o' else ''}_k"].to_numpy(np.int64),
                               S[f"{v}{'_opp' if s == 'o' else ''}_why"].to_numpy()) for s in ("s", "o")}
        # entry (name, tf) and family (role, tf) ids
        self.ent_key = (S.name + "|" + S.tf).to_numpy()
        self.ents, self.ent = np.unique(self.ent_key, return_inverse=True)
        self.fam_key = (S.role + "|" + S.tf).to_numpy()
        self.fams, self.fam = np.unique(self.fam_key, return_inverse=True)
        self.blocks = []                     # per mapping: rows, state matrix, sparse one-hots
        for tf, htfs in TFMAPS.items():
            rows = np.flatnonzero(S.tf.to_numpy() == tf)
            for h in htfs:
                St = np.stack([state(S.iloc[rows], s, h) for s in SRCS], 1).astype(np.int8)
                b = {"tf": tf, "htf": h, "rows": rows, "St": St}
                for lab, ids, n in (("E", self.ent[rows], len(self.ents)), ("F", self.fam[rows], len(self.fams))):
                    m = len(rows)
                    b[lab] = sp.csr_matrix((np.ones(m, np.float32), (ids, np.arange(m))), shape=(n, m))
                    b[lab + "d"] = sp.csr_matrix((np.ones(m, np.float32), (ids * self.nd + self.dd[rows],
                                                                          np.arange(m))), shape=(n * self.nd, m))
                self.blocks.append(b)
        self.coinday = (S.coin.to_numpy(np.int64) * 1000 + self.dd)
        self.cd_u, self.cd_inv = np.unique(self.coinday, return_inverse=True)

    def run(self, flip=None, want_rows=False):
        """Cell sums for H1 (exit before split) and H2 (not open at the end) under side flips (None = actual)."""
        f = np.ones(len(self.side), np.int8) if flip is None else flip[self.cd_inv]
        side = self.side * f
        res = {}
        for v in ("w35", "a2"):
            (rs, ks, ws), (ro, ko, wo) = self.out[v]["s"], self.out[v]["o"]
            r = np.where(f > 0, rs, ro)
            k = np.where(f > 0, ks, ko)
            w = np.where(f > 0, ws, wo)
            ok1 = self.h1 & (self.e + k <= SPLIT_E) & np.isfinite(r) & (k >= 0)
            ok2 = ~self.h1 & (w != 3) & np.isfinite(r) & (k >= 0)
            res[v] = {"r": np.nan_to_num(r), "ok1": ok1, "ok2": ok2}
        cells = {}
        for bi, b in enumerate(self.blocks):
            rows = b["rows"]
            A = (b["St"] * side[rows, None]) == 1                         # with the trend
            for v in ("w35", "a2"):
                rr = res[v]["r"][rows]
                for half, okk in (("H1", res[v]["ok1"][rows]), ("H2", res[v]["ok2"][rows])):
                    W = (A & okk[:, None]).astype(np.float32)
                    Wr = W * rr[:, None].astype(np.float32)
                    for lab in ("E", "F"):
                        n = b[lab] @ W
                        s1 = b[lab] @ Wr
                        o = {"n": n, "s": s1}
                        if half == "H1":
                            o["q"] = b[lab] @ (Wr * rr[:, None].astype(np.float32))
                            dd = (b[lab + "d"] @ W).reshape(-1, self.nd, W.shape[1])
                            o["d"] = (dd > 0).sum(1)
                        cells[(bi, v, half, lab)] = o
        return cells

    def table(self, cells, v, lab):
        """Long table of cells for exit v and level lab: block, id, src, H1 n/mean/sd/days/score, H2 n/mean."""
        out = []
        for bi, b in enumerate(self.blocks):
            c1, c2 = cells[(bi, v, "H1", lab)], cells[(bi, v, "H2", lab)]
            n1, n2 = c1["n"], c2["n"]
            with np.errstate(invalid="ignore", divide="ignore"):
                m1 = c1["s"] / n1
                var = np.maximum(c1["q"] / n1 - m1 ** 2, 0) * n1 / np.maximum(n1 - 1, 1)
                se = np.sqrt(var / n1)
                m2 = c2["s"] / n2
            ids, ss = np.meshgrid(np.arange(n1.shape[0]), np.arange(n1.shape[1]), indexing="ij")
            out.append(pd.DataFrame({"block": bi, "id": ids.ravel(), "src": np.asarray(SRCS)[ss.ravel()],
                                     "n1": n1.ravel(), "m1": m1.ravel(), "se1": se.ravel(), "d1": c1["d"].ravel(),
                                     "n2": n2.ravel(), "m2": m2.ravel(), "s2": c2["s"].ravel()}))
        T = pd.concat(out, ignore_index=True)
        T["score"] = T.m1 - T.se1
        return T


def pick(T, lab, eng):
    mn, md = (MIN_N, MIN_D) if lab == "E" else (FMIN_N, FMIN_D)
    E = T[(T.n1 >= mn) & (T.d1 >= md)].sort_values("score", ascending=False)
    names = eng.ents if lab == "E" else eng.fams
    E = E.assign(key=names[E.id.to_numpy()])
    top1 = E.head(1)
    k = 10 if lab == "E" else 5
    topk = E.drop_duplicates("key").head(k)
    return top1, topk


def pooled(T):
    n = T.n2.sum()
    return float(T.s2.sum() / n) if n else np.nan


def main():
    t0 = time.time()
    S = load("sig")
    S = S[S.role != "trend"].reset_index(drop=True)
    eng = Engine(S)
    log("engine", len(S), "rows", len(eng.ents), "entries", len(eng.fams), "families", round(time.time() - t0, 1))
    cells = eng.run()
    actual = {}
    picks = []
    for v in ("w35", "a2"):
        for lab in ("E", "F"):
            T = eng.table(cells, v, lab)
            names = eng.ents if lab == "E" else eng.fams
            T["key"] = names[T.id.to_numpy()]
            T["tf"] = [eng.blocks[b]["tf"] for b in T.block]
            T["htf"] = [eng.blocks[b]["htf"] for b in T.block]
            keep = T[(T.n1 + T.n2) >= 5].drop(columns=["block", "id"])
            keep.to_csv(os.path.join(HERE, f"search_cells_{v}_{lab}.csv.gz"), index=False, float_format="%.5g",
                        compression="gzip")
            top1, topk = pick(T, lab, eng)
            elig = int(((T.n1 >= (MIN_N if lab == "E" else FMIN_N)) & (T.d1 >= (MIN_D if lab == "E" else FMIN_D))).sum())
            actual[(v, lab)] = {"best_score": float(top1.score.iloc[0]), "top1_h2": float(top1.m2.iloc[0]),
                                "topk_h2_pooled": pooled(topk), "topk_h2_eq": float(np.nanmean(topk.m2)),
                                "n_cells": int(len(T)), "n_eligible": elig}
            for rank, (_, r) in enumerate(topk.iterrows(), 1):
                picks.append({"exit": v, "level": lab, "rank": rank, "key": r.key, "tf": r.tf, "htf": r.htf,
                              "src": r.src, "n1": r.n1, "d1": r.d1, "m1": r.m1, "se1": r.se1, "score": r.score,
                              "n2": r.n2, "m2": r.m2, "top1": rank == 1 and r.key == top1.key.iloc[0]
                              and r.src == top1.src.iloc[0]})
            log(v, lab, actual[(v, lab)])
    P = pd.DataFrame(picks)
    P.to_csv(os.path.join(HERE, "search_picks.csv"), index=False, float_format="%.5g")
    # ---------------------------------------------------------------- permutations
    rng = np.random.default_rng(20261024)
    null = []
    for i in range(NPERM):
        flip = rng.choice(np.array([-1, 1], np.int8), len(eng.cd_u))
        c = eng.run(flip)
        row = {"perm": i}
        for v in ("w35", "a2"):
            for lab in ("E", "F"):
                T = eng.table(c, v, lab)
                names = eng.ents if lab == "E" else eng.fams
                top1, topk = pick(T, lab, eng)
                row[f"{v}_{lab}_best"] = float(top1.score.iloc[0])
                row[f"{v}_{lab}_top1_h2"] = float(top1.m2.iloc[0])
                row[f"{v}_{lab}_topk_h2"] = pooled(topk)
                row[f"{v}_{lab}_topk_h2_eq"] = float(np.nanmean(topk.m2))
        null.append(row)
        if i % 50 == 0:
            log("perm", i, round(time.time() - t0, 1))
    N = pd.DataFrame(null)
    N.to_csv(os.path.join(HERE, "search_perm.csv"), index=False, float_format="%.5g")
    summ = {}
    for (v, lab), a in actual.items():
        k = f"{v}_{lab}"
        summ[k] = {**a,
                   "p_best_h1": float(np.mean(N[f"{k}_best"] >= a["best_score"])),
                   "p_top1_h2": float(np.mean(N[f"{k}_top1_h2"] >= a["top1_h2"])),
                   "p_topk_h2": float(np.mean(N[f"{k}_topk_h2"] >= a["topk_h2_pooled"])),
                   "p_topk_h2_eq": float(np.mean(N[f"{k}_topk_h2_eq"] >= a["topk_h2_eq"])),
                   "null_best_med": float(N[f"{k}_best"].median()),
                   "null_topk_h2_med": float(N[f"{k}_topk_h2"].median()),
                   "null_topk_h2_p95": float(N[f"{k}_topk_h2"].quantile(0.95)),
                   "null_top1_h2_med": float(N[f"{k}_top1_h2"].median())}
    json.dump({"n_perm": NPERM, "summary": summ}, open(os.path.join(HERE, "search.json"), "w"), indent=1)
    log("done", round(time.time() - t0, 1))
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
