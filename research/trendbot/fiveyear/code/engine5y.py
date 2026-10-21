"""Five-year replay of the 추세판단 봇 (deploy/combo.trend.json) on the verified Binance USD-M 1m bars, event-driven but
with the minute order of the live engine (paperbot/combo.py + paperbot/trendbot.py; the order of the earlier
minute-by-minute replay, entryrate/code/simulate.py, which matched the live engine on 7/1-10/20):

  per minute ts: (1) the member signals whose bar closed at ts: when -> entry block (weekend, macro, NYSE open, chase)
  -> trend check (trendjudge.check on the last closed higher bar) -> pullback wait; every signal is an early-exit
  candidate; then the pulled entries due at ts (entry block again at the entry minute); (2) supervisor (TIME / JUDGE,
  before the first lock); (3) engine: supervisor close at the open, else REV close at the open (own member, same
  coin, other side, bar closed after the entry, before the first lock); funding (position held over the open);
  entries (one position; rank score > timeframe > order > coin); exit checks of the 1m bar (open gap, stop / lock,
  stop first inside the bar, the new lock from the next bar, no lock on the entry bar); (4) pullback touches ->
  entry the next minute.

The pullback waits do not depend on the position (they wait and touch with or without a position, as live), so the
candidates are built once; the position is simulated in vectorised chunks of 1m bars from its entry to its exit.
The repo's own functions decide: trendjudge.check / score / Judgment / Spot / TrendRules, ladder2.ComboLadder,
ladder.net_roe / roe_price, combo.kst_weekend / us_open_pause / chase_check (checked against the array form),
margin.liquidation_price. The judge and spot values are the full-series arrays of judge5y.py (equal to the live
300-bar frames on every sampled bar).

A run: run(variant dict) -> (trades DataFrame, candidates DataFrame, info). Each trade carries the outcome of the
same entry with the OTHER side too (same entry minute and price, same supervisor / REV events, which follow the
bot's judged direction as the live coin-flip twin's JUDGE does), so coin-flip twins are draws over those two."""
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fycommon import *
import bisect, copy, math, time, warnings
from collections import defaultdict

from paperbot import combo as C
from paperbot.trendjudge import HTF_OF, JUDGES, Judgment, Spot, TrendRules, check, score
from paperbot.ladder2 import ComboLadder
from paperbot.margin import BracketTier, liquidation_price

CFG = json.load(open(f"{REPO}/deploy/combo.trend.json"))
PRI = list(C.V3_SYMBOLS)
TF_MIN = {"30m": 30, "1h": 60}
MMR = BracketTier(50_000, 50, 0.005, 0.0)        # Brackets.example() first tier (live: Binance's table; liq only on gaps)
EPS = 1e-9


def macro_events(hist=True):
    """FOMC + NFP 2020-2026 (research/hunt/macro_calendar.json, the repo's historical calendar; hist) and the live file
    data/macro_events.csv (2026-10..12, CPI / PCE too). CPI and PCE before 2026-10 are not in the repo."""
    t = [int(e["t_ms"]) for e in json.load(open(f"{REPO}/research/hunt/macro_calendar.json"))["events"]] if hist else []
    from paperbot import events as EV
    evs, _ = EV.parse(open(f"{REPO}/data/macro_events.csv").read())
    t += [e.ts_ms for e in evs]
    return np.array(sorted(set(t)), dtype=np.int64)


MACRO = {"hist": macro_events(True), "csv": macro_events(False)}


def macro_near(ts, w, src="hist"):
    a = MACRO[src]
    lo = np.searchsorted(a, ts - w, side="left")
    hi = np.searchsorted(a, ts + w, side="right")
    return hi > lo


_USO = {}


def us_open(ts, mins, pre):
    k = (ts, mins, pre)
    v = _USO.get(k)
    if v is None:
        v = bool(C.us_open_pause(ts, mins, pre))
        _USO[k] = v
    return v


# ====================================================================== market data
class Market:
    def __init__(self, coin, with_oct=True):
        self.coin = coin
        m = load_grid(coin, with_oct=with_oct)
        self.n = m["n"]
        self.first = m["first"]
        for k in ("o", "h", "l", "c", "mo", "mh", "ml", "fund"):
            setattr(self, k, m[k])
        # chase windows on hourly high / low (hours k-24 .. k-1 and k-168 .. k-1 before the hour of the bar close)
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
        z = np.load(f"{OUT}/judge/{coin}.npz")
        self.J = {k: z[k] for k in z.files}

    def i(self, ts):
        return (int(ts) - T0) // MIN

    # -- chase (combo.chase_check on the array form)
    def chase(self, bar_close, side, price):
        k = int(bar_close) // HOUR - T0 // HOUR
        hi24, lo24, n24 = self.r24[0][k], self.r24[1][k], self.r24[2][k]
        if not (n24 >= C.CHASE_24H_MIN):
            return None
        p24 = (price - lo24) / max(hi24 - lo24, 1e-12)
        if side > 0 and p24 >= C.CHASE_24H_HI:
            return True
        if side < 0 and p24 <= C.CHASE_24H_LO:
            return True
        hi7, lo7, n7 = self.r7[0][k], self.r7[1][k], self.r7[2][k]
        if n7 >= C.CHASE_7D_MIN:
            p7 = (price - lo7) / max(hi7 - lo7, 1e-12)
            if side > 0 and p7 >= C.CHASE_7D_HI:
                return True
            if side < 0 and p7 <= C.CHASE_7D_LO:
                return True
        return False

    def chase_repo(self, bar_close, side, price):
        """combo.chase_check itself (for the check of the array form)."""
        k = int(bar_close) // HOUR - T0 // HOUR
        hh, ll, have = self.hours_raw
        hours = {T0 // HOUR + j: (float(hh[j]), float(ll[j])) for j in range(max(0, k - C.CHASE_7D), k) if have[j]}
        return C.chase_check(hours, bar_close, side, price)[0]

    # -- judge / spot
    def bar_index(self, tf, t):
        """Index of the tf bar that closed at the boundary at or before t."""
        ms_ = TF_MS[tf]
        close = int(t) - int(t) % ms_
        c0 = int(self.J[f"{tf}_tclose"][0])
        return (close - c0) // ms_

    def judgment(self, tf, t, rules, vm):
        k = self.bar_index(tf, t)
        if k < 120 or k >= len(self.J[f"{tf}_tclose"]):
            return None
        J = self.J
        raw = J[f"{tf}_raw{vm}"]
        hold = rules.hold(tf)
        held = tuple(int(x) for x in raw[k - hold + 1:k + 1])
        r = int(raw[k])
        d = r if (r != 0 and len(held) == hold and all(h == r for h in held)) else 0
        adx, adx_prev = float(J[f"{tf}_adx"][k]), float(J[f"{tf}_adx"][k - 1])
        close, ema20, atr = float(J[f"{tf}_close"][k]), float(J[f"{tf}_ema20"][k]), float(J[f"{tf}_atr"][k])
        if not all(math.isfinite(v) for v in (adx, adx_prev, close, ema20, atr)) or not atr > 0:
            return None
        return Judgment(symbol=self.coin, tf=tf, bar_close=int(J[f"{tf}_tclose"][k]), votes={v: int(J[f"{tf}_{v}"][k]) for v in JUDGES},
                        raw=r, dir=d, held=held, adx=adx, adx_prev=adx_prev, close=close, ema20=ema20, atr=atr)

    def spot(self, tf, t):
        k = self.bar_index(tf, t)
        if k < 120 or k >= len(self.J[f"{tf}_tclose"]):
            return None
        J = self.J
        v = (float(J[f"{tf}_s_close"][k]), float(J[f"{tf}_s_ema20"][k]), float(J[f"{tf}_s_atr"][k]),
             float(J[f"{tf}_s_rsi"][k]), float(J[f"{tf}_s_range"][k]))
        if not all(math.isfinite(x) for x in v) or not v[2] > 0:
            return None
        return Spot(tf=tf, bar_close=int(J[f"{tf}_tclose"][k]), close=v[0], ema20=v[1], atr=v[2], rsi=v[3], range=v[4])

    def flip_times(self, tf, vm):
        """{+1: bar closes with raw +1, -1: with raw -1} (the supervisor's JUDGE reads raw of each closed bar)."""
        key = f"_ft_{tf}_{vm}"
        if not hasattr(self, key):
            raw = self.J[f"{tf}_raw{vm}"]
            cl = self.J[f"{tf}_tclose"]
            setattr(self, key, {1: cl[raw == 1].astype(np.int64), -1: cl[raw == -1].astype(np.int64)})
        return getattr(self, key)


MK = {}


def markets(with_oct=True):
    if not MK:
        for c in COINS:
            MK[c] = Market(c, with_oct)
    return MK


# ====================================================================== variants
BASE = {
    "name": "D0_current",
    "time_bars": None,               # TIME exit off (owners 10-21 night)
    "vote_min": 3,
    "entry": "pullback",             # "pullback" | "immediate" | "maker"
    "lev": {"BTCUSDT": 40, "default": 30},
    "stop_roe": 0.5,
    "ladder": dict(CFG["ladder"]),
    "taker": 0.0005, "slip": 0.0002, "maker": 0.0002,
    "funding": True,
    "us_open_pause": 30, "us_open_pre": 30, "macro_min": 30, "macro": "hist", "no_weekend": True,
    "start": ms("2021-01-01"), "end": ms("2026-10-01"),       # signal bar closes in [start, end)
    "early_exit": True,
}


def variant(**kw):
    v = copy.deepcopy(BASE)
    for k, x in kw.items():
        if k == "ladder":
            v["ladder"].update(x)
        else:
            v[k] = x
    return v


def lev_of(v, coin):
    return int(v["lev"].get(coin, v["lev"]["default"]))


# ====================================================================== members / signals
MEMBERS = {}
for _i, _m in enumerate(CFG["members"], 1):
    MEMBERS[f"{_m['strategy']}@{_m['tf']}"] = {"name": _m["strategy"], "tf": _m["tf"], "order": _i,
                                              "when_side": -1 if _m.get("when") else None}
assert [m.get("when") for m in CFG["members"]].count(None) == 9


def load_signals(start, end):
    s = pd.read_csv(f"{OUT}/signals5y.csv")
    s = s[(s.bar_close >= start) & (s.bar_close < end)]
    s["label"] = s.member + "@" + s.tf
    s = s[s.label.isin(MEMBERS)]
    return s.sort_values(["bar_close", "tf", "member", "symbol"]).reset_index(drop=True)


# ====================================================================== candidates (independent of the position)
def candidates(v, sig, mk):
    rules = TrendRules.from_dict({**CFG["trend"], "vote_min": v["vote_min"], "time_bars": v["time_bars"]})
    W = v["macro_min"] * MIN

    def block(ts, coin, side, bar_close, price):
        if v["no_weekend"] and C.kst_weekend(ts):
            return "weekend"
        if W and macro_near(ts, W, v["macro"]):
            return "macro"
        if (v["us_open_pause"] or v["us_open_pre"]) and us_open(ts, v["us_open_pause"], v["us_open_pre"]):
            return "us_open"
        ch = mk[coin].chase(bar_close, side, price)
        if ch is None:
            return "chase_nodata"
        if ch:
            return "chase"
        return ""

    rows = []
    for r in sig.itertuples(index=False):
        m = MEMBERS[r.label]
        ts, coin, side, tf = int(r.bar_close), r.symbol, int(r.side), r.tf
        M = mk[coin]
        rec = {"t0": ts, "label": r.label, "coin": coin, "side": side, "tf": tf, "stage": "", "entry_t": None}
        if m["when_side"] is not None and side != m["when_side"]:
            rec["stage"] = "x_when"
            rows.append(rec)
            continue
        i0 = M.i(ts)
        price = float(M.o[i0])
        why = block(ts, coin, side, ts, price)
        if why:
            rec["stage"] = "x_block:" + why
            rows.append(rec)
            continue
        htf = HTF_OF[tf]
        j = M.judgment(htf, ts, rules, v["vote_min"])
        s = M.spot(tf, ts)
        if j is None or s is None:
            rec["stage"] = "x_nojudge"
            rows.append(rec)
            continue
        assert j.bar_close == ts - ts % TF_MS[htf] and s.bar_close == ts, (j.bar_close, s.bar_close, ts)
        why, info = check(rules, m["name"], tf, side, price, j, s)
        if why:
            rec["stage"] = "x_check"
            rec["why"] = why[:60]
            rows.append(rec)
            continue
        sc, parts = score(rules, side, j, s, price, [])
        rec.update(score_base=parts["strength"] + parts["spot"], level=float(info["level"]), big=bool(info["big_bar"]),
                   strength=int(j.strength(side)), order=m["order"], name=m["name"])
        until = ts + TF_MS[tf]
        a, b = i0 + 1, M.i(until - MIN)                   # touch minutes t0+1 .. until-2 (b exclusive)
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
                et, ref = T0 + k * MIN, lvl                  # filled inside minute k at the level
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
    return pd.DataFrame(rows), rules


# ====================================================================== the position
def lock_vec(lad, best):
    """ComboLadder.lock_for on an array (-inf = no lock)."""
    out = np.full(best.shape, -np.inf)
    ok = best >= lad.first_trigger - 1e-12
    if not lad.two_part:
        n = np.floor((best - lad.first_trigger) / lad.step + EPS)
        out[ok] = (lad.first_lock + lad.step * n)[ok]
        return out
    lo = ok & ~(best >= lad.next_trigger - 1e-12)
    out[lo] = lad.first_lock
    hi = best >= lad.next_trigger - 1e-12
    n = np.floor((best - lad.next_trigger) / lad.step + EPS)
    out[hi] = (lad.next_trigger - lad.next_gap + lad.step * n)[hi]
    return out


def simulate_position(M, side, e, ref, lev, ev_i, P, maker_entry=False):
    """One position from entry minute index e (fill at ref*(1+side*slip), or at ref for a maker entry) until its exit.
    ev_i: minute index of the first supervisor / REV event (None: none). Margin normalised to 1 (ROE = P&L)."""
    slip, rt, lad = P["slip"], P["rt"], P["ladder"]
    fee_in_rate = P["maker"] if maker_entry else P["taker"]
    fill = ref if maker_entry else ref * (1 + side * slip)
    Q = lev / fill                       # margin 1 -> notional lev
    N = Q * fill
    fee_in = N * fee_in_rate
    dist = ref * (P["stop_roe"] / lev - rt)
    stop0 = ref - side * dist
    a = e
    cumF0 = 0.0
    lock_prev = -np.inf
    stop_prev = stop0
    mfe_prev = fill
    CH = 2880
    while True:
        b = min(a + CH, M.n)
        if a >= b:
            # data end: close at the last close
            x = M.n - 1
            X = float(M.c[x]) * (1 - side * slip)
            return _finish(side, Q, fill, ref, lev, X, float(M.c[x]), x, "END", lock_prev, cumF0, fee_in, P, mfe_prev)
        o, h, l = M.o[a:b], M.h[a:b], M.l[a:b]
        mo, mh, ml = M.mo[a:b], M.mh[a:b], M.ml[a:b]
        idx = np.arange(a, b)
        pay = side * Q * mo * M.fund[a:b] if P["funding"] else np.zeros(b - a)
        pay = np.where(idx > e, pay, 0.0)
        cumF = cumF0 + np.cumsum(pay)
        ff = cumF / N
        hx, lx = h, l
        if maker_entry and a == e:                     # filled inside minute e: its range may predate the fill
            hx, lx = h.copy(), l.copy()
            hx[0] = lx[0] = fill
        if side > 0:
            mfe = np.maximum.accumulate(np.maximum(hx, mfe_prev))
        else:
            mfe = np.minimum.accumulate(np.minimum(lx, mfe_prev))
        best = lev * (side * (mfe / fill - 1) - rt - ff)
        cand = lock_vec(lad, best)
        cand = np.where(idx > e, cand, -np.inf)
        lockmax = np.maximum.accumulate(np.maximum(cand, lock_prev))
        prevlock = np.concatenate([[lock_prev], lockmax[:-1]])
        rise = lockmax > prevlock + 1e-12
        stop_c = np.where(rise, fill * (1 + side * (lockmax / lev + rt + ff)), np.nan)
        if side > 0:
            stop_after = np.fmax.accumulate(np.where(np.isnan(stop_c), -np.inf, stop_c))
            stop_after = np.maximum(stop_after, stop_prev)
        else:
            stop_after = np.fmin.accumulate(np.where(np.isnan(stop_c), np.inf, stop_c))
            stop_after = np.minimum(stop_after, stop_prev)
        stop_eff = np.concatenate([[stop_prev], stop_after[:-1]])
        lock_eff = prevlock                            # lock in force during minute k (set by k-1)
        marg = 1.0 - cumF
        # liquidation price with the margin after funding: LP = (WB + cum - side*Q*EP) / (Q*mmr - side*Q)
        liq = (marg + MMR.cum - side * Q * fill) / (Q * MMR.mmr - side * Q)
        liq = np.maximum(liq, 0.0)
        later = idx > e
        gap_liq = later & ((mo - liq) * side <= 0)
        gap_stop = later & ((o - stop_eff) * side <= 0)
        hit = (l <= stop_eff) if side > 0 else (h >= stop_eff)
        hit_liq = (ml <= liq) if side > 0 else (mh >= liq)
        any_exit = gap_liq | gap_stop | hit | hit_liq
        ks = np.flatnonzero(any_exit)
        k_s = int(idx[ks[0]]) if len(ks) else None
        # supervisor / REV event at the open of ev_i, before the first lock
        if ev_i is not None and a <= ev_i < b and (k_s is None or ev_i <= k_s):
            j = ev_i - a
            if lock_eff[j] == -np.inf:
                X_ref = float(o[j])
                F = float(cumF[j - 1]) if j > 0 else cumF0          # no funding at the event minute (closed first)
                return _finish(side, Q, fill, ref, lev, X_ref * (1 - side * slip), X_ref, ev_i, "EVENT", -np.inf, F,
                               fee_in, P, float(mfe[j - 1]) if j > 0 else mfe_prev)
        if k_s is not None:
            j = k_s - a
            lk = lock_eff[j]
            reason = "LOCK" if lk > -np.inf else "SL"
            F = float(cumF[j])
            if gap_liq[j]:
                return _finish(side, Q, fill, ref, lev, None, float(o[j]), k_s, "LIQ", lk, F, fee_in, P, float(mfe[j]))
            if gap_stop[j]:
                X_ref = float(o[j])
                return _finish(side, Q, fill, ref, lev, X_ref * (1 - side * slip), X_ref, k_s, reason, lk, F, fee_in,
                               P, float(mfe[j]), at_open=True)
            if hit[j]:
                X_ref = float(stop_eff[j])
                return _finish(side, Q, fill, ref, lev, X_ref * (1 - side * slip), X_ref, k_s, reason, lk, F, fee_in,
                               P, float(mfe[j]))
            return _finish(side, Q, fill, ref, lev, None, float(liq[j]), k_s, "LIQ", lk, F, fee_in, P, float(mfe[j]))
        cumF0, lock_prev, stop_prev, mfe_prev = float(cumF[-1]), float(lockmax[-1]), float(stop_after[-1]), float(mfe[-1])
        a = b


def _finish(side, Q, fill, ref, lev, X, X_ref, x, reason, lock, F, fee_in, P, mfe, at_open=False):
    if X is not None:
        gross = side * Q * (X - fill)
    if X is None or gross < -(1.0 - F):
        # isolated margin: liquidation loses the (funding-reduced) margin: engine net = -margin - fee_in - funding
        net = -(1.0 - F) - fee_in - F
        return {"x": x, "X": X_ref, "X_ref": X_ref, "reason": "LIQ", "lock": None if lock == -np.inf else lock,
                "roe": net, "pre": lev * side * (X_ref / ref - 1), "slip_cost": np.nan, "fee": fee_in, "fund": F,
                "mfe_roe": lev * side * (mfe / fill - 1)}
    fee_out = Q * X * P["taker"]
    net = gross - fee_in - fee_out - F
    pre = lev * side * (X_ref / ref - 1)
    return {"x": x, "X": X, "X_ref": X_ref, "reason": reason, "lock": None if lock == -np.inf else float(lock),
            "roe": net, "pre": pre, "slip_cost": pre - gross, "fee": fee_in + fee_out, "fund": F,
            "mfe_roe": lev * side * (mfe / fill - 1), "at_open": at_open}


# ====================================================================== the run
def run(v, verbose=True, sig=None, cand=None):
    """cand: candidates() output of the same entry rules (vote_min, entry, pauses), reused across exit variants."""
    t_start = time.time()
    mk = markets()
    if sig is None:
        sig = load_signals(v["start"], v["end"])
    if cand is None:
        cand, rules = candidates(v, sig, mk)
    else:
        cand, rules = cand[0].copy(), cand[1]
    lad = ComboLadder.of(v["ladder"])
    P = {"slip": v["slip"], "rt": 2 * (v["taker"] + v["slip"]), "ladder": lad, "stop_roe": v["stop_roe"],
         "taker": v["taker"], "maker": v["maker"], "funding": v["funding"]}
    # early-exit candidates: every member signal, by (label, coin, side)
    rev = {}
    if v["early_exit"]:
        for (lab, coin, side), g in sig.groupby(["label", "symbol", "side"]):
            rev[(lab, coin, int(side))] = np.sort(g.bar_close.to_numpy(np.int64))
    ok = cand[cand.stage == "entered?"].copy()
    ok = ok.sort_values("entry_t")
    groups = ok.groupby("entry_t", sort=True)
    records = defaultdict(list)          # label -> [(exit minute idx, pnl)] oldest first
    trades = []
    pos_exit = -1                        # minute index of the open position's exit (entries need a later minute)
    stage = {}
    maker = v["entry"] == "maker"
    for et, g in groups:
        et = int(et)
        ei = (et - T0) // MIN
        if ei <= pos_exit:
            for ix in g.index:
                stage[ix] = "x_skip_in_position"
            continue
        # score with the member's record as it stood at the signal minute
        best, best_key = None, None
        for ix, r in g.iterrows():
            t0i = (int(r.t0) - T0) // MIN
            rec = [p for (xi, p) in reversed(records[r.label]) if xi < t0i][:rules.record_n]
            form = (sum(1 for p in rec if p > 0) / len(rec) - 0.5) if len(rec) >= rules.record_min else 0.0
            key = (-(r.score_base + form), -TF_MIN[r.tf], r.order, PRI.index(r.coin), r["name"], r.tf)
            if best_key is None or key < best_key:
                best, best_key = ix, key
        for ix in g.index:
            stage[ix] = "x_skip_lower_score" if ix != best else "entered"
        r = g.loc[best]
        coin, side, tf = r.coin, int(r.side), r.tf
        M = mk[coin]
        lev = lev_of(v, coin)
        # events relative to the bot's direction (side): JUDGE on the higher bar, REV of the own member, TIME
        evs = []
        htf = HTF_OF[tf]
        ft = M.flip_times(htf, v["vote_min"])[-side]
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
        # priority at the same minute: TIME, then JUDGE (supervisor), then REV
        pri = {"TIME": 0, "JUDGE": 1, "REV": 2}
        evs.sort(key=lambda z: (z[0], pri[z[1]]))
        ev_t, ev_kind = (evs[0] if evs else (None, None))
        ev_i = (ev_t - T0) // MIN if ev_t is not None else None
        out = simulate_position(M, side, ei, float(r.entry_ref), lev, ev_i, P, maker)
        opp = simulate_position(M, -side, ei, float(r.entry_ref), lev, ev_i, P, maker)
        for o_ in (out, opp):
            if o_["reason"] == "EVENT":
                o_["reason"] = ev_kind
        pos_exit = out["x"]
        records[r.label].append((out["x"], out["roe"]))
        trades.append({"entry_t": et, "t0": int(r.t0), "label": r.label, "coin": coin, "side": side, "tf": tf,
                       "lev": lev, "ref": float(r.entry_ref), "level": float(r.level), "strength": int(r.strength),
                       "exit_t": T0 + out["x"] * MIN, **{k: out[k] for k in ("reason", "lock", "roe", "pre", "slip_cost",
                                                                          "fee", "fund", "mfe_roe", "X_ref")},
                       "opp_roe": opp["roe"], "opp_reason": opp["reason"], "opp_pre": opp["pre"],
                       "opp_exit_t": T0 + opp["x"] * MIN})
    for ix, s in stage.items():
        cand.at[ix, "stage"] = s
    T = pd.DataFrame(trades)
    info = {"variant": {k: (x if k != "ladder" else dict(x)) for k, x in v.items()}, "elapsed_s": round(time.time() - t_start, 1),
            "n_signals": int(len(sig)), "n_trades": int(len(T))}
    if verbose:
        print(f"{v['name']}: {len(sig)} signals, {len(T)} trades, {info['elapsed_s']}s", flush=True)
    return T, cand, info
