"""Reference (after the results): the custom-value landscape of every cell at the live exit (grid_stats.npz) and the
exit landscape at the default numbers (default_by_exit.npz). Per cell: how many custom values were positive in each
period, whether the select-period ranking carried into the test period (Spearman), where the default stood, what the
select-period top 5% did next, and per parameter which values were better in each period (and whether they agree).
Per cell for the 84 exits: the select-period best exits and their test results, the live exit's rank, and the
select-to-test rank correlation.

    python research/fullgrid/diag/landscape.py RESULTS_BRANCH_DIR OUT.json
"""

import json
import os
import sys

FG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(FG)))
sys.path.insert(0, FG)

import numpy as np  # noqa: E402

import run as R  # noqa: E402

MIN_SEL, MIN_TEST, MIN_EXTRA = R.MIN_SELECT, R.MIN_TEST, R.MIN_EXTRA


def spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    if len(a) < 10:
        return None
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def means(st: np.ndarray) -> tuple:
    n = st[:, :, 0]
    with np.errstate(invalid="ignore", divide="ignore"):
        m = st[:, :, 1] / n
        w = st[:, :, 3] / n
    return n, m, w


def grid_cell(kind: str, name: str, st: np.ndarray, default_idx: int | None) -> dict:
    n, m, w = means(st)
    ok = (n[:, 0] >= MIN_SEL) & (n[:, 1] >= MIN_TEST)
    out = {"combos": int(len(st)), "eligible": int(ok.sum())}
    if ok.sum() and not np.isfinite(st[ok, :, 1]).any():
        out["hidden"] = True   # the run left DeepSeek P&L out of its files (D11)
        out["win_select_median"] = float(np.nanmedian(w[ok, 0]))
        return out
    if ok.sum() == 0:
        return out
    ms, mt = m[ok, 0], m[ok, 1]
    okx = ok & (n[:, 2] >= MIN_EXTRA)
    out.update({
        "pos_select": float((ms > 0).mean()), "pos_test": float((mt > 0).mean()),
        "pos_both": float(((ms > 0) & (mt > 0)).mean()),
        "pos_all3": float(((m[okx, 0] > 0) & (m[okx, 1] > 0) & (m[okx, 2] > 0)).mean()) if okx.any() else None,
        "rho_select_test": spearman(ms, mt), "rho_select_extra": spearman(m[okx, 0], m[okx, 2]) if okx.sum() >= 10 else None,
        "test_median": float(np.median(mt)), "select_median": float(np.median(ms)),
        "win_select_median": float(np.nanmedian(w[ok, 0])),
    })
    k = max(1, int(round(0.05 * ok.sum())))
    top = np.argsort(-ms)[:k]
    out["top5_test_median"] = float(np.median(mt[top]))
    out["top5_select_median"] = float(np.median(ms[top]))
    best = int(np.argmax(ms))
    out["best_select"] = {"select": float(ms[best]), "test": float(mt[best])}
    if default_idx is not None and ok[default_idx]:
        out["default_pct_select"] = float((ms < m[default_idx, 0]).mean())
        out["default_pct_test"] = float((mt < m[default_idx, 1]).mean())
    ps, vals, combos = R.cell_grid(kind, name)
    params = []
    idx_ok = np.flatnonzero(ok)
    for j, p in enumerate(ps):
        pname = p["name"]
        col = [combos[i][pname] for i in idx_ok]
        rows = []
        for v in vals[j]:
            sel = np.array([c == v for c in col])
            if sel.sum() == 0:
                continue
            rows.append({"value": v if not isinstance(v, tuple) else list(v), "count": int(sel.sum()),
                         "select": float(np.mean(ms[sel])), "test": float(np.mean(mt[sel]))})
        if len(rows) >= 3:
            s_arr = np.array([r["select"] for r in rows])
            t_arr = np.array([r["test"] for r in rows])
            ra, rb = np.argsort(np.argsort(s_arr)), np.argsort(np.argsort(t_arr))
            agree = float(np.corrcoef(ra, rb)[0, 1]) if ra.std() and rb.std() else None
        else:
            agree = None
        params.append({"param": pname, "default": p.get("default") if not isinstance(p.get("default"), tuple)
                       else list(p["default"]), "values": rows, "agree": agree})
    out["params"] = params
    return out


def exit_cell(st: np.ndarray, names: list) -> dict:
    n, m, w = means(st)
    ok = (n[:, 0] >= MIN_SEL) & (n[:, 1] >= MIN_TEST)
    out = {"eligible": int(ok.sum())}
    if ok.sum() and not np.isfinite(st[ok, :, 1]).any():
        out["hidden"] = True
        return out
    if ok.sum() < 3:
        return out
    idx = np.flatnonzero(ok)
    order = idx[np.argsort(-m[idx, 0])]
    out["top_select"] = [{"exit": names[i], "select": float(m[i, 0]), "test": float(m[i, 1]),
                          "extra": float(m[i, 2]) if n[i, 2] >= MIN_EXTRA else None,
                          "win_test": float(w[i, 1]), "n_test": int(n[i, 1])} for i in order[:3]]
    tb = idx[np.argmax(m[idx, 1])]
    out["best_test"] = {"exit": names[tb], "test": float(m[tb, 1])}
    out["rho_select_test"] = spearman(m[idx, 0], m[idx, 1])
    out["pos_test"] = int((m[idx, 1] > 0).sum())
    if ok[0]:
        out["live_rank_select"] = int((m[idx, 0] > m[0, 0]).sum()) + 1
        out["live_rank_test"] = int((m[idx, 1] > m[0, 1]).sum()) + 1
    return out


def main(res_dir: str, dst: str) -> None:
    g = json.load(open(os.path.join(res_dir, "grids.json")))
    names = g["exits"]
    zg = np.load(os.path.join(res_dir, "grid_stats.npz"))
    ze = np.load(os.path.join(res_dir, "default_by_exit.npz"))
    out = {}
    for key in zg.keys():
        kind, name, tf = key.split("|")
        ps, vals, combos = R.cell_grid(kind, name)
        d = R.default_combo(kind, name)
        dkey = {k: R._hashable(v) for k, v in d.items()}
        default_idx = next((i for i, c in enumerate(combos) if c == dkey), None)
        out[key] = {"grid": grid_cell(kind, name, zg[key], default_idx), "exits": exit_cell(ze[key], names),
                    "default_in_grid": default_idx is not None}
        print(key, out[key]["grid"].get("rho_select_test"), flush=True)
    json.dump(out, open(dst, "w"))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
