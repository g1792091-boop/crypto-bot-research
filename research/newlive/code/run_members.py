"""The 추세판단 봇 (deploy/combo.trend.json) with ANY member list: research/trendbot/fiveyear/code/engine5y.py generalised.
Everything but the members is the live config (judges V39 / S6 / OBV / N12 at 1h -> 30m and 4h -> 1h entries,
vote >= 3, held, ADX >= 20, not tired, the entry checks, the chase block for every member (all live members have
no_chase), pullback 0.25 ATR (0.5 after a long bar), score rank, ONE position, BTC 40x / others 30x, margin 40 %, stop
-50 % net ROE, the two-part ladder, REV (own member) and JUDGE exits before the first lock, no TIME exit, pauses: KST
weekend, macro +-30 min, NYSE open -30 .. +30 min). The judge arrays are judge_all.py's (= judge5y's on the extended
data); the member signals signals_all.py's. The position, the funding, the stop / ladder, the liquidation and the
other-side outcome (for the coin-flip twin) are engine5y.simulate_position itself; macro_near / us_open / the chase
array form / Market.judgment / spot / flip_times are engine5y's too. What is new here: the member list (label,
breakout flag, ``when``), the record key, the data end, the cost presets and the solo / basket modes.

A member: {"label": "<strategy>@<tf>[#<pick id>]", "breakout": bool | None, "when": combo when | None}
 - breakout: the breakout entry check (trendjudge.check: ADX below breakout_adx_max and rising); None = as the live
   config's trend.breakout list (F3_BOS, F15_ORB, N06_MACD_ORB), by strategy name as live;
 - when: combo's ``when`` conditions (symbol / side / session / weekend; btc_trend is not supported here), e.g.
   [{"side": "short"}]; a signal outside them never enters but still closes its own member's position early (REV), as
   live (combo._queue: exit-only);
 - order: the list order (rank ties: score > timeframe > order > coin, as live);
 - the member's record for the score is keyed by (strategy, tf) as live (trendbot._record_of).

Run (python3 -I):
  run_members.py current [--compat] [--save NAME]                 the 10 live members
  run_members.py solo LABEL [--breakout | --no-breakout] [--when-side long|short] [--save NAME]
  run_members.py basket FILE.json [--save NAME]                   FILE: {"members": [member, ...]}
common: --start 2021-01-01 --end <date> (signal bar closes [start, end), default 2021-01-01 .. the data end)
        --judge J4|J4L (J4 = 3 of 4 on one side, live; J4L = up - down >= 2, PREREG_AMEND_1)
        --cost paper|zero|nofund|bybit|woo|maker  --draws N (coin-flip twin, 0 = none)  --quiet (time only)
        --compat: the five-year study's data form (end 2026-10-01, October mark = last price) for its reproduction
API: run(members, start=, end=, cost=) -> (trades, cand, info); twin(trades, draws=, seed=, start=, end=) -> dict"""
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nlcommon import *
import copy, math, time, warnings
from collections import defaultdict
import dataclasses

import engine5y as E                     # its module-level reads: deploy/combo.trend.json, the macro calendars
from paperbot import combo as C
from paperbot.trendjudge import HTF_OF, JUDGES, TrendRules, check, score
from paperbot.ladder2 import ComboLadder

CFG = E.CFG
PRI = E.PRI
TF_MIN = E.TF_MIN
LIVE_BREAKOUT = tuple(CFG["trend"]["breakout"])
BRK, NOBRK = "\x00breakout", "\x00plain"            # the names check() sees: rules.breakout = (BRK,)
COSTS = {
    "paper": {"taker": 0.0005, "slip": 0.0002, "maker": 0.0002, "funding": True},     # the paper bot's (five-year D0)
    "zero": {"taker": 0.0, "slip": 0.0, "maker": 0.0, "funding": False},
    "nofund": {"taker": 0.0005, "slip": 0.0002, "maker": 0.0002, "funding": False},
    "bybit": {"taker": 0.00044, "slip": 0.0002, "maker": 0.0002, "funding": True},
    "woo": {"taker": 0.00042, "slip": 0.0002, "maker": 0.0002, "funding": True},
    "maker": {"taker": 0.0005, "slip": 0.0002, "maker": 0.0002, "funding": True, "entry": "maker"},
}
SEED = 20261021                                      # analyze.py's coin-flip seed
MARGIN = 0.4


# ====================================================================== market data
class Market(E.Market):
    """engine5y.Market on this study's grid (load_grid: fg1m + October, mark prices) and judge arrays."""

    def __init__(self, coin, end=None, oct_mark="mark", judge_dir=JUDGE):
        self.coin = coin
        m = load_grid(coin, end, oct_mark)
        self.n = m["n"]
        self.first = m["first"]
        for k in ("o", "h", "l", "c", "mo", "mh", "ml", "fund"):
            setattr(self, k, m[k])
        nh = self.n // 60
        have = ~np.isnan(m["c"][:nh * 60].reshape(nh, 60)).all(axis=1)
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            hh = np.nanmax(m["h"][:nh * 60].reshape(nh, 60), axis=1)
            ll = np.nanmin(m["l"][:nh * 60].reshape(nh, 60), axis=1)
        hh[~have], ll[~have] = np.nan, np.nan
        s_h, s_l = pd.Series(hh), pd.Series(ll)
        self.r24 = (s_h.rolling(24, min_periods=1).max().shift(1).to_numpy(),
                    s_l.rolling(24, min_periods=1).min().shift(1).to_numpy(),
                    pd.Series(have.astype(float)).rolling(24, min_periods=1).sum().shift(1).fillna(0).to_numpy())
        self.r7 = (s_h.rolling(168, min_periods=1).max().shift(1).to_numpy(),
                   s_l.rolling(168, min_periods=1).min().shift(1).to_numpy(),
                   pd.Series(have.astype(float)).rolling(168, min_periods=1).sum().shift(1).fillna(0).to_numpy())
        self.hours_raw = (hh, ll, have)
        z = np.load(f"{judge_dir}/{coin}.npz")
        self.J = {k: z[k] for k in z.files}
        for tf in ("1h", "4h"):                           # J4L (PREREG_AMEND_1 A): up votes - down votes >= 2
            sv = sum(np.sign(self.J[f"{tf}_{k}"].astype(int)) for k in JUDGES)
            self.J[f"{tf}_rawL"] = np.where(sv >= 2, 1, np.where(sv <= -2, -1, 0)).astype(np.int8)
        last = int(self.J["1h_tclose"][-1])
        assert last >= m["end"] - HOUR, f"judge arrays end {pd.Timestamp(last, unit='ms')} before the data end"


_MK = {}


def markets(end=None, oct_mark="mark", judge_dir=JUDGE):
    end = DATA_END if end is None else int(end)
    key = (end, oct_mark, judge_dir)
    if key not in _MK:
        _MK.clear()                                   # one data form per process (6 coins ~ 2 GB)
        _MK[key] = {c: Market(c, end, oct_mark, judge_dir) for c in COINS}
    return _MK[key]


# ====================================================================== members and their signals
def current_members():
    """The live config's 10 members (deploy/combo.trend.json): breakout by its trend.breakout list, when as written."""
    out = []
    for m in CFG["members"]:
        assert "pick" not in m and "numbers" not in m
        out.append({"label": label_of(m["strategy"], m["tf"]), "breakout": None, "when": m.get("when")})
    return out


def resolve(members):
    """Member dicts (or labels) -> specs {label, name, tf, pick, order, breakout (bool), when (parsed), when_raw}."""
    out, seen = [], set()
    for i, m in enumerate(members, 1):
        if isinstance(m, str):
            m = {"label": m}
        lab = m["label"]
        if lab in seen:
            raise ValueError(f"{lab} twice")
        seen.add(lab)
        name, tf, pick = parse_label(lab)
        if tf not in ("30m", "1h"):
            raise ValueError(f"{lab}: the trend bot takes 30m / 1h entries only")
        brk = m.get("breakout")
        brk = (name in LIVE_BREAKOUT) if brk is None else bool(brk)
        when = C.parse_when(m.get("when"), lab)
        if when and any(k == "btc_trend" for c in when for k, _ in c):
            raise ValueError(f"{lab}: when btc_trend is not supported here")
        if not os.path.isfile(sig_path(lab)):
            raise ValueError(f"{lab}: no signal file (signals_all.py)")
        out.append({"label": lab, "name": name, "tf": tf, "pick": pick, "order": i, "breakout": brk, "when": when,
                    "when_raw": m.get("when")})
    return out


def load_member_signals(specs, start, end):
    """DataFrame bar_close, tf, label, member (name), symbol, side of the members' signals with bar close in [start, end)."""
    parts = []
    for s in specs:
        z = np.load(sig_path(s["label"]))
        meta = json.loads(str(z["meta"]))
        assert meta["data_end"] >= min(end, DATA_END), (s["label"], meta["data_end"], end)
        t = z["t"]
        k = (t >= start) & (t < end)
        parts.append(pd.DataFrame({"bar_close": t[k], "tf": s["tf"], "label": s["label"], "member": s["name"],
                                   "symbol": np.array(COINS)[z["coin"][k]], "side": z["side"][k].astype(int)}))
    sig = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(
        columns=["bar_close", "tf", "label", "member", "symbol", "side"])
    return sig.sort_values(["bar_close", "tf", "member", "symbol", "label"]).reset_index(drop=True)


# ====================================================================== candidates (engine5y.candidates, any members)
JUDGE_SETS = ("J4", "J4L")


def vm_of(v):
    """The raw-direction key of the judge arrays: J4 = raw<vote_min> (3 of 4 on one side, the live rule; vote_min 4 =
    the five-year D3 shadow), J4L = rawL (up - down >= 2). Hold, ADX, tired, the checks and the JUDGE exit follow it."""
    j = v.get("judge", "J4")
    assert j in JUDGE_SETS, j
    return v["vote_min"] if j == "J4" else "L"


def candidates(v, sig, mk, specs):
    rules = TrendRules.from_dict({**CFG["trend"], "vote_min": v["vote_min"], "time_bars": v["time_bars"]})
    rules = dataclasses.replace(rules, breakout=(BRK,))
    W = v["macro_min"] * MIN
    by = {s["label"]: s for s in specs}

    def block(ts, coin, side, bar_close, price):
        if v["no_weekend"] and C.kst_weekend(ts):
            return "weekend"
        if W and E.macro_near(ts, W, v["macro"]):
            return "macro"
        if (v["us_open_pause"] or v["us_open_pre"]) and E.us_open(ts, v["us_open_pause"], v["us_open_pre"]):
            return "us_open"
        ch = mk[coin].chase(bar_close, side, price)
        if ch is None:
            return "chase_nodata"
        if ch:
            return "chase"
        return ""

    rows = []
    for r in sig.itertuples(index=False):
        m = by[r.label]
        ts, coin, side, tf = int(r.bar_close), r.symbol, int(r.side), r.tf
        M = mk[coin]
        rec = {"t0": ts, "label": r.label, "coin": coin, "side": side, "tf": tf, "stage": "", "entry_t": None}
        if m["when"] and not any(C.condition_holds(c, coin, side, ts, None) for c in m["when"]):
            rec["stage"] = "x_when"
            rows.append(rec)
            continue
        i0 = M.i(ts)
        if i0 + 1 >= M.n:
            rec["stage"] = "x_data_end"
            rows.append(rec)
            continue
        price = float(M.o[i0])
        why = block(ts, coin, side, ts, price)
        if why:
            rec["stage"] = "x_block:" + why
            rows.append(rec)
            continue
        htf = HTF_OF[tf]
        j = M.judgment(htf, ts, rules, vm_of(v))
        s = M.spot(tf, ts)
        if j is None or s is None:
            rec["stage"] = "x_nojudge"
            rows.append(rec)
            continue
        assert j.bar_close == ts - ts % TF_MS[htf] and s.bar_close == ts, (j.bar_close, s.bar_close, ts)
        why, info = check(rules, BRK if m["breakout"] else NOBRK, tf, side, price, j, s)
        if why:
            rec["stage"] = "x_check"
            rec["why"] = why[:60]
            rows.append(rec)
            continue
        sc, parts = score(rules, side, j, s, price, [])
        rec.update(score_base=parts["strength"] + parts["spot"], level=float(info["level"]), big=bool(info["big_bar"]),
                   strength=int(j.strength(side)), order=m["order"], name=m["name"])
        until = ts + TF_MS[tf]
        a, b = i0 + 1, M.i(until - MIN)
        b = min(b, M.n - 1)
        lvl = rec["level"]
        if v["entry"] == "immediate":
            rec["entry_t"], rec["entry_ref"], rec["stage"] = ts, price, "entered?"
        else:
            if v["entry"] == "maker":
                hit = (M.l[a:b] < lvl) if side > 0 else (M.h[a:b] > lvl)
            else:
                hit = (M.l[a:b] <= lvl) if side > 0 else (M.h[a:b] >= lvl)
            nz = np.flatnonzero(hit)
            if not len(nz):
                rec["stage"] = "x_no_pullback"
                rows.append(rec)
                continue
            k = a + int(nz[0])
            if v["entry"] == "maker":
                et, ref = T0 + k * MIN, lvl
            else:
                et = T0 + (k + 1) * MIN
                ref = float(M.o[k + 1])
            why = block(et, coin, side, et, ref)
            if why:
                rec["stage"] = "x_block_at_entry:" + why
                rows.append(rec)
                continue
            rec["entry_t"], rec["entry_ref"], rec["stage"] = et, ref, "entered?"
        rows.append(rec)
    cols = ["t0", "label", "coin", "side", "tf", "stage", "entry_t"]
    return (pd.DataFrame(rows) if rows else pd.DataFrame(columns=cols)), rules


# ====================================================================== the run (engine5y.run, any members)
def make_variant(name="run", start=None, end=None, cost="paper", **kw):
    c = dict(COSTS[cost]) if isinstance(cost, str) else dict(cost)
    entry = c.pop("entry", None)
    v = E.variant(name=name, start=ms("2021-01-01") if start is None else int(start),
                  end=DATA_END if end is None else int(end), **c, **kw)
    if entry and "entry" not in kw:
        v["entry"] = entry
    v["cost"] = cost if isinstance(cost, str) else "custom"
    return v


def run(members, start=None, end=None, cost="paper", name="run", data_end=None, oct_mark="mark", verbose=False,
        judge="J4", **kw):
    """members: member dicts / labels. start / end: signal bar closes [start, end) (ms). data_end: the 1m data end
    (default DATA_END: positions open at the end close there, reason END). Returns (trades, cand, info)."""
    t_start = time.time()
    v = make_variant(name, start, end, cost, **kw)
    v["judge"] = judge
    specs = resolve(members)
    mk = markets(data_end, oct_mark)
    sig = load_member_signals(specs, v["start"], v["end"])
    cand, rules = candidates(v, sig, mk, specs)
    lad = ComboLadder.of(v["ladder"])
    P = {"slip": v["slip"], "rt": 2 * (v["taker"] + v["slip"]), "ladder": lad, "stop_roe": v["stop_roe"],
         "taker": v["taker"], "maker": v["maker"], "funding": v["funding"]}
    rev = {}
    if v["early_exit"]:
        for (lab, coin, side), g in sig.groupby(["label", "symbol", "side"]):
            rev[(lab, coin, int(side))] = np.sort(g.bar_close.to_numpy(np.int64))
    ok = cand[cand.stage == "entered?"].copy().sort_values("entry_t") if len(cand) else cand
    records = defaultdict(list)          # (strategy, tf) -> [(exit minute idx, pnl)] oldest first (trendbot._record_of)
    trades = []
    pos_exit = -1
    stage = {}
    maker = v["entry"] == "maker"
    for et, g in (ok.groupby("entry_t", sort=True) if len(ok) else []):
        et = int(et)
        ei = (et - T0) // MIN
        if ei <= pos_exit:
            for ix in g.index:
                stage[ix] = "x_skip_in_position"
            continue
        best, best_key = None, None
        for ix, r in g.iterrows():
            t0i = (int(r.t0) - T0) // MIN
            rec = [p for (xi, p) in reversed(records[(r["name"], r.tf)]) if xi < t0i][:rules.record_n]
            form = (sum(1 for p in rec if p > 0) / len(rec) - 0.5) if len(rec) >= rules.record_min else 0.0
            key = (-(r.score_base + form), -TF_MIN[r.tf], r.order, PRI.index(r.coin), r["name"], r.tf)
            if best_key is None or key < best_key:
                best, best_key = ix, key
        for ix in g.index:
            stage[ix] = "x_skip_lower_score" if ix != best else "entered"
        r = g.loc[best]
        coin, side, tf = r.coin, int(r.side), r.tf
        M = mk[coin]
        lev = E.lev_of(v, coin)
        evs = []
        htf = HTF_OF[tf]
        ft = M.flip_times(htf, vm_of(v))[-side]
        j = np.searchsorted(ft, et, side="right")
        if j < len(ft):
            evs.append((int(ft[j]), "JUDGE"))
        if v["early_exit"]:
            rt_ = rev.get((r.label, coin, -side))
            if rt_ is not None:
                j = np.searchsorted(rt_, et, side="right")
                if j < len(rt_):
                    evs.append((int(rt_[j]), "REV"))
        if v["time_bars"]:
            evs.append((et + v["time_bars"] * TF_MS[tf], "TIME"))
        pri = {"TIME": 0, "JUDGE": 1, "REV": 2}
        evs.sort(key=lambda z: (z[0], pri[z[1]]))
        ev_t, ev_kind = (evs[0] if evs else (None, None))
        ev_i = (ev_t - T0) // MIN if ev_t is not None else None
        if ev_i is not None and ev_i >= M.n:
            ev_i = None                                      # after the data end: no event inside the data
        out = E.simulate_position(M, side, ei, float(r.entry_ref), lev, ev_i, P, maker)
        opp = E.simulate_position(M, -side, ei, float(r.entry_ref), lev, ev_i, P, maker)
        for o_ in (out, opp):
            if o_["reason"] == "EVENT":
                o_["reason"] = ev_kind
        pos_exit = out["x"]
        records[(r["name"], r.tf)].append((out["x"], out["roe"]))
        trades.append({"entry_t": et, "t0": int(r.t0), "label": r.label, "coin": coin, "side": side, "tf": tf,
                       "lev": lev, "ref": float(r.entry_ref), "level": float(r.level), "strength": int(r.strength),
                       "exit_t": T0 + out["x"] * MIN, **{k: out[k] for k in ("reason", "lock", "roe", "pre", "slip_cost",
                                                                          "fee", "fund", "mfe_roe", "X_ref")},
                       "opp_roe": opp["roe"], "opp_reason": opp["reason"], "opp_pre": opp["pre"],
                       "opp_exit_t": T0 + opp["x"] * MIN})
    for ix, s in stage.items():
        cand.at[ix, "stage"] = s
    T = pd.DataFrame(trades, columns=None if trades else ["entry_t", "t0", "label", "coin", "side", "tf", "lev", "ref",
                                                         "level", "strength", "exit_t", "reason", "lock", "roe", "pre",
                                                         "slip_cost", "fee", "fund", "mfe_roe", "X_ref", "opp_roe",
                                                         "opp_reason", "opp_pre", "opp_exit_t"])
    info = {"variant": {k: (x if k != "ladder" else dict(x)) for k, x in v.items()},
            "members": [{k: s[k] for k in ("label", "order", "breakout", "when_raw")} for s in specs],
            "data_end": int(mk[COINS[0]].n * MIN + T0), "oct_mark": oct_mark,
            "elapsed_s": round(time.time() - t_start, 2), "n_signals": int(len(sig)), "n_trades": int(len(T)),
            "funnel": funnel(cand)}
    if verbose:
        print(f"{name}: {len(sig)} signals, {len(T)} trades, {info['elapsed_s']}s", flush=True)
    return T, cand, info


STAGES = ["when", "data_end", "block", "nojudge", "check", "no_pullback", "block_at_entry", "in_position",
          "lower_score", "entered"]


def funnel(cand):
    """Signal -> entry counts: total and per member (the stage of each signal, analyze.funnel's names)."""
    if not len(cand):
        return {"total": {}, "by_member": {}, "blocks": {}, "checks": {}}
    st = cand.stage.fillna("")
    s = np.select([st.str.startswith("x_when"), st.str.startswith("x_data_end"), st.str.startswith("x_block:"),
                   st.str.startswith("x_nojudge"), st.str.startswith("x_check"), st.str.startswith("x_no_pullback"),
                   st.str.startswith("x_block_at_entry"), st.str.startswith("x_skip_in_position"),
                   st.str.startswith("x_skip_lower"), st == "entered"], STAGES, "other")
    c = cand.assign(s=s)
    out = {"total": {k: int(x) for k, x in c.s.value_counts().items()},
           "by_member": {lab: {k: int(x) for k, x in g.s.value_counts().items()} for lab, g in c.groupby("label")},
           "blocks": {k: int(x) for k, x in st[st.str.startswith("x_block:")].str.split(":").str[1].value_counts().items()}}
    if "why" in c:
        w = c.why.dropna().str.extract(r"^([^(]*)")[0].str.strip()
        out["checks"] = {k: int(x) for k, x in w.value_counts().head(20).items()}
    return out


# ====================================================================== the coin-flip twin (analyze.py)
def prep(T):
    T = T.sort_values("entry_t").reset_index(drop=True).copy()
    T["g"] = 1 + MARGIN * T.roe
    T["opp_g"] = 1 + MARGIN * T.opp_roe
    dt = pd.to_datetime(T.entry_t, unit="ms", utc=True)
    T["year"] = dt.dt.year
    T["half"] = dt.dt.year.astype(str) + np.where(dt.dt.month <= 6, "H1", "H2")
    T["win"] = T.roe > 0
    return T


def periods(start, end):
    """Calendar years and half-years inside [start, end) (clipped)."""
    ys, hs = [], []
    y0, y1 = pd.Timestamp(start, unit="ms").year, pd.Timestamp(end - 1, unit="ms").year
    for y in range(y0, y1 + 1):
        a, b = max(start, ms(f"{y}-01-01")), min(end, ms(f"{y + 1}-01-01"))
        if a < b:
            ys.append((str(y), a, b))
        for h, (m0, m1) in (("H1", (f"{y}-01-01", f"{y}-07-01")), ("H2", (f"{y}-07-01", f"{y + 1}-01-01"))):
            a, b = max(start, ms(m0)), min(end, ms(m1))
            if a < b:
                hs.append((f"{y}{h}", a, b))
    return ys, hs


def twin(T, draws=1000, seed=SEED, start=None, end=None, halves=True, extra=None):
    """analyze.block on the trades (same entries, side drawn at random, ``draws`` draws, numpy default_rng(seed)):
    {"all", "years", "halves"} with the bot's numbers and its rank against the twin. ``extra``: {name: (a, b)}."""
    import analyze as A
    A.NDRAW, A.SEED = int(draws), int(seed)
    T = prep(T)
    start = int(T.entry_t.min()) if start is None else int(start)
    end = int(T.entry_t.max()) + 1 if end is None else int(end)
    flip = A.draws(T)
    res = {"draws": int(draws), "seed": int(seed), "margin": MARGIN,
           "all": A.block(T, flip, (T.entry_t >= start) & (T.entry_t < end), start, end)}
    ys, hs = periods(start, end)
    res["years"] = {y: A.block(T, flip, (T.entry_t >= a) & (T.entry_t < b), a, b) for y, a, b in ys}
    if halves:
        res["halves"] = {h: A.block(T, flip, (T.entry_t >= a) & (T.entry_t < b), a, b) for h, a, b in hs}
    for k, (a, b) in (extra or {}).items():
        res[k] = A.block(T, flip, (T.entry_t >= a) & (T.entry_t < b), a, b)
    return res


# ====================================================================== CLI
def _arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def save(name, T, cand, info, tw=None):
    os.makedirs(RUNS, exist_ok=True)
    T.to_csv(f"{RUNS}/{name}_trades.csv.gz", index=False)
    cand[[c for c in ["t0", "label", "coin", "side", "tf", "stage", "entry_t", "why"] if c in cand]].to_csv(
        f"{RUNS}/{name}_cand.csv.gz", index=False)
    json.dump({**info, "twin": tw}, open(f"{RUNS}/{name}_info.json", "w"), indent=1, default=str)


def main():
    mode = sys.argv[1]
    compat = "--compat" in sys.argv
    start = ms(_arg("--start", "2021-01-01"))
    end = ms(_arg("--end")) if _arg("--end") else (ms("2026-10-01") if compat else DATA_END)
    cost = _arg("--cost", "paper")
    draws = int(_arg("--draws", "0"))
    quiet = "--quiet" in sys.argv
    if mode == "current":
        members = current_members()
    elif mode == "solo":
        lab = sys.argv[2]
        brk = True if "--breakout" in sys.argv else (False if "--no-breakout" in sys.argv else None)
        ws = _arg("--when-side")
        members = [{"label": lab, "breakout": brk, "when": [{"side": ws}] if ws else None}]
    elif mode == "basket":
        members = json.load(open(sys.argv[2]))["members"]
    else:
        raise SystemExit(__doc__)
    t0 = time.time()
    data_end = T_FY_END if compat else None
    T, cand, info = run(members, start, end, cost, name=_arg("--save", mode), data_end=data_end,
                        oct_mark="last" if compat else "mark", judge=_arg("--judge", "J4"))
    t1 = time.time()
    tw = twin(T, draws, start=start, end=end) if (draws and len(T)) else None
    t2 = time.time()
    if _arg("--save"):
        save(_arg("--save"), T, cand, info, tw)
    if quiet:
        print(json.dumps({"run_s": round(t1 - t0, 2), "twin_s": round(t2 - t1, 2), "draws": draws}))
        return
    print(json.dumps({"members": info["members"], "n_signals": info["n_signals"], "n_trades": info["n_trades"],
                      "funnel_total": info["funnel"]["total"], "run_s": round(t1 - t0, 2), "twin_s": round(t2 - t1, 2)},
                     indent=1, default=str))


if __name__ == "__main__":
    main()
