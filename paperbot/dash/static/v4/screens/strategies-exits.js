// 매매법 상세: 어떻게 끝났나 (batch ana8A). The strategy's closed trades (already loaded from /api/account, at most the
// last 500 per timeframe account) split by how they ended: the exit reason (house exits: 손절 / 잠금 +N% per lock_roe step /
// 강제청산; the reel: 손절 / 윗밴드 익절 / 시간), the leverage the sizing actually gave, 평일·주말, the funding window (±10 min of
// 00/08/16 UTC) and the US stock open (±60 min of 09:30 New York, weekdays). The windows are paperbot/sessions.py's,
// ported below (tests/test_dash_ana8a.py checks the port against Python's zoneinfo).
// Under the exit split: the 5-year reference. The 36: the card's lock share (sized with the v3 rules, every signal from
// 50x, so the share is not the v4 one; the card says so). The reel: its study's exit mix per period (the same exits as
// live; /api/profile rows[].periods[].exit_reason_pct). DeepSeek: none (its study used other exits).
// HONESTY: descriptive only (no pass / fail words); small cells say 표본 적음; DeepSeek shows counts, never money; money
// rows carry assume().
import {h, put, ui, fmt, motion, local} from "../core/pb.js";

const DAY = 86400000;
const MIN_ROWS = 10;                 // a cell under 10 trades: 표본 적음 (the split card's floor)
const LOCK_TOP = 30;                 // lock steps from +30% up share one row

// ---------------------------------------------------------------- time windows (paperbot/sessions.py, ported)
function nthSunday(y, m, n) {        // day of month of the n-th Sunday (m: 0-based month)
  const first = new Date(Date.UTC(y, m, 1)).getUTCDay();
  return 1 + ((7 - first) % 7) + 7 * (n - 1);
}
/** New York's UTC offset in hours at ms: −4 from the second Sunday of March 07:00 UTC to the first Sunday of November
 *  06:00 UTC (the US rule since 2007), else −5. */
export function nyOffsetH(ms) {
  const y = new Date(ms).getUTCFullYear();
  const start = Date.UTC(y, 2, nthSunday(y, 2, 2), 7), end = Date.UTC(y, 10, nthSunday(y, 10, 1), 6);
  return ms >= start && ms < end ? -4 : -5;
}
/** sessions.time_features for one entry time: weekend in Korea time, the funding window, the US open window. */
export function timeWin(ms) {
  ms = Number(ms);
  const kwd = new Date(ms + 9 * 3600000).getUTCDay();
  const sec = Math.floor(ms / 1000) % 28800;                       // seconds since the last 00/08/16 UTC settlement
  const ny = ms + nyOffsetH(ms) * 3600000;
  const nwd = new Date(ny).getUTCDay();
  const tod = ((ny % DAY) + DAY) % DAY;                             // New York time of day, ms
  return {weekend: kwd === 0 || kwd === 6, funding: Math.min(sec, 28800 - sec) <= 600,
    usOpen: nwd !== 0 && nwd !== 6 && Math.abs(tod - 34200000) <= 3600000};
}

// ---------------------------------------------------------------- the split
const REEL_KO = {SL: "손절", TP: "윗밴드 익절", TIME: "시간 (96봉)", LIQ: "강제청산"};
/** How one trade ended: {key, ko, ord}. kind: the page's kind (strategy | ds200 | reel). */
export function exitKey(t, kind) {
  const r = String(t.exit_reason || "");
  if (kind === "reel") return {key: r, ko: REEL_KO[r] || fmt.reasonKo(r), ord: ["SL", "TP", "TIME", "LIQ"].indexOf(r) >>> 0};
  if (r === "SL") return {key: "SL", ko: "손절", ord: 0};
  if (r === "LOCK") {
    const s = Math.round(Number(t.lock_roe) * 100);
    if (!Number.isFinite(s) || t.lock_roe == null) return {key: "LOCK?", ko: "잠금 (단계 기록 없음)", ord: 99};
    if (s >= LOCK_TOP) return {key: "LOCK" + LOCK_TOP, ko: `잠금 +${LOCK_TOP}% 이상`, ord: LOCK_TOP};
    return {key: "LOCK" + s, ko: `잠금 +${s}%`, ord: s};
  }
  if (r === "LIQ") return {key: "LIQ", ko: "강제청산", ord: 200};
  return {key: r, ko: fmt.reasonKo(r), ord: 300};
}

/** Closed trades split five ways: {n, reason, lev, week, funding, usopen} -> [{key, ko, n, wins, losses, pnl, share, rate,
 *  r1x}] (r1x: the mean of ROE ÷ leverage, the per-trade net in 1x price %). trades: /api/account rows. */
export function splitExits(trades, kind) {
  const rows = (trades || []).filter((t) => t && t.exit_reason);
  const dims = {reason: new Map(), lev: new Map(), week: new Map(), funding: new Map(), usopen: new Map()};
  const add = (m, key, ko, ord, t) => {
    if (!m.has(key)) m.set(key, {key, ko, ord, n: 0, wins: 0, losses: 0, pnl: 0, r1: 0, r1n: 0});
    const c = m.get(key), pnl = Number(t.pnl) || 0, lev = Number(t.leverage), roe = Number(t.roe);
    c.n++; c.pnl += pnl;
    if (pnl > 0) c.wins++; else if (pnl < 0) c.losses++;
    if (lev > 0 && Number.isFinite(roe)) { c.r1 += roe / lev; c.r1n++; }
  };
  for (const t of rows) {
    const e = exitKey(t, kind);
    add(dims.reason, e.key, e.ko, e.ord, t);
    const lev = Number(t.leverage);
    if (lev > 0) add(dims.lev, String(Math.round(lev)), `${fmt.int(lev)}배`, -lev, t);
    if (t.entry_time != null) {
      const w = timeWin(t.entry_time);
      add(dims.week, w.weekend ? "end" : "day", w.weekend ? "주말 (토·일)" : "평일", w.weekend ? 1 : 0, t);
      add(dims.funding, w.funding ? "in" : "out", w.funding ? "펀딩 ±10분 안" : "그 밖", w.funding ? 0 : 1, t);
      add(dims.usopen, w.usOpen ? "in" : "out", w.usOpen ? "미국장 개장 ±60분 안" : "그 밖", w.usOpen ? 0 : 1, t);
    }
  }
  const n = rows.length;
  const fin = (m) => [...m.values()].sort((a, b) => a.ord - b.ord).map(({r1, r1n, ...c}) =>
    ({...c, share: n ? c.n / n : null, rate: c.n ? c.wins / c.n : null, r1x: r1n ? r1 / r1n : null}));
  return {n, reason: fin(dims.reason), lev: fin(dims.lev), week: fin(dims.week), funding: fin(dims.funding), usopen: fin(dims.usopen)};
}

/** The 36's live lock share per timeframe: {tf: {n, locks, share}}. byTf: {tf: [trades]}. */
export function lockShareByTf(byTf) {
  const out = {};
  for (const [tf, rows] of Object.entries(byTf || {})) {
    const done = (rows || []).filter((t) => t && t.exit_reason);
    const locks = done.filter((t) => t.exit_reason === "LOCK").length;
    out[tf] = {n: done.length, locks, share: done.length ? locks / done.length : null};
  }
  return out;
}

// ---------------------------------------------------------------- the card
const DIMS = [{id: "reason", label: "나간 이유"}, {id: "lev", label: "레버리지"}, {id: "week", label: "평일·주말"},
  {id: "funding", label: "펀딩 ±10분"}, {id: "usopen", label: "미국장 개장"}];
const HOW = {
  reason: {strategy: "손절 = 처음 손절선(2 ATR)에 닿아 나감. 잠금 +N% = 이익이 올라 옮겨 둔 잠금선(순 ROE +N%)에 닿아 나감.",
    ds200: "손절 = 처음 손절선(2 ATR)에 닿아 나감. 잠금 +N% = 이익이 올라 옮겨 둔 잠금선(순 ROE +N%)에 닿아 나감.",
    reel: "손절 = 하단 이탈 뒤 최저점 아래 손절선. 윗밴드 익절 = 볼린저 윗선에 닿음. 시간 = 96봉(8시간)이 지나 나감."},
  lev: {strategy: "실제로 받은 배수. 좋은 자리는 50배, 보통 자리는 30배부터 시작하고, 청산 거리·손실 한도에 걸리면 한 단계씩 내려갑니다.",
    ds200: "딥시크는 규칙상 늘 보통 자리(30배부터, 걸리면 20배).", reel: "5분봉은 규칙상 늘 보통 자리(30배부터, 걸리면 20배)."},
  week: "진입 시각 기준 (한국 시간). 주말 = 토·일.",
  funding: "진입이 펀딩 정산(한국 09·17·01시) 앞뒤 10분 안이었는지.",
  usopen: "진입이 미국 주식 개장(뉴욕 09:30, 평일) 앞뒤 60분 안이었는지. 서머타임을 따릅니다.",
};

/** exitsCard(ctx, {kind}) -> {el, trades(byTf), profile(p)}: the card; detail feeds it the loaded trades and the
 *  /api/profile answer. */
export function exitsCard(ctx, o = {}) {
  const kind = o.kind || "strategy";
  const money = kind !== "ds200";                                   // DeepSeek: counts only, never money
  const v = {dim: DIMS.some((d) => d.id === local.get("strat-exdim")) ? local.get("strat-exdim") : "reason", byTf: null, p: undefined};
  const seg = ui.seg(DIMS, v.dim, (id) => { v.dim = id; local.set("strat-exdim", id); render(true); }, {label: "끝난 모양 나눠 보기", scroll: true});
  const body = h("div", {class: "stack tight"}, motion.shimmer(3));
  const el = ui.card({plate: "어떻게 끝났나", sub: "끝난 거래 기준", cls: "strat-o5 strat-howend"}, seg, body);

  function row(c, dim) {
    const share = dim === "reason";
    const w = Math.round(((share ? c.share : c.rate) || 0) * 100) + "%";
    return h("div", {class: "strat-srow", role: "listitem"},
      h("span", {class: "nm2"}, c.ko),
      h("span", {class: "wl-bar", title: share ? `전체의 ${fmt.pct(c.share, 0, false)}` : `이긴 비율 ${fmt.pct(c.rate, 0, false)}`}, h("i", {style: {"--w": w}})),
      h("span", {class: "num small"}, share ? `${fmt.int(c.n)}건 · ${fmt.pct(c.share, 0, false)}` : `${fmt.int(c.wins)}승 ${fmt.int(c.losses)}패`),
      money ? h("b", {class: ["num", fmt.tone(c.pnl, fmt.money(c.pnl, true))]}, fmt.money(c.pnl, true))
        : h("span", {class: "num small muted"}, share ? "" : `${fmt.int(c.n)}건`),
      h("span", {class: "strat-sp"}, ui.smallSample(c.n, MIN_ROWS)));
  }

  function reference(sp) {
    const p = v.p;
    if (p === undefined) return [h("div", {class: "strat-exref"}, motion.shimmer(2))];
    if (kind === "ds200") return [h("p", {class: "muted small strat-exref"}, "5년 기준 없음: 딥시크 연구는 다른 청산(ATR 손절·익절, 추적 손절)으로 쟀기 때문에 나간 이유를 나란히 놓지 않습니다.")];
    if (!p || !(p.rows || []).length) return [h("p", {class: "muted small strat-exref"}, "5년 기준: 자료 없음.")];
    if (kind === "reel") {
      const live = {}; for (const c of sp.reason) live[c.key] = c.share;
      const keys = ["SL", "TP", "TIME"];
      const r0 = p.rows[0] || {}, per = r0.periods || {};
      const ko = Object.fromEntries((p.periods || []).map((x) => [x.key, x.ko]));
      const rows = [{k: sp.n ? `지금 (${fmt.int(sp.n)}건)` : "지금", now: true, v: (x) => (sp.n ? fmt.pct(live[x] || 0, 0, false) : "—")},
        ...Object.keys(per).filter((k) => per[k] && per[k].exit_reason_pct).map((k) =>
          ({k: `5년 ${ko[k] || k}`, v: (x) => fmt.pctOf(per[k].exit_reason_pct[x] || 0, 0)}))];
      return [h("div", {class: "strat-exref"},
        h("p", {class: "small"}, h("b", null, "5년 연구와 나란히"), h("span", {class: "muted"}, " · 연구와 라이브가 같은 릴스 청산")),
        ui.table([{label: "", l: true, get: (r) => (r.now ? h("b", null, r.k) : r.k)}, ...keys.map((x) => ({label: REEL_KO[x], get: (r) => r.v(x)}))], rows),
        sp.n < MIN_ROWS ? h("p", {class: "muted small"}, ui.smallSample(sp.n, MIN_ROWS), ` 지금은 ${fmt.int(sp.n)}건이라 비율이 크게 흔들립니다.`) : null)];
    }
    // the 36: the card's lock share, per timeframe, next to the live one
    const live = lockShareByTf(v.byTf);
    const rows = (p.rows || []).filter((r) => r.tf !== "5m").map((r) => ({tf: r.tf, y5: r.lock_share, now: live[r.tf] || {n: 0}}));
    return [h("div", {class: "strat-exref"},
      h("p", {class: "small"}, h("b", null, "잠금으로 나간 비율"), h("span", {class: "muted"}, " · 지금 vs 5년 시험")),
      ui.table([
        {label: "봉", l: true, get: (r) => fmt.tfKo(r.tf)},
        {label: "지금", get: (r) => (r.now.n ? h("span", null, fmt.pct(r.now.share, 0, false), h("span", {class: "muted"}, ` (${fmt.int(r.now.n)}건)`)) : h("span", {class: "muted"}, "아직 없음"))},
        {label: "5년 (v3 50배부터)", get: (r) => (r.y5 == null ? "—" : fmt.pct(r.y5, 0, false))}], rows),
      h("p", {class: "muted small"}, "5년 시험은 모든 신호를 50배부터 잡은 v3 크기 규칙입니다. 지금 보통 자리는 30배부터라 같은 가격 움직임에서 ROE가 작고, 잠금선(순 ROE +12%)에 덜 닿습니다. 그래서 이 비율은 설명용이고, 차이가 나도 실력 차이를 뜻하지 않습니다."))];
  }

  function render(animate) {
    if (!v.byTf) return;
    const all = Object.values(v.byTf).flat();
    const sp = splitExits(all, kind);
    const how = HOW[v.dim];
    const howText = typeof how === "string" ? how : how[kind] || how.strategy;
    const ref = v.dim === "reason" ? reference(sp) : [];
    if (!sp.n) {
      put(body, ui.empty(`아직 없음 · 끝난 거래가 ${MIN_ROWS}건쯤 쌓이면 어떻게 끝났는지 나눠 볼 만해집니다.`),
        h("p", {class: "muted small"}, howText), ...ref);
    } else {
      const rows = sp[v.dim] || [];
      put(body,
        h("p", {class: "muted small"}, `끝난 거래 ${fmt.int(sp.n)}건 (봉 계좌마다 최근 500건까지). ${howText}`),
        rows.length ? h("div", {class: "strat-split", role: "list"}, rows.map((c) => row(c, v.dim)))
          : h("p", {class: "muted"}, "이 기준으로 나눌 기록이 없습니다."),
        sp.n < MIN_ROWS ? h("p", {class: "muted small"}, ui.smallSample(sp.n, MIN_ROWS), ` 아직 ${fmt.int(sp.n)}건: ${MIN_ROWS}건 미만 칸은 결론 없이 참고만.`) : null,
        // the leverage tab: per-trade net in 1x price % (ROE ÷ leverage), the unit that compares across multiples
        v.dim === "lev" && rows.some((c) => c.r1x != null) ? h("p", {class: "muted small"}, "거래당 순손익 1배 환산 (ROE ÷ 레버리지): ",
          rows.filter((c) => c.r1x != null).map((c, i) => [i ? " · " : "", `${c.ko} `, h("span", {class: fmt.tone(c.r1x, fmt.pct(c.r1x, 2))}, fmt.pct(c.r1x, 2))])) : null,
        ...ref,
        money ? ui.assume() : h("p", {class: "muted small"}, "딥시크는 건수만 셉니다 (계좌 돈은 순위표의 묶음 숫자로)."));
    }
    if (animate) motion.swap(body);
  }

  return {
    el,
    /** byTf: {tf: [trades]} (the detail's v.trades). */
    trades(byTf) { v.byTf = byTf || {}; render(false); },
    /** p: the /api/profile answer (null when it failed). */
    profile(p) { v.p = p || null; render(false); },
  };
}
